"""Offline preview of shaders/painted.gdshader: Kuwahara filter + warm grade applied to a screenshot.
usage: python3 paint_post.py IN.png OUT.png [radius]"""
# offline copy of shaders/painted.gdshader (Kuwahara r=3 + warm grade) for preview on the CPU-only build box
import sys, numpy as np
from PIL import Image
from scipy.ndimage import uniform_filter
src, dst = sys.argv[1], sys.argv[2]; r = int(sys.argv[3]) if len(sys.argv) > 3 else 3
im = np.asarray(Image.open(src).convert("RGB")).astype(np.float32) / 255
k = r + 1
m = uniform_filter(im, (k, k, 1)); m2 = uniform_filter(im * im, (k, k, 1))
var = np.abs(m2 - m * m).sum(2)
H, W = var.shape
def shift(a, dy, dx):
    return np.roll(np.roll(a, dy, 0), dx, 1)
# sector centres offset by half the window in each diagonal
o = r // 2 + (r % 2)
cands = [(shift(m, oy, ox), shift(var, oy, ox)) for oy in (o, -o) for ox in (o, -o)]
best = cands[0][0].copy(); bv = cands[0][1].copy()
for c, v in cands[1:]:
    s = v < bv; best[s] = c[s]; bv[s] = v[s]
col = best
l = (col * [0.299, 0.587, 0.114]).sum(2, keepdims=True)
col = l + (col - l) * 1.22
col = col + 0.06 * (1 - col) * (1 - np.clip(l / 0.5, 0, 1) ** 2 * (3 - 2 * np.clip(l / 0.5, 0, 1)))
wt = (1 - np.abs(l - 0.5) * 2)
col[..., 0:1] += 0.05 * wt; col[..., 2:3] -= 0.03 * wt
Image.fromarray((np.clip(col, 0, 1) * 255).astype(np.uint8)).save(dst)
