"""LiDAR -> per-building measurements (height, eave, roof type, stepped tiers for big buildings).

usage: lidar_process.py <laz dir> <osm tiles dir> <out.pkl>
Step 1 buckets points into 500 m cells (plan coords, same projection as build_city.py).
Step 2 measures every OSM building footprint against the points.
"""
import sys, os, glob, math, json, pickle, time
import numpy as np, laspy, shapely
from shapely.geometry import Polygon, box, LineString
from shapely.ops import unary_union, polygonize
from shapely.geometry.polygon import orient
from multiprocessing import Pool

LAZ, OSM, OUT = sys.argv[1:4]
TMP = OUT + ".buckets"
LAT0, LON0 = 41.6528, -83.5379
R = 6378137.0; COSLAT = math.cos(math.radians(LAT0)); CELL = 500.0
T0 = time.time()
def log(*a): print(f"[{time.time()-T0:6.0f}s]", *a, flush=True)

def to_plan(mx, my):
    lon = mx / 20037508.34 * 180.0
    lat = np.degrees(np.arctan(np.exp(my * np.pi / 20037508.34))) * 2 - 90.0
    return (lon - LON0) * np.pi / 180 * R * COSLAT, (lat - LAT0) * np.pi / 180 * R

# ------------------------------------------------------------------ step 1: bucket points
def bucket_file(args):
    i, f = args
    l = laspy.read(f)
    cls = np.asarray(l.classification); rn = np.asarray(l.return_number)
    keep_g = cls == 2
    keep_n = ((cls == 1) | (cls == 6)) & (rn == 1)
    keep_b = cls == 17
    k = keep_g | keep_n | keep_b
    x, y = to_plan(np.asarray(l.x)[k], np.asarray(l.y)[k])
    z = np.asarray(l.z)[k].astype(np.float32)
    c = np.where(keep_g[k], 0, np.where(keep_b[k], 2, 1)).astype(np.uint8)
    bx = np.floor(x / CELL).astype(np.int32); by = np.floor(y / CELL).astype(np.int32)
    key = bx.astype(np.int64) * 100000 + by
    order = np.argsort(key, kind="stable")
    key, x, y, z, c = key[order], x[order], y[order], z[order], c[order]
    uk, starts = np.unique(key, return_index=True)
    ends = list(starts[1:]) + [len(key)]
    for kk, s, e in zip(uk, starts, ends):
        cx, cy = int(kk // 100000), int(kk % 100000)
        if cy > 50000: cx += 1; cy -= 100000   # handle negative modulo
        d = f"{TMP}/{cx}_{cy}"; os.makedirs(d, exist_ok=True)
        np.savez(f"{d}/{i}.npz", x=x[s:e].astype(np.float32), y=y[s:e].astype(np.float32), z=z[s:e], c=c[s:e])
    return len(z)

def load_cell(cx, cy):
    xs, ys, zs, cs = [], [], [], []
    for f in glob.glob(f"{TMP}/{cx}_{cy}/*.npz"):
        d = np.load(f); xs.append(d["x"]); ys.append(d["y"]); zs.append(d["z"]); cs.append(d["c"])
    if not xs: return None
    return np.concatenate(xs), np.concatenate(ys), np.concatenate(zs), np.concatenate(cs)

# ------------------------------------------------------------------ step 2: buildings
def P(lat, lon): return ((lon - LON0) * math.pi / 180 * R * COSLAT, (lat - LAT0) * math.pi / 180 * R)
def area_geom(e):
    if e["type"] == "way":
        pts = [P(g["lat"], g["lon"]) for g in e.get("geometry", []) if g]
        if len(pts) < 4: return None
        try:
            p = Polygon(pts); p = p if p.is_valid else p.buffer(0)
            return p if not p.is_empty else None
        except Exception: return None
    outers, inners = [], []
    for m in e.get("members", []):
        if m.get("type") != "way" or "geometry" not in m: continue
        pts = [P(g["lat"], g["lon"]) for g in m["geometry"] if g]
        if len(pts) > 1: (inners if m.get("role") == "inner" else outers).append(LineString(pts))
    if not outers: return None
    try:
        po = unary_union(list(polygonize(unary_union(outers))))
        if inners: po = po.difference(unary_union(list(polygonize(unary_union(inners)))))
        return po.buffer(0) if not po.is_empty else None
    except Exception: return None

class Grid:
    """Points of a 3x3 bucket neighbourhood with a 4 m cell index for fast bbox queries."""
    G = 4.0
    def __init__(self, arrs):
        self.x, self.y, self.z, self.c = arrs
        gx = np.floor(self.x / self.G).astype(np.int64); gy = np.floor(self.y / self.G).astype(np.int64)
        self.key = gx * 10_000_000 + gy
        o = np.argsort(self.key, kind="stable")
        self.x, self.y, self.z, self.c, self.key = self.x[o], self.y[o], self.z[o], self.c[o], self.key[o]
        self.uk, self.st = np.unique(self.key, return_index=True)
        self.en = np.append(self.st[1:], len(self.key))
    def query(self, x0, y0, x1, y1):
        idx = []
        for gx in range(int(math.floor(x0 / self.G)), int(math.floor(x1 / self.G)) + 1):
            lo = np.searchsorted(self.uk, gx * 10_000_000 + int(math.floor(y0 / self.G)))
            hi = np.searchsorted(self.uk, gx * 10_000_000 + int(math.floor(y1 / self.G)), side="right")
            for a in range(lo, hi):
                idx.append(np.arange(self.st[a], self.en[a]))
        return np.concatenate(idx) if idx else np.zeros(0, np.int64)

def measure(g, grid):
    x0, y0, x1, y1 = g.bounds
    idx = grid.query(x0 - 14, y0 - 14, x1 + 14, y1 + 14)
    if len(idx) < 5: return None
    x, y, z, c = grid.x[idx], grid.y[idx], grid.z[idx], grid.c[idx]
    ring = g.buffer(14).difference(g.buffer(1.5))
    gm = (c == 0) & shapely.contains_xy(ring, x, y)
    if gm.sum() < 3:
        gm = (c == 0)
        if gm.sum() < 3: return None
    ground = float(np.median(z[gm]))
    inner = g.buffer(-0.5) if g.area > 30 else g
    if inner.is_empty: inner = g
    im = (c == 1) & shapely.contains_xy(inner, x, y)
    zr = z[im] - ground
    keep = zr > 1.8
    if keep.sum() < 4: return {"g": ground, "n": int(keep.sum())}
    xr, yr, zr = x[im][keep], y[im][keep], zr[keep]
    h = float(np.percentile(zr, 96)); eave = float(np.percentile(zr, 12))
    out = {"g": ground, "n": int(len(zr)), "h": round(h, 2), "eave": round(eave, 2)}
    # roof shape on the min rotated rectangle frame
    rect = g.minimum_rotated_rectangle
    if isinstance(rect, Polygon) and len(zr) >= 12 and g.area < 900:
        cs = list(rect.exterior.coords)[:4]
        e0 = np.subtract(cs[1], cs[0]); e1 = np.subtract(cs[2], cs[1])
        if np.linalg.norm(e0) < np.linalg.norm(e1): e0, e1 = e1, e0
        ua = e0 / np.linalg.norm(e0); va = e1 / np.linalg.norm(e1)
        cx, cy = rect.centroid.x, rect.centroid.y
        u = (xr - cx) * ua[0] + (yr - cy) * ua[1]; v = (xr - cx) * va[0] + (yr - cy) * va[1]
        L, Wd = np.linalg.norm(e0) / 2, np.linalg.norm(e1) / 2
        def corr(a, b):
            if np.std(a) < 1e-6 or np.std(b) < 1e-6: return 0.0
            return float(np.corrcoef(a, b)[0, 1])
        rv = corr(zr, -np.abs(v) / max(Wd, 0.5)); ru = corr(zr, -np.abs(u) / max(L, 0.5))
        pitch = h - eave
        if pitch < 1.0: shape = "flat"
        elif rv > 0.45 and ru > 0.35: shape = "hip"
        elif rv > 0.45: shape = "gable"
        elif ru > 0.45: shape = "gable_cross"
        else: shape = "complex"
        out.update(roof=shape, rv=round(rv, 2), ru=round(ru, 2))
    # stepped tiers for big buildings (captures towers, setbacks, wings)
    if g.area > 800 and h > 12 and len(zr) > 60:
        C = 3.0
        gx = np.floor((xr - x0) / C).astype(int); gy = np.floor((yr - y0) / C).astype(int)
        nx, ny = gx.max() + 1, gy.max() + 1
        hm = np.full((nx, ny), np.nan, np.float32)
        np.fmax.at(hm, (gx, gy), zr.astype(np.float32)) if False else None
        for a, b, v_ in zip(gx, gy, zr):
            if not (hm[a, b] >= v_): hm[a, b] = v_
        vals = np.sort(hm[~np.isnan(hm)])
        # split height levels where there are big gaps; keep up to 4 tiers
        levels = [vals[0]]
        for v_ in vals[1:]:
            if v_ - levels[-1] > 5.0: levels.append(v_)
            else: levels[-1] = max(levels[-1], v_)
        tiers = []
        prev = 0.0
        for li, L_ in enumerate(levels[-5:]):
            lo_ = (levels[-5:][li - 1] + 2.0) if li > 0 else -1
            cells = [box(x0 + a * C, y0 + b * C, x0 + (a + 1) * C, y0 + (b + 1) * C)
                     for a, b in zip(*np.where(hm >= lo_))] if li > 0 else [g]
            reg = unary_union(cells).buffer(0.6).buffer(-0.6).intersection(g).simplify(0.8)
            if reg.is_empty or reg.area < 40: continue
            top = float(np.percentile(hm[hm >= lo_] if li > 0 else vals, 90))
            tiers.append([round(prev, 2), round(top, 2), reg.wkt])
            prev = top
        if len(tiers) >= 2: out["tiers"] = tiers
    return out

def do_cell(args):
    cx, cy, items = args
    arrs = [load_cell(cx + dx, cy + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)]
    arrs = [a for a in arrs if a is not None]
    if not arrs: return {}
    grid = Grid(tuple(np.concatenate([a[i] for a in arrs]) for i in range(4)))
    res = {}
    for key, wkt in items:
        try:
            m = measure(shapely.from_wkt(wkt), grid)
            if m: res[key] = m
        except Exception as ex:
            pass
    return res

if __name__ == "__main__":
    files = sorted(glob.glob(os.path.join(LAZ, "*.laz")))
    if not os.path.exists(TMP + "/.done"):
        os.makedirs(TMP, exist_ok=True)
        with Pool(2) as pool:
            n = 0
            for i, cnt in enumerate(pool.imap_unordered(bucket_file, list(enumerate(files)), chunksize=8)):
                n += cnt
                if i % 200 == 0: log("bucketed", i, "/", len(files), "points", n)
        open(TMP + "/.done", "w").write("ok")
    log("buckets ready")
    seen = set(); cells = {}
    for f in sorted(glob.glob(os.path.join(OSM, "*.json"))):
        for e in json.load(open(f))["elements"]:
            t = e.get("tags", {})
            if e["type"] == "node" or not ("building" in t or "building:part" in t): continue
            k = f"{e['type'][0]}{e['id']}"
            if k in seen: continue
            seen.add(k)
            g = area_geom(e)
            if g is None or g.area < 6: continue
            rp = g.representative_point()
            ck = (math.floor(rp.x / CELL), math.floor(rp.y / CELL))
            cells.setdefault(ck, []).append((k, g.wkt))
    log("buildings", len(seen), "cells", len(cells))
    out = {}
    jobs = [(cx, cy, it) for (cx, cy), it in cells.items()]
    with Pool(2) as pool:
        for i, r in enumerate(pool.imap_unordered(do_cell, jobs, chunksize=2)):
            out.update(r)
            if i % 100 == 0: log("cells", i, "/", len(jobs), "measured", len(out))
    pickle.dump(out, open(OUT, "wb"))
    hs = [v["h"] for v in out.values() if "h" in v]
    import collections
    log("DONE measured", len(out), "with height", len(hs), "roofs", collections.Counter(v.get("roof") for v in out.values()).most_common(),
        "tiered", sum(1 for v in out.values() if "tiers" in v))
