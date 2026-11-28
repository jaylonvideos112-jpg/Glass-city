"""Photoreal Blender build of one map area (owner, 2026-11-28: "I want the map made in blender first to be photo
accurate, then converted when done"; fully photoreal; pilot = Weiler Homes, the real complex behind the story's
Eastport Homes, East Toledo).

Input: the area JSON from tools/photoreal/extract_area.py (OSM footprints/roads/areas + LiDAR heights) and trees
from lidar/trees.json. Materials, sky and props are CC0 Poly Haven assets (tools/photoreal/fetch_assets.py).
Building looks follow typologies matched by hand to reference photos (county parcel photos are reference only,
never shipped). Typology "weiler_row": two-storey buff-brick townhouse rows, low hip roof in brown shingles with
white aluminium fascia and gutters, paired brown entry doors under small copper-green canopies on black iron posts,
dark bronze sliding windows with stone sills, recessed brown panels with white downspouts between unit pairs,
concrete stoops and a walk from every entry to the sidewalk.

Coordinates: plan metres (x east, y north) minus the area centre; z up; lawn level 0.15, road 0.

usage: bpyenv/bin/python tools/blender/../photoreal/build_area.py AREA.json ASSETS OUT.blend [render=PNG]
       [cam=x,y,z:tx,ty,tz] [samples=96] [res=1280x720] [grass_r=60]"""
import sys, os, json, math, random
import bpy, bmesh
import numpy as np
from mathutils import Vector
import shapely
from shapely.geometry import Polygon, LineString, MultiPolygon, box as sbox, Point
from shapely.ops import unary_union

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
AREA, ASSETS, OUT = os.path.abspath(argv[0]), os.path.abspath(argv[1]), os.path.abspath(argv[2])
OPT = dict(a.split("=", 1) for a in argv[3:] if "=" in a)
D = json.load(open(AREA))
X0, Y0, X1, Y1 = D["bbox"]
CX, CY = (X0 + X1) / 2, (Y0 + Y1) / 2
LAWN = 0.15
rng = random.Random(7)


def L(p): return (p[0] - CX, p[1] - CY)


bpy.ops.wm.read_factory_settings(use_empty=True)
SC = bpy.context.scene
COL = {}


def coll(name):
    if name not in COL:
        c = bpy.data.collections.new(name); SC.collection.children.link(c); COL[name] = c
    return COL[name]


# ---------------------------------------------------------------- materials
def img(path, non_color=False):
    im = bpy.data.images.load(path, check_existing=True)
    if non_color: im.colorspace_settings.name = "Non-Color"
    return im


def pbr(name, tex, size_m, tint=None, rough_k=1.0, bump=1.0, box=True, weather=0.0):
    """Poly Haven PBR set, world-scale mapping (object = world coords: every mesh has an identity transform)."""
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; N = nt.nodes; Lk = nt.links
    bs = N["Principled BSDF"]
    tc = N.new("ShaderNodeTexCoord"); mp = N.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (1 / size_m, 1 / size_m, 1 / size_m)
    Lk.new(tc.outputs["Object"], mp.inputs["Vector"])
    d = os.path.join(ASSETS, "tex", tex)

    def tx(f, nc):
        t = N.new("ShaderNodeTexImage"); t.image = img(os.path.join(d, f), nc)
        if box: t.projection = "BOX"; t.projection_blend = 0.25
        Lk.new(mp.outputs["Vector"], t.inputs["Vector"]); return t
    c = tx("diff.jpg", False)
    col = c.outputs["Color"]
    if tint:
        mix = N.new("ShaderNodeMix"); mix.data_type = "RGBA"; mix.blend_type = "MULTIPLY"
        mix.inputs["Factor"].default_value = 1.0
        Lk.new(col, mix.inputs["A"]); mix.inputs["B"].default_value = (*tint, 1)
        col = mix.outputs["Result"]
    if weather > 0:
        # grime splashed up from the ground (fades out by ~0.7 m) and faint vertical rain streaks
        geo = N.new("ShaderNodeNewGeometry"); sep = N.new("ShaderNodeSeparateXYZ"); Lk.new(geo.outputs["Position"], sep.inputs[0])
        ramp = N.new("ShaderNodeMapRange"); ramp.inputs["From Min"].default_value = 0.0; ramp.inputs["From Max"].default_value = 0.75
        ramp.inputs["To Min"].default_value = 1.0; ramp.inputs["To Max"].default_value = 0.0
        Lk.new(sep.outputs["Z"], ramp.inputs["Value"])
        nz = N.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = 3.0; nz.inputs["Detail"].default_value = 6
        Lk.new(geo.outputs["Position"], nz.inputs["Vector"])
        st = N.new("ShaderNodeTexNoise"); st.inputs["Scale"].default_value = 1.0; st.inputs["Detail"].default_value = 2
        sm = N.new("ShaderNodeMapping"); sm.inputs["Scale"].default_value = (9.0, 9.0, 0.35)
        Lk.new(geo.outputs["Position"], sm.inputs["Vector"]); Lk.new(sm.outputs["Vector"], st.inputs["Vector"])
        g1 = N.new("ShaderNodeMath"); g1.operation = "MULTIPLY"; Lk.new(ramp.outputs["Result"], g1.inputs[0]); Lk.new(nz.outputs["Fac"], g1.inputs[1])
        s1 = N.new("ShaderNodeMapRange"); s1.inputs["From Min"].default_value = 0.55; s1.inputs["From Max"].default_value = 0.8
        s1.inputs["To Max"].default_value = 0.35; Lk.new(st.outputs["Fac"], s1.inputs["Value"])
        ad = N.new("ShaderNodeMath"); ad.operation = "ADD"; ad.use_clamp = True
        Lk.new(g1.outputs[0], ad.inputs[0]); Lk.new(s1.outputs["Result"], ad.inputs[1])
        wk = N.new("ShaderNodeMath"); wk.operation = "MULTIPLY"; wk.inputs[1].default_value = weather
        Lk.new(ad.outputs[0], wk.inputs[0])
        dk = N.new("ShaderNodeMix"); dk.data_type = "RGBA"; dk.blend_type = "MULTIPLY"
        Lk.new(wk.outputs[0], dk.inputs["Factor"]); Lk.new(col, dk.inputs["A"]); dk.inputs["B"].default_value = (0.32, 0.27, 0.22, 1)
        col = dk.outputs["Result"]
    Lk.new(col, bs.inputs["Base Color"])
    r = tx("rough.jpg", True)
    if rough_k != 1.0:
        mt = N.new("ShaderNodeMath"); mt.operation = "MULTIPLY"; mt.inputs[1].default_value = rough_k
        Lk.new(r.outputs["Color"], mt.inputs[0]); Lk.new(mt.outputs[0], bs.inputs["Roughness"])
    else:
        Lk.new(r.outputs["Color"], bs.inputs["Roughness"])
    n = tx("nor.jpg", True)
    nm = N.new("ShaderNodeNormalMap"); nm.inputs["Strength"].default_value = bump
    Lk.new(n.outputs["Color"], nm.inputs["Color"]); Lk.new(nm.outputs["Normal"], bs.inputs["Normal"])
    return m


