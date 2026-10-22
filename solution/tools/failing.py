"""Печатает внутренние вызовы сервисов, закончившиеся отказом.

Отказ — ответ ``status = 0`` или HTTP-код от 400. Запуск::

    python -m solution.tools.failing S1 [S2 …]
"""

import sys

from .. import web
from ..values import LibObj
from .common import in_big_stack, run


def collect(sid):
    """Выполняет сценарий и возвращает строки с отказами."""
    out = []
    orig_serve = web.Web.serve

    def serve(self, module, mi, ci, pvars, query, body, caller, *rest):
        r = orig_serve(self, module, mi, ci, pvars, query, body, caller, *rest)
        resp_body = r.f.get("body") if isinstance(r, LibObj) else None
        status = r.f.get("status") if isinstance(r, LibObj) else None
        code = status.f.get("code") if isinstance(status, LibObj) else None
        failed_body = (
            isinstance(resp_body, dict) and resp_body.get("status") == 0
        )
        if failed_body or (code and code >= 400):
            src = "ENTRY"
            if caller:
                src = f"<- {caller.cls.name}#{caller.name}"
            msg = resp_body.get("msg") if isinstance(resp_body, dict) else None
            out.append(f"{src} => {ci.name}#{mi.name} code={code} msg={msg}")
        return r

    web.Web.serve = serve
    try:
        run(sid)
    finally:
        web.Web.serve = orig_serve
    return out


def main(argv):
    """Печатает отказы для каждого сценария из аргументов."""
    for sid in argv:
        print("=====", sid)
        for line in in_big_stack(collect, sid):
            print("  ", line)


if __name__ == "__main__":
    main(sys.argv[1:])
