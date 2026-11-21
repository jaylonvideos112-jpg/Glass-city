"""GLASS CITY's own human head (no MakeHuman): a parametric, Bully-style head built from scratch.

How it works:
  1. The head is a signed-distance field (SDF) made of simple sculpting primitives blended with smooth unions:
     cranium, face mass, jaw, chin, jaw angles, cheekbones, brow ridge, nose (bridge, tip, wings), muzzle, lips,
     the mouth slit, eye sockets with eyelids, and the neck. Each named parameter in DEFAULTS moves or resizes some
     of those primitives (the game's face sliders are exactly these parameters).
  2. A FIXED set of rays (same for every face) is shot inward from outside towards the head centre (or the neck
     axis, for the neck rows), and each ray stops where it meets the surface. Ray i always becomes vertex i, so every
     face has identical topology. A face slider's blend shape is head(P + 1) - head(P).
  3. Rays are denser over the face, especially round the eyes, nose and mouth, so the mesh has detail where it
     matters.
Eyes are separate spheres (iris and pupil painted); the SDF already contains the eyeball as solid, so the eyelids
wrap them. Ears come from ear.py. Forward is +Y (Godot -Z), up is +Z, metres. The head centre is the origin; the eye
line is at z ~ +0.01.
head_mesh(P) -> verts (N,3), quads, tris, uv (N,2), anchors."""
import math
import numpy as np

DEFAULTS = {
    # skull
    "head_width": 0.0, "head_height": 0.0, "head_depth": 0.0, "crown": 0.0, "back_head": 0.0, "jaw_width": 0.0,
    "jaw_square": 0.0, "chin_length": 0.0, "chin_width": 0.0, "chin_forward": 0.0, "cheek_full": 0.0,
    "forehead_height": 0.0, "forehead_slope": 0.0,
    # eyes
    "eye_size": 0.0, "eye_spacing": 0.0, "eye_height": 0.0, "eye_tilt": 0.0, "eye_open": 0.0, "eye_depth": 0.0,
    "brow_ridge": 0.0, "brow_height": 0.0,
    # nose
    "nose_length": 0.0, "nose_width": 0.0, "nose_size": 0.0, "nose_bridge": 0.0, "nose_tip": 0.0, "nose_hook": 0.0,
    "nostril_flare": 0.0, "nose_upturn": 0.0,
    # cheeks
    "cheekbones": 0.0, "cheek_hollow": 0.0,
    # mouth
    "mouth_width": 0.0, "mouth_height": 0.0, "lip_upper": 0.0, "lip_lower": 0.0, "mouth_forward": 0.0, "smile": 0.0,
    # ears (ear.py)
    "ear_size": 0.0, "ear_out": 0.0,
    # neck
    "neck_width": 0.0,
}

# ------------------------------------------------------------------ SDF helpers (p: (...,3) arrays)
def ell(p, c, r):
    q = (p - c) / r
    k0 = np.linalg.norm(q, axis=-1); k1 = np.linalg.norm(q / r, axis=-1)
    return k0 * (k0 - 1) / np.maximum(k1, 1e-9)

def sph(p, c, r):
    return np.linalg.norm(p - c, axis=-1) - r

def capsule(p, a, b, ra, rb):
    a = np.asarray(a, float); b = np.asarray(b, float); ba = b - a
    t = np.clip(((p - a) @ ba) / (ba @ ba), 0, 1)
    return np.linalg.norm(p - (a + t[..., None] * ba), axis=-1) - (ra + (rb - ra) * t)

def rbox(p, c, r, rad):
    q = np.abs(p - c) - (np.asarray(r) - rad)
    return np.linalg.norm(np.maximum(q, 0), axis=-1) + np.minimum(q.max(-1), 0) - rad

def smin(a, b, k):
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0, 1)
    return b * (1 - h) + a * h - k * h * (1 - h)

def smax(a, b, k):
    return -smin(-a, -b, k)