def flat(name, rgb, rough=0.5, metal=0.0, emit=None):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*rgb, 1); b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if emit:
        b.inputs["Emission Color"].default_value = (*emit[0], 1); b.inputs["Emission Strength"].default_value = emit[1]
    return m


def glass_mat():
    """real window glass: clear, reflective at grazing angles, so blinds, curtains and dim rooms show through"""
    m = bpy.data.materials.new("window_glass"); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.9, 0.93, 0.92, 1); b.inputs["Roughness"].default_value = 0.02
    b.inputs["Transmission Weight"].default_value = 1.0; b.inputs["IOR"].default_value = 1.5
    return m


MAT = {
    "brick": pbr("buff_brick", "brick_wall_07", 1.7, tint=(1.22, 1.08, 0.76), bump=0.8, weather=0.85),
    "roof": pbr("brown_shingle", "grey_roof_01", 6.0, tint=(0.4, 0.27, 0.21), bump=0.7),
    "concrete": pbr("sidewalk", "concrete_pavement", 1.8, tint=(1.05, 1.03, 1.0)),
    "curb": pbr("curb", "brushed_concrete", 2.5),
    "asphalt": pbr("asphalt", "asphalt_02", 3.0, tint=(0.85, 0.85, 0.85)),
    "grass": pbr("lawn", "grass_ground", 2.5, tint=(0.62, 0.95, 0.42)),
    "fascia": flat("white_alu", (0.82, 0.82, 0.8), 0.35, 0.1),
    "door": flat("brown_door", (0.13, 0.07, 0.045), 0.45),
    "panel": flat("brown_panel", (0.16, 0.09, 0.06), 0.6),
    "frame": flat("bronze_frame", (0.05, 0.04, 0.035), 0.4, 0.3),
    "glass": glass_mat(),
    "sill": flat("limestone", (0.62, 0.6, 0.55), 0.7),
    "copper": flat("copper_green", (0.22, 0.42, 0.36), 0.55, 0.4),
    "iron": flat("black_iron", (0.02, 0.02, 0.02), 0.5, 0.6),
    "curtain": flat("curtain", (0.55, 0.5, 0.42), 0.9),
    "blind": flat("blinds", (0.78, 0.76, 0.7), 0.5),
    "dark": flat("room_dark", (0.03, 0.028, 0.025), 0.9),
    "room": flat("room_wall", (0.32, 0.29, 0.25), 0.9),
    "room_floor": flat("room_floor", (0.12, 0.09, 0.07), 0.7),
    "chrome": flat("brass", (0.6, 0.5, 0.3), 0.3, 1.0),
    "ac": flat("ac_unit", (0.7, 0.7, 0.68), 0.5, 0.2),
    "paint": flat("road_paint", (0.85, 0.85, 0.8), 0.6),
    "siding": flat("vinyl_siding", (0.78, 0.76, 0.7), 0.55),
    "shingle_dk": pbr("dark_shingle", "grey_roof_01", 6.0, tint=(0.45, 0.43, 0.42)),
    "metal_roof": flat("metal_roof", (0.55, 0.56, 0.58), 0.4, 0.8),
    "wood_pole": pbr("pole_wood", "brushed_concrete", 1.0, tint=(0.38, 0.27, 0.18), bump=1.5),
    "wire": flat("wire", (0.01, 0.01, 0.01), 0.4),
    "insulator": flat("insulator", (0.45, 0.47, 0.45), 0.3),
    "lamp_head": flat("cobra_head", (0.55, 0.56, 0.55), 0.4, 0.6),
    "lamp_lens": flat("lamp_lens", (0.85, 0.85, 0.8), 0.1),
}


# ---------------------------------------------------------------- mesh helpers
def mesh_obj(name, verts, faces, mat, col="misc"):
    me = bpy.data.meshes.new(name); me.from_pydata(verts, [], faces); me.update()
    o = bpy.data.objects.new(name, me); coll(col).objects.link(o)
    if mat: o.data.materials.append(MAT[mat] if isinstance(mat, str) else mat)
    return o


class Batch:
    """Collects many boxes / polys per material into one mesh (fast to build and render)."""
    def __init__(self, col): self.col = col; self.d = {}

    def add(self, mat, verts, faces):
        V, F = self.d.setdefault(mat, ([], []))
        o = len(V); V.extend(verts); F.extend([[i + o for i in f] for f in faces])

    def box(self, mat, c, u, v, hu, hv, z0, z1):
        """box centred c (2D), axes u,v (unit 2D), half sizes hu,hv, from z0 to z1"""
        cx, cy = c; pts = []
        for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            pts.append((cx + u[0] * hu * su + v[0] * hv * sv, cy + u[1] * hu * su + v[1] * hv * sv))
        verts = [(x, y, z0) for x, y in pts] + [(x, y, z1) for x, y in pts]
        faces = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]
        self.add(mat, verts, faces)

    def done(self, name):
        for mat, (V, F) in self.d.items():
            o = mesh_obj("%s_%s" % (name, mat), V, F, mat, self.col)
            for p in o.data.polygons: p.use_smooth = False
        self.d = {}


def tri_poly(geom):
    """shapely (Multi)Polygon -> (verts2d, tris) via constrained Delaunay."""
    V, F = [], []
    tris = shapely.constrained_delaunay_triangles(geom)
    for t in getattr(tris, "geoms", [tris]):
        if t.is_empty: continue
        c = list(t.exterior.coords)[:3]
        o = len(V); V.extend(c); F.append([o, o + 1, o + 2])
    return V, F


