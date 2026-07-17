# 役割: Phase D-1「根拠収集」の純粋な分類・優先順位付けロジック。
#
# Phase R(RC指標)・Phase G(Grounding指標)・Phase S-2(Mastery Driveの
# 言語化)・bug_inventory.md(過去のインシデント記録)という、既に存在
# する4つの資産を読み取り、Phase D-2(仮説生成、未実装)が扱いやすい
# 構造化された根拠(EvidenceItem)へ変換するだけの層。**ここでは新しい
# 改良案を組み立てない**——優先順位付けまでがこのモジュールの責務。
#
# cycle_health_metrics.py/grounding_health_metrics.pyと同じく、I/Oを一切
# 持たない純粋関数のみを置く。DB・ファイル読み取りはevidence_aggregation_
# runner.py側の責務。

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.services.cycle_health_metrics import check_metric_drop

# RC-5(cycle_health_metrics.detect_cycle_break)と同じ「recurring pattern
# として信頼するための最低サンプル数」「絶対値20ポイントの落ち込み」を
# そのまま踏襲した値。Phase Dでも同じ閾値を使う判断根拠: RC-5がこの値を
# 導入した時点で既に「未検証の暫定値」と明記されており(phase_r_report.md
# 15.3節)、指標ごとに別々の未検証の値を新設するより、既存の1つの暫定値に
# 揃えておく方が、将来まとめて実データを見て調整する際に扱いやすい。
_DEGRADATION_MIN_HISTORY = 3
_DEGRADATION_DROP_THRESHOLD = 0.2

# goal_proposal.py::_format_mastery_lines()が実際に使っている閾値
# (RC-1/RC-2 < 0.8、RC-5 == "break_detected")をそのまま踏襲した値。
# 【重要な既知の結合】goal_proposal.py側の閾値が将来変更された場合、
# ここも追随させる必要がある——import して共有する形にしなかった判断
# 根拠は、goal_proposal.py側の関数がDriveStateオブジェクトを引数に取る
# のに対し、ここではsigmaris_experience.context(既に保存済みのflat
# dict)を扱っており、型が異なるため素直に共有できないこと、また
# evidence_aggregation.py(根拠収集)からgoal_proposal.py(行動実行)への
# 依存を新設するのは責務の向きとして逆転していると判断したため。
_MASTERY_RC_THRESHOLD = 0.8

# bug_inventory.mdの「出典」欄に含まれる外部レポートファイル名を検出する
# ための正規表現。「本タスク」等の自己参照(bug_inventory.md自身の章番号)
# はこの正規表現にマッチしないため、区別に使える。
_SOURCE_MD_FILENAME_RE = re.compile(r"[A-Za-z0-9_]+\.md")

# bug_inventory.mdの概要・深刻度欄に頻出する「解決済み」を示すキーワード。
# 発見当時の報告書の表記を機械的に踏襲しただけの簡易マッチであり、意味的
# な判定ではない(6章の懸念点として明記)。
_RESOLVED_KEYWORDS = ("修正済み", "解決済み", "解消済み", "対応不要", "対応済み")


@dataclass
class EvidenceItem:
    category: str  # "metric_degradation" | "recurring_problem" | "mastery_proposal"
    source_system: str  # "phase_r" | "phase_g" | "phase_s_mastery" | "bug_inventory"
    title: str
    description: str
    severity: str | None  # "high" | "medium" | "low" | None(不明)
    priority_score: int
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvidenceBundle:
    items: list[EvidenceItem]
    sources_checked: dict[str, int]


def _invert(value: float) -> float:
    """lower-is-better指標(contradiction_rate等)を、check_metric_drop()
    が前提とするhigher-is-better方向へ反転する。check_metric_drop()自体
    には手を加えず、呼び出し側でのみ反転する(cycle_health_metrics.py
    への影響を最小化する判断、docs/sigmaris/phase_d_report.md参照)。"""
    return 1.0 - value


