"""ATM locations for the money system (scripts/money.gd).

usage: make_atms.py <osm tiles dir> <island.json> <out atms.json>
Every bank/credit union in the real area gets an ATM out front (the game puts it on the nearest sidewalk).
Bank names become made-up ones (no real brands)."""
import glob, json, math, os, random, sys
TILES, ISL, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
LAT0, LON0 = 41.6528, -83.5379; R = 6378137.0; C = math.cos(math.radians(LAT0))
def P(lat, lon): return ((lon - LON0) * math.pi / 180 * R * C, (lat - LAT0) * math.pi / 180 * R)
S, W, N, E = json.load(open(ISL))["real"]
NAMES = ["Maumee Mutual", "Glass City Savings", "Lakeshore Trust", "Harbor Federal", "Stonebridge Credit Union",
         "First Glassmere Bank", "Union Furnace Bank", "Northfork Federal", "Kingsferry Savings", "Pinewick Community Bank"]
seen, out = set(), []
rng = random.Random(7)
for f in sorted(glob.glob(os.path.join(TILES, "*.json"))):
    for e in json.load(open(f))["elements"]:
        t = e.get("tags", {})
        if t.get("amenity") not in ("bank", "atm"): continue
        if e["type"] == "node": la, lo = e["lat"], e["lon"]
        elif e.get("geometry"):
            g = e["geometry"]; la = sum(q["lat"] for q in g) / len(g); lo = sum(q["lon"] for q in g) / len(g)
        elif e.get("center"): la, lo = e["center"]["lat"], e["center"]["lon"]
        else: continue
        if not (S <= la <= N and W <= lo <= E): continue
        x, y = P(la, lo)
        k = (round(x / 25), round(y / 25))
        if k in seen: continue
        seen.add(k)
        out.append({"x": round(x, 1), "z": round(-y, 1), "bank": rng.choice(NAMES)})
json.dump({"_doc": "made by tools/pipeline/make_atms.py; x/z are world metres", "atms": out}, open(OUT, "w"))
print("atms", len(out))
