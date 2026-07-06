# Phase BA1 実施報告: B3(記憶自己検証)のバックグラウンド化

対象ブランチ: `phase-ba1-inquiry-fire-and-forget`(mainからfork)

---

## 0. 前提ドキュメントについて

指示書が参照する`docs/sigmaris/phase_b_arch_roadmap.md`は本タスク開始時点で
リポジトリ上に存在しなかった(`docs/sigmaris/`配下を検索したが該当ファイルなし)。
本タスクは代わりに`docs/sigmaris/incident_response_latency_investigation.md`
(6.5節)と`docs/sigmaris/phase_b3_report.md`を一次情報として進めた。ロードマップ
ファイル自体の作成・復元は本タスクの範囲外と判断し、実施していない。

---

## 1. サイレント失敗の実態調査結果

### 結論: 実際にほぼ毎回タイムアウトしていた可能性が高い

`orchestrator/service.py`の変更前コード(`run_orchestrator_chat`・
`run_orchestrator_chat_stream`の両方に同一パターンが重複していた)は次の形だった:

```python
try:
    from app.services.active_inquiry import get_inquiry_question
    full_messages_so_far = list(messages) + [{"role": "assistant", "content": response_text}]
    inquiry = await asyncio.wait_for(
        get_inquiry_question(jwt, full_messages_so_far, thread_id=effective_thread_id), timeout=2.0
    )
    if inquiry:
        response_text = response_text + "\n\n" + inquiry
except (asyncio.TimeoutError, Exception):
    pass  # Never block the response for inquiry failures
```

`except (asyncio.TimeoutError, Exception): pass`は、`asyncio.TimeoutError`は
`Exception`のサブクラスなので実質的に`except Exception: pass`と同義であり、
**タイムアウトを含むあらゆる失敗を一切ログに残さず握りつぶす**コードだった。

`docs/sigmaris/incident_response_latency_investigation.md`6.5節の実測ログでは、
`get_inquiry_question`区間(`48.349`〜`50.352`)がちょうど**約2.003秒**で完了し
ている。これは実装上のタイムアウト値(2.0秒)にほぼ完全に一致しており、単発の
偶然というよりは、**この呼び出しが構造的に2秒近辺(またはそれ以上)かかること
が常態化しており、タイムアウトによって機能がほぼ毎回打ち切られていた**ことを
強く示唆する。

### 原因の特定: `TaskType.COMPLEX_REASONING`が重量級モデルにルーティングされていた

`active_inquiry.py`の質問生成(`_generate_missing_field_question`・
`_generate_confirmation_question`)は`TaskType.COMPLEX_REASONING`を使用してい
る。`local_llm.py`を確認したところ:

- `COMPLEX_REASONING`は`_LOCAL_TASK_TYPES`に含まれておらず、常にOpenAI(ローカ
  ルOllamaへは絶対にルーティングされない)。
- `_openai_model_for_task()`は`COMPLEX_REASONING`を`SELF_REFLECT`と同じ扱いに
  し、`settings.sigmaris_reflect_model or settings.openai_advanced_model`(「上
  位」モデル階層)を返す。これは、他の大半のバックグラウンド分類呼び出し
  (`ROUTING`・`MEMORY_EXTRACTION`・`DECISION_DETECTION`・
  `EPISODE_DETECTION`・`TOPIC_DETECTION`等)が使う`openai_nano_model`(高速・
  軽量モデル階層)とは異なる。

つまりB3の質問生成は、他のB群バックグラウンド処理より重いモデル階層を使ってお
り、それが応答経路上の2秒タイムアウトと組み合わさることで、**機能が事実上ほと
んど動作していなかった**可能性が高い(質問が生成されても2秒以内に間に合わなけ
れば、ユーザーには何も届かず、ログにも何も残らない)。

`get_null_fields(jwt)`・`get_confirmation_candidates(jwt)`(いずれも単純な
Supabase REST読み取り)自体は軽量なはずで、律速要因はLLM呼び出し1回(質問文生
成)であると判断した。なお、この2つの候補取得呼び出しは`active_inquiry.py`内で
逐次(sequential)に`await`されており並列化されていない点にも気づいたが、支配
的な要因ではないと判断し、今回は変更していない(5章で後述)。

### 対応方針

タイムアウト値の調整やモデル階層の変更ではなく、指示書の要求通り**応答経路か
ら完全に排除する**(fire-and-forget化)ことで、この問題自体を構造的に解消し
た。あわせて、握りつぶされていた例外はすべて`logger.exception`/`logger.info`
で記録するようにした(3章)。

---

## 2. fire-and-forget化の実装詳細

### 変更ファイル
- `backend/app/services/active_inquiry.py`
- `backend/app/services/orchestrator/service.py`(`run_orchestrator_chat`・
  `run_orchestrator_chat_stream`の両方)

