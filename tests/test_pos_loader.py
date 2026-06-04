# PROMPT: Verify POS loading supports the challenge CSV schema and safely skips bad data.
# CHANGES MADE: Added unit tests for order_id fallback, timestamp parsing, invalid rows, and duplicate counting.

import csv

import pytest

from pipeline.pos_loader import load_pos, parse_pos_row


def test_pos_loader_supports_order_id_schema():
    row = {
        "order_id": "ORD-1",
        "order_date": "04-06-2026",
        "order_time": "10:05:00",
        "store_id": "STORE_BLR_002",
        "total_amount": "499.50",
    }

    parsed = parse_pos_row(row)

    assert parsed == {
        "transaction_id": "ORD-1",
        "store_id": "STORE_BLR_002",
        "timestamp": "2026-06-04T10:05:00Z",
        "basket_value": 499.50,
    }


def test_pos_loader_prefers_invoice_number_when_present():
    row = {
        "invoice_number": "INV-9",
        "order_id": "ORD-9",
        "order_date": "2026-06-04",
        "order_time": "10:05",
        "store_id": "STORE_BLR_002",
        "total_amount": "100",
    }

    assert parse_pos_row(row)["transaction_id"] == "INV-9"


def test_pos_loader_skips_invalid_rows():
    assert parse_pos_row({"order_id": "ORD-1", "total_amount": "nope"}) is None


@pytest.mark.asyncio
async def test_load_pos_deduplicates_and_reports_counts(tmp_path, monkeypatch):
    csv_path = tmp_path / "pos.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["order_id", "order_date", "order_time", "store_id", "total_amount"],
        )
        writer.writeheader()
        writer.writerow({
            "order_id": "ORD-1",
            "order_date": "04-06-2026",
            "order_time": "10:00:00",
            "store_id": "STORE_BLR_002",
            "total_amount": "200",
        })
        writer.writerow({
            "order_id": "ORD-1",
            "order_date": "04-06-2026",
            "order_time": "10:00:00",
            "store_id": "STORE_BLR_002",
            "total_amount": "200",
        })
        writer.writerow({
            "order_id": "",
            "order_date": "bad",
            "order_time": "bad",
            "store_id": "STORE_BLR_002",
            "total_amount": "200",
        })

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"loaded": 1}

    class FakeClient:
        def __init__(self, *_, **__):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr("pipeline.pos_loader.httpx.AsyncClient", FakeClient)

    result = await load_pos(str(csv_path), "http://api")

    assert result == {"parsed": 1, "skipped": 1, "duplicates": 1, "loaded": 1}
