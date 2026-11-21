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
import bvh_fk, mhclo

if __name__ == "__main__":
    OUT, BVH, RIGF, WF = sys.argv[1:5]; ONLY = sys.argv[5:]
else:      # imported by charcreator/make_character.py for the mocap retarget (it sets BVH)
    OUT = RIGF = WF = None; BVH = os.environ.get("BVH_DIR", "/home/claude/dl/bvh"); ONLY = []
D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mh")
SYS = os.environ.get("MHSYS", "/home/claude/dl/mhpack/sys")     # MakeHuman system assets (CC0)
# body targets, skin, outfit, hair, shoes, eyebrows, eyes, height (m)
VARIANTS = {
    "m1": ({"caucasian-male-young": 1.0}, "young_caucasian_male", "male_casualsuit03", "short02", "shoes02", "eyebrow001", "brown", 1.78),
    "m2": ({"african-male-young": 1.0}, "young_african_male", "male_casualsuit05", "short04", "shoes05", "eyebrow003", "brown", 1.82),
    "m3": ({"asian-male-young": 1.0}, "young_asian_male", "male_casualsuit01", "short01", "shoes04", "eyebrow002", "brown", 1.72),
    "m4": ({"caucasian-male-young": 0.5, "african-male-young": 0.5, "universal-male-young-averagemuscle-maxweight": 0.55},
           "middleage_caucasian_male", "male_worksuit01", "short03", "shoes03", "eyebrow004", "bluegreen", 1.76),
    "m5": ({"caucasian-male-young": 1.0}, "young_caucasian_male2", "male_elegantsuit01", "short02", "shoes04", "eyebrow005", "blue", 1.8),
    "m6": ({"african-male-young": 0.8, "universal-male-young-averagemuscle-maxweight": 0.4}, "middleage_african_male",
           "male_casualsuit06", "short04", "shoes06", "eyebrow006", "brown", 1.77),
    "f1": ({"caucasian-female-young": 1.0}, "young_caucasian_female", "female_casualsuit01", "ponytail01", "shoes05", "eyebrow008", "blue", 1.66),
    "f2": ({"african-female-young": 1.0}, "young_african_female", "female_elegantsuit01", "bob02", "shoes04", "eyebrow009", "brown", 1.68),
    "f3": ({"asian-female-young": 1.0}, "young_asian_female", "female_sportsuit01", "bob01", "shoes06", "eyebrow010", "brown", 1.6),
    "f4": ({"caucasian-female-young": 0.5, "asian-female-young": 0.5, "universal-female-young-averagemuscle-maxweight": 0.45},
           "middleage_caucasian_female", "female_casualsuit02", "long01", "shoes05", "eyebrow011", "green", 1.63),
    "f5": ({"caucasian-female-young": 1.0}, "young_caucasian_female2", "female_casualsuit01", "braid01", "shoes02", "eyebrow008", "brownlight", 1.69),
    "f6": ({"african-female-young": 0.8, "universal-female-young-averagemuscle-maxweight": 0.35}, "middleage_african_female",
           "female_elegantsuit01", "afro01", "shoes01", "eyebrow012", "brown", 1.65),
}
LOGO_TEES = ("female_casualsuit01", "female_casualsuit02", "male_casualsuit02", "male_casualsuit04", "male_casualsuit06")
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

import tempfile
TMP = tempfile.mkdtemp()

