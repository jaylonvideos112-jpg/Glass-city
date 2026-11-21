"""Fence textures for back-yard fences (build_city.py fences): textures/chainlink.png (RGBA galvanized diamond wire,
one tile = 0.6 m x 0.6 m, alpha-tested) and textures/fence_wood.png (weathered vertical privacy boards, one tile =
1.8 m wide x 1.8 m tall, a few boards replaced / darker, stains at the bottom).
usage: python3 tools/pipeline/make_fence_textures.py"""
import numpy as np, os
from PIL import Image, ImageFilter
R = os.path.join(os.path.dirname(__file__), "..", "..", "textures")
rng = np.random.default_rng(7)
# ---- chain link: 512 px = 0.6 m; diamonds ~5 cm -> 12 cells across
N = 512; cells = 12
y, x = np.mgrid[0:N, 0:N] / N * cells
d1 = np.abs(((x + y) % 1.0) - 0.5); d2 = np.abs(((x - y) % 1.0) - 0.5)
wire = np.clip(1 - np.minimum(d1, d2) / 0.06, 0, 1)
a = (wire > 0.35).astype(np.float32)
shade = 0.55 + 0.45 * wire
col = np.stack([shade * 168, shade * 172, shade * 170], -1)
col *= (1 - 0.15 * rng.random((N, N)))[..., None]                       # zinc speckle
img = np.dstack([np.clip(col, 0, 255), a * 255]).astype(np.uint8)
Image.fromarray(img, "RGBA").save(os.path.join(R, "chainlink.png"))
# ---- wood privacy boards: 1024 px = 1.8 m; boards 14 cm wide
W = 1024; img = np.zeros((W, W, 3), np.float32)
bw = int(W * 0.14 / 1.8)
base = np.array([128, 98, 70], np.float32)
yy = np.arange(W)[:, None]
for i in range(0, W, bw):
    t = rng.random(); w_ = min(bw, W - i)
    c = base * (0.75 + 0.35 * t) if t > 0.12 else np.array([165, 130, 92], np.float32)      # an odd newer board
    grain = 0.9 + 0.1 * np.sin(np.arange(w_)[None, :] * 0.9 + rng.random() * 6 + yy * 0.02 * rng.random())
    img[:, i:i + bw] = c * grain[..., None]
    img[:, i:i + 2] *= 0.45; img[:, i + w_ - 1:i + w_] *= 0.6               # gaps
    for nz in (0.18, 0.82):                                                   # nail pairs on the rails
        r0 = int(W * (1 - nz)); img[r0 - 3:r0 + 3, i + w_ // 3:i + w_ // 3 + 5] *= 0.5
img *= (0.65 + 0.35 * np.clip(np.arange(W) / (W * 0.25), 0, 1))[::-1, None, None] ** 0.5 * 1.0   # dark splash at the bottom
im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.6))
im.save(os.path.join(R, "fence_wood.png"))
print("fence textures written")
