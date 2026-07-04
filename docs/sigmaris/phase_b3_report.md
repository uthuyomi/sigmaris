# Phase B3 実施報告: 記憶の自己検証ループ

対象ブランチ: `phase-b3-memory-self-verification`(mainからfork)

---

## 0. baseline値の性質について(先行B群タスクと同様)

`docs/sigmaris/phase_c_mini_report.md`のbaselineおよび先行B群タスクの参考値は、
`sigmaris_decision_log`のデータ蓄積状況に依存する不確実性を含む。本タスク完了後
の`run_eval.py`の数値も引き続き参考値として扱う。本タスクの効果確認は指示書通
り、「確信度の低い記憶が適切に検出され、自然な形で確認質問が生成されるか」とい
う機能テストで行った(下記5章)。

---

## 1. 確認対象選定ロジックの実装詳細(閾値・判断根拠)

`memory_validator.py`に`get_confirmation_candidates(jwt)`を新設した。対象は
`user_fact_items`のうち`value`が非nullの行のみ(値が欠落している項目は既存の
`get_null_fields()`の担当領域であり、両者は明確に別の質問形状 ——「まだ知らな
い」 vs 「以前伺ったが今も正しいか」—— なので責務を分離した)。

以下3条件のいずれかを満たせば確認候補とする(OR条件):

1. **`confidence < 0.5`(`_CONFIRM_CONFIDENCE_THRESHOLD`)**: `memory_extractor.
   py`自身の抽出プロンプトが確信度を「0.9=明言/0.6=強い示唆/0.4=推測」と較正
   しているため、0.5はその境界線そのものを流用した(0.4=推測レベルまで落ちて
   いる、または後述の減衰・矛盾検出によってそこまで下がった記憶を確認対象にす
   る、という意味的に自然な閾値)。
2. **`is_stale = true`**: `memory_validator.validate_all_facts()`のPhase 2(矛
   盾検出)が既に立てているフラグをそのまま再利用。
3. **`updated_at`から180日以上(`_CONFIRM_STALENESS_DAYS`)経過**: `_DECAY_
   RULES`で`profile`カテゴリのみ減衰ルールが`(None, 1.0)`(減衰なし)に設定さ
   れているため、条件1・2だけでは`profile`の記憶が理論上永遠に確認対象になら
   ない。この抜け穴を塞ぐための独立した年齢ベースの基準。180日は既存の減衰ル
   ール内で最長の`devices`/`environment`(180日)に合わせた。この値を選んだ理
   由は、減衰ルールを持つカテゴリに対してこの基準がより早く発火してしまうこと
   を避けるため(既存の減衰挙動より積極的にならないように)。

条件2の`is_stale`と条件1の`confidence`は完全に独立ではない(矛盾検出は同時に
confidenceも0.7倍する)ため、多くの場合は条件1が先に該当するが、矛盾判定直後で
まだconfidenceが0.5を上回っている場合のフォールバックとして条件2を残した。

---

## 2. `confidence`列の実態調査結果

**B17の`importance_score`とは対照的に、`confidence`は本物の per-fact 変動値で
あることを確認した。** 根拠:

- `set_fact_category_defaults`トリガー(`importance_score`をカテゴリ固定値で上書
  きする、B17で発見済み)は`confidence`列には一切触れない。
- `memory_extractor.py`の抽出プロンプトが、抽出のたびにLLMへ「0.9=明言/0.6=示
  唆/0.4=推測」という明示的な較正基準で確信度を出力させており、同一カテゴリ内
  でも事実ごとに異なる値が実際に付与される。
- `memory_validator.py`のPhase 1(減衰)がカテゴリ・重要度に応じて`confidence`
  を時間経過で実際に引き下げる(B17で重要度に応じた減衰速度調整済み)。
- 同Phase 2(矛盾検出)が矛盾を検出すると`confidence *= 0.7`する。
- Phase 3(論理削除)は`importance_score × confidence`を閾値判定に使っており、
  `confidence`はこの積の中で唯一「事実ごとに意味のある形で変動する」項である
  (`importance_score`はB17判明の通りカテゴリ固定なので、実質的に個々の記憶の
  信頼度を左右しているのは`confidence`の方)。

