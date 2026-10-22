"""Общие фикстуры тестов: проект, база данных и запуск сценариев."""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from solution.solve import to_edges  # noqa: E402
from solution.tools import common  # noqa: E402


@pytest.fixture(scope="session")
def project():
    """Разобранный проект Train Ticket (один на все тесты)."""
    return common.in_big_stack(common.project)


@pytest.fixture(scope="session")
def run_steps(project):
    """Функция: список шагов -> ``(интерпретатор, клиент, ошибки)``."""

    def run(steps, sid="T"):
        scenario = {
            "id": sid,
            "steps": [{"n": i, "action": a} for i, a in enumerate(steps, 1)],
        }
        return common.in_big_stack(common.run, scenario)

    return run


@pytest.fixture(scope="session")
def answer(project):
    """Функция: идентификатор сценария -> множества рёбер ответа."""
    valid_methods = {
        k for k, n in project.nodes.items() if n["kind"] == "method"
    }
    valid_tables = set(project.tables)
    cache = {}

    def get(sid):
        if sid not in cache:
            it, _client, errors = common.in_big_stack(common.run, sid)
            edges = to_edges(sid, it.trace, valid_methods, valid_tables)
            cache[sid] = (edges, errors)
        return cache[sid]

    return get