def tex(path, size=1024, alpha=False, delogo=False):
    """downscale a MakeHuman texture (jpeg for opaque, png for alpha) and return the temp path"""
    import cv2
    im = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if im is None: return None
    if im.shape[0] > size: im = cv2.resize(im, (size, size), interpolation=cv2.INTER_AREA)
    if delogo:     # the MakeHuman logo printed on the system tees: paint it out from the surrounding fabric
        bgr = im[:, :, :3]
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        m = (((hsv[:, :, 0] < 28) | (hsv[:, :, 0] > 170)) & (hsv[:, :, 1] > 90) & (hsv[:, :, 2] > 90)).astype(np.uint8) * 255
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        n, lab, stats, _ = cv2.connectedComponentsWithStats(m)
        keep = np.zeros_like(m)
        for k in range(1, n):
            x, y, w, h, a = stats[k]
            if a > 60 and max(w, h) < size * 0.3: keep[lab == k] = 255
        keep = cv2.dilate(keep, np.ones((15, 15), np.uint8))
        im[:, :, :3] = cv2.inpaint(bgr, keep, 9, cv2.INPAINT_TELEA)
    base = os.path.basename(path).lower()
    if BULLY and not alpha and im.ndim == 3 and "normal" not in base:
        rgb = im[:, :, :3]
        if "skins" in path:      # painted skin: pores and blotches smoothed into soft tones
            rgb = cv2.edgePreservingFilter(rgb, flags=1, sigma_s=30, sigma_r=0.2)
        elif "eye" in base:      # irises keep their colour; the whites stop glowing
            rgb = (rgb.astype(np.float32) * 0.78).astype(np.uint8)
        else:                    # clothes: lighter pass, the fabric weave stays
            rgb = cv2.addWeighted(cv2.edgePreservingFilter(rgb, flags=1, sigma_s=12, sigma_r=0.12), 0.7, rgb, 0.3, 0)
        im = rgb if im.shape[2] == 3 else np.dstack([rgb, im[:, :, 3]])
    out = os.path.join(TMP, os.path.basename(path).rsplit(".", 1)[0] + ("_a.png" if alpha else ".jpg"))
    if alpha: cv2.imwrite(out, im)
    else: cv2.imwrite(out, im[:, :, :3] if im.ndim == 3 else im, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return out

def tex_mat(name, diffuse, normal=None, alpha=False, rough=0.7, delogo=False):
    m = bpy.data.materials.new(name)
    nt = m.node_tree if m.node_tree else None
    if nt is None:
        m.use_nodes = True; nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    b.inputs["Roughness"].default_value = rough
    if diffuse and os.path.exists(diffuse):
        t = nt.nodes.new("ShaderNodeTexImage"); t.image = bpy.data.images.load(tex(diffuse, alpha=alpha, delogo=delogo))
        nt.links.new(t.outputs["Color"], b.inputs["Base Color"])
        if alpha:
            nt.links.new(t.outputs["Alpha"], b.inputs["Alpha"])
            try: m.surface_render_method = "DITHERED"
            except Exception: pass
    if normal and os.path.exists(normal):
        t2 = nt.nodes.new("ShaderNodeTexImage"); t2.image = bpy.data.images.load(tex(normal, size=1024))
        t2.image.colorspace_settings.name = "Non-Color"
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nt.links.new(t2.outputs["Color"], nm.inputs["Color"]); nt.links.new(nm.outputs["Normal"], b.inputs["Normal"])
    return m

def load_base():
    V, T, F, G = [], [], [], []
    cur = None
    for line in open(os.path.join(D, "base.obj")):
        if line.startswith("v "): V.append([float(x) for x in line.split()[1:4]])
        elif line.startswith("vt "): T.append([float(x) for x in line.split()[1:3]])
        elif line.startswith("g "): cur = line.split()[1]
        elif line.startswith("f "):
            vs, ts = [], []
            for tok in line.split()[1:]:
                p_ = tok.split("/"); vs.append(int(p_[0]) - 1); ts.append(int(p_[1]) - 1)
            F.append((vs, ts)); G.append(cur)
    return np.array(V), np.array(T), F, G

def mesh_obj(name, verts, faces, uvs, mats):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], [tuple(f[0]) for f in faces])
    uvl = me.uv_layers.new(name="UVMap")
    li = 0
    for poly, f in zip(me.polygons, faces):
        for k, l in enumerate(poly.loop_indices):
            ti = f[1][k]
            if 0 <= ti < len(uvs): uvl.data[l].uv = tuple(uvs[ti])
    for m in mats: me.materials.append(m)
    o = bpy.data.objects.new(name, me); bpy.context.collection.objects.link(o)
    return o

# ---------------------------------------------------------------- Bully style (art direction 2026-11-21)
# Each person gets a caricatured face (a handful of MakeHuman face sliders pushed hard, seeded by the variant, so
# everyone looks distinct and readable from across the street), a slightly bigger head and bigger hands, painted
# skin (pores and photo noise smoothed into soft tones) and eyes that aren't bright white. BULLY=0 builds the
# earlier realistic people.
BULLY = os.environ.get("BULLY", "1") == "1"
FACE_T = os.environ.get("MH_FACE_TARGETS", "/home/claude/dl/mpfb_src/mpfb2/src/mpfb/data/targets")
FACE_SLIDERS = [("nose", ["nose-scale-horiz-incr", "nose-scale-horiz-decr", "nose-scale-vert-incr", "nose-point-width-incr",
                          "nose-hump-incr", "nose-trans-down", "nose-flaring-incr", "nose-scale-depth-incr"]),
                ("chin", ["chin-prominent-incr", "chin-width-incr", "chin-height-incr", "chin-jaw-drop-incr", "chin-cleft-incr"]),
                ("mouth", ["mouth-scale-horiz-incr", "mouth-lowerlip-volume-incr", "mouth-upperlip-volume-incr", "mouth-scale-horiz-decr"]),
                ("eyes", ["l-eye-scale-incr", "l-eye-trans-up", "l-eye-height2-decr", "l-eye-trans-in", "l-eye-trans-out"]),
                ("cheek", ["l-cheek-bones-incr", "l-cheek-volume-incr", "l-cheek-volume-decr"]),
                ("head", ["head-square", "head-oval", "head-round", "head-fat-incr", "head-invertedtriangular"]),
                ("brows", ["eyebrows-trans-down", "eyebrows-angle-up", "eyebrows-angle-down"]),
                ("ears", ["r-ear-scale-incr", "r-ear-flap-incr"])]

