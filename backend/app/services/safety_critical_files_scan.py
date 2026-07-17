# 役割: Safety-3「異常検知・監視の強化」— Safety-2が申し送った、根本的な
# リスク(「新しく追加された、安全上重要なファイルが、`safety_critical_
# files.py`のリストに反映されないまま放置される」)を検知する、軽量な
# ルールベースのスキャナー。
#
# 【依頼書「重要な制約」への対応】
# 新しい監視の仕組みをゼロから作らず、D-2(`hypothesis_generation.py::
# rule_based_safety_flag()`)が既に確立している「キーワード一致の
# OR結合(安全側に倒す)」という判定方式を、そのまま踏襲した——
# rule_based_safety_flag()は(a)安全機構キーワードへの言及、(b)弱める
# 方向の動詞、という2種類のシグナルをORで結合していたが、本モジュールは
# (a)ゲートらしい関数名パターン、(b)ファイル冒頭の"役割:"コメント内の
# 安全関連キーワード、という2種類のシグナルをORで結合する、全く同じ
# 設計思想の応用である。機械学習ベースの異常検知は導入していない
# (依頼書の制約への直接対応)。
#
# 【本モジュールが行わないこと(依頼書の制約「完全な自動化は行わない」)】
# 本モジュールは、「安全上重要である可能性があるファイルが、リストに
# 含まれていない」ことを検出し、報告するのみである。**`SAFETY_CRITICAL_
# FILES`への自動追加・自動書き換えは、一切行わない。** 判定は、あくまで
# 「気づいていない抜けがあるかもしれない」という、人間への気づきの提供に
# 留まる——ヒューリスティックな名前・コメントの一致に基づくため、
# 過検知(本当は安全機構ではないファイルが候補に挙がる)・見逃し(命名
# 規則に従わない新しいゲートが見逃される)の両方がありうることを前提と
# した設計であり、最終判断は常に人間が行う。

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.services.safety_critical_files import get_safety_mechanism_file_patterns

# ── シグナルA: 関数名パターン ────────────────────────────────────────────
# 既存の安全機構(Safety-1・Safety-2で棚卸し済み)が実際に使っている
# 関数名から、共通する語彙を抽出した。汎用的すぎる語(例: 単なる
# "check_"接頭辞)は、RC-2(cycle_health_metrics.py::check_chat_message_
# order()等、安全機構ではない既存の"check_"関数)を過検知するため、
# 意図的に採用しなかった——安全・承認・レビュー判定に特有の語彙のみを
# 対象にする(判断根拠、レポート参照)。
_GATE_FUNCTION_NAME_MARKERS: tuple[str, ...] = (
    "safety",  # check_diff_safety, rule_based_safety_flag
    "requires_approval",
    "requires_special_review",
    "review_decision",  # record_review_decision (E-4/F-1/F-3共通)
    "mentions_migration",
    "confidence_tier",  # classify_confidence_tier
    "confidence_guidance",  # confidence_guidance_note
    "forbidden_assistant_names",  # replace_forbidden_assistant_names
    "executive_gate",  # evaluate_executive_gate
    "constitution_guard",
    "diff_safety",
)

_GATE_FUNCTION_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)", re.MULTILINE)


def _matches_gate_function_name(source: str) -> tuple[bool, str]:
    for match in _GATE_FUNCTION_DEF_RE.finditer(source):
        func_name = match.group(1).lower()
        for marker in _GATE_FUNCTION_NAME_MARKERS:
            if marker in func_name:
                return True, f"関数名「{match.group(1)}」がマーカー「{marker}」に一致"
    return False, ""


# ── シグナルB: ファイル冒頭コメントのキーワード ───────────────────────────
# このコードベースの一貫した慣習(全サービスファイルが"# 役割: ..."で
# 始まる)を利用し、冒頭コメントブロックに、安全機構・承認フローに特有の
# 語彙が含まれるかを確認する。関数名シグナルより幅広く、命名規則に
# 従わない新しいゲートも拾える可能性がある(2つのシグナルの相補性)。
_HEADER_COMMENT_MARKERS: tuple[str, ...] = (
    "安全機構", "承認フロー", "承認必須", "承認が必要", "承認待ち",
    "review_status", "ブロックリスト", "constitution_guard",
    "safety_critical_files",
)

