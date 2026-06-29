#!/usr/bin/env python3
"""
Import ChatGPT conversation exports into Sigmaris fact memory.

Required environment variables:
  OPENAI_API_KEY
  NEXT_PUBLIC_SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY

Optional environment variables:
  OPENAI_NANO_MODEL or OPENAI_MODEL (defaults to gpt-5.4-nano)
  OLLAMA_BASE_URL (defaults to http://localhost:11434)
  OLLAMA_EMBED_MODEL (defaults to nomic-embed-text)

Usage:
  python3 ~/shift-pilot-ai/scripts/import_chatgpt_history.py \
    --files ~/conversations-*.json \
    --user-id 9d3e94d2-babe-4f91-aabf-70ee8f6fc623 \
    --batch-size 10
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from openai import OpenAI

SYSTEM_PROMPT = """会話から海星さんに関する情報を抽出してください。
以下の3種類を抽出します。
1. 永続的な事実(目標・職業・技術・価値観・好み)
2. 重要な決定(何かを決めた・方針を変えた)
3. 時系列イベント(何かが起きた・変化した)
特に時刻情報を正確に保持してください。
JSONのみ返してください。"""

VALID_FACT_CATEGORIES = {
    "goals",
    "work",
    "health",
    "preference",
    "environment",
    "personality",
}
VALID_EVENT_CATEGORIES = {"project", "technology", "personal", "goal_change"}
SOURCE = "chatgpt_import"
EMBEDDING_DIMENSIONS = 768


@dataclass(frozen=True)
class Conversation:
    conversation_id: str
    title: str
    created_at: str
    updated_at: str
    year_month: str
    messages: list[dict[str, str]]


@dataclass
class ImportStats:
    conversations: int = 0
    facts: int = 0
    decisions: int = 0
    timeline_events: int = 0
    embeddings: int = 0
    errors: int = 0
    oldest: str | None = None
    latest: str | None = None


class SupabaseClient:
    def __init__(self) -> None:
        self.base_url = require_env("NEXT_PUBLIC_SUPABASE_URL").rstrip("/")
        self.service_key = require_env("SUPABASE_SERVICE_ROLE_KEY")
        self.client = httpx.Client(timeout=httpx.Timeout(45.0))

    def close(self) -> None:
        self.client.close()

    def headers(self, *, prefer: str | None = None) -> dict[str, str]:
        headers = {
            "apikey": self.service_key,
            "Authorization": f"Bearer {self.service_key}",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        return headers

    def select(self, table: str, params: dict[str, str]) -> list[dict[str, Any]]:
        response = self.client.get(
            f"{self.base_url}/rest/v1/{table}",
            headers=self.headers(),
            params=params,
        )
        raise_for_status(response)
        data = response.json()
        return data if isinstance(data, list) else []

    def insert_one(self, table: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.client.post(
            f"{self.base_url}/rest/v1/{table}",
            headers=self.headers(prefer="return=representation"),
            json=payload,
        )
        raise_for_status(response)
        rows = response.json()
        if not isinstance(rows, list) or not rows:
            raise RuntimeError(f"Supabase insert returned no row for {table}.")
        return rows[0]

    def update(self, table: str, payload: dict[str, Any], params: dict[str, str]) -> None:
        response = self.client.patch(
            f"{self.base_url}/rest/v1/{table}",
            headers=self.headers(prefer="return=minimal"),
            params=params,
            json=payload,
        )
        raise_for_status(response)

    def rpc(self, function_name: str, payload: dict[str, Any]) -> Any:
        response = self.client.post(
            f"{self.base_url}/rest/v1/rpc/{function_name}",
            headers=self.headers(),
            json=payload,
        )
        raise_for_status(response)
        return response.json()


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is not set.")
    return value


def load_env_files() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    for path in [repo_root / "backend" / ".env", repo_root / "frontend" / ".env.local", repo_root / ".env"]:
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def raise_for_status(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = response.text.strip()
        message = f"{response.status_code} {response.reason_phrase}: {response.request.method} {response.request.url}"
        if detail:
            message = f"{message}: {detail[:1000]}"
        raise RuntimeError(message) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import ChatGPT history into Sigmaris memory.")
    parser.add_argument("--files", nargs="+", required=True, help="JSON export files or glob patterns.")
    parser.add_argument("--user-id", required=True, help="Supabase auth.users id to own imported memories.")
    parser.add_argument("--batch-size", type=int, default=10, help="Progress/ETA batch size.")
    parser.add_argument("--model", default=os.environ.get("OPENAI_NANO_MODEL") or os.environ.get("OPENAI_MODEL") or "gpt-5.4-nano")
    parser.add_argument("--max-conversation-chars", type=int, default=24000)
    parser.add_argument("--match-threshold", type=float, default=0.78)
    parser.add_argument("--dry-run", action="store_true", help="Extract and report without writing to Supabase.")
    parser.add_argument("--limit", type=int, default=None, help="Optional conversation limit for test runs.")
    return parser.parse_args()


def expand_files(patterns: list[str]) -> list[Path]:
    paths: list[Path] = []
    for pattern in patterns:
        expanded = glob.glob(os.path.expanduser(pattern))
        if expanded:
            paths.extend(Path(p) for p in expanded)
        else:
            paths.append(Path(os.path.expanduser(pattern)))
    unique = sorted({p.resolve() for p in paths})
    missing = [str(p) for p in unique if not p.exists()]
    if missing:
        raise FileNotFoundError("Missing input file(s): " + ", ".join(missing))
    return unique


def unix_to_iso(value: Any) -> str:
    if value is None:
        return datetime.now(UTC).isoformat()
    ts = float(value)
    if ts > 10_000_000_000:
        ts = ts / 1000.0
    return datetime.fromtimestamp(ts, UTC).isoformat()


def year_month(iso_value: str) -> str:
    return iso_value[:7]


def load_conversations(path: Path) -> list[Conversation]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_conversations = payload if isinstance(payload, list) else payload.get("conversations", [])
    conversations: list[Conversation] = []
    for index, raw in enumerate(raw_conversations):
        if not isinstance(raw, dict):
            continue
        conversation_id = str(raw.get("id") or raw.get("conversation_id") or f"{path.stem}-{index}")
        title = str(raw.get("title") or "Untitled")
        created_at = unix_to_iso(raw.get("create_time") or raw.get("created_at") or raw.get("update_time"))
        updated_at = unix_to_iso(raw.get("update_time") or raw.get("updated_at") or raw.get("create_time"))
        messages = extract_messages(raw)
        conversations.append(
            Conversation(
                conversation_id=conversation_id,
                title=title,
                created_at=created_at,
                updated_at=updated_at,
                year_month=year_month(created_at),
                messages=messages,
            )
        )
    return conversations


def extract_messages(raw: dict[str, Any]) -> list[dict[str, str]]:
    mapping = raw.get("mapping")
    messages: list[tuple[float, dict[str, str]]] = []
    if isinstance(mapping, dict):
        for node in mapping.values():
            message = node.get("message") if isinstance(node, dict) else None
            parsed = parse_message(message)
            if parsed:
                ts = float(message.get("create_time") or 0.0)
                messages.append((ts, parsed))
    elif isinstance(raw.get("messages"), list):
        for item in raw["messages"]:
            parsed = parse_message(item)
            if parsed:
                ts = float(item.get("create_time") or item.get("created_at") or 0.0)
                messages.append((ts, parsed))

    messages.sort(key=lambda item: item[0])
    return [item for _, item in messages]


def parse_message(message: Any) -> dict[str, str] | None:
    if not isinstance(message, dict):
        return None
    author = message.get("author") if isinstance(message.get("author"), dict) else {}
    role = str(author.get("role") or message.get("role") or "").strip()
    if role not in {"user", "assistant", "system", "tool"}:
        return None
    content = message.get("content")
    text = content_to_text(content)
    if not text.strip():
        return None
    return {"role": role, "content": text.strip()}


def content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, dict):
        return ""
    parts = content.get("parts")
    if isinstance(parts, list):
        texts: list[str] = []
        for part in parts:
            if isinstance(part, str):
                texts.append(part)
            elif isinstance(part, dict):
                value = part.get("text") or part.get("content") or part.get("name")
                if isinstance(value, str):
                    texts.append(value)
        return "\n".join(texts)
    text = content.get("text")
    return text if isinstance(text, str) else ""


def format_conversation(conversation: Conversation, max_chars: int) -> str:
    header = {
        "conversation_id": conversation.conversation_id,
        "title": conversation.title,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
        "year_month": conversation.year_month,
    }
    lines = ["# metadata", json.dumps(header, ensure_ascii=False), "# messages"]
    for message in conversation.messages:
        content = message["content"].replace("\x00", "").strip()
        if content:
            lines.append(f"{message['role']}: {content}")
    text = "\n\n".join(lines)
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    return text[:half] + "\n\n[... middle omitted for length ...]\n\n" + text[-half:]


def extract_memory(client: OpenAI, model: str, conversation: Conversation, max_chars: int) -> dict[str, Any]:
    user_prompt = "\n\n".join(
        [
            "以下のChatGPT会話ログから、指定スキーマで抽出してください。",
            "categoryは facts では goals|work|health|preference|environment|personality のみを使ってください。",
            "timeline_events.categoryは project|technology|personal|goal_change のみを使ってください。",
            "observed_at/decided_at/occurred_at は会話メタデータの created_at を基本にし、会話内でより具体的な時刻が明示されている場合だけその時刻を使ってください。",
            "古い情報は stale と決めつけず、当時の状態として temporal_note に残してください。",
            "返すJSONスキーマ:",
            json.dumps(
                {
                    "facts": [
                        {
                            "category": "goals|work|health|preference|environment|personality",
                            "key": "unique_key",
                            "value": "fact text",
                            "confidence": 0.0,
                            "observed_at": conversation.created_at,
                            "is_stale": False,
                            "temporal_note": "state at that time",
                        }
                    ],
                    "decisions": [
                        {
                            "title": "decision",
                            "decided_at": conversation.created_at,
                            "context": "why it was decided",
                        }
                    ],
                    "timeline_events": [
                        {
                            "event": "what happened",
                            "occurred_at": conversation.created_at,
                            "category": "project|technology|personal|goal_change",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            "会話ログ:",
            format_conversation(conversation, max_chars),
        ]
    )
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or "{}"
    parsed = json.loads(content)
    return parsed if isinstance(parsed, dict) else {}


def normalize_extraction(data: dict[str, Any], conversation: Conversation) -> dict[str, list[dict[str, Any]]]:
    facts = [normalize_fact(item, conversation) for item in as_list(data.get("facts"))]
    decisions = [normalize_decision(item, conversation) for item in as_list(data.get("decisions"))]
    events = [normalize_event(item, conversation) for item in as_list(data.get("timeline_events"))]
    return {
        "facts": [item for item in facts if item],
        "decisions": [item for item in decisions if item],
        "timeline_events": [item for item in events if item],
    }


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def normalize_fact(item: Any, conversation: Conversation) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    category = str(item.get("category") or "").strip()
    if category == "preferences":
        category = "preference"
    if category not in VALID_FACT_CATEGORIES:
        return None
    key = clean_key(item.get("key") or category)
    value = str(item.get("value") or "").strip()
    if not value:
        return None
    observed_at = normalize_iso(item.get("observed_at"), conversation.created_at)
    confidence = clamp_float(item.get("confidence"), 0.5)
    return {
        "category": category,
        "key": key,
        "value": value,
        "confidence": confidence,
        "observed_at": observed_at,
        "is_stale": bool(item.get("is_stale", False)),
        "temporal_note": str(item.get("temporal_note") or "").strip(),
    }


def normalize_decision(item: Any, conversation: Conversation) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    title = str(item.get("title") or "").strip()
    if not title:
        return None
    return {
        "title": title,
        "decided_at": normalize_iso(item.get("decided_at"), conversation.created_at),
        "context": str(item.get("context") or "").strip(),
    }


def normalize_event(item: Any, conversation: Conversation) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    event = str(item.get("event") or "").strip()
    category = str(item.get("category") or "personal").strip()
    if not event:
        return None
    if category not in VALID_EVENT_CATEGORIES:
        category = "personal"
    return {
        "event": event,
        "occurred_at": normalize_iso(item.get("occurred_at"), conversation.created_at),
        "category": category,
    }


def normalize_iso(value: Any, fallback: str) -> str:
    if value is None:
        return fallback
    if isinstance(value, (int, float)):
        return unix_to_iso(value)
    text = str(value).strip()
    if not text:
        return fallback
    try:
        normalized = text.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).astimezone(UTC).isoformat()
    except ValueError:
        return fallback


def clean_key(value: Any) -> str:
    raw = str(value or "").strip().lower()
    raw = re.sub(r"\s+", "_", raw)
    raw = re.sub(r"[^a-z0-9_\-\u3040-\u30ff\u3400-\u9fff]", "_", raw)
    raw = re.sub(r"_+", "_", raw).strip("_")
    return raw[:80] or "memory"


def temporal_key(base_key: str, observed_at: str, conversation_id: str, value: str) -> str:
    day = observed_at[:10]
    digest = hashlib.sha1(f"{conversation_id}:{base_key}:{value}".encode("utf-8")).hexdigest()[:10]
    return f"{base_key}__{day}__{digest}"


def clamp_float(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(0.0, min(1.0, number))


def confidence_with_decay(confidence: float, observed_at: str) -> float:
    observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00")).astimezone(UTC)
    age_days = (datetime.now(UTC) - observed).days
    if age_days <= 92:
        multiplier = 1.0
    elif age_days <= 366:
        multiplier = 0.8
    else:
        multiplier = 0.6
    return round(clamp_float(confidence * multiplier, confidence), 3)


def vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in values) + "]"


def fact_embedding_text(item: dict[str, Any]) -> str:
    return "\n".join(
        str(part).strip()
        for part in [item.get("category"), item.get("key"), item.get("value"), item.get("notes")]
        if str(part or "").strip()
    )


def generate_embedding(text: str) -> list[float]:
    if not text.strip():
        return []
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    model = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")
    with httpx.Client(timeout=httpx.Timeout(30.0)) as client:
        response = client.post(
            f"{base_url}/api/embeddings",
            json={"model": model, "prompt": text},
        )
    raise_for_status(response)
    data = response.json()
    embedding = data.get("embedding")
    if not isinstance(embedding, list):
        raise RuntimeError("Ollama embedding response did not include embedding.")
    values = [float(value) for value in embedding]
    if len(values) != EMBEDDING_DIMENSIONS:
        raise RuntimeError(f"Embedding dimension mismatch: expected {EMBEDDING_DIMENSIONS}, got {len(values)}.")
    return values


def search_relevant_memories(
    db: SupabaseClient,
    *,
    query: str,
    user_id: str,
    threshold: float,
    limit: int = 5,
) -> list[dict[str, Any]]:
    try:
        embedding = generate_embedding(query)
        if not embedding:
            return []
        result = db.rpc(
            "search_fact_memory",
            {
                "query_embedding": vector_literal(embedding),
                "user_id_param": user_id,
                "match_threshold": threshold,
                "match_count": limit,
            },
        )
        rows = result if isinstance(result, list) else []
        rows.sort(key=lambda item: float(item.get("similarity") or 0.0), reverse=True)
        return rows
    except Exception as exc:
        print(f"  warning: memory search skipped ({exc})", file=sys.stderr)
        return []


def notes_for(conversation: Conversation, temporal_note: str, original_key: str) -> str:
    payload = {
        "conversation_id": conversation.conversation_id,
        "title": conversation.title,
        "conversation_created_at": conversation.created_at,
        "conversation_updated_at": conversation.updated_at,
        "year_month": conversation.year_month,
        "original_key": original_key,
        "temporal_note": temporal_note,
    }
    return json.dumps(payload, ensure_ascii=False)


def save_fact(
    db: SupabaseClient,
    *,
    user_id: str,
    conversation: Conversation,
    fact: dict[str, Any],
    match_threshold: float,
) -> str:
    original_key = fact["key"]
    key = temporal_key(original_key, fact["observed_at"], conversation.conversation_id, fact["value"])
    confidence = confidence_with_decay(float(fact["confidence"]), fact["observed_at"])
    notes = notes_for(conversation, fact.get("temporal_note", ""), original_key)
    row_payload = {
        "user_id": user_id,
        "category": fact["category"],
        "key": key,
        "value": fact["value"],
        "confidence": confidence,
        "source": SOURCE,
        "notes": notes,
        "created_at": fact["observed_at"],
        "is_stale": bool(fact.get("is_stale", False)),
    }

    existing = search_relevant_memories(
        db,
        query=f"{fact['category']}\n{original_key}\n{fact['value']}",
        user_id=user_id,
        threshold=match_threshold,
    )
    inserted = insert_fact_idempotent(db, row_payload)
    if inserted.get("_existing"):
        return inserted["id"]

    old_value = None
    if existing:
        best = existing[0]
        if str(best.get("value") or "").strip() != fact["value"].strip():
            old_value = best.get("value")

    db.insert_one(
        "user_fact_history",
        {
            "user_id": user_id,
            "fact_item_id": inserted["id"],
            "old_value": old_value,
            "new_value": fact["value"],
            "changed_by": SOURCE,
            "reason": fact.get("temporal_note") or f"Imported from ChatGPT conversation: {conversation.title}",
            "changed_at": fact["observed_at"],
            "created_at": fact["observed_at"],
        },
    )
    return inserted["id"]


def insert_fact_idempotent(db: SupabaseClient, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        row = db.insert_one("user_fact_items", payload)
        row["_existing"] = False
        return row
    except RuntimeError as exc:
        if "duplicate key" not in str(exc) and "23505" not in str(exc):
            raise
        rows = db.select(
            "user_fact_items",
            {
                "select": "id,category,key,value",
                "user_id": f"eq.{payload['user_id']}",
                "category": f"eq.{payload['category']}",
                "key": f"eq.{payload['key']}",
                "limit": "1",
            },
        )
        if not rows:
            raise
        row = rows[0]
        row["_existing"] = True
        return row


def save_decision(db: SupabaseClient, *, decision: dict[str, Any], conversation: Conversation) -> None:
    db.insert_one(
        "sigmaris_decision_log",
        {
            "decision_type": "action",
            "title": decision["title"],
            "reason": decision.get("context"),
            "context": decision.get("context"),
            "created_at": decision["decided_at"],
            "decided_at": decision["decided_at"],
            "internal_state_snapshot": {
                "source": SOURCE,
                "conversation_id": conversation.conversation_id,
                "conversation_title": conversation.title,
            },
        },
    )


def save_timeline_event(
    db: SupabaseClient,
    *,
    user_id: str,
    event: dict[str, Any],
    conversation: Conversation,
    match_threshold: float,
) -> str:
    fact = {
        "category": "timeline",
        "key": clean_key(event["category"]),
        "value": event["event"],
        "confidence": 0.9,
        "observed_at": event["occurred_at"],
        "is_stale": False,
        "temporal_note": f"timeline_event:{event['category']}",
    }
    return save_fact(
        db,
        user_id=user_id,
        conversation=conversation,
        fact=fact,
        match_threshold=match_threshold,
    )


def embed_fact(db: SupabaseClient, fact_id: str) -> bool:
    rows = db.select(
        "user_fact_items",
        {
            "select": "id,category,key,value,notes",
            "id": f"eq.{fact_id}",
            "limit": "1",
        },
    )
    if not rows:
        return False
    embedding = generate_embedding(fact_embedding_text(rows[0]))
    db.update("user_fact_items", {"embedding": vector_literal(embedding)}, {"id": f"eq.{fact_id}"})
    return True


def update_date_bounds(stats: ImportStats, conversation: Conversation) -> None:
    if stats.oldest is None or conversation.created_at < stats.oldest:
        stats.oldest = conversation.created_at
    if stats.latest is None or conversation.updated_at > stats.latest:
        stats.latest = conversation.updated_at


def print_eta(start: float, done: int, total: int) -> None:
    if done <= 0:
        return
    elapsed = time.monotonic() - start
    remaining = max(total - done, 0)
    eta_seconds = elapsed / done * remaining
    eta = datetime.fromtimestamp(time.time() + eta_seconds).astimezone().isoformat(timespec="seconds")
    print(f"  progress: {done}/{total} conversations, estimated finish: {eta}")


def main() -> int:
    load_env_files()
    args = parse_args()
    paths = expand_files(args.files)
    openai_client = OpenAI(api_key=require_env("OPENAI_API_KEY"))
    db = None if args.dry_run else SupabaseClient()
    stats = ImportStats()
    start = time.monotonic()

    try:
        all_conversations_by_file = [(path, load_conversations(path)) for path in paths]
        total = sum(len(items) for _, items in all_conversations_by_file)
        if args.limit is not None:
            total = min(total, args.limit)
        print(f"Input files: {len(paths)}")
        print(f"Conversations to process: {total}")

        processed = 0
        for path, conversations in all_conversations_by_file:
            print(f"\nFile: {path}")
            for file_index, conversation in enumerate(conversations, start=1):
                if args.limit is not None and processed >= args.limit:
                    break
                processed += 1
                stats.conversations += 1
                update_date_bounds(stats, conversation)
                print(
                    f"[{processed}/{total}] conversation {file_index}/{len(conversations)} "
                    f"{conversation.conversation_id} {conversation.created_at} {conversation.title[:60]}"
                )
                try:
                    extracted = extract_memory(openai_client, args.model, conversation, args.max_conversation_chars)
                    normalized = normalize_extraction(extracted, conversation)
                    fact_count = len(normalized["facts"])
                    decision_count = len(normalized["decisions"])
                    event_count = len(normalized["timeline_events"])
                    print(f"  extracted: facts={fact_count}, decisions={decision_count}, events={event_count}")

                    if not args.dry_run and db is not None:
                        fact_ids: list[str] = []
                        for fact in normalized["facts"]:
                            fact_ids.append(
                                save_fact(
                                    db,
                                    user_id=args.user_id,
                                    conversation=conversation,
                                    fact=fact,
                                    match_threshold=args.match_threshold,
                                )
                            )
                        for decision in normalized["decisions"]:
                            save_decision(db, decision=decision, conversation=conversation)
                        for event in normalized["timeline_events"]:
                            fact_ids.append(
                                save_timeline_event(
                                    db,
                                    user_id=args.user_id,
                                    event=event,
                                    conversation=conversation,
                                    match_threshold=args.match_threshold,
                                )
                            )
                        for fact_id in fact_ids:
                            try:
                                if embed_fact(db, fact_id):
                                    stats.embeddings += 1
                            except Exception as exc:
                                stats.errors += 1
                                print(f"  warning: embedding failed for {fact_id}: {exc}", file=sys.stderr)

                    stats.facts += fact_count
                    stats.decisions += decision_count
                    stats.timeline_events += event_count
                except Exception as exc:
                    stats.errors += 1
                    print(f"  error: {exc}", file=sys.stderr)

                if processed % max(args.batch_size, 1) == 0 or processed == total:
                    print_eta(start, processed, total)

            if args.limit is not None and processed >= args.limit:
                break

        print("\nTimeline summary")
        print(f"  oldest conversation: {stats.oldest or 'n/a'}")
        print(f"  latest conversation : {stats.latest or 'n/a'}")
        print("Import summary")
        print(f"  conversations: {stats.conversations}")
        print(f"  facts: {stats.facts}")
        print(f"  decisions: {stats.decisions}")
        print(f"  timeline events: {stats.timeline_events}")
        print(f"  embeddings: {stats.embeddings}")
        print(f"  errors: {stats.errors}")
        return 1 if stats.errors else 0
    finally:
        if db is not None:
            db.close()


if __name__ == "__main__":
    raise SystemExit(main())
