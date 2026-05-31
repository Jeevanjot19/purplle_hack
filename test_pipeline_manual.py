#!/usr/bin/env python
"""
Manual test of the detection pipeline on CAM_1.mp4
Real store: Brigade Road Bangalore, ST1008
Video: 10/04/2026 20:10:27 to 20:12:46 (~2.3 minutes)
"""
import asyncio
import sys
from pathlib import Path

# Add pipeline modules to path
sys.path.insert(0, str(Path(__file__).parent))

from pipeline.detect import process_clip


async def main():
    """Test the pipeline on CAM_1 with real store configuration."""
    
    # Real store configuration
    store_id = "ST1008"
    camera_id = "CAM_1"
    clip_path = "/data/CAM_1.mp4"  # Mounted volume in Docker
    
    # Check if file exists locally
    local_clip = Path(__file__).parent / "data" / "CAM_1.mp4"
    if local_clip.exists():
        clip_path = str(local_clip)
    else:
        print(f"[WARN] Clip not found at {clip_path} or {local_clip}")
        print("       Available files in ./data/:")
        data_dir = Path(__file__).parent / "data"
        if data_dir.exists():
            for f in data_dir.glob("*.mp4"):
                print(f"         - {f.name}")
    
    print("=" * 70)
    print("MANUAL PIPELINE TEST")
    print("=" * 70)
    print(f"Store ID:   {store_id}")
    print(f"Camera:     {camera_id}")
    print(f"Clip:       {clip_path}")
    print(f"API URL:    http://localhost:8000")
    print(f"Speed:      5.0x (demo mode)")
    print("=" * 70)
    
    try:
        await process_clip(
            clip_path=clip_path,
            store_id=store_id,
            camera_id=camera_id,
            layout_path="./data/store_layout.json",
            api_url="http://localhost:8000",
            speed_factor=5.0,  # 5× real-time for quick demo
            model_path="yolo11s.pt",
        )
        print("\n[SUCCESS] Pipeline completed successfully")
        
    except FileNotFoundError as e:
        print(f"\n[ERROR] File not found: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
