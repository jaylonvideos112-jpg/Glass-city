"""Face fitting for the character creator (runs inside Blender with MPFB2).

1. Correspondence (built once, cached in mp_to_mh.json): every one of MediaPipe's 468 face-mesh landmarks is tied
   to a vertex of the MakeHuman base mesh. MediaPipe's canonical face is aligned to the base head on the eyes and
   nose tip, then nearest-vertex matching is refined 3 times while the MakeHuman face sliders are fitted to the
   canonical face (so the match is made between two faces of the same shape).
2. Fit: photo landmarks (tools/pipeline/face_landmarks.py) -> alternate (a) similarity pose of the model face onto
   the photo points and (b) bounded linear least squares for the face slider weights. MakeHuman targets are
   linear vertex offsets, so (b) is exact: min |W (P0 + D w - L)|^2 + lam |w|^2, 0 <= w <= 1.
3. Photo projection: the posed model face is projected into the photo and the photo is baked into the skin
   texture's UV space, feathered into the skin and colour-matched to it."""
import os, json, math, glob, importlib
import numpy as np
import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
CORR = os.path.join(HERE, "mp_to_mh.json")
CANON = os.environ.get("MP_CANON", "/home/claude/dl/facefit/canonical_face_model.obj")
# slider families the face fit may use (MakeHuman target folders); ears are never seen from the front
FIT_DIRS = ["nose", "mouth", "eyes", "eyebrows", "chin", "cheek", "forehead", "head", "neck"]
SKIP = ("head-scale", "head-trans", "head-age", "neck-trans", "neck-scale-vert")
# per-family slider limits: the lip and nose correspondences are the least reliable, so they may move less
CAPS = {"mouth": 0.35, "nose": 0.5, "l-eye": 0.5, "eyebrows": 0.5, "chin": 0.6, "l-cheek": 0.6, "head-scale": 0.5,
        "head-fat": 0.6, "head-": 0.35, "forehead": 0.5}
def cap_of(name):
    for k, v in CAPS.items():
        if name.startswith(k): return v
    return 0.9
# MediaPipe landmark groups
LIPS = [0, 13, 14, 17, 37, 39, 40, 61, 78, 80, 81, 82, 84, 87, 88, 91, 95, 146, 178, 181, 185, 191, 267, 269, 270, 291,
        308, 310, 311, 312, 314, 317, 318, 321, 324, 375, 402, 405, 409, 415]
CONTOUR = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152, 148, 176, 149,
           150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]

def _mpfb(name): return importlib.import_module("bl_ext.user_default.mpfb.services." + name)

def mesh_coords(obj):
    """current vertex positions (shape-key mix applied, no modifiers), object space"""
    n = len(obj.data.vertices)
    co = np.empty(n * 3); obj.data.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
    sk = obj.data.shape_keys
    if not sk: return co
    B = np.empty(n * 3); sk.reference_key.data.foreach_get("co", B); B = B.reshape(-1, 3)
    out = B.copy()
    for k in sk.key_blocks:
        if k == sk.reference_key or k.mute or abs(k.value) < 1e-6: continue
        a = np.empty(n * 3); k.data.foreach_get("co", a)
        out += k.value * (a.reshape(-1, 3) - B)
    return out

def group_verts(obj, name):
    gi = obj.vertex_groups[name].index
    return np.array([v.index for v in obj.data.vertices if any(g.group == gi and g.weight > 0.5 for g in v.groups)])

def canonical():
    C = np.array([[float(t) for t in l.split()[1:4]] for l in open(CANON) if l.startswith("v ")])[:468]
    return np.stack([C[:, 0], -C[:, 2], C[:, 1]], 1)        # MediaPipe (x, y up, z toward viewer) -> Blender (x, y back, z up)

def umeyama(src, dst, w=None):
    """similarity (s, R, t) with dst ~ s R src + t"""
    w = np.ones(len(src)) if w is None else w; w = w / w.sum()
    ms, md = (src * w[:, None]).sum(0), (dst * w[:, None]).sum(0)
    a, b = src - ms, dst - md
    cov = (b * w[:, None]).T @ a
    U, S, Vt = np.linalg.svd(cov); d = np.sign(np.linalg.det(U @ Vt))
    D = np.diag([1, 1, d]); R = U @ D @ Vt
    var = (w * (a ** 2).sum(1)).sum(); s = (S * np.diag(D)).sum() / var
    return s, R, md - s * R @ ms

