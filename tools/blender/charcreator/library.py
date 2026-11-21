"""NPC library base characters (character creator, Bully style): one rigged, animated base per gender whose face
and body are driven by blend shapes, so 500 face presets per gender cost nothing at runtime.

Built with MPFB2 like every creator character:
  * neutral base: average age/weight/muscle/height, ethnicity 1/3 each, Bully proportions (head x1.1, hands x1.15)
  * face blend shapes "f_<target>": ~70 MakeHuman face sliders (nose, mouth, eyes, brows, chin, jaw, cheeks,
    forehead, head shape, ears); left/right twins are merged into one symmetric shape
  * ethnicity shapes "r_african|r_asian|r_caucasian" and body shapes "b_heavy|b_thin|b_muscle|b_slim|b_tall|b_short"
    (differences of whole MakeHuman macro builds)
  * every shape is carried over to the eyes, brows, lashes, teeth and clothes (MPFB refit per shape), so eyes stay in
    their sockets and clothes follow the body
  * painted, neutral-toned skin (the game multiplies it by each person's skin tone)
  * the 17 CMU mocap clips (tools/blender/rigged_people.py)
usage: bpyenv/bin/python tools/blender/charcreator/library.py m|f OUT.glb"""
import sys, os, json, math, importlib, glob
import numpy as np
import bpy, addon_utils, bmesh
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(HERE))
GENDER, OUT = sys.argv[-2], sys.argv[-1]
M = GENDER == "m"

addon_utils.enable("bl_ext.user_default.mpfb", default_set=True, persistent=False)
def svc(n): return importlib.import_module("bl_ext.user_default.mpfb.services." + n)
HS = svc("humanservice").HumanService
TS = svc("targetservice").TargetService
TROOT = svc("locationservice").LocationService.get_mpfb_data("targets")
TFILES = {os.path.basename(f)[:-len(".target.gz")]: f for f in glob.glob(os.path.join(TROOT, "*", "*.target.gz"))}

FACE = """nose-scale-horiz nose-scale-vert nose-scale-depth nose-nostrils-width nose-point-width nose-flaring nose-hump
nose-trans:up,down nose-trans:forward,backward nose-base:up,down nose-width1 nose-width2 nose-width3 nose-septumangle
mouth-scale-horiz mouth-scale-vert mouth-trans:up,down mouth-trans:forward,backward mouth-lowerlip-volume mouth-upperlip-volume
mouth-lowerlip-height mouth-upperlip-height mouth-angles:up,down mouth-cupidsbow-width l-eye-scale l-eye-trans:in,out
l-eye-trans:up,down l-eye-height1 l-eye-height2 l-eye-height3 l-eye-corner1:up,down l-eye-corner2:up,down l-eye-bag
l-eye-epicanthus:in,out eyebrows-trans:up,down eyebrows-angle:up,down eyebrows-trans:forward,backward chin-prominent
chin-width chin-height chin-jaw-drop chin-bones chin-cleft l-cheek-bones l-cheek-volume l-cheek-inner l-cheek-trans:up,down
forehead-scale-vert forehead-temple forehead-nubian forehead-trans:forward,backward head-fat head-scale-horiz
head-scale-vert head-age l-ear-scale l-ear-flap l-ear-lobe l-ear-trans:up,down""".split()
SINGLES = ["head-oval", "head-round", "head-square", "head-triangular", "head-invertedtriangular", "head-diamond", "head-rectangular"]

def face_targets():
    """[(shape name, [target names applied together])]: both directions of every slider, twins merged"""
    out = []
    for item in FACE:
        base, _, suf = item.partition(":")
        dirs = suf.split(",") if suf else ["decr", "incr"]
        for d in dirs:
            n = "%s-%s" % (base, d)
            if n not in TFILES: continue
            names = [n] + (["r-" + n[2:]] if n.startswith("l-") and ("r-" + n[2:]) in TFILES else [])
            out.append(("f_" + n[2:] if n.startswith("l-") else "f_" + n, names))
    for n in SINGLES:
        if n in TFILES: out.append(("f_" + n, [n]))
    return out

def info_for(ph):
    info = HS._create_default_human_info_dict()
    info["phenotype"].update({k: v for k, v in ph.items() if k != "race"}); info["phenotype"]["race"] = dict(ph["race"])
    return info

BASE_PH = {"gender": 1.0 if M else 0.0, "age": 0.5, "muscle": 0.5, "weight": 0.5, "height": 0.5, "proportions": 0.5,
           "cupsize": 0.5, "firmness": 0.5, "race": {"african": 1 / 3, "asian": 1 / 3, "caucasian": 1 / 3}}

