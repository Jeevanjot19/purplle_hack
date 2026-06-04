"""
Load POS CSV rows and post them to /pos/load.

Supports both the original invoice_number schema and the challenge CSV schema:
order_id, order_date, order_time, store_id, total_amount.
"""

import csv
from datetime import datetime, timezone
from pathlib import Path

import httpx
import structlog

logger = structlog.get_logger()


def parse_pos_row(row: dict) -> dict | None:
    try:
        transaction_id = (row.get("invoice_number") or row.get("order_id") or "").strip()
        store_id = (row.get("store_id") or "").strip()
        if not transaction_id or not store_id:
            return None

        timestamp = _parse_timestamp(row)
        if timestamp is None:
            return None

        amount_raw = row.get("total_amount") or row.get("basket_value") or ""
        basket_value = float(str(amount_raw).replace(",", "").strip())

        return {
            "transaction_id": transaction_id,
            "store_id": store_id,
            "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
            "basket_value": basket_value,
        }
    except Exception:
        return None


def _parse_timestamp(row: dict) -> datetime | None:
    combined = (row.get("timestamp") or row.get("order_timestamp") or "").strip()
    if combined:
        try:
            parsed = datetime.fromisoformat(combined.replace("Z", "+00:00"))
            return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    date_str = (row.get("order_date") or "").strip()
    time_str = (row.get("order_time") or "00:00:00").strip()
    for date_fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        for time_fmt in ("%H:%M:%S", "%H:%M"):
            try:
                parsed = datetime.strptime(f"{date_str} {time_str}", f"{date_fmt} {time_fmt}")
                return parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


async def load_pos(csv_path: str, api_url: str = "http://api:8000") -> dict:
    if not Path(csv_path).exists():
        logger.warning("pos_csv_not_found", path=csv_path)
        return {"parsed": 0, "skipped": 0, "duplicates": 0, "loaded": 0}

    seen: set[str] = set()
    rows = []
    skipped = 0
    duplicates = 0

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            parsed = parse_pos_row(row)
            if not parsed:
                skipped += 1
                continue
            if parsed["transaction_id"] in seen:
                duplicates += 1
                continue
            seen.add(parsed["transaction_id"])
            rows.append(parsed)

    logger.info("pos_parsed", parsed=len(rows), skipped=skipped, duplicates=duplicates)
    if not rows:
        return {"parsed": 0, "skipped": skipped, "duplicates": duplicates, "loaded": 0}

    loaded = 0
    async with httpx.AsyncClient(timeout=30.0) as client:
        for i in range(0, len(rows), 500):
            batch = rows[i:i + 500]
            try:
                resp = await client.post(f"{api_url}/pos/load", json={"transactions": batch})
                if resp.status_code < 400:
                    loaded += resp.json().get("loaded", 0)
                logger.info(
                    "pos_batch_loaded",
                    batch=i // 500 + 1,
                    count=len(batch),
                    status=resp.status_code,
                )
            except Exception as exc:
                logger.error("pos_load_failed", error=str(exc), batch=i // 500 + 1)

    return {"parsed": len(rows), "skipped": skipped, "duplicates": duplicates, "loaded": loaded}
