//! Лёгкий разборщик Java 8 (подмножество, достаточное для Train Ticket).
//!
//! Строит AST методов с позициями вызовов (строка, колонка), которые
//! совпадают с вершинами `call_site` скелета: у вызова метода это позиция
//! имени метода, у `new X(...)` — позиция слова `new`.

use std::cell::Cell;
use std::collections::HashSet;
use std::fmt;
use std::rc::Rc;

/// Ключевые слова Java.
const KEYWORDS: &[&str] = &[
    "abstract", "assert", "boolean", "break", "byte", "case", "catch", "char", "class",
    "const", "continue", "default", "do", "double", "else", "enum", "extends", "final",
    "finally", "float", "for", "goto", "if", "implements", "import", "instanceof", "int",
    "interface", "long", "native", "new", "package", "private", "protected", "public",
    "return", "short", "static", "strictfp", "super", "switch", "synchronized", "this",
    "throw", "throws", "transient", "try", "void", "volatile", "while", "true", "false",
    "null",
];

/// Примитивные типы Java.
pub const PRIMS: &[&str] = &[
    "boolean", "byte", "char", "short", "int", "long", "float", "double",
];

/// Модификаторы объявлений.
const MODIFIERS: &[&str] = &[
    "public",
    "private",
    "protected",
    "static",
    "final",
    "abstract",
    "native",
    "synchronized",
    "transient",
    "volatile",
    "strictfp",
    "default",
];

/// Операторы в порядке проверки (как в альтернативах регулярного выражения).
const OPERATORS: &[&str] = &[
    ">>>=", "<<=", ">>=", ">>>", "...", "->", "::", "++", "--", "&&", "||", "==", "!=", "<=",
    ">=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<", ">>",
];

/// Односимвольные операторы.
const SINGLE_OPS: &str = "{}()[];,.@=<>!~?:+-*/&|^%";

/// Проверяет, что строка — примитивный тип Java.
pub fn is_prim(t: &str) -> bool {
    PRIMS.contains(&t)
}

/// Вид лексемы.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum TokKind {
    /// Ключевое слово.
    Kw,
    /// Идентификатор.
    Id,
    /// Оператор.
    Op,
    /// Строковый литерал.
    Str,
    /// Символьный литерал.
    Chr,
    /// Число.
    Num,
    /// Конец файла.
    Eof,
}

/// Лексема: вид, текст и позиция в исходнике.
#[derive(Clone, Debug)]
pub struct Tok {
    /// Вид лексемы.
    pub k: TokKind,
    /// Текст лексемы.
    pub t: String,
    /// Строка (с 1).
    pub line: i64,
    /// Колонка в символах (с 1).
    pub col: i64,
}

fn is_id_start(c: char) -> bool {
    c.is_ascii_alphabetic() || c == '_' || c == '$'
}

fn is_id_part(c: char) -> bool {
    c.is_ascii_alphanumeric() || c == '_' || c == '$'
}

fn is_digit(c: char) -> bool {
    c.is_ascii_digit()
}

/// Длина совпадения числового литерала в позиции `pos` или 0.
fn match_number(s: &[char], pos: usize) -> usize {
    let n = s.len();
    let at = |i: usize| if i < n { Some(s[i]) } else { None };
    // 0[xX][0-9a-fA-F_]+[lL]?
    if at(pos) == Some('0') && matches!(at(pos + 1), Some('x') | Some('X')) {
        let mut i = pos + 2;
        while let Some(c) = at(i) {
            if c.is_ascii_hexdigit() || c == '_' {
                i += 1;
            } else {
                break;
            }
        }
        if i > pos + 2 {
            if matches!(at(i), Some('l') | Some('L')) {
                i += 1;
            }
            return i - pos;
        }
    }
    // \d[\d_]*\.?\d*(?:[eE][+-]?\d+)?[fFdDlL]?
    if at(pos).is_some_and(is_digit) {
        let mut i = pos + 1;
        while at(i).is_some_and(|c| is_digit(c) || c == '_') {
            i += 1;
        }
        if at(i) == Some('.') {
            i += 1;
        }
        while at(i).is_some_and(is_digit) {
            i += 1;
        }
        i = match_exponent(s, i);
        if matches!(at(i), Some('f' | 'F' | 'd' | 'D' | 'l' | 'L')) {
            i += 1;
        }
        return i - pos;
    }
    // \.\d[\d_]*(?:[eE][+-]?\d+)?[fFdD]?
    if at(pos) == Some('.') && at(pos + 1).is_some_and(is_digit) {
        let mut i = pos + 2;
        while at(i).is_some_and(|c| is_digit(c) || c == '_') {
            i += 1;
        }
        i = match_exponent(s, i);
        if matches!(at(i), Some('f' | 'F' | 'd' | 'D')) {
            i += 1;
        }
        return i - pos;
    }
    0
}

fn match_exponent(s: &[char], i: usize) -> usize {
    let n = s.len();
    if i < n && (s[i] == 'e' || s[i] == 'E') {
        let mut j = i + 1;
        if j < n && (s[j] == '+' || s[j] == '-') {
            j += 1;
        }
        let start = j;
        while j < n && is_digit(s[j]) {
            j += 1;
        }
        if j > start {
            return j;
        }
    }
    i
}

/// Длина строкового (`quote = '"'`) или символьного литерала, или 0.
fn match_quoted(s: &[char], pos: usize, quote: char, at_least_one: bool) -> usize {
    let n = s.len();
    if s[pos] != quote {
        return 0;
    }
    let mut i = pos + 1;
    let mut count = 0;
    while i < n {
        let c = s[i];
        if c == '\\' {
            // Обратная косая черта с любым следующим символом (в том числе
            // переводом строки): шаблон разбирается с флагом DOTALL.
            if i + 1 < n {
                i += 2;
                count += 1;
                continue;
            }
            return 0;
        }
        if c == quote {
            if at_least_one && count == 0 {
                return 0;
            }
            return i + 1 - pos;
        }
        if c == '\n' {
            return 0;
        }
        i += 1;
        count += 1;
    }
    0
}

/// Разбивает исходный текст Java на лексемы с позициями.
///
/// Пробелы и комментарии отбрасываются, в конце добавляется лексема `Eof`.
pub fn tokenize(src: &str) -> Vec<Tok> {
    let s: Vec<char> = src.chars().collect();
    let n = s.len();
    let mut toks = Vec::new();
    let (mut line, mut ls, mut pos) = (1i64, 0usize, 0usize);
    let keywords: HashSet<&str> = KEYWORDS.iter().copied().collect();
    while pos < n {
        let c = s[pos];
        let col = (pos - ls + 1) as i64;
        if matches!(c, ' ' | '\t' | '\r' | '\x0c') {
            while pos < n && matches!(s[pos], ' ' | '\t' | '\r' | '\x0c') {
                pos += 1;
            }
            continue;
        }
        if c == '\n' {
            line += 1;
            pos += 1;
            ls = pos;
            continue;
        }
        if c == '/' && pos + 1 < n && s[pos + 1] == '/' {
            while pos < n && s[pos] != '\n' {
                pos += 1;
            }
            continue;
        }
        if c == '/' && pos + 1 < n && s[pos + 1] == '*' {
            let mut j = pos + 2;
            let mut found = None;
            while j + 1 < n {
                if s[j] == '*' && s[j + 1] == '/' {
                    found = Some(j + 2);
                    break;
                }
                j += 1;
            }
            if let Some(end) = found {
                let text = &s[pos..end];
                let nls = text.iter().filter(|&&ch| ch == '\n').count();
                if nls > 0 {
                    line += nls as i64;
                    let last = text.iter().rposition(|&ch| ch == '\n').unwrap_or(0);
                    ls = pos + last + 1;
                }
                pos = end;
                continue;
            }
        }
        if c == '"' {
            let len = match_quoted(&s, pos, '"', false);
            if len > 0 {
                toks.push(Tok {
                    k: TokKind::Str,
                    t: s[pos..pos + len].iter().collect(),
                    line,
                    col,
                });
                pos += len;
                continue;
            }
        }
        if c == '\'' {
            let len = match_quoted(&s, pos, '\'', true);
            if len > 0 {
                toks.push(Tok {
                    k: TokKind::Chr,
                    t: s[pos..pos + len].iter().collect(),
                    line,
                    col,
                });
                pos += len;
                continue;
            }
        }
        let len = match_number(&s, pos);
        if len > 0 {
            toks.push(Tok {
                k: TokKind::Num,
                t: s[pos..pos + len].iter().collect(),
                line,
                col,
            });
            pos += len;
            continue;
        }
        if is_id_start(c) {
            let mut j = pos + 1;
            while j < n && is_id_part(s[j]) {
                j += 1;
            }
            let text: String = s[pos..j].iter().collect();
            let k = if keywords.contains(text.as_str()) {
                TokKind::Kw
            } else {
                TokKind::Id
            };
            toks.push(Tok { k, t: text, line, col });
            pos = j;
            continue;
        }
        let mut matched = None;
        for op in OPERATORS {
            let oc: Vec<char> = op.chars().collect();
            if pos + oc.len() <= n && s[pos..pos + oc.len()] == oc[..] {
                matched = Some(op.to_string());
                break;
            }
        }
        if matched.is_none() && SINGLE_OPS.contains(c) {
            matched = Some(c.to_string());
        }
        if let Some(op) = matched {
            pos += op.chars().count();
            toks.push(Tok {
                k: TokKind::Op,
                t: op,
                line,
                col,
            });
            continue;
        }
        pos += 1;
    }
    toks.push(Tok {
        k: TokKind::Eof,
        t: "<eof>".to_string(),
        line,
        col: 1,
    });
    toks
}

