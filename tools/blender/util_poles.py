"""Blender (bpy) utility poles for GLASS CITY's lived-in streets and alleys (Toledo neighbourhoods have wooden
poles with overhead wires along almost every alley, and along streets that have no alley).
Origin = pole base on the ground; Blender +Y = along the wire run (the pole's yaw follows the street/alley), so
the cross-arm runs across it on X. Wire attachment points (scripts/utility_wires.gd must match):
  primaries   x = -1.0, -0.4, +1.0  at z = 10.12  (insulators on the cross-arm)
  secondary   x = +0.2             at z = 8.0    (triplex rack)
  phone/cable x = +0.18            at z = 6.4
Models: util_pole (plain), util_pole_t (with a transformer can and a drop), util_pole_f (flyers stapled on).
usage: bpyenv/bin/python tools/blender/util_poles.py OUTDIR"""
import sys, os, math
sys.argv = [sys.argv[0], sys.argv[1]]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy
from street_props import reset, mat, box, cyl, export


def pole(name, transformer=False, flyers=False):
    reset()
    wood = mat("pole_wood", (0.30, 0.24, 0.18), rough=0.92)
    arm = mat("pole_arm", (0.36, 0.3, 0.23), rough=0.9)
    ins = mat("pole_ins", (0.42, 0.5, 0.42), rough=0.35)          # green-grey glass insulators
    steel = mat("pole_steel", (0.45, 0.46, 0.46), metal=0.7, rough=0.5)
    cyl(0.16, 10.6, (0, 0, 5.3), wood, verts=10, r2=0.12)           # tapered shaft
    box((2.5, 0.1, 0.11), (0, 0, 9.98), arm, bevel=0)               # cross-arm
    for sx in (-1, 1):                                               # braces
        b = box((0.04, 0.04, 0.95), (sx * 0.32, 0, 9.55), steel, bevel=0)
        b.rotation_euler = (0, sx * math.radians(-40), 0)
    for x in (-1.0, -0.4, 1.0):                                      # insulators
        cyl(0.045, 0.14, (x, 0, 10.1), ins, verts=8)
    box((0.08, 0.12, 0.22), (0.17, 0, 8.0), steel, bevel=0)         # secondary rack
    box((0.06, 0.1, 0.12), (0.15, 0, 6.4), steel, bevel=0)          # cable clamp
    for z in range(3, 9):                                            # step bolts
        cyl(0.012, 0.26, (0.0, 0.0, z * 0.9 + 0.4), steel, verts=5, rot=(0, math.pi / 2, (z % 2) * math.pi / 2))
    box((0.1, 0.012, 0.08), (0, -0.155, 2.6), mat("pole_tag", (0.75, 0.7, 0.3), metal=0.6, rough=0.4), bevel=0)  # pole tag
    if transformer:
        can = mat("pole_xfmr", (0.5, 0.52, 0.5), metal=0.4, rough=0.55)
        cyl(0.27, 0.85, (-0.43, 0, 8.6), can, verts=14)
        cyl(0.29, 0.06, (-0.43, 0, 9.05), can, verts=14)
        cyl(0.025, 0.9, (-0.43, 0, 9.45), ins, verts=6)
    if flyers:                                                       # lost-cat / yard-sale flyers, staples, tape
        for i, (z, a, col) in enumerate(((1.55, 0.3, (0.92, 0.9, 0.82)), (1.85, -0.9, (0.95, 0.85, 0.35)),
                                          (1.35, 1.8, (0.9, 0.6, 0.7)), (2.05, 2.6, (0.85, 0.88, 0.9)))):
            r = 0.165 - z * 0.002
            f = box((0.2, 0.004, 0.27), (math.sin(a) * r, -math.cos(a) * r, z), mat("pole_flyer%d" % i, col, rough=0.85), bevel=0)
            f.rotation_euler = (0, 0, a)
    export(name)


if __name__ == "__main__":
    import street_props; street_props.OUT = sys.argv[1]
    pole("util_pole")
    pole("util_pole_t", transformer=True)
    pole("util_pole_f", flyers=True)


