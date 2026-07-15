# 役割: Phase S-3「異論表明の仕組み」— B14(sigmaris_user_preference_
# patterns)の判断傾向データを、初めて「反論の材料」として使う。
#
# 【最重要】新しい判断傾向の抽出ロジック・新しいデータ収集テーブルは
# 一切追加していない(依頼書の制約)。
#   - 判断傾向の材料はB14(decision_log.get_active_preference_patterns())
#     をそのまま読み取るのみ——新しい抽出は行わない。
#   - 異論への反応の観測・蓄積は、B15(abstention_feedback.py)の「保留
#     マーカー→次の返答を分類→bounded offsetへ集約」という**既存の
#     仕組みを転用**する。反応の記録先も、新しいテーブルではなく
#     **B15の既存テーブル(sigmaris_abstention_feedback)をそのまま使う**
#     ——`reaction`列に'dissent_accepted'/'dissent_pushed_back'という
#     新しい値を追加しただけで、テーブル自体・書き込み関数
#     (abstention_feedback.record_reaction())は完全に共有している
#     (202607220049_dissent_feedback.sqlのCHECK制約拡張、判断根拠は
#     そのマイグレーションのコメント参照)。
#
# 頻度制御(依頼書3章)は、異論を伝える強さの調整(本ファイルの
# get_dissent_boldness_adjustment())とは意図的に別の仕組みとして分離
# した: 同じpattern_keyについての異論は_DISSENT_COOLDOWN_SECONDS
# (7日間)は再度候補にしない、というB3(active_inquiry._asked_cache)
# と同じ形のプロセス内クールダウンで担う。「頻度」と「踏み込み方」は
# 独立した2つの調整軸であり、依頼書がテスト・報告の両方でこの2つを
# 別項目として要求していることとも整合する。

from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.config import settings
from app.services.abstention_feedback import record_reaction
from app.services.local_llm import TaskType, get_llm_router
from app.services.supabase_rest import _get_client, _require_supabase_config

logger = logging.getLogger(__name__)

_TABLE = "sigmaris_abstention_feedback"  # B15と共有(モジュール冒頭コメント参照)

# 判断傾向を異論の根拠として使ってよい最低証拠件数。orchestrator/
# service.pyの_PREFERENCE_PATTERN_HYPOTHESIS_MAX_EVIDENCE(=3、傾向層/
# 仮説層の境界)と意図的に同じ値を使う——傾向層(evidence_count > 3)に
# 達していない仮説層の判断傾向を根拠に異論を唱えるのは、依頼書の
# 「複数の証拠に基づいて形成されたものであることを踏まえ、その証拠件数
# が十分な場合にのみ」という要件に反する。circular importを避けるため
# ここで独立した定数として複製している(値の同期はコメントで明示する
# 以外に機械的な保証がないことに留意——Phase R-2の_CONSOLIDATION_WEEKDAY
# 等と同じ、この既知のトレードオフを踏襲する)。
_MIN_EVIDENCE_FOR_DISSENT = 3

# 同じ判断傾向についての異論を再度候補にするまでの間隔。B16の14日間
# (目標整合性フラグ)ほど長くはしないが、B3の48時間(単純な再確認質問)
# より意図的に長くした——「異論」はB3の確認質問より心理的な重みが大きい
# と判断したため。未検証の暫定値であることを明記する(このコードベース
# の他の多くのチューニング定数と同じ性質)。
_DISSENT_COOLDOWN_SECONDS = 7 * 24 * 60 * 60

# B15の_MIN_EVIDENCE_FOR_ADJUSTMENT(=5)と同じ値・同じ判断根拠(単一
# ユーザー運用の現実的な発生量の範囲内で、かつ「疎な証拠から結論しない」
# という原則)。
_MIN_EVIDENCE_FOR_ADJUSTMENT = 5

# get_dissent_boldness_adjustment()がこの値を下回った(=pushbackが優勢)
# 場合にのみ、_build_dissent_context()(orchestrator/service.py)は
# パターン自身の階層(傾向層)を無視して、より慎重な仮説層寄りの言い回し
# を強制する。正方向にはキャップを設けていない——persona.md 5章の階層
# 自体が既に踏み込みの上限を規定しているため、「押し返されていない」
# ことは「もっと踏み込んでよい」の根拠にはしない(判断根拠、レポート
# 参照: 異論の踏み込み方向は常に「より慎重な方向にのみ調整可能」という
# 非対称設計)。
_BOLDNESS_PUSHBACK_THRESHOLD = -0.3

