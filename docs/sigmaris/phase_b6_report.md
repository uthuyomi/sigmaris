# Phase B6 実施報告: 話題遷移トラッキング

対象ブランチ: `phase-b6-topic-transition-tracking`(mainからfork)

---

## 0. baseline値の性質・過剰実装への警戒について

`docs/sigmaris/phase_c_mini_report.md`のbaselineおよび先行B群タスクの参考値は、
`sigmaris_decision_log`のデータ蓄積状況に依存する不確実性を含む。本タスク完了後
の`run_eval.py`の数値も引き続き参考値として扱う。効果確認は指示書通り「話題の推
移が正しく検出・記録され、会話に自然に反映されるか」という機能テストで行った
(下記4章)。

指示書で明示的に警告されている過剰設計を避けるため、話題分類体系・グラフ構造は
一切導入せず、**LLMが生成する数語程度のラベル文字列を時系列で並べるだけの、単
一のフラットテーブル**に実装を留めた。「現在の話題」「直前の話題」以外の概念
(話題の階層、関連話題、話題の再出現検出等)は今回のスコープに含めていない。

---

## 1. 話題遷移の記録方式の実装詳細

### テーブル設計: `sigmaris_topic_log`

```sql
create table public.sigmaris_topic_log (
  id            uuid primary key default gen_random_uuid(),
  topic_label   text not null,
  thread_id     uuid,
  invocation_id uuid,
  created_at    timestamptz not null default timezone('utc', now())
);
```

**開始・終了範囲を表す列を持たない**(判断根拠): 「ある話題がいつまで続いたか」
は「次の行が現れるまで」という暗黙の情報で十分表現できるため、`ended_at`のよう
な列を追加する必要はないと判断した。「現在の話題」=最新1行、「直前の話題」=そ
の1つ前の行、という単純な取得ロジックのみで要件を満たせる。

**`sigmaris_decision_log`/`sigmaris_experience`/`sigmaris_user_preference_
patterns`と同じservice-role専用のグローバル単一テナントテーブル**にした(判断
根拠): 本システムはユーザーが海星さん一人の単一テナント運用であり、これら既存
のB群テーブルは全て`user_id`列を持たずRLSも`service_role_only`ポリシーのみで統
一されている。`thread_id`/`invocation_id`はB4の出所情報パターンを踏襲した参照
用の列であり、パーティションキーではない(Phase A1がスレッドを跨いだ会話継続性
を前提に設計されているため、話題の継続性もスレッドを跨いで良いという判断)。

### 判定ロジック: `detect_and_record_topic_transition()`

`decision_log.detect_and_record_decision()`/`experience_layer.detect_and_
record_episode()`と全く同じ形にした:

- 対象は「今回のターンのみ」(`turn_messages`)。理由も同じ: 古いやり取りが再度
  「話題変化」として誤検出されるのを防ぐため。
- 現在の話題ラベル(なければ「(なし)」)をプロンプトに含め、LLMに「明確に変わ
  った場合のみ`changed: true`と新ラベルを返す」よう指示する。雑談の範囲内の些細
  な変化では変わったと判定しないよう明示した。
- **防御的な重複排除**: LLMが`changed: true`を返しても、新ラベルが現在のラベル
  と(前後空白・大小文字を無視して)同一内容であれば記録をスキップする。LLMの
  判定揺れによる無意味な重複行を防ぐための追加ガード。
- 話題がまだ1件も記録されていない状態(`current_topic`が`None`)でも、同じプロ
  ンプトフローで最初の話題を記録できるようにした(特別分岐を作らず、「(なし)」
  という現在ラベル表現をLLMへの入力にそのまま使う設計)。

### 記録なし(要件2)の担保

LLMが`changed: false`を返した場合、`_record_topic()`(DB書き込み)自体が一切呼
ばれない(早期return)。これはdecision_log/experience_layerの「該当しなければ
None」という契約と同一で、テストで明示的に検証した(4章)。

### TaskType: `TOPIC_DETECTION`(新規)

`DECISION_DETECTION`/`EPISODE_DETECTION`と同じ構造(1ターンごとの安価な分類+
抽出タスク)のため、専用のタスクタイプを新設し、ローカルLLM対象集合・OpenAI
nanoモデル振り分け先の両方に追加した(B2で確立した「観測性のため専用タイプを作
る」という前例を踏襲)。

---

## 2. Phase A1・B2との役割分担の最終的な整理

`topic_tracker.py`の冒頭コメントに明記した:

- **Phase A1(直近ログウィンドウ、`_prepare_session_messages`)**: 生の会話その
  もの — 実際に何と発言されたか、逐語的な記録。