def _face_file(name):
    for sub in ("nose", "chin", "mouth", "eyes", "cheek", "head", "eyebrows", "ears", "forehead"):
        f = os.path.join(FACE_T, sub, name + ".target.gz")
        if os.path.exists(f): return f
    return None

def caricature(V, var):
    """push 5-7 face features hard (deterministic per variant); l-/r- sliders are applied to both sides"""
    import random
    rng = random.Random("glasscity-" + var)
    picks = []
    fams = FACE_SLIDERS[:]; rng.shuffle(fams)
    for fam, opts in fams[:rng.randint(5, 7)]:
        picks.append((rng.choice(opts), rng.uniform(0.45, 0.9)))
    V = V.copy()
    for name, w in picks:
        names = [name] + (["r-" + name[2:]] if name.startswith("l-") else ["l-" + name[2:]] if name.startswith("r-") else [])
        for n in names:
            f = _face_file(n)
            if not f: continue
            for line in gzip.open(f, "rt"):
                if not line.strip() or line[0] == "#": continue
                a = line.split(); V[int(a[0])] += w * np.array([float(a[1]), float(a[2]), float(a[3])])
    print("  caricature", var, [(n, round(w, 2)) for n, w in picks])
    return V

def scale_parts(V, groups, W, parts):
    """scale skin-weighted regions about a joint (MakeHuman space, before proxies are fitted so clothes, hair and
    eyes follow): parts = [(bones, joint group, factor)]"""
    V = V.copy()
    for bones, joint, k in parts:
        piv = V[list(groups[joint])].mean(axis=0)
        wv = np.zeros(len(V))
        for b in bones:
            for vi, w in W.get(b, []): wv[vi] += w
        wv = np.clip(wv, 0, 1)
        V += (V - piv) * ((k - 1.0) * wv)[:, None]
    return V