### `active_inquiry.py`: 新設した2関数

既存の`get_inquiry_question()`(候補選定・ランキング・LLM生成のロジック本体)
は一切変更していない。その代わりに、呼び出し方を差し替える薄いラッパーを2つ追
加した:

1. **`generate_and_stash_inquiry_question(*, jwt, recent_messages, thread_id)`**
   (fire-and-forgetのエントリポイント): `get_inquiry_question()`をそのまま呼
   び出し、結果を`_pending_inquiry_text[thread_id]`に
   `{"question": ..., "generated_at": time.time()}`として保存するだけ。
   `thread_id`が`None`の場合は、届け先がないため生成自体を行わずスキップする
   (判断根拠: 二度と使われることのないLLM呼び出しを課金・実行するだけ無駄なた
   め)。例外は`try/except`で捕捉し`logger.exception`で必ず記録する(要件2)。
2. **`take_pending_inquiry_question(thread_id) -> str | None`**: 該当
   `thread_id`の保留質問を辞書から**pop**して返す。I/Oを一切行わない純粋な辞書
   操作なので、応答経路に組み込んでも実行時間への影響は事実上ゼロ。

どちらの関数も`_pending_confirmations`(既存のB3実装)や`_pending_hedges`
(B15)と同じく、プロセス内・スレッドID単位・one-shot(消費後は残らない)の設
計にした。

### `orchestrator/service.py`: 呼び出し側の変更

`run_orchestrator_chat`・`run_orchestrator_chat_stream`の双方で、以前は同じ場
所(persona rewrite・`finish_invocation`の直後)にあった
「`asyncio.wait_for(get_inquiry_question(...), timeout=2.0)`を直列await」ブ
ロックを、次の2箇所に分離した:

1. **同じ場所**(finish_invocationの直後): 前ターンの保留質問があれば
   `take_pending_inquiry_question(effective_thread_id)`で取り出し、既存の追記
   方式(`response_text + "\n\n" + inquiry`。ストリーミング版は
   `OrchestratorStreamEvent(delta=...)`として追加でyield)にそのまま合流させ
   た。**LLM呼び出しも待機も発生しない**ため、応答経路のレイテンシへの影響は
   ゼロ(要件1)。
2. **既存のfire-and-forget群と同じ位置**(`_extract_facts_bg`の
   `asyncio.create_task`の直後): 今回のターンの`full_messages`(ユーザー発話
   +このターンの応答テキスト。以前`get_inquiry_question`に渡していた
   `full_messages_so_far`と同一の組み立て方)を渡して
   `generate_and_stash_inquiry_question`を`asyncio.create_task`で起動する。応
   答はこのタスクの完了を待たない。

これにより、`get_inquiry_question()`本体のロジック・生成対象の判定条件・
`_asked_cache`によるクールダウン挙動は一切変更せずに、**呼ばれるタイミングと、
その結果がいつユーザーに届くか**だけを変更した。

---

## 3. 次ターンへの織り込み方式の実装詳細

### 基本設計: 「生成は今のターンの文脈で、消費は次のターンで」

`_pending_inquiry_text: dict[thread_id, {"question": str, "generated_at": float}]`
という新しいプロセス内辞書を`active_inquiry.py`に追加した。B15
(`_pending_hedges`)・B3自身の`_pending_confirmations`が既に確立している
「スレッドIDをキーにした、プロセス内・one-shotの保留状態」パターンをそのまま
踏襲している。ただし、B15/B3の既存パターンは「**過去に提示した内容へのユーザ
ーの反応を次ターンで解釈する**」ものであるのに対し、本機能は「**今回の文脈で
生成した内容を、次ターン以降の応答に追加する**」という逆方向のデータフローで
ある点が異なる。この逆方向パターンの最も近い既存の前例はB16
(`goal_alignment.py`)の`_pending_surfaced_flag_ids`/
`get_active_goal_alignment_flags()`(週次バッチで生成済みのフラグを、後続ター
ンの応答に「提示してよい文脈」として渡す)だが、B16は生成が週次バッチ・DB永続
化を伴うのに対し、本機能は**このターンの直近会話文脈に基づいて生成し、DBには
永続化しない**(プロセス再起動でリセットされる点は他の保留状態と同じ)。

### 保留質問の消費頻度・自然さへの配慮(TTL)

指示書が指摘する通り、生成された保留質問が必ず次のターンで自然に使えるとは限
らない。次のいずれかの設計を検討した:

