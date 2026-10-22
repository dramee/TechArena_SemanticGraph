"""Интерпретатор подмножества Java для кода сервисов Train Ticket.

Выполняет код проекта «как JVM»: методы, конструкторы, вызовы между
сервисами (RestTemplate), репозитории (база в памяти). Невычислимые значения
представлены как UNK, а условие над UNK решается эвристикой выбора ветви.
Итог прогона — трасса с множествами executes, calls, remote и data.
"""

import collections
import itertools
import random
import re

from . import config as _cfg
from . import lib
from .jparse import (
    ArrayLit,
    Assert,
    Assign,
    Binary,
    Block,
    Break,
    Call,
    Cast,
    ClassDecl,
    ClassLit,
    Cond,
    Continue,
    DoWhile,
    Empty,
    ExprStmt,
    FieldAcc,
    For,
    ForEach,
    If,
    Index,
    InstanceOf,
    Labeled,
    Lambda,
    Lit,
    LocalClass,
    LocalVar,
    MethodRef,
    Name,
    New,
    NewArray,
    Postfix,
    Return,
    Super,
    Switch,
    Sync,
    This,
    Throw,
    Try,
    TypeExpr,
    Unary,
    While,
)
from .model import (
    PRIM_DEFAULT,
    ClassInfo,
    called_names,
    strip_generics,
    type_args,
)
from .values import (
    NOTFOUND,
    NOW,
    UNK,
    BreakEx,
    ContinueEx,
    JavaThrow,
    JClass,
    JEnum,
    JLambda,
    JList,
    JMethodRef,
    JObj,
    JOpt,
    JSet,
    LibObj,
    ReturnEx,
)


class Trace:
    """Итог прогона: множества рёбер executes, calls, remote и data."""

    def __init__(self):
        """Создаёт пустую трассу."""
        self.executes = set()
        self.calls = set()
        self.remote = set()
        self.data = set()
        self.exec_origin = collections.defaultdict(
            set
        )  # id метода -> {'new','hib','call','lib'}
        self.call_origin = {}

    def merge(self, other):
        """Добавляет в трассу рёбра другой трассы."""
        self.executes |= other.executes
        self.calls |= other.calls
        self.remote |= other.remote
        self.data |= other.data


class OutOfFuel(BaseException):
    """Защита от зацикливания: слишком много вызовов методов в одном шаге."""


class StaticRef:
    """Имя класса в позиции выражения."""

    __slots__ = ("ci", "name")

    def __init__(self, ci, name):
        """Ссылается на класс ``ci``, упомянутый в коде как ``name``."""
        self.ci, self.name = ci, name

    def __repr__(self):
        """Возвращает имя класса."""
        return f"Static<{self.name}>"


class Frame:
    """Кадр вызова: метод, ``this``, класс и локальные переменные."""

    __slots__ = ("method", "this", "locals", "cls", "up", "module", "static")

    def __init__(self, method, this, cls, up=None):
        """Создаёт кадр; ``up`` — окружение лямбды или анонимного класса."""
        self.method, self.this, self.cls, self.up = method, this, cls, up
        self.locals = {}
        self.module = cls.module if cls is not None else None


class LibClass:
    """Синтетический ClassInfo для библиотечных исключений."""

    pass


# Зерно генератора случайных чисел: прогоны воспроизводимы.
RANDOM_SEED = 12345

# Предел вызовов методов на прогон (переопределяется на каждый шаг).
DEFAULT_FUEL = 4_000_000

# Предел глубины вызовов методов: глубже рекурсия считается бесконечной.
MAX_CALL_DEPTH = 400

# Предел итераций цикла с неизвестным условием.
LOOP_CAP = 50

# иерархия библиотечных исключений
EXC_PARENT = {
    "Throwable": None,
    "Exception": "Throwable",
    "Error": "Throwable",
    "RuntimeException": "Exception",
    "IOException": "Exception",
    "ServletException": "Exception",
    "InterruptedException": "Exception",
    "ParseException": "Exception",
    "IllegalStateException": "RuntimeException",
    "IllegalArgumentException": "RuntimeException",
    "NullPointerException": "RuntimeException",
    "NumberFormatException": "IllegalArgumentException",
    "IndexOutOfBoundsException": "RuntimeException",
    "ArrayIndexOutOfBoundsException": "IndexOutOfBoundsException",
    "ClassCastException": "RuntimeException",
    "UnsupportedOperationException": "RuntimeException",
    "NoSuchElementException": "RuntimeException",
    "ArithmeticException": "RuntimeException",
    "JwtException": "RuntimeException",
    "AuthenticationException": "RuntimeException",
    "BadCredentialsException": "AuthenticationException",
    "UsernameNotFoundException": "AuthenticationException",
    "RestClientException": "RuntimeException",
    "HttpClientErrorException": "RestClientException",
    "HttpServerErrorException": "RestClientException",
    "ResourceAccessException": "RestClientException",
    "JsonProcessingException": "IOException",
    "DataAccessException": "RuntimeException",
    "EmptyResultDataAccessException": "DataAccessException",
    "MessagingException": "Exception",
    "ExecutionException": "Exception",
    "TimeoutException": "Exception",
}


