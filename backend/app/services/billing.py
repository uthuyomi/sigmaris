from __future__ import annotations

from typing import Any

from app.config import settings
from app.services.supabase_rest import get_current_user, rest_select

ACTIVE_SUBSCRIPTION_STATUSES = {"active", "trialing"}


def _override_emails() -> set[str]:
    return {
        email.strip().lower()
        for email in (settings.pro_plan_override_emails or "").split(",")
        if email.strip()
    }


def _has_override_email(email: str | None) -> bool:
    return bool(email and email.strip().lower() in _override_emails())


def _pro_override_status() -> dict[str, Any]:
    return {
        "plan": "pro",
        "subscriptionStatus": "manual_override",
        "currentPeriodEnd": None,
        "cancelAtPeriodEnd": False,
    }


async def read_billing_status(jwt: str) -> dict[str, Any]:
    try:
        user = await get_current_user(jwt)
        if _has_override_email(user.get("email")):
            return _pro_override_status()
    except Exception:
        pass

    try:
        rows = await rest_select(
            jwt,
            "subscriptions",
            {
                "select": "status,current_period_end,cancel_at_period_end",
                "status": f"in.({','.join(ACTIVE_SUBSCRIPTION_STATUSES)})",
                "order": "current_period_end.desc",
                "limit": "1",
            },
        )
    except Exception:
        return {
            "plan": "free",
            "subscriptionStatus": None,
            "currentPeriodEnd": None,
            "cancelAtPeriodEnd": False,
        }

    subscription = rows[0] if rows else None
    status = subscription.get("status") if subscription else None
    return {
        "plan": "pro" if status in ACTIVE_SUBSCRIPTION_STATUSES else "free",
        "subscriptionStatus": status,
        "currentPeriodEnd": subscription.get("current_period_end") if subscription else None,
        "cancelAtPeriodEnd": bool(subscription.get("cancel_at_period_end")) if subscription else False,
    }


async def has_pro_plan(jwt: str) -> bool:
    return (await read_billing_status(jwt))["plan"] == "pro"
