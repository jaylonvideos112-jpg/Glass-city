bl_info = {
    "name": "Schoolyard Characters v3 (MPFB)",
    "author": "Jay",
    "version": (3, 0, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar (N) > Schoolyard",
    "description": "Semi-realistic 2000s schoolyard-game style teens built on MPFB (MakeHuman): "
                   "caricatured faces, school uniforms and clique outfits, game-engine rig, FBX export",
    "category": "Add Mesh",
}

# Requires: the MPFB extension (Blender 4.2+) and these free CC0 MakeHuman asset packs installed
# through MPFB: makehuman_system_assets, skins01-03, hair01, shirts01, pants01, suits01, suits02,
# shoes01, hats01, hats02, skirts01, glasses01, eyebrows01, system_clothes_materials01,
# system_hair_materials01.

import importlib
import os
import random
import sys

import os as _os
# GLASS CITY addition: curl size for the Curly Top style (1 = original; ~0.6 = short, tight sponge curls)
_CURL_K = float(_os.environ.get("SY_CURL_SCALE", "1.0"))
import bpy
import numpy as np
import types as _types
from bpy.props import (BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty,
                       PointerProperty, StringProperty)


# ======================================================================================
#  URBAN WARDROBE + MODERN HAIR  (procedural, grown from the MPFB body so it fits any build)
# ======================================================================================
import math

import bmesh
import bpy
import numpy as np
from mathutils import Vector, Quaternion, Matrix, noise
from mathutils.bvhtree import BVHTree


def _srgb(h):
    h = h.lstrip('#')
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return np.array(out)


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


# --------------------------------------------------------------------------------------
# Body sampling
# --------------------------------------------------------------------------------------

class Body:
    """Rest-pose snapshot of the MPFB basemesh (shape keys applied, helpers included so
    vertex indices match the basemesh)."""

    def __init__(self, h):
        self.h = h
        masks = [m for m in h.modifiers if m.type == 'MASK']
        arms = [m for m in h.modifiers if m.type == 'ARMATURE']
        states = [(m, m.show_viewport) for m in masks + arms]
        for m, _ in states:
            m.show_viewport = False
        dg = bpy.context.evaluated_depsgraph_get()
        dg.update()
        ev = h.evaluated_get(dg)
        me = bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=True, depsgraph=dg)
        for m, s in states:
            m.show_viewport = s
        self.me = me
        n = len(me.vertices)
        co = np.empty(n * 3)
        me.vertices.foreach_get('co', co)
        self.co = co.reshape(-1, 3)
        e = np.empty(len(me.edges) * 2, np.int64)
        me.edges.foreach_get('vertices', e)
        self.edges = e.reshape(-1, 2)
        lt = np.empty(len(me.polygons), np.int64)
        ls = np.empty(len(me.polygons), np.int64)
        me.polygons.foreach_get('loop_total', lt)
        me.polygons.foreach_get('loop_start', ls)
        lv = np.empty(len(me.loops), np.int64)
        me.loops.foreach_get('vertex_index', lv)
        self.polys = [lv[s:s + t] for s, t in zip(ls, lt)]
        tris = []
        for pv in self.polys:
            for k in range(1, len(pv) - 1):
                tris.append((pv[0], pv[k], pv[k + 1]))
        self.tris = np.array(tris)
        names = [g.name for g in h.vertex_groups]
        self.names = names
        W = np.zeros((n, len(names)), np.float32)
        for v in me.vertices:
            for g in v.groups:
                if g.group < len(names):
                    W[v.index, g.group] = g.weight
        self.W = W
        self.gi = {nm: i for i, nm in enumerate(names)}
        self.isbody = self.w('body') > 0.5
        self.nrm = self.normals(self.co)
        # joints
        self.J = {}
        for nm in names:
            if nm.startswith('joint-'):
                m = self.w(nm) > 0.5
                if m.any():
                    self.J[nm[6:]] = self.co[m].mean(0)
        hw = self.w('head')
        hm = (hw > 0.9) & self.isbody
        self.crown_z = self.co[hm, 2].max()
        self.head_c = self.co[hm].mean(0)
        eyes = [self.J.get('l-eye'), self.J.get('r-eye')]
        self.eye = np.mean([e for e in eyes if e is not None], 0)
        self.chin_z = self.co[hm & (self.co[:, 1] < self.eye[1] + 0.02), 2].min()
        self.head_h = self.crown_z - self.chin_z
        # adjacency for smoothing
        self.nb_cnt = np.bincount(self.edges.ravel(), minlength=n).astype(float)

    def w(self, *groups):
        out = np.zeros(len(self.co), np.float32)
        for g in groups:
            if g in self.gi:
                out += self.W[:, self.gi[g]]
        return out

    def wprefix(self, *prefixes):
        out = np.zeros(len(self.co), np.float32)
        for nm, i in self.gi.items():
            if nm.startswith(prefixes) and not nm.startswith('joint'):
                out += self.W[:, i]
        return out

    def normals(self, co):
        t = self.tris
        fn = np.cross(co[t[:, 1]] - co[t[:, 0]], co[t[:, 2]] - co[t[:, 0]])
        N = np.zeros_like(co)
        for k in range(3):
            np.add.at(N, t[:, k], fn)
        return N / np.maximum(np.linalg.norm(N, axis=1), 1e-12)[:, None]

    def smooth(self, co, iters, lam=0.5, mu=-0.53, mask=None):
        co = co.copy()
        a, b = self.edges[:, 0], self.edges[:, 1]
        cnt = np.maximum(self.nb_cnt, 1)[:, None]
        for _ in range(iters):
            for f in (lam, mu):
                s = np.zeros_like(co)
                np.add.at(s, a, co[b])
                np.add.at(s, b, co[a])
                d = s / cnt - co
                if mask is not None:
                    d *= mask[:, None]
                co += f * d
        return co

    def grow(self, sel, rings):
        sel = sel.copy()
        a, b = self.edges[:, 0], self.edges[:, 1]
        for _ in range(rings):
            s2 = sel.copy()
            s2[a[sel[b]]] = True
            s2[b[sel[a]]] = True
            sel = s2
        return sel

    def shrink(self, sel, rings):
        return ~self.grow(~sel, rings)

    def free(self):
        bpy.data.meshes.remove(self.me)


# --------------------------------------------------------------------------------------
# Materials (colour lives in a vertex colour so it survives FBX export to a game engine)
# --------------------------------------------------------------------------------------

def vc_material(name, rough=0.8, sheen=0.0, metal=0.0, alpha=False, bump=0.0, bump_scale=200.0):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    try:
        mat.use_nodes = True
    except Exception:
        pass
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')
    vc = nt.nodes.new('ShaderNodeVertexColor')
    vc.layer_name = 'Col'
    nt.links.new(vc.outputs['Color'], bsdf.inputs['Base Color'])
    nt.links.new(bsdf.outputs[0], out.inputs[0])
    bsdf.inputs['Roughness'].default_value = rough
    bsdf.inputs['Metallic'].default_value = metal
    for key in ('Sheen Weight', 'Sheen'):
        if key in bsdf.inputs:
            bsdf.inputs[key].default_value = sheen
            break
    if alpha:
        nt.links.new(vc.outputs['Alpha'], bsdf.inputs['Alpha'])
        for attr, val in (('blend_method', 'HASHED'), ('surface_render_method', 'DITHERED')):
            try:
                setattr(mat, attr, val)
            except Exception:
                pass
    if bump > 0:
        tex = nt.nodes.new('ShaderNodeTexNoise')
        tex.inputs['Scale'].default_value = bump_scale
        bm = nt.nodes.new('ShaderNodeBump')
        bm.inputs['Strength'].default_value = bump
        nt.links.new(tex.outputs['Fac'], bm.inputs['Height'])
        nt.links.new(bm.outputs['Normal'], bsdf.inputs['Normal'])
    return mat


MATS = {
    'cotton': dict(rough=0.88, sheen=0.3, bump=0.1, bump_scale=420),
    'fleece': dict(rough=0.93, sheen=0.4, bump=0.14, bump_scale=300),
    'denim': dict(rough=0.82, sheen=0.18, bump=0.18, bump_scale=600),
    'nylon': dict(rough=0.32, sheen=0.0, bump=0.0),
    'satin': dict(rough=0.38, sheen=0.05, bump=0.0),
    'knit': dict(rough=0.95, sheen=0.08, bump=0.2, bump_scale=250),
    'hair': dict(rough=0.66, sheen=0.08, alpha=True, bump=0.5, bump_scale=900),
    'locs': dict(rough=0.85, sheen=0.0, bump=0.6, bump_scale=700),
    'coil': dict(rough=0.6, sheen=0.0),
    'hairsolid': dict(rough=0.72, sheen=0.0, bump=0.25, bump_scale=900),
    'leather': dict(rough=0.4, bump=0.05, bump_scale=300),
    'gold': dict(rough=0.18, metal=1.0),
    'chrome': dict(rough=0.12, metal=1.0),
    'rubber': dict(rough=0.6),
}


def get_mat(kind):
    return vc_material("SY_Urban_" + kind, **MATS[kind])


# --------------------------------------------------------------------------------------
# Object creation helpers
# --------------------------------------------------------------------------------------

def _attach(ob, h, rig, coll):
    coll.objects.link(ob)
    if rig is not None:
        ob.parent = rig
        ob.matrix_parent_inverse = h.matrix_parent_inverse.copy()
        ob.matrix_basis = h.matrix_basis.copy()
        mod = ob.modifiers.new("Armature", 'ARMATURE')
        mod.object = rig
    else:
        ob.parent = h


def _set_colors(me, rgba):
    attr = me.color_attributes.get('Col') or me.color_attributes.new('Col', 'FLOAT_COLOR', 'POINT')
    attr.data.foreach_set('color', np.asarray(rgba, np.float32).ravel())
    try:
        me.color_attributes.active_color = attr
        me.color_attributes.render_color_index = me.color_attributes.active_color_index
    except Exception:
        pass


def shell_object(B, h, rig, coll, name, co_new, keep, rgba, kind, solid=0.0035):
    """Copy the basemesh, move its verts to co_new, keep faces whose verts are all in keep."""
    me = B.me.copy()
    me.name = name
    me.vertices.foreach_set('co', co_new.ravel())
    for attr in list(me.color_attributes):
        me.color_attributes.remove(attr)
    _set_colors(me, rgba)
    if me.shape_keys:
        pass
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    dead = [f for f in bm.faces if not all(keep[v.index] for v in f.verts)]
    bmesh.ops.delete(bm, geom=dead, context='FACES')
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context='VERTS')
    # straighten the cut edges (hems, necklines, hairlines) so they don't follow the body's quad steps
    bnd = [v for v in bm.verts if v.is_boundary]
    for _ in range(6):
        new = {}
        for v in bnd:
            nb = [e.other_vert(v) for e in v.link_edges if e.is_boundary]
            if len(nb) == 2:
                new[v] = v.co * 0.5 + (nb[0].co + nb[1].co) * 0.25
        for v, c in new.items():
            v.co = c
    bm.to_mesh(me)
    bm.free()
    me.materials.clear()
    me.materials.append(get_mat(kind))
    try:
        me.polygons.foreach_set('use_smooth', np.ones(len(me.polygons), bool))
    except Exception:
        pass
    me.update()
    ob = bpy.data.objects.new(name, me)
    for nm in B.names:
        ob.vertex_groups.new(name=nm)
    coll.objects.link(ob)
    if kind not in ('hair',):
        sub = ob.modifiers.new("Subdivision", 'SUBSURF')
        sub.levels = 1
        sub.render_levels = 1
        tex = bpy.data.textures.get("SY_Folds") or bpy.data.textures.new("SY_Folds", 'CLOUDS')
        tex.noise_scale = 0.07
        tex.noise_depth = 3
        d = ob.modifiers.new("Folds", 'DISPLACE')
        d.texture = tex
        d.texture_coords = 'LOCAL'
        d.strength = {'fleece': 0.0022, 'denim': 0.0025, 'cotton': 0.0010}.get(kind, 0.0015)
        d.mid_level = 0.5
    coll.objects.unlink(ob)
    _attach(ob, h, rig, coll)
    if solid > 0:
        s = ob.modifiers.new("Thickness", 'SOLIDIFY')
        s.thickness = solid
        s.offset = -1.0
        s.use_rim = True
        s.use_even_offset = False
        s.thickness_clamp = 0.5
    return ob


def tube_mesh(paths, radii, colors, name, sides=6, twist=0.0, bulge=0.0, bulge_freq=0.0, flat=1.0):
    """paths: list of (n,3) polylines. radii: list of (n,) arrays. colors: list of (n,4)."""
    V, F, C = [], [], []
    for P, R, Cc in zip(paths, radii, colors):
        n = len(P)
        base = len(V)
        T = np.gradient(P, axis=0)
        T /= np.maximum(np.linalg.norm(T, axis=1), 1e-9)[:, None]
        up = np.array([0, 0, 1.0]) if abs(T[0][2]) < 0.9 else np.array([1.0, 0, 0])
        Nn = np.cross(T[0], up)
        Nn /= np.linalg.norm(Nn)
        for i in range(n):
            Nn = Nn - T[i] * (Nn @ T[i])
            Nn /= max(np.linalg.norm(Nn), 1e-9)
            Bn = np.cross(T[i], Nn)
            r = R[i] * (1 + bulge * math.sin(i * bulge_freq)) if bulge else R[i]
            for k in range(sides):
                a = 2 * math.pi * k / sides + twist * i
                V.append(P[i] + (Nn * math.cos(a) * flat + Bn * math.sin(a)) * r)
                C.append(Cc[i])
        for i in range(n - 1):
            for k in range(sides):
                k2 = (k + 1) % sides
                F.append((base + i * sides + k, base + i * sides + k2, base + (i + 1) * sides + k2, base + (i + 1) * sides + k))
        # end caps
        c0 = len(V)
        V.append(P[0])
        C.append(Cc[0])
        F += [(c0, base + (k + 1) % sides, base + k) for k in range(sides)]
        c1 = len(V)
        V.append(P[-1])
        C.append(Cc[-1])
        last = base + (n - 1) * sides
        F += [(c1, last + k, last + (k + 1) % sides) for k in range(sides)]
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in V], [], F)
    _set_colors(me, np.array(C))
    try:
        me.polygons.foreach_set('use_smooth', np.ones(len(me.polygons), bool))
    except Exception:
        pass
    me.update()
    return me


def mesh_object(me, h, rig, coll, kind, bone_weights):
    me.materials.clear()
    me.materials.append(get_mat(kind))
    ob = bpy.data.objects.new(me.name, me)
    for bname, w in bone_weights.items():
        vg = ob.vertex_groups.new(name=bname)
        if np.isscalar(w):
            vg.add(list(range(len(me.vertices))), float(w), 'REPLACE')
        else:
            q = np.round(np.asarray(w) * 20).astype(int)
            for lv in np.unique(q):
                if lv > 0:
                    vg.add(np.nonzero(q == lv)[0].tolist(), lv / 20.0, 'REPLACE')
    _attach(ob, h, rig, coll)
    return ob


def hide_body_under(h, B, keep, rings=3, tag="SY"):
    covered = B.shrink(keep, rings) & B.isbody
    name = "Delete." + tag
    vg = h.vertex_groups.get(name) or h.vertex_groups.new(name=name)
    idx = np.nonzero(covered)[0].tolist()
    if idx:
        vg.add(idx, 1.0, 'REPLACE')
        m = h.modifiers.new(name, 'MASK')
        m.vertex_group = name
        m.invert_vertex_group = True


def rgba(col, n, a=1.0):
    out = np.ones((n, 4))
    out[:, :3] = col
    out[:, 3] = a
    return out


# --------------------------------------------------------------------------------------
# Patterns (painted into vertex colour)
# --------------------------------------------------------------------------------------

def pattern_colors(co, base, pattern, accent):
    n = len(co)
    c = np.tile(base, (n, 1)).astype(float)
    if pattern == 'CAMO':
        pal = [base, base * 0.55 + accent * 0.0 + np.array([0.02, 0.025, 0.01]), base * 0.35 + 0.01,
               accent]
        f = np.array([noise.noise(Vector(p * 9.0)) + 0.5 * noise.noise(Vector(p * 21.0 + 3)) for p in co])
        g = np.array([noise.noise(Vector(p * 9.0 + 40)) for p in co])
        c[f > 0.12] = pal[1]
        c[(f < -0.2)] = pal[2]
        c[(g > 0.35)] = pal[3]
    elif pattern == 'STRIPE':
        z = co[:, 2]
        c[(np.sin(z * 2 * math.pi / 0.09) > 0.55)] = accent
    elif pattern == 'BLOCK':
        c[co[:, 2] > np.percentile(co[:, 2], 62)] = accent
    elif pattern == 'TWOTONE_SLEEVE':
        pass
    jitter = np.array([noise.noise(Vector(p * 60.0)) for p in co]) * 0.04
    return np.clip(c * (1 + jitter)[:, None], 0, 1)


# --------------------------------------------------------------------------------------
# TOPS
# --------------------------------------------------------------------------------------

def _regions(B):
    torso = B.w('pelvis', 'spine_01', 'spine_02', 'spine_03', 'clavicle_l', 'clavicle_r')
    neck = B.w('neck_01')
    head = B.w('head')
    upper = B.w('upperarm_l', 'upperarm_r')
    lower = B.w('lowerarm_l', 'lowerarm_r')
    hand = B.wprefix('hand_', 'index', 'middle', 'pinky', 'ring', 'thumb')
    thigh = B.w('thigh_l', 'thigh_r')
    calf = B.w('calf_l', 'calf_r')
    foot = B.w('foot_l', 'foot_r', 'ball_l', 'ball_r')
    return dict(torso=torso, neck=neck, head=head, upper=upper, lower=lower, hand=hand, thigh=thigh,
                calf=calf, foot=foot)


def _arm_param(B, co, side_sign):
    """0 at shoulder, 1 at wrist along the arm (per side)."""
    s = 'l' if side_sign > 0 else 'r'
    S, E, W = B.J.get(s + '-shoulder'), B.J.get(s + '-elbow'), B.J.get(s + '-hand')
    if S is None or W is None:
        return np.zeros(len(co))
    d = W - S
    return np.clip(((co - S) @ d) / (d @ d), -1, 2)


def _arm_t(B, co):
    tl = _arm_param(B, co, 1)
    tr = _arm_param(B, co, -1)
    return np.where(co[:, 0] > 0, tl, tr) if B.J['l-shoulder'][0] > 0 else np.where(co[:, 0] > 0, tr, tl)


SIM_MODE = False
FREE_DRAPE = False   # posed gravity drape: pin only the yoke
HAIR_OBSTACLES = []   # SDFs (e.g. a laid hood) that long strands must rest on, not pass through


def _boundary_loops(bm):
    edges = [e for e in bm.edges if e.is_boundary]
    seen, loops = set(), []
    for e0 in edges:
        if e0 in seen:
            continue
        stack, comp = [e0], []
        seen.add(e0)
        while stack:
            e = stack.pop()
            comp.append(e)
            for v in e.verts:
                for e2 in v.link_edges:
                    if e2.is_boundary and e2 not in seen:
                        seen.add(e2)
                        stack.append(e2)
        loops.append(comp)
    return loops


def extend_hem(ob, length, flare, pick='torso', rings=5, center_xy=None, folds=0.0, nfolds=9, seed=0,
               level=False, rib=0, rib_in=0.0, rib_shade=0.86):
    """Extrude the hem loop(s) of a garment straight down so it hangs like real fabric
    instead of ending on the body. pick='torso' -> the single loop around the hips,
    pick='legs' -> the two lowest loops (pant hems)."""
    if length <= 0:
        return ob
    me = ob.data
    bm = bmesh.new()
    bm.from_mesh(me)
    loops = _boundary_loops(bm)
    info = []
    for L in loops:
        vs = {v for e in L for v in e.verts}
        c = sum((v.co for v in vs), Vector()) / len(vs)
        info.append((c.z, abs(c.x), L, c))
    if pick == 'torso':
        cand = [i for i in info if i[1] < 0.05 and len(i[2]) > 12]
        cand = sorted(cand, key=lambda i: i[0])[:1]
    elif pick == 'sleeves':
        cand = sorted([i for i in info if i[1] > 0.12 and len(i[2]) > 6], key=lambda i: -i[1])[:2]
    else:
        cand = sorted([i for i in info if len(i[2]) > 6], key=lambda i: i[0])[:2]
    uvl = bm.loops.layers.uv.active
    old_faces = set(bm.faces)
    tag = {}
    col_layer = bm.verts.layers.float_color.get('Col')
    for li, (zc, _, L, c) in enumerate(cand):
        zmin = min(v.co.z for e in L for v in e.verts)
        for e in L:
            for v in e.verts:
                tag[v] = (li, 0, math.atan2(v.co.y - c.y, v.co.x - c.x))
        cur = L
        for k in range(rings):
            ret = bmesh.ops.extrude_edge_only(bm, edges=cur)
            nv = [g for g in ret['geom'] if isinstance(g, bmesh.types.BMVert)]
            ne = [g for g in ret['geom'] if isinstance(g, bmesh.types.BMEdge)]
            for v in nv:
                if pick == 'sleeves' and center_xy is not None:
                    o = Vector(center_xy[0] if c.x * center_xy[0][0] > 0 else center_xy[1])
                    ax = (c - o).normalized()
                    r = (v.co - c)
                    r = (r - ax * r.dot(ax))
                    if r.length > 1e-6:
                        r.normalize()
                    v.co += ax * (length / rings) + r * (flare / rings)
                    tag[v] = (li, k + 1, math.atan2(v.co.y - c.y, (v.co - c).dot(Vector((0, 0, 1))) + (v.co.x - c.x)))
                    continue
                r = Vector((v.co.x - c.x, v.co.y - c.y, 0.0))
                if r.length > 1e-6:
                    r.normalize()
                v.co.z -= length / rings
                if level:
                    # a real hem hangs level: pull each ring toward a horizontal line
                    tgt = zmin - length * (k + 1) / rings
                    wl = (k + 1) / rings
                    v.co.z = v.co.z * (1 - wl) + tgt * wl
                ang = math.atan2(r.y, r.x)
                rip = folds / rings * (math.sin(ang * nfolds + seed) * 0.7 + math.sin(ang * (nfolds * 2 + 3) + 2 * seed) * 0.3)
                in_rib = rib and k >= rings - rib
                if in_rib:
                    rip = 0.0
                v.co += r * (flare / rings + rip - (rib_in if in_rib and k == rings - rib else 0.0))
                if in_rib and col_layer is not None:
                    cc = v[col_layer]
                    v[col_layer] = (cc[0] * rib_shade, cc[1] * rib_shade, cc[2] * rib_shade, cc[3])
                tag[v] = (li, k + 1, ang)
            cur = [e for e in ne if e.is_boundary]
        # crisp edge: a 3mm ring right at the hem so smooth shading turns the corner tightly
        # (no rounded 'pillow' edge), plus the folded-hem step and its stitch line ~1.5cm up
        ret = bmesh.ops.extrude_edge_only(bm, edges=cur)
        nv = [g for g in ret['geom'] if isinstance(g, bmesh.types.BMVert)]
        for v in nv:
            if pick == 'sleeves' and center_xy is not None:
                o = Vector(center_xy[0] if c.x * center_xy[0][0] > 0 else center_xy[1])
                v.co += (c - o).normalized() * 0.003
            else:
                v.co.z -= 0.003
            tag[v] = (li, rings + 1, tag.get(v, (li, 0, math.atan2(v.co.y - c.y, v.co.x - c.x)))[2]
                      if False else math.atan2(v.co.y - c.y, v.co.x - c.x))
        for v in list(tag):
            if not v.is_valid or tag[v][0] != li:
                continue
            kk = tag[v][1]
            if kk == rings and col_layer is not None and not rib:
                cc = v[col_layer]
                v[col_layer] = (cc[0] * 0.9, cc[1] * 0.9, cc[2] * 0.9, cc[3])
        cur = [e for e in bm.edges if e.is_boundary and all(x in nv for x in e.verts)]
    # the hanging hem must not follow the thighs when the legs pose (that pulls it inward into a
    # curled, puffy edge): hand thigh weights over to the pelvis on the extension
    if pick == 'torso':
        dl = bm.verts.layers.deform.active
        gi = {vg.name: vg.index for vg in ob.vertex_groups}
        pel_i = gi.get('pelvis')
        thighs = [gi[n] for n in ('thigh_l', 'thigh_r') if n in gi]
        if dl is not None and pel_i is not None and thighs:
            for v, t in tag.items():
                if not v.is_valid:
                    continue
                frac = 1.0 if t[1] > 0 else 0.6
                dv = v[dl]
                moved = 0.0
                for ti in thighs:
                    if ti in dv:
                        w = dv[ti] * frac
                        dv[ti] = dv[ti] - w
                        moved += w
                if moved > 0:
                    dv[pel_i] = dv.get(pel_i, 0.0) + moved
    # UVs: squeeze the original layout into u<0.8 and give each new band its own strip on the right,
    # so the position-based texture bake has clean, non-overlapping texels (no bpy.ops needed)
    if uvl is not None and cand:
        ncol = len(cand)
        for f in bm.faces:
            if f in old_faces:
                for lp in f.loops:
                    lp[uvl].uv.x *= 0.8
            else:
                vs = [tag.get(lp.vert, (0, 0, 0.0)) for lp in f.loops]
                us = [(t[2] + math.pi) / (2 * math.pi) for t in vs]
                if max(us) - min(us) > 0.5:
                    us = [u + 1.0 if u < 0.5 else u for u in us]
                for lp, t, u in zip(f.loops, vs, us):
                    col = 0.81 + t[0] * (0.18 / ncol)
                    lp[uvl].uv.x = col + (0.18 / ncol - 0.005) * t[1] / (rings + 1)
                    lp[uvl].uv.y = 0.01 + 0.93 * u / 1.04
    bm.to_mesh(me)
    bm.free()
    me.update()
    return ob


def _hang_from_chest(B, P, co, arm, hem, style):
    """Fabric hangs from the chest/shoulder blades: below the chest a top can't pull in to
    follow the waist, so the side profile drops straight (no pinched 'peplum' waist)."""
    shz = (B.J['l-shoulder'][2] + B.J['r-shoulder'][2]) / 2
    chest_z = shz - 0.13
    tor = (arm < 0.45) & (co[:, 2] < chest_z + 0.02) & (co[:, 2] > hem - 0.01) & (np.abs(co[:, 0]) < 0.3)
    idx = np.nonzero(tor)[0]
    if len(idx) < 20:
        return P
    Q = P[idx]
    # slice centres (front/back midpoint at each height)
    # one fixed centre line (from the chest) so the back bridges the lumbar hollow and the
    # front falls straight off the chest instead of following the belly/waist
    cm = np.abs(Q[:, 2] - (chest_z - 0.01)) < 0.02
    cy0 = 0.5 * (Q[cm, 1].min() + Q[cm, 1].max()) if cm.sum() > 4 else Q[:, 1].mean()
    cy = np.full(len(Q), cy0)
    dx, dy = Q[:, 0], Q[:, 1] - cy
    r = np.hypot(dx, dy)
    ang = np.arctan2(dy, dx)
    nb = 40
    ab = np.floor((ang + math.pi) / (2 * math.pi) * nb).astype(int) % nb
    r_new = r.copy()
    for b in range(nb):
        m = np.nonzero(ab == b)[0]
        if len(m) == 0:
            continue
        o = m[np.argsort(-Q[m, 2])]
        env = 0.0
        for j in o:
            env = max(env, r[j])                  # no per-vertex decay: the side seam drops straight
            r_new[j] = max(r[j], env * 0.98)
    # boxy cut: below the chest the cross-section is at least a rounded rectangle as wide as the
    # chest panel (straight side seams from armpit to hem), not the body's waist curve
    sh = abs(B.J['l-shoulder'][0])
    Wx = sh * {'BOXY_TEE': 1.07, 'JERSEY': 1.1, 'HOODIE': 1.05, 'ZIPUP': 1.0, 'LONGSLEEVE': 0.95}.get(style, 1.0)
    cmask = np.abs(Q[:, 2] - (chest_z - 0.01)) < 0.025
    if cmask.sum() > 4:
        Df = cy0 - Q[cmask, 1].min()
        Db = Q[cmask, 1].max() - cy0
        Wy = np.where(dy < 0, Df, Db) * 1.02
        c_, s_ = np.abs(np.cos(ang)), np.abs(np.sin(ang))
        pexp = 4.0
        Rbox = 1.0 / ((c_ / Wx) ** pexp + (s_ / np.maximum(Wy, 1e-3)) ** pexp + 1e-12) ** (1 / pexp)
        r_new = np.maximum(r_new, Rbox)
    # hoodie / zip-up rib band at the hem still gathers in a little
    if style in ('HOODIE', 'ZIPUP'):
        band = smoothstep(hem + 0.07, hem + 0.01, Q[:, 2])
        r_new = r_new - (r_new - r) * 0.25 * band
    blend = smoothstep(chest_z + 0.02, chest_z - 0.04, Q[:, 2])
    rr = r + (r_new - r) * blend
    sc = rr / np.maximum(r, 1e-6)
    D = np.zeros_like(P)
    D[idx, 0] = dx * sc - Q[:, 0]
    D[idx, 1] = cy + dy * sc - Q[:, 1]
    # the push-out is a smooth field over the garment (no per-vertex lumps)
    D = B.smooth(D, 8, lam=0.5, mu=0.0)
    return P + D


def garment_folds(B, co, arm, armt, sleeve_end, hem, style):
    """Structured cloth folds where real tops crease: radiating armpit folds (arms hang down),
    stacked rings above long-sleeve cuffs, inner-elbow creases, gathers above a rib hem."""
    out = np.zeros(len(co))
    shz = (B.J['l-shoulder'][2] + B.J['r-shoulder'][2]) / 2
    sh = abs(B.J['l-shoulder'][0])
    wob = vnoise(co, 0.05, 11)
    # armpit: folds fan out from the armpit across the side of the chest and the upper sleeve
    for sx in (1, -1):
        ap = np.array([sx * sh * 0.92, 0.0, shz - 0.11])
        d = co - ap
        dist = np.linalg.norm(d, axis=1)
        ang = np.arctan2(d[:, 2], d[:, 0] * sx + 0.5 * np.abs(d[:, 1]))
        f = np.sin(ang * 9 + wob * 2.0)
        fall = smoothstep(0.17, 0.05, dist) * smoothstep(0.01, 0.04, dist)
        out += 0.0055 * f * fall * (np.sign(co[:, 0]) == sx)
    # long sleeves: fabric stacks into rings above the cuff, and creases at the inner elbow
    if sleeve_end > 0.8:
        a_in = (arm > 0.5)
        stack = smoothstep(sleeve_end - 0.3, sleeve_end - 0.12, armt) * smoothstep(sleeve_end - 0.02, sleeve_end - 0.07, armt)
        ring = np.sin(armt * 2 * math.pi / 0.065 + wob * 3.0)
        out += 0.0065 * ring * stack * a_in
        elbow = np.exp(-((armt - 0.5) / 0.07) ** 2) * (co[:, 1] < 0.0)
        out += 0.004 * np.sin(armt * 2 * math.pi / 0.04 + wob * 2) * elbow * a_in
    # tees: a few long vertical drape folds falling from the chest / shoulder blades
    if style in ('BOXY_TEE', 'JERSEY', 'LONGSLEEVE'):
        chest_z = shz - 0.13
        g = smoothstep(chest_z, chest_z - 0.2, co[:, 2]) * (arm < 0.3)
        th = np.arctan2(co[:, 0], -co[:, 1])
        cusp = 1.0 - 2.0 * np.abs(np.sin(th * 3.5 + wob * 1.5)) ** 0.6   # soft ridges, sharper valleys
        out += 0.0045 * cusp * g
    # rib-hem gathers (hoodies / zip-ups): vertical ripples just above the band
    if style in ('HOODIE', 'ZIPUP'):
        g = smoothstep(hem + 0.16, hem + 0.06, co[:, 2]) * smoothstep(hem + 0.01, hem + 0.05, co[:, 2]) * (arm < 0.3)
        out += 0.005 * np.sin(np.arctan2(co[:, 0], co[:, 1]) * 22 + wob * 2.5) * g
    return out


