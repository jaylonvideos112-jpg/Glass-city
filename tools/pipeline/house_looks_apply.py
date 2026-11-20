"""Join photo-derived house looks to building keys and quantize into a small paint palette.

usage: house_looks_apply.py house_parcels.json house_looks.json out_keys.json palette.json
out_keys: {building_key: {"w": wall_idx, "t": trim_idx|-1, "p": 0|1|-1}}
palette:  {"wall": ["#rrggbb", ...], "trim": [...]}   (only colours ship with the game, never the photos)
"""
import sys, json
import numpy as np, cv2

LINK, LOOKS, OUT, PAL = sys.argv[1:5]
NW, NT = 40, 8
link = json.load(open(LINK)); looks = json.load(open(LOOKS))


def paint(rgb):
    """Photo colour -> paint albedo: lift shade exposure and the desaturation of hazy/overcast shots."""
    hsv = cv2.cvtColor(np.uint8([[rgb]]), cv2.COLOR_RGB2HSV).astype(np.float32)[0, 0]
    hsv[1] = min(255, hsv[1] * 1.3)
    hsv[2] = min(240, hsv[2] * 1.05 + 6)
    return cv2.cvtColor(np.uint8([[hsv]]), cv2.COLOR_HSV2RGB)[0, 0].astype(np.float32)


keys, walls, trims = [], [], []
for k, (assr, _, _) in link.items():
    lk = looks.get(assr)
    if not lk or lk.get("q", 0) < 0.3: continue
    keys.append((k, lk)); walls.append(paint(lk["wall"]))
    if "trim" in lk: trims.append(paint(lk["trim"]))
print("houses with photo looks", len(keys))


def km(px, n):
    lab = cv2.cvtColor(np.uint8(np.array(px))[None], cv2.COLOR_RGB2LAB)[0].astype(np.float32)
    n = min(n, len(lab))
    _, lb, cen = cv2.kmeans(lab, n, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 0.2), 4, cv2.KMEANS_PP_CENTERS)
    rgb = cv2.cvtColor(np.uint8(np.clip(cen, 0, 255))[None], cv2.COLOR_LAB2RGB)[0]
    return rgb, cen


wrgb, wlab = km(walls, NW)
trgb, tlab = km(trims or [[235, 233, 226]], NT)


def nearest(cen, rgb):
    lab = cv2.cvtColor(np.uint8([[rgb]]), cv2.COLOR_RGB2LAB)[0, 0].astype(np.float32)
    return int(np.argmin(((cen - lab) ** 2).sum(1)))


# hand labels read off the photos (porch F/P/E/N, dormer, shutters, roof G/S/H/M/X, awnings, brick piers)
import os
LAB = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "source_data", "house_photo_labels.json")))
out = {}
for k, (assr, _, _) in link.items():
    if assr in LAB: out[k] = {"w": -1, "t": -1, "p": -1, "lab": LAB[assr]}
for (k, lk), wcol in zip(keys, walls):
    o = {"w": nearest(wlab, wcol), "t": nearest(tlab, paint(lk["trim"])) if "trim" in lk else -1}
    o["p"] = 1 if lk["porch"] >= 0.2 and lk.get("q", 0) >= 0.45 else -1     # "no porch" is not reliable from segmentation
    if k in out: o["lab"] = out[k]["lab"]
    out[k] = o
hx = lambda c: "#%02x%02x%02x" % tuple(int(v) for v in c)
json.dump(out, open(OUT, "w"))
json.dump({"wall": [hx(c) for c in wrgb], "trim": [hx(c) for c in trgb]}, open(PAL, "w"), indent=0)
print("keys", len(out), "porch yes/no", sum(v["p"] == 1 for v in out.values()), sum(v["p"] == 0 for v in out.values()))
