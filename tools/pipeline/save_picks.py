import csv,json,sys
m=json.loads(sys.argv[1])
s=list(csv.reader(open('refs/signs.csv'))); p=list(csv.reader(open('refs/picks.csv')))
n=0
for a,b in zip(s[1:],p[1:]):
    if a[0] in m: b[0]=m[a[0]]; n+=1
csv.writer(open('refs/picks.csv','w',newline='')).writerows(p); print("saved",n)
