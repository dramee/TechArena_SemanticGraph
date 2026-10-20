"""Возмущения запросов: какие поля тел запросов меняют ТОЛЬКО executes/calls (не remote и не data).

Такие ветки на платформе невидимы по remote/data, а значит остаточные расхождения могут прятаться именно в них.
    python perturb.py S7 [S2 ...]
"""
import copy
import json
import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from solve import *
import scenario as SC

ALTS = [None, "", 0, "zzz"]


def sets(it):
    tr = it.trace
    ex, calls = apply_label_rules(tr)
    return {"E": ex, "C": calls, "R": set(tr.remote), "D": set(tr.data)}


def short(x):
    if isinstance(x, tuple):
        return x[0].split("#")[-1].split("(")[0] + "->" + x[1].split("#")[-1].split("(")[0]
    return x.split(":", 2)[-1].split("(")[0]


def run(proj, tables0, S, perturb):
    orig_api = SC.Client.api
    orig_step = SC.Client.step
    log = {}

    def step(self, n, text):
        self.cur_step = n
        return orig_step(self, n, text)

    def api(self, verb, path, body=None, query=None):
        n = getattr(self, "cur_step", None)
        if isinstance(body, dict):
            log.setdefault(n, [])
            log[n] = sorted(set(log[n]) | set(body.keys()))
            if perturb and perturb[0] == n and perturb[1] in body:
                body = dict(body)
                body[perturb[1]] = perturb[2]
        return orig_api(self, verb, path, body, query)

    SC.Client.api, SC.Client.step = api, step
    try:
        it, cl, errs = run_scenario(proj, tables0, S)
    finally:
        SC.Client.api, SC.Client.step = orig_api, orig_step
    return it, log


def main():
    proj = Project("skeleton/trainticket.json.gz", "targets/trainticket")
    tables0 = dbm.parse_dump("context/db-after-warmup.sql.gz")
    for sid in sys.argv[1:]:
        S = load_json(f"scenarios/{sid}.json")
        base_it, fields = run(proj, tables0, S, None)
        base = sets(base_it)
        print(f"===== {sid}: полей по шагам {sum(len(v) for v in fields.values())}")
        for n in sorted(k for k in fields if k is not None):
            for f in fields[n]:
                seen = set()
                for alt in ALTS:
                    it, _ = run(proj, tables0, S, (n, f, alt))
                    s = sets(it)
                    d = {k: (s[k] - base[k], base[k] - s[k]) for k in s}
                    key = json.dumps({k: [sorted(map(str, a)), sorted(map(str, b))] for k, (a, b) in d.items()}, sort_keys=True)
                    if key in seen:
                        continue
                    seen.add(key)
                    if not any(d[k][0] or d[k][1] for k in "EC"):
                        continue
                    flag = "ТОЛЬКО E/C" if not (d["R"][0] or d["R"][1] or d["D"][0] or d["D"][1]) else "меняет и R/D"
                    print(f"  шаг {n} поле {f}={alt!r}: {flag}: "
                          f"E+{len(d['E'][0])}/-{len(d['E'][1])} C+{len(d['C'][0])}/-{len(d['C'][1])} R+{len(d['R'][0])}/-{len(d['R'][1])} D+{len(d['D'][0])}/-{len(d['D'][1])}")
                    if flag == "ТОЛЬКО E/C":
                        for k in "EC":
                            if d[k][0]:
                                print("       +", k, [short(x) for x in sorted(d[k][0], key=str)][:4])
                            if d[k][1]:
                                print("       -", k, [short(x) for x in sorted(d[k][1], key=str)][:4])


if __name__ == "__main__":
    threading.stack_size(64 * 1024 * 1024)
    th = threading.Thread(target=main)
    th.start()
    th.join()
