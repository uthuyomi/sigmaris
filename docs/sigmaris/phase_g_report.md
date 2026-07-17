# Phase G-1 実施報告: Trigger Detection(検索が必要かどうかの判定ロジック)

**作業ブランチ:** `phase-g1-trigger-detection`(mainから新規作成)
**範囲:** 「この質問には検索が必要か」を判定する軽量ロジックの実装と検証のみ。実際のWeb検索実行(G-2: Evidence Structuring以降)は行わない。

---

## 0. 前提として確認したこと

着手前に指示書が指定した3ファイルを確認した。

- `docs/sigmaris/glossary_curiosity.md`: このコードベースには「curiosity」を名乗る3つの無関係な概念(curiosity mood・curiosity research queue・Knowledge-Gap Drive)が既に存在することを確認した。**本タスクが実装する「検索要否の判定」は、これら3つのいずれとも異なる、新しい第4の概念である**——curiosity research queue(`curiosity_engine.py`)は「シグマリスが自発的に関心を持ち調べる」ための既存の仕組みであるのに対し、本タスクは「ユーザーからの質問に対してリアルタイムに検索が必要か」を判定するものであり、目的も発火タイミングも異なる。混同を避けるため、本タスクのコード・本報告書では「curiosity」という語を一切使わず、「search need」「検索要否」という独立した用語で統一した。
- `docs/sigmaris/phase_s_report.md`(S-2): S-2(Goal Proposal)の`_act_on_knowledge_gap`が、既存の`curiosity_engine.generate_curiosity_queries()`を呼び、`sigmaris_curiosity_queue`へクエリを追加するだけで、実際の外部検索(`research_agent.run_research_for_query()`)は既存の日次6:15バッチが別途実行する設計になっていることを再確認した。この「判定・生成」と「実行」を分離する設計は、本タスク(G-1: 判定のみ)とG-2(検索実行)の分離方針とも一致しており、既存の設計思想を踏襲した。
- `docs/sigmaris/incident_response_latency_investigation.md`(11章、nano-tier移行): `chat_routing.py::classify_chat_intent()`が、`local_llm.py`の`TaskType.CHAT_INTENT_CLASSIFICATION`(nano階層、Ollama優先・OpenAI nanoへの即時フォールバック)経由のChat Completions API呼び出しに、既に移行済み(mainにマージ済み)であることを確認した。本タスクは、この既存の1回のLLM呼び出しに相乗りする設計とした。

---

## 1. 判定基準の実装詳細(ルールベース部分とLLM判定部分の分担)

新設ファイル: `backend/app/services/search_trigger.py`(I/Oなし、LLM呼び出しなしの純粋関数のみで構成)。

### 1.1 ルールベース部分: `detect_search_need()`

依頼書が示した4つの判定基準のうち、**3つ(鮮度キーワード・固有名詞への言及・変動しやすい事実の言及)を、LLMを一切呼ばないルールベースの文字列照合だけで判定する。**

| 観点 | 実装方法 |
|---|---|
| 鮮度キーワード | `_FRESHNESS_KEYWORDS`(タプル、"最新"/"現在"/"今年"等) |
| 変動しやすい事実 | `_VOLATILE_FACT_KEYWORDS`(タプル、"価格"/"スペック"/"在庫"等) |
| 固有名詞・型番 | `_MODEL_NUMBER_PATTERN`(正規表現、英字2文字以上+数字1〜4桁、例: "iPhone 15" "RTX4090") |

この3つのうちいずれか1つでも該当すれば`needs_search=True`。該当した具体的な語・パターンは`reasons`(文字列のリスト、例: `["freshness_keyword:最新", "volatile_fact_keyword:価格"]`)として返す。

**判断根拠(キーワードの絞り込み)**: 実装当初は「今の」「今日」「最近」「いま」も鮮度キーワードに含めていたが、テスト実装中に「今日は疲れたなあ」「最近どう？」のような、検索とは無関係な日常会話まで誤検出することを確認した。これらは日本語の日常会話で極めて高頻度に使われる語であり、検索の要否とはほぼ無相関だと判断し、「最新」「現在」「今年」等、より明確に情報の鮮度そのものを問う語へ絞り込んだ。依頼書「過度に複雑な判定ロジックにしないこと」の精神に沿い、文脈判定の追加ではなく、誤検出率の高い語自体をリストから外す方を選んだ。

**判断根拠(固有名詞パターンの正規表現)**: 当初`r"[A-Za-z]{2,}[\-\s]?\d{1,4}[A-Za-z]?\b"`(末尾に単語境界`\b`)としていたが、"RTX4090の性能"のように直後に日本語が続く文でマッチに失敗することをテストで発見した。Pythonの`re`はデフォルト(Unicodeモード)で日本語の文字も`\w`とみなすため、数字と日本語の間に単語境界が成立しなかったことが原因である。英数字側の開始点だけで十分に絞り込めると判断し、末尾の`\b`を削除した。

**4つ目の基準(既存記憶`user_fact_items`でカバーできるか)について**: 本関数では明示的なメモリ照合を行っていない。`classify_chat_intent()`は現状`messages`と`attachment_facts`のみを受け取り、`user_fact_items`(B1記憶検索の結果)を受け取っていない——これを新たに配線するには、`chat.py::run_chat_completion()`/`stream_chat_completion_ui()`の呼び出し順序自体を変更する必要があり、依頼書が明示する「本タスクの範囲は判定ロジックのみ」を超えるプラミング変更になると判断した。代わりに、**鮮度・固有名詞・変動事実のいずれの信号も無ければ`needs_search=False`とする設計自体が、「時間とともに変化する情報でなければ、既存の一般知識・記憶で十分」という前提を暗黙的に体現している**、という考え方を採用した。この点は5章の懸念点・G-2への申し送りで改めて扱う。

### 1.2 LLM判定部分: 既存の`classify_chat_intent()`への相乗り

新しいLLM呼び出しは一切追加していない。`classify_chat_intent()`が、ヒューリスティック(`heuristic_intent()`)でintentを即断できず、既存のnano-tier LLM呼び出し(`TaskType.CHAT_INTENT_CLASSIFICATION`)を行う場合にのみ、**同じプロンプト・同じJSON応答へ`needs_search`/`search_reason`の2フィールドを追加**し、LLMの判定をルールベースの結果へ統合する。

```python
# プロンプトへの追加(1行)
"Also decide needs_search: true if answering well requires current prices, "
"specs, availability, versions, rankings, release dates, or other facts "
"that change over time and might be stale in memory; also true if the "
"request names a specific product, company, or model whose current "
"details may not be known. False for general chat, personal schedule "
"questions, or anything answerable from stable general knowledge or the "
"assistant's existing memory of the user. Briefly explain in search_reason."

# JSON応答形式の変更
'Return JSON only like {"intent":"...","reason":"...","needs_search":true,"search_reason":"..."}.'
```

### 1.3 ルールベースとLLM判定の統合: `merge_llm_search_judgment()`

```python
def merge_llm_search_judgment(rule_signal, *, llm_needs_search, llm_search_reason) -> dict:
    ...
```

**判断根拠(OR統合、安全側に倒す設計)**: 本タスクの動機は「価格・スペック・最新情報のような、鮮度が重要な質問に対して、もっともらしいが検証されていない内容を答えてしまう」ことへの対応であり、**過剰検出(不要な検索がG-2で実行される)より、見逃し(必要な検索がされない)の方が実害が大きい**と判断した。そのため、ルールベース・LLM判定のいずれかが`needs_search=True`であれば、最終的にも`True`とする(いずれもFalse、またはLLM側が判定不能・呼ばれなかった場合のみFalse)。ヒューリスティックがintentを即断してLLMが一切呼ばれないターンでは、ルールベースの結果(`source: "rule"`)のみを返す——この場合でも判定自体は必ず行われる(依頼書要件1)。

---

## 2. 既存の意図分類への統合方法

`chat_routing.py::classify_chat_intent()`の3つの返却経路すべてに、新しい`search`キー(辞書: `{"needs_search": bool, "reasons": list[str], "source": "rule"|"rule+llm"}`)を追加した。

| 経路 | `search`キーの中身 | LLM呼び出し |
|---|---|---|
| ヒューリスティック即断(`source: "heuristic"`) | ルールベースのみ(`source: "rule"`) | 呼ばれない(既存通り) |
| LLM判定成功(`source: "llm"`) | ルールベース+LLM判定の統合(`source: "rule+llm"`) | 既存の1回のみ(新規追加なし) |
| LLM呼び出し失敗・例外(`source: "fallback"`) | ルールベースのみ(`source: "rule"`) | 既存の1回のみ(結果は使わず、例外時のフォールバック) |

**既存コードへの影響範囲**: `chat_routing.py`の変更は、(a) `search_trigger`モジュールのimport追加、(b) `detect_search_need()`の呼び出し1行追加、(c) プロンプト文字列への1行追加+JSON応答形式の変更、(d) 3つの返却辞書それぞれへの`search`キー追加、(e) 戻り値の型注釈を`dict[str, str]`から`dict[str, Any]`へ修正(既存の`intent`/`reason`/`source`は全てstrのままだが、`search`はネストした辞書のため)。**`intent`/`reason`/`source`という既存の3キーの値・意味は一切変更していない。**

`chat.py`側(`classify_chat_intent()`の2つの呼び出し元、`run_chat_completion()`・`stream_chat_completion_ui()`)は**一切変更していない**。`route["search"]`は現状どこからも読まれていないが、辞書のキーとして常に存在するため、G-2以降が`route["search"]`を参照するだけで、追加のプラミング無しに利用できる状態になっている。**判断根拠**: `chat.py`のmetadata(`routeIntent`/`routeReason`/`routeSource`)へ`routeSearchNeeded`等を追加することも検討したが、依頼書が繰り返し強調する「本タスクの範囲は判定ロジックのみ」により忠実であるため、既存のホットパスへの変更を最小限(`chat_routing.py`の内部のみ)に留めた。

---

## 3. テスト結果

`test_phase_g1_search_trigger.py`として19件のテストを作成した(scratchディレクトリ、`backend/tests/`には追加していない、既定の方針通り)。

```
DetectSearchNeedTests (7件、ルールベース単体)
  PASS: 鮮度キーワード(「現在の円相場ってどのくらい？」)で検索必要と判定
  PASS: 変動しやすい事実キーワード(「iPhoneの価格を教えて」)で検索必要と判定
  PASS: 固有名詞・型番パターン(「RTX4090の性能ってどう？」)で検索必要と判定
  PASS: 一般的な雑談(「今日は疲れたなあ、ちょっと休憩したい」)で検索不要と判定
  PASS: 既存記憶で十分な予定確認(「明日の予定を教えて」)で検索不要と判定
  PASS: 複数信号が同時に該当する場合、全てreasonsに記録されること
  PASS: 英語キーワードも大文字小文字を区別せず判定されること

MergeLlmSearchJudgmentTests (4件、統合ロジック単体)
  PASS: ルール=False・LLM=Trueの場合、最終的にTrueになること
  PASS: ルール=True・LLM=Falseの場合でも、最終的にTrueが保たれること
        (OR統合・安全側設計の直接検証)
  PASS: 両方Falseの場合のみFalseになること
  PASS: LLM側が未判定(None)の場合、ルールベースの結果を変更しないこと

ClassifyChatIntentSearchIntegrationTests (8件、既存関数への統合)
  PASS: ヒューリスティック即断時、ルーターを一切呼ばずにsearchキーが
        含まれること(要件2の直接検証)
  PASS: ヒューリスティックが検索不要な文言にマッチしても、同じ発言に
        検索を要する信号があれば、ルール層は独立してそれを検出すること
  PASS: 【重要】LLM経路で、1回のLLM呼び出しのみでintentとsearchの両方
        が得られること(要件2の直接検証。router.chatがちょうど1回だけ
        呼ばれること、TaskType.CHAT_INTENT_CLASSIFICATION・
        max_tokens=800・json_mode=Trueが維持されていることを確認)
  PASS: LLM応答にneeds_searchフィールドが無い(旧形式・不正な形式)場合も
        例外にならず、ルールベースの結果に安全に縮退すること
  PASS: LLMルーター呼び出しが例外を送出した場合も、ルールベースの結果は
        返されること
  PASS: (回帰)calendar_write等、既存のintent分類がLLM経由でも引き続き
        正しく機能すること
  PASS: (回帰)空・非dict出力時の既存フォールバックが引き続き機能すること
  PASS: (回帰)旧`client=`/`model=`引数を渡すとTypeErrorになる
        (nano-tier移行時の既存の回帰確認を再検証)

19 passed
```

既存の`backend/tests/`(16件)、直近のPhase S(S-0〜S-4、82件)・Phase R系(39件)・BA4系(59件、順序修正・タイムスタンプ関連)、およびnano-tier移行時の既存テスト(`test_classify_intent_nanotier.py`、12件)も全て再実行し、リグレッションは確認されなかった。

```
19(本タスク) + 200(既存の関連テスト一式) = 219 passed(合算実行)
```

