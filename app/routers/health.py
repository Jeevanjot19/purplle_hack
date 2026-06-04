from datetime import datetime, timezone

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import settings
from app.db import AsyncSessionLocal
from app.redis_client import get_redis, key_last_event_ts

router = APIRouter(tags=["health"])
logger = structlog.get_logger()


@router.get("/health")
async def health_check():
    db_ok, redis_ok = True, True
    db_error, redis_error = None, None
    redis_client = None

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        db_ok = False
        db_error = str(exc)

    try:
        redis_client = await get_redis()
        await redis_client.ping()
    except Exception as exc:
        redis_ok = False
        redis_error = str(exc)

    stores = {}
    if db_ok:
        try:
            async with AsyncSessionLocal() as session:
                stores.update(await _get_store_health_from_db(session))
        except Exception as exc:
            logger.warning("health_db_store_scan_failed", error=str(exc))

    if redis_ok and redis_client:
        try:
            stores.update(await _get_store_health_from_redis(redis_client, stores))
        except Exception as exc:
            logger.warning("health_redis_store_scan_failed", error=str(exc))

    body = {
        "status": "healthy" if db_ok and redis_ok else "degraded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": {
            "database": {"status": "ok" if db_ok else "error", "error": db_error},
            "cache": {"status": "ok" if redis_ok else "error", "error": redis_error},
        },
        "stores": stores,
    }
    return JSONResponse(body, status_code=200 if db_ok and redis_ok else 503)


async def _get_store_health_from_db(session) -> dict:
    result = await session.execute(text("""
        SELECT store_id, MAX(timestamp) AS last_event
        FROM events
        GROUP BY store_id
    """))
    stores = {}
    for row in result.fetchall():
        if row.last_event:
            stores[row.store_id] = _store_status(row.last_event.isoformat())
    return stores


async def _get_store_health_from_redis(redis: aioredis.Redis, current: dict) -> dict:
    stores = {}
    async for key in redis.scan_iter("store:*:last_event_ts"):
        store_id = key.split(":")[1]
        raw = await redis.get(key_last_event_ts(store_id))
        if raw:
            stores[store_id] = _store_status(raw)
    return {**current, **stores}


def _store_status(raw_timestamp: str) -> dict:
    try:
        last_dt = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        lag = (datetime.now(timezone.utc) - last_dt).total_seconds()
        return {
            "last_event": raw_timestamp,
            "lag_seconds": round(lag),
            "feed_status": "STALE_FEED" if lag > settings.stale_feed_threshold_seconds else "ok",
        }
    except Exception:
        return {"last_event": raw_timestamp, "lag_seconds": None, "feed_status": "unknown"}
