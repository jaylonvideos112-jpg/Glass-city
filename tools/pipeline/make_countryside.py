"""Made-up countryside between the real-data box and the island coast (owner decision 2026-11-15).

usage: make_countryside.py <island.json> <osm tiles dir> <out.json>
Writes OSM-style elements (ways with inline geometry, tag "fictional"="yes") that build_city.py reads like any tile:
  * every real road that leaves the real box continues outward and ends on a coast road that loops the island
  * farmsteads (house, barn, sometimes a silo) along the country roads, with driveways
  * woodlots, and a few small lakeside villages with a street grid, houses, a church and a general store
All randomness is seeded, so the same inputs always give the same land."""
import json, glob, math, os, random, sys
from shapely.geometry import Polygon, Point, LineString, box, MultiLineString
from shapely.ops import unary_union, nearest_points
from shapely.strtree import STRtree
from shapely import affinity

ISL, TILES, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
LAT0, LON0 = 41.6528, -83.5379; R = 6378137.0; C = math.cos(math.radians(LAT0))
def P(lat, lon): return ((lon - LON0) * math.pi / 180 * R * C, (lat - LAT0) * math.pi / 180 * R)
def LL(x, y): return (LAT0 + y / R * 180 / math.pi, LON0 + x / (R * C) * 180 / math.pi)
BANK = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "source_data", "name_bank.txt")).read().split()

isl = json.load(open(ISL))
S, W, N, E = isl["real"]
x0, y0 = P(S, W); x1, y1 = P(N, E)
REAL = box(x0, y0, x1, y1)
ISLAND = Polygon([P(a, b) for a, b in isl["ring"]], [[P(a, b) for a, b in h] for h in isl.get("holes", [])]).buffer(0)
BAND = ISLAND.difference(REAL)                      # the made-up land
INNER = ISLAND.buffer(-60)                          # keep clear of the beach
rng = random.Random(20261115)
els = []
nid = [9_000_000_000_000]
wid = [9_100_000_000]
def new_node():
    nid[0] += 1; return nid[0]
def way(tags, pts, nodes=None, closed=False):
    if closed and pts[0] != pts[-1]: pts = list(pts) + [pts[0]]
    wid[0] += 1
    if nodes is None:
        nodes = [new_node() for _ in pts]
        if closed: nodes[-1] = nodes[0]
    tags = dict(tags); tags["fictional"] = "yes"
    els.append({"type": "way", "id": wid[0], "tags": tags, "nodes": nodes,
                "geometry": [dict(zip(("lat", "lon"), LL(x, y))) for x, y in pts]})
    return wid[0]
def pname(kind):
    return f"{BANK[rng.randrange(len(BANK))]} {kind}"

# ------------------------------------------------------------------ 1. coast road around the island
_ib = ISLAND.buffer(-420)
if _ib.geom_type != "Polygon": _ib = max(_ib.geoms, key=lambda a: a.area)
coast_road_line = _ib.exterior
cr = coast_road_line.intersection(BAND.buffer(-150))
coast_parts = [g for g in (cr.geoms if hasattr(cr, "geoms") else [cr]) if g.geom_type == "LineString" and g.length > 800]
coast_roads = []          # (LineString, [node ids], way id)
for g in coast_parts:
    g = g.simplify(8)
    n = max(2, int(g.length / 60))
    pts = [g.interpolate(i / n, normalized=True) for i in range(n + 1)]
    pts = [(q.x, q.y) for q in pts]
    nodes = [new_node() for _ in pts]
    w = way({"highway": "secondary", "name": "Lakeshore Parkway", "maxspeed": "45 mph"}, pts, nodes)
    coast_roads.append((LineString(pts), nodes, w, pts))
print("coast road pieces", len(coast_roads), "km", round(sum(c[0].length for c in coast_roads) / 1000, 1))

def snap_to_coast(p):
    """nearest vertex on the coast road: (node id, point)"""
    best = None
    for line, nodes, w, pts in coast_roads:
        for i, q in enumerate(pts):
            d = math.hypot(q[0] - p[0], q[1] - p[1])
            if best is None or d < best[0]: best = (d, nodes[i], q)
    return best

# ------------------------------------------------------------------ 2. continue every real road that leaves the box
CLS = {"motorway": 0, "trunk": 1, "primary": 2, "secondary": 3, "tertiary": 4, "unclassified": 5, "residential": 5}
crossings = []
for f in glob.glob(os.path.join(TILES, "*.json")):
    for e in json.load(open(f))["elements"]:
        t = e.get("tags", {}); hw = t.get("highway", "")
        base = hw.replace("_link", "")
        if e["type"] != "way" or base not in CLS or hw.endswith("_link"): continue
        g = e.get("geometry", []); nodes = e.get("nodes", [])
        if len(g) < 2 or len(nodes) != len(g): continue
        pts = [P(q["lat"], q["lon"]) for q in g]
        for i in range(len(pts) - 1):
            a, b = Point(pts[i]), Point(pts[i + 1])
            ina, inb = REAL.contains(a), REAL.contains(b)
            if ina != inb:
                inside, outside = (i, i + 1) if ina else (i + 1, i)
                crossings.append((CLS[base], nodes[inside], pts[inside], pts[outside], t))
