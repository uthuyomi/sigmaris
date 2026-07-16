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

## 16. 2026-07-12 追補: フロントエンド切断時の応答継続

### 16.1 背景

海星さんから、「フロントエンドアプリを途中で閉じると、応答が途切れ、その後の会話で文脈が保持されなくなる」という不具合が報告された。実装前に、依頼書が指定した2点の調査を行った。

### 16.2 原因調査の結果

#### 調査1: 応答生成が、フロントエンドとの接続に依存しているか → **依存していた(直接的な原因)**

ストリーミング経路(`/chat`の実際の利用経路)を末端まで追跡したところ、**2段階にネストしたHTTPストリーミング呼び出し**になっていることを確認した。

1. フロントエンド ⇄ `orchestrator.py`の`/api/orchestrator/chat/stream`(`StreamingResponse`、内部で`run_orchestrator_chat_stream()`を`async for`で直接消費)
2. `run_orchestrator_chat_stream()`(`orchestrator/service.py`) ⇄ `agent.py`の`/api/agent/chat/stream`への**実際のHTTPリクエスト**(`schedule_agent_client.py`が`httpx.AsyncClient.stream()`で発行、`async for line in response.aiter_lines()`で消費)
3. `agent.py`の`/chat/stream` ⇄ `chat.py::stream_chat_completion_ui()`が、OpenAIの`client.responses.create(..., stream=True)`を`async for event in stream`で直接消費し、生成の最後に`_persist_chat_messages_safely()`で`chat_messages`へ保存

`orchestrator.py`の`_generate()`(1)は、Starlette/uvicornが標準で提供する「クライアント切断検知」の対象になる`StreamingResponse`の`async`ジェネレータそのものである。**フロントエンドが切断すると、Starletteはこのジェネレータをキャンセル(`GeneratorExit`)するが、このキャンセルは`async for`の連鎖をそのまま遡り、(2)のhttpxストリーミング呼び出し、さらにその内側で実行されている(3)のOpenAIストリーミング呼び出しそのものまで、生成が完了する前に打ち切ってしまう。** これは`run_orchestrator_chat_stream()`の`except Exception`ブロックでも捕捉できない——切断によるキャンセルは`asyncio.CancelledError`(`BaseException`のサブクラスであり`Exception`ではない)として伝播するため、既存の例外処理をすり抜ける。

#### 調査2: 生成完了前に接続が切れた場合、保存・後続処理はどうなるか → **一切実行されなかった**

`run_orchestrator_chat_stream()`のコードを確認したところ、以下は全て「`async for event in call_schedule_agent_stream(...)`ループが最後まで完了した後」にしか到達しないコードだった。

- `finish_invocation(status="completed", ...)`(監査ログの完了記録)
- `chat_messages`への保存(`chat.py::_persist_chat_messages_safely()`。上記の通り、これはさらに内側、(3)の生成ループ完了後にしか実行されない)
- 記憶抽出のfire-and-forgetスケジューリング(`asyncio.create_task(_extract_facts_bg(...))`)
- 意思決定検出のfire-and-forgetスケジューリング(`asyncio.create_task(_cognitive_layer_bg(...))`)
- Temporal Layer Step2の`_mark_events_mentioned_bg`スケジューリング

**すなわち、生成の途中で接続が切れた場合、これらは`asyncio.create_task(...)`の呼び出しにすら到達しない**(コード自体が実行されない、fire-and-forgetの「発火」自体が起きない)。B群の記憶抽出・decision_log検出が動かないだけでなく、そもそも`chat_messages`にその会話ターンが一切保存されないため、次回接続時に文脈が失われる、という報告内容と一致する原因を特定した。

### 16.3 選択した修正方針とその根拠

依頼書が提示した方針のうち、「応答生成処理を、フロントエンドへのストリーミング配信とは独立したタスクとして実行する」を採用した。

**実装(`orchestrator/service.py`に`run_orchestrator_chat_stream_detached()`を新規追加)**:

```python
async def run_orchestrator_chat_stream_detached(...):
    queue: asyncio.Queue = asyncio.Queue()

    async def _produce() -> None:
        try:
            async for event in run_orchestrator_chat_stream(...):
                await queue.put(event)
        except Exception as error:
            await queue.put(error)
        finally:
            await queue.put(None)

    asyncio.create_task(_produce(), name="orchestrator_stream_detached")

    while True:
        item = await queue.get()
        if item is None:
            return
        if isinstance(item, Exception):
            raise item
        yield item
```

`orchestrator.py`のルートは、従来の`run_orchestrator_chat_stream()`ではなく、この`run_orchestrator_chat_stream_detached()`を`async for`で消費するよう変更した。

**判断根拠(なぜ`asyncio.shield()`ではなくbackground task + queueなのか)**: 依頼書は`asyncio.shield()`も選択肢として挙げていたが、`shield()`は「1つのawait対象(Future/Task)」をキャンセルから守る仕組みであり、**`async for`で連続的に消費され続ける非同期ジェネレータの"消費され続けること自体"を守ることはできない。** 今回の問題は「誰もジェネレータの次の要素を取りに来なくなった(消費が止まった)」ことがキャンセル伝播の引き金であり、`shield()`を`__anext__()`呼び出し1つ1つに個別適用しても、消費側がそもそも呼び出しを止めてしまえば生成は進まなくなる。**bareな`asyncio.create_task()`で生成処理全体を独立したタスクとして起動する**方式であれば、そのタスクは呼び出し元コルーチンの`await`連鎖の外側に存在するため、呼び出し元がキャンセルされてもタスク自体はキャンセルされない——これは本コードベースが既存の`_extract_facts_bg`/`_cognitive_layer_bg`等のfire-and-forgetパターンで既に採用している手法と全く同じ仕組みであり、実績のある手法を踏襲した。