| 案 | 内容 | 採用可否 |
|---|---|---|
| A. 無期限に保持し、いつか会話の流れが合うまで待つ | 実装は単純だが、数日後に突然「そういえば」と古い文脈の質問が出てくると、ユーザーには何の脈絡もない発言に見える | 不採用 |
| B. 次のターンで必ず使う(現在の同期版と同じ強制追記) | 会話が全く違う話題に転換していても機械的に追記されてしまう(例: ユーザーが急ぎの用件を聞いている最中に雑談的な確認質問が挟まる) | 不採用(そもそも今回の要件が「フィットしない場合もある」ことを前提にしている) |
| **C. 短いTTL(鮮度切れで破棄)** | 生成時点の直近会話に基づいて文面自体が組み立てられている(ランキングも文面もrecent_messagesに依存)ため、時間が経つほど「その時点の文脈への自然な相槌」という前提が崩れる。一定時間内に使われなければ黙って破棄し、次に条件を満たした際に新しく生成させる | **採用** |

TTLは**30分**(`_INQUIRY_PENDING_TTL_SECONDS = 1800`)とした。判断根拠:
- `_asked_cache`の48時間クールダウン(B3既存)は「同じフィールドを再度尋ねな
  い」ための頻度制御であり、本TTL(「この一回の言い回しが今も文脈にフィットす
  るか」)とは全く別の関心事なので、同じ値を流用する理由がない。
- `goal_alignment.py`の14日クールダウン(B16)も同様に「しつこく繰り返さな
  い」ための頻度制御であり、生成された文面自体は`flag_statement`として長期間
  有効であることを前提にしている(中立的な観察文であり、会話の流れに依存しな
  い)。本機能の質問文は逆に「直近の会話の流れに乗せる」ことを目的に生成され
  ているため、性質が異なる。
- 30分は「同じチャットセッション内である可能性が高い」目安として選んだ。実運
  用のターン間隔(数秒〜数分)を大きく超えて安全マージンを持たせつつ、セッシ
  ョンをまたいで(例えば数時間後・翌日)古い質問が唐突に出てくることは防げる
  長さにした。

`take_pending_inquiry_question()`は、TTLを超えていた場合も**one-shotとして必
ず消費(pop)**する(要件: 破棄したエントリを次回以降も判定し続けない)。破棄
時は`logger.info`で記録する(単なるサイレント消滅にしない)。

### 消費されなかった場合、次にどうなるか

保留質問が期限切れで破棄された場合、そのフィールド/確認候補自体は消えない
(`_asked_cache`のクールダウンが切れていれば)。次にユーザーとの会話がその話
題の候補選定・関連度ランキングで再び選ばれれば、新しいターンの文脈で改めて生
成が走る。「同じ内容を無理に使い回す」のではなく「機会があれば都度その時点の
文脈で作り直す」設計とした(判断根拠: 既存の`get_inquiry_question()`のランキ
ング・選定ロジックを一切変更しないという方針(2章)と整合する、最も変更が小さ
い選択)。

### トーンの維持

`_SYSTEM`/`_PROMPT`・`_CONFIRM_SYSTEM`/`_CONFIRM_PROMPT`(persona.md準拠のプ
ロンプト)は一切変更していない。以前から「LLMが生成した質問文をそのまま
`response_text`に追記する」設計だった(persona rewriteを経由しない)ため、生
成タイミングを変えても文面のトーン自体への影響はない。

---

## 4. テスト結果

`backend/tests/`には、既存の方針(B2・B3等)にならい今回のテストはコミットし
ていない(スクラッチテストとして実行のみ)。実モデルAPIキーは本セッションで
取得しておらず、`unittest.IsolatedAsyncioTestCase`ベースのモック検証で確認し
た。

### 4.1 既存の回帰テスト
```
backend/tests/ 一式(8件): 全て成功(変更前と同じ)
```

### 4.2 `active_inquiry.py`の新規ロジック(11件)
`take_pending_inquiry_question()`:
- 何も保留がなければNoneを返す
- `thread_id`が`None`ならNoneを返す
- 新鮮な質問はそのまま返り、one-shotで消費される(2回目はNone)
- TTLを超えた質問は破棄されNoneを返り、かつ消費される(残らない)
- TTL境界(ぎりぎり内側)の質問は正しく返される
- 複数スレッドの保留質問は互いに独立している

`generate_and_stash_inquiry_question()`:
- `thread_id`が`None`の場合、`get_inquiry_question`自体を呼ばない(無駄なLLM
  呼び出しを避ける設計の確認)
- 質問が生成されれば`_pending_inquiry_text`に正しく保存される
- 質問が生成されなかった場合(None)は何も保存しない
- 内部で例外が発生しても呼び出し元には伝播せず、かつ`logger`にERRORとして記
  録される(要件2、`assertLogs`で確認 — 以前の`except: pass`と対照的に、今回
  は必ずログに残ることを検証)
- (2秒を超える)遅いLLM呼び出しでも正常に完了・保存できる(以前の2秒タイム
  アウトが再導入されていないことの回帰確認)

