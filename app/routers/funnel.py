"""
GET /stores/{store_id}/funnel

Returns conversion funnel: Entry → Zone Visit → Billing → Purchase
Session is the unit. Re-entries must not double-count.

Uses the sessions table (kept in sync by ingestion.py) so this
is a lightweight query, not a heavy aggregation over all events.
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
            COUNT(*)                                            AS total_sessions,
            COUNT(*) FILTER (WHERE zones_visited != '[]'::jsonb
                             AND is_staff = FALSE)             AS visited_zone,
            COUNT(*) FILTER (WHERE reached_billing = TRUE
                             AND is_staff = FALSE)             AS reached_billing,
            COUNT(*) FILTER (WHERE converted = TRUE
                             AND is_staff = FALSE)             AS purchased,
            COUNT(*) FILTER (WHERE is_staff = FALSE)           AS customer_sessions
        FROM sessions
        WHERE store_id = :store_id
          AND entry_time >= CURRENT_DATE
    """), {"store_id": store_id})

    row = result.fetchone()

    total      = row.customer_sessions or 0
    zone_visit = row.visited_zone      or 0
    billing    = row.reached_billing   or 0
    purchased  = row.purchased         or 0

    def pct(n, base):
        return round(n / base * 100, 1) if base > 0 else 0.0

    def drop(a, b, base):
        lost = a - b
        return {"lost": lost, "pct_lost": pct(lost, base)}

    stages = [
        {"stage": "entry",         "count": total,      "pct": 100.0},
        {"stage": "zone_visit",    "count": zone_visit, "pct": pct(zone_visit, total)},
        {"stage": "billing_queue", "count": billing,    "pct": pct(billing, total)},
        {"stage": "purchase",      "count": purchased,  "pct": pct(purchased, total)},
    ]

    dropoffs = [
        {"from": "entry",         "to": "zone_visit",    **drop(total,      zone_visit, total)},
        {"from": "zone_visit",    "to": "billing_queue", **drop(zone_visit, billing,    total)},
        {"from": "billing_queue", "to": "purchase",      **drop(billing,    purchased,  total)},
    ]

    return {
        "store_id":       store_id,
        "sessions_total": total,
        "stages":         stages,
        "dropoffs":       dropoffs,
    }
