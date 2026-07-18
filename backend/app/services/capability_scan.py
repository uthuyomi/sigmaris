# 役割: Self-1「コードベースのスキャン、機能の洗い出し」(自己認識の
# 自動更新、第一段階、docs/sigmaris/self_awareness_report.md)—
# シグマリスが、persona.md・self_model(人間が手で書く固定の文書)には
# 反映されていない、実際に実装・稼働している機能を、機械的に洗い出す、
# 読み取り専用のスキャナー。
#
# 【依頼書「重要な制約: 既存資産の再利用を最優先すること」への対応】
# Safety-3(`safety_critical_files_scan.py`)が確立した「(a)関数名パターン、
# (b)ファイル冒頭コメントのキーワード、の2種類のシグナルをOR結合する」
# という設計思想を、そのまま応用した。新しい静的解析基盤・ASTベースの
# 高度な解析は導入していない——正規表現による軽量なテキストマッチのみで
# 完結する、Safety-3と全く同じ技法である。
#
# 本モジュールがSafety-3と異なる点は、シグナルの「対象」のみである。
# Safety-3は「安全機構らしさ」を検出したが、本モジュールは「能力
# (シグマリスが実際に行える機能)らしさ」を検出する。
#   - シグナルA: ファイル冒頭のPhaseタグ(例: "Phase H-1"・"Phase B11"・
#     "Phase G-4")。このコードベースの大半の機能ファイルは、実装した
#     Phase番号を冒頭コメント/docstringに明記する慣習を持つ(H-1〜H-3=
#     X投稿・返信、B群=記憶検索・抽出、D〜F=自己改善、G=検索・引用精度、
#     S=主体性、R=循環健全性等)。
#   - シグナルB: ファイル名に含まれる、能力領域を示す語彙(例:
#     "memory_"・"x_post"・"hypothesis"・"citation_audit")。B群の一部
#     (memory_search.py・memory_extractor.py等)は、調査の結果、Phase
#     タグを一切持たないことが判明した——ファイル名シグナルは、この
#     取りこぼしを補う、Safety-3の「2つのシグナルの相補性」という設計
#     思想をそのまま踏襲したものである(判断根拠、報告書参照)。
#   - シグナルC(scripts/限定): `if __name__ == "__main__":`を持つ、
#     独立したCLIとして実行可能なスクリプトであること(依頼書「scripts/
#     配下の独立したCLIとして実行可能な機能」への直接対応)。
#
# 【本モジュールが行わないこと(依頼書「本タスクの範囲は洗い出しのみ」)】
# 洗い出した結果を日本語に要約する処理(Self-2)、応答生成への注入
# (Self-3)は、一切行わない。DBへの書き込み・ファイルへの書き込みも
# 行わない、完全に読み取り専用のスキャナーである。

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# ── シグナルA: ファイル冒頭のPhaseタグ ──────────────────────────────────
# 観測された実際の表記ゆれ(判断根拠、報告書2.2節): "Phase H-1"・
# "Phase B11"(ハイフン無し)・"Phase G-4"・"Phase C-full"・"Phase C-mini"・
# "Phase H-2.5"(サブフェーズ)・"Phase D"(番号無し)。これら全てを1つの
# 正規表現で捉えられるよう、"Phase"の後に大文字1字+任意の英数字/ハイフン/
# ドットが続く、という緩い形にした。
_PHASE_TAG_RE = re.compile(r"Phase\s+[A-Z][\w.-]*")

# Phaseの先頭文字から、能力領域への大まかな対応付け(報告書2.1節の
# 4領域+洗い出しの過程で追加したcuriosity領域に対応)。この対応付けは
# あくまで報告の見やすさのためのグルーピングであり、判定基準そのもの
# ではない(Signal A自体は、対応表に無い先頭文字でも一致する——例えば
# Phase Sを持つファイルは"self_improvement"寄りの内容が多いが、S群
# 全体を厳密にどの領域とみなすかは、Self-2以降の要約タスクの判断に
# 委ねる、という保守的な割り当てにした)。
_PHASE_PREFIX_TO_DOMAIN: dict[str, str] = {
    "H": "x_post_reply",
    "B": "memory",
    "D": "self_improvement",
    "E": "self_improvement",
    "F": "self_improvement",
    "G": "search_citation",
}


_PHASE_ALPHA_PREFIX_RE = re.compile(r"^[A-Za-z]+")


