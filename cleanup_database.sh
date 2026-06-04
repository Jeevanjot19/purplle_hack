#!/bin/bash
# Database Cleanup Script for Test Data
# Purpose: Clear old test data before evaluation runs

set -e

echo "================================"
echo "DATABASE CLEANUP"
echo "================================"
echo ""
echo "[WARNING] This will DELETE all test data from:"
echo "  - events table"
echo "  - sessions table"
echo "  - anomaly_log table"
echo ""
read -p "Continue? (yes/no): " confirm
if [ "$confirm" != "yes" ]; then
    echo "Cancelled."
    exit 1
fi

echo ""
echo "[INFO] Connecting to database..."
docker exec store-intelligence-db-1 psql -U store -d storedb << EOF
BEGIN TRANSACTION;

-- Disable triggers if any
-- DELETE FROM pos_transactions CASCADE;

DELETE FROM anomaly_log;
DELETE FROM sessions;
DELETE FROM events;

-- Reset sequences
ALTER SEQUENCE events_id_seq RESTART WITH 1;
ALTER SEQUENCE anomaly_log_id_seq RESTART WITH 1;

COMMIT;
EOF

echo ""
echo "[INFO] Verification: Checking record counts"
docker exec store-intelligence-db-1 psql -U store -d storedb -c "
SELECT
  (SELECT COUNT(*) FROM events) as event_count,
  (SELECT COUNT(*) FROM sessions) as session_count,
  (SELECT COUNT(*) FROM anomaly_log) as anomaly_count;
"

echo ""
echo "✅ Database cleanup complete"
echo ""
echo "Next steps:"
echo "  1. Run: python test_pipeline_manual.py"
echo "  2. Wait for completion"
echo "  3. Check metrics: curl http://localhost:8000/stores/ST1008/metrics"
