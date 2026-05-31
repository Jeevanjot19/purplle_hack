"""
pipeline/staff.py
─────────────────
Staff classifier — uses two signals weighted together:

Signal 1 (weight 0.6): Movement pattern
  Staff oscillate across many zones quickly.
  Staff appear in restricted/staff zones.
  Staff are present for >60 minutes continuously.

Signal 2 (weight 0.4): Uniform color (HSV analysis)
  Extract upper-body crop, compute dominant hue.
  Compare against configured staff_uniform_hue_range.

A visitor_id's staff_score accumulates over time.
Once it crosses 0.65 → is_staff = True permanently.
"""
import cv2
import numpy as np
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class StaffState:
    zones_visited:   set   = field(default_factory=set)
    first_seen:      datetime | None = None
    last_seen:       datetime | None = None
    zone_changes:    int   = 0
    staff_score:     float = 0.0
    is_staff:        bool  = False


class StaffClassifier:
    """
    One instance per pipeline run.
    Call update() on every frame for every active track.
    Call is_staff() to query current classification.
    """

    STAFF_THRESHOLD  = 0.65
    MIN_ZONES_STAFF  = 5        # visited 5+ distinct zones → suspicious
    STAFF_DURATION_M = 60       # present 60+ minutes → likely staff
    # Hue range for common retail uniform colors (blue/navy aprons)
    # HSV hue is 0-179 in OpenCV. Blue = 100-130.
    STAFF_HUE_RANGES = [(100, 130), (0, 10), (165, 179)]  # blue, red, red-wrap

    def __init__(self, uniform_hue_ranges: list | None = None):
        self._states: dict[int, StaffState] = {}   # keyed by track_id
        if uniform_hue_ranges:
            self.STAFF_HUE_RANGES = uniform_hue_ranges

    def update(self, track_id: int, zone: str | None, frame_ts: datetime,
               frame: np.ndarray | None, bbox: tuple):
        if track_id not in self._states:
            self._states[track_id] = StaffState(first_seen=frame_ts)

        state = self._states[track_id]
        if state.is_staff:
            return   # already classified — no need to recompute

        state.last_seen = frame_ts

        # ── Signal 1: Zone diversity ───────────────────────────
        if zone and zone not in state.zones_visited:
            state.zones_visited.add(zone)
            state.zone_changes += 1

        zone_score = min(len(state.zones_visited) / self.MIN_ZONES_STAFF, 1.0)

        # ── Signal 1b: Duration ────────────────────────────────
        duration_score = 0.0
        if state.first_seen:
            minutes = (frame_ts - state.first_seen).total_seconds() / 60
            if minutes >= self.STAFF_DURATION_M:
                duration_score = 1.0
            elif minutes >= 30:
                duration_score = 0.5

        movement_score = max(zone_score, duration_score)

        # ── Signal 2: Uniform color ────────────────────────────
        color_score = 0.0
        if frame is not None:
            color_score = self._uniform_color_score(frame, bbox)

        # ── Weighted combination ───────────────────────────────
        state.staff_score = (0.6 * movement_score) + (0.4 * color_score)

        if state.staff_score >= self.STAFF_THRESHOLD:
            state.is_staff = True

    def is_staff(self, track_id: int) -> bool:
        return self._states.get(track_id, StaffState()).is_staff

    def get_score(self, track_id: int) -> float:
        return self._states.get(track_id, StaffState()).staff_score

    def _uniform_color_score(self, frame: np.ndarray, bbox: tuple) -> float:
        """Extract upper-body crop and check dominant hue against uniform ranges."""
        try:
            x1, y1, x2, y2 = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
            h = y2 - y1
            # Upper 40% of bounding box = torso/upper body
            crop = frame[y1: y1 + int(h * 0.4), x1:x2]
            if crop.size == 0:
                return 0.0

            hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
            hue_channel = hsv[:, :, 0].flatten()

            # Count pixels matching any staff hue range
            match_pixels = 0
            for lo, hi in self.STAFF_HUE_RANGES:
                match_pixels += np.sum((hue_channel >= lo) & (hue_channel <= hi))

            ratio = match_pixels / len(hue_channel) if len(hue_channel) > 0 else 0.0
            # If >40% of pixels match uniform color → strong signal
            return min(ratio / 0.4, 1.0)
        except Exception:
            return 0.0

    def cleanup_exited(self, track_id: int):
        """Call when a track exits. Preserve state for potential re-entry lookup."""
        # Don't delete — we may need state for re-entry classification
        pass
