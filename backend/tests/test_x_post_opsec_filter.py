from __future__ import annotations

# X_POST_OPSEC_FILTER_SPEC / X_OPSEC_LAYER1_REFINE_SPEC の回帰テスト。
# 公開X投稿から自宅インフラの"具体的な秘密"が漏れないことを2層で担保する。
# 線引き(X_OPSEC_LAYER1_REFINE): 機材・存在レベル(GPU型番/OS/自宅サーバー運用)
# は公開OK、actionable な具体秘密(IP/認証/ポート/回線設定/連絡先)のみ非公開。
# 層1・層2は同一の actionable 基準(filter_private_info)に揃っている。
# ネットワーク非依存(DB/LLM に触れない・正規表現のみで決定的)。

from app.services.x_post_category_selector import (
    _is_sensitive_confirm_candidate,
    _public_safe_confirm_candidates,
)
from app.services.x_privacy_filter import filter_private_info


# ─── 層1(本丸): actionable な具体秘密を含む候補だけ公開Aから除外 ──────
def test_machine_level_candidate_is_public_safe():
    # 機材・存在レベルの確認は公開に通す(除外しない)。
    assert not _is_sensitive_confirm_candidate(
        {"category": "devices", "key": "home_server", "value": "自宅サーバーでGTX1660を動かしてるらしい", "confirm_reason": "low_confidence"}
    )
    assert not _is_sensitive_confirm_candidate(
        {"category": "environment", "key": "os", "value": "OSはUbuntu、AIサーバーとして運用してる", "confirm_reason": "low_confidence"}
    )
    assert not _is_sensitive_confirm_candidate(
        {"category": "devices", "key": "gpu", "value": "GTX1660 6GB", "confirm_reason": "long_unupdated"}
    )


def test_concrete_secret_candidate_is_sensitive():
    # IP / 認証情報 / ポート開放 / 連絡先 を含む候補は除外(active_inquiry へ)。
    assert _is_sensitive_confirm_candidate(
        {"category": "environment", "key": "expose", "value": "外部公開のためポート12345を開ける", "confirm_reason": "low_confidence"}
    )
    assert _is_sensitive_confirm_candidate(
        {"category": "devices", "key": "ip", "value": "IPは 192.168.0.11", "confirm_reason": "low_confidence"}
    )
    assert _is_sensitive_confirm_candidate(
        {"category": "devices", "key": "auth", "value": "api_key=abcd1234efgh を使ってる", "confirm_reason": "low_confidence"}
    )
    assert _is_sensitive_confirm_candidate(
        {"category": "profile", "key": "email", "value": "連絡先は foo@example.com", "confirm_reason": "low_confidence"}
    )


def test_broad_infra_terms_alone_do_not_exclude():
    # 広いインフラ語(server/gpu/gtx/ubuntu 等)だけでは除外しない(線引きの要)。
    assert not _is_sensitive_confirm_candidate(
        {"category": "goals", "key": "plan", "value": "自宅サーバをもっと活用したい", "confirm_reason": "low_confidence"}
    )


def test_non_infra_candidate_is_public_safe():
    assert not _is_sensitive_confirm_candidate(
        {"category": "preferences", "key": "favorite_food", "value": "ラーメン", "confirm_reason": "low_confidence"}
    )


def test_public_safe_keeps_machine_level_excludes_secrets():
    candidates = [
        {"category": "devices", "key": "home_server", "value": "自宅サーバーでGTX1660を動かしてる"},   # 公開OK
        {"category": "environment", "key": "os", "value": "OSはUbuntu Server"},                      # 公開OK
        {"category": "environment", "key": "expose", "value": "SIM対応ルータで外部公開、ポート開放してる"},  # 除外(回帰: 当初漏洩例)
        {"category": "devices", "key": "ip", "value": "IPは 192.168.0.11"},                         # 除外
    ]
    safe = _public_safe_confirm_candidates(candidates)
    keys = {c["key"] for c in safe}
    assert keys == {"home_server", "os"}


def test_public_safe_all_machine_level_kept():
    # 機材レベルばかりなら全部残る(=公開材料が消えて「投稿なし」にならない)。
    candidates = [
        {"category": "environment", "key": "home_server", "value": "自宅でAIサーバー運用してる"},
        {"category": "devices", "key": "gpu", "value": "GTX1660 6GB"},
    ]
    assert len(_public_safe_confirm_candidates(candidates)) == 2


# ─── 層2(保険): actionable な opsec のみブロック ─────────────────────
def _blocked(text: str) -> bool:
    safe, _detected = filter_private_info(text)
    return not safe


def test_layer2_blocks_actionable():
    assert _blocked("100.64.1.5 でアクセスできる")            # CGNAT
    assert _blocked("192.168.0.11 が自宅サーバー")            # 既存 IPv4
    assert _blocked("ポート12345を開けて外部公開してる")       # ポート+外部公開
    assert _blocked("port 8080 を公開")
    assert _blocked("api_key=abcd1234efgh")                    # 認証情報(既存)
    assert _blocked("固定IPでDDNS設定した")
    assert _blocked("ポートフォワーディングを設定")
    assert _blocked("SSIDは myhome_wifi")
    assert _blocked("sigmaris.local に繋いでる")               # 内部ホスト名
    assert _blocked("Tailscaleで 100.100.1.2 のノードに繋ぐ")  # 文脈依存+接地あり


def test_layer2_does_not_block_mere_mention():
    # 方針の要: 具体設定を伴わない単なる言及は弾かない(D/E の技術発信を守る)。
    assert not _blocked("自宅サーバーでGTX1660を動かしてる")
    assert not _blocked("使ってるOSはUbuntu Serverです")
    assert not _blocked("Tailscaleでリモート開発してる")       # 接地なし
    assert not _blocked("新しいアーキテクチャの設計を考えた")   # D/E 高レベル
    assert not _blocked("今日はよく眠れた")                     # 無害 remark
    assert not _blocked("モバイルルータで外に出てる")           # 一般語のみ
