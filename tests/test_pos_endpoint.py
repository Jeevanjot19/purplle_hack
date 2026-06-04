# PROMPT: Increase confidence in POS ingestion and conversion correlation.
# CHANGES MADE: Added endpoint-level tests for idempotent POS loading and Redis conversion count updates.

from datetime import datetime, timezone

import pytest

from app.routers.pos import POSLoadPayload, POSTransaction, load_pos_transactions


class Result:
    def __init__(self, scalar=None, rowcount=0):
        self._scalar = scalar
        self.rowcount = rowcount

    def scalar_one_or_none(self):
        return self._scalar

    def scalar_one(self):
        return self._scalar


class POSDB:
    def __init__(self, duplicate=False):
        self.duplicate = duplicate
        self.commits = 0

    async def execute(self, sql, params=None):
        query = str(sql)
        if "INSERT INTO pos_transactions" in query:
            return Result(scalar=None if self.duplicate else params["transaction_id"])
        if "UPDATE sessions" in query:
            return Result(rowcount=2)
        if "SELECT COUNT(*) FROM sessions" in query:
            return Result(scalar=2)
        return Result(scalar=0)

    async def commit(self):
        self.commits += 1


class RedisCapture:
    def __init__(self):
        self.values = {}

    async def set(self, key, value):
        self.values[key] = value


def payload():
    return POSLoadPayload(transactions=[
        POSTransaction(
            transaction_id="ORD-1",
            store_id="STORE_BLR_002",
            timestamp=datetime(2026, 6, 4, 10, 5, tzinfo=timezone.utc),
            basket_value=499.0,
        )
    ])


@pytest.mark.asyncio
async def test_pos_load_marks_sessions_converted_and_sets_redis_count():
    redis = RedisCapture()

    response = await load_pos_transactions(payload(), POSDB(), redis)

    assert response == {"loaded": 1, "duplicate_skipped": 0, "sessions_converted": 2}
    assert redis.values["store:STORE_BLR_002:conversion_count"] == 2


@pytest.mark.asyncio
async def test_pos_load_reports_duplicates():
    response = await load_pos_transactions(payload(), POSDB(duplicate=True), RedisCapture())

    assert response["loaded"] == 0
    assert response["duplicate_skipped"] == 1