def _matches_phase_tag(source: str, header_lines: int) -> tuple[bool, str, str | None]:
    """冒頭header_lines行以内にPhaseタグがあれば(一致, 理由, 推定domain)を返す。"""
    header = "\n".join(source.splitlines()[:header_lines])
    match = _PHASE_TAG_RE.search(header)
    if not match:
        return False, "", None
    tag = match.group(0)
    # 先頭の英字の並びを丸ごと取り出す(例: "B15"→"B", "BA2"→"BA",
    # "C-full"→"C")。「先頭1文字だけ」で判定すると、"BA"(orchestrator
    # 統合、B群=記憶検索とは無関係の別系列)が"B"に誤って丸め込まれる
    # ——実際にapp_profile_data.py(Phase BA2)で過検知が発生することを
    # 実装時に発見し、この完全一致方式へ修正した(判断根拠、報告書参照)。
    alpha_match = _PHASE_ALPHA_PREFIX_RE.match(tag.replace("Phase", "").strip())
    prefix = alpha_match.group(0) if alpha_match else ""
    domain = _PHASE_PREFIX_TO_DOMAIN.get(prefix)
    return True, f"冒頭コメントにPhaseタグ「{tag}」を検出", domain


# ── シグナルB: ファイル名に含まれる能力領域の語彙 ────────────────────────
# 依頼書2章が例示した4領域(X投稿・返信/記憶検索・抽出/自己改善/検索・
# 引用精度向上)それぞれから、実際にこのコードベースで使われている
# ファイル名の接頭辞・部分文字列を抽出した。ファイル名のみを対象とする
# (ファイル冒頭コメント全体は対象にしない)——判断根拠: ヘッダーコメント
# には他モジュールのimport文も含まれるため、"memory"・"fact"のような
# 単語をヘッダーテキスト全体に対して照合すると、単に`user_fact_data`を
# importしているだけの無関係なファイルまで過検知することが、実装時の
# 検証で判明した。ファイル名は、このコードベースの命名規則が既に領域を
# 表しているため、より精度の高い、安全なシグナルとして採用した。
#
# 依頼書の4領域に加え、"curiosity_engine.py"・"research_agent.py"
# (好奇心駆動の研究機能)を、洗い出しの過程で追加発見した——依頼書
# 2章の対象定義が「以下のような対象」(非網羅的な例示)であったため、
# 実在する既知の能力領域を追加することは、依頼書の意図に反しないと
# 判断した(判断根拠、報告書に明記)。
_DOMAIN_FILENAME_MARKERS: tuple[tuple[str, str], ...] = (
    ("x_post", "x_post_reply"),
    ("x_reply", "x_post_reply"),
    ("x_publisher", "x_post_reply"),
    ("x_content_filter", "x_post_reply"),
    ("x_privacy_filter", "x_post_reply"),
    ("memory_", "memory"),
    ("user_fact", "memory"),
    ("fact_memory", "memory"),
    ("hypothesis", "self_improvement"),
    ("code_diff", "self_improvement"),
    ("diff_approval", "self_improvement"),
    ("diff_patch", "self_improvement"),
    ("evidence_aggregation", "self_improvement"),
    ("github_pr_publisher", "self_improvement"),
    ("static_verification", "self_improvement"),
    ("migration_review", "self_improvement"),
    ("citation_audit", "search_citation"),
    ("evidence_search", "search_citation"),
    ("self_critique", "search_citation"),
    ("grounding", "search_citation"),
    ("multihop_search", "search_citation"),
    ("search_trigger", "search_citation"),
    ("curiosity", "research_curiosity"),
    ("research_agent", "research_curiosity"),
)


def _matches_domain_filename(stem: str) -> tuple[bool, str, str | None]:
    lowered = stem.lower()
    for marker, domain in _DOMAIN_FILENAME_MARKERS:
        if marker in lowered:
            return True, f"ファイル名がマーカー「{marker}」に一致", domain
    return False, "", None


# ── シグナルC(scripts/限定): 独立したCLIとして実行可能であること ────────
_MAIN_GUARD_RE = re.compile(r'if\s+__name__\s*==\s*["\']__main__["\']\s*:')


def _matches_cli_entrypoint(source: str) -> tuple[bool, str]:
    if _MAIN_GUARD_RE.search(source):
        return True, "独立したCLI(`if __name__ == \"__main__\":`)として実行可能"
    return False, ""


# 公開関数名の抽出(Safety-3::_GATE_FUNCTION_DEF_REと同じ、軽量な正規表現
# ベースの検出——ASTパーサは導入しない)。アンダースコア始まりの関数
# (実装の詳細、内部ヘルパー)は、依頼書「対応する関数」が指す"能力の
# 入り口"には当たらないため、除外する。
_FUNCTION_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)", re.MULTILINE)
_HEADER_SCAN_LINES = 15


