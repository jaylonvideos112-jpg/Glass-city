"""Photo -> face landmarks + colours for the character creator (tools/blender/charcreator).

MediaPipe Face Landmarker (478 points: 468 face mesh + 10 iris) on the largest face in the photo. Writes JSON with
pixel-space landmarks (x right, y down, z depth in pixels, smaller = nearer the camera), the image size, the head
pose matrix, and colours sampled from the photo: skin (cheeks + forehead, median), iris, hair (above the brow
line), brows and lips. The model file is Google's face_landmarker.task (Apache-2.0).

usage: python3 tools/pipeline/face_landmarks.py PHOTO OUT.json [MODEL.task]"""
import sys, json, os
import numpy as np
from PIL import Image, ImageOps
import mediapipe as mp
from mediapipe.tasks import python as mpt
from mediapipe.tasks.python import vision

PHOTO, OUT = sys.argv[1], sys.argv[2]
MODEL = sys.argv[3] if len(sys.argv) > 3 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../dl/facefit/face_landmarker.task")

img = ImageOps.exif_transpose(Image.open(PHOTO)).convert("RGB")
W, H = img.size
arr = np.asarray(img)
det = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
    base_options=mpt.BaseOptions(model_asset_path=MODEL), num_faces=4,
    output_facial_transformation_matrixes=True, output_face_blendshapes=True))
res = det.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=arr))
if not res.face_landmarks:
    print("no face found"); sys.exit(2)
# largest face
def span(lm): xs = [p.x for p in lm]; return max(xs) - min(xs)
fi = max(range(len(res.face_landmarks)), key=lambda i: span(res.face_landmarks[i]))
lm = res.face_landmarks[fi]
P = np.array([[p.x * W, p.y * H, p.z * W] for p in lm], dtype=np.float64)

def sample(idx, r=None):
    """median colour in small discs around landmark indices"""
    pts = P[idx, :2]
    r = r or max(2, int(0.012 * (P[:, 0].max() - P[:, 0].min())))
    vals = []
    for x, y in pts:
        x0, x1 = int(max(0, x - r)), int(min(W, x + r + 1)); y0, y1 = int(max(0, y - r)), int(min(H, y + r + 1))
        if x1 > x0 and y1 > y0: vals.append(arr[y0:y1, x0:x1].reshape(-1, 3))
    v = np.concatenate(vals) if vals else np.zeros((1, 3))
    return [round(float(c) / 255.0, 4) for c in np.median(v, axis=0)]

face_w = P[:468, 0].max() - P[:468, 0].min()
# hair: a band above the top of the forehead (landmark 10), between the temples
top = P[10]; up = (P[10, :2] - P[152, :2]); up = up / (np.linalg.norm(up) + 1e-9)
hair_pts = []
for f in (0.10, 0.16, 0.22):
    for s in (-0.25, 0.0, 0.25):
        side = np.array([-up[1], up[0]])
        q = top[:2] + up * f * face_w * 1.0 + side * s * face_w
        if 0 <= q[0] < W and 0 <= q[1] < H: hair_pts.append(arr[int(q[1]), int(q[0])])
hair = [round(float(c) / 255.0, 4) for c in np.median(np.array(hair_pts), axis=0)] if hair_pts else None

# white balance from the whites of the eyes (between iris and the eye corners): skin colour without the photo's light tint
scl = []
for iris, corners in ((468, (33, 133)), (473, (362, 263))):
    for c in corners:
        q = P[iris, :2] * 0.5 + P[c, :2] * 0.5
        x, y = int(q[0]), int(q[1])
        if 0 <= x < W and 0 <= y < H: scl.append(arr[max(0, y - 1):y + 2, max(0, x - 1):x + 2].reshape(-1, 3))
sclera = np.median(np.concatenate(scl), 0) / 255.0 if scl else np.ones(3)
wb = sclera.mean() / np.maximum(sclera, 0.05)
wb = np.clip(wb / wb.mean(), 0.7, 1.4)

out = {
    "photo": os.path.abspath(PHOTO), "size": [W, H], "landmarks": P.round(3).tolist(),
    "pose": np.array(res.facial_transformation_matrixes[fi]).round(5).tolist() if res.facial_transformation_matrixes else None,
    "blendshapes": {b.category_name: round(b.score, 4) for b in res.face_blendshapes[fi]} if res.face_blendshapes else {},
    "colors": {
        "skin": sample([50, 280, 101, 330, 151, 9, 108, 337]),      # cheeks + forehead
        "iris": sample([468, 473], r=max(1, int(0.008 * face_w))),
        "brow": sample([105, 334, 66, 296], r=max(1, int(0.006 * face_w))),
        "lips": sample([13, 14, 0, 17], r=max(1, int(0.006 * face_w))),
        "hair": hair},
    "face_width_px": round(float(face_w), 1), "white_balance": wb.round(4).tolist()}
out["colors"]["skin_wb"] = [round(float(min(1, c * g)), 4) for c, g in zip(out["colors"]["skin"], wb)]
out["colors"]["lips_wb"] = [round(float(min(1, c * g)), 4) for c, g in zip(out["colors"]["lips"], wb)]
json.dump(out, open(OUT, "w"))
print("face %d px wide; skin %s iris %s hair %s; smile %.2f" % (face_w, out["colors"]["skin"], out["colors"]["iris"], hair,
      out["blendshapes"].get("mouthSmileLeft", 0)))
