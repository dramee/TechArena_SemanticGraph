//! Значения времени выполнения интерпретатора Java.
//!
//! Модель повторяет динамические значения исходного решения: объекты
//! проекта, константы перечислений, библиотечные объекты, коллекции Java,
//! даты и неизвестное значение `Unk`.

use std::cell::RefCell;
use std::fmt::Write as _;
use std::rc::Rc;

use chrono::NaiveDateTime;
use indexmap::IndexMap;

use crate::decimal::Dec;
use crate::interp::FrameRef;
use crate::jparse::LambdaBody;
use crate::model::{CiRef, MiRef};
use crate::repo::RepoProxy;

/// Изменяемая общая ссылка.
pub type Shared<T> = Rc<RefCell<T>>;

/// Создаёт изменяемую общую ссылку.
pub fn shared<T>(v: T) -> Shared<T> {
    Rc::new(RefCell::new(v))
}

/// Объект проекта.
pub type ObjRef = Shared<JObj>;
/// Константа перечисления.
pub type EnumRef = Shared<JEnum>;
/// Библиотечный объект.
pub type LibRef = Shared<LibObj>;
/// Список Java.
pub type ListRef = Shared<JList>;
/// Множество Java.
pub type SetRef = Shared<IndexMap<Key, Value>>;
/// Отображение Java: ключ хеширования -> (исходный ключ, значение).
pub type MapRef = Shared<IndexMap<Key, (Value, Value)>>;

/// Поля объекта по именам.
pub type Fields = IndexMap<Rc<str>, Value>;

/// Значение времени выполнения.
#[derive(Clone, Default)]
pub enum Value {
    /// `null`.
    #[default]
    Null,
    /// Неизвестное значение.
    Unk,
    /// Признак «не найдено» (отличается от `null`).
    NotFound,
    /// Логическое значение.
    Bool(bool),
    /// Целое число.
    Int(i64),
    /// Число с плавающей точкой.
    Float(f64),
    /// `BigDecimal`.
    Dec(Dec),
    /// Строка; `json` — исходный объект строки JSON (`writeValueAsString`).
    Str(Rc<str>, Option<Rc<Value>>),
    /// Объект проекта.
    Obj(ObjRef),
    /// Константа перечисления проекта.
    Enum(EnumRef),
    /// Библиотечный объект.
    Lib(LibRef),
    /// Список (а также поток и ленивая коллекция).
    List(ListRef),
    /// Множество.
    Set(SetRef),
    /// Отображение.
    Map(MapRef),
    /// `Optional`.
    Opt(Rc<Value>),
    /// `java.util.Date`.
    Date(Shared<NaiveDateTime>),
    /// `java.util.Calendar`.
    Cal(Shared<NaiveDateTime>),
    /// Лямбда.
    Lambda(Rc<JLambda>),
    /// Ссылка на метод.
    MethodRef(Rc<JMethodRef>),
    /// Литерал класса.
    Class(Rc<JClass>),
    /// Имя класса в позиции выражения.
    Static(Rc<StaticRef>),
    /// Бин репозитория Spring Data.
    Repo(Rc<RepoProxy>),
    /// Описание класса (внутреннее значение полей библиотечных объектов).
    Ci(CiRef),
}

/// Вид списка.
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum ListKind {
    /// Обычный список.
    Plain,
    /// Поток `Stream`.
    Stream,
}

/// Ленивая коллекция сущности: таблица и владелец.
pub struct Lazy {
    /// Вершина таблицы коллекции в скелете.
    pub node: Option<Rc<str>>,
    /// Сущность-владелец.
    pub owner: ObjRef,
}

/// Список Java.
pub struct JList {
    /// Элементы.
    pub items: Vec<Value>,
    /// Вид списка.
    pub kind: ListKind,
    /// Ленивая загрузка (до первого обращения).
    pub lazy: Option<Lazy>,
}

impl JList {
    /// Создаёт обычный список.
    pub fn new(items: Vec<Value>) -> Self {
        JList {
            items,
            kind: ListKind::Plain,
            lazy: None,
        }
    }
}

/// Метки объекта: внешний объект, окружение, загрузчик.
#[derive(Clone, Default)]
pub struct Tag {
    /// Внешний объект (для внутренних и анонимных классов).
    pub outer: Option<Value>,
    /// Окружение анонимного класса.
    pub env: Option<FrameRef>,
    /// Библиотечный суперкласс анонимного класса.
    pub lib: Option<Rc<str>>,
    /// Метод, загрузивший сущность (`Some(None)` — загружена вне метода).
    pub loader: Option<Option<MiRef>>,
}

/// Экземпляр класса проекта.
pub struct JObj {
    /// Класс.
    pub cls: CiRef,
    /// Поля.
    pub f: Fields,
    /// Метки.
    pub tag: Option<Tag>,
}

