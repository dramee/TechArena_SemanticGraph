"""Лёгкий парсер Java 8 (подмножество, достаточное для проекта Train Ticket).

Даёт AST методов с позициями вызовов (line, col) — они совпадают с call_site-вершинами скелета:
    - вызов метода: позиция имени метода;
    - new X(...): позиция слова `new`.
Только стандартная библиотека Python.
"""
import re

KEYWORDS = {
    "abstract", "assert", "boolean", "break", "byte", "case", "catch", "char", "class", "const", "continue",
    "default", "do", "double", "else", "enum", "extends", "final", "finally", "float", "for", "goto", "if",
    "implements", "import", "instanceof", "int", "interface", "long", "native", "new", "package", "private",
    "protected", "public", "return", "short", "static", "strictfp", "super", "switch", "synchronized", "this",
    "throw", "throws", "transient", "try", "void", "volatile", "while", "true", "false", "null",
}
PRIMS = {"boolean", "byte", "char", "short", "int", "long", "float", "double"}
MODIFIERS = {"public", "private", "protected", "static", "final", "abstract", "native", "synchronized",
             "transient", "volatile", "strictfp", "default"}

TOKEN_RE = re.compile(r"""
    (?P<ws>[ \t\r\f]+)
  | (?P<nl>\n)
  | (?P<lc>//[^\n]*)
  | (?P<bc>/\*.*?\*/)
  | (?P<str>"(?:\\.|[^"\\\n])*")
  | (?P<chr>'(?:\\.|[^'\\\n])+')
  | (?P<num>0[xX][0-9a-fA-F_]+[lL]?|\d[\d_]*\.?\d*(?:[eE][+-]?\d+)?[fFdDlL]?|\.\d[\d_]*(?:[eE][+-]?\d+)?[fFdD]?)
  | (?P<id>[A-Za-z_$][A-Za-z_$0-9]*)
  | (?P<op>>>>=|<<=|>>=|>>>|\.\.\.|->|::|\+\+|--|&&|\|\||==|!=|<=|>=|\+=|-=|\*=|/=|%=|&=|\|=|\^=|<<|>>|[{}()\[\];,.@=<>!~?:+\-*/&|^%])
""", re.X | re.S)


class Tok:
    __slots__ = ("k", "t", "line", "col")

    def __init__(self, k, t, line, col):
        self.k, self.t, self.line, self.col = k, t, line, col

    def __repr__(self):
        return f"{self.t}@{self.line}:{self.col}"


def tokenize(src):
    toks, line, ls, pos, n = [], 1, 0, 0, len(src)
    while pos < n:
        m = TOKEN_RE.match(src, pos)
        if not m:
            pos += 1
            continue
        kind = m.lastgroup
        text = m.group()
        col = pos - ls + 1
        if kind == "nl":
            line += 1; ls = m.end()
        elif kind == "bc":
            nls = text.count("\n")
            if nls:
                line += nls; ls = pos + text.rfind("\n") + 1
        elif kind in ("ws", "lc"):
            pass
        elif kind == "id":
            toks.append(Tok("kw" if text in KEYWORDS else "id", text, line, col))
        else:
            toks.append(Tok(kind, text, line, col))
        pos = m.end()
    toks.append(Tok("eof", "<eof>", line, 1))
    return toks


# --------------------------------------------------------------------------------------- AST
class Node:
    __slots__ = ()

    def __repr__(self):
        return f"{type(self).__name__}(" + ", ".join(f"{s}={getattr(self, s, None)!r}" for s in self.__slots__) + ")"


def _mk(name, fields):
    cls = type(name, (Node,), {"__slots__": tuple(fields.split())})
    def init(self, *a, **kw):
        for s, v in zip(cls.__slots__, a):
            setattr(self, s, v)
        for s in cls.__slots__[len(a):]:
            setattr(self, s, kw.get(s))
    cls.__init__ = init
    return cls


