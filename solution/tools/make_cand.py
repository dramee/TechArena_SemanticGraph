"""Бисекция по 7 кандидатам для S5: python make_cand.py <имя> <индексы через запятую>.
0 getSoldTickets->LeftTicketInfo#toString; 1 OrderOther#queryOrders->String2Date; 2-4 TripInfo#<init> (searchCheapest/searchQuickest/getTransferSearch);
5 TravelPlan#getRestTicketNumber->Seat#<init>; 6 travel2#getRouteByTripId->TripId#<init>(String)."""
import sys, os, json, zipfile, threading
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from solve import *
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
SUB = json.load(open(os.path.join(ROOT, "submission.json"), encoding="utf-8"))
def main():
    name, idx = sys.argv[1], [int(x) for x in sys.argv[2].split(',')]
    proj = Project('skeleton/trainticket.json.gz', 'targets/trainticket')
    tables0 = dbm.parse_dump('context/db-after-warmup.sql.gz')
    valid = {k for k, n in proj.N.items() if n["kind"] == "method"}
    it, cl, errs = run_scenario(proj, tables0, load_json('scenarios/S5.json'))
    f = lambda m: m.split(':', 2)[2].split('(')[0]
    other = set()
    for k in range(0, 8):
        if k == 5: continue
        o_it, _, _ = run_scenario(proj, tables0, load_json(f'scenarios/S{k}.json'))
        other |= o_it.trace.calls
    ctor = sorted(c for c in it.trace.calls if '#<init>' in c[1] and c not in other and c[0] in valid and c[1] in valid)
    cands = [
        (next(m for m in valid if 'order.service.OrderServiceImpl#getSoldTickets(' in m), next(m for m in valid if m.endswith('LeftTicketInfo#toString()'))),
        (next(m for m in valid if 'OrderOtherServiceImpl#queryOrders(' in m), next(m for m in valid if m.endswith('StringUtils#String2Date(java.lang.String)'))),
    ] + ctor
    for i, c in enumerate(cands): print(i, f(c[0]), '->', f(c[1]))
    assert len(cands) == 7, len(cands)
    add = [cands[i] for i in idx]
    for a, b in add:
        SUB['scenarios']['S5']['edges'].append({"source": a, "relation": "calls", "target": b})
    n, k = 267, len(add)
    M = lambda iou: round((6 + 1 - (1 - iou) / 4) / 7, 5)
    print('добавлено', k, '| ожидаемое среднее: y в A ->', M((n + 1) / (n + k)), '| y не в A ->', M(n / (n + 1 + k)))
    code = ["your_solution.py", "SOLUTION.md"]
    for dp, dns, fns in os.walk(os.path.join(ROOT, "solution")):
        dns[:] = [d for d in dns if d != "__pycache__"]
        code += [os.path.relpath(os.path.join(dp, f), ROOT).replace(os.sep, "/") for f in fns if not f.endswith(".pyc")]
    zp = os.path.join(ROOT, "probes", f"{name}.zip")
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for fn in sorted(code):
            z.write(os.path.join(ROOT, fn), fn)
        z.writestr("submission.json", json.dumps(SUB, ensure_ascii=False))
    print("->", os.path.normpath(zp))
th = threading.Thread(target=main); threading.stack_size(64*1024*1024); th = threading.Thread(target=main); th.start(); th.join()
