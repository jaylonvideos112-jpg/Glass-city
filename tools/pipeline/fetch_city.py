"""Tiled, resumable Overpass download for the whole city. Alternates https/http, retries forever-ish.
usage: fetch_city.py S W N E rows cols outdir [worker_index worker_count]"""
import json, sys, time, subprocess, os

S, W, N, E = map(float, sys.argv[1:5])
ROWS, COLS = int(sys.argv[5]), int(sys.argv[6])
OUT = sys.argv[7]
WI = int(sys.argv[8]) if len(sys.argv) > 8 else 0
WC = int(sys.argv[9]) if len(sys.argv) > 9 else 1
os.makedirs(OUT, exist_ok=True)
URLS = ["https://maps.mail.ru/osm/tools/overpass/api/interpreter", "https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter"]

def q(s, w, n, e):
    b = f"({s},{w},{n},{e})"
    return f"""[out:json][timeout:180][maxsize:536870912];
(
 way["highway"]{b};
 way["building"]{b};
 relation["building"]{b};
 way["building:part"]{b};
 way["natural"="water"]{b};
 relation["natural"="water"]{b};
 way["natural"="coastline"]{b};
 way["waterway"~"river|riverbank|canal"]{b};
 way["leisure"~"park|pitch|stadium|garden|playground|golf_course|nature_reserve"]{b};
 relation["leisure"~"park|golf_course|nature_reserve"]{b};
 way["landuse"~"grass|recreation_ground|cemetery|forest|meadow|industrial|railway"]{b};
 relation["landuse"~"cemetery|forest|industrial"]{b};
 way["natural"~"wood|scrub|wetland"]{b};
 way["amenity"="parking"]{b};
 way["railway"="rail"]{b};
 node["place"~"neighbourhood|suburb|quarter|village|hamlet|town"]{b};
 node["highway"~"^(traffic_signals|stop|give_way)$"]{b};
);
out geom;"""

tiles = [(i, j) for i in range(ROWS) for j in range(COLS)]
mine = [t for k, t in enumerate(tiles) if k % WC == WI]
dlat, dlon = (N - S) / ROWS, (E - W) / COLS
attempt = 0
while True:
    todo = [t for t in mine if not os.path.exists(f"{OUT}/{t[0]}_{t[1]}.json")]
    if not todo:
        break
    i, j = todo[0]
    s, w = S + i * dlat, W + j * dlon
    path = f"{OUT}/{i}_{j}.json"; tmp = path + f".tmp{WI}"
    r = subprocess.run(["curl", "-sS", "-m", "150", "-A", "GlassCityBuilder/0.3", "-G",
                        "--data-urlencode", "data=" + q(s, w, s + dlat, w + dlon),
                        URLS[0 if attempt % 4 != 3 else 1 + (attempt // 4) % (len(URLS) - 1)], "-o", tmp, "-w", "%{http_code}"], capture_output=True, text=True)
    attempt += 1
    code = r.stdout.strip()
    ok = False
    if code == "200":
        try:
            d = json.load(open(tmp))
            if "remark" in d and "runtime error" in d.get("remark", ""):
                print("remark", d["remark"][:120], flush=True)
            else:
                os.replace(tmp, path); ok = True
                print(f"tile {i}_{j} ok {len(d['elements'])} el", flush=True)
        except Exception as ex:
            print("bad json", ex, flush=True)
    if not ok:
        if attempt % 10 == 0:
            print(f"tile {i}_{j} attempt {attempt} code {code} {r.stderr.strip()[:60]}", flush=True)
        time.sleep(30 if code == "429" else 6)
print("worker done", WI, flush=True)
