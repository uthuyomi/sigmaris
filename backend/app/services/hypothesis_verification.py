# 役割: Phase F-2「E-1・E-2検証環境との統合」の中核ロジック——「ある
# 1つの仮説が、どの程度、検証されていると言えるか」を、E-1(仮説単位の
# 静的検証)とE-2(サンドボックス基盤全体の健全性証明)という、**粒度の
# 異なる2つの検証結果**から、正直に分類する、純粋関数(I/Oなし)。
#
# 【F-1で発見された、矛盾の正確な原因(要件1・2)】
# E-1(static_verification.py)は、**1つの仮説につき1つの判定**を返す
# ——「この仮説が触れると推定される領域に、既存テストがあるか」という、
# 仮説そのものの内容に基づく、仮説単位の検証である。
#
# E-2(sandbox_verification.py)は、**1回の起動セッションにつき1つの
# 判定**を返す——「現在のコード(仮説の内容は一切適用しない)を、隔離
# された環境で起動し、軽量なヘルスチェックが例外を出さなかったか」と
# いう、サンドボックス基盤そのものの健全性の証明であり、**仮説の内容を
# 一切読まない**(sandbox_verification_runner.pyの設計、E-2報告書0章で
# 既に明記済み)。
#
# この2つは、検証の「対象」が全く異なる(E-1=仮説の内容、E-2=環境
# インフラそのもの)。そのため「E-1とE-2、両方を通過した仮説」という
# 集合は、これらを単純にANDで組み合わせても意味を持たない——E-2は
# そもそも「どの仮説を通過させたか」という情報を持たない。
#
# 【本モジュールが行うこと】この2つの、性質の異なる検証結果を、
# 「仮説単位の検証結果」として、以下の3段階に正直に分類する。
#   1. hypothesis_verified_coverage: E-1が、この仮説の対象領域について、
#      既存テストのカバレッジを実際に確認済み(内容に基づく、最も
#      信頼できる検証)
#   2. sandbox_infra_available_unverified_content: この仮説の対象領域に
#      既存テストは無いが(E-1=insufficient_signal)、直近のE-2実行で、
#      サンドボックス基盤自体は健全に起動・停止できることが確認されて
#      いる。**これは、仮説の内容を検証したものでは全く無い**——単に
#      「この仮説を人間が手動で検証したくなった場合に使える環境が、
#      今のところ壊れていない」という、インフラの可用性を意味するに
#      すぎない
#   3. not_eligible: 上記いずれにも該当しない

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class VerificationTier:
    tier: str  # "hypothesis_verified_coverage" | "sandbox_infra_available_unverified_content" | "not_eligible"
    reason: str


def classify_verification_tier(
    static_verification_row: dict[str, Any], *, latest_sandbox_verification: dict[str, Any] | None
) -> VerificationTier:
    """1件のE-1判定(仮説単位)と、直近1回分のE-2判定(セッション単位、
    仮説に依存しない)から、この仮説の検証段階を分類する。

    判断根拠(「直近1回分」のE-2結果を使う理由): E-2は仮説単位の記録を
    持たないため、「この仮説のためのE-2実行」というものは存在しない。
    代わりに、「現時点でサンドボックス基盤が使える状態にあるか」という
    問いに対する、最新の答えを採用する——古すぎるE-2実行結果は、現在の
    基盤の状態を正しく反映していない可能性がある(この限界は、レポートに
    明記する。本モジュールでは、鮮度に基づく足切り(例えば1週間以内等)は
    設けていない——依頼書が要求したのは「直近のE-2実行」の活用であり、
    新しい鮮度判定ロジックを追加することは、過度な複雑化を避ける、という
    このコードベース一貫の方針に反すると判断した)。
    """
    verdict = static_verification_row.get("verdict")

    if verdict == "baseline_healthy_with_coverage":
        return VerificationTier(
            tier="hypothesis_verified_coverage",
            reason="E-1が、この仮説の対象領域を実際にカバーする既存テストを確認済み"
            "(仮説そのものの内容に基づく検証)",
        )

    if verdict == "insufficient_signal":
        sandbox_healthy = (
            latest_sandbox_verification is not None
            and latest_sandbox_verification.get("verdict") == "started_and_healthy"
        )
        if sandbox_healthy:
            return VerificationTier(
                tier="sandbox_infra_available_unverified_content",
                reason="この仮説の対象領域に既存テストは無いが、直近のE-2実行でサンドボックス基盤自体は"
                "健全に起動・停止できることを確認済み"
                "(注意: これは仮説の内容そのものを検証したものではない、環境の可用性の確認にすぎない)",
            )
        return VerificationTier(
            tier="not_eligible",
            reason="E-1でinsufficient_signalであり、かつ直近のE-2実行が健全でない、またはE-2が未実行のため",
        )

    return VerificationTier(tier="not_eligible", reason=f"E-1判定「{verdict}」は対象外")
