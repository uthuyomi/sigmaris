# Phase B2 実施報告: エピソード記憶/意味記憶の分離

対象ブランチ: `phase-b2-episode-semantic-split`(mainからfork)

---

## 0. baseline値の性質について(先行B群タスクと同様)

`docs/sigmaris/phase_c_mini_report.md`のbaselineおよび先行B群タスクの参考値は、
`sigmaris_decision_log`のデータ蓄積状況に依存する不確実性を含む。本タスク完了後
の`run_eval.py`の数値も引き続き参考値として扱うこと。本タスクの効果確認は、指示
書通り「実際にエピソード記憶が記録され、意味記憶への統合が正しく行われるか」と
いう機能テストで行った(下記4章)。実モデルAPIでの検証はできないため、mock/単体
テストのみでの確認とした。

---

## 1. エピソード記録経路の追加箇所と実装詳細

### 前提: 呼び出し元の不在の解消

`backend/app/services/experience_layer.py`の`record_experience()`は、Phase B4時
点では`POST /agent/experience/record`(外部エージェント向けルート、
`backend/app/routes/agent.py`)からしか到達できず、通常の会話フロー
(`orchestrator/service.py`)には呼び出し元が存在しなかった
(`docs/sigmaris/phase_b4_report.md`§1で確認済み)。本タスクではこれを解消する
ため、`record_experience()`を直接使うのではなく、A3のdecision_log検出と対になる
新しい判定+記録関数`experience_layer.detect_and_record_episode()`を追加し、
`orchestrator/service.py`の`_cognitive_layer_bg()`(fire-and-forgetの認知レイヤー
処理、A3のdecision_log検出が既に走っている場所)に組み込んだ。

### 判定ロジック: `detect_and_record_episode()`

`decision_log.detect_and_record_decision()`と全く同じ形にした:

- 対象は「今回のターンのみ」(`turn_messages` = 直近のユーザー発話1件 + アシスタ
  ント応答1件)。`_prepare_session_messages()`が組み立てるクロススレッド窓全体
  ではなく、A3のdecision_log検出と同じスコープに絞った。理由も同じ: 過去の古い
  やり取りがまだコンテキストに残っている場合に、ターンごとに再度「新しいエピソ
  ード」として検出されてしまうのを防ぐため。
- LLMに`has_episode: true/false`を判定させ、`true`の場合のみ
  `experience_type`(success/failure/unresolved)・`category`(proposal/
  reflection/research/interaction/prediction)・title・description・outcome・
  lessonを抽出する。無効な値が返った場合は`unresolved`/`interaction`にフォール
  バックする(decision_logの`decision_type`が無効なら`policy_change`にフォール
  バックするのと同じ防御パターン)。
- 「後から参照する価値のある出来事」の粒度基準はプロンプト(`_DETECT_EPISODE_
  PROMPT`)にのみ実装し、コード側の閾値は設けていない — 雑談・単純な質問応答・
  確認のみのやり取りには反応しないことをsystemプロンプトとuserプロンプト両方で
  明示している。

### タスクタイプ: `TaskType.EPISODE_DETECTION`(新規)

`decision_detection`と構造が同一(1ターンごとの安価な分類+抽出タスク)のため、
専用のタスクタイプを新設し、ローカルLLM対象集合(`_LOCAL_TASK_TYPES`)とOpenAI
nanoモデル振り分け先(`_openai_model_for_task()`)の両方に`decision_detection`と
並べて追加した。既存の`decision_detection`のタスクタイプを流用する選択肢もあっ
たが、コスト計測・ログ上での可観測性を分けたかったため専用タイプとした
(判断根拠)。

### fire-and-forgetパターンの踏襲方法

`_cognitive_layer_bg()`は元々`await detect_and_record_decision(...)`を単独で呼
んでいたが、今回`detect_and_record_episode(...)`も同じturn_messagesを読むだけの
独立した処理なので、`asyncio.gather()`で並行実行するよう変更した(判断根拠: 逐
次awaitでも機能的には問題ないが、どちらもLLM呼び出しを含むため、並行化した方が
このバックグラウンドタスク全体の完了が早まり、次のインターナルステート更新まで
の待ち時間も縮む)。`_cognitive_layer_bg()`自体は変わらず
`asyncio.create_task(...)`で起動されるため、応答速度への影響はない(4章のテスト
で確認)。