def polys(geom):
    """only the polygon parts of any geometry (set operations leave stray lines and points)"""
    out = []
    for g in getattr(geom, "geoms", [geom]):
        if g.geom_type == "Polygon" and not g.is_empty: out.append(g)
        elif hasattr(g, "geoms"): out.extend(polys(g))
    return out


def slab(name, geom, z, mat, col, thick=0.0):
    geom = MultiPolygon(polys(geom)) if not geom.is_empty else geom
    if geom.is_empty: return None
    V2, F = tri_poly(geom)
    V = [(x, y, z) for x, y in V2]
    for f in F:            # every ground face points up (hair grows along the normal; shading too)
        (ax, ay), (bx, by), (cx_, cy_) = V2[f[0]], V2[f[1]], V2[f[2]]
        if (bx - ax) * (cy_ - ay) - (by - ay) * (cx_ - ax) < 0: f[1], f[2] = f[2], f[1]
    o = mesh_obj(name, V, F, mat, col)
    if thick > 0:     # vertical skirt down to z - thick along every ring (curbs, kerbs)
        bm = bmesh.new()
        for g in getattr(geom, "geoms", [geom]):
            for ring in [g.exterior] + list(g.interiors):
                cs = list(ring.coords)
                for (ax, ay), (bx, by) in zip(cs, cs[1:]):
                    a = bm.verts.new((ax, ay, z)); b = bm.verts.new((bx, by, z))
                    c = bm.verts.new((bx, by, z - thick)); d = bm.verts.new((ax, ay, z - thick))
                    bm.faces.new((a, b, c, d))
        me = bpy.data.meshes.new(name + "_skirt"); bm.to_mesh(me); bm.free()
        so = bpy.data.objects.new(name + "_skirt", me); coll(col).objects.link(so)
        so.data.materials.append(MAT["curb"])
    return o


# ---------------------------------------------------------------- ground: roads, sidewalks, parking, lawns, walks
area_box = sbox(X0 - CX - 40, Y0 - CY - 40, X1 - CX + 40, Y1 - CY + 40)
WIDTH = {"tertiary": 11.0, "secondary": 13.0, "primary": 14.0, "residential": 8.5, "service": 5.5, "unclassified": 8.0}
roads, sidewalk_lines = [], []
for r in D["roads"]:
    hw = r["tags"].get("highway")
    if hw not in WIDTH: continue
    ls = LineString([L(p) for p in r["pts"]])
    w = WIDTH[hw]
    roads.append(ls.buffer(w / 2, cap_style="flat", join_style="round"))
    if hw in ("tertiary", "residential", "secondary", "unclassified"):
        sidewalk_lines.append((ls, w))
road_u = unary_union(roads).buffer(0.6).buffer(-0.6).intersection(area_box)
park_u = unary_union([Polygon([L(p) for p in a["ring"]]).buffer(0) for a in D["areas"]
                      if a["tags"].get("amenity") == "parking"] or [Polygon()]).difference(road_u)
foot = []
BLD = []
for b in D["buildings"]:
    pg = Polygon([L(p) for p in b["ring"]]).buffer(0)
    if pg.is_empty or not pg.intersects(area_box): continue
    BLD.append((b, pg)); foot.append(pg)
foot_u = unary_union(foot)
side = []
for ls, w in sidewalk_lines:
    outer = ls.buffer(w / 2 + 3.9, cap_style="flat"); inner = ls.buffer(w / 2 + 2.4, cap_style="flat")
    side.append(outer.difference(inner))
side_u = unary_union(side).difference(road_u).difference(park_u).difference(foot_u.buffer(0.5)).intersection(area_box)


# ---------------------------------------------------------------- building typologies
def orient_rect(pg):
    r = pg.minimum_rotated_rectangle
    cs = list(r.exterior.coords)[:4]
    e0 = Vector((cs[1][0] - cs[0][0], cs[1][1] - cs[0][1], 0)); e1 = Vector((cs[2][0] - cs[1][0], cs[2][1] - cs[1][1], 0))
    if e0.length < e1.length: e0, e1 = e1, e0
    c = r.centroid
    return (c.x, c.y), e0.normalized(), e1.normalized(), e0.length / 2, e1.length / 2


def hip_roof(B, c, u, v, hu, hv, z, rise, over, mat="roof"):
    """Hip roof over the rectangle (centre c, long axis u), eave at z, ridge `rise` higher, with overhang."""
    hu += over; hv += over
    rl = max(hu - hv, 0.0)
    P = lambda a, b, zz: (c[0] + u[0] * a + v[0] * b, c[1] + u[1] * a + v[1] * b, zz)
    e = [P(-hu, -hv, z), P(hu, -hv, z), P(hu, hv, z), P(-hu, hv, z)]
    r0, r1 = P(-rl, 0, z + rise), P(rl, 0, z + rise)
    B.add(mat, e + [r0, r1], [[0, 1, 5, 4], [2, 3, 4, 5], [1, 2, 5], [3, 0, 4]])
    # fascia + soffit band (white aluminium) and gutter lip
    ring = e + [e[0]]
    for a, bq in zip(ring, ring[1:]):
        B.add("fascia", [a, bq, (bq[0], bq[1], bq[2] - 0.24), (a[0], a[1], a[2] - 0.24)], [[0, 1, 2, 3]])
    P2 = lambda a, b, zz: (c[0] + u[0] * a + v[0] * b, c[1] + u[1] * a + v[1] * b, zz)
    s = [P2(-hu, -hv, z - 0.24), P2(hu, -hv, z - 0.24), P2(hu, hv, z - 0.24), P2(-hu, hv, z - 0.24)]
    B.add("fascia", s, [[0, 1, 2, 3]])


def gable_roof(B, c, u, v, hu, hv, z, rise, over, mat="shingle_dk"):
    hu += over; hv += over
    P = lambda a, b, zz: (c[0] + u[0] * a + v[0] * b, c[1] + u[1] * a + v[1] * b, zz)
    e = [P(-hu, -hv, z), P(hu, -hv, z), P(hu, hv, z), P(-hu, hv, z)]
    r0, r1 = P(-hu, 0, z + rise), P(hu, 0, z + rise)
    B.add(mat, e + [r0, r1], [[0, 1, 5, 4], [2, 3, 4, 5]])
    B.add("siding", [P(-hu + over, -hv + over, z), P(-hu + over, hv - over, z), P(-hu + over, 0, z + rise - 0.1)], [[0, 1, 2]])
    B.add("siding", [P(hu - over, -hv + over, z), P(hu - over, hv - over, z), P(hu - over, 0, z + rise - 0.1)], [[0, 2, 1]])


