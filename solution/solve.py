"""Точка входа решения: сценарии -> submission.json.

    python3 your_solution.py skeleton/trainticket.json.gz targets/trainticket scenarios/*.json -o submission.json
"""
import sys, os, json, copy, time, argparse, traceback, threading, collections, glob
sys.setrecursionlimit(30000)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from model import Project, load_json
from interp import Interp, Trace, OutOfFuel
from repo import Repos
from web import Web
from scenario import Client
from values import JavaThrow
import db as dbm
import config as _cfg


def run_scenario(proj, tables0, S, verbose=False):
    """Выполнить сценарий на свежей копии БД: шаги -> HTTP-запросы -> интерпретация кода сервисов."""
    tables = copy.deepcopy(tables0)
    it = Interp(proj, tables)
    Repos(it)
    Web(it)
    cl = Client(it, S)
    errors = []
    for st in S.get("steps", []):
        try:
            cl.step(st.get("n"), st.get("action", ""))
        except JavaThrow as jt:
            errors.append((st.get("n"), "JavaThrow", repr(jt.value)))
        except OutOfFuel:
            errors.append((st.get("n"), "OutOfFuel", ""))
            break
        except Exception as e:                        # ошибка в интерпретаторе: считаем шаг оборвавшимся
            errors.append((st.get("n"), type(e).__name__, str(e)[:200], getattr(e, "_where", None),
                           "".join(traceback.format_exc(limit=-3).splitlines()[-6:])[-420:]))
    if _cfg.JACKSON_CTORS_WITH_CALLS:
        merge_jackson_ctors(it)
    return it, cl, errors


def merge_jackson_ctors(it):
    """Конструктор, который создал Jackson при разборе тела запроса и который вызывает методы проекта (RebookInfo#<init> ->
    StringUtils#Date2String), в эталоне есть (как и конструкторы, созданные Hibernate); явные сеттеры/геттеры Jackson — нет."""
    jt, tr = it.json_trace, it.trace
    for a, b in jt.calls:
        if "#<init>" in a and "#<init>" not in b:
            tr.calls.add((a, b))
            tr.executes.add(a)
            if b in jt.executes:
                tr.executes.add(b)


def apply_label_rules(tr):
    """Правила разметки эталона, выведенные по диагностическим сдачам (см. config.py)."""
    calls = set(tr.calls)
    if _cfg.DROP_CTOR_CALL_TARGETS:
        calls = {c for c in calls if "#<init>" not in c[1]}
    executes = set(tr.executes)
    if _cfg.DROP_CTORS_WITHOUT_CALLS:
        callers = {c[0] for c in calls}
        executes = {m for m in executes if "#<init>" not in m or m in callers}
    return executes, calls


def to_edges(sid, tr, valid_methods, valid_tables):
    edges = []
    executes, calls = apply_label_rules(tr)
    for m in sorted(executes):
        if m in valid_methods:
            edges.append({"source": f"scenario:{sid}", "relation": "executes", "target": m})
    for a, b in sorted(calls):
        if a in valid_methods and b in valid_methods:
            edges.append({"source": a, "relation": "calls", "target": b})
    for a, b in sorted(tr.remote):
        if a in valid_methods and b in valid_methods:
            edges.append({"source": a, "relation": "remote", "target": b})
    for a, t in sorted(tr.data):
        if a in valid_methods and t in valid_tables:
            edges.append({"source": a, "relation": "data", "target": t})
    return edges


def expand_paths(patterns):
    """Раскрыть шаблоны (`scenarios/*.json`) самостоятельно: cmd.exe в Windows этого не делает. Порядок — по имени."""
    out = []
    for pat in patterns:
        found = sorted(glob.glob(pat)) if any(c in pat for c in "*?[") else [pat]
        for f in found:
            if f not in out:
                out.append(f)
    return out


def find_dump(explicit, skeleton_path):
    cands = [explicit] if explicit else []
    sk_dir = os.path.dirname(os.path.abspath(skeleton_path))
    here = os.path.dirname(os.path.abspath(__file__))
    for base in (os.path.dirname(sk_dir), sk_dir, os.getcwd(), os.path.dirname(here), here):
        cands.append(os.path.join(base, "context", "db-after-warmup.sql.gz"))
    for c in cands:
        if c and os.path.exists(c):
            return c
    raise FileNotFoundError("не найден context/db-after-warmup.sql.gz (укажите --dump)")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("skeleton")
    ap.add_argument("root", help="корень исходников проекта (targets/trainticket)")
    ap.add_argument("scenario", nargs="+")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--dump", default=None, help="SQL-дамп БД (по умолчанию context/db-after-warmup.sql.gz)")
    ap.add_argument("-v", "--verbose", action="store_true", help="журнал запросов, предупреждений и решений")
    a = ap.parse_args(argv)
    a.scenario = expand_paths(a.scenario)
    if not a.scenario:
        ap.error("не найдено ни одного файла сценария")
    t0 = time.time()
    proj = Project(a.skeleton, a.root)
    tables0 = dbm.parse_dump(find_dump(a.dump, a.skeleton))
    valid_methods = {k for k, n in proj.N.items() if n["kind"] == "method"}
    valid_tables = set(proj.tables)
    out = {"project": proj.sk["project"], "scenarios": {}}
    for path in a.scenario:
        S = load_json(path)
        sid = S["id"]
        try:
            it, cl, errors = run_scenario(proj, tables0, S, a.verbose)
            edges = to_edges(sid, it.trace, valid_methods, valid_tables)
        except Exception:
            traceback.print_exc()
            it, cl, errors, edges = None, None, [], []
        out["scenarios"][sid] = {"edges": edges}
        if it is not None:
            tr = it.trace
            print(f"{sid}: executes {len(tr.executes)} calls {len(tr.calls)} remote {len(tr.remote)} data {len(tr.data)}"
                  f"  (ошибок интерпретатора: {len(errors)})")
            if a.verbose:
                for l in cl.log:
                    print("   ", l)
                for e in errors:
                    print("   ERR", e)
                print("   warnings", dict(it.warnings))
                for e in it.exc_log[:20]:
                    print("   EXC", e)
                for e in it.auth_log[:20]:
                    print("   AUTH-DENIED", e)
                dec = collections.Counter((k[0].split('/')[-1], k[1], d, txt) for k, d, txt in it.decisions)
                for k, c in dec.most_common(40):
                    print("   decision", k, c)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"готово за {time.time() - t0:.1f} с -> {a.out}")


def run_main(argv=None):
    """Запуск в потоке с большим стеком (глубокая рекурсия интерпретатора)."""
    err = []

    def target():
        try:
            main(argv)
        except SystemExit as e:
            err.append(e)
        except BaseException:
            traceback.print_exc()
            err.append(SystemExit(1))
    for size in (256, 128, 64, 32):
        try:
            threading.stack_size(size * 1024 * 1024)
            break
        except (ValueError, RuntimeError):
            continue
    th = threading.Thread(target=target)
    th.start()
    th.join()
    if err:
        raise err[0]


if __name__ == "__main__":
    run_main()