// ------------------------------------------------------------------------ AST

/// Ссылка на выражение.
pub type E = Rc<Expr>;
/// Ссылка на оператор.
pub type S = Rc<Stmt>;

/// Значение литерала.
#[derive(Clone, Debug)]
pub enum LitVal {
    /// Целое число.
    Int(i64),
    /// Число с плавающей точкой.
    Float(f64),
    /// Строка или символ.
    Str(Rc<str>),
    /// Логическое значение.
    Bool(bool),
    /// `null`.
    Null,
}

/// Вид литерала.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum LitKind {
    /// Целое.
    Int,
    /// Дробное.
    Float,
    /// Строка.
    Str,
    /// Символ.
    Char,
    /// Логическое.
    Bool,
    /// `null`.
    Null,
}

/// Литерал класса: имя типа или выражение перед `.class`.
#[derive(Debug)]
pub enum ClassLitTy {
    /// Имя типа.
    Name(String),
    /// Выражение.
    Expr(E),
}

/// Тело лямбды.
#[derive(Debug, Clone)]
pub enum LambdaBody {
    /// Блок операторов.
    Block(S),
    /// Выражение.
    Expr(E),
}

/// Выражение Java.
#[derive(Debug)]
pub enum Expr {
    /// Литерал.
    Lit(LitKind, LitVal),
    /// Имя.
    Name { id: Rc<str>, line: i64, col: i64 },
    /// Обращение к полю через точку.
    FieldAcc { obj: E, name: Rc<str>, line: i64, col: i64 },
    /// Вызов метода (`obj` пуст — неявный получатель).
    Call {
        obj: Option<E>,
        name: Rc<str>,
        args: Vec<E>,
        line: i64,
        col: i64,
    },
    /// Создание объекта.
    New {
        ty: Rc<str>,
        args: Vec<E>,
        body: Option<Rc<ClassDecl>>,
        line: i64,
        col: i64,
        outer: Option<E>,
    },
    /// Создание массива.
    NewArray {
        ty: Rc<str>,
        dims: Vec<Option<E>>,
        init: Option<Vec<E>>,
    },
    /// Литерал массива.
    ArrayLit(Vec<E>),
    /// Элемент массива.
    Index { obj: E, idx: E },
    /// Унарный оператор.
    Unary { op: Rc<str>, e: E },
    /// Постфиксный оператор.
    Postfix { op: Rc<str>, e: E },
    /// Бинарный оператор.
    Binary { op: Rc<str>, l: E, r: E },
    /// Присваивание.
    Assign { op: Rc<str>, target: E, value: E },
    /// Условный оператор.
    Cond { c: E, a: E, b: E },
    /// Приведение типа.
    Cast { ty: Rc<str>, e: E },
    /// `instanceof`.
    InstanceOf {
        e: E,
        ty: Rc<str>,
        bind: Option<Rc<str>>,
    },
    /// Лямбда.
    Lambda {
        params: Rc<Vec<Rc<str>>>,
        body: LambdaBody,
    },
    /// Ссылка на метод.
    MethodRef { obj: E, name: Rc<str> },
    /// `this`.
    This,
    /// `super`.
    Super,
    /// Литерал класса.
    ClassLit(ClassLitTy),
    /// Имя типа в позиции выражения.
    TypeExpr(Rc<str>),
    /// `switch` в позиции выражения.
    SwitchExpr(S),
}

/// Ветвь `switch`: метки (`None` — `default`) и операторы.
pub type Case = (Option<Vec<E>>, Vec<S>);

/// Оператор Java.
#[derive(Debug)]
pub enum Stmt {
    /// Блок.
    Block { stmts: Vec<S>, line: i64 },
    /// Объявление локальных переменных.
    LocalVar {
        ty: Rc<str>,
        decls: Vec<(Rc<str>, Option<E>)>,
        line: i64,
    },
    /// Оператор-выражение.
    ExprStmt { e: E, line: i64 },
    /// `if`.
    If {
        c: E,
        then: S,
        els: Option<S>,
        line: i64,
    },
    /// `while`.
    While { c: E, body: S, line: i64 },
    /// `do … while`.
    DoWhile { body: S, c: E, line: i64 },
    /// `for`.
    For {
        init: Vec<S>,
        c: Option<E>,
        update: Vec<E>,
        body: S,
        line: i64,
    },
    /// Цикл по коллекции.
    ForEach {
        ty: Rc<str>,
        name: Rc<str>,
        iter: E,
        body: S,
        line: i64,
    },
    /// `return`.
    Return { e: Option<E>, line: i64 },
    /// `throw`.
    Throw { e: E, line: i64 },
    /// `break`.
    Break { label: Option<Rc<str>> },
    /// `continue`.
    Continue { label: Option<Rc<str>> },
    /// `try`.
    Try {
        res: Vec<(Option<Rc<str>>, E)>,
        body: S,
        catches: Vec<(Vec<Rc<str>>, Rc<str>, S)>,
        fin: Option<S>,
        line: i64,
    },
    /// `switch`.
    Switch { e: E, cases: Vec<Case>, line: i64 },
    /// `synchronized`.
    Sync { e: E, body: S },
    /// Оператор с меткой.
    Labeled { label: Rc<str>, stmt: S },
    /// Локальный класс.
    LocalClass(Rc<ClassDecl>),
    /// `assert`.
    Assert { c: E, m: Option<E> },
    /// Пустой оператор.
    Empty,
}

impl Stmt {
    /// Строка оператора (0, если у вида оператора её нет).
    pub fn line(&self) -> i64 {
        match self {
            Stmt::Block { line, .. }
            | Stmt::LocalVar { line, .. }
            | Stmt::ExprStmt { line, .. }
            | Stmt::If { line, .. }
            | Stmt::While { line, .. }
            | Stmt::DoWhile { line, .. }
            | Stmt::For { line, .. }
            | Stmt::ForEach { line, .. }
            | Stmt::Return { line, .. }
            | Stmt::Throw { line, .. }
            | Stmt::Try { line, .. }
            | Stmt::Switch { line, .. } => *line,
            _ => 0,
        }
    }
}

/// Параметр метода.
#[derive(Debug)]
pub struct Param {
    /// Тип.
    pub ty: Rc<str>,
    /// Имя.
    pub name: Rc<str>,
    /// Аннотации.
    pub annots: Vec<Annot>,
    /// Переменное число аргументов.
    pub varargs: bool,
}

/// Аннотация: имя и исходный текст аргументов.
#[derive(Debug, Clone)]
pub struct Annot {
    /// Имя (возможно, через точку).
    pub name: String,
    /// Аргументы исходным текстом (лексемы через пробел).
    pub args: String,
}

