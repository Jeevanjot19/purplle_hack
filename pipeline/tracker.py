"""
pipeline/tracker.py
────────────────────
GlobalSessionRegistry

Maps BoT-SORT track_id (resets each clip) → visitor_id (permanent UUID).
Handles ENTRY/EXIT/REENTRY events and cross-camera deduplication.

One instance shared across all 3 cameras for a single store.
Thread-safe: asyncio single-threaded model — no locks needed.
"""
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field

import numpy as np

from pipeline.reid import ReIDGallery
from pipeline.emit import build_event


@dataclass
class ActiveSession:
    visitor_id:       str
    camera_id:        str
    entry_time:       datetime
    last_zone:        str | None = None
    zone_entry_time:  datetime | None = None
    last_dwell_emit:  datetime | None = None
    in_billing:       bool = False
    session_seq:      int  = 0
    last_embedding:   np.ndarray | None = None
    confidence:       float = 1.0


class GlobalSessionRegistry:
    """
    One instance per store per pipeline run.
    """

    def __init__(self, store_id: str):
        self.store_id = store_id
        self._active:  dict[int, ActiveSession] = {}  # track_id → session
        self._gallery  = ReIDGallery()
        self._billing_count = 0   # current people in billing zone

    # ────────────────────────────────────────────────────────────
    # Called by detect.py on every tracked person every frame
    # ────────────────────────────────────────────────────────────

    def process(
        self,
        track_id:  int,
        bbox:      tuple,
        zone:      str | None,
        frame:     np.ndarray,
        frame_ts:  datetime,
        conf:      float,
        camera_id: str,
        is_staff:  bool,
        is_entry_camera: bool = False,
    ) -> list[dict]:
        """
        Returns list of events to emit for this track on this frame.
        
        is_entry_camera: If True, this is the entry/exit camera and ENTRY/EXIT events
                        will be emitted. If False (floor camera), only ZONE events are emitted.
        """
        events = []

        if track_id not in self._active:
            # New track — ENTRY or REENTRY or cross-cam dup (only on entry camera)
            embedding = ReIDGallery.extract_embedding(frame, bbox)

            # Check cross-camera dedup first
            dup_vid = self._gallery.find_cross_cam_dup(embedding, camera_id, frame_ts)
            if dup_vid:
                # Suppress — link to existing session
                self._active[track_id] = ActiveSession(
                    visitor_id=dup_vid,
                    camera_id=camera_id,
                    entry_time=frame_ts,
                    confidence=conf,
                )
                # Don't emit a new ENTRY
                return events

            # ── Only emit ENTRY/REENTRY events on entry camera ──
            if is_entry_camera:
                # Check re-entry
                reentry_vid = self._gallery.find_reentry(embedding, frame_ts)
                if reentry_vid:
                    visitor_id = reentry_vid
                    event_type = "REENTRY"
                else:
                    visitor_id = f"VIS_{uuid.uuid4().hex[:6]}"
                    event_type = "ENTRY"

                session = ActiveSession(
                    visitor_id=visitor_id,
                    camera_id=camera_id,
                    entry_time=frame_ts,
                    last_embedding=embedding,
                    confidence=conf,
                )
                self._active[track_id] = session
                self._gallery.add_active(visitor_id, embedding, camera_id, frame_ts)

                entry_event = build_event(
                    event_type=event_type,
                    store_id=self.store_id,
                    camera_id=camera_id,
                    visitor_id=visitor_id,
                    timestamp=frame_ts,
                    zone_id=None,
                    dwell_ms=0,
                    is_staff=is_staff,
                    confidence=conf,
                    event_id=str(uuid.uuid4()),
                    session_seq=session.session_seq,
                )
                events.append(entry_event)
                session.session_seq += 1
            else:
                # Floor camera: create session silently (assume person already entered via entry cam)
                visitor_id = f"VIS_{uuid.uuid4().hex[:6]}"
                session = ActiveSession(
                    visitor_id=visitor_id,
                    camera_id=camera_id,
                    entry_time=frame_ts,
                    last_embedding=embedding,
                    confidence=conf,
                )
                self._active[track_id] = session
                self._gallery.add_active(visitor_id, embedding, camera_id, frame_ts)
                # No ENTRY event emitted for floor cameras

        session = self._active[track_id]
        session.confidence = conf

        # ── Zone change detection ──────────────────────────────
        if zone != session.last_zone:
            # Exit old zone
            if session.last_zone is not None:
                dwell_ms = 0
                if session.zone_entry_time:
                    dwell_ms = int(
                        (frame_ts - session.zone_entry_time).total_seconds() * 1000
                    )
                events.append(build_event(
                    event_type="ZONE_EXIT",
                    store_id=self.store_id,
                    camera_id=camera_id,
                    visitor_id=session.visitor_id,
                    timestamp=frame_ts,
                    zone_id=session.last_zone,
                    dwell_ms=dwell_ms,
                    is_staff=is_staff,
                    confidence=conf,
                    event_id=str(uuid.uuid4()),
                    session_seq=session.session_seq,
                ))
                session.session_seq += 1

                # Handle billing zone exit
                if "billing" in session.last_zone.lower() and session.in_billing:
                    session.in_billing = False
                    if self._billing_count > 0:
                        self._billing_count -= 1

            # Enter new zone
            if zone is not None:
                events.append(build_event(
                    event_type="ZONE_ENTER",
                    store_id=self.store_id,
                    camera_id=camera_id,
                    visitor_id=session.visitor_id,
                    timestamp=frame_ts,
                    zone_id=zone,
                    dwell_ms=0,
                    is_staff=is_staff,
                    confidence=conf,
                    event_id=str(uuid.uuid4()),
                    session_seq=session.session_seq,
                ))
                session.session_seq += 1

                # Handle billing zone entry
                if "billing" in zone.lower() and not session.in_billing:
                    session.in_billing = True
                    self._billing_count += 1
                    if self._billing_count > 1 and not is_staff:
                        # There's already someone in billing — this person joins queue
                        events.append(build_event(
                            event_type="BILLING_QUEUE_JOIN",
                            store_id=self.store_id,
                            camera_id=camera_id,
                            visitor_id=session.visitor_id,
                            timestamp=frame_ts,
                            zone_id=zone,
                            dwell_ms=0,
                            is_staff=is_staff,
                            confidence=conf,
                            event_id=str(uuid.uuid4()),
                            queue_depth=self._billing_count - 1,
                            session_seq=session.session_seq,
                        ))
                        session.session_seq += 1

            session.last_zone       = zone
            session.zone_entry_time = frame_ts
            session.last_dwell_emit = None

        # ── ZONE_DWELL every 30 seconds ────────────────────────
        if zone and session.zone_entry_time:
            secs_in_zone = (frame_ts - session.zone_entry_time).total_seconds()
            last_emit_secs = (
                (frame_ts - session.last_dwell_emit).total_seconds()
                if session.last_dwell_emit else secs_in_zone
            )
            if secs_in_zone >= 30 and last_emit_secs >= 30:
                events.append(build_event(
                    event_type="ZONE_DWELL",
                    store_id=self.store_id,
                    camera_id=camera_id,
                    visitor_id=session.visitor_id,
                    timestamp=frame_ts,
                    zone_id=zone,
                    dwell_ms=int(secs_in_zone * 1000),
                    is_staff=is_staff,
                    confidence=conf,
                    event_id=str(uuid.uuid4()),
                    sku_zone=zone,
                    session_seq=session.session_seq,
                ))
                session.session_seq += 1
                session.last_dwell_emit = frame_ts

        return events

    def handle_lost_track(
        self,
        track_id:  int,
        frame_ts:  datetime,
        frame:     np.ndarray | None,
        is_staff:  bool,
        is_entry_camera: bool = False,
    ) -> list[dict]:
        """
        Called when BoT-SORT drops a track.
        Only emits EXIT event if is_entry_camera=True (entry camera detects exits).
        """
        if track_id not in self._active:
            return []

        session = self._active.pop(track_id)

        # Add to re-entry gallery
        if session.last_embedding is not None:
            self._gallery.add_exit(
                session.visitor_id,
                session.last_embedding,
                session.camera_id,
                frame_ts,
            )

        # Decrement billing count if they were in billing
        if session.in_billing and self._billing_count > 0:
            self._billing_count -= 1

        # Only emit EXIT event on entry camera
        if not is_entry_camera:
            return []

        return [build_event(
            event_type="EXIT",
            store_id=self.store_id,
            camera_id=session.camera_id,
            visitor_id=session.visitor_id,
            timestamp=frame_ts,
            zone_id=None,
            dwell_ms=0,
            is_staff=is_staff,
            confidence=session.confidence,
            event_id=str(uuid.uuid4()),
            session_seq=session.session_seq,
        )]

    def get_active_track_ids(self) -> set[int]:
        return set(self._active.keys())
