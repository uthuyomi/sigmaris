from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

from app.config import settings
from app.services.user_fact_data import get_fact_items, upsert_fact_item

logger = logging.getLogger(__name__)

_FIT_BASE = "https://www.googleapis.com/fitness/v1/users/me"

# Google Fit data source / data type name mappings
_DATA_TYPES = {
    "steps": "derived:com.google.step_count.delta:com.google.android.gms:estimated_steps",
    "heart_rate": "derived:com.google.heart_rate.bpm:com.google.android.gms:resting_heart_rate<-merge_heart_rate_summary",
    "calories": "derived:com.google.calories.expended:com.google.android.gms:merge_calories_expended",
    "sleep": "derived:com.google.sleep.segment:com.google.android.gms:merged",
}

# Sleep stage values from Google Fit
_SLEEP_STAGES = {1: "awake", 2: "sleep", 3: "out_of_bed", 4: "light", 5: "deep", 6: "rem"}
_SLEEP_COUNTING = {2, 4, 5, 6}  # stages counted as "asleep"


@dataclass
class DailyHealthSummary:
    date: str
    steps: int | None = None
    resting_heart_rate: float | None = None
    avg_heart_rate: float | None = None
    calories_kcal: float | None = None
    sleep_minutes: int | None = None
    sleep_quality: str | None = None
    errors: list[str] = field(default_factory=list)


