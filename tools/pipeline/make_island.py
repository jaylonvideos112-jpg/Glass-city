"""Island outline around the real-data area (owner decisions 2026-11-15): the real map stays whole; a band of made-up
countryside (2-6 km) surrounds it out to a natural coastline; real Lake Erie / Maumee Bay stays open to the lake.

usage: make_island.py <erie.json> <out island.json>
Writes {"real": [S, W, N, E], "ring": [[lat, lon], ...], "islets": [...]} in lat/lon."""
import json, math, random, sys
from shapely.geometry import Polygon, Point, LineString, box
from shapely.ops import unary_union, polygonize

ERIE, OUT = sys.argv[1], sys.argv[2]
REAL = (41.5115, -83.8060, 41.7325, -83.3110)          # S W N E: everything we have real data for (north = Michigan line)
LAT0, LON0 = 41.6528, -83.5379; C = math.cos(math.radians(LAT0))
toxy = lambda la, lo: ((lo - LON0) * 111.32 * C, (la - LAT0) * 110.57)          # km
tolatlon = lambda x, y: (LAT0 + y / 110.57, LON0 + x / (111.32 * C))

S, W, N, E = REAL
x0, y0 = toxy(S, W); x1, y1 = toxy(N, E)
rect = box(x0, y0, x1, y1)

# real Lake Erie inside the rect (faces of shore + rect holding a lake seed)
lines = [LineString([toxy(q["lat"], q["lon"]) for q in e["geometry"]]) for e in json.load(open(ERIE))["elements"] if len(e.get("geometry", [])) > 1]
cl = unary_union(lines).intersection(rect.buffer(0.5))
seeds = [Point(*toxy(41.70, -83.40)), Point(*toxy(41.725, -83.33)), Point(*toxy(41.72, -83.45))]
lake = unary_union([pg for pg in polygonize(unary_union([rect.buffer(0.5).exterior, cl])) if any(pg.contains(s) for s in seeds)])
lake_in = lake.intersection(rect)

# base outline: the rect pushed out by a slowly varying margin (2-6 km), then fractal coast detail
base = rect.buffer(3.6, join_style=1)
L = base.exterior; n = int(L.length / 0.04)
P = [L.interpolate(i / n, normalized=True) for i in range(n)]; P = [(q.x, q.y) for q in P]; Nn = len(P)
rnd = random.Random(1977)
terms = [(k, (2.0 * k ** -1.0 if k < 8 else 2.2 * k ** -1.3) * (0.5 + rnd.random()), rnd.uniform(0, 2 * math.pi)) for k in range(2, 1100)]
env = [(0.05, 0.06, 1.0), (0.27, 0.05, 1.2), (0.48, 0.07, 0.9), (0.72, 0.05, 1.3), (0.9, 0.04, 1.0)]
feats = [(0.06, 0.02, -1.6), (0.15, 0.012, +1.4), (0.29, 0.025, -1.8), (0.40, 0.010, +1.2), (0.53, 0.02, -1.5),
         (0.63, 0.009, +1.6), (0.79, 0.025, -1.7), (0.91, 0.015, +1.5)]
cx = sum(x for x, y in P) / Nn; cy = sum(y for x, y in P) / Nn
pts = []
for i in range(Nn):
    t = i / Nn
    lo = sum(a * math.sin(2 * math.pi * k * t + ph) for k, a, ph in terms if k < 40)
    hi = sum(a * math.sin(2 * math.pi * k * t + ph) for k, a, ph in terms if k >= 40)
    r = 0.35 + sum(w * math.exp(-((min(abs(t - c), 1 - abs(t - c))) / s) ** 2) for c, s, w in env)
    v = lo + hi * r
    for c, w, d in feats:
        dd = min(abs(t - c), 1 - abs(t - c)); v += d * math.exp(-(dd / w) ** 2)
    x0_, y0_ = P[i - 1]; x1_, y1_ = P[(i + 1) % Nn]; tx, ty = x1_ - x0_, y1_ - y0_; l = math.hypot(tx, ty) or 1
    nx, ny = ty / l, -tx / l
    if (P[i][0] - cx) * nx + (P[i][1] - cy) * ny < 0: nx, ny = -nx, -ny
    q = (P[i][0] + nx * v, P[i][1] + ny * v)
    # never closer than ~1.6 km to the real area: push such points out, keeping a little roughness
    qp = Point(q); dmin = 1.6 + 0.35 * hi * r
    if rect.contains(qp) or rect.exterior.distance(qp) < dmin:
        b = rect.exterior.interpolate(rect.exterior.project(qp))
        ux, uy = qp.x - b.x, qp.y - b.y; ul = math.hypot(ux, uy)
        if rect.contains(qp) or ul < 1e-6: ux, uy, ul = nx, ny, 1.0
        q = (b.x + ux / ul * max(dmin, 1.3), b.y + uy / ul * max(dmin, 1.3))
    pts.append(q)
