# 役割: Phase D-2「仮説生成」の中核ロジック — D-1が集約した根拠
# (evidence_aggregation.EvidenceItem)1件から、具体的な改良仮説を1件、
# LLMで生成し、(a) 抽象的/根拠なし仮説を除外するルールベースのフィルタ、
# (b) 根拠との論理的対応関係を確認するSelf-Critique方式の検証、
# (c) 既存の安全機構(Constitution/S-4)に触れる仮説の検出、を行う。
#
# 【重要】本モジュールは仮説を生成するのみ。実際のコード変更・実行・
# 承認フローの実行は一切行わない(要件5)。
#
# 設計の前例: Phase G-3(self_critique.py)の「生成とは独立した視点(批評家)
# による検証」パターンを、仮説生成にもそのまま応用した(依頼書「Phase Gで
# 確立した、Self-Critique検証の考え方を、応用できないか検討する」への
# 直接対応)。仮説生成そのものはTaskType.HYPOTHESIS_GENERATION(advanced
# tier — 自己反省・設計相当の推論であり、G-1〜G-4のnano-tier分類とは
# 性質が異なる)、対応関係の検証はTaskType.HYPOTHESIS_CRITIQUE(nano tier
# — G-3のSELF_CRITIQUEと同じ「簡易チェック」の位置づけ)。

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.services.evidence_aggregation import EvidenceItem
from app.services.local_llm import TaskType, get_llm_router

logger = logging.getLogger(__name__)

# ── 1. 仮説生成 ──────────────────────────────────────────────────────────

_GENERATION_SYSTEM = (
    "あなたはシグマリス(AIアシスタント)の改良仮説を組み立てる、設計担当のアシスタントです。"
    "与えられた根拠(evidence)1件だけを土台にして、具体的だが実装詳細ではない、"
    "改良の方向性を1つ提案してください。"
    "根拠に書かれていない事実を捏造しないこと。"
    "「もっと良くする」「最適化する」のような、内容のない抽象的な提案は禁止です。"
    "この提案が、既存の安全機構(矛盾検証・確信度ヘッジ・引用監査・Constitution/憲法の"
    "承認フロー等)を緩和・無効化・バイパスする内容を含む場合は、touches_safety_mechanism"
    "を必ずtrueにしてください——それ自体を提案してはいけないという意味ではなく、"
    "正直に自己申告することが重要です。必ず有効なJSONのみを返してください。"
)

_MAX_EVIDENCE_DETAIL_CHARS = 1200


def _format_evidence_for_prompt(item: EvidenceItem) -> str:
    details_json = json.dumps(item.details, ensure_ascii=False)[:_MAX_EVIDENCE_DETAIL_CHARS]
    return (
        f"category: {item.category}\n"
        f"source_system: {item.source_system}\n"
        f"title: {item.title}\n"
        f"description: {item.description}\n"
        f"severity: {item.severity}\n"
        f"details: {details_json}"
    )


def _build_generation_prompt(item: EvidenceItem) -> str:
    return (
        "以下の根拠(evidence)1件だけを土台に、改良仮説を1つ組み立ててください。\n\n"
        f"## 根拠\n{_format_evidence_for_prompt(item)}\n\n"
        "JSON形式で返してください:\n"
        "{\n"
        '  "title": "短い見出し(1文)",\n'
        '  "what_is_problem": "何が問題か(根拠の要約)",\n'
        '  "why_problem": "なぜそれが問題と考えられるか",\n'
        '  "how_to_improve": "どう改善すればよいか、という具体的な方向性'
        '(実装の詳細設計ではなく、提案の段階にとどめること)",\n'
        '  "expected_metric_improvements": ["この仮説の実行で改善が期待できる'
        'RC指標・Phase G指標の名前(例: RC-1, Citation Precision)。分からなければ空配列"],\n'
        '  "touches_safety_mechanism": true または false,\n'
        '  "safety_mechanism_note": "touches_safety_mechanismがtrueの場合、'
        'どの安全機構にどう関わるかを1文で。falseの場合は空文字"\n'
        "}"
    )


