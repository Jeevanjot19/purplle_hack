"""Direct Python - test without problematic numpy warnings."""
import sys
import warnings

# Try to catch and suppress the numpy issue at startup
warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

try:
    import json
    import tempfile
    import os
    from pipeline.zones import ZoneEngine
    
    # Create a fake store_layout.json
    layout = {
      'stores': {
        'STORE_TEST': {
          'zones': [
            {'id': 'SKINCARE', 'polygon': [[0,0],[100,0],[100,100],[0,100]]},
            {'id': 'BILLING',  'polygon': [[200,0],[300,0],[300,100],[200,100]]},
          ]
        }
      }
    }
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
        json.dump(layout, f)
        path = f.name
    
    ze = ZoneEngine('STORE_TEST', path)
    zone1 = ze.get_zone(50, 50)
    zone2 = ze.get_zone(250, 50)
    zone3 = ze.get_zone(150, 50)
    
    print(f"Zone at (50,50): {zone1}")
    print(f"Zone at (250,50): {zone2}")
    print(f"Zone at (150,50): {zone3}")
    
    assert zone1 == 'SKINCARE', f'Should be SKINCARE, got {zone1}'
    assert zone2 == 'BILLING', f'Should be BILLING, got {zone2}'
    assert zone3 is None, f'Should be None, got {zone3}'
    
    print('✅ ZoneEngine tests passed')
    os.unlink(path)
    sys.exit(0)
    
except Exception as e:
    print(f"❌ Error: {e}", file=sys.stderr)
    import traceback
    traceback.print_exc()
    sys.exit(1)
