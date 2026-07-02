# Phase A0 実施報告: chat_threads / chat_messages 書き込み経路の一本化

**目的:** `frontend/src/lib/chat-threads.ts`(Next.jsからSupabase直接アクセス)と`backend/app/services/app_chat_data.py`(FastAPI経由)という2つの独立した書き込み経路を、バックエンド経由の1経路に統一する。
**作業ブランチ:** `phase-a0-chat-thread-consolidation`（`main`から分岐、作業前に`git status`でクリーンな状態を確認済み）
**範囲:** 本タスクは書き込み経路の統一のみ。Phase A1(セッション継続)・A2(プロンプト構造)・A3(decision_log本稼働)・A5(RAGのLOCAL_LLM_ENABLED依存)には着手していない。

---

## 1. 洗い出した呼び出し箇所（作業開始前の調査結果）

### `frontend/src/lib/chat-threads.ts` の各関数の呼び出し元

| 関数 | 呼び出し元 |
|---|---|
| `listChatThreads` | `frontend/src/app/chat/page.tsx`（スレッド一覧取得） |
| `createChatThread` | `frontend/src/app/chat/page.tsx`（スレッドが0件の時の初期作成、選択スレッドが見つからない時のフォールバック作成）、`frontend/src/app/api/chat/threads/route.ts`（`POST /api/chat/threads`） |
| `getChatThread` | `frontend/src/app/chat/page.tsx`（選択スレッドの存在確認） |
| `renameChatThread` | `frontend/src/app/api/chat/threads/[threadId]/route.ts`（`PATCH`） |
| `deleteChatThread` | `frontend/src/app/api/chat/threads/[threadId]/route.ts`（`DELETE`） |
| `listChatMessages` | `frontend/src/app/chat/page.tsx`（選択スレッドの初期メッセージ取得） |
| `replaceChatMessages` | **呼び出し元ゼロ（未使用のエクスポート関数）** |

`chat-threads.ts`を直接呼んでいるのはこの4ファイルのみ（`chat-workspace.tsx`等のクライアントコンポーネントは呼んでいない。実チャット時のメッセージ保存は`/api/chat/stream` → バックエンドの`chat.py::stream_chat_completion_ui(persist_messages=True)`が内部で`app_chat_data.replace_chat_messages`を直接呼ぶ経路で行われており、`chat-threads.ts`の`replaceChatMessages`は経由しない）。

### `frontend/src/app/api/chat/threads/route.ts` / `[threadId]/route.ts` の呼び出し内容

- `route.ts` (`POST`): 認証確認 → `createChatThread(user.id, { id: threadId? })` を呼び出し、作成したスレッドを返す。
- `[threadId]/route.ts` (`PATCH`): 認証確認 → `renameChatThread(user.id, threadId, title)`。
- `[threadId]/route.ts` (`DELETE`): 認証確認 → `deleteChatThread(user.id, threadId)`。

### `backend/app/services/app_chat_data.py` の対応関数のバックエンド側呼び出し元（移行前）

| 関数 | 呼び出し元 |
|---|---|
| `get_chat_thread` | `backend/app/services/chat.py`（`run_chat_completion`/`stream_chat_completion_ui`内、`persist_messages=True`時の存在確認）、`backend/app/routes/app_data.py`（`GET /api/app/chat/threads/{thread_id}`、**ただし移行前はこのエンドポイントをフロントエンドから呼んでいる箇所はゼロだった**） |
| `replace_chat_messages` | `backend/app/services/chat.py`（同上、応答生成後の永続化）、`backend/app/routes/app_data.py`（`POST /api/app/chat/messages/replace`、**これも移行前はフロントエンドからの呼び出し元がゼロだった**） |
| スレッド一覧取得・作成・リネーム・削除・メッセージ一覧取得 | **移行前は存在しなかった**（`chat-threads.ts`がSupabaseに直接行っていた） |

**重要な発見**: `GET /api/app/chat/threads/{thread_id}` と `POST /api/app/chat/messages/replace` はPhase A0着手前から**バックエンドに存在していた**が、フロントエンドはこれらを一切呼ばず、独自にSupabaseへ直接アクセスしていた。つまり「2つの独立した経路」のうち、バックエンド側の経路は既に部分的に用意されていたが未接続だった状態。

---

## 2. 追加・変更したファイルの一覧と変更概要

### バックエンド

