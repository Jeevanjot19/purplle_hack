import structlog
from datetime import datetime, timezone
from fastapi import APIRouter
from sqlalchemy import text
import redis.asyncio as aioredis

from app.db import AsyncSessionLocal
from app.redis_client import get_redis, key_last_event_ts
from app.config import settings

router = APIRouter(tags=["health"])
logger = structlog.get_logger()


async def _get_store_health(redis: aioredis.Redis) -> dict:
    stores = {}
    async for key in redis.scan_iter("store:*:last_event_ts"):
        store_id = key.split(":")[1]
        raw = await redis.get(key)
        if raw:
            try:
                last_dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                lag = (datetime.now(timezone.utc) - last_dt).total_seconds()
                stores[store_id] = {
                    "last_event":  raw,
                    "lag_seconds": round(lag),
                    "feed_status": "STALE_FEED" if lag > settings.stale_feed_threshold_seconds else "ok",
                }
            except Exception:
                stores[store_id] = {"last_event": raw, "feed_status": "unknown"}
    return stores


@router.get("/health")
async def health_check():
    db_ok, redis_ok = True, True
    db_error, redis_error = None, None

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        db_ok = False
        db_error = str(exc)

    redis_client = None
    try:
        redis_client = await get_redis()
        await redis_client.ping()
    except Exception as exc:
        redis_ok = False
        redis_error = str(exc)

    store_health = {}
    if redis_client and redis_ok:
        try:
            store_health = await _get_store_health(redis_client)
        except Exception:
            pass

    return {
        "status": "healthy" if (db_ok and redis_ok) else "degraded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": {
            "database": {"status": "ok" if db_ok else "error", "error": db_error},
            "cache":    {"status": "ok" if redis_ok else "error", "error": redis_error},
        },
        "stores": store_health,
    }
