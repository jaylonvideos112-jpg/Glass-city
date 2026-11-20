"""Download named Wikimedia Commons files (960px thumbnails) as reference photos for one replica.
usage: fetch_named.py <out dir>/<key> "File name.jpg" ...   (names found via web search; reference only, never shipped)"""
import sys, os, time, hashlib, urllib.request, urllib.parse
d = sys.argv[1]; os.makedirs(d, exist_ok=True)
UA = {"User-Agent": "GlassCityBuilder/0.3 (game reference research)"}
n = len([f for f in os.listdir(d) if f.endswith(".jpg")])
for name in sys.argv[2:]:
    f = name.replace(" ", "_"); h = hashlib.md5(f.encode()).hexdigest(); q = urllib.parse.quote(f)
    for w in (960, 1280, 500):
        u = "https://upload.wikimedia.org/wikipedia/commons/thumb/%s/%s/%s/%dpx-%s" % (h[0], h[:2], q, w, q)
        b = b""
        for tr in range(5):
            try:
                b = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60).read(); break
            except urllib.error.HTTPError as e:
                if e.code == 429: time.sleep(15 * (tr + 1)); continue
                break
            except Exception:
                time.sleep(5)
        if b[:2] == b"\xff\xd8": break
        time.sleep(2)
    if b[:2] != b"\xff\xd8":
        try: b = urllib.request.urlopen(urllib.request.Request("https://upload.wikimedia.org/wikipedia/commons/%s/%s/%s" % (h[0], h[:2], q), headers=UA), timeout=90).read()
        except Exception: b = b""
    if b[:2] == b"\xff\xd8":
        open(os.path.join(d, "%02d.jpg" % n), "wb").write(b)
        open(os.path.join(d, "sources.txt"), "a").write("%02d.jpg  https://commons.wikimedia.org/wiki/File:%s\n" % (n, f)); n += 1
        print("ok", name)
    else: print("FAILED", name)
    time.sleep(2)
