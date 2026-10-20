import sys, os, gzip, json, collections
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from jparse import *
ROOT="targets/trainticket"
sk = json.load(gzip.open('skeleton/trainticket.json.gz', 'rt', encoding='utf-8'))
N=sk['nodes']
byfile=collections.defaultdict(list)
for k,n in N.items():
    if n['kind']=='method': byfile[n['file']].append((n['name'],n['line'],n['end'],k))
def allclasses(c):
    yield c
    for i in c.inner: yield from allclasses(i)
tot=ok=0; bad=[]
for f in sorted({n['file'] for n in N.values() if n['kind']=='method'}):
    p,types=parse_file(os.path.join(ROOT,f))
    nodes=byfile[f]
    decls=[]
    for t in types:
        for c in allclasses(t):
            for m in c.methods: decls.append(m)
    idx=collections.defaultdict(list)
    for nm,l,e,k in nodes: idx[nm].append((l,e,k))
    for m in decls:
        tot+=1
        cands=idx.get(m.name,[])
        hit=[c for c in cands if c[0]==m.start]
        if hit: ok+=1
        else: bad.append((f,m.name,m.line,cands))
print(tot,ok,len(bad))
for b in bad[:20]: print(b)
# skeleton nodes without decl match
