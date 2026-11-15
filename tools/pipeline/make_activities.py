"""Activity places (scripts/activities.gd): gyms, bowling alleys, stadiums/ballparks, cinemas, fishing spots.

usage: make_activities.py <osm tiles dir> <island.json> <out activities.json>
Fishing spots are boat ramps, piers, docks and marked fishing places along the river and lake. Names are made up."""
import glob, json, math, os, random, sys
TILES, ISL, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
LAT0, LON0 = 41.6528, -83.5379; R = 6378137.0; C = math.cos(math.radians(LAT0))
def P(lat, lon): return ((lon - LON0) * math.pi / 180 * R * C, (lat - LAT0) * math.pi / 180 * R)
S, W, N, E = json.load(open(ISL))["real"]
rng = random.Random(4)
NAMES = {"gym": ["Iron Furnace Fitness", "Glass City Athletic Club", "Lakeshore Gym", "Northfork Fitness", "Maumee Muscle", "24/7 Grind"],
         "bowling": ["Strike City Lanes", "Pinewick Bowl", "Walleye Lanes", "Glassmere Bowl-O-Rama"],
         "stadium": ["Riverside Ballpark", "Swamp Field", "Community Diamond", "Northfork Stadium"],
         "cinema": ["Marquee 8", "Lakeshore Cinemas", "Old Mill Theater", "Glass City Picture House"],
         "fishing": ["fishing spot"]}
def kind_of(t):
    if t.get("leisure") in ("fitness_centre",) or (t.get("leisure") == "sports_centre" and t.get("sport") in (None, "fitness", "multi")): return "gym"
    if t.get("leisure") == "bowling_alley" or t.get("sport") in ("10pin", "bowling"): return "bowling"
    if t.get("leisure") == "stadium" or (t.get("leisure") == "pitch" and t.get("sport") == "baseball" and t.get("name")): return "stadium"
    if t.get("amenity") == "cinema": return "cinema"
    if t.get("leisure") in ("slipway", "fishing") or t.get("man_made") == "pier" or t.get("leisure") == "marina": return "fishing"
    return None
out, seen = [], set()
for f in sorted(glob.glob(os.path.join(TILES, "*.json"))):
    for e in json.load(open(f))["elements"]:
        k = kind_of(e.get("tags", {}))
        if k is None: continue
        if e["type"] == "node": la, lo = e["lat"], e["lon"]
        elif e.get("geometry"):
            g = e["geometry"]; la = sum(q["lat"] for q in g) / len(g); lo = sum(q["lon"] for q in g) / len(g)
        else: continue
        if not (S <= la <= N and W <= lo <= E): continue
        x, y = P(la, lo)
        key = (k, round(x / 150), round(y / 150))
        if key in seen: continue
        seen.add(key)
        name = rng.choice(NAMES[k]) if k != "fishing" else "Fishing spot"
        out.append({"id": len(out), "kind": k, "name": name, "x": round(x, 1), "z": round(-y, 1)})
# more fishing spots: along the banks of the river and creeks, about every 1.2 km
from shapely.geometry import Polygon, LineString
banks = []
for f in sorted(glob.glob(os.path.join(TILES, "*.json"))):
    for e in json.load(open(f))["elements"]:
        t = e.get("tags", {})
        if not (t.get("natural") == "water" or t.get("waterway") == "riverbank"): continue
        if t.get("name") not in ("Maumee River", "Ottawa River", "Swan Creek", "Ten Mile Creek", "Duck Creek", "Otter Creek"): continue
        for m in ([e] if e["type"] == "way" else e.get("members", [])):
            g = m.get("geometry") or []
            if len(g) > 2: banks.append(LineString([P(q["lat"], q["lon"]) for q in g]))
x0, y0 = P(S, W); x1, y1 = P(N, E)
for ln in banks:
    d = 300.0
    while d < ln.length:
        q = ln.interpolate(d); d += 1200.0
        if not (x0 < q.x < x1 and y0 < q.y < y1): continue
        key = ("fishing", round(q.x / 600), round(q.y / 600))
        if key in seen: continue
        seen.add(key)
        out.append({"id": len(out), "kind": "fishing", "name": "Riverbank fishing spot", "x": round(q.x, 1), "z": round(-q.y, 1)})
json.dump({"_doc": "made by tools/pipeline/make_activities.py; made-up names; world metres", "places": out}, open(OUT, "w"))
from collections import Counter
print(len(out), Counter(p["kind"] for p in out))
