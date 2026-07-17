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
