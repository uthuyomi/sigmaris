from __future__ import annotations

# 役割: Sigmaris Live「詳細表示、+機密情報のマスキング」タスク。
# 記憶検索・ツール呼び出しの「詳細」情報(要約より踏み込んだ、部分的な
# 生データ)を表示する前に、個人を特定できる具体的な情報を検出し、
# マスキングする。
#
# 【設計判断1: x_privacy_filter.pyを流用せず、独自の(より厳しい)判定にした】
# x_privacy_filter.py::filter_private_info()は、X投稿という公開の場での
# チェックであり、都道府県・市区町村レベルの地名や、ありふれた個人名は
# 意図的に許容している(同モジュールのdocstring参照)。Sigmaris Liveの
# 詳細表示は、記憶検索・ツール呼び出しという、より個人的な内容(家庭の
# 出来事・予定等)を扱うため、同じ判定基準を流用せず、地名・氏名・日付も
# マスク対象に含む、独自の、より安全側に倒した判定にした。
#
# 【設計判断2: regex-onlyとし、LLM呼び出しは行わない】
# x_privacy_filter.py::filter_private_info()と同じ理由——マスキング対象の
# 判定のためだけに、ユーザーの記憶内容を外部LLM APIへ送信することは、この
# 機能が守ろうとしているプライバシー方針そのものに反する。また、Live-4が
# 確立した「イベント発行が応答速度に影響しないこと」という制約とも整合的
# ではない(LLM呼び出しは数百ミリ秒〜数秒かかりうる)。
#
# 【設計判断3: 完璧な検出を目指さない】
# G-1(search_trigger.py)・H-2(x_reply_filter.py)と同じ「安全側に倒す」
# 方針を踏襲する。誤検出(過剰マスキング)は許容し、見逃し(マスキング漏れ)
# を減らす方向を優先する——依頼書「明らかに機密性が高い可能性のある情報は
# 安全側に倒して隠す」という方針そのものである。

import re

MASK_TOKEN = "[マスク済み]"

# 日付(具体的な、個別の出来事に紐づきうる)。
_DATE_RE = re.compile(
    r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?"
    r"|\d{1,2}月\d{1,2}日"
    r"|\d{1,2}/\d{1,2}(?:/\d{2,4})?"
)

# 地名(都道府県・市区町村・番地・駅名等)。x_privacy_filter.pyの
# _ADDRESS_DETAIL_RE(丁目+番+号等の街区レベル)より広く、市区町村・駅名の
# 単位も対象にする——都道府県・市区町村レベルの地名を許容するX投稿向けの
# 判定基準とは、意図的に異なる基準にしている(設計判断1)。
_PLACE_RE = re.compile(
    r"[一-龥ぁ-んァ-ヶー]{1,10}(?:都|道府県|県|市|区|町|村|丁目|番地|号室|駅)"
)

# 氏名らしきパターン(敬称付き)。
_NAME_RE = re.compile(
    r"[一-龥ぁ-んァ-ヶーA-Za-z]{1,10}(?:さん|くん|君|ちゃん|様|氏)"
)

# メールアドレス・電話番号・信用情報等、x_privacy_filter.pyと同種の
# パターン(用途が異なるため独立して定義するが、検出内容は同等)。
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
# 末尾は\bではなく(?!\d)にしている——日本語の文章では、電話番号の直後に
# 助詞等の(Unicode上は\wと判定される)文字が空白無しで続くことが多く、
# \bは"数字→日本語文字"の境界を検出できない(どちらも\wなので境界と
# 見なされない)。実際にテストで確認して初めて気づいた挙動のため、
# x_privacy_filter.pyの同名パターン(\b終端)とは、この点で意図的に
# 差異がある。
_PHONE_RE = re.compile(r"(?:\+81|0)\d{1,4}[\-\s]?\d{2,4}[\-\s]?\d{4}(?!\d)")
_ADDRESS_DETAIL_RE = re.compile(r"\d+丁目\d+番(?:\d+号)?|\d+番地\d*号?|\d+号室")
_MONEY_RE = re.compile(
    r"(?<!\d)\d+万円|\d+(?:[,，]\d{3})+円|\d{5,}円|¥\d{4,}(?:[,，]\d{3})*"
)
_CREDENTIAL_RE = re.compile(
    r"(?:password|passwd|token|secret|api[_\-]?key|pwd)[\s=:]+\S{4,}", re.IGNORECASE
)
_IP_RE = re.compile(
    r"(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)(?!\d)"
)

_ALL_PATTERNS: tuple[re.Pattern[str], ...] = (
    _EMAIL_RE,
    _PHONE_RE,
    _ADDRESS_DETAIL_RE,
    _MONEY_RE,
    _CREDENTIAL_RE,
    _IP_RE,
    _DATE_RE,
    _PLACE_RE,
    _NAME_RE,
)

_MAX_PREVIEW_LENGTH = 160


# ─── マスキングの撤廃(Sigmaris Live Redesign-1) ──────────────────────
# 運用方針: /chat は JWT 認証が必須で、Sigmaris Live の詳細表示も海星さん
# 本人にしか届かない(本人限定)。そのため、詳細表示のマスキングは不要と
# 判断し、以下の3関数は「原文をそのまま返す(any_masked は常に False)」
# パススルーに変更した。上部の正規表現群(_DATE_RE 等)・MASK_TOKEN は、
# 将来マスキングを再度有効化する場合の参照として残置している(現在はどの
# 関数からも使われない)。
#
# 【重要】この変更は Sigmaris Live の詳細表示のみに関わる。X 投稿向けの
# プライバシー保護(x_privacy_filter.py 等)には一切触れていない——別
# モジュール・別用途(公開の場での発信)であり、そちらのマスキング/フィルタは
# そのまま維持される。


def mask_sensitive_text(text: str) -> tuple[str, bool]:
    """マスキング撤廃(上記)。原文をそのまま返す。"""
    return text, False


def build_masked_memory_preview(value: str) -> tuple[str, bool]:
    """記憶(user_fact_itemsのvalue)1件分の、詳細表示用プレビュー文字列。
    マスキングは撤廃(上記)。表示長のための切り詰め(_MAX_PREVIEW_LENGTH)
    のみ維持し、内容自体はそのまま返す。"""
    if len(value) > _MAX_PREVIEW_LENGTH:
        return value[:_MAX_PREVIEW_LENGTH] + "…", False
    return value, False


# ツール呼び出しの引数は、このアプリでは、ほぼ全てがカレンダー・旅行計画等の
# 個人的な予定に関する自由記述(タイトル・場所・メモ等)である。regexによる
# 部分マスキングでは、文の構造や意図がそのまま残ってしまい、見逃しの
# リスクが高いと判断した。そのため、文字列値は【全体を】マスキングし、
# 数値・真偽値・null(構造的な情報であり、内容そのものではない)のみ、
# そのまま表示する、という、より単純で安全側に倒した方針にした(判断根拠、
# 報告書に詳述)。
def mask_tool_arguments(arguments: dict[str, object]) -> tuple[dict[str, object], bool]:
    """ツール呼び出しの引数を、詳細表示用に返す。マスキングは撤廃(上記)の
    ため、実際の引数をそのまま(浅いコピーで)返す。"""
    return dict(arguments), False
