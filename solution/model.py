"""Модель проекта: скелет + разобранные исходники -> классы, методы, поля, разрешение типов."""
import os, re, gzip, json, collections
from jparse import (parse_file, ClassDecl, MethodDecl, FieldDecl, New, Lambda, LocalClass, Node, Block,
                    Call, Name)

PRIM_DEFAULT = {"int": 0, "long": 0, "short": 0, "byte": 0, "char": "\0", "float": 0.0, "double": 0.0, "boolean": False}
NUMERIC_BOXED = {"Integer", "Long", "Short", "Byte", "Double", "Float"}


def load_json(path):
    with (gzip.open(path, "rt", encoding="utf-8") if path.endswith(".gz") else open(path, encoding="utf-8")) as fh:
        return json.load(fh)


def strip_generics(t):
    """List<String>[] -> List[]; java.util.Map.Entry<K,V> -> java.util.Map.Entry."""
    out, depth = [], 0
    for ch in t:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        elif depth == 0:
            out.append(ch)
    return "".join(out).strip()


def type_args(t):
    """'Response<List<String>>' -> ['List<String>']"""
    i = t.find("<")
    if i < 0 or not t.endswith(">"):
        return []
    inner, depth, cur, res = t[i + 1:-1], 0, "", []
    for ch in inner:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        if ch == "," and depth == 0:
            res.append(cur.strip()); cur = ""
        else:
            cur += ch
    if cur.strip():
        res.append(cur.strip())
    return res


class FieldInfo:
    __slots__ = ("name", "type", "init", "static", "final", "annots", "cls", "line")

    def __init__(self, fd, cls):
        self.name, self.type, self.init = fd.name, fd.type, fd.init
        self.static = "static" in fd.mods or cls.kind == "interface"
        self.final = "final" in fd.mods
        self.annots = {a.name.split(".")[-1]: a.args for a in fd.annots}
        self.cls, self.line = cls, fd.line


class MethodInfo:
    __slots__ = ("name", "decl", "cls", "id", "params", "static", "abstract", "ctor", "annots", "ret", "varargs", "_called")

    def __init__(self, md, cls):
        self.name, self.decl, self.cls = md.name, md, cls
        self.params = [(p.type, p.name, {a.name.split(".")[-1]: a.args for a in p.annots}) for p in md.params]
        self.static = "static" in md.mods
        self.abstract = md.body is None
        self.ctor = md.ctor
        self.annots = {a.name.split(".")[-1]: a.args for a in md.annots}
        self.ret = md.ret
        self.id = None
        self._called = None
        self.varargs = bool(md.params and md.params[-1].varargs)

    def __repr__(self):
        return f"<{self.cls.name}#{self.name}/{len(self.params)}>"


class ClassInfo:
    def __init__(self, decl, module, file, pkg, imports, outer=None):
        self.decl, self.module, self.file, self.pkg = decl, module, file, pkg
        self.imports = imports
        self.name = decl.name
        self.fqn = decl.fqn
        self.kind = decl.kind
        self.outer = outer
        self.annots = {a.name.split(".")[-1]: a.args for a in decl.annots}
        self.fields = collections.OrderedDict()
        self.methods = collections.defaultdict(list)
        self.ctors = []
        self.inner = {}
        self.enum_names = [e.name for e in decl.enums]
        self.super_name = decl.ext
        self.iface_names = list(decl.impls)
        self._super = False
        self._ifaces = None
        self.id = f"type:{module}:{decl.fqn}"
        self.anon = decl.anon
        for fd in decl.fields:
            self.fields[fd.name] = FieldInfo(fd, self)
        for md in decl.methods:
            mi = MethodInfo(md, self)
            (self.ctors if md.ctor else self.methods[md.name]).append(mi)

    def __repr__(self):
        return f"<class {self.module}:{self.fqn}>"


