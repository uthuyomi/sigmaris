# Phase A3 実施報告: `sigmaris_decision_log` の本稼働

**目的:** `sigmaris_decision_log`が実際の決定事項を記録するようにする（新規テーブルではなく既存の空疎な実装の作り直し）。
**作業ブランチ:** `phase-a3-decision-log`（Phase A0〜A2がマージ済みの`main`から新規作成）
**範囲:** Phase A4(排他制御)・A5(RAGのLOCAL_LLM_ENABLED依存見直し)・Phase B(記憶拡張機能群)には着手していない。

---

## 1. 決定判定ロジックの実装詳細

### LLM呼び出し方式・TaskType選定理由

**新規`TaskType.DECISION_DETECTION`を追加した**（`local_llm.py`）。既存の`MEMORY_EXTRACTION`を流用する案も検討したが、以下の理由で新設を選んだ:

- 事実抽出（fact memory）と決定検出は入力（直近のやり取り＋既知の事実＋アクティブな決定一覧）・出力スキーマ・目的が異なり、同じTaskTypeに混ぜると将来的に「決定検出だけモデルを変えたい」「事実抽出だけプロンプトを調整したい」といった独立したチューニングができなくなる。
- コスト・重さの面では両者とも同格（軽量な分類・抽出タスク）と判断し、`_LOCAL_TASK_TYPES`（ローカルLLM対象）と`_openai_model_for_task`のnanoモデル階層（`MEMORY_EXTRACTION`/`ROUTING`/`SUMMARIZE`と同じ）の両方に`DECISION_DETECTION`を追加した。`LOCAL_LLM_ENABLED=true`環境では既存の事実抽出と同様にOllamaへルーティングされ、無効時は`OPENAI_NANO_MODEL`にフォールバックする。

### 判定・記録フロー

1. `orchestrator/service.py::run_orchestrator_chat`(非ストリーミング)・`run_orchestrator_chat_stream`(ストリーミング)の両方で、応答生成後に`asyncio.create_task(_cognitive_layer_bg(...))`としてfire-and-forget実行（既存パターンを踏襲、`await`しない）。
2. `_cognitive_layer_bg`に渡す`turn_messages`は**今回のターンのみ**（直近のユーザー発言1件＋アシスタント応答1件）。Phase A1のスレッド横断ウィンドウ（`session_messages`、最大40件）ではなく、元の`messages`パラメータから`_latest_user_message()`で抽出した直近ユーザー発言のみを使用している。
   - **判断根拠**: ウィンドウ全体を毎回LLMに渡すと、過去に一度検出済みの決定が古いターンとしてウィンドウに残り続け、次のターン以降も再度「決定あり」と誤検出されるリスクがある。今回のターンだけに絞ることで、この重複検出リスクを構造的に排除した。
3. `decision_log.py::detect_and_record_decision()`が実際の判定を行う:
   - 直近のやり取り（transcript）、海星さんの既知の事実の要約（`build_facts_context()`を再利用、上位15件）、現在アクティブな直近の決定一覧（`superseded_by`がnullのもの最大10件）をプロンプトに含めてLLMに提示。
   - LLMは`{"has_decision": false}`（決定なし）または`{"has_decision": true, "decision_type", "title", "reason", "outcome", "related_fact_keys", "supersedes_decision_id"}`（決定あり）のいずれかを返す。
   - `has_decision=false`の場合は**書き込みを一切行わない**（要件2）。
   - `has_decision=true`の場合、`related_fact_keys`（例: `"goals/parking_plan"`）を`fact_items`のcategory/keyと突き合わせて実際の`user_fact_items.id`に解決し`memory_refs`とする。
   - `supersedes_decision_id`はアクティブな決定一覧のidと突き合わせて検証し、一致しない値（LLMのハルシネーション含む）は`None`として無視する。

---

## 2. `decision_type`の値域と判定の対応

既存の値域: `proposal` / `refusal` / `notification` / `action`（いずれもシグマリス視点の行動を表す: 提案した／断った／通知した／実行した）。

**`policy_change`を新規追加した**（マイグレーションで`CHECK`制約を拡張）。理由: 「会話の中でユーザー（または対話を通じて）決定・方針転換があった」という今回検出したい対象は、既存4種のいずれにも正確に対応しない。特に`proposal`は「シグマリスが提案する」行為を指しており、「ユーザーが方針を決定した」という主体・意味が異なる。指示書が例示していた"proposal/policy_change等"のうち、**主たる型として`policy_change`を採用**し、LLMの判定結果が万一これ以外の値域外の文字列を返した場合は`policy_change`にフォールバックする防御的処理を入れた（`decision_type not in _VALID_TYPES`の場合）。

LLM自身にも`policy_change`または`proposal`のいずれかを選ばせる設計にしており（プロンプト内で明示）、「ユーザー主導の明確な方針決定」は`policy_change`、「複数選択肢からの選定に近いニュアンス」は`proposal`という緩やかな使い分けをLLMの判断に委ねている。

