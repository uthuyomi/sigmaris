from __future__ import annotations

# X_POST_OPSEC_FILTER_SPEC の回帰テスト。
# 公開X投稿から自宅インフラ/機微記憶が漏れないことを、2層で担保する。
# ネットワーク非依存(DB/LLM に触れない): 層1は confirm_candidates の振り分け
# ヘルパーを直接検証、層2は filter_private_info(正規表現のみ)を直接検証する。

from app.services.x_post_category_selector import (
    _is_sensitive_confirm_candidate,
    _public_safe_confirm_candidates,
)
from app.services.x_privacy_filter import filter_private_info


# ─── 層1(本丸): 機微 confirm_candidate を公開A素材から除外 ────────────
def test_infra_candidate_is_sensitive_by_category():
    # 実サンプル相当: 自宅サーバー構成(environment/devices カテゴリ)。
    assert _is_sensitive_confirm_candidate(
        {"category": "environment", "key": "home_server", "value": "自宅Ubuntu Server + GTX1660", "confirm_reason": "low_confidence"}
    )
    assert _is_sensitive_confirm_candidate(
        {"category": "devices", "key": "router", "value": "SIM対応ルータ", "confirm_reason": "low_confidence"}
    )


def test_infra_candidate_is_sensitive_by_term_in_other_category():
    # category が汎用(goals)でも、value にインフラ/opsec 語があれば機微扱い。
    assert _is_sensitive_confirm_candidate(
        {"category": "goals", "key": "plan", "value": "自宅サーバを外部公開したい", "confirm_reason": "low_confidence"}
    )


def test_non_infra_candidate_is_not_sensitive():
    assert not _is_sensitive_confirm_candidate(
        {"category": "preferences", "key": "favorite_food", "value": "ラーメン", "confirm_reason": "low_confidence"}
    )
    assert not _is_sensitive_confirm_candidate(
        {"category": "health", "key": "sleep", "value": "早寝早起き", "confirm_reason": "flagged_stale"}
    )


def test_public_safe_excludes_infra_keeps_others():
    candidates = [
        {"category": "environment", "key": "home_server", "value": "自宅Ubuntu Server + GTX1660"},
        {"category": "devices", "key": "router", "value": "SIM対応ルータ"},
        {"category": "preferences", "key": "hobby", "value": "写真"},
    ]
    safe = _public_safe_confirm_candidates(candidates)
    # 公開Aに載るのは非機微の1件のみ。インフラ2件は外れる(active_inquiry へ)。
    assert len(safe) == 1
    assert safe[0]["key"] == "hobby"


def test_public_safe_all_infra_yields_empty():
    # 全候補が機微なら公開A素材は空 → 呼び出し側は A を eligible にしない。
    candidates = [
        {"category": "environment", "key": "home_server", "value": "自宅Ubuntu Server"},
        {"category": "devices", "key": "gpu", "value": "GTX1660 6GB"},
    ]
    assert _public_safe_confirm_candidates(candidates) == []


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
