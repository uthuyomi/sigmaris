# Phase BA4 実装報告: 応答生成の統合

## 1. 採用した統合方式

`orchestrator/service.py` から `rewrite_with_persona()` / `rewrite_with_persona_stream()` の呼び出しを外し、schedule-agent (`chat.py::stream_chat_completion_ui()`) の1回目の生成をそのまま最終応答として採用する方式に変更した。

ただし、単に rewrite を外すだけだと従来の schedule-agent 用 prompt が「plain に返し、後段で人格化される」前提のまま残るため、`schedule_agent_client.py` の `system_override` を BA4 用に変更した。

- `persona.md` の内容を `persona_context` として schedule-agent に渡す
- 「後段の人格変換は存在しないので、最初から Sigmaris としてユーザー向け最終文を生成する」と明示する
- tool 出力由来の日時・数値・URL・成功/失敗状態を保持することを明示する
- `<!-- shiftpilot-confirmation ... -->` マーカーを生成する場合は JSON を含めて壊さないことを明示する

この方式を選んだ理由は、既存の tool call ループ、確認ボタン生成、AI SDK tool event 生成は `chat.py` 側に集約されており、そこを変更しない方が Phase A1-b の安全機構を保ちやすいためである。

## 2. 事実確認機構

採用方式は (b) 「生成そのものに事実確認の指示を組み込む」+ 軽量な機械的 post-check。

実装内容:

- `schedule_agent_client.py` の system override に、tool 出力と日時・数値・成功状態を一致させる指示を追加
- `response_guard.py` に `compare_response_to_tool_outputs()` を追加
- streaming 経路では中継された `tool-output-available` / `tool-output-error` を蓄積し、最終応答中の ISO 日付、時刻、日付+時刻、単位付き数値が tool 出力側に存在するかを確認
- 禁止 assistant 名の置換 (`replace_forbidden_assistant_names()`) は引き続き最終応答へ適用

判断根拠:

- 旧 `compare_semantic_entities()` は別 LLM 呼び出しであり、BA4 の目的である「2段階目の完全な LLM 生成を消す」効果を弱める
- BA4 で消える主なリスクは「一度正しく生成された実務応答を別 LLM が書き換える過程で事実が変わる」ことであり、rewrite を廃止することでそのリスク自体が大きく減る
- ただし tool 結果と最終文のズレは残り得るため、日時・数値など高シグナルな値だけを高速に検出する軽量 guard を追加した

制限:

- 固有名詞の意味的な同一性判定は LLM guard なしでは完全ではない
- 非 streaming の `/api/orchestrator/chat` は現状 tool event を受け取らないため、post-check は主に streaming 経路で有効
- 実モデルで persona の自然さと事実一致を確認する作業は、本番 API キーのある環境での実測に委ねる

## 3. Phase A1-b 安全機構との整合性

確認結果:

- tool event 中継: `call_schedule_agent_stream()` の `tool_event` を `run_orchestrator_chat_stream()` が従来通り `OrchestratorStreamEvent.tool_event` として relay する。今回の変更ではこの流れを維持した
- 確認ボタン: rewrite が全ケースで廃止されたため、`<!-- shiftpilot-confirmation ... -->` マーカーは LLM 書き換え工程を通らない。A1-b の「marker 付き応答だけ rewrite skip」よりさらに単純な保護になった
- 禁止名置換: `replace_forbidden_assistant_names()` は unified response の finalize 時に必ず適用する
- tool loop: `chat.py` の最大8回 tool call ループ、確認必須 tool の confirmation flow は変更していない

## 4. テスト結果

実行したテスト:

```bash
$env:PYTHONPATH='backend'; python -m unittest discover backend/tests
```

結果:

```text
Ran 14 tests in 0.046s
OK
```

追加・更新した主なテスト:

- 雑談相当: `test_unified_generation_passes_persona_context_without_rewrite`
  - schedule-agent に `persona_context` が渡ること
  - 旧禁止名が最終応答に残らないこと
- tool 呼び出し相当: `test_stream_relays_tool_event_and_preserves_confirmation_marker`
  - `tool_event` がそのまま relay されること
- 確認ボタン相当: 同テストで `shiftpilot-confirmation` マーカーが最終 delta に残ること
- 事実歪み検知: `test_tool_output_guard_rejects_ungrounded_time`
  - tool 出力が `10:00` のとき、応答が `15:00` と言った場合に guard violation になること

補足:

- `pytest` はローカル環境に未導入だったため、標準 `unittest` で検証した
- 実 OpenAI API / 実 Google Calendar API による end-to-end 検証は未実施

## 5. 応答時間の変化

モック単体テストでは、旧 persona rewrite LLM 呼び出しと semantic guard LLM 呼び出しが完全に消えたことを確認した。

期待される実運用上の変化:

