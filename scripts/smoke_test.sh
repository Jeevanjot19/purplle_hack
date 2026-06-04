#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"
STORE_ID="${STORE_ID:-STORE_BLR_002}"

pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1"; exit 1; }

curl_json() {
  local path="$1"
  curl -fsS "${API_URL}${path}"
}

echo "Smoke testing ${API_URL} for ${STORE_ID}"

curl_json "/health" >/tmp/store_health.json && pass "health endpoint" || fail "health endpoint"

if [ -f "data/sample_events.jsonl" ]; then
  python scripts/convert_sample_events.py --input data/sample_events.jsonl --output data/converted_events.jsonl
  python scripts/convert_sample_events.py --input data/sample_events.jsonl --output data/converted_events.jsonl --ingest --api-url "${API_URL}"
  pass "converted and ingested sample_events.jsonl"
fi

curl -fsS -X POST "${API_URL}/events/ingest" \
  -H "Content-Type: application/json" \
  --data-binary @data/sample_ingest_events.json >/tmp/store_ingest.json \
  && pass "ingested sample STORE_BLR_002 batch" || fail "ingest sample batch"

curl_json "/stores/${STORE_ID}/metrics" >/tmp/store_metrics.json && pass "metrics endpoint" || fail "metrics endpoint"
curl_json "/stores/${STORE_ID}/funnel" >/tmp/store_funnel.json && pass "funnel endpoint" || fail "funnel endpoint"
curl_json "/stores/${STORE_ID}/heatmap" >/tmp/store_heatmap.json && pass "heatmap endpoint" || fail "heatmap endpoint"
curl_json "/stores/${STORE_ID}/anomalies" >/tmp/store_anomalies.json && pass "anomalies endpoint" || fail "anomalies endpoint"

echo "Smoke test complete."
