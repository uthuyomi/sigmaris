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

# ─── Actionable opsec detection (X_POST_OPSEC_FILTER_SPEC 層2) ─────────
# 方針: "攻撃に使える具体情報"だけを弾く。「自宅サーバーがある」「GPU型番」
# 「使ってるOS」レベルの単なる言及は一律ブロックしない(誤爆源＝D/Eの技術
# 発信を殺すため。本丸は層1で対処)。既存方針どおり正規表現/キーワードのみで、
# LLM には一切投げない(プライベート情報を外部送信しない)。パターンは後から
# 調整できるよう、名前付きの定数(ラベル, 正規表現)のリストで管理する。

# CGNAT 帯(100.64.0.0/10)。Tailscale 等の内部アドレスがここに入るため、
# 通常の IPv4(_IP_RE)とは別に明示して確実に捕捉する。
_CGNAT_RE = re.compile(
    r'\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.'
    r'(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.'
    r'(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b'
)

# 内部ホスト名(.local mDNS)。
_LOCAL_HOST_RE = re.compile(r'\b[A-Za-z0-9\-]{1,63}\.local\b', re.IGNORECASE)

# ポート番号(URL/ホスト文脈、または「ポート/port + 数字」)。単なる数字の
# 誤爆を避けるため、port という語か、host:port 形の :数字 のみを対象にする。
# 末尾は \b を使わない — 日本語では数字の直後に助詞(を/の 等、Unicode 上は
# \w)が続き "数字→日本語" が \w どうしで境界にならないため(電話番号 regex と
# 同じ既知の挙動)。代わりに (?!\d) で「これ以上数字が続かない」ことだけ課す。
_PORT_RE = re.compile(
    r'(?:ポート|port)\s*[:：]?\s*\d{2,5}(?!\d)'
    r'|(?<=[A-Za-z0-9\.\]])\:\d{2,5}(?!\d)',
    re.IGNORECASE,
)

# 語そのものが"具体的なネットワーク設定"を指すもの(単独ヒットでブロック)。
# 「ルータ」「SIM」「回線」のような一般語は含めない — それらは層1で記憶確認
# として除外され、単なる言及は誤爆源になるため層2では弾かない。
_NET_CONFIG_TERMS: tuple[str, ...] = (
    "ポート開放",
    "ポートフォワーディング",
    "ポートフォワード",
    "port forwarding",
    "port forward",
    "ddns",
    "グローバルip",
    "固定ip",
    "静的ip",
    "static ip",
    "ssid",
    "vpnエンドポイント",
    "vpn endpoint",
    "wireguard",
    "upnp",
)
_NET_CONFIG_RE = re.compile(
    "|".join(re.escape(term) for term in _NET_CONFIG_TERMS),
    re.IGNORECASE,
)

# "文脈依存"の語 — これ単体では D/E の正当な技術発信でも出うるため一律には
# 弾かず、具体的な接地情報(IP/CGNAT/内部ホスト名/ポート)が同じ文に伴うとき
# だけブロックする(「Tailscale でリモート開発してる」等の単なる言及は誤爆に
# しない、という層2の方針)。
_CONTEXT_DEPENDENT_TERMS: tuple[str, ...] = (
    "tailscale",
    "外部公開",
    "外部からアクセス",
)
_CONTEXT_DEPENDENT_RE = re.compile(
    "|".join(re.escape(term) for term in _CONTEXT_DEPENDENT_TERMS),
    re.IGNORECASE,
)


def _detect_actionable_opsec(text: str) -> list[str]:
    """攻撃に使える actionable な opsec 情報だけを検出する。ヒットしたラベル
    のリストを返す(空なら検出なし)。"""
    detected: list[str] = []
    has_ip = bool(_CGNAT_RE.search(text))
    has_local = bool(_LOCAL_HOST_RE.search(text))
    has_port = bool(_PORT_RE.search(text))
    if has_ip:
        detected.append("内部IP(CGNAT)")
    if has_local:
        detected.append("内部ホスト名(.local)")
    if has_port:
        detected.append("ポート番号")
    if _NET_CONFIG_RE.search(text):
        detected.append("具体的なネットワーク設定")
    # 文脈依存の語は、具体的な接地情報(IP/ホスト/ポート)を伴うときのみ
    # actionable(外部公開の操作手順/トポロジ)としてブロックする。
    if _CONTEXT_DEPENDENT_RE.search(text) and (has_ip or has_local or has_port):
        detected.append("外部公開の操作手順/トポロジ")
    return detected


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
    - Personal names ("海星", "安崎", "安崎海星"):
        Name conversion (→ @Oyasu1999) is handled upstream in x_post_generator
        before this check runs. Blocking names here would be redundant and would
        false-positive on mentions of the converted @handle text.
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

    # X_POST_OPSEC_FILTER_SPEC 層2: actionable な opsec 情報(CGNAT/内部
    # ホスト名/ポート/具体ネット設定・外部公開手順)を追加検出する。
    detected.extend(_detect_actionable_opsec(text))

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
