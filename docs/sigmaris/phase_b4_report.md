# Phase B4 実施報告: 記憶の出所(provenance)トラッキング

**目的:** `user_fact_items`・`sigmaris_decision_log`・`sigmaris_experience`が「どの会話・どのターンから生まれたか」を一貫して追跡できるようにする。B1(ハイブリッド検索)の申し送り事項(検索ヒット経路の記録)にも可能な範囲で対応する。
**作業ブランチ:** `phase-b4-memory-provenance`(Phase A0〜A5・C-mini・JWT永続化・LLMRouter修正・FREE LIMIT削除・B1がマージ済みの`main`から新規作成)
**範囲:** B17・B14・B13等、他のB群機能には着手していない。

---

## 0. baseline値の性質について(B1と同様、指示書の注意事項の遵守)

出所トラッキング自体はC-miniの3指標に直接影響しにくい機能であるため、指示書の通り**このタスクの効果確認は「出所情報が正しく記録・参照できるか」という機能テストで行い、C-miniのスコア変動をもって成否を判断しない。** `run_eval.py`の数値(取得できた場合)は参考値としてのみ扱う。

---

## 1. 各テーブルの出所情報の現状

### `sigmaris_decision_log`: 既に完全に実装済み。コード変更不要と確認した

Phase A3の`202607040026_decision_log_supersede.sql`で`thread_id`・`invocation_id`列が追加済み(未適用ではあるが、列定義自体は存在)。今回、実際の書き込みコードを再確認したところ、**書き込みロジック自体は既に正しく出所情報を設定していた**:

- `orchestrator/service.py::_cognitive_layer_bg()`が`invocation_id`・`thread_id`(`effective_thread_id`)を受け取り、
- `decision_log.py::detect_and_record_decision(..., thread_id=thread_id, invocation_id=invocation_id)`に渡し、
- そこから`log_decision(..., thread_id=thread_id, invocation_id=invocation_id)`が呼ばれ、
- `log_decision()`は`thread_id is not None`/`invocation_id is not None`の場合にpayloadへ含めてINSERTしている。

`run_orchestrator_chat`・`run_orchestrator_chat_stream`の両方の呼び出し元で、実際に`invocation_id=invocation_id, thread_id=effective_thread_id`が渡されていることをコード上で確認した(2箇所とも)。**このテーブルについては指示書の想定通り、確認のみで完了とし、コード変更は行っていない。**

### `user_fact_items`: 出所情報の列が存在せず、新規追加した

既存スキーマには`source`(manual/chat/sensor/import、「どの経路で」の粗い分類)はあるが、「どの会話・どのターンか」を追跡する`thread_id`/`invocation_id`に相当する列は無かった。実際の書き込み元である`memory_extractor.py::extract_from_conversation()`も、これらを受け取る仕組みが無かった。**新規に追加した。**

### `sigmaris_experience`: 出所情報の列が存在せず、新規追加した(ただし現状書き込み元がこの情報を持たない)

既存スキーマには`related_fact_ids`(JSONB、関連factへの参照)はあるが、`thread_id`/`invocation_id`は無かった。**列自体は新規に追加したが、3章で述べる通り、実際にこの情報を供給できる呼び出し元が現状存在しない。**

---

## 2. マイグレーション内容(`202607080030_memory_provenance.sql`、未適用)

```sql
alter table public.user_fact_items
  add column if not exists thread_id uuid,
  add column if not exists invocation_id uuid;

create index if not exists idx_user_fact_items_thread_id
  on public.user_fact_items (thread_id);

alter table public.sigmaris_experience
  add column if not exists thread_id uuid,
  add column if not exists invocation_id uuid;

create index if not exists idx_sigmaris_experience_thread_id
  on public.sigmaris_experience (thread_id);

-- upsert_fact_item(): p_thread_id/p_invocation_id を新規パラメータとして追加
-- (デフォルトnull、末尾に追加のため既存呼び出しと後方互換)。
-- INSERT分岐でのみ設定し、UPDATE分岐では一切参照しない。
create or replace function public.upsert_fact_item(
  ..., p_thread_id uuid default null, p_invocation_id uuid default null
) returns jsonb ...
```

### 判断根拠

