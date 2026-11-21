"""Toledo city generator v2: Overpass JSON tiles -> streamed Godot chunk files.

usage: build_city.py <osm json file or dir of tiles> <outdir> [S W N E]

* True 1:1 meters around a downtown origin (LAT0/LON0). Plan (x=east, y=north) -> Godot (x, h, -y).
* Processes the map in 1 km regions so the whole city fits in memory; each region's chunks are
  written to disk and freed before the next region.
"""
import re, pickle, zlib, json, math, struct, sys, os, hashlib, random, glob, heapq, time
from collections import defaultdict
import numpy as np
import cv2
import shapely
import shapely.prepared
import shapely.affinity
from shapely.geometry import Polygon, LineString, MultiPolygon, box, Point, GeometryCollection, MultiLineString
from shapely.geometry.polygon import orient
from shapely.ops import unary_union, polygonize, linemerge
from shapely.strtree import STRtree

SRC, OUTDIR = sys.argv[1], sys.argv[2]
LIDAR_PKL = os.environ.get("LIDAR", "")
LAT0, LON0 = 41.6528, -83.5379
R = 6378137.0
CHUNK = 200.0
REGION = 1000.0
COSLAT = math.cos(math.radians(LAT0))
GROUND_COL_Y = 0.09
WATER_Y = -1.6
BED_Y = -5.0
T0 = time.time()

def P(lat, lon):
    return ((lon - LON0) * math.pi / 180 * R * COSLAT, (lat - LAT0) * math.pi / 180 * R)

def _LL(x, y):
    return (LAT0 + y / R * 180 / math.pi, LON0 + x / (R * COSLAT) * 180 / math.pi)

def log(*a):
    print(f"[{time.time() - T0:6.1f}s]", *a, flush=True)

# ---------------------------------------------------------------- Godot Variant encoder
class PV3:
    def __init__(self, a): self.a = a
class PV2:
    def __init__(self, a): self.a = a
class PF32:
    def __init__(self, a): self.a = a
class PCOL:
    def __init__(self, a): self.a = a

def enc(v):
    if isinstance(v, bool): return struct.pack("<II", 1, int(v))
    if isinstance(v, int):
        if -2**31 <= v < 2**31: return struct.pack("<Ii", 2, v)
        return struct.pack("<Iq", 2 | (1 << 16), v)
    if isinstance(v, float): return struct.pack("<Id", 3 | (1 << 16), v)
    if isinstance(v, str):
        b = v.encode("utf8"); pad = (4 - len(b) % 4) % 4
        return struct.pack("<II", 4, len(b)) + b + b"\0" * pad
    if isinstance(v, dict):
        return struct.pack("<II", 27, len(v)) + b"".join(enc(k) + enc(x) for k, x in v.items())
    if isinstance(v, list):
        return struct.pack("<II", 28, len(v)) + b"".join(enc(x) for x in v)
    if isinstance(v, PV3):
        a = np.asarray(v.a, np.float32).reshape(-1, 3)
        return struct.pack("<II", 36, len(a)) + a.tobytes()
    if isinstance(v, PV2):
        a = np.asarray(v.a, np.float32).reshape(-1, 2)
        return struct.pack("<II", 35, len(a)) + a.tobytes()
    if isinstance(v, PF32):
        a = np.asarray(v.a, np.float32).reshape(-1)
        return struct.pack("<II", 32, len(a)) + a.tobytes()
    if isinstance(v, PCOL):
        a = np.asarray(v.a, np.float32).reshape(-1, 4)
        return struct.pack("<II", 37, len(a)) + a.tobytes()
    raise TypeError(type(v))

# ---------------------------------------------------------------- mesh accumulation
class Chunk:
    def __init__(self, cx, cz):
        self.cx, self.cz = cx, cz
        self.ox, self.oy = cx * CHUNK, cz * CHUNK
        self.layers = defaultdict(lambda: ([], [], []))
        self.fac = ([], [], [], [], [], [])     # facade layer: V, N, UV(m), UV2(floor h, bay w), COLOR, CUSTOM0
        self.col = []
        self.streets, self.labels = [], []
        self.props = PropList(self)
        self.bars = []
        self.roads, self.ix = [], []    # traffic network: lane segments and intersection controls

chunks = {}
def ckey(x, y): return (math.floor(x / CHUNK), math.floor(y / CHUNK))
def rkey(x, y): return (math.floor(x / REGION), math.floor(y / REGION))
CUR_REGION = None; SPILL = defaultdict(int)
def chunk_at(x, y):
    k = ckey(x, y)
    if k not in chunks:
        chunks[k] = Chunk(*k)
        if CUR_REGION is not None and rkey(k[0] * CHUNK + 1, k[1] * CHUNK + 1) != CUR_REGION:
            import traceback
            fr = traceback.extract_stack()[-2]; SPILL[(fr.name, fr.lineno)] += 1
    return chunks[k]
# ---------------------------------------------------------------- terrain (tools/pipeline/dem.py: 4 m LiDAR bare earth)
# Game y = metres above DATUM. Everything is draped onto the ground unless ZBASE says otherwise: a building sets ZBASE
# to its lowest ground point so it stays level, bridges and water use absolute heights (ZBASE = 0).
DEM_DIR = os.environ.get("DEM")
DATUM = 176.0                       # 174.4 m water surface -> WATER_Y -1.6
_dem = {}
def _dem_tile(cx, cy):
    t = _dem.get((cx, cy))
    if t is None:
        if len(_dem) > 600: _dem.clear()          # regions are built in order: old tiles are not needed again
        f = os.path.join(DEM_DIR, f"{cx}_{cy}.npz") if DEM_DIR else None
        t = (np.load(f)["h"].astype(np.float32) / 100.0 + 150.0 - DATUM) if f and os.path.exists(f) else False
        _dem[(cx, cy)] = t
    return t
def TZ(x, y):
    """bare-earth height (m above DATUM) at plan (x, y), bilinear on the 4 m grid."""
    if not DEM_DIR: return 0.0
    gx = x / 4.0 - 0.5; gy = y / 4.0 - 0.5
    i0 = math.floor(gx); j0 = math.floor(gy); fx = gx - i0; fy = gy - j0
    v = 0.0
    for di, dj, w in ((0, 0, (1 - fx) * (1 - fy)), (1, 0, fx * (1 - fy)), (0, 1, (1 - fx) * fy), (1, 1, fx * fy)):
        ci, cj = i0 + di, j0 + dj
        t = _dem_tile(ci // 125, cj // 125)
        v += w * (float(t[124 - cj % 125, ci % 125]) if t is not False else 0.0)
    return v
ZBASE = [None]
def G(x, y): return ZBASE[0] if ZBASE[0] is not None else TZ(x, y)
def foot_base(g):
    """level base for a building: its lowest ground point (walls on the downhill side meet the ground)."""
    if not DEM_DIR: return 0.0
    if hasattr(g, "geoms"): g = max(g.geoms, key=lambda q: q.area)
    pts = list(g.exterior.coords)[:-1] if hasattr(g, "exterior") else []
    pts.append((g.centroid.x, g.centroid.y))
    return min(TZ(x, y) for x, y in pts)
def to3(c, x, y, h): return (x - c.ox, h + G(x, y), -(y - c.oy))

class PropList(list):
    """chunk props carry their own height (p[3]); add the ground (or the current building base) on append."""
    def __init__(self, c): super().__init__(); self.ox, self.oy = c.ox, c.oy      # no back-reference: no cycle
    def append(self, p):
        if DEM_DIR and len(p) > 3:
            x, y = p[1] + self.ox, self.oy - p[2]
            if p[0] == "pillar": p = list(p); gz = TZ(x, y); p[3] = max(0.5, p[3] - gz); p[4] = gz     # pillar: [.., height, ground y]
            elif p[0] in ("pool", "wire"): pass         # wire: [.., x0, z0, x1, z1] (heights at runtime)
            else: p = list(p); p[3] = p[3] + G(x, y)
        super().append(p)

def tri(c, mat, a, b, cc, n, uvs, collide=False):
    ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2]); ac = (cc[0] - a[0], cc[1] - a[1], cc[2] - a[2])
    cr = (ab[1] * ac[2] - ab[2] * ac[1], ab[2] * ac[0] - ab[0] * ac[2], ab[0] * ac[1] - ab[1] * ac[0])
    if cr[0] * n[0] + cr[1] * n[1] + cr[2] * n[2] > 0:
        b, cc = cc, b; uvs = (uvs[0], uvs[2], uvs[1])
    V, N, U = c.layers[mat]
    V.extend((a, b, cc)); N.extend((n, n, n)); U.extend(uvs)
    if collide: c.col.extend((a, b, cc))

def wtri(mat, a, b, cc, n, uv=((0, 0), (1, 0), (0, 1)), collide=False):
    """Queue a triangle given in plan coords (x, y, h); emitted when its region is processed."""
    mx, my = (a[0] + b[0] + cc[0]) / 3, (a[1] + b[1] + cc[1]) / 3
    seg_jobs[rkey(mx, my)].append(("wt", mat, a, b, cc, n, uv, collide))

def wquad(mat, p0, p1, p2, p3, n, uv=((0, 0), (1, 0), (1, 1), (0, 1)), collide=False):
    wtri(mat, p0, p1, p2, n, (uv[0], uv[1], uv[2]), collide); wtri(mat, p0, p2, p3, n, (uv[0], uv[2], uv[3]), collide)

def wbox(mat, cx, cy, u, v, hu, hv, z0, z1, collide=True, top=True, hu1=None, hv1=None):
    """Oriented (optionally tapered) box in plan space: centre cx,cy; axes u,v unit 2D; half sizes hu,hv."""
    hu1 = hu if hu1 is None else hu1; hv1 = hv if hv1 is None else hv1
    def corner(su, sv, z, a, b): return (cx + u[0] * su * a + v[0] * sv * b, cy + u[1] * su * a + v[1] * sv * b, z)
    sgn = [(1, 1), (-1, 1), (-1, -1), (1, -1)]
    for k in range(4):
        (a0, b0), (a1, b1) = sgn[k], sgn[(k + 1) % 4]
        p0 = corner(a0, b0, z0, hu, hv); p1 = corner(a1, b1, z0, hu, hv)
        p2 = corner(a1, b1, z1, hu1, hv1); p3 = corner(a0, b0, z1, hu1, hv1)
        mx, my = (a0 + a1) / 2, (b0 + b1) / 2
        nx, ny = u[0] * mx + v[0] * my, u[1] * mx + v[1] * my
        L = math.hypot(nx, ny) or 1
        wquad(mat, p0, p1, p2, p3, (nx / L, 0.0, -ny / L), ((0, 0), (1, 0), (1, (z1 - z0) / 6), (0, (z1 - z0) / 6)), collide)
    if top:
        q = [corner(a, b, z1, hu1, hv1) for a, b in sgn]
        wquad(mat, q[0], q[1], q[2], q[3], (0.0, 1.0, 0.0), collide=collide)

def wbeam(mat, a, b, r, collide=False):
    """Thin square beam between two plan-space 3D points (cables, braces, hangers)."""
    dx, dy, dz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    L = math.sqrt(dx * dx + dy * dy + dz * dz)
    if L < 0.01: return
    d = np.array([dx, dy, dz]) / L
    up = np.array([0, 0, 1.0]) if abs(d[2]) < 0.9 else np.array([1.0, 0, 0])
    s1 = np.cross(d, up); s1 /= np.linalg.norm(s1); s2 = np.cross(d, s1)
    A = np.array(a); B = np.array(b)
    offs = [s1 * r + s2 * r, -s1 * r + s2 * r, -s1 * r - s2 * r, s1 * r - s2 * r]
    for k in range(4):
        o0, o1 = offs[k], offs[(k + 1) % 4]
        nn = (o0 + o1); nn /= np.linalg.norm(nn)
        wquad(mat, tuple(A + o0), tuple(A + o1), tuple(B + o1), tuple(B + o0), (float(nn[0]), float(nn[2]), float(-nn[1])), collide=collide)

def quad(c, mat, p0, p1, p2, p3, n, uv, collide=False):
    tri(c, mat, p0, p1, p2, n, (uv[0], uv[1], uv[2]), collide)
    tri(c, mat, p0, p2, p3, n, (uv[0], uv[2], uv[3]), collide)

def triangulate(poly):
    if poly.is_empty or poly.area < 0.05: return []
    try:
        t = shapely.constrained_delaunay_triangles(poly)
    except Exception:
        poly = poly.buffer(0)
        if poly.is_empty: return []
        try: t = shapely.constrained_delaunay_triangles(poly)
        except Exception: return []
    return [list(g.exterior.coords)[:3] for g in getattr(t, "geoms", [t]) if not g.is_empty]

def polys_of(g):
    if g is None or g.is_empty: return []
    if isinstance(g, Polygon): return [g]
    if isinstance(g, (MultiPolygon, GeometryCollection)): return [p for x in g.geoms for p in polys_of(x)]
    return []

UP = (0.0, 1.0, 0.0)
def _drape_cell(poly):
    """grid size for draping a ground polygon on the terrain: none where it is flat enough."""
    if not DEM_DIR or ZBASE[0] is not None: return 0
    x0, y0, x1, y1 = poly.bounds
    if max(x1 - x0, y1 - y0) < 6: return 0
    zs = [TZ(x, y) for x in (x0, (x0 + x1) / 2, x1) for y in (y0, (y0 + y1) / 2, y1)]
    rng = max(zs) - min(zs)
    if rng < 0.12: return 0
    # how far the terrain bends away from a plane over this polygon (edge midpoints and centre vs corners)
    m = (zs[0] + zs[2] + zs[6] + zs[8]) / 4
    err = max(abs(zs[4] - m), abs(zs[1] - (zs[0] + zs[2]) / 2), abs(zs[7] - (zs[6] + zs[8]) / 2),
              abs(zs[3] - (zs[0] + zs[6]) / 2), abs(zs[5] - (zs[2] + zs[8]) / 2))
    if err < 0.08 and rng < 4: return 0           # a tilted plane: the polygon's own vertices drape it exactly
    # grid fine enough to keep the sag between grid points small (terrain bends are broad in Toledo)
    return 8.0 if err > 1.0 else 16.0 if err > 0.4 else 32.0 if err > 0.15 else 64.0

def _cells(poly, g):
    x0, y0, x1, y1 = poly.bounds
    out = []
    for gx in np.arange(math.floor(x0 / g) * g, x1, g):
        for gy in np.arange(math.floor(y0 / g) * g, y1, g):
            b = box(gx, gy, gx + g, gy + g)
            if not b.intersects(poly): continue
            if poly.contains(b): out.append(b); continue
            out.extend(polys_of(poly.intersection(b)))
    return out

def flat_poly(c, mat, poly, h, uvscale, collide=False, col_h=None):
    g = _drape_cell(poly)
    if g:
        for sub in _cells(poly, g): flat_poly_1(c, mat, sub, h, uvscale, collide, col_h)
        return
    flat_poly_1(c, mat, poly, h, uvscale, collide, col_h)

def flat_poly_1(c, mat, poly, h, uvscale, collide=False, col_h=None):
    for t in triangulate(poly):
        pts = [to3(c, x, y, h) for x, y in t]
        tri(c, mat, pts[0], pts[1], pts[2], UP, [(x / uvscale, -y / uvscale) for x, y in t], False)
        if collide:
            ch = h if col_h is None else col_h
            c.col.extend([to3(c, x, y, ch) for x, y in t])

def add_area(geom, mat, h, uvscale, collide=False, col_h=None):
    if geom is None or geom.is_empty: return
    x0, y0, x1, y1 = geom.bounds
    for i in range(math.floor(x0 / CHUNK), math.floor(x1 / CHUNK) + 1):
        for j in range(math.floor(y0 / CHUNK), math.floor(y1 / CHUNK) + 1):
            part = geom.intersection(box(i * CHUNK, j * CHUNK, (i + 1) * CHUNK, (j + 1) * CHUNK))
            pp = polys_of(part)
            if not pp: continue
            c = chunks.setdefault((i, j), Chunk(i, j))
            for p in pp:
                flat_poly(c, mat, p, h, uvscale, collide, col_h)

# ---------------------------------------------------------------- load OSM
files = sorted(glob.glob(os.path.join(SRC, "*.json"))) if os.path.isdir(SRC) else [SRC]
els_by = {}
bbox = None
for f in files:
    d = json.load(open(f))
    bbox = bbox or d.get("bbox")
    for e in d["elements"]:
        els_by[(e["type"], e["id"])] = e
els = list(els_by.values()); del els_by
# ---- Lucas County footprints (2025 aerial-traced) + AREIS property records (wall, stories, year, garage...)
COUNTY = os.environ.get("COUNTY", "")
ATTACH = {}
if COUNTY and os.path.exists(os.path.join(COUNTY, "county_osm.json")):
    _drop = set(json.load(open(os.path.join(COUNTY, "county_drop.json"))))
    els = [e for e in els if not (e["type"] == "way" and f"w{e['id']}" in _drop)] + json.load(open(os.path.join(COUNTY, "county_osm.json")))["elements"]
    ATTACH = {k: {"c:" + a: str(v) for a, v in d.items()} for k, d in json.load(open(os.path.join(COUNTY, "county_attach.json"))).items()}
    del _drop
# ---- made-up countryside (owner decision 2026-11-15): real data stays inside island.json "real"; outside it only
# the generated land from make_countryside.py (FICTION env, default osm/fiction/countryside.json) is used
_islp0 = os.environ.get("ISLAND", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "source_data", "island.json"))
_REALBOX = json.load(open(_islp0)).get("real") if os.path.exists(_islp0) and os.environ.get("ISLAND", "1") != "0" else None
if _REALBOX:
    _rs, _rw, _rn, _re = _REALBOX
    _RB = box(*P(_rs, _rw), *P(_rn, _re))
    _inr = lambda g: _rs <= g["lat"] <= _rn and _rw <= g["lon"] <= _re
    _kept = []; _cut = 0
    for e in els:
        if e.get("tags", {}).get("fictional"): _kept.append(e); continue
        if e["type"] == "node":
            if _inr(e): _kept.append(e)
            else: _cut += 1
            continue
        if e["type"] == "relation":
            gs = [g for m in e.get("members", []) for g in m.get("geometry", []) or [] if g]
            if not gs or any(_inr(g) for g in gs): _kept.append(e)   # e.g. the Maumee River multipolygon; area clipped below
            else: _cut += 1
            continue
        g = e.get("geometry", []); ns = e.get("nodes", [])
        if not g: continue
        ins = [bool(q) and _inr(q) for q in g]
        if all(ins): _kept.append(e); continue
        if not any(ins): _cut += 1; continue
        t = e.get("tags", {})
        closed = len(g) > 3 and g[0] == g[-1]
        if closed:   # areas: clip to the real box (largest piece)
            try:
                pg = Polygon([P(q["lat"], q["lon"]) for q in g]).buffer(0).intersection(_RB)
                pg = max(polys_of(pg), key=lambda a: a.area) if not pg.is_empty else None
            except Exception: pg = None
            if pg is None or pg.area < 20: _cut += 1; continue
            if "building" in t and pg.area < 0.6 * Polygon([P(q["lat"], q["lon"]) for q in g]).buffer(0).area: _cut += 1; continue
            e = dict(e); cs = list(pg.exterior.coords)
            e["geometry"] = [dict(zip(("lat", "lon"), _LL(x, y))) for x, y in cs]; e["nodes"] = [-(e["id"] * 1000 + i) for i in range(len(cs) - 1)] + [-(e["id"] * 1000)]
            _kept.append(e); continue
        # lines: split into the runs that are inside the box (made-up roads continue from the last inside node)
        run = []; k = 0
        for i, ok in enumerate(ins + [False]):
            if ok: run.append(i); continue
            if len(run) >= 2:
                e2 = dict(e); e2["id"] = e["id"] + k * 10_000_000_000_000; k += 1
                e2["geometry"] = [g[j] for j in run]
                if len(ns) == len(g): e2["nodes"] = [ns[j] for j in run]
                _kept.append(e2)
            run = []
    log("real data clipped to the real box: kept", len(_kept), "dropped", _cut)
    els = _kept; del _kept
    _fic = os.environ.get("FICTION", os.path.join(os.path.dirname(os.path.abspath(SRC.rstrip("/"))), "fiction", "countryside.json"))
    if os.path.exists(_fic) and not any(e.get("tags", {}).get("fictional") for e in els[:0]):
        _fe = json.load(open(_fic))["elements"]
        _have = {(e["type"], e["id"]) for e in els}
        els += [e for e in _fe if (e["type"], e["id"]) not in _have]
        log("made-up countryside elements", len(_fe))
if len(sys.argv) >= 7: bbox = list(map(float, sys.argv[3:7]))
S, W, N, E = bbox
bx0, by0 = P(S, W); bx1, by1 = P(N, E)
BBOX = box(bx0, by0, bx1, by1)
BBOX_P = shapely.prepared.prep(BBOX)
log("elements", len(els), "files", len(files), "bbox m", round(bx1 - bx0), "x", round(by1 - by0))

def way_pts(w): return [P(g["lat"], g["lon"]) for g in w.get("geometry", []) if g]
def way_poly(w):
    pts = way_pts(w)
    if len(pts) < 4: return None
    try:
        p = Polygon(pts)
        if not p.is_valid: p = p.buffer(0)
        return p if not p.is_empty else None
    except Exception: return None
def rel_poly(r):
    outers, inners = [], []
    for m in r.get("members", []):
        if m.get("type") != "way" or "geometry" not in m: continue
        pts = [P(g["lat"], g["lon"]) for g in m["geometry"] if g]
        if len(pts) < 2: continue
        (inners if m.get("role") == "inner" else outers).append(LineString(pts))
    if not outers: return None
    try:
        po = unary_union(list(polygonize(unary_union(outers))))
        if po.is_empty: return None
        if inners: po = po.difference(unary_union(list(polygonize(unary_union(inners)))))
        return po.buffer(0)
    except Exception: return None
def area_geom(e): return way_poly(e) if e["type"] == "way" else rel_poly(e)
def tags(e): return e.get("tags", {})

# ---------------------------------------------------------------- places (neighbourhood names for HUD + styling)
# ---- parody town names (source_data/place_names.json): whole-word swap in labels and POI/building names
import re as _re
_pnp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "source_data", "place_names.json")
TOWN_MAP = {k: v for k, v in json.load(open(_pnp)).items() if not k.startswith("_")} if os.path.exists(_pnp) else {}
WATER_MAP = json.load(open(_pnp)).get("_water", {}) if os.path.exists(_pnp) else {}
if WATER_MAP:   # rivers, bays and the lake: every name except streets (street_names.json handles those)
    _wre = _re.compile(r"\b(" + "|".join(_re.escape(k) for k in sorted(WATER_MAP, key=len, reverse=True)) + r")\b")
    _wn = 0
    for e in els:
        t = e.get("tags")
        if not t or "highway" in t: continue
        for k in ("name", "official_name", "operator", "alt_name"):
            v = t.get(k)
            if v and _wre.search(v): t[k] = _wre.sub(lambda m: WATER_MAP[m.group(1)], v); _wn += 1
    log("water names swapped in", _wn, "tags")