outer = Polygon(pts).buffer(0)
if outer.geom_type != "Polygon": outer = max(outer.geoms, key=lambda a: a.area)

# keep the real lake open to the open lake: no made-up land in front of the real shore
# Maumee Bay becomes a real bay of the island: made-up land wraps around it, and a winding channel connects it to
# the open lake to the north-east (instead of a straight cut)
cx0, cy0 = toxy(41.722, -83.345)
cpts = []
for i in range(60):
    t = i / 59.0
    d = t * 11.0
    cpts.append((cx0 + d * math.cos(math.radians(38)) + 0.9 * math.sin(t * 7.0) , cy0 + d * math.sin(math.radians(38)) + 0.6 * math.sin(t * 4.0 + 1.0)))
chan = LineString(cpts)
widths = [1.6 + 0.9 * math.sin(i * 0.37) for i in range(len(cpts))]
channel = unary_union([LineString([cpts[i], cpts[i + 1]]).buffer(widths[i], quad_segs=8) for i in range(len(cpts) - 1)])
band = outer.difference(rect).difference(channel)
island = unary_union([rect.difference(lake_in), band]).buffer(-0.5).buffer(0.5)   # round off cut corners
if island.geom_type != "Polygon": island = max(island.geoms, key=lambda a: a.area)
lake_open = lake.union(channel).union(lake_in)
if island.geom_type != "Polygon": island = max(island.geoms, key=lambda a: a.area)
island = Polygon(island.exterior, [h for h in island.interiors]).simplify(0.004)

# a few small islands offshore
islets = []
for ang, dist, size, seed in [(200, 2.6, 0.6, 1), (228, 1.7, 0.28, 2), (305, 2.2, 0.45, 3), (130, 2.8, 0.75, 4), (160, 1.8, 0.3, 5), (250, 2.0, 0.35, 6)]:
    a = math.radians(ang); ray = LineString([(cx, cy), (cx + math.cos(a) * 60, cy + math.sin(a) * 60)])
    hit = ray.intersection(island.exterior)
    if hit.is_empty: continue
    hp = hit if hit.geom_type == "Point" else max(hit.geoms, key=lambda q: math.hypot(q.x - cx, q.y - cy))
    ix, iy = hp.x + math.cos(a) * dist, hp.y + math.sin(a) * dist
    ring = []
    for j in range(48):
        t = 2 * math.pi * j / 48; r = size * (1 + 0.3 * math.sin(2 * t + seed) + 0.18 * math.sin(5 * t + 2 * seed) + 0.08 * math.sin(11 * t))
        ring.append(tolatlon(ix + r * math.cos(t), iy + r * math.sin(t) * 0.75))
    if not Polygon([toxy(*p) for p in ring]).intersects(island.buffer(0.4)):
        islets.append([[round(a, 5), round(b, 5)] for a, b in ring])

out = {"_doc": "GLASS CITY island (owner 2026-11-15): 'real' = the real-data box [S, W, N, E]; 'ring' = coastline (lat, lon) with "
               "made-up countryside between the box and the coast; 'islets' = small offshore islands. Generated by "
               "tools/pipeline/make_island.py.",
       "real": list(REAL), "ring": [[round(a, 5), round(b, 5)] for a, b in (tolatlon(x, y) for x, y in island.exterior.coords)],
       "holes": [[[round(a, 5), round(b, 5)] for a, b in (tolatlon(x, y) for x, y in h.coords)] for h in island.interiors],
       "islets": islets}
json.dump(out, open(OUT, "w"))
band_area = island.difference(rect).area
print(f"island {island.area:.0f} km2 (real box {rect.area:.0f}, made-up land {band_area:.0f}), coast {island.exterior.length:.0f} km, islets {len(islets)}")
