"""Эмуляция используемого проектом подмножества JDK / Spring / Jackson."""

import datetime
import decimal
import functools
import math
import re
from decimal import Decimal

from .values import (
    NOTFOUND,
    UNK,
    JavaThrow,
    JCal,
    JClass,
    JDate,
    JEnum,
    JLambda,
    JList,
    JMap,
    JMethodRef,
    JObj,
    JOpt,
    JSet,
    LibObj,
)

UNK_CH = "￾"  # маркер неизвестного фрагмента внутри строки


class UUIDStr(str):
    """Строка UUID: результат ``UUID.randomUUID()`` и ``UUID.toString()``."""


class JsonStr(str):
    """Строка JSON, которая помнит исходный объект.

    Так ``readValue`` после ``writeValueAsString`` возвращает тот же объект.
    """

    obj = None


def has_unk(s):
    """Проверяет, содержит ли строка неизвестную часть (символ UNK_CH)."""
    return isinstance(s, str) and UNK_CH in s


def is_num(x):
    """Проверяет, что значение — число Java (не логическое)."""
    return isinstance(x, (int, float, Decimal)) and not isinstance(x, bool)


# ---------------------------------------------------------------------------------------------
# арифметика
def arith(op, a, b):
    """Выполняет арифметическую операцию Java над числами."""
    if a is UNK or b is UNK:
        return UNK
    if a is None or b is None:
        return UNK
    try:
        if op == "+":
            if isinstance(a, str) or isinstance(b, str):
                return str(a) + str(b)
            return (
                _num(a) + _num(b)
                if not (isinstance(a, Decimal) or isinstance(b, Decimal))
                else Decimal(a) + Decimal(b)
            )
        if op == "-":
            return (
                a - b
                if not (isinstance(a, Decimal) ^ isinstance(b, Decimal))
                else Decimal(a) - Decimal(b)
            )
        if op == "*":
            return (
                a * b
                if not (isinstance(a, Decimal) ^ isinstance(b, Decimal))
                else Decimal(a) * Decimal(b)
            )
        if op == "/":
            if isinstance(a, int) and isinstance(b, int):
                if b == 0:
                    return UNK
                q = abs(a) // abs(b)
                return q if (a >= 0) == (b >= 0) else -q
            if b == 0:
                return UNK
            return a / b
        if op == "%":
            if b == 0:
                return UNK
            if isinstance(a, int) and isinstance(b, int):
                return int(math.fmod(a, b))
            return math.fmod(a, b)
        if op == "<<":
            return a << b
        if op == ">>" or op == ">>>":
            return a >> b
        if op == "&":
            return a & b
        if op == "|":
            return a | b
        if op == "^":
            return a ^ b
    except (TypeError, ValueError, decimal.InvalidOperation, OverflowError):
        return UNK
    return UNK


def _num(x):
    return x


def binop(it, op, left, right):
    """Выполняет бинарный оператор Java, включая конкатенацию строк."""
    if op == "+":
        if isinstance(left, str) or isinstance(right, str):
            if left is UNK or right is UNK:
                return (to_str(it, left) if left is not UNK else UNK_CH) + (
                    to_str(it, right) if right is not UNK else UNK_CH
                )
            return to_str(it, left) + to_str(it, right)
        return arith(op, left, right)
    if op in ("-", "*", "/", "%", "<<", ">>", ">>>"):
        return arith(op, left, right)
    if op in ("&", "|", "^"):
        if isinstance(left, bool) and isinstance(right, bool):
            return (
                (left and right)
                if op == "&"
                else ((left or right) if op == "|" else (left != right))
            )
        return arith(op, left, right)
    if op in ("==", "!="):
        eq = java_eq(left, right)
        if eq is UNK:
            return UNK
        return eq if op == "==" else (not eq)
    if op in ("<", ">", "<=", ">="):
        if left is UNK or right is UNK or left is None or right is None:
            return UNK
        try:
            if isinstance(left, (JDate,)):
                left, right = left.dt, right.dt
            if op == "<":
                return left < right
            if op == ">":
                return left > right
            if op == "<=":
                return left <= right
            return left >= right
        except TypeError:
            return UNK
    return UNK


def java_eq(a, b):
    """Сравнивает значения оператором ``==`` по правилам Java."""
    if a is UNK or b is UNK:
        return UNK
    if a is None or b is None:
        return a is b
    if isinstance(a, str) and isinstance(b, str):
        if has_unk(a) or has_unk(b):
            return UNK
        return a == b
    if is_num(a) and is_num(b):
        return a == b
    if isinstance(a, bool) and isinstance(b, bool):
        return a == b
    if isinstance(a, (JEnum, JObj, list, dict, LibObj)):
        return a is b
    try:
        return a == b
    except Exception:
        return UNK


def obj_equals(it, a, b):
    """equals(): строки по значению; JObj — через проектный equals / Lombok."""
    if a is UNK or b is UNK:
        return UNK
    if a is None:
        return UNK
    if isinstance(a, JObj):
        cands = [
            m
            for m in it.p.find_methods(a.cls, "equals")
            if not m.abstract and len(m.params) == 1
        ]
        if cands:
            return it.lib_invoke(cands[0], a, [b])
        return lombok_equals(it, a, b)
    if isinstance(a, str) and isinstance(b, str):
        if has_unk(a) or has_unk(b):
            return UNK
        return a == b
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return False
        for x, y in zip(a, b):
            e = obj_equals(it, x, y)
            if e is UNK:
                return UNK
            if not e:
                return False
        return True
    if a is b:
        return True
    if is_num(a) and is_num(b):
        return a == b
    try:
        return a == b
    except Exception:
        return False


def lombok_equals(it, a, b):
    """Сравнивает объекты, как ``equals`` из Lombok (@Data, @Value)."""
    if a is b:
        return True
    if not isinstance(b, JObj) or a.cls is not b.cls:
        return False
    if not ({"Data", "EqualsAndHashCode", "Value"} & a.cls.annots.keys()):
        return False
    for k, v in a.f.items():
        e = (
            obj_equals(it, v, b.f.get(k))
            if v is not None
            else (b.f.get(k) is None)
        )
        if e is UNK:
            return UNK
        if not e:
            return False
    return True


def instance_of(v, t):
    """Проверяет ``v instanceof t`` для библиотечного типа ``t``."""
    t = t.split(".")[-1]
    if t == "Object":
        return True
    if isinstance(v, bool):
        return t == "Boolean"
    if isinstance(v, int):
        return t in ("Integer", "Long", "Short", "Number", "Byte")
    if isinstance(v, float):
        return t in ("Double", "Float", "Number")
    if isinstance(v, str):
        return t in ("String", "CharSequence")
    if isinstance(v, list):
        return t in (
            "List",
            "ArrayList",
            "Collection",
            "Iterable",
            "LinkedList",
        )
    if isinstance(v, dict):
        return t in ("Map", "HashMap", "LinkedHashMap", "Set", "HashSet")
    return False


# ---------------------------------------------------------------------------------------------
# строки
def java_double_str(x):
    """Возвращает строку числа ``double`` так, как её печатает Java."""
    if x != x:
        return "NaN"
    if x in (float("inf"), float("-inf")):
        return "Infinity" if x > 0 else "-Infinity"
    if x == int(x) and abs(x) < 1e7:
        return f"{int(x)}.0"
    r = repr(float(x))
    if "e" in r:
        m, e = r.split("e")
        if "." not in m:
            m += ".0"
        return f"{m}E{int(e)}"
    return r


