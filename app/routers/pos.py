"""
POST /pos/load - bulk load POS transactions and correlate purchases.
"""

from datetime import datetime

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.redis_client import get_redis, key_conversion_count

router = APIRouter(tags=["pos"])
logger = structlog.get_logger()


class POSTransaction(BaseModel):
    transaction_id: str = Field(..., min_length=1)
    store_id: str = Field(..., min_length=1)
    timestamp: datetime
    basket_value: float = Field(..., ge=0)

    @field_validator("timestamp")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return value


class POSLoadPayload(BaseModel):
    transactions: list[POSTransaction] = Field(default_factory=list, max_length=500)


@router.post("/pos/load")
async def load_pos_transactions(
    payload: POSLoadPayload,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    if not payload.transactions:
        return {"loaded": 0, "duplicate_skipped": 0, "sessions_converted": 0}

    inserted = 0
    for txn in payload.transactions:
        result = await db.execute(text("""
            INSERT INTO pos_transactions (transaction_id, store_id, timestamp, basket_value)
            VALUES (:transaction_id, :store_id, :timestamp, :basket_value)
            ON CONFLICT (transaction_id) DO NOTHING
            RETURNING transaction_id
        """), txn.model_dump())
        if result.scalar_one_or_none():
            inserted += 1
    await db.commit()

    sessions_converted = 0
    for txn in payload.transactions:
        result = await db.execute(text("""
            UPDATE sessions
            SET converted = TRUE,
                basket_value = :basket_value,
                last_updated = NOW()
            WHERE store_id = :store_id
              AND is_staff = FALSE
              AND reached_billing = TRUE
              AND converted = FALSE
              AND last_updated >= CAST(:txn_ts AS timestamptz) - INTERVAL '5 minutes'
              AND last_updated <= CAST(:txn_ts AS timestamptz)
        """), {
            "store_id": txn.store_id,
            "basket_value": txn.basket_value,
            "txn_ts": txn.timestamp,
        })
        sessions_converted += result.rowcount or 0

    await db.commit()

    if sessions_converted:
        by_store: dict[str, int] = {}
        for txn in payload.transactions:
            by_store.setdefault(txn.store_id, 0)
        # Recompute exact converted counts per touched store to keep Redis bounded.
        for store_id in by_store:
            count_result = await db.execute(text("""
                SELECT COUNT(*) FROM sessions
                WHERE store_id = :store_id
                  AND is_staff = FALSE
                  AND converted = TRUE
            """), {"store_id": store_id})
            await redis.set(key_conversion_count(store_id), count_result.scalar_one() or 0)

    duplicate_skipped = len(payload.transactions) - inserted
    logger.info(
        "pos_loaded",
        loaded=inserted,
        duplicate_skipped=duplicate_skipped,
        sessions_converted=sessions_converted,
    )
    return {
        "loaded": inserted,
        "duplicate_skipped": duplicate_skipped,
        "sessions_converted": sessions_converted,
    }
