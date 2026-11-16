"""Blender (bpy) weapon models for GLASS CITY: bevelled, smooth-shaded parts with real detail (slide serrations,
ejection port, beavertail, rounded grips with stippled panels, trigger + guard, rails, ribbed pump, curved mag...).
One .glb per weapon and per attachment (gun_<id>.glb, att_<mod>_<id>.glb) into OUT. Material names are the contract
with scripts/gun_models.gd: fin (finish colour), poly, wood, steel, lens.
Coordinates are written in GODOT space (x right, y up, -z forward, grip hand at the origin) and converted here.
usage: bpyenv/bin/python tools/blender/guns.py OUTDIR"""
import sys, math, bpy, bmesh
from mathutils import Vector, Euler
OUT = sys.argv[1]
PI = math.pi

def G(p): return Vector((p[0], -p[2], p[1]))          # Godot -> Blender position

M = {}
def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    M.clear()
    for k, c in {"fin": (0.1, 0.1, 0.11), "poly": (0.05, 0.05, 0.055), "wood": (0.43, 0.24, 0.11), "steel": (0.72, 0.73, 0.75), "lens": (0.1, 0.2, 0.35)}.items():
        m = bpy.data.materials.new(k); m.use_nodes = True
        m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (*c, 1)
        M[k] = m

def _fin(o, mat, bevel, seg=2, smooth=True):
    o.data.materials.append(M[mat])
    bpy.context.view_layer.objects.active = o
    if bevel > 0:
        b = o.modifiers.new("b", "BEVEL"); b.width = bevel; b.segments = seg; b.limit_method = "ANGLE"
        bpy.ops.object.modifier_apply(modifier="b")
    if smooth: bpy.ops.object.shade_auto_smooth(angle=math.radians(40))
    return o

def box(mat, size, pos, rot=(0, 0, 0), bevel=0.0015, taper=None):
    """size/pos/rot in Godot space (rot about Godot X only, or full Euler for rare cases)."""
    bpy.ops.mesh.primitive_cube_add(size=1, location=G(pos))
    o = bpy.context.active_object
    o.scale = (size[0], size[2], size[1])
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if taper:      # narrow the top (y+) to taper[0] of the width and pull its front back by taper[1]
        for v in o.data.vertices:
            if v.co.z > 0: v.co.x *= taper[0]; v.co.y -= taper[1] if v.co.y > 0 else 0.0
    o.rotation_euler = Euler((rot[0], -rot[2], rot[1]), "XYZ")
    return _fin(o, mat, bevel)

def cyl(mat, r, h, pos, along_z=True, verts=20, bevel=0.0008, r2=None):
    if r2 is None: bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=r, depth=h, location=G(pos))
    else: bpy.ops.mesh.primitive_cone_add(vertices=verts, radius1=r, radius2=r2, depth=h, location=G(pos))
    o = bpy.context.active_object
    if along_z: o.rotation_euler = (-PI / 2, 0, 0)     # Godot +Z axis (toward the back)
    return _fin(o, mat, bevel)

def lathe(mat, prof, at, seg=24, axis="z"):
    """prof [[d, r]] along the axis (Godot +Z, or +Y)."""
    bm = bmesh.new(); rings = []
    for d, r in prof:
        ring = []
        for i in range(seg):
            a = 2 * PI * i / seg
            if axis == "z": p = (math.cos(a) * r, math.sin(a) * r, d)
            else: p = (math.cos(a) * r, d, math.sin(a) * r)
            ring.append(bm.verts.new(G((at[0] + p[0], at[1] + p[1], at[2] + p[2]))))
        rings.append(ring)
    for a, b in zip(rings, rings[1:]):
        for i in range(seg):
            j = (i + 1) % seg; bm.faces.new((a[i], a[j], b[j], b[i]))
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new("l"); bm.to_mesh(me); bm.free()
    o = bpy.data.objects.new("l", me); bpy.context.collection.objects.link(o)
    return _fin(o, mat, 0)

