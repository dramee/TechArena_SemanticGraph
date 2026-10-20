"""Кандидаты на недостающие calls по статическим рёбрам скелета (calls/runtime_dispatch): оба метода исполнены, ребра нет."""
import sys, os, gzip, json, re, collections
a = json.load(open('submission.json', encoding='utf-8'))['scenarios']
sk = json.load(gzip.open('skeleton/trainticket.json.gz', 'rt', encoding='utf-8'))
sid = sys.argv[1] if len(sys.argv) > 1 else 'S5'
ex = {e['target'] for e in a[sid]['edges'] if e['relation'] == 'executes'}
calls = {(e['source'], e['target']) for e in a[sid]['edges'] if e['relation'] == 'calls'}
f = lambda m: m.split(':', 2)[2]
pairs = collections.defaultdict(set)
for e in sk['edges']:
    if e['type'] in ('calls', 'runtime_dispatch'):
        s = e['source']; m = re.match(r'call:(method:[^@]*)@(\d+:\d+)$', s)
        if not m: continue
        pairs[(m.group(1), e['target'])].add((e['type'], m.group(2)))
out = [(p, v) for p, v in pairs.items() if p[0] in ex and p[1] in ex and p not in calls]
print(len(pairs), 'static pairs;', len(out), 'candidates (both executed, no edge)')
for (x, y), v in sorted(out):
    print(f(x).split('(')[0], '->', f(y).split('(')[0], sorted(v))
