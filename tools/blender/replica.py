"""Blender (bpy) replica builder: a real building recreated on its exact LiDAR footprint from a hand-written spec
(tools/blender/replicas/<key>/spec.json, written from reference photos) + massing.json (replica_massing.py).

Geometry: every facade of the main tier is a grid of floors x bays; window cells are recessed with reveals and a
sill, glass set back, optional mullions; wall cells stay flush. Piers stand proud of the wall, belt courses and the
cornice are profiles swept around the footprint, storefront bases get big glass with stone pilasters. Upper LiDAR
tiers become penthouses / mechanical floors. UVs are world-scale (1 unit = 1 m) so the game's tiling PBR
materials fit; material names are the contract with scripts/replicas.gd. Window glass carries UV2.x = a random
per-window id (lit windows at night).
usage: bpyenv/bin/python tools/blender/replica.py <replica dir> <out.glb>"""
import sys, os, json, math, random
import bpy, bmesh
from mathutils import Vector

DIR, OUT = sys.argv[1], sys.argv[2]
M = json.load(open(os.path.join(DIR, "massing.json")))
S = json.load(open(os.path.join(DIR, "spec.json")))
rng = random.Random(M["key"])
bm = bmesh.new()
uvl = bm.loops.layers.uv.new("UVMap")
uv2 = bm.loops.layers.uv.new("UV2")
MATS = []
def mi(name):
    if name not in MATS: MATS.append(name)
    return MATS.index(name)

def face(pts, mat, uvs=None, wid=0.0):
    """pts: list of Vector (CCW seen from outside). uvs: list of (u, v) in metres."""
    vs = [bm.verts.new(p) for p in pts]
    f = bm.faces.new(vs)
    f.material_index = mi(mat)
    for i, l in enumerate(f.loops):
        l[uvl].uv = uvs[i] if uvs else (pts[i].x + pts[i].y, pts[i].z)
        l[uv2].uv = (wid, 0.0)
    return f

def quad_on(o, t, n, a0, a1, z0, z1, d, mat, wid=0.0):
    """rectangle on a facade plane: origin o, tangent t, outward normal n; along a0..a1, height z0..z1, pushed d along n."""
    p = [o + t * a0 + n * d + Vector((0, 0, z0)), o + t * a1 + n * d + Vector((0, 0, z0)),
         o + t * a1 + n * d + Vector((0, 0, z1)), o + t * a0 + n * d + Vector((0, 0, z1))]
    face(p, mat, [(a0, z0), (a1, z0), (a1, z1), (a0, z1)], wid)

def box_on(o, t, n, a0, a1, z0, z1, d0, d1, mat):
    """a block standing proud of the facade from depth d0 to d1 (piers, sills, belt pieces)."""
    quad_on(o, t, n, a0, a1, z0, z1, d1, mat)                                  # front
    for a, s in ((a0, -1), (a1, 1)):                                          # sides
        pa = o + t * a; p = [pa + n * d0 + Vector((0, 0, z0)), pa + n * d1 + Vector((0, 0, z0)), pa + n * d1 + Vector((0, 0, z1)), pa + n * d0 + Vector((0, 0, z1))]
        if s > 0: p = [p[1], p[0], p[3], p[2]]
        face(p, mat, [(0, z0), (d1 - d0, z0), (d1 - d0, z1), (0, z1)])
    for z, s in ((z0, -1), (z1, 1)):                                          # bottom / top
        p = [o + t * a0 + n * d0, o + t * a1 + n * d0, o + t * a1 + n * d1, o + t * a0 + n * d1]
        p = [q + Vector((0, 0, z)) for q in p]
        if s > 0: p.reverse()
        face(p, mat, [(q.x, q.y) for q in p])

