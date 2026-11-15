import pickle,json,glob,math,sys
from shapely import wkt
from shapely.geometry import Point, LineString
LAT0,LON0=41.6528,-83.5379;R=6378137;C=math.cos(math.radians(LAT0))
P=lambda la,lo:((lo-LON0)*math.pi/180*R*C,(la-LAT0)*math.pi/180*R)
d=pickle.load(open('lidar/downtown_exact.pkl','rb'))
streets=[]
for f in glob.glob('osm/city/*.json'):
    for e in json.load(open(f))['elements']:
        t=e.get('tags',{})
        if e['type']=='way' and t.get('highway') and t.get('name') and e.get('geometry'):
            ls=LineString([P(p['lat'],p['lon']) for p in e['geometry']])
            if ls.distance(Point(0,-150))<1800: streets.append((t['name'],ls))
rows=json.load(open('/tmp/dt_rows.json'))
out={}
for h,k,nm,meta in rows:
    g=wkt.loads(d[k]['tiers'][0][2]); c=g.centroid
    near=sorted({(round(ls.distance(g)),n) for n,ls in streets})
    seen=[];
    for dist,n in near:
        if n not in seen and dist<40: seen.append(n)
    lat=LAT0+c.y/R*180/math.pi; lon=LON0+c.x/(R*C)*180/math.pi
    out[k]={"h":round(h,1),"name":nm,"meta":meta,"lat":round(lat,5),"lon":round(lon,5),"streets":seen[:3],"area":round(g.area)}
json.dump(out,open('osm/dt_buildings.json','w'),indent=0)
for k,v in list(out.items())[:int(sys.argv[1]) if len(sys.argv)>1 else 40]: print(k,v['h'],v['name'],v['streets'],v['lat'],v['lon'],v['area'])
