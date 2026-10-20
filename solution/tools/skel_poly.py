"""Кандидаты на недостающие calls через полиморфизм: receiver_type R, метод B в классе C <= R (implements/extends), оба исполнены, ребра нет."""
import sys, gzip, json, collections
sid = sys.argv[1] if len(sys.argv) > 1 else 'S5'
a = json.load(open('submission.json', encoding='utf-8'))['scenarios']
sk = json.load(gzip.open('skeleton/trainticket.json.gz', 'rt', encoding='utf-8'))
ex = {e['target'] for e in a[sid]['edges'] if e['relation'] == 'executes'}
calls = {(e['source'], e['target']) for e in a[sid]['edges'] if e['relation'] == 'calls'}
sub = collections.defaultdict(set)   # R -> subtypes (fqn)
for e in sk['edges']:
    if e['type'] in ('implements', 'extends'):
        r = e['target'].split(':', 2)[2]; c = e['source'].split(':', 2)[2]
        sub[r].add(c)
def allsub(r, seen=None):
    seen = seen or set(); out = {r}
    for c in sub.get(r, ()):
        if c not in seen:
            seen.add(c); out |= allsub(c, seen)
    return out
byname = collections.defaultdict(list)
for m in ex:
    cls = m.split(':', 2)[2].split('#')[0]
    byname[m.split('#', 1)[1].split('(')[0]].append((cls, m))
f = lambda m: m.split(':', 2)[2].split('(')[0]
out = []
for k, v in sk['nodes'].items():
    if v['kind'] != 'call_site': continue
    A = v['method']
    if A not in ex: continue
    R = v.get('receiver_type'); n = v['callee']
    if R is None or n == '<init>': continue
    S = allsub(R)
    for cls, B in byname.get(n, []):
        if cls in S and (A, B) not in calls and A != B:
            out.append((f(A), f(B), R, v['line']))
print(len(out))
for o in sorted(set(out)): print(o)
