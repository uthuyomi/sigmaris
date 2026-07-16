# Phase S-4(docs/sigmaris/phase_s_report.md): Constitution層 — Capability
# (能力の一線)の技術的実装。
#
# docs/sigmaris/constitution.md Article 6「必ず承認が必要なこと」を、
# S-2(goal_proposal.py)の行動生成に対して照合できる形に、4つのカテゴリ
# へ集約しただけのもの。新しい重量級フィルタではなく、行動カテゴリ文字列
# を固定リストと突き合わせるだけの、純粋関数・I/Oなしのチェックリスト。
#
# 【重要】この一線は「日常の検閲官」ではない——4カテゴリ以外の行動には
# 一切関与しない。S-0〜S-3の既存の自由な動作(観察・提案の言語化・調査
# クエリのキュー登録等)は、このモジュールの対象外であり続ける
# (docs/sigmaris/constitution.md Article 6「承認なしで自律実行できること」)。
#
# 判断根拠(4カテゴリの選定): Article 6の承認必須リスト(コード変更/Git
# 操作/DB構造変更/データ削除/外部投稿/課金・外部サービス操作/憲法変更/
# 人格構造変更)を、意味的に重複しない4つの軸へ集約した——
#   - delete_data: 重要なデータの削除
#   - external_transmission: ユーザーの許可なき外部送信・投稿
#   - code_change: コード・DB構造・システム設定の変更(将来Phase D以降)
#   - credential_access: 認証情報・APIキー等への未承認アクセス
# 「憲法の変更」「人格構造の変更」は、この文書自体が人間の直接編集のみを
# 前提とする固定文書であるため(AIによる自動書き換え機構を持たない)、
# 行動カテゴリとして照合する対象に含めていない——そもそも実行系の"行動"
# ではなく文書編集であり、Sigmaris自身が実行しうる行動空間の外にある。

from __future__ import annotations

# docs/sigmaris/constitution.md Article 6 と対応。この文書は人間(海星
# さん)が直接編集する固定文書であり、この定数リストも同文書の変更に
# 追随して人間が編集するものとする——実行時にプログラムから書き換える
# コードは存在しない(存在させない)。
CAPABILITY_APPROVAL_REQUIRED_CATEGORIES: frozenset[str] = frozenset(
    {
        "delete_data",
        "external_transmission",
        "code_change",
        "credential_access",
    }
)


def requires_approval(capability_category: str | None) -> bool:
    """Trueなら、ユーザーの明示的な承認なしに実行してはならない。

    capability_categoryがNone、または4カテゴリのいずれにも一致しない
    場合はFalse(=承認不要、日常的な自由な行動)。未知の文字列を安全側
    (承認必要)に倒すことはしない——本関数は「明示的にリストへ載って
    いるものだけを止める」チェックリストであり、憶測で行動を止める
    検閲機構ではない(docs/sigmaris/constitution.md の運用原則)。
    """
    if not capability_category:
        return False
    return capability_category in CAPABILITY_APPROVAL_REQUIRED_CATEGORIES
