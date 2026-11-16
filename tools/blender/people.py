"""Blender (bpy) realistic people for GLASS CITY, built from the MakeHuman CC0 base mesh (tools/blender/mh/).
For each body variant (gender x ethnicity, + build): apply the MakeHuman targets, repose the A-pose arms down to the
sides with the real rig's skin weights (linear blend), drop the elbows a touch, convert to metres / Godot facing,
decimate (keeping the face dense) and tag every vertex for the animation shader:
  UV2 = (part + (1 - weight) * 0.9, joint height)  part 0 body, 1/2 legs, 3/4 arms (weighted near hips/shoulders)
  UV  = (bend weight, bend joint height)            knees / elbows
Faces carry region materials (head, scalp, jaw, lips, neck, chest, hips, upperarm, forearm, hand, thigh, shin, foot)
that scripts/humans.gd dresses: skin, or clothing pushed out along the normals in that person's colours. Extra
meshes: eyes (white/iris/pupil), brows, hair drape / bun / cap brim, skirt, shoe soles.
usage: bpyenv/bin/python tools/blender/people.py OUTDIR [variant ...]"""
import sys, os, json, gzip, math
import numpy as np
import bpy, bmesh
from mathutils import Vector, Matrix
from mathutils.kdtree import KDTree

OUT = sys.argv[1]; ONLY = sys.argv[2:]
D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mh")
VARIANTS = {
    "m1": {"caucasian-male-young": 1.0}, "m2": {"african-male-young": 1.0}, "m3": {"asian-male-young": 1.0},
    "m4": {"caucasian-male-young": 0.5, "african-male-young": 0.5, "universal-male-young-averagemuscle-maxweight": 0.55},
    "f1": {"caucasian-female-young": 1.0}, "f2": {"african-female-young": 1.0}, "f3": {"asian-female-young": 1.0},
    "f4": {"caucasian-female-young": 0.5, "asian-female-young": 0.5, "universal-female-young-averagemuscle-maxweight": 0.45},
}

HEIGHT = {"m1": 1.77, "m2": 1.8, "m3": 1.72, "m4": 1.76, "f1": 1.65, "f2": 1.67, "f3": 1.6, "f4": 1.63}

# ---------------------------------------------------------------- MakeHuman data
def load_obj():
    V = []; F = []
    cur = None
    for line in open(os.path.join(D, "base.obj")):
        if line.startswith("v "): V.append([float(x) for x in line.split()[1:4]])
        elif line.startswith("g "): cur = line.split()[1]
        elif line.startswith("f "):
            F.append((cur, [int(t.split("/")[0]) - 1 for t in line.split()[1:]]))
    return np.array(V), F

def apply_targets(V, mix):
    V = V.copy()
    for name, w in mix.items():
        for line in gzip.open(os.path.join(D, name + ".target.gz"), "rt"):
            if not line.strip() or line[0] == "#": continue
            a = line.split(); i = int(a[0])
            V[i] += w * np.array([float(a[1]), float(a[2]), float(a[3])])
    return V

def to_game(V):
    """MakeHuman OBJ (Y up, decimetres, facing +Z) -> Blender metres, Z up, facing +Y (= Godot -Z)."""
    return np.stack([-V[:, 0], V[:, 2], V[:, 1]], axis=1) * 0.1

BONESETS = {
    "head": ("head", "jaw", "eye", "oculi", "orbicularis", "oris", "risorius", "levator", "temporalis", "special", "tongue"),
    "neck": ("neck",), "torso": ("spine", "breast", "clavicle", "shoulder01", "root", "pelvis"),
    "upperarm": ("upperarm",), "forearm": ("lowerarm",), "hand": ("wrist", "metacarpal", "finger"),
    "thigh": ("upperleg",), "shin": ("lowerleg",), "foot": ("foot", "toe")}

def weights(N):
    W = json.load(open(os.path.join(D, "weights.json")))["weights"]
    cat = {k: np.zeros(N) for k in BONESETS}
    side = {s: {k: np.zeros(N) for k in ("arm", "fore", "leg", "shin")} for s in "LR"}
    for bone, lst in W.items():
        b = bone.split(".")[0]
        c = next((k for k, pre in BONESETS.items() if b.startswith(pre)), "torso")
        s = bone[-1] if bone.endswith((".L", ".R")) else None
        for vi, w in lst:
            if vi >= N: continue
            cat[c][vi] += w
            if s:
                if c in ("upperarm", "forearm", "hand"): side[s]["arm"][vi] += w
                if b == "shoulder01": side[s]["arm"][vi] += 0.4 * w
                if c in ("forearm", "hand"): side[s]["fore"][vi] += w
                if c in ("thigh", "shin", "foot"): side[s]["leg"][vi] += w
                if c in ("shin", "foot"): side[s]["shin"][vi] += w
    return cat, side

