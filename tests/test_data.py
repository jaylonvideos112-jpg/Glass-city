"""Data tests for hand-authored source data and built game data. Run: python3 tests/test_data.py
Exit code = number of failures. No third-party test framework needed."""
import json, os, re, sys, csv, glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "source_data")
results = []

def test(fn):
    try:
        detail = fn() or ""
        results.append((fn.__name__, True, detail))
    except AssertionError as e:
        results.append((fn.__name__, False, str(e)))
    except Exception as e:  # noqa
        results.append((fn.__name__, False, f"{type(e).__name__}: {e}"))
    return fn

def bar_themes():
    s = open(os.path.join(ROOT, "scripts", "bars.gd")).read()
    block = s[s.index("const THEMES"):s.index("\n}\n", s.index("const THEMES"))]
    return set(re.findall(r'^\t"([^"]+)":', block, re.M))

@test
def facades_schema():
    F = {k: v for k, v in json.load(open(os.path.join(SRC, "facades.json"))).items() if not k.startswith("_")}
    assert len(F) >= 20, f"only {len(F)} facade specs"
    for k, v in F.items():
        for f in ("floor", "style", "wall", "wmat"):
            assert f in v, f"{k} missing {f}"
        assert 2.5 <= v["floor"] <= 8.0, f"{k} floor height {v["floor"]} m out of range (2.5-8 m)"
        assert 0 <= v["style"] <= 7, f"{k} style {v['style']}"
        assert re.fullmatch(r"#[0-9a-fA-F]{6}", v["wall"]), f"{k} wall colour {v['wall']}"
        assert 0.0 <= v["wmat"] <= 1.0, f"{k} wmat {v['wmat']}"
        assert v.get("src") in ("photo", "facts"), f"{k} has no provenance (src)"
        if "bay" in v: assert 0.8 <= v["bay"] <= 6.0, f"{k} bay {v['bay']}"
    return f"{len(F)} specs"

@test
def bars_reference_known_themes():
    B = json.load(open(os.path.join(SRC, "bars.json")))
    T = bar_themes()
    assert len(T) == 15, f"expected 15 bar brands in bars.gd, found {len(T)}"
    used = {b["theme"] for b in B}
    unknown = used - T
    assert not unknown, f"bars.json uses themes with no interior: {unknown}"
    for b in B:
        assert isinstance(b["x"], (int, float)) and isinstance(b["y"], (int, float)), f"bad position {b}"
    return f"{len(B)} bars, {len(used)} brands used"

@test
def downtown_ring_polygon():
    from shapely.geometry import Polygon
    d = json.load(open(os.path.join(SRC, "downtown_ring.json")))
    import math
    pts = d if isinstance(d, list) else d["ring"]   # [[lat, lon], ...]
    c = math.cos(math.radians(41.6528))
    g = Polygon([((lon + 83.5379) * 111320 * c, (lat - 41.6528) * 110574) for lat, lon in pts])
    assert g.is_valid and g.area > 1e5, f"downtown ring invalid or tiny (area {g.area:.0f})"
    return f"{g.area / 1e6:.2f} km2"

@test
def sign_names_complete():
    rows = list(csv.DictReader(open(os.path.join(SRC, "sign_names.csv"))))
    assert len(rows) > 800, f"only {len(rows)} sign rows"
    return f"{len(rows)} rows"

