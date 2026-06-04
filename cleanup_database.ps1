# Database Cleanup Script for Test Data (PowerShell)
# Purpose: Clear old test data before evaluation runs

Write-Host "================================" -ForegroundColor Cyan
Write-Host "DATABASE CLEANUP" -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "[WARNING] This will DELETE all test data from:" -ForegroundColor Yellow
Write-Host "  - events table"
Write-Host "  - sessions table"
Write-Host "  - anomaly_log table"
Write-Host ""
$confirm = Read-Host "Continue? (yes/no)"
if ($confirm -ne "yes") {
    Write-Host "Cancelled." -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "[INFO] Connecting to database..." -ForegroundColor Blue

$sql = @"
BEGIN TRANSACTION;

DELETE FROM anomaly_log;
DELETE FROM sessions;
DELETE FROM events;

ALTER SEQUENCE events_id_seq RESTART WITH 1;
ALTER SEQUENCE anomaly_log_id_seq RESTART WITH 1;

COMMIT;
"@

docker exec store-intelligence-db-1 psql -U store -d storedb -c $sql

Write-Host ""
Write-Host "[INFO] Verification: Checking record counts" -ForegroundColor Blue
docker exec store-intelligence-db-1 psql -U store -d storedb -c "
SELECT
  (SELECT COUNT(*) FROM events) as event_count,
  (SELECT COUNT(*) FROM sessions) as session_count,
  (SELECT COUNT(*) FROM anomaly_log) as anomaly_count;
"

Write-Host ""
Write-Host "✅ Database cleanup complete" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Run: python test_pipeline_manual.py"
Write-Host "  2. Wait for completion"
Write-Host "  3. Check metrics: curl http://localhost:8000/stores/ST1008/metrics"
