#!/usr/bin/env python
"""
Quick debug: Check YOLO model loading and video I/O
"""
import sys
from pathlib import Path
import time

sys.path.insert(0, str(Path(__file__).parent))

print("=" * 70)
print("YOLO MODEL & VIDEO DEBUG")
print("=" * 70)

# Check video file
clip_path = Path("data/CAM_1.mp4")
print(f"\n✓ Video path: {clip_path}")
print(f"  Exists: {clip_path.exists()}")
print(f"  Size: {clip_path.stat().st_size / 1024 / 1024:.1f} MB")

# Try loading video
import cv2
print(f"\n[1/3] Loading video with OpenCV...")
cap = cv2.VideoCapture(str(clip_path))
if cap.isOpened():
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    print(f"✓ Video opened: {total_frames} frames @ {fps} fps")
    ret, frame = cap.read()
    print(f"✓ First frame read: {frame.shape}")
    cap.release()
else:
    print(f"✗ Failed to open video")
    sys.exit(1)

# Try loading YOLO
print(f"\n[2/3] Loading YOLO11s model...")
t0 = time.time()
try:
    from ultralytics import YOLO
    model = YOLO("yolo11s.pt")
    t1 = time.time()
    print(f"✓ YOLO11s loaded in {t1-t0:.1f}s")
except Exception as e:
    print(f"✗ YOLO load failed: {e}")
    sys.exit(1)

# Try one frame inference
print(f"\n[3/3] Running one frame through YOLO...")
cap = cv2.VideoCapture(str(clip_path))
ret, frame = cap.read()
cap.release()

if ret:
    t0 = time.time()
    try:
        results = model.track(frame, persist=True, classes=[0], conf=0.25)
        t1 = time.time()
        print(f"✓ Inference completed in {t1-t0:.2f}s")
        print(f"  Detections: {len(results[0].boxes)}")
    except Exception as e:
        print(f"✗ Inference failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

print(f"\n" + "=" * 70)
print("✓ All systems ready for pipeline")
print("=" * 70)