class Interp:
    """Интерпретатор кода сервисов: исполняет методы и пишет трассу."""

    def __init__(self, proj, tables, trace=None):
        """Готовит интерпретатор для проекта ``proj`` и базы ``tables``."""
        self.p = proj
        self.trace = trace if trace is not None else Trace()
        # Имя таблицы -> db.Table.
        self.tables = tables
        # ClassInfo -> статические поля класса.
        self.statics = {}
        # (модуль, ClassInfo) -> бин Spring.
        self.beans = {}
        self.depth = 0
        # Журнал решений по неопределённым условиям.
        self.decisions = []
        self.warnings = collections.Counter()
        # Стек кадров Frame.
        self.stack = []
        self._anon = {}
        self.exc_classes = {}
        # Пароли, известные клиенту (имя -> пароль): ими эмулируется сверка
        # хешей BCrypt.
        self.known_passwords = {}
        self.max_depth = MAX_CALL_DEPTH
        self.loop_cap = LOOP_CAP
        # Заполняются при создании web.Web и repo.Repos.
        self.web = None
        self.repos = None
        # (файл, строка) -> решение для неопределённого условия.
        self.overrides = {}
        self.exc_log = []
        self.fuel = DEFAULT_FUEL
        self.session = {}
        self.origin = None
        self.lombok_depth = 0
        self.auth_log = []
        self.json_trace = Trace()
        self.rng = random.Random(RANDOM_SEED)
        self.now = NOW
        self.uuid_counter = itertools.count(1)

    def new_uuid(self):
        """Возвращает следующий детерминированный UUID этого прогона."""
        return "00000000-0000-4000-8000-%012d" % next(self.uuid_counter)

    # ------------------------------------------------------------------------------------------
    # трассировка
    @staticmethod
    def has_stmts(mi):
        """Проверяет, что у метода есть тело с операторами."""
        b = mi.decl.body
        return b is not None and any(not isinstance(x, Empty) for x in b.stmts)

    def rec_exec(self, mi):
        """Отмечает исполнение метода (ребро executes)."""
        if mi is not None and mi.id and self.has_stmts(mi):
            self.trace.executes.add(mi.id)
            self.trace.exec_origin[mi.id].add(self.origin or "call")

    def rec_call(self, caller, callee):
        """Отмечает вызов метода методом (ребро calls)."""
        if (
            caller is not None
            and caller.id
            and callee is not None
            and callee.id
            and self.has_stmts(callee)
        ):
            self.trace.calls.add((caller.id, callee.id))

    def warn(self, what):
        """Считает предупреждение интерпретатора (для журнала ``-v``)."""
        self.warnings[what] += 1

    # ------------------------------------------------------------------------------------------
    # статика / бины
    def statics_of(self, ci):
        """Возвращает статические поля класса, инициализируя их один раз."""
        st = self.statics.get(ci)
        if st is not None:
            return st
        st = {}
        self.statics[ci] = st
        saved = self.trace
        self.trace = (
            Trace()
        )  # инициализация классов происходит до сценария: не учитывается
        try:
            fr = Frame(None, None, ci)
            if ci.kind == "enum":
                for i, ec in enumerate(ci.decl.enums):
                    e = JEnum(ci, ec.name, i)
                    st[ec.name] = e
                for i, ec in enumerate(ci.decl.enums):
                    e = st[ec.name]
                    for f in self.p.all_fields(ci):
                        e.f[f.name] = PRIM_DEFAULT.get(
                            strip_generics(f.type), None
                        )
                    cls_for = ci
                    if ec.body is not None:
                        cls_for = self._anon_class(ec.body, ci, ci.name)
                        e.cls = cls_for
                    args = [self.ev(a, fr) for a in ec.args]
                    self._run_ctor(ci, e, args, None, fr)
            for f in ci.fields.values():
                if f.static:
                    st[f.name] = PRIM_DEFAULT.get(strip_generics(f.type), None)
            for f in ci.fields.values():
                if f.static and f.init is not None:
                    try:
                        st[f.name] = self.ev_init(f.init, fr, f.type)
                    except (
                        JavaThrow,
                        TypeError,
                        AttributeError,
                        KeyError,
                        IndexError,
                        ValueError,
                    ):
                        st[f.name] = UNK
            for is_static, blk in ci.decl.inits:
                if is_static:
                    try:
                        self.ex(blk, fr)
                    except Exception:
                        pass
        finally:
            self.trace = saved
        return st

    def ev_init(self, e, fr, tname):
        """Вычисляет инициализатор переменной (выражение или массив)."""
        if isinstance(e, ArrayLit):
            return JList(self.ev(x, fr) for x in e.elems)
        return self.ev(e, fr)

    def bean(self, module, ci):
        """Возвращает бин Spring класса в модуле, создавая его один раз."""
        key = (module, ci)
        b = self.beans.get(key)
        if b is not None:
            return b
        b = JObj(ci)
        self.beans[key] = b
        for f in self.p.all_fields(ci):
            b.f[f.name] = PRIM_DEFAULT.get(strip_generics(f.type), None)
        saved = self.trace
        self.trace = Trace()
        try:
            fr = Frame(None, b, ci)
            for f in self.p.all_fields(ci):
                if f.init is not None:
                    try:
                        b.f[f.name] = self.ev_init(f.init, fr, f.type)
                    except Exception:
                        b.f[f.name] = UNK
        finally:
            self.trace = saved
        for f in self.p.all_fields(ci):
            if (
                "Autowired" in f.annots
                or "Resource" in f.annots
                or "Inject" in f.annots
            ):
                b.f[f.name] = self.inject(module, f, ci)
        return b

    def inject(self, module, f, owner):
        """Возвращает значение поля ``@Autowired``: бин или репозиторий."""
        t = strip_generics(f.type)
        tci = self.p.resolve(t, f.cls)
        if tci is None:
            return lib.new_lib_bean(t, self)
        if self.repos.is_repo(tci):
            return self.repos.proxy(tci)
        if tci.kind == "interface" or "abstract" in tci.decl.mods:
            impls = self.p.implementations(tci, module)
            impls = [c for c in impls if self.is_component(c)] or impls
            if impls:
                return self.bean(module, impls[0])
            return UNK
        return self.bean(module, tci)

    def is_component(self, ci):
        """Проверяет, что класс — бин Spring (@Service, @Component и т. п.)."""
        return bool(
            ci.annots.keys()
            & {
                "Service",
                "Component",
                "RestController",
                "Controller",
                "Repository",
                "Configuration",
            }
        )

    # ------------------------------------------------------------------------------------------
    # классы
    def _anon_class(self, decl, outer_ci, super_name):
        key = id(decl)
        ci = self._anon.get(key)
        if ci is None:
            ci = ClassInfo(
                decl,
                outer_ci.module,
                outer_ci.file,
                outer_ci.pkg,
                outer_ci.imports,
                outer_ci,
            )
            ci.super_name = super_name
            ci.anon = True
            for md_list in list(ci.methods.values()):
                for mi in md_list:
                    mi.id = self.p.method_by_start[outer_ci.file].get(
                        (mi.name, mi.decl.start)
                    )
            self._anon[key] = ci
        return ci

    def lib_exc_class(self, name):
        """Возвращает описание библиотечного класса исключения."""
        ci = self.exc_classes.get(name)
        if ci is None:
            ci = ClassInfo(
                ClassDecl(
                    "class",
                    name,
                    set(),
                    [],
                    EXC_PARENT.get(name),
                    [],
                    [],
                    [],
                    [],
                    [],
                    [],
                    0,
                    0,
                    None,
                    False,
                    name,
                ),
                "<lib>",
                "",
                "",
                [],
            )
            self.exc_classes[name] = ci
        return ci

    def is_exc_instance(self, v, tname, ctx):
        """Проверяет, ловит ли ``catch (T e)`` с типом ``tname`` исключение."""
        if not isinstance(v, JObj):
            return False
        base = strip_generics(tname).split(".")[-1]
        if base in ("Throwable", "Exception"):
            return True
        tci = self.p.resolve(tname, ctx)
        if tci is not None:
            return self.p.is_subclass(v.cls, tci)
        # библиотечный
        c = v.cls
        while c is not None:
            if c.name == base:
                return True
            nm = c.super_name
            if c.module == "<lib>":
                nm = EXC_PARENT.get(c.name)
                c2 = self.lib_exc_class(nm) if nm else None
            else:
                c2 = self.p.super_of(c)
                if c2 is None and nm:
                    # проектный класс, наследующий библиотечное исключение
                    n2 = strip_generics(nm).split(".")[-1]
                    while n2:
                        if n2 == base:
                            return True
                        n2 = EXC_PARENT.get(n2)
                    return False
            c = c2
        return False

    def make_exc(self, name, msg=None):
        """Создаёт объект библиотечного исключения с сообщением."""
        o = JObj(self.lib_exc_class(name))
        o.f["message"] = msg
        if name in (
            "NullPointerException",
            "ClassCastException",
            "IndexOutOfBoundsException",
            "NoSuchElementException",
        ):
            where = [
                f"{f.method.cls.name}#{f.method.name}"
                for f in self.stack
                if f.method is not None
            ][-4:]
            self.exc_log.append((name, msg, where))
        return o

    # ------------------------------------------------------------------------------------------
    # создание объектов
    def default_fields(self, ci):
        """Возвращает значения полей по умолчанию для нового объекта."""
        d = {}
        for f in self.p.all_fields(ci):
            d[f.name] = PRIM_DEFAULT.get(strip_generics(f.type), None)
        return d

    def instantiate(self, ci, args, caller, fr=None):
        """Создаёт объект класса проекта и выполняет конструктор."""
        obj = JObj(ci, self.default_fields(ci))
        self._run_ctor(ci, obj, args, caller, fr)
        return obj

    def _pick_ctor(self, ci, args):
        return self.pick_overload(ci.ctors, args)

    def pick_overload(self, cands, args):
        """Выбирает перегрузку метода по типам аргументов."""
        cands = [
            m
            for m in cands
            if len(m.params) == len(args)
            or (m.varargs and len(args) >= len(m.params) - 1)
        ]
        if not cands:
            return None
        if len(cands) == 1:
            return cands[0]
        best, bs = None, -1
        for m in cands:
            s = 0
            if len(m.params) == len(args):
                s += 1
            for (pt, _, _), a in zip(m.params, args):
                s += self.type_score(strip_generics(pt), a)
            if s > bs:
                best, bs = m, s
        return best

    def type_score(self, pt, a):
        """Оценивает соответствие аргумента ``a`` типу параметра ``pt``."""
        pt = pt.split(".")[-1]
        if a is UNK:
            return 0
        if a is None:
            return 0 if pt in PRIM_DEFAULT else 1
        if isinstance(a, bool):
            return 3 if pt in ("boolean", "Boolean") else -3
        if isinstance(a, int):
            if pt in ("int", "long", "short", "byte", "Integer", "Long"):
                return 3
            if pt in ("double", "float", "Double", "Float"):
                return 1
            return -3 if pt in ("String", "boolean") else 0
        if isinstance(a, float):
            return (
                3
                if pt in ("double", "float", "Double", "Float")
                else (-3 if pt in ("int", "long", "String") else 0)
            )
        if isinstance(a, str):
            return (
                3
                if pt in ("String", "CharSequence")
                else (1 if pt == "Object" else -3)
            )
        if isinstance(a, JObj):
            if a.cls.name == pt:
                return 4
            return (
                2
                if any(c.name == pt for c in self.p.supertypes(a.cls))
                else (0 if pt == "Object" else -2)
            )
        if isinstance(a, list):
            return (
                3
                if pt
                in (
                    "List",
                    "ArrayList",
                    "Collection",
                    "Iterable",
                    "LinkedList",
                )
                or pt.endswith("[]")
                else -2
            )
        return 0

    def _run_ctor(self, ci, obj, args, caller, fr):
        ctor = self._pick_ctor(ci, args) if ci.ctors else None
        if ctor is not None:
            self.rec_exec(ctor)
            self.rec_call(caller, ctor)
            f2 = Frame(ctor, obj, ci)
            self.bind_params(ctor, args, f2)
            body = ctor.decl.body.stmts if ctor.decl.body else []
            first = body[0] if body else None
            explicit = None
            if (
                isinstance(first, ExprStmt)
                and isinstance(first.e, Call)
                and first.e.obj is None
                and first.e.name in ("this", "super")
            ):
                explicit = first.e
                body = body[1:]
            if explicit is not None and explicit.name == "this":
                a2 = [self.ev(a, f2) for a in explicit.args]
                tgt = self.pick_overload(ci.ctors, a2)
                if tgt is not None and tgt is not ctor:
                    self._run_ctor_explicit(ci, obj, tgt, a2, ctor)
            else:
                sup = self.p.super_of(ci)
                if sup is not None:
                    a2 = (
                        [self.ev(a, f2) for a in explicit.args]
                        if explicit is not None
                        else []
                    )
                    self._run_ctor(sup, obj, a2, ctor, f2)
                self._field_inits(ci, obj)
            try:
                for st in body:
                    self.ex(st, f2)
            except ReturnEx:
                pass
        else:
            sup = self.p.super_of(ci)
            if sup is not None:
                self._run_ctor(sup, obj, [], caller, fr)
            self._field_inits(ci, obj)
            if args:
                self._lombok_ctor(ci, obj, args)

    def _run_ctor_explicit(self, ci, obj, ctor, args, caller):
        self.rec_exec(ctor)
        self.rec_call(caller, ctor)
        f2 = Frame(ctor, obj, ci)
        self.bind_params(ctor, args, f2)
        body = ctor.decl.body.stmts if ctor.decl.body else []
        first = body[0] if body else None
        if (
            isinstance(first, ExprStmt)
            and isinstance(first.e, Call)
            and first.e.obj is None
            and first.e.name in ("this", "super")
        ):
            explicit = first.e
            body = body[1:]
            if explicit.name == "this":
                a2 = [self.ev(a, f2) for a in explicit.args]
                tgt = self.pick_overload(ci.ctors, a2)
                if tgt is not None and tgt is not ctor:
                    self._run_ctor_explicit(ci, obj, tgt, a2, ctor)
            else:
                sup = self.p.super_of(ci)
                if sup is not None:
                    self._run_ctor(
                        sup,
                        obj,
                        [self.ev(a, f2) for a in explicit.args],
                        ctor,
                        f2,
                    )
                self._field_inits(ci, obj)
        else:
            sup = self.p.super_of(ci)
            if sup is not None:
                self._run_ctor(sup, obj, [], ctor, f2)
            self._field_inits(ci, obj)
        try:
            for st in body:
                self.ex(st, f2)
        except ReturnEx:
            pass

    def _field_inits(self, ci, obj):
        if not ci.decl.inits and not any(
            f.init is not None and not f.static for f in ci.fields.values()
        ):
            return
        fr = Frame(None, obj, ci)
        for f in ci.fields.values():
            if not f.static and f.init is not None:
                obj.f[f.name] = self.ev_init(f.init, fr, f.type)
        for is_static, blk in ci.decl.inits:
            if not is_static:
                self.ex(blk, fr)

    def _lombok_ctor(self, ci, obj, args):
        flds = [f for f in ci.fields.values() if not f.static]
        if (
            "RequiredArgsConstructor" in ci.annots
            and "AllArgsConstructor" not in ci.annots
        ):
            flds = [f for f in flds if f.final and f.init is None]
        for f, a in zip(flds, args):
            obj.f[f.name] = a

    def bind_params(self, mi, args, fr):
        """Связывает параметры метода с аргументами в кадре."""
        ps = mi.params
        for i, (pt, pn, _) in enumerate(ps):
            if mi.varargs and i == len(ps) - 1:
                rest = args[i:]
                if len(rest) == 1 and (
                    isinstance(rest[0], list) or rest[0] is None
                ):
                    fr.locals[pn] = rest[0]
                else:
                    fr.locals[pn] = JList(rest)
            else:
                v = args[i] if i < len(args) else None
                fr.locals[pn] = self.coerce(v, pt)

    def coerce(self, v, pt):
        """Приводит числовое значение к типу параметра ``pt``."""
        pt = strip_generics(pt)
        if isinstance(v, bool) or v is None or v is UNK:
            return v
        if pt in ("double", "float", "Double", "Float") and isinstance(v, int):
            return float(v)
        if pt in ("int", "long", "short", "byte") and isinstance(v, float):
            return int(v)
        return v

    # ------------------------------------------------------------------------------------------
    # вызов метода
    def invoke(self, mi, this, args, caller):
        """Выполнить проектный метод с телом."""
        if mi.decl.body is None:
            return UNK
        if self.depth > self.max_depth:
            self.warn("recursion limit")
            return UNK
        self.fuel -= 1
        if self.fuel < 0:
            raise OutOfFuel()
        self.rec_exec(mi)
        self.rec_call(caller, mi)
        fr = Frame(mi, this, mi.cls)
        self.bind_params(mi, args, fr)
        self.depth += 1
        self.stack.append(fr)
        try:
            self.ex(mi.decl.body, fr)
            return None
        except ReturnEx as r:
            return r.value
        except (JavaThrow, BreakEx, ContinueEx):
            raise
        except Exception as e:
            if getattr(e, "_where", None) is None:
                try:
                    e._where = [
                        f"{f.method.cls.name}#{f.method.name}"
                        for f in self.stack
                        if f.method is not None
                    ][-6:]
                except Exception:
                    pass
            raise
        finally:
            self.depth -= 1
            self.stack.pop()

    def lib_invoke(self, mi, this, args):
        """Вызывает метод проекта из кода библиотеки внутри метода проекта.

        Так вызывают Spring Security, логирование (toString) и коллекции.
        В эталоне это даёт ребро calls от ближайшего метода проекта в стеке,
        если в его исходнике есть вызов с тем же именем.
        """
        r = self.invoke(mi, this, args, None)
        if self.lombok_depth and _cfg.LOMBOK_BREAKS_CHAIN:
            # между библиотекой и методом стоит сгенерированный Lombok метод
            # класса проекта: ребра calls нет
            return r
        if _cfg.LIB_NAME_MATCH_EDGES and self.stack and not mi.ctor:
            f = self.stack[-1].method
            if f is not None and mi.name in called_names(f):
                self.rec_call(f, mi)
        return r

    def call_virtual(self, obj, name, args, caller):
        """Вызов метода у проектного объекта (виртуальная диспетчеризация)."""
        ci = obj.cls
        cands = [m for m in self.p.find_methods(ci, name) if not m.abstract]
        mi = self.pick_overload(cands, args)
        if mi is not None:
            return True, self.invoke(mi, obj, args, caller)
        return False, None

    def call_static(self, ci, name, args, caller):
        """Вызывает статический метод класса проекта, если он есть."""
        cands = [m for m in self.p.find_methods(ci, name) if not m.abstract]
        mi = self.pick_overload(cands, args)
        if mi is not None:
            return True, self.invoke(mi, None, args, caller)
        return False, None

    # ------------------------------------------------------------------------------------------
    # операторы
    def ex(self, st, fr):
        """Выполняет оператор в кадре ``fr``."""
        t = type(st)
        h = self._ex_table.get(t)
        if h is None:
            raise NotImplementedError(f"оператор {t.__name__}")
        return h(self, st, fr)

    def ex_block(self, st, fr):
        """Выполняет блок операторов."""
        for s in st.stmts:
            self.ex(s, fr)

    def ex_local(self, st, fr):
        """Выполняет объявление локальных переменных."""
        for nm, init in st.decls:
            if init is None:
                fr.locals[nm] = PRIM_DEFAULT.get(strip_generics(st.type), None)
            else:
                fr.locals[nm] = self.coerce(
                    self.ev_init(init, fr, st.type), st.type
                )

    def ex_expr(self, st, fr):
        """Выполняет оператор-выражение."""
        self.ev(st.e, fr)

    def ex_if(self, st, fr):
        """Выполняет условный оператор ``if``."""
        c = self.cond(st.c, fr, st)
        if c:
            self.ex(st.then, fr)
        elif st.els is not None:
            self.ex(st.els, fr)

    def ex_while(self, st, fr):
        """Выполняет цикл ``while``."""
        n = 0
        while True:
            c = self.cond(st.c, fr, st, loop=True)
            if not c:
                break
            n += 1
            if n > self.loop_cap:
                self.warn(f"loop cap {fr.cls.name}:{getattr(st, 'line', 0)}")
                break
            try:
                self.ex(st.body, fr)
            except BreakEx as b:
                if b.label is None:
                    break
                raise
            except ContinueEx as c_:
                if c_.label is None:
                    continue
                raise

    def ex_dowhile(self, st, fr):
        """Выполняет цикл ``do … while``."""
        n = 0
        while True:
            n += 1
            try:
                self.ex(st.body, fr)
            except BreakEx as b:
                if b.label is None:
                    break
                raise
            except ContinueEx as c_:
                if c_.label is not None:
                    raise
            if n > self.loop_cap or not self.cond(st.c, fr, st, loop=True):
                break

    def ex_for(self, st, fr):
        """Выполняет цикл ``for``."""
        for s in st.init:
            self.ex(s, fr)
        n = 0
        while True:
            if st.c is not None and not self.cond(st.c, fr, st, loop=True):
                break
            n += 1
            if n > self.loop_cap:
                self.warn(f"loop cap {fr.cls.name}:{getattr(st, 'line', 0)}")
                break
            try:
                self.ex(st.body, fr)
            except BreakEx as b:
                if b.label is None:
                    break
                raise
            except ContinueEx as c_:
                if c_.label is not None:
                    raise
            for u in st.update:
                self.ev(u, fr)

    def ex_foreach(self, st, fr):
        """Выполняет цикл по коллекции."""
        it = self.ev(st.iter, fr)
        items = self.iter_items(it)
        for x in items:
            fr.locals[st.name] = x
            try:
                self.ex(st.body, fr)
            except BreakEx as b:
                if b.label is None:
                    break
                raise
            except ContinueEx as c_:
                if c_.label is not None:
                    raise

    def iter_items(self, it):
        """Возвращает элементы коллекции для цикла по ней."""
        if it is UNK:
            return [UNK]  # неизвестная коллекция: выполнить тело один раз
        if it is None:
            raise JavaThrow(
                self.make_exc("NullPointerException", "for-each over null")
            )
        if isinstance(it, JSet):
            return list(it.values())
        if isinstance(it, dict):
            return list(it.keys())
        if isinstance(it, (list, tuple, set)):
            return list(it)
        if isinstance(it, JOpt):
            return [] if it.v is None else [it.v]
        return [UNK]

    def ex_return(self, st, fr):
        """Выполняет ``return``."""
        raise ReturnEx(self.ev(st.e, fr) if st.e is not None else None)

    def ex_throw(self, st, fr):
        """Выполняет ``throw``."""
        v = self.ev(st.e, fr)
        raise JavaThrow(v)

    def ex_break(self, st, fr):
        """Выполняет ``break``."""
        raise BreakEx(st.label)

    def ex_continue(self, st, fr):
        """Выполняет ``continue``."""
        raise ContinueEx(st.label)

    def ex_try(self, st, fr):
        """Выполняет ``try`` с ресурсами, ``catch`` и ``finally``."""
        try:
            try:
                for nm, e in st.res:
                    v = self.ev(e, fr)
                    if nm:
                        fr.locals[nm] = v
                self.ex(st.body, fr)
            except JavaThrow as jt:
                v = jt.value
                for types, nm, blk in st.catches:
                    if any(self.is_exc_instance(v, t, fr.cls) for t in types):
                        fr.locals[nm] = v
                        self.ex(blk, fr)
                        break
                else:
                    raise
            except RecursionError:
                raise
        finally:
            if st.fin is not None:
                self.ex(st.fin, fr)

    def ex_switch(self, st, fr):
        """Выполняет ``switch``."""
        v = self.ev(st.e, fr)
        matched = False
        try:
            for labels, stmts in st.cases:
                if not matched:
                    if labels is None:
                        matched = True
                    else:
                        for lab in labels:
                            lv = self.case_label(lab, v, fr)
                            if lv is True:
                                matched = True
                                break
                if matched:
                    for s in stmts:
                        self.ex(s, fr)
            if not matched and v is UNK:
                pass
        except BreakEx as b:
            if b.label is not None:
                raise

    def case_label(self, lab, v, fr):
        """Проверяет, совпадает ли метка ``case`` со значением."""
        if v is UNK:
            return False
        if isinstance(lab, Name) and isinstance(v, JEnum):
            return lab.id == v.name
        lv = self.ev(lab, fr)
        return lv == v

    def ex_sync(self, st, fr):
        """Выполняет блок ``synchronized``."""
        self.ex(st.body, fr)

    def ex_labeled(self, st, fr):
        """Выполняет оператор с меткой."""
        try:
            self.ex(st.stmt, fr)
        except BreakEx as b:
            if b.label != st.label:
                raise

    def ex_noop(self, st, fr):
        """Пропускает пустой оператор или объявление класса."""

    def ex_assert(self, st, fr):
        """Пропускает ``assert`` (в сервисах проверки выключены)."""

    _ex_table = {}

    # ------------------------------------------------------------------------------------------
    # условия
    def cond(self, e, fr, node, loop=False):
        """Вычисляет условие; неизвестное условие решается эвристикой."""
        v = self.ev(e, fr)
        if v is UNK:
            return self.decide(e, fr, node, loop)
        if v is None:
            return False
        return bool(v)

    def decide(self, e, fr, node, loop=False):
        """Решение по неизвестному условию."""
        key = (fr.cls.file if fr.cls else "?", getattr(node, "line", 0))
        ov = self.overrides.get(key)
        if ov is not None:
            d = ov
        elif loop:
            d = self._decide_loop(e, node)
        else:
            d = self._decide_if(e, node)
        self.decisions.append((key, d, expr_text(e)))
        return d

    def _decide_loop(self, e, node):
        return (
            getattr(node, "_ud", 0) == 0 and not setattr(node, "_ud", 1)
            if False
            else self._loop_once(node)
        )

    def _loop_once(self, node):
        # неизвестное условие цикла: выполняем тело один раз за вход в оператор
        cnt = getattr(self, "_loop_state", None)
        if cnt is None:
            cnt = self._loop_state = {}
        k = id(node)
        cnt[k] = cnt.get(k, 0) + 1
        if cnt[k] == 1:
            return True
        cnt[k] = 0
        return False

    def _decide_if(self, e, node):
        if not isinstance(node, If):
            return True
        te = branch_score(node.then)
        ee = branch_score(node.els) if node.els is not None else 0
        if te < ee:
            return True
        if ee < te:
            return False
        txt = expr_text(e)
        return heuristic_polarity(txt)

    # ------------------------------------------------------------------------------------------
    # выражения
    def ev(self, e, fr):
        """Вычисляет выражение в кадре ``fr``."""
        h = self._ev_table.get(type(e))
        if h is None:
            raise NotImplementedError(f"выражение {type(e).__name__}")
        return h(self, e, fr)

    def ev_lit(self, e, fr):
        """Возвращает значение литерала."""
        return e.val

    def ev_name(self, e, fr):
        """Вычисляет имя: переменная, поле или класс."""
        nm = e.id
        f = fr
        while f is not None:
            if nm in f.locals:
                return f.locals[nm]
            f = f.up
        # поле this / внешнего объекта
        v = self.lookup_field_ctx(nm, fr)
        if v is not NOTFOUND:
            return v
        ref = self.class_ref(nm, fr.cls)
        if ref is not None:
            return ref
        self.warn(f"name? {nm}")
        return UNK

    def lookup_field_ctx(self, nm, fr):
        """Находит поле по имени у ``this`` и внешних объектов."""
        this = fr.this
        f = fr
        while f is not None and this is None:
            this = f.this
            f = f.up
        # this chain (для анонимных/внутренних: tag.outer)
        obj = this
        guard = 0
        while obj is not None and guard < 6:
            guard += 1
            if isinstance(obj, (JObj, JEnum)) and nm in obj.f:
                return obj.f[nm]
            if isinstance(obj, JObj) and obj.tag and isinstance(obj.tag, dict):
                env = obj.tag.get("env")
                if env is not None:
                    f2 = env
                    while f2 is not None:
                        if nm in f2.locals:
                            return f2.locals[nm]
                        f2 = f2.up
                obj = obj.tag.get("outer")
                continue
            break
        # статические поля класса, родителей и внешних классов
        c = fr.cls
        while c is not None:
            for s in self.p.supertypes(c):
                if nm in s.fields and s.fields[nm].static:
                    return self.statics_of(s).get(nm, None)
                if s.kind == "enum" and nm in s.enum_names:
                    return self.statics_of(s)[nm]
            c = c.outer
        return NOTFOUND

    def class_ref(self, nm, ctx):
        """Возвращает ссылку на класс по имени в контексте ``ctx``."""
        if ctx is None:
            return None
        ci = self.p.resolve(nm, ctx)
        if ci is not None:
            return StaticRef(ci, nm)
        return (
            StaticRef(None, nm)
            if nm[:1].isupper() or nm in ("java", "javax", "org", "com")
            else None
        )

    def ev_field(self, e, fr):
        """Вычисляет обращение к полю через точку."""
        o = (
            self.ev(e.obj, fr)
            if not (isinstance(e.obj, Name) and self._is_pkg(e.obj.id, fr))
            else StaticRef(None, e.obj.id)
        )
        nm = e.name
        if isinstance(o, StaticRef):
            if o.ci is not None:
                st = self.statics_of(o.ci)
                if nm in st:
                    return st[nm]
                if nm in o.ci.inner:
                    return StaticRef(o.ci.inner[nm], nm)
                f = self.p.find_field(o.ci, nm)
                if f is not None and f.static:
                    return self.statics_of(f.cls).get(nm)
                return UNK
            return lib.static_field(self, o.name, nm)
        if o is UNK:
            return UNK
        if o is None:
            self.warn("NPE field " + nm)
            raise JavaThrow(
                self.make_exc("NullPointerException", f"field {nm} of null")
            )
        if isinstance(o, (JObj, JEnum)):
            if nm in o.f:
                return o.f[nm]
            if nm == "length":
                return UNK
            return UNK
        if nm == "length" and isinstance(o, (list, str)):
            return len(o)
        return UNK

    def _is_pkg(self, nm, fr):
        if nm in ("java", "javax", "org", "com", "edu"):
            f = fr
            while f is not None:
                if nm in f.locals:
                    return False
                f = f.up
            return True
        return False

    def ev_this(self, e, fr):
        """Возвращает ``this`` текущего кадра."""
        f = fr
        while f is not None:
            if f.this is not None:
                return f.this
            f = f.up
        return None

    def ev_unary(self, e, fr):
        """Вычисляет унарный оператор."""
        op = e.op
        if op in ("++", "--"):
            old = self.ev(e.e, fr)
            new = lib.arith("+" if op == "++" else "-", old, 1)
            self.assign_to(e.e, new, fr)
            return new
        v = self.ev(e.e, fr)
        if v is UNK:
            return UNK
        if op == "!":
            return not v if v is not None else UNK
        if op == "-":
            return -v
        if op == "+":
            return v
        if op == "~":
            return ~v
        return UNK

    def ev_postfix(self, e, fr):
        """Вычисляет ``x++`` и ``x--``."""
        old = self.ev(e.e, fr)
        new = lib.arith("+" if e.op == "++" else "-", old, 1)
        self.assign_to(e.e, new, fr)
        return old

    def ev_binary(self, e, fr):
        """Вычисляет бинарный оператор (с ленивыми ``&&`` и ``||``)."""
        op = e.op
        if op == "&&":
            left = self.ev(e.l, fr)
            if left is UNK:
                right = self.ev(e.r, fr)
                if right is UNK or right:
                    return UNK
                return False
            if not left:
                return False
            return self.ev(e.r, fr)
        if op == "||":
            left = self.ev(e.l, fr)
            if left is UNK:
                right = self.ev(e.r, fr)
                if right is UNK or not right:
                    return UNK
                return True
            if left:
                return True
            return self.ev(e.r, fr)
        left = self.ev(e.l, fr)
        right = self.ev(e.r, fr)
        return lib.binop(self, op, left, right)

    def ev_cond(self, e, fr):
        """Вычисляет условный оператор ``c ? a : b``."""
        c = self.ev(e.c, fr)
        if c is UNK:
            c = self.decide_cond_expr(e, fr)
        return self.ev(e.a if c else e.b, fr)

    def decide_cond_expr(self, e, fr):
        """Угадывает ветвь условного оператора с неизвестным условием."""
        return heuristic_polarity(expr_text(e.c))

    def ev_cast(self, e, fr):
        """Вычисляет приведение типа."""
        v = self.ev(e.e, fr)
        t = strip_generics(e.type)
        if v is UNK or v is None:
            return v
        if t in ("int", "long", "short", "byte"):
            if isinstance(v, float):
                return int(v)
            return v
        if t in ("double", "float"):
            return float(v) if isinstance(v, (int, float)) else v
        if t == "char" and isinstance(v, int):
            return chr(v)
        return v

    def ev_instanceof(self, e, fr):
        """Вычисляет ``instanceof``."""
        v = self.ev(e.e, fr)
        if v is UNK:
            return UNK
        if v is None:
            return False
        t = strip_generics(e.type)
        if isinstance(v, JObj):
            tci = self.p.resolve(t, fr.cls)
            if tci is not None:
                r = self.p.is_subclass(v.cls, tci)
            else:
                r = self.is_exc_instance(v, t, fr.cls) or t == "Object"
            if r and e.bind:
                fr.locals[e.bind] = v
            return r
        r = lib.instance_of(v, t)
        if r and e.bind:
            fr.locals[e.bind] = v
        return r

    def ev_index(self, e, fr):
        """Вычисляет обращение к элементу массива."""
        o = self.ev(e.obj, fr)
        i = self.ev(e.idx, fr)
        if o is UNK or i is UNK or o is None:
            return UNK
        try:
            return o[i]
        except (IndexError, KeyError, TypeError):
            return UNK

    def ev_arraylit(self, e, fr):
        """Вычисляет литерал массива."""
        return JList(self.ev(x, fr) for x in e.elems)

    def ev_newarray(self, e, fr):
        """Создаёт массив оператором ``new``."""
        if e.init is not None:
            return JList(self.ev(x, fr) for x in e.init.elems)
        n = 0
        if e.dims and e.dims[0] is not None:
            n = self.ev(e.dims[0], fr)
            if not isinstance(n, int):
                n = 0
        return JList([PRIM_DEFAULT.get(e.type, None)] * n)

    def ev_lambda(self, e, fr):
        """Создаёт значение лямбды с захваченным окружением."""
        return JLambda(e.params, e.body, fr, fr)

    def ev_methodref(self, e, fr):
        """Создаёт значение ссылки на метод."""
        o = e.obj
        if isinstance(o, Name):
            v = self.ev(o, fr)
        elif isinstance(o, TypeExpr):
            v = StaticRef(None, o.type)
        else:
            v = self.ev(o, fr)
        return JMethodRef(v, e.name)

    def ev_classlit(self, e, fr):
        """Возвращает литерал класса ``X.class``."""
        if isinstance(e.type, str):
            return JClass(self.p.resolve(e.type, fr.cls), e.type)
        v = (
            self.ev(e.type, fr)
            if not isinstance(e.type, Name)
            else self.class_ref(e.type.id, fr.cls)
        )
        if isinstance(v, StaticRef):
            return JClass(v.ci, v.name)
        return JClass(None, "?")

    def ev_typeexpr(self, e, fr):
        """Возвращает ссылку на тип в позиции выражения."""
        return StaticRef(self.p.resolve(e.type, fr.cls), e.type)

    def ev_super(self, e, fr):
        """Возвращает ``this`` для обращения через ``super``."""
        return self.ev_this(e, fr)

    def ev_switchexpr(self, e, fr):
        # switch как выражение: результат последнего выражения выбранной ветви
        """Возвращает UNK для выражения ``switch`` (в проекте их нет)."""
        return UNK

    # --- присваивания
    def ev_assign(self, e, fr):
        """Вычисляет присваивание, в том числе составное (``+=``)."""
        op = e.op
        if op == "=":
            v = self.ev_init(e.value, fr, None)
        else:
            old = self.ev(e.target, fr)
            r = self.ev(e.value, fr)
            v = lib.binop(self, op[:-1], old, r)
        self.assign_to(e.target, v, fr)
        return v

    def assign_to(self, tgt, v, fr):
        """Записывает значение в переменную, поле или элемент массива."""
        if isinstance(tgt, Name):
            nm = tgt.id
            f = fr
            while f is not None:
                if nm in f.locals:
                    f.locals[nm] = v
                    return
                f = f.up
            obj = fr.this
            f = fr
            while obj is None and f is not None:
                obj = f.this
                f = f.up
            guard = 0
            while obj is not None and guard < 6:
                guard += 1
                if isinstance(obj, JObj) and nm in obj.f:
                    obj.f[nm] = v
                    return
                if (
                    isinstance(obj, JObj)
                    and isinstance(obj.tag, dict)
                    and obj.tag.get("outer") is not None
                ):
                    obj = obj.tag["outer"]
                    continue
                break
            c = fr.cls
            while c is not None:
                for s in self.p.supertypes(c):
                    if nm in s.fields and s.fields[nm].static:
                        self.statics_of(s)[nm] = v
                        return
                c = c.outer
            fr.locals[nm] = v
        elif isinstance(tgt, FieldAcc):
            o = self.ev(tgt.obj, fr)
            if isinstance(o, StaticRef) and o.ci is not None:
                self.statics_of(o.ci)[tgt.name] = v
            elif isinstance(o, (JObj, JEnum)):
                o.f[tgt.name] = v
        elif isinstance(tgt, Index):
            o = self.ev(tgt.obj, fr)
            i = self.ev(tgt.idx, fr)
            if isinstance(o, list) and isinstance(i, int) and 0 <= i < len(o):
                o[i] = v
            elif isinstance(o, dict):
                o[i] = v

    # --- вызовы
    def ev_new(self, e, fr):
        """Создаёт объект оператором ``new`` (проектный или библиотечный)."""
        args = [self.ev(a, fr) for a in e.args]
        caller = fr.method
        tname = e.type
        base = strip_generics(tname)
        ci = self.p.resolve(tname, fr.cls)
        if e.body is not None and base.split(".")[-1] in (
            "ParameterizedTypeReference",
            "TypeReference",
        ):
            ta = type_args(tname)
            return LibObj("PTR", type=ta[0] if ta else None, ctx=fr.cls)
        if e.body is not None:
            sup = ci
            anon = self._anon_class(e.body, fr.cls, tname)
            obj = JObj(anon, self.default_fields(anon))
            if sup is not None and sup.kind != "interface":
                self._run_ctor(sup, obj, args, caller, fr)
            self._field_inits(anon, obj)
            obj.tag = {"outer": fr.this, "env": fr}
            if sup is None:
                obj.tag["lib"] = base
            return obj
        if ci is not None:
            if ci.kind == "enum":
                return UNK
            if ci.kind == "interface" or "abstract" in ci.decl.mods:
                return UNK
            obj = JObj(ci, self.default_fields(ci))
            if (
                ci.outer is not None
                and "static" not in ci.decl.mods
                and ci.kind != "enum"
            ):
                obj.tag = {"outer": fr.this}
            saved_o = self.origin
            self.origin = "new"
            try:
                self._run_ctor(ci, obj, args, caller, fr)
            finally:
                self.origin = saved_o
            return obj
        return lib.new_lib(self, base, tname, args, fr)

    def ev_call(self, e, fr):
        """Вычисляет вызов метода."""
        name = e.name
        caller = fr.method
        # --- целевой объект
        if e.obj is None:
            args = [self.ev(a, fr) for a in e.args]
            return self.call_implicit(name, args, fr)
        if isinstance(e.obj, Super):
            args = [self.ev(a, fr) for a in e.args]
            this = self.ev_this(e.obj, fr)
            sup = self.p.super_of(fr.cls)
            cands = []
            if sup is not None:
                cands = [
                    m for m in self.p.find_methods(sup, name) if not m.abstract
                ]
            if not cands:
                for i in self.p.ifaces_of(fr.cls):
                    cands += [
                        m
                        for m in self.p.find_methods(i, name)
                        if not m.abstract
                    ]
            mi = self.pick_overload(cands, args)
            if mi is not None:
                return self.invoke(mi, this, args, caller)
            return lib.call_object_default(self, this, name, args)
        if isinstance(e.obj, Name) and self._is_pkg(e.obj.id, fr):
            recv = StaticRef(None, e.obj.id)
        elif isinstance(e.obj, FieldAcc) and self._pkg_chain(e.obj, fr):
            recv = StaticRef(
                self.p.lookup_fqn(fr.module, self._pkg_chain(e.obj, fr)),
                e.obj.name,
            )
        else:
            recv = self.ev(e.obj, fr)
        args = [self.ev(a, fr) for a in e.args]
        return self.call_on(recv, name, args, fr, e)

    def _pkg_chain(self, fa, fr):
        """a.b.C -> 'a.b.C', если цепочка начинается с пакета."""
        parts, cur = [], fa
        while isinstance(cur, FieldAcc):
            parts.append(cur.name)
            cur = cur.obj
        if isinstance(cur, Name) and self._is_pkg(cur.id, fr):
            parts.append(cur.id)
            return ".".join(reversed(parts))
        return None

    def call_implicit(self, name, args, fr):
        """Вызывает метод без получателя: у this, внешнего или родителя."""
        caller = fr.method
        this = fr.this
        f = fr
        while this is None and f is not None:
            this = f.this
            f = f.up
        # 1. виртуально у this
        obj = this
        guard = 0
        ci = fr.cls
        while ci is not None and guard < 6:
            guard += 1
            cands = [
                m for m in self.p.find_methods(ci, name) if not m.abstract
            ]
            if cands:
                mi = self.pick_overload(cands, args)
                if mi is not None:
                    if mi.static:
                        return self.invoke(mi, None, args, caller)
                    tgt = obj
                    if isinstance(tgt, JObj):
                        # переопределение в классе объекта
                        ok, r = self.call_virtual(tgt, name, args, caller)
                        if ok:
                            return r
                    return self.invoke(mi, tgt, args, caller)
            # анонимный/внутренний: пробуем внешний объект
            if (
                isinstance(obj, JObj)
                and isinstance(obj.tag, dict)
                and obj.tag.get("outer") is not None
            ):
                obj = obj.tag["outer"]
            ci = ci.outer
        if isinstance(this, JObj):
            ok, r = self.call_virtual(this, name, args, caller)
            if ok:
                return r
            r = lib.call_object_default(self, this, name, args)
            if r is not NOTFOUND:
                return r
        # статический импорт: import static a.b.C.name / a.b.C.*
        for static, q in fr.cls.imports if fr.cls is not None else ():
            if not static:
                continue
            head, _, member = q.rpartition(".")
            if member == name or member == "*":
                tci = self.p.lookup_fqn(fr.module, head)
                if tci is not None:
                    ok, r = self.call_static(tci, name, args, caller)
                    if ok:
                        return r
                else:
                    return lib.static_call(
                        self, head.split(".")[-1], name, args, fr
                    )
        self.warn(f"implicit? {name}")
        return UNK

    def call_on(self, recv, name, args, fr, node=None):
        """Вызывает метод ``name`` у получателя ``recv``."""
        caller = fr.method
        if recv is UNK:
            return UNK
        if isinstance(recv, StaticRef):
            if recv.ci is not None:
                ok, r = self.call_static(recv.ci, name, args, caller)
                if ok:
                    return r
                # enum values()/valueOf, статические методы Lombok и т.д.
                return lib.static_project(self, recv.ci, name, args)
            return lib.static_call(self, recv.name, name, args, fr)
        if recv is None:
            self.warn(f"NPE call {name}")
            where = fr.cls.file.split("/")[-1] if fr.cls else "?"
            line = getattr(node, "line", "?")
            raise JavaThrow(
                self.make_exc(
                    "NullPointerException",
                    f"call {name} on null @{where}:{line}",
                )
            )
        if isinstance(recv, JObj):
            ok, r = self.call_virtual(recv, name, args, caller)
            if ok:
                return r
            r = lib.call_object_default(self, recv, name, args)
            if r is not NOTFOUND:
                return r
            self.warn(f"method? {recv.cls.name}.{name}")
            return UNK
        if isinstance(recv, JEnum):
            ci = recv.cls
            ok, r = False, None
            cands = [
                m for m in self.p.find_methods(ci, name) if not m.abstract
            ]
            mi = self.pick_overload(cands, args)
            if mi is not None:
                return self.invoke(mi, recv, args, caller)
            r = lib.enum_default(self, recv, name, args)
            if r is not NOTFOUND:
                return r
            return UNK
        return lib.call_builtin(self, recv, name, args, fr, node)

    def ev_new_lambda_call(self, fn, args, fr=None):
        """Вызывает функциональное значение: лямбду или ссылку на метод.

        Подходит и объект проекта с единственным методом.
        """
        if isinstance(fn, JLambda):
            f2 = Frame(fn.frame.method, fn.frame.this, fn.frame.cls, up=fn.env)
            for p, a in zip(fn.params, args):
                f2.locals[p] = a
            if isinstance(fn.body, Block):
                try:
                    self.ex(fn.body, f2)
                except ReturnEx as r:
                    return r.value
                return None
            return self.ev(fn.body, f2)
        if isinstance(fn, JMethodRef):
            o = fn.obj
            if isinstance(o, StaticRef):
                if o.ci is not None:
                    if fn.name == "new":
                        return self.instantiate(o.ci, args, None)
                    ok, r = self.call_static(o.ci, fn.name, args, None)
                    if ok:
                        return r
                    if args:
                        return self.call_on(
                            args[0],
                            fn.name,
                            args[1:],
                            (
                                self.stack[-1]
                                if self.stack
                                else Frame(None, None, None)
                            ),
                        )
                    return UNK
                return lib.static_call_ref(self, o.name, fn.name, args)
            if args and o is None:
                return UNK
            return self.call_on(
                o,
                fn.name,
                args,
                self.stack[-1] if self.stack else Frame(None, None, None),
            )
        if isinstance(fn, JObj):
            for m in self.p.supertypes(fn.cls):
                for ms in m.methods.values():
                    for mi in ms:
                        if not mi.abstract and len(mi.params) == len(args):
                            return self.invoke(mi, fn, args, None)
        return UNK

    # ------------------------------------------------------------------------------------------
    # вспомогательное
    def to_str(self, v, implicit=True):
        """Возвращает строку значения; явный toString класса исполняется."""
        return lib.to_str(self, v)


