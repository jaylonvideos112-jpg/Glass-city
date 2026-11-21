"""Bully-style texture art pass (owner, 2026-11-21: "4K upscaled Bully" look on modern geometry).

Makes a hand-painted-looking copy of every colour (albedo) texture into textures_bully/, same names and folders:
edge-preserving smoothing removes photo grain and grime while keeping brick courses, siding laps, cracks and
shapes; colours get Bully's cleaner, warmer, more saturated palette; grass is pushed to a lively green.
Normal / roughness / emission maps are not copied (the game keeps using the originals, at reduced normal strength).
The game picks textures_bully/ automatically when source_data/look.json says "style": "bully" (scripts/look.gd).
usage: python3 tools/pipeline/make_bully_textures.py [REPO]"""
import os, sys, glob
import numpy as np
import cv2

R = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", ".."))
SRC = os.path.join(R, "textures"); DST = os.path.join(R, "textures_bully")
SKIP = ("_nor", "_rough", "_emit", "_ao", "_disp", "_arm", "phone_map", "bar_")   # bar_* are signs (artwork already)

def paint(im, name):
    h, w = im.shape[:2]
    has_a = im.shape[2] == 4 if im.ndim == 3 else False
    rgb = im[..., :3]
    s = max(1.0, max(h, w) / 1024.0)
    out = cv2.edgePreservingFilter(rgb, flags=1, sigma_s=int(40 * s), sigma_r=0.3)
    hsv = cv2.cvtColor(out, cv2.COLOR_BGR2HSV).astype(np.float32)
    sat = 1.18
    if any(k in name for k in ("grass", "leaves", "forest", "lawn", "tree")):
        # lively green: pull hues toward green, more saturation and a touch brighter
        hsv[..., 0] = hsv[..., 0] * 0.55 + 45 * 0.45
        sat = 1.35; hsv[..., 2] *= 1.06
    hsv[..., 1] *= sat
    out = cv2.cvtColor(np.clip(hsv, 0, 255).astype(np.uint8), cv2.COLOR_HSV2BGR).astype(np.float32)
    out[..., 2] *= 1.035; out[..., 0] *= 0.975                      # warm
    out = np.clip(out, 0, 255).astype(np.uint8)
    return np.dstack([out, im[..., 3]]) if has_a else out

n = 0
for f in sorted(glob.glob(os.path.join(SRC, "**", "*.*"), recursive=True)):
    if not f.lower().endswith((".png", ".jpg", ".jpeg")) or "/_orig/" in f: continue
    b = os.path.basename(f).lower()
    if any(k in b for k in SKIP): continue
    rel = os.path.relpath(f, SRC); out = os.path.join(DST, rel)
    if os.path.exists(out) and os.path.getmtime(out) > os.path.getmtime(f): continue
    im = cv2.imread(f, cv2.IMREAD_UNCHANGED)
    if im is None or im.ndim < 3: continue
    os.makedirs(os.path.dirname(out), exist_ok=True)
    cv2.imwrite(out, paint(im, b), [cv2.IMWRITE_JPEG_QUALITY, 92] if out.lower().endswith((".jpg", ".jpeg")) else [])
    n += 1
print("painted %d textures -> %s" % (n, DST))
