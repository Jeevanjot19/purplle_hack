"""
GET /stores/{store_id}/funnel

Session-based funnel: entry -> zone_visit -> billing_queue -> purchase.
"""

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db

router = APIRouter(tags=["intelligence"])
logger = structlog.get_logger()


@router.get("/stores/{store_id}/funnel")
async def get_funnel(
    store_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(text("""
        SELECT
            COUNT(*) FILTER (WHERE is_staff = FALSE) AS entry,
            COUNT(*) FILTER (
                WHERE is_staff = FALSE AND zones_visited != '[]'::jsonb
            ) AS zone_visit,
            COUNT(*) FILTER (
                WHERE is_staff = FALSE AND reached_billing = TRUE
            ) AS billing_queue,
            COUNT(*) FILTER (
                WHERE is_staff = FALSE AND converted = TRUE
            ) AS purchase,
            COALESCE(SUM(reentry_count) FILTER (WHERE is_staff = FALSE), 0) AS reentries
        FROM sessions
        WHERE store_id = :store_id
    """), {"store_id": store_id})
    row = result.fetchone()

    counts = {
        "entry": row.entry or 0,
        "zone_visit": row.zone_visit or 0,
        "billing_queue": row.billing_queue or 0,
        "purchase": row.purchase or 0,
    }
    total = counts["entry"]

    def pct(value: int, base: int) -> float:
        return round(value / base * 100, 1) if base else 0.0

    stages = [
        {"stage": name, "count": count, "pct_of_entry": pct(count, total)}
        for name, count in counts.items()
    ]

    transitions = [
        ("entry", "zone_visit"),
        ("zone_visit", "billing_queue"),
        ("billing_queue", "purchase"),
    ]
    dropoffs = []
    for start, end in transitions:
        start_count = counts[start]
        end_count = counts[end]
        lost = max(start_count - end_count, 0)
        dropoffs.append({
            "from": start,
            "to": end,
            "lost": lost,
            "dropoff_pct": pct(lost, start_count),
        })

    return {
        "store_id": store_id,
        "session_unit": "visitor_id",
        "sessions_total": total,
        "reentries_observed": row.reentries or 0,
        "stages": stages,
        "dropoffs": dropoffs,
    }
