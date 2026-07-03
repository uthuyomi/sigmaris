# Phase B1 実施報告: ハイブリッド検索(ベクトル+全文検索)

**目的:** 既存のpgvectorベクトル検索(Phase A5でOpenAI/Ollama双方対応済み)に全文検索(キーワードマッチ)を組み合わせ、固有名詞・完全一致の取りこぼしを防ぐ。C-miniの3指標で参考測定を行う。
**作業ブランチ:** `phase-b1-hybrid-search`(Phase A0〜A5・C-mini・JWT永続化・LLMRouter修正・FREE LIMIT削除がマージ済みの`main`から新規作成)
**範囲:** B4・B17・B14・B13等、他のB群機能には着手していない。

---

## 0. baseline値の性質について(指示書の注意事項の遵守)

指示書の通り、2026-07-03取得のbaseline(`memory_f1_score: 0.100`等)は、同日判明した`LLMRouter.is_available()`バグの影響下で取得された数値であり、`sigmaris_decision_log`にほぼデータが無い状態(decision由来設問0件)での測定である。**本タスクで得られる`run_eval.py`の数値は参考値として記録するに留め、これを「B1の正式な効果測定」とは扱わない。** 正式な効果測定は、decision_logにデータが十分蓄積された後、運用者の判断で改めて実施される。

主たる効果確認の根拠は、指示書の方針通り**4章の固有名詞テストケースによる定性確認**とする。

---

## 1. 採用した全文検索方式: `pg_trgm`

### 検討した選択肢

- **`pg_trgm`(トライグラム類似度)**: 文字3-gram単位の類似度計算。言語非依存(単語境界の検出に依存しない)。
- **`tsvector`/`to_tsquery`(標準全文検索)**: 単語単位のインデックス・検索。日本語は空白で単語が区切られないため、標準の`simple`/`english`設定では機能せず、形態素解析可能な設定(`pg_bigm`等の追加拡張、またはカスタム日本語辞書)が別途必要になる。

### 判断根拠

**`pg_trgm`を採用した。** 理由:

1. **日本語の単語境界問題を回避できる。** 海星さんとのやり取りは日本語中心であり、標準的な`tsvector`設定は日本語の単語分割ができない。追加拡張(`pg_bigm`等)の可用性は本番Supabase環境で未確認であり、確認自体にサーバーアクセスが必要(この環境からは不可)。`pg_trgm`はPostgreSQL標準contrib拡張として広く利用可能で、Supabaseでも標準的に有効化できることが期待できる(指示書もこの点を優先的に検討するよう指示していた)。
2. **今回のタスクの本来の目的(固有名詞の取りこぼし防止)と、`pg_trgm`の得意分野が一致する。** 「ThinkPad T14」「シグマリス」等の固有名詞は英数字を含むことが多く、`pg_trgm`の単語抽出(非英数字記号を区切りとして扱う)はこうしたラテン文字混じりの固有名詞に対して特に有効に働く。
3. **言語非依存で追加設定が不要。** 形態素解析辞書のインストール・メンテナンスが不要で、実装・運用コストが低い。

### 実装したもの(マイグレーション`202607070029_hybrid_search_trgm.sql`)

```sql
create extension if not exists pg_trgm;

alter table public.user_fact_items
  add column if not exists search_text text
  generated always as (
    coalesce(category, '') || ' ' || coalesce(key, '') || ' ' ||
    coalesce(value, '') || ' ' || coalesce(notes, '')
  ) stored;

create index if not exists user_fact_items_search_text_trgm_idx
  on public.user_fact_items
  using gin (search_text gin_trgm_ops);

create or replace function public.search_fact_memory_trgm(
  query_text text, user_id_param uuid,
  match_threshold float default 0.15, match_count int default 5
)
returns table (id uuid, category text, fact_key text, value text, confidence float, similarity float)
...
  where user_fact_items.user_id = user_id_param
    and coalesce(user_fact_items.is_deleted, false) = false
    and coalesce(user_fact_items.is_stale, false) = false
    and similarity(user_fact_items.search_text, query_text) > match_threshold
  order by similarity(user_fact_items.search_text, query_text) desc
  limit match_count;
```

