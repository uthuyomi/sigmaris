from __future__ import annotations

from typing import Any

from app.services.supabase_rest import rest_select

ACTIVE_SUBSCRIPTION_STATUSES = {"active", "trialing"}


async def read_billing_status(jwt: str) -> dict[str, Any]:
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
