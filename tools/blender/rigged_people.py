"""Blender (bpy): skinned, skeletal-animated people for GLASS CITY (and the Unreal port).

Body: MakeHuman CC0 base mesh + ethnicity/gender targets (tools/blender/mh), skinned to the MPFB2 'game_engine'
rig (CC0) - 53 bones named like the Unreal mannequin (pelvis, spine_01..03, thigh_l, calf_l, upperarm_l, ...), so
the same files retarget straight onto UE5's Manny/Quinn.
Animation: CMU Graphics Lab motion capture (cgspeed BVH conversion; free for any use), retargeted per bone:
target_world = swing(bone axis -> mocap segment direction) * mocap_global_rotation * target_rest. Locomotion
clips are cut to a single seamless gait cycle (best-matching frame pair) and played in place; the game moves the
character, and each clip records its real ground speed (custom property 'speed' -> glTF extras).

Materials (tinted per person in scripts/humans.gd): skin, hair, shirt, sleeve (forearm), pants, shin, shoes,
eye_white, iris.
usage: bpyenv/bin/python tools/blender/rigged_people.py OUTDIR BVHDIR RIG.json WEIGHTS.json [variant ...]"""
import sys, os, json, gzip, math
import numpy as np
import bpy, bmesh
from mathutils import Vector, Matrix, Quaternion
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bvh_fk

OUT, BVH, RIGF, WF = sys.argv[1:5]; ONLY = sys.argv[5:]
D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mh")
VARIANTS = {
    "m1": {"caucasian-male-young": 1.0}, "m2": {"african-male-young": 1.0}, "m3": {"asian-male-young": 1.0},
    "m4": {"caucasian-male-young": 0.5, "african-male-young": 0.5, "universal-male-young-averagemuscle-maxweight": 0.55},
    "f1": {"caucasian-female-young": 1.0}, "f2": {"african-female-young": 1.0}, "f3": {"asian-female-young": 1.0},
    "f4": {"caucasian-female-young": 0.5, "asian-female-young": 0.5, "universal-female-young-averagemuscle-maxweight": 0.45},
}
HEIGHT = {"m1": 1.77, "m2": 1.8, "m3": 1.72, "m4": 1.76, "f1": 1.65, "f2": 1.67, "f3": 1.6, "f4": 1.63}
FPS = 30

# name, bvh, mode, window (seconds or None), extra
CLIPS = [
    ("idle", "82_08", "loop", (1.0, 8.5), {"period": (2.5, 4.5)}),
    ("walk", "07_01", "loop", None, {"period": (0.9, 1.4)}),
    ("walk_fast", "07_12", "loop", None, {"period": (0.8, 1.3)}),
    ("jog", "02_03", "loop", None, {"period": (0.55, 0.9)}),
    ("run", "09_02", "loop", None, {"period": (0.5, 0.85)}),
    ("sprint", "09_10", "loop", None, {"period": (0.5, 0.85)}),
    ("crouch_walk", "77_14", "loop", None, {"period": (0.9, 1.8)}),
    ("limp", "77_19", "loop", None, {"period": (1.0, 2.0)}),
    ("carry_walk", "70_10", "loop", None, {"period": (0.9, 1.4)}),
    ("jump", "16_05", "jump", None, {}),
    ("punch", "02_05", "strike", None, {"joint": "RightHand", "pre": 0.35, "post": 0.45}),
    ("punch_l", "02_05", "strike", None, {"joint": "LeftHand", "pre": 0.35, "post": 0.45}),
    ("kick", "74_03", "strike", None, {"joint": "RightFoot", "pre": 0.5, "post": 0.6}),
    ("aim", "79_96", "hold", None, {"joint": "RightHand"}),
    ("wave", "13_26", "window", (1.0, 3.5), {}),
    ("sit", "13_01", "lowhold", None, {}),
    ("get_up", "77_16", "rise", None, {}),
]