def expr_text(e, depth=0):
    """Возвращает короткий текст выражения для журнала и эвристик."""
    if depth > 6:
        return "…"
    t = type(e)
    if t is Lit:
        return repr(e.val)
    if t is Name:
        return e.id
    if t is FieldAcc:
        return expr_text(e.obj, depth + 1) + "." + e.name
    if t is Call:
        return (
            (expr_text(e.obj, depth + 1) + "." if e.obj is not None else "")
            + e.name
            + "("
            + ",".join(expr_text(a, depth + 1) for a in e.args)
            + ")"
        )
    if t is Binary:
        return (
            f"({expr_text(e.l, depth + 1)} {e.op} {expr_text(e.r, depth + 1)})"
        )
    if t is Unary:
        return e.op + expr_text(e.e, depth + 1)
    if t is New:
        return "new " + e.type
    if t is Cast:
        return expr_text(e.e, depth + 1)
    if t is Cond:
        return expr_text(e.c, depth + 1) + "?"
    if t is Index:
        return expr_text(e.obj, depth + 1) + "[]"
    if t is This:
        return "this"
    return t.__name__


ERR_LOG = re.compile(r"error|warn", re.I)


def branch_score(st):
    """Оценивает, насколько ветвь «ошибочная».

    Признаки ошибки: ``throw``, ``return Response(0, …)``, запись в журнал
    ошибок или предупреждений, ``return null``.
    """
    sc = 0
    stack = [st]
    while stack:
        n = stack.pop()
        if n is None:
            continue
        if isinstance(n, Throw):
            sc += 10
        elif isinstance(n, Return):
            e = n.e
            if (
                isinstance(e, New)
                and e.args
                and isinstance(e.args[0], Lit)
                and e.args[0].val == 0
                and "Response" in e.type
            ):
                sc += 10
            elif isinstance(e, Lit) and e.kind == "null":
                sc += 4
        elif (
            isinstance(n, ExprStmt)
            and isinstance(n.e, Call)
            and n.e.obj is not None
            and isinstance(n.e.obj, Name)
        ):
            if n.e.obj.id in ("LOGGER", "logger", "log") and n.e.name in (
                "error",
                "warn",
            ):
                sc += 1
        elif isinstance(n, Block):
            stack.extend(n.stmts)
        elif isinstance(n, If):
            stack.append(n.then)
            stack.append(n.els)
        elif isinstance(n, (For, ForEach, While, DoWhile)):
            stack.append(n.body)
        elif isinstance(n, Try):
            stack.append(n.body)
    return sc