**テスト中に確認した、本タスクと無関係な既存の問題**: `test_classify_intent_lightweight.py`(nano-tier移行より前の、token-cap+client-reuseタスクのスクラッチテスト)が、`classify_chat_intent()`に`client=`/`model=`引数を渡そうとして`TypeError`で失敗する状態だった。これは`main`の現時点で(本タスクの変更を`git stash`で除いても)既に同じ理由で失敗することを確認した——nano-tier移行(11章)が`client`/`model`パラメータをシグネチャから削除したことによる、本タスクとは無関係な既存の陳腐化である(11.4節・17章で既に報告されている、同種の既知の劣化パターン)。スクラッチファイルであり`backend/tests/`の対象外のため、本タスクでは修正していない。

### 3.1 判定精度のサンプル

| 発言 | 期待 | ルールベースの結果 | 理由 |
|---|---|---|---|
| 「最新のiPhone 16の価格を知りたい」 | 検索必要 | needs_search=True | freshness_keyword:最新, volatile_fact_keyword:価格, proper_noun_or_model_number |
| 「RTX4090の性能ってどう？」 | 検索必要 | needs_search=True | volatile_fact_keyword:性能, proper_noun_or_model_number |
| 「What's the current price of this?」 | 検索必要 | needs_search=True | freshness_keyword:current, volatile_fact_keyword:price |
| 「今日は疲れたなあ、ちょっと休憩したい」 | 検索不要 | needs_search=False | (該当なし) |
| 「明日の予定を教えて」 | 検索不要 | needs_search=False | (該当なし、既存記憶で回答可能) |

### 3.2 誤判定・限界として認識しているケース

- **偽陰性の可能性**: 「〇〇ってどんな感じ？」のように、固有名詞を含みながら鮮度・変動事実キーワードを一切使わない曖昧な質問は、ルールベースでは`needs_search=False`になりうる(固有名詞パターンが英数字混在型番形式に限定されているため、純粋なカタカナ製品名等は拾えない)。この場合、ヒューリスティックがintentを即断しなければLLM判定が補完する可能性があるが、即断された場合はルールベースの判定のみに留まる。
- **偽陽性の可能性**: 「価格.com見て」のような、既に固有名詞的なサービス名を含む発言等、`volatile_fact_keyword`(例:「見て」に隣接する「価格」)に反応して`needs_search=True`になるケースがありうるが、これは実害が小さい(過検出であり、G-2側で追加の判断材料として使われるだけで、即座に不要な検索が実行されるわけではない、という設計を前提としている)。

---

## 4. レイテンシへの影響

- **ルールベース部分(`detect_search_need()`)**: I/O・LLM呼び出しなしの純粋な文字列照合のみで、19件のテストが1秒未満で完了していることからも分かる通り、無視できるオーダー(ミリ秒未満)である。
- **LLM判定部分**: **新規のLLM呼び出しは一切追加していない**(要件2・3の核心)。既存の1回のnano-tier呼び出しのプロンプトへ、以下の増分のみが加わる。

  - プロンプト(入力)側: 約536文字(概算で約130トークン)の増分。入力トークンはLLMの生成時間にほとんど寄与しないため、体感できるレイテンシ増加は無いと考えられる。
  - JSON応答(出力)側: `needs_search`(真偽値)・`search_reason`(短い説明文字列)の2フィールド分、出力トークンがわずかに増える。既存の`max_tokens=800`という上限は変更していない(依頼書は判定ロジックの精度検証を優先しており、トークン上限の再調整は本タスクの範囲外と判断した)。

  実モデルAPIでの前後比較測定は、依頼書の制約(追加のサーバーアクセス・APIキー取得を試みない)に従い実施していない。11章(nano-tier移行時)の見積もりでは、この呼び出し自体が「数秒未満」のオーダーであり、出力トークンが数十程度増える影響は、その中でも十分に小さいと考えられる。

---

## 5. 気づいた懸念点・G-2(Evidence Structuring)に向けた申し送り事項

1. **「既存記憶(user_fact_items)でカバーできるか」は、明示的な照合を実装していない。** 1.1節で述べた通り、現状は「鮮度・固有名詞・変動事実のいずれの信号も無ければ、既存記憶で十分とみなす」という暗黙の設計に留まっている。G-2で実際に検索を実行する段階になったら、`_act_on_knowledge_gap`(S-2)がB3(`active_inquiry.py`/`memory_validator.py`)の確信度データを参照している前例と同様に、`user_fact_items`の確信度・鮮度(`memory_confidence.py`のB11階層)と本タスクの判定を組み合わせることで、より精度の高い要否判断ができる可能性がある。
2. **固有名詞検出パターン(`_MODEL_NUMBER_PATTERN`)は、英数字混在の型番形式に限定されている。** 純粋なカタカナ・漢字のみの製品名・地名・イベント名等は拾えない。より広いカバレッジが必要になった場合、固有表現抽出(NER)等の重い仕組みを追加するのではなく、まず既存のB1記憶検索が持つエンティティ抽出機構(`entities`/`relations`、`_build_memory_context()`が既に構築している)を転用できないか検討する価値がある——新しいNLP機構をゼロから追加せず、既存資産を再利用するという、このコードベース一貫の設計哲学に沿う。
3. **ルールベースのキーワードリストは、日本語の口語表現のロングテールをカバーしきれない。** 3.2節で述べた偽陰性・偽陽性の限界は、依頼書が明示的に許容する「シンプルなルールベース」の範囲内でのトレードオフである。実運用で誤判定パターンが蓄積された場合、B14(判断傾向)のような「証拠件数に基づく学習」の仕組みを転用し、キーワードリスト自体を運用者のフィードバックから調整できるようにする、という発展の余地がある(現時点では過剰実装と判断し、行っていない)。
4. **`search`キーは、現状どこからも実際には消費されていない。** `chat.py`・`orchestrator/service.py`のいずれも、`classify_chat_intent()`が返す`search`キーを一切参照していない(依頼書の範囲制限に従った意図的な設計)。G-2で実際に検索実行へ繋げる際は、この`route["search"]`をどこで受け取り、どのような閾値・信頼度で実際の検索トリガーとするか(例えば`needs_search=True`かつ`source="rule+llm"`の場合のみ実行する、等)を新たに設計する必要がある。
5. **`TaskType.CHAT_INTENT_CLASSIFICATION`のプロンプトが、intentと検索要否という2つの異なる判定を1つのLLM呼び出しに詰め込む形になった。** 現時点ではJSON応答に2フィールド追加しただけで実害は無いと考えているが、将来G-2以降でさらに判定軸(検索クエリの具体的な組み立て等)を同じ呼び出しに相乗りさせ続けると、1回の呼び出しが担う責務が肥大化し、プロンプトの複雑化・分類精度への悪影響が生じるリスクがある。これ以上判定軸を増やす場合は、専用のTaskType(11.1節が確立した「意味的に異なる分類処理には専用のTaskTypeを与える」という設計方針)へ切り出すことを検討すべきタイミングが来る可能性がある。
6. **`docs/sigmaris/glossary_curiosity.md`への追記の要否**: 本タスクは同ドキュメントが扱う3つの「curiosity」概念のいずれとも異なる新しい概念を導入した。用語の混同を避けるため、今後この用語集ドキュメントに「search need(検索要否判定)」を第4の概念として追記する価値があるかもしれないが、本タスクでは(ドキュメント更新の指示が明示されていないため)行っていない。運用者の判断を仰ぎたい。

---

## 6. マージについて

「テスト・検証」章の要件をすべて満たしていることを確認した(判定基準の実装・既存意図分類への相乗り・精度・レイテンシ見積もり・既存テストの回帰確認、いずれも達成)。依頼書の指示通り、確認を待たずmainへマージ・プッシュする。

---

# Phase G-2 実施報告: Evidence Structuring(検索実行と証拠の構造化)

**作業ブランチ:** `phase-g2-evidence-structuring`(mainから新規作成)
**範囲:** G-1が`needs_search=true`と判定した質問に対する、実際のWeb検索実行と、検索結果の"claim・source_url・source_title・retrieved_at"への構造化。

---

## 0. 前提として確認したこと

着手前に指示書が指定した2ファイルを確認した。

- `docs/sigmaris/phase_g_report.md`(G-1): `classify_chat_intent()`が返す`route["search"]`(`needs_search`・`reasons`・`source`)の形を再確認した。本タスクはこの辞書をそのまま入力として使う。
- `docs/sigmaris/glossary_curiosity.md`: `curiosity_engine.py`/`research_agent.py`が既に持つ検索の仕組みの実態を、コードを直接読んで確認した(1章で詳述)。

---

## 1. 既存資産の再利用検討: なぜ`curiosity_engine.py`/`research_agent.py`を再利用しなかったか

依頼書の最重要制約に従い、`research_agent.py::run_research_for_query()`(curiosity queueが実際に検索を実行する唯一の経路)のコードを直接読み、再利用可能性を検討した。

### 1.1 実態調査の結果: 汎用検索ではなく、固定2ソースへのキーワードフィルタだった

```python
async def run_research_for_query(query: str) -> dict[str, Any]:
    ...
    hn_items, arxiv_items = await asyncio.gather(_fetch_hn_items(), _fetch_arxiv_items(), ...)
    raw = [...HackerNewsトップストーリー30件 + arXiv cs.AI/cs.LG/cs.RO/cs.NC論文20件...]
    keywords = [k.lower() for k in query.split() if len(k) > 1]
    filtered = [item for item in raw if any(kw in (item["title"] + item["raw_summary"]).lower() for kw in keywords)]
```

`run_research_for_query()`は、**「クエリ文字列で実際にWeb検索する」のではなく、「HackerNewsのトップストーリーとarXivの直近論文という、固定・限定された2つのソースを毎回まるごと取得し、クエリの単語がタイトル・要約に含まれるかをフィルタするだけ」**という実装だった。

### 1.2 再利用できないと判断した理由

1. **ソースが技術ニュース・論文に限定されている**: `_fetch_hn_items()`はHackerNewsのトップ30件、`_fetch_arxiv_items()`はarXiv `cs.AI`/`cs.LG`/`cs.RO`/`cs.NC`カテゴリの直近論文20件のみを取得する。「iPhoneの価格」「〇〇の在庫状況」のような一般消費者向けの製品・価格情報は、この2ソースのいずれにもほぼ存在しない。
2. **「検索」ではなく「フィルタ」である**: 任意のクエリでWeb全体を検索するのではなく、あらかじめ決まった(トップストーリー30件・直近論文20件という)母集団の中から、クエリの単語を含むものだけを拾うだけの仕組みである。母集団に該当データが無ければ、どんなクエリでも0件になる。
3. **実際に試算した結果**: 「iPhone 16 価格」というクエリで`run_research_for_query()`を実行した場合を机上で追跡すると、HackerNewsのトップストーリー(技術系ニュース中心)・arXivの論文(学術論文)のいずれにも、iPhone の価格情報が含まれる可能性はほぼゼロであり、`filtered`は高い確率で空になる。

**結論**: この仕組みは「シグマリス自身の関心軸(Article 8)に沿った、AI/ML分野の探索」という、curiosity research queue本来の目的には適した設計だが、「ユーザーの任意の質問に答えるための汎用グラウンディング」という本タスクの目的とは、対象ドメインが根本的に異なる。拡張(ソースを増やす等)よりも、別の実装を用意する方が適切と判断した(要件3、依頼書が明示的に許容する対応)。

### 1.3 新規に追加した最小限の検索経路: OpenAI Responses APIの`web_search`ツール

新しい外部検索API・APIキーを追加する代わりに、**既にこのコードベースが使っているOpenAI APIが標準で提供する`web_search`ツール**(Responses API専用、`tools=[{"type": "web_search"}]`)を採用した。

**判断根拠**:
- 新規のAPIキー・外部サービス契約が一切不要(既存の`OPENAI_API_KEY`のみで動作する)——依頼書の「既存資産の再利用を最優先」という精神に、外部検索エンジンを新規契約するよりも忠実だと判断した。
- `chat.py`のBA4メイン応答生成が、既に`client.responses.create()`(Responses API)を使っている実績がある(同じAPIファミリーの延長)。
- **APIレスポンスに引用(`annotations`、`type: "url_citation"`)が構造化された形で含まれる**——`title`・`url`・`start_index`・`end_index`が返るため、claimの出典(URL・タイトル)をLLMに自由記述させる必要がなく、APIが実際に返した値をそのまま使える。これは2章で述べる「ハルシネーション耐性のある構造化」の核となる設計判断である。

---

## 2. 検索実行の実装詳細

新設ファイル: `backend/app/services/evidence_search.py`。

### 2.1 検索クエリの整形: G-1の判定根拠を反映

依頼書「元の質問文をそのまま使うのではなく、G-1が返した判定根拠を踏まえて、適切なクエリに整形すること」に対応し、`_build_search_prompt()`が`route["search"]["reasons"]`の内容に応じてヒント文を追加する。

