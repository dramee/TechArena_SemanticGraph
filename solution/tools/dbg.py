import sys, os, json, copy, threading
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from solve import *
import interp as I
from values import *

def main():
    sid = sys.argv[1]; watch = sys.argv[2:] 
    proj = Project('skeleton/trainticket.json.gz', 'targets/trainticket')
    tables0 = dbm.parse_dump('context/db-after-warmup.sql.gz')
    S = load_json(f'scenarios/{sid}.json')
    orig = I.Interp.invoke
    def inv(self, mi, this, args, caller):
        if any(w == f"{mi.cls.name}#{mi.name}" for w in watch):
            print("INVOKE", mi.cls.name, mi.name, [ ([type(x).__name__ if not hasattr(x,"cls") else x.cls.name for x in a] if isinstance(a,list) else str(a)[:300]) for a in args])
        r = orig(self, mi, this, args, caller)
        if any(w == f"{mi.cls.name}#{mi.name}" for w in watch):
            print("  RETURN", mi.cls.name, mi.name, str(r)[:600])
        return r
    I.Interp.invoke = inv
    it, cl, errors = run_scenario(proj, tables0, S)
    for l in cl.log: print(l)
    print(errors[:3]); print(it.exc_log[:5])
th = threading.Thread(target=main); threading.stack_size(64*1024*1024); th = threading.Thread(target=main); th.start(); th.join()