def heuristic_polarity(txt):
    """Угадывает по тексту условия, чаще ли оно истинно.

    Применяется, когда обе ветви одинаково «безошибочны».
    """
    t = txt
    if (
        re.search(
            r"isPresent\(\)|!= *None|isEmpty\(\)\)|\.size\(\) *>|>= *1", t
        )
        and "!" not in t[:2]
    ):
        return True
    if re.search(r"== *None|isEmpty\(\)|\.size\(\) *==|<= *0", t):
        return False
    return True


Interp._ex_table = {
    Block: Interp.ex_block,
    LocalVar: Interp.ex_local,
    ExprStmt: Interp.ex_expr,
    If: Interp.ex_if,
    While: Interp.ex_while,
    DoWhile: Interp.ex_dowhile,
    For: Interp.ex_for,
    ForEach: Interp.ex_foreach,
    Return: Interp.ex_return,
    Throw: Interp.ex_throw,
    Break: Interp.ex_break,
    Continue: Interp.ex_continue,
    Try: Interp.ex_try,
    Switch: Interp.ex_switch,
    Sync: Interp.ex_sync,
    Labeled: Interp.ex_labeled,
    Empty: Interp.ex_noop,
    Assert: Interp.ex_assert,
    LocalClass: Interp.ex_noop,
}
Interp._ev_table = {
    Lit: Interp.ev_lit,
    Name: Interp.ev_name,
    FieldAcc: Interp.ev_field,
    Call: Interp.ev_call,
    New: Interp.ev_new,
    NewArray: Interp.ev_newarray,
    ArrayLit: Interp.ev_arraylit,
    Index: Interp.ev_index,
    Unary: Interp.ev_unary,
    Postfix: Interp.ev_postfix,
    Binary: Interp.ev_binary,
    Assign: Interp.ev_assign,
    Cond: Interp.ev_cond,
    Cast: Interp.ev_cast,
    InstanceOf: Interp.ev_instanceof,
    Lambda: Interp.ev_lambda,
    MethodRef: Interp.ev_methodref,
    This: Interp.ev_this,
    Super: Interp.ev_super,
    ClassLit: Interp.ev_classlit,
    TypeExpr: Interp.ev_typeexpr,
    Switch: Interp.ev_switchexpr,
}
