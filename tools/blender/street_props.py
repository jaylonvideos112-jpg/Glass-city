"""Blender (bpy) procedural street props, bevelled and subdivided, exported as .glb into assets/models/.
Godot faces -Z = Blender +Y, so every prop's 'front' (road side) points +Y here.
usage: bpyenv/bin/python tools/blender/street_props.py OUTDIR"""
import sys, math, bpy, bmesh
from mathutils import Vector, Matrix
OUT = sys.argv[1]

def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)

def mat(name, col, metal=0.0, rough=0.5, emit=None):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*col, 1)
    b.inputs["Metallic"].default_value = metal
    b.inputs["Roughness"].default_value = rough
    if emit:
        b.inputs["Emission Color"].default_value = (*emit, 1); b.inputs["Emission Strength"].default_value = 1.0
    return m

def finish(o, m, bevel=0.0, seg=2, smooth=True):
    o.data.materials.append(m)
    if bevel > 0:
        md = o.modifiers.new("bev", "BEVEL"); md.width = bevel; md.segments = seg; md.limit_method = "ANGLE"
    bpy.context.view_layer.objects.active = o
    for md in list(o.modifiers): bpy.ops.object.modifier_apply(modifier=md.name)
    if smooth:
        bpy.ops.object.shade_auto_smooth(angle=math.radians(35))
    return o

def box(size, loc, m, bevel=0.01, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc, rotation=rot)
    o = bpy.context.active_object; o.scale = size
    bpy.ops.object.transform_apply(scale=True)
    return finish(o, m, bevel)

def cyl(r, h, loc, m, verts=24, bevel=0.0, r2=None, rot=(0, 0, 0)):
    if r2 is None:
        bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=r, depth=h, location=loc, rotation=rot)
    else:
        bpy.ops.mesh.primitive_cone_add(vertices=verts, radius1=r, radius2=r2, depth=h, location=loc, rotation=rot)
    return finish(bpy.context.active_object, m, bevel)

def export(name):
    for o in bpy.context.scene.objects: o.select_set(o.type == "MESH")
    bpy.context.view_layer.objects.active = [o for o in bpy.context.scene.objects if o.type == "MESH"][0]
    bpy.ops.object.join()
    o = bpy.context.active_object; o.name = name
    bpy.ops.export_scene.gltf(filepath="%s/%s.glb" % (OUT, name), export_format="GLB", use_selection=False)
    tris = sum(len(p.vertices) - 2 for p in o.data.polygons)
    print("built", name, tris, "tris")

# ---------------------------------------------------------------- cobra-head street light (7 m, arm over road)
def street_light():
    reset()
    steel = mat("lamp_steel", (0.42, 0.44, 0.45), metal=0.85, rough=0.38)
    dark = mat("lamp_dark", (0.12, 0.12, 0.13), metal=0.6, rough=0.5)
    bulb = mat("bulb", (0.95, 0.9, 0.75), rough=0.2)
    cyl(0.16, 0.5, (0, 0, 0.25), dark, verts=8, bevel=0.015)                     # octagonal base cover
    cyl(0.2, 0.06, (0, 0, 0.03), dark, verts=8, bevel=0.01)
    cyl(0.115, 6.6, (0, 0, 3.75), steel, verts=16, r2=0.07)                      # tapered pole
    cyl(0.085, 0.15, (0, 0, 7.05), steel, verts=16, bevel=0.01)                 # cap
    # arm: a curve swept with a round profile, rising out then levelling toward the road (+Y)
    cu = bpy.data.curves.new("arm", "CURVE"); cu.dimensions = "3D"; cu.bevel_depth = 0.045; cu.bevel_resolution = 3
    sp = cu.splines.new("BEZIER"); sp.bezier_points.add(1)
    a, b = sp.bezier_points
    a.co = (0, 0, 6.55); a.handle_left = (0, -0.3, 6.2); a.handle_right = (0, 0.25, 7.05)
    b.co = (0, 1.95, 6.92); b.handle_left = (0, 1.1, 7.0); b.handle_right = (0, 2.3, 6.9)
    ob = bpy.data.objects.new("arm", cu); bpy.context.collection.objects.link(ob)
    bpy.context.view_layer.objects.active = ob; ob.select_set(True)
    bpy.ops.object.convert(target="MESH"); finish(ob, steel)
    # cobra head: a squashed, tapered shell
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=1, location=(0, 2.2, 6.86))
    h = bpy.context.active_object; h.scale = (0.24, 0.48, 0.13)
    bpy.ops.object.transform_apply(scale=True)
    bm = bmesh.new(); bm.from_mesh(h.data)
    for v in bm.verts:
        if v.co.z < 6.86: v.co.z = 6.86 - (6.86 - v.co.z) * 0.35     # flat underside
        v.co.x *= 1.0 - max(0.0, (2.2 - v.co.y)) * 0.55              # narrows toward the arm
    bm.to_mesh(h.data); bm.free()
    finish(h, mat("lamp_head", (0.55, 0.57, 0.58), metal=0.5, rough=0.4))
    bpy.ops.mesh.primitive_uv_sphere_add(segments=20, ring_count=8, radius=1, location=(0, 2.25, 6.83))
    l = bpy.context.active_object; l.scale = (0.17, 0.32, 0.05)              # glass bowl (emissive in-game)
    bpy.ops.object.transform_apply(scale=True)
    finish(l, bulb)
    export("street_light")

