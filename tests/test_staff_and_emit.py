# PROMPT: Add pipeline utility coverage for staff detection and event emission.
# CHANGES MADE: Added tests for staff duration/zone signals, uniform color scoring, event building, and emitter flush behavior.

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from pipeline.emit import EventEmitter, build_event
from pipeline.staff import StaffClassifier


def test_staff_classifier_marks_long_duration_as_staff():
    clf = StaffClassifier()
    start = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)
    frame = np.zeros((20, 20, 3), dtype=np.uint8)
    frame[:, :] = (255, 0, 0)

    clf.update(1, "SKINCARE", start, None, (0, 0, 10, 10))
    clf.update(1, "SKINCARE", start + timedelta(minutes=61), frame, (0, 0, 10, 10))

    assert clf.is_staff(1)


def test_staff_classifier_zone_diversity_score():
    clf = StaffClassifier()
    ts = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)

    for idx, zone in enumerate(["A", "B", "C", "D", "E"]):
        clf.update(2, zone, ts + timedelta(minutes=idx), None, (0, 0, 10, 10))

    assert clf.get_score(2) >= 0.6


def test_uniform_color_score_handles_empty_crop():
    clf = StaffClassifier()
    frame = np.zeros((5, 5, 3), dtype=np.uint8)

    assert clf._uniform_color_score(frame, (20, 20, 30, 30)) == 0.0


def test_build_event_sets_required_schema():
    ts = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)

    event = build_event(
        "ENTRY",
        "STORE_BLR_002",
        "CAM_3",
        "VIS_123",
        ts,
        None,
        0,
        False,
        0.98765,
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    )

    assert event["confidence"] == 0.9877
    assert event["timestamp"] == "2026-06-04T10:00:00Z"
    assert event["metadata"]["session_seq"] == 0


class FakeResponse:
    status_code = 200


class FakeClient:
    def __init__(self):
        self.posts = []
        self.closed = False

    async def post(self, *args, **kwargs):
        self.posts.append((args, kwargs))
        return FakeResponse()

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_event_emitter_flushes_buffer(monkeypatch):
    client = FakeClient()

    class ClientFactory:
        def __init__(self, *_, **__):
            pass

        def __call__(self, *_, **__):
            return client

    monkeypatch.setattr("pipeline.emit.httpx.AsyncClient", ClientFactory())
    emitter = EventEmitter(api_url="http://api", buffer_seconds=100)

    async with emitter:
        emitter.queue({"event_id": "1"})
        await emitter.flush_all()

    assert len(client.posts) == 1
    assert client.posts[0][1]["json"] == {"events": [{"event_id": "1"}]}
    assert client.closed
