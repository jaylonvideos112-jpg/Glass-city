"""Homes for rent or sale (scripts/homes.gd).

usage: make_homes.py <osm tiles dir> <island.json> <out homes.json>
Picks ~220 real houses and apartment buildings spread over the real area (at least 250 m apart) and lists each for
rent and/or sale. Price comes from the footprint area and the neighbourhood (nicer near the river and the west side,
pricier downtown for apartments). Addresses are made up."""
import glob, json, math, os, random, sys
TILES, ISL, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
LAT0, LON0 = 41.6528, -83.5379; R = 6378137.0; C = math.cos(math.radians(LAT0))
def P(lat, lon): return ((lon - LON0) * math.pi / 180 * R * C, (lat - LAT0) * math.pi / 180 * R)
S, W, N, E = json.load(open(ISL))["real"]
rng = random.Random(2026)
cands = []
for f in sorted(glob.glob(os.path.join(TILES, "*.json"))):
    for e in json.load(open(f))["elements"]:
        t = e.get("tags", {}); b = t.get("building")
        if b not in ("house", "detached", "apartments", "residential", "semidetached_house", "bungalow"): continue
        g = e.get("geometry")
        if not g or len(g) < 4: continue
        la = sum(q["lat"] for q in g) / len(g); lo = sum(q["lon"] for q in g) / len(g)
        if not (S <= la <= N and W <= lo <= E): continue
        pts = [P(q["lat"], q["lon"]) for q in g]
        area = abs(sum(pts[i][0] * pts[i + 1][1] - pts[i + 1][0] * pts[i][1] for i in range(len(pts) - 1))) / 2
        if area < 60 or area > 4000: continue
        x, y = P(la, lo)
        cands.append((x, y, "apartment" if b in ("apartments", "residential") and area > 300 else "house", area))
rng.shuffle(cands)
picked = []
for c in cands:
    if all(math.hypot(c[0] - p[0], c[1] - p[1]) > 250 for p in picked): picked.append(c)
    if len(picked) >= 220: break
STREETS = ["Elm", "Oak", "Maple", "Birch", "Cedar", "Walnut", "Lakeview", "Harbor", "Mill", "Prospect", "Summit", "Grove", "Ridge", "Sunset", "Willow"]
out = []
for i, (x, y, kind, area) in enumerate(picked):
    d = math.hypot(x, y)
    hood = 1.0 + 0.35 * math.exp(-((d - 5000) / 3500) ** 2) + (0.25 if x < -4000 else 0.0)   # west side and mid-ring are nicer
    if kind == "apartment":
        units_area = 75.0
        rent = int(round((180 + units_area * 1.6) * hood * (1.25 if d < 1500 else 1.0) / 10)) * 10
        out.append({"id": i, "kind": "apartment", "x": round(x, 1), "z": round(-y, 1), "address": f"{rng.randint(100, 2999)} {rng.choice(STREETS)} Ave, Apt {rng.randint(1, 24)}",
                    "rent_week": rent, "price": 0, "garage": False})
    else:
        price = int(round((40000 + area * 900) * hood / 1000)) * 1000
        rent = int(round(price * 0.0028 / 10)) * 10
        out.append({"id": i, "kind": "house", "x": round(x, 1), "z": round(-y, 1), "address": f"{rng.randint(100, 4999)} {rng.choice(STREETS)} St",
                    "rent_week": rent, "price": price, "garage": rng.random() < 0.7})
json.dump({"_doc": "made by tools/pipeline/make_homes.py; made-up addresses; x/z world metres", "homes": out}, open(OUT, "w"))
print(len(out), sum(1 for h in out if h["kind"] == "house"), "houses")
