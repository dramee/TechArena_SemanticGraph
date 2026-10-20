"""Кандидаты на недостающие calls-рёбра: оба метода исполнены в сценарии, в исходнике вызывающего есть вызов с именем вызываемого, ребра нет."""
import sys, os, threading
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from solve import *
from model import called_names
import re
_T = {}
def _txt(f):
    if f not in _T:
        _T[f] = open(os.path.join('targets/trainticket', f), encoding='utf-8', errors='replace').read()
    return _T[f]
def main():
    sid = sys.argv[1] if len(sys.argv) > 1 else 'S5'
    proj = Project('skeleton/trainticket.json.gz', 'targets/trainticket')
    tables0 = dbm.parse_dump('context/db-after-warmup.sql.gz')
    S = load_json(f'scenarios/{sid}.json')
    it, cl, errs = run_scenario(proj, tables0, S)
    ex, calls = apply_label_rules(it.trace)
    mis = proj.methods_by_id
    print(len(mis), 'methods indexed')
    out = []
    for a in sorted(ex):
        ma = mis.get(a)
        if ma is None: continue
        names = called_names(ma)
        for b in sorted(ex):
            if b == a or '#<init>' in b: continue
            nm = b.split('#', 1)[1].split('(')[0]
            if nm in names and (a, b) not in calls:
                mb = mis.get(b)
                if mb is None: continue
                if mb.cls is not ma.cls and not (len(sys.argv) > 2 and sys.argv[2] == 'all'):
                    txt = _txt(ma.cls.file)
                    if not re.search(r'' + re.escape(mb.cls.name) + r'', txt):
                        continue
                out.append((a, b))
    f = lambda m: m.split(':', 2)[2].split('(')[0]
    print(len(out), 'кандидатов')
    for a, b in out: print(f(a), '->', f(b))
th = threading.Thread(target=main); threading.stack_size(64*1024*1024); th = threading.Thread(target=main); th.start(); th.join()
