import json
import time
import uuid

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Event, IngestResponse, RejectedEvent
from app.redis_client import (
    get_redis,
    key_conversion_count,
    key_last_event_ts,
    key_pubsub_channel,
    key_queue_depth,
    key_visitor_count,
    key_zone_dwell_count,
    key_zone_dwell_sum,
)

router = APIRouter(tags=["ingestion"])
logger = structlog.get_logger()


@router.post("/events/ingest", response_model=IngestResponse)
async def ingest_events(
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    trace_id = request.headers.get("X-Trace-ID", str(uuid.uuid4()))
    t_start = time.perf_counter()

    rejected: list[RejectedEvent] = []
    valid_events: list[Event] = []

    try:
        payload = await request.json()
    except Exception as exc:
        return IngestResponse(
            accepted=0,
            rejected=[
                RejectedEvent(
                    index=0,
                    event_id=None,
                    reason="invalid_json",
                    detail=str(exc),
                )
            ],
            duplicate_skipped=0,
        )

    raw_events = payload.get("events") if isinstance(payload, dict) else None
    if not isinstance(raw_events, list):
        return IngestResponse(
            accepted=0,
            rejected=[
                RejectedEvent(
                    index=0,
                    event_id=None,
                    reason="invalid_payload",
                    detail="Request body must be an object with an events list",
                )
            ],
            duplicate_skipped=0,
        )

    if len(raw_events) > 500:
        return IngestResponse(
            accepted=0,
            rejected=[
                RejectedEvent(
                    index=i,
                    event_id=e.get("event_id") if isinstance(e, dict) else None,
                    reason="batch_too_large",
                    detail="Batch size exceeds 500 events",
                )
                for i, e in enumerate(raw_events)
            ],
            duplicate_skipped=0,
        )

    for index, raw_event in enumerate(raw_events):
        event_id = raw_event.get("event_id") if isinstance(raw_event, dict) else None
        try:
            valid_events.append(Event.model_validate(raw_event))
        except ValidationError as exc:
            first_error = exc.errors()[0] if exc.errors() else {}
            rejected.append(
                RejectedEvent(
                    index=index,
                    event_id=event_id,
                    reason="validation_error",
                    detail=first_error.get("msg", str(exc)),
                )
            )
        except Exception as exc:
            rejected.append(
                RejectedEvent(
                    index=index,
                    event_id=event_id,
                    reason="invalid_event",
                    detail=str(exc),
                )
            )

    new_events: list[Event] = []
    if valid_events:
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
            RETURNING event_id
        """)

        for event in valid_events:
            result = await db.execute(insert_sql, event.to_db_dict())
            if result.scalar_one_or_none():
                new_events.append(event)

        await db.commit()
        await _update_sessions(db, new_events)

    stores_updated = await _update_redis(redis, new_events)

    for store_id in stores_updated:
        try:
            snapshot = await _build_metrics_snapshot(redis, store_id)
            await redis.publish(key_pubsub_channel(store_id), snapshot)
        except Exception as exc:
            logger.warning("pubsub_failed", store_id=store_id, error=str(exc))

    latency_ms = round((time.perf_counter() - t_start) * 1000, 1)
    duplicate_skipped = len(valid_events) - len(new_events)
    logger.info(
        "ingest_complete",
        trace_id=trace_id,
        accepted=len(new_events),
        rejected=len(rejected),
        duplicate_skipped=duplicate_skipped,
        event_count=len(raw_events),
        latency_ms=latency_ms,
    )

    return IngestResponse(
        accepted=len(new_events),
        rejected=rejected,
        duplicate_skipped=duplicate_skipped,
    )


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
            is_billing_zone = any(
                marker in event.zone_id.upper()
                for marker in ("BILLING", "CHECKOUT", "CASH")
            )
            await db.execute(text("""
                UPDATE sessions SET
                    zones_visited = CASE
                        WHEN zones_visited @> CAST(:zone_arr AS jsonb) THEN zones_visited
                        ELSE zones_visited || CAST(:zone_arr AS jsonb)
                    END,
                    reached_billing = CASE
                        WHEN :is_billing_zone THEN TRUE
                        ELSE reached_billing END,
                    last_updated = NOW()
                WHERE visitor_id = :vid
            """), {"vid": vid, "is_billing_zone": is_billing_zone,
                   "zone_arr": json.dumps([event.zone_id])})

        elif event.event_type == "BILLING_QUEUE_JOIN":
            await db.execute(text("""
                UPDATE sessions SET reached_billing = TRUE, last_updated = :ts
                WHERE visitor_id = :vid
            """), {"vid": vid, "ts": event.timestamp})

    if events:
        await db.commit()


async def _update_redis(redis: aioredis.Redis, events: list[Event]) -> set[str]:
    stores_updated: set[str] = set()
    if not events:
        return stores_updated

    pipe = redis.pipeline(transaction=False)
    for event in events:
        sid = event.store_id
        stores_updated.add(sid)
        pipe.set(key_last_event_ts(sid), event.timestamp.isoformat())
        if event.is_staff:
            continue
        if event.event_type == "ENTRY":
            pipe.incr(key_visitor_count(sid))
        elif event.event_type == "ZONE_DWELL" and event.zone_id:
            pipe.incrbyfloat(key_zone_dwell_sum(sid, event.zone_id), event.dwell_ms)
            pipe.incr(key_zone_dwell_count(sid, event.zone_id))
        elif event.event_type == "BILLING_QUEUE_JOIN" and event.metadata.queue_depth:
            pipe.set(key_queue_depth(sid), event.metadata.queue_depth)
        elif event.event_type == "EXIT":
            current = await redis.get(key_queue_depth(sid))
            if current and int(current) > 0:
                pipe.decr(key_queue_depth(sid))
    await pipe.execute()
    return stores_updated


async def _build_metrics_snapshot(redis: aioredis.Redis, store_id: str) -> str:
    vc = int(await redis.get(key_visitor_count(store_id)) or 0)
    qd = int(await redis.get(key_queue_depth(store_id)) or 0)
    cc = int(await redis.get(key_conversion_count(store_id)) or 0)
    lts = await redis.get(key_last_event_ts(store_id))
    return json.dumps({
        "store_id": store_id,
        "visitor_count": vc,
        "unique_visitors": vc,
        "queue_depth_current": qd,
        "conversion_count": cc,
        "conversion_rate": round(cc / vc, 4) if vc > 0 else 0.0,
        "last_event_ts": lts,
    })
