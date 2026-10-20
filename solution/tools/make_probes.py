"""Диагностические сдачи: в каждом сценарии обнуляется один вид связей.

Падение балла сценария на платформе = IoU этого вида связей / 4 (если в эталоне вид не пуст).
Три файла покрывают пары «сценарий × вид» так, что по сумме (балл = среднее четырёх IoU) восстанавливается вся матрица.

    python solution/tools/make_probes.py   ->  probes/probe_A.json, probe_B.json, probe_C.json
"""
import json
import os
import zipfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
BASE = json.load(open(os.path.join(ROOT, "submission.json"), encoding="utf-8"))

# сценарий -> какой вид связей обнулить (E=executes, C=calls, R=remote, D=data)
PLANS = {
    "A": {"S1": "R", "S2": "C", "S3": "D", "S4": "E", "S5": "R", "S6": "C", "S7": "D"},
    "B": {"S1": "D", "S2": "E", "S3": "R", "S4": "C", "S5": "D", "S6": "E", "S7": "R"},
    "C": {"S1": "C", "S2": "R", "S3": "E", "S4": "D", "S5": "C", "S6": "R", "S7": "C"},
}
REL = {"E": "executes", "C": "calls", "R": "remote", "D": "data"}

CODE_FILES = ["your_solution.py", "SOLUTION.md"]
for dp, dns, fns in os.walk(os.path.join(ROOT, "solution")):
    dns[:] = [d for d in dns if d != "__pycache__"]
    for f in fns:
        if not f.endswith(".pyc"):
            CODE_FILES.append(os.path.relpath(os.path.join(dp, f), ROOT).replace(os.sep, "/"))
CODE_FILES.sort()

os.makedirs(os.path.join(ROOT, "probes"), exist_ok=True)
for name, plan in PLANS.items():
    out = {"project": BASE["project"], "scenarios": {}}
    for sid, blk in BASE["scenarios"].items():
        drop = REL.get(plan.get(sid))
        out["scenarios"][sid] = {"edges": [e for e in blk["edges"] if e["relation"] != drop]}
    path = os.path.join(ROOT, "probes", f"probe_{name}.json")
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    # zip в том же виде, что solution.zip: код решения + submission.json (здесь — диагностический)
    zpath = os.path.join(ROOT, "probes", f"probe_{name}.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in CODE_FILES:
            z.write(os.path.join(ROOT, f), f)
        z.writestr("submission.json", json.dumps(out, ensure_ascii=False))
    print(name, plan, "->", os.path.normpath(zpath))
