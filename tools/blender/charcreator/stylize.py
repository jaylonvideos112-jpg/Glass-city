"""Stylized ('painted', Bully-like) look for creator characters.
- proportions: head and hands scaled up about their joints (weights from the skin, so every attached mesh -
  hair, brows, eyes, clothes - moves with the body)
- painted skin: the MakeHuman skin texture smoothed into soft brush areas and re-toned to the photo skin colour;
  normal maps flattened so pores don't fight the painted look"""
import bpy, numpy as np
S_LUM = 0.82
LIP_RECOLOUR = False   # the texture-based lip mask also caught the chin; off until it uses the UV lip region
from mathutils import Vector

def _bone_head(arm, name):
    b = arm.data.bones.get(name)
    return (arm.matrix_world @ b.head_local) if b else None

def _scale_part(arm, bones, pivot_bone, k):
    piv = _bone_head(arm, pivot_bone)
    if piv is None or abs(k - 1) < 1e-3: return
    for o in bpy.data.objects:
        if o.type != "MESH": continue
        gids = [o.vertex_groups[b].index for b in bones if b in o.vertex_groups]
        if not gids: continue
        mw = o.matrix_world; mi = mw.inverted()
        for v in o.data.vertices:
            w = sum(g.weight for g in v.groups if g.group in gids)
            if w <= 0: continue
            p = mw @ v.co
            q = piv + (p - piv) * (1 + (k - 1) * min(1.0, w))
            v.co = mi @ q

def _painted_skin(obj, rgb, lips=None):
    from scipy.ndimage import gaussian_filter, median_filter
    for slot in obj.material_slots:
        m = slot.material
        if not m or not m.node_tree: continue
        for n in m.node_tree.nodes:
            if n.type == "NORMAL_MAP": n.inputs["Strength"].default_value = 0.15
            if n.type == "TEX_IMAGE" and n.image and "normal" not in n.image.name.lower() and n.image.size[0] > 0:
                img = n.image; W, H = img.size
                T = np.array(img.pixels[:], dtype=np.float32).reshape(H, W, 4)
                c = T[..., :3]
                # lips: pixels much redder than the skin around them (MakeHuman textures paint the lips pink)
                red = c[..., 0] - c[..., 1]
                body = c.reshape(-1, 3).sum(1) > 0.15
                lipmask = red > (np.median(red.reshape(-1)[body]) + 0.12)
                from scipy.ndimage import binary_opening, gaussian_filter as _g
                lipmask = _g(binary_opening(lipmask, iterations=2).astype(np.float32), 2.0)
                sig = max(1.5, W / 700.0)
                c = median_filter(c, size=(5, 5, 1))
                c = gaussian_filter(c, sigma=(sig, sig, 0))
                if rgb is not None:
                    med = np.median(c.reshape(-1, 3)[c.reshape(-1, 3).sum(1) > 0.15], 0)
                    tgt = np.array(rgb) * float(S_LUM)                 # photo skin minus its highlight
                    c = c * (tgt / np.maximum(med, 1e-3))
                if lips is not None and LIP_RECOLOUR:
                    lum = c.mean(2, keepdims=True) / max(1e-3, float(np.mean(lips)))
                    lipc = np.clip(np.array(lips) * np.clip(lum, 0.6, 1.3) * 0.95, 0, 1)
                    c = c * (1 - lipmask[..., None]) + lipc * lipmask[..., None]
                # gentle posterize toward flat painted areas
                lv = 24.0
                c = np.round(c * lv) / lv * 0.35 + c * 0.65
                T[..., :3] = np.clip(c, 0, 1)
                new = bpy.data.images.new(img.name + "_painted", W, H, alpha=True)
                new.pixels = T.ravel(); new.pack(); n.image = new
        for n in m.node_tree.nodes:
            if n.type == "BSDF_PRINCIPLED":
                n.inputs["Roughness"].default_value = 0.65
                if "Subsurface Weight" in n.inputs: n.inputs["Subsurface Weight"].default_value = 0.05

def apply(basemesh, ST, S):
    arm = basemesh.parent if basemesh.parent and basemesh.parent.type == "ARMATURE" else next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    if arm:
        _scale_part(arm, ["head"], "head", float(ST.get("head_scale", 1.0)))
        for side in ("l", "r"):
            hb = ["hand_" + side] + [f"{f}_{i:02d}_{side}" for f in ("thumb", "index", "middle", "ring", "pinky") for i in (1, 2, 3)]
            _scale_part(arm, hb, "hand_" + side, float(ST.get("hand_scale", 1.0)))
    if ST.get("painted"):
        rgb = ST.get("skin_rgb")
        if rgb is None and S.get("fit"):
            import json
            lm = json.load(open(S["fit"]["landmarks"]))
            rgb = lm["colors"].get("skin_wb", lm["colors"]["skin"]); lips = lm["colors"].get("lips_wb")
        else: lips = None
        _painted_skin(basemesh, rgb, lips)