def walls(B, pg, z0, z1, mat):
    cs = list(shapely.geometry.polygon.orient(pg, 1.0).exterior.coords)
    for (ax, ay), (bx, by) in zip(cs, cs[1:]):
        B.add(mat, [(ax, ay, z0), (bx, by, z0), (bx, by, z1), (ax, ay, z1)], [[0, 1, 2, 3]])


def wall_feature(B, c, u, n, s, z, w, h, depth, mat):
    """a thin box on the wall plane: centre along wall s, bottom z, width w, height h, standing out `depth` along n"""
    cc = (c[0] + u[0] * s + n[0] * depth / 2, c[1] + u[1] * s + n[1] * depth / 2)
    B.box(mat, cc, u, n, w / 2, abs(depth) / 2, z, z + h)


def P3(c, u, n, s, d, z):
    """point on a wall: centre c, along-wall s (axis u), out of the wall d (axis n), height z"""
    return (c[0] + u[0] * s + n[0] * d, c[1] + u[1] * s + n[1] * d, z)


def window(B, c, u, n, s, z, w, h, ac=False, ops=None, R=0.11):
    """A real opening: the hole is cut by wall_with_holes (recorded in ops); here the frame sits R deep in it,
    slider glass in two panes, curtains or blinds behind, and a stone sill that sticks out past the brick."""
    if ops is not None: ops.append((s, z, w, h))
    fw = 0.045
    for (a0, a1, b0, b1) in ((-w / 2, -w / 2 + fw, 0, h), (w / 2 - fw, w / 2, 0, h), (-w / 2, w / 2, 0, fw), (-w / 2, w / 2, h - fw, h)):
        cc = (c[0] + u[0] * (s + (a0 + a1) / 2) - n[0] * (R - 0.03), c[1] + u[1] * (s + (a0 + a1) / 2) - n[1] * (R - 0.03))
        B.box("frame", cc, u, n, (a1 - a0) / 2, 0.03, z + b0, z + b1)
    for k, off in ((-1, -0.075), (1, -0.095)):        # the two slider sashes, one in front of the other
        cc = (c[0] + u[0] * (s + k * w / 4) + n[0] * (off - R + 0.11), c[1] + u[1] * (s + k * w / 4) + n[1] * (off - R + 0.11))
        B.box("glass", cc, u, n, w / 4 - 0.01, 0.004, z + fw, z + h - fw)
        cc2 = (c[0] + u[0] * (s + k * (w / 2 - fw / 2) * 0 + 0) + n[0] * (off - R + 0.11), c[1] + u[1] * s + n[1] * (off - R + 0.11))
    cc = (c[0] + u[0] * s - n[0] * (R - 0.02), c[1] + u[1] * s - n[1] * (R - 0.02))
    B.box("frame", cc, u, n, 0.022, 0.035, z, z + h)                                     # meeting rail
    kind = rng.random()
    if kind < 0.45:                                                                       # curtains
        k = rng.uniform(0.35, 1.0)
        for side_ in (-1, 1):
            c2 = (c[0] + u[0] * (s + side_ * w * 0.3) - n[0] * (R + 0.08), c[1] + u[1] * (s + side_ * w * 0.3) - n[1] * (R + 0.08))
            B.box("curtain", c2, u, n, w * 0.2 * k, 0.01, z + 0.02, z + h - 0.02)
    elif kind < 0.8:                                                                      # mini blinds, part down
        k = rng.uniform(0.2, 0.9)
        c2 = (c[0] + u[0] * s - n[0] * (R + 0.06), c[1] + u[1] * s - n[1] * (R + 0.06))
        for j in range(int(h * k / 0.03)):
            zz = z + h - 0.05 - j * 0.03
            B.box("blind", c2, u, n, w / 2 - 0.05, 0.012, zz - 0.012, zz)
    # stone sill: below the opening, out past the wall face, a little wider than the opening
    cc = (c[0] + u[0] * s + n[0] * (0.05 - R / 2), c[1] + u[1] * s + n[1] * (0.05 - R / 2))
    B.box("sill", cc, u, n, w / 2 + 0.08, 0.05 + R / 2, z - 0.09, z)
    if ac:
        cc = (c[0] + u[0] * (s + w * 0.25) + n[0] * 0.18, c[1] + u[1] * (s + w * 0.25) + n[1] * 0.18)
        B.box("ac", cc, u, n, 0.31, 0.3, z + 0.02, z + 0.4)
        cc = (c[0] + u[0] * (s + w * 0.25) + n[0] * 0.49, c[1] + u[1] * (s + w * 0.25) + n[1] * 0.49)
        B.box("frame", cc, u, n, 0.28, 0.005, z + 0.05, z + 0.37)                       # fan grille
        WEEP.append((P3(c, u, n, s + w * 0.25, 0.2, z), 1.6))                          # drip stain under it


def wall_with_holes(B, c, u, n, s0, s1, z0, z1, ops, mat="brick", R=0.11):
    """flat wall from s0..s1, z0..z1 with every opening in ops cut out, plus brick reveals R deep"""
    from shapely.geometry import box as _b
    g = _b(s0, z0, s1, z1)
    holes = [_b(s - w / 2, z, s + w / 2, z + h) for s, z, w, h in ops]
    if holes: g = g.difference(unary_union(holes))
    nn = Vector((n[0], n[1], 0))
    for pgn in polys(g):
        V2, F = tri_poly(pgn)
        V = [P3(c, u, n, a, 0.0, b) for a, b in V2]
        for f in F:
            a_, b_, c_ = (Vector(V[i]) for i in f)
            if (b_ - a_).cross(c_ - a_).dot(nn) < 0: f[1], f[2] = f[2], f[1]
        B.add(mat, V, F)
    for s, z, w, h in ops:          # reveals: jambs, head, and the brick floor of the opening under the sill
        a, b = s - w / 2, s + w / 2
        for q in (((a, z), (a, z + h)), ((b, z + h), (b, z)), ((a, z + h), (b, z + h)), ((b, z), (a, z))):
            (sa, za), (sb, zb) = q
            B.add(mat, [P3(c, u, n, sa, 0, za), P3(c, u, n, sb, 0, zb), P3(c, u, n, sb, -R, zb), P3(c, u, n, sa, -R, za)], [[0, 1, 2, 3]])
        dd = -R - 2.4
        B.add("room", [P3(c, u, n, a - 0.8, dd, z - 1.0), P3(c, u, n, b + 0.8, dd, z - 1.0), P3(c, u, n, b + 0.8, dd, z + h + 0.6), P3(c, u, n, a - 0.8, dd, z + h + 0.6)], [[0, 1, 2, 3]])
        B.add("room_floor", [P3(c, u, n, a - 0.8, -R, z - 0.9), P3(c, u, n, b + 0.8, -R, z - 0.9), P3(c, u, n, b + 0.8, dd, z - 0.9), P3(c, u, n, a - 0.8, dd, z - 0.9)], [[0, 1, 2, 3]])
        for sd_ in (a - 0.8, b + 0.8):
            B.add("room", [P3(c, u, n, sd_, -R, z - 1.0), P3(c, u, n, sd_, dd, z - 1.0), P3(c, u, n, sd_, dd, z + h + 0.6), P3(c, u, n, sd_, -R, z + h + 0.6)], [[0, 1, 2, 3]])


