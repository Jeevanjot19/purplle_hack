# PROMPT:
#   "Write exhaustive pytest tests for an event schema defined with Pydantic v2.
#    The schema has 8 event types, UUID v4 validation, UTC timestamp enforcement,
#    zone_id null rules per event type, queue_depth rules for BILLING_QUEUE_JOIN,
#    dwell_ms = 0 for instantaneous events, visitor_id must start with VIS_,
#    confidence in [0,1], and extra fields are forbidden."
#
# CHANGES MADE:
#   - Added specific error message assertions (not just 'raises ValueError')
#   - Added boundary tests for confidence (0.0, 1.0, 0.001, 0.999 all valid)
#   - Added test for lowercase normalisation of event_id
#   - Added test that low-confidence events (e.g. 0.03) are valid — schema never
#     suppresses low confidence, that is a detection pipeline concern
#   - Removed AI's suggestion to test session_seq < 0 as invalid because the
#     pipeline starts seq at 0 on ENTRY and 0 is valid

import pytest
from datetime import datetime, timezone, timedelta
from pydantic import ValidationError

from app.models import Event, EventMetadata, IngestPayload, new_event_id, new_visitor_id


def make_event(**overrides) -> dict:
    """Return a minimal valid ENTRY event dict, with optional overrides."""
    base = {
        "event_id": new_event_id(),
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM_ENTRY_01",
        "visitor_id": new_visitor_id(),
        "event_type": "ENTRY",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "zone_id": None,
        "dwell_ms": 0,
        "is_staff": False,
        "confidence": 0.91,
        "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 1},
    }
    base.update(overrides)
    return base


class TestValidEvents:
    def test_entry_event(self):
        e = Event.model_validate(make_event(event_type="ENTRY", zone_id=None))
        assert e.event_type == "ENTRY"
        assert e.zone_id is None
        assert e.dwell_ms == 0

    def test_exit_event(self):
        e = Event.model_validate(make_event(event_type="EXIT", zone_id=None))
        assert e.event_type == "EXIT"

    def test_reentry_event(self):
        e = Event.model_validate(make_event(event_type="REENTRY", zone_id=None))
        assert e.event_type == "REENTRY"

    def test_zone_enter_event(self):
        e = Event.model_validate(make_event(event_type="ZONE_ENTER", zone_id="SKINCARE", dwell_ms=0))
        assert e.zone_id == "SKINCARE"

    def test_zone_exit_event(self):
        e = Event.model_validate(make_event(event_type="ZONE_EXIT", zone_id="SKINCARE", dwell_ms=0))
        assert e.event_type == "ZONE_EXIT"

    def test_zone_dwell_event(self):
        e = Event.model_validate(make_event(event_type="ZONE_DWELL", zone_id="HAIRCARE", dwell_ms=30000))
        assert e.dwell_ms == 30000

    def test_billing_queue_join(self):
        e = Event.model_validate(make_event(
            event_type="BILLING_QUEUE_JOIN",
            zone_id="BILLING",
            dwell_ms=0,
            metadata={"queue_depth": 3, "session_seq": 5},
        ))
        assert e.metadata.queue_depth == 3

    def test_billing_queue_abandon(self):
        e = Event.model_validate(make_event(event_type="BILLING_QUEUE_ABANDON", zone_id="BILLING", dwell_ms=0))
        assert e.event_type == "BILLING_QUEUE_ABANDON"

    def test_is_staff_true(self):
        e = Event.model_validate(make_event(is_staff=True))
        assert e.is_staff is True

    def test_confidence_boundaries(self):
        for conf in [0.0, 0.001, 0.5, 0.999, 1.0]:
            e = Event.model_validate(make_event(confidence=conf))
            assert e.confidence == conf

    def test_low_confidence_not_suppressed(self):
        e = Event.model_validate(make_event(confidence=0.03))
        assert e.confidence == pytest.approx(0.03)

    def test_event_id_normalised_to_lowercase(self):
        raw_id = new_event_id().upper()
        e = Event.model_validate(make_event(event_id=raw_id))
        assert e.event_id == raw_id.lower()

    def test_metadata_extra_fields_ignored(self):
        e = Event.model_validate(make_event(metadata={"queue_depth": None, "session_seq": 1, "debug_frame": 420}))
        assert e.metadata.session_seq == 1

    def test_to_db_dict_flat(self):
        e = Event.model_validate(make_event(
            event_type="BILLING_QUEUE_JOIN",
            zone_id="BILLING",
            dwell_ms=0,
            metadata={"queue_depth": 2, "sku_zone": "LIPSTICK", "session_seq": 4},
        ))
        d = e.to_db_dict()
        assert d["queue_depth"] == 2
        assert d["sku_zone"] == "LIPSTICK"
        assert d["session_seq"] == 4
        assert "metadata" not in d


