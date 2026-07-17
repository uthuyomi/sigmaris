# 役割: Phase E-1「静的検証パイプライン」の純粋なロジック(I/Oなし)。
#
# D-3が優先順位付けした仮説(sigmaris_hypothesis_priorities、track="normal"
# のみ)を対象に、「実際にコードを一切書き換えず」、以下の2つだけを行う。
#   1. マイグレーション(DBスキーマ変更)を伴う仮説を、キーワードベースで
#      検出し、本パイプラインの対象から除外する
#   2. 仮説の文面から、それが触れていそうなSigmarisのモジュールを推定し、
#      既存のbackend/tests/がそのモジュールを実際にカバーしているかを
#      照合する(=「この領域には、少なくとも何らかの既存テストがある」
#      という、参考情報にとどまる軽量なシグナル)
#
# 【最重要】本モジュールは、いかなる意味でも「コードを変更する」処理を
# 一切含まない。仮説の内容通りにコードを書き換えてテストを実行する、
# という行為(依頼書が絶対に行わないよう明示的に禁じている)は、
# この静的検証パイプライン全体を通じて一度も発生しない——ここで行うのは
# (a) 既存の(変更していない)テストスイートをそのまま実行するベースライン
# 確認、(b) 仮説のテキストと、既存テストファイルのimport文という、
# いずれも読み取り専用の情報を突き合わせるだけの、テキストレベルの
# 照合である。
#
# 【判断根拠(「合格/不合格」という二値判定にしなかった理由)】
# 依頼書は検証結果の例として「合格、不合格、検証不能等」を挙げているが、
# 実際にコードを実行しない静的検証だけでは、「この仮説の変更が正しい」
# ことも「間違っている」ことも証明できない。そのため本パイプラインは、
# 「ある仮説の対象領域に、既存の回帰テストが存在するかどうか」という、
# 誠実に主張できる範囲の情報だけを返す3値の判定にした——G-5の
# Search Trigger Rateが自らを「下限近似値」と明記した、Phase R-2の
# RC-1が「evaluated_not_promoted」を安易にhealthy/unhealthyと決めつけ
# なかったのと同じ、「この手法で言えることの限界を、判定結果自体に
# 正直に反映する」という、このコードベース一貫の設計哲学を踏襲した。

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import Any

# D-2のrule_based_safety_flag()と同じ「安全側に倒すキーワード一致」方式。
# マイグレーションに言及していそうな仮説を、意味解析なしで検出する。
_MIGRATION_KEYWORDS: tuple[str, ...] = (
    "マイグレーション", "migration",
    "スキーマ変更", "db schema", "データベーススキーマ",
    "alter table", "create table", "drop table", "drop column",
    "テーブルを追加", "テーブルを新設", "カラムを追加", "列を追加",
    "supabase/migrations", ".sql",
)


def mentions_migration(hypothesis: dict[str, Any]) -> tuple[bool, str]:
    """(マイグレーションに言及しているか, 理由)を返す。依頼書の方針
    (`docs/sigmaris/phase_e_report.md` 3.2節)に従い、マイグレーションを
    伴う仮説は、静的検証パイプラインの対象から常に除外する——自動検証
    できるのはアプリケーションコードのロジックのみであり、DBスキーマの
    変更は本番Supabaseと共有の環境である以上、この段階(E-1)では一切
    扱わない。"""
    haystack = " ".join(
        str(hypothesis.get(field_name) or "")
        for field_name in ("title", "what_is_problem", "why_problem", "how_to_improve")
    ).lower()
    for keyword in _MIGRATION_KEYWORDS:
        if keyword in haystack:
            return True, f"マイグレーション関連キーワード「{keyword}」に言及"
    return False, ""


# 仮説の自由文から、Sigmarisのモジュール名らしきトークンを拾うための
# 簡易正規表現。意味解析は行わない(D-2のevidence_aggregation.py::
# _tokenize_for_overlap()と同じ判断根拠——新しい重量級の依存を追加せず、
# 既存の「簡易トークン化+既知の語彙との突き合わせ」パターンをそのまま
# 踏襲した)。
#
# 【重要】`\b`(単語境界)は使わない。Phase G-1(search_trigger.py、
# docs/sigmaris/phase_g_report.md)で実際に踏んだ既知の落とし穴と同じ
# 理由——Pythonの`re`モジュールはデフォルト(Unicodeモード)で日本語文字も
# `\w`とみなすため、"response_guardの改善"のように、識別子の直後に
# 日本語が(区切り文字なしで)続く実際のテキストでは、`\b`がASCII識別子と
# 日本語の境界で成立せず、トークン全体がマッチしなくなる。文字クラス
# `[a-z][a-z0-9_]{3,}`自体が既にトークンの範囲を過不足なく規定している
# ため、`\b`が無くても誤って長い識別子の一部だけを拾う心配はない。
_IDENTIFIER_RE = re.compile(r"[a-z][a-z0-9_]{3,}")


