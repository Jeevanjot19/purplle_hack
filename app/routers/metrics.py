"""
GET /stores/{store_id}/metrics

Returns live store metrics while using PostgreSQL as the source of truth for
session and conversion counts. Redis is still used for hot queue/depth state.
"""

from datetime import datetime, timezone

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.redis_client import (
    get_redis,
    key_last_event_ts,
    key_queue_depth,
    key_zone_dwell_count,
    key_zone_dwell_sum,
)

router = APIRouter(tags=["intelligence"])
logger = structlog.get_logger()


@router.get("/stores/{store_id}/metrics")
async def get_metrics(
    store_id: str,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    session_result = await db.execute(text("""
        SELECT
            COUNT(*) FILTER (WHERE is_staff = FALSE) AS visitor_count,
            COUNT(*) FILTER (WHERE is_staff = FALSE AND converted = TRUE) AS conversion_count
        FROM sessions
        WHERE store_id = :store_id
    """), {"store_id": store_id})
    session_row = session_result.fetchone()
    visitor_count = session_row.visitor_count or 0
    conversion_count = session_row.conversion_count or 0

    if visitor_count == 0:
        visitor_result = await db.execute(text("""
            SELECT COUNT(DISTINCT visitor_id) AS visitor_count
            FROM events
            WHERE store_id = :store_id
              AND is_staff = FALSE
              AND event_type = 'ENTRY'
        """), {"store_id": store_id})
        visitor_count = visitor_result.scalar_one() or 0

    conversion_rate = round(conversion_count / visitor_count, 4) if visitor_count else 0.0

    queue_depth = int(await redis.get(key_queue_depth(store_id)) or 0)
    if queue_depth == 0:
        queue_result = await db.execute(text("""
            SELECT queue_depth
            FROM events
            WHERE store_id = :store_id
              AND event_type = 'BILLING_QUEUE_JOIN'
              AND queue_depth IS NOT NULL
            ORDER BY timestamp DESC
            LIMIT 1
        """), {"store_id": store_id})
        queue_depth = queue_result.scalar_one_or_none() or 0

    zone_dwell = await _zone_dwell_from_redis(redis, store_id)
    if not zone_dwell:
        zone_dwell = await _zone_dwell_from_db(db, store_id)

    abandon_result = await db.execute(text("""
        SELECT
            COUNT(*) FILTER (WHERE event_type = 'BILLING_QUEUE_ABANDON') AS abandons,
            COUNT(*) FILTER (WHERE event_type = 'BILLING_QUEUE_JOIN') AS joins
        FROM events
        WHERE store_id = :store_id
          AND is_staff = FALSE
    """), {"store_id": store_id})
    abandon_row = abandon_result.fetchone()
    abandons, joins = (abandon_row.abandons or 0), (abandon_row.joins or 0)
    abandonment_rate = round(abandons / joins, 4) if joins else 0.0

    last_event_ts = await redis.get(key_last_event_ts(store_id))
    if not last_event_ts:
        last_result = await db.execute(text("""
            SELECT MAX(timestamp) AS last_event_ts
            FROM events
            WHERE store_id = :store_id
        """), {"store_id": store_id})
        last_dt = last_result.scalar_one_or_none()
        last_event_ts = last_dt.isoformat() if last_dt else None

    freshness_ms = None
    if last_event_ts:
        try:
            last_dt = datetime.fromisoformat(last_event_ts.replace("Z", "+00:00"))
            freshness_ms = int((datetime.now(timezone.utc) - last_dt).total_seconds() * 1000)
        except Exception:
            logger.warning("metrics_freshness_parse_failed", store_id=store_id, value=last_event_ts)

    return {
        "store_id": store_id,
        "window": "all",
        "visitor_count": visitor_count,
        "unique_visitors": visitor_count,
        "conversion_count": conversion_count,
        "conversion_rate": conversion_rate,
        "avg_dwell_by_zone": zone_dwell,
        "queue_depth_current": queue_depth,
        "abandonment_rate": abandonment_rate,
        "last_event_ts": last_event_ts,
        "data_freshness_ms": freshness_ms,
    }


async def _zone_dwell_from_redis(redis: aioredis.Redis, store_id: str) -> dict[str, int]:
    zone_dwell = {}
    async for key in redis.scan_iter(f"store:{store_id}:zone:*:dwell_sum"):
        zone_id = key.split(":")[3]
        dwell_sum = float(await redis.get(key_zone_dwell_sum(store_id, zone_id)) or 0)
        dwell_count = int(await redis.get(key_zone_dwell_count(store_id, zone_id)) or 0)
        if dwell_count > 0:
            zone_dwell[zone_id] = round(dwell_sum / dwell_count)
    return zone_dwell


async def _zone_dwell_from_db(db: AsyncSession, store_id: str) -> dict[str, int]:
    result = await db.execute(text("""
        SELECT zone_id, AVG(dwell_ms) AS avg_dwell_ms
        FROM events
        WHERE store_id = :store_id
          AND is_staff = FALSE
          AND event_type = 'ZONE_DWELL'
          AND zone_id IS NOT NULL
        GROUP BY zone_id
    """), {"store_id": store_id})
    return {row.zone_id: round(row.avg_dwell_ms or 0) for row in result.fetchall()}
