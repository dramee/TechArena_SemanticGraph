"""Общие функции инструментов: пути пакета задачи и запуск сценариев."""

import functools
import gzip
import json
import os
import sys
import threading
import traceback

from .. import db as dbm
from ..model import Project, load_json
from ..solve import RECURSION_LIMIT, STACK_SIZES_MB, run_scenario

ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
SKELETON = os.path.join(ROOT, "skeleton", "trainticket.json.gz")
SOURCES = os.path.join(ROOT, "targets", "trainticket")
DUMP = os.path.join(ROOT, "context", "db-after-warmup.sql.gz")
SCENARIOS = os.path.join(ROOT, "scenarios")


@functools.lru_cache(maxsize=1)
def project():
    """Возвращает разобранный проект (скелет и исходники)."""
    return Project(SKELETON, SOURCES)


@functools.lru_cache(maxsize=1)
def tables():
    """Возвращает исходное состояние БД из дампа."""
    return dbm.parse_dump(DUMP)


@functools.lru_cache(maxsize=1)
def skeleton():
    """Возвращает скелет как словарь (nodes, edges, context)."""
    with gzip.open(SKELETON, "rt", encoding="utf-8") as f:
        return json.load(f)


def scenario(sid):
    """Загружает сценарий по идентификатору (S0, S1, …)."""
    return load_json(os.path.join(SCENARIOS, sid + ".json"))


def run(sid_or_scenario):
    """Выполняет сценарий и возвращает ``(interp, client, errors)``."""
    if isinstance(sid_or_scenario, str):
        sid_or_scenario = scenario(sid_or_scenario)
    return run_scenario(project(), tables(), sid_or_scenario)


def in_big_stack(fn, *args):
    """Вызывает ``fn`` в потоке с большим стеком и возвращает результат.

    Интерпретатор рекурсивен, стека главного потока ему не хватает.
    """
    sys.setrecursionlimit(RECURSION_LIMIT)
    result, failure = [], []

    def target():
        try:
            result.append(fn(*args))
        except BaseException as exc:
            failure.append(exc)
            traceback.print_exc()

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
    return result[0]


def short(method_id):
    """Сокращает ID метода до ``Класс#метод`` для печати."""
    tail = method_id.split(":", 2)[-1]
    return tail.split("(")[0]