def build_body(var, rig, W):
    targets, skin, suit, hair, shoes, brows, eyes, H = VARIANTS[var]
    V0, UV, F, G = load_base()
    V = apply_targets(V0, targets)
    groups = {}
    for g, f in zip(G, F): groups.setdefault(g, set()).update(f[0])
    if BULLY:
        V = caricature(V, var)
        fingers = lambda sd: ["hand_" + sd] + ["%s_%02d_%s" % (f, i, sd) for f in ("thumb", "index", "middle", "ring", "pinky") for i in (1, 2, 3)]
        V = scale_parts(V, groups, W, [(["head"], "joint-head", 1.1), (fingers("l"), "joint-l-hand", 1.15), (fingers("r"), "joint-r-hand", 1.15)])
    body_ids = np.array(sorted(groups["body"])); N = int(body_ids.max()) + 1
    P0 = to_blender(V)
    floor = P0[body_ids, 2].min(); P0[:, 2] -= floor
    sc = H / P0[body_ids, 2].max()
    conv = lambda X: (to_blender(X) - np.array([0, 0, floor])) * sc
    P = conv(V)
    J = {g: P[list(groups[g])].mean(axis=0) for g in groups if g.startswith("joint-")}
    # per-vertex base weights
    bones = list(W.keys()); BW = {}
    for bi, bone in enumerate(bones):
        for vi, w in W[bone]: BW.setdefault(vi, []).append((bi, w))
    # proxies
    def clo_path(kind, name):
        for f in os.listdir(os.path.join(SYS, kind, name)):
            if f.endswith(".mhclo"): return os.path.join(SYS, kind, name, f)
    proxies = [("suit", "clothes", suit), ("shoes", "clothes", shoes), ("hair", "hair", hair), ("brows", "eyebrows", brows),
               ("lashes", "eyelashes", "eyelashes01"), ("eyes", "eyes", "high-poly")]
    clos = []
    delete = set()
    for role, kind, name in proxies:
        c = mhclo.load(clo_path(kind, name)); clos.append((role, name, c)); delete |= c["delete"]
    # ---- body (skin texture; faces hidden under clothes/shoes removed)
    sk = os.path.join(SYS, "skins", skin); dif = next((os.path.join(sk, f) for f in os.listdir(sk) if f.endswith(".png") and "thumb" not in f), None)
    skin_m = tex_mat("skin", dif, rough=0.55)
    faces = [f for g, f in zip(G, F) if g == "body" and not any(v in delete for v in f[0])]
    used = sorted({v for f in faces for v in f[0]}); remap = {v: k for k, v in enumerate(used)}
    body = mesh_obj("body", P[used], [([remap[v] for v in f[0]], f[1]) for f in faces], UV, [skin_m])
    for bone, lst in W.items():
        g = body.vertex_groups.new(name=bone)
        for vi, w in lst:
            if vi in remap: g.add([remap[vi]], w, "REPLACE")
    dvg = body.vertex_groups.new(name="_dec")
    head_bones = {bones.index(b) for b in ("head", "neck_01") if b in bones}
    for v in used:
        dense = any(bi in head_bones and w > 0.3 for bi, w in BW.get(v, []))
        dvg.add([remap[v]], 0.1 if dense else 1.0, "REPLACE")
    bpy.context.view_layer.objects.active = body; body.select_set(True)
    dm = body.modifiers.new("dec", "DECIMATE"); dm.ratio = 0.45; dm.vertex_group = "_dec"; dm.vertex_group_factor = 1.0
    bpy.ops.object.modifier_apply(modifier="dec")
    if "_dec" in body.vertex_groups: body.vertex_groups.remove(body.vertex_groups["_dec"])
    bpy.ops.object.shade_smooth()
    objs = [body]
    # ---- proxies: fitted, textured, skinned with the base weights blended from their 3 anchor vertices
    for role, name, c in clos:
        Vp = conv(mhclo.fit(c, V))
        _, UVp, Fp = mhclo.load_obj(c["obj"])
        mm = mhclo.material(c["material"])
        alpha = role in ("hair", "brows", "lashes")
        m = tex_mat(("a_" if alpha else ("eyes" if role == "eyes" else "cloth_")) + (role if alpha or role == "eyes" else name),
                    mm["diffuse"], mm["normal"], alpha=alpha, rough=0.45 if role == "hair" else 0.8, delogo=(name in LOGO_TEES))
        o = mesh_obj(role, Vp, Fp, UVp, [m])
        acc = [dict() for _ in range(len(Vp))]
        for i in range(len(Vp)):
            for k in range(3):
                wk = c["w"][i, k]
                if wk <= 0: continue
                for bi, w in BW.get(int(c["refs"][i, k]), []):
                    acc[i][bi] = acc[i].get(bi, 0.0) + wk * w
        vgs = {}
        for i, dct in enumerate(acc):
            top = sorted(dct.items(), key=lambda kv: -kv[1])[:4]; tot = sum(w for _, w in top) or 1.0
            for bi, w in top:
                if bi not in vgs: vgs[bi] = o.vertex_groups.new(name=bones[bi])
                vgs[bi].add([i], w / tot, "REPLACE")
        bpy.context.view_layer.objects.active = o
        if role in ("suit", "shoes"):
            bpy.ops.object.select_all(action="DESELECT"); o.select_set(True); bpy.ops.object.shade_smooth()
        objs.append(o)
    return body, P, J, objs

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
    # rest facing differs between CMU subjects: measure it from the rest skeleton and turn it to +Y,
    # so every joint's rotation 'from rest' means the same thing for every clip
    rp, _ = bvh_fk.fk(joints, np.zeros((1, vals.shape[1])))
    rp = rp[0] @ C.T
    l = rp[I["LeftUpLeg"]] - rp[I["RightUpLeg"]]
    hr = math.atan2(-l[0], l[1])          # forward = left x up = (l_y, -l_x)
    A = yaw(math.pi / 2 - hr)
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

PEL0 = np.eye(3)
def frame3(right, up):
    r = right / np.linalg.norm(right); u = up - r * np.dot(up, r); u /= np.linalg.norm(u)
    return np.stack([r, np.cross(u, r), u], axis=1)      # columns: right, forward, up