def torus(mat, R, r, pos, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_torus_add(major_radius=R, minor_radius=r, major_segments=24, minor_segments=8, location=G(pos))
    o = bpy.context.active_object; o.rotation_euler = Euler((rot[0], -rot[2], rot[1]), "XYZ")
    return _fin(o, mat, 0)

def guard(c, w, depth=0.05):
    """trigger guard: a flattened loop under the frame, plus the trigger blade."""
    bpy.ops.mesh.primitive_torus_add(major_radius=0.024, minor_radius=0.0035, major_segments=28, minor_segments=8, location=G((0, c[1] - 0.012, c[2])))
    o = bpy.context.active_object; o.rotation_euler = (0, PI / 2, 0); o.scale = (0.75, 1.0, 1.0)
    bm = bmesh.new(); bm.from_mesh(o.data)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.co.x < -0.006], context="VERTS")    # open at the top
    bm.to_mesh(o.data); bm.free()
    _fin(o, "poly", 0)
    t = box("steel", (0.006, 0.026, 0.006), (0, c[1] - 0.008, c[2] + 0.004), rot=(0.25, 0, 0), bevel=0.0018)

def export(name):
    objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs: o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    o = bpy.context.active_object; o.name = name
    bpy.ops.export_scene.gltf(filepath="%s/%s.glb" % (OUT, name), export_format="GLB")
    print("built", name, sum(len(p.vertices) - 2 for p in o.data.polygons), "tris")

# ------------------------------------------------------------------ weapons
def pistol():
    reset()
    box("fin", (0.031, 0.034, 0.19), (0, 0.032, -0.06), bevel=0.004)                       # slide
    box("fin", (0.027, 0.012, 0.03), (0, 0.043, -0.15), bevel=0.003)                       # front chamfer
    for i in range(7): box("poly", (0.0322, 0.026, 0.0022), (0, 0.031, 0.006 + i * 0.006), bevel=0.0004)   # serrations
    box("poly", (0.012, 0.012, 0.042), (0.012, 0.047, -0.03), bevel=0.001)                  # ejection port
    box("steel", (0.01, 0.009, 0.03), (0.011, 0.046, -0.03), bevel=0.001)                   # barrel hood in the port
    box("poly", (0.029, 0.022, 0.16), (0, 0.006, -0.05), bevel=0.003)                       # frame
    for i in range(3): box("poly", (0.03, 0.003, 0.004), (0, -0.004, -0.1 - i * 0.012), bevel=0)      # rail slots
    box("poly", (0.031, 0.108, 0.048), (0, -0.056, 0.036), rot=(0.28, 0, 0), bevel=0.009)   # grip
    box("poly", (0.0322, 0.07, 0.034), (0, -0.056, 0.036), rot=(0.28, 0, 0), bevel=0.003)   # stippled panel
    box("poly", (0.028, 0.012, 0.03), (0, 0.012, 0.045), rot=(-0.4, 0, 0), bevel=0.005)     # beavertail
    box("poly", (0.033, 0.009, 0.052), (0, -0.112, 0.05), rot=(0.28, 0, 0), bevel=0.003)   # mag base
    guard((0, -0.0, -0.025), 0.028)
    cyl("steel", 0.0062, 0.012, (0, 0.035, -0.157)); cyl("poly", 0.0035, 0.013, (0, 0.035, -0.158))   # muzzle + bore
    box("steel", (0.004, 0.008, 0.006), (0, 0.053, -0.145), bevel=0.001)                    # front sight
    box("steel", (0.022, 0.008, 0.008), (0, 0.053, 0.026), bevel=0.0015)                    # rear sight
    box("steel", (0.004, 0.006, 0.012), (0.016, 0.012, -0.03), bevel=0.001)                 # slide stop
    box("steel", (0.012, 0.016, 0.006), (0, 0.04, 0.042), rot=(-0.5, 0, 0), bevel=0.0015)  # hammer
    export("gun_pistol")

