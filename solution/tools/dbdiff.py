"""Изменения БД после сценария: python dbdiff.py S1"""
import sys, os, json, copy, threading
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from solve import *
def main():
    sid = sys.argv[1]
    proj = Project('skeleton/trainticket.json.gz', 'targets/trainticket')
    tables0 = dbm.parse_dump('context/db-after-warmup.sql.gz')
    S = load_json(f'scenarios/{sid}.json')
    it, cl, errors = run_scenario(proj, tables0, S)
    for name, t in it.tables.items():
        t0 = tables0[name]
        old = {json.dumps(r, sort_keys=True, default=str) for r in t0.rows}
        new = [r for r in t.rows if json.dumps(r, sort_keys=True, default=str) not in old]
        gone = [r for r in t0.rows if json.dumps(r, sort_keys=True, default=str) not in {json.dumps(x, sort_keys=True, default=str) for x in t.rows}]
        if new or gone:
            print(f"== {name}: +{len(new)} -{len(gone)}")
            for r in new: print("   +", {k: v for k, v in r.items()})
            for r in gone: print("   -", {k: v for k, v in r.items()})
th = threading.Thread(target=main); threading.stack_size(64*1024*1024); th = threading.Thread(target=main); th.start(); th.join()
