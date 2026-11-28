"""Blender (bpy) procedural car bodies for GLASS CITY. One .glb per body type into OUT/car_<body>.glb.
Body = lofted cross-section rings along the length -> Catmull-Clark subdivision -> wheel-arch booleans -> faces
classified into paint / glass / trim by region -> lights, grille, bumpers, mirrors, handles and plates placed by
raycasting onto the finished surface. Wheels are NOT included (the game adds its own wheel meshes).
Material names are a contract with scripts/traffic.gd: paint, glass, chrome, trim, head, tail.
Axes: Blender +Y = car front (= Godot -Z), +Z up. Origin: ground under the body centre.
usage: bpyenv/bin/python tools/blender/cars.py OUTDIR [body ...]"""
import sys, math, bpy, bmesh
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree

if __name__ == "__main__":
    OUT = sys.argv[1]
    ONLY = sys.argv[2:]

def lerp(a, b, t): return a + (b - a) * t
def clamp(x, a, b): return max(a, min(b, x))
def interp(prof, t):
    """prof: [(t, v)] sorted by t descending (front +0.5 -> rear -0.5)."""
    if t >= prof[0][0]: return prof[0][1]
    for (t0, v0), (t1, v1) in zip(prof, prof[1:]):
        if t1 <= t <= t0:
            return lerp(v0, v1, (t0 - t) / max(1e-6, t0 - t1))
    return prof[-1][1]

# body types: size (L, W, H); belt (fraction of H); top profile (t, fraction of H); pillars (t of B/C pillars);
# tumblehome (m); sill (m); wheel radius; tall (box-like van/truck/bus)
TYPES = {
    "sedan":  dict(size=(4.8, 1.85, 1.45), belt=0.64, sill=0.3, tum=0.17, wr=0.34, pillars=[-0.06],
                   top=[(0.5, 0.47), (0.47, 0.56), (0.30, 0.63), (0.19, 0.66), (0.04, 1.0), (-0.17, 1.0), (-0.32, 0.69), (-0.45, 0.67), (-0.5, 0.56)]),
    "coupe":  dict(size=(4.8, 1.9, 1.3), belt=0.64, sill=0.29, tum=0.2, wr=0.34, pillars=[],
                   top=[(0.5, 0.46), (0.47, 0.56), (0.28, 0.62), (0.17, 0.65), (0.0, 1.0), (-0.16, 1.0), (-0.34, 0.7), (-0.46, 0.68), (-0.5, 0.57)]),
    "sports": dict(size=(4.4, 1.9, 1.2), belt=0.6, sill=0.24, tum=0.22, wr=0.34, pillars=[],
                   top=[(0.5, 0.44), (0.46, 0.57), (0.36, 0.68), (0.24, 0.7), (0.13, 0.71), (-0.04, 1.0), (-0.16, 0.98), (-0.36, 0.71), (-0.47, 0.7), (-0.5, 0.6)]),
    "hatch":  dict(size=(4.2, 1.75, 1.46), belt=0.62, sill=0.3, tum=0.15, wr=0.34, pillars=[-0.02],
                   top=[(0.5, 0.47), (0.47, 0.56), (0.32, 0.62), (0.22, 0.65), (0.06, 1.0), (-0.36, 0.97), (-0.47, 0.72), (-0.5, 0.6)]),
    "wagon":  dict(size=(4.8, 1.8, 1.5), belt=0.62, sill=0.3, tum=0.15, wr=0.34, pillars=[-0.04, -0.3],
                   top=[(0.5, 0.47), (0.47, 0.56), (0.31, 0.62), (0.21, 0.65), (0.06, 1.0), (-0.44, 0.98), (-0.48, 0.74), (-0.5, 0.62)]),
    "suv":    dict(size=(4.8, 1.92, 1.8), belt=0.6, sill=0.38, tum=0.12, wr=0.4, pillars=[-0.04, -0.3],
                   top=[(0.5, 0.5), (0.47, 0.57), (0.3, 0.61), (0.21, 0.63), (0.07, 1.0), (-0.42, 0.99), (-0.48, 0.78), (-0.5, 0.62)]),
    "pickup": dict(size=(5.85, 2.02, 1.92), belt=0.56, sill=0.42, tum=0.1, wr=0.4, pillars=[-0.02], bed=-0.1,
                   top=[(0.5, 0.52), (0.47, 0.58), (0.3, 0.6), (0.24, 0.62), (0.13, 1.0), (-0.08, 1.0), (-0.1, 0.6), (-0.5, 0.6)]),
    "van":    dict(size=(5.6, 2.05, 2.4), belt=0.48, sill=0.36, tum=0.05, wr=0.4, pillars=[0.18], tall=True,
                   top=[(0.5, 0.36), (0.47, 0.42), (0.38, 0.47), (0.29, 0.98), (0.26, 1.0), (-0.5, 1.0)]),
    "box":    dict(size=(7.4, 2.4, 3.3), belt=0.4, sill=0.42, tum=0.04, wr=0.46, pillars=[], tall=True, cab=0.28,
                   top=[(0.5, 0.3), (0.48, 0.36), (0.42, 0.4), (0.37, 0.72), (0.27, 0.74), (0.255, 1.0), (-0.5, 1.0)]),
    "bus":    dict(size=(12.2, 2.6, 3.2), belt=0.34, sill=0.32, tum=0.03, wr=0.46, tall=True,
                   pillars=[0.38, 0.27, 0.16, 0.05, -0.06, -0.17, -0.28, -0.39], top=[(0.5, 0.92), (0.48, 1.0), (-0.48, 1.0), (-0.5, 0.94)]),
}

