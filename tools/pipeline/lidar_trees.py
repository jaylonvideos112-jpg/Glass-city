"""LiDAR -> individual trees (position, height, crown radius).

usage: lidar_trees.py <buckets dir> <buildings.pkl (key -> (name, Polygon))> <out.json>

The county LiDAR has no vegetation class: trees are the first-return 'unclassified' points that stand
well above the ground and are not on a building. Per 500 m bucket cell we
  1. grid ground points into a 2 m DTM (min z, holes filled from neighbours),
  2. grid non-ground first returns into a 1 m canopy height model (max z - DTM),
  3. blank out building footprints (+1.5 m) so roofs and parapets don't become trees,
  4. smooth and find local maxima (window grows with height) -> tree tops,
  5. measure the crown radius as the mean distance at which the canopy drops below 55% of the top.
Output: {"trees": [[x, z_game, h, r], ...]} in game coordinates (x east, z = -north).
"""
import sys, os, glob, json, math, pickle, time
import numpy as np
from scipy import ndimage
from multiprocessing import Pool
from shapely.geometry import box
from shapely.strtree import STRtree

BUCK, BLD, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
CELL = 500.0
B = pickle.load(open(BLD, "rb"))
POLYS = [g for _, g in B.values() if g.is_valid and g.area > 4]
TREE = STRtree(POLYS)

def raster_mask(x0, y0, n, res, polys):
    """boolean mask of building footprints (buffered) on an n x n grid at res metres."""
    from matplotlib.path import Path
    m = np.zeros((n, n), bool)
    xs = x0 + (np.arange(n) + 0.5) * res
    for p in polys:
        g = p.buffer(1.5, join_style=2)
        if g.geom_type == "MultiPolygon": parts = list(g.geoms)
        else: parts = [g]
        for q in parts:
            bx0, by0, bx1, by1 = q.bounds
            i0 = max(0, int((bx0 - x0) / res)); i1 = min(n, int((bx1 - x0) / res) + 1)
            j0 = max(0, int((by0 - y0) / res)); j1 = min(n, int((by1 - y0) / res) + 1)
            if i0 >= i1 or j0 >= j1: continue
            gx, gy = np.meshgrid(x0 + (np.arange(i0, i1) + 0.5) * res, y0 + (np.arange(j0, j1) + 0.5) * res, indexing="ij")
            inside = Path(np.asarray(q.exterior.coords)).contains_points(np.c_[gx.ravel(), gy.ravel()]).reshape(gx.shape)
            m[i0:i1, j0:j1] |= inside
    return m

def do_cell(name):
    cx, cy = map(int, name.split("_"))
    xs, ys, zs, cs = [], [], [], []
    for f in glob.glob(f"{BUCK}/{name}/*.npz"):
        d = np.load(f); xs.append(d["x"]); ys.append(d["y"]); zs.append(d["z"]); cs.append(d["c"])
    if not xs: return []
    x = np.concatenate(xs); y = np.concatenate(ys); z = np.concatenate(zs); c = np.concatenate(cs)
    x0, y0 = cx * CELL, cy * CELL
    # --- DTM 2 m
    gn = int(CELL / 2)
    g = c == 0
    if g.sum() < 200: return []
    gi = np.clip(((x[g] - x0) / 2).astype(int), 0, gn - 1); gj = np.clip(((y[g] - y0) / 2).astype(int), 0, gn - 1)
    dtm = np.full((gn, gn), np.inf, np.float32)
    np.minimum.at(dtm, (gi, gj), z[g])
    holes = ~np.isfinite(dtm)
    if holes.all(): return []
    idx = ndimage.distance_transform_edt(holes, return_distances=False, return_indices=True)
    dtm = dtm[tuple(idx)]
    # --- CHM 2 m (the local LiDAR copy is ~0.25 non-ground pts/m2, so 1 m cells are mostly empty)
    RES = 2.0; n = int(CELL / RES)
    v = c == 1
    vi = np.clip(((x[v] - x0) / RES).astype(int), 0, n - 1); vj = np.clip(((y[v] - y0) / RES).astype(int), 0, n - 1)
    top = np.full((n, n), -np.inf, np.float32)
    np.maximum.at(top, (vi, vj), z[v])
    chm = np.where(np.isfinite(top), top - dtm, 0.0).astype(np.float32)
    chm[(chm < 2.0) | (chm > 45.0)] = 0.0
    near = [POLYS[i] for i in TREE.query(box(x0 - 3, y0 - 3, x0 + CELL + 3, y0 + CELL + 3))]
    bmask = raster_mask(x0, y0, n, RES, near) if near else np.zeros((n, n), bool)
    chm[bmask] = 0.0
    chm = ndimage.grey_closing(chm, size=3)          # fill the sampling gaps inside crowns
    chm[bmask] = 0.0
    support = ndimage.uniform_filter((chm > 2.5).astype(np.float32), 3)
    chm[support < 0.5] = 0.0                         # lone returns: wires, poles, light standards
    sm = ndimage.gaussian_filter(chm, 0.8)
    out = []
    for win, hmin, hmax in ((3, 4.0, 13.0), (5, 13.0, 60.0)):
        mx = ndimage.maximum_filter(sm, size=win)
        peaks = np.argwhere((sm == mx) & (sm >= hmin) & (sm < hmax))
        for i, j in peaks:
            h = float(chm[max(0, i - 1):i + 2, max(0, j - 1):j + 2].max())
            if h < 4.0: continue
            rs = []
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)):
                st = math.hypot(di, dj); k = 1
                while k < 8:
                    ii, jj = i + di * k, j + dj * k
                    if not (0 <= ii < n and 0 <= jj < n) or sm[ii, jj] < 0.5 * h: break
                    k += 1
                rs.append((k - 0.5) * st * RES)
            r = float(np.clip(np.mean(rs), 1.5, 12.0))
            out.append((round(x0 + (i + 0.5) * RES, 1), round(-(y0 + (j + 0.5) * RES), 1), round(h, 1), round(r, 1)))
    # suppress tops closer than 0.6 * crown radius of a taller neighbour
    out.sort(key=lambda t: -t[2]); keep = []
    grid = {}
    for t in out:
        k = (int(t[0] // 6), int(t[1] // 6)); bad = False
        for a in range(k[0] - 2, k[0] + 3):
            for b in range(k[1] - 2, k[1] + 3):
                for u in grid.get((a, b), ()):
                    if math.hypot(u[0] - t[0], u[1] - t[1]) < 0.6 * u[3]: bad = True; break
                if bad: break
            if bad: break
        if not bad: keep.append(t); grid.setdefault(k, []).append(t)
    return keep

if __name__ == "__main__":
    # only cells that hold game buildings (the island) - avoids the empty county / lake cells
    cells = set()
    for g in POLYS:
        c = g.centroid; cells.add(f"{int(math.floor(c.x / CELL))}_{int(math.floor(c.y / CELL))}")
    cells = sorted(cc for cc in cells if os.path.isdir(f"{BUCK}/{cc}"))
    print(len(cells), "cells", flush=True)
    t0 = time.time(); trees = []
    with Pool(2) as pool:
        for k, res in enumerate(pool.imap_unordered(do_cell, cells, chunksize=4)):
            trees += res
            if k % 100 == 0: print(f"[{time.time() - t0:7.0f}s] {k}/{len(cells)} trees {len(trees)}", flush=True)
    json.dump({"trees": trees}, open(OUT, "w"))
    print("DONE", len(trees), "trees", flush=True)
