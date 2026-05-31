"""
GET /stores/{store_id}/anomalies

Five anomaly types, all rule-based:
  BILLING_QUEUE_SPIKE   - queue > 2× 7-day hourly avg   → CRITICAL
  CONVERSION_DROP       - today rate < 70% of 7-day avg → WARN
  DEAD_ZONE             - no visits in 30 min (open hrs) → INFO
  STALE_FEED            - no events in 10 min            → CRITICAL
  ABNORMAL_EXIT_RATIO   - exits > entries + 10%          → WARN
"""

import structlog
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends
import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.redis_client import get_redis, key_queue_depth, key_last_event_ts
from app.config import settings

router = APIRouter(tags=["intelligence"])
logger = structlog.get_logger()


@router.get("/stores/{store_id}/anomalies")
async def get_anomalies(
    store_id: str,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    anomalies = []
    now = datetime.now(timezone.utc)

    # ── 1. STALE_FEED ─────────────────────────────────────────
    last_ts_raw = await redis.get(key_last_event_ts(store_id))
    if last_ts_raw:
        try:
            last_ts = datetime.fromisoformat(last_ts_raw.replace("Z", "+00:00"))
            lag_seconds = (now - last_ts).total_seconds()
            if lag_seconds > settings.stale_feed_threshold_seconds:
                anomalies.append({
                    "anomaly_type":     "STALE_FEED",
                    "severity":         "CRITICAL",
                    "detected_at":      now.isoformat(),
                    "details":          {
                        "last_event_ts":  last_ts_raw,
                        "lag_seconds":    round(lag_seconds),
                    },
                    "suggested_action": (
                        f"No events received from {store_id} for "
                        f"{round(lag_seconds/60, 1)} minutes. "
                        "Check camera feed and pipeline health."
                    ),
                })
        except Exception:
            pass
    else:
        anomalies.append({
            "anomaly_type":     "STALE_FEED",
            "severity":         "CRITICAL",
            "detected_at":      now.isoformat(),
            "details":          {"last_event_ts": None},
            "suggested_action": f"No events ever received from {store_id}. Check pipeline.",
        })

    # ── 2. BILLING_QUEUE_SPIKE ────────────────────────────────
    current_queue = int(await redis.get(key_queue_depth(store_id)) or 0)
    avg_result = await db.execute(text("""
        SELECT COALESCE(AVG(queue_depth), 0) AS avg_depth
        FROM events
        WHERE store_id  = :store_id
          AND event_type = 'BILLING_QUEUE_JOIN'
          AND timestamp  >= NOW() - INTERVAL '7 days'
          AND EXTRACT(HOUR FROM timestamp) = EXTRACT(HOUR FROM NOW())
          AND queue_depth IS NOT NULL
    """), {"store_id": store_id})
    avg_queue = float(avg_result.fetchone().avg_depth or 0)

    if avg_queue > 0 and current_queue > (2 * avg_queue):
        anomalies.append({
            "anomaly_type":     "BILLING_QUEUE_SPIKE",
            "severity":         "CRITICAL",
            "detected_at":      now.isoformat(),
            "details":          {
                "current_depth": current_queue,
                "7_day_avg":     round(avg_queue, 1),
                "ratio":         round(current_queue / avg_queue, 2),
            },
            "suggested_action": (
                f"Queue depth {current_queue} is {round(current_queue/avg_queue, 1)}× "
                "the 7-day average. Open an additional billing counter immediately."
            ),
        })

    # ── 3. CONVERSION_DROP ────────────────────────────────────
    today_result = await db.execute(text("""
        SELECT
            COUNT(*) FILTER (WHERE converted = TRUE)  AS converted_today,
            COUNT(*) FILTER (WHERE is_staff = FALSE)  AS total_today
        FROM sessions
        WHERE store_id   = :store_id
          AND entry_time >= CURRENT_DATE
    """), {"store_id": store_id})
    today_row = today_result.fetchone()
    total_today     = today_row.total_today     or 0
    converted_today = today_row.converted_today or 0
    today_rate = converted_today / total_today if total_today > 0 else None

    hist_result = await db.execute(text("""
        SELECT
            COUNT(*) FILTER (WHERE converted = TRUE)::float /
            NULLIF(COUNT(*) FILTER (WHERE is_staff = FALSE), 0) AS hist_rate
        FROM sessions
        WHERE store_id   = :store_id
          AND entry_time >= CURRENT_DATE - INTERVAL '7 days'
          AND entry_time <  CURRENT_DATE
    """), {"store_id": store_id})
    hist_rate = hist_result.fetchone().hist_rate

    if today_rate is not None and hist_rate and today_rate < (0.7 * hist_rate):
        anomalies.append({
            "anomaly_type":     "CONVERSION_DROP",
            "severity":         "WARN",
            "detected_at":      now.isoformat(),
            "details":          {
                "today_rate":   round(today_rate, 4),
                "7_day_avg":    round(hist_rate, 4),
                "drop_pct":     round((1 - today_rate / hist_rate) * 100, 1),
            },
            "suggested_action": (
                f"Today's conversion rate ({round(today_rate*100,1)}%) is more than "
                f"30% below the 7-day average ({round(hist_rate*100,1)}%). "
                "Review staff performance and product placement."
            ),
        })

    # ── 4. DEAD_ZONE ──────────────────────────────────────────
    dead_result = await db.execute(text("""
        SELECT
            zone_id,
            MAX(timestamp) AS last_visit
        FROM events
        WHERE store_id   = :store_id
          AND is_staff   = FALSE
          AND zone_id    IS NOT NULL
          AND event_type = 'ZONE_ENTER'
          AND timestamp  >= CURRENT_DATE
        GROUP BY zone_id
        HAVING MAX(timestamp) < NOW() - INTERVAL '30 minutes'
    """), {"store_id": store_id})

    for row in dead_result.fetchall():
        minutes_inactive = round(
            (now - row.last_visit.replace(tzinfo=timezone.utc)).total_seconds() / 60
        )
        anomalies.append({
            "anomaly_type":     "DEAD_ZONE",
            "severity":         "INFO",
            "detected_at":      now.isoformat(),
            "details":          {
                "zone_id":           row.zone_id,
                "last_visit_ts":     row.last_visit.isoformat(),
                "minutes_inactive":  minutes_inactive,
            },
            "suggested_action": (
                f"Zone '{row.zone_id}' has had no visitors for {minutes_inactive} minutes. "
                "Consider promotional activity or check camera coverage."
            ),
        })

    # ── 5. ABNORMAL_EXIT_RATIO ───────────────────────────────
    ratio_result = await db.execute(text("""
        SELECT
            COUNT(*) FILTER (WHERE event_type = 'ENTRY') AS entries,
            COUNT(*) FILTER (WHERE event_type = 'EXIT')  AS exits
        FROM events
        WHERE store_id  = :store_id
          AND is_staff  = FALSE
          AND timestamp >= CURRENT_DATE
    """), {"store_id": store_id})
    r = ratio_result.fetchone()
    entries, exits = (r.entries or 0), (r.exits or 0)
    if entries > 10 and exits > entries * 1.1:
        anomalies.append({
            "anomaly_type":     "ABNORMAL_EXIT_RATIO",
            "severity":         "WARN",
            "detected_at":      now.isoformat(),
            "details":          {"entries": entries, "exits": exits},
            "suggested_action": (
                "Exit count significantly exceeds entry count — "
                "possible detection error or camera misconfiguration."
            ),
        })

    return {
        "store_id":        store_id,
        "checked_at":      now.isoformat(),
        "active_anomalies": anomalies,
        "count":           len(anomalies),
    }
