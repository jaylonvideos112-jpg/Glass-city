"""GLASS CITY's own human head (no MakeHuman): a parametric, Bully-style head built from scratch.

The head is a quad grid over spherical coordinates around the head centre (u = azimuth, v = polar angle). The
radius at every grid point is a skull shape (stretched superellipsoid: wide cranium, narrower jaw, flat face) plus
facial features added as smooth displacement fields in "face coordinates" (X across the face, Z up the face):
eye sockets shaped like almonds (the eyeballs show through them, which gives eyelids for free), brow ridge, nose
(bridge, tip, wings, base), cheekbones, lips with a mouth slit, philtrum, chin and jaw. Every feature is controlled
by a named parameter (P below); the game's face sliders are exactly these parameters, so each slider is a blend
shape = head(P + step) - head(P). Ears are separate parametric shells; eyes are spheres with a painted iris.
Forward is +Y (Godot -Z), up is +Z, metres. The neck continues below as a tube for the body to join.
Coordinates: UV = (u / 2pi, v-ish) so the painted skin texture is laid out in the same angular space."""
import math
import numpy as np

# ---------------------------------------------------------------- parameters (all sliders default 0 = average)
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
    # ears
    "ear_size": 0.0, "ear_out": 0.0,
    # neck
    "neck_width": 0.0,
}
SLIDER_RANGE = 1.0      # every slider runs -1..+1

def g(x, s):            # gaussian bump
    return np.exp(-(x * x) / (2 * s * s))

def smooth(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)

