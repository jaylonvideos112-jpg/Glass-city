"""Workplaces for jobs (scripts/jobs.gd) and businesses for sale (scripts/business.gd).

usage: make_workplaces.py <osm tiles dir> <island.json> <out workplaces.json>
Shops, restaurants, gas stations, warehouses, factories and construction sites in the real area. Real names and
brands are replaced with made-up ones (seeded, so the same place keeps its name)."""
import glob, json, math, os, random, sys
TILES, ISL, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
LAT0, LON0 = 41.6528, -83.5379; R = 6378137.0; C = math.cos(math.radians(LAT0))
def P(lat, lon): return ((lon - LON0) * math.pi / 180 * R * C, (lat - LAT0) * math.pi / 180 * R)
S, W, N, E = json.load(open(ISL))["real"]
KIND = {("shop", "supermarket"): "grocery", ("shop", "convenience"): "convenience", ("amenity", "fuel"): "gas_station",
        ("amenity", "fast_food"): "fast_food", ("amenity", "restaurant"): "restaurant", ("amenity", "cafe"): "restaurant",
        ("shop", "clothes"): "clothing", ("shop", "department_store"): "clothing", ("shop", "hardware"): "retail",
        ("shop", "car_repair"): "auto_shop", ("amenity", "post_office"): "delivery", ("building", "warehouse"): "warehouse",
        ("building", "industrial"): "factory", ("landuse", "construction"): "construction"}
FIRST = ["Lakeshore", "Glass City", "Maumee Valley", "Northfork", "Harbor", "Furnace", "Pinewick", "Kingsferry", "Swamp",
         "Erie Line", "Riverside", "Old Mill", "Union", "Westgate", "Heron", "Walleye", "Ironwood", "Cherry", "Summit", "Ottawa Bend"]
LAST = {"grocery": ["Grocers", "Market", "Fresh Foods", "Food Mart"], "convenience": ["Quick Stop", "Corner Store", "Mini Mart", "Go Shop"],
        "gas_station": ["Fuel", "Gas & Go", "Petro", "Fill-Up"], "fast_food": ["Burger Barn", "Fry Shack", "Chicken Hut", "Taco Stand", "Pizza Pit"],
        "restaurant": ["Diner", "Grill", "Kitchen", "Bistro", "Eatery"], "clothing": ["Outfitters", "Threads", "Apparel", "Department Store"],
        "retail": ["Hardware", "Supply Co.", "Tool Depot"], "auto_shop": ["Auto Repair", "Tire & Lube", "Garage"],
        "delivery": ["Parcel Depot", "Courier Hub"], "warehouse": ["Logistics", "Distribution", "Storage & Freight"],
        "factory": ["Glassworks", "Manufacturing", "Fabrication", "Plastics", "Assembly"], "construction": ["Construction", "Builders"]}
rng = random.Random(1115)
out, seen = [], set()
for f in sorted(glob.glob(os.path.join(TILES, "*.json"))):
    for e in json.load(open(f))["elements"]:
        t = e.get("tags", {})
        kind = None
        for k in ("shop", "amenity", "building", "landuse"):
            if (k, t.get(k)) in KIND: kind = KIND[(k, t.get(k))]; break
        if kind is None: continue
        if e["type"] == "node": la, lo = e["lat"], e["lon"]
        elif e.get("geometry"):
            g = e["geometry"]; la = sum(q["lat"] for q in g) / len(g); lo = sum(q["lon"] for q in g) / len(g)
        else: continue
        if not (S <= la <= N and W <= lo <= E): continue
        x, y = P(la, lo)
        key = (kind, round(x / 60), round(y / 60))
        if key in seen: continue
        seen.add(key)
        size = len(e.get("geometry", [])) if e["type"] != "node" else 4
        out.append({"id": len(out), "kind": kind, "name": f"{rng.choice(FIRST)} {rng.choice(LAST[kind])}",
                    "x": round(x, 1), "z": round(-y, 1), "size": size})
json.dump({"_doc": "made by tools/pipeline/make_workplaces.py (made-up names); x/z world metres", "places": out}, open(OUT, "w"))
from collections import Counter
print(len(out), Counter(p["kind"] for p in out))
