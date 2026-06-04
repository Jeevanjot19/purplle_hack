#!/usr/bin/env python
"""Export internal API events to the challenge submission JSONL schema.

The organizer email asks for an event log in JSONL format following the provided
sample_events.jsonl style. This script converts our internal event schema into a
submission-friendly JSONL file with one JSON object per line.
"""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from typing import Any


INTERNAL_TO_SUBMISSION = {
    "ENTRY": "entry",
    "EXIT": "exit",
    "REENTRY": "entry",
    "ZONE_ENTER": "zone_entered",
    "ZONE_EXIT": "zone_exited",
    "ZONE_DWELL": "zone_entered",
    "BILLING_QUEUE_JOIN": "queue_completed",
    "BILLING_QUEUE_ABANDON": "queue_abandoned",
}

BILLING_MARKERS = ("BILLING", "CASH", "CHECKOUT", "QUEUE")


def load_layout(path: str = "data/store_layout.json") -> dict[str, dict[str, Any]]:
    layout_path = Path(path)
    if not layout_path.exists():
        return {}
    try:
        raw = json.loads(layout_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    zones: dict[str, dict[str, Any]] = {}
    for store in raw.get("stores", {}).values():
        for camera in store.get("cameras", {}).values():
            for zone in camera.get("zones", []):
                zone_id = zone.get("id") or zone.get("zone_id")
                if not zone_id:
                    continue
                polygon = zone.get("polygon") or []
                hotspot_x = hotspot_y = None
                if polygon:
                    hotspot_x = round(sum(p[0] for p in polygon) / len(polygon), 2)
                    hotspot_y = round(sum(p[1] for p in polygon) / len(polygon), 2)
                zones[zone_id] = {
                    "zone_name": zone.get("label") or zone_id,
                    "zone_type": "BILLING" if zone.get("is_billing") else "SHELF",
                    "is_revenue_zone": "Yes" if not zone.get("is_entry") else "No",
                    "zone_hotspot_x": hotspot_x,
                    "zone_hotspot_y": hotspot_y,
                }
    return zones


def iter_internal_events(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []

    # Supports either {"events": [...]} JSON or JSONL.
    if text.startswith("{"):
        data = json.loads(text)
        events = data.get("events", []) if isinstance(data, dict) else []
        return [e for e in events if isinstance(e, dict)]

    events = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Invalid JSON on line {line_no}: {exc}") from exc
        if isinstance(obj, dict):
            events.append(obj)
    return events


def event_time(event: dict[str, Any]) -> str:
    return str(event.get("timestamp") or event.get("event_timestamp") or event.get("event_time") or "")


def zone_info(zone_id: str | None, layout: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if zone_id and zone_id in layout:
        return layout[zone_id]
    upper = (zone_id or "").upper()
    is_billing = any(marker in upper for marker in BILLING_MARKERS)
    return {
        "zone_name": zone_id or None,
        "zone_type": "BILLING" if is_billing else "SHELF",
        "is_revenue_zone": "Yes" if zone_id else "No",
        "zone_hotspot_x": None,
        "zone_hotspot_y": None,
    }


def base_identity(event: dict[str, Any]) -> dict[str, Any]:
    visitor_id = event.get("visitor_id") or event.get("id_token") or event.get("track_id") or f"VIS_{uuid.uuid4().hex[:6]}"
    return {
        "track_id": visitor_id,
        "id_token": visitor_id,
        "store_id": event.get("store_id") or event.get("store_code") or "STORE_BLR_002",
        "store_code": event.get("store_id") or event.get("store_code") or "STORE_BLR_002",
        "camera_id": event.get("camera_id") or "CAM_ENTRY_01",
    }


def to_submission_event(event: dict[str, Any], layout: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    internal_type = str(event.get("event_type", "ENTRY")).upper()
    event_type = INTERNAL_TO_SUBMISSION.get(internal_type)
    if not event_type:
        return None

    identity = base_identity(event)
    zone_id = event.get("zone_id")
    zinfo = zone_info(zone_id, layout)
    is_staff = bool(event.get("is_staff", False))

    if event_type in {"entry", "exit"}:
        return {
            "event_type": event_type,
            "id_token": identity["id_token"],
            "store_code": identity["store_code"],
            "camera_id": identity["camera_id"],
            "event_timestamp": event_time(event),
            "is_staff": is_staff,
            "gender_pred": None,
            "age_pred": None,
            "age_bucket": None,
            "is_face_hidden": True,
            "group_id": event.get("group_id"),
            "group_size": event.get("group_size"),
        }

    if event_type in {"zone_entered", "zone_exited"}:
        return {
            "event_type": event_type,
            "track_id": identity["track_id"],
            "store_id": identity["store_id"],
            "camera_id": identity["camera_id"],
            "zone_id": zone_id,
            "zone_name": zinfo["zone_name"],
            "zone_type": zinfo["zone_type"],
            "is_revenue_zone": zinfo["is_revenue_zone"],
            "event_time": event_time(event),
            "zone_hotspot_x": zinfo["zone_hotspot_x"],
            "zone_hotspot_y": zinfo["zone_hotspot_y"],
            "gender": None,
            "age": None,
            "age_bucket": None,
        }

    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    queue_depth = metadata.get("queue_depth") or event.get("queue_depth") or 1
    abandoned = event_type == "queue_abandoned"
    ts = event_time(event)
    return {
        "queue_event_id": event.get("event_id") or str(uuid.uuid4()),
        "event_type": event_type,
        "track_id": identity["track_id"],
        "store_id": identity["store_id"],
        "camera_id": identity["camera_id"],
        "zone_id": zone_id or "BILLING_QUEUE",
        "zone_name": zinfo["zone_name"] or "Billing Queue",
        "zone_type": "BILLING",
        "is_revenue_zone": "Yes",
        "queue_join_ts": ts,
        "queue_served_ts": None if abandoned else ts,
        "queue_exit_ts": ts,
        "wait_seconds": int(event.get("wait_seconds") or max(int(event.get("dwell_ms", 0)) // 1000, 0)),
        "queue_position_at_join": int(queue_depth),
        "abandoned": abandoned,
        "zone_hotspot_x": zinfo["zone_hotspot_x"],
        "zone_hotspot_y": zinfo["zone_hotspot_y"],
        "gender": None,
        "age": None,
        "age_bucket": None,
    }


def export_event_log(input_path: Path, output_path: Path, layout_path: str = "data/store_layout.json") -> int:
    layout = load_layout(layout_path)
    events = iter_internal_events(input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output_path.open("w", encoding="utf-8") as out:
        for event in events:
            converted = to_submission_event(event, layout)
            if converted is None:
                continue
            out.write(json.dumps(converted, separators=(",", ":")) + "\n")
            count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Export submission-ready event_log.jsonl")
    parser.add_argument("--input", default="data/sample_ingest_events.json")
    parser.add_argument("--output", default="submission/event_log.jsonl")
    parser.add_argument("--layout", default="data/store_layout.json")
    args = parser.parse_args()

    count = export_event_log(Path(args.input), Path(args.output), args.layout)
    print(f"exported={count} output={args.output}")


if __name__ == "__main__":
    main()
