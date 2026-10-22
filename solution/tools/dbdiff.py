"""Печатает изменения БД после сценария.

Запуск::

    python -m solution.tools.dbdiff S1
"""

import json
import sys

from .common import in_big_stack, run, tables


def _key(row):
    return json.dumps(row, sort_keys=True, default=str)


def diff(sid):
    """Возвращает ``{таблица: (добавленные, удалённые)}``."""
    it, _client, _errors = run(sid)
    before = tables()
    out = {}
    for name, table in it.tables.items():
        old = {_key(r) for r in before[name].rows}
        new = {_key(r) for r in table.rows}
        added = [r for r in table.rows if _key(r) not in old]
        removed = [r for r in before[name].rows if _key(r) not in new]
        if added or removed:
            out[name] = (added, removed)
    return out


def main(argv):
    """Печатает изменения по таблицам."""
    for name, (added, removed) in in_big_stack(diff, argv[0]).items():
        print(f"== {name}: +{len(added)} -{len(removed)}")
        for r in added:
            print("   +", r)
        for r in removed:
            print("   -", r)


if __name__ == "__main__":
    main(sys.argv[1:])
