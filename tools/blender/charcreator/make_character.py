"""GLASS CITY character creator (Blender + the MPFB2 add-on, MakeHuman CC0 assets).

Builds one person from a character spec (JSON): MakeHuman body (gender/age/muscle/weight/height/ethnicity macros),
up to ~270 face/body detail sliders (MakeHuman targets: nose, mouth, eyes, brows, cheeks, chin, jaw, head shape,
ears, neck, torso ...), skin, eyes, brows, lashes, teeth, hair and clothes, skinned to MPFB2's 53-bone
'game_engine' skeleton (Unreal-mannequin bone names; same skeleton as tools/blender/rigged_people.py).

Optional "fit" block: face landmarks from a photo (tools/pipeline/face_landmarks.py) -> the face sliders are solved
so the model's face matches (bounded least squares; see charcreator/facefit.py), and the photo's face is projected
into the skin texture.

usage: bpyenv/bin/python tools/blender/charcreator/make_character.py SPEC.json OUT.glb [PREVIEW.png]
spec keys (all optional): name, phenotype{gender,age,muscle,weight,height,proportions,cupsize,firmness,
  race{african,asian,caucasian}}, targets{name: value}, skin, eyes, eyebrows, eyelashes, hair, clothes[],
  hair_color [r,g,b], skin_tint [r,g,b], fit{landmarks, photo, strength}"""
import sys, os, json, importlib
import bpy, addon_utils
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

SPEC, OUT = sys.argv[1], sys.argv[2]
PREVIEW = sys.argv[3] if len(sys.argv) > 3 else None
S = json.load(open(SPEC))

addon_utils.enable("bl_ext.user_default.mpfb", default_set=True, persistent=False)
def svc(name): return importlib.import_module("bl_ext.user_default.mpfb.services." + name)
HumanService = svc("humanservice").HumanService
TargetService = svc("targetservice").TargetService

for o in list(bpy.data.objects): bpy.data.objects.remove(o)

info = HumanService._create_default_human_info_dict()
ph = info["phenotype"]
for k, v in S.get("phenotype", {}).items():
    if k == "race": ph["race"] = dict(v)
    else: ph[k] = float(v)
info["name"] = S.get("name", "person")
info["rig"] = "game_engine"
info["eyes"] = "eyes/low-poly/low-poly.mhclo"
info["eyes_material_type"] = "MAKESKIN"
info["eyes_material_settings"] = {}
info["eyebrows"] = "eyebrows/%s/%s.mhclo" % ((S.get("eyebrows", "eyebrow001"),) * 2)
info["eyelashes"] = "eyelashes/%s/%s.mhclo" % ((S.get("eyelashes", "eyelashes01"),) * 2)
info["teeth"] = "teeth/teeth_base/teeth_base.mhclo" if S.get("teeth", True) else ""
info["tongue"] = ""
info["hair"] = ("hair/%s/%s.mhclo" % ((S["hair"],) * 2)) if S.get("hair") else ""
info["clothes"] = ["clothes/%s/%s.mhclo" % (c, c) for c in S.get("clothes", [])]
info["skin_mhmat"] = "skins/%s/%s.mhmat" % ((S.get("skin", "young_caucasian_male"),) * 2)
info["skin_material_type"] = "MAKESKIN"
info["alternative_materials"] = {}
info["targets"] = [{"target": k, "value": float(v)} for k, v in S.get("targets", {}).items() if abs(float(v)) > 1e-4]

settings = HumanService.get_default_deserialization_settings()
settings.update(subdiv_levels=0, override_skin_model="MAKESKIN", material_instances="NEVER", scale=0.1)
basemesh = HumanService.deserialize_from_dict(info, settings)

# ---- face fit from photo landmarks: solve the face sliders against the macro-shaped head
if S.get("fit"):
    import facefit
    weights = facefit.fit(basemesh, S["fit"], TargetService)
    print("fit: %d sliders set" % len(weights))
    ST = S.get("style", {})
    if ST.get("exaggerate"):          # caricature: push every fitted slider further from neutral
        kb = basemesh.data.shape_keys.key_blocks
        for n, x in weights.items():
            for k in (n, "r-" + n[2:] if n.startswith("l-") else None):
                if k and k in kb: kb[k].value = min(1.0, x * float(ST["exaggerate"]))
    HumanService.refit(basemesh)      # eyes, brows, lashes, hair and clothes follow the new face
    if S["fit"].get("photo") and not ST.get("painted"):
        facefit.project_photo(basemesh, S["fit"])

# eye colour: MakeSkin eye material by name
if S.get("eyes"):
    for o in bpy.data.objects:
        if o.type == "MESH" and "eye" in o.name.lower() and "brow" not in o.name.lower() and "lash" not in o.name.lower():
            for slot in o.material_slots:
                m = slot.material
                if not m or not m.node_tree: continue
                for n in m.node_tree.nodes:
                    if n.type == "TEX_IMAGE" and n.image and "_eye" in n.image.name.lower():
                        p = os.path.join(os.path.dirname(bpy.path.abspath(n.image.filepath)), "%s_eye.png" % S["eyes"])
                        if os.path.exists(p): n.image = bpy.data.images.load(p, check_existing=True)

def tint(obj_pred, rgb):
    for o in bpy.data.objects:
        if o.type != "MESH" or not obj_pred(o.name.lower()): continue
        for slot in o.material_slots:
            m = slot.material
            if not m or not m.node_tree: continue
            bsdf = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
            tex = next((n for n in m.node_tree.nodes if n.type == "TEX_IMAGE"), None)
            if not bsdf: continue
            if tex:     # multiply the texture by the tint
                mix = m.node_tree.nodes.new("ShaderNodeMix"); mix.data_type = "RGBA"; mix.blend_type = "MULTIPLY"
                mix.inputs[0].default_value = 1.0; mix.inputs[7].default_value = (*rgb, 1.0)
                m.node_tree.links.new(tex.outputs["Color"], mix.inputs[6])
                m.node_tree.links.new(mix.outputs[2], bsdf.inputs["Base Color"])
            else:
                bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
if S.get("hair_color"): tint(lambda n: "hair" in n or "brow" in n, S["hair_color"])
if S.get("skin_tint"): tint(lambda n: n == basemesh.name.lower() or "body" in n, S["skin_tint"])

# ---- export: armature + every mesh parented to it, shape keys baked
for o in bpy.data.objects:
    if o.type == "MESH" and o.data.shape_keys:
        for x in bpy.context.selected_objects: x.select_set(False)
        bpy.context.view_layer.objects.active = o; o.select_set(True)
        bpy.ops.object.shape_key_remove(all=True, apply_mix=True)      # bake the slider mix into the mesh
        o.select_set(False)
ST = S.get("style", {})
if ST:
    import stylize
    stylize.apply(basemesh, ST, S)
os.makedirs(os.path.dirname(os.path.abspath(OUT)), exist_ok=True)
bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", export_skins=True, export_animations=False,
                          export_morph=False, export_image_format="AUTO")
print("built", OUT, "objects:", [o.name for o in bpy.data.objects])

if PREVIEW:
    import preview_face
    preview_face.render(basemesh, PREVIEW, S.get("preview", {}))
