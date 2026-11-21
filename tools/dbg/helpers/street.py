import json,glob,math,sys
LAT0, LON0 = 41.6528, -83.5379; R=6378137.0; C=math.cos(math.radians(LAT0))
P=lambda la,lo: ((lo-LON0)*math.pi/180*R*C,(la-LAT0)*math.pi/180*R)
q=sys.argv[1].upper()
for f in glob.glob('osm/city_all/*.json'):
  for e in json.load(open(f)).get('elements',[]):
    n=(e.get('tags') or {}).get('name','')
    if q in n.upper() and e.get('geometry'):
      g=e['geometry']; a=P(g[0]['lat'],g[0]['lon']); b=P(g[-1]['lat'],g[-1]['lon'])
      print(n,[round(v) for v in a],[round(v) for v in b])
