"""Blender (bpy) park & sports equipment, exported as .glb into assets/models/ (placed from OSM leisure=pitch /
playground by tools/pipeline/build_city.py). Blender +Y = Godot -Z = the prop's 'front'.
usage: bpyenv/bin/python tools/blender/park_props.py OUTDIR"""
import sys, math, os
sys.argv = [sys.argv[0], sys.argv[1]]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy
from street_props import reset, mat, finish, box, cyl, export   # shared helpers (module body only defines functions)

def tube(p0, p1, r, m, verts=10):
    """cylinder from p0 to p1 (world points)."""
    import mathutils
    a, b = mathutils.Vector(p0), mathutils.Vector(p1)
    d = b - a; L = d.length
    rot = d.to_track_quat("Z", "Y").to_euler()
    return cyl(r, L, tuple((a + b) / 2), m, verts=verts, rot=tuple(rot))

# ------------------------------------------------------------------ playground: deck tower, slide, swings
def playground():
    reset()
    post = mat("pg_post", (0.10, 0.32, 0.18), metal=0.6, rough=0.45)        # green powder-coated posts
    deck = mat("pg_deck", (0.20, 0.20, 0.22), metal=0.4, rough=0.6)
    slide = mat("pg_slide", (0.95, 0.72, 0.08), rough=0.35)                 # yellow plastic
    roof = mat("pg_roof", (0.10, 0.35, 0.75), rough=0.4)                    # blue canopy
    rail = mat("pg_rail", (0.85, 0.15, 0.10), metal=0.3, rough=0.4)
    chain = mat("pg_chain", (0.55, 0.56, 0.58), metal=0.9, rough=0.35)
    seat = mat("pg_seat", (0.08, 0.08, 0.08), rough=0.7)
    # 2.4 x 2.4 m tower, deck at 1.5 m
    for x in (-1.2, 1.2):
        for y in (-1.2, 1.2):
            cyl(0.06, 3.6, (x, y, 1.8), post, verts=12)
    box((2.5, 2.5, 0.08), (0, 0, 1.5), deck, bevel=0.01)
    for (x0, y0, x1, y1) in ((-1.2, -1.2, 1.2, -1.2), (-1.2, -1.2, -1.2, 1.2), (1.2, 1.2, -0.2, 1.2)):
        tube((x0, y0, 2.4), (x1, y1, 2.4), 0.03, rail)
    bpy.ops.mesh.primitive_cone_add(vertices=4, radius1=2.1, radius2=0.05, depth=1.0, location=(0, 0, 4.0), rotation=(0, 0, math.pi / 4))
    finish(bpy.context.active_object, roof, smooth=False)
    # slide out the +X side
    bpy.ops.mesh.primitive_cube_add(size=1, location=(2.55, 0.4, 0.8), rotation=(0, math.radians(31), 0))
    o = bpy.context.active_object; o.scale = (3.0, 0.7, 0.06); bpy.ops.object.transform_apply(scale=True); finish(o, slide, 0.02)
    for s in (-1, 1):
        bpy.ops.mesh.primitive_cube_add(size=1, location=(2.55, 0.4 + s * 0.37, 0.95), rotation=(0, math.radians(31), 0))
        o = bpy.context.active_object; o.scale = (3.0, 0.05, 0.3); bpy.ops.object.transform_apply(scale=True); finish(o, slide, 0.01)
    # ladder on -X
    for y in (-0.35, 0.35): tube((-1.9, y, 0.0), (-1.25, y, 1.5), 0.03, post)
    for k in range(1, 5):
        t = k / 5.0; tube((-1.9 + 0.65 * t, -0.35, 1.5 * t), (-1.9 + 0.65 * t, 0.35, 1.5 * t), 0.02, rail)
    # swing set beside it (-Y), A-frame 2.4 m high, 2 swings
    for x in (-1.6, 1.6):
        tube((x, -4.2, 0), (x, -3.4, 2.4), 0.05, post); tube((x, -2.6, 0), (x, -3.4, 2.4), 0.05, post)
    tube((-1.7, -3.4, 2.4), (1.7, -3.4, 2.4), 0.06, post)
    for x in (-0.7, 0.7):
        for dx in (-0.22, 0.22): tube((x + dx, -3.4, 2.4), (x + dx, -3.4, 0.5), 0.008, chain, verts=6)
        box((0.5, 0.18, 0.04), (x, -3.4, 0.48), seat, bevel=0.01)
    export("park_playground")

