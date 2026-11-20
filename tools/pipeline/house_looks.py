"""Extract per-house appearance from county reference photos (photos stay local; only colours/flags go in the game).

usage: house_looks.py PHOTO_DIR SEG_MODEL.onnx out.json [debug_dir]
out: {assr: {"wall":[r,g,b], "trim":[r,g,b], "roof":[r,g,b], "porch":0..1, "q":0..1}}
"""
import sys, os, json, glob
import numpy as np, cv2, onnxruntime as ort

PH, MODEL, OUT = sys.argv[1:4]
DBG = sys.argv[4] if len(sys.argv) > 4 else None
sess = ort.InferenceSession(MODEL, providers=["CPUExecutionProvider"])
MEAN = np.array([0.485, 0.456, 0.406], np.float32); STD = np.array([0.229, 0.224, 0.225], np.float32)
HOUSE = (0, 1, 25, 79)            # wall, building, house, hovel
OPEN = (8, 14, 58, 63, 18, 86)     # windows, doors, screen doors, blinds, curtains, awnings
PORCH = (38, 42, 53, 59, 95)       # railing, column, stairs, stairway, bannister
SKY = 2


def seg(img):
    x = cv2.resize(img, (512, 512), interpolation=cv2.INTER_AREA)[:, :, ::-1].astype(np.float32) / 255
    x = ((x - MEAN) / STD).transpose(2, 0, 1)[None]
    lg = sess.run(None, {"pixel_values": x})[0][0]
    lab = lg.argmax(0).astype(np.uint8)
    return cv2.resize(lab, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST)


def kmeans(px, k):
    px = np.float32(px)
    k = min(k, len(px))
    _, lab, cen = cv2.kmeans(px, k, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 0.5), 3, cv2.KMEANS_PP_CENTERS)
    cnt = np.bincount(lab.ravel(), minlength=k)
    return cen, cnt, lab.ravel()


def lin(c):  # sRGB 0..255 -> linear-light-ish 'albedo' used to undo exposure later
    return c


