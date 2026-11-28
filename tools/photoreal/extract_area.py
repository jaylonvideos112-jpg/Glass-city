"""Extract everything the photoreal Blender build needs for one area into a single JSON (plan metres, x east,
y north, same origin as the game: tools/pipeline/build_city.py LAT0/LON0).

  buildings: footprint ring, OSM tags, LiDAR ground / eave / height / roof type (lidar/buildings.pkl)
  roads:     centreline + tags (highway, name, lanes, width, surface, sidewalk)
  areas:     landuse / leisure / amenity / parking polygons
  lines:     barriers (fences, walls), footways
  points:    trees, street lamps, hydrants, other tagged nodes

usage: python3 tools/photoreal/extract_area.py WORK X0 Y0 X1 Y1 OUT.json
  WORK = the work folder holding osm/city_all and lidar/ (outside the repo)."""
import sys, os, json, glob, math, pickle

WORK, X0, Y0, X1, Y1, OUT = sys.argv[1], *map(float, sys.argv[2:6]), sys.argv[6]
LAT0, LON0, R = 41.6528, -83.5379, 6378137.0
COSLAT = math.cos(math.radians(LAT0))


def P(lat, lon):
    return ((lon - LON0) * math.pi / 180 * R * COSLAT, (lat - LAT0) * math.pi / 180 * R)


M = 60.0      # margin, so features that cross the edge come whole


def inside(x, y, m=M):
    return X0 - m <= x <= X1 + m and Y0 - m <= y <= Y1 + m


lid = pickle.load(open(os.path.join(WORK, "lidar", "buildings.pkl"), "rb"))
out = {"bbox": [X0, Y0, X1, Y1], "buildings": [], "roads": [], "areas": [], "lines": [], "points": []}
seen = set()
for f in sorted(glob.glob(os.path.join(WORK, "osm", "city_all", "*.json"))):
    for e in json.load(open(f))["elements"]:
        key = e["type"][0] + str(e["id"])
        if key in seen: continue
        t = e.get("tags", {})
        if e["type"] == "node":
            if not t: continue
            x, y = P(e["lat"], e["lon"])
            if not inside(x, y): continue
            seen.add(key)
            out["points"].append({"id": key, "p": [round(x, 2), round(y, 2)], "tags": t})
            continue
        if e["type"] != "way" or "geometry" not in e: continue
        pts = [P(g["lat"], g["lon"]) for g in e["geometry"] if g]
        if not pts or not any(inside(x, y) for x, y in pts): continue
        seen.add(key)
        pts = [[round(x, 2), round(y, 2)] for x, y in pts]
        closed = len(pts) > 3 and pts[0] == pts[-1]
        if "building" in t and closed:
            b = {"id": key, "ring": pts, "tags": t}
            L = lid.get("w%d" % e["id"])
            if L: b["lidar"] = L
            out["buildings"].append(b)
        elif "highway" in t and not closed:
            out["roads"].append({"id": key, "pts": pts, "tags": t})
        elif closed and any(k in t for k in ("landuse", "leisure", "amenity", "natural", "parking", "area:highway", "surface")):
            out["areas"].append({"id": key, "ring": pts, "tags": t})
        elif any(k in t for k in ("barrier", "highway", "footway", "railway", "power")):
            out["lines"].append({"id": key, "pts": pts, "tags": t})
json.dump(out, open(OUT, "w"))
print("buildings %d (lidar %d), roads %d, areas %d, lines %d, points %d -> %s" % (
    len(out["buildings"]), sum("lidar" in b for b in out["buildings"]), len(out["roads"]), len(out["areas"]),
    len(out["lines"]), len(out["points"]), OUT))