/// Константа перечисления.
pub struct JEnum {
    /// Класс (для константы с телом — анонимный подкласс).
    pub cls: CiRef,
    /// Имя.
    pub name: Rc<str>,
    /// Порядковый номер.
    pub ordinal: i64,
    /// Поля.
    pub f: Fields,
}

/// Объект библиотечного класса без своей логики.
pub struct LibObj {
    /// Вид объекта.
    pub kind: Rc<str>,
    /// Поля.
    pub f: IndexMap<Rc<str>, Value>,
}

/// Лямбда с захваченным окружением.
pub struct JLambda {
    /// Параметры.
    pub params: Rc<Vec<Rc<str>>>,
    /// Тело.
    pub body: LambdaBody,
    /// Окружение.
    pub env: FrameRef,
    /// Кадр создания.
    pub frame: FrameRef,
}

/// Ссылка на метод.
pub struct JMethodRef {
    /// Получатель или имя типа.
    pub obj: Value,
    /// Имя метода.
    pub name: Rc<str>,
}

/// Литерал класса.
pub struct JClass {
    /// Класс проекта.
    pub ci: Option<CiRef>,
    /// Имя.
    pub name: Rc<str>,
}

/// Имя класса в позиции выражения.
pub struct StaticRef {
    /// Класс проекта (`None` — библиотечный).
    pub ci: Option<CiRef>,
    /// Имя, как в коде.
    pub name: Rc<str>,
}

/// Ключ хеш-таблицы Java (как ключ словаря Python).
#[derive(Clone, PartialEq, Eq, Hash, Debug)]
pub enum Key {
    /// `null`.
    Null,
    /// Число (логические значения и целые дробные совпадают с целыми).
    Int(i64),
    /// Дробное число.
    Float(u64),
    /// Строка.
    Str(Rc<str>),
    /// Объект по идентичности.
    Id(usize),
    /// Неизвестное значение.
    Unk,
}

/// Создаёт строковое значение.
pub fn s(v: &str) -> Value {
    Value::Str(Rc::from(v), None)
}

/// Создаёт строковое значение из `Rc<str>`.
pub fn rs(v: Rc<str>) -> Value {
    Value::Str(v, None)
}

/// Создаёт новый объект-список.
pub fn new_list(items: Vec<Value>) -> Value {
    Value::List(shared(JList::new(items)))
}

/// Создаёт новый поток.
pub fn new_stream(items: Vec<Value>) -> Value {
    Value::List(shared(JList {
        items,
        kind: ListKind::Stream,
        lazy: None,
    }))
}

/// Создаёт пустое отображение.
pub fn new_map() -> Value {
    Value::Map(shared(IndexMap::new()))
}

/// Создаёт пустое множество.
pub fn new_set() -> Value {
    Value::Set(shared(IndexMap::new()))
}

/// Создаёт библиотечный объект с полями.
pub fn lib(kind: &str, fields: Vec<(&str, Value)>) -> Value {
    let mut f = IndexMap::new();
    for (k, v) in fields {
        f.insert(Rc::from(k), v);
    }
    Value::Lib(shared(LibObj {
        kind: Rc::from(kind),
        f,
    }))
}

/// Создаёт объект статуса HTTP.
pub fn http_status(name: &str, code: i64) -> Value {
    lib("HttpStatus", vec![("name", s(name)), ("code", Value::Int(code))])
}

impl Value {
    /// Проверяет, что значение — `null`.
    pub fn is_null(&self) -> bool {
        matches!(self, Value::Null)
    }

    /// Проверяет, что значение неизвестно.
    pub fn is_unk(&self) -> bool {
        matches!(self, Value::Unk)
    }

    /// Строка, если значение — строка.
    pub fn as_str(&self) -> Option<&str> {
        match self {
            Value::Str(v, _) => Some(v),
            _ => None,
        }
    }

    /// Целое, если значение — целое или логическое (как `int` в Python).
    pub fn as_int(&self) -> Option<i64> {
        match self {
            Value::Int(v) => Some(*v),
            Value::Bool(b) => Some(*b as i64),
            _ => None,
        }
    }

    /// Проверяет `isinstance(v, int)` (логические значения тоже целые).
    pub fn is_int(&self) -> bool {
        matches!(self, Value::Int(_) | Value::Bool(_))
    }

    /// Проверяет, что значение — число Java (не логическое).
    pub fn is_num(&self) -> bool {
        matches!(self, Value::Int(_) | Value::Float(_) | Value::Dec(_))
    }

    /// Проверяет `isinstance(v, list)`.
    pub fn is_list(&self) -> bool {
        matches!(self, Value::List(_))
    }

    /// Проверяет `isinstance(v, dict)` (множество в исходной модели — словарь).
    pub fn is_dict(&self) -> bool {
        matches!(self, Value::Map(_) | Value::Set(_))
    }