def build_metric_degradation_items(
    rc_runs: list[dict[str, Any]], grounding_runs: list[dict[str, Any]]
) -> list[EvidenceItem]:
    """RC指標(Phase R)・Grounding指標(Phase G)それぞれの最新実行が、
    過去の実行群の平均から大きく落ち込んでいないかを確認する。

    rc_runs/grounding_runsは、それぞれget_recent_cycle_health_runs()/
    get_recent_grounding_health_runs()の戻り値(created_at降順、最新が
    先頭)をそのまま渡す想定。RC-5(cycle_health_metrics.detect_cycle_
    break)が既に確立した「直近平均との単純な閾値比較」をRC-3/RC-4・
    Grounding指標にも横展開する——新しい検知ロジックを作らず、既存の
    check_metric_drop()をそのまま再利用する(要件2への対応)。

    search_trigger_rateは意図的に対象外とした。Phase G-5の報告書
    (docs/sigmaris/phase_g_report.md)自身が「低い/高いは必ずしも良し悪し
    ではない」と明記しており、方向性が不明な指標を機械的に「悪化」と
    判定することは、G-5が確立した「短絡的な良し悪し判定を避ける」という
    設計哲学に反する。
    """
    items: list[EvidenceItem] = []

    if rc_runs:
        latest_rc = rc_runs[0]
        historical_rc = rc_runs[1:]
        rc_metric_fields = [
            ("rc1_eligible_completion_rate", "RC-1(循環完了率)"),
            ("rc2_score", "RC-2(時間的一貫性)"),
            ("rc3_score", "RC-3(信念の安定性)"),
            ("rc4_score", "RC-4(方策整合性)"),
        ]
        degraded_rc: list[tuple[str, Any]] = []
        for field_name, label in rc_metric_fields:
            current = latest_rc.get(field_name)
            historical = [
                row[field_name] for row in historical_rc if isinstance(row.get(field_name), (int, float))
            ]
            check = check_metric_drop(
                metric=field_name,
                current=current if isinstance(current, (int, float)) else None,
                historical=historical,
                min_history=_DEGRADATION_MIN_HISTORY,
                drop_threshold=_DEGRADATION_DROP_THRESHOLD,
            )
            if check.broke_threshold:
                degraded_rc.append((label, check))

        for label, check in degraded_rc:
            items.append(
                EvidenceItem(
                    category="metric_degradation",
                    source_system="phase_r",
                    title=f"{label}の悪化",
                    description=(
                        f"{label}が過去平均{check.baseline:.0%}から{check.current:.0%}まで低下している"
                        f"(落ち込み{check.drop:.0%}ポイント)。"
                    ),
                    severity="high" if len(degraded_rc) >= 2 else "medium",
                    # 「複数の指標に同時に悪影響を与えているものを優先する」
                    # という依頼書の例示基準をそのまま採用: 同一実行内で
                    # 同時に悪化した指標の数を優先度スコアの核にする。
                    priority_score=len(degraded_rc),
                    details={
                        "metric": check.metric,
                        "current": check.current,
                        "baseline": check.baseline,
                        "drop": check.drop,
                        "co_degraded_with": [other for other, _ in degraded_rc if other != label],
                    },
                )
            )

    if grounding_runs:
        latest_g = grounding_runs[0]
        historical_g = grounding_runs[1:]
        g_metric_checks: list[tuple[str, Any]] = []

        cp_current = latest_g.get("citation_precision")
        cp_historical = [
            row["citation_precision"]
            for row in historical_g
            if isinstance(row.get("citation_precision"), (int, float))
        ]
        cp_check = check_metric_drop(
            metric="citation_precision",
            current=cp_current if isinstance(cp_current, (int, float)) else None,
            historical=cp_historical,
            min_history=_DEGRADATION_MIN_HISTORY,
            drop_threshold=_DEGRADATION_DROP_THRESHOLD,
        )
        if cp_check.broke_threshold:
            g_metric_checks.append(("Citation Precision(引用精度)", cp_check))

        cr_current = latest_g.get("contradiction_rate")
        cr_historical = [
            row["contradiction_rate"]
            for row in historical_g
            if isinstance(row.get("contradiction_rate"), (int, float))
        ]
        cr_check = check_metric_drop(
            metric="contradiction_rate(inverted)",
            current=_invert(cr_current) if isinstance(cr_current, (int, float)) else None,
            historical=[_invert(v) for v in cr_historical],
            min_history=_DEGRADATION_MIN_HISTORY,
            drop_threshold=_DEGRADATION_DROP_THRESHOLD,
        )
        if cr_check.broke_threshold:
            g_metric_checks.append(("Contradiction Rate(矛盾検出率)", cr_check))

        for label, check in g_metric_checks:
            # 表示上はinvert前の直感的な値に戻す(current/baselineは
            # invert後の値のためcontradiction_rateのみ再反転)。
            display_current = 1.0 - check.current if "contradiction" in check.metric else check.current
            display_baseline = 1.0 - check.baseline if "contradiction" in check.metric else check.baseline
            items.append(
                EvidenceItem(
                    category="metric_degradation",
                    source_system="phase_g",
                    title=f"{label}の悪化",
                    description=(
                        f"{label}が過去平均{display_baseline:.0%}から{display_current:.0%}まで悪化している"
                        f"(落ち込み{check.drop:.0%}ポイント相当)。"
                    ),
                    severity="high" if len(g_metric_checks) >= 2 else "medium",
                    priority_score=len(g_metric_checks),
                    details={
                        "metric": check.metric,
                        "current": display_current,
                        "baseline": display_baseline,
                        "drop": check.drop,
                        "co_degraded_with": [other for other, _ in g_metric_checks if other != label],
                    },
                )
            )

    return items


