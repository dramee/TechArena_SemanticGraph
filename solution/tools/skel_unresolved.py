"""Кандидаты на недостающие calls: call-site без статического ребра в скелете, имя callee совпадает с исполненным методом проекта."""
import sys, os, gzip, json, collections
sid = sys.argv[1] if len(sys.argv) > 1 else 'S5'
a = json.load(open('submission.json', encoding='utf-8'))['scenarios']
sk = json.load(gzip.open('skeleton/trainticket.json.gz', 'rt', encoding='utf-8'))
ex = {e['target'] for e in a[sid]['edges'] if e['relation'] == 'executes'}
calls = {(e['source'], e['target']) for e in a[sid]['edges'] if e['relation'] == 'calls'}
byname = collections.defaultdict(list)
for m in ex:
    byname[m.split('#', 1)[1].split('(')[0]].append(m)
resolved = {e['source'] for e in sk['edges'] if e['source'].startswith('call:')}
f = lambda m: m.split(':', 2)[2].split('(')[0]
out = []
for k, v in sk['nodes'].items():
    if v['kind'] != 'call_site' or k in resolved: continue
    A = v['method']
    if A not in ex: continue
    nm = v['callee']
    rt = v.get('receiver_type')
    for B in byname.get(nm, []):
        if nm == '<init>': continue
        bcls = B.split(':', 2)[2].split('#')[0]
        if rt is not None and rt != bcls: continue
        if (A, B) not in calls and A != B:
            out.append((f(A), f(B), v['receiver'], v['receiver_type'], v['line']))
out.sort()
print(len(out))
for o in out: print(o)