def head_mesh(P=None, nu=112, nv=84, neck_rings=10):
    """returns verts (N,3), quads (list of 4-index tuples), uvs per vertex (N,2), and feature anchors (dict)"""
    p = dict(DEFAULTS); p.update(P or {})
    # ---- base proportions (m): Bully heads are a touch big and rounded
    W = 0.079 * (1 + 0.08 * p["head_width"])          # half width
    D = 0.098 * (1 + 0.07 * p["head_depth"])          # half depth (front-back)
    H = 0.118 * (1 + 0.07 * p["head_height"])         # half height (crown to chin ~ 2H)
    vmax = math.pi * 0.80                             # where the head surface stops and the neck tube starts
    us = np.linspace(0, 2 * math.pi, nu, endpoint=False)
    vs = np.linspace(0.02, vmax, nv)
    U, V = np.meshgrid(us, vs)                        # (nv, nu)
    # unit direction: u = 0 points forward (+Y)
    dx = np.sin(V) * np.sin(U); dy = np.sin(V) * np.cos(U); dz = np.cos(V)
    # ---- skull: superellipsoid-ish radius
    fwd = np.clip(dy, 0, 1); back = np.clip(-dy, 0, 1); low = np.clip(-dz, 0, 1); high = np.clip(dz, 0, 1)
    rx = W * (1 + 0.06 * p["crown"] * high - (0.22 + 0.12 * -p["jaw_width"]) * low * fwd ** 0.6
              - 0.08 * low * back)
    ry = D * (1 - 0.13 * fwd ** 2 * (1 - low) + 0.06 * p["back_head"] * back - 0.1 * low * back)
    rz = H * (1 + 0.05 * p["crown"] * high)
    # superellipse exponent: squarer jaw for jaw_square
    e = 2.0 + 0.6 * p["jaw_square"] * low
    denom = (np.abs(dx / rx) ** e + np.abs(dy / ry) ** e + np.abs(dz / rz) ** e) ** (1 / e)
    R = 1.0 / np.maximum(denom, 1e-6)
    pts = np.stack([dx * R, dy * R, dz * R], -1)
    # ---- face coordinates on the front: X across (m), Z up (m)
    X = pts[..., 0]; Z = pts[..., 2]; Yf = pts[..., 1]
    front = smooth(0.0, 0.45, dy) * (Yf > 0)
    disp = np.zeros_like(X)
    # landmarks (m), relative to the head centre
    eyeZ = 0.012 + 0.008 * p["eye_height"]
    eyeX = 0.033 * (1 + 0.1 * p["eye_spacing"])
    mouthZ = -0.062 - 0.006 * p["mouth_height"] - 0.004 * p["nose_length"]
    noseTipZ = -0.03 - 0.008 * p["nose_length"]
    browZ = eyeZ + 0.022 + 0.006 * p["brow_height"]
    chinZ = -0.1 - 0.012 * p["chin_length"]
    # forehead: slightly flatter and set back toward the top; slope slider
    disp += front * (-0.004 - 0.006 * p["forehead_slope"]) * smooth(browZ + 0.01, H * 0.8, Z)
    # brow ridge
    disp += front * (0.004 + 0.004 * p["brow_ridge"]) * g(Z - browZ, 0.007) * g(np.abs(X) - eyeX * 0.9, 0.022)
    # eye sockets: almond-shaped dents (the eyeball pokes through them)
    es = 1 + 0.12 * p["eye_size"]
    for sx in (-1, 1):
        lx = (X - sx * eyeX)
        tilt = 0.18 * p["eye_tilt"] * sx
        lz = (Z - eyeZ) - tilt * lx
        a = 0.0155 * es; b = (0.0072 + 0.0016 * p["eye_open"]) * es
        almond = (lx / a) ** 2 + (lz / (b * (1 - 0.35 * (lx / a) ** 2).clip(0.2, 1))) ** 2
        disp -= front * (0.016 + 0.004 * p["eye_depth"]) * np.exp(-almond ** 1.6 * 1.1)
        # soft orbit around the almond (upper lid crease and under-eye)
        disp -= front * 0.0035 * g(lx, 0.02) * g(lz + 0.002, 0.016)
    # cheekbones and cheeks
    for sx in (-1, 1):
        disp += front * (0.004 + 0.005 * p["cheekbones"]) * g(X - sx * 0.048, 0.016) * g(Z - (eyeZ - 0.028), 0.012)
        disp += front * (0.003 * p["cheek_full"] - 0.004 * p["cheek_hollow"]) * g(X - sx * 0.045, 0.018) * g(Z - (mouthZ + 0.012), 0.016)
    # nose: bridge -> tip ridge, wings, base
    ns = 1 + 0.15 * p["nose_size"]
    nz0, nz1 = eyeZ - 0.002, noseTipZ
    t = np.clip((nz0 - Z) / (nz0 - nz1), 0, 1)                       # 0 at bridge top, 1 at tip
    prof = (0.004 + 0.004 * p["nose_bridge"]) * (1 - t) + (0.018 + 0.006 * p["nose_tip"]) * t ** 1.6
    prof += 0.006 * p["nose_hook"] * np.sin(t * math.pi) * (t < 1)
    nw = (0.0075 + (0.011 + 0.003 * p["nose_width"]) * t ** 1.4) * ns
    inside = (Z <= nz0) & (Z >= nz1 - 0.012)
    below = smooth(nz1 + 0.003, nz1 - 0.012 - 0.004 * p["nose_upturn"], Z)     # nose base drops to the lip
    disp += front * ns * prof * g(X, nw) * inside * (1 - below)
    for sx in (-1, 1):   # wings
        disp += front * ns * (0.006 + 0.003 * p["nostril_flare"]) * g(X - sx * (0.013 + 0.003 * p["nose_width"]) * ns, 0.006) * g(Z - (nz1 + 0.002), 0.006)
    # philtrum and mouth
    mw = 0.024 * (1 + 0.12 * p["mouth_width"])
    disp += front * 0.004 * g(X, 0.008) * smooth(mouthZ, nz1 - 0.004, Z) * (Z < nz1)            # upper-lip area forward
    lipU = (0.0045 + 0.0025 * p["lip_upper"]) * g(Z - (mouthZ + 0.004), 0.0035) * smooth(mw, mw * 0.7, np.abs(X))
    lipL = (0.0055 + 0.0025 * p["lip_lower"]) * g(Z - (mouthZ - 0.006), 0.0045) * smooth(mw * 0.95, mw * 0.6, np.abs(X))
    slit = 0.0035 * g(Z - (mouthZ + 0.0008 * p["smile"] * (np.abs(X) / mw) ** 2 * 6), 0.0011) * smooth(mw * 1.05, mw * 0.8, np.abs(X))
    corners = 0.003 * (g(np.abs(X) - mw, 0.004) * g(Z - mouthZ, 0.005))
    disp += front * (lipU + lipL - slit - corners + 0.003 * p["mouth_forward"] * g(X, 0.03) * g(Z - mouthZ, 0.015))
    # chin
    disp += front * (0.006 + 0.005 * p["chin_forward"]) * g(Z - (chinZ + 0.012), 0.012) * g(X, 0.018 * (1 + 0.25 * p["chin_width"]))
    disp -= front * 0.0025 * g(Z - (mouthZ - 0.016), 0.004) * g(X, 0.02)                      # groove under the lip
    # apply along the radial direction
    n = pts / np.maximum(np.linalg.norm(pts, axis=-1, keepdims=True), 1e-9)
    pts = pts + n * disp[..., None]
    # chin length: stretch the lower face down
    lowf = smooth(mouthZ, chinZ - 0.02, pts[..., 2]) * (pts[..., 1] > -0.02)
    pts[..., 2] -= 0.012 * p["chin_length"] * lowf
    # ---- neck tube below the head opening
    ring0 = pts[-1]                                        # last head ring
    nr = 0.052 * (1 + 0.1 * p["neck_width"])
    neck = []
    zc = ring0[:, 2].mean()
    for k in range(1, neck_rings + 1):
        t = k / neck_rings
        circ = np.stack([nr * np.sin(us), nr * 0.95 * np.cos(us) - 0.012, np.full(nu, zc - 0.015 - 0.11 * t)], -1)
        neck.append(ring0 * (1 - smooth(0, 0.45, t)) + circ * smooth(0, 0.45, t))
    grid = np.concatenate([pts, np.array(neck)], 0)        # (rows, nu, 3)
    rows = grid.shape[0]
    verts = grid.reshape(-1, 3)
    # top cap vertex
    top = np.array([[0, 0, pts[0, :, 2].mean() + 0.0015]])
    verts = np.concatenate([verts, top], 0); top_i = len(verts) - 1
    quads = []
    for r in range(rows - 1):
        for c in range(nu):
            a = r * nu + c; b = r * nu + (c + 1) % nu
            quads.append((a, b, b + nu, a + nu)[::-1])
    tris = [(top_i, (c + 1) % nu, c)[::-1] for c in range(nu)]
    uv = np.zeros((len(verts), 2))
    for r in range(rows):
        uv[r * nu:(r + 1) * nu, 0] = us / (2 * math.pi)
        uv[r * nu:(r + 1) * nu, 1] = 1 - r / (rows - 1)
    uv[top_i] = (0.5, 1.0)
    anchors = {"eye_l": (eyeX, eyeZ), "eye_r": (-eyeX, eyeZ), "eye_size": es, "eye_depth": p["eye_depth"], "mouth_z": mouthZ,
               "W": W, "D": D, "H": H, "nu": nu, "rows": rows, "nose_tip_z": noseTipZ, "brow_z": browZ}
    return verts, quads, tris, uv, anchors

def eye_center(verts_grid_fn, anchors, side):
    """where to put an eyeball: behind the socket, so its front pokes through the almond opening"""
    ex, ez = anchors["eye_l"] if side > 0 else anchors["eye_r"]
    return ex, ez
