#!/usr/bin/env python
"""
Convert legacy/sample event JSONL into the Store Intelligence API schema.
"""

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

INSTANT_EVENTS = {
    "ENTRY",
    "EXIT",
    "REENTRY",
    "ZONE_ENTER",
    "BILLING_QUEUE_JOIN",
    "BILLING_QUEUE_ABANDON",
}
EVENT_ALIASES = {
    "entry": "ENTRY",
    "exit": "EXIT",
    "reentry": "REENTRY",
    "zone_enter": "ZONE_ENTER",
    "zone_entered": "ZONE_ENTER",
    "zone_exit": "ZONE_EXIT",
    "zone_exited": "ZONE_EXIT",
    "zone_dwell": "ZONE_DWELL",
    "dwell": "ZONE_DWELL",
    "billing_queue_join": "BILLING_QUEUE_JOIN",
    "queue_join": "BILLING_QUEUE_JOIN",
    "billing_queue_abandon": "BILLING_QUEUE_ABANDON",
    "queue_abandon": "BILLING_QUEUE_ABANDON",
}


def convert_event(raw: dict) -> dict:
    event_type = normalize_event_type(raw.get("event_type", "ENTRY"))
    visitor_id = normalize_visitor_id(raw.get("visitor_id") or raw.get("id_token") or raw.get("person_id"))
    timestamp = normalize_timestamp(raw.get("event_timestamp") or raw.get("event_time") or raw.get("timestamp") or raw.get("time"))

    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    queue_depth = raw.get("queue_depth", metadata.get("queue_depth"))
    if event_type == "BILLING_QUEUE_JOIN" and not queue_depth:
        queue_depth = 1

    dwell_ms = int(raw.get("dwell_ms") or raw.get("dwell_time_ms") or 0)
    if event_type in INSTANT_EVENTS:
        dwell_ms = 0

    zone_id = raw.get("zone_id") or raw.get("zone") or raw.get("sku_zone")
    if event_type in {"ENTRY", "EXIT", "REENTRY"}:
        zone_id = None

    return {
        "event_id": normalize_event_id(raw.get("event_id") or raw.get("id")),
        "store_id": raw.get("store_id") or raw.get("store_code") or "STORE_BLR_002",
        "camera_id": raw.get("camera_id") or raw.get("camera") or "CAM_SAMPLE_01",
        "visitor_id": visitor_id,
        "event_type": event_type,
        "timestamp": timestamp,
        "zone_id": zone_id,
        "dwell_ms": dwell_ms,
        "is_staff": bool(raw.get("is_staff", False)),
        "confidence": float(raw.get("confidence", 0.75)),
        "metadata": {
            "queue_depth": queue_depth,
            "sku_zone": raw.get("sku_zone") or metadata.get("sku_zone"),
            "session_seq": int(raw.get("session_seq") or metadata.get("session_seq") or 0),
        },
    }


def normalize_event_type(value: str) -> str:
    text = str(value or "ENTRY").strip()
    return EVENT_ALIASES.get(text.lower(), text.upper())


def normalize_event_id(value: str | None) -> str:
    if value:
        try:
            parsed = uuid.UUID(str(value))
            if parsed.version == 4:
                return str(parsed)
        except ValueError:
            pass
    return str(uuid.uuid4())


def normalize_visitor_id(value: str | None) -> str:
    token = str(value or uuid.uuid4().hex[:8]).strip()
    if token.startswith("VIS_"):
        return token
    if token.startswith("ID_"):
        return f"VIS_{token[3:]}"
    safe = "".join(ch for ch in token if ch.isalnum())[:24] or uuid.uuid4().hex[:8]
    return f"VIS_{safe}"


def normalize_timestamp(value: str | None) -> str:
    if not value:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def convert_file(input_path: Path, output_path: Path) -> list[dict]:
    converted = []
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with input_path.open("r", encoding="utf-8") as source, output_path.open("w", encoding="utf-8") as dest:
        for line in source:
            if not line.strip():
                continue
            event = convert_event(json.loads(line))
            converted.append(event)
            dest.write(json.dumps(event) + "\n")
    return converted


def ingest(events: list[dict], api_url: str) -> None:
    with httpx.Client(timeout=30.0) as client:
        for i in range(0, len(events), 500):
            batch = events[i:i + 500]
            response = client.post(f"{api_url}/events/ingest", json={"events": batch})
            print(f"batch={i // 500 + 1} status={response.status_code} body={response.text}")
            response.raise_for_status()


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert sample_events.jsonl to API schema")
    parser.add_argument("--input", default="data/sample_events.jsonl")
    parser.add_argument("--output", default="data/converted_events.jsonl")
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--ingest", action="store_true")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")

    events = convert_file(input_path, Path(args.output))
    print(f"converted={len(events)} output={args.output}")
    if args.ingest and events:
        ingest(events, args.api_url)


if __name__ == "__main__":
    main()