def weiler_row(B, Bg, pg, L_):
    c, u, v, hu, hv = orient_rect(pg)
    g = 0.0
    eave = max(5.4, min(6.4, L_.get("eave", 5.9) - 0.1))
    floor = 0.45
    # short end walls (plain brick); the long walls are built with their openings below
    for sd in (1, -1):
        e0 = (c[0] + u[0] * hu * sd + v[0] * hv * sd, c[1] + u[1] * hu * sd + v[1] * hv * sd)
        e1 = (c[0] + u[0] * hu * sd - v[0] * hv * sd, c[1] + u[1] * hu * sd - v[1] * hv * sd)
        B.add("brick", [(e0[0], e0[1], g), (e1[0], e1[1], g), (e1[0], e1[1], eave), (e0[0], e0[1], eave)], [[0, 1, 2, 3]])
        GRIME.append((e0, e1))
    hip_roof(B, c, u, v, hu, hv, eave, min(2.6, hv * 0.42), 0.45)
    # foundation band
    walls(B, pg.buffer(0.03, join_style="mitre"), g - 0.2, floor - 0.1, "curb")
    bay = 10.6
    nb = max(1, int(round(2 * hu / bay)))
    bay = 2 * hu / nb
    for side in (1, -1):         # front (+v) and back (-v): both get entries; Weiler rows face walks on both sides
        n = (v[0] * side, v[1] * side)
        wc = (c[0] + v[0] * hv * side, c[1] + v[1] * hv * side)
        uu = (u[0] * side, u[1] * side)          # keep features reading left-to-right from outside
        ops = []
        GRIME.append(((wc[0] - uu[0] * hu, wc[1] - uu[1] * hu), (wc[0] + uu[0] * hu, wc[1] + uu[1] * hu)))
        for i in range(nb):
            s0 = -hu + (i + 0.5) * bay
            if side < 0: s0 = -s0
            front = side > 0
            # paired entry in the middle of the bay
            if front or i % 2 == 0:
                ops.append((s0, floor, 1.96, 2.2))
                for ds in (-0.49, 0.49):     # two brown steel doors set into the opening, each with a lite
                    cc = (wc[0] + uu[0] * (s0 + ds) - n[0] * 0.09, wc[1] + uu[1] * (s0 + ds) - n[1] * 0.09)
                    B.box("door", cc, uu, n, 0.46, 0.025, floor, floor + 2.16)
                    cc = (wc[0] + uu[0] * (s0 + ds) - n[0] * 0.062, wc[1] + uu[1] * (s0 + ds) - n[1] * 0.062)
                    B.box("glass", cc, uu, n, 0.15, 0.004, floor + 1.25, floor + 1.85)
                    B.box("door", cc, uu, n, 0.17, 0.003, floor + 1.22, floor + 1.25)
                    cc = (wc[0] + uu[0] * (s0 + ds - 0.3) - n[0] * 0.055, wc[1] + uu[1] * (s0 + ds - 0.3) - n[1] * 0.055)
                    B.box("iron", cc, uu, n, 0.08, 0.02, floor + 0.95, floor + 1.15)                   # mail slot box
                    cc = (wc[0] + uu[0] * (s0 + ds + 0.36 * (1 if ds < 0 else -1)) - n[0] * 0.05, wc[1] + uu[1] * (s0 + ds + 0.36 * (1 if ds < 0 else -1)) - n[1] * 0.05)
                    B.box("chrome", cc, uu, n, 0.02, 0.03, floor + 0.98, floor + 1.08)                  # knob
                cc = (wc[0] + uu[0] * s0 - n[0] * 0.08, wc[1] + uu[1] * s0 - n[1] * 0.08)
                B.box("door", cc, uu, n, 0.035, 0.03, floor, floor + 2.2)                               # centre mullion
                for hn, hs in ((-1, -1.18), (1, 1.18)):                                                  # house numbers
                    cc = (wc[0] + uu[0] * (s0 + hs) + n[0] * 0.01, wc[1] + uu[1] * (s0 + hs) + n[1] * 0.01)
                    B.box("iron", cc, uu, n, 0.07, 0.006, floor + 1.55, floor + 1.7)
                # canopy: flat copper-green hood on iron posts
                cc = (wc[0] + n[0] * 0.55 + uu[0] * s0, wc[1] + n[1] * 0.55 + uu[1] * s0)
                B.box("copper", cc, uu, n, 1.4, 0.55, floor + 2.35, floor + 2.5)
                for ps in (-1.3, 1.3):
                    pc = (wc[0] + n[0] * 1.02 + uu[0] * (s0 + ps), wc[1] + n[1] * 1.02 + uu[1] * (s0 + ps))
                    B.box("iron", pc, uu, n, 0.025, 0.025, 0.0, floor + 2.35)
                # stoop + steps
                sc = (wc[0] + n[0] * 0.75 + uu[0] * s0, wc[1] + n[1] * 0.75 + uu[1] * s0)
                B.box("curb", sc, uu, n, 1.3, 0.75, -0.1, floor)
                for k in range(2):
                    sc2 = (wc[0] + n[0] * (1.65 + k * 0.3) + uu[0] * s0, wc[1] + n[1] * (1.65 + k * 0.3) + uu[1] * s0)
                    B.box("curb", sc2, uu, n, 0.75, 0.15, -0.1, floor - 0.15 * (k + 1))
                # lamps either side
                for ls in (-1.15, 1.15):
                    wall_feature(B, wc, uu, n, s0 + ls, floor + 1.95, 0.12, 0.22, 0.12, "iron")
                # walk from the steps out to the sidewalk / lawn edge
                a = Point(wc[0] + n[0] * 2.4 + uu[0] * s0, wc[1] + n[1] * 2.4 + uu[1] * s0)
                bpt = Point(wc[0] + n[0] * 9.0 + uu[0] * s0, wc[1] + n[1] * 9.0 + uu[1] * s0)
                WALKS.append(LineString([a, bpt]).buffer(0.6, cap_style="flat"))
                for ws in (-2.35, 2.35):
                    window(B, wc, uu, n, s0 + ws, floor + 0.85, 1.55, 1.05, ac=False, ops=ops)
            else:
                for ws in (-2.3, 0.0, 2.3):
                    window(B, wc, uu, n, s0 + ws, floor + 0.85, 1.25, 1.05, ops=ops)
            # upper floor windows
            for ws in (-2.35, 0.0, 2.35):
                window(B, wc, uu, n, s0 + ws, floor + 3.35, 1.15 if ws else 1.0, 1.05, ac=rng.random() < 0.25, ops=ops)
            # recessed brown panel + white downspouts at the bay boundary
            if i < nb - 1:
                sb = s0 + bay / 2
                wall_feature(B, wc, uu, n, sb, 0.5, 0.48, eave - 0.7, 0.012, "panel")
                for d in (-0.38, 0.38):
                    pc = (wc[0] + n[0] * 0.07 + uu[0] * (sb + d), wc[1] + n[1] * 0.07 + uu[1] * (sb + d))
                    B.box("fascia", pc, uu, n, 0.04, 0.035, 0.05, eave - 0.2)
                    WEEP.append(((pc[0], pc[1], 0.05), 0.0))
        wall_with_holes(B, wc, uu, n, -hu, hu, g, eave, ops)
    # shrubs along the fronts
    for side in (1, -1):
        for i in range(int(hu * 2 / 1.6)):
            s = -hu + 0.8 + i * 1.6 + rng.uniform(-0.3, 0.3)
            if rng.random() < 0.75:
                SHRUBS.append((c[0] + u[0] * s + v[0] * (hv + 0.9) * side, c[1] + u[1] * s + v[1] * (hv + 0.9) * side,
                               rng.uniform(0.6, 1.0)))


