#!/bin/bash
set -e

STORE_ID="${STORE_ID:-ST1008}"
SPEED_FACTOR="${SPEED_FACTOR:-5.0}"
DATA_DIR="${DATA_DIR:-/data}"
API_URL="${API_URL:-http://api:8000}"

echo "╔══════════════════════════════════════════╗"
echo "║  Store Intelligence — Detection Pipeline  ║"
echo "╠══════════════════════════════════════════╣"
echo "║  Store       : $STORE_ID"
echo "║  Speed       : ${SPEED_FACTOR}× real-time"
echo "║  Data dir    : $DATA_DIR"
echo "║  API         : $API_URL"
echo "╚══════════════════════════════════════════╝"

# 1. Load POS transactions
echo ""
echo "[1/3] Loading POS transactions..."
python -c "
import asyncio
from pipeline.pos_loader import load_pos
asyncio.run(load_pos('$DATA_DIR/pos_transactions.csv', '$API_URL'))
"

# 2. Process all clips for this store
echo ""
echo "[2/3] Processing CCTV clips..."

python -c "
import asyncio, glob, os, sys
sys.path.insert(0, '/pipeline')
from pipeline.detect import process_clip

async def main():
    clips = sorted(glob.glob('$DATA_DIR/${STORE_ID}_CAM_*.mp4'))
    if not clips:
        # Try generic pattern
        clips = sorted(glob.glob('$DATA_DIR/*.mp4'))
    if not clips:
        print('No clips found in $DATA_DIR')
        return

    print(f'Found {len(clips)} clip(s): {clips}')

    # Process all cameras concurrently
    tasks = []
    for clip in clips:
        fname = os.path.basename(clip)
        # Extract camera_id from filename
        if 'ENTRY' in fname.upper():
            cam = 'CAM_ENTRY_01'
        elif 'FLOOR' in fname.upper() or 'MAIN' in fname.upper():
            cam = 'CAM_FLOOR_01'
        elif 'BILLING' in fname.upper():
            cam = 'CAM_BILLING_01'
        else:
            cam = f'CAM_{fname[:10]}'

        tasks.append(process_clip(
            clip_path='$DATA_DIR/' + fname,
            store_id='$STORE_ID',
            camera_id=cam,
            layout_path='$DATA_DIR/store_layout.json',
            api_url='$API_URL',
            speed_factor=float('$SPEED_FACTOR'),
        ))

    await asyncio.gather(*tasks)

asyncio.run(main())
"

echo ""
echo "[3/3] Pipeline complete."
echo "      Dashboard: http://localhost:3000"
echo "      Metrics:   $API_URL/stores/$STORE_ID/metrics"