if TOWN_MAP:
    _tre = _re.compile(r"\b(" + "|".join(_re.escape(k) for k in sorted(TOWN_MAP, key=len, reverse=True)) + r")\b")
    _tn = 0
    for e in els:
        t = e.get("tags")
        if not t or "highway" in t or "waterway" in t or t.get("natural") in ("water", "coastline") or t.get("water"): continue
        for k in ("name", "official_name", "operator", "brand"):
            v = t.get(k)
            if v and _tre.search(v):
                t[k] = _tre.sub(lambda m: TOWN_MAP[m.group(1)], v); _tn += 1
    log("town names swapped in", _tn, "tags")
places = []
for e in els:
    if e["type"] == "node" and "place" in tags(e) and tags(e).get("name"):
        x, y = P(e["lat"], e["lon"])
        places.append([tags(e)["name"], x, -y, tags(e)["place"]])
log("places", len(places))
OWE = [(x, -z) for n, x, z, k in places if n.lower() == "old west end"]
def in_owe(x, y): return any(math.hypot(x - a, y - b) < 900 for a, b in OWE)

# ---------------------------------------------------------------- water (incl. Lake Erie / Maumee Bay via coastline)
water = []
for e in els:
    t = tags(e)
    if t.get("natural") == "water" or t.get("waterway") == "riverbank":
        g = area_geom(e)
        if g is not None and _REALBOX and not t.get("fictional"): g = g.intersection(_RB)
        if g is not None and not g.is_empty: water.append(g)
coast = [LineString(way_pts(e)) for e in els if e["type"] == "way" and tags(e).get("natural") == "coastline" and len(way_pts(e)) > 1]
if coast:
    big = BBOX.buffer(500)
    cl = unary_union(coast).intersection(big)
    samples = []
    for ln in (cl.geoms if hasattr(cl, "geoms") else [cl]):
        if not isinstance(ln, LineString): continue
        cs = list(ln.coords)
        for (x0, y0), (x1, y1) in zip(cs, cs[1:]):
            L = math.hypot(x1 - x0, y1 - y0)
            if L < 1: continue
            # OSM coastline: land on the left, water on the right
            samples.append(Point((x0 + x1) / 2 + (y1 - y0) / L * 2, (y0 + y1) / 2 - (x1 - x0) / L * 2))
    parts = list(polygonize(unary_union([big.exterior, cl])))
    lake = [p for p in parts if sum(p.contains(s) for s in samples[:: max(1, len(samples) // 400)]) > 0]
    water.extend(lake)
    log("coastline segments", len(samples), "lake polys", len(lake))
# ---- the island (owner decision 2026-11-15): everything outside source_data/island.json is Lake Erie
_islp = os.environ.get("ISLAND", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "source_data", "island.json"))
ISLAND = None
if os.path.exists(_islp) and os.environ.get("ISLAND", "1") != "0":
    _isd = json.load(open(_islp))
    ISLAND = unary_union([Polygon([P(a, b) for a, b in _isd["ring"]], [[P(a, b) for a, b in h] for h in _isd.get("holes", [])]).buffer(0)]
                         + [Polygon([P(a, b) for a, b in r]).buffer(0) for r in _isd.get("islets", [])])
    sea = BBOX.buffer(400).difference(ISLAND)
    if not sea.is_empty: water.append(sea)
    log("island km2", round(ISLAND.intersection(BBOX).area / 1e6, 1))
# the real Lake Erie shore (member ways of the Lake Erie relation, osm/extra/erie.json): the tiles have no
# coastline ways, so faces of (shore + bbox) that hold a lake seed point become water (Maumee Bay etc.)
_eriep = os.path.join(os.path.dirname(os.path.abspath(SRC.rstrip("/"))), "extra", "erie.json")
if os.path.exists(_eriep) and not _REALBOX:   # with the made-up island the lake is already "outside the island"
    _el = [LineString([P(q["lat"], q["lon"]) for q in e["geometry"]]) for e in json.load(open(_eriep))["elements"] if len(e.get("geometry", [])) > 1]
    _bb = BBOX.buffer(500)
    _cl = unary_union(_el).intersection(_bb)
    _seeds = [Point(*P(41.70, -83.40)), Point(*P(41.735, -83.33)), Point(*P(41.72, -83.45))]
    _lake = [pg for pg in polygonize(unary_union([_bb.exterior, _cl])) if any(pg.contains(sd) for sd in _seeds)]
    if _REALBOX: _lake = [q for pg in _lake for q in polys_of(pg.intersection(_RB.buffer(30)))]   # the real lake only; outside it is the island coast
    water.extend(_lake)
    log("lake erie faces", len(_lake), "km2", round(sum(pg.area for pg in _lake) / 1e6, 1))
WATER = unary_union(water).intersection(BBOX.buffer(400)).buffer(0) if water else Polygon()
if ISLAND is not None:
    BBOX_P = shapely.prepared.prep(BBOX.intersection(ISLAND))   # buildings, roads, props, labels only on the island
    # beach: a sand strip along the made-up coast (not along the real river/lake shores inside the island)
    BEACH_W = 40.0
    BEACH = unary_union([q.exterior.buffer(BEACH_W) for q in polys_of(ISLAND)]).intersection(ISLAND).intersection(BBOX)
    INLAND_P = shapely.prepared.prep(ISLAND.buffer(-(BEACH_W + 4.0)).difference(WATER))
else:
    BEACH = Polygon(); INLAND_P = None
WATER_TREE_SRC = polys_of(WATER)
log("water km2", round(WATER.area / 1e6, 2))

# ---------------------------------------------------------------- roads
WIDTH = {"motorway": 11, "trunk": 10, "primary": 12, "secondary": 11, "tertiary": 9.5,
         "residential": 7.5, "unclassified": 7.5, "service": 4.5, "living_street": 6,
         "motorway_link": 6, "trunk_link": 6, "primary_link": 6, "secondary_link": 6, "tertiary_link": 6, "track": 3.5}
WALK = {"footway": 2.2, "path": 2.0, "pedestrian": 6, "cycleway": 2.2}
SIDEWALK_ON = {"primary", "secondary", "tertiary", "residential", "unclassified", "living_street", "trunk"}
RESID = {"residential", "unclassified", "living_street"}

def road_width(t):
    hw = t["highway"]
    w = WIDTH.get(hw) or WALK.get(hw)
    if w is None: return None
    try:
        if "width" in t: w = max(w * 0.6, min(float(t["width"].split()[0]), 30))
        elif "lanes" in t and hw in WIDTH: w = max(w, int(t["lanes"].split(";")[0]) * 3.4)
    except ValueError: pass
    return w

# ---- traffic network (engine-neutral): every drivable segment with OSM node ids so the game can rebuild the graph
TRAFFIC_CLASS = {"motorway": 0, "trunk": 1, "primary": 2, "secondary": 3, "tertiary": 4, "residential": 5,
                 "unclassified": 5, "living_street": 6}
for _b in list(TRAFFIC_CLASS):
    if _b in ("motorway", "trunk", "primary", "secondary", "tertiary"): TRAFFIC_CLASS[_b + "_link"] = TRAFFIC_CLASS[_b]
DEFAULT_MPH = {0: 65, 1: 55, 2: 35, 3: 35, 4: 30, 5: 25, 6: 15}
node_classes = defaultdict(list)    # node id -> [(class, is_end_of_way)]
node_xy = {}
def _mph(t, cls):
    v = t.get("maxspeed", "")
    try: return float(v.split()[0]) if "mph" in v else (float(v) * 0.621 if v else DEFAULT_MPH[cls])
    except ValueError: return DEFAULT_MPH[cls]
def _lanes(t, cls, oneway):
    try: return max(1, int(str(t.get("lanes", "")).split(";")[0]))
    except ValueError: return {0: 4, 1: 4, 2: 4, 3: 2, 4: 2}.get(cls, 2) // (2 if oneway else 1) or 1
def traffic_jobs(e, t, pts):
    hw = t["highway"]
    cls = TRAFFIC_CLASS.get(hw)
    nodes = e.get("nodes", [])
    if cls is None or len(nodes) != len(pts): return
    ow = t.get("oneway", "")
    oneway = -1 if ow == "-1" else (1 if ow in ("yes", "true", "1") or hw in ("motorway", "motorway_link") or t.get("junction") == "roundabout" else 0)
    lanes = _lanes(t, cls, oneway); mps = _mph(t, cls) * 0.44704
    w = road_width(t) or 7.0
    walk = 1 if (hw in SIDEWALK_ON and t.get("sidewalk") != "no" and t.get("bridge") in (None, "no")) else 0
    for i in range(len(pts) - 1):
        (x0, y0), (x1, y1) = pts[i], pts[i + 1]
        if math.hypot(x1 - x0, y1 - y0) < 0.05: continue
        seg_jobs[rkey((x0 + x1) / 2, (y0 + y1) / 2)].append(("rd", nodes[i], nodes[i + 1], x0, y0, x1, y1, cls, lanes, oneway, mps, w, walk))
    for i, nid in enumerate(nodes):
        node_classes[nid].append((cls, i in (0, len(nodes) - 1)))
        node_xy[nid] = pts[i]

_smp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "source_data", "street_names.json")
STREET_MAP = {k: v for k, v in json.load(open(_smp)).items() if not k.startswith("_")} if os.path.exists(_smp) else {}
road_polys, side_polys, bridge_ways = [], [], []
street_lines = []
street_keys = []           # parallel to street_lines: the real street name reduced to its core words (address matching)
_SFX = {"AVE", "AVENUE", "ST", "STREET", "RD", "ROAD", "DR", "DRIVE", "BLVD", "BOULEVARD", "LN", "LANE", "CT", "COURT", "PL",
        "PLACE", "WAY", "PKWY", "PARKWAY", "CIR", "CIRCLE", "TER", "TERRACE", "HWY", "N", "S", "E", "W", "NORTH", "SOUTH",
        "EAST", "WEST", "TRL", "TRAIL", "SQ", "PIKE"}
def street_key(name):
    return frozenset(w for w in re.sub(r"[^A-Z0-9 ]", " ", (name or "").upper()).split() if w not in _SFX and not w.isdigit())
ALLEY_TREE = [None]
seg_jobs = defaultdict(list)       # region -> centerline / street / lamp / streettree jobs
node_degree = defaultdict(int)

for e in els:
    if e["type"] == "way" and "highway" in tags(e):
        for nid in e.get("nodes", []): node_degree[nid] += 1

ALLEY_LINES = []
def utility_line(pts, w, is_alley):
    """Wooden utility poles every ~38 m with overhead wires between them: along every alley, and along one side
    of residential streets (those runs are dropped at build time where an alley runs within 45 m, because the
    lines then live in the alley). Jobs: ("upole", x, y, fx, fy, variant, street?) and ("uwire", x0, y0, x1, y1, street?)."""
    if is_alley: ALLEY_LINES.append(LineString(pts))
    side = 1 if is_alley else -1
    off = (w / 2 + (0.6 if is_alley else 0.75)) * side
    step = 38.0
    prev = None; acc = 0.0; d = step * 0.5
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        L = math.hypot(x1 - x0, y1 - y0)
        if L < 0.1: continue
        dx, dy = (x1 - x0) / L, (y1 - y0) / L
        while d < L:
            px, py = x0 + dx * d - dy * off, y0 + dy * d + dx * off
            hv = (math.sin(px * 12.9898 + py * 78.233) * 43758.5453) % 1.0
            var = "util_pole_t" if hv < 0.22 else "util_pole_f" if hv < 0.32 else "util_pole"
            seg_jobs[rkey(px, py)].append(("upole", px, py, dx, dy, var, not is_alley))
            if prev is not None and math.hypot(px - prev[0], py - prev[1]) < 60:
                mx, my = (px + prev[0]) / 2, (py + prev[1]) / 2
                seg_jobs[rkey(mx, my)].append(("uwire", prev[0], prev[1], px, py, not is_alley))
            prev = (px, py)
            d += step
        d -= L

rng = random.Random(42)
for e in els:
    t = tags(e)
    if e["type"] != "way" or "highway" not in t or t.get("area") == "yes": continue
    hw = t["highway"]; w = road_width(t)
    if w is None: continue
    pts = way_pts(e)
    if len(pts) < 2: continue
    line = LineString(pts)
    drivable = hw in WIDTH
    if drivable: traffic_jobs(e, t, pts)
    if t.get("bridge") not in (None, "no") and t.get("tunnel") in (None, "no"):
        bridge_ways.append((e, pts, w, drivable)); continue
    if drivable:
        road_polys.append(line.buffer(w / 2, cap_style="flat" if hw.startswith("motor") else "round", quad_segs=3))
        if hw not in ("service", "track", "motorway", "motorway_link"): street_lines.append(line); street_keys.append(street_key(t.get("name")))
        if hw in SIDEWALK_ON and t.get("sidewalk") != "no":
            side_polys.append(line.buffer(w / 2 + 2.8, quad_segs=3))
    else:
        side_polys.append(line.buffer(w / 2, quad_segs=2))
    center = drivable and hw in ("primary", "secondary", "tertiary", "trunk") and t.get("oneway") != "yes"
    name = STREET_MAP.get(t.get("name"), t.get("name")) if drivable else None   # parody street names
    acc_l = acc_t = 0.0
    lamp_step = 50.0 if hw in RESID else 36.0
    is_alley = hw == "service" and t.get("service") == "alley"
    if YARD_LIFE and (is_alley or hw in RESID) and t.get("bridge") in (None, "no"):
        utility_line(pts, w, is_alley)
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        L = math.hypot(x1 - x0, y1 - y0)
        if L < 0.1: continue
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        rk = rkey(mx, my)
        if center: seg_jobs[rk].append(("cl", x0, y0, x1, y1))
        if name: seg_jobs[rk].append(("st", name, x0, y0, x1, y1))
        if not (drivable and hw in SIDEWALK_ON): continue
        dx, dy = (x1 - x0) / L, (y1 - y0) / L
        d = lamp_step / 2 - acc_l
        while d < L:
            sides = (1,) if hw in RESID else (-1, 1)
            for side in sides:
                off = (w / 2 + 0.7) * side
                px, py = x0 + dx * d - dy * off, y0 + dy * d + dx * off
                seg_jobs[rkey(px, py)].append(("lamp", px, py, math.atan2(-dy * side, -dx * side)))
            d += lamp_step
        acc_l = (acc_l + L) % lamp_step
        if hw in RESID:   # street trees in the yard strip beyond the sidewalk
            d = 7.0 - acc_t
            while d < L:
                for side in (-1, 1):
                    if rng.random() < 0.55:
                        off = (w / 2 + 4.3) * side
                        px, py = x0 + dx * d - dy * off, y0 + dy * d + dx * off
                        seg_jobs[rkey(px, py)].append(("stree", px, py, rng.uniform(0.75, 1.3)))
                d += 14.0
            acc_t = (acc_t + L) % 14.0
log("roads", len(road_polys), "bridges", len(bridge_ways))

# ---------------------------------------------------------------- land use
park, parking, forest, industrial = [], [], [], []

# ---- intersection control: real OSM signals/stop signs if osm/extra/signals.json exists, else inferred from road classes
_sig = {}
_sigp = os.path.join(os.path.dirname(os.path.abspath(SRC.rstrip("/"))), "extra", "signals.json")
try: _sigd = json.load(open(_sigp)) if os.path.exists(_sigp) else {}
except ValueError: _sigd = {}
if _sigd:
    for _e in _sigd.get("elements", []):
        _sig[_e["id"]] = {"traffic_signals": "signal", "stop": "stop", "give_way": "yield"}.get(_e.get("tags", {}).get("highway"), "")
for _e in els:   # signal/stop nodes fetched with the map tiles (newer tiles include them)
    if _e["type"] == "node" and _e.get("tags", {}).get("highway") in ("traffic_signals", "stop", "give_way"):
        _sig[_e["id"]] = {"traffic_signals": "signal", "stop": "stop", "give_way": "yield"}[_e["tags"]["highway"]]
IX_SOURCE = f"osm for {len(_sig)} nodes, inferred elsewhere"
for nid, lst in node_classes.items():
    approaches = sum(1 if end else 2 for _, end in lst)
    if approaches < 3: continue
    cl = sorted(c for c, _ in lst)
    if cl[0] <= 1 and all(c <= 1 for c in cl): continue            # freeway merges: no control
    if nid in _sig and _sig[nid]:
        ctrl = _sig[nid]          # real OSM signal / stop sign
    else:                         # not mapped (or area without signal data): infer from road classes
        major = [c for c in cl if c <= 4]
        if len(major) >= 2 and len(lst) >= 2 and cl[1] <= 4: ctrl = "signal"
        elif major: ctrl = "stop_minor"
        elif approaches >= 4: ctrl = "all_stop"
        else: ctrl = "yield"
    if not ctrl: continue
    x, y = node_xy[nid]
    seg_jobs[rkey(x, y)].append(("ix", nid, x, y, ctrl, cl[0]))
log("traffic: intersections", sum(1 for v in seg_jobs.values() for j in v if j[0] == "ix"), "controls from", IX_SOURCE)

# made-up crop fields (make_countryside.py): one ground material per crop look
FIELD_KIND = {"wheat": 0, "maize": 1, "soy": 2, "hay": 3, "plowed": 4}
fields = [[] for _ in range(5)]
for e in els:
    t = tags(e)
    if "building" in t or "highway" in t or e["type"] == "node": continue
    lu, le, nat = t.get("landuse"), t.get("leisure"), t.get("natural")
    dst = None
    if le in ("park", "pitch", "garden", "playground", "stadium", "golf_course") or lu in ("grass", "recreation_ground", "cemetery", "meadow"):
        dst = park
    elif lu == "forest" or nat in ("wood", "scrub") or le == "nature_reserve":
        dst = forest
    elif lu == "farmland" and t.get("fictional"):
        dst = fields[FIELD_KIND.get(t.get("crop", ""), 0)]
    elif t.get("amenity") == "parking":
        dst = parking
    elif lu in ("industrial", "railway"):
        dst = industrial
    if dst is not None:
        g = area_geom(e)
        if g is not None and g.area < 2.5e7: dst.append(g)

def tree_of(lst):
    lst = [g for g in lst if g is not None and not g.is_empty]
    return (lst, STRtree(lst) if lst else None)
T_ROAD, T_SIDE, T_PARK, T_PARKING, T_FOREST, T_IND, T_WATER = map(tree_of, (road_polys, side_polys, park, parking, forest, industrial, WATER_TREE_SRC))
if os.environ.get("DUMP_WATER"):          # tools/pipeline/dem.py needs the same water polygons (river surface level)
    pickle.dump([g for g in WATER_TREE_SRC if g is not None and not g.is_empty], open(os.environ["DUMP_WATER"], "wb"))
    log("water dumped"); sys.exit(0)
T_FIELDS = [tree_of(f) for f in fields]

def local_union(tr, rb):
    lst, t = tr
    if t is None: return Polygon()
    idx = t.query(rb)
    if len(idx) == 0: return Polygon()
    try: return unary_union([lst[i] for i in idx]).buffer(0)
    except Exception: return unary_union([lst[i].buffer(0) for i in idx])

def safe(f, *a):
    try: return f(*a)
    except Exception:
        return f(*[x.buffer(0) for x in a])

# ---------------------------------------------------------------- bridges (global ramp solve, then bucket segments)
bnodes = defaultdict(list)
for idx, (e, pts, w, drv) in enumerate(bridge_ways):
    for nid in e["nodes"]: bnodes[nid].append(idx)
parent = list(range(len(bridge_ways)))
def find(i):
    while parent[i] != i: parent[i] = parent[parent[i]]; i = parent[i]
    return i
for nid, lst in bnodes.items():
    for o in lst[1:]: parent[find(o)] = find(lst[0])
comp = defaultdict(list)
for i in range(len(bridge_ways)): comp[find(i)].append(i)
node_pos = {}
for e, pts, w, drv in bridge_ways:
    for nid, p in zip(e["nodes"], pts): node_pos[nid] = p
RAMP = 45.0
node_h = {}
BRIDGE_CFG = [("glass city skyway", 40.0, 0.045, "skyway"), ("anthony wayne bridge", 32.3, 0.06, "suspension")]
special_bridges = defaultdict(list)
for root, members in comp.items():
    adj = defaultdict(list); layer = 1
    cfg = None
    for i in members:
        nm_ = tags(bridge_ways[i][0]).get("name", "").lower()
        for key_, deck_, grade_, kind_ in BRIDGE_CFG:
            if key_ in nm_:
                cfg = (deck_, grade_, kind_); special_bridges[kind_].append(bridge_ways[i])
    for i in members:
        e = bridge_ways[i][0]
        try: layer = max(layer, int(tags(e).get("layer", "1")))
        except ValueError: pass
        ns = e["nodes"]
        for a, b in zip(ns, ns[1:]):
            d = math.dist(node_pos[a], node_pos[b]); adj[a].append((b, d)); adj[b].append((a, d))
    H = 7.0 * max(1, min(layer, 3))
    ramp = RAMP
    if cfg:
        H = cfg[0]
        total = sum(w_ for n in adj for _, w_ in adj[n]) / 2
        ramp = min(H / cfg[1], max(60.0, total * 0.42))
    terms = [n for n in adj if node_degree[n] > len(bnodes[n]) or len(adj[n]) == 1]
    dist = {n: 0.0 for n in terms}; pq = [(0.0, n) for n in terms]
    while pq:
        d, n = heapq.heappop(pq)
        if d > dist.get(n, 1e18): continue
        for m, w_ in adj[n]:
            if d + w_ < dist.get(m, 1e18): dist[m] = d + w_; heapq.heappush(pq, (d + w_, m))
    # terrain under the ends: every node blends the ground heights of the bridge's ends by graph distance
    base = {n: 0.0 for n in adj}
    if DEM_DIR and terms:
        acc = {n: [0.0, 0.0] for n in adj}
        for t in terms[:12]:
            tz = TZ(*node_pos[t]); dd = {t: 0.0}; pq2 = [(0.0, t)]
            while pq2:
                d, n = heapq.heappop(pq2)
                if d > dd.get(n, 1e18): continue
                for m, w_ in adj[n]:
                    if d + w_ < dd.get(m, 1e18): dd[m] = d + w_; heapq.heappush(pq2, (d + w_, m))
            for n, d in dd.items():
                wgt = 1.0 / (d + 5.0) ** 2; acc[n][0] += tz * wgt; acc[n][1] += wgt
        base = {n: (a / b if b else 0.0) for n, (a, b) in acc.items()}
    for n in adj: node_h[n] = H * min(1.0, dist.get(n, ramp) / ramp) + base[n]

def densify(nodes, pts, step=8.0):
    out = []
    for (na, a), (nb, b) in zip(zip(nodes, pts), zip(nodes[1:], pts[1:])):
        ha, hb = node_h.get(na, 0), node_h.get(nb, 0)
        L = math.dist(a, b); k = max(1, int(L / step))
        for s in range(k):
            f = s / k
            out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, ha + (hb - ha) * f))
    out.append((pts[-1][0], pts[-1][1], node_h.get(nodes[-1], 0)))
    return out