def window(o, t, n, a0, a1, z0, z1, depth, frame, glass, mull, wid):
    """recessed opening: reveals (wall material) + frame + glass + optional mullion/transom."""
    wall = S["materials"]["body_now"]
    for (pa, pb, za, zb) in ((a0, a0, z0, z1), (a1, a1, z0, z1)):              # side reveals
        pass
    # reveals: 4 quads from the facade plane back to the glass plane
    c = [(a0, z0), (a1, z0), (a1, z1), (a0, z1)]
    for i in range(4):
        (u0, w0), (u1, w1) = c[i], c[(i + 1) % 4]
        p0 = o + t * u0 + Vector((0, 0, w0)); p1 = o + t * u1 + Vector((0, 0, w1))
        face([p0, p1, p1 - n * depth, p0 - n * depth], wall, [(0, 0), (1, 0), (1, depth), (0, depth)])
    fw = 0.06
    quad_on(o, t, n, a0 + fw, a1 - fw, z0 + fw, z1 - fw, -depth - 0.01, glass, wid)
    # frame ring (as 4 thin quads just in front of the glass)
    for (b0, b1, y0, y1) in ((a0, a1, z0, z0 + fw), (a0, a1, z1 - fw, z1), (a0, a0 + fw, z0, z1), (a1 - fw, a1, z0, z1)):
        quad_on(o, t, n, b0, b1, y0, y1, -depth + 0.005, frame)
    if mull in ("cross", "vertical"):
        m = (a0 + a1) / 2
        quad_on(o, t, n, m - 0.03, m + 0.03, z0, z1, -depth + 0.012, frame)
    if mull in ("cross", "transom"):
        tz = z0 + (z1 - z0) * 0.62
        quad_on(o, t, n, a0, a1, tz - 0.03, tz + 0.03, -depth + 0.012, frame)
    if S.get("arched") or S.get("_arch_now"):
        # semicircular head: glass fan set back like the pane, a stone/brick voussoir ring on the wall face
        r = (a1 - a0) / 2; cx = (a0 + a1) / 2; seg = 10
        ring = [(cx + math.cos(math.pi * k / seg) * r, z1 + math.sin(math.pi * k / seg) * r) for k in range(seg + 1)]
        for k in range(seg):
            (u0, w0), (u1, w1) = ring[k], ring[k + 1]
            P0 = o + t * cx + n * (-depth - 0.01) + Vector((0, 0, z1)); P1 = o + t * u0 + n * (-depth - 0.01) + Vector((0, 0, w0)); P2 = o + t * u1 + n * (-depth - 0.01) + Vector((0, 0, w1))
            face([P0, P1, P2], glass, [(cx, z1), (u0, w0), (u1, w1)], wid)
            # voussoirs: ring band 0.25 m wide just proud of the wall
            Q0 = o + t * u0 + n * 0.03 + Vector((0, 0, w0)); Q1 = o + t * u1 + n * 0.03 + Vector((0, 0, w1))
            d0 = Vector((u0 - cx, 0, w0 - z1)).normalized() * 0.28; d1 = Vector((u1 - cx, 0, w1 - z1)).normalized() * 0.28
            face([Q0, Q0 + t * d0.x + Vector((0, 0, d0.z)), Q1 + t * d1.x + Vector((0, 0, d1.z)), Q1][::-1], S["materials"].get("arch", S["materials"]["trim"]))
    # sill
    box_on(o, t, n, a0 - 0.06, a1 + 0.06, z0 - 0.09, z0, 0.0, 0.07, S["materials"].get("sill", S["materials"]["trim"]))

# --------------------------------------------------------------------------- facades of one tier
def floors_for(z0, z1):
    fl = []; z = z0
    spec = S["floors"]
    total = sum(f["n"] * f["h"] for f in spec)
    k = (z1 - z0 - S.get("cornice", {}).get("h", 0) * 0.0) / total          # fit the storey heights to the real height
    for f in spec:
        for i in range(f["n"]):
            fl.append((z, z + f["h"] * k, f.get("kind", "typical"), f)); z += f["h"] * k
    return fl

def curtain(o, t, n, L, z0, z1, fl):
    """glass curtain wall: vertical mullions proud of the glass, a spandrel band at every floor slab."""
    mats = S["materials"]; C = S.get("curtain", {})
    pitch = C.get("mullion", 1.5); nm = max(1, int(round(L / pitch))); pw = L / nm
    g = mats.get("curtain_glass", "glass_curtain"); fr = mats.get("mullion", "metal_dark")
    spand = C.get("spandrel", 0.9)
    for (fz0, fz1, kind, f) in fl:
        for i in range(nm):
            a0 = i * pw; a1 = a0 + pw
            quad_on(o, t, n, a0, a1, fz0, fz0 + spand, -0.02, mats.get("spandrel", g), rng.random() * 0.0)
            quad_on(o, t, n, a0, a1, fz0 + spand, fz1, -0.04, g, rng.random())
        quad_on(o, t, n, 0, L, fz0 + spand - 0.05, fz0 + spand, 0.03, fr)       # transom rail at the sill line
    for i in range(nm + 1):
        a = i * pw
        box_on(o, t, n, a - C.get("mw", 0.06), a + C.get("mw", 0.06), z0, z1, -0.04, C.get("fin", 0.12), fr)

