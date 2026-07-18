# 役割: Phase S-1「Executive Gate」— Drive System(drive_system.py)の
# 状態を踏まえて、「今、シグマリスが自発的に話しかけてよいタイミングか」
# を判定する、読み取り専用のルールベース判定層。
#
# 設計方針(依頼書の通り):
#   1. まず機械的な絶対制約(深夜早朝・直近の連続話しかけ防止)を確認する。
#      これらをクリアしない限り、Drive Stateを参照するまでもなく却下する
#      (=Drive Stateの取得自体を行わない、無駄なI/Oを避ける設計)。
#   2. 絶対制約をクリアした場合のみ、drive_system.get_current_drive_state()
#      を参照し、いずれかのDriveのlevelが閾値を超えていれば「話しかけて
#      よい」と判定する。
#
# 本モジュールは判定結果を返すのみで、実際に何を話すかの生成(S-2:
# Goal Proposal相当)、Pushover等の通知への統合は行わない
# (docs/sigmaris/phase_s_report.md参照)。

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import settings
from app.services.drive_system import DriveState, get_current_drive_state
from app.services.supabase_rest import rest_select

# 深夜早朝の絶対制約: 依頼書の目安通り23時〜7時(settings.sigmaris_
# timezone基準、他のPhase R/proactive/scheduler.pyのジョブ時刻判定と
# 同じタイムゾーン規約)。既存の朝ブリーフィング(8:00)・夕方チェックイン
# (22:00)の外側と(1時間の余裕を持って)整合しており、既存スケジュールが
# 暗黙に前提としていた「活動時間帯」とも矛盾しない値であることを確認した
# (判断根拠、レポート参照)。
_QUIET_HOURS_START = 23  # この時刻以降は深夜(23:00〜)
_QUIET_HOURS_END = 7  # この時刻より前は早朝(〜07:00)

# 直近の自発的な話しかけからのクールダウン。Temporal Layerのlast_
# mentioned_at(事実単位の既読管理)とは異なり、こちらは「シグマリスが
# 自発的に接触したこと自体」の頻度を抑える、会話全体単位のクールダウン。
# B3の48時間(フィールド単位)・B16の14日間(同一乖離フラグの再提示)の
# 中間的な性格——「連日ではなく、同日内での連投を避ける」ことを主眼に
# 3時間とした。未検証の暫定値であることを明記する(他の多くのB群/Phase S
# 暫定チューニング定数と同じ性質)。
_PROACTIVE_CONTACT_COOLDOWN = timedelta(hours=3)

# Drive Stateのlevelがこの値以上であれば「話しかけてよい」根拠とみなす。
# 0.5(中間点)よりやや高く、MasteryDriveのbreak_detectedフロア(0.7、
# drive_system.py)よりは低い——「明確に高まっている」が「緊急」ではない
# 水準を意図した未検証の暫定値。
_DRIVE_LEVEL_THRESHOLD = 0.6


@dataclass
class ExecutiveGateResult:
    may_speak: bool
    blocked_by: str | None  # "quiet_hours" | "cooldown" | "no_drive_above_threshold" | None(may_speak時)
    reason: str
    checked_at: str
    quiet_hours: bool
    cooldown_active: bool
    last_proactive_contact_at: str | None
    triggering_drives: list[str] = field(default_factory=list)
    drive_state: DriveState | None = None  # 絶対制約で却下された場合はNone(未取得、無駄なI/Oを避けるため)


def _is_quiet_hours(hour: int) -> bool:
    """23時〜翌7時(またぎ)を深夜早朝とみなす。"""
    return hour >= _QUIET_HOURS_START or hour < _QUIET_HOURS_END


