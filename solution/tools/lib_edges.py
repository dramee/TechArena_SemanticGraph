"""Рёбра calls, порождённые name-match правилом библиотечных вызовов (lib_invoke), по сценариям."""
import sys, os, threading
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from solve import *
import interp as I
def main():
    proj = Project('skeleton/trainticket.json.gz', 'targets/trainticket')
    tables0 = dbm.parse_dump('context/db-after-warmup.sql.gz')
    LIB = {}
    orig = I.Interp.lib_invoke
    cur = [None]
    def li(self, mi, this, args):
        cur[0] = self
        return orig(self, mi, this, args)
    orig_rc = I.Interp.rec_call
    flag = [0]
    def li2(self, mi, this, args):
        flag[0] += 1
        try:
            return orig(self, mi, this, args)
        finally:
            flag[0] -= 1
    def rc(self, a, b):
        if flag[0] and a is not None and b is not None and a.id and b.id and self.has_stmts(b) and (a.id, b.id) not in self.trace.calls:
            LIB.setdefault('cur', set()).add((a.id, b.id))
        return orig_rc(self, a, b)
    I.Interp.lib_invoke = li2
    I.Interp.rec_call = rc
    res = {}
    for k in range(0, 8):
        LIB.clear()
        S = load_json(f'scenarios/S{k}.json')
        it, cl, errs = run_scenario(proj, tables0, S)
        res[k] = set(LIB.get('cur', set()))
    f = lambda m: m.split(':', 2)[2].split('(')[0]
    for k in range(0, 8):
        others = set().union(*[res[j] for j in res if j != k])
        print(f"S{k}: lib-edges {len(res[k])}, only-here {len(res[k]-others)}")
        for a, b in sorted(res[k] - others): print("     ", f(a), '->', f(b))
th = threading.Thread(target=main); threading.stack_size(64*1024*1024); th = threading.Thread(target=main); th.start(); th.join()
