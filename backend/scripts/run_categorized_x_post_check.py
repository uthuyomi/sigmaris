#!/usr/bin/env python3
"""
7カテゴリXポストの「投稿してよいか確認」ジョブ(proactive/scheduler.py::
_categorized_x_post_check)を、定期実行を待たずに手動で1回だけ起動する。

X_CATEGORIZED_POST_LIVE=false(Shadow Mode)の間は、実際の投稿
(x_publisher.post_tweet())は一切呼ばれず、"投稿するつもりだった内容"を
ログに記録するだけなので、このスクリプトの実行は読み取り専用で安全。

使い方:
    cd backend
    python scripts/run_categorized_x_post_check.py

必要な環境変数(backend/.env): run_cycle_health.py と同じ
    (NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY,
     SIGMARIS_REFRESH_TOKEN または SIGMARIS_USER_JWT)
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Windows端末でのcp932による日本語文字化け対策(run_cycle_health.pyと同じ対応)。
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# main.pyのlogging.basicConfigを経由しない単発実行のため、ここで明示的に
# INFOログを標準出力へ出す設定をしないと、_categorized_x_post_check内の
# logger.info("[shadow mode] ...")等が一切表示されない。
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

from app.services.proactive.scheduler import _categorized_x_post_check  # noqa: E402
from app.services.supabase_rest import shutdown_supabase_http_client  # noqa: E402


async def run() -> None:
    try:
        await _categorized_x_post_check()
    finally:
        await shutdown_supabase_http_client()


if __name__ == "__main__":
    asyncio.run(run())
