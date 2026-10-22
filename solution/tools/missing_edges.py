"""Ищет кандидатов на недостающие рёбра ``calls`` в ответе сценария.

Кандидат — пара «вызывающий → вызываемый», где оба метода исполнены, место
вызова есть в скелете, а ребра в ответе нет. Учитываются три источника:
статические рёбра ``calls``/``runtime_dispatch``, вызовы с неразрешённым
типом получателя (совпадение по имени) и полиморфные вызовы через
``implements``/``extends``. Запуск::

    python -m solution.tools.missing_edges submission.json S5
"""

import collections
import json
import re
import sys

from .common import short, skeleton


def _answer(path, sid):
    with open(path, encoding="utf-8") as f:
        block = json.load(f)["scenarios"][sid]["edges"]
    executes = {e["target"] for e in block if e["relation"] == "executes"}
    calls = {
        (e["source"], e["target"]) for e in block if e["relation"] == "calls"
    }
    return executes, calls


def _subtypes(sk):
    sub = collections.defaultdict(set)
    for e in sk["edges"]:
        if e["type"] in ("implements", "extends"):
            parent = e["target"].split(":", 2)[2]
            child = e["source"].split(":", 2)[2]
            sub[parent].add(child)

    def closure(name):
        out, todo = {name}, [name]
        while todo:
            for child in sub.get(todo.pop(), ()):
                if child not in out:
                    out.add(child)
                    todo.append(child)
        return out

    return closure


def candidates(path, sid):
    """Возвращает список ``(вызывающий, вызываемый, причина)``."""
    sk = skeleton()
    executes, calls = _answer(path, sid)
    out = set()
    for e in sk["edges"]:
        if e["type"] not in ("calls", "runtime_dispatch"):
            continue
        m = re.match(r"call:(method:[^@]*)@\d+:\d+$", e["source"])
        if m:
            pair = (m.group(1), e["target"])
            both = pair[0] in executes and pair[1] in executes
            if both and pair not in calls:
                out.add(pair + ("static",))
    by_name = collections.defaultdict(list)
    for m in executes:
        cls = m.split(":", 2)[2].split("#")[0]
        by_name[m.split("#", 1)[1].split("(")[0]].append((cls, m))
    resolved = {
        e["source"] for e in sk["edges"] if e["source"].startswith("call:")
    }
    subtypes = _subtypes(sk)
    for node_id, node in sk["nodes"].items():
        if node["kind"] != "call_site" or node["method"] not in executes:
            continue
        name, receiver = node["callee"], node.get("receiver_type")
        if name == "<init>":
            continue
        for cls, callee in by_name.get(name, ()):
            pair = (node["method"], callee)
            if pair in calls or pair[0] == pair[1]:
                continue
            if receiver is None and node_id not in resolved:
                out.add(pair + ("by-name",))
            elif receiver is not None and cls in subtypes(receiver):
                out.add(pair + ("polymorphic",))
    return sorted(out)


def main(argv):
    """Печатает кандидатов для сценария из ответа."""
    found = candidates(argv[0], argv[1])
    print(len(found), "кандидатов")
    for caller, callee, why in found:
        print(f"{short(caller)} -> {short(callee)}  [{why}]")


if __name__ == "__main__":
    main(sys.argv[1:])
