"""Test ZoneEngine with fake layout."""
import json, tempfile, os
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
assert ze.get_zone(50, 50) == 'SKINCARE', 'Should be SKINCARE'
assert ze.get_zone(250, 50) == 'BILLING',  'Should be BILLING'
assert ze.get_zone(150, 50) is None,       'Should be None'
print('✅ ZoneEngine tests passed')
os.unlink(path)
