"""Репозитории Spring Data поверх БД в памяти: производные запросы по имени метода, ORM-таблицы коллекций,
учёт обращений к таблицам (data)."""
import re, collections
from values import *
import config as _cfg
from model import strip_generics, type_args, PRIM_DEFAULT
from jparse import Lit, Name, FieldAcc


def snake(s):
    s = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", s)
    return s.lower()


def _top_level(args):
    """Аргументы аннотации без содержимого вложенных скобок/фигурных скобок."""
    out, depth = [], 0
    for ch in args:
        if ch in "({":
            depth += 1
            if depth == 1:
                out.append(ch)
            continue
        if ch in ")}":
            depth -= 1
            if depth == 0:
                out.append(ch)
            continue
        if depth <= 1:
            out.append(ch)
    return "".join(out)


def ann_str(args, key=None):
    """Значение строкового аргумента аннотации: (name = "x") / ("x") — только верхний уровень."""
    if not args:
        return None
    args = _top_level(args)
    if key:
        m = re.search(r"\b" + key + r"\s*=\s*\"([^\"]*)\"", args)
        if m:
            return m.group(1)
        return None
    m = re.search(r"\"([^\"]*)\"", args)
    return m.group(1) if m else None


class RepoProxy:
    __slots__ = ("ci", "entity", "meta")

    def __init__(self, ci, entity, meta):
        self.ci, self.entity, self.meta = ci, entity, meta


class LazyColl(JList):
    """Лениво загружаемая коллекция сущности: первое обращение даёт SQL к таблице коллекции."""

    def __init__(self, items, on_touch):
        super().__init__(items)
        self._cb = on_touch

    def _t(self):
        cb = self._cb
        if cb is not None:
            self._cb = None
            cb()

    def __iter__(self):
        self._t()
        return super().__iter__()

    def __len__(self):
        self._t()
        return super().__len__()

    def __getitem__(self, i):
        self._t()
        return super().__getitem__(i)

    def __contains__(self, x):
        self._t()
        return super().__contains__(x)

    def append(self, x):
        self._t()
        super().append(x)

    def __bool__(self):
        self._t()
        return super().__len__() > 0


class EntityMeta:
    def __init__(self, ci, it):
        self.ci = ci
        self.it = it
        p = it.p
        a = ci.annots
        tname = ann_str(a.get("Table"), "name") if a.get("Table") else None
        self.table_name = tname or snake(ci.name)
        self.table = it.tables.get(self.table_name)
        self.table_node = self._node(self.table_name, ci)
        self.id_field = None
        self.cols = []                 # (field, col, type)
        self.embedded = []             # (field, embedded ClassInfo)
        self.colls = []                # dict(field, table, node, join, valcol, elem_type, eager)
        for f in p.all_fields(ci):
            if "Transient" in f.annots or f.static:
                continue
            if "Id" in f.annots or "EmbeddedId" in f.annots:
                self.id_field = f.name
            if "ElementCollection" in f.annots:
                ctab = None
                if "CollectionTable" in f.annots:
                    ctab = ann_str(f.annots["CollectionTable"], "name")
                if not ctab:
                    ctab = snake(ci.name) + "_" + snake(f.name)
                    ctab = ctab if ctab in it.tables else snake(f.name)
                join = "id"
                jc = f.annots.get("CollectionTable") or ""
                m = re.search(r"JoinColumn\s*\(\s*name\s*=\s*\"([^\"]+)\"", jc)
                tbl = it.tables.get(ctab)
                join = m.group(1) if m else (snake(ci.name) + "_id")
                if tbl is not None and join not in tbl.cols:
                    for c in tbl.cols:
                        if c.endswith("_id"):
                            join = c
                            break
                et = type_args(f.type)[0] if type_args(f.type) else "String"
                eager = "EAGER" in f.annots["ElementCollection"]
                self.colls.append(dict(field=f.name, table=tbl, name=ctab, node=self._node(ctab, ci), join=join,
                                       elem=et, eager=eager, set=strip_generics(f.type) in ("Set", "HashSet")))
                continue
            if "Embedded" in f.annots or "EmbeddedId" in f.annots:
                eci = p.resolve(f.type, f.cls)
                if eci is not None:
                    self.embedded.append((f.name, eci))
                    continue
            col = ann_str(f.annots.get("Column"), "name") if f.annots.get("Column") else None
            self.cols.append((f.name, col or snake(f.name), f.type, f))

    def _node(self, tname, ci):
        p = self.it.p
        for k in p.tables_by_file.get(ci.file, []):
            if p.tables[k]["name"] == tname:
                return k
        for k, n in p.tables.items():
            if n["name"] == tname and n.get("schema", "").startswith(ci.module.split("-service")[0]):
                return k
        for k, n in p.tables.items():
            if n["name"] == tname:
                return k
        return None


