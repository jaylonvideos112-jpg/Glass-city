"""Download named Wikimedia Commons files (960px thumbnails) as reference photos for one replica, via curl
(urllib gets throttled where curl does not). Reference only, never shipped.
usage: fetch_named.py <refs dir>/<key> "File name.jpg" ..."""
import sys, os, time, hashlib, subprocess, urllib.parse
d = sys.argv[1]; os.makedirs(d, exist_ok=True)
UA = "GlassCityBuilder/0.3 (game reference research)"
n = len([f for f in os.listdir(d) if f.endswith(".jpg")])
for name in sys.argv[2:]:
    f = name.replace(" ", "_"); h = hashlib.md5(f.encode()).hexdigest(); q = urllib.parse.quote(f)
    ok = False
    for url in ["https://upload.wikimedia.org/wikipedia/commons/thumb/%s/%s/%s/%dpx-%s" % (h[0], h[:2], q, w, q) for w in (960, 1280, 500)] + \
               ["https://upload.wikimedia.org/wikipedia/commons/%s/%s/%s" % (h[0], h[:2], q)]:
        for tr in range(4):
            out = os.path.join(d, "%02d.jpg" % n)
            code = subprocess.run(["curl", "-s", "-A", UA, "--max-time", "90", "-o", out, "-w", "%{http_code}", url], capture_output=True, text=True).stdout
            if code == "200" and open(out, "rb").read(2) == b"\xff\xd8": ok = True; break
            if os.path.exists(out): os.remove(out)
            if code == "429": time.sleep(10 * (tr + 1)); continue
            break
        if ok: break
        time.sleep(2)
    if ok:
        open(os.path.join(d, "sources.txt"), "a").write("%02d.jpg  https://commons.wikimedia.org/wiki/File:%s\n" % (n, f)); n += 1
        print("ok", name, flush=True)
    else: print("FAILED", name, flush=True)
    time.sleep(3)
