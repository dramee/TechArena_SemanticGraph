import sys, os, json, copy, threading
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from solve import *
import interp as I
from values import *
def main():
    sid=sys.argv[1]; meth=sys.argv[2]; upto=int(sys.argv[3]) if len(sys.argv)>3 else 99
    proj = Project('skeleton/trainticket.json.gz', 'targets/trainticket')
    tables0 = dbm.parse_dump('context/db-after-warmup.sql.gz')
    S = load_json(f'scenarios/{sid}.json'); S['steps']=S['steps'][:upto]
    orig = I.Interp.invoke
    def show(a, d=0):
        if isinstance(a, JObj): return a.cls.name + '{' + ', '.join(f'{k}={show(v,d+1)}' for k,v in a.f.items()) + '}' if d<3 else a.cls.name+'{..}'
        if isinstance(a, list): return '[' + ', '.join(show(x,d+1) for x in a[:6]) + ']'
        if isinstance(a, dict): return '{' + ', '.join(f'{k}: {show(v,d+1)}' for k,v in list(a.items())[:8]) + '}'
        return repr(a)[:60]
    def inv(self, mi, this, args, caller):
        hit = meth == f"{mi.cls.name}#{mi.name}"
        if hit: print("INVOKE", meth, [show(a) for a in args])
        r = orig(self, mi, this, args, caller)
        if hit: print("  RETURN", show(r))
        return r
    I.Interp.invoke = inv
    it, cl, errors = run_scenario(proj, tables0, S)
    print([e[:4] for e in errors])
th = threading.Thread(target=main); threading.stack_size(64*1024*1024); th = threading.Thread(target=main); th.start(); th.join()