/// Объявление метода или конструктора.
#[derive(Debug)]
pub struct MethodDecl {
    /// Имя (`<init>` у конструктора).
    pub name: Rc<str>,
    /// Параметры.
    pub params: Vec<Param>,
    /// Возвращаемый тип.
    pub ret: Option<Rc<str>>,
    /// Тело.
    pub body: Option<S>,
    /// Модификаторы.
    pub mods: HashSet<String>,
    /// Аннотации.
    pub annots: Vec<Annot>,
    /// Строка имени.
    pub line: i64,
    /// Строка конца.
    pub end: i64,
    /// Конструктор ли это.
    pub ctor: bool,
    /// Есть ли параметры типа.
    pub tparams: bool,
    /// Строка начала объявления.
    pub start: i64,
}

/// Объявление поля.
#[derive(Debug)]
pub struct FieldDecl {
    /// Тип.
    pub ty: Rc<str>,
    /// Имя.
    pub name: Rc<str>,
    /// Инициализатор.
    pub init: Option<E>,
    /// Модификаторы.
    pub mods: HashSet<String>,
    /// Аннотации.
    pub annots: Vec<Annot>,
    /// Строка.
    pub line: i64,
}

/// Константа перечисления.
#[derive(Debug)]
pub struct EnumConst {
    /// Имя.
    pub name: Rc<str>,
    /// Аргументы конструктора.
    pub args: Vec<E>,
    /// Тело (анонимный класс).
    pub body: Option<Rc<ClassDecl>>,
    /// Строка.
    pub line: i64,
}

/// Объявление класса, интерфейса, перечисления или аннотации.
#[derive(Debug, Default)]
pub struct ClassDecl {
    /// Вид: class, interface, enum, annotation.
    pub kind: String,
    /// Простое имя.
    pub name: String,
    /// Модификаторы.
    pub mods: HashSet<String>,
    /// Аннотации.
    pub annots: Vec<Annot>,
    /// Суперкласс.
    pub ext: Option<String>,
    /// Интерфейсы.
    pub impls: Vec<String>,
    /// Поля.
    pub fields: Vec<FieldDecl>,
    /// Методы и конструкторы.
    pub methods: Vec<Rc<MethodDecl>>,
    /// Блоки инициализации (статический ли, блок).
    pub inits: Vec<(bool, S)>,
    /// Вложенные классы.
    pub inner: Vec<Rc<ClassDecl>>,
    /// Константы перечисления.
    pub enums: Vec<EnumConst>,
    /// Строка начала.
    pub line: i64,
    /// Строка конца.
    pub end: i64,
    /// Анонимный ли класс.
    pub anon: bool,
    /// Полное имя.
    pub fqn: String,
    /// Параметры типа.
    pub tparams: Option<Vec<String>>,
}

/// Ошибка разбора исходного файла Java.
#[derive(Debug)]
pub struct ParseError(pub String);

impl fmt::Display for ParseError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.0)
    }
}

type PR<T> = Result<T, ParseError>;

/// Импорт: статический ли и полное имя.
pub type Import = (bool, String);

/// Рекурсивный разборщик Java 8.
pub struct Parser {
    toks: Vec<Tok>,
    i: usize,
    path: String,
    /// Пакет файла.
    pub pkg: String,
    /// Импорты файла.
    pub imports: Vec<Import>,
    anon_counter: Cell<usize>,
}

const ASSIGN_OPS: &[&str] = &[
    "=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>=", ">>>=",
];

const PREC: &[&[&str]] = &[
    &["||"],
    &["&&"],
    &["|"],
    &["^"],
    &["&"],
    &["==", "!="],
    &["<", ">", "<=", ">=", "instanceof"],
    &["<<", ">>", ">>>"],
    &["+", "-"],
    &["*", "/", "%"],
];

fn rc(s: &str) -> Rc<str> {
    Rc::from(s)
}

impl Parser {
    /// Готовит разбор исходного текста из файла `path`.
    pub fn new(src: &str, path: &str) -> Self {
        Parser {
            toks: tokenize(src),
            i: 0,
            path: path.to_string(),
            pkg: String::new(),
            imports: Vec::new(),
            anon_counter: Cell::new(0),
        }
    }

    fn tok(&self) -> &Tok {
        &self.toks[self.i]
    }

    fn peek(&self, k: usize) -> &Tok {
        let j = self.i + k;
        if j < self.toks.len() {
            &self.toks[j]
        } else {
            self.toks.last().expect("eof")
        }
    }

    fn word_kind(k: TokKind) -> bool {
        matches!(k, TokKind::Op | TokKind::Kw | TokKind::Id)
    }

    fn at(&self, t: &str) -> bool {
        let x = self.tok();
        x.t == t && Self::word_kind(x.k)
    }

    fn at_op(&self, t: &str) -> bool {
        let x = self.tok();
        x.k == TokKind::Op && x.t == t
    }

    fn accept(&mut self, t: &str) -> bool {
        if self.at(t) {
            self.i += 1;
            true
        } else {
            false
        }
    }

    fn err(&self, msg: &str) -> ParseError {
        let x = self.tok();
        ParseError(format!("{}:{}:{}: {}", self.path, x.line, x.col, msg))
    }

    fn expect(&mut self, t: &str) -> PR<Tok> {
        if !self.at(t) {
            let found = self.tok().t.clone();
            return Err(self.err(&format!("ожидалось {t:?}, найдено {found:?}")));
        }
        let x = self.tok().clone();
        self.i += 1;
        Ok(x)
    }

    fn ident(&mut self) -> PR<String> {
        let x = self.tok();
        if x.k != TokKind::Id {
            let found = x.t.clone();
            return Err(self.err(&format!("ожидался идентификатор, найдено {found:?}")));
        }
        let t = x.t.clone();
        self.i += 1;
        Ok(t)
    }

    fn split_gt(&mut self) {
        let x = &self.toks[self.i];
        if x.k == TokKind::Op && x.t.starts_with('>') && x.t.len() > 1 {
            let rest = Tok {
                k: TokKind::Op,
                t: x.t[1..].to_string(),
                line: x.line,
                col: x.col + 1,
            };
            self.toks[self.i].t = ">".to_string();
            self.toks.insert(self.i + 1, rest);
        }
    }

    fn skip_balanced(&mut self, open: &str, close: &str) -> PR<()> {
        let mut depth = 0;
        loop {
            let x = self.tok();
            if x.k == TokKind::Eof {
                return Err(ParseError(format!("unbalanced {open}")));
            }
            if x.k == TokKind::Op {
                if x.t == open {
                    depth += 1;
                } else if x.t == close {
                    depth -= 1;
                    if depth == 0 {
                        self.i += 1;
                        return Ok(());
                    }
                }
            }
            self.i += 1;
        }
    }

    // ---------------------------------------------------------------- типы

    fn parse_type(&mut self) -> PR<String> {
        let mut parts = String::new();
        while self.at_op("@") {
            self.parse_annotation()?;
        }
        let x = self.tok().clone();
        if x.k == TokKind::Kw && is_prim(&x.t) {
            self.i += 1;
            parts.push_str(&x.t);
        } else if x.k == TokKind::Op && x.t == "?" {
            self.i += 1;
            parts.push('?');
            if self.accept("extends") || self.accept("super") {
                parts.push(' ');
                parts.push_str(&self.parse_type()?);
            }
            return Ok(parts);
        } else if x.k == TokKind::Id {
            parts.push_str(&self.ident()?);
            loop {
                if self.at_op("<") {
                    parts.push_str(&self.parse_type_args()?);
                }
                if self.at_op(".") && self.peek(1).k == TokKind::Id {
                    self.i += 1;
                    parts.push('.');
                    parts.push_str(&self.ident()?);
                } else {
                    break;
                }
            }
        } else if x.k == TokKind::Kw && x.t == "void" {
            self.i += 1;
            return Ok("void".to_string());
        } else {
            return Err(self.err(&format!("ожидался тип, найдено {:?}", x.t)));
        }
        while self.at_op("[") && self.peek(1).t == "]" {
            self.i += 2;
            parts.push_str("[]");
        }
        Ok(parts)
    }

    fn parse_type_args(&mut self) -> PR<String> {
        self.expect("<")?;
        let mut out = String::from("<");
        if self.at_op(">") {
            self.i += 1;
            return Ok("<>".to_string());
        }
        loop {
            out.push_str(&self.parse_type()?);
            if self.accept(",") {
                out.push(',');
                continue;
            }
            break;
        }
        self.split_gt();
        self.expect(">")?;
        out.push('>');
        Ok(out)
    }

