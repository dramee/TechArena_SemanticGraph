"""Чувствительность: что меняется в трассе, если шаг выбросить. python sens.py S1"""
import sys, os, json, copy, threading
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from solve import *
def score(a, b):
    tot = 0
    for k in ('executes', 'calls', 'remote', 'data'):
        A, B = getattr(a, k), getattr(b, k)
        tot += (len(A & B) / len(A | B)) if (A | B) else 1
    return tot / 4
def main():
    sid = sys.argv[1]
    proj = Project('skeleton/trainticket.json.gz', 'targets/trainticket')
    tables0 = dbm.parse_dump('context/db-after-warmup.sql.gz')
    S = load_json(f'scenarios/{sid}.json')
    base, _, _ = run_scenario(proj, tables0, S)
    for i, st in enumerate(S['steps']):
        S2 = copy.deepcopy(S); del S2['steps'][i]
        it, _, _ = run_scenario(proj, tables0, S2)
        print(f"{sid} step {st['n']:2d} dropped -> IoU {score(base.trace, it.trace):.3f}   {st['action'][:70]}")
th = threading.Thread(target=main); threading.stack_size(64*1024*1024); th = threading.Thread(target=main); th.start(); th.join()
