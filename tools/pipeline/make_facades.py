#!/usr/bin/env python3
"""Rebuild the tiling facade textures with photo-scanned wall materials (CC0 Poly Haven, textures/pbr/).

For every facade texture the window layout of the original (textures/_orig/<name>.png, windows found from the
glossy mask <name>_rough.png or by darkness) is kept, and everything else is redrawn at real-world scale:
  wall    = a photo wall material tiled at its real size, tinted toward the original's wall colour
  windows = frame, glass with a sky-to-ground reflection gradient, a room behind it (blinds, curtains or dark),
            a mullion on wide windows, a stone sill and a shadowed recess at the top
Writes <name>.png (colour), <name>_nor.png (normal, OpenGL), <name>_rough.png (R roughness, G metallic).
usage: make_facades.py [name ...]     (default: all in FACADES)"""
import os, sys, zlib
import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
TEX = os.path.join(ROOT, "textures")
PBR = os.path.join(TEX, "pbr")
ORIG = os.path.join(TEX, "_orig")

# real-world size (m) of one repeat of each photo set (Poly Haven sizes, corrected where courses showed otherwise)
SET_M = {"red_brick_03": 1.0, "brick_wall_001": 1.4, "brick_wall_003": 1.5, "brick_wall_005": 1.44,
         "large_sandstone_blocks": 3.0, "concrete_wall_008": 2.71, "exterior_wall_cladding": 2.0, "white_stucco": 2.0,
         "white_sandstone_bricks": 2.0, "box_profile_metal_sheet": 2.0, "concrete_block_wall": 2.0}
# facade texture -> (photo set, tile metres (w, h) from build_city TILE, tint strength, frame colour)
WHITE, BRONZE, DARK, GREEN = (0.86, 0.85, 0.82), (0.25, 0.2, 0.15), (0.12, 0.12, 0.13), (0.16, 0.24, 0.2)
FACADES = {
    "brick_red": ("red_brick_03", (7, 7), 0.35, WHITE),
    "brick_brown": ("brick_wall_001", (7, 7), 0.45, WHITE),
    "brick_tan": ("brick_wall_003", (7, 7), 0.55, BRONZE),
    "warehouse": ("brick_wall_005", (12, 9), 0.4, GREEN),
    "storefront": ("red_brick_03", (8, 4.2), 0.3, DARK),
    "concrete": ("concrete_wall_008", (12, 10.5), 0.6, DARK),
    "limestone": ("large_sandstone_blocks", (6, 4.2), 0.75, BRONZE),
    "sandstone": ("large_sandstone_blocks", (6, 5), 0.6, BRONZE),
    "terracotta": ("concrete_wall_008", (5, 4.0), 0.8, BRONZE),
    "yamasaki": ("white_stucco", (3, 3.9), 0.7, DARK),
    "siding": ("exterior_wall_cladding", (5, 5), 0.0, WHITE),
    "h_stucco": ("white_stucco", (5.0, 2.95), 0.7, WHITE),
    "h_stone": ("white_sandstone_bricks", (5.0, 2.95), 0.4, WHITE),
    "h_block": ("concrete_block_wall", (4.0, 2.95), 0.5, DARK),
}
for era in ["old", "mid", "post", "new"]:
    w = 3.4 if era == "old" else 5.0
    FACADES["h_brick_" + era] = (["brick_wall_001", "red_brick_03", "brick_wall_005", "brick_wall_003"][["old", "mid", "post", "new"].index(era)], (w, 2.95), 0.35, WHITE)
    FACADES["h_clap_" + era] = ("exterior_wall_cladding", (w, 2.95), 0.0, WHITE)   # tinted at runtime (era paint)
FACADES["h_lap_plain"] = ("exterior_wall_cladding", (4.0, 2.95), 0.0, WHITE)

CONTRAST = {"limestone": 0.45, "sandstone": 0.6, "h_stone": 0.6, "warehouse": 0.8, "brick_brown": 0.85}

def load(p, mode="RGB"):
    return np.asarray(Image.open(p).convert(mode)).astype(np.float32) / 255.0