def facade(a, b, z0, z1, fl):
    o = Vector((a[0], a[1], 0.0)); e = Vector((b[0] - a[0], b[1] - a[1], 0.0)); L = e.length
    if L < 0.5: return
    t = e / L; n = Vector((t.y, -t.x, 0.0))                       # polygon CCW -> outward normal on the right
    mats = S["materials"]
    style = S.get("style", "punched")
    if L < S.get("solid_below", 0.0): style = "solid"
    if style == "solid":
        quad_on(o, t, n, 0, L, z0, z1, 0, mats.get("solid", mats["body"])); return
    if style == "curtain":
        if fl and fl[0][2] == "lobby":
            f0 = fl[0]
            quad_on(o, t, n, 0, L, f0[0], f0[1], -0.6, mats.get("shop_glass", "glass_shop"), rng.random())
            for i in range(int(L / 6) + 1):
                box_on(o, t, n, i * L / max(1, int(L / 6)) - 0.3, i * L / max(1, int(L / 6)) + 0.3, f0[0], f0[1], -0.6, 0.0, mats.get("base", mats["body"]))
            fl = fl[1:]
        curtain(o, t, n, L, fl[0][0], z1, fl); return
    W = S["window"]; bay = S.get("bay", 3.0)
    corner = S.get("corner_pier", 1.2)
    usable = L - 2 * corner
    nb = max(0, int(round(usable / bay))) if usable > bay * 0.7 else 0
    if L < S.get("min_face", 4.0): nb = 0
    bw = usable / nb if nb else 0
    for (fz0, fz1, kind, f) in fl:
        fh = fz1 - fz0
        body = mats.get(f.get("mat", ""), None) or (mats["base"] if kind == "storefront" else mats["body"])
        S["materials"]["body_now"] = body
        if kind == "storefront" and nb:
            # big shop glass between stone pilasters
            pil = S.get("pilaster", 0.7)
            quad_on(o, t, n, 0, corner, fz0, fz1, 0, body); quad_on(o, t, n, L - corner, L, fz0, fz1, 0, body)
            for i in range(nb):
                c0 = corner + i * bw; c1 = c0 + bw
                quad_on(o, t, n, c0, c0 + pil / 2, fz0, fz1, 0, body); quad_on(o, t, n, c1 - pil / 2, c1, fz0, fz1, 0, body)
                box_on(o, t, n, c0 - pil / 2 + (0 if i else pil / 2), c0 + pil / 2, fz0, fz1, 0, 0.12, body) if i else None
                gz1 = fz0 + fh * f.get("glass_h", 0.82)
                quad_on(o, t, n, c0 + pil / 2, c1 - pil / 2, gz1, fz1, 0, body)
                quad_on(o, t, n, c0 + pil / 2, c1 - pil / 2, fz0, fz0 + 0.45, 0, body)
                window(o, t, n, c0 + pil / 2, c1 - pil / 2, fz0 + 0.45, gz1, 0.25, mats["frame"], mats.get("shop_glass", mats["glass"]), "vertical", rng.random())
            continue
        if not nb or kind == "blank":
            quad_on(o, t, n, 0, L, fz0, fz1, 0, body); continue
        quad_on(o, t, n, 0, corner, fz0, fz1, 0, body); quad_on(o, t, n, L - corner, L, fz0, fz1, 0, body)
        ww = f.get("ww", W["w"]); wh = f.get("wh", W["h"]); grp = f.get("group", W.get("group", 1))
        S["_arch_now"] = f.get("arched", False)
        wz0 = fz0 + fh * (1 - wh) * W.get("sill_frac", 0.45); wz1 = wz0 + fh * wh
        for i in range(nb):
            c0 = corner + i * bw; c1 = c0 + bw
            # window group centred in the bay; wall around it
            g_here = W.get("end_group", grp) if (i == 0 or i == nb - 1) else grp
            gw = bw * ww * (g_here / grp) ** 0.85; g0 = (c0 + c1) / 2 - gw / 2; g1 = g0 + gw
            quad_on(o, t, n, c0, g0, fz0, fz1, 0, body); quad_on(o, t, n, g1, c1, fz0, fz1, 0, body)
            quad_on(o, t, n, g0, g1, fz0, wz0, 0, body); quad_on(o, t, n, g0, g1, wz1, fz1, 0, body)
            gap = W.get("group_gap", 0.25)
            each = (gw - gap * (g_here - 1)) / g_here
            for k in range(g_here):
                w0 = g0 + k * (each + gap); w1 = w0 + each
                if k: quad_on(o, t, n, w0 - gap, w0, wz0, wz1, 0, body)
                window(o, t, n, w0, w1, wz0, wz1, W.get("depth", 0.18), mats["frame"], mats["glass"], f.get("mull", W.get("mull", "none")), rng.random())
    # piers: proud vertical strips between bays over the typical floors
    P = S.get("piers")
    if P and nb:
        pz0 = min(f[0] for f in fl if f[2] != "storefront"); pz1 = max(f[1] for f in fl)
        for i in range(0, nb + 1, P.get("every", 1)):
            c = corner + i * bw
            if i == 0: c0, c1 = 0.0, corner
            elif i == nb: c0, c1 = L - corner, L
            else: c0, c1 = c - P["w"] / 2, c + P["w"] / 2
            box_on(o, t, n, c0, c1, pz0, pz1, 0.0, P["d"], mats.get("pier", mats["body"]))