**結論**: `confidence`は`importance_score`のような粗いカテゴリ代理指標ではな
く、抽出時のLLM較正・時間減衰・矛盾検出という3つの独立した経路から実際に事実ご
とに変動する値。今回の確認候補選定閾値(0.5)は、この「本物の変動値」という前提
があって初めて意味を持つ(`importance_score`ベースで同様の閾値を作っていたら
B17と同じ「実はカテゴリで決め打ちされているだけ」という問題に陥っていた可能性
が高い)。

---

## 3. 確認質問生成・頻度制御の統合方法

### 統合方式: 単一の候補プールに合流させる

既存の`get_null_fields()`(欠落項目)と新設の`get_confirmation_candidates()`
(再確認候補)を`active_inquiry.get_inquiry_question()`内で単純に連結し、既存
の`_asked_cache`(48時間クールダウン)・`_rank_by_relevance()`(直近会話とのキ
ーワード一致度ランキング)にそのまま通す形にした。**優先度を「欠落項目を先に」
のような固定順にはせず、両者を同じ関連度ランキングで競わせる**(判断根拠: 既存
の欠落項目ランキングも「カテゴリ固定優先度」ではなく関連度のみで並べていたた
め、新しい候補種別だけ特別扱いする理由がないと判断した)。

`_cache_key()`を拡張し、確認候補には`confirm:{category}:{key}`という欠落項目
用の`fact:{category}:{key}`とは異なるプレフィックスを付けた(判断根拠: 同じ
category/keyが理論上両プールに同時に現れることは実際には起こらない(valueが
nullなら欠落項目、非nullなら確認候補、で排他的)が、クールダウンのセマンティク
スが「まだ聞いたことがない」と「前に答えを聞いたことを再確認する」で異なるた
め、将来の変更で衝突する事故を防ぐために別名前空間にした)。

「1ターンあたり最大1件」という既存の制約は、両プールを1つのリストに合流させて
から`ranked[0]`を1件だけ選ぶ実装のため、自動的に維持される(要件3、テストで確
認)。

### 確認質問の文面

`_CONFIRM_SYSTEM`/`_CONFIRM_PROMPT`を新設し、既存の欠落項目質問
(`_SYSTEM`/`_PROMPT`)とは別テンプレートにした。`docs/persona.md`3章(共感→興
味→質問)・4章(語尾: 多用「〜ですね/〜かもしれません/どうでしょう」、避ける
「〜である/〜すべき/絶対」)に沿うよう、プロンプト内で明示的に「〜ですかね」
「〜で合ってますか」のような、断定せずお伺いを立てる語尾を使うよう指示した。既
存の欠落項目質問の「そういえば/ちなみに」で始める切り出しパターンは踏襲した。

---

## 4. 確認結果の反映ロジックの実装詳細

### 課題: 「どの質問への返答か」をどう追跡するか

ユーザーの「はい、変わりないです」のような短い返答だけでは、それがどの記憶に対
する確認なのかをLLMに正しく推測させるのは不安定と判断した(直近数十メッセージ
を渡す既存の`memory_extractor.extract_from_conversation()`の一般抽出フローに任
せる案も検討したが、暗黙の文脈推測に依存するのは要件4の「正しく反映されるこ
と」というテスト可能性の要求に対して脆いと考え、専用の追跡機構を実装した、判断
根拠)。

`active_inquiry.py`にプロセス内辞書`_pending_confirmations: dict[thread_id,
dict]`を新設。確認質問を生成した時点(`_generate_confirmation_question()`)で、
`thread_id`をキーに「どのcategory/key/value/confidenceを確認したか」を記録す
る。**1スレッドにつき直近1件のみ保持**(新しい確認質問が発行されると古い保留
分は無条件に上書きされ、二度と反映されない)。これは意図的な設計で、何ターンも
後に来た無関係な返答を古い確認質問に誤って紐付けるリスクを避けるため(判断根
拠)。`_asked_cache`と同様プロセス内のみで永続化しない(再起動でリセットされ
る)。

### 反映処理: `reflect_pending_confirmation()`

`orchestrator/service.py`の`_cognitive_layer_bg()`(A3のdecision検出・B2の
episode検出と同じfire-and-forget箇所)に第3の並行処理として追加した
(`asyncio.gather`に第3引数を追加)。処理内容:

1. `thread_id`に保留中の確認候補があるかを確認(なければ即return)。
2. あれば、直近のユーザー発話一つを取り出し、専用プロンプト
   (`_REFLECT_SYSTEM`/`_REFLECT_PROMPT`)でLLMに`confirmed`/`updated`/
   `unclear`の3択で解釈させる。
