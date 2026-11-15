"""Download Ohio OSIP aerial imagery for each 1 km game region and cut it into 200 m chunk JPEGs.
Core area (within CORE_R of downtown) at 0.25 m/px (800 px per chunk), rest at 0.625 m/px (320 px).
usage: aerial_fetch.py <manifest.json> <outdir>"""
import json, math, os, sys, subprocess, io, concurrent.futures as cf
from PIL import Image

MAN, OUT = sys.argv[1], sys.argv[2]
LAT0, LON0 = 41.6528, -83.5379
R = 6378137.0; COSLAT = math.cos(math.radians(LAT0))
CHUNK, REGION = 200.0, 1000.0
CORE_R = 2600.0
URL = "https://maps.ohio.gov/image/rest/services/osip_most_current/ImageServer/exportImage"
os.makedirs(f"{OUT}/raw", exist_ok=True); os.makedirs(f"{OUT}/chunks", exist_ok=True)

def plan_to_ll(x, y): return LON0 + x / (R * COSLAT) * 180 / math.pi, LAT0 + y / R * 180 / math.pi
def merc(lon, lat): return lon * 20037508.34 / 180, math.log(math.tan((90 + lat) * math.pi / 360)) * 20037508.34 / math.pi

man = json.load(open(MAN))
regions = sorted({(math.floor(c[0] * CHUNK / REGION), math.floor(c[1] * CHUNK / REGION)) for c in man["chunks"]})
chunk_set = {(c[0], c[1]) for c in man["chunks"]}

def do_region(rk):
    rx, ry = rk
    cx, cy = (rx + 0.5) * REGION, (ry + 0.5) * REGION
    core = math.hypot(cx, cy) < CORE_R
    px_per_chunk = 800 if core else 320
    n = int(REGION / CHUNK)
    size = px_per_chunk * n
    need = [(rx * n + i, ry * n + j) for i in range(n) for j in range(n) if (rx * n + i, ry * n + j) in chunk_set]
    if all(os.path.exists(f"{OUT}/chunks/{a}_{b}.jpg") for a, b in need): return rk, "skip"
    lo0, la0 = plan_to_ll(rx * REGION, ry * REGION); lo1, la1 = plan_to_ll((rx + 1) * REGION, (ry + 1) * REGION)
    x0, y0 = merc(lo0, la0); x1, y1 = merc(lo1, la1)
    raw = f"{OUT}/raw/{rx}_{ry}.jpg"
    if not os.path.exists(raw):
        url = f"{URL}?bbox={x0},{y0},{x1},{y1}&bboxSR=3857&imageSR=3857&size={size},{size}&format=jpg&compressionQuality=85&f=image"
        for attempt in range(6):
            r = subprocess.run(["curl", "-sS", "-m", "300", "-o", raw + ".part", "-w", "%{http_code}", url], capture_output=True, text=True)
            if r.stdout.strip() == "200":
                try:
                    Image.open(raw + ".part").verify(); os.replace(raw + ".part", raw); break
                except Exception: pass
        else:
            return rk, "FAIL"
    img = Image.open(raw).convert("RGB")
    if img.size != (size, size): img = img.resize((size, size))
    for i in range(n):
        for j in range(n):
            k = (rx * n + i, ry * n + j)
            if k not in chunk_set: continue
            # image row 0 is north (max y); chunk j counts northward
            box_ = (i * px_per_chunk, (n - 1 - j) * px_per_chunk, (i + 1) * px_per_chunk, (n - j) * px_per_chunk)
            img.crop(box_).save(f"{OUT}/chunks/{k[0]}_{k[1]}.jpg", quality=82, optimize=True)
    return rk, "core" if core else "ok"

done = 0
with cf.ThreadPoolExecutor(4) as ex:
    for rk, st in ex.map(do_region, regions):
        done += 1
        if done % 20 == 0 or st == "FAIL": print(done, "/", len(regions), rk, st, flush=True)
print("DONE", done)
