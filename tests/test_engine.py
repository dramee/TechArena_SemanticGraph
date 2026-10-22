"""Разбор Java и интерпретатор на всём коде проекта."""

import collections
import os
import subprocess
import sys

from solution import jparse
from solution.tools import common
from solution.tools.compare import compare
from solution.values import JMap, LibObj


def test_all_java_files_parse(project):
    assert project.parsed
    for path in project.parsed:
        assert path.endswith(".java")


def test_call_sites_match_skeleton(project):
    """Позиции вызовов разборщика совпадают с вершинами call_site скелета."""
    mine = collections.defaultdict(set)

    def collect(node, path, depth=0):
        if depth > 300:
            return
        if isinstance(node, (jparse.Call, jparse.New)):
            mine[path].add((node.line, node.col))
        if isinstance(node, jparse.Node):
            for slot in node.__slots__:
                if slot in ("outer", "cls"):
                    continue
                collect(getattr(node, slot), path, depth + 1)
        elif isinstance(node, (list, tuple)):
            for x in node:
                collect(x, path, depth + 1)

    for path, (_parser, types) in project.parsed.items():
        collect(types, path)
    sites = [n for n in project.nodes.values() if n["kind"] == "call_site"]
    matched = sum((n["line"], n["col"]) in mine[n["file"]] for n in sites)
    assert matched / len(sites) > 0.99


def test_every_handler_runs_without_interpreter_errors(project):
    """Каждый REST-обработчик выполняется с типовыми аргументами."""

    def fuzz():
        it, _client, _errors = common.run({"id": "F", "steps": []})
        web = it.web
        web.enforce_auth = False
        user = "4d2a46c7-71cb-4cf1-b5bb-b68406d9da6f"
        failures = []
        for module in sorted(web.handlers):
            for verb, tpl, mi, ci in web.handlers[module]:
                pvars = {}
                for seg in tpl:
                    if seg.startswith("{"):
                        name = seg[1:-1].split(":")[0]
                        low = name.lower()
                        if "ccount" in name or "user" in low:
                            pvars[name] = user
                        elif "trip" in low:
                            pvars[name] = "D1345"
                        else:
                            pvars[name] = "shanghai"
                path = "/" + "/".join(
                    (
                        pvars.get(s[1:-1].split(":")[0], s)
                        if s.startswith("{")
                        else s
                    )
                    for s in tpl
                )
                it.trace = type(it.trace)()
                it.fuel = 400_000
                headers = LibObj("HttpHeaders", map=JMap())
                try:
                    web.serve(
                        module,
                        mi,
                        ci,
                        pvars,
                        {},
                        JMap(),
                        None,
                        headers,
                        path,
                        verb or "GET",
                    )
                except Exception as exc:
                    failures.append(f"{ci.name}#{mi.name}: {exc!r}")
        return failures

    assert common.in_big_stack(fuzz) == []


def test_cli_writes_valid_submission(tmp_path):
    """Командная строка строит ответ по образцу из README."""
    out = tmp_path / "answer.json"
    cmd = [
        sys.executable,
        os.path.join(common.ROOT, "your_solution.py"),
        common.SKELETON,
        common.SOURCES,
        os.path.join(common.SCENARIOS, "S0.json"),
        "-o",
        str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True, cwd=common.ROOT)
    gold = os.path.join(common.ROOT, "gold", "S0.json")
    per_relation, score = compare(str(out), gold)["S0"]
    assert score == 1.0, per_relation
