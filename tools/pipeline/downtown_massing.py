"""Exact downtown massing from full-resolution LiDAR.

For every building footprint inside the downtown ring: rasterize first-return heights at 0.5 m,
find the building's real height levels (roof, setbacks, towers, penthouses), and turn each level into
an extruded polygon.  Output: {key: {"h", "tiers": [(z0, z1, wkt), ...], "ground"}} merged over LID.
usage: downtown_massing.py <laz dir> <county_osm.json> <osm tiles dir> <ring.json> <out.pkl>
"""
import sys, os, glob, json, math, pickle
import numpy as np, laspy
from shapely.geometry import Polygon, Point, shape, box
from shapely.ops import unary_union
from shapely.validation import make_valid
from scipy import ndimage
from rasterio import features
from rasterio.transform import from_origin

LAZ, COUNTY, OSM, RING, OUT = sys.argv[1:6]
LAT0, LON0 = 41.6528, -83.5379; R = 6378137.0; C = math.cos(math.radians(LAT0))
def P(lat, lon): return ((lon - LON0) * math.pi / 180 * R * C, (lat - LAT0) * math.pi / 180 * R)
ring = Polygon([P(a, b) for a, b in json.load(open(RING))]).buffer(30)

# ---------------- points
xs, ys, zs, cs = [], [], [], []
for f in glob.glob(f"{LAZ}/*.laz"):
    l = laspy.read(f)
    mx, my = np.asarray(l.x), np.asarray(l.y)
    lon = mx / 20037508.34 * 180.0
    lat = np.degrees(np.arctan(np.exp(my * np.pi / 20037508.34))) * 2 - 90.0
    x = (lon - LON0) * np.pi / 180 * R * C; y = (lat - LAT0) * np.pi / 180 * R
    cl = np.asarray(l.classification); rn = np.asarray(l.return_number)
    rb = ring.bounds
    k = ((cl == 2) | (((cl == 1) | (cl == 6)) & (rn == 1))) & (x > rb[0]) & (x < rb[2]) & (y > rb[1]) & (y < rb[3])
    xs.append(x[k]); ys.append(y[k]); zs.append(np.asarray(l.z)[k]); cs.append(cl[k])
X = np.concatenate(xs); Y = np.concatenate(ys); Z = np.concatenate(zs).astype(np.float32); CL = np.concatenate(cs)
print("points", len(X), flush=True)
G = 0.5
x0, y0 = X.min(), Y.max()
W = int((X.max() - x0) / G) + 1; H = int((y0 - Y.min()) / G) + 1
ci = ((X - x0) / G).astype(np.int32); ri = ((y0 - Y) / G).astype(np.int32)
top = np.full((H, W), np.nan, np.float32); gnd = np.full((H, W), np.nan, np.float32)
nb = CL != 2
# max per cell (vectorised): sort by z then assign
o = np.argsort(Z[nb]); top[ri[nb][o], ci[nb][o]] = Z[nb][o]
g = CL == 2; o = np.argsort(-Z[g]); gnd[ri[g][o], ci[g][o]] = Z[g][o]
# ground surface: fill holes with nearest ground value
mask = np.isnan(gnd)
idx = ndimage.distance_transform_edt(mask, return_distances=False, return_indices=True)
gnd = gnd[tuple(idx)]
gnd = ndimage.median_filter(gnd, size=9)
# fill small gaps in roofs (no-return glass/dark roofs) with a max filter then median
tmask = np.isnan(top)
tf = np.where(tmask, -9999, top)
tf = np.where(tmask, ndimage.maximum_filter(tf, size=3), tf)
top = np.where(tf < -9000, np.nan, tf)
rel = top - gnd
print("grid", W, H, flush=True)
TR = from_origin(x0, y0, G, G)

# ---------------- footprints (county + OSM landmarks kept)
fps = []
for e in json.load(open(COUNTY))["elements"]:
    pg = Polygon([P(p["lat"], p["lon"]) for p in e["geometry"]])
    if not pg.is_valid: pg = make_valid(pg)
    if ring.contains(pg.representative_point()): fps.append((f"w{e['id']}", pg))
attach = json.load(open(os.path.join(os.path.dirname(COUNTY), "county_attach.json")))
for f in glob.glob(f"{OSM}/*.json"):
    for e in json.load(open(f))["elements"]:
        k = f"w{e['id']}"
        if k in attach and e.get("geometry"):
            pg = Polygon([P(p["lat"], p["lon"]) for p in e["geometry"]])
            if not pg.is_valid: pg = make_valid(pg)
            if ring.contains(pg.representative_point()): fps.append((k, pg))
print("footprints", len(fps), flush=True)