    /// Вид библиотечного объекта.
    pub fn lib_kind(&self) -> Option<Rc<str>> {
        match self {
            Value::Lib(o) => Some(o.borrow().kind.clone()),
            _ => None,
        }
    }

    /// Поле библиотечного объекта (`None`, если его нет).
    pub fn lib_get(&self, key: &str) -> Option<Value> {
        match self {
            Value::Lib(o) => o.borrow().f.get(key).cloned(),
            _ => None,
        }
    }

    /// Поле библиотечного объекта или `null`.
    pub fn lib_field(&self, key: &str) -> Value {
        self.lib_get(key).unwrap_or(Value::Null)
    }

    /// Адрес объекта для сравнения по идентичности.
    pub fn ptr(&self) -> Option<usize> {
        Some(match self {
            Value::Obj(o) => Rc::as_ptr(o) as *const u8 as usize,
            Value::Enum(o) => Rc::as_ptr(o) as *const u8 as usize,
            Value::Lib(o) => Rc::as_ptr(o) as *const u8 as usize,
            Value::List(o) => Rc::as_ptr(o) as *const u8 as usize,
            Value::Set(o) => Rc::as_ptr(o) as *const u8 as usize,
            Value::Map(o) => Rc::as_ptr(o) as *const u8 as usize,
            Value::Opt(o) => Rc::as_ptr(o) as *const u8 as usize,
            Value::Date(o) => Rc::as_ptr(o) as *const u8 as usize,
            Value::Cal(o) => Rc::as_ptr(o) as *const u8 as usize,
            Value::Lambda(o) => Rc::as_ptr(o) as *const u8 as usize,
            Value::MethodRef(o) => Rc::as_ptr(o) as *const u8 as usize,
            Value::Class(o) => Rc::as_ptr(o) as *const u8 as usize,
            Value::Static(o) => Rc::as_ptr(o) as *const u8 as usize,
            Value::Repo(o) => Rc::as_ptr(o) as *const u8 as usize,
            Value::Ci(o) => Rc::as_ptr(o) as *const u8 as usize,
            _ => return None,
        })
    }

    /// Проверяет `a is b` из Python.
    pub fn is(&self, other: &Value) -> bool {
        match (self, other) {
            (Value::Null, Value::Null)
            | (Value::Unk, Value::Unk)
            | (Value::NotFound, Value::NotFound) => true,
            (Value::Bool(a), Value::Bool(b)) => a == b,
            (Value::Int(a), Value::Int(b)) => a == b && (-5..=256).contains(a),
            (Value::Str(a, _), Value::Str(b, _)) => Rc::ptr_eq(a, b),
            _ => match (self.ptr(), other.ptr()) {
                (Some(a), Some(b)) => a == b,
                _ => false,
            },
        }
    }

    /// Ключ хеш-таблицы для значения.
    pub fn key(&self) -> Key {
        match self {
            Value::Null => Key::Null,
            Value::Unk => Key::Unk,
            Value::Bool(b) => Key::Int(*b as i64),
            Value::Int(v) => Key::Int(*v),
            Value::Float(f) => {
                if f.fract() == 0.0 && f.abs() < 9.0e15 {
                    Key::Int(*f as i64)
                } else {
                    Key::Float(f.to_bits())
                }
            }
            Value::Dec(d) => match d.to_f64() {
                f if f.fract() == 0.0 && f.abs() < 9.0e15 => Key::Int(f as i64),
                f => Key::Float(f.to_bits()),
            },
            Value::Str(v, _) => Key::Str(v.clone()),
            other => Key::Id(other.ptr().unwrap_or(0)),
        }
    }

    /// Имя типа значения, как `type(v).__name__` в Python (для журнала).
    pub fn type_name(&self) -> &'static str {
        match self {
            Value::Null => "NoneType",
            Value::Unk => "_Unknown",
            Value::NotFound => "_NotFound",
            Value::Bool(_) => "bool",
            Value::Int(_) => "int",
            Value::Float(_) => "float",
            Value::Dec(_) => "Decimal",
            Value::Str(..) => "str",
            Value::Obj(_) => "JObj",
            Value::Enum(_) => "JEnum",
            Value::Lib(_) => "LibObj",
            Value::List(_) => "JList",
            Value::Set(_) => "JSet",
            Value::Map(_) => "JMap",
            Value::Opt(_) => "JOpt",
            Value::Date(_) => "JDate",
            Value::Cal(_) => "JCal",
            Value::Lambda(_) => "JLambda",
            Value::MethodRef(_) => "JMethodRef",
            Value::Class(_) => "JClass",
            Value::Static(_) => "StaticRef",
            Value::Repo(_) => "RepoProxy",
            Value::Ci(_) => "ClassInfo",
        }
    }
}

