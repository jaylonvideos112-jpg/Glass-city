"""Assemble README.md: the complete GLASS CITY brief, in one file.

Hand-written parts live in docs/readme/*.md (brief, bible summary, know-how); everything that can be read from
the repo is generated here: a file-by-file index (from each file's header comment/docstring), every data file and
its names (cars, bars, banks, dealers, workplaces, schools, places, bus routes, homes ...), the full test list, the
landmark replica list, build settings, demo shot names, the other docs inlined in full, and the street-name table.
Run after every change (owner's rule):   python3 tools/make_readme.py
usage: python3 tools/make_readme.py [REPO]"""
import os, re, sys, json, glob, ast, csv, datetime

R = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), ".."))
J = lambda *p: os.path.join(R, *p)
out = []
w = out.append

def rel(p): return os.path.relpath(p, R)

def gd_header(p):
    lines = []
    for l in open(p, encoding="utf-8", errors="replace"):
        s = l.strip()
        if s.startswith("##"): lines.append(s.lstrip("#").strip())
        elif s.startswith(("extends", "class_name", "@tool")) or not s: continue
        else: break
    return " ".join(lines)

def py_doc(p):
    try: d = ast.get_docstring(ast.parse(open(p, encoding="utf-8", errors="replace").read()))
    except Exception: d = None
    if d: return " ".join(d.split())
    lines = []
    for l in open(p, encoding="utf-8", errors="replace"):
        if l.startswith("#!"): continue
        if l.startswith("#"): lines.append(l.lstrip("#").strip())
        elif lines or l.strip(): break
    return " ".join(lines)

def sh_doc(p):
    lines = []
    for l in open(p, encoding="utf-8", errors="replace"):
        if l.startswith("#!"): continue
        if l.startswith("#"): lines.append(l.lstrip("#").strip())
        else: break
    return " ".join(lines)

def shader_doc(p):
    lines = []
    for l in open(p, encoding="utf-8", errors="replace"):
        s = l.strip()
        if s.startswith("//"): lines.append(s.lstrip("/").strip())
        elif s.startswith("shader_type") or not s: continue
        else: break
    return " ".join(lines)

def cut(s, n=700): return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + " …"

# ------------------------------------------------------------------------------------------------ hand-written
parts = sorted(glob.glob(J("docs/readme/*.md")))
today = datetime.date.today().isoformat()
for p in parts:
    t = open(p, encoding="utf-8").read()
    t = re.sub(r"Last updated: \*\*[0-9-]+\*\*", "Last updated: **%s**" % today, t)
    w(t.rstrip() + "\n\n")

# ------------------------------------------------------------------------------------------------ file index
w("## 18. File-by-file index (generated from each file's header)\n\n")
groups = [("Game scripts (`scripts/`)", "scripts/*.gd", gd_header), ("Shaders (`shaders/`)", "shaders/*.gdshader", shader_doc),
          ("Tests", "tests/*", None), ("Data pipeline (`tools/pipeline/`)", "tools/pipeline/*.py", py_doc),
          ("Blender builders (`tools/blender/`)", "tools/blender/*.py", py_doc),
          ("Character creator (`tools/blender/charcreator/`)", "tools/blender/charcreator/*.py", py_doc),
          ("Tools and debug (`tools/`, `tools/dbg/`)", "tools/*.*", None), ("", "tools/dbg/*.*", None), ("", "tools/dbg/helpers/*", None)]
for title, pat, fn in groups:
    files = sorted(f for f in glob.glob(J(pat)) if os.path.isfile(f) and not f.endswith((".import", ".uid", ".pyc")))
    if not files: continue
    if title: w("### %s\n\n| file | what it is |\n|---|---|\n" % title)
    for f in files:
        if fn: d = fn(f)
        elif f.endswith(".py"): d = py_doc(f)
        elif f.endswith(".gd"): d = gd_header(f)
        elif f.endswith((".sh", ".bat")): d = sh_doc(f) if f.endswith(".sh") else ""
        else: d = ""
        w("| `%s` | %s |\n" % (rel(f), cut(d).replace("|", "/") or "—"))
    w("\n")
nrep = len(glob.glob(J("tools/blender/replicas/*/spec.json")))
nglb = len(glob.glob(J("assets/models/*.glb")))
w("Also: `tools/blender/replicas/<key>/{spec,massing}.json` (%d landmark specs), `tools/blender/mh/` (MakeHuman base mesh, "
  "targets, rig and weights; see its SOURCE.md), `assets/models/` (%d .glb models), `textures/` (procedural + Poly Haven PBR), "
  "`scenes/`, `fonts/`, `assets_src/` (source models, not shipped).\n\n" % (nrep, nglb))

