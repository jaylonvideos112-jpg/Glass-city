"""Bully-style trees (Blender): full, rounded canopies of painted leaf clusters on a sturdy trunk and branches.

Two shapes (round maple-like, tall oval elm-like) x two sizes, to replace the photo-scan tree impostors in the Bully
look. The canopy is made of a few overlapping lobes; each lobe is covered with leaf cards that carry a painted
leaf-cluster texture (generated here: soft, stylised leaves in a few greens). Card normals point out from the
canopy centre, so the crown lights as one soft rounded mass, like Bully's trees. Exported as .glb for
tools/dbg/bake_impostor.gd, which bakes the billboards into textures_bully/trees/ (same names as textures/trees/).
usage: bpyenv/bin/python tools/blender/bully_trees.py OUTDIR"""
import sys, os, math, random
import bpy, bmesh
import numpy as np
from mathutils import Vector, Matrix

OUT = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else sys.argv[1]
os.makedirs(OUT, exist_ok=True)

def leaf_texture(path, seed, base=(0.24, 0.47, 0.13)):
    """512px painted leaf cluster: ~160 rounded leaves, light from the top, darker toward the middle."""
    from PIL import Image, ImageDraw, ImageFilter
    rng = random.Random(seed); S = 512
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0)); dr = ImageDraw.Draw(im)
    for i in range(170):
        r = rng.uniform(0.0, 0.46) ** 0.8 * S; a = rng.uniform(0, 2 * math.pi)
        cx, cy = S / 2 + math.cos(a) * r, S / 2 + math.sin(a) * r
        L = rng.uniform(26, 44); W = L * rng.uniform(0.45, 0.6); rot = rng.uniform(0, math.pi)
        light = 0.75 + 0.5 * (1 - cy / S) + rng.uniform(-0.12, 0.12)
        col = tuple(int(min(255, c * 255 * light * rng.uniform(0.9, 1.1))) for c in base) + (255,)
        pts = []
        for k in range(14):
            t = k / 14 * 2 * math.pi
            x, y = math.cos(t) * L / 2, math.sin(t) * W / 2 * (1 - 0.35 * math.cos(t))
            pts.append((cx + x * math.cos(rot) - y * math.sin(rot), cy + x * math.sin(rot) + y * math.cos(rot)))
        dr.polygon(pts, fill=col)
    im = im.filter(ImageFilter.SMOOTH)
    im.save(path)

def mat_leaf(path, name):
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; b = nt.nodes["Principled BSDF"]
    tx = nt.nodes.new("ShaderNodeTexImage"); tx.image = bpy.data.images.load(path)
    nt.links.new(tx.outputs["Color"], b.inputs["Base Color"]); nt.links.new(tx.outputs["Alpha"], b.inputs["Alpha"])
    b.inputs["Roughness"].default_value = 0.8
    m.blend_method = "CLIP" if hasattr(m, "blend_method") else None
    return m

def mat_bark(name):
    m = bpy.data.materials.new(name); m.use_nodes = True
    m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.11, 0.08, 0.055, 1)
    m.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.9
    return m

def tube(bm, p0, p1, r0, r1, seg=10):
    d = (p1 - p0); L = d.length; z = d.normalized()
    x = z.orthogonal().normalized(); y = z.cross(x)
    rings = []
    for (p, r) in ((p0, r0), (p1, r1)):
        rings.append([bm.verts.new(p + (x * math.cos(2 * math.pi * k / seg) + y * math.sin(2 * math.pi * k / seg)) * r) for k in range(seg)])
    for k in range(seg):
        bm.faces.new([rings[0][k], rings[0][(k + 1) % seg], rings[1][(k + 1) % seg], rings[1][k]])

