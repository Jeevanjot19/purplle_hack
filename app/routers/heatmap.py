"""
GET /stores/{store_id}/heatmap

Zone visit frequency + avg dwell, normalised 0-100.
Includes data_confidence flag if fewer than 20 sessions in window.
"""

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db

router = APIRouter(tags=["intelligence"])
logger = structlog.get_logger()


@router.get("/stores/{store_id}/heatmap")
async def get_heatmap(
    store_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(text("""
        SELECT
            zone_id,
            COUNT(*)           AS visit_count,
            AVG(dwell_ms)      AS avg_dwell_ms,
            COUNT(DISTINCT visitor_id) AS unique_visitors
        FROM events
        WHERE store_id  = :store_id
          AND is_staff  = FALSE
          AND zone_id   IS NOT NULL
          AND event_type IN ('ZONE_ENTER', 'ZONE_DWELL')
          AND timestamp >= CURRENT_DATE
        GROUP BY zone_id
        ORDER BY visit_count DESC
    """), {"store_id": store_id})

    rows = result.fetchall()

    # Session count for confidence flag
    session_result = await db.execute(text("""
        SELECT COUNT(*) AS session_count
        FROM sessions
        WHERE store_id = :store_id
          AND is_staff = FALSE
          AND entry_time >= CURRENT_DATE
    """), {"store_id": store_id})
    session_count = session_result.fetchone().session_count or 0
    low_confidence = session_count < 20

    if not rows:
        return {
            "store_id": store_id,
            "zones": [],
            "data_confidence": "low" if low_confidence else "normal",
            "session_count": session_count,
        }

    # Normalise visit_count and avg_dwell to 0-100
    max_visits = max(r.visit_count for r in rows)
    max_dwell  = max(r.avg_dwell_ms or 0 for r in rows) or 1

    zones = []
    for r in rows:
        zones.append({
            "zone_id":          r.zone_id,
            "visit_count":      r.visit_count,
            "avg_dwell_ms":     round(r.avg_dwell_ms or 0),
            "unique_visitors":  r.unique_visitors,
            "heat_score":       round((r.visit_count / max_visits) * 100),
            "dwell_score":      round(((r.avg_dwell_ms or 0) / max_dwell) * 100),
        })

    return {
        "store_id":        store_id,
        "zones":           zones,
        "data_confidence": "low" if low_confidence else "normal",
        "session_count":   session_count,
    }