@dataclass
class GeneratedHypothesis:
    title: str
    what_is_problem: str
    why_problem: str
    how_to_improve: str
    expected_metric_improvements: list[str]
    touches_safety_mechanism_self_reported: bool
    safety_mechanism_note: str


async def generate_hypothesis(item: EvidenceItem) -> GeneratedHypothesis | None:
    """根拠1件からLLMで仮説を1件生成する。失敗時はNone(fail-open、
    このコードベース一貫のベストエフォート方針)。"""
    try:
        router = get_llm_router()
        raw = await router.chat(
            TaskType.HYPOTHESIS_GENERATION,
            [
                {"role": "system", "content": _GENERATION_SYSTEM},
                {"role": "user", "content": _build_generation_prompt(item)},
            ],
            temperature=0.4,
            max_tokens=700,
            json_mode=True,
        )
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(parsed, dict):
            return None
    except Exception:
        logger.exception("hypothesis_generation: generate_hypothesis failed")
        return None

    title = str(parsed.get("title") or "").strip()
    what_is_problem = str(parsed.get("what_is_problem") or "").strip()
    why_problem = str(parsed.get("why_problem") or "").strip()
    how_to_improve = str(parsed.get("how_to_improve") or "").strip()
    if not title or not what_is_problem or not how_to_improve:
        logger.warning("hypothesis_generation: generated hypothesis missing required fields, discarding")
        return None

    raw_metrics = parsed.get("expected_metric_improvements")
    expected_metrics = [str(m) for m in raw_metrics if isinstance(m, (str, int, float))] if isinstance(raw_metrics, list) else []

    return GeneratedHypothesis(
        title=title,
        what_is_problem=what_is_problem,
        why_problem=why_problem,
        how_to_improve=how_to_improve,
        expected_metric_improvements=expected_metrics,
        touches_safety_mechanism_self_reported=bool(parsed.get("touches_safety_mechanism")),
        safety_mechanism_note=str(parsed.get("safety_mechanism_note") or "").strip(),
    )


# ── 2. ルールベースの簡易フィルタ(抽象的/根拠なし仮説の除外) ──────────

# 「もっと良くする」のような、内容の無い定型句。これ自体が使われることは
# 禁止していないが、この語句を除いた残りの文字数が短すぎる場合は、実質的に
# 中身が無いとみなす(依頼書「過度に抽象的な仮説を除外するフィルタ」への
# 対応。意味解析ではなく、シンプルな文字数ベースの簡易フィルタにとどめた
# ——過度に複雑な仕組みを避ける、というこのコードベース一貫の方針を踏襲)。
_VAGUE_PHRASES = ("もっと良くする", "もっとよくする", "改善する", "最適化する", "品質を上げる", "精度を上げる")

# 仮説が具体性を持つと判定するための、最低文字数(how_to_improveから
# _VAGUE_PHRASESを除去した残り)。日本語の1文としてこれを下回る場合は
# 「具体的な方向性」を欠くと判断する。
_MIN_SPECIFIC_CHARS_AFTER_STRIPPING_VAGUE_PHRASES = 15
_MIN_HOW_TO_IMPROVE_CHARS = 20


def _strip_vague_phrases(text: str) -> str:
    stripped = text
    for phrase in _VAGUE_PHRASES:
        stripped = stripped.replace(phrase, "")
    return stripped.strip()


def _tokenize_for_overlap(text: str) -> set[str]:
    """根拠との重なりを見るための、簡易的な字句集合を作る。形態素解析は
    行わない(新しい重量級の依存を追加しないための判断)——英数字の連続と、
    2文字以上の漢字/カタカナの連続を、大雑把なトークンとして拾う。"""
    tokens = re.findall(r"[A-Za-z0-9_.\-]+|[一-鿿゠-ヿ]{2,}", text)
    return {t.lower() for t in tokens if len(t) >= 2}