# target bone -> (mocap joint whose global rotation drives it, mocap joint the bone points at)
MAP = {
    "pelvis": ("Hips", None), "spine_01": ("LowerBack", None), "spine_02": ("Spine", None),
    "spine_03": ("Spine1", None), "neck_01": ("Neck", None), "head": ("Head", None),
    "clavicle_l": ("LeftShoulder", "LeftArm"), "upperarm_l": ("LeftArm", "LeftForeArm"),
    "lowerarm_l": ("LeftForeArm", "LeftHand"), "hand_l": ("LeftHand", "LeftFingerBase"),
    "clavicle_r": ("RightShoulder", "RightArm"), "upperarm_r": ("RightArm", "RightForeArm"),
    "lowerarm_r": ("RightForeArm", "RightHand"), "hand_r": ("RightHand", "RightFingerBase"),
    "thigh_l": ("LeftUpLeg", "LeftLeg"), "calf_l": ("LeftLeg", "LeftFoot"), "foot_l": ("LeftFoot", "LeftToeBase"),
    "ball_l": ("LeftToeBase", "LeftToeBase_end"),
    "thigh_r": ("RightUpLeg", "RightLeg"), "calf_r": ("RightLeg", "RightFoot"), "foot_r": ("RightFoot", "RightToeBase"),
    "ball_r": ("RightToeBase", "RightToeBase_end"),
}

# ---------------------------------------------------------------- MakeHuman body
def load_obj():
    V = []; F = []; cur = None
    for line in open(os.path.join(D, "base.obj")):
        if line.startswith("v "): V.append([float(x) for x in line.split()[1:4]])
        elif line.startswith("g "): cur = line.split()[1]
        elif line.startswith("f "): F.append((cur, [int(t.split("/")[0]) - 1 for t in line.split()[1:]]))
    return np.array(V), F

def apply_targets(V, mix):
    V = V.copy()
    for name, w in mix.items():
        for line in gzip.open(os.path.join(D, name + ".target.gz"), "rt"):
            if not line.strip() or line[0] == "#": continue
            a = line.split(); V[int(a[0])] += w * np.array([float(a[1]), float(a[2]), float(a[3])])
    return V

def to_blender(V):
    """MakeHuman OBJ (Y up, decimetres, facing +Z) -> metres, Z up, facing +Y (= Godot -Z)."""
    return np.stack([-V[:, 0], V[:, 2], V[:, 1]], axis=1) * 0.1

COLS = {"skin": (0.78, 0.58, 0.47), "hair": (0.2, 0.14, 0.09), "shirt": (0.25, 0.35, 0.6), "sleeve": (0.25, 0.35, 0.6),
        "pants": (0.15, 0.17, 0.25), "shin": (0.15, 0.17, 0.25), "shoes": (0.08, 0.08, 0.08), "eye_white": (0.9, 0.9, 0.88),
        "iris": (0.25, 0.17, 0.1), "lips": (0.6, 0.35, 0.33)}

def mat(name):
    m = bpy.data.materials.get(name)
    if m is None:
        m = bpy.data.materials.new(name); m.use_nodes = True
        b = m.node_tree.nodes["Principled BSDF"]
        b.inputs["Base Color"].default_value = (*COLS[name], 1); b.inputs["Roughness"].default_value = 0.6 if name != "eye_white" else 0.15
    return m

REGION_OF = [("head", "skin"), ("neck_01", "skin"), ("spine", "shirt"), ("clavicle", "shirt"), ("pelvis", "pants"),
             ("upperarm", "shirt"), ("lowerarm", "sleeve"), ("hand", "skin"), ("thumb", "skin"), ("index", "skin"),
             ("middle", "skin"), ("ring", "skin"), ("pinky", "skin"), ("thigh", "pants"), ("calf", "shin"),
             ("foot", "shoes"), ("ball", "shoes"), ("Root", "pants")]