class TestEventId:
    def test_rejects_non_uuid(self):
        with pytest.raises(ValidationError, match="UUID v4"):
            Event.model_validate(make_event(event_id="not-a-uuid"))

    def test_rejects_uuid_v1(self):
        with pytest.raises(ValidationError):
            Event.model_validate(make_event(event_id="550e8400-e29b-11d4-a716-446655440000"))

    def test_rejects_uuid_v3(self):
        with pytest.raises(ValidationError):
            Event.model_validate(make_event(event_id="550e8400-e29b-31d4-a716-446655440000"))

    def test_rejects_empty_string(self):
        with pytest.raises(ValidationError):
            Event.model_validate(make_event(event_id=""))

    def test_valid_uuid4_accepted(self):
        valid = "550e8400-e29b-41d4-a716-446655440000"
        e = Event.model_validate(make_event(event_id=valid))
        assert e.event_id == valid.lower()


class TestTimestamp:
    def test_rejects_naive_datetime(self):
        with pytest.raises(ValidationError, match="timezone-aware"):
            Event.model_validate(make_event(timestamp=datetime.now()))

    def test_accepts_utc_datetime(self):
        ts = datetime.now(timezone.utc)
        e = Event.model_validate(make_event(timestamp=ts))
        assert e.timestamp.tzinfo is not None

    def test_accepts_iso_string_with_z(self):
        e = Event.model_validate(make_event(timestamp="2026-03-03T14:22:10Z"))
        assert e.timestamp is not None

    def test_accepts_iso_string_with_offset(self):
        e = Event.model_validate(make_event(timestamp="2026-03-03T14:22:10+00:00"))
        assert e.timestamp is not None


class TestVisitorId:
    def test_rejects_missing_vis_prefix(self):
        with pytest.raises(ValidationError, match="VIS_"):
            Event.model_validate(make_event(visitor_id="customer_123"))

    def test_rejects_empty(self):
        with pytest.raises(ValidationError):
            Event.model_validate(make_event(visitor_id=""))

    def test_accepts_vis_prefix(self):
        vid = new_visitor_id()
        e = Event.model_validate(make_event(visitor_id=vid))
        assert e.visitor_id == vid


class TestZoneIdRules:
    @pytest.mark.parametrize("event_type", ["ENTRY", "EXIT", "REENTRY"])
    def test_entry_exit_reentry_must_have_null_zone(self, event_type):
        with pytest.raises(ValidationError, match="zone_id=null"):
            Event.model_validate(make_event(event_type=event_type, zone_id="SKINCARE"))

    @pytest.mark.parametrize("event_type", ["ZONE_ENTER", "ZONE_EXIT", "ZONE_DWELL"])
    def test_zone_events_require_zone_id(self, event_type):
        dwell = 30000 if event_type == "ZONE_DWELL" else 0
        with pytest.raises(ValidationError, match="require a non-null zone_id"):
            Event.model_validate(make_event(event_type=event_type, zone_id=None, dwell_ms=dwell))

    def test_billing_queue_join_with_zone_id(self):
        e = Event.model_validate(make_event(
            event_type="BILLING_QUEUE_JOIN",
            zone_id="BILLING",
            dwell_ms=0,
            metadata={"queue_depth": 1, "session_seq": 3},
        ))
        assert e.zone_id == "BILLING"


class TestBillingQueueJoin:
    def test_requires_queue_depth_gte_1(self):
        with pytest.raises(ValidationError, match="queue_depth"):
            Event.model_validate(make_event(
                event_type="BILLING_QUEUE_JOIN",
                zone_id="BILLING",
                dwell_ms=0,
                metadata={"queue_depth": None, "session_seq": 1},
            ))

    def test_rejects_queue_depth_zero(self):
        with pytest.raises(ValidationError):
            Event.model_validate(make_event(
                event_type="BILLING_QUEUE_JOIN",
                zone_id="BILLING",
                dwell_ms=0,
                metadata={"queue_depth": 0, "session_seq": 1},
            ))

    def test_accepts_queue_depth_1(self):
        e = Event.model_validate(make_event(
            event_type="BILLING_QUEUE_JOIN",
            zone_id="BILLING",
            dwell_ms=0,
            metadata={"queue_depth": 1, "session_seq": 1},
        ))
        assert e.metadata.queue_depth == 1