    // ---------------------------------------------------------- аннотации

    fn parse_annotation(&mut self) -> PR<Annot> {
        self.expect("@")?;
        let mut name = self.ident()?;
        while self.at_op(".") && self.peek(1).k == TokKind::Id {
            self.i += 1;
            name.push('.');
            name.push_str(&self.ident()?);
        }
        let mut args = String::new();
        if self.at_op("(") {
            let start = self.i;
            self.skip_balanced("(", ")")?;
            args = self.toks[start..self.i]
                .iter()
                .map(|t| t.t.as_str())
                .collect::<Vec<_>>()
                .join(" ");
        }
        Ok(Annot { name, args })
    }

    fn parse_modifiers(&mut self) -> PR<(HashSet<String>, Vec<Annot>)> {
        let mut mods = HashSet::new();
        let mut annots = Vec::new();
        loop {
            let x = self.tok().clone();
            if x.k == TokKind::Op && x.t == "@" && self.peek(1).t != "interface" {
                annots.push(self.parse_annotation()?);
            } else if x.k == TokKind::Kw && MODIFIERS.contains(&x.t.as_str()) {
                if x.t == "default" && matches!(self.peek(1).t.as_str(), ":" | "->") {
                    break;
                }
                mods.insert(x.t.clone());
                self.i += 1;
            } else {
                break;
            }
        }
        Ok((mods, annots))
    }

    // ------------------------------------------------------- файл целиком

    /// Разбирает файл: пакет, импорты и объявления типов.
    pub fn parse_unit(&mut self) -> PR<Vec<Rc<ClassDecl>>> {
        let mut types = Vec::new();
        if self.at("package") {
            self.i += 1;
            self.pkg = self.qualified(false)?;
            self.expect(";")?;
        }
        while self.at("import") {
            self.i += 1;
            let st = self.accept("static");
            let q = self.qualified(true)?;
            self.expect(";")?;
            self.imports.push((st, q));
        }
        while self.tok().k != TokKind::Eof {
            if self.accept(";") {
                continue;
            }
            let (mods, annots) = self.parse_modifiers()?;
            types.push(Rc::new(self.parse_class(mods, annots, None)?));
        }
        Ok(types)
    }

    fn qualified(&mut self, allow_star: bool) -> PR<String> {
        let mut parts = vec![self.ident()?];
        while self.at_op(".") {
            self.i += 1;
            if allow_star && self.at_op("*") {
                self.i += 1;
                parts.push("*".to_string());
                break;
            }
            parts.push(self.ident()?);
        }
        Ok(parts.join("."))
    }

    // ----------------------------------------------------------- объявления

    fn parse_class(
        &mut self,
        mods: HashSet<String>,
        annots: Vec<Annot>,
        outer_fqn: Option<&str>,
    ) -> PR<ClassDecl> {
        let x = self.tok().clone();
        let kind = if x.t == "@" && self.peek(1).t == "interface" {
            self.i += 2;
            "annotation".to_string()
        } else if matches!(x.t.as_str(), "class" | "interface" | "enum") {
            self.i += 1;
            x.t.clone()
        } else {
            return Err(self.err(&format!(
                "ожидалось class/interface/enum, найдено {:?}",
                x.t
            )));
        };
        let line = x.line;
        let name = self.ident()?;
        let fqn = match outer_fqn {
            None => {
                if self.pkg.is_empty() {
                    name.clone()
                } else {
                    format!("{}.{}", self.pkg, name)
                }
            }
            Some(o) => format!("{o}${name}"),
        };
        let mut c = ClassDecl {
            kind: kind.clone(),
            name,
            mods,
            annots,
            line,
            end: line,
            fqn,
            ..Default::default()
        };
        if self.at_op("<") {
            c.tparams = Some(self.parse_type_params()?);
        }
        if self.accept("extends") {
            if kind == "interface" {
                c.impls.push(self.parse_type()?);
                while self.accept(",") {
                    c.impls.push(self.parse_type()?);
                }
            } else {
                c.ext = Some(self.parse_type()?);
            }
        }
        if self.accept("implements") {
            c.impls.push(self.parse_type()?);
            while self.accept(",") {
                c.impls.push(self.parse_type()?);
            }
        }
        self.parse_class_body(&mut c)?;
        Ok(c)
    }

    fn parse_type_params(&mut self) -> PR<Vec<String>> {
        self.expect("<")?;
        let mut depth: i64 = 1;
        let mut names = Vec::new();
        let mut expect_name = true;
        while depth != 0 {
            let x = self.tok().clone();
            if x.k == TokKind::Eof {
                return Err(ParseError("type params".to_string()));
            }
            if x.k == TokKind::Op {
                match x.t.as_str() {
                    "<" => depth += 1,
                    ">" => depth -= 1,
                    ">>" => depth -= 2,
                    ">>>" => depth -= 3,
                    "," if depth == 1 => expect_name = true,
                    _ => {}
                }
            } else if x.k == TokKind::Id && expect_name && depth == 1 {
                names.push(x.t.clone());
                expect_name = false;
            }
            self.i += 1;
        }
        Ok(names)
    }

    fn parse_class_body(&mut self, c: &mut ClassDecl) -> PR<()> {
        self.expect("{")?;
        if c.kind == "enum" {
            self.parse_enum_constants(c)?;
        }
        while !self.at_op("}") {
            if self.tok().k == TokKind::Eof {
                return Err(ParseError(format!("{}: EOF in class {}", self.path, c.name)));
            }
            self.parse_member(c)?;
        }
        c.end = self.tok().line;
        self.expect("}")?;
        Ok(())
    }

    fn parse_enum_constants(&mut self, c: &mut ClassDecl) -> PR<()> {
        while self.tok().k == TokKind::Id || self.at_op("@") {
            while self.at_op("@") {
                self.parse_annotation()?;
            }
            let line = self.tok().line;
            let name = self.ident()?;
            let mut args = Vec::new();
            if self.at_op("(") {
                args = self.parse_args()?;
            }
            let mut body = None;
            if self.at_op("{") {
                let mut b = ClassDecl {
                    kind: "class".to_string(),
                    name: format!("{}${}", c.name, name),
                    ext: Some(c.name.clone()),
                    line,
                    end: line,
                    anon: true,
                    fqn: format!("{}${}", c.fqn, name),
                    ..Default::default()
                };
                self.parse_class_body(&mut b)?;
                body = Some(Rc::new(b));
            }
            c.enums.push(EnumConst {
                name: rc(&name),
                args,
                body,
                line,
            });
            if !self.accept(",") {
                break;
            }
        }
        self.accept(";");
        Ok(())
    }

