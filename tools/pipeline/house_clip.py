"""Zero-shot architectural attributes from the county reference photos with CLIP (ONNX, CPU).
Only the attribute labels go into the game; photos stay local.

usage: house_clip.py PHOTO_DIR CLIP_DIR out.json
out: {assr: {"style": name, "porch": full|small|enclosed|none, "dormer": 0/1, "shutters": 0/1, "piers": 0/1, "conf": {...}}}
"""
import sys, os, json, glob
import numpy as np, cv2, onnxruntime as ort
from tokenizers import Tokenizer

PH, CD, OUT = sys.argv[1:4]
vis = ort.InferenceSession(os.path.join(CD, "vision_model_quantized.onnx"), providers=["CPUExecutionProvider"])
txt = ort.InferenceSession(os.path.join(CD, "text_model_quantized.onnx"), providers=["CPUExecutionProvider"])
tok = Tokenizer.from_file(os.path.join(CD, "tokenizer.json"))
MEAN = np.array([0.48145466, 0.4578275, 0.40821073], np.float32); STD = np.array([0.26862954, 0.26130258, 0.27577711], np.float32)

GROUPS = {
    "style": {"foursquare": "a photo of an American Foursquare house, a boxy two-story house with a hipped roof",
              "bungalow": "a photo of a Craftsman bungalow, a one-and-a-half story house with a low sloping roof",
              "dutch": "a photo of a Dutch Colonial house with a gambrel roof",
              "tudor": "a photo of a Tudor revival house with a steep roof and half-timbering",
              "victorian": "a photo of a Victorian Queen Anne house with ornate trim",
              "colonial": "a photo of a symmetrical Colonial revival house with a side-gabled roof",
              "cape": "a photo of a small Cape Cod house with a steep side-gabled roof",
              "ranch": "a photo of a one-story ranch house",
              "frontgable": "a photo of a narrow two-story house with its gable facing the street"},
    "porch": {"full": "a house with a porch across the whole front",
              "small": "a house with a small covered stoop over the front door",
              "enclosed": "a house with an enclosed front porch with windows",
              "none": "a house with no front porch"},
    "dormer": {1: "a house with a dormer window sticking out of the roof", 0: "a house with a plain roof and no dormers"},
    "shutters": {1: "a house with shutters beside the windows", 0: "a house with windows without shutters"},
    "piers": {1: "a porch with tapered columns on brick piers", 0: "a porch with plain wooden posts"},
}


def enc_text(s):
    ids = tok.encode(s).ids[:77]
    return np.array([ids], np.int64)


TXT = {}
for g, opts in GROUPS.items():
    E = []
    for k, s in opts.items():
        e = txt.run(None, {"input_ids": enc_text(s)})[0][0]; E.append(e / np.linalg.norm(e))
    TXT[g] = (list(opts.keys()), np.stack(E))


def prep(img):
    h, w = img.shape[:2]
    if (img[int(h * 0.9):].reshape(-1, 3).min(1) > 225).mean() > 0.5: img = img[: int(h * 0.9)]; h = img.shape[0]
    s = 224 / min(h, w)
    img = cv2.resize(img, (round(w * s), round(h * s)), interpolation=cv2.INTER_CUBIC)
    h, w = img.shape[:2]; y0, x0 = (h - 224) // 2, (w - 224) // 2
    x = img[y0:y0 + 224, x0:x0 + 224, ::-1].astype(np.float32) / 255
    return ((x - MEAN) / STD).transpose(2, 0, 1)


out = json.load(open(OUT)) if os.path.exists(OUT) else {}
EMBF = OUT.rsplit(".", 1)[0] + "_emb.npz"          # image embeddings, for the probe trained on hand-labelled houses
EMB = dict(np.load(EMBF)) if os.path.exists(EMBF) else {}
out = {k: v for k, v in out.items() if k in EMB}
fs = [f for f in sorted(glob.glob(os.path.join(PH, "*.jpg"))) if os.path.basename(f)[:-4] not in out]
B = 16
for i in range(0, len(fs), B):
    batch, names = [], []
    for f in fs[i:i + B]:
        im = cv2.imread(f)
        if im is None: continue
        batch.append(prep(im)); names.append(os.path.basename(f)[:-4])
    if not batch: continue
    ie = vis.run(None, {"pixel_values": np.stack(batch)})[0]
    ie /= np.linalg.norm(ie, axis=1, keepdims=True)
    for n, v in zip(names, ie):
        # raw cosine similarities; labels are decided later against the whole set (zero-shot CLIP is biased toward
        # some prompts, so each prompt's dataset mean is subtracted first - see clip_labels())
        out[n] = {g: [round(float(x), 4) for x in (E @ v)] for g, (ks, E) in TXT.items()}
        EMB[n] = v.astype(np.float16)
    if (i // B) % 20 == 0:
        json.dump(out, open(OUT, "w")); np.savez(EMBF, **EMB); print(i, len(fs), flush=True)
json.dump(out, open(OUT, "w")); np.savez(EMBF, **EMB)
print("clip attrs", len(out))


def clip_labels(raw, prior=None):
    """{assr: {group: label}} from raw sims: subtract each prompt's mean over all houses, then argmax."""
    prior = prior or {}
    keys = {g: list(o.keys()) for g, o in GROUPS.items()}
    res = {a: {} for a in raw}
    for g, ks in keys.items():
        M = np.array([raw[a][g] for a in raw]); M = M - M.mean(0)
        if len(ks) == 2 and g in prior:                 # binary: flag the top share given by the prior
            d = M[:, list(ks).index(1)] - M[:, list(ks).index(0)]
            thr = np.quantile(d, 1 - prior[g])
            for a, x in zip(raw, d): res[a][g] = int(x >= thr)
        else:
            for a, row in zip(raw, M): res[a][g] = ks[int(np.argmax(row))]
    return res
