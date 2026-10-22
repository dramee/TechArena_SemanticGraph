"""Веб-слой сервисов Train Ticket.

Модуль направляет HTTP-запросы в обработчики ``@RestController``,
выполняет вызовы ``RestTemplate`` между сервисами, переводит объекты в JSON
и обратно (как Jackson), эмулирует Spring Security и доставку сообщений
RabbitMQ.
"""

import collections
import re

from . import lib
from .lib import UNK_CH, has_unk, to_str
from .model import PRIM_DEFAULT, strip_generics, type_args
from .values import (
    UNK,
    JavaThrow,
    JClass,
    JDate,
    JEnum,
    JList,
    JMap,
    JObj,
    JOpt,
    JSet,
    LibObj,
)

MAPPINGS = {
    "GetMapping": "GET",
    "PostMapping": "POST",
    "PutMapping": "PUT",
    "DeleteMapping": "DELETE",
    "PatchMapping": "PATCH",
    "RequestMapping": None,
}
BOXED = {
    "Integer",
    "Long",
    "Short",
    "Byte",
    "Double",
    "Float",
    "Boolean",
    "String",
    "int",
    "long",
    "short",
    "byte",
    "double",
    "float",
    "boolean",
    "char",
    "Character",
    "BigDecimal",
    "Number",
    "UUID",
}


def map_paths(args):
    """Пути из аргументов аннотации *Mapping."""
    if not args:
        return [""]
    vals = re.findall(r'"([^"]*)"', re.sub(r"method\s*=\s*[^,)]*", "", args))
    vals = [
        v
        for v in vals
        if v == ""
        or v.startswith("/")
        or "{" in v
        or v.isidentifier()
        or "/" in v
    ]
    return vals or [""]


def segs(p):
    """Возвращает непустые сегменты пути без строки запроса."""
    return [s for s in p.split("?")[0].split("/") if s]


def match_path(tpl, req):
    """Сопоставляет шаблон пути Spring с сегментами запроса.

    Возвращает словарь переменных пути или ``None``.
    """
    out = {}
    i = 0
    for i, t in enumerate(tpl):
        if t == "**":
            return out
        if i >= len(req):
            return None
        s = req[i]
        if t.startswith("{") and t.endswith("}"):
            inner = t[1:-1]
            name, _, rx = inner.partition(":")
            if rx and not re.fullmatch(rx, s):
                return None
            out[name] = s
        elif t == "*":
            pass
        elif t != s:
            return None
    if len(req) != len(tpl):
        return None
    return out


class BindError(Exception):
    """Ошибка привязки запроса к параметрам обработчика (ответ 400)."""


