import sys, os, gzip, json, collections, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import jparse
from jparse import *

ROOT = "targets/trainticket"
def walk(n, f):
    if isinstance(n, Node):
        f(n)
        for s in n.__slots__:
            if s in ('outer','cls') and not isinstance(n, New): continue
            walk(getattr(n, s), f)
    elif isinstance(n, (list, tuple, set)):
        for x in n: walk(x, f)
    elif isinstance(n, dict):
        for x in n.values(): walk(x, f)

sk = json.load(gzip.open('skeleton/trainticket.json.gz', 'rt', encoding='utf-8'))
files = sorted({n['file'] for n in sk['nodes'].values() if n['kind']=='file' and n['file'].endswith('.java')} if False else
               {n['path'] for n in sk['nodes'].values() if n['kind']=='file' and n['path'].endswith('.java')})
print(len(files), 'java files in skeleton')
t0 = time.time()
errs = 0
parsed = {}
for f in files:
    try:
        p, types = parse_file(os.path.join(ROOT, f))
        parsed[f] = types
    except Exception as e:
        errs += 1
        print('ERR', f, str(e)[:200])
print('parsed', len(parsed), 'errs', errs, 'time', round(time.time()-t0,1))
# сравнение позиций вызовов
mine = collections.defaultdict(set)
for f, types in parsed.items():
    def f_(n, f=f):
        if isinstance(n, Call): mine[f].add((n.line, n.col))
        elif isinstance(n, New): mine[f].add((n.line, n.col))
    for t in types: walk(t, f_)
miss = collections.Counter(); tot = 0; ok = 0; ex = []
for k, n in sk['nodes'].items():
    if n['kind'] != 'call_site': continue
    tot += 1
    if (n['line'], n['col']) in mine[n['file']]: ok += 1
    else:
        miss[n['module']] += 1
        if len(ex) < 15: ex.append((n['file'], n['line'], n['col'], n['callee'], n['receiver']))
print('call sites', tot, 'matched', ok)
print(miss.most_common(5))
for e in ex: print(e)
extra = sum(len(v) for v in mine.values()) - ok
print('my call positions not in skeleton:', extra)
