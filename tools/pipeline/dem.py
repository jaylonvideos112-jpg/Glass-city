"""Bare-earth terrain from the LiDAR ground returns: a 4 m grid per 500 m bucket cell.

Ground points (class 0) are averaged per 4 m cell; rivers and lakes are pinned to the water surface so banks slope
down into them; everything else with no ground return (under buildings, dense trees) is filled from its
surroundings by normalized convolution at growing radii; a light median removes leftovers.

usage: dem.py WORK [cx0 cy0 cx1 cy1]      -> WORK/lidar/dem/<cx>_<cy>.npz  (h: uint16 cm above 150 m, 125x125,
                                              row 0 = north edge, col 0 = west edge)
"""
import sys, os, glob, math, pickle
import numpy as np, cv2, shapely
from shapely.geometry import box
from shapely.strtree import STRtree

WORK = sys.argv[1]
BUCK = os.path.join(WORK, "lidar/buildings.pkl.buckets")
OUT = os.path.join(WORK, "lidar/dem"); os.makedirs(OUT, exist_ok=True)
CELL, RES, BLK, MARG = 500.0, 4.0, 4, 1           # 500 m buckets, 4 m grid, 4x4-cell blocks, 1-cell margin
WATER_Z = 174.4                                   # Maumee / Lake Erie surface (m)
N = int(CELL / RES)
water = pickle.load(open(os.path.join(WORK, "lidar/water.pkl"), "rb"))
wtree = STRtree(water)
cells = sorted({tuple(map(int, os.path.basename(d).split("_"))) for d in glob.glob(BUCK + "/*_*")})
if len(sys.argv) > 5:
    a, b, c, d = map(int, sys.argv[2:6]); cells = [(x, y) for x, y in cells if a <= x <= c and b <= y <= d]
cellset = set(cells)
blocks = sorted({(x // BLK, y // BLK) for x, y in cells})
print("cells", len(cells), "blocks", len(blocks), flush=True)


def load(cx, cy):
    xs, ys, zs = [], [], []
    for f in glob.glob(f"{BUCK}/{cx}_{cy}/*.npz"):
        d = np.load(f); m = d["c"] == 0
        if m.any(): xs.append(d["x"][m]); ys.append(d["y"][m]); zs.append(d["z"][m])
    if not xs: return None
    return np.concatenate(xs), np.concatenate(ys), np.concatenate(zs)


def fill(Z, K):
    """normalized convolution: fill unknown cells (K == 0) from known neighbours, small radius first."""
    Z = Z.copy(); K = K.astype(np.float32)
    for s in (1, 2, 4, 8, 16, 32, 64):
        if K.min() > 0: break
        k = int(s * 3) | 1
        num = cv2.GaussianBlur(Z * K, (k, k), s); den = cv2.GaussianBlur(K, (k, k), s)
        ok = (K == 0) & (den > 1e-3)
        Z[ok] = num[ok] / den[ok]; K[ok] = 1.0
    return Z, K


done = {os.path.basename(f)[:-4] for f in glob.glob(OUT + "/*.npz")}
for bi, (bx, by) in enumerate(blocks):
    mine = [(x, y) for x in range(bx * BLK, bx * BLK + BLK) for y in range(by * BLK, by * BLK + BLK) if (x, y) in cellset]
    if all(f"{x}_{y}" in done for x, y in mine): continue
    x0c, y0c = bx * BLK - MARG, by * BLK - MARG; W = (BLK + 2 * MARG) * N
    X0, Y1 = x0c * CELL, (y0c + BLK + 2 * MARG) * CELL          # block west edge, north edge
    S = np.zeros((W, W), np.float64); C = np.zeros((W, W), np.float64)
    for x in range(x0c, x0c + BLK + 2 * MARG):
        for y in range(y0c, y0c + BLK + 2 * MARG):
            if (x, y) not in cellset: continue
            p = load(x, y)
            if p is None: continue
            c = ((p[0] - X0) / RES).astype(int); r = ((Y1 - p[1]) / RES).astype(int)
            ok = (c >= 0) & (c < W) & (r >= 0) & (r < W)
            np.add.at(S, (r[ok], c[ok]), p[2][ok]); np.add.at(C, (r[ok], c[ok]), 1)
    Z = np.where(C > 0, S / np.maximum(C, 1), 0).astype(np.float32); K = (C > 0)
    # water: pin to the surface (and drop stray ground returns on it - docks, boats)
    bb = box(X0, Y1 - W * RES, X0 + W * RES, Y1)
    ws = [water[i] for i in wtree.query(bb)]
    if ws:
        gx, gy = np.meshgrid(X0 + (np.arange(W) + 0.5) * RES, Y1 - (np.arange(W) + 0.5) * RES)
        wm = np.zeros((W, W), bool)
        for g in ws:
            if g.intersects(bb): wm |= shapely.contains_xy(g.intersection(bb), gx, gy)
        wm = cv2.erode(wm.astype(np.uint8), np.ones((2, 2), np.uint8)).astype(bool)   # keep the bank cell itself
        Z[wm] = WATER_Z; K = K | wm
    if K.sum() == 0:
        Z[:] = WATER_Z; K[:] = True
    Z, K = fill(Z, K)
    Z[K == 0] = WATER_Z
    Z = cv2.medianBlur(Z, 3)
    for x, y in mine:
        c0 = (x - x0c) * N; r0 = (y0c + BLK + 2 * MARG - 1 - y) * N
        tile = Z[r0:r0 + N, c0:c0 + N]
        np.savez_compressed(f"{OUT}/{x}_{y}.npz", h=np.clip((tile - 150.0) * 100, 0, 65535).astype(np.uint16))
    if bi % 20 == 0: print(bi, len(blocks), flush=True)
print("done")
