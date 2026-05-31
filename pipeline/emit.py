"""
pipeline/emit.py
────────────────
Async event emitter. Buffers events for 1 second (15 frames)
then POSTs to POST /events/ingest. Fire-and-forget — a failed
POST is logged and dropped, never blocks the detection loop.
"""
import asyncio
import json
import time
import structlog
import httpx
from datetime import datetime, timezone

logger = structlog.get_logger()

API_URL_DEFAULT = "http://api:8000"


class EventEmitter:
    def __init__(self, api_url: str = API_URL_DEFAULT, buffer_seconds: float = 1.0):
        self.api_url        = api_url
        self.buffer_seconds = buffer_seconds
        self._buffer:   list[dict] = []
        self._last_flush = time.time()
        self._client:   httpx.AsyncClient | None = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=10.0)
        return self

    async def __aexit__(self, *_):
        # Flush remaining events on exit
        if self._buffer:
            await self._flush()
        if self._client:
            await self._client.aclose()

    def queue(self, event: dict):
        """Add event to buffer. Call this synchronously from the frame loop."""
        self._buffer.append(event)

    async def tick(self):
        """
        Call once per frame. Flushes buffer if 1 second has elapsed.
        This keeps HTTP round-trips to ~1/second regardless of FPS.
        """
        if (time.time() - self._last_flush) >= self.buffer_seconds:
            if self._buffer:
                await self._flush()

    async def flush_all(self):
        """Call at end of clip to emit remaining buffered events."""
        if self._buffer:
            await self._flush()

    async def _flush(self):
        if not self._buffer or not self._client:
            return

        batch = self._buffer[:]
        self._buffer.clear()
        self._last_flush = time.time()

        try:
            response = await self._client.post(
                f"{self.api_url}/events/ingest",
                json={"events": batch},
                headers={"Content-Type": "application/json"},
            )
            if response.status_code != 200:
                logger.warning("emit_non_200",
                               status=response.status_code,
                               batch_size=len(batch))
        except Exception as exc:
            logger.error("emit_failed", error=str(exc), batch_size=len(batch))
            # Don't re-queue — a lost batch is better than an infinite retry loop


def build_event(
    event_type: str,
    store_id: str,
    camera_id: str,
    visitor_id: str,
    timestamp: datetime,
    zone_id: str | None,
    dwell_ms: int,
    is_staff: bool,
    confidence: float,
    event_id: str,
    queue_depth: int | None = None,
    sku_zone: str | None = None,
    session_seq: int = 0,
) -> dict:
    """Build a validated event dict ready to POST."""
    return {
        "event_id":   event_id,
        "store_id":   store_id,
        "camera_id":  camera_id,
        "visitor_id": visitor_id,
        "event_type": event_type,
        "timestamp":  timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "zone_id":    zone_id,
        "dwell_ms":   dwell_ms,
        "is_staff":   is_staff,
        "confidence": round(float(confidence), 4),
        "metadata": {
            "queue_depth": queue_depth,
            "sku_zone":    sku_zone,
            "session_seq": session_seq,
        },
    }
