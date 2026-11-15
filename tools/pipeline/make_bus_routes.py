"""Bus routes for Glass City Transit (made up: the area's real route data could not be downloaded, 2026-11-15).

usage: make_bus_routes.py <osm tiles dir> <countryside.json> <out bus_routes.json>
Each route runs from the downtown hub to one town centre and back along the road network, preferring big roads
and obeying one-way streets (outbound and inbound are found separately). Stops every ~350 m, at road nodes, so the
game can place them on the traffic graph (nodes are OSM node ids, the same ids traffic.gd uses)."""
import glob, heapq, json, math, os, sys

TILES, FIC, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
LAT0, LON0 = 41.6528, -83.5379; R = 6378137.0; C = math.cos(math.radians(LAT0))
def P(lat, lon): return ((lon - LON0) * math.pi / 180 * R * C, (lat - LAT0) * math.pi / 180 * R)
COST = {"motorway": 9, "trunk": 1.2, "primary": 1.0, "secondary": 1.05, "tertiary": 1.25, "unclassified": 1.8,
        "residential": 2.2, "primary_link": 1.3, "secondary_link": 1.3, "tertiary_link": 1.4, "trunk_link": 1.5}
pos, adj = {}, {}
els = []
for f in glob.glob(os.path.join(TILES, "*.json")): els += json.load(open(f))["elements"]
els += json.load(open(FIC))["elements"]
for e in els:
    t = e.get("tags", {}); hw = t.get("highway")
    if e["type"] != "way" or hw not in COST: continue
    ns, g = e.get("nodes", []), e.get("geometry", [])
    if len(ns) != len(g) or len(ns) < 2: continue
    ow = t.get("oneway") in ("yes", "1", "true") or hw == "motorway" or t.get("junction") == "roundabout"
    rev = t.get("oneway") == "-1"
    for i, q in enumerate(g): pos[ns[i]] = P(q["lat"], q["lon"])
    for i in range(len(ns) - 1):
        a, b = ns[i], ns[i + 1]
        d = math.dist(pos[a], pos[b]) * COST[hw]
        if not rev: adj.setdefault(a, []).append((b, d))
        if not ow or rev: adj.setdefault(b, []).append((a, d))

def nearest(x, y):
    return min((n for n in adj), key=lambda n: (pos[n][0] - x) ** 2 + (pos[n][1] - y) ** 2)

def path(a, b):
    dist = {a: 0.0}; prev = {}; h = [(0.0, a)]
    while h:
        d, n = heapq.heappop(h)
        if n == b: break
        if d > dist.get(n, 1e18): continue
        for m, w in adj.get(n, []):
            nd = d + w
            if nd < dist.get(m, 1e18): dist[m] = nd; prev[m] = n; heapq.heappush(h, (nd, m))
    if b not in prev: return None
    out = [b]
    while out[-1] != a: out.append(prev[out[-1]])
    return out[::-1]

def stops(nodes, every=350.0):
    out = [nodes[0]]; acc = 0.0
    for i in range(1, len(nodes)):
        acc += math.dist(pos[nodes[i - 1]], pos[nodes[i]])
        if acc >= every: out.append(nodes[i]); acc = 0.0
    if out[-1] != nodes[-1]: out.append(nodes[-1])
    return out

# destinations: town centres (lat, lon) with their game names (source_data/place_names.json)
DEST = [("1", "Pinewick", 41.7189, -83.7130), ("2", "Kingsferry", 41.5570, -83.6272), ("3", "Stonebridge", 41.5628, -83.6538),
        ("4", "Eastshore", 41.6436, -83.4869), ("5", "Gatesboro", 41.6012, -83.4855), ("6", "Furnace Hill", 41.6017, -83.5641),
        ("7", "Windmill Park", 41.6217, -83.7116), ("8", "Velvet Ridge", 41.6639, -83.6430), ("9", "Gull Shores", 41.7130, -83.4920),
        ("10", "University of Glass City", 41.6575, -83.6145), ("11", "Westgate", 41.6530, -83.6640), ("12", "Airport Highway", 41.6020, -83.6500)]
hub = nearest(*P(41.6520, -83.5385))
routes = []
for ref, name, la, lo in DEST:
    d = nearest(*P(la, lo))
    out_p, in_p = path(hub, d), path(d, hub)
    if not out_p or not in_p:
        print("no route", name); continue
    loop = out_p + in_p[1:]
    km = sum(math.dist(pos[loop[i]], pos[loop[i + 1]]) for i in range(len(loop) - 1)) / 1000
    routes.append({"ref": ref, "name": f"{ref} Downtown - {name}", "nodes": loop, "stops": stops(out_p) + stops(in_p)[1:], "km": round(km, 1)})
    print(ref, name, len(loop), "nodes", round(km, 1), "km", len(routes[-1]["stops"]), "stops")
json.dump({"_doc": "made by tools/pipeline/make_bus_routes.py; operator name is a placeholder the owner can change",
           "operator": "Glass City Transit", "routes": routes}, open(OUT, "w"))
