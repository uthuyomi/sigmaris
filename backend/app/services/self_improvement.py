from __future__ import annotations

import base64
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import httpx

from app.config import settings
from app.services.local_llm import LLMRouter, TaskType, get_llm_router
from app.services.self_model import get_self_model
from app.services.supabase_rest import _get_client, _require_supabase_config, rest_select
from app.services.proactive.jwt_manager import get_sigmaris_jwt

logger = logging.getLogger(__name__)

ProposalType = Literal["persona", "code"]

# Files that must never be modified — absolute constraint.
_BLOCKED_PATTERNS = [
    r"\.env",
    r"\.env\.",
    r"env\.example",
    r"secret",
    r"credential",
    r"password",
    r"\.pem$",
    r"\.key$",
    r"\.p12$",
    r"\.pfx$",
    r"auth\.py$",
    r"jwt_manager\.py$",
]


@dataclass
class ImprovementProposal:
    proposal_type: ProposalType
    target_file: str
    description: str
    proposed_change: str
    reasoning: str
    safe: bool = True
    blocked_reason: str = ""


@dataclass
class ApplyResult:
    ok: bool
    proposal_type: ProposalType
    action: str
    detail: str = ""
    error: str = ""


def _is_blocked(file_path: str) -> str:
    """Return a non-empty reason string if the file is forbidden, else ''."""
    normalized = file_path.replace("\\", "/").lower()
    for pattern in _BLOCKED_PATTERNS:
        if re.search(pattern, normalized):
            return f"Target file '{file_path}' matches blocked pattern '{pattern}'."
    return ""


def _resolve_persona_path() -> Path:
    base = Path(__file__).resolve().parent.parent.parent.parent
    raw = settings.sigmaris_persona_path
    candidate = (Path(__file__).resolve().parent.parent / raw).resolve()
    if candidate.exists():
        return candidate
    return (base / "docs" / "persona.md").resolve()


