# リポジトリ名変更（shift-pilot-ai → sigmaris）の影響範囲調査

**調査日**: 2026-07-21
**性質**: 本ドキュメントは調査・洗い出しのみを目的とする。**この調査タスクの中では一切のコード・設定変更を行っていない。また、GitHubリポジトリ名の変更操作自体も行っていない（運用者が実施する）。**
**対象コミット**: `02519ba`（main）
**現在のリポジトリURL**: `https://github.com/uthuyomi/shift-pilot-ai`（`git remote -v` で確認）

---

## 0. 調査の前提・スコープ・重要な結論

### スコープ（依頼書に従う）
- **対象**: GitHubリポジトリ名の変更に**直接伴って追従が必要になる箇所**のみ。
- **対象外（今回変更しない）**: Supabaseプロジェクト名・テーブル名・**環境変数の名前**・**ローカル/サーバーのフォルダ名**・npm/Pythonのパッケージ名など、変更に時間・リスクがかかるもの。
- コードの実装・修正は行わない。調査・提案のみ。

### 最重要の結論（先に述べる）
**GitHubのリポジトリ名変更は、既存のGitHub側リダイレクトにより、単体では"必須の追従作業"をほとんど生まない。**

GitHubはリポジトリ名を変更しても、旧名（`.../uthuyomi/shift-pilot-ai`）への **Web・git（HTTPS/SSH）・REST API のリクエストを新名へ恒久的にリダイレクト**する（※旧名で別リポジトリが新規作成された場合のみリダイレクトは失われる）。したがって、

- ローカルPC・Ubuntuサーバーの `git remote`（origin URL）は**旧URLのままでも `git pull`/`git push` は動き続ける**。
- Vercelの GitHub 連携・`SIGMARIS_PR_GITHUB_REPO` を使う自己改良PR作成も、旧名のまま**当面は動作し続ける**。

そのため本調査で挙げる項目の大半は「**壊れるから必須**」ではなく「**一貫性・将来の事故防止のため、更新が望ましい**」という性質のものである。以下、性質を明示して分類する。

### 検索方法
作業ツリー全体を、正確な文字列 `shift-pilot-ai`（ハイフン付きスラッグ）と、ブランド由来の `shiftpilot`/`ShiftPilotAI`（ハイフン無し）で分けて検索した。両者は意味が異なる:

- `shift-pilot-ai`（ハイフン付き） … **GitHubリポジトリのスラッグ**、または偶然同名の他リソース（Fly.ioアプリ名）、またはサーバーのフォルダパス。
- `shiftpilot` / `ShiftPilotAI`（ハイフン無し） … **製品ブランド名／パッケージ名**。リポジトリ名変更とは**独立**の別課題（`docs/sigmaris/incident_shiftpilotai_naming_report.md` で既にトラッキング済み）。

---

## 1. コードベース内の直接的な参照箇所（一覧）

`shift-pilot-ai`（ハイフン付きスラッグ）が現れる箇所を、**リポジトリ名変更との関係の性質**で分類する。ビルド成果物・ログ（`frontend/package-lock.json`、`frontend/next-dev-*.log`、`.next`）は除外した。

### 1-A. リポジトリURLに直接依存する箇所（＝リポジトリ名変更で追従が望ましい）

| 箇所 | 内容 | 性質 | 追従の要否 |
|---|---|---|---|
| `git remote` origin（ローカルPC） | `https://github.com/uthuyomi/shift-pilot-ai` | リポジトリURL | **推奨**（旧URLでも動作継続。`git remote set-url` で更新） |
| `git remote` origin（Ubuntuサーバーのチェックアウト） | 同上（`~/shift-pilot-ai` 内） | リポジトリURL | **推奨**（同上。§2参照） |
| `SIGMARIS_PR_GITHUB_REPO`（`.env` の**値**） | `github_pr_publisher.py` が `https://api.github.com/repos/{owner/repo}/...` を組み立てる際に使用（`backend/app/services/github_pr_publisher.py:94,126,130,137,160,170,189,204`） | リポジトリの `owner/repo` 値 | **推奨**（GitHub APIも旧名をリダイレクトするため即座には壊れないが、自己改良PRの宛先なので明示的に新名へ更新するのが安全。※変数の"名前"は変えない＝スコープ内は"値"のみ） |

