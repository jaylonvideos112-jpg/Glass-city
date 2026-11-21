"""Pack the LiDAR terrain (lidar/dem, 4 m) into one coarse game grid: data/terrain.bin.
Header: b"TRZ1", x0, y0 (plan metres of the south-west corner), cell, W, H, raw size (f32 x3, i32 x2, u32),
then zlib of W*H uint16 heights in cm above DATUM - 20 m, rows from south (plan y0) to north, columns west to east.
The game (scripts/terrain.gd) uses it for "where is the ground here" (spawn spots, AI, tests); collision is exact.
usage: terrain_export.py DEM_DIR manifest.json out.bin [cell=16]"""
import sys, os, json, glob, math, struct
import numpy as np, cv2
DEM, MAN, OUT = sys.argv[1:4]; CELL = float(sys.argv[4]) if len(sys.argv) > 4 else 16.0
DATUM = 176.0
m = json.load(open(MAN)); bx0, by0, bx1, by1 = m["bbox"] if "bbox" in m else (None,) * 4
fs = glob.glob(os.path.join(DEM, "*.npz"))
cs = [tuple(map(int, os.path.basename(f)[:-4].split("_"))) for f in fs]
cx0, cy0 = min(c[0] for c in cs), min(c[1] for c in cs); cx1, cy1 = max(c[0] for c in cs), max(c[1] for c in cs)
k = int(500 / CELL); n = 125
W, H = (cx1 - cx0 + 1) * k, (cy1 - cy0 + 1) * k
G = np.full((H, W), int((174.4 - DATUM + 20) * 100), np.uint16)
for f, (cx, cy) in zip(fs, cs):
    t = np.load(f)["h"].astype(np.float32) / 100 + 150 - DATUM + 20        # metres above DATUM-20, row 0 = north
    t = cv2.resize(np.flipud(t), (k, k), interpolation=cv2.INTER_AREA)       # row 0 = south
    G[(cy - cy0) * k:(cy - cy0 + 1) * k, (cx - cx0) * k:(cx - cx0 + 1) * k] = np.clip(t * 100, 0, 65535).astype(np.uint16)
import zlib
raw = G.tobytes()
with open(OUT, "wb") as fo:
    fo.write(b"TRZ1" + struct.pack("<fffiiI", cx0 * 500.0, cy0 * 500.0, CELL, W, H, len(raw))); fo.write(zlib.compress(raw, 6))
print("terrain", W, H, os.path.getsize(OUT) // 1024, "KB")