class Repos:
    def __init__(self, it):
        self.it = it
        self.metas = {}
        self.proxies = {}
        it.repos = self

    def is_repo(self, tci):
        if tci.kind != "interface":
            return False
        return any(re.search(r"Repository\b", n) for n in tci.iface_names) or \
            any(self.is_repo(i) for i in self.it.p.ifaces_of(tci))

    def entity_of(self, tci):
        """Тип сущности — первый параметр Repository<Entity, Id> (в самом интерфейсе или предках)."""
        for n in tci.iface_names:
            if "Repository" in n:
                ta = type_args(n)
                if ta:
                    return self.it.p.resolve(ta[0], tci)
        for i in self.it.p.ifaces_of(tci):
            e = self.entity_of(i)
            if e is not None:
                return e
        return None

    def proxy(self, tci):
        px = self.proxies.get(tci)
        if px is None:
            ent = self.entity_of(tci)
            px = RepoProxy(tci, ent, self.meta(ent) if ent is not None else None)
            self.proxies[tci] = px
        return px

    def meta(self, ent):
        m = self.metas.get(ent)
        if m is None:
            m = EntityMeta(ent, self.it)
            self.metas[ent] = m
        return m

    # ------------------------------------------------------------------ учёт обращений
    def touch(self, caller, node):
        if caller is not None and caller.id and node:
            self.it.trace.data.add((caller.id, node))

    # ------------------------------------------------------------------ строка <-> сущность
    def conv_in(self, raw, ftype, ctx):
        t = strip_generics(ftype)
        if raw is None:
            return PRIM_DEFAULT.get(t, None)
        if t in ("int", "long", "short", "byte", "Integer", "Long", "Short"):
            try:
                return int(raw)
            except (TypeError, ValueError):
                return raw
        if t in ("double", "float", "Double", "Float"):
            try:
                return float(raw)
            except (TypeError, ValueError):
                return raw
        if t in ("boolean", "Boolean"):
            return bool(raw)
        if t == "String":
            return raw if isinstance(raw, str) else str(raw)
        if t == "UUID":
            return raw
        eci = self.it.p.resolve(t, ctx)
        if eci is not None and eci.kind == "enum":
            st = self.it.statics_of(eci)
            names = eci.enum_names
            if isinstance(raw, str) and raw in st:
                return st[raw]
            if isinstance(raw, int) and 0 <= raw < len(names):
                return st[names[raw]]
        return raw

    def conv_out(self, v, ftype, f=None):
        if isinstance(v, JEnum):
            if f is not None and "Enumerated" in f.annots and "STRING" in f.annots["Enumerated"]:
                return v.name
            return v.ordinal if (f is None or "Enumerated" not in f.annots) and not self._enum_str(f) else v.name
        if isinstance(v, bool):
            return 1 if v else 0
        if v is UNK:
            return None
        return v

    def _enum_str(self, f):
        return f is not None and f.annots.get("Convert") is not None

    def load(self, meta, row, caller):
        """Строка -> сущность. Конструктор по умолчанию выполняется (как в Hibernate).
        Повторная загрузка той же строки в рамках запроса (OSIV) возвращает уже загруженный объект."""
        sess = self.it.session
        key = (meta.table_name, row.get(self._idcol(meta)))
        cached = sess.get(key)
        if cached is not None:
            return cached
        obj = self._load(meta, row, caller)
        if key[1] is not None:
            sess[key] = obj
        return obj

    def _load(self, meta, row, caller):
        it = self.it
        ci = meta.ci
        obj = JObj(ci, it.default_fields(ci))
        saved_o, it.origin = it.origin, "hib"
        try:
            it._run_ctor(ci, obj, [], None, None)
        finally:
            it.origin = saved_o
        for fname, col, ftype, f in meta.cols:
            if col in row:
                obj.f[fname] = self.conv_in(row[col], ftype, f.cls)
        for fname, eci in meta.embedded:
            sub = JObj(eci, it.default_fields(eci))
            it._run_ctor(eci, sub, [], None, None)
            for sf in it.p.all_fields(eci):
                col = ann_str(sf.annots.get("Column"), "name") if sf.annots.get("Column") else None
                col = col or snake(sf.name)
                if col in row:
                    sub.f[sf.name] = self.conv_in(row[col], sf.type, sf.cls)
            obj.f[fname] = sub
        pk = row.get(self._idcol(meta))
        for c in meta.colls:
            tbl = c["table"]
            items = []
            if tbl is not None:
                rows = [r for r in tbl.rows if r.get(c["join"]) == pk]
                col_order = [k for k in tbl.cols if k.endswith("_order")]
                if col_order:
                    rows.sort(key=lambda r: r.get(col_order[0]) or 0)
                for r in rows:
                    items.append(self._elem(c, r, meta))
            if c["eager"]:
                if items or True:
                    self.touch(caller, c["node"])
                obj.f[c["field"]] = JSet({hk_(x): x for x in items}) if c["set"] else JList(items)
            else:
                node = c["node"]
                holder = obj

                def on_touch(node=node, obj=obj, meta=meta):
                    self.touch(self._attr_method(obj), node)
                lc = LazyColl(items, on_touch)
                lc.tag_owner = None if False else None
                obj.f[c["field"]] = lc
                if obj.tag is None:
                    obj.tag = {"loader": caller}
        if obj.tag is None:
            obj.tag = {"loader": caller}
        else:
            obj.tag.setdefault("loader", caller)
        return obj

    def _attr_method(self, obj):
        """Метод, которому приписывается ленивый SQL: ближайший не-сущностный проектный кадр, иначе загрузивший метод."""
        it = self.it
        if it.web is not None and it.web.in_serialization:
            # Jackson читает коллекцию после возврата из метода проекта: в эталоне такой SQL ни к какому методу не относится
            return None if _cfg.DROP_SERIALIZATION_LAZY_SQL else (obj.tag.get("loader") if isinstance(obj.tag, dict) else None)
        for fr in reversed(it.stack):
            if fr.method is not None and "Entity" not in fr.method.cls.annots and fr.method.id:
                return fr.method
        return obj.tag.get("loader") if isinstance(obj.tag, dict) else None

    def _elem(self, c, r, meta):
        et = c["elem"]
        eci = self.it.p.resolve(et, meta.ci)
        if eci is None:
            col = snake(c["field"])
            v = r.get(col)
            if v is None:
                for k in r:
                    if k not in (c["join"],) and not k.endswith("_order"):
                        v = r[k]
                        break
            return self.conv_in(v, et, meta.ci)
        sub = JObj(eci, self.it.default_fields(eci))
        self.it._run_ctor(eci, sub, [], None, None)
        for sf in self.it.p.all_fields(eci):
            col = snake(sf.name)
            if col in r:
                sub.f[sf.name] = self.conv_in(r[col], sf.type, sf.cls)
        return sub

    def _idcol(self, meta):
        for fname, col, ftype, f in meta.cols:
            if fname == meta.id_field:
                return col
        return "id"

    def to_row(self, meta, obj):
        row = {}
        for fname, col, ftype, f in meta.cols:
            row[col] = self.conv_out(obj.f.get(fname), ftype, f)
        for fname, eci in meta.embedded:
            sub = obj.f.get(fname)
            for sf in self.it.p.all_fields(eci):
                col = ann_str(sf.annots.get("Column"), "name") if sf.annots.get("Column") else None
                row[col or snake(sf.name)] = self.conv_out(sub.f.get(sf.name) if isinstance(sub, JObj) else None, sf.type, sf)
        return row

    # ------------------------------------------------------------------ вызовы репозитория
    def call(self, px, name, args, fr):
        it = self.it
        caller = fr.method if fr is not None else None
        meta = px.meta
        if meta is None:
            return UNK
        if meta.table is None:
            it.warn(f"no table {meta.table_name}")
            return UNK
        m = self._decl(px, name, len(args))
        ret = strip_generics(m.ret) if m is not None and m.ret else None
        rt_full = m.ret if m is not None else None
        # --- стандартные методы
        if name in ("save", "saveAndFlush"):
            return self._save(meta, args[0], caller)
        if name == "saveAll":
            out = JList()
            for e in args[0]:
                out.append(self._save(meta, e, caller))
            return out
        if name in ("delete", "remove"):
            self._delete_rows(meta, [self._id_of(meta, args[0])], caller)
            return None
        if name == "deleteAll":
            self._delete_rows(meta, [r.get(self._idcol(meta)) for r in list(meta.table.rows)], caller)
            return None
        if name in ("deleteById", "removeById"):
            self._delete_rows(meta, [args[0]], caller)
            return None
        if name == "findById":
            hit = self.it.session.get((meta.table_name, args[0]))
            if hit is not None:                       # кэш первого уровня: SQL не выполняется
                return JOpt(hit) if strip_generics(rt_full or "") == "Optional" else hit
            return self._wrap(rt_full, self._find(meta, [(self._idcol(meta), "=", args[0])], caller, many=False))
        if name == "existsById":
            return len([r for r in meta.table.rows if r.get(self._idcol(meta)) == args[0]]) > 0 if self._touch_base(meta, caller) else False
        if name == "findAll":
            rows = self._select(meta, lambda r: True, caller)
            return self._wrap(rt_full, rows, many=True)
        if name == "count":
            self._touch_base(meta, caller)
            return len(meta.table.rows)
        if name == "findAllById":
            ids = list(args[0])
            rows = self._select(meta, lambda r: r.get(self._idcol(meta)) in ids, caller)
            return self._wrap(rt_full, rows, many=True)
        # --- @Query
        if m is not None and "Query" in m.annots:
            return self._native(meta, m, args, caller, rt_full)
        # --- производные запросы
        return self._derived(meta, name, args, caller, rt_full)

    def _touch_base(self, meta, caller):
        self.touch(caller, meta.table_node)
        return True

    def _decl(self, px, name, argc):
        cands = [m for m in self.it.p.find_methods(px.ci, name) if len(m.params) == argc]
        return cands[0] if cands else None

    def _id_of(self, meta, obj):
        return obj.f.get(meta.id_field) if isinstance(obj, JObj) else obj

    def _select(self, meta, pred, caller):
        self.touch(caller, meta.table_node)
        rows = [r for r in meta.table.rows if pred(r)]
        return rows

    def _find(self, meta, conds, caller, many):
        def pred(r):
            for col, op, val in conds:
                if not self._cmp(r.get(col), op, val):
                    return False
            return True
        rows = self._select(meta, pred, caller)
        return rows

    @staticmethod
    def _eq(a, b):
        """Сравнение как в MySQL (utf8mb4_0900_ai_ci): строки без учёта регистра."""
        if a is None or b is None:
            return a is None and b is None
        if a == b:
            return True
        return str(a).lower() == str(b).lower()

    def _cmp(self, a, op, b):
        if op == "=":
            return self._eq(a, b)
        if op == "!=":
            return not self._cmp(a, "=", b)
        if op == "in":
            return any(self._cmp(a, "=", x) for x in b)
        if op == "not in":
            return not any(self._cmp(a, "=", x) for x in b)
        if op == "like":
            pat = "^" + re.escape(str(b)).replace("%", ".*") + "$"
            return a is not None and re.match(pat, str(a), re.I) is not None
        if op == "contains":
            return a is not None and str(b) in str(a)
        if op == "starts":
            return a is not None and str(a).startswith(str(b))
        if op == "ends":
            return a is not None and str(a).endswith(str(b))
        if op == "isnull":
            return a is None
        if op == "notnull":
            return a is not None
        try:
            if op == ">":
                return a > b
            if op == "<":
                return a < b
            if op == ">=":
                return a >= b
            if op == "<=":
                return a <= b
        except TypeError:
            return False
        return False

    def _wrap(self, rt_full, rows, many=None):
        """Строки -> результат нужного вида (Optional / List / сущность)."""
        meta_rows = rows
        return ("ROWS", rt_full, meta_rows)

    def _finish(self, meta, rt_full, rows, caller):
        it = self.it
        rt = strip_generics(rt_full) if rt_full else ""
        if rt in ("long", "int", "Long", "Integer"):
            return len(rows)
        if rt in ("boolean", "Boolean"):
            return len(rows) > 0
        if rt == "void" or rt == "":
            return None
        ents = [self.load(meta, r, caller) for r in rows]
        if rt == "Optional":
            return JOpt(ents[0] if ents else None)
        if rt in ("List", "ArrayList", "Collection", "Iterable", "LinkedList", "Set", "HashSet"):
            return JList(ents)
        return ents[0] if ents else None

    # --- сохранение
    def _save(self, meta, obj, caller):
        it = self.it
        if not isinstance(obj, JObj):
            return obj
        self._touch_base(meta, caller)
        idf = meta.id_field
        if idf and (obj.f.get(idf) in (None, "")):
            obj.f[idf] = fake_uuid()
        row = self.to_row(meta, obj)
        idc = self._idcol(meta)
        found = None
        for r in meta.table.rows:
            if r.get(idc) == row.get(idc):
                found = r
                break
        full = {c: None for c in meta.table.cols}
        full.update({k: v for k, v in row.items() if k in meta.table.cols})
        if found is not None:
            found.update(full)
        else:
            meta.table.rows.append(full)
        self.it.session[(meta.table_name, row.get(idc))] = obj
        for c in meta.colls:
            coll = obj.f.get(c["field"])
            vals = list(coll) if isinstance(coll, (list, dict)) and coll is not None and not isinstance(coll, LazyColl) else (
                list(super(LazyColl, coll).__iter__()) if isinstance(coll, LazyColl) else [])
            if isinstance(coll, JSet):
                vals = list(coll.values())
            tbl = c["table"]
            if tbl is None:
                continue
            if vals or found is not None:
                self.touch(caller, c["node"])
            tbl.rows[:] = [r for r in tbl.rows if r.get(c["join"]) != row.get(idc)]
            for i, v in enumerate(vals):
                r = {k: None for k in tbl.cols}
                r[c["join"]] = row.get(idc)
                for k in tbl.cols:
                    if k.endswith("_order"):
                        r[k] = i
                eci = it.p.resolve(c["elem"], meta.ci)
                if eci is not None and isinstance(v, JObj):
                    for sf in it.p.all_fields(eci):
                        r[snake(sf.name)] = v.f.get(sf.name)
                else:
                    vc = [k for k in tbl.cols if k != c["join"] and not k.endswith("_order")]
                    if vc:
                        r[vc[0]] = v
                tbl.rows.append(r)
        return obj

    def _delete_rows(self, meta, ids, caller):
        self._touch_base(meta, caller)
        idc = self._idcol(meta)
        for c in meta.colls:
            if c["table"] is not None:
                self.touch(caller, c["node"])
                c["table"].rows[:] = [r for r in c["table"].rows if r.get(c["join"]) not in ids]
        meta.table.rows[:] = [r for r in meta.table.rows if r.get(idc) not in ids]
        for i in ids:
            self.it.session.pop((meta.table_name, i), None)

    # --- производные запросы
    def _derived(self, meta, name, args, caller, rt_full):
        m = re.match(r"^(find|get|read|query|count|exists|delete|remove)(Distinct)?(First\d*|Top\d*)?(All)?(?:\w*?)By(.*)$", name)
        if not m:
            self.it.warn(f"repo? {name}")
            return UNK
        verb, rest = m.group(1), m.group(5)
        limit = None
        if m.group(3):
            d = re.sub(r"\D", "", m.group(3))
            limit = int(d) if d else 1
        order = None
        mo = re.match(r"^(.*?)OrderBy(.*)$", rest)
        if mo:
            rest, order = mo.group(1), mo.group(2)
        conds = self._parse_conds(meta, rest)
        if conds is None:
            self.it.warn(f"repo cond? {name}")
            return UNK
        # присвоение аргументов
        ai = 0
        parsed = []
        for alts in conds:
            clause = []
            for col, op, ic in alts:
                if op in ("isnull", "notnull"):
                    clause.append((col, op, None))
                elif op == "between":
                    clause.append((col, op, (args[ai], args[ai + 1]))); ai += 2
                else:
                    clause.append((col, op, args[ai] if ai < len(args) else None)); ai += 1
            parsed.append(clause)

        def pred(r):
            for clause in parsed:      # parsed: список OR-групп из AND-условий
                if all(self._cmp_row(meta, r, c, o, v) for c, o, v in clause):
                    return True
            return False
        rows = self._select(meta, pred, caller)
        if order:
            mm = re.match(r"(.*?)(Asc|Desc)?$", order)
            col = self._prop_col(meta, mm.group(1))
            if col:
                rows.sort(key=lambda r: (r.get(col) is None, r.get(col)), reverse=(mm.group(2) == "Desc"))
        if limit:
            rows = rows[:limit]
        if verb in ("delete", "remove"):
            ids = [r.get(self._idcol(meta)) for r in rows]
            self._delete_rows(meta, ids, caller)
            return len(ids) if strip_generics(rt_full or "") in ("long", "int") else None
        if verb == "count":
            return len(rows)
        if verb == "exists":
            return len(rows) > 0
        return self._finish(meta, rt_full, rows, caller)

    def _cmp_row(self, meta, r, col, op, val):
        # встроенные поля: колонка может принадлежать embedded-типу; val может быть объектом TripId
        if isinstance(val, JObj) and col.startswith("@emb:"):
            for sf, sv in val.f.items():
                c2 = snake(sf)
                rv = r.get(c2)
                if isinstance(sv, JEnum):
                    sv = sv.ordinal
                if sv is not None and not self._cmp(rv, "=", sv):
                    return False
            return True
        if isinstance(val, JEnum):
            val = val.ordinal if not isinstance(r.get(col), str) else val.name
        if isinstance(val, JSet):
            val = list(val.values())
        return self._cmp(r.get(col), op, val)

    OPS = [("IsNotNull", "notnull"), ("NotNull", "notnull"), ("IsNull", "isnull"), ("Null", "isnull"),
           ("NotIn", "not in"), ("In", "in"), ("Containing", "contains"), ("Contains", "contains"),
           ("StartingWith", "starts"), ("EndingWith", "ends"), ("Like", "like"), ("GreaterThanEqual", ">="),
           ("LessThanEqual", "<="), ("GreaterThan", ">"), ("LessThan", "<"), ("After", ">"), ("Before", "<"),
           ("Between", "between"), ("Not", "!="), ("IsNot", "!="), ("Is", "="), ("Equals", "=")]

    def _parse_conds(self, meta, s):
        groups = []
        for orpart in re.split(r"Or(?=[A-Z])", s):
            alts = []
            for andpart in re.split(r"And(?=[A-Z])", orpart):
                if not andpart:
                    continue
                ic = False
                if andpart.endswith("IgnoreCase"):
                    andpart = andpart[:-10]; ic = True
                op = "="
                for suf, o in self.OPS:
                    if andpart.endswith(suf) and andpart != suf:
                        prop = andpart[:-len(suf)]
                        if self._prop_col(meta, prop):
                            op, andpart = o, prop
                            break
                col = self._prop_col(meta, andpart)
                if not col:
                    return None
                alts.append((col, op, ic))
            groups.append(alts)
        return groups

    def _prop_col(self, meta, prop):
        if not prop:
            return None
        lp = prop[0].lower() + prop[1:]
        for fname, col, ftype, f in meta.cols:
            if fname == lp:
                return col
        for fname, eci in meta.embedded:
            if fname == lp:
                return "@emb:" + fname
            if prop.startswith(fname[0].upper() + fname[1:]):
                rest = prop[len(fname):]
                for sf in self.it.p.all_fields(eci):
                    if sf.name == rest[0].lower() + rest[1:]:
                        return snake(sf.name)
        return None

    # --- @Query (native)
    def _native(self, meta, m, args, caller, rt_full):
        q = ann_str(m.annots["Query"], "value") or ann_str(m.annots["Query"])
        if not q:
            return UNK
        mm = re.search(r"where\s+(.*)$", q, re.I)
        conds = []
        if mm:
            for part in re.split(r"\s+and\s+", mm.group(1), flags=re.I):
                pm = re.match(r"\s*(\w+)\s*(=|in)\s*\?(\d+)", part, re.I)
                if not pm:
                    self.it.warn("native cond?")
                    return UNK
                conds.append((pm.group(1), pm.group(2).lower(), args[int(pm.group(3)) - 1]))
        rows = self._select(meta, lambda r: all(self._cmp(r.get(c), o, v) for c, o, v in conds), caller)
        return self._finish(meta, rt_full, rows, caller)


def hk_(x):
    try:
        hash(x)
        return x
    except TypeError:
        return id(x)


# переопределяем «обёртки»: _wrap возвращает кортеж, финализируем в call()
_orig_call = Repos.call


def _call(self, px, name, args, fr):
    r = _orig_call(self, px, name, args, fr)
    if isinstance(r, tuple) and r and r[0] == "ROWS":
        caller = fr.method if fr is not None else None
        return self._finish(px.meta, r[1], r[2], caller)
    return r


Repos.call = _call
