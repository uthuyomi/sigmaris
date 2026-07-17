#!/usr/bin/env python3
"""
Phase Safety-3「異常検知・監視の強化」— `safety_critical_files.py`の
リストに、まだ反映されていない可能性のある、安全上重要なファイルを、
ヒューリスティックに検出する、読み取り専用のスキャナー。

【最重要】本スクリプトは、検出結果をSAFETY_CRITICAL_FILESへ自動的に
追加しない。DBへの書き込みも、ファイルへの書き込みも一切行わない
(依頼書「完全な自動化は行わないこと」への直接対応)。人間が、この
出力を見て、追加するかどうかを判断すること。

判定はヒューリスティック(関数名パターン+ファイル冒頭コメントの
キーワード、OR結合)であり、過検知(本当は安全機構ではない)・
見逃し(命名規則に従わない新しいゲート)の両方がありうる——
「絶対に正しい」ことを保証する仕組みではなく、「気づいていない抜けが
あるかもしれない」という気づきを提供するだけの、軽量な仕組みである。

使い方:
    cd backend
    python scripts/scan_safety_critical_files.py
"""

from __future__ import annotations

import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.safety_critical_files_scan import find_unregistered_gate_files  # noqa: E402


def main() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    result = find_unregistered_gate_files(backend_root)

    print("=" * 60)
    print("Safety-3 安全上重要なファイルの追加漏れスキャン")
    print("=" * 60)
    print(f"スキャン対象ファイル数: {result.scanned_file_count}")
    print(f"ゲートらしいパターンに一致したファイル数: {result.gate_pattern_file_count}")
    print(f"うち、safety_critical_files.pyに未登録: {result.unregistered_count}")
    print()

    if result.coverage_complete:
        print("✓ 検出された全てのゲートらしいファイルが、リストに登録済みです。")
    else:
        print("⚠ 以下のファイルは、ゲート・チェックの実装パターンを含む可能性がありますが、")
        print("  safety_critical_files.py の SAFETY_CRITICAL_FILES に登録されていません。")
        print("  実際に安全上重要かどうかは、人間が判断してください(自動追加はしません)。")
        print()
        for candidate in result.unregistered_candidates:
            print(f"  - {candidate.relative_path}")
            for reason in candidate.reasons:
                print(f"      理由: {reason}")
    print("=" * 60)


if __name__ == "__main__":
    main()