- **Phase B2(`sigmaris_experience`、エピソード記憶)**: 「何が起きたか」という
  出来事の記録。特定の会話に依存せず、それ単体で恒久的な価値を持つ記録単位(例:
  「海星さんがX機能の実装で詰まり、Yという方法で解決した」)。
- **本タスク(`sigmaris_topic_log`)**: どちらでもない。「今何の話をしている
  か」を表す、数語だけの軽量な見出し情報。発言内容も出来事の詳細も一切保持しな
  い。話題分類体系やグラフ構造も持たない、単なる時系列の短い文字列の並び。

3者が重複して同じ情報を保持することはない: 話題ログには「何を話したか」の詳細
は一切書き込まれず(ラベル文字列のみ)、エピソード記憶には「今何の話をしている
か」という進行中のメタ情報は書き込まれない(エピソードは「起きた出来事」の確定
記録であり、話題の遷移そのものではない)。

---

## 3. プロンプトへの反映方法

### コンテキスト構築: `_build_topic_context()`

`orchestrator/service.py`に、既存の`_build_self_model_context()`/`_build_
preference_patterns_context()`と同じ形の`_build_topic_context(current_topic,
previous_topic)`を追加した。現在の話題ラベル・(あれば)直前の話題ラベルに加
え、「必要だと感じた場合のみ話題の切り替わりに自然に触れてよい。毎回言及する必
要はない」という指示行を含める(要件3の「強制的に毎回言及させる必要はない」を
プロンプト側で明示)。

**既存の`_build_trends_context()`(trend_analyzer.py由来、`[傾向トピック]`)と
の名前衝突に注意**: `user_trend_items`テーブルも偶然`topic_label`という列名を
使っているが、全く別機能(数週間単位の生活・行動傾向)であり、本タスクの
`sigmaris_topic_log`とは無関係。コード上のコメントで明示的に区別した。

### キャッシュ: 既存のTTLキャッシュ機構を再利用

`_cached_current_and_previous_topic()`を、`_cached_self_model()`/`_cached_
preference_patterns()`と同じ`_cache`(TTL 300秒)を使う形で実装した。両方の
`run_orchestrator_chat`/`run_orchestrator_chat_stream`の初期`asyncio.gather`に
追加し、`topic_context`を`call_schedule_agent`/`call_schedule_agent_stream`に渡
すよう`schedule_agent_client.py`の`_build_system_override`/`_build_payload`/両
呼び出し関数に`topic_context`引数を追加した。

**キャッシュ無効化のタイミング(判断根拠)**: 既存の`facts`キャッシュ無効化は
`run_orchestrator_chat`のメインフロー内で、fire-and-forgetタスク(`extract_from_
conversation`)の完了を待たずに即座に行われる(やや早すぎるが許容されている既
存パターン)。本タスクでは、話題の書き込み自体が`_cognitive_layer_bg`という
fire-and-forgetタスクの中で起きるため、そのタスク自身の`finally`節で`_cache.
pop("topic", None)`を行うようにした。これは既存のfactsパターンより実際には正確
(書き込みが実際に完了した後にキャッシュを無効化する)。`asyncio.gather`内の他
の呼び出し(decision/episode/confirmation)が例外を投げても`finally`により必ず
無効化されることをテストで確認した。

### Phase A2プロンプトキャッシュへの配慮(要件5)

`self_model_context`/`preference_patterns_context`と全く同じ扱いで、
`chat_prompts.py`の`rules`(ターン間で不変であるべき部分)には一切触れず、
`_build_system_override`の末尾側に追加する形にした。既存の可変コンテキストパイ
プをそのまま延長しただけであり、キャッシュ構造への新たな悪影響はない。

---

## 4. テスト結果

実モデルAPIでの検証はできないため、mock/単体テストで確認した(2ファイル、計19
ケース、B2/B3までと同じくスクラッチテストとして作成・実行、backend/tests配下に
はコミットしていない)。

### `get_current_and_previous_topic()`(4ケース)
- 行が0件のとき`(None, None)`を返すこと
- 行が1件のとき現在のみ・直前は`None`
- 行が2件のとき現在・直前がそれぞれ正しく対応すること
- 取得失敗時は例外を投げず`(None, None)`を返すこと

### `detect_and_record_topic_transition()`(6ケース)
- 話題が明確に変わった場合に正しく新しいラベルで記録され、`thread_id`/
  `invocation_id`が伝播すること
- 話題が変わっていない場合、DB書き込み自体が一切呼ばれないこと(要件2)
- LLMが`changed: true`でも新ラベルが現在のラベルと実質同一(空白差のみ)の場合
  は記録がスキップされること(防御的重複排除の確認)
- 空のtranscriptではLLM・DB双方が一切呼ばれないこと
- LLM呼び出し失敗時に例外を握りつぶしNoneを返すこと
- 話題がまだ1件もない状態から最初の話題が正しく記録されること

