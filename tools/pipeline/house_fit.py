"""Per-wing LiDAR fit for every house: splits each small-building footprint into rectangular wings (same split as
build_city.rect_parts) and measures each wing on its own - eave height, ridge height, roof shape (gable along /
gable across / hip / flat) - so one-storey additions, attached garages and porches get their real heights and
roofs instead of the whole house being extruded to one height with a guessed roof.

usage: house_fit.py <buckets dir> <buildings.pkl (lidar measurements: key -> {g, h, ...})> <osm_blds.pkl> <out.pkl>
out: key -> [{"rect": [(x, y) x4], "eave": m, "h": m, "shape": str, "n": points}, ...]   (heights above ground)
"""
import sys, os, glob, math, pickle, time
import numpy as np, shapely, shapely.affinity
from shapely.geometry import Polygon, box
from shapely.strtree import STRtree
from multiprocessing import Pool

BUCK, LIDF, BLDF, OUT = sys.argv[1:5]
CELL = 500.0

def _max_rect(M):
    H = np.zeros(M.shape[1], int); best = (0, 0, 0, 0, 0)
    for i in range(M.shape[0]):
        H = np.where(M[i], H + 1, 0); st = []
        for j in range(M.shape[1] + 1):
            hj = H[j] if j < M.shape[1] else 0
            start = j
            while st and st[-1][1] >= hj:
                s0, hh = st.pop()
                if hh * (j - s0) > best[0]: best = (hh * (j - s0), i - hh + 1, s0, i + 1, j)
                start = s0
            st.append((start, hj))
    return best

def wings_of(g, res=0.5, max_parts=4):
    """rectangular wings in the footprint's own frame (largest first); a near-rectangle is one wing."""
    rect = g.minimum_rotated_rectangle
    if not isinstance(rect, Polygon): return []
    cs = list(rect.exterior.coords)[:4]
    if g.area / max(rect.area, 1e-6) > 0.82: return [cs]
    if math.dist(cs[0], cs[1]) < math.dist(cs[1], cs[2]): cs = cs[1:] + cs[:1]
    ang = math.atan2(cs[1][1] - cs[0][1], cs[1][0] - cs[0][0]); ca, sa = math.cos(ang), math.sin(ang)
    ox, oy = g.centroid.x, g.centroid.y
    loc = shapely.affinity.affine_transform(g, [ca, sa, -sa, ca, -(ca * ox + sa * oy), -(-sa * ox + ca * oy)])
    x0, y0, x1, y1 = loc.bounds
    nx, ny = int(math.ceil((x1 - x0) / res)), int(math.ceil((y1 - y0) / res))
    if nx * ny > 40000 or nx < 4 or ny < 4: return [cs]
    gx, gy = np.meshgrid(x0 + (np.arange(nx) + 0.5) * res, y0 + (np.arange(ny) + 0.5) * res, indexing="ij")
    M = shapely.contains_xy(loc, gx, gy); total = M.sum(); parts = []
    while len(parts) < max_parts and M.sum() > 0.12 * total:
        a, i0, j0, i1, j1 = _max_rect(M)
        if a * res * res < 8.0 or min(i1 - i0, j1 - j0) * res < 2.5: break
        M[i0:i1, j0:j1] = False
        lx0, lx1, ly0, ly1 = x0 + i0 * res, x0 + i1 * res, y0 + j0 * res, y0 + j1 * res
        parts.append([(ox + ca * u - sa * v, oy + sa * u + ca * v) for u, v in ((lx0, ly0), (lx1, ly0), (lx1, ly1), (lx0, ly1))])
    return parts or [cs]

