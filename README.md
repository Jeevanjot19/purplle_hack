# Store Intelligence — Retail Analytics Platform
**Build**: 1.0.0 | **Status**: Pre-Release | **Phase**: Testing

A production-ready CCTV-based retail analytics system for real-time visitor tracking, zone heatmaps, funnel analysis, and anomaly detection.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                       STORE INTELLIGENCE                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  Layer 5: DETECTION                Layer 4: DASHBOARD            │
│  ┌──────────────────────┐          ┌──────────────────────────┐ │
│  │ YOLO11s + BoT-SORT   │          │ Live Metrics UI (React) │ │
│  │ Multi-Camera Coord   │          │ - Visitor Count         │ │
│  │ Staff Classification │          │ - Zone Heatmap          │ │
│  │ Zone Tracking        │          │ - Funnel Analysis       │ │
│  │ Re-entry Detection   │          │ - Anomalies             │ │
│  └──────────┬───────────┘          └────────────┬─────────────┘ │
│             │                                   │                 │
│  Layer 3: INTELLIGENCE APIs     Layer 2: CACHE │                 │
│  ┌──────────────────────────────────────────────┼──────────────┐ │
│  │ POST /events/ingest                          │ Redis        │ │
│  │ GET /stores/{id}/metrics                     │ - Sessions   │ │
│  │ GET /stores/{id}/funnel                      │ - Live stats │ │
│  │ GET /stores/{id}/heatmap                     │ - Galleries  │ │
│  │ GET /stores/{id}/anomalies                   └──────────────┘ │
│  │ GET /stores/{id}/stream (SSE)                                 │
│  └──────────────────────┬──────────────────────────────────────┘ │
│                         │                                         │
│                    Layer 1: DATA                                  │
│                  ┌──────────────────┐                            │
│                  │  PostgreSQL 16   │                            │
│                  │  - Events        │                            │
│                  │  - Sessions      │                            │
│                  │  - Transactions  │                            │
│                  │  - Anomalies     │                            │
│                  └──────────────────┘                            │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

## Key Features

✅ **Real-Time Visitor Tracking**
- YOLO11s person detection + BoT-SORT tracking
- Per-frame zone classification (Shapely polygon containment)
- Cross-camera visitor deduplication (HSV ReID embeddings)

✅ **Multi-Camera Architecture**
- Entry/Exit camera (tripwire-based ENTRY/EXIT events)
- Floor cameras (ZONE tracking only)
- Automatic cross-camera overlap handling

✅ **Advanced Analytics**
- Funnel analysis: Entry → Zones → Billing → Conversion
- Zone dwell time & heatmaps
- Anomaly detection (unusual visitor patterns)
- Staff vs. customer classification (zone diversity + HSV signature)

✅ **Production-Ready**
- Event idempotency (ON CONFLICT handling)
- Async/await throughout (FastAPI + asyncpg)
- Fire-and-forget event batching (1 sec buffer)
- Pub/Sub metrics broadcast (Redis)
- Structured logging (structlog + JSON)

## Getting Started

### Prerequisites
- Docker & Docker Compose
- Python 3.10+
- 2GB RAM minimum
- GPU optional (YOLO inference 5-10ms/frame on CPU)

### Quick Start

```bash
# 1. Clone and setup
git clone https://github.com/Jeevanjot19/purplle_hack.git
cd store-intelligence
docker-compose up -d

# 2. Wait for health checks
docker-compose ps  # All services: healthy

# 3. Process a test video
python test_pipeline_manual.py

# 4. Check metrics
curl http://localhost:8000/stores/ST1008/metrics | jq

# 5. View dashboard
open http://localhost:3000
```

## Configuration

### Store Configuration (`data/store_layout.json`)

Define camera views, zones, and tripwires per store:

```json
{
  "stores": {
    "ST1008": {
      "name": "Brigade Road, Bangalore",
      "cameras": {
        "CAM_1": {
          "type": "main_floor",
          "zones": [
            {
              "zone_id": "COSMETICS_WALL",
              "polygon": [[0, 0], [100, 0], [100, 100], [0, 100]]
            }
          ]
        },
        "CAM_3": {
          "type": "entry_exit",
          "zones": [...],
          "tripwire": {
            "x1": 300, "y1": 350, "x2": 950, "y2": 350,
            "inside_y_direction": "up"
          }
        }
      }
    }
  }
}
```

### Environment Variables

```bash
# API
DATABASE_URL=postgresql+asyncpg://store:store123@db:5432/storedb
REDIS_URL=redis://cache:6379
LOG_LEVEL=INFO

# Pipeline
STORE_ID=ST1008
CAMERA_ID=CAM_1
API_URL=http://localhost:8000
```

## API Reference

### Ingest Events
```bash
POST /events/ingest
Content-Type: application/json

{
  "events": [
    {
      "event_id": "550e8400-e29b-41d4-a716-446655440001",
      "store_id": "ST1008",
      "camera_id": "CAM_1",
      "visitor_id": "VIS_abc123def456",
      "event_type": "ZONE_ENTER",
      "timestamp": "2026-06-01T20:15:30Z",
      "zone_id": "COSMETICS_WALL",
      "confidence": 0.95
    }
  ]
}
```

### Metrics
```bash
GET /stores/ST1008/metrics

{
  "store_id": "ST1008",
  "unique_visitors": 14,
  "queue_depth_current": 2,
  "conversion_count": 3,
  "conversion_rate": 0.2143,
  "last_event_ts": "2026-06-01T20:15:47Z"
}
```

