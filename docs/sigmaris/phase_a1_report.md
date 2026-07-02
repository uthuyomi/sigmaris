# Phase A1 実施報告: セッション継続方式の実装

**目的:** スレッドをまたいでも直近文脈が引き継がれるようにし、かつ毎ターン全履歴を送る方式による線形なトークン増大を解消する。
**作業ブランチ:** `phase-a1-session-continuity`（`phase-a0-chat-thread-consolidation`から分岐。Phase A0の統一済み書き込み経路に依存するため）
**範囲:** Phase A2(プロンプト構造の並べ替え)・A3(decision_log本稼働)・A4(排他制御)・A5(RAG見直し)には着手していない。

---

## 0. 実装前に発見した前提の誤り（着手前に確認を取った内容）

実装前の再調査で、監査レポート(1-A章)の前提そのものに誤りがあることが判明した。

**実際のフロントエンドには互いに独立した2つのチャットUIが存在する:**

1. **`/chat`**（`app-shell.tsx`のナビゲーションにリンクされている、実際にユーザーが使う本編のチャットページ。Phase A0で統一したスレッドサイドバーを持つ） → `useChat` → `/api/chat` → バックエンド `/api/chat/stream`（`chat.py`直呼び）。**`chat_messages`への永続化は行うが、fact/self_model/trendの記憶注入は一切行わない**（監査レポートの1-B相当）。
2. **`/sigmaris`**（`app-shell.tsx`にリンクなし。ナビゲーション上到達不可能なページ） → `sendOrchestratorMessage` → `/api/orchestrator/chat` → `orchestrator/service.py`。記憶注入は行うが、`schedule_agent_client.py`が`persist_thread: False`を固定していたため**`chat_messages`への永続化を一切行っていなかった**。スレッド一覧UIも存在せず、会話はReactのstateのみでリロードすると消える。

Phase A1の指示書は`orchestrator/service.py`への実装を明示的に指定していたため、文字通り実装すると「ナビゲーションから到達できないページの、しかも自分自身のトラフィックすら記録していない経路」に対してセッション継続機能を作ることになり、機能として空洞化するリスクがあった。この点を実装前に確認を取り、**「指示書通りorchestrator/service.pyのみを対象とし、かつorchestrator経由の会話もchat_messagesへ永続化するよう合わせて変更する」**方針で進めることの了承を得た。

---

## 1. 直近ログウィンドウの実装方式の詳細

### N の初期値

`settings.sigmaris_recent_message_window`（`backend/app/config.py`）として環境変数`SIGMARIS_RECENT_MESSAGE_WINDOW`で上書き可能な設定値とし、初期値は **40** とした（指示書の目安「30〜50」の中央よりやや上）。根拠: 5章のトークン実測で、代表的な往復パターン（1往復あたり約35トークン相当の短い実務的なやり取り）40件で約1,400トークン相当となり、固定システムプロンプト（約1,600トークン）と合わせても3,000トークン程度に収まる。オーバーヘッドとして許容できる範囲と判断した。

### 取得ロジック

`backend/app/services/app_chat_data.py`に`get_recent_messages_across_threads(jwt, *, limit)`を新設した（`list_chat_messages`とは別関数。既存のスレッド単位取得は無改修）。

```python
async def get_recent_messages_across_threads(jwt, *, limit):
    context = await get_profile_context(jwt)
    user_id = context["userId"]
    result = await rest_select(jwt, "chat_messages", {
        "select": "id,thread_id,role,parts,metadata,created_at",
        "user_id": f"eq.{user_id}",
        "order": "created_at.desc",
        "limit": str(limit),
    })
    rows = result if isinstance(result, list) else []
    rows.reverse()  # 時系列昇順に戻す
    return rows
```

`thread_id`によるフィルタを行わず、ユーザー単位（`user_id`）で直近N件を横断取得している。既存の`idx_chat_messages_thread_order (thread_id, message_order asc)`インデックスはこのアクセスパターン（`user_id`条件＋`created_at`ソート）を効率的にカバーできないため、新規インデックスを追加した:

```sql
-- supabase/migrations/202607030025_chat_messages_user_created_index.sql
create index if not exists idx_chat_messages_user_created_at
  on public.chat_messages (user_id, created_at desc);
```

> ⚠️ **このマイグレーションは未適用**。ローカル環境に`SUPABASE_SERVICE_ROLE_KEY`がなく、`scripts/apply_migration.py`（本番サーバー上で実行する想定のスクリプト）を私の手元からは実行できなかった。本番サーバーで`python3 scripts/apply_migration.py 202607030025`を実行するか、Supabase Dashboard の SQL Editor で手動適用が必要。**インデックスがなくても機能は正しく動作する**（PostgRESTはシーケンシャルスキャンにフォールバックするだけ）が、`chat_messages`の行数が増えるほど遅くなるため、パフォーマンス上は適用を推奨する。