class Web:
    """Веб-слой: обработчики, вызовы между сервисами, JSON и безопасность."""

    def __init__(self, it):
        """Находит обработчики REST и правила безопасности всех сервисов."""
        self.it = it
        it.web = self
        self.handlers = collections.defaultdict(
            list
        )  # module -> [(verb, tpl, mi, ci)]
        self.jwt_id = None
        self.in_serialization = False
        self.enforce_auth = True
        self._tracing = False
        self.sec = {}
        self._build()
        self._load_security()

    def _build(self):
        p = self.it.p
        for (module, fqn), ci in p.classes.items():
            if "RestController" in ci.annots or "Controller" in ci.annots:
                cps = (
                    map_paths(ci.annots.get("RequestMapping"))
                    if "RequestMapping" in ci.annots
                    else [""]
                )
                for ms in ci.methods.values():
                    for mi in ms:
                        for an, verb in MAPPINGS.items():
                            if an in mi.annots:
                                v = verb
                                if v is None:
                                    mv = re.search(
                                        r"RequestMethod\.(\w+)",
                                        mi.annots[an] or "",
                                    )
                                    v = mv.group(1) if mv else None
                                for cp in cps:
                                    for mp in map_paths(mi.annots[an]):
                                        self.handlers[module].append(
                                            (v, segs(cp + "/" + mp), mi, ci)
                                        )
        for (module, fqn), ci in p.classes.items():
            if ci.name == "JWTFilter" and module == "ts-common":
                for m in ci.methods.get("doFilterInternal", []):
                    self.jwt_id = m.id

    # ------------------------------------------------------------------------------
    # Spring Security
    def _load_security(self):
        """Собирает правила авторизации сервисов.

        Метод ``configure(HttpSecurity)`` исполняется на «записывающем»
        построителе, который запоминает пути и требуемые роли.
        """
        from .interp import Trace

        it = self.it
        p = it.p
        saved = it.trace
        it.trace = Trace()
        try:
            for (module, fqn), ci in p.classes.items():
                for mi in ci.methods.get("configure", []):
                    if (
                        len(mi.params) == 1
                        and "HttpSecurity" in mi.params[0][0]
                        and mi.decl.body is not None
                    ):
                        try:
                            bean = it.bean(module, ci)
                            rec = LibObj("SecBuilder", rules=[])
                            it.invoke(mi, bean, [rec], None)
                            self.sec[module] = rec.f["rules"]
                        except Exception:
                            it.warn("security config failed " + module)
        finally:
            it.trace = saved
            it.stack = []

    @staticmethod
    def ant_match(pat, path):
        """Проверяет путь по шаблону Ant.

        ``**`` — любые сегменты, ``*`` — часть сегмента, ``?`` — один символ.
        """
        out, i = [], 0
        while i < len(pat):
            c = pat[i]
            if pat.startswith("**", i):
                out.append(".*")
                i += 2
            elif c == "*":
                out.append("[^/]*")
                i += 1
            elif c == "?":
                out.append("[^/]")
                i += 1
            else:
                out.append(re.escape(c))
                i += 1
        return re.fullmatch("".join(out), path) is not None or (
            pat.endswith("/**") and path == pat[:-3]
        )

    @staticmethod
    def token_roles(headers):
        """Возвращает роли из заголовка ``Authorization`` или ``None``."""
        if not isinstance(headers, LibObj):
            return None
        auth = headers.f["map"].get("Authorization")
        if isinstance(auth, list):
            auth = auth[0] if auth else None
        if not isinstance(auth, str) or not auth.startswith("Bearer "):
            return None
        tok = auth[7:]
        if not tok.startswith("jwt."):
            return set()
        parts = tok.split(".", 2)
        return set(
            x for x in (parts[2].split(",") if len(parts) > 2 else []) if x
        )

    def check_auth(self, module, verb, path, headers):
        """Проверяет, пропускают ли правила сервиса запрос с этим токеном."""
        rules = self.sec.get(module)
        if not rules:
            return True
        roles = self.token_roles(headers)
        for meth, pats, kind, req in rules:
            if meth and meth != verb:
                continue
            if not any(self.ant_match(p, path) for p in pats):
                continue
            if kind == "permitAll":
                return True
            if kind == "authenticated":
                return roles is not None
            if kind in (
                "hasAnyRole",
                "hasRole",
                "hasAuthority",
                "hasAnyAuthority",
            ):
                need = {
                    r if r.startswith("ROLE_") else "ROLE_" + r for r in req
                }
                return roles is not None and bool(roles & need)
            if kind == "denyAll":
                return False
            return True
        return True

    # ------------------------------------------------------------------------------
    # маршрутизация
    def find_handler(self, module, verb, path):
        """Находит обработчик в модуле: ``(метод, класс, переменные пути)``."""
        req = segs(path)
        best = None
        for v, tpl, mi, ci in self.handlers.get(module, ()):
            if v is not None and v != verb:
                continue
            pv = match_path(tpl, req)
            if pv is not None:
                score = sum(1 for t in tpl if not t.startswith("{"))
                if best is None or score > best[0]:
                    best = (score, mi, ci, pv)
        return best[1:] if best else None

    def module_of_host(self, host):
        """Возвращает модуль сервиса по имени хоста из URL."""
        h = host.split(":")[0]
        if h in self.it.p.modules:
            return h
        return None

    def parse_url(self, url):
        """Разбирает URL на хост, путь и строку запроса."""
        m = re.match(r"^(?:https?://)?([^/]+)(/[^?]*)?(?:\?(.*))?$", url)
        if not m:
            return None
        return m.group(1), (m.group(2) or "/"), m.group(3) or ""

    # ------------------------------------------------------------------------------
    # обработка запроса сервисом
    def serve(
        self,
        module,
        mi,
        ci,
        pvars,
        query,
        body,
        caller,
        headers=None,
        path=None,
        verb=None,
    ):
        """Выполняет обработчик запроса и возвращает ``ResponseEntity``.

        Запрос проходит фильтр JWT и проверку прав, тело и переменные пути
        привязываются к параметрам, исключения превращаются в ответы с кодом
        ошибки.
        """
        it = self.it
        if self.jwt_id:
            it.trace.executes.add(self.jwt_id)
        if path is not None and not self.check_auth(
            module, verb, path, headers
        ):
            it.auth_log.append(
                (module, verb, path, caller.name if caller else "ENTRY")
            )
            if self.enforce_auth:
                return LibObj(
                    "ResponseEntity",
                    body=None,
                    status=LibObj("HttpStatus", name="FORBIDDEN", code=403),
                    exc=None,
                )
        if caller is not None and caller.id and mi.id:
            it.trace.remote.add((caller.id, mi.id))
        from .interp import Trace

        saved = it.trace
        it.trace = Trace()  # разбор аргументов (Jackson) не учитывается
        try:
            args = self.bind(mi, ci, pvars, query, body, headers)
        except BindError:
            it.trace = saved
            return LibObj(
                "ResponseEntity",
                body=None,
                status=LibObj("HttpStatus", name="BAD_REQUEST", code=400),
                exc=None,
            )
        finally:
            it.trace = saved
        bean = it.bean(module, ci)
        saved_stack = it.stack
        saved_session = it.session
        it.stack = []  # новый вызов в другом «процессе»: стек сервиса пуст
        it.session = {}  # у каждого HTTP-запроса своя сессия Hibernate (OSIV)
        try:
            try:
                r = it.invoke(mi, bean, args, None)
            except JavaThrow as jt:
                return LibObj(
                    "ResponseEntity",
                    body=None,
                    status=LibObj(
                        "HttpStatus", name="INTERNAL_SERVER_ERROR", code=500
                    ),
                    exc=jt.value,
                )
            self.in_serialization = True
            try:
                if isinstance(r, LibObj) and r.kind == "ResponseEntity":
                    out = LibObj(
                        "ResponseEntity",
                        body=self.to_raw(r.f["body"], traced=False),
                        status=r.f["status"],
                    )
                else:
                    out = LibObj(
                        "ResponseEntity",
                        body=self.to_raw(r, traced=False),
                        status=LibObj("HttpStatus", name="OK", code=200),
                    )
            finally:
                self.in_serialization = False
            return out
        finally:
            it.stack = saved_stack
            it.session = saved_session

    def bind(self, mi, ci, pvars, query, body, headers):
        """Привязывает переменные пути, параметры и тело запроса к методу."""
        args = []
        for pt, pn, an in mi.params:
            t = strip_generics(pt).split(".")[-1]
            if "PathVariable" in an:
                nm = lib_ann_name(an["PathVariable"]) or pn
                if nm not in pvars:
                    raise BindError(
                        nm
                    )  # MissingPathVariableException: обработчик не вызывается
                args.append(self.coerce_path(pvars.get(nm), pt))
            elif "RequestParam" in an:
                nm = lib_ann_name(an["RequestParam"]) or pn
                v = query.get(nm)
                if v is None:
                    mm = re.search(
                        r"defaultValue\s*=\s*\"([^\"]*)\"",
                        an["RequestParam"] or "",
                    )
                    v = mm.group(1) if mm else None
                args.append(self.coerce_path(v, pt))
            elif "RequestBody" in an:
                args.append(self.convert(body, pt, ci, None))
            elif "RequestHeader" in an or t in ("HttpHeaders",):
                args.append(
                    headers
                    if headers is not None
                    else LibObj("HttpHeaders", map=JMap())
                )
            elif t in (
                "HttpServletRequest",
                "HttpServletResponse",
                "ServletRequest",
                "ServletResponse",
            ):
                args.append(LibObj(t))
            else:
                args.append(
                    self.convert(body, pt, ci, None)
                    if body is not None
                    and not isinstance(body, str)
                    and t not in BOXED
                    else None
                )
        return args

    def coerce_path(self, v, pt):
        """Приводит переменную пути или параметр запроса к типу ``pt``."""
        t = strip_generics(pt).split(".")[-1]
        if v is None or v is UNK:
            return v if v is not None else PRIM_DEFAULT.get(t)
        if isinstance(v, str) and has_unk(v):
            return UNK
        try:
            if t in ("int", "Integer", "long", "Long", "short", "Short"):
                return int(v)
            if t in ("double", "Double", "float", "Float"):
                return float(v)
            if t in ("boolean", "Boolean"):
                return str(v).lower() == "true"
            if t == "UUID":
                return lib.UUIDStr(v)
        except ValueError:
            return UNK
        return v

    # ------------------------------------------------------------------------------
    # RestTemplate
    def rest_call(self, name, a, fr, node=None):
        """Выполняет вызов ``RestTemplate`` к другому сервису.

        Добавляет ребро ``remote`` от вызывающего метода к обработчику и
        переводит ответ в объявленный тип.
        """
        it = self.it
        meth, ent, rtype, url = "GET", None, None, None
        extra = []
        if name == "exchange":
            url, meth, ent, rtype = a[0], a[1], a[2], a[3]
            extra = a[4:]
        elif name in ("getForObject", "getForEntity"):
            url, rtype = a[0], a[1]
            extra = a[2:]
        elif name in (
            "postForObject",
            "postForEntity",
            "postForLocation",
            "patchForObject",
        ):
            url, ent = a[0], a[1]
            rtype = a[2] if len(a) > 2 else None
            meth = "POST" if name.startswith("post") else "PATCH"
            extra = a[3:]
        elif name == "put":
            url, ent, meth = a[0], a[1], "PUT"
            extra = a[2:]
        elif name == "delete":
            url, meth = a[0], "DELETE"
            extra = a[1:]
        else:
            return UNK
        if isinstance(meth, LibObj):
            meth = meth.f.get("name", "GET")
        if (
            isinstance(extra, list)
            and len(extra) == 1
            and isinstance(extra[0], list)
        ):
            extra = list(extra[0])
        if isinstance(url, str):
            for x in extra:
                url = re.sub(
                    r"\{[^}]*\}", lambda m, x=x: to_str(it, x), url, count=1
                )
        if not isinstance(url, str):
            return UNK
        body = None
        if isinstance(ent, LibObj) and ent.kind == "HttpEntity":
            body = ent.f.get("body")
        elif ent is not None and ent is not UNK:
            body = ent
        raw_body = (
            self.to_raw(body, traced=False) if body is not None else None
        )
        hdrs = (
            ent.f.get("headers")
            if isinstance(ent, LibObj) and ent.kind == "HttpEntity"
            else None
        )
        resp = self.dispatch(meth, url, raw_body, fr, node, hdrs)
        if resp is None:
            exc = it.make_exc(
                "ResourceAccessException",
                f'I/O error on {meth} request for "{url}": Connection refused',
            )
            raise JavaThrow(exc)
        if isinstance(resp, LibObj) and resp.f.get("exc") is not None:
            raise JavaThrow(
                it.make_exc(
                    "HttpServerErrorException", "500 Internal Server Error"
                )
            )
        if resp is UNK:
            result = UNK
            status = LibObj("HttpStatus", name="OK", code=200)
        else:
            tn, ci, ctx = self.rtype_info(rtype)
            result = (
                self.convert(resp.f["body"], tn, ctx, ci, traced=False)
                if tn
                else resp.f["body"]
            )
            status = resp.f["status"]
        if name in ("getForObject", "postForObject", "patchForObject"):
            return result
        if name in ("put", "delete", "postForLocation"):
            return None
        return LibObj("ResponseEntity", body=result, status=status)

    def rtype_info(self, rtype):
        """Тип ответа -> (имя типа, ClassInfo|None, контекстный класс)."""
        if isinstance(rtype, LibObj) and rtype.kind == "PTR":
            return rtype.f["type"], None, rtype.f.get("ctx")
        if isinstance(rtype, JClass):
            return (rtype.ci.name if rtype.ci else rtype.name), rtype.ci, None
        return None, None, None

    def dispatch(self, meth, url, body, fr, node, headers=None):
        """-> ResponseEntity | UNK | None (хост недоступен)."""
        it = self.it
        parsed = self.parse_url(url)
        if parsed is None:
            return UNK
        host, path, query = parsed
        caller = fr.method if fr is not None else None
        if has_unk(host) or has_unk(
            path.split("/")[1] if path.count("/") > 1 else ""
        ):
            return self._dispatch_by_skeleton(
                meth, url, body, fr, node, caller, headers
            )
        module = self.module_of_host(host)
        if module is None:
            return None
        found = self.find_handler(module, meth, path)
        if found is None and has_unk(path):
            return self._dispatch_by_skeleton(
                meth, url, body, fr, node, caller, headers
            )
        if found is None:
            it.warn(f"no handler {meth} {module}{path}")
            return UNK
        mi, ci, pv = found
        q = dict(
            kv.split("=", 1) if "=" in kv else (kv, "")
            for kv in query.split("&")
            if kv
        )
        return self.serve(
            module,
            mi,
            ci,
            pv,
            q,
            body,
            caller,
            headers if isinstance(headers, LibObj) else None,
            path,
            meth,
        )

    def _dispatch_by_skeleton(
        self, meth, url, body, fr, node, caller, headers=None
    ):
        it = self.it
        p = it.p
        if node is None or fr is None or fr.cls is None:
            return UNK
        cs = p.cs_at.get((fr.cls.file, node.line, node.col))
        if cs is None:
            return UNK
        cands = [
            p.methods_by_id.get(t)
            for t in p.cs_edges[cs].get("remote_call", [])
        ]
        cands = [m for m in cands if m is not None]
        rx = re.compile(
            "^"
            + re.escape(url.split("?")[0].split("://")[-1]).replace(
                re.escape(UNK_CH), "[^/]+"
            )
            + "$"
        )
        ok = []
        for mi in cands:
            module = mi.cls.module
            for v, tpl, m2, ci in self.handlers.get(module, ()):
                if m2 is mi and (v is None or v == meth):
                    tp = (
                        module
                        + "/"
                        + "/".join(re.sub(r"^\{.*\}$", "XX", s) for s in tpl)
                    )
                    if rx.match(tp) or True:
                        ok.append((m2, ci, module, tpl))
        if len(ok) == 1:
            m2, ci, module, tpl = ok[0]
            pv = {
                s[1:-1].split(":")[0]: UNK_CH for s in tpl if s.startswith("{")
            }
            return self.serve(
                module,
                m2,
                ci,
                pv,
                {},
                body,
                caller,
                headers if isinstance(headers, LibObj) else None,
            )
        return UNK

    # ------------------------------------------------------------------------------
    # Spring Security
    def authenticate(self, o, n, a, fr):
        """Эмулирует ``AuthenticationManager.authenticate``.

        Загружает пользователя, вызывает проверки UserDetails и сверяет пароль
        с известным клиенту.
        """
        it = self.it
        if n != "authenticate":
            return UNK
        tok = a[0]
        username = tok.f.get("principal") if isinstance(tok, LibObj) else UNK
        module = fr.module
        ci = None
        for (m, fqn), c in it.p.classes.items():
            if (
                m == module
                and "UserDetailsService" in " ".join(c.iface_names)
                and c.kind == "class"
            ):
                ci = c
                break
        if ci is None:
            return UNK
        bean = it.bean(module, ci)
        user = it.invoke(
            next(m for m in it.p.find_methods(ci, "loadUserByUsername")),
            bean,
            [username],
            None,
        )
        if isinstance(user, JObj):
            # DaoAuthenticationProvider: проверки до сверки пароля, сверка,
            # проверки после.
            self._user_checks(
                user,
                (
                    "isAccountNonLocked",
                    "isEnabled",
                    "isAccountNonExpired",
                    "getPassword",
                ),
            )
            presented = (
                tok.f.get("credentials") if isinstance(tok, LibObj) else UNK
            )
            known = (
                it.known_passwords.get(username)
                if isinstance(username, str)
                else None
            )
            if (
                known is not None
                and isinstance(presented, str)
                and presented != known
            ):
                raise JavaThrow(
                    it.make_exc("BadCredentialsException", "Bad credentials")
                )
            self._user_checks(
                user, ("isCredentialsNonExpired", "getAuthorities")
            )
        return LibObj("Authentication", principal=user)

    def _user_checks(self, user, names):
        """Вызывает методы UserDetails так, как это делает Spring Security."""
        for nm in names:
            g = [
                m
                for m in self.it.p.find_methods(user.cls, nm)
                if not m.abstract and not m.params
            ]
            if g:
                self.it.lib_invoke(g[0], user, [])

    def lib_method(self, o, n, a, fr, node=None):
        """Выполняет методы библиотечных бинов веб-слоя (RabbitMQ, пароли)."""
        it = self.it
        k = o.kind
        if k in ("RabbitTemplate", "AmqpTemplate") and n.startswith(
            "convertAndSend"
        ):
            return self._rabbit(a, fr, node)
        if k in ("BCryptPasswordEncoder", "PasswordEncoder"):
            if n == "encode":
                return "{bcrypt}" + to_str(it, a[0])
            if n == "matches":
                return True
        if k == "Authentication":
            return UNK
        return UNK

    def _rabbit(self, a, fr, node):
        it = self.it
        p = it.p
        caller = fr.method if fr is not None else None
        if node is None or fr is None:
            return None
        cs = p.cs_at.get((fr.cls.file, node.line, node.col))
        if cs is None:
            return None
        for t in p.cs_edges[cs].get("message_delivery", []):
            mi = p.methods_by_id.get(t)
            if mi is None:
                continue
            if caller is not None and caller.id:
                it.trace.remote.add((caller.id, mi.id))
            bean = it.bean(mi.cls.module, mi.cls)
            saved_stack = it.stack
            it.stack = []
            try:
                msg = a[-1] if a else None
                it.invoke(mi, bean, [msg] if mi.params else [], None)
            except JavaThrow:
                pass
            finally:
                it.stack = saved_stack
        return None

    # ------------------------------------------------------------------------------
    # JSON
    def to_raw(self, v, traced=False):
        """Переводит объект в JSON-значения, как Jackson при сериализации.

        Результат — ``JMap``, ``JList`` и примитивы. При ``traced=True`` явные
        геттеры считаются исполненными; иначе они исполняются в отдельной
        трассе ``it.json_trace`` (для анализа гипотез разметки).
        """
        it = self.it
        if traced or getattr(self, "_in_raw", False):
            return self._to_raw(v, traced)
        from .interp import Trace

        saved = it.trace
        it.trace = Trace()
        self._in_raw = True
        try:
            return self._to_raw(v, True)
        finally:
            self._in_raw = False
            it.json_trace.merge(it.trace)
            it.trace = saved

    def _to_raw(self, v, traced=False):
        it = self.it
        seen = set()

        def go(x, depth=0):
            if depth > 30:
                return None
            if x is UNK or x is None or isinstance(x, (bool, int, float, str)):
                return x
            if isinstance(x, lib.Decimal):
                return float(x)
            if isinstance(x, JEnum):
                return x.name
            if isinstance(x, JOpt):
                return go(x.v, depth)
            if isinstance(x, JDate):
                return x.dt.strftime("%Y-%m-%d %H:%M:%S")
            if isinstance(x, JObj):
                if id(x) in seen:
                    return None
                seen.add(id(x))
                m = JMap()
                for fname, val in list(x.f.items()):
                    m[fname] = go(val, depth + 1)
                if traced:
                    for ms in x.cls.methods.values():
                        for mi in ms:
                            if (
                                not mi.static
                                and not mi.params
                                and re.match(r"^(get|is)[A-Z]", mi.name)
                                and mi.decl.body is not None
                                and "public" in mi.decl.mods
                            ):
                                try:
                                    it.lib_invoke(mi, x, [])
                                except (
                                    JavaThrow,
                                    TypeError,
                                    AttributeError,
                                    KeyError,
                                    IndexError,
                                    ValueError,
                                ):
                                    pass
                seen.discard(id(x))
                return m
            if isinstance(x, JSet):
                return JList(go(e, depth + 1) for e in x.values())
            if isinstance(x, dict):
                return JMap({k: go(e, depth + 1) for k, e in x.items()})
            if isinstance(x, (list, tuple)):
                return JList(go(e, depth + 1) for e in x)
            if isinstance(x, LibObj):
                return None
            return x

        return go(v)

    def convert(self, v, tname, ctx, ci=None, traced=False, tvars=None):
        """Переводит JSON-значение в значение типа ``tname``, как Jackson."""
        it = self.it
        if v is UNK or v is None or tname is None:
            return v
        self._tracing = traced
        if not traced:
            from .interp import Trace

            saved = it.trace
            it.trace = Trace()
            try:
                return self._conv(v, tname, ctx, ci, tvars or {})
            finally:
                it.json_trace.merge(
                    it.trace
                )  # что исполнил бы разбор Jackson (для анализа гипотез)
                it.trace = saved
        return self._conv(v, tname, ctx, ci, tvars or {})

    def _conv(self, v, tname, ctx, ci, tvars):
        it = self.it
        p = it.p
        t = tname.strip()
        if t in tvars:
            t, ctx = tvars[t]
            tvars = {}
        if v is UNK or v is None:
            return v
        base = strip_generics(t)
        args = type_args(t)
        if base.endswith("[]"):
            et = base[:-2]
            return JList(
                self._conv(x, et, ctx, ci, tvars) for x in self._items(v)
            )
        short = base.split(".")[-1]
        if short in (
            "List",
            "ArrayList",
            "LinkedList",
            "Collection",
            "Iterable",
        ):
            et = args[0] if args else "Object"
            return JList(
                self._conv(x, et, ctx, None, tvars) for x in self._items(v)
            )
        if short in ("Set", "HashSet", "LinkedHashSet"):
            et = args[0] if args else "Object"
            s = JSet()
            for x in self._items(v):
                y = self._conv(x, et, ctx, None, tvars)
                s[lib.hk(y)] = y
            return s
        if short in ("Map", "HashMap", "LinkedHashMap"):
            vt = args[1] if len(args) > 1 else "Object"
            if isinstance(v, dict):
                return JMap(
                    {
                        k: self._conv(e, vt, ctx, None, tvars)
                        for k, e in v.items()
                    }
                )
            return v
        if short in ("Object", "?", "T", "E", "V", "K"):
            return self.to_raw(v) if isinstance(v, (JObj, JEnum)) else v
        if short in BOXED:
            return self._prim(v, short)
        if ci is None:
            ci = p.resolve(base, ctx) if ctx is not None else None
        if ci is None:
            return self.to_raw(v) if isinstance(v, (JObj, JEnum)) else v
        if ci.kind == "enum":
            st = it.statics_of(ci)
            if isinstance(v, str) and v in st:
                return st[v]
            if isinstance(v, int) and 0 <= v < len(ci.enum_names):
                return st[ci.enum_names[v]]
            return v
        src = (
            v.f
            if isinstance(v, JObj)
            else (v if isinstance(v, dict) else None)
        )
        if src is None:
            return v
        obj = JObj(ci, it.default_fields(ci))
        it._run_ctor(ci, obj, [], None, None)
        tp = list(ci.decl.tparams or [])
        sub = dict(tvars)
        for name_, ta in zip(tp, args):
            sub[name_] = (ta, ctx)
        for f in p.all_fields(ci):
            if f.name in src:
                val = self._conv(
                    src[f.name], f.type, f.cls, None, sub if tp else {}
                )
                setter = None
                if True:
                    cap = f.name[0].upper() + f.name[1:]
                    cs = [
                        m
                        for m in p.find_methods(ci, "set" + cap)
                        if not m.abstract
                        and len(m.params) == 1
                        and not m.static
                    ]
                    setter = cs[0] if cs else None
                if setter is not None:
                    it.lib_invoke(
                        setter, obj, [val]
                    )  # Jackson вызывает явный сеттер
                else:
                    obj.f[f.name] = val
        return obj

    def _items(self, v):
        if isinstance(v, JSet):
            return list(v.values())
        if isinstance(v, (list, tuple)):
            return list(v)
        if isinstance(v, dict):
            return list(v.values())
        return []

    def _prim(self, v, short):
        try:
            if short in (
                "int",
                "Integer",
                "long",
                "Long",
                "short",
                "Short",
                "byte",
                "Byte",
            ):
                return (
                    int(v)
                    if not isinstance(v, bool)
                    and isinstance(v, (int, float, str))
                    else v
                )
            if short in ("double", "Double", "float", "Float"):
                return (
                    float(v)
                    if isinstance(v, (int, float, str))
                    and not isinstance(v, bool)
                    else v
                )
            if short in ("boolean", "Boolean"):
                return v
            if short == "BigDecimal":
                return lib.Decimal(str(v))
            if short == "String":
                return (
                    v
                    if isinstance(v, str)
                    else (
                        to_str(self.it, v)
                        if isinstance(v, (int, float))
                        else v
                    )
                )
        except (ValueError, TypeError):
            return v
        return v


def lib_ann_name(args):
    """Возвращает имя из аргументов аннотации: ``value``, ``name`` и т. п."""
    if not args:
        return None
    m = re.search(r"(?:value|name)\s*=\s*\"([^\"]+)\"", args)
    if m:
        return m.group(1)
    m = re.match(r"^\s*\(\s*\"([^\"]+)\"", args)
    return m.group(1) if m else None


def entry_request(web, verb, path, body=None, query=None, headers=None):
    """Выполняет запрос клиента через шлюз.

    Обработчик ищется по всем сервисам. Возвращает ``ResponseEntity`` или
    ``None``, если обработчика нет.
    """
    it = web.it
    for module in sorted(web.handlers):
        found = web.find_handler(module, verb, path)
        if found:
            mi, ci, pv = found
            return web.serve(
                module,
                mi,
                ci,
                pv,
                query or {},
                body,
                None,
                headers,
                path,
                verb,
            )
    it.warn(f"entry: no handler {verb} {path}")
    return None
