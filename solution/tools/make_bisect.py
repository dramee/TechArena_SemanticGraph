"""Бисекция лишнего ребра calls в S5: python make_bisect.py <имя> <lo> <hi>  (удаляет из S5 рёбра cands[lo:hi]).
cands = рёбра calls S5, которых нет в остальных сценариях (отсортированы), хранятся в probes/bisect_S5.json."""
import json, os, sys, zipfile
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
SUB = json.load(open(os.path.join(ROOT, "submission.json"), encoding="utf-8"))
CF = os.path.join(ROOT, "probes", "bisect_S5.json")
if not os.path.exists(CF):
    ed = lambda s: {(e["source"], e["target"]) for e in SUB["scenarios"][s]["edges"] if e["relation"] == "calls"}
    other = set()
    for s in SUB["scenarios"]:
        if s != "S5":
            other |= ed(s)
    json.dump(sorted(ed("S5") - other), open(CF, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
cands = [tuple(x) for x in json.load(open(CF, encoding="utf-8"))]
name, lo, hi = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
drop = set(cands[lo:hi])
blk = SUB["scenarios"]["S5"]["edges"]
new = [e for e in blk if not (e["relation"] == "calls" and (e["source"], e["target"]) in drop)]
SUB["scenarios"]["S5"]["edges"] = new
print(f"S5: убрано {len(blk) - len(new)} рёбер calls ([{lo}:{hi}] из {len(cands)}); calls осталось {sum(e['relation'] == 'calls' for e in new)}")
code = ["your_solution.py", "SOLUTION.md"]
for dp, dns, fns in os.walk(os.path.join(ROOT, "solution")):
    dns[:] = [d for d in dns if d != "__pycache__"]
    code += [os.path.relpath(os.path.join(dp, f), ROOT).replace(os.sep, "/") for f in fns if not f.endswith(".pyc")]
zp = os.path.join(ROOT, "probes", f"{name}.zip")
with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted(code):
        z.write(os.path.join(ROOT, f), f)
    z.writestr("submission.json", json.dumps(SUB, ensure_ascii=False))
print("->", os.path.normpath(zp))