# ------------------------------------------------------------------------------------------------- face sliders
_TS = None
# curated sliders a front photo can actually measure (l- eye/cheek sliders are tied to their r- twin: symmetric)
CURATED = """nose-scale-horiz nose-scale-vert nose-nostrils-width nose-point-width nose-flaring nose-width1 nose-width2
nose-width3 nose-base:up,down nose-trans:up,down mouth-scale-horiz mouth-scale-vert mouth-trans:up,down
mouth-upperlip-height mouth-lowerlip-height mouth-upperlip-width mouth-lowerlip-width mouth-cupidsbow-width
l-eye-scale l-eye-trans:in,out l-eye-trans:up,down l-eye-height1 l-eye-height2 l-eye-height3 l-eye-corner1:up,down
l-eye-corner2:up,down chin-width chin-height chin-jaw-drop chin-bones chin-triangle: l-cheek-bones l-cheek-volume
l-cheek-inner forehead-scale-vert forehead-temple head-oval: head-round: head-square: head-triangular:
head-invertedtriangular: head-diamond: head-rectangular: head-fat head-scale-horiz eyebrows-trans:up,down
eyebrows-angle:up,down""".split()

def target_paths():
    """{target name: [files]} (l-/r- twins share one entry) and the slider list: [(name, neg target|None, pos target)]"""
    root = _mpfb("locationservice").LocationService.get_mpfb_data("targets")
    files = {os.path.basename(f)[:-len(".target.gz")]: f for f in glob.glob(os.path.join(root, "*", "*.target.gz"))}
    out = {}; sliders = []
    def add(n):
        if n not in files: return None
        fs = [files[n]]
        if n.startswith("l-") and "r-" + n[2:] in files: fs.append(files["r-" + n[2:]])
        out[n] = fs; return n
    excl = tuple(x for x in os.environ.get("FIT_EXCLUDE", "").split(",") if x)
    for item in CURATED:
        if excl and item.startswith(excl): continue
        base, _, suf = item.partition(":")
        if ":" in item and not suf:
            if add(base): sliders.append((base, None, base))
            continue
        a, b = suf.split(",") if suf else ("decr", "incr")
        neg, pos = add("%s-%s" % (base, a)), add("%s-%s" % (base, b))
        if neg and pos: sliders.append((base, neg, pos))
    return out, sliders

def load_slider_keys(obj, names_paths):
    """load each target file as a zero-weight shape key; returns {column: [shape key names]}"""
    TS = _mpfb("targetservice").TargetService
    if not obj.data.shape_keys: obj.shape_key_add(name="Basis")
    keys = {}
    for n, paths in names_paths.items():
        ks = []
        for p in paths:
            tn = os.path.basename(p)[:-len(".target.gz")]
            if tn in obj.data.shape_keys.key_blocks: ks.append(tn); continue
            sk = TS.load_target(obj, p, weight=0.0, name=tn)
            if sk is not None: ks.append(sk.name)
        if ks: keys[n] = ks
    return keys

def deltas(obj, keys, idx):
    kb = obj.data.shape_keys.key_blocks; basis = obj.data.shape_keys.reference_key
    B = np.empty(len(basis.data) * 3); basis.data.foreach_get("co", B); B = B.reshape(-1, 3)[idx]
    D = np.zeros((len(idx) * 3, len(keys)))
    for j, (n, ks) in enumerate(keys.items()):
        for k in ks:
            a = np.empty(len(basis.data) * 3); kb[k].data.foreach_get("co", a)
            D[:, j] += (a.reshape(-1, 3)[idx] - B).ravel()
    return D

def solve(P0, D, L, wts, lam, iters=6, x0=None, lo=None, hi=None):
    """alternate similarity pose and bounded LSQ. P0: model points (n,3); L: target points (n,3) in any frame."""
    from scipy.optimize import lsq_linear
    w = np.zeros(D.shape[1]) if x0 is None else np.array(x0, float)
    for it in range(iters):
        P = P0 + (D @ w).reshape(-1, 3)
        s, R, t = umeyama(P, L, wts[:, 0])
        Lm = ((L - t) @ R) / s                                   # target points in model space
        Wr = np.sqrt(wts).ravel()
        A = np.vstack([D * Wr[:, None], math.sqrt(lam) * np.eye(D.shape[1])])
        b = np.concatenate([((Lm - P0).ravel()) * Wr, np.zeros(D.shape[1])])
        hi_ = np.full(D.shape[1], float(os.environ.get("FIT_MAX", 0.9))) if hi is None else np.asarray(hi, float)
        lo_ = np.zeros(D.shape[1]) if lo is None else np.maximum(lo, -hi_)
        w = lsq_linear(A, b, bounds=(lo_, hi_), lsmr_tol="auto", max_iter=300).x
    P = P0 + (D @ w).reshape(-1, 3)
    s, R, t = umeyama(P, L, wts[:, 0])
    Q = s * P @ R.T + t; err = np.sqrt(((Q - L)[:, [0, 2]] ** 2).sum(1)).mean() / s      # frontal-plane error
    return w, (s, R, t), err