# --------------------------------------------------------------------------- profiles swept around the footprint
def offset_poly(poly, d):
    """outward offset of a CCW polygon by d (miter, clamped)."""
    out = []; N = len(poly)
    for i in range(N):
        p0 = Vector(poly[i - 1]); p1 = Vector(poly[i]); p2 = Vector(poly[(i + 1) % N])
        e0 = (p1 - p0).normalized(); e1 = (p2 - p1).normalized()
        n0 = Vector((e0.y, -e0.x)); n1 = Vector((e1.y, -e1.x))
        m = (n0 + n1); m = m.normalized() if m.length > 1e-6 else n0
        k = d / max(0.35, m.dot(n1))
        out.append(p1 + m * k)
    return out

def sweep(poly, prof, z, mat):
    """prof: [(out, dz)] from bottom to top; rings joined into a band (cornice, belt course, plinth)."""
    rings = [[Vector((p[0], p[1], z + dz)) for p in offset_poly(poly, d)] for d, dz in prof]
    N = len(poly)
    for r0, r1 in zip(rings, rings[1:]):
        for i in range(N):
            j = (i + 1) % N
            a, b, c, d = r0[i], r0[j], r1[j], r1[i]
            if (b - a).length < 1e-4: continue
            face([a, b, c, d], mat, [(0, a.z), ((b - a).length, b.z), ((c - d).length, c.z), (0, d.z)])
    # cap the top ring inward (flat top of the moulding)
    top = rings[-1]; base = [Vector((p[0], p[1], top[0].z)) for p in poly]
    for i in range(N):
        j = (i + 1) % N
        face([top[i], top[j], base[j], base[i]], mat)

PROFILES = {
    "classical": [(0.0, 0.0), (0.12, 0.0), (0.12, 0.25), (0.35, 0.45), (0.35, 0.6), (0.55, 0.62), (0.55, 0.8), (1.0, 1.05), (1.15, 1.15), (1.15, 1.35), (0.0, 1.35)],
    "belt": [(0.0, 0.0), (0.12, 0.05), (0.18, 0.18), (0.18, 0.32), (0.0, 0.42)],
    "plinth": [(0.0, 0.0), (0.1, 0.0), (0.1, 0.9), (0.04, 1.0), (0.0, 1.0)],
    "coping": [(0.0, 0.0), (0.06, 0.0), (0.06, 0.12), (0.0, 0.12)],
    "deco": [(0.0, 0.0), (0.25, 0.0), (0.25, 0.4), (0.12, 0.45), (0.12, 1.2), (0.3, 1.25), (0.3, 1.45), (0.0, 1.45)],
}
def profile(name, scale_h, scale_out):
    return [(o * scale_out, z * scale_h) for o, z in PROFILES[name]]

def ccw(poly):
    a = sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1] for i in range(len(poly)))
    return poly if a > 0 else list(reversed(poly))

def roof(poly, z, mat):
    bmesh.ops.contextual_create  # (keep bmesh imported names used)
    vs = [bm.verts.new((p[0], p[1], z)) for p in poly]
    f = bm.faces.new(vs); f.material_index = mi(mat)
    for l in f.loops: l[uvl].uv = (l.vert.co.x, l.vert.co.y); l[uv2].uv = (0, 0)

