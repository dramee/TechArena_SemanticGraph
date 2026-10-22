"""Печатает REST-обработчики сервисов: метод, путь, класс и параметры.

Запуск::

    python -m solution.tools.handlers [фрагмент имени модуля …]
"""

import sys

from .common import in_big_stack, run


def collect(filters):
    """Возвращает строки описания обработчиков."""
    it, _client, _errors = run({"id": "X", "steps": []})
    rows = []
    for module, handlers in sorted(it.web.handlers.items()):
        if filters and not any(f in module for f in filters):
            continue
        for verb, tpl, mi, ci in handlers:
            params = ", ".join(p[1] for p in mi.params)
            name = module.replace("ts-", "").replace("-service", "")
            path = "/" + "/".join(tpl)
            rows.append(
                f"{name} | {verb or '*'} | {path} | "
                f"{ci.name}#{mi.name}({params})"
            )
    return rows


def main(argv):
    """Печатает обработчики выбранных модулей."""
    for line in in_big_stack(collect, argv):
        print(line)


if __name__ == "__main__":
    main(sys.argv[1:])