# ------------------------------------------------------------------------------------------------- correspondence
def build_correspondence(obj):
    V = mesh_coords(obj)
    body = group_verts(obj, "body")
    eL = V[group_verts(obj, "helper-l-eye")].mean(0); eR = V[group_verts(obj, "helper-r-eye")].mean(0)
    if eL[0] < eR[0]: eL, eR = eR, eL                          # subject's left = +x
    head = body[V[body, 2] > (eL[2] - 0.16)]
    mid = head[np.abs(V[head, 0]) < 0.004]
    nose = mid[np.argmin(V[mid, 1] + 10 * (V[mid, 2] > eL[2]) + 10 * (V[mid, 2] < eL[2] - 0.08))]
    C = canonical()
    src = np.array([(C[362] + C[263]) / 2, (C[33] + C[133]) / 2, C[1]])
    dst = np.array([eL, eR, V[nose]])
    s, R, t = umeyama(src, dst)
    Cm = s * C @ R.T + t
    from scipy.spatial import cKDTree
    names, _ = target_paths(); keys = load_slider_keys(obj, names)
    corr = None
    for rnd in range(4):
        Vn = mesh_coords(obj)
        # surface points: match on the front of the face in the frontal plane (x, z), so lip and nose landmarks land
        # on the visible lip/nose surface and not on the inside of the mouth or under the nose; the jaw contour
        # (silhouette points) matches in 3D
        nrm = np.array([obj.data.vertices[i].normal[:] for i in head])
        front = head[nrm[:, 1] < -0.35]
        tree3 = cKDTree(Vn[head]); _, ii = tree3.query(Cm); corr = head[ii]
        tree2 = cKDTree(Vn[front][:, [0, 2]]); _, jj = tree2.query(Cm[:, [0, 2]])
        for k in LIPS: corr[k] = front[jj[k]]     # lips only: 3D matching put them inside the mouth / under the lip
        if rnd == 3: break
        D = deltas(obj, keys, corr); P0 = Vn[corr]
        wts = np.ones((468, 3)); wts[LIPS, 1] = 0.1
        w, (s2, R2, t2), err = solve(P0, D, Cm, wts, lam=2e-6)
        for (n, ks), x in zip(keys.items(), w):
            for k in ks: obj.data.shape_keys.key_blocks[k].value = float(x)
        print("corr round %d: mean err %.4f m, %d sliders > 0.05" % (rnd, err, int((w > 0.05).sum())))
    for ks in keys.values():
        for k in ks: obj.data.shape_keys.key_blocks[k].value = 0.0
    json.dump({"mp_to_mh": [int(i) for i in corr]}, open(CORR, "w"))
    return corr

