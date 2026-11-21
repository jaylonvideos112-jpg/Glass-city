"""Blender (bpy) street trash and clutter for GLASS CITY (owner, 2026-11-21: "trash and clutter in streets like
real Toledo, with every section having like 5 different variants ... on sidewalks and grass near streets and
walkways too"). Placed by tools/pipeline/build_city.py (clutter jobs), five or more variants per kind of place:
  litter_a..e      small litter clusters (gutters, sidewalks, grass strips, path edges, lots): cans, cups,
                   chip bags, bottles, napkins, butts, newspaper and flyers
  res_*            residential curb / tree lawn bulk trash: couch, mattress, CRT TV, bag pile, chair + boxes
  alley_*          alleys: tire stack, broken pallet, bag pile, leaning mattress, junk pile
  com_*            business strips: flattened boxes, shopping cart, newspaper bundle, dropped drink, bag pile
  lot_*            parking lots: shopping cart, tipped cart, single tire, knocked cone, (litter)
  ind_*            industrial yards: pallet stack, oil drums, tires, scrap pile, crate
Origin on the ground, +Y = front. usage: bpyenv/bin/python tools/blender/clutter.py OUTDIR"""
import sys, os, math, random
sys.argv = [sys.argv[0], sys.argv[1]]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy
from street_props import reset, mat, box, cyl, export

R = random.Random(11)
def M():
    return dict(
        can=mat("cl_can_red", (0.62, 0.08, 0.07), metal=0.7, rough=0.35), can2=mat("cl_can_silver", (0.7, 0.72, 0.74), metal=0.8, rough=0.3),
        can3=mat("cl_can_blue", (0.12, 0.22, 0.55), metal=0.7, rough=0.35),
        cup=mat("cl_cup", (0.92, 0.9, 0.86), rough=0.6), cupr=mat("cl_cup_red", (0.75, 0.1, 0.1), rough=0.6),
        lid=mat("cl_lid", (0.85, 0.85, 0.82), rough=0.4), straw=mat("cl_straw", (0.9, 0.2, 0.2), rough=0.5),
        chips=mat("cl_chips", (0.95, 0.7, 0.1), metal=0.5, rough=0.35), chips2=mat("cl_chips2", (0.15, 0.35, 0.75), metal=0.5, rough=0.35),
        paper=mat("cl_paper", (0.88, 0.86, 0.8), rough=0.9), news=mat("cl_news", (0.72, 0.71, 0.68), rough=0.95),
        brownbag=mat("cl_brownbag", (0.62, 0.47, 0.3), rough=0.9), bottle=mat("cl_bottle", (0.55, 0.75, 0.6), rough=0.15),
        butt=mat("cl_butt", (0.85, 0.6, 0.35), rough=0.9), bag=mat("cl_trashbag", (0.03, 0.03, 0.035), rough=0.3),
        bagw=mat("cl_trashbag_w", (0.8, 0.8, 0.78), rough=0.4), card=mat("cl_cardboard", (0.6, 0.46, 0.3), rough=0.95),
        fabric=mat("cl_couch", (0.42, 0.3, 0.22), rough=0.95), fabric2=mat("cl_couch2", (0.35, 0.4, 0.3), rough=0.95),
        matt=mat("cl_mattress", (0.85, 0.82, 0.72), rough=0.9), stain=mat("cl_stain", (0.62, 0.52, 0.35), rough=0.95),
        tvplast=mat("cl_tv", (0.12, 0.12, 0.12), rough=0.5), screen=mat("cl_screen", (0.08, 0.1, 0.1), rough=0.1),
        tire=mat("cl_tire", (0.06, 0.06, 0.06), rough=0.85), rim=mat("cl_rim", (0.5, 0.5, 0.5), metal=0.8, rough=0.4),
        wood=mat("cl_pallet", (0.6, 0.5, 0.36), rough=0.95), woodd=mat("cl_wood_dark", (0.4, 0.33, 0.25), rough=0.95),
        steel=mat("cl_cart", (0.7, 0.72, 0.74), metal=0.85, rough=0.35), red=mat("cl_cart_red", (0.7, 0.1, 0.08), rough=0.5),
        drum=mat("cl_drum", (0.2, 0.32, 0.55), metal=0.5, rough=0.5), drum2=mat("cl_drum_rust", (0.45, 0.22, 0.12), metal=0.3, rough=0.8),
        cone=mat("cl_cone", (0.95, 0.4, 0.05), rough=0.6), white=mat("cl_white", (0.92, 0.92, 0.9), rough=0.6),
        rust=mat("cl_rust", (0.42, 0.24, 0.14), metal=0.3, rough=0.85), bucket=mat("cl_bucket", (0.9, 0.85, 0.3), rough=0.6))

