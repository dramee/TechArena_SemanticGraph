"""Значения времени выполнения интерпретатора Java."""

import datetime

# Системное время прогона по умолчанию (уточняется контекстом скелета).
NOW = datetime.datetime(2026, 9, 15, 8, 5, 0)


class _Unknown:
    """Неизвестное значение: всё, что интерпретатор не смог вычислить."""

    __slots__ = ()

    def __repr__(self):
        return "UNK"

    def __bool__(self):
        # Неявное приведение к bool запрещено: условие над UNK решается
        # отдельно (эвристикой), а не случайно.
        raise TypeError("UNK в булевом контексте")


UNK = _Unknown()


class _NotFound:
    """Признак «поле или метод не найден» (отличается от ``None``)."""

    __slots__ = ()

    def __repr__(self):
        return "NOTFOUND"


NOTFOUND = _NotFound()


def _short(v):
    s = repr(v)
    return s if len(s) < 40 else s[:37] + "..."


class JObj:
    """Экземпляр проектного класса: сущность, DTO, сервис и т. п."""

    __slots__ = ("cls", "f", "tag", "__weakref__")

    def __init__(self, cls, fields=None):
        """Создаёт объект класса ``cls`` с полями ``fields``."""
        self.cls = cls
        self.f = fields if fields is not None else {}
        # Служебные пометки: источник загрузки, ленивые коллекции и т. п.
        self.tag = None

    def __repr__(self):
        """Возвращает имя класса и первые поля."""
        fields = ", ".join(
            f"{k}={_short(v)}" for k, v in list(self.f.items())[:6]
        )
        return f"{self.cls.name}{{{fields}}}"


class JEnum:
    """Константа перечисления проекта."""

    __slots__ = ("cls", "name", "ordinal", "f")

    def __init__(self, cls, name, ordinal, fields=None):
        """Создаёт константу ``name`` с порядковым номером ``ordinal``."""
        self.cls, self.name, self.ordinal = cls, name, ordinal
        self.f = fields if fields is not None else {}

    def __repr__(self):
        """Возвращает ``Класс.КОНСТАНТА``."""
        return f"{self.cls.name}.{self.name}"


class LibObj:
    """Объект библиотечного класса без своей логики (HttpHeaders и т. п.)."""

    __slots__ = ("kind", "f")

    def __init__(self, kind, **kw):
        """Создаёт объект вида ``kind`` с полями из именованных аргументов."""
        self.kind = kind
        self.f = kw

    def __repr__(self):
        """Возвращает вид объекта."""
        return f"Lib<{self.kind}>"


class JList(list):
    """Список Java (ArrayList, LinkedList, массив)."""


class JSet(dict):
    """Множество Java с порядком добавления (LinkedHashSet): ключи словаря."""


class JMap(dict):
    """Отображение Java (HashMap, LinkedHashMap) и JSON-объект."""


class JOpt:
    """Значение ``java.util.Optional``."""

    __slots__ = ("v",)

    def __init__(self, v):
        """Создаёт Optional со значением ``v`` (``None`` — пустой)."""
        self.v = v

    def __repr__(self):
        """Возвращает ``Optional[значение]``."""
        return f"Optional[{self.v!r}]"


class JDate:
    """Значение ``java.util.Date``."""

    __slots__ = ("dt",)

    def __init__(self, dt):
        """Создаёт дату из ``datetime``."""
        self.dt = dt

    def __repr__(self):
        """Возвращает дату в формате ``ГГГГ-ММ-ДД чч:мм:сс``."""
        return f"Date({self.dt:%Y-%m-%d %H:%M:%S})"


class JCal:
    """Значение ``java.util.Calendar``."""

    __slots__ = ("dt",)

    def __init__(self, dt):
        """Создаёт календарь на момент ``dt``."""
        self.dt = dt


class JLambda:
    """Лямбда-выражение с захваченным окружением."""

    __slots__ = ("params", "body", "env", "frame")

    def __init__(self, params, body, env, frame):
        """Создаёт лямбду: параметры, тело, окружение и кадр создания."""
        self.params, self.body, self.env, self.frame = params, body, env, frame


class JMethodRef:
    """Ссылка на метод (``Класс::метод``, ``объект::метод``)."""

    __slots__ = ("obj", "name", "tname")

    def __init__(self, obj, name, tname=None):
        """Создаёт ссылку на метод ``name`` объекта или типа ``tname``."""
        self.obj, self.name, self.tname = obj, name, tname


class JClass:
    """Литерал класса или результат ``getClass()``."""

    __slots__ = ("ci", "name")

    def __init__(self, ci, name=None):
        """Создаёт литерал проектного класса ``ci`` или библиотечного."""
        self.ci, self.name = ci, name or (ci.name if ci else "?")


class JavaThrow(Exception):
    """Исключение Java, выброшенное интерпретируемым кодом."""

    def __init__(self, value):
        """Оборачивает объект исключения Java."""
        super().__init__(value)
        self.value = value


class ReturnEx(Exception):
    """Возврат из метода (``return``) внутри интерпретатора."""

    def __init__(self, value):
        """Оборачивает возвращаемое значение."""
        super().__init__(value)
        self.value = value


class BreakEx(Exception):
    """Оператор ``break`` (возможно, с меткой)."""

    def __init__(self, label=None):
        """Запоминает метку цикла."""
        super().__init__(label)
        self.label = label


class ContinueEx(Exception):
    """Оператор ``continue`` (возможно, с меткой)."""

    def __init__(self, label=None):
        """Запоминает метку цикла."""
        super().__init__(label)
        self.label = label