def analyze(path):
    img = cv2.imread(path)
    if img is None: return None
    h, w = img.shape[:2]
    # county stamps a white caption strip at the bottom of newer photos
    bot = img[int(h * 0.9):, :, :].reshape(-1, 3)
    if (bot.min(1) > 225).mean() > 0.5: img = img[: int(h * 0.9)]; h = img.shape[0]
    lab = seg(img)
    house = np.isin(lab, HOUSE)
    # the parcel's house is the one in the middle of the frame: keep the connected house blob covering the centre
    n, cc, st, _ = cv2.connectedComponentsWithStats(house.astype(np.uint8), 8)
    if n <= 1: return None
    cx0, cx1 = int(w * 0.3), int(w * 0.7)
    score = [(np.count_nonzero(cc[:, cx0:cx1] == i), i) for i in range(1, n)]
    best = max(score)[1]
    m = cc == best
    area = m.mean()
    if area < 0.06: return None
    ys, xs = np.nonzero(m)
    y0, y1 = ys.min(), ys.max()
    # shrink away from edges (anti-aliased boundaries, sky bleed) and drop windows/doors explicitly
    mk = cv2.erode(m.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    mk &= ~np.isin(lab, OPEN)
    # white-patch exposure + white balance from the house's own brightest parts (trim, porch posts, window frames):
    # county photos are shot against a bright sky, so facades come out underexposed and tinted
    ref = np.percentile(img[m].reshape(-1, 3).astype(np.float32), 97, axis=0)
    gain = float(np.clip(232.0 / max(ref.max(), 1), 1.0, 1.8))        # exposure only: white balance from trim proved unreliable
    img = np.clip(img.astype(np.float32) * gain, 0, 255).astype(np.uint8)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    # remove deep shadow and blown highlights - they're not the paint colour
    v = hsv[:, :, 2]
    good = mk & (v > 35) & (v < 250)
    # siding lives in the middle of the facade: skip the roof band and the porch/foundation band, and the frame edges
    H = y1 - y0
    band = np.zeros_like(good)
    band[y0 + int(H * 0.22): y0 + int(H * 0.72), int(w * 0.3): int(w * 0.7)] = True
    sel = good & band
    if np.count_nonzero(sel) < 400: sel = good
    if np.count_nonzero(sel) < 400: return None
    labimg = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    cen, cnt, _ = kmeans(labimg[sel], 5)
    cen = cv2.cvtColor(np.uint8(np.clip(cen, 0, 255))[None], cv2.COLOR_LAB2BGR)[0].astype(np.float32)
    # the paint is the big *coloured, lit* cluster: grey shade, glass and porch-roof clusters lose to it unless they dominate
    labc = cv2.cvtColor(np.uint8(np.clip(cen, 0, 255))[None], cv2.COLOR_BGR2LAB)[0].astype(np.float32)
    chroma = np.hypot(labc[:, 1] - 128, labc[:, 2] - 128)
    score = cnt * (1 + chroma / 200.0)
    wall = cen[int(np.argmax(score))]
    px = img[good]
    tc, tn, _ = kmeans(px, 4)
    cnt, cen = tn, tc
    order = np.argsort(-cnt)
    # trim: a clearly lighter cluster with a real share (white/cream trim, porch posts)
    trim = None
    for i in order[1:]:
        hv = cv2.cvtColor(np.uint8([[cen[i]]]), cv2.COLOR_BGR2HSV)[0, 0]
        if cnt[i] > 0.05 * cnt.sum() and cen[i].mean() > wall.mean() + 28 and hv[1] < 60 and hv[2] > 165:
            trim = cen[i]; break
    # roof: pixels just under the sky along the top of the house blob (per column), clustered; darkest big cluster
    roofpx = []
    top_band = max(4, int((y1 - y0) * 0.14))
    for x in range(xs.min(), xs.max() + 1, 2):
        col = np.nonzero(m[:, x])[0]
        if len(col) < 10: continue
        t = col[0]
        if t > 2 and lab[t - 2, x] != SKY: continue
        roofpx.append(img[t + 2: t + 2 + top_band, x])
    roof = None
    if roofpx:
        rp = np.concatenate(roofpx)
        if len(rp) > 200:
            rc, rn, _ = kmeans(rp, 3)
            ro = np.argsort(-rn)
            cand = [rc[i] for i in ro if rn[i] > 0.2 * rn.sum()]
            roof = min(cand, key=lambda c: c.mean())
            # a roof that reads like the wall is really the gable siding - don't trust it
            if np.abs(roof - wall).mean() < 18: roof = None
    # porch: railings/columns/stairs in the lower half under the house blob
    xr = slice(xs.min(), xs.max() + 1)
    low = lab[(y0 + y1) // 2:, xr]
    porch = float(np.isin(low, PORCH).mean())
    # quality: house share of frame, unoccluded fraction (trees/cars over the house)
    occl = np.isin(lab[y0:y1, xr], (4, 17, 20)).mean()
    q = float(np.clip(area * 3, 0, 1) * (1 - occl))
    res = {"wall": [int(c) for c in wall[::-1]], "porch": round(min(1.0, porch * 12), 2), "q": round(q, 2)}
    if trim is not None: res["trim"] = [int(c) for c in trim[::-1]]
    if roof is not None: res["roof"] = [int(c) for c in roof[::-1]]
    if DBG:
        dbg = img.copy()
        dbg[~m] = (dbg[~m] * 0.35).astype(np.uint8)
        sw = np.zeros((40, w, 3), np.uint8)
        for i, (k, c) in enumerate((("wall", wall), ("trim", trim), ("roof", roof))):
            if c is not None: sw[:, i * w // 3:(i + 1) * w // 3] = c
        cv2.putText(sw, f"porch {res['porch']} q {res['q']}", (6, 28), 0, 0.7, (255, 0, 255), 2)
        cv2.imwrite(os.path.join(DBG, os.path.basename(path)), np.vstack([dbg, sw]))
    return res


if __name__ == "__main__":
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}
    if DBG: os.makedirs(DBG, exist_ok=True)
    fs = sorted(glob.glob(os.path.join(PH, "*.jpg")))
    for i, f in enumerate(fs):
        a = os.path.basename(f)[:-4]
        if a in out: continue
        try: out[a] = analyze(f)
        except Exception as e: print("err", a, e); out[a] = None
        if i % 200 == 0: json.dump(out, open(OUT, "w")); print(i, len(fs), flush=True)
    json.dump(out, open(OUT, "w"))
    print("looks", sum(1 for v in out.values() if v), "of", len(out))