### 統合方法の選定理由（system_override注入 vs input配列再構築）

**input配列を直近ログウィンドウで再構築する方式を採用した**（system_override側へのテキスト注入は不採用）。

理由:
1. 指示書が「直近ログウィンドウを正として扱い、フロントエンドから送られてくるmessages配列への依存を段階的に減らす」ことを明示的に求めていた。system_overrideへのテキスト注入は「参考情報を付け加える」実装であり、依存を減らす方向に沿わない。
2. `chat.py`の`client.responses.create()`は`input`配列を実際の会話ターンとして解釈する。会話構造を保ったまま渡す方が、テキストブロックとして丸めてsystem_overrideに埋め込むよりモデルにとって自然で、将来ツール呼び出しの文脈を扱う際にも破綻しにくい。
3. 既存の`system_override`（`user_profile_context` + `self_model_context`）は既に一定の長さがあり、そこに会話ログをさらに追記すると「システムプロンプトの中に会話が埋め込まれる」歪な構造になる（監査7章で指摘した「固定指示の前に可変要素が来てキャッシュが効きにくい」問題を悪化させかねない）。

ただし「フロントエンドから送られてくる`messages`配列を完全なplaceholderに置き換える」のではなく、**その配列の最後にあるユーザーの新規発言1件だけ**を直近ログウィンドウの末尾に追加する設計にした。

```python
combined = window_messages + ([latest_user] if latest_user else [])
```

理由: リクエスト到達時点でDBにはまだ「今回の新規ユーザー発言」が書き込まれていない（永続化は応答生成後に行われるため）。ウィンドウだけを送ると直近の質問そのものが欠落する。かといって呼び出し元の`messages`配列全体をウィンドウに追加すると、既に永続化済みの過去ターンとウィンドウ内容が重複する可能性がある。「呼び出し元の配列からは最新のユーザー発言1件だけを信頼する」のが、指示書の「実装時にリスクの少ない方を選ぶ」という指示に対する最も安全な折衷案と判断した。

トレードオフとして、呼び出し元が一度のリクエストで複数の新規未永続メッセージを送ってきた場合（通常のチャットUIでは起こらないが、リトライや特殊なクライアント実装では起こり得る）、最後の1件以外は失われる。現状把握している全クライアント（Webの`/sigmaris`、WearOS）は「1ターンにつき新規ユーザー発言1件」のみを送る設計になっているため実害はないと判断した。

### メッセージ形式の変換

`chat_messages.parts`はUIMessage形式（`[{"type":"text","text":"..."}]`）のJSONBだが、`orchestrator/service.py`が扱う`messages`はシンプルな`{"role","content"}`形式（`OrchestratorMessage`スキーマに準拠）。`_extract_text_from_parts()` / `_window_rows_to_messages()`を新設し、`role`が`user`/`assistant`以外の行（想定外だが将来的な`system`ロール等）は除外、`parts`からtext部分のみを抽出して結合する変換を行っている。

### スレッド永続化の有効化（判断根拠）

`schedule_agent_client.py::_build_payload()`の`"persist_thread": False`固定を`persist_thread`パラメータ化し、`orchestrator/service.py`から`True`を渡すようにした。

**リスクと対策**: `chat.py::run_chat_completion()`は`persist_messages=True`かつ対象の`chat_threads`行が存在しない場合`RuntimeError("Requested chat thread was not found.")`を送出する。WearOSのように`thread_id`をクライアント側で自由生成し、事前にスレッド行を作らないクライアントが実在するため、単純に`persist_thread=True`を渡すだけでは本番の会話が壊れる可能性があった。

対策として`_ensure_chat_thread(jwt, thread_id)`を新設し、スケジュールエージェント呼び出し**前**に該当スレッド行の存在を確認し、なければ`create_chat_thread()`で作成するようにした。さらに、その確認/作成処理自体が失敗した場合（ネットワーク不調・同時作成のレース等）は、例外を送出せず**その回だけ`persist_thread=False`にフォールバック**する設計にした（チャット応答そのものを止めないことを優先）。同時作成のレースについては、作成失敗後に再度`get_chat_thread`で存在確認を行い、既に存在していれば正常系として続行する。

---

## 2. previous_response_id の扱いに関する判断

`chat.py`を再確認した結果、`previous_response_id`は`run_chat_completion()`（526行目）・`stream_chat_completion_ui()`（818行目）の**それぞれの関数内でローカル変数として毎回`None`に初期化**されており、リクエストをまたいだ再利用は元々行われていなかった（同一リクエスト内のツール呼び出しリトライループ内でのみ使い回される）。