def build_mastery_proposal_items(experiences: list[dict[str, Any]]) -> list[EvidenceItem]:
    """S-2のMastery Driveが既に言語化した改善提案(sigmaris_experience、
    category="proposal"、experience_type="unresolved")を、そのまま根拠
    として取り込む。新しい言語化ロジックは追加しない(要件1・2)。"""
    items: list[EvidenceItem] = []
    for exp in experiences:
        context = exp.get("context") if isinstance(exp.get("context"), dict) else {}
        signal_count = 0
        if isinstance(context.get("rc1_eligible_completion_rate"), (int, float)) and (
            context["rc1_eligible_completion_rate"] < _MASTERY_RC_THRESHOLD
        ):
            signal_count += 1
        if isinstance(context.get("rc2_score"), (int, float)) and context["rc2_score"] < _MASTERY_RC_THRESHOLD:
            signal_count += 1
        if context.get("rc5_status") == "break_detected":
            signal_count += 1

        severity = "high" if context.get("rc5_status") == "break_detected" else (
            "medium" if signal_count >= 2 else "low"
        )
        items.append(
            EvidenceItem(
                category="mastery_proposal",
                source_system="phase_s_mastery",
                title=exp.get("title") or "循環健全性の改善提案",
                description=exp.get("description") or "",
                severity=severity,
                priority_score=signal_count,
                details={
                    "experience_id": exp.get("id"),
                    "created_at": exp.get("created_at"),
                    "context": context,
                },
            )
        )
    return items


def parse_bug_inventory_table(markdown_text: str) -> list[dict[str, Any]]:
    """bug_inventory.mdの「## 4. 問題一覧表」セクションにある、
    `| # | 概要 | 出典 | 深刻度 | 推定根本原因 | 優先度目安 |`という
    Markdownテーブルをパースする。

    【重要な限界】これは表の見出し列名・列順が変わらないことを前提にした
    テキストベースのベストエフォート・パーサーであり、意味的な理解を
    伴わない(bug_inventory.mdの表フォーマット自体が変わった場合は壊れ
    うる)。依頼書の「ドキュメントのみの場合は、本タスクでは無理に構造化
    せず、参照方法を報告するに留めてよい」という許容を踏まえた上で、
    それでも簡易的な構造化を試みた判断根拠は、bug_inventory.mdの表が
    既に十分定型的なMarkdownテーブルであり、追加のデータ収集を一切せず
    既存ドキュメントをそのまま読むだけで実現できると判断したため
    (レポート参照)。
    """
    section_match = re.search(r"## 4\. 問題一覧表(.*?)(?=\n## 5\.|\Z)", markdown_text, re.DOTALL)
    if not section_match:
        return []
    section = section_match.group(1)

    rows: list[dict[str, Any]] = []
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("|") or not line.endswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 6:
            continue
        if cells[0] in ("#", "") or set(cells[0]) <= {"-"}:
            continue
        num, summary, source, severity, root_cause, priority_hint = cells
        rows.append(
            {
                "number": num,
                "summary": summary,
                "source": source,
                "severity": severity,
                "root_cause": root_cause,
                "priority_hint": priority_hint,
            }
        )
    return rows


