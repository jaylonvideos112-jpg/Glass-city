"""Register a replica, export its massing, write its spec, build the glb and render a preview - one step.

usage: replica_add.py WORK KEY "Name" spec.json [azimuth elevation]
-> source_data/replicas.json entry, tools/blender/replicas/KEY/{massing,spec}.json, assets/models/bld_KEY.glb,
   /tmp/prev_KEY.png
"""
import sys, os, json, subprocess, shutil
WORK, KEY, NAME, SPEC = sys.argv[1:5]
AZ = sys.argv[5] if len(sys.argv) > 5 else "35"; EL = sys.argv[6] if len(sys.argv) > 6 else "14"
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BPY = os.environ.get("BPY", "/home/claude/bpyenv/bin/python")
p = os.path.join(REPO, "source_data/replicas.json"); d = json.load(open(p))
if KEY not in {b["key"] for b in d["buildings"]}:
    d["buildings"].append({"key": KEY, "name": NAME}); json.dump(d, open(p, "w"), indent=1)
rd = os.path.join(REPO, "tools/blender/replicas", KEY)
if not os.path.exists(os.path.join(rd, "massing.json")):
    subprocess.run(["python3", os.path.join(REPO, "tools/pipeline/replica_massing.py"), WORK, REPO], check=True, capture_output=True)
os.makedirs(rd, exist_ok=True)
if os.path.abspath(SPEC) != os.path.abspath(os.path.join(rd, "spec.json")): shutil.copy(SPEC, os.path.join(rd, "spec.json"))
out = os.path.join(REPO, f"assets/models/bld_{KEY}.glb")
r = subprocess.run([BPY, os.path.join(REPO, "tools/blender/replica.py"), rd, out], capture_output=True, text=True)
print([l for l in r.stdout.splitlines() if l.startswith("built")] or r.stderr[-1500:])
env = dict(os.environ); env.setdefault("RX", "1000"); env.setdefault("RY", "640")
subprocess.run([BPY, os.path.join(REPO, "tools/blender/preview_replica.py"), out, f"/tmp/prev_{KEY}.png", AZ, EL], env=env, capture_output=True)
