"""Render a quick turnaround preview (workbench) of a .glb: preview.py IN.glb OUT.png"""
import sys, bpy, math
from mathutils import Vector
src, out = sys.argv[1], sys.argv[2]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
mn = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
mx = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
c = (mn + mx) / 2; r = max((mx - mn).length, 0.1)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); bpy.context.collection.objects.link(cam)
cam.location = c + Vector((r * 0.9, r * 1.1, r * 0.6))
d = c - cam.location; cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
bpy.context.scene.camera = cam
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN")); bpy.context.collection.objects.link(sun)
sun.rotation_euler = (0.8, 0.3, 0.6); sun.data.energy = 4
sc = bpy.context.scene
sc.render.engine = "BLENDER_EEVEE" if "BLENDER_EEVEE" in [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items] else "BLENDER_WORKBENCH"
sc.render.resolution_x = 480; sc.render.resolution_y = 400
sc.world = bpy.data.worlds.new("w"); sc.world.color = (0.6, 0.65, 0.7)
sc.render.filepath = out
try:
    bpy.ops.render.render(write_still=True)
except Exception as e:
    sc.render.engine = "BLENDER_WORKBENCH"; sc.display.shading.light = "STUDIO"; sc.display.shading.color_type = "TEXTURE"
    bpy.ops.render.render(write_still=True)
print("dims", mx - mn)
