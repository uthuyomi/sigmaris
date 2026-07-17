# 役割: Phase G-1(Grounding, docs/sigmaris/phase_g_report.md)— 「この質問
# には検索が必要か」を判定する、軽量な判定ロジック。
#
# 【重要】本タスクは判定ロジックの実装のみを行う。実際のWeb検索実行(G-2
# 以降)には一切繋げない——ここで返す辞書は、後続タスクが参照できる形で
# 「検索が必要か」「どの基準に該当したか」を提供するだけの、独立した関数
# として実装する(依頼書の制約)。
#
# 新しい重量級のLLM呼び出しはここでは一切行わない。ルールベースの判定
# (detect_search_need())はI/O・LLM呼び出しなしの純粋関数であり、
# chat_routing.py::classify_chat_intent()が既に行っているLLM呼び出し
# (nano-tier、TaskType.CHAT_INTENT_CLASSIFICATION)が実際に発生する場合
# にのみ、そのLLMの判定結果を merge_llm_search_judgment() でルールベース
# の結果へ統合する——LLM呼び出し自体はclassify_chat_intent()側が既存の
# 1回のまま増やさない。

from __future__ import annotations

import re
from typing import Any

# 鮮度キーワード: 時間的な鮮度を問う表現。
#
# 判断根拠(「今日」「最近」「いま」「今の」を含めなかった理由): これらは
# 日常会話で極めて頻繁に使われる語("今日は疲れた"、"最近どう？"等)であり、
# 検索の要否とはほぼ無関係に出現する。テスト実装中に実際にこれらが雑談で
# 誤検出を起こすことを確認した(依頼書「過度に複雑な判定ロジックにしない
# こと」の精神に沿い、複雑な文脈判定を追加する代わりに、誤検出率の高い
# キーワード自体をリストから外す方を選んだ)。「最新」「現在」「今年」等、
# より明確に情報の鮮度そのものを問う語に絞った。
_FRESHNESS_KEYWORDS = (
    "最新", "現在", "今年", "現時点", "今どきの",
    "latest", "current", "currently", "up to date", "this year",
)

# 変動しやすい事実キーワード: 価格・スペック・在庫等、頻繁に変わりうる事実。
_VOLATILE_FACT_KEYWORDS = (
    "価格", "値段", "いくら", "円", "ドル", "スペック", "性能", "在庫",
    "発売", "リリース", "バージョン", "最新版", "何位", "ランキング",
    "price", "cost", "spec", "specs", "stock", "release", "version", "ranking",
)

# 固有名詞・型番らしきパターン: 英字+数字の組み合わせ(製品名・型番に
# 多く見られる形、例: "iPhone 15" "RTX4090" "GPT-5")。誤検出・見逃しの
# 両方がありうる、意図的に簡易なパターンであることを明記する
# (依頼書「過度に複雑な判定ロジックにしないこと」への対応)。
#
# 末尾に\bを付けないこと: Pythonのreはデフォルト(Unicodeモード)で日本語の
# 文字も\wとみなすため、"RTX4090の性能"のように直後に日本語が続く場合、
# "0"と"の"の間に単語境界(\b)が成立せずマッチに失敗することをテストで
# 確認した。英数字側の開始点([A-Za-z]{2,})だけで十分に絞り込めるため、
# 末尾の境界チェックは行わない。
_MODEL_NUMBER_PATTERN = re.compile(r"[A-Za-z]{2,}[\-\s]?\d{1,4}[A-Za-z]?")


def detect_search_need(*, latest_text: str) -> dict[str, Any]:
    """ルールベースのみの判定(LLM呼び出しなし)。常にO(1)級の文字列検索
    のみで完結し、classify_chat_intent()がヒューリスティックで即座に
    intentを確定させ、LLMを一切呼ばないターンでも、この判定だけは必ず
    行える(依頼書の判定基準4項目のうち、鮮度キーワード・固有名詞・
    変動しやすい事実の3つをここで扱う)。

    「既存記憶でカバーできるか」(4項目目)は、本関数では明示的な
    メモリ照合を行わない——classify_chat_intent()は現状user_fact_itemsを
    受け取っておらず、それを新たに配線するのはG-1の「判定ロジックのみ」
    という範囲を超えるプラミング変更になる(判断根拠、レポート参照)。
    代わりに、鮮度・固有名詞・変動事実のいずれの信号も無ければ
    needs_search=Falseとする設計自体が、「時間とともに変化する情報で
    なければ、既存の一般知識・記憶で十分」という前提を暗黙的に体現して
    いる。
    """
    reasons: list[str] = []
    lowered = latest_text.lower()

    matched_freshness = next((kw for kw in _FRESHNESS_KEYWORDS if kw.lower() in lowered), None)
    if matched_freshness:
        reasons.append(f"freshness_keyword:{matched_freshness}")

    matched_volatile = next((kw for kw in _VOLATILE_FACT_KEYWORDS if kw.lower() in lowered), None)
    if matched_volatile:
        reasons.append(f"volatile_fact_keyword:{matched_volatile}")

    if _MODEL_NUMBER_PATTERN.search(latest_text):
        reasons.append("proper_noun_or_model_number")

    return {
        "needs_search": bool(reasons),
        "reasons": reasons,
        "source": "rule",
    }


def merge_llm_search_judgment(
    rule_signal: dict[str, Any],
    *,
    llm_needs_search: bool | None,
    llm_search_reason: str | None,
) -> dict[str, Any]:
    """classify_chat_intent()のLLM呼び出しが実際に発生した場合のみ呼ばれる。
    ルールベースの判定に、同じ呼び出しが返したintent分類のJSONに相乗り
    させたneeds_search/search_reasonフィールドを統合する。

    判断根拠(ORで統合する設計): 本タスクの動機は「検索すべき質問を
    見逃して、もっともらしいが未検証の内容を答えてしまう」ことへの
    対応であり、過剰検出(不要な検索が後続タスクで実行される)より
    見逃し(必要な検索がされない)の方が実害が大きいと判断した。その
    ため、ルールベース・LLM判定のいずれかがTrueであれば、最終的に
    needs_search=Trueとする——安全側に倒す設計。
    """
    reasons = list(rule_signal.get("reasons", []))
    needs_search = bool(rule_signal.get("needs_search"))

    if llm_needs_search is True:
        needs_search = True
        reasons.append(f"llm_judgment:{llm_search_reason or 'needs-search'}")
    elif llm_needs_search is False:
        reasons.append(f"llm_judgment:{llm_search_reason or 'no-search-needed'}")

    return {
        "needs_search": needs_search,
        "reasons": reasons,
        "source": "rule+llm",
    }