def rot_about(P, pivot, axis, ang, wgt):
    R = np.array(Matrix.Rotation(ang, 3, axis))
    moved = (P - pivot) @ R.T + pivot
    return P + (moved - P) * wgt[:, None]

# ---------------------------------------------------------------- build
def mat(name, col):
    m = bpy.data.materials.get(name)
    if m is None:
        m = bpy.data.materials.new(name); m.use_nodes = True
        m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (*col, 1)
    return m

COLS = {"head": (0.8, 0.6, 0.5), "scalp": (0.3, 0.2, 0.1), "jaw": (0.75, 0.55, 0.45), "lips": (0.6, 0.3, 0.3),
        "neck": (0.8, 0.6, 0.5), "chest": (0.2, 0.3, 0.6), "hips": (0.15, 0.15, 0.3), "upperarm": (0.25, 0.35, 0.65),
        "forearm": (0.8, 0.6, 0.5), "hand": (0.8, 0.6, 0.5), "thigh": (0.15, 0.15, 0.3), "shin": (0.15, 0.15, 0.35),
        "foot": (0.1, 0.1, 0.1), "eye_white": (0.9, 0.9, 0.88), "iris": (0.3, 0.2, 0.1), "pupil": (0.02, 0.02, 0.02),
        "brow": (0.2, 0.15, 0.1), "hair": (0.25, 0.18, 0.1), "cap": (0.2, 0.2, 0.6), "skirt": (0.5, 0.2, 0.3), "sole": (0.9, 0.9, 0.88)}

def make_obj(name, verts, faces, mats, face_mat):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], [tuple(f) for f in faces])
    for m in mats: me.materials.append(mat(m, COLS.get(m, (0.5, 0.5, 0.5))))
    for i, p in enumerate(me.polygons): p.material_index = mats.index(face_mat[i])
    o = bpy.data.objects.new(name, me); bpy.context.collection.objects.link(o)
    return o

def set_attrs(o, uv_fn, uv2_fn):
    me = o.data
    a = me.uv_layers.new(name="UVMap"); b = me.uv_layers.new(name="UV2")
    for poly in me.polygons:
        for li in poly.loop_indices:
            vi = me.loops[li].vertex_index
            a.data[li].uv = uv_fn(vi); b.data[li].uv = uv2_fn(vi)