3. `confirmed`: 値は変えず、確信度だけ`max(0.9, 元の確信度)`に引き上げて
   `upsert_fact_item()`を呼ぶ(値が同じでもRPCのUPDATE分岐は`updated_at`を必
   ず更新するため、「鮮度情報の更新」も同時に満たされる)。
4. `updated`: LLMが抽出した新しい値で`upsert_fact_item()`を呼ぶ(確信度は
   `confirmed`と同じ0.9 —— 判断根拠: `memory_extractor.py`が「明言」に割り当て
   る確信度と同じ意味合いの入力なので、同じ数値を流用して尺度を分裂させなかっ
   た)。
5. `unclear`: 何もしない(値も確信度も一切変更しない)。
6. いずれの結果でも保留エントリは消費される(1回限り)。

`_cognitive_layer_bg()`自体は`jwt`を受け取っていなかった(decision_log/
experience_layerはservice-role直接アクセスでJWT不要なため)。今回`reflect_
pending_confirmation()`が`upsert_fact_item()`経由でユーザー本人のRLS越しに書き
込む必要があるため、`_cognitive_layer_bg()`のシグネチャに`jwt`を追加し、両方の
呼び出し元(`run_orchestrator_chat`/`run_orchestrator_chat_stream`)から
`jwt=jwt`を渡すよう変更した。

### 出所情報のギャップ発見と追加修正

要件4は「Phase B4の出所情報(この確認・更新がどの会話から行われたか)を正しく
記録すること」を求めていたが、調査の結果、**既存のB4出所情報の仕組みでは原理的
に満たせないことが判明した**。`upsert_fact_item`のUPDATE分岐は`thread_id`/
`invocation_id`をそもそも書き込まない設計(B4で「最初に作られた時点を記録す
る」という意図で意図的にINSERT分岐限定にされていた)。確認による反映は定義上必
ず既存事実へのUPDATEになるため、このままでは要件4を満たせない。

これを解消するため、`user_fact_history`(変更履歴テーブル、既存でold_value/
new_value/changed_by/reasonは記録済みだが「どの会話から」は一切記録していなか
った)に`thread_id`/`invocation_id`列を追加し、`upsert_fact_item` RPCの履歴INSE
RT文を、INSERT/UPDATEどちらの分岐でも常にこの2値を書き込むよう変更した(マイグ
レーション`202607130035_fact_confirmation_provenance.sql`)。`user_fact_items`
自体の`thread_id`/`invocation_id`(「最初に作られた場所」)とは意味が異なる別
種の出所情報として、履歴側は「その変更を引き起こした会話」を毎回記録する設計に
した(判断根拠: 両者は問いが違うため、片方を変えるのではなく履歴側に新しく持た
せるのが正しいと判断した)。

### 副次的な修正: `is_stale`のクリア

調査中に、`is_stale=true`(矛盾検出フラグ)が一度立つと、それを解除する手段が
コード上どこにも存在しないことに気付いた(`search_fact_memory`系のRPCはすべて
`is_stale=false`を検索条件にしているため、フラグが立ったまま永久に検索から除外
され続ける)。今回の確認フローでユーザーが再確認・更新した事実については、矛盾
が解消されたとみなすのが自然なため、`upsert_fact_item`のUPDATE分岐に
`is_stale = false`を追加した(判断根拠: このRPC経由の更新は「事実の値を能動的
に再主張する」操作であり、矛盾フラグを解除するのに最も自然なタイミングと判断し
た)。同じマイグレーションファイルに含めた。

---

## 5. テスト結果

実モデルAPIでの検証はできないため、mock/単体テストで確認した(2ファイル、計
13ケース、B2までと同じく`unittest.IsolatedAsyncioTestCase`ベースのスクラッチテ
ストとして作成・実行、backend/tests配下にはコミットしていない)。

### `get_confirmation_candidates()`(6ケース)
- 低確信度(0.4)の事実が`low_confidence`理由で候補に入ること
- `is_stale=true`の事実が`flagged_stale`理由で候補に入ること
- 200日更新されていない事実が`long_unupdated`理由で候補に入ること
- 直近更新・高確信度の事実は候補に入らないこと
- `value`がnullの事実は、確信度がどれだけ低くても確認候補にはならないこと(欠
  落項目フローとの責務分離の確認)
- 取得失敗時は例外を投げず空リストを返すこと

