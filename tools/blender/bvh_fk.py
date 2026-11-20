"""Tiny BVH reader + forward kinematics (numpy). Returns per-frame global joint positions and rotations.
Used by rigged_people.py to retarget CMU motion capture (cgspeed BVH conversion, free for any use)."""
import numpy as np, math

def _rot(axis, deg):
    a = math.radians(deg); c, s = math.cos(a), math.sin(a)
    if axis == "X": return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
    if axis == "Y": return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])

def load(path):
    toks = open(path).read().split()
    i = 0; joints = []; stack = []
    def nxt():
        nonlocal i; t = toks[i]; i += 1; return t
    while True:
        t = nxt()
        if t in ("ROOT", "JOINT", "End"):
            name = nxt() if t != "End" else (joints[stack[-1]]["name"] + "_end")
            if t == "End": pass
            nxt()  # {
            j = {"name": name, "parent": stack[-1] if stack else -1, "offset": None, "channels": [], "end": t == "End"}
            joints.append(j); stack.append(len(joints) - 1)
        elif t == "OFFSET":
            joints[stack[-1]]["offset"] = np.array([float(nxt()), float(nxt()), float(nxt())])
        elif t == "CHANNELS":
            n = int(nxt()); joints[stack[-1]]["channels"] = [nxt() for _ in range(n)]
        elif t == "}":
            stack.pop()
        elif t == "MOTION":
            break
    nxt(); nf = int(nxt()); nxt(); nxt(); ft = float(nxt())
    vals = np.array([float(x) for x in toks[i:]]).reshape(nf, -1)
    return joints, vals, ft

def fk(joints, vals):
    """global positions (F, J, 3) and rotations (F, J, 3, 3) in BVH space."""
    F = len(vals); J = len(joints)
    pos = np.zeros((F, J, 3)); rot = np.zeros((F, J, 3, 3))
    for f in range(F):
        c = 0
        for j, jt in enumerate(joints):
            R = np.eye(3); T = np.zeros(3)
            for ch in jt["channels"]:
                v = vals[f, c]; c += 1
                if ch.endswith("position"): T["XYZ".index(ch[0])] = v
                else: R = R @ _rot(ch[0], v)
            p = jt["parent"]
            if p < 0:
                rot[f, j] = R; pos[f, j] = jt["offset"] + T
            else:
                rot[f, j] = rot[f, p] @ R
                pos[f, j] = pos[f, p] + rot[f, p] @ jt["offset"]
    return pos, rot

def index(joints): return {j["name"]: k for k, j in enumerate(joints)}