    fn parse_member(&mut self, c: &mut ClassDecl) -> PR<()> {
        if self.accept(";") {
            return Ok(());
        }
        if self.at_op("{") {
            let blk = self.parse_block()?;
            c.inits.push((false, blk));
            return Ok(());
        }
        if self.at("static") && self.peek(1).t == "{" {
            self.i += 1;
            let blk = self.parse_block()?;
            c.inits.push((true, blk));
            return Ok(());
        }
        let start_line = self.tok().line;
        let (mods, annots) = self.parse_modifiers()?;
        let x = self.tok().clone();
        if matches!(x.t.as_str(), "class" | "interface" | "enum")
            || (x.t == "@" && self.peek(1).t == "interface")
        {
            let fqn = c.fqn.clone();
            let inner = self.parse_class(mods, annots, Some(&fqn))?;
            c.inner.push(Rc::new(inner));
            return Ok(());
        }
        let mut tparams = false;
        if self.at_op("<") {
            self.parse_type_params()?;
            tparams = true;
        }
        let line = self.tok().line;
        if self.tok().k == TokKind::Id && self.tok().t == c.name && self.peek(1).t == "(" {
            self.i += 1;
            let params = self.parse_params()?;
            if self.accept("throws") {
                self.parse_type()?;
                while self.accept(",") {
                    self.parse_type()?;
                }
            }
            let body = self.parse_block()?;
            let end = self.toks[self.i - 1].line;
            c.methods.push(Rc::new(MethodDecl {
                name: rc("<init>"),
                params,
                ret: None,
                body: Some(body),
                mods,
                annots,
                line,
                end,
                ctor: true,
                tparams,
                start: start_line,
            }));
            return Ok(());
        }
        let rtype = self.parse_type()?;
        let mut nm_tok = self.tok().clone();
        let mut name = self.ident()?;
        if self.at_op("(") {
            let params = self.parse_params()?;
            while self.at_op("[") && self.peek(1).t == "]" {
                self.i += 2;
            }
            if self.accept("throws") {
                self.parse_type()?;
                while self.accept(",") {
                    self.parse_type()?;
                }
            }
            let mut body = None;
            let end;
            if self.at_op("{") {
                body = Some(self.parse_block()?);
                end = self.toks[self.i - 1].line;
            } else {
                if self.accept("default") {
                    while !self.at_op(";") {
                        self.i += 1;
                    }
                }
                self.expect(";")?;
                end = self.toks[self.i - 1].line;
            }
            c.methods.push(Rc::new(MethodDecl {
                name: rc(&name),
                params,
                ret: Some(rc(&rtype)),
                body,
                mods,
                annots,
                line: nm_tok.line,
                end,
                ctor: false,
                tparams,
                start: start_line,
            }));
            return Ok(());
        }
        loop {
            let mut ftype = rtype.clone();
            while self.at_op("[") && self.peek(1).t == "]" {
                self.i += 2;
                ftype.push_str("[]");
            }
            let mut init = None;
            if self.accept("=") {
                init = Some(self.parse_var_init()?);
            }
            c.fields.push(FieldDecl {
                ty: rc(&ftype),
                name: rc(&name),
                init,
                mods: mods.clone(),
                annots: annots.clone(),
                line: nm_tok.line,
            });
            if self.accept(",") {
                nm_tok = self.tok().clone();
                name = self.ident()?;
                continue;
            }
            break;
        }
        self.expect(";")?;
        Ok(())
    }

    fn parse_params(&mut self) -> PR<Vec<Param>> {
        self.expect("(")?;
        let mut params = Vec::new();
        while !self.at_op(")") {
            let (_mods, annots) = self.parse_modifiers()?;
            let mut t = self.parse_type()?;
            let varargs = self.accept("...");
            if self.at("this") {
                self.i += 1;
            } else {
                let nm = self.ident()?;
                while self.at_op("[") && self.peek(1).t == "]" {
                    self.i += 2;
                    t.push_str("[]");
                }
                params.push(Param {
                    ty: rc(&t),
                    name: rc(&nm),
                    annots,
                    varargs,
                });
            }
            if !self.accept(",") {
                break;
            }
        }
        self.expect(")")?;
        Ok(params)
    }

    // ------------------------------------------------------------- операторы

    fn parse_block(&mut self) -> PR<S> {
        let line = self.tok().line;
        self.expect("{")?;
        let mut stmts = Vec::new();
        while !self.at_op("}") {
            if self.tok().k == TokKind::Eof {
                return Err(ParseError(format!("{}: EOF in block", self.path)));
            }
            stmts.push(self.parse_stmt()?);
        }
        self.expect("}")?;
        Ok(Rc::new(Stmt::Block { stmts, line }))
    }

    fn parse_var_init(&mut self) -> PR<E> {
        if self.at_op("{") {
            return self.parse_array_init();
        }
        self.parse_expr()
    }

    fn parse_array_init(&mut self) -> PR<E> {
        self.expect("{")?;
        let mut elems = Vec::new();
        while !self.at_op("}") {
            elems.push(self.parse_var_init()?);
            if !self.accept(",") {
                break;
            }
        }
        self.expect("}")?;
        Ok(Rc::new(Expr::ArrayLit(elems)))
    }

    fn is_local_decl(&mut self) -> bool {
        let x = self.tok().clone();
        if x.k == TokKind::Kw && is_prim(&x.t) {
            return true;
        }
        if x.k == TokKind::Op && x.t == "@" {
            return true;
        }
        if x.k == TokKind::Kw && x.t == "final" {
            return true;
        }
        if x.k != TokKind::Id {
            return false;
        }
        let save = self.i;
        let ok = match self.parse_type() {
            Ok(_) => {
                self.tok().k == TokKind::Id
                    && matches!(self.peek(1).t.as_str(), "=" | ";" | "," | ":" | "[")
            }
            Err(_) => false,
        };
        self.i = save;
        ok
    }

    fn parse_stmt(&mut self) -> PR<S> {
        let x = self.tok().clone();
        let line = x.line;
        if x.k == TokKind::Op {
            if x.t == "{" {
                return self.parse_block();
            }
            if x.t == ";" {
                self.i += 1;
                return Ok(Rc::new(Stmt::Empty));
            }
        }
        if x.k == TokKind::Kw {
            let t = x.t.as_str();
            match t {
                "if" => {
                    self.i += 1;
                    self.expect("(")?;
                    let c = self.parse_expr()?;
                    self.expect(")")?;
                    let then = self.parse_stmt()?;
                    let mut els = None;
                    if self.accept("else") {
                        els = Some(self.parse_stmt()?);
                    }
                    return Ok(Rc::new(Stmt::If { c, then, els, line }));
                }
                "while" => {
                    self.i += 1;
                    self.expect("(")?;
                    let c = self.parse_expr()?;
                    self.expect(")")?;
                    let body = self.parse_stmt()?;
                    return Ok(Rc::new(Stmt::While { c, body, line }));
                }
                "do" => {
                    self.i += 1;
                    let body = self.parse_stmt()?;
                    self.expect("while")?;
                    self.expect("(")?;
                    let c = self.parse_expr()?;
                    self.expect(")")?;
                    self.expect(";")?;
                    return Ok(Rc::new(Stmt::DoWhile { body, c, line }));
                }
                "for" => return self.parse_for(),
                "return" => {
                    self.i += 1;
                    let mut e = None;
                    if !self.at_op(";") {
                        e = Some(self.parse_expr()?);
                    }
                    self.expect(";")?;
                    return Ok(Rc::new(Stmt::Return { e, line }));
                }
                "throw" => {
                    self.i += 1;
                    let e = self.parse_expr()?;
                    self.expect(";")?;
                    return Ok(Rc::new(Stmt::Throw { e, line }));
                }
                "break" | "continue" => {
                    self.i += 1;
                    let mut lab = None;
                    if self.tok().k == TokKind::Id {
                        lab = Some(rc(&self.ident()?));
                    }
                    self.expect(";")?;
                    return Ok(Rc::new(if t == "break" {
                        Stmt::Break { label: lab }
                    } else {
                        Stmt::Continue { label: lab }
                    }));
                }
                "try" => return self.parse_try(),
                "switch" => return self.parse_switch(),
                "synchronized" => {
                    self.i += 1;
                    self.expect("(")?;
                    let e = self.parse_expr()?;
                    self.expect(")")?;
                    let body = self.parse_block()?;
                    return Ok(Rc::new(Stmt::Sync { e, body }));
                }
                "assert" => {
                    self.i += 1;
                    let c = self.parse_expr()?;
                    let mut m = None;
                    if self.accept(":") {
                        m = Some(self.parse_expr()?);
                    }
                    self.expect(";")?;
                    return Ok(Rc::new(Stmt::Assert { c, m }));
                }
                _ => {}
            }
            if matches!(t, "class" | "interface" | "enum" | "abstract" | "static")
                || (t == "final" && self.peek(1).t == "class")
            {
                let (mods, annots) = self.parse_modifiers()?;
                if matches!(self.tok().t.as_str(), "class" | "interface" | "enum") {
                    let decl = self.parse_class(mods, annots, None)?;
                    return Ok(Rc::new(Stmt::LocalClass(Rc::new(decl))));
                }
            }
        }
        if x.k == TokKind::Id && self.peek(1).t == ":" && self.peek(1).k == TokKind::Op {
            let lab = self.ident()?;
            self.i += 1;
            let stmt = self.parse_stmt()?;
            return Ok(Rc::new(Stmt::Labeled {
                label: rc(&lab),
                stmt,
            }));
        }
        if self.is_local_decl() {
            return self.parse_local_var(line);
        }
        let e = self.parse_expr()?;
        self.expect(";")?;
        Ok(Rc::new(Stmt::ExprStmt { e, line }))
    }