crossings.sort(key=lambda c: c[0])
kept = []
for c in crossings:
    if all(math.hypot(c[2][0] - k[2][0], c[2][1] - k[2][1]) > (700 if c[0] <= 2 else 350) for k in kept): kept.append(c)
print("roads leaving the real box", len(crossings), "continued", len(kept))

country_roads = []        # LineStrings of made-up roads (for farm placement)
for cls, n_in, pin, pout, t in kept:
    hw = {0: "motorway", 1: "trunk", 2: "primary", 3: "secondary", 4: "tertiary"}.get(cls, "unclassified")
    dx, dy = pout[0] - pin[0], pout[1] - pin[1]; l = math.hypot(dx, dy) or 1
    dx, dy = dx / l, dy / l
    # outward normal of the box side we cross
    q = REAL.exterior.interpolate(REAL.exterior.project(Point(pout)))
    if abs(q.x - x0) < 1: nx, ny = -1, 0
    elif abs(q.x - x1) < 1: nx, ny = 1, 0
    elif abs(q.y - y0) < 1: nx, ny = 0, -1
    else: nx, ny = 0, 1
    hx, hy = (dx + 2 * nx), (dy + 2 * ny); hl = math.hypot(hx, hy); hx, hy = hx / hl, hy / hl
    pts = [pin, pout]
    cur = pout; heading = math.atan2(hy, hx); ok = False
    for step in range(120):
        heading += rng.uniform(-0.06, 0.06)
        target = math.atan2(ny, nx)
        heading += 0.08 * math.sin(target - heading)
        nxt = (cur[0] + math.cos(heading) * 90, cur[1] + math.sin(heading) * 90)
        if not INNER.contains(Point(nxt)) or ISLAND.exterior.distance(Point(nxt)) < 520:
            ok = True; break
        pts.append(nxt); cur = nxt
    sn = snap_to_coast(cur) if coast_roads else None
    nodes = [n_in] + [new_node() for _ in pts[1:]]
    if ok and sn and sn[0] < 900:
        pts.append(sn[2]); nodes.append(sn[1])
    if len(pts) < 3: continue
    name = t.get("name") or pname("Road")
    tags = {"highway": hw, "name": name}
    if t.get("lanes"): tags["lanes"] = t["lanes"]
    if t.get("oneway"): tags["oneway"] = t["oneway"]
    if t.get("maxspeed"): tags["maxspeed"] = t["maxspeed"]
    way(tags, pts, nodes)
    if cls >= 2: country_roads.append(LineString(pts[1:]))