/// Сравнивает значения как `==` в Python для простых значений.
pub fn py_eq(a: &Value, b: &Value) -> bool {
    match (a, b) {
        (Value::Null, Value::Null) | (Value::Unk, Value::Unk) => true,
        (Value::Str(x, _), Value::Str(y, _)) => x == y,
        (Value::Dec(x), Value::Dec(y)) => x.cmp_dec(y) == std::cmp::Ordering::Equal,
        (Value::Dec(x), y) | (y, Value::Dec(x)) if y.is_num() || y.is_int() => {
            num_f64(y).is_some_and(|v| x.to_f64() == v)
        }
        _ if (a.is_int() || matches!(a, Value::Float(_)))
            && (b.is_int() || matches!(b, Value::Float(_))) =>
        {
            match (a.as_int(), b.as_int()) {
                (Some(x), Some(y)) => x == y,
                _ => num_f64(a) == num_f64(b),
            }
        }
        (Value::Date(x), Value::Date(y)) => Rc::ptr_eq(x, y),
        (Value::List(x), Value::List(y)) => {
            if Rc::ptr_eq(x, y) {
                return true;
            }
            let (x, y) = (x.borrow(), y.borrow());
            x.items.len() == y.items.len()
                && x.items.iter().zip(y.items.iter()).all(|(p, q)| py_eq(p, q))
        }
        _ => a.is(b),
    }
}

/// Число как `f64`, если значение числовое (или логическое).
pub fn num_f64(v: &Value) -> Option<f64> {
    match v {
        Value::Int(i) => Some(*i as f64),
        Value::Bool(b) => Some(*b as i64 as f64),
        Value::Float(f) => Some(*f),
        Value::Dec(d) => Some(d.to_f64()),
        _ => None,
    }
}

/// Сравнивает числа или строки как `<` в Python; `None` — несравнимы.
pub fn py_cmp(a: &Value, b: &Value) -> Option<std::cmp::Ordering> {
    match (a, b) {
        (Value::Str(x, _), Value::Str(y, _)) => Some(x.as_ref().cmp(y.as_ref())),
        (Value::Dec(x), Value::Dec(y)) => Some(x.cmp_dec(y)),
        (Value::Date(x), Value::Date(y)) => Some(x.borrow().cmp(&y.borrow())),
        _ => match (a.as_int(), b.as_int()) {
            (Some(x), Some(y)) => Some(x.cmp(&y)),
            _ => match (num_f64(a), num_f64(b)) {
                (Some(x), Some(y)) => x.partial_cmp(&y),
                _ => None,
            },
        },
    }
}

/// Значение по умолчанию для типа (`int` -> 0, ссылка -> `null`).
pub fn prim_default(t: &str) -> Value {
    match t {
        "int" | "long" | "short" | "byte" => Value::Int(0),
        "char" => s("\0"),
        "float" | "double" => Value::Float(0.0),
        "boolean" => Value::Bool(false),
        _ => Value::Null,
    }
}

/// Проверяет, что тип — примитив с значением по умолчанию.
pub fn is_prim_default(t: &str) -> bool {
    matches!(
        t,
        "int" | "long" | "short" | "byte" | "char" | "float" | "double" | "boolean"
    )
}

/// Повторяет `repr(float)` Python.
pub fn py_float_repr(x: f64) -> String {
    if x.is_nan() {
        return "nan".to_string();
    }
    if x.is_infinite() {
        return if x > 0.0 { "inf" } else { "-inf" }.to_string();
    }
    if x == 0.0 {
        return if x.is_sign_negative() { "-0.0" } else { "0.0" }.to_string();
    }
    let shortest = format!("{x:e}");
    let (mant, exp) = shortest.split_once('e').unwrap_or((&shortest, "0"));
    let exp: i32 = exp.parse().unwrap_or(0);
    let neg = mant.starts_with('-');
    let digits: String = mant.chars().filter(|c| c.is_ascii_digit()).collect();
    let mut out = String::new();
    if neg {
        out.push('-');
    }
    if (-4..16).contains(&exp) {
        let point = exp + 1;
        if point <= 0 {
            out.push_str("0.");
            for _ in 0..(-point) {
                out.push('0');
            }
            out.push_str(&digits);
        } else if point as usize >= digits.len() {
            out.push_str(&digits);
            for _ in 0..(point as usize - digits.len()) {
                out.push('0');
            }
            out.push_str(".0");
        } else {
            out.push_str(&digits[..point as usize]);
            out.push('.');
            out.push_str(&digits[point as usize..]);
        }
    } else {
        out.push_str(&digits[..1]);
        if digits.len() > 1 {
            out.push('.');
            out.push_str(&digits[1..]);
        }
        let _ = write!(out, "e{}{:02}", if exp < 0 { '-' } else { '+' }, exp.abs());
    }
    out
}
