"""
pipeline/pos_loader.py
──────────────────────
Loads the real Brigade Bangalore POS CSV into the database.
Real column names: order_id, invoice_number, order_date, order_time,
                   total_amount, store_id
"""
import csv
import asyncio
import httpx
import structlog
from pathlib import Path
from datetime import datetime

logger = structlog.get_logger()


def parse_pos_row(row: dict) -> dict | None:
    """Convert a real POS CSV row into our DB format."""
    try:
        # Parse datetime from separate date + time columns
        date_str = row.get("order_date", "").strip()   # "10-04-2026"
        time_str = row.get("order_time", "").strip()   # "16:55:36"

        # Handle both formats: "10-04-2026" and "2026-04-10"
        for fmt in ("%d-%m-%Y", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(f"{date_str} {time_str}", f"{fmt} %H:%M:%S")
                break
            except ValueError:
                continue
        else:
            return None

        # Use invoice_number as transaction_id (deduplicate by it)
        return {
            "transaction_id": row["invoice_number"].strip(),
            "store_id":        row["store_id"].strip(),
            "timestamp":       dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "basket_value":    float(row.get("total_amount", 0) or 0),
        }
    except Exception as e:
        return None


async def load_pos(csv_path: str, api_url: str = "http://api:8000"):
    if not Path(csv_path).exists():
        logger.warning("pos_csv_not_found", path=csv_path)
        return

    seen_invoices = set()
    rows = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            parsed = parse_pos_row(row)
            if parsed and parsed["transaction_id"] not in seen_invoices:
                seen_invoices.add(parsed["transaction_id"])
                rows.append(parsed)

    if not rows:
        logger.warning("pos_no_rows_parsed", path=csv_path)
        return

    logger.info("pos_parsed", unique_transactions=len(rows))

    # POST in batches of 500
    async with httpx.AsyncClient(timeout=30.0) as client:
        for i in range(0, len(rows), 500):
            batch = rows[i:i + 500]
            try:
                resp = await client.post(
                    f"{api_url}/pos/load",
                    json={"transactions": batch}
                )
                logger.info("pos_batch_loaded",
                            batch=i // 500 + 1,
                            count=len(batch),
                            status=resp.status_code)
            except Exception as e:
                logger.error("pos_load_failed", error=str(e))
