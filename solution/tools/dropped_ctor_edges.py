import sys, os, threading
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from solve import *
def main():
    proj = Project('skeleton/trainticket.json.gz', 'targets/trainticket')
    tables0 = dbm.parse_dump('context/db-after-warmup.sql.gz')
    f = lambda m: m.split(':', 2)[2]
    res = {}
    for k in range(0, 8):
        S = load_json(f'scenarios/S{k}.json')
        it, cl, errs = run_scenario(proj, tables0, S)
        ex, calls = apply_label_rules(it.trace)
        res[k] = {c for c in it.trace.calls if '#<init>' in c[1]}
        res[(k,'ex')] = ex
    for k in range(0, 8):
        others = set().union(*[res[j] for j in range(8) if j != k])
        print(f"S{k}: ctor-target calls {len(res[k])}, only-here {len(res[k]-others)}")
        for a, b in sorted(res[k] - others): print('    ', f(a).split('(')[0], '->', f(b), 'ctor in executes:', b in res[(k,'ex')])
th = threading.Thread(target=main); threading.stack_size(64*1024*1024); th = threading.Thread(target=main); th.start(); th.join()