`detect_and_record_episode()`内部にも独自のtry/exceptがあり(decision_log側と同
じ二重防御)、失敗時は例外を投げずNoneを返す。

---

## 2. エピソード記憶/意味記憶の役割分担の最終定義

`experience_layer.py`冒頭にコードコメントとして明記した:

- **`sigmaris_experience`(エピソード記憶)**: 「その時々に起きた出来事」。本質
  的に時点依存・状況依存。同じ話題が状況の推移とともに複数行にまたがって記録さ
  れうる(例:「Xで詰まっている」→ 後で「Xを解決した」)。古い行は後から書き換
  えない。
- **`user_fact_items`(意味記憶)**: 「恒久的に成り立つ事実」。一度記録されたら
  何かに矛盾・置き換えられるまで成り立ち続けることが期待される
  (`memory_validator.py`の減衰・矛盾検出ロジックの対象)。エピソードのように
  自然な終了時点を持たない。
- 重複防止: エピソード(「海星さんがX機能の実装で詰まり、Yという方法で解決し
  た」)はそのままではエピソード記憶に留まり、`consolidate_episodic_memory()`が
  「恒久的な事実が導けるか」を判定した場合のみ意味記憶に昇格する(「海星さんは
  Xという技術に慣れていない」)。昇格してもエピソード行は削除・上書きされず、
  昇格した事実行は`source_experience_ids`で元のエピソードを参照する別レコード
  として作られる。

---

## 3. 統合(consolidation)ジョブの実装詳細

### スケジュール

`proactive/scheduler.py`に日曜4:55(`adoption_count_recompute`の4:50の5分後、
`narrative_generate`の5:00の5分前)で追加。既存ジョブ間の空き枠に収めた。

```python
_scheduler.add_job(_episode_consolidate, CronTrigger(day_of_week="sun", hour=4, minute=55, ...), id="episode_consolidate", ...)
```

`_episode_consolidate()`は`_memory_embed`/`_memory_validate`と同じパターンで
`get_sigmaris_jwt()`を先に解決してから本体`consolidate_episodic_memory(jwt)`を呼
ぶ。他のB13/B14の週次ジョブ(decision_log.py側)がすべてservice-role・JWT不要な
のに対し、本ジョブだけJWTが必要な点が異なる(判断根拠は次項)。

### なぜJWTが必要か(判断根拠)

`sigmaris_experience`・`sigmaris_decision_log`・`sigmaris_user_preference_
patterns`はいずれもservice-role専用のグローバル(単一ユーザー前提)テーブルで、
B13/B14の週次ジョブはservice-roleヘッダーで直接読み書きしている。一方
`user_fact_items`は`user_id`ごとのRLSが敷かれた通常のユーザーテーブルであり、新
規factを1件作る処理は既存の`upsert_fact_item()` RPC
(`SECURITY INVOKER` + `auth.uid()`)を再利用するのが最も安全で実装コストも低い
と判断した。B13の`recompute_adoption_counts()`のようにservice-roleで直接
`user_fact_items`をPATCHする方式も検討したが、あちらは「既存行のadoption_count
を更新するだけ」なのに対し、本ジョブは「新しい意味記憶を作成する」処理であり、
既存のupsert経路(履歴記録・(category,key)一意制約によるdedup込み)をそのまま
使う方が、直接書き込みを再実装するより堅牢と考えた。

### 採用基準・判定ロジック

`_CONSOLIDATE_PROMPT`にLLMへの指示として組み込んだ:

1. 複数エピソードに共通するパターン(推奨): 裏付けとなるエピソードが最低2件
   (`_MIN_SUPPORTING_EXPERIENCES=2`、B14の`_MIN_SUPPORTING_DECISIONS`と同じ値
   で揃えた)。