_pending_dissents: dict[str, dict[str, Any]] = {}
_dissent_cooldown_cache: dict[str, float] = {}

_CLASSIFY_SYSTEM = (
    "あなたはシグマリスの応答傾向学習システムです。シグマリスが海星さんの発言に対し、"
    "過去の判断傾向との食い違いについて控えめに異論を示した直後の、海星さんの返答を"
    "分類します。必ず有効なJSONのみを返してください。"
)

_CLASSIFY_PROMPT = """シグマリスは直前の応答で、海星さんの発言が過去の判断傾向と食い違っている
可能性について、控えめに異論を示しました。

シグマリスが触れた判断傾向:
{pattern_statement}

海星さんの直後の返答:
{user_reply}

---
この返答を、以下のいずれかに分類してください:

- "dissent_accepted": 異論を受け止めている、指摘を認めている、考えを改めている
  (例:「そうだね、確かに」「言われてみればそうかも」「今回は違う理由があって」)
- "dissent_pushed_back": 異論に反発している、以前の傾向とは違うことを明確に主張している
  (例:「いや、今回はこれでいい」「その傾向はもう古い」「違う、そうじゃない」)
- "unclear": どちらとも判断できない、または話題が変わった

以下のJSON形式で返してください:
{{"reaction": "dissent_accepted" または "dissent_pushed_back" または "unclear"}}"""