    fn parse_local_var(&mut self, line: i64) -> PR<S> {
        self.parse_modifiers()?;
        let t = self.parse_type()?;
        let mut decls = Vec::new();
        loop {
            let nm = self.ident()?;
            while self.at_op("[") && self.peek(1).t == "]" {
                self.i += 2;
            }
            let mut init = None;
            if self.accept("=") {
                init = Some(self.parse_var_init()?);
            }
            decls.push((rc(&nm), init));
            if !self.accept(",") {
                break;
            }
        }
        self.expect(";")?;
        Ok(Rc::new(Stmt::LocalVar {
            ty: rc(&t),
            decls,
            line,
        }))
    }

    fn parse_for(&mut self) -> PR<S> {
        let line = self.tok().line;
        self.expect("for")?;
        self.expect("(")?;
        let save = self.i;
        if self.is_local_decl() {
            self.parse_modifiers()?;
            let t = self.parse_type()?;
            let nm = self.ident()?;
            if self.accept(":") {
                let iter = self.parse_expr()?;
                self.expect(")")?;
                let body = self.parse_stmt()?;
                return Ok(Rc::new(Stmt::ForEach {
                    ty: rc(&t),
                    name: rc(&nm),
                    iter,
                    body,
                    line,
                }));
            }
            self.i = save;
        }
        let mut init = Vec::new();
        if !self.at_op(";") {
            if self.is_local_decl() {
                self.parse_modifiers()?;
                let t = self.parse_type()?;
                let mut decls = Vec::new();
                loop {
                    let nm = self.ident()?;
                    let mut ini = None;
                    if self.accept("=") {
                        ini = Some(self.parse_var_init()?);
                    }
                    decls.push((rc(&nm), ini));
                    if !self.accept(",") {
                        break;
                    }
                }
                init.push(Rc::new(Stmt::LocalVar {
                    ty: rc(&t),
                    decls,
                    line,
                }));
            } else {
                let e = self.parse_expr()?;
                init.push(Rc::new(Stmt::ExprStmt { e, line }));
                while self.accept(",") {
                    let e = self.parse_expr()?;
                    init.push(Rc::new(Stmt::ExprStmt { e, line }));
                }
            }
        }
        self.expect(";")?;
        let mut c = None;
        if !self.at_op(";") {
            c = Some(self.parse_expr()?);
        }
        self.expect(";")?;
        let mut update = Vec::new();
        if !self.at_op(")") {
            update.push(self.parse_expr()?);
            while self.accept(",") {
                update.push(self.parse_expr()?);
            }
        }
        self.expect(")")?;
        let body = self.parse_stmt()?;
        Ok(Rc::new(Stmt::For {
            init,
            c,
            update,
            body,
            line,
        }))
    }

    fn parse_try(&mut self) -> PR<S> {
        let line = self.tok().line;
        self.expect("try")?;
        let mut res = Vec::new();
        if self.accept("(") {
            while !self.at_op(")") {
                if self.is_local_decl() {
                    self.parse_modifiers()?;
                    self.parse_type()?;
                    let nm = self.ident()?;
                    self.expect("=")?;
                    res.push((Some(rc(&nm)), self.parse_expr()?));
                } else {
                    res.push((None, self.parse_expr()?));
                }
                if !self.accept(";") {
                    break;
                }
            }
            self.expect(")")?;
        }
        let body = self.parse_block()?;
        let mut catches = Vec::new();
        while self.at("catch") {
            self.i += 1;
            self.expect("(")?;
            self.parse_modifiers()?;
            let mut types = vec![rc(&self.parse_type()?)];
            while self.accept("|") {
                types.push(rc(&self.parse_type()?));
            }
            let nm = self.ident()?;
            self.expect(")")?;
            catches.push((types, rc(&nm), self.parse_block()?));
        }
        let mut fin = None;
        if self.accept("finally") {
            fin = Some(self.parse_block()?);
        }
        Ok(Rc::new(Stmt::Try {
            res,
            body,
            catches,
            fin,
            line,
        }))
    }

    fn parse_switch(&mut self) -> PR<S> {
        let line = self.tok().line;
        self.expect("switch")?;
        self.expect("(")?;
        let e = self.parse_expr()?;
        self.expect(")")?;
        self.expect("{")?;
        let mut cases = Vec::new();
        while !self.at_op("}") {
            let labels = if self.accept("default") {
                None
            } else {
                self.expect("case")?;
                let mut l = vec![self.parse_ternary()?];
                while self.accept(",") {
                    l.push(self.parse_ternary()?);
                }
                Some(l)
            };
            let stmts = if self.accept("->") {
                if self.at_op("{") {
                    vec![self.parse_block()?]
                } else if self.at("throw") {
                    vec![self.parse_stmt()?]
                } else {
                    let ex = self.parse_expr()?;
                    self.expect(";")?;
                    vec![
                        Rc::new(Stmt::ExprStmt { e: ex, line }),
                        Rc::new(Stmt::Break { label: None }),
                    ]
                }
            } else {
                self.expect(":")?;
                let mut v = Vec::new();
                while !(self.at("case") || self.at("default") || self.at_op("}")) {
                    v.push(self.parse_stmt()?);
                }
                v
            };
            cases.push((labels, stmts));
        }
        self.expect("}")?;
        Ok(Rc::new(Stmt::Switch { e, cases, line }))
    }

    // ------------------------------------------------------------ выражения

    fn parse_expr(&mut self) -> PR<E> {
        self.parse_assign()
    }

    fn parse_assign(&mut self) -> PR<E> {
        if let Some(lam) = self.try_lambda()? {
            return Ok(lam);
        }
        let left = self.parse_ternary()?;
        let x = self.tok().clone();
        if x.k == TokKind::Op && ASSIGN_OPS.contains(&x.t.as_str()) {
            self.i += 1;
            let right = self.parse_assign()?;
            return Ok(Rc::new(Expr::Assign {
                op: rc(&x.t),
                target: left,
                value: right,
            }));
        }
        Ok(left)
    }

    fn try_lambda(&mut self) -> PR<Option<E>> {
        let x = self.tok().clone();
        if x.k == TokKind::Id && self.peek(1).t == "->" && self.peek(1).k == TokKind::Op {
            self.i += 2;
            let body = self.parse_lambda_body()?;
            return Ok(Some(Rc::new(Expr::Lambda {
                params: Rc::new(vec![rc(&x.t)]),
                body,
            })));
        }
        if x.k == TokKind::Op && x.t == "(" {
            let mut depth = 0;
            let mut j = self.i;
            loop {
                let t = &self.toks[j];
                if t.k == TokKind::Eof {
                    return Ok(None);
                }
                if t.k == TokKind::Op {
                    if t.t == "(" {
                        depth += 1;
                    } else if t.t == ")" {
                        depth -= 1;
                        if depth == 0 {
                            break;
                        }
                    }
                }
                j += 1;
            }
            let nxt = &self.toks[j + 1];
            if nxt.k == TokKind::Op && nxt.t == "->" {
                self.i += 1;
                let mut params = Vec::new();
                while !self.at_op(")") {
                    if self.tok().k == TokKind::Id
                        && matches!(self.peek(1).t.as_str(), "," | ")")
                    {
                        params.push(rc(&self.ident()?));
                    } else {
                        self.parse_modifiers()?;
                        self.parse_type()?;
                        params.push(rc(&self.ident()?));
                    }
                    if !self.accept(",") {
                        break;
                    }
                }
                self.expect(")")?;
                self.expect("->")?;
                let body = self.parse_lambda_body()?;
                return Ok(Some(Rc::new(Expr::Lambda {
                    params: Rc::new(params),
                    body,
                })));
            }
        }
        Ok(None)
    }

    fn parse_lambda_body(&mut self) -> PR<LambdaBody> {
        if self.at_op("{") {
            return Ok(LambdaBody::Block(self.parse_block()?));
        }
        Ok(LambdaBody::Expr(self.parse_expr()?))
    }

    fn parse_ternary(&mut self) -> PR<E> {
        let c = self.parse_binary(0)?;
        if self.at_op("?") {
            self.i += 1;
            let a = self.parse_ternary_branch()?;
            self.expect(":")?;
            let b = self.parse_ternary_branch()?;
            return Ok(Rc::new(Expr::Cond { c, a, b }));
        }
        Ok(c)
    }

    fn parse_ternary_branch(&mut self) -> PR<E> {
        if let Some(lam) = self.try_lambda()? {
            return Ok(lam);
        }
        self.parse_ternary()
    }

