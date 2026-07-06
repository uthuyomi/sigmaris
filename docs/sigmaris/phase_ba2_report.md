# Phase BA2 実施報告: 重複取得の排除・不要データ取得の削減

対象ブランチ: `phase-ba2-dedup-and-column-trim`(mainからfork)

---

## 1. facts_ctx/trends_ctxバグの現状確認結果

**既に対応済みだった。** `docs/sigmaris/incident_facts_context_overwrite_fix.md`
はコミット`d7a1493`(2026-07-06、本タスク着手前)として既にmainに存在し、実
コードも修正済みであることを確認した:

- `orchestrator/service.py`の`_build_memory_context()`内部
  (440〜461行目)で、`facts_ctx`(top-5事実)・`trends_ctx`(top-3傾向)が
  `build_profile_context(fact_profile)`の直後に正しく組み立てられ、関数の唯
  一の戻り値に含まれている。
- `run_orchestrator_chat`・`run_orchestrator_chat_stream`の両方を確認したと
  ころ、呼び出し元に`facts_ctx`/`trends_ctx`を独自に組み立てる重複ブロックは
  残っておらず、`_build_memory_context()`の呼び出し1回のみで完結している
  (`grep`で`facts_ctx`/`trends_ctx`の出現箇所を全て確認済み — 定義箇所とコメ
  ント参照のみで、上書きパターンは存在しない)。

したがって本タスクでの追加修正は不要と判断し、主題(重複取得排除)に進んだ。

---

## 2. `get_profile_context()`重複排除の実装詳細

### 実態調査で判明した呼び出し箇所

`get_profile_context(jwt)`(`app_profile_data.py`、内部で`auth/v1/user`+
`profiles`+`saved_locations`を取得)の呼び出し箇所を全て洗い出したところ、実
測調査が指摘した3箇所に加えて、**同一ファイル内にさらに5箇所**存在すること
が判明した:

| ファイル | 関数 | 用途 |
|---|---|---|
| `app_chat_data.py` | `get_recent_messages_across_threads`(Phase A1、実測調査の指摘箇所) | `userId`のみ使用 |
| `app_chat_data.py` | `replace_chat_messages`(実測調査の指摘箇所) | `userId`のみ使用 |
| `app_chat_data.py` | `list_chat_threads` | `userId`のみ使用 |
| `app_chat_data.py` | `create_chat_thread` | `userId`のみ使用 |
| `app_chat_data.py` | `rename_chat_thread` | `userId`のみ使用 |
| `app_chat_data.py` | `delete_chat_thread` | `userId`のみ使用 |
| `app_chat_data.py` | `list_chat_messages` | `userId`のみ使用 |
| `chat.py` | `run_chat_completion`(実測調査の指摘箇所) | `aiTone`のみ使用 |
| `chat.py` | `stream_chat_completion_ui` | `aiTone`のみ使用 |
| `chat_tools.py` | `read_home_context`ツール | `homeAddress`/`preferredTravelMode`/`arrivalLeadMinutes`/`savedLocations`(フル使用) |
| `chat_tools.py` | `save_travel_plan_for_event`ツール(プラン未指定時のみ) | `arrivalLeadMinutes`のみ使用 |
| `routes/app_data.py` | `/api/app/home-context`ルート | フル使用(フロントエンドの設定画面用) |

### 選択した方式: キャッシュ(TTL方式)

**引数伝搬(呼び出し元から既知のuser_id/プロフィールを渡す)ではなく、
`get_profile_context()`自体へのTTLキャッシュを採用した。**

判断根拠:
1. **呼び出し元が単一の呼び出しグラフに収まらない**: orchestratorの
   `_prepare_session_messages`(Phase A1)から`chat.py`への経路は
   `schedule_agent_client.py`経由の**実HTTPホップ**(`POST /api/agent/chat/
   stream`)であり、Python引数として素通しできない。加えて`app_chat_data.py`
   の7関数は`routes/app_data.py`(フロントエンドのチャットUI用REST API)から
   も独立して直接呼ばれており、そちらはorchestratorの呼び出しグラフに一切含
   まれない。引数伝搬では、orchestrator内部の経路しかカバーできず、
   `routes/app_data.py`経由の呼び出しの重複は解消できない。