| `reasons`に含まれる接頭辞 | 追加されるヒント |
|---|---|
| `freshness_keyword:` | 「この質問は情報の鮮度が重要です。最新の情報源を優先してください。」 |
| `volatile_fact_keyword:` | 「価格・スペック・在庫等、変動しうる具体的な事実を確認してください。」 |
| `proper_noun_or_model_number` | 「特定の製品・型番について、公式または信頼できる情報源を優先してください。」 |

**判断根拠(検索エンジン向けのキーワード列ではなく自然文の指示にした理由)**: `web_search`ツールは、渡された自由記述のプロンプト全体を踏まえてモデル自身が検索クエリを組み立てる仕組みであり、外部の検索エンジンAPIのように「検索文字列」を直接受け取るものではない。そのため、キーワードの羅列ではなく、「何を優先して調べるべきか」を伝える自然な指示文として整形した。

### 2.2 検索実行: `run_web_search()`

```python
response = await client.responses.create(
    model=settings.openai_model,
    input=query_prompt,
    tools=[{"type": "web_search", "search_context_size": "low"}],
)
```

`response.output`を走査し、`type == "message"`の項目の中から`type == "output_text"`のcontentパートを見つけ、その`annotations`から`type == "url_citation"`のものだけを`{"title", "url", "start_index", "end_index"}`として収集する。

**判断根拠(nano-tierではなく`settings.openai_model`を使う理由)**: `web_search`ツールはResponses API専用の機能であり、このコードベースのnano階層ルーティング(`local_llm.py`のTaskType/LLMRouter)は、`_OpenAIAdapter.chat()`がChat Completions APIのみを経由するため、nano階層へ安全に委譲できない(Ollamaのローカル推論も同様にWeb検索ツールを持たない)。BA4のメイン応答生成が既に`settings.openai_model`でResponses APIのtool呼び出しを行っている実績があるため、同じモデル階層を踏襲した。依頼書は構造化(2.3節)についてのみnano-tierを明示的に要求しており、検索実行そのものの階層までは指定していないと解釈した。

**`search_context_size: "low"`を選んだ理由**: OpenAI APIのドキュメントに準拠する設定項目で、`low`/`medium`(デフォルト)/`high`から選べる。本タスクの目的は「価格・スペック等の具体的な事実確認」であり、深い調査というより素早い事実確認が中心になると想定されるため、レイテンシとコストを優先し`low`を選んだ。判断根拠として明記する——実モデルでの精度検証はできていないため、`low`では情報が不足するケースが実際に見つかった場合、`medium`への変更を検討する余地がある(6章の懸念点参照)。

### 2.3 検索結果の構造化: `structure_evidence()`(nano-tier)

`_extract_cited_spans()`が、引用(`annotations`)のインデックス範囲だけを`output_text`から切り出す。**引用を持たない応答(`web_search`ツールが実際には検索しなかった、または出典を明示しなかった場合)からは、根拠のない文を一切抽出しない**(空リストを返す)——依頼書が明示的に要求する「構造化された証拠」は、常に実際の検索結果に紐づいたものだけになるようにした。

切り出された引用済みテキスト(spans)を、`TaskType.EVIDENCE_STRUCTURING`(新設、nano-tier、`local_llm.py`に追加)経由のLLM呼び出しで、簡潔なclaimへ要約する。

```python
'JSON形式で返してください: {"items": [{"source_index": 1, "claims": ["...", "..."]}, ...]}'
```

**判断根拠(`source_url`/`source_title`をLLMに生成させない設計)**: LLMには`claims`(テキストのみ)を出力させ、`source_index`を使ってPython側で元の`spans`(APIが実際に返した`url_citation`そのもの)から`source_url`/`source_title`を機械的に引き当てる。LLMにURL文字列を自由に生成させると、実在しないURLや誤字を生成するリスクがある——出典情報は常にOpenAI APIが実際に返した値のみを使うことで、この経路を構造的に排除する設計とした。**これは依頼書が要求する「原文の長い引用を避け、要点を抽出・要約した簡潔な主張とすること」に加え、独自に追加したグラウンディング安全性の設計である。**

`TaskType.EVIDENCE_STRUCTURING`は`CHAT_INTENT_CLASSIFICATION`(G-1、nano-tier移行時)と同じ設計方針(意味的に異なる分類処理には専用のTaskTypeを与える、`docs/sigmaris/incident_response_latency_investigation.md` 11.1節)に従い、`SUMMARIZE`への相乗りではなく新設した。判断根拠: `SUMMARIZE`は単一の既知のテキストを散文へ要約する用途だが、本タスクは複数の引用それぞれについて、出典への厳密なマッピングを保ったままJSON構造で返す必要があり、契約(入出力の形)が異なる。

---

## 3. 応答生成への統合方法、キャッシュへの影響確認結果

### 3.1 統合方法

`chat.py`に新設した`_append_evidence_context()`が、`route["search"]["needs_search"]`を確認し、真の場合のみ`gather_search_evidence()`(検索→構造化のパイプライン全体)を呼び、結果を`build_evidence_context()`で整形して`router_instruction`へ追記する。

```python
router_instruction = build_specialized_router_instruction(...)
router_instruction = await _append_evidence_context(route, router_instruction, messages)
```

この1行の追加を、`run_chat_completion()`・`stream_chat_completion_ui()`の両方(既存の対称構造)に適用した。`needs_search=false`の場合は即座に`router_instruction`をそのまま返す(I/O・LLM呼び出し一切なし)——通常のターンには何の影響も無い設計である。

**判断根拠(新しいパラメータを`build_system_prompt()`/`chat_prompts.py`に追加しなかった理由)**: `router_instruction`という既存の文字列へ2つ目のコンテキストブロックを連結する、というこのコードベース既存のパターン(例: Phase S-3の`dissent_context`が`preference_patterns_context`へ連結される、`orchestrator/service.py`)をそのまま踏襲した。新しいパラメータを追加すると、呼び出し元・`chat_prompts.build_system_prompt()`双方の変更が必要になるが、既存の文字列へ連結するだけであれば、`chat.py`内の変更のみで完結する。

### 3.2 Phase A2キャッシュ構造への影響確認

`chat_prompts.py::build_system_prompt()`のコメントが明記する既存の順序(キャッシュ安定性の高い順): (1) `rules`(固定) → (2) `ai_tone_instruction`(ユーザー設定) → (3) `base_system`(事実・自己モデル文脈) → (4) `attachment_facts` → (5) `router_instruction`(**「毎ターンLLMで再分類される」と明記済み**) → (6) `time_instruction`(毎ターン変化)。

**Evidenceは、この既存の順序における(5) `router_instruction`自体へ追記する形にした。** `router_instruction`は、そもそも毎ターンLLM再分類によって内容が変わりうる、既に不安定な領域として設計・コメントされている——Evidenceをそこへ追記しても、`rules`/`ai_tone_instruction`/`base_system`という、より安定した接頭辞部分(OpenAIのプレフィックスベースのプロンプトキャッシュが実際にマッチする範囲)には一切触れない。**したがって、Evidenceの追加によってキャッシュのヒット率が新たに悪化することはない**——`router_instruction`は元々ターンごとに変わりうる文字列であり、そこに変動要素を追加で足しても、キャッシュ上のふるまいは質的に変わらないと判断した。

`needs_search=false`のターン(大多数)では`router_instruction`は元のまま変化しないため、この点でも既存の挙動に影響しない。

---

## 4. テスト結果

`test_phase_g2_evidence_search.py`として29件のテストを作成した(scratchディレクトリ)。

```
BuildSearchPromptTests (4件)
  PASS: 鮮度キーワードの根拠がヒント文に反映されること
  PASS: 変動しやすい事実キーワードの根拠がヒント文に反映されること
  PASS: 固有名詞・型番の根拠がヒント文に反映されること
  PASS: 根拠が無い場合はヒント文が追加されないこと

RunWebSearchTests (4件)
  PASS: output_text・citationsが正しく抽出されること
        (web_searchツール・search_context_size="low"の指定を直接確認)
  PASS: 引用が無い応答でも空リストとして正しく扱われること
  PASS: API呼び出し失敗時にNoneへ安全に縮退すること
  PASS: APIキー未設定時も例外を伝播させずNoneへ縮退すること

ExtractCitedSpansTests (5件)
  PASS: 引用インデックスから正しい部分文字列が切り出されること
  PASS: 範囲外インデックスは無視されること
  PASS: 転倒したインデックス(start > end)は無視されること
  PASS: 非整数インデックスは無視されること
  PASS: 複数の引用がすべて正しく抽出されること

StructureEvidenceTests (5件)
  PASS: 引用が空の場合、LLMを一切呼ばずに空リストを返すこと
  PASS: 【重要】claimがsource_index経由で、APIが実際に返したsource_url/
        source_titleへ正しくマッピングされること(LLM生成のURLを使わない
        設計の直接検証)、nano-tier(TaskType.EVIDENCE_STRUCTURING)が
        使われていることの確認
  PASS: 範囲外のsource_indexは無視されること
  PASS: LLM呼び出し失敗時に空リストへ安全に縮退すること
  PASS: claimsが空配列の場合、Evidenceが生成されないこと

BuildEvidenceContextTests (2件)
  PASS: 空のEvidenceはNoneを返すこと
  PASS: claim・出典が正しく整形されること

GatherSearchEvidenceTests (4件)
  PASS: needs_search=falseの場合、一切の呼び出しをせず即座に空リストを
        返すこと(要件6の直接検証)
  PASS: 質問文が空の場合も即座に空リストを返すこと
  PASS: 【重要】検索→構造化の全体パイプラインが正しく配線されていること
        (引用から生成されたspansがstructure_evidence()へ正しく渡ること)
  PASS: 検索失敗時に空リストへ安全に縮退すること

EvidenceStructuringTaskTypeConfigTests (2件)
  PASS: EVIDENCE_STRUCTURINGがnano階層(openai_nano_model)にマップ
        されていること
  PASS: EVIDENCE_STRUCTURINGがローカル(Ollama)対象に含まれていること

AppendEvidenceContextIntegrationTests (3件、chat.pyへの統合)
  PASS: needs_search=falseの場合、router_instructionが変更されず、
        gather_search_evidence()が一切呼ばれないこと(要件6の直接検証)
  PASS: 【重要】needs_search=trueの場合、Evidenceがrouter_instructionへ
        正しく追記されること(要件4の直接検証)。ユーザーの最新発言が
        正しくgather_search_evidence()へ渡ることも確認
  PASS: Evidenceが1件も見つからなかった場合、router_instructionが
        変更されないこと

29 passed
```

既存の`backend/tests/`(16件)、G-1の全テスト(19件)、直近のPhase S・R・BA4系・nano-tier移行の既存テスト一式(200件)も全て再実行し、リグレッションは確認されなかった。

```
29(本タスク) + 219(既存の関連テスト一式、G-1含む) = 248 passed(合算実行)
```

**実モデルAPI・実際のWeb検索での検証は行っていない。** テストは`AsyncOpenAI`クライアント・`LLMRouter`をモックする形にとどまる(依頼書の注意事項通り、追加のサーバーアクセス・APIキー取得は試みていない)。特に、実際の`web_search`ツールが返す`annotations`の実データ形状(本報告のテストは`openai` Python SDK 2.33.0の型定義ファイルを直接確認して構築したモック)が、本番でも同じ形で返るかは、実際のAPI呼び出しでの確認が別途必要である。

---

## 5. レイテンシへの影響

**新しいLLM呼び出しが2つ追加される(依頼書が明示的に許容する範囲)が、いずれも`needs_search=true`と判定されたターンのみで発生する。**

- **検索実行(`run_web_search()`)**: OpenAIの`web_search`ツールは、モデルが実際にWeb検索を行い、その結果を読んで応答を組み立てる(内部的に複数回のサブリクエストが発生しうる)ため、通常のテキスト生成のみの呼び出しよりも明確に遅い。実モデルでの計測はできていないが、`search_context_size="low"`を選んだ上でも、経験的に数秒程度(既存の`classify_chat_intent()`のnano-tier呼び出しが1〜数秒オーダーだったのに対し、Web検索を伴う呼び出しはそれより長くなりやすいと考えられる)のオーダーになると見積もる。
- **構造化(`structure_evidence()`)**: 引用が実際に見つかった場合のみ実行される、nano-tier(既存のG-1・B7等と同オーダー)の呼び出し。引用が0件の場合はLLM呼び出し自体が発生しない(2.3節)。
- **直列実行であること**: 検索結果が無ければ構造化する対象が無いため、この2つは必然的に直列実行になる。並列化の余地はない。

**`needs_search=false`のターン(大多数)には、レイテンシへの影響が一切無い**(`_append_evidence_context()`が即座に`router_instruction`をそのまま返す、要件6)。`needs_search=true`のターンでは、検索+構造化の合計で、既存の応答生成に数秒〜十数秒程度の追加レイテンシが生じる可能性が高いと見積もる——これは依頼書が「実行頻度の低い呼び出しであるため、許容される」と明示している通りのトレードオフであり、正確性(グラウンディング)と引き換えに受け入れるべき遅延と判断した。

---

