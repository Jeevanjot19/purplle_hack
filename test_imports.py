#!/usr/bin/env python
"""Test that all pipeline modules can be imported."""
import sys
import warnings

warnings.filterwarnings("ignore")

try:
    from pipeline.zones import ZoneEngine
    print("✅ ZoneEngine imported")
    
    from pipeline.staff import StaffClassifier
    print("✅ StaffClassifier imported")
    
    from pipeline.reid import ReIDGallery
    print("✅ ReIDGallery imported")
    
    from pipeline.emit import EventEmitter, build_event
    print("✅ EventEmitter imported")
    
    from pipeline.tracker import GlobalSessionRegistry
    print("✅ GlobalSessionRegistry imported")
    
    print("\n✅ All pipeline imports OK")
    sys.exit(0)
except Exception as e:
    print(f"\n❌ Import failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
