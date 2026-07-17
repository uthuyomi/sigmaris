# 役割: Phase E-2「別ポートでの動的検証」の純粋寄りのロジック
# (環境変数の組み立て・結果のデータ構造)。実際のsubprocess起動・停止・
# ポーリングは、I/Oを持つsandbox_verification_runner.py側の責務。
#
# 【最重要・繰り返し明記】本タスクは、E-1で判断できなかった仮説の
# 「内容」を一切読み取らず、その仮説をコードへ適用する処理も一切行わ
# ない(ユーザーとの合意事項、docs/sigmaris/phase_e_report.md E-2節
# 参照)。ここで検証するのは、「現在の(変更していない)Sigmarisの
# コードが、本番から隔離された環境で、安全に起動・停止でき、既存の
# 軽量なヘルスチェックが致命的なエラーを起こさないか」という、
# サンドボックス基盤そのものの健全性である——将来E-3以降で、実際に
# コード変更を伴う検証を行う際の土台として、この基盤が安全に機能する
# ことを、ここで先に確認する。

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

# 本番が実際に使っているポート(docs/infrastructure.mdに明記)。この値と
# 同じポートでサンドボックスを起動することを、コードレベルで拒否する
# 「絶対に超えない一線」——依頼書「本番のポートとは、完全に別のポートを
# 使うこと」を、設定ミスでも破れないハードガードにした。
FORBIDDEN_PRODUCTION_PORT = 8000

# サンドボックスは127.0.0.1(ループバックアドレス)にのみbindする——
# 依頼書は「別ポート」としか求めていないが、0.0.0.0でbindすると
# LAN/Tailscale経由で外部から到達可能になってしまう。ポート番号の分離に
# 加えて、そもそもこのマシンの外からは一切到達できない、という、より
# 強い分離を追加の安全策として採用した(判断根拠、レポート参照)。
SANDBOX_BIND_HOST = "127.0.0.1"

# サンドボックスのsubprocessへ渡す環境変数のうち、外部への副作用を持つ
# 機能を強制的に無効化するもの。実際の.envの値(有効になっているか
# どうか)に関わらず、常にこれらの値で上書きする——「オペレーターの
# .env設定に依存しない」という多層防御(判断根拠、レポート参照)。
_FORCED_DISABLED_FLAGS: dict[str, str] = {
    "PROACTIVE_ENABLED": "false",  # startup_scheduler()自体がこのフラグでガードしており、
                                     # falseならジョブは一切登録されない(scheduler.py 268行目で確認済み)
    "X_ENABLED": "false",
    "HEALTH_SYNC_ENABLED": "false",
    "RESEARCH_ENABLED": "false",
}

# 実際の認証情報・トークン類も、フラグの上書きだけに頼らず併せて空文字に
# する(多層防御——フラグのチェックが将来どこかで漏れても、トークン自体が
# 無ければ外部呼び出しは失敗するだけで実害が出ない、という設計)。
_BLANKED_CREDENTIAL_KEYS: tuple[str, ...] = (
    "X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET",
    "PUSHOVER_APP_TOKEN", "PUSHOVER_USER_KEY",
    "NEWS_API_KEY",
    # SIGMARIS_USER_JWT/SIGMARIS_REFRESH_TOKENは、海星さん本人の本番
    # 認証情報そのもの。このsandboxはbenchアカウント(get_eval_bench_jwt()
    # 経由)しか使わない設計のため、本番JWTがsubprocess内で誤って使われる
    # 余地自体を無くす。
    "SIGMARIS_USER_JWT", "SIGMARIS_REFRESH_TOKEN", "SIGMARIS_GOOGLE_ACCESS_TOKEN",
    # エージェント間インターフェース(/api/agent/*)の認証情報。この
    # sandboxへは一切agentリクエストを送らない設計のため、万一何かの
    # 経路で叩かれても、AGENT_SECRETS未設定として503で弾かれるようにする。
    "AGENT_SECRETS",
    # schedule_agent_client.pyのデフォルト値(http://127.0.0.1:8000)が
    # 本番ポートと衝突するため、明示的に空にしておく——空の場合の挙動は
    # schedule_agent_client.py側の既存のエラーハンドリングに委ねる
    # (新しい分岐は追加しない)。
    "SCHEDULE_AGENT_BASE_URL",
)


def build_sandbox_env(*, port: int, base_env: dict[str, str] | None = None) -> dict[str, str]:
    """サンドボックスsubprocess向けの環境変数を組み立てる。base_envは
    現在のプロセスの環境(通常os.environ)のコピーを渡す想定——テストでは
    任意の辞書を渡せる。

    判断根拠(既存の.envをベースにコピーしてから上書きする設計):
    SUPABASE_SERVICE_ROLE_KEY・OPENAI_API_KEY等、サンドボックスでも
    正当に必要な設定(RC/Grounding指標の計算にはSupabase接続が必須)は
    そのまま引き継ぐ必要がある。「全て空から組み立てる」のではなく、
    「既存の環境をコピーし、外部副作用に関わる項目だけを上書きする」
    方式にすることで、将来Phase Eが必要とする新しい環境変数が増えても、
    このリストに追加し忘れない限り安全側に倒れる(copy-then-override、
    許可リスト方式ではなく拒否リスト方式を選んだ判断根拠)。
    """
    if port == FORBIDDEN_PRODUCTION_PORT:
        raise ValueError(
            f"サンドボックスを本番ポート({FORBIDDEN_PRODUCTION_PORT})で起動することは禁止されています。"
        )

    env = dict(base_env if base_env is not None else os.environ)
    env["PORT"] = str(port)
    env.update(_FORCED_DISABLED_FLAGS)
    for key in _BLANKED_CREDENTIAL_KEYS:
        env[key] = ""
    return env


@dataclass
class HealthCheckOutcome:
    name: str
    status: str  # "ok" | "error" | "skipped"
    detail: str = ""


@dataclass
class SandboxVerificationResult:
    port: int
    started: bool
    startup_detail: str
    health_checks: list[HealthCheckOutcome] = field(default_factory=list)
    candidate_hypothesis_ids: list[str] = field(default_factory=list)
    terminated_cleanly: bool = False

    @property
    def verdict(self) -> str:
        """依頼書「合格/不合格ではなく、正確な区分」への対応(E-1の
        3値+除外という設計をそのまま踏襲)。サンドボックス自体が実際の
        コードを一切変更していない以上、ここでも「合格=この仮説群は
        正しい」という意味にはならない——あくまで「サンドボックス基盤
        自体が、今回は問題なく起動・停止し、軽量チェックがエラーを
        出さなかった」という、基盤の健全性の確認にとどまる。
        """
        if not self.started:
            return "failed_to_start"
        if any(c.status == "error" for c in self.health_checks):
            return "started_with_errors"
        if all(c.status == "skipped" for c in self.health_checks) and self.health_checks:
            return "started_but_checks_skipped"
        return "started_and_healthy"
