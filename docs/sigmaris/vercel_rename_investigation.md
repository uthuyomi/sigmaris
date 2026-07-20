# Vercelプロジェクト名変更（shift-pilot-ai → sigmaris）の影響範囲調査

**調査日**: 2026-07-21
**性質**: 本ドキュメントは調査・洗い出しのみを目的とする。**この調査タスクの中では一切のコード・設定変更を行っていない。また、Vercel側のプロジェクト名変更操作も行っていない（運用者が実施する）。**
**対象コミット**: `7cea651`（main）
**前提**: GitHubリポジトリ名変更（`shift-pilot-ai` → `sigmaris`）は完了済み（`docs/sigmaris/repo_rename_investigation.md`）。本タスクは続く**Vercelプロジェクト名（及びそれに伴う `*.vercel.app` URL）の変更**の影響調査。

---

## 0. 最重要の結論（先に述べる）

**`shift-pilot-ai.vercel.app` という文字列は、コードベースのどこにもハードコードされていない。**
（作業ツリー全体を `shift-pilot-ai.vercel.app` / `.vercel.app` / `vercel.app` で検索した結果、実URLの直書きはゼロ。ヒットしたのは `your-frontend.vercel.app` という**プレースホルダ例**のみ＝§1）。

したがって **Vercelプロジェクト名変更に伴う"コード修正"は不要（変更点ゼロ）**。追従が必要になるのは、いずれも**コード外の設定値**である:

| 優先度 | 対象 | 種類 | 影響 |
|---|---|---|---|
| **最重要** | バックエンド `FRONTEND_ORIGIN`（`.env` の値） | CORS許可オリジン | 新フロントURLに更新しないと、ブラウザ→バックエンドの直接呼び出しがCORSで拒否されうる |
| 高 | `GOOGLE_REDIRECT_URI`（env値）＋ Google Cloud Console の承認済みリダイレクトURI | Google OAuth（カレンダー連携） | 未更新だとGoogle連携の認可が失敗 |
| 高 | Supabase Auth の Site URL / Redirect URLs 許可リスト（Supabase管理画面） | ログインOAuthリダイレクト先の許可 | 未登録だとログイン後のリダイレクトが拒否される |
| 中 | Vercel環境変数（管理画面）で旧URLを値に持つものが無いか | 各種env値 | コードからは確認不能。要目視確認（§3） |

> **重要な前提の分岐（確認不能・要確認）**: そもそも本番フロントが `shift-pilot-ai.vercel.app`（Vercelの既定サブドメイン）で提供されているのか、**カスタムドメイン**（例: `sigmaris.jp` / `app.sigmaris.jp` 等）で提供されているのかは、コードからは判断できない。もし本番がカスタムドメインで運用されているなら、Vercelプロジェクト名変更＝**既定サブドメインが変わるだけ**で、`FRONTEND_ORIGIN` 等が指すのはカスタムドメインなので**機能的影響はほぼ無い**。以下の追従作業は「本番URLが実際に `*.vercel.app` に依存している場合」に必要になる。まず**本番フロントの実URL（＝ブラウザがアクセスするオリジン）が何か**を運用者に確認すること。

---

## 1. `shift-pilot-ai.vercel.app` の直接的な参照箇所（一覧）

作業ツリー全体を検索した結果:

| 検索文字列 | ヒット | 判定 |
|---|---|---|
| `shift-pilot-ai.vercel.app` | **0件** | コード・設定・ドキュメントのいずれにも実URLの直書きなし |
| `your-frontend.vercel.app`（プレースホルダ） | 2ファイル | 例示のみ（下表）。実動作に影響しない |

| ファイル | 該当行 | 内容 | 対応 |
|---|---|---|---|
| `backend/env.example:3` | `FRONTEND_ORIGIN=https://your-frontend.vercel.app` | `.env` 記入例のプレースホルダ | 任意（ドキュメント一貫性。実値ではない） |
| `docs/operations/fly-backend-deploy.md:19,26` | `FRONTEND_ORIGIN="https://your-frontend.vercel.app"` / `GOOGLE_REDIRECT_URI="https://your-frontend.vercel.app/auth/callback"` | Fly.ioデプロイ手順の例（レガシー） | 任意（Flyはレガシー。優先度・低） |

**結論**: フロントのVercel URLを前提に**直接埋め込んだコードは存在しない**。以下、依頼書が重点確認を求めた各観点を個別に検証する。

### 1-1. CORS許可リスト（バックエンド）
→ **ハードコードなし**。§2で詳述。