def build_body(var, rig, W):
    V0, F = load_obj()
    V = apply_targets(V0, VARIANTS[var])
    groups = {}
    for g, f in F: groups.setdefault(g, set()).update(f)
    P = to_blender(V)
    body_ids = np.array(sorted(groups["body"])); N = int(body_ids.max()) + 1
    P[:, 2] -= P[body_ids, 2].min()
    P *= HEIGHT[var] / P[body_ids, 2].max()
    J = {g: P[list(groups[g])].mean(axis=0) for g in groups if g.startswith("joint-")}
    # ---- per-vertex dominant bone -> material region
    wsum = {}
    for bone, lst in W.items():
        for vi, w in lst:
            if vi < N and w > wsum.get(vi, (None, 0))[1]: wsum[vi] = (bone, w)
    def region(vi):
        b = wsum.get(vi, ("spine_01", 1))[0]
        for pre, r in REGION_OF:
            if b.startswith(pre): return r
        return "shirt"
    reg = [region(i) for i in range(N)]
    eyez = J["joint-l-eye"][2]; headj = J["joint-head"]
    for i in range(N):
        if reg[i] == "skin" and wsum.get(i, ("", 0))[0] == "head":
            p = P[i]
            if p[2] > eyez + 0.045 or (p[2] > eyez - 0.02 and p[1] < headj[1] - 0.035): reg[i] = "hair"
        if reg[i] == "shirt" and P[i][2] < J["joint-pelvis"][2] + 0.1: reg[i] = "pants"
    # clothes sit a few mm proud of the skin
    nrm = np.zeros_like(P[:N])
    faces = [f for g, f in F if g == "body"]
    for f in faces:
        a, b, c = P[f[0]], P[f[1]], P[f[2]]; n = np.cross(b - a, c - a)
        for v in f: nrm[v] += n
    nrm /= np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-9
    for i in range(N):
        if reg[i] in ("shirt", "sleeve", "pants", "shin"): P[i] += nrm[i] * 0.006
        elif reg[i] == "shoes": P[i] += nrm[i] * 0.009
    mats = ["skin", "hair", "shirt", "sleeve", "pants", "shin", "shoes", "eye_white", "iris"]
    me = bpy.data.meshes.new("body")
    eye_faces = [f for g, f in F if g in ("helper-l-eye", "helper-r-eye")]
    allf = faces + eye_faces
    used = sorted({v for f in allf for v in f})
    remap = {v: k for k, v in enumerate(used)}
    me.from_pydata([tuple(P[v]) for v in used], [], [tuple(remap[v] for v in f) for f in allf])
    for m in mats: me.materials.append(mat(m))
    fwd = np.array([0, 1, 0])
    for k, poly in enumerate(me.polygons):
        if k < len(faces):
            rs = [reg[v] for v in allf[k]]; poly.material_index = mats.index(max(set(rs), key=rs.count))
        else:
            c = np.array(poly.center); side = J["joint-l-eye"] if c[0] < 0 else J["joint-r-eye"]
            d = c - side; d /= np.linalg.norm(d) + 1e-9
            poly.material_index = mats.index("iris" if d[1] > 0.88 else "eye_white")
    body = bpy.data.objects.new("body", me); bpy.context.collection.objects.link(body)
    # ---- skin weights
    vg = {}
    for bone, lst in W.items():
        g = body.vertex_groups.new(name=bone); vg[bone] = g
        for vi, w in lst:
            if vi in remap and vi < N: g.add([remap[vi]], w, "REPLACE")
    hg = vg.get("head") or body.vertex_groups.new(name="head")
    for v in used:
        if v >= N: hg.add([remap[v]], 1.0, "REPLACE")     # eyeballs ride the head
    # ---- decimate (face stays dense)
    dvg = body.vertex_groups.new(name="_dec")
    for v in used:
        dvg.add([remap[v]], 0.1 if (v >= N or wsum.get(v, ("", 0))[0] in ("head", "neck_01")) else 1.0, "REPLACE")
    bpy.context.view_layer.objects.active = body; body.select_set(True)
    dm = body.modifiers.new("dec", "DECIMATE"); dm.ratio = 0.35; dm.vertex_group = "_dec"; dm.vertex_group_factor = 1.0
    bpy.ops.object.modifier_apply(modifier="dec")
    if "_dec" in body.vertex_groups: body.vertex_groups.remove(body.vertex_groups["_dec"])
    bpy.ops.object.shade_smooth()
    return body, P, J

