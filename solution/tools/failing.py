"""Внутренние вызовы с ответом status=0 / HTTP>=400: python failing.py S1 [S2 ...]"""
import sys, os, json, copy, threading
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from solve import *
import web as W
from values import *
def main():
    proj = Project('skeleton/trainticket.json.gz', 'targets/trainticket')
    tables0 = dbm.parse_dump('context/db-after-warmup.sql.gz')
    for sid in sys.argv[1:]:
        S = load_json(f'scenarios/{sid}.json')
        out = []
        oserve = W.Web.serve
        def serve(self, module, mi, ci, pvars, query, body, caller, headers=None):
            r = oserve(self, module, mi, ci, pvars, query, body, caller, headers)
            b = r.f.get('body') if isinstance(r, LibObj) else None
            code = r.f['status'].f.get('code') if isinstance(r, LibObj) and isinstance(r.f.get('status'), LibObj) else None
            if (isinstance(b, dict) and b.get('status') == 0) or (code and code >= 400):
                out.append(f"{'  <-' + caller.cls.name + '#' + caller.name if caller else 'ENTRY'} => {ci.name}#{mi.name} code={code} msg={b.get('msg') if isinstance(b, dict) else None}")
            return r
        W.Web.serve = serve
        it, cl, errors = run_scenario(proj, tables0, S)
        W.Web.serve = oserve
        print('=====', sid)
        for o in out: print('  ', o)
th = threading.Thread(target=main); threading.stack_size(64*1024*1024); th = threading.Thread(target=main); th.start(); th.join()