2. **キャッシュなら1箇所の変更で全呼び出し元に効く**: `get_profile_
   context()`自体にキャッシュを持たせれば、上記12箇所すべて(orchestrator経
   由・HTTP経由・ツール呼び出し経由のいずれも)が変更なしに恩恵を受ける。
3. **既存パターンの流用**: `orchestrator/service.py`が既に持つ`_cache_get`/
   `_cache_set`のTTLキャッシュパターン(実測調査の優先度1提案そのもの)と同
   じ設計を、`get_profile_context()`が定義されている`app_profile_data.py`自
   体に適用した(orchestratorの`_cache`辞書はorchestrator専用であり、
   `app_chat_data.py`/`chat.py`/`chat_tools.py`/`routes/app_data.py`はいずれ
   もorchestratorより下位のレイヤーで、上位レイヤーの内部状態に依存させるの
   はレイヤー違反になるため、独立したキャッシュとした)。

### 実装内容

- `app_profile_data.py`に、jwtをキーとするプロセス内TTLキャッシュ
  (`_cache: dict[str, tuple[float, dict]]`)を追加。既存の`get_profile_
  context()`本体を`_fetch_profile_context()`にリネームし、`get_profile_
  context()`はキャッシュを確認してヒットすればそれを返し、ミスすれば
  `_fetch_profile_context()`を呼んで結果をキャッシュする薄いラッパーにし
  た。
- **TTLは60秒**とした。判断根拠: `profiles`/`saved_locations`はフロントエ
  ンドからSupabaseへ直接書き込まれ、本バックエンドを一切経由しないため、書
  き込み時にキャッシュを無効化するフックを仕込む手段が存在しない(=TTLのみ
  が唯一の鮮度制御手段)。実測調査(`incident_response_latency_
  investigation.md`6.2節)が測定した1ターンの最悪ケース所要時間(約36.4秒)
  を余裕を持ってカバーしつつ、ユーザーが設定を変更した直後にどれだけ古い値
  が使われうるかという上限を、orchestratorの既存B群キャッシュ(300秒=5分、
  LLM由来で変動が緩やかなデータ向け)よりも大幅に短く抑えた。
- **失敗時はキャッシュしない**: `_fetch_profile_context()`が例外を投げた場
  合、その例外はそのまま呼び出し元に伝播し、キャッシュへの書き込みは行わな
  い(一時的な認証エラー等を60秒間キャッシュして再試行を妨げないため)。
- キャッシュキーは**jwt全体のSHA-256ハッシュ**とした(prefixではない)。理
  由は次節(3.1)で詳述する、既存コードに発見した別の不具合と直接関係する。

---

## 3. 副次的に発見・修正した問題

### 3.1 `jwt[:20]`キーによるキャッシュ衝突(既存バグ、修正済み)

`get_profile_context()`用のキャッシュキー設計を検討する過程で、
`orchestrator/service.py`の既存キャッシュ(`_cached_user_profile`・
`_cached_active_trends`)が`f"profile:{jwt[:20]}"`/`f"trends:{jwt[:20]}"`と
いう、**jwtの先頭20文字**をキーにしていることに気づいた。

検証した結果: HS256署名のJWTのヘッダー部分(`{"alg":"HS256","typ":"JWT"}`
をbase64url化したもの)は36文字の固定文字列
(`eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9`)であり、**先頭20文字はどのユーザー
のJWTでも完全に同一**になる(実際に計算して確認済み)。つまりこの2つの既存
キャッシュは、**異なるユーザーのJWTでも同じキーになり、一方のユーザーの
プロフィール・傾向データがもう一方に返される可能性がある**設計になっていた。

**実害の有無**: 過去の複数のPhase報告書(B3・B15等)が明記している通り、本
システムの現行運用形態は**単一プロセス・単一ユーザー**であるため、衝突相手
となる「もう一人のユーザー」が実在せず、**現時点では実害はない**。ただし、
これは潜在的な設計不備であり、かつ今回新設する`get_profile_context()`用
キャッシュがもし同じ`jwt[:20]`パターンを踏襲していたら同じ欠陥を複製してし
まうところだった。