def _public_function_names(source: str) -> tuple[str, ...]:
    """モジュール内で定義された、アンダースコア始まりでない関数・メソッド名
    (順序維持・重複除去)。抽象基底クラス+複数実装クラスが同名メソッドを
    持つファイル(例: x_publisher.py)で、同じ名前が繰り返し表示されるのを
    避けるため、重複除去する(Safety-3の同種正規表現と異なる点、判断根拠は
    報告書参照——安全機構の検出には重複の有無は無関係だったが、本モジュール
    は「対応する関数」を人間が読む一覧として提示するため、可読性を優先した)。"""
    seen: dict[str, None] = {}
    for match in _FUNCTION_DEF_RE.finditer(source):
        name = match.group(1)
        if not name.startswith("_"):
            seen.setdefault(name, None)
    return tuple(seen.keys())


def _header_description(source: str) -> str | None:
    """冒頭の"# 役割: ..."行、または先頭の三重引用符docstringの最初の
    非空行を、Self-2が要約する際の"元になる情報"として抜き出す
    (要約自体は行わない、依頼書の範囲外)。"""
    lines = source.splitlines()
    for line in lines[:_HEADER_SCAN_LINES]:
        stripped = line.strip()
        if stripped.startswith("# 役割:"):
            return stripped.removeprefix("#").strip()
    # scripts/*.pyの慣習(shebang直後のtriple-quoted docstring)への対応
    in_docstring = False
    for line in lines[:_HEADER_SCAN_LINES]:
        stripped = line.strip()
        if not in_docstring and stripped.startswith('"""'):
            in_docstring = True
            remainder = stripped[3:].strip()
            if remainder and not remainder.endswith('"""'):
                return remainder
            continue
        if in_docstring and stripped:
            return stripped
    return None


@dataclass
class CapabilityCandidate:
    relative_path: str  # posix形式、リポジトリルートからの相対パス
    domain: str  # 報告の見やすさのための大まかな分類("other"=どの領域にも一致しないがPhaseタグ等で検出)
    reasons: list[str] = field(default_factory=list)
    header_description: str | None = None
    public_functions: tuple[str, ...] = ()


@dataclass
class CapabilityScanResult:
    scanned_file_count: int
    candidates: list[CapabilityCandidate]

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)


# スキャン対象ディレクトリ。依頼書が例示した機能(H-1〜H-3・B群・D〜F・G)は
# いずれもapp/services/配下、独立したCLIはscripts/配下に置かれてきた
# (Safety-3と全く同じ対象ディレクトリ選定、判断根拠も同じ——依頼書
# 「過度に複雑にしない」方針に従い、フロントエンド・テストファイル等の
# 明らかに対象外の領域は最初からスキャンしない)。
_SCAN_SUBDIRS: tuple[str, ...] = ("app/services", "scripts")

# 本モジュール自身は、能力そのものではなく能力を発見する仕組みである
# ため、自己参照による無意味な"検出"を避ける(Safety-3の同種の除外と
# 同じ判断)。
_EXCLUDED_BASENAMES: frozenset[str] = frozenset({
    "capability_scan.py",
    "scan_capabilities.py",
})


def scan_capabilities(backend_root: Path) -> CapabilityScanResult:
    """backend_root配下(app/services・scripts)の.pyファイルを走査し、
    シグナルA・B・Cのいずれかに一致するファイルを、能力候補として返す
    (OR結合、モジュールdocstring参照)。"""
    candidates: list[CapabilityCandidate] = []
    scanned_count = 0

    for subdir in _SCAN_SUBDIRS:
        base = backend_root / subdir
        if not base.exists():
            continue
        is_scripts_dir = subdir == "scripts"
        for path in sorted(base.rglob("*.py")):
            if path.name in _EXCLUDED_BASENAMES or path.name.startswith("__"):
                continue
            scanned_count += 1
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue

            reasons: list[str] = []
            domain: str | None = None

            phase_matched, phase_reason, phase_domain = _matches_phase_tag(source, _HEADER_SCAN_LINES)
            if phase_matched:
                reasons.append(phase_reason)
                domain = domain or phase_domain

            name_matched, name_reason, name_domain = _matches_domain_filename(path.stem)
            if name_matched:
                reasons.append(name_reason)
                domain = domain or name_domain

            if is_scripts_dir:
                cli_matched, cli_reason = _matches_cli_entrypoint(source)
                if cli_matched:
                    reasons.append(cli_reason)
                    domain = domain or "cli_script"

            if not reasons:
                continue

            relative = path.relative_to(backend_root.parent).as_posix()
            candidates.append(
                CapabilityCandidate(
                    relative_path=relative,
                    domain=domain or "other",
                    reasons=reasons,
                    header_description=_header_description(source),
                    public_functions=_public_function_names(source),
                )
            )

    return CapabilityScanResult(scanned_file_count=scanned_count, candidates=candidates)