**判断根拠(ストリーミング経路のみを対象とし、非ストリーミング経路は対象外とした理由)**: 非ストリーミングの`run_orchestrator_chat()`(`/api/orchestrator/chat`)は、`async`ジェネレータとして`StreamingResponse`に直接ドライブされているわけではなく、単一の`await`されるコルーチンである。Starletteの「クライアント切断検知→ジェネレータキャンセル」という仕組みは`StreamingResponse`のチャンク送信を監視する専用のものであり、通常のPOSTハンドラには同じ形では適用されない。依頼書の背景説明も「ストリーミングでトークンを逐次返す方式」を明示的に問題としており、調査結果とも一致するため、非ストリーミング経路は今回のスコープ外と判断した。

### 16.4 テスト結果

`test_disconnect_response_continuity.py`として4件のテストを作成した。

- **通常系(切断なし)**: `run_orchestrator_chat_stream_detached()`が、モックした`run_orchestrator_chat_stream()`の全イベントを順序通り中継すること。
- **エラー伝播**: 生成中に例外が起きた場合、その例外が消費側にも正しく伝播すること(既存の`except Exception`によるエラーハンドリング・監査ログ記録が壊れていないことの確認)。
- **切断シミュレーション(要件1・2・3の直接検証)**: モックした生成関数を、最初のイベントを返した後に`asyncio.sleep(0.05)`で「まだ生成中」を模し、その後「保存+fire-and-forgetスケジューリングに相当する処理」を実行してから完了イベントを返すよう設計。消費側は最初のイベントを受け取った直後に**明示的に`gen.aclose()`を呼び、以降一切読み取らない**(=フロントエンド切断の模倣)。それでもなお、`await asyncio.sleep(0.2)`後には「保存+fire-and-forgetスケジューリングに相当する処理」が実行済みであることを確認した——**切断後も、生成・保存・fire-and-forget相当の処理が最後まで完了することを直接証明するテスト。**
- **キャンセル伝播の否定(仕組みそのものの検証)**: 消費側を丸ごと別の`asyncio.Task`として起動し、最初のイベントを受け取った直後に**そのタスク自体を`.cancel()`**(Starletteが切断時に行う操作により近いシミュレーション)。それでも、背後の生成処理が`asyncio.sleep(0.1)`後に到達するはずのマーカーへ正しく到達することを確認した。

```
4 passed
```

既存の`backend/tests/`(16件)、および直近のTemporal Layer・タイムスタンプ修正・`/timeline`関連のスクラッチテスト(計55件)も全て再実行し、リグレッションは確認されなかった。

```
16 passed
55 passed
```

**テスト中に確認した、本タスクと無関係な既存の問題**: `test_phase_ba1_stream_integration.py`(過去タスクのスクラッチテスト)が、`rewrite_with_persona_stream`というBA4で既に削除済みのシンボルを参照してモックに失敗する状態だった。これは本タスクの変更以前から存在していた既知の劣化(前回のセッションで`test_phase_ba1_service_integration.py`に同種の問題を確認済み)であり、本タスクの変更が原因ではない。スクラッチファイルであり`backend/tests/`の対象外のため、本タスクでは修正していない。

**実モデルAPI・実際のブラウザ切断による検証は行っていない。** テストは`asyncio`レベルでの切断・キャンセルの模倣にとどまる(依頼書の注意事項通り、追加のサーバーアクセス・APIキー取得は試みていない)。

### 16.5 気づいた懸念点

1. **Phase A4の排他制御(`chat_threads.version`によるCAS)との整合性について**: 今回の修正は「生成処理を切断から切り離す」ことが目的であり、`_persist_chat_messages_safely()`自体(`expected_version`を使った楽観的排他制御)には一切手を加えていない。したがって、切断後もバックグラウンドで生成が完了し、通常通りその時点の`expected_version`で保存を試みる——**この保存タイミングが「切断前より遅くなる」ことはない**(むしろ従来は切断で保存自体が消えていたのに対し、今回の修正で確実に保存が試みられるようになった、という変化)。ただし、ユーザーが切断後にすぐ別のデバイス・別タブから同じスレッドへ新しいメッセージを送った場合、「切断前に送った(バックグラウンドで生成が進行中の)ターン」と「新しく送った別のターン」が、ほぼ同時に同じスレッドへの書き込みを試みる可能性がある。既存のバージョンチェック(`ThreadVersionConflictError`)がこのケースを検知すること自体は変わらないが、「バックグラウンドで生成中の古いターンが、新しいターンの後に完了して保存を試み、バージョン競合でエラーになる」という新しいタイミングのケースが増える可能性がある。これは切断前から理論上存在した競合パターンではあるが、今回の修正で「切断後も生成が続く」ようになった分、発生頻度が上がる可能性がある——実運用での監視を推奨する。
2. **B群の記憶抽出(`memory_extractor.py`)・decision_log検出との整合性について**: これらは元々fire-and-forgetの`asyncio.create_task()`で起動されており、今回の修正によって「起動されること自体」が保証されるようになった(調査2参照)、という変化のみで、これらの処理自体のロジックには一切変更を加えていない。
3. **バックグラウンドタスクの監視性**: `_produce()`は`asyncio.create_task()`で起動後、明示的な参照を保持していない(このコードベースの既存fire-and-forgetパターンと同じ設計)。プロセスがクラッシュ・再起動した場合、進行中だった生成はそこで失われる——これは今回の修正の対象外(プロセスの生存を跨いだ永続化は、依頼書のスコープである「フロントエンド切断からの独立」とは別の課題)であり、今後もし必要になれば別タスクとして検討する価値がある。
4. **切断後にユーザーが応答を見られない体験そのものについて**: 今回の修正は「バックエンド側で生成・保存・記憶抽出が失われない」ことを保証するものであり、「切断中にフロントエンド側へ結果をリアルタイムで届ける」ことまでは保証しない(切断している間は当然、SSEでの配信先がない)。次回接続時に`chat_messages`から正しく履歴が読み込まれることで、海星さんが後から会話を再開したときに文脈が保持される、という形で要件4を満たしている。

