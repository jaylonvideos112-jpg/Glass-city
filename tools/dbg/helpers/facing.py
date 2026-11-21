import json, glob, math, sys, pickle, os
from shapely.geometry import LineString, Point
LAT0, LON0 = 41.6528, -83.5379; R = 6378137.0; C = math.cos(math.radians(LAT0))
P=lambda la,lo: ((lo-LON0)*math.pi/180*R*C,(la-LAT0)*math.pi/180*R)
o=pickle.load(open('lidar/osm_blds.pkl','rb'))
keys=sys.argv[1:]
pts={k:o[k][1].centroid for k in keys}
best={k:(1e9,None,None) for k in keys}
for f in glob.glob('osm/city_all/*.json'):
    for e in json.load(open(f)).get('elements',[]):
        t=e.get('tags') or {}
        if os.environ.get("STREET") and t.get("name","").upper().find(os.environ["STREET"])<0: continue
        if t.get("highway") not in ('residential','tertiary','secondary','primary','unclassified','trunk'): continue
        g=e.get('geometry')
        if not g or len(g)<2: continue
        ln=LineString([P(q['lat'],q['lon']) for q in g])
        for k,p in pts.items():
            d=ln.distance(p)
            if d<best[k][0]: best[k]=(d,t.get('name'),ln)
for k,(d,n,ln) in best.items():
    q=ln.interpolate(ln.project(pts[k])); v=(q.x-pts[k].x,q.y-pts[k].y); L=math.hypot(*v)
    print(k, n, round(d,1), 'facing', round(v[0]/L,3), round(v[1]/L,3))
