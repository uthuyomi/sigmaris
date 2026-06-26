from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Email addresses
_EMAIL_RE = re.compile(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b')

# Japanese phone numbers: 090-XXXX-XXXX, 03-XXXX-XXXX, +81-XX-XXXX-XXXX
_PHONE_RE = re.compile(r'(?:\+81|0)\d{1,4}[\-\s]?\d{2,4}[\-\s]?\d{4}\b')

# Address detail: 丁目+番+号, 番地, 号室
# Excludes prefecture/city level ("札幌市" etc.) — only block street-level detail
_ADDRESS_DETAIL_RE = re.compile(
    r'\d+丁目\d+番(?:\d+号)?'
    r'|\d+番地\d*号?'
    r'|\d+号室'
)

# Specific yen amounts that could reveal income or large personal expenses.
# Allowed: "100円ショップ", "数百円" (vague).
# Blocked: "30万円", "¥50,000", "50000円", "50,000円".
_MONEY_RE = re.compile(
    r'(?<!\d)\d+万円'           # X万円 (e.g. 30万円)
    r'|\d+(?:[,，]\d{3})+円'    # formatted: 50,000円
    r'|\d{5,}円'                 # 5+ digit raw: 50000円
    r'|¥\d{4,}(?:[,，]\d{3})*'  # ¥10000
)

# Credential-like strings (password=, token=, api_key=, etc.)
_CREDENTIAL_RE = re.compile(
    r'(?:password|passwd|token|secret|api[_\-]?key|pwd)[\s=:]+\S{4,}',
    re.IGNORECASE,
)

# IPv4 addresses
_IP_RE = re.compile(
    r'\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}'
    r'(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b'
)


def filter_private_info(text: str) -> tuple[bool, list[str]]:
    """Check tweet text for private information.

    Returns (safe, detected_categories).
    safe=True → no private info found, post can proceed.

    Intentionally regex-only — no LLM call so private data is never sent externally.

    NOT blocked (too broad or acceptable public info):
    - Prefecture/city level addresses ("札幌市", "渋谷区")
    - General job titles ("Webエンジニア")
    - Hobbies and preferences
    - SNS handles (@sigmarisai)
    - Surname-only or given-name-only (no full name detection without data)
    """
    detected: list[str] = []

    if _EMAIL_RE.search(text):
        detected.append("メールアドレス")

    if _PHONE_RE.search(text):
        detected.append("電話番号")

    if _ADDRESS_DETAIL_RE.search(text):
        detected.append("番地・部屋番号")

    if _MONEY_RE.search(text):
        detected.append("金額の具体的な数字")

    if _CREDENTIAL_RE.search(text):
        detected.append("パスワード・トークン")

    if _IP_RE.search(text):
        detected.append("IPアドレス")

    return len(detected) == 0, detected


async def filter_private_facts(text: str, jwt: str) -> tuple[bool, list[str]]:
    """Check tweet text against the user's private fact values stored in memory.

    Fetches all user_fact_items where privacy_level='private' and checks whether
    any of those values appear verbatim in the tweet text.

    Returns (safe, blocked_reasons).
    safe=True → none of the private values were found in text.

    Requires migration 202606270019_trend_memory to be applied (adds privacy_level
    column). Fails open: returns (True, []) on any error so that a DB issue never
    blocks X posting.
    """
    try:
        from app.services.supabase_rest import rest_select  # noqa: PLC0415
        rows = await rest_select(jwt, "user_fact_items", {
            "select": "category,key,value",
            "privacy_level": "eq.private",
            "is_deleted": "eq.false",
            "value": "not.is.null",
        })
        if not isinstance(rows, list):
            return True, []
    except Exception:
        logger.warning("x_privacy_filter: private-facts DB fetch failed (failing open)")
        return True, []

    blocked: list[str] = []
    text_lower = text.lower()

    for row in rows:
        value = row.get("value")
        if not isinstance(value, str) or len(value) < 4:
            # Skip very short values (single digits, single chars) to avoid false positives
            continue
        if value.lower() in text_lower:
            label = f"{row.get('category')}/{row.get('key')}"
            blocked.append(label)
            logger.warning(
                "x_privacy_filter: private fact value matched in tweet: %s", label
            )

    return len(blocked) == 0, blocked
