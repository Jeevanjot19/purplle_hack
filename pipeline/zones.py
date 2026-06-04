"""
pipeline/zones.py
─────────────────
Loads store_layout.json and answers one question per frame:
"Given this (x, y) centroid, which zone is it in?"

Uses Shapely polygon containment — O(n_zones) per query,
fast enough for 15fps × 3 cameras × n_people.
"""
import json
from pathlib import Path
from shapely.geometry import Point, Polygon


class ZoneEngine:
    def __init__(self, store_id: str, layout_path: str = "/data/store_layout.json"):
        self.store_id = store_id
        self.zones: dict[str, Polygon] = {}
        self.entry_zone: str | None = None
        self._load(layout_path)

    def _load(self, path: str):
        with open(path) as f:
            layout = json.load(f)

        # Find the zones for this store
        # Expected format:
        # {"stores": {"STORE_BLR_002": {"zones": [{"id":"SKINCARE","polygon":[[x,y],...]}]}}}
        stores = layout.get("stores", layout)  # handle flat or nested
        store_data = stores.get(self.store_id, {})
        zones_raw = list(store_data.get("zones", []))
        for camera in store_data.get("cameras", {}).values():
            if camera.get("process", True) is False:
                continue
            zones_raw.extend(camera.get("zones", []))

        for zone in zones_raw:
            zone_id = zone.get("id") or zone.get("zone_id")
            if not zone_id:
                continue
            coords  = zone["polygon"]           # list of [x, y] pairs
            self.zones[zone_id] = Polygon(coords)
            if "entry" in zone_id.lower() or zone.get("is_entry", False):
                self.entry_zone = zone_id

    def get_zone(self, cx: float, cy: float) -> str | None:
        """Return zone_id if centroid (cx, cy) falls inside any zone, else None."""
        pt = Point(cx, cy)
        for zone_id, polygon in self.zones.items():
            if polygon.contains(pt):
                return zone_id
        return None

    def get_entry_line(self) -> tuple[int, int, int, int] | None:
        """
        Return (x1, y1, x2, y2) of the entry zone's midline for tripwire logic.
        If no entry zone defined, returns None (fallback: use frame midline).
        """
        if not self.entry_zone:
            return None
        poly = self.zones[self.entry_zone]
        bounds = poly.bounds          # (minx, miny, maxx, maxy)
        minx, miny, maxx, maxy = bounds
        # Horizontal midline of entry zone
        mid_y = int((miny + maxy) / 2)
        return (int(minx), mid_y, int(maxx), mid_y)
