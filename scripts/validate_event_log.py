#!/usr/bin/env python
"""Validate challenge submission event_log.jsonl.

This intentionally validates the organizer-facing JSONL schema, not the internal
API ingest schema. It checks valid JSONL, required fields by event_type, and
prints event counts so the file can be sanity-checked before submission.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

REQUIRED = {
    "entry": [
        "event_type", "id_token", "store_code", "camera_id", "event_timestamp",
        "is_staff", "is_face_hidden",
    ],
    "exit": [
        "event_type", "id_token", "store_code", "camera_id", "event_timestamp",
        "is_staff", "is_face_hidden",
    ],
    "zone_entered": [
        "event_type", "track_id", "store_id", "camera_id", "zone_id",
        "zone_name", "zone_type", "is_revenue_zone", "event_time",
    ],
    "zone_exited": [
        "event_type", "track_id", "store_id", "camera_id", "zone_id",
        "zone_name", "zone_type", "is_revenue_zone", "event_time",
    ],
    "queue_completed": [
        "queue_event_id", "event_type", "track_id", "store_id", "camera_id",
        "zone_id", "zone_name", "zone_type", "queue_join_ts", "queue_served_ts",
        "queue_exit_ts", "wait_seconds", "queue_position_at_join", "abandoned",
    ],
    "queue_abandoned": [
        "queue_event_id", "event_type", "track_id", "store_id", "camera_id",
        "zone_id", "zone_name", "zone_type", "queue_join_ts", "queue_exit_ts",
        "wait_seconds", "queue_position_at_join", "abandoned",
    ],
}


def validate_event(event: dict[str, Any], line_no: int) -> list[str]:
    errors = []
    event_type = event.get("event_type")
    if event_type not in REQUIRED:
        return [f"line {line_no}: unsupported event_type={event_type!r}"]

    for field in REQUIRED[event_type]:
        if field not in event:
            errors.append(f"line {line_no}: missing required field {field!r} for {event_type}")

    if event_type in {"queue_completed", "queue_abandoned"}:
        expected_abandoned = event_type == "queue_abandoned"
        if event.get("abandoned") is not expected_abandoned:
            errors.append(f"line {line_no}: abandoned must be {expected_abandoned} for {event_type}")
        if not isinstance(event.get("wait_seconds"), int):
            errors.append(f"line {line_no}: wait_seconds must be an integer")
        if not isinstance(event.get("queue_position_at_join"), int):
            errors.append(f"line {line_no}: queue_position_at_join must be an integer")

    return errors


def validate_file(path: Path) -> int:
    errors: list[str] = []
    counts: Counter[str] = Counter()
    total = 0

    if not path.exists():
        raise SystemExit(f"File not found: {path}")

    with path.open("r", encoding="utf-8") as source:
        for line_no, line in enumerate(source, start=1):
            if not line.strip():
                continue
            total += 1
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"line {line_no}: invalid JSON: {exc}")
                continue
            if not isinstance(event, dict):
                errors.append(f"line {line_no}: expected JSON object")
                continue
            counts[event.get("event_type", "<missing>")] += 1
            errors.extend(validate_event(event, line_no))

    print(f"validated={total}")
    for event_type, count in sorted(counts.items()):
        print(f"{event_type}: {count}")

    if errors:
        print("ERRORS:")
        for error in errors[:50]:
            print(f"- {error}")
        if len(errors) > 50:
            print(f"... {len(errors) - 50} more")
        return 1

    print("event_log_valid=true")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate submission event_log.jsonl")
    parser.add_argument("path", nargs="?", default="submission/event_log.jsonl")
    args = parser.parse_args()
    raise SystemExit(validate_file(Path(args.path)))


if __name__ == "__main__":
    main()
