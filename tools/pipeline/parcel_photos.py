"""Polite, rate-limited fetch of Lucas County Auditor parcel photos (reference only, never shipped in the game).

usage: parcel_photos.py house_parcels.json OUT_DIR CX CY [MAX] [DELAY]
Fetches houses nearest to (CX, CY) first. Saves OUT_DIR/<assr>.jpg downscaled to 512 px wide,
plus OUT_DIR/index.json {assr: {"taxyr", "title"}}. Resumable.
"""
import sys, os, re, json, time, base64, subprocess, urllib.parse, html

LINK, OUT, CX, CY = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4])
MAX = int(sys.argv[5]) if len(sys.argv) > 5 else 1000
DELAY = float(sys.argv[6]) if len(sys.argv) > 6 else 1.5
UA = "GlassCityBuilder/0.3 (game reference research)"
BASE = "https://icare.co.lucas.oh.us/LucasCare/"
JAR = os.path.join(OUT, ".cookies")
os.makedirs(OUT, exist_ok=True)
IDX = os.path.join(OUT, "index.json")
idx = json.load(open(IDX)) if os.path.exists(IDX) else {}
last = [0.0]


def get(url, out=None, data=None, ref=None):
    dt = time.time() - last[0]
    if dt < DELAY: time.sleep(DELAY - dt)
    cmd = ["curl", "-s", "-m", "60", "-A", UA, "-c", JAR, "-b", JAR, "-w", "%{http_code}", "-o", out or "-"]
    if ref: cmd += ["-e", ref]
    if data is not None: cmd += ["--data", data]
    r = subprocess.run(cmd + [url], capture_output=True)
    last[0] = time.time()
    body = r.stdout[:-3] if out is None else b""
    code = int(r.stdout[-3:] or b"0") if r.stdout else 0
    return code, body


def form(t):
    d = {}
    for i in re.findall(r"<input[^>]*>", t):
        n = re.search(r'name="([^"]+)"', i); v = re.search(r'value="([^"]*)"', i); ty = re.search(r'type="([^"]+)"', i)
        if n and (not ty or ty.group(1).lower() in ("hidden", "text")):
            d[n.group(1)] = html.unescape(v.group(1)) if v else ""
    return d


def new_token():
    """Run one ordinary address search (as the public site does) and read the photo viewer's page token."""
    u = BASE + "search/commonsearch.aspx?mode=address"
    _, t = get(u)
    d = form(t.decode("utf-8", "ignore"))
    d.update({"inpNumber": "2049", "inpStreet": "ROBINWOOD", "hdAction": "Search", "btSearch": "Search"})
    get(u, data=urllib.parse.urlencode(d), ref=u)
    get(BASE + "Datalets/Datalet.aspx?sIndex=0&idx=1")
    _, t = get(BASE + "idoc2/photoview.aspx?sIndex=0&idx=1&LMparent=20")
    m = re.search(rb"var token = '([^']+)'", t)
    if not m: raise SystemExit("no token")
    return m.group(1).decode()


def main():
    order = sorted(byassr, key=lambda a: (byassr[a][1] - CX) ** 2 + (byassr[a][2] - CY) ** 2)
    print("residential parcels", len(order), flush=True)
    tok = new_token(); n = fails = 0
    for assr in order:
        if n >= MAX: break
        if assr in idx: continue
        url = BASE + "api/documents/Parcel%20Photo/048/" + base64.b64encode(assr.encode()).decode() + "?token=" + tok
        code, body = get(url)
        if code != 200:
            fails += 1
            if fails > 5: raise SystemExit(f"stopping: {code}")
            time.sleep(30); tok = new_token(); continue
        fails = 0
        try: docs = json.loads(body)
        except ValueError: docs = []
        docs = [d for d in docs if (d.get("Fields") or {}).get("Photo Category", "Primary View") == "Primary View"] or docs
        if not docs:
            idx[assr] = None; n += 1; continue
        d = max(docs, key=lambda d: ((d["Fields"] or {}).get("Taxyr") or 0, -d.get("Rank", 9)))
        tmp = os.path.join(OUT, ".tmp.jpg")
        code, _ = get(BASE + "api/document/" + urllib.parse.quote(d["Id"], safe="") + "/standard?token=" + tok, out=tmp)
        if code == 200:
            subprocess.run(["python3", "-c", "import cv2,sys;i=cv2.imread(sys.argv[1]);"
                            "h,w=i.shape[:2];cv2.imwrite(sys.argv[2],cv2.resize(i,(512,int(512*h/w)),interpolation=cv2.INTER_AREA),[1,88])",
                            tmp, os.path.join(OUT, assr + ".jpg")])
            idx[assr] = {"taxyr": d["Fields"].get("Taxyr"), "title": d["Fields"].get("Title")}
        n += 1
        if n % 25 == 0:
            json.dump(idx, open(IDX, "w")); print(n, assr, flush=True)
    json.dump(idx, open(IDX, "w")); print("done", n)


import csv
RES = set(r["AssrNo"] for r in csv.DictReader(open(os.environ.get("RESCSV", "county/res.csv"))) if r["YearBlt"] not in ("", "0"))
link = {k: v for k, v in json.load(open(LINK)).items() if v[0] in RES}
byassr = {}
for k, v in link.items(): byassr.setdefault(v[0], v)
main()