def joint_pos(spec, P, J):
    s = spec.get("strategy")
    if s == "CUBE": return J[spec["cube_name"]]
    if s == "MEAN": return P[spec["vertex_indices"]].mean(axis=0)
    if s == "VERTEX": return P[spec["vertex_index"]]
    return np.array(spec["default_position"])

def build_armature(rig, P, J):
    arm = bpy.data.armatures.new("Armature"); ob = bpy.data.objects.new("Armature", arm)
    bpy.context.collection.objects.link(ob); bpy.context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode="EDIT")
    eb = {}
    order = []
    def visit(n):
        if n in order: return
        p = rig[n]["parent"]
        if p: visit(p)
        order.append(n)
    for n in rig: visit(n)
    for n in order:
        b = arm.edit_bones.new(n); h = joint_pos(rig[n]["head"], P, J); t = joint_pos(rig[n]["tail"], P, J)
        if np.linalg.norm(t - h) < 1e-3: t = h + np.array([0, 0, 0.05])
        b.head = Vector(h); b.tail = Vector(t)
        d = (t - h) / np.linalg.norm(t - h)
        b.align_roll(Vector((0, 0, 1)) if abs(d[1]) > 0.8 else Vector((0, 1, 0)))
        if rig[n]["parent"]: b.parent = eb[rig[n]["parent"]]
        eb[n] = b
    bpy.ops.object.mode_set(mode="OBJECT")
    return ob, order

# ---------------------------------------------------------------- mocap retarget
C = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], float)     # BVH (Y up) -> Z up

def yaw(a):
    c, s = math.cos(a), math.sin(a); return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])

def swing(a, b):
    a = a / np.linalg.norm(a); b = b / np.linalg.norm(b)
    v = np.cross(a, b); c = float(np.dot(a, b))
    if c < -0.9999: return np.array(Matrix.Rotation(math.pi, 3, Vector(np.cross(a, [1, 0, 0]) if abs(a[0]) < 0.9 else np.cross(a, [0, 1, 0])).normalized()))
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx / (1 + c)

def load_clip(code):
    joints, vals, ft = bvh_fk.load(os.path.join(BVH, code + ".bvh"))
    pos, rot = bvh_fk.fk(joints, vals)
    I = bvh_fk.index(joints)
    pos = pos @ C.T; rot = C @ rot @ C.T                        # to Z up (global rotations conjugated)
    # rest facing: BVH rest pose faces +Z(bvh) -> -Y here; turn the whole thing so rest faces +Y
    A = yaw(math.pi)
    pos = pos @ A.T; rot = A @ rot @ A.T
    # resample to 30 fps
    n = len(pos); T = (n - 1) * ft; m = int(T * FPS) + 1
    idx = np.clip(np.round(np.arange(m) / FPS / ft).astype(int), 0, n - 1)
    return pos[idx], rot[idx], I

def heading(pos, I, f):
    l = pos[f, I["LeftUpLeg"]] - pos[f, I["RightUpLeg"]]; l[2] = 0
    fw = np.array([l[1], -l[0], 0.0])          # forward = left x up
    return math.atan2(fw[1], fw[0])

def pose_dist(pos, I, a, b):
    """pose difference between frames a and b, in each frame's own hips-relative heading-aligned space."""
    def norm(f):
        h = heading(pos, I, f); R = yaw(math.pi / 2 - h)
        return (pos[f] - pos[f, I["Hips"]]) @ R.T
    return float(np.abs(norm(a) - norm(b)).mean())