# ------------------------------------------------------------------------------------------------- fit to photo
def fit(obj, F, TargetService=None):
    lm = json.load(open(F["landmarks"]))
    L = np.array(lm["landmarks"])[:468]
    L = np.stack([L[:, 0], L[:, 2], -L[:, 1]], 1)               # pixels: x right, depth, up
    corr = np.array(json.load(open(CORR))["mp_to_mh"]) if os.path.exists(CORR) else build_correspondence(obj)
    names, sliders = target_paths(); keys = load_slider_keys(obj, names)
    V = mesh_coords(obj)                                         # macro-shaped head, sliders at 0
    Dt = deltas(obj, keys, corr); col = {n: j for j, n in enumerate(keys)}; P0 = V[corr]
    wts = np.ones((468, 3)); wts[:, 1] = float(F.get("depth_weight", 0.0))
    wts[CONTOUR] *= 0.6
    bs = lm.get("blendshapes", {})
    expr = max(bs.get("mouthSmileLeft", 0), bs.get("mouthSmileRight", 0), bs.get("jawOpen", 0))
    wts[LIPS] *= 0.25 if expr > 0.3 else 0.5                    # lip outlines match loosely; a smile must not bake in
    s0, R0, t0 = umeyama(P0, L)
    Lm = ((L - t0) @ R0) / s0                                    # photo points in model units
    lam = float(F.get("lam", 2e-5)) / max(0.05, float(F.get("strength", 1.0)))
    # pass 1: each opposing pair is one signed slider (pos - neg) / 2
    D1 = np.stack([(Dt[:, col[pz]] - (Dt[:, col[ng]] if ng else 0)) / (2.0 if ng else 1.0) for _, ng, pz in sliders], 1)
    caps = np.array([cap_of(n) for n, _, _ in sliders])
    w1, _, _ = solve(P0, D1, Lm, wts, lam, lo=np.array([-1.0 if ng else 0.0 for _, ng, _ in sliders]), hi=caps)
    # pass 2: the side each slider landed on, exact target, 0..1
    chosen = [(pz if x >= 0 else ng) for (n, ng, pz), x in zip(sliders, w1)]
    D2 = np.stack([Dt[:, col[c]] for c in chosen], 1)
    w2, pose, err = solve(P0, D2, Lm, wts, lam, lo=np.zeros(len(chosen)), hi=caps, x0=np.abs(w1))
    keys = {c: keys[c] for c in chosen}; w = w2
    kb = obj.data.shape_keys.key_blocks
    out = {}
    for (n, ks), x in zip(keys.items(), w):
        for k in ks: kb[k].value = float(x)
        if x > 0.01: out[n] = round(float(x), 3)
    s, R, t = pose
    F["_pose"] = (s0 * s, R0 @ R, s0 * (R0 @ t) + t0)
    F["_lm"] = lm
    try:
        from PIL import Image, ImageDraw
        im = Image.open(lm["photo"]).convert("RGB"); dr = ImageDraw.Draw(im)
        S_, R_, T_ = F["_pose"]; Q = S_ * (P0 + (D2 @ w).reshape(-1, 3)) @ R_.T + T_
        for (x, _, y), (a, _, b) in zip(Q, L): dr.line([(a, -b), (x, -y)], fill=(255, 255, 0)); dr.point((x, -y), fill=(255, 0, 0))
        im.save(os.path.splitext(F["landmarks"])[0] + "_fit.png")
    except Exception as ex: print("overlay failed", ex)
    print("face fit: mean landmark error %.1f mm, %d sliders used" % (err * 1000, len(out)))
    json.dump(out, open(os.path.splitext(F["landmarks"])[0] + "_sliders.json", "w"), indent=1)
    return out

