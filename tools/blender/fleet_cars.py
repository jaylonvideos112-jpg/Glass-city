"""Blender (bpy) per-model vehicles for GLASS CITY's Toledo fleet (source_data/toledo_fleet.json).

Unlike tools/blender/cars.py (one generic body per type), every model here gets its own build function, with its
own proportions, grille, headlights, taillights, bumpers and trim, so that a 2007-13 full-size pickup reads as that
truck at a glance. All names and badges are parody: no real logos (the badge is an original oval plate).

Construction: bevelled solids (bmesh hulls and boxes) for the panels, wheel arches cut with booleans plus a raised
painted flare, glass as thin panels just proud of the greenhouse, lights and grille as separate parts.
Materials follow the contract with scripts/traffic.gd: paint, glass, chrome, trim, head, tail.
Axes: Blender +Y = front (= Godot -Z), +Z up, origin on the ground under the body centre. Axles at +-0.32 L
(where traffic.gd puts its wheels). Wheels are added only for the preview render, not exported.

usage: bpyenv/bin/python tools/blender/fleet_cars.py OUTDIR MODEL [preview=PNG] [paint=#rrggbb]
models: corvane_stockman (Corvane Stockman 1500 crew cab, 2007-13 style; fleet rank 1)
The Corvane badge is an original flat hexagon plate."""
import sys, math, bpy, bmesh
from mathutils import Vector

ARGS = [a for a in sys.argv[sys.argv.index("--") + 1:]] if "--" in sys.argv else sys.argv[1:]
OUT, MODEL = ARGS[0], ARGS[1]
OPT = dict(a.split("=", 1) for a in ARGS[2:] if "=" in a)


def hexc(s):
    s = s.lstrip("#"); c = [int(s[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)


def mat(name, col, metal=0.0, rough=0.5, emit=None, es=1.0):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*col, 1); b.inputs["Metallic"].default_value = metal
    b.inputs["Roughness"].default_value = rough
    if emit:
        b.inputs["Emission Color"].default_value = (*emit, 1); b.inputs["Emission Strength"].default_value = es
    return m


M = {}
PARTS = []          # exported
PREVIEW_ONLY = []   # wheels, ground
REF = [0.0, 0.0, 1.2]   # cab centre, set by each model (panels push away from it)


def link(me, name, kind):
    o = bpy.data.objects.new(name, me); bpy.context.collection.objects.link(o)
    if kind: o.data.materials.append(M[kind])
    return o


def bevel(o, w, seg=3, angle=50):
    bpy.context.view_layer.objects.active = o
    b = o.modifiers.new("b", "BEVEL"); b.width = w; b.segments = seg; b.limit_method = "ANGLE"
    b.angle_limit = math.radians(angle); b.harden_normals = False
    bpy.ops.object.modifier_apply(modifier="b")


def hull(name, pts, kind, bev=0.0, seg=3, keep=True):
    """Convex solid through the given points."""
    bm = bmesh.new()
    for p in pts: bm.verts.new(p)
    bmesh.ops.convex_hull(bm, input=bm.verts)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    # drop the loose verts the hull leaves inside
    for v in [v for v in bm.verts if not v.link_faces]: bm.verts.remove(v)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    o = link(me, name, kind)
    if bev > 0: bevel(o, bev, seg)
    if keep: PARTS.append(o)
    return o


def box(name, x0, x1, y0, y1, z0, z1, kind, bev=0.0, seg=3, keep=True):
    return hull(name, [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)], kind, bev, seg, keep)


def mirror_x(pts): return [(-x, y, z) for x, y, z in pts]


def cyl(name, r, depth, loc, rot, kind, verts=20, bev=0.0, keep=True):
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=r, depth=depth, location=loc, rotation=rot)
    o = bpy.context.active_object; o.name = name
    o.data.materials.append(M[kind])
    if bev > 0: bevel(o, bev, 2, 40)
    if keep: PARTS.append(o)
    return o


def cut(o, cutter):
    bpy.context.view_layer.objects.active = o
    m = o.modifiers.new("cut", "BOOLEAN"); m.object = cutter; m.operation = "DIFFERENCE"; m.solver = "EXACT"
    bpy.ops.object.modifier_apply(modifier="cut")


def arch_cutters(axles, r, zc, W):
    cs = []
    for y in axles:
        for sx in (-1, 1):
            bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=r, depth=0.62, location=(sx * W * 0.5, y, zc),
                                                rotation=(0, math.pi / 2, 0))
            cs.append(bpy.context.active_object)
    return cs


def liner_faces(o, axles, r, zc, W):
    """Faces left by the arch cylinders (the inside of the wheel well) become dark trim."""
    if "trim" not in [m.name for m in o.data.materials]: o.data.materials.append(M["trim"])
    ti = [m.name for m in o.data.materials].index("trim")
    for f in o.data.polygons:
        c = f.center
        for y in axles:
            d = math.hypot(c.y - y, c.z - zc)
            if abs(d - r) < 0.012 and abs(c.x) < W * 0.5 + 0.01:
                f.material_index = ti


def arch_flare(name, y, zc, r_in, r_out, x_in, x_out, a0=-12, a1=192, steps=40, square=0.0):
    """Raised painted lip around a wheel arch, seen from the side: a band from r_in to r_out, standing out from
    x_in to x_out. square>0 flattens the top of the arc toward the boxy flares of the era's trucks."""
    bm = bmesh.new(); rings = []
    for i in range(steps + 1):
        a = math.radians(a0 + (a1 - a0) * i / steps)
        ca, sa = math.cos(a), math.sin(a)
        def P(rr, xx):
            dy, dz = rr * ca, rr * sa
            if square > 0 and dz > 0:   # pull the crown flatter and the shoulders out
                dz = dz * (1 - square * 0.15) + square * 0.15 * rr * (1 if dz > rr * 0.6 else dz / (rr * 0.6))
            return bm.verts.new((xx, y + dy, zc + dz))
        rings.append([P(r_in, x_in), P(r_out, x_in), P(r_out, x_out * 0.6 + x_in * 0.4), P(r_in + 0.012, x_out)])
    for a, b in zip(rings, rings[1:]):
        for i in range(4):
            j = (i + 1) % 4
            bm.faces.new((a[i], a[j], b[j], b[i]))
    bm.faces.new(rings[0]); bm.faces.new(list(reversed(rings[-1])))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    o = link(me, name, "paint"); PARTS.append(o)
    return o


