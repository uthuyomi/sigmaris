#!/home/sigmaris/shift-pilot-ai/backend/.venv/bin/python3
"""
Sigmaris Terminal Chat Client v2 — フロントエンド /chat 体験の再現版
デプロイ先: シンボリックリンクを推奨(git pullだけで更新が反映されるため)
    ln -sf ~/shift-pilot-ai/scripts/sigmaris_chat_v2.py ~/sigmaris_chat_v2.py
    (docs/sigmaris/cli_chat_investigation.md「運用上の課題への対応」参照)

依存ライブラリ: rich・httpx(backend/pyproject.tomlに記載済み、
                backend/.venvを再利用するため追加インストール不要)

設定読み込み:
    /home/sigmaris/shift-pilot-ai/backend/.env

【scripts/sigmaris_chat.py(v1)との関係、及び本ファイルを新規実装にした判断根拠】
このファイルは、v1(scripts/sigmaris_chat.py)を拡張したものではなく、
意図的に完全に独立した、新規のファイルである(依頼書2章「既存のsigmaris_
chat.pyを、そのまま拡張するのではなく、新規の実装として作成すること」)。
v1は変更・削除しておらず、両者は完全に独立して共存する。

ログイン・SSEストリーミング等、両ファイルで似た処理が重複することを
承知の上で、あえて共有ライブラリへ切り出さなかった——このプロジェクトの
既存の運用慣習(scripts/apply_migration.py・scripts/sigmaris_chat.pyは、
いずれも他のスクリプトに依存しない、単一ファイルで完結する設計になって
おり、サーバー上へ個別にデプロイ・実行できる)を踏襲し、v2だけを更新する
際に、v1に影響を与えない(その逆も同様)独立性を優先した判断である。

【v1との機能上の違い】
v1は、起動のたびに新規のthread_idを発行するのみで、過去のスレッドの
一覧・選択・履歴表示という概念を持たない。v2は、フロントエンドの/chat
画面が持つ、これらの体験を再現する。
    - 起動時、スレッド一覧を取得し、既存スレッドの再開、または新規
      スレッドの開始を選べる
    - 既存スレッドを選んだ場合、そのスレッドの会話履歴を表示してから
      対話を開始する
    - /threads コマンドで、セッション中にいつでもスレッドを切り替えられる
    - /new コマンドで、新規スレッドをその場で開始できる
    - /rename コマンドで、現在のスレッドの表題を変更できる
      (フロントエンドのスレッド管理機能を再現する、小さな追加)
Sigmaris Live(内部処理のリアルタイム可視化)は、依頼書の指示により、
意図的に含めていない。

応答生成は、v1と全く同じく、既存の/api/orchestrator/chat・
/api/orchestrator/chat/streamをそのまま呼ぶのみで、新しい応答生成の
ロジックは一切実装していない。

操作:
    Enter       — 送信
    Ctrl+C      — 終了
    /threads    — スレッド一覧を表示し、切り替える
    /new        — 新規スレッドを開始する
    /rename <表題>  — 現在のスレッドの表題を変更する
    /help       — コマンド一覧
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

# UTF-8 入出力を強制(SSH ターミナルでの日本語文字化け対策。v1と同じ対応)
sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

import httpx
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.text import Text

# ─── 定数 ─────────────────────────────────────────────────────────────────────

ENV_PATH = Path("/home/sigmaris/shift-pilot-ai/backend/.env")
BACKEND = "http://localhost:8000"
MAX_HISTORY = 40  # ローカルで保持する最大メッセージ数(v1と同じ考え方)
THREAD_PAGE_SIZE = 15  # 一覧に表示するスレッド数の上限

# ─── .env 読み込み(v1と同じ実装) ──────────────────────────────────────────


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
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        env[key] = value
    return env


_env = _load_env(ENV_PATH)

USER_JWT = _env.get("SIGMARIS_USER_JWT", "")
SUPABASE_URL = _env.get("NEXT_PUBLIC_SUPABASE_URL", "")
ANON_KEY = _env.get("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "")
USER_EMAIL = _env.get("SIGMARIS_USER_EMAIL", "")
USER_PASSWORD = _env.get("SIGMARIS_USER_PASSWORD", "")

console = Console(highlight=False)

# ─── ユーティリティ ───────────────────────────────────────────────────────────


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _fmt_dt(raw: str | None) -> str:
    if not raw:
        return "—"
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return str(raw)[:16]


# ─── 認証(v1と同じ実装) ──────────────────────────────────────────────────────


def login() -> str:
    global USER_JWT

    if not SUPABASE_URL or not ANON_KEY:
        raise RuntimeError("NEXT_PUBLIC_SUPABASE_URL または NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY が未設定です")
    if not USER_EMAIL or not USER_PASSWORD:
        raise RuntimeError("SIGMARIS_USER_EMAIL または SIGMARIS_USER_PASSWORD が未設定です")

    resp = httpx.post(
        f"{SUPABASE_URL}/auth/v1/token",
        params={"grant_type": "password"},
        headers={"apikey": ANON_KEY, "Content-Type": "application/json"},
        json={"email": USER_EMAIL, "password": USER_PASSWORD},
        timeout=15.0,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("access_token", "")
    if not token:
        raise RuntimeError(f"ログイン応答に access_token がありません: {data}")

    USER_JWT = token
    return token


def _user_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {USER_JWT}"}


# ─── API 呼び出し: チャットスレッド(依頼書の中核要件) ─────────────────────────
#
# frontend/src/lib/chat-threads.tsが呼ぶのと全く同じ、既存のバックエンド
# エンドポイント(backend/app/routes/app_data.py)をそのまま利用する。
# 新しいエンドポイントは一切追加していない。


def api_list_threads() -> list[dict[str, Any]]:
    """GET /api/app/chat/threads — updated_at降順(バックエンド側で既に整列済み)"""
    resp = httpx.get(f"{BACKEND}/api/app/chat/threads", headers=_user_headers(), timeout=15.0)
    resp.raise_for_status()
    return resp.json().get("threads", [])


def api_list_messages(thread_id: str) -> list[dict[str, Any]]:
    """GET /api/app/chat/threads/{thread_id}/messages — message_order昇順"""
    resp = httpx.get(
        f"{BACKEND}/api/app/chat/threads/{thread_id}/messages",
        headers=_user_headers(),
        timeout=15.0,
    )
    resp.raise_for_status()
    return resp.json().get("messages", [])


def api_create_thread() -> dict[str, Any]:
    """POST /api/app/chat/threads(thread_id省略、DB側で新規発行させる)"""
    resp = httpx.post(
        f"{BACKEND}/api/app/chat/threads",
        headers={**_user_headers(), "Content-Type": "application/json"},
        json={},
        timeout=15.0,
    )
    resp.raise_for_status()
    return resp.json().get("thread", {})


def api_rename_thread(thread_id: str, title: str) -> None:
    """PATCH /api/app/chat/threads/{thread_id}"""
    resp = httpx.patch(
        f"{BACKEND}/api/app/chat/threads/{thread_id}",
        headers={**_user_headers(), "Content-Type": "application/json"},
        json={"title": title},
        timeout=15.0,
    )
    resp.raise_for_status()


def _extract_text(parts: list[dict[str, Any]]) -> str:
    """UIMessage形式のpartsから、テキスト部分だけを連結して取り出す。
    file/tool等、テキスト以外のpartは、履歴表示上は無視する(依頼書が
    求めるのは会話履歴の表示であり、添付ファイルの再現ではないため)。"""
    texts = [str(p.get("text", "")) for p in parts if isinstance(p, dict) and p.get("type") == "text"]
    return "\n".join(t for t in texts if t.strip())


# ─── API 呼び出し: 応答生成(v1と全く同じ、既存エンドポイントの再利用) ──────


def api_chat(messages: list[dict], thread_id: str) -> tuple[str, str]:
    """POST /api/orchestrator/chat(ストリーミング失敗時のフォールバック用)"""
    for attempt in range(2):
        try:
            resp = httpx.post(
                f"{BACKEND}/api/orchestrator/chat",
                headers=_user_headers(),
                json={"messages": messages, "thread_id": thread_id},
                timeout=90.0,
            )
        except httpx.ConnectError:
            return "⚠ バックエンドに接続できません (http://localhost:8000)", thread_id
        except httpx.TimeoutException:
            return "⚠ タイムアウト — バックエンドの応答が90秒以内に返りませんでした", thread_id
        except Exception as e:
            return f"⚠ 予期しないエラー: {e}", thread_id

        if resp.status_code == 401 and attempt == 0:
            console.print("[dim cyan]  JWT期限切れ、再ログイン中...[/dim cyan]")
            try:
                login()
            except Exception as e:
                return f"⚠ 再ログイン失敗: {e}", thread_id
            continue

        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            try:
                detail = e.response.json().get("detail", {})
                msg = detail.get("error", e.response.text[:200]) if isinstance(detail, dict) else str(detail)[:200]
            except Exception:
                msg = e.response.text[:200]
            return f"⚠ HTTP {e.response.status_code}: {msg}", thread_id

        data = resp.json()
        return data.get("text", "(応答なし)"), data.get("thread_id", thread_id)

    return "⚠ 認証エラー: 再ログイン後も失敗しました", thread_id


def api_chat_stream(messages: list[dict], thread_id: str) -> tuple[str, str]:
    """POST /api/orchestrator/chat/stream(SSEストリーミング、v1と同じ実装)"""
    url = f"{BACKEND}/api/orchestrator/chat/stream"
    full_text = ""
    returned_thread_id = thread_id
    header_printed = False

    def _print_stream_header() -> None:
        ts = _ts()
        sys.stdout.write(f"\033[1;36mΣ シグマリス  [{ts}]\033[0m\n")
        sys.stdout.flush()

    try:
        req_headers = {**_user_headers(), "Content-Type": "application/json", "Accept": "text/event-stream"}
        with httpx.stream(
            "POST",
            url,
            headers=req_headers,
            json={"messages": messages, "thread_id": thread_id},
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0),
        ) as resp:
            if resp.status_code == 401:
                console.print("[dim cyan]  JWT期限切れ、再ログイン中...[/dim cyan]")
                try:
                    login()
                except Exception as e:
                    return f"⚠ 再ログイン失敗: {e}", thread_id
                text, tid = api_chat(messages, thread_id)
                print_sigmaris_msg(text, _ts())
                return text, tid

            if resp.is_error:
                raise httpx.HTTPError(f"HTTP {resp.status_code}")

            for line in resp.iter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw:
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                if "error" in event:
                    if header_printed:
                        sys.stdout.write("\n\n")
                        sys.stdout.flush()
                    return f"⚠ {event['error']}", thread_id

                if "delta" in event:
                    chunk: str = event["delta"]
                    if not header_printed:
                        _print_stream_header()
                        header_printed = True
                    full_text += chunk
                    sys.stdout.write(chunk)
                    sys.stdout.flush()

                if event.get("done"):
                    returned_thread_id = event.get("thread_id", thread_id)
                    break

        if header_printed:
            sys.stdout.write("\n\n")
            sys.stdout.flush()

        if not full_text:
            return "(応答なし)", returned_thread_id

        return full_text, returned_thread_id

    except (httpx.ConnectError, httpx.RemoteProtocolError):
        text, tid = api_chat(messages, thread_id)
        print_sigmaris_msg(text, _ts())
        return text, tid
    except Exception:
        text, tid = api_chat(messages, thread_id)
        print_sigmaris_msg(text, _ts())
        return text, tid


# ─── 表示 ─────────────────────────────────────────────────────────────────────


def print_header(thread_title: str) -> None:
    console.clear()
    console.print(Panel(
        f"[bold magenta]Σ  S I G M A R I S[/bold magenta]   [dim]{escape(thread_title)}[/dim]",
        style="bold magenta",
        expand=True,
        padding=(0, 2),
    ))
    console.print(
        "[dim]  Enter で送信  /  [bold]/threads[/bold] でスレッド切替  /  "
        "[bold]/help[/bold] でコマンド一覧  /  [bold]Ctrl+C[/bold] で終了[/dim]\n"
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
        "  [bold cyan]/threads[/bold cyan]        スレッド一覧を表示し、切り替える\n"
        "  [bold cyan]/new[/bold cyan]             新規スレッドを開始する\n"
        "  [bold cyan]/rename <表題>[/bold cyan]   現在のスレッドの表題を変更する\n"
        "  [bold cyan]/help[/bold cyan]            このヘルプを表示\n"
        "  [bold cyan]Ctrl+C[/bold cyan]           終了",
        title="[bold magenta]Σ HELP[/bold magenta]",
        style="magenta",
        padding=(1, 2),
    ))
    console.print()


def print_thinking() -> None:
    console.print("[dim cyan]  Σ 考えています...[/dim cyan]")


def print_error(msg: str) -> None:
    console.print(f"[bold red]  ⚠ {escape(msg)}[/bold red]\n")


def print_thread_history(messages: list[dict[str, Any]]) -> None:
    """フロントエンドの/chat画面が、スレッドを開いた際に既存の会話履歴を
    表示するのと同じ体験を再現する。"""
    if not messages:
        console.print("[dim]  (このスレッドには、まだメッセージがありません)[/dim]\n")
        return
    for msg in messages:
        role = msg.get("role")
        text = _extract_text(msg.get("parts") or [])
        if not text:
            continue
        ts = _fmt_dt(msg.get("created_at"))
        if role == "assistant":
            print_sigmaris_msg(text, ts)
        else:
            print_user_msg(text, ts)


# ─── スレッド選択(依頼書の中核要件: 一覧・切り替え) ────────────────────────


def choose_thread() -> tuple[str, str, list[dict[str, str]]]:
    """スレッド一覧を表示し、既存スレッドの再開、または新規スレッドの
    開始を選ばせる。戻り値: (thread_id, thread_title, ローカルmessages初期値)。"""
    console.print("[dim cyan]  スレッド一覧を取得中...[/dim cyan]")
    try:
        threads = api_list_threads()
    except Exception as e:
        print_error(f"スレッド一覧の取得に失敗しました: {e}")
        threads = []

    threads = threads[:THREAD_PAGE_SIZE]

    lines = ["[bold]0[/bold]  新しいチャットを開始"]
    for i, t in enumerate(threads, start=1):
        title = escape(str(t.get("title") or "(無題)"))
        updated = _fmt_dt(t.get("updated_at"))
        lines.append(f"[bold]{i}[/bold]  {title}  [dim]({updated})[/dim]")

    console.print(Panel(
        "\n".join(lines),
        title="[bold magenta]Σ スレッド選択[/bold magenta]",
        style="magenta",
        padding=(1, 2),
    ))

    while True:
        choice = console.input("[bold white]番号を選んでください > [/bold white]").strip()
        if choice == "0" or choice == "":
            try:
                thread = api_create_thread()
            except Exception as e:
                print_error(f"新規スレッドの作成に失敗しました: {e}")
                continue
            return thread["id"], thread.get("title", "新しいチャット"), []

        if choice.isdigit() and 1 <= int(choice) <= len(threads):
            selected = threads[int(choice) - 1]
            thread_id = selected["id"]
            title = selected.get("title", "新しいチャット")
            console.print("[dim cyan]  会話履歴を取得中...[/dim cyan]")
            try:
                history = api_list_messages(thread_id)
            except Exception as e:
                print_error(f"会話履歴の取得に失敗しました: {e}")
                history = []
            local_messages = [
                {"role": m["role"], "content": _extract_text(m.get("parts") or [])}
                for m in history
                if m.get("role") in ("user", "assistant") and _extract_text(m.get("parts") or [])
            ]
            return thread_id, title, local_messages

        console.print("[dim]  不正な選択です。番号を入力してください。[/dim]")


# ─── 入力読み取り(v1と同じ実装) ──────────────────────────────────────────────


def _read_input() -> str | None:
    lines: list[str] = []
    first = True
    while True:
        prompt = "\033[1;37m> \033[0m" if first else "  "
        sys.stdout.write(prompt)
        sys.stdout.flush()
        first = False

        try:
            raw = sys.stdin.readline()
        except UnicodeDecodeError:
            sys.stdout.write("\n")
            sys.stdout.flush()
            continue

        if not raw:
            return None

        line = raw.rstrip("\n").rstrip("\r")
        if line.endswith("\\"):
            lines.append(line[:-1])
        else:
            lines.append(line)
            break

    return "\n".join(lines)


# ─── 事前チェック(v1と同じ実装) ──────────────────────────────────────────────


def _preflight() -> None:
    if not ENV_PATH.exists():
        console.print(f"[bold red]エラー:[/bold red] .env ファイルが見つかりません: {ENV_PATH}")
        sys.exit(1)

    if not USER_EMAIL or not USER_PASSWORD:
        console.print(
            "[bold red]エラー:[/bold red] SIGMARIS_USER_EMAIL または SIGMARIS_USER_PASSWORD が設定されていません。\n"
            f"[dim]{ENV_PATH}[/dim] を確認してください。"
        )
        sys.exit(1)

    console.print("[dim cyan]  Supabase にログイン中...[/dim cyan]")
    try:
        login()
        console.print("[dim cyan]  ログイン完了[/dim cyan]\n")
    except Exception as e:
        console.print(f"[bold red]エラー:[/bold red] ログイン失敗: {e}")
        sys.exit(1)


# ─── メインループ ─────────────────────────────────────────────────────────────


def main() -> None:
    _preflight()

    thread_id, thread_title, messages = choose_thread()
    print_header(thread_title)
    if messages:
        print_thread_history([
            {"role": m["role"], "parts": [{"type": "text", "text": m["content"]}]} for m in messages
        ])

    try:
        while True:
            user_input = _read_input()
            if user_input is None:  # EOF (Ctrl+D)
                break
            user_input = user_input.strip()

            if not user_input:
                continue

            # ─── コマンド処理 ────────────────────────────────────────────────

            if user_input.lower() == "/threads":
                thread_id, thread_title, messages = choose_thread()
                print_header(thread_title)
                if messages:
                    print_thread_history([
                        {"role": m["role"], "parts": [{"type": "text", "text": m["content"]}]} for m in messages
                    ])
                continue

            if user_input.lower() == "/new":
                try:
                    thread = api_create_thread()
                except Exception as e:
                    print_error(f"新規スレッドの作成に失敗しました: {e}")
                    continue
                thread_id, thread_title, messages = thread["id"], thread.get("title", "新しいチャット"), []
                print_header(thread_title)
                continue

            if user_input.lower().startswith("/rename"):
                new_title = user_input[len("/rename"):].strip()
                if not new_title:
                    console.print("[dim]  使い方: /rename <新しい表題>[/dim]\n")
                    continue
                try:
                    api_rename_thread(thread_id, new_title)
                    thread_title = new_title
                    console.print(f"[dim]  表題を変更しました: {escape(new_title)}[/dim]\n")
                except Exception as e:
                    print_error(f"表題の変更に失敗しました: {e}")
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

            # ─── チャット送信(既存の応答生成APIをそのまま再利用) ──────────────

            ts_user = _ts()
            console.print()
            print_user_msg(user_input, ts_user)

            messages.append({"role": "user", "content": user_input})

            print_thinking()
            response_text, thread_id = api_chat_stream(messages, thread_id)

            messages.append({"role": "assistant", "content": response_text})

            if len(messages) > MAX_HISTORY:
                messages = messages[-MAX_HISTORY:]

    except KeyboardInterrupt:
        console.print(
            "\n\n[dim magenta]  またね。シグマリスを終了します。[/dim magenta]\n"
        )
        sys.exit(0)


if __name__ == "__main__":
    main()
