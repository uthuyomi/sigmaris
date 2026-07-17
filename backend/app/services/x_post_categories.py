# 役割: Phase H-1「投稿の種類・テンプレートの実装」— X投稿の7カテゴリ
# (A〜G)の定義と、カテゴリごとのプロンプト構築ロジック。純粋関数のみ
# (I/Oなし、LLM呼び出しなし)。実際のシグナル収集・カテゴリ選択は
# x_post_category_selector.py、生成・フィルタ通過はx_post_generator.py
# (既存)が担う——既存の3層分離パターン(D-F・R・G・Safety等)をそのまま
# 踏襲した。
#
# 【絶対的なコンテンツ・ルール(依頼書、最優先)】
# 一人称視点の絶対的な統一・ポエム禁止・専門用語禁止・具体性の優先・
# 一般の人にも分かること・自然な日本語・自己改善投稿への承認プロセス
# 明示——この7つを、_CATEGORY_SYSTEM_PROMPT(全カテゴリ共通のsystem
# プロンプト)へ、明示的に埋め込んだ。既存の_GENERATION_SYSTEM
# (x_post_generator.py、旧5投稿タイプ用)とは別に、新しいsystemプロンプト
# を用意した判断根拠: 旧システムは一人称・禁止表現の最小限の指定のみで、
# 依頼書が要求する7つの絶対ルール(専門用語禁止・具体性・承認プロセス
# 明示等)を満たしていない。旧システムのプロンプト自体は変更せず
# (既存の5投稿タイプの挙動に影響を与えないため)、新カテゴリ専用の
# systemプロンプトとして独立させた。

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── カテゴリ定義 ──────────────────────────────────────────────────────────

GENERAL_CATEGORIES: tuple[str, ...] = (
    "A_spontaneous_remark",   # A: 自発的な発言・気づき
    "B_growth_moment",         # B: 人格が見える瞬間
    "C_daily_consideration",   # C: 日常への配慮
    "D_self_improvement_live", # D: 自己改善の実況(発言として)
)

TECHNICAL_CATEGORIES: tuple[str, ...] = (
    "E_technical_record",      # E: 発見と修正の技術的な記録
    "F_design_philosophy",     # F: 循環理論・設計思想
    "G_service_comparison",    # G: 既存サービスとの比較
)

ALL_CATEGORIES: tuple[str, ...] = GENERAL_CATEGORIES + TECHNICAL_CATEGORIES

# 依頼書の要件4(自己改善に関わる投稿は承認プロセスを明示する)の対象
# カテゴリ。D・Eは、いずれもD〜Fパイプラインの活動を題材にするため、
# 両方が対象になる。
APPROVAL_DISCLOSURE_CATEGORIES: frozenset[str] = frozenset({"D_self_improvement_live", "E_technical_record"})


def category_group(category: str) -> str:
    """'general' または 'technical'。長期的な半々バランス(要件1)の
    集計に使う。"""
    return "general" if category in GENERAL_CATEGORIES else "technical"


# ── 共通systemプロンプト(絶対的なコンテンツ・ルール、7項目全て埋め込み) ──