def build(var):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    V0, F = load_obj()
    V = apply_targets(V0, VARIANTS[var])
    groups = {}
    for g, f in F: groups.setdefault(g, set()).update(f)
    P = to_game(V)
    body_ids = np.array(sorted(groups["body"]))
    N = int(body_ids.max()) + 1
    floor = P[body_ids, 2].min(); P[:, 2] -= floor
    P *= HEIGHT[var] / P[body_ids, 2].max()       # normalise stature (the game varies it per person)
    J = {g: P[list(groups[g])].mean(axis=0) for g in groups if g.startswith("joint-")}
    cat, side = weights(N)
    # --- arms down to the sides, elbows a touch forward (blend-skinned with the rig's weights)
    for s, jl in (("L", "l"), ("R", "r")):
        sh, el = J["joint-%s-shoulder" % jl], J["joint-%s-elbow" % jl]
        d = el - sh
        cur = math.atan2(abs(d[0]), -d[2]); target = math.radians(9.0)
        sgn = 1.0 if d[0] > 0 else -1.0
        ang = sgn * (cur - target)            # rotate about +Y (forward axis) toward the body
        Pb = P[:N].copy()
        Pb = rot_about(Pb, sh, "Y", ang, np.clip(side[s]["arm"], 0, 1))
        el2 = (Matrix.Rotation(ang, 3, "Y") @ Vector(el - sh)) + Vector(sh)
        Pb = rot_about(Pb, np.array(el2), "X", math.radians(11), np.clip(side[s]["fore"], 0, 1))
        P[:N] = Pb
        J["joint-%s-elbow" % jl] = np.array(el2)
    hipz = (J["joint-l-upper-leg"][2] + J["joint-r-upper-leg"][2]) * 0.5
    kneez = (J["joint-l-knee"][2] + J["joint-r-knee"][2]) * 0.5
    shz = (J["joint-l-shoulder"][2] + J["joint-r-shoulder"][2]) * 0.5
    elz = (J["joint-l-elbow"][2] + J["joint-r-elbow"][2]) * 0.5
    eyez = J["joint-l-eye"][2]
    # --- regions per original vertex
    cats = list(BONESETS.keys())
    C = np.stack([cat[k] for k in cats], axis=1)
    region = [cats[i] for i in C.argmax(axis=1)]
    nrm_fwd = None
    for i in range(N):
        r = region[i]; p = P[i]
        if r == "torso": region[i] = "hips" if p[2] < hipz + 0.14 else "chest"
        if r == "head":
            jaw = cat["head"][i] > 0 and p[2] < J["joint-head"][2] - 0.015 and p[1] > J["joint-head"][1] - 0.02
            if p[2] > eyez + 0.045 or (p[2] > eyez - 0.02 and p[1] < J["joint-head"][1] - 0.035): region[i] = "scalp"
            elif jaw and p[2] < eyez - 0.075: region[i] = "jaw"
            else: region[i] = "head"
    # lips: a small band in front of the mouth
    mouth = np.array([0.0, P[body_ids, 1].max(), eyez - 0.085])
    # --- body mesh
    faces = [f for g, f in F if g == "body"]
    fm = []
    for f in faces:
        rs = [region[v] for v in f]
        fm.append(max(set(rs), key=rs.count))
    regions = sorted(set(fm) | {"lips"})
    body = make_obj("body", P[:N], faces, regions, fm)
    # mouth band -> lips (front-most faces near the mouth height)
    front = max(P[v][1] for v in range(N) if abs(P[v][0]) < 0.02 and abs(P[v][2] - mouth[2]) < 0.03)
    for poly in body.data.polygons:
        c = poly.center
        if abs(c.x) < 0.024 and abs(c.z - (eyez - 0.088)) < 0.011 and c.y > front - 0.012: poly.material_index = regions.index("lips")
    # --- decimate (face stays dense)
    vg = body.vertex_groups.new(name="dec")
    for i in range(N):
        vg.add([i], 0.08 if region[i] in ("head", "lips", "jaw") else 1.0, "REPLACE")
    bpy.context.view_layer.objects.active = body; body.select_set(True)
    dm = body.modifiers.new("dec", "DECIMATE"); dm.ratio = 0.17; dm.vertex_group = "dec"; dm.vertex_group_factor = 1.0
    dm.use_collapse_triangulate = True
    bpy.ops.object.modifier_apply(modifier="dec")
    # --- shader tags from the nearest original vertex
    kd = KDTree(N)
    for i in range(N): kd.insert(P[i], i)
    kd.balance()
    near = [kd.find(v.co)[1] for v in body.data.vertices]
    def tag(vi):
        o = near[vi]; x = P[o][0]
        s = "L" if x < 0 else "R"
        lw = min(1.0, side[s]["leg"][o]); aw = min(1.0, side[s]["arm"][o])
        if lw > 0.02: return (1 if x < 0 else 2), lw, hipz, min(1.0, side[s]["shin"][o]), kneez
        if aw > 0.02: return (3 if x < 0 else 4), aw, shz, min(1.0, side[s]["fore"][o]), elz
        return 0, 1.0, 0.0, 0.0, 0.0
    tags = [tag(i) for i in range(len(body.data.vertices))]
    set_attrs(body, lambda i: (tags[i][3], tags[i][4]), lambda i: (tags[i][0] + (1.0 - tags[i][1]) * 0.9 if tags[i][0] else 0.0, tags[i][2]))
    bpy.ops.object.shade_smooth()
    cloth_shell(body, regions)
    shoes(body, P, groups, hipz, kneez)
    extras(P, F, groups, J, eyez, hipz, kneez, var)
    bpy.ops.export_scene.gltf(filepath="%s/person_%s.glb" % (OUT, var), export_format="GLB", export_attributes=True)
    tri = sum(len(p.vertices) - 2 for o in bpy.context.scene.objects if o.type == "MESH" for p in o.data.polygons)
    h = P[body_ids, 2].max()
    bt = sum(len(p.vertices) - 2 for p in body.data.polygons)
    print("body %d tris" % bt)
    print("built person_%s: %d tris, height %.2f m, hip %.2f shoulder %.2f" % (var, tri, h, hipz, shz))

