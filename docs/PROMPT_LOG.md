# Prompt Evolution Log — Store Intelligence Project

## PROMPT_001 [Initial Brief]
"Build a 5-layer retail analytics system for Purplle."

**Key Outcomes**:
- ✅ Defined 5 layers: ingestion, caching, intelligence, dashboard, detection
- ✅ Chose FastAPI, PostgreSQL, Redis, YOLO11, BoT-SORT
- ✅ Identified critical dependencies: structlog, pydantic, sqlalchemy, ultralytics

---

## PROMPT_012 [Data Ingestion + Store Reality]
[Uploaded: Brigade_Road_Store_Layout.xlsx, Brigade_Bangalore_POS.csv, Evaluation_Framework.pdf, CAM_1.mp4]

**Key Discoveries**:
- Real store ID: ST1008 (not STORE_BLR_002)
- POS CSV columns: invoice_number, order_date, order_time, total_amount (not transaction_id, basket_value_inr)
- Video timestamp: 10/04/2026 20:10:27 to 20:12:46 (evening clip, ~2.3 min, 30fps, 1920×1080)
- Camera: Main floor overhead wide-angle
- Faces not pre-blurred — camera itself blurs faces
- Evaluators spend only 10 minutes per submission
- Integrity check: outputs must vary with input (if not, score capped at 50%)
- Top 30 from 5000 = top 0.6%

**Key Outcomes**:
- ✅ Created real store_layout.json (v1 with 12 zones)
- ✅ Updated pos_loader.py to parse real CSV columns
- ✅ Added POST /pos/load endpoint
- ✅ Fixed timestamp extraction for "10/04/2026 20:10:27" format
- ⚠️ Single-camera layout (will be revised in PROMPT_013)

---

## PROMPT_013 [Camera Analysis + Multi-Camera Architecture]
[Uploaded: CAM_2.mp4, CAM_3.mp4]
"I'll share the rest 2 in next prompt cause of limits"

**Complete Camera Map Discovery**:

### CAM_3 — Entry/Exit Camera ⭐ CRITICAL
- **Mount**: At entrance looking inward
- **Visible**: Glass storefront door (dark reflective centre), entry threshold, Purplle standee
- **Outside**: People on right side = blurred faces on street (outside store)
- **Inside**: People on left = visible faces in store (inside)
- **Threshold**: Black marble floor (outside) vs wooden floor (inside)
- **Tripwire**: y≈350 (horizontal line at door boundary)
  - Moving UP (y decreasing) = ENTERING
  - Moving DOWN (y increasing) = EXITING
- **Critical Role**: This is the ONLY camera that should emit ENTRY/EXIT events

### CAM_2 — Makeup/Back Wall Camera
- **Mount**: Top-left corner looking across back wall
- **Visible Brands**: Alps, L'Oreal, 6Mars, Swiss Beauty, Lakme, Faces Canada, Maybelline
- **Zones**: PMU counter (left), central display (bottom)
- **Staff**: 3 people in black uniforms = staff in makeup area
- **Zone Events Only**: ZONE_ENTER/EXIT/DWELL (no ENTRY/EXIT)

### CAM_1 — Main Floor Camera ✅ (Already uploaded)
- **Mount**: Right side looking across main floor
- **Visible Brands**: The Face Shop, Good Vibes, DermDoc, Minimalist, Aqualogica, Cash Counter
- **Zone Events Only**: ZONE_ENTER/EXIT/DWELL (no ENTRY/EXIT)

### Cross-Camera Overlaps
1. **CAM_1 + CAM_2**: Central display ("Beat the Heat" summer essentials) → ReID dedup needed
2. **CAM_3 + CAM_1**: Entry-to-main-floor transition → First entry via CAM_3, then floor tracking via CAM_1

**Architectural Breakthrough**:
- ⚠️ **Problem with original design**: All cameras emitting ENTRY/EXIT = 3× visitor count
- ✅ **Solution**: Only CAM_3 emits ENTRY/EXIT; CAM_1/CAM_2 only emit ZONE events
- ✅ **Result**: Visitor count = unique entries via CAM_3, metrics now accurate

**Key Outcomes**:
- ✅ Complete multi-camera store_layout.json (camera types, tripwires, overlaps)
- ✅ Updated tracker.py: is_entry_camera parameter in process() and handle_lost_track()
- ✅ Updated detect.py: Camera type detection, passing to tracker
- ✅ Created ARCHITECTURE.md documentation
- ✅ Identified test sequence: CAM_3 first (entry/exit), then CAM_1, then CAM_2, then all 3

**Test Plan**:
1. **Phase 1**: CAM_3 alone → verify ENTRY/EXIT counts
2. **Phase 2**: CAM_1 alone → verify zone tracking (no ENTRY/EXIT)
3. **Phase 3**: CAM_2 alone → verify makeup zones
4. **Phase 4**: All 3 → verify cross-camera dedup and visitor count accuracy

---

## Design Decisions Locked

| Decision | Rationale | Status |
|----------|-----------|--------|
| Only entry camera emits ENTRY/EXIT | Prevents multi-counting across overlapping cameras | ✅ Locked |
| ReID gallery for cross-cam dedup | Identify same person in different cameras | ✅ Locked |
| CAM_3 tripwire at y=350 | Clear visual boundary (marble vs wood) | ✅ Locked |
| Visitor count = unique entries via CAM_3 | True count regardless of overlay effects | ✅ Locked |

---

## Next Prompts (Expected)

**PROMPT_014** (Expected): "Here's CAM_4 and CAM_5 footage, map them to zones"  
→ Add to store_layout.json, test full concurrent processing

**PROMPT_015** (Expected): "Pipeline test results + metrics validation"  
→ Debug event count discrepancies, refine zone polygons

**PROMPT_016** (Expected): "Prepare for competition evaluation"  
→ Add DESIGN.md, CHOICES.md, final integrity check

---
