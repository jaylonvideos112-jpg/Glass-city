"""Lived-in yard props (Blender, bpy): what makes a Bully-style street feel inhabited, not like a store-asset town.
  yard_toter     wheeled trash bin (Toledo's city carts), lid and handle
  yard_bike      kid's bike leaning on its kickstand
  yard_chair     white plastic patio chair
  yard_grill     kettle grill on three legs
  yard_slide     small plastic kids' slide
  yard_shrub     foundation shrub: a lumpy clump of painted leaf cards (same style as tools/blender/bully_trees.py)
Exported to assets/models/<name>.glb; build_city.py places them per house ("m:<name>" props).
usage: bpyenv/bin/python tools/blender/yard_props.py -- OUTDIR"""
import sys, os, math, random
import bpy, bmesh
from mathutils import Vector, Matrix

OUT = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else sys.argv[1]
os.makedirs(OUT, exist_ok=True)

def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)

def mat(name, rgb, rough=0.6, metal=0.0):
    m = bpy.data.materials.get(name)
    if m: return m
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*rgb, 1); b.inputs["Roughness"].default_value = rough; b.inputs["Metallic"].default_value = metal
    return m

def obj(name, bm, material):
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    for p in me.polygons: p.use_smooth = False
    me.materials.append(material)
    o = bpy.data.objects.new(name, me); bpy.context.collection.objects.link(o); return o

def box(name, c, s, material, rot=0.0):
    bm = bmesh.new(); bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector(s), verts=bm.verts)
    bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(rot, 3, "Z"), verts=bm.verts)
    bmesh.ops.translate(bm, vec=Vector(c), verts=bm.verts)
    return obj(name, bm, material)

def cyl(name, p0, p1, r, material, seg=12):
    bm = bmesh.new()
    d = Vector(p1) - Vector(p0); L = d.length
    bmesh.ops.create_cone(bm, cap_ends=True, segments=seg, radius1=r, radius2=r, depth=L)
    q = d.normalized().to_track_quat("Z", "Y")
    bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=q.to_matrix(), verts=bm.verts)
    bmesh.ops.translate(bm, vec=(Vector(p0) + Vector(p1)) / 2, verts=bm.verts)
    return obj(name, bm, material)

def torus(name, c, R, r, axis, material):
    bm = bmesh.new()
    ring, seg = 20, 8
    verts = []
    for i in range(ring):
        a = 2 * math.pi * i / ring
        row = []
        for j in range(seg):
            b = 2 * math.pi * j / seg
            p = Vector(((R + r * math.cos(b)) * math.cos(a), r * math.sin(b), (R + r * math.cos(b)) * math.sin(a)))
            row.append(bm.verts.new(p))
        verts.append(row)
    for i in range(ring):
        for j in range(seg):
            bm.faces.new([verts[i][j], verts[(i + 1) % ring][j], verts[(i + 1) % ring][(j + 1) % seg], verts[i][(j + 1) % seg]])
    if axis == "x": bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(math.pi / 2, 3, "Z"), verts=bm.verts)
    bmesh.ops.translate(bm, vec=Vector(c), verts=bm.verts)
    return obj(name, bm, material)

def sphere(name, c, r, material, sz=1.0, cut_top=False):
    bm = bmesh.new(); bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=10, radius=r)
    if cut_top: bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.co.z > 0.001], context="VERTS")
    bmesh.ops.scale(bm, vec=(1, 1, sz), verts=bm.verts)
    bmesh.ops.translate(bm, vec=Vector(c), verts=bm.verts)
    o = obj(name, bm, material)
    for p in o.data.polygons: p.use_smooth = True
    return o

def export(name):
    p = os.path.join(OUT, name + ".glb")
    bpy.ops.export_scene.gltf(filepath=p, export_format="GLB")
    print("prop", name, p)

