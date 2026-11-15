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

for name, ok, detail in results:
    print(f"[data-test] {'PASS' if ok else 'FAIL'} {name}  ({detail})")
failed = sum(1 for r in results if not r[1])
print(f"[data-test] {len(results) - failed} passed, {failed} failed")
sys.exit(failed)