### 1-2. フロントエンド環境変数（`NEXT_PUBLIC_APP_URL` 等）
- `NEXT_PUBLIC_APP_URL` / `NEXT_PUBLIC_SITE_URL` に相当する変数は**存在しない**（grepで不検出）。
- フロント→バックエンドのベースURLは `frontend/src/lib/backend/client.ts:3-8`:
  ```
  process.env.NEXT_PUBLIC_API_URL ?? process.env.BACKEND_API_BASE_URL ?? "http://127.0.0.1:8000"
  ```
  これは**バックエンド**（`api.sigmaris.jp` / Cloudflare Tunnel）を指す値であり、**Vercelフロントの自URLではない**。Vercelプロジェクト名変更の影響を受けない。
- したがって「フロントが自分自身のVercel URLを環境変数として持つ」構造は無い。

### 1-3. X（Twitter）投稿・返信の生成ロジック
- `backend/app/services/x_post_generator.py` を `vercel` / `sigmaris.jp` / `https://` / `.app` で検索 → **該当なし**。投稿文にフロントのVercel URLを埋め込む処理は**存在しない**。
- 投稿文中のURLは、名前→Xハンドル変換（`@Oyasu1999` 等）とハッシュタグのみで、フロントドメインは含まれない。→ Vercel名変更の影響なし。

### 1-4. `og:url` 等 SNS共有用メタタグ
- `metadataBase` / `openGraph` / `og:url` に相当する記述は**存在しない**（grepで不検出）。
- PWA `frontend/src/app/manifest.ts` の `start_url` は **`/launch`（相対パス）**、`scope` は `/`。絶対URL（Vercelドメイン）を持たない → 影響なし。
- したがって、**フロントドメインを絶対URLで埋め込んだメタタグは無く**、Vercel名変更で追従すべきメタタグは存在しない。

---

## 2. CORS設定への影響（最重要）

### 2-1. 実装の確認（コード上の事実）
- `backend/app/main.py:55-61`:
  ```python
  app.add_middleware(
      CORSMiddleware,
      allow_origins=[settings.frontend_origin],
      allow_credentials=True,
      allow_methods=["*"],
      allow_headers=["*"],
  )
  ```
- `backend/app/config.py:10`:
  ```python
  frontend_origin: str = "http://localhost:3000"
  ```
- **CORSの許可オリジンは環境変数 `FRONTEND_ORIGIN` から与えられる単一オリジン**であり、コードに `shift-pilot-ai.vercel.app` 等の**URLはハードコードされていない**。許可オリジンを組み立てる箇所は `main.py` の1箇所のみ（他にオリジンリストを構築するコードは無い）。

### 2-2. 影響と必要な追従（最重要）
- **必要なコード変更: なし。**
- 追従が必要なのは**バックエンドの `.env` の `FRONTEND_ORIGIN` の値**（環境変数の"名前"ではなく"値"）。本番フロントのオリジンが `https://shift-pilot-ai.vercel.app` から新URLに変わる場合、`FRONTEND_ORIGIN` をその新URL（**スキームとホストのみ、末尾スラッシュ無し**）へ更新する必要がある。
- 未更新の場合の症状: **ブラウザがバックエンドを直接呼び出す経路があれば**、プリフライト/本リクエストがCORSで拒否され、該当機能が失敗する。

### 2-3. 影響度の但し書き（過度に恐れないための正確な整理）
- 本アプリの主経路は「ブラウザ → Next.js（同一オリジン）→ **Next.js APIルート（サーバー側）** → バックエンド」であり、**サーバー→サーバーのfetchにはブラウザCORSは適用されない**（`frontend/src/lib/backend/client.ts` の `fetchBackendJson` はNextサーバー側実行）。ライブSSEも `EventSource("/api/live/stream")`（同一オリジンのNextルート）経由でサーバーがバックエンドへ中継する。
- したがって、**ブラウザがバックエンド（`api.sigmaris.jp`）を直接叩く経路が現状どれだけあるか**によってCORSの実影響度は変わる。`NEXT_PUBLIC_API_URL`（ブラウザ露出）が未設定なら、ブラウザは基本的にバックエンドURLを知らず、直接呼び出しは発生しにくい。
- **とはいえ**、`allow_credentials=True` でCORSが設定されている以上、`FRONTEND_ORIGIN` を新フロントオリジンに一致させておくのが**正しく安全**。「最重要の追従項目」という位置づけは変えない（設定漏れが起きたときの切り分けを容易にするためにも、確実に合わせるべき）。

---

## 3. Vercelの環境変数への影響

