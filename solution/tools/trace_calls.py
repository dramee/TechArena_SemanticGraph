"""Печатает вызовы заданного метода в сценарии: аргументы и результат.

Запуск::

    python -m solution.tools.trace_calls S5 OrderServiceImpl#getSoldTickets
"""

import sys

from .. import interp
from .common import in_big_stack, run


def _show(value):
    return value.f if hasattr(value, "f") else value


def collect(sid, target):
    """Выполняет сценарий и возвращает строки о вызовах метода."""
    cls_name, method_name = target.split("#")
    out = []
    orig_invoke = interp.Interp.invoke

    def invoke(self, mi, this, args, caller):
        hit = mi.name == method_name and mi.cls.name == cls_name
        if hit:
            src = caller.id.split("#")[-1] if caller else None
            out.append(f"CALL {target} {[_show(a) for a in args]} from {src}")
        result = orig_invoke(self, mi, this, args, caller)
        if hit:
            out.append("   -> " + str(_show(result))[:300])
        return result

    interp.Interp.invoke = invoke
    try:
        run(sid)
    finally:
        interp.Interp.invoke = orig_invoke
    return out


def main(argv):
    """Печатает вызовы метода ``Класс#метод`` в сценарии."""
    for line in in_big_stack(collect, argv[0], argv[1]):
        print(line)


if __name__ == "__main__":
    main(sys.argv[1:])