---

## 3. supersede機構の実装方法

### スキーマ変更

新規マイグレーション`supabase/migrations/202607040026_decision_log_supersede.sql`:

```sql
alter table public.sigmaris_decision_log
  add column if not exists thread_id uuid,
  add column if not exists invocation_id uuid,
  add column if not exists supersedes uuid references public.sigmaris_decision_log(id),
  add column if not exists superseded_by uuid references public.sigmaris_decision_log(id);

create index if not exists idx_sigmaris_decision_log_thread_id on public.sigmaris_decision_log (thread_id);
create index if not exists idx_sigmaris_decision_log_superseded_by on public.sigmaris_decision_log (superseded_by);

alter table public.sigmaris_decision_log
  drop constraint if exists sigmaris_decision_log_decision_type_check;
alter table public.sigmaris_decision_log
  add constraint sigmaris_decision_log_decision_type_check
  check (decision_type in ('proposal', 'refusal', 'notification', 'action', 'policy_change'));
```

- `thread_id`/`invocation_id`: どの会話・どのオーケストレーター呼び出しからこの決定が生まれたかの出所トラッキング（Phase B4の前提として指示書が明示的に要求）。あえて`chat_threads`への外部キー制約は付けていない（判断根拠は6章参照）。
- `supersedes`（新レコード→旧レコード）と`superseded_by`（旧レコード→新レコード）を**双方向**に持たせた。指示書は「古いレコードに参照を持たせる」（`superseded_by`相当）のみを求めていたが、「この決定は何を置き換えたか」を新レコード側からも直接たどれた方が今後の分析（Phase B14想定）で扱いやすいと判断し、両方向の列を追加した。両方とも`sigmaris_decision_log(id)`への自己参照外部キー。

### 実装ロジック

`decision_log.py`に`mark_superseded(old_decision_id, new_decision_id)`を新設。`log_decision()`は新規レコードを`supersedes=<old_id>`付きでINSERTし、成功後に`mark_superseded()`が旧レコードを`UPDATE ... SET superseded_by=<new_id>`する（**削除・上書きは一切行わない**、`title`/`outcome`等の既存カラムは無変更）。

`detect_and_record_decision()`内での順序: ①新規決定をINSERT → ②INSERTが成功し、かつLLMが有効な`supersedes_decision_id`を返していた場合のみ`mark_superseded()`を呼ぶ。この順序により、自己参照FKが常に「既に存在する行」を指す状態を維持できる。

---

## 4. テスト結果

### 既存テスト

`backend/tests/`（8件）: 全てPASS（回帰なし）。

### マイグレーション未適用による制約

新規カラム(`thread_id`/`invocation_id`/`supersedes`/`superseded_by`)と拡張した`decision_type`のCHECK制約は、ローカル環境に`SUPABASE_SERVICE_ROLE_KEY`がなく`scripts/apply_migration.py`を実行できないため、**本番DBへの適用ができていない**（過去のPhaseで判明した既知の制約と同様）。そのため、実際のSupabaseテーブルに対する書き込みテストは実施していない。

### 実施した検証: LLM呼び出し＋Supabase HTTP層をモックしたロジック検証

`detect_and_record_decision()`のロジックを、LLM応答とSupabase HTTPクライアントの両方をモックして4パターン検証した（実行結果全文、文字化けは実行環境のコンソール文字コードの問題でデータ自体は正しいUTF-8。アサーションで内容一致を検証済み）:

1. **雑談 → 記録なし**: `{"has_decision": false}`を返すモックに対し、`POST`が一切発行されないこと・戻り値が`None`であることを確認。
2. **明確な決定 → 記録あり、memory_refs解決**: 「駐車場問題、AプランじゃなくてBプランにしよう」という会話に対し、`decision_type=policy_change`でレコードが作成され、`related_fact_keys=["goals/parking_plan"]`が実際の`fact_items`から`memory_refs=["fact-1"]`に正しく解決されることを確認。
3. **方針変更（supersede）**: 既存のアクティブな決定（`id=existing-decision-1`）を置き換える新しい決定を送信し、①新レコードに`supersedes=existing-decision-1`が設定されること、②旧レコードに対して`PATCH ... {"superseded_by": <新id>}`が正確に1回発行されること、③旧レコードの他のフィールド（`title`/`outcome`）が一切変更されないこと（削除・上書きなし）を確認。
4. **ハルシネーション耐性**: LLMがアクティブな決定一覧に存在しない`supersedes_decision_id`を返した場合、`supersedes`が`None`として無視され、余計な`PATCH`も発行されないことを確認（不正な自己参照FK違反を未然に防ぐ設計の裏付け）。