# -------------------------------------------------------------- toters (city trash / recycling carts), front = -Y
def toter(name, body_rgb, lid_rgb):
    reset()
    body = mat("toter_body", body_rgb, 0.5); lid = mat("toter_lid", lid_rgb, 0.45); blk = mat("rubber", (0.03, 0.03, 0.03), 0.8)
    grey = mat("axle", (0.25, 0.25, 0.26), 0.5, 0.4)
    bm = bmesh.new()
    # tapered body with rounded vertical corners: 0.54 x 0.62 at the bottom, 0.6 x 0.72 at the rim (1.0 m)
    def ring(z, hx, hy, r, seg=4):
        pts = []
        for cx, cy, a0 in ((hx - r, hy - r, 0), (-(hx - r), hy - r, 90), (-(hx - r), -(hy - r), 180), (hx - r, -(hy - r), 270)):
            for k in range(seg + 1):
                a = math.radians(a0 + 90 * k / seg)
                pts.append(bm.verts.new((cx + math.cos(a) * r, cy + math.sin(a) * r, z)))
        return pts
    rings = [ring(0.06, 0.27, 0.31, 0.06), ring(0.5, 0.285, 0.34, 0.07), ring(0.96, 0.3, 0.36, 0.08), ring(1.0, 0.31, 0.37, 0.08)]
    bm.faces.new(rings[0][::-1])
    for r0, r1 in zip(rings, rings[1:]):
        n = len(r0)
        for i in range(n): bm.faces.new([r0[i], r0[(i + 1) % n], r1[(i + 1) % n], r1[i]])
    bm.faces.new(rings[-1])
    o = obj("toter_body", bm, body)
    for p_ in o.data.polygons: p_.use_smooth = True
    # lid: overhanging slab with a hinge bar at the back and a molded grip at the front
    box("toter_lid", (0, 0.0, 1.035), (0.66, 0.8, 0.045), lid)
    box("toter_lid_lip", (0, -0.41, 1.0), (0.6, 0.04, 0.08), lid)
    box("toter_hinge", (0, 0.42, 1.0), (0.62, 0.07, 0.07), lid)
    # handle bar and wheel housing at the back
    cyl("toter_handle", (-0.24, 0.47, 0.96), (0.24, 0.47, 0.96), 0.018, grey)
    box("toter_wheelwell", (0, 0.36, 0.14), (0.62, 0.14, 0.2), body)
    cyl("toter_axle", (-0.33, 0.39, 0.12), (0.33, 0.39, 0.12), 0.015, grey)
    for sx in (-1, 1): cyl("toter_wheel%d" % sx, (sx * 0.3, 0.39, 0.12), (sx * 0.37, 0.39, 0.12), 0.12, blk, 16)
    # front lifting bar (the truck arm grabs it)
    box("toter_bar", (0, -0.37, 0.78), (0.42, 0.05, 0.05), lid)
    export(name)
toter("yard_toter", (0.11, 0.2, 0.13), (0.09, 0.17, 0.11))         # trash: dark green
toter("yard_toter_k", (0.05, 0.05, 0.055), (0.06, 0.06, 0.065))    # trash: black
toter("yard_toter_b", (0.07, 0.17, 0.42), (0.06, 0.14, 0.36))      # recycling: blue

# -------------------------------------------------------------- kid's bike on its kickstand
reset()
frame = mat("bike_frame", (0.62, 0.08, 0.08), 0.35, 0.3); tyre = mat("rubber", (0.03, 0.03, 0.03), 0.8); chrome = mat("chrome", (0.7, 0.7, 0.72), 0.25, 0.9)
R = 0.25
parts = [torus("wheel_f", (0, -0.42, R), R, 0.025, "x", tyre), torus("wheel_r", (0, 0.42, R), R, 0.025, "x", tyre),
         cyl("down", (0, -0.3, 0.55), (0, 0.05, 0.28), 0.022, frame), cyl("top", (0, -0.3, 0.6), (0, 0.18, 0.55), 0.02, frame),
         cyl("seat_t", (0, 0.05, 0.28), (0, 0.18, 0.6), 0.022, frame), cyl("chain", (0, 0.05, 0.28), (0, 0.42, R), 0.016, frame),
         cyl("stay", (0, 0.18, 0.55), (0, 0.42, R), 0.016, frame), cyl("fork", (0, -0.3, 0.6), (0, -0.42, R), 0.018, chrome),
         cyl("bar", (-0.25, -0.32, 0.75), (0.25, -0.32, 0.75), 0.016, chrome), cyl("stem", (0, -0.3, 0.6), (0, -0.32, 0.75), 0.016, chrome),
         box("seat", (0, 0.2, 0.66), (0.12, 0.24, 0.05), tyre)]
for o in parts: o.rotation_euler = (0, math.radians(9), 0)      # leaning on the stand
export("yard_bike")

# -------------------------------------------------------------- white plastic patio chair
reset()
wp = mat("plastic_white", (0.86, 0.86, 0.82), 0.45)
box("seat", (0, 0, 0.42), (0.5, 0.48, 0.04), wp)
box("back", (0, 0.24, 0.72), (0.5, 0.04, 0.55), wp, 0).rotation_euler = (math.radians(-12), 0, 0)
for sx in (-1, 1):
    for sy in (-1, 1): cyl("leg", (sx * 0.22, sy * 0.21, 0.0), (sx * 0.2, sy * 0.19, 0.42), 0.022, wp)
    box("arm", (sx * 0.25, 0.0, 0.62), (0.05, 0.46, 0.03), wp)
export("yard_chair")

