"""Проба r3: в S2 и S7 добавляется Jackson-конструктор RebookInfo#<init> (executes) и ребро calls -> StringUtils#Date2String.
База sub_n2.json; остальные сценарии не меняются (контроль)."""
import json, os, zipfile
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
BASE = json.load(open(os.path.join(ROOT, "sub_n2.json"), encoding="utf-8"))
CTOR = "method:ts-rebook-service:rebook.entity.RebookInfo#<init>()"
D2S = "method:ts-common:edu.fudan.common.util.StringUtils#Date2String(java.util.Date)"
for sid in ("S2", "S7"):
    ed = BASE["scenarios"][sid]["edges"]
    ed.append({"source": f"scenario:{sid}", "relation": "executes", "target": CTOR})
    ed.append({"source": CTOR, "relation": "calls", "target": D2S})
code = ["your_solution.py", "SOLUTION.md"]
for dp, dns, fns in os.walk(os.path.join(ROOT, "solution")):
    dns[:] = [d for d in dns if d != "__pycache__"]
    code += [os.path.relpath(os.path.join(dp, f), ROOT).replace(os.sep, "/") for f in fns if not f.endswith(".pyc")]
zp = os.path.join(ROOT, "probes", "r3.zip")
with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted(code):
        z.write(os.path.join(ROOT, f), f)
    z.writestr("submission.json", json.dumps(BASE, ensure_ascii=False))
print("->", os.path.normpath(zp))