# ------------------------------------------------------------------ 3. villages on the coast road
VILLAGE_NAMES = ["Heron Point", "Harbor Bend", "Marsh Landing", "Walleye Cove", "Cattail Corners", "Lighthouse Bay"]
villages = []
road_union = unary_union([c[0] for c in coast_roads] + country_roads)
for k in range(5):
    line, nodes, w, pts = coast_roads[rng.randrange(len(coast_roads))]
    if line.length < 3000: continue
    t0 = rng.uniform(0.15, 0.85)
    c = line.interpolate(t0, normalized=True)
    if any(c.distance(v) < 7000 for v in villages) or REAL.distance(c) < 900: continue
    villages.append(c)
    a = line.interpolate(min(1, t0 + 0.002), normalized=True)
    ang = math.atan2(a.y - c.y, a.x - c.x)
    # grid: 4 streets along the coast road, 3 cross streets inland
    inl = ang - math.pi / 2
    if not ISLAND.buffer(-900).contains(Point(c.x + math.cos(inl) * 300, c.y + math.sin(inl) * 300)): inl += math.pi
    ux, uy = math.cos(ang), math.sin(ang); vx, vy = math.cos(inl), math.sin(inl)
    name = VILLAGE_NAMES[len(villages) - 1]
    els.append({"type": "node", "id": new_node(), "lat": LL(c.x + vx * 200, c.y + vy * 200)[0], "lon": LL(c.x + vx * 200, c.y + vy * 200)[1],
                "tags": {"place": "village", "name": name, "fictional": "yes"}})
    streets = []
    for j in range(1, 4):   # parallel streets
        o = j * 110
        p0 = (c.x - ux * 380 + vx * o, c.y - uy * 380 + vy * o); p1 = (c.x + ux * 380 + vx * o, c.y + uy * 380 + vy * o)
        way({"highway": "residential", "name": pname("Street"), "sidewalk": "both"}, [p0, p1]); streets.append(LineString([p0, p1]))
    for i in (-1, 0, 1):    # cross streets from the coast road inland
        p0 = (c.x + ux * i * 260, c.y + uy * i * 260); p1 = (p0[0] + vx * 360, p0[1] + vy * 360)
        sn = snap_to_coast(p0)
        pts2 = [sn[2], p1]; nodes2 = [sn[1], new_node()]
        way({"highway": "tertiary" if i == 0 else "residential", "name": (name.split()[0] + " Main Street") if i == 0 else pname("Avenue"), "sidewalk": "both"}, pts2, nodes2)
        streets.append(LineString(pts2))
    # houses along the parallel streets, shops + church on main street
    for s_ in streets:
        L = s_.length; dd = 18.0
        (sx0, sy0), (sx1, sy1) = s_.coords[0], s_.coords[-1]
        tx, ty = (sx1 - sx0) / L, (sy1 - sy0) / L
        while dd < L - 18:
            for side in (-1, 1):
                if rng.random() < 0.15: continue
                cx_, cy_ = sx0 + tx * dd + (-ty) * side * 19, sy0 + ty * dd + tx * side * 19
                if not INNER.contains(Point(cx_, cy_)) or REAL.distance(Point(cx_, cy_)) < 50: continue
                if road_union.distance(Point(cx_, cy_)) < 14: continue
                wdt, dep = rng.uniform(8, 11), rng.uniform(9, 13)
                rect_ = Polygon([(-wdt / 2, -dep / 2), (wdt / 2, -dep / 2), (wdt / 2, dep / 2), (-wdt / 2, dep / 2)])
                rect_ = affinity.translate(affinity.rotate(rect_, math.degrees(math.atan2(ty, tx)), origin=(0, 0)), cx_, cy_)
                way({"building": "house", "building:levels": str(rng.choice([1, 1, 2, 2, 2])), "roof:shape": rng.choice(["gabled", "gabled", "hipped"])},
                    list(rect_.exterior.coords)[:-1], closed=True)
            dd += rng.uniform(22, 30)
    for j, (kind, nm) in enumerate([("church", f"{name} Community Church"), ("retail", f"{name} General Store"), ("retail", f"{name} Diner"), ("retail", "Bait & Tackle")]):
        cx_, cy_ = c.x + ux * (j * 55 - 80) + vx * 40, c.y + uy * (j * 55 - 80) + vy * 40
        sz = (22, 30) if kind == "church" else (16, 20)
        rect_ = affinity.translate(affinity.rotate(Polygon([(-sz[0] / 2, -sz[1] / 2), (sz[0] / 2, -sz[1] / 2), (sz[0] / 2, sz[1] / 2), (-sz[0] / 2, sz[1] / 2)]), math.degrees(ang), origin=(0, 0)), cx_, cy_)
        way({"building": kind, "name": nm, "building:levels": "1" if kind != "church" else "2"}, list(rect_.exterior.coords)[:-1], closed=True)
print("villages", len(villages))

# ------------------------------------------------------------------ 4. farmsteads along the country roads
VILL = unary_union([v.buffer(900) for v in villages]) if villages else Polygon()
farm_count = 0
all_country = [c[0] for c in coast_roads] + country_roads
for line in all_country:
    L = line.length; dd = rng.uniform(150, 500)
    while dd < L - 100:
        p = line.interpolate(dd); a = line.interpolate(min(L, dd + 5))
        tx, ty = a.x - p.x, a.y - p.y; tl = math.hypot(tx, ty) or 1; tx, ty = tx / tl, ty / tl
        side = rng.choice((-1, 1)); nx_, ny_ = -ty * side, tx * side
        hx, hy = p.x + nx_ * 35, p.y + ny_ * 35
        if INNER.contains(Point(hx, hy)) and BAND.contains(Point(hx, hy)) and not VILL.contains(Point(hx, hy)) and REAL.distance(Point(hx, hy)) > 120 \
                and road_union.distance(Point(hx, hy)) > 25:
            ang = math.degrees(math.atan2(ty, tx))
            def bld(cx_, cy_, w_, d_, tags):
                r_ = affinity.translate(affinity.rotate(Polygon([(-w_ / 2, -d_ / 2), (w_ / 2, -d_ / 2), (w_ / 2, d_ / 2), (-w_ / 2, d_ / 2)]), ang, origin=(0, 0)), cx_, cy_)
                way(tags, list(r_.exterior.coords)[:-1], closed=True)
            bld(hx, hy, rng.uniform(10, 13), rng.uniform(8, 10), {"building": "farmhouse", "building:levels": "2", "roof:shape": "gabled"})
            bx_, by_ = hx + nx_ * 45 + tx * rng.uniform(-25, 25), hy + ny_ * 45 + ty * rng.uniform(-25, 25)
            bld(bx_, by_, rng.uniform(18, 28), rng.uniform(12, 16), {"building": "barn", "height": str(round(rng.uniform(8, 11), 1)), "roof:shape": "gabled", "roof:colour": rng.choice(["#8a2b22", "#5a5f63", "#7a3b2a"])})
            if rng.random() < 0.5:
                sx_, sy_ = bx_ + tx * 22, by_ + ty * 22
                ring = [(sx_ + 3 * math.cos(k * math.pi / 4), sy_ + 3 * math.sin(k * math.pi / 4)) for k in range(8)]
                way({"building": "silo", "height": str(round(rng.uniform(14, 20), 1)), "roof:shape": "dome"}, ring, closed=True)
            # driveway
            way({"highway": "service", "service": "driveway"}, [(p.x, p.y), (hx + nx_ * 8, hy + ny_ * 8), (bx_, by_)])
            farm_count += 1
        dd += rng.uniform(220, 520)
