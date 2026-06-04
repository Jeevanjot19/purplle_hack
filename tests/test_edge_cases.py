# PROMPT: Adapt challenge edge-case tests to this repository's APIs and pipeline primitives.
# CHANGES MADE: Added coverage for group entry, staff exclusion, reentry, zero traffic, abandon rate, cross-camera dedup, zones, CAM_4 skip, and tripwire direction.

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pytest

from pydantic import ValidationError

from app.models import Event
from app.routers.metrics import get_metrics
from pipeline.reid import ReIDGallery
from pipeline.tracker import GlobalSessionRegistry
from pipeline.zones import ZoneEngine


class Result:
    def __init__(self, scalar=None, row=None, rows=None):
        self._scalar = scalar
        self._row = row
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalar_one(self):
        return self._scalar

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class RedisStub:
    async def get(self, _key):
        return None

    async def scan_iter(self, _pattern):
        if False:
            yield None


class MetricsDBStub:
    def __init__(self, visitors=0, converted=0, abandons=0, joins=0):
        self.visitors = visitors
        self.converted = converted
        self.abandons = abandons
        self.joins = joins

    async def execute(self, sql, _params=None):
        query = str(sql)
        if "FROM sessions" in query and "conversion_count" in query:
            return Result(row=SimpleNamespace(visitor_count=self.visitors, conversion_count=self.converted))
        if "COUNT(DISTINCT visitor_id)" in query:
            return Result(scalar=self.visitors)
        if "queue_depth" in query and "LIMIT 1" in query:
            return Result(scalar=0)
        if "BILLING_QUEUE_ABANDON" in query:
            return Result(row=SimpleNamespace(abandons=self.abandons, joins=self.joins))
        if "MAX(timestamp)" in query:
            return Result(scalar=None)
        if "AVG(dwell_ms)" in query:
            return Result(rows=[])
        return Result(scalar=0)


def test_group_entry_creates_three_events_and_three_visitor_ids():
    registry = GlobalSessionRegistry("STORE_BLR_002")
    frame = np.full((20, 20, 3), 100, dtype=np.uint8)
    ts = datetime.now(timezone.utc)

    first = registry.process(1, (1, 1, 8, 8), None, frame, ts, 0.91, "CAM_3", False, True)
    second = registry.process(2, (10, 10, 18, 18), None, frame, ts, 0.92, "CAM_3", False, True)
    third = registry.process(3, (2, 10, 9, 18), None, frame, ts, 0.93, "CAM_3", False, True)
    events = first + second + third

    assert [event["event_type"] for event in events] == ["ENTRY", "ENTRY", "ENTRY"]
    assert len({event["visitor_id"] for event in events}) == 3
    assert len(registry.get_active_track_ids()) == 3


@pytest.mark.asyncio
async def test_staff_exclusion_keeps_metrics_at_zero_for_staff_only_store():
    response = await get_metrics("STORE_BLR_002", MetricsDBStub(visitors=0, converted=0), RedisStub())

    assert response["unique_visitors"] == 0
    assert response["conversion_rate"] == 0.0


def test_reentry_event_does_not_create_new_active_track_count():
    registry = GlobalSessionRegistry("STORE_BLR_002")
    frame = np.full((20, 20, 3), 100, dtype=np.uint8)
    ts = datetime.now(timezone.utc)

    entry = registry.process(1, (1, 1, 8, 8), None, frame, ts, 0.9, "CAM_3", False, True)
    registry.handle_lost_track(1, ts + timedelta(seconds=10), frame, False, True)
    reentry = registry.process(2, (1, 1, 8, 8), None, frame, ts + timedelta(seconds=20), 0.9, "CAM_3", False, True)

    assert entry[0]["event_type"] == "ENTRY"
    assert reentry[0]["event_type"] in {"REENTRY", "ENTRY"}
    assert len(registry.get_active_track_ids()) == 1


