import sys, os, json, base64, urllib.parse
sys.argv = ["x", "lidar/house_parcels.json", "/tmp/pp_tmp", "0", "0", "0", "1.0"]
src = open("proj/tools/pipeline/parcel_photos.py").read().split("def main():")[0]
exec(src)
tok = new_token()
out = os.environ["OUT"]; os.makedirs(out, exist_ok=True)
for assr in os.environ["ASSR"].split(","):
    code, body = get(BASE + "api/documents/Parcel%20Photo/048/" + base64.b64encode(assr.encode()).decode() + "?token=" + tok)
    docs = json.loads(body) if code == 200 else []
    print(assr, code, len(docs), [ (d["Fields"] or {}).get("Taxyr") for d in docs])
    for i, d in enumerate(docs):
        p = os.path.join(out, f"{assr}_{i}.jpg")
        get(BASE + "api/document/" + urllib.parse.quote(d["Id"], safe="") + "/standard?token=" + tok, out=p)