2. 単発だが明らかに恒久的な事実(例:「札幌に引っ越した」)は、LLMが
   `single_episode_exception: true`を明示し、`reason`になぜ恒久的と判断したか
   を書いた場合のみ1件で採用可。
3. 「その場限りの状態」(例:「今疲れている」)は絶対に抽出しないよう明示。

コード側の防御:
- LLMが返した`supporting_experience_ids`は、実際に送った直近100件のエピソード
  IDに含まれるものだけを信用する(decision_log.pyの`extract_preference_
  patterns()`と同じ、LLM生成IDを鵜呑みにしない防御)。フィルタ後に件数が閾値を
  下回れば`single_episode_exception`の有無に関わらず棄却する。
- `category`は`user_fact_items`のCHECK制約
  (`profile/health/lifestyle/environment/devices/preferences/preference/
  relationships/finance/goals/work/personality/timeline`)に含まれないものは棄
  却する。
- `key`・`value`が空の候補も棄却する。

### 再スキャン方式(cursorを持たない設計、判断根拠)

「既に統合済みのエピソード」を追跡するカーソル列は追加しなかった。毎回直近100
件を再スキャンする方式にした理由: `upsert_fact_item`は(user_id, category, key)
単位で冪等なので、同じエピソードから同じ事実を再導出しても単に同じ行が更新され
るだけで重複は発生しない。これはB14の`extract_preference_patterns()`が毎回同じ
100件の決定を再分析する設計と同じ考え方であり、実装をシンプルに保てる
(判断根拠)。

### 出所情報: `source_experience_ids`(新規、Phase B4の出所情報とは別種)

`user_fact_items`に新規列`source_experience_ids uuid[]`を追加した。Phase B4の
`thread_id`/`invocation_id`が「会話のどのターンで最初に作られたか」を記録するの
に対し、これは「どのエピソード記憶群から統合されたか」という別種の出所情報であ
り、`consolidate_episodic_memory()`が作る行にのみ設定される(通常の
memory_extractorが作る行や手動作成の行はNULLのまま)。`upsert_fact_item()` RPC
に`p_source_experience_ids uuid[] default null`を追加し、Phase B4の
`thread_id`/`invocation_id`と同じ「INSERT時のみ設定、UPDATE時は無視」というパタ
ーンを踏襲した。

`source`のCHECK制約に`'episode_consolidation'`を追加し、統合由来のfactを既存の
`manual`/`chat`/`sensor`/`import`/`chatgpt_import`と区別できるようにした。

マイグレーション: `supabase/migrations/202607120034_episode_consolidation.sql`
(未適用、運用者側での適用が必要)。`upsert_fact_item`は戻り値が`jsonb`(固定列
の`RETURNS TABLE`ではない)ため、B1/B17/B13で3回必要だった`DROP FUNCTION`は不要
で、`CREATE OR REPLACE`のみで対応できた。

---

## 4. テスト結果

実モデルAPIでの検証はできないため、mock/単体テストで確認した(3ファイル、計14
ケース、`unittest.IsolatedAsyncioTestCase` + `unittest.mock`、backend/tests配下
にコミットはせず、既存のB1/B4/B13/B14と同様にセッション内のスクラッチテストと
して作成・実行・確認)。

### `detect_and_record_episode()`(5ケース)
- `has_episode: false`のとき`record_experience`が呼ばれないこと
- `has_episode: true`のとき、フィールドが正しくマッピングされ、thread_id/
  invocation_idが伝播すること
- 無効な`experience_type`/`category`が`unresolved`/`interaction`にフォールバッ
  クすること
- 空のtranscript(発話なし)ではLLM呼び出し自体が行われないこと
- LLM呼び出し失敗時に例外を握りつぶしNoneを返すこと

### `consolidate_episodic_memory()`(6ケース)
- エピソード件数が閾値未満(`_MIN_EXPERIENCES_FOR_CONSOLIDATION=3`)のときLLM
  を呼ばずinsufficient_dataを返すこと
- 2件の裏付けがある候補が正しく`upsert_fact_item`に`source="episode_
  consolidation"`・`source_experience_ids`付きで昇格されること