def _severity_rank(severity_text: str) -> str | None:
    if "高" in severity_text:
        return "high"
    if "中" in severity_text:
        return "medium"
    if "低" in severity_text:
        return "low"
    return None


def _is_resolved(row: dict[str, Any]) -> bool:
    combined = f"{row.get('summary', '')} {row.get('severity', '')}"
    return any(keyword in combined for keyword in _RESOLVED_KEYWORDS)


def build_recurring_problem_items(bug_rows: list[dict[str, Any]]) -> list[EvidenceItem]:
    """bug_inventory.mdの問題一覧表から、「同種の問題が複数回記録されて
    いるもの」を抽出する。

    判断根拠(「複数回記録」の判定方法): 各行の「出典」列には、その問題が
    言及されている報告書ファイル名(例: phase_b9_report.md)が記載されて
    いる。1件の行に**異なる複数の`.md`ファイル名が登場する場合**、それは
    「同種の問題が複数の独立した報告書で繰り返し指摘されている」ことを
    意味する(実例: bug_inventory.md #6「B群6機能が同一パイプラインを
    重複実装」は phase_b9_report.md・phase_b16_report.md・
    phase_b_summary.mdの3つに渡って言及されている)。一方「本タスク2.1節」
    のような自己参照(bug_inventory.md自身の章番号)は`.md`ファイル名を
    含まないため、この判定には数えられない——「今回新規発見した」問題と
    「以前から繰り返し記録されている」問題を区別する、シンプルな基準。

    解決済み(概要・深刻度に「修正済み」等の記載がある)行は除外する
    ——依頼書「実際の改良案の生成は次のタスク」の範囲外である、既に
    対応済みの事項をD-2に渡す意味がないため。
    """
    items: list[EvidenceItem] = []
    for row in bug_rows:
        if _is_resolved(row):
            continue
        source_files = set(_SOURCE_MD_FILENAME_RE.findall(row.get("source", "")))
        if len(source_files) < 2:
            continue
        severity = _severity_rank(row.get("severity", ""))
        severity_weight = {"high": 3, "medium": 2, "low": 1}.get(severity, 0)
        priority_score = severity_weight + 1  # +1は「複数回記録」自体のボーナス
        items.append(
            EvidenceItem(
                category="recurring_problem",
                source_system="bug_inventory",
                title=f"[#{row.get('number')}] {row.get('summary', '')[:60]}",
                description=row.get("summary", ""),
                severity=severity,
                priority_score=priority_score,
                details={
                    "number": row.get("number"),
                    "source": row.get("source"),
                    "source_files": sorted(source_files),
                    "root_cause": row.get("root_cause"),
                    "priority_hint": row.get("priority_hint"),
                },
            )
        )
    return items


def aggregate_evidence(
    *,
    rc_runs: list[dict[str, Any]],
    grounding_runs: list[dict[str, Any]],
    mastery_experiences: list[dict[str, Any]],
    bug_inventory_markdown: str | None,
) -> EvidenceBundle:
    """4つの既存資産から根拠を集約し、優先順位付けした上で1つの
    EvidenceBundleにまとめる。優先順位は`priority_score`降順(同点の場合は
    元の順序を保つ、Timsortの安定ソート特性に依存)。"""
    items: list[EvidenceItem] = []
    items.extend(build_metric_degradation_items(rc_runs, grounding_runs))
    items.extend(build_mastery_proposal_items(mastery_experiences))

    bug_rows: list[dict[str, Any]] = []
    if bug_inventory_markdown:
        bug_rows = parse_bug_inventory_table(bug_inventory_markdown)
        items.extend(build_recurring_problem_items(bug_rows))

    items.sort(key=lambda item: item.priority_score, reverse=True)

    return EvidenceBundle(
        items=items,
        sources_checked={
            "phase_r_runs": len(rc_runs),
            "phase_g_runs": len(grounding_runs),
            "mastery_proposals": len(mastery_experiences),
            "bug_inventory_rows": len(bug_rows),
        },
    )