def make_top(B, h, rig, coll, name, style, color, accent, pattern):
    R = _regions(B)
    co, N = B.co, B.nrm
    pel = B.J['pelvis']
    neck = B.J['neck']
    armt = _arm_t(B, co)
    arm = R['upper'] + R['lower']
    sleeve_end = {'HOODIE': 0.97, 'PUFFER': 0.97, 'BOXY_TEE': 0.42, 'LONGSLEEVE': 0.97, 'JERSEY': 0.38,
                  'ZIPUP': 0.97}[style]
    hem = pel[2] - {'HOODIE': 0.07, 'PUFFER': 0.0, 'BOXY_TEE': 0.11, 'LONGSLEEVE': 0.09, 'JERSEY': 0.13,
                    'ZIPUP': 0.05}[style]
    hem = pel[2] + 0.015
    keep = B.isbody & (co[:, 2] > hem) & (R['head'] < 0.4) & (R['hand'] < 0.35)
    keep &= ~((arm > 0.5) & (armt > sleeve_end))
    keep &= (R['thigh'] < 0.12)
    # neckline: lower at the front, rising at the back like a real crew/hoodie neck
    # neckline follows the base of the neck: low at the front, up over the trapezius at the
    # sides, highest at the back (a real crew neck, not a wide boat neck)
    na = np.arctan2(co[:, 0] - neck[0], -(co[:, 1] - neck[1]))
    nback = 0.5 - 0.5 * np.cos(na)
    nside = np.abs(np.sin(na))
    base_cut = {'BOXY_TEE': -0.035, 'JERSEY': -0.045, 'LONGSLEEVE': -0.03, 'HOODIE': -0.04,
                'ZIPUP': -0.035}.get(style, -0.005)
    zcut = neck[2] + base_cut + 0.03 * nside + 0.035 * nback
    near_neck = np.hypot(co[:, 0] - neck[0], co[:, 1] - neck[1]) < 0.11
    keep &= ~near_neck | (co[:, 2] < zcut)
    keep &= co[:, 2] < neck[2] + 0.02
    base = {'HOODIE': 0.03, 'PUFFER': 0.05, 'BOXY_TEE': 0.016, 'LONGSLEEVE': 0.008, 'JERSEY': 0.02,
            'ZIPUP': 0.022}[style]
    armx = {'HOODIE': 0.012, 'PUFFER': 0.0, 'BOXY_TEE': 0.018, 'LONGSLEEVE': 0.0, 'JERSEY': 0.02,
            'ZIPUP': 0.008}[style]
    off = base + armx * np.clip(arm, 0, 1)
    shz_ = (B.J['l-shoulder'][2] + B.J['r-shoulder'][2]) / 2
    sh_ = abs(B.J['l-shoulder'][0])
    cap = smoothstep(shz_ - 0.06, shz_ + 0.01, co[:, 2]) * smoothstep(sh_ * 0.6, sh_ * 1.05, np.abs(co[:, 0]))
    off = off * (1 - 0.55 * cap * (style != 'PUFFER'))
    # hang: looser toward the hem, boxy
    off += 0.012 * smoothstep(pel[2] + 0.15, hem, co[:, 2]) * (style in ('BOXY_TEE', 'JERSEY', 'HOODIE'))
    # hems hang loose over the waistband of baggy pants
    flare = {'HOODIE': 0.03, 'ZIPUP': 0.028, 'PUFFER': 0.01, 'BOXY_TEE': 0.045, 'LONGSLEEVE': 0.03, 'JERSEY': 0.05}[style]
    flare *= 0.3
    off = off + flare * smoothstep(pel[2] + 0.16, hem, co[:, 2]) * (arm < 0.3)
    # the top must sit OUTSIDE the pants' waistband so the extended hem hangs over it
    off = off + 0.034 * smoothstep(pel[2] + 0.16, pel[2] + 0.07, co[:, 2]) * (arm < 0.3) * (style != 'PUFFER')
    if style in ('HOODIE', 'ZIPUP', 'LONGSLEEVE'):
        # sleeves are straight tubes: roomy at the upper arm, narrowing slightly toward the cuff
        sl = arm > 0.5
        cap_off = (0.026 if style != 'LONGSLEEVE' else 0.012) - 0.01 * np.clip(armt, 0, 1)
        off = np.where(sl, np.minimum(off, cap_off), off)
    # ribbed cuffs / hem bands (hoodie, zip-up, puffer cuffs)
    if style in ('HOODIE', 'ZIPUP', 'PUFFER', 'LONGSLEEVE'):
        cuff = smoothstep(sleeve_end - 0.06, sleeve_end - 0.01, armt) * (arm > 0.3)
        off = off * (1 - 0.75 * cuff)
        band = smoothstep(hem + 0.06, hem + 0.01, co[:, 2])
        off = off * (1 - 0.25 * band * (style != 'PUFFER'))
    # neckline: tighter near neck
    nk = smoothstep(neck[2] - 0.08, neck[2], co[:, 2]) * (arm < 0.3)
    off = off * (1 - 0.6 * nk)
    if style == 'PUFFER':
        # quilted channels: horizontal on body, around the arm on sleeves
        q_body = 0.5 + 0.5 * np.cos(co[:, 2] * 2 * math.pi / 0.115)
        q_arm = 0.5 + 0.5 * np.cos(armt * 2 * math.pi / 0.2)
        q = np.where(arm > 0.5, q_arm, q_body)
        off = off + 0.018 * q
    smooth_body = B.smooth(co, 18)   # fabric bridges over the chest/pec contours instead of hugging them
    Ns = B.normals(smooth_body)
    P = smooth_body + Ns * off[:, None]
    P = B.smooth(P, 10)
    if style != 'PUFFER':
        P = _hang_from_chest(B, P, co, arm, hem, style)
        P = B.smooth(P, 10)     # fabric panels read flat, not lumpy over the belly
    # drape: let the bottom 8cm hang straight down past the hips
    hang = smoothstep(hem + 0.12, hem, co[:, 2]) * (arm < 0.3)
    drop = {'HOODIE': 0.09, 'BOXY_TEE': 0.13, 'JERSEY': 0.14, 'LONGSLEEVE': 0.08, 'ZIPUP': 0.08, 'PUFFER': 0.035}[style]
    drop *= 0.15
    P[:, 2] -= drop * hang
    # folds
    fold = np.array([noise.noise(Vector(p * 7.0)) for p in co])
    P += Ns * ({'HOODIE': 0.003, 'ZIPUP': 0.003}.get(style, 0.0012) * fold)[:, None] * (style != 'PUFFER')
    if style != 'PUFFER':
        P += Ns * garment_folds(B, co, arm, armt, sleeve_end, hem, style)[:, None]
    cols = pattern_colors(co, color, pattern, accent)
    if style == 'JERSEY':
        cols[(arm > 0.4) & (armt > sleeve_end - 0.06)] = accent
        cols[np.abs(co[:, 0]) < 0.0] = accent
    if style == 'PUFFER':
        q_d = np.where(arm > 0.5, 0.5 + 0.5 * np.cos(armt * 2 * math.pi / 0.2),
                       0.5 + 0.5 * np.cos(co[:, 2] * 2 * math.pi / 0.115))
        cols *= (0.75 + 0.25 * q_d)[:, None]
    if style in ('HOODIE', 'ZIPUP'):
        cuffs = (arm > 0.3) & (armt > sleeve_end - 0.06)
        cols[cuffs] *= 0.88
    if style == 'ZIPUP':
        front = (np.abs(co[:, 0]) < 0.008) & (N[:, 1] < -0.4)
        cols[front] = np.array([0.6, 0.6, 0.62])
    ob = shell_object(B, h, rig, coll, name, P, keep, np.concatenate([cols, np.ones((len(co), 1))], 1),
                      'nylon' if style == 'PUFFER' else ('fleece' if style in ('HOODIE', 'ZIPUP') else 'cotton'),
                      solid=0.004)
    # real tops hang past the waistband: extend the hem straight down
    # hem lengths from real fits: boxy tee hem at / just below the hip, hoodie band at high-to-mid hip
    ext = {'BOXY_TEE': (0.075, 0.006), 'JERSEY': (0.09, 0.008), 'LONGSLEEVE': (0.07, 0.004),
           'HOODIE': (0.075, 0.004), 'ZIPUP': (0.065, 0.004), 'PUFFER': (0.0, 0.0)}[style]
    ribbed = style in ('HOODIE', 'ZIPUP')
    extend_hem(ob, ext[0], ext[1], 'torso', rings=6, folds=0.0 if ribbed else 0.005, nfolds=6, level=True,
               rib=2 if ribbed else 0, rib_in=0.012 if ribbed else 0.0)
    if style in ('BOXY_TEE', 'JERSEY'):
        # open, wide sleeve ends that hang past the elbow line instead of a rounded cuff
        extend_hem(ob, 0.035, 0.008, 'sleeves', rings=2,
                   center_xy=(tuple(B.J['l-shoulder']), tuple(B.J['r-shoulder'])))
    extras = []
    if style in ('HOODIE', 'ZIPUP'):
        hd = _laid_hood(B, h, rig, coll, name, color, zip_front=(style == 'ZIPUP'))
        if hd is not None:
            extras.append(hd)
    elif style == 'PUFFER':
        extras.append(_hood_or_collar(B, h, rig, coll, name, style, color, P, keep))
    else:
        cc = _crew_collar(B, h, rig, coll, name, ob, color)
        if cc is not None:
            extras.append(cc)
    return [ob] + extras, keep


def body_skin(B, V, k=4):
    """Skin weights for loose geometry copied from the nearest body vertices, so add-ons
    (collars, hoods) move exactly with the shirt/body under them when posed."""
    from mathutils.kdtree import KDTree
    kd = getattr(B, '_skin_kd', None)
    if kd is None:
        ids = np.nonzero(B.isbody)[0]
        kd = KDTree(len(ids))
        for j, i in enumerate(ids):
            kd.insert(Vector(B.co[i]), int(i))
        kd.balance()
        B._skin_kd = kd
    acc = np.zeros((len(V), B.W.shape[1]), np.float32)
    for n, v in enumerate(V):
        hits = kd.find_n(Vector(v), k)
        tw = 0.0
        for _, i, d in hits:
            w = 1.0 / max(d, 1e-4)
            acc[n] += B.W[i] * w
            tw += w
        acc[n] /= max(tw, 1e-9)
    out = {}
    for j, nm in enumerate(B.names):
        if nm in ('body', 'scalp', 'ears') or nm.startswith('joint') or nm.startswith('helper'):
            continue
        col = acc[:, j]
        if col.max() > 0.03:
            out[nm] = col
    tot = sum(out.values())
    if not np.isscalar(tot):
        tot = np.maximum(tot, 1e-6)
        out = {nm: c / tot for nm, c in out.items()}
    return out


def _laid_hood(B, h, rig, coll, name, color, zip_front=False):
    """A hood lying down: a soft fabric bag on the upper back plus a thick rim around the
    neck that dips into a V at the front, like a real hoodie when the hood is down."""
    co = B.co
    neck = B.J['neck']
    nkm = (B.w('neck_01') > 0.5) & B.isbody
    nk = co[nkm]
    cx0, cy = (nk[:, 0].mean(), nk[:, 1].mean()) if len(nk) else (0.0, neck[1])
    rn = np.mean(np.linalg.norm(nk[:, :2] - np.array([cx0, cy]), axis=1)) if len(nk) else 0.055
    band = B.isbody & (np.abs(co[:, 2] - (neck[2] - 0.12)) < 0.03) & (np.abs(co[:, 0]) < 0.06)
    yb = co[band, 1].max() if band.any() else cy + 0.1
    cz = neck[2] - 0.035
    R = rn + 0.042

    def fn(P):
        x, y, z = P[:, 0] - cx0, P[:, 1], P[:, 2]
        # bag on the back, slightly flattened against the shoulder blades
        bag = sd_ell(P, np.array([cx0, yb + 0.022, neck[2] - 0.115]), [0.115, 0.042, 0.105])
        bag = bag + 0.004 * np.sin(x * 70) * np.sin(z * 55)          # soft folds
        # rim: a ring around the neck, front dipping into a V
        a = np.arctan2(x, -(y - cy))                      # 0 = front
        back = 0.5 - 0.5 * np.cos(a)
        zt = cz + 0.02 * back - 0.05 * (1 - back) ** 3
        rr = R + 0.012 * back
        rho = np.hypot(x, (y - cy))
        rt = 0.021 + 0.008 * back
        rim = np.hypot(rho - rr, (z - zt) * 1.25) - rt
        if zip_front:
            rim = np.maximum(rim, 0.012 - np.abs(x))      # opening at the zip
        d = s_min(bag, rim, 0.025)
        # keep it off the inside of the neck
        d = s_max(d, (rn + 0.006) - rho, 0.004)
        return d

    lo = np.array([cx0 - 0.16, cy - R - 0.05, cz - 0.11])
    hi = np.array([cx0 + 0.16, yb + 0.09, neck[2] + 0.05])
    V, Q, N = sdf_mesh(fn, lo, hi, 0.0032)
    if len(V) == 0:
        return None
    HAIR_OBSTACLES.append(fn)
    col = np.tile(color, (len(V), 1)) * (0.9 + 0.08 * np.array([noise.noise(Vector(p * 60)) for p in V]))[:, None]
    # inner lining of the rim reads a bit darker
    inner = (np.hypot(V[:, 0] - cx0, V[:, 1] - cy) < R) & (V[:, 2] > cz - 0.02)
    col[inner] *= 0.75
    me = bpy.data.meshes.new(name + "_Hood")
    me.from_pydata([tuple(v) for v in V], [], Q.tolist())
    _set_colors(me, np.concatenate([np.clip(col, 0, 1), np.ones((len(V), 1))], 1))
    me.polygons.foreach_set('use_smooth', np.ones(len(Q), bool))
    me.update()
    return mesh_object(me, h, rig, coll, 'fleece', body_skin(B, V))


