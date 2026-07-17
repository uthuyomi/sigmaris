# 役割: Phase F-1「仮説からコード差分への変換」の中核ロジック——LLMに
# よる差分生成(1件のみのLLM呼び出し)と、生成された差分に対する、
# 機械的な安全性チェック(LLM呼び出しなし)。
#
# 【絶対原則、このファイル・呼び出し元のいずれにも実装しないこと】
# 本モジュールが生成する差分は、テキストとして組み立てられ、DBへ
# "承認待ち"として保存されるだけである。**このファイル、および
# code_diff_generation_runner.py・code_diff_proposal_store.py・
# scripts/run_code_diff_generation.pyのいずれにも、git add/commit/
# push/PR作成に相当する処理は一切実装しない。** `subprocess`・`git`
# コマンド呼び出し・GitHub API呼び出しのいずれも、この4ファイル群には
# 存在しない(依頼書「絶対原則」への直接対応、テストで実測証明する、
# レポート参照)。

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.services.local_llm import TaskType, get_llm_router
from app.services.safety_critical_files import get_safety_mechanism_file_patterns

logger = logging.getLogger(__name__)

# ── 1. 差分生成 ──────────────────────────────────────────────────────────

_GENERATION_SYSTEM = (
    "あなたはシグマリス(AIアシスタント)のコード改良案を、統一diff形式で"
    "組み立てる、設計担当のアシスタントです。"
    "与えられた改良仮説と、対象ファイルの現在の内容だけを根拠に、"
    "その仮説が示す方向性を反映した、最小限の変更を提案してください。"
    "変更は、示された1ファイルの中に完結させ、他のファイルへの変更は"
    "含めないでください。"
    "認証情報・秘密鍵・CI/CD設定への変更を、絶対に提案しないでください。"
    "出力は、`--- a/<path>`と`+++ b/<path>`から始まる、標準的な統一diff"
    "形式のみとし、説明文やコードフェンスは含めないでください。"
)

# 対象ファイルの内容が、これを超える場合は、diff生成自体を見送る
# (判断根拠、レポート参照): 大きなファイルの一部だけをプロンプトに
# 切り詰めて渡すと、LLMが実際には存在しない周辺コードを幻視して
# 不正確なdiffを生成するリスクが高まる。無理に生成させるより、
# 「対象ファイルが大きすぎる」という明示的な結果にとどめる方が安全、
# という判断(D-2のis_vague_or_unsupported()と同じ、無理をしない設計)。
MAX_FILE_CHARS_FOR_DIFF = 12000


def build_diff_generation_prompt(
    *, hypothesis_title: str, what_is_problem: str, why_problem: str, how_to_improve: str, target_file: str, file_content: str
) -> str:
    return (
        f"## 改良仮説\n"
        f"タイトル: {hypothesis_title}\n"
        f"何が問題か: {what_is_problem}\n"
        f"なぜ問題か: {why_problem}\n"
        f"どう改善するか: {how_to_improve}\n\n"
        f"## 対象ファイル: {target_file}\n"
        f"```\n{file_content}\n```\n\n"
        f"上記の仮説が示す方向性を反映した、最小限の変更を、{target_file}に対する"
        "統一diff形式で提案してください。"
    )


@dataclass
class GeneratedDiff:
    diff_text: str
    target_file: str


async def generate_diff(
    *,
    hypothesis_title: str,
    what_is_problem: str,
    why_problem: str,
    how_to_improve: str,
    target_file: str,
    file_content: str,
) -> GeneratedDiff | None:
    """1件の仮説・1件の対象ファイルから、統一diff形式のテキストを生成
    する。**このテキストは、どのファイルにも適用しない、DBへ保存される
    だけの文字列である。** 失敗時はNone(fail-open、このコードベース
    一貫のベストエフォート方針)。"""
    if len(file_content) > MAX_FILE_CHARS_FOR_DIFF:
        logger.warning(
            "code_diff_generation: target_file=%s exceeds MAX_FILE_CHARS_FOR_DIFF, skipping generation",
            target_file,
        )
        return None

    try:
        router = get_llm_router()
        raw = await router.chat(
            TaskType.CODE_DIFF_GENERATION,
            [
                {"role": "system", "content": _GENERATION_SYSTEM},
                {
                    "role": "user",
                    "content": build_diff_generation_prompt(
                        hypothesis_title=hypothesis_title,
                        what_is_problem=what_is_problem,
                        why_problem=why_problem,
                        how_to_improve=how_to_improve,
                        target_file=target_file,
                        file_content=file_content,
                    ),
                },
            ],
            temperature=0.2,
            max_tokens=1500,
        )
    except Exception:
        logger.exception("code_diff_generation: generate_diff failed")
        return None

    diff_text = (raw or "").strip()
    if not diff_text or "---" not in diff_text or "+++" not in diff_text:
        logger.warning("code_diff_generation: generated output does not look like a unified diff, discarding")
        return None

    return GeneratedDiff(diff_text=diff_text, target_file=target_file)


# ── 2. 安全性チェック(LLM呼び出しなし、機械的な照合のみ) ─────────────