- 単発かつ`single_episode_exception=false`の候補は棄却されること
- 単発かつ`single_episode_exception=true`の候補は1件でも昇格されること
- LLMが送っていないID(架空ID)を含む候補は、フィルタ後に件数が閾値未満になれ
  ば棄却されること
- CHECK制約外の`category`を返した候補は棄却されること

### `_cognitive_layer_bg()`の配線・fire-and-forget(3ケース)
- decision検出とepisode検出の両方が、同じ`turn_messages`/`thread_id`/
  `invocation_id`で呼ばれること
- episode検出側が例外を投げても(通常は内部で握りつぶされるが、二重防御として)
  `_cognitive_layer_bg`自体は呼び出し元に例外を伝播しないこと
- `run_orchestrator_chat()`全体の fire-and-forget 検証:
  `_cognitive_layer_bg`をモックで意図的に遅延させ、`asyncio.Event`を使って「応
  答が返った時点でバックグラウンド処理がまだ完了していない」ことを直接確認し
  た。当初は経過時間の閾値(< 1秒)でテストしたが、テスト環境自体に本変更と無
  関係な遅延(Supabase未設定によるエラーパス処理などが累積して約2.5秒)がある
  ことが判明したため、絶対時間ではなく「応答完了時点でバックグラウンドタスクが
  未完了」というイベント順序に基づく検証に切り替えた(気づいた点、下記5章にも
  記載)。

### 既存機能への非破壊確認(要件5)
`backend/tests/`の既存8テストを再実行し、全て成功することを確認した。

```
14 passed (B2新規テスト)
8 passed (既存回帰テスト)
```

---

## 5. 気づいた懸念点・次のB機能(B3: 記憶の自己検証ループ)に影響しそうな発見

- **経過時間ベースのfire-and-forget検証は、この環境では信頼できない**: バック
  エンドの単体テスト環境にはSupabase接続情報が設定されておらず、多くの内部呼び
  出しが「即座に失敗する」のではなく数百ms〜数秒単位の実httpxリクエスト試行・失
  敗を伴う(実測で約2.5秒)。今後、応答速度やレイテンシに関するテストを書く際
  は、絶対時間の閾値ではなく`asyncio.Event`等によるイベント順序の検証を使うこ
  と。この問題はB2固有ではなく既存のテスト全般に当てはまりうる潜在的な懸念点で
  あり、次にレイテンシ関連のテストを書く機会があれば留意されたい。
- **`consolidate_episodic_memory()`の再スキャン方式は、エピソードが将来大量に
  蓄積した場合にコストが線形に増える**: 現状は直近100件固定のため実害はない
  が、B3(記憶の自己検証ループ)が仮に既存のuser_fact_itemsを大量に走査する設
  計になる場合、同様の「毎回全件再走査」ではなく差分検出の仕組みが必要になるか
  もしれない。
- **`user_fact_items.source_experience_ids`は現状、検索・ランキング(B1/B17/
  B13)には一切影響しない、純粋な出所情報としてのみ実装した**: B3が「意味記憶
  の自己検証」を行う際、ある事実がどのエピソードから来たか(`source_experience_
  ids`)を遡って再検証する、という設計は自然に繋がる可能性がある。
- **`experience_type`/`category`の粒度は現状LLM任せで、コード側の閾値は一切な
  い**: 実運用でどの程度の頻度でエピソードが記録されるか(過剰記録によるテーブ
  ル肥大 or 過小記録で統合ジョブがinsufficient_dataのまま停滞するか)は、実際の
  会話ログでの観測が必要。運用者側での`sigmaris_experience`行数の定期確認を推奨
  する。

---

## Related Documents

- `docs/sigmaris/sigmaris_roadmap.md`
- `docs/sigmaris/phase_b4_report.md`(呼び出し元不在の発見元)
- `docs/sigmaris/phase_b14_report.md`(preference patternsの検証済みID防御パター
  ンの踏襲元)
- `docs/sigmaris/phase_b13_report.md`(直前のB群タスク、実装パターンの多くを踏
  襲)
- `supabase/migrations/202607120034_episode_consolidation.sql`(未適用)