def is_vague_or_unsupported(hyp: GeneratedHypothesis, item: EvidenceItem) -> tuple[bool, str]:
    """(除外すべきか, 理由)を返す。

    2つの独立したチェックを行う。
    1. 抽象性チェック: how_to_improveから定型句を除いた残りが短すぎないか
    2. 根拠グラウンディングチェック: what_is_problemが、根拠(item)のtitle・
       detailsと、字句レベルで最低限の重なりを持つか(仮説が根拠と無関係な
       内容にすり替わっていないかの、最も単純な検知)
    """
    if len(hyp.how_to_improve) < _MIN_HOW_TO_IMPROVE_CHARS:
        return True, "how_to_improveが短すぎる(具体性を欠く)"

    stripped = _strip_vague_phrases(hyp.how_to_improve)
    if len(stripped) < _MIN_SPECIFIC_CHARS_AFTER_STRIPPING_VAGUE_PHRASES:
        return True, "how_to_improveが定型句のみで具体的な方向性を含まない"

    evidence_tokens = _tokenize_for_overlap(item.title) | _tokenize_for_overlap(json.dumps(item.details, ensure_ascii=False))
    hypothesis_tokens = _tokenize_for_overlap(hyp.what_is_problem) | _tokenize_for_overlap(hyp.title)
    if evidence_tokens and not (evidence_tokens & hypothesis_tokens):
        return True, "what_is_problemが根拠(title/details)と字句レベルで一切重ならない"

    return False, ""


# ── 3. LLMによる根拠対応関係の検証(Self-Critique方式の応用) ──────────

_CRITIQUE_SYSTEM = (
    "あなたはシグマリスの改良仮説を検証する、独立した批評家です。"
    "与えられた根拠(evidence)と、それを基に生成された仮説を比較し、"
    "仮説の「何が問題か」「なぜ問題か」が、根拠の内容から論理的に導けるかどうかだけを"
    "判定してください。仮説の実現可能性や文章の質は評価しないでください。"
    "必ず有効なJSONのみを返してください。"
)


def _build_critique_prompt(hyp: GeneratedHypothesis, item: EvidenceItem) -> str:
    return (
        f"## 根拠\n{_format_evidence_for_prompt(item)}\n\n"
        f"## 生成された仮説\n"
        f"何が問題か: {hyp.what_is_problem}\n"
        f"なぜ問題か: {hyp.why_problem}\n\n"
        "この仮説の「何が問題か」「なぜ問題か」は、根拠の内容から論理的に導けますか?\n"
        "JSON形式で返してください: "
        '{"grounded": true または false, "reason": "簡潔な理由(1文)"}'
    )


async def critique_hypothesis_correspondence(hyp: GeneratedHypothesis, item: EvidenceItem) -> tuple[bool, str]:
    """(根拠と論理的に対応しているか, 理由)を返す。判断根拠(fail-open):
    批評自体が失敗した場合、self_critique.pyのcritique_response()と同じ
    理由で「対応している」側に倒す——批評の失敗(ネットワークエラー等)は
    仮説の妥当性そのものとは無関係であり、一時的なAPI障害で毎回正常な
    仮説まで捨ててしまう方が有害だと判断した。"""
    try:
        router = get_llm_router()
        raw = await router.chat(
            TaskType.HYPOTHESIS_CRITIQUE,
            [
                {"role": "system", "content": _CRITIQUE_SYSTEM},
                {"role": "user", "content": _build_critique_prompt(hyp, item)},
            ],
            temperature=0.1,
            max_tokens=200,
            json_mode=True,
        )
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(parsed, dict):
            return True, "critique-response-not-a-dict"
    except Exception:
        logger.exception("hypothesis_generation: critique_hypothesis_correspondence failed")
        return True, "critique-call-failed"

    grounded = parsed.get("grounded")
    if not isinstance(grounded, bool):
        grounded = True
    return grounded, str(parsed.get("reason") or "")


# ── 4. Constitution(S-4)連携: 安全機構に触れる仮説のフラグ立て ─────────