### 4.3 `orchestrator/service.py`との統合テスト(3件)
`run_orchestrator_chat`(非ストリーミング):
- 前ターンの保留質問が、今回の応答テキストに正しく追記されること、かつ
  one-shotで消費されること(要件3)。追記処理自体は
  `generate_and_stash_inquiry_question`を一切awaitしないこと(要件1の直接確
  認)。その後バックグラウンドタスクとして正しくディスパッチされること
- 背景生成が3秒かかるようモックしても、応答全体が1秒未満で返ること(以前の同
  期的timeout=2.0の再発防止の直接的な回帰テスト)

`run_orchestrator_chat_stream`(ストリーミング):
- 前ターンの保留質問が、追加のSSE deltaイベントとして正しくyieldされること
  (ストリーミング版でも要件3が満たされることの確認)

```
8 passed  (既存回帰テスト)
11 passed (active_inquiry.py 新規ロジック)
2 passed  (run_orchestrator_chat 統合テスト)
1 passed  (run_orchestrator_chat_stream 統合テスト)
= 22 passed
```

いずれもモック検証であり、実際のOllama/OpenAI呼び出し・実Supabase接続は行っ
ていない(本セッションでは新規のAPIキー・サーバーアクセス取得は行っていな
い、指示書の注意事項通り)。統合テスト実行時、開発環境の`.env`にSupabase/
OpenAIの実接続情報が完全には設定されていないため、`_cached_user_profile`等の
周辺処理は例外を握りつぶして空のデフォルト値にフォールバックしている(これは
本タスクで変更した箇所ではなく、既存の防御的実装がテスト環境でもそのまま機能
していることの副次的な確認になった)。

---

## 5. 気づいた懸念点・BA2(重複排除)に影響しそうな発見

- **`get_null_fields(jwt)`と`get_confirmation_candidates(jwt)`が`active_
  inquiry.py`内で逐次(直列)にawaitされている**: 両者は互いに独立した
  Supabase読み取りであり、`asyncio.gather`で並列化できる。fire-and-forget化
  によって応答レイテンシへの影響はなくなったため優先度は下がったが、バックグ
  ラウンドタスク自体の所要時間(=保留質問がどれだけ早く「使える状態」になるか
  = 4章のTTLとの相対的な余裕度)には直接効くため、次にこの領域を触る機会が
  あれば検討する価値がある。今回は「変更範囲を必要最小限に保つ」という判断か
  ら見送った。
- **`TaskType.COMPLEX_REASONING`が`openai_advanced_model`(重量級)にルーティ
  ングされている点**(1章): これは応答レイテンシには最早影響しないが、コスト
  面では他のB群バックグラウンド処理(大半が`openai_nano_model`)より高くつい
  ている。質問生成の複雑さに対して本当にこの階層が必要かは、本タスクの範囲外
  として検討していない。
- **`_pending_inquiry_text`はプロセス内のみで、水平スケール(複数バックエンド
  インスタンス)構成では機能しない**: `_pending_confirmations`・
  `_pending_hedges`と全く同じ制約であり、新規の制約ではないが、これで「プロ
  セス内one-shot辞書」がB3系だけで3つ(`_asked_cache`を入れれば4つ)に増え
  た。将来スケールする場合、これらをまとめてRedis等の外部ステートストアに移
  行する設計を検討する価値がある(既存のB3報告書でも同様の指摘がある)。
- **BA2(重複排除)への関連**: 本タスクは`get_inquiry_question()`の候補選定
  ロジック自体(欠落項目・確認候補の統合プール、`_rank_by_relevance`)には一
  切手を入れていない。BA2が重複排除を扱う場合、`_pending_inquiry_text`に既に
  保留中の質問がある状態で、次のターンの`generate_and_stash_inquiry_question`
  が新しい質問を生成し**上書き**してしまう(古い保留質問は使われないまま消え
  る)ケースが起こりうる点は未対応。現状は`_pending_confirmations`と同じ「新
  しい方が常に古い方を置き換える」仕様(要件を満たす最小実装)としたが、BA2で
  「候補の重複」を扱う際にはこの上書きタイミングの扱いも合わせて確認する価値
  がある。
- **マイグレーション**: 本タスクはDBスキーマ変更を一切伴わない(プロセス内辞
  書のみ)。マイグレーションファイルの作成は不要と判断した。

---

## Related Documents

- `docs/sigmaris/incident_response_latency_investigation.md`(6.5節、本タスク
  の発端となった実測調査)
- `docs/sigmaris/phase_b3_report.md`(`get_inquiry_question`の元設計)
- `docs/sigmaris/phase_b15_report.md`・`docs/sigmaris/phase_b16_report.md`
  (「pending→次ターンで消費」パターンの確立元)