class HealthDataCollector:
    """Fetches daily health summaries from Google Fit API and stores them in fact memory."""

    # ─── fetch ────────────────────────────────────────────────────────────────

    async def fetch_daily_summary(
        self,
        target_date: date,
        google_access_token: str,
    ) -> DailyHealthSummary:
        summary = DailyHealthSummary(date=target_date.isoformat())

        start_ms = int(datetime(
            target_date.year, target_date.month, target_date.day,
            0, 0, 0, tzinfo=timezone.utc,
        ).timestamp() * 1000)
        end_ms = start_ms + 86_400_000  # +24h

        headers = {"Authorization": f"Bearer {google_access_token}"}

        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
            summary.steps = await self._fetch_steps(client, headers, start_ms, end_ms)
            hr_resting, hr_avg = await self._fetch_heart_rate(client, headers, start_ms, end_ms)
            summary.resting_heart_rate = hr_resting
            summary.avg_heart_rate = hr_avg
            summary.calories_kcal = await self._fetch_calories(client, headers, start_ms, end_ms)
            sleep_min, sleep_q = await self._fetch_sleep(client, headers, start_ms, end_ms)
            summary.sleep_minutes = sleep_min
            summary.sleep_quality = sleep_q

        return summary

    async def _fetch_steps(
        self,
        client: httpx.AsyncClient,
        headers: dict,
        start_ms: int,
        end_ms: int,
    ) -> int | None:
        r = await client.get(
            f"{_FIT_BASE}/dataset:aggregate",
            headers=headers,
            params=_agg_params("com.google.step_count.delta", start_ms, end_ms),
        )
        if r.is_error:
            logger.warning("health: steps fetch failed %s", r.status_code)
            return None
        buckets = r.json().get("bucket", [])
        total = 0
        for bucket in buckets:
            for ds in bucket.get("dataset", []):
                for pt in ds.get("point", []):
                    for val in pt.get("value", []):
                        total += val.get("intVal", 0)
        return total if total > 0 else None

    async def _fetch_heart_rate(
        self,
        client: httpx.AsyncClient,
        headers: dict,
        start_ms: int,
        end_ms: int,
    ) -> tuple[float | None, float | None]:
        r = await client.get(
            f"{_FIT_BASE}/dataset:aggregate",
            headers=headers,
            params=_agg_params("com.google.heart_rate.bpm", start_ms, end_ms),
        )
        if r.is_error:
            logger.warning("health: heart_rate fetch failed %s", r.status_code)
            return None, None

        values: list[float] = []
        for bucket in r.json().get("bucket", []):
            for ds in bucket.get("dataset", []):
                for pt in ds.get("point", []):
                    for val in pt.get("value", []):
                        fp = val.get("fpVal")
                        if fp is not None:
                            values.append(float(fp))

        if not values:
            return None, None
        avg = round(sum(values) / len(values), 1)
        resting = round(min(values), 1)
        return resting, avg

    async def _fetch_calories(
        self,
        client: httpx.AsyncClient,
        headers: dict,
        start_ms: int,
        end_ms: int,
    ) -> float | None:
        r = await client.get(
            f"{_FIT_BASE}/dataset:aggregate",
            headers=headers,
            params=_agg_params("com.google.calories.expended", start_ms, end_ms),
        )
        if r.is_error:
            logger.warning("health: calories fetch failed %s", r.status_code)
            return None
        total = 0.0
        for bucket in r.json().get("bucket", []):
            for ds in bucket.get("dataset", []):
                for pt in ds.get("point", []):
                    for val in pt.get("value", []):
                        fp = val.get("fpVal")
                        if fp is not None:
                            total += float(fp)
        return round(total, 1) if total > 0 else None

    async def _fetch_sleep(
        self,
        client: httpx.AsyncClient,
        headers: dict,
        start_ms: int,
        end_ms: int,
    ) -> tuple[int | None, str | None]:
        r = await client.get(
            f"{_FIT_BASE}/dataset:aggregate",
            headers=headers,
            params=_agg_params("com.google.sleep.segment", start_ms, end_ms),
        )
        if r.is_error:
            logger.warning("health: sleep fetch failed %s", r.status_code)
            return None, None

        sleep_ms = 0
        deep_ms = 0
        rem_ms = 0
        for bucket in r.json().get("bucket", []):
            for ds in bucket.get("dataset", []):
                for pt in ds.get("point", []):
                    stage = (pt.get("value") or [{}])[0].get("intVal", 0)
                    if stage not in _SLEEP_COUNTING:
                        continue
                    start_ns = int(pt.get("startTimeNanos", 0))
                    end_ns = int(pt.get("endTimeNanos", 0))
                    duration_ms = (end_ns - start_ns) // 1_000_000
                    sleep_ms += duration_ms
                    if stage == 5:
                        deep_ms += duration_ms
                    elif stage == 6:
                        rem_ms += duration_ms

        if sleep_ms == 0:
            return None, None

        sleep_min = sleep_ms // 60_000
        total = sleep_ms
        deep_ratio = deep_ms / total if total else 0
        rem_ratio = rem_ms / total if total else 0
        if deep_ratio >= 0.20 and rem_ratio >= 0.20:
            quality = "good"
        elif deep_ratio >= 0.12 or rem_ratio >= 0.12:
            quality = "fair"
        else:
            quality = "poor"

        return sleep_min, quality

    # ─── store ────────────────────────────────────────────────────────────────

    async def store_to_fact_memory(self, jwt: str, summary: DailyHealthSummary) -> list[dict]:
        """Store daily health summary to fact memory.

        Sleep minutes + quality are combined into a single human-readable entry
        (e.g. 'sleep_2026-01-01' = '7.5時間 品質:good') to keep the memory
        layer easy to read. Other metrics are stored individually.
        The DB trigger automatically sets privacy_level='private' and
        importance_score=0.9 for category='health'.
        """
        stored: list[dict] = []

        # Build individual metric entries
        scalar_items: list[tuple[str, str | None]] = [
            ("steps", str(summary.steps) if summary.steps is not None else None),
            ("resting_heart_rate", str(summary.resting_heart_rate) if summary.resting_heart_rate is not None else None),
            ("avg_heart_rate", str(summary.avg_heart_rate) if summary.avg_heart_rate is not None else None),
            ("calories_kcal", str(summary.calories_kcal) if summary.calories_kcal is not None else None),
        ]

        # Combined sleep entry: "7.5時間 品質:good"
        if summary.sleep_minutes is not None:
            sleep_hours = summary.sleep_minutes / 60.0
            sleep_val = f"{sleep_hours:.1f}時間"
            if summary.sleep_quality:
                sleep_val += f" 品質:{summary.sleep_quality}"
            scalar_items.append(("sleep", sleep_val))

        for key, value in scalar_items:
            if value is None:
                continue
            try:
                result = await upsert_fact_item(
                    jwt,
                    category="health",
                    key=f"{key}_{summary.date}",
                    value=value,
                    confidence=0.9,
                    source="sensor",
                    reason=f"Google Fit sync for {summary.date}",
                )
                stored.append(result)
            except Exception:
                logger.exception("health: failed to store %s for %s", key, summary.date)

        return stored


# ─── helpers ─────────────────────────────────────────────────────────────────


def _agg_params(data_type_name: str, start_ms: int, end_ms: int) -> dict:
    return {
        "aggregateBy": [{"dataTypeName": data_type_name}],
        "bucketByTime": {"durationMillis": str(86_400_000)},
        "startTimeMillis": str(start_ms),
        "endTimeMillis": str(end_ms),
    }


def _summarize_health_items(items: list[dict]) -> dict[str, Any]:
    """Group raw fact items into a human-readable 7-day summary."""
    by_date: dict[str, dict] = {}
    for item in items:
        key: str = item.get("key", "")
        value = item.get("value")
        if not key or value is None:
            continue
        parts = key.rsplit("_", 1)
        if len(parts) != 2:
            continue
        metric, d = parts[0], parts[1]
        by_date.setdefault(d, {})[metric] = value

    return {"days": [{"date": d, **metrics} for d, metrics in sorted(by_date.items())]}