class TestDwellMs:
    @pytest.mark.parametrize("event_type", ["ENTRY", "EXIT", "REENTRY", "ZONE_ENTER", "BILLING_QUEUE_JOIN", "BILLING_QUEUE_ABANDON"])
    def test_instantaneous_events_require_zero_dwell(self, event_type):
        kwargs = {"event_type": event_type, "dwell_ms": 10}
        if event_type in {"ENTRY", "EXIT", "REENTRY"}:
            kwargs["zone_id"] = None
        else:
            kwargs["zone_id"] = "BILLING" if "BILLING" in event_type else "SKINCARE"
        if event_type == "BILLING_QUEUE_JOIN":
            kwargs["metadata"] = {"queue_depth": 1, "session_seq": 1}
        with pytest.raises(ValidationError, match="instantaneous"):
            Event.model_validate(make_event(**kwargs))

    def test_zone_dwell_can_have_positive_dwell(self):
        e = Event.model_validate(make_event(event_type="ZONE_DWELL", zone_id="SKINCARE", dwell_ms=30000))
        assert e.dwell_ms == 30000

    def test_negative_dwell_rejected(self):
        with pytest.raises(ValidationError):
            Event.model_validate(make_event(event_type="ZONE_DWELL", zone_id="SKINCARE", dwell_ms=-1))


class TestConfidence:
    def test_rejects_confidence_less_than_zero(self):
        with pytest.raises(ValidationError):
            Event.model_validate(make_event(confidence=-0.01))

    def test_rejects_confidence_greater_than_one(self):
        with pytest.raises(ValidationError):
            Event.model_validate(make_event(confidence=1.01))

    def test_accepts_float_confidence(self):
        e = Event.model_validate(make_event(confidence=0.732))
        assert e.confidence == pytest.approx(0.732)


class TestMetadata:
    def test_metadata_defaults(self):
        raw = make_event()
        del raw["metadata"]
        e = Event.model_validate(raw)
        assert e.metadata.queue_depth is None
        assert e.metadata.sku_zone is None
        assert e.metadata.session_seq == 0

    def test_metadata_queue_depth_negative_rejected(self):
        with pytest.raises(ValidationError):
            EventMetadata.model_validate({"queue_depth": -1})

    def test_metadata_session_seq_zero_valid(self):
        m = EventMetadata.model_validate({"session_seq": 0})
        assert m.session_seq == 0

    def test_metadata_session_seq_negative_rejected(self):
        with pytest.raises(ValidationError):
            EventMetadata.model_validate({"session_seq": -1})


class TestExtraFields:
    def test_top_level_extra_forbidden(self):
        raw = make_event()
        raw["unexpected"] = "boom"
        with pytest.raises(ValidationError):
            Event.model_validate(raw)

    def test_metadata_extra_ignored(self):
        raw = make_event(metadata={"queue_depth": None, "session_seq": 1, "extra": "ok"})
        e = Event.model_validate(raw)
        assert not hasattr(e.metadata, "extra")


class TestIngestPayload:
    def test_payload_accepts_one_event(self):
        payload = IngestPayload.model_validate({"events": [make_event()]})
        assert len(payload.events) == 1

    def test_payload_rejects_empty_events(self):
        with pytest.raises(ValidationError):
            IngestPayload.model_validate({"events": []})

    def test_payload_rejects_more_than_500(self):
        with pytest.raises(ValidationError):
            IngestPayload.model_validate({"events": [make_event() for _ in range(501)]})

    def test_payload_accepts_exactly_500(self):
        payload = IngestPayload.model_validate({"events": [make_event() for _ in range(500)]})
        assert len(payload.events) == 500


class TestUniqueHelpers:
    def test_event_ids_are_unique(self):
        ids = {new_event_id() for _ in range(1000)}
        assert len(ids) == 1000

    def test_visitor_ids_are_unique(self):
        ids = {new_visitor_id() for _ in range(1000)}
        assert len(ids) == 1000
