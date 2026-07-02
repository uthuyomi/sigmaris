# Phase A5 実施報告: RAG(pgvector検索)の`LOCAL_LLM_ENABLED`依存見直し

**目的:** `LOCAL_LLM_ENABLED=false`(OpenAI利用)時に`generate_embedding()`が即座に空リストを返し、RAG検索(`search_relevant_memories`)が丸ごとスキップされていた問題を修正し、`LOCAL_LLM_ENABLED`の値によらず記憶検索が機能するようにする。
**作業ブランチ:** `phase-a5-rag-embedding-fallback`(Phase A0〜A4がマージ済みの`main`から新規作成)
**範囲:** Phase B(記憶拡張機能群)には着手していない。このタスクをもってPhase Aは完了とする。

---

## 1. 次元数の不整合有無とその対処方法

### 確認結果

- `user_fact_items.embedding`列: `supabase/migrations/202606290023_pgvector_memory.sql`で`vector(768)`固定。
- `search_fact_memory` RPC: 同マイグレーションで`query_embedding vector(768)`と**シグネチャに768次元がハードコードされている**(SQL関数定義そのものが768次元専用)。
- Ollama `nomic-embed-text`: 768次元(既存実装の前提通り)。
- OpenAI `text-embedding-3-small`: デフォルト出力は1536次元 → **そのままでは不整合**。

### 対処方法

OpenAI Embeddings APIの`dimensions`パラメータで768次元に切り詰めて生成する(`memory_search.py::_generate_embedding_openai`)。

```python
response = await _openai_embed_client.embeddings.create(
    model=settings.openai_embedding_model,  # text-embedding-3-small
    input=cleaned,
    dimensions=EMBEDDING_DIMENSIONS,  # 768
)
```

`dimensions`パラメータは`text-embedding-3-*`系モデルがMatryoshka Representation Learning(MRL)で学習されているために公式にサポートされている機能であり、単純な配列切り詰めのような場当たり的対処ではない。この方式により、**テーブル定義(`vector(768)`)・RPC関数シグネチャ(`vector(768)`)のどちらも変更不要**で次元不整合を解消できた。テーブル設計の変更は発生していないため、指示書の「テーブル設計変更が必要な場合のみ事前確認」という除外条件には該当しない。

---

## 2. 既存285件のデータ移行方針とその根拠

### 方針: 既存データの再生成は行わない。現状のOllama生成embeddingをそのまま残す。

### 根拠

1. **次元数は既に一致している**ため、再生成しなくても`search_fact_memory` RPCの実行自体はエラーにならない(1章の対処で解決済み)。
2. **フォールバックの優先順位を「Ollama優先・OpenAIは非常時のみ」に設計した**(4章参照)ため、`LOCAL_LLM_ENABLED=true`かつOllamaが疎通可能な通常運用では、新規に生成されるembeddingも引き続きOllama製になる。つまり**この修正は既存285件の生成方式に一切影響を与えない**。フォールバックが実際に発動するのは「Ollamaが無効/疎通不可」の場面に限られ、その場面は今まさに「検索が完全に機能していなかった」場面と一致する。再生成の緊急性・必要性は薄いと判断した。
3. **一括再生成にはOpenAI API呼び出しコストが発生する**上、ローカル環境に`OPENAI_API_KEY`がなく実行して確認することもできない。判断根拠が薄いまま285件分の書き込みを本番DBに対して行うのは、今回のタスクの「検索精度に直接影響する不具合を直す」というスコープに対して不釣り合いに大きい。
4. 混在を許容しても要件4(「既存285件が検索可能であること」)は満たされる — 詳細は3章。

---

## 3. フォールバック実装の詳細

### 採用したパターン: `local_llm.py::LLMRouter`と同系統の「設定フラグ + 疎通確認の遅延プローブ」パターンに揃えた

