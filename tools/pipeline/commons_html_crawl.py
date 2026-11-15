"""Polite Commons crawl through normal category/file HTML pages (the API is rate-limited for this host).
Collects file names under seed categories (depth-limited), then downloads 1280px thumbnails from
upload.wikimedia.org and records license/author/coords from each file page.
usage: commons_html_crawl.py <outdir> <depth> <seed category> [...]"""
import sys, os, re, json, time, html, hashlib, subprocess, urllib.parse

OUT = sys.argv[1]; DEPTH = int(sys.argv[2]); SEEDS = sys.argv[3:]
os.makedirs(f"{OUT}/img", exist_ok=True)
UA = "ToledoGameRefBot/0.1 (personal non-commercial game; reference photos)"
DB = f"{OUT}/index.json"
db = json.load(open(DB)) if os.path.exists(DB) else {"cats": {}, "files": {}}
last = [0.0]

def get(url, path=None):
    for attempt in range(5):
        wait = (1.0 if "upload.wikimedia.org" in url else 3.0) - (time.time() - last[0])
        if wait > 0: time.sleep(wait)
        last[0] = time.time()
        args = ["curl", "-s", "-m", "60", "-A", UA, "-w", "%{http_code}"]
        args += ["-o", path] if path else ["-o", "/tmp/_c.html"]
        code = subprocess.run(args + [url], capture_output=True, text=True).stdout.strip()
        if code == "200":
            return True if path else open("/tmp/_c.html", encoding="utf-8", errors="ignore").read()
        if code == "429": time.sleep(30 * (attempt + 1))
        elif code == "404": return None
        else: time.sleep(5)
    return None

def save(): json.dump(db, open(DB, "w"), indent=0)

def crawl(cat, depth):
    if cat in db["cats"]: return
    t = get("https://commons.wikimedia.org/wiki/" + urllib.parse.quote(cat))
    if t is None: return
    body = t.split('id="mw-subcategories"')[-1] if 'id="mw-subcategories"' in t else t
    subs = sorted(set(html.unescape(urllib.parse.unquote(c)) for c in re.findall(r'href="/wiki/(Category:[^"#?]+)"', body.split('id="mw-normal-catlinks"')[0])))
    files = sorted(set(html.unescape(urllib.parse.unquote(f)) for f in re.findall(r'href="/wiki/(File:[^"#?]+)"', t)))
    db["cats"][cat] = {"subs": subs, "files": files}
    for f in files: db["files"].setdefault(f, {"cats": []})["cats"].append(cat)
    save(); print("cat", cat, len(subs), len(files), flush=True)
    if depth > 0:
        for s in subs:
            if ("Block_Card" in s and "Downtown" not in s) or "People" in s or "Events" in s: continue
            if any(k in s for k in ("Toledo", "Lucas_County", "Maumee", "SeaGate", "Seagate", "Fifth_Third", "Huntington_Center")):
                crawl(s, depth - 1)

def thumb_url(fname, w=1280):
    name = fname[5:].replace(" ", "_")
    h = hashlib.md5(name.encode()).hexdigest()
    q = urllib.parse.quote(name)
    ext = name.rsplit(".", 1)[-1].lower()
    if ext in ("tif", "tiff", "pdf", "djvu", "svg"): return None
    return f"https://upload.wikimedia.org/wikipedia/commons/thumb/{h[0]}/{h[:2]}/{q}/{w}px-{q}"

for s in SEEDS: crawl(s, DEPTH)
todo = [f for f, v in db["files"].items() if "img" not in v and not v.get("skip")]
def prio(f):
    sc = 5
    if re.search(r"20[012]\d", f): sc -= 3
    if any(k in f for k in ("DPLA", "approximately", "Postcard", "postcard", "interior", "Interior", "1912", "190")): sc += 4
    if any(k in f.lower() for k in ("summit", "madison", "jefferson", "adams", "huron", "superior", "st. clair", "erie", "skyline", "downtown", "tower", "building")): sc -= 1
    return sc
todo.sort(key=prio)
print("files", len(db["files"]), "to fetch", len(todo), flush=True)
for i, f in enumerate(todo):
    v = db["files"][f]
    page = None if os.environ.get("NOPAGES") else get("https://commons.wikimedia.org/wiki/" + urllib.parse.quote(f.replace(" ", "_")))
    if page:
        lic = re.search(r'class="licensetpl_short"[^>]*>([^<]+)<', page)
        v["license"] = html.unescape(lic.group(1)) if lic else ""
        au = re.search(r'id="fileinfotpl_aut"[^>]*>.*?</td>\s*<td[^>]*>(.*?)</td>', page, re.S)
        v["author"] = re.sub(r"<[^>]+>", "", html.unescape(au.group(1))).strip()[:120] if au else ""
        geo = re.search(r'data-lat="([-\d.]+)"\s+data-lon="([-\d.]+)"', page) or re.search(r'"wgCoordinates":\{"lat":([-\d.]+),"lon":([-\d.]+)', page)
        if geo: v["lat"], v["lon"] = float(geo.group(1)), float(geo.group(2))
        dt = re.search(r'id="fileinfotpl_date"[^>]*>.*?</td>\s*<td[^>]*>(.*?)</td>', page, re.S)
        v["date"] = re.sub(r"<[^>]+>", "", html.unescape(dt.group(1))).strip()[:40] if dt else ""
    u = thumb_url(f)
    if not u: v["skip"] = True; continue
    fn = f"{OUT}/img/{hashlib.md5(f.encode()).hexdigest()[:12]}.jpg"
    if get(u, fn): v["img"] = fn
    else:
        u2 = thumb_url(f, 800)
        if get(u2, fn): v["img"] = fn
        else: v["skip"] = True
    if i % 10 == 0: save(); print("img", i, len(todo), flush=True)
save(); print("DONE", sum(1 for v in db["files"].values() if "img" in v), "images")