def house(B, pg, L_):
    c, u, v, hu, hv = orient_rect(pg)
    eave = max(2.8, min(6.5, L_.get("eave", 4.5)))
    h = max(eave + 1.0, L_.get("h", eave + 2.0))
    walls(B, pg, 0, eave, "siding")
    gable_roof(B, c, v, (-u[0], -u[1]), hv, hu, eave, min(h - eave, hv * 0.9), 0.3)
    n = (v[0], v[1]); wc = (c[0] + v[0] * hv, c[1] + v[1] * hv)
    for s in (-hu * 0.5, hu * 0.5):
        window(B, wc, u, n, s, 0.95, 0.9, 1.3)
    wall_feature(B, wc, u, n, 0.0, 0.25, 0.95, 2.05, 0.03, "door")


def block(B, pg, L_):
    h = max(3.5, min(L_.get("eave", 5.0) + 0.5, L_.get("h", 6.0)))
    walls(B, pg, 0, h, "brick")
    V2, F = tri_poly(pg)
    B.add("metal_roof", [(x, y, h) for x, y in V2], F)


WALKS, SHRUBS, GRIME, WEEP = [], [], [], []
weiler_zone = Polygon([L(p) for p in ((1335, -2300), (1745, -2300), (1745, -2650), (1335, -2650))])
for b, pg in BLD:
    Bb = Batch("buildings")
    L_ = b.get("lidar", {})
    c, u, v, hu, hv = orient_rect(pg)
    rect_fill = pg.area / max(1.0, 4 * hu * hv)
    if pg.centroid.within(weiler_zone) and hu > 9 and hv < 10 and rect_fill > 0.8 and L_.get("eave", 6) < 9:   # every Weiler block is a 2-storey row (LiDAR h can include trees)
        weiler_row(Bb, None, pg, L_)
    elif pg.area < 260:
        house(Bb, pg, L_)
    else:
        block(Bb, pg, L_)
    Bb.done(b["id"])

walks_u = unary_union(WALKS).difference(foot_u).difference(road_u.buffer(2.4)) if WALKS else Polygon()   # walks stop at the sidewalk
paved = unary_union([side_u, walks_u, park_u])
lawn = area_box.difference(road_u).difference(paved).difference(foot_u)
slab("road", road_u, 0.0, "asphalt", "ground")
slab("parking", park_u, 0.0, "asphalt", "ground")
slab("sidewalk", side_u.union(walks_u), LAWN + 0.01, "concrete", "ground", thick=0.16)
slab("lawn", lawn, LAWN, "grass", "ground", thick=0.15)
# land beyond the built area out to the horizon (context comes later, area by area)
far = sbox(-4000, -4000, 4000, 4000).difference(area_box)
slab("far_ground", far, LAWN - 0.02, "grass", "ground")
# utility poles along one side of each street, wires sagging between them, cobra-head lights on every other pole
def wire_curve(name, pts, r):
    cu = bpy.data.curves.new(name, "CURVE"); cu.dimensions = "3D"; cu.bevel_depth = r; cu.bevel_resolution = 1
    sp = cu.splines.new("POLY"); sp.points.add(len(pts) - 1)
    for i, q in enumerate(pts): sp.points[i].co = (*q, 1)
    o = bpy.data.objects.new(name, cu); coll("utility").objects.link(o); o.data.materials.append(MAT["wire"])