CALIB = {}      # bone -> 3x3 right-multiplied correction so the 'stand still' frame of 82_08 maps to the rest pose
CAL_BONES = ("spine_01", "spine_02", "spine_03", "neck_01", "head", "clavicle_l", "clavicle_r")

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

def clip_calib(pos, rot, I, ob):
    """per-clip (per-subject) correction for rotation-driven upper-body bones: over the clip's upright frames the
    bone, relative to the pelvis frame, should sit at its rest pose. CMU subjects' joint axes differ, so a single
    global calibration turned some heads backwards."""
    arm = ob.data
    pel0 = frame3(np.array(arm.bones["thigh_r"].head_local - arm.bones["thigh_l"].head_local),
                  np.array(arm.bones["spine_02"].head_local - arm.bones["pelvis"].head_local))
    hz = pos[:, I["Head"], 2] - np.minimum(pos[:, I["LeftToeBase"], 2], pos[:, I["RightToeBase"], 2])
    up = np.where(hz > 0.9 * hz.max())[0]
    if len(up) < 5: up = np.arange(len(pos))
    up = up[:: max(1, len(up) // 120)]
    K = {}
    for bn in CAL_BONES:
        R0 = np.array(arm.bones[bn].matrix_local)[:3, :3]; j = I[MAP[bn][0]]
        qs = []
        for f in up:
            Fp = frame3(pos[f, I["RightUpLeg"]] - pos[f, I["LeftUpLeg"]], pos[f, I["Spine"]] - pos[f, I["Hips"]])
            Kf = rot[f, j].T @ Fp @ pel0.T @ R0
            q = Matrix(Kf.tolist()).to_quaternion()
            if qs and q.dot(Quaternion(qs[0])) < 0: q.negate()
            qs.append(np.array(q))
        qm = np.mean(qs, axis=0); qm /= np.linalg.norm(qm)
        K[bn] = np.array(Quaternion(qm).to_matrix())
    return K

KB = {}
def retarget(ob, order, code, mode, win, extra, name):
    pos, rot, I = load_clip(code)
    KB.clear(); KB.update(clip_calib(pos, rot, I, ob))
    a, b, loop = pick(pos, rot, I, mode, win, extra)
    pos, rot = pos[a:b + 1], rot[a:b + 1]
    n = len(pos)
    # face +Y: undo the average heading over the clip
    hs = [heading(pos, I, f) for f in range(n)]
    h0 = math.atan2(np.mean(np.sin(hs)), np.mean(np.cos(hs)))
    H = yaw(math.pi / 2 - h0)
    pos = pos @ H.T; rot = H[None, None] @ rot          # turning the world: left-multiply (A above re-bases rest)
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
    global PEL0
    PEL0 = frame3(np.array(arm.bones["thigh_r"].head_local - arm.bones["thigh_l"].head_local),
                  np.array(arm.bones["spine_02"].head_local - arm.bones["pelvis"].head_local))
    for f in range(n):
        world = {}
        for bn in order:
            R0 = rest[bn][:3, :3]
            if bn == "pelvis":      # pelvis from the hip joints + lower back positions (robust to odd root Euler data)
                r_ = pos[f, I["RightUpLeg"]] - pos[f, I["LeftUpLeg"]]; u_ = pos[f, I["Spine"]] - pos[f, I["Hips"]]
                Ft = frame3(r_, u_)
                Rw = Ft @ PEL0.T @ R0
            elif bn in MAP:
                sj, dj = MAP[bn]
                Rw = rot[f, I[sj]] @ (KB[bn] if bn in KB else R0)
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
    body, P, J, objs = build_body(var, rig, W)
    ob, order = build_armature(rig, P, J)
    for o in objs:
        o.parent = ob
        md = o.modifiers.new("Armature", "ARMATURE"); md.object = ob
    for name, code, mode, win, extra in CLIPS:
        try: retarget(ob, order, code, mode, win, extra, name)
        except Exception as ex: print("  clip", name, "FAILED", ex)
    for o in bpy.context.scene.objects: o.select_set(True)
    bpy.ops.export_scene.gltf(filepath="%s/char_%s.glb" % (OUT, var), export_format="GLB", export_animations=True,
                              export_animation_mode="ACTIONS", export_extras=True, export_skins=True,
                              export_force_sampling=True, export_frame_range=False, export_anim_slide_to_zero=True)
    tri = sum(len(p.vertices) - 2 for o in objs for p in o.data.polygons)
    print("built char_%s: %d tris, %d bones" % (var, tri, len(order)))

if __name__ == "__main__":
    for v in (ONLY or VARIANTS.keys()):
        build(v)