## 17. 2026-07-12 追補: 再接続後の文脈捏造、およびメッセージ表示順序の乱れ

### 17.1 背景

前項(16章)の修正後もなお、(1)再接続後に「さっきの続きだけど」と話しかけると無関係な内容をあたかも直近の出来事のように語り出す、(2)チャット画面を開き直すとメッセージの表示順序が実際の時系列と一致していない、という2つの現象が報告された。応答内容自体は正確だったため、単純な記憶欠落ではなく保存・順序の問題であると推測されており、実装前に4点の調査を行った。

### 17.2 原因調査の結果

#### 調査1・2: スレッド再利用の実態、および書き込み・表示順序の実態 → **両現象は同一の根本原因から生じていた**

`chat.py`の永続化経路をたどったところ、以下の構造的な問題を発見した。

1. Phase A1(セッション継続)により、`orchestrator/service.py`は`get_recent_messages_across_threads()`で構築した**クロススレッドの直近ログウィンドウ**(最大40件、複数のスレッドにまたがりうる)を、`session_messages`として`call_schedule_agent[_stream]()`経由で`chat.py`へ渡す。これはLLMへの文脈として渡すために意図的に設計されたものであり(Phase A1報告書参照)、それ自体は問題ではない。
2. しかし`chat.py`の`run_chat_completion()`/`stream_chat_completion_ui()`は、**この同じ`messages`引数(クロススレッドウィンドウ)をそのまま`messages_to_store = [*messages, assistant_message]`として`chat_messages`への保存に使い回していた。** `replace_chat_messages()`は指定された`thread_id`の`chat_messages`を全削除してから全INSERTする方式(既存設計、A4以前から不変)のため、**毎ターン、現在のスレッドの全履歴が、複数スレッドにまたがるクロススレッドウィンドウの内容で丸ごと上書きされていた。** これが現象1の直接的な原因である——ある会話で参照された別スレッドの内容が、たまたまウィンドウに乗った結果、現在のスレッドの「保存済み履歴」として書き込まれてしまい、後日そのスレッドを再開して「さっきの続き」と話しかけると、LLM自身がこの(正しく渡された)文脈をそのまま誠実に使って応答してしまう——ハルシネーションというより、**バックエンドのデータ整合性バグによって汚染された文脈を、LLMが忠実に使った結果**だった。
3. `_message_insert_payload()`(INSERTペイロード構築)は`created_at`を明示的に設定しておらず、DBのカラムデフォルト(`timezone('utc', now())`)に委ねていた。1回のバルクINSERT文の中では、Postgresの`now()`はトランザクション時刻として**全行が同一の値**になる。つまり、**「保存し直されるだけの、内容が変わっていない過去のメッセージ」も含め、スレッドの全メッセージが、保存のたびに`created_at`が「今」に上書きされていた。** これが現象2の直接的な原因である——`created_at`でソートする経路(`get_recent_messages_across_threads()`等)は、保存を重ねるたびに全メッセージのタイムスタンプが同一の値に収束していくため、本来の時系列が失われ、同着のタイブレーク順(不定)に頼るしかなくなる。
4. さらに、直前のタスク(16章)で導入した`_format_message_timestamp_prefix()`(`chat_messages`の`created_at`をLLMへの相対時間表現の根拠として使う仕組み)は、この`created_at`崩壊の影響を直接受ける——**保存を重ねるほど、古いメッセージも「たった今」に近いタイムスタンプを持つようになり、直前のタスクの修正がむしろLLMに「これは最近の話だ」という誤った確信を強める方向に作用しうる状態だった。** 2つのタスクの修正が意図せず組み合わさり、問題を悪化させる可能性があったことを明記する。

`get_earliest_message_at()`(Temporal Layer Step3の「関係の起点日」推定に使用)も同じ`created_at`崩壊の影響を受けていたと考えられる——保存を重ねるほど「最初の会話の日時」が実際より新しい方へドリフトしていた可能性があり、本修正で副次的に解消される。

#### 調査3: Phase A4(排他制御)との相互作用 → **競合時に書き込みが無条件で失われる設計だった**

`_persist_chat_messages_safely()`は、`ThreadVersionConflictError`(楽観ロックの競合)を検知すると、**警告ログを出すだけで、そのターンの内容を二度と保存しようとせず破棄していた**(リトライなし)。前タスク(16章)で導入したバックグラウンド生成の分離により、生成が切断後も継続して完了できるようになった結果、「バックグラウンドで完了した古いターン」と「再接続後に送られた新しいターン」がほぼ同時に同じスレッドへ書き込みを試みる可能性が実質的に増えており、この「競合時に無条件で消える」設計は、まさに16章の懸念点1で予告した通りのリスクだった。