つまり「previous_response_idをNoneのままにする」という判断は、**新たに何かを変更する話ではなく、既存の実装が既にそうなっていることの確認**だった。今回のセッション継続方式（直近ログウィンドウを毎回明示的に構築してinputに含める）と、リクエストをまたいだ`previous_response_id`チェインは論理的に排他ではないが、後者を導入する意味は薄い（inputに全文脈を含めている以上、OpenAI側にも文脈保持させると二重管理になる）ため、コード変更は行わなかった。

---

## 3. `/api/chat/stream`経路（1-B）について

**今回は変更していない**（指示書通りスコープ外）。ただし0章の発見の通り、この経路こそが実際にナビゲーションからユーザーが到達する唯一のチャットUIである。この経路には長期記憶注入が一切なく、かつ今回のセッション継続の恩恵も受けない。

**今後の課題として残る**: Phase A2以降、またはA1の追加スコープとして、`/chat`ページ（`assistant.tsx`）を`orchestrator/service.py`経由に切り替えるか、あるいは`chat.py`直呼び経路にも記憶注入・セッション継続を持たせるかの意思決定が必要になる。現状のままでは「セッション継続機能が実装されたが、実際にユーザーが使う画面では効果が出ない」状態が続く。

---

## 4. スレッド横断テストの結果

**制約**: ローカル環境に`OPENAI_API_KEY`と`SCHEDULE_AGENT_SECRET`が設定されておらず、実際のOpenAI応答を経由するHTTPレベルのE2Eテスト（`curl`で`/api/orchestrator/chat`を叩き、モデルの応答内容でスレッド横断を確認する）は実行できなかった。そのため、**新設したロジックを実データ層で直接呼び出す検証**を、本番と同一のSupabaseプロジェクトに対して実施した（OpenAI呼び出しの手前までを検証）。

検証スクリプト（要旨。実行後、生成したテストデータは全て削除済み）:

```
1. thread_a を新規作成 → _ensure_chat_thread が chat_threads 行を作成することを確認
2. thread_a に「私の好きな色はコバルトブルーです」というユーザー発言 + 応答を
   replace_chat_messages() で永続化
3. get_recent_messages_across_threads() を limit=40 で呼び出し、
   thread_a の内容が（thread_bを一切指定していないユーザー単位のクエリで）
   含まれることを確認
4. thread_b（新規、履歴なし）に対して _prepare_session_messages() を呼び出し、
   incoming = [{"role":"user","content":"さっき好きだと言った色は何でしたっけ？"}]
   を渡す
5. 戻り値の session_messages に thread_a の「コバルトブルー」が含まれ、
   かつ末尾が thread_b の新規発言であることを確認
```

**実行結果（ログ全文）:**

```
thread_a=a6358091-84b8-4a9b-b7f0-5128db786cb5
thread_b=454fa7c9-576a-499d-8e28-078de67afe4e
PASS: _ensure_chat_thread created thread_a row
PASS: _ensure_chat_thread is idempotent on existing thread
PASS: seeded thread_a with a distinctive fact via replace_chat_messages
window size=6 matching_content_found=True
PASS: get_recent_messages_across_threads sees thread_a's content (cross-thread, not thread-scoped)
effective_thread_id == thread_b: True
persist_thread=True
session_messages count=7
session_messages includes thread_a's fact: True
session_messages ends with thread_b's new question: True
PASS: requirement 1 (thread A -> thread B context carryover) verified at the data layer
PASS: thread_b row auto-created by _prepare_session_messages
requested limit=3, got=3
PASS: window respects the limit parameter (token-ceiling mechanism)

ALL DATA-LAYER CHECKS PASSED
```

**要件1（スレッドA→スレッドBの文脈引き継ぎ）は、`orchestrator/service.py`に実際に組み込まれるデータの流れ（DB読み取り→ウィンドウ構築→最新発言の合成）としては確認できた。** ただし「モデルが実際にその文脈を使って正しく回答するか」はOpenAI呼び出しそのものを検証していないため未確認。この部分は本番環境（`OPENAI_API_KEY`が設定されているUbuntuサーバー）でのみ検証可能。

既存のバックエンドテスト（`backend/tests/orchestrator/`、8件）は全てPASSし、回帰は確認していない。

---

## 5. トークン数の実測値

同じくOpenAI課金APIを経由しない検証として、`tiktoken`（`cl100k_base`エンコーディング。GPT-5.4-mini系列の正確なトークナイザーではなく近似値である点に注意）でウィンドウ内容と固定システムプロンプトのトークン数を直接計測した。