async def _get_last_proactive_contact_at(jwt: str) -> datetime | None:
    """直近の自発的な話しかけの時刻を、agent_invocation_audit_logsから
    取得する。「自発的」の判定は、orchestrator/service.py::_is_proactive_
    call()が既に使っている"proactive-scheduler:"プレフィックス
    (旧proactive/actions.py::_run_action()がcaller_agent_idに付与していた、
    Temporal Layer Step2から確立済みの既存シグナル)をそのまま踏襲する
    ——新しい「自発的接触」の記録テーブル・記録経路は一切追加していない。

    【Phase S-6での注記】このプレフィックスを実際にセットしていた唯一の
    書き込み元(旧proactive/actions.py、朝ブリーフィング・夕方チェックイン・
    週次レビュー)は機能自体を完全廃止した。このため本関数は今後、常に
    Noneを返す(=cooldown_active=False)ようになる——X投稿選定
    (x_post_category_selector.py)への影響としては、「直近のブリーフィング
    から3時間以内はX投稿を控える」という制約が事実上消滅したことを意味する
    (詳細な判断根拠、docs/sigmaris/phase_s_report.md Phase S-6参照)。
    quiet_hours制約・Drive閾値判定は無変更のため、X投稿選定ロジック自体が
    壊れることはない。
    """
    try:
        rows = await rest_select(jwt, "agent_invocation_audit_logs", {
            "select": "created_at",
            "caller_agent_id": "like.proactive-scheduler:%",
            "order": "created_at.desc",
            "limit": "1",
        })
    except Exception:
        return None
    if not isinstance(rows, list) or not rows:
        return None
    created_at = rows[0].get("created_at")
    if not isinstance(created_at, str):
        return None
    try:
        return datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return None


async def evaluate_executive_gate(
    jwt: str,
    *,
    is_urgent: bool = False,
    now: datetime | None = None,
) -> ExecutiveGateResult:
    """"今、話しかけてよいか"を判定する。

    is_urgent: 深夜早朝の絶対制約のみをバイパスする(依頼書の「深夜早朝は
    緊急以外の自発的な話しかけを行わない」という文言に対応)。連続話しかけ
    防止のクールダウンは、urgent時でもバイパスしない——「緊急なら深夜でも
    起こしてよい」と「緊急なら何度でも連投してよい」は別の性質の判断であり、
    後者まで本タスクの絶対制約を弱めることは要求されていないため、安全側
    に倒した(判断根拠、レポート参照)。本タスク時点でis_urgent=Trueを渡す
    呼び出し元は存在しない(緊急性の判定自体はS-1のスコープ外)。

    絶対制約(深夜早朝・クールダウン)のいずれかで却下される場合、Drive
    State自体を取得しない(drive_state=None) — 参照するまでもなく結果が
    決まっているため、無駄なI/Oを避ける設計判断。
    """
    now = now or datetime.now(UTC)
    local_now = now.astimezone(ZoneInfo(settings.sigmaris_timezone))
    quiet = _is_quiet_hours(local_now.hour)

    if quiet and not is_urgent:
        return ExecutiveGateResult(
            may_speak=False,
            blocked_by="quiet_hours",
            reason=f"深夜早朝({_QUIET_HOURS_START}時〜{_QUIET_HOURS_END}時)のため、緊急以外の自発的な話しかけを見送る",
            checked_at=now.isoformat(),
            quiet_hours=True,
            cooldown_active=False,
            last_proactive_contact_at=None,
        )

    last_contact_at = await _get_last_proactive_contact_at(jwt)
    cooldown_active = last_contact_at is not None and (now - last_contact_at) < _PROACTIVE_CONTACT_COOLDOWN
    if cooldown_active:
        return ExecutiveGateResult(
            may_speak=False,
            blocked_by="cooldown",
            reason=f"直近の自発的な話しかけから{_PROACTIVE_CONTACT_COOLDOWN}未満のため見送る",
            checked_at=now.isoformat(),
            quiet_hours=quiet,
            cooldown_active=True,
            last_proactive_contact_at=last_contact_at.isoformat() if last_contact_at else None,
        )

    drive_state = await get_current_drive_state(jwt)
    named_drives = (
        ("knowledge_gap", drive_state.knowledge_gap.level),
        ("mastery", drive_state.mastery.level),
        ("coherence", drive_state.coherence.level),
    )
    triggering = [name for name, level in named_drives if level is not None and level >= _DRIVE_LEVEL_THRESHOLD]
    may_speak = bool(triggering)

    return ExecutiveGateResult(
        may_speak=may_speak,
        blocked_by=None if may_speak else "no_drive_above_threshold",
        reason=(
            f"閾値({_DRIVE_LEVEL_THRESHOLD})を超えたDrive: {', '.join(triggering)}"
            if may_speak
            else f"いずれのDriveも閾値({_DRIVE_LEVEL_THRESHOLD})に達していない"
        ),
        checked_at=now.isoformat(),
        quiet_hours=quiet,
        cooldown_active=False,
        last_proactive_contact_at=last_contact_at.isoformat() if last_contact_at else None,
        triggering_drives=triggering,
        drive_state=drive_state,
    )
