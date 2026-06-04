"""
GET /stores/{store_id}/anomalies

Rule-based anomalies for queue spike, conversion drop, and dead zones.
"""

from datetime import datetime, timezone

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.redis_client import get_redis, key_queue_depth

router = APIRouter(tags=["intelligence"])
logger = structlog.get_logger()


@router.get("/stores/{store_id}/anomalies")
async def get_anomalies(
    store_id: str,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    now = datetime.now(timezone.utc)
    anomalies: list[dict] = []

    current_queue = int(await redis.get(key_queue_depth(store_id)) or 0)
    queue_avg_result = await db.execute(text("""
        SELECT COALESCE(AVG(queue_depth), 0) AS avg_depth
        FROM events
        WHERE store_id = :store_id
          AND event_type = 'BILLING_QUEUE_JOIN'
          AND queue_depth IS NOT NULL
          AND timestamp >= NOW() - INTERVAL '7 days'
    """), {"store_id": store_id})
    avg_queue = float(queue_avg_result.scalar_one() or 0)
    if current_queue >= 5 or (avg_queue > 0 and current_queue > avg_queue * 2):
        anomalies.append(_anomaly(
            "BILLING_QUEUE_SPIKE",
            "CRITICAL" if current_queue >= 8 else "WARN",
            f"Current billing queue depth is {current_queue}.",
            "Open another billing counter and route staff to checkout.",
            now,
            {"current_depth": current_queue, "baseline_depth": round(avg_queue, 2)},
        ))

    today = await db.execute(text("""
        SELECT
            COUNT(*) FILTER (WHERE is_staff = FALSE) AS visitors,
            COUNT(*) FILTER (WHERE is_staff = FALSE AND converted = TRUE) AS converted
        FROM sessions
        WHERE store_id = :store_id
          AND entry_time >= CURRENT_DATE
    """), {"store_id": store_id})
    today_row = today.fetchone()
    today_visitors = today_row.visitors or 0
    today_rate = (today_row.converted or 0) / today_visitors if today_visitors else None

    baseline = await db.execute(text("""
        SELECT
            COUNT(*) FILTER (WHERE is_staff = FALSE) AS visitors,
            COUNT(*) FILTER (WHERE is_staff = FALSE AND converted = TRUE) AS converted
        FROM sessions
        WHERE store_id = :store_id
          AND entry_time >= CURRENT_DATE - INTERVAL '7 days'
          AND entry_time < CURRENT_DATE
    """), {"store_id": store_id})
    base_row = baseline.fetchone()
    base_visitors = base_row.visitors or 0
    base_rate = (base_row.converted or 0) / base_visitors if base_visitors else None

    if today_rate is not None and base_rate is not None and today_rate < base_rate * 0.7:
        anomalies.append(_anomaly(
            "CONVERSION_DROP",
            "WARN",
            f"Today's conversion rate is {today_rate:.1%}, below the 7-day baseline {base_rate:.1%}.",
            "Check billing wait time, staff coverage, and high-intent zones.",
            now,
            {"today_rate": round(today_rate, 4), "baseline_rate": round(base_rate, 4)},
        ))
    elif base_visitors == 0:
        anomalies.append(_anomaly(
            "CONVERSION_BASELINE_UNAVAILABLE",
            "INFO",
            "No 7-day conversion baseline is available yet.",
            "Collect more historical sessions before alerting on conversion drops.",
            now,
            {"baseline_visitors": 0},
        ))

    traffic_result = await db.execute(text("""
        SELECT COUNT(*) AS recent_events
        FROM events
        WHERE store_id = :store_id
          AND is_staff = FALSE
          AND timestamp >= NOW() - INTERVAL '30 minutes'
    """), {"store_id": store_id})
    has_recent_traffic = (traffic_result.scalar_one() or 0) > 0
    if has_recent_traffic:
        dead_result = await db.execute(text("""
            SELECT zone_id, MAX(timestamp) AS last_visit
            FROM events
            WHERE store_id = :store_id
              AND is_staff = FALSE
              AND zone_id IS NOT NULL
              AND event_type IN ('ZONE_ENTER', 'ZONE_DWELL')
            GROUP BY zone_id
            HAVING MAX(timestamp) < NOW() - INTERVAL '30 minutes'
        """), {"store_id": store_id})
        for row in dead_result.fetchall():
            anomalies.append(_anomaly(
                "DEAD_ZONE",
                "INFO",
                f"Zone {row.zone_id} has no visits in the last 30 minutes while store traffic exists.",
                "Check camera coverage and consider moving a promotion or staff prompt to this zone.",
                now,
                {"zone_id": row.zone_id, "last_visit": row.last_visit.isoformat()},
            ))

    return {
        "store_id": store_id,
        "checked_at": now.isoformat(),
        "active_anomalies": anomalies,
        "count": len(anomalies),
    }


def _anomaly(
    anomaly_type: str,
    severity: str,
    message: str,
    suggested_action: str,
    detected_at: datetime,
    details: dict,
) -> dict:
    return {
        "type": anomaly_type,
        "anomaly_type": anomaly_type,
        "severity": severity,
        "message": message,
        "suggested_action": suggested_action,
        "detected_at": detected_at.isoformat(),
        "details": details,
    }