for e, pts, w, drv in bridge_ways:
    dp = densify(e["nodes"], pts)
    for i in range(len(dp) - 1):
        mx, my = (dp[i][0] + dp[i + 1][0]) / 2, (dp[i][1] + dp[i + 1][1]) / 2
        seg_jobs[rkey(mx, my)].append(("br", dp[i], dp[i + 1], w, drv, i))
    if tags(e).get("name") and drv:
        for a, b in zip(pts, pts[1:]):
            seg_jobs[rkey((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)].append(("st", tags(e)["name"], a[0], a[1], b[0], b[1]))

def river_crossing(ways):
    """Midpoint and axis of where a set of bridge ways crosses open water."""
    cands = []
    for e, pts, w, drv in ways:
        ln = LineString(pts)
        try: inter = ln.intersection(WATER)
        except Exception: continue
        for g in getattr(inter, "geoms", [inter]):
            if isinstance(g, LineString) and g.length > 40:
                cs = list(g.coords)
                cands.append((g.length, g.interpolate(0.5, normalized=True), np.subtract(cs[-1], cs[0])))
    if not cands: return None
    best = max(cands, key=lambda c_: c_[0])
    u = best[2] / np.linalg.norm(best[2])
    # parallel carriageways crossing the same stretch of river: centre on the median between them
    near = [c_ for c_ in cands if c_[1].distance(best[1]) < 60 and abs(np.dot(c_[2] / np.linalg.norm(c_[2]), u)) > 0.9]
    mx = sum(c_[1].x for c_ in near) / len(near); my = sum(c_[1].y for c_ in near) / len(near)
    return mx, my, (float(u[0]), float(u[1])), best[0]

def build_skyway(ways, deck):
    rc = river_crossing(ways)
    if rc is None: return
    # pylon sits in the median: average the river crossings of all carriageways
    cx, cy, u, wl = rc
    v = (-u[1], u[0])
    top = 121.0
    wbox("concrete_dk", cx, cy, u, v, 6.0, 3.2, BED_Y, deck - 2, top=False, hu1=5.0, hv1=2.8)
    wbox("concrete_dk", cx, cy, u, v, 5.0, 2.8, deck - 2, top - 60, top=False, hu1=4.2, hv1=2.4)
    wbox("glass_lit", cx, cy, u, v, 4.2, 2.4, top - 60, top, top=True, hu1=3.2, hv1=1.9)
    for side in (-1, 1):                         # single plane of stays, combined fan/harp
        for k in range(20):
            s_ = 24 + k * 8.2
            dp = (cx + u[0] * s_ * side, cy + u[1] * s_ * side, deck + 1.2)
            ap = (cx + u[0] * 2.5 * side, cy + u[1] * 2.5 * side, deck + 24 + k * 2.9)
            wbeam("cable", ap, dp, 0.18)
    log("skyway pylon at", round(cx), round(cy))

def build_suspension(ways, deck):
    rc = river_crossing(ways)
    if rc is None: return
    cx, cy, u, wl = rc
    v = (-u[1], u[0])
    half_main, side_len = 119.6, 71.2
    tower_top = 61.3 + WATER_Y
    leg_off = 10.2
    deck_y = deck + GROUND_COL_Y
    for t in (-1, 1):
        tx, ty = cx + u[0] * half_main * t, cy + u[1] * half_main * t
        for l in (-1, 1):
            lx, ly = tx + v[0] * leg_off * l, ty + v[1] * leg_off * l
            wbox("bridge_blue", lx, ly, u, v, 1.3, 1.1, BED_Y, tower_top, top=True, hu1=0.9, hv1=0.8)
        for zb in (deck_y - 2.5, deck_y + 12, tower_top - 1.5):    # struts
            wbeam("bridge_blue", (tx + v[0] * leg_off, ty + v[1] * leg_off, zb), (tx - v[0] * leg_off, ty - v[1] * leg_off, zb), 0.6, True)
        for a_, b_ in ((deck_y + 12, tower_top - 1.5), (deck_y - 2.5, deck_y + 12)):  # X bracing
            wbeam("bridge_blue", (tx + v[0] * leg_off, ty + v[1] * leg_off, a_), (tx - v[0] * leg_off, ty - v[1] * leg_off, b_), 0.35)
            wbeam("bridge_blue", (tx - v[0] * leg_off, ty - v[1] * leg_off, a_), (tx + v[0] * leg_off, ty + v[1] * leg_off, b_), 0.35)
    for l in (-1, 1):                                             # main cables + paired suspenders
        ox, oy = v[0] * leg_off * l, v[1] * leg_off * l
        def cable_z(s_):
            a = abs(s_)
            if a <= half_main: return deck_y + 2.0 + (tower_top - 1.0 - deck_y - 2.0) * (a / half_main) ** 2
            f = (a - half_main) / side_len
            return tower_top - 1.0 - (tower_top - 1.0 - deck_y - 1.0) * f
        span = half_main + side_len
        prev = None
        for k in range(0, 61):
            s_ = -span + 2 * span * k / 60
            p_ = (cx + u[0] * s_ + ox, cy + u[1] * s_ + oy, cable_z(s_))
            if prev: wbeam("bridge_blue", prev, p_, 0.35)
            prev = p_
        s_ = -span + 6.1
        while s_ < span - 3:
            z_top = cable_z(s_)
            if z_top - deck_y > 1.5:
                for d_ in (-0.25, 0.25):
                    bx_, by_ = cx + u[0] * (s_ + d_) + ox, cy + u[1] * (s_ + d_) + oy
                    wbeam("cable", (bx_, by_, deck_y + 0.8), (bx_, by_, z_top), 0.05)
            s_ += 6.1
        for t in (-1, 1):                                         # anchorage blocks
            ax_, ay_ = cx + u[0] * span * t + ox * 1.15, cy + u[1] * span * t + oy * 1.15
            wbox("concrete_dk", ax_, ay_, u, v, 6, 2.0, 0.0, deck_y - 1.6)
    log("suspension towers at", round(cx), round(cy))

ZBASE[0] = 0.0
for kind_, ways_ in special_bridges.items():
    cfg_ = [c_ for c_ in BRIDGE_CFG if c_[3] == kind_][0]
    (build_skyway if kind_ == "skyway" else build_suspension)(ways_, cfg_[1])
ZBASE[0] = None

def emit_bridge_seg(p0, p1, w, drv, i):
    (x0, y0, h0), (x1, y1, h1) = p0, p1
    L = math.hypot(x1 - x0, y1 - y0)
    if L < 0.05: return
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    if not BBOX_P.contains(Point(mx, my)): return
    c = chunk_at(mx, my)
    dx, dy = (x1 - x0) / L, (y1 - y0) / L; nx, ny = -dy, dx
    mat = "asphalt" if drv else "sidewalk"
    hw_ = w / 2 + (0.6 if drv else 0.2)
    ex = 0.3
    ax, ay = x0 - dx * ex, y0 - dy * ex; bx, by = x1 + dx * ex, y1 + dy * ex
    top0, top1 = h0 + GROUND_COL_Y + 0.02, h1 + GROUND_COL_Y + 0.02
    l0 = to3(c, ax - nx * hw_, ay - ny * hw_, top0); r0 = to3(c, ax + nx * hw_, ay + ny * hw_, top0)
    l1 = to3(c, bx - nx * hw_, by - ny * hw_, top1); r1 = to3(c, bx + nx * hw_, by + ny * hw_, top1)
    slope = (h1 - h0) / L
    n = np.array([-dx * slope, 1.0, dy * slope]); n = tuple(float(v) for v in n / np.linalg.norm(n))
    quad(c, mat, l0, l1, r1, r0, n, [(0, 0), (L / 6, 0), (L / 6, w / 6), (0, w / 6)], True)
    if max(h0, h1) > 0.6:
        for side in (-1, 1):
            sx, sy = nx * hw_ * side, ny * hw_ * side
            q0 = (ax + sx, ay + sy); q1 = (bx + sx, by + sy)
            nn = (nx * side, 0.0, -ny * side); inn = (-nn[0], 0.0, -nn[2])
            quad(c, "concrete_dk", to3(c, *q0, top0 - 1.2), to3(c, *q1, top1 - 1.2), to3(c, *q1, top1), to3(c, *q0, top0), nn, [(0, 0), (L / 4, 0), (L / 4, .3), (0, .3)])
            quad(c, "concrete_dk", to3(c, *q0, top0), to3(c, *q1, top1), to3(c, *q1, top1 + 1.0), to3(c, *q0, top0 + 1.0), nn, [(0, 0), (L / 4, 0), (L / 4, .25), (0, .25)], True)
            quad(c, "concrete_dk", to3(c, *q0, top0), to3(c, *q1, top1), to3(c, *q1, top1 + 1.0), to3(c, *q0, top0 + 1.0), inn, [(0, 0), (L / 4, 0), (L / 4, .25), (0, .25)], True)
        quad(c, "concrete_dk", to3(c, ax - nx * hw_, ay - ny * hw_, top0 - 1.2), to3(c, bx - nx * hw_, by - ny * hw_, top1 - 1.2),
             to3(c, bx + nx * hw_, by + ny * hw_, top1 - 1.2), to3(c, ax + nx * hw_, ay + ny * hw_, top0 - 1.2), (0, -1.0, 0), [(0, 0), (1, 0), (1, 1), (0, 1)])
    if i % 3 == 0 and min(h0, h1) > 3.5:
        c.props.append(["pillar", mx - c.ox, -(my - c.oy), min(h0, h1) - 1.0, w])

def emit_centerline(x0, y0, x1, y1, water_p):
    L = math.hypot(x1 - x0, y1 - y0)
    if L < 1: return
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    if not BBOX_P.contains(Point(mx, my)): return
    cw = chunk_at(mx, my)                # the whole line stays in its own chunk (region-safe)
    if DEM_DIR and L > 24:              # follow the terrain: paint in short pieces
        k = int(L / 12) + 1
        for i in range(k):
            a, b = i / k, (i + 1) / k
            emit_centerline_1(x0 + (x1 - x0) * a, y0 + (y1 - y0) * a, x0 + (x1 - x0) * b, y0 + (y1 - y0) * b, water_p, i == 0, i == k - 1, cw)
        return
    emit_centerline_1(x0, y0, x1, y1, water_p, True, True, cw)

def emit_centerline_1(x0, y0, x1, y1, water_p, first=True, last=True, cw=None):
    L = math.hypot(x1 - x0, y1 - y0)
    if L < 1: return
    dx, dy = (x1 - x0) / L, (y1 - y0) / L; nx, ny = -dy, dx
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    if not BBOX_P.contains(Point(mx, my)) or water_p.contains(Point(mx, my)): return
    c = cw if cw is not None else chunk_at(mx, my)
    tr = 4 if L > 12 or not (first and last) else 0
    sx0, sy0 = (x0 + dx * tr, y0 + dy * tr) if first else (x0, y0)
    sx1, sy1 = (x1 - dx * tr, y1 - dy * tr) if last else (x1, y1)
    for off in (-0.18, 0.18):
        ox, oy, h = nx * off, ny * off, 0.06
        p = [(sx0 + ox - nx * h, sy0 + oy - ny * h), (sx1 + ox - nx * h, sy1 + oy - ny * h), (sx1 + ox + nx * h, sy1 + oy + ny * h), (sx0 + ox + nx * h, sy0 + oy + ny * h)]
        q = [to3(c, x, y, 0.1) for x, y in p]
        quad(c, "yellowline", q[0], q[1], q[2], q[3], UP, [(0, 0), (1, 0), (1, 1), (0, 1)])

def ring_walls(geom, R_ext, top, bot, mat):
    for p in polys_of(geom):
        p = orient(p, 1.0)
        for ring in [p.exterior] + list(p.interiors):
            cs = list(ring.coords)
            for (x0, y0), (x1, y1) in zip(cs, cs[1:]):
                L = math.hypot(x1 - x0, y1 - y0)
                if L < 0.01: continue
                mx, my = (x0 + x1) / 2, (y0 + y1) / 2
                if R_ext.distance(Point(mx, my)) < 0.05: continue   # artificial region/bbox cut edge
                c = chunk_at(mx, my)
                nx, ny = -(y1 - y0) / L, (x1 - x0) / L
                n = (nx, 0.0, -ny)
                b0 = (x0 - c.ox, bot, -(y0 - c.oy)); b1 = (x1 - c.ox, bot, -(y1 - c.oy))      # bed: absolute; top: on the bank
                quad(c, mat, b0, b1, to3(c, x1, y1, top), to3(c, x0, y0, top), n,
                     [(0, bot / 3), (L / 3, bot / 3), (L / 3, top / 3), (0, top / 3)], True)

# ---------------------------------------------------------------- buildings
PARODY = {
    "fifth third field": "Fifth Fourth Field", "fifth third center": "Fifth Fourth Center",
    "huntington center": "Huntingdon Centre", "pnc bank": "PNB Tower", "owens corning": "Owings Cornwell HQ",
    "imagination station": "Imagine Station", "hilton": "Hillside Inn", "marriott": "Merriwood Hotel",
    "renaissance": "Renaissant Hotel", "the blade": "The Toledo Edge", "toledo blade": "The Toledo Edge",
    "amtrak": "Toledo Rail Station", "promedica": "ProMedix", "mercy health": "Merciful Health",
    "jeep": "Jeepers Assembly", "stellantis": "Stellantine Assembly", "walmart": "ValuMart", "kroger": "Krogan's",
    "meijer": "Mayer's", "costco": "CostKo", "home depot": "Home Despot", "lowe's": "Lowly's", "target": "Targit",
}
SCHOOLS_PATH = os.environ.get("SCHOOLS", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "source_data", "school_names.json"))
SCHOOLS = json.load(open(SCHOOLS_PATH)) if os.path.exists(SCHOOLS_PATH) else {}
GOV_OK = ("courthouse", "county", "city", "government", "federal", "library", "church", "cathedral", "museum",
          "safety building", "post office", "school", "university", "station", "civic", "hospital", "zoo", "college", "stadium", "arena")
BRANDY = ("credit union", "bank", "inc", "llc", "hotel", "store", "market", "restaurant", "bar ", "grill")

buildings, parts = [], []
for e in els:
    t = tags(e)
    if e["type"] == "node": continue
    if "building:part" in t and t.get("building:part") != "no":
        g = area_geom(e)
        if g is not None: parts.append((e, g))
    elif "building" in t:
        g = area_geom(e)
        if g is not None and g.area > 4: buildings.append((e, g))
part_tree = STRtree([g.representative_point() for _, g in parts]) if parts else None
log("buildings", len(buildings), "parts", len(parts))

def num(s):
    if s is None: return None
    try: return float(str(s).split(";")[0].replace("m", "").strip())
    except ValueError: return None

HOUSEY = ("house", "detached", "semidetached_house", "residential", "terrace", "bungalow")
def classify(kind, area):
    if kind in HOUSEY: return "house"
    if kind in ("garage", "garages", "shed", "carport"): return "garage"
    if kind == "yes" and area < 55: return "garage"
    if kind == "yes" and area < 260: return "house"
    return kind

def h_of(t, rnd, cls, dist_core, owe):
    h = num(t.get("height"))
    if h is None:
        lv = num(t.get("building:levels"))
        if lv is not None: h = lv * 3.6 + (1.0 if lv > 1 else 0.5)
    if h is None:
        if cls == "house": h = (9.5 + rnd * 3.0) if owe else (6.0 + rnd * 2.5)
        elif cls == "garage": h = 3.0
        elif cls in ("roof", "carport"): h = 3.2
        elif cls == "parking": h = 10 + rnd * 8
        elif dist_core < 450: h = 12 + rnd * 18
        elif dist_core < 900: h = 9 + rnd * 9
        elif cls in ("industrial", "warehouse", "commercial", "retail"): h = 7 + rnd * 5
        else: h = 6 + rnd * 6
    mn = num(t.get("min_height"))
    if mn is None:
        ml = num(t.get("building:min_level"))
        mn = ml * 3.6 if ml else 0.0
    return max(h, mn + 2.5), mn

def style_of(t, cls, h, x, y, rnd, owe):
    dcore = math.hypot(x, y)
    mat = t.get("building:material", "")
    if cls in ("house", "garage"):
        if owe: return "brick_brown" if rnd < 0.3 else f"siding{3 + int(rnd * 30) % 3}"
        if rnd < 0.18: return "brick_red"
        return f"siding{int(rnd * 600) % 6}"
    if h > 38: return "glass" if rnd < 0.65 else "concrete"
    if mat == "brick": return "brick_red"
    if mat == "glass": return "glass"
    if mat in ("concrete", "stone"): return "concrete"
    if -900 < y < -150 and -700 < x < 450 and cls in ("industrial", "warehouse", "commercial", "yes", "retail", "apartments"):
        return "warehouse" if rnd < 0.6 else "brick_red"
    if cls in ("industrial", "warehouse", "manufacture"): return "warehouse" if rnd < 0.5 else "metal"
    if cls in ("retail", "commercial", "supermarket") and dcore > 1500: return "concrete" if rnd < 0.5 else "brick_tan"
    if cls == "parking": return "concrete"
    if dcore < 700: return ["brick_red", "brick_brown", "brick_tan", "concrete"][int(rnd * 4) % 4]
    if cls in ("apartments", "school", "church"): return "brick_brown" if rnd < .5 else "brick_red"
    return ["brick_red", "brick_brown", "brick_tan", "concrete"][int(rnd * 4) % 4]

# ---- county-record facades: real wall material, era-correct windows, paint palettes typical of each era
ERA_TINTS = {"old": ["#e9e3d2", "#c8b386", "#7f8d6f", "#9b5c4b", "#61748a", "#d8c27c", "#5e6b5a", "#efe8d8"],
             "mid": ["#eeeadc", "#bab29b", "#8f9c86", "#c6a679", "#7f90a2", "#e6dcc1", "#a8826a", "#f3efe4"],
             "post": ["#f2f0ea", "#cfd3cf", "#a3b3c1", "#e3d6b5", "#b9aa92", "#a7b59c", "#e9e4d4", "#c9c2b2"],
             "new": ["#f4f2ec", "#d9d5c9", "#c3c5c0", "#b7ab95", "#8f9ba4", "#e8e0cc", "#a6a294", "#d2c6ad"]}
HOUSE_MATS = [f"h_clap_{e}#{i}" for e in ERA_TINTS for i in range(8)] + [f"h_lap#{e}{i}" for e in ERA_TINTS for i in range(8)] + \
             [f"h_brick_{e}" for e in ERA_TINTS] + ["h_stucco", "h_stone", "h_block"]
def era_of(y):
    return "old" if y < 1915 else "mid" if y < 1946 else "post" if y < 1980 else "new"
def _f(t, k, d=0.0):
    try: return float(t.get(k, d) or d)
    except ValueError: return d
def county_style(t, g, h, rnd, cls, store, m, e):
    """Pick facade/height/porch from the county record. Returns (mat, cls, h, store)."""
    luc = t.get("c:luc", ""); wall = t.get("c:wall", ""); y = int(_f(t, "c:year")); st = _f(t, "c:stories")
    ctype = int(_f(t, "c:ctype", -1)); era = era_of(y) if y > 1700 else "mid"
    tint = int(rnd * 997) % 8
    has_lidar = m is not None and "h" in m and m.get("n", 0) >= 6
    # AREIS ctype 12 is "converted/mixed": a house only on a residential (5xx) parcel. On a commercial or exempt
    # parcel (Main St, Starr Ave) it is an 1890s brick block with a shop below, not a sided house
    resid = ctype in (2, 3, 4, 5) or ((ctype < 0 or ctype == 12) and luc[:1] == "5")
    if ctype == 12 and luc[:1] != "5" and (st or 1) <= 4 and g.area < 2500:
        mat = ["brick_red", "brick_brown"][int(rnd * 2) % 2]       # photo wall colour (BLOOKS) tints it later
        if not has_lidar and st: h = st * 4.2 + 0.8
        if st and h > st * 4.6 + 3.5: h = st * 4.3 + 1.2
        return mat, "retail", h, (st or 1) >= 2 or h > 6.5
    lid_h = m["h"] if has_lidar else (st or 1) * 3.0
    # big street trees over small East-Toledo-style houses push the LiDAR top up to 15-27 m: a 1.5-storey house
    # can't be taller than its storeys plus a steep roof, so cap it (and its wings) at that
    if resid and st and st <= 3 and g.area < 650:
        cap = st * 3.0 + 6.0
        e["_hcap"] = cap
        if lid_h > cap: lid_h = st * 3.0 + 4.0; h = min(h, lid_h)
    if resid and (g.area >= 650 or lid_h > 13.5 or (st or 1) > 3):
        resid = False; ctype = 1                     # big residential = apartment block, not a house
    if resid and g.area < 650:
        tla_fp = _f(t, "c:tla") * 0.0929 / max(1.0, min(st or 1, 2.5))
        if g.area < 90 and (tla_fp == 0 or g.area < 0.55 * tla_fp):
            cls = "garage"
            mat = f"h_lap#{era if era != 'old' else 'mid'}{tint}" if wall != "brick" else f"h_brick_{era}"
            if not has_lidar: h = 3.3
            return mat, cls, h, False
        cls = "house"
        if wall == "brick": mat = f"h_brick_{era}"
        elif wall == "stucco": mat = "h_stucco"
        elif wall == "stone": mat = "h_stone"
        elif wall == "block": mat = "h_block"
        else: mat = f"h_clap_{era}#{tint}"
        if wall == "partbrick":
            e["_base"] = (f"h_brick_{era}", 1.1 if st <= 1.3 else 3.0)
        e["_porch"] = {"old": 0.92, "mid": 0.85, "post": 0.22, "new": 0.12}[era]
        if not has_lidar: h = max(3.0, (st or 1) * 2.9) + 2.0
        if e.get("_hcap"): h = min(h, e["_hcap"])
        return mat, cls, h, False
    # ---------------- commercial / institutional by AREIS structure type
    if not has_lidar and st: h = st * (4.2 if st <= 2 else 3.7) + 0.8
    if st and st <= 4 and h > st * 4.6 + 3.5 and g.area < 3000:
        h = st * 4.3 + 1.2                     # LiDAR top is a street tree or a sign, not the building
    if ctype < 0 and luc[:1] == "4" and luc not in ("401", "402", "403", "404") and (st or 1) <= 3 and g.area < 2500:
        # neighbourhood commercial strip (Main St, Starr Ave, Front St): brick shopfronts, storefront ground floor
        if era in ("old", "mid"):
            mat = ["brick_red", "brick_brown", "brick_tan"][int(rnd * 3) % 3]
            return mat, "retail", h, (st or 1) >= 2 or h > 6.5
        return ("brick_tan" if rnd < 0.5 else "concrete"), "retail", h, False
    if luc[:2] == "68" and ctype not in (103, 104, 105, 106, 130, 131, 1) and g.area < 2500:
        # religious land use (680-689): a church even when AREIS files it as an office or converted building
        # (811 E Broadway: a stone-and-brick gabled church with a bell tower, recorded as structure type 22)
        return ("h_stone" if era == "old" and rnd < 0.5 else "brick_tan" if era in ("old", "mid") else "brick_brown"), "church", h, False
    if ctype in (20, 21, 22, 23, 24, 30, 31, 32, 33, 34, 35) and st == 1 and h > 5.8 and g.area < 1500:
        h = 5.8                                      # one-storey shop or office: the extra LiDAR height is trees/signs
    if ctype == 1 or (resid and g.area >= 650):     # apartments
        small = g.area < 500 and lid_h <= 13.5
        if small:
            mat = f"h_brick_{era}" if era != "new" else (f"h_clap_new#{tint}" if rnd < 0.5 else "h_brick_new")
        else:
            mat = ["brick_red", "brick_brown", "brick_tan"][int(rnd * 3) % 3] if era in ("old", "mid") else ("brick_tan" if rnd < 0.5 else "concrete")
        return mat, "apartments", h, False
    if ctype == 11:                                 # mixed residential/commercial: storefront under brick
        return ("brick_red" if rnd < 0.5 else "brick_brown"), "commercial", h, True
    if ctype in (20, 21, 22, 23, 24):
        if era in ("old", "mid"): mat = "brick_tan" if rnd < 0.5 else "brick_brown"
        elif era == "post": mat = "concrete" if rnd < 0.5 else "brick_tan"
        else: mat = "glass" if (st or 1) >= 3 else ("brick_tan" if rnd < 0.6 else "concrete")
        return mat, "office", h, False
    if ctype in (30, 31, 32, 33, 34, 35):
        return ("brick_tan" if rnd < 0.6 else "brick_red"), "retail", h, ctype in (30, 34, 35) and era in ("old", "mid")
    if 40 <= ctype <= 49 or ctype in (123, 125):
        return ("concrete" if rnd < 0.5 else "brick_tan") if era in ("post", "new") else "brick_red", "retail", h, True
    if 60 <= ctype <= 66 or ctype == 128:
        return ("metal" if rnd < 0.5 else "concrete"), "commercial", h, False
    if 67 <= ctype <= 76 or ctype == 126:
        return ("brick_red" if era in ("old", "mid") else ("warehouse" if rnd < 0.6 else "metal")), "industrial", h, False
    if ctype == 112:
        return ("h_stone" if era == "old" else "brick_brown" if era == "mid" else "brick_tan"), "church", h, False
    if ctype in (103, 104, 130, 131, 105, 106):
        return ("brick_brown" if rnd < 0.5 else "brick_red"), "school", h, False
    if ctype in (107, 129, 10):
        return ("brick_tan" if era in ("old", "mid") else "concrete"), "hospital", h, False
    if ctype in (8, 9, 122):
        if lid_h <= 12 and g.area < 900:
            return (f"h_clap_new#{tint}" if era == "new" else "brick_tan"), "hotel", h, False
        return ("concrete" if era in ("post", "new") else "brick_tan"), "hotel", h, False
    return None, cls, h, store

