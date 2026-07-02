# Phase A1-b 実施報告: `/chat` を orchestrator 経由に切り替える

**目的:** 実際にユーザーが使う唯一のチャットUI(`/chat`)を`orchestrator/service.py`経由に切り替え、Phase A1のスレッド横断セッション継続と、既存のfact/self_model/trend記憶注入を実利用画面に反映させる。
**作業ブランチ:** `phase-a1b-chat-orchestrator-switch`（`phase-a1-session-continuity`から分岐）
**範囲:** Phase A2(プロンプト構造)・A3(decision_log本稼働)・A4(排他制御)・A5(RAG見直し)には着手していない。

---

## 0. 実装前に発見した2つの破壊的リスク（着手前に確認を取った内容）

指示書通りの単純な切り替え（`/chat`のAPIルートが叩く先を`/api/chat/stream`から`/api/orchestrator/chat/stream`に変えるだけ）を検証した結果、要件3「既存UI動作...ツール呼び出し結果表示...が引き続き問題なく動作すること」を満たせない、確度の異なる2つの問題を実装前に発見した。

1. **確実に起きる問題**: `routes/agent.py::agent_chat_stream`（orchestratorがschedule-agentを呼ぶ際に経由する既存の中継エンドポイント）は、上流の`chat.py`ストリームから`text-delta`と`finish`イベントのみを転送し、`tool-input-available`/`tool-output-available`/`tool-output-error`（ツール呼び出しのUI表示に使われるイベント）を無条件に握りつぶしていた。単純に切り替えるだけでは、ツール呼び出しの表示カードが永久に消える。
2. **検証不能だが実害があり得る問題**: カレンダー登録などの確認ボタンフロー（「予定を登録しますか？」）は、`<!-- shiftpilot-confirmation {...} -->`というHTMLコメント＋JSON文字列をアシスタントのテキストに直接埋め込む方式で実装されている。orchestrator経由にすると、このテキストは`persona_rewriter.py`のLLMによるトーン変換パスを通る。トーン変換の指示文には「不可視のマークアップを保持せよ」という指示が一切なく、`response_guard.py`の機械的ガード（日時・数値等の一致確認）もHTMLコメントの有無を直接検査していないため、確認マーカーが変換中に欠落・破損しても検出されない可能性があった。ローカルに`OPENAI_API_KEY`がなく実際に検証できなかった。

この2点を実装前に確認を取り、「両方とも作り込んで解消する」方針で進めることの了承を得た。

---

## 1. 変更した箇所の一覧

### バックエンド

| ファイル | 変更概要 |
|---|---|
| `backend/app/routes/agent.py` | `agent_chat_stream`が`tool-input-available`/`tool-output-available`/`tool-output-error`イベントを`{"tool_event": {...元イベント...}}`として中継するように追加（従来は`text-delta`/`finish`のみ転送） |
| `backend/app/services/orchestrator/schedule_agent_client.py` | `ScheduleAgentStreamEvent`に`tool_event`フィールドを追加。`call_schedule_agent_stream`が上流の`tool_event`を解釈してyieldするように変更 |
| `backend/app/services/orchestrator/service.py` | ①`OrchestratorStreamEvent`に`tool_event`フィールドを追加し、`run_orchestrator_chat_stream`が中継。②`run_orchestrator_chat`・`run_orchestrator_chat_stream`の両方で、schedule-agentの応答に確認マーカー(`<!-- shiftpilot-confirmation ... -->`)が含まれる場合は`rewrite_with_persona`/`rewrite_with_persona_stream`を**スキップ**し、`replace_forbidden_assistant_names`のみを適用した生テキストをそのまま返すように変更（`CONFIRMATION_MARKER_RE`は`chat_messages.py`から再利用、新規正規表現は定義していない） |
| `backend/app/routes/orchestrator.py` | `orchestrator_chat_stream`のSSE出力に`tool_event`を追加し、docstringのイベント形式説明を更新 |

**新規マイグレーションは今回不要**（DBスキーマ変更なし）。

### フロントエンド

| ファイル | 変更概要 |
|---|---|
| `frontend/src/lib/orchestrator/stream-translator.ts`（新規） | オーケストレーターのSSE形式(`delta`/`tool_event`/`done`/`error`)を、AI SDKのUI Message Streamプロトコル(`start`/`text-start`/`text-delta`/ツールイベント/`text-end`/`finish`)に変換するReadableStreamトランスフォーマー |
| `frontend/src/app/api/chat/route.ts` | バックエンドの呼び先を`/api/chat/stream`から`/api/orchestrator/chat/stream`に変更。受信した`UIMessage[]`を`{role, content}`形式に変換して送信し、レスポンスは上記トランスレーターを通して返す |