def rot(o, x=0, y=0, z=0):
    o.rotation_euler = (math.radians(x), math.radians(y), math.radians(z)); return o

def can(m, x, y, k=None):    # crushed can lying on its side
    o = cyl(0.033, 0.11 * R.uniform(0.6, 1.0), (x, y, 0.03), k or R.choice([m["can"], m["can2"], m["can3"]]), verts=8)
    return rot(o, 90, 0, R.uniform(0, 180))

def cup(m, x, y, red=False):
    o = cyl(0.045, 0.14, (x, y, 0.045), m["cupr"] if red else m["cup"], verts=8, r2=0.035)
    return rot(o, 90, 0, R.uniform(0, 180))

def flat(m, k, x, y, w, d, z=0.004, a=None):
    return rot(box((w, d, 0.006), (x, y, z), m[k], bevel=0), R.uniform(-4, 4), R.uniform(-4, 4), a if a is not None else R.uniform(0, 180))

def bag_pile(m, n, spread):
    for i in range(n):
        r = R.uniform(0.28, 0.38)
        o = cyl(r, r * 1.6, (R.uniform(-spread, spread), R.uniform(-spread, spread), r * 0.7), m["bag"] if R.random() < 0.8 else m["bagw"], verts=10, r2=r * 0.55)
        rot(o, R.uniform(-15, 15), R.uniform(-15, 15), R.uniform(0, 90))

def tire(m, x, y, z, lay=True):
    o = cyl(0.33, 0.21, (x, y, z), m["tire"], verts=16)
    if not lay: rot(o, 90, 0, R.uniform(0, 180))
    return o

def pallet(m, x, y, z, broken=False):
    for i in range(5):
        if broken and i in (1, 3): continue
        box((1.2, 0.12, 0.022), (x, y - 0.48 + i * 0.24, z + 0.13), m["wood"], bevel=0)
    for j in (-0.5, 0, 0.5):
        box((0.09, 1.0, 0.1), (x + j, y, z + 0.06), m["woodd"], bevel=0)

def cart(m, tipped=False):
    parts = []
    parts.append(box((0.55, 0.85, 0.02), (0, 0, 0.45), m["steel"], bevel=0))
    for sx in (-1, 1):
        parts.append(box((0.02, 0.85, 0.45), (sx * 0.27, 0, 0.68), m["steel"], bevel=0))
    parts.append(box((0.55, 0.02, 0.45), (0, 0.42, 0.68), m["steel"], bevel=0))
    parts.append(box((0.5, 0.02, 0.4), (0, -0.42, 0.68), m["steel"], bevel=0))
    parts.append(box((0.6, 0.04, 0.04), (0, -0.5, 1.0), m["red"], bevel=0))       # handle
    for sx in (-1, 1):
        for sy in (-1, 1):
            parts.append(box((0.02, 0.02, 0.4), (sx * 0.22, sy * 0.35, 0.23), m["steel"], bevel=0))
            parts.append(cyl(0.05, 0.03, (sx * 0.22, sy * 0.35, 0.05), m["tire"], verts=8, rot=(0, math.pi / 2, 0)))
    if tipped:
        for o in parts:
            o.select_set(True)
        bpy.context.view_layer.objects.active = parts[0]
        bpy.ops.object.join(); o = bpy.context.active_object
        o.rotation_euler = (0, math.radians(90), math.radians(20)); o.location.z = 0.3

# ------------------------------------------------------------------ litter clusters
def litter(name, kind):
    reset(); m = M()
    if kind == 0:
        can(m, 0.1, 0.05); cup(m, -0.25, 0.1); flat(m, "paper", 0.3, -0.2, 0.12, 0.09)
        rot(cyl(0.004, 0.2, (-0.15, 0.25, 0.01), m["straw"], verts=4), 90, 0, 30)
    elif kind == 1:
        flat(m, "chips", 0.0, 0.0, 0.16, 0.22, z=0.01); flat(m, "paper", 0.35, 0.15, 0.1, 0.1); flat(m, "paper", -0.3, -0.1, 0.12, 0.08)
        flat(m, "chips2", -0.1, 0.4, 0.08, 0.12)
    elif kind == 2:
        rot(cyl(0.035, 0.24, (0.0, 0.0, 0.035), m["bottle"], verts=8), 90, 0, 40)
        for i in range(6): rot(cyl(0.004, 0.025, (R.uniform(-0.4, 0.4), R.uniform(-0.3, 0.3), 0.004), m["butt"], verts=4), 90, 0, R.uniform(0, 180))
        flat(m, "paper", 0.3, -0.25, 0.07, 0.16)
    elif kind == 3:
        rot(box((0.2, 0.12, 0.25), (0.0, 0.0, 0.06), m["brownbag"], bevel=0), 80, 0, 25)
        cup(m, 0.3, 0.2, red=True); rot(cyl(0.05, 0.01, (0.32, 0.38, 0.005), m["lid"], verts=10), 0, 0, 0)
        flat(m, "paper", -0.3, 0.2, 0.15, 0.1)
    else:
        for i in range(4): flat(m, "news", R.uniform(-0.5, 0.5), R.uniform(-0.4, 0.4), 0.3, 0.4, z=0.004 + i * 0.002)
        flat(m, "paper", 0.5, 0.4, 0.15, 0.2); can(m, -0.4, 0.4)
    export(name)

