# Phase A サマリー(A0〜A5)

**期間:** 2026-07-03 〜 2026-07-05
**発端:** [global_state_migration_audit.md](global_state_migration_audit.md)(`sigmaris_global_state`への移行可否を調査した監査レポート)で洗い出された、既存アーキテクチャの構造的な問題群への対応。
**完了状況:** Phase A0〜A5すべて完了・`main`へマージ済み。**Phase Aはこれで完了とする。** Phase B(記憶拡張機能群)は未着手。

---

## 各Phaseの概要

| Phase | タイトル | 目的 | 状態 |
|---|---|---|---|
| A0 | chat_threads/chat_messages書き込み経路の一本化 | フロントエンドの直Supabase書き込みとバックエンド経由書き込みが並存していた二重経路を、バックエンド単一経路に統合 | 完了・マージ済み |
| A1 | セッション継続方式の実装 | ターン毎のトークン線形増加とスレッド間で記憶が分断される問題を、スレッド横断の「直近ログウィンドウ」で解消 | 完了・マージ済み |
| A1-b | `/chat`画面をorchestrator経由に切り替え | 実際にナビゲーション可能な唯一のチャットUIが、記憶注入・A1のウィンドウを持つorchestratorを経由していなかった問題を修正 | 完了・マージ済み(実モデル応答での検証は未実施、6章参照) |
| A2 | プロンプト構造の並べ替え(OpenAIキャッシュ有効化) | `build_system_prompt()`内の分単位タイムスタンプがプレフィックスキャッシュを毎回無効化していた問題を、固定部分を前方に集約して解消 | 完了・マージ済み |
| A3 | `sigmaris_decision_log`の本稼働 | 毎ターン無条件で汎用的な`chat_turn:xxxx`行が記録されるだけだった意思決定ログを、LLM判定による実質的な決定・方針転換の記録に置き換え | 完了・マージ済み |
| A4 | 同時書き込みの排他制御 | `replace_chat_messages()`の全削除→全INSERT方式が持つ、競合書き込み時のサイレントなデータ消失リスクを、楽観ロック(CAS)で検知・防止 | 完了・マージ済み |
| A5 | RAG(pgvector検索)の`LOCAL_LLM_ENABLED`依存見直し | `LOCAL_LLM_ENABLED=false`時にRAG検索が丸ごとスキップされていた問題を、OpenAI Embeddings APIへのフォールバックで解消 | 完了・マージ済み |

各Phaseの詳細は個別レポートを参照: [phase_a0_report.md](phase_a0_report.md) / [phase_a1_report.md](phase_a1_report.md) / [phase_a1b_report.md](phase_a1b_report.md) / [phase_a2_report.md](phase_a2_report.md) / [phase_a3_report.md](phase_a3_report.md) / [phase_a4_report.md](phase_a4_report.md) / [phase_a5_report.md](phase_a5_report.md)

---

## Phase Aを通じて解消された構造的問題

1. **書き込み経路の二重化**(A0): フロントエンドが直接Supabaseに書き込むパスと、バックエンド経由のパスが並存し、どちらが正かが曖昧だった。バックエンド単一経路に統合し、会話履歴の正がどこにあるかを明確化した。
2. **記憶のスレッド分断**(A1): 各チャットスレッドが独立した文脈しか持たず、スレッドを跨ぐと記憶が失われていた。スレッド横断の直近ログウィンドウを導入し、連続性を確保した。
3. **実UIとorchestratorの乖離**(A1-b): 記憶注入・セッション継続を持つorchestrator経由の実装が存在していたにもかかわらず、実際にユーザーが使う`/chat`画面はそれを経由しない別経路(`chat.py`直呼び)を使っていた。A1までの改善が実際には一切効いていなかったことが判明し、切り替えを実施した。
4. **プロンプトキャッシュの無効化**(A2): システムプロンプトに分単位のタイムスタンプが埋め込まれており、OpenAIのプレフィックスキャッシュが実質的に毎回ミスしていた。固定部分を前方・可変部分を末尾に再配置し、キャッシュヒットを可能にした。
5. **意思決定ログの形骸化**(A3): 毎ターン中身のない`chat_turn:xxxx`行が記録されるだけで、自己改善システムの「経験の蓄積」として機能していなかった。LLM判定による実質的な決定検出とsupersede(方針転換の追跡)機構を導入した。
6. **同時書き込みによるデータ消失リスク**(A4): 複数クライアント(Web・WearOSなど)が同一スレッドに同時に書き込んだ場合、片方の変更が無条件に上書きされ消える可能性があった。`chat_threads.version`を使った楽観ロックで、競合を検知してエラーとして扱えるようにした(セッションを跨いだ分岐までは未解決、後述)。
7. **RAG検索のLOCAL_LLM_ENABLED依存**(A5): OpenAI運用時にembedding生成が即座にスキップされ、pgvectorによる記憶検索が完全に機能していなかった。OpenAI Embeddings APIへのフォールバック(768次元に切り詰め)を実装し、運用モードによらず検索が機能するようにした。

