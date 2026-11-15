"""The phone's map (scripts/phone.gd Maps app): a styled map of the whole island with the real road network,
water, parks, the made-up countryside and town/river labels.
usage: make_phone_map.py <out png> [width px]   (bounds are written next to it as phone_map.json)"""
import json, glob, math, sys
from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import Polygon, LineString, box
from shapely.ops import unary_union, polygonize
d=json.load(open('/home/claude/proj/source_data/island.json'))
S,W,N,E=41.45,-83.92,41.79,-83.20
Wd=int(sys.argv[2]) if len(sys.argv)>2 else 3600; c=math.cos(math.radians(41.63)); Ht=int(Wd*(N-S)/((E-W)*c))
X=lambda lon:(lon-W)/(E-W)*Wd; Y=lambda lat:(N-lat)/(N-S)*Ht
SEA=(124,170,205); LAND=(236,232,220); GREEN=(206,224,190); RIV=(140,182,214)
im=Image.new('RGB',(Wd,Ht),SEA); dr=ImageDraw.Draw(im)
ring=d['ring']; isl=Polygon([(b,a) for a,b in ring])
dr.polygon([(X(b),Y(a)) for a,b in ring],fill=(214,226,196))
rl=d.get('real')
if rl:
    rp=box(rl[1],rl[0],rl[3],rl[2]).intersection(Polygon([(b,a) for a,b in ring]).buffer(0))
    for q in (rp.geoms if hasattr(rp,'geoms') else [rp]): dr.polygon([(X(x),Y(y)) for x,y in q.exterior.coords],fill=LAND)
for h in d.get('holes',[]): dr.polygon([(X(b),Y(a)) for a,b in h],fill=SEA)
for r in d.get('islets',[]): dr.polygon([(X(b),Y(a)) for a,b in r],fill=GREEN)
files=sorted(glob.glob('/home/claude/osm/city_all/*.json'))
roads={'motorway':[],'trunk':[],'primary':[],'secondary':[],'tertiary':[]}
water=[]; parks=[]; coast=[]
for f in files:
    for e in json.load(open(f))['elements']:
        if e['type']!='way': continue
        t=e.get('tags',{}); g=[(p['lon'],p['lat']) for p in e.get('geometry',[]) if p]
        if len(g)<2: continue
        h=t.get('highway','').replace('_link','')
        if h in roads: roads[h].append(g)
        elif t.get('natural')=='water' or t.get('waterway')=='riverbank':
            if len(g)>=4: water.append(g)
        elif t.get('leisure') in ('park','golf_course','nature_reserve') or t.get('landuse') in ('forest','cemetery') or t.get('natural')=='wood':
            if len(g)>=4: parks.append(g)
        elif t.get('natural')=='coastline': coast.append(g)
def clipdraw(poly_pts, fill):
    try:
        p=Polygon(poly_pts).buffer(0).intersection(isl)
    except Exception: return
    for q in (p.geoms if hasattr(p,'geoms') else [p]):
        if q.is_empty or q.geom_type!='Polygon': continue
        dr.polygon([(X(x),Y(y)) for x,y in q.exterior.coords],fill=fill)
for g in parks: clipdraw(g, GREEN)
for g in water: clipdraw(g, RIV)
isl=Polygon([(b,a) for a,b in ring]).buffer(0)
if rl: isl=box(rl[1],rl[0],rl[3],rl[2]).intersection(isl)
# Lake Erie shoreline (member ways of the Lake Erie relation): faces holding a lake seed are water
import os
from shapely.geometry import Point
ep='/home/claude/osm/extra/erie.json'
if os.path.exists(ep):
    lines=[LineString([(q['lon'],q['lat']) for q in e['geometry']]) for e in json.load(open(ep))['elements'] if len(e.get('geometry',[]))>1]
    bb=box(rl[1],rl[0],rl[3],rl[2]) if rl else box(W,S,E,41.7325); cl=unary_union(lines).intersection(bb)
    seeds=[Point(-83.40,41.70),Point(-83.33,41.735),Point(-83.45,41.72)]
    for pg in polygonize(unary_union([bb.exterior,cl])):
        if any(pg.contains(sd) for sd in seeds): clipdraw(list(pg.exterior.coords), SEA)
# water relations (Maumee River etc.)
for f in files:
    for e in json.load(open(f))['elements']:
        t=e.get('tags',{})
        if e['type']=='relation' and (t.get('natural')=='water' or t.get('waterway')=='riverbank'):
            ls=[LineString([(q['lon'],q['lat']) for q in m['geometry']]) for m in e.get('members',[]) if m.get('role')=='outer' and len(m.get('geometry',[]))>1]
            for pg in polygonize(unary_union(ls)): clipdraw(list(pg.exterior.coords), RIV)