def mat(name, col, metal=0.0, rough=0.5, emit=None):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*col, 1); b.inputs["Metallic"].default_value = metal; b.inputs["Roughness"].default_value = rough
    if emit:
        b.inputs["Emission Color"].default_value = (*emit, 1); b.inputs["Emission Strength"].default_value = 2.0
    return m

def ring(p, t, L, W, H):
    """cross-section at station t (front +0.5): list of (x, z) for the right half, bottom centre -> top centre."""
    hw0 = W * 0.5
    e = max(0.0, abs(t) - 0.36) / 0.14                 # 0 mid-body .. 1 at the bumper
    tall = p.get("tall", False)
    hw = hw0 * (1.0 - (0.07 if not tall else 0.025) * e * e)
    sill = p["sill"] + (0.08 if not tall else 0.03) * e * e
    belt = H * p["belt"]
    top = H * interp(p["top"], t)
    if p.get("bed") is not None and t < p["bed"] - 0.02:      # pickup bed: flat deck at the bed rails
        top = min(top, H * 0.6)
    g = clamp((top - belt) / 0.18, 0.0, 1.0)            # greenhouse present
    tum = p["tum"] * g
    beltz = min(belt, top - 0.03)
    low = sill + 0.16
    mid = lerp(low, beltz, 0.55)
    pts = [(0.0, sill - 0.02), (hw * 0.86, sill), (hw * 0.985, low), (hw, mid), (hw * 0.975, beltz)]
    # greenhouse (or, collapsed, the rounded bonnet/deck edge)
    full = [(hw * 0.965 - tum * 0.45, lerp(beltz, top, 0.5)), (hw * 0.955 - tum, top - 0.05), (hw * 0.8 - tum, top), (hw * 0.35, top)]
    flat = [(hw * 0.94, top - 0.012), (hw * 0.86, top), (hw * 0.6, top + 0.004), (hw * 0.3, top + 0.006)]
    for (fx, fz), (cx, cz) in zip(full, flat):
        pts.append((lerp(cx, fx, g), lerp(cz, fz, g)))
    pts.append((0.0, top + (0.006 if g < 0.5 else 0.0)))
    if tall:     # boxy: sharper shoulders
        pts[-3] = (hw * 0.97, top - 0.03); pts[-2] = (hw * 0.8, top); pts[-4] = (hw * 0.975, lerp(beltz, top, 0.6))
    return pts