- **コードからは確認不能**（Vercel管理画面側の設定のため）。以下を運用者が目視確認すること。
- 確認観点:
  - Vercelプロジェクトの環境変数のうち、**値に旧URL（`shift-pilot-ai.vercel.app`）を含むもの**が無いか。
  - 特に `BACKEND_API_BASE_URL` / `NEXT_PUBLIC_API_URL` は**バックエンドURL**（`api.sigmaris.jp` 等）を指すはずで、**フロントの自URLではない**ため、通常はVercel名変更の影響を受けない（値がバックエンドを指していることを確認）。
  - `GOOGLE_REDIRECT_URI`（§4-2）が `https://<旧フロントドメイン>/auth/callback` を値に持つ場合、新ドメインへの更新が必要。
- コード側では、これらの環境変数は**値の直書きが無く**、すべて `process.env.*` 参照（`client.ts`, `oauth.ts` 等）なので、**env値の更新のみで追従でき、コード修正は不要**。

---

## 4. Cloudflare Tunnel・その他インフラ／認証への影響

### 4-1. Cloudflare Tunnel
- `docs/cloudflare-tunnel.md` を確認。Tunnelは `api.sigmaris.jp → Cloudflare Tunnel → localhost:8000（FastAPI）` を公開するのみで、**VercelフロントのURLへの依存は無い**。
- ただし**逆方向の依存**に注意: バックエンドのCORS（`FRONTEND_ORIGIN`）はフロントのオリジンに依存する（§2）。Tunnel設定自体は変更不要だが、**Tunnel経由でバックエンドに届くブラウザ直リクエストのOriginが新フロントドメインになる**点は、`FRONTEND_ORIGIN` 更新（§2）でカバーされる。
- **結論**: Cloudflare Tunnelの設定は**追従不要**。

### 4-2. Google OAuth（カレンダー連携）— 高優先の追従
- `frontend/src/lib/google/oauth.ts:45-49` は `GOOGLE_REDIRECT_URI`（env）を `google.auth.OAuth2` に渡す。
- 本番のリダイレクトURIが `https://<旧フロントドメイン>/auth/callback` の場合、**フロントドメインが変わると以下が必要**:
  1. `GOOGLE_REDIRECT_URI`（env値）を新ドメインへ更新。
  2. **Google Cloud Console の「承認済みのリダイレクトURI」「承認済みのJavaScript生成元」**に新ドメインを追加。
- 未対応だと Googleカレンダー/シート連携の認可が `redirect_uri_mismatch` で失敗する。**コード変更は不要（env値＋Console設定）**。

### 4-3. Supabase Auth（ログイン）— 高優先の追従
- `frontend/src/components/auth-controls.tsx:69` は OAuthログイン時の `redirectTo` を **`${window.location.origin}/auth/callback` と動的に生成**する（ドメインをハードコードしていない）。`frontend/src/app/auth/callback/route.ts` も `request.url` 基準の相対リダイレクトで、ドメイン直書きは無い。
- したがって**コード上はドメイン変更に自動追従**する。ただし Supabase 側の許可リストに依存する:
  - **Supabase 管理画面 → Authentication → URL Configuration の「Site URL」「Redirect URLs」許可リスト**に、新フロントドメイン（`https://<新ドメイン>/**` 等）を追加する必要がある。未登録だと、ログイン後のリダイレクトが Supabase に拒否される。
- **コード変更は不要（Supabase管理画面の設定）**。

### 4-4. インフラ／認証まとめ

| 対象 | 影響 | 追従 | 種類 |
|---|---|---|---|
| Cloudflare Tunnel | なし | 不要 | — |
| バックエンド CORS `FRONTEND_ORIGIN` | フロントオリジン依存 | **必要（最重要）** | backend `.env` 値 |
| Google OAuth `GOOGLE_REDIRECT_URI` ＋ Google Cloud Console | フロントドメイン依存 | 必要（本番URLが変わる場合） | env値＋外部管理画面 |
| Supabase Auth Site URL / Redirect 許可リスト | フロントドメイン依存 | 必要（本番URLが変わる場合） | Supabase管理画面 |
| Vercel環境変数 | 旧URL値の有無次第 | 目視確認 | Vercel管理画面 |
| コード（フロント/バック） | ハードコードなし | **不要（変更点ゼロ）** | — |

---

## 5. 変更後の確認手順（提案）

前提: まず**本番フロントの実オリジン**（`*.vercel.app` かカスタムドメインか）を確定させる（§0の分岐）。以下は「本番URLが実際に変わる場合」の確認手順。