- 旧: schedule-agent 生成 約12秒 + persona rewrite / semantic guard 約10秒
- 新: schedule-agent 統合生成 1回 + 軽量正規表現 guard

軽量 guard は Python の文字列/正規表現処理のみであり、単体テスト全体 14件が 0.046秒で完了している。実モデルでの最終応答時間は本番サーバー上で改めて計測が必要。

## 6. 懸念点・Phase C-full 前に対応すべき事項

1. persona 品質は実モデルで確認が必要
   - 今回は `persona.md` を1回目の生成へ注入する配線を実装したが、実際に「共感→興味→質問→分析→結論」の流れが自然に出るかは本番 API 環境で確認する必要がある

2. streaming 経路はまだ「schedule-agent 完了後にまとめて final delta」
   - 事実 guard を text 表示前に実行するため、schedule-agent の text delta は内部で蓄積してから返している
   - これでも二段階目の LLM 約10秒は削れるが、真の first-token latency 改善は追加設計の余地がある

3. 固有名詞 guard は旧 LLM semantic guard より弱い
   - BA4 の速度目的を優先し、固有名詞の意味的比較は外した
   - Phase C-full の response_error_rate 評価で問題が出る場合、tool 出力内の title/location/name などの key に限定した deterministic guard を追加するのが次候補

4. 非 streaming endpoint の tool-output guard
   - `/api/agent/chat/complete` は tool event を返さないため、非 streaming では prompt 指示と禁止名置換のみになる
   - WearOS など非 streaming 利用が重要になった場合、complete 応答にも tool event summary を返す拡張を検討する

## 7. 2026-07-06 追補: system_override 4000文字上限への対応

サーバー反映後、`/api/agent/chat/stream` が `system_override` の `max_length=4000` により HTTP 422 を返すことが判明した。BA4初版では `persona.md` 全文を `persona_context` として渡していたが、`persona.md` 単体で約4598文字あり、既存の記憶 context と合わせると必ず上限を超える。

対応:

- `persona.md` 全文の注入をやめ、BA4統合生成に必要な短い persona 方針へ置換
- `schedule_agent_client.py::_build_system_override()` に最終的な 4000文字 cap を追加
- 固定の BA4 safety 指示 (`You are Sigmaris...`) は切り捨てず、動的 context 側のみを `[context truncated]` 付きで短縮
- `test_schedule_agent_client.py` を追加し、長い context でも 4000文字以内になることを検証

この修正により、同種の 422 は `system_override` 組み立て段階で防止される。

## 8. 2026-07-06 追補: streaming無音時間への対応

BA4初版では、事実 guard をユーザー表示前に実行するため、`run_orchestrator_chat_stream()` が schedule-agent の `delta` を内部で最後まで蓄積し、完了後に一括送信していた。

サーバー反映後、短い応答では成功する一方、後続ターンでフロントエンドに assistant 枠だけが出て本文が出ない現象が確認された。原因として、生成中に orchestrator から text delta が出ない無音時間が発生し、フロント/プロキシ/クライアント側の stream 処理が実質的に待ち切れない可能性が高いと判断した。

対応:

- streaming 経路では schedule-agent の `delta` を受け取った時点で即座に `OrchestratorStreamEvent(delta=...)` として中継する形に戻した
- `replace_forbidden_assistant_names()` は各 delta に適用し、最終保存用の全文にも改めて適用する
- tool-output fact guard は、表示前 gate ではなく、stream 完了後の軽量検知・ログ記録として実行する
- 確認ボタンマーカーは引き続き LLM rewrite を通らず、schedule-agent 生成物をそのまま中継する

この修正で、BA4の一段生成化を維持しながら、streaming UX と接続安定性を優先した。

## 9. 2026-07-06 追補: /api/orchestrator/chat/stream 422への対応

サーバーログで `/api/orchestrator/chat/stream` 自体が HTTP 422 を返していることを確認した。これは内部 schedule-agent ではなく、外側 orchestrator endpoint の Pydantic request validation で落ちている状態である。

原因候補として、Next.js の `/api/chat` route が AI SDK の `UIMessage[]` 全履歴をそのまま backend に送っており、`OrchestratorChatRequest.messages` の `max_length=50` を超えうることが分かった。backend の `_prepare_session_messages()` はDBから直近会話ウィンドウを取得し、リクエスト側からは最新 user turn があれば足りる設計なので、全履歴送信は不要だった。

対応:

- `frontend/src/app/api/chat/route.ts` で backend に送る履歴を直近24件に制限
- 各 message content を backend schema 上限の 20,000 文字以内に制限
- backend 側の recent-window / 最新 user turn 統合設計は維持

検証:

- `python -m unittest discover backend/tests`: PASS
- `npx eslint src/app/api/chat/route.ts`: PASS