#### 調査4: 文脈が不足・混乱している場合のLLMの振る舞い → **honesty(不足の申告)を促す仕組みは存在しなかった**

B11(`memory_confidence.py`)は、B1記憶検索(`user_fact_items`由来の事実)の確信度較正のみを対象としており、`chat_messages`由来の会話履歴の一貫性・完全性は一切扱っていない。persona.mdにも、会話履歴が不完全・不連続に見える場合に正直に申告すべき、という指示は存在しなかった。**LLMは渡された文脈をそのまま真実として扱う以外の選択肢を与えられていなかった**——今回の場合、根本原因(データ汚染)を修正すればLLMに渡る文脈自体が正しくなるため、この観点の欠如が現象の"直接"原因ではないが、依頼書の要件4に沿って防御的な指示を追加した(17.3節)。

### 17.3 選択した修正方針とその根拠

#### (a) 永続化の対象を「クロススレッドウィンドウ」から「このスレッド自身の履歴」へ分離

`orchestrator/service.py`の`messages`引数(呼び出し元が今回新たに送ってきた、genuinely新しい内容)から、そのターンの新規ユーザー発言だけを取り出し、`new_user_message`という新しい明示的なパラメータとして`schedule_agent_client.py`→`agent.py`→`chat.py`まで一貫して受け渡すようにした。

`chat.py::_persist_chat_messages_safely()`は、`new_user_message`が渡された場合、**保存直前に`list_chat_messages(thread_id=...)`でこのスレッド自身の現在の履歴を新鮮に再取得し**、そこに新規ユーザー発言と新規アシスタント応答だけを追記した配列を保存するよう変更した。クロススレッドウィンドウ(`fallback_messages`という名前に変更)は、LLMへの文脈としては引き続き使われる(Phase A1の意図した機能は無傷)が、**保存には一切使わない。**

**判断根拠**: 依頼書は「全削除→全INSERT方式自体の見直しも含めて検討してよい」としていたが、真の根本原因は削除→再INSERT方式そのものではなく、「何を保存するか」の取り違えだったため、方式自体の刷新(差分追記型への全面移行等)は行わなかった。既存の削除→再INSERT方式を維持しつつ、**「保存する配列を正しく組み立てる」ことに絞って修正**する方が、変更範囲が明確で判断根拠を示しやすく、依頼書の「中途半端な対処に留めず、根本原因の特定を最優先する」という要求にも、根本原因(取り違え)を直接修正するという形で応えられると判断した。

#### (b) `created_at`の保持

`_message_insert_payload()`を変更し、渡されたメッセージ辞書に`created_at`が含まれる場合はそれを保存し、含まれない場合(=本当に新規のメッセージ)のみDBのデフォルト(今の時刻)に委ねるようにした。`list_chat_messages()`の`SELECT`に`created_at`を追加し、(a)で導入した再取得の際にこの値が流れるようにした。

#### (c) 保存直前の再取得によるレースコンディションの自己修復、およびバージョン競合時のリトライ

`list_chat_messages()`による再取得を、生成開始時点ではなく**保存の直前**に行うことで、生成に時間がかかった場合でも常に最新のDB状態を土台にできるようにした。加えて、`ThreadVersionConflictError`発生時、`new_user_message`が利用可能な場合に限り、**現在のバージョンとスレッド内容を再取得した上で1回だけ書き込みをリトライする**設計にした(フロントエンドの未使用コード`replaceChatMessages()`が既に採用していた「現在のバージョンに対して1回だけリトライする」という方針を踏襲)。`new_user_message`がない呼び出し元(既存のフォールバック経路)は、従来通りログのみで諦める挙動を維持した——このケースでは「何が新規で何が単なるウィンドウの写しか」を区別する情報がなく、安全にリトライを組み立てられないため。

#### (d) persona.mdへの防御的指示の追加(要件4)

12章(直前タスクで追加済み)がタイムスタンプの扱いを規定しているのに対し、新規に14章「文脈が不完全な場合の振る舞い」を追加し、会話履歴が実際の流れと噛み合わない・話の続きが読み取れない場合は、もっともらしく話を繋げようとせず正直に確認する旨を明記した。**これは根本原因(a)(b)(c)が修正されればLLMに渡る文脈自体が正しくなるため、本質的な解決策ではなく、あくまで多層防御(defense in depth)として位置づけている。** 依頼書が要件4として明示的に要求していたため実装したが、報告書としては(a)(b)(c)を主たる修正として位置づける。

### 17.4 テスト結果

`test_context_fabrication_and_message_order.py`として12件のテストを作成した。