**対応**: `orchestrator/service.py`に`_jwt_cache_key(jwt)`
(jwt全体のSHA-256ハッシュ)を新設し、`_cached_user_profile`・`_cached_
active_trends`の両方のキー生成をこれに置き換えた。単一テナント環境である
現状、キャッシュの中身自体は変わらない(常に唯一のユーザーの値が唯一のキー
に対応するため、ハッシュ化前後でキャッシュヒット率・返す値は変化しない)の
で、要件4(既存機能への悪影響なし)は満たしている。新設した`get_profile_
context()`のキャッシュも、最初から同じ`_cache_key()`(SHA-256ハッシュ)方
式を採用した。

### 3.2 `chat_threads`の重複読み取り(item 3、対応見送り)

実測調査が指摘した、orchestrator層(`_ensure_chat_thread`→
`get_chat_thread`)とchat.py層(`get_chat_thread`+`get_chat_thread_
version`)、さらに調査中に発見した`replace_chat_messages`内部
(`app_chat_data.py`225行目)の**3箇所**が、1ターン中に同じ`chat_threads`行
を読み直している実態を確認した。

`get_profile_context()`と同様のTTLキャッシュを`get_chat_thread()`に適用す
ることも検討したが、**見送った**。理由:

- `replace_chat_messages()`はPhase A4で導入された楽観的並行性制御
  (`expected_version`とのCAS)のために、まさにこの`get_chat_thread()`相当
  の読み取り(225行目の`current_thread = await get_chat_thread(jwt,
  thread_id)`)を**更新直前に**行っている。この関数が存在する理由そのもの
  が「他の書き込み者が間に割り込んでいないかを、更新直前の最新状態で検知す
  る」ことであり、ここをキャッシュ経由の(数十秒前の)値に差し替えてしまう
  と、**まさにこの機構が検知しようとしている競合を見逃す**方向に働きかねな
  い。
- `get_chat_thread()`は`list_chat_threads`・`rename_chat_thread`・
  `delete_chat_thread`・routes/app_data.pyのスレッド一覧・詳細取得ルートな
  ど、`chat_threads`への書き込み操作を伴う経路からも広く呼ばれており、
  `get_profile_context()`(バックエンドを経由しない外部書き込みのみ)とは異
  なり、**このバックエンド自身が頻繁に書き込むテーブル**である。TTLキャッ
  シュを適用すると、直前の`rename_chat_thread`/`create_chat_thread`の結果が
  数十秒間反映されない、といった新たな不整合を生みかねない。

以上より、パフォーマンス上の重複排除よりも、Phase A4が導入した並行性制御
の正しさを優先し、**本タスクでは`get_chat_thread()`への変更を行わなかった**
(item 3が要求通り「対応必須ではない」ため、見送りとして報告する)。

---

## 4. embedding除外の実装詳細

### 調査結果: 対象とした経路

`user_fact_items`テーブルへの読み取りを全て洗い出し、`embedding`
(vector(768))列が実際にPythonコード側で参照されているかを確認した。

- **`embedding`列がPython側で読み取られている箇所は皆無**だった
  (`memory_search.py`内の`data.get("embedding")`はOllama/OpenAIの埋め込み
  API自体のレスポンス解析であり、`user_fact_items`テーブルの列とは無関係)。
  ベクトル類似度計算は`search_fact_memory`等のRPCを通じて**Postgres側で完
  結**しており、Python側がベクトル値そのものを扱うことは一切ない。
- 既に`select`句を絞っていた箇所(`memory_search.py`のバックフィル対象検出
  クエリ、`x_privacy_filter.py`・`self_narrative.py`・`x_post_generator.py`・
  `trend_analyzer.py`の各読み取り)は、いずれも元々`embedding`を含んでおら
  ず、変更不要と確認した。