def layout(P=None):
    """the primitive positions/sizes for a parameter set (also used for anchors)"""
    p = dict(DEFAULTS); p.update(P or {})
    L = {"p": p}
    L["eyeZ"] = 0.010 + 0.006 * p["eye_height"]
    L["eyeX"] = 0.0315 * (1 + 0.08 * p["eye_spacing"])
    L["eyeR"] = 0.0112 * (1 + 0.10 * p["eye_size"])
    L["eyeY"] = 0.061 - 0.004 * p["eye_depth"]
    L["mouthZ"] = -0.060 - 0.005 * p["mouth_height"] - 0.003 * p["nose_length"]
    L["noseTip"] = np.array([0, 0.106 + 0.005 * p["nose_tip"] + 0.004 * p["nose_size"], -0.026 - 0.007 * p["nose_length"]])
    L["chin"] = np.array([0, 0.068 + 0.007 * p["chin_forward"], -0.100 - 0.010 * p["chin_length"]])
    L["browZ"] = L["eyeZ"] + 0.017 + 0.005 * p["brow_height"]
    return L

def head_sdf(X, L):
    p = L["p"]
    hw, hh, hd = 1 + 0.07 * p["head_width"], 1 + 0.06 * p["head_height"], 1 + 0.06 * p["head_depth"]
    # cranium (Bully: a touch big and round), crown and back-of-head
    d = ell(X, np.array([0, -0.014 - 0.004 * p["back_head"], 0.020 + 0.004 * p["crown"]]),
            np.array([0.077 * hw, (0.094 + 0.004 * p["back_head"]) * hd, (0.090 + 0.005 * p["crown"]) * hh]))
    # forehead: flatter front, slope slider tilts it back
    fh = ell(X, np.array([0, 0.040 - 0.004 * p["forehead_slope"], 0.038 + 0.004 * p["forehead_height"]]), np.array([0.062 * hw, 0.046, 0.050]))
    d = smin(d, fh, 0.02)
    # face mass (cheeks/maxilla)
    jw = 1 + 0.10 * p["jaw_width"]
    d = smin(d, ell(X, np.array([0, 0.030, -0.026]), np.array([0.059 * hw, 0.064, 0.064])), 0.025)
    # jaw: ellipsoid blended toward a rounded box for jaw_square
    jc = np.array([0, 0.024, -0.072 - 0.004 * p["chin_length"]]); jr = np.array([0.054 * jw, 0.060, 0.040 + 0.004 * p["chin_length"]])
    jd = ell(X, jc, jr)
    sq = np.clip(0.35 + 0.35 * p["jaw_square"], 0, 1)
    jd = jd * (1 - sq) + rbox(X, jc, jr, 0.022) * sq
    d = smin(d, jd, 0.02)
    # jaw angles (gonion)
    for sx in (-1, 1):
        d = smin(d, sph(X, np.array([sx * 0.054 * jw, -0.022, -0.058]), 0.016), 0.02)
    # chin
    d = smin(d, ell(X, L["chin"], np.array([0.021 * (1 + 0.25 * p["chin_width"]), 0.016, 0.018])), 0.016)
    # cheekbones / cheeks
    for sx in (-1, 1):
        d = smin(d, ell(X, np.array([sx * 0.047, 0.064, L["eyeZ"] - 0.020]), np.array([0.018, 0.013 + 0.004 * p["cheekbones"], 0.012])), 0.012)
        ch = ell(X, np.array([sx * 0.044, 0.060, L["mouthZ"] + 0.012]), np.array([0.020, 0.016, 0.018]))
        cv = p["cheek_full"] - p["cheek_hollow"]
        if cv > 0:
            d = smin(d, ch + 0.006 * (1 - cv), 0.015)
        elif cv < 0:
            d = smax(d, -(ch + 0.016 + 0.012 * cv), 0.012)
    # muzzle (mouth area pushes forward)
    d = smin(d, ell(X, np.array([0, 0.068 + 0.004 * p["mouth_forward"], L["mouthZ"] + 0.002]), np.array([0.032, 0.034, 0.030])), 0.018)
    # brow ridge
    br = 1 + 0.4 * p["brow_ridge"]
    for sx in (-1, 1):
        d = smin(d, ell(X, np.array([sx * 0.028, 0.077 + 0.003 * br, L["browZ"]]), np.array([0.025, 0.011 * br, 0.010])), 0.014)
    d = smin(d, ell(X, np.array([0, 0.083 + 0.002 * br, L["browZ"] - 0.002]), np.array([0.012, 0.008, 0.010])), 0.01)
    # eye sockets, eyeballs and lids
    ex, ez, er, ey = L["eyeX"], L["eyeZ"], L["eyeR"], L["eyeY"]
    lids = None
    for sx in (-1, 1):
        c = np.array([sx * ex, ey, ez])
        d = smax(d, -sph(X, c + np.array([0, 0.007, 0.002]), 0.0165), 0.010)
        # almond opening (prism along +Y)
        lx = X[..., 0] - sx * ex; lz = X[..., 2] - ez - 0.20 * p["eye_tilt"] * (lx * sx)
        a = er * 1.12; b = er * (0.44 + 0.12 * p["eye_open"])
        bz = b * np.clip(1 - 0.55 * (lx / a) ** 2, 0.05, 1)
        alm = (np.sqrt((lx / a) ** 2 + (lz / bz) ** 2) - 1) * min(a, b)
        alm = np.maximum(alm, c[1] - X[..., 1])                    # only cuts in front of the eye centre
        lid = np.maximum(sph(X, c, er + 0.0022), -alm)
        lids = lid if lids is None else np.minimum(lids, lid)
        d = np.minimum(d, sph(X, c, er))                            # eyeball (solid; drawn separately)
    d = smin(d, lids, 0.004)
    # nose
    ns = 1 + 0.12 * p["nose_size"]; nw = 1 + 0.15 * p["nose_width"]
    tip = L["noseTip"]; top = np.array([0, 0.083, L["eyeZ"] - 0.002])
    mid = (top + tip) / 2 + np.array([0, 0.004 * p["nose_hook"] + 0.002 * p["nose_bridge"], 0])
    nd = smin(capsule(X, top, mid, 0.0055 * nw, 0.0065 * nw * ns), capsule(X, mid, tip - [0, 0.004, -0.002], 0.0065 * nw * ns, 0.0085 * ns * nw), 0.006)
    up = 0.004 * p["nose_upturn"]
    nd = smin(nd, ell(X, tip + np.array([0, 0, up * 0.5]), np.array([0.0125 * ns * nw, 0.0105 * ns, 0.0105 * ns])), 0.008)
    fl = 1 + 0.25 * p["nostril_flare"]
    for sx in (-1, 1):
        nd = smin(nd, ell(X, tip + np.array([sx * 0.0140 * nw * fl, -0.012, -0.004 + up]), np.array([0.0082 * fl, 0.0080, 0.0068])), 0.007)
    d = smin(d, nd, 0.006)
    # nostril holes (underside)
    for sx in (-1, 1):
        d = smax(d, -ell(X, tip + np.array([sx * 0.0065 * nw, -0.006, -0.0085 + up]), np.array([0.0035, 0.0045, 0.0022])), 0.002)
    # lips
    mw = 1 + 0.12 * p["mouth_width"]; mz = L["mouthZ"]; mf = 0.004 * p["mouth_forward"]
    lu = 1 + 0.35 * p["lip_upper"]; ll = 1 + 0.35 * p["lip_lower"]
    d = smin(d, ell(X, np.array([0, 0.091 + mf, mz + 0.0050 * lu]), np.array([0.0220 * mw, 0.0100, 0.0060 * lu])), 0.009)
    d = smin(d, ell(X, np.array([0, 0.087 + mf, mz - 0.0060 * ll]), np.array([0.0205 * mw, 0.0110, 0.0078 * ll])), 0.009)
    # mouth slit, curved up at the corners with smile
    sz = X[..., 2] - p["smile"] * 0.0045 * (X[..., 0] / (0.022 * mw)) ** 2
    Xs = np.stack([X[..., 0], X[..., 1], sz], -1)
    d = smax(d, -ell(Xs, np.array([0, 0.098 + mf, mz]), np.array([0.0225 * mw, 0.010, 0.0010])), 0.0015)
    # groove under the lower lip (mentolabial) and philtrum dip
    d = smax(d, -ell(X, np.array([0, 0.092, mz - 0.017]), np.array([0.016, 0.006, 0.0035])), 0.004)
    for sx in (-1, 1):
        d = smin(d, capsule(X, [sx * 0.0035, 0.088, mz + 0.010], [sx * 0.004, 0.096, tip[2] - 0.010], 0.0018, 0.0015), 0.003)
    # neck
    nk = 1 + 0.10 * p["neck_width"]
    d = smin(d, capsule(X, [0, -0.010, -0.050], [0, -0.004, -0.300], 0.056 * nk, 0.060 * nk), 0.03)
    return d