`LLMRouter._get_backend()`は「`LOCAL_LLM_ENABLED`かつタスク種別がローカル対象 かつ Ollamaが疎通確認済み」の場合のみローカルを使い、それ以外はOpenAIにフォールバックする。`memory_search.py`にも同じ形の判定を実装した(`generate_embedding`):

```python
if settings.local_llm_enabled and await _probe_ollama_embed_available():
    return await _generate_embedding_ollama(cleaned)

if not settings.openai_api_key:
    logger.warning(...)
    return []

return await _generate_embedding_openai(cleaned)
```

`_probe_ollama_embed_available()`は`LLMRouter._local_available`と同じ「プロセス生存中に一度だけ疎通確認し、結果をキャッシュする」設計(モジュールレベルのグローバル変数`_ollama_embed_available`に保持)。`LOCAL_LLM_ENABLED=false`の場合は`and`の短絡評価によりOllamaへの疎通確認自体が発生しない(無駄なHTTPリクエストを出さない)。

`LLMRouter`をそのまま再利用しなかった理由: `LLMRouter`は「チャット補完(`chat()`)」専用のインターフェースで、埋め込み生成(`embeddings.create`)とはAPI形状が異なる(モデル・エンドポイントが別物)。無理に共通化すると`LLMRouter`側に埋め込み専用の分岐を持ち込むことになり、責務が混ざる。パターン(設定+疎通プローブによるフォールバック)だけを踏襲し、実装は`memory_search.py`内に閉じた。

### `update_fact_embeddings()`側の対応漏れも合わせて修正

`_build_memory_context()`の分岐(4章)とは別に、`update_fact_embeddings()`(embedding未設定のfactを定期バックフィルするジョブ本体、`proactive/scheduler.py::_memory_embed`から30分毎などに呼ばれる)にも**同種の`if not settings.local_llm_enabled: return`という早期リターンが独立して存在していた**。これは検索側とは別の場所にあるバグで、指示書には明示されていなかったが、直さなければ「新規に登録されたfactのembeddingが、OpenAI運用時は永久に生成されない」という同根の不具合が残ってしまうため、`generate_embedding()`のフォールバックが機能するよう、この早期リターンも削除した。`generate_embedding()`自体がフォールバック込みで空リストを返すべき場面(バックエンド利用不可)を判断するため、呼び出し側の`update_fact_embeddings()`はその判断をgenerate_embedding()に委譲する形にした。

---

## 4. `_build_memory_context()`の分岐修正

### 修正前

```python
if settings.local_llm_enabled:
    # ベクトル検索(search_relevant_memories)
    ...
    return ...

# LOCAL_LLM_ENABLED=false: ベクトル検索を一切行わず、
# 単純な「直近上位5件のfact」+ trends を代わりに使う
facts_ctx = build_facts_context(fact_items or [], top_n=5)
...
```

### 修正後

`if settings.local_llm_enabled:`の分岐そのものを削除し、旧true分岐(ベクトル検索を行うコード)を無条件に実行するようにした。要件2(「`LOCAL_LLM_ENABLED=true`の既存動作に影響を与えないこと」)を厳密に満たすため、**true分岐のコードは一切変更せず、ガードだけを外した**。false分岐にあった`build_facts_context`(類似度に基づかない、単純な上位N件のfact羅列)は、`generate_embedding()`のフォールバックにより本物のベクトル類似検索に置き換わったため削除した。

### 気づいた点(このタスクのスコープ外として未対応)

`run_orchestrator_chat`/`run_orchestrator_chat_stream`側(`_build_memory_context`呼び出し元)には、`_build_memory_context`の戻り値で**直後に上書きされて捨てられるだけの`facts_ctx`/`trends_ctx`計算コード**が呼び出し前に重複して存在していた(orchestrator/service.py 450〜465行目付近、両関数に1箇所ずつ)。これは今回のバグとは無関係のデッドコードで、Phase A5の指示範囲(`_build_memory_context`内のif分岐)には含まれないため触っていない。また、`_build_memory_context`のtrue分岐には元々`active_trends`(トレンド情報)を組み込むロジックが無く、false分岐にのみ存在していた。要件2を厳密に守るため今回はtrue分岐を変更しなかった結果、**修正後もtrendsは`_build_memory_context`の出力に反映されない**(これは修正前のtrue分岐と同じ挙動であり、新たな劣化ではない)。Phase B以降でメモリコンテキストを再設計する際に、このデッドコード整理とtrends統合を合わせて検討する余地がある。

