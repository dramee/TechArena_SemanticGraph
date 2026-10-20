"""Одноразовый патч: клиентский Jackson (внутри метода проекта) исполняет явные сеттеры/геттеры (флаг config.TRACE_CLIENT_JSON)."""
import os

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def rd(n):
    return open(os.path.join(ROOT, n), encoding="utf-8").read()


def wr(n, s):
    open(os.path.join(ROOT, n), "w", encoding="utf-8", newline="\n").write(s)


w = rd("web.py")

# 1. convert: запомнить, трассируем ли разбор
w = w.replace('''        it = self.it
        if v is UNK or v is None or tname is None:
            return v
        if not traced:''', '''        it = self.it
        if v is UNK or v is None or tname is None:
            return v
        self._tracing = traced
        if not traced:''')
w = w.replace('''        self.enforce_auth = True
        self.sec = {}''', '''        self.enforce_auth = True
        self._tracing = False
        self.sec = {}''')

# 2. _conv: явные сеттеры
old = '''        for f in p.all_fields(ci):
            if f.name in src:
                obj.f[f.name] = self._conv(src[f.name], f.type, f.cls, None, sub if tp else {})
        return obj'''
new = '''        for f in p.all_fields(ci):
            if f.name in src:
                val = self._conv(src[f.name], f.type, f.cls, None, sub if tp else {})
                setter = None
                if self._tracing:
                    cap = f.name[0].upper() + f.name[1:]
                    cs = [m for m in p.find_methods(ci, "set" + cap) if not m.abstract and len(m.params) == 1 and not m.static]
                    setter = cs[0] if cs else None
                if setter is not None:
                    it.lib_invoke(setter, obj, [val])         # Jackson вызывает явный сеттер
                else:
                    obj.f[f.name] = val
        return obj'''
assert old in w
w = w.replace(old, new)

# 3. to_raw: явные геттеры через lib_invoke
w = w.replace('''                                try:
                                    r = it.invoke(mi, x, [], None) if False else self._exec_getter(mi, x)
                                except Exception:
                                    r = None''', '''                                try:
                                    it.lib_invoke(mi, x, [])
                                except (JavaThrow, TypeError, AttributeError, KeyError, IndexError, ValueError):
                                    pass''')
wr("web.py", w)

# 4. ObjectMapper.writeValueAsString: геттеры при трассировке
l = rd("lib.py")
old = '''        if n == "writeValueAsString":
            s = JsonStr("{json}")
            s.obj = a[0]
            return s'''
new = '''        if n == "writeValueAsString":
            s = JsonStr("{json}")
            s.obj = a[0]
            if _cfg.TRACE_CLIENT_JSON:
                it.web.to_raw(a[0], traced=True)
            return s'''
assert old in l
l = l.replace(old, new)
wr("lib.py", l)
print("patched")
