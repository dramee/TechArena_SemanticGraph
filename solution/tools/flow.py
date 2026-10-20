"""Печать дерева выполнения шага сценария: python _flow.py S1 <n шага|all> [maxdepth]"""
import sys, os, json, threading
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from solve import *
import interp as I
import web as W
from values import *

def main():
    sid = sys.argv[1]; which = sys.argv[2]; maxd = int(sys.argv[3]) if len(sys.argv) > 3 else 99
    proj = Project('skeleton/trainticket.json.gz', 'targets/trainticket')
    tables0 = dbm.parse_dump('context/db-after-warmup.sql.gz')
    S = load_json(f'scenarios/{sid}.json')
    out = []
    oinv = I.Interp.invoke
    def inv(self, mi, this, args, caller):
        d = len(self.stack)
        if d <= maxd:
            out.append("  " * d + f"{mi.cls.name}#{mi.name}  [{mi.cls.module.replace('ts-','').replace('-service','')}]")
        return oinv(self, mi, this, args, caller)
    I.Interp.invoke = inv
    oserve = W.Web.serve
    def serve(self, module, mi, ci, pvars, query, body, caller, headers=None):
        out.append("  " * len(self.it.stack) + f"==> REMOTE {module} {ci.name}#{mi.name}")
        return oserve(self, module, mi, ci, pvars, query, body, caller, headers)
    W.Web.serve = serve
    tables = copy.deepcopy(tables0)
    it = I.Interp(proj, tables); Repos(it); Web(it)
    cl = Client(it, S)
    for st in S['steps']:
        out.append(f"##### STEP {st['n']}: {st['action']}")
        try: cl.step(st['n'], st['action'])
        except Exception as e: out.append("!!! " + repr(e)[:200])
        out.append("  -> " + str(cl.log[-1])[:200])
    txt = "\n".join(out)
    if which != 'all':
        parts = txt.split("##### STEP ")
        txt = "\n".join("##### STEP " + p for p in parts if p.startswith(which + ":"))
    print(txt)
th = threading.Thread(target=main); threading.stack_size(64*1024*1024); th = threading.Thread(target=main); th.start(); th.join()