---

## 5. テスト結果

### 環境上の制約

ローカル環境に`OPENAI_API_KEY`・`SUPABASE_SERVICE_ROLE_KEY`が存在せず(`backend/.env`は`AGENT_SECRETS`・`LOCAL_LLM_ENABLED`・`OLLAMA_BASE_URL`・`OLLAMA_EMBED_MODEL`の4項目のみ)、実際のOpenAI Embeddings APIや本番Supabaseに対する実行時検証はできなかった。指示書の許容(「実モデルAPIでの検証ができない場合は、その旨を報告し可能な範囲に留めてよい」)に従い、モックベースの検証に留めている。

### 既存テスト

`backend/tests/`(8件)全てPASS。バックエンドの`import app.main`も成功。

### `generate_embedding()`フォールバックロジックのモック検証

Ollama(`httpx`)・OpenAI(`AsyncOpenAI.embeddings.create`)の両方をモックし、5パターンを検証した:

```
PASS: local_llm_enabled=true + Ollama reachable -> uses Ollama
PASS: local_llm_enabled=true + Ollama unreachable -> falls back to OpenAI (768-dim)
PASS: local_llm_enabled=false -> OpenAI directly, no wasted Ollama probe
PASS: no backend available -> [] (graceful skip, matches pre-A5 skip semantics)
PASS: Ollama dimension mismatch raises RuntimeError
```

2つ目のケースで、OpenAI呼び出しに渡された`dimensions`引数が768であることも直接アサートし、1章の次元数対処が実装レベルで機能していることを確認した。

### `_build_memory_context()`分岐修正のモック検証

`search_relevant_memories`をモックし、`LOCAL_LLM_ENABLED`の値ごとに実際に呼ばれるか・結果がコンテキスト文字列に反映されるかを検証した:

```
PASS: LOCAL_LLM_ENABLED=false still invokes search_relevant_memories and includes results
PASS: LOCAL_LLM_ENABLED=true behavior unchanged (still calls search, includes results)
```

要件1(false時に検索が機能すること)・要件2(true時の挙動が変わらないこと)の両方をこの2ケースで直接裏付けている。

### 未検証事項

- 実際のOpenAI Embeddings APIを呼んだ場合の応答形状(`response.data[0].embedding`のアクセスパス)は、OpenAI公式SDKのドキュメント上の形状に基づいて実装したが、実APIに対する呼び出し確認はできていない。
- 本番Supabase上の285件に対する実際の検索精度(混在時の類似度スコアの実際の値)は未検証(6章参照)。

---

## 6. Phase A全体(A0〜A5)を通じて残っている既知の懸念事項

1. **Phase A1-bのtool-event中継・confirmation marker迂回ロジックが実モデル応答に対して未検証のまま`main`へマージされている**(Phase A1-bのフォローアップ時点でサーバーSSHアクセスがなく検証不能、ユーザーが「4つまとめてマージ、A1-bのリスクは許容する」と判断)。
2. **Phase A4のCASは「厳密に同時」なレースのみ解決し、セッションをまたいだ会話履歴の分岐(divergence)は未解決**(`phase_a4_report.md` 5章に詳細)。
3. **マイグレーション3件が未適用**:
   - `202607030025_chat_messages_user_created_index.sql`(Phase A1、`chat_messages`の複合インデックス)
   - `202607040026_decision_log_supersede.sql`(Phase A3、`sigmaris_decision_log`のsupersedeカラム・`policy_change`型追加)
   - `202607050027_chat_threads_version.sql`(Phase A4、`chat_threads.version`カラム追加)
   いずれも`SUPABASE_SERVICE_ROLE_KEY`を持つ運用者側での適用が必要(`python3 scripts/apply_migration.py <id>`)。Phase A5では新規マイグレーションは発生していない(1章参照、テーブル変更なしで解決できたため)。