TILE = {"brick_red": (7, 7), "brick_brown": (7, 7), "brick_tan": (7, 7), "warehouse": (12, 9),
        "glass": (6, 8), "concrete": (12, 10.5), "metal": (8, 6)}
for i in range(6): TILE[f"siding{i}"] = (5, 5)
for _m in HOUSE_MATS:
    TILE[_m] = (3.4 if "_old" in _m else 5.0, 2.95) if not _m.startswith("h_lap") else (4.0, 2.95)
TILE["h_block"] = (4.0, 2.95)
TILE.update({"hsid": (2.4, 2.4), "hbrk": (1.45, 1.45), "hstu": (3.0, 3.0), "hstn": (2.2, 2.2), "hblk": (2.2, 2.2)})
def tile_of(mat):
    mat = mat.split("~")[0]
    if mat in TILE: return TILE[mat]
    b = mat.split("@")[0].split("#")[0]
    if b.startswith("hbrk"): b = "hbrk"
    return TILE.get(b, TILE.get(mat.split("@")[0] + "#0", (6, 6)))
TILE.update({m: (8, 4.5) for m in ["bar_shooters","bar_anchor","bar_cardboard","bar_easypour","bar_velvet","bar_lakefront","bar_coyote","bar_gator","dive_twobuck","dive_dollar","dive_cornertap","dive_happyhour","dive_tipsytom","dive_bar","dive_lastcall"]})
TILE.update({"storefront": (8, 4.2), "intl_dark": (4.5, 3.9), "glass_oneseagate": (6, 3.9), "limestone": (6, 4.2),
             "granite_black": (6, 4.5), "yamasaki": (3, 3.9), "terracotta": (5, 4.0), "sandstone": (6, 5), "marble": (8, 8),
             "glass_dark": (6, 3.6), "glass_blue": (6, 3.6), "seats": (2, 2), "porch": (3, 3)})

# ---- landmark registry: real heights (CTBUH / Wikipedia) and facade materials for Toledo's skyline
LANDMARKS = {
    "w429957698": dict(h=121.9, mat="intl_dark"),                                   # Tower on the Maumee (Fiberglas Tower), 1969
    "w429957793": dict(h=112.2, mat="limestone", base=("granite_black", 8.0), crown="deco"),  # PNC Bank Bldg, 1930 Art Deco
    "w189305197": dict(h=99.8, mat="yamasaki"),                                     # Government Center (Yamasaki), 1982
    "w429962019": dict(h=88.0, mat="terracotta", base=("limestone", 9.0)),         # Riverfront Apts (Toledo Trust), 1913
    "w429787172": dict(h=76.8, mat="glass_dark"),                                   # Summit Center / ProMedica Senior Care
    "w189371898": dict(h=76.2, mat="brick_tan", base=("limestone", 8.0)),          # Nicholas Building, 1906
    "w580662591": dict(h=70.1, mat="glass_dark"),                                   # Edison Plaza, 1972
    "w189369980": dict(h=64.0, mat="glass_blue"),                                   # Hylant (LOF) Building, 1960
    "w429963849": dict(h=54.9, mat="brick_brown"),                                  # AT&T / Ohio Bell, 1925
    "w429955308": dict(h=54.3, mat="brick_tan", base=("limestone", 7.0)),          # Ohio Building, 1906
    "w171964340": dict(h=49.1, mat="glass_dark"),                                   # Renaissance Toledo Downtown
    "w189372081": dict(h=56.1, mat="brick_brown"),                                  # Four SeaGate (brown)
    "w189371912": dict(h=42.4, mat="brick_tan", base=("limestone", 6.0)),          # Spitzer Building, 1896
    "w708650218": dict(h=37.2, mat="sandstone"),                                    # Pythian Castle, 1890
    "w189363860": dict(mat="sandstone"),                                            # Lucas County Courthouse
    "w233893958": dict(mat="marble", colonnade=True),                               # Toledo Museum of Art (Greek Revival)
    "w189367647": dict(mat="limestone"),                                            # Main Library (Art Deco)
    "r8833546": dict(mat="sandstone"),                                              # University Hall, UT
}
POINT_LANDMARKS = [((41.65333, -83.53056), dict(h=125.3, mat="glass_oneseagate", name="One SeaGate"))]
LID = pickle.load(open(LIDAR_PKL, "rb")) if LIDAR_PKL and os.path.exists(LIDAR_PKL) else {}
for _ev in ("LIDAR2", "LIDAR3"):          # LIDAR3 = exact downtown massing (full-res LiDAR), applied last
    _l2 = os.environ.get(_ev, "")
    if _l2 and os.path.exists(_l2): LID.update(pickle.load(open(_l2, "rb")))
log("lidar measurements", len(LID))
# real trees measured from LiDAR (tools/pipeline/lidar_trees.py): [x, z_game, height, crown radius]
LTREES = defaultdict(list)
_lt = os.environ.get("LTREES", "")
if _lt and os.path.exists(_lt):
    for _x, _z, _h, _r in json.load(open(_lt))["trees"]: LTREES[rkey(_x, -_z)].append((_x, -_z, _h, _r))
log("lidar trees", sum(len(v) for v in LTREES.values()))
STREET_TREE = STRtree(street_lines) if street_lines else None

def rect_frame(g):
    rect = g.minimum_rotated_rectangle
    if not isinstance(rect, Polygon) or rect.area <= 0 or g.area / rect.area < 0.82: return None
    cs = list(rect.exterior.coords)[:4]
    e0 = math.dist(cs[0], cs[1]); e1 = math.dist(cs[1], cs[2])
    if e0 < e1: cs = cs[1:] + cs[:1]; e0, e1 = e1, e0
    return cs, e0, e1, rect

def dome(c, cx, cy, r, z0, hgt, mat):
    rings, segs = 6, 14
    pts = [[(cx + r * math.cos(a_ / segs * 2 * math.pi) * math.cos(b_ / rings * math.pi / 2),
             cy + r * math.sin(a_ / segs * 2 * math.pi) * math.cos(b_ / rings * math.pi / 2),
             z0 + hgt * math.sin(b_ / rings * math.pi / 2)) for a_ in range(segs + 1)] for b_ in range(rings + 1)]
    for b_ in range(rings):
        for a_ in range(segs):
            p0, p1, p2, p3 = pts[b_][a_], pts[b_][a_ + 1], pts[b_ + 1][a_ + 1], pts[b_ + 1][a_]
            mx = (p0[0] + p2[0]) / 2 - cx; my = (p0[1] + p2[1]) / 2 - cy; mz = ((p0[2] + p2[2]) / 2 - z0) * r / max(hgt, 0.1)
            L = math.sqrt(mx * mx + my * my + mz * mz) or 1
            quad(c, mat, to3(c, *p0), to3(c, *p1), to3(c, *p2), to3(c, *p3), (mx / L, mz / L, -my / L), [(0, 0), (1, 0), (1, 1), (0, 1)], True)

def pitched_roof(c, g, h, mat_wall, ridge, kind="gable", roof_mat="shingle", ov=0.45):
    """Gable / cross-gable / hip roof on a near-rectangular footprint, walls already up to h.
    The roof planes overhang the walls by `ov` (eaves + rakes) with a soffit underneath and a fascia board."""
    fr = rect_frame(g)
    if fr is None: return False
    cs, e0, e1, rect = fr
    if kind == "gable_cross":          # ridge runs across the short axis
        cs = cs[1:] + cs[:1]; e0, e1 = e1, e0
    if e1 > 22: return False
    a, b, cc, d = cs                   # a-b and c-d are the eave edges parallel to the ridge
    cx_, cy_ = rect.centroid.x, rect.centroid.y
    ux, uy = (b[0] - a[0]) / e0, (b[1] - a[1]) / e0          # along the ridge
    vx, vy = (d[0] - a[0]) / e1, (d[1] - a[1]) / e1          # across it
    slope = ridge / max(e1 / 2, 0.5)
    def grow(p, su, sv):  # push a corner out along u (rake) and v (eave)
        return (p[0] + ux * su + vx * sv, p[1] + uy * su + vy * sv)
    rake = ov if kind != "hip" else ov
    A, B, CC, D = grow(a, -rake, -ov), grow(b, rake, -ov), grow(cc, rake, ov), grow(d, -rake, ov)
    he = h - ov * slope                                     # eave line drops as the slope continues out
    m0 = ((a[0] + d[0]) / 2, (a[1] + d[1]) / 2); m1 = ((b[0] + cc[0]) / 2, (b[1] + cc[1]) / 2)
    M0, M1 = grow(m0, -rake, 0), grow(m1, rake, 0)
    if kind == "hip":                  # pull ridge ends inward by half the width -> four sloped faces
        inset = min(e1 / 2, e0 / 2 - 0.3)
        m0 = (m0[0] + ux * inset, m0[1] + uy * inset); m1 = (m1[0] - ux * inset, m1[1] - uy * inset)
        M0, M1 = m0, m1
    top = h + ridge
    P3 = lambda p, z: to3(c, p[0], p[1], z)
    def face_n(p, q, rise, run):
        ex, ey = q[0] - p[0], q[1] - p[1]; L = math.hypot(ex, ey)
        nx, ny = ey / L, -ex / L
        if ((p[0] + q[0]) / 2 - cx_) * nx + ((p[1] + q[1]) / 2 - cy_) * ny < 0: nx, ny = -nx, -ny
        n = np.array([nx * rise, run, -ny * rise]); return tuple(float(v) for v in n / np.linalg.norm(n)), L, (nx, ny)
    for (p, q) in ((A, B), (CC, D)):   # long slopes
        n, L, _ = face_n(p, q, ridge, e1 / 2)
        rp = M0 if math.dist(M0, p) < math.dist(M1, p) else M1
        rq = M1 if rp is M0 else M0
        S_ = math.hypot(ridge, e1 / 2 + ov) / 2.0
        quad(c, roof_mat, P3(p, he), P3(q, he), P3(rq, top), P3(rp, top), n, [(0, S_), (L / 2.0, S_), (L / 2.0, 0), (0, 0)], True)
        # soffit: underside of the overhang, back to the wall line
        wp = grow(p, 0, ov if p in (A, B) else -ov); wq = grow(q, 0, ov if q in (A, B) else -ov)
        quad(c, TRIM_MAT[0], P3(wp, he), P3(wq, he), P3(q, he), P3(p, he), (0.0, -1.0, 0.0), [(0, 0), (1, 0), (1, 1), (0, 1)])
        # fascia board on the eave edge
        _, _, (nx, ny) = face_n(p, q, 1, 1)
        quad(c, TRIM_MAT[0], P3(p, he - 0.22), P3(q, he - 0.22), P3(q, he), P3(p, he), (nx, 0.0, -ny), [(0, 0), (1, 0), (1, 1), (0, 1)])
    for (p, q, m, wp, wq) in ((D, A, M0, d, a), (B, CC, M1, b, cc)):
        if kind == "hip":
            n, L, _ = face_n(p, q, ridge, max(math.dist(m, ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)), 0.5))
            S_ = math.hypot(ridge, max(math.dist(m, ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)), 0.5)) / 2.0
            tri(c, roof_mat, P3(p, he), P3(q, he), P3(m, top), n, [(0, S_), (L / 2.0, S_), (L / 4.0, 0)], True)
        else:
            _, L, (nx, ny) = face_n(wp, wq, 1, 1)
            tw, th = tile_of(mat_wall)
            tri(c, mat_wall, P3(wp, h), P3(wq, h), P3(((wp[0] + wq[0]) / 2, (wp[1] + wq[1]) / 2), top), (nx, 0.0, -ny), [(0, -h / th), (L / tw, -h / th), (L / 2 / tw, -top / th)], True)
            # rake board along the gable edge
            for (e_, f_) in ((p, m), (m, q)):
                z0_, z1_ = (he, top) if e_ is p else (top, he)
                quad(c, TRIM_MAT[0], P3(e_, z0_ - 0.2), P3(f_, z1_ - 0.2), P3(f_, z1_), P3(e_, z0_), (nx, 0.0, -ny), [(0, 0), (1, 0), (1, 1), (0, 1)])
    return True

def chimney(c, g, h, ridge, rnd, mat="brick_red"):
    """brick chimney on an older house: on the ridge line near one gable end, rising ~1 m above the ridge."""
    fr = rect_frame(g)
    if fr is None: return
    cs, e0, e1, rect = fr
    a, b, cc, d = cs
    t = 0.2 if rnd < 0.5 else 0.8
    x = a[0] + (b[0] - a[0]) * t + (d[0] - a[0]) * 0.5; y = a[1] + (b[1] - a[1]) * t + (d[1] - a[1]) * 0.5
    u = ((b[0] - a[0]) / e0, (b[1] - a[1]) / e0); v = (-u[1], u[0])
    cbox(c, x, y, u, v, 0.45, 0.35, h - 0.5, h + ridge + 1.0, mat)

def _max_rect(M):
    """largest all-True axis-aligned rectangle in a bool matrix (histogram method) -> (area, i0, j0, i1, j1)."""
    H = np.zeros(M.shape[1], int); best = (0, 0, 0, 0, 0)
    for i in range(M.shape[0]):
        H = np.where(M[i], H + 1, 0); st = []
        for j in range(M.shape[1] + 1):
            hj = H[j] if j < M.shape[1] else 0
            start = j
            while st and st[-1][1] >= hj:
                s0, hh = st.pop()
                if hh * (j - s0) > best[0]: best = (hh * (j - s0), i - hh + 1, s0, i + 1, j)
                start = s0
            st.append((start, hj))
    return best

def rect_parts(g, res=0.5, max_parts=4):
    """Split an L / T / U / stepped house footprint into rectangles in its own frame, so each wing gets a real
    pitched roof (wings at the same pitch intersect like real cross gables)."""
    rect = g.minimum_rotated_rectangle
    if not isinstance(rect, Polygon): return []
    cs = list(rect.exterior.coords)[:4]
    if math.dist(cs[0], cs[1]) < math.dist(cs[1], cs[2]): cs = cs[1:] + cs[:1]
    ang = math.atan2(cs[1][1] - cs[0][1], cs[1][0] - cs[0][0]); ca, sa = math.cos(ang), math.sin(ang)
    ox, oy = g.centroid.x, g.centroid.y
    loc = shapely.affinity.affine_transform(g, [ca, sa, -sa, ca, -(ca * ox + sa * oy), -(-sa * ox + ca * oy)])
    x0, y0, x1, y1 = loc.bounds
    nx, ny = int(math.ceil((x1 - x0) / res)), int(math.ceil((y1 - y0) / res))
    if nx * ny > 40000 or nx < 4 or ny < 4: return []
    xs = x0 + (np.arange(nx) + 0.5) * res; ys = y0 + (np.arange(ny) + 0.5) * res
    gx, gy = np.meshgrid(xs, ys, indexing="ij")
    M = shapely.contains_xy(loc, gx, gy)
    total = M.sum(); parts = []
    while len(parts) < max_parts and M.sum() > 0.12 * total:
        a, i0, j0, i1, j1 = _max_rect(M)
        if a * res * res < 8.0 or min(i1 - i0, j1 - j0) * res < 2.5: break
        M[i0:i1, j0:j1] = False
        lx0, lx1, ly0, ly1 = x0 + i0 * res, x0 + i1 * res, y0 + j0 * res, y0 + j1 * res
        pts = [(lx0, ly0), (lx1, ly0), (lx1, ly1), (lx0, ly1)]
        parts.append(Polygon([(ox + ca * u - sa * v, oy + sa * u + ca * v) for u, v in pts]))
    return parts if len(parts) >= 1 and sum(q.area for q in parts) > 0.7 * g.area else []

def cbox(c, cx, cy, u, v, hu, hv, z0, z1, mat, collide=False, trim=False):
    """Oriented box in chunk space (porches, columns, crowns). trim=True: a board against a wall - no back
    (toward -v) and no top face (trim boards, gutters, downspouts are seen from the street)."""
    sg = [(1, 1), (-1, 1), (-1, -1), (1, -1)]
    cor = lambda a, b, z: to3(c, cx + u[0] * hu * a + v[0] * hv * b, cy + u[1] * hu * a + v[1] * hv * b, z)
    for k in range(4):
        (a0, b0), (a1, b1) = sg[k], sg[(k + 1) % 4]
        if trim and b0 == -1 and b1 == -1: continue
        nx, ny = u[0] * (a0 + a1) / 2 + v[0] * (b0 + b1) / 2, u[1] * (a0 + a1) / 2 + v[1] * (b0 + b1) / 2
        L = math.hypot(nx, ny) or 1
        quad(c, mat, cor(a0, b0, z0), cor(a1, b1, z0), cor(a1, b1, z1), cor(a0, b0, z1), (nx / L, 0.0, -ny / L), [(0, 0), (1, 0), (1, 1), (0, 1)], collide)
    if trim: return
    quad(c, mat, cor(1, 1, z1), cor(-1, 1, z1), cor(-1, -1, z1), cor(1, -1, z1), UP, [(0, 0), (1, 0), (1, 1), (0, 1)], collide)

def walls(c, p, z0, z1, mat):
    tw, th = tile_of(mat)
    for ring in [p.exterior] + list(p.interiors):
        cs = list(ring.coords); u = 0.0
        for (x0, y0), (x1, y1) in zip(cs, cs[1:]):
            L = math.hypot(x1 - x0, y1 - y0)
            if L < 0.05: continue
            nx, ny = (y1 - y0) / L, -(x1 - x0) / L
            quad(c, mat, to3(c, x0, y0, z0), to3(c, x1, y1, z0), to3(c, x1, y1, z1), to3(c, x0, y0, z1), (nx, 0.0, -ny),
                 [(u / tw, -z0 / th), ((u + L) / tw, -z0 / th), ((u + L) / tw, -z1 / th), (u / tw, -z1 / th)], True)
            u += L

# ---------------------------------------------------------------- parametric facades (downtown exact buildings)
# per-house paint from county reference photos (tools/pipeline/house_looks*.py): key -> wall/trim palette index, porch seen
HLOOKS = json.load(open(os.environ["HLOOKS"])) if os.environ.get("HLOOKS") and os.path.exists(os.environ["HLOOKS"]) else {}
TRIM_MAT = ["trim_white"]
VACANT = set(json.load(open(os.environ["VACANT"]))) if os.environ.get("VACANT") and os.path.exists(os.environ["VACANT"]) else set()
BLOOKS = json.load(open(os.environ["BLOOKS"])) if os.environ.get("BLOOKS") and os.path.exists(os.environ["BLOOKS"]) else {}
FACADES = json.load(open(os.environ["FACADES"])) if os.environ.get("FACADES") and os.path.exists(os.environ["FACADES"]) else {}
MAT_WALL = {"brick_red": ("#8c3a2c", 0.0), "brick_brown": ("#6e4430", 0.0), "brick_tan": ("#b89a72", 0.0), "concrete": ("#aaa69d", 0.5),
            "limestone": ("#cfc6b0", 0.25), "granite_black": ("#2a2a2c", 0.25), "metal": ("#8e9399", 0.75), "intl_dark": ("#2c2f33", 0.75),
            "yamasaki": ("#e6e3dc", 0.5), "terracotta": ("#cdbb9c", 0.25), "sandstone": ("#c8ab7c", 0.25), "marble": ("#e8e4dc", 0.25),
            "warehouse": ("#8a5a44", 0.0), "storefront": ("#5a5048", 0.5), "glass": ("#3a4652", 1.0), "glass_dark": ("#1d2329", 1.0),
            "glass_blue": ("#2e4a66", 1.0), "glass_oneseagate": ("#3c5a6e", 1.0), "copper_green": ("#6f9a86", 0.75)}
GLASS_OF = {"glass": 0, "glass_dark": 4, "glass_blue": 1, "glass_oneseagate": 1}

def hex_rgb(h):
    h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))

