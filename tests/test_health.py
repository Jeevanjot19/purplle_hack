# PROMPT: Verify health status objects expose feed freshness in the structure expected by evaluators.
# CHANGES MADE: Added unit coverage for store health status including stale-feed detection fields.

from datetime import datetime, timedelta, timezone

from app.routers.health import _store_status


def test_health_returns_valid_store_structure():
    recent = datetime.now(timezone.utc).isoformat()

    status = _store_status(recent)

    assert set(status) == {"last_event", "lag_seconds", "feed_status"}
    assert status["feed_status"] == "ok"


def test_health_marks_stale_feed():
    old = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()

    status = _store_status(old)

    assert status["feed_status"] == "STALE_FEED"