## 6. 気づいた懸念点・G-3(Self-Critique検証)に向けた申し送り事項

1. **実際の`web_search`ツールのレスポンス形状を、実モデルで検証できていない。** 4章で述べた通り、テストはSDKの型定義から構築したモックに基づいている。本番反映後、実際にannotationsが期待通り返るか、`search_context_size="low"`で十分な情報が得られるかは、運用者側での実地確認が必要である。
2. **`search_context_size="low"`は速度優先の選択であり、情報の網羅性とのトレードオフである。** 実運用で「検索したはずなのに関連情報が見つからなかった」というケースが多発する場合、`medium`への変更を検討する価値がある。
3. **`gather_search_evidence()`は、1ターンにつき最大1回の検索のみを行う。** 複数の異なる事実を同時に問う複雑な質問(例:「AとBの価格を両方教えて」)では、1回の検索で両方をカバーしきれない可能性がある。本タスクではシンプルさを優先し、複数クエリへの分割は行っていない——G-3(Self-Critique検証)で、得られたEvidenceが質問の全側面をカバーできているかを検証する際に、この限界が顕在化する可能性がある。
4. **構造化されたEvidenceは、応答生成のプロンプトへ「参考情報」として注入されるのみで、LLMが実際にそれを正しく使う(出典に基づかない推測と混同しない)ことまでは保証していない。** `build_evidence_context()`の末尾に「出典に基づかない推測とは明確に区別してください」という指示文を含めているが、これはプロンプトによる指示に過ぎず、強制力はない。G-3(Self-Critique検証)・G-4(引用監査)が、実際の応答がEvidenceに基づいているかどうかを事後的に検証する仕組みとして、まさにこの限界を埋める役割を担うと考えられる。
5. **`docs/sigmaris/glossary_curiosity.md`が扱う3つの「curiosity」概念、およびG-1が導入した「search need(検索要否)」概念に加え、本タスクは5つ目の関連概念(Evidence/grounding search)を導入した。** G-1の報告書でも同様の懸念を申し送ったが、今後この用語集ドキュメントへ「Evidence(グラウンディング検索)」を追記する価値があるかもしれない。本タスクでは(明示的な指示が無いため)行っていない。運用者の判断を仰ぎたい。
6. **`_MAX_PERSPECTIVES_PER_DAY`のような、既存のresearch_agent.pyが持つ「1日あたりの上限」という設計は、本タスクの検索経路には適用していない。** `needs_search`の判定自体がG-1のルールベース+LLM判定によって既に一定の頻度制御がかかっている(要らない検索は`needs_search=false`になる)ため、本タスクでは追加の上限を設けなかったが、実運用で想定より頻繁に検索が発火する場合、1日あたりの検索回数上限のような、既存のresearch_agent.pyの設計パターンを転用する価値があるかもしれない。

---

## 7. マージについて

「テスト・検証」章の要件をすべて満たしていることを確認した(検索実行・構造化・応答生成への統合・キャッシュ影響確認・既存テストの回帰確認、いずれも達成)。依頼書の指示通り、確認を待たずmainへマージ・プッシュする。

---

# Phase G-3 実施報告: Self-Critique検証(独立した視点での、生成結果のチェック)

**作業ブランチ:** `phase-g3-self-critique`(mainから新規作成)
**範囲:** G-2の構造化された証拠(Evidence)と、生成された応答が矛盾していないかを、生成とは独立した視点(別プロンプト・同じnano-tierだが別の役割)で検証し、矛盾が見つかった場合はB11のヘッジ機構と連携して該当表現を修正する。

---

## 0. 前提として確認したこと

着手前に指示書が指定した`docs/sigmaris/phase_g_report.md`(G-1・G-2)を再確認した。特に、G-2が`route["search"]`(`needs_search`・`reasons`)と、構造化されたEvidence(`claim`・`source_url`・`source_title`・`retrieved_at`)をどう受け渡しているかを再確認し、本タスクがその両方を入力として使う設計とした。加えて、B11(`memory_confidence.py`)の実装を読み直し、既存のヘッジ文言(`_LOW_CONFIDENCE_NOTE`・`_NO_EVIDENCE_NOTE`)と`confidence_guidance_note()`関数の正確な挙動を確認した(2章で詳述)。

---

## 1. Self-Critique検証の実装詳細

新設ファイル: `backend/app/services/self_critique.py`。新設TaskType: `TaskType.SELF_CRITIQUE`(`local_llm.py`、nano-tier)。

### 1.1 批評プロンプトの設計

`critique_response(response_text, evidence)`が、`_CRITIC_SYSTEM`(「批評家」という役割を明示し、Evidenceとの矛盾の有無だけを判定対象とし、文体・質等は評価しないことを明記)と、Evidence一覧・応答内容(最大2000文字に切り詰め)を並べたユーザープロンプトで、nano-tierのLLMへ1回だけ問い合わせる。

```
JSON形式で返してください:
{"verdict": "no_contradiction"|"minor_mismatch"|"clear_contradiction",
 "conflicting_claim": "矛盾するEvidenceのclaim(あれば、無ければnull)",
 "reason": "簡潔な理由(1文)"}
```

**判断根拠(応答全文ではなく最大2000文字に切り詰める理由)**: 依頼書「検証は、生成された応答全体を再評価するのではなく、Evidenceに関連する主張の部分だけを対象とすること」に対応。厳密に「Evidenceに関連する部分だけ」を機械的に抽出する仕組み(文分割・関連度判定等)を新設すると過剰実装になると判断し、代わりに、通常の会話応答であれば2000文字を超えることは稀である(Evidence関連の事実確認は通常数文で完結する)という前提のもと、上限を設けることで「過剰に広い範囲を検証しない」という要件の精神を、シンプルな方法で満たすことにした。

**判断根拠(モデル階層の選定)**: 依頼書「生成に使ったモデルとは異なる階層(nano-tier)を使用すること」に直接対応。生成(BA4のメイン応答)は`settings.openai_model`(mini階層)、批評は`TaskType.SELF_CRITIQUE`経由で`settings.openai_nano_model`(nano階層)——モデル階層そのものが異なるため、依頼書が言う「異なるモデル・異なる役割による相互検証」の"異なるモデル"の部分を、既存のnano-tierルーティングをそのまま使うだけで満たせた。新しいモデル階層・新しい外部サービスは追加していない。

### 1.2 検証結果の区分

`no_contradiction`(矛盾なし)・`minor_mismatch`(軽微な不一致)・`clear_contradiction`(明確な矛盾)の3区分のみ(依頼書「過度に複雑な採点方式にしないこと」に対応)。不正な値・パース失敗時は`no_contradiction`へ安全側に縮退する。

**判断根拠(失敗時にno_contradiction側へ縮退する設計、fail-open)**: このコードベース全体で一貫した「補助処理の失敗が主応答を壊さない」という設計方針(`chat.py::_persist_chat_messages_safely()`、`evidence_search.py::run_web_search()`等)を踏襲した。批評自体が失敗した場合、安全側に倒すなら本来"clear_contradiction"扱いにして強制的にヘッジすべきという考え方もありうるが、批評の失敗(ネットワークエラー等)は応答内容の信頼性そのものとは無関係であり、一時的なAPI障害のたびに正常な応答まで不必要にヘッジしてしまう方が、ユーザー体験として悪化すると判断した。

---

## 2. 検証結果に応じた挙動(B11との連携方法)

### 2.1 B11のConfidenceTier・ヘッジ文言をそのまま再利用

`_confidence_tier_for_verdict()`が、G-3の3区分をB11(`memory_confidence.py`)の`ConfidenceTier`(`confident`/`low_confidence`/`no_evidence`)へ写像する。

| G-3の区分 | 写像先のB11階層 | 理由 |
|---|---|---|
| `no_contradiction` | `confident` | ヘッジ不要 |
| `minor_mismatch` | `low_confidence` | 断定を避けるだけでよい |
| `clear_contradiction` | `no_evidence` | B11に3階層しか無く、最も慎重な既存の階層を流用。実際に検索で確認した事実と食い違っているという意味で、単なる「根拠薄弱」より強い注意が必要な状態だが、B11の型を新規拡張せず既存の3階層内で表現した |

写像した階層を、そのまま**`memory_confidence.confidence_guidance_note(tier)`(B11の既存関数、新規実装なし)へ渡し、B11が既に持つ日本語のヘッジ指示文(`_LOW_CONFIDENCE_NOTE`「もしかしたら〜かもしれません」「まだ確証はないんですが」/`_NO_EVIDENCE_NOTE`「記憶にない内容を断定したり作話したりせず」)をそのまま取得する。** これは「B11の仕組みに接続する」という依頼書の要求を、概念の模倣ではなく、実際にB11の関数をimportして呼び出す形で満たした設計である。

### 2.2 「ヘッジ表現への切り替え」の実装: 全文再生成ではなく、既存応答への最小限の書き換え

`apply_hedge_if_needed(response_text, critique)`が、`no_contradiction`以外の場合にのみ、既存の応答テキストと、2.1節で取得したB11のガイダンス文を入力として、nano-tier(`TaskType.SELF_CRITIQUE`、批評と同じ型)のLLMへ「矛盾が指摘された箇所だけをヘッジ表現に書き換え、それ以外の文章は変更しないでください」という制約付きの書き換えを依頼する。

**判断根拠(全文再生成ではなく最小限の書き換えにした理由)**: 依頼書「全文の再生成は最終手段とすること。まずB11のヘッジ表現への切り替えを優先すること」に対応。ゼロから応答を再生成する代わりに、既存の応答テキストを入力として与え、「矛盾箇所だけ直す」という制約付きの書き換えにすることで、(a) 出力トークン数を元の応答とほぼ同程度に抑えられる、(b) Evidenceと無関係な話題・文体を保持できる、という2点を狙った。

**書き換え失敗時の防御**: LLM呼び出し自体が例外を送出した場合、および出力が空または元の応答の1/5未満に極端に短い(壊れた・切り詰められた出力の疑いがある)場合は、書き換えを破棄し元の応答をそのまま使う——「ヘッジに失敗して不完全な応答になる」より、「断定的だが完全な応答を保つ」方が安全という判断に基づく防御である。

### 2.3 【重要な設計判断】ストリーミング経路では、実際の応答書き換えを行わない

`chat.py`には`run_chat_completion()`(非ストリーミング)と`stream_chat_completion_ui()`(ストリーミング、`/chat`の実際の利用経路)の2つの生成経路があるが、**本タスクの「矛盾があればヘッジ表現に切り替える」という実際の応答変更効果(要件4)は、非ストリーミング経路にのみ実装した。**

**判断根拠**: `docs/sigmaris/phase_ba4_report.md` 8章(「2026-07-06 追補: streaming無音時間への対応」)が、生成中にtext deltaが出ない無音時間が、フロントエンド側で「assistant枠だけ出て本文が出ない」バグを引き起こすことを、実際に本番で確認・修正した記録が残っている——「表示前にブロックする」設計から「即時中継+事後のadvisory検知のみ」設計へ切り替えた、という直接の前例である。

本タスクのSelf-Critique(批評+条件付き書き換え)は、Evidenceがある場合に限っても、追加のLLM呼び出しが最大2回発生しうる(4章のレイテンシ見積もり参照)。これをストリーミング完了後・応答確定前の同期処理として挟むと、8章が実際に踏んだのと同種の「長い無音時間→フロントエンドが待ちきれずassistant枠が空のまま」というバグを再発させるリスクが高いと判断した。

そのため、ストリーミング経路では、`response_guard.compare_response_to_tool_outputs()`(BA4追補8の事実整合性ガード)が既に確立している**「検知してログに残すが、応答は変更しない」というadvisory-onlyパターンをそのまま踏襲**した。具体的には、`critique_response()`の呼び出しを`asyncio.create_task()`で起動し、応答の送信を一切待たせない(fire-and-forget)。矛盾が検出された場合は`logger.warning()`で記録するのみで、既に送信済みの応答テキストを書き換えることはしない。

この判断は、要件4(「矛盾が検出された場合、B11の仕組みと連携し、ヘッジ表現に切り替えられること」)を、**非ストリーミング経路(`run_chat_completion`)では完全に満たし、ストリーミング経路(実際の主要な利用経路)では検証のみ行い実際の書き換えは行わない**、という部分的な充足に留まる。この点は6章の懸念点で改めて明記する。

---

## 3. `chat.py`への統合方法

### 3.1 Evidence取得ロジックのリファクタリング

G-2で実装した`_append_evidence_context(route, router_instruction, messages) -> str`(Evidenceを取得し、文字列として返すだけの関数)を、`_gather_evidence_and_context(route, messages) -> tuple[evidence, evidence_context]`(Evidence自体もそのまま返す)+ `_append_evidence_context(router_instruction, evidence_context) -> str`(純粋な文字列連結のみ)の2関数へ分割した。