def simplify(poly, tol=0.35):
    """drop near-collinear / tiny-edge vertices (LiDAR outlines are noisy)."""
    pts = [Vector(p) for p in poly]
    changed = True
    while changed and len(pts) > 3:
        changed = False
        for i in range(len(pts)):
            a, b, c = pts[i - 1], pts[i], pts[(i + 1) % len(pts)]
            area = abs((b - a).cross(c - a)) if hasattr(b - a, "cross") else abs((b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x))
            if area / max((c - a).length, 1e-6) < tol or (b - a).length < 0.6:
                pts.pop(i); changed = True; break
    return [(p.x, p.y) for p in pts]

# --------------------------------------------------------------------------- build
tiers = M["tiers"]
BASE_SPEC = dict(S)
def build_tier(ti, tr):
    global S
    S = dict(BASE_SPEC); S.update((BASE_SPEC.get("tiers") or [{}] * 99)[ti] if ti < len(BASE_SPEC.get("tiers") or []) else {})
    S["materials"] = dict(BASE_SPEC["materials"]); S["materials"].update(S.get("mat_over", {}))
    mz0, mz1 = tr["z0"], tr["z1"] - S.get("cornice", {}).get("h", 0.0) - S.get("parapet", 0.0)
    fl = floors_for(mz0, mz1)
    for poly in tr["polys"]:
        poly = ccw(simplify(poly, S.get("simplify", 0.35)))
        if len(poly) < 3: continue
        for i in range(len(poly)):
            facade(poly[i], poly[(i + 1) % len(poly)], mz0, mz1, fl)
        mats = S["materials"]
        if S.get("plinth"): sweep(poly, profile("plinth", S["plinth"], 1.0), mz0, mats["base"])
        for b in S.get("belts", []):
            z = fl[b["above_floor"] - 1][1] if b.get("above_floor") else mz0 + b["z"]
            sweep(poly, profile(b.get("profile", "belt"), b.get("h", 0.6) / 0.42, b.get("out", 0.25) / 0.18), z - 0.05, mats["trim"])
        top = mz1
        if S.get("cornice"):
            c = S["cornice"]
            sweep(poly, profile(c.get("profile", "classical"), c["h"] / 1.35, c["out"] / 1.15), top, mats.get("cornice", mats["trim"]))
            top += c["h"]
        if S.get("parapet"):
            p2 = [(p.x, p.y) for p in offset_poly(poly, -0.05)]
            for i in range(len(p2)):
                a_, b_ = Vector((*p2[i], top)), Vector((*p2[(i + 1) % len(p2)], top))
                face([a_, b_, b_ + Vector((0, 0, S["parapet"])), a_ + Vector((0, 0, S["parapet"]))], mats.get("parapet", mats["body"]), [(0, top), ((b_ - a_).length, top), ((b_ - a_).length, top + S["parapet"]), (0, top + S["parapet"])])
            sweep(p2, profile("coping", 1.0, 1.0), top + S["parapet"], mats["trim"])
        roof(poly, top + 0.02, mats.get("roof", "roof_flat"))

# --------------------------------------------------------------------------- parts mode (churches, houses, halls)
def rect_poly(r):
    cx, cy, w, d = r[:4]; a = math.radians(r[4] if len(r) > 4 else 0.0)
    ca, sa = math.cos(a), math.sin(a)
    return [(cx + ca * x - sa * y, cy + sa * x + ca * y) for x, y in ((-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2))]

def tri(a, b, c, mat):
    face([a, b, c], mat, [(a.x + a.y, a.z), (b.x + b.y, b.z), (c.x + c.y, c.z)])