CLOTH = ("chest", "upperarm", "forearm", "hips", "thigh", "shin")

def cloth_shell(body, regions):
    """garment surface: the clothed regions smoothed (no muscle or bone detail showing through), pushed out a little."""
    o = body.copy(); o.data = body.data.copy(); o.name = "cloth"; bpy.context.collection.objects.link(o)
    bpy.context.view_layer.objects.active = o
    ls = o.modifiers.new("ls", "LAPLACIANSMOOTH"); ls.iterations = 3; ls.lambda_factor = 0.35; ls.use_volume_preserve = True
    ls.use_x = ls.use_y = ls.use_z = True
    bpy.ops.object.modifier_apply(modifier="ls")
    dp = o.modifiers.new("dp", "DISPLACE"); dp.strength = 0.007; dp.mid_level = 0.0; dp.direction = "NORMAL"
    bpy.ops.object.modifier_apply(modifier="dp")
    keep = {regions.index(r) for r in CLOTH if r in regions}
    bm = bmesh.new(); bm.from_mesh(o.data)
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.material_index not in keep], context="FACES")
    bm.to_mesh(o.data); bm.free()
    bpy.ops.object.shade_smooth()

def shoes(body, P, groups, hipz, kneez):
    """a sneaker per foot: the convex hull of the foot below the ankle, smoothed, with a contrasting sole."""
    ids = list(groups["body"])
    for sx, part in ((-1, 1), (1, 2)):
        pts = [Vector(P[v]) for v in ids if P[v][2] < 0.105 and P[v][0] * sx > 0.02]
        if len(pts) < 4: continue
        bm = bmesh.new()
        for q in pts: bm.verts.new(q)
        bmesh.ops.convex_hull(bm, input=bm.verts)
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
        me = bpy.data.meshes.new("shoe"); bm.to_mesh(me); bm.free()
        o = bpy.data.objects.new("shoe_%d" % part, me); bpy.context.collection.objects.link(o)
        bpy.context.view_layer.objects.active = o
        rm = o.modifiers.new("r", "REMESH"); rm.mode = "SMOOTH"; rm.octree_depth = 5; rm.scale = 0.9
        bpy.ops.object.modifier_apply(modifier="r")
        ls = o.modifiers.new("ls", "LAPLACIANSMOOTH"); ls.iterations = 4; ls.lambda_factor = 0.6; ls.use_volume_preserve = True
        bpy.ops.object.modifier_apply(modifier="ls")
        dp = o.modifiers.new("dp", "DISPLACE"); dp.strength = 0.009; dp.mid_level = 0.0; dp.direction = "NORMAL"
        bpy.ops.object.modifier_apply(modifier="dp")
        dc = o.modifiers.new("dc", "DECIMATE"); dc.ratio = min(1.0, 500.0 / max(1, len(o.data.polygons)))
        bpy.ops.object.modifier_apply(modifier="dc")
        o.data.materials.append(mat("shoe", (0.1, 0.1, 0.1))); o.data.materials.append(mat("sole", COLS["sole"]))
        for poly in o.data.polygons:
            if poly.center.z < 0.022: poly.material_index = 1
        for v in o.data.vertices:
            if v.co.z < 0.0: v.co.z = 0.0
        bpy.ops.object.shade_smooth()
        set_attrs(o, lambda i: (1.0, kneez), lambda i, part=part: (float(part), hipz))

def helper(name, P, F, gname, region_fn=None, default="hair", sub=0):
    fs = [f for g, f in F if g == gname]
    if not fs: return None
    ids = sorted({v for f in fs for v in f}); m = {v: i for i, v in enumerate(ids)}
    verts = [P[v] for v in ids]; faces = [[m[v] for v in f] for f in fs]
    fm = [default] * len(faces)
    o = make_obj(name, verts, faces, [default], fm)
    if sub:
        bpy.context.view_layer.objects.active = o
        sd = o.modifiers.new("s", "SUBSURF"); sd.levels = sub; bpy.ops.object.modifier_apply(modifier="s")
    return o

def tag_static(o):
    set_attrs(o, lambda i: (0.0, 0.0), lambda i: (0.0, 0.0))