def extract_candidate_modules(hypothesis: dict[str, Any]) -> set[str]:
    """仮説のtitle/what_is_problem/why_problem/how_to_improve、および
    source_evidenceのtitleから、Pythonの識別子らしきトークン(snake_case、
    4文字以上)を抽出する。`.py`拡張子が付いている場合は取り除く。

    判断根拠(なぜ「らしきトークン」全てを拾うのか): D-2の生成プロンプトは
    「対象ファイル名」を明示的に出力させていない(target_filesはPhase E
    向けの未設定プレースホルダ、D-3報告書20章参照)。そのため、仮説の
    自由文からモジュール名を確実に特定する手段が無く、幅広く候補を拾った
    上で、次段のカバレッジ照合(既知のモジュール名と一致するかどうか)で
    絞り込む、という二段階の設計にした。
    """
    text_parts = [
        str(hypothesis.get(field_name) or "")
        for field_name in ("title", "what_is_problem", "why_problem", "how_to_improve")
    ]
    source_evidence = hypothesis.get("source_evidence")
    if isinstance(source_evidence, dict):
        text_parts.append(str(source_evidence.get("title") or ""))

    combined = " ".join(text_parts)
    tokens = {t.removesuffix(".py") for t in _IDENTIFIER_RE.findall(combined.lower())}
    return tokens


def parse_imported_app_modules(source_code: str) -> set[str]:
    """1つのテストファイルのソースコード文字列から、`app.services.*`/
    `app.routes.*`配下のモジュールのベース名(最後のドットセグメント)を
    抽出する。`ast.parse()`のみを使う——コードは一切実行しない、純粋な
    構文解析(依頼書「実際にコードを動かさない」の徹底)。

    パース自体が失敗した場合(構文エラー等)は空集合を返す(fail-open、
    既存の全モジュールと同じベストエフォート方針)。
    """
    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return set()

    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app."):
            modules.add(node.module.rsplit(".", 1)[-1])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("app."):
                    modules.add(alias.name.rsplit(".", 1)[-1])
    return modules


@dataclass
class BaselineResult:
    passed: bool
    summary: str
    return_code: int | None = None


@dataclass
class StaticVerificationResult:
    hypothesis_id: str | None
    hypothesis_priority_id: str | None
    verdict: str  # "excluded_migration" | "baseline_unhealthy" | "insufficient_signal" | "baseline_healthy_with_coverage"
    matched_modules: list[str]
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


def assess_hypothesis(
    hypothesis: dict[str, Any], *, coverage_index: dict[str, list[str]], baseline: BaselineResult
) -> StaticVerificationResult:
    """1件の仮説(D-3のphase_e_handoffペイロード)を評価する。

    判定の優先順位(判断根拠): (1)マイグレーション言及 → 常に除外
    (baselineの状態に関わらず、これは「静的検証の対象外」という別種の
    判定であるため最優先)。(2)baseline自体が不健全 → その仮説固有の
    情報を評価しても無意味なので、baseline_unhealthyで統一する。
    (3)候補モジュールが既存テストのカバレッジと1件でも一致 →
    baseline_healthy_with_coverage。(4)一致なし →
    insufficient_signal(依頼書の「合格」に対応する、最も楽観的な結果
    でも、あくまで「既存テストが実行できる状態で、対象領域に何らかの
    テストが存在する」という限定的な意味しか持たないことを、この
    3値の名前自体に反映した)。
    """
    hyp_id = hypothesis.get("hypothesis_id")
    priority_id = hypothesis.get("id")

    is_migration, migration_reason = mentions_migration(hypothesis)
    if is_migration:
        return StaticVerificationResult(
            hypothesis_id=hyp_id,
            hypothesis_priority_id=priority_id,
            verdict="excluded_migration",
            matched_modules=[],
            reason=migration_reason,
        )

    if not baseline.passed:
        return StaticVerificationResult(
            hypothesis_id=hyp_id,
            hypothesis_priority_id=priority_id,
            verdict="baseline_unhealthy",
            matched_modules=[],
            reason=f"既存テストスイート自体が現在失敗している状態のため、個別の仮説を評価できない: {baseline.summary}",
        )

    candidates = extract_candidate_modules(hypothesis)
    matched = sorted(candidates & coverage_index.keys())

    if matched:
        return StaticVerificationResult(
            hypothesis_id=hyp_id,
            hypothesis_priority_id=priority_id,
            verdict="baseline_healthy_with_coverage",
            matched_modules=matched,
            reason=f"既存テストスイートは正常に通過しており、対象領域と推定される{', '.join(matched)}に既存のテストが存在する",
            details={"covering_test_files": {m: coverage_index[m] for m in matched}},
        )

    return StaticVerificationResult(
        hypothesis_id=hyp_id,
        hypothesis_priority_id=priority_id,
        verdict="insufficient_signal",
        matched_modules=[],
        reason="既存テストスイートは正常に通過しているが、この仮説が触れると推定される領域を"
        "カバーする既存テストが見つからない(=この静的検証では何も言えない、実装前に人間の確認を推奨)",
    )
