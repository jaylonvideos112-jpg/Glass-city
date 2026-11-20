"""Export the exact massing of buildings chosen for hand-made replicas (source_data/replicas.json) so the Blender
builder (tools/blender/replica.py) models on the real footprint and heights.
For each key: LiDAR tiers (downtown exact massing, else county LiDAR height over the OSM footprint), ground level,
and the anchor (footprint centroid) in game coordinates (x east, z = -north, metres from the map origin).
usage: replica_massing.py <work dir> <repo>     -> <repo>/tools/blender/replicas/<key>/massing.json"""
import sys, os, json, glob, math, pickle
from shapely import wkt
from shapely.geometry import Polygon, mapping
WORK, REPO = sys.argv[1], sys.argv[2]
LAT0, LON0 = 41.6528, -83.5379; R = 6378137.0; C = math.cos(math.radians(LAT0))
def P(lat, lon): return ((lon - LON0) * math.pi / 180 * R * C, (lat - LAT0) * math.pi / 180 * R)
reps = json.load(open(os.path.join(REPO, "source_data/replicas.json")))["buildings"]
keys = {r["key"] for r in reps}
EX = pickle.load(open(os.path.join(WORK, "lidar/downtown_exact.pkl"), "rb"))
CO = pickle.load(open(os.path.join(WORK, "lidar/county.pkl"), "rb"))
BU = pickle.load(open(os.path.join(WORK, "lidar/buildings.pkl"), "rb"))
osm = {}
for f in glob.glob(os.path.join(WORK, "osm/city_all/*.json")) + [os.path.join(WORK, "osm/county_osm.json")]:
    for e in json.load(open(f)).get("elements", []):
        k = e["type"][0] + str(e["id"])
        if k not in keys or k in osm: continue
        geo = e.get("geometry")
        if not geo:
            mem = [m for m in e.get("members", []) if m.get("role") == "outer" and m.get("geometry")]
            geo = mem[0]["geometry"] if mem else None
        if geo: osm[k] = (Polygon([P(g["lat"], g["lon"]) for g in geo if g]), e.get("tags", {}))
for k in sorted(keys):
    tiers = []; ground = None; src = ""
    if k in EX and EX[k].get("tiers"):
        tiers = [(float(t[0]), float(t[1]), wkt.loads(t[2])) for t in EX[k]["tiers"]]; ground = EX[k].get("ground"); src = "lidar_exact"
    elif k in osm:
        m = CO.get(k) or BU.get(k) or {}
        h = float(m.get("h") or osm[k][1].get("height", "0").split()[0] or 0) or 3.2 * float(osm[k][1].get("building:levels", 3))
        tiers = [(0.0, h, osm[k][0])]; src = "lidar_county" if m else "osm"
    if not tiers: print("no massing:", k); continue
    foot = max((t[2] for t in tiers), key=lambda g: g.area) if src != "lidar_exact" else tiers[0][2]
    cx, cy = foot.centroid.x, foot.centroid.y
    def loc(g):
        gs = list(g.geoms) if hasattr(g, "geoms") else [g]
        return [[[round(x - cx, 3), round(y - cy, 3)] for x, y in list(p.exterior.coords)[:-1]] for p in gs if p.area > 1]
    out = {"key": k, "src": src, "anchor": [round(cx, 3), round(-cy, 3)], "ground": ground,
           "tiers": [{"z0": a, "z1": b, "polys": loc(g)} for a, b, g in tiers],
           "osm_tags": osm.get(k, (None, {}))[1]}
    d = os.path.join(REPO, "tools/blender/replicas", k); os.makedirs(d, exist_ok=True)
    json.dump(out, open(os.path.join(d, "massing.json"), "w"), indent=1)
    print(k, src, "tiers", len(tiers), "h %.1f" % max(t[1] for t in tiers))
