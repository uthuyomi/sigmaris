from __future__ import annotations

# 役割: アプリ内チャットデータの保存と取得を扱う。

import logging
from datetime import UTC, datetime
from typing import Any

from app.services.app_profile_data import get_profile_context
from app.services.supabase_rest import rest_delete, rest_insert, rest_select, rest_update

logger = logging.getLogger(__name__)

DEFAULT_THREAD_TITLE = "新しいチャット"
LEGACY_DEFAULT_THREAD_TITLE = "New chat"
THREAD_TITLE_MAX_LENGTH = 20


class ThreadVersionConflictError(RuntimeError):
    """Raised by replace_chat_messages() when expected_version no longer
    matches chat_threads.version — another writer already replaced this
    thread's messages first. chat_messages is left untouched when this is
    raised (the version check happens before any delete/insert)."""


def compact_parts(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compacted = []
    for part in parts:
        if part.get("type") == "file":
            next_part = dict(part)
            next_part["url"] = ""
            compacted.append(next_part)
        else:
            compacted.append(part)
    return compacted


def derive_thread_title(messages: list[dict[str, Any]]) -> str:
    for message in messages:
        if message.get("role") != "user":
            continue
        for part in message.get("parts", []):
            if part.get("type") == "text" and str(part.get("text", "")).strip():
                return str(part["text"]).strip()[:THREAD_TITLE_MAX_LENGTH]
        for part in message.get("parts", []):
            if part.get("type") == "file" and part.get("filename"):
                return str(part["filename"])[:THREAD_TITLE_MAX_LENGTH]
    return DEFAULT_THREAD_TITLE


async def get_chat_thread(jwt: str, thread_id: str) -> dict[str, Any] | None:
    return await rest_select(
        jwt,
        "chat_threads",
        {
            "select": "id,title,created_at,updated_at",
            "id": f"eq.{thread_id}",
        },
        single=True,
    )


async def get_chat_thread_version(jwt: str, thread_id: str) -> int | None:
    """Best-effort fetch of chat_threads.version for optimistic-concurrency
    control (Phase A4). Deliberately never raises: until the version column
    migration (202607050027) is applied, this query fails (unknown column)
    and the function returns None rather than propagating that failure —
    every caller already treats None as "skip CAS, use legacy unconditional
    overwrite", so the feature safely no-ops pre-migration and activates on
    its own afterward with no code redeploy needed. Kept as a separate
    query (not folded into get_chat_thread's default select) specifically
    so a missing column can never break the many existing call sites that
    just need id/title/timestamps."""
    try:
        row = await rest_select(
            jwt,
            "chat_threads",
            {"select": "version", "id": f"eq.{thread_id}"},
            single=True,
        )
        version = row.get("version") if row else None
        return int(version) if isinstance(version, (int, float)) else None
    except Exception:
        logger.warning(
            "app_chat_data: could not read chat_threads.version for id=%s "
            "(version migration not applied yet?)",
            thread_id,
        )
        return None


async def list_chat_threads(jwt: str) -> list[dict[str, Any]]:
    context = await get_profile_context(jwt)
    user_id = context["userId"]
    result = await rest_select(
        jwt,
        "chat_threads",
        {
            "select": "id,title,created_at,updated_at",
            "user_id": f"eq.{user_id}",
            "order": "updated_at.desc",
        },
    )
    return result if isinstance(result, list) else []


async def create_chat_thread(
    jwt: str,
    *,
    thread_id: str | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    context = await get_profile_context(jwt)
    user_id = context["userId"]
    payload: dict[str, Any] = {
        "user_id": user_id,
        "title": title or DEFAULT_THREAD_TITLE,
    }
    if thread_id:
        payload["id"] = thread_id
    return await rest_insert(jwt, "chat_threads", payload, single=True)


async def rename_chat_thread(jwt: str, *, thread_id: str, title: str) -> None:
    context = await get_profile_context(jwt)
    user_id = context["userId"]
    await rest_update(
        jwt,
        "chat_threads",
        {"title": title},
        {"id": f"eq.{thread_id}", "user_id": f"eq.{user_id}"},
    )


async def delete_chat_thread(jwt: str, *, thread_id: str) -> None:
    context = await get_profile_context(jwt)
    user_id = context["userId"]
    await rest_delete(
        jwt,
        "chat_threads",
        {"id": f"eq.{thread_id}", "user_id": f"eq.{user_id}"},
    )


async def list_chat_messages(jwt: str, *, thread_id: str) -> list[dict[str, Any]]:
    context = await get_profile_context(jwt)
    user_id = context["userId"]
    result = await rest_select(
        jwt,
        "chat_messages",
        {
            "select": "id,role,parts,metadata",
            "user_id": f"eq.{user_id}",
            "thread_id": f"eq.{thread_id}",
            "order": "message_order.asc",
        },
    )
    return result if isinstance(result, list) else []


async def get_earliest_message_at(jwt: str) -> str | None:
    """Returns the created_at of this user's very first chat_messages row
    (across all threads), or None if they have never sent a message yet.

    Temporal Layer Step 3 (docs/sigmaris/temporal_layer_report.md): used as
    the "relationship origin date" for Sigmaris's elapsed-days awareness —
    the first-ever exchange is the only data-driven, unambiguous candidate
    in this schema (sigmaris_self_model has no project-start field; its own
    created_at only reflects when that table/feature was introduced, not
    when 海星さん and Sigmaris actually started talking).
    """
    context = await get_profile_context(jwt)
    user_id = context["userId"]
    result = await rest_select(
        jwt,
        "chat_messages",
        {
            "select": "created_at",
            "user_id": f"eq.{user_id}",
            "order": "created_at.asc",
            "limit": "1",
        },
    )
    rows = result if isinstance(result, list) else []
    return rows[0]["created_at"] if rows else None


async def get_recent_messages_across_threads(
    jwt: str,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Return the caller's most recent `limit` chat_messages rows across ALL
    threads (not scoped to one thread_id), in chronological order (oldest
    first). Distinct from list_chat_messages(), which is thread-scoped.

    Used to build a cross-thread "recent log window" for session continuity
    (Phase A1) — separate from the per-thread history used to render a
    single thread's UI.
    """
    context = await get_profile_context(jwt)
    user_id = context["userId"]
    result = await rest_select(
        jwt,
        "chat_messages",
        {
            "select": "id,thread_id,role,parts,metadata,created_at",
            "user_id": f"eq.{user_id}",
            "order": "created_at.desc",
            "limit": str(limit),
        },
    )
    rows = result if isinstance(result, list) else []
    rows.reverse()
    return rows


async def replace_chat_messages(
    jwt: str,
    *,
    thread_id: str,
    messages: list[dict[str, Any]],
    expected_version: int | None = None,
) -> int | None:
    """Full delete-then-reinsert of a thread's messages (unchanged from
    before Phase A4 — see phase_a4_report.md for why a diff-append rewrite
    was not pursued here).

    When `expected_version` is given, this first does an atomic
    compare-and-swap on chat_threads.version: the UPDATE only matches (and
    bumps the version) if the row's current version still equals
    expected_version. If another writer already replaced this thread's
    messages since expected_version was read, zero rows match and
    ThreadVersionConflictError is raised *before* chat_messages is touched
    — the loser's write never reaches the message rows, so the winner's
    data is never silently destroyed.

    When `expected_version` is None (caller didn't capture one, or
    get_chat_thread_version() couldn't read the column because the Phase A4
    migration isn't applied yet), the `version` column is never referenced
    at all — this behaves byte-for-byte like the pre-A4 unconditional
    overwrite. The CAS gate is entirely opt-in so this function is safe to
    deploy before the migration is applied: nothing breaks, optimistic
    concurrency control just isn't active yet.

    Returns the new version number, or None if no version tracking was
    performed (thread row missing, or expected_version was None).
    """
    context = await get_profile_context(jwt)
    user_id = context["userId"]

    current_thread = await get_chat_thread(jwt, thread_id)
    if current_thread is None:
        # Matches pre-A4 behavior: proceed with the message write even if
        # the thread row is (unexpectedly) missing, just skip title/version.
        await rest_delete(
            jwt, "chat_messages", {"user_id": f"eq.{user_id}", "thread_id": f"eq.{thread_id}"}
        )
        if messages:
            await rest_insert(jwt, "chat_messages", _message_insert_payload(thread_id, user_id, messages))
        return None

    current_title = current_thread.get("title")
    next_title = (
        derive_thread_title(messages)
        if current_title in {DEFAULT_THREAD_TITLE, LEGACY_DEFAULT_THREAD_TITLE}
        else current_title
    )

    update_payload: dict[str, Any] = {
        "title": next_title,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    update_params = {"id": f"eq.{thread_id}", "user_id": f"eq.{user_id}"}
    if expected_version is not None:
        update_payload["version"] = expected_version + 1
        update_params["version"] = f"eq.{expected_version}"

    updated_rows = await rest_update(jwt, "chat_threads", update_payload, update_params)
    if expected_version is not None and not updated_rows:
        raise ThreadVersionConflictError(
            f"chat_thread {thread_id} was modified concurrently "
            f"(expected version {expected_version})."
        )
    new_version = updated_rows[0].get("version") if updated_rows else None

    # Only reached once the version gate above has passed (or was skipped),
    # so a losing concurrent writer never deletes/reinserts messages at all.
    await rest_delete(
        jwt, "chat_messages", {"user_id": f"eq.{user_id}", "thread_id": f"eq.{thread_id}"}
    )
    if messages:
        await rest_insert(jwt, "chat_messages", _message_insert_payload(thread_id, user_id, messages))

    return new_version


def _message_insert_payload(
    thread_id: str, user_id: str, messages: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    return [
        {
            "thread_id": thread_id,
            "user_id": user_id,
            "message_order": index,
            "role": message.get("role"),
            "parts": compact_parts(message.get("parts", [])),
            "metadata": message.get("metadata", {}),
        }
        for index, message in enumerate(messages)
    ]