# 旧self_improvement.py(削除済み、docs/sigmaris/phase_d_report.mdの
# self_improvement.py削除節参照)が持っていたブロックリストの考え方を、
# そのまま再利用した。認証情報・秘密鍵・CI/CD設定・依存関係マニフェスト
# への変更を、機械的に拒否する。
_BLOCKED_FILE_PATTERNS: tuple[str, ...] = (
    r"\.env", r"env\.example", r"secret", r"credential", r"password",
    r"\.pem$", r"\.key$", r"\.p12$", r"\.pfx$",
    r"auth\.py$", r"jwt_manager\.py$", r"config\.py$", r"settings\.py$",
    r"\.github/",
    r"requirements.*\.txt$", r"pyproject\.toml$", r"setup\.py$",
    r"package\.json$", r"package-lock\.json$",
    r"dockerfile", r"docker-compose", r"nginx\.conf",
)

# S-4(docs/sigmaris/phase_s_report.md 28.1節)の「最後の砦」棚卸し結果を
# そのまま再利用した——D-2のrule_based_safety_flag()が仮説の"文章"を
# 対象にしたのと同じキーワード源を、ここでは"生成された差分の対象ファイル
# パス"に対して適用する。新しい安全機構リストは作らない。
#
# 【Safety-2追記(docs/sigmaris/safety_governance_report.md)】このタプル
# は、以前はこのファイルへ直接ハードコードされていたが、hypothesis_
# generation.py::_SAFETY_MECHANISM_KEYWORDSと内容がほぼ同一であるにも
# かかわらず独立して更新されており、F-3で新設されたdiff_approval.py等が
# どちらのリストにも反映されていない、という具体的な抜けをSafety-1が
# 実測で発見した(check_diff_safety()を直接呼び出し、diff_approval.py
# 等が誤ってpassed判定になることを確認した)。単一の正典(safety_
# critical_files.py)へ統合し、両ファイルがそこを参照する形に変更した
# ——値・照合ロジック(下記check_diff_safety()のre.search(pattern,
# normalized))は一切変更していない。
_SAFETY_MECHANISM_FILE_PATTERNS: tuple[str, ...] = get_safety_mechanism_file_patterns()

_DIFF_PATH_RE = re.compile(r"^\+\+\+ b/(.+)$", re.MULTILINE)


def extract_diff_target_paths(diff_text: str) -> set[str]:
    """統一diffの`+++ b/<path>`行から、実際に変更対象とされているファイル
    パスを全て抽出する。LLMが依頼された1ファイルの範囲を超えて、別の
    ファイルへの変更を紛れ込ませていないかを確認するために使う——
    生成プロンプト自体が「1ファイルに限定」を指示しているが、指示だけに
    頼らず機械的に検証する(判断根拠、レポート参照)。"""
    return set(_DIFF_PATH_RE.findall(diff_text))


@dataclass
class SafetyCheckResult:
    status: str  # "passed" | "blocked_sensitive_file" | "blocked_safety_mechanism" | "blocked_unexpected_target"
    reason: str


def check_diff_safety(diff_text: str, *, expected_target_file: str) -> SafetyCheckResult:
    """生成された差分に対する、機械的な安全性チェック(LLM呼び出し
    なし)。要件4「機密ファイル・Constitution違反に該当しないか」への
    対応。判定の優先順位:
      1. 機密ファイルへの変更(ブロックリスト) → blocked_sensitive_file
      2. 安全機構ファイルへの変更 → blocked_safety_mechanism
      3. 依頼した対象ファイル以外への変更が紛れ込んでいる →
         blocked_unexpected_target(LLMが指示を逸脱した兆候であり、
         内容を精査せず一律で拒否する——「1ファイルに限定する」という
         生成時の指示自体が、安全性チェックの一部でもあるため)
      4. 上記いずれにも該当しない → passed
    """
    target_paths = extract_diff_target_paths(diff_text)
    all_paths = target_paths | {expected_target_file}

    for path in all_paths:
        normalized = path.replace("\\", "/").lower()
        for pattern in _BLOCKED_FILE_PATTERNS:
            if re.search(pattern, normalized):
                return SafetyCheckResult(
                    status="blocked_sensitive_file",
                    reason=f"差分が機密性の高いファイル「{path}」に触れている(パターン: {pattern})",
                )

    for path in all_paths:
        normalized = path.replace("\\", "/")
        for pattern in _SAFETY_MECHANISM_FILE_PATTERNS:
            if re.search(pattern, normalized):
                return SafetyCheckResult(
                    status="blocked_safety_mechanism",
                    reason=f"差分が既存の安全機構ファイル「{path}」に触れている(Constitution/S-4の管理対象)",
                )

    if target_paths and target_paths != {expected_target_file}:
        return SafetyCheckResult(
            status="blocked_unexpected_target",
            reason=f"生成された差分が、依頼したファイル({expected_target_file})以外を対象にしている: {sorted(target_paths)}",
        )

    return SafetyCheckResult(status="passed", reason="")