    fn parse_binary(&mut self, level: usize) -> PR<E> {
        if level >= PREC.len() {
            return self.parse_unary();
        }
        let mut left = self.parse_binary(level + 1)?;
        let ops = PREC[level];
        loop {
            let x = self.tok().clone();
            if (x.k == TokKind::Op || x.k == TokKind::Kw) && ops.contains(&x.t.as_str()) {
                if x.t == "instanceof" {
                    self.i += 1;
                    self.accept("final");
                    let t = self.parse_type()?;
                    let mut bind = None;
                    if self.tok().k == TokKind::Id {
                        bind = Some(rc(&self.ident()?));
                    }
                    left = Rc::new(Expr::InstanceOf {
                        e: left,
                        ty: rc(&t),
                        bind,
                    });
                    continue;
                }
                self.i += 1;
                let right = self.parse_binary(level + 1)?;
                left = Rc::new(Expr::Binary {
                    op: rc(&x.t),
                    l: left,
                    r: right,
                });
            } else {
                break;
            }
        }
        Ok(left)
    }

    fn parse_unary(&mut self) -> PR<E> {
        let x = self.tok().clone();
        if x.k == TokKind::Op {
            if matches!(x.t.as_str(), "+" | "-" | "!" | "~") {
                self.i += 1;
                let e = self.parse_unary()?;
                if x.t == "-" {
                    if let Expr::Lit(kind, val) = &*e {
                        match (kind, val) {
                            (LitKind::Int, LitVal::Int(v)) => {
                                return Ok(Rc::new(Expr::Lit(
                                    LitKind::Int,
                                    LitVal::Int(v.wrapping_neg()),
                                )));
                            }
                            (LitKind::Float, LitVal::Float(v)) => {
                                return Ok(Rc::new(Expr::Lit(LitKind::Float, LitVal::Float(-v))));
                            }
                            _ => {}
                        }
                    }
                }
                return Ok(Rc::new(Expr::Unary { op: rc(&x.t), e }));
            }
            if x.t == "++" || x.t == "--" {
                self.i += 1;
                let e = self.parse_unary()?;
                return Ok(Rc::new(Expr::Unary { op: rc(&x.t), e }));
            }
            if x.t == "(" {
                if let Some(c) = self.try_cast()? {
                    return Ok(c);
                }
            }
        }
        self.parse_postfix()
    }

    fn try_cast(&mut self) -> PR<Option<E>> {
        let save = self.i;
        self.i += 1;
        let x = self.tok().clone();
        let attempt: PR<Option<E>> = (|| {
            if x.k == TokKind::Kw && is_prim(&x.t) {
                let t = self.parse_type()?;
                if self.at_op(")") {
                    self.i += 1;
                    let e = self.parse_unary()?;
                    return Ok(Some(Rc::new(Expr::Cast { ty: rc(&t), e })));
                }
                self.i = save;
                return Ok(None);
            }
            if x.k == TokKind::Id {
                let t = self.parse_type()?;
                while self.accept("&") {
                    self.parse_type()?;
                }
                if self.at_op(")") {
                    let nx = self.peek(1).clone();
                    let ok = matches!(
                        nx.k,
                        TokKind::Id | TokKind::Str | TokKind::Chr | TokKind::Num
                    ) || (nx.k == TokKind::Kw
                        && matches!(
                            nx.t.as_str(),
                            "new" | "this" | "super" | "true" | "false" | "null"
                        ))
                        || (nx.k == TokKind::Op && matches!(nx.t.as_str(), "(" | "!" | "~"));
                    if ok {
                        self.i += 1;
                        let e = self.parse_unary()?;
                        return Ok(Some(Rc::new(Expr::Cast { ty: rc(&t), e })));
                    }
                }
            }
            self.i = save;
            Ok(None)
        })();
        match attempt {
            Ok(v) => Ok(v),
            Err(_) => {
                self.i = save;
                Ok(None)
            }
        }
    }

    fn parse_args(&mut self) -> PR<Vec<E>> {
        self.expect("(")?;
        let mut args = Vec::new();
        while !self.at_op(")") {
            args.push(self.parse_expr()?);
            if !self.accept(",") {
                break;
            }
        }
        self.expect(")")?;
        Ok(args)
    }

    fn parse_postfix(&mut self) -> PR<E> {
        let mut e = self.parse_primary()?;
        loop {
            let x = self.tok().clone();
            if x.k == TokKind::Op {
                match x.t.as_str() {
                    "." => {
                        self.i += 1;
                        if self.at_op("<") {
                            self.parse_type_args()?;
                        }
                        let y = self.tok().clone();
                        if y.k == TokKind::Kw && y.t == "new" {
                            e = self.parse_new(Some(e))?;
                            continue;
                        }
                        if y.k == TokKind::Kw && y.t == "class" {
                            self.i += 1;
                            e = Rc::new(Expr::ClassLit(ClassLitTy::Expr(e)));
                            continue;
                        }
                        if y.k == TokKind::Kw && y.t == "this" {
                            self.i += 1;
                            e = Rc::new(Expr::This);
                            continue;
                        }
                        if y.k == TokKind::Kw && y.t == "super" {
                            self.i += 1;
                            e = Rc::new(Expr::Super);
                            continue;
                        }
                        let nm = self.ident()?;
                        if self.at_op("(") {
                            let args = self.parse_args()?;
                            e = Rc::new(Expr::Call {
                                obj: Some(e),
                                name: rc(&nm),
                                args,
                                line: y.line,
                                col: y.col,
                            });
                        } else {
                            e = Rc::new(Expr::FieldAcc {
                                obj: e,
                                name: rc(&nm),
                                line: y.line,
                                col: y.col,
                            });
                        }
                        continue;
                    }
                    "[" => {
                        self.i += 1;
                        let idx = self.parse_expr()?;
                        self.expect("]")?;
                        e = Rc::new(Expr::Index { obj: e, idx });
                        continue;
                    }
                    "++" | "--" => {
                        self.i += 1;
                        e = Rc::new(Expr::Postfix { op: rc(&x.t), e });
                        continue;
                    }
                    "::" => {
                        self.i += 1;
                        let name = if self.accept("new") {
                            "new".to_string()
                        } else {
                            self.ident()?
                        };
                        e = Rc::new(Expr::MethodRef {
                            obj: e,
                            name: rc(&name),
                        });
                        continue;
                    }
                    _ => {}
                }
            }
            break;
        }
        Ok(e)
    }

    fn parse_new(&mut self, outer: Option<E>) -> PR<E> {
        let x = self.expect("new")?;
        self.parse_modifiers()?;
        let t = self.parse_type_no_dims()?;
        if self.at_op("[") {
            let mut dims = Vec::new();
            while self.at_op("[") {
                self.i += 1;
                if self.at_op("]") {
                    self.i += 1;
                    dims.push(None);
                } else {
                    dims.push(Some(self.parse_expr()?));
                    self.expect("]")?;
                }
            }
            let mut init = None;
            if self.at_op("{") {
                if let Expr::ArrayLit(elems) = &*self.parse_array_init()? {
                    init = Some(elems.clone());
                }
            }
            return Ok(Rc::new(Expr::NewArray {
                ty: rc(&t),
                dims,
                init,
            }));
        }
        let args = self.parse_args()?;
        let mut body = None;
        if self.at_op("{") {
            self.anon_counter.set(self.anon_counter.get() + 1);
            let mut b = ClassDecl {
                kind: "class".to_string(),
                name: String::new(),
                ext: Some(t.clone()),
                line: x.line,
                end: x.line,
                anon: true,
                // Как в Python: полное имя анонимного класса не задано.
                fqn: "None".to_string(),
                ..Default::default()
            };
            self.parse_class_body(&mut b)?;
            body = Some(Rc::new(b));
        }
        Ok(Rc::new(Expr::New {
            ty: rc(&t),
            args,
            body,
            line: x.line,
            col: x.col,
            outer,
        }))
    }

    fn parse_type_no_dims(&mut self) -> PR<String> {
        let x = self.tok().clone();
        if x.k == TokKind::Kw && is_prim(&x.t) {
            self.i += 1;
            return Ok(x.t);
        }
        let mut parts = self.ident()?;
        loop {
            if self.at_op("<") {
                parts.push_str(&self.parse_type_args()?);
            }
            if self.at_op(".") && self.peek(1).k == TokKind::Id {
                self.i += 1;
                parts.push('.');
                parts.push_str(&self.ident()?);
            } else {
                break;
            }
        }
        Ok(parts)
    }

