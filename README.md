# Store Intelligence - Purplle Engineering Challenge

CCTV-based offline retail analytics for visitor counting, zone dwell, funnel conversion, queue monitoring, health checks, and anomaly detection.

## 5-Command Setup

```bash
git clone https://github.com/Jeevanjot19/purplle_hack.git
cd purplle_hack
docker compose up --build
curl http://localhost:8000/health
curl http://localhost:8000/stores/STORE_BLR_002/metrics
```

Dashboard: http://localhost:3000

## What Runs

`docker compose up --build` starts:

- PostgreSQL 16 with the schema from `migrations/001_initial.sql`
- Redis 7 for live counters and feed freshness
- FastAPI on http://localhost:8000
- Static dashboard on http://localhost:3000

The detection pipeline is available under the `pipeline` Compose profile so normal API startup remains fast.

## Camera Layout

The richer demo layout in `data/store_layout.json` models the real multi-camera store setup:

- `CAM_1` main floor: skincare, central display, and cash-counter-adjacent zones.
- `CAM_2` makeup wall: makeup and accessories wall zones.
- `CAM_3` entry/exit: door tripwire and source of truth for ENTRY/EXIT.
- `CAM_4` stockroom: marked `process=false` and skipped because it is staff-only.
- `CAM_5` billing counter: checkout desk and queue zones.

The acceptance-store layout for `STORE_BLR_002` is also included so the evaluator can call `/stores/STORE_BLR_002/metrics` on a clean database and receive valid JSON immediately.

## Core Commands

Start services:

```bash
docker compose up --build
```

Check health:

```bash
curl http://localhost:8000/health
```

Ingest the committed sample batch for the acceptance store:

```bash
curl -X POST http://localhost:8000/events/ingest \
  -H "Content-Type: application/json" \
  --data-binary @data/sample_ingest_events.json
```

Verify metrics:

```bash
curl http://localhost:8000/stores/STORE_BLR_002/metrics
```

Check funnel, heatmap, and anomalies:

```bash
curl http://localhost:8000/stores/STORE_BLR_002/funnel
curl http://localhost:8000/stores/STORE_BLR_002/heatmap
curl http://localhost:8000/stores/STORE_BLR_002/anomalies
```

Run the smoke test after Compose is up:

```bash
bash scripts/smoke_test.sh
```

## Sample Event Conversion

Some challenge sample files use older names such as `id_token`, `store_code`, `event_timestamp`, and lowercase event types. Convert them with:

```bash
python scripts/convert_sample_events.py \
  --input data/sample_events.jsonl \
  --output data/converted_events.jsonl
```

Convert and ingest in one step:

```bash
python scripts/convert_sample_events.py \
  --input data/sample_events.jsonl \
  --output data/converted_events.jsonl \
  --ingest \
  --api-url http://localhost:8000
```

## POS CSV Loading

The POS loader supports both `invoice_number` and the challenge schema:

`order_id, order_date, order_time, store_id, product_id, brand_name, total_amount`

Run it locally:

```bash
python -c "import asyncio; from pipeline.pos_loader import load_pos; asyncio.run(load_pos('data/pos_transactions.csv', 'http://localhost:8000'))"
```

Or let the pipeline container run it before video processing:

```bash
docker compose --profile pipeline up --build pipeline
```

## Detection Pipeline

Manual CAM_3 entry/exit test:

```bash
python test_cam3_entry_exit.py
```

Manual CAM_1 zone test:

```bash
python test_pipeline_manual.py
```

Full Compose pipeline profile:

```bash
docker compose --profile pipeline up --build pipeline
```

The real detector is CPU-heavy. On a laptop, full video processing can take several minutes. For API/demo verification without YOLO, use:

```bash
python pipeline/simulator.py --stores STORE_BLR_002 --duration 20 --speed 5
```

## API Endpoints

### `POST /events/ingest`

Accepts batches up to 500 events. Each event is validated independently. Valid events are inserted, duplicate `event_id` values are skipped, and malformed rows are returned in `rejected` without failing the whole batch.

Required fields:

- `event_id` UUID v4
- `store_id`
- `camera_id`
- `visitor_id` beginning with `VIS_`
- `event_type`
- `timestamp` ISO-8601 with timezone
- `zone_id`
- `dwell_ms`
- `is_staff`
- `confidence`
- `metadata.queue_depth`
- `metadata.sku_zone`
- `metadata.session_seq`

Supported event types:

`ENTRY`, `EXIT`, `ZONE_ENTER`, `ZONE_EXIT`, `ZONE_DWELL`, `BILLING_QUEUE_JOIN`, `BILLING_QUEUE_ABANDON`, `REENTRY`

### `GET /stores/{id}/metrics`

Returns visitor count, conversion count/rate, average dwell by zone, queue depth, abandonment rate, and feed freshness. Staff events are excluded. Empty and zero-purchase stores return valid JSON with `conversion_rate: 0.0`.

### `GET /stores/{id}/funnel`

Returns session-based stages: `entry`, `zone_visit`, `billing_queue`, `purchase`. Reentries increment `reentry_count` but do not create a new visitor.

### `GET /stores/{id}/heatmap`

Returns known zones from `store_layout.json` when possible, visit count, average dwell, `normalized_score` from 0 to 100, and `data_confidence` (`LOW` below 20 sessions, otherwise `HIGH`).

### `GET /stores/{id}/anomalies`

Returns structured anomalies with `type`, `severity`, `message`, `suggested_action`, and `detected_at`. Implemented rules include queue spike, conversion drop against 7-day baseline, and dead zone.

### `GET /health`

Checks database and Redis. Returns store feed freshness and marks feeds as `STALE_FEED` after 10 minutes of lag. Dependency failures return HTTP 503 with structured JSON.

## Running Tests

```bash
pytest -q
```

Coverage command:

```bash
pytest --cov=app --cov=pipeline --cov=scripts --cov-report=term-missing
```

## Repository Layout

```text
app/                  FastAPI app and routers
pipeline/             CCTV detector, emitter, POS loader, simulator
data/                 store layout and sample ingest events
dashboard/            static dashboard served by nginx
docs/DESIGN.md        design overview and AI-assisted decisions
docs/CHOICES.md       three key architecture decisions
scripts/              converter and smoke test
tests/                pytest suite
docker-compose.yml    db, redis, api, dashboard, optional pipeline
```

## Final Submission Checklist

- `docker compose up --build` tested
- `/health` tested
- `/events/ingest` tested
- `/stores/STORE_BLR_002/metrics` tested
- `docs/DESIGN.md` present and over 250 words
- `docs/CHOICES.md` present and over 250 words
- `pytest -q` test suite available
- Dashboard URL: http://localhost:3000

## Known Limitations

The detector is CPU-heavy without GPU acceleration. The POS correlation rule is intentionally pragmatic: sessions that reached billing within five minutes before a transaction are marked converted. For production, this should be improved with register location, receipt timing, and stronger customer-to-transaction matching.