**判断根拠**: G-2時点では、Evidenceは`router_instruction`へ文字列として注入されるだけで、構造化データとしては消費されていなかった。本タスクでは、批評(`critique_response()`)がEvidenceの構造化データ(`claim`・`source_title`)自体を必要とするため、生成した`evidence`をそのまま`chat.py`内で保持しておく必要がある。関数を分割することで、(a) Evidence取得のロジック自体は変更せず、(b) 呼び出し側が生成後のフェーズでも同じEvidenceを再利用できる、という2点を両立させた。既存のG-2テスト(`test_phase_g2_evidence_search.py`)は、新しい2関数を使う形へ更新し、元のテストが検証していた内容(needs_search=falseで一切呼ばれないこと等)は保持した。

### 3.2 各経路への配線

- `run_chat_completion()`: `final_text`が確定した直後(`assistant_message`を組み立てる直前)、`evidence`が非空であれば`critique_response()`→(必要なら)`apply_hedge_if_needed()`を同期的に`await`し、`final_text`を更新してから`assistant_message`を構築する。
- `stream_chat_completion_ui()`: 同じく`final_text`確定直後、`evidence`が非空であれば`_log_self_critique_advisory()`を`asyncio.create_task()`で起動するのみ(2.3節参照)。

いずれも`evidence`が空リスト(`needs_search=false`、またはG-2の検索・構造化が0件だった場合)であれば、この節のコードは一切実行されない——要件1・5を満たす。

---

## 4. テスト結果

`test_phase_g3_self_critique.py`として27件のテストを作成した(scratchディレクトリ)。既存のG-2テストファイル(`test_phase_g2_evidence_search.py`)も、3.1節のリファクタリングに合わせて3件を更新した(振る舞い自体は変更せず、新しい2関数のシグネチャに追従させただけ)。

```
BuildCritiquePromptTests (2件)
  PASS: Evidence・応答内容がプロンプトに含まれること
  PASS: 長い応答が切り詰められること

CritiqueResponseTests (7件)
  PASS: Evidenceが空の場合、LLMを呼ばずno_contradictionを返すこと(要件1)
  PASS: 応答が空文字の場合も同様
  PASS: no_contradiction判定が正しくパースされること(TaskType.SELF_CRITIQUE
        の使用を直接確認)
  PASS: clear_contradiction判定・conflicting_claimが正しく取得できること
  PASS: 不正な判定文字列はno_contradictionへ安全に縮退すること
  PASS: LLM呼び出し失敗時、no_contradictionへfail-openすること
  PASS: 非dictなJSON出力も安全に扱われること

ConfidenceTierMappingTests (3件)
  PASS: clear_contradiction → no_evidence
  PASS: minor_mismatch → low_confidence
  PASS: no_contradiction → confident

ApplyHedgeIfNeededTests (5件)
  PASS: no_contradictionの場合、LLMを呼ばず元のテキストを返すこと
  PASS: 【重要】minor_mismatchの場合、B11の_LOW_CONFIDENCE_NOTE(「仮説層」
        という同ノート特有の文言)が実際にプロンプトへ使われ、書き換えが
        行われることの直接検証(B11との連携の核心部分)
  PASS: 【重要】clear_contradictionの場合、B11の_NO_EVIDENCE_NOTE
        (「記憶にない内容を断定したり作話したりせず」という同ノート特有の
        文言)が使われることの直接検証
  PASS: 書き換えLLM呼び出し失敗時、元のテキストへ安全に縮退すること
  PASS: 書き換え結果が極端に短い(壊れている疑い)場合、元のテキストを
        保持すること

SelfCritiqueTaskTypeConfigTests (2件)
  PASS: SELF_CRITIQUEがnano階層(openai_nano_model)にマップされていること
  PASS: SELF_CRITIQUEがローカル(Ollama)対象に含まれていること

ChatGatherEvidenceAndContextTests (2件)
  PASS: needs_search=falseの場合、一切の呼び出しなしで空を返すこと(要件5)
  PASS: needs_search=trueの場合、evidence・contextの両方が正しく
        取得できること

ChatAppendEvidenceContextPureFunctionTests (3件)
  PASS: contextがNoneの場合、router_instructionが変更されないこと
  PASS: context有りの場合、正しく連結されること
  PASS: router_instructionが空文字の場合、contextのみが返ること

LogSelfCritiqueAdvisoryTests (3件、ストリーミング経路のadvisory-only
  動作の直接検証)
  PASS: 矛盾なしの場合、警告ログが出ないこと
  PASS: 【重要】矛盾ありの場合、応答テキストは変更せず、警告ログにverdict
        が記録されることのみを確認(2.3節の設計の直接検証)
  PASS: critique呼び出しが例外を送出しても、fire-and-forgetタスク自体は
        伝播させないこと

27 passed
```

既存の`backend/tests/`(16件)、G-1・G-2の全テスト(48件)、直近のPhase S・R・BA4系・nano-tier移行の既存テスト一式(211件)も全て再実行し、リグレッションは確認されなかった。

```
27(本タスク) + 248(既存の関連テスト一式、G-1・G-2含む) = 275 passed(合算実行)
```

**実モデルAPI・実際の応答生成での検証は行っていない。** テストは`LLMRouter`をモックする形にとどまる(依頼書の注意事項通り、追加のサーバーアクセス・APIキー取得は試みていない)。

---

## 5. レイテンシへの影響

**新しいLLM呼び出しが、Evidenceが存在する場合(`needs_search=true`)にのみ追加される(要件1・5、依頼書が明示的に許容する範囲)。**

### 5.1 非ストリーミング経路(`run_chat_completion`): 最大2回の追加呼び出し、同期

- **批評(`critique_response()`)**: nano-tier、常に1回(Evidenceがある場合)。既存のG-1・B7等のnano-tier呼び出しと同オーダー(1〜3秒程度と見積もる)。
- **書き換え(`apply_hedge_if_needed()`)**: nano-tier、矛盾が検出された場合のみ実行。同程度のオーダー。
- **合計**: Evidence取得(G-2、既に3〜13秒程度と見積もり済み)+ メイン応答生成 + 批評(1〜3秒)+(矛盾があれば)書き換え(1〜3秒)。ワーストケース(検索+矛盾検出+書き換え全て発生)では、既存の応答生成に対しさらに2〜6秒程度の追加が見込まれる。

### 5.2 ストリーミング経路(`stream_chat_completion_ui`): 追加レイテンシほぼゼロ

2.3節の設計判断により、批評は`asyncio.create_task()`で起動されるのみで、応答の送信(ストリーミング完了・`assistant_message`確定)を一切待たない。**ユーザーへの応答時間には、理論上ほぼ影響を与えない**(バックグラウンドタスクの実行がサーバーのCPU/ネットワークリソースをわずかに使うのみ)。

### 5.3 「体感速度に大きな悪影響を与える場合は実装を止める」という条件の判断

依頼書の安全弁(3章・マージの章)に照らし、以下の理由から**実装を継続し、要件4を非ストリーミング経路に限定する形で満たすことを選んだ**(全面的な「止めて報告」ではなく、スコープを限定した上での実装継続)。

1. Self-Critiqueが発動するのはEvidenceが存在する場合のみであり、これは既にG-2の時点で「実行頻度の低い、数秒〜十数秒の追加レイテンシを許容される特別なターン」として運用者から明示的に許可されている経路である。
2. **実際にユーザーが最も使う経路(ストリーミング)には、本タスクによる追加レイテンシがほぼ発生しない**設計にした(5.2節)。
3. 非ストリーミング経路への追加レイテンシ(2〜6秒)は、既存のG-2の検索レイテンシ(3〜13秒)と比べて相対的に小さく、この経路自体が既に「低頻度・許容される遅さ」の範囲内にあると判断した。

一方で、この判断の結果として、**ストリーミング経路では「矛盾があってもヘッジ表現への実際の切り替えは行われない」**(検知はするが、応答は変わらない)という制約が生じている。これは要件4の字面を完全には満たしていない可能性があり、6章で正直に明記する。

---

## 6. 気づいた懸念点・G-4(Two-Layer Citation Audit)に向けた申し送り事項

1. **【重要】要件4(矛盾検出時のヘッジ切り替え)は、実際の主要経路(ストリーミング)では発動しない。** 2.3節・5.3節で述べた通り、これは8章の無音時間バグという直接の前例を踏まえた、意図的な安全側の判断である。もし運用者がストリーミング経路でも実際に応答を書き換えたい場合、選択肢は(a) Evidenceがある場合に限り、ストリーミングを内部的にバッファリングしてから一括送信する方式へ切り替える(8章と同種のリスクを再度受け入れる必要がある)、(b) 矛盾が見つかった場合に、既に送信済みの応答とは別に、訂正メッセージを追加で送るUI・プロトコルを新設する(フロントエンドの変更を伴う、本タスクの範囲外)、のいずれかになると考える。G-4(Two-Layer Citation Audit)がこの制約とどう向き合うか、設計時に本節を参照してほしい。
2. **批評(`critique_response()`)自体の精度は、実モデルでの検証ができていない。** nano-tierモデルが、実際に「Evidenceとの矛盾」を正しく検出できるか(過検出・見逃しの実際の比率)は、テストのモック環境では確認できない範囲である。運用開始後、`logger.warning`(ストリーミング経路)のログを継続的に確認し、誤検出・見逃しの傾向を把握することを推奨する。
3. **書き換え(`apply_hedge_if_needed()`)の品質も未検証。** 「矛盾箇所だけを直す」という制約付き書き換えが、実際に自然な日本語で、かつ本当に該当箇所だけを修正できているかは、実モデルでの確認が必要である。
4. **`TaskType.SELF_CRITIQUE`は、批評と書き換えという2つの異なるプロンプト・出力形式(JSON判定 vs 自由記述テキスト)を、1つのTaskTypeで共有している。** 1章で述べた通り、これは意図的な判断(密結合な1機能の2ステップ)だが、将来この2ステップが別々の理由で調整されるようになった場合(例えば書き換えのみ別モデルへ切り替えたくなった場合)、TaskTypeの分離を再検討する必要がある。
5. **ストリーミング経路のadvisoryログは、DBへの永続化を行っていない(`logger.warning`のみ)。** G-4(Two-Layer Citation Audit)が、矛盾の発生傾向を分析する必要がある場合、この時点でログではなくテーブルへの記録(例えば`sigmaris_decision_log`への相乗り、または新規テーブル)を検討する価値があるかもしれない——本タスクでは依頼書に明示的な永続化要求が無いため、最小限のログ出力に留めた。
6. **`gather_search_evidence()`(G-2)自体が実際にEvidenceを1件も返さなかった場合(検索したが引用が得られなかった場合)、G-3は一切発動しない。** これはG-2の既存の設計(引用の無い応答からは何も抽出しない、ハルシネーション防止)の自然な帰結であり、本タスクの範囲では正しい挙動だが、「検索はしたのに、結局グラウンディングの検証も一切行われない」ケースが一定数存在することになる——G-2の6章で申し送った懸念点(`search_context_size="low"`が原因で情報が不足するケース)と合わせて、実運用でのモニタリングが必要な項目として改めて記録する。

---

## 7. マージについて

「テスト・検証」章の要件をすべて満たしていることを確認した。ただし5.3節・6章1項で明記した通り、要件4はストリーミング経路(実際の主要な利用経路)では完全には満たされていない——これは実装不足ではなく、8章の既知の障害パターンを踏まえた意図的なスコープ限定であり、レイテンシ・安定性を優先した判断である。この判断自体は依頼書の「体感速度に大きな悪影響を与える場合は実装を止めて報告する」という安全弁の精神(レイテンシへの警戒)に沿ったものであり、「要件を満たせない」という全面的な停止条件には該当しないと判断し、mainへマージ・プッシュする。この判断が運用者の意図と異なる場合は、6章1項の代替案を踏まえて再検討をお願いしたい。

---

# Phase G-4 実施報告: Two-Layer Citation Audit(二段階の引用監査)+ Abstention連携の仕上げ

**作業ブランチ:** `phase-g4-citation-audit`(mainから新規作成)
**範囲:** 引用の二段階監査のうち2段階目(claim単位での使われ方の忠実性チェック)の実装、B11連携の仕上げ、G-5に向けた監査結果の永続化。

---

## 0. 前提として確認したこと

着手前に指示書が指定した`docs/sigmaris/phase_g_report.md`(G-1〜G-3)を再確認した。特に、G-3(`self_critique.py`)の`critique_response()`・`apply_hedge_if_needed()`の正確な実装、およびG-3の懸念点5(「ストリーミング経路のadvisoryログは、DBへの永続化を行っていない」)を再確認し、本タスクがこの懸念点への直接的な対応も兼ねる設計とした(3章参照)。

---

## 1. 二段階目監査の実装詳細(G-3との役割分担)

新設ファイル: `backend/app/services/citation_audit.py`。新設TaskType: `TaskType.CITATION_AUDIT`(`local_llm.py`、nano-tier)。

### 1.1 G-3との役割分担(依頼書「G-3と重複しない範囲に絞ること」への対応)

