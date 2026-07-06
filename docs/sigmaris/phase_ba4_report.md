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

## 10. 2026-07-06 追補: B3確認質問の自動表示をデフォルト停止

本番反映後の会話で、文脈と無関係に「自宅のUbuntu Server / GTX 1660 6GB構成で合っているか」という確認質問が複数回表示された。調査したところ、Memory SnapshotやBA4の統合生成が直接同じ記憶を誤取得しているのではなく、BA1でHot Pathから退避したB3の `active_inquiry` が、前ターンで生成した確認質問を次ターン末尾へ自動注入していたことが原因だった。

発生条件:

- `active_inquiry.generate_and_stash_inquiry_question()` が `confirm:devices:has_self_hosted_server_and_gpu` の確認質問をバックグラウンド生成する
- 次ターンで `take_pending_inquiry_question()` がその質問を応答末尾へ追加する
- デプロイ・再起動でプロセスローカルの `_asked_cache` が消え、同じ確認質問のクールダウンが失われる
- BA4後はpersona rewriteで自然に混ぜ直されず、schedule-agent生成後にそのまま追加されるため唐突さが目立つ

対応:

- `settings.sigmaris_surface_inquiry_questions` を追加し、デフォルトを `False` にした
- デフォルト状態では、pending inquiryの取得・次ターン用の確認質問生成タスクをどちらも実行しない
- 通常の記憶検索、Memory Snapshot、事実抽出、認知レイヤー、BA4統合生成は維持する
- 将来、文脈適合性判定や永続的な質問クールダウンを追加できた段階で、`SIGMARIS_SURFACE_INQUIRY_QUESTIONS=true` により再有効化できる

判断根拠:

- 問題は「記憶層が情報を持っていること」ではなく、「未確認記憶の確認質問を会話の空気に関係なく自動表示すること」だった
- 本番安定化の優先度が高く、BA4の速度改善と一段生成の効果を維持したまま、最小範囲で唐突な質問注入だけを止めるのが低リスク
- B3の抽出ロジック本体は削除せず、明示設定で戻せる形に留めた

検証:

- `python -m unittest discover backend/tests`: PASS (`Ran 16 tests`)
- pending inquiryが存在しても、デフォルト設定では応答末尾に追加されないことを `test_pending_inquiry_is_not_surfaced_by_default` で確認

## 11. 2026-07-06 追補: フロントエンドstream表示の揺れへの対応

本番再起動後、ターンが増えるほどstreaming中のassistant表示が何度も表示・消失するように見える問題が報告された。調査対象はBA1〜BA4のバックエンド変更に加え、Next.js側のAI SDK / assistant-ui接続層まで広げた。

原因候補と判断:

- BA4で `run_orchestrator_chat_stream()` がschedule-agentのdeltaを即時中継するようになり、従来より細かい頻度でフロントエンドが再描画されるようになった
- `frontend/src/app/assistant.tsx` で `sendAutomaticallyWhen: lastAssistantMessageIsCompleteWithToolCalls` が残っており、バックエンドで完結済みのtool eventを受け取った後に、AI SDKが「tool結果が揃ったので続きを送る」と判断して追加リクエストを発火し得る状態だった。Sigmarisのtool loopはバックエンド側で完結するため、この自動再送は不要
- `/api/chat` のstream translatorが毎回ランダムな `messageId` を発行していた。AI SDKは `start.messageId` を受け取ると生成中assistant messageのIDを書き換えるため、完了後のDB履歴refreshと一時stream messageの対応が不安定になりやすい
- `AssistantChatTransport` がrenderごとに生成されていたため、stream中の細かい再描画と組み合わさると状態追跡の見通しが悪かった

対応:

- `sendAutomaticallyWhen` を削除し、tool完了後の不要な自動再送を停止
- `AssistantChatTransport` を `useMemo` でthread単位に固定
- `useChat({ experimental_throttle: 50 })` を設定し、細かすぎるdelta再描画を抑制
- AI SDKがPOST bodyに含める `messageId` を `/api/chat` routeで受け取り、`translateOrchestratorStream()` の `start.messageId` にそのまま使うよう変更