def panel(name, quad, kind, off=0.004, keep=True):
    """A thin flat plate on the quad (4 points, outward winding), pushed `off` along its normal."""
    a, b, c, d = [Vector(p) for p in quad]
    n = (b - a).cross(d - a).normalized()
    ctr = (a + b + c + d) / 4
    if n.dot(ctr - Vector(REF)) < 0: n = -n          # always push away from the cab's centre
    pts = [p + n * off for p in (a, b, c, d)] + [p + n * (off - 0.006) for p in (a, b, c, d)]
    return hull(name, [tuple(p) for p in pts], kind, 0.0, keep=keep)


def lerp(a, b, t): return a + (b - a) * t


# ------------------------------------------------------------------------------------------------------------------
# Shared toolkit for lofted (curved) bodies: tools/blender/cars.py does the body; these put model-specific lamps,
# grilles and trim on it as patches that follow the curved surface.
sys.path.insert(0, __import__("os").path.dirname(__file__))
import cars as CB
from mathutils.bvhtree import BVHTree
import numpy as np

BV = {"bvh": None}


def rrect(u0, v0, u1, v1, r, seg=4):
    """Rounded rectangle outline (counter-clockwise) in the patch's (u, v) plane."""
    r = min(r, abs(u1 - u0) / 2 - 1e-4, abs(v1 - v0) / 2 - 1e-4)
    pts = []
    for cx, cy, a0 in ((u1 - r, v0 + r, -90), (u1 - r, v1 - r, 0), (u0 + r, v1 - r, 90), (u0 + r, v0 + r, 180)):
        for i in range(seg + 1):
            a = math.radians(a0 + 90 * i / seg)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def poly_round(pts, r=0.02, seg=3):
    """Round every corner of a polygon outline by r."""
    out = []
    n = len(pts)
    for i in range(n):
        p0, p1, p2 = Vector((*pts[i - 1], 0)), Vector((*pts[i], 0)), Vector((*pts[(i + 1) % n], 0))
        a, b = (p0 - p1), (p2 - p1)
        rr = min(r, a.length * 0.45, b.length * 0.45)
        if rr < 1e-4:
            out.append(pts[i]); continue
        s0, s1 = p1 + a.normalized() * rr, p1 + b.normalized() * rr
        for k in range(seg + 1):
            t = k / seg
            q = (s0 * (1 - t) ** 2 + p1 * 2 * t * (1 - t) + s1 * t * t)
            out.append((q.x, q.y))
    return out


def conform(name, poly, side, kind, off=0.006, depth=0.012, grid=0.025, keep=True):
    """A plate shaped like `poly` (outline in the view plane), projected onto the body along a view axis and
    raised `off` above it, with short walls sunk `depth` into the body. side: 'front', 'rear', 'left', 'right'.
    front/rear: (u, v) = (x, z); left/right: (u, v) = (y, z)."""
    bvh = BV["bvh"]
    if side == "front": org = lambda u, v: (Vector((u, 50, v)), Vector((0, -1, 0)))
    elif side == "rear": org = lambda u, v: (Vector((u, -50, v)), Vector((0, 1, 0)))
    elif side == "right": org = lambda u, v: (Vector((50, u, v)), Vector((-1, 0, 0)))
    else: org = lambda u, v: (Vector((-50, u, v)), Vector((1, 0, 0)))
    bm = bmesh.new()
    vs = [bm.verts.new((u, v, 0)) for u, v in poly]
    try:
        bm.faces.new(vs)
    except ValueError:
        bm.free(); return None
    us = [u for u, v in poly]; ws = [v for u, v in poly]
    for k in np.arange(min(us) + grid, max(us), grid):
        g = bm.verts[:] + bm.edges[:] + bm.faces[:]
        bmesh.ops.bisect_plane(bm, geom=g, plane_co=(k, 0, 0), plane_no=(1, 0, 0))
    for k in np.arange(min(ws) + grid, max(ws), grid):
        g = bm.verts[:] + bm.edges[:] + bm.faces[:]
        bmesh.ops.bisect_plane(bm, geom=g, plane_co=(0, k, 0), plane_no=(0, 1, 0))
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    hitp, hitn, bad = {}, {}, set()
    for v in bm.verts:
        o, d = org(v.co.x, v.co.y)
        h = bvh.ray_cast(o, d)
        if h[0] is None: bad.add(v); continue
        n = h[1] if h[1].dot(d) < 0 else -h[1]
        hitp[v] = h[0]; hitn[v] = n
    if bad:
        bmesh.ops.delete(bm, geom=list(bad), context="VERTS")
    if not bm.faces:
        bm.free(); return None
    for v in bm.verts:
        v.co = hitp[v] + hitn[v] * off
    bnd = [e for e in bm.edges if e.is_boundary]
    ret = bmesh.ops.extrude_edge_only(bm, edges=bnd)
    new = [g for g in ret["geom"] if isinstance(g, bmesh.types.BMVert)]
    # each new vert sits on an old boundary vert: push it into the body
    old_by_pos = {}
    for v in bm.verts:
        if v in hitp: old_by_pos[tuple(round(c, 6) for c in v.co)] = v
    for v in new:
        q = old_by_pos.get(tuple(round(c, 6) for c in v.co))
        if q is not None: v.co = hitp[q] - hitn[q] * depth
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    o = link(me, name, kind)
    if keep: PARTS.append(o)
    return o


def both(fn, poly, *a, **k):
    """Run a conform patch for a right-side outline and its mirror on the left (front/rear views)."""
    fn(poly, *a, **k)
    fn([(-u, v) for u, v in reversed(poly)], *a, **k)


