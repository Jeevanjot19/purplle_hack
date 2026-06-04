"""
GET /stores/{store_id}/stream

Server-Sent Events endpoint using FastAPI 0.135's native SSE.
Subscribes to Redis pub/sub channel and forwards messages to browser.

Flow:
  pipeline POSTs events
    → ingestion.py publishes to Redis channel
    → this SSE endpoint receives and yields to browser
    → browser EventSource updates counters live
"""

import json
import asyncio
import structlog
from collections.abc import AsyncIterable

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse
import redis.asyncio as aioredis

from app.redis_client import get_redis_pool, key_pubsub_channel

router = APIRouter(tags=["stream"])
logger = structlog.get_logger()


@router.get(
    "/stores/{store_id}/stream",
    response_model=None,
    response_class=EventSourceResponse,
    summary="Live metric stream for a store",
)
async def store_stream(store_id: str) -> AsyncIterable[dict[str, str]]:
    """
    Yields a Server-Sent Event every time the ingest endpoint
    processes new events for this store. Clients connect once
    and receive a continuous stream — no polling required.
    """
    pool = await get_redis_pool()
    redis = aioredis.Redis(connection_pool=pool, decode_responses=True)
    pubsub = redis.pubsub()
    channel = key_pubsub_channel(store_id)

    await pubsub.subscribe(channel)
    logger.info("sse_client_connected", store_id=store_id)

    # Send initial heartbeat so the browser knows the connection is live
    yield {"event": "heartbeat", "data": json.dumps({"type": "connected", "store_id": store_id})}

    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                yield {"event": "metrics_update", "data": message["data"]}
    except asyncio.CancelledError:
        # Client disconnected — clean up
        logger.info("sse_client_disconnected", store_id=store_id)
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()
