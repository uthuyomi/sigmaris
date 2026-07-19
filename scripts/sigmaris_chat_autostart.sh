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
#                               (既定: 本スクリプト自身の実体があるディレクトリ内の
#                               sigmaris_chat_v2.py。symlink経由で呼ばれた場合も、
#                               readlink -fで解決した実ディレクトリを基準にする)
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
#
# 【物理コンソール限定への修正(判断根拠、docs/sigmaris/
# cli_chat_investigation.md「物理コンソール判定」節に検証結果を詳述)】
#   Ubuntu Serverはヘッドレス構成のため、対話的なログインシェルの
#   制御端末(controlling terminal)は、以下の2種類しかありえない。
#     - /dev/tty1〜/dev/tty63 等: getty/loginがサーバーに直結された
#       モニター・キーボードのために立ち上げる、物理コンソール
#     - /dev/pts/N: 疑似端末(pseudo-terminal)。sshd経由のリモート
#       ログインは、必ずこちらになる(tmux/screen内のシェルも同様に
#       pts扱いになるが、これは.bashrc側の既存のTMUXガード
#       (scripts/sigmaris_chat_login_snippet.sh)で別途対処済みであり、
#       本スクリプト自身が判定すべき対象ではない)。
#   `tty`コマンドの出力(制御端末のパス)に加え、sshdが必ず設定する
#   環境変数(SSH_CONNECTION・SSH_TTY・SSH_CLIENT)のいずれかが1つでも
#   設定されていれば、tty名の判定結果によらず「物理コンソールではない」
#   と扱う——依頼書「SSH経由での自動起動を確実に防ぐことを最優先する」
#   への対応として、2つの独立した判定方法のうち、どちらか一方でも
#   「SSH的である」と判定すれば、安全側(起動しない)に倒す設計にした。
#   物理コンソールでないと判定された場合は、メッセージを一切出さず、
#   即座に終了する(依頼書2章「物理コンソールでは、ない、と判定された
#   場合は、何も、せず、即座に、終了する」)——SSH経由のあらゆるログイン
#   シェルの起動のたびに、無関係な出力が.bashrc経由で表示されることを
#   避けるため、この判定結果自体は非表示にし、既存の「バックエンドの
#   起動状態」の確認(2.以降、既存ロジックを維持)だけが、引き続き
#   メッセージを出す設計を保った。

set -u

# ─── 0. 物理コンソールからのログインであることを確認する ───────────────────

if [ -n "${SSH_CONNECTION:-}" ] || [ -n "${SSH_TTY:-}" ] || [ -n "${SSH_CLIENT:-}" ]; then
    exit 0
fi

_current_tty="$(tty 2>/dev/null)" || exit 0

case "$_current_tty" in
    /dev/tty[0-9]|/dev/tty[0-9][0-9])
        ;; # 物理コンソール(tty1〜tty63) — 起動処理を続行する
    *)
        exit 0
        ;;
esac

BACKEND_SERVICE="${SIGMARIS_BACKEND_SERVICE:-sigmaris-backend}"
# CHAT_SCRIPTの既定値は、$HOME直下への決め打ち("$HOME/sigmaris_chat_v2.py"、
# ~/sigmaris_chat_v2.py というシンボリックリンクが存在する前提)だったが、
# そのシンボリックリンクが実際には作成されず、本体が
# ~/shift-pilot-ai/scripts/sigmaris_chat_v2.py にしか存在しない環境で、
# 「見つからない」エラーになる不具合が判明した。本スクリプト自身の実体の
# あるディレクトリ(readlink -fでシンボリックリンクを解決した上でdirname)
# を基準に、同じディレクトリ内のsigmaris_chat_v2.pyを既定値にすることで、
# 本スクリプトがシンボリックリンク経由・リポジトリ直接参照のいずれで
# 呼ばれても、常に実体の隣にある正しいパスを指すようにした。
SCRIPT_REAL_PATH="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null || echo "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_REAL_PATH")"
CHAT_SCRIPT="${SIGMARIS_CHAT_SCRIPT:-$SCRIPT_DIR/sigmaris_chat_v2.py}"
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
