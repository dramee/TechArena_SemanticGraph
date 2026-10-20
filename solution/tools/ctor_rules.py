"""Какое правило отбора конструкторов лучше всего объясняет измеренные E и C."""
import sys, os, json, threading
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from solve import *
MEAS = {1:(0.904,0.948),2:(0.920,0.956),3:(0.908,0.956),4:(0.908,0.944),5:(0.924,0.940),6:(0.928,0.944),7:(0.916,0.956)}
def iou(P, G): return len(P & G) / len(P | G) if (P | G) else 1.0
def main():
    proj = Project('skeleton/trainticket.json.gz', 'targets/trainticket')
    tables0 = dbm.parse_dump('context/db-after-warmup.sql.gz')
    show = True
    for k in range(1, 8):
        S = load_json(f'scenarios/S{k}.json')
        it, cl, errs = run_scenario(proj, tables0, S)
        tr = it.trace
        init = {m for m in tr.executes if '#<init>' in m}
        callers = {c[0] for c in tr.calls}
        keep_calling = {m for m in init if m in callers}
        keep_hib = {m for m, o in ((m, tr.exec_origin[m]) for m in init) if 'hib' in o}
        calls_to_init = {c for c in tr.calls if '#<init>' in c[1]}
        rules = {
            'R1 оставить <init> с исходящими calls': init - keep_calling,
            'R2 оставить Hibernate-созданные': init - keep_hib,
            'R3 оставить Hibernate-созданные и с calls': init - keep_hib - keep_calling,
        }
        out = []
        for n, rm in rules.items():
            out.append(f"{n[:2]} E={iou(tr.executes, tr.executes - rm):.3f}(-{len(rm)})")
        print(f"S{k}: измерено E={MEAS[k][0]} | " + " | ".join(out))
        if show:
            show = False
            mp = lambda m: m.split(':', 2)[2][:80]
            print("   с исходящими calls:", sorted(mp(m) for m in keep_calling))
            print("   только Hibernate:", sorted(mp(m) for m in keep_hib))
            print("   остальные:", sorted(mp(m) for m in init - keep_calling - keep_hib))
th = threading.Thread(target=main); threading.stack_size(64*1024*1024); th = threading.Thread(target=main); th.start(); th.join()