# ------------------------------------------------------------------ fixed ray layout
def _warp(s, a):
    return a * s + (1 - a) * s * np.abs(s)

def _rows(nv):
    """elevation angles (deg) for head rows, dense over the face band"""
    phis = np.linspace(89.0, -66.0, 4000)
    w = 1 + 2.2 * np.exp(-((phis + 15) / 28) ** 2)
    cdf = np.cumsum(w); cdf = (cdf - cdf[0]) / (cdf[-1] - cdf[0])
    return np.interp(np.linspace(0, 1, nv), cdf, phis)

def rays(nu=136, nv=100, neck_rows=12):
    s = np.linspace(-1, 1, nu, endpoint=False) + 1.0 / nu
    us = math.pi * _warp(s, 0.42)                        # azimuth, 0 = forward, dense at the front
    phis = np.radians(_rows(nv))
    O, Dd = [], []
    for ph in phis:
        dr = np.stack([np.cos(ph) * np.sin(us), np.cos(ph) * np.cos(us), np.full(nu, np.sin(ph))], -1)
        O.append(np.zeros((nu, 3))); Dd.append(dr)
    for k in range(neck_rows):
        z = -0.135 - 0.15 * k / (neck_rows - 1)
        dr = np.stack([np.sin(us), np.cos(us), np.zeros(nu)], -1)
        O.append(np.tile([0, -0.008, z], (nu, 1))); Dd.append(dr)
    return us, np.array(O), np.array(Dd)              # (rows, nu, 3)

