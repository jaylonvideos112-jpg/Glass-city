"""Generate a GLASS CITY character with the owner's Blender add-on (tools/blender/schoolyard/
schoolyard_characters_v3.py, from his Google Drive "GLASS CITY - Character Generator (Blender add-on)") and export
it as a rigged .glb for Godot. The add-on needs MPFB (MakeHuman extension) + its CC0 asset packs.
usage: bpyenv/bin/python gen_character.py OUT.glb PRESET [seed] [key=value ...] [anim=1] [preview=PNG]
  e.g. gen_character.py assets/models/char_p1.glb HOOPER 3 stance=A_POSE anim=1
anim=1 retargets the game's 17 CMU mocap clips (tools/blender/rigged_people.py) onto the add-on's MPFB
game_engine skeleton (same bone names as the rest of the cast) and exports them as glTF actions, facing Godot -Z.
preview=PNG renders a front / 3-4 / side look-dev image (Eevee) for checking."""
import sys, os, importlib.util, time
import bpy, addon_utils
args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
OUT, PRESET = args[0], args[1]
SEED = int(args[2]) if len(args) > 2 and "=" not in args[2] else 1
KV = [a for a in args[2:] if "=" in a and a.split("=")[0] not in ("anim", "preview")]
OPT = dict(a.split("=", 1) for a in args[2:] if "=" in a and a.split("=")[0] in ("anim", "preview"))
ANIM = OPT.get("anim", "0") in ("1", "true"); PREVIEW = OPT.get("preview")

bpy.ops.wm.read_factory_settings(use_empty=True)
addon_utils.enable("bl_ext.user_default.mpfb", default_set=True)
here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("schoolyard_characters_v3", os.path.join(here, "schoolyard_characters_v3.py"))
SY = importlib.util.module_from_spec(spec); sys.modules["schoolyard_characters_v3"] = SY; spec.loader.exec_module(SY)
SY.register()
p = bpy.context.scene.sy3_props
p.preset = PRESET
p.seed = SEED
for kv in KV:
    k, v = kv.split("=", 1)
    cur = getattr(p, k)
    setattr(p, k, (v.lower() in ("1", "true", "yes")) if isinstance(cur, bool) else type(cur)(v) if not isinstance(cur, str) else v)
t = time.time()
SY.build(bpy.context, p)
print("built in %.1fs" % (time.time() - t))
objs = [o for o in bpy.context.scene.objects]
arm = [o for o in objs if o.type == "ARMATURE"]
print("objects:", len(objs), "meshes:", sum(o.type == "MESH" for o in objs), "armature bones:", len(arm[0].data.bones) if arm else 0)
if arm: print("bones:", [b.name for b in arm[0].data.bones][:30])
if PREVIEW:
    import math
    from mathutils import Vector
    sc = bpy.context.scene; sc.render.engine = "BLENDER_EEVEE"; sc.render.resolution_x, sc.render.resolution_y = 1500, 1000
    w = bpy.data.worlds.new("w"); sc.world = w; w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[0].default_value = (0.55, 0.6, 0.66, 1); w.node_tree.nodes["Background"].inputs[1].default_value = 0.9
    for nm, rot, e in (("key", (55, 0, 35), 3.2), ("fill", (65, 0, -60), 1.2), ("rim", (60, 0, 170), 2.0)):
        ld = bpy.data.lights.new(nm, "SUN"); ld.energy = e; lo = bpy.data.objects.new(nm, ld); sc.collection.objects.link(lo)
        lo.rotation_euler = [math.radians(x) for x in rot]
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH" and not o.hide_render]
    zs = [ (o.matrix_world @ Vector(c)).z for o in meshes for c in o.bound_box ]
    top, bot = max(zs), min(zs); mid = (top + bot) / 2
    shots = []
    for i, ang in enumerate((0, 35, 90)):
        cd = bpy.data.cameras.new("c"); cd.lens = 50; c = bpy.data.objects.new("c", cd); sc.collection.objects.link(c)
        r = (top - bot) * 2.1; a_ = math.radians(ang)
        c.location = (r * math.sin(a_), -r * math.cos(a_), mid + 0.1)
        c.rotation_euler = (Vector((0, 0, mid)) - c.location).to_track_quat("-Z", "Y").to_euler()
        sc.camera = c; sc.render.resolution_x = 500; fp = PREVIEW.replace(".png", "_%d.png" % i); sc.render.filepath = fp
        bpy.ops.render.render(write_still=True); shots.append(fp)
    from PIL import Image
    ims = [Image.open(f) for f in shots]; out = Image.new("RGB", (sum(i.width for i in ims), ims[0].height))
    x = 0
    for im in ims: out.paste(im, (x, 0)); x += im.width
    out.save(PREVIEW); print("preview", PREVIEW)
# ---- mocap (same CMU clips as the rest of the game's people). The retarget works facing +Y; MPFB faces -Y:
# turn rig + meshes 180 degrees and apply, so the exported model faces Godot -Z like the rest of the cast.
arm = next((o for o in bpy.context.scene.objects if o.type == "ARMATURE"), None)
if ANIM and arm is not None:
    import math
    sys.path.insert(0, os.path.dirname(here))
    import rigged_people as RP
    for pb in arm.pose.bones: pb.rotation_quaternion = (1, 0, 0, 0); pb.rotation_euler = (0, 0, 0); pb.location = (0, 0, 0)
    bpy.ops.object.select_all(action="DESELECT")
    arm.rotation_euler[2] += math.pi
    for o in [arm] + list(arm.children_recursive): o.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    order = []
    def _visit(b):
        order.append(b.name)
        for c in b.children: _visit(c)
    for b in arm.data.bones:
        if b.parent is None: _visit(b)
    ok = 0
    for name, code, mode, win, extra in RP.CLIPS:
        try: RP.retarget(arm, order, code, mode, win, extra, name); ok += 1
        except Exception as ex: print("  clip", name, "FAILED", ex)
    print("animations: %d of %d clips" % (ok, len(RP.CLIPS)))
bpy.ops.object.select_all(action="DESELECT")
for o in objs:
    if o.type in ("MESH", "ARMATURE") and not o.hide_get(): o.select_set(True)
bpy.ops.export_scene.gltf(filepath=OUT, use_selection=True, export_format="GLB", export_skins=True,
                          export_animations=ANIM, export_animation_mode="ACTIONS", export_force_sampling=True,
                          export_frame_range=False, export_anim_slide_to_zero=True, export_morph=False)
print("exported", OUT, os.path.getsize(OUT) // 1024, "KB")
