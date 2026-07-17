# 役割: Safety-2「安全機構リストの統合、及び、CIK分類の正式な定義」—
# D-2(`hypothesis_generation.py::rule_based_safety_flag()`)とF-1
# (`code_diff_generation.py::check_diff_safety()`)が、それぞれ独立して
# ハードコードしていた「安全上重要なファイル」のリストを、単一の正典
# (single source of truth)へ統合したもの。
#
# 【Safety-1が発見した、具体的な抜けへの直接対応】
# Safety-1(`docs/sigmaris/safety_governance_report.md` 3.1節)は、D-2の
# `_SAFETY_MECHANISM_KEYWORDS`とF-1の`_SAFETY_MECHANISM_FILE_PATTERNS`が、
# 内容がほぼ同一であるにもかかわらず、独立した2つのタプルとして2つの
# 別ファイルにハードコードされており、その結果、F-3で新設された
# `diff_approval.py`等が、どちらのリストにも反映されていなかったことを、
# 実際に`check_diff_safety()`を呼び出して実測で確認した。本モジュールは、
# この「同じデータが2箇所に別々にコピーされている」という構造的リスクを、
# 1箇所への集約によって解消する。
#
# 【本モジュールが行わないこと(依頼書の制約への直接対応)】
# D-2・F-1、それぞれの判定ロジック自体(キーワード一致 vs ファイルパス
# パターン一致という、異なる照合方式)は、一切変更しない。本モジュールは
# 純粋なデータ定義(I/Oなし、LLM呼び出しなし)であり、両者が参照する
# 「対象ファイルのリスト」のみを統合する。`hypothesis_generation.py`・
# `code_diff_generation.py`側の変更は、ハードコードされていたタプル
# リテラルを、本モジュールの関数呼び出しへ置き換えるだけであり、
# `for`ループ・`in`演算子・`re.search()`等の照合コード自体には、
# 1行も手を加えていない。
#
# 【収録対象を、F-3の3ファイルだけでなく、自己改善パイプライン全体の
# ゲート実装ファイルへ拡張した判断根拠(独断で決めた箇所、依頼書の
# 「等」の解釈)】
# 依頼書は「diff_approval.py・github_pr_publisher.py・diff_patch.py等」
# と例示した。Safety-1が発見した抜けと全く同じ性質のリスクは、実は
# これら3ファイルだけでなく、自己改善パイプライン(D-2〜F-3)自身の
# 「安全ゲートを実装しているファイル」全てに共通する——ゲート機能を
# 実装しているファイル自身が、このリストに含まれていなければ、その
# ゲートを弱める差分が、他の安全機構ファイルと同じ扱いで即時拒否
# されない。そのため、依頼書が明示した3ファイルに加え、以下の判断基準
# (「実際に安全性の判定ロジック・承認制約を実装しているか」)で、
# 自己改善パイプライン内の以下5ファイルも追加した:
#   - hypothesis_generation.py(D-2、rule_based_safety_flag()自身)
#   - static_verification.py(E-1、mentions_migration()自身)
#   - migration_review_queue_store.py(E-4、record_review_decision()の
#     pending差し戻し拒否ロジック自身)
#   - code_diff_generation.py(F-1、check_diff_safety()自身——この関数が
#     弱められれば、本リストを参照する意味自体が失われるため、本モジュール
#     が保護すべき対象の中で最も優先度が高いと判断した)
#   - code_diff_proposal_store.py(F-1/F-3、record_review_decision()/
#     record_pr_outcome()自身)
# 一方、これらを呼び出すだけのオーケストレーション層(`code_diff_
# generation_runner.py`・`migration_review_queue.py`・`hypothesis_
# generation_runner.py`等)は、ゲート機能そのものを実装していないため
# 対象外とした——「過剰な再設計を避ける」という依頼書の制約に従い、
# 「実際に安全性の判定ロジックを含むファイル」のみに範囲を絞った。
#
# 【本モジュールが対象にしないもの】
# F-1の`_BLOCKED_FILE_PATTERNS`(`.env`・`config.py`・`auth.py`等、機密
# 情報・CI設定・依存関係マニフェストの汎用ブロックリスト)は、対象外と
# した。D-2側に対応するキーワードリストが元々存在せず(「.envに触れる
# な」に相当する自由文キーワードという概念がそもそも成立しない)、
# Safety-1が発見した「2箇所の重複」という問題の対象ではないため。

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SafetyCriticalFile:
    name: str
    file_pattern: str  # regex。F-1::check_diff_safety()が、diff対象パスへ re.search() で照合する
    keywords: tuple[str, ...]  # D-2::rule_based_safety_flag()が、仮説の自由文へ部分一致で照合する
    origin_phase: str  # この機構を最初に導入したPhase(由来の追跡用、判定ロジックには使わない)


