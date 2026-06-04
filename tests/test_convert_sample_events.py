# PROMPT: Verify legacy sample_events.jsonl rows can be converted to the strict ingest schema.
# CHANGES MADE: Added tests for field-name mapping, UUID generation, VIS_ normalization, and event-type normalization.

import json
import uuid

from scripts.convert_sample_events import convert_event, convert_file


def test_convert_event_maps_challenge_fields():
    converted = convert_event({
        "id_token": "abc123",
        "store_code": "STORE_BLR_002",
        "event_timestamp": "2026-06-04T10:00:00+05:30",
        "event_type": "entry",
    })

    assert uuid.UUID(converted["event_id"]).version == 4
    assert converted["store_id"] == "STORE_BLR_002"
    assert converted["visitor_id"] == "VIS_abc123"
    assert converted["event_type"] == "ENTRY"
    assert converted["timestamp"] == "2026-06-04T04:30:00Z"
    assert converted["dwell_ms"] == 0
    assert converted["confidence"] == 0.75


def test_convert_event_maps_legacy_variants():
    converted = convert_event({
        "id_token": "ID_60001",
        "store_id": "STORE_BLR_002",
        "event_time": "2026-06-04T10:00:00",
        "event_type": "zone_entered",
        "camera_id": "CAM_FLOOR_01",
        "zone_id": "SKINCARE",
    })

    assert converted["visitor_id"] == "VIS_60001"
    assert converted["event_type"] == "ZONE_ENTER"
    assert converted["timestamp"] == "2026-06-04T10:00:00Z"
    assert converted["camera_id"] == "CAM_FLOOR_01"


def test_convert_event_preserves_zone_for_dwell():
    converted = convert_event({
        "id_token": "person-7",
        "event_type": "dwell",
        "zone": "MAKEUP",
        "dwell_time_ms": 45000,
    })

    assert converted["visitor_id"] == "VIS_person7"
    assert converted["event_type"] == "ZONE_DWELL"
    assert converted["zone_id"] == "MAKEUP"
    assert converted["dwell_ms"] == 45000


def test_convert_file_writes_jsonl(tmp_path):
    source = tmp_path / "sample_events.jsonl"
    dest = tmp_path / "converted_events.jsonl"
    source.write_text(json.dumps({"id_token": "u1", "event_type": "entry"}) + "\n", encoding="utf-8")

    events = convert_file(source, dest)

    assert len(events) == 1
    assert dest.read_text(encoding="utf-8").strip()
