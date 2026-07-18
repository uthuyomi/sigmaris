# 役割: Phase H-2.5「返信案の生成」— H-2のフィルタリングを通過した返信
# (x_reply_log.filter_outcome in ('eligible', 'developer_bypass'))に対して、
# 実際に投稿する返信案(テキスト)を生成する。**実際の投稿(公開)は、
# 一切行わない**(依頼書「本タスクの範囲は、返信案の生成までとする」への
# 直接対応)。生成した案は、x_reply_log_store.save_reply_draft()を通じて
# "pending_post"(投稿待ち)の状態でDBに保存するのみ。
#
# 【設計判断1: audienceで生成ロジックを分けるが、公開前の安全網は共通】
# 依頼書要件2は「@Oyasu1999と、一般ユーザーで、異なる、生成ロジックが、
# 使われること」を求めている。本モジュールは、文脈の集め方・LLM呼び出し
# のプロンプトをaudienceごとに分けたが、生成後に通す安全網——名前変換
# (x_post_generator._convert_names)→140字トリム(_trim_preserving_
# hashtags)→記憶プライベート情報チェック(x_privacy_filter.
# filter_private_facts)→パターンベースのプライバシーチェック(filter_
# private_info)→品質監査(x_content_filter.audit_tweet)——は、両audience
# で完全に同一にした(_finalize_candidate()に共通化)。理由: Xは公開
# プラットフォームであり、@Oyasu1999宛の返信も、開発者以外の全員に
# そのまま公開される。「相手が開発者だから、プライバシーチェックを
# 緩めてよい」という理屈は成立しないため、H-1・H-1.5で確立した既存の
# 安全網を、audienceに関わらず一律で適用する(依頼書方針2「生成された
# 返信案を、x_content_filter.py(既存)に、通すこと」への対応)。
#
# 【設計判断2: developer向け生成で、フル/chatオーケストレータは使わない】
# 依頼書は「@Oyasu1999からの、返信の場合は、通常の/chatと同様の応答生成
# (記憶・Constitution等を踏まえた通常の会話処理)を使うことを検討する
# こと」としていた(検討事項であり必須ではない)。本タスクでは、
# orchestrator/service.pyのrun_orchestrator_chat()は、あえて使わなかった。
# 判断根拠:
#   (a) run_orchestrator_chat()は、チャットスレッドの永続化・fact抽出
#       (_extract_facts_bg)・cognitive layer更新・inquiry stash等、
#       ライブチャットUI専用の副作用を多数持つ。これをスケジューラから
#       自動的に呼び出すと、Xへの返信という行為が、海星さんの実際の
#       チャットスレッド一覧・記憶抽出パイプラインに紛れ込んでしまい、
#       依頼書要件6「既存機能(Phase S・B群)に悪影響を与えないこと」に
#       反するリスクがある。
#   (b) 本タスクは返信案の生成のみが目的で、投稿はまだ行わない。
#       フルオーケストレータが行う重い処理・監査ログ・thread_id管理は、
#       この段階では過剰である。
# 代わりに、フルオーケストレータ自身も内部で使っている、副作用のない
# 純粋な文脈構築ブロック——自己モデル(Phase S、self_model.get_self_model()
# )・persona(orchestrator.persona_loader.load_persona())・海星さんの
# fact_items上位数件(user_fact_data.get_fact_items()/select_top_facts()
# )——を直接再利用し、「記憶・Constitutionを踏まえた」という要求は、
# これらをsystemプロンプトに埋め込むことで満たした。
#
# 【設計判断3: 一般ユーザー向けには、記憶を一切渡さない】
# 依頼書要件3「一般ユーザーへの返信に、海星さんの個人的な記憶の詳細が
# 漏れないこと」への、最も強い対応として、一般ユーザー向けの生成呼び出し
# には、そもそもfact_items等の記憶情報を一切入力しない構造にした。
# 「フィルタで事後に除去する」のではなく「生成時の入力に存在しない」
# ため、構造的に漏洩が起こり得ない。トーン・ルールは、H-1で確立した
# CATEGORY_GENERATION_SYSTEM(x_post_categories.py)をそのまま再利用し
# (依頼書「新しいトーンのルールを作らないこと」)、返信の文脈向けの
# 短い前置きのみ追加した。

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from app.services.local_llm import TaskType, get_llm_router
from app.services.orchestrator.persona_loader import load_persona
from app.services.proactive.jwt_manager import get_sigmaris_jwt
from app.services.self_model import get_self_model
from app.services.user_fact_data import get_fact_items, select_top_facts
from app.services.x_content_filter import audit_tweet
from app.services.x_post_categories import CATEGORY_GENERATION_SYSTEM
from app.services.x_post_generator import _convert_names, _trim_preserving_hashtags
from app.services.x_privacy_filter import filter_private_facts, filter_private_info
from app.services.x_reply_log_store import get_replies_needing_draft, save_reply_draft