def build_body(name, p):
    L, W, H = p["size"]
    stations = sorted(set([round(0.5 - i / 40.0, 4) for i in range(41)] + [round(t, 4) for t, _ in p["top"]] +
                          [round(t + d, 4) for t, _ in p["top"] for d in (-0.012, 0.012) if -0.5 < t + d < 0.5]), reverse=True)
    bm = bmesh.new()
    rings = []
    for t in stations:
        half = ring(p, t, L, W, H)
        loop = [(x, z) for x, z in half] + [(-x, z) for x, z in reversed(half[1:-1])]
        rings.append([bm.verts.new((x, t * L, z)) for x, z in loop])
    n = len(rings[0])
    for a, b in zip(rings, rings[1:]):
        for i in range(n):
            j = (i + 1) % n
            bm.faces.new((a[i], a[j], b[j], b[i]))
    # end caps pulled in slightly so subdivision rounds the nose and tail
    for r, sgn in ((rings[0], 1), (rings[-1], -1)):
        c = sum((v.co for v in r), Vector()) / len(r)
        inner = [bm.verts.new(c + (v.co - c) * 0.72 + Vector((0, 0.06 * sgn, 0))) for v in r]
        for i in range(n):
            j = (i + 1) % n
            f = bm.faces.new((r[i], r[j], inner[j], inner[i]) if sgn > 0 else (r[j], r[i], inner[i], inner[j]))
        bm.faces.new(inner if sgn < 0 else list(reversed(inner)))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    cr = bm.edges.layers.float.new("crease_edge")
    half_n = len(ring(p, 0.0, L, W, H))
    sharp = {4: 0.55, half_n - 3: 0.45}     # shoulder/belt line and the roof rail
    for a, b in zip(rings, rings[1:]):
        for i, w in sharp.items():
            for k in (i, n - i):
                if 0 < k < n:
                    e = bm.edges.get((a[k], b[k]))
                    if e: e[cr] = w
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    o = bpy.data.objects.new(name, me); bpy.context.collection.objects.link(o)
    bpy.context.view_layer.objects.active = o; o.select_set(True)
    sd = o.modifiers.new("sub", "SUBSURF"); sd.levels = 2; sd.render_levels = 2
    bpy.ops.object.modifier_apply(modifier="sub")
    # wheel arches
    wr = p["wr"]
    axf = p.get("axle", 0.32)
    for wy, sx in ((L * axf, 1), (-L * axf, 1), (L * axf, -1), (-L * axf, -1)):
        bpy.ops.mesh.primitive_cylinder_add(vertices=40, radius=wr + 0.075, depth=0.7, location=(sx * (W * 0.5 + 0.05), wy, wr + 0.02), rotation=(0, math.pi / 2, 0))
        cut = bpy.context.active_object
        bo = o.modifiers.new("arch", "BOOLEAN"); bo.object = cut; bo.operation = "DIFFERENCE"; bo.solver = "EXACT"
        bpy.context.view_layer.objects.active = o
        bpy.ops.object.modifier_apply(modifier="arch")
        bpy.data.objects.remove(cut)
    return o

def classify(o, p, M):
    L, W, H = p["size"]
    belt = H * p["belt"]; tall = p.get("tall", False)
    for k in ("paint", "glass", "trim", "chrome"): o.data.materials.append(M[k])
    idx = {k: i for i, k in enumerate(("paint", "glass", "trim", "chrome"))}
    me = o.data
    for f in me.polygons:
        c = f.center; nrm = f.normal; t = c.y / L
        top = H * interp(p["top"], t)
        m = "paint"
        if c.z < p["sill"] + 0.07 or nrm.z < -0.6: m = "trim"
        for wy in (L * p.get("axle", 0.32), -L * p.get("axle", 0.32)):      # inside of the wheel arches (the boolean's cylinder walls)
            d = Vector((wy - c.y, p["wr"] + 0.02 - c.z))
            if abs(d.length - p["wr"] - 0.075) < 0.02 and abs(c.x) < W * 0.5 - 0.01 and Vector((nrm.y, nrm.z)).dot(d.normalized()) > 0.5: m = "trim"
        if p.get("bed") is not None and t < p["bed"] - 0.03 and nrm.z > 0.8 and abs(c.x) < W * 0.42: m = "trim"   # bed cover
        if not tall:
            prof = p["top"]
            roof = [t for t, v in prof if v >= 0.96]
            roof_f, roof_r = max(roof), min(roof)
            cowl = min(t for t, v in prof if t > roof_f)
            rbase = max(t for t, v in prof if t < roof_r)
            if belt + 0.06 < c.z < H - 0.05 and abs(nrm.x) <= 0.45 and abs(c.x) < W * 0.39:
                if roof_f * L + 0.05 < c.y < cowl * L - 0.04 and nrm.y > 0.2: m = "glass"     # windscreen
                if rbase * L + 0.04 < c.y < roof_r * L - 0.05 and nrm.y < -0.2: m = "glass"   # rear window
            if belt + 0.04 < c.z < top - 0.045:
                if abs(nrm.x) > 0.45:       # side windows: keep a frame away from the sloped pillars
                    tp = H * interp(prof, (c.y + 0.09) / L); tm = H * interp(prof, (c.y - 0.09) / L)
                    if c.z < min(tp, tm) - 0.05 and all(abs(c.y - pt * L) > 0.06 for pt in p["pillars"]): m = "glass"
        else:
            if belt + 0.05 < c.z < H - 0.12 and nrm.y > 0.5 and abs(c.x) < W * 0.42 and t > 0.25 and (p.get("cab") is None or c.z < H * 0.72 - 0.08):
                m = "glass"
            elif belt + 0.05 < c.z < top - 0.1:
                if False: pass
                elif abs(nrm.x) > 0.6:
                    if "bus" in o.name: inside = -0.46 * L < c.y < 0.45 * L
                    elif p.get("cab") is not None: inside = (p["cab"] + 0.02) * L < c.y < 0.43 * L
                    else: inside = (p["pillars"][0] + 0.02) * L < c.y < 0.42 * L
                    if inside and all(abs(c.y - pt * L) > 0.07 for pt in p["pillars"]) and c.z < top - 0.15: m = "glass"
        f.material_index = idx[m]

