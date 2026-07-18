#!/usr/bin/env python3
"""
Self-2「洗い出した機能の日本語への要約」(自己認識の自動更新、第二段階) —
Self-1(capability_scan.py)が洗い出した能力候補を、まとまりのある単位で
グループ化し、各ファイルが実際に他のコードから呼び出されている(配線済み)
か、まだ呼び出されていない(未配線・実験段階)かを判定した上で、nano-tier
のLLM呼び出しで、シグマリスが一人称で語る2〜3文の日本語説明へ要約する。

【本スクリプトが行わないこと】
応答生成への注入(Self-3)は、一切行わない。生成した要約は
sigmaris_capability_summariesへ保存するのみ(--dry-runで保存を省略可能)。

使い方:
    cd backend
    python scripts/generate_capability_summaries.py
    python scripts/generate_capability_summaries.py --dry-run   # DBに記録せず標準出力のみ

必要な環境変数(backend/.env):
    OPENAI_API_KEY(要約生成、nano tier)
    NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY,
    SUPABASE_SERVICE_ROLE_KEY(sigmaris_capability_summariesへの記録に必要、
    --dry-run時は不要)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.capability_summary import DOMAIN_LABELS, generate_capability_summaries  # noqa: E402
from app.services.capability_summary_store import record_capability_summary  # noqa: E402
from app.services.supabase_rest import shutdown_supabase_http_client  # noqa: E402


async def _main(args: argparse.Namespace) -> None:
    backend_root = Path(__file__).resolve().parents[1]
    print("Self-2 能力要約を生成中...")
    summaries = await generate_capability_summaries(backend_root)

    print("\n" + "=" * 60)
    print("Self-2 コードベース機能の日本語要約(自己認識)")
    print("=" * 60)
    for s in summaries:
        label = DOMAIN_LABELS.get(s.domain, s.domain)
        print(f"\n[{s.domain}] {label}")
        print(f"  対象ファイル数: {s.file_count}(配線済み{s.wired_file_count} / 未配線{s.unwired_file_count})")
        print(f"  要約: {s.summary_text}")
    print("\n" + "=" * 60)

    if args.dry_run:
        print("\n--dry-run のため sigmaris_capability_summaries には記録していません。")
        return

    for s in summaries:
        row_id = await record_capability_summary(
            domain=s.domain,
            summary_text=s.summary_text,
            file_count=s.file_count,
            wired_file_count=s.wired_file_count,
            unwired_file_count=s.unwired_file_count,
            source_files=s.source_files,
        )
        if row_id:
            print(f"✓ [{s.domain}] sigmaris_capability_summaries に記録しました (id={row_id})")
        else:
            print(
                f"⚠ [{s.domain}] sigmaris_capability_summaries への記録に失敗しました "
                "(マイグレーション202608070065未適用、またはSUPABASE_SERVICE_ROLE_KEY未設定の可能性)。"
                "上記の要約自体は正しく生成されています。"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="DBに記録せず標準出力のみ行う")
    args = parser.parse_args()

    async def run() -> None:
        try:
            await _main(args)
        finally:
            await shutdown_supabase_http_client()

    asyncio.run(run())


if __name__ == "__main__":
    main()