- `search_text`は`memory_search.py::_fact_embedding_text()`(埋め込み生成に使っているテキスト)と**全く同じフィールド構成**(category/key/value/notes)にした。両検索経路が同じ情報源に対して検索することで、挙動の一貫性を保つため。
- **未適用。** 他のPhaseと同様、`SUPABASE_SERVICE_ROLE_KEY`がこの環境に無く、私からは適用できない。`python3 scripts/apply_migration.py 202607070029`を運用者側で実行する必要がある。
- `match_threshold`のデフォルト値(0.15)は、ベクトル検索の`threshold`(デフォルト0.7)とは別スケールの値であり、文献的に妥当と考えられる値を暫定的に設定した。**実データに対する経験的なチューニングは、この環境からは実施できていない**(0章のDBアクセス制約による)。運用開始後、実際の検索結果を見ながら調整することを推奨する。

---

## 2. マージロジックの実装詳細

`memory_search.py::search_relevant_memories()`の内部実装をハイブリッド化した。**関数シグネチャは変更していない**(呼び出し元の`orchestrator/service.py`・`routes/agent.py`・Phase C-miniの`eval_runner.py`は無変更で動作する)。

### マージ方式: Reciprocal Rank Fusion(RRF) + 高信頼度キーワードヒットの優先浮上

```python
def _merge_hybrid_results(vector_rows, trgm_rows, *, limit):
    # 標準的なRRF: 各リストでの順位(1始まり)から 1/(k+rank) を加算、両リストで合算
    ...
    # トライグラム類似度が0.5以上(ほぼ完全一致とみなせるキーワードヒット)は、
    # RRFのランキングとは無関係に最優先で浮上させる
    high_confidence_ids = [row["id"] for row in trgm_rows if similarity >= 0.5]
    ...
```

**判断根拠**: 標準のRRF(両リストを対等に扱う)だけでは、「ベクトル検索の上位には一切現れないが、全文検索では完全一致する」というケース(固有名詞の取りこぼし、まさに今回の目的)で、その完全一致ヒットが埋もれる可能性がある。指示書の「全文検索で完全一致・高スコアのヒットがあった場合、それを優先的に上位に反映させる設計にする」という要求に文字通り対応するため、トライグラム類似度が高い(0.5以上、ほぼ完全一致)ヒットは**RRFのランキング計算を経由せず無条件で最優先表示**する設計にした。0.5未満の弱いトライグラムヒットは通常通りRRFで統合される。

### 並列実行によるレイテンシ対策

埋め込み生成(LLM呼び出し、最も時間がかかりうる処理)とトライグラム検索(DBクエリ)は独立しているため、`asyncio.gather`で並列実行する設計にした。ベクトル検索自体は埋め込みが確定してからでないと実行できないため、埋め込み生成の完了を待って続けて実行する。

```
[埋め込み生成(LLM)] ─┬─ 並列 ─┬─→ [ベクトル検索RPC] ─┐
[トライグラム検索RPC]  ─┘        │                     ├─→ マージ
                                 └─────────────────────┘
```

これにより、ハイブリッド化で追加されたトライグラム検索の分のレイテンシは、埋め込み生成の待ち時間にほぼ吸収される(5章で実測)。

### 副次的なメリット: embedding生成失敗時のフォールバック

トライグラム検索は埋め込み生成に一切依存しないため、Phase A5で対応した「Ollama・OpenAIどちらの埋め込みバックエンドも使えない」場合(以前は検索結果が空になっていた)でも、**キーワードベースの検索結果だけは返せるようになった。** これは今回のタスクの主目的ではないが、実装の結果として得られた副次的な堅牢性向上である。