def _crew_collar(B, h, rig, coll, name, ob, color, rad=0.0055):
    """Rib-knit crew collar sewn along the neckline loop of a tee."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    best = None
    for L in _boundary_loops(bm):
        vs = {v for e in L for v in e.verts}
        c = sum((v.co for v in vs), Vector()) / len(vs)
        if abs(c.x) < 0.05 and (best is None or c.z > best[0]):
            best = (c.z, L)
    if best is None:
        bm.free()
        return None
    L = best[1]
    adj = {}
    for e in L:
        a_, b_ = e.verts
        adj.setdefault(a_, []).append(b_)
        adj.setdefault(b_, []).append(a_)
    start = next(iter(adj))
    order, prev, cur = [start], None, start
    while True:
        nxt = [v for v in adj[cur] if v is not prev]
        if not nxt or nxt[0] is start:
            break
        prev, cur = cur, nxt[0]
        order.append(cur)
        if len(order) > 2000:
            break
    pts = np.array([tuple(v.co) for v in order] + [tuple(order[0].co)])
    bm.free()
    # resample and smooth so the collar is a clean ring
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    t = np.concatenate([[0], np.cumsum(seg)])
    tt = np.linspace(0, t[-1], 64)
    P = np.stack([np.interp(tt, t, pts[:, i]) for i in range(3)], 1)
    for _ in range(4):
        P[1:-1] = P[1:-1] * 0.5 + (P[:-2] + P[2:]) * 0.25
        P[0] = P[-1] = (P[1] + P[-2]) * 0.5
    me = tube_mesh([P], [np.full(len(P), rad)], [rgba(color * 0.93, len(P))], name + "_Collar", sides=6, flat=0.6)
    Vc = np.array([tuple(v.co) for v in me.vertices])
    return mesh_object(me, h, rig, coll, 'knit', body_skin(B, Vc))


def _hood_or_collar(B, h, rig, coll, name, style, color, P, keep):
    neck = B.J['neck']
    nk = B.co[(B.w('neck_01') > 0.5) & B.isbody]
    rn = np.mean(np.linalg.norm(nk[:, :2] - nk[:, :2].mean(0), axis=1)) if len(nk) else 0.055
    cz = neck[2] - 0.035
    cy = nk[:, 1].mean() if len(nk) else neck[1]
    pts, rad, cols = [], [], []
    n = 40
    for i in range(n + 1):
        a = 2 * math.pi * i / n
        back = 0.5 - 0.5 * math.cos(a)  # 0 front, 1 back (a=pi)
        if style == 'PUFFER':
            rr = rn + 0.035
            pts.append((math.sin(a) * rr, cy - math.cos(a) * rr * 1.05, cz + 0.03 + 0.01 * back))
            rad.append(0.026)
        else:
            rr = rn + 0.03 + 0.045 * back ** 1.5
            pts.append((math.sin(a) * rr, cy - math.cos(a) * rr + 0.02 * back, cz + 0.01 * back - 0.012 * (1 - back)))
            rad.append(0.016 + 0.05 * back ** 2)
        cols.append((*(color * (0.85 + 0.1 * back)), 1))
    me = tube_mesh([np.array(pts)], [np.array(rad)], [np.array(cols)], name + "_Hood", sides=10, flat=0.55)
    return mesh_object(me, h, rig, coll, 'nylon' if style == 'PUFFER' else 'fleece', {'spine_03': 0.6, 'neck_01': 0.4})


def _project_front(B, P, keep, x, z, out=0.006):
    """Find the garment surface in front (min y) at (x,z) by nearest kept vertex column."""
    cand = keep & (np.abs(P[:, 0] - x) < 0.02) & (np.abs(P[:, 2] - z) < 0.02)
    if not cand.any():
        return None
    y = P[cand, 1].min()
    return np.array([x, y - out, z])


def _pocket(B, h, rig, coll, name, P, keep, color):
    pel = B.J['pelvis']
    pts, rad = [], []
    for zz in np.linspace(pel[2] + 0.02, pel[2] + 0.17, 7):
        row = []
        for xx in np.linspace(-0.11, 0.11, 9):
            q = _project_front(B, P, keep, xx, zz, 0.004)
            row.append(q)
        pts.append(row)
    # build a simple grid patch
    V, F = [], []
    rows = len(pts)
    cols_n = len(pts[0])
    ok = all(q is not None for r in pts for q in r)
    if not ok:
        return None
    for r in pts:
        for q in r:
            V.append(tuple(q))
    for i in range(rows - 1):
        for j in range(cols_n - 1):
            a = i * cols_n + j
            F.append((a, a + 1, a + cols_n + 1, a + cols_n))
    me = bpy.data.meshes.new(name + "_Pocket")
    me.from_pydata(V, [], F)
    _set_colors(me, rgba(color, len(V)))
    me.update()
    ob = mesh_object(me, h, rig, coll, 'fleece', {'spine_01': 0.5, 'pelvis': 0.5})
    s = ob.modifiers.new("Thickness", 'SOLIDIFY')
    s.thickness = 0.004
    return ob


def _drawstrings(B, h, rig, coll, name, P, keep, color):
    neck = B.J['neck']
    paths, radii, cols = [], [], []
    for xs in (-0.035, 0.035):
        line = []
        for t in np.linspace(0, 1, 10):
            z = neck[2] - 0.05 - 0.17 * t
            q = _project_front(B, P, keep, xs * (1 + 0.2 * t), z, 0.006)
            if q is not None:
                line.append(q)
        if len(line) > 2:
            paths.append(np.array(line))
            radii.append(np.full(len(line), 0.0028))
            cols.append(rgba(color, len(line)))
    if not paths:
        return None
    me = tube_mesh(paths, radii, cols, name + "_Strings", sides=5)
    return mesh_object(me, h, rig, coll, 'cotton', {'spine_03': 1.0})


# --------------------------------------------------------------------------------------
# BOTTOMS
# --------------------------------------------------------------------------------------

def make_bottom(B, h, rig, coll, name, style, color, accent, pattern):
    R = _regions(B)
    co = B.co
    pel = B.J['pelvis']
    knee = (B.J['l-knee'] + B.J['r-knee']) / 2
    ank = (B.J['l-ankle'] + B.J['r-ankle']) / 2
    waist = pel[2] + 0.07
    low = {'BAGGY_JEANS': ank[2] + 0.012, 'JOGGERS': ank[2] + 0.02, 'CARGO': ank[2] + 0.012,
           'JORTS': knee[2] - 0.07, 'SHORTS': knee[2] + 0.02, 'TRACK': ank[2] + 0.012}[style]
    keep = B.isbody & (co[:, 2] < waist) & (co[:, 2] > low) & (R['hand'] < 0.3) & (R['upper'] + R['lower'] < 0.4)
    leg = R['thigh'] + R['calf']
    tlen = np.clip((pel[2] - co[:, 2]) / (pel[2] - ank[2]), 0, 1)  # 0 at hips, 1 at ankle
    if style in ('BAGGY_JEANS', 'CARGO', 'TRACK'):
        off = 0.014 + 0.03 * tlen + 0.012 * (style == 'BAGGY_JEANS')
    elif style == 'JOGGERS':
        off = 0.016 + 0.02 * tlen
        cuff = smoothstep(low + 0.06, low + 0.015, co[:, 2])
        off = off * (1 - 0.8 * cuff)
    else:
        off = 0.02 + 0.03 * tlen
    # inner thighs must not collide
    inner = (np.sign(co[:, 0]) * B.nrm[:, 0] < -0.4) & (leg > 0.5)
    off = np.where(inner, np.minimum(off, 0.01), off)
    # waistband snug
    off = off * (1 - 0.6 * smoothstep(waist - 0.05, waist, co[:, 2]))
    smooth_body = B.smooth(co, 14)
    Ns = B.normals(smooth_body)
    P = smooth_body + Ns * off[:, None]
    # stacking at the ankle
    if style in ('BAGGY_JEANS', 'CARGO', 'TRACK'):
        stack = smoothstep(low + 0.16, low + 0.02, co[:, 2])
        P += Ns * (0.009 * stack * np.sin(co[:, 2] * 2 * math.pi / 0.032))[:, None]
    if style in ('BAGGY_JEANS', 'CARGO', 'TRACK'):
        # wide straight legs: push each leg out to a near-cylinder around the leg axis,
        # so the fabric hangs from the thigh instead of hugging the calf
        Rtop, Rhem = {'BAGGY_JEANS': (0.092, 0.095), 'CARGO': (0.09, 0.088), 'TRACK': (0.082, 0.078)}[style]
        for side, sx in (('l', 1.0), ('r', -1.0)):
            kn, an = B.J[side + '-knee'], B.J[side + '-ankle']
            hp = np.array([sx * 0.10, 0.0, pel[2]])
            sel = (np.sign(co[:, 0]) == sx) & (co[:, 2] < pel[2] - 0.02)
            z = P[sel, 2]
            t1 = np.clip((hp[2] - z) / (hp[2] - kn[2]), 0, 1)[:, None]
            t2 = np.clip((kn[2] - z) / (kn[2] - an[2]), 0, 1.3)[:, None]
            ax = np.where((z > kn[2])[:, None], hp + (kn - hp) * t1, kn + (an - kn) * t2)
            r = P[sel, :2] - ax[:, :2]
            rl = np.linalg.norm(r, axis=1) + 1e-6
            rh = r / rl[:, None]
            tt = np.clip((pel[2] - z) / (pel[2] - an[2]), 0, 1)
            R = Rtop + (Rhem - Rtop) * tt
            inner = np.clip(-rh[:, 0] * sx, 0, 1)
            R = R * (1 - 0.42 * inner)
            blend = smoothstep(pel[2] - 0.02, pel[2] - 0.12, z)
            newl = rl + np.maximum(R - rl, 0) * blend
            P[sel, :2] = ax[:, :2] + rh * newl[:, None]
    P = B.smooth(P, 5)
    # long legs hang straight down over the shoe instead of following the foot
    if style in ('BAGGY_JEANS', 'CARGO', 'TRACK'):
        hang = smoothstep(low + 0.07, low, co[:, 2])
        P[:, 2] -= 0.03 * hang
        P[:, 1] = P[:, 1] * (1 - 0.5 * hang) + smooth_body[:, 1] * 0.5 * hang
    fold = np.array([noise.noise(Vector(p * 6.0 + 5)) for p in co])
    P += Ns * (0.004 * fold)[:, None]
    cols = pattern_colors(co, color, pattern, accent)
    if style in ('BAGGY_JEANS', 'JORTS'):
        # fades on the thighs/knees, darker creases
        fade = np.clip(-B.nrm[:, 1], 0, 1) * smoothstep(low, pel[2], co[:, 2])
        cols = cols * (1 + 0.35 * fade)[:, None]
        seam = np.abs(np.abs(co[:, 0]) - np.abs(B.J['l-knee'][0]) - 0.065) < 0.004
        cols[seam] *= 1.25
    if style == 'TRACK':
        stripe = (np.abs(B.nrm[:, 0]) > 0.85) & (np.abs(np.abs(B.nrm[:, 0]) - 0.93) < 0.06)
        cols[stripe] = accent
    if style == 'CARGO':
        pockets = (np.abs(co[:, 2] - (knee[2] + 0.12)) < 0.07) & (np.abs(B.nrm[:, 0]) > 0.7)
        cols[pockets] *= 0.85
    kind = 'denim' if style in ('BAGGY_JEANS', 'JORTS') else ('fleece' if style == 'JOGGERS' else 'cotton')
    ob = shell_object(B, h, rig, coll, name, P, keep, np.concatenate([cols, np.ones((len(co), 1))], 1), kind,
                      solid=0.004)
    if style in ('BAGGY_JEANS', 'CARGO', 'TRACK'):
        extend_hem(ob, 0.022, 0.012, 'legs', rings=3)   # break / stack over the sneaker
    return [ob], keep


def make_socks(B, h, rig, coll, name, color, stripe):
    co = B.co
    ank = (B.J['l-ankle'] + B.J['r-ankle']) / 2
    knee = (B.J['l-knee'] + B.J['r-knee']) / 2
    top = ank[2] + 0.4 * (knee[2] - ank[2])
    keep = B.isbody & (co[:, 2] < top) & (co[:, 2] > ank[2] - 0.03) & (B.w('calf_l', 'calf_r', 'foot_l', 'foot_r') > 0.3)
    P = co + B.nrm * 0.003
    cols = np.tile(color, (len(co), 1))
    if stripe is not None:
        sel = (np.abs(co[:, 2] - (top - 0.025)) < 0.008) | (np.abs(co[:, 2] - (top - 0.045)) < 0.006)
        cols[sel] = stripe
    return [shell_object(B, h, rig, coll, name, P, keep, np.concatenate([cols, np.ones((len(co), 1))], 1),
                         'knit', solid=0.0)], keep


# --------------------------------------------------------------------------------------
# HEADWEAR
# --------------------------------------------------------------------------------------

def _head_frame(B):
    hc = B.head_c.copy()
    return hc, B.eye, B.crown_z, B.chin_z, B.head_h


def make_headwear(B, h, rig, coll, name, style, color, accent):
    co = B.co
    hc, eye, crown, chin, H = _head_frame(B)
    head = (B.w('head') > 0.6) & B.isbody
    rel = co - hc
    front = rel[:, 1] < (eye[1] - hc[1]) * 0.5
    objs = []
    if style == 'BEANIE':
        edge = eye[2] + 0.06 * H / 0.24
        edge_line = edge - 0.03 * smoothstep(-0.02, 0.06, rel[:, 1])
        keep = head & (co[:, 2] > edge_line - 0.01) & ~((B.w('ears') > 0.3))
        smooth_head = B.smooth(co, 8)
        Ns = B.normals(smooth_head)
        cuff = smoothstep(edge_line + 0.05, edge_line + 0.035, co[:, 2])
        rib = 0.5 + 0.5 * np.sin(np.arctan2(rel[:, 0], rel[:, 1]) * 70)
        off = 0.012 + 0.012 * cuff + 0.0015 * rib + 0.012 * smoothstep(crown - 0.06, crown, co[:, 2])
        P = smooth_head + Ns * off[:, None]
        cols = np.tile(color, (len(co), 1)) * (0.85 + 0.15 * rib)[:, None]
        objs.append(shell_object(B, h, rig, coll, name, P, keep, np.concatenate([cols, np.ones((len(co), 1))], 1),
                                 'knit', solid=0.003))
        cover_z = edge_line
    elif style in ('CAP', 'CAP_BACK'):
        edge_line = eye[2] + 0.055 * H / 0.24 - 0.025 * smoothstep(-0.02, 0.08, rel[:, 1])
        keep = head & (co[:, 2] > edge_line) & (B.w('ears') < 0.3)
        smooth_head = B.smooth(co, 8)
        Ns = B.normals(smooth_head)
        th = np.arctan2(rel[:, 0], -rel[:, 1])
        seam = np.abs(np.sin(th * 3)) < 0.05
        off = 0.01 + 0.004 * smoothstep(crown - 0.05, crown, co[:, 2])
        P = smooth_head + Ns * off[:, None]
        cols = np.tile(color, (len(co), 1))
        cols[seam] *= 0.8
        objs.append(shell_object(B, h, rig, coll, name, P, keep, np.concatenate([cols, np.ones((len(co), 1))], 1),
                                 'cotton', solid=0.003))
        # brim
        sgn = 1.0 if style == 'CAP_BACK' else -1.0
        brim_z = edge_line.min() if np.ndim(edge_line) else edge_line
        bz = eye[2] + 0.055 * H / 0.24 + (0.0 if sgn < 0 else -0.03)
        fy = hc[1] + sgn * (np.abs(rel[keep, 1]).max() if keep.any() else 0.1)
        V, F = [], []
        nr, nc = 6, 13
        for i in range(nr):
            t = i / (nr - 1)
            for j in range(nc):
                u = (j / (nc - 1)) * 2 - 1
                w = 0.085 * math.sqrt(max(0.0, 1 - u * u * 0.85))
                x = u * 0.085
                y = fy + sgn * (w * t * 0.95 - 0.01)
                z = bz - 0.012 * t - 0.01 * (u * u) * t
                V.append((x, y, z))
        for i in range(nr - 1):
            for j in range(nc - 1):
                a = i * nc + j
                F.append((a, a + 1, a + nc + 1, a + nc))
        me = bpy.data.meshes.new(name + "_Brim")
        me.from_pydata(V, [], F)
        _set_colors(me, rgba(accent, len(V)))
        me.update()
        b = mesh_object(me, h, rig, coll, 'cotton', {'head': 1.0})
        s = b.modifiers.new("Thickness", 'SOLIDIFY')
        s.thickness = 0.006
        objs.append(b)
        # button
        sv = [(0, 0, 0)]
        cover_z = edge_line
    elif style == 'DURAG':
        edge_line = eye[2] + 0.05 * H / 0.24 - 0.06 * smoothstep(-0.03, 0.07, rel[:, 1])
        keep = head & (co[:, 2] > edge_line) & (B.w('ears') < 0.3)
        smooth_head = B.smooth(co, 6)
        Ns = B.normals(smooth_head)
        # satin is pulled tight over the crown and gathers into soft wrinkles toward the tie at
        # the back; a centre seam runs front to back
        back = smoothstep(-0.02, 0.09, rel[:, 1])
        wob = vnoise(co, 0.03, 5)
        wr = np.sin(np.arctan2(rel[:, 2], rel[:, 0]) * 14 + wob * 3.0) * back
        tight = 1 - back
        off = 0.0095 + 0.0022 * wr + 0.001 * wob * tight + 0.003 * back
        P = smooth_head + Ns * off[:, None]
        P = B.smooth(P, 1)
        seam = np.exp(-(rel[:, 0] / 0.0025) ** 2) * (rel[:, 2] > -0.02)
        cols = np.tile(color, (len(co), 1)) * (1 - 0.35 * seam)[:, None] * (0.95 + 0.05 * wob)[:, None]
        # wrinkle valleys a touch darker
        cols *= (1 - 0.12 * np.clip(-wr, 0, 1))[:, None]
        objs.append(shell_object(B, h, rig, coll, name, P, keep, np.concatenate([cols, np.ones((len(co), 1))], 1),
                                 'satin', solid=0.002))
        # tails hanging down the back
        nape = hc + np.array([0, 0, 0])
        back_y = (co[head, 1].max())
        # the knot where the ties wrap: a twisted lump just above the nape
        kz = edge_line[head].min() if np.ndim(edge_line) else edge_line
        kc = np.array([0.0, back_y + 0.012, chin + 0.035])
        kpath = [kc + np.array([0.018 * math.cos(a), 0.006 * math.sin(a), 0.008 * math.sin(a)]) for a in np.linspace(0, 2 * math.pi, 16)]
        km = tube_mesh([np.array(kpath)], [np.full(16, 0.009)], [rgba(color * 0.85, 16)], name + "_Knot", sides=8, flat=0.7)
        objs.append(mesh_object(km, h, rig, coll, 'satin', {'head': 1.0}))
        paths, radii, cl = [], [], []
        for sx in (-0.022, 0.022):
            pts = []
            for t in np.linspace(0, 1, 14):
                z = chin - 0.26 * t
                band = B.isbody & (np.abs(co[:, 2] - z) < 0.015) & (np.abs(co[:, 0]) < 0.05)
                by = co[band, 1].max() if band.any() else back_y
                # lie on the back of the shirt (tee offset + fabric), not cut through it
                y = max(back_y + 0.012, by + 0.045 * smoothstep(0.0, 0.25, t) + 0.012)
                pts.append((sx * (1 + 0.6 * t), y, z))
            paths.append(np.array(pts))
            radii.append(np.linspace(0.016, 0.026, 14))
            cl.append(rgba(color * 0.9, 14))
        me = tube_mesh(paths, radii, cl, name + "_Tails", sides=8, flat=0.18)
        objs.append(mesh_object(me, h, rig, coll, 'satin', {'neck_01': 0.6, 'spine_03': 0.4}))
        cover_z = edge_line
    else:
        return [], None
    return objs, cover_z


# --------------------------------------------------------------------------------------
# HAIR
# --------------------------------------------------------------------------------------

def _scalp(B, hairline_front, hairline_side, hairline_back):
    co = B.co
    hc, eye, crown, chin, H = _head_frame(B)
    rel = co - hc
    head = (B.w('head') > 0.6) & B.isbody & (B.w('ears') < 0.2)
    ty = np.clip((rel[:, 1] + 0.09) / 0.18, 0, 1)
    side = smoothstep(0.035, 0.065, np.abs(rel[:, 0]))
    top_line = eye[2] + H * np.interp(ty, [0, 0.35, 0.75, 1.0], [hairline_front, hairline_front + 0.01,
                                                                 hairline_back + 0.08, hairline_back])
    side_line = eye[2] + H * np.interp(ty, [0, 0.25, 0.42, 0.55, 0.75, 1.0],
                                       [hairline_front, hairline_side, hairline_side, 0.1, hairline_back + 0.04,
                                        hairline_back])
    zline = top_line * (1 - side) + side_line * side
    return head, zline, rel


def make_hair(B, h, rig, coll, name, style, color, fade, cover_z=None, seed=1, coil_count=900):
    co = B.co
    hc, eye, crown, chin, H = _head_frame(B)
    rng = np.random.default_rng(seed)
    objs = []
    head, zline, rel = _scalp(B, 0.27, 0.12, -0.25)
    above = co[:, 2] - zline
    keep = head & (above > -0.002)
    if cover_z is not None:
        keep &= co[:, 2] < (cover_z + 0.04 if np.ndim(cover_z) == 0 else cover_z + 0.04)
    hgt = (co[:, 2] - eye[2]) / H  # 0 at eyes, ~0.5 at crown
    # fade: density from 0 (skin) low on the sides to 1 up top
    side_amt = smoothstep(0.03, 0.07, np.abs(rel[:, 0])) + smoothstep(0.02, 0.08, rel[:, 1])
    side_amt = np.clip(side_amt, 0, 1)
    fade_lo, fade_hi = FADES[fade]
    dens = np.where(side_amt > 0.3, smoothstep(fade_lo, fade_hi, hgt), 1.0)
    dens = np.clip(dens, 0, 1)
    top = smoothstep(0.16, 0.36, hgt) * (1 - 0.6 * side_amt) + smoothstep(0.3, 0.44, hgt) * side_amt * 0.6
    smooth_head = B.smooth(co, 6)
    Ns = B.normals(smooth_head)
    base_off = 0.0015 + 0.003 * dens
    cols = np.tile(color, (len(co), 1))
    alpha = np.clip(0.15 + 0.85 * dens, 0, 1) * smoothstep(-0.002, 0.012, above)
    edge_taper = 0.3 + 0.7 * smoothstep(-0.002, 0.02, above)
    vol = 0.0
    if style == 'BUZZ':
        off = base_off
    elif style == 'WAVES':
        cp = hc + np.array([0, 0.01, H * 0.5])
        r = np.linalg.norm((co - cp)[:, :2], axis=1) + 0.3 * np.maximum(0, cp[2] - co[:, 2])
        wv = np.sin(r * 2 * math.pi / 0.011 + np.arctan2(rel[:, 0], rel[:, 1]) * 2)
        off = base_off + 0.0012 * wv * dens + 0.002
        cols *= (0.75 + 0.35 * (0.5 + 0.5 * wv))[:, None]
    elif style in ('CURLY_TOP', 'TWISTS', 'LOCS', 'FLAT_TOP'):
        vol = {'CURLY_TOP': 0.045 * _CURL_K, 'TWISTS': 0.012, 'LOCS': 0.01, 'FLAT_TOP': 0.06}[style]
        # curly top: the coils carry the volume; the shell stays low so there's no solid 'wall' at the fade
        off = base_off + vol * top * (0.45 if style == 'CURLY_TOP' else 1.0)
        if style in ('CURLY_TOP', 'FLAT_TOP'):
            curl = vnoise(co, 0.012, seed) + 0.5 * vnoise(co, 0.005, seed + 3)
            off += 0.008 * curl * top
            cols *= (0.75 + 0.3 * (0.5 + 0.5 * curl))[:, None]
        if style == 'FLAT_TOP':
            Ptmp = smooth_head + Ns * off[:, None]
            capz = crown + 0.035
            over = np.maximum(0, Ptmp[:, 2] - capz)
            off = off - over / np.maximum(Ns[:, 2], 0.3)
    elif style == 'CORNROWS':
        xr = rel[:, 0]
        row = np.sin(xr * 2 * math.pi / 0.024)
        braid = np.sin(rel[:, 1] * 2 * math.pi / 0.008 + np.sign(row) * 1.5)
        ridge = np.clip(row, 0, 1) ** 0.6
        off = 0.0012 + 0.0008 * ridge
        cols *= (0.45 + 0.7 * ridge * (0.8 + 0.2 * braid))[:, None]
        alpha[:] = smoothstep(-0.002, 0.008, above) * (0.25 + 0.75 * smoothstep(-0.6, -0.1, row))
        dens[:] = 1.0
    elif style in ('BRAIDS', 'BUN', 'PUFF'):
        off = 0.003 + 0.002 * dens
        alpha[:] = smoothstep(-0.002, 0.01, above)
        part = np.abs(np.sin(rel[:, 0] * 2 * math.pi / 0.03)) < 0.12
        if style == 'BRAIDS':
            cols[part] *= 0.6
    else:
        off = base_off
    if style in ('TAPER', 'WAVES', 'BUZZ', 'CURLY_TOP', 'FLAT_TOP', 'TWISTS'):
        off = off * edge_taper        # hair thins out to the hairline instead of ending in a lip
    P = smooth_head + Ns * off[:, None]
    rgba_ = np.concatenate([cols, alpha[:, None]], 1)
    kind = 'hair'
    objs.append(shell_object(B, h, rig, coll, name, P, keep, rgba_, kind, solid=0.0))

    # strand geometry on top
    hb = {'head': 1.0}
    # coils give curly volumes a real, fuzzy silhouette
    if style in ('CURLY_TOP', 'FLAT_TOP') and coil_count > 0:
        cand = np.nonzero(keep & (top > 0.12))[0]
        if len(cand):
            n_c = coil_count * 3
            pick = rng.choice(cand, size=n_c, replace=True)
            # spread roots across faces: jitter toward random neighbours
            nb = rng.choice(cand, size=n_c, replace=True)
            t = rng.random((n_c, 1)) * 0.5
            pts = P[pick] * (1 - t) + P[nb] * t
            pts = pts - Ns[pick] * 0.004
            if style == 'CURLY_TOP':
                # stack coils through the volume the shell no longer fills
                lift = rng.random(n_c) * (0.045 * _CURL_K * 0.55) * top[pick]
                pts = pts + Ns[pick] * lift[:, None]
            nrm = Ns[pick] + rng.normal(0, 0.35, (n_c, 3))
            pa, ra, ca = coil_mesh(pts, nrm, color, seed=seed, length=(0.012 * _CURL_K, 0.022 * _CURL_K),
                                   radius=0.0035 * (0.5 + 0.5 * _CURL_K),
                                   wire=0.0013, droop=0.08, turns=(1.8, 2.8))
            me = tube_mesh(pa, ra, ca, name + "_Coils", sides=4)
            objs.append(mesh_object(me, h, rig, coll, 'coil', {'head': 1.0}))
    if style == 'CORNROWS':
        # real plaits running front-to-back along the scalp
        hc_ = B.head_c
        xs = np.arange(-0.07, 0.0701, 0.021)
        paths, rads, cl = [], [], []
        upper = P[:, 2] > B.eye[2] + 0.1 * B.head_h
        nape = (rel[:, 1] > 0.03) & (np.abs(rel[:, 0]) < 0.06) & (P[:, 2] > B.chin_z + 0.02)
        sel = keep & (dens > 0.5) & (upper | nape)
        for x0 in xs:
            band = sel & (np.abs(rel[:, 0] - x0) < 0.006)
            if band.sum() < 8:
                continue
            pts = P[band] + Ns[band] * 0.004
            # bin along the front-to-back arc and take medians -> clean, straight-back row
            ang = np.arctan2(pts[:, 2] - hc_[2], (pts[:, 1] - hc_[1]))
            ang = np.where(ang < -1.2, ang + 2 * np.pi, ang)
            bins = np.linspace(ang.min(), ang.max(), 36)
            idx = np.digitize(ang, bins)
            line = []
            for bi in range(len(bins), 0, -1):
                m = idx == bi
                if m.sum() >= 1:
                    q = np.median(pts[m], 0)
                    q[0] = x0 * 0.85 + q[0] * 0.15
                    line.append(q)
            if len(line) < 8:
                continue
            line = np.array(line)
            seg = np.r_[0, np.cumsum(np.linalg.norm(np.diff(line, axis=0), axis=1))]
            if seg[-1] < 0.05:
                continue
            ss = np.linspace(0, seg[-1], max(16, int(seg[-1] / 0.004)))
            line = np.stack([np.interp(ss, seg, line[:, k]) for k in range(3)], 1)
            for _ in range(4):
                line[1:-1] = (line[:-2] + line[1:-1] * 2 + line[2:]) / 4
            r = np.full(len(line), 0.0058)
            r[:5] = np.linspace(0.0028, 0.0058, 5)
            r[-4:] = np.linspace(0.0058, 0.0035, 4)
            for sp, sr in twist_paths(line, r, 'BRAID', phase=x0 * 300):
                paths.append(sp)
                rads.append(sr)
                cl.append(rgba(color * rng.uniform(0.85, 1.1), len(sp)))
        if paths:
            me = tube_mesh(paths, rads, cl, name + "_Plaits", sides=6)
            objs.append(mesh_object(me, h, rig, coll, 'coil', {'head': 1.0}))
    if style in ('TWISTS', 'LOCS', 'BRAIDS'):
        n_roots = {'TWISTS': 150, 'LOCS': 90, 'BRAIDS': 160}[style]
        cand = np.nonzero(keep & (dens > 0.9) & (top > 0.25 if style == 'TWISTS' else keep))[0]
        if style != 'TWISTS':
            cand = np.nonzero(keep & (hgt > 0.12) & (rel[:, 1] > -0.035))[0]
        if len(cand):
            roots = rng.choice(cand, size=min(n_roots, len(cand)), replace=False)
            length = {'TWISTS': 0.075, 'LOCS': 0.2, 'BRAIDS': 0.36}[style]
            rad0 = {'TWISTS': 0.0055, 'LOCS': 0.0065, 'BRAIDS': 0.0035}[style]
            paths, radii, cl = [], [], []
            axes = np.array([0.105, 0.115, 0.13]) * H / 0.24
            cen = hc + np.array([0, 0.005, 0.01])
            for ri in roots:
                p = P[ri].copy()
                d = Ns[ri].copy()
                if style == 'TWISTS':
                    d = d + np.array([0, 0.15, 0.25])
                else:
                    # sweep away from the face
                    if rel[ri, 1] < 0.07:
                        sx = np.sign(rel[ri, 0]) if abs(rel[ri, 0]) > 0.004 else (1 if ri % 2 else -1)
                        d = d + np.array([sx * 1.4, 2.2, 0.5])
                d /= np.linalg.norm(d)
                L = length * rng.uniform(0.8, 1.15)
                n = 16 if style == 'TWISTS' else 40
                seg = L / n
                pts = [p.copy()]
                for k in range(n):
                    g = np.array([0, 0.0, -1.0]) * (0.22 if style == 'TWISTS' else 0.55)
                    d = d + g
                    d /= np.linalg.norm(d)
                    p = p + d * seg
                    q = (p - cen) / axes
                    rr = np.linalg.norm(q)
                    if rr < 1.06 and p[2] > chin - 0.02:
                        p = cen + q / rr * 1.06 * axes
                    for ob_fn in HAIR_OBSTACLES:
                        dd = ob_fn(p[None])[0]
                        clear = 0.006 + rad0
                        if dd < clear:
                            e = 0.002
                            gr = np.array([ob_fn((p + np.eye(3)[j] * e)[None])[0] - dd for j in range(3)]) / e
                            gn = np.linalg.norm(gr)
                            if gn > 1e-6:
                                p = p + gr / gn * (clear - dd)
                                d = d + gr / gn * 0.5
                                d /= np.linalg.norm(d)
                    pts.append(p.copy())
                pts = np.array(pts)
                t = np.linspace(0, 1, len(pts))
                rads = rad0 * (1.0 - 0.25 * t) * rng.uniform(0.85, 1.15)
                paths.append(pts)
                radii.append(rads)
                cl.append(rgba(color * rng.uniform(0.8, 1.15), len(pts)))
            if style == 'LOCS':
                # irregular, slightly lumpy, matte locs
                radii = [r * (1 + 0.18 * vnoise(pp, 0.02, seed + i)) for i, (pp, r) in enumerate(zip(paths, radii))]
                me = tube_mesh(paths, radii, cl, name + "_Strands", sides=7, twist=0.2)
                kind = 'locs'
            else:
                sub_p, sub_r, sub_c = [], [], []
                for i, (pp, r, cc) in enumerate(zip(paths, radii, cl)):
                    for sp, sr in twist_paths(pp, r * 1.15, 'TWIST' if style == 'TWISTS' else 'BRAID', phase=i * 1.7):
                        sub_p.append(sp)
                        sub_r.append(sr)
                        sub_c.append(cc)
                me = tube_mesh(sub_p, sub_r, sub_c, name + "_Strands", sides=6)
                kind = 'coil'
            objs.append(mesh_object(me, h, rig, coll, kind, {'head': 1.0}))
    if style in ('BUN', 'PUFF'):
        big = style == 'PUFF'
        c = hc + np.array([0, 0.03 if not big else 0.02, H * (0.52 if not big else 0.5)])
        me = bpy.data.meshes.new(name + "_Bun")
        r = 0.045 if not big else 0.062
        V, F = [], []
        seg, rings = 40, 24
        for i in range(rings + 1):
            ph = math.pi * i / rings
            for j in range(seg):
                th = 2 * math.pi * j / seg
                dv = Vector((math.sin(ph) * math.cos(th), math.sin(ph) * math.sin(th), math.cos(ph)))
                bump = 1 + (0.05 if big else 0.02) * noise.noise(dv * 6)
                V.append(tuple(c + np.array(dv) * r * bump))
        for i in range(rings):
            for j in range(seg):
                a = i * seg + j
                b2 = i * seg + (j + 1) % seg
                F.append((a, b2, b2 + seg, a + seg))
        me.from_pydata(V, [], F)
        _set_colors(me, rgba(color, len(V)))
        me.update()
        bun = mesh_object(me, h, rig, coll, 'hairsolid', hb)
        if big and coil_count > 0:
            vv = np.array([v[:] for v in V])
            n_c = coil_count * 3
            dirs = rng.normal(0, 1, (n_c, 3))
            dirs /= np.linalg.norm(dirs, axis=1)[:, None]
            dirs = dirs[dirs[:, 2] > -0.55]
            pts = c + dirs * r * 0.95
            pa, ra, ca = coil_mesh(pts, dirs + rng.normal(0, 0.3, dirs.shape), color, seed=seed + 4,
                                   length=(0.014, 0.024), radius=0.0038, wire=0.0013, droop=0.0, turns=(1.8, 2.8))
            cm = tube_mesh(pa, ra, ca, name + "_PuffCoils", sides=4)
            objs.append(mesh_object(cm, h, rig, coll, 'coil', hb))
        try:
            me.polygons.foreach_set('use_smooth', np.ones(len(me.polygons), bool))
        except Exception:
            pass
        sub = bun.modifiers.new("Smooth", 'SUBSURF')
        sub.levels = 1
        bun.modifiers.move(len(bun.modifiers) - 1, 0) if hasattr(bun.modifiers, 'move') else None
        objs.append(bun)
    return objs


# --------------------------------------------------------------------------------------
# ACCESSORIES
# --------------------------------------------------------------------------------------

def _outer_bvh(objs):
    dg = bpy.context.evaluated_depsgraph_get()
    verts, polys = [], []
    for ob in objs:
        if ob is None or ob.type != 'MESH':
            continue
        ev = ob.evaluated_get(dg)
        me = ev.to_mesh()
        M = ob.matrix_world
        base = len(verts)
        verts += [M @ v.co for v in me.vertices]
        polys += [[base + i for i in p.vertices] for p in me.polygons]
        ev.to_mesh_clear()
    if not verts:
        return None
    return BVHTree.FromPolygons(verts, polys)


def _project_y(bvh, x, z, M, out):
    o = M @ Vector((x, -1.0, z))
    hit = bvh.ray_cast(o, (M.to_3x3() @ Vector((0, 1, 0))).normalized())
    if hit[0] is None:
        return None
    p = M.inverted() @ hit[0]
    return np.array([p.x, p.y - out, p.z])


def make_chain(B, h, rig, coll, name, outer_objs, color):
    bvh = _outer_bvh([h] + outer_objs[:1])
    if bvh is None:
        return []
    neck = B.J['neck']
    M = h.matrix_world
    pts = []
    for a in np.linspace(-1.25, 1.25, 31):
        u = a / 1.25
        x = u * 0.072
        z = neck[2] - 0.03 - 0.14 * (1 - u * u)
        q = _project_y(bvh, x, z, M, 0.006)
        if q is not None:
            pts.append(q)
    if len(pts) < 4:
        return []
    pts = np.array(pts)
    me = tube_mesh([pts], [np.full(len(pts), 0.0035)], [rgba(color, len(pts))], name, sides=6, twist=1.3,
                   bulge=0.35, bulge_freq=2.5)
    return [mesh_object(me, h, rig, coll, 'gold', {'spine_03': 1.0})]


def make_crossbody(B, h, rig, coll, name, outer_objs, color, strap_color):
    bvh = _outer_bvh([h] + outer_objs)
    if bvh is None:
        return []
    M = h.matrix_world
    sh = B.J['l-shoulder']
    pel = B.J['pelvis']
    side = 1 if sh[0] > 0 else -1
    a = np.array([sh[0] * 0.75, 0, sh[2] + 0.02])
    b = np.array([-side * 0.12, 0, pel[2] + 0.08])
    pts = []
    for t in np.linspace(0, 1, 18):
        p = a + (b - a) * t
        q = _project_y(bvh, p[0], p[2], M, 0.007)
        if q is not None:
            pts.append(q)
    objs = []
    if len(pts) > 3:
        pts = np.array(pts)
        me = tube_mesh([pts], [np.full(len(pts), 0.009)], [rgba(strap_color, len(pts))], name + "_Strap", sides=6,
                       flat=0.3)
        objs.append(mesh_object(me, h, rig, coll, 'nylon', body_skin(B, pts)))
        end = pts[-1]
        c = np.array([end[0], end[1] - 0.03, end[2]])
        hx, hy, hz = 0.1, 0.022, 0.06

        def bag_fn(P):
            q = P - c
            d = sd_rbox(P, c, [hx - 0.015, hy - 0.008, hz - 0.015], 0.02)
            # padded front: bulges out in the middle
            bul = np.clip(1 - (q[:, 0] / hx) ** 2, 0, 1) * np.clip(1 - (q[:, 2] / hz) ** 2, 0, 1)
            d = d - 0.01 * bul * (q[:, 1] < 0)
            return d

        V, Q, N = sdf_mesh(bag_fn, c - np.array([hx + 0.03, hy + 0.03, hz + 0.03]),
                           c + np.array([hx + 0.03, hy + 0.03, hz + 0.03]), 0.003)
        if len(V):
            q = V - c
            col = np.tile(color, (len(V), 1))
            zip_ = (np.abs(q[:, 2] - (hz - 0.016)) < 0.0035) & (q[:, 1] < 0)
            col[zip_] = color * 0.5 + 0.25
            pull = (np.abs(q[:, 2] - (hz - 0.02)) < 0.008) & (np.abs(q[:, 0] - hx * 0.55) < 0.006) & (q[:, 1] < 0)
            col[pull] = np.array([0.7, 0.7, 0.72])
            seam = np.abs(np.abs(q[:, 0]) - (hx - 0.012)) < 0.002
            col[seam] *= 0.75
            me = bpy.data.meshes.new(name + "_Bag")
            me.from_pydata([tuple(v) for v in V], [], Q.tolist())
            _set_colors(me, np.concatenate([np.clip(col, 0, 1), np.ones((len(V), 1))], 1))
            me.polygons.foreach_set('use_smooth', np.ones(len(Q), bool))
            me.update()
            objs.append(mesh_object(me, h, rig, coll, 'nylon', body_skin(B, V)))
    return objs


# ======================================================================================
#  DESIGNER-INSPIRED PIECES (original designs: silhouettes/construction only, no brand marks)
# ======================================================================================

# ---------------- compact SDF toolkit (numpy) for sculpted parts like sneakers --------

def sd_ell(P, c, r):
    q = P - c
    r = np.asarray(r, float)
    k0 = np.linalg.norm(q / r, axis=1)
    k1 = np.linalg.norm(q / (r * r), axis=1)
    return k0 * (k0 - 1.0) / np.maximum(k1, 1e-12)


def sd_rbox(P, c, half, rad):
    q = np.abs(P - c) - (np.asarray(half, float) - rad)
    return np.linalg.norm(np.maximum(q, 0), axis=1) + np.minimum(q.max(axis=1), 0) - rad


def s_min(a, b, k):
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0, 1)
    return b + (a - b) * h - k * h * (1 - h)


def s_max(a, b, k):
    return -s_min(-a, -b, k)


_CORN = np.array([[i, j, k] for k in (0, 1) for j in (0, 1) for i in (0, 1)])
_EDG = [(a, b) for a in range(8) for b in range(a + 1, 8) if np.abs(_CORN[a] - _CORN[b]).sum() == 1]


def sdf_mesh(fn, lo, hi, h):
    lo = np.asarray(lo, float)
    hi = np.asarray(hi, float)
    n = np.ceil((hi - lo) / h).astype(int) + 1
    ax = [lo[i] + h * np.arange(n[i]) for i in range(3)]
    G = np.stack(np.meshgrid(*ax, indexing='ij'), -1).reshape(-1, 3)
    F = fn(G).reshape(n)
    ins = F < 0
    nx, ny, nz = F.shape
    cell = np.zeros((nx - 1, ny - 1, nz - 1), np.uint8)
    for c, (i, j, k) in enumerate(_CORN):
        cell |= (ins[i:nx - 1 + i, j:ny - 1 + j, k:nz - 1 + k].astype(np.uint8) << c)
    act = (cell != 0) & (cell != 255)
    I, J, K = np.nonzero(act)
    acc = np.zeros((len(I), 3))
    cnt = np.zeros(len(I))
    fv = [F[I + a, J + b, K + c] for (a, b, c) in _CORN]
    for a, b in _EDG:
        fa, fb = fv[a], fv[b]
        m = (fa < 0) != (fb < 0)
        t = np.where(m, fa / np.where(m, fa - fb, 1), 0)
        acc[m] += (_CORN[a] + t[:, None] * (_CORN[b] - _CORN[a]))[m]
        cnt[m] += 1
    V = lo + (np.stack([I, J, K], 1) + acc / np.maximum(cnt, 1)[:, None]) * h
    vid = np.full(act.shape, -1, np.int64)
    vid[I, J, K] = np.arange(len(I))
    Q = []
    s = ins[:-1, 1:-1, 1:-1] != ins[1:, 1:-1, 1:-1]
    i, j, k = np.nonzero(s); j += 1; k += 1
    Q.append(np.stack([vid[i, j - 1, k - 1], vid[i, j, k - 1], vid[i, j, k], vid[i, j - 1, k]], 1))
    s = ins[1:-1, :-1, 1:-1] != ins[1:-1, 1:, 1:-1]
    i, j, k = np.nonzero(s); i += 1; k += 1
    Q.append(np.stack([vid[i - 1, j, k - 1], vid[i - 1, j, k], vid[i, j, k], vid[i, j, k - 1]], 1))
    s = ins[1:-1, 1:-1, :-1] != ins[1:-1, 1:-1, 1:]
    i, j, k = np.nonzero(s); i += 1; j += 1
    Q.append(np.stack([vid[i - 1, j - 1, k], vid[i, j - 1, k], vid[i, j, k], vid[i - 1, j, k]], 1))
    Q = np.concatenate(Q)
    e = h * 0.5
    for _ in range(2):
        f = fn(V)
        o = np.eye(3) * e
        g = np.stack([(fn(V + o[d]) - fn(V - o[d])) / (2 * e) for d in range(3)], 1)
        step = (f / np.maximum((g * g).sum(1), 1e-12))[:, None] * g
        sl = np.linalg.norm(step, axis=1)
        V = V - step * np.minimum(1, 0.6 * h / np.maximum(sl, 1e-12))[:, None]
    o = np.eye(3) * e
    N = np.stack([(fn(V + o[d]) - fn(V - o[d])) for d in range(3)], 1)
    N /= np.maximum(np.linalg.norm(N, axis=1), 1e-12)[:, None]
    fnr = np.cross(V[Q[:, 2]] - V[Q[:, 0]], V[Q[:, 3]] - V[Q[:, 1]])
    flip = (fnr * N[Q].sum(1)).sum(1) < 0
    Q[flip] = Q[flip][:, ::-1]
    return V, Q, N


# ---------------- sneakers ----------------------------------------------------------

def _foot_frame(B, side_x):
    co = B.co
    fw = B.w('foot_l', 'foot_r', 'ball_l', 'ball_r')
    sel = (fw > 0.4) & B.isbody & (np.sign(co[:, 0]) == np.sign(side_x))
    P = co[sel]
    heel_y, toe_y = P[:, 1].max(), P[:, 1].min()
    ground = P[:, 2].min()
    cx = np.median(P[:, 0])
    width = np.percentile(P[:, 0], 97) - np.percentile(P[:, 0], 3)
    s = 'l' if side_x > 0 else 'r'
    ank = None
    for k in (s + '-ankle',):
        if k in B.J:
            ank = B.J[k]
    if ank is None or np.sign(ank[0]) != np.sign(side_x):
        ank = np.array([cx, heel_y - 0.05, ground + 0.08])
    return dict(heel=heel_y, toe=toe_y, ground=ground, cx=cx, width=width, ank=ank, sel=sel)


def _make_sneakers_sdf(B, h, rig, coll, name, style, c_main, c_accent, c_sole, seed=1):
    objs = []
    covered = np.zeros(len(B.co), bool)
    for side_x in (1, -1):
        fr = _foot_frame(B, side_x if B.J['l-ankle'][0] > 0 else -side_x)
        L = fr['heel'] - fr['toe'] + 0.035
        W = max(fr['width'], 0.085) + 0.03
        g = fr['ground']
        cx = fr['cx']
        y0 = fr['toe'] - 0.022  # toe tip
        ank = fr['ank']
        chunky = style == 'CHUNKY'
        court = style == 'COURT'
        # silhouette parameters: sole height, extra heel stack, upper height scale, sole overhang
        sole_h, heel_up, hsc, over = {'CHUNKY': (0.040, 0.010, 1.08, 0.009),
                                      'RUNNER': (0.024, 0.016, 0.9, 0.004),
                                      'COURT': (0.029, 0.004, 1.0, 0.005)}[style]
        if chunky:
            W += 0.012

        def u_of(P):
            return np.clip((P[:, 1] - y0) / L, 0, 1)  # 0 toe .. 1 heel

        UK = [0.0, 0.05, 0.16, 0.3, 0.5, 0.7, 0.88, 1.0]
        WK = [0.8, 0.86, 0.95, 1.0, 0.86, 0.83, 0.82, 0.8]
        HK_U = [0.0, 0.07, 0.2, 0.42, 0.64, 0.8, 1.0]
        HK = [0.016, 0.03, 0.043, 0.06, 0.08, 0.074, 0.08]

        def frame(P):
            uu = (P[:, 1] - y0) / L
            uc = np.clip(uu, 0, 1)
            hw = W / 2 * np.interp(uc, UK, WK)
            # round toe and heel in plan view (no square-cut ends)
            tr = np.sqrt(np.clip(1 - np.clip((0.14 - uu) / 0.14, 0, 1) ** 2, 0.0, 1))
            hr = np.sqrt(np.clip(1 - np.clip((uu - 0.86) / 0.14, 0, 1) ** 2, 0.0, 1))
            hw = np.maximum(hw * tr * hr, 1e-4)
            spring = 0.016 * np.clip((0.2 - uu) / 0.2, 0, 1) ** 2      # toe spring
            st = g + spring + sole_h + heel_up * np.clip((uu - 0.55) / 0.45, 0, 1)
            H = np.interp(uc, HK_U, HK) * hsc
            return uu, uc, hw, spring, st, H

        def fn(P):
            uu, uc, hw, spring, st, H = frame(P)
            dx = np.abs(P[:, 0] - cx)
            # upper: superellipse cross-section sitting on the sole, rounded toe in plan view
            zz = np.clip((P[:, 2] - st) / H, 0, None)
            n = ((dx / hw) ** 2.6 + zz ** 2.6) ** (1 / 2.6)
            up = (n - 1) * np.minimum(hw, H) * 0.85
            up = s_max(up, (st - 0.004) - P[:, 2], 0.003)
            up = s_max(up, (y0 - 0.002) - P[:, 1], 0.01)
            up = s_max(up, P[:, 1] - (y0 + L), 0.012)
            # tongue and heel tab
            tongue = sd_ell(P, np.array([cx, y0 + L * 0.66, g + sole_h + 0.083 * hsc]), [0.024, 0.045, 0.012])
            up = s_min(up, tongue, 0.01)
            tab = sd_ell(P, np.array([ank[0], y0 + L - 0.012, g + sole_h + 0.085 * hsc]), [0.016, 0.01, 0.018])
            up = s_min(up, tab, 0.006)
            # ankle opening
            hole = sd_ell(P, np.array([ank[0], y0 + L * 0.8, g + sole_h + 0.1 * hsc]), [0.033, 0.05, 0.03])
            up = s_max(up, -hole, 0.005)
            # sole: follows the outline with a little overhang, flat sidewall, toe spring
            sw = hw * 1.04 + over
            uo = over / L
            tro = np.sqrt(np.clip(1 - np.clip((0.14 - uu - uo) / 0.14, 0, 1) ** 2, 0.0, 1))
            hro = np.sqrt(np.clip(1 - np.clip((uu - uo - 0.86) / 0.14, 0, 1) ** 2, 0.0, 1))
            sw = (W / 2 * np.interp(uc, UK, WK) * 1.04 + over) * tro * hro
            sole = np.maximum.reduce([dx - sw, (g + spring * 0.9) - P[:, 2], P[:, 2] - (st + 0.002),
                                      (y0 - over) - P[:, 1], P[:, 1] - (y0 + L + over)])
            sole = s_max(sole, dx - sw, 0.004)
            if chunky:
                # stacked midsole layer + sculpted ripples
                sole = sole + 0.0012 * np.sin(P[:, 1] * 2 * math.pi / 0.045 + P[:, 2] * 60) * (P[:, 2] < st)
            d = s_min(sole, up, 0.003)
            d = s_max(d, g - P[:, 2], 0.002)
            return d

        lo = np.array([cx - W / 2 - 0.03, y0 - 0.02, g - 0.01])
        hi = np.array([cx + W / 2 + 0.03, fr['heel'] + 0.03, g + 0.2])
        V, Q, N = sdf_mesh(fn, lo, hi, 0.0028)
        u = np.clip((V[:, 1] - y0) / L, 0, 1)
        z = V[:, 2] - g
        _, _, hwv, _, stv, Hv = frame(V)
        col = np.tile(c_main, (len(V), 1))
        mat_id = np.zeros(len(V), int)  # 0 upper, 1 sole rubber, 2 metallic
        sole_m = V[:, 2] < stv + 0.001
        # outsole stitching line and a darker rubber bottom edge
        stitch = ~sole_m & (V[:, 2] < stv + 0.008) & (np.sin(V[:, 1] * 2 * math.pi / 0.006) > 0.2)
        bottom = z < 0.006
        col[sole_m] = c_sole
        col[sole_m & bottom] = c_sole * 0.55
        mat_id[sole_m] = 1
        if court:
            # leather panels: toe cap, eyestay and heel counter slightly darker seams + side panel overlay
            ov = ~sole_m & ((u > 0.72) & (V[:, 2] < stv + 0.05) | (np.abs(np.abs(V[:, 0] - cx) - hwv * 0.9) < 0.004) & (u > 0.3) & (u < 0.7))
            col[ov] = c_accent
            seam = ~sole_m & (np.abs(u - 0.2) < 0.006)
            col[seam] *= 0.8
            col[stitch] *= 0.82
        elif chunky:
            col[(z > sole_h - 0.004) & (z < sole_h + 0.012)] = c_sole * 0.85 + c_accent * 0.15
            # layered overlays on the upper: toe cap, eyestay, heel counter
            ov = ~sole_m & ((u < 0.22) | (u > 0.78) | (np.abs(V[:, 0] - cx) > W / 2 * 0.72))
            col[ov] = c_accent
        else:
            # retro runner: mesh base, metallic overlays sweeping diagonally, gel window
            band = ~sole_m & (np.abs(np.sin((u * 2.2 - z * 9) * math.pi)) < 0.22) & (np.abs(V[:, 0] - cx) > W / 2 * 0.55)
            col[band] = c_accent
            mat_id[band] = 2
            heel = ~sole_m & (u > 0.8) & (z < sole_h + 0.05)
            col[heel] = c_accent
            mat_id[heel] = 2
            gel = sole_m & (u > 0.7) & (z > 0.012) & (z < sole_h - 0.006) & (np.abs(V[:, 0] - cx) > W / 2 * 0.6)
            col[gel] = np.array([0.55, 0.6, 0.65])
            mesh_tex = 0.92 + 0.08 * (np.sin(V[:, 1] * 900) * np.sin(V[:, 2] * 900) > 0)
            col[~sole_m & ~band & ~heel] *= mesh_tex[~sole_m & ~band & ~heel][:, None]
        # laces across the top
        lace = (~sole_m) & (u > 0.3) & (u < 0.66) & (np.abs(V[:, 0] - cx) < 0.022) & (N[:, 2] > 0.45) & \
               (np.sin(u * 2 * math.pi / 0.05) > 0.1)
        col[lace] = c_main * 0.6 + 0.4 * np.array([0.9, 0.9, 0.9])
        col *= (1 + 0.04 * np.array([noise.noise(Vector(p * 80)) for p in V]))[:, None]
        me = bpy.data.meshes.new(name + ("_L" if side_x > 0 else "_R"))
        me.from_pydata([tuple(v) for v in V], [], Q.tolist())
        _set_colors(me, np.concatenate([np.clip(col, 0, 1), np.ones((len(V), 1))], 1))
        me.materials.append(get_mat('leather'))
        me.materials.append(get_mat('rubber'))
        me.materials.append(get_mat('chrome'))
        fm = mat_id[Q].max(1)
        me.polygons.foreach_set('material_index', fm.astype(np.int32))
        me.polygons.foreach_set('use_smooth', np.ones(len(Q), bool))
        me.update()
        sfx = 'l' if (V[:, 0].mean() > 0) == (B.J['l-ankle'][0] > 0) else 'r'
        wb = smoothstep(0.55, 0.3, u)
        ob = bpy.data.objects.new(me.name, me)
        for bname, w in (('ball_' + sfx, wb), ('foot_' + sfx, 1 - wb)):
            vg = ob.vertex_groups.new(name=bname)
            q = np.round(w * 20).astype(int)
            for lv in np.unique(q):
                if lv > 0:
                    vg.add(np.nonzero(q == lv)[0].tolist(), lv / 20.0, 'REPLACE')
        _attach(ob, h, rig, coll)
        objs.append(ob)
        covered |= fr['sel'] | ((B.w('foot_l', 'foot_r', 'ball_l', 'ball_r') > 0.2) & (np.sign(B.co[:, 0]) == np.sign(fr['cx'])))
    return objs, covered


# ---------------- sneakers v2: explicit sneaker construction ----------------------------
# Built like a real shoe: lasted upper (toe box, vamp, quarters, heel) with a real throat and
# collar opening, padded collar, eyestay edges, tongue, criss-cross laces, and a separate
# midsole/outsole with toe spring, sidewall, tread and insole.

def _sweep_tube(path, rad, sides=8, flat=1.0, up=(0.0, 0.0, 1.0)):
    path = np.asarray(path, float)
    n = len(path)
    rad = np.broadcast_to(np.asarray(rad, float), (n,))
    T = np.gradient(path, axis=0)
    T /= np.maximum(np.linalg.norm(T, axis=1, keepdims=True), 1e-9)
    U = np.array(up, float)
    V, F = [], []
    for i in range(n):
        nrm = U - T[i] * np.dot(U, T[i])
        if np.linalg.norm(nrm) < 1e-6:
            nrm = np.array([1.0, 0, 0]) - T[i] * T[i, 0]
        nrm /= np.linalg.norm(nrm)
        bi = np.cross(T[i], nrm)
        for k in range(sides):
            a = 2 * math.pi * k / sides
            V.append(path[i] + rad[i] * (math.cos(a) * bi + flat * math.sin(a) * nrm))
    for i in range(n - 1):
        for k in range(sides):
            a, b = i * sides + k, i * sides + (k + 1) % sides
            F.append((a, b, b + sides, a + sides))
    return np.array(V), F


def make_sneakers(B, h, rig, coll, name, style, c_main, c_accent, c_sole, seed=1):
    objs = []
    covered = np.zeros(len(B.co), bool)
    c_main = np.asarray(c_main, float)
    c_accent = np.asarray(c_accent, float)
    c_sole = np.asarray(c_sole, float)
    rng = np.random.default_rng(seed)
    for side_x in (1, -1):
        fr = _foot_frame(B, side_x if B.J['l-ankle'][0] > 0 else -side_x)
        L = fr['heel'] - fr['toe'] + 0.04
        W = max(fr['width'], 0.085) + 0.01
        g = fr['ground']
        cx = fr['cx']
        y0 = fr['toe'] - 0.026
        sx_out = 1.0 if cx > 0 else -1.0          # +1 = lateral side is +x
        chunky, court, runner = style == 'CHUNKY', style == 'COURT', style == 'RUNNER'
        sole_h, drop, over, hsc = {'CHUNKY': (0.046, 0.010, 0.011, 1.04),
                                   'RUNNER': (0.024, 0.016, 0.004, 0.93),
                                   'COURT': (0.031, 0.003, 0.004, 1.0)}[style]
        if chunky:
            W += 0.01

        # ---- last shape --------------------------------------------------------------
        UK = [0.0, 0.05, 0.14, 0.27, 0.45, 0.62, 0.8, 0.92, 1.0]
        WK = [0.6, 0.8, 0.94, 1.0, 0.88, 0.84, 0.82, 0.78, 0.7]

        def round_ends(u, r0=0.12, r1=0.1):
            tr = np.sqrt(np.clip(1 - np.clip((r0 - u) / r0, 0, 1) ** 2, 0, 1))
            hr = np.sqrt(np.clip(1 - np.clip((u - (1 - r1)) / r1, 0, 1) ** 2, 0, 1))
            return tr * hr

        def hw(u):
            return np.maximum(W / 2 * np.interp(u, UK, WK) * round_ends(u, 0.22, 0.16), 1e-4)

        def spring(u):
            return 0.019 * np.clip((0.22 - u) / 0.22, 0, 1) ** 2

        def st(u):   # top of the sole (where the upper sits)
            return g + spring(u) + sole_h + drop * smoothstep(0.4, 1.0, u)

        HU = [0.0, 0.03, 0.1, 0.22, 0.34, 0.5, 0.66, 0.74, 0.86, 1.0]
        HH = [0.014, 0.026, 0.037, 0.045, 0.051, 0.062, 0.077, 0.082, 0.08, 0.075]

        def H(u):
            return np.interp(u, HU, HH) * hsc * (1.0 if not runner else 0.97)

        pe = 2.25

        def section(u, phi):
            s = np.sign(np.sin(phi)) * np.abs(np.sin(phi)) ** (2 / pe)
            c = np.abs(np.cos(phi)) ** (2 / pe)
            x = cx + hw(u) * s
            z = st(u) + H(u) * c
            return x, z

        # opening: throat (lace gap) then collar
        def phi_open(u):
            gap = 0.008 + 0.009 * np.clip((u - 0.34) / 0.38, 0, 1)
            sg = np.clip(gap / hw(u), 0, 1) ** (pe / 2)
            ph_gap = np.arcsin(np.clip(sg, 0, 1))
            ph_gap = ph_gap * smoothstep(0.31, 0.37, u)
            hc = np.interp(u, [0.68, 0.76, 0.84, 0.93, 1.0], [0.08, 0.062, 0.055, 0.066, 0.074]) * hsc
            ch = np.clip(hc / H(u), 0, 1) ** (pe / 2)
            ph_h = np.arccos(np.clip(ch, 0, 1))
            b = smoothstep(0.66, 0.78, u)
            return ph_gap * (1 - b) + np.maximum(ph_h, ph_gap) * b

        nu, nj = 140, 30
        tt = np.linspace(0, 1, nu)
        us = 0.5 * tt + 0.5 * (0.5 - 0.5 * np.cos(math.pi * tt))   # a bit denser at toe and heel
        Vu, Fu, Pu, Phu, Su = [], [], [], [], []
        for side in (-1, 1):
            base = len(Vu)
            for i, u in enumerate(us):
                po = phi_open(np.array([u]))[0]
                for j in range(nj + 1):
                    ph = side * (po + (j / nj) * (math.pi / 2 - po))
                    x, z = section(np.array([u]), np.array([ph]))
                    Vu.append((x[0], y0 + u * L, z[0]))
                    Pu.append(u)
                    Phu.append(abs(ph) - po)   # distance (rad) from the opening edge
                    Su.append(side)
            for i in range(nu - 1):
                for j in range(nj):
                    a = base + i * (nj + 1) + j
                    b_ = a + nj + 1
                    if side < 0:
                        Fu.append((a, a + 1, b_ + 1, b_))
                    else:
                        Fu.append((a, b_, b_ + 1, a + 1))
        # stitch the two halves together where the upper is closed (toe box / vamp)
        for i in range(nu - 1):
            if phi_open(np.array([us[i]]))[0] < 1e-4 and phi_open(np.array([us[i + 1]]))[0] < 1e-4:
                aL = i * (nj + 1)
                aR = (nu * (nj + 1)) + i * (nj + 1)
                Fu.append((aL, aL + nj + 1, aR + nj + 1, aR))
        Vu = np.array(Vu)
        Pu = np.array(Pu)
        Phu = np.array(Phu)
        Su = np.array(Su)
        zu = Vu[:, 2] - st(Pu)
        xl = (Vu[:, 0] - cx) * sx_out                 # + lateral, - medial

        # ---- upper colours: real overlay panels + seams --------------------------------
        col = np.tile(c_main, (len(Vu), 1))
        seam = np.zeros(len(Vu))

        def band_edge(f, w=0.0018):
            return np.exp(-(f / w) ** 2)

        mud = 0.017 + 0.004 * np.sin(Pu * 6)          # mudguard / foxing line height
        toecap = 0.2 - 0.03 * np.abs(Vu[:, 0] - cx) / (W / 2)
        heelc = 0.79 + 0.04 * (zu / 0.06)
        eyestay = Phu < 0.32
        throat = (Pu > 0.33) & (Pu < 0.74)
        if court:
            over_m = (zu < mud) | (Pu < toecap) | ((Pu > heelc) & (zu < 0.055)) | (eyestay & throat)
            col[over_m] = c_accent
            # side panel: a clean sweep on both quarters (logo-free)
            sweep = (Pu > 0.42) & (Pu < 0.8) & (np.abs(zu - (0.022 + 0.035 * (Pu - 0.42))) < 0.006 + 0.012 * (0.8 - Pu))
            col[sweep] = c_accent * 0.98
            seam += band_edge(zu - mud) * (Pu < 0.85) + band_edge((Pu - toecap) * L) + band_edge((Pu - heelc) * L) * (zu < 0.055)
            # toe perforations
            perf = (Pu > 0.04) & (Pu < 0.17) & (zu > 0.012) & ((np.sin(Pu * L * 2 * math.pi / 0.006) * np.sin(Vu[:, 0] * 2 * math.pi / 0.006)) > 0.85)
            col[perf] *= 0.7
        elif runner:
            mesh = 0.97 + 0.03 * ((np.sin(Pu * L * 2 * math.pi / 0.004) * np.sin(Vu[:, 2] * 2 * math.pi / 0.004)) > 0)
            col *= mesh[:, None]
            suede = (Pu < 0.17) | ((Pu > 0.8) & (zu < 0.05)) | (eyestay & throat) | (zu < 0.012)
            col[suede] = c_main * 0.82
            # flowing metallic overlays on the quarters (generic, logo-free)
            flow = (Pu > 0.3) & (Pu < 0.85) & (np.abs(np.sin((Pu * 3.0 - zu * 22) * math.pi)) < 0.16) & (zu > 0.01)
            col[flow] = c_accent
            seam += band_edge((Pu - 0.17) * L) + band_edge(zu - 0.012)
        else:
            panels = (Pu < 0.24) | ((Pu > 0.76) & (zu < 0.06)) | (zu < 0.02 + 0.01 * np.sin(Pu * 9))
            col[panels] = c_accent
            mesh = np.ones(len(Vu))
            col[~panels] *= mesh[~panels][:, None]
            seam += band_edge((Pu - 0.24) * L) + band_edge(zu - 0.02 - 0.01 * np.sin(Pu * 9))
        # stitching: dashed lines just inside each seam
        dash = (np.sin((Pu * L + zu) * 2 * math.pi / 0.004) > 0).astype(float)
        col *= (1 - 0.3 * np.clip(seam, 0, 1))[:, None]
        col *= (1 - 0.08 * dash * np.clip(seam * 0.6, 0, 1))[:, None]
        col *= (1 + 0.03 * rng.standard_normal(len(Vu)) * 0.3)[:, None]
        mat_u = np.zeros(len(Fu), int)
        if runner:
            fl = np.array([flow[list(f)].all() for f in Fu])
            mat_u[fl] = 2

        parts_V, parts_F, parts_C, parts_M, parts_U = [Vu], [Fu], [col], [mat_u], [Pu]

        def add_part(V, F, C, mat, U):
            parts_V.append(np.asarray(V))
            parts_F.append(F)
            parts_C.append(np.asarray(C))
            parts_M.append(np.full(len(F), mat))
            parts_U.append(np.asarray(U))

        def edge_point(u, side, out=0.0, lift=0.0):
            po = phi_open(np.array([u]))[0]
            x, z = section(np.array([u]), np.array([side * po]))
            return np.array([x[0] + side * out, y0 + u * L, z[0] + lift])

        # ---- padded collar ------------------------------------------------------------
        cu = np.linspace(0.70, 1.0, 26)
        path = [edge_point(u, -1, 0.002, 0.001) for u in cu] + [edge_point(u, 1, 0.002, 0.001) for u in cu[::-1]]
        path = np.array(path)
        for _ in range(3):
            path[1:-1] = path[1:-1] * 0.5 + (path[:-2] + path[2:]) * 0.25
        Vc, Fc = _sweep_tube(path, 0.0062 if not runner else 0.0055, sides=10, flat=0.85)
        add_part(Vc, Fc, np.tile(c_main * (0.92 if court else 0.85), (len(Vc), 1)), 0, np.full(len(Vc), 0.85))
        # eyestay edges
        for side in (-1, 1):
            eu = np.linspace(0.34, 0.71, 24)
            ep = np.array([edge_point(u, side, 0.0, 0.0008) for u in eu])
            Ve, Fe = _sweep_tube(ep, 0.0022, sides=6, flat=0.7)
            add_part(Ve, Fe, np.tile(c_accent * 0.95, (len(Ve), 1)), 0, np.interp(np.arange(len(Ve)) // 6, [0, 23], [0.34, 0.71]))

        # ---- tongue -------------------------------------------------------------------
        tu = np.linspace(0.32, 0.79, 30)
        tn = 9
        Vt, Ft, Ut = [], [], []
        for i, u in enumerate(tu):
            po = phi_open(np.array([min(u, 0.74)]))[0]
            half = (hw(np.array([min(u, 0.74)]))[0] * (np.sin(po) ** (2 / pe))) + 0.009
            ztop = st(np.array([min(u, 0.72)]))[0] + H(np.array([min(u, 0.72)]))[0]
            rise = 0.02 * smoothstep(0.66, 0.79, u)            # tongue stands up above the collar
            back = 0.012 * smoothstep(0.7, 0.79, u)
            for k in range(tn):
                xx = (k / (tn - 1) * 2 - 1)
                z = ztop - 0.0035 + rise - 0.006 * xx * xx
                Vt.append((cx + xx * half, y0 + min(u, 0.74) * L + back, z))
                Ut.append(u)
        for i in range(len(tu) - 1):
            for k in range(tn - 1):
                a = i * tn + k
                Ft.append((a, a + 1, a + tn + 1, a + tn))
        Vt = np.array(Vt)
        ctg = np.tile(c_main * 0.97, (len(Vt), 1))
        ctg[np.array(Ut) > 0.74] = c_accent * 0.9         # tongue tag area
        add_part(Vt, Ft, ctg, 0, Ut)

        # ---- laces (criss-cross over the tongue) ---------------------------------------
        nl = 6 if not runner else 7
        lu = np.linspace(0.39, 0.69, nl)
        E = {(s, k): edge_point(u, s, 0.0045, 0.0015) for k, u in enumerate(lu) for s in (-1, 1)}
        lace_col = c_main * 0.85 + 0.12 if court else np.clip(c_main * 0.6 + 0.35, 0, 1)
        segs = [(E[(-1, 0)], E[(1, 0)])]
        for k in range(nl - 1):
            segs.append((E[(-1, k)], E[(1, k + 1)]))
            segs.append((E[(1, k)], E[(-1, k + 1)]))
        for si, (a, b) in enumerate(segs):
            t = np.linspace(0, 1, 9)[:, None]
            p = a * (1 - t) + b * t
            p[:, 2] += 0.003 * np.sin(np.pi * t[:, 0]) + 0.0012 * (si % 2)
            Vl, Fl = _sweep_tube(p, 0.0028, sides=6, flat=0.45)
            add_part(Vl, Fl, np.tile(lace_col, (len(Vl), 1)), 3, np.full(len(Vl), float(lu.mean())))
        # loose lace ends near the top eyelet
        for s in (-1, 1):
            a = E[(s, nl - 1)]
            p = np.array([a + np.array([s * 0.004 * t, 0.012 * t, -0.03 * t * t]) for t in np.linspace(0, 1, 7)])
            Vl, Fl = _sweep_tube(p, 0.0026, sides=6, flat=0.45)
            add_part(Vl, Fl, np.tile(lace_col, (len(Vl), 1)), 3, np.full(len(Vl), 0.7))

        # ---- sole: sidewall swept around the plan outline + outsole + insole ---------
        ns = 70
        su = 0.5 - 0.5 * np.cos(math.pi * np.linspace(0, 1, ns))

        def rim_w(uu):
            return (W / 2 * np.interp(uu, UK, WK) + over) * 1.03 * round_ends(uu, 0.22, 0.16)

        def rim_y(uu):
            return y0 - over * 0.7 + uu * (L + over * 1.4)

        per = [(u_, 1.0) for u_ in su] + [(u_, -1.0) for u_ in su[::-1][1:-1]]
        levels = np.array([0.0, 0.05, 0.18, 0.45, 0.72, 0.9, 1.0])
        inset = np.array([0.0035, 0.0012, 0.0, 0.0, 0.0, 0.0, 0.0012 if court else 0.0])
        bulge = 0.0015 * np.sin(np.pi * levels) * (2.5 if chunky else 1.0)
        Vs, Cs, Us, Fs = [], [], [], []
        npr = len(per)
        for k, lev in enumerate(levels):
            for (u_, sd) in per:
                uu = np.array([u_])
                rw = rim_w(uu)[0]
                zb = g + spring(uu)[0] * 0.92
                zt = st(uu)[0] + 0.002
                # outward direction in plan ~ sideways, but at the tips the outline turns: push along
                # the outline normal by scaling about the centre line
                x = cx + sd * max(rw - inset[k] + bulge[k], 0.0)
                tip = 1 - round_ends(uu, 0.22, 0.16)[0]
                yy = rim_y(uu)[0] + (-(inset[k] - bulge[k]) * tip if u_ < 0.5 else (inset[k] - bulge[k]) * tip)
                Vs.append((x, yy, zb + lev * (zt - zb)))
                Us.append(u_)
                c = c_sole.copy()
                if court:
                    if abs(lev - 0.78) < 0.08 and np.sin(u_ * L * 2 * math.pi / 0.005) > 0:
                        c = c * 0.8                          # cupsole stitching
                    if lev < 0.1:
                        c = c * 0.86
                elif chunky:
                    c = c * (1.0 if int(lev * 3.999) % 2 == 0 else 0.86)
                    if lev < 0.08:
                        c = c * 0.7
                else:
                    if u_ > 0.66 and 0.25 < lev < 0.75 and sd * sx_out > 0:
                        c = c_accent * 0.85 + 0.1            # heel cushioning window
                    if lev < 0.1:
                        c = c * 0.6
                Cs.append(tuple(c))
        # ledge: the sole's top face runs inward under the upper (no open gap / dark seam)
        for (u_, sd) in per:
            uu = np.array([u_])
            x = cx + sd * hw(uu)[0] * 0.9
            tip = 1 - round_ends(uu, 0.22, 0.16)[0]
            yy = rim_y(uu)[0] + (0.006 * tip if u_ < 0.5 else -0.006 * tip)
            Vs.append((x, yy, st(uu)[0] + 0.001))
            Us.append(u_)
            Cs.append(tuple(c_sole * 0.95))
        nlev = len(levels) + 1
        for k in range(nlev - 1):
            for i in range(npr):
                a_ = k * npr + i
                b2 = k * npr + (i + 1) % npr
                Fs.append((a_, a_ + npr, b2 + npr, b2))
        add_part(np.array(Vs), Fs, np.array(Cs), 1, np.array(Us))
        # outsole (bottom) and insole as grids across the outline
        for which in ('bottom', 'insole'):
            Vb, Cb, Ub, Fb = [], [], [], []
            nb = 9
            for u_ in su:
                uu = np.array([u_])
                rw = rim_w(uu)[0] - (inset[0] if which == 'bottom' else over + 0.01)
                z = (g + spring(uu)[0] * 0.92) if which == 'bottom' else st(uu)[0] - 0.002
                for m in range(nb):
                    xx = -1 + 2 * m / (nb - 1)
                    Vb.append((cx + xx * max(rw, 0), rim_y(uu)[0], z))
                    Ub.append(u_)
                    if which == 'insole':
                        Cb.append((0.13, 0.13, 0.14))
                    else:
                        tread = (np.sin(u_ * L * 2 * math.pi / 0.009) > 0.3) or \
                                (0.15 < u_ < 0.4 and abs(np.hypot((u_ - 0.27) * L, xx * rw) % 0.012 - 0.006) < 0.0018)
                        Cb.append(tuple(c_sole * (0.6 if tread else 0.74)))
            for i in range(ns - 1):
                for m in range(nb - 1):
                    a_ = i * nb + m
                    if which == 'bottom':
                        Fb.append((a_, a_ + nb, a_ + nb + 1, a_ + 1))
                    else:
                        Fb.append((a_, a_ + 1, a_ + nb + 1, a_ + nb))
            add_part(np.array(Vb), Fb, np.array(Cb), 1, np.array(Ub))

        # ---- merge, smooth, material -------------------------------------------------
        Vall, Fall, Call, Mall, Uall = [], [], [], [], []
        off = 0
        for V, F, C, M, U in zip(parts_V, parts_F, parts_C, parts_M, parts_U):
            Vall.append(V)
            Fall += [tuple(int(i) + off for i in f) for f in F]
            Call.append(C)
            Mall.append(M)
            Uall.append(U)
            off += len(V)
        V = np.concatenate(Vall)
        C = np.concatenate(Call)
        U = np.concatenate(Uall)
        M = np.concatenate(Mall)
        C = np.clip(C * (1 + 0.04 * np.array([noise.noise(Vector(p * 80)) for p in V]))[:, None], 0, 1)
        me = bpy.data.meshes.new(name + ("_L" if side_x > 0 else "_R"))
        me.from_pydata([tuple(v) for v in V], [], Fall)
        me.validate()
        # colours by nearest original vertex index survive remove_doubles via index order only
        # if nothing merged; re-sample by position to be safe
        from mathutils.kdtree import KDTree
        kd = KDTree(len(V))
        for i, p in enumerate(V):
            kd.insert(Vector(p), i)
        kd.balance()
        nv = len(me.vertices)
        idx = np.array([kd.find(v.co)[1] for v in me.vertices])
        _set_colors(me, np.concatenate([C[idx], np.ones((nv, 1))], 1))
        for kind in ('leather', 'rubber', 'chrome', 'cotton'):
            me.materials.append(get_mat(kind))
        # face materials from the part each face came from (first vertex)
        if len(me.polygons) == len(M):
            me.polygons.foreach_set('material_index', M.astype(np.int32))
        me.polygons.foreach_set('use_smooth', np.ones(len(me.polygons), bool))
        me.update()
        Uv = U[idx]
        sfx = 'l' if (V[:, 0].mean() > 0) == (B.J['l-ankle'][0] > 0) else 'r'
        wb = smoothstep(0.55, 0.3, Uv)
        ob = bpy.data.objects.new(me.name, me)
        sub = ob.modifiers.new("Subsurf", 'SUBSURF')
        sub.levels = 0
        sub.render_levels = 1
        for bname, w in (('ball_' + sfx, wb), ('foot_' + sfx, 1 - wb)):
            vg = ob.vertex_groups.new(name=bname)
            q = np.round(w * 20).astype(int)
            for lv in np.unique(q):
                if lv > 0:
                    vg.add(np.nonzero(q == lv)[0].tolist(), lv / 20.0, 'REPLACE')
        _attach(ob, h, rig, coll)
        objs.append(ob)
        covered |= fr['sel'] | ((B.w('foot_l', 'foot_r', 'ball_l', 'ball_r') > 0.2) & (np.sign(B.co[:, 0]) == np.sign(fr['cx'])))
    return objs, covered


# ---------------- graphic prints painted into vertex colour ----------------------------

def _front_uv(B, co):
    """Chest-centred 2D coordinates (x, z) for front prints."""
    c = B.J.get('spine-3', B.J['neck'] - np.array([0, 0, 0.18]))
    return co[:, 0] - c[0], co[:, 2] - (c[2] - 0.02)


def web_mask(x, z, spokes=12, ring_gap=0.045, width=0.0035):
    r = np.hypot(x, z)
    th = np.arctan2(z, x)
    seg = 2 * math.pi / spokes
    a = (th % seg) - seg / 2
    spoke_d = np.abs(np.sin(a)) * r
    # rings: polygon arcs that sag between spokes
    sag = 1 - 0.18 * (np.cos(a * spokes / 2 * 2) * 0 + (np.abs(a) / (seg / 2)) ** 2 * 0)
    rr = r * np.cos(a) / np.cos(seg / 2) * (1 + 0.06 * (1 - (np.abs(a) / (seg / 2)) ** 2))
    ring_d = np.abs(((rr + ring_gap / 2) % ring_gap) - ring_gap / 2)
    return (np.minimum(spoke_d, ring_d) < width) & (r < 0.24), np.minimum(spoke_d, ring_d)


def star_mask(x, z, cx, cz, R):
    px, pz = x - cx, z - cz
    r = np.hypot(px, pz)
    th = np.arctan2(pz, px) + math.pi / 2
    k = (th % (2 * math.pi / 5)) - math.pi / 5
    # inner radius ratio 0.45 star
    edge = R * (0.45 + 0.55 * (np.abs(k) / (math.pi / 5)) ** 0) / (np.cos(k) * 1.0 + 1e-6)
    rs = R * 0.45 / np.maximum(np.cos(np.abs(k) - math.pi / 5) * 0.45 + np.cos(k) * 0.55 * 0, 1e-3)
    tip = R / np.maximum(np.cos(k), 1e-3)
    lim = np.interp(np.abs(k) / (math.pi / 5), [0, 1], [R, R * 0.42])
    return r < lim


def flower_mask(x, z, scale=0.07, seed=3):
    rng = np.random.default_rng(seed)
    out = np.zeros(len(x), bool)
    gx = np.round(x / scale)
    gz = np.round(z / scale)
    jx = (np.sin(gx * 12.9898 + gz * 78.233) * 43758.5453) % 1.0 - 0.5
    jz = (np.sin(gx * 39.346 + gz * 11.135) * 23421.631) % 1.0 - 0.5
    cx = (gx + jx * 0.4) * scale
    cz = (gz + jz * 0.4) * scale
    px, pz = x - cx, z - cz
    r = np.hypot(px, pz)
    th = np.arctan2(pz, px) + gx
    petal = scale * 0.32 * (0.55 + 0.45 * np.abs(np.cos(th * 2.5)))
    ring = np.abs(r - petal) < scale * 0.03
    centre = r < scale * 0.06
    return ring | centre


# ---------------- designer-inspired tops / bottoms --------------------------------------

def make_designer_top(B, h, rig, coll, name, style, color, accent, pattern):
    base_style = 'ZIPUP' if style == 'TECH' else 'HOODIE'
    return make_top(B, h, rig, coll, name, base_style, color, accent, pattern)


def make_designer_bottom(B, h, rig, coll, name, style, color, accent, pattern, seed=1):
    base = {'RIPPED': 'JOGGERS', 'STARPATCH': 'BAGGY_JEANS', 'FLORAL': 'BAGGY_JEANS', 'TECH': 'JOGGERS'}[style]
    return make_bottom(B, h, rig, coll, name, base, color, accent, pattern)


def add_rhinestones(B, h, rig, coll, name, ob, accent=None, count=520):
    r = _raster_positions(ob.data, 700)
    if r is None:
        return None
    _, pos, _ = r
    chest = B.J.get('spine-3', B.J['neck'] - np.array([0, 0, 0.18]))
    x = pos[:, 0]
    z = pos[:, 2] - (chest[2] - 0.03)
    m, d = web_mask(x, z, spokes=12, ring_gap=0.05, width=0.0025)
    m &= pos[:, 1] < chest[1] + 0.02
    pts = pos[m]
    if not len(pts):
        return None
    rng = np.random.default_rng(3)
    pts = pts[rng.choice(len(pts), size=min(count, len(pts)), replace=False)]
    # push studs out along the garment's front
    bm = bmesh.new()
    for p in pts:
        res = bmesh.ops.create_icosphere(bm, subdivisions=1, radius=0.0021)
        for v in res['verts']:
            v.co += Vector((p[0], p[1] - 0.0045, p[2]))
    sm = bpy.data.meshes.new(name)
    bm.to_mesh(sm)
    bm.free()
    _set_colors(sm, rgba(np.array([0.92, 0.94, 0.97]), len(sm.vertices)))
    sm.update()
    return mesh_object(sm, h, rig, coll, 'chrome', {'spine_02': 0.5, 'spine_03': 0.5})


def make_jewelry(B, h, rig, coll, name, outer_objs, metal, pendant):
    col = np.array([0.8, 0.6, 0.22]) if metal == 'GOLD' else np.array([0.82, 0.83, 0.85])
    objs = make_chain(B, h, rig, coll, name, outer_objs, col)
    for o in objs:
        o.data.materials.clear()
        o.data.materials.append(get_mat('gold' if metal == 'GOLD' else 'chrome'))
    if pendant and objs:
        me = objs[0].data
        lowest = min(me.vertices, key=lambda v: v.co.z).co
        bm = bmesh.new()
        # generic medallion (round disc)
        bmesh.ops.create_cone(bm, cap_ends=True, segments=20, radius1=0.016, radius2=0.016, depth=0.004)
        for v in bm.verts:
            v.co = Vector((v.co.x, v.co.z, v.co.y))
            v.co += Vector((lowest.x, lowest.y - 0.004, lowest.z - 0.02))
        pm = bpy.data.meshes.new(name + "_Pendant")
        bm.to_mesh(pm)
        bm.free()
        _set_colors(pm, rgba(col, len(pm.vertices)))
        pm.update()
        objs.append(mesh_object(pm, h, rig, coll, 'gold' if metal == 'GOLD' else 'chrome', {'spine_03': 1.0}))
    return objs


# ======================================================================================
#  TEXTURE BAKING: rasterise the garment's UVs, evaluate print/fabric functions per texel
# ======================================================================================

def _raster_positions(me, res):
    """Return (pix_index, xyz, vcolor) for every covered texel of mesh UV layout."""
    me.calc_loop_triangles()
    uvl = me.uv_layers.active
    if uvl is None:
        return None
    nt = len(me.loop_triangles)
    tl = np.empty(nt * 3, np.int64)
    me.loop_triangles.foreach_get('loops', tl)
    tv = np.empty(nt * 3, np.int64)
    me.loop_triangles.foreach_get('vertices', tv)
    tl = tl.reshape(-1, 3)
    tv = tv.reshape(-1, 3)
    uv = np.empty(len(me.loops) * 2)
    uvl.data.foreach_get('uv', uv)
    uv = uv.reshape(-1, 2) * res
    co = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get('co', co)
    co = co.reshape(-1, 3)
    col = None
    if me.color_attributes.get('Col'):
        c = np.empty(len(me.vertices) * 4, np.float32)
        me.color_attributes['Col'].data.foreach_get('color', c)
        col = c.reshape(-1, 4)[:, :3]
    wear = me.color_attributes.get('SY_Wear')
    if wear is not None and wear.domain == 'POINT' and col is not None:
        wv = np.empty(len(me.vertices) * 4, np.float32)
        wear.data.foreach_get('color', wv)
        col = np.concatenate([col, wv.reshape(-1, 4)[:, :3]], 1)     # carried along, split off in bake
    pix, pos, vcs = [], [], []
    A, Bv, Cv = uv[tl[:, 0]], uv[tl[:, 1]], uv[tl[:, 2]]
    mn = np.floor(np.minimum(np.minimum(A, Bv), Cv)).astype(int)
    mx = np.ceil(np.maximum(np.maximum(A, Bv), Cv)).astype(int)
    for t in range(nt):
        x0, y0 = mn[t]
        x1, y1 = mx[t]
        if x1 - x0 > 400 or y1 - y0 > 400:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
        px = xs.ravel() + 0.5
        py = ys.ravel() + 0.5
        a, b, c = A[t], Bv[t], Cv[t]
        den = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(den) < 1e-12:
            continue
        w0 = ((b[1] - c[1]) * (px - c[0]) + (c[0] - b[0]) * (py - c[1])) / den
        w1 = ((c[1] - a[1]) * (px - c[0]) + (a[0] - c[0]) * (py - c[1])) / den
        w2 = 1 - w0 - w1
        ok = (w0 >= -0.02) & (w1 >= -0.02) & (w2 >= -0.02)
        if not ok.any():
            continue
        w = np.stack([w0[ok], w1[ok], w2[ok]], 1)
        vi = tv[t]
        pos.append(w @ co[vi])
        if col is not None:
            vcs.append(w @ col[vi])
        xi = np.clip(xs.ravel()[ok], 0, res - 1)
        yi = np.clip(ys.ravel()[ok], 0, res - 1)
        pix.append(yi * res + xi)
    if not pix:
        return None
    return np.concatenate(pix), np.concatenate(pos), (np.concatenate(vcs) if vcs else None)


def _dilate(img, filled, iters=6):
    res = img.shape[0]
    for _ in range(iters):
        acc = np.zeros_like(img)
        cnt = np.zeros((res, res, 1))
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            sh = np.roll(np.roll(img, dy, 0), dx, 1)
            fm = np.roll(np.roll(filled, dy, 0), dx, 1)
            acc += sh * fm[..., None]
            cnt += fm[..., None]
        grow = (~filled) & (cnt[..., 0] > 0)
        img[grow] = acc[grow] / cnt[grow]
        filled = filled | grow
    return img


def garment_wear(ob, B, occluders, kind='top', strength=1.0, seed=0, n_rays=14):
    """Per-vertex baked shading + wear, stored as an RGB multiplier ('SY_Wear'):
    ambient occlusion in folds/overlaps, grime on cuffs/collars/hems, dirt low on pants,
    sun-fading on exposed areas, scuffs on shoes. Used when baking textures (or applied to
    the vertex colours directly when there is no texture)."""
    from mathutils.bvhtree import BVHTree
    me = ob.data
    nv = len(me.vertices)
    if nv == 0:
        return
    rest_co = np.empty(nv * 3)
    me.vertices.foreach_get('co', rest_co)
    rest_co = rest_co.reshape(-1, 3)

    def posed(o):
        """Vertex positions/normals of o deformed only by its armature (current pose), in o's space."""
        saved = []
        for m in o.modifiers:
            saved.append((m, m.show_viewport))
            m.show_viewport = (m.type == 'ARMATURE')
        dg = bpy.context.evaluated_depsgraph_get()
        dg.update()
        ev = o.evaluated_get(dg)
        em = ev.to_mesh()
        n = len(em.vertices)
        V = np.empty(n * 3)
        em.vertices.foreach_get('co', V)
        N = np.empty(n * 3)
        em.vertices.foreach_get('normal', N)
        F = [tuple(pp.vertices) for pp in em.polygons]
        ev.to_mesh_clear()
        for m, v in saved:
            m.show_viewport = v
        M = np.array(o.matrix_world)
        V = V.reshape(-1, 3) @ M[:3, :3].T + M[:3, 3]
        N = N.reshape(-1, 3) @ M[:3, :3].T
        return V, N, F
    # occlusion is computed on the posed character (arms down at the sides, shirt over the
    # waistband), the way the stance actually shades it
    co, nrm, own_f = posed(ob)
    if len(co) != nv:
        co = rest_co
        nrm = np.empty(nv * 3)
        me.vertices.foreach_get('normal', nrm)
        nrm = nrm.reshape(-1, 3)
        own_f = [tuple(pp.vertices) for pp in me.polygons]
    # occluders: body + other garments + itself (folds shade themselves), all in rest space
    verts, polys = [], []
    off = 0

    def add_mesh(V, F):
        nonlocal off
        verts.extend(map(tuple, V))
        polys.extend([tuple(int(i) + off for i in f) for f in F])
        off += len(V)
    if hasattr(B, 'h'):
        Vb, _, Fb = posed(B.h)
        if len(Vb) == len(B.isbody):
            bm_ok = B.isbody
            Fb = [f for f in Fb if all(bm_ok[i] for i in f)]
        add_mesh(Vb, Fb)
    for o in list(occluders):
        if o is None or o.type != 'MESH':
            continue
        Vo, _, Fo = posed(o)
        add_mesh(Vo, Fo)
    add_mesh(co, own_f)
    tree = BVHTree.FromPolygons(verts, polys, epsilon=0.0)
    rng = np.random.default_rng(seed + 3)
    dirs = rng.normal(size=(n_rays, 3))
    dirs /= np.linalg.norm(dirs, axis=1, keepdims=True)
    occ = np.zeros(nv)
    maxd = 0.09
    for i in range(nv):
        n = Vector(nrm[i])
        o_ = Vector(co[i]) + n * 0.0025
        hits = 0.0
        tot = 0.0
        for d in dirs:
            dv = Vector(d)
            c = dv.dot(n)
            if c < 0:
                dv = -dv
                c = -c
            w = c
            tot += w
            loc, _, _, dist = tree.ray_cast(o_, dv, maxd)
            if loc is not None:
                hits += w * (1 - dist / maxd) ** 0.5
        occ[i] = hits / max(tot, 1e-6)
    # smooth a little over the surface so it reads like a baked map, not noise
    me.calc_loop_triangles()
    e = np.empty(len(me.edges) * 2, np.int64)
    me.edges.foreach_get('vertices', e)
    e = e.reshape(-1, 2)
    for _ in range(2):
        acc = np.zeros(nv)
        cnt = np.zeros(nv)
        np.add.at(acc, e[:, 0], occ[e[:, 1]])
        np.add.at(acc, e[:, 1], occ[e[:, 0]])
        np.add.at(cnt, e[:, 0], 1)
        np.add.at(cnt, e[:, 1], 1)
        occ = 0.5 * occ + 0.5 * acc / np.maximum(cnt, 1)
    if kind == 'shoe':
        occ = occ * 0.15          # shoe parts shade each other too much; keep the dirt, not the AO
    ao = 1 - 0.9 * strength * np.clip(occ * 1.4, 0, 1) ** 0.65
    # cavity: fold valleys darker, ridges catch a little light (the classic baked-fold look)
    acc = np.zeros((nv, 3))
    cnt = np.zeros(nv)
    np.add.at(acc, e[:, 0], co[e[:, 1]])
    np.add.at(acc, e[:, 1], co[e[:, 0]])
    np.add.at(cnt, e[:, 0], 1)
    np.add.at(cnt, e[:, 1], 1)
    lap = acc / np.maximum(cnt, 1)[:, None] - co
    elen = np.linalg.norm(co[e[:, 0]] - co[e[:, 1]], axis=1).mean()
    curv = np.einsum('ij,ij->i', lap, nrm) / max(elen, 1e-5)
    for _ in range(1):
        a2 = np.zeros(nv)
        np.add.at(a2, e[:, 0], curv[e[:, 1]])
        np.add.at(a2, e[:, 1], curv[e[:, 0]])
        curv = 0.5 * curv + 0.5 * a2 / np.maximum(cnt, 1)
    cav = np.clip(curv * 7.0, -1, 1)
    if kind != 'shoe':
        ao = ao * (1 - 0.6 * strength * np.clip(cav, 0, 1)) * (1 + 0.15 * strength * np.clip(-cav, 0, 1))
        # lived-in fabric: faint uneven dinginess across the whole garment
        ao = ao * (1 - 0.07 * strength * (vnoise(co, 0.05, seed + 41) * 0.5 + 0.5))
    mul = np.tile(np.clip(ao, 0.25, 1.15)[:, None], (1, 3))
    # distance to open edges (hems, cuffs, collar) by graph propagation
    bnd = np.zeros(nv, bool)
    import bmesh as _bm
    bm = _bm.new()
    bm.from_mesh(me)
    for ed in bm.edges:
        if ed.is_boundary:
            for v in ed.verts:
                bnd[v.index] = True
    bm.free()
    dist = np.where(bnd, 0.0, 9.0)
    L = np.linalg.norm(rest_co[e[:, 0]] - rest_co[e[:, 1]], axis=1)
    for _ in range(40):
        d0 = dist.copy()
        np.minimum.at(dist, e[:, 0], dist[e[:, 1]] + L)
        np.minimum.at(dist, e[:, 1], dist[e[:, 0]] + L)
        if np.allclose(d0, dist):
            break
    edge = np.exp(-dist / 0.014)
    co = rest_co
    grime = np.array([0.74, 0.69, 0.62])          # dull, slightly warm grime
    pel = B.J['pelvis'][2]
    ground = B.J.get('ground', np.array([0, 0, 0]))[2] if hasattr(B.J.get('ground', None), '__len__') else 0.0
    wob = vnoise(co, 0.03, seed + 7) * 0.5 + 0.5
    if kind == 'bottom':
        low = smoothstep(0.32, 0.04, co[:, 2] - ground) * (0.6 + 0.4 * wob)
        knee = 0.0
        for s_ in ('l-knee', 'r-knee'):
            if s_ in B.J:
                knee = knee + np.exp(-(np.linalg.norm(co - B.J[s_], axis=1) / 0.06) ** 2) * (co[:, 1] < B.J[s_][1])
        dirt = np.clip(low * 0.55 + knee * 0.25 + edge * 0.35, 0, 1) * strength
        mul *= 1 - dirt[:, None] * (1 - grime)
    elif kind == 'top':
        cuff_collar = edge * (co[:, 2] > pel - 0.2)
        dirt = np.clip(cuff_collar * 0.45 * (0.6 + 0.4 * wob), 0, 1) * strength
        mul *= 1 - dirt[:, None] * (1 - grime)
        # sun fading on shoulders / top of the sleeves (exposed, facing up)
        up = np.clip(nrm[:, 2], 0, 1) * (1 - np.clip(occ, 0, 1))
        mul *= (1 + 0.07 * strength * up)[:, None]
    elif kind == 'shoe':
        dirt = np.clip(smoothstep(0.035, 0.0, co[:, 2] - ground) * 0.8 + 0.25 * wob * smoothstep(0.08, 0.0, co[:, 2] - ground), 0, 1)
        mul *= 1 - dirt[:, None] * strength * (1 - np.array([0.62, 0.6, 0.56]))
    mul = np.clip(mul, 0.15, 1.15)
    rgba = np.concatenate([mul, np.ones((nv, 1))], 1).astype(np.float32)
    a = me.color_attributes.get('SY_Wear') or me.color_attributes.new('SY_Wear', 'FLOAT_COLOR', 'POINT')
    a.data.foreach_set('color', rgba.ravel())
    try:
        me.color_attributes.active_color = me.color_attributes['Col']
        me.color_attributes.render_color_index = me.color_attributes.active_color_index
    except Exception:
        pass
    return mul