def levels_of(h, slender=True):
    """Distinct roof levels: histogram peaks of cell heights, merged when closer than 1.5 m."""
    h = h[h > 1.5]
    if h.size < 8: return []
    bins = np.arange(0, h.max() + 1.0, 0.5)
    hist, edges = np.histogram(h, bins)
    hist = ndimage.uniform_filter1d(hist.astype(float), 3)
    lv = []
    for i in range(1, len(hist) - 1):
        if hist[i] >= hist[i - 1] and hist[i] >= hist[i + 1] and hist[i] >= max(3, 0.012 * h.size):
            lv.append((edges[i] + 0.25, hist[i]))
    if not lv: lv = [(float(np.percentile(h, 90)), 1)]
    # slender tops (spires, crowns, towers on a podium): keep them if a handful of cells stand well above
    hs_ = np.sort(h)
    if slender and hs_.size >= 12 and hs_[-4] > max(z for z, _ in lv) + 3.0:
        lv.append((float(np.median(hs_[-4:])), 1))
    lv.sort()
    merged = []
    for z, w in lv:
        if merged and z - merged[-1][0] < 1.5:
            if w > merged[-1][1]: merged[-1] = (z, w)
        else: merged.append((z, w))
    return [z for z, _ in merged]

from shapely import affinity
from shapely.wkt import loads as wkt_loads
def clean_tier(geo, pg):
    """Raster outline -> clean architectural outline: whole footprint if it nearly fills it, else smoothed and
    squared to the building's own wall directions (from its footprint's minimum rotated rectangle)."""
    geo = geo.intersection(pg)
    if geo.is_empty: return geo
    if geo.area >= 0.85 * pg.area: return pg
    mrr = pg.minimum_rotated_rectangle
    cs = list(mrr.exterior.coords)
    ang = math.degrees(math.atan2(cs[1][1] - cs[0][1], cs[1][0] - cs[0][0]))
    o = pg.centroid
    g = affinity.rotate(geo, -ang, origin=o)
    g = g.buffer(1.0, join_style=2).buffer(-1.6, join_style=2).buffer(0.6, join_style=2)
    if g.is_empty: return g
    # square it up: snap vertices to a 0.5 m grid in the building frame, then drop collinear points
    from shapely.geometry import Polygon as _P, MultiPolygon as _MP
    def snap(poly):
        ext = [(round(x * 2) / 2, round(y * 2) / 2) for x, y in poly.exterior.coords]
        q = _P(ext).buffer(0)
        return q.simplify(0.7, preserve_topology=True)
    parts = [snap(q) for q in (g.geoms if g.geom_type == "MultiPolygon" else [g]) if q.area > 2]
    g = unary_union([q for q in parts if not q.is_empty])
    g = affinity.rotate(g, ang, origin=o)
    return g.intersection(pg)

out = {}
for n, (key, pg) in enumerate(fps):
    b = pg.bounds
    c0 = max(0, int((b[0] - x0) / G) - 1); c1 = min(W, int((b[2] - x0) / G) + 2)
    r0 = max(0, int((y0 - b[3]) / G) - 1); r1 = min(H, int((y0 - b[1]) / G) + 2)
    if c1 - c0 < 2 or r1 - r0 < 2: continue
    sub = rel[r0:r1, c0:c1]
    tr = from_origin(x0 + c0 * G, y0 - r0 * G, G, G)
    inside = features.rasterize([(pg, 1)], out_shape=sub.shape, transform=tr, fill=0, all_touched=False).astype(bool)
    hh = np.where(inside, sub, np.nan)
    vals = hh[~np.isnan(hh)]
    if vals.size < 8: continue
    lv = levels_of(vals, slender=pg.area < 8000)   # stadiums/arenas: light poles & cranes are not towers
    if not lv: continue
    # smooth so single noisy cells don't create spikes
    hs = ndimage.median_filter(np.nan_to_num(hh, nan=0.0), size=3)
    tiers, prev = [], 0.0
    for i, z in enumerate(lv):
        thr = z - 0.75 if i else 0.0
        m = (hs >= thr) & inside if i else inside
        m = ndimage.binary_opening(m, iterations=1) if (i and m.sum() > 40) else m
        if m.sum() < (3 if i else 1): continue
        polys = [shape(s) for s, v in features.shapes(m.astype(np.uint8), mask=m, transform=tr) if v == 1]
        geo = pg if not tiers else clean_tier(unary_union(polys), pg)
        if tiers:   # upper tiers must sit on the one below, and be at least ~3 m wide (no floating slivers)
            geo = geo.intersection(wkt_loads(tiers[-1][2])).buffer(-1.4, join_style=2).buffer(1.4, join_style=2)
            if geo.geom_type == "GeometryCollection":
                geo = unary_union([q for q in geo.geoms if q.geom_type in ("Polygon", "MultiPolygon")])
        if geo.is_empty or geo.area < (6 if i else 4): continue
        zbot = 0.0 if not tiers else tiers[-1][1]
        tiers.append((round(zbot, 2), round(float(z), 2), geo.wkt))
    if not tiers: continue
    ground = float(np.nanmedian(gnd[r0:r1, c0:c1][inside])) if inside.any() else None
    out[key] = {"h": tiers[-1][1], "tiers": tiers, "n": int(vals.size), "ground": ground, "exact": True}
    if n % 100 == 0: print("bldg", n, len(fps), flush=True)
pickle.dump(out, open(OUT, "wb"))
import collections
print("DONE", len(out), "tier counts", collections.Counter(len(v["tiers"]) for v in out.values()).most_common(8))