---

## 3. C-mini測定結果(参考値・正式な効果測定ではない)

**この環境からは実行できなかった。** `backend/.env`に引き続き実クレデンシャルが無く(`AGENT_SECRETS`・`LOCAL_LLM_ENABLED`・`OLLAMA_BASE_URL`・`OLLAMA_EMBED_MODEL`のみ)、`sigmaris@192.168.179.11`へのSSH接続も`Permission denied`のままだった。指示書の「可能な範囲で実行を試みること」に従い試行したが、実行経路が無いことを再確認した(過去のタスクと同一の制約)。

**運用者へのお願い**: `python scripts/run_eval.py --notes "B1(ハイブリッド検索)実装直後・参考値"`を実行し、baseline(`memory_f1_score: 0.100`等)との差分を確認してください。ただし0章の通り、この差分は「B1の効果」と「decision_logのデータ蓄積による自然回復」が混在した数値になるため、**単体でB1の効果判定に使わないこと。**

---

## 4. 固有名詞テストケースでの定性確認(主たる効果確認の根拠)

実DBへのアクセス手段が無いため、Phase C-mini・Phase A5と同様にモック環境での確認とした。`backend/scripts/seed_fact_memory.py`の実際のシードデータ(`devices/laptop: "ThinkPad T14 Gen3 / Core i7-1260P / 32GB / 1TB / Windows"`)を題材に、「ベクトル検索の上位に本来ヒットすべき事実が入らないが、トライグラム検索では拾える」状況を再現し、`search_relevant_memories()`をエンドツーエンドで実行した。

```python
query = "ThinkPad T14の話をした?"

# ベクトル検索(モック): 本来無関係なfactが上位に来てしまうケースを再現
vector検索結果 = [{"id": "unrelated-1", ..., "similarity": 0.71}]  # laptop-factを含まない

# トライグラム検索(モック): "ThinkPad T14"の文字列一致で正しくヒット
trgm検索結果 = [{"id": "laptop-fact", "value": "ThinkPad T14 Gen3", ..., "similarity": 0.62}]

結果 = await search_relevant_memories(query, user_id, limit=5)
# -> ["laptop-fact", "unrelated-1"]  laptop-factが最優先で浮上
```

**確認結果**: ベクトル検索単体の結果には`laptop-fact`が一切含まれない(取りこぼされている)状況でも、ハイブリッド検索の最終結果では`laptop-fact`が1位に浮上することを確認した。要件1を満たしている。

**留保**: これは実際の埋め込みモデル・実データに対する測定ではなく、「ベクトル検索が取りこぼす」という状況をモックで意図的に再現した上でのロジック確認である。実際にOpenAI/Ollamaの埋め込みが「ThinkPad T14」のような固有名詞クエリでどの程度取りこぼすかは、実測できていない(0章と同じ制約)。運用開始後、実際の検索結果を継続的に観察することを推奨する。

---

## 5. レイテンシへの影響

モックで埋め込み生成に0.2秒、トライグラム検索に0.05秒かかる状況を再現し、`search_relevant_memories()`全体の所要時間を計測した。

```
PASS: embedding generation (0.2s) and trigram query (0.05s) run concurrently
      (total elapsed 0.203s, not ~0.25s+)
```

埋め込み生成とトライグラム検索が並列実行されていることを確認した(合計時間が0.203秒であり、逐次実行なら発生するはずの0.25秒超えは観測されなかった)。**追加されたベクトル検索後の処理(マージ計算)はO(件数)の軽量な処理であり、無視できる規模。** 実際のネットワークレイテンシ(Supabase RPC呼び出し自体の往復時間)は実測できていないが、設計上、ハイブリッド化による直列的な追加待ち時間は「トライグラム検索の実行時間 − 埋め込み生成時間」の差分(通常は埋め込み生成の方が遅いため、ほぼゼロ)に抑えられる。

