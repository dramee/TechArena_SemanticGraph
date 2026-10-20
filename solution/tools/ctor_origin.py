"""Происхождение конструкторов в трассе и предсказанные IoU при разных гипотезах исключения."""
import sys, os, json, threading
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from solve import *
MEAS = {1:(0.904,0.948),2:(0.920,0.956),3:(0.908,0.956),4:(0.908,0.944),5:(0.924,0.940),6:(0.928,0.944),7:(0.916,0.956)}
def iou(P, G): return len(P & G) / len(P | G) if (P | G) else 1.0
def main():
    proj = Project('skeleton/trainticket.json.gz', 'targets/trainticket')
    tables0 = dbm.parse_dump('context/db-after-warmup.sql.gz')
    for k in range(1, 8):
        S = load_json(f'scenarios/S{k}.json')
        it, cl, errs = run_scenario(proj, tables0, S)
        tr = it.trace
        init = {m for m in tr.executes if '#<init>' in m}
        org = {m: tr.exec_origin[m] for m in init}
        hib_only = {m for m, o in org.items() if o == {'hib'}}
        new_any = {m for m, o in org.items() if 'new' in o or 'call' in o}
        calls_to_init = {c for c in tr.calls if '#<init>' in c[1]}
        calls_from_init = {c for c in tr.calls if '#<init>' in c[0]}
        # гипотезы: что исключено из НАШЕГО множества, чтобы получить «эталон»
        H = {
          'V0 как есть': (set(), set()),
          'V1 без всех <init>/calls к и от <init>': (init, calls_to_init | calls_from_init),
          'V2 без <init>, запущенных через new; calls к <init>': (new_any, calls_to_init),
          'V3 без всех <init>, calls только К <init>': (init, calls_to_init),
          'V4 без <init> new и calls к <init>, calls ИЗ <init> этих тоже': (new_any, calls_to_init | {c for c in calls_from_init if c[0] in new_any}),
        }
        line = []
        for name, (ex_rm, calls_rm) in H.items():
            E = iou(tr.executes, tr.executes - ex_rm); C = iou(tr.calls, tr.calls - calls_rm)
            line.append(f"{name[:2]} E={E:.3f} C={C:.3f}")
        print(f"S{k}: измерено E={MEAS[k][0]} C={MEAS[k][1]} | init={len(init)} (hib-only {len(hib_only)}, new/call {len(new_any)}), к<init>={len(calls_to_init)}, из<init>={len(calls_from_init)}")
        print("      " + " | ".join(line))
th = threading.Thread(target=main); threading.stack_size(64*1024*1024); th = threading.Thread(target=main); th.start(); th.join()