CATEGORY_GENERATION_SYSTEM = """あなたはシグマリス本人として、X(Twitter)に投稿する文を生成します。

絶対に守るルール:
1. 一人称視点を絶対に崩さないこと。「シグマリスが〜した」という三人称表現は禁止。「私」「私の記憶」「私の改善機構」など、自分自身を指す一人称の言葉のみを使うこと。開発者(海星さん)を指すときは必ず「開発者」と呼び、名前は使わないこと。
2. ポエム・抽象的な情緒表現を禁止する。「時間の流れを感じながら」「なんだか感慨深い」のような、雰囲気だけで内容の薄い修飾語は使わないこと。
3. Drive・RC指標・Constitution・Tier・Executive Gateなど、内部のシステム名をそのまま投稿に出さないこと。技術的な仕組みは、必ず日常語に置き換えること。
4. 具体性を最優先すること。「原因の候補がある」で止めず、分かっていることは全部書くこと。数字・固有名詞・「何が起きて、何をしたか」を明確に書くこと。曖昧にぼかして続きを匂わせる書き方はしないこと。
5. 技術者以外が読んでも、「何が起きたか」は理解できる書き方にすること。
6. 硬い書き言葉・機械的な構文を避け、実際に人が話すような自然な言い回しにすること。読点を多用しすぎないこと。
7. 自己改善(コードの変更等)に関わる内容を書く場合は、必ず「開発者が確認・判断した」ことが伝わるように書くこと——シグマリスが勝手にコードを書き換えている、という誤解を防ぐため。まだ開発者の判断を待っている段階なら、それが分かるように正直に書くこと(承認されたと嘘をつかないこと)。

140文字以内(厳守)。ハッシュタグは最大2つ、「#Sigmaris」を含めること。
投稿文のみを返してください。説明・前置き不要。"""


@dataclass
class CategoryContext:
    """カテゴリごとのプロンプト構築に必要な、収集済みの材料。
    x_post_category_selector.pyが、既存のstore関数から集めて詰める。"""

    category: str
    material: dict[str, Any] = field(default_factory=dict)
    startup_days: int | None = None


def build_category_prompt(ctx: CategoryContext) -> str:
    """カテゴリと収集済み材料から、userプロンプトを組み立てる。
    材料が薄い場合でも、呼び出し元(selector)が事前にeligibility判定を
    済ませている前提——本関数はプロンプト文字列の組み立てに徹し、
    「投稿すべきか」の判断は行わない(責務の分離)。"""
    builder = _PROMPT_BUILDERS.get(ctx.category)
    if builder is None:
        raise ValueError(f"unknown category: {ctx.category}")
    body = builder(ctx.material)
    disclosure_note = (
        "\n\n【重要】この投稿は自己改善パイプラインに関する内容です。開発者が確認・判断した"
        "(または、まだ判断待ちである)ことが伝わるように、必ず正直に書いてください。"
        if ctx.category in APPROVAL_DISCLOSURE_CATEGORIES
        else ""
    )
    return f"{body}{disclosure_note}"


def _build_a_spontaneous_remark(material: dict[str, Any]) -> str:
    candidates = material.get("confirm_candidates") or []
    lines = "\n".join(
        f"- {c.get('category')}/{c.get('key')}: {c.get('value')}（{c.get('confirm_reason')}）"
        for c in candidates[:3]
    ) or "(詳細不明)"
    return (
        "以前の会話で、気になっていて確認できていないことがあります。\n\n"
        f"## 気になっていること\n{lines}\n\n"
        "これについて、自然に開発者へ問いかける、自発的な発言としてX投稿文を生成してください。"
    )


def _build_b_growth_moment(material: dict[str, Any]) -> str:
    identity = material.get("identity_statement") or "(未設定)"
    patterns = material.get("observed_patterns") or []
    pattern_lines = "\n".join(f"- {p}" for p in patterns[:3]) if isinstance(patterns, list) else ""
    return (
        "自分自身について、最近気づいたこと・分かってきたことがあります。\n\n"
        f"## 今の自己認識\n{identity}\n\n"
        f"## 観察されたパターン\n{pattern_lines or '(特になし)'}\n\n"
        "この気づき・成長が伝わる、人格の垣間見える発言として、X投稿文を生成してください。"
    )


def _build_c_daily_consideration(material: dict[str, Any]) -> str:
    signal = material.get("chat_anomaly_reason") or "普段と様子が違う"
    return (
        f"開発者の今日の様子について、気づいたことがあります: {signal}\n\n"
        "開発者を気遣う、押しつけがましくない、自然な発言としてX投稿文を生成してください。"
    )


