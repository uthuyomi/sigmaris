#!/usr/bin/env python3
"""
Self-1「コードベースのスキャン、機能の洗い出し」(自己認識の自動更新、
第一段階) — persona.md・self_modelという人間が手で書く固定の文書には
反映されていない、実際にコードベースへ実装・稼働している機能を、
ヒューリスティックに洗い出す、読み取り専用のスキャナー。

【本スクリプトが行わないこと】
洗い出した結果を日本語へ要約する処理(Self-2)、応答生成への注入
(Self-3)は、一切行わない。DBへの書き込み・ファイルへの書き込みも
行わない——標準出力への表示のみで完結する。

判定はヒューリスティック(Phaseタグ・ファイル名・CLIエントリポイントの
OR結合)であり、過検知・見逃しの両方がありうる——「絶対に正しい」こと
を保証する仕組みではなく、「今コードベースに実際に存在する機能」に
気づく手がかりを提供するだけの、軽量な仕組みである。

使い方:
    cd backend
    python scripts/scan_capabilities.py
    python scripts/scan_capabilities.py --domain memory   # 特定領域のみ表示
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.capability_scan import scan_capabilities  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--domain", default=None, help="この領域のみ表示(例: memory, x_post_reply, self_improvement, search_citation, research_curiosity, cli_script, other)")
    args = parser.parse_args()

    backend_root = Path(__file__).resolve().parents[1]
    result = scan_capabilities(backend_root)

    candidates = result.candidates
    if args.domain:
        candidates = [c for c in candidates if c.domain == args.domain]

    print("=" * 60)
    print("Self-1 コードベース機能スキャン(能力の洗い出し)")
    print("=" * 60)
    print(f"スキャン対象ファイル数: {result.scanned_file_count}")
    print(f"能力候補として検出されたファイル数: {result.candidate_count}"
          + (f"(うちdomain={args.domain}: {len(candidates)}件)" if args.domain else ""))
    print()

    by_domain: dict[str, int] = {}
    for c in result.candidates:
        by_domain[c.domain] = by_domain.get(c.domain, 0) + 1
    print("領域別の内訳:")
    for domain, count in sorted(by_domain.items(), key=lambda kv: -kv[1]):
        print(f"  {domain:20s}: {count}件")
    print()

    for candidate in candidates:
        print(f"- [{candidate.domain}] {candidate.relative_path}")
        if candidate.header_description:
            print(f"    説明の元情報: {candidate.header_description}")
        if candidate.public_functions:
            funcs = ", ".join(candidate.public_functions[:8])
            more = "..." if len(candidate.public_functions) > 8 else ""
            print(f"    公開関数: {funcs}{more}")
        for reason in candidate.reasons:
            print(f"    理由: {reason}")
    print("=" * 60)


if __name__ == "__main__":
    main()
