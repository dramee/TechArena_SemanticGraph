import sys, os, json, threading
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from solve import *
import web as W
def run(sid, traced):
    proj = Project('skeleton/trainticket.json.gz', 'targets/trainticket')
    tables0 = dbm.parse_dump('context/db-after-warmup.sql.gz')
    S = load_json(f'scenarios/{sid}.json')
    oc = W.Web.convert; ot = W.Web.to_raw
    if traced:
        def conv(self, v, tname, ctx, ci=None, traced=False, tvars=None): return oc(self, v, tname, ctx, ci, self._client_side, tvars)
        W.Web.convert = conv
    if not traced:
        def conv(self, v, tname, ctx, ci=None, traced=False, tvars=None): return oc(self, v, tname, ctx, ci, False, tvars)
        def raw(self, v, traced=False): return ot(self, v, False)
        W.Web.convert = conv; W.Web.to_raw = raw
    it, cl, errs = run_scenario(proj, tables0, S)
    W.Web.convert = oc; W.Web.to_raw = ot
    return it.trace
def main():
    for sid in sys.argv[1:]:
        a = run(sid, True); b = run(sid, False)
        print(sid, 'executes', len(a.executes), len(b.executes), 'calls', len(a.calls), len(b.calls))
        for m in sorted(a.executes - b.executes): print('   only traced:', m.split(':',2)[2][:120])
        for c in sorted(a.calls - b.calls)[:10]: print('   only traced call:', c[0].split(':',2)[2][:70], '->', c[1].split(':',2)[2][:70])
th = threading.Thread(target=main); threading.stack_size(64*1024*1024); th = threading.Thread(target=main); th.start(); th.join()