def add_part(o_list, kind, size, loc, M, rot=(0, 0, 0), bevel=0.01, cyl=False, verts=16):
    if cyl:
        bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=size[0], depth=size[1], location=loc, rotation=rot)
    else:
        bpy.ops.mesh.primitive_cube_add(size=1, location=loc, rotation=rot)
        bpy.context.active_object.scale = size
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    q = bpy.context.active_object
    q.data.materials.append(M[kind])
    if bevel > 0:
        b = q.modifiers.new("b", "BEVEL"); b.width = bevel; b.segments = 2
        bpy.ops.object.modifier_apply(modifier="b")
    o_list.append(q)
    return q

def details(o, p, M):
    L, W, H = p["size"]; hw = W * 0.5; tall = p.get("tall", False)
    dg = bpy.context.evaluated_depsgraph_get()
    bvh = BVHTree.FromObject(o, dg)
    belt = H * p["belt"]
    parts = []
    def hit(origin, d):
        r = bvh.ray_cast(Vector(origin), Vector(d))
        return r[0], r[1]
    # headlights + grille + front bumper
    ly = belt - (0.13 if not tall else 0.2) if not tall else p["sill"] + 0.62
    if "bus" in o.name: ly = p["sill"] + 0.45
    for sx in (-1, 1):
        x = sx * hw * (0.68 if not tall else 0.74)
        pos, n = hit((x, L, ly), (0, -1, 0))
        if pos:
            q = add_part(parts, "trim", (W * 0.23, 0.07, 0.13), pos - n * 0.004, M, bevel=0.025)
            q.rotation_euler = n.to_track_quat("Y", "Z").to_euler()
            q = add_part(parts, "head", (W * 0.2, 0.08, 0.1), pos + n * 0.006, M, bevel=0.03)
            q.rotation_euler = n.to_track_quat("Y", "Z").to_euler()
        pos, n = hit((x, -L, ly + (0.05 if not tall else 0.0)), (0, 1, 0))
        if pos:
            q = add_part(parts, "tail", (W * 0.2 if not tall else 0.22, 0.06, 0.1 if not tall else 0.3), pos + n * 0.004, M, bevel=0.015)
            q.rotation_euler = (-n).to_track_quat("-Y", "Z").to_euler() if False else n.to_track_quat("Y", "Z").to_euler()
    pos, n = hit((0, L, ly - 0.06), (0, -1, 0))
    if pos:
        g = add_part(parts, "trim", (W * 0.36, 0.06, 0.14 if not tall else 0.3), pos + n * 0.004, M, bevel=0.02)
        g.rotation_euler = n.to_track_quat("Y", "Z").to_euler()
        for i in range(4 if not tall else 6):        # grille slats
            s = add_part(parts, "chrome", (W * 0.35, 0.01, 0.012), pos + n * 0.03 + Vector((0, 0, -0.05 + i * 0.035)), M, bevel=0)
    for ends in (1, -1):
        bz = p["sill"] + 0.1
        pos, n = hit((0, ends * L, bz), (0, -ends, 0))
        if pos:
            add_part(parts, "trim", (W * 0.94, 0.12, 0.14), Vector((0, pos.y + ends * 0.02, bz)), M, bevel=0.04)
        pos, n = hit((0, ends * L, bz + 0.2), (0, -ends, 0))
        if pos:   # license plate
            q = add_part(parts, "chrome", (0.52, 0.01, 0.12), pos + n * 0.006, M, bevel=0.0)
            q.rotation_euler = n.to_track_quat("Y", "Z").to_euler()
    # mirrors at the A-pillar base, door handles along the belt
    fr = max(t for t, v in p["top"] if v * H > belt + 0.12) if not tall else 0.43
    for sx in (-1, 1):
        pos, n = hit((sx * W, (fr - 0.03) * L, belt + 0.06), (-sx, 0, 0))
        if pos:
            add_part(parts, "paint", (0.16, 0.1, 0.11), pos + Vector((sx * 0.1, 0, 0)), M, bevel=0.03)
            add_part(parts, "trim", (0.06, 0.03, 0.03), pos + Vector((sx * 0.03, 0, 0)), M, bevel=0.0)
        if not tall or "bus" not in o.name:
            for hy in ([0.1, -0.12] if not tall else [0.32]):
                pos, n = hit((sx * W, hy * L, belt - 0.07), (-sx, 0, 0))
                if pos: add_part(parts, "chrome", (0.02, 0.15, 0.03), pos + n * 0.01, M, bevel=0.008)
    # door seams: thin dark lines following the side surface from the rocker up to the window line
    seams = {"sedan": [0.21, -0.06, -0.31], "coupe": [0.17, -0.2], "sports": [0.12, -0.2], "hatch": [0.22, -0.02, -0.3],
             "wagon": [0.21, -0.04, -0.3], "suv": [0.2, -0.04, -0.3], "pickup": [0.2, -0.02], "van": [0.42, 0.18, -0.05, -0.5 + 0.01],
             "box": [0.44, 0.29], "bus": [0.44, 0.36]}.get(o.name.replace("car_", ""), [])
    for sx in (-1, 1):
        for sy in seams:
            z = p["sill"] + 0.1; top_z = belt - 0.01 if not tall else H * 0.9
            while z < top_z:
                pos, n = hit((sx * W, sy * L, z + 0.04), (-sx, 0, 0))
                if pos:
                    q = add_part(parts, "trim", (0.006, 0.008, 0.085), pos + n * 0.002, M, bevel=0)
                    q.rotation_euler = n.to_track_quat("X", "Z").to_euler() if sx > 0 else (-n).to_track_quat("-X", "Z").to_euler()
                z += 0.08
    # side skirt / rocker trim
    for sx in (-1, 1):
        add_part(parts, "trim", (0.05, L * 0.3, 0.08), (sx * (hw * 0.86 + 0.01), 0, p["sill"] + 0.03), M, bevel=0.02)
    if p.get("bed") is not None:     # pickup bed rails + tailgate line
        for sx in (-1, 1):
            add_part(parts, "trim", (0.05, L * 0.36, 0.04), (sx * (hw * 0.9), (p["bed"] - 0.21) * L, H * 0.6 + 0.02), M, bevel=0.01)
    return parts