def pitched(poly, z, rf, wallmat):
    """gable / hip / pyramid / spire roof over a rectangle (poly from rect_poly, CCW). Gable ridge runs along the
    rectangle's long axis unless rf['ridge'] == 'short'. Gable end triangles are filled with the wall material."""
    kind = rf.get("type", "gable"); mat = rf.get("mat", "slate"); ov = rf.get("overhang", 0.35)
    P = [Vector((p[0], p[1], z)) for p in poly]
    e0 = (P[1] - P[0]); e1 = (P[2] - P[1])
    if (e0.length < e1.length) != (rf.get("ridge") == "short"): P = P[1:] + P[:1]; e0, e1 = e1, (P[2] - P[1])
    # now P0->P1 is along the ridge; half span across = |e1|/2
    span = (P[2] - P[1]).length / 2
    h = rf.get("h") or span * math.tan(math.radians(rf.get("pitch", 40)))
    u = (P[1] - P[0]).normalized(); v = (P[2] - P[1]).normalized()
    Q = [P[0] - u * ov - v * ov, P[1] + u * ov - v * ov, P[2] + u * ov + v * ov, P[3] - u * ov + v * ov]   # eave corners
    drop = Vector((0, 0, -ov * h / max(span, 0.1)))
    Q = [q + drop for q in Q]
    c = sum(P, Vector()) / 4 + Vector((0, 0, h))
    if kind in ("pyramid", "spire"):
        if kind == "spire": c.z = z + rf.get("h", span * 4)
        for i in range(4): tri(Q[i], Q[(i + 1) % 4], c, mat)
        return
    r0 = (P[0] + P[3]) / 2 + Vector((0, 0, h)); r1 = (P[1] + P[2]) / 2 + Vector((0, 0, h))
    if kind == "hip":
        inset = span * 0.9
        r0 = r0 + u * inset; r1 = r1 - u * inset
        face([Q[0], Q[1], r1, r0], mat); face([Q[2], Q[3], r0, r1], mat)
        tri(Q[1], Q[2], r1, mat); tri(Q[3], Q[0], r0, mat)
        return
    e0r = r0 - u * ov; e1r = r1 + u * ov
    face([Q[0], Q[1], e1r, e0r], mat); face([Q[2], Q[3], e0r, e1r], mat)
    # gable end walls
    tri(P[3], P[0], r0, wallmat); tri(P[1], P[2], r1, wallmat)
    return (r0, r1, P)

def rose(center, normal, r, mat_glass, mat_ring):
    """round window on a gable: glass disc with a tracery ring."""
    n = normal.normalized(); t = Vector((n.y, -n.x, 0)).normalized(); up = Vector((0, 0, 1))
    seg = 20
    ring = [center + n * 0.02 + (t * math.cos(2 * math.pi * k / seg) + up * math.sin(2 * math.pi * k / seg)) * r for k in range(seg)]
    for k in range(seg):
        face([center + n * 0.01, ring[k], ring[(k + 1) % seg]], mat_glass, None, rng.random())
        a, b = ring[k], ring[(k + 1) % seg]
        a2 = center + n * 0.06 + (a - center - n * 0.02) * 1.18; b2 = center + n * 0.06 + (b - center - n * 0.02) * 1.18
        face([a, b, b2, a2][::-1], mat_ring)

