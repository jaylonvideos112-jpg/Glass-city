"""Houses that are gone: buildings standing on parcels the county now records as vacant residential land
(land use 500, building value 0), plus houses whose county photo shows an empty lot (label 'V').
usage: vacant_keys.py all_parcels.json gen.csv labels.json osm_blds.pkl out.json"""
import sys, csv, json, pickle
LINK, GEN, LAB, BLDS, OUT = sys.argv[1:6]
g = {r["AssrNo"]: r for r in csv.DictReader(open(GEN))}
lab = json.load(open(LAB)); o = pickle.load(open(BLDS, "rb"))
link = json.load(open(LINK))
out = []
for k, (a, _, _) in link.items():
    r = g.get(a)
    if k not in o or o[k][1].area > 450: continue
    if (r and r["Landuse"] == "500" and r["Bldg"] in ("0", "")) or lab.get(a, "").startswith("V"):
        out.append(k)
json.dump(sorted(out), open(OUT, "w"))
print("gone", len(out))
