# 緊急修正1 実施報告: `facts_ctx`/`trends_ctx`が上書きで握りつぶされていた問題

対象ブランチ: `fix-facts-trends-context-overwrite`(mainからfork)

`docs/sigmaris/incident_response_latency_investigation.md`の調査で発見された
問題への対応。

---

## 1. 発見した実態の詳細

### 上書きの具体的な発生箇所

`backend/app/services/orchestrator/service.py`の`run_orchestrator_chat`・
`run_orchestrator_chat_stream`は、いずれも同一のパターンで以下を行っていた
(修正前、行番号は`run_orchestrator_chat`側):

```python
# 812行目〜
profile_context = build_profile_context(fact_profile)
if profile_context and len(profile_context) > 200:
    profile_context = profile_context[:200] + "…"

facts_ctx = build_facts_context(fact_items or [], top_n=5)      # top-5事実(重要度順)
if facts_ctx and profile_context:
    profile_context = profile_context + "\n\n" + facts_ctx
elif facts_ctx:
    profile_context = facts_ctx

trends_ctx = _build_trends_context(active_trends)                # top-3傾向
if trends_ctx and profile_context:
    profile_context = profile_context + "\n\n" + trends_ctx
elif trends_ctx:
    profile_context = trends_ctx

# 829行目 ← ここで上記の連結結果が丸ごと破棄される
profile_context = await _build_memory_context(
    jwt=jwt, user_id=user_id, messages=messages,
    fact_profile=fact_profile, fact_items=fact_items, active_trends=active_trends,
    ...
)
```

`_build_memory_context()`自体の内部(修正前)は、次のようになっていた:

```python
async def _build_memory_context(*, jwt, user_id, messages, fact_profile,
                                 fact_items, active_trends, ...) -> str | None:
    profile_context = build_profile_context(fact_profile)   # ← fact_profileから再計算するだけ
    ...(200文字丸め)...
    # fact_items, active_trends はこの関数の引数として受け取られているが、
    # 関数本体のどこにも参照されていなかった(デッドパラメータ)。
    relevant_context = ...  # search_with_decomposition() によるRAG検索結果
    ...
    return profile_context + "\n\n" + relevant_context  # facts_ctx/trends_ctxは一切含まれない
```

つまり:
1. 呼び出し元(`run_orchestrator_chat`/`_stream`)が`facts_ctx`(top-5事実)・
   `trends_ctx`(top-3傾向)を`profile_context`に連結する。
2. その直後、`_build_memory_context()`の戻り値が同じ変数`profile_context`に
   **再代入**される。
3. `_build_memory_context()`は`fact_items`・`active_trends`を引数として受け
   取ってはいたが、関数内で一切使用しておらず、内部で`build_profile_
   context(fact_profile)`を独自に再計算していただけだった。
4. 結果として、呼び出し元が組み立てたfacts_ctx・trends_ctxの内容は、スケジ
   ュールエージェントへ送られる最終的なプロンプト(`user_profile_context`)
   には一切反映されていなかった。

この挙動は`run_orchestrator_chat`・`run_orchestrator_chat_stream`の**両方**で
全く同一に発生していた(コードが完全に重複していたため)。

### 意図の判断

`_build_memory_context()`が`fact_items`・`active_trends`を引数として受け取っ
ているにもかかわらず内部で未使用だったという事実、およびコメント「Build
lightweight context (profile 200 chars, facts top 5, trends top 3)」が明確
に3つの要素を意図していたことから、**当初は「profile+facts+trends」という
静的な基礎コンテキストがあり、そこにPhase B1のハイブリッド検索結果
(`relevant_context`)を追加で載せる、という加算的な設計だった**と判断した。
`_build_memory_context()`導入(Phase A5〜B1の頃)の際、呼び出し元の`facts_
ctx`/`trends_ctx`の組み立てをこの関数の内部に移す作業が中途半端なまま止ま
り、`fact_items`/`active_trends`だけが引数として渡されるようになったものの、
関数内部でそれらを実際に使う処理が移植されずに残った、というのが最も自然な
経緯と考えられる。

---

## 2. 選択した修正方針とその根拠

指示書の選択肢(a)(`_build_memory_context()`の戻り値にfacts_ctx/trends_ctx
を含める)を採用した。