---

## 未適用のマイグレーション(要運用者対応)

`SUPABASE_SERVICE_ROLE_KEY`がローカル環境に存在しないため、以下3件は作成のみ済みで**未適用**。運用者側で`python3 scripts/apply_migration.py <id>`を実行する必要がある(適用順は依存関係なし、どの順でも安全):

| マイグレーションID | Phase | 内容 |
|---|---|---|
| `202607030025_chat_messages_user_created_index.sql` | A1 | `chat_messages(user_id, created_at desc)`の複合インデックス追加 |
| `202607040026_decision_log_supersede.sql` | A3 | `sigmaris_decision_log`に`thread_id`・`invocation_id`・`supersedes`・`superseded_by`列、`decision_type`に`policy_change`を追加 |
| `202607050027_chat_threads_version.sql` | A4 | `chat_threads`に`version`列(デフォルト1)を追加 |

いずれも各Phaseの実装は「マイグレーション未適用でも既存機能を一切壊さない」設計になっており(A4で特に厳密に検証済み、`phase_a4_report.md` 4章参照)、適用タイミングはいつでもよい。適用するとそれぞれの新機能(セッション継続の高速化・decision_logのsupersede追跡・書き込み競合の検知)が有効化される。

---

## Phase A全体を通じて残っている既知の懸念事項

1. **Phase A1-bのtool-event中継・confirmation marker迂回ロジックが、実モデル応答に対して一度も検証されていない**。Phase A1-bのフォローアップ時点でサーバー(`sigmaris@192.168.179.11`)へのSSHアクセスがなく検証不能だったため、ユーザーの判断で「A0〜A2をまとめてマージし、A1-bのリスクは許容する」という形で`main`に取り込まれている。
2. **A4のCASは「厳密に同時」なレースのみ解決し、セッションを跨いだ会話履歴の分岐(divergence)は未解決**。同一スレッドを複数クライアントが並行して開いている場合、片方の書き込み成功後にもう片方が(古い会話履歴のまま)次のターンを送信すると、バージョンチェック自体は通過してしまい、内容としては上書きが起きる。全メッセージ配列を毎回丸ごと置き換える設計に内在する限界で、真に解決するには差分アペンド方式への書き換えかクライアント側の再取得ロジックが必要(`phase_a4_report.md` 5章)。
3. **`/api/app/chat/messages/replace`(A0で追加)は生きたトラフィックからの呼び出しが一度もない**。A4で追加した409競合ハンドリング・フロントエンドのリトライロジックも未検証の経路。
4. **既存fact embeddingのモデル由来混在リスク**(A5): 次元は揃えたが、Ollama製とOpenAI製の embeddingが同一テーブルに混在し得る状態になっており、異なるモデル間のコサイン類似度の意味的妥当性は厳密には保証されない。実運用では「Ollama優先」設計のため発生頻度は限定的と見込むが、Phase B以降で検索精度が疑わしい場合はまずここを疑うべき(`phase_a5_report.md` 7章)。
5. **`update_fact_embeddings`のバックフィルジョブが、OpenAI運用期間中はずっと空振りしていた可能性がある**(A5で発見・修正)。次回スケジュール実行で未生成分が遡って処理されることを運用側で確認しておくとよい。
6. 上記いずれも、実モデルAPI・本番サーバーへのアクセスが確保でき次第、優先的に実地検証すべき項目である。

---

## Phase B以降への申し送り

- Phase A5・7章で触れた「embedding provenance追跡」「embedding生成のチャットホットパス化に伴うレイテンシ」は、Phase Bで記憶機能を拡張する前に一度実測・検討する価値がある。
- Phase A4・5章で触れた「セッションを跨いだ divergence」は、Phase Bで記憶の一貫性をさらに扱う場合に前提条件として効いてくる可能性が高い。
- `orchestrator/service.py`内の未使用デッドコード(facts_ctx/trends_ctx の重複計算、`phase_a5_report.md` 4章)は、Phase Bで`_build_memory_context`周辺を触る際に併せて整理する候補。