### `_build_topic_context()`(4ケース)
- 現在の話題がない場合`None`を返すこと
- 現在の話題のみの場合、直前の話題行が含まれないこと
- 現在・直前両方がある場合、両方が正しく含まれること
- ラベルが空白のみの場合`None`を返すこと(トリム後の空文字ガード)

### `_cognitive_layer_bg()`の配線(2ケース、B2/B3で確立したfire-and-forget検証
手法を踏襲)
- decision/episode/confirmation/topicの4つの検出・反映処理が同じ`turn_
  messages`スコープで並行呼び出しされること
- いずれかが例外を投げても、`finally`節により`topic`キャッシュが必ず無効化され
  ること

### 既存のB2/B3スクラッチテストの再実行(回帰確認)
`_cognitive_layer_bg()`の`asyncio.gather`に4番目の呼び出しが増えたため、B2の
`test_b2_orchestrator_wiring.py`を更新し、4つの呼び出し全てが同じスコープで正し
く呼ばれることを再確認した。

### 既存機能への非破壊確認(要件6)
`backend/tests/`の既存8テストを再実行し、全て成功することを確認した。

```
19 passed (B6新規テスト)
33 passed (B2/B3スクラッチテスト再実行、シグネチャ更新含む)
8 passed (既存回帰テスト)
```

---

## 5. 気づいた懸念点・次のB機能(B7: マルチホップ質問の分解検索)に影響しそうな発見

- **話題ラベルの粒度はLLM任せであり、揺れが生じうる**: 「AdFlow AIの収益化」と
  「AdFlow AIの値付け」のように、意味的にはほぼ同じ話題でも表現が微妙に異なる
  と、防御的重複排除(文字列完全一致のみ)をすり抜けて別行として記録される可能
  性がある。現状は指示書の「シンプルな実装に留める」という制約に従い、意味的類
  似度判定などは実装していない。実運用でノイズが多い場合は、将来的に軽量な類似
  度チェックの追加を検討する余地がある。
- **`sigmaris_topic_log`はグローバル単一テーブルのため、将来的にマルチユーザー
  化する場合は他のB群グローバルテーブル同様`user_id`列の追加が必要になる**: 現
  時点では単一テナント運用のため実害はない。
- **B7(マルチホップ質問の分解検索)との接点**: 「さっきまで◯◯の話をしてたけ
  ど」のような話題遷移情報は、マルチホップ質問(例:「さっきの話とさっき言って
  た件、両方に関係するんだけど」)の分解時に、どの話題を指しているかの手がかり
  として使える可能性がある。ただし今回の実装は「直前1件」の話題しか保持しない
  ため、2ターン以上前の話題への言及を解決する用途には使えない — B7で過去の話題
  参照が必要になった場合は、`sigmaris_topic_log`をより深く遡って取得するAPI
  (現状の`get_recent_topics(limit=2)`をより大きなlimitで呼ぶだけで対応可能)を
  拡張することを検討されたい。

---

## 追記: 既存`facts`キャッシュ無効化タイミングの是正(フォローアップ)

本報告§3で「既存の`facts`キャッシュ無効化は、fire-and-forgetタスクの完了を待た
ずに即座に行われる(やや早すぎるが許容されている既存パターン)」と指摘した箇所
について、ユーザーからの指示を受け、`topic`キャッシュと同じ「書き込みタスク自
身の`finally`節で無効化する」パターンに揃える修正を行った。

`orchestrator/service.py`に新設した`_extract_facts_bg()`が
`extract_from_conversation()`の呼び出しをラップし、その`finally`節で
`_cache.pop(f"facts:{user_id}", None)`を行う。`run_orchestrator_chat`/`run_
orchestrator_chat_stream`双方のメインフロー側にあった、タスク発火直後の即時
`_cache.pop(...)`呼び出しは削除した。

テストで「抽出処理が完了するまではキャッシュが残っていること」「例外発生時でも
必ず無効化されること」の両方を確認し(`asyncio.Event`でタスクの進行を制御する
手法、既存のfire-and-forget検証と同じ手法)、既存の全回帰テスト(54件)が引き
続き成功することを確認した。

---

## Related Documents

- `docs/sigmaris/sigmaris_roadmap.md`
- `docs/sigmaris/phase_b2_report.md`(エピソード記憶との役割分担の比較対象、
  fire-and-forget統合パターンの踏襲元)
- `docs/sigmaris/phase_a1_report.md`(直近ログウィンドウ、話題継続性がスレッド
  を跨ぐ設計根拠)
- `docs/sigmaris/phase_b14_report.md`(preference_patterns_contextのプロンプト
  注入パターンの踏襲元)
- `supabase/migrations/202607140036_topic_transition_tracking.sql`(未適用)