# ------------------------------------------------------------------ residential bulk trash (curb / tree lawn)
def res(name, kind):
    reset(); m = M()
    if kind == 0:      # couch
        f = R.choice([m["fabric"], m["fabric2"]])
        box((1.9, 0.8, 0.42), (0, 0, 0.21), f, bevel=0.04); box((1.9, 0.22, 0.5), (0, -0.3, 0.67), f, bevel=0.04)
        for sx in (-1, 1): box((0.2, 0.8, 0.3), (sx * 0.85, 0, 0.55), f, bevel=0.04)
        rot(box((0.6, 0.6, 0.12), (0.3, 0.6, 0.06), f, bevel=0.03), 0, 0, 25)       # a cushion fell off
    elif kind == 1:    # mattress + box spring lying flat, stained
        box((1.4, 1.95, 0.2), (0, 0, 0.1), m["matt"], bevel=0.04); flat(m, "stain", 0.2, 0.3, 0.5, 0.4, z=0.205, a=10)
        rot(box((1.4, 1.95, 0.15), (0.15, 0.1, 0.28), m["matt"], bevel=0.03), 0, 0, 8)
    elif kind == 2:    # old CRT TV and its box
        box((0.62, 0.5, 0.5), (0, 0, 0.25), m["tvplast"], bevel=0.03); box((0.5, 0.02, 0.38), (0, 0.26, 0.27), m["screen"], bevel=0)
        rot(box((0.7, 0.6, 0.55), (0.75, -0.1, 0.27), m["card"], bevel=0.01), 0, 0, 15)
        bag_pile(m, 1, 0.1)
    elif kind == 3:    # bag pile
        bag_pile(m, 5, 0.45)
    else:              # broken chair + cardboard boxes
        rot(box((0.45, 0.45, 0.05), (0, 0, 0.25), m["woodd"], bevel=0), 0, 70, 20)
        for i in range(3):
            rot(box((0.5, 0.4, 0.35), (0.6 + i * 0.1, 0.1 - i * 0.3, 0.175 + (0.35 if i == 2 else 0)), m["card"], bevel=0.01), 0, 0, R.uniform(-20, 20))
        flat(m, "card", -0.6, 0.2, 0.8, 0.6, z=0.01)
    export(name)

# ------------------------------------------------------------------ alleys
def alley(name, kind):
    reset(); m = M()
    if kind == 0:
        for i in range(3): tire(m, R.uniform(-0.05, 0.05), R.uniform(-0.05, 0.05), 0.105 + i * 0.21)
        tire(m, 0.7, 0.2, 0.33, lay=False)
    elif kind == 1:
        pallet(m, 0, 0, 0.0, broken=True); rot(box((1.2, 0.12, 0.022), (0.5, 0.8, 0.02), m["wood"], bevel=0), 0, 0, 30)
    elif kind == 2:
        bag_pile(m, 4, 0.4); can(m, 0.6, 0.4)
    elif kind == 3:    # mattress leaning on a fence/garage
        rot(box((1.4, 0.2, 1.95), (0, 0.4, 0.9), m["matt"], bevel=0.04), -15, 0, 0); flat(m, "stain", 0.1, 0.52, 0.4, 0.4, z=1.0, a=0)
    else:              # junk pile: boards, bucket, paint cans
        for i in range(5): rot(box((1.6, 0.1, 0.025), (R.uniform(-0.2, 0.2), R.uniform(-0.3, 0.3), 0.02 + i * 0.03), m["woodd"], bevel=0), 0, 0, R.uniform(-30, 30))
        cyl(0.15, 0.36, (0.7, 0.3, 0.18), m["bucket"], verts=12, r2=0.13)
        for i in range(2): cyl(0.09, 0.19, (0.55 + i * 0.2, -0.3, 0.095), m["rust"], verts=10)
    export(name)

