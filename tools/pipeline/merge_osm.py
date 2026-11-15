import json, sys, glob
out = sys.argv[1]; bbox = list(map(float, sys.argv[2:6])); files = sys.argv[6:]
els = {}
for pat in files:
    for f in glob.glob(pat):
        for e in json.load(open(f))["elements"]:
            els[(e["type"], e["id"])] = e
json.dump({"bbox": bbox, "elements": list(els.values())}, open(out, "w"))
print(len(els), "elements")