def to_str(it, v):
    """Переводит значение в строку, как ``String.valueOf`` в Java.

    Для объектов проекта вызывается явный ``toString`` (он исполняется) или
    строится строка Lombok.
    """
    if v is None:
        return "null"
    if v is UNK:
        return UNK_CH
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return str(v)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return java_double_str(v)
    if isinstance(v, Decimal):
        return format(v, "f")
    if isinstance(v, list):
        return "[" + ", ".join(to_str(it, x) for x in v) + "]"
    if isinstance(v, dict):
        if isinstance(v, JSet):
            return "[" + ", ".join(to_str(it, x) for x in v) + "]"
        return (
            "{"
            + ", ".join(
                f"{to_str(it, k)}={to_str(it, x)}" for k, x in v.items()
            )
            + "}"
        )
    if isinstance(v, JObj):
        if it is not None:
            cands = [
                m
                for m in it.p.find_methods(v.cls, "toString")
                if not m.abstract and not m.params
            ]
            if cands:
                r = it.lib_invoke(cands[0], v, [])
                return r if isinstance(r, str) else UNK_CH
        return lombok_str(it, v)
    if isinstance(v, JEnum):
        cands = (
            [m for m in it.p.find_methods(v.cls, "toString") if not m.abstract]
            if it is not None
            else []
        )
        if cands:
            return to_str(it, it.invoke(cands[0], v, [], None))
        return v.name
    if isinstance(v, JDate):
        return v.dt.strftime("%a %b %d %H:%M:%S CST %Y")
    if isinstance(v, JOpt):
        return (
            "Optional.empty" if v.v is None else f"Optional[{to_str(it, v.v)}]"
        )
    if isinstance(v, LibObj):
        if v.kind == "SB":
            return "".join(v.f["parts"])
        if v.kind == "ResponseEntity":
            return "<200 OK," + to_str(it, v.f.get("body")) + ">"
        if v.kind == "HttpStatus":
            return v.f["name"]
        return f"{v.kind}@1"
    return UNK_CH


_STR_DEPTH = [0]


def lombok_str(it, o):
    """Строит строку объекта, как ``toString`` из Lombok (@ToString, @Data).

    Поля перечисляются по порядку; если у поля есть явный геттер, Lombok
    вызывает его, и геттер исполняется.
    """
    ci = o.cls
    lombok = bool({"Data", "ToString", "Value"} & ci.annots.keys())
    if not lombok or it is None or _STR_DEPTH[0] > 6:
        return (
            ci.name
            + "("
            + ", ".join(f"{k}={to_str(it, v)}" for k, v in o.f.items())
            + ")"
        )
    _STR_DEPTH[0] += 1
    it.lombok_depth += 1
    try:
        parts = []
        for f in ci.fields.values():
            if f.static:
                continue
            val = o.f.get(f.name)
            cap = f.name[0].upper() + f.name[1:]
            for gname in ("get" + cap, "is" + cap):
                g = [
                    m
                    for m in it.p.find_methods(ci, gname)
                    if not m.abstract and not m.params and not m.static
                ]
                if g:
                    val = it.lib_invoke(g[0], o, [])
                    break
            parts.append(f"{f.name}={to_str(it, val)}")
        return ci.name + "(" + ", ".join(parts) + ")"
    finally:
        _STR_DEPTH[0] -= 1
        it.lombok_depth -= 1


def java_format(it, fmt, args):
    """String.format: %s %d %f %.2f %n %%."""
    if has_unk(fmt):
        return UNK_CH
    out, i, ai = [], 0, 0
    while i < len(fmt):
        c = fmt[i]
        if c != "%":
            out.append(c)
            i += 1
            continue
        m = re.match(r"%(\d+\$)?([-+ 0,#]*)(\d+)?(\.\d+)?([a-zA-Z%])", fmt[i:])
        if not m:
            out.append(c)
            i += 1
            continue
        conv = m.group(5)
        i += m.end()
        if conv == "%":
            out.append("%")
            continue
        if conv == "n":
            out.append("\n")
            continue
        a = args[ai] if ai < len(args) else UNK
        ai += 1
        if a is UNK:
            out.append(UNK_CH)
            continue
        flags, width, prec = m.group(2) or "", m.group(3), m.group(4)
        if conv in "sS":
            s = to_str(it, a)
        elif conv in "dx":
            s = (
                format(
                    int(a),
                    "x" if conv == "x" else ("," if "," in flags else "d"),
                )
                if is_num(a)
                else UNK_CH
            )
        elif conv in "fF":
            p = int(prec[1:]) if prec else 6
            s = f"{float(a):.{p}f}" if is_num(a) else UNK_CH
        else:
            s = to_str(it, a)
        if width:
            s = (
                s.rjust(int(width), "0" if "0" in flags else " ")
                if "-" not in flags
                else s.ljust(int(width))
            )
        out.append(s)
    return "".join(out)


# ---------------------------------------------------------------------------------------------
# статические поля
CAL = {
    "YEAR": 1,
    "MONTH": 2,
    "WEEK_OF_YEAR": 3,
    "DATE": 5,
    "DAY_OF_MONTH": 5,
    "DAY_OF_YEAR": 6,
    "DAY_OF_WEEK": 7,
    "HOUR": 10,
    "HOUR_OF_DAY": 11,
    "MINUTE": 12,
    "SECOND": 13,
    "MILLISECOND": 14,
}
HTTP_STATUS = {
    "OK": 200,
    "CREATED": 201,
    "ACCEPTED": 202,
    "NO_CONTENT": 204,
    "BAD_REQUEST": 400,
    "UNAUTHORIZED": 401,
    "FORBIDDEN": 403,
    "NOT_FOUND": 404,
    "INTERNAL_SERVER_ERROR": 500,
    "CONFLICT": 409,
}


def static_field(it, cname, field):
    """Возвращает значение статического поля библиотечного класса."""
    if cname == "HttpMethod":
        return field
    if cname == "HttpStatus":
        return LibObj("HttpStatus", name=field, code=HTTP_STATUS.get(field, 0))
    if cname == "Calendar":
        return CAL.get(field, 0)
    if cname == "Integer":
        return {"MAX_VALUE": 2147483647, "MIN_VALUE": -2147483648}.get(
            field, UNK
        )
    if cname == "Long":
        return {
            "MAX_VALUE": 9223372036854775807,
            "MIN_VALUE": -9223372036854775808,
        }.get(field, UNK)
    if cname == "Double":
        return {"MAX_VALUE": 1.7976931348623157e308, "MIN_VALUE": 5e-324}.get(
            field, UNK
        )
    if cname == "Float":
        return {"MAX_VALUE": 3.4028234663852886e38, "MIN_VALUE": 1.4e-45}.get(
            field, UNK
        )
    if cname == "Boolean":
        return {"TRUE": True, "FALSE": False}.get(field, UNK)
    if cname == "BigDecimal":
        return {"ZERO": Decimal(0), "ONE": Decimal(1), "TEN": Decimal(10)}.get(
            field, UNK
        )
    if cname == "System":
        return LibObj("PrintStream")
    if cname == "HttpHeaders":
        return {
            "AUTHORIZATION": "Authorization",
            "CONTENT_TYPE": "Content-Type",
            "ACCEPT": "Accept",
        }.get(field, field)
    if cname == "MediaType":
        return field
    if cname == "Locale":
        return field
    if cname == "TimeUnit":
        return LibObj("TimeUnit", name=field)
    return UNK


# ---------------------------------------------------------------------------------------------
# создание объектов
def new_lib_bean(tname, it):
    """Создаёт библиотечный бин Spring (RestTemplate и т. п.)."""
    base = tname.split(".")[-1]
    return LibObj(base)