### Stream (SSE)
```bash
GET /stores/ST1008/stream

event: metrics
data: {"store_id":"ST1008","unique_visitors":14,...}
```

## Project Structure

```
store-intelligence/
├── app/                      # FastAPI application
│   ├── main.py              # App initialization, lifespan
│   ├── config.py            # Settings (pydantic)
│   ├── models.py            # Pydantic models (Event, etc)
│   ├── db.py                # SQLAlchemy session/engine
│   ├── orm.py               # ORM models (Event table, etc)
│   ├── redis_client.py      # Redis connection pool
│   └── routers/             # API endpoints
│       ├── health.py        # GET /health
│       ├── ingestion.py     # POST /events/ingest
│       ├── metrics.py       # GET /stores/{id}/metrics
│       ├── funnel.py        # GET /stores/{id}/funnel
│       ├── heatmap.py       # GET /stores/{id}/heatmap
│       ├── anomalies.py     # GET /stores/{id}/anomalies
│       ├── sse.py           # GET /stores/{id}/stream
│       └── pos.py           # POST /pos/load
│
├── pipeline/                # Detection pipeline
│   ├── detect.py           # Main orchestrator (frame loop)
│   ├── tracker.py          # GlobalSessionRegistry (multi-camera)
│   ├── zones.py            # ZoneEngine (polygon containment)
│   ├── staff.py            # StaffClassifier (zone diversity + HSV)
│   ├── reid.py             # ReIDGallery (cross-cam dedup)
│   ├── emit.py             # EventEmitter (batching + HTTP POST)
│   ├── botsort.yaml        # BoT-SORT tracker config
│   ├── run.sh              # Pipeline entrypoint
│   └── pos_loader.py       # Load POS CSV at startup
│
├── data/                    # Configuration & video data
│   ├── store_layout.json   # Multi-camera config
│   ├── CAM_1.mp4           # Test video (Brigade Road)
│   ├── CAM_2.mp4           # Optional: makeup wall
│   └── CAM_3.mp4           # Optional: entry/exit
│
├── migrations/              # Database schema
│   └── 001_initial.sql     # Tables: events, sessions, pos_transactions, anomaly_log
│
├── tests/                   # Test suite (expanding)
│   ├── test_imports.py     # Smoke test
│   ├── test_zone_engine.py # Zone polygon tests
│   ├── test_pipeline_manual.py  # E2E pipeline test
│   └── test_cam3_entry_exit.py  # Entry/exit validation
│
├── docs/                    # Documentation
│   ├── ARCHITECTURE.md      # Multi-camera design
│   ├── PROMPT_LOG.md        # Decision history
│   └── AUDIT_ANALYSIS.md    # Weak points & recommendations
│
├── docker-compose.yml       # Services: api, db, cache, dashboard
├── Dockerfile.api          # FastAPI image
├── Dockerfile.pipeline     # Detection pipeline image
├── requirements.api.txt    # API dependencies
├── requirements.pipeline.txt # Pipeline dependencies
└── README.md               # This file
```

## Development Roadmap

### Phase 1: Validation Testing (In Progress)
- [ ] Upload CAM_3.mp4 (entry camera)
- [ ] Upload CAM_2.mp4 (makeup wall)
- [ ] Run Phase 1 test: CAM_3 entry/exit accuracy
- [ ] Run Phase 2 test: CAM_1 zone tracking
- [ ] Run Phase 3 test: CAM_2 zone tracking
- [ ] Run Phase 4 test: All 3 concurrent, cross-camera dedup

### Phase 2: Bug Fixes & Tuning
- [ ] Fix identified weak points (see AUDIT_ANALYSIS.md)
- [ ] Tune ReID thresholds empirically
- [ ] Add integration tests
- [ ] Benchmark performance

### Phase 3: Production Hardening
- [ ] Add authentication/authorization
- [ ] Implement retry logic for event emitter
- [ ] Add persistent event buffer
- [ ] Performance optimization
- [ ] Load testing

### Phase 4: Evaluation Readiness
- [ ] Final documentation sweep
- [ ] Edge case testing
- [ ] Evaluator walkthrough
- [ ] Setup guide + troubleshooting

## Weak Points & Known Issues

See [AUDIT_ANALYSIS.md](AUDIT_ANALYSIS.md) for comprehensive analysis.

**Critical**:
1. Event emitter is fire-and-forget (no retry)
2. ReID thresholds tuned theoretically, not empirically
3. No concurrent multi-camera processing (sequential only)
4. Git repository just initialized (legacy project)

**Medium**:
5. Zone polygon validation not strict
6. Staff classifier lacks zone list validation
7. No billing zone exit detection
8. Registry per-clip design (reentry inflation risk)

## Contributors

- **[Your Name]** - Architecture, Core Modules
- **[AI Agent]** - Infrastructure, Testing

## License

MIT License — See LICENSE file

## Support

For issues, questions, or contributions:
1. Check [AUDIT_ANALYSIS.md](AUDIT_ANALYSIS.md) for known issues
2. Check [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for design decisions
3. Review [PROMPT_LOG.md](docs/PROMPT_LOG.md) for discovery history
4. Create an issue on GitHub

---

**Last Updated**: June 1, 2026  
**Status**: ✅ Pre-Release, Ready for Testing  
**Next Action**: Upload CAM_2/CAM_3 → Run Phase 1 tests