UB = Batch("utility")
npole = 0
for ls, w in sidewalk_lines:
    if ls.length < 40: continue
    off = ls.parallel_offset(w / 2 + 1.0, "left")
    if off.is_empty or off.geom_type != "LineString": continue
    k = max(2, int(off.length / 38) + 1)
    poles = [off.interpolate(i / (k - 1), normalized=True) for i in range(k)]
    tops = []
    for i, pp in enumerate(poles):
        if Point(pp.x, pp.y).buffer(1.0).intersects(foot_u): continue
        a = off.interpolate(max(0, off.project(pp) - 1)); b = off.interpolate(min(off.length, off.project(pp) + 1))
        dx, dy = b.x - a.x, b.y - a.y; dl = math.hypot(dx, dy) or 1; t = (dx / dl, dy / dl); nrm = (-t[1], t[0])
        B_ = UB; H = 10.5 + rng.uniform(-0.5, 0.8)
        bpy.ops.mesh.primitive_cylinder_add(vertices=10, radius=0.13, depth=H, location=(pp.x, pp.y, H / 2))
        po = bpy.context.active_object; po.data.materials.append(MAT["wood_pole"])
        for vv in po.data.vertices:                     # tapered
            if vv.co.z > 0: vv.co.x *= 0.75; vv.co.y *= 0.75
        po.rotation_euler = (rng.uniform(-0.015, 0.015), rng.uniform(-0.015, 0.015), 0)
        for uc in list(po.users_collection): uc.objects.unlink(po)
        coll("utility").objects.link(po)
        B_.box("wood_pole", (pp.x, pp.y), nrm, t, 1.1, 0.05, H - 0.6, H - 0.48)      # crossarm across the street
        tp = []
        for d in (-0.95, 0.0, 0.95):
            q = (pp.x + nrm[0] * d, pp.y + nrm[1] * d)
            B_.box("insulator", q, t, nrm, 0.04, 0.04, H - 0.48, H - 0.32)
            tp.append((q[0], q[1], H - 0.32 if d else H + 0.25))
        tp.append((pp.x, pp.y, H - 2.2))                 # lower communication cable
        B_.box("wire", (pp.x, pp.y), t, nrm, 0.07, 0.07, H - 2.4, H - 2.0)
        if i % 2 == 0:                                   # cobra-head street light reaching over the road
            arm = (pp.x - nrm[0] * 1.8, pp.y - nrm[1] * 1.8)
            B_.box("lamp_head", ((pp.x + arm[0]) / 2, (pp.y + arm[1]) / 2), nrm, t, 0.95, 0.03, H - 3.1, H - 3.04)
            B_.box("lamp_head", arm, nrm, t, 0.35, 0.16, H - 3.2, H - 3.04)
            B_.box("lamp_lens", arm, nrm, t, 0.28, 0.12, H - 3.24, H - 3.2)
        tops.append(tp)
        npole += 1
    for a_, b_ in zip(tops, tops[1:]):
        for (ax, ay, az), (bx, by, bz) in zip(a_, b_):
            sag = 0.012 * math.hypot(bx - ax, by - ay)
            pts = [(ax + (bx - ax) * f, ay + (by - ay) * f, az + (bz - az) * f - sag * 4 * f * (1 - f)) for f in np.linspace(0, 1, 16)]
            wire_curve("wire", pts, 0.009)
UB.done("poles")
print("poles", npole)

# parking stall lines
pl = Batch("ground")
for pgk in getattr(park_u, "geoms", [park_u]):
    if pgk.area < 200: continue
    c, u, v, hu, hv = orient_rect(pgk)
    for row in (-1, 1):
        for k in range(int(2 * hu / 2.7)):
            s = -hu + 1.5 + k * 2.7
            cc = (c[0] + u[0] * s + v[0] * row * (hv - 2.6), c[1] + u[1] * s + v[1] * row * (hv - 2.6))
            if Point(cc).within(pgk): pl.box("paint", cc, u, v, 0.05, 2.5, 0.0, 0.006)
pl.done("stalls")


# ---------------------------------------------------------------- vegetation + props (Poly Haven models, instanced)
def load_model(mid):
    p = os.path.join(ASSETS, "model", mid, mid + ".gltf")
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=p)
    objs = [o for o in bpy.data.objects if o not in before]
    c = bpy.data.collections.new("src_" + mid)
    for o in objs:
        for uc in list(o.users_collection): uc.objects.unlink(o)
        c.objects.link(o)
    zs = [(o.matrix_world @ Vector(k)).z for o in objs if o.type == "MESH" for k in o.bound_box]
    return c, max(zs) - min(zs)


def instance(c, x, y, z, s, rot):
    e = bpy.data.objects.new(c.name + "_i", None); e.instance_type = "COLLECTION"; e.instance_collection = c
    e.location = (x, y, z); e.scale = (s, s, s); e.rotation_euler = (0, 0, rot)
    coll("vegetation").objects.link(e)


tree_c, tree_h = load_model("tree_small_02")
def make_bush(name, seed):
    """dense, round clipped evergreen (yews / junipers along the fronts in the reference photos)"""
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=4, radius=0.5)
    o = bpy.context.active_object; o.name = name
    o.scale = (1.0, 1.0, 0.8); bpy.ops.object.transform_apply(scale=True)
    tx = bpy.data.textures.new(name + "_n", "CLOUDS"); tx.noise_scale = 0.18; tx.noise_depth = 2
    dm = o.modifiers.new("d", "DISPLACE"); dm.texture = tx; dm.strength = 0.16; dm.mid_level = 0.5
    bpy.ops.object.modifier_apply(modifier="d")
    for v in o.data.vertices:
        if v.co.z < -0.25: v.co.z = -0.25 + (v.co.z + 0.25) * 0.2       # flat-ish bottom on the ground
    for f in o.data.polygons: f.use_smooth = True
    m = bpy.data.materials.new(name + "_leaf"); m.use_nodes = True; N = m.node_tree.nodes; Lk = m.node_tree.links
    b = N["Principled BSDF"]; vo = N.new("ShaderNodeTexVoronoi"); vo.inputs["Scale"].default_value = 60
    ramp = N.new("ShaderNodeValToRGB"); ramp.color_ramp.elements[0].color = (0.015, 0.05, 0.012, 1)
    ramp.color_ramp.elements[1].color = (0.07, 0.17, 0.04, 1)
    Lk.new(vo.outputs["Distance"], ramp.inputs["Fac"]); Lk.new(ramp.outputs["Color"], b.inputs["Base Color"])
    bm_ = N.new("ShaderNodeBump"); bm_.inputs["Strength"].default_value = 0.9
    Lk.new(vo.outputs["Distance"], bm_.inputs["Height"]); Lk.new(bm_.outputs["Normal"], b.inputs["Normal"])
    b.inputs["Roughness"].default_value = 0.75
    o.data.materials.append(m)
    o.location = (0, 0, 0.25)
    bpy.ops.object.transform_apply(location=True)
    c = bpy.data.collections.new("src_" + name)
    for uc in list(o.users_collection): uc.objects.unlink(o)
    c.objects.link(o)
    return c, 0.85


