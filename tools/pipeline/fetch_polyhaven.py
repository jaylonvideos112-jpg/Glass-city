#!/usr/bin/env python3
"""Download CC0 PBR textures / models from Poly Haven (polyhaven.com, CC0 1.0) via its public API.
usage: fetch_polyhaven.py OUTDIR RES asset[:maps] ...   maps default: Diffuse,nor_gl,Rough   (RES: 1k/2k)
       fetch_polyhaven.py --model OUTDIR RES asset ...   (glTF + its textures)
Generic User-Agent only."""
import json, os, sys, urllib.request
UA = {"User-Agent": "GlassCityBuilder/0.3"}
def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90).read()
def files(a): return json.loads(get("https://api.polyhaven.com/files/" + a))
def tex(out, res, spec):
    a, _, maps = spec.partition(":")
    maps = maps.split(",") if maps else ["Diffuse", "nor_gl", "Rough"]
    f = files(a); os.makedirs(out, exist_ok=True)
    for m in maps:
        if m not in f: print("  missing", a, m); continue
        r = f[m].get(res) or f[m][sorted(f[m])[0]]
        u = r.get("jpg", r.get("png"))["url"]
        dst = os.path.join(out, "%s_%s.%s" % (a, {"Diffuse": "diff", "nor_gl": "nor", "Rough": "rough", "arm": "arm", "AO": "ao"}.get(m, m), u.rsplit(".", 1)[1]))
        if not os.path.exists(dst): open(dst, "wb").write(get(u))
    print("ok", a)
def model(out, res, a):
    f = files(a)["gltf"][res]["gltf"]; d = os.path.join(out, a); os.makedirs(d, exist_ok=True)
    open(os.path.join(d, a + ".gltf"), "wb").write(get(f["url"]))
    for rel, inc in f.get("include", {}).items():
        p = os.path.join(d, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
        if not os.path.exists(p): open(p, "wb").write(get(inc["url"]))
    print("ok model", a)
if __name__ == "__main__":
    args = sys.argv[1:]
    if args[0] == "--model":
        for a in args[3:]: model(args[1], args[2], a)
    else:
        for a in args[2:]: tex(args[0], args[1], a)
