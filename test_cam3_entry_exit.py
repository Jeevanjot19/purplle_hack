#!/usr/bin/env python
"""
Manual pipeline test for CAM_3 (Entry/Exit camera)
Real store: Brigade Road Bangalore, ST1008
Expected output: ENTRY/EXIT event count matches visible visitors at threshold

Test Phase: 1/4 (Entry/Exit accuracy baseline)
"""
import asyncio
import sys
from pathlib import Path

# Add pipeline to path
sys.path.insert(0, str(Path(__file__).parent))

from pipeline.detect import process_clip


async def test_cam3():
    """Test CAM_3 entry/exit detection."""
    
    store_id = "ST1008"
    camera_id = "CAM_3"
    
    # Try both absolute and relative paths
    video_path = Path(__file__).parent / "data" / "CAM_3.mp4"
    if not video_path.exists():
        print(f"[ERROR] CAM_3 not found at {video_path}")
        print("        Expected file: d:/CCTV project/store-intelligence/data/CAM_3.mp4")
        sys.exit(1)
    
    print("=" * 80)
    print("PIPELINE TEST — PHASE 1: Entry/Exit Camera (CAM_3)")
    print("=" * 80)
    print(f"Store:        {store_id} (Brigade Road Bangalore)")
    print(f"Camera:       {camera_id} (Entry/Exit threshold)")
    print(f"Video:        {video_path.name}")
    print(f"API:          http://localhost:8000")
    print(f"Speed:        5.0× real-time (demo mode)")
    print("=" * 80)
    print()
    print("EXPECTED OUTPUT:")
    print("  - ENTRY events: ~2-3 people entering store")
    print("  - EXIT events: ~1-2 people exiting")
    print("  - ZONE_ENTER/EXIT: minimal (entry zone only)")
    print("  - NO ENTRY/EXIT on CAM_1 or CAM_2 later")
    print()
    print("INTEGRITY CHECK:")
    print("  - If visitor_count changes with different cameras → PASS")
    print("  - If visitor_count always same → FAIL (integrity issue)")
    print("=" * 80)
    print()
    
    try:
        await process_clip(
            clip_path=str(video_path),
            store_id=store_id,
            camera_id=camera_id,
            layout_path=str(Path(__file__).parent / "data" / "store_layout.json"),
            api_url="http://localhost:8000",
            speed_factor=5.0,  # Demo speed
            model_path="yolo11s.pt",
        )
        print()
        print("[SUCCESS] CAM_3 pipeline completed")
        print()
        print("NEXT STEPS:")
        print("  1. Check metrics: curl http://localhost:8000/stores/ST1008/metrics")
        print("  2. Verify event count in database")
        print("  3. Run Phase 2 test on CAM_1")
        return True
        
    except Exception as e:
        print()
        print(f"[ERROR] Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(test_cam3())
    sys.exit(0 if success else 1)