def apply_wear_to_vcol(ob):
    """No texture bake: fold the wear multiplier straight into the vertex colours."""
    me = ob.data
    a = me.color_attributes.get('SY_Wear')
    c = me.color_attributes.get('Col')
    if a is None or c is None or a.domain != c.domain:
        return
    n = len(c.data)
    cv = np.empty(n * 4, np.float32)
    c.data.foreach_get('color', cv)
    wv = np.empty(n * 4, np.float32)
    a.data.foreach_get('color', wv)
    cv = cv.reshape(-1, 4)
    cv[:, :3] *= wv.reshape(-1, 4)[:, :3]
    c.data.foreach_set('color', cv.ravel())


def bake_texture(ob, fn, res=2048, name=None, kind='cotton', alpha=False):
    """fn(P(n,3) rest positions, base_rgb(n,3)) -> rgb (n,3). Writes an image and swaps the
    material to image-textured so the detail survives FBX export."""
    me = ob.data
    r = _raster_positions(me, res)
    if r is None:
        return None
    pix, pos, vc = r
    if vc is None:
        vc = np.full((len(pos), 3), 0.5)
    wmul = None
    if vc is not None and vc.shape[1] == 6:
        vc, wmul = vc[:, :3], vc[:, 3:]
    out = np.clip(fn(pos, vc), 0, 1)
    if wmul is not None:
        # baked shading + wear (Rockstar-style: occlusion and grime live in the texture)
        out = np.concatenate([out[:, :3] * wmul, out[:, 3:]], 1) if out.shape[1] > 3 else out * wmul
        out = np.clip(out, 0, 1)
    ch = out.shape[1]
    img = np.zeros((res, res, ch))
    filled = np.zeros((res, res), bool)
    yy, xx = np.divmod(pix, res)
    img[yy, xx] = out
    filled[yy, xx] = True
    img = _dilate(img, filled)
    if ch == 3:
        img = np.concatenate([img, np.ones((res, res, 1))], 2)
    import uuid
    name = (name or ob.name) + "_tex_" + uuid.uuid4().hex[:6]
    im = bpy.data.images.new(name, res, res, alpha=alpha, float_buffer=False)
    rgba_ = img.astype(np.float32)
    # Blender images are linear in float pixels; convert linear->sRGB for byte images
    lin = rgba_[..., :3]
    srgb = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(np.maximum(lin, 0), 1 / 2.4) - 0.055)
    rgba_[..., :3] = srgb
    im.pixels.foreach_set(rgba_.ravel())
    im.pack()
    mat = bpy.data.materials.new(name + "_mat")
    try:
        mat.use_nodes = True
    except Exception:
        pass
    nt = mat.node_tree
    for nd in list(nt.nodes):
        nt.nodes.remove(nd)
    outn = nt.nodes.new('ShaderNodeOutputMaterial')
    out = outn
    bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')
    tx = nt.nodes.new('ShaderNodeTexImage')
    tx.image = im
    nt.links.new(tx.outputs['Color'], bsdf.inputs['Base Color'])
    nt.links.new(bsdf.outputs[0], out.inputs[0])
    if alpha:
        nt.links.new(tx.outputs['Alpha'], bsdf.inputs['Alpha'])
        for attr, val in (('blend_method', 'HASHED'), ('surface_render_method', 'DITHERED')):
            try:
                setattr(mat, attr, val)
            except Exception:
                pass
    spec = MATS.get(kind, {})
    bsdf.inputs['Roughness'].default_value = spec.get('rough', 0.85)
    me.materials.clear()
    me.materials.append(mat)
    return im