def default_facade(mat, t, h, cls, store, rnd):
    """Best guess from records until a building is matched to photos (FACADES file overrides any key)."""
    y = int(_f(t, "c:year")) if t else 0
    era = era_of(y) if y > 1700 else ("mid" if mat.startswith("brick") or mat in ("limestone", "terracotta", "sandstone") else "post")
    wall, wm = MAT_WALL.get(mat, ("#a9a59c", 0.5))
    if mat.startswith("h_brick"): wall, wm = ("#8c4a36", 0.0)
    if mat.startswith(("h_clap", "h_lap")): wall, wm = ("#d8d2c4", 0.5)
    sp = {"wall": wall, "wmat": wm, "floor": {"old": 4.3, "mid": 4.0, "post": 3.7, "new": 3.9}[era],
          "bay": {"old": 2.6, "mid": 2.8, "post": 3.0, "new": 3.0}[era], "ww": 0.5 if era in ("old", "mid") else 0.6,
          "wh": 0.58 if era in ("old", "mid") else 0.55, "style": 0, "glass": 0,
          "base": 4.6 if (store or cls in ("retail", "commercial")) and h > 7 else 0.0}
    if wm >= 1.0:
        sp.update(style=2, glass=GLASS_OF.get(mat, 0), bay=1.6, floor=3.9)
    elif era in ("post", "new") and cls in ("office", "commercial", "hospital") and rnd < 0.4:
        sp.update(style=1, wh=0.42, glass=1 if rnd < 0.15 else 0)
    if wm == 0.0 and not mat.startswith("h_"):
        # brick tones seen in downtown photos, by era (Italianate orange-red -> 1910s-20s red/buff -> post-war tan/brown)
        pal = {"old": ["#a5573c", "#9a4a35", "#b0623f", "#8c4a36", "#a0503a"],
               "mid": ["#8c3a2c", "#9b4a3a", "#b89a72", "#a98a64", "#7e4434", "#c2a982"],
               "post": ["#b89a72", "#8a6a50", "#a68e70", "#6e4430"], "new": ["#a68e70", "#8a5a44", "#b9a07e"]}[era]
        sp["wall"] = pal[int(rnd * 997) % len(pal)]
        if y and y < 1900 and cls not in ("industrial", "parking"):
            sp.update(style=5, ww=0.42, wh=0.62, bay=2.2, floor=4.4)   # Italianate: tall segmental-arch windows
    if cls in ("industrial",) or mat == "warehouse":
        sp.update(ww=0.55, wh=0.5, base=0.0, floor=4.6)
    if cls == "parking":
        sp.update(style=1, wh=0.45, glass=4, floor=3.1, wall="#a39f96", wmat=0.5, base=0.0)
    return sp

def fwalls(c, p, z0, z1, sp, base=True):
    r, g_, b_ = hex_rgb(sp["wall"])
    col4 = (r, g_, b_, float(sp["wmat"]))
    c0 = (float(sp["ww"]), float(sp["wh"]), float(sp["base"]) if base else 0.0, float(sp["style"] + 8 * sp["glass"]))
    V, N, U, U2, CO, C0 = c.fac
    for ring in [p.exterior] + list(p.interiors):
        cs = list(ring.coords); u = 0.0
        for (x0, y0), (x1, y1) in zip(cs, cs[1:]):
            L = math.hypot(x1 - x0, y1 - y0)
            if L < 0.05: continue
            nx, ny = (y1 - y0) / L, -(x1 - x0) / L
            n = (nx, 0.0, -ny)
            bw = L / max(1, round(L / sp["bay"])) if L > sp["bay"] * 0.6 else L
            a, b, cc, d = to3(c, x0, y0, z0), to3(c, x1, y1, z0), to3(c, x1, y1, z1), to3(c, x0, y0, z1)
            ua, ub, uc, ud = (0.0, z0), (L, z0), (L, z1), (0.0, z1)
            for tri_ in ((a, b, cc, ua, ub, uc), (a, cc, d, ua, uc, ud)):
                p0, p1, p2, q0, q1, q2 = tri_
                ab = (p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]); ac = (p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2])
                cr = (ab[1] * ac[2] - ab[2] * ac[1], ab[2] * ac[0] - ab[0] * ac[2], ab[0] * ac[1] - ab[1] * ac[0])
                if cr[0] * n[0] + cr[1] * n[1] + cr[2] * n[2] > 0: p1, p2, q1, q2 = p2, p1, q2, q1
                V.extend((p0, p1, p2)); N.extend((n, n, n)); U.extend((q0, q1, q2))
                U2.extend(((sp["floor"], bw),) * 3); CO.extend((col4,) * 3); C0.extend((c0,) * 3)
                c.col.extend((p0, p1, p2))
            u += L

def porch(c, p, rnd):
    """Front porch on the side of the house facing the nearest street."""
    if STREET_TREE is None: return
    k = STREET_TREE.nearest(p.centroid)
    road = street_lines[k]
    if road.distance(p) > 45: return
    rp = road.interpolate(road.project(p.centroid))
    best = None
    cs = list(orient(p, 1.0).exterior.coords)
    for (x0, y0), (x1, y1) in zip(cs, cs[1:]):
        L = math.hypot(x1 - x0, y1 - y0)
        if L < 5: continue
        nx, ny = (y1 - y0) / L, -(x1 - x0) / L
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        dx, dy = rp.x - mx, rp.y - my; dl = math.hypot(dx, dy) or 1
        score = (nx * dx + ny * dy) / dl
        if best is None or score > best[0]: best = (score, mx, my, (x1 - x0) / L, (y1 - y0) / L, nx, ny, L)
    if best is None or best[0] < 0.5: return
    _, mx, my, ux, uy, nx, ny, L = best
    wdt = min(L * 0.8, 7.5) / 2 if rnd < 0.6 else min(L * 0.45, 3.5) / 2
    if rnd >= 0.6: mx, my = mx + ux * (L / 2 - wdt - 0.3), my + uy * (L / 2 - wdt - 0.3)
    dep = 2.3
    pcx, pcy = mx + nx * dep / 2, my + ny * dep / 2
    cbox(c, pcx, pcy, (ux, uy), (nx, ny), wdt, dep / 2, 0.0, 0.55, "concrete_dk", True)         # deck
    cbox(c, pcx + nx * 0.15, pcy + ny * 0.15, (ux, uy), (nx, ny), wdt + 0.2, dep / 2 + 0.15, 2.85, 3.05, "porch")  # roof slab
    for s_ in (-1, 0, 1) if wdt > 2.5 else (-1, 1):
        cx_ = pcx + ux * (wdt - 0.2) * s_ + nx * (dep / 2 - 0.2); cy_ = pcy + uy * (wdt - 0.2) * s_ + ny * (dep / 2 - 0.2)
        cbox(c, cx_, cy_, (ux, uy), (nx, ny), 0.12, 0.12, 0.55, 2.85, "porch" if TRIM_MAT[0] == "trim_white" else TRIM_MAT[0])

def _modelz(name, x, y, z, fx, fy):
    if rkey(x, y) != CUR_REGION: return
    c = chunk_at(x, y); c.props.append(["m:" + name, round(x - c.ox, 2), round(-(y - c.oy), 2), round(z, 2), round(_yaw(fx, fy), 3)])

def front_edge(p, addr=None):
    """The house wall facing its street: (x0, y0, ux, uy, nx, ny, L) or None. With the county address, the street
    is the one the house is numbered on (corner houses face their address street, not just the nearest one)."""
    if STREET_TREE is None: return None
    road = street_lines[STREET_TREE.nearest(p.centroid)]
    if addr:
        ak = street_key(addr)
        if ak:
            near = [i for i in STREET_TREE.query(p.centroid.buffer(55)) if street_keys[i] & ak]
            if near: road = street_lines[min(near, key=lambda i: street_lines[i].distance(p))]
    if road.distance(p) > 45: return None
    rp = road.interpolate(road.project(p.centroid))
    best = None
    cs = list(orient(p, 1.0).exterior.coords)
    for (x0, y0), (x1, y1) in zip(cs, cs[1:]):
        L = math.hypot(x1 - x0, y1 - y0)
        if L < 4: continue
        nx, ny = (y1 - y0) / L, -(x1 - x0) / L
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        dx, dy = rp.x - mx, rp.y - my; dl = math.hypot(dx, dy) or 1
        sc = (nx * dx + ny * dy) / dl + L * 0.01
        if best is None or sc > best[0]: best = (sc, x0, y0, (x1 - x0) / L, (y1 - y0) / L, nx, ny, L)
    return best[1:] if best and best[0] > 0.45 else None

FLOOR = 2.85; DECK = 0.55
def house_style(wl, rnd, want_porch, look):
    """Toledo house features, from the hand-labelled photo when there is one, otherwise from what the photos show is
    typical for the house's measured shape (186 labelled houses): hipped two-storeys are Foursquares (front dormer,
    full porch, often on brick piers); front-gables mostly have a full porch; a share have enclosed sun porches."""
    lab = (look or {}).get("lab")
    if lab:
        return {"porch": lab[0], "dormer": lab[1] == "1", "shutters": lab[2] == "1", "awning": lab[4] == "1", "piers": lab[5] == "1"}
    main = max(wl, key=lambda w: w[0].area)
    hip = main[3] == "hip"; two = main[1] > 4.6
    r = lambda k: (rnd * (7.13 + k * 3.71)) % 1.0
    if not want_porch: porch = "N" if r(1) < 0.6 else "P"
    elif hip and two: porch = "F" if r(1) < 0.8 else ("E" if r(1) < 0.9 else "P")
    else: porch = "F" if r(1) < 0.55 else ("E" if r(1) < 0.75 else "P")
    return {"porch": porch,
            "dormer": (hip and two and r(2) < 0.7) or (main[3] in ("gable", "gable_cross") and r(2) < 0.12),
            "shutters": r(3) < 0.09, "awning": r(4) < 0.07,
            "piers": porch in ("F", "E") and r(5) < (0.6 if hip and two else 0.25)}

def dormer(c, p, wl, fe, mat):
    """A front dormer on the main roof slope that faces the street: box with a little hipped roof and two windows."""
    q, eave, top, shape = max(wl, key=lambda w: w[0].area)
    if shape == "flat" or top - eave < 2.4: return
    fx, fy = fe[4], fe[5]
    qc = list(orient(q, 1.0).exterior.coords)
    short = min(math.dist(*e_) for e_ in zip(qc, qc[1:]))
    slope = (top - eave) / max(short / 2, 0.5)
    for a_, b_ in zip(qc, qc[1:]):
        L = math.dist(a_, b_)
        ux, uy = (b_[0] - a_[0]) / L, (b_[1] - a_[1]) / L; nx, ny = uy, -ux
        if nx * fx + ny * fy < 0.85 or L < 5.0: continue
        if shape != "hip" and L < short + 0.5: continue          # gable end: no slope there
        mx, my = (a_[0] + b_[0]) / 2, (a_[1] + b_[1]) / 2
        dw = min(3.0, L * 0.4); s0 = 0.7
        zb = eave + s0 * slope; zt = zb + 1.45
        s1 = (zt - eave) / slope
        if s1 > short / 2 - 0.3: return
        P = lambda t, sdist, z: to3(c, mx + ux * t - nx * sdist, my + uy * t - ny * sdist, z)
        quad(c, mat, P(-dw / 2, s0, zb - 0.1), P(dw / 2, s0, zb - 0.1), P(dw / 2, s0, zt), P(-dw / 2, s0, zt), (nx, 0.0, -ny), [(0, 0), (dw / 2.4, 0), (dw / 2.4, 0.6), (0, 0.6)])
        for sg in (-1, 1):
            tri(c, mat, P(sg * dw / 2, s0, zb - 0.1), P(sg * dw / 2, s0, zt), P(sg * dw / 2, s1, zt), (sg * ux, 0.0, -sg * uy), [(0, 0), (0, 0.6), (0.6, 0.6)])
        # dormer roof: three slopes down from a short ridge, overhanging the face
        o_ = 0.3; zr = zt + 0.55; zr_e = zt - 0.05
        quad(c, "shingle", P(-dw / 2 - o_, s0 - o_, zr_e), P(dw / 2 + o_, s0 - o_, zr_e), P(dw / 4, s0 + 0.6, zr), P(-dw / 4, s0 + 0.6, zr), (nx * 0.6, 0.8, -ny * 0.6), [(0, 0.7), (dw / 2, 0.7), (dw / 2, 0), (0, 0)])
        for sg in (-1, 1):
            quad(c, "shingle", P(sg * (dw / 2 + o_), s0 - o_, zr_e), P(sg * (dw / 2 + o_), s1 + 0.4, zr_e + 0.1), P(sg * dw / 4, s1 + 0.4, zr), P(sg * dw / 4, s0 + 0.6, zr), (sg * ux * 0.6, 0.8, -sg * uy * 0.6), [(0, 0), (1, 0), (1, 0.6), (0, 0.6)])
        quad(c, TRIM_MAT[0], P(-dw / 2 - o_, s0 - o_, zr_e - 0.16), P(dw / 2 + o_, s0 - o_, zr_e - 0.16), P(dw / 2 + o_, s0 - o_, zr_e), P(-dw / 2 - o_, s0 - o_, zr_e), (nx, 0.0, -ny), [(0, 0), (1, 0), (1, 1), (0, 1)])
        for t in ((-0.38, 0.38) if dw >= 2.2 else (0.0,)):
            _modelz("hp_attic", mx + ux * t - nx * (s0 - 0.01), my + uy * t - ny * (s0 - 0.01), zb + 0.12, nx, ny)
        return

YARD_LIFE = os.environ.get("YARD_LIFE", "1") == "1"
def yard_life(c, p, fe, st, porch_span, rnd, hsh):
    """What makes a street look lived in (Bully, not a store-asset town): foundation shrubs along the front, the
    city trash carts beside the house, and now and then a bike, a grill, patio chairs on the porch or a kids'
    slide. Deterministic per house. Nothing is placed inside the house."""
    if not YARD_LIFE or fe is None: return
    x0, y0, ux, uy, nx, ny, L = fe
    inside = lambda x, y: p.buffer(0.35).contains(Point(x, y))
    def put(name, x, y, fx, fy, z=None):
        if inside(x, y) and z is None: return
        (_model(name, x, y, fx, fy) if z is None else _modelz(name, x, y, z, fx, fy))
    # foundation shrubs along the front, clear of the porch and the door
    if hsh(x0, y0, 1.0) < 0.75:
        n = 2 + int(hsh(x0, y0, 2.0) * 3)
        for i in range(n):
            t = (i + 0.5) * L / n
            if porch_span and porch_span[0] - 0.6 < t < porch_span[1] + 0.6: continue
            put("yard_shrub", x0 + ux * t + nx * 0.7, y0 + uy * t + ny * 0.7, nx, ny)
    # two trash carts beside the house, a few metres back from the front corner
    if hsh(x0, y0, 3.0) < 0.7:
        side = -1 if hsh(x0, y0, 4.0) < 0.5 else 1
        bx_, by_ = (x0, y0) if side < 0 else (x0 + ux * L, y0 + uy * L)
        trash = "yard_toter" if hsh(x0, y0, 9.0) < 0.6 else "yard_toter_k"
        for k, name in enumerate((trash, "yard_toter_b" if hsh(x0, y0, 10.0) < 0.8 else trash)):   # trash + recycling
            put(name, bx_ + ux * side * 1.0 - nx * (2.0 + k * 0.85), by_ + uy * side * 1.0 - ny * (2.0 + k * 0.85), nx, ny)
    # porch chairs
    if porch_span and st.get("porch") == "F" and hsh(x0, y0, 5.0) < 0.45:
        for k in (0.25, 0.4):
            t = porch_span[0] + (porch_span[1] - porch_span[0]) * k
            put("yard_chair", x0 + ux * t + nx * 1.1, y0 + uy * t + ny * 1.1, nx, ny, z=DECK)
    r = hsh(x0, y0, 6.0)
    if r < 0.16:      # a bike by the porch steps
        t = (porch_span[1] + 0.8) if porch_span else L * 0.7
        put("yard_bike", x0 + ux * min(t, L - 0.5) + nx * 1.6, y0 + uy * min(t, L - 0.5) + ny * 1.6, ux, uy)
    elif r < 0.36:    # a grill in the side yard
        side = 1 if hsh(x0, y0, 7.0) < 0.5 else -1
        bx_, by_ = (x0, y0) if side < 0 else (x0 + ux * L, y0 + uy * L)
        put("yard_grill", bx_ + ux * side * 1.6 - nx * 5.0, by_ + uy * side * 1.6 - ny * 5.0, nx, ny)
    elif r < 0.44:    # a kids' slide in the side yard
        side = 1 if hsh(x0, y0, 8.0) < 0.5 else -1
        bx_, by_ = (x0, y0) if side < 0 else (x0 + ux * L, y0 + uy * L)
        put("yard_slide", bx_ + ux * side * 2.4 - nx * 4.0, by_ + uy * side * 2.4 - ny * 4.0, ux, uy)