> 補足: `SIGMARIS_PR_GITHUB_REPO` は `.env`（gitignore、非コミット）にあり、コード上には値が無い。**環境変数の"名前"は変更対象外**だが、その**値がリポジトリ名そのものを指す**ため、リポジトリ名変更に直接連動する数少ない項目として挙げる。運用者側の作業。

### 1-B. 文字列は一致するが、リポジトリ名変更とは独立（＝追従不要）

| 箇所 | 内容 | なぜ独立か |
|---|---|---|
| `backend/fly.toml:1,6` | `app = 'shift-pilot-ai'`（Fly.ioアプリ名） | **Fly.io側のアプリ資源名**であり、GitHubリポジトリ名とは無関係。GitHubを改名してもFlyアプリ名は変わらないし、変える必要もない。加えてバックエンドはFly.io→Ubuntu+Cloudflareへ移行済み（`docs/infrastructure.md`）で、fly.toml自体がレガシー。**今回は触れない。** |
| `backend/app/services/research_agent.py:304` | User-Agent: `... (contact: https://github.com/uthuyomi)` | **ユーザープロフィールURL**であってリポジトリURLではない。リポジトリ名変更の影響を受けない。 |

### 1-C. サーバーのフォルダパス（＝依頼書によりスコープ外）

以下は `/home/sigmaris/shift-pilot-ai/` または `~/shift-pilot-ai/` という**サーバー上のチェックアウト先フォルダ名**への依存であり、**フォルダ名変更は依頼書で対象外**。GitHubリポジトリ名を変更しても、git clone 済みディレクトリの名前は自動では変わらない（両者は独立）。したがって**リポジトリ名変更のみでは、これらは修正不要**。運用者がフォルダ名も併せて改名する場合にのみ追従が必要になる（今回は対象外）。

| 箇所 | 内容 |
|---|---|
| `scripts/apply_migration.py:1`（shebang） | `#!/home/sigmaris/shift-pilot-ai/backend/.venv/bin/python3` |
| `scripts/apply_migration.py:4,13`（docstring） | `デプロイ先: /home/sigmaris/shift-pilot-ai/scripts/apply_migration.py` 等 |
| `scripts/import_chatgpt_history.py:16`（使用例コメント） | `python3 ~/shift-pilot-ai/scripts/import_chatgpt_history.py ...` |

> 注意: `apply_migration.py` の shebang はフォルダパスをハードコードしているため、**もし将来サーバーのフォルダ名を変える場合は shebang の追従が必須**（さもないとスクリプト実行が壊れる）。ただし今回のスコープ（リポジトリ名のみ）では対象外。

### 1-D. 製品ブランド名（ハイフン無し／別課題・原則追従不要）

以下は**製品名「ShiftPilotAI」やパッケージ名**であり、GitHubリポジトリのスラッグとは別物。リポジトリ名変更に伴って直す必要はない（＝依頼書のスコープ外だが、混同を避けるため一覧化する）。ブランド名の統一は `docs/sigmaris/incident_shiftpilotai_naming_report.md` が扱う独立タスク。