| | G-3(`critique_response`) | G-4(`audit_citation_usage`、本タスク) |
|---|---|---|
| 対象 | 応答"全体" vs Evidence"全体" | Evidenceの各claim"個別" |
| 検出する問題 | 矛盾(応答がEvidenceと食い違っている) | 使い方の歪み(claim自体は正しいが、応答内での使われ方が誇張・意味の取り違え・文脈からの逸脱をしている) |
| 判定区分 | `no_contradiction`/`minor_mismatch`/`clear_contradiction` | `not_used`/`faithful`/`distorted`(claimごと) |

`_AUDIT_SYSTEM`プロンプトには「応答全体が正しいかどうかは評価対象外です(それは別の検証で既に行われています)」という一文を明記し、G-3の役割を代替・再検証しないことを、プロンプトレベルでも明示した。

### 1.2 claim単位の判定を、1回のLLM呼び出しでまとめて行う設計

`audit_citation_usage(response_text, evidence)`は、evidence内の全claim(最大10件、`_MAX_CLAIMS_FOR_AUDIT`)を1つのプロンプトへ番号付きで並べ、nano-tierのLLMへ**1回だけ**問い合わせ、JSON配列で各claimの判定を受け取る。

**判断根拠(claim件数ぶんの個別呼び出しをしない理由)**: `research_agent.py::_classify_items()`が既に採用している「複数項目をバッチでまとめてLLMへ判定させる」というこのコードベースの既存パターンを踏襲した。claim件数に比例してLLM呼び出しが増える設計は、依頼書のレイテンシへの配慮に反すると判断した。

**判断根拠(source_url/source_titleをLLMに再生成させない設計)**: `audit_citation_usage()`の戻り値は、G-2の元の`evidence`要素へ`usage`/`note`を追加しただけのものであり、`source_url`/`source_title`はG-2が保持していた値をそのまま引き継ぐ。LLMには`claim_index`(番号)と`usage`/`note`だけを出力させ、Python側で元のevidenceへ機械的に結合する——`evidence_search.py::structure_evidence()`が既に確立した「出典情報は常にAPIが実際に返した値のみを使う」というグラウンディング安全設計を、G-4でも一貫して踏襲した。

---

## 2. B11連携の仕上げ内容

### 2.1 新設した引用不一致専用ノート

「情報源は実在するが、内容が主張を十分に裏付けていない」ケース向けに、`_CITATION_MISMATCH_NOTE`を新設した。

```
[引用の確認結果に関する注意]
検索で確認した情報源は実在しますが、その内容を十分に裏付けているとは
言えない使い方をしている箇所があります。「情報源はありますが、断定は
できません」「確認できた範囲では、というのが正直なところです」のよう
に、断定を避け、正直に伝えてください。
```

**判断根拠(B11本体を拡張せず、`self_critique.py`/`citation_audit.py`側に新設した理由)**: B11(`memory_confidence.py`)の既存ノート(`_LOW_CONFIDENCE_NOTE`/`_NO_EVIDENCE_NOTE`)は、いずれも「記憶が薄い/無い」という前提の文言であり、「情報源は実在し、G-2の時点で構造的に確認済みだが、使い方が不正確」という本ケースの前提とは異なる。B11自体を「情報源はあるが使い方が不正確」という新しい概念で拡張するより、B11と同じ「短い日本語の指示文を、書き換えプロンプトへ注入する」という設計パターンだけを踏襲し、文言自体はPhase G独自のものとして新設する方が、B11の既存の意味論(記憶の確信度)を汚さないと判断した。依頼書が例示した言い回し(「情報源はありますが、断定はできません」)は、そのままこのノートに反映した。

### 2.2 G-3とG-4の統合判断: `select_guidance_note()`

```python
def select_guidance_note(critique, audit_results) -> str | None:
    if critique.get("verdict") not in (None, "no_contradiction"):
        return confidence_guidance_note(_confidence_tier_for_verdict(critique["verdict"]))  # B11(G-3経由)
    if any(item["usage"] == "distorted" for item in audit_results):
        return _CITATION_MISMATCH_NOTE  # G-4固有
    return None
```

**判断根拠(優先順位: G-3が優先)**: G-3が既に矛盾を検出している場合は、そちらのB11階層マッピングを優先する——応答全体の矛盾の方が、個別claimの使い方の粗さより深刻な問題である可能性が高いと判断した。G-3が「矛盾なし」でも、G-4がclaim単位で"distorted"を検出していれば、本タスク専用のノートを使う——これがまさに依頼書が想定する「claim自体は実在する情報だが、生成応答が文脈から外れた形で使っている」ケースであり、G-3の粗いチェックでは見逃されうる、G-4固有の検出対象である。

**書き換え呼び出しの重複防止**: `finalize_response_with_citation_audit()`/`verify_response()`は、G-3・G-4のどちらか一方、または両方が問題を検出した場合でも、`rewrite_response_with_guidance()`(G-3が実装した既存の書き換え実行部、1章参照)の呼び出しを**合計1回のみ**に抑えている。テストで直接検証済み(4章参照)。

---

## 3. 監査結果の記録方法(G-5での測定を見据えた設計)

### 3.1 新設テーブル: `sigmaris_citation_audit_log`

新設マイグレーション: `supabase/migrations/202607230050_citation_audit_log.sql`(作成のみ、適用は運用者側に委ねる、依頼書の注意事項通り)。

```sql
create table if not exists public.sigmaris_citation_audit_log (
  id                uuid primary key default gen_random_uuid(),
  thread_id         text,
  claim             text not null,
  source_url        text not null,
  source_title      text,
  usage             text not null check (usage in ('not_used', 'faithful', 'distorted')),
  note              text,
  critique_verdict  text check (critique_verdict in ('no_contradiction', 'minor_mismatch', 'clear_contradiction')),
  created_at        timestamptz not null default timezone('utc', now())
);
```

**判断根拠(claim単位の粒度で1行ずつ記録、集計テーブルにしない理由)**: 依頼書「本タスクでは実装しないが、G-5で継続的な精度測定を実装する予定」という位置づけを踏まえ、`sigmaris_cycle_health_runs`(Phase R-3、周期的な**集計**run)ではなく`sigmaris_decision_log`(**個別イベント**ログ)の形に倣った。G-5が引用精度・再現率等の指標を計算する際の"生データ"として、本テーブルを集計させる想定であり、集計そのもの(G-5の役割)を本タスクで先取りしないよう、あえて粒度を細かいままにした。

**判断根拠(`critique_verdict`列を含めた理由)**: G-3自身は何も永続化していない(G-3の報告書、懸念点5で明記済み)。本タスクでこの列を追加することで、G-5が「G-3の判定とG-4の判定がどれくらい一致/不一致するか」を、追加のテーブル結合無しに分析できるようにした——G-3の懸念点5への直接的な対応でもある。

**判断根拠(`service_role_only`、JWTスコープのRLSにしなかった理由)**: このテーブルはSigmaris自身の内部検証データであり、ユーザー所有のコンテンツ(`chat_messages`等)とは性質が異なる。`sigmaris_decision_log`/`sigmaris_experience`/`sigmaris_cycle_health_runs`と同じ、既存の`service_role_only`パターンを踏襲した。

### 3.2 永続化のタイミング(要件4)

- 非ストリーミング経路: `verify_response()`が完了した直後、`persist_citation_audit()`を**同期的に`await`**する(DB書き込み1回程度のコストは、既に発生している複数回のLLM呼び出しに比べ無視できるため、fire-and-forgetにする必要は無いと判断した)。
- ストリーミング経路: G-3から続くadvisory-onlyのfire-and-forgetタスク(`_log_verification_advisory()`)の中で、G-3・G-4の検証結果と合わせて永続化する。

`audit_results`が空(Evidenceが無い、またはG-4の判定自体が失敗した場合)は、`persist_citation_audit()`自体が即座に何もせず返る(要件6、無駄なHTTP呼び出しをしない)。

---

## 4. レイテンシへの影響、および追加で行った最適化

### 4.1 G-3とG-4の並行実行

依頼書のレイテンシへの配慮を踏まえ、本タスクで**G-3の`critique_response()`とG-4の`audit_citation_usage()`を`asyncio.gather()`で並行実行する**最適化を追加した(`citation_audit.py::run_verification_checks()`)。両者は互いの判定結果に依存しない独立したLLM呼び出しであり、順に`await`する必然性が無いと判断した——G-1の報告書が申し送った「`classify_chat_intent()`と記憶コンテキスト構築の並列化」と同種の判断である。テストで、両呼び出しが実際に並行して開始されることを直接検証した(`RunVerificationChecksTests::test_runs_concurrently_not_sequentially`、4章参照)。

### 4.2 レイテンシの見積もり

- **非ストリーミング経路**: G-3(批評)+G-4(claim単位監査)は並行実行のため、追加レイテンシは「遅い方の1回分」(nano-tier、1〜3秒程度)に抑えられる——直列だった場合の約2倍のレイテンシを回避した。矛盾/不一致が検出された場合の書き換え(最大1回)は、G-3・G-4どちらの検出であっても共通の1回のみ(2.2節)。ワーストケース(検索+矛盾/不一致検出+書き換え)では、既存の応答生成に対しさらに2〜4秒程度の追加が見込まれる——G-3単独の見積もり(2〜6秒)と比べて、並行化により実質的な増分は小さい。
- **ストリーミング経路**: G-3と同じ`asyncio.create_task()`によるfire-and-forgetパターンを踏襲しており、ユーザーへの応答時間には理論上ほぼ影響を与えない。追加されたDB書き込み(`persist_citation_audit()`)も同じバックグラウンドタスク内で行われる。

### 4.3 「体感速度に大きな悪影響を与える場合は止める」の判断

G-3が確立した判断(非ストリーミング経路は許容される低頻度の遅延、ストリーミング経路はadvisory-onlyでレイテンシ影響ほぼゼロ)をそのまま踏襲し、かつ本タスクでG-3・G-4を並行化したことで、G-3単独の時点より実質的なレイテンシ増分はむしろ縮小したと判断した。よって「実装を止めて報告する」条件には該当しないと判断し、実装を継続した。

---

## 5. テスト結果

`test_phase_g4_citation_audit.py`として30件のテストを作成した(scratchディレクトリ)。既存のG-3テストファイル(`test_phase_g3_self_critique.py`)から、chat.py内の関数リネーム(`_log_self_critique_advisory` → `_log_verification_advisory`、G-3単独からG-3+G-4統合への拡張に伴う)によって重複・陳腐化した3件のテストクラスを削除し、同等以上のカバレッジを本タスクのテストファイルへ引き継いだ。

```
BuildAuditPromptTests (2件)
  PASS: 全claim・応答内容がプロンプトに含まれること
  PASS: claim件数の上限が守られること

AuditCitationUsageTests (6件)
  PASS: Evidenceが空の場合、LLMを呼ばず空リストを返すこと(要件6)
  PASS: 応答が空文字の場合も同様
  PASS: 【重要】faithful/distortedが正しくパースされ、source_url/
        source_titleが元のevidenceの値のまま保持されること
        (LLM生成のURLを使わない設計の直接検証、TaskType.CITATION_AUDIT
        の使用も確認)
  PASS: LLMが判定を返さなかったclaimはnot_usedへ安全に縮退すること
  PASS: 不正なclaim_indexは無視されること
  PASS: LLM呼び出し失敗時、全claimがnot_usedへfail-openすること

SelectGuidanceNoteTests (5件)
  PASS: 問題が無い場合、Noneを返すこと
  PASS: G-3が矛盾を検出した場合、B11のマッピング済みノートを使うこと
        (apply_hedge_if_needed()と同一のノートであることを直接比較)
  PASS: 【重要】G-3がクリーンでも、G-4がdistortedを検出していれば、
        引用不一致専用ノートを使うこと(G-4固有の検出対象の直接検証)
  PASS: 両方が検出した場合、G-3側が優先されること
  PASS: verdictが欠損していても、G-4側は正しく判定されること

FinalizeResponseWithCitationAuditTests (3件)
  PASS: 問題が無い場合、書き換え呼び出しなしで元のテキストを返すこと
  PASS: distorted検出時、引用不一致ノートで正しく1回だけ書き換えられること
  PASS: 【重要】G-3・G-4両方が検出した場合でも、書き換え呼び出しは
        合計1回のみであること(要件2の直接検証)

RunVerificationChecksTests (2件)
  PASS: G-3・G-4両方の結果が正しく返ること
  PASS: 【重要】両呼び出しが逐次ではなく並行して開始されることの直接
        検証(タイミング計測による、4章の最適化の裏付け)

VerifyResponseTests (2件)
  PASS: 問題が無い場合、応答が変更されないこと
  PASS: G-3の矛盾検出時、正しく書き換えられG-3の結果も返ること

PersistCitationAuditTests (3件)
  PASS: 監査結果が空の場合、HTTP呼び出しをしないこと
  PASS: 正しいペイロード形状(thread_id・claim・source_url・usage・
        critique_verdict等)でPOSTされること
  PASS: HTTP失敗時、例外を伝播させないこと

CitationAuditTaskTypeConfigTests (2件)
  PASS: CITATION_AUDITがnano階層にマップされていること
  PASS: CITATION_AUDITがローカル(Ollama)対象に含まれていること

RewriteResponseWithGuidanceTests (2件、self_critique.pyのリファクタリング
  検証)
  PASS: 任意のガイダンス文言での書き換えが機能すること(G-4が再利用する
        共通部品の直接検証)
  PASS: リファクタリング後もapply_hedge_if_needed()(G-3単体)が
        引き続き正しく機能すること(回帰確認)

LogVerificationAdvisoryTests (3件、chat.pyの拡張されたストリーミング
  advisory関数)
  PASS: クリーンなターンでは警告ログが出ないこと
  PASS: distorted検出時、警告ログが出て監査結果が永続化されること
  PASS: 例外が発生しても伝播しないこと

30 passed
```