class SelfImprovementAgent:
    def __init__(self, router: LLMRouter | None = None) -> None:
        self._router = router or get_llm_router()

    # ─── analyze ─────────────────────────────────────────────────────────────

    async def analyze(self) -> list[ImprovementProposal]:
        """
        Analyzes audit logs and the current self-model to generate improvement
        proposals. Returns a list of ImprovementProposal objects.
        """
        if not settings.self_improvement_enabled:
            logger.info("SelfImprovementAgent: disabled via SELF_IMPROVEMENT_ENABLED")
            return []

        jwt = await get_sigmaris_jwt()

        since = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        logs: list[dict] = await rest_select(jwt, "agent_invocation_audit_logs", {
            "created_at": f"gte.{since}",
            "order": "created_at.desc",
            "limit": "30",
        }) or []

        self_model = await get_self_model()
        current_identity = (self_model or {}).get("identity_statement", "")
        current_patterns = (self_model or {}).get("observed_patterns", [])

        persona_path = _resolve_persona_path()
        persona_snippet = ""
        if persona_path.exists():
            content = persona_path.read_text(encoding="utf-8")
            persona_snippet = content[:2000]

        log_lines = []
        for lg in logs[:20]:
            status = lg.get("status", "?")
            caller = lg.get("caller_agent_id", "?")
            reason = (lg.get("reason") or "")[:60]
            ts = (lg.get("created_at") or "")[:16]
            dur = lg.get("duration_ms")
            log_lines.append(f"- [{ts}] {caller} → {status} {dur}ms | {reason}")
        log_summary = "\n".join(log_lines) or "（ログなし）"

        system = (
            "あなたはシグマリス（AIアシスタント）の改良エンジンです。"
            "行動ログと現在の自己モデルを分析して具体的な改善提案を生成します。"
            "必ず有効なJSONのみを返してください。"
        )
        user = f"""## 現在の自己認識
{current_identity or '（未設定）'}

## 観察パターン
{json.dumps(current_patterns, ensure_ascii=False, indent=2)}

## persona.md（先頭2000文字）
{persona_snippet}

## 直近48時間の行動ログ（{len(logs)}件）
{log_summary}

---
上記を踏まえて次のJSON配列を出力してください（0〜3件）:
[
  {{
    "proposal_type": "persona" または "code",
    "target_file": "対象ファイルのパス（例: docs/persona.md）",
    "description": "改善内容の要約（1文）",
    "proposed_change": "具体的な変更内容（persona.mdなら追記・修正テキスト、codeならdiff風の説明）",
    "reasoning": "なぜこの改善が必要か（2〜3文）"
  }}
]
改善不要なら空リスト []。認証情報・セキュリティ設定・.envには絶対に触れないこと。"""

        raw = await self._router.chat(
            TaskType.SELF_REFLECT,
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.3,
            max_tokens=1200,
            json_mode=True,
        )

        try:
            parsed = json.loads(raw)
            items = parsed if isinstance(parsed, list) else parsed.get("proposals", [])
        except json.JSONDecodeError:
            logger.error("SelfImprovementAgent.analyze: invalid JSON: %s", raw[:200])
            return []

        proposals: list[ImprovementProposal] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            target = str(item.get("target_file", ""))
            blocked = _is_blocked(target)
            proposals.append(ImprovementProposal(
                proposal_type=item.get("proposal_type", "code"),
                target_file=target,
                description=str(item.get("description", "")),
                proposed_change=str(item.get("proposed_change", "")),
                reasoning=str(item.get("reasoning", "")),
                safe=not blocked,
                blocked_reason=blocked,
            ))

        return proposals

    # ─── apply ───────────────────────────────────────────────────────────────

    async def apply_improvement(self, proposal: ImprovementProposal) -> ApplyResult:
        """
        Applies a single proposal:
        - persona type → writes persona.md directly
        - code type    → creates a GitHub PR (never pushes directly)
        Blocked proposals are rejected immediately.
        """
        if not settings.self_improvement_enabled:
            return ApplyResult(
                ok=False,
                proposal_type=proposal.proposal_type,
                action="rejected",
                error="SELF_IMPROVEMENT_ENABLED is false.",
            )

        if not proposal.safe:
            logger.warning("SelfImprovementAgent: blocked proposal: %s", proposal.blocked_reason)
            return ApplyResult(
                ok=False,
                proposal_type=proposal.proposal_type,
                action="blocked",
                error=proposal.blocked_reason,
            )

        if proposal.proposal_type == "persona":
            return await self._apply_persona(proposal)

        return await self._create_github_pr(proposal)

    # ─── persona update ───────────────────────────────────────────────────────

    async def _apply_persona(self, proposal: ImprovementProposal) -> ApplyResult:
        persona_path = _resolve_persona_path()
        if not persona_path.exists():
            return ApplyResult(
                ok=False,
                proposal_type="persona",
                action="failed",
                error=f"persona.md not found at {persona_path}",
            )

        existing = persona_path.read_text(encoding="utf-8")
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        appended = (
            f"\n\n---\n<!-- 自己改良 {timestamp} -->\n"
            f"{proposal.proposed_change}\n"
        )
        persona_path.write_text(existing + appended, encoding="utf-8")
        logger.info("SelfImprovementAgent: updated persona.md — %s", proposal.description)
        return ApplyResult(
            ok=True,
            proposal_type="persona",
            action="persona_updated",
            detail=f"persona.md updated ({len(appended)} chars appended)",
        )

    # ─── GitHub PR ────────────────────────────────────────────────────────────

    async def _create_github_pr(self, proposal: ImprovementProposal) -> ApplyResult:
        token = settings.github_token
        repo = settings.github_repo
        if not token or not repo:
            return ApplyResult(
                ok=False,
                proposal_type="code",
                action="skipped",
                detail="GITHUB_TOKEN or GITHUB_REPO not configured — PR skipped.",
            )

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        api = "https://api.github.com"

        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
            # 1. Get default branch SHA
            r = await client.get(f"{api}/repos/{repo}", headers=headers)
            r.raise_for_status()
            default_branch = r.json()["default_branch"]

            r = await client.get(
                f"{api}/repos/{repo}/git/ref/heads/{default_branch}", headers=headers
            )
            r.raise_for_status()
            base_sha = r.json()["object"]["sha"]

            # 2. Create branch
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
            branch = f"sigmaris/self-improve-{timestamp}"
            r = await client.post(
                f"{api}/repos/{repo}/git/refs",
                headers=headers,
                json={"ref": f"refs/heads/{branch}", "sha": base_sha},
            )
            if r.status_code not in (200, 201, 422):
                r.raise_for_status()

            # 3. Get current file content (if exists) and update
            file_path = proposal.target_file.lstrip("/")
            file_sha: str | None = None
            current_content = ""
            r = await client.get(
                f"{api}/repos/{repo}/contents/{file_path}",
                headers=headers,
                params={"ref": branch},
            )
            if r.is_success:
                file_data = r.json()
                file_sha = file_data.get("sha")
                current_content = base64.b64decode(file_data["content"].replace("\n", "")).decode("utf-8")

            timestamp_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            new_content = (
                current_content
                + f"\n\n<!-- 自己改良提案 {timestamp_str} -->\n"
                + proposal.proposed_change
                + "\n"
            )
            encoded = base64.b64encode(new_content.encode("utf-8")).decode("ascii")

            put_body: dict[str, Any] = {
                "message": f"chore(sigmaris): {proposal.description[:72]}",
                "content": encoded,
                "branch": branch,
            }
            if file_sha:
                put_body["sha"] = file_sha

            r = await client.put(
                f"{api}/repos/{repo}/contents/{file_path}",
                headers=headers,
                json=put_body,
            )
            r.raise_for_status()

            # 4. Create PR
            r = await client.post(
                f"{api}/repos/{repo}/pulls",
                headers=headers,
                json={
                    "title": f"[Sigmaris自己改良] {proposal.description[:72]}",
                    "body": (
                        f"## 改善提案\n\n{proposal.description}\n\n"
                        f"## 理由\n\n{proposal.reasoning}\n\n"
                        f"## 変更内容\n\n```\n{proposal.proposed_change[:1000]}\n```\n\n"
                        f"*このPRはシグマリス自己改良エンジンによって自動生成されました。*"
                    ),
                    "head": branch,
                    "base": default_branch,
                },
            )
            r.raise_for_status()
            pr_url = r.json()["html_url"]
            logger.info("SelfImprovementAgent: PR created %s", pr_url)

        return ApplyResult(
            ok=True,
            proposal_type="code",
            action="pr_created",
            detail=pr_url,
        )
