# Multi-Camera Architecture Update

**Date**: June 1, 2026  
**Change Type**: Critical Architectural Fix  
**Impact**: ENTRY/EXIT event generation, visitor counting accuracy

---

## Overview

The detection pipeline now properly handles **multi-camera deployments** with distinct camera types:

- **Entry/Exit Cameras** (CAM_3): Detect store entries and exits, emit ENTRY/REENTRY/EXIT events
- **Floor Cameras** (CAM_1, CAM_2): Track visitor movement within zones, emit ZONE_ENTER/ZONE_EXIT/ZONE_DWELL events

### Why This Matters

Previously, the system emitted ENTRY/EXIT events from all cameras, which would:
- **Double-count** visitors (1 entry per camera = 3× for a person visible in all 3 cameras)
- **Invalid metrics**: Visitor count and funnel accuracy dependent on camera overlap
- **Failing integrity check**: Same person in different cameras = different event sequences

**Solution**: Designate CAM_3 as the "single source of truth" for store entries/exits. All other cameras suppress ENTRY/EXIT events and only report zone movements.

---

## Technical Changes

### 1. `data/store_layout.json` — Multi-Camera Configuration

**New Structure**:
```json
{
  "stores": {
    "ST1008": {
      "cameras": {
        "CAM_1": {
          "type": "main_floor",
          "zones": [...]
        },
        "CAM_2": {
          "type": "makeup_wall",
          "zones": [...]
        },
        "CAM_3": {
          "type": "entry_exit",
          "zones": [...],
          "tripwire": { "x1": 300, "y1": 350, "x2": 950, ... }
        }
      },
      "cross_camera_overlap": [
        { "cameras": ["CAM_1", "CAM_2"], "region": "central_display" },
        { "cameras": ["CAM_3", "CAM_1"], "region": "entry_to_main_floor" }
      ]
    }
  }
}
```

**Key Addition**: `"type"` field determines camera behavior.

---

### 2. `pipeline/tracker.py` — Entry Camera Logic

**Changes to `process()` method**:
```python
def process(self, ..., is_entry_camera: bool = False) -> list[dict]:
    if track_id not in self._active:
        if is_entry_camera:
            # Emit ENTRY/REENTRY event (CAM_3 only)
            event_type = "ENTRY" or "REENTRY"
        else:
            # Floor camera: silently create session (no ENTRY event)
            session = ActiveSession(...)
            return []  # No ENTRY event
```

**Changes to `handle_lost_track()` method**:
```python
def handle_lost_track(self, ..., is_entry_camera: bool = False) -> list[dict]:
    if not is_entry_camera:
        return []  # Only exit on entry camera
    
    return [build_event(event_type="EXIT", ...)]
```

**Result**: 
- CAM_3 processes all ENTRY/EXIT/REENTRY events
- CAM_1, CAM_2 only emit ZONE events
- Visitor count = unique entries via CAM_3, not sum of all detections

---

### 3. `pipeline/detect.py` — Camera Type Detection

**New initialization code**:
```python
# Determine camera type (entry vs floor)
is_entry_camera = False
try:
    with open(layout_path, 'r') as f:
        layout = json.load(f)
        camera_config = layout["stores"][store_id]["cameras"].get(camera_id, {})
        is_entry_camera = camera_config.get("type") == "entry_exit"
except Exception as e:
    logger.warning("camera_type_detection_failed", error=str(e))
```

**Passed to tracker**:
```python
events = registry.process(..., is_entry_camera=is_entry_camera)
exit_events = registry.handle_lost_track(..., is_entry_camera=is_entry_camera)
```

---

## Camera Map — Brigade Road Bangalore (ST1008)

| Camera | Type | View | Role |
|--------|------|------|------|
| **CAM_3** ⭐ | entry_exit | Glass door, threshold (y=350) | **ENTRY/EXIT source** — all visitor entries/exits come from here |
| **CAM_1** | main_floor | Korean skincare wall, cash counter | Zone tracking (ZONE_ENTER/EXIT/DWELL) |
| **CAM_2** | makeup_wall | Back wall: Alps, Swiss Beauty, Lakme, Faces Canada | Zone tracking (ZONE_ENTER/EXIT/DWELL) |

### Cross-Camera Overlap

1. **CAM_1 + CAM_2** → Central display ("Beat the Heat" summer essentials)  
   - Person at central table visible in both cameras
   - ReID deduplication prevents duplicate ZONE events

2. **CAM_3 + CAM_1** → Entry-to-main-floor transition  
   - Person enters via CAM_3 door
   - Walks into CAM_1 main floor view
   - ReID gallery finds existing visitor_id, links track_id to same session

---

## Testing Sequence

### Phase 1: Entry/Exit Accuracy (USE CAM_3)
```bash
python pipeline/detect.py CAM_3
# Expected: X unique ENTRYs, Y EXITs, X-Y = active visitors
```

### Phase 2: Zone Tracking (USE CAM_1)
```bash
python pipeline/detect.py CAM_1
# Expected: ZONE_ENTER/EXIT/DWELL for zones, NO ENTRY/EXIT events
```

### Phase 3: Back Wall Zones (USE CAM_2)
```bash
python pipeline/detect.py CAM_2
# Expected: Makeup zone events (Alps, Swiss Beauty, Lakme, Faces Canada)
```

### Phase 4: Cross-Camera Validation (USE ALL 3)
```bash
docker-compose run --rm pipeline python run.sh
# Expected: visitor_count matches CAM_3 entries only
#          zone events come from all cameras
#          cross-camera dedup works (same person tracked correctly)
```

---

## Integrity Check (For Evaluators)

**Input Variation Test**:
- **CAM_3 alone**: X unique entries
- **CAM_1 alone**: Y zone visits (different number than X, expected)
- **CAM_2 alone**: Z zone visits in makeup area
- **All 3**: Total unique visitors = X (matches CAM_3), zones = Y + Z deduplicated

✅ **Pass if**: visitor_count varies correctly per camera combo  
❌ **Fail if**: visitor_count stays same regardless of input

---

## Files Modified

```
data/store_layout.json          — Multi-camera zone definitions + tripwire
pipeline/tracker.py             — is_entry_camera parameter (process, handle_lost_track)
pipeline/detect.py              — Camera type detection + passing to tracker
docs/ARCHITECTURE.md            — This document
```

---

## Next Steps

1. **Test CAM_3 first** — verify ENTRY/EXIT event count matches actual visitors
2. **Test CAM_1** — verify zone events without spurious ENTRY/EXIT
3. **Test CAM_2** — verify makeup zone tracking
4. **Test all 3 concurrently** — verify cross-camera deduplication
5. **Evaluate**: Check visitor_count metrics across all test combinations

---

## Rollback Plan

If cross-camera dedup fails:
1. Disable ReID gallery checks: comment out `dup_vid = self._gallery.find_cross_cam_dup(...)`
2. Revert to per-camera visitor counts
3. Debug embedding similarity thresholds (currently 0.78 for 30sec cross-cam)

---
