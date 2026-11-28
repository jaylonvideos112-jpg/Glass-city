"""Download CC0 assets from Poly Haven (polyhaven.com, all CC0, no account needed) for the photoreal Blender map.

Textures: diffuse, OpenGL normal, roughness (and displacement when asked) at the chosen resolution.
HDRIs: one .hdr. Models: the glTF with its textures.
Files go to DEST/<kind>/<id>/ and are skipped when present. Polite: one request at a time, a short pause between.

usage: python3 tools/photoreal/fetch_assets.py DEST [--res 2k] tex:ID ... hdri:ID ... model:ID ..."""
import sys, os, json, time, urllib.request

UA = "GlassCityBuilder/0.3 (game reference research)"
args = sys.argv[1:]
DEST = args.pop(0)
RES = "2k"
if "--res" in args:
    i = args.index("--res"); RES = args[i + 1]; del args[i:i + 2]


def get(url, path=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    time.sleep(0.3)
    if path:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "wb").write(data)
    return data


for spec in args:
    kind, aid = spec.split(":", 1)
    files = json.loads(get("https://api.polyhaven.com/files/" + aid))
    out = os.path.join(DEST, kind, aid)
    if kind == "tex":
        maps = {"Diffuse": "diff", "nor_gl": "nor", "Rough": "rough", "Displacement": "disp", "AO": "ao"}
        for k, short in maps.items():
            if k not in files: continue
            f = files[k].get(RES, {}).get("jpg") or files[k].get(RES, {}).get("png")
            if not f: continue
            p = os.path.join(out, "%s.%s" % (short, f["url"].rsplit(".", 1)[1]))
            if not os.path.exists(p): get(f["url"], p)
    elif kind == "hdri":
        f = files["hdri"][RES]["hdr"]
        p = os.path.join(out, aid + ".hdr")
        if not os.path.exists(p): get(f["url"], p)
    elif kind == "model":
        g = files["gltf"][RES]["gltf"]
        p = os.path.join(out, aid + ".gltf")
        if not os.path.exists(p):
            get(g["url"], p)
            for rel, inc in g.get("include", {}).items():
                get(inc["url"], os.path.join(out, rel))
    print("ok", spec, "->", out)