def new_lib(it, base, tname, args, fr):
    """Создаёт объект библиотечного класса оператором ``new``."""
    b = base.split(".")[-1]
    if b in (
        "ArrayList",
        "LinkedList",
        "Vector",
        "CopyOnWriteArrayList",
        "Stack",
    ):
        if args and isinstance(args[0], list):
            return JList(args[0])
        if args and isinstance(args[0], JSet):
            return JList(args[0].values())
        if args and isinstance(args[0], dict):
            return JList(args[0].keys())
        return JList()
    if b in (
        "HashMap",
        "LinkedHashMap",
        "TreeMap",
        "ConcurrentHashMap",
        "Hashtable",
        "IdentityHashMap",
        "WeakHashMap",
    ):
        return JMap(args[0]) if args and isinstance(args[0], dict) else JMap()
    if b in ("HashSet", "LinkedHashSet", "TreeSet", "CopyOnWriteArraySet"):
        s = JSet()
        if args and isinstance(args[0], JSet):
            for x in args[0].values():
                s[hk(x)] = x
        elif args and isinstance(args[0], (list, dict)):
            for x in args[0]:
                s[hk(x)] = x
        return s
    if b == "Date":
        if len(args) >= 3 and all(isinstance(x, int) for x in args):
            # устаревший конструктор Date(year-1900, month, day[, hours,
            # minutes, seconds])
            y, m, d = args[0] + 1900, args[1], args[2]
            hh, mi, ss = (list(args[3:6]) + [0, 0, 0])[:3]
            tm = y * 12 + m
            y, m = divmod(tm, 12)
            try:
                dt = datetime.datetime(y, m + 1, 1) + datetime.timedelta(
                    days=d - 1, hours=hh, minutes=mi, seconds=ss
                )
            except (ValueError, OverflowError):
                return UNK
            return JDate(dt)
        if args and isinstance(args[0], int):
            return JDate(
                datetime.datetime(1970, 1, 1)
                + datetime.timedelta(milliseconds=args[0])
            )
        return JDate(it.now)
    if b in ("StringBuilder", "StringBuffer"):
        parts = (
            [to_str(it, args[0])] if args and isinstance(args[0], str) else []
        )
        return LibObj("SB", parts=parts)
    if b == "Object":
        return LibObj("Object")
    if b == "BigDecimal":
        if args and args[0] is not UNK and args[0] is not None:
            a0 = args[0]
            if isinstance(a0, str):
                if has_unk(a0):
                    return UNK
                try:
                    return (
                        Decimal(a0.strip())
                        if re.fullmatch(
                            r"\s*[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?\s*", a0
                        )
                        else _raise_nfe(it)
                    )
                except decimal.InvalidOperation:
                    return _raise_nfe(it)
            try:
                return Decimal(a0)
            except (decimal.InvalidOperation, TypeError):
                return UNK
        return UNK
    if b == "DecimalFormat":
        return LibObj("DecimalFormat", pattern=args[0] if args else "#")
    if b in ("BigInteger",):
        return (
            int(args[0]) if args and isinstance(args[0], (str, int)) else UNK
        )
    if b == "ResponseEntity":
        body = args[0] if args else None
        st = (
            args[-1]
            if len(args) >= 2
            else LibObj("HttpStatus", name="OK", code=200)
        )
        return LibObj("ResponseEntity", body=body, status=st)
    if b == "HttpEntity":
        body = headers = None
        if len(args) == 1:
            if isinstance(args[0], LibObj) and args[0].kind == "HttpHeaders":
                headers = args[0]
            else:
                body = args[0]
        elif len(args) >= 2:
            body, headers = args[0], args[1]
        return LibObj("HttpEntity", body=body, headers=headers)
    if b == "HttpHeaders":
        return LibObj("HttpHeaders", map=JMap())
    if b == "ParameterizedTypeReference":
        from .model import type_args

        ta = type_args(tname)
        return LibObj(
            "PTR",
            type=ta[0] if ta else None,
            ctx=fr.cls if fr is not None else None,
        )
    if b == "SimpleDateFormat":
        return LibObj(
            "SDF", pattern=args[0] if args else "yyyy-MM-dd HH:mm:ss"
        )
    if b == "Random":
        return LibObj("Random")
    if b in ("String",):
        return args[0] if args and isinstance(args[0], str) else ""
    if b in ("Integer", "Long", "Short", "Byte"):
        return (
            int(args[0])
            if args
            and is_num(args[0])
            or (
                args
                and isinstance(args[0], str)
                and re.fullmatch(r"-?\d+", args[0])
            )
            else UNK
        )
    if b in ("Double", "Float"):
        return float(args[0]) if args and is_num(args[0]) else UNK
    if b == "Boolean":
        return args[0] if args and isinstance(args[0], bool) else False
    if b == "RestTemplate":
        return LibObj("RestTemplate")
    if b == "ObjectMapper":
        return LibObj("ObjectMapper")
    if b == "UsernamePasswordAuthenticationToken":
        return LibObj(
            "AuthToken",
            principal=args[0] if args else None,
            credentials=args[1] if len(args) > 1 else None,
        )
    if b.endswith("Exception") or b.endswith("Error"):
        o = it.make_exc(b, None)
        for a in args:
            if isinstance(a, str):
                o.f["message"] = a
                break
        if args and isinstance(args[-1], JObj):
            o.f["cause"] = args[-1]
        return o
    if b in ("Thread",):
        return LibObj("Thread", target=args[0] if args else None)
    if b == "AtomicInteger" or b == "AtomicLong":
        return LibObj("Atomic", v=args[0] if args else 0)
    return LibObj(b, args=args)


def _raise_nfe(it):
    raise JavaThrow(
        it.make_exc(
            "NumberFormatException", "Character array is missing exponent mark"
        )
    )


def hk(x):
    """Ключ для Set/Map: JObj и прочее хешируемое по идентичности."""
    if isinstance(x, (list, dict)):
        return id(x)
    try:
        hash(x)
        return x
    except TypeError:
        return id(x)


# ---------------------------------------------------------------------------------------------
# статические вызовы
def static_call(it, cname, name, args, fr):
    """Выполняет вызов статического метода библиотечного класса."""
    c = cname.split(".")[-1]
    f = _STATIC.get((c, name))
    if f is not None:
        return f(it, args, fr)
    g = _STATIC_CLASS.get(c)
    if g is not None:
        return g(it, name, args, fr)
    it.warn(f"static? {c}.{name}")
    return UNK


def static_call_ref(it, cname, name, args):
    """Выполняет ссылку на статический метод (``Класс::метод``)."""
    c = cname.split(".")[-1]
    if (c, name) in _STATIC:
        return _STATIC[(c, name)](it, args, None)
    if args:
        return call_builtin(it, args[0], name, args[1:], None, None)
    return UNK


def _uuid_random(it, a, fr):
    return UUIDStr(it.new_uuid())


def _uuid_from(it, a, fr):
    return UUIDStr(a[0]) if a and isinstance(a[0], str) else UNK


def _as_list(it, a, fr):
    if len(a) == 1 and isinstance(a[0], list):
        return JList(a[0])
    return JList(a)


def _empty_list(it, a, fr):
    return JList()


def _empty_map(it, a, fr):
    return JMap()


def _parse_int(it, a, fr):
    s = a[0] if a else UNK
    if s is UNK or s is None or has_unk(s):
        return UNK
    try:
        return int(str(s).strip())
    except ValueError:
        raise JavaThrow(
            it.make_exc("NumberFormatException", f'For input string: "{s}"')
        )


def _parse_double(it, a, fr):
    s = a[0] if a else UNK
    if s is UNK or s is None or has_unk(s):
        return UNK
    try:
        return float(str(s).strip())
    except ValueError:
        raise JavaThrow(
            it.make_exc("NumberFormatException", f'For input string: "{s}"')
        )


def _string_valueof(it, a, fr):
    x = a[0] if a else UNK
    if isinstance(x, list) and all(isinstance(c, str) for c in x):
        return "".join(x)
    return to_str(it, x)


def _objects_equals(it, a, fr):
    if a[0] is None or a[1] is None:
        return a[0] is a[1]
    return obj_equals(it, a[0], a[1])


def _sort(it, a, fr):
    lst = a[0]
    if not isinstance(lst, list):
        return None
    cmp = a[1] if len(a) > 1 else None
    _sort_list(it, lst, cmp)
    return None


def _sort_list(it, lst, cmp):

    if cmp is None:
        try:
            lst.sort()
        except TypeError:
            pass
        return

    def c(x, y):
        r = it.ev_new_lambda_call(cmp, [x, y])
        return r if isinstance(r, int) and not isinstance(r, bool) else 0

    lst.sort(key=functools.cmp_to_key(c))


def _msg_format(it, a, fr):
    pat = a[0]
    if not isinstance(pat, str):
        return UNK_CH
    args = a[1:]
    if len(args) == 1 and isinstance(args[0], list):
        args = args[0]

    def rep(m):
        i = int(m.group(1))
        return to_str(it, args[i]) if i < len(args) else m.group(0)

    return re.sub(r"\{(\d+)\}", rep, pat)


def _logger_factory(it, a, fr):
    return LibObj("Logger")


def _resp_ok(it, a, fr):
    if a:
        return LibObj(
            "ResponseEntity",
            body=a[0],
            status=LibObj("HttpStatus", name="OK", code=200),
        )
    return LibObj(
        "REBuilder", status=LibObj("HttpStatus", name="OK", code=200)
    )


def _resp_status(it, a, fr):
    return LibObj("REBuilder", status=a[0] if a else UNK)


def _resp_simple(code, name):
    def f(it, a, fr):
        return LibObj(
            "REBuilder", status=LibObj("HttpStatus", name=name, code=code)
        )

    return f


def _optional_of(it, a, fr):
    return JOpt(a[0])


