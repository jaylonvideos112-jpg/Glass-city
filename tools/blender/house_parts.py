"""Blender (bpy) house parts placed on every house wall by tools/pipeline/build_city.py: double-hung windows with
real casings/sills/sashes, attic windows, panel front doors, porch posts, porch railings, front steps.
Origin = on the wall plane, bottom centre; Blender +Y = out of the wall (Godot -Z = the prop's front).
usage: bpyenv/bin/python tools/blender/house_parts.py OUTDIR"""
import sys, math, os
sys.argv = [sys.argv[0], sys.argv[1]]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy
from street_props import reset, mat, box, cyl, export


def mats():
    return dict(trim=mat("hp_trim", (0.86, 0.86, 0.83), rough=0.55),
                glass=mat("hp_glass", (0.035, 0.045, 0.055), rough=0.06),
                blind=mat("hp_blind", (0.78, 0.76, 0.70), rough=0.8),
                step=mat("hp_step", (0.36, 0.355, 0.34), rough=0.92))


def window_unit(m, cx, w, h, z0=0.0, blinds=0.0):
    """One double-hung window, glass w x h, bottom of the sill at z0."""
    cas, t = 0.1, 0.035
    sill_h = 0.05
    zb = z0 + sill_h                       # bottom of glass opening
    # glass (a pane sits a hair in front of the wall plane; the blind behind the upper sash shows as a pale band)
    box((w, 0.01, h), (cx, 0.006, zb + h / 2), m["glass"], bevel=0)
    if blinds > 0:
        box((w - 0.02, 0.008, h * blinds), (cx, 0.003, zb + h - h * blinds / 2), m["blind"], bevel=0)
    # casing boards around the opening
    box((cas, t, h + cas), (cx - w / 2 - cas / 2, t / 2, zb + (h + cas) / 2), m["trim"], bevel=0)
    box((cas, t, h + cas), (cx + w / 2 + cas / 2, t / 2, zb + (h + cas) / 2), m["trim"], bevel=0)
    box((w + 2 * cas + 0.06, t + 0.015, cas + 0.03), (cx, (t + 0.015) / 2, zb + h + cas / 2 + 0.03), m["trim"], bevel=0)   # head
    box((w + 2 * cas + 0.1, 0.022, 0.02), (cx, 0.011 + 0.03, zb + h + cas + 0.055), m["trim"], bevel=0)                 # drip cap
    box((w + 2 * cas + 0.08, 0.075, sill_h), (cx, 0.0375, z0 + sill_h / 2), m["trim"], bevel=0)                         # sill
    # sashes: frame bars + meeting rail
    s = 0.045
    for zz in (zb + s / 2, zb + h - s / 2, zb + h / 2):
        box((w, 0.03, s if zz != zb + h / 2 else s * 1.4), (cx, 0.018, zz), m["trim"], bevel=0)
    for xx in (cx - w / 2 + s / 2, cx + w / 2 - s / 2):
        box((s, 0.03, h), (xx, 0.018, zb + h / 2), m["trim"], bevel=0)


def win(name, units=1, w=0.82, h=1.45, blinds=0.0):
    reset(); m = mats()
    gap = 0.16
    tot = units * w + (units - 1) * gap
    for i in range(units):
        window_unit(m, -tot / 2 + w / 2 + i * (w + gap), w, h, blinds=blinds)
    export(name)


def door(name, col):
    reset(); m = mats()
    dm = mat(name, col, rough=0.62)
    knob = mat("hp_brass", (0.75, 0.58, 0.28), metal=1.0, rough=0.3)
    w, h = 0.92, 2.05
    box((w, 0.04, h), (0, 0.02, h / 2), dm, bevel=0)
    for zc in (0.45, 1.05):                                   # raised panels
        for xc in (-0.21, 0.21):
            box((0.3, 0.02, 0.5), (xc, 0.045, zc), dm, bevel=0)
    box((0.66, 0.012, 0.42), (0, 0.042, 1.68), m["glass"], bevel=0)      # glass light in the top third
    cyl(0.03, 0.06, (0.36, 0.08, 1.0), knob, verts=10, rot=(math.pi / 2, 0, 0))
    cas, t = 0.12, 0.04
    box((cas, t, h + cas), (-w / 2 - cas / 2, t / 2, (h + cas) / 2), m["trim"], bevel=0)
    box((cas, t, h + cas), (w / 2 + cas / 2, t / 2, (h + cas) / 2), m["trim"], bevel=0)
    box((w + 2 * cas + 0.08, t + 0.02, 0.16), (0, (t + 0.02) / 2, h + 0.1), m["trim"], bevel=0)
    export(name)


def post():
    """Porch column, deck (0) to porch beam (2.35): square shaft with base and capital."""
    reset(); m = mats()
    box((0.24, 0.24, 0.22), (0, 0, 0.11), m["trim"], bevel=0)
    box((0.15, 0.15, 1.95), (0, 0, 0.22 + 0.975), m["trim"], bevel=0)
    box((0.22, 0.22, 0.08), (0, 0, 2.21), m["trim"], bevel=0)
    box((0.26, 0.26, 0.06), (0, 0, 2.32), m["trim"], bevel=0)
    export("hp_post")


def rail():
    """1.0 m railing segment centred on the origin, along X."""
    reset(); m = mats()
    box((1.0, 0.09, 0.05), (0, 0, 0.88), m["trim"], bevel=0)
    box((1.0, 0.07, 0.05), (0, 0, 0.1), m["trim"], bevel=0)
    for i in range(8):
        box((0.035, 0.035, 0.73), (-0.4375 + i * 0.125, 0, 0.49), m["trim"], bevel=0)
    export("hp_rail")


def steps():
    """Three concrete steps from the porch deck (0.55) down to grade, running out along +Y."""
    reset(); m = mats()
    for i in range(3):
        top = 0.55 - i * 0.18
        box((1.5, 0.3, top), (0, 0.15 + i * 0.3, top / 2), m["step"], bevel=0)
    export("hp_steps")


if __name__ == "__main__":
    OUT = sys.argv[1]
    import street_props; street_props.OUT = OUT
    win("hp_win")
    win("hp_win_b", blinds=0.45)                 # same window, blind half down (variety along a street)
    win("hp_win2", units=2)                      # mulled pair (living-room front window)
    win("hp_attic", w=0.62, h=0.95)
    door("hp_door_r", (0.36, 0.07, 0.06))
    door("hp_door_k", (0.06, 0.08, 0.07))
    door("hp_door_w", (0.82, 0.82, 0.79))
    post(); rail(); steps()
