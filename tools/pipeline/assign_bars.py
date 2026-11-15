"""Assign bar brands: user-fixed picks first, then big themed brands to the biggest bar buildings,
cheap generic dives to the smallest. Writes osm/bars.json (consumed by build_city.py)."""
import json, glob, math
from shapely.geometry import Polygon, Point
from shapely.strtree import STRtree
LAT0, LON0 = 41.6528, -83.5379; R = 6378137.0; C = math.cos(math.radians(LAT0))
P = lambda la, lo: ((lo - LON0) * math.pi / 180 * R * C, (la - LAT0) * math.pi / 180 * R)
bars = json.load(open('osm/bars.json'))
bars = [b for b in bars if b.get('real') != 'Crox Bar & Grill']
# Crox Bar & Grill (1432 Ingomar Ave) is not in OSM: placed on Ingomar Ave by address numbering
bars.append({"real": "Crox Bar & Grill", "theme": "Alligator Club", "x": -3180.0, "y": -2722.0, "fixed": True})
FIXED = {"Cardboard Club", "The Salty Hull", "Easy Pour", "Shot Clock"}
user_rows = json.load(open('/tmp/bar_fixed.json')) if glob.glob('/tmp/bar_fixed.json') else []
polys = []
for f in glob.glob('osm/city/*.json'):
    for e in json.load(open(f)).get('elements', []):
        if e['type'] == 'way' and 'building' in e.get('tags', {}) and len(e.get('geometry', [])) >= 4:
            try:
                g = Polygon([P(p['lat'], p['lon']) for p in e['geometry']])
                if g.is_valid and g.area > 20: polys.append(g)
            except Exception: pass
tree = STRtree(polys)
for b in bars:
    pt = Point(b['x'], b['y']); k = tree.nearest(pt)
    b['area'] = polys[k].area if polys[k].distance(pt) < 30 else 150.0
    b['fixed'] = b.get('fixed') or b['real'] in user_rows
BIG = ["Shot Clock", "The Salty Hull", "Cardboard Club", "Easy Pour", "Velvet Mile", "Erie Tiki", "Neon Coyote"]
CHEAP = ["Two Buck Tavern", "Dollar Draft", "Corner Tap", "Happy Hour Hut", "Tipsy Tom's", "BAR", "Last Call"]
free = sorted([b for b in bars if not b['fixed']], key=lambda b: -b['area'])
nbig = round(len(free) * 0.62)
for i, b in enumerate(free[:nbig]): b['theme'] = BIG[i % len(BIG)]
for i, b in enumerate(free[nbig:]): b['theme'] = CHEAP[i % len(CHEAP)]
json.dump(bars, open('osm/bars.json', 'w'), indent=0)
import collections; print(len(bars), collections.Counter(b['theme'] for b in bars))
