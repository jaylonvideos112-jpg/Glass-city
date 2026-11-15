import re,sys,urllib.parse,subprocess,html,json
J='/tmp/l.txt'; URL='https://lucapps.co.lucas.oh.us/Downloads/Home.aspx'
def form(t):
    d={}
    for i in re.findall(r'<input[^>]*>',t):
        n=re.search(r'name="([^"]+)"',i); v=re.search(r'value="([^"]*)"',i); ty=re.search(r'type="([^"]+)"',i)
        if n and (not ty or ty.group(1) in ('hidden','text')): d[n.group(1)]=html.unescape(v.group(1)) if v else ''
    for s in re.finditer(r'<select[^>]*name="([^"]+)"[^>]*>(.*?)</select>',t,re.S):
        sel=re.search(r'<option[^>]*selected="selected"[^>]*value="([^"]*)"',s.group(2))
        d[s.group(1)]=sel.group(1) if sel else ''
    return d
def post(t,extra,out):
    d=form(t); d.update(extra)
    open('/tmp/pb.post','w').write(urllib.parse.urlencode(d))
    subprocess.run(['curl','-s','-c',J,'-b',J,'-L','-m','600','-o',out,'--data','@/tmp/pb.post',URL])
    return open(out,encoding='utf-8',errors='ignore').read() if not out.endswith(('.zip','.accdb','.bin')) else ''