実務的な短い往復（例:「明日の午前中の予定を確認したい」⇔「明日の午前中は…」など、1往復あたり平均約35トークン相当）を40件（N=40の設定値通り）投入した場合:

| 項目 | トークン数（概算） |
|---|---|
| 直近ログウィンドウ（40メッセージ） | 約1,410 |
| 固定システムプロンプト（`chat_prompts.py::build_system_prompt`） | 約1,592 |
| **合計（1リクエストあたりの推定入力トークン数）** | **約3,002** |

この合計は**Nを超えてどれだけ会話を継続してもこの水準で頭打ちになる**（ウィンドウが常に最新N件に固定されるため）。移行前は「毎ターン全履歴を送る」設計だったため、たとえば100往復目には旧方式で7,000トークンを超えていたと推定される内容が、新方式では常に約3,000トークン程度に収まる。

**未検証**: 実際のOpenAI課金レスポンス（`usage.input_tokens`等）による実測ではなく、あくまでローカルトークナイザーによる推定値である点は明記しておく。

---

## 6. 気づいた懸念点・Phase A2以降に影響しそうな発見

1. **（最重要・0章で詳述）`/chat`ページは今回の変更の恩恵を受けない**。ナビゲーションからアクセス可能な唯一のチャットUIが`orchestrator/service.py`を経由しないため、Phase A2以降でこの経路をどうするかの意思決定が必要。
2. **マイグレーション未適用**: `202607030025_chat_messages_user_created_index.sql`は本番サーバーでの手動適用が必要（1章参照）。適用するまでは`get_recent_messages_across_threads`が`chat_messages`の全件シーケンシャルスキャンにフォールバックする。
3. **`persist_thread`有効化は`orchestrator/service.py`経由の全呼び出し（WearOS・`/sigmaris`ページ・将来のクライアント全て）に影響する**。今回の変更で、これらの会話が初めて`chat_messages`に記録されるようになる。これは意図した挙動だが、「今まで記録されていなかったものが今後は記録される」というデータ量の増加が今後発生する。既存のプロアクティブアクション（`proactive/actions.py::run_morning_briefing`等）も`run_orchestrator_chat`を経由しているため、朝夕週次のブリーフィング会話も今後`chat_threads`にスレッドとして残るようになる（`thread_id=f"proactive-{action_name}-{uuid4()}"`という使い捨てIDのまま）。これらのプロアクティブ用スレッドがユーザーの`/chat`スレッド一覧に混在して見える設計になっていないか（`/chat`は現状`orchestrator/service.py`を経由しないため直接の影響はないはずだが、将来1の課題を解消する際に考慮が必要）。
4. **`active_inquiry`・`memory_extractor`は意図的に変更していない**（要件3を満たすため、既存の`messages`パラメータをそのまま使用）。この2つは「直近の生ログ」ではなく「今回のスレッドの見える会話」を対象にした別の関心事のため、Phase A1の対象外とした。将来的にこれらも横断ウィンドウを参照するよう拡張する余地はある。
5. **トークン計測がGPT-5.4-mini系列の正確なトークナイザーではない**。`cl100k_base`は近似値であり、正確な数値は本番環境でのOpenAI API利用実績（レスポンスの`usage`フィールド）から確認する必要がある。

---

## テスト・検証章の充足状況（マージ可否の判断）

指示書は「テスト・検証章の要件をすべて満たせていることを確認できたら、確認を待たずmainへプッシュ・マージしてよい」としているが、以下の理由により**要件を完全には満たせていないと判断し、マージ前の確認を求める**。

- 要件1（スレッド横断の文脈引き継ぎ）: **データ層では確認済み**。実際のOpenAI応答での確認は環境制約（`OPENAI_API_KEY`未設定）によりできていない。
- 要件2（トークン数の頭打ち）: **確認済み**（`tiktoken`による推定値ベース）。
- 要件3（既存の記憶注入への非影響）: **確認済み**（`git diff`でfact/self_model/trend関連コードが無変更であることを確認、および既存テストが全てPASS）。
- 要件4（Phase A0の書き込み経路を前提とし、新たなSupabase直接アクセスを作らない）: **確認済み**（`app_chat_data.py`経由のみ）。

加えて、0章の「実装対象の`orchestrator/service.py`はナビゲーションから到達できないページの経路である」という発見自体が、指示書に明記された「判断に迷う実装上の分岐」に該当するため、この点も含めてマージ前にご確認をお願いします。

---

## Related Documents

- [global_state_migration_audit.md](global_state_migration_audit.md) — 発端となった監査レポート（1-A章の前提に誤りがあったことは本レポート0章を参照）
- [phase_a0_report.md](phase_a0_report.md) — 本Phaseが依存するchat_threads/chat_messages書き込み経路統一の報告
