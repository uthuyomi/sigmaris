#!/usr/bin/env python3
"""
Seed Sigmaris fact memory with initial user data.

Usage:
    cd backend
    NEXT_PUBLIC_SUPABASE_URL=https://xxx.supabase.co \
    SUPABASE_SERVICE_ROLE_KEY=eyJ... \
    SIGMARIS_USER_ID=<uuid> \
    python scripts/seed_fact_memory.py

The service role key bypasses RLS and allows inserting with an explicit user_id.
Get the service role key from: Supabase Dashboard > Project Settings > API > service_role.
Get the user UUID from:        Supabase Dashboard > Authentication > Users.
"""

from __future__ import annotations

import json
import os
import sys

import httpx

# ─── required env vars ───────────────────────────────────────────────────────

def _env(key: str) -> str:
    value = os.environ.get(key, "").strip()
    if not value:
        print(f"ERROR: {key} is not set.", file=sys.stderr)
        sys.exit(1)
    return value


# ─── seed data ────────────────────────────────────────────────────────────────

PROFILE_DATA: dict = {
    "name": "安崎 海星",
    "birthdate": "1999-01-18",
    "prefecture": "北海道",
    "city": "札幌市",
    "address_detail": None,
    "email": "kaiseif4e@gmail.com",
    "occupation": "個人事業主 / Webエンジニア / 個人開発者",
    "income_range": "月10〜20万円台(2026年6月時点・変動あり)",
    "lifestyle_notes": {
        "sleep_pattern": "夜型",
        "alcohol": "月1回程度",
        "exercise": ["自転車", "キャンプ", "散策"],
    },
    "devices": [
        {"name": "ThinkPad T14 Gen3", "specs": "Core i7-1260P, 32GB RAM, 1TB SSD, Windows"},
        {"name": "デスクトップPC", "specs": "Core i5-12500, 16GB RAM, Windows"},
        {"name": "Sigmaris専用機", "specs": "Ubuntu Server(構築中)"},
        {"name": "Google Pixel Watch 2", "specs": None},
    ],
    "preferences": {
        "food_likes": ["肉料理", "丼物", "キャンプ飯"],
        "food_dislikes": ["サバ", "青魚の強い風味"],
        "hobbies": [
            "AI・個人開発", "SaaS開発", "ロボット", "航空機",
            "キャンプ", "車中泊", "自転車", "釣り", "カエル観察", "英会話",
        ],
        "services": [
            "ChatGPT", "Claude", "Cursor", "Codex",
            "Supabase", "Vercel", "GitHub", "Google Calendar",
        ],
        "subscriptions": ["ChatGPT Plus"],
    },
    "goals": {
        "short_term": ["AdFlow AI収益化", "Sigmaris基盤構築", "在宅エンジニアとしての安定収入"],
        "long_term": ["Sigmarisを家庭支援OSとして完成させロボット搭載", "個人開発のみで生活"],
    },
    "values": {
        "principles": ["企業依存を避けたい", "技術で問題解決", "自立性", "合理性", "長期視点"],
        "strengths": ["継続的な個人開発", "短納期対応", "技術習得速度", "AI活用"],
        "weaknesses": ["営業・集客が課題", "収益の安定化が未達"],
    },
    "communication_settings": {
        "nickname": "海星さん",
        "tone": "フランク寄り",
        "morning_checklist": [
            "今日の予定", "重要タスク", "未完了タスク",
            "天気", "支出状況", "健康状況サマリー",
        ],
    },
}