- **`created_at`保持**: 過去のメッセージが`created_at`付きで渡された場合はそのまま保存されること、新規メッセージ(`created_at`なし)はDBのデフォルトに委ねられること、両者が混在するバッチでも`message_order`は配列位置通りに割り振られること。
- **`list_chat_messages()`の`SELECT`に`created_at`が含まれること**。
- **`_to_storable_new_user_message()`**: `{role, content}`形式から保存用の`{role, parts}`形式への変換、`None`入力で`None`を返すこと。
- **永続化スコープの直接検証(現象1・2の再現テスト)**: 「このスレッド自身の履歴」と「無関係な別スレッドの内容を含むクロススレッドウィンドウ」を用意し、`_persist_chat_messages_safely()`実行後、保存される内容にこのスレッド自身の履歴・新規発言・新規応答は含まれるが、**別スレッドの内容は一切含まれないこと**を確認した。あわせて、保持されるべき過去メッセージの`created_at`が保存後も変わらないこと、新規メッセージには`created_at`が強制されていないことを確認した。
- **`new_user_message`未提供時の後方互換性**: 提供されない場合は`list_chat_messages()`を一切呼ばず、従来通り`fallback_messages`をそのまま使うこと。
- **バージョン競合時のリトライ(複数バックグラウンド生成の並行実行シナリオ、現象2の再現テスト)**: 1回目の書き込みが競合で失敗した後、**現在のバージョンとスレッド内容(=先に書き込んだ側の内容を含む)を再取得した上でリトライし**、最終的に保存される配列が正しい時系列順(先勝ちの内容→自分の新規発言→自分の新規応答)になることを確認した。リトライも競合した場合は例外を送出せず諦めること(既存の「応答自体は止めない」方針の維持)、`new_user_message`がない場合はリトライ自体を試みないこと(バージョン取得・再取得が一切呼ばれないことを含め)、それぞれ確認した。
- **オーケストレーターの配線確認**: `run_orchestrator_chat()`が、`session_messages`(クロススレッドウィンドウ)ではなく、呼び出し元の`messages`引数から抽出した新規ユーザー発言を`new_user_message`として`call_schedule_agent()`に渡すこと。

```
12 passed
```

既存の`backend/tests/`(16件)、および直近の関連スクラッチテスト(Temporal Layer・タイムスタンプ・接続継続・`/timeline`関連、計59件)も全て再実行し、リグレッションは確認されなかった。

```
16 passed
59 passed
```

**実モデルAPI・実データベースでの検証は行っていない。** テストは`chat.py`・`orchestrator/service.py`の関数を直接呼び出し、DB層(`rest_select`/`rest_insert`/`rest_delete`相当)をモックする形にとどまる(依頼書の注意事項通り、追加のサーバーアクセス・APIキー取得は試みていない)。

### 17.5 気づいた懸念点・完全に解決しきれない場合の残存リスク

1. **削除→全INSERT方式そのものは維持しており、保存のたびにスレッド全体の`id`・`message_order`は再生成される。** `created_at`は保持するようにしたが、各行の`id`(UUID)は`_message_insert_payload()`が明示的に設定しておらず、保存のたびに新しい`id`が振られる——メッセージの「識別子としての安定性」までは今回のスコープでは解決していない。フロントエンドが特定のメッセージIDを跨ターンで参照する設計に将来なった場合は、再検討が必要。
2. **`list_chat_messages()`による再取得から`replace_chat_messages()`の書き込みまでの間には、依然として微小なTOCTOU(time-of-check-to-time-of-use)の余地が残る。** リトライを1回に限定しているため、3者以上が同時に同じスレッドへ書き込もうとした場合、2番目のリトライも競合し、その回の内容は破棄されうる(17.3節(c)で述べた通り、これは新規のリスクではなく既存の設計を踏襲した意図的な範囲限定)。単一テナント(海星さん一人)かつ通常はデバイス1台からの利用という前提では、3者以上の同時書き込みは考えにくいが、複数デバイスからの同時利用が今後増える場合は再検討の価値がある。
3. **persona.md 14章(文脈が不完全な場合の振る舞い)の実効性は、実モデルでの確認ができていない。** LLMが実際にこの指示に従って正直に確認するかどうかは、本番相当の環境での運用を通じてしか最終確認できない。
4. **`get_earliest_message_at()`(Temporal Layer Step3)への好影響は理論上のものであり、実データでの改善確認はしていない。** 既に`created_at`が崩壊した状態で保存されてしまった既存メッセージがあれば、今回の修正はそれらを遡って訂正しない(新規の保存からのみ正しい`created_at`保持が働く)。運用者側で、既存スレッドの`chat_messages.created_at`が不自然に同一時刻へ集中していないか確認することを推奨する。
5. **本タスクの2つの現象は、いずれも「LLMが誠実に、渡された(汚染された)文脈を使った結果」であり、狭義のハルシネーション(文脈にない内容を捏造すること)ではなかった。** 依頼書は「ハルシネーションに直結する深刻な問題」としていたが、調査の結果、根本原因はモデルの生成品質ではなくバックエンドのデータ整合性にあったと判断した。この判断自体が誤っている可能性(モデル側の挙動にも別途問題がある可能性)は完全には排除できないが、少なくとも今回発見した構造的なデータ汚染は、それだけで両現象を矛盾なく説明できる。

---

## 18. 2026-07-16 追補: メッセージ表示順序の崩れ(AI応答→ユーザー発言の逆転)調査・修正、+ UIへの日時表示追加

### 18.1 背景

17章の修正(created_atの保持・スレッドスコープの分離)を反映した後もなお、画面上のメッセージ表示順序が崩れる現象(本来「ユーザーメッセージ→AI応答」の順であるべきところが「AI応答→ユーザーメッセージ」の順に見える)が、スクリーンショットで複数回確認された。依頼書の指示通り、実装より先に4点の調査を行った。

### 18.2 原因調査の結果

#### 調査1・2: DB上のcreated_atの実態、および表示側のソートロジック → **どちらも「単独ターンの範囲では」正しく機能していた**