def coords_of(ph):
    """body vertex positions of a bare human with this phenotype (shape-key mix)"""
    for o in list(bpy.data.objects): bpy.data.objects.remove(o)
    st = HS.get_default_deserialization_settings(); st.update(load_clothes=False, scale=0.1, subdiv_levels=0)
    info = info_for(ph); info["rig"] = ""; info["eyes"] = info["eyebrows"] = info["eyelashes"] = info["teeth"] = info["tongue"] = info["hair"] = ""
    info["alternative_materials"] = {}; info["skin_mhmat"] = ""
    h = HS.deserialize_from_dict(info, st)
    import facefit
    c = facefit.mesh_coords(h)
    for o in list(bpy.data.objects): bpy.data.objects.remove(o)
    return c

# ---- macro difference shapes (ethnicity, body)
macro = {}
v0 = coords_of(BASE_PH)
for name, ch in (("r_african", {"race": {"african": 1.0, "asian": 0.0, "caucasian": 0.0}}),
                 ("r_asian", {"race": {"african": 0.0, "asian": 1.0, "caucasian": 0.0}}),
                 ("r_caucasian", {"race": {"african": 0.0, "asian": 0.0, "caucasian": 1.0}}),
                 ("b_heavy", {"weight": 1.0}), ("b_thin", {"weight": 0.0}), ("b_muscle", {"muscle": 1.0}),
                 ("b_slim", {"muscle": 0.0}), ("b_old", {"age": 0.875})):
    ph = json.loads(json.dumps(BASE_PH)); ph.update(ch)
    macro[name] = coords_of(ph) - v0
    print("macro", name, round(float(np.abs(macro[name]).max()), 4))

# ---- the base character
for o in list(bpy.data.objects): bpy.data.objects.remove(o)
info = info_for(BASE_PH)
info["name"] = "npc_" + GENDER; info["rig"] = "game_engine"
info["eyes"] = "eyes/low-poly/low-poly.mhclo"; info["eyes_material_type"] = "MAKESKIN"; info["eyes_material_settings"] = {}
info["eyebrows"] = "eyebrows/eyebrow001/eyebrow001.mhclo" if M else "eyebrows/eyebrow008/eyebrow008.mhclo"
info["eyelashes"] = "eyelashes/eyelashes01/eyelashes01.mhclo"; info["teeth"] = "teeth/teeth_base/teeth_base.mhclo"
info["tongue"] = ""; info["hair"] = ""
OUTFIT = ["male_casualsuit03", "shoes02"] if M else ["female_casualsuit01", "shoes05"]
info["clothes"] = ["clothes/%s/%s.mhclo" % (c, c) for c in OUTFIT]
info["skin_mhmat"] = "skins/%s/%s.mhmat" % (("young_caucasian_male",) * 2 if M else ("young_caucasian_female",) * 2)
info["skin_material_type"] = "MAKESKIN"; info["alternative_materials"] = {}; info["targets"] = []
st = HS.get_default_deserialization_settings(); st.update(subdiv_levels=0, override_skin_model="MAKESKIN", material_instances="NEVER", scale=0.1)
body = HS.deserialize_from_dict(info, st)
proxies = [o for o in bpy.data.objects if o.type == "MESH" and o != body]

def sel_only(o):
    for x in bpy.context.selected_objects: x.select_set(False)
    bpy.context.view_layer.objects.active = o; o.select_set(True)

# bake the macro mix into the mesh, then Bully proportions on the plain mesh (before any shape keys exist)
if body.data.shape_keys:
    sel_only(body); bpy.ops.object.shape_key_remove(all=True, apply_mix=True)
import stylize
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
stylize._scale_part(arm, ["head"], "head", 1.1)
for sd in ("l", "r"):
    stylize._scale_part(arm, ["hand_" + sd] + [f"{f}_{i:02d}_{sd}" for f in ("thumb", "index", "middle", "ring", "pinky") for i in (1, 2, 3)], "hand_" + sd, 1.15)
HS.refit(body)

# shapes on the body: face targets (loaded by MPFB, twins merged) and the macro differences
body.shape_key_add(name="Basis")
shapes = []
for sname, tnames in face_targets():
    keys = []
    for t in tnames:
        sk = TS.load_target(body, TFILES[t], weight=0.0, name=t)
        if sk is not None: keys.append(sk)
    if not keys: continue
    for k in keys: k.value = 1.0
    new = body.shape_key_add(name=sname, from_mix=True); new.value = 0.0
    for k in keys: body.shape_key_remove(k)
    shapes.append(sname)