def tile_to(img, out_h, out_w, px):
    """repeat img (resized to px x px) to cover out_h x out_w"""
    im = np.asarray(Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8)).resize((px, px), Image.LANCZOS)).astype(np.float32) / 255.0
    reps = (out_h // px + 2, out_w // px + 2) + ((1,) if im.ndim == 3 else ())
    return np.tile(im, reps)[:out_h, :out_w]

def window_mask(name, a):
    rp = os.path.join(ORIG, name + "_rough.png")
    if os.path.exists(rp):
        r = load(rp)
        m = r[..., 1] > 0.4
    else:
        l = a @ np.array([0.299, 0.587, 0.114], np.float32)
        m = (l < np.median(l) * 0.62) & (a[..., 2] >= a[..., 0] - 0.03)
    m = ndimage.binary_opening(m, iterations=1)
    m = ndimage.binary_closing(m, iterations=2)
    return m

def build(name):
    src = os.path.join(ORIG, name + ".png")
    if not os.path.exists(src): print("skip", name); return
    a0 = load(src)
    setn, (tw, th), tint_k, frame = FACADES[name]
    win0 = window_mask(name, a0)
    # output size: ~140 px per metre, capped at 2048
    ppm = min(2048.0 / tw, 2048.0 / th, 160.0)
    W, H = int(round(tw * ppm / 4) * 4), int(round(th * ppm / 4) * 4)
    a = np.asarray(Image.fromarray((a0 * 255).astype(np.uint8)).resize((W, H), Image.LANCZOS)).astype(np.float32) / 255.0
    win = np.asarray(Image.fromarray(win0.astype(np.uint8) * 255).resize((W, H), Image.NEAREST)) > 127
    px = max(8, int(round(SET_M[setn] * ppm)))
    wall = tile_to(load(os.path.join(PBR, setn + "_diff.jpg")), H, W, px)
    wnor = tile_to(load(os.path.join(PBR, setn + "_nor.jpg")), H, W, px)
    wrough = tile_to(load(os.path.join(PBR, setn + "_rough.jpg"), "L"), H, W, px)
    # calm down very grungy scans (stone sets read as dirty at building scale)
    k = CONTRAST.get(name, 1.0)
    if k < 1.0:
        m = wall.reshape(-1, 3).mean(axis=0); lw = wall @ np.array([0.299, 0.587, 0.114], np.float32)
        wall = m + (wall - m) * k
        wall = wall * 0.7 + lw[..., None] * 0.3 * (m.mean() / max(lw.mean(), 1e-3))      # a little desaturation
    # tint the photo toward the original wall colour (keeps the city's palette); siding stays neutral for runtime paint
    if tint_k > 0 and (~win).any():
        target = a[~win].mean(axis=0); cur = wall.reshape(-1, 3).mean(axis=0)
        wall = wall * (1 - tint_k) + wall * (target / np.maximum(cur, 1e-3)) * tint_k
    elif tint_k == 0:
        l = wall @ np.array([0.299, 0.587, 0.114], np.float32)
        wall = np.repeat((l / max(l.mean(), 1e-3) * 0.82)[..., None], 3, axis=2)   # neutral light grey, painted in-engine
    col = wall.copy(); nor = wnor.copy(); rough = wrough.copy(); metal = np.zeros((H, W), np.float32)
    rng = np.random.default_rng(zlib.crc32(name.encode()))
    win = win.copy()
    lab, n = ndimage.label(win)
    yy, xx = np.mgrid[0:H, 0:W]
    fpx = max(2, int(0.05 * ppm)); sill = max(2, int(0.07 * ppm))
    for i, sl in enumerate(ndimage.find_objects(lab)):
        if sl is None: continue
        y0, y1, x0, x1 = sl[0].start, sl[0].stop, sl[1].start, sl[1].stop
        h, w = y1 - y0, x1 - x0
        if h < 0.35 * ppm or w < 0.3 * ppm:      # specks in the old texture: wall, not windows
            win[sl][lab[sl] == i + 1] = False
            continue
        # frame
        col[y0:y1, x0:x1] = frame; rough[y0:y1, x0:x1] = 0.45; nor[y0:y1, x0:x1] = (0.5, 0.5, 1.0)
        gy0, gy1, gx0, gx1 = y0 + fpx, y1 - fpx, x0 + fpx, x1 - fpx
        if gy1 - gy0 < 3 or gx1 - gx0 < 3: continue
        gh = gy1 - gy0
        t = np.linspace(0, 1, gh)[:, None]
        sky = np.array([0.42, 0.5, 0.58]); ground = np.array([0.13, 0.14, 0.15])
        glass = sky * (1 - t[..., None]) ** 1.5 + ground * (1 - (1 - t[..., None]) ** 1.5)
        glass = np.broadcast_to(glass, (gh, gx1 - gx0, 3)).copy()
        kind = rng.random()
        if kind < 0.3:      # blinds lowered part way
            drop = int(gh * rng.uniform(0.2, 0.7)); c = np.array([0.72, 0.68, 0.6]) * rng.uniform(0.8, 1.05)
            stripes = (np.arange(drop) // max(1, int(0.025 * ppm))) % 2
            glass[:drop] = glass[:drop] * 0.35 + c * (0.55 + 0.1 * stripes[:, None, None])
        elif kind < 0.5:    # curtains at the sides
            cw = int((gx1 - gx0) * rng.uniform(0.15, 0.3)); c = rng.choice([[0.55, 0.2, 0.18], [0.75, 0.7, 0.55], [0.25, 0.3, 0.45], [0.6, 0.55, 0.5]])
            glass[:, :cw] = glass[:, :cw] * 0.3 + np.array(c) * 0.6; glass[:, -cw:] = glass[:, -cw:] * 0.3 + np.array(c) * 0.6
        else:
            glass *= rng.uniform(0.75, 1.05)
        col[gy0:gy1, gx0:gx1] = glass
        rough[gy0:gy1, gx0:gx1] = 0.05; metal[gy0:gy1, gx0:gx1] = 0.75
        nor[gy0:gy1, gx0:gx1] = (0.5, 0.5, 1.0)
        if gx1 - gx0 > 1.2 * ppm:      # mullion
            mx = (gx0 + gx1) // 2
            col[gy0:gy1, mx - fpx // 2: mx + fpx // 2 + 1] = frame; rough[gy0:gy1, mx - fpx // 2: mx + fpx // 2 + 1] = 0.45; metal[gy0:gy1, mx - fpx // 2: mx + fpx // 2 + 1] = 0
        # recess shadow along the top of the opening
        sh = max(2, int(0.12 * ppm)); k = np.linspace(0.55, 1.0, min(sh, gh))[:, None, None]
        col[gy0:gy0 + len(k), gx0:gx1] *= k
        # sill below (light stone), slightly wider than the opening
        sy0, sy1 = y1, min(H, y1 + sill); sx0, sx1 = max(0, x0 - fpx), min(W, x1 + fpx)
        if name not in ("siding",) and not name.startswith("h_clap") and not name.startswith("h_lap"):
            col[sy0:sy1, sx0:sx1] = np.array([0.78, 0.76, 0.7]) * rng.uniform(0.9, 1.0)
            nor[sy0:sy1, sx0:sx1] = (0.5, 0.75, 0.85)
            col[sy1:min(H, sy1 + sill), sx0:sx1] *= 0.75     # shadow under the sill
    # recess edges into the normal map (height: wall 1, opening 0)
    hgt = ndimage.gaussian_filter((~win).astype(np.float32), 1.2)
    gy, gx = np.gradient(hgt)
    edge = np.clip(np.abs(gx) + np.abs(gy), 0, 1) > 0.02
    nx = 0.5 - gx * 3.0; ny = 0.5 + gy * 3.0
    nor[..., 0] = np.where(edge, np.clip(nx, 0, 1), nor[..., 0]); nor[..., 1] = np.where(edge, np.clip(ny, 0, 1), nor[..., 1])
    # grime: darker toward the bottom of each tile row a little, and soft random weathering
    weather = ndimage.gaussian_filter(rng.random((H // 16 + 1, W // 16 + 1)).astype(np.float32), 2)
    weather = np.asarray(Image.fromarray((weather * 255).astype(np.uint8)).resize((W, H), Image.BILINEAR)).astype(np.float32) / 255.0
    col *= (0.92 + 0.12 * weather)[..., None]
    out = lambda arr, p: Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8)).save(os.path.join(TEX, p))
    out(col, name + ".png")
    out(nor, name + "_nor.png")
    out(np.stack([rough, metal, np.zeros_like(rough)], -1), name + "_rough.png")
    # emission mask (lit windows at night) follows the new size
    ep = os.path.join(ORIG, name + "_emit.png")
    if os.path.exists(ep):
        Image.open(ep).resize((W, H), Image.NEAREST).save(os.path.join(TEX, name + "_emit.png"))
    print("facade", name, W, H, "windows", n)

if __name__ == "__main__":
    os.makedirs(ORIG, exist_ok=True)
    names = sys.argv[1:] or list(FACADES)
    for nm in names:
        for suf in ["", "_rough", "_emit"]:
            p, o = os.path.join(TEX, nm + suf + ".png"), os.path.join(ORIG, nm + suf + ".png")
            if os.path.exists(p) and not os.path.exists(o): Image.open(p).save(o)
        build(nm)