| 箇所 | 内容 | 備考 |
|---|---|---|
| `package.json:2` | `"name": "shiftpilotai-workspace"` | npmワークスペース名（非公開）。パッケージ名＝スコープ外 |
| `frontend/package.json:2` | `"name": "shiftpilotai"` | 同上 |
| `backend/pyproject.toml:2` | `name = "shiftpilotai-backend"` | Pythonパッケージ名（非公開）。スコープ外 |
| `backend/shiftpilotai_backend.egg-info/*` | 自動生成物（`pip install -e .` の産物） | パッケージ名の派生。生成物 |
| `backend/app/services/chat_prompts.py`（`incident_shiftpilotai_naming_report.md:12` で言及） | 「ShiftPilotAI・shift-pilot-ai・ShiftPilotという名前は絶対に使わない」固定ルール | **意図的なガード。リポジトリ名変更で削除・変更してはならない**（"shift-pilot-ai"を名乗らせないための防止策）。むしろ残すべき |
| `orchestrator/service.py`, `chat.py`, `chat_routing.py` の `replace_forbidden_assistant_names` 等 | 応答中の "ShiftPilotAI/ShiftPilot" を "シグマリス" へ置換 | ブランド統一の実装。リポジトリ名とは無関係 |
| `frontend/src/lib/chat-confirmation.ts`, `chat_messages.py`, `thread.tsx`, `app-shell.tsx` 等の `shiftpilot-confirmation` マーカー | ツール確認用の内部プロトコル文字列 | 内部識別子。リポジトリ名と無関係（変更はUI/バックエンド双方の同時修正が必要で高リスク＝別課題） |
| `supabase/migrations/202603290001_initial_app_schema.sql` | `shiftpilot` 参照 | DB＝スコープ外 |
| `frontend/public/sw.js` | ブランド由来文字列 | 生成/静的アセット。ブランド課題 |

### 1-E. コミット済みCI/CD
- **`.github/workflows/` に追跡されたワークフローは存在しない**（`git ls-files .github` は空）。よって**GitHub Actions等のCI設定でリポジトリ名を追従すべき箇所は無い**。

---

## 2. インフラ（Vercel／サーバー／Cloudflare Tunnel）への影響・確認結果

### 2-1. Vercel
- **コード内にGitHubリポジトリURLの参照は無い。** `vercel.json`・`frontend/vercel.json` はビルド設定（framework/installCommand/buildCommand/outputDirectory/ignoreCommand）のみで、リポジトリ名・URLを持たない（実ファイル確認済み）。
- Vercelプロジェクトが参照するGitHubリポジトリは、**Vercel管理画面（Git Integration）側の設定**。GitHub上でリポジトリを改名すると、GitHub App（Vercel連携）へ `repository` の rename イベントが送られ、**通常はVercel側の接続が自動的に新名へ更新される**。
- **確認不能（コードからは判断できない）**: Vercel管理画面の実状態。改名後、Vercelダッシュボードの Project → Settings → Git で接続先リポジトリが新名になっているか、直近のプッシュでデプロイがトリガーされるかを目視確認すること（§4）。

### 2-2. Ubuntuサーバー上のチェックアウト（`~/shift-pilot-ai`）
- サーバーには `/home/sigmaris/shift-pilot-ai/` にチェックアウトが存在する（`docs/infrastructure.md`、`docs/sigmaris/self_awareness_report.md:771` の `sigmaris@sigmaris:~/shift-pilot-ai$` プロンプト、`apply_migration.py` のパス等から確認）。
- **`git remote`（origin URL）**: 旧URL `https://github.com/uthuyomi/shift-pilot-ai` のままでも、GitHubの恒久リダイレクトにより `git pull`/`git push` は動作継続する。**必須ではないが、`git remote set-url origin https://github.com/uthuyomi/<新名>.git` で明示更新するのが安全**（将来、旧名で別リポジトリが作られた場合の誤接続を防ぐ）。
- **フォルダ名 `~/shift-pilot-ai` 自体**: 依頼書によりスコープ外（変更しない）。GitHubリポジトリ名を変えてもこのフォルダ名は自動では変わらず、変える必要もない。ただし §1-C の通り、`apply_migration.py` の shebang 等がこのフォルダパスに依存している点は記録しておく（フォルダ名を変えるなら別途追従が必要だが、今回は対象外）。

