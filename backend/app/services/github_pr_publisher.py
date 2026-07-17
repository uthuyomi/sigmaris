# 役割: Phase F-3「承認フロー、及び、承認後のプルリクエスト作成」——
# 人間が明示的に承認した、1件のコード差分提案を、実際にGitHub上の新規
# ブランチへコミットし、プルリクエストを作成する。
#
# 【このファイルだけが持つ、特別な性質】
# **本モジュールは、このコードベース全体の中で唯一、GitHubへの書き込み
# API呼び出し(ブランチ作成・コミット・PR作成)を行うモジュールである。**
# diff_approval.py::approve_diff_proposal()の、承認確定後の経路からのみ
# 呼び出される——他のいかなるRunner・スケジューラ・APIエンドポイントも、
# 本モジュールの publish_approved_diff() を直接呼び出さない
# (import グラフの静的証明、テスト参照)。
#
# 【絶対原則】
# 本モジュールは、GitHubのREST API(https://api.github.com)への、
# httpx経由のHTTPリクエストのみを行う。**ローカルのgitコマンド
# (`subprocess`・`git`)は、一切使用しない。** ローカルのワーキング
# ツリー・mainブランチには、指一本触れない——実際のコミットは、常に
# GitHubサーバー上の新規ブランチに対してのみ発生する(F-1/F-2で確立
# した「ローカルgit状態のSHA-256ハッシュ比較」証明パターンが、F-3でも
# 引き続き成立する理由、レポート参照)。
#
# 【旧self_improvement.py(削除済み、git履歴 bea3ada~1)との違い】
# 1. 旧実装は、統一diffを一切適用せず、proposed_changeのテキストを
#    ファイル末尾にHTMLコメット付きで追記するだけだった。本モジュールは
#    diff_patch.apply_unified_diff()で、実際の統一diffを、対象ファイルの
#    現在の内容(承認時点ではなく、PR作成の直前にGitHubから取得した
#    最新の内容)に対して適用する。
# 2. ブランチ命名を `sigmaris/self-improve-*` から `sigmaris/f3-approved-*`
#    へ変更した——削除済みの旧仕組みと、新しい正式な承認フローの成果物を、
#    運用者が一目で区別できるようにするための判断(レポート参照)。
# 3. 専用の書き込みクレデンシャル(settings.sigmaris_pr_github_token /
#    sigmaris_pr_github_repo)を使う——research_agent.py用の読み取り専用
#    github_tokenとは、意図的に完全に分離した(config.py参照)。

from __future__ import annotations

import base64
import logging
import posixpath
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from app.config import settings
from app.services.code_diff_generation import check_diff_safety
from app.services.diff_patch import DiffApplyError, apply_unified_diff

logger = logging.getLogger(__name__)

_API_BASE = "https://api.github.com"

# 削除済み旧self_improvement.pyから踏襲した、1日あたりのPR作成上限
# (判断根拠: 暴走防止の最後の砦として、旧実装が持っていた値をそのまま
# 引き継いだ——新たな数値を独断で選ばない)。
_MAX_DAILY_PRS = 3

# 新しいブランチ命名規則(旧 `sigmaris/self-improve-*` から変更、
# モジュールdocstring参照)。
_BRANCH_PREFIX = "sigmaris/f3-approved-"


@dataclass
class PrPublishResult:
    status: str  # "pr_created" | "skipped_not_configured" | "blocked" | "skipped_daily_limit" | "failed"
    pr_url: str = ""
    branch: str = ""
    error: str = ""
    detail: str = ""


def _safe_relative_path(raw: str) -> tuple[str, str]:
    """パストラバーサルを防ぐ、防御的な正規化(旧self_improvement.py::
    _safe_file_path()と同じ考え方)。戻り値は (正規化済みパス, エラー文字列)。
    """
    normalized = posixpath.normpath(raw.lstrip("/"))
    if normalized.startswith("..") or normalized == "..":
        return "", f"パストラバーサルの兆候を検知した: {raw!r}"
    return normalized, ""