def _optional_empty(it, a, fr):
    return JOpt(None)


def _cal_instance(it, a, fr):
    return JCal(it.now)


def _now_ms(it, a, fr):
    return int((it.now - datetime.datetime(1970, 1, 1)).total_seconds() * 1000)


def _math(fn):
    def f(it, a, fr):
        if any(x is UNK or x is None for x in a):
            return UNK
        return fn(*a)

    return f


def _str_empty(it, a, fr):
    s = a[0] if a else UNK
    if s is UNK:
        return UNK
    return s is None or s == ""


def _str_hastext(it, a, fr):
    s = a[0] if a else UNK
    if s is UNK:
        return UNK
    return s is not None and str(s).strip() != ""


def _collectors(kind):
    def f(it, a, fr):
        return LibObj("Collector", ckind=kind, args=a)

    return f


def _noop(it, a, fr):
    return None


def _sec_ctx(it, a, fr):
    return LibObj("SecurityContext")


def _boolean_valueof(it, a, fr):
    x = a[0] if a else UNK
    if isinstance(x, str):
        return x.lower() == "true"
    return x


def _int_tostring(it, a, fr):
    return to_str(it, a[0]) if a else UNK


def _list_copy(it, a, fr):
    return JList(a[0]) if a and isinstance(a[0], list) else a[0] if a else UNK


_STATIC = {
    ("UUID", "randomUUID"): _uuid_random,
    ("UUID", "fromString"): _uuid_from,
    ("Arrays", "asList"): _as_list,
    ("List", "of"): _as_list,
    ("Collections", "emptyList"): _empty_list,
    ("Collections", "emptyMap"): _empty_map,
    ("Collections", "singletonList"): _as_list,
    ("Collections", "unmodifiableList"): _list_copy,
    ("Collections", "sort"): _sort,
    ("Arrays", "sort"): _sort,
    ("Collections", "reverse"): lambda it, a, fr: (
        a[0].reverse() if isinstance(a[0], list) else None,
        None,
    )[1],
    ("Integer", "parseInt"): _parse_int,
    ("Integer", "valueOf"): _parse_int,
    ("Long", "parseLong"): _parse_int,
    ("Long", "valueOf"): _parse_int,
    ("Double", "parseDouble"): _parse_double,
    ("Double", "valueOf"): _parse_double,
    ("Float", "parseFloat"): _parse_double,
    ("Boolean", "parseBoolean"): _boolean_valueof,
    ("Boolean", "valueOf"): _boolean_valueof,
    ("String", "valueOf"): _string_valueof,
    ("String", "format"): lambda it, a, fr: java_format(
        it,
        a[0],
        a[1:] if not (len(a) == 2 and isinstance(a[1], list)) else a[1],
    ),
    ("String", "join"): lambda it, a, fr: a[0].join(
        to_str(it, x)
        for x in (a[1] if len(a) == 2 and isinstance(a[1], list) else a[1:])
    ),
    ("Integer", "toString"): _int_tostring,
    ("Double", "toString"): _int_tostring,
    ("Long", "toString"): _int_tostring,
    ("Math", "min"): _math(min),
    ("Math", "max"): _math(max),
    ("Math", "abs"): _math(abs),
    ("Math", "floor"): _math(lambda x: float(math.floor(x))),
    ("Math", "ceil"): _math(lambda x: float(math.ceil(x))),
    ("Math", "round"): _math(lambda x: int(math.floor(x + 0.5))),
    ("Math", "random"): lambda it, a, fr: it.rng.random(),
    ("Math", "pow"): _math(lambda x, y: float(x) ** y),
    ("Math", "sqrt"): _math(math.sqrt),
    ("Objects", "equals"): _objects_equals,
    ("Objects", "isNull"): lambda it, a, fr: a[0] is None,
    ("Objects", "nonNull"): lambda it, a, fr: a[0] is not None,
    ("Objects", "requireNonNull"): lambda it, a, fr: a[0],
    ("Objects", "hash"): lambda it, a, fr: UNK,
    ("System", "currentTimeMillis"): _now_ms,
    ("System", "nanoTime"): _now_ms,
    ("System", "exit"): _noop,
    ("System", "getProperty"): lambda it, a, fr: UNK,
    ("System", "getenv"): lambda it, a, fr: None,
    ("Thread", "sleep"): _noop,
    ("Calendar", "getInstance"): _cal_instance,
    ("Optional", "of"): _optional_of,
    ("Optional", "ofNullable"): _optional_of,
    ("Optional", "empty"): _optional_empty,
    ("MessageFormat", "format"): _msg_format,
    ("LoggerFactory", "getLogger"): _logger_factory,
    ("ResponseEntity", "ok"): _resp_ok,
    ("ResponseEntity", "status"): _resp_status,
    ("ResponseEntity", "badRequest"): _resp_simple(400, "BAD_REQUEST"),
    ("ResponseEntity", "notFound"): _resp_simple(404, "NOT_FOUND"),
    ("ResponseEntity", "accepted"): _resp_simple(202, "ACCEPTED"),
    ("ResponseEntity", "noContent"): _resp_simple(204, "NO_CONTENT"),
    ("StringUtils", "isEmpty"): _str_empty,
    ("StringUtils", "hasText"): _str_hastext,
    ("StringUtils", "hasLength"): _str_hastext,
    ("Collectors", "toList"): _collectors("toList"),
    ("Collectors", "toSet"): _collectors("toSet"),
    ("Collectors", "toMap"): _collectors("toMap"),
    ("Collectors", "joining"): _collectors("joining"),
    ("Collectors", "groupingBy"): _collectors("groupingBy"),
    ("Collectors", "counting"): _collectors("counting"),
    ("SecurityContextHolder", "getContext"): _sec_ctx,
    ("Character", "isDigit"): lambda it, a, fr: isinstance(a[0], str)
    and a[0].isdigit(),
    ("Character", "isLetter"): lambda it, a, fr: isinstance(a[0], str)
    and a[0].isalpha(),
    ("Stream", "of"): lambda it, a, fr: JStream(a),
    ("Jwts", "claims"): lambda it, a, fr: LibObj("Claims", map=JMap()),
    ("Jwts", "builder"): lambda it, a, fr: LibObj("JwtBuilder"),
    ("Executors", "newFixedThreadPool"): lambda it, a, fr: LibObj("Executor"),
}


class JStream(list):
    """Поток java.util.stream.Stream: элементы в порядке обхода."""


def _static_class_generic(it, name, args, fr):
    return UNK


_STATIC_CLASS = {}


# ---------------------------------------------------------------------------------------------
# проектные статические умолчания
def static_project(it, ci, name, args):
    """Выполняет встроенные статические методы перечисления проекта."""
    if ci.kind == "enum":
        st = it.statics_of(ci)
        consts = [st[n] for n in ci.enum_names]
        if name == "values":
            return JList(consts)
        if name == "valueOf":
            for c in consts:
                if c.name == args[0]:
                    return c
            raise JavaThrow(
                it.make_exc("IllegalArgumentException", "No enum constant")
            )
    if name == "builder":
        return LibObj("Builder", ci=ci, f={})
    it.warn(f"static project? {ci.name}.{name}")
    return UNK


def enum_default(it, e, name, args):
    """Выполняет встроенные методы константы перечисления."""
    if name == "name" or name == "toString":
        return e.name
    if name == "ordinal":
        return e.ordinal
    if name == "equals":
        return e is args[0]
    if name == "compareTo":
        return e.ordinal - args[0].ordinal
    if name == "hashCode":
        return e.ordinal
    if name == "getDeclaringClass":
        return JClass(e.cls)
    r = lombok_accessor(it, e, name, args)
    return r


