"""MakeHuman proxy (MHCLO) fitting: clothes, hair, eyebrows, eyelashes and eyes ride the morphed base mesh.
Each proxy vertex = w1*V[a] + w2*V[b] + w3*V[c] + offset * per-axis scale (scales measured on the morphed mesh
between the reference vertex pairs given in the file). Pure numpy; coordinates in MakeHuman OBJ space."""
import os, numpy as np

def load(path):
    d = {"refs": [], "w": [], "off": [], "scale": {}, "delete": set(), "dir": os.path.dirname(path), "material": None}
    mode = None
    for line in open(path, encoding="utf-8", errors="ignore"):
        s = line.strip()
        if not s or s.startswith("#"): continue
        t = s.split()
        if t[0] in ("x_scale", "y_scale", "z_scale"):
            d["scale"][t[0][0]] = (int(t[1]), int(t[2]), float(t[3])); continue
        if t[0] == "obj_file": d["obj"] = os.path.join(d["dir"], t[1]); continue
        if t[0] == "material": d["material"] = os.path.normpath(os.path.join(d["dir"], t[1])); continue
        if t[0] == "name": d["name"] = t[1]; continue
        if t[0] == "verts": mode = "verts"; continue
        if t[0] == "delete_verts": mode = "delete"; continue
        if t[0] in ("weights", "tag", "uuid", "basemesh", "z_depth", "max_pole", "special_pose", "offsets", "material_name", "license", "author", "description"):
            if t[0] in ("weights", "offsets"): mode = None
            continue
        if mode == "verts":
            if len(t) == 9:
                d["refs"].append([int(t[0]), int(t[1]), int(t[2])]); d["w"].append([float(x) for x in t[3:6]]); d["off"].append([float(x) for x in t[6:9]])
            elif len(t) == 1:
                d["refs"].append([int(t[0])] * 3); d["w"].append([1.0, 0.0, 0.0]); d["off"].append([0.0, 0.0, 0.0])
        elif mode == "delete":
            k = 0
            while k < len(t):
                if k + 2 < len(t) and t[k + 1] == "-":
                    d["delete"].update(range(int(t[k]), int(t[k + 2]) + 1)); k += 3
                else:
                    d["delete"].add(int(t[k])); k += 1
    d["refs"] = np.array(d["refs"]); d["w"] = np.array(d["w"]); d["off"] = np.array(d["off"])
    return d

def fit(clo, V):
    sc = np.ones(3)
    for i, ax in enumerate("xyz"):
        if ax in clo["scale"]:
            a, b, ref = clo["scale"][ax]
            sc[i] = abs(V[a][i] - V[b][i]) / ref
    P = (V[clo["refs"]] * clo["w"][:, :, None]).sum(axis=1)
    return P + clo["off"] * sc

def load_obj(path):
    """vertices, uvs, faces as [(vi...), (ti...)]"""
    V, T, F = [], [], []
    for line in open(path, encoding="utf-8", errors="ignore"):
        if line.startswith("v "): V.append([float(x) for x in line.split()[1:4]])
        elif line.startswith("vt "): T.append([float(x) for x in line.split()[1:3]])
        elif line.startswith("f "):
            vs, ts = [], []
            for tok in line.split()[1:]:
                p = tok.split("/")
                vs.append(int(p[0]) - 1); ts.append(int(p[1]) - 1 if len(p) > 1 and p[1] else -1)
            F.append((vs, ts))
    return np.array(V), np.array(T) if T else np.zeros((0, 2)), F

def material(path):
    m = {"diffuse": None, "normal": None, "transparent": False, "cull": True}
    if not path or not os.path.exists(path): return m
    base = os.path.dirname(path)
    for line in open(path, encoding="utf-8", errors="ignore"):
        t = line.split()
        if len(t) < 2: continue
        if t[0] == "diffuseTexture": m["diffuse"] = os.path.join(base, t[1])
        if t[0] == "normalmapTexture": m["normal"] = os.path.join(base, t[1])
        if t[0] == "transparent": m["transparent"] = t[1] == "True"
        if t[0] == "backfaceCull": m["cull"] = t[1] == "True"
    return m