def _svc_headers() -> dict[str, str]:
    _require_supabase_config()
    key = settings.supabase_service_role_key
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY is not configured.")
    return {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _relevance_score(pattern: dict[str, Any], conversation_text: str) -> int:
    """LLMを使わない重なりスコア。active_inquiry._rank_by_relevance()と同じ
    「キーワード重なりだけで十分、新しい類似度アルゴリズムは導入しない」
    という方針を踏襲するが、同じ実装(空白区切り)はそのまま使えない——
    _rank_by_relevance()が分割するkey/labelは元々英数字snake_caseや空白
    区切りの短いラベルだが、pattern_statementは分かち書きされていない
    日本語の文であり、`.split()`は文全体を1語として返してしまい実質的に
    機能しない。そのため文字2-gram(バイグラム)の重なりを数える、分かち
    書き不要の同種に軽量な代替を用いた——形態素解析ライブラリ等の新規
    依存は追加していない。"""
    statement = str(pattern.get("pattern_statement") or "")
    if not statement or not conversation_text:
        return 0
    bigrams = {statement[i:i + 2] for i in range(len(statement) - 1)}
    return sum(1 for bg in bigrams if bg.strip() and len(bg) == 2 and bg in conversation_text)


def _is_on_cooldown(pattern_key: str) -> bool:
    last = _dissent_cooldown_cache.get(pattern_key)
    return last is not None and (time.time() - last) < _DISSENT_COOLDOWN_SECONDS


def select_dissent_candidate(
    patterns: list[dict[str, Any]] | None, latest_user_text: str
) -> dict[str, Any] | None:
    """B14の判断傾向一覧と、直近のユーザー発言を照らし合わせ、異論の根拠に
    してよい候補を最大1件選ぶ。純粋関数に近いが、選ばれた候補は
    _dissent_cooldown_cacheに即座に記録する(B3のget_inquiry_question()が
    「選んだ時点でクールダウンに登録し、LLM呼び出しの成否に関わらず再選出
    されないようにする」のと同じ設計——本関数にLLM呼び出しは無いが、
    「選んだのに後続処理で使われなかった」場合の扱いは同じ判断とした)。

    要件1「明確な矛盾がある場合のみ」「過剰検出を避ける」への対応:
    キーワード重なりが1件も無い候補は除外する(=最低限の話題的関連性を
    要求する)。「本当に矛盾しているか」というより深い意味判定は、
    ここでは行わない——_build_dissent_context()がこの候補を会話コンテキ
    ストへ注入し、実際に矛盾しているかどうか・どう言葉にするかの最終判断
    は、BA4の統合生成LLM呼び出し自身に委ねる(判断根拠、レポート参照:
    新しい検出専用LLM呼び出しを応答経路に追加しないための設計)。
    """
    if not patterns or not latest_user_text:
        return None

    conversation_text = latest_user_text.lower()
    eligible = [
        p for p in patterns
        if isinstance(p.get("pattern_key"), str)
        and int(p.get("evidence_count") or 0) > _MIN_EVIDENCE_FOR_DISSENT
        and not _is_on_cooldown(p["pattern_key"])
    ]
    if not eligible:
        return None

    scored = [(p, _relevance_score(p, conversation_text)) for p in eligible]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    best, best_score = scored[0]
    if best_score <= 0:
        return None

    _dissent_cooldown_cache[best["pattern_key"]] = time.time()
    return best


def record_pending_dissent(thread_id: str | None, *, pattern_key: str, pattern_statement: str) -> None:
    """B15のrecord_pending_hedge()と同じ形——このスレッドが今まさに異論を
    受け取ったことを記録し、次のfire-and-forget認知レイヤーが海星さんの
    返答を分類できるようにする。"""
    if thread_id:
        _pending_dissents[thread_id] = {"pattern_key": pattern_key, "pattern_statement": pattern_statement}


def _latest_user_text(messages: list[dict[str, str]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content") or "").strip()
    return ""


async def reflect_dissent_reaction(
    *, thread_id: str | None, turn_messages: list[dict[str, str]], invocation_id: str | None = None
) -> None:
    """Fire-and-forget: abstention_feedback.reflect_abstention_reaction()と
    同じ構造。このスレッドが直前に異論を受け取っていた場合のみ、海星さん
    の返答を分類してsigmaris_abstention_feedback(B15と共有)へ記録する。
    保留が無い場合(大半のターン)はLLM呼び出し自体を行わない。"""
    if not thread_id or thread_id not in _pending_dissents:
        return
    pending = _pending_dissents.pop(thread_id)  # one-shot(B15/B3と同じ)

    user_reply = _latest_user_text(turn_messages)
    if not user_reply:
        return

    try:
        router = get_llm_router()
        raw = await router.chat(
            # B15と同じTaskTypeを再利用する判断根拠: 分類対象の形(短い
            # ユーザー返答 -> 小さな列挙値)が完全に同一であり、依頼書が
            # 「新しい仕組みを増やさない」ことを優先しているため、
            # local_llm.pyへの変更(新TaskType追加)も行わなかった
            # (EPISODE_DETECTIONがDECISION_DETECTIONから分離された際の
            # 「可観測性を分けたい」という判断根拠は、今回は要件の優先度
            # 上、あえて採用しなかった——判断根拠、レポート参照)。
            TaskType.ABSTENTION_REACTION_DETECTION,
            [
                {"role": "system", "content": _CLASSIFY_SYSTEM},
                {"role": "user", "content": _CLASSIFY_PROMPT.format(
                    pattern_statement=pending["pattern_statement"],
                    user_reply=user_reply[:500],
                )},
            ],
            temperature=0.1,
            max_tokens=100,
            json_mode=True,
        )
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(parsed, dict):
            return

        reaction = parsed.get("reaction")
        if reaction not in ("dissent_accepted", "dissent_pushed_back"):
            # "unclear"は証拠として扱わない(B15と同じ方針)。
            return

        await record_reaction(reaction, thread_id=thread_id, invocation_id=invocation_id)
    except Exception:
        logger.exception("dissent: failed to reflect_dissent_reaction thread_id=%s", thread_id)


async def get_dissent_boldness_adjustment() -> float:
    """sigmaris_abstention_feedbackのdissent_accepted/dissent_pushed_back
    行を集計し、[-1.0, 1.0]の比率を返す(正=受容優勢、負=反発優勢)。
    _MIN_EVIDENCE_FOR_ADJUSTMENT未満なら0.0(未学習、B15と同じ方針)。

    B15のget_threshold_adjustment()とはあえて別関数にした判断根拠:
    対象とする列値・返り値の意味(踏み込みの強さの比率であり、B15の
    ような確信度しきい値への直接加算オフセットではない)が異なるため、
    同じ関数に条件分岐を持ち込むより、それぞれが単独で読める形にする
    方が明快と判断した。ただしテーブル・接続設定はB15と完全に共有する
    (新しい接続経路は作っていない)。
    """
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        r = await client.get(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            params={"select": "reaction"},
        )
        r.raise_for_status()
        rows = r.json()
        if not isinstance(rows, list):
            return 0.0

        accepted = sum(1 for row in rows if row.get("reaction") == "dissent_accepted")
        pushed_back = sum(1 for row in rows if row.get("reaction") == "dissent_pushed_back")
        total = accepted + pushed_back
        if total < _MIN_EVIDENCE_FOR_ADJUSTMENT:
            return 0.0

        return (accepted - pushed_back) / total
    except Exception:
        logger.exception("dissent: failed to get_dissent_boldness_adjustment")
        return 0.0