# ---------------- per-texel fabric + print functions -------------------------------------

def _n3(P, s, off=0.0):
    return np.array([noise.noise(Vector(p * s + off)) for p in P])


def seams(P, c, B=None):
    """Darken construction seams and add stitch dashes (side, shoulder, armhole, inseam, outseam)."""
    if B is None:
        return c
    sh = abs(B.J['l-shoulder'][0])
    shz = B.J['l-shoulder'][2]
    pel = B.J['pelvis']
    kx = abs(B.J['l-knee'][0])
    x, y, z = P[:, 0], P[:, 1], P[:, 2]
    side = (np.abs(y - 0.0) < 0.003) & (z > pel[2] - 0.05) & (z < shz)
    shoulder = (np.abs(z - (shz + 0.03) + 0.25 * np.abs(x)) < 0.0025) & (np.abs(x) < sh) & (y > -0.06) & (y < 0.06)
    arm = (np.abs(np.abs(x) - sh * 1.06 - 0.25 * np.clip(z - shz, -0.2, 0.0)) < 0.0025) & (z > shz - 0.13)
    outseam = (np.abs(np.abs(x) - (kx + 0.075)) < 0.0028) & (z < pel[2])
    inseam = (np.abs(np.abs(x) - (kx - 0.06)) < 0.0025) & (z < pel[2] - 0.08) & (np.abs(y) < 0.04)
    m = side | shoulder | arm | outseam | inseam
    c = c.copy()
    c[m] *= 0.72
    stitch = m & (np.sin((x + y + z) * 2 * math.pi / 0.005) > 0.45)
    c[stitch] = c[stitch] * 1.35 + 0.03
    return c


def fabric(P, base, kind):
    if kind == 'denim':
        tw = 0.5 + 0.5 * np.sin((P[:, 0] * 0.7 + P[:, 2] + P[:, 1] * 0.7) * 2 * math.pi / 0.004)
        slub = _n3(P * np.array([1, 1, 8]), 40)
        c = base * (0.94 + 0.07 * tw)[:, None] * (1 + 0.08 * slub)[:, None]
        return c
    if kind == 'fleece':
        h = _n3(P, 900) * 0.5 + _n3(P, 300) * 0.5
        return base * (1 + 0.09 * h)[:, None]
    if kind == 'knit':
        rib = 0.5 + 0.5 * np.sin(np.arctan2(P[:, 0], P[:, 1]) * 140)
        return base * (0.85 + 0.15 * rib)[:, None]
    h = _n3(P, 700)
    return base * (1 + 0.05 * h)[:, None]


def print_fn(B, style, accent, seed=1):
    """Returns fn(P, base) for the requested print / construction detail."""
    cx = 0.0
    chest = B.J.get('spine-3', B.J['neck'] - np.array([0, 0, 0.18]))
    kz = (B.J['l-knee'][2] + B.J['r-knee'][2]) / 2
    kx = abs(B.J['l-knee'][0])
    ank = B.J['l-ankle'][2]
    rng = np.random.default_rng(seed)
    rips = []
    for leg in (1, -1):
        for zc, w, hgt in [(kz + 0.01, 0.042, 0.028), (kz + 0.17 + rng.uniform(-0.02, 0.02), 0.034, 0.02),
                           (kz - 0.12, 0.028, 0.016), (kz + 0.28, 0.025, 0.012)]:
            rips.append((leg, zc, w, hgt, rng.uniform(-0.012, 0.012)))

    def web(P, base):
        c = fabric(P, base, 'fleece')
        x = P[:, 0] - cx
        z = P[:, 2] - (chest[2] - 0.03)
        front = P[:, 1] < chest[1] + 0.02
        m, d = web_mask(x, z, spokes=12, ring_gap=0.05, width=0.004)
        m &= front
        c[m] = accent
        # thin dark outline makes it read as puff print
        edge = front & (d < 0.0055) & ~m & (np.hypot(x, z) < 0.24)
        c[edge] = c[edge] * 0.6
        return c

    def hoodie(P, base):
        c = fabric(P, base, 'fleece')
        pel = B.J['pelvis']
        x, z = P[:, 0], P[:, 2] - pel[2]
        front = P[:, 1] < chest[1] - 0.02
        w = 0.12 - np.clip(z - 0.05, 0, 1) * 0.35
        inside = front & (np.abs(x) < w) & (z > -0.06) & (z < 0.16)
        edge = front & (np.abs(np.abs(x) - w) < 0.003) & (z > -0.06) & (z < 0.16)
        top = front & (np.abs(z - 0.16) < 0.003) & (np.abs(x) < 0.07)
        c[inside] *= 0.93
        c[edge | top] *= 0.7
        return c

    def tech(P, base):
        c = fabric(P, base, 'fleece')
        x, z = P[:, 0], P[:, 2] - chest[2]
        front = P[:, 1] < chest[1]
        # tech-fleece construction: raglan seams from the collar out to the underarm, a curved
        # chest panel, and curved side panels low on the front (no seams crossing the belly)
        rag = (np.abs(np.abs(x) - (0.055 + (0.2 - z) * 0.75)) < 0.0018) & (z > 0.04) & (z < 0.2)
        arc = (np.abs(np.abs(x) - (0.07 + 2.2 * (z - 0.02) ** 2)) < 0.0018) & (z > -0.06) & (z < 0.1)
        side = (np.abs(np.abs(x) - (0.13 - 0.9 * (z + 0.12) ** 2)) < 0.0018) & (z < -0.04) & (z > -0.3)
        seam = rag | arc | side
        c[seam] *= 0.62
        stitch = seam & (np.sin((z + x) * 2 * math.pi / 0.006) > 0.4)
        c[stitch] *= 1.25
        zip_c = front & (np.abs(x) < 0.004)
        c[zip_c] = np.array([0.12, 0.12, 0.13])
        teeth = zip_c & (np.sin(z * 2 * math.pi / 0.004) > 0)
        c[teeth] = np.array([0.5, 0.5, 0.52])
        pk = front & (np.abs((x - 0.06) - (z - 0.06) * 0.4) < 0.0022) & (x > 0.025) & (x < 0.115) & (z > 0.0) & (z < 0.13)
        c[pk] = np.array([0.45, 0.45, 0.48])
        return c

    def tech_jog(P, base):
        c = fabric(P, base, 'fleece')
        side = np.abs(np.abs(P[:, 0]) - kx - 0.06) < 0.0025
        knee = (np.abs(P[:, 2] - (kz + 0.07)) < 0.002) | (np.abs(P[:, 2] - (kz - 0.06)) < 0.002)
        c[side | knee] *= 0.65
        zp = (np.abs(P[:, 2] - (kz + 0.2) - P[:, 1] * 0.5) < 0.002) & (np.abs(P[:, 2] - kz - 0.2) < 0.06) & \
             (np.abs(P[:, 0]) > kx + 0.02)
        c[zp] = np.array([0.42, 0.42, 0.45])
        return c

    def ripped(P, base):
        c = fabric(P, base, 'denim')
        # whiskering + fades
        fade = np.clip(1 - np.abs(P[:, 2] - (kz + 0.2)) / 0.25, 0, 1)
        c = c * (1 + 0.25 * fade)[:, None]
        sign = np.sign(P[:, 0])
        front = P[:, 1] < 0.0
        for leg, zc, w, hgt, jx in rips:
            lx = (P[:, 0] - leg * kx - jx) / w
            lz = (P[:, 2] - zc) / hgt
            rr = np.hypot(lx, lz) + 0.15 * np.sin(np.arctan2(lz, lx) * 7)
            sel = (sign == leg) & front
            hole = sel & (rr < 0.8)
            ribs = 0.5 + 0.5 * np.sin(P[:, 2] * 2 * math.pi / 0.005)
            c[hole] = np.array([0.012, 0.012, 0.014]) * (1 + 1.2 * ribs[hole, None])
            threads = sel & (rr >= 0.8) & (rr < 1.05) & (np.sin(P[:, 0] * 2 * math.pi / 0.0025) > 0.2)
            c[threads] = np.array([0.82, 0.84, 0.88])
        hem = P[:, 2] < ank + 0.12
        c[hem] *= (0.9 + 0.15 * (np.sin(P[hem, 2] * 2 * math.pi / 0.02) > 0))[:, None]
        return c

    def stars(P, base):
        c = fabric(P, base, 'denim')
        front = P[:, 1] < 0.02
        for (sx, sz, R) in [(0.11, kz + 0.2, 0.034), (-0.1, kz + 0.05, 0.03), (0.09, kz - 0.15, 0.028),
                            (-0.12, kz + 0.28, 0.025), (0.12, kz - 0.02, 0.022), (-0.08, kz - 0.22, 0.02)]:
            m = star_mask(P[:, 0], P[:, 2], sx, sz, R) & front
            c[m] = np.array([0.018, 0.016, 0.016]) * (1 + 0.6 * _n3(P[m], 300)[:, None])
            ring = star_mask(P[:, 0], P[:, 2], sx, sz, R * 1.12) & front & ~m
            c[ring] = np.array([0.75, 0.74, 0.7])
        return c

    def floral(P, base):
        c = fabric(P, base, 'denim')
        m = flower_mask(P[:, 0] + 0.3 * P[:, 1], P[:, 2], 0.06, seed)
        c[m] = c[m] * 0.2 + np.array([0.9, 0.9, 0.86]) * 0.8
        return c

    def camo(P, base):
        # woodland-style camo: four colours, organic blobs with crisp printed edges
        # (domain-warped noise so shapes are irregular, not round smudges)
        wq = np.stack([_n3(P, 7, 11), _n3(P, 7, 23), _n3(P, 7, 37)], 1) * 0.035
        Q = P + wq
        f1 = _n3(Q, 11, 1) + 0.35 * _n3(Q, 27, 2)
        f2 = _n3(Q, 13, 5) + 0.35 * _n3(Q, 31, 6)
        f3 = _n3(Q, 17, 9) + 0.3 * _n3(Q, 41, 10)
        b0 = base if base.ndim == 1 else base.mean(0)
        c = np.tile(b0, (len(P), 1))
        brown = np.array([0.16, 0.11, 0.06])
        dark = b0 * 0.45
        black = np.array([0.025, 0.025, 0.02])
        c[f1 > 0.1] = brown
        c[f2 > 0.18] = dark
        c[f3 > 0.32] = black
        if np.ndim(accent) and np.mean(accent) > 0:
            c[(f1 < -0.38)] = accent * 0.9
        return fabric(P, c, 'cotton')

    def plain(kind):
        return lambda P, base: fabric(P, base, kind)

    f = {'WEB': web, 'TECH': tech, 'TECH_JOG': tech_jog, 'RIPPED': ripped, 'STARPATCH': stars,
         'FLORAL': floral, 'CAMO': camo, 'DENIM': plain('denim'), 'FLEECE': plain('fleece'),
         'COTTON': plain('cotton'), 'KNIT': plain('knit'), 'HOODIE': hoodie}[style]
    return lambda P, base: seams(P, f(P, base), B)


# ======================================================================================
#  CLOTH SIMULATION DRAPE: let garments hang, fold and stack like real fabric
# ======================================================================================

FABRIC_SIM = {  # mass, tension, bending, compression
    'cotton': (0.15, 15.0, 0.08, 15.0),
    'fleece': (0.3, 15.0, 0.6, 15.0),
    'denim': (0.45, 30.0, 6.0, 30.0),
    'knit': (0.25, 10.0, 0.15, 10.0),
}


def _set_pin(ob, mask, name="SY_Pin", weights=None):
    vg = ob.vertex_groups.get(name) or ob.vertex_groups.new(name=name)
    idx = np.nonzero(mask)[0]
    if weights is None:
        vg.add(idx.tolist(), 1.0, 'REPLACE')
    else:
        q = np.round(weights[idx] * 10).astype(int)
        for lv in np.unique(q):
            if lv > 0:
                vg.add(idx[q == lv].tolist(), lv / 10.0, 'REPLACE')
    return vg.name


def _unpose(ob, rig, me):
    """Inverse linear-blend skinning: take a mesh simulated in the posed stance and move every
    vertex back to the rest pose, so the drape is stored rig-ready (it re-poses exactly)."""
    n = len(me.vertices)
    P = np.empty(n * 3)
    me.vertices.foreach_get('co', P)
    P = P.reshape(-1, 3)
    names = {vg.index: vg.name for vg in ob.vertex_groups}
    Mo = np.array(ob.matrix_world)
    Mr = np.array(rig.matrix_world)
    A = np.linalg.inv(Mr) @ Mo                     # object -> armature space
    Ainv = np.linalg.inv(A)
    S = {}
    for pb in rig.pose.bones:
        S[pb.name] = np.array(pb.matrix) @ np.linalg.inv(np.array(pb.bone.matrix_local))
    out = P.copy()
    for i, v in enumerate(me.vertices):
        M = np.zeros((4, 4))
        tw = 0.0
        for g in v.groups:
            nm = names.get(g.group)
            if nm in S and g.weight > 0:
                M += g.weight * S[nm]
                tw += g.weight
        if tw < 1e-6:
            continue
        M /= tw
        pa = A @ np.append(P[i], 1.0)
        try:
            ra = np.linalg.solve(M, pa)
        except np.linalg.LinAlgError:
            continue
        out[i] = (Ainv @ ra)[:3]
    me.vertices.foreach_set('co', out.ravel())
    me.update()


def drape(ob, colliders, pin_fn, fabric='cotton', frames=36, subdivide=True, rig=None):
    """Cloth-sim ob and bake the result into its mesh. With rig given (and posed), the drape is
    simulated on the posed body under gravity, then converted back to rest pose."""
    scene = bpy.context.scene
    posed = rig is not None
    # temporarily disable everything except subdivision (and the armature when draping posed)
    saved = []
    for m in ob.modifiers:
        saved.append((m, m.show_viewport, m.show_render))
        keep_on = (m.type == 'SUBSURF' and subdivide) or (posed and m.type == 'ARMATURE')
        if not keep_on:
            m.show_viewport = False
            m.show_render = False
    # pin group must be computed on the (base) mesh
    me = ob.data
    co = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get('co', co)
    co = co.reshape(-1, 3)
    pin_mask, pin_w = pin_fn(co)
    pname = _set_pin(ob, pin_mask, weights=pin_w)
    cl = ob.modifiers.new("SY_Cloth", 'CLOTH')
    s = cl.settings
    mass, ten, bend, comp = FABRIC_SIM.get(fabric, FABRIC_SIM['cotton'])
    s.quality = 6
    s.mass = mass
    s.tension_stiffness = ten
    s.compression_stiffness = comp
    s.shear_stiffness = ten * 0.5
    s.bending_stiffness = bend
    s.air_damping = 2.0
    s.vertex_group_mass = pname
    s.pin_stiffness = 2.0
    try:
        s.shrink_min = 0.0
    except Exception:
        pass
    cs = cl.collision_settings
    cs.distance_min = 0.006 if posed else 0.005
    cs.use_self_collision = False
    cs.collision_quality = 3
    cl.point_cache.frame_start = 1
    cl.point_cache.frame_end = frames
    added = []
    for c in colliders:
        if c is None:
            continue
        if not any(m.type == 'COLLISION' for m in c.modifiers):
            c.modifiers.new("SY_Collision", 'COLLISION')
            added.append(c)
        # garments are solidified inward by ~4mm, so keep a real gap to whatever is underneath
        c.collision.thickness_outer = 0.005 if posed else 0.004
        c.collision.cloth_friction = 8.0
    f0 = scene.frame_current
    scene.frame_set(1)
    cl.show_viewport = False
    dg = bpy.context.evaluated_depsgraph_get()
    start = bpy.data.meshes.new_from_object(ob.evaluated_get(dg), depsgraph=dg)
    cl.show_viewport = True
    p0 = np.empty(len(start.vertices) * 3)
    start.vertices.foreach_get('co', p0)
    p0 = p0.reshape(-1, 3)
    bpy.data.meshes.remove(start)
    if posed:
        # animate from rest into the stance over the first frames (like posing a sim avatar),
        # so cloth never starts inside the legs/pants, then let it settle under gravity
        target = {pb.name: pb.matrix_basis.copy() for pb in rig.pose.bones}
        dec = {k: m.decompose() for k, m in target.items()}
        ramp = max(10, int(frames * 0.45))

        def set_pose(t):
            for pb in rig.pose.bones:
                loc, rot, scl = dec[pb.name]
                q = Quaternion().slerp(rot, t)
                pb.matrix_basis = Matrix.LocRotScale(loc * t, q, Vector((1, 1, 1)).lerp(scl, t))
        set_pose(0.0)
        scene.frame_set(0)
        scene.frame_set(1)
    for f in range(2, frames + 1):
        if posed:
            t = min(1.0, (f - 1) / ramp)
            set_pose(t * t * (3 - 2 * t))
        scene.frame_set(f)
    if posed:
        for pb in rig.pose.bones:
            pb.matrix_basis = target[pb.name]
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    new = bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=True, depsgraph=dg)
    if len(new.vertices) == len(p0):
        p1 = np.empty(len(new.vertices) * 3)
        new.vertices.foreach_get('co', p1)
        p1 = p1.reshape(-1, 3)
        d = np.linalg.norm(p1 - p0, axis=1)
        bad = d > (0.12 if posed else 0.06)
        e = np.empty(len(new.edges) * 2, np.int64)
        new.edges.foreach_get('vertices', e)
        e = e.reshape(-1, 2)
        L = np.linalg.norm(p1[e[:, 0]] - p1[e[:, 1]], axis=1)
        L0 = np.linalg.norm(p0[e[:, 0]] - p0[e[:, 1]], axis=1)
        stretched = L > np.maximum(L0 * 3.0, 0.02)
        bad[e[stretched].ravel()] = True
        if bad.any():
            # grow the bad region a little and blend it back to the start shape
            for _ in range(2):
                g = bad.copy()
                g[e[:, 0][bad[e[:, 1]]]] = True
                g[e[:, 1][bad[e[:, 0]]]] = True
                bad = g
            p1[bad] = p0[bad] + np.clip(p1[bad] - p0[bad], -0.02, 0.02)
            new.vertices.foreach_set('co', p1.ravel())
            new.update()
    scene.frame_set(f0)
    if posed:
        _unpose(ob, rig, new)
    old = ob.data
    mats = list(old.materials)
    ob.modifiers.remove(cl)
    for m, v, r in saved:
        if m.type == 'SUBSURF' and subdivide:
            ob.modifiers.remove(m)
        else:
            m.show_viewport, m.show_render = v, r
    new.materials.clear()
    for mt in mats:
        new.materials.append(mt)
    ob.data = new
    bpy.data.meshes.remove(old)
    vg = ob.vertex_groups.get(pname)
    if vg:
        ob.vertex_groups.remove(vg)
    for c in added:
        for m in list(c.modifiers):
            if m.type == 'COLLISION' and m.name.startswith("SY_Collision"):
                c.modifiers.remove(m)
    return ob


def drawstrings_on(B, h, rig, coll, name, top_ob, color):
    bvh = _outer_bvh([top_ob])
    if bvh is None:
        return None
    M = h.matrix_world
    neck = B.J['neck']
    paths = []
    for xs in (-0.035, 0.035):
        line = []
        for t in np.linspace(0, 1, 12):
            q = _project_y(bvh, xs * (1 + 0.25 * t), neck[2] - 0.045 - 0.18 * t, M, 0.004)
            if q is not None:
                line.append(q)
        if len(line) > 3:
            paths.append(np.array(line))
    if not paths:
        return None
    me = tube_mesh(paths, [np.full(len(pp), 0.0028) for pp in paths], [rgba(color, len(pp)) for pp in paths],
                   name, sides=5)
    return mesh_object(me, h, rig, coll, 'cotton', {'spine_03': 1.0})


def top_pins(B, style):
    neck = B.J['neck']
    sh = abs(B.J['l-shoulder'][0])
    shz = (B.J['l-shoulder'][2] + B.J['r-shoulder'][2]) / 2

    pel = B.J['pelvis']

    def fn(co):
        yoke = (co[:, 2] > shz - 0.015) & (np.abs(co[:, 0]) < sh * 1.05)
        w = np.clip((co[:, 2] - (shz - 0.05)) / 0.05, 0, 1)
        # the extended hem keeps its tailored hang (a short sim crumples it against the pants)
        # the hem keeps its tailored, level hang (contact with the waistband otherwise shreds it);
        # in posed drape the chest, back, shoulders and sleeves fall freely under gravity
        skirt = np.clip((pel[2] + 0.10 - co[:, 2]) / 0.10, 0, 1) * (np.abs(co[:, 0]) < 0.3)
        w = np.maximum(w, skirt * (0.85 if FREE_DRAPE else 1.0))
        if FREE_DRAPE:
            return yoke | (w > 0.05), np.maximum(yoke.astype(float), w)
        chest = (co[:, 2] > pel[2] + 0.18) & (co[:, 2] < shz) & (np.abs(co[:, 0]) < sh * 0.85)
        w = np.maximum(w, chest * 0.65)
        waist = (co[:, 2] > pel[2] + 0.04) & (co[:, 2] <= pel[2] + 0.18) & (np.abs(co[:, 0]) < 0.3)
        w = np.maximum(w, waist * 0.65)
        return yoke | (w > 0.05), np.maximum(yoke.astype(float), w)
    return fn


def bottom_pins(B, style):
    pel = B.J['pelvis']
    waist = pel[2] + 0.07
    ank = (B.J['l-ankle'][2] + B.J['r-ankle'][2]) / 2

    def fn(co):
        band = co[:, 2] > waist - 0.045
        w = np.clip((co[:, 2] - (waist - 0.08)) / 0.04, 0, 1)
        if style in ('JOGGERS', 'TECH_JOG', 'RIPPED'):
            cuff = co[:, 2] < ank + 0.045
            w = np.maximum(w, cuff.astype(float) * 0.7)
            band |= cuff
        return band | (w > 0.05), np.maximum(band.astype(float) * 0.9, w)
    return fn


# ======================================================================================
#  STRAND-LEVEL HAIR: vectorised noise, baked hair textures, coils, twists, braids, locs
# ======================================================================================

def _hash3(ix, iy, iz, seed=0):
    h = (ix * 73856093) ^ (iy * 19349663) ^ (iz * 83492791) ^ (seed * 2654435761)
    h = (h ^ (h >> 13)) * 1274126177
    return ((h ^ (h >> 16)) & 0xFFFFFF) / float(0xFFFFFF)


def cell_dist(P, size, seed=0):
    """Distance to the nearest jittered feature point (vectorised Worley noise) + that cell's id hash."""
    q = P / size
    base = np.floor(q).astype(np.int64)
    best = np.full(len(P), 9.0)
    bid = np.zeros(len(P))
    for ox in (-1, 0, 1):
        for oy in (-1, 0, 1):
            for oz in (-1, 0, 1):
                c = base + np.array([ox, oy, oz])
                jx = _hash3(c[:, 0], c[:, 1], c[:, 2], seed + 1)
                jy = _hash3(c[:, 0], c[:, 1], c[:, 2], seed + 2)
                jz = _hash3(c[:, 0], c[:, 1], c[:, 2], seed + 3)
                pt = c + np.stack([jx, jy, jz], 1)
                d = np.linalg.norm(q - pt, axis=1)
                m = d < best
                best = np.where(m, d, best)
                bid = np.where(m, _hash3(c[:, 0], c[:, 1], c[:, 2], seed + 9), bid)
    return best * size, bid


def vnoise(P, size, seed=0):
    q = P / size
    b = np.floor(q).astype(np.int64)
    f = q - b
    f = f * f * (3 - 2 * f)
    out = 0
    for ox in (0, 1):
        for oy in (0, 1):
            for oz in (0, 1):
                w = (f[:, 0] if ox else 1 - f[:, 0]) * (f[:, 1] if oy else 1 - f[:, 1]) * (f[:, 2] if oz else 1 - f[:, 2])
                out = out + w * _hash3(b[:, 0] + ox, b[:, 1] + oy, b[:, 2] + oz, seed)
    return out * 2 - 1


def hairline_z(B, P, front=0.27, side=0.12, back=-0.25):
    hc, eye, crown, chin, H = B.head_c, B.eye, B.crown_z, B.chin_z, B.head_h
    rel = P - hc
    ty = np.clip((rel[:, 1] + 0.09) / 0.18, 0, 1)
    sd = smoothstep(0.035, 0.065, np.abs(rel[:, 0]))
    top_line = eye[2] + H * np.interp(ty, [0, 0.35, 0.75, 1.0], [front, front + 0.01, back + 0.08, back])
    side_line = eye[2] + H * np.interp(ty, [0, 0.25, 0.42, 0.55, 0.75, 1.0],
                                       [front, side, side, 0.1, back + 0.04, back])
    return top_line * (1 - sd) + side_line * sd, rel


FADES = {'NONE': (-1, -0.9), 'LOW': (-0.03, 0.17), 'MID': (0.04, 0.29), 'HIGH': (0.13, 0.38)}


def hair_texel_fn(B, style, fade, color, seed=1):
    """Per-texel RGBA for short/scalp styles: coils, fade stubble, crisp edge-up, waves, cornrows."""
    color = np.asarray(color, float)

    def fn(P, base):
        zl, rel = hairline_z(B, P)
        above = P[:, 2] - zl
        hgt = (P[:, 2] - B.eye[2]) / B.head_h
        side = np.clip(smoothstep(0.03, 0.07, np.abs(rel[:, 0])) + smoothstep(0.02, 0.08, rel[:, 1]), 0, 1)
        lo, hi = FADES.get(fade, FADES['NONE'])
        dens = np.where(side > 0.3, smoothstep(lo, hi, hgt), 1.0)
        # coil texture: tiny jittered coils, each a slightly different shade
        d, cid = cell_dist(P, 0.0026, seed)
        coil = smoothstep(0.0016, 0.0003, d)
        shade = 0.55 + 0.5 * cid
        c = color[None, :] * (0.45 + 0.75 * coil * shade)[:, None]
        sheen = smoothstep(0.0004, 0.0, np.abs(d - 0.0009)) * 0.25
        c = c + sheen[:, None] * (color[None, :] * 2 + 0.03)
        # stubble dots for the faded part: density of visible follicles follows the fade
        sd_, _ = cell_dist(P, 0.0014, seed + 5)
        stubble = sd_ < (0.00035 + 0.0006 * dens)
        thin = np.clip(stubble * (0.55 + 0.45 * dens) + dens * 0.35, 0, 1)
        full = smoothstep(0.55, 1.0, dens)          # blend into full coverage, no hard line
        alpha = thin * (1 - full) + full
        c = c * (0.8 + 0.2 * dens)[:, None]          # shorter hair in the fade reads a touch lighter/greyer
        if style == 'WAVES':
            cp = B.head_c + np.array([0, 0.015, B.head_h * 0.5])
            r = np.linalg.norm((P - cp)[:, :2], axis=1) + 0.3 * np.maximum(0, cp[2] - P[:, 2])
            ang = np.arctan2(rel[:, 0], rel[:, 1])
            wv = np.sin(r * 2 * math.pi / 0.0105 + ang * 2 + vnoise(P, 0.02, seed) * 0.8)
            crest = smoothstep(0.2, 0.95, wv)
            trough = smoothstep(-0.2, -0.9, wv)
            c = c * (0.85 + 0.2 * crest - 0.2 * trough)[:, None] + (crest * 0.015)[:, None]
        if style == 'CORNROWS':
            # parts sit halfway between plait centres (-0.07 + k*0.021)
            u = ((rel[:, 0] + 0.07 - 0.0105) / 0.021)
            dpart = np.abs(u - np.round(u)) * 0.021
            part = smoothstep(0.0016, 0.0006, dpart)
            c = c * 0.85
            alpha = np.clip(1.0 - part, 0, 1)
        # crisp barber edge-up with a fine broken edge
        edge = smoothstep(-0.0004, 0.0012, above + 0.0004 * vnoise(P, 0.0012, seed))
        alpha = alpha * edge
        return np.concatenate([np.clip(c, 0, 1), alpha[:, None]], 1)
    return fn