print("farmsteads", farm_count)

# ------------------------------------------------------------------ 5. woodlots and wetlands
taken = unary_union([road_union.buffer(30), VILL] + [Point(0, 0).buffer(0)])
wood = 0
for k in range(int(BAND.area / 1e6 * 1.6)):
    bx_, by_, bx1_, by1_ = BAND.bounds
    c = Point(rng.uniform(bx_, bx1_), rng.uniform(by_, by1_))
    if not BAND.buffer(-120).contains(c) or taken.distance(c) < 40: continue
    r0 = rng.uniform(90, 320)
    ring = [(c.x + r0 * (1 + 0.35 * math.sin(3 * t + k) + 0.2 * math.sin(7 * t + 2 * k)) * math.cos(t),
             c.y + r0 * 0.8 * (1 + 0.3 * math.sin(2 * t + k)) * math.sin(t)) for t in [i * 2 * math.pi / 28 for i in range(28)]]
    g = Polygon(ring).buffer(0).difference(taken).intersection(BAND.buffer(-80))
    for q in (g.geoms if hasattr(g, "geoms") else [g]):
        if q.geom_type == "Polygon" and q.area > 6000:
            way({"natural": "wood"} if rng.random() < 0.85 else {"natural": "wetland"}, list(q.exterior.coords)[:-1], closed=True)
            wood += 1
print("woodlots", wood)

# ------------------------------------------------------------------ 6. crop fields between the roads
farm_yards = unary_union([Polygon([P(q["lat"], q["lon"]) for q in e["geometry"]]).buffer(45) for e in els
                          if e["type"] == "way" and e["tags"].get("building") in ("farmhouse", "barn", "silo")])
woods_u = unary_union([Polygon([P(q["lat"], q["lon"]) for q in e["geometry"]]).buffer(0) for e in els
                       if e["type"] == "way" and e["tags"].get("natural") in ("wood", "wetland")])
road_lines = unary_union([LineString([P(q["lat"], q["lon"]) for q in e["geometry"]]) for e in els
                          if e["type"] == "way" and "highway" in e["tags"]] + [g for g in country_roads])
blocked = unary_union([road_lines.buffer(14), farm_yards, woods_u.buffer(8), VILL.buffer(200), REAL.buffer(30)])
CROPS = ["wheat", "maize", "soy", "soy", "maize", "hay", "plowed"]
bx_, by_, bx1_, by1_ = BAND.bounds
fields = 0
FW, FH = 320.0, 460.0
yy = by_
while yy < by1_:
    xx = bx_ + rng.uniform(-FW, 0)
    while xx < bx1_:
        w_ = FW * rng.uniform(0.7, 1.3)
        cell = box(xx + 4, yy + 4, xx + w_ - 4, yy + FH - 4)
        xx += w_
        if not BAND.intersects(cell): continue
        g = cell.intersection(INNER).difference(blocked)
        for q in (g.geoms if hasattr(g, "geoms") else [g]):
            if q.geom_type == "Polygon" and q.area > 9000:
                q = q.simplify(3)
                way({"landuse": "farmland", "crop": rng.choice(CROPS)}, list(q.exterior.coords)[:-1], closed=True)
                fields += 1
    yy += FH
print("fields", fields)

json.dump({"version": 0.6, "generator": "make_countryside.py", "elements": els}, open(OUT, "w"))
print("elements", len(els))