`frontend/src/app/chat/page.tsx`、`chat-workspace.tsx`、`assistant.tsx`、`Thread`コンポーネント、`chat-threads.ts`（Phase A0で統一済み）は**無改修**。UI側は`/api/chat`が返すストリーム形式が変わらないため、クライアント側のトランスポート設定（`AssistantChatTransport({api: "/api/chat", body: {threadId}})`）に一切手を入れていない。

---

## 2. レスポンス形式の差異とその吸収方法

| 項目 | `chat.py`直呼び(旧) | orchestrator経由(新) | 吸収方法 |
|---|---|---|---|
| ストリームプロトコル | AI SDK UI Message Stream準拠(`start`/`text-start`/`text-delta`/`tool-*`/`text-end`/`finish`) | 独自の簡易SSE(`delta`/`tool_event`/`done`/`error`) | `stream-translator.ts`で変換。`start`/`text-start`は接続確立時に即座に発行し、以降`delta`→`text-delta`、`done`→`text-end`+`finish(stop)`、`error`→エラーメッセージのtext-delta+`finish(error)`にマッピング |
| ツール呼び出しUI | `chat.py`が直接`tool-input-available`等を発行 | `agent_chat_stream`が握りつぶしていた | 0章で詳述の通り`agent_chat_stream`を修正し中継。バックエンドの`tool_event`はAI SDK形式のまま（`chat.py::_tool_ui_chunks()`が生成した元の辞書）なので、フロントの変換層は中身を解釈せず**そのまま右から左へ転送**するだけで済む |
| 確認マーカー | `chat.py`の生テキストがそのままストリーム | persona rewriteを経由すると破損の恐れ | 0章で詳述の通りバックエンド側で確認マーカーを検出したらrewriteをスキップ |
| メッセージ入力形式 | `UIMessage[]`(parts配列)をそのまま`/api/chat/stream`に転送 | orchestratorは`{role, content}`のシンプル形式(`OrchestratorMessage`スキーマ)を要求 | `route.ts`の`extractText()`で`parts`からtext部分のみ抽出して変換。添付ファイル(`type: "file"`のparts)は現状**送信されない**（6章の懸念点参照） |
| 記憶注入 | `system=None`で一切注入されない | `orchestrator/service.py`がfact/self_model/trend/直近ログウィンドウを注入 | 変換不要。orchestrator側の既存ロジックがそのまま効くようになる（今回の主目的） |

**SSEの分割境界(チャンクがJSON途中で分割される場合)への対応**: `stream-translator.ts`は`\n\n`区切りでバッファリングしながら読み進める実装にした（1チャンク=1行という単純な前提を置いていない）。Node.js環境で合成テストを実施し、`data: {...}`がバイト境界で分割された場合でも正しく再構成されることを確認済み(4章参照)。

---

## 3. `routes/chat.py`(旧経路)を残したか削除したか

**残した。** 理由:

- `POST /api/chat/stream`自体は今回の変更で呼び出し元がゼロになった。
- しかし同じ`routes/chat.py`ルーター内の`GET /api/chat/capabilities`は、`frontend/src/lib/backend/chat.ts::readBackendChatCapabilities()`から**現在も呼ばれている**（さらに`frontend/src/app/api/backend/chat-capabilities/route.ts`という診断用エンドポイントが依存している）。ファイル全体を削除すると、この無関係な依存を巻き添えで壊すことになる。
- `/api/chat/stream`ハンドラ単体を`routes/chat.py`から削除することも検討したが、(a) 指示書が削除を必須要件としていないこと、(b) 万一今回のorchestrator切り替えに問題が見つかった際のロールバック先として温存しておく価値があること、(c) 削除してもコードベースの複雑性が大きく下がるわけではないこと、を踏まえて**現状維持**とした。

今後の課題として: `/api/chat/stream`が本当に不要と確定した時点（orchestrator経由の運用が安定した後）で、`routes/chat.py`から`/stream`ハンドラのみを削除し、`chat.py::stream_chat_completion_ui`本体の要否も含めて再検討することを推奨する。

---

## 4. テスト・検証の結果

### 4-1. バックエンド

