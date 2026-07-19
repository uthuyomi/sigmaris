#!/bin/bash
# Sigmaris CLIチャット: 自動起動ラッパー
# デプロイ先: /home/sigmaris/sigmaris_chat_autostart.sh
#   (シンボリックリンクを推奨。docs/sigmaris/cli_chat_investigation.md
#   「運用上の課題への対応」節を参照——リポジトリを`git pull`しただけで、
#   サーバー上の実体にも変更が反映されるようにするため)
#     ln -sf ~/shift-pilot-ai/scripts/sigmaris_chat_autostart.sh ~/sigmaris_chat_autostart.sh
#     chmod +x ~/shift-pilot-ai/scripts/sigmaris_chat_autostart.sh
#
# 役割:
#   1. バックエンド(systemdサービス sigmaris-backend)が "active (running)"
#      であることを確認する。
#   2. activeでなければ、分かりやすいメッセージを表示し、チャットを一切
#      起動せずに終了する(依頼書の必須要件2)。
#   3. activeであれば、tmuxセッション(既定名: sigmaris-chat)にアタッチ
#      する。セッションが無ければ新規作成し、その中でCLIチャット
#      (既定: sigmaris_chat_v2.py)を起動する。これにより、SSH接続が
#      切れても、セッション自体は生き続ける(依頼書の判断根拠、後述)。
#
# ~/.bash_profile 等、ログインシェルの設定へ組み込んで使う想定
# (scripts/sigmaris_chat_login_snippet.sh に、組み込み方の実例がある)。
#
# 設定(環境変数で上書き可能。既定値は本番サーバーの構成を想定):
#   SIGMARIS_BACKEND_SERVICE  — 確認対象のsystemdサービス名(既定: sigmaris-backend)
#   SIGMARIS_CHAT_SCRIPT      — 起動するCLIチャットの実行ファイル
#                               (既定: ~/sigmaris_chat_v2.py)
#   SIGMARIS_TMUX_SESSION     — tmuxセッション名(既定: sigmaris-chat)
#
# 判断根拠(依頼書「tmuxを使い、SSH切断でもセッションが継続する、という
# 方針を踏襲すること」への対応):
#   sigmaris_chat.py・sigmaris_chat_v2.pyは、いずれも対話的な標準入出力
#   (TTY)を前提にした設計であり(docs/sigmaris/cli_chat_investigation.md、
#   6.1節で確認済み)、systemdサービス化(バックグラウンドデーモン化)には
#   構造的に向かない。ログインシェルからの起動+tmuxによるセッション
#   永続化の組み合わせが、既存の実装を変更せずに「SSH切断でも継続する」を
#   実現できる、唯一の現実的な方式だと判断した。

set -u

BACKEND_SERVICE="${SIGMARIS_BACKEND_SERVICE:-sigmaris-backend}"
CHAT_SCRIPT="${SIGMARIS_CHAT_SCRIPT:-$HOME/sigmaris_chat_v2.py}"
TMUX_SESSION="${SIGMARIS_TMUX_SESSION:-sigmaris-chat}"

# ─── 1. バックエンドの起動状態を確認する ───────────────────────────────────

if ! command -v systemctl >/dev/null 2>&1; then
    echo "⚠ systemctlが見つかりません。バックエンドの起動状態を確認できないため、CLIチャットは起動しません。"
    exit 1
fi

if ! systemctl is-active --quiet "$BACKEND_SERVICE"; then
    echo "⚠ バックエンド ($BACKEND_SERVICE) が起動していません。CLIチャットは起動しません。"
    echo "  状態確認: systemctl status $BACKEND_SERVICE"
    exit 1
fi

# ─── 2. チャットスクリプトの存在確認 ────────────────────────────────────────

if [ ! -e "$CHAT_SCRIPT" ]; then
    echo "⚠ CLIチャットの実行ファイルが見つかりません: $CHAT_SCRIPT"
    echo "  SIGMARIS_CHAT_SCRIPT環境変数で、パスを指定できます。"
    exit 1
fi

# ─── 3. tmux経由での起動(SSH切断でもセッションを継続させる) ──────────────

if ! command -v tmux >/dev/null 2>&1; then
    echo "  tmuxが見つかりません。直接起動します(SSH切断すると終了します)。"
    exec "$CHAT_SCRIPT"
fi

if tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
    exec tmux attach-session -t "$TMUX_SESSION"
else
    exec tmux new-session -s "$TMUX_SESSION" "$CHAT_SCRIPT"
fi
