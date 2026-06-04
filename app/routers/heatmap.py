"""
GET /stores/{store_id}/heatmap

Zone visit frequency, dwell time, and normalized score.
"""

import json
from pathlib import Path

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
            COUNT(*) AS visit_count,
            AVG(dwell_ms) FILTER (WHERE event_type = 'ZONE_DWELL') AS avg_dwell_ms,
            COUNT(DISTINCT visitor_id) AS unique_visitors
        FROM events
        WHERE store_id = :store_id
          AND is_staff = FALSE
          AND zone_id IS NOT NULL
          AND event_type IN ('ZONE_ENTER', 'ZONE_DWELL')
        GROUP BY zone_id
    """), {"store_id": store_id})
    observed = {
        row.zone_id: {
            "visit_count": row.visit_count or 0,
            "avg_dwell_ms": round(row.avg_dwell_ms or 0),
            "unique_visitors": row.unique_visitors or 0,
        }
        for row in result.fetchall()
    }

    session_result = await db.execute(text("""
        SELECT COUNT(*) AS session_count
        FROM sessions
        WHERE store_id = :store_id
          AND is_staff = FALSE
    """), {"store_id": store_id})
    session_count = session_result.scalar_one() or 0
    known_zones = _known_zones(store_id)

    all_zone_ids = list(dict.fromkeys([*known_zones, *observed.keys()]))
    max_visits = max((observed.get(zone, {}).get("visit_count", 0) for zone in all_zone_ids), default=0)
    max_dwell = max((observed.get(zone, {}).get("avg_dwell_ms", 0) for zone in all_zone_ids), default=0)

    zones = []
    for zone_id in all_zone_ids:
        data = observed.get(zone_id, {})
        visit_count = data.get("visit_count", 0)
        avg_dwell_ms = data.get("avg_dwell_ms", 0)
        visit_score = (visit_count / max_visits * 100) if max_visits else 0
        dwell_score = (avg_dwell_ms / max_dwell * 100) if max_dwell else 0
        zones.append({
            "zone_id": zone_id,
            "visit_count": visit_count,
            "avg_dwell_ms": avg_dwell_ms,
            "unique_visitors": data.get("unique_visitors", 0),
            "normalized_score": round((visit_score * 0.7) + (dwell_score * 0.3)),
        })

    return {
        "store_id": store_id,
        "zones": zones,
        "data_confidence": "LOW" if session_count < 20 else "HIGH",
        "session_count": session_count,
    }


def _known_zones(store_id: str) -> list[str]:
    layout_path = Path("data/store_layout.json")
    if not layout_path.exists():
        return []
    try:
        layout = json.loads(layout_path.read_text(encoding="utf-8"))
        cameras = layout.get("stores", {}).get(store_id, {}).get("cameras", {})
        zones: list[str] = []
        for camera in cameras.values():
            for zone in camera.get("zones", []):
                zone_id = zone.get("id") or zone.get("zone_id")
                if zone_id:
                    zones.append(zone_id)
        return zones
    except Exception as exc:
        logger.warning("layout_read_failed", store_id=store_id, error=str(exc))
        return []