def build_part(pt):
    global S
    S = dict(BASE_SPEC); S.update(pt)
    S["materials"] = dict(BASE_SPEC["materials"]); S["materials"].update(pt.get("mat_over", {}))
    poly = rect_poly(pt["rect"]) if "rect" in pt else pt["poly"]
    poly = ccw(poly)
    z0, z1 = pt.get("z0", 0.0), pt["z1"]
    fl = floors_for(z0, z1)
    for i in range(len(poly)):
        facade(poly[i], poly[(i + 1) % len(poly)], z0, z1, fl)
    mats = S["materials"]
    if S.get("plinth"): sweep(poly, profile("plinth", S["plinth"], 1.0), z0, mats["base"])
    for b in S.get("belts", []):
        z = fl[b["above_floor"] - 1][1] if b.get("above_floor") else z0 + b["z"]
        sweep(poly, profile(b.get("profile", "belt"), b.get("h", 0.6) / 0.42, b.get("out", 0.25) / 0.18), z - 0.05, mats["trim"])
    top = z1
    if S.get("cornice"):
        c = S["cornice"]; sweep(poly, profile(c.get("profile", "classical"), c["h"] / 1.35, c["out"] / 1.15), top, mats.get("cornice", mats["trim"])); top += c["h"]
    if S.get("parapet"):
        for i in range(len(poly)):
            a_, b_ = Vector((*poly[i], top)), Vector((*poly[(i + 1) % len(poly)], top))
            face([a_, b_, b_ + Vector((0, 0, S["parapet"])), a_ + Vector((0, 0, S["parapet"]))], mats.get("parapet", mats["body"]))
        if S.get("battlement"):
            for i in range(len(poly)):
                A, Bv = Vector(poly[i]), Vector(poly[(i + 1) % len(poly)]); L = (Bv - A).length; nmer = max(1, int(L / 1.2))
                tt = (Bv - A) / L; nn = Vector((tt.y, -tt.x))
                for k in range(0, nmer, 2):
                    a0 = k * L / nmer; a1 = (k + 1) * L / nmer
                    oo = Vector((A.x, A.y, 0)); box_on(oo, Vector((tt.x, tt.y, 0)), Vector((nn.x, nn.y, 0)), a0, a1, top + S["parapet"], top + S["parapet"] + 0.7, -0.4, 0.05, mats.get("parapet", mats["body"]))
        sweep(poly, profile("coping", 1.0, 1.0), top + S["parapet"], mats["trim"])
    rf = pt.get("roof", {"type": "flat"})
    if rf.get("type", "flat") == "flat":
        roof(poly, top + 0.02, mats.get("roof", "roof_flat"))
    else:
        res = pitched(poly, top, rf, mats["body"])
        if res and pt.get("rose"):
            r0, r1, P = res
            end = r1 if pt["rose"].get("end", 1) == 1 else r0
            base_mid = (P[1] + P[2]) / 2 if end is r1 else (P[0] + P[3]) / 2
            nrm = (base_mid - (P[0] + P[1] + P[2] + P[3]) / 4); nrm.z = 0
            ctr = base_mid + Vector((0, 0, (end.z - base_mid.z) * 0.38)) + nrm.normalized() * 0.03
            rose(ctr, nrm, pt["rose"].get("r", 2.0), mats.get("glass", "glass_window"), mats.get("arch", mats["trim"]))
    for tu in pt.get("turrets", []):        # little corner pinnacles on towers
        for q in poly:
            c = Vector(q) - (Vector(q) - sum((Vector(p) for p in poly), Vector((0.0, 0.0))) / len(poly)).normalized() * tu["r"]
            sq = rect_poly([c.x, c.y, tu["r"] * 2, tu["r"] * 2, pt["rect"][4] if "rect" in pt and len(pt["rect"]) > 4 else 0])
            for i in range(4):
                A, Bv = Vector((*sq[i], top)), Vector((*sq[(i + 1) % 4], top))
                face([A, Bv, Bv + Vector((0, 0, tu["h"])), A + Vector((0, 0, tu["h"]))], mats["body"])
            pitched(sq, top + tu["h"], {"type": "pyramid", "h": tu.get("cap", 2.0), "mat": tu.get("mat", "slate"), "overhang": 0.05}, mats["body"])

if BASE_SPEC.get("parts"):
    for pt in BASE_SPEC["parts"]: build_part(pt)
    tiers = []
else:
    build_tier(0, tiers[0])
# upper LiDAR tiers: penthouse / mechanical volumes
for ti, tr in enumerate(tiers[1:], 1):
    if BASE_SPEC.get("tiers") and ti < len(BASE_SPEC["tiers"]) and BASE_SPEC["tiers"][ti]:
        build_tier(ti, tr); continue
    S = dict(BASE_SPEC)
    for poly in tr["polys"]:
        poly = ccw(simplify(poly, 0.5))
        if len(poly) < 3: continue
        z0, z1 = tr["z0"], tr["z1"]
        for i in range(len(poly)):
            a, b = poly[i], poly[(i + 1) % len(poly)]
            A, B = Vector((a[0], a[1], z0)), Vector((b[0], b[1], z0))
            L = (B - A).length
            face([A, B, B + Vector((0, 0, z1 - z0)), A + Vector((0, 0, z1 - z0))], S["materials"].get("penthouse", S["materials"]["body"]), [(0, z0), (L, z0), (L, z1), (0, z1)])
        roof(poly, z1, S["materials"].get("roof", "roof"))

# --------------------------------------------------------------------------- object + export
bpy.ops.wm.read_factory_settings(use_empty=True)
me = bpy.data.meshes.new("bld_" + M["key"])
bm.to_mesh(me); bm.free()
for name in MATS:
    m = bpy.data.materials.new(name); m.use_nodes = True
    me.materials.append(m)
o = bpy.data.objects.new("bld_" + M["key"], me); bpy.context.collection.objects.link(o)
# Blender: x east, y north, z up. The game: x east, y up, z = -north -> glTF export (+Y up) maps exactly.
bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", export_normals=True)
print("built %s: %d tris, %d materials" % (M["key"], sum(len(p.vertices) - 2 for p in me.polygons), len(MATS)))