### 2-3. Cloudflare Tunnel・その他ネットワーク
- **リポジトリ名への依存は無い。** `docs/cloudflare-tunnel.md` によれば、Tunnelは `api.sigmaris.jp → Cloudflare Tunnel → localhost:8000（FastAPI）` を公開するのみで、設定（`/etc/cloudflared/config.yml`、トンネル名 `sigmaris`、ドメイン `sigmaris.jp`）は**GitHubリポジトリ名と無関係**。
- Tailscale（管理SSH）・ドメイン（onamae.com登録、Cloudflare NS）も同様にリポジトリ名非依存。
- **結論**: Cloudflare Tunnel・ネットワーク周りは**リポジトリ名変更による追従不要**。

### 2-4. インフラ影響まとめ

| 対象 | リポジトリ名変更の影響 | 追従の要否 |
|---|---|---|
| Vercel（Git連携） | GitHub App経由で自動追従が期待できる | 目視確認のみ（自動更新されるはず） |
| サーバー `git remote` | 旧URLでも動作継続（リダイレクト） | 推奨（`set-url` で更新） |
| サーバーのフォルダ名 | 変わらない／変える必要なし | 対象外（スコープ外） |
| `apply_migration.py` shebang | フォルダ名依存（リポジトリ名非依存） | 対象外（フォルダ名を変えない限り不要） |
| Cloudflare Tunnel | 影響なし | 不要 |
| Tailscale／ドメイン | 影響なし | 不要 |
| `SIGMARIS_PR_GITHUB_REPO`（`.env` 値） | 自己改良PRの宛先。旧名でも当面動くが更新推奨 | 推奨（運用者が `.env` を更新） |

---

## 3. ドキュメント内の記述（一覧・更新可否の提案）

以下はコードの動作には影響しない。**一貫性のための更新候補**として提示する（更新は任意）。文字列は概ね「サーバーのチェックアウトパス例」か「git clone 先の例示パス」。

| ファイル | 該当内容（例） | 更新提案 |
|---|---|---|
| `README.md` / `README_ja.md` | 製品名「ShiftPilotAI」中心の説明。GitHubトピック案あり。**クローンURLの直書きは無し** | ブランド刷新の一環で将来更新（リポジトリ名変更"必須"ではない）。優先度・低 |
| `wearos/README.md:50` | `cd /path/to/shift-pilot-ai/backend` | 例示パス。更新任意（`/path/to/<新名>` 等）。優先度・低 |
| `docs/sigmaris/self_awareness_report.md:771` | `sigmaris@sigmaris:~/shift-pilot-ai$ ...`（実行ログの引用） | **過去の実行ログの引用**。改変すると記録の正確性を損なうため**そのまま保持推奨**（更新しない） |
| `docs/sigmaris/cli_chat_investigation.md`（58,374,375,408,434,459行 等） | `~/shift-pilot-ai`・`/home/sigmaris/shift-pilot-ai/...` の運用手順 | サーバーフォルダ名（スコープ外）に対応する記述。フォルダ名を変えない限り**現状のまま正しい**。更新不要 |
| `docs/sigmaris/phase_a3_report.md:119` / `phase_a4_report.md:91` | `cd /path/to/shift-pilot-ai` | 過去レポートの例示。**歴史的記録として保持推奨**（更新しない） |
| `docs/sigmaris/incident_shiftpilotai_naming_report.md`（12,22,156,165,196行 等） | `shift-pilot-ai`/`shiftpilotai_backend` を"名残"として言及 | **意図的な記録**。更新不要（むしろ経緯として残す） |
| `docs/sigmaris/phase_h_report.md:544`, `phase_ba4_report.md`, `temporal_layer_report.md`, `bug_inventory.md`, `phase_b8_report.md`, `phase_b14_report.md`, `incident_response_latency_investigation.md`, `incident_free_limit_removal_report.md` | ブランド名／パス／確認マーカーへの言及 | 過去レポートの記録。**歴史的記録として保持推奨** |
| `map.md`, `docs/README.md`, `docs/operations/README.md`, `docs/requirements/README.md`, `docs/decisions/README.md`, `docs/design/README.md`, `docs/design/chat-google-tools.md`, `docs/design/chat-thread-persistence.md` | ブランド名／確認マーカー言及 | ブランド課題（別タスク）。リポジトリ名変更では更新不要 |

