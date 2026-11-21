"""Link each house in house_wings.pkl to its county parcel (AssrNo) via the county footprint shapefile.

usage: parcel_link.py COUNTY_DIR osm_blds.pkl house_wings.pkl out.json
out: {building_key: [assr, cx, cy]}  (plan coords of the footprint centroid)
"""
import sys, os, math, pickle, json
import shapefile, pyproj
from shapely.geometry import Polygon, Point
from shapely.strtree import STRtree

CO, BLDS, WINGS, OUT = sys.argv[1:5]
LAT0, LON0 = 41.6528, -83.5379; R = 6378137.0; C = math.cos(math.radians(LAT0))
tr = pyproj.Transformer.from_crs("EPSG:3734", "EPSG:4326", always_xy=True)

wings = pickle.load(open(WINGS, "rb"))
blds = pickle.load(open(BLDS, "rb"))
keys = [k for k in blds if k.startswith("w8")] if os.environ.get("ALLKEYS") else [k for k in wings if k in blds]
geoms = [blds[k][1] for k in keys]
tree = STRtree(geoms)
print("houses", len(keys))

sf = shapefile.Reader(f"{CO}/x_footprints/BuildingFootprints/BuildingFootprints")
out = {}
for i in range(len(sf)):
    try:
        shp = sf.shape(i); rec = sf.record(i)
    except Exception:
        continue
    assr = (rec[0] or "").strip()
    if not assr or len(shp.points) < 4: continue
    xs = [p[0] for p in shp.points]; ys = [p[1] for p in shp.points]
    lon, lat = tr.transform(sum(xs) / len(xs), sum(ys) / len(ys))
    p = Point((lon - LON0) * math.pi / 180 * R * C, (lat - LAT0) * math.pi / 180 * R)
    for j in tree.query(p):
        if geoms[j].contains(p):
            k = keys[j]
            if k not in out: out[k] = [assr, round(p.x, 1), round(p.y, 1)]
            break
json.dump(out, open(OUT, "w"))
print("linked", len(out))
