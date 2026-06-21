from __future__ import annotations

# 役割: 監査ログのコンテキスト情報を表すデータクラスを提供する。

from dataclasses import dataclass


@dataclass
class AuditContext:
    action: str
    actor_type: str
    actor_ref: str | None = None
    reason: str | None = None

    def to_jsonb(self) -> dict[str, str | None]:
        return {
            "action": self.action,
            "actor_type": self.actor_type,
            "actor_ref": self.actor_ref,
            "reason": self.reason,
        }
