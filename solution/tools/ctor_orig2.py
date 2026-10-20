import sys, os, threading
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from solve import *
def main():
    proj = Project('skeleton/trainticket.json.gz', 'targets/trainticket')
    tables0 = dbm.parse_dump('context/db-after-warmup.sql.gz')
    for k in range(0, 8):
        S = load_json(f'scenarios/S{k}.json')
        it, cl, errs = run_scenario(proj, tables0, S)
        tr = it.trace
        ex, calls = apply_label_rules(tr)
        print(f"S{k}:", {m.split(':',2)[1].split('#')[0].split('.')[-2:][0]+'.'+m.split('#')[0].split('.')[-1]: sorted(tr.exec_origin.get(m,[])) for m in ex if '#<init>' in m})
th = threading.Thread(target=main); threading.stack_size(64*1024*1024); th = threading.Thread(target=main); th.start(); th.join()