def shotgun():
    reset()
    box("fin", (0.042, 0.06, 0.24), (0, 0.018, -0.02), bevel=0.005)                        # receiver
    box("poly", (0.043, 0.02, 0.07), (0.0, 0.03, -0.02), bevel=0.001)                      # ejection port
    cyl("fin", 0.011, 0.5, (0, 0.035, -0.39)); cyl("poly", 0.0075, 0.502, (0, 0.035, -0.39))
    for i in range(10): box("fin", (0.006, 0.004, 0.012), (0, 0.048, -0.18 - i * 0.045), bevel=0)   # vent rib posts
    box("fin", (0.008, 0.003, 0.46), (0, 0.051, -0.38), bevel=0.0008)                      # rib
    cyl("fin", 0.0105, 0.38, (0, 0.006, -0.33)); cyl("fin", 0.012, 0.02, (0, 0.006, -0.52))   # mag tube + cap
    cyl("poly", 0.022, 0.17, (0, 0.008, -0.26), verts=24, bevel=0.003)                     # pump
    for i in range(7): torus("poly", 0.022, 0.0026, (0, 0.008, -0.195 - i * 0.022), rot=(PI / 2, 0, 0))
    box("steel", (0.006, 0.006, 0.006), (0, 0.055, -0.63), bevel=0.002)
    box("poly", (0.034, 0.1, 0.05), (0, -0.045, 0.1), rot=(0.35, 0, 0), bevel=0.01)       # grip
    guard((0, -0.003, 0.035), 0.032)
    stock("wood", (0, 0.0, 0.11), 0.33, 0.06, 0.13, 0.045)
    box("poly", (0.047, 0.136, 0.022), (0, -0.033, 0.445), bevel=0.008)                     # recoil pad
    export("gun_shotgun")