def call_object_default(it, obj, name, args):
    """Выполняет метод объекта без явной реализации в классе.

    Это аксессоры Lombok, ``equals``, ``hashCode``, ``toString`` и
    ``getClass``.
    """
    if name == "getClass":
        return JClass(obj.cls)
    if name == "equals":
        return (
            obj_equals(it, obj, args[0])
            if isinstance(obj, JObj) and not obj.cls.module == "<lib>"
            else (obj is args[0])
        )
    if name == "hashCode":
        return hash(id(obj)) & 0x7FFFFFFF
    if name == "toString":
        return lombok_str(it, obj)
    if isinstance(obj, JObj) and obj.cls.module == "<lib>":
        if name in ("getMessage", "getLocalizedMessage"):
            return obj.f.get("message")
        if name in ("printStackTrace", "addSuppressed", "initCause"):
            return None
        if name == "getCause":
            return obj.f.get("cause")
    if (
        isinstance(obj, JObj)
        and obj.tag
        and isinstance(obj.tag, dict)
        and obj.tag.get("lib")
    ):
        return NOTFOUND
    if isinstance(obj, JObj) and it.p.supertypes(obj.cls):
        # проектное исключение, унаследованное от библиотечного
        if name in ("getMessage", "getLocalizedMessage"):
            return obj.f.get("message")
        if name in ("printStackTrace",):
            return None
        if name == "getCause":
            return obj.f.get("cause")
    return lombok_accessor(it, obj, name, args)


def lombok_accessor(it, obj, name, args):
    """Выполняет геттер или сеттер, сгенерированный Lombok."""
    f = obj.f
    m = re.match(r"^(get|is|set)([A-Z].*)$", name)
    if m:
        kind, rest = m.group(1), m.group(2)
        cands = [rest[0].lower() + rest[1:], rest, "is" + rest]
        if kind in ("get", "is"):
            for c in cands:
                if c in f:
                    return f[c]
        elif kind == "set":
            for c in cands:
                if c in f:
                    if args:
                        f[c] = args[0]
                    return None
            # builder-стиль / отсутствующее поле: создаём поле, чтобы не терять
            # значение
            if args:
                f[cands[0]] = args[0]
            return None
    # fluent: @Accessors(fluent=true)
    if name in f and not args:
        return f[name]
    return NOTFOUND


# ---------------------------------------------------------------------------------------------
# методы встроенных типов
def call_builtin(it, recv, name, args, fr, node):
    """Выполняет метод значения встроенного типа (строки, списка и т. п.)."""
    r = _call_builtin(it, recv, name, args, fr, node)
    if (
        r is UNK
        and not any(
            a is UNK or (isinstance(a, str) and has_unk(a)) for a in args
        )
        and not (isinstance(recv, str) and has_unk(recv))
    ):
        kind = "/" + recv.kind if isinstance(recv, LibObj) else ""
        it.warn(f"unk-result {type(recv).__name__}{kind}.{name}")
    return r


def _call_builtin(it, recv, name, args, fr, node):
    if isinstance(recv, str):
        return str_method(it, recv, name, args)
    if isinstance(recv, bool):
        if name == "booleanValue":
            return recv
        if name == "equals":
            return recv == args[0]
        if name == "toString":
            return "true" if recv else "false"
        return UNK
    if isinstance(recv, (int, float, Decimal)):
        return num_method(it, recv, name, args)
    if isinstance(recv, JStream):
        return stream_method(it, recv, name, args)
    if isinstance(recv, list):
        return list_method(it, recv, name, args, fr)
    if isinstance(recv, JSet):
        return set_method(it, recv, name, args, fr)
    if isinstance(recv, dict):
        return map_method(it, recv, name, args, fr)
    if isinstance(recv, JOpt):
        return opt_method(it, recv, name, args)
    if isinstance(recv, JDate):
        return date_method(it, recv, name, args)
    if isinstance(recv, JCal):
        return cal_method(it, recv, name, args)
    if isinstance(recv, JClass):
        if name in ("getSimpleName", "getName"):
            return recv.name
        if name == "equals":
            return (
                isinstance(args[0], JClass)
                and args[0].ci is recv.ci
                and args[0].name == recv.name
            )
        return UNK
    if isinstance(recv, LibObj):
        return libobj_method(it, recv, name, args, fr, node)
    if recv.__class__.__name__ == "RepoProxy":
        return it.repos.call(recv, name, args, fr)
    if isinstance(recv, (JLambda, JMethodRef)):
        return it.ev_new_lambda_call(recv, args)
    it.warn(f"builtin? {type(recv).__name__}.{name}")
    return UNK


def str_method(it, s, n, a):
    """Выполняет метод ``java.lang.String``."""
    if has_unk(s):
        if n in ("length",):
            return UNK
        if n == "toString" or n == "trim" or n == "intern":
            return s
        if n in (
            "equals",
            "equalsIgnoreCase",
            "isEmpty",
            "contains",
            "startsWith",
            "endsWith",
            "indexOf",
        ):
            return UNK
        return (
            UNK_CH
            if n
            in (
                "substring",
                "replace",
                "toLowerCase",
                "toUpperCase",
                "concat",
                "replaceAll",
            )
            else UNK
        )
    if any(x is UNK or (isinstance(x, str) and has_unk(x)) for x in a):
        return UNK
    if n == "equals":
        return isinstance(a[0], str) and s == a[0]
    if n == "equalsIgnoreCase":
        return isinstance(a[0], str) and s.lower() == a[0].lower()
    if n == "isEmpty":
        return s == ""
    if n == "isBlank":
        return s.strip() == ""
    if n == "length":
        return len(s)
    if n == "charAt":
        return s[a[0]] if 0 <= a[0] < len(s) else UNK
    if n == "substring":
        return s[a[0] : a[1]] if len(a) > 1 else s[a[0] :]
    if n == "indexOf":
        return s.find(a[0]) if isinstance(a[0], str) else s.find(chr(a[0]))
    if n == "lastIndexOf":
        return s.rfind(a[0])
    if n == "contains":
        return a[0] in s
    if n == "startsWith":
        return s.startswith(a[0])
    if n == "endsWith":
        return s.endswith(a[0])
    if n == "trim" or n == "strip":
        return s.strip()
    if n == "toLowerCase":
        return s.lower()
    if n == "toUpperCase":
        return s.upper()
    if n == "replace":
        return s.replace(to_str(it, a[0]), to_str(it, a[1]))
    if n == "replaceAll":
        return re.sub(a[0], re.sub(r"\$(\d)", r"\\\1", a[1]), s)
    if n == "split":
        parts = re.split(a[0], s)
        while parts and parts[-1] == "" and len(parts) > 1:
            parts.pop()
        return JList(parts)
    if n == "toString" or n == "intern":
        return s
    if n == "hashCode":
        h = 0
        for ch in s:
            h = (31 * h + ord(ch)) & 0xFFFFFFFF
        return h - (1 << 32) if h >= (1 << 31) else h
    if n == "compareTo":
        return (s > a[0]) - (s < a[0])
    if n == "concat":
        return s + a[0]
    if n == "matches":
        return re.fullmatch(a[0], s) is not None
    if n == "getBytes":
        return JList(s.encode("utf-8"))
    if n == "toCharArray":
        return JList(s)
    if n == "format" or n == "formatted":
        return java_format(it, s, a)
    return UNK


def num_method(it, x, n, a):
    """Выполняет метод числовой обёртки (Integer, Double, BigDecimal)."""
    if any(v is UNK for v in a):
        return UNK
    try:
        return _num_method(it, x, n, a)
    except (
        TypeError,
        ValueError,
        decimal.InvalidOperation,
        ZeroDivisionError,
    ):
        return UNK


def _num_method(it, x, n, a):
    if n in ("intValue", "longValue", "shortValue"):
        return int(x)
    if n in ("doubleValue", "floatValue"):
        return float(x)
    if n == "equals":
        return is_num(a[0]) and x == a[0] and type(x) is type(a[0])
    if n == "toString":
        return to_str(it, x)
    if n == "compareTo" or n == "compare":
        return (x > a[0]) - (x < a[0])
    if n == "hashCode":
        return int(x)
    if isinstance(x, Decimal):
        if n == "add":
            return x + Decimal(a[0])
        if n == "subtract":
            return x - Decimal(a[0])
        if n == "multiply":
            return x * Decimal(a[0])
        if n == "divide":
            return x / Decimal(a[0]) if a[0] != 0 else UNK
        if n == "setScale":
            q = Decimal(1).scaleb(-a[0])
            return x.quantize(q, rounding=decimal.ROUND_HALF_UP)
        if n == "negate":
            return -x
        if n == "abs":
            return abs(x)
        if n == "signum":
            return (x > 0) - (x < 0)
        if n == "max":
            return max(x, a[0])
        if n == "min":
            return min(x, a[0])
    return UNK


