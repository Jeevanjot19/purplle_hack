# Store Intelligence Design

## Plain-Language Architecture Overview

This project turns CCTV clips into retail intelligence. The system watches people, converts their movement into structured events, stores those events durably, and exposes metrics that a store manager can act on. The core idea is deliberately simple: the detection pipeline emits facts, the API validates and stores them, and the intelligence endpoints compute visitor, funnel, heatmap, and anomaly views from those facts.

The expected flow is:

`Raw CCTV -> Detection -> Event Stream -> API -> PostgreSQL/Redis -> Dashboard`

Raw clips and `store_layout.json` describe what each camera sees. The pipeline runs person detection, tracks people across frames, determines whether a person is inside a configured zone, and emits events such as `ENTRY`, `ZONE_DWELL`, `BILLING_QUEUE_JOIN`, and `EXIT`. The API accepts events through `POST /events/ingest`, validates each event independently, stores valid events in PostgreSQL, updates sessions, and refreshes Redis counters for live reads. The dashboard polls the API every few seconds.

## Detection Pipeline Design

The detection pipeline uses YOLO11s for person detection and BoT-SORT for tracking. CAM_3 is treated as the source of truth for entry and exit because it sees the door. Interior cameras emit zone events only. This avoids counting the same visitor as a new entry when they simply move between cameras inside the store.

Zone classification is polygon based. Each camera in `store_layout.json` has named zones with pixel polygons. For each tracked person, the center point of the bounding box is checked against those polygons. The pipeline emits dwell events for meaningful zone time, billing events for checkout areas, and marks likely staff separately so intelligence endpoints can exclude staff.

## Event Schema Explanation

The event schema is intentionally strict. Every event has a UUID v4 `event_id` for idempotency, `store_id`, `camera_id`, `visitor_id`, `event_type`, UTC `timestamp`, optional `zone_id`, `dwell_ms`, `is_staff`, `confidence`, and metadata fields for queue depth, SKU zone, and session sequence. This makes the API predictable and lets the repository include a converter for older sample event formats.

Malformed events do not poison a full batch. The ingest endpoint validates each row independently, inserts valid rows, skips duplicate `event_id` values, and returns structured rejection details with the event index and reason.

## API Architecture

FastAPI is the web layer. PostgreSQL is the durable source of truth for events, sessions, POS transactions, and anomaly records. Redis stores hot state such as last event timestamp, queue depth, and live counters for dashboard responsiveness. The API has separate routers for ingest, POS, metrics, funnel, heatmap, anomalies, health, and SSE streaming.

The metrics endpoint uses sessions for visitor and conversion counts, not only Redis counters. This matters because Redis can be cleared or restarted; the durable session table still answers the business question.

## Database and Cache Design

The `events` table is append-only and idempotent by `event_id`. The `sessions` table is keyed by `visitor_id` and stores entry time, exit time, zones visited, whether billing was reached, conversion status, basket value, staff flag, and reentry count. The `pos_transactions` table stores loaded transactions by transaction ID.

Redis is a performance layer, not the only truth. It keeps queue depth, dwell running totals, last event timestamps, and pub/sub updates for the dashboard. If Redis has no value, endpoints fall back to PostgreSQL where possible.

## Session and Funnel Logic

The funnel unit is a session, not a raw event. A visitor with an `ENTRY` creates a session. `REENTRY` increments `reentry_count` but does not create a new visitor. Zone events append to `zones_visited`. Billing events mark `reached_billing`. Purchases mark `converted`. The funnel returns `entry`, `zone_visit`, `billing_queue`, and `purchase`, with drop-off percentages between each stage.

## POS Correlation Logic

POS CSV rows are loaded through `pipeline/pos_loader.py` and `/pos/load`. The loader supports both `invoice_number` and challenge-style `order_id`. It combines `order_date` and `order_time` into an ISO-8601 UTC timestamp and uses `total_amount` as basket value. A session counts as converted when it reached billing in the five minutes before a transaction timestamp.

This is a pragmatic local rule. In production, the correlation would improve by using counter ID, register location, basket size, and stronger visitor-to-POS matching.

## Failure Handling

The API avoids raw stack traces in normal responses. Ingest returns structured partial success. Duplicate event IDs are skipped through PostgreSQL `ON CONFLICT DO NOTHING`. `/health` checks PostgreSQL and Redis and returns HTTP 503 with a structured body if either dependency is unavailable. Store feed freshness is reported as `STALE_FEED` when lag is over ten minutes.

## Production-Readiness Notes

The repo is containerized with Docker Compose. Normal startup brings up PostgreSQL, Redis, the API, and the dashboard. The pipeline is behind a Compose profile so it does not block normal API startup. Structured logs include trace ID, path, latency, status code, and store ID when present.

Known production upgrades include a durable queue between detection and API, GPU inference, per-store calibration workflows, stronger ReID, and authentication. Those were kept out of scope so the challenge submission stays runnable and understandable.

## AI-Assisted Decisions

AI helped compare YOLO/BoT-SORT against simpler motion detection and ByteTrack. The suggestion was useful because it highlighted identity stability as more important than raw FPS for a funnel system. We kept YOLO11s plus BoT-SORT, but we simplified the deployment story by documenting CPU limitations honestly.

AI also helped shape the event schema and session design. The initial recommendation was event sourcing with immutable events and derived sessions. We adopted that because idempotency and replayability are valuable, but we overrode the idea of accepting loose event fields directly in the API. Instead, the API remains strict and a converter normalizes sample files.

Finally, AI suggested a Redis-heavy architecture and even Redis Streams for decoupling. We kept Redis for hot live state but chose PostgreSQL as the source of truth for conversion and funnel correctness. We simplified away stream consumers because the evaluator needs a reliable local `docker compose up --build`, not a miniature distributed system.
