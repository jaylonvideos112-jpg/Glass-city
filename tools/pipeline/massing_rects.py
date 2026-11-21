"""Break a building's LiDAR roof into rectangular masses with their heights, in replica-local coordinates
(relative to the footprint centroid, the anchor tools/pipeline/replica_massing.py uses). Used to write replica specs.

usage: massing_rects.py WORK KEY [height bands, e.g. 3,9,13]
prints one line per rectangle: band, [cx, cy, w, d, angle], h10/h50/h97 above ground; writes /tmp/rects_<KEY>.json
"""
import sys, os, glob, math, json, pickle
import numpy as np, cv2
from shapely.geometry import Point
import shapely

WORK, KEY = sys.argv[1], sys.argv[2]
BANDS = [float(x) for x in sys.argv[3].split(",")] if len(sys.argv) > 3 else [2.5]
o = pickle.load(open(os.path.join(WORK, "lidar/osm_blds.pkl"), "rb"))
LID = {}
for f in ("lidar/county.pkl", "lidar/buildings.pkl"): LID.update(pickle.load(open(os.path.join(WORK, f), "rb")))
F = o[KEY][1]; ground = (LID.get(KEY) or {}).get("g")
x0, y0, x1, y1 = F.bounds; x0 -= 4; y0 -= 4; x1 += 4; y1 += 4
xs, ys, zs, cs = [], [], [], []
for cx in range(math.floor(x0 / 500), math.floor(x1 / 500) + 1):
    for cy in range(math.floor(y0 / 500), math.floor(y1 / 500) + 1):
        for f in glob.glob(os.path.join(WORK, f"lidar/buildings.pkl.buckets/{cx}_{cy}/*.npz")):
            d = np.load(f); xs.append(d["x"]); ys.append(d["y"]); zs.append(d["z"]); cs.append(d["c"])
x = np.concatenate(xs); y = np.concatenate(ys); z = np.concatenate(zs); c = np.concatenate(cs)
if ground is None:
    gm = (c == 0) & (x > x0) & (x < x1) & (y > y0) & (y < y1); ground = float(np.median(z[gm]))
m = (c == 1) & (x > x0) & (x < x1) & (y > y0) & (y < y1)
W, H = int(math.ceil(x1 - x0)), int(math.ceil(y1 - y0))
R = np.zeros((H, W), np.float32)
np.maximum.at(R, ((y1 - y[m]).astype(int).clip(0, H - 1), (x[m] - x0).astype(int).clip(0, W - 1)), z[m] - ground)
R = cv2.dilate(R, np.ones((3, 3), np.uint8))                  # 0.25 pts/m2: close the gaps between returns
gx, gy = np.meshgrid(x0 + np.arange(W) + 0.5, y1 - np.arange(H) - 0.5)
inF = shapely.contains_xy(F.buffer(0.5), gx, gy)
rr = F.minimum_rotated_rectangle; cs_ = list(rr.exterior.coords)
e = max(((cs_[i], cs_[i + 1]) for i in range(4)), key=lambda p: math.dist(*p))
ang = math.degrees(math.atan2(e[1][1] - e[0][1], e[1][0] - e[0][0]))
AX, AY = F.centroid.x, F.centroid.y

def maxrect(B):
    best = (0, 0, 0, 0, 0); h = np.zeros(B.shape[1], int)
    for i in range(B.shape[0]):
        h = np.where(B[i], h + 1, 0); st = []
        for j in range(B.shape[1] + 1):
            hj = h[j] if j < B.shape[1] else 0; s = j
            while st and st[-1][1] >= hj:
                s0, hh = st.pop()
                if hh * (j - s0) > best[0]: best = (hh * (j - s0), i - hh + 1, s0, i + 1, j)
                s = s0
            st.append((s, hj))
    return best

out = []
for bi, lo in enumerate(BANDS):
    hi = BANDS[bi + 1] if bi + 1 < len(BANDS) else 1e9
    mask = (R > lo) & inF
    # a higher band sits on top of this one: rectangles of this band cover the whole footprint at >= lo
    ctr = (W / 2, H / 2); Mx = cv2.getRotationMatrix2D(ctr, -ang, 1.0); Mi = cv2.invertAffineTransform(Mx)
    B = cv2.warpAffine(mask.astype(np.uint8), Mx, (W, H), flags=cv2.INTER_NEAREST) > 0
    Rr = cv2.warpAffine(R, Mx, (W, H), flags=cv2.INTER_NEAREST)
    tot = B.sum()
    while tot and B.sum() > 0.05 * tot:
        a, i0, j0, i1, j1 = maxrect(B)
        if a < 30 or min(i1 - i0, j1 - j0) < 4: break
        B[i0:i1, j0:j1] = False
        v = Rr[i0:i1, j0:j1]; v = v[v > lo]
        pts = []
        for u, w in ((j0, i0), (j1, i0), (j1, i1), (j0, i1)):
            uu = Mi[0, 0] * u + Mi[0, 1] * w + Mi[0, 2]; ww = Mi[1, 0] * u + Mi[1, 1] * w + Mi[1, 2]
            pts.append((x0 + uu, y1 - ww))
        cx = sum(p[0] for p in pts) / 4 - AX; cy = sum(p[1] for p in pts) / 4 - AY
        e0 = math.dist(pts[0], pts[1]); e1 = math.dist(pts[1], pts[2])
        a0 = math.degrees(math.atan2(pts[1][1] - pts[0][1], pts[1][0] - pts[0][0]))
        r = dict(band=lo, rect=[round(cx, 2), round(cy, 2), round(e0, 2), round(e1, 2), round(a0, 2)],
                 h10=round(float(np.percentile(v, 10)), 1) if len(v) else 0, h50=round(float(np.percentile(v, 50)), 1) if len(v) else 0,
                 h97=round(float(np.percentile(v, 97)), 1) if len(v) else 0)
        out.append(r); print(r)
json.dump(dict(key=KEY, anchor=[AX, AY], ground=ground, angle=ang, rects=out), open(f"/tmp/rects_{KEY}.json", "w"))
v = np.clip(R / max(1, R.max()) * 255, 0, 255).astype(np.uint8); col = cv2.applyColorMap(v, cv2.COLORMAP_JET); col[R == 0] = 0
cs2 = np.array([[(px - x0), (y1 - py)] for px, py in F.exterior.coords], np.int32)
cv2.polylines(col, [cs2], True, (255, 255, 255), 1)
cv2.imwrite(f"/tmp/rects_{KEY}.png", cv2.resize(col, (W * 4, H * 4), interpolation=cv2.INTER_NEAREST))