def list_method(it, lst, n, a, fr):
    """Выполняет метод ``java.util.List``."""
    if n == "add":
        if len(a) == 2:
            if isinstance(a[0], int) and 0 <= a[0] <= len(lst):
                lst.insert(a[0], a[1])
            return None
        lst.append(a[0])
        return True
    if n == "get":
        if isinstance(a[0], int) and 0 <= a[0] < len(lst):
            return lst[a[0]]
        if isinstance(a[0], int):
            raise JavaThrow(
                it.make_exc(
                    "IndexOutOfBoundsException", f"Index {a[0]} out of bounds"
                )
            )
        return UNK
    if n == "size":
        return len(lst)
    if n == "isEmpty":
        return len(lst) == 0
    if n == "contains":
        for x in lst:
            e = obj_equals(it, a[0], x) if a[0] is not None else (x is None)
            if e is UNK:
                return UNK
            if e:
                return True
        return False
    if n == "indexOf":
        for i, x in enumerate(lst):
            e = obj_equals(it, a[0], x) if a[0] is not None else (x is None)
            if e is True:
                return i
        return -1
    if n == "remove":
        if (
            len(a) == 1
            and isinstance(a[0], int)
            and not isinstance(a[0], bool)
        ):
            if 0 <= a[0] < len(lst):
                return lst.pop(a[0])
            return UNK
        for i, x in enumerate(lst):
            if obj_equals(it, a[0], x) is True:
                lst.pop(i)
                return True
        return False
    if n == "addAll":
        src = a[-1]
        if isinstance(src, list):
            if len(a) == 2:
                lst[a[0] : a[0]] = list(src)
            else:
                lst.extend(src)
        elif isinstance(src, JSet):
            lst.extend(src.values())
        elif isinstance(src, dict):
            lst.extend(src.keys())
        return True
    if n == "set":
        if 0 <= a[0] < len(lst):
            old = lst[a[0]]
            lst[a[0]] = a[1]
            return old
        return UNK
    if n == "clear":
        lst.clear()
        return None
    if n in ("iterator", "listIterator"):
        return LibObj("Iterator", items=list(lst), pos=0)
    if n in ("stream", "parallelStream"):
        return JStream(lst)
    if n == "forEach":
        for x in list(lst):
            it.ev_new_lambda_call(a[0], [x])
        return None
    if n == "toArray":
        return JList(lst)
    if n == "subList":
        return JList(lst[a[0] : a[1]])
    if n == "sort":
        _sort_list(it, lst, a[0] if a else None)
        return None
    if n == "equals":
        return obj_equals(it, lst, a[0])
    if n == "toString":
        return to_str(it, lst)
    if n == "removeAll":
        src = a[0] if isinstance(a[0], list) else list(a[0])
        keep = [
            x
            for x in lst
            if not any(obj_equals(it, x, y) is True for y in src)
        ]
        ch = len(keep) != len(lst)
        lst[:] = keep
        return ch
    if n == "retainAll":
        src = a[0] if isinstance(a[0], list) else list(a[0])
        keep = [
            x for x in lst if any(obj_equals(it, x, y) is True for y in src)
        ]
        ch = len(keep) != len(lst)
        lst[:] = keep
        return ch
    if n == "containsAll":
        return all(
            any(obj_equals(it, x, y) is True for y in lst) for x in a[0]
        )
    if n == "lastIndexOf":
        r = -1
        for i, x in enumerate(lst):
            if obj_equals(it, a[0], x) is True:
                r = i
        return r
    if n == "hashCode":
        return len(lst)
    if n == "getFirst":
        return lst[0] if lst else UNK
    if n == "removeIf":
        keep = [x for x in lst if not it.ev_new_lambda_call(a[0], [x])]
        ch = len(keep) != len(lst)
        lst[:] = keep
        return ch
    if n == "replaceAll":
        lst[:] = [it.ev_new_lambda_call(a[0], [x]) for x in lst]
        return None
    return UNK


def set_method(it, s, n, a, fr):
    """Выполняет метод ``java.util.Set``."""
    if n == "add":
        k = hk(a[0])
        if k in s:
            return False
        s[k] = a[0]
        return True
    if n == "contains":
        return hk(a[0]) in s
    if n == "remove":
        return s.pop(hk(a[0]), NOTFOUND) is not NOTFOUND
    if n == "size":
        return len(s)
    if n == "isEmpty":
        return len(s) == 0
    if n == "addAll":
        ch = False
        for x in (a[0] if isinstance(a[0], list) else a[0].values()):
            k = hk(x)
            if k not in s:
                s[k] = x
                ch = True
        return ch
    if n == "removeAll":
        ch = False
        for x in (a[0] if isinstance(a[0], list) else a[0].values()):
            if s.pop(hk(x), NOTFOUND) is not NOTFOUND:
                ch = True
        return ch
    if n == "retainAll":
        keep = {
            hk(x) for x in (a[0] if isinstance(a[0], list) else a[0].values())
        }
        for k in [k for k in s if k not in keep]:
            del s[k]
        return True
    if n == "clear":
        s.clear()
        return None
    if n == "iterator":
        return LibObj("Iterator", items=list(s.values()), pos=0)
    if n in ("stream", "parallelStream"):
        return JStream(s.values())
    if n == "forEach":
        for x in list(s.values()):
            it.ev_new_lambda_call(a[0], [x])
        return None
    if n == "containsAll":
        return all(
            hk(x) in s
            for x in (a[0] if isinstance(a[0], list) else a[0].values())
        )
    if n == "toString":
        return to_str(it, s)
    if n == "equals":
        return isinstance(a[0], JSet) and set(s) == set(a[0])
    return UNK


def map_method(it, m, n, a, fr):
    """Выполняет метод ``java.util.Map``."""
    if n == "put":
        k = hk(a[0])
        old = m.get(k)
        m[k] = a[1]
        return old
    if n == "get":
        return m.get(hk(a[0]))
    if n == "getOrDefault":
        return m.get(hk(a[0]), a[1])
    if n == "containsKey":
        return hk(a[0]) in m
    if n == "containsValue":
        return any(obj_equals(it, a[0], v) is True for v in m.values())
    if n == "remove":
        return m.pop(hk(a[0]), None)
    if n == "keySet":
        s = JSet()
        for k in m:
            s[k] = k
        return s
    if n == "values":
        return JList(m.values())
    if n == "entrySet":
        s = JSet()
        for k, v in m.items():
            e = LibObj("Entry", k=k, v=v)
            s[id(e)] = e
        return s
    if n == "size":
        return len(m)
    if n == "isEmpty":
        return len(m) == 0
    if n == "putAll":
        if isinstance(a[0], dict):
            m.update(a[0])
        return None
    if n == "putIfAbsent":
        k = hk(a[0])
        if k not in m or m[k] is None:
            m[k] = a[1]
            return None
        return m[k]
    if n == "clear":
        m.clear()
        return None
    if n == "forEach":
        for k, v in list(m.items()):
            it.ev_new_lambda_call(a[0], [k, v])
        return None
    if n == "computeIfAbsent":
        k = hk(a[0])
        if k not in m or m[k] is None:
            m[k] = it.ev_new_lambda_call(a[1], [a[0]])
        return m[k]
    if n == "toString":
        return to_str(it, m)
    if n == "equals":
        return m is a[0] or m == a[0]
    if n == "hashCode":
        return len(m)
    return UNK


def opt_method(it, o, n, a):
    """Выполняет метод ``java.util.Optional``."""
    if n == "isPresent":
        return o.v is not None
    if n == "isEmpty":
        return o.v is None
    if n == "get" or n == "orElseThrow":
        if o.v is None:
            if n == "orElseThrow" and a:
                exc = it.ev_new_lambda_call(a[0], [])
                raise JavaThrow(exc)
            raise JavaThrow(
                it.make_exc("NoSuchElementException", "No value present")
            )
        return o.v
    if n == "orElse":
        return o.v if o.v is not None else a[0]
    if n == "orElseGet":
        return o.v if o.v is not None else it.ev_new_lambda_call(a[0], [])
    if n == "ifPresent":
        if o.v is not None:
            it.ev_new_lambda_call(a[0], [o.v])
        return None
    if n == "map":
        return (
            JOpt(it.ev_new_lambda_call(a[0], [o.v])) if o.v is not None else o
        )
    if n == "filter":
        return (
            o
            if o.v is not None and it.ev_new_lambda_call(a[0], [o.v])
            else JOpt(None)
        )
    if n == "toString":
        return to_str(it, o)
    return UNK