def coil_mesh(roots, normals, color, seed=1, length=(0.010, 0.018), radius=0.0024, wire=0.00085, sides=4,
              turns=(2.0, 3.2), droop=0.15):
    rng = np.random.default_rng(seed)
    paths, radii, cols = [], [], []
    for p, n in zip(roots, normals):
        n = n / max(np.linalg.norm(n), 1e-9)
        a = np.cross(n, [0, 0, 1.0])
        if np.linalg.norm(a) < 1e-3:
            a = np.cross(n, [1.0, 0, 0])
        a /= np.linalg.norm(a)
        b = np.cross(n, a)
        L = rng.uniform(*length)
        T = rng.uniform(*turns)
        ph = rng.uniform(0, 6.28)
        k = 14
        t = np.linspace(0, 1, k)
        th = ph + t * T * 2 * math.pi
        r = radius * (0.6 + 0.4 * t) * rng.uniform(0.8, 1.2)
        axis = n[None, :] * (t * L)[:, None] + np.array([0, 0, -1.0])[None, :] * (droop * L * t ** 2)[:, None]
        pts = p + axis + (np.cos(th)[:, None] * a + np.sin(th)[:, None] * b) * r[:, None]
        paths.append(pts)
        radii.append(np.full(k, wire) * (1 - 0.3 * t))
        cols.append(rgba(color * rng.uniform(0.75, 1.25), k))
    return paths, radii, cols


def twist_paths(center, rad, kind, phase=0.0):
    """Expand one centreline into the strands that make a two-strand twist or a 3-strand braid."""
    n = len(center)
    T = np.gradient(center, axis=0)
    T /= np.maximum(np.linalg.norm(T, axis=1), 1e-9)[:, None]
    up = np.array([0, 0, 1.0])
    Nn = np.cross(T[0], up)
    if np.linalg.norm(Nn) < 1e-6:
        Nn = np.array([1.0, 0, 0])
    Nn /= np.linalg.norm(Nn)
    frames = []
    for i in range(n):
        Nn = Nn - T[i] * (Nn @ T[i])
        Nn /= max(np.linalg.norm(Nn), 1e-9)
        frames.append((Nn.copy(), np.cross(T[i], Nn)))
    s = np.cumsum(np.r_[0, np.linalg.norm(np.diff(center, axis=0), axis=1)])
    out = []
    if kind == 'TWIST':
        for k in range(2):
            pts = []
            for i in range(n):
                a = s[i] / (rad[i] * 3.2) * 2 * math.pi + phase + k * math.pi
                Nf, Bf = frames[i]
                pts.append(center[i] + (Nf * math.cos(a) + Bf * math.sin(a)) * rad[i] * 0.55)
            out.append((np.array(pts), rad * 0.62))
    else:  # 3-strand braid
        for k in range(3):
            pts = []
            for i in range(n):
                a = s[i] / (rad[i] * 4.0) * 2 * math.pi + phase + k * 2 * math.pi / 3
                Nf, Bf = frames[i]
                pts.append(center[i] + Nf * math.sin(a) * rad[i] * 0.6 + Bf * math.sin(2 * a) * rad[i] * 0.3)
            out.append((np.array(pts), rad * 0.55))
    return out


U = sys.modules[__name__]

# --------------------------------------------------------------------------------------
# MPFB access
# --------------------------------------------------------------------------------------

def _mpfb(pkg, key):
    for name in list(sys.modules):
        if name.endswith(pkg):
            return getattr(importlib.import_module(name), key)
    raise RuntimeError("MPFB is not installed/enabled. Install it from Edit > Preferences > Get Extensions.")


class M:
    _ok = False

    @classmethod
    def load(cls):
        if cls._ok:
            return
        cls.HS = _mpfb("mpfb.services.humanservice", "HumanService")
        cls.TS = _mpfb("mpfb.services.targetservice", "TargetService")
        cls.AS = _mpfb("mpfb.services.assetservice", "AssetService")
        cls.LS = _mpfb("mpfb.services.locationservice", "LocationService")
        cls.HOP = _mpfb("mpfb.entities.objectproperties", "HumanObjectProperties")
        cls._ok = True


def hexc(h):
    h = h.lstrip('#')
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return tuple(out)


# --------------------------------------------------------------------------------------
# Look data
# --------------------------------------------------------------------------------------

# The "schoolyard" caricature: broad squarish heads, heavy jutting brows, lidded squinting eyes,
# big noses, wide thin mouths, strong jaws, thick necks. Scaled by the Caricature slider.
CARICATURE = {
    'head-scale-horiz-incr': 0.4, 'head-scale-vert-incr': 0.2, 'head-scale-depth-incr': 0.25,
    'head-square': 0.6, 'head-rectangular': 0.25,
    'chin-width-incr': 0.4, 'chin-bones-incr': 0.6, 'chin-prominent-incr': 0.35, 'chin-height-incr': 0.2,
    'nose-volume-incr': 0.5, 'nose-scale-vert-incr': 0.35, 'nose-point-width-incr': 0.45,
    'nose-hump-incr': 0.25, 'nose-width2-incr': 0.25,
    'eyebrows-trans-down': 0.6, 'eyebrows-trans-forward': 0.8, 'forehead-trans-forward': 0.25,
    'forehead-scale-vert-decr': 0.35,
    'mouth-scale-horiz-incr': 0.4, 'mouth-upperlip-volume-decr': 0.45, 'mouth-lowerlip-volume-decr': 0.15,
    'neck-scale-horiz-incr': 0.3,
}
CARICATURE_SYM = {'eye-height2-decr': 0.45, 'eye-eyefold-down': 0.6, 'eye-bag-incr': 0.45,
                  'eye-scale-decr': 0.15, 'ear-wing-incr': 0.4, 'cheek-bones-incr': 0.5, 'cheek-inner-decr': 0.25}

SKINS = {  # tone -> (male mhmat, female mhmat, ethnicity mix (african, asian, caucasian))
    'LIGHT': ('young_caucasian_male', 'young_caucasian_female', (0, 0, 1)),
    'LIGHT2': ('young_caucasian_male2', 'young_caucasian_female2', (0, 0, 1)),
    'FRECKLED': ('toigo_light_skin_male_freckles', 'toigo_light_skin_female_freckles', (0, 0, 1)),
    'GINGER': ('toigo_light_skin_male_ginger', 'toigo_light_skin_female_ginger', (0, 0, 1)),
    'TAN': ('young_caucasian_male2', 'young_caucasian_female2', (0.15, 0.1, 0.75)),
    'ASIAN': ('young_asian_male', 'young_asian_female', (0, 1, 0)),
    'BROWN': ('young_african_male', 'young_african_female', (0.75, 0, 0.25)),
    'DEEP': ('mindfront_skin_male_african_middleage', 'young_african_female', (1, 0, 0)),
    'DARK': ('young_african_male', 'young_african_female', (1, 0, 0)),
}

HAIR = {'BUZZ': 'short01', 'NEAT': 'culturalibre_hair_02', 'PART': 'short02', 'SLICK': 'short04',
        'SWEEP': 'short03', 'SPIKY': 'culturalibre_hair_05', 'MESSY': 'cortu_short_messy_hair',
        'AFRO': 'afro01', 'LONG': 'long01', 'PONYTAIL': 'ponytail01', 'BOB': 'bob02', 'BALD': None}

BROWS = [(0.25, 'eyebrow006'), (0.5, 'eyebrow003'), (0.75, 'eyebrow008'), (1.01, 'eyebrow009')]

# outfit -> list of (asset, colour role, special)
OUTFITS = {
    'UNIFORM': [('namuhekam_male_polo_shirt', 'top', None), ('toigo_fisherman_sweater', 'outer', 'VEST'),
                ('toigo_wool_pants', 'pants', None)],
    'SWEATER': [('toigo_fisherman_sweater', 'outer', None), ('toigo_wool_pants', 'pants', None)],
    'POLO': [('namuhekam_male_polo_shirt', 'top', None), ('toigo_wool_pants', 'pants', None)],
    'TEE': [('elvs_crude_t-shirt_male', 'top', None), ('cortu_cargo_pants', 'pants', None)],
    'JACKET': [('male_casualsuit05', 'outer', 'JACKET')],
    'DENIM': [('male_casualsuit01', None, None)],
    'STRIPED': [('male_casualsuit03', None, None)],
    'OVERALLS': [('male_worksuit01', None, None)],
}
GIRL_OUTFITS = {
    'UNIFORM': [('namuhekam_male_polo_shirt', 'top', None), ('toigo_fisherman_sweater', 'outer', 'VEST'),
                ('toigo_tiered_mini_skirt', 'pants', None)],
    'SWEATER': [('toigo_fisherman_sweater', 'outer', None), ('toigo_tiered_mini_skirt', 'pants', None)],
    'POLO': [('namuhekam_male_polo_shirt', 'top', None), ('toigo_tiered_mini_skirt', 'pants', None)],
    'TEE': [('joepal_crude_t-shirt_female', 'top', None), ('cortu_jeans_shorts', 'pants', None)],
    'JACKET': [('female_casualsuit01', None, None)],
    'DENIM': [('female_casualsuit02', None, None)],
    'STRIPED': [('female_sportsuit01', None, None)],
    'OVERALLS': [('male_worksuit01', None, None)],
}
SHOES = {'SCHOOL': 'shoes01', 'SNEAKERS': 'shoes03', 'BOOTS': 'toigo_ankle_boots_male', 'WORK': 'shoes02',
         'FLATS': 'toigo_flats', 'NONE': None}
HATS = {'NONE': None, 'NEWSBOY': 'jujube_newsboy_cap', 'FEDORA': 'fedora01'}
GLASSES = {'NONE': None, 'ROUND': 'toigo_round_glasses_leopard', 'LIBRARY': 'frankyaye_glasses_library_male',
           'OPTICAL': 'kwnet_at_optical_glasses'}


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------

def target(h, name, w):
    if abs(w) < 1e-3:
        return
    if name.startswith(('l-', 'r-')):
        sub = {'eye': 'eyes', 'ear': 'ears', 'cheek': 'cheek'}[name.split('-')[1]]
    elif name.startswith('measure-neck'):
        sub = 'neck'
    elif name.startswith('measure'):
        sub = 'torso'
    else:
        sub = name.split('-')[0]
    path = os.path.join(M.LS.get_mpfb_data("targets"), sub, name + '.target.gz')
    if os.path.exists(path):
        M.TS.load_target(h, path, weight=w)


def target_dir(h, sub, name, w):
    if abs(w) < 1e-3:
        return
    path = os.path.join(M.LS.get_mpfb_data("targets"), sub, name + '.target.gz')
    if os.path.exists(path):
        M.TS.load_target(h, path, weight=w)


def apply_hands(h, p, female):
    """Fuller, more solid hands: thicker fingers, a slightly bigger palm, sturdier wrists."""
    t = p.hand_thickness - 0.5          # 0.5 = stock MakeHuman hands
    for s in ('l', 'r'):
        target_dir(h, 'hands', s + '-hand-fingers-diameter-' + ('incr' if t > 0 else 'decr'), min(1.0, abs(t) * 2.7))
        target_dir(h, 'hands', s + '-hand-scale-' + ('incr' if t > 0 else 'decr'), abs(t) * (0.75 if not female else 0.45))
        target_dir(h, 'arms', s + '-lowerarm-fat-' + ('incr' if t > 0 else 'decr'), abs(t) * 0.6)
    target_dir(h, 'hands', 'measure-wrist-circ-' + ('incr' if t > 0 else 'decr'), min(1.0, abs(t) * 1.8))


def target_pm(h, base, value):
    """value>0 -> base-incr, value<0 -> base-decr (or custom pair)."""
    if isinstance(base, tuple):
        pos, neg = base
    else:
        pos, neg = base + '-incr', base + '-decr'
    if value > 0:
        target(h, pos, value)
    elif value < 0:
        target(h, neg, -value)


def sym(h, name, w):
    target(h, 'l-' + name, w)
    target(h, 'r-' + name, w)


def add_asset(h, sub, name, typ):
    if not name:
        return None
    path = M.AS.find_asset_absolute_path(name + '.mhclo', asset_subdir=sub)
    if path is None:
        print("[Schoolyard] missing asset", sub, name)
        return None
    before = set(bpy.data.objects)
    M.HS.add_mhclo_asset(path, h, asset_type=typ)
    new = [o for o in bpy.data.objects if o not in before and o.type == 'MESH']
    return new[0] if new else None


def _image_gain(img):
    try:
        n = img.size[0] * img.size[1]
        if n == 0:
            return 1.0
        px = np.empty(n * 4, np.float32)
        img.pixels.foreach_get(px)
        px = px.reshape(-1, 4)[::97]
        a = px[:, 3] > 0.5
        lum = (px[a, :3] @ np.array([0.2126, 0.7152, 0.0722], np.float32)) if a.any() else np.array([0.5])
        return float(np.clip(0.92 / max(float(lum.mean()), 0.03), 0.5, 8.0))
    except Exception:
        return 1.0


def tint(obj, rgb, keep=0.0, mat_filter=None):
    """Recolour a textured MPFB material: keeps the texture's shading/detail, replaces its hue."""
    if obj is None or rgb is None:
        return
    for slot in obj.material_slots:
        m = slot.material
        if m is None or not m.node_tree or (mat_filter and not mat_filter(m.name)):
            continue
        nt = m.node_tree
        tex = next((n for n in nt.nodes if n.type == 'TEX_IMAGE' and n.name == 'diffuseTexture'), None) \
            or next((n for n in nt.nodes if n.type == 'TEX_IMAGE'), None)
        if tex is None or tex.image is None:
            bsdf = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
            if bsdf:
                bsdf.inputs['Base Color'].default_value = (*rgb, 1)
            continue
        links = [l for l in nt.links if l.from_node == tex and l.from_socket.name == 'Color']
        if not links or nt.nodes.get('SY_Tint'):
            if nt.nodes.get('SY_Tint'):
                nt.nodes['SY_Tint'].inputs[7].default_value = (*[c * nt.nodes['SY_Tint']['gain'] for c in rgb], 1)
            continue
        gain = _image_gain(tex.image)
        hs = nt.nodes.new('ShaderNodeHueSaturation')
        hs.name = 'SY_Gray'
        hs.inputs['Saturation'].default_value = keep
        mix = nt.nodes.new('ShaderNodeMix')
        mix.name = 'SY_Tint'
        mix.data_type = 'RGBA'
        mix.blend_type = 'MULTIPLY'
        mix.inputs[0].default_value = 1.0
        mix['gain'] = gain
        mix.inputs[7].default_value = (*[c * gain for c in rgb], 1)
        nt.links.new(tex.outputs['Color'], hs.inputs['Color'])
        nt.links.new(hs.outputs['Color'], mix.inputs[6])
        for l in links:
            to = l.to_socket
            nt.links.remove(l)
            nt.links.new(mix.outputs[2], to)


# --------------------------------------------------------------------------------------
# Heritage-aware facial features. MPFB's ethnicity macros give the population average;
# this adds individual variation inside measured human ranges (never exaggeration) so
# characters don't all share one template face.
# --------------------------------------------------------------------------------------

def apply_features(h, p, female):
    r = random.Random(p.seed * 7919 + 17)
    af = SKINS[p.skin_tone][2][0]
    def var(lo, hi):
        return r.uniform(lo, hi)
    # sliders are centred at 0.5 -> 0 change; auto variation is added on top
    nose_w = (p.nose_width - 0.5) + (var(-0.25, 0.35) * af if p.auto_features else 0)
    lips = (p.lip_fullness - 0.5) + (var(-0.15, 0.4) * af if p.auto_features else 0)
    bridge = (p.nose_bridge - 0.5) + (var(-0.35, 0.3) * af if p.auto_features else 0)
    face_w = (p.face_width - 0.5) + (var(-0.1, 0.3) * af if p.auto_features else 0)
    target_pm(h, 'nose-flaring', nose_w * 0.9)
    target_pm(h, ('nose-nostrils-width-incr', 'nose-nostrils-width-decr'), nose_w * 0.7)
    target_pm(h, 'nose-scale-horiz', nose_w * 0.5)
    target_pm(h, 'nose-point-width', nose_w * 0.5)
    target_pm(h, ('nose-hump-incr', 'nose-hump-decr'), bridge * 0.6)
    target_pm(h, 'nose-scale-depth', bridge * 0.5)
    target_pm(h, ('mouth-upperlip-volume-incr', 'mouth-upperlip-volume-decr'), lips * 0.9)
    target_pm(h, ('mouth-lowerlip-volume-incr', 'mouth-lowerlip-volume-decr'), lips * 0.9)
    target_pm(h, ('mouth-trans-forward', 'mouth-trans-backward'), lips * 0.35)
    target_pm(h, 'mouth-scale-horiz', lips * 0.3)
    target_pm(h, 'head-scale-horiz', face_w * 0.5)
    for sd in ('l', 'r'):
        target_pm(h, (sd + '-cheek-bones-incr', sd + '-cheek-bones-decr'), face_w * 0.6)
    if p.auto_features:
        target_pm(h, 'head-scale-vert', var(-0.25, 0.25))
        target_pm(h, 'chin-width', var(-0.3, 0.3))
        target_pm(h, 'chin-height', var(-0.3, 0.3))
        for sd in ('l', 'r'):
            pass
        target_pm(h, ('head-oval', 'head-round'), var(-0.4, 0.4))
    if p.auto_features and af > 0.3:
        target(h, 'forehead-nubian-incr', var(0.0, 0.35) * af)
        target(h, 'chin-prominent-decr', var(0.0, 0.25) * af)


# --------------------------------------------------------------------------------------
# Realistic skin: rich albedo (no ashiness), per-tone subsurface, pores + grain,
# oily T-zone roughness/sheen, natural tone variation. Zone masks live in a vertex
# colour so they also export to a game engine.
# --------------------------------------------------------------------------------------

SKIN_LOOK = {  # tone: (saturation, value, hue shift, sss weight, sss radius scale)
    'LIGHT': (0.97, 0.97, 0.5, 0.25, 1.0), 'LIGHT2': (0.97, 0.97, 0.5, 0.25, 1.0),
    'FRECKLED': (1.05, 0.97, 0.5, 0.25, 1.0), 'GINGER': (1.0, 0.98, 0.5, 0.28, 1.0),
    'TAN': (1.18, 0.74, 0.497, 0.2, 0.9), 'ASIAN': (1.0, 0.98, 0.5, 0.22, 0.9),
    'BROWN': (0.92, 1.02, 0.495, 0.15, 0.7), 'DARK': (0.9, 1.04, 0.495, 0.1, 0.55),
    'DEEP': (0.88, 0.97, 0.495, 0.08, 0.5),
}


def skin_zones(h):
    """Vertex colour 'SkinZones': R=oiliness (T-zone), G=pore size, B=deepened tone (eyes, knuckles, knees, lips)."""
    B = U.Body(h)
    try:
        co, n = B.co, len(B.co)
        eye = B.eye
        H = B.head_h
        head = B.w('head')
        rel = co - eye
        front = smoothstep(0.02, -0.04, rel[:, 1] / H * 0.24)
        tz_fore = np.exp(-((rel[:, 0] / (0.05 * H / 0.24)) ** 2 + ((rel[:, 2] - 0.05 * H / 0.24) / (0.04 * H / 0.24)) ** 2))
        tz_nose = np.exp(-((rel[:, 0] / (0.018 * H / 0.24)) ** 2 + ((rel[:, 2] + 0.03 * H / 0.24) / (0.04 * H / 0.24)) ** 2))
        tz_chin = np.exp(-((rel[:, 0] / (0.025 * H / 0.24)) ** 2 + ((rel[:, 2] + 0.105 * H / 0.24) / (0.02 * H / 0.24)) ** 2))
        oil = np.clip((tz_fore + tz_nose * 1.2 + tz_chin) * front * head, 0, 1)
        pores = np.clip(0.35 + 0.65 * (tz_nose + 0.6 * np.exp(-(((np.abs(rel[:, 0]) - 0.035 * H / 0.24) / (0.025 * H / 0.24)) ** 2
                                                               + ((rel[:, 2] + 0.03 * H / 0.24) / (0.03 * H / 0.24)) ** 2))) * front, 0, 1)
        deep = np.zeros(n)
        for side in ('l', 'r'):
            e = B.J.get(side + '-eye')
            if e is not None:
                d = np.linalg.norm(co - e, axis=1)
                deep = np.maximum(deep, np.exp(-(d / (0.022 * H / 0.24)) ** 2) * 0.9)
            for j in (side + '-knee', side + '-elbow'):
                if j in B.J:
                    deep = np.maximum(deep, np.exp(-(np.linalg.norm(co - B.J[j], axis=1) / 0.045) ** 2) * 0.7)
        knuck = B.wprefix('index_01', 'middle_01', 'ring_01', 'pinky_01', 'thumb_02')
        deep = np.maximum(deep, np.clip(knuck, 0, 1) * 0.6)
        lips = B.w('lips') if 'lips' in B.gi else np.zeros(n)
        deep = np.maximum(deep, np.clip(lips, 0, 1) * 0.5)
        col = np.stack([oil, pores, np.clip(deep, 0, 1), np.ones(n)], 1).astype(np.float32)
        me = h.data
        a = me.color_attributes.get('SkinZones') or me.color_attributes.new('SkinZones', 'FLOAT_COLOR', 'POINT')
        a.data.foreach_set('color', col.ravel())
    finally:
        B.free()


def realistic_skin(h, tone, strength=1.0):
    sat, val, hue, sssw, sssr = SKIN_LOOK.get(tone, SKIN_LOOK['LIGHT'])
    for slot in h.material_slots:
        m = slot.material
        if not m or not m.node_tree or m.node_tree.nodes.get('SY_Real'):
            continue
        nt = m.node_tree
        bsdf = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        tex = next((n for n in nt.nodes if n.type == 'TEX_IMAGE'), None)
        if bsdf is None or tex is None:
            continue
        mark = nt.nodes.new('NodeFrame')
        mark.name = 'SY_Real'
        lname = m.name.lower()
        if any(k in lname for k in ('eye', 'brow', 'lash', 'teeth', 'tongue', 'nail')):
            continue
        # colour: rich, never ashy; deepened tone in zones; low-frequency mottling
        base_link = next((l for l in nt.links if l.to_socket == bsdf.inputs['Base Color']), None)
        src = base_link.from_socket if base_link else tex.outputs['Color']
        hs = nt.nodes.new('ShaderNodeHueSaturation')
        hs.inputs['Hue'].default_value = hue
        hs.inputs['Saturation'].default_value = 1 + (sat - 1) * strength
        hs.inputs['Value'].default_value = 1 + (val - 1) * strength
        nt.links.new(src, hs.inputs['Color'])
        zones = nt.nodes.new('ShaderNodeVertexColor')
        zones.layer_name = 'SkinZones'
        sep = nt.nodes.new('ShaderNodeSeparateColor')
        nt.links.new(zones.outputs['Color'], sep.inputs['Color'])
        deep = nt.nodes.new('ShaderNodeMix')
        deep.data_type = 'RGBA'
        deep.blend_type = 'MULTIPLY'
        deep.inputs[7].default_value = (0.78, 0.7, 0.68, 1)
        mfac = nt.nodes.new('ShaderNodeMath')
        mfac.name = 'SY_deepfac'
        mfac.operation = 'MULTIPLY'
        mfac.inputs[1].default_value = 0.55 * strength
        nt.links.new(sep.outputs['Blue'], mfac.inputs[0])
        nt.links.new(mfac.outputs[0], deep.inputs[0])
        nt.links.new(hs.outputs['Color'], deep.inputs[6])
        coord = nt.nodes.new('ShaderNodeTexCoord')
        mott = nt.nodes.new('ShaderNodeTexNoise')
        mott.inputs['Scale'].default_value = 25.0
        nt.links.new(coord.outputs['Object'], mott.inputs['Vector'])
        mott_mix = nt.nodes.new('ShaderNodeMix')
        mott_mix.data_type = 'RGBA'
        mott_mix.blend_type = 'OVERLAY'
        mott_mix.inputs[0].default_value = 0.12 * strength
        nt.links.new(deep.outputs[2], mott_mix.inputs[6])
        nt.links.new(mott.outputs['Fac'], mott_mix.inputs[7])
        nt.links.new(mott_mix.outputs[2], bsdf.inputs['Base Color'])
        # subsurface tuned per tone (translucency matters less on deep skin)
        for key, valx in (('Subsurface Weight', sssw * strength), ('Subsurface Scale', 0.006 * sssr)):
            if key in bsdf.inputs:
                bsdf.inputs[key].default_value = valx
        if 'Subsurface Radius' in bsdf.inputs:
            bsdf.inputs['Subsurface Radius'].default_value = (1.0, 0.38, 0.22)
        # roughness: 0.48 baseline, oily T-zone down to ~0.3, plus sheen/coat
        rmap = nt.nodes.new('ShaderNodeMapRange')
        rmap.inputs['To Min'].default_value = 0.55
        rmap.inputs['To Max'].default_value = 0.4
        nt.links.new(sep.outputs['Red'], rmap.inputs['Value'])
        nt.links.new(rmap.outputs['Result'], bsdf.inputs['Roughness'])
        for key, valx in (('Specular IOR Level', 0.45), ('Coat Weight', 0.04 * strength), ('Coat Roughness', 0.45),
                          ('Sheen Weight', 0.03 * strength), ('Sheen Roughness', 0.4)):
            if key in bsdf.inputs:
                bsdf.inputs[key].default_value = valx
        # pores (bigger on nose/cheeks) + fine grain
        vor = nt.nodes.new('ShaderNodeTexVoronoi')
        vor.inputs['Scale'].default_value = 1100.0
        nt.links.new(coord.outputs['Object'], vor.inputs['Vector'])
        grain = nt.nodes.new('ShaderNodeTexNoise')
        grain.inputs['Scale'].default_value = 2600.0
        grain.inputs['Detail'].default_value = 4.0
        nt.links.new(coord.outputs['Object'], grain.inputs['Vector'])
        pmul = nt.nodes.new('ShaderNodeMath')
        pmul.operation = 'MULTIPLY'
        nt.links.new(vor.outputs['Distance'], pmul.inputs[0])
        nt.links.new(sep.outputs['Green'], pmul.inputs[1])
        hsum = nt.nodes.new('ShaderNodeMath')
        hsum.operation = 'MULTIPLY_ADD'
        nt.links.new(grain.outputs['Fac'], hsum.inputs[0])
        hsum.inputs[1].default_value = 0.35
        nt.links.new(pmul.outputs[0], hsum.inputs[2])
        bump = nt.nodes.new('ShaderNodeBump')
        bump.name = 'SY_bump'
        bump.inputs['Strength'].default_value = 0.22 * strength
        bump.inputs['Distance'].default_value = 0.0004
        nt.links.new(hsum.outputs[0], bump.inputs['Height'])
        old_n = next((l for l in nt.links if l.to_socket == bsdf.inputs['Normal']), None)
        if old_n:
            nt.links.new(old_n.from_socket, bump.inputs['Normal'])
        nt.links.new(bump.outputs['Normal'], bsdf.inputs['Normal'])


def fix_eyes(obj):
    """MPFB's default eye texture reads reddish; calm it down to a natural brown."""
    if obj is None:
        return
    for slot in obj.material_slots:
        m = slot.material
        if not m or not m.node_tree or m.node_tree.nodes.get('SY_Eye'):
            continue
        nt = m.node_tree
        tex = next((n for n in nt.nodes if n.type == 'TEX_IMAGE'), None)
        if tex is None:
            continue
        links = [l for l in nt.links if l.from_node == tex and l.from_socket.name == 'Color']
        hs = nt.nodes.new('ShaderNodeHueSaturation')
        hs.name = 'SY_Eye'
        hs.inputs['Hue'].default_value = 0.505
        hs.inputs['Saturation'].default_value = 0.7
        hs.inputs['Value'].default_value = 0.62
        nt.links.new(tex.outputs['Color'], hs.inputs['Color'])
        for l in links:
            to = l.to_socket
            nt.links.remove(l)
            nt.links.new(hs.outputs['Color'], to)
        bsdf = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if bsdf:
            bsdf.inputs['Roughness'].default_value = 0.08


def warm_skin(obj, amount):
    """Push MPFB skins a little toward the saturated, warm painted skin of PS2-era games."""
    for slot in obj.material_slots:
        m = slot.material
        if not m or not m.node_tree or m.node_tree.nodes.get('SY_Warm'):
            continue
        nt = m.node_tree
        tex = next((n for n in nt.nodes if n.type == 'TEX_IMAGE'), None)
        if tex is None:
            continue
        links = [l for l in nt.links if l.from_node == tex and l.from_socket.name == 'Color']
        if not links:
            continue
        hs = nt.nodes.new('ShaderNodeHueSaturation')
        hs.name = 'SY_Warm'
        hs.inputs['Hue'].default_value = 0.49
        hs.inputs['Saturation'].default_value = 1.0 + 0.35 * amount
        hs.inputs['Value'].default_value = 1.0 - 0.06 * amount
        nt.links.new(tex.outputs['Color'], hs.inputs['Color'])
        for l in links:
            to = l.to_socket
            nt.links.remove(l)
            nt.links.new(hs.outputs['Color'], to)


def cut_vest(obj, rig, vneck_depth):
    """Turn a sweater into a sweater vest: delete sleeve faces (weighted to arm bones) and cut a V-neck."""
    if obj is None:
        return
    me = obj.data
    arm_groups = {g.index for g in obj.vertex_groups if g.name.startswith(('upperarm', 'lowerarm', 'hand'))}
    cla = {g.index for g in obj.vertex_groups if g.name.startswith('clavicle')}
    n = len(me.vertices)
    armw = np.zeros(n)
    claw = np.zeros(n)
    for v in me.vertices:
        for g in v.groups:
            if g.group in arm_groups:
                armw[v.index] += g.weight
            elif g.group in cla:
                claw[v.index] += g.weight
    co = np.array([v.co[:] for v in me.vertices])
    # width of the torso at shoulder height: anything clearly outboard is sleeve
    zs = co[:, 2]
    top = zs.max()
    kill_v = armw > 0.25
    # V-neck: front (-Y) vertices near the top centre
    collar_h = 0.05
    kill_v |= zs > top - collar_h
    if vneck_depth > 0:
        neck_z = top - collar_h
        depth = vneck_depth * (top - zs.min())
        front = co[:, 1] < np.median(co[:, 1])
        dz = neck_z - zs
        vshape = (dz > -0.01) & (dz < depth) & (np.abs(co[:, 0]) < (depth - dz) * 0.55 + 0.02) & front
        kill_v |= vshape
    kill = []
    for p in me.polygons:
        if sum(kill_v[i] for i in p.vertices) >= 2:
            kill.append(p.index)
    if not kill:
        return
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.faces[i] for i in kill], context='FACES')
    loose = [v for v in bm.verts if not v.link_faces]
    bmesh.ops.delete(bm, geom=loose, context='VERTS')
    bm.to_mesh(me)
    bm.free()
    me.update()
    # sweater vests sit a touch further out over the polo
    disp = obj.modifiers.new("SY_OverShirt", 'DISPLACE')
    disp.mid_level = 0.0
    disp.strength = 0.018
    sol = obj.modifiers.new("SY_Thickness", 'SOLIDIFY')
    sol.thickness = 0.005
    sol.offset = 1.0
    # put the push right after the armature so it follows the pose
    try:
        with bpy.context.temp_override(object=obj):
            bpy.ops.object.modifier_move_to_index(modifier=disp.name, index=1)
    except Exception:
        pass


def collect(h):
    objs = [h]
    for o in bpy.data.objects:
        p = o.parent
        while p is not None:
            if p == h or (p.type == 'ARMATURE' and h.parent == p):
                objs.append(o)
                break
            p = p.parent
    if h.parent:
        objs.append(h.parent)
        objs += [o for o in h.parent.children_recursive if o not in objs]
    return list(dict.fromkeys(objs))


# --------------------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------------------

# --- display stance (pose only; rest pose stays A-pose for export/rigging) ---
import math
from mathutils import Vector, Quaternion, Matrix

def _aim(rig, name, d, twist=0.0):
    pb = rig.pose.bones.get(name)
    if pb is None: return
    bpy.context.view_layer.update()
    M = pb.matrix.copy()
    head = M.translation.copy()
    cur = (M.to_3x3() @ Vector((0, 1, 0))).normalized()
    q = cur.rotation_difference(Vector(d).normalized())
    if twist:
        q = Quaternion(Vector(d).normalized(), twist) @ q
    R = Matrix.Translation(head) @ q.to_matrix().to_4x4() @ Matrix.Translation(-head)
    pb.matrix = R @ M

def _rot_world(rig, name, axis, ang):
    pb = rig.pose.bones.get(name)
    if pb is None: return
    bpy.context.view_layer.update()
    M = pb.matrix.copy(); head = M.translation.copy()
    R = Matrix.Translation(head) @ Matrix.Rotation(ang, 4, Vector(axis)) @ Matrix.Translation(-head)
    pb.matrix = R @ M

def _curl(rig, name, ang):
    pb = rig.pose.bones.get(name)
    if pb is None: return
    pb.rotation_mode = 'QUATERNION'
    pb.rotation_quaternion = Quaternion((1, 0, 0), ang) @ pb.rotation_quaternion