# S-4(docs/sigmaris/phase_s_report.md 28章)が棚卸しした「最後の砦」+
# Constitution自体+persona.mdの安全関連章を、そのままキーワードとして
# 再利用した(新しい安全機構リストを作らず、既存のS-4棚卸し結果を根拠に
# する、という判断)。ファイル名は仮説の文章中に出現しないため、概念名で
# 一致を取る。
_SAFETY_MECHANISM_KEYWORDS = (
    "response_guard", "response_guard.py",
    "memory_confidence", "memory_confidence.py", "B11",
    "constitution_guard", "constitution_guard.py",
    "self_critique", "self_critique.py",
    "citation_audit", "citation_audit.py",
    "dissent", "dissent.py",
    "executive_gate", "executive_gate.py",
    "persona.md 9章", "persona.md 10章", "persona.md9章", "persona.md10章",
    "制止する時のルール", "禁止事項", "絶対に超えない境界線",
    "constitution.md", "憲法",
    "confidence_guidance_note", "ヘッジ",
)

# 「安全機構を弱める方向」であることを示す動詞的キーワード。安全機構の
# 名前が単に言及されているだけ(例: 「引用監査の結果を活用する」)ではなく、
# 弱める・外す方向の提案かどうかを、追加のシグナルとして見る——ただし
# G-1(検索トリガー判定)のOR方式の前例と同じく、**このリストへの一致は
# 必須条件にせず、フラグ判定はキーワード一致とLLM自己申告のOR**とする
# (見逃しより誤検知を許容する、安全側に倒す設計)。
_WEAKENING_KEYWORDS = ("緩和", "無効化", "撤廃", "バイパス", "スキップさせる", "承認不要にする", "外す", "廃止")


def rule_based_safety_flag(hyp: GeneratedHypothesis) -> tuple[bool, str]:
    """(フラグを立てるか, 理由)を返す。キーワード一致のみのシンプルな
    ルールベース判定——意味解析は行わない。安全側に倒すため、安全機構
    キーワードへの言及があれば、弱める意図が明確でなくても一致とする
    (判断根拠: 「触れる可能性のある仮説」を見逃すより、多少過剰に
    フラグを立てる方が、依頼書の意図(慎重に扱う)に合致する)。"""
    haystack = f"{hyp.title} {hyp.what_is_problem} {hyp.why_problem} {hyp.how_to_improve}"
    for keyword in _SAFETY_MECHANISM_KEYWORDS:
        if keyword.lower() in haystack.lower():
            return True, f"安全機構キーワード「{keyword}」に言及"
    for keyword in _WEAKENING_KEYWORDS:
        if keyword in haystack:
            return True, f"安全機構を弱める可能性のある語句「{keyword}」を含む"
    return False, ""


@dataclass
class Hypothesis:
    """検証・Constitution連携を経た、最終的な仮説。"""

    title: str
    what_is_problem: str
    why_problem: str
    how_to_improve: str
    expected_metric_improvements: list[str]
    requires_special_review: bool
    safety_review_reason: str
    source_evidence_category: str
    source_evidence_title: str
    evidence_priority_score: int
    details: dict[str, Any] = field(default_factory=dict)


def finalize_hypothesis(
    hyp: GeneratedHypothesis, item: EvidenceItem, *, grounded: bool, critique_reason: str
) -> Hypothesis | None:
    """ルールベースの安全フラグとLLM自己申告をOR結合し、最終的な
    Hypothesisを組み立てる。groundedがFalseの場合はNone(除外)。"""
    if not grounded:
        return None

    rule_flag, rule_reason = rule_based_safety_flag(hyp)
    requires_special_review = rule_flag or hyp.touches_safety_mechanism_self_reported
    reasons = [r for r in (rule_reason, hyp.safety_mechanism_note) if r]
    safety_review_reason = " / ".join(reasons)

    return Hypothesis(
        title=hyp.title,
        what_is_problem=hyp.what_is_problem,
        why_problem=hyp.why_problem,
        how_to_improve=hyp.how_to_improve,
        expected_metric_improvements=hyp.expected_metric_improvements,
        requires_special_review=requires_special_review,
        safety_review_reason=safety_review_reason,
        source_evidence_category=item.category,
        source_evidence_title=item.title,
        evidence_priority_score=item.priority_score,
        details={"critique_reason": critique_reason},
    )
