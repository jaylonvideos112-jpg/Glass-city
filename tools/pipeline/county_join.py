"""Lucas County footprints + AREIS records -> buildings for the generator.

Outputs (in OUT dir):
  county_osm.json   OSM-style way elements for county footprints (id 8_000_000_000 + n), tags carry the county attributes
  county_drop.json  OSM building keys replaced by a county footprint
County footprints win (complete, traced from 2025 aerials) except where the OSM building is a hand-tuned landmark,
has building:parts, or carries an explicit height; there the OSM shape stays and only the attributes are attached.
"""
import sys, os, json, csv, glob, math, collections, pickle
import shapefile, pyproj
from shapely.geometry import Polygon, shape as shp
from shapely.strtree import STRtree
from shapely.validation import make_valid

CO, OSM, OUT = sys.argv[1:4]
LAT0, LON0 = 41.6528, -83.5379; R = 6378137.0; C = math.cos(math.radians(LAT0))
tr = pyproj.Transformer.from_crs("EPSG:3734", "EPSG:4326", always_xy=True)
def plan(lon, lat): return ((lon - LON0) * math.pi / 180 * R * C, (lat - LAT0) * math.pi / 180 * R)

WALL = {"1": "stucco", "2": "block", "3": "vinyl", "4": "brick", "5": "stone", "6": "wood", "7": "partbrick"}
GAR = {"1": "basement", "2": "attached", "3": "detached", "4": "carport", "5": "detached", "6": "garage"}
STRUCT = {}
res, com, gen = {}, collections.defaultdict(list), {}
for r in csv.DictReader(open(f"{CO}/res.csv")):
    if r["AssrNo"] not in res or r["SubPar"] in ("0", "1"): res[r["AssrNo"]] = r
for r in csv.DictReader(open(f"{CO}/com.csv")): com[r["AssrNo"]].append(r)
for r in csv.DictReader(open(f"{CO}/gen.csv")): gen.setdefault(r["AssrNo"], r)

def story_count(code):
    try: c = float(code)
    except ValueError: return None
    return {1: 1, 2: 1.3, 3: 1.5, 4: 2, 5: 1.5, 6: 2, 7: 2.5, 8: 3}.get(int(c), None) if c < 9 else round((c - 9) * 10 + 0.0) + 0

def attrs(assr, area_m2):
    a = {}
    g = gen.get(assr)
    if g:
        a["luc"] = g["Landuse"]; a["cls"] = g["Class"]
        try: a["bval"] = int(float(g["Bldg"] or 0))
        except ValueError: pass
        a["addr"] = f'{g["StreetNumber"]} {g["Direction"] or ""} {g["Address"]} {g["AdrSuf"] or ""}'.replace("  ", " ").strip()
    r = res.get(assr)
    if r and r["YearBlt"] not in ("", "0"):
        a["year"] = int(r["YearBlt"]); a["wall"] = WALL.get(r["Wall"], "")
        sc = story_count(r["Stories"]); a["stories"] = sc if sc else 1
        a["story_code"] = r["Stories"]
        a["garage"] = GAR.get(r["GarageType"], "")
        a["bsmt"] = r["BsmtType"]; a["grade"] = int(r["Grade"] or 0); a["cond"] = int(r["Cond"] or 0)
        a["tla"] = int(float(r["TLA"] or 0)); a["occ"] = r["Occupancy"]
    cs = com.get(assr)
    if cs:
        # several buildings on one parcel: pick the one whose floor area best matches this footprint
        best = min(cs, key=lambda c: abs(float(c["GBA"] or 0) * 0.0929 / max(1.0, float(c["Stories"] or 1)) - area_m2))
        a["ctype"] = int(best["PrimStructType"] or 0); a["year"] = int(best["YearBlt"] or 0) or a.get("year", 0)
        a["stories"] = max(1, int(float(best["Stories"] or 1))); a["grade"] = int(best["Grade"] or 0)
        a["units"] = int(float(best["LivingUnits"] or 0))
    return a