# выражения
Lit = _mk("Lit", "kind val")                      # kind: int,float,str,char,bool,null
Name = _mk("Name", "id line col")
FieldAcc = _mk("FieldAcc", "obj name line col")
Call = _mk("Call", "obj name args line col")      # obj None -> неявный this/статический импорт
New = _mk("New", "type args body line col outer")
NewArray = _mk("NewArray", "type dims init")
ArrayLit = _mk("ArrayLit", "elems")
Index = _mk("Index", "obj idx")
Unary = _mk("Unary", "op e")
Postfix = _mk("Postfix", "op e")
Binary = _mk("Binary", "op l r")
Assign = _mk("Assign", "op target value")
Cond = _mk("Cond", "c a b")
Cast = _mk("Cast", "type e")
InstanceOf = _mk("InstanceOf", "e type bind")
Lambda = _mk("Lambda", "params body")
MethodRef = _mk("MethodRef", "obj name")
This = _mk("This", "")
Super = _mk("Super", "")
ClassLit = _mk("ClassLit", "type")
TypeExpr = _mk("TypeExpr", "type")               # имя типа в позиции выражения (статическая цель)
# операторы
Block = _mk("Block", "stmts line")
LocalVar = _mk("LocalVar", "type decls line")     # decls: [(name, init)]
ExprStmt = _mk("ExprStmt", "e line")
If = _mk("If", "c then els line")
While = _mk("While", "c body line")
DoWhile = _mk("DoWhile", "body c line")
For = _mk("For", "init c update body line")
ForEach = _mk("ForEach", "type name iter body line")
Return = _mk("Return", "e line")
Throw = _mk("Throw", "e line")
Break = _mk("Break", "label")
Continue = _mk("Continue", "label")
Try = _mk("Try", "res body catches fin line")     # catches: [(types, name, block)]
Switch = _mk("Switch", "e cases line")            # cases: [(labels|None, [stmts])]
Sync = _mk("Sync", "e body")
Labeled = _mk("Labeled", "label stmt")
LocalClass = _mk("LocalClass", "decl")
Assert = _mk("Assert", "c m")
Empty = _mk("Empty", "")
# декларации
Param = _mk("Param", "type name annots varargs")
Annot = _mk("Annot", "name args")                 # args — исходный текст внутри скобок
MethodDecl = _mk("MethodDecl", "name params ret body mods annots line end cls ctor tparams start")
FieldDecl = _mk("FieldDecl", "type name init mods annots line cls")
ClassDecl = _mk("ClassDecl", "kind name mods annots ext impls fields methods inits inner enums line end outer anon fqn tparams")
EnumConst = _mk("EnumConst", "name args body line")


class ParseError(Exception):
    pass