def apply_stance(rig, style='RELAXED', seed=0, female=False):
    for pb in rig.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
    if style == 'A_POSE':
        return
    import random
    r = random.Random(seed)
    out = 0.215 if not female else 0.15
    for s, sx in (('l', 1), ('r', -1)):
        _rot_world(rig, 'clavicle_' + s, (0, 1, 0), sx * math.radians(14))   # drop + round the shoulders (spreads the arm rotation)
        _aim(rig, 'upperarm_' + s, (sx * out, 0.03, -1.0))
        _aim(rig, 'lowerarm_' + s, (sx * (out * 0.5), -0.32 - 0.1 * r.random(), -1.0))
        _aim(rig, 'hand_' + s, (sx * 0.02, -0.12, -1.0))
        for f, a in (('index', 0.25), ('middle', 0.35), ('ring', 0.42), ('pinky', 0.5)):
            for k in ('01', '02', '03'):
                _curl(rig, '%s_%s_%s' % (f, k, s), a * (0.6 if k == '01' else 1.0))
        _curl(rig, 'thumb_02_' + s, 0.2); _curl(rig, 'thumb_03_' + s, 0.2)
    bpy.context.view_layer.update()
    # narrower, natural stance with weight on one leg
    w = 1 if r.random() < 0.5 else -1
    for s, sx in (('l', 1), ('r', -1)):
        relaxed = (sx == w)
        _aim(rig, 'thigh_' + s, (sx * 0.035, -0.10 if relaxed else -0.07, -1.0))
        _aim(rig, 'calf_' + s, (sx * 0.05, 0.11 if relaxed else 0.07, -1.0))
        _aim(rig, 'foot_' + s, (sx * 0.25, -1.0, -0.35))
    _rot_world(rig, 'pelvis', (0, 1, 0), w * math.radians(2.5))
    _rot_world(rig, 'spine_02', (0, 1, 0), -w * math.radians(2.5))
    _rot_world(rig, 'spine_03', (1, 0, 0), math.radians(-2))
    _rot_world(rig, 'head', (0, 0, 1), math.radians(r.uniform(-8, 8)))
    _rot_world(rig, 'head', (1, 0, 0), math.radians(-3))
    bpy.context.view_layer.update()



# --------------------------------------------------------------------------------------
# Painted skin maps (Bully / GTA V style): colour zones, stubble, brows, pores, wrinkles,
# oily/dry roughness -- baked into image textures so they survive export to a game engine.
# --------------------------------------------------------------------------------------

def _skin_raster(me, co, res, vmask, attrs):
    """Texels of the body UV layout -> (pix, rest position, interpolated per-vertex attrs)."""
    me.calc_loop_triangles()
    uvl = me.uv_layers.active
    nt = len(me.loop_triangles)
    tl = np.empty(nt * 3, np.int64)
    me.loop_triangles.foreach_get('loops', tl)
    tv = np.empty(nt * 3, np.int64)
    me.loop_triangles.foreach_get('vertices', tv)
    tl = tl.reshape(-1, 3)
    tv = tv.reshape(-1, 3)
    keep = vmask[tv].all(1)
    tl, tv = tl[keep], tv[keep]
    uv = np.empty(len(me.loops) * 2)
    uvl.data.foreach_get('uv', uv)
    uv = uv.reshape(-1, 2) * res
    A, Bv, Cv = uv[tl[:, 0]], uv[tl[:, 1]], uv[tl[:, 2]]
    mn = np.floor(np.minimum(np.minimum(A, Bv), Cv)).astype(int)
    mx = np.ceil(np.maximum(np.maximum(A, Bv), Cv)).astype(int)
    pix, pos, att = [], [], []
    for t in range(len(tl)):
        x0, y0 = mn[t]
        x1, y1 = mx[t]
        if x1 - x0 > 300 or y1 - y0 > 300:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
        px = xs.ravel() + 0.5
        py = ys.ravel() + 0.5
        a, b, c = A[t], Bv[t], Cv[t]
        den = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(den) < 1e-12:
            continue
        w0 = ((b[1] - c[1]) * (px - c[0]) + (c[0] - b[0]) * (py - c[1])) / den
        w1 = ((c[1] - a[1]) * (px - c[0]) + (a[0] - c[0]) * (py - c[1])) / den
        w2 = 1 - w0 - w1
        ok = (w0 >= -0.03) & (w1 >= -0.03) & (w2 >= -0.03)
        if not ok.any():
            continue
        w = np.stack([w0[ok], w1[ok], w2[ok]], 1)
        vi = tv[t]
        pos.append(w @ co[vi])
        att.append(w @ attrs[vi])
        xi = np.clip(xs.ravel()[ok], 0, res - 1)
        yi = np.clip(ys.ravel()[ok], 0, res - 1)
        pix.append(yi * res + xi)
    pix = np.concatenate(pix)
    pos = np.concatenate(pos)
    att = np.concatenate(att)
    # one sample per texel
    _, first = np.unique(pix, return_index=True)
    return pix[first], pos[first], att[first]


def _img_from(vals, pix, res, name, srgb=True):
    ch = vals.shape[1] if vals.ndim == 2 else 1
    v = vals.reshape(len(pix), ch)
    img = np.zeros((res, res, ch))
    filled = np.zeros((res, res), bool)
    yy, xx = np.divmod(pix, res)
    img[yy, xx] = v
    filled[yy, xx] = True
    img = U._dilate(img, filled, iters=8)
    if ch == 1:
        img = np.repeat(img, 3, 2)
    if srgb:
        lin = np.clip(img, 0, 1)
        img = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(lin, 1 / 2.4) - 0.055)
    rgba_ = np.concatenate([np.clip(img, 0, 1), np.ones((res, res, 1))], 2).astype(np.float32)
    import uuid
    im = bpy.data.images.new(name + "_" + uuid.uuid4().hex[:5], res, res, alpha=False)
    if not srgb:
        im.colorspace_settings.name = 'Non-Color'     # set before writing: changing it regenerates the buffer
    im.pixels.foreach_set(rgba_.ravel())
    im.pack()
    return im


def _gauss(d, r):
    return np.exp(-(d / r) ** 2)


def _seg_dist(P, a, b):
    ab = b - a
    t = np.clip(((P - a) @ ab) / max(ab @ ab, 1e-12), 0, 1)
    return np.linalg.norm(P - (a + t[:, None] * ab), axis=1), t


SKIN_PAINT = {   # redness, pigment-darkening, stubble tint, highlight, freckles
    'LIGHT': (0.28, 0.45, (0.62, 0.66, 0.72), 0.05, 0.0),
    'LIGHT2': (0.28, 0.45, (0.62, 0.66, 0.72), 0.05, 0.0),
    'FRECKLED': (0.25, 0.45, (0.66, 0.6, 0.55), 0.05, 1.0),
    'GINGER': (0.27, 0.42, (0.7, 0.56, 0.45), 0.05, 0.7),
    'TAN': (0.18, 0.55, (0.6, 0.6, 0.62), 0.06, 0.0),
    'ASIAN': (0.16, 0.5, (0.58, 0.6, 0.64), 0.05, 0.0),
    'BROWN': (0.08, 0.7, (0.62, 0.6, 0.6), 0.07, 0.0),
    'DARK': (0.05, 0.75, (0.66, 0.64, 0.64), 0.08, 0.0),
    'DEEP': (0.04, 0.75, (0.7, 0.68, 0.68), 0.08, 0.0),
}


def paint_skin(h, p, female, res=2048):
    """Paint a full skin set for this character and hook it into the skin materials."""
    tone = p.skin_tone
    red_k, pig_k, stub_tint, hi_k, frk = SKIN_PAINT.get(tone, SKIN_PAINT['LIGHT'])
    stubble = 0.0 if female else p.stubble
    B = U.Body(h)
    try:
        co = B.co
        n = len(co)
        H = B.head_h
        s = H / 0.22
        eye = B.eye
        J = B.J
        vmask = B.isbody | (B.w('lips') > 0) | (B.w('ears') > 0)
        knuck = B.wprefix('index_02', 'middle_02', 'ring_02', 'pinky_02', 'index_01', 'middle_01', 'ring_01', 'pinky_01')
        attrs = np.stack([B.w('lips'), B.w('ears'), B.w('head'), np.clip(knuck, 0, 1),
                          B.w('fingernails'), B.w('nipple')], 1)
        pix, P, A = _skin_raster(h.data, co, res, vmask, attrs)
    finally:
        B.free()
    lips, ears, headw, kn, nails, nip = (A[:, i] for i in range(6))
    r = P - eye
    face = (headw > 0.5) & (r[:, 1] < 0.03 * s)
    front = smoothstep(0.03 * s, -0.03 * s, r[:, 1])
    # --- landmarks ------------------------------------------------------------------
    mouth = J.get('mouth', eye + np.array([0, -0.01, -0.07 * s]))
    nose_tip = eye + np.array([0.0, -0.055 * s, -0.04 * s])
    hm = face & (np.abs(r[:, 0]) < 0.012 * s) & (r[:, 2] < -0.01 * s) & (r[:, 2] > -0.06 * s)
    if hm.any():
        nose_tip = P[hm][np.argmin(P[hm][:, 1])]
    el, er_ = J.get('l-eye', eye + np.array([0.032 * s, 0, 0])), J.get('r-eye', eye - np.array([0.032 * s, 0, 0]))
    # --- colour fields ---------------------------------------------------------------
    red = np.zeros(len(P))
    red += _gauss(np.linalg.norm(P - nose_tip, axis=1), 0.016 * s) * 0.6
    for sx in (1, -1):
        cheek = eye + np.array([sx * 0.04 * s, -0.035 * s, -0.035 * s])
        red += _gauss(np.linalg.norm((P - cheek) * np.array([1, 1.6, 1.2]), axis=1), 0.024 * s) * 0.7
        ala = nose_tip + np.array([sx * 0.016 * s, 0.01 * s, 0.003 * s])
        red += _gauss(np.linalg.norm(P - ala, axis=1), 0.007 * s) * 0.6
    red = red * front * face
    red += ears * 0.7 + lips * 0.8 + kn * 0.6
    for j in ('l-elbow', 'r-elbow', 'l-knee', 'r-knee'):
        if j in J:
            red += _gauss(np.linalg.norm(P - J[j], axis=1), 0.04) * 0.4
    red = np.clip(red, 0, 1)

    dark = np.zeros(len(P))
    for e, sx in ((el, 1), (er_, -1)):
        d = np.linalg.norm((P - e) * np.array([1.0, 1.0, 1.35]), axis=1)
        socket = _gauss(d, 0.021 * s) * (1 - _gauss(d, 0.011 * s) * 0.3)
        under = _gauss(np.linalg.norm(P - (e + np.array([0.003 * sx * s, -0.008 * s, -0.016 * s])), axis=1), 0.011 * s)
        dark += socket * 1.0 + under * 0.6
        # nasolabial fold: from the nose wing down to the mouth corner
        a = nose_tip + np.array([sx * 0.019 * s, 0.012 * s, 0.0])
        b = mouth + np.array([sx * 0.03 * s, 0.0, -0.004 * s])
        dl, tt = _seg_dist(P, a, b)
        dark += _gauss(dl, 0.0035 * s) * 0.45 * np.sin(np.pi * tt) * front
        dark += _gauss(np.linalg.norm(P - (mouth + np.array([sx * 0.026 * s, -0.003 * s, 0.0])), axis=1), 0.005 * s) * 0.5
    for sx in (1, -1):
        nos = nose_tip + np.array([sx * 0.011 * s, 0.006 * s, -0.007 * s])
        dark += _gauss(np.linalg.norm(P - nos, axis=1), 0.005 * s) * 0.7
    dark += _gauss(np.abs(r[:, 0]), 0.02 * s) * _gauss(P[:, 2] - (mouth[2] - 0.016 * s), 0.006 * s) * front * 0.45
    dark += ears * 0.35
    lip_edge = np.clip(1 - np.abs(lips - 0.5) * 2.5, 0, 1) * (lips > 0.05)
    dark += lip_edge * 0.6
    dark += kn * 0.7 * (pig_k > 0.6)
    for j in ('l-elbow', 'r-elbow', 'l-knee', 'r-knee'):
        if j in J:
            dark += _gauss(np.linalg.norm(P - J[j], axis=1), 0.035) * (0.6 if pig_k > 0.6 else 0.2)
    neck = J.get('neck')
    if neck is not None:
        dn = np.abs(P[:, 2] - (neck[2] + 0.02))
        dark += _gauss(dn, 0.004) * (np.abs(P[:, 0]) < 0.06) * (P[:, 1] < neck[1]) * 0.3
    dark = np.clip(dark, 0, 1)

    high = np.zeros(len(P))
    high += _gauss(np.abs(r[:, 0]), 0.008 * s) * smoothstep(-0.045 * s, -0.005 * s, r[:, 2]) * smoothstep(0.03 * s, 0.0, r[:, 2])
    high += _gauss(np.linalg.norm(r * np.array([0.6, 1, 1]) - np.array([0, -0.02 * s, 0.06 * s]), axis=1), 0.03 * s) * 0.7
    for sx in (1, -1):
        high += _gauss(np.linalg.norm(P - (eye + np.array([sx * 0.045 * s, -0.025 * s, -0.018 * s])), axis=1), 0.013 * s) * 0.8
    high = np.clip(high * front * face, 0, 1)

    # stubble zone: jaw, chin, upper lip, lower cheeks
    jaw = J.get('jaw', mouth - np.array([0, 0, 0.03 * s]))
    zone = face & (r[:, 2] < -0.04 * s)
    zone_f = zone * smoothstep(-0.04 * s, -0.062 * s, r[:, 2])
    upper_lip = _gauss(np.abs(r[:, 0]), 0.022 * s) * _gauss(P[:, 2] - (mouth[2] + 0.009 * s), 0.006 * s) * front
    cheek_line = smoothstep(0.075 * s, 0.05 * s, np.abs(r[:, 0]))
    sz = np.clip((zone_f * cheek_line + upper_lip) * (1 - smoothstep(0.1, 0.6, lips)), 0, 1)
    chin_z = mouth[2] - 0.048 * s
    sz *= smoothstep(chin_z - 0.03 * s, chin_z - 0.005 * s, P[:, 2])     # fades out under the chin
    dots, _ = U.cell_dist(P, 0.0011, seed=31)
    hairs = np.clip(1 - dots / 0.00045, 0, 1)
    stub = np.clip(sz * stubble, 0, 1)

    # eyebrows: painted hair strokes along an arch above each eye
    brow = np.zeros(len(P))
    for e, sx in ((el, 1), (er_, -1)):
        q = P - e
        u = (q[:, 0] * sx) / (0.034 * s)                 # -0.6 inner .. 1.0 outer
        zc = 0.019 * s + 0.007 * s * np.sin(np.clip((u + 0.6) / 1.6, 0, 1) * np.pi * 0.9)
        thick = (0.0055 - 0.0025 * np.clip(u, 0, 1)) * s
        band = _gauss(q[:, 2] - zc, thick) * smoothstep(-0.75, -0.55, u) * smoothstep(1.15, 0.95, u)
        stroke = 0.5 + 0.5 * np.sin((q[:, 2] * 1.8 - q[:, 0] * sx * 0.6) * 2 * np.pi / 0.0011 + U.vnoise(P, 0.002, 7) * 4)
        brow += band * (0.55 + 0.45 * stroke) * front
    # (MakeHuman's texture and eyebrow asset already carry the brows; painting a second set
    #  doubled them up, so only a light density boost right on the existing brow line)
    brow = np.clip(brow * 1.1, 0, 1) * 0.0

    # freckles / moles
    fd, fid = U.cell_dist(P, 0.006, seed=77)
    frk_m = np.clip(1 - fd / 0.0012, 0, 1) * (fid > 0.55) * frk * (front * face + (P[:, 2] > 1.25) * 0.6)
    md, mid = U.cell_dist(P, 0.05, seed=p.seed + 5)
    mole = np.clip(1 - md / 0.0016, 0, 1) * (mid > 0.82)

    mott = U.vnoise(P, 0.018, 3) * 0.5 + U.vnoise(P, 0.006, 4) * 0.35 + U.vnoise(P, 0.0018, 5) * 0.15
    blotch = np.clip(U.vnoise(P, 0.012, 6) * 1.6 - 0.3, 0, 1) * front * face

    pore_s = np.where(face, 0.00085, 0.0011)
    pd, _ = U.cell_dist(P, 0.001, seed=11)
    pores = np.clip(1 - pd / (0.00028 + 0.00012 * red), 0, 1)
    pore_k = 0.5 + 0.5 * np.clip(_gauss(np.linalg.norm(P - nose_tip, axis=1), 0.03 * s) * 1.5 + 0.4 * front * face, 0, 1)
    # --- compose the albedo on top of the MakeHuman skin -----------------------------
    tex_img = None
    for slot in h.material_slots:
        m = slot.material
        if m and m.node_tree:
            t = next((nd for nd in m.node_tree.nodes if nd.type == 'TEX_IMAGE' and nd.image), None)
            if t is not None:
                tex_img = t.image
                break
    if tex_img is None:
        return
    bw, bh = tex_img.size
    base = np.array(tex_img.pixels[:], dtype=np.float32).reshape(bh, bw, -1)[..., :3]
    yy, xx = np.divmod(pix, res)
    by = np.clip((yy + 0.5) / res * bh, 0, bh - 1).astype(int)
    bx = np.clip((xx + 0.5) / res * bw, 0, bw - 1).astype(int)
    c = base[by, bx]
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)       # sRGB -> linear
    lum = c.mean(1, keepdims=True)
    warm = np.array([1.0, 0.55, 0.5])
    c = c * (1 + red_k * red[:, None] * (warm - 1) * 0.9)          # flush toward red, not grey
    pig = np.array([0.62, 0.52, 0.55]) if pig_k < 0.6 else np.array([0.55, 0.47, 0.45])
    c = c * (1 - dark[:, None] * pig_k * (1 - pig))
    c = c * (1 + hi_k * high[:, None] * 1.4)
    c = c * (1 + 0.14 * mott[:, None])
    c = c * (1 + red_k * 0.8 * blotch[:, None] * (warm - 1))                      # uneven, blotchy redness
    # lips: darker toward the outer edge, a little lighter and pinker in the middle
    inner = np.clip((lips - 0.5) * 2, 0, 1)
    c = c * (1 + inner[:, None] * np.array([0.06, -0.02, 0.0]) * (1 if pig_k < 0.6 else 2.0))
    # pore pits read a touch darker in the albedo (like GTA's baked texture)
    c = c * (1 - 0.12 * pores[:, None] * pore_k[:, None])
    tint = np.array(stub_tint)
    c = c * (1 - stub[:, None] * 0.8 * (1 - tint))
    c = c * (1 - (stub * hairs)[:, None] * 0.7)
    hc = np.minimum(np.array(p.hair_color) * 0.6 + 0.02, c * 0.38)     # brows always darker than the skin
    c = c * (1 - brow[:, None]) + hc * brow[:, None]
    c = c * (1 - frk_m[:, None] * 0.35 * (1 - np.array([0.7, 0.5, 0.35])))
    c = c * (1 - mole[:, None] * 0.55)
    c[nails > 0.5] = c[nails > 0.5] * 0.7 + 0.25 * np.array([0.85, 0.72, 0.68])
    alb = _img_from(c, pix, res, h.name + "_skin_albedo", srgb=True)

    # --- height map: pores, grain, wrinkles, creases --------------------------------
    grain = U.vnoise(P, 0.00035, 13) * 0.5 + U.vnoise(P, 0.0012, 14) * 0.5
    hgt = 0.5 - pores * 0.3 * pore_k + grain * 0.08
    # fine cross-hatched skin texture (dermal glyphs), strongest on hands and around the eyes
    gl1 = np.abs(np.sin((P[:, 0] * 0.7 + P[:, 2]) / 0.0009 * np.pi + U.vnoise(P, 0.003, 21) * 3))
    gl2 = np.abs(np.sin((P[:, 0] * 0.7 - P[:, 2]) / 0.0011 * np.pi + U.vnoise(P, 0.003, 22) * 3))
    glyph = (1 - np.minimum(gl1, gl2)) ** 6
    hgt -= glyph * 0.05
    # forehead lines (faint on young characters)
    fz = r[:, 2] - 0.05 * s
    fl = np.sin(fz / (0.011 * s) * 2 * np.pi) * _gauss(fz, 0.018 * s) * smoothstep(0.055 * s, 0.03 * s, np.abs(r[:, 0]))
    hgt -= np.clip(fl, 0, 1) ** 4 * 0.2 * front * face
    for e, sx in ((el, 1), (er_, -1)):
        corner = e + np.array([sx * 0.024 * s, 0.006 * s, 0.0])
        q = P - corner
        ang = np.arctan2(q[:, 2], q[:, 0] * sx)
        d = np.linalg.norm(q, axis=1)
        crow = (np.abs(np.sin(ang * 9)) ** 8) * _gauss(d - 0.012 * s, 0.008 * s) * (q[:, 0] * sx > 0)
        hgt -= crow * 0.2 * front
        a = nose_tip + np.array([sx * 0.019 * s, 0.012 * s, 0.0])
        b = mouth + np.array([sx * 0.03 * s, 0.0, -0.004 * s])
        dl, tt = _seg_dist(P, a, b)
        hgt -= _gauss(dl, 0.0028 * s) * 0.32 * np.sin(np.pi * tt) * front
        lid = _gauss(np.linalg.norm((P - (e + np.array([0, -0.004 * s, 0.011 * s]))) * np.array([0.6, 1, 2.2]), axis=1), 0.004 * s)
        hgt -= lid * 0.3
    hgt -= (np.abs(np.sin(r[:, 0] / 0.0014 * np.pi + U.vnoise(P, 0.002, 23) * 2)) ** 5) * lips * 0.3    # lip lines
    for side in ('l', 'r'):
        for f in range(1, 6):
            for k in (2, 3):
                jn = '%s-finger-%d-%d' % (side, f, k)
                if jn in J:
                    d = np.linalg.norm(P - J[jn], axis=1)
                    hgt -= (np.abs(np.sin(d / 0.0016 * np.pi)) ** 5) * _gauss(d, 0.008) * 0.4
    for e, sx in ((el, 1), (er_, -1)):
        crease = _gauss(np.linalg.norm((P - (e + np.array([0, 0.002 * s, 0.009 * s]))) * np.array([0.55, 1, 3.0]), axis=1), 0.003 * s)
        hgt -= crease * 0.35
        tear = _gauss(np.linalg.norm((P - (e + np.array([0.004 * sx * s, -0.006 * s, -0.013 * s]))) * np.array([0.6, 1, 3.0]), axis=1), 0.003 * s)
        hgt -= tear * 0.25
    if neck is not None:
        nl = np.sin((P[:, 2] - neck[2]) / 0.012 * 2 * np.pi)
        hgt -= np.clip(nl, 0, 1) ** 6 * _gauss(P[:, 2] - neck[2] - 0.02, 0.03) * (P[:, 1] < neck[1]) * 0.1
    hgt += stub * hairs * 0.12          # stubble hairs stand slightly proud of the skin
    hgt = np.clip(hgt, 0, 1)
    him = _img_from(hgt, pix, res, h.name + "_skin_height", srgb=False)

    # --- roughness: oily T-zone and lips, matte elsewhere ---------------------------
    tz = (_gauss(np.abs(r[:, 0]), 0.022 * s) * smoothstep(-0.06 * s, -0.02 * s, r[:, 2]) +
          _gauss(np.linalg.norm(P - nose_tip, axis=1), 0.02 * s))
    rough = 0.6 - 0.1 * np.clip(tz * front * face, 0, 1) - 0.12 * lips + 0.06 * stub + 0.05 * pores \
        + 0.04 * mott
    rough = np.clip(rough, 0.25, 0.75)
    rim = _img_from(rough, pix, res, h.name + "_skin_rough", srgb=False)

    # --- hook the maps into every skin material --------------------------------------
    for slot in h.material_slots:
        m = slot.material
        if not m or not m.node_tree:
            continue
        nt = m.node_tree
        for t in nt.nodes:
            if t.type == 'TEX_IMAGE' and t.image == tex_img:
                t.image = alb
        lname = m.name.lower()
        if any(k in lname for k in ('eye', 'brow', 'lash', 'teeth', 'tongue', 'nail')):
            continue
        bsdf = next((nd for nd in nt.nodes if nd.type == 'BSDF_PRINCIPLED'), None)
        if bsdf is None:
            continue
        df = nt.nodes.get('SY_deepfac')
        if df is not None:
            df.inputs[1].default_value = 0.0         # zones are painted into the albedo now
        uvn = nt.nodes.new('ShaderNodeUVMap')
        ht = nt.nodes.new('ShaderNodeTexImage')
        ht.image = him
        ht.interpolation = 'Cubic'
        nt.links.new(uvn.outputs['UV'], ht.inputs['Vector'])
        rt = nt.nodes.new('ShaderNodeTexImage')
        rt.image = rim
        nt.links.new(uvn.outputs['UV'], rt.inputs['Vector'])
        nt.links.new(rt.outputs['Color'], bsdf.inputs['Roughness'])
        bump = nt.nodes.get('SY_bump')
        if bump is None:
            bump = nt.nodes.new('ShaderNodeBump')
            nt.links.new(bump.outputs['Normal'], bsdf.inputs['Normal'])
        bump.inputs['Strength'].default_value = 1.0 * min(1.0, p.skin_detail)
        bump.inputs['Distance'].default_value = 0.0016 * max(1.0, p.skin_detail)
        nt.links.new(ht.outputs['Color'], bump.inputs['Height'])


def build(context, p):
    M.load()
    female = p.gender == 'FEMALE'
    h = M.HS.create_human()
    tone = SKINS[p.skin_tone]
    af, asn, cau = tone[2]
    macros = dict(gender=0.0 if female else 1.0, age=0.25 + 0.12 * p.age, muscle=0.35 + 0.5 * p.muscle,
                  weight=0.3 + 0.55 * p.build, height=0.25 + 0.5 * p.height, proportions=0.5,
                  african=af, asian=asn, caucasian=cau)
    for k, v in macros.items():
        M.HOP.set_value(k, v, entity_reference=h)
    M.TS.reapply_macro_details(h)

    c = p.caricature
    af = SKINS[p.skin_tone][2][0]
    for k, v in CARICATURE.items():
        if k in ('mouth-upperlip-volume-decr', 'mouth-lowerlip-volume-decr', 'nose-scale-vert-incr', 'nose-hump-incr'):
            v = v * (1 - af)   # don't push features that contradict the character's own face shape
        target(h, k, v * c)
    for k, v in CARICATURE_SYM.items():
        sym(h, k, v * c)
    hs = p.head_size - 1.0
    for ax in ('horiz', 'vert', 'depth'):
        target_pm(h, 'head-scale-' + ax, hs * 1.5)
    target_pm(h, 'chin-width', p.jaw - 0.5)
    target_pm(h, 'chin-prominent', p.chin - 0.5)
    target_pm(h, 'nose-volume', p.nose - 0.5)
    target_pm(h, ('nose-trans-forward', 'nose-trans-backward'), (p.nose - 0.5) * 0.5)
    target_pm(h, ('eyebrows-angle-down', 'eyebrows-angle-up'), p.brow_angle)
    for side in ('l', 'r'):
        target_pm(h, (side + '-eye-height2-decr', side + '-eye-height2-incr'), 0.5 - p.eye_open)
        target_pm(h, (side + '-ear-scale-incr', side + '-ear-scale-decr'), p.ears - 0.5)
    target_pm(h, ('mouth-angles-down', 'mouth-angles-up'), p.scowl)
    if p.fat_face > 0:
        target(h, 'head-fat-incr', p.fat_face)
        target(h, 'neck-double-incr', p.fat_face * 0.6)

    apply_features(h, p, female)
    apply_hands(h, p, female)

    rig = None
    if p.add_rig:
        rig = M.HS.add_builtin_rig(h, "game_engine")
        if rig is None:
            rig = h.parent

    eyes = add_asset(h, 'eyes', 'high-poly', 'Eyes') or add_asset(h, 'eyes', 'low-poly', 'Eyes')
    fix_eyes(eyes)
    brow_name = next(n for t, n in BROWS if p.brow_heavy < t)
    brows = add_asset(h, 'eyebrows', brow_name, 'Eyebrows')
    add_asset(h, 'eyelashes', 'eyelashes01', 'Eyelashes')
    add_asset(h, 'teeth', 'teeth_base', 'Teeth')
    add_asset(h, 'tongue', 'tongue01', 'Tongue')

    skin = tone[1] if female else tone[0]
    sp = M.AS.find_asset_absolute_path(skin + '.mhmat', asset_subdir='skins')
    if sp:
        M.HS.set_character_skin(sp, h, skin_type="MAKESKIN")
        warm_skin(h, p.skin_warmth * (0.0 if p.skin_tone in ('BROWN', 'DARK', 'DEEP', 'TAN') else 0.35))
        if p.real_skin:
            skin_zones(h)
            realistic_skin(h, p.skin_tone, p.skin_detail)
            if p.skin_paint:
                try:
                    paint_skin(h, p, female, res=p.tex_res)
                except Exception as ex:
                    print("SY: skin paint failed", ex)

    urban_hair = p.hair_style in URBAN_HAIR
    if not urban_hair:
        hair = add_asset(h, 'hair', HAIR.get(p.hair_style), 'Hair')
        tint(hair, tuple(p.hair_color), keep=0.15)
    tint(brows, tuple(p.hair_color), keep=0.0)

    table = GIRL_OUTFITS if female else OUTFITS
    colors = {'top': tuple(p.top_color), 'outer': tuple(p.outer_color), 'pants': tuple(p.pants_color)}
    street = p.outfit == 'STREET'
    if street or urban_hair or p.hat in URBAN_HATS or p.chain or p.crossbody or p.socks != 'NONE' or p.shoes in SNEAKERS:
        build_urban(context, p, h, rig, street, urban_hair)
    for asset, role, special in ([] if street else table[p.outfit]):
        ob = add_asset(h, 'clothes', asset, 'Clothes')
        if ob is None:
            continue
        if special == 'VEST':
            cut_vest(ob, rig, p.vneck)
        if role and p.recolor:
            tint(ob, colors[role], keep=0.1)
    shoes = add_asset(h, 'clothes', None if (street and p.shoes == 'SNEAKERS') else SHOES.get(p.shoes), 'Clothes')
    if p.recolor and p.shoes in ('SCHOOL', 'BOOTS'):
        tint(shoes, tuple(p.shoe_color), keep=0.2)
    hat = add_asset(h, 'clothes', HATS.get(p.hat), 'Clothes')
    tint(hat, tuple(p.hat_color), keep=0.1)
    add_asset(h, 'clothes', GLASSES[p.glasses], 'Clothes')

    # naming / placement
    name = p.char_name.strip() or "Student"
    root = h.parent if h.parent else h
    root.name = name + ("_Rig" if root != h else "")
    h.name = name
    root.location = context.scene.cursor.location.copy()
    coll = bpy.data.collections.get("SY_" + name)
    if coll is not None and p.replace_existing:
        for ob in list(coll.objects):
            bpy.data.objects.remove(ob, do_unlink=True)
    if coll is None:
        coll = bpy.data.collections.new("SY_" + name)
        context.scene.collection.children.link(coll)
    for ob in collect(h):
        for uc in list(ob.users_collection):
            uc.objects.unlink(ob)
        coll.objects.link(ob)
        if ob != h and ob.type == 'MESH' and not ob.name.startswith(name):
            ob.name = name + "." + ob.name.split('.', 1)[-1]
    if rig is not None:
        try:
            apply_stance(rig, p.stance, seed=p.seed, female=(p.gender == 'FEMALE'))
        except Exception as ex:
            print("SY: stance failed", ex)
    return h



URBAN_HAIR = ('TAPER', 'WAVES', 'CURLY_TOP', 'TWISTS', 'LOCS', 'CORNROWS', 'HIGH_TOP', 'BRAIDS', 'BUN', 'PUFF')
URBAN_HATS = ('BEANIE', 'CAP', 'CAP_BACK', 'DURAG')
SNEAKERS = ('CHUNKY', 'RUNNER', 'COURT')
DESIGNER_TOPS = ('TECH', 'WEB')
DESIGNER_BOTTOMS = ('RIPPED', 'STARPATCH', 'FLORAL', 'TECH_JOG')
_HAIR_MAP = {'TAPER': 'BUZZ', 'HIGH_TOP': 'FLAT_TOP'}