- `python -c "import app.main"`: エラーなし。
- `backend/tests/`（8件）: 全てPASS（回帰なし）。
- 確認マーカー検出ロジックの直接検証（実データではなく正規表現ロジック単体）:
  ```
  with marker match: True
  without marker match: False
  PASS: confirmation marker detection works as expected
  ```
- **未検証**: `agent_chat_stream`のtool_event中継、`rewrite_with_persona`スキップ分岐の実際のLLM応答での動作。いずれも`OPENAI_API_KEY`が必要で、ローカル環境には設定されていない。

### 4-2. フロントエンド

- `npx tsc --noEmit -p .`: エラー0件。
- `npx eslint`: 対象ファイルで警告・エラー0件。
- `stream-translator.ts`のロジックを、Next.jsの外側でNode.js単体実行できる形に移植し、合成SSE入力に対して4パターンを検証（実行結果全文）:
  ```
  test1 types: [ 'start', 'text-start', 'text-delta', 'text-delta', 'text-end', 'finish' ]
  test1 PASS   -- 通常のdelta+done、start/text-start/text-end/finishの順序が正しいこと
  test2 events: [{"type":"start",...},{"type":"tool-input-available","toolCallId":"call-1","toolName":"list_app_events","input":{"date":"2026-07-04"},"dynamic":true},{"type":"text-start",...},...]
  test2 PASS   -- tool_eventがtoolCallId/toolNameを含め改変なく中継されること
  test3 PASS   -- errorイベントがfinishReason:"error"として正しく終端されること
  test4 PASS   -- data:{...}\n\n がバイト境界で分割されても正しく再構成されること

  ALL TRANSLATOR TESTS PASSED
  ```

### 4-3. 実モデル応答での確認

**できなかった。** ローカル環境に`OPENAI_API_KEY`・`SCHEDULE_AGENT_SECRET`が設定されておらず、実際に`/chat`からメッセージを送信してモデルの応答・ツール呼び出し表示・確認ボタンの実地確認を行うことができなかった（Phase A1のときと同じ制約）。

代わりに実施したのは:
- バックエンドの変換ロジック（tool_event中継、確認マーカー検出・rewrite分岐）のコードレビューと、mockベースの既存テストが壊れていないことの確認。
- フロントエンドの変換ロジック（SSEプロトコル変換）の実行時テスト（本物のOpenAI応答を模した合成データで、Web標準の`ReadableStream`を実際に流して検証。Next.js固有のパスエイリアスを除けば本番コードと同一のアルゴリズム）。

**本番環境（`OPENAI_API_KEY`が設定されたUbuntuサーバー）での実地確認が必須。** 特に確認してほしいのは: (a) 実際にカレンダー登録を伴う会話で確認ボタンが正しく表示・機能すること、(b) ツール呼び出し中に何らかのインジケーターが表示されること、(c) fact/self_model/trendの内容が応答に反映されていること（バックエンドログの`orchestrator: loaded fact_items count=...`等で確認可能）。

### 4-4. 記憶注入がプロンプトに含まれることの確認

Phase A1のデータ層検証と同様の方法で、`orchestrator/service.py`の`profile_context`/`self_model_context`組み立てロジック自体は今回一切変更していないことを`git diff`で確認済み（0行の変更）。`/chat`が今回`orchestrator/service.py`を経由するようになったことで、このロジックが**呼ばれるようになる**という構造的な変化そのものが記憶注入を有効化する仕組みであり、ロジック自体の正しさはPhase A1以前から存在する既存機能に依存している。

---

## 5. WearOSへの影響

**影響なし（コンタクトの構造的な理由により）。**

- WearOSは`POST /api/orchestrator/chat`（非ストリーミング）を直接叩いている。このエンドポイントのリクエスト/レスポンス契約(`OrchestratorChatRequest`/`OrchestratorChatResponse`)は今回一切変更していない。
- `run_orchestrator_chat`（非ストリーミング版）に加えた変更は、確認マーカー検出時の`rewrite_with_persona`スキップ分岐のみ（3章参照）。これは通常の会話（確認マーカーを含まない）では従来と全く同じコードパスを通るため、動作に差は生じない。確認マーカーを含む場合も、結果的に生テキストがそのまま返るだけで、レスポンスの型・フィールドは変わらない。
- ツール呼び出しイベント中継(`tool_event`)は**ストリーミングエンドポイントのみ**に追加した機能であり、WearOSが使う非ストリーミングエンドポイントには存在しない概念のため無関係。
- 実機（WearOSアプリ）での再検証はしていないが、契約が変わっていないため影響がないと判断した。念のため次回WearOSを使う際に会話が問題なく続くことを確認することを推奨する。