REGION_WALKS = []
def house_detail(c, p, wl, rnd, want_porch, mat, addr=None, look=None):
    """Real-looking house skin: 3D double-hung windows on every wall and floor, attic windows in the gables, a panel
    front door facing the street, corner boards, and a front porch (posts, railings, steps, shed roof)."""
    p = orient(p, 1.0)
    low = min(w[1] for w in wl)
    fe = front_edge(p, addr)
    hsh = lambda *a: (math.sin(sum(v * k for v, k in zip(a, (12.9898, 78.233, 37.719)))) * 43758.5453) % 1.0
    door_m = ("hp_door_r", "hp_door_k", "hp_door_w")[int(rnd * 31) % 3]
    porch_span = None
    st = house_style(wl, rnd, want_porch, look)
    if fe is not None:
        x0, y0, ux, uy, nx, ny, L = fe
        if st["porch"] != "N" and L >= 4.0:
            if st["porch"] == "P": pw = min(2.8, L - 0.6)
            else: pw = min(L - 0.4, 9.0) if rnd < 0.75 else min(L * 0.6, 5.0)
            t0 = (L - pw) / 2 if (st["porch"] != "P" and rnd < 0.75) else max(0.2, min(L - pw - 0.2, L * 0.62 - pw / 2))
            porch_span = (t0, t0 + pw)
            porch3d(c, x0 + ux * t0, y0 + uy * t0, ux, uy, nx, ny, pw, rnd, st, mat)
        if st["dormer"]: dormer(c, p, wl, fe, mat)
    yard_life(c, p, fe, st, porch_span, rnd, hsh)
    cs = list(p.exterior.coords)
    for ei, ((ax, ay), (bx, by)) in enumerate(zip(cs, cs[1:])):
        L = math.hypot(bx - ax, by - ay)
        if L < 1.0: continue
        ux, uy = (bx - ax) / L, (by - ay) / L; nx, ny = uy, -ux
        if YARD_LIFE and L >= 1.5:     # grime band: splash-back and dirt along the bottom of every wall
            quad(c, "grime_base", to3(c, ax + nx * 0.025, ay + ny * 0.025, 0.0), to3(c, bx + nx * 0.025, by + ny * 0.025, 0.0),
                 to3(c, bx + nx * 0.025, by + ny * 0.025, 1.0), to3(c, ax + nx * 0.025, ay + ny * 0.025, 1.0),
                 (nx, 0.0, -ny), [(0, 0), (L / 2.5, 0), (L / 2.5, 1), (0, 1)])     # image top row = wall base
        # corner board at the start of every edge (convex corners; concave ones hide inside the wall)
        if TRIM_MAT[0] and mat.startswith("hsid"):
            cbox(c, ax + nx * 0.03 + ux * 0.07, ay + ny * 0.03 + uy * 0.07, (ux, uy), (nx, ny), 0.07, 0.03, DECK - 0.05, min(low, 9.0) - 0.05, TRIM_MAT[0], trim=True)
        if L < 1.7: continue
        mx, my = (ax + bx) / 2, (ay + by) / 2
        probe = Point(mx - nx * 0.6, my - ny * 0.6)
        eave = max([w[1] for w in wl if w[0].buffer(0.4).contains(probe)] or [low])
        is_front = fe is not None and abs(fe[0] - ax) < 1e-6 and abs(fe[1] - ay) < 1e-6
        n = max(1, int((L - 0.6) / 2.6))
        slots = [(i + 0.5) * L / n for i in range(n)]
        fw = (look or {}).get("fw") if is_front else None          # window columns counted in the house's photo
        door_t = None
        if is_front:
            door_t = (porch_span[0] + porch_span[1]) / 2 if porch_span else (slots[n // 2] if n > 1 else L / 2)
            if porch_span and n >= 2: door_t = min(slots, key=lambda t: abs(t - (porch_span[0] + 1.0)))
            if porch_span and st["porch"] == "P": door_t = (porch_span[0] + porch_span[1]) / 2
            if look and look.get("dx") is not None:                 # door position read off the photo
                door_t = min(max(look["dx"] * L, 0.8), L - 0.8)
            # walk from the door (or the porch steps) straight out to the street
            dep_ = (1.6 if st["porch"] == "P" else 2.4 if rnd < 0.7 else 2.0) + 0.9 if porch_span and porch_span[0] - 0.1 <= door_t <= porch_span[1] + 0.1 else 0.9
            sx_, sy_ = ax + ux * door_t + nx * dep_, ay + uy * door_t + ny * dep_
            rd = street_lines[STREET_TREE.nearest(Point(sx_, sy_))] if STREET_TREE is not None else None
            if rd is not None:
                k_ = rd.distance(Point(sx_, sy_))
                if 1.0 < k_ < 40: REGION_WALKS.append(LineString([(sx_ - nx * 0.3, sy_ - ny * 0.3), (sx_ + nx * k_, sy_ + ny * k_)]).buffer(0.6, cap_style="flat"))
            _modelz(door_m, ax + ux * door_t + nx * 0.01, ay + uy * door_t + ny * 0.01, DECK, nx, ny)
            if not porch_span: _modelz("hp_steps", ax + ux * door_t, ay + uy * door_t, 0.0, nx, ny)
        floors = max(1, int(round((eave - DECK) / FLOOR)))
        fh = (eave - DECK) / floors
        if fh < 2.45 and floors > 1: floors -= 1; fh = (eave - DECK) / floors
        for f in range(floors):
            zs = DECK + f * fh + min(0.82, max(0.45, fh - 1.55 - 0.3))
            if zs + 1.55 > eave - 0.08: break
            sl_ = slots
            if fw and fw[min(f, 1)] > 0:
                nf = min(fw[min(f, 1)], max(1, int((L - 0.6) / 1.1)))
                sl_ = [(i + 0.5) * L / nf for i in range(nf)]
            for t in sl_:
                if f == 0 and door_t is not None and abs(t - door_t) < 1.3: continue
                if t < 0.65 or t > L - 0.65: continue
                h_ = hsh(ax, ay, t * 3 + f)
                name = "hp_win_b" if h_ < 0.3 else "hp_win"
                if is_front and f == 0 and L / len(sl_) >= 2.4 and h_ > 0.45 and not fw: name = "hp_win2"
                if st["shutters"] and is_front and name != "hp_win2": name = "hp_win_sh" if rnd < 0.6 else "hp_win_shr"
                if st["awning"] and (is_front or h_ < 0.4) and not (f == 0 and porch_span and is_front):
                    _modelz("hp_awning", ax + ux * t + nx * 0.02, ay + uy * t + ny * 0.02, zs + 1.72, nx, ny)
                _modelz(name, ax + ux * t + nx * 0.01, ay + uy * t + ny * 0.01, zs, nx, ny)
    # gable-end attic windows: the short sides of each gable wing, where they are outside walls
    for q, eave, top, shape in wl:
        if shape not in ("gable", "gable_cross") or top - eave < 2.7: continue
        qc = list(orient(q, 1.0).exterior.coords)
        es = sorted(zip(qc, qc[1:]), key=lambda e_: math.hypot(e_[1][0] - e_[0][0], e_[1][1] - e_[0][1]))
        for (a_, b_) in es[:2]:
            L = math.hypot(b_[0] - a_[0], b_[1] - a_[1])
            if L < 3.0: continue
            mx, my = (a_[0] + b_[0]) / 2, (a_[1] + b_[1]) / 2
            if p.exterior.distance(Point(mx, my)) > 0.5: continue
            nx, ny = (b_[1] - a_[1]) / L, -(b_[0] - a_[0]) / L
            _modelz("hp_attic", mx + nx * 0.01, my + ny * 0.01, eave + 0.3, nx, ny)
    # gutters along every eave edge and a downspout at each end
    for q, eave, top, shape in wl:
        if shape == "flat": continue
        qc = list(orient(q, 1.0).exterior.coords)
        es = list(zip(qc, qc[1:]))
        short = min(math.dist(*e_) for e_ in es)
        ov = 0.45; he = eave - (top - eave) * ov / max(short / 2, 0.5)
        eaves = es if shape == "hip" else sorted(es, key=lambda e_: -math.dist(*e_))[:2]
        for (a_, b_) in eaves:
            L = math.dist(a_, b_)
            if L < 2.0: continue
            ux, uy = (b_[0] - a_[0]) / L, (b_[1] - a_[1]) / L; nx, ny = uy, -ux
            mx, my = (a_[0] + b_[0]) / 2, (a_[1] + b_[1]) / 2
            if p.exterior.distance(Point(mx, my)) > 0.6: continue
            cbox(c, mx + nx * (ov + 0.07), my + ny * (ov + 0.07), (ux, uy), (nx, ny), L / 2 + ov, 0.065, he - 0.3, he - 0.12, TRIM_MAT[0], trim=True)
            sgn = 1 if (int(mx * 7 + my * 3) & 1) else -1           # one downspout per gutter, at the back-ish end
            ex, ey = mx + ux * sgn * (L / 2 - 0.15) + nx * 0.06, my + uy * sgn * (L / 2 - 0.15) + ny * 0.06
            cbox(c, ex, ey, (ux, uy), (nx, ny), 0.045, 0.035, 0.0, he - 0.3, TRIM_MAT[0], trim=True)

def porch3d(c, sx, sy, ux, uy, nx, ny, pw, rnd, st=None, wall_mat="hsid#mid0"):
    """Front porch along a wall from (sx, sy) for pw metres: deck, a hipped roof with fascia and painted ceiling, and
    by kind - open with posts and railings (F), a small stoop (P), enclosed with windows (E); brick piers and knee
    walls instead of posts and rails when st["piers"]."""
    st = st or {"porch": "F", "piers": False}
    kind = st["porch"]; piers = st.get("piers") and kind != "P"
    dep = 1.6 if kind == "P" else (2.4 if rnd < 0.7 else 2.0)
    cx, cy = sx + ux * pw / 2 + nx * dep / 2, sy + uy * pw / 2 + ny * dep / 2
    cbox(c, cx, cy, (ux, uy), (nx, ny), pw / 2, dep / 2, -0.2, DECK, "concrete_dk", True)          # deck
    z_beam = DECK + 2.38
    ov = 0.3; zr1 = z_beam + 0.12; D = dep + ov
    zr0 = zr1 + D * 0.42                                                                           # ~23 degree pitch
    def P(t, d, z): return to3(c, sx + ux * t + nx * d, sy + uy * t + ny * d, z)
    t0, t1 = -ov, pw + ov
    dd = min(D, (t1 - t0) / 2 - 0.05)
    zr0 = zr1 + dd * 0.42
    nz = 1 / math.hypot(1, 0.42)
    # hipped porch roof: front slope + two side slopes, rising to the house wall
    quad(c, "shingle", P(t0, D, zr1), P(t1, D, zr1), P(t1 - dd, D - dd, zr0), P(t0 + dd, D - dd, zr0), (nx * 0.42 * nz, nz, -ny * 0.42 * nz), [(0, D / 2), ((t1 - t0) / 2, D / 2), ((t1 - t0 - dd) / 2, 0), (dd / 2, 0)])
    if D - dd > 0.05:
        quad(c, "shingle", P(t0 + dd, D - dd, zr0), P(t1 - dd, D - dd, zr0), P(t1 - dd, 0, zr0), P(t0 + dd, 0, zr0), UP, [(0, 0), (1, 0), (1, 1), (0, 1)])
    for sg, te, ti in ((-1, t0, t0 + dd), (1, t1, t1 - dd)):
        quad(c, "shingle", P(te, 0, zr1), P(te, D, zr1), P(ti, D - dd, zr0), P(ti, 0, zr0), (sg * ux * 0.42 * nz, nz, -sg * uy * 0.42 * nz), [(0, 0), (D / 2, 0), (D / 2, dd / 2), (0, dd / 2)])
    for (a_, b_, nn) in (((t0, D), (t1, D), (nx, ny)), ((t0, 0), (t0, D), (-ux, -uy)), ((t1, D), (t1, 0), (ux, uy))):     # fascia
        quad(c, TRIM_MAT[0], P(a_[0], a_[1], zr1 - 0.2), P(b_[0], b_[1], zr1 - 0.2), P(b_[0], b_[1], zr1), P(a_[0], a_[1], zr1), (nn[0], 0.0, -nn[1]), [(0, 0), (1, 0), (1, 1), (0, 1)])
    quad(c, TRIM_MAT[0], P(t0, 0, zr1 - 0.2), P(t0, D, zr1 - 0.2), P(t1, D, zr1 - 0.2), P(t1, 0, zr1 - 0.2), (0.0, -1.0, 0.0), [(0, 0), (1, 0), (1, 1), (0, 1)])   # ceiling
    cbox(c, sx + ux * pw / 2 + nx * (dep - 0.14), sy + uy * pw / 2 + ny * (dep - 0.14), (ux, uy), (nx, ny), pw / 2 + 0.05, 0.12, z_beam, zr1 - 0.2, TRIM_MAT[0])   # beam
    mid = pw / 2
    _modelz("hp_steps", sx + ux * mid + nx * dep, sy + uy * mid + ny * dep, 0.0, nx, ny)
    if kind == "P":
        for t in (0.2, pw - 0.2):
            _modelz("hp_post", sx + ux * t + nx * (dep - 0.15), sy + uy * t + ny * (dep - 0.15), DECK, nx, ny)
        return
    nposts = max(2, int(pw / 2.6) + 1)
    pts = [min(max(i * pw / (nposts - 1), 0.25), pw - 0.25) for i in range(nposts)]
    if kind == "E":
        # sun porch: siding knee wall and a ribbon of windows on the front and ends
        for (a_, b_, nn, ln) in ((0.0, pw, (nx, ny), pw),):
            cbox(c, sx + ux * pw / 2 + nx * (dep - 0.1), sy + uy * pw / 2 + ny * (dep - 0.1), (ux, uy), (nx, ny), pw / 2, 0.1, DECK, DECK + 0.85, wall_mat)
        for sg in (0, 1):
            t = 0.1 if sg == 0 else pw - 0.1
            cbox(c, sx + ux * t + nx * dep / 2, sy + uy * t + ny * dep / 2, (nx, ny), (ux, uy), dep / 2, 0.1, DECK, DECK + 0.85, wall_mat)
        nw = max(1, int((pw - 0.4) / 1.9))
        for i in range(nw):
            t = 0.2 + (i + 0.5) * (pw - 0.4) / nw
            if abs(t - mid) < 0.6 and nw > 2: continue                  # entry door gap
            _modelz("hp_win2", sx + ux * t + nx * dep, sy + uy * t + ny * dep, DECK + 0.8, nx, ny)
        for t in (0.1, pw - 0.1):
            _modelz("hp_win", sx + ux * t + nx * dep / 2, sy + uy * t + ny * dep / 2, DECK + 0.8, ux if t > 1 else -ux, uy if t > 1 else -uy)
        _modelz("hp_door_w", sx + ux * mid + nx * (dep + 0.01), sy + uy * mid + ny * (dep + 0.01), DECK, nx, ny)
        return
    for t in pts:
        _modelz("hp_pier" if piers else "hp_post", sx + ux * t + nx * (dep - 0.25 if piers else dep - 0.15), sy + uy * t + ny * (dep - 0.25 if piers else dep - 0.15), DECK, nx, ny)
    if piers:
        # brick knee wall between the piers, open at the steps
        for a, b in zip(pts, pts[1:]):
            lo, hi = a + 0.25, b - 0.25
            for (u0, u1) in ((lo, min(hi, mid - 0.8)), (max(lo, mid + 0.8), hi)):
                if u1 - u0 > 0.3:
                    cbox(c, sx + ux * (u0 + u1) / 2 + nx * (dep - 0.25), sy + uy * (u0 + u1) / 2 + ny * (dep - 0.25), (ux, uy), (nx, ny), (u1 - u0) / 2, 0.11, DECK, DECK + 0.8, "hbrk_old")
        for t in (0.25, pw - 0.25):
            cbox(c, sx + ux * t + nx * (dep / 2 - 0.1), sy + uy * t + ny * (dep / 2 - 0.1), (nx, ny), (ux, uy), dep / 2 - 0.4, 0.11, DECK, DECK + 0.8, "hbrk_old")
        return
    for a, b in zip(pts, pts[1:]):
        t = a + 0.62
        while t + 0.5 <= b - 0.1:
            if abs(t - mid) > 0.95:
                _modelz("hp_rail", sx + ux * t + nx * (dep - 0.15), sy + uy * t + ny * (dep - 0.15), DECK, nx, ny)
            t += 1.0
    for t in (0.25, pw - 0.25):
        d = 0.6
        while d + 0.5 <= dep - 0.3:
            _modelz("hp_rail", sx + ux * t + nx * d, sy + uy * t + ny * d, DECK, ux, uy)
            d += 1.0

def deco_crown(c, p, h, mat):
    """PNC-style Art Deco setbacks with a stepped pyramidal top (after the Mausoleum at Halicarnassus)."""
    tiers = [(0.71, 0.0), (0.82, 3.0), (0.90, 6.0)]
    z0 = -0.3
    last = p
    for frac, inset in tiers:
        q = p.buffer(-inset, join_style=2) if inset else p
        q = max(polys_of(q), key=lambda a: a.area) if polys_of(q) else last
        walls(c, orient(q, 1.0), z0, h * frac, mat); flat_poly(c, "roof", q, h * frac, 6.0, True)
        z0 = h * frac; last = q
    fr = rect_frame(last.buffer(-1.5, join_style=2)) or rect_frame(last)
    if fr is None: return
    cs, e0, e1, rect = fr
    ap = rect.centroid
    steps = 6
    for k in range(steps):      # stepped pyramid
        f = 1 - k / steps
        cs_k = [(ap.x + (x - ap.x) * f, ap.y + (y - ap.y) * f) for x, y in cs]
        poly = Polygon(cs_k)
        zz0 = h * 0.90 + (h * 0.1) * k / steps; zz1 = h * 0.90 + (h * 0.1) * (k + 1) / steps
        walls(c, orient(poly, 1.0), zz0, zz1, mat); flat_poly(c, "roof", poly, zz1, 6.0, True)

def colonnade(c, p, h):
    hc = min(h * 0.8, 13.0)
    cs = list(orient(p, 1.0).exterior.coords)
    for (x0, y0), (x1, y1) in zip(cs, cs[1:]):
        L = math.hypot(x1 - x0, y1 - y0)
        if L < 30: continue
        ux, uy = (x1 - x0) / L, (y1 - y0) / L; nx, ny = uy, -ux
        n = int(L / 4.2)
        for k in range(1, n):
            cx_, cy_ = x0 + ux * k * L / n + nx * 1.6, y0 + uy * k * L / n + ny * 1.6
            cbox(c, cx_, cy_, (ux, uy), (nx, ny), 0.45, 0.45, 0.0, hc, "marble", True)
        mx0, my0 = x0 + nx * 1.6, y0 + ny * 1.6
        cbox(c, (x0 + x1) / 2 + nx * 1.6, (y0 + y1) / 2 + ny * 1.6, (ux, uy), (nx, ny), L / 2, 1.2, hc, hc + 1.4, "marble", True)

# per-wing LiDAR fit (tools/pipeline/house_fit.py): key -> [{"rect", "h", "eave", "shape", "n"}]
HWINGS = pickle.load(open(os.environ["HWINGS"], "rb")) if os.environ.get("HWINGS") and os.path.exists(os.environ["HWINGS"]) else {}

def emit_wings(c, p, hw, mat, roof_mat, z0, rnd, min_eave=0.0):
    """A house as its measured wings: every wing gets its own wall height and roof (gable/hip/flat) from the LiDAR."""
    wl = []
    tot = sum(Polygon(w_["rect"]).area for w_ in hw) or 1.0
    for w_ in hw:
        q = Polygon(w_["rect"])
        if not q.is_valid or q.area < 4: continue
        eave = max(2.5, min(w_["eave"], w_["h"] - 0.6)); top = max(eave + 0.6, w_["h"])
        if q.area > 0.35 * tot and eave < min_eave and top > min_eave + 1.2:
            eave = min_eave
        wl.append((q, eave, top, w_["shape"]))
    if not wl:
        walls(c, p, z0, 3.0, mat); flat_poly(c, "roof", p, 3.0, 6.0, True); return
    low = min(x[1] for x in wl)
    walls(c, p, z0, low, mat)
    flat_poly(c, "roof", p, low, 6.0, True)          # under-deck for any sliver the wings miss
    mi = max(range(len(wl)), key=lambda i: wl[i][0].area)
    for i, (q, eave, top, shape) in enumerate(wl):
        q = orient(q, 1.0)
        if shape == "flat":
            walls(c, q, low, top, mat); flat_poly(c, "roof", q, top, 6.0, True); continue
        if eave > low + 0.4: walls(c, q, low, eave, mat)
        ridge = max(0.8, min(7.0, top - eave))
        if not pitched_roof(c, q, eave, mat, ridge, "hip" if shape == "hip" else "gable", roof_mat):
            flat_poly(c, "roof", q, eave, 6.0, True)
        elif i == mi and ((rnd * 5.71) % 1.0) < 0.55 and ridge > 1.5:
            chimney(c, q, eave, ridge, (rnd * 9.13) % 1.0)

def emit_building(e, g, h, mn, mat, rnd, cls, cp, roof=None, eave=None, tiers=None, lm=None, store=False, roof_mat="shingle"):
    c = chunk_at(cp.x, cp.y)
    g = g.simplify(0.25, preserve_topology=True)
    b0 = mn if mn > 0 else -0.3
    if lm and lm.get("crown") == "deco" and not e.get("_exact"):
        for p in polys_of(g):
            base = lm.get("base")
            if base: walls(c, orient(p, 1.0), -0.3, base[1], base[0])
            deco_crown(c, p, h, mat)
        return
    if tiers and (not lm or e.get("_exact")):
        for tier in tiers:
            z0, z1, wkt = tier[:3]
            fspec = e.get("_fspec")
            if len(tier) > 3 and fspec:   # a sub-building inside this footprint with its own facade (e.g. Secor in the convention centre)
                fspec = dict(fspec); fspec.update(FACADES.get(tier[3], {}))
            for p in polys_of(shapely.from_wkt(wkt)):
                p = orient(p, 1.0)
                zb = -0.3 if z0 <= 0.5 else z0
                if z0 <= 0.5 and lm and lm.get("base"):
                    walls(c, p, zb, min(lm["base"][1], z1), lm["base"][0]); zb = min(lm["base"][1], z1)
                elif z0 <= 0.5 and store and z1 > 6 and not e.get("_fspec"):
                    walls(c, p, zb, 4.2, "storefront"); zb = 4.2
                if fspec:
                    fwalls(c, p, zb, z1, fspec, base=z0 <= 0.5)
                else:
                    walls(c, p, zb, z1, mat)
                flat_poly(c, "roof", p, z1, 6.0, True)
        return
    for p in polys_of(g):
        p = orient(p, 1.0)
        kind = roof
        if kind is None and cls in ("house", "garage") and e.get("tags", {}).get("roof:shape") != "flat":
            kind = "gable" if rnd < 0.62 else "hip"
        if kind is None and cls == "church" and p.area < 900 and e.get("tags", {}).get("roof:shape") != "flat":
            kind = "gable"                       # neighbourhood churches: a steep gable, not a flat office roof
        if kind == "dome":
            r_ = math.sqrt(p.area / math.pi)
            dome_h = min(r_ * 0.9, 25.0)
            walls(c, p, b0, h - dome_h if h - dome_h > 3 else h, mat)
            dome(c, p.centroid.x, p.centroid.y, r_, h - dome_h if h - dome_h > 3 else h, dome_h, roof_mat if roof_mat != "shingle" else "cable")
            continue
        hw = e.get("_hw") if cls == "house" and not lm else None
        if hw:
            z = b0
            if e.get("_base"):
                bm_, bh_ = e["_base"]; bh_ = min(bh_, min(w_["eave"] for w_ in hw) - 0.3)
                if bh_ > z + 0.3: walls(c, p, z, bh_, bm_); z = bh_
            emit_wings(c, p, hw, mat, roof_mat, z, rnd, e.get("_hw_eave", 0.0))
            walls(c, p.buffer(0.08, join_style=2) if p.area > 20 else p, -0.3, 0.55, "foundation")
            want_porch = ((rnd * 3.17) % 1.0) < e.get("_porch", 0.78) and 45 < p.area < 300
            if e.get("_detail"):
                house_detail(c, p, [(orient(Polygon(w_["rect"]), 1.0), max(2.5, min(w_["eave"], w_["h"] - 0.6)) if not (Polygon(w_["rect"]).area > 0.35 * sum(Polygon(x["rect"]).area for x in hw) and w_["eave"] < e.get("_hw_eave", 0) and w_["h"] > e.get("_hw_eave", 0) + 1.2) else e["_hw_eave"], w_["h"], w_["shape"]) for w_ in hw], rnd, want_porch, mat, e.get("_addr"), e.get("_look"))
            elif want_porch:
                porch(c, p, (rnd * 7.31) % 1.0)
            continue
        wings = []
        pitched = kind in ("gable", "gable_cross", "hip") and rect_frame(p) is not None and (p.area < 700 or e.get("tags", {}).get("roof:shape"))
        if not pitched and kind in ("gable", "gable_cross", "hip") and p.area < 700 and cls in ("house", "garage", "yes", "detached", "residential", "semidetached_house"):
            wings = rect_parts(p)        # L / T shaped house: one pitched roof per wing
            pitched = bool(wings)
        if pitched:
            wall_top = eave if (eave and eave > 2.2) else (h if roof is None else h - 2.2)
            ridge = max(0.8, min(7.0, h - wall_top)) if (h - wall_top) > 0.8 else (2.2 if cls == "house" else 1.2)
        else:
            wall_top = h
        z = b0
        if lm and lm.get("base"):
            walls(c, p, z, lm["base"][1], lm["base"][0]); z = lm["base"][1]
        elif store and wall_top > 6:
            walls(c, p, z, 4.2, "storefront"); z = 4.2
        if e.get("_base") and not store:
            bm_, bh_ = e["_base"]; bh_ = min(bh_, wall_top - 0.3)
            if bh_ > z + 0.3: walls(c, p, z, bh_, bm_); z = bh_
        walls(c, p, z, wall_top, mat)
        if wings:
            flat_poly(c, "roof", p, wall_top, 6.0, True)          # under-deck for any sliver the wings miss
            main = max(wings, key=lambda q: q.area); fr0 = rect_frame(main)
            slope = ridge / max(fr0[2] / 2, 1.0) if fr0 else 0.6
            for q in wings:
                fq = rect_frame(q)
                if fq is None: continue
                pitched_roof(c, q, wall_top, mat, max(0.6, min(7.0, slope * fq[2] / 2)), "gable" if kind == "gable_cross" else kind, roof_mat)
        elif not (pitched and pitched_roof(c, p, wall_top, mat, ridge, kind, roof_mat)):
            flat_poly(c, "roof", p, wall_top, 6.0, True)
        elif cls == "house" and ((rnd * 5.71) % 1.0) < 0.55 and ridge > 1.5:
            chimney(c, p, wall_top, ridge, (rnd * 9.13) % 1.0)
        if cls in ("house", "garage") and not lm:
            walls(c, p.buffer(0.08, join_style=2) if p.area > 20 else p, -0.3, 0.55, "foundation")   # exposed concrete foundation
        if mn > 0:
            for t3 in triangulate(p):
                pts = [to3(c, x, y, mn) for x, y in t3]
                tri(c, "concrete_dk", pts[0], pts[1], pts[2], (0, -1.0, 0), [(0, 0), (1, 0), (0, 1)])
        want_porch = cls == "house" and ((rnd * 3.17) % 1.0) < e.get("_porch", 0.78) and 45 < p.area < 300
        if e.get("_detail") and cls == "house":
            house_detail(c, p, [(p, wall_top, wall_top + (ridge if pitched else 0.0), kind if pitched else "flat")], rnd, want_porch, mat, e.get("_addr"), e.get("_look"))
        elif want_porch:
            porch(c, p, (rnd * 7.31) % 1.0)
        if lm and lm.get("colonnade"):
            colonnade(c, p, h)
    if g.area > 300 and h > 8 and rnd > 0.35 and cls not in ("house", "garage"):
        rp = g.representative_point()
        c.props.append(["hvac", rp.x - c.ox, -(rp.y - c.oy), h, rnd])

stadium_jobs = defaultdict(list)
_pitches = []
for e in els:
    t = tags(e)
    if e["type"] != "node" and t.get("leisure") == "pitch":
        gg = area_geom(e)
        if gg is not None: _pitches.append(gg)
for e in els:
    t = tags(e)
    if e["type"] != "node" and t.get("leisure") == "stadium":
        sg = area_geom(e)
        if sg is None or sg.area < 3000: continue
        inside = [pp for pp in _pitches if sg.contains(pp.representative_point())]
        if not inside: continue
        pitch = max(inside, key=lambda a: a.area)
        cp_ = sg.representative_point()
        stadium_jobs[rkey(cp_.x, cp_.y)].append((sg, pitch, t.get("name", "")))
log("stadiums", sum(len(v) for v in stadium_jobs.values()))

# ---------------------------------------------------------------- sports courts, ball fields, playgrounds (OSM leisure=*)
park_jobs = defaultdict(list)
for e in els:
    t = tags(e); le = t.get("leisure")
    if le not in ("pitch", "playground"): continue
    if e["type"] == "node":
        if le == "playground" and "lat" in e:
            x, y = P(e["lat"], e["lon"]); park_jobs[rkey(x, y)].append(("play", Point(x, y).buffer(9), "", ""))
        continue
    gg = area_geom(e)
    if gg is None or gg.area < 40 or gg.area > 60000: continue
    cp_ = gg.representative_point()
    park_jobs[rkey(cp_.x, cp_.y)].append(("pitch" if le == "pitch" else "play", gg, t.get("sport", ""), t.get("surface", "")))
log("park features", sum(len(v) for v in park_jobs.values()))

def _yaw(fx, fy): return math.atan2(-fx, fy)          # model front (+Y blender / -Z godot) -> plan direction

def _model(name, x, y, fx, fy):
    if rkey(x, y) != CUR_REGION: return        # never touch a neighbour region's (already written) chunks
    c = chunk_at(x, y); c.props.append(["m:" + name, round(x - c.ox, 2), round(-(y - c.oy), 2), 0.0, round(_yaw(fx, fy), 3)])

def _frame(g):
    fr = rect_frame(g) or (lambda r: (list(r.exterior.coords)[:4], 0, 0, r))(g.minimum_rotated_rectangle)
    cs = fr[0]
    if math.dist(cs[0], cs[1]) < math.dist(cs[1], cs[2]): cs = cs[1:] + cs[:1]
    L, S_ = math.dist(cs[0], cs[1]), math.dist(cs[1], cs[2])
    u = ((cs[1][0] - cs[0][0]) / L, (cs[1][1] - cs[0][1]) / L); v = ((cs[2][0] - cs[1][0]) / S_, (cs[2][1] - cs[1][1]) / S_)
    c0 = g.minimum_rotated_rectangle.centroid
    return (c0.x, c0.y), u, v, L, S_

def _rect(cx, cy, u, v, hl, hs):
    return Polygon([(cx + u[0] * a * hl + v[0] * b * hs, cy + u[1] * a * hl + v[1] * b * hs) for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))])

