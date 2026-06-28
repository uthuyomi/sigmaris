#!/home/sigmaris/shift-pilot-ai/backend/.venv/bin/python3
"""
Supabase マイグレーション適用スクリプト
デプロイ先: /home/sigmaris/shift-pilot-ai/scripts/apply_migration.py

使い方:
    python3 apply_migration.py                        # 全 pending migration を適用
    python3 apply_migration.py 202606280021           # 番号指定で1件だけ適用
    python3 apply_migration.py --list                 # 適用済み一覧を表示

仕組み:
    Supabase Management API の SQL 実行エンドポイントを使用する。
    接続情報は /home/sigmaris/shift-pilot-ai/backend/.env から読み取る。

必要な環境変数:
    NEXT_PUBLIC_SUPABASE_URL        — https://xxxx.supabase.co
    SUPABASE_SERVICE_ROLE_KEY       — service_role JWT

適用済み管理:
    スクリプトと同じディレクトリに .applied_migrations を保存する。
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import httpx

# ─── 設定 ─────────────────────────────────────────────────────────────────────

_SCRIPT_DIR = Path(__file__).parent
_REPO_ROOT = _SCRIPT_DIR.parent
_ENV_PATH = _REPO_ROOT / "backend" / ".env"
_MIGRATIONS_DIR = _REPO_ROOT / "supabase" / "migrations"
_APPLIED_FILE = _SCRIPT_DIR / ".applied_migrations"


def _load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip().strip('"').strip("'")
        env[key.strip()] = val
    return env


_env = _load_env(_ENV_PATH)
SUPABASE_URL = _env.get("NEXT_PUBLIC_SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = _env.get("SUPABASE_SERVICE_ROLE_KEY", "")


# ─── 適用済み管理 ──────────────────────────────────────────────────────────────


def _load_applied() -> dict[str, str]:
    """{ migration_name: sha256 } を返す"""
    if not _APPLIED_FILE.exists():
        return {}
    try:
        return json.loads(_APPLIED_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_applied(applied: dict[str, str]) -> None:
    _APPLIED_FILE.write_text(json.dumps(applied, ensure_ascii=False, indent=2), encoding="utf-8")


# ─── SQL 実行 ─────────────────────────────────────────────────────────────────


def _execute_sql(sql: str) -> dict:
    """
    Supabase REST /rest/v1/rpc/exec_sql でSQLを実行する。
    ※ exec_sql RPC が存在しない環境では直接 pg_query エンドポイントを使用。
    """
    if not SUPABASE_URL or not SERVICE_KEY:
        raise RuntimeError("NEXT_PUBLIC_SUPABASE_URL または SUPABASE_SERVICE_ROLE_KEY が未設定です。")

    headers = {
        "apikey": SERVICE_KEY,
        "Authorization": f"Bearer {SERVICE_KEY}",
        "Content-Type": "application/json",
    }

    # Supabase Management API (v1) の SQL endpoint を試みる
    # URL形式: https://api.supabase.com/v1/projects/{ref}/database/query
    # ただし通常のプロジェクト URL から ref を抽出する
    match = re.search(r"https://([a-z0-9]+)\.supabase\.co", SUPABASE_URL)
    if not match:
        raise RuntimeError(f"Supabase URL から project ref を取得できません: {SUPABASE_URL}")

    project_ref = match.group(1)
    mgmt_url = f"https://api.supabase.com/v1/projects/{project_ref}/database/query"

    resp = httpx.post(
        mgmt_url,
        headers=headers,
        json={"query": sql},
        timeout=60.0,
    )
    if resp.is_error:
        raise RuntimeError(
            f"SQL実行エラー {resp.status_code}: {resp.text[:500]}"
        )
    return resp.json() if resp.text.strip() else {}


# ─── メイン処理 ───────────────────────────────────────────────────────────────


def list_migrations() -> list[Path]:
    """migration ファイルを名前順に返す"""
    return sorted(_MIGRATIONS_DIR.glob("*.sql"))


def print_applied_list() -> None:
    applied = _load_applied()
    all_files = list_migrations()
    print(f"\n{'状態':<6}  {'ファイル名'}")
    print("-" * 50)
    for f in all_files:
        status = "✅ 適用済" if f.name in applied else "⏳ 未適用"
        print(f"{status}  {f.name}")
    print()


def apply_migration(path: Path, *, dry_run: bool = False) -> bool:
    sql = path.read_text(encoding="utf-8")
    sha = hashlib.sha256(sql.encode()).hexdigest()[:16]

    print(f"  → {path.name}  (sha256={sha})")
    if dry_run:
        print("    [DRY RUN] スキップ")
        return True

    try:
        _execute_sql(sql)
        print("    ✅ 完了")
        return True
    except Exception as e:
        print(f"    ❌ 失敗: {e}")
        return False


def main() -> None:
    args = sys.argv[1:]

    if "--list" in args:
        print_applied_list()
        return

    dry_run = "--dry-run" in args
    force = "--force" in args
    target = next((a for a in args if not a.startswith("-")), None)

    applied = _load_applied()
    all_files = list_migrations()

    if target:
        candidates = [f for f in all_files if target in f.name]
        if not candidates:
            print(f"❌ '{target}' に一致するマイグレーションが見つかりません。")
            sys.exit(1)
    else:
        candidates = all_files

    pending = [f for f in candidates if force or f.name not in applied]
    if not pending:
        print("✅ 全てのマイグレーションは適用済みです。")
        return

    print(f"\n適用予定: {len(pending)} 件\n")
    ok_count = 0
    for f in pending:
        sql = f.read_text(encoding="utf-8")
        sha = hashlib.sha256(sql.encode()).hexdigest()[:16]
        success = apply_migration(f, dry_run=dry_run)
        if success and not dry_run:
            applied[f.name] = sha
            _save_applied(applied)
            ok_count += 1
        elif not success:
            print(f"\n⚠️ {f.name} で失敗しました。以降の適用を中止します。")
            break

    print(f"\n完了: {ok_count}/{len(pending)} 件 適用済み\n")


if __name__ == "__main__":
    main()