def pick(pos, rot, I, mode, win, extra):
    """choose frame range [a, b) for the clip."""
    n = len(pos)
    if win: a0, a1 = int(win[0] * FPS), min(n - 1, int(win[1] * FPS))
    else: a0, a1 = int(0.3 * FPS), n - 1
    if mode == "loop":
        lo, hi = int(extra["period"][0] * FPS), int(extra["period"][1] * FPS)
        best = None
        for a in range(a0, max(a0 + 1, a1 - hi), 2):
            for b in range(a + lo, min(a1, a + hi) + 1):
                d = pose_dist(pos, I, a, b)
                if best is None or d < best[0]: best = (d, a, b)
        return best[1], best[2], True
    if mode == "strike":
        j = I[extra["joint"]]
        sp = np.linalg.norm(np.diff(pos[:, j] - pos[:, I["Hips"]], axis=0), axis=1)
        sp[:a0] = 0
        f = int(np.argmax(sp)); return max(0, f - int(extra["pre"] * FPS)), min(n - 1, f + int(extra["post"] * FPS)), False
    if mode == "jump":
        z = pos[:, I["Hips"]][:, 2]; f = int(np.argmax(z[a0:])) + a0
        return max(0, f - int(0.7 * FPS)), min(n - 1, f + int(0.8 * FPS)), False
    if mode == "hold":      # arm-raised aim: 1 s around the highest hand
        z = pos[:, I[extra["joint"]], 2]; f = int(np.argmax(z))
        return max(0, f - 15), min(n - 1, f + 15), True
    if mode == "lowhold":   # seated: 2 s window at the lowest hips
        z = pos[:, I["Hips"], 2]; f = int(np.argmin(z[a0:])) + a0
        return max(0, f - 30), min(n - 1, f + 30), True
    if mode == "rise":      # from lying to standing: lowest hips -> first frame back near standing height
        z = pos[:, I["Hips"], 2]; lo_ = int(np.argmin(z)); top = z.max()
        up = next((k for k in range(lo_, n) if z[k] > 0.92 * top), n - 1)
        return lo_, min(n - 1, up + 10), False
    return a0, a1, False

CALIB = {}      # bone -> 3x3 right-multiplied correction so the 'stand still' frame of 82_08 maps to the rest pose
CAL_BONES = ("pelvis", "spine_01", "spine_02", "spine_03", "neck_01", "head", "clavicle_l", "clavicle_r")

def calibrate(ob, order):
    """average, over a whole normal walk (07_01), of each upper-body bone's offset to its rest pose -> correction.
    A walk averages out torso twist and head turns, so the result is 'upright, facing forward'."""
    CALIB.clear()
    pos, rot, I = load_clip("07_01")
    arm = ob.data
    frames = range(10, len(pos) - 10)
    for bn in CAL_BONES:
        R0 = np.array(arm.bones[bn].matrix_local)[:3, :3]
        qs = []
        for f in frames:
            h = heading(pos, I, f); H = yaw(math.pi / 2 - h)
            Rw = (H @ rot[f, I[MAP[bn][0]]] @ H.T) @ R0
            q = Matrix((Rw.T @ R0).tolist()).to_quaternion()
            if qs and q.dot(qs[0]) < 0: q.negate()
            qs.append(np.array(q))
        qm = np.mean(qs, axis=0); qm /= np.linalg.norm(qm)
        CALIB[bn] = np.array(Quaternion(qm).to_matrix())

