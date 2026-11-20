"""Hand corrections to the LiDAR massing where the point cloud is wrong or the city has changed (sources in comments)."""
import pickle, sys
from shapely import wkt, affinity
d = pickle.load(open(sys.argv[1], "rb"))

def tower_on(key, base_h, top_h, plate_m2):
    g = wkt.loads(d[key]["tiers"][0][2])
    # one clean rectangular slab, aligned with the podium, scaled to the published floor-plate area
    r = g.minimum_rotated_rectangle
    k = (plate_m2 / r.area) ** 0.5
    inner = affinity.scale(r, k, k, origin=g.centroid)
    d[key]["tiers"] = [(0.0, base_h, g.wkt), (base_h, top_h, inner.wkt)]
    d[key]["h"] = top_h
    print(key, "tower plate", round(inner.area), "m2 ->", top_h, "m")

def set_top(key, h):
    t = d[key]["tiers"]; t[-1] = (t[-1][0], h) + tuple(t[-1][2:]); d[key]["h"] = h; print(key, "top ->", h)

# One SeaGate (Fifth Third Center): 125 m / 32 floors, ~2,320 m2 floor plate; LiDAR has no returns from the glass tower
tower_on("w191008880", 12.2, 125.3, 2320)
set_top("w189305197", 99.8)      # Michael DiSalle Government Center: 100 m, 22 floors; dark glass under-read
set_top("w189372081", 56.0)      # Four SeaGate (KeyBank): 56 m, 10 floors
set_top("w429787172", 75.0)      # ProMedica Senior Care (HCR ManorCare), 333 N Summit: 77 m to the gable peak
# Hotel SeaGate, 141 N Summit: deconstructed 2021 (pocket park). County footprint ids are renumbered whenever
# county_join reruns, so find it by its county address rather than by key.
import json as _json, os as _os
_co = _json.load(open(_os.path.join(_os.path.dirname(_os.path.abspath(sys.argv[1])), "..", "osm", "county_osm.json")))
for _e in _co["elements"]:
    if _e.get("tags", {}).get("c:addr", "").upper().startswith("141 N SUMMIT"):
        _k = "w%d" % _e["id"]
        if _k in d: d[_k]["demolished"] = True; print(_k, "Hotel SeaGate demolished")

# Secor Building (425 Jefferson, 1908, 10 floors) sits inside the convention-centre footprint: carve it out
cc = d["w599481318"]["tiers"]
if len(cc[-1]) == 3 and cc[-1][1] > 30:
    sec = wkt.loads(cc[-1][2]); top = cc[-1][1]
    rest = []
    for z0, z1, w in cc[:-1]:
        g2 = wkt.loads(w).difference(sec.buffer(0.3, join_style=2))
        if not g2.is_empty and g2.area > 5: rest.append((z0, z1, g2.wkt))
    d["w599481318"]["tiers"] = rest + [(0.0, top, sec.wkt, "secor")]
    print("secor carved", round(sec.area), "m2 ->", top)
pickle.dump(d, open(sys.argv[1], "wb"))
