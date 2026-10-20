"""Одноразовый патч: ребра calls от библиотечных вызовов (name-match) и Lombok-toString с явными геттерами."""
import os

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def rd(n):
    return open(os.path.join(ROOT, n), encoding="utf-8").read()


def wr(n, s):
    open(os.path.join(ROOT, n), "w", encoding="utf-8", newline="\n").write(s)


# --- model: имена вызываемых методов
m = rd("model.py")
if "def called_names" not in m:
    m = m.replace('''class Project:
    def __init__(self, skeleton_path, root):''', '''def _walk_names(n, out, depth=0):
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
    def __init__(self, skeleton_path, root):''', 1)
    m = m.replace('"annots", "ret", "varargs")', '"annots", "ret", "varargs", "_called")')
    m = m.replace("        self.id = None\n        self.varargs", "        self.id = None\n        self._called = None\n        self.varargs")
    wr("model.py", m)

# --- config
c = rd("config.py")
if "LIB_NAME_MATCH_EDGES" not in c:
    c += '''
# Метод проекта, вызванный кодом библиотеки внутри метода F: в эталоне есть ребро F -> метод, если в исходнике F есть вызов
# с тем же именем (так получается getToken -> User#getPassword при authenticate).
LIB_NAME_MATCH_EDGES = True
# Lombok-toString при логировании/конкатенации вызывает явные геттеры класса.
LOMBOK_TOSTRING_CALLS_GETTERS = True
'''
    wr("config.py", c)

# --- interp
i = rd("interp.py")
if "def lib_invoke" not in i:
    i = i.replace('''    def call_virtual(self, obj, name, args, caller):''', '''    def lib_invoke(self, mi, this, args):
        """Вызов метода проекта из кода библиотеки (Spring Security, логирование/toString, коллекции) внутри метода проекта.
        В эталоне такое выполнение даёт ребро calls от ближайшего метода проекта в стеке, если в его исходнике есть вызов с тем же именем."""
        r = self.invoke(mi, this, args, None)
        if _cfg.LIB_NAME_MATCH_EDGES and self.stack and not mi.ctor:
            f = self.stack[-1].method
            if f is not None and mi.name in called_names(f):
                self.rec_call(f, mi)
        return r

    def call_virtual(self, obj, name, args, caller):''', 1)
    i = i.replace("import lib\n", "import lib\nimport config as _cfg\nfrom model import called_names\n", 1)
    wr("interp.py", i)

# --- lib
l = rd("lib.py")
l = l.replace('''    if isinstance(v, JObj):
        if it is not None:
            ok, r = it.call_virtual(v, "toString", [], None)
            if ok:
                return r if isinstance(r, str) else UNK_CH
        return lombok_str(it, v)''', '''    if isinstance(v, JObj):
        if it is not None:
            cands = [m for m in it.p.find_methods(v.cls, "toString") if not m.abstract and not m.params]
            if cands:
                r = it.lib_invoke(cands[0], v, [])
                return r if isinstance(r, str) else UNK_CH
        return lombok_str(it, v)''')
l = l.replace('''def lombok_str(it, o):
    return o.cls.name + "(" + ", ".join(f"{k}={to_str(it, v)}" for k, v in o.f.items()) + ")"''', '''_STR_DEPTH = [0]


def lombok_str(it, o):
    """@ToString/@Data: поля класса по порядку; для поля вызывается явный геттер, если он есть (он исполняется)."""
    ci = o.cls
    lombok = bool({"Data", "ToString", "Value"} & ci.annots.keys())
    if not lombok or it is None or not _cfg.LOMBOK_TOSTRING_CALLS_GETTERS or _STR_DEPTH[0] > 6:
        return ci.name + "(" + ", ".join(f"{k}={to_str(it, v)}" for k, v in o.f.items()) + ")"
    _STR_DEPTH[0] += 1
    try:
        parts = []
        for f in ci.fields.values():
            if f.static:
                continue
            val = o.f.get(f.name)
            cap = f.name[0].upper() + f.name[1:]
            for gname in ("get" + cap, "is" + cap):
                g = [m for m in it.p.find_methods(ci, gname) if not m.abstract and not m.params and not m.static]
                if g:
                    val = it.lib_invoke(g[0], o, [])
                    break
            parts.append(f"{f.name}={to_str(it, val)}")
        return ci.name + "(" + ", ".join(parts) + ")"
    finally:
        _STR_DEPTH[0] -= 1''')
l = l.replace('''    if isinstance(a, JObj):
        ok, r = it.call_virtual(a, "equals", [b], None)
        if ok:
            return r
        return lombok_equals(it, a, b)''', '''    if isinstance(a, JObj):
        cands = [m for m in it.p.find_methods(a.cls, "equals") if not m.abstract and len(m.params) == 1]
        if cands:
            return it.lib_invoke(cands[0], a, [b])
        return lombok_equals(it, a, b)''')
if "import config as _cfg" not in l:
    l = l.replace("from values import *\n", "from values import *\nimport config as _cfg\n", 1)
wr("lib.py", l)

# --- web.authenticate
w = rd("web.py")
w = w.replace('''        if isinstance(user, JObj):
            for nm in ("isAccountNonLocked", "isEnabled", "isAccountNonExpired", "getPassword", "isCredentialsNonExpired", "getAuthorities"):
                ok, r = it.call_virtual(user, nm, [], None)
            # особенность разметки эталона: ребро вызывающий метод -> User#getPassword
            ok_m = [m for m in it.p.find_methods(user.cls, "getPassword") if not m.abstract]
            if ok_m and fr.method is not None:
                it.rec_call(fr.method, ok_m[0])''', '''        if isinstance(user, JObj):
            for nm in ("isAccountNonLocked", "isEnabled", "isAccountNonExpired", "getPassword", "isCredentialsNonExpired", "getAuthorities"):
                g = [m for m in it.p.find_methods(user.cls, nm) if not m.abstract and not m.params]
                if g:
                    it.lib_invoke(g[0], user, [])''')
wr("web.py", w)
print("patched")
