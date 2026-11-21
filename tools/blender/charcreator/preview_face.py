"""Studio render of a character: full body + face close-up side by side (EEVEE)."""
import bpy, math, os
from mathutils import Vector

def _cam(loc, look, lens):
    cd = bpy.data.cameras.new("c"); cd.lens = lens
    c = bpy.data.objects.new("c", cd); bpy.context.collection.objects.link(c)
    c.location = loc; d = Vector(look) - Vector(loc); c.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    return c

def render(basemesh, out, opt):
    import os as _os
    quick = _os.environ.get("QUICK")
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_EEVEE"
    sc.render.resolution_x, sc.render.resolution_y = 640, 900
    sc.view_settings.view_transform = "AgX" if "AgX" in [i.identifier for i in sc.view_settings.bl_rna.properties["view_transform"].enum_items] else "Standard"
    w = bpy.data.worlds.new("w"); sc.world = w; w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[0].default_value = (0.42, 0.44, 0.47, 1); w.node_tree.nodes["Background"].inputs[1].default_value = 0.6
    for name, rot, e in (("key", (55, 0, 35), 3.2), ("fill", (70, 0, -60), 1.2), ("rim", (60, 0, 180), 2.0)):
        ld = bpy.data.lights.new(name, "SUN"); ld.energy = e
        lo = bpy.data.objects.new(name, ld); bpy.context.collection.objects.link(lo)
        lo.rotation_euler = [math.radians(a) for a in rot]
    zs = [ (basemesh.matrix_world @ v.co).z for v in basemesh.data.vertices ]
    top = max(zs); hz = top - 0.12
    # MakeHuman faces -Y in Blender
    shots = []
    c = _cam((0, -0.95, hz), (0, 0, hz), 85); sc.camera = c
    p1 = out.replace(".png", "_face.png"); sc.render.filepath = p1; bpy.ops.render.render(write_still=True); shots.append(p1)
    if quick:
        import shutil; shutil.copy(p1, out); return
    c2 = _cam((0.7, -0.7, hz), (0, 0, hz), 85); sc.camera = c2
    p2 = out.replace(".png", "_face34.png"); sc.render.filepath = p2; bpy.ops.render.render(write_still=True); shots.append(p2)
    c3 = _cam((0, -4.2, top * 0.55), (0, 0, top * 0.5), 50); sc.camera = c3
    p3 = out.replace(".png", "_body.png"); sc.render.filepath = p3; bpy.ops.render.render(write_still=True); shots.append(p3)
    try:
        import numpy as np
        ims = []
        for p in shots:
            im = bpy.data.images.load(p); a = np.array(im.pixels[:]).reshape(im.size[1], im.size[0], 4)[::-1]; ims.append(a)
        sheet = np.concatenate(ims, axis=1)
        img = bpy.data.images.new("sheet", sheet.shape[1], sheet.shape[0], alpha=True)
        img.pixels = sheet[::-1].ravel(); img.filepath_raw = out; img.file_format = "PNG"; img.save()
    except Exception as ex:
        print("sheet failed", ex)
