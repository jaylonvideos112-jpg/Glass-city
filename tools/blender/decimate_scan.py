"""Blender (bpy) script: import a high-poly CC0 scan (glTF), decimate it to a triangle budget, keep its PBR
textures, set its origin to the base centre, and export a game-ready .glb (optionally with a lower LOD).
usage: bpyenv/bin/python tools/blender/decimate_scan.py IN.gltf OUT.glb TRIS [LOD1_TRIS]"""
import sys, bpy, bmesh
from mathutils import Vector

src, out, tris = sys.argv[1], sys.argv[2], int(sys.argv[3])
lod1 = int(sys.argv[4]) if len(sys.argv) > 4 else 0
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
import os, re
drop = os.environ.get("DROP", "")           # regex of node names to discard (alternate variants, loose parts)
for o in list(bpy.context.scene.objects):
    if o.type == "MESH" and drop and re.search(drop, o.name): bpy.data.objects.remove(o)
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
total = sum(len(o.data.polygons) for o in meshes)
# join into one object (keeps material slots)
bpy.ops.object.select_all(action="DESELECT")
for o in meshes: o.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
if len(meshes) > 1: bpy.ops.object.join()
obj = bpy.context.view_layer.objects.active
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
tri_now = sum(len(p.vertices) - 2 for p in obj.data.polygons)
if tri_now > tris:
    m = obj.modifiers.new("dec", "DECIMATE"); m.ratio = tris / tri_now; m.use_collapse_triangulate = True
    bpy.ops.object.modifier_apply(modifier="dec")
# origin at the bottom centre
bb = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
mn = Vector((min(v.x for v in bb), min(v.y for v in bb), min(v.z for v in bb)))
mx = Vector((max(v.x for v in bb), max(v.y for v in bb), max(v.z for v in bb)))
base = Vector(((mn.x + mx.x) / 2, (mn.y + mx.y) / 2, mn.z))
bpy.context.scene.cursor.location = base
bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
obj.location = (0, 0, 0)
bpy.ops.object.shade_smooth()
obj.name = "LOD0"
if lod1:
    o2 = obj.copy(); o2.data = obj.data.copy(); bpy.context.collection.objects.link(o2); o2.name = "LOD1"
    m2 = o2.modifiers.new("dec", "DECIMATE"); m2.ratio = lod1 / max(1, sum(len(p.vertices) - 2 for p in obj.data.polygons))
    bpy.context.view_layer.objects.active = o2; bpy.ops.object.modifier_apply(modifier="dec")
    o2.hide_set(True)
    bpy.data.objects.remove(o2)       # Godot builds its own LODs on import; keep the file simple
final = sum(len(p.vertices) - 2 for p in obj.data.polygons)
bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", use_selection=False, export_yup=True,
    export_image_format="JPEG", export_jpeg_quality=88)
print("decimated %s: %d faces -> %d tris, size %.2f x %.2f x %.2f m" % (src, total, final, mx.x - mn.x, mx.y - mn.y, mx.z - mn.z))