# ------------------------------------------------------------------------------------------------ data files
w("## 19. Data files (`source_data/`) and every name in them\n\n")
def names_in(o, key="name", acc=None):
    acc = [] if acc is None else acc
    if isinstance(o, dict):
        if key in o and isinstance(o[key], str): acc.append(o[key])
        for v in o.values(): names_in(v, key, acc)
    elif isinstance(o, list):
        for v in o: names_in(v, key, acc)
    return acc
for f in sorted(glob.glob(J("source_data/*"))):
    if f.endswith(".import"): continue
    b = os.path.basename(f); size = os.path.getsize(f)
    w("### `%s` (%d KB)\n" % (b, max(1, size // 1024)))
    if f.endswith(".json"):
        d = json.load(open(f, encoding="utf-8"))
        doc = (d.get("_doc") or d.get("_note")) if isinstance(d, dict) else None
        if doc: w("%s\n\n" % (doc if isinstance(doc, str) else json.dumps(doc)))
        if isinstance(d, dict): w("Top-level keys: %s\n\n" % ", ".join("`%s`" % k for k in list(d)[:25]) + (" …" if len(d) > 25 else ""))
        else: w("List of %d records.\n\n" % len(d))
        if b == "vehicles.json":
            w("Makes: %s\n\n" % "; ".join("**%s**" % v for v in d["makes"].values()))
            w("| id | make | model | category | price $ | traffic share |\n|---|---|---|---|---|---|\n")
            for m in d["models"]: w("| %s | %s | %s | %s | %s | %s |\n" % (m.get("id"), m.get("make"), m.get("model"), m.get("category"), m.get("price"), m.get("traffic_share")))
            w("\n")
        elif b == "bars.json":
            w("Bars (%d): %s\n\n" % (len(d), "; ".join("%s (real: %s)" % (x.get("theme"), x.get("real")) for x in d)))
        elif b == "atms.json":
            banks = sorted(set(x.get("bank") for x in d["atms"]))
            w("%d ATMs. Banks (made up): %s\n\n" % (len(d["atms"]), ", ".join(banks)))
        elif b in ("place_names.json",):
            w("```json\n%s\n```\n\n" % json.dumps(d, indent=1, ensure_ascii=False))
        elif b == "school_names.json":
            w("| real school | in-game name |\n|---|---|\n")
            for k, v in d.items():
                if k.startswith("_"): continue
                w("| %s | %s |\n" % (k, v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)))
            w("\n")
        elif b == "street_names.json":
            w("%d streets renamed (full table in the appendix at the end). Hand-fixed: %s\n\n" % (len([k for k in d if not k.startswith("_")]), json.dumps(d.get("_fixed", {}), ensure_ascii=False)))
        elif b == "replicas.json":
            bl = d["buildings"]
            w("%d landmark candidates/replicas. Built models are marked ✔.\n\n| key | name | built |\n|---|---|---|\n" % len(bl))
            for x in bl: w("| %s | %s | %s |\n" % (x.get("key"), x.get("name"), "✔" if os.path.exists(J("assets/models/bld_%s.glb" % x.get("key"))) else ""))
            w("\n")
        elif b == "house_photo_labels.json":
            from collections import Counter
            c = Counter(v[0] for v in d.values() if isinstance(v, str) and v)
            w("%d hand-labelled houses (parcel number -> `PDSRAP` code, see section 15). Porch types: %s\n\n" % (len(d), dict(c)))
        elif b == "facades.json":
            w("%d downtown facade specs (photo/fact matched).\n\n" % len([k for k in d if not k.startswith("_")]))
        elif b == "island.json":
            w("Island outline, real-data box, holes and islets (geometry).\n\n")
        elif b == "bus_routes.json":
            w("Operator: %s. Routes: %s\n\n" % (d.get("operator"), "; ".join(names_in(d["routes"])) or len(d["routes"])))
        else:
            ns = names_in(d)
            if ns:
                uniq = list(dict.fromkeys(ns))
                w("%d named records: %s\n\n" % (len(ns), ", ".join(uniq)))
            else:
                small = json.dumps(d, ensure_ascii=False)
                if len(small) < 3500: w("```json\n%s\n```\n\n" % json.dumps(d, indent=1, ensure_ascii=False))
    elif f.endswith(".csv"):
        rows = list(csv.reader(open(f, encoding="utf-8")))
        w("%d rows. Columns: %s\n\n" % (len(rows) - 1, rows[0] if rows else ""))
        w("Names: %s\n\n" % ", ".join(r[0] for r in rows[1:] if r))
    else:
        t = open(f, encoding="utf-8", errors="replace").read()
        w("```\n%s\n```\n\n" % t[:3000])

# ------------------------------------------------------------------------------------------------ tests
w("## 20. Every automated test\n\n")
tr = open(J("tests/test_runner.gd"), encoding="utf-8").read()
names = re.findall(r'\["([a-z0-9_]+)", t_[a-z0-9_]+\]', tr)
w("In-game tests (`tests/test_runner.gd`, %d): %s\n\n" % (len(names), ", ".join("`%s`" % n for n in names)))
if os.path.exists(J("tests/test_data.py")):
    td = re.findall(r"def (test_[a-z0-9_]+)", open(J("tests/test_data.py"), encoding="utf-8").read())
    w("Data tests (`tests/test_data.py`, %d): %s\n\n" % (len(td), ", ".join("`%s`" % n for n in td)))
res = J("tests/out/results.json")
if os.path.exists(res):
    r = json.load(open(res)); w("Last recorded run: %s, %s passed, %s failed.\n\n" % (r.get("when"), r.get("passed"), r.get("failed")))

# ------------------------------------------------------------------------------------------------ build settings, shots
w("## 21. Build script and settings\n\n```sh\n%s\n```\n\n" % open(J("tools/build.sh"), encoding="utf-8").read())
demo = open(J("scripts/demo.gd"), encoding="utf-8").read()
shots = sorted(set(re.findall(r'"(@[a-z_]+)"', demo)))
w("Demo shot keywords in `scripts/demo.gd`: %s. Command-line flags read by the game: %s\n\n" % (
    ", ".join("`%s`" % s for s in shots),
    ", ".join("`%s`" % s for s in sorted(set(re.findall(r'"(--[a-z\-]+=?)', "".join(open(f, encoding="utf-8").read() for f in glob.glob(J("scripts/*.gd")) + [J("tests/test_runner.gd")])))))))

# ------------------------------------------------------------------------------------------------ inline docs
for i, (fn, title) in enumerate([("ARCHITECTURE.md", "Architecture"), ("BUILD.md", "Build"), ("DATA_SOURCES.md", "Data sources and licences"),
                                  ("PERF_BUDGETS.md", "Performance budgets"), ("CODING_STANDARDS.md", "Coding standards"),
                                  ("DECISIONS.md", "Decision log (full)"), ("CHANGELOG.md", "Changelog (full feature history)")], 22):
    p = J("docs", fn)
    if not os.path.exists(p): continue
    t = open(p, encoding="utf-8").read()
    t = re.sub(r"^(#+) ", lambda m: "#" * (len(m.group(1)) + 2) + " ", t, flags=re.M)   # demote headings
    w("## %d. %s (`docs/%s`, inlined)\n\n%s\n\n" % (i, title, fn, t.strip()))

# ------------------------------------------------------------------------------------------------ appendix
sn = json.load(open(J("source_data/street_names.json"), encoding="utf-8"))
w("## Appendix A. Street name table (real -> in-game)\n\n<details><summary>%d streets</summary>\n\n| real | in-game |\n|---|---|\n" % len(sn))
for k, v in sn.items():
    if k.startswith("_"): continue
    w("| %s | %s |\n" % (k, v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)))
w("\n</details>\n\n")

w("""---

## Keeping this file current
**Rule (owner, 2026-11-21):** every change to the project updates this README in the same commit.
1. Edit the hand-written parts in `docs/readme/` (01 brief: current state, decisions, preferences; 02 bible summary;
   03 know-how: history, lessons, helpers, recipes) and the other docs (`docs/CHANGELOG.md` for every feature).
2. Give new files a header comment / docstring (it becomes their index line).
3. Run `python3 tools/make_readme.py` - it regenerates everything else (index, data, names, tests, replicas,
   inlined docs) - and commit README.md with the change.
""")
open(J("README.md"), "w", encoding="utf-8").write("".join(out))
print("README.md: %d lines, %d KB" % ("".join(out).count("\n"), len("".join(out).encode()) // 1024))
