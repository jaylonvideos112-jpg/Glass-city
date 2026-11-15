"""Download the USGS EPT (Entwine) LiDAR nodes covering a lon/lat box down to a max depth.
usage: lidar_fetch.py S W N E maxdepth outdir [--plan]"""
import json, math, os, sys, subprocess, concurrent.futures as cf

BASE = "https://usgs-lidar-public.s3.amazonaws.com/" + os.environ.get("EPT", "USGS_LPC_OH_LowerMaumee_B16_2016_LAS_2017")
S, W, N, E = map(float, sys.argv[1:5]); MAXD = int(sys.argv[5]); OUT = sys.argv[6]
PLAN = "--plan" in sys.argv
os.makedirs(f"{OUT}/hier", exist_ok=True); os.makedirs(f"{OUT}/laz", exist_ok=True)

def merc(lon, lat): return lon * 20037508.34 / 180, math.log(math.tan((90 + lat) * math.pi / 360)) * 20037508.34 / math.pi
bx0, by0 = merc(W, S); bx1, by1 = merc(E, N)
ept = json.load(open(f"{OUT}/ept.json")) if os.path.exists(f"{OUT}/ept.json") else None
if ept is None:
    subprocess.run(["curl", "-sS", "-m", "60", "-o", f"{OUT}/ept.json", f"{BASE}/ept.json"], check=True)
    ept = json.load(open(f"{OUT}/ept.json"))
B = ept["bounds"]; W0 = B[3] - B[0]

def node_bounds(key):
    d, x, y, z = map(int, key.split("-"))
    w = W0 / (2 ** d)
    return B[0] + x * w, B[1] + y * w, B[2] + z * w, w

def overlaps(key):
    x0, y0, z0, w = node_bounds(key)
    return not (x0 > bx1 or x0 + w < bx0 or y0 > by1 or y0 + w < by0)

def get(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 0: return True
    for _ in range(6):
        r = subprocess.run(["curl", "-sS", "-m", "300", "-o", path + ".part", "-w", "%{http_code}", url], capture_output=True, text=True)
        if r.stdout.strip() == "200":
            os.replace(path + ".part", path); return True
    return False

def hier(key):
    p = f"{OUT}/hier/{key}.json"
    get(f"{BASE}/ept-hierarchy/{key}.json", p)
    return json.load(open(p))

want = {}
pending = ["0-0-0-0"]
while pending:
    nxt = []
    with cf.ThreadPoolExecutor(8) as ex:
        for h in ex.map(hier, pending):
            for k, cnt in h.items():
                d = int(k.split("-")[0])
                if d > MAXD or not overlaps(k): continue
                if cnt == -1: nxt.append(k)
                elif cnt > 0: want[k] = cnt
    pending = [k for k in nxt if k not in ("0-0-0-0",)]
tot = sum(want.values())
print(f"nodes {len(want)} points {tot:,} (~{tot * 3.4 / 1e9:.1f} GB laz est)", flush=True)
by_d = {}
for k, c in want.items(): by_d[int(k.split('-')[0])] = by_d.get(int(k.split('-')[0]), 0) + c
print("by depth", sorted(by_d.items()), flush=True)
json.dump(want, open(f"{OUT}/nodes.json", "w"))
if PLAN: sys.exit()
done = 0
def dl(k):
    return get(f"{BASE}/ept-data/{k}.laz", f"{OUT}/laz/{k}.laz")
with cf.ThreadPoolExecutor(12) as ex:
    for ok in ex.map(dl, sorted(want, key=lambda k: int(k.split('-')[0]))):
        done += 1
        if done % 200 == 0: print("downloaded", done, "/", len(want), flush=True)
print("DONE", done, flush=True)
