"""Photo-measured wall colours for non-house buildings (shops, churches, factories): key -> "#rrggbb" + a wall class.

usage: bld_looks_apply.py all_parcels.json nonres_looks.json out.json
A parcel's photo shows its main building; it is applied to every building on the parcel bigger than a shed.
"""
import sys, json, pickle
import numpy as np, cv2
LINK, LOOKS, OUT = sys.argv[1:4]
link = json.load(open(LINK)); looks = json.load(open(LOOKS))

def paint(rgb):
    hsv = cv2.cvtColor(np.uint8([[rgb]]), cv2.COLOR_RGB2HSV).astype(np.float32)[0, 0]
    hsv[1] = min(255, hsv[1] * 1.2); hsv[2] = min(235, hsv[2] * 1.05 + 6)
    return [int(v) for v in cv2.cvtColor(np.uint8([[hsv]]), cv2.COLOR_HSV2RGB)[0, 0]]

def wall_class(rgb):
    r, g, b = rgb; mx, mn = max(rgb), min(rgb); sat = (mx - mn) / max(mx, 1); v = mx
    if r > g + 18 and r > b + 25 and v < 190: return "brick"          # red/brown brick
    if sat < 0.12 and v > 150: return "light"                        # white/grey paint, precast, metal panel
    if sat < 0.12: return "grey"
    if r >= g >= b and v > 140: return "buff"                         # tan/buff brick, beige
    return "paint"

out = {}
for k, (assr, _, _) in link.items():
    lk = looks.get(assr)
    if not lk or lk.get("q", 0) < 0.25: continue
    c = paint(lk["wall"])
    out[k] = {"wall": "#%02x%02x%02x" % tuple(c), "cls": wall_class(c)}
json.dump(out, open(OUT, "w"))
import collections
print("buildings", len(out), collections.Counter(v["cls"] for v in out.values()))