1. **フロント表示**: 新URL（新 `*.vercel.app` またはカスタムドメイン）で `/`・`/login`・`/chat` が正常表示されることを確認。
2. **ログイン（Supabase OAuth）**: Googleログインを実行し、`/auth/callback` を経て正常にログインできることを確認。失敗する場合は Supabase の Site URL / Redirect URLs 許可リスト（§4-3）を確認。
3. **チャット疎通（CORS含む）**: ログイン後 `/chat` で1往復会話が成立することを確認（フロント→Next APIルート→バックエンドの経路）。ブラウザのDevTools → Network / Console で **CORSエラーが出ていないか**を確認。CORSエラーが出た場合はバックエンドの `FRONTEND_ORIGIN`（§2）を新オリジンに更新し、バックエンド再起動。
4. **Googleカレンダー連携**: `/settings` からGoogle連携を実行、または予定作成/一覧ツールを使い、`redirect_uri_mismatch` 等が出ないことを確認。出る場合は `GOOGLE_REDIRECT_URI` と Google Cloud Console（§4-2）を確認。
5. **ライブSSE**: `/live` を開き、チャット中の内部イベントがリアルタイム表示されることを確認（同一オリジンのNextルート経由なのでCORS非依存だが、総合疎通確認として）。
6. **PWA/manifest**: 新ドメインで `manifest.webmanifest` が取得でき、`start_url:/launch` が相対で解決されることを確認（絶対URL依存が無いことの確認）。
7. **バックエンド健全性**: `curl -s https://api.sigmaris.jp/health` が `{"status":"ok",...}` を返す（バックエンド自体はVercel名変更の影響を受けないことの再確認）。
8. **Vercelデプロイ**: プロジェクト名変更後、Vercelダッシュボードでデプロイが正常状態か、環境変数に旧URL値が残っていないか（§3）を確認。

---

## 6. 推奨される実施順序

コード変更は不要のため、順序は「設定値・許可リストの更新 → 確認」が中心。

1. **事前確認（変更前）**
   - **本番フロントの実オリジンを確定**（`*.vercel.app` かカスタムドメインか）。カスタムドメイン運用なら、Vercel名変更の機能的影響はほぼ無い（§0）。
   - 現在の `FRONTEND_ORIGIN` / `GOOGLE_REDIRECT_URI` の値、Supabase の Site URL / Redirect URLs、Google Cloud Console のリダイレクトURIを控える。
2. **Vercelプロジェクト名を変更（運用者が実施）**
   - 新 `*.vercel.app` サブドメインが払い出される。カスタムドメイン運用なら本番URLは不変。
3. **本番オリジンが実際に変わる場合のみ、許可リスト/設定値を"追加"更新（切替はダウンタイム最小化のため"追加→切替→削除"の順が安全）**
   - Supabase Auth の Redirect URLs / Site URL に**新ドメインを追加**（§4-3）。
   - Google Cloud Console の承認済みリダイレクトURI/JS生成元に**新ドメインを追加**（§4-2）。
   - バックエンド `.env` の `FRONTEND_ORIGIN` を新オリジンへ更新 → **バックエンド再起動**（§2）。
   - 必要なら `GOOGLE_REDIRECT_URI`（env）を新ドメインへ更新。
   - Vercel環境変数に旧URL値が無いか確認（§3）。
4. **総合確認**
   - §5 の 1〜8 を実施。特に **3（CORS）・2（ログイン）・4（Google連携）** を重点確認。
5. **後片付け（任意・安定確認後）**
   - 旧ドメインを許可リストから削除（不要な許可を残さない）。
   - `backend/env.example` / `docs/operations/fly-backend-deploy.md` のプレースホルダ例を、必要ならブランド更新のついでに整える（優先度・低）。

**原則**: コードのデプロイは不要。CORS（`FRONTEND_ORIGIN`）・OAuth 許可（Supabase / Google）の**設定値更新が本体**であり、これらは「新URLを追加 → 動作確認 → 旧URLを削除」の順にすると切替時の不通を避けられる。

---

## 7. 調査上の制約

- 本調査は作業ツリー（`7cea651`）の静的読み取りのみ。**以下は確認不能**:
  - 本番フロントの実オリジン（`*.vercel.app` かカスタムドメインか）。
  - Vercel管理画面の環境変数・ドメイン設定。
  - バックエンド `.env` の `FRONTEND_ORIGIN` / `GOOGLE_REDIRECT_URI` の実値。
  - Supabase 管理画面の Site URL / Redirect URLs 許可リスト。
  - Google Cloud Console の承認済みリダイレクトURI。
  - `.env`・秘密情報の実値（本ドキュメントには一切含めない）。
- 上記はいずれも**コード外の設定**であり、実際の追従作業は運用者が各管理画面で行う。本調査で確定できたのは「**コード側にVercel URLの直書きは無く、コード変更は不要**」という点である。

---

*本ドキュメントは読み取り専用の調査成果物であり、コード・設定・Vercelプロジェクト名のいずれにも変更を加えていない。*
