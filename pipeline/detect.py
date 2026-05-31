"""
pipeline/detect.py
──────────────────
Main orchestrator. Processes one CCTV clip in simulated real-time.

Frame loop:
  1. Read frame from VideoCapture
  2. Run YOLO11s.track() with BoT-SORT + ReID (persist=True)
  3. For each track: zone classify, staff classify, session events
  4. Detect lost tracks → EXIT events
  5. Buffer events → flush every 1 second to POST /events/ingest
  6. Sleep to maintain real-time pacing (speed_factor configurable)
"""
import asyncio
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np
import structlog
from ultralytics import YOLO

from pipeline.emit    import EventEmitter
from pipeline.tracker import GlobalSessionRegistry
from pipeline.staff   import StaffClassifier
from pipeline.zones   import ZoneEngine

logger = structlog.get_logger()


def get_clip_start_ts(clip_path: str) -> datetime:
    """
    Extract clip start timestamp from filename.
    Supports formats:
      - STORE_BLR_002_CAM_ENTRY_01_20260303T142000Z.mp4
      - CAM_1_20260410_201027.mp4
      - CAM_1.mp4 (uses file mtime)
    
    For real Brigade footage with burn-in timestamp, we use file mtime
    as a safe fallback when filename lacks explicit timestamp.
    """
    import re
    
    stem = Path(clip_path).stem
    
    # Try format: YYYY-MM-DD_HH-MM-SS or YYYYMMDD_HHMMSS
    match = re.search(r'(\d{8})_(\d{6})', stem)
    if match:
        try:
            return datetime.strptime(
                f"{match.group(1)}{match.group(2)}", "%Y%m%d%H%M%S"
            ).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    
    # Try format: 20260303T142000Z
    match = re.search(r'(\d{8})T(\d{6})Z', stem)
    if match:
        try:
            return datetime.strptime(
                f"{match.group(1)}{match.group(2)}", "%Y%m%d%H%M%S"
            ).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    
    # Fallback: file modification time
    # For Brigade footage recorded on 10/04/2026 20:10:27, this would match
    mtime = os.path.getmtime(clip_path)
    return datetime.fromtimestamp(mtime, tz=timezone.utc)


async def process_clip(
    clip_path:    str,
    store_id:     str,
    camera_id:    str,
    layout_path:  str  = "/data/store_layout.json",
    api_url:      str  = "http://api:8000",
    speed_factor: float = 1.0,
    model_path:   str  = "yolo11s.pt",
):
    """
    Process a single CCTV clip end-to-end.

    speed_factor:
        1.0 = real-time (1 sec of clip = 1 sec of wall time)
        5.0 = 5× faster than real-time (good for demos)
        0.0 = as fast as possible (dev/test mode)
    """
    logger.info("clip_start", clip=clip_path, store=store_id, camera=camera_id,
                speed=speed_factor)

    # ── Initialise components ──────────────────────────────────
    model       = YOLO(model_path)
    zone_engine = ZoneEngine(store_id, layout_path)
    staff_clf   = StaffClassifier()
    registry    = GlobalSessionRegistry(store_id)
    clip_start  = get_clip_start_ts(clip_path)
    
    # ── Determine camera type (entry vs floor) ─────────────────
    is_entry_camera = False
    try:
        import json
        with open(layout_path, 'r') as f:
            layout = json.load(f)
            camera_config = layout["stores"][store_id]["cameras"].get(camera_id, {})
            is_entry_camera = camera_config.get("type") == "entry_exit"
            logger.info("camera_config", camera_id=camera_id, type=camera_config.get("type"),
                       is_entry_camera=is_entry_camera)
    except Exception as e:
        logger.warning("camera_type_detection_failed", error=str(e), camera_id=camera_id)

    cap = cv2.VideoCapture(clip_path)
    if not cap.isOpened():
        logger.error("clip_open_failed", clip=clip_path)
        return

    fps            = cap.get(cv2.CAP_PROP_FPS) or 15.0
    frame_duration = 1.0 / fps
    frame_num      = 0
    wall_start     = time.perf_counter()
    prev_track_ids: set[int] = set()

    async with EventEmitter(api_url=api_url) as emitter:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            frame_num += 1
            frame_ts = clip_start + timedelta(seconds=frame_num / fps)

            # ── Real-time pacing ───────────────────────────────
            if speed_factor > 0:
                expected_wall = (frame_num * frame_duration) / speed_factor
                elapsed_wall  = time.perf_counter() - wall_start
                sleep_time    = expected_wall - elapsed_wall
                if sleep_time > 0.002:
                    await asyncio.sleep(sleep_time)

            # ── Detection + tracking ───────────────────────────
            results = model.track(
                frame,
                persist=True,
                classes=[0],            # person only
                conf=0.25,
                iou=0.45,
                tracker="pipeline/botsort.yaml",
                verbose=False,
            )

            current_track_ids: set[int] = set()
            frame_events: list[dict] = []

            if results[0].boxes is not None and results[0].boxes.id is not None:
                boxes    = results[0].boxes.xyxy.cpu().numpy()
                track_ids = results[0].boxes.id.int().cpu().numpy()
                confs    = results[0].boxes.conf.cpu().numpy()

                for bbox, track_id, conf in zip(boxes, track_ids, confs):
                    track_id = int(track_id)
                    current_track_ids.add(track_id)

                    cx = (bbox[0] + bbox[2]) / 2
                    cy = (bbox[1] + bbox[3]) / 2
                    zone = zone_engine.get_zone(cx, cy)

                    staff_clf.update(track_id, zone, frame_ts, frame, bbox)
                    is_staff = staff_clf.is_staff(track_id)

                    events = registry.process(
                        track_id=track_id,
                        bbox=tuple(bbox),
                        zone=zone,
                        frame=frame,
                        frame_ts=frame_ts,
                        conf=float(conf),
                        camera_id=camera_id,
                        is_staff=is_staff,
                        is_entry_camera=is_entry_camera,
                    )
                    frame_events.extend(events)

            # ── Detect lost tracks → EXIT events ──────────────
            lost_ids = prev_track_ids - current_track_ids
            for lost_id in lost_ids:
                exit_events = registry.handle_lost_track(
                    track_id=lost_id,
                    frame_ts=frame_ts,
                    frame=frame,
                    is_staff=staff_clf.is_staff(lost_id),
                    is_entry_camera=is_entry_camera,
                )
                frame_events.extend(exit_events)

            prev_track_ids = current_track_ids

            # ── Queue events + flush every ~1 second ──────────
            for ev in frame_events:
                emitter.queue(ev)
            await emitter.tick()

        # End of clip — flush remaining events + close EXIT for all active tracks
        cap.release()
        now_ts = clip_start + timedelta(seconds=frame_num / fps)
        for tid in list(registry.get_active_track_ids()):
            exit_events = registry.handle_lost_track(
                track_id=tid,
                frame_ts=now_ts,
                frame=None,
                is_staff=staff_clf.is_staff(tid),
                is_entry_camera=is_entry_camera,
            )
            for ev in exit_events:
                emitter.queue(ev)

        await emitter.flush_all()

    logger.info("clip_done", clip=clip_path, frames=frame_num,
                duration_s=round(time.perf_counter() - wall_start, 1))