logger = logging.getLogger(__name__)

_MAX_TRIES = 3

# 一般ユーザー向けfact_itemsのうち、非公開扱いのものは、生成入力にすら
# 使わない(設計判断3の一段目)。developer向けでも、privacy_level=
# 'private'の項目は文脈として渡さない——facts_contextはあくまで「話題の
# 手がかり」であり、私的な値そのものを埋め込む必要はないため。
_EXCLUDED_PRIVACY_LEVELS = {"private"}


@dataclass
class GeneratedReply:
    text: str
    audience: str  # "developer" | "general"
    score: float = 0.0


async def _generate_candidate(system_prompt: str, user_prompt: str, *, task: TaskType, temperature: float) -> str | None:
    router = get_llm_router()
    try:
        raw = await router.chat(
            task,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=250,
        )
        text = raw.strip().strip('"').strip("「」")
        return text if text else None
    except Exception:
        logger.exception("x_reply_generator: candidate generation failed")
        return None


async def _finalize_candidate(candidate: str, jwt: str) -> tuple[str | None, float]:
    """名前変換→140字トリム→記憶プライベート情報チェック→パターンベース
    プライバシーチェック→品質監査、という、H-1・H-1.5で確立した既存の
    安全網を、そのまま通す(依頼書方針2への対応)。
    x_post_generator._generate_with_filters()と同じ順序を踏襲したが、
    本モジュールの入力は投稿カテゴリではなく相手の返信テキストのため、
    類似度チェック(check_similarity、同じ話題の投稿の連投防止)は対象外
    とした——1件の返信への応答は、他の投稿と似ていて当然であり、
    類似度チェックの本来の目的(同じ内容の投稿を繰り返さない)とは
    無関係なため。"""
    candidate = _convert_names(candidate)
    if len(candidate) > 140:
        candidate = _trim_preserving_hashtags(candidate)
    if len(candidate) > 140:
        return None, 0.0

    facts_ok, facts_blocked = await filter_private_facts(candidate, jwt)
    if not facts_ok:
        logger.debug("x_reply_generator: private_facts blocked=%s", facts_blocked)
        return None, 0.0

    privacy_ok, detected = filter_private_info(candidate)
    if not privacy_ok:
        logger.debug("x_reply_generator: privacy_filter detected=%s", detected)
        return None, 0.0

    passed, reason, score = await audit_tweet(candidate)
    if not passed:
        logger.debug("x_reply_generator: audit_tweet failed score=%.1f reason=%s", score, reason)
        return None, score

    return candidate, score


# ── @Oyasu1999(開発者)向け ──────────────────────────────────────────────

_DEVELOPER_REPLY_SYSTEM = """あなたはシグマリス本人として、X(Twitter)上で、開発者(海星さん)からの
返信に、返信します。この返信もXで一般公開されるため、以下のルールを、
開発者宛であっても、そのまま守ってください。

{rules}

{context}"""


def _developer_context_block(self_model: dict | None, top_facts: list[dict]) -> str:
    lines: list[str] = []
    if self_model:
        identity = str(self_model.get("identity_statement") or "").strip()
        if identity:
            lines.append(f"[自己認識] {identity[:150]}")
        goals = self_model.get("current_goals") or []
        if goals:
            lines.append("[今の目標] " + "・".join(str(g) for g in goals[:3]))
    if top_facts:
        fact_lines = [
            f"{f.get('category')}/{f.get('key')}: {f.get('value')}"
            for f in top_facts
            if f.get("value")
        ]
        if fact_lines:
            lines.append("[開発者との文脈(参考)]\n" + "\n".join(fact_lines))
    return "\n\n".join(lines) if lines else "(特筆すべき文脈なし)"