`chat_messages.created_at`は`timestamptz`(マイクロ秒精度)であり、17章の修正により、新規メッセージには保存直前に決まる値が、既存メッセージには保持された値が、それぞれ正しく入っていた。表示順序についても、`list_chat_messages()`は`created_at`ではなく既存の`message_order`(スレッドごとの連番、`replace_chat_messages()`の全削除→全INSERT時に配列の並びからそのまま採番される)でソートしており、フロントエンド(`chat-threads.ts::listChatMessages()`)は取得した配列をそのまま`UIMessage[]`として使うだけで、独自の再ソートは一切行っていない(`frontend/src`全体を`.sort(`で検索し、チャットメッセージの表示経路にソート処理が無いことを確認した)。**つまり、1回の`replace_chat_messages()`呼び出しが組み立てる配列の中の並びは、常に「既存履歴 → 今回のユーザー発言 → 今回のAI応答」という正しい順序になっており、この経路単体にはバグが無かった。**

#### 調査3(調査4に相当、時系列の実態): 複数ターンが並行して永続化される場合に問題が生じることを特定 → **これが直接的な原因**

16章(フロントエンド切断時の応答継続)で導入した「生成処理をバックグラウンドタスクとして独立実行する」設計により、**同一スレッドに対する複数ターンの生成が、実質的に並行して進行しうるようになった。** これは16.5節の懸念点1で明確に予告されていたリスクであり、今回その通りの症状として顕在化したと判断した。

`chat.py::_persist_chat_messages_safely()`(17章で導入)の`_build_messages_to_store()`は、保存の直前に`list_chat_messages()`で「このスレッドの現在の履歴」を再取得し、そこへ今回のユーザー発言・AI応答を**常に配列の末尾へ追記**していた。この設計は「後から実行された`replace_chat_messages()`呼び出しが常に真実」という前提に立っているが、**「後から実行された」ことと「後から送信された」ことは同じではない。** 具体的には、以下の順で症状が再現する。

1. 海星さんがメッセージA(ターンA)を送信する。生成が始まる(バックグラウンドタスクとして)。
2. ターンAの生成が(ツール呼び出し等で)長引いている間に、何らかの理由(フロントエンドの一時切断・再接続、複数タブ等)で、海星さんが同じスレッドへメッセージB(ターンB)を送信する。ターンBの生成も独立したバックグラウンドタスクとして並行して始まる。
3. ターンBの方が生成が速く完了し、先に`_persist_chat_messages_safely()`が実行される。この時点の`list_chat_messages()`は(ターンAがまだ保存されていないため)ターンB以前の履歴のみを返し、`[既存履歴, ユーザーB, 応答B]`が保存される。
4. 少し遅れてターンAの生成が完了し、`_persist_chat_messages_safely()`が実行される。この時点で`list_chat_messages()`を再取得すると、**手順3で先に保存されたターンBの内容が既に含まれている。** そこへターンAのペアを末尾に追記するため、最終的な保存内容は`[既存履歴, ユーザーB, 応答B, ユーザーA, 応答A]`となる。

**この結果、実際には先に送信されたターンAが、後から送信されたターンBより後ろに表示される。** ユーザーから見ると、「応答Bの直後に、文脈的につながりの薄いユーザーAの発言が現れ、その後にようやく応答Aが現れる」という、時系列的に破綻した並びになる——これが「AI応答→ユーザー発言の逆転」として報告された現象の実態であると判断した。`message_order`はこの配列の並びをそのまま採番するだけの機構であり、この種の並び順の誤りをそれ自体では検知・修正できない。

#### 調査4: タイムスタンプの精度 → **精度自体は問題ではなかった**

`chat_messages.created_at`は`timestamptz`(マイクロ秒精度)であり、依頼書が懸念していた「同一秒内の複数メッセージが区別できない」という問題は生じていなかった。既存の`message_order`列(スレッド内で一意な連番)も、精度とは独立に厳密な順序を保証する仕組みとして既に存在していた。**問題は精度ではなく、「どの時点の状態を基準に配列を組み立てるか」という設計そのものだった。**

### 18.3 選択した修正方針とその根拠

#### (a) 送信時刻を「生成が始まった瞬間」に捕捉し、それを根拠にターンを正しい位置へ挿入する

`orchestrator/service.py`の`run_orchestrator_chat()`・`run_orchestrator_chat_stream()`の**冒頭**(コンテキスト構築やLLM呼び出しより前)で、`turn_started_at = datetime.now(UTC).isoformat()`を捕捉するようにした。この値を`_to_storable_new_user_message()`経由で`new_user_message["created_at"]`として、既存のnew_user_messageペイロード(スキーマ変更不要、`dict[str, Any] | None`として元々自由な形で流れている)にそのまま乗せた。

`chat.py`に新設した`_merge_messages_chronologically()`が、保存直前に`list_chat_messages()`で取得した`existing`(全行が`created_at`を持つ、NOT NULL制約済み)と、今回の`new_user_message`・`assistant_message`のペアを**created_atの昇順で安定ソート**する。`assistant_message`自体には元々`created_at`が付与されていないため、`new_user_message`と同じ値(=同じターンのcreated_at)を共有させる——「実際に応答生成が完了した時刻」ではなく「そのターンが送信された時刻」を基準に他ターンとの前後を比べることが、ユーザーの体感する時系列と一致するための判断である。

```python
def _merge_messages_chronologically(existing, new_user_message, assistant_message):
    if not assistant_message.get("created_at"):
        turn_created_at = new_user_message.get("created_at")
        if turn_created_at:
            assistant_message = {**assistant_message, "created_at": turn_created_at}
    combined = [*existing, new_user_message, assistant_message]
    combined.sort(key=_chronological_sort_key)  # 安定ソート
    return combined
```

