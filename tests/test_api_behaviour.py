# PROMPT: Cover Store Intelligence API edge cases required by the challenge acceptance checklist.
# CHANGES MADE: Added async unit tests for ingest, metrics, funnel, heatmap, anomalies, and health-shaped responses.

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.routers.anomalies import get_anomalies
from app.routers.funnel import get_funnel
from app.routers.heatmap import get_heatmap
from app.routers.ingestion import ingest_events
from app.routers.metrics import get_metrics


def event(event_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", **overrides):
    data = {
        "event_id": event_id,
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM_ENTRY_01",
        "visitor_id": "VIS_test01",
        "event_type": "ENTRY",
        "timestamp": "2026-06-04T10:00:00Z",
        "zone_id": None,
        "dwell_ms": 0,
        "is_staff": False,
        "confidence": 0.95,
        "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 1},
    }
    data.update(overrides)
    return data


class FakeRequest:
    headers = {}

    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


class Result:
    def __init__(self, scalar=None, row=None, rows=None):
        self._scalar = scalar
        self._row = row
        self._rows = rows or []
        self.rowcount = scalar if isinstance(scalar, int) else 0

    def scalar_one_or_none(self):
        return self._scalar

    def scalar_one(self):
        return self._scalar

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.published = []

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value):
        self.values[key] = str(value)

    async def incr(self, key):
        self.values[key] = str(int(self.values.get(key, 0)) + 1)

    async def incrby(self, key, amount):
        self.values[key] = str(int(self.values.get(key, 0)) + amount)

    async def publish(self, channel, payload):
        self.published.append((channel, payload))

    def pipeline(self, transaction=False):
        return FakePipe(self)

    async def scan_iter(self, _pattern):
        if False:
            yield None


class FakePipe:
    def __init__(self, redis):
        self.redis = redis
        self.ops = []

    def set(self, key, value):
        self.ops.append(("set", key, value))

    def incr(self, key):
        self.ops.append(("incr", key, None))

    def incrbyfloat(self, key, value):
        self.ops.append(("incrbyfloat", key, value))

    def decr(self, key):
        self.ops.append(("decr", key, None))

    async def execute(self):
        for op, key, value in self.ops:
            if op == "set":
                self.redis.values[key] = str(value)
            elif op == "incr":
                self.redis.values[key] = str(int(self.redis.values.get(key, 0)) + 1)
            elif op == "incrbyfloat":
                self.redis.values[key] = str(float(self.redis.values.get(key, 0)) + value)
            elif op == "decr":
                self.redis.values[key] = str(max(int(self.redis.values.get(key, 0)) - 1, 0))


class IngestDB:
    def __init__(self, duplicate_ids=None):
        self.duplicate_ids = set(duplicate_ids or [])
        self.inserted = []

    async def execute(self, sql, params=None):
        if "INSERT INTO events" in str(sql):
            if params["event_id"] in self.duplicate_ids:
                return Result(scalar=None)
            self.inserted.append(params["event_id"])
            return Result(scalar=params["event_id"])
        return Result(scalar=0)

    async def commit(self):
        return None


@pytest.mark.asyncio
async def test_ingest_accepts_valid_events():
    response = await ingest_events(FakeRequest({"events": [event()]}), IngestDB(), FakeRedis())

    assert response.accepted == 1
    assert response.rejected == []
    assert response.duplicate_skipped == 0


@pytest.mark.asyncio
async def test_ingest_skips_duplicate_event_id():
    response = await ingest_events(
        FakeRequest({"events": [event()]}),
        IngestDB(duplicate_ids={"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"}),
        FakeRedis(),
    )

    assert response.accepted == 0
    assert response.duplicate_skipped == 1


@pytest.mark.asyncio
async def test_ingest_partial_success_with_malformed_event():
    response = await ingest_events(
        FakeRequest({"events": [event(), {"event_id": "bad"}]}),
        IngestDB(),
        FakeRedis(),
    )

    assert response.accepted == 1
    assert len(response.rejected) == 1
    assert response.rejected[0].index == 1


class MetricsDB:
    def __init__(self, visitors=0, converted=0):
        self.visitors = visitors
        self.converted = converted

    async def execute(self, sql, params=None):
        query = str(sql)
        if "FROM sessions" in query and "converted" in query:
            return Result(row=SimpleNamespace(visitor_count=self.visitors, conversion_count=self.converted))
        if "COUNT(DISTINCT visitor_id)" in query:
            return Result(scalar=self.visitors)
        if "BILLING_QUEUE_JOIN" in query and "queue_depth" in query:
            return Result(scalar=0)
        if "BILLING_QUEUE_ABANDON" in query:
            return Result(row=SimpleNamespace(abandons=0, joins=0))
        if "MAX(timestamp)" in query:
            return Result(scalar=None)
        if "AVG(dwell_ms)" in query:
            return Result(rows=[])
        return Result(scalar=0)


@pytest.mark.asyncio
async def test_metrics_for_empty_store():
    response = await get_metrics("EMPTY", MetricsDB(), FakeRedis())

    assert response["visitor_count"] == 0
    assert response["conversion_rate"] == 0.0


@pytest.mark.asyncio
async def test_metrics_excludes_staff_and_zero_purchases():
    response = await get_metrics("STORE_BLR_002", MetricsDB(visitors=2, converted=0), FakeRedis())

    assert response["unique_visitors"] == 2
    assert response["conversion_rate"] == 0.0


class FunnelDB:
    async def execute(self, *_):
        return Result(row=SimpleNamespace(entry=1, zone_visit=1, billing_queue=1, purchase=0, reentries=1))


@pytest.mark.asyncio
async def test_funnel_reentry_does_not_double_count():
    response = await get_funnel("STORE_BLR_002", FunnelDB())

    assert response["sessions_total"] == 1
    assert response["reentries_observed"] == 1
    assert response["stages"][0]["count"] == 1


class HeatmapDB:
    async def execute(self, sql, params=None):
        query = str(sql)
        if "FROM events" in query:
            return Result(rows=[])
        return Result(scalar=2)


@pytest.mark.asyncio
async def test_heatmap_low_confidence_when_fewer_than_20_sessions():
    response = await get_heatmap("STORE_BLR_002", HeatmapDB())

    assert response["data_confidence"] == "LOW"
    assert any(zone["zone_id"] == "SKINCARE" for zone in response["zones"])


class AnomalyDB:
    async def execute(self, sql, params=None):
        query = str(sql)
        if "AVG(queue_depth)" in query:
            return Result(scalar=0)
        if "entry_time >= CURRENT_DATE" in query:
            return Result(row=SimpleNamespace(visitors=0, converted=0))
        if "entry_time >= CURRENT_DATE - INTERVAL '7 days'" in query:
            return Result(row=SimpleNamespace(visitors=0, converted=0))
        if "recent_events" in query:
            return Result(scalar=0)
        return Result(rows=[])


@pytest.mark.asyncio
async def test_anomalies_return_structured_response():
    response = await get_anomalies("STORE_BLR_002", AnomalyDB(), FakeRedis())

    assert "active_anomalies" in response
    assert response["active_anomalies"][0]["type"] == "CONVERSION_BASELINE_UNAVAILABLE"
    assert response["active_anomalies"][0]["suggested_action"]