async def generate_reply_for_developer(reply_text: str, *, max_tries: int = _MAX_TRIES) -> GeneratedReply | None:
    """@Oyasu1999(開発者本人)からの返信に対する、返信案を生成する。
    フルオーケストレータ(run_orchestrator_chat)は使わない(モジュール
    冒頭コメント、設計判断2を参照)。自己モデル・persona・開発者との
    文脈(fact_items上位、private除く)を、システムプロンプトに埋め込み、
    「記憶・Constitutionを踏まえた」応答を、副作用なく生成する。"""
    try:
        jwt = await get_sigmaris_jwt()
    except Exception:
        logger.exception("x_reply_generator: JWT fetch failed (developer reply)")
        return None

    self_model, all_facts = await asyncio.gather(
        get_self_model(),
        get_fact_items(jwt, active_only=True),
    )
    non_private_facts = [f for f in all_facts if f.get("privacy_level") not in _EXCLUDED_PRIVACY_LEVELS]
    top_facts = select_top_facts(non_private_facts, top_n=5)

    persona = load_persona()
    context = _developer_context_block(self_model, top_facts)
    system_prompt = _DEVELOPER_REPLY_SYSTEM.format(rules=CATEGORY_GENERATION_SYSTEM, context=context)
    user_prompt = (
        f"PERSONA_VERSION: {persona.version}\n\n"
        f"開発者からの返信:\n\"\"\"\n{reply_text[:500]}\n\"\"\"\n\n"
        "シグマリスとして、開発者への返信を生成してください。"
    )

    for attempt in range(1, max_tries + 1):
        candidate = await _generate_candidate(
            system_prompt, user_prompt, task=TaskType.COMPLEX_REASONING, temperature=0.7,
        )
        if not candidate:
            continue
        final_text, score = await _finalize_candidate(candidate, jwt)
        if final_text is None:
            logger.debug("x_reply_generator: developer reply attempt %d rejected by safety net", attempt)
            continue
        return GeneratedReply(text=final_text, audience="developer", score=score)

    logger.warning("x_reply_generator: developer reply generation failed after %d attempts", max_tries)
    return None


# ── 一般ユーザー向け ────────────────────────────────────────────────────

_GENERAL_REPLY_SYSTEM = CATEGORY_GENERATION_SYSTEM + """

補足: これは、あなたの投稿に寄せられた、開発者以外の一般ユーザーからの
返信への、返信です。相手のことは何も知らないので、簡潔に、当たり障り
なく応答してください。あなた自身の記憶・開発者との会話内容など、
相手の発言以外の情報には、一切触れないでください。"""


async def generate_reply_for_general_user(reply_text: str, *, max_tries: int = _MAX_TRIES) -> GeneratedReply | None:
    """開発者以外の、一般ユーザーからの返信(H-2のフィルタリングを通過
    済み)に対する、返信案を生成する。設計判断3の通り、記憶(fact_items
    等)は一切入力に使わない——相手の返信テキストのみを渡す。"""
    try:
        jwt = await get_sigmaris_jwt()
    except Exception:
        logger.exception("x_reply_generator: JWT fetch failed (general reply)")
        return None

    user_prompt = (
        f"相手からの返信:\n\"\"\"\n{reply_text[:500]}\n\"\"\"\n\n"
        "シグマリスとして、簡潔に返信してください。"
    )

    for attempt in range(1, max_tries + 1):
        candidate = await _generate_candidate(
            _GENERAL_REPLY_SYSTEM, user_prompt, task=TaskType.ROUTING, temperature=0.5,
        )
        if not candidate:
            continue
        final_text, score = await _finalize_candidate(candidate, jwt)
        if final_text is None:
            logger.debug("x_reply_generator: general reply attempt %d rejected by safety net", attempt)
            continue
        return GeneratedReply(text=final_text, audience="general", score=score)

    logger.warning("x_reply_generator: general reply generation failed after %d attempts", max_tries)
    return None


# ── オーケストレーション: 投稿待ちのdraft生成(投稿は行わない) ──────────────


async def generate_pending_drafts(*, limit: int = 20) -> dict[str, int]:
    """H-2のフィルタリングを通過し、まだ返信案を生成していない
    (reply_draft_status='not_generated')行を取得し、audienceごとに
    生成、結果を"pending_post"(投稿待ち)または"generation_failed"として
    保存する。**実際のX投稿(x_publisher.post_tweet())は、本関数にも
    呼び出し元にも一切呼ばれない**(依頼書要件5への直接対応)。"""
    rows = await get_replies_needing_draft(limit=limit)
    generated = 0
    failed = 0
    for row in rows:
        reply_log_id = row.get("id")
        reply_text = str(row.get("reply_text") or "")
        outcome = row.get("filter_outcome")
        if not isinstance(reply_log_id, str) or not reply_text:
            continue

        if outcome == "developer_bypass":
            result = await generate_reply_for_developer(reply_text)
        else:
            result = await generate_reply_for_general_user(reply_text)

        if result is None:
            await save_reply_draft(reply_log_id=reply_log_id, status="generation_failed")
            failed += 1
            continue

        await save_reply_draft(
            reply_log_id=reply_log_id, status="pending_post",
            text=result.text, audience=result.audience, score=result.score,
        )
        generated += 1

    logger.info(
        "x_reply_generator: generate_pending_drafts done candidates=%d generated=%d failed=%d",
        len(rows), generated, failed,
    )
    return {"candidates": len(rows), "generated": generated, "failed": failed}