**判断根拠(なぜ末尾追記のまま「毎回全件を先に読んで判定する」等の重量な仕組みにしなかったか)**: `list_chat_messages()`による保存直前の再取得は17章で既に導入済みであり、今回追加したのは「その取得結果と新しいペアをどう組み合わせるか」という1関数(`_merge_messages_chronologically()`)のみである。Python標準の`list.sort()`はO(N log N)かつ安定ソートであり、1スレッドあたりのメッセージ件数(通常数十〜数百件)を考えれば無視できるコストである。新しい監視機構・重量フィルタは追加していない。

**判断根拠(created_atを`assistant_message`にも複製する設計)**: `message_order`は既存通り「最終的な配列の並び」から機械的に採番されるため、同じターンのペアが確実に隣接し、かつユーザー発言が先に来ることを保証する必要がある。同一created_atの場合、Pythonの安定ソートは`combined`配列内での元の並び順(常に`new_user_message`→`assistant_message`の順で構築している)を保つため、追加の優先度ロジックを書かなくても「同ターンはuser→assistantの順を保つ」が自然に成立する——判断根拠としてテスト(`test_same_turn_pair_keeps_user_before_assistant_on_timestamp_tie`)で直接検証した。

#### (b) 不正・欠損したcreated_atへの防御

`_parse_message_timestamp()`は、`created_at`が無い、または`datetime.fromisoformat()`でパースできない場合に`None`を返し、`_chronological_sort_key()`はそれを「タイムスタンプを持つ全ての行より後」というグループへ振り分ける(実運用では発生しないはずだが——`chat_messages.created_at`はNOT NULL制約済み——万一の不整合時にも例外で落ちず、既存の相対順序をできる限り保つための防御)。

### 18.4 UIへの日時表示の実装詳細

**表示形式**: 相対時間表現(小さくグレーアウトした文字)+ ホバー時に絶対日時(`title`属性によるネイティブブラウザツールチップ)。絶対日時の書式は`/timeline`ページの`formatDate()`(`年/月/日 時:分`、`ja-JP`ロケール)と揃えたが、あちらは"「/timelineページが表示するevent/state/traitデータの整形ロジック」と明記されたページ専用モジュール"であるため、直接インポートはせず`frontend/src/lib/format-time.ts`へ同じ書式を複製した(判断根拠: モジュールの責務分離を優先し、見た目の一貫性は書式の複製で担保した)。相対表現は`Intl.RelativeTimeFormat("ja-JP")`(標準組み込み、新規ライブラリ依存なし)を使用。

**createdAtの伝搬経路(3経路)**:

1. **DB再読み込み時**: `chat-threads.ts::listChatMessages()`が、バックエンドから返る`created_at`(既にAPIレスポンスに含まれていた——17章で`list_chat_messages()`のSELECTへ追加済み。ただし従来のフロントエンド側マッピングはこれを捨てていたため、`metadata.createdAt`へ載せる処理を今回追加した)を`UIMessage.metadata.createdAt`へ格納する。
2. **ユーザー自身の新規発言(ライブ)**: `assistant.tsx::toCreateMessage()`が、送信の瞬間にクライアント側で`new Date().toISOString()`を捕捉し`metadata.createdAt`へ格納する。
3. **AI応答(ライブ、ストリーミング中)**: `stream-translator.ts`が、AI SDKのUI Message Streamプロトコルが標準でサポートする`start`イベントの`messageMetadata`フィールド(`ai`パッケージの型定義で確認済み、独自拡張ではない)を使い、応答の中継が始まった時点の時刻を`{ createdAt: ... }`として付与する。

**判断根拠(ライブ表示用の値と、DB保存用の`created_at`が別物であること)**: バックエンドの`turn_started_at`(chat.pyの並び替えロジックが使う、順序の正しさを担保する値)と、フロントエンドがライブ表示用に独自に捕捉するタイムスタンプは、意図的に別の値である。前者はFastAPIプロセスのクロックで、リクエスト処理の最初期(コンテキスト構築より前)に捕捉される「順序の正」であるのに対し、後者はNext.js側のクロックで、表示の体感を損なわないための近似値に過ぎない。両者を無理に一致させる設計(例えばSSEでバックエンドのturn_started_atをフロントへ送る)も検討したが、依頼書の要件が「表示」であり「順序の正」ではないこと、既存の`start`イベントのペイロードを増やすだけで済むことから、シンプルさを優先してクライアント側捕捉とした。次回のスレッド再読み込み時には、DB由来の正しい`created_at`に自然に置き換わる。

**判断根拠(相対時間表示を秒単位で自動更新しない設計)**: 13〜15章の既存の教訓(体感応答時間の秒数表示が、頻繁なタイマー更新によりstreaming描画と競合し、最終的に撤去された)を踏まえ、`MessageTimestamp`コンポーネントはレンダー時に1度だけ相対時間を計算し、tickによる自動更新は行わない設計にした。既存のチャットUIのデザインシステム・streaming描画への影響を避けるための意図的な判断である。

**表示コンポーネント(`thread.tsx`内、`MessageTimestamp`)**: `AssistantMessage`では応答本文の下に左寄せで、`UserMessage`では吹き出しの下に右寄せで、それぞれ`text-xs text-[#8e8ea0]`(既存のUIが他の補助テキストに使っている色)で表示する。`createdAt`が取得できない場合(理論上は発生しないはずだが、防御的に)は何も表示しない。

### 18.5 テスト結果

`test_message_order_reversal_fix.py`として18件のテストを作成した(既存の`test_context_fabrication_and_message_order.py`をベースに、今回の変更で仕様が変わった箇所を更新し、新しいテストクラスを追加)。

