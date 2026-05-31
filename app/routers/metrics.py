"""
GET /stores/{store_id}/metrics

Returns real-time store metrics. Hot path — reads from Redis.
Only falls back to Postgres if Redis has no data for this store.

Fields returned:
  - unique_visitors      : count of non-staff ENTRY events today
  - conversion_rate      : converted sessions / total customer sessions
  - avg_dwell_by_zone    : {zone_id: avg_dwell_ms} from Redis running averages
  - queue_depth_current  : current billing queue depth from Redis
  - abandonment_rate     : BILLING_QUEUE_ABANDON / BILLING_QUEUE_JOIN
  - data_freshness_ms    : ms since last event was ingested
"""

import json
import structlog
from datetime import datetime, timezone, date
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as aioredis

from app.db import get_db
from app.redis_client import (
    get_redis,
    key_visitor_count, key_queue_depth, key_conversion_count,
    key_last_event_ts, key_zone_dwell_sum, key_zone_dwell_count,
)

router = APIRouter(tags=["intelligence"])
logger = structlog.get_logger()


@router.get("/stores/{store_id}/metrics")
async def get_metrics(
    store_id: str,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    # ── Live counters from Redis (sub-millisecond) ─────────────
    visitor_count    = int(await redis.get(key_visitor_count(store_id))    or 0)
    queue_depth      = int(await redis.get(key_queue_depth(store_id))      or 0)
    conversion_count = int(await redis.get(key_conversion_count(store_id)) or 0)
    last_event_ts    = await redis.get(key_last_event_ts(store_id))

    conversion_rate = round(conversion_count / visitor_count, 4) if visitor_count > 0 else 0.0

    # ── Zone dwell averages from Redis ─────────────────────────
    # Scan for all zone dwell keys for this store
    zone_dwell = {}
    pattern = f"store:{store_id}:zone:*:dwell_sum"
    async for key in redis.scan_iter(pattern):
        zone_id = key.split(":")[3]
        dwell_sum   = float(await redis.get(key_zone_dwell_sum(store_id, zone_id))   or 0)
        dwell_count = int(  await redis.get(key_zone_dwell_count(store_id, zone_id)) or 0)
        if dwell_count > 0:
            zone_dwell[zone_id] = round(dwell_sum / dwell_count)

    # ── Abandonment rate from Postgres ─────────────────────────
    # Redis doesn't track this — needs a query
    abandon_result = await db.execute(text("""
        SELECT
            COUNT(*) FILTER (WHERE event_type = 'BILLING_QUEUE_ABANDON') AS abandons,
            COUNT(*) FILTER (WHERE event_type = 'BILLING_QUEUE_JOIN')    AS joins
        FROM events
        WHERE store_id = :store_id
          AND is_staff = FALSE
          AND timestamp >= CURRENT_DATE
    """), {"store_id": store_id})
    row = abandon_result.fetchone()
    abandons, joins = (row.abandons or 0), (row.joins or 0)
    abandonment_rate = round(abandons / joins, 4) if joins > 0 else 0.0

    # ── Data freshness ─────────────────────────────────────────
    freshness_ms = None
    if last_event_ts:
        try:
            last_dt = datetime.fromisoformat(last_event_ts.replace("Z", "+00:00"))
            freshness_ms = int((datetime.now(timezone.utc) - last_dt).total_seconds() * 1000)
        except Exception:
            pass

    return {
        "store_id":           store_id,
        "window":             "today",
        "unique_visitors":    visitor_count,
        "conversion_rate":    conversion_rate,
        "avg_dwell_by_zone":  zone_dwell,
        "queue_depth_current": queue_depth,
        "abandonment_rate":   abandonment_rate,
        "data_freshness_ms":  freshness_ms,
    }