検証:

- `npx eslint src/app/assistant.tsx src/app/api/chat/route.ts src/lib/orchestrator/stream-translator.ts`: PASS
- `npm run lint`: PASS

## 12. 2026-07-06 追補: Markdown smooth streaming補間を停止

前項の対応後も、streaming中のassistant本文が「最初から表示され、消えて、また最初から表示され始める」ように見える問題が残った。追加調査で `@assistant-ui/react-markdown` の `MarkdownTextPrimitive` がデフォルトで `smooth=true` になっていることを確認した。

`smooth=true` の場合、assistant-ui内部の `useSmooth()` はstreaming中messageを空文字から補間表示する。BA4でschedule-agentのdeltaを即時中継するようになり、更新頻度が大きく上がったため、この補間が頻繁にリセットされ、ユーザーからは「高速で何度も出直している」ように見える状態になっていた可能性が高い。

対応:

- `frontend/src/components/markdown-text.tsx` の `MarkdownTextPrimitive` に `smooth={false}` を明示
- AI SDK / backend streamのdeltaをそのまま表示し、assistant-ui側の追加typewriter補間を使わない

検証:

- `npx eslint src/components/markdown-text.tsx src/app/assistant.tsx src/app/api/chat/route.ts src/lib/orchestrator/stream-translator.ts`: PASS

## 13. 2026-07-06 追補: チャットUI上の体感応答時間表示

BA1〜BA4の速度改善後、ユーザー体感での応答時間を会話しながら確認できるよう、フロントエンドのチャット本文付近に応答時間を表示する機能を追加した。

計測範囲:

- 開始: フロントエンド上で送信後、threadが `isRunning=true` になった時点
- 終了: stream完了後、threadが `isRunning=false` に戻った時点
- 表示: streaming中は `計測中 x.x秒`、完了後は `応答時間 x.x秒`

この値はブラウザ上の体感時間であり、backend auditの `duration_ms` とは測定開始点が異なる。サーバー内部の詳細分析には既存の `agent_invocation_audit_logs.duration_ms` / `response_summary` を使い、ユーザー体験の確認にはこのUI表示を使う。

検証:

- `npm run lint`: PASS

## 14. 2026-07-06 追補: 体感応答時間表示によるstream描画の途切れを修正

前項の初期実装では、streaming中の `計測中 x.x秒` 表示を `Thread` 直下のContext値として100msごとに更新していた。そのため、秒数更新がチャット本文全体へ波及し、BA4後の細かいdelta streamingと競合して、本文が一文字ずつではなく途切れ途切れに表示される副作用が出た。

対応:

- 100ms更新を `ResponseTimingBadge` / `LiveResponseTimingBadge` の小さな表示コンポーネント内に隔離
- `Thread` 全体のContext更新は開始時・終了時のみになるよう変更
- assistant本文、Markdown、assistant-ui message streamの描画経路をタイマー更新から切り離した

検証:

- `npx eslint src/components/thread.tsx`: PASS
- `npm run lint`: PASS
- `npm run build`: PASS

## 15. 2026-07-06 追補: チャットUI上の秒数表示を撤去

前項の隔離対応後も、チャット本文のstreaming表示が十分に改善しなかったため、チャット本文付近に表示していた `計測中 x.x秒` / `応答時間 x.x秒` のUIを撤去した。

判断:

- ユーザー体感の秒数表示より、本文streamの滑らかさと会話体験を優先する
- フロントエンド上でのライブ秒数更新は、assistant-ui / Markdown / stream描画との相互作用が大きく、現時点では副作用が読みにくい
- 応答時間の確認は、当面は既存のbackend audit (`agent_invocation_audit_logs.duration_ms`) とサーバーログで行う

対応:

- `frontend/src/components/thread.tsx` を秒数表示追加前の状態へ戻した
- BA4のstream安定化、Markdown smooth停止、tool自動再送停止などの修正は維持