def bball_hoop():
    reset()
    pole = mat("hoop_pole", (0.18, 0.2, 0.22), metal=0.7, rough=0.4)
    board = mat("hoop_board", (0.95, 0.95, 0.93), rough=0.35)
    rim = mat("hoop_rim", (0.9, 0.3, 0.05), metal=0.6, rough=0.35)
    net = mat("hoop_net", (0.92, 0.92, 0.92), rough=0.8)
    cyl(0.08, 3.4, (0, -1.0, 1.7), pole, verts=12)
    tube((0, -1.0, 3.3), (0, -0.1, 3.3), 0.06, pole)
    box((1.8, 0.05, 1.05), (0, 0, 3.4), board, bevel=0.01)
    bpy.ops.mesh.primitive_torus_add(major_radius=0.23, minor_radius=0.012, location=(0, 0.3, 3.05))
    finish(bpy.context.active_object, rim)
    bpy.ops.mesh.primitive_cone_add(vertices=12, radius1=0.22, radius2=0.14, depth=0.42, location=(0, 0.3, 2.83), end_fill_type="NOTHING")
    finish(bpy.context.active_object, net, smooth=False)
    export("park_hoop")

def soccer_goal():
    reset()
    w = mat("goal_white", (0.95, 0.95, 0.95), metal=0.3, rough=0.4)
    net = mat("goal_net", (0.85, 0.85, 0.85), rough=0.9)
    W, H, D = 7.32, 2.44, 1.8
    for x in (-W / 2, W / 2):
        tube((x, 0, 0), (x, 0, H), 0.06, w); tube((x, 0, H), (x, -D * 0.5, H), 0.03, w); tube((x, -D * 0.5, H), (x, -D, 0), 0.03, w)
    tube((-W / 2, 0, H), (W / 2, 0, H), 0.06, w)
    tube((-W / 2, -D, 0), (W / 2, -D, 0), 0.03, w)
    # net: thin slabs (back + roof)
    bpy.ops.mesh.primitive_plane_add(size=1, location=(0, -D * 0.75, H * 0.5), rotation=(math.radians(90 - 20), 0, 0))
    o = bpy.context.active_object; o.scale = (W, H * 1.05, 1); bpy.ops.object.transform_apply(scale=True); finish(o, net, smooth=False)
    export("park_goal")

def tennis_net():
    reset()
    post = mat("tn_post", (0.12, 0.25, 0.15), metal=0.6, rough=0.4)
    net = mat("tn_net", (0.08, 0.08, 0.08), rough=0.9)
    band = mat("tn_band", (0.95, 0.95, 0.95), rough=0.5)
    L = 12.8
    for x in (-L / 2, L / 2): cyl(0.05, 1.07, (x, 0, 0.535), post, verts=10)
    box((L, 0.01, 0.9), (0, 0, 0.5), net, bevel=0)
    box((L, 0.03, 0.06), (0, 0, 0.95), band, bevel=0)
    export("park_tennis_net")

def backstop():
    reset()
    pole = mat("bs_pole", (0.55, 0.56, 0.57), metal=0.8, rough=0.35)
    fence = mat("bs_fence", (0.6, 0.62, 0.63), metal=0.7, rough=0.5)
    R, H = 6.0, 4.5
    pts = [(R * math.sin(a), R * math.cos(a)) for a in [math.radians(d) for d in range(-60, 61, 20)]]
    for x, y in pts: cyl(0.05, H, (x, y, H / 2), pole, verts=8)
    for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
        L = math.hypot(x1 - x0, y1 - y0); ang = math.atan2(y1 - y0, x1 - x0)
        bpy.ops.mesh.primitive_plane_add(size=1, location=((x0 + x1) / 2, (y0 + y1) / 2, H / 2), rotation=(math.radians(90), 0, ang))
        o = bpy.context.active_object; o.scale = (L, H, 1); bpy.ops.object.transform_apply(scale=True); finish(o, fence, smooth=False)
    export("park_backstop")

def goalpost():
    reset()
    y = mat("gp_yellow", (0.95, 0.8, 0.1), metal=0.4, rough=0.4)
    tube((0, -1.5, 0), (0, -1.5, 2.6), 0.09, y); tube((0, -1.5, 2.6), (0, 0, 3.05), 0.08, y)
    tube((-2.82, 0, 3.05), (2.82, 0, 3.05), 0.07, y)
    for x in (-2.82, 2.82): tube((x, 0, 3.05), (x, 0, 9.1), 0.05, y)
    export("park_goalpost")

for f in (playground, bball_hoop, soccer_goal, tennis_net, backstop, goalpost): f()