1. **`sigmaris_decision_log`のPhase A3と同じ列名(`thread_id`/`invocation_id`)・同じ型(`uuid`、FK制約なし)に統一した。** 3つの記憶テーブルを横断して同じ意味の情報を同じ名前で持たせることで、将来これらを横断的にクエリする際の一貫性を保つ。FK制約を付けなかった理由もPhase A3と同じ(`chat_threads`・`agent_invocation_audit_logs`は別テーブルで所有者・RLSの構造が異なり、疎結合を保つ方が安全と判断)。
2. **`upsert_fact_item` RPCは「INSERT分岐でのみ`thread_id`/`invocation_id`を設定し、UPDATE分岐では一切触らない」設計にした。** 出所情報は「このfactがいつ・どの会話から**生まれたか**」を表すものであり、「最後に触られたのはいつか」ではない。同じ`(category, key)`の組に対して後日別の会話から確認・更新があっても、最初の出所情報を上書きしない方が、指示書の「どの会話・どのターンから生まれたか」という定義に忠実だと判断した。
3. **既存レコードへの遡及的なバックフィルは行っていない**(要件2・注意事項の通り)。`add column ... default null`の形なので、既存の285件超のfactは全て`thread_id`/`invocation_id`が`NULL`のままになる。これは意図した挙動であり、読み取り側もNULLを正しく扱える設計にしている(5章のテストで確認)。
4. **未適用。** 他のPhaseと同様、`SUPABASE_SERVICE_ROLE_KEY`がこの環境に無いため、`python3 scripts/apply_migration.py 202607080030`を運用者側で実行する必要がある。

---

## 3. コード変更内容

| ファイル | 変更内容 |
|---|---|
| `user_fact_data.py::upsert_fact_item()` | `thread_id`/`invocation_id`(共にoptional、デフォルト`None`)を追加し、RPCへ`p_thread_id`/`p_invocation_id`として渡す |
| `memory_extractor.py::extract_from_conversation()` | `thread_id`/`invocation_id`(optional)を追加し、抽出した各factの`upsert_fact_item()`呼び出しに渡す |
| `orchestrator/service.py` | `extract_from_conversation()`の2つの呼び出し箇所(`run_orchestrator_chat`・`run_orchestrator_chat_stream`)で、既にスコープ内に存在していた`effective_thread_id`・`invocation_id`をそのまま渡すよう変更 |
| `experience_layer.py::record_experience()` | `thread_id`/`invocation_id`(optional)を追加し、指定時のみpayloadに含める |
| `routes/agent.py::ExperienceRecordRequest`・`experience_record()` | リクエストボディに`thread_id`/`invocation_id`(optional)を追加し、`record_experience()`へ渡す |

いずれも**既存の呼び出し元の挙動を変えない**(全て新規オプション引数、デフォルト`None`)。`memory_extractor.py`側は`orchestrator/service.py`の2箇所の呼び出しを実際に更新し、初めて実際にデータが流れる状態にした。

### `sigmaris_experience`について: 列・パラメータは追加したが、実際に値を供給する呼び出し元が現状無い

`record_experience()`の唯一の呼び出し元を調査したところ、`routes/agent.py::POST /agent/experience/record`(外部エージェント向けのHTTPエンドポイント、`_verify_agent`で保護)のみだった。`orchestrator/service.py`の会話ターン処理からは一度も呼ばれておらず、`proactive/scheduler.py`も読み取り専用の`analyze_patterns()`しか呼んでいない。

つまり、この経路には現状「今どの会話のどのターンか」という文脈を持つ内部呼び出しが存在しない。今回は`user_fact_items`・`sigmaris_decision_log`と同じスキーマ・同じ受け入れ口(パラメータ)を用意し、**将来何らかのエージェント/処理がこの情報を持って呼び出せば正しく記録される状態**にしたが、**現時点でこのテーブルへの新規書き込みに実際の出所情報が入ることは無い**(常にNULL)。これは正直に限界として報告する。将来的に自己改良システム(Phase D以降)や会話内での経験記録トリガーが実装される際に、この受け入れ口をそのまま使えるはずである。

---

## 4. B1申し送り事項(検索ヒット経路の記録)への対応

**対応した。** `memory_search.py::_merge_hybrid_results()`が、マージ後の各結果に`match_source`(`"vector"` / `"trgm"` / `"both"`)フィールドを付与するようにした。加えて`search_relevant_memories()`に、マージ結果のヒット件数・出所内訳を出力するログ行(`logger.info`)を追加した。

### 判断根拠: DBへの永続化ではなく、結果への注釈+ログ出力に留めた

指示書は「過剰な実装は避け、シンプルな形で対応すること」「軽量な形(ログ出力、または簡易的な記録テーブル)で対応してよい」としていた。以下の理由から、新規テーブルは作らず、既存の戻り値への注釈+ログ出力という最も軽量な形を選んだ:

1. **この情報の主な用途は「実データでの閾値チューニング」であり、これは運用者がログを見ながら`match_threshold`(0.15)・`_TRGM_HIGH_CONFIDENCE_SIMILARITY`(0.5)を調整する一時的な作業**。永続的な履歴クエリ機能が必要になるとは考えにくく、テーブル化は今の時点では過剰と判断した。
2. `_build_relevant_memories_context()`(orchestrator/service.py)は既知のキー(category/key/value/confidence/similarity)だけを読むため、`match_source`という新しいキーが追加されても無視されるだけで、LLMへの注入内容には影響しない(5章で確認)。
3. 将来、経路別の精度分析を本格的に行う必要が出てきた場合は、Phase C-full(独自指標SB-1〜7の本格運用)のタイミングで改めてテーブル化を検討するのが筋が良いと考える。

---

## 5. テスト結果

いずれもモック(実DB未接続)。

```
PASS: upsert_fact_item() forwards thread_id/invocation_id as p_thread_id/p_invocation_id to the RPC
PASS: existing callers that don't pass thread_id/invocation_id still work (defaults to None)
PASS: extract_from_conversation() forwards thread_id/invocation_id to upsert_fact_item for each extracted fact
PASS: record_experience() includes thread_id/invocation_id in the insert payload when provided
PASS: record_experience() without provenance omits those keys entirely (existing callers unaffected)
PASS: B1 follow-up — merged rows tagged with match_source (vector/trgm/both)
```

要件1(新規生成される記憶に出所情報が正しく記録されること)・要件2(既存呼び出し元がthread_id/invocation_idを渡さない場合でも壊れないこと、NULL許容)を直接検証している。

### 既存機能への非破壊確認(要件3・4)

- `backend/tests/`(既存8件)全てPASS、`import app.main`成功。
- Phase B1のハイブリッド検索テスト(`_merge_hybrid_results`・`search_relevant_memories`のエンドツーエンドケース)を再実行し、`match_source`付与後も全てPASSすることを確認した(検索結果の中身・順序への影響なし)。
- Phase C-miniの`eval_runner`・`testset_gen`テストを再実行し、`upsert_fact_item`・`search_relevant_memories`の呼び出し契約が変わっていないことを確認した(既存の位置引数呼び出しは全て新規オプション引数の追加のみで影響を受けない)。

### C-mini参考値

**この環境からは実行できなかった。** `backend/.env`に実クレデンシャルが無く、`sigmaris@192.168.179.11`へのSSHも`Permission denied`のままだった(過去のタスクと同一の制約、再確認済み)。

---

## 6. 気づいた懸念点・次のB機能(B17: Memory Importance Learning)に影響しそうな発見

1. **`sigmaris_experience`への出所情報供給が「配管は用意したが実際には使われない」状態のまま残っている。** B17やそれ以降で経験記憶の重要度学習・忘却耐性を扱う際、この出所情報が空のままだと「いつ・どの会話から生まれた経験か」が分からず、重要度判定の材料として使えない。B17着手時、あるいはそれ以前に、`sigmaris_experience`への実際の書き込みトリガー(会話内のどのタイミングで経験記録を残すか)自体を設計する必要があるかもしれない。
2. **`user_fact_items`の出所情報は、あくまで「最初にfactが作られた瞬間」のスナップショットである。** 同じfactが後から別の会話で更新される場合(`upsert_fact_item`のUPDATE分岐)、`updated_at`は更新されるが`thread_id`/`invocation_id`は最初の会話のまま固定される。B17で「最近強化されたfact」のような時系列重要度を扱う場合、`updated_at`と出所情報(`thread_id`)は別々の意味を持つことに注意が必要(混同すると「最後に更新した会話」と「最初に生まれた会話」を取り違える)。
3. **`match_source`(B1申し送り対応)は現状ログにしか出ておらず、集計・分析する仕組みが無い。** 実際に`match_threshold`のチューニングを行うには、運用者がログを直接読むか、別途集計スクリプトを書く必要がある。差し迫った必要性はまだ無いと考えるが、B群が進んで検索精度への関心が高まった時点で、軽量な集計手段(例えば直近N件のログをパースするスクリプト)を検討する価値がある。
4. **`sigmaris_decision_log`の出所情報が既に機能していたことは良い意味での発見だった。** Phase A3の設計時点で既にこの点が考慮されていたことが確認でき、B4のスコープが結果的に`user_fact_items`・`sigmaris_experience`の2テーブルに絞られたことで、想定より小さな変更で完了できた。

---

## Related Documents

- [phase_b1_report.md](phase_b1_report.md) — B1申し送り事項(検索ヒット経路の記録)の発端
- [phase_a3_report.md](phase_a3_report.md) — `sigmaris_decision_log`の`thread_id`/`invocation_id`設計の先例
- [sigmaris_roadmap.md](sigmaris_roadmap.md) — Phase B群全体の計画、B4→B17の順序