**選択肢(b)(呼び出し元での連結)を選ばなかった理由**: `_build_memory_
context()`は内部で`build_profile_context(fact_profile)`を独自に再計算して
いるため、仮に呼び出し元で「呼び出し元のprofile_context(facts_ctx/trends_
ctx込み) + `_build_memory_context()`の戻り値」を単純に連結すると、
`build_profile_context(fact_profile)`から生成される同一のプロフィール文
(200文字に丸めた同じ文字列)が**プロンプト中に2回重複して出現する**ことに
なる。これは指示書が禁じる「重複した情報が二重にプロンプトに含まれる」状態
を新たに作り出してしまうため、選択肢(b)は採用しなかった。

選択肢(a)であれば、`_build_memory_context()`が既に受け取っていた`fact_
items`・`active_trends`という(元から意図されていたと考えられる)引数をそ
のまま活かして、関数内部の唯一の`profile_context`変数に対して facts_ctx→
trends_ctx→relevant_contextの順で一度だけ組み立てることができ、プロフィー
ル文の重複も発生しない。

### 実際の修正内容

- `_build_memory_context()`内部で、`build_profile_context(fact_profile)`の
  直後に、呼び出し元にあった`facts_ctx`/`trends_ctx`の組み立てロジックをそ
  のまま移植した(`build_facts_context(fact_items or [], top_n=5)`→
  `_build_trends_context(active_trends)`→既存の`relevant_context`という順
  序)。
- `run_orchestrator_chat`・`run_orchestrator_chat_stream`双方から、重複して
  いた`facts_ctx`/`trends_ctx`の組み立てブロックを削除し、`_build_memory_
  context()`の呼び出し1行のみに置き換えた。
- `build_profile_context`・`build_facts_context`・`_build_trends_context`の
  import/定義自体はどちらも他で使われていないため、削除はせず、呼び出し箇所
  を`_build_memory_context()`内の1箇所に集約した(各ヘルパーの呼び出し回数
  が、修正前の「呼び出し元1回+関数内0回」から「呼び出し元0回+関数内1回」に
  変わっただけで、正味の呼び出し回数は変わっていない)。

---

## 3. 重複確認の結果

`facts_ctx`(top-5、`importance_score × confidence`降順)と`relevant_
context`(現在の質問に対するハイブリッド検索結果、B7〜B12適用後)は、**選択
基準が異なる別々の抽出**であることを確認した:

- `facts_ctx`: `user_fact_items`全体から、質問の内容に関係なく「重要度×確
  信度」が高い上位5件を機械的に抽出する、**質問非依存の基礎コンテキスト**。
- `relevant_context`: 直近のユーザー発言に対して、ベクトル+trigramのハイブ
  リッド検索(Phase B1)・必要に応じた分解(B7)・リランク(B10)・信頼度判
  定(B11)・圧縮(B12)を経て抽出される、**質問依存の検索結果**。

両者は選択ロジックが異なるため、**同一の個別事実が偶然両方に出現する可能性は
あるが、それは設計上許容される重複**と判断した(例:「AdFlow AIを軌道に乗せ
る」という目標がtop-5事実にも入り、かつ「AdFlow AIについて」という質問への
関連事実としても検索されるケース)。これは今回の修正で新たに生じた重複では
なく、facts_ctx/trends_ctxとrelevant_contextが加算的に共存するという、修正
前から意図されていた設計の性質そのものである。個別事実の重複排除(同一
`fact_key`が両方に出現する場合に片方を間引く等)は、本タスクの指示書が求める
「二重に含まれないこと」を、ブロック単位(facts_ctx/trends_ctx/relevant_
contextという3つの異なるセクションが同じ内容を丸ごと重複して持たないこと)
と解釈し、個々の事実単位での重複排除までは過剰な実装と判断し、行っていない。
テストでは、3つのセクション見出し(「記憶した事実」「傾向トピック」「関連す
る事実記憶」)がそれぞれ1回ずつ独立して出現することを確認した(5章)。

---

## 4. Phase A2キャッシュ構造への影響確認結果

`schedule_agent_client.py::_build_system_override()`における`user_profile_
context`(=`_build_memory_context()`の戻り値)の**位置**(常に最初のパー
ツ)は、今回の修正の前後で一切変わっていない。また、修正前から`_build_
memory_context()`の戻り値には既に`relevant_context`(質問ごとに変わる検索
結果)が含まれていたため、`user_profile_context`スロットは**修正前から既に
「毎ターン変動しうる」ブロックだった**。今回の修正はそこにfacts_ctx(事実の
更新頻度に応じて変わる、facts_ctxより変動は緩やか)・trends_ctx(週次更新程
度で緩やか)を、relevant_contextより**前**に追加しただけであり、ブロック内
の並びも「比較的安定→比較的変動」の順を保っている。