# ---------------------------------------------------------------- OSM buildings
LM = set(json.load(open(f"{OUT}/landmark_ids.json"))) if os.path.exists(f"{OUT}/landmark_ids.json") else set()
osm, keys, parent_with_parts = [], [], set()
parts = []
for f in sorted(glob.glob(f"{OSM}/*.json")):
    for e in json.load(open(f))["elements"]:
        t = e.get("tags", {})
        if e["type"] != "way" or not e.get("geometry"): continue
        try:
            g = Polygon([plan(p["lon"], p["lat"]) for p in e["geometry"]])
            if not g.is_valid: g = make_valid(g)
        except Exception: continue
        k = f"w{e['id']}"
        if "building:part" in t: parts.append(g); continue
        if "building" not in t or k in keys: continue
        osm.append((k, g, t)); keys.append(k)
ptree = STRtree(parts) if parts else None
otree = STRtree([g for _, g, _ in osm])
xs = [g.bounds for _, g, _ in osm]
bx0 = min(b[0] for b in xs) - 50; by0 = min(b[1] for b in xs) - 50; bx1 = max(b[2] for b in xs) + 50; by1 = max(b[3] for b in xs) + 50
print("osm buildings", len(osm), "parts", len(parts))

# ---------------------------------------------------------------- county footprints
sf = shapefile.Reader(f"{CO}/x_footprints/BuildingFootprints/BuildingFootprints")
els, drop, attach = [], set(), {}
n = kept_osm = 0; stats = collections.Counter()
class _SR: pass
def _iter():
    for i in range(len(sf)):
        try:
            o = _SR(); o.shape = sf.shape(i); o.record = sf.record(i); yield o
        except Exception:
            continue
for sr in _iter():
    pts = sr.shape.points
    if len(pts) < 4: continue
    lon, lat = tr.transform([p[0] for p in pts], [p[1] for p in pts])
    xy = [plan(a, b) for a, b in zip(lon, lat)]
    if not (bx0 < xy[0][0] < bx1 and by0 < xy[0][1] < by1): continue
    parts_idx = list(sr.shape.parts) + [len(pts)]
    ring = xy[parts_idx[0]:parts_idx[1]]
    if len(ring) < 4: continue
    try:
        g = Polygon(ring)
        if not g.is_valid: g = make_valid(g)
        if g.area < 6: continue
    except Exception: continue
    assr = sr.record[0] or ""
    a = attrs(assr, g.area)
    # overlapping OSM buildings
    best, bo = None, 0.0
    for i in otree.query(g):
        k, og, t = osm[i]
        try: ov = og.intersection(g).area
        except Exception: continue
        if ov > 0.3 * min(og.area, g.area):
            special = k in LM or t.get("height") or t.get("building:levels") and float(str(t["building:levels"]).split(";")[0] or 0) > 4 \
                or (ptree is not None and any(parts[j].intersects(og) for j in ptree.query(og)))
            if special:
                attach[k] = a; best = "keep"; break
            drop.add(k)
            if ov > bo: bo, best = ov, t
    if best == "keep": kept_osm += 1; stats["osm_kept"] += 1; continue
    tags = {"building": (best or {}).get("building", "yes"), "county": "1"}
    for tk in ("name", "amenity", "shop", "brand", "roof:shape", "roof:colour", "building:colour", "building:material"):
        if best and tk in best: tags[tk] = best[tk]
    for ak, av in a.items(): tags["c:" + ak] = str(av)
    n += 1
    els.append({"type": "way", "id": 8_000_000_000 + n, "tags": tags,
                "geometry": [{"lat": b, "lon": a_} for a_, b in zip(lon[parts_idx[0]:parts_idx[1]], lat[parts_idx[0]:parts_idx[1]])]})
    stats["with_res" if "wall" in a else ("with_com" if "ctype" in a else "no_attrs")] += 1
json.dump({"elements": els}, open(f"{OUT}/county_osm.json", "w"))
json.dump(sorted(drop), open(f"{OUT}/county_drop.json", "w"))
json.dump(attach, open(f"{OUT}/county_attach.json", "w"))
print("county buildings", n, "osm replaced", len(drop), "osm kept w/ attrs", kept_osm, dict(stats))