```
MessageInsertPayloadCreatedAtPreservationTests (3件、既存・無変更で再PASS)
ListChatMessagesSelectTests (1件、既存・無変更で再PASS)
ToStorableNewUserMessageTests (2件、turn_started_atパラメータ必須化に合わせて更新)
  PASS: {role, content}形式から{role, parts, created_at}形式への変換、
        turn_started_atがcreated_atとしてそのまま乗ること
  PASS: latest_userがNoneならturn_started_atの値に関わらずNoneを返すこと
PersistChatMessagesSafelyScopingTests (2件、既存・無変更で再PASS)
PersistChatMessagesSafelyConflictRetryTests (3件、既存・無変更で再PASS)
MergeMessagesChronologicallyTests (6件、新規・本タスクの核心)
  PASS: 通常時、新しいターンが既存の末尾に正しく追記されること
  PASS: 【重要】報告された逆転現象の直接再現・修正検証: 先に送信された
        が生成が長引いたターンA、後に送信されたが先に完了したターンB
        について、修正後は常にA→Bの正しい送信順で並ぶこと(修正前の
        挙動であれば[B,B,A,A]になるところを検証)
  PASS: assistant_messageにcreated_atが無い場合、new_user_messageと同じ
        created_atを引き継ぐこと
  PASS: assistant_messageが既にcreated_atを持つ場合、上書きされないこと
  PASS: 同一ターンのペアは、created_atが同値の場合でも常にuser→assistant
        の順を保つこと(安定ソートの直接検証)
  PASS: created_atが欠損・不正な形式でも例外を送出せず、有効な
        タイムスタンプを持つ行より後ろへ振り分けられること
OrchestratorPassesNewUserMessageTests (1件、created_atの実在検証を追加)

18 passed
```

既存の`backend/tests/`(16件)、直近のPhase S(S-0〜S-4、82件)・Phase R系(39件)のスクラッチテスト、および本タスクに直接関連する既存スクラッチテスト(`test_chat_timestamp_awareness.py`・`test_disconnect_response_continuity.py`・`test_temporal_layer_step2.py`・`test_temporal_layer_step3.py`、計47件)も全て再実行し、リグレッションは確認されなかった。

```
18(本タスク) + 123(S-0〜S-4・R系・backend/tests) + 47(関連既存スクラッチ) = 188 passed(合算実行)
```

フロントエンドについては、`npx eslint`(変更した5ファイル対象)・`npx tsc --noEmit`(プロジェクト全体)・`npm run build`(本番ビルド)のいずれも成功した。

**実モデルAPI・実ブラウザでの検証は行っていない。** テストは`chat.py`・`orchestrator/service.py`の関数を直接呼び出す形にとどまり、「2つのバックグラウンドタスクが実際に並行して完了する」というレースコンディション自体は`asyncio`レベルでシミュレートしていない(`_merge_messages_chronologically()`を直接呼び出し、レース後の状態を模した入力を与えて検証する形を取った——`test_disconnect_response_continuity.py`の既存の非同期レースシミュレーション技法よりも、純粋関数の入出力を直接検証する方が本質を捉えやすいと判断した)。依頼書の注意事項通り、追加のサーバーアクセス・APIキー取得は試みていない。マイグレーションは不要だった(スキーマ変更なし、`created_at`列は既存のまま)。

### 18.6 気づいた懸念点

1. **フロントエンドのライブ表示用タイムスタンプ(assistant.tsx・stream-translator.ts)は、Next.jsプロセスのクロックに依存する。** サーバーのクロックスキューが大きい場合、DB再読み込み前後で表示される時刻が数秒単位でずれて見える可能性がある——実害はない(表示専用で、順序の正はバックエンドの`turn_started_at`が担う)が、体感として違和感が出る可能性はゼロではない。
2. **`_merge_messages_chronologically()`は、あくまで「保存する瞬間に判明している情報」を基準にソートする。** 3つ以上のターンが同時多発的に競合した場合(17.5節の懸念点2で既に指摘されているTOCTOUの範囲内)、リトライは1回に限定されているため、最終的な並びが理論上完全に保証されるわけではない——単一テナント・通常は単一デバイスという前提では稀なケースと考えるが、複数デバイスの同時利用が増える場合は再検討の価値がある(17.5節の既存の懸念点と同種のスコープ限定)。
3. **既に本番DBに保存されてしまっている、過去の順序崩れは遡って修正されない。** 今回の修正は新規の保存からのみ効果を持つ。運用者側で、既存スレッドの表示順序に明らかな崩れが残っていないか確認することを推奨する。
4. **UIの日時表示コンポーネント(`MessageTimestamp`)は、Reactのレンダー時に1度だけ相対時間を計算する(tick更新なし)ため、同じ画面を長時間開いたままにすると、表示上の相対時間(「3分前」等)が実際の経過時間より古いまま静止する。** 13〜15章の教訓(streaming描画とタイマー更新の競合)を踏まえた意図的なトレードオフだが、運用上気になる場合は、ページ遷移やスレッド切り替え時の再マウントで自然に更新される、という程度の対応に留まっている。
5. **実ブラウザでの、実際に2つの端末/タブから同一スレッドへほぼ同時に送信するシナリオでの動作確認はできていない。** 本タスクのテストは、あくまでバックエンド関数レベルでのレース後の状態を模したものであり、実際のネットワーク遅延・ブラウザの挙動を含めた end-to-end の確認は運用者側での実地検証に委ねる。
