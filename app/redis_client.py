import redis.asyncio as aioredis
from app.config import settings

_pool: aioredis.ConnectionPool | None = None

async def get_redis_pool() -> aioredis.ConnectionPool:
    global _pool
    if _pool is None:
        _pool = aioredis.ConnectionPool.from_url(
            settings.redis_url,
            max_connections=20,
            decode_responses=True,
        )
    return _pool

async def get_redis() -> aioredis.Redis:
    pool = await get_redis_pool()
    return aioredis.Redis(connection_pool=pool)

def key_visitor_count(store_id: str) -> str:
    return f"store:{store_id}:visitor_count"

def key_queue_depth(store_id: str) -> str:
    return f"store:{store_id}:queue_depth"

def key_conversion_count(store_id: str) -> str:
    return f"store:{store_id}:conversion_count"

def key_last_event_ts(store_id: str) -> str:
    return f"store:{store_id}:last_event_ts"

def key_zone_dwell_sum(store_id: str, zone_id: str) -> str:
    return f"store:{store_id}:zone:{zone_id}:dwell_sum"

def key_zone_dwell_count(store_id: str, zone_id: str) -> str:
    return f"store:{store_id}:zone:{zone_id}:dwell_count"

def key_pubsub_channel(store_id: str) -> str:
    return f"store:{store_id}:updates"