FMT_MAP = [
    ("yyyy", "%Y"),
    ("MM", "%m"),
    ("dd", "%d"),
    ("HH", "%H"),
    ("mm", "%M"),
    ("ss", "%S"),
    ("SSS", "%f"),
]


def java_fmt_to_py(p):
    """Переводит шаблон ``SimpleDateFormat`` в шаблон ``strftime``."""
    out = p
    for j, py in FMT_MAP:
        out = out.replace(j, py)
    return out


def date_method(it, d, n, a):
    """Выполняет метод ``java.util.Date``."""
    if n == "getTime":
        return int(
            (d.dt - datetime.datetime(1970, 1, 1)).total_seconds() * 1000
        )
    if n == "before":
        return d.dt < a[0].dt if isinstance(a[0], JDate) else UNK
    if n == "after":
        return d.dt > a[0].dt if isinstance(a[0], JDate) else UNK
    if n == "compareTo":
        return (d.dt > a[0].dt) - (d.dt < a[0].dt)
    if n == "toString":
        return to_str(it, d)
    if n == "equals":
        return isinstance(a[0], JDate) and a[0].dt == d.dt
    if n == "setTime":
        d.dt = datetime.datetime(1970, 1, 1) + datetime.timedelta(
            milliseconds=a[0]
        )
        return None
    if n == "hashCode":
        return int(d.dt.timestamp()) & 0x7FFFFFFF
    return UNK