# ------------------------------------------------------------------------------------------------- photo -> skin
def project_photo(obj, F):
    from PIL import Image
    lm = F["_lm"]; s, R, t = F["_pose"]
    photo = np.asarray(Image.open(F.get("photo") or lm["photo"]).convert("RGB")).astype(np.float32) / 255.0
    H, W = photo.shape[:2]
    V = mesh_coords(obj)
    Pp = s * V @ R.T + t                                         # (x px, depth, -y px)
    px, py = Pp[:, 0], -Pp[:, 2]
    # skin material + its diffuse image
    mat = obj.material_slots[0].material
    tex = next(n for n in mat.node_tree.nodes if n.type == "TEX_IMAGE" and n.image and "normal" not in n.image.name.lower())
    img = tex.image; TW, TH = img.size
    T = np.array(img.pixels[:], dtype=np.float32).reshape(TH, TW, 4)
    me = obj.data; uvl = me.uv_layers.active.data
    body = set(group_verts(obj, "body").tolist())
    # which faces: front-facing in the photo and inside the landmark face region (with a feather margin)
    from matplotlib.path import Path as MPath
    Lpx = np.array(lm["landmarks"])[:468, :2]
    hull = MPath(Lpx[CONTOUR])
    cen = Lpx[CONTOUR].mean(0); rad = np.linalg.norm(Lpx[CONTOUR] - cen, axis=1).mean()
    acc = np.zeros((TH, TW, 3), np.float32); wacc = np.zeros((TH, TW), np.float32)
    for poly in me.polygons:
        vs = list(poly.vertices)
        if vs[0] not in body: continue
        nrm = np.array(poly.normal)
        fz = float(np.dot(R @ nrm, np.array([0, -1.0, 0])))   # >0: faces the camera
        if fz < 0.15: continue
        c = np.array([px[vs].mean(), py[vs].mean()])
        dn = np.linalg.norm(c - cen) / rad
        if dn > 1.15 or not (hull.contains_point(c) or dn < 0.9): continue
        fw = min(1.0, (fz - 0.15) / 0.35) * min(1.0, max(0.0, (1.12 - dn) / 0.25))
        if fw <= 0: continue
        loops = list(poly.loop_indices)
        uv = np.array([uvl[l].uv[:] for l in loops]) * [TW, TH]
        ip = np.stack([px[vs], py[vs]], 1)
        for k in range(1, len(vs) - 1):
            _raster(uv[[0, k, k + 1]], ip[[0, k, k + 1]], photo, acc, wacc, fw)
    m = wacc > 0
    acc[m] /= wacc[m, None]
    # colour match: photo skin median vs texture median in the same texels
    tex_rgb = T[..., :3]
    a = np.median(acc[m], 0); b = np.median(tex_rgb[m], 0)
    gain = a / np.maximum(b, 1e-3)
    lum = float(np.clip(gain.mean(), 0.75, 1.35)); gain = np.clip(gain / gain.mean() * lum, 0.5, 1.8)
    tone = tex_rgb * gain                                        # whole skin re-toned to the photo
    acc[m] = acc[m] * (np.median(tone[m], 0) / np.maximum(np.median(acc[m], 0), 1e-3))   # photo detail, matched tone
    # feathered blend weight: grow the mask edge softly
    wm = np.clip(wacc, 0, 1)
    try:
        from scipy.ndimage import gaussian_filter
        wm = gaussian_filter(wm, sigma=max(2, TW // 256)) * (wacc > 0)
    except Exception: pass
    wm = np.clip(wm * float(F.get("photo_strength", 0.9)), 0, 1)[..., None]
    T[..., :3] = tone * (1 - wm) + acc * wm
    new = bpy.data.images.new(obj.name + "_face", TW, TH, alpha=True)
    new.pixels = T.ravel(); new.file_format = "PNG"
    outp = os.path.join(os.path.dirname(os.path.abspath(F["landmarks"])), obj.name + "_skin.png")
    new.filepath_raw = outp; new.save()
    tex.image = new
    F["_skin_gain"] = gain.tolist()
    print("photo projected: %d texels, skin gain %s" % (int(m.sum()), np.round(gain, 2)))

def _raster(uv, ip, photo, acc, wacc, fw):
    """fill triangle uv (texel coords, y up) with photo samples at the matching image points (bilinear)"""
    TH, TW = wacc.shape; H, W = photo.shape[:2]
    u0, v0 = np.floor(uv.min(0)).astype(int); u1, v1 = np.ceil(uv.max(0)).astype(int)
    u0, v0 = max(u0, 0), max(v0, 0); u1, v1 = min(u1, TW - 1), min(v1, TH - 1)
    if u1 < u0 or v1 < v0: return
    gu, gv = np.meshgrid(np.arange(u0, u1 + 1) + 0.5, np.arange(v0, v1 + 1) + 0.5)
    a, b, c = uv
    den = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
    if abs(den) < 1e-9: return
    l1 = ((b[1] - c[1]) * (gu - c[0]) + (c[0] - b[0]) * (gv - c[1])) / den
    l2 = ((c[1] - a[1]) * (gu - c[0]) + (a[0] - c[0]) * (gv - c[1])) / den
    l3 = 1 - l1 - l2
    ins = (l1 >= -0.01) & (l2 >= -0.01) & (l3 >= -0.01)
    if not ins.any(): return
    X = l1 * ip[0, 0] + l2 * ip[1, 0] + l3 * ip[2, 0]; Y = l1 * ip[0, 1] + l2 * ip[1, 1] + l3 * ip[2, 1]
    X = np.clip(X, 0, W - 1.001); Y = np.clip(Y, 0, H - 1.001)
    x0 = X.astype(int); y0 = Y.astype(int); fx = (X - x0)[..., None]; fy = (Y - y0)[..., None]
    col = (photo[y0, x0] * (1 - fx) * (1 - fy) + photo[y0, x0 + 1] * fx * (1 - fy) +
           photo[y0 + 1, x0] * (1 - fx) * fy + photo[y0 + 1, x0 + 1] * fx * fy)
    rows = np.arange(v0, v1 + 1)[:, None].repeat(u1 - u0 + 1, 1); cols = np.arange(u0, u1 + 1)[None, :].repeat(v1 - v0 + 1, 0)
    rr, cc = rows[ins], cols[ins]
    acc[rr, cc] += col[ins] * fw; wacc[rr, cc] += fw