# ------------------------------------------------------------------ business strips
def com(name, kind):
    reset(); m = M()
    if kind == 0:
        for i in range(4): rot(box((0.9, 0.7, 0.012), (0, 0, 0.01 + i * 0.013), m["card"], bevel=0), 0, 0, R.uniform(-15, 15))
        box((0.5, 0.4, 0.4), (0.7, 0.2, 0.2), m["card"], bevel=0.01)
    elif kind == 1:
        cart(m)
    elif kind == 2:    # tied newspaper bundle + loose sheets
        box((0.4, 0.3, 0.25), (0, 0, 0.125), m["news"], bevel=0.01)
        for i in range(3): flat(m, "news", R.uniform(-0.6, 0.6), R.uniform(-0.4, 0.4), 0.35, 0.5)
    elif kind == 3:    # dropped drink: cup, lid, spill
        cup(m, 0, 0, red=True); rot(cyl(0.05, 0.01, (0.15, 0.1, 0.005), m["lid"], verts=10), 0, 0, 0)
        flat(m, "stain", 0.25, -0.05, 0.5, 0.35, z=0.002, a=20); flat(m, "paper", -0.3, 0.2, 0.12, 0.12)
    else:
        bag_pile(m, 3, 0.3); flat(m, "card", 0.6, 0.0, 0.7, 0.5, z=0.01)
    export(name)

# ------------------------------------------------------------------ parking lots
def lot(name, kind):
    reset(); m = M()
    if kind == 0: cart(m)
    elif kind == 1: cart(m, tipped=True)
    elif kind == 2: tire(m, 0, 0, 0.105)
    elif kind == 3:
        rot(cyl(0.16, 0.6, (0, 0, 0.16), m["cone"], verts=10, r2=0.03), 90, 0, 30)
        box((0.36, 0.36, 0.03), (0.0, -0.3, 0.16), m["cone"], bevel=0).rotation_euler = (math.radians(90), 0, math.radians(30))
    else:
        bag_pile(m, 2, 0.25); can(m, 0.5, 0.2); cup(m, -0.4, 0.3)
    export(name)

# ------------------------------------------------------------------ industrial yards
def ind(name, kind):
    reset(); m = M()
    if kind == 0:
        for i in range(4): pallet(m, R.uniform(-0.05, 0.05), R.uniform(-0.05, 0.05), i * 0.16)
    elif kind == 1:
        for i, (x, y) in enumerate(((0, 0), (0.62, 0.05), (0.3, 0.55))):
            cyl(0.29, 0.88, (x, y, 0.44), m["drum"] if i != 1 else m["drum2"], verts=14)
        rot(cyl(0.29, 0.88, (-0.6, 0.4, 0.29), m["drum2"], verts=14), 90, 0, 40)
    elif kind == 2:
        for i in range(6): tire(m, R.uniform(-0.8, 0.8), R.uniform(-0.6, 0.6), 0.105 + (i % 2) * 0.2)
    elif kind == 3:    # scrap pile
        for i in range(9):
            rot(box((R.uniform(0.6, 2.0), R.uniform(0.05, 0.3), R.uniform(0.03, 0.2)), (R.uniform(-0.7, 0.7), R.uniform(-0.6, 0.6), 0.1 + i * 0.05), m["rust"], bevel=0), R.uniform(-20, 20), R.uniform(-20, 20), R.uniform(0, 180))
    else:
        box((1.2, 1.0, 0.9), (0, 0, 0.45), m["wood"], bevel=0.01); box((0.8, 0.8, 0.6), (0.2, 0.9, 0.3), m["woodd"], bevel=0.01)
    export(name)


if __name__ == "__main__":
    import street_props; street_props.OUT = sys.argv[1]
    for i, c in enumerate("abcde"):
        litter("litter_" + c, i)
    for i, n in enumerate(("couch", "mattress", "tv", "bags", "chair")): res("res_" + n, i)
    for i, n in enumerate(("tires", "pallet", "bags", "mattress", "junk")): alley("alley_" + n, i)
    for i, n in enumerate(("boxes", "cart", "news", "drink", "bags")): com("com_" + n, i)
    for i, n in enumerate(("cart", "cart_tipped", "tire", "cone", "litter")): lot("lot_" + n, i)
    for i, n in enumerate(("pallets", "drums", "tires", "scrap", "crates")): ind("ind_" + n, i)