# ---------------------------------------------------------------- USPS-style blue collection box
def mailbox():
    reset()
    blue = mat("mail_blue", (0.02, 0.09, 0.32), metal=0.3, rough=0.45)
    dark = mat("mail_dark", (0.02, 0.04, 0.12), metal=0.4, rough=0.5)
    chrome = mat("mail_metal", (0.7, 0.7, 0.72), metal=0.9, rough=0.3)
    white = mat("mail_white", (0.85, 0.86, 0.88), rough=0.5)
    for sx in (-0.2, 0.2):
        box((0.06, 0.48, 0.3), (sx, 0, 0.15), dark, 0.012)
    box((0.52, 0.46, 0.72), (0, 0, 0.66), blue, 0.03)
    bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=0.26, depth=0.46, location=(0, 0, 1.02), rotation=(math.pi / 2, 0, 0))
    t = bpy.context.active_object; t.scale = (1, 1, 1)
    bm = bmesh.new(); bm.from_mesh(t.data)
    r = bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=(0, 0, 0), plane_no=(0, 1, 0), clear_inner=True)
    bmesh.ops.holes_fill(bm, edges=[e for e in bm.edges if e.is_boundary])    # closed half cylinder (local y = up)
    bm.to_mesh(t.data); bm.free()
    finish(t, blue, 0.02)
    box((0.36, 0.06, 0.16), (0, 0.24, 1.0), chrome, 0.015, rot=(0.35, 0, 0))     # pull-down chute
    box((0.3, 0.012, 0.03), (0, 0.235, 0.86), dark, 0.004)
    box((0.22, 0.01, 0.22), (0, 0.233, 0.6), white, 0.004)                     # label panel
    box((0.42, 0.012, 0.04), (0, 0.233, 0.36), chrome, 0.004)
    export("mailbox")

# ---------------------------------------------------------------- newspaper vending box on a pedestal
def newsbox():
    reset()
    red = mat("news_red", (0.42, 0.04, 0.03), metal=0.3, rough=0.4)
    dark = mat("news_dark", (0.05, 0.05, 0.05), metal=0.6, rough=0.45)
    glass = mat("news_glass", (0.55, 0.62, 0.66), metal=0.1, rough=0.08)
    paper = mat("news_paper", (0.82, 0.8, 0.74), rough=0.8)
    chrome = mat("news_metal", (0.7, 0.7, 0.72), metal=0.9, rough=0.3)
    cyl(0.05, 0.42, (0, 0, 0.21), dark, verts=12)
    box((0.44, 0.38, 0.03), (0, 0, 0.015), dark, 0.008)
    box((0.48, 0.42, 0.06), (0, 0, 0.44), dark, 0.01)
    box((0.48, 0.42, 0.52), (0, 0, 0.73), red, 0.025)
    box((0.5, 0.44, 0.04), (0, 0, 1.0), red, 0.012)
    box((0.38, 0.02, 0.24), (0, 0.205, 0.78), glass, 0.006)
    box((0.34, 0.02, 0.2), (0, 0.198, 0.78), paper, 0.0)
    box((0.42, 0.04, 0.03), (0, 0.22, 0.63), chrome, 0.01)                     # door handle bar
    box((0.1, 0.04, 0.12), (0.15, 0.22, 0.93), chrome, 0.01)                   # coin box
    export("newsbox")

# ---------------------------------------------------------------- park bench: cast-iron sides, wooden slats
def bench():
    reset()
    iron = mat("bench_iron", (0.03, 0.04, 0.035), metal=0.7, rough=0.45)
    wood = mat("bench_wood", (0.3, 0.17, 0.08), rough=0.65)
    for sx in (-0.72, 0.72):
        box((0.05, 0.06, 0.44), (sx, 0.2, 0.22), iron, 0.012)                    # front leg (+Y = road side)
        box((0.05, 0.06, 0.86), (sx, -0.2, 0.43), iron, 0.012, rot=(-0.16, 0, 0)) # back leg rising into backrest
        box((0.05, 0.5, 0.05), (sx, 0.0, 0.43), iron, 0.012)                     # seat rail
        box((0.06, 0.08, 0.04), (sx, 0.24, 0.62), iron, 0.012)                   # armrest
        box((0.04, 0.04, 0.2), (sx, 0.24, 0.52), iron, 0.01)
    for i in range(4):
        box((1.62, 0.085, 0.032), (0, 0.19 - i * 0.11, 0.47), wood, 0.008)
    for i in range(3):
        box((1.62, 0.028, 0.095), (0, -0.25 - i * 0.02, 0.6 + i * 0.12), wood, 0.008, rot=(-0.16, 0, 0))
    export("park_bench")

street_light(); mailbox(); newsbox(); bench()
