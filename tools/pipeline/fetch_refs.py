"""Reference photos for replica buildings: Wikidata image (P18) + up to N files from the building's Commons category
(P373), as 960px thumbnails. Polite: generic UA, a few seconds between requests, backoff on 429.
Photos are reference only (looked at to model from); they never ship.
usage: fetch_refs.py <repo> <out dir> [N] [key ...]"""
import sys, os, json, time, hashlib, urllib.request, urllib.parse
REPO, OUT = sys.argv[1], sys.argv[2]
N = int(sys.argv[3]) if len(sys.argv) > 3 else 8
ONLY = set(sys.argv[4:])
UA = {"User-Agent": "GlassCityBuilder/0.3 (game reference research)"}
def get(url, binary=False, tries=6):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                b = r.read(); time.sleep(3.0)
                return b if binary else json.loads(b)
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(20 * (i + 1)); continue
            return None
        except Exception:
            time.sleep(5)
    return None
def thumb(name):
    f = name.replace(" ", "_"); h = hashlib.md5(f.encode()).hexdigest()
    q = urllib.parse.quote(f)
    return "https://upload.wikimedia.org/wikipedia/commons/thumb/%s/%s/%s/960px-%s" % (h[0], h[:2], q, q)
reps = json.load(open(os.path.join(REPO, "source_data/replicas.json")))["buildings"]
for r in reps:
    if ONLY and r["key"] not in ONLY: continue
    d = os.path.join(OUT, r["key"]); os.makedirs(d, exist_ok=True)
    if len([f for f in os.listdir(d) if f.endswith(".jpg")]) >= N: continue
    files = []
    if r.get("wikidata"):
        e = get("https://www.wikidata.org/wiki/Special:EntityData/%s.json" % r["wikidata"])
        if e:
            cl = list(e["entities"].values())[0]["claims"]
            for p in cl.get("P18", []): files.append(p["mainsnak"]["datavalue"]["value"])
            cat = [p["mainsnak"]["datavalue"]["value"] for p in cl.get("P373", [])]
            if cat:
                q = get("https://commons.wikimedia.org/w/api.php?action=query&list=categorymembers&cmtype=file&cmlimit=40&format=json&cmtitle=" + urllib.parse.quote("Category:" + cat[0]))
                if q:
                    files += [m["title"][5:] for m in q["query"]["categorymembers"] if m["title"].lower().endswith((".jpg", ".jpeg", ".png"))]
    if len(files) < N and r.get("name") and not r["name"].startswith("("):
        # fall back to a Commons file search on the name (+ Toledo)
        q = get("https://commons.wikimedia.org/w/api.php?action=query&list=search&srnamespace=6&srlimit=20&format=json&srsearch=" + urllib.parse.quote('"%s" Toledo' % r["name"]))
        if q: files += [m["title"][5:] for m in q.get("query", {}).get("search", []) if m["title"].lower().endswith((".jpg", ".jpeg"))]
    seen = []; got = 0
    for f in files:
        if f in seen or got >= N: continue
        seen.append(f)
        b = get(thumb(f), binary=True)
        if b and b[:2] == b"\xff\xd8":
            open(os.path.join(d, "%02d.jpg" % got), "wb").write(b); got += 1
            open(os.path.join(d, "sources.txt"), "a").write("%02d.jpg  https://commons.wikimedia.org/wiki/File:%s\n" % (got - 1, f.replace(" ", "_")))
    print(r["key"], r.get("name"), "photos", got, "of", len(files), flush=True)
