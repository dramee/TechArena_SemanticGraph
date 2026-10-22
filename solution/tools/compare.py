"""Сравнивает два ответа (или ответ с эталоном) по каждому виду связи.

IoU считается так же, как на платформе: для каждого сценария и вида связи
отношение пересечения множеств рёбер к их объединению. Запуск::

    python -m solution.tools.compare submission.json gold/S0.json
"""

import json
import sys

RELATIONS = ("executes", "calls", "remote", "data")


def _gold_sets(sid, block):
    """Множества рёбер из файла эталона (поля methods/calls/remote/data)."""
    sets = {"executes": {(f"scenario:{sid}", m) for m in block["methods"]}}
    for rel in ("calls", "remote", "data"):
        sets[rel] = {tuple(pair) for pair in block.get(rel, ())}
    return sets


def edge_sets(path):
    """Возвращает ``{сценарий: {вид связи: множество рёбер}}``.

    Понимает и формат сдачи (``edges``), и формат эталона ``gold/S0.json``.
    """
    with open(path, encoding="utf-8") as f:
        scenarios = json.load(f)["scenarios"]
    out = {}
    for sid, block in scenarios.items():
        if "edges" not in block:
            out[sid] = _gold_sets(sid, block)
            continue
        sets = {rel: set() for rel in RELATIONS}
        for e in block["edges"]:
            sets.setdefault(e["relation"], set()).add(
                (e["source"], e["target"])
            )
        out[sid] = sets
    return out


def iou(predicted, gold):
    """Возвращает IoU двух множеств (1.0 для двух пустых)."""
    union = predicted | gold
    return len(predicted & gold) / len(union) if union else 1.0


def compare(first, second):
    """Возвращает ``{сценарий: ({вид: IoU}, балл сценария)}``."""
    a, b = edge_sets(first), edge_sets(second)
    out = {}
    for sid in sorted(set(a) & set(b)):
        per_rel = {rel: iou(a[sid][rel], b[sid][rel]) for rel in RELATIONS}
        out[sid] = (per_rel, sum(per_rel.values()) / len(RELATIONS))
    return out


def main(argv):
    """Печатает IoU по сценариям и видам связей."""
    for sid, (per_rel, score) in compare(argv[0], argv[1]).items():
        parts = " ".join(f"{rel}={v:.4f}" for rel, v in per_rel.items())
        print(f"{sid}: {score:.4f}  {parts}")


if __name__ == "__main__":
    main(sys.argv[1:])
