#!/usr/bin/env python3
"""
Sigmaris Terminal Chat Client
デプロイ先: /home/sigmaris/sigmaris_chat.py

依存ライブラリ:
    pip install rich httpx --break-system-packages

設定読み込み:
    /home/sigmaris/shift-pilot-ai/backend/.env

操作:
    Enter       — 送信
    Ctrl+C      — 終了
    /clear      — チャット履歴クリア
    /status     — シグマリスの状態表示
    /help       — コマンド一覧
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

# ─── 定数 ─────────────────────────────────────────────────────────────────────

ENV_PATH = Path("/home/sigmaris/shift-pilot-ai/backend/.env")
BACKEND = "http://localhost:8000"
MAX_HISTORY = 40   # 保持する最大メッセージ数（古いものから削除）

# ─── .env 読み込み ─────────────────────────────────────────────────────────────

def _load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # シングル・ダブルクォートを除去
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        env[key] = value
    return env


_env = _load_env(ENV_PATH)

USER_JWT       = _env.get("SIGMARIS_USER_JWT", "")
AGENT_ID       = _env.get("SCHEDULE_AGENT_ID", "sigmaris-orchestrator")
AGENT_SECRET   = _env.get("SCHEDULE_AGENT_SECRET", "")
SUPABASE_URL   = _env.get("NEXT_PUBLIC_SUPABASE_URL", "")
SERVICE_KEY    = _env.get("SUPABASE_SERVICE_ROLE_KEY", "")
LAUNCH_DATE    = _env.get("SIGMARIS_LAUNCH_DATE", "")

# AGENT_SECRETS JSON から secret を補完（SCHEDULE_AGENT_SECRET 未設定の場合）
if not AGENT_SECRET:
    raw_secrets = _env.get("AGENT_SECRETS", "")
    if raw_secrets:
        try:
            AGENT_SECRET = json.loads(raw_secrets).get(AGENT_ID, "")
        except (json.JSONDecodeError, AttributeError):
            pass

# ─── Console ──────────────────────────────────────────────────────────────────

console = Console(highlight=False)

# ─── ユーティリティ ───────────────────────────────────────────────────────────

def _ts() -> str:
    """現在時刻 HH:MM:SS"""
    return datetime.now().strftime("%H:%M:%S")


def _uptime() -> str:
    """稼働日数を計算して返す"""
    if not LAUNCH_DATE:
        return "不明"
    try:
        delta = date.today() - date.fromisoformat(LAUNCH_DATE)
        return f"{delta.days}日"
    except ValueError:
        return "不明"


def _fmt_dt(raw: str | None) -> str:
    """ISO 8601 を読みやすい形式に変換"""
    if not raw:
        return "—"
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        # ローカルタイムに変換
        local = dt.astimezone()
        return local.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return str(raw)[:16]


# ─── HTTP ヘッダー ────────────────────────────────────────────────────────────

def _user_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {USER_JWT}"}


def _agent_headers(with_jwt: bool = False) -> dict[str, str]:
    h: dict[str, str] = {
        "X-Agent-Id":     AGENT_ID,
        "X-Agent-Secret": AGENT_SECRET,
    }
    if with_jwt:
        h["Authorization"] = f"Bearer {USER_JWT}"
    return h


def _supabase_headers() -> dict[str, str]:
    return {
        "apikey":        SERVICE_KEY,
        "Authorization": f"Bearer {SERVICE_KEY}",
        "Prefer":        "count=exact",
        "Range":         "0-0",
    }


# ─── API 呼び出し ─────────────────────────────────────────────────────────────

def api_chat(messages: list[dict], thread_id: str) -> tuple[str, str]:
    """
    POST /api/orchestrator/chat
    Returns: (response_text, thread_id)
    """
    try:
        resp = httpx.post(
            f"{BACKEND}/api/orchestrator/chat",
            headers=_user_headers(),
            json={"messages": messages, "thread_id": thread_id},
            timeout=90.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("text", "(応答なし)"), data.get("thread_id", thread_id)
    except httpx.ConnectError:
        return "⚠ バックエンドに接続できません (http://localhost:8000)", thread_id
    except httpx.TimeoutException:
        return "⚠ タイムアウト — バックエンドの応答が90秒以内に返りませんでした", thread_id
    except httpx.HTTPStatusError as e:
        try:
            detail = e.response.json().get("detail", {})
            msg = detail.get("error", e.response.text[:200]) if isinstance(detail, dict) else str(detail)[:200]
        except Exception:
            msg = e.response.text[:200]
        return f"⚠ HTTP {e.response.status_code}: {msg}", thread_id
    except Exception as e:
        return f"⚠ 予期しないエラー: {e}", thread_id


def api_self_model() -> dict[str, Any]:
    """GET /api/agent/self/model"""
    try:
        resp = httpx.get(
            f"{BACKEND}/api/agent/self/model",
            headers=_agent_headers(with_jwt=False),
            timeout=15.0,
        )
        resp.raise_for_status()
        return resp.json().get("model") or {}
    except Exception:
        return {}


def api_fact_count() -> str:
    """GET /api/agent/facts/items → 件数"""
    if not USER_JWT:
        return "—"
    try:
        resp = httpx.get(
            f"{BACKEND}/api/agent/facts/items",
            headers=_agent_headers(with_jwt=True),
            timeout=15.0,
        )
        resp.raise_for_status()
        return str(resp.json().get("count", "—"))
    except Exception:
        return "—"


def api_research_count() -> str:
    """Supabase REST で research_items の件数を取得"""
    if not SUPABASE_URL or not SERVICE_KEY:
        return "—"
    try:
        resp = httpx.get(
            f"{SUPABASE_URL}/rest/v1/research_items",
            headers=_supabase_headers(),
            params={"select": "id"},
            timeout=15.0,
        )
        cr = resp.headers.get("content-range", "")
        # Content-Range: 0-0/TOTAL  or  */0
        if "/" in cr:
            return cr.split("/")[-1]
        # 件数0の場合は body が [] になる
        if resp.status_code in (200, 206):
            try:
                data = resp.json()
                if isinstance(data, list):
                    return "0"
            except Exception:
                pass
        return "—"
    except Exception:
        return "—"


def fetch_status() -> dict[str, str]:
    """全ステータス情報を収集して dict で返す"""
    model = api_self_model()
    return {
        "version":          str(model.get("version", "—")),
        "last_reflected":   _fmt_dt(model.get("reflected_at") or model.get("updated_at")),
        "fact_count":       api_fact_count(),
        "research_count":   api_research_count(),
        "uptime":           _uptime(),
    }


# ─── 表示 ─────────────────────────────────────────────────────────────────────

def print_header() -> None:
    console.clear()
    console.print(Panel(
        f"[bold magenta]Σ  S I G M A R I S[/bold magenta]   "
        f"[dim]稼働 {_uptime()}[/dim]",
        style="bold magenta",
        expand=True,
        padding=(0, 2),
    ))
    console.print(
        "[dim]  Enter で送信  /  [bold]/help[/bold] でコマンド一覧  /  "
        "[bold]Ctrl+C[/bold] で終了[/dim]\n"
    )


def print_sigmaris_msg(content: str, ts: str) -> None:
    header = Text()
    header.append("Σ シグマリス", style="bold cyan")
    header.append(f"  [{ts}]", style="dim")
    console.print(header)
    console.print(Text(content, style="cyan"))
    console.print()


def print_user_msg(content: str, ts: str) -> None:
    header = Text()
    header.append("あなた", style="bold white")
    header.append(f"  [{ts}]", style="dim")
    console.print(header)
    console.print(Text(content, style="white"))
    console.print()


def print_help() -> None:
    console.print(Panel(
        "[bold]コマンド一覧[/bold]\n\n"
        "  [bold cyan]/clear[/bold cyan]    チャット履歴をクリアして最初から\n"
        "  [bold cyan]/status[/bold cyan]   シグマリスの状態を表示\n"
        "  [bold cyan]/help[/bold cyan]     このヘルプを表示\n"
        "  [bold cyan]Ctrl+C[/bold cyan]    終了\n\n"
        "[dim]メッセージを入力して Enter を押すと送信されます。[/dim]",
        title="[bold magenta]Σ HELP[/bold magenta]",
        style="magenta",
        padding=(1, 2),
    ))
    console.print()


def print_status() -> None:
    console.print("[dim cyan]  ステータスを取得中...[/dim cyan]")
    s = fetch_status()

    lines = (
        f"  [bold]自己モデル バージョン:[/bold]    [cyan]{escape(s['version'])}[/cyan]\n"
        f"  [bold]記憶している事実の件数:[/bold]  [cyan]{escape(s['fact_count'])}[/cyan]\n"
        f"  [bold]最終自己反省日時:[/bold]        [cyan]{escape(s['last_reflected'])}[/cyan]\n"
        f"  [bold]稼働日数:[/bold]                [cyan]{escape(s['uptime'])}[/cyan]\n"
        f"  [bold]リサーチ済み記事数:[/bold]      [cyan]{escape(s['research_count'])}[/cyan]"
    )
    console.print(Panel(
        lines,
        title="[bold magenta]Σ STATUS[/bold magenta]",
        style="magenta",
        padding=(1, 0),
    ))
    console.print()


def print_thinking() -> None:
    console.print("[dim cyan]  Σ 考えています...[/dim cyan]")


def print_error(msg: str) -> None:
    console.print(f"[bold red]  ⚠ {escape(msg)}[/bold red]\n")


# ─── 事前チェック ─────────────────────────────────────────────────────────────

def _preflight() -> None:
    if not ENV_PATH.exists():
        console.print(f"[bold red]エラー:[/bold red] .env ファイルが見つかりません: {ENV_PATH}")
        sys.exit(1)

    if not USER_JWT:
        console.print(
            "[bold red]エラー:[/bold red] SIGMARIS_USER_JWT が設定されていません。\n"
            f"[dim]{ENV_PATH}[/dim] に SIGMARIS_USER_JWT を設定してください。"
        )
        sys.exit(1)

    if not AGENT_SECRET:
        console.print(
            "[bold yellow]警告:[/bold yellow] SCHEDULE_AGENT_SECRET / AGENT_SECRETS が未設定です。\n"
            "[dim]/status コマンドの一部機能が制限されます。[/dim]"
        )


# ─── メインループ ─────────────────────────────────────────────────────────────

def main() -> None:
    _preflight()

    messages: list[dict[str, str]] = []
    thread_id = str(uuid.uuid4())

    print_header()

    try:
        while True:
            try:
                user_input = console.input("[bold white]> [/bold white]").strip()
            except EOFError:
                break

            if not user_input:
                continue

            # ─── コマンド処理 ────────────────────────────────────────────────

            if user_input.lower() == "/clear":
                messages = []
                thread_id = str(uuid.uuid4())
                print_header()
                console.print("[dim]  チャット履歴をクリアしました。[/dim]\n")
                continue

            if user_input.lower() == "/status":
                print_status()
                continue

            if user_input.lower() == "/help":
                print_help()
                continue

            if user_input.startswith("/"):
                console.print(
                    f"[dim]  不明なコマンド: {escape(user_input)}  "
                    "([bold]/help[/bold] でコマンド一覧)[/dim]\n"
                )
                continue

            # ─── チャット送信 ─────────────────────────────────────────────────

            ts_user = _ts()
            console.print()
            print_user_msg(user_input, ts_user)

            messages.append({"role": "user", "content": user_input})

            print_thinking()
            response_text, thread_id = api_chat(messages, thread_id)

            ts_resp = _ts()
            print_sigmaris_msg(response_text, ts_resp)

            messages.append({"role": "assistant", "content": response_text})

            # 長期会話でのトークン肥大化を防ぐ（最新 MAX_HISTORY 件を保持）
            if len(messages) > MAX_HISTORY:
                messages = messages[-MAX_HISTORY:]

    except KeyboardInterrupt:
        console.print(
            "\n\n[dim magenta]  またね。シグマリスを終了します。[/dim magenta]\n"
        )
        sys.exit(0)


if __name__ == "__main__":
    main()
