"""Точка входа решения: сценарии превращаются в ``submission.json``.

Запуск::

    python3 your_solution.py skeleton/trainticket.json.gz \
        targets/trainticket scenarios/*.json -o submission.json
"""

import argparse
import collections
import copy
import glob
import json
import os
import sys
import threading
import time
import traceback

from . import config as _cfg
from . import db as dbm
from .context import RunContext
from .interp import Interp, OutOfFuel
from .model import Project, load_json
from .repo import Repos
from .scenario import Client
from .values import JavaThrow
from .web import Web

# Глубина рекурсии Python для интерпретатора Java (вложенные вызовы и AST).
RECURSION_LIMIT = 30000

# Размеры стека потока интерпретатора в МБ: первый поддерживаемый ОС.
STACK_SIZES_MB = (256, 128, 64, 32)

# Предел вызовов методов на шаг: защита от бесконечного цикла в одном шаге.
FUEL_PER_STEP = 4_000_000

DUMP_NAME = os.path.join("context", "db-after-warmup.sql.gz")


def run_scenario(proj, tables0, scenario, verbose=False):
    """Выполняет сценарий на свежей копии БД.

    Шаги превращаются в HTTP-запросы, код сервисов интерпретируется.
    Возвращает ``(интерпретатор, клиент, ошибки интерпретатора)``.
    """
    tables = copy.deepcopy(tables0)
    it = Interp(proj, tables)
    it.now = RunContext.from_skeleton(proj.sk.get("context")).now
    Repos(it)
    Web(it)
    client = Client(it, scenario)
    errors = []
    for st in scenario.get("steps", []):
        n = st.get("n")
        it.fuel = FUEL_PER_STEP
        try:
            client.step(n, st.get("action", ""))
        except JavaThrow as jt:
            errors.append((n, "JavaThrow", repr(jt.value)))
        except OutOfFuel:
            errors.append((n, "OutOfFuel", ""))
        except Exception as e:
            # Ошибка самого интерпретатора: шаг считается оборвавшимся.
            tail = traceback.format_exc(limit=-3).splitlines()[-6:]
            errors.append(
                (
                    n,
                    type(e).__name__,
                    str(e)[:200],
                    getattr(e, "_where", None),
                    "".join(tail)[-420:],
                )
            )
    if _cfg.JACKSON_CTORS_WITH_CALLS:
        merge_jackson_ctors(it)
    return it, client, errors


def merge_jackson_ctors(it):
    """Добавляет в трассу конструкторы, созданные Jackson.

    Конструктор объекта из тела запроса, вызывающий методы проекта
    (``RebookInfo#<init>`` → ``StringUtils#Date2String``), в эталоне есть,
    как и конструкторы, созданные Hibernate. Явные сеттеры и геттеры,
    вызванные Jackson, в эталон не входят.
    """
    jt, tr = it.json_trace, it.trace
    for a, b in jt.calls:
        if "#<init>" in a and "#<init>" not in b:
            tr.calls.add((a, b))
            tr.executes.add(a)
            if b in jt.executes:
                tr.executes.add(b)


def apply_label_rules(tr):
    """Применяет правила разметки эталона (см. ``config.py``).

    Возвращает множества ``executes`` и ``calls`` после правил.
    """
    calls = set(tr.calls)
    if _cfg.DROP_CTOR_CALL_TARGETS:
        calls = {c for c in calls if "#<init>" not in c[1]}
    executes = set(tr.executes)
    if _cfg.DROP_CTORS_WITHOUT_CALLS:
        callers = {c[0] for c in calls}
        executes = {m for m in executes if "#<init>" not in m or m in callers}
    return executes, calls


def to_edges(sid, tr, valid_methods, valid_tables):
    """Переводит трассу в список рёбер ответа с ID из скелета."""
    edges = []
    executes, calls = apply_label_rules(tr)
    for m in sorted(executes):
        if m in valid_methods:
            edges.append(
                {
                    "source": f"scenario:{sid}",
                    "relation": "executes",
                    "target": m,
                }
            )
    for relation, pairs in (("calls", calls), ("remote", tr.remote)):
        for a, b in sorted(pairs):
            if a in valid_methods and b in valid_methods:
                edges.append({"source": a, "relation": relation, "target": b})
    for a, t in sorted(tr.data):
        if a in valid_methods and t in valid_tables:
            edges.append({"source": a, "relation": "data", "target": t})
    return edges


