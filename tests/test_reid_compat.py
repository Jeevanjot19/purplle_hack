# PROMPT: Add ReID compatibility tests for Claude-style edge-case expectations.
# CHANGES MADE: Added alias, TTL, cross-camera duplicate, same-camera, and zero-vector cosine coverage.

from datetime import datetime, timedelta, timezone

import numpy as np

from pipeline.reid import ReIDGallery


def test_reentry_match_within_15_minutes_via_alias():
    gallery = ReIDGallery()
    ts = datetime.now(timezone.utc)
    embedding = np.ones(96, dtype=np.float32)

    gallery.on_exit("VIS_abc123", embedding, "CAM_3", ts)

    assert gallery.find_reentry(embedding, ts + timedelta(minutes=14)) == "VIS_abc123"


def test_no_reentry_after_ttl_expiry():
    gallery = ReIDGallery()
    ts = datetime.now(timezone.utc)
    embedding = np.ones(96, dtype=np.float32)

    gallery.on_exit("VIS_abc123", embedding, "CAM_3", ts)

    assert gallery.find_reentry(embedding, ts + timedelta(minutes=16)) is None


def test_cross_camera_duplicate_within_30_seconds_via_alias():
    gallery = ReIDGallery()
    ts = datetime.now(timezone.utc)
    embedding = np.ones(96, dtype=np.float32)

    gallery.on_entry("VIS_abc123", embedding, "CAM_3", ts)

    assert gallery.find_cross_cam_dup(embedding, "CAM_1", ts + timedelta(seconds=20)) == "VIS_abc123"


def test_same_camera_is_not_deduped():
    gallery = ReIDGallery()
    ts = datetime.now(timezone.utc)
    embedding = np.ones(96, dtype=np.float32)

    gallery.on_entry("VIS_abc123", embedding, "CAM_3", ts)

    assert gallery.find_cross_cam_dup(embedding, "CAM_3", ts + timedelta(seconds=20)) is None


def test_zero_vector_cosine_returns_zero():
    assert ReIDGallery._cosine(np.zeros(96), np.ones(96)) == 0.0