def retarget(ob, order, code, mode, win, extra, name):
    pos, rot, I = load_clip(code)
    a, b, loop = pick(pos, rot, I, mode, win, extra)
    pos, rot = pos[a:b + 1], rot[a:b + 1]
    n = len(pos)
    # face +Y: undo the average heading over the clip
    hs = [heading(pos, I, f) for f in range(n)]
    h0 = math.atan2(np.mean(np.sin(hs)), np.mean(np.cos(hs)))
    H = yaw(math.pi / 2 - h0)
    pos = pos @ H.T; rot = H @ rot @ H.T
    # ground speed (in-place playback)
    hip = pos[:, I["Hips"]]
    travel = np.linalg.norm(hip[-1, :2] - hip[0, :2])
    # scale: mocap leg length -> character leg length
    arm = ob.data
    leg_t = (arm.bones["thigh_l"].head_local - arm.bones["foot_l"].head_local).length
    leg_s = np.linalg.norm(pos[0, I["LeftUpLeg"]] - pos[0, I["LeftLeg"]]) + np.linalg.norm(pos[0, I["LeftLeg"]] - pos[0, I["LeftFoot"]])
    k = leg_t / leg_s
    speed = travel * k / max(1e-6, (n - 1) / FPS)
    # ground the feet: lowest foot point over the clip sits on z=0
    foot_min = min(pos[:, I["LeftToeBase"], 2].min(), pos[:, I["RightToeBase"], 2].min(), pos[:, I["LeftFoot"], 2].min() - 0.0)
    act = bpy.data.actions.new(name); act.use_fake_user = True
    ob.animation_data_create(); ob.animation_data.action = act
    pb = ob.pose.bones
    rest = {bn: np.array(arm.bones[bn].matrix_local) for bn in order}
    for f in range(n):
        world = {}
        for bn in order:
            R0 = rest[bn][:3, :3]
            if bn in MAP:
                sj, dj = MAP[bn]
                Rw = rot[f, I[sj]] @ R0
                if bn in CALIB: Rw = Rw @ CALIB[bn]
                if dj and dj in I:
                    d = pos[f, I[dj]] - pos[f, I[sj]]
                    if np.linalg.norm(d) > 1e-6: Rw = swing(Rw[:, 1], d) @ Rw
            else:
                par = arm.bones[bn].parent
                if par is not None and par.name in world:
                    Rp = world[par.name][:3, :3]; Rp0 = rest[par.name][:3, :3]
                    Rw = Rp @ Rp0.T @ R0          # unmapped (fingers): follow the parent rigidly
                else: Rw = R0
            M = np.eye(4); M[:3, :3] = Rw
            par = arm.bones[bn].parent
            if par is None:
                M[:3, 3] = rest[bn][:3, 3]
            else:
                Mp = world[par.name]; rel = np.linalg.inv(rest[par.name]) @ rest[bn]
                M[:3, 3] = (Mp @ rel)[:3, 3]
            if bn == "pelvis":           # in place horizontally (the game moves the character), real height bob
                tr = hip[0] + (hip[-1] - hip[0]) * (f / max(1, n - 1))
                M[0, 3] = rest[bn][0, 3] + (hip[f, 0] - tr[0]) * k
                M[1, 3] = rest[bn][1, 3] + (hip[f, 1] - tr[1]) * k
                M[2, 3] = (hip[f, 2] - foot_min) * k
            world[bn] = M
            if par is None: basis = np.linalg.inv(rest[bn]) @ M
            else: basis = np.linalg.inv(np.linalg.inv(rest[par.name]) @ rest[bn]) @ np.linalg.inv(world[par.name]) @ M
            p = pb[bn]; mb = Matrix(basis.tolist())
            p.rotation_mode = "QUATERNION"
            p.rotation_quaternion = mb.to_quaternion()
            p.keyframe_insert("rotation_quaternion", frame=f + 1, group=bn)
            if bn == "pelvis":
                p.location = mb.to_translation(); p.keyframe_insert("location", frame=f + 1, group=bn)
    # seamless loop: last key = first key
    act["speed"] = float(speed); act["loop"] = bool(loop)
    ob.animation_data.action = None
    print("  clip %-12s %s frames %3d  %.2fs  speed %.2f m/s  loop %s" % (name, code, n, (n - 1) / FPS, speed, loop))

def build(var):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    rig = json.load(open(RIGF)); W = json.load(open(WF))["weights"]
    body, P, J = build_body(var, rig, W)
    ob, order = build_armature(rig, P, J)
    body.parent = ob
    md = body.modifiers.new("Armature", "ARMATURE"); md.object = ob
    calibrate(ob, order)
    for name, code, mode, win, extra in CLIPS:
        try: retarget(ob, order, code, mode, win, extra, name)
        except Exception as ex: print("  clip", name, "FAILED", ex)
    for o in bpy.context.scene.objects: o.select_set(True)
    bpy.ops.export_scene.gltf(filepath="%s/char_%s.glb" % (OUT, var), export_format="GLB", export_animations=True,
                              export_animation_mode="ACTIONS", export_extras=True, export_skins=True,
                              export_force_sampling=True, export_frame_range=False, export_anim_slide_to_zero=True)
    tri = sum(len(p.vertices) - 2 for p in body.data.polygons)
    print("built char_%s: %d tris, %d bones" % (var, tri, len(order)))

for v in (ONLY or VARIANTS.keys()):
    build(v)
