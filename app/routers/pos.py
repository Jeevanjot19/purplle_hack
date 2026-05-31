"""
app/routers/pos.py
──────────────────
POST /pos/load — Internal endpoint to bulk-load POS transactions.
Called by pipeline/pos_loader.py at startup.
Also handles POS correlation: marks sessions as converted when a
transaction occurs within 5 minutes of a billing zone visit.
"""
import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.redis_client import get_redis, key_conversion_count

router = APIRouter(tags=["pos"])
logger = structlog.get_logger()


class POSTransaction(BaseModel):
    transaction_id: str
    store_id:       str
    timestamp:      str
    basket_value:   float


class POSLoadPayload(BaseModel):
    transactions: list[POSTransaction]


@router.post("/pos/load")
async def load_pos_transactions(
    payload: POSLoadPayload,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """Bulk load POS transactions and correlate with sessions."""
    if not payload.transactions:
        return {"loaded": 0}

    rows = [t.model_dump() for t in payload.transactions]

    # Bulk insert with ON CONFLICT DO NOTHING for idempotency
    await db.execute(text("""
        INSERT INTO pos_transactions (transaction_id, store_id, timestamp, basket_value)
        VALUES (:transaction_id, :store_id, :timestamp::timestamptz, :basket_value)
        ON CONFLICT (transaction_id) DO NOTHING
    """), rows)
    await db.commit()

    # Correlate with sessions: any session in the billing zone
    # within 5 minutes before this transaction = converted
    for txn in payload.transactions:
        result = await db.execute(text("""
            UPDATE sessions
            SET converted = TRUE,
                basket_value = :basket_value,
                last_updated = NOW()
            WHERE store_id = :store_id
              AND reached_billing = TRUE
              AND converted = FALSE
              AND entry_time >= :txn_ts::timestamptz - INTERVAL '5 minutes'
              AND entry_time <= :txn_ts::timestamptz
        """), {
            "store_id":     txn.store_id,
            "basket_value": txn.basket_value,
            "txn_ts":       txn.timestamp,
        })

        # Update Redis conversion counter for each newly converted session
        if result.rowcount > 0:
            await redis.incrby(key_conversion_count(txn.store_id), result.rowcount)

    await db.commit()

    logger.info("pos_loaded", count=len(rows))
    return {"loaded": len(rows)}