# -------------------------------------------------------------- kettle grill
reset()
bk = mat("grill_black", (0.03, 0.03, 0.03), 0.4, 0.2); st = mat("chrome", (0.7, 0.7, 0.72), 0.25, 0.9)
sphere("bowl", (0, 0, 0.72), 0.3, bk, 0.8, cut_top=True)
sphere("lid", (0, 0, 0.72), 0.3, bk, 0.7).scale = (1, 1, 1)
bpy.data.objects["lid"].data.transform(Matrix.Translation((0, 0, 0)))
# drop the lower half of the lid sphere
me = bpy.data.objects["lid"].data
bm = bmesh.new(); bm.from_mesh(me); bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.co.z < 0.72], context="VERTS"); bm.to_mesh(me); bm.free()
cyl("handle", (-0.08, 0, 0.95), (0.08, 0, 0.95), 0.015, st)
for k in range(3):
    a = k * 2 * math.pi / 3
    cyl("leg", (math.cos(a) * 0.12, math.sin(a) * 0.12, 0.5), (math.cos(a) * 0.3, math.sin(a) * 0.3, 0.0), 0.012, st)
export("yard_grill")

# -------------------------------------------------------------- kids' plastic slide
reset()
red = mat("plastic_red", (0.7, 0.1, 0.07), 0.45); yel = mat("plastic_yellow", (0.85, 0.65, 0.1), 0.45); blu = mat("plastic_blue", (0.1, 0.25, 0.6), 0.45)
box("platform", (0, 0.55, 0.85), (0.6, 0.45, 0.06), blu)
for sx in (-1, 1):
    cyl("post", (sx * 0.27, 0.75, 0.0), (sx * 0.27, 0.75, 0.88), 0.03, yel); cyl("post2", (sx * 0.27, 0.35, 0.0), (sx * 0.27, 0.35, 0.88), 0.03, yel)
    box("rail", (sx * 0.27, -0.35, 0.5), (0.04, 1.4, 0.12), red).rotation_euler = (math.radians(-33), 0, 0)
s = box("chute", (0, -0.35, 0.44), (0.5, 1.45, 0.03), red); s.rotation_euler = (math.radians(-33), 0, 0)
for k in range(4): box("step%d" % k, (0, 0.8 + 0.0, 0.18 + k * 0.2), (0.5, 0.12, 0.03), yel)
export("yard_slide")

# -------------------------------------------------------------- foundation shrub (painted leaf cards)
reset()
from PIL import Image, ImageDraw, ImageFilter
rng = random.Random(5); S = 256
im = Image.new("RGBA", (S, S), (0, 0, 0, 0)); dr = ImageDraw.Draw(im)
for i in range(120):
    r = rng.uniform(0, 0.46) ** 0.8 * S; a = rng.uniform(0, 2 * math.pi)
    cx, cy = S / 2 + math.cos(a) * r, S / 2 + math.sin(a) * r
    L = rng.uniform(12, 20); W = L * 0.55; light = 0.7 + 0.5 * (1 - cy / S) + rng.uniform(-0.1, 0.1)
    col = tuple(int(min(255, c * 255 * light)) for c in (0.16, 0.3, 0.1)) + (255,)
    dr.ellipse([cx - L / 2, cy - W / 2, cx + L / 2, cy + W / 2], fill=col)
im = im.filter(ImageFilter.SMOOTH); tex = os.path.join(OUT, "yard_shrub_leaf.png"); im.save(tex)
m = bpy.data.materials.new("shrub_leaf"); m.use_nodes = True; nt = m.node_tree; b = nt.nodes["Principled BSDF"]
tx = nt.nodes.new("ShaderNodeTexImage"); tx.image = bpy.data.images.load(tex)
nt.links.new(tx.outputs["Color"], b.inputs["Base Color"]); nt.links.new(tx.outputs["Alpha"], b.inputs["Alpha"])
bm = bmesh.new(); uv = bm.loops.layers.uv.new("UVMap"); normals = []
centre = Vector((0, 0, 0.45))
for lobe in range(4):
    c = centre + Vector((rng.uniform(-0.3, 0.3), rng.uniform(-0.2, 0.2), rng.uniform(-0.1, 0.15)))
    for k in range(45):
        u = rng.uniform(-0.4, 1); t = rng.uniform(0, 2 * math.pi); q = math.sqrt(max(0, 1 - u * u))
        d = Vector((q * math.cos(t), q * math.sin(t), u))
        p = c + Vector((d.x * 0.5, d.y * 0.4, d.z * 0.42)) * rng.uniform(0.7, 1.0)
        n = (p - centre).normalized(); x = n.orthogonal().normalized(); y = n.cross(x); hs = rng.uniform(0.16, 0.24)
        vs = [bm.verts.new(p + (x * sx + y * sy) * hs) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        f = bm.faces.new(vs)
        for l, (a_, b_) in zip(f.loops, ((0, 0), (1, 0), (1, 1), (0, 1))): l[uv].uv = (a_, b_)
        normals += [tuple(n)] * 4
me = bpy.data.meshes.new("shrub"); bm.to_mesh(me); bm.free(); me.materials.append(m)
try: me.normals_split_custom_set_from_vertices(normals)
except Exception: pass
o = bpy.data.objects.new("shrub", me); bpy.context.collection.objects.link(o)
export("yard_shrub")