def build_urban(context, p, h, rig, street, urban_hair):
    coll = context.scene.collection
    B = U.Body(h)
    U.SIM_MODE = bool(p.cloth_sim)
    U.HAIR_OBSTACLES.clear()
    # drape clothes on the posed body (real gravity folds), stored back in rest pose
    posed_drape = bool(p.cloth_sim) and p.stance != 'A_POSE' and rig is not None
    U.FREE_DRAPE = posed_drape
    if rig is not None and p.stance != 'A_POSE':
        apply_stance(rig, p.stance, seed=p.seed, female=(p.gender == 'FEMALE'))
        bpy.context.view_layer.update()
    drig = rig if posed_drape else None
    try:
        acc = np.array(p.accent_color)
        outer = []
        keeps = []
        if street:
            if p.street_bottom in DESIGNER_BOTTOMS:
                objs, keep = U.make_designer_bottom(B, h, rig, coll, "SY_Bottom",
                                                    'TECH' if p.street_bottom == 'TECH_JOG' else p.street_bottom,
                                                    np.array(p.pants_color), acc, p.bottom_pattern, seed=p.seed)
            else:
                objs, keep = U.make_bottom(B, h, rig, coll, "SY_Bottom", p.street_bottom, np.array(p.pants_color),
                                           acc, p.bottom_pattern)
            if p.cloth_sim:
                fab = 'denim' if p.street_bottom in ('BAGGY_JEANS', 'JORTS', 'RIPPED', 'STARPATCH', 'FLORAL') else \
                      'fleece' if p.street_bottom in ('JOGGERS', 'TECH_JOG') else 'cotton'
                U.drape(objs[0], [h], U.bottom_pins(B, p.street_bottom), fab, frames=max(p.sim_frames, 50) if drig else p.sim_frames, rig=drig)
            bottom_obj = objs[0]
            bottom_objs = objs

            def _bake_bottom(occl):
                if p.wear > 0:
                    U.garment_wear(objs[0], B, occl, 'bottom', p.wear, p.seed)
                if not p.textures:
                    U.apply_wear_to_vcol(objs[0])
                    return
                sb = p.street_bottom
                tk = ({'RIPPED': 'RIPPED', 'STARPATCH': 'STARPATCH', 'FLORAL': 'FLORAL', 'TECH_JOG': 'TECH_JOG',
                       'BAGGY_JEANS': 'DENIM', 'JORTS': 'DENIM', 'JOGGERS': 'FLEECE'}.get(sb, 'COTTON'))
                if p.bottom_pattern == 'CAMO':
                    tk = 'CAMO'
                U.bake_texture(objs[0], U.print_fn(B, tk, acc, p.seed), res=p.tex_res,
                               kind='denim' if tk in ('RIPPED', 'STARPATCH', 'FLORAL', 'DENIM') else 'cotton')
            keeps.append(keep)
            if p.socks != 'NONE' and p.street_bottom in ('JORTS', 'SHORTS', 'JOGGERS'):
                pass
            maker = U.make_designer_top if p.street_top in DESIGNER_TOPS else U.make_top
            objs2, keep2 = maker(B, h, rig, coll, "SY_Top", p.street_top, np.array(p.outer_color), acc,
                                 p.top_pattern)
            if p.cloth_sim and p.street_top != 'PUFFER':
                fab = 'fleece' if p.street_top in ('HOODIE', 'ZIPUP', 'TECH', 'WEB') else 'cotton'
                U.drape(objs2[0], [h, bottom_obj], U.top_pins(B, p.street_top), fab, frames=max(p.sim_frames, 60) if drig else p.sim_frames, rig=drig)
            # bake both garments now that each can shade the other (shirt hem over the waistband)
            _bake_bottom([o for o in objs2 if o is not None])
            if p.wear > 0 and p.street_top != 'PUFFER':
                U.garment_wear(objs2[0], B, [bottom_obj], 'top', p.wear, p.seed)
                if not p.textures:
                    U.apply_wear_to_vcol(objs2[0])
            if p.textures and p.street_top != 'PUFFER':
                tk = ('WEB' if p.street_top == 'WEB' else 'TECH' if p.street_top == 'TECH' else
                      'CAMO' if p.top_pattern == 'CAMO' else
                      'HOODIE' if p.street_top == 'HOODIE' else
                      'FLEECE' if p.street_top == 'ZIPUP' else 'COTTON')
                U.bake_texture(objs2[0], U.print_fn(B, tk, acc, p.seed), res=p.tex_res,
                               kind='fleece' if tk in ('WEB', 'TECH', 'FLEECE', 'HOODIE') else 'cotton')
            if p.street_top == 'WEB':
                U.add_rhinestones(B, h, rig, coll, "SY_Rhinestones", objs2[0])
            if p.street_top in ('HOODIE', 'WEB'):
                U.drawstrings_on(B, h, rig, coll, "SY_Strings", objs2[0], acc)
            outer += [o for o in objs2 if o is not None]
            keeps.append(keep2)
        sock_kind = p.socks
        if sock_kind == 'NONE' and street and p.street_bottom in ('JOGGERS', 'TECH_JOG', 'RIPPED'):
            sock_kind = 'BLACK' if np.mean(p.pants_color) < 0.25 else 'WHITE'   # no bare ankle under cuffed joggers
        if sock_kind != 'NONE':
            sc = {'WHITE': (np.array([0.85, 0.85, 0.83]), None),
                  'BLACK': (np.array([0.02, 0.02, 0.02]), None),
                  'STRIPED': (np.array([0.85, 0.85, 0.83]), acc),
                  'PINK': (np.array([0.86, 0.45, 0.56]), None)}[sock_kind]
            U.make_socks(B, h, rig, coll, "SY_Socks", sc[0], sc[1])
        cover = None
        if p.hat in URBAN_HATS:
            _, cover = U.make_headwear(B, h, rig, coll, "SY_Hat", p.hat, np.array(p.hat_color),
                                       np.array(p.hat_color) * 0.8)
        if urban_hair:
            hst = _HAIR_MAP.get(p.hair_style, p.hair_style)
            hobjs = U.make_hair(B, h, rig, coll, "SY_Hair", hst, np.array(p.hair_color), p.fade,
                                cover if p.hat != 'DURAG' else None, seed=p.seed,
                                coil_count={'LOW': 300, 'MEDIUM': 900, 'HIGH': 1800}[p.strand_detail])
            if p.textures and hobjs:
                U.bake_texture(hobjs[0], U.hair_texel_fn(B, hst, p.fade, np.array(p.hair_color), p.seed),
                               res=p.tex_res, kind='hair', alpha=True)
        if p.shoes in SNEAKERS or (street and p.shoes == 'SNEAKERS'):
            if p.shoes == 'SNEAKERS':   # street look: clean white low court shoe instead of the stock asset
                wht = np.array([0.9, 0.89, 0.86])
                _, fcov = U.make_sneakers(B, h, rig, coll, "SY_Sneaker", 'COURT', wht, wht * 0.97, wht, seed=p.seed)
            else:
                _, fcov = U.make_sneakers(B, h, rig, coll, "SY_Sneaker", p.shoes, np.array(p.shoe_color),
                                          np.array(p.sneaker_accent), np.array(p.sole_color), seed=p.seed)
            keeps.append(fcov)
            if p.wear > 0:
                for so in [o for o in bpy.data.objects if o.name.startswith(p.char_name + ".SY_Sneaker") or
                           (o.name.startswith("SY_Sneaker") and o.parent == rig)]:
                    U.garment_wear(so, B, [bottom_obj] if street else [], 'shoe', p.wear, p.seed, n_rays=5)
                    U.apply_wear_to_vcol(so)
        if p.chain:
            U.make_jewelry(B, h, rig, coll, "SY_Chain", outer, p.metal, p.pendant)
        if p.crossbody:
            U.make_crossbody(B, h, rig, coll, "SY_Bag", outer, np.array([0.03, 0.03, 0.03]), np.array([0.05, 0.05, 0.05]))
        for i, k in enumerate(keeps):
            U.hide_body_under(h, B, k, rings=3, tag="SY%d" % i)
    finally:
        B.free()

# --------------------------------------------------------------------------------------
# Presets / random
# --------------------------------------------------------------------------------------

_D = dict(gender='MALE', age=0.6, build=0.4, muscle=0.4, height=0.5, head_size=1.08, caricature=1.0,
          jaw=0.5, chin=0.5, nose=0.5, brow_heavy=0.6, brow_angle=0.3, eye_open=0.5, ears=0.5, scowl=0.2,
          fat_face=0.0, skin_tone='LIGHT', skin_warmth=0.35, hair_style='PART', hair_color=hexc('4a2e1c'),
          outfit='UNIFORM', top_color=hexc('f2f0ea'), outer_color=hexc('1f3a7a'), pants_color=hexc('3a3b40'),
          shoes='SCHOOL', shoe_color=hexc('2a1d15'), hat='NONE', hat_color=hexc('5a4a3a'), glasses='NONE',
          vneck=0.22, auto_features=True, nose_width=0.5, nose_bridge=0.5, lip_fullness=0.5, face_width=0.5, real_skin=True, skin_detail=1.0, sneaker_accent=hexc('9a9ea6'), sole_color=hexc('e9e6df'), metal='SILVER', pendant=False, textures=True, tex_res=2048, cloth_sim=True, sim_frames=36, strand_detail='MEDIUM', street_top='HOODIE', street_bottom='BAGGY_JEANS', top_pattern='SOLID',
          bottom_pattern='SOLID', accent_color=hexc('d8d2c4'), fade='LOW', socks='NONE', chain=False, crossbody=False)


def _p(**kw):
    d = dict(_D)
    d.update(kw)
    return d


PRESETS = {
    'STUDENT': _p(),
    'JOCK': _p(build=0.55, muscle=0.95, height=0.75, head_size=1.02, jaw=0.9, chin=0.7, brow_heavy=0.7,
               hair_style='BUZZ', hair_color=hexc('b8924a'), skin_tone='TAN', skin_warmth=0.1, outfit='STRIPED',
               shoes='SNEAKERS', scowl=0.1),
    'NERD': _p(build=0.15, muscle=0.0, height=0.2, head_size=1.12, jaw=0.15, chin=0.2, nose=0.8,
               brow_heavy=0.3, brow_angle=-0.3, eye_open=0.75, ears=0.8, hair_style='SWEEP',
               hair_color=hexc('6b4a2b'), outfit='UNIFORM', outer_color=hexc('5f7f3a'),
               pants_color=hexc('8a7a5a'), glasses='LIBRARY', skin_tone='FRECKLED', scowl=-0.1),
    'PREP': _p(build=0.3, muscle=0.4, height=0.6, jaw=0.7, chin=0.8, nose=0.35, brow_heavy=0.35,
               brow_angle=0.0, hair_style='NEAT', hair_color=hexc('c9a35c'), outfit='SWEATER',
               outer_color=hexc('9fc3e0'), pants_color=hexc('e6dcc0'), scowl=0.0),
    'GREASER': _p(build=0.35, muscle=0.55, jaw=0.75, nose=0.65, brow_heavy=0.8, brow_angle=0.6, eye_open=0.3,
                  hair_style='SLICK', hair_color=hexc('15110e'), outfit='JACKET', outer_color=hexc('141414'),
                  shoes='BOOTS', shoe_color=hexc('111111'), scowl=0.4),
    'BRUISER': _p(build=0.8, muscle=0.6, height=0.8, head_size=1.02, jaw=1.0, nose=0.9, brow_heavy=1.0,
                  brow_angle=0.9, eye_open=0.25, fat_face=0.4, skin_tone='BROWN', hair_style='BUZZ',
                  hair_color=hexc('2b1d14'), outfit='UNIFORM', scowl=0.6),
    'TOWNIE': _p(build=0.45, muscle=0.5, jaw=0.7, nose=0.7, brow_heavy=0.7, brow_angle=0.5, eye_open=0.35,
                 hair_style='LONG', hair_color=hexc('5a3d22'), outfit='OVERALLS', shoes='WORK', scowl=0.3),
    # --- today's urban fits (see research notes in the README) ---
    'HOOPER': _p(build=0.4, muscle=0.6, height=0.8, skin_tone='DARK', caricature=0.7, hair_style='WAVES', fade='LOW',
                 hair_color=hexc('120d0a'), outfit='STREET', street_top='HOODIE', outer_color=hexc('2a2a2e'),
                 street_bottom='BAGGY_JEANS', pants_color=hexc('3c5a86'), shoes='CHUNKY', shoe_color=hexc('e8e6e1'), sneaker_accent=hexc('2a2a2e'), chain=True, scowl=0.1),
    'TWISTS': _p(build=0.3, muscle=0.4, skin_tone='BROWN', caricature=0.7, hair_style='TWISTS', fade='HIGH',
                 hair_color=hexc('140e0a'), outfit='STREET', street_top='PUFFER', outer_color=hexc('101010'),
                 street_bottom='CARGO', pants_color=hexc('4a4a3a'), shoes='RUNNER', shoe_color=hexc('d9dadc'), crossbody=True),
    'LOCS': _p(build=0.35, muscle=0.5, skin_tone='DARK', caricature=0.7, hair_style='LOCS', fade='NONE',
               hair_color=hexc('1a120c'), outfit='STREET', street_top='BOXY_TEE', outer_color=hexc('e8e4da'),
               street_bottom='JORTS', pants_color=hexc('46628f'), socks='WHITE', shoes='SNEAKERS', crossbody=True),
    'CORNROWS': _p(build=0.45, muscle=0.7, skin_tone='TAN', caricature=0.8, hair_style='CORNROWS', fade='NONE',
                   hair_color=hexc('120d0a'), outfit='STREET', street_top='JERSEY', outer_color=hexc('1f3a7a'),
                   accent_color=hexc('f2f0ea'), street_bottom='TRACK', pants_color=hexc('111111'), shoes='SNEAKERS',
                   chain=True),
    'CURLS': _p(build=0.3, muscle=0.35, skin_tone='LIGHT2', caricature=0.75, hair_style='CURLY_TOP', fade='MID',
                hair_color=hexc('2b1d14'), outfit='STREET', street_top='HOODIE', outer_color=hexc('5d6b4a'),
                top_pattern='CAMO', accent_color=hexc('2e2a22'), street_bottom='JOGGERS', pants_color=hexc('707070'),
                socks='WHITE', shoes='SNEAKERS'),
    'DURAG': _p(build=0.5, muscle=0.6, skin_tone='DARK', caricature=0.8, hair_style='WAVES', fade='LOW',
                hair_color=hexc('120d0a'), hat='DURAG', hat_color=hexc('101010'), outfit='STREET',
                street_top='BOXY_TEE', outer_color=hexc('ffffff'), street_bottom='CARGO', pants_color=hexc('2b2b2b'),
                shoes='SNEAKERS', chain=True),
    'BRAIDS_GIRL': _p(gender='FEMALE', build=0.25, muscle=0.2, height=0.45, caricature=0.4, skin_tone='DARK',
                      jaw=0.2, chin=0.3, nose=0.3, brow_heavy=0.25, eye_open=0.7, ears=0.3, scowl=0.0,
                      hair_style='BRAIDS', fade='NONE', hair_color=hexc('140e0a'), outfit='STREET',
                      street_top='ZIPUP', outer_color=hexc('c9c3b6'), street_bottom='BAGGY_JEANS',
                      pants_color=hexc('5d7aa8'), shoes='SNEAKERS'),
    'BUN_GIRL': _p(gender='FEMALE', build=0.25, muscle=0.2, height=0.45, caricature=0.4, skin_tone='TAN',
                   jaw=0.2, chin=0.3, nose=0.3, brow_heavy=0.25, eye_open=0.7, ears=0.3, scowl=0.0,
                   hair_style='BUN', fade='NONE', hair_color=hexc('1a120c'), outfit='STREET', street_top='BOXY_TEE',
                   outer_color=hexc('1a1a1a'), street_bottom='CARGO', pants_color=hexc('6b6650'), shoes='SNEAKERS',
                   crossbody=True),
    'LUXE_RIPPED': _p(build=0.3, muscle=0.5, skin_tone='DARK', caricature=0.7, hair_style='TWISTS', fade='HIGH',
                      hair_color=hexc('120d0a'), outfit='STREET', street_top='WEB', outer_color=hexc('e06aa8'),
                      accent_color=hexc('15151a'), street_bottom='RIPPED', pants_color=hexc('2b3f66'),
                      shoes='CHUNKY', shoe_color=hexc('1a1a1a'), sneaker_accent=hexc('c0302a'),
                      sole_color=hexc('efece6'), chain=True, metal='SILVER', pendant=True),
    'TECH_SET': _p(build=0.35, muscle=0.55, skin_tone='BROWN', caricature=0.7, hair_style='WAVES', fade='MID',
                   hair_color=hexc('120d0a'), outfit='STREET', street_top='TECH', outer_color=hexc('5a5c60'),
                   accent_color=hexc('1b1b1d'), street_bottom='TECH_JOG', pants_color=hexc('5a5c60'),
                   shoes='RUNNER', shoe_color=hexc('e7e8ea'), sneaker_accent=hexc('b9bcc2'), crossbody=True),
    'STAR_DENIM': _p(build=0.3, muscle=0.4, skin_tone='LIGHT2', caricature=0.75, hair_style='CURLY_TOP', fade='LOW',
                     hair_color=hexc('2b1d14'), outfit='STREET', street_top='BOXY_TEE', outer_color=hexc('101012'),
                     street_bottom='STARPATCH', pants_color=hexc('4f6f9c'), shoes='CHUNKY',
                     shoe_color=hexc('efede8'), sneaker_accent=hexc('9fa3ab'), chain=True, metal='SILVER'),
    'FLORAL_DENIM': _p(build=0.4, muscle=0.5, skin_tone='TAN', caricature=0.75, hair_style='LOCS', fade='NONE',
                       hair_color=hexc('1a120c'), outfit='STREET', street_top='HOODIE', outer_color=hexc('ece8de'),
                       street_bottom='FLORAL', pants_color=hexc('2f4a78'), shoes='RUNNER',
                       shoe_color=hexc('ece9e2'), sneaker_accent=hexc('a6a9ae'), chain=True, metal='GOLD'),
    'GIRL': _p(gender='FEMALE', build=0.25, muscle=0.15, height=0.4, head_size=1.06, caricature=0.45, jaw=0.2,
               chin=0.3, nose=0.25, brow_heavy=0.2, brow_angle=-0.2, eye_open=0.75, ears=0.3, scowl=0.0,
               hair_style='PONYTAIL', hair_color=hexc('7a4a24'), outfit='UNIFORM', pants_color=hexc('2b2f45'),
               shoes='FLATS'),
}


def apply_preset(self, context):
    for k, v in PRESETS.get(self.preset, {}).items():
        setattr(self, k, v)


def randomize(p):
    r = random.Random(p.seed)
    p.preset = 'CUSTOM'
    p.gender = r.choice(['MALE', 'MALE', 'MALE', 'FEMALE'])
    fem = p.gender == 'FEMALE'
    for k in ('age', 'build', 'muscle', 'height', 'jaw', 'chin', 'nose', 'brow_heavy', 'eye_open', 'ears'):
        setattr(p, k, r.random())
    p.build = r.random() ** 1.4
    p.head_size = r.uniform(1.0, 1.14)
    p.caricature = r.uniform(0.35, 0.6) if fem else r.uniform(0.6, 1.0)
    p.brow_angle = r.uniform(-0.4, 0.9)
    p.scowl = r.uniform(-0.2, 0.6)
    p.fat_face = max(0.0, p.build - 0.6)
    p.skin_tone = r.choice(list(SKINS))
    p.hair_style = r.choice(['PONYTAIL', 'LONG', 'BOB', 'MESSY'] if fem else
                            ['BUZZ', 'NEAT', 'PART', 'SLICK', 'SWEEP', 'SPIKY', 'MESSY', 'AFRO', 'LONG'])
    p.hair_color = hexc(r.choice(['15110e', '2b1d14', '4a2e1c', '6b4a2b', '8a5a2b', 'c9a35c', 'e2c98a', '7a2e1a']))
    p.outfit = r.choice(['UNIFORM', 'UNIFORM', 'SWEATER', 'POLO', 'TEE', 'JACKET', 'DENIM', 'STRIPED'])
    cols = ['f2f0ea', '1f3a7a', '8a1f24', '5f7f3a', '3a3b40', '141414', '9fc3e0', 'e6dcc0', '6b6f5a', 'c46a2b']
    p.top_color = hexc(r.choice(['f2f0ea', 'ffffff', 'd8d2c4', '9fc3e0']))
    p.outer_color = hexc(r.choice(cols))
    p.pants_color = hexc(r.choice(['3a3b40', '2f4a73', 'e6dcc0', '8a7a5a', '2b2f45']))
    p.shoes = 'FLATS' if fem else r.choice(['SCHOOL', 'SCHOOL', 'SNEAKERS', 'BOOTS', 'WORK'])
    p.hat = r.choice(['NONE'] * 8 + ['NEWSBOY'])
    p.glasses = r.choice(['NONE'] * 7 + ['ROUND', 'LIBRARY', 'OPTICAL'])
    p.seed += 1


# --------------------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------------------

def _col(d):
    return FloatVectorProperty(subtype='COLOR', size=3, min=0, max=1, default=d)


def _f(name, d, lo=0.0, hi=1.0, desc=""):
    return FloatProperty(name=name, default=d, min=lo, max=hi, description=desc)


class SY3_Props(bpy.types.PropertyGroup):
    char_name: StringProperty(name="Name", default="Student")
    preset: EnumProperty(name="Preset", update=apply_preset, default='CUSTOM', items=[
        ('CUSTOM', "Custom", ""), ('STUDENT', "Student", ""), ('JOCK', "Jock", ""), ('NERD', "Nerd", ""),
        ('PREP', "Prep", ""), ('GREASER', "Greaser", ""), ('BRUISER', "Bruiser", ""), ('TOWNIE', "Townie", ""),
        ('GIRL', "Student (Girl)", ""), ('HOOPER', "Street: Waves + Hoodie", ""),
        ('TWISTS', "Street: Twists + Puffer", ""), ('LOCS', "Street: Locs + Jorts", ""),
        ('CORNROWS', "Street: Cornrows + Jersey", ""), ('CURLS', "Street: Curly Top + Camo", ""),
        ('DURAG', "Street: Durag + Boxy Tee", ""), ('BRAIDS_GIRL', "Street: Box Braids (Girl)", ""),
        ('BUN_GIRL', "Street: Slick Bun (Girl)", ""), ('LUXE_RIPPED', "Designer: Web Hoodie + Ripped Denim", ""),
        ('TECH_SET', "Designer: Tech Fleece Set", ""), ('STAR_DENIM', "Designer: Star-Patch Denim", ""),
        ('FLORAL_DENIM', "Designer: Floral Denim", "")])
    seed: IntProperty(name="Seed", default=1)
    gender: EnumProperty(name="Body", items=[('MALE', "Boy", ""), ('FEMALE', "Girl", "")], default='MALE')
    age: _f("Age (13-18)", 0.6)
    build: _f("Build (Thin-Heavy)", 0.4)
    muscle: _f("Muscle", 0.4)
    height: _f("Height", 0.5)
    head_size: _f("Head Size", 1.08, 0.9, 1.25)
    caricature: _f("Caricature", 1.0, 0.0, 1.5, "How strongly faces are pushed toward the schoolyard-game look")
    jaw: _f("Jaw Width", 0.5)
    chin: _f("Chin", 0.5)
    nose: _f("Nose", 0.5)
    brow_heavy: _f("Brow Weight", 0.6)
    brow_angle: _f("Brow Angle (Angry)", 0.3, -1.0, 1.0)
    eye_open: _f("Eye Openness", 0.5)
    ears: _f("Ears", 0.5)
    scowl: _f("Scowl", 0.2, -1.0, 1.0)
    fat_face: _f("Chubby Face", 0.0)
    skin_tone: EnumProperty(name="Skin", default='LIGHT', items=[
        ('LIGHT', "Light", ""), ('LIGHT2', "Light 2", ""), ('FRECKLED', "Freckled", ""), ('GINGER', "Ginger", ""),
        ('TAN', "Tan", ""), ('ASIAN', "East Asian", ""), ('BROWN', "Brown", ""), ('DARK', "Dark", ""),
        ('DEEP', "Deep", "")])
    auto_features: BoolProperty(name="Natural Feature Variation", default=True,
                                description="Vary nose, lips, bridge and face width per character within real human ranges")
    nose_width: _f("Nose Width", 0.5)
    nose_bridge: _f("Nose Bridge Height", 0.5)
    lip_fullness: _f("Lip Fullness", 0.5)
    face_width: _f("Face Width", 0.5)
    real_skin: BoolProperty(name="Realistic Skin", default=True,
                            description="Pores, oily T-zone sheen, subsurface tuned per tone, rich colour")
    skin_detail: _f("Skin Detail", 1.0, 0.0, 1.5)
    skin_warmth: _f("Skin Warmth", 0.35)
    hair_style: EnumProperty(name="Hair", default='PART', items=[(k, k.replace('_', ' ').title(), "") for k in HAIR] + [
        ('TAPER', "Taper / Buzz", ""), ('WAVES', "Waves", ""), ('CURLY_TOP', "Curly Top", ""),
        ('TWISTS', "Two-Strand Twists", ""), ('LOCS', "Locs", ""), ('CORNROWS', "Cornrows / Stitch Braids", ""),
        ('HIGH_TOP', "High-Top", ""), ('BRAIDS', "Knotless Box Braids", ""), ('BUN', "Slick Bun", ""),
        ('PUFF', "Puff", "")])
    hair_color: _col(hexc('4a2e1c'))
    outfit: EnumProperty(name="Outfit", default='UNIFORM', items=[
        ('UNIFORM', "Uniform (Polo + Sweater Vest)", ""), ('SWEATER', "Sweater", ""), ('POLO', "Polo", ""),
        ('TEE', "T-Shirt + Cargos", ""), ('JACKET', "Jacket + Jeans", ""), ('DENIM', "Denim Shirt + Jeans", ""),
        ('STRIPED', "Striped Shirt + Jeans", ""), ('OVERALLS', "Overalls", ""),
        ('STREET', "Street (Today's Urban Fits)", "Oversized hoodies, puffers, boxy tees, baggy jeans, cargos...")])
    street_top: EnumProperty(name="Top", default='HOODIE', items=[
        ('HOODIE', "Oversized Hoodie", ""), ('ZIPUP', "Zip-Up Hoodie", ""), ('PUFFER', "Puffer Jacket", ""),
        ('BOXY_TEE', "Boxy Oversized Tee", ""), ('LONGSLEEVE', "Long Sleeve", ""), ('JERSEY', "Jersey", ""),
        ('TECH', "Tech Fleece Zip (paneled)", ""), ('WEB', "Rhinestone Web Hoodie", "")])
    street_bottom: EnumProperty(name="Bottom", default='BAGGY_JEANS', items=[
        ('BAGGY_JEANS', "Baggy Jeans", ""), ('CARGO', "Cargo Pants", ""), ('JOGGERS', "Sweats / Joggers", ""),
        ('TRACK', "Track Pants", ""), ('JORTS', "Jorts", ""), ('SHORTS', "Shorts", ""),
        ('RIPPED', "Ripped Jeans, Leather-Backed", ""), ('STARPATCH', "Star-Patch Jeans", ""),
        ('FLORAL', "Baggy Floral-Print Jeans", ""), ('TECH_JOG', "Tech Fleece Joggers", "")])
    sneaker_accent: _col(hexc('9a9ea6'))
    sole_color: _col(hexc('e9e6df'))
    strand_detail: EnumProperty(name="Hair Strand Detail", default='MEDIUM',
                                items=[('LOW', "Low (game)", ""), ('MEDIUM', "Medium", ""), ('HIGH', "High (cinematic)", "")])
    skin_paint: BoolProperty(name="Painted Skin Maps", default=True,
                             description="Bake Bully/GTA-style skin detail (colour zones, stubble, brows, pores, "
                                         "wrinkles, oily T-zone) into albedo/height/roughness images")
    stubble: FloatProperty(name="Stubble", default=0.75, min=0.0, max=1.0)
    wear: FloatProperty(name="Baked Shading & Wear", default=0.8, min=0.0, max=1.0,
                        description="Rockstar-style baked occlusion in folds/overlaps plus grime on cuffs, "
                                    "collars, hems, pant legs and soles")
    hand_thickness: FloatProperty(name="Hand Thickness", default=0.85, min=0.0, max=1.0,
                                  description="0.5 = stock hands; higher = thicker fingers, fuller palm and wrists")
    stance: EnumProperty(name="Stance", default='RELAXED',
                         items=[('RELAXED', "Relaxed (street)", "Arms down, weight on one leg, natural hands"),
                                ('A_POSE', "A-Pose (rest)", "Rig rest pose, for export/animation setup")])
    cloth_sim: BoolProperty(name="Cloth Sim Drape", default=True,
                            description="Simulate fabric so clothes hang, fold and stack (slower)")
    sim_frames: IntProperty(name="Sim Frames", default=36, min=10, max=120)
    textures: BoolProperty(name="Bake Fabric Textures", default=True,
                           description="Paint prints and fabric detail into real image textures (exported with FBX)")
    tex_res: IntProperty(name="Texture Size", default=2048, min=512, max=4096)
    metal: EnumProperty(name="Metal", default='SILVER', items=[('SILVER', "Silver", ""), ('GOLD', "Gold", "")])
    pendant: BoolProperty(name="Pendant", default=False)
    top_pattern: EnumProperty(name="Top Pattern", default='SOLID', items=[
        ('SOLID', "Solid", ""), ('CAMO', "Camo", ""), ('STRIPE', "Stripes", ""), ('BLOCK', "Colour Block", "")])
    bottom_pattern: EnumProperty(name="Bottom Pattern", default='SOLID', items=[
        ('SOLID', "Solid", ""), ('CAMO', "Camo", ""), ('BLOCK', "Colour Block", "")])
    accent_color: _col(hexc('d8d2c4'))
    fade: EnumProperty(name="Fade", default='LOW', items=[('NONE', "None", ""), ('LOW', "Low / Taper", ""),
                                                           ('MID', "Mid", ""), ('HIGH', "High", "")])
    socks: EnumProperty(name="Socks", default='NONE', items=[('NONE', "None", ""), ('WHITE', "White Crew", ""),
                                                              ('BLACK', "Black Crew", ""), ('STRIPED', "Striped Crew", ""),
                                                              ('PINK', "Pink Crew", "")])   # GLASS CITY: Yelly's fit
    chain: BoolProperty(name="Chain", default=False)
    crossbody: BoolProperty(name="Crossbody Bag", default=False)
    recolor: BoolProperty(name="Recolour Clothes", default=True)
    top_color: _col(hexc('f2f0ea'))
    outer_color: _col(hexc('1f3a7a'))
    pants_color: _col(hexc('3a3b40'))
    vneck: _f("V-Neck Depth", 0.22, 0.0, 0.45)
    shoes: EnumProperty(name="Shoes", default='SCHOOL', items=[(k, k.title(), "") for k in SHOES] + [
        ('CHUNKY', "Chunky Dad Sneaker", "Stacked-sole luxury runner silhouette"),
        ('RUNNER', "Retro Runner (Metallic)", "Late-2000s mesh runner with metallic overlays"),
        ('COURT', "Low Court Sneaker", "Clean leather low-top court shoe with cupsole")])
    shoe_color: _col(hexc('2a1d15'))
    hat: EnumProperty(name="Hat", default='NONE', items=[(k, k.title(), "") for k in HATS] + [
        ('BEANIE', "Beanie", ""), ('CAP', "Fitted Cap", ""), ('CAP_BACK', "Cap (Backwards)", ""), ('DURAG', "Durag", "")])
    hat_color: _col(hexc('5a4a3a'))
    glasses: EnumProperty(name="Glasses", default='NONE', items=[(k, k.title(), "") for k in GLASSES])
    add_rig: BoolProperty(name="Game Rig (Unreal/Unity names)", default=True)
    replace_existing: BoolProperty(name="Replace Same Name", default=True)
    show_body: BoolProperty(default=True)
    show_face: BoolProperty(default=False)
    show_look: BoolProperty(default=False)
    show_outfit: BoolProperty(default=False)


class SY3_OT_generate(bpy.types.Operator):
    bl_idname = "sy3.generate"
    bl_label = "Generate"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        try:
            build(context, context.scene.sy3_props)
        except RuntimeError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        return {'FINISHED'}


class SY3_OT_random(bpy.types.Operator):
    bl_idname = "sy3.random"
    bl_label = "Random"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        p = context.scene.sy3_props
        randomize(p)
        p.char_name = "Student_%d" % p.seed
        build(context, p)
        return {'FINISHED'}


class SY3_OT_export(bpy.types.Operator):
    bl_idname = "sy3.export_fbx"
    bl_label = "Export FBX"
    bl_description = "Export the selected character (rig + meshes) as a game-ready FBX"
    filepath: StringProperty(subtype='FILE_PATH', default="//character.fbx")

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        bpy.ops.export_scene.fbx(filepath=bpy.path.abspath(self.filepath), use_selection=True,
                                 object_types={'ARMATURE', 'MESH'}, add_leaf_bones=False,
                                 bake_anim=False, path_mode='COPY', embed_textures=True)
        return {'FINISHED'}


def _sec(L, p, flag, title, icon):
    b = L.box()
    r = b.row()
    r.prop(p, flag, text=title, icon='TRIA_DOWN' if getattr(p, flag) else 'TRIA_RIGHT', emboss=False)
    r.label(icon=icon)
    return b.column(align=True) if getattr(p, flag) else None


class SY3_PT_panel(bpy.types.Panel):
    bl_label = "Schoolyard Characters v3"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Schoolyard'

    def draw(self, context):
        p = context.scene.sy3_props
        L = self.layout
        c = L.column(align=True)
        c.prop(p, "char_name")
        c.prop(p, "preset")
        r = L.row(align=True)
        r.scale_y = 1.5
        r.operator("sy3.generate", icon='USER')
        r.operator("sy3.random", icon='FILE_REFRESH')
        L.prop(p, "seed")
        c = _sec(L, p, "show_body", "Body", 'ARMATURE_DATA')
        if c:
            for k in ("gender", "age", "build", "muscle", "height", "skin_tone", "skin_warmth"):
                c.prop(p, k)
        c = _sec(L, p, "show_face", "Face", 'MONKEY')
        if c:
            for k in ("caricature", "head_size", "jaw", "chin", "nose", "nose_width", "nose_bridge", "lip_fullness",
                      "face_width", "brow_heavy", "brow_angle", "eye_open", "ears", "scowl", "fat_face",
                      "auto_features", "real_skin", "skin_detail"):
                c.prop(p, k)
        c = _sec(L, p, "show_look", "Hair & Accessories", 'MATERIAL')
        if c:
            c.prop(p, "hair_style")
            c.prop(p, "hair_color", text="Hair Colour")
            if p.hair_style in URBAN_HAIR:
                c.prop(p, "fade")
                c.prop(p, "strand_detail")
            c.prop(p, "hat")
            if p.hat != 'NONE':
                c.prop(p, "hat_color", text="Hat Colour")
            c.prop(p, "glasses")
            c.prop(p, "chain")
            if p.chain:
                c.prop(p, "metal")
                c.prop(p, "pendant")
            c.prop(p, "crossbody")
        c = _sec(L, p, "show_outfit", "Outfit", 'MOD_CLOTH')
        if c:
            c.prop(p, "outfit")
            if p.outfit == 'STREET':
                c.prop(p, "street_top")
                c.prop(p, "top_pattern")
                c.prop(p, "street_bottom")
                c.prop(p, "bottom_pattern")
                c.prop(p, "accent_color", text="Accent / Trim")
            c.prop(p, "socks")
            c.prop(p, "recolor")
            if p.recolor:
                c.prop(p, "top_color", text="Shirt")
                c.prop(p, "outer_color", text="Vest / Sweater / Jacket")
                c.prop(p, "pants_color", text="Pants / Skirt")
            c.prop(p, "vneck")
            c.prop(p, "shoes")
            c.prop(p, "shoe_color", text="Shoe Colour")
            if p.shoes in SNEAKERS:
                c.prop(p, "sneaker_accent", text="Overlay Colour")
                c.prop(p, "sole_color", text="Sole Colour")
        L.prop(p, "wear")
        L.prop(p, "skin_paint")
        L.prop(p, "stubble")
        L.prop(p, "hand_thickness")
        L.prop(p, "stance")
        L.prop(p, "cloth_sim")
        if p.cloth_sim:
            L.prop(p, "sim_frames")
        L.prop(p, "textures")
        if p.textures:
            L.prop(p, "tex_res")
        L.prop(p, "add_rig")
        L.prop(p, "replace_existing")
        L.operator("sy3.export_fbx", icon='EXPORT')


classes = (SY3_Props, SY3_OT_generate, SY3_OT_random, SY3_OT_export, SY3_PT_panel)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.sy3_props = PointerProperty(type=SY3_Props)


def unregister():
    del bpy.types.Scene.sy3_props
    for c in reversed(classes):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