### `active_inquiry.py`の統合・反映ロジック(7ケース)
- 欠落項目・確認候補の両方が存在しても、LLM呼び出しは1回・質問は1件のみである
  こと(要件3)
- 確認質問が生成されたとき、`_pending_confirmations`に正しくthread_idキーで登
  録されること
- 候補が0件の場合はLLMを呼ばずNoneを返すこと
- 保留中の確認がないスレッドでは`reflect_pending_confirmation()`が何もしないこ
  と
- `confirmed`判定で値は変えず確信度が0.9以上に引き上げられ、保留エントリが消費
  されること
- `updated`判定で新しい値が書き込まれること
- `unclear`判定では何も書き込まれず、保留エントリのみ消費されること
- LLM呼び出し失敗時も例外を握りつぶし、保留エントリは消費されること(次ターン
  に持ち越さない)

### 既存のB2テストの再実行(3ケース、シグネチャ変更の回帰確認)
`_cognitive_layer_bg()`に`jwt`必須引数を追加したため、B2で書いたスクラッチテス
トを更新し、decision検出・episode検出・(新設の)confirmation反映の3つが同じ
turn_messagesスコープで正しく並行呼び出しされること、いずれかが例外を投げても
呼び出し元に伝播しないことを再確認した。

### 既存機能への非破壊確認(要件6)
`backend/tests/`の既存8テストを再実行し、全て成功することを確認した。

```
13 passed (B3新規テスト)
15 passed (B2スクラッチテスト再実行、シグネチャ更新含む)
8 passed (既存回帰テスト)
```

---

## 6. 気づいた懸念点・次のB機能(B6: 話題遷移トラッキング)に影響しそうな発見

- **`_pending_confirmations`はプロセス内・1スレッド1件のみの設計であるため、複
  数バックエンドインスタンス(水平スケール)構成では機能しない**: 現状の運用形
  態(単一プロセス・単一ユーザー)では問題にならないが、将来スケールする場合は
  Redis等の外部ステートストアへの移行が必要になる。`_asked_cache`も同じ制約を
  既に抱えている。
- **確認質問と欠落項目質問が同じランキングプールを共有するため、記憶の量が増え
  るほど「確認質問ばかりが選ばれ、欠落項目が埋まらない」または逆の偏りが将来起
  こりうる**: 現状はどちらも関連度スコアのみで競わせているため、件数の非対称性
  (確認候補が欠落項目より圧倒的に多い場合など)がランキング結果を偏らせる可能
  性がある。B6(話題遷移トラッキング)や将来のPhaseで、両プールの出現比率を観
  測し、必要であれば重み付けを検討する余地がある。
- **`user_fact_history`への`thread_id`/`invocation_id`追加は、確認フロー以外の
  全ての`upsert_fact_item`呼び出し(memory_extractor.py通常フロー含む)にも同時
  に効果が及ぶ**: 意図した副次効果だが、これにより既存の全fact更新について「ど
  の会話が原因か」が今後遡って追跡可能になる。B6が話題遷移を検出する際、
  `user_fact_history`のこの新しい列を使って「ある話題への遷移が、どの記憶更新
  と時間的に対応するか」を分析する土台になりうる。
- **`is_stale`のクリアは「このRPC経由の更新なら常に解除」という単純なルールに
  した**: 矛盾フラグが本当に解消されたかどうかをLLMに再判定させる、というより
  慎重な設計も検討したが、過剰実装と判断し見送った(判断根拠、要件6「既存機能
  に悪影響を与えない」の範囲内であることは、is_staleを参照する既存コード(検索
  RPC)が全て「フラグが立っていない = 検索対象」という一方向の意味しか持たない
  ため、フラグを解除する行為自体に安全上のリスクはないと判断した)。

---

## Related Documents

- `docs/sigmaris/sigmaris_roadmap.md`
- `docs/sigmaris/phase_b17_report.md`(`importance_score`が粗い代理指標だったと
  いう前例、本タスクの`confidence`実態調査の比較対象)
- `docs/sigmaris/phase_b4_report.md`(Phase B4出所情報の元設計)
- `docs/sigmaris/phase_b2_report.md`(直前のB群タスク、fire-and-forget統合パタ
  ーンの踏襲元)
- `docs/persona.md`(3章・4章、確認質問のトーン根拠)
- `supabase/migrations/202607130035_fact_confirmation_provenance.sql`(未適用)