- **`select: "*"`のままだった箇所を4つ発見し、修正した**:
  1. `user_fact_data.py::get_fact_items()`(RLS経由、orchestratorの
     `_cached_fact_items`が使用。実測調査6.5節が指摘した約380件・約0.6秒の
     パースオーバーヘッドの直接の原因)
  2. `user_fact_data.py::get_fact_items_for_user()`(service-role経由、同上
     のフォールバック先)
  3. `memory_validator.py::get_confirmation_candidates()`(Phase B3。BA1
     でfire-and-forget化された結果、**毎ターンバックグラウンドで実行され
     るようになった**呼び出しでもある)
  4. `memory_validator.py::validate_all_facts()`(日次バッチの重要度判
     定・減衰・矛盾検出・論理削除の4フェーズ全ての起点)

`get_memory_dashboard_items()`(Phase B5のダッシュボード)は既に専用の
`_DASHBOARD_SELECT`で`embedding`・`search_text`を除外済みであり、変更不要
だった。

### 実装内容

`user_fact_data.py`に共有定数`FACT_ITEM_SELECT`を新設し、`user_fact_items`
の全列から`embedding`(vector(768))と生成列`search_text`のみを除いた列リス
ト(`id,user_id,category,key,value,confidence,source,notes,expires_at,
created_at,updated_at,is_stale,is_deleted,deleted_at,importance_score,
privacy_level,thread_id,invocation_id,adoption_count,source_experience_
ids`)を定義した。`get_fact_items()`・`get_fact_items_for_user()`の
`"select": "*"`をこの定数に置き換え、`memory_validator.py`からも同じ定数を
import して2箇所の`"select": "*"`を置き換えた(列リストの重複定義・将来的
な乖離を避けるため、1箇所に集約)。

列リストは、対象テーブルの全マイグレーション
(`202606240016`〜`202607120034`)を確認し、`embedding`/`search_text`を除く
現存する全列を含めた(既存の`.get()`ベースのアクセスパターンを壊さないた
め、必要最小限ではなく「embeddingとsearch_text以外は全部含める」という保守
的な絞り方にした)。

**検索処理(`memory_search.py`)への影響はない**ことを確認済み(独自の狭い
`select`句を既に使用しており、今回変更した4箇所とは完全に別のクエリ)。

---

## 5. テスト結果

`backend/tests/`には未コミット(既存方針に合わせスクラッチテストとして実行
のみ)。実モデルAPI・実Supabase接続へのアクセスは行っていない。

### 5.1 既存の回帰テスト
```
backend/tests/ 一式(8件): 全て成功
```

### 5.2 `get_profile_context()`キャッシュ(3件)
- TTL内の2回目の呼び出しがキャッシュヒットし、`get_current_user`/
  `rest_select`が実質1回しか呼ばれないこと(要件1の直接確認)
- TTL経過後は再フェッチされること
- **先頭20文字が衝突する2つの異なるjwt**(現実のHS256 JWTを模した値)で
  も、それぞれ独立してキャッシュされ、互いのプロフィールを混同しないこと
  (3.1の不具合の再発防止テスト)

### 5.3 embedding除外(6件)
- `FACT_ITEM_SELECT`が`embedding`・`search_text`を含まず、`"*"`でもなく、
  既存の主要フィールドは含んでいること
- `memory_validator.py`が`user_fact_data.py`と同一の定数オブジェクトを参
  照していること(列リストの二重管理・将来の乖離がないことの確認)
- `get_fact_items()`・`get_fact_items_for_user()`の実際のリクエストパラ
  メータが`FACT_ITEM_SELECT`を使っていること(要件2の直接確認)
- `memory_validator.py`の`get_confirmation_candidates()`・`validate_all_
  facts()`の実際のリクエストパラメータも同様であること

### 5.4 `app_chat_data.py`経由の重複排除(統合テスト、1件)
- `get_recent_messages_across_threads()`と`list_chat_threads()`を同一jwt
  で連続して呼び出した場合、`get_current_user`(認証+プロフィール+保存済み
  住所のフルチェーン)が実質1回しか実行されないこと(要件1をモジュール境界
  を跨いだ形で確認)

### 5.5 orchestrator既存キャッシュの衝突修正(3件)
- 先頭20文字が衝突する2つのjwtで`_jwt_cache_key()`が異なる値を返すこと
- 同一jwtに対しては安定した値を返すこと
- `_cached_user_profile()`が、衝突する2つのjwtに対して独立してキャッシュ
  され、互いの`user_fact_profile`を混同しないこと

