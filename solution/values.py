"""Значения времени выполнения интерпретатора."""
import datetime, itertools


class _Unknown:
    """Неизвестное значение: результат всего, что интерпретатор не смог вычислить."""
    __slots__ = ()

    def __repr__(self):
        return "UNK"

    def __bool__(self):          # защита: неявное приведение к bool запрещено
        raise TypeError("UNK в булевом контексте")


UNK = _Unknown()


class JObj:
    """Экземпляр проектного класса (сущность, DTO, сервис ...)."""
    __slots__ = ("cls", "f", "tag", "__weakref__")

    def __init__(self, cls, fields=None):
        self.cls = cls
        self.f = fields if fields is not None else {}
        self.tag = None                      # служебные пометки (источник загрузки, ленивые коллекции ...)

    def __repr__(self):
        return f"{self.cls.name}{{" + ", ".join(f"{k}={_short(v)}" for k, v in list(self.f.items())[:6]) + "}"


def _short(v):
    s = repr(v)
    return s if len(s) < 40 else s[:37] + "..."


class JEnum:
    __slots__ = ("cls", "name", "ordinal", "f")

    def __init__(self, cls, name, ordinal, fields=None):
        self.cls, self.name, self.ordinal = cls, name, ordinal
        self.f = fields if fields is not None else {}

    def __repr__(self):
        return f"{self.cls.name}.{self.name}"


class LibObj:
    """Объект библиотечного класса без собственной логики: HttpHeaders, Logger ..."""
    __slots__ = ("kind", "f")

    def __init__(self, kind, **kw):
        self.kind = kind
        self.f = kw

    def __repr__(self):
        return f"Lib<{self.kind}>"


class JList(list):
    pass


class JSet(dict):
    """LinkedHashSet: ключи словаря."""
    pass


class JMap(dict):
    pass


class JOpt:
    __slots__ = ("v",)

    def __init__(self, v):
        self.v = v

    def __repr__(self):
        return f"Optional[{self.v!r}]"


class JDate:
    __slots__ = ("dt",)

    def __init__(self, dt):
        self.dt = dt

    def __repr__(self):
        return f"Date({self.dt:%Y-%m-%d %H:%M:%S})"


class JCal:
    __slots__ = ("dt",)

    def __init__(self, dt):
        self.dt = dt


class JLambda:
    __slots__ = ("params", "body", "env", "frame")

    def __init__(self, params, body, env, frame):
        self.params, self.body, self.env, self.frame = params, body, env, frame


class JMethodRef:
    __slots__ = ("obj", "name", "tname")

    def __init__(self, obj, name, tname=None):
        self.obj, self.name, self.tname = obj, name, tname


class JClass:
    """Class-литерал / результат getClass()."""
    __slots__ = ("ci", "name")

    def __init__(self, ci, name=None):
        self.ci, self.name = ci, name or (ci.name if ci else "?")


class JavaThrow(Exception):
    def __init__(self, value):
        self.value = value


class ReturnEx(Exception):
    def __init__(self, value):
        self.value = value


class BreakEx(Exception):
    def __init__(self, label=None):
        self.label = label


class ContinueEx(Exception):
    def __init__(self, label=None):
        self.label = label


_uuid_counter = itertools.count(1)


def fake_uuid():
    n = next(_uuid_counter)
    return "00000000-0000-4000-8000-%012d" % n


NOW = datetime.datetime(2026, 9, 15, 8, 5, 0)


class _NotFound:
    def __repr__(self):
        return "NOTFOUND"


NOTFOUND = _NotFound()
