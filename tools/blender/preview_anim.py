"""Render a contact sheet of a glTF character's animation clips (workbench, side view).
usage: bpyenv/bin/python tools/blender/preview_anim.py IN.glb OUT.png clip1,clip2,... [frames_per_clip]"""
import sys, bpy, math
from mathutils import Vector
IN, OUT, CLIPS = sys.argv[1], sys.argv[2], sys.argv[3].split(",")
K = int(sys.argv[4]) if len(sys.argv) > 4 else 6
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=IN)
arm = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
sc = bpy.context.scene
sc.render.engine = "BLENDER_WORKBENCH"; sc.display.shading.light = "STUDIO"; sc.display.shading.color_type = "MATERIAL"
sc.render.resolution_x = 220; sc.render.resolution_y = 300
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam); sc.camera = cam
cam.location = (3.6, 0.6, 1.0); cam.rotation_euler = (math.radians(90), 0, math.radians(97))
cam.data.lens = 50
bpy.ops.mesh.primitive_plane_add(size=10)
import os, tempfile
tiles = []
for clip in CLIPS:
    act = bpy.data.actions.get(clip) or next((a for a in bpy.data.actions if a.name.startswith(clip)), None)
    if act is None: print("no clip", clip); continue
    if arm.animation_data is None: arm.animation_data_create()
    arm.animation_data.action = act
    if hasattr(act, "slots") and len(act.slots): arm.animation_data.action_slot = act.slots[0]
    f0, f1 = act.frame_range
    for k in range(K):
        f = f0 + (f1 - f0) * k / max(1, K - 1)
        sc.frame_set(int(round(f)))
        p = os.path.join(tempfile.gettempdir(), "pa_%s_%d.png" % (clip, k))
        sc.render.filepath = p; bpy.ops.render.render(write_still=True); tiles.append((clip, k, p))
# stitch
import numpy as np
rows = []
for clip in CLIPS:
    ims = [bpy.data.images.load(p) for c, k, p in tiles if c == clip]
    if not ims: continue
    arrs = [np.array(im.pixels[:]).reshape(im.size[1], im.size[0], 4) for im in ims]
    rows.append(np.concatenate(arrs, axis=1))
w = max(r.shape[1] for r in rows)
rows = [np.pad(r, ((0, 0), (0, w - r.shape[1]), (0, 0))) for r in rows]
big = np.concatenate(rows[::-1], axis=0)
img = bpy.data.images.new("sheet", big.shape[1], big.shape[0], alpha=True)
img.pixels = big.ravel().tolist(); img.filepath_raw = OUT; img.file_format = "PNG"; img.save()
print("saved", OUT)