shr = [make_bush("bush_a", 1), make_bush("bush_b", 2)]
T = json.load(open(os.path.join(os.path.dirname(AREA), "..", "lidar", "trees.json")))["trees"] if os.path.exists(
    os.path.join(os.path.dirname(AREA), "..", "lidar", "trees.json")) else []
nt = 0
for x, y, h, d in T:
    if not (X0 - 30 <= x <= X1 + 30 and Y0 - 30 <= y <= Y1 + 30): continue
    lx, ly = L((x, y))
    if Point(lx, ly).within(foot_u): continue
    instance(tree_c, lx, ly, LAWN, max(0.4, min(2.5, h / tree_h)), rng.uniform(0, 6.28)); nt += 1
for x, y, s in SHRUBS:
    c, hh = shr[rng.randrange(2)]
    instance(c, x, y, LAWN, s * rng.uniform(0.9, 1.4), rng.uniform(0, 6.28))
print("trees", nt, "shrubs", len(SHRUBS))

# grass blades near the camera (hair particles on a lawn patch) for a real lawn edge in close shots
cam = OPT.get("cam", "")
if cam:
    (px, py, pz), (tx, ty, tz) = [tuple(map(float, s.split(","))) for s in cam.split(":")]
if cam and OPT.get("grass") == "1":
    (px, py, pz), (tx, ty, tz) = [tuple(map(float, s.split(","))) for s in cam.split(":")]
    gr = float(OPT.get("grass_r", 60))
    patch = lawn.intersection(Point(px, py).buffer(gr))
    if not patch.is_empty:
        go = slab("lawn_hair", patch, LAWN + 0.001, "grass", "ground")
        gm = bpy.data.materials.new("grass_blade"); gm.use_nodes = True
        gb = gm.node_tree.nodes["Principled BSDF"]; gb.inputs["Roughness"].default_value = 0.55
        hi = gm.node_tree.nodes.new("ShaderNodeHairInfo"); rp = gm.node_tree.nodes.new("ShaderNodeValToRGB")
        rp.color_ramp.elements[0].color = (0.03, 0.07, 0.01, 1); rp.color_ramp.elements[1].color = (0.16, 0.3, 0.05, 1)
        gm.node_tree.links.new(hi.outputs["Intercept"], rp.inputs["Fac"]); gm.node_tree.links.new(rp.outputs["Color"], gb.inputs["Base Color"])
        go.data.materials.append(gm)
        ps = go.modifiers.new("grass", "PARTICLE_SYSTEM").particle_system.settings
        ps.type = "HAIR"; ps.count = int(patch.area * 45); ps.hair_length = 0.09
        ps.child_type = "INTERPOLATED"; ps.child_percent = 3; ps.rendered_child_count = 12; ps.child_radius = 0.12
        ps.roughness_2 = 0.03; ps.roughness_endpoint = 0.02
        ps.material = 2
        for k, val in (("root_radius", 1.0), ("tip_radius", 0.0), ("radius_scale", 0.003)):
            if hasattr(ps, k): setattr(ps, k, val)
        go.data.materials[0] = MAT["grass"]

# ---------------------------------------------------------------- world, sun, camera, render
w = bpy.data.worlds.new("sky"); SC.world = w; w.use_nodes = True
env = w.node_tree.nodes.new("ShaderNodeTexEnvironment")
env.image = img(os.path.join(ASSETS, "hdri", "kloofendal_48d_partly_cloudy_puresky", "kloofendal_48d_partly_cloudy_puresky.hdr"))
mpw = w.node_tree.nodes.new("ShaderNodeMapping"); tcw = w.node_tree.nodes.new("ShaderNodeTexCoord")
mpw.inputs["Rotation"].default_value = (0, 0, math.radians(float(OPT.get("sky_rot", 120))))
w.node_tree.links.new(tcw.outputs["Generated"], mpw.inputs["Vector"]); w.node_tree.links.new(mpw.outputs["Vector"], env.inputs["Vector"])
w.node_tree.links.new(env.outputs["Color"], w.node_tree.nodes["Background"].inputs["Color"])
w.node_tree.nodes["Background"].inputs["Strength"].default_value = 1.0
sun = bpy.data.lights.new("sun", "SUN"); sun.energy = 3.2; sun.angle = math.radians(1.0); sun.color = (1.0, 0.96, 0.9)
so = bpy.data.objects.new("sun", sun); SC.collection.objects.link(so)
so.rotation_euler = (math.radians(40), 0, math.radians(float(OPT.get("sun_az", 150))))

bpy.ops.wm.save_as_mainfile(filepath=OUT)
print("saved", OUT)
if OPT.get("render") and cam:
    cd = bpy.data.cameras.new("cam"); cd.lens = float(OPT.get("lens", 28)); co = bpy.data.objects.new("cam", cd)
    SC.collection.objects.link(co); co.location = (px, py, pz)
    co.rotation_euler = (Vector((tx, ty, tz)) - Vector((px, py, pz))).to_track_quat("-Z", "Y").to_euler()
    SC.camera = co
    SC.render.engine = "CYCLES"; SC.cycles.device = "CPU"
    SC.cycles.samples = int(OPT.get("samples", 96)); SC.cycles.use_denoising = True
    try: SC.cycles.denoiser = "OPENIMAGEDENOISE"
    except Exception: pass
    SC.cycles.max_bounces = 4; SC.cycles.diffuse_bounces = 2; SC.cycles.glossy_bounces = 2
    rx, ry = map(int, OPT.get("res", "1280x720").split("x"))
    SC.render.resolution_x, SC.render.resolution_y = rx, ry
    SC.view_settings.view_transform = "AgX" if "AgX" in [v.identifier for v in SC.view_settings.bl_rna.properties["view_transform"].enum_items] else "Filmic"
    SC.view_settings.look = "None"
    SC.render.filepath = OPT["render"]
    bpy.ops.render.render(write_still=True)
    print("rendered", OPT["render"])