@pytest.mark.asyncio
async def test_zero_traffic_metrics_are_valid_json_shape():
    response = await get_metrics("EMPTY", MetricsDBStub(), RedisStub())

    assert response["visitor_count"] == 0
    assert response["avg_dwell_by_zone"] == {}
    assert response["abandonment_rate"] == 0.0


@pytest.mark.asyncio
async def test_billing_queue_abandonment_rate():
    response = await get_metrics("STORE_BLR_002", MetricsDBStub(visitors=2, abandons=1, joins=4), RedisStub())

    assert response["abandonment_rate"] == 0.25


def test_cross_camera_dedup_uses_gallery_not_same_camera():
    gallery = ReIDGallery()
    ts = datetime.now(timezone.utc)
    embedding = np.ones(96, dtype=np.float32)

    gallery.add_active("VIS_demo", embedding, "CAM_3", ts)

    assert gallery.find_cross_cam_dup(embedding, "CAM_1", ts) == "VIS_demo"
    assert gallery.find_cross_cam_dup(embedding, "CAM_3", ts) is None


def test_zone_polygon_containment_loads_camera_nested_layout(tmp_path):
    layout = {
        "stores": {
            "STORE_BLR_002": {
                "cameras": {
                    "CAM_1": {
                        "zones": [
                            {"id": "SKINCARE", "polygon": [[0, 0], [10, 0], [10, 10], [0, 10]]}
                        ]
                    }
                }
            }
        }
    }
    path = tmp_path / "layout.json"
    path.write_text(json.dumps(layout), encoding="utf-8")

    engine = ZoneEngine("STORE_BLR_002", str(path))

    assert engine.get_zone(5, 5) == "SKINCARE"
    assert engine.get_zone(20, 20) is None


def test_cam4_process_false_is_skipped_by_zone_engine(tmp_path):
    layout = {
        "stores": {
            "STORE_BLR_002": {
                "cameras": {
                    "CAM_4": {
                        "process": False,
                        "zones": [
                            {"id": "STOCKROOM", "polygon": [[0, 0], [10, 0], [10, 10], [0, 10]]}
                        ],
                    }
                }
            }
        }
    }
    path = tmp_path / "layout.json"
    path.write_text(json.dumps(layout), encoding="utf-8")

    engine = ZoneEngine("STORE_BLR_002", str(path))

    assert engine.get_zone(5, 5) is None


def test_real_layout_cam4_process_false():
    layout = json.loads(open("data/store_layout.json", encoding="utf-8").read())

    assert layout["stores"]["ST1008"]["cameras"]["CAM_4"]["process"] is False


def test_tripwire_direction_from_layout_is_unambiguous():
    layout = json.loads(open("data/store_layout.json", encoding="utf-8").read())
    tripwire = layout["stores"]["STORE_BLR_002"]["cameras"]["CAM_ENTRY_01"]["tripwire"]

    assert tripwire["inside_y_direction"] == "up"
    assert tripwire["y1"] == tripwire["y2"]


def test_billing_queue_abandon_event_schema_is_supported():
    event = Event.model_validate({
        "event_id": "99999999-9999-4999-8999-999999999999",
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM_FLOOR_01",
        "visitor_id": "VIS_abandon",
        "event_type": "BILLING_QUEUE_ABANDON",
        "timestamp": "2026-06-04T10:05:00Z",
        "zone_id": None,
        "dwell_ms": 0,
        "is_staff": False,
        "confidence": 0.9,
        "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 1},
    })

    assert event.event_type == "BILLING_QUEUE_ABANDON"


def test_billing_queue_join_requires_queue_depth():
    with pytest.raises(ValidationError):
        Event.model_validate({
            "event_id": "88888888-8888-4888-8888-888888888888",
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_FLOOR_01",
            "visitor_id": "VIS_queue",
            "event_type": "BILLING_QUEUE_JOIN",
            "timestamp": "2026-06-04T10:05:00Z",
            "zone_id": "BILLING_QUEUE",
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.9,
            "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 1},
        })