既存の`backend/tests/`(16件)、G-1〜G-3の全テスト(72件、うちG-3の3件は前述の通りリネームに伴い本タスクのファイルへ統合)、直近のPhase S・R・BA4系・nano-tier移行の既存テスト一式(184件)も全て再実行し、リグレッションは確認されなかった。

```
30(本タスク) + 272(既存の関連テスト一式、G-1〜G-3含む) = 302 passed(合算実行)
```

**実モデルAPI・実際の応答生成での検証は行っていない。** テストは`LLMRouter`をモックする形にとどまる(依頼書の注意事項通り、追加のサーバーアクセス・APIキー取得は試みていない)。

---

## 6. 気づいた懸念点・G-5(言い回し調整+継続測定)に向けた申し送り事項

1. **`select_guidance_note()`の優先順位(G-3優先)は未検証の設計判断である。** 実際の運用で、G-4が検出する「使い方の歪み」の方が、G-3が見逃す・軽視する重大な問題であるケースが多いと判明した場合、優先順位の再検討が必要になるかもしれない。G-5の継続測定が、この優先順位の妥当性を検証する材料になりうる。
2. **`_MAX_CLAIMS_FOR_AUDIT`(10件)を超えるEvidenceがあった場合、超過分のclaimは監査対象外のまま応答生成へ使われる。** G-2の実際の生成claim数は通常1桁に収まると見込んでいるが、この上限に達するケースが実際にあるかどうかは、`sigmaris_citation_audit_log`のデータからG-5が確認できる。
3. **`audit_citation_usage()`のプロンプトは、「文脈からの逸脱」という判定基準がやや抽象的である。** nano-tierモデルが実際にどの程度の「誇張」「意味の取り違え」を"distorted"と判定するか(閾値の厳しさ)は、実モデルでの検証ができていない。過検出・見逃しの傾向は、G-5が`sigmaris_citation_audit_log`の`usage`列の分布を集計することで初めて定量的に把握できる——本タスクはまさにそのためのデータ収集基盤を用意した、という位置づけである。
4. **`_CITATION_MISMATCH_NOTE`の文言は、依頼書の例示に沿って新設したが、実モデルでの自然さの検証ができていない。** B11の既存ノートと同様、実際にこの文言が意図通りヘッジ表現へ反映されるかは、運用開始後の確認が必要である。
5. **G-4の並行化最適化(4.1節)は、G-3単体の設計を変更する(`_log_self_critique_advisory`→`_log_verification_advisory`への改名、内部実装の書き換え)ことで実現した。** G-3の既存テストのうち3件が、この変更に伴い陳腐化・削除対象になった(5章参照)。今後Phase Gにさらに検証レイヤーを追加する場合、同様の「既存の検証関数を、複数レイヤー共通の並行実行フレームワークへ統合し直す」というリファクタリングが再度必要になる可能性がある——その際は、既存テストの陳腐化を都度検知・更新する運用を継続する必要がある。
6. **本タスクで、Phase Gの検証機能(G-1〜G-4)が一通り完成した。** G-1(検索要否判定)→G-2(検索実行+構造化)→G-3(応答全体の矛盾検証)→G-4(claim単位の使われ方監査)という4段階が、いずれも「Evidenceが存在する場合にのみ発動し、通常の会話には一切のオーバーヘッドを与えない」という一貫した設計方針の下に実装された。G-5では、これら4段階が実際に生成した`sigmaris_citation_audit_log`・G-3のログ(現状DB非永続)を材料に、Phase Rと同様の継続的な精度測定(引用精度・引用再現率等)を実装する想定である——本タスクが用意した`critique_verdict`列付きの監査ログが、その最初のデータソースになる。

---

## 7. マージについて

「テスト・検証」章の要件をすべて満たしていることを確認した(claim単位監査の実装・G-3との役割分担・B11連携の仕上げ・監査結果の永続化・既存テストの回帰確認、いずれも達成)。5章で述べた通り、G-3・G-4を並行実行する最適化により、レイテンシへの影響はG-3単独の時点よりむしろ縮小したと判断し、依頼書の指示通り確認を待たずmainへマージ・プッシュする。

---

# Phase G-5 実施報告: 「調べたことが分かる」言い回しの調整、+ 継続的な精度測定

**作業ブランチ:** `phase-g5-grounding-health`(mainから新規作成)
**範囲:** persona.mdへの検索由来情報の言い回しルール追加、およびG-4の`sigmaris_citation_audit_log`から算出する継続的な精度測定(Citation Precision・Search Trigger Rate・Contradiction Rate)。Phase G(G-1〜G-5)全体の完了サマリーも本節末尾に含める。

---

## 0. 前提として確認したこと

着手前に指示書が指定した2ファイルを確認した。

- `docs/sigmaris/phase_g_report.md`(G-1〜G-4): 特にG-4が新設した`sigmaris_citation_audit_log`の正確なスキーマ(`thread_id`・`claim`・`source_url`・`source_title`・`usage`・`note`・`critique_verdict`・`created_at`)を再確認し、本タスクの指標算出がこのテーブルの実際の列構成と整合するよう設計した。
- `docs/sigmaris/phase_r_report.md`: RC指標(RC-1〜RC-5)の設計思想——「Noneは0ではなく算出対象0件を意味する」「高い/低いを短絡的に良し悪しと結びつけない」「独立したCLIスクリプト+`cycle_health_runs`テーブル+`cycle_health_metrics.py`(純粋関数)/`cycle_health_runner.py`(I/O)の3層分離」という設計パターンを、本タスクでもそのまま踏襲した。

---

## 1. persona.mdに追加した言い回しルールの内容

`docs/persona.md`に**15章「調べた情報の伝え方」**を新設した(既存の12〜14章と同じ「新規追加」表記のスタイルを踏襲)。

### 1.1 ルールの要点

- **多用してよいフレーズ**: 「調べてみたところ」「最近の情報によると」「〇〇によれば」「確認したところ」
- **5章(確信度の伝え方)との関係を明記**: 「調べた」という前置きは、事実層/傾向層/仮説層という既存の確信度階層とは独立した軸であり、両方を組み合わせて使う(例: 「調べたら〇〇でした」= 事実層相当、「調べてみたのですが、〇〇のようです。まだ確証はないんですが」= 仮説層相当)
- **過剰な繰り返しの禁止**: 1ターンで「調べた」を何度も繰り返さない。直前の文脈から検索済みであることが明らかな場合は前置き自体を省略してよい
- **G-3/G-4の監査結果との整合性**: 「情報源はあるが使い方が不正確」(G-4)・矛盾検出(G-3)の場合は、5章の確信度表現(ヘッジ)を、「調べた」という前置きよりも優先する

### 1.2 サンプル文面(依頼書要件1)

```
悪い例: 〇〇の価格は5万円です。
良い例: 調べてみたところ、〇〇の価格は5万円のようです。
```

```
海星「このカメラの最新モデルの価格っていくら?」
シグマリス「調べてみたところ、公式サイトでは12万円前後のようですね。
           ただ、在庫状況までは確認できませんでした。」
```

```
海星「(直前に「価格調べて」と頼んだ流れで)で、いくらだった?」
シグマリス「12万円前後でした。在庫はちょっと分からなかったです。」
(直前の文脈で検索済みと分かるため、前置きを省略した例)
```

### 1.3 実際の生成プロンプトへの反映(重要な実装判断)

**persona.md全文は毎ターン注入されない**(BA4 追補7、`system_override`の4000文字上限により、persona.mdは短い方針への置換が既に行われている——`docs/sigmaris/phase_ba4_report.md` 7章参照)。そのため、15章を書き加えるだけでは、実際の生成には一切反映されない。

**判断根拠**: Phase S-3の`_build_dissent_context()`・B16の`_build_goal_alignment_context()`が、persona.mdの該当章を名指しで参照する指示文を、それぞれの注入チャネル(`preference_patterns_context`)へ直接書き込む、という既存パターンを確認し、本タスクでも同じ手法を踏襲した。`evidence_search.py::build_evidence_context()`(G-2が新設、Evidenceを応答生成プロンプトへ注入する関数)の末尾へ、以下の1文を追加した。

```python
"persona.md 15章(調べた情報の伝え方)に従い、「調べてみたところ」のような、"
"今回調べた情報であることが自然に伝わる言い回しを使ってください。ただし1ターンで"
"何度も繰り返さないこと。"
```

これにより、Evidenceが存在するターン(G-1の`needs_search=true`判定があったターン)でのみ、この指示が実際のプロンプトへ注入される——通常の会話には一切影響しない(要件5)。

---

## 2. 3つの指標の算出ロジック

新設ファイル: `backend/app/services/grounding_health_metrics.py`(純粋関数)・`grounding_health_runner.py`(I/O)・`grounding_health_runs_store.py`(永続化)。`cycle_health_metrics.py`/`cycle_health_runner.py`/`cycle_health_runs_store.py`(Phase R)と同じ3層分離を踏襲した。

### 2.1 共通: claim単位のログを「1ターン」へ再構成する

`sigmaris_citation_audit_log`はclaim単位のフラットなログであり、「1回のやり取り」という単位は列として持たない。`citation_audit.persist_citation_audit()`が1ターン分の全claimを**1回のバルクINSERT**で書き込んでおり、Postgresの`now()`は同一トランザクション内の全行で同じ値になるため、**同じターンのclaimは常に同一の`created_at`を持つ**。`(thread_id, created_at)`の組をキーにグルーピングすることで、新しい列・新しいデータ収集を一切追加せず、既存ログの構造だけから「1ターン」単位を安全に再構成した(依頼書「新しいデータ収集の仕組みを追加しないこと」への対応)。

### 2.2 Citation Precision(引用精度)

```
precision = faithful_count / (faithful_count + distorted_count)
```

分母0件(引用されたclaimが1件もない=全て`not_used`)の場合はNone(0%と区別)。

**判断根拠(`not_used`を分母から除外)**: `not_used`は「Evidenceとして取得されたが、応答内では触れられなかったclaim」であり、検索結果を全て使い切らないこと自体はG-2の設計上正常な挙動である。「引用の使い方」の精度を測る本指標の対象を、実際に使われたclaim(`faithful` + `distorted`)に限定した。

### 2.3 Search Trigger Rate(検索発動率) — 下限近似値であることの明記

```
rate = audited_turns(監査ログに記録が残ったターン数) / total_turns(全アシスタント発言数)
```

**【重要】この指標は、G-1の`needs_search=true`判定そのものの下限近似値である。** G-1の判定結果は現状どのターンについても永続化されていない(`chat.py`の`assistant_message.metadata`には`routeIntent`/`routeReason`/`routeSource`のみが記録され、`search`判定は含まれない)。依頼書「新しいデータ収集の仕組みを追加しないこと」の制約により、本タスクではこれを追加していない。

そのため、実際に`needs_search=true`と判定された件数の代わりに、「実際に`sigmaris_citation_audit_log`へ記録が残ったターン数」を分子として使う。以下の場合に実際の発動件数より**少なく**カウントされる(下限近似):

- `needs_search=true`と判定されたが、G-2のWeb検索自体が失敗した場合
- 検索は成功したが、引用(citation)を含まない応答だった場合(`_extract_cited_spans()`が空リストを返した場合)

いずれの場合もG-4の監査自体が発火せず、監査ログに記録が残らない。**判断根拠(この近似のまま実装した理由)**: 真の値を得るには、G-1の判定結果を`chat_messages.metadata`へ新たに永続化する設計変更が必要になるが、これは依頼書が明示的に禁じる「新しいデータ収集の仕組み」に該当すると判断した。6章の設計メモで、この制約を解消する将来案を具体的に記載する。

### 2.4 Contradiction Rate(矛盾検出率)

```
rate = flagged_turns / audited_turns(検証が行われたターン数)
```

「フラグが立った」の判定は、そのターンのいずれかのclaimが`usage="distorted"`(G-4)、またはそのターンの`critique_verdict`が`"no_contradiction"`以外(G-3)のいずれか一方でも該当すれば真とする——G-4の`select_guidance_note()`が採用するOR方式の判断を、指標の集計でも一貫して適用した。

**判断根拠(分母を「検証が行われたターン」に限定)**: 全ターンを分母にすると、「そもそも検証が行われなかった」ケースと「検証したが問題なしだった」ケースが区別できなくなり、指標の意味が「矛盾検出率」から別の指標にすり替わってしまう。分母はSearch Trigger Rateの`audited_turns`と同じ値になる。