| ファイル | 変更概要 |
|---|---|
| `backend/app/services/app_chat_data.py` | `list_chat_threads` / `create_chat_thread` / `rename_chat_thread` / `delete_chat_thread` / `list_chat_messages` を新規追加。すべて既存の`get_profile_context`でJWTから`user_id`を解決し、既存の`rest_select`/`rest_insert`/`rest_update`/`rest_delete`ヘルパーを使う既存パターンを踏襲（新規ロジックの重複実装なし）。 |
| `backend/app/services/app_data.py` | 上記5関数を集約窓口として re-export に追加。 |
| `backend/app/routes/app_data.py` | 新規エンドポイントを追加: `GET /api/app/chat/threads`（一覧）、`POST /api/app/chat/threads`（作成）、`PATCH /api/app/chat/threads/{thread_id}`（リネーム）、`DELETE /api/app/chat/threads/{thread_id}`（削除）、`GET /api/app/chat/threads/{thread_id}/messages`（メッセージ一覧）。既存の`_require_jwt()`パターン、既存の`routes/agent.py`等と同じレスポンス形式（`{"ok": true, ...}`）に合わせた。 |

### フロントエンド

| ファイル | 変更概要 |
|---|---|
| `frontend/src/lib/chat-threads.ts` | 全面書き換え。Supabaseクライアントへの直接アクセスを削除し、`fetchBackendJson`（`@/lib/backend/client`、既存の共通HTTPクライアント）と`readBackendAuthHeaders`（`@/lib/backend/auth`、既存の認証ヘッダー生成、`frontend/src/app/api/chat/route.ts`等で既に使われているものと同一）を使ってバックエンドAPIを呼ぶ薄いプロキシに置き換えた。**エクスポートする関数のシグネチャ（引数名・順序・返り値の型）は変更していない**ため、呼び出し元（`page.tsx`、`api/chat/threads/*`）は無改修で動作する。 |

`frontend/src/app/chat/page.tsx`、`frontend/src/app/api/chat/threads/route.ts`、`frontend/src/app/api/chat/threads/[threadId]/route.ts` は**変更していない**（シグネチャ互換のため改修不要だった）。

---

## 3. 削除したコード（旧Supabase直接アクセス部分）

`frontend/src/lib/chat-threads.ts`から以下を完全に削除（コメントアウトではなく削除）:

- `import { createClient } from "@/lib/supabase/server"` および全関数内での`createClient()`呼び出し
- `import type { UIMessage } from "ai"` は型定義のためのみ残し、実データ処理から`supabase.from("chat_threads")...`/`supabase.from("chat_messages")...`のクエリチェーンを全て削除
- `compactPartsForStorage()`（ファイル添付URLの空文字化、旧`replaceChatMessages`専用のヘルパー）: バックエンドの`app_chat_data.py::compact_parts()`が既に同じ処理をしているため、フロントエンド側では不要になった
- `deriveThreadTitle()`（スレッドタイトル自動生成、旧`replaceChatMessages`専用のヘルパー）: バックエンドの`app_chat_data.py::derive_thread_title()`が既に同じ処理をしているため、フロントエンド側では不要になった
- `LEGACY_DEFAULT_THREAD_TITLE`定数: 上記ヘルパーの削除に伴い未使用になったため削除

---

## 4. テスト・検証の結果

ローカル環境（`backend/.venv`）で`uvicorn app.main:app`を起動し、実際のSupabaseプロジェクト（本番と同一）に対して、実ユーザーのJWTを使い一連の操作をcurlで検証した。

| 手順 | 結果 |
|---|---|
| 1. 既存スレッド一覧取得（`GET /api/app/chat/threads`） | ✓ 移行前に作成済みの2件のスレッドが欠損なく取得できることを確認 |
| 2. 新規スレッド作成（`POST /api/app/chat/threads`） | ✓ `200 OK`、新規UUIDが発行されたスレッドが返却される |
| 3. スレッド取得（`GET .../{thread_id}`） | ✓ 作成直後のスレッドが取得できる |
| 4. メッセージ書き込み（`POST /api/app/chat/messages/replace`） | ✓ `200 OK` |
| 5. メッセージ一覧取得（`GET .../{thread_id}/messages`） | ✓ 書き込んだメッセージが1件返る |
| 6. スレッドリネーム（`PATCH .../{thread_id}`） | ✓ `200 OK`、直後の取得でタイトルが反映されている |
| 7. スレッド削除（`DELETE .../{thread_id}`） | ✓ `200 OK` |
| 8. 削除後の再取得 | ✓ `thread: null`（削除確認） |
| 9. 削除後のメッセージ一覧 | ✓ `messages: []`（`on delete cascade`によりメッセージも連動削除されていることを確認） |
| 10. 未認証アクセス | ✓ `401 Unauthorized`（`{"error": "Missing bearer token."}`） |
| バックエンドログでの経路確認 | ✓ `uvicorn`ログを目視確認し、`chat_threads`/`chat_messages`へのSupabase REST呼び出し（PATCH/DELETE等）が**すべてバックエンドプロセスから発行されたもののみ**であることを確認。フロントエンドから直接Supabaseへ向かうリクエストは存在しない（コード上`chat-threads.ts`からSupabaseクライアントの参照自体を削除済みのため、原理的に発生し得ない） |