def _walk_names(n, out, depth=0):
    """Имена вызываемых методов в теле (Call.name), включая лямбды и анонимные классы."""
    if depth > 200:
        return
    if isinstance(n, Call):
        out.add(n.name)
    if isinstance(n, Node):
        for s in n.__slots__:
            if s in ("outer", "cls"):
                continue
            _walk_names(getattr(n, s), out, depth + 1)
    elif isinstance(n, (list, tuple)):
        for x in n:
            _walk_names(x, out, depth + 1)


def called_names(mi):
    """Простые имена методов, которые вызывает исходный код метода (кэшируется)."""
    cn = mi._called
    if cn is None:
        cn = set()
        if mi.decl.body is not None:
            _walk_names(mi.decl.body, cn)
        mi._called = cn
    return cn


class Project:
    def __init__(self, skeleton_path, root):
        self.sk = load_json(skeleton_path)
        self.root = root
        N = self.N = self.sk["nodes"]
        self.classes = {}                # (module, fqn) -> ClassInfo
        self.by_module_simple = collections.defaultdict(list)
        self.methods_by_id = {}
        self._parse_all()
        self._index_skeleton()

    # ------------------------------------------------------------------ загрузка
    def _parse_all(self):
        N = self.N
        files = sorted((n["module"], n["path"]) for n in N.values() if n["kind"] == "file" and n["path"].endswith(".java"))
        self.parsed = {}
        method_by_start = collections.defaultdict(dict)       # file -> (name,start)-> id
        for k, n in N.items():
            if n["kind"] == "method":
                method_by_start[n["file"]][(n["name"], n["line"])] = k
        for module, path in files:
            p, types = parse_file(os.path.join(self.root, path))
            self.parsed[path] = (p, types)

            def reg(decl, outer, p=p, module=module, path=path):
                ci = ClassInfo(decl, module, path, p.pkg, p.imports, outer)
                self.classes[(module, decl.fqn)] = ci
                self.by_module_simple[(module, decl.name)].append(ci)
                if outer is not None:
                    outer.inner[decl.name] = ci
                for md_list in list(ci.methods.values()) + [ci.ctors]:
                    for mi in md_list:
                        mi.id = method_by_start[path].get((mi.name, mi.decl.start))
                        if mi.id:
                            self.methods_by_id[mi.id] = mi
                for inner in decl.inner:
                    reg(inner, ci)
                return ci
            for t in types:
                reg(t, None)
        # enum-константы с телами и анонимные классы регистрируются лениво в интерпретаторе
        self.method_by_start = method_by_start

    def _index_skeleton(self):
        N = self.N
        self.cs_at = {}                      # (file, line, col) -> call_site id
        for k, n in N.items():
            if n["kind"] == "call_site":
                self.cs_at[(n["file"], n["line"], n["col"])] = k
        self.cs_edges = collections.defaultdict(lambda: collections.defaultdict(list))
        for e in self.sk["edges"]:
            t = e["type"]
            if t in ("calls", "runtime_dispatch", "remote_call", "data_access", "message_delivery", "creates"):
                self.cs_edges[e["source"]][t].append(e["target"])
        self.tables = {k: n for k, n in N.items() if n["kind"] == "data_resource"}
        # таблицы по файлу сущности
        self.tables_by_file = collections.defaultdict(list)
        for k, n in self.tables.items():
            for o in n.get("origin") or []:
                self.tables_by_file[o["file"]].append(k)
        self.modules = {n["name"] for n in N.values() if n["kind"] == "module"}

    # ------------------------------------------------------------------ поиск типов
    def visible_modules(self, module):
        return (module, "ts-common")

    def lookup_fqn(self, module, fqn):
        for m in self.visible_modules(module):
            ci = self.classes.get((m, fqn))
            if ci:
                return ci
        # вложенные: a.b.Outer.Inner
        parts = fqn.split(".")
        for i in range(len(parts) - 1, 0, -1):
            outer = ".".join(parts[:i])
            for m in self.visible_modules(module):
                ci = self.classes.get((m, outer))
                if ci:
                    cur = ci
                    for nm in parts[i:]:
                        cur = cur.inner.get(nm)
                        if cur is None:
                            break
                    if cur is not None:
                        return cur
        return None

    def resolve(self, tname, ctx):
        """Имя типа (как в коде) в контексте класса ctx -> ClassInfo или None (библиотечный тип)."""
        if not tname:
            return None
        base = strip_generics(tname).replace("[]", "").strip()
        if not base or base in PRIM_DEFAULT or base in ("void", "?"):
            return None
        module = ctx.module
        if "." in base:
            ci = self.lookup_fqn(module, base)
            if ci:
                return ci
            first, rest = base.split(".", 1)
            c0 = self.resolve(first, ctx)
            if c0:
                cur = c0
                for nm in rest.split("."):
                    cur = cur.inner.get(nm) if cur else None
                return cur
            return None
        # вложенные классы окружения и родителей
        c = ctx
        while c is not None:
            if c.name == base and not c.anon:
                return c
            if base in c.inner:
                return c.inner[base]
            sc = self.super_of(c)
            while sc is not None:
                if base in sc.inner:
                    return sc.inner[base]
                sc = self.super_of(sc)
            c = c.outer
        # явный импорт
        for static, q in ctx.imports:
            if not static and q.endswith("." + base):
                ci = self.lookup_fqn(module, q)
                return ci            # None -> библиотечный класс, импортированный явно
        # тот же пакет
        if ctx.pkg:
            ci = self.lookup_fqn(module, ctx.pkg + "." + base)
            if ci:
                return ci
        else:
            for m in self.visible_modules(module):
                for ci in self.by_module_simple.get((m, base), []):
                    if not ci.pkg:
                        return ci
        # импорт со звёздочкой
        for static, q in ctx.imports:
            if q.endswith(".*"):
                ci = self.lookup_fqn(module, q[:-2] + "." + base)
                if ci:
                    return ci
        return None

    def super_of(self, ci):
        if ci._super is False:
            ci._super = None                 # защита от рекурсии при разрешении имени
            r = self.resolve(ci.super_name, ci.outer or ci) if ci.super_name and ci.kind != "interface" else None
            ci._super = None if r is ci else r
        return ci._super

    def ifaces_of(self, ci):
        if ci._ifaces is None:
            res = []
            for n in ci.iface_names:
                r = self.resolve(n, ci.outer or ci) if "." not in n else self.resolve(n, ci)
                if r is not None and r is not ci:
                    res.append(r)
            ci._ifaces = res
        return ci._ifaces

    def supertypes(self, ci):
        """Все надтипы (транзитивно), включая сам класс, ближайшие первыми."""
        out, seen, st = [], set(), [ci]
        while st:
            c = st.pop(0)
            if id(c) in seen:
                continue
            seen.add(id(c)); out.append(c)
            s = self.super_of(c)
            if s:
                st.append(s)
            st.extend(self.ifaces_of(c))
        return out

    def is_subclass(self, ci, other):
        return any(c is other for c in self.supertypes(ci))

    def find_field(self, ci, name):
        c = ci
        while c is not None:
            f = c.fields.get(name)
            if f:
                return f
            for i in self.ifaces_of(c):
                f = self.find_field(i, name)
                if f:
                    return f
            c = self.super_of(c)
        return None

    def all_fields(self, ci):
        """Нестатические поля класса и родителей, родители первыми."""
        chain = []
        c = ci
        while c is not None:
            chain.append(c)
            c = self.super_of(c)
        out = []
        for c in reversed(chain):
            out.extend(f for f in c.fields.values() if not f.static)
        return out

    def find_methods(self, ci, name):
        """Кандидаты метода по имени: класс, суперклассы, интерфейсы (default)."""
        res = []
        for c in self.supertypes(ci):
            res.extend(c.methods.get(name, ()))
        return res

    def implementations(self, iface, module):
        """Не абстрактные классы модуля (и ts-common), реализующие/наследующие iface."""
        out = []
        for (m, fqn), ci in self.classes.items():
            if m in self.visible_modules(module) and ci is not iface and ci.kind == "class" and not ci.anon \
                    and "abstract" not in ci.decl.mods and self.is_subclass(ci, iface):
                out.append(ci)
        return out

    def has_annot(self, ci, *names):
        return any(n in ci.annots for n in names)
