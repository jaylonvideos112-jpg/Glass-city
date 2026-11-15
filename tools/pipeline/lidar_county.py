import sys, json, math, pickle, collections
sys.argv = ["x", "lidar/laz/laz", "osm/city", "lidar/buildings.pkl"]
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import lidar_process as L
from multiprocessing import Pool
from shapely.geometry import Polygon
els = json.load(open("osm/county_osm.json"))["elements"]
cells = {}
for e in els:
    g = Polygon([L.P(p["lat"], p["lon"]) for p in e["geometry"]])
    if not g.is_valid: g = g.buffer(0)
    if g.is_empty: continue
    rp = g.representative_point()
    cells.setdefault((math.floor(rp.x / L.CELL), math.floor(rp.y / L.CELL)), []).append((f"w{e['id']}", g.wkt))
out = {}
with Pool(2) as pool:
    for i, r in enumerate(pool.imap_unordered(L.do_cell, [(cx, cy, it) for (cx, cy), it in cells.items()], chunksize=2)):
        out.update(r)
        if i % 200 == 0: print("cells", i, len(cells), len(out), flush=True)
pickle.dump(out, open("lidar/county.pkl", "wb"))
print("DONE", len(out), collections.Counter(v.get("roof") for v in out.values()).most_common())