async def publish_approved_diff(proposal: dict[str, Any]) -> PrPublishResult:
    """承認済み(review_status="approved")の1件の差分提案を、実際に
    GitHub上のブランチ・コミット・プルリクエストへ変換する。

    **呼び出し前提**: proposalは、diff_approval.py側で、承認確定
    直前・直後の2回、check_diff_safety()による安全性チェックを既に
    通過している。本関数は、それに加えて3回目の防御的チェックを、
    実際のGitHub書き込みの直前にも行う(多層防御、独断の判断根拠は
    レポート参照)。
    """
    token = settings.sigmaris_pr_github_token
    repo = settings.sigmaris_pr_github_repo
    if not token or not repo:
        return PrPublishResult(
            status="skipped_not_configured",
            detail="SIGMARIS_PR_GITHUB_TOKEN または SIGMARIS_PR_GITHUB_REPO が未設定のため、PR作成をスキップした。",
        )

    target_file = str(proposal.get("target_file") or "")
    diff_text = str(proposal.get("diff_text") or "")
    title = str(proposal.get("title") or "")
    proposal_id = str(proposal.get("id") or "unknown")

    normalized_path, path_error = _safe_relative_path(target_file)
    if path_error:
        logger.warning("github_pr_publisher: unsafe target_file — %s", path_error)
        return PrPublishResult(status="blocked", error=path_error)

    # 3回目の防御的チェック(多層防御、モジュールdocstring参照)
    safety = check_diff_safety(diff_text, expected_target_file=normalized_path)
    if safety.status != "passed":
        logger.warning("github_pr_publisher: safety re-check failed at publish time — %s", safety.reason)
        return PrPublishResult(status="blocked", error=safety.reason)

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
            # 1. デフォルトブランチと、その先端SHAを取得
            r = await client.get(f"{_API_BASE}/repos/{repo}", headers=headers)
            r.raise_for_status()
            default_branch = r.json()["default_branch"]

            r = await client.get(f"{_API_BASE}/repos/{repo}/git/ref/heads/{default_branch}", headers=headers)
            r.raise_for_status()
            base_sha = r.json()["object"]["sha"]

            # 2. 1日あたりのPR作成上限を確認(暴走防止の最後の砦)
            today_prefix = datetime.now(UTC).strftime("%Y%m%d")
            r_branches = await client.get(
                f"{_API_BASE}/repos/{repo}/branches", headers=headers, params={"per_page": "100"}
            )
            if r_branches.is_success:
                existing_today = sum(
                    1
                    for b in r_branches.json()
                    if b.get("name", "").startswith(f"{_BRANCH_PREFIX}{today_prefix}")
                )
                if existing_today >= _MAX_DAILY_PRS:
                    logger.info(
                        "github_pr_publisher: daily PR limit reached (%d/%d) — skipping",
                        existing_today, _MAX_DAILY_PRS,
                    )
                    return PrPublishResult(
                        status="skipped_daily_limit",
                        detail=f"1日あたりのPR作成上限({_MAX_DAILY_PRS})に達したため、作成をスキップした。",
                    )

            # 3. 新規ブランチを作成
            timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
            short_id = proposal_id.replace("-", "")[:8] or "noid"
            branch = f"{_BRANCH_PREFIX}{today_prefix}-{short_id}-{timestamp}"
            r = await client.post(
                f"{_API_BASE}/repos/{repo}/git/refs",
                headers=headers,
                json={"ref": f"refs/heads/{branch}", "sha": base_sha},
            )
            if r.status_code not in (200, 201, 422):
                r.raise_for_status()

            # 4. 対象ファイルの現在の内容(承認時点ではなく、今この瞬間の
            # GitHub上の内容)を取得し、diffを実際に適用する
            r = await client.get(
                f"{_API_BASE}/repos/{repo}/contents/{normalized_path}", headers=headers, params={"ref": branch}
            )
            r.raise_for_status()
            file_data = r.json()
            file_sha = file_data.get("sha")
            current_content = base64.b64decode(file_data["content"].replace("\n", "")).decode("utf-8")

            try:
                patched_content = apply_unified_diff(current_content, diff_text)
            except DiffApplyError as exc:
                logger.warning("github_pr_publisher: diff no longer applies cleanly — %s", exc)
                return PrPublishResult(
                    status="failed",
                    branch=branch,
                    error=f"対象ファイルの内容が変化しており、差分を適用できなかった: {exc}",
                )

            encoded = base64.b64encode(patched_content.encode("utf-8")).decode("ascii")
            r = await client.put(
                f"{_API_BASE}/repos/{repo}/contents/{normalized_path}",
                headers=headers,
                json={
                    "message": f"chore(sigmaris): {title[:72]}" if title else "chore(sigmaris): approved code diff",
                    "content": encoded,
                    "branch": branch,
                    "sha": file_sha,
                },
            )
            r.raise_for_status()

            # 5. プルリクエストを作成(mainへの直接の影響は、ここには
            # 一切無い——新規ブランチとPRの作成のみ。mainへのマージは、
            # 依然として運用者が、通常のGitHub操作で行う)
            r = await client.post(
                f"{_API_BASE}/repos/{repo}/pulls",
                headers=headers,
                json={
                    "title": f"[Sigmaris承認済み改良提案] {title[:72]}" if title else "[Sigmaris承認済み改良提案]",
                    "body": (
                        f"## 改良提案\n\n{title}\n\n"
                        f"## 対象ファイル\n\n`{normalized_path}`\n\n"
                        f"## 適用された差分\n\n```diff\n{diff_text[:2000]}\n```\n\n"
                        f"---\n*このPRは、Sigmarisの自己改善パイプライン(Phase D〜F)により、"
                        f"海星さんの明示的な承認を経て作成されました。マージ判断は、依然として"
                        f"海星さん自身が、通常のGitHub操作で行います。*"
                    ),
                    "head": branch,
                    "base": default_branch,
                },
            )
            r.raise_for_status()
            pr_url = r.json()["html_url"]
    except httpx.HTTPStatusError as exc:
        logger.exception("github_pr_publisher: GitHub API call failed")
        return PrPublishResult(status="failed", error=f"GitHub API エラー: {exc}")
    except Exception as exc:
        logger.exception("github_pr_publisher: unexpected failure")
        return PrPublishResult(status="failed", error=f"予期しないエラー: {exc}")

    logger.info("github_pr_publisher: PR created %s", pr_url)
    return PrPublishResult(status="pr_created", pr_url=pr_url, branch=branch)
