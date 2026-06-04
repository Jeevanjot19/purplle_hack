# Architectural Choices

This file records the three decisions I would want an evaluator to understand before reading the code. I used AI as a sounding board, but the final choices are grounded in the size of this challenge, the local Docker setup, and the fact that the system has to be easy to run during evaluation.

## Detection model choice

**Options considered:** YOLO11n, YOLO11s, larger YOLO models, OpenCV background subtraction, and cloud vision APIs.

**What AI suggested:** The first suggestion was to use a proven person detector rather than hand-tuned motion detection. It also suggested looking at smaller YOLO models because the evaluation environment might be CPU-only.

**What we chose:** YOLO11s with BoT-SORT tracking. The detector runs person-only inference, and BoT-SORT provides stable track IDs across short occlusions. The pipeline keeps CAM_3 as the source of truth for ENTRY and EXIT events, while floor cameras emit zone and dwell events.

**Why we chose it:** A retail analytics system is only useful if the person identity is stable enough for a session funnel. A slightly slower detector is acceptable for this challenge because the demo pipeline processes short clips and batches events every second. Classical background subtraction was tempting because it is fast, but it breaks under lighting changes, reflections, and crowded shelves.

**Trade-offs and limitations:** YOLO11s is still CPU-heavy. On a laptop, full video processing can take much longer than wall-clock video duration. We also simplified ReID and staff classification for the challenge; a production rollout would tune thresholds per store and preferably use GPU inference.

## Event schema design rationale

**Options considered:** Storing raw detections only, storing analytics aggregates only, or storing a normalized event stream with derived session rows.

**What AI suggested:** AI pushed toward an event-sourced design: immutable events first, then sessions and metrics derived from them. It also suggested idempotency by `event_id`.

**What we chose:** A strict event schema with `event_id`, `store_id`, `camera_id`, `visitor_id`, `event_type`, `timestamp`, optional `zone_id`, `dwell_ms`, `is_staff`, `confidence`, and metadata for queue depth, SKU zone, and session sequence. PostgreSQL stores every accepted event. A `sessions` table keeps the current visitor-level view for funnel and conversion logic.

**Why we chose it:** This gives us replayability and auditability. If the pipeline emits a wrong event, we can inspect the raw row. If metrics logic improves, we can recompute from events. Idempotent inserts let the pipeline retry without double-counting.

**Trade-offs and limitations:** The schema is stricter than some sample data, so we added a converter for legacy JSONL fields. We also enforce UTC timestamps and `VIS_` visitor IDs, which is good for consistency but means raw challenge files need normalization before ingest.

## API architecture choice

**Options considered:** A single PostgreSQL-backed API, a Redis-only metrics API, Kafka/Redis Streams between pipeline and API, or FastAPI with PostgreSQL plus Redis hot counters.

**What AI suggested:** AI initially suggested Redis Streams for a more production-like event bus and Redis counters for every metric.

**What we chose:** FastAPI writes events to PostgreSQL and updates Redis for hot live state such as queue depth and last-event timestamps. Metrics, funnel, heatmap, and conversion use PostgreSQL/session truth first, with Redis used where live state matters.

**Why we chose it:** The acceptance gate rewards correctness and reproducibility more than queueing sophistication. PostgreSQL gives idempotency, SQL aggregation, and durable audit records. Redis makes dashboard reads fast and keeps `/health` feed freshness cheap. Direct HTTP batching from the pipeline is simpler than running a stream consumer during evaluation.

**Trade-offs and limitations:** Direct POST means a failed batch can be lost if the detector process exits immediately after a network error. For a production fleet, I would move the pipeline-to-API boundary to Redis Streams or Kafka with dead-letter handling. For this submission, the simpler path is easier to run, easier to debug, and still robust because duplicate event IDs are skipped safely.