**ドキュメント方針の提案**:
- **過去のフェーズレポート・インシデントレポート・実行ログは改変しない**（記録の正確性を優先）。
- 更新するとすれば「現役の入口ドキュメント」（`README`・`wearos/README` の例示パス）に限定し、かつ**ブランド全体の改名タスクとまとめて**行うのが効率的。リポジトリ名変更だけを理由に一斉置換する必要はない。

---

## 4. 変更後の確認手順（提案）

リポジトリ名を（運用者がGitHub上で）変更した**後**に、正常動作を確かめる手順。

### 4-1. GitHub本体
1. ブラウザで旧URL `https://github.com/uthuyomi/shift-pilot-ai` を開き、**新URLへリダイレクトされる**ことを確認。
2. 新URL `https://github.com/uthuyomi/<新名>` が表示され、コミット履歴・ブランチが揃っていることを確認。

### 4-2. ローカルPC
3. `git remote -v` で現状を確認 → `git fetch` が成功する（旧URLのままでもリダイレクトで通る）ことを確認。
4. 推奨: `git remote set-url origin https://github.com/uthuyomi/<新名>.git` → 再度 `git fetch`／`git push`（ダミーの小コミットや `--dry-run`）で疎通確認。

### 4-3. Ubuntuサーバー（Tailscale経由でSSH）
5. `cd ~/shift-pilot-ai && git remote -v && git pull` が成功することを確認（旧URLでも通る）。
6. 推奨: `git remote set-url origin https://github.com/uthuyomi/<新名>.git` → `git pull` で再確認。
7. FastAPIの稼働確認: `systemctl status <uvicornのサービス>`（またはプロセス確認 `ss -tulpn | grep 8000`）、`curl -s http://localhost:8000/health` が `{"status":"ok",...}` を返す。
8. Cloudflare Tunnel経由の外部疎通: `curl -s https://api.sigmaris.jp/health` が同上を返す（リポジトリ名変更の影響を受けないはずだが、念のため）。

### 4-4. Vercel
9. Vercelダッシュボード → 対象プロジェクト → Settings → Git で、接続先リポジトリが**新名**になっていることを確認。
10. `main` へ小さなコミットをpushし、**Vercelのデプロイが自動トリガーされる**ことを確認。デプロイ後、フロントエンド（`/chat` 等）が正常表示されること、`/api/backend/health` 等でバックエンド疎通が取れることを確認。
11. （もし自動追従されていなければ）Vercelで一度Gitを切断→新名で再接続する。

### 4-5. 自己改良PR（任意・使う場合のみ）
12. `.env` の `SIGMARIS_PR_GITHUB_REPO` を新 `owner/repo` に更新後、`backend/scripts/review_diff_proposals.py` 等で承認フローを走らせ、`github_pr_publisher.py` が**新リポジトリにPRを作成できる**ことを確認（旧名でもGitHub APIリダイレクトで通る可能性はあるが、明示更新を推奨）。

### 4-6. 回帰確認（全体）
13. チャット（`/chat`）で1往復の会話が成立すること（フロント→Vercel→Cloudflare→FastAPI の一連が生きていることの総合確認）。
14. `git log`／CIが無いこと（§1-E）を踏まえ、**CI起因の追従漏れは無い**ことを再確認。

---

## 5. 推奨される実施順序

GitHub側の改名を起点に、追従を最小リスクで行う順序。**「必須」ではなく「一貫性・事故防止のための推奨」**である点に留意（GitHubリダイレクトにより多くは旧名のままでも当面動く）。