---

## 6. 気づいた懸念点・Phase A2以降に影響しそうな発見

1. **ファイル添付が送れなくなった**: `route.ts`の`extractText()`は`UIMessage.parts`から`type:"text"`のみを抽出しており、`type:"file"`（画像添付等）を無視している。`orchestrator/service.py`が受け取る`OrchestratorMessage`スキーマ自体が`role`+`content`(文字列)のみで添付ファイルの概念を持たないため、根本的にはorchestrator側にマルチモーダル対応がない限り解消できない。旧`chat.py`直呼び経路では`build_attachment_facts(extract_latest_image_contexts(messages))`で画像を解釈していたため、これは実質的な機能後退。次のPhaseでの対応検討を推奨する。
2. **確認マーカーのrewriteスキップは持続的トレードオフを生む**: 確認ボタンを含むメッセージは常にpersona（口調）がかからない生テキストになる。頻度は低い（カレンダー書き込み確認時のみ）ため実害は小さいと判断したが、意図した仕様変更として認識しておく必要がある。
3. **`routes/chat.py`の`/api/chat/stream`は死んだコードとして残っている**: 3章の通り、いずれ削除を検討すべき。
4. **`agent_chat_stream`のtool_event中継は`/api/orchestrator/chat/stream`にのみ効果があり、`/api/agent/chat/stream`自体の他の呼び出し元（もしあれば）にも同時に影響する**: `routes/agent.py::agent_chat_stream`はorchestrator専用ではなく`/api/agent/chat/stream`という汎用のエージェント間インターフェースの一部。他のエージェントがこのエンドポイントを直接叩いている場合、tool_eventが新たに追加されたことで、そのエージェント側で未知のイベント種別として無視されるか、パース側で問題が起きないか確認が必要（現状確認できた範囲では他の呼び出し元は見つからなかった）。
5. **`persist_thread`が今回のorchestrator切り替えにより`/chat`のトラフィックにも適用される**: Phase A1で`persist_thread=True`化した効果が、今回`/chat`経由の全会話にも及ぶ。`/chat`は元々`chat.py`直呼び経路でも`persist_messages=True`だったため永続化自体は既存動作だが、永続化を担う実装が`chat.py`の`replace_chat_messages`直接呼び出しから、`orchestrator/service.py`経由の同名関数呼び出しに変わった。両者は同じ`app_chat_data.replace_chat_messages`を最終的に呼ぶため実質的な差異はないと考えられるが、念のため記載する。

---

## テスト・検証章の充足状況（マージ可否の判断）

- 要件1（スレッド横断ログウィンドウの対象になること）: `/chat`がorchestrator経由になったことで**構造的に満たされる**（Phase A1のロジックがそのまま適用される）。Phase A1のデータ層検証は別レポートで実施済み。今回`/chat`固有の実モデルテストは未実施。
- 要件2（fact/self_model/trend記憶注入が効くこと）: **構造的に満たされる**（5章参照）。実モデル応答での確認は未実施。
- 要件3（既存UI動作が壊れないこと）: **設計上は対処したが実地未確認**。ツール呼び出し表示・確認ボタンフローは0章の問題を解消する実装を行ったが、`OPENAI_API_KEY`がなく実際のモデル応答での確認ができていない。
- 要件4（WearOSへの影響なし）: **契約不変のため影響なしと判断**（5章参照）。実機再確認は未実施。

**結論: マージ前の確認を求める。** 「テスト・検証」章がマージ可否の基準として求めている「実モデル応答での確認」ができておらず、特に要件3（確認ボタンフロー）は本番相当の環境での実地確認なしに安全と言い切れない。本番サーバー（`OPENAI_API_KEY`設定済み）で最低限、(a) 通常のチャット応答、(b) ツール呼び出しを伴う応答、(c) カレンダー書き込みの確認ボタンフロー、の3パターンを一度動作確認してからのマージを推奨する。

---

## Related Documents

- [phase_a1_report.md](phase_a1_report.md) — 本Phaseの前提となるセッション継続機能の実装報告（0章で言及した経路の誤りの発見元）
- [global_state_migration_audit.md](global_state_migration_audit.md) — 発端となった監査レポート