# real Lake Erie inside the outline: polygonize coastline against the island box
if coast:
    cl=unary_union([LineString(g) for g in coast]); bb=box(W,S,E,41.7325)
    samples=[]
    for ln in (cl.geoms if hasattr(cl,'geoms') else [cl]):
        cs=list(ln.coords)
        for (x0,y0),(x1,y1) in zip(cs,cs[1:]):
            L=math.hypot(x1-x0,y1-y0)
            if L>0: samples.append(((x0+x1)/2+(y1-y0)/L*2e-5,(y0+y1)/2-(x1-x0)/L*2e-5))
    from shapely.geometry import Point
    for p in polygonize(unary_union([bb.exterior,cl.intersection(bb)])):
        if sum(p.contains(Point(*s)) for s in samples[::max(1,len(samples)//300)])>0: clipdraw(list(p.exterior.coords), SEA)
style={'motorway':((214,90,70),5),'trunk':((228,130,80),4),'primary':((240,190,90),3),'secondary':((250,235,170),2),'tertiary':((255,255,255),1)}
for h in ['tertiary','secondary','primary','trunk','motorway']:
    col,w=style[h]
    for g in roads[h]:
        try: ln=LineString(g).intersection(isl)
        except Exception: continue
        for q in (ln.geoms if hasattr(ln,'geoms') else [ln]):
            if q.geom_type=='LineString' and len(q.coords)>1: dr.line([(X(x),Y(y)) for x,y in q.coords],fill=col,width=w)
fic=json.load(open('/home/claude/osm/fiction/countryside.json'))['elements']
RC={'motorway':((217,90,70),6),'trunk':((217,90,70),5),'primary':((235,130,70),4),'secondary':((245,185,80),3),'tertiary':((248,215,120),2),'unclassified':((255,255,255),1),'residential':((255,255,255),1)}
for e in fic:
    if e['type']!='way': continue
    t=e['tags']; g=[(X(q['lon']),Y(q['lat'])) for q in e['geometry']]
    if 'natural' in t: dr.polygon(g,fill=(170,200,150) if t['natural']=='wood' else (180,205,195))
for e in fic:
    if e['type']!='way': continue
    t=e['tags']; g=[(X(q['lon']),Y(q['lat'])) for q in e['geometry']]
    if 'building' in t: dr.polygon(g,fill=(150,110,100))
    elif t.get('highway') in RC: col,w=RC[t['highway']]; dr.line(g,fill=col,width=w)
fv=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",16)
for e in fic:
    if e['type']=='node' and e['tags'].get('place'):
        n=e['tags']['name'].upper(); tw=dr.textlength(n,font=fv); dr.text((X(e['lon'])-tw/2,Y(e['lat'])-8),n,fill=(60,60,70),font=fv,stroke_width=3,stroke_fill=(250,250,245))
dr.line([(X(b),Y(a)) for a,b in ring+[ring[0]]],fill=(110,130,140),width=2)
if rl: dr.rectangle([X(rl[1]),Y(rl[2]),X(rl[3]),Y(rl[0])],outline=(170,120,120),width=1)
f=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",20)
towns={"GLASS CITY":(41.6528,-83.5379),"PINEWICK":(41.7187,-83.7130),"WINDMILL PARK":(41.6217,-83.7116),"VELVET RIDGE":(41.6642,-83.6430),"STONEBRIDGE":(41.5628,-83.6538),
"KINGSFERRY":(41.5570,-83.6272),"FURNACE HILL":(41.6098,-83.5644),"GATESBORO":(41.6056,-83.4838),"EASTSHORE":(41.6437,-83.4869),"SWITCHYARD":(41.5878,-83.4930),
"GULL SHORES":(41.7120,-83.4880),"HARVEST MILL":(41.5662,-83.4277)}
for n,(la,lo) in towns.items():
    tw=dr.textlength(n,font=f); dr.text((X(lo)-tw/2,Y(la)-10),n,fill=(60,60,70),font=f,stroke_width=3,stroke_fill=(250,250,245))
dr.text((X(-83.43),Y(41.735)),"LAKE GLASSMERE",fill=(70,110,150),font=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",34))
fi=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",17)
for n,(la,lo) in {"Stone Ridge River":(41.590,-83.585),"Northfork River":(41.703,-83.590),"Mallard Creek":(41.628,-83.640),"Stone Ridge Bay":(41.712,-83.400)}.items():
    tw=dr.textlength(n,font=fi); dr.text((X(lo)-tw/2,Y(la)-9),n,fill=(40,90,140),font=fi,stroke_width=3,stroke_fill=(235,242,248))
im.save(sys.argv[1])
LAT0, LON0 = 41.6528, -83.5379; R = 6378137.0; C0 = math.cos(math.radians(LAT0))
wx = lambda lon: (lon - LON0) * math.pi / 180 * R * C0
wz = lambda lat: -(lat - LAT0) * math.pi / 180 * R
json.dump({"_doc": "world-metre bounds of textures/phone_map.png (x left..right, z top..bottom)", "x0": wx(W), "x1": wx(E), "z0": wz(N), "z1": wz(S), "w": Wd, "h": Ht},
          open(sys.argv[1].rsplit('/', 2)[0] + '/source_data/phone_map.json' if '/textures/' in sys.argv[1] else sys.argv[1] + '.json', 'w'))
print(im.size, len(files), "tiles")