def build(body):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    p = TYPES[body]
    M = {"paint": mat("paint", (0.6, 0.6, 0.62), 0.3, 0.3), "glass": mat("glass", (0.03, 0.04, 0.05), 0.5, 0.05),
         "trim": mat("trim", (0.04, 0.04, 0.045), 0.0, 0.7), "chrome": mat("chrome", (0.7, 0.72, 0.74), 1.0, 0.15),
         "head": mat("head", (0.95, 0.95, 0.9), 0.0, 0.1, emit=(1, 0.95, 0.85)), "tail": mat("tail", (0.6, 0.02, 0.02), 0.0, 0.2, emit=(1, 0.05, 0.02))}
    o = build_body(body, p)
    classify(o, p, M)
    bpy.context.view_layer.objects.active = o
    dm = o.modifiers.new("dec", "DECIMATE"); dm.decimate_type = "DISSOLVE"; dm.angle_limit = math.radians(0.6); dm.delimit = {"MATERIAL", "SHARP"}
    bpy.ops.object.modifier_apply(modifier="dec")
    tr = o.modifiers.new("tri", "TRIANGULATE"); bpy.ops.object.modifier_apply(modifier="tri")
    tris = len(o.data.polygons)
    if tris > 99999:
        dm = o.modifiers.new("dec2", "DECIMATE"); dm.ratio = 5200 / tris
        bpy.ops.object.modifier_apply(modifier="dec2")
    parts = details(o, p, M)
    bpy.ops.object.select_all(action="DESELECT")
    for q in parts + [o]: q.select_set(True)
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.join()
    bpy.ops.object.shade_auto_smooth(angle=math.radians(40))
    o.name = "car_" + body
    tris = sum(len(f.vertices) - 2 for f in o.data.polygons)
    bpy.ops.export_scene.gltf(filepath="%s/car_%s.glb" % (OUT, body), export_format="GLB")
    print("built car_%s %d tris" % (body, tris))

if __name__ == "__main__":
    for b in (ONLY or TYPES.keys()):
        build(b)