```
=== small talk -> no record ===
  no write occurred (correct)
PASS: small talk does not create a decision_log row

=== explicit decision -> recorded with memory_refs ===
PASS: decision recorded with correctly resolved memory_refs, no supersede

=== supersede an existing decision ===
  patch params={'id': 'eq.existing-decision-1'} body={'superseded_by': 'fake-id-1'}
PASS: supersede chain recorded (new row references old, old row PATCHed with superseded_by; old row not deleted)

=== hallucinated supersedes_decision_id is ignored ===
PASS: hallucinated/invalid supersedes_decision_id is safely ignored

ALL DECISION-LOG LOGIC TESTS PASSED
```

**実モデルAPIでの確認はできていない**（`OPENAI_API_KEY`が引き続きローカルにないため）。指示書の許容に従い、モックベースの検証で要件1〜3の充足を判断した。

### マイグレーション適用手順（要ユーザー対応）

```bash
# サーバー上、backend/.env に SUPABASE_SERVICE_ROLE_KEY が設定された状態で
cd /path/to/shift-pilot-ai
python3 scripts/apply_migration.py 202607040026
# または Supabase Dashboard の SQL Editor で該当ファイルを直接実行
```

適用前は、`decision_type`が新しく`policy_change`の行を挿入しようとすると`CHECK`制約違反で失敗し、`log_decision()`内の`try/except`が例外を捕捉してログに残すのみ（**アプリケーションはクラッシュしないが、決定は記録されない**）。**マイグレーション適用が完了するまでは、本Phaseの機能は実質的に動作しない**点に注意。

---

## 5. `memory_model.md`との整合性確認

`docs/sigmaris/memory_model.md`のDecision Memoryセクションを確認した。「重要な意思決定の経緯・根拠・結果を保存する」「なぜその判断をしたかを後から追跡可能にする」という設計意図と、今回実装した`reason`/`outcome`/`memory_refs`/`supersedes`系のフィールドは整合している。

**軽微な不整合（既存のドキュメント側の問題、今回の実装では変更していない）**: `memory_model.md`は将来実装予定のテーブル名を`sigmaris_decision_logs`（複数形）と記載しているが、実際に存在するテーブルは`sigmaris_decision_log`（単数形）。ドキュメントが先に書かれ、後から実装時に単数形で作られたと見られる命名のズレで、今回のタスク範囲外のため修正はしていない（気づいた点として記録のみ）。

---

## 6. 気づいた懸念点・Phase B以降に影響しそうな発見

1. **`thread_id`に外部キー制約を付けなかった判断**: Phase A1で`orchestrator/service.py::_ensure_chat_thread()`により、orchestrator経由の全呼び出しで`chat_threads`行の存在が事前に保証されるようになったため、理論上は`thread_id uuid references chat_threads(id)`という厳格なFKも可能だった。しかし、`decision_log`テーブル自体はservice-role専用（RLSでuser policyなし）であり、`chat_threads`はユーザーRLS付きのテーブルという扱いの非対称性があること、また将来チャット以外の経路（Phase B等）から決定が記録される可能性を考慮し、あえて緩い（FK制約なしの）UUID列とした。Phase B4で出所トラッキングを本格的に設計する際に、この判断を見直す価値がある。
2. **`turn_messages`を今回のターンのみに絞ったことで、複数ターンにまたがる決定を見逃す可能性**: 例えば「Aにする？」「うーん、ちょっと考える」（次のターン）「やっぱりBにする」という2ターンにまたがる方針変更の場合、2ターン目単体では文脈が薄く、LLMが正しく判定できない可能性がある。現在はアクティブな決定一覧をコンテキストとして渡しているが、それは既に記録済みの決定に限られ、「まだ記録されていない検討中の話題」はカバーしない。Phase B以降で複数ターンにまたがる決定検出が必要になった場合は、直近数ターン（Phase A1のウィンドウの一部）を渡す設計への拡張を検討する必要がある。
3. **決定の粒度・過検出のリスクは実モデルでの検証待ち**: プロンプトで「雑談・確認・単純な質問応答には反応しない」よう明示的に指示しているが、実際のLLM（特にnanoモデル階層）がどの程度の粒度で「決定」を検出するかは、実運用でのチューニングが必要になる可能性が高い。次点の検証としてサーバー上での実地確認を推奨する。
4. **Phase B14（意思決定パターンモデリング）への接続**: 既存の`analyze_decision_patterns()`（週次分析ジョブ）は今回変更していないが、`decision_type`に`policy_change`が加わったことで`type_counts`の分布が変化する。また、supersede関係（同じトピックが何度覆されたか）は今のところこの週次分析の入力に含まれていない。Phase B14で「意思決定パターン」を分析する際は、supersedeチェーンの長さ（何度覆されたか）を明示的な特徴量として活用できる可能性がある。

---

## Related Documents

- [global_state_migration_audit.md](global_state_migration_audit.md) — 発端となった監査レポート(3章)
- [memory_model.md](memory_model.md) — Decision Memoryの設計意図の原典
- [phase_a1_report.md](phase_a1_report.md) — 本Phaseが前提とする`_ensure_chat_thread`（thread_id出所保証）の実装