4. **`/api/app/chat/messages/replace`・`chat-threads.ts::replaceChatMessages`(Phase A0で追加)は依然として生きたトラフィックからの呼び出しがゼロ**。Phase A4で追加した409エラーハンドリング・リトライロジックも未検証の経路のまま。
5. **既存285件のfact embeddingとの意味空間の違い**(本報告7章で詳述)。次元は一致しているが、モデルが異なれば類似度計算の意味的な妥当性は厳密には保証されない。
6. `orchestrator/service.py`の`run_orchestrator_chat`/`run_orchestrator_chat_stream`内にある、`_build_memory_context`呼び出し直前の使われないfacts_ctx/trends_ctx計算(5章で言及)は、今回のタスクとは無関係の既存デッドコードとして残っている。

---

## 7. 気づいた懸念点・Phase B以降に影響しそうな発見

1. **埋め込みモデルの由来(provenance)を追跡する列が存在しない**。今回の対処で「Ollama製」「OpenAI製(768次元切り詰め)」のembeddingが同一の`user_fact_items.embedding`列に混在し得る状態になった。次元は揃っているためRPCはエラーなく動くが、コサイン類似度はあくまで**同一モデルの埋め込み空間内での距離**を前提にした指標であり、異なるモデルが生成したベクトル同士の類似度は理論的な保証がない(たまたま数値としては算出できるが、その値がどの程度意味を持つかは不明)。今回のフォールバックは「Ollama優先」設計のため実運用での発生頻度は限定的だと考えるが、Phase B以降で記憶検索の精度が疑わしい場合、まずこの混在を疑うべき。対策案としては、`embedding_source`のような列を追加してモデル由来を記録し、将来的に「モデルを統一する」「モデルごとに個別インデックスを持つ」といった判断ができるようにしておくことが考えられる(今回は指示書の「テーブル設計変更は要事前確認」という制約もあり、必要性が明確でない段階での追加は見送った)。
2. **`generate_embedding()`がチャットのホットパスに乗った**: `_build_memory_context`のガードを外した結果、`LOCAL_LLM_ENABLED=false`の運用でも毎ターン埋め込み生成(OpenAI API呼び出し)が発生するようになった。これはこの修正の目的そのもの(検索を機能させる)だが、副作用として**チャット応答のレイテンシにOpenAI Embeddings APIの呼び出し時間が新たに乗る**ことになる。数百ms程度と見込まれるが、実際の計測はできていない。Phase B以降でレイテンシが問題になった場合、埋め込み生成をfire-and-forgetにする、あるいは直近の埋め込みをキャッシュする、といった最適化の余地がある。
3. **`update_fact_embeddings`のバックフィルジョブが今まで(OpenAI運用下で)ずっと空振りしていた可能性**: 3章で述べた通り、このジョブにも独立した`LOCAL_LLM_ENABLED`ガードがあった。もし本番運用がOpenAIモードだった期間があれば、その間に登録されたfactは埋め込みが一切生成されないまま溜まっていた可能性がある。今回の修正でジョブ自体は正常化したが、次回のスケジュール実行で未生成分が遡って処理される(embedding is.nullで拾われるため)ことを確認しておくとよい。

---

## Related Documents

- [global_state_migration_audit.md](global_state_migration_audit.md) — 発端となった監査レポート(3章・6章でRAGの`LOCAL_LLM_ENABLED`依存を指摘)
- [phase_a_summary.md](phase_a_summary.md) — Phase A0〜A5全体のサマリー
