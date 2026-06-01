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
import asyncio, glob, os, sys, json
sys.path.insert(0, '/pipeline')
from pipeline.detect import process_clip

async def main():
    clips = sorted(glob.glob('$DATA_DIR/*.mp4'))
    if not clips:
        print('No clips found in $DATA_DIR')
        return

    print(f'Found {len(clips)} clip(s): {clips}')

    # Load camera config from store_layout.json
    try:
        with open('/pipeline/data/store_layout.json') as f:
            layout = json.load(f)
            skip_cams = layout['stores']['$STORE_ID'].get('skip_cameras', [])
    except:
        skip_cams = ['CAM_4']

    print(f'Skipping cameras: {skip_cams}')

    # Extract camera_id from filename
    # Expected patterns: CAM_1.mp4, CAM_3.mp4, etc.
    camera_map = {}
    for clip in clips:
        fname = os.path.basename(clip).upper()
        cam_id = None
        
        # Try exact match: CAM_1.mp4, CAM_3.mp4, etc.
        for i in range(1, 6):
            if f'CAM_{i}' in fname or f'CAM{i}' in fname:
                cam_id = f'CAM_{i}'
                break
        
        if not cam_id:
            # Fallback heuristics
            if 'ENTRY' in fname:
                cam_id = 'CAM_3'
            elif 'BILLING' in fname or 'CASH' in fname:
                cam_id = 'CAM_5'
            elif 'MAIN' in fname or 'FLOOR' in fname:
                cam_id = 'CAM_1'
            elif 'MAKEUP' in fname:
                cam_id = 'CAM_2'
            elif 'STOCK' in fname or 'BACK' in fname:
                cam_id = 'CAM_4'
            else:
                cam_id = 'CAM_1'  # default
        
        # SKIP CAM_4 (stockroom)
        if cam_id in skip_cams:
            print(f'[SKIP] {fname} → {cam_id} (staff-only area)')
            continue
        
        camera_map[clip] = cam_id

    # Process all non-skipped cameras concurrently
    tasks = []
    for clip, cam_id in camera_map.items():
        fname = os.path.basename(clip)

        tasks.append(process_clip(
            clip_path='$DATA_DIR/' + fname,
            store_id='$STORE_ID',
            camera_id=cam_id,
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