def expand_paths(patterns):
    """Раскрывает шаблоны вроде ``scenarios/*.json`` в порядке имён.

    Нужно для Windows: cmd.exe не раскрывает шаблоны сам.
    """
    out = []
    for pat in patterns:
        if any(c in pat for c in "*?["):
            found = sorted(glob.glob(pat))
        else:
            found = [pat]
        for f in found:
            if f not in out:
                out.append(f)
    return out


def find_dump(explicit, skeleton_path):
    """Находит дамп БД: явно указанный или рядом со скелетом и решением."""
    candidates = [explicit] if explicit else []
    sk_dir = os.path.dirname(os.path.abspath(skeleton_path))
    here = os.path.dirname(os.path.abspath(__file__))
    for base in (
        os.path.dirname(sk_dir),
        sk_dir,
        os.getcwd(),
        os.path.dirname(here),
        here,
    ):
        candidates.append(os.path.join(base, DUMP_NAME))
    for c in candidates:
        if c and os.path.exists(c):
            return c
    raise FileNotFoundError(f"не найден {DUMP_NAME} (укажите --dump)")


def _print_verbose(it, client, errors):
    for entry in client.log:
        print("   ", entry)
    for e in errors:
        print("   ERR", e)
    print("   warnings", dict(it.warnings))
    for e in it.exc_log[:20]:
        print("   EXC", e)
    for e in it.auth_log[:20]:
        print("   AUTH-DENIED", e)
    decisions = collections.Counter(
        (k[0].split("/")[-1], k[1], d, txt) for k, d, txt in it.decisions
    )
    for k, c in decisions.most_common(40):
        print("   decision", k, c)


def _parse_args(argv):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("skeleton")
    ap.add_argument(
        "root", help="корень исходников проекта (targets/trainticket)"
    )
    ap.add_argument("scenario", nargs="+")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument(
        "--dump", default=None, help=f"SQL-дамп БД (по умолчанию {DUMP_NAME})"
    )
    ap.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="журнал запросов, предупреждений и решений",
    )
    args = ap.parse_args(argv)
    args.scenario = expand_paths(args.scenario)
    if not args.scenario:
        ap.error("не найдено ни одного файла сценария")
    return args


def main(argv=None):
    """Строит ответ для всех сценариев и пишет его в файл."""
    args = _parse_args(argv)
    t0 = time.time()
    proj = Project(args.skeleton, args.root)
    tables0 = dbm.parse_dump(find_dump(args.dump, args.skeleton))
    valid_methods = {k for k, n in proj.nodes.items() if n["kind"] == "method"}
    valid_tables = set(proj.tables)
    out = {"project": proj.sk["project"], "scenarios": {}}
    for path in args.scenario:
        scenario = load_json(path)
        sid = scenario.get("id") or os.path.splitext(os.path.basename(path))[0]
        try:
            it, client, errors = run_scenario(
                proj, tables0, scenario, args.verbose
            )
            edges = to_edges(sid, it.trace, valid_methods, valid_tables)
        except Exception:
            traceback.print_exc()
            it, client, errors, edges = None, None, [], []
        out["scenarios"][sid] = {"edges": edges}
        if it is None:
            continue
        tr = it.trace
        print(
            f"{sid}: executes {len(tr.executes)} calls {len(tr.calls)} "
            f"remote {len(tr.remote)} data {len(tr.data)}  "
            f"(ошибок интерпретатора: {len(errors)})"
        )
        if args.verbose:
            _print_verbose(it, client, errors)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"готово за {time.time() - t0:.1f} с -> {args.out}")


def run_main(argv=None):
    """Запускает ``main`` в потоке с большим стеком.

    Интерпретатор рекурсивен, поэтому ему нужен стек больше стандартного.
    """
    sys.setrecursionlimit(RECURSION_LIMIT)
    failure = []

    def target():
        try:
            main(argv)
        except SystemExit as e:
            failure.append(e)
        except BaseException:
            traceback.print_exc()
            failure.append(SystemExit(1))

    for size in STACK_SIZES_MB:
        try:
            threading.stack_size(size * 1024 * 1024)
            break
        except (ValueError, RuntimeError):
            continue
    th = threading.Thread(target=target)
    th.start()
    th.join()
    if failure:
        raise failure[0]
