import time, uuid, json, structlog
from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as aioredis

from app.db import get_db
from app.models import Event, IngestPayload, IngestResponse, RejectedEvent
from app.redis_client import (
    get_redis, key_visitor_count, key_queue_depth, key_conversion_count,
    key_last_event_ts, key_zone_dwell_sum, key_zone_dwell_count, key_pubsub_channel,
)

router = APIRouter(tags=["ingestion"])
logger = structlog.get_logger()


@router.post("/events/ingest", response_model=IngestResponse)
async def ingest_events(
    payload: IngestPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    trace_id = request.headers.get("X-Trace-ID", str(uuid.uuid4()))
    t_start  = time.perf_counter()

    valid_events: list[Event] = list(payload.events)
    rejected: list[RejectedEvent] = []

    # Bulk upsert — ON CONFLICT DO NOTHING = free idempotency
    new_count = 0
    if valid_events:
        rows = [e.to_db_dict() for e in valid_events]
        insert_sql = text("""
            INSERT INTO events (
                event_id, store_id, camera_id, visitor_id, event_type,
                timestamp, zone_id, dwell_ms, is_staff, confidence,
                queue_depth, sku_zone, session_seq
            ) VALUES (
                :event_id, :store_id, :camera_id, :visitor_id, :event_type,
                :timestamp, :zone_id, :dwell_ms, :is_staff, :confidence,
                :queue_depth, :sku_zone, :session_seq
            )
            ON CONFLICT (event_id) DO NOTHING
        """)
        result = await db.execute(insert_sql, rows)
        await db.commit()
        new_count = result.rowcount
        await _update_sessions(db, valid_events)

    # Redis live counters
    stores_updated: set[str] = set()
    if valid_events:
        pipe = redis.pipeline(transaction=False)
        for event in valid_events:
            sid = event.store_id
            stores_updated.add(sid)
            pipe.set(key_last_event_ts(sid), event.timestamp.isoformat())
            if event.is_staff:
                continue
            if event.event_type == "ENTRY":
                pipe.incr(key_visitor_count(sid))
            elif event.event_type in ("ZONE_DWELL",) and event.zone_id:
                pipe.incrbyfloat(key_zone_dwell_sum(sid, event.zone_id), event.dwell_ms)
                pipe.incr(key_zone_dwell_count(sid, event.zone_id))
            elif event.event_type == "BILLING_QUEUE_JOIN" and event.metadata.queue_depth:
                pipe.set(key_queue_depth(sid), event.metadata.queue_depth)
            elif event.event_type == "EXIT":
                current = await redis.get(key_queue_depth(sid))
                if current and int(current) > 0:
                    pipe.decr(key_queue_depth(sid))
        await pipe.execute()

    # Publish to SSE
    for store_id in stores_updated:
        try:
            snapshot = await _build_metrics_snapshot(redis, store_id)
            await redis.publish(key_pubsub_channel(store_id), snapshot)
        except Exception as e:
            logger.warning("pubsub_failed", store_id=store_id, error=str(e))

    latency_ms = round((time.perf_counter() - t_start) * 1000, 1)
    dup_skipped = len(valid_events) - new_count

    logger.info("ingest_complete", trace_id=trace_id, accepted=len(valid_events),
                rejected=len(rejected), new=new_count, dup=dup_skipped, ms=latency_ms)

    return IngestResponse(accepted=len(valid_events), rejected=rejected,
                          duplicate_skipped=dup_skipped)


async def _update_sessions(db: AsyncSession, events: list[Event]) -> None:
    for event in events:
        vid, sid = event.visitor_id, event.store_id

        if event.event_type in ("ENTRY", "REENTRY"):
            await db.execute(text("""
                INSERT INTO sessions (visitor_id, store_id, entry_time, is_staff)
                VALUES (:vid, :sid, :ts, :staff)
                ON CONFLICT (visitor_id) DO UPDATE SET
                    reentry_count = sessions.reentry_count +
                        CASE WHEN :etype = 'REENTRY' THEN 1 ELSE 0 END,
                    last_updated = NOW()
            """), {"vid": vid, "sid": sid, "ts": event.timestamp,
                   "staff": event.is_staff, "etype": event.event_type})

        elif event.event_type == "EXIT":
            await db.execute(text("""
                UPDATE sessions SET exit_time = :ts, last_updated = NOW()
                WHERE visitor_id = :vid
            """), {"vid": vid, "ts": event.timestamp})

        elif event.event_type in ("ZONE_ENTER", "ZONE_DWELL") and event.zone_id:
            await db.execute(text("""
                UPDATE sessions SET
                    zones_visited = CASE
                        WHEN zones_visited @> :zone_arr THEN zones_visited
                        ELSE zones_visited || :zone_arr
                    END,
                    reached_billing = CASE
                        WHEN :zone_id ILIKE '%billing%' THEN TRUE
                        ELSE reached_billing END,
                    last_updated = NOW()
                WHERE visitor_id = :vid
            """), {"vid": vid, "zone_id": event.zone_id,
                   "zone_arr": f'["{event.zone_id}"]'})

        elif event.event_type == "BILLING_QUEUE_JOIN":
            await db.execute(text("""
                UPDATE sessions SET reached_billing = TRUE, last_updated = NOW()
                WHERE visitor_id = :vid
            """), {"vid": vid})

    await db.commit()


async def _build_metrics_snapshot(redis: aioredis.Redis, store_id: str) -> str:
    vc  = int(await redis.get(key_visitor_count(store_id))   or 0)
    qd  = int(await redis.get(key_queue_depth(store_id))     or 0)
    cc  = int(await redis.get(key_conversion_count(store_id)) or 0)
    lts = await redis.get(key_last_event_ts(store_id))
    return json.dumps({
        "store_id":            store_id,
        "unique_visitors":     vc,
        "queue_depth_current": qd,
        "conversion_count":    cc,
        "conversion_rate":     round(cc / vc, 4) if vc > 0 else 0.0,
        "last_event_ts":       lts,
    })