1. **事前確認（改名前）**
   - 本ドキュメントの §1〜§3 を運用者と共有。
   - `.env` の `SIGMARIS_PR_GITHUB_REPO` の現在値を控える（自己改良PRを使っている場合）。
   - 進行中の作業（未マージのブランチ／PR）が無い、または退避済みであることを確認。

2. **GitHub上でリポジトリ名を変更（運用者が実施）**
   - `shift-pilot-ai` → `sigmaris`（または近い名前）へ。
   - GitHubが旧URL→新URLのリダイレクトを自動設定する。**旧名で新規リポジトリを作らないこと**（リダイレクトが失われるため）。

3. **直後の疎通確認（何も追従しない状態で）**
   - §4-1・§4-2の3・§4-3の5 を実施し、**旧URLのままでも動く**ことを確認（＝緊急の追従は不要という安全確認）。

4. **git remote の更新（ローカルPC → サーバーの順）**
   - §4-2の4 → §4-3の6。それぞれ `set-url` 後に `fetch`/`pull` で確認。

5. **Vercelの確認・（必要なら）再接続**
   - §4-4。自動追従されているのが通常。されていなければ再接続。

6. **`.env`（`SIGMARIS_PR_GITHUB_REPO`）の更新（自己改良PRを使う場合のみ）**
   - §4-5。運用者がサーバーの `.env` を更新し、サービス再起動が必要なら再起動。

7. **ドキュメントの一貫性更新（任意・後回し可）**
   - §3の方針に従い、**現役の入口ドキュメントのみ**、必要ならブランド改名タスクとまとめて更新。過去レポート・実行ログは改変しない。

8. **総合回帰確認**
   - §4-6。チャット1往復・デプロイ・health を通しで確認。

**タイミングの原則**: 2（改名）と 4〜6（追従）は**同日中に連続実施が望ましい**が、リダイレクトがあるため厳密な即時性は不要。7（ドキュメント）は急がなくてよい。

---

## 6. 付録: 本調査で「対象外」と判断した主な項目（再掲・混同防止）

| 項目 | 判断 | 理由 |
|---|---|---|
| Supabaseプロジェクト名・テーブル名 | 対象外 | 依頼書で除外。DB変更は高リスク |
| 環境変数の**名前** | 対象外 | 依頼書で除外（`SIGMARIS_PR_GITHUB_REPO` は"値"のみ追従推奨） |
| サーバー/ローカルの**フォルダ名**（`~/shift-pilot-ai`） | 対象外 | 依頼書で除外。リポジトリ名変更で自動では変わらない |
| `backend/fly.toml` の `app = 'shift-pilot-ai'` | 対象外 | Fly.io側の独立リソース名。GitHubリポジトリ名と無関係、かつFlyはレガシー |
| npm/Pythonパッケージ名（`shiftpilotai*`） | 対象外 | パッケージ名（非公開）。ブランド課題であり、リポジトリスラッグとは別 |
| 製品ブランド名「ShiftPilotAI」全般 | 別課題 | `incident_shiftpilotai_naming_report.md` が扱う独立タスク |
| `chat_prompts.py` の禁止名ルール（"shift-pilot-ai"を名乗らせない） | **保持** | 意図的なガード。削除・変更してはならない |

---

## 7. 調査上の制約

- 本調査は作業ツリー（`02519ba`）の静的読み取りのみ。**以下は確認不能**:
  - GitHub管理画面の実状態、リダイレクト設定。
  - Vercel管理画面のGit連携設定。
  - Ubuntuサーバー上の実際の `git remote` 出力、`.env` の `SIGMARIS_PR_GITHUB_REPO` 実値、systemdユニットの有無（リポジトリ内に無く、コードからは判断できない）。
  - `.env`・秘密情報の実値（本ドキュメントには一切含めない）。
- GitHubのリダイレクト挙動は一般的仕様に基づく記述であり、実際の挙動は改名後に §4 で実地確認すること。

---

*本ドキュメントは読み取り専用の調査成果物であり、コード・設定・GitHubリポジトリ名のいずれにも変更を加えていない。*