# (category, key, value, confidence, source, notes)
FACT_ITEMS: list[tuple[str, str, str, float, str, str | None]] = [
    # profile
    ("profile", "name",       "安崎 海星",                        1.0, "manual", None),
    ("profile", "birthdate",  "1999-01-18",                        1.0, "manual", None),
    ("profile", "residence",  "北海道札幌市",                      1.0, "manual", "番地不明"),
    ("profile", "email",      "kaiseif4e@gmail.com",               1.0, "manual", None),
    ("profile", "occupation", "個人事業主 / Webエンジニア / 個人開発者", 1.0, "manual", None),
    # finance
    ("finance", "income_range",   "月10〜20万円台(変動あり)",      0.8, "manual", "2026年6月時点"),
    ("finance", "subscriptions",  "ChatGPT Plus",                  1.0, "manual", None),
    # lifestyle
    ("lifestyle", "sleep_pattern",      "夜型",                    0.9, "manual", None),
    ("lifestyle", "alcohol_frequency",  "月1回程度",               0.9, "manual", None),
    ("lifestyle", "exercise",           "自転車・キャンプ・散策",  0.9, "manual", None),
    # environment
    ("environment", "car",     "Honda Today JA4 / 1996年式 AT",   1.0, "manual", None),
    ("environment", "bicycle", "Land Gear ロードバイク",           1.0, "manual", None),
    # devices
    ("devices", "laptop",  "ThinkPad T14 Gen3 / Core i7-1260P / 32GB / 1TB / Windows", 1.0, "manual", None),
    ("devices", "desktop", "Core i5-12500 / 16GB / Windows",      1.0, "manual", None),
    ("devices", "server",  "Sigmaris専用機 / Ubuntu Server",       0.8, "manual", "構築中"),
    ("devices", "watch",   "Google Pixel Watch 2",                 1.0, "manual", None),
    # preferences
    ("preferences", "food_likes",   "肉料理・丼物・キャンプ飯",   1.0, "manual", None),
    ("preferences", "food_dislikes","サバ・青魚の強い風味",        1.0, "manual", None),
    ("preferences", "hobbies",
        "AI・個人開発・SaaS・ロボット・航空機・キャンプ・車中泊・自転車・釣り・カエル観察・英会話",
        1.0, "manual", None),
    # goals
    ("goals", "short_term_1",  "AdFlow AI収益化",                  1.0, "manual", None),
    ("goals", "short_term_2",  "Sigmaris基盤構築",                  1.0, "manual", None),
    ("goals", "short_term_3",  "在宅エンジニアとしての安定収入",   1.0, "manual", None),
    ("goals", "long_term_1",   "Sigmarisを家庭支援OSとして完成・ロボット搭載", 1.0, "manual", None),
    ("goals", "long_term_2",   "個人開発のみで生活",               1.0, "manual", None),
    ("goals", "values",
        "企業依存を避けたい・技術で問題解決・自立性・合理性・長期視点",
        1.0, "manual", None),
    ("goals", "strengths",
        "継続的な個人開発・短納期対応・技術習得速度・AI活用",
        1.0, "manual", None),
    ("goals", "weaknesses",
        "営業・集客が課題・収益の安定化が未達",
        0.9, "manual", None),
]


# ─── helpers ─────────────────────────────────────────────────────────────────

def _post(client: httpx.Client, url: str, headers: dict, payload) -> httpx.Response:
    response = client.post(url, headers=headers, json=payload)
    if response.is_error:
        print(f"  ERROR {response.status_code}: {response.text[:300]}", file=sys.stderr)
        sys.exit(1)
    return response


# ─── main ────────────────────────────────────────────────────────────────────

def main() -> None:
    supabase_url = _env("NEXT_PUBLIC_SUPABASE_URL").rstrip("/")
    service_role_key = _env("SUPABASE_SERVICE_ROLE_KEY")
    user_id = _env("SIGMARIS_USER_ID")

    upsert_headers = {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=representation",
    }

    with httpx.Client(timeout=30.0) as client:
        # 1. Upsert user_fact_profile
        print("→ Upserting user_fact_profile …")
        resp = _post(
            client,
            f"{supabase_url}/rest/v1/user_fact_profile",
            upsert_headers,
            {"user_id": user_id, **PROFILE_DATA},
        )
        print(f"  OK (1 row)")

        # 2. Upsert user_fact_items (batch)
        print(f"→ Upserting {len(FACT_ITEMS)} user_fact_items …")
        items_payload = [
            {
                "user_id": user_id,
                "category": cat,
                "key": key,
                "value": value,
                "confidence": confidence,
                "source": source,
                **({"notes": notes} if notes else {}),
            }
            for cat, key, value, confidence, source, notes in FACT_ITEMS
        ]
        resp = _post(
            client,
            f"{supabase_url}/rest/v1/user_fact_items",
            upsert_headers,
            items_payload,
        )
        inserted = resp.json()
        count = len(inserted) if isinstance(inserted, list) else "?"
        print(f"  OK ({count} rows upserted)")

    print("\n✓ Seed complete.")
    print(f"  user_id : {user_id}")
    print(f"  profile : 1 row")
    print(f"  items   : {len(FACT_ITEMS)} rows")


if __name__ == "__main__":
    main()