---

## 6. テスト結果

いずれもモック(実DB・実LLM未接続)。

### `_merge_hybrid_results()`(純粋関数)

```
PASS: vector-only results preserved when trigram search returns nothing
PASS: trigram-only results preserved when vector search returns nothing (embedding-generation-failed fallback path)
PASS: an item present in both ranked lists outranks a same-position single-list item: ['b', 'a', 'c']
PASS: proper-noun fact entirely missed by vector search still surfaces (and first): ['laptop-fact', 'unrelated-1', 'unrelated-2']
PASS: weak trigram similarity (below 0.5) does not get the priority-surface boost: ['a', 'b']
PASS: limit truncation respected after merge
PASS: multiple high-confidence trigram hits stay ordered by their own trigram rank: ['exact-match', 'near-exact']
```

### `search_relevant_memories()`(エンドツーエンド、RPC呼び出しをモック)

```
PASS: end-to-end hybrid search surfaces the ThinkPad T14 fact that vector search alone missed
PASS: embedding generation raising an exception degrades gracefully to trigram-only results, no crash
PASS: trigram RPC raising an exception degrades gracefully to vector-only results, no crash
PASS: both search paths failing -> empty list, not an unhandled exception
PASS: embedding generation and trigram query run concurrently (latency)
```

要件1(固有名詞ヒット)・要件2(既存ベクトル検索の挙動非破壊、失敗時のフォールバック)・要件3(レイテンシ)を直接検証している。

### 既存テスト

`backend/tests/`(既存8件)全てPASS、`import app.main`成功。Phase A5の埋め込みフォールバックテスト・Phase C-miniの`eval_runner`テストも再実行し、両方とも引き続きPASSすることを確認した(既存機能への非破壊確認)。

---

## 7. 気づいた懸念点・次のB機能(B4: 出所トラッキング)に影響しそうな発見

1. **`match_threshold=0.15`・高信頼度判定`0.5`は、実データでの経験的検証ができていない暫定値。** トライグラム類似度は文字列の長さ・言語混在の度合いによって挙動が変わりやすく、日本語主体の短い質問文に対して0.15が緩すぎる(ノイズが多い)か厳しすぎる(拾えない)かは、実運用データでの調整が必要。
2. **`search_text`生成列は`category`/`key`/`value`/`notes`の単純結合であり、`category`や`key`(内部的な識別子、例: `"short_term_1"`)がノイズとしてトライグラム類似度計算に混入する可能性がある。** 将来的に`value`列だけを対象にする、あるいは重み付けを分けるといった改善余地がある。
3. **B4(出所トラッキング)との関係**: ハイブリッド検索の結果には現状「どちらの経路(ベクトル/トライグラム/両方)でヒットしたか」という情報が含まれていない(`similarity`フィールドのみ)。B4で記憶の出所(どの会話から生まれたか)を追跡する際、併せて「どの検索経路でヒットしたか」も記録できると、今後のチューニング(4章・5章の留保の解消)に役立つ可能性がある。今回は指示書のスコープ外のため実装していないが、B4着手時に検討の余地がある。
4. **`sigmaris_decision_log`は引き続きこのハイブリッド検索の対象外である**(Phase C-mini・Phase A5で既出の制約、`search_fact_memory`/`search_fact_memory_trgm`はどちらも`user_fact_items`のみを検索する)。B4以降で決定記録も検索対象にする場合、トライグラム検索側にも同様の対応が必要になる。

---

## Related Documents

- [phase_a5_report.md](phase_a5_report.md) — 埋め込み生成フォールバックの実装(本タスクが土台にしている)
- [phase_c_mini_report.md](phase_c_mini_report.md) — baseline値の性質、C-mini指標の位置づけ
- [sigmaris_roadmap.md](sigmaris_roadmap.md) — Phase B群全体の計画、B1の位置づけ