    fn parse_primary(&mut self) -> PR<E> {
        let x = self.tok().clone();
        match x.k {
            TokKind::Num => {
                self.i += 1;
                return Ok(Rc::new(num_lit(&x.t)));
            }
            TokKind::Str => {
                self.i += 1;
                let inner: String = {
                    let cs: Vec<char> = x.t.chars().collect();
                    cs[1..cs.len() - 1].iter().collect()
                };
                return Ok(Rc::new(Expr::Lit(LitKind::Str, LitVal::Str(rc(&unescape(&inner))))));
            }
            TokKind::Chr => {
                self.i += 1;
                let inner: String = {
                    let cs: Vec<char> = x.t.chars().collect();
                    cs[1..cs.len() - 1].iter().collect()
                };
                return Ok(Rc::new(Expr::Lit(LitKind::Char, LitVal::Str(rc(&unescape(&inner))))));
            }
            TokKind::Kw => {
                let t = x.t.as_str();
                match t {
                    "true" | "false" => {
                        self.i += 1;
                        return Ok(Rc::new(Expr::Lit(LitKind::Bool, LitVal::Bool(t == "true"))));
                    }
                    "null" => {
                        self.i += 1;
                        return Ok(Rc::new(Expr::Lit(LitKind::Null, LitVal::Null)));
                    }
                    "this" | "super" => {
                        self.i += 1;
                        if self.at_op("(") {
                            let args = self.parse_args()?;
                            return Ok(Rc::new(Expr::Call {
                                obj: None,
                                name: rc(t),
                                args,
                                line: x.line,
                                col: x.col,
                            }));
                        }
                        return Ok(Rc::new(if t == "this" { Expr::This } else { Expr::Super }));
                    }
                    "new" => return self.parse_new(None),
                    "switch" => {
                        let s = self.parse_switch()?;
                        return Ok(Rc::new(Expr::SwitchExpr(s)));
                    }
                    _ => {}
                }
                if is_prim(t) || t == "void" {
                    let ty = self.parse_type()?;
                    if self.at_op(".") && self.peek(1).t == "class" {
                        self.i += 2;
                        return Ok(Rc::new(Expr::ClassLit(ClassLitTy::Name(ty))));
                    }
                    if self.at_op("::") {
                        return Ok(Rc::new(Expr::TypeExpr(rc(&ty))));
                    }
                    return Err(ParseError(format!(
                        "{}:{}:{}: неожиданный {}",
                        self.path, x.line, x.col, t
                    )));
                }
            }
            TokKind::Op => {
                if x.t == "(" {
                    self.i += 1;
                    let e = self.parse_expr()?;
                    self.expect(")")?;
                    return Ok(e);
                }
                if x.t == "{" {
                    return self.parse_array_init();
                }
            }
            TokKind::Id => {
                self.i += 1;
                if self.at_op("(") {
                    let args = self.parse_args()?;
                    return Ok(Rc::new(Expr::Call {
                        obj: None,
                        name: rc(&x.t),
                        args,
                        line: x.line,
                        col: x.col,
                    }));
                }
                if self.at_op("[") && self.peek(1).t == "]" {
                    let save = self.i;
                    self.i -= 1;
                    let ty = self.parse_type()?;
                    if self.at_op(".") && self.peek(1).t == "class" {
                        self.i += 2;
                        return Ok(Rc::new(Expr::ClassLit(ClassLitTy::Name(ty))));
                    }
                    if self.at_op("::") {
                        return Ok(Rc::new(Expr::TypeExpr(rc(&ty))));
                    }
                    self.i = save;
                }
                if self.at_op("<") {
                    let save = self.i;
                    if self.parse_type_args().is_ok() && self.at_op("::") {
                        return Ok(Rc::new(Expr::Name {
                            id: rc(&x.t),
                            line: x.line,
                            col: x.col,
                        }));
                    }
                    self.i = save;
                }
                return Ok(Rc::new(Expr::Name {
                    id: rc(&x.t),
                    line: x.line,
                    col: x.col,
                }));
            }
            _ => {}
        }
        Err(ParseError(format!(
            "{}:{}:{}: неожиданный токен {:?}",
            self.path, x.line, x.col, x.t
        )))
    }
}

/// Переводит текст в целое по основанию, как `int(s, base)` в Python.
fn py_int(s: &str, base: u32) -> Option<i64> {
    let t = s.trim();
    let (neg, body) = match t.strip_prefix('-') {
        Some(r) => (true, r),
        None => (false, t.strip_prefix('+').unwrap_or(t)),
    };
    let body = if base == 16 {
        body.strip_prefix("0x")
            .or_else(|| body.strip_prefix("0X"))
            .unwrap_or(body)
    } else {
        body
    };
    if body.is_empty() {
        return None;
    }
    let v = i128::from_str_radix(body, base).ok()?;
    let v = if neg { -v } else { v };
    i64::try_from(v).ok().or(Some(v as i64))
}

/// Переводит числовой литерал Java в узел `Lit`.
pub fn num_lit(t: &str) -> Expr {
    let s = t.replace('_', "");
    let low = s.to_lowercase();
    let int = |v: Option<i64>| match v {
        Some(v) => Expr::Lit(LitKind::Int, LitVal::Int(v)),
        None => Expr::Lit(LitKind::Float, LitVal::Float(0.0)),
    };
    if low.starts_with("0x") {
        return int(py_int(low.trim_end_matches('l'), 16));
    }
    if low.ends_with('l') && !low.contains('.') {
        return int(py_int(&low[..low.len() - 1], 10));
    }
    if low.ends_with('f') || low.ends_with('d') || low.contains('.') || low.contains('e') {
        let f: Option<f64> = low.trim_end_matches(['f', 'd']).parse().ok();
        return Expr::Lit(LitKind::Float, LitVal::Float(f.unwrap_or(0.0)));
    }
    if low.starts_with('0') && low.len() > 1 && low.chars().all(|c| c.is_ascii_digit()) {
        return int(py_int(&low, 8));
    }
    int(py_int(&low, 10))
}

/// Раскрывает escape-последовательности строкового литерала Java.
pub fn unescape(s: &str) -> String {
    if !s.contains('\\') {
        return s.to_string();
    }
    let cs: Vec<char> = s.chars().collect();
    let mut out = String::new();
    let mut i = 0;
    while i < cs.len() {
        let c = cs[i];
        if c == '\\' && i + 1 < cs.len() {
            let d = cs[i + 1];
            if d == 'u' && i + 5 <= cs.len() {
                let hex: String = cs[i + 2..(i + 6).min(cs.len())].iter().collect();
                if let Ok(code) = u32::from_str_radix(hex.trim(), 16) {
                    if let Some(ch) = char::from_u32(code) {
                        out.push(ch);
                        i += 6;
                        continue;
                    }
                }
            }
            out.push(match d {
                'n' => '\n',
                't' => '\t',
                'r' => '\r',
                'b' => '\u{8}',
                'f' => '\u{c}',
                '0' => '\0',
                other => other,
            });
            i += 2;
        } else {
            out.push(c);
            i += 1;
        }
    }
    out
}

/// Разобранный файл: пакет, импорты и объявления типов.
pub struct ParsedFile {
    /// Пакет.
    pub pkg: String,
    /// Импорты.
    pub imports: Rc<Vec<Import>>,
    /// Объявления типов верхнего уровня.
    pub types: Vec<Rc<ClassDecl>>,
}

/// Разбирает файл Java.
pub fn parse_file(path: &str) -> Result<ParsedFile, ParseError> {
    let bytes = std::fs::read(path).map_err(|e| ParseError(format!("{path}: {e}")))?;
    let text = String::from_utf8_lossy(&bytes).into_owned();
    parse_text(&text, path)
}

/// Разбирает исходный текст Java.
pub fn parse_text(text: &str, path: &str) -> Result<ParsedFile, ParseError> {
    let mut p = Parser::new(text, path);
    let types = p.parse_unit()?;
    Ok(ParsedFile {
        pkg: p.pkg,
        imports: Rc::new(p.imports),
        types,
    })
}