### 5.6 Phase BA1のテストの再実行(回帰確認)
BA1で作成した14件のスクラッチテスト(fire-and-forget化・pending inquiry
question関連)を再実行し、全て成功することを確認した。BA2の変更(get_
profile_contextのキャッシュ化・embedding列の除外・jwtキー修正)がBA1の
挙動に影響していないことを確認した。

```
8 passed  (既存回帰テスト)
3 passed  (get_profile_contextキャッシュ)
6 passed  (embedding除外)
1 passed  (app_chat_data経由の重複排除・統合)
3 passed  (jwtキー衝突修正)
14 passed (Phase BA1の既存スクラッチテスト再実行)
= 35 passed
```

---

## 6. 気づいた懸念点・BA3(Memory Snapshot方式)に影響しそうな発見

- **`jwt[:20]`衝突バグの範囲確認**: `_cached_user_profile`・`_cached_
  active_trends`以外に同種のパターン(`jwt[:N]`をキャッシュキーに使う箇
  所)が残っていないか、`grep`で確認済み(該当なし)。ただし、将来的に同種
  のキャッシュを追加する際は、この報告書の3.1節を参照して同じ轍を踏まない
  よう注意が必要。
- **単一テナント前提への依存が増えている**: 今回の`jwt[:20]`衝突・
  `get_profile_context`のキャッシュ設計いずれも、「実害なし」の根拠を最終
  的には「現状は単一ユーザーしかいない」という運用前提に置いている。B3・
  B15の既報告書も同様の前提に依拠しており、**この前提が将来崩れた場合(マ
  ルチテナント化)、今回のようなキャッシュ設計を含め、プロセス内・jwtキー
  ベースの各種キャッシュ・保留状態(`_pending_confirmations`・`_pending_
  hedges`・`_pending_inquiry_text`・本タスクの2つの新規キャッシュ)を包括的
  に再点検する必要がある**。BA3がMemory Snapshot方式(何らかの形での状態の
  外部化・永続化)を検討するのであれば、この「プロセス内jwtキー辞書」群を
  まとめて棚卸しする良い機会になる。
- **`FACT_ITEM_SELECT`は「embeddingとsearch_text以外は全部」という保守的
  な絞り方**: 本当に必要な列だけに絞ればさらに転送量を削減できる可能性が
  あるが、呼び出し箇所ごとに必要な列が微妙に異なり(3章参照)、将来の呼び
  出し追加のたびに列不足で壊れるリスクを避けるため、今回は「大きい列だけ除
  く」保守的な方針にとどめた。BA3で読み取りパスをさらに見直す場合、呼び出
  し元ごとに本当に必要な最小列を再検討する余地がある。
- **`get_chat_thread()`の重複読み取りは未解消のまま残っている**(5.2節)。
  Phase A4のCAS機構と衝突しない形での重複排除(例: `replace_chat_messages`
  だけは常に非キャッシュの直接読み取りを行い、それ以外の読み取り専用経路
  [`_ensure_chat_thread`・`list_chat_threads`等]にのみ短いTTLキャッシュを適
  用する、といった経路ごとの使い分け)は今回検討していない。BA3または今後
  の別タスクで、この非対称なキャッシュ適用を検討する価値がある。

---

## Related Documents

- `docs/sigmaris/incident_response_latency_investigation.md`(本タスクの発
  端となった実測調査、6.2/6.5節)
- `docs/sigmaris/incident_facts_context_overwrite_fix.md`(1章で確認した既
  修正済みの問題)
- `docs/sigmaris/phase_b5_report.md`(`_DASHBOARD_SELECT`、embedding除外の
  先行事例)
- `docs/sigmaris/phase_a4_report.md`(`chat_threads.version`によるCAS機構、
  5.2節の見送り判断の根拠)
- `docs/sigmaris/phase_ba1_report.md`(直前のBA群タスク、`_pending_
  inquiry_text`等プロセス内jwtキー辞書の前例)
