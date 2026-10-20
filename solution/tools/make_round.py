"""Диагностическая сдача: в разные сценарии кладутся разные варианты гипотез (python make_round.py <имя>).

База — текущий submission_new.json (все новые правила). Для каждого сценария можно вычесть из него набор рёбер.
Падение/рост балла сценария относительно известного балла прежней сдачи показывает, верна ли гипотеза.
"""
import json
import os
import sys
import zipfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
BASE = json.load(open(os.path.join(ROOT, "submission_new.json"), encoding="utf-8"))

# имя раунда -> {сценарий: [(вид, подстрока источника/цели)]} : что убрать из базы
ROUNDS = {
    "r1": {
        "S3": [("executes", "order.entity.Order#equals")],
        "S4": [("executes", "delivery.mq.RabbitReceive#process")],
        "S6": [("executes", "order.entity.Order#equals")],
    },
}


def build(name):
    plan = ROUNDS[name]
    out = {"project": BASE["project"], "scenarios": {}}
    for sid, blk in BASE["scenarios"].items():
        drops = plan.get(sid, [])
        edges = []
        for e in blk["edges"]:
            key = e["target"] if e["relation"] == "executes" else e["source"] + " " + e["target"]
            if any(e["relation"] == rel and sub in key for rel, sub in drops):
                continue
            edges.append(e)
        out["scenarios"][sid] = {"edges": edges}
        if drops:
            print(sid, "убрано рёбер:", len(blk["edges"]) - len(edges), drops)
    code = ["your_solution.py", "SOLUTION.md"]
    for dp, dns, fns in os.walk(os.path.join(ROOT, "solution")):
        dns[:] = [d for d in dns if d != "__pycache__"]
        code += [os.path.relpath(os.path.join(dp, f), ROOT).replace(os.sep, "/") for f in fns if not f.endswith(".pyc")]
    os.makedirs(os.path.join(ROOT, "probes"), exist_ok=True)
    zpath = os.path.join(ROOT, "probes", f"{name}.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(code):
            z.write(os.path.join(ROOT, f), f)
        z.writestr("submission.json", json.dumps(out, ensure_ascii=False))
    print("->", os.path.normpath(zpath))


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "r1")