def cal_method(it, c, n, a):
    """Выполняет метод ``java.util.Calendar``."""
    if n == "setTime":
        c.dt = a[0].dt if isinstance(a[0], JDate) else c.dt
        return None
    if n == "getTime":
        return JDate(c.dt)
    if n == "get":
        f = a[0]
        d = c.dt
        return {
            1: d.year,
            2: d.month - 1,
            5: d.day,
            6: d.timetuple().tm_yday,
            7: (d.isoweekday() % 7) + 1,
            10: d.hour % 12,
            11: d.hour,
            12: d.minute,
            13: d.second,
            14: d.microsecond // 1000,
        }.get(f, UNK)
    if any(x is UNK for x in a):
        return UNK
    if n == "add":
        f, v = a[0], a[1]
        d = c.dt
        if f == 5:
            c.dt = d + datetime.timedelta(days=v)
        elif f in (11, 10):
            c.dt = d + datetime.timedelta(hours=v)
        elif f == 12:
            c.dt = d + datetime.timedelta(minutes=v)
        elif f == 13:
            c.dt = d + datetime.timedelta(seconds=v)
        elif f == 2:
            m = d.month - 1 + v
            c.dt = d.replace(year=d.year + m // 12, month=m % 12 + 1)
        elif f == 1:
            c.dt = d.replace(year=d.year + v)
        return None
    if n == "set":
        f, v = a[0], a[1]
        d = c.dt
        try:
            if f == 1:
                c.dt = d.replace(year=v)
            elif f == 2:
                c.dt = d.replace(month=v + 1)
            elif f == 5:
                c.dt = d.replace(day=v)
            elif f == 11:
                c.dt = d.replace(hour=v)
            elif f == 12:
                c.dt = d.replace(minute=v)
            elif f == 13:
                c.dt = d.replace(second=v)
        except ValueError:
            pass
        return None
    if n == "getTimeInMillis":
        return int(
            (c.dt - datetime.datetime(1970, 1, 1)).total_seconds() * 1000
        )
    return UNK


def libobj_method(it, o, n, a, fr, node):
    """Выполняет метод библиотечного объекта (Logger, HttpHeaders и т. п.)."""
    k = o.kind
    if k == "Logger":
        if n in ("info", "warn", "error", "debug", "trace"):
            if n in ("info", "warn", "error"):
                for x in a:
                    # SLF4J форматирует аргументы -> неявный toString
                    # (проектные toString выполняются)
                    (
                        to_str(it, x)
                        if isinstance(x, (JObj, list, dict))
                        else None
                    )
        return None
    if k == "ResponseEntity":
        if n == "getBody":
            return o.f["body"]
        if n == "getStatusCode":
            return o.f["status"]
        if n == "getHeaders":
            return LibObj("HttpHeaders", map=JMap())
        if n == "getStatusCodeValue":
            return (
                o.f["status"].f.get("code")
                if isinstance(o.f["status"], LibObj)
                else UNK
            )
        return UNK
    if k == "REBuilder":
        if n == "body":
            return LibObj("ResponseEntity", body=a[0], status=o.f["status"])
        if n == "build":
            return LibObj("ResponseEntity", body=None, status=o.f["status"])
        if n in ("header", "contentType"):
            return o
        return UNK
    if k == "HttpStatus":
        if n == "value":
            return o.f["code"]
        if n == "name" or n == "toString":
            return o.f["name"]
        if n == "is2xxSuccessful":
            return 200 <= o.f["code"] < 300
        return UNK
    if k == "HttpEntity":
        if n == "getBody":
            return o.f["body"]
        if n == "getHeaders":
            return o.f["headers"]
        return UNK
    if k == "HttpHeaders":
        m = o.f["map"]
        if n in ("set", "add"):
            m[a[0]] = a[1]
            return None
        if n == "getFirst":
            v = m.get(a[0])
            return v[0] if isinstance(v, list) and v else v
        if n == "get":
            v = m.get(a[0])
            return JList([v]) if isinstance(v, str) else v
        if n == "containsKey":
            return a[0] in m
        if n == "setContentType":
            return None
        return UNK
    if k == "RestTemplate":
        return it.web.rest_call(n, a, fr, node)
    if k == "SB":
        if n == "append":
            o.f["parts"].append(to_str(it, a[0]))
            return o
        if n == "toString":
            return "".join(o.f["parts"])
        if n == "length":
            return len("".join(o.f["parts"]))
        if n == "insert":
            s = "".join(o.f["parts"])
            o.f["parts"] = [s[: a[0]] + to_str(it, a[1]) + s[a[0] :]]
            return o
        if n == "reverse":
            o.f["parts"] = ["".join(o.f["parts"])[::-1]]
            return o
        return UNK
    if k == "Iterator":
        if n == "hasNext":
            return o.f["pos"] < len(o.f["items"])
        if n == "next":
            i = o.f["pos"]
            o.f["pos"] += 1
            return o.f["items"][i] if i < len(o.f["items"]) else UNK
        if n == "remove":
            return None
        return UNK
    if k == "Entry":
        if n == "getKey":
            return o.f["k"]
        if n == "getValue":
            return o.f["v"]
        return UNK
    if k == "SDF":
        pat = java_fmt_to_py(o.f["pattern"])
        if n == "format":
            d = a[0]
            return (
                d.dt.strftime(pat).replace("%f", "000")
                if isinstance(d, JDate)
                else UNK_CH
            )
        if n == "parse":
            s = a[0]
            if isinstance(s, str) and not has_unk(s):
                try:
                    return JDate(datetime.datetime.strptime(s, pat))
                except ValueError:
                    raise JavaThrow(
                        it.make_exc(
                            "ParseException", f'Unparseable date: "{s}"'
                        )
                    )
            return UNK
        return UNK
    if k == "Random":
        if n == "nextInt":
            return (
                it.rng.randrange(a[0])
                if a and isinstance(a[0], int) and a[0] > 0
                else it.rng.getrandbits(31)
            )
        if n == "nextDouble":
            return it.rng.random()
        return 0
    if k == "ObjectMapper":
        if n == "writeValueAsString":
            s = JsonStr("{json}")
            s.obj = a[0]
            return s
        if n == "readValue":
            src = a[0]
            tgt = a[1] if len(a) > 1 else None
            val = src.obj if isinstance(src, JsonStr) else UNK
            if isinstance(tgt, JClass):
                return it.web.convert(
                    val,
                    (
                        tgt.name
                        if tgt.name.endswith("[]")
                        else (tgt.ci.name if tgt.ci else tgt.name)
                    ),
                    fr.cls if fr else None,
                    tgt.ci,
                    traced=False,
                )
            if isinstance(tgt, LibObj) and tgt.kind == "PTR":
                return it.web.convert(
                    val,
                    tgt.f["type"],
                    tgt.f.get("ctx"),
                    None,
                    traced=False,
                )
            return val
        if n == "convertValue":
            tgt = a[1] if len(a) > 1 else None
            if isinstance(tgt, JClass):
                return it.web.convert(
                    it.web.to_raw(a[0]),
                    (
                        tgt.name
                        if tgt.name.endswith("[]")
                        else (tgt.ci.name if tgt.ci else tgt.name)
                    ),
                    fr.cls if fr else None,
                    tgt.ci,
                    traced=False,
                )
            if isinstance(tgt, LibObj) and tgt.kind == "PTR":
                return it.web.convert(
                    it.web.to_raw(a[0]),
                    tgt.f["type"],
                    tgt.f.get("ctx"),
                    None,
                    traced=False,
                )
            return a[0]
        return UNK
    if k == "AuthToken":
        if n == "getPrincipal":
            return o.f["principal"]
        if n == "getCredentials":
            return o.f["credentials"]
        if n == "getName":
            return o.f["principal"]
        return UNK
    if k == "AuthenticationManager" or k == "AuthManager":
        return it.web.authenticate(o, n, a, fr)
    if k == "Builder":
        # Lombok-билдер
        if n == "build":
            ci = o.f["ci"]
            obj = JObj(ci, it.default_fields(ci))
            obj.f.update(o.f["f"])
            return obj
        o.f["f"][n] = a[0] if a else None
        return o
    if k == "Atomic":
        v = o.f["v"]
        if n in ("get", "intValue", "longValue"):
            return v
        if n == "incrementAndGet":
            o.f["v"] = v + 1
            return o.f["v"]
        if n == "getAndIncrement":
            o.f["v"] = v + 1
            return v
        if n == "set":
            o.f["v"] = a[0]
            return None
        return UNK
    if k == "DecimalFormat":
        if n == "format":
            v = a[0]
            if not is_num(v):
                return UNK
            pat = o.f["pattern"]
            frac = (
                len(pat.split(".")[1].replace("#", "0")) if "." in pat else 0
            )
            mn = (
                len(pat.split(".")[1]) - pat.split(".")[1].count("#")
                if "." in pat
                else 0
            )
            q = Decimal(1).scaleb(-frac)
            r = Decimal(v).quantize(q, rounding=decimal.ROUND_HALF_EVEN)
            s = format(r, "f")
            if "." in s and mn < frac:
                s = s.rstrip("0")
                if s.endswith("."):
                    s = s[:-1]
            return s
        return UNK
    if k == "SecBuilder":
        if n == "antMatchers":
            meth = (
                a[0]
                if a
                and isinstance(a[0], str)
                and a[0] in ("GET", "POST", "PUT", "DELETE", "PATCH")
                else None
            )
            pats = [x for x in (a[1:] if meth else a) if isinstance(x, str)]
            for x in a:
                if isinstance(x, list):
                    pats += [y for y in x if isinstance(y, str)]
            return LibObj(
                "SecMatcher",
                rules=o.f["rules"],
                meth=meth,
                pats=pats,
                parent=o,
            )
        if n == "anyRequest":
            return LibObj(
                "SecMatcher",
                rules=o.f["rules"],
                meth=None,
                pats=["/**"],
                parent=o,
            )
        return o
    if k == "SecMatcher":
        if n in (
            "permitAll",
            "authenticated",
            "denyAll",
            "hasAnyRole",
            "hasRole",
            "hasAuthority",
            "hasAnyAuthority",
            "access",
        ):
            roles = []
            for x in a:
                roles += x if isinstance(x, list) else [x]
            o.f["rules"].append(
                (o.f["meth"], o.f["pats"], n, [to_str(it, r) for r in roles])
            )
        return o.f["parent"]
    if k == "Claims":
        if n == "setSubject":
            o.f["sub"] = a[0]
            return o
        if n in ("setId", "setIssuer"):
            return o
        if n == "put":
            o.f["map"][hk(a[0])] = a[1]
            return None
        if n == "get":
            return o.f["map"].get(hk(a[0]))
        return UNK
    if k == "JwtBuilder":
        if n == "setClaims":
            o.f["claims"] = a[0]
            return o
        if n == "compact":
            cl = o.f.get("claims")
            sub, roles = "", []
            if isinstance(cl, LibObj) and cl.kind == "Claims":
                sub = to_str(it, cl.f.get("sub", ""))
                rr = cl.f["map"].get("roles")
                if rr is not None and rr is not UNK:
                    roles = [
                        to_str(it, x)
                        for x in (rr.values() if isinstance(rr, JSet) else rr)
                    ]
            return "jwt." + sub + "." + ",".join(sorted(roles))
        return o
    if k == "DiscoveryClient":
        if n == "getInstances":
            return JList([LibObj("ServiceInstance", host=to_str(it, a[0]))])
        if n == "getServices":
            return JList()
        return UNK
    if k == "ServiceInstance":
        if n == "getHost":
            return o.f["host"]
        if n == "getPort":
            return 8080
        return UNK
    if k == "Collector":
        return UNK
    if k == "SecurityContext":
        return UNK
    if k == "PrintStream":
        return None
    if k == "Executor":
        return UNK
    if k == "Object":
        if n == "hashCode":
            return id(o) & 0x7FFFFFFF
        if n == "equals":
            return o is a[0]
        if n == "toString":
            return "java.lang.Object@1"
        return UNK
    if k == "Thread":
        if n == "start" and o.f.get("target") is not None:
            it.ev_new_lambda_call(o.f["target"], [])
        return None
    return it.web.lib_method(o, n, a, fr, node)


def stream_method(it, s, n, a):
    """Выполняет метод потока ``Stream`` с лямбдами проекта."""

    def call(f, *args):
        return it.ev_new_lambda_call(f, list(args))

    if n == "filter":
        return JStream(x for x in s if call(a[0], x) is True)
    if n in ("map", "mapToInt", "mapToDouble", "mapToLong", "mapToObj"):
        return JStream(call(a[0], x) for x in s)
    if n in ("boxed", "sequential", "parallel", "peek"):
        return s
    if n == "forEach":
        for x in s:
            call(a[0], x)
        return None
    if n == "collect":
        c = a[0]
        if isinstance(c, LibObj) and c.kind == "Collector":
            kind = c.f["ckind"]
            if kind == "toList":
                return JList(s)
            if kind == "toSet":
                r = JSet()
                for x in s:
                    r[hk(x)] = x
                return r
            if kind == "toMap":
                r = JMap()
                for x in s:
                    r[hk(call(c.f["args"][0], x))] = call(c.f["args"][1], x)
                return r
            if kind == "joining":
                sep = c.f["args"][0] if c.f["args"] else ""
                return sep.join(to_str(it, x) for x in s)
            if kind == "counting":
                return len(s)
        return JList(s)
    if n == "toList":
        return JList(s)
    if n == "count":
        return len(s)
    if n == "sum":
        return sum(s) if all(is_num(x) for x in s) else UNK
    if n == "sorted":
        r = JList(s)
        _sort_list(it, r, a[0] if a else None)
        return JStream(r)
    if n == "limit":
        return JStream(list(s)[: a[0]])
    if n == "skip":
        return JStream(list(s)[a[0] :])
    if n == "distinct":
        seen, r = set(), []
        for x in s:
            k = hk(x)
            if k not in seen:
                seen.add(k)
                r.append(x)
        return JStream(r)
    if n in ("findFirst", "findAny"):
        return JOpt(s[0] if s else None)
    if n == "anyMatch":
        return any(call(a[0], x) is True for x in s)
    if n == "allMatch":
        return all(call(a[0], x) is True for x in s)
    if n == "noneMatch":
        return not any(call(a[0], x) is True for x in s)
    if n in ("max", "min"):
        if not s:
            return JOpt(None)
        cmp = a[0] if a else None
        f = (
            (lambda x, y: call(cmp, x, y))
            if cmp
            else (lambda x, y: (x > y) - (x < y))
        )
        best = s[0]
        for x in s[1:]:
            r = f(x, best)
            if (n == "max" and r > 0) or (n == "min" and r < 0):
                best = x
        return JOpt(best)
    if n == "toArray":
        return JList(s)
    if n == "average":
        return JOpt(sum(s) / len(s) if s else None)
    if n == "reduce":
        if len(a) == 2:
            acc = a[0]
            for x in s:
                acc = call(a[1], acc, x)
            return acc
        return UNK
    return UNK