def tree(name, kind, height, seed):
    rng = random.Random(seed)
    for o in list(bpy.data.objects): bpy.data.objects.remove(o)
    bark = mat_bark("bark")
    tex = os.path.join(OUT, f"{name}_leaf.png"); leaf_texture(tex, seed, base=(0.22, 0.45, 0.12) if kind == "round" else (0.2, 0.42, 0.13))
    leaf = mat_leaf(tex, "a_leaf")
    # trunk and main branches
    bm = bmesh.new()
    trunk_h = height * (0.38 if kind == "round" else 0.3)
    top = Vector((rng.uniform(-0.2, 0.2), rng.uniform(-0.2, 0.2), trunk_h))
    tube(bm, Vector((0, 0, -0.2)), top, 0.3 * height / 9, 0.2 * height / 9, 12)
    crown_c = Vector((0, 0, height * (0.64 if kind == "round" else 0.62)))
    rx = height * (0.42 if kind == "round" else 0.3); rz = height * (0.36 if kind == "round" else 0.42)
    for i in range(5):
        a = i / 5 * 2 * math.pi + rng.uniform(-0.3, 0.3)
        end = crown_c + Vector((math.cos(a) * rx * 0.55, math.sin(a) * rx * 0.55, rng.uniform(-0.2, 0.3) * rz))
        tube(bm, top, end, 0.14 * height / 9, 0.05 * height / 9, 8)
    me = bpy.data.meshes.new(name + "_wood"); bm.to_mesh(me); bm.free()
    wood = bpy.data.objects.new(name + "_wood", me); bpy.context.collection.objects.link(wood); me.materials.append(bark)
    # canopy lobes + leaf cards
    lobes = [(crown_c, 1.0)]
    for i in range(6 if kind == "round" else 5):
        a = rng.uniform(0, 2 * math.pi); e = rng.uniform(-0.4, 0.7)
        lobes.append((crown_c + Vector((math.cos(a) * rx * 0.5, math.sin(a) * rx * 0.5, e * rz * 0.5)), rng.uniform(0.55, 0.75)))
    bm = bmesh.new(); uv = bm.loops.layers.uv.new("UVMap")
    normals = []
    card = height * 0.13
    for (c, s) in lobes:
        n = int(130 * s)
        for k in range(n):
            # point on the lobe surface (ellipsoid), a little inside
            u = rng.uniform(-1, 1); t = rng.uniform(0, 2 * math.pi); q = math.sqrt(1 - u * u)
            dirv = Vector((q * math.cos(t), q * math.sin(t), u))
            p = c + Vector((dirv.x * rx * s, dirv.y * rx * s, dirv.z * rz * s)) * rng.uniform(0.75, 1.0)
            nrm = (p - crown_c + Vector((0, 0, rz * 0.25))).normalized()
            # card facing outward, random spin
            zax = nrm; xax = zax.orthogonal().normalized(); yax = zax.cross(xax)
            spin = rng.uniform(0, 2 * math.pi)
            xr = xax * math.cos(spin) + yax * math.sin(spin); yr = zax.cross(xr)
            hs = card * rng.uniform(0.8, 1.25) / 2
            vs = [bm.verts.new(p + (xr * sx + yr * sy) * hs) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
            f = bm.faces.new(vs)
            for l, (a_, b_) in zip(f.loops, ((0, 0), (1, 0), (1, 1), (0, 1))): l[uv].uv = (a_, b_)
            normals += [tuple(nrm)] * 4
    me = bpy.data.meshes.new(name + "_leaves"); bm.to_mesh(me); bm.free()
    me.materials.append(leaf)
    # outward custom normals: the crown shades as one rounded mass
    try:
        me.normals_split_custom_set_from_vertices(normals)
    except Exception as ex: print("normals", ex)
    lv = bpy.data.objects.new(name + "_leaves", me); bpy.context.collection.objects.link(lv)
    path = os.path.join(OUT, name + ".glb")
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", export_normals=True)
    print("tree", name, path)

bpy.ops.wm.read_factory_settings(use_empty=True)
for name, kind, h, seed in (("tree_small_02_a", "round", 9.0, 11), ("tree_small_02_b", "round", 7.0, 12),
                            ("island_tree_02_c", "oval", 11.0, 13), ("island_tree_02_d", "oval", 8.5, 14)):
    tree(name, kind, h, seed)
