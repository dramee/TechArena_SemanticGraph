"""Печатает дерево вызовов методов по шагам сценария.

Запуск::

    python -m solution.tools.flow S1 [номер шага | all] [глубина]
"""

import sys

from .. import interp, web
from ..scenario import Client
from .common import in_big_stack, run


def collect(sid, max_depth):
    """Выполняет сценарий и возвращает строки дерева вызовов."""
    out = []
    orig_invoke = interp.Interp.invoke
    orig_serve = web.Web.serve
    orig_step = Client.step

    def invoke(self, mi, this, args, caller):
        depth = len(self.stack)
        if depth <= max_depth:
            module = mi.cls.module.replace("ts-", "").replace("-service", "")
            out.append("  " * depth + f"{mi.cls.name}#{mi.name}  [{module}]")
        return orig_invoke(self, mi, this, args, caller)

    def serve(self, module, mi, ci, *args, **kwargs):
        indent = "  " * len(self.it.stack)
        out.append(f"{indent}==> REMOTE {module} {ci.name}#{mi.name}")
        return orig_serve(self, module, mi, ci, *args, **kwargs)

    def step(self, n, text):
        out.append(f"##### STEP {n}: {text}")
        result = orig_step(self, n, text)
        out.append("  -> " + str(self.log[-1] if self.log else None)[:200])
        return result

    interp.Interp.invoke = invoke
    web.Web.serve = serve
    Client.step = step
    try:
        run(sid)
    finally:
        interp.Interp.invoke = orig_invoke
        web.Web.serve = orig_serve
        Client.step = orig_step
    return out


def main(argv):
    """Разбирает аргументы и печатает дерево."""
    sid = argv[0]
    which = argv[1] if len(argv) > 1 else "all"
    max_depth = int(argv[2]) if len(argv) > 2 else 99
    lines = in_big_stack(collect, sid, max_depth)
    text = "\n".join(lines)
    if which != "all":
        parts = text.split("##### STEP ")
        text = "\n".join(
            "##### STEP " + p for p in parts if p.startswith(which + ":")
        )
    print(text)


if __name__ == "__main__":
    main(sys.argv[1:])