def manhole():
    """Cast-iron manhole cover, 0.64 m across, sitting 1 cm proud of the road; raised waffle pattern + ring."""
    reset()
    iron = mat("mh_iron", (0.11, 0.1, 0.095), metal=0.6, rough=0.55)
    rust = mat("mh_rust", (0.24, 0.13, 0.08), rough=0.85)
    cyl(0.36, 0.02, (0, 0, 0.0), rust, verts=24)                    # rusty frame ring
    cyl(0.32, 0.03, (0, 0, 0.005), iron, verts=24)
    for i in range(-3, 4):
        box((0.48 - abs(i) * 0.05, 0.03, 0.008), (0, i * 0.075, 0.022), iron, bevel=0)
        box((0.03, 0.48 - abs(i) * 0.05, 0.008), (i * 0.075, 0, 0.022), iron, bevel=0)
    export("manhole")


def storm_grate():
    """Curb-side storm drain: a steel grate 0.9 x 0.55 in a concrete apron. +Y = toward the curb."""
    reset()
    conc = mat("sg_conc", (0.42, 0.41, 0.39), rough=0.95)
    iron = mat("sg_iron", (0.09, 0.085, 0.08), metal=0.6, rough=0.5)
    box((1.15, 0.8, 0.02), (0, 0, 0.0), conc, bevel=0)
    box((0.9, 0.55, 0.012), (0, 0, 0.012), mat("sg_hole", (0.01, 0.01, 0.01), rough=1.0), bevel=0)
    for i in range(9):
        box((0.03, 0.55, 0.02), (-0.4 + i * 0.1, 0, 0.018), iron, bevel=0)
    box((0.9, 0.03, 0.02), (0, -0.26, 0.018), iron, bevel=0); box((0.9, 0.03, 0.02), (0, 0.26, 0.018), iron, bevel=0)
    export("storm_grate")


if __name__ == "__main__":
    manhole(); storm_grate()


def fence_panel(name, kind):
    """2.4 m back-yard fence panel centred on the origin along X, front = +Y. chain: 1.22 m galvanized posts, top
    rail, wire mesh (alpha texture chainlink.png, UV 0.6 m tiles); wood: 1.83 m privacy boards (fence_wood.png)
    with rails on the back. Instanced per chunk (build_city.py yard fences), so fences cost no chunk geometry."""
    reset()
    import bmesh
    if kind == "chain":
        H, tex, tile = 1.22, "chainlink", 0.6
        pm = mat("fence_metal", (0.62, 0.64, 0.63), metal=0.6, rough=0.45)
        cyl(0.025, H + 0.05, (1.2, 0, (H + 0.05) / 2), pm, verts=8)
        box((2.4, 0.035, 0.035), (0, 0, H - 0.01), pm, bevel=0)
    else:
        H, tex, tile = 1.83, "fence_wood", 1.8
        pm = mat("fence_post", (0.42, 0.33, 0.24), rough=0.95)
        box((0.09, 0.09, H + 0.05), (1.2, -0.06, (H + 0.05) / 2), pm, bevel=0)
        for z in (0.3, 1.5):
            box((2.4, 0.04, 0.09), (0, -0.04, z), pm, bevel=0)
    im = mat(tex, (1, 1, 1), rough=0.5 if kind == "chain" else 0.95)
    nt = im.node_tree; ti = nt.nodes.new("ShaderNodeTexImage")
    ti.image = bpy.data.images.load(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "textures", tex + ".png"))
    nt.links.new(ti.outputs["Color"], nt.nodes["Principled BSDF"].inputs["Base Color"])
    if kind == "chain":
        nt.links.new(ti.outputs["Alpha"], nt.nodes["Principled BSDF"].inputs["Alpha"]); im.blend_method = "CLIP"
    me = bpy.data.meshes.new("panel"); b = bmesh.new()
    vs = [b.verts.new(v) for v in ((-1.2, 0, 0.02), (1.2, 0, 0.02), (1.2, 0, H), (-1.2, 0, H))]
    f = b.faces.new(vs); uvl = b.loops.layers.uv.new()
    vt = H / tile if kind == "chain" else 1.0
    for lp, uv in zip(f.loops, ((0, 0), (2.4 / tile, 0), (2.4 / tile, vt), (0, vt))): lp[uvl].uv = uv
    b.to_mesh(me); b.free()
    o = bpy.data.objects.new("panel", me); bpy.context.collection.objects.link(o); me.materials.append(im)
    export(name)


if __name__ == "__main__":
    fence_panel("fence_chain", "chain"); fence_panel("fence_wood", "wood")
