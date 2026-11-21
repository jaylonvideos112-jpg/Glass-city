#!/bin/sh
# usage: grp.sh out.jpg key:assr ...
OUT=$1; shift
for kv in "$@"; do /tmp/study.sh ${kv%%:*} ${kv##*:} 2.5,9 > /tmp/r_${kv%%:*}.txt; done
python3 - "$OUT" "$@" <<'PY'
import cv2, numpy as np, sys
out=sys.argv[1]; ks=[a.split(':')[0] for a in sys.argv[2:]]
ims=[cv2.resize(cv2.imread(f'/tmp/study_{k}.jpg'),(640,720)) for k in ks]
while len(ims)%2: ims.append(np.zeros_like(ims[0]))
cv2.imwrite(out,np.vstack([np.hstack(ims[i:i+2]) for i in range(0,len(ims),2)]),[1,76])
PY
for kv in "$@"; do echo "== ${kv%%:*}"; cat /tmp/r_${kv%%:*}.txt; done