def classify(xr, yr, zr, cs):
    """roof shape of one rectangular wing from its LiDAR returns (heights above ground)."""
    e0 = np.subtract(cs[1], cs[0]); e1 = np.subtract(cs[2], cs[1])
    if np.linalg.norm(e0) < np.linalg.norm(e1): e0, e1 = e1, e0
    ua = e0 / np.linalg.norm(e0); va = e1 / np.linalg.norm(e1)
    cx = sum(p[0] for p in cs) / 4; cy = sum(p[1] for p in cs) / 4
    u = (xr - cx) * ua[0] + (yr - cy) * ua[1]; v = (xr - cx) * va[0] + (yr - cy) * va[1]
    L, Wd = np.linalg.norm(e0) / 2, np.linalg.norm(e1) / 2
    def corr(a, b):
        if np.std(a) < 1e-6 or np.std(b) < 1e-6: return 0.0
        return float(np.corrcoef(a, b)[0, 1])
    h = float(np.percentile(zr, 95)); eave = float(np.percentile(zr, 10))
    rv = corr(zr, -np.abs(v) / max(Wd, 0.5)); ru = corr(zr, -np.abs(u) / max(L, 0.5))
    if h - eave < 0.9: shape = "flat"
    elif rv > 0.4 and ru > 0.3: shape = "hip"
    elif rv >= ru and rv > 0.25: shape = "gable"
    elif ru > rv and ru > 0.25: shape = "gable_cross"
    else: shape = "gable"          # sloped but noisy: a ridge along the long side is by far the most common
    return h, eave, shape

def do_cell(name):
    cx, cy = map(int, name.split("_"))
    xs, ys, zs, cs_ = [], [], [], []
    for f in glob.glob(f"{BUCK}/{name}/*.npz"):
        d = np.load(f); xs.append(d["x"]); ys.append(d["y"]); zs.append(d["z"]); cs_.append(d["c"])
    if not xs: return {}
    x = np.concatenate(xs); y = np.concatenate(ys); z = np.concatenate(zs); c = np.concatenate(cs_)
    m = c == 1; x, y, z = x[m], y[m], z[m]
    out = {}
    for key, g in CELL_B.get(name, []):
        gz = LID.get(key, {}).get("g")
        if gz is None: continue
        bx0, by0, bx1, by1 = g.bounds
        sel = (x > bx0) & (x < bx1) & (y > by0) & (y < by1)
        if sel.sum() < 6: continue
        px, py, pz = x[sel], y[sel], z[sel] - gz
        inside = shapely.contains_xy(g.buffer(-0.3) if g.area > 30 else g, px, py)
        px, py, pz = px[inside], py[inside], pz[inside]
        keep = pz > 1.8
        px, py, pz = px[keep], py[keep], pz[keep]
        if len(pz) < 6: continue
        res = []
        for cs in wings_of(g):
            w = Polygon(cs)
            ins = shapely.contains_xy(w, px, py)
            n = int(ins.sum())
            if n >= 5:
                h, eave, shape = classify(px[ins], py[ins], pz[ins], cs)
                res.append({"rect": [tuple(map(float, p)) for p in cs], "h": round(h, 2), "eave": round(eave, 2), "shape": shape, "n": n})
            else:
                res.append({"rect": [tuple(map(float, p)) for p in cs], "n": n})
        out[key] = res
    return out

LID = {}
for f_ in LIDF.split(","): LID.update(pickle.load(open(f_, "rb")))     # OSM-keyed + county-footprint-keyed measurements
ONLY = os.environ.get("ONLY_PREFIX", "")
B = pickle.load(open(BLDF, "rb"))
CELL_B = {}
for k, (nm, g) in B.items():
    if ONLY and not k.startswith(ONLY): continue
    if not (25 < g.area < 700) or not g.is_valid or g.geom_type != "Polygon": continue
    c0 = g.centroid
    CELL_B.setdefault(f"{int(math.floor(c0.x / CELL))}_{int(math.floor(c0.y / CELL))}", []).append((k, g))

if __name__ == "__main__":
    cells = sorted(cc for cc in CELL_B if os.path.isdir(f"{BUCK}/{cc}"))
    print(len(cells), "cells", sum(len(CELL_B[c]) for c in cells), "houses", flush=True)
    t0 = time.time(); res = {}
    with Pool(2) as pool:
        for k, r in enumerate(pool.imap_unordered(do_cell, cells, chunksize=2)):
            res.update(r)
            if k % 100 == 0: print(f"[{time.time() - t0:6.0f}s] {k}/{len(cells)} houses {len(res)}", flush=True)
    pickle.dump(res, open(OUT, "wb"))
    import collections
    print("DONE", len(res), "houses", collections.Counter(len(v) for v in res.values()).most_common(5),
          collections.Counter(w.get("shape") for v in res.values() for w in v).most_common(), flush=True)
