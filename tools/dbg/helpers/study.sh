#!/bin/sh
# usage: study.sh KEY ASSR [bands]
K=$1; A=$2; B=${3:-2.5}
python3 proj/tools/pipeline/massing_rects.py /home/claude $K $B 2>&1 | sed 's/np.float64(\([^)]*\))/\1/g' > /tmp/rects_$K.txt
python3 - "$K" "$A" <<'PY'
import cv2, numpy as np, glob, sys
K, A = sys.argv[1], sys.argv[2]
fs = sorted(glob.glob(f'dl/refs_et/{A}_*.jpg'))[:4]
ims = [cv2.resize(cv2.imread(f), (640, 480)) for f in fs]
r = cv2.imread(f'/tmp/rects_{K}.png'); s = 480 / r.shape[0]; r = cv2.resize(r, (int(r.shape[1] * s), 480), interpolation=cv2.INTER_NEAREST)
ims.append(r)
rows = [np.hstack(ims[i:i + 2]) if len(ims[i:i + 2]) == 2 else ims[i] for i in range(0, len(ims), 2)]
W = max(x.shape[1] for x in rows)
rows = [np.hstack([x, np.zeros((x.shape[0], W - x.shape[1], 3), np.uint8)]) for x in rows]
cv2.imwrite(f'/tmp/study_{K}.jpg', np.vstack(rows), [1, 80])
PY
cat /tmp/rects_$K.txt