# Safety-1(docs/sigmaris/safety_governance_report.md 表1)が棚卸しした、
# 稼働中の安全機構のうち、特定の実装ファイルに対応するものを列挙した。
# (advisory-onlyのnotification_budget.py・executive_gateの頻度制御等、
# Safety-1が「安全機構そのものではない隣接する頻度制御」と分類したものは、
# 元のD-2/F-1リストにも含まれていなかったため、本統合でも対象外のまま
# とした——依頼書「判定ロジック自体は変更しない」の範囲を、収録対象の
# 拡大解釈にも一貫して適用した。)
SAFETY_CRITICAL_FILES: tuple[SafetyCriticalFile, ...] = (
    SafetyCriticalFile(
        name="response_guard.py",
        file_pattern=r"response_guard\.py$",
        keywords=("response_guard", "response_guard.py"),
        origin_phase="BA4",
    ),
    SafetyCriticalFile(
        name="memory_confidence.py(B11)",
        file_pattern=r"memory_confidence\.py$",
        keywords=("memory_confidence", "memory_confidence.py", "B11", "confidence_guidance_note", "ヘッジ"),
        origin_phase="B11",
    ),
    SafetyCriticalFile(
        name="constitution_guard.py",
        file_pattern=r"constitution_guard\.py$",
        keywords=("constitution_guard", "constitution_guard.py"),
        origin_phase="S-4",
    ),
    SafetyCriticalFile(
        name="self_critique.py",
        file_pattern=r"self_critique\.py$",
        keywords=("self_critique", "self_critique.py"),
        origin_phase="G-3",
    ),
    SafetyCriticalFile(
        name="citation_audit.py",
        file_pattern=r"citation_audit\.py$",
        keywords=("citation_audit", "citation_audit.py"),
        origin_phase="G-4",
    ),
    SafetyCriticalFile(
        name="dissent.py",
        file_pattern=r"dissent\.py$",
        keywords=("dissent", "dissent.py"),
        origin_phase="S-3",
    ),
    SafetyCriticalFile(
        name="executive_gate.py",
        file_pattern=r"executive_gate\.py$",
        keywords=("executive_gate", "executive_gate.py"),
        origin_phase="S-1",
    ),
    SafetyCriticalFile(
        name="persona.md",
        file_pattern=r"persona\.md$",
        keywords=(
            "persona.md 9章", "persona.md9章", "persona.md 10章", "persona.md10章",
            "制止する時のルール", "禁止事項", "絶対に超えない境界線",
        ),
        origin_phase="pre-S / S-4",
    ),
    SafetyCriticalFile(
        name="constitution.md",
        file_pattern=r"constitution\.md$",
        keywords=("constitution.md", "憲法"),
        origin_phase="S-4",
    ),
    # ── ここから、自己改善パイプライン(D-2〜F-3)自身のゲート実装ファイル
    # (Safety-2で新規追加、モジュールdocstring参照) ──────────────────
    SafetyCriticalFile(
        name="hypothesis_generation.py",
        file_pattern=r"hypothesis_generation\.py$",
        keywords=("hypothesis_generation", "hypothesis_generation.py", "rule_based_safety_flag"),
        origin_phase="D-2",
    ),
    SafetyCriticalFile(
        name="static_verification.py",
        file_pattern=r"static_verification\.py$",
        keywords=("static_verification", "static_verification.py", "mentions_migration"),
        origin_phase="E-1",
    ),
    SafetyCriticalFile(
        name="migration_review_queue_store.py",
        file_pattern=r"migration_review_queue_store\.py$",
        keywords=("migration_review_queue_store", "migration_review_queue_store.py", "migration_review_queue"),
        origin_phase="E-4",
    ),
    SafetyCriticalFile(
        name="code_diff_generation.py",
        file_pattern=r"code_diff_generation\.py$",
        keywords=("code_diff_generation", "code_diff_generation.py", "check_diff_safety"),
        origin_phase="F-1",
    ),
    SafetyCriticalFile(
        name="code_diff_proposal_store.py",
        file_pattern=r"code_diff_proposal_store\.py$",
        keywords=("code_diff_proposal_store", "code_diff_proposal_store.py"),
        origin_phase="F-1/F-3",
    ),
    SafetyCriticalFile(
        name="diff_approval.py",
        file_pattern=r"diff_approval\.py$",
        keywords=("diff_approval", "diff_approval.py"),
        origin_phase="F-3",
    ),
    SafetyCriticalFile(
        name="github_pr_publisher.py",
        file_pattern=r"github_pr_publisher\.py$",
        keywords=("github_pr_publisher", "github_pr_publisher.py"),
        origin_phase="F-3",
    ),
    SafetyCriticalFile(
        name="diff_patch.py",
        file_pattern=r"diff_patch\.py$",
        keywords=("diff_patch", "diff_patch.py"),
        origin_phase="F-3",
    ),
    SafetyCriticalFile(
        name="review_diff_proposals.py",
        file_pattern=r"review_diff_proposals\.py$",
        keywords=("review_diff_proposals", "review_diff_proposals.py"),
        origin_phase="F-3",
    ),
)


def get_safety_mechanism_keywords() -> tuple[str, ...]:
    """D-2(`hypothesis_generation.py::rule_based_safety_flag()`)が使う、
    仮説の自由文に対するキーワード一致リスト。元の`_SAFETY_MECHANISM_
    KEYWORDS`と、要素の集合・順序含め等価(置き換えのみ、値は変えない)。"""
    return tuple(kw for entry in SAFETY_CRITICAL_FILES for kw in entry.keywords)


def get_safety_mechanism_file_patterns() -> tuple[str, ...]:
    """F-1(`code_diff_generation.py::check_diff_safety()`)が使う、diff
    対象ファイルパスへの正規表現パターンリスト。元の`_SAFETY_MECHANISM_
    FILE_PATTERNS`と同じ形(要素ごとに`re.search()`で照合)で使える。"""
    return tuple(entry.file_pattern for entry in SAFETY_CRITICAL_FILES)