型チェック・静的解析:

- `npx tsc --noEmit -p .`: エラー0件（フロントエンド全体）
- `npx eslint src/lib/chat-threads.ts`: 警告・エラー0件
- `python -c "import app.main"`: エラーなくインポート成功（バックエンド全体の起動時チェック）

**未実施の検証（今回のスコープ外/環境制約）:**

- 実際のブラウザ操作によるUI経由の手動E2Eテスト（本番同等のフロントエンドNext.jsサーバーを起動しての確認）は未実施。curlによるAPIレベルの検証のみ。
- 同時に2タブ/2デバイスから同じスレッドを操作した場合の競合挙動テストは未実施（要件3「現状から悪化させないこと」は、書き込みロジック自体（`replace_chat_messages`の全削除→全INSERT方式）を変更していないため、コードレビューベースでは移行前と同じ挙動のはずだが、実機での競合テストは行っていない）。

---

## 5. 懸念点・気づいた点

1. **`replaceChatMessages`(chat-threads.ts)が実質デッドコードだった**: 移行前調査で判明した通り、この関数はフロントエンドのどこからも呼ばれていなかった。今回はご指示通り独断で削除せず、バックエンドプロキシとして実装を保守した（シグネチャ互換維持のため）。**将来的に本当に不要と確認できれば削除を検討してよいが、今回はそのまま残した。** Phase A1でセッション継続ロジックを実装する際、この関数を実際に使うのか、それとも別の経路（現状の`/api/chat/stream`経由の自動永続化）に一本化するのかを判断する必要がある。

2. **`GET /api/app/chat/threads/{thread_id}` と `POST /api/app/chat/messages/replace` も移行前は「存在するが未接続」だった**: バックエンドにコードは存在していたが、フロントエンドから一切呼ばれていなかった。これは「未実装」ではなく「配線漏れ」だった。今回の変更でこの2つも実際に使われるようになった。

3. **`ChatStreamRequest`/`AgentChatRequest`の`thread_id`と、今回一本化した`chat_threads`テーブルの`id`は同一空間だが、生成元が異なる**: `chat/page.tsx`側は`chat-threads.ts`経由でバックエンドに`chat_threads`行を作らせてから`thread_id`を使うのに対し、`/api/orchestrator/chat`経由のリクエスト（WearOSアプリ等）は`thread_id`をクライアント側で自由に生成して送っており、対応する`chat_threads`行が存在しない場合がある(orchestrator経由は`persist_thread: False`のため、そもそも`chat_threads`行の存在確認をスキップする設計)。今回の変更はこの非対称性自体には触れていないが、Phase A1でセッション継続を実装する際に「`chat_threads`行が存在しないthread_id」が来た場合の扱いを整理する必要がある。

4. **`create_chat_thread`にユーザー指定の`thread_id`をそのまま`id`カラムへ渡している**: 元の`chat-threads.ts::createChatThread`と同じ挙動（`options.id`があればそれを使う）を維持したが、UUID形式でない値が来た場合はSupabase側でエラーになる（`chat_threads.id`は`uuid`型）。フロントエンドの`api/chat/threads/route.ts`は`zod`の`z.uuid()`でバリデーション済みのため実害はないが、他のクライアント（将来のモバイルアプリ等）がこの新設バックエンドAPIを直接叩く場合は同様のバリデーションを呼び出し側で行う必要がある。

5. **ローカル動作確認時にビルド外の問題を発見（本タスクでは未修正）**: `frontend/.env.local`（gitignore対象、ローカル限定ファイル）の先頭にUTF-8 BOMが付与されており、`NEXT_PUBLIC_SUPABASE_URL`のキー名がBOM文字と結合してPython側の`pydantic-settings`が正しく読み込めない事象を確認した。本番サーバー（Ubuntu機）では別ファイルのため未確認だが、念のため共有します。**これはPhase A0の変更とは無関係の、ローカル開発環境限定の既知の注意点として報告のみに留め、修正はしていません**（gitignore対象ファイルのため、修正してもコミットされません）。

---

## Related Documents

- [global_state_migration_audit.md](global_state_migration_audit.md) — 本Phase A0の発端となった監査レポート
