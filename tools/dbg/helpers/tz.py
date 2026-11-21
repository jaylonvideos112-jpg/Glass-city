import numpy as np, math, sys, os
def TZ(x,y):
    gx=x/4-0.5; gy=y/4-0.5; i=math.floor(gx); j=math.floor(gy)
    t=np.load(f'lidar/dem/{i//125}_{j//125}.npz')['h'].astype(np.float32)/100+150-176
    return float(t[124-j%125, i%125])
for a in sys.argv[1:]:
    x,y=map(float,a.split(',')); print(a, round(TZ(x,y),2))