def lofted(name, p):
    """Body from cars.py's lofted builder with this model's profile; returns the object, glass etc. classified."""
    o = CB.build_body(name, p)
    CB.classify(o, p, M)
    bpy.context.view_layer.objects.active = o
    dm = o.modifiers.new("dec", "DECIMATE"); dm.decimate_type = "DISSOLVE"; dm.angle_limit = math.radians(0.6)
    dm.delimit = {"MATERIAL", "SHARP"}
    bpy.ops.object.modifier_apply(modifier="dec")
    tr = o.modifiers.new("tri", "TRIANGULATE"); bpy.ops.object.modifier_apply(modifier="tri")
    # face-classified glass has stair-stepped edges: paint it over and lay clean glass patches on top instead
    gi = [m.name for m in o.data.materials].index("glass"); pi = [m.name for m in o.data.materials].index("paint")
    for f in o.data.polygons:
        if f.material_index == gi: f.material_index = pi
    PARTS.insert(0, o)
    BV["bvh"] = BVHTree.FromObject(o, bpy.context.evaluated_depsgraph_get())
    return o



def roof_z(p, y):
    L, W, H = p["size"]
    return H * CB.interp(p["top"], y / L)


def glasshouse(p, pillars, inset=0.065, belt_gap=0.035, ws=(0.06, 0.05), rw=(0.06, 0.05), ws_w=(0.74, 0.62),
               rw_w=(0.7, 0.6), pillar_w=0.08, dark_pillars=True):
    """Clean glass: side windows that follow the roofline (split at the pillars), windscreen and back light."""
    L, W, H = p["size"]
    belt = H * p["belt"] + belt_gap
    ys = np.linspace(L / 2, -L / 2, 260)
    inside = [y for y in ys if roof_z(p, y) - inset > belt + 0.06]
    y_front, y_back = max(inside), min(inside)
    cuts = sorted([y_back - 0.01] + [c * L for c in pillars] + [y_front + 0.01], reverse=True)
    for sx, side in ((1, "right"), (-1, "left")):
        for a, b in zip(cuts, cuts[1:]):
            y0 = a - (pillar_w / 2 if a < y_front else 0.0)
            y1 = b + (pillar_w / 2 if b > y_back else 0.0)
            seg = [y for y in np.linspace(y0, y1, 30) if roof_z(p, y) - inset > belt + 0.03]
            if len(seg) < 2: continue
            top = [(y, roof_z(p, y) - inset) for y in seg]
            outline = [(seg[-1], belt), (seg[0], belt)] + top     # counter-clockwise-ish; conform doesn't care
            outline = [(u, max(v, belt)) for u, v in outline]
            conform("side_glass", poly_round(outline[:2] + top[::max(1, len(top) // 12)] + [top[-1]], 0.025, 2),
                    side, "glass", 0.004, 0.015, 0.04)
        if dark_pillars:
            for c in pillars:
                y = c * L
                conform("pillar", [(y - pillar_w / 2, belt - 0.01), (y + pillar_w / 2, belt - 0.01),
                                   (y + pillar_w / 2, roof_z(p, y) - inset + 0.02), (y - pillar_w / 2, roof_z(p, y) - inset + 0.02)],
                        side, "trim", 0.005, 0.01, 0.04)
    # windscreen: seen from the front, between the cowl and the roof's front edge
    roof_t = [t for t, v in p["top"] if v >= 0.96]
    rf, rr = max(roof_t) * L, min(roof_t) * L
    rf_t, rr_t = rf / L, rr / L
    zc = H * min(((t, v) for t, v in p["top"] if t > rf_t + 1e-3), key=lambda tv: tv[0])[1]   # cowl: last point before the roof
    z0, z1 = zc + ws[0], H - ws[1]
    conform("windscreen", poly_round([(-ws_w[0], z0), (ws_w[0], z0), (ws_w[1], z1), (-ws_w[1], z1)], 0.05), "front", "glass", 0.004, 0.015, 0.04)
    zd = H * max(((t, v) for t, v in p["top"] if t < rr_t - 1e-3), key=lambda tv: tv[0])[1]   # deck at the back light's base
    z0, z1 = zd + rw[0], H - rw[1]
    conform("backlight", poly_round([(-rw_w[0], z0), (rw_w[0], z0), (rw_w[1], z1), (-rw_w[1], z1)], 0.06), "rear", "glass", 0.004, 0.015, 0.04)


def hit(origin, d):
    h = BV["bvh"].ray_cast(Vector(origin), Vector(d))
    return h[0], h[1]


def side_basics(p, door_seams, handles, mirror_y, mirror_z, rocker=True, chrome_handles=False):
    """Mirrors, door seams, handles, rocker trim, plates — the parts every car has, placed on the real surface."""
    L, W, H = p["size"]
    for sx in (-1, 1):
        side = "right" if sx > 0 else "left"
        for y in door_seams:
            z0, z1 = p["sill"] + 0.08, H * p["belt"] - 0.01
            conform("seam", [(y - 0.004, z0), (y + 0.004, z0), (y + 0.004, z1), (y - 0.004, z1)], side, "trim", 0.001, 0.006, 0.05)
        for y in handles:
            z = H * p["belt"] - 0.08
            conform("handle", rrect(y - 0.13, z - 0.022, y, z + 0.022, 0.018), side, "chrome" if chrome_handles else "paint", 0.012, 0.02, 0.03)
        pos, n = hit((sx * W, mirror_y, mirror_z), (-sx, 0, 0))
        if pos:
            box("mirror", min(pos.x, pos.x + sx * 0.2), max(pos.x, pos.x + sx * 0.2), pos.y - 0.12, pos.y, pos.z - 0.06, pos.z + 0.08, "paint", 0.03)
            box("mirror_arm", min(pos.x - sx * 0.02, pos.x + sx * 0.06), max(pos.x - sx * 0.02, pos.x + sx * 0.06), pos.y - 0.1, pos.y - 0.02, pos.z - 0.05, pos.z - 0.0, "trim", 0.01)
        if rocker:
            ax = p.get("axle", 0.32) * L
            conform("rocker", [(-ax + p["wr"] + 0.12, p["sill"] - 0.02), (ax - p["wr"] - 0.12, p["sill"] - 0.02),
                               (ax - p["wr"] - 0.12, p["sill"] + 0.06), (-ax + p["wr"] + 0.12, p["sill"] + 0.06)], side, "trim", 0.004, 0.01, 0.06)


def plates(p, zf, zr, front=True):
    if front: conform("plate_f", rrect(-0.155, zf - 0.06, 0.155, zf + 0.06, 0.01), "front", "chrome", 0.01, 0.02, 0.04)
    conform("plate_r", rrect(-0.155, zr - 0.06, 0.155, zr + 0.06, 0.01), "rear", "chrome", 0.01, 0.02, 0.04)


def hexbadge(side, u, v, size=0.06, kind="chrome"):
    pts = [(u + size * 1.6 * math.cos(math.radians(a)), v + size * math.sin(math.radians(a))) for a in range(0, 360, 60)]
    conform("badge", pts, side, kind, 0.016, 0.02, 0.02)


# ------------------------------------------------------------------------------------------------------------------
def corvane_stockman():
    """Corvane Stockman 1500, crew cab short box, 2007-13 style (fleet rank 1). Square-shouldered body with a
    continuous belt line, tall flat bonnet, big chrome grille split by a body-wide chrome bar carrying the badge,
    stacked rectangular headlamps, chrome bumpers, tall vertical taillights, boxy painted arch flares, tube steps."""
    L, W, H = 5.84, 2.03, 1.88
    hw = W / 2
    yf, yr = L / 2, -L / 2
    REF[:] = [0.0, 0.2, 1.45]
    ax = (L * 0.32, -L * 0.32)
    wr, wz = 0.40, 0.40                  # tyre radius / axle height
    sill, belt = 0.50, 1.30
    cowl, cab_r = 1.22, -0.80            # cowl (back of the bonnet) / back of the cab
    bed_f = cab_r - 0.05
    nose = yf - 0.20                     # bonnet/fender front face (bumper and grille stand in front of it)

    # --- front clip: fenders + bonnet as one block; bonnet top falls 6 cm to the nose, shoulders square
    fc = [(hw, cowl, sill), (hw, nose, sill + 0.06), (hw, cowl, belt), (hw - 0.02, nose, belt - 0.05),
          (hw * 0.86, cowl, belt + 0.03), (hw * 0.86, nose, belt - 0.03)]
    fc += [(0.0, cowl, belt + 0.06), (0.0, nose, belt - 0.0)]       # centre power dome
    front = hull("front", fc + mirror_x(fc), "paint", 0.045)
    # --- cab lower (doors)
    cl = [(hw, cab_r, sill), (hw, cowl + 0.02, sill), (hw, cab_r, belt), (hw, cowl + 0.02, belt),
          (hw * 0.9, cab_r, belt + 0.02), (hw * 0.9, cowl + 0.02, belt + 0.02)]
    cabl = hull("cab_lower", cl + mirror_x(cl), "paint", 0.04)
    # --- greenhouse: raked windscreen, near-vertical back light, tumblehome
    gh_t = 0.86 * hw
    roof_f, roof_r, ws_base, roof_z = cowl - 0.66, cab_r + 0.06, cowl - 0.04, H
    gh = [(hw * 0.95, ws_base, belt), (hw * 0.95, cab_r, belt), (gh_t, roof_f, roof_z), (gh_t, roof_r, roof_z),
          (gh_t * 0.92, roof_f - 0.02, roof_z + 0.015), (gh_t * 0.92, roof_r + 0.02, roof_z + 0.015)]
    green = hull("greenhouse", gh + mirror_x(gh), "paint", 0.07, 4)
    # --- bed: box with the tub hollowed out, separate from the cab by a 5 cm gap
    bed = box("bed", -hw, hw, yr + 0.06, bed_f, sill, belt, "paint", 0.035)
    tub = box("tub", -hw + 0.07, hw - 0.07, yr + 0.13, bed_f - 0.07, 0.86, belt + 0.3, "trim", 0.0, keep=False)
    cut(bed, tub); bpy.data.objects.remove(tub)
    # --- wheel arches
    r_arch, z_arch = wr + 0.075, wz + 0.02
    for o in (front, bed):
        for c in arch_cutters(ax, r_arch, z_arch, W):
            cut(o, c); bpy.data.objects.remove(c)
        liner_faces(o, ax, r_arch, z_arch, W)
    for y in ax:
        for sx in (-1, 1):
            fl = arch_flare("flare", y, z_arch, r_arch - 0.005, r_arch + 0.07, sx * (hw - 0.02), sx * (hw + 0.035),
                            -14 if y > 0 else -12, 194, square=1.0)
    # inner well boxes so you can't see through the arch
    for y in ax:
        box("well", -hw + 0.08, hw - 0.08, y - r_arch, y + r_arch, z_arch - 0.05, z_arch + r_arch - 0.02, "trim")

    # --- glass (thin plates proud of the greenhouse faces)
    zb, zt = belt + 0.05, roof_z - 0.07
    def on_side(y, z, sx):
        # x on the greenhouse side surface at height z (linear tumblehome)
        t = (z - belt) / (roof_z - belt)
        return sx * (lerp(hw * 0.95, gh_t, t) + 0.004)
    def ws_y(z): return lerp(ws_base, roof_f, (z - belt) / (roof_z - belt))
    # windscreen
    t0, t1 = 0.06, 0.93
    wq = []
    for sx, tz in ((-1, t0), (1, t0), (1, t1), (-1, t1)):
        z = lerp(belt, roof_z, tz); x = lerp(hw * 0.95, gh_t, tz) - 0.09
        wq.append((sx * x, ws_y(z) + 0.012, z))
    panel("windscreen", [wq[1], wq[0], wq[3], wq[2]], "glass", 0.008)
    # back light
    bq = [(sx * (lerp(hw * 0.95, gh_t, tz) - 0.12), cab_r - 0.006, lerp(belt, roof_z, tz)) for sx, tz in
          ((1, 0.12), (-1, 0.12), (-1, 0.86), (1, 0.86))]
    panel("backlight", bq, "glass", 0.006)
    # side glass: front door (with the A pillar's slope) and rear door; B pillar blacked out
    b_y = 0.22
    for sx in (-1, 1):
        def sp(y, z): return (on_side(y, z, sx), y, z)
        zA = zb; zB = zt
        fq = [sp(b_y + 0.06, zA), sp(ws_y(zA) - 0.1, zA), sp(ws_y(zB) - 0.06, zB), sp(b_y + 0.06, zB)]
        rq = [sp(cab_r + 0.12, zA), sp(b_y - 0.06, zA), sp(b_y - 0.06, zB), sp(cab_r + 0.16, zB)]
        panel("glass_f", fq, "glass", 0.006); panel("glass_r", rq, "glass", 0.006)
        bp = [sp(b_y - 0.06, zA - 0.03), sp(b_y + 0.06, zA - 0.03), sp(b_y + 0.06, zB + 0.02), sp(b_y - 0.06, zB + 0.02)]
        panel("bpillar", bp, "trim", 0.007)
        # belt moulding along the bottom of the side glass
        box("beltline", sx * (hw * 0.95 - 0.01), sx * (hw * 0.95 + 0.012), cab_r + 0.08, ws_y(zA) - 0.04, belt + 0.01,
            belt + 0.035, "trim")
    # --- grille: chrome surround, dark mesh with slats, body-wide chrome bar + oval badge
    gy = nose + 0.035
    gx = 0.56
    box("grille_back", -gx, gx, nose - 0.05, gy - 0.01, 0.74, belt - 0.07, "trim")
    for i in range(5):                                   # horizontal slats
        z = 0.80 + i * 0.075
        if 0.95 < z < 1.13: continue
        box("slat", -gx + 0.05, gx - 0.05, gy - 0.02, gy + 0.005, z, z + 0.028, "chrome", 0.006, 2)
    for sx in (-1, 1):                                   # surround: thick chrome sides
        box("surround", sx * gx - 0.04, sx * gx + 0.04, nose - 0.02, gy + 0.02, 0.72, belt - 0.05, "chrome", 0.02)
    box("surround_top", -gx - 0.04, gx + 0.04, nose - 0.02, gy + 0.02, belt - 0.11, belt - 0.05, "chrome", 0.02)
    box("surround_bot", -gx - 0.04, gx + 0.04, nose - 0.02, gy + 0.02, 0.72, 0.77, "chrome", 0.02)
    box("bar", -gx - 0.04, gx + 0.04, nose - 0.02, gy + 0.04, 0.965, 1.115, "chrome", 0.03)
    badge = cyl("badge", 0.085, 0.03, (0, gy + 0.045, 1.04), (math.pi / 2, 0, 0), "chrome", 6, 0.008)
    badge.scale = (1.9, 1.0, 0.8); bpy.ops.object.transform_apply(scale=True)
    inset = cyl("badge_in", 0.062, 0.02, (0, gy + 0.054, 1.04), (math.pi / 2, 0, 0), "trim", 6)
    inset.scale = (1.9, 1.0, 0.75); bpy.ops.object.transform_apply(scale=True)
    # --- headlamps: stacked twin chambers, top edge flush with the bonnet
    for sx in (-1, 1):
        x0, x1 = sx * (gx + 0.06), sx * (hw - 0.03)
        lo, hi = min(x0, x1), max(x0, x1)
        box("lamp_house", lo, hi, nose - 0.04, nose + 0.035, 0.84, belt - 0.06, "chrome", 0.02)
        box("lamp_lens", lo + 0.015, hi - 0.015, nose + 0.02, nose + 0.045, 0.855, belt - 0.075, "head", 0.012)
        cx = (lo + hi) / 2
        for z0, z1 in ((0.875, 1.03), (1.06, belt - 0.09)):   # two stacked chambers
            box("chamber", cx - 0.13, cx + 0.13, nose + 0.044, nose + 0.05, z0, z1, "chrome", 0.012)
            cyl("bulb", 0.05, 0.02, (cx + sx * 0.03, nose + 0.055, (z0 + z1) / 2), (math.pi / 2, 0, 0), "head", 20)
        box("amber", cx - sx * 0.13 - 0.03, cx - sx * 0.13 + 0.03, nose + 0.05, nose + 0.056, 0.875, 0.94, "tail")
    # --- front bumper: chrome, wraps round the corners; black air dam with fog lamps below
    fb = [(hw - 0.02, yf - 0.16, 0.48), (hw - 0.02, yf - 0.16, 0.76), (hw - 0.12, yf, 0.50), (hw - 0.12, yf - 0.01, 0.74)]
    hull("bumper_f", fb + mirror_x(fb), "chrome", 0.04)
    box("bumper_f_pad", -0.42, 0.42, yf - 0.02, yf + 0.012, 0.58, 0.66, "trim", 0.01)
    ad = [(hw - 0.1, yf - 0.22, 0.40), (hw - 0.16, yf - 0.1, 0.41), (hw - 0.1, yf - 0.22, 0.5), (hw - 0.16, yf - 0.08, 0.5)]
    hull("airdam", ad + mirror_x(ad), "trim", 0.02)
    for sx in (-1, 1):
        box("fog_bezel", sx * 0.68 - 0.1, sx * 0.68 + 0.1, yf - 0.03, yf - 0.0, 0.52, 0.6, "trim", 0.01)
        cyl("fog", 0.035, 0.02, (sx * 0.68, yf + 0.002, 0.56), (math.pi / 2, 0, 0), "head", 20)
    box("plate_f", -0.15, 0.15, yf - 0.005, yf + 0.008, 0.535, 0.62, "chrome")
    # --- rear: tailgate face detail, vertical taillights, chrome bumper with step, plate
    ry = yr + 0.06
    box("tailgate_handle_bezel", -0.16, 0.16, ry - 0.012, ry + 0.01, 1.11, 1.19, "trim", 0.01)
    box("tailgate_handle", -0.1, 0.1, ry - 0.018, ry, 1.13, 1.17, "chrome", 0.008)
    box("tailgate_seam", -hw + 0.05, hw - 0.05, ry - 0.006, ry + 0.01, 0.80, 0.81, "trim")
    for sx in (-1, 1):
        x_out = sx * (hw + 0.004); x_in = sx * (hw - 0.17)
        lo, hi = min(x_out, x_in), max(x_out, x_in)
        box("taillamp", lo, hi, ry - 0.03, ry + 0.06, 0.80, belt - 0.03, "tail", 0.02)
        box("reverse", lo + 0.02, hi - 0.02, ry - 0.034, ry - 0.01, 0.95, 1.03, "head", 0.006)
        box("bedcap", sx * hw - 0.075, sx * hw + 0.005, ry + 0.02, bed_f - 0.01, belt - 0.005, belt + 0.03, "trim", 0.01)
    box("bedcap_front", -hw, hw, bed_f - 0.08, bed_f - 0.005, belt - 0.005, belt + 0.03, "trim", 0.01)
    rb = [(hw - 0.01, yr + 0.12, 0.48), (hw - 0.01, yr + 0.12, 0.72), (hw - 0.08, yr - 0.07, 0.49), (hw - 0.08, yr - 0.07, 0.71)]
    hull("bumper_r", rb + mirror_x(rb), "chrome", 0.035)
    box("step_pad", -0.38, 0.38, yr - 0.082, yr + 0.0, 0.70, 0.725, "trim", 0.008)
    box("plate_r", -0.15, 0.15, yr - 0.08, yr - 0.068, 0.53, 0.62, "chrome")
    box("hitch", -0.04, 0.04, yr - 0.17, yr, 0.44, 0.49, "trim", 0.01)
    # --- sides: door seams, handles, mirrors, tube steps, fuel door, rockers
    seams = [cowl + 0.0, b_y, cab_r + 0.01]
    for sx in (-1, 1):
        x = sx * (hw + 0.003)
        for y in seams:
            box("seam", min(x, x - sx * 0.006), max(x, x - sx * 0.006), y - 0.005, y + 0.005, sill + 0.05, belt + 0.0, "trim")
        box("seam_low", min(x, x - sx * 0.006), max(x, x - sx * 0.006), cab_r + 0.01, cowl, sill + 0.045, sill + 0.055, "trim")
        for y in (b_y + 0.08, cab_r + 0.14):
            box("handle_pocket", min(x, x + sx * 0.006), max(x, x + sx * 0.006), y - 0.12, y + 0.0, belt - 0.12, belt - 0.06, "trim", 0.006)
            box("handle", min(x + sx * 0.004, x + sx * 0.022), max(x + sx * 0.004, x + sx * 0.022), y - 0.11, y - 0.01,
                belt - 0.11, belt - 0.07, "chrome", 0.008)
        # big towing-style mirror on a stalk
        mx0 = x; mx1 = x + sx * 0.24
        box("mirror_arm", min(mx0, mx1 - sx * 0.08), max(mx0, mx1 - sx * 0.08), cowl - 0.14, cowl - 0.06, belt + 0.04, belt + 0.09, "trim", 0.015)
        box("mirror", min(mx1 - sx * 0.12, mx1), max(mx1 - sx * 0.12, mx1), cowl - 0.16, cowl - 0.06, belt + 0.02, belt + 0.27, "paint", 0.03)
        box("mirror_glass", min(mx1 - sx * 0.11, mx1 - sx * 0.01), max(mx1 - sx * 0.11, mx1 - sx * 0.01), cowl - 0.165, cowl - 0.155,
            belt + 0.035, belt + 0.255, "chrome")
        # chrome tube step between the arches
        y0, y1 = ax[1] + r_arch + 0.1, ax[0] - r_arch - 0.12
        cyl("step", 0.038, y1 - y0, (sx * (hw + 0.05), (y0 + y1) / 2, sill - 0.04), (math.pi / 2, 0, 0), "chrome", 16)
        for y in (y0 + 0.12, (y0 + y1) / 2, y1 - 0.12):
            box("step_bracket", min(sx * (hw - 0.06), sx * (hw + 0.05)), max(sx * (hw - 0.06), sx * (hw + 0.05)), y - 0.025,
                y + 0.025, sill - 0.06, sill - 0.01, "trim")
        box("rocker", min(sx * (hw - 0.03), sx * (hw + 0.005)), max(sx * (hw - 0.03), sx * (hw + 0.005)), cab_r, cowl, sill - 0.04, sill + 0.03, "trim", 0.01)
    box("fuel_door", -hw - 0.004, -hw + 0.001, ax[1] + r_arch + 0.14, ax[1] + r_arch + 0.32, 1.0, 1.15, "trim")
    box("fuel_door_lid", -hw - 0.007, -hw - 0.003, ax[1] + r_arch + 0.15, ax[1] + r_arch + 0.31, 1.01, 1.14, "paint", 0.005)
    # wiper arms + cowl vent
    box("cowl_vent", -hw * 0.86, hw * 0.86, cowl - 0.07, cowl + 0.0, belt + 0.035, belt + 0.06, "trim", 0.01)
    for x in (-0.25, 0.35):
        hull("wiper", [(x, cowl - 0.02, belt + 0.06), (x + 0.02, cowl - 0.02, belt + 0.07), (x - 0.5, cowl - 0.2, belt + 0.14),
                       (x - 0.48, cowl - 0.2, belt + 0.15)], "trim")
    # antenna
    cyl("antenna", 0.004, 0.75, (hw - 0.12, cowl - 0.15, belt + 0.4), (0.12, 0, 0), "trim", 6)
    # underbody: frame rails, fuel tank, exhaust, spare under the bed (dark)
    box("under", -hw + 0.1, hw - 0.1, yr + 0.3, yf - 0.4, sill - 0.12, sill, "trim")
    for sx in (-1, 1):
        box("frame", sx * 0.42 - 0.04, sx * 0.42 + 0.04, yr + 0.15, yf - 0.25, 0.32, 0.48, "trim")
    cyl("exhaust", 0.045, 0.14, (hw - 0.45, yr + 0.05, 0.38), (math.pi / 2, 0, 0), "chrome", 14)
    return dict(L=L, W=W, H=H, axles=ax, wr=wr, wz=wz, tyre_w=0.27)


def corvane_dutchess():
    """Corvane Dutchess, 2006-13 full-size front-drive sedan style (fleet rank 2): long, upright three-box with a
    tall rounded nose, wide swept headlamps, a narrow chrome upper grille over a chrome bar with the badge, a big
    lower intake, short high deck with wide corner taillamps and a chrome deck strip."""
    L, W, H = 5.09, 1.85, 1.48
    p = dict(size=(L, W, H), belt=0.62, sill=0.30, tum=0.17, wr=0.34, axle=0.276, pillars=[-0.07],
             top=[(0.5, 0.52), (0.48, 0.58), (0.33, 0.645), (0.22, 0.665), (0.05, 1.0), (-0.19, 1.0), (-0.32, 0.73),
                  (-0.46, 0.715), (-0.5, 0.63)])
    REF[:] = [0.0, 0.0, 1.0]
    lofted("car_body", p)
    glasshouse(p, [-0.07], ws_w=(0.72, 0.6), rw_w=(0.66, 0.56))
    # front: headlamps, grille, bar + badge, lower intake, fog lamps
    head = poly_round([(0.40, 0.745), (0.78, 0.715), (0.885, 0.76), (0.875, 0.84), (0.41, 0.855)], 0.03)
    both(lambda q: conform("headlamp", q, "front", "head", 0.008, 0.02), head)
    both(lambda q: conform("lamp_bezel", q, "front", "chrome", 0.004, 0.02), poly_round([(0.385, 0.735), (0.79, 0.703), (0.9, 0.755),
                                                                                       (0.89, 0.85), (0.395, 0.866)], 0.035))
    both(lambda q: conform("lamp_inner", q, "front", "chrome", 0.012, 0.01), rrect(0.47, 0.765, 0.63, 0.835, 0.03))
    conform("grille_surround", rrect(-0.36, 0.745, 0.36, 0.86, 0.03), "front", "chrome", 0.008, 0.02)
    conform("grille_mesh", rrect(-0.33, 0.765, 0.33, 0.84, 0.02), "front", "trim", 0.011, 0.01)
    for z in (0.785, 0.81):
        conform("grille_bar", [(-0.32, z), (0.32, z), (0.32, z + 0.008), (-0.32, z + 0.008)], "front", "chrome", 0.013, 0.004, 0.04)
    conform("bar", rrect(-0.42, 0.70, 0.42, 0.735, 0.012), "front", "chrome", 0.01, 0.02)
    hexbadge("front", 0.0, 0.80, 0.045)
    conform("intake", poly_round([(-0.5, 0.42), (0.5, 0.42), (0.44, 0.59), (-0.44, 0.59)], 0.04), "front", "trim", 0.006, 0.03)
    for z in (0.47, 0.53):
        conform("intake_bar", [(-0.46, z), (0.46, z), (0.46, z + 0.012), (-0.46, z + 0.012)], "front", "chrome", 0.01, 0.004, 0.04)
    both(lambda q: conform("fog", q, "front", "head", 0.008, 0.02), rrect(0.6, 0.44, 0.72, 0.51, 0.03))
    conform("chin", rrect(-0.75, 0.30, 0.75, 0.36, 0.02), "front", "trim", 0.006, 0.02)
    # rear: corner taillamps with round inners, reverse lamps, deck chrome, badge, plate, lower valance
    both(lambda q: conform("taillamp", q, "rear", "tail", 0.008, 0.02), rrect(0.40, 0.83, 0.875, 0.975, 0.045))
    for cx in (0.55, 0.74):
        both(lambda q: conform("tail_ring", q, "rear", "chrome", 0.012, 0.006, 0.02),
             [(cx + 0.05 * math.cos(math.radians(a)), 0.902 + 0.05 * math.sin(math.radians(a))) for a in range(0, 360, 30)])
    both(lambda q: conform("reverse", q, "rear", "head", 0.012, 0.01), rrect(0.42, 0.845, 0.49, 0.895, 0.012))
    conform("deck_strip", rrect(-0.38, 0.91, 0.38, 0.935, 0.01), "rear", "chrome", 0.008, 0.015)
    hexbadge("rear", 0.0, 0.98, 0.04)
    conform("valance", rrect(-0.8, 0.30, 0.8, 0.38, 0.02), "rear", "trim", 0.006, 0.02)
    plates(p, 0.0, 0.56, front=False)
    cyl("exhaust", 0.035, 0.16, (0.55, -L / 2 + 0.1, 0.31), (math.pi / 2, 0, 0), "chrome", 14)
    side_basics(p, door_seams=[0.86, -0.12, -0.98], handles=[-0.02, -0.85], mirror_y=0.92, mirror_z=1.0)
    # side marker reflectors + body-colour rub strip
    for sx, side in ((1, "right"), (-1, "left")):
        conform("rub", rrect(-1.5, 0.52, 1.6, 0.56, 0.02), side, "trim", 0.006, 0.01, 0.05)
        conform("marker_f", rrect(2.2, 0.62, 2.32, 0.65, 0.01), side, "tail", 0.006, 0.01)
        conform("marker_r", rrect(-2.38, 0.66, -2.26, 0.69, 0.01), side, "tail", 0.006, 0.01)
    return dict(L=L, W=W, H=H, axles=(L * p["axle"], -L * p["axle"]), wr=p["wr"], wz=p["wr"], tyre_w=0.23)


MODELS = {"corvane_stockman": corvane_stockman, "corvane_dutchess": corvane_dutchess}
# which toledo_fleet.json ranks each model stands in for (same make/model/generation)
RANKS = {"corvane_stockman": [1], "corvane_dutchess": [2]}


def write_manifest(info):
    """assets/models/fleet/fleet_models.json: what traffic.gd needs to spawn each built model at its real share."""
    import json, os
    root = os.path.dirname(os.path.abspath(OUT.rstrip("/")))
    fleet = json.load(open(os.path.join(os.path.dirname(__file__), "..", "..", "source_data", "toledo_fleet.json")))["vehicles"]
    first = [v for v in fleet if v["rank"] == RANKS[MODEL][0]][0]
    path = os.path.join(OUT, "fleet_models.json")
    man = json.load(open(path)) if os.path.exists(path) else {"_doc": "Built Toledo fleet models (tools/blender/fleet_cars.py). "
          "size = [L, W, H] m; axle = axle distance from centre / L; wr = wheel radius m; ranks = toledo_fleet.json ranks covered.",
          "models": []}
    man["models"] = [m for m in man["models"] if m["id"] != MODEL]
    man["models"].append({"id": MODEL, "glb": "fleet/car_" + MODEL, "make": first["parody_make"], "model": first["parody_model"],
                          "family": first["body"], "years": first["years"], "ranks": RANKS[MODEL],
                          "size": [round(info["L"], 3), round(info["W"], 3), round(info["H"], 3)],
                          "axle": round(info["axles"][0] / info["L"], 4), "wr": info["wr"]})
    man["models"].sort(key=lambda m: m["ranks"][0])
    json.dump(man, open(path, "w"), indent=1)


def make_wheel(c, r, w, sx):
    """Preview wheel: tyre + chrome-clad steel/alloy face (the game uses its own WheelMesh)."""
    t = cyl("tyre", r, w, c, (0, math.pi / 2, 0), "trim", 40, 0.04, keep=False); PREVIEW_ONLY.append(t)
    face = Vector(c) + Vector((sx * (w / 2 - 0.02), 0, 0))
    rim = cyl("rim", r * 0.66, 0.04, tuple(face), (0, math.pi / 2, 0), "rim", 32, 0.01, keep=False); PREVIEW_ONLY.append(rim)
    hub = cyl("hub", r * 0.2, 0.06, tuple(face + Vector((sx * 0.02, 0, 0))), (0, math.pi / 2, 0), "chrome", 16, keep=False)
    PREVIEW_ONLY.append(hub)
    dish = cyl("dish", r * 0.5, 0.045, tuple(face - Vector((sx * 0.004, 0, 0))), (0, math.pi / 2, 0), "trim", 24, keep=False)
    PREVIEW_ONLY.append(dish)


def render_preview(path, info):
    from PIL import Image
    sc = bpy.context.scene; sc.render.engine = "BLENDER_EEVEE"
    w = bpy.data.worlds.new("w"); sc.world = w; w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[0].default_value = (0.62, 0.68, 0.76, 1)
    w.node_tree.nodes["Background"].inputs[1].default_value = 0.9
    for nm, rot, e in (("key", (50, 0, 40), 3.4), ("fill", (70, 0, -70), 1.0), ("rim", (60, 0, 180), 1.6)):
        ld = bpy.data.lights.new(nm, "SUN"); ld.energy = e; ld.angle = math.radians(6)
        lo = bpy.data.objects.new(nm, ld); sc.collection.objects.link(lo)
        lo.rotation_euler = [math.radians(x) for x in rot]
    g = box("ground", -12, 12, -12, 12, -0.02, 0.0, None, keep=False)
    g.data.materials.append(mat("asphalt", (0.16, 0.16, 0.17), 0, 0.9))
    shots = []
    for i, (ang, el) in enumerate(((35, 12), (150, 12), (90, 4), (0, 6))):
        cd = bpy.data.cameras.new("c"); cd.lens = 50; c = bpy.data.objects.new("c", cd); sc.collection.objects.link(c)
        r = 9.5; a = math.radians(ang); e = math.radians(el)
        tgt = Vector((0, 0, 0.95))
        c.location = tgt + Vector((r * math.sin(a) * math.cos(e), r * math.cos(a) * math.cos(e), r * math.sin(e)))
        c.rotation_euler = (tgt - c.location).to_track_quat("-Z", "Y").to_euler()
        sc.camera = c; sc.render.resolution_x, sc.render.resolution_y = 900, 600
        fp = path.replace(".png", "_%d.png" % i); sc.render.filepath = fp
        bpy.ops.render.render(write_still=True); shots.append(fp)
    ims = [Image.open(f) for f in shots]
    out = Image.new("RGB", (ims[0].width * 2, ims[0].height * 2))
    for k, im in enumerate(ims): out.paste(im, ((k % 2) * im.width, (k // 2) * im.height))
    out.save(path); print("preview", path)


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    paint = hexc(OPT.get("paint", "#8a1414"))
    M.update({"paint": mat("paint", paint, 0.35, 0.28), "glass": mat("glass", (0.02, 0.025, 0.03), 0.4, 0.05),
              "trim": mat("trim", (0.035, 0.035, 0.04), 0.0, 0.75), "chrome": mat("chrome", (0.75, 0.76, 0.78), 1.0, 0.12),
              "head": mat("head", (0.9, 0.9, 0.88), 0.0, 0.08, emit=(1, 0.96, 0.88), es=0.3),
              "rim": mat("rim", (0.55, 0.56, 0.58), 0.6, 0.35),
              "tail": mat("tail", (0.55, 0.02, 0.02), 0.0, 0.15, emit=(1, 0.05, 0.02), es=0.4)})
    info = MODELS[MODEL]()
    for o in PARTS:
        o.select_set(False)
    # join exported parts
    bpy.ops.object.select_all(action="DESELECT")
    for o in PARTS: o.select_set(True)
    body = PARTS[0]; bpy.context.view_layer.objects.active = body
    bpy.ops.object.join(); body.name = "car_" + MODEL
    bpy.ops.object.shade_auto_smooth(angle=math.radians(35))
    tris = sum(len(f.vertices) - 2 for f in body.data.polygons)
    bpy.ops.object.select_all(action="DESELECT"); body.select_set(True)
    out = "%s/car_%s.glb" % (OUT, MODEL)
    bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", use_selection=True)
    print("built %s %d tris -> %s" % (MODEL, tris, out))
    if "assets/models/fleet" in OUT: write_manifest(info)
    if OPT.get("preview"):
        for y in info["axles"]:
            for sx in (-1, 1):
                make_wheel((sx * (info["W"] / 2 - 0.12), y, info["wz"]), info["wr"], info["tyre_w"], sx)
        render_preview(OPT["preview"], info)


main()