def extras(P, F, groups, J, eyez, hipz, kneez, var):
    # eyes: the base mesh's eyeball helpers, iris and pupil by facing
    for g, nm in (("helper-l-eye", "eye_l"), ("helper-r-eye", "eye_r")):
        o = helper(nm, P, F, g, default="eye_white", sub=1)
        for mn in ("iris", "pupil"): o.data.materials.append(mat(mn, COLS[mn]))
        c = Vector(P[list(groups[g])].mean(axis=0))
        for poly in o.data.polygons:
            d = (poly.center - c).normalized()
            poly.material_index = 2 if d.y > 0.94 else (1 if d.y > 0.8 else 0)
        tag_static(o)
    # brows: short ribbons over each eye, laid on the face
    for sx, nm in ((-1, "brow_l"), (1, "brow_r")):
        e = J["joint-%s-eye" % ("l" if sx < 0 else "r")]
        pts = []
        for k in range(6):
            t = k / 5.0
            x = e[0] + sx * (-0.012 + t * 0.042) * (1 if sx > 0 else 1)
            pts.append((x, e[2] + 0.021 + math.sin(t * math.pi) * 0.004 - t * 0.002))
        verts = []; faces = []
        bodyfront = P[list(groups["body"])]
        for x, z in pts:
            sel = bodyfront[(np.abs(bodyfront[:, 0] - x) < 0.006) & (np.abs(bodyfront[:, 2] - z) < 0.006)]
            y = sel[:, 1].max() + 0.0015 if len(sel) else e[1] + 0.02
            verts += [(x, y, z - 0.0035), (x, y + 0.0005, z + 0.0035)]
        for k in range(5): faces.append([k * 2, k * 2 + 2, k * 2 + 3, k * 2 + 1])
        o = make_obj(nm, verts, faces, ["brow"], ["brow"] * len(faces)); tag_static(o)
    # skirt (dress) from the base mesh's skirt helper
    o = helper("skirt", P, F, "helper-skirt", default="skirt", sub=1)
    if o: tag_static(o)
    head = J["joint-head"]; top = P[list(groups["body"]), 2].max()
    # long hair drape: a curved sheet behind the head down to the shoulders
    verts = []; faces = []
    rows, cols = 7, 9
    for r in range(rows):
        z = top - 0.06 - r * (0.3 / (rows - 1))
        rad = 0.105 + 0.01 * r / rows
        for c in range(cols):
            a = math.pi * (0.12 + 0.76 * c / (cols - 1))     # around the back of the head
            verts.append((math.cos(a) * rad, head[1] - math.sin(a) * rad * 1.05 + 0.01, z))
    for r in range(rows - 1):
        for c in range(cols - 1):
            i = r * cols + c; faces.append([i, i + 1, i + cols + 1, i + cols])
    o = make_obj("hair_long", verts, faces, ["hair"], ["hair"] * len(faces))
    bpy.context.view_layer.objects.active = o
    so = o.modifiers.new("t", "SOLIDIFY"); so.thickness = 0.03; bpy.ops.object.modifier_apply(modifier="t")
    sd = o.modifiers.new("s", "SUBSURF"); sd.levels = 1; bpy.ops.object.modifier_apply(modifier="s")
    tag_static(o)
    # bun
    bpy.ops.mesh.primitive_uv_sphere_add(segments=14, ring_count=8, radius=0.055, location=(0, head[1] - 0.11, top - 0.05))
    o = bpy.context.active_object; o.name = "hair_bun"; o.data.materials.append(mat("hair", COLS["hair"])); tag_static(o)
    # cap brim
    bpy.ops.mesh.primitive_cylinder_add(vertices=20, radius=0.1, depth=0.012, location=(0, head[1] + 0.13, top - 0.045))
    o = bpy.context.active_object; o.name = "cap_brim"; o.scale = (0.9, 0.75, 1)
    bm = bmesh.new(); bm.from_mesh(o.data)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.co.y < -0.02], context="VERTS"); bm.to_mesh(o.data); bm.free()
    o.rotation_euler = (math.radians(-8), 0, 0)
    o.data.materials.append(mat("cap", COLS["cap"])); bpy.ops.object.transform_apply(location=False, rotation=True, scale=True); tag_static(o)
    # (the bend weight 1 with joint height 0 keeps the sole flat under the knee bend's foot)

for v in (ONLY or VARIANTS.keys()):
    build(v)