_HEADER_SCAN_LINES = 40


def _matches_header_comment(source: str) -> tuple[bool, str]:
    header = "\n".join(source.splitlines()[:_HEADER_SCAN_LINES])
    for marker in _HEADER_COMMENT_MARKERS:
        if marker.lower() in header.lower():
            return True, f"冒頭コメントがマーカー「{marker}」に一致"
    return False, ""


@dataclass
class GatePatternFile:
    relative_path: str  # posix形式、リポジトリルートからの相対パス
    reasons: list[str] = field(default_factory=list)


@dataclass
class SafetyCoverageScanResult:
    scanned_file_count: int
    gate_pattern_files: list[GatePatternFile]
    unregistered_candidates: list[GatePatternFile]

    @property
    def gate_pattern_file_count(self) -> int:
        return len(self.gate_pattern_files)

    @property
    def unregistered_count(self) -> int:
        return len(self.unregistered_candidates)

    @property
    def coverage_complete(self) -> bool:
        return self.unregistered_count == 0


# スキャン対象ディレクトリ。安全上重要なファイルが実際に置かれてきた
# 場所(backend/app/services/、backend/scripts/)に絞る——依頼書
# 「過度に複雑にしない」方針に従い、フロントエンド・テストファイル等
# 明らかに対象外の領域は最初からスキャンしない。
_SCAN_SUBDIRS: tuple[str, ...] = ("app/services", "scripts")

# 本モジュール自身・正典モジュール自身・本モジュールを呼ぶだけのCLIは、
# スキャン対象から除外する(自己参照による無意味な"検知"を避ける——
# これらのファイルの冒頭コメント自体が、上記マーカーの多くを説明の
# ために含んでいるが、ゲート・チェックのロジック自体は実装していない
# ため、Safety-2が確立した「実際に判定ロジックを含むファイルのみ登録
# する」という基準にも、そもそも合致しない)。
_EXCLUDED_BASENAMES: frozenset[str] = frozenset({
    "safety_critical_files.py",
    "safety_critical_files_scan.py",
    "scan_safety_critical_files.py",
})


def scan_for_gate_pattern_files(backend_root: Path) -> list[GatePatternFile]:
    """backend_root配下(app/services・scripts)の.pyファイルを走査し、
    シグナルA・シグナルBのいずれかに一致するファイルを返す(OR結合、
    モジュールdocstring参照)。"""
    results: list[GatePatternFile] = []
    for subdir in _SCAN_SUBDIRS:
        base = backend_root / subdir
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            if path.name in _EXCLUDED_BASENAMES or path.name.startswith("__"):
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue

            reasons: list[str] = []
            name_matched, name_reason = _matches_gate_function_name(source)
            if name_matched:
                reasons.append(name_reason)
            header_matched, header_reason = _matches_header_comment(source)
            if header_matched:
                reasons.append(header_reason)

            if reasons:
                relative = path.relative_to(backend_root.parent).as_posix()
                results.append(GatePatternFile(relative_path=relative, reasons=reasons))

    return results


def find_unregistered_gate_files(backend_root: Path) -> SafetyCoverageScanResult:
    """ゲートらしいファイルのうち、`safety_critical_files.SAFETY_
    CRITICAL_FILES`のいずれのfile_patternにも一致しないものを返す。
    **リストへの自動追加は行わない**(モジュールdocstring参照)。"""
    scanned = list(scan_for_gate_pattern_files(backend_root))
    registered_patterns = [re.compile(p) for p in get_safety_mechanism_file_patterns()]

    unregistered: list[GatePatternFile] = []
    for candidate in scanned:
        normalized = candidate.relative_path.replace("\\", "/")
        if not any(pattern.search(normalized) for pattern in registered_patterns):
            unregistered.append(candidate)

    total_scanned = sum(
        1 for subdir in _SCAN_SUBDIRS if (backend_root / subdir).exists()
        for _ in (backend_root / subdir).rglob("*.py")
    )
    return SafetyCoverageScanResult(
        scanned_file_count=total_scanned,
        gate_pattern_files=scanned,
        unregistered_candidates=unregistered,
    )