def _line(a, b, w=0.08): return LineString([a, b]).buffer(w / 2, cap_style="flat")

def _aa(g, *args):
    if g is None or g.is_empty: return
    g = g.intersection(box(CUR_REGION[0] * REGION, CUR_REGION[1] * REGION, (CUR_REGION[0] + 1) * REGION, (CUR_REGION[1] + 1) * REGION))
    if not g.is_empty: add_area(g, *args)

def park_feature(kind, g, sport, surface):
    (cx, cy), u, v, L, S_ = _frame(g)
    P2 = lambda a, b: (cx + u[0] * a + v[0] * b, cy + u[1] * a + v[1] * b)
    lines = []
    if kind == "play":
        if g.area < 60: return
        _aa(g, "mulch", 0.03, 3.0)
        n = 2 if g.area > 700 else 1
        for k in range(n):
            x, y = P2((k - (n - 1) / 2) * min(L / 2, 9), 0)
            _model("park_playground", x, y, v[0], v[1])
        return
    hard = sport in ("tennis", "basketball", "pickleball", "volleyball", "multi", "netball") and surface not in ("grass", "sand", "clay")
    if sport in ("tennis", "pickleball") and hard:
        _aa(g, "court_green", 0.03, 4.0)
        cl, cw = (23.77, 10.97) if sport == "tennis" else (13.41, 6.1)
        n = max(1, min(6, int(round(S_ / (cw + 7.0)))))
        if L < cl * 0.8: cl, cw = L * 0.85, min(cw, S_ * 0.7); n = 1
        for k in range(n):
            ob = (k - (n - 1) / 2) * (S_ / n)
            ccx, ccy = P2(0, ob)
            inner = _rect(ccx, ccy, u, v, cl / 2, cw / 2)
            _aa(_rect(ccx, ccy, u, v, cl / 2 + 3.5, cw / 2 + 2.0).intersection(g), "court_blue", 0.035, 4.0)
            lines.append(inner.exterior.buffer(0.04))
            lines.append(_line(P2(0, ob - cw / 2), P2(0, ob + cw / 2)))
            if sport == "tennis":
                for sgn in (-1, 1):
                    lines.append(_line(P2(sgn * 6.4, ob - cw / 2 + 1.37), P2(sgn * 6.4, ob + cw / 2 - 1.37)))
                lines.append(_line(P2(-6.4, ob), P2(6.4, ob)))
                for sgn in (-1, 1): lines.append(_line(P2(-cl / 2, ob + sgn * (cw / 2 - 1.37)), P2(cl / 2, ob + sgn * (cw / 2 - 1.37))))
            x, y = P2(0, ob); _model("park_tennis_net", x, y, u[0], u[1])
    elif sport == "basketball" or (hard and sport in ("multi", "netball")):
        _aa(g, "court_red" if surface in ("acrylic",) else "asphalt", 0.03, 4.0)
        cl, cw = min(28.0, L - 1.0), min(15.0, S_ - 1.0)
        if cl < 8 or cw < 5: return
        lines.append(_rect(cx, cy, u, v, cl / 2, cw / 2).exterior.buffer(0.04))
        lines.append(_line(P2(0, -cw / 2), P2(0, cw / 2)))
        lines.append(Point(cx, cy).buffer(1.8).exterior.buffer(0.04))
        for sgn in (-1, 1):
            lines.append(Point(P2(sgn * (cl / 2 - 1.6), 0)).buffer(6.75).exterior.buffer(0.04).intersection(_rect(*P2(sgn * (cl / 2 - 3.4), 0), u, v, 3.4, cw / 2)))
            lines.append(_rect(*P2(sgn * (cl / 2 - 2.9), 0), u, v, 2.9, 2.45).exterior.buffer(0.04))
            x, y = P2(sgn * (cl / 2 - 0.2), 0); _model("park_hoop", x, y, -sgn * u[0], -sgn * u[1])
    elif sport in ("soccer", "american_football", "rugby", "lacrosse", "field_hockey"):
        lines.append(_rect(cx, cy, u, v, L / 2 - 1.0, S_ / 2 - 1.0).exterior.buffer(0.06))
        if sport == "american_football":
            for k in range(-5, 6): lines.append(_line(P2(k * 9.144, -S_ / 2 + 1), P2(k * 9.144, S_ / 2 - 1), 0.1))
            for sgn in (-1, 1): x, y = P2(sgn * (L / 2 - 0.5), 0); _model("park_goalpost", x, y, -sgn * u[0], -sgn * u[1])
        else:
            lines.append(_line(P2(0, -S_ / 2 + 1), P2(0, S_ / 2 - 1), 0.1))
            lines.append(Point(cx, cy).buffer(min(9.15, S_ / 5)).exterior.buffer(0.06))
            for sgn in (-1, 1):
                pa = min(16.5, L / 6); pw = min(40.3, S_ * 0.6)
                lines.append(_rect(*P2(sgn * (L / 2 - 1 - pa / 2), 0), u, v, pa / 2, pw / 2).exterior.buffer(0.06))
                if L > 40: x, y = P2(sgn * (L / 2 - 1.0), 0); _model("park_goal", x, y, -sgn * u[0], -sgn * u[1])
    elif sport in ("baseball", "softball"):
        # home plate = the polygon corner closest to a right angle with long straight sides (the foul lines)
        q = g.simplify(1.5); cs = list(q.exterior.coords)[:-1]; best = None
        for i in range(len(cs)):
            a, b, c3 = cs[i - 1], cs[i], cs[(i + 1) % len(cs)]
            l1, l2 = math.dist(a, b), math.dist(b, c3)
            if min(l1, l2) < 15: continue
            ang = math.degrees(math.acos(max(-1, min(1, ((a[0] - b[0]) * (c3[0] - b[0]) + (a[1] - b[1]) * (c3[1] - b[1])) / (l1 * l2)))))
            sc = abs(ang - 90) - min(l1, l2) * 0.05
            if best is None or sc < best[0]: best = (sc, b, a, c3)
        if best is None or best[0] > 25: return
        _, hp, a, c3 = best
        d1 = ((a[0] - hp[0]) / math.dist(a, hp), (a[1] - hp[1]) / math.dist(a, hp)); d2 = ((c3[0] - hp[0]) / math.dist(c3, hp), (c3[1] - hp[1]) / math.dist(c3, hp))
        bis = (d1[0] + d2[0], d1[1] + d2[1]); bl = math.hypot(*bis) or 1; bis = (bis[0] / bl, bis[1] / bl)
        bs = 27.43 if sport == "baseball" else 18.29; rr = 29.0 if sport == "baseball" else 20.0
        sector = Polygon([hp] + [(hp[0] + rr * math.cos(t_), hp[1] + rr * math.sin(t_)) for t_ in
                  [math.atan2(d1[1], d1[0]) + (math.atan2(d2[1], d2[0]) - math.atan2(d1[1], d1[0])) * k / 12 for k in range(13)]])
        if sector.is_valid: _aa(sector.intersection(g), "infield", 0.03, 3.0)
        diamond = Polygon([hp, (hp[0] + d1[0] * bs, hp[1] + d1[1] * bs), (hp[0] + (d1[0] + d2[0]) * bs, hp[1] + (d1[1] + d2[1]) * bs), (hp[0] + d2[0] * bs, hp[1] + d2[1] * bs)])
        if diamond.is_valid: _aa(diamond.buffer(-1.4, join_style=2), "grass", 0.035, 8.0)
        for d_ in (d1, d2): lines.append(_line(hp, (hp[0] + d_[0] * min(90, rr * 3), hp[1] + d_[1] * min(90, rr * 3)), 0.1).intersection(g))
        _model("park_backstop", hp[0] - bis[0] * 1.0, hp[1] - bis[1] * 1.0, -bis[0], -bis[1])
    else:
        return
    ln = unary_union([l for l in lines if l is not None and not l.is_empty])
    if not ln.is_empty: _aa(ln, "paint_line", 0.045, 2.0)

def build_stadium(sg, pitch):
    cp_ = sg.representative_point(); c = chunk_at(cp_.x, cp_.y)
    for k in range(16):
        inner = pitch.buffer(5 + k * 2.6); outer = pitch.buffer(5 + (k + 1) * 2.6)
        ring = safe(lambda a, b: a.difference(b), outer, inner).intersection(sg)
        if ring.is_empty or ring.area < 5: break
        z = 1.2 + k * 1.05
        for pg in polys_of(ring):
            pg = orient(pg, 1.0)
            walls(c, pg, 0.0, z, "concrete_dk"); flat_poly(c, "seats", pg, z, 2.0, True)
    ring_ = sg.exterior
    for k in range(6):
        pt = ring_.interpolate(k / 6, normalized=True)
        cbox(c, pt.x, pt.y, (1.0, 0.0), (0.0, 1.0), 0.5, 0.5, 0.0, 34.0, "concrete_dk", True)
        cbox(c, pt.x, pt.y, (1.0, 0.0), (0.0, 1.0), 2.4, 0.9, 34.0, 36.5, "glass_lit")

bjobs = defaultdict(list)
PART_PARENT = {}

# ---------------------------------------------------------------- themed bars (enterable)
BAR_MAT = {"Shot Clock": "bar_shooters", "The Salty Hull": "bar_anchor", "Cardboard Club": "bar_cardboard", "Easy Pour": "bar_easypour",
           "Velvet Mile": "bar_velvet", "Erie Tiki": "bar_lakefront", "Neon Coyote": "bar_coyote", "Alligator Club": "bar_gator",
           "Two Buck Tavern": "dive_twobuck", "Dollar Draft": "dive_dollar", "Corner Tap": "dive_cornertap", "Happy Hour Hut": "dive_happyhour",
           "Tipsy Tom's": "dive_tipsytom", "BAR": "dive_bar", "Last Call": "dive_lastcall"}
BAR_BLDG = {}          # building key -> theme
BARS_PATH = os.environ.get("BARS", os.path.join(os.path.dirname(os.path.abspath(SRC.rstrip("/"))), "bars.json"))
_bars = json.load(open(BARS_PATH)) if os.path.exists(BARS_PATH) else []
_btree = STRtree([g for _, g in buildings]) if buildings else None
_synth = 0
for b in _bars:
    pt = Point(b["x"], b["y"])
    if not BBOX_P.contains(pt): continue
    k = _btree.nearest(pt) if _btree is not None else None
    if k is not None and buildings[k][1].distance(pt) < 30 and buildings[k][1].area < 6000:
        e_, g_ = buildings[k]
        BAR_BLDG[f"{e_['type'][0]}{e_['id']}"] = b["theme"]
    else:   # no mapped building: put a modest one-storey bar where the business is
        _synth += 1
        fake = {"type": "way", "id": 9_000_000_000 + _synth, "tags": {"building": "commercial", "height": "5.5"}}
        g_ = box(b["x"] - 8, b["y"] - 6, b["x"] + 8, b["y"] + 6)
        buildings.append((fake, g_))
        BAR_BLDG[f"w{fake['id']}"] = b["theme"]
log("bars mapped", len(BAR_BLDG), "synthesized", _synth)

def bar_door(c, p, theme, h):
    """Front door on the wall facing the nearest street; records it for the game (enter/exit + exterior props)."""
    cs = list(orient(p, 1.0).exterior.coords)
    road = street_lines[STREET_TREE.nearest(p.centroid)] if STREET_TREE is not None else None
    best = None
    for (x0, y0), (x1, y1) in zip(cs, cs[1:]):
        L = math.hypot(x1 - x0, y1 - y0)
        if L < 3: continue
        nx, ny = (y1 - y0) / L, -(x1 - x0) / L
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        score = L * 0.01
        if road is not None:
            rp = road.interpolate(road.project(Point(mx, my)))
            dx, dy = rp.x - mx, rp.y - my; dl = math.hypot(dx, dy) or 1
            score += (nx * dx + ny * dy) / dl - dl * 0.01
        if best is None or score > best[0]: best = (score, mx, my, nx, ny, L)
    if best is None: return
    _, mx, my, nx, ny, L = best
    dx_, dy_ = mx + nx * 0.25, my + ny * 0.25
    yaw = math.atan2(-nx, ny)   # Godot yaw so that local -Z points out of the building
    c.bars.append([theme, dx_ - c.ox, -(dy_ - c.oy), float(yaw), float(min(h, 12.0)), float(L), float(G(dx_, dy_))])
# ---------------------------------------------------------------- yards: lawns, driveways, front walks, shrubs
def _is_small_res(e, g):
    t = e.get("tags", {})
    if t.get("shop") or t.get("amenity") or t.get("building") in ("commercial", "retail", "industrial", "warehouse", "office", "church", "school"): return False
    return 25 < g.area < 420
_SMALL = [g for e, g in buildings if _is_small_res(e, g) and f"w{e.get('id')}" not in VACANT]
_BIG = [g for e, g in buildings if g.area > 1200]
HOUSE_TREE = STRtree(_SMALL) if _SMALL else None
BIG_TREE = STRtree(_BIG) if _BIG else None
log("yard houses", len(_SMALL))

