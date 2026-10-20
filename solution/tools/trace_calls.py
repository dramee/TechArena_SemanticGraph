"""Печать вызовов заданного метода: python trace_calls.py S5 Class#method"""
import sys, os, threading
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from solve import *
import interp as I
def main():
    sid, target = sys.argv[1], sys.argv[2]
    cname, mname = target.split('#')
    proj = Project('skeleton/trainticket.json.gz', 'targets/trainticket')
    tables0 = dbm.parse_dump('context/db-after-warmup.sql.gz')
    orig = I.Interp.invoke
    def inv(self, mi, this, args, caller):
        hit = mi.name == mname and mi.cls.name == cname
        if hit:
            def sh(v):
                try:
                    return v.f if hasattr(v, 'f') else v
                except Exception:
                    return v
            print('CALL', mi.cls.name, mi.name, [sh(a) for a in args], 'from', caller.id.split('#')[-1] if caller else None)
        r = orig(self, mi, this, args, caller)
        if hit:
            rr = r
            if hasattr(r, 'f'):
                rr = r.f
            print('   ->', str(rr)[:300])
        return r
    I.Interp.invoke = inv
    S = load_json(f'scenarios/{sid}.json')
    run_scenario(proj, tables0, S)
th = threading.Thread(target=main); threading.stack_size(64*1024*1024); th = threading.Thread(target=main); th.start(); th.join()