class Parser:
    def __init__(self, src, path=""):
        self.toks = tokenize(src)
        self.i = 0
        self.path = path
        self.pkg = ""
        self.imports = []
        self.anon_counter = {}
        self.src = src

    # ---------------------------------------------------------------- utils
    @property
    def tok(self):
        return self.toks[self.i]

    def peek(self, k=1):
        j = self.i + k
        return self.toks[j] if j < len(self.toks) else self.toks[-1]

    def at(self, t):
        return self.toks[self.i].t == t and self.toks[self.i].k in ("op", "kw", "id")

    def at_op(self, t):
        x = self.toks[self.i]
        return x.k == "op" and x.t == t

    def accept(self, t):
        x = self.toks[self.i]
        if x.t == t and x.k in ("op", "kw", "id"):
            self.i += 1
            return True
        return False

    def expect(self, t):
        x = self.toks[self.i]
        if x.t != t or x.k not in ("op", "kw", "id"):
            raise ParseError(f"{self.path}:{x.line}:{x.col}: ожидалось {t!r}, найдено {x.t!r}")
        self.i += 1
        return x

    def ident(self):
        x = self.toks[self.i]
        if x.k != "id":
            raise ParseError(f"{self.path}:{x.line}:{x.col}: ожидался идентификатор, найдено {x.t!r}")
        self.i += 1
        return x.t

    def split_gt(self):
        """Разбить составной токен '>>', '>>>', '>=', '>>=' перед закрытием списка типовых аргументов."""
        x = self.toks[self.i]
        if x.k == "op" and x.t.startswith(">") and len(x.t) > 1:
            rest = Tok("op", x.t[1:], x.line, x.col + 1)
            x.t = ">"
            self.toks.insert(self.i + 1, rest)

    def skip_balanced(self, open_, close):
        depth = 0
        while True:
            x = self.tok
            if x.k == "eof":
                raise ParseError("unbalanced " + open_)
            if x.k == "op":
                if x.t == open_:
                    depth += 1
                elif x.t == close:
                    depth -= 1
                    if depth == 0:
                        self.i += 1
                        return
            self.i += 1

    # ---------------------------------------------------------------- types
    def parse_type(self):
        """Тип: примитив/имя с точками, <...>, [] -> строка (без пробелов)."""
        x = self.tok
        parts = []
        while self.at_op("@"):
            self.parse_annotation()
        x = self.tok
        if x.k == "kw" and x.t in PRIMS:
            self.i += 1
            parts.append(x.t)
        elif x.k == "op" and x.t == "?":
            self.i += 1
            parts.append("?")
            if self.accept("extends") or self.accept("super"):
                parts.append(" " + self.parse_type())
            return "".join(parts)
        elif x.k == "id":
            parts.append(self.ident())
            while True:
                if self.at_op("<"):
                    parts.append(self.parse_type_args())
                if self.at_op(".") and self.peek().k == "id":
                    self.i += 1
                    parts.append("." + self.ident())
                else:
                    break
        elif x.k == "kw" and x.t == "void":
            self.i += 1
            return "void"
        else:
            raise ParseError(f"{self.path}:{x.line}:{x.col}: ожидался тип, найдено {x.t!r}")
        while self.at_op("[") and self.peek().t == "]":
            self.i += 2
            parts.append("[]")
        return "".join(parts)

    def parse_type_args(self):
        self.expect("<")
        out = ["<"]
        if self.at_op(">"):
            self.i += 1
            return "<>"
        while True:
            out.append(self.parse_type())
            if self.accept(","):
                out.append(",")
                continue
            break
        self.split_gt()
        self.expect(">")
        out.append(">")
        return "".join(out)

    def try_type(self):
        """Спекулятивный разбор типа; при неудаче откат и None."""
        save = self.i
        saved_toks = None
        try:
            return self.parse_type()
        except ParseError:
            self.i = save
            return None

    # ---------------------------------------------------------------- annotations
    def parse_annotation(self):
        self.expect("@")
        name = self.ident()
        while self.at_op(".") and self.peek().k == "id":
            self.i += 1
            name += "." + self.ident()
        args = ""
        if self.at_op("("):
            start = self.i
            self.skip_balanced("(", ")")
            args = " ".join(t.t for t in self.toks[start:self.i])
        return Annot(name, args)

    def parse_modifiers(self):
        mods, annots = set(), []
        while True:
            x = self.tok
            if x.k == "op" and x.t == "@" and not (self.peek().t == "interface"):
                annots.append(self.parse_annotation())
            elif x.k == "kw" and x.t in MODIFIERS:
                if x.t == "default" and self.peek().t in (":", "->"):
                    break
                mods.add(x.t)
                self.i += 1
            else:
                break
        return mods, annots

    # ---------------------------------------------------------------- compilation unit
    def parse_unit(self):
        types = []
        if self.at("package"):
            self.i += 1
            self.pkg = self.qualified()
            self.expect(";")
        while self.at("import"):
            self.i += 1
            static = self.accept("static")
            q = self.qualified(allow_star=True)
            self.expect(";")
            self.imports.append((static, q))
        while self.tok.k != "eof":
            if self.accept(";"):
                continue
            mods, annots = self.parse_modifiers()
            types.append(self.parse_class(mods, annots, None))
        return types

    def qualified(self, allow_star=False):
        parts = [self.ident()]
        while self.at_op("."):
            self.i += 1
            if allow_star and self.at_op("*"):
                self.i += 1
                parts.append("*")
                break
            parts.append(self.ident())
        return ".".join(parts)

    # ---------------------------------------------------------------- declarations
    def parse_class(self, mods, annots, outer):
        x = self.tok
        if x.t == "@" and self.peek().t == "interface":
            self.i += 2
            kind = "annotation"
        elif x.t in ("class", "interface", "enum"):
            kind = x.t
            self.i += 1
        else:
            raise ParseError(f"{self.path}:{x.line}:{x.col}: ожидалось class/interface/enum, найдено {x.t!r}")
        line = x.line
        name = self.ident()
        c = ClassDecl(kind, name, mods, annots, None, [], [], [], [], [], [], line, line, outer, False, None)
        if outer is None:
            c.fqn = (self.pkg + "." if self.pkg else "") + name
        else:
            c.fqn = outer.fqn + "$" + name
        if self.at_op("<"):
            c.tparams = self.parse_type_params()
        if self.accept("extends"):
            if kind == "interface":
                c.impls.append(self.parse_type())
                while self.accept(","):
                    c.impls.append(self.parse_type())
            else:
                c.ext = self.parse_type()
        if self.accept("implements"):
            c.impls.append(self.parse_type())
            while self.accept(","):
                c.impls.append(self.parse_type())
        self.parse_class_body(c)
        return c

    def parse_type_params(self):
        """<T extends X, U> -> ['T', 'U'] (имена параметров верхнего уровня)."""
        self.expect("<")
        depth = 1
        names = []
        expect_name = True
        while depth:
            x = self.tok
            if x.k == "eof":
                raise ParseError("type params")
            if x.k == "op":
                if x.t == "<":
                    depth += 1
                elif x.t == ">":
                    depth -= 1
                elif x.t == ">>":
                    depth -= 2
                elif x.t == ">>>":
                    depth -= 3
                elif x.t == "," and depth == 1:
                    expect_name = True
            elif x.k == "id" and expect_name and depth == 1:
                names.append(x.t)
                expect_name = False
            self.i += 1
        return names

    def parse_class_body(self, c):
        self.expect("{")
        if c.kind == "enum":
            self.parse_enum_constants(c)
        while not self.at_op("}"):
            if self.tok.k == "eof":
                raise ParseError(f"{self.path}: EOF in class {c.name}")
            self.parse_member(c)
        c.end = self.tok.line
        self.expect("}")

    def parse_enum_constants(self, c):
        while self.tok.k == "id" or self.at_op("@"):
            while self.at_op("@"):
                self.parse_annotation()
            line = self.tok.line
            name = self.ident()
            args = []
            if self.at_op("("):
                args = self.parse_args()
            body = None
            if self.at_op("{"):
                body = ClassDecl("class", c.name + "$" + name, set(), [], c.name, [], [], [], [], [], [], line, line, c, True, c.fqn + "$" + name)
                self.parse_class_body(body)
            c.enums.append(EnumConst(name, args, body, line))
            if not self.accept(","):
                break
        if not self.accept(";"):
            # enum без членов
            pass

    def parse_member(self, c):
        if self.accept(";"):
            return
        if self.at_op("{"):
            blk = self.parse_block()
            c.inits.append((False, blk))
            return
        if self.at("static") and self.peek().t == "{":
            self.i += 1
            blk = self.parse_block()
            c.inits.append((True, blk))
            return
        start_line = self.tok.line
        mods, annots = self.parse_modifiers()
        x = self.tok
        if x.t in ("class", "interface", "enum") or (x.t == "@" and self.peek().t == "interface"):
            inner = self.parse_class(mods, annots, c)
            c.inner.append(inner)
            return
        tparams = None
        if self.at_op("<"):
            self.parse_type_params()
            tparams = True
        line = self.tok.line
        # конструктор
        if self.tok.k == "id" and self.tok.t == c.name and self.peek().t == "(":
            self.i += 1
            params = self.parse_params()
            if self.accept("throws"):
                self.parse_type()
                while self.accept(","):
                    self.parse_type()
            body = self.parse_block()
            m = MethodDecl("<init>", params, None, body, mods, annots, line, body_end(body, self), c, True, tparams, start_line)
            c.methods.append(m)
            return
        rtype = self.parse_type()
        nm_tok = self.tok
        name = self.ident()
        if self.at_op("("):
            params = self.parse_params()
            while self.at_op("[") and self.peek().t == "]":
                self.i += 2
            if self.accept("throws"):
                self.parse_type()
                while self.accept(","):
                    self.parse_type()
            body = None
            if self.at_op("{"):
                body = self.parse_block()
                end = self.toks[self.i - 1].line
            else:
                if self.accept("default"):      # аннотационное значение
                    while not self.at_op(";"):
                        self.i += 1
                self.expect(";")
                end = self.toks[self.i - 1].line
            m = MethodDecl(name, params, rtype, body, mods, annots, nm_tok.line, end, c, False, tparams, start_line)
            c.methods.append(m)
            return
        # поля
        while True:
            ftype = rtype
            while self.at_op("[") and self.peek().t == "]":
                self.i += 2
                ftype += "[]"
            init = None
            if self.accept("="):
                init = self.parse_var_init()
            c.fields.append(FieldDecl(ftype, name, init, mods, annots, nm_tok.line, c))
            if self.accept(","):
                nm_tok = self.tok
                name = self.ident()
                continue
            break
        self.expect(";")

    def parse_params(self):
        self.expect("(")
        params = []
        while not self.at_op(")"):
            mods, annots = self.parse_modifiers()
            t = self.parse_type()
            varargs = False
            if self.accept("..."):
                varargs = True
            if self.at("this"):
                self.i += 1
            else:
                nm = self.ident()
                while self.at_op("[") and self.peek().t == "]":
                    self.i += 2
                    t += "[]"
                params.append(Param(t, nm, annots, varargs))
            if not self.accept(","):
                break
        self.expect(")")
        return params

    # ---------------------------------------------------------------- statements
    def parse_block(self):
        line = self.tok.line
        self.expect("{")
        stmts = []
        while not self.at_op("}"):
            if self.tok.k == "eof":
                raise ParseError(f"{self.path}: EOF in block")
            stmts.append(self.parse_stmt())
        self.expect("}")
        return Block(stmts, line)

    def parse_var_init(self):
        if self.at_op("{"):
            return self.parse_array_init()
        return self.parse_expr()

    def parse_array_init(self):
        self.expect("{")
        elems = []
        while not self.at_op("}"):
            elems.append(self.parse_var_init())
            if not self.accept(","):
                break
        self.expect("}")
        return ArrayLit(elems)

    def is_local_decl(self):
        """Начинается ли оператор с объявления локальной переменной: Type ident (= | ; | , | : | [)."""
        x = self.tok
        if x.k == "kw" and x.t in PRIMS:
            return True
        if x.k == "op" and x.t == "@":
            return True
        if x.k == "kw" and x.t == "final":
            return True
        if x.k != "id":
            return False
        save = self.i
        try:
            t = self.parse_type()
            ok = self.tok.k == "id" and self.peek().t in ("=", ";", ",", ":", "[")
            return ok
        except ParseError:
            return False
        finally:
            self.i = save

    def parse_stmt(self):
        x = self.tok
        line = x.line
        if x.k == "op":
            if x.t == "{":
                return self.parse_block()
            if x.t == ";":
                self.i += 1
                return Empty()
        if x.k == "kw":
            t = x.t
            if t == "if":
                self.i += 1
                self.expect("(")
                c = self.parse_expr()
                self.expect(")")
                th = self.parse_stmt()
                el = None
                if self.accept("else"):
                    el = self.parse_stmt()
                return If(c, th, el, line)
            if t == "while":
                self.i += 1
                self.expect("(")
                c = self.parse_expr()
                self.expect(")")
                return While(c, self.parse_stmt(), line)
            if t == "do":
                self.i += 1
                body = self.parse_stmt()
                self.expect("while")
                self.expect("(")
                c = self.parse_expr()
                self.expect(")")
                self.expect(";")
                return DoWhile(body, c, line)
            if t == "for":
                return self.parse_for()
            if t == "return":
                self.i += 1
                e = None
                if not self.at_op(";"):
                    e = self.parse_expr()
                self.expect(";")
                return Return(e, line)
            if t == "throw":
                self.i += 1
                e = self.parse_expr()
                self.expect(";")
                return Throw(e, line)
            if t == "break":
                self.i += 1
                lab = None
                if self.tok.k == "id":
                    lab = self.ident()
                self.expect(";")
                return Break(lab)
            if t == "continue":
                self.i += 1
                lab = None
                if self.tok.k == "id":
                    lab = self.ident()
                self.expect(";")
                return Continue(lab)
            if t == "try":
                return self.parse_try()
            if t == "switch":
                return self.parse_switch()
            if t == "synchronized":
                self.i += 1
                self.expect("(")
                e = self.parse_expr()
                self.expect(")")
                return Sync(e, self.parse_block())
            if t == "assert":
                self.i += 1
                c = self.parse_expr()
                m = None
                if self.accept(":"):
                    m = self.parse_expr()
                self.expect(";")
                return Assert(c, m)
            if t in ("class", "interface", "enum", "abstract", "static") or (t == "final" and self.peek().t == "class"):
                mods, annots = self.parse_modifiers()
                if self.tok.t in ("class", "interface", "enum"):
                    return LocalClass(self.parse_class(mods, annots, None))
        if x.k == "id" and self.peek().t == ":" and self.peek().k == "op":
            lab = self.ident()
            self.i += 1
            return Labeled(lab, self.parse_stmt())
        if self.is_local_decl():
            return self.parse_local_var(line)
        e = self.parse_expr()
        self.expect(";")
        return ExprStmt(e, line)

    def parse_local_var(self, line):
        self.parse_modifiers()
        t = self.parse_type()
        decls = []
        while True:
            nm = self.ident()
            tt = t
            while self.at_op("[") and self.peek().t == "]":
                self.i += 2
            init = None
            if self.accept("="):
                init = self.parse_var_init()
            decls.append((nm, init))
            if not self.accept(","):
                break
        self.expect(";")
        return LocalVar(t, decls, line)

    def parse_for(self):
        line = self.tok.line
        self.expect("for")
        self.expect("(")
        # for-each?
        save = self.i
        if self.is_local_decl():
            self.parse_modifiers()
            t = self.parse_type()
            nm = self.ident()
            if self.accept(":"):
                it = self.parse_expr()
                self.expect(")")
                return ForEach(t, nm, it, self.parse_stmt(), line)
            self.i = save
        init = []
        if not self.at_op(";"):
            if self.is_local_decl():
                self.parse_modifiers()
                t = self.parse_type()
                decls = []
                while True:
                    nm = self.ident()
                    ini = None
                    if self.accept("="):
                        ini = self.parse_var_init()
                    decls.append((nm, ini))
                    if not self.accept(","):
                        break
                init.append(LocalVar(t, decls, line))
            else:
                init.append(ExprStmt(self.parse_expr(), line))
                while self.accept(","):
                    init.append(ExprStmt(self.parse_expr(), line))
        self.expect(";")
        c = None
        if not self.at_op(";"):
            c = self.parse_expr()
        self.expect(";")
        upd = []
        if not self.at_op(")"):
            upd.append(self.parse_expr())
            while self.accept(","):
                upd.append(self.parse_expr())
        self.expect(")")
        return For(init, c, upd, self.parse_stmt(), line)

    def parse_try(self):
        line = self.tok.line
        self.expect("try")
        res = []
        if self.accept("("):
            while not self.at_op(")"):
                if self.is_local_decl():
                    self.parse_modifiers()
                    t = self.parse_type()
                    nm = self.ident()
                    self.expect("=")
                    res.append((nm, self.parse_expr()))
                else:
                    res.append((None, self.parse_expr()))
                if not self.accept(";"):
                    break
            self.expect(")")
        body = self.parse_block()
        catches = []
        while self.at("catch"):
            self.i += 1
            self.expect("(")
            self.parse_modifiers()
            types = [self.parse_type()]
            while self.accept("|"):
                types.append(self.parse_type())
            nm = self.ident()
            self.expect(")")
            catches.append((types, nm, self.parse_block()))
        fin = None
        if self.accept("finally"):
            fin = self.parse_block()
        return Try(res, body, catches, fin, line)

    def parse_switch(self):
        line = self.tok.line
        self.expect("switch")
        self.expect("(")
        e = self.parse_expr()
        self.expect(")")
        self.expect("{")
        cases = []
        while not self.at_op("}"):
            labels = []
            if self.accept("default"):
                labels = None
            else:
                self.expect("case")
                labels.append(self.parse_ternary())
                while self.accept(","):
                    labels.append(self.parse_ternary())
            if self.accept("->"):
                if self.at_op("{"):
                    stmts = [self.parse_block()]
                elif self.at("throw"):
                    stmts = [self.parse_stmt()]
                else:
                    ex = self.parse_expr()
                    self.expect(";")
                    stmts = [ExprStmt(ex, line), Break(None)]
            else:
                self.expect(":")
                stmts = []
                while not (self.at("case") or self.at("default") or self.at_op("}")):
                    stmts.append(self.parse_stmt())
            cases.append((labels, stmts))
        self.expect("}")
        return Switch(e, cases, line)

    # ---------------------------------------------------------------- expressions
    def parse_expr(self):
        return self.parse_assign()

    ASSIGN_OPS = {"=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>=", ">>>="}

    def parse_assign(self):
        # лямбда
        lam = self.try_lambda()
        if lam is not None:
            return lam
        left = self.parse_ternary()
        x = self.tok
        if x.k == "op" and x.t in self.ASSIGN_OPS:
            self.i += 1
            right = self.parse_assign()
            return Assign(x.t, left, right)
        return left

    def try_lambda(self):
        x = self.tok
        if x.k == "id" and self.peek().t == "->" and self.peek().k == "op":
            self.i += 2
            return Lambda([x.t], self.parse_lambda_body())
        if x.k == "op" and x.t == "(":
            # найти закрывающую скобку и проверить '->'
            depth, j = 0, self.i
            while True:
                t = self.toks[j]
                if t.k == "eof":
                    return None
                if t.k == "op":
                    if t.t == "(":
                        depth += 1
                    elif t.t == ")":
                        depth -= 1
                        if depth == 0:
                            break
                j += 1
            nxt = self.toks[j + 1]
            if nxt.k == "op" and nxt.t == "->":
                self.i += 1
                params = []
                while not self.at_op(")"):
                    # (a, b) или (Type a, Type b)
                    if self.tok.k == "id" and self.peek().t in (",", ")"):
                        params.append(self.ident())
                    else:
                        self.parse_modifiers()
                        self.parse_type()
                        params.append(self.ident())
                    if not self.accept(","):
                        break
                self.expect(")")
                self.expect("->")
                return Lambda(params, self.parse_lambda_body())
        return None

    def parse_lambda_body(self):
        if self.at_op("{"):
            return self.parse_block()
        return self.parse_expr()

    def parse_ternary(self):
        c = self.parse_binary(0)
        if self.at_op("?"):
            self.i += 1
            a = self.parse_ternary_branch()
            self.expect(":")
            b = self.parse_ternary_branch()
            return Cond(c, a, b)
        return c

    def parse_ternary_branch(self):
        lam = self.try_lambda()
        if lam is not None:
            return lam
        return self.parse_ternary()

    PREC = [("||",), ("&&",), ("|",), ("^",), ("&",), ("==", "!="), ("<", ">", "<=", ">=", "instanceof"),
            ("<<", ">>", ">>>"), ("+", "-"), ("*", "/", "%")]

    def parse_binary(self, level):
        if level >= len(self.PREC):
            return self.parse_unary()
        left = self.parse_binary(level + 1)
        ops = self.PREC[level]
        while True:
            x = self.tok
            if (x.k == "op" or x.k == "kw") and x.t in ops:
                if x.t == "instanceof":
                    self.i += 1
                    self.accept("final")
                    t = self.parse_type()
                    bind = None
                    if self.tok.k == "id":
                        bind = self.ident()
                    left = InstanceOf(left, t, bind)
                    continue
                # '>' может быть началом '>>' с пробелами — токенайзер уже склеил подряд идущие
                self.i += 1
                right = self.parse_binary(level + 1)
                left = Binary(x.t, left, right)
            else:
                break
        return left

    def parse_unary(self):
        x = self.tok
        if x.k == "op":
            if x.t in ("+", "-", "!", "~"):
                self.i += 1
                e = self.parse_unary()
                if x.t == "-" and isinstance(e, Lit) and e.kind in ("int", "float"):
                    return Lit(e.kind, -e.val)
                return Unary(x.t, e)
            if x.t in ("++", "--"):
                self.i += 1
                return Unary(x.t, self.parse_unary())
            if x.t == "(":
                c = self.try_cast()
                if c is not None:
                    return c
        return self.parse_postfix()

    def try_cast(self):
        save = self.i
        self.i += 1
        x = self.tok
        try:
            if x.k == "kw" and x.t in PRIMS:
                t = self.parse_type()
                if self.at_op(")"):
                    self.i += 1
                    return Cast(t, self.parse_unary())
                self.i = save
                return None
            if x.k == "id":
                t = self.parse_type()
                while self.accept("&"):
                    self.parse_type()
                if self.at_op(")"):
                    nx = self.peek()
                    if nx.k in ("id", "str", "chr", "num") or (nx.k == "kw" and nx.t in ("new", "this", "super", "true", "false", "null")) \
                            or (nx.k == "op" and nx.t in ("(", "!", "~")):
                        self.i += 1
                        return Cast(t, self.parse_unary())
        except ParseError:
            pass
        self.i = save
        return None

    def parse_args(self):
        self.expect("(")
        args = []
        while not self.at_op(")"):
            args.append(self.parse_expr())
            if not self.accept(","):
                break
        self.expect(")")
        return args

    def parse_postfix(self):
        e = self.parse_primary()
        while True:
            x = self.tok
            if x.k == "op":
                if x.t == ".":
                    self.i += 1
                    if self.at_op("<"):               # явные типовые аргументы
                        self.parse_type_args()
                    y = self.tok
                    if y.k == "kw" and y.t == "new":  # outer.new Inner()
                        e = self.parse_new(outer=e)
                        continue
                    if y.k == "kw" and y.t == "class":
                        self.i += 1
                        e = ClassLit(e)
                        continue
                    if y.k == "kw" and y.t == "this":
                        self.i += 1
                        e = This()
                        continue
                    if y.k == "kw" and y.t == "super":
                        self.i += 1
                        e = Super()
                        continue
                    nm = self.ident()
                    if self.at_op("("):
                        args = self.parse_args()
                        e = Call(e, nm, args, y.line, y.col)
                    else:
                        e = FieldAcc(e, nm, y.line, y.col)
                    continue
                if x.t == "[":
                    self.i += 1
                    idx = self.parse_expr()
                    self.expect("]")
                    e = Index(e, idx)
                    continue
                if x.t in ("++", "--"):
                    self.i += 1
                    e = Postfix(x.t, e)
                    continue
                if x.t == "::":
                    self.i += 1
                    if self.accept("new"):
                        e = MethodRef(e, "new")
                    else:
                        e = MethodRef(e, self.ident())
                    continue
            break
        return e

    def parse_new(self, outer=None):
        x = self.expect("new")
        self.parse_modifiers()
        if self.tok.k == "kw" and self.tok.t in PRIMS:
            t = self.parse_type_no_dims()
        else:
            t = self.parse_type_no_dims()
        if self.at_op("["):
            dims = []
            while self.at_op("["):
                self.i += 1
                if self.at_op("]"):
                    self.i += 1
                    dims.append(None)
                else:
                    dims.append(self.parse_expr())
                    self.expect("]")
            init = None
            if self.at_op("{"):
                init = self.parse_array_init()
            return NewArray(t, dims, init)
        args = self.parse_args()
        body = None
        if self.at_op("{"):
            self.anon_counter[None] = self.anon_counter.get(None, 0) + 1
            body = ClassDecl("class", "", set(), [], t, [], [], [], [], [], [], x.line, x.line, None, True, None)
            self.parse_class_body(body)
        return New(t, args, body, x.line, x.col, outer)

    def parse_type_no_dims(self):
        parts = []
        x = self.tok
        if x.k == "kw" and x.t in PRIMS:
            self.i += 1
            return x.t
        parts.append(self.ident())
        while True:
            if self.at_op("<"):
                parts.append(self.parse_type_args())
            if self.at_op(".") and self.peek().k == "id":
                self.i += 1
                parts.append("." + self.ident())
            else:
                break
        return "".join(parts)

    def parse_primary(self):
        x = self.tok
        k = x.k
        if k == "num":
            self.i += 1
            return self.num_lit(x.t)
        if k == "str":
            self.i += 1
            return Lit("str", unescape(x.t[1:-1]))
        if k == "chr":
            self.i += 1
            return Lit("char", unescape(x.t[1:-1]))
        if k == "kw":
            t = x.t
            if t == "true" or t == "false":
                self.i += 1
                return Lit("bool", t == "true")
            if t == "null":
                self.i += 1
                return Lit("null", None)
            if t == "this":
                self.i += 1
                if self.at_op("("):
                    args = self.parse_args()
                    return Call(None, "this", args, x.line, x.col)
                return This()
            if t == "super":
                self.i += 1
                if self.at_op("("):
                    args = self.parse_args()
                    return Call(None, "super", args, x.line, x.col)
                return Super()
            if t == "new":
                return self.parse_new()
            if t in PRIMS or t == "void":
                # int.class, int[].class
                ty = self.parse_type()
                if self.at_op(".") and self.peek().t == "class":
                    self.i += 2
                    return ClassLit(ty)
                if self.at_op("::"):
                    return TypeExpr(ty)
                raise ParseError(f"{self.path}:{x.line}:{x.col}: неожиданный {t}")
            if t == "switch":
                s = self.parse_switch()
                return s
        if k == "op":
            if x.t == "(":
                self.i += 1
                e = self.parse_expr()
                self.expect(")")
                return e
            if x.t == "{":
                return self.parse_array_init()
        if k == "id":
            self.i += 1
            if self.at_op("("):
                args = self.parse_args()
                return Call(None, x.t, args, x.line, x.col)
            # Type[]::new / Type[].class / generic type method ref
            if self.at_op("[") and self.peek().t == "]":
                save = self.i
                self.i -= 1
                ty = self.parse_type()
                if self.at_op(".") and self.peek().t == "class":
                    self.i += 2
                    return ClassLit(ty)
                if self.at_op("::"):
                    return TypeExpr(ty)
                self.i = save
            if self.at_op("<"):
                # Type<Args>::method
                save = self.i
                try:
                    self.parse_type_args()
                    if self.at_op("::"):
                        return Name(x.t, x.line, x.col)
                except ParseError:
                    pass
                self.i = save
            return Name(x.t, x.line, x.col)
        raise ParseError(f"{self.path}:{x.line}:{x.col}: неожиданный токен {x.t!r}")

    @staticmethod
    def num_lit(t):
        s = t.replace("_", "")
        low = s.lower()
        try:
            if low.startswith("0x"):
                return Lit("int", int(low.rstrip("l"), 16))
            if low.endswith("l") and "." not in low:
                return Lit("int", int(low[:-1]))
            if low.endswith("f") or low.endswith("d") or "." in low or "e" in low:
                return Lit("float", float(low.rstrip("fd")))
            return Lit("int", int(low, 8) if low.startswith("0") and len(low) > 1 and low.isdigit() else int(low))
        except ValueError:
            return Lit("float", 0.0)


def body_end(body, p):
    return p.toks[p.i - 1].line


ESC = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "0": "\0", "\\": "\\", "'": "'", '"': '"'}


def unescape(s):
    if "\\" not in s:
        return s
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            d = s[i + 1]
            if d == "u" and i + 5 < len(s) + 1:
                try:
                    out.append(chr(int(s[i + 2:i + 6], 16)))
                    i += 6
                    continue
                except ValueError:
                    pass
            out.append(ESC.get(d, d))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def parse_file(path, text=None):
    if text is None:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    p = Parser(text, path)
    types = p.parse_unit()
    return p, types