def green_of(rb):
    """vegetated ground in the aerial photo (excess-green index on a 2 m grid) as polygons: real lawns, school
    grounds, vacant lots, field edges - so leftover ground is grass where it is grass and paved where it is paved."""
    AERIAL_DIR = os.environ.get("AERIAL", os.path.join(_REPO, "data/aerial"))
    x0, y0, x1, y1 = rb.bounds
    W, H = int(math.ceil((x1 - x0) / 2)), int(math.ceil((y1 - y0) / 2))
    img = np.zeros((H, W, 3), np.float32); have = np.zeros((H, W), bool)
    for cx in range(math.floor(x0 / 200), math.floor((x1 - 1e-6) / 200) + 1):
        for cy in range(math.floor(y0 / 200), math.floor((y1 - 1e-6) / 200) + 1):
            f = os.path.join(AERIAL_DIR, f"{cx}_{cy}.jpg")
            if not os.path.exists(f): continue
            t = cv2.imread(f)
            if t is None: continue
            t = cv2.resize(t, (100, 100), interpolation=cv2.INTER_AREA).astype(np.float32)
            c0 = int(round((cx * 200 - x0) / 2)); r0 = int(round((y1 - (cy + 1) * 200) / 2))
            a0, b0 = max(0, r0), max(0, c0); a1, b1 = min(H, r0 + 100), min(W, c0 + 100)
            if a1 <= a0 or b1 <= b0: continue
            img[a0:a1, b0:b1] = t[a0 - r0:a1 - r0, b0 - c0:b1 - c0]; have[a0:a1, b0:b1] = True
    if not have.any(): return Polygon()
    b, g, r = img[..., 0], img[..., 1], img[..., 2]
    exg = (2 * g - r - b) / np.maximum(r + g + b, 1)
    br = (r + g + b) / 3; yel = (r + g) / 2 - b            # leaf-off imagery: dormant grass is dull, dark and yellowish
    m = ((((exg > 0.06) & (g > 45)) | ((yel > 11) & (br < 108) & (br > 40))) & have).astype(np.uint8) * 255
    m = (cv2.medianBlur(m, 3) > 0).astype(np.uint8)
    cs, hier = cv2.findContours(m, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    polys = []
    for ci, cn in enumerate(cs):
        if hier[0][ci][3] != -1 or cv2.contourArea(cn) < 6: continue
        pts = [(x0 + (p[0][0] + 0.5) * 2, y1 - (p[0][1] + 0.5) * 2) for p in cn]
        if len(pts) < 3: continue
        holes = [[(x0 + (p[0][0] + 0.5) * 2, y1 - (p[0][1] + 0.5) * 2) for p in cs[hj]] for hj in range(len(cs))
                 if hier[0][hj][3] == ci and len(cs[hj]) >= 3 and cv2.contourArea(cs[hj]) >= 6]
        pg = Polygon(pts, holes).buffer(0)
        if not pg.is_empty: polys.append(pg)
    return unary_union(polys).simplify(1.0) if polys else Polygon()

def yards(Rg, rb, generic, roads_r, side_r, rng_):
    lot, lawn, extra = yards_0(Rg, rb, generic, roads_r, side_r, rng_)
    if lot is not None and not lot.is_empty:
        gr = green_of(rb)
        if not gr.is_empty:
            gl = safe(lambda a, b: a.intersection(b), lot, gr)
            if not gl.is_empty:
                lot = safe(lambda a, b: a.difference(b), lot, gl)
                lawn = gl if lawn is None or lawn.is_empty else unary_union([lawn, gl])
    return lot, lawn, extra

def yards_0(Rg, rb, generic, roads_r, side_r, rng_):
    """split the leftover ground into lawns (around houses) and paved lots; add driveways, walks and shrubs."""
    if HOUSE_TREE is None or generic.is_empty: return generic, Polygon(), []
    hs = [_SMALL[i] for i in HOUSE_TREE.query(rb)]
    if not hs: return generic, Polygon(), []
    zone = unary_union([h.buffer(22, quad_segs=2) for h in hs])
    if BIG_TREE is not None:
        bg = [_BIG[i] for i in BIG_TREE.query(rb)]
        if bg: zone = safe(lambda a, b: a.difference(b), zone, unary_union([b.buffer(10, join_style=2) for b in bg]))
    lawn = safe(lambda a, b: a.intersection(b), generic, zone)
    lot = safe(lambda a, b: a.difference(b), generic, zone)
    paved, shrubs = [], []
    rp = shapely.prepared.prep(Rg)
    hard_ = unary_union([roads_r, side_r])
    for h in hs:
        if h.geom_type != "Polygon":
            h = max(polys_of(h), key=lambda a: a.area) if not h.is_empty else None
            if h is None: continue
        c_ = h.centroid
        if not rp.contains(c_) or STREET_TREE is None: continue
        road = street_lines[STREET_TREE.nearest(c_)]
        q = road.interpolate(road.project(c_))
        d = c_.distance(q)
        if d < 4 or d > 45: continue
        ux, uy = (q.x - c_.x) / d, (q.y - c_.y) / d
        if h.area < 75:          # detached garage: a driveway from its door to the street
            paved.append(LineString([(c_.x, c_.y), (q.x, q.y)]).buffer(1.5, cap_style="flat"))
            continue
        # front walk: from the wall facing the street to the sidewalk
        edge = h.exterior.interpolate(h.exterior.project(Point(c_.x + ux * 60, c_.y + uy * 60)))
        # foundation shrubs along the front wall
        vx, vy = -uy, ux
        for k in range(-2, 3):
            if rng_.random() < 0.35: continue
            sx, sy = edge.x + ux * 1.1 + vx * (k * 2.2 + rng_.uniform(-0.4, 0.4)), edge.y + uy * 1.1 + vy * (k * 2.2)
            if abs(k) == 0: continue                      # keep the walk clear
            shrubs.append((sx, sy, rng_.uniform(0.9, 1.6)))
    pv = safe(lambda a, b: a.difference(b), unary_union(paved), hard_) if paved else Polygon()
    pv = safe(lambda a, b: a.intersection(b), pv, Rg) if not pv.is_empty else pv
    return lot, lawn, [pv, shrubs]

_coast_dropped = 0
for e, g in buildings:
    cp = g.representative_point()
    if not BBOX_P.contains(cp): continue
    if INLAND_P is not None and not INLAND_P.contains(g):   # anything touching the beach or the lake is removed
        _coast_dropped += 1; continue
    key_ = f"{e['type'][0]}{e['id']}"
    if part_tree is not None:
        hits = [k for k in part_tree.query(g) if g.contains(parts[k][1].representative_point())]
        if hits:
            for k in hits:
                if key_ in LANDMARKS: PART_PARENT[k] = key_
            covered = sum(parts[k][1].area for k in hits)
            if covered > 0.6 * g.area and key_ not in LANDMARKS: continue
    bjobs[rkey(cp.x, cp.y)].append((e, g, cp, False))
# LiDAR-exact massing replaces OSM building:parts entirely (orphaned parts would float or double up)
_ex = [g for e, g in buildings if (LID.get(f"{e['type'][0]}{e['id']}") or {}).get("exact")]
_ex_tree = STRtree(_ex) if _ex else None
for k_, (e, g) in enumerate(parts):
    cp = g.representative_point()
    if _ex_tree is not None and any(_ex[i].contains(cp) for i in _ex_tree.query(cp)): continue
    if INLAND_P is not None and not INLAND_P.contains(g): continue
    if BBOX_P.contains(cp): bjobs[rkey(cp.x, cp.y)].append((e, g, cp, ("part", k_)))

labels_done = set()
# ---- hand-made replicas (tools/blender/replica.py): their generic geometry is left out, the game places the model
_REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
REPLICAS = {}
for _mf in glob.glob(os.path.join(_REPO, "tools/blender/replicas/*/massing.json")):
    _md = json.load(open(_mf))
    if not os.path.exists(os.path.join(_REPO, "assets/models/bld_%s.glb" % _md["key"])): continue
    _ax, _ay = _md["anchor"][0], -_md["anchor"][1]
    _polys = [Polygon([(x + _ax, y + _ay) for x, y in pp]) for pp in _md["tiers"][0]["polys"] if len(pp) >= 3]
    REPLICAS[_md["key"]] = {"anchor": _md["anchor"], "foot": unary_union(_polys).buffer(1.5)}
log("replicas", len(REPLICAS))
REPLICA_PLACED = []

def do_building(e, g, cp, is_part):
    if VACANT and f"w{e.get('id')}" in VACANT: return       # demolished since the survey (county: vacant lot)
    """every building is level: its geometry and props sit on the lowest ground point of its footprint."""
    ZBASE[0] = foot_base(g)
    try: return _do_building(e, g, cp, is_part)
    finally: ZBASE[0] = None

def _do_building(e, g, cp, is_part):
    t = tags(e)
    _k = f"{e['type'][0]}{e['id']}"
    if _k in REPLICAS: return
    if REPLICAS and any(r["foot"].contains(cp) for r in REPLICAS.values()): return     # parts inside a replica
    rnd = int(hashlib.md5(str(e["id"]).encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    part_lm = LANDMARKS.get(PART_PARENT.get(is_part[1])) if isinstance(is_part, tuple) else None
    kind = "yes" if is_part else t.get("building", "yes")
    cls = classify(kind, g.area)
    owe = in_owe(cp.x, cp.y)
    h, mn = h_of(t, rnd, cls, math.hypot(cp.x, cp.y), owe)
    key = f"{e['type'][0]}{e['id']}"
    lm = LANDMARKS.get(key)
    if lm is None and not is_part:
        for (la, lo), d_ in POINT_LANDMARKS:
            px, py = P(la, lo)
            if g.buffer(8).contains(Point(px, py)) and g.area > 600: lm = d_; break
    m = LID.get(key)
    roof = eave = tiers = None
    has_tag_h = t.get("height") or t.get("building:levels")
    if m and "h" in m and m.get("n", 0) >= 6:
        mh = m["h"]
        # trust LiDAR unless the building is newer than the 2016 scan (no/low returns) or tags say much taller
        if not (has_tag_h and h > mh * 1.6):
            if not is_part or mn <= 0: h = max(2.6, mh)
            roof = m.get("roof")
            if roof == "complex": roof = None
            eave = m.get("eave")
            tiers = m.get("tiers") if not is_part else None
            cls = "house" if (cls == "yes" and roof in ("gable", "hip", "gable_cross") and g.area < 300) else cls
    if m and m.get("demolished"): return
    exact = bool(m and m.get("exact"))
    if exact:
        h = m["h"]; tiers = m["tiers"]; roof = None
    elif lm:
        h = lm.get("h", h); tiers = None
    osm_roof = {"gabled": "gable", "hipped": "hip", "dome": "dome", "pyramidal": "hip", "flat": "flat"}.get(t.get("roof:shape", ""))
    if osm_roof: roof = osm_roof
    mat = lm["mat"] if lm else (part_lm["mat"] if part_lm else style_of(t, cls, h, cp.x, cp.y, rnd, owe))
    roof_mat = {"green": "copper_green", "silver": "cable", "black": "roof", "red": "shingle_red"}.get(t.get("roof:colour", ""), "shingle")
    dcore = math.hypot(cp.x, cp.y)
    store = (not lm) and cls not in ("house", "garage") and roof in (None, "flat") and (h < 60 or dcore < 1600) and \
            (cls in ("commercial", "retail") or (cls in ("yes", "office", "apartments", "hotel") and dcore < 1800 and g.area > 120))
    if lm or tiers or roof in (None, "flat"):
        roof = None if (lm and not osm_roof) else roof
    ct = t if "c:luc" in t or "c:ctype" in t else ATTACH.get(key)
    if ct and not lm and not part_lm and not is_part:
        cmat, cls2, h2, store2 = county_style(ct, g, h, rnd, cls, store, m, e)
        if cmat:
            mat, cls, h, store = cmat, cls2, h2, store2
            if cls in ("house", "garage") and roof is None and not (m and m.get("roof") == "flat"):
                roof = "gable" if rnd < 0.62 else "hip"
    if cls == "house" and not lm and not is_part and key in HWINGS and not exact:
        hw_ = HWINGS[key]
        if all("h" in w_ and w_.get("n", 0) >= 6 for w_ in hw_):
            if e.get("_hcap"):
                cap_ = e["_hcap"]
                hw_ = [dict(w_, h=min(w_["h"], cap_), eave=min(w_["eave"], cap_ - 2.2)) for w_ in hw_]
            e["_hw"] = hw_
            st_ = _f(ct or {}, "c:stories", 0)
            # county story count -> least believable eave for the main body (LiDAR's low percentile catches porch roofs)
            e["_hw_eave"] = {1: 2.7, 1.3: 2.9, 1.5: 3.4, 2: 5.5, 2.5: 5.8, 3: 8.3}.get(st_, 0.0) if st_ else 0.0
    bl = BLOOKS.get(key) if cls not in ("house", "garage") and not lm and not exact and not is_part else None
    if bl and (mat.startswith("brick") or mat == "h_stone") and cls in ("retail", "commercial", "church") and bl["cls"] in ("light", "grey"):
        bl = None    # old brick shop blocks: a "light" photo reading is shop glass, white trim or sky, not the wall
    if bl and not mat.startswith(("h_", "hsid", "hbrk")):
        wc = bl["cls"]
        if wc == "brick": mat = mat if mat.startswith("brick") else "brick_red"
        elif wc == "buff": mat = "brick_tan"
        elif wc in ("light", "grey", "paint"): mat = "metal" if cls == "industrial" and wc != "paint" else "concrete"
        mat = mat + "~" + bl["wall"][1:]
    hl = HLOOKS.get(key) if cls in ("house", "garage") and not lm else None
    if hl:
        if hl["w"] >= 0 and mat.startswith("h_clap_"): mat = mat.split("#")[0] + "@%d" % hl["w"]
        elif hl["w"] >= 0 and mat.startswith("h_lap#"): mat = "h_lap@%d" % hl["w"]
        if hl["t"] >= 0: TRIM_MAT[0] = "trim@%d" % hl["t"]
        if hl["p"] >= 0 and cls == "house": e["_porch"] = float(hl["p"])
        e["_look"] = hl
        rf = {"H": "hip", "G": "gable", "S": "gable"}.get((hl.get("lab") or "xxxx")[3])
        if rf and e.get("_hw"):            # the photo shows the roof type: trust it over a noisy LiDAR fit
            tot_ = sum(Polygon(w_["rect"]).area for w_ in e["_hw"])
            e["_hw"] = [dict(w_, shape=rf) if Polygon(w_["rect"]).area > 0.35 * tot_ and w_.get("shape") != "flat" else w_ for w_ in e["_hw"]]
    if cls in ("house", "garage") and not lm and not exact:
        if mat.startswith(("h_clap_", "h_lap")):
            if "@" in mat: mat = "hsid@" + mat.split("@")[1]
            else:
                era_, i_ = (mat[7:].split("#") if mat.startswith("h_clap_") else (mat[6:-1], mat[-1]))
                mat = f"hsid#{era_}{i_}"
            e["_detail"] = cls == "house"
        elif mat.startswith("h_brick_"):
            mat = "hbrk_" + mat[8:]; e["_detail"] = cls == "house"
        elif mat in ("h_stucco", "h_stone", "h_block"):
            mat = {"h_stucco": "hstu", "h_stone": "hstn", "h_block": "hblk"}[mat]; e["_detail"] = cls == "house"
        e["_addr"] = (ct or {}).get("c:addr")
    bar_theme = BAR_BLDG.get(key)
    if bar_theme and h <= 15.0:      # the themed bar front only on low buildings; a tower keeps its own walls (door + sign still go on)
        mat = BAR_MAT[bar_theme]; store = False; roof = None; tiers = None
    if exact:
        e["_exact"] = True
        sp = default_facade(mat, ct or t, h, cls, store, rnd)
        sp.update(FACADES.get(key, {}))
        e["_fspec"] = sp
    emit_building(e, g, h, mn, mat, rnd, cls, cp, roof=roof, eave=eave, tiers=tiers, lm=lm, store=store, roof_mat=roof_mat)
    TRIM_MAT[0] = "trim_white"
    if bar_theme:
        c_ = chunk_at(cp.x, cp.y)
        p_ = max(polys_of(g), key=lambda a: a.area)
        bar_door(c_, p_, bar_theme, h)
    nm = (t.get("name") or "").strip()
    if nm and not is_part:
        low = nm.lower().replace("-", " "); shown = None
        for k, v in PARODY.items():
            if k in low: shown = v; break
        big = g.area > 1500 or h > 25
        if shown is None and big and any(k in low for k in GOV_OK) and not any(b in low for b in BRANDY) and not t.get("brand") and not t.get("shop"):
            shown = nm
        # schools and colleges: owner-chosen fictional names (source_data/school_names.json); "_closed" = no label
        if nm in SCHOOLS: shown = SCHOOLS[nm] if SCHOOLS[nm] != "_closed" else None
        elif shown:
            for k, v in SCHOOLS.get("_replace", {}).items(): shown = shown.replace(k, v)
            if shown == nm and any(w in low for w in ("school", "academy", "college", "university")):
                shown = None   # a school nobody has named yet: hide its real name until it gets one
        if shown and shown not in labels_done and g.area > 400:
            labels_done.add(shown)
            c = chunk_at(cp.x, cp.y)
            c.labels.append([shown, cp.x - c.ox, -(cp.y - c.oy), h + 3.0 + foot_base(g) if DEM_DIR else h + 3.0])

# ---------------------------------------------------------------- spawn
def find_spawn():
    by_name = defaultdict(list)
    for rk, jobs in seg_jobs.items():
        for j in jobs:
            if j[0] == "st" and j[1] in [STREET_MAP.get(x, x) for x in ("North Summit Street", "Summit Street", "Madison Avenue")]:
                by_name[j[1]].append(LineString([(j[2], j[3]), (j[4], j[5])]))
    for n1, n2 in ((STREET_MAP.get(a, a), STREET_MAP.get(b, b)) for a, b in (("North Summit Street", "Madison Avenue"), ("Summit Street", "Madison Avenue"))):
        if by_name[n1] and by_name[n2]:
            i = unary_union(by_name[n1]).intersection(unary_union(by_name[n2]))
            if not i.is_empty:
                p = i.representative_point()
                return (p.x, p.y, n1, n2)
    return (0.0, 0.0, "", "")
sx, sy, s1, s2 = find_spawn()
log("spawn", round(sx), round(sy), s1, s2)

# ---------------------------------------------------------------- region loop
os.makedirs(os.path.join(OUTDIR, "chunks"), exist_ok=True)
manifest_chunks = []
written = set()
total_v = 0
MATV = defaultdict(int)
def flush_region():
    global total_v
    for (i, j), c in list(chunks.items()):
        if (i, j) in written: print("WARN chunk rewritten", i, j)
        written.add((i, j))
        layers = []
        for mat, (V, Nn, U) in c.layers.items():
            if V:
                layers.append({"mat": mat, "v": PV3(V), "n": PV3(Nn), "uv": PV2(U)})
                total_v += len(V); MATV[mat.split("@")[0].split("#")[0].split("~")[0]] += len(V)
        if c.fac[0]:
            V, Nn, U, U2, CO, C0 = c.fac
            layers.append({"mat": "facade", "v": PV3(V), "n": PV3(Nn), "uv": PV2(U), "uv2": PV2(U2), "color": PCOL(CO), "c0": PF32(C0)})
            total_v += len(V)
        d = {"x": i, "z": j, "ox": c.ox, "oz": -c.oy, "layers": layers, "col": PV3(c.col),
             "streets": c.streets, "labels": c.labels, "bars": c.bars, "roads": c.roads, "ix": c.ix,
             "props": [[p[0], float(p[1]), float(p[2]), float(p[3]), float(p[4])] for p in c.props]}
        raw = enc(d)
        with open(os.path.join(OUTDIR, "chunks", f"{i}_{j}.bin"), "wb") as f:
            f.write(b"TCZ1" + struct.pack("<I", len(raw)) + zlib.compress(raw, 6))
        manifest_chunks.append([i, j])
    chunks.clear()

rx0, ry0 = math.floor(bx0 / REGION), math.floor(by0 / REGION)
rx1, ry1 = math.floor(bx1 / REGION), math.floor(by1 / REGION)
nreg = (rx1 - rx0 + 1) * (ry1 - ry0 + 1); done = 0
for ri in range(rx0, rx1 + 1):
    for rj in range(ry0, ry1 + 1):
        Rb_ = box(ri * REGION, rj * REGION, (ri + 1) * REGION, (rj + 1) * REGION)
        Rg = Rb_.intersection(BBOX)
        CUR_REGION = (ri, rj)
        done += 1
        if Rg.is_empty or Rg.area < 1: continue
        rb = Rg.buffer(40)
        clip = lambda g: safe(lambda a, b: a.intersection(b), g, Rg)
        water_r = clip(local_union(T_WATER, rb))
        roads_r = safe(lambda a, b: a.difference(b), clip(local_union(T_ROAD, rb)), water_r)
        side_r = safe(lambda a, b: a.difference(b), clip(local_union(T_SIDE, rb)), unary_union([roads_r, water_r]))
        taken = unary_union([water_r, roads_r, side_r])
        beach_r = safe(lambda a, b: a.difference(b), clip(BEACH), taken) if not BEACH.is_empty else Polygon()
        taken = unary_union([taken, beach_r])
        park_r = safe(lambda a, b: a.difference(b), clip(local_union(T_PARK, rb)), taken)
        taken = unary_union([taken, park_r])
        forest_r = safe(lambda a, b: a.difference(b), clip(local_union(T_FOREST, rb)), taken)
        taken = unary_union([taken, forest_r])
        field_rs = []
        for tf in T_FIELDS:
            fr = safe(lambda a, b: a.difference(b), clip(local_union(tf, rb)), taken) if tf[1] is not None else Polygon()
            field_rs.append(fr); taken = unary_union([taken, fr])
        parking_r = safe(lambda a, b: a.difference(b), clip(local_union(T_PARKING, rb)), taken)
        taken = unary_union([taken, parking_r])
        ind_r = safe(lambda a, b: a.difference(b), clip(local_union(T_IND, rb)), taken)
        taken = unary_union([taken, ind_r])
        generic = safe(lambda a, b: a.difference(b), Rg, taken)
        add_area(beach_r, "sand", 0.0, 6.0, True, GROUND_COL_Y)
        lot_r, lawn_r, yard_extra = yards(Rg, rb, generic, roads_r, side_r, random.Random(ri * 7919 + rj))
        add_area(lot_r, "lot", 0.0, 8.0, True, GROUND_COL_Y)
        add_area(lawn_r, "lawn", 0.0, 8.0, True, GROUND_COL_Y)
        if yard_extra:
            add_area(yard_extra[0], "drive", 0.03, 3.0)
            for shx, shy, shh in yard_extra[1]:          # (not sx/sy: those hold the spawn point)
                if rkey(shx, shy) != (ri, rj): continue
                c = chunk_at(shx, shy); c.props.append(["tree", round(shx - c.ox, 2), round(-(shy - c.oy), 2), 0.0, round(shh / 8.0, 2), round(shh * 0.9 / 6.0, 2)])
        add_area(park_r, "grass", 0.0, 8.0, True, GROUND_COL_Y)
        add_area(forest_r, "forest_floor", 0.0, 8.0, True, GROUND_COL_Y)
        for fi, fr in enumerate(field_rs): add_area(fr, "field%d" % fi, 0.0, 12.0, True, GROUND_COL_Y)
        add_area(ind_r, "industrial", 0.01, 8.0, True, GROUND_COL_Y)
        add_area(parking_r, "parking", 0.02, 6.0, True, GROUND_COL_Y)
        add_area(side_r, "sidewalk", 0.05, 3.0, True, GROUND_COL_Y)
        add_area(roads_r, "asphalt", 0.08, 6.0, True, GROUND_COL_Y)
        if not water_r.is_empty:
            ZBASE[0] = 0.0                                  # water surface and bed are absolute levels
            add_area(water_r, "water", WATER_Y, 20.0)
            add_area(water_r, "riverbed", BED_Y, 10.0, True)
            ZBASE[0] = None
            ring_walls(water_r, Rg.exterior, GROUND_COL_Y, BED_Y, "seawall")
        water_p = shapely.prepared.prep(water_r)
        hard = shapely.prepared.prep(unary_union([roads_r.buffer(0.5), water_r, side_r]))
        lamp_bad = shapely.prepared.prep(unary_union([roads_r.buffer(0.2), water_r]))   # lamps stand ON the sidewalk
        # real trees from LiDAR; the random scatter below only fills regions the LiDAR didn't cover
        lt = LTREES.get((ri, rj), [])
        for tx, ty, th, trd in lt:
            pt = Point(tx, ty)
            if not BBOX_P.contains(pt) or water_p.contains(pt): continue
            if hard.contains(pt):         # crown centre over a street/sidewalk: put the trunk just off it
                for dx, dy in ((2, 0), (-2, 0), (0, 2), (0, -2), (3, 3), (-3, -3), (3, -3), (-3, 3), (4, 0), (-4, 0), (0, 4), (0, -4)):
                    if not hard.contains(Point(tx + dx, ty + dy)) and rkey(tx + dx, ty + dy) == (ri, rj): tx += dx; ty += dy; break
                else: continue
            c = chunk_at(tx, ty)
            # [kind, x, z, y, height scale, crown scale]: billboards are ~8 m tall and ~6 m wide at scale 1
            c.props.append(["tree", round(tx - c.ox, 2), round(-(ty - c.oy), 2), 0.0, round(min(th, 26.0) / 8.0, 2), round(2.0 * min(trd, 0.45 * min(th, 26.0), 9.0) / 6.0, 2)])
        for g, dens in (() if lt else ((park_r, 220.0), (forest_r, 55.0))):
            for pg in polys_of(g):
                n = int(pg.area / dens); x0, y0, x1, y1 = pg.bounds; tries = 0
                pp = shapely.prepared.prep(pg)
                while n > 0 and tries < n * 5 + 10:
                    tries += 1
                    x, y = rng.uniform(x0, x1), rng.uniform(y0, y1)
                    if pp.contains(Point(x, y)):
                        c = chunk_at(x, y); c.props.append(["tree", x - c.ox, -(y - c.oy), 0.0, rng.uniform(0.7, 1.4)]); n -= 1
        for j in seg_jobs.get((ri, rj), []):
            k = j[0]
            if k == "cl": emit_centerline(j[1], j[2], j[3], j[4], water_p)
            elif k == "st":
                mx, my = (j[2] + j[4]) / 2, (j[3] + j[5]) / 2
                if BBOX_P.contains(Point(mx, my)):
                    c = chunk_at(mx, my)
                    c.streets.append([j[1], j[2] - c.ox, -(j[3] - c.oy), j[4] - c.ox, -(j[5] - c.oy)])
            elif k == "rd":
                mx, my = (j[3] + j[5]) / 2, (j[4] + j[6]) / 2
                if BBOX_P.contains(Point(mx, my)):
                    c = chunk_at(mx, my)
                    c.roads.append([j[1], j[2], float(j[3] - c.ox), float(-(j[4] - c.oy)), float(j[5] - c.ox), float(-(j[6] - c.oy)), j[7], j[8], j[9], float(j[10]), float(j[11]), j[12]])
            elif k == "ix":
                if BBOX_P.contains(Point(j[2], j[3])):
                    c = chunk_at(j[2], j[3])
                    c.ix.append([j[1], float(j[2] - c.ox), float(-(j[3] - c.oy)), j[4], j[5]])
            elif k == "lamp":
                pt = Point(j[1], j[2])
                if BBOX_P.contains(pt) and not lamp_bad.contains(pt):
                    c = chunk_at(j[1], j[2]); c.props.append(["lamp", j[1] - c.ox, -(j[2] - c.oy), 0.0, j[3]])
            elif k in ("upole", "uwire"):
                if ALLEY_TREE[0] is None: ALLEY_TREE[0] = shapely.STRtree(ALLEY_LINES) if ALLEY_LINES else False
                if k == "upole": pts_ = [(j[1], j[2])]
                else: pts_ = [(j[1], j[2]), (j[3], j[4])]
                if not all(BBOX_P.contains(Point(*q)) and not lamp_bad.contains(Point(*q)) for q in pts_): continue
                if j[-1] and ALLEY_TREE[0]:                  # street run: skip where an alley carries the lines
                    q = Point(*pts_[0])
                    if ALLEY_LINES[ALLEY_TREE[0].nearest(q)].distance(q) < 45: continue
                if k == "upole":
                    c = chunk_at(j[1], j[2]); c.props.append(["m:" + j[5], round(j[1] - c.ox, 2), round(-(j[2] - c.oy), 2), 0.0, round(_yaw(j[3], j[4]), 3)])
                else:
                    mx, my = (j[1] + j[3]) / 2, (j[2] + j[4]) / 2
                    c = chunk_at(mx, my); c.props.append(["wire", round(j[1] - c.ox, 2), round(-(j[2] - c.oy), 2), round(j[3] - c.ox, 2), round(-(j[4] - c.oy), 2)])
            elif k == "stree":
                if lt: continue                # LiDAR already has the real street trees here
                pt = Point(j[1], j[2])
                if BBOX_P.contains(pt) and not hard.contains(pt):
                    c = chunk_at(j[1], j[2]); c.props.append(["tree", j[1] - c.ox, -(j[2] - c.oy), 0.0, j[3]])
            elif k == "br":
                ZBASE[0] = 0.0; emit_bridge_seg(*j[1:]); ZBASE[0] = None
            elif k == "wt":
                _, mat_, a_, b_, c3_, n_, uv_, col_ = j
                ch = chunk_at((a_[0] + b_[0] + c3_[0]) / 3, (a_[1] + b_[1] + c3_[1]) / 3)
                tri(ch, mat_, to3(ch, *a_), to3(ch, *b_), to3(ch, *c3_), n_, uv_, col_)
        for pj in park_jobs.get((ri, rj), []):
            try: park_feature(*pj)
            except Exception as ex_: log("park feature skipped", ex_)
        for (sg, pitch, nm_) in stadium_jobs.get((ri, rj), []):
            try: build_stadium(sg, pitch)
            except Exception as ex: print("stadium fail", nm_, ex)
        for (e, g, cp, is_part) in bjobs.get((ri, rj), []):
            try: do_building(e, g, cp, is_part)
            except Exception as ex: print("bldg fail", e["id"], ex)
        if REGION_WALKS:      # front walks laid by house_detail, from each real door out to the street
            wk = safe(lambda a, b: a.difference(b), unary_union(REGION_WALKS), unary_union([roads_r, side_r, water_r]))
            wk = safe(lambda a, b: a.intersection(b), wk, Rg)
            if not wk.is_empty: add_area(wk, "drive", 0.035, 3.0)
            REGION_WALKS.clear()
        flush_region()
        if done % 20 == 0: log(f"region {done}/{nreg} chunks {len(manifest_chunks)} verts {total_v}")

manifest = {"chunk_size": CHUNK, "origin_lat": LAT0, "origin_lon": LON0, "chunks": manifest_chunks,
            "spawn": [sx, -sy], "spawn_desc": f"{s1} & {s2}", "bbox": [bx0, -by1, bx1, -by0],
            "water_y": WATER_Y, "ground_y": GROUND_COL_Y, "places": places}
json.dump(manifest, open(os.path.join(OUTDIR, "manifest.json"), "w"))
if os.environ.get("HPAL") and os.path.exists(os.environ["HPAL"]):     # paint palette the photo looks index into
    import shutil; shutil.copy(os.environ["HPAL"], os.path.join(OUTDIR, "house_palette.json"))
REPLICA_PLACED = [{"key": k, "anchor": r["anchor"], "y": round(foot_base(r["foot"].buffer(-1.5)) if DEM_DIR else 0.0, 2)} for k, r in sorted(REPLICAS.items())]
json.dump({"replicas": REPLICA_PLACED}, open(os.path.join(OUTDIR, "replicas.json"), "w"))
log("replicas placed", len(REPLICA_PLACED))
log("verts by material", sorted(MATV.items(), key=lambda kv: -kv[1])[:16])
log("chunk spill sources", sorted(SPILL.items(), key=lambda kv: -kv[1])[:10])
log("DONE chunks", len(manifest_chunks), "verts", total_v, "labels", len(labels_done))