def head_mesh(P=None, nu=136, nv=100, neck_rows=12):
    L = layout(P)
    us, O, Dd = rays(nu, nv, neck_rows)
    rows = O.shape[0]
    o = O.reshape(-1, 3); dr = Dd.reshape(-1, 3)
    # march inward from 0.3 m out; first point that is inside
    ts = np.arange(0.30, 0.0, -0.0015)
    hit = np.full(len(o), np.nan)
    prev = np.full(len(o), 0.30)
    for t in ts:
        m = np.isnan(hit)
        if not m.any(): break
        v = head_sdf(o[m] + dr[m] * t, L)
        idx = np.where(m)[0]
        inside = v < 0
        hit[idx[inside]] = t
    lo = hit.copy(); hi = hit + 0.0015                  # lo inside, hi outside
    for _ in range(18):
        mid = (lo + hi) / 2
        v = head_sdf(o + dr * mid[:, None], L)
        lo = np.where(v < 0, mid, lo); hi = np.where(v < 0, hi, mid)
    verts = o + dr * ((lo + hi) / 2)[:, None]
    # top cap
    topv = np.array([[0, verts[:nu, 1].mean(), verts[:nu, 2].max() + 0.0005]])
    verts = np.concatenate([verts, topv]); ti = len(verts) - 1
    quads = []
    for r in range(rows - 1):
        for c in range(nu):
            a = r * nu + c; b = r * nu + (c + 1) % nu
            quads.append((a, a + nu, b + nu, b))
    tris = [(ti, c, (c + 1) % nu) for c in range(nu)]
    uv = np.zeros((len(verts), 2))
    for r in range(rows):
        uv[r * nu:(r + 1) * nu, 0] = us / (2 * math.pi) + 0.5
        uv[r * nu:(r + 1) * nu, 1] = 1 - r / (rows - 1)
    uv[ti] = (0.5, 1.0)
    p = L["p"]
    anchors = {"eye_l": (L["eyeX"], L["eyeY"], L["eyeZ"]), "eye_r": (-L["eyeX"], L["eyeY"], L["eyeZ"]), "eye_r_m": L["eyeR"],
               "mouth_z": L["mouthZ"], "nose_tip": tuple(L["noseTip"]), "chin": tuple(L["chin"]), "nu": nu, "rows": rows,
               "ear_size": p["ear_size"], "ear_out": p["ear_out"]}
    return verts, quads, tris, uv, anchors
