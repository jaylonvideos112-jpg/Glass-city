"""Render a replica .glb with stand-in colours per material name, from a raised corner view (compare to photos).
usage: preview_replica.py IN.glb OUT.png [azimuth_deg] [elev_deg]"""
import sys, math, bpy
from mathutils import Vector
src, out = sys.argv[1], sys.argv[2]
az = math.radians(float(sys.argv[3]) if len(sys.argv) > 3 else 35); el = math.radians(float(sys.argv[4]) if len(sys.argv) > 4 else 18)
COL = {"limestone": (0.72, 0.68, 0.6), "brick_buff": (0.66, 0.55, 0.42), "brick_tan": (0.62, 0.5, 0.38), "brick_red": (0.45, 0.2, 0.14),
       "brick_brown": (0.35, 0.22, 0.15), "granite_dark": (0.18, 0.17, 0.17), "terracotta": (0.75, 0.6, 0.45), "frame_dark": (0.08, 0.08, 0.08),
       "frame_white": (0.85, 0.85, 0.82), "glass_window": (0.06, 0.08, 0.1), "glass_shop": (0.08, 0.1, 0.12), "roof_flat": (0.3, 0.3, 0.3),
       "precast": (0.75, 0.73, 0.68), "concrete": (0.6, 0.6, 0.58), "metal_dark": (0.12, 0.13, 0.14), "glass_curtain": (0.12, 0.2, 0.28), "sandstone": (0.6, 0.45, 0.32), "brick_orange": (0.62, 0.36, 0.22), "slate": (0.2, 0.21, 0.24), "paint_white": (0.85, 0.84, 0.8), "slate_red": (0.5, 0.2, 0.15), "lead": (0.45, 0.47, 0.5), "precast_white": (0.85, 0.85, 0.83), "glass_teal": (0.15, 0.32, 0.35), "glass_dark": (0.03, 0.03, 0.04), "metal_light": (0.6, 0.62, 0.64), "marble": (0.88, 0.88, 0.86), "copper": (0.35, 0.58, 0.5), "tile_red": (0.6, 0.28, 0.18), "brick_tapestry": (0.3, 0.15, 0.11), "siding_cream": (0.8, 0.74, 0.6), "siding_blue": (0.6, 0.7, 0.76), "siding_sage": (0.5, 0.52, 0.42), "siding_white": (0.88, 0.88, 0.85), "siding_grey": (0.55, 0.55, 0.53), "siding_yellow": (0.85, 0.75, 0.45), "stone_lime": (0.7, 0.66, 0.58), "stucco": (0.85, 0.83, 0.78), "paint_cream": (0.85, 0.8, 0.62), "paint_green": (0.12, 0.38, 0.27), "paint_red": (0.55, 0.1, 0.08), "shingle": (0.24, 0.22, 0.21), "terracotta_cream": (0.82, 0.76, 0.6), "paint_yellow": (0.86, 0.66, 0.22), "neon_red": (0.85, 0.22, 0.2)}
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
for o in objs:
    for m in o.data.materials:
        b = m.node_tree.nodes.get("Principled BSDF")
        if b:
            b.inputs["Base Color"].default_value = (*COL.get(m.name.split(".")[0], (0.5, 0.5, 0.5)), 1)
            b.inputs["Roughness"].default_value = 0.15 if "glass" in m.name else 0.8
pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
mn = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts))); mx = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
c = (mn + mx) / 2; r = (mx - mn).length
import os
if os.environ.get("FOCUS"):                   # FOCUS="x,y,z,dist": look at a detail from closer
    fx, fy, fz, fd = map(float, os.environ["FOCUS"].split(",")); c = Vector((fx, fy, fz)); r = fd / 1.25
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); bpy.context.collection.objects.link(cam)
cam.data.lens = 40
cam.location = c + Vector((math.cos(az) * math.cos(el), math.sin(az) * math.cos(el), math.sin(el))) * r * 1.25
cam.rotation_euler = (c - cam.location).to_track_quat("-Z", "Y").to_euler()
bpy.context.scene.camera = cam
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN")); bpy.context.collection.objects.link(sun)
sun.rotation_euler = (0.9, 0.2, 2.2); sun.data.energy = 3.5
sc = bpy.context.scene; sc.render.engine = "BLENDER_EEVEE"; sc.render.resolution_x = int(os.environ.get('RX', 700)); sc.render.resolution_y = int(os.environ.get('RY', 900))
sc.world = bpy.data.worlds.new("w"); sc.world.color = (0.75, 0.78, 0.82)
sc.render.filepath = out
bpy.ops.render.render(write_still=True)
