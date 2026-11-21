"""Render a GLASS CITY head (glasshuman/head.py) from the front, three-quarter and side, for tuning.
usage: bpyenv/bin/python tools/blender/glasshuman/preview_head.py OUT.png [param=value ...]"""
import sys, os, math
import numpy as np
import bpy, bmesh
from mathutils import Vector
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import head as HD

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
OUT = args[0]
P = {k: float(v) for k, v in (a.split("=") for a in args[1:])}

def build_head(P, skin=(0.72, 0.52, 0.42)):
    V, Q, T, UV, A = HD.head_mesh(P)
    me = bpy.data.meshes.new("head"); me.from_pydata([tuple(v) for v in V], [], [tuple(q) for q in Q] + [tuple(t) for t in T])
    for p in me.polygons: p.use_smooth = True
    m = bpy.data.materials.new("skin"); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]; b.inputs["Base Color"].default_value = (*skin, 1); b.inputs["Roughness"].default_value = 0.6
    if "Subsurface Weight" in b.inputs: b.inputs["Subsurface Weight"].default_value = 0.08
    me.materials.append(m)
    o = bpy.data.objects.new("head", me); bpy.context.collection.objects.link(o)
    # eyes: find the skin surface in front of each socket centre, sit the eyeball behind it
    for side in (1, -1):
        ex, ey, ez = A["eye_l"] if side > 0 else A["eye_r"]
        r = A["eye_r_m"] + 0.0004
        c = Vector((ex, ey, ez))
        bm = bmesh.new(); bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=16, radius=r)
        em = bpy.data.meshes.new("eye"); bm.to_mesh(em); bm.free()
        for p in em.polygons: p.use_smooth = True
        mt = bpy.data.materials.new("eye"); mt.use_nodes = True
        nt = mt.node_tree; bs = nt.nodes["Principled BSDF"]
        # iris: dark disc on the +Y pole via a gradient on the local Y coordinate
        tc = nt.nodes.new("ShaderNodeTexCoord"); sep = nt.nodes.new("ShaderNodeSeparateXYZ"); ramp = nt.nodes.new("ShaderNodeValToRGB")
        nt.links.new(tc.outputs["Object"], sep.inputs[0]); nt.links.new(sep.outputs["Y"], ramp.inputs[0])
        el = ramp.color_ramp.elements
        el[0].position = r * 0.80 / r * 0.0 + 0.0; el[0].color = (0.92, 0.9, 0.86, 1)
        el[1].position = 1.0; el[1].color = (0.04, 0.03, 0.02, 1)
        ramp.color_ramp.elements.new(r * 0.0 + 0.0).color = (0.92, 0.9, 0.86, 1)
        # map: y/r from 0.72 (white) to 0.75 iris brown to 0.93 pupil
        mr = nt.nodes.new("ShaderNodeMapRange"); mr.inputs["From Min"].default_value = -r; mr.inputs["From Max"].default_value = r
        nt.links.new(sep.outputs["Y"], mr.inputs["Value"]); nt.links.new(mr.outputs["Result"], ramp.inputs[0])
        while len(ramp.color_ramp.elements) > 1: ramp.color_ramp.elements.remove(ramp.color_ramp.elements[-1])
        ramp.color_ramp.elements[0].position = 0.0; ramp.color_ramp.elements[0].color = (0.9, 0.88, 0.84, 1)
        for pos, col in ((0.86, (0.9, 0.88, 0.84, 1)), (0.875, (0.25, 0.15, 0.08, 1)), (0.95, (0.3, 0.18, 0.09, 1)), (0.955, (0.02, 0.02, 0.02, 1))):
            e_ = ramp.color_ramp.elements.new(pos); e_.color = col
        nt.links.new(ramp.outputs["Color"], bs.inputs["Base Color"]); bs.inputs["Roughness"].default_value = 0.15
        em.materials.append(mt)
        eo = bpy.data.objects.new("eye", em); eo.location = c; bpy.context.collection.objects.link(eo)
    return o, A

def render(out):
    sc = bpy.context.scene; sc.render.engine = "BLENDER_EEVEE"; sc.render.resolution_x, sc.render.resolution_y = 520, 620
    w = bpy.data.worlds.new("w"); sc.world = w; w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[0].default_value = (0.42, 0.45, 0.5, 1); w.node_tree.nodes["Background"].inputs[1].default_value = 0.7
    for name, rot, e in (("key", (60, 0, 30), 3.0), ("fill", (70, 0, -70), 1.0), ("rim", (60, 0, 170), 1.5)):
        ld = bpy.data.lights.new(name, "SUN"); ld.energy = e; lo = bpy.data.objects.new(name, ld); sc.collection.objects.link(lo)
        lo.rotation_euler = [math.radians(a) for a in rot]; lo.rotation_euler[2] += math.pi
    shots = []
    for i, (loc) in enumerate(((0, 0.62, -0.01), (0.42, 0.45, -0.01), (0.62, 0.0, -0.01))):
        cd = bpy.data.cameras.new("c"); cd.lens = 85; c = bpy.data.objects.new("c", cd); sc.collection.objects.link(c)
        c.location = loc; c.rotation_euler = (Vector((0, 0, -0.02)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        sc.camera = c; p = out.replace(".png", "_%d.png" % i); sc.render.filepath = p; bpy.ops.render.render(write_still=True); shots.append(p)
    from PIL import Image
    ims = [Image.open(p) for p in shots]; s = Image.new("RGB", (sum(i.width for i in ims), ims[0].height))
    x = 0
    for i in ims: s.paste(i, (x, 0)); x += i.width
    s.save(out)

bpy.ops.wm.read_factory_settings(use_empty=True)
build_head(P)
render(OUT)
print("rendered", OUT)