---

## 3. 実行方法(CLIコマンド)

```bash
cd backend
python scripts/run_grounding_health.py
python scripts/run_grounding_health.py --window-days 60
python scripts/run_grounding_health.py --dry-run   # DBに記録せず標準出力のみ
```

`run_cycle_health.py`と完全に同じ引数体系(`--window-days`・`--notes`・`--dry-run`)、同じ環境変数(`SUPABASE_SERVICE_ROLE_KEY`等)を採用した。標準出力は、3指標それぞれについて「値がNoneの場合は算出対象0件を意味する」「Search Trigger Rateは下限近似値である」という注意書きを、値そのものと併記する形にした——依頼書要件4(「高い/低い=良い/悪いを短絡的に決めつけず、その意味を正確に説明できる設計にすること」)への対応であり、Phase Rの`run_cycle_health.py`が既に確立している、指標の値の直後に解釈上の注意を1行添えるという表示スタイルをそのまま踏襲した。

**新設マイグレーション**: `supabase/migrations/202607240051_grounding_health_runs.sql`(作成のみ、適用は運用者側に委ねる)。`sigmaris_cycle_health_runs`と同じ「1回の実行 = 1行、見出し指標は実列、詳細は`details` jsonb」という設計を踏襲した、独立した新規テーブルとした——判断根拠は、RC指標(循環の健全性)・C-mini/C-full(記憶検索精度)・Grounding指標(検索・引用精度)が測定対象の異なる別系統の指標であり、同じテーブルに混在させると「どの指標体系の行か」が読み取り時に曖昧になるという、`sigmaris_cycle_health_runs`のマイグレーション自身が既に述べている理由をそのまま適用した。

---

## 4. テスト結果

`test_phase_g5_grounding_health.py`として22件のテストを作成した(scratchディレクトリ)。

```
ComputeCitationPrecisionTests (4件)
  PASS: 引用されたclaimが0件の場合、precisionがNoneになること
  PASS: 全てfaithfulな場合、precision=1.0になること
  PASS: faithful/distortedが混在する場合、正しい比率になること
  PASS: not_usedのみの場合もprecisionがNoneになること(分母から除外)

ComputeSearchTriggerRateTests (4件)
  PASS: 全ターン数が0の場合、rateがNoneになること
  PASS: 監査ログが空の場合、rate=0.0になること
  PASS: 【重要】同一(thread_id, created_at)の複数claimが1ターンとして
        正しくグルーピングされること(バルクINSERTのcreated_at一致を
        利用したターン再構成ロジックの直接検証)
  PASS: 異なるターンが正しく別々にカウントされること

ComputeContradictionRateTests (5件)
  PASS: 監査ログが空の場合、rateがNoneになること
  PASS: クリーンなターンはフラグが立たないこと
  PASS: distortedなclaimがあるターンはフラグが立つこと
  PASS: 【重要】全claimがfaithfulでも、critique_verdictが矛盾を示す場合は
        フラグが立つこと(G-3・G-4のOR方式判定の直接検証)
  PASS: critique_verdictが欠損している場合、no_contradiction相当として
        扱われること
  PASS: 複数ターンが混在する場合の比率が正しく算出されること

RunGroundingHealthTests (2件)
  PASS: 3指標が正しく統合されて返ること
  PASS: 監査ログ取得・ターン数カウントの両方に、正しい期間の起点が
        渡されること

RecordGroundingHealthRunTests (2件)
  PASS: 正しいペイロード形状でPOSTされること
  PASS: HTTP失敗時、例外を伝播させずNoneを返すこと

GetCitationAuditLogSinceTests (2件、citation_audit.pyへ新設した読み取り
  ヘルパー)
  PASS: sinceフィルタが正しくクエリに含まれること
  PASS: 失敗時に空リストを返すこと

CountAssistantMessagesSinceTests (2件、app_chat_data.pyへ新設したカウント
  ヘルパー)
  PASS: role=assistant・user_idスコープで正しくカウントされること
  PASS: 非リスト結果の場合、0を返すこと

22 passed
```

既存の`backend/tests/`(16件)、G-1〜G-4の全テスト(102件)、直近のPhase S・R・BA4系・nano-tier移行の既存テスト一式(206件)も全て再実行し、リグレッションは確認されなかった。

```
22(本タスク) + 302(既存の関連テスト一式、G-1〜G-4含む) = 324 passed(合算実行)
```

`scripts/run_grounding_health.py --help`の実行により、CLIの引数解析・ヘルプテキスト表示が正しく機能することも確認した。

**実モデルAPI・実データベースでの検証は行っていない。** テストは`supabase_rest`のHTTPクライアントをモックする形にとどまる(依頼書の注意事項通り、追加のサーバーアクセス・APIキー取得は試みていない)。

---

## 5. Phase G全体(G-1〜G-5)を通じての振り返り・残っている懸念事項の総まとめ

### 5.1 各フェーズの到達点

| Phase | 到達点 | 主な設計判断 |
|---|---|---|
| G-1 | 「検索が必要か」の軽量判定。既存の`classify_chat_intent()`(nano-tier)へ相乗り | ルールベース(鮮度キーワード等)+LLM判定のハイブリッド。新規LLM呼び出しゼロ |
| G-2 | 実際のWeb検索実行+構造化されたEvidence(claim/source_url/source_title/retrieved_at)への変換 | 既存のcuriosity_engine.pyは汎用検索に不向きと判断し、OpenAI Responses APIのweb_searchツールを新規採用。出典はAPIの実引用のみ使用 |
| G-3 | 応答全体とEvidence全体の矛盾を検出するSelf-Critique検証 | B11のConfidenceTier・ヘッジ文言を実際に再利用。ストリーミング経路は8章の教訓によりadvisory-onlyに限定 |
| G-4 | claim単位の使われ方監査(二段階目)。B11連携の仕上げ、G-5向けの永続化 | G-3と重複しないclaim粒度のチェック。G-3・G-4を並行実行しレイテンシを最適化 |
| G-5 | persona.mdへの言い回しルール追加、継続的な精度測定(3指標) | G-4の監査ログのみを使い新規データ収集ゼロ。Phase Rの3層分離パターンを踏襲 |

### 5.2 Phase G全体を通じた一貫した設計哲学

- **「Evidenceが存在する場合にのみ発動し、通常の会話には一切のオーバーヘッドを与えない」**という原則が、G-1〜G-5の全段階で一貫して守られた。`needs_search=false`のターンには、G-1のルールベース判定以外、一切の追加コストが発生しない。
- **既存資産の再利用が、単なる方針ではなく、実際に毎回具体的な調査・判断を伴って実践された**: G-2でのcuriosity_engine.py不採用の判断(調査の上で理由を明記)、G-3・G-4でのB11(`confidence_guidance_note()`)の直接再利用、G-5でのPhase R 3層分離パターンの踏襲。
- **レイテンシへの警戒が、単なる見積もりに留まらず、実際の設計変更を伴って反映された**: G-3でのストリーミング経路のadvisory-only化(BA4 8章の実際の障害記録を根拠とした判断)、G-4でのG-3・G-4並行実行化。

### 5.3 残っている懸念事項(既存分の再掲+G-5での新規分)

1. (G-1から継続)ルールベースのキーワードリストが、日本語の口語表現のロングテールをカバーしきれない。
2. (G-2から継続)`search_context_size="low"`が原因で、情報が不足するケースが実運用でどの程度発生するかは未検証。
3. (G-3から継続)実際の主要経路(ストリーミング)では、矛盾検出時の実際の応答書き換えが行われない(advisory-onlyのため)。
4. (G-4から継続)`audit_citation_usage()`の「文脈からの逸脱」判定基準が抽象的で、実モデルでの検証ができていない。
5. **(G-5で新規)Search Trigger Rateは下限近似値であり、真の発動率とは乖離しうる。** 2.3節で述べた通り、G-1の判定結果自体を永続化していないことに起因する。6章の設計メモに、この制約を解消する具体案を記載する。
6. **(G-5で新規)Citation Precision・Contradiction Rateは、あくまでG-3/G-4というAIによる自動判定の結果を集計したものであり、その自動判定自体の精度(4)が未検証である以上、指標自体にもその不確実性が引き継がれる。** 「measuring the measurer」の限界として認識しておく必要がある——将来、人手によるサンプル検査(例えば`sigmaris_citation_audit_log`から一定数を無作為抽出し、実際にclaimの使われ方が正しく分類されているかを目視確認する)を行い、G-3/G-4自体の判定精度を検証する価値がある。
7. **(G-5で新規)`sigmaris_grounding_health_runs`は、Phase R同様「直近N日」を毎回計算し直す設計であり、RC-3/RC-5のような「前回実行との比較」機能は持たない。** 本タスクの3指標には、RC-3(信念の反転)・RC-5(急激な悪化検知)に相当する時系列比較の要求が無かったため実装しなかったが、将来的に「先月と比べて引用精度が悪化していないか」を自動検知したい場合は、`get_recent_grounding_health_runs()`(既に用意済み)を使った比較ロジックの追加を検討する余地がある。

---

## 6. Phase RとPhase Gの、将来的な統合可能性についての設計メモ

依頼書の要求に従い、実装は行わず、設計メモとして記載する。

### 6.1 現状の関係

Phase R(RC指標)・C-mini/C-full(eval_runs)・Phase G(Grounding指標)は、意図的に**独立したテーブル・独立したCLIスクリプト・独立した指標体系**として実装されている。3者はいずれも「Sigmaris自身の振る舞いを測定する」という大枠の目的は共有するが、測定対象のレイヤーが異なる。

| 指標体系 | 測定対象 | テーブル |
|---|---|---|
| RC指標(Phase R) | Experience→Memory→...→Actionという循環自体の健全性 | `sigmaris_cycle_health_runs` |
| eval_runs(C-mini/C-full) | 記憶検索(B群)の精度 | `sigmaris_eval_runs` |
| Grounding指標(Phase G) | 検索・引用の精度 | `sigmaris_grounding_health_runs` |

### 6.2 統合の動機になりうるシナリオ

将来、以下のような問いに答えたくなった場合、3者を横断した分析が必要になる。

- 「Grounding指標が悪化した時期に、RC指標(特にRC-2、時間的一貫性)も同時に悪化していないか」——検索結果の混入がchat_messagesの時系列に何らかの影響を与えていないかを確認したい場合
- 「Contradiction Rateが高いターンは、そのままsigmaris_experienceへ記録され、Phase Rの循環(RC-1)に乗るのか、それとも矛盾検出によって循環から除外されるのか」——G-3/G-4の検証結果が、Phase Rが測る循環自体にどう影響するかを追跡したい場合

### 6.3 統合の設計案(未実装、案のみ)

**案A: 共通の「measurement run」メタテーブルを新設し、各指標体系のrunsテーブルへ外部キーで紐づける。** `sigmaris_measurement_runs(id, run_type, run_at)`のような薄いテーブルを作り、`sigmaris_cycle_health_runs`/`sigmaris_eval_runs`/`sigmaris_grounding_health_runs`それぞれに`measurement_run_id`列を追加する。判断根拠: 既存の3テーブルの構造(見出し指標を実列に持つ、というスタイル)を一切変更せずに、後から横断クエリを可能にできる、最も非破壊的な統合方法。

**案B: 定期実行を1つのCLIスクリプトへ統合し、実行タイミングだけを揃える。** `run_cycle_health.py`・`run_eval.py`・`run_grounding_health.py`を、同じcronジョブ(例えば週次)から順に呼び出すラッパースクリプトを新設する。テーブル構造は現状のまま独立を維持しつつ、`run_at`が近い実行同士を後から時系列で突き合わせやすくする。判断根拠: 実装コストが最も低く、テーブル設計への影響がゼロ。ただし「同時刻に実行された」という保証がラッパー側の運用に依存する、緩い紐付けに留まる。

**案C(非推奨として明記): 3つの指標体系を1つのテーブルへ統合する。** 検討した上で不採用と判断した——`sigmaris_cycle_health_runs`のマイグレーションコメントが既に指摘する通り、測定対象の異なる指標を1つのテーブルへ混在させると、「どの指標体系の行か」が読み取り時に曖昧になる。この既存の判断根拠は、Phase G追加後も変わらず有効である。

**現時点での推奨**: 案Aが最もクリーンだが、実際に横断分析が必要になるまでは過剰実装になりうる。統合の実需が具体的に生じた時点(例えば上記6.2節のシナリオが実際に運用上の疑問として浮上した時)に、案Aを実装するのが妥当と考える。

---

## 7. マージについて

「テスト・検証」章の要件をすべて満たしていることを確認した(persona.mdへのルール追加・言い回しの反映・3指標の算出・CLIからの実行・既存テストの回帰確認、いずれも達成)。依頼書の指示通り、確認を待たずmainへマージ・プッシュする。これをもって、Phase G(G-1〜G-5、Trigger Detection・Evidence Structuring・Self-Critique検証・Two-Layer Citation Audit・言い回し調整+継続測定)が完了する。