したがって、**Phase A2が意図するプレフィックスキャッシュの構造(`chat_
prompts.py`の「安定した内容を先頭に」という設計)に対して、今回の修正による
新たな悪影響はない**。既存の`incident_response_latency_investigation.md`5
章で指摘した「`user_profile_context`スロット自体がRAG結果を含むため毎ターン
変動し、それより後ろのブロックのキャッシュ効果を妨げている可能性がある」と
いう懸念は、今回の修正の前から存在していた別の問題であり、今回のタスクの範
囲外(そちらは別途、優先度3の改善提案として整理済み)。

---

## 5. テスト結果

mock/単体テストで確認した(5ケース、スクラッチテスト、backend/tests/には未
コミット)。

- `_build_memory_context()`が、質問文がない(=`relevant_context`が生成され
  ない)場合でも、facts_ctx・trends_ctxの内容を含んだ文字列を返すこと(修正
  前は空のprofile_contextのみが返っていたケースの直接確認)
- `_build_memory_context()`が、質問文があり検索結果もある場合、facts_ctx・
  trends_ctx・relevant_contextの3セクション全てが同時に含まれること(重複な
  く共存することの確認)
- facts_ctx・trends_ctx・質問文のいずれも無い場合、`None`を返すこと(既存の
  空振り挙動が壊れていないことの確認)
- `fact_items=[]`・`active_trends=[]`でも例外を投げないこと
- ソースコード上、`build_facts_context()`/`_build_trends_context()`の呼び出
  し箇所が、`_build_memory_context()`内の1箇所ずつに集約されており、`run_
  orchestrator_chat`/`_stream`側に重複した呼び出しが残っていないこと

```
5 passed (新規)
```

### 既存機能への非破壊確認

これまでの全B群スクラッチテスト・facts cache修正テスト・Phase B9関連テスト
(orchestrator wiring含む)を合わせて再実行し、全て成功することを確認した。

```
195 passed (スクラッチテスト全体、新規5件含む)
8 passed (backend/tests/、既存の安定回帰スイート)
```

`git diff --ignore-all-space --stat`でCRLF/LFノイズがないことも確認した(差
分は`backend/app/services/orchestrator/service.py`1ファイルのみ、36行追加・
33行削除)。

---

## 6. C-miniの`memory_f1_score`への影響についての所見(理論的な見通し)

実測は次回のbaseline取得時になるが、理論的には以下のように予測する:

- **改善方向に働く可能性が高い**: 修正前は、質問と直接関連しない(=RAG検索
  に引っかからない)が重要度の高い事実(例:目標・自己紹介的な情報)が、
  `relevant_context`が生成される限りプロンプトから完全に欠落していた。特に
  「質問文に含まれるキーワードとは一致しないが、常に踏まえておくべき重要な
  事実」に関する質問(例:直接的なキーワードを含まない曖昧な質問)では、
  `memory_f1_score`の再現率(recall)側が本来より低く出ていた可能性がある。
- **一方で、過度な改善は期待しにくい**: `facts_ctx`はtop-5固定であり、B1の
  ハイブリッド検索(`relevant_context`)ほど質問に適応的ではない。既にRAG検
  索側で十分にカバーされていた質問については、今回の修正による`memory_f1_
  score`への影響は限定的と考えられる。
- **`response_error_rate`への影響は中立と予想**: 追加される情報は既存の
  `user_fact_items`から抽出される事実の範囲内であり、新しい種類の情報が増
  えるわけではないため、応答の正確性を悪化させる方向には働きにくいと考えら
  れる。
- **プロンプト長がわずかに増える**: facts_ctx(最大5件)・trends_ctx(最大
  3件)の分だけ、システムプロンプトが常に数百文字程度増える。B12の圧縮
  (`compress_memories_if_needed`)は`relevant_context`側のみに適用されてお
  り、facts_ctx/trends_ctxには適用されないため、token予算への影響は軽微だ
  が皆無ではない。

いずれも実測(`run_eval.py`によるbaseline再取得)でのみ確定できる推測であ
り、次回のPhase C関連タスクでの実行時に、この修正の前後比較として合わせて確
認することを推奨する。

---

## Related Documents

- `docs/sigmaris/incident_response_latency_investigation.md`(本問題の発見
  元)
- `docs/sigmaris/phase_c_mini_report.md`(`memory_f1_score`の定義)
- `docs/sigmaris/phase_b17_report.md`(`importance_score`、facts_ctxの並び
  替え基準)
- `docs/sigmaris/phase_b12_report.md`(`compress_memories_if_needed`が
  `relevant_context`側にのみ適用される設計)
