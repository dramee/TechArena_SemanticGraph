"""Методы проекта, исполняемые разбором/сериализацией Jackson и вызывающие методы проекта (кандидаты в эталон)."""
import sys, os, threading
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from solve import *
def main():
    proj = Project('skeleton/trainticket.json.gz', 'targets/trainticket')
    tables0 = dbm.parse_dump('context/db-after-warmup.sql.gz')
    for k in range(0, 8):
        S = load_json(f'scenarios/S{k}.json')
        it, cl, errs = run_scenario(proj, tables0, S)
        jt = it.json_trace
        srcs = {c[0] for c in jt.calls}
        main_ex, main_calls = it.trace.executes, it.trace.calls
        new_ex = sorted(m for m in srcs if m not in main_ex)
        new_calls = sorted(c for c in jt.calls if c not in main_calls and '#<init>' not in c[1])
        f = lambda m: m.split(':', 2)[2].split('(')[0]
        print(f"S{k}: executes +{len(new_ex)} {[f(m) for m in new_ex]}")
        print(f"      calls +{len(new_calls)} {[f(a).split('.')[-1] + '->' + f(b).split('.')[-1] for a, b in new_calls]}")
th = threading.Thread(target=main); threading.stack_size(64*1024*1024); th = threading.Thread(target=main); th.start(); th.join()