@test
def built_data_present():
    m = os.path.join(ROOT, "data", "manifest.json")
    assert os.path.exists(m), "data/manifest.json missing: run tools/build.sh city"
    man = json.load(open(m))
    missing = [c for c in man["chunks"][:: max(1, len(man["chunks"]) // 200)]
               if not os.path.exists(os.path.join(ROOT, "data", "chunks", f"{c[0]}_{c[1]}.bin"))]
    assert not missing, f"{len(missing)} sampled chunk files missing, e.g. {missing[:3]}"
    return f"{len(man['chunks'])} chunks in manifest"

@test
def textures_imported():
    pngs = glob.glob(os.path.join(ROOT, "textures", "*.png"))
    no_import = [os.path.basename(p) for p in pngs if not os.path.exists(p + ".import")]
    assert not no_import, f"textures never imported by Godot (blank in game): {no_import[:5]}"
    return f"{len(pngs)} textures"

@test
def licence_register_covers_sources():
    reg = open(os.path.join(ROOT, "docs", "DATA_SOURCES.md")).read()
    for must in ("OpenStreetMap", "ODbL", "USGS", "Lucas County", "Wikimedia Commons", "OSIP"):
        assert must in reg, f"DATA_SOURCES.md does not mention {must}"

@test
def climate_schema():
    C = json.load(open(os.path.join(SRC, "climate.json")))
    ck = C["clock"]
    assert ck["real_seconds_per_game_day"] == 3600, "day length must be 1 real hour (docs/DECISIONS.md)"
    assert ck["days_per_season"] == 12 and len(ck["seasons"]) == 4
    assert len(C["occupancy_by_hour"]) == 24 and all(0 <= v <= 1 for v in C["occupancy_by_hour"])
    st = C["weather"]["states"]
    for season, odds in C["weather"]["next"].items():
        assert set(odds) <= set(st), f"{season} odds name unknown states {set(odds) - set(st)}"
        assert abs(sum(odds.values()) - 1.0) < 0.02, f"{season} odds sum to {sum(odds.values()):.2f}"
    assert C["weather"]["next"]["summer"].get("snow", 0) == 0, "snow possible in summer"
    for k, v in st.items():
        assert v["hours"][0] <= v["hours"][1], f"{k} spell hours reversed"
    return f"{len(st)} weather states"

@test
def island_outline():
    import math
    from shapely.geometry import Polygon, Point
    ring = json.load(open(os.path.join(SRC, "island.json")))["ring"]
    g = Polygon([(lon, lat) for lat, lon in ring])
    assert g.is_valid, "island outline self-intersects"
    d = json.load(open(os.path.join(SRC, "island.json")))
    S_, W_, N_, E_ = d["real"]   # real data box; the made-up countryside (and the land that replaces Michigan) lies outside it
    lats = [lat for lat, _ in ring]; lons = [lon for _, lon in ring]
    assert min(lats) < S_ and max(lats) > N_ and min(lons) < W_ and max(lons) > E_, "made-up land must surround the real box"
    names = json.load(open(os.path.join(SRC, "place_names.json")))
    assert names.get("Toledo") == "Glass City" and len({v for k, v in names.items() if not k.startswith("_")}) == len([k for k in names if not k.startswith("_")]), "town names must be unique"
    towns = {"Toledo": (41.6528, -83.5379), "Sylvania": (41.7187, -83.7130), "Holland": (41.6217, -83.7116), "Maumee": (41.5628, -83.6538),
             "Perrysburg": (41.5570, -83.6272), "Rossford": (41.6098, -83.5644), "Northwood": (41.6056, -83.4838), "Oregon": (41.6437, -83.4869),
             "Walbridge": (41.5878, -83.4930), "Ottawa Hills": (41.6642, -83.6430), "Millbury": (41.5662, -83.4277)}
    out = [n for n, (la, lo) in towns.items() if not g.contains(Point(lo, la))]
    assert not out, f"towns outside the island: {out}"
    c = math.cos(math.radians(41.63))
    km2 = Polygon([(lo * 111.32 * c, la * 110.57) for la, lo in ring]).area
    return f"{km2:.0f} km2, all {len(towns)} towns inside"

for name, ok, detail in results:
    print(f"[data-test] {'PASS' if ok else 'FAIL'} {name}  ({detail})")
failed = sum(1 for r in results if not r[1])
print(f"[data-test] {len(results) - failed} passed, {failed} failed")
sys.exit(failed)