def stock(mat, at, length, h0, h1, w):
    """tapered stock: a lofted block from the grip (h0) to the butt (h1), comb on top, toe dropping."""
    bm = bmesh.new()
    def ring(z, h, drop):
        return [bm.verts.new(G((at[0] + x * w * 0.5, at[1] - drop + y * h * 0.5, at[2] + z))) for x, y in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    r0 = ring(0.0, h0, 0.0); r1 = ring(length, h1, (h1 - h0) * 0.5 + 0.01)
    for i in range(4):
        j = (i + 1) % 4; bm.faces.new((r0[i], r0[j], r1[j], r1[i]))
    bm.faces.new(list(reversed(r0))); bm.faces.new(r1)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new("s"); bm.to_mesh(me); bm.free()
    o = bpy.data.objects.new("s", me); bpy.context.collection.objects.link(o)
    return _fin(o, mat, 0.008, seg=3)

def curved_mag(top, length, w, d, bend):
    """box section swept down and forward along an arc (bend = total turn in radians)."""
    bm = bmesh.new(); rings = []; n = 8
    for i in range(n + 1):
        f = i / n; a = bend * f
        cy = top[1] - math.sin(a + 1e-6) / (bend / length) if bend else top[1] - f * length
        cz = top[2] - (1 - math.cos(a)) / (bend / length)
        ca, sa = math.cos(a), math.sin(a)
        ring = []
        for x, u in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            off_z = u * d * 0.5 * ca; off_y = -u * d * 0.5 * sa     # the section turns with the arc
            ring.append(bm.verts.new(G((x * w * 0.5, cy + off_y, cz + off_z))))
        rings.append(ring)
    for a, b in zip(rings, rings[1:]):
        for i in range(4):
            j = (i + 1) % 4; bm.faces.new((a[i], a[j], b[j], b[i]))
    bm.faces.new(rings[0]); bm.faces.new(list(reversed(rings[-1])))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new("m"); bm.to_mesh(me); bm.free()
    o = bpy.data.objects.new("m", me); bpy.context.collection.objects.link(o)
    return _fin(o, "poly", 0.003)

def rifle():
    reset()
    box("fin", (0.034, 0.046, 0.25), (0, 0.03, -0.03), bevel=0.003)                       # upper
    box("fin", (0.024, 0.008, 0.25), (0, 0.057, -0.03), bevel=0.001)                       # rail base
    for i in range(16): box("fin", (0.026, 0.005, 0.007), (0, 0.063, -0.15 + i * 0.016), bevel=0.0006)   # picatinny teeth
    box("poly", (0.035, 0.016, 0.05), (0.004, 0.03, -0.02), bevel=0.001)                   # ejection port cover
    cyl("fin", 0.006, 0.02, (0.02, 0.035, 0.03), along_z=False)                            # forward assist
    box("fin", (0.03, 0.04, 0.17), (0, -0.005, 0.0), bevel=0.003)                          # lower
    box("fin", (0.03, 0.03, 0.05), (0, -0.03, -0.065), rot=(-0.12, 0, 0), bevel=0.003)    # mag well
    cyl("poly", 0.025, 0.24, (0, 0.026, -0.265), verts=8, bevel=0.002)                     # handguard (octagonal)
    for i in range(7):
        box("poly", (0.052, 0.007, 0.012), (0, 0.026, -0.17 - i * 0.03), bevel=0)         # M-LOK slots (cut look)
    cyl("steel", 0.0085, 0.16, (0, 0.026, -0.45)); cyl("fin", 0.012, 0.024, (0, 0.026, -0.4))   # barrel + gas block
    cyl("fin", 0.0125, 0.05, (0, 0.026, -0.54), verts=6, bevel=0.0008)                     # brake
    cyl("poly", 0.006, 0.052, (0, 0.026, -0.541))
    box("fin", (0.012, 0.04, 0.012), (0, 0.06, -0.385), bevel=0.0015)                      # front sight post
    box("fin", (0.024, 0.03, 0.03), (0, 0.078, 0.06), bevel=0.003)                         # rear sight
    curved_mag((0, -0.028, -0.06), 0.16, 0.025, 0.06, 0.5)                               # curved magazine
    box("poly", (0.028, 0.008, 0.066), (0, -0.18, -0.1), rot=(-0.5, 0, 0), bevel=0.002)
    box("poly", (0.03, 0.095, 0.04), (0, -0.06, 0.07), rot=(0.38, 0, 0), bevel=0.008)     # pistol grip
    for i in range(3): box("poly", (0.031, 0.005, 0.03), (0, -0.04 - i * 0.022, 0.065 + i * 0.008), rot=(0.38, 0, 0), bevel=0.001)
    guard((0, -0.02, 0.015), 0.03)
    cyl("poly", 0.0145, 0.17, (0, 0.015, 0.2), verts=16)                                   # buffer tube
    stock("poly", (0, 0.0, 0.2), 0.16, 0.05, 0.11, 0.04)
    box("poly", (0.042, 0.115, 0.016), (0, -0.032, 0.365), bevel=0.006)
    box("steel", (0.006, 0.008, 0.02), (0.017, 0.003, 0.04), bevel=0.001)                 # selector
    export("gun_rifle")

def bat():
    reset()
    prof = [[0.0, 0.0], [0.0, 0.021], [0.01, 0.022], [0.016, 0.014], [0.03, 0.0125], [0.25, 0.014], [0.45, 0.02], [0.6, 0.028],
            [0.82, 0.0335], [0.85, 0.032], [0.858, 0.022], [0.86, 0.0]]
    lathe("wood", prof, (0, 0, 0.12), seg=24)
    for i in range(6): torus("poly", 0.0145, 0.0022, (0, 0, 0.1 - i * 0.017), rot=(PI / 2, 0, 0))
    export("gun_bat")

def knife():
    reset()
    box("poly", (0.019, 0.027, 0.11), (0, 0, 0.03), bevel=0.007)
    for i in range(4): box("poly", (0.0195, 0.004, 0.006), (0, -0.013, 0.0 + i * 0.022), bevel=0.0015)
    box("steel", (0.022, 0.032, 0.008), (0, 0, -0.026), bevel=0.0018)
    cyl("steel", 0.003, 0.0195, (0, 0.004, 0.06), along_z=False)
    # clip-point blade: tapered from the spine to a thin edge, drop to the point
    bm = bmesh.new()
    pts = [(0, 0.013), (0.09, 0.013), (0.12, 0.004), (0.135, -0.004), (0.12, -0.009), (0.06, -0.013), (0, -0.013)]
    top = [bm.verts.new(G((0.0025 if y > 0 else 0.0004, 0.002 + y, -0.03 - x))) for x, y in pts]
    bot = [bm.verts.new(G((-0.0025 if y > 0 else -0.0004, 0.002 + y, -0.03 - x))) for x, y in pts]
    bm.faces.new(top); bm.faces.new(list(reversed(bot)))
    for i in range(len(pts)):
        j = (i + 1) % len(pts); bm.faces.new((top[j], top[i], bot[i], bot[j]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new("b"); bm.to_mesh(me); bm.free()
    o = bpy.data.objects.new("b", me); bpy.context.collection.objects.link(o); _fin(o, "steel", 0, smooth=False)
    export("gun_knife")

def grenade():
    reset()
    lathe("fin", [[0.0, 0.0], [0.006, 0.02], [0.02, 0.03], [0.045, 0.033], [0.07, 0.029], [0.085, 0.017], [0.09, 0.0]], (0, -0.045, 0), seg=24, axis="y")
    for i in range(5): torus("fin", 0.0305 + (0.002 if i == 2 else 0), 0.0016, (0, -0.025 + i * 0.01, 0), rot=(0, 0, 0))   # segment grooves
    cyl("steel", 0.011, 0.016, (0, 0.05, 0), along_z=False)                                # fuze body
    box("steel", (0.012, 0.075, 0.006), (0, 0.0, -0.035), rot=(0.12, 0, 0), bevel=0.0015)  # spoon
    torus("steel", 0.011, 0.0015, (0.02, 0.055, 0), rot=(0, 0, PI / 2))                    # pin ring
    export("gun_grenade")

# ------------------------------------------------------------------ attachments (positions match gun_models.gd)
def attachments():
    for gid, y, sy in (("rifle", 0.09, 0.07), ("pistol", 0.072, 0.055), ("shotgun", 0.072, 0.055)):
        reset()
        cyl("poly", 0.017, 0.15, (0, y, -0.03), verts=24); cyl("poly", 0.021, 0.035, (0, y, -0.11), verts=24, bevel=0.002)
        cyl("poly", 0.019, 0.03, (0, y, 0.055), verts=24, bevel=0.002)                     # eyepiece
        cyl("lens", 0.0185, 0.002, (0, y, -0.128), verts=24); cyl("lens", 0.016, 0.002, (0, y, 0.071), verts=24)
        cyl("poly", 0.008, 0.02, (0, y + 0.02, -0.03), along_z=False); cyl("poly", 0.008, 0.02, (0.02, y, -0.03), along_z=False)   # turrets
        box("poly", (0.014, 0.025, 0.02), (0, sy, -0.0), bevel=0.002); box("poly", (0.014, 0.025, 0.02), (0, sy, -0.07), bevel=0.002)
        export("att_scope_" + gid)
    for gid, z0, y0, r in (("pistol", -0.2, 0.035, 0.014), ("rifle", -0.62, 0.026, 0.017), ("shotgun", -0.7, 0.035, 0.017)):
        reset()
        cyl("poly", r, 0.17, (0, y0, z0), verts=24, bevel=0.003)
        for k in range(3): torus("poly", r, 0.0012, (0, y0, z0 - 0.06 + k * 0.06), rot=(PI / 2, 0, 0))
        cyl("poly", r * 0.4, 0.172, (0, y0, z0))
        export("att_suppressor_" + gid)
    reset(); box("poly", (0.028, 0.06, 0.04), (0, -0.13, 0.055), rot=(0.28, 0, 0), bevel=0.004); export("att_ext_mag_pistol")
    for gid in ("rifle", "shotgun"):
        reset()
        box("poly", (0.024, 0.045, 0.034), (0, -0.165, -0.11), rot=(-0.45, 0, 0), bevel=0.003)
        box("poly", (0.024, 0.045, 0.034), (0, -0.2, -0.13), rot=(-0.6, 0, 0), bevel=0.003)
        export("att_ext_mag_" + gid)
    for gid, z in (("rifle", -0.27), ("shotgun", -0.26), ("pistol", -0.1)):
        reset()
        cyl("poly", 0.012, 0.07, (0, -0.03, z), along_z=False, verts=16, bevel=0.002)
        for i in range(4): torus("poly", 0.012, 0.0014, (0, -0.01 - i * 0.014, z))
        export("att_grip_" + gid)
    for gid, z in (("rifle", -0.22), ("shotgun", -0.22), ("pistol", -0.11)):
        reset()
        cyl("poly", 0.011, 0.07, (0.03, 0.01, z), verts=16); cyl("poly", 0.0125, 0.018, (0.03, 0.01, z - 0.03), verts=16, bevel=0.002)
        cyl("lens", 0.0095, 0.002, (0.03, 0.01, z - 0.04), verts=16); box("poly", (0.014, 0.012, 0.03), (0.018, 0.01, z), bevel=0.002)
        export("att_flashlight_" + gid)

pistol(); shotgun(); rifle(); bat(); knife(); grenade(); attachments()