basis = np.empty(len(body.data.vertices) * 3); body.data.shape_keys.reference_key.data.foreach_get("co", basis); basis = basis.reshape(-1, 3)
for name, d in macro.items():
    k = body.shape_key_add(name=name, from_mix=False); k.value = 0.0
    k.data.foreach_set("co", (basis + d * 1.0).ravel())        # MPFB keeps object space = base mesh space
    shapes.append(name)
print("body shapes:", len(shapes))

# carry every shape over to the proxies (eyes, brows, lashes, teeth, clothes): refit at full weight, record
def proxy_coords():
    out = {}
    for p in proxies:
        a = np.empty(len(p.data.vertices) * 3); p.data.vertices.foreach_get("co", a); out[p.name] = a
    return out
HS.refit(body); rest = proxy_coords()
for p in proxies:
    if not p.data.shape_keys: p.shape_key_add(name="Basis")
kb = body.data.shape_keys.key_blocks
for sname in shapes:
    kb[sname].value = 1.0; HS.refit(body); now = proxy_coords(); kb[sname].value = 0.0
    for p in proxies:
        k = p.shape_key_add(name=sname, from_mix=False); k.value = 0.0
        k.data.foreach_set("co", now[p.name])
HS.refit(body)
for p in proxies:     # refit moved the base vertices of the proxies; put the rest shape back
    p.data.vertices.foreach_set("co", rest[p.name]); p.data.shape_keys.reference_key.data.foreach_set("co", rest[p.name])

# helper geometry out (bmesh keeps shape keys)
gi = body.vertex_groups["body"].index
bm = bmesh.new(); bm.from_mesh(body.data); dl = bm.verts.layers.deform.active
bmesh.ops.delete(bm, geom=[v for v in bm.verts if not (dl and gi in v[dl] and v[dl][gi] > 0.5)], context="VERTS")
bm.to_mesh(body.data); bm.free()
for m in list(body.modifiers):
    if m.type == "MASK": body.modifiers.remove(m)

# painted, neutral skin: the game tints it with each person's tone
def neutral_paint(obj):
    from scipy.ndimage import median_filter
    import cv2
    for slot in obj.material_slots:
        mt = slot.material
        if not mt or not mt.node_tree: continue
        for n in mt.node_tree.nodes:
            if n.type == "NORMAL_MAP": n.inputs["Strength"].default_value = 0.15
            if n.type == "TEX_IMAGE" and n.image and "normal" not in n.image.name.lower():
                W, H = n.image.size
                T = np.array(n.image.pixels[:], dtype=np.float32).reshape(H, W, 4)
                rgb = (T[..., :3] * 255).astype(np.uint8)
                rgb = cv2.edgePreservingFilter(rgb, flags=1, sigma_s=30, sigma_r=0.2).astype(np.float32) / 255
                body_px = rgb.reshape(-1, 3)[rgb.reshape(-1, 3).sum(1) > 0.15]
                med = np.median(body_px, 0)
                rgb = np.clip(rgb / np.maximum(med, 1e-3) * 0.8, 0, 1)      # neutral grey-ish, relative detail kept
                T[..., :3] = rgb
                im = bpy.data.images.new(obj.name + "_skin_neutral", W, H, alpha=True); im.pixels = T.ravel(); im.pack(); n.image = im
neutral_paint(body)

# mocap
import rigged_people as RP
sel_only(arm)
arm.rotation_euler[2] += math.pi
for o in [arm] + list(arm.children_recursive): o.select_set(True)
bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
order = []
def visit(b):
    order.append(b.name)
    for c in b.children: visit(c)
for b in arm.data.bones:
    if b.parent is None: visit(b)
ok = 0
for name, code, mode, win, extra in RP.CLIPS:
    try: RP.retarget(arm, order, code, mode, win, extra, name); ok += 1
    except Exception as ex: print("  clip", name, "FAILED", ex)
print("animations: %d of %d" % (ok, len(RP.CLIPS)))

for o in bpy.context.scene.objects: o.select_set(True)
bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", export_skins=True, export_animations=True,
                          export_animation_mode="ACTIONS", export_extras=True, export_force_sampling=True,
                          export_frame_range=False, export_anim_slide_to_zero=True, export_morph=True,
                          export_morph_normal=False, export_image_format="AUTO")
json.dump({"shapes": shapes, "face": [s for s in shapes if s.startswith("f_")]},
          open(os.path.splitext(OUT)[0] + "_shapes.json", "w"), indent=0)
print("built", OUT, "shapes", len(shapes), "objects", [o.name for o in bpy.data.objects])