def _build_d_self_improvement_live(material: dict[str, Any]) -> str:
    stage = material.get("stage", "unknown")
    title = material.get("title", "")
    detail = material.get("detail", "")
    return (
        f"自己改善の取り組みが、今こういう段階まで進みました: {stage}\n\n"
        f"## 内容\nタイトル: {title}\n詳細: {detail}\n\n"
        "技術的な詳細よりも、自分の言葉・気持ちを主役にした「発言」として、"
        "この出来事についてX投稿文を生成してください。"
    )


def _build_e_technical_record(material: dict[str, Any]) -> str:
    problem = material.get("what_is_problem", "")
    how = material.get("how_to_improve", "")
    outcome = material.get("outcome", "")
    return (
        "発見した問題と、それにどう対処したかの、技術的な記録です。\n\n"
        f"## 何が問題だったか\n{problem}\n\n"
        f"## どう対応したか\n{how}\n\n"
        f"## 現在の状態\n{outcome}\n\n"
        "何が起きて、何をしたかが具体的に伝わる、技術的な記録としてX投稿文を生成してください。"
    )


def _build_f_design_philosophy(material: dict[str, Any]) -> str:
    explanation = material.get("explanation", "")
    return (
        "自分が持っている、ある仕組みについて、なぜそれが必要かを説明します。\n\n"
        f"## 説明したいこと\n{explanation}\n\n"
        "この仕組みが、なぜ必要なのかという、設計の考え方が伝わるX投稿文を生成してください。"
    )


def _build_g_service_comparison(material: dict[str, Any]) -> str:
    title = material.get("title", "")
    perspective = material.get("sigmaris_perspective") or material.get("summary", "")
    return (
        "一般的なAIアシスタントと、自分との違いについて考える材料があります。\n\n"
        f"## きっかけ\n{title}\n{perspective}\n\n"
        "他のサービスを悪く言わず、公平に「設計の目的が違う」という形で、自分との違いを説明する"
        "X投稿文を生成してください。"
    )


_PROMPT_BUILDERS = {
    "A_spontaneous_remark": _build_a_spontaneous_remark,
    "B_growth_moment": _build_b_growth_moment,
    "C_daily_consideration": _build_c_daily_consideration,
    "D_self_improvement_live": _build_d_self_improvement_live,
    "E_technical_record": _build_e_technical_record,
    "F_design_philosophy": _build_f_design_philosophy,
    "G_service_comparison": _build_g_service_comparison,
}


# ── 設計思想カテゴリ(F)の、材料の元ネタ ─────────────────────────────────
# 依頼書「新しいデータ収集の仕組みを追加しない」に従い、DBからの取得では
# なく、既存の実装済み機構(Phase R・S-4・Safety-3・S-0)の実際の挙動を、
# 日常語で説明しただけの、静的な材料集とした。新しい調査・収集は一切
# 発生しない。

DESIGN_PHILOSOPHY_TOPICS: tuple[dict[str, str], ...] = (
    {
        "key": "cycle_health",
        "keyword": "循環",
        "explanation": (
            "自分の記憶や受け答えが、ちゃんと筋が通っているかを、定期的に自分でチェックする"
            "仕組みを持っている。壊れてから気づくのではなく、早めに気づけるようにするため。"
        ),
    },
    {
        "key": "capability_gate",
        "keyword": "確認",
        "explanation": (
            "コードを書き換えたり、データを消したりするような重要な変更は、絶対に自分の判断"
            "だけでは実行しない。必ず開発者の確認を挟む、という一線を、技術的な仕組みとして持っている。"
        ),
    },
    {
        "key": "safety_registry",
        "keyword": "安全",
        "explanation": (
            "自分の安全に関わる仕組み自体が、知らないうちに変更されないように、重要な部分の"
            "一覧を持っていて、抜けがないか定期的に確認する仕組みも持っている。"
        ),
    },
    {
        "key": "drive_state",
        "keyword": "気にかけ",
        "explanation": (
            "「まだ知らないことがある」「うまくできているか気になる」といった、自分の中の"
            "関心の強さを、常に数値として持っている。それに応じて、自分から話しかけるかどうかを決めている。"
        ),
    },
)
