//! Модель проекта: скелет и разобранные исходники.
//!
//! Из скелета берутся точные ID методов, мест вызова и таблиц, из
//! исходников — классы, методы и поля. Модуль также разрешает имена типов
//! так, как это делает компилятор Java: вложенные классы, импорты, пакет,
//! модуль ts-common.

use std::cell::{OnceCell, RefCell};
use std::collections::{HashMap, HashSet};
use std::io::Read;
use std::rc::Rc;

use indexmap::IndexMap;
use serde_json::Value as Json;

use crate::jparse::{self, ClassDecl, EnumConst, Expr, Import, LambdaBody, MethodDecl, Stmt, E, S};

/// Ссылка на класс.
pub type CiRef = Rc<ClassInfo>;
/// Ссылка на метод.
pub type MiRef = Rc<MethodInfo>;
/// Ссылка на поле.
pub type FiRef = Rc<FieldInfo>;

/// Аннотации: последний сегмент имени -> аргументы исходным текстом.
pub type Annots = IndexMap<String, String>;

fn annots_of(list: &[jparse::Annot]) -> Annots {
    let mut out = IndexMap::new();
    for a in list {
        let name = a.name.rsplit('.').next().unwrap_or(&a.name).to_string();
        out.insert(name, a.args.clone());
    }
    out
}

/// Читает JSON-файл, в том числе сжатый gzip (`.gz`).
pub fn load_json(path: &str) -> Result<Json, String> {
    let bytes = std::fs::read(path).map_err(|e| format!("{path}: {e}"))?;
    let text = if path.ends_with(".gz") {
        let mut s = String::new();
        flate2::read::GzDecoder::new(&bytes[..])
            .read_to_string(&mut s)
            .map_err(|e| format!("{path}: {e}"))?;
        s
    } else {
        String::from_utf8_lossy(&bytes).into_owned()
    };
    serde_json::from_str(&text).map_err(|e| format!("{path}: {e}"))
}

/// Убирает параметры типа из имени: `List<String>[]` даёт `List[]`.
pub fn strip_generics(t: &str) -> String {
    let mut out = String::new();
    let mut depth = 0i32;
    for ch in t.chars() {
        if ch == '<' {
            depth += 1;
        } else if ch == '>' {
            depth -= 1;
        } else if depth == 0 {
            out.push(ch);
        }
    }
    out.trim().to_string()
}

/// Возвращает аргументы типа верхнего уровня: `Response<List<X>>` -> `List<X>`.
pub fn type_args(t: &str) -> Vec<String> {
    let Some(i) = t.find('<') else {
        return Vec::new();
    };
    if !t.ends_with('>') {
        return Vec::new();
    }
    let inner = &t[i + 1..t.len() - 1];
    let mut res = Vec::new();
    let mut depth = 0i32;
    let mut cur = String::new();
    for ch in inner.chars() {
        if ch == '<' {
            depth += 1;
        } else if ch == '>' {
            depth -= 1;
        }
        if ch == ',' && depth == 0 {
            res.push(cur.trim().to_string());
            cur.clear();
        } else {
            cur.push(ch);
        }
    }
    if !cur.trim().is_empty() {
        res.push(cur.trim().to_string());
    }
    res
}

/// Последний сегмент имени через точку.
pub fn short_name(t: &str) -> &str {
    t.rsplit('.').next().unwrap_or(t)
}

/// Поле класса.
pub struct FieldInfo {
    /// Имя.
    pub name: Rc<str>,
    /// Тип.
    pub ty: Rc<str>,
    /// Инициализатор.
    pub init: Option<E>,
    /// Статическое ли поле.
    pub is_static: bool,
    /// Финальное ли поле.
    pub is_final: bool,
    /// Аннотации.
    pub annots: Annots,
    /// Класс-владелец.
    pub cls: OnceCell<CiRef>,
}

impl FieldInfo {
    /// Класс-владелец.
    pub fn cls(&self) -> &CiRef {
        self.cls.get().expect("класс поля")
    }
}

/// Параметр метода: тип, имя, аннотации.
pub struct ParamInfo {
    /// Тип.
    pub ty: Rc<str>,
    /// Имя.
    pub name: Rc<str>,
    /// Аннотации.
    pub annots: Annots,
}

/// Метод или конструктор.
pub struct MethodInfo {
    /// Имя.
    pub name: Rc<str>,
    /// Объявление.
    pub decl: Rc<MethodDecl>,
    /// Класс-владелец.
    pub cls: OnceCell<CiRef>,
    /// ID метода в скелете.
    pub id: RefCell<Option<Rc<str>>>,
    /// Параметры.
    pub params: Vec<ParamInfo>,
    /// Статический ли метод.
    pub is_static: bool,
    /// Без тела ли метод.
    pub is_abstract: bool,
    /// Конструктор ли это.
    pub ctor: bool,
    /// Аннотации.
    pub annots: Annots,
    /// Возвращаемый тип.
    pub ret: Option<Rc<str>>,
    /// Переменное ли число аргументов.
    pub varargs: bool,
    called: RefCell<Option<Rc<HashSet<Rc<str>>>>>,
    has_stmts: bool,
}

impl MethodInfo {
    fn new(md: &Rc<MethodDecl>) -> Self {
        let has_stmts = match &md.body {
            Some(b) => match &**b {
                Stmt::Block { stmts, .. } => stmts.iter().any(|s| !matches!(**s, Stmt::Empty)),
                _ => true,
            },
            None => false,
        };
        MethodInfo {
            name: md.name.clone(),
            decl: md.clone(),
            cls: OnceCell::new(),
            id: RefCell::new(None),
            params: md
                .params
                .iter()
                .map(|p| ParamInfo {
                    ty: p.ty.clone(),
                    name: p.name.clone(),
                    annots: annots_of(&p.annots),
                })
                .collect(),
            is_static: md.mods.contains("static"),
            is_abstract: md.body.is_none(),
            ctor: md.ctor,
            annots: annots_of(&md.annots),
            ret: md.ret.clone(),
            varargs: md.params.last().is_some_and(|p| p.varargs),
            called: RefCell::new(None),
            has_stmts,
        }
    }

    /// Класс-владелец.
    pub fn cls(&self) -> &CiRef {
        self.cls.get().expect("класс метода")
    }

    /// ID метода в скелете.
    pub fn id(&self) -> Option<Rc<str>> {
        self.id.borrow().clone()
    }

    /// Проверяет, что у метода есть тело с операторами.
    pub fn has_stmts(&self) -> bool {
        self.has_stmts
    }

    /// Возвращает простые имена методов, вызываемых в исходнике метода.
    pub fn called_names(&self) -> Rc<HashSet<Rc<str>>> {
        if let Some(c) = &*self.called.borrow() {
            return c.clone();
        }
        let mut out = HashSet::new();
        if let Some(b) = &self.decl.body {
            walk_stmt(b, &mut out, 0);
        }
        let rc = Rc::new(out);
        *self.called.borrow_mut() = Some(rc.clone());
        rc
    }
}

fn walk_class(c: &ClassDecl, out: &mut HashSet<Rc<str>>, depth: usize) {
    if depth > 200 {
        return;
    }
    for f in &c.fields {
        if let Some(i) = &f.init {
            walk_expr(i, out, depth + 3);
        }
    }
    for m in &c.methods {
        if let Some(b) = &m.body {
            walk_stmt(b, out, depth + 3);
        }
    }
    for (_, b) in &c.inits {
        walk_stmt(b, out, depth + 4);
    }
    for i in &c.inner {
        walk_class(i, out, depth + 2);
    }
    for EnumConst { args, body, .. } in &c.enums {
        for a in args {
            walk_expr(a, out, depth + 4);
        }
        if let Some(b) = body {
            walk_class(b, out, depth + 3);
        }
    }
}

fn walk_expr(e: &E, out: &mut HashSet<Rc<str>>, depth: usize) {
    if depth > 200 {
        return;
    }
    let d = depth + 1;
    match &**e {
        Expr::Call { obj, name, args, .. } => {
            out.insert(name.clone());
            if let Some(o) = obj {
                walk_expr(o, out, d);
            }
            for a in args {
                walk_expr(a, out, d + 1);
            }
        }
        Expr::FieldAcc { obj, .. } => walk_expr(obj, out, d),
        Expr::New { args, body, .. } => {
            for a in args {
                walk_expr(a, out, d + 1);
            }
            if let Some(b) = body {
                walk_class(b, out, d);
            }
        }
        Expr::NewArray { dims, init, .. } => {
            for x in dims.iter().flatten() {
                walk_expr(x, out, d + 1);
            }
            for x in init.iter().flatten() {
                walk_expr(x, out, d + 2);
            }
        }
        Expr::ArrayLit(el) => {
            for x in el {
                walk_expr(x, out, d + 1);
            }
        }
        Expr::Index { obj, idx } => {
            walk_expr(obj, out, d);
            walk_expr(idx, out, d);
        }
        Expr::Unary { e, .. } | Expr::Postfix { e, .. } | Expr::Cast { e, .. } => {
            walk_expr(e, out, d)
        }
        Expr::InstanceOf { e, .. } => walk_expr(e, out, d),
        Expr::Binary { l, r, .. } => {
            walk_expr(l, out, d);
            walk_expr(r, out, d);
        }
        Expr::Assign { target, value, .. } => {
            walk_expr(target, out, d);
            walk_expr(value, out, d);
        }
        Expr::Cond { c, a, b } => {
            walk_expr(c, out, d);
            walk_expr(a, out, d);
            walk_expr(b, out, d);
        }
        Expr::Lambda { body, .. } => match body {
            LambdaBody::Block(s) => walk_stmt(s, out, d),
            LambdaBody::Expr(x) => walk_expr(x, out, d),
        },
        Expr::MethodRef { obj, .. } => walk_expr(obj, out, d),
        Expr::ClassLit(jparse::ClassLitTy::Expr(x)) => walk_expr(x, out, d),
        Expr::SwitchExpr(s) => walk_stmt(s, out, d),
        _ => {}
    }
}

fn walk_stmt(s: &S, out: &mut HashSet<Rc<str>>, depth: usize) {
    if depth > 200 {
        return;
    }
    let d = depth + 1;
    match &**s {
        Stmt::Block { stmts, .. } => {
            for x in stmts {
                walk_stmt(x, out, d + 1);
            }
        }
        Stmt::LocalVar { decls, .. } => {
            for (_, i) in decls {
                if let Some(i) = i {
                    walk_expr(i, out, d + 2);
                }
            }
        }
        Stmt::ExprStmt { e, .. } | Stmt::Throw { e, .. } => walk_expr(e, out, d),
        Stmt::If { c, then, els, .. } => {
            walk_expr(c, out, d);
            walk_stmt(then, out, d);
            if let Some(e) = els {
                walk_stmt(e, out, d);
            }
        }
        Stmt::While { c, body, .. } | Stmt::DoWhile { body, c, .. } => {
            walk_expr(c, out, d);
            walk_stmt(body, out, d);
        }
        Stmt::For { init, c, update, body, .. } => {
            for x in init {
                walk_stmt(x, out, d + 1);
            }
            if let Some(c) = c {
                walk_expr(c, out, d);
            }
            for u in update {
                walk_expr(u, out, d + 1);
            }
            walk_stmt(body, out, d);
        }
        Stmt::ForEach { iter, body, .. } => {
            walk_expr(iter, out, d);
            walk_stmt(body, out, d);
        }
        Stmt::Return { e, .. } => {
            if let Some(e) = e {
                walk_expr(e, out, d);
            }
        }
        Stmt::Try { res, body, catches, fin, .. } => {
            for (_, e) in res {
                walk_expr(e, out, d + 2);
            }
            walk_stmt(body, out, d);
            for (_, _, b) in catches {
                walk_stmt(b, out, d + 2);
            }
            if let Some(f) = fin {
                walk_stmt(f, out, d);
            }
        }
        Stmt::Switch { e, cases, .. } => {
            walk_expr(e, out, d);
            for (labs, sts) in cases {
                for l in labs.iter().flatten() {
                    walk_expr(l, out, d + 3);
                }
                for x in sts {
                    walk_stmt(x, out, d + 3);
                }
            }
        }
        Stmt::Sync { e, body } => {
            walk_expr(e, out, d);
            walk_stmt(body, out, d);
        }
        Stmt::Labeled { stmt, .. } => walk_stmt(stmt, out, d),
        Stmt::LocalClass(c) => walk_class(c, out, d),
        Stmt::Assert { c, m } => {
            walk_expr(c, out, d);
            if let Some(m) = m {
                walk_expr(m, out, d);
            }
        }
        _ => {}
    }
}

/// Кэш суперкласса.
enum SuperCache {
    Unknown,
    InProgress,
    Known(Option<CiRef>),
}

/// Класс, интерфейс или перечисление проекта со своими членами.
pub struct ClassInfo {
    /// Объявление.
    pub decl: Rc<ClassDecl>,
    /// Модуль.
    pub module: Rc<str>,
    /// Файл.
    pub file: Rc<str>,
    /// Пакет.
    pub pkg: Rc<str>,
    /// Импорты файла.
    pub imports: Rc<Vec<Import>>,
    /// Простое имя.
    pub name: Rc<str>,
    /// Полное имя.
    pub fqn: Rc<str>,
    /// Вид: class, interface, enum, annotation.
    pub kind: Rc<str>,
    /// Внешний класс.
    pub outer: Option<CiRef>,
    /// Аннотации.
    pub annots: Annots,
    /// Поля.
    pub fields: IndexMap<Rc<str>, FiRef>,
    /// Методы по именам.
    pub methods: IndexMap<Rc<str>, Vec<MiRef>>,
    /// Конструкторы.
    pub ctors: Vec<MiRef>,
    /// Вложенные классы.
    pub inner: RefCell<IndexMap<Rc<str>, CiRef>>,
    /// Имена констант перечисления.
    pub enum_names: Vec<Rc<str>>,
    /// Имя суперкласса.
    pub super_name: Option<Rc<str>>,
    /// Имена интерфейсов.
    pub iface_names: Vec<Rc<str>>,
    /// ID типа.
    pub id: String,
    /// Анонимный ли класс.
    pub anon: bool,
    sup: RefCell<SuperCache>,
    ifaces: RefCell<Option<Vec<CiRef>>>,
}

impl ClassInfo {
    /// Строит описание класса по объявлению из исходного файла.
    pub fn build(
        decl: Rc<ClassDecl>,
        module: Rc<str>,
        file: Rc<str>,
        pkg: Rc<str>,
        imports: Rc<Vec<Import>>,
        outer: Option<CiRef>,
        super_override: Option<Option<Rc<str>>>,
        anon_override: Option<bool>,
    ) -> CiRef {
        let mut fields = IndexMap::new();
        for fd in &decl.fields {
            fields.insert(
                fd.name.clone(),
                Rc::new(FieldInfo {
                    name: fd.name.clone(),
                    ty: fd.ty.clone(),
                    init: fd.init.clone(),
                    is_static: fd.mods.contains("static") || decl.kind == "interface",
                    is_final: fd.mods.contains("final"),
                    annots: annots_of(&fd.annots),
                    cls: OnceCell::new(),
                }),
            );
        }
        let mut methods: IndexMap<Rc<str>, Vec<MiRef>> = IndexMap::new();
        let mut ctors = Vec::new();
        for md in &decl.methods {
            let mi = Rc::new(MethodInfo::new(md));
            if md.ctor {
                ctors.push(mi);
            } else {
                methods.entry(md.name.clone()).or_default().push(mi);
            }
        }
        let ci = Rc::new(ClassInfo {
            module: module.clone(),
            file,
            pkg,
            imports,
            name: Rc::from(decl.name.as_str()),
            fqn: Rc::from(decl.fqn.as_str()),
            kind: Rc::from(decl.kind.as_str()),
            outer,
            annots: annots_of(&decl.annots),
            fields,
            methods,
            ctors,
            inner: RefCell::new(IndexMap::new()),
            enum_names: decl.enums.iter().map(|e| e.name.clone()).collect(),
            super_name: super_override
                .unwrap_or_else(|| decl.ext.as_deref().map(Rc::from)),
            iface_names: decl.impls.iter().map(|s| Rc::from(s.as_str())).collect(),
            id: format!("type:{}:{}", module, decl.fqn),
            anon: anon_override.unwrap_or(decl.anon),
            sup: RefCell::new(SuperCache::Unknown),
            ifaces: RefCell::new(None),
            decl,
        });
        for f in ci.fields.values() {
            let _ = f.cls.set(ci.clone());
        }
        for ms in ci.methods.values() {
            for m in ms {
                let _ = m.cls.set(ci.clone());
            }
        }
        for m in &ci.ctors {
            let _ = m.cls.set(ci.clone());
        }
        ci
    }

    /// Все методы и конструкторы класса (методы, затем конструкторы).
    pub fn all_methods(&self) -> Vec<MiRef> {
        let mut out: Vec<MiRef> = self.methods.values().flatten().cloned().collect();
        out.extend(self.ctors.iter().cloned());
        out
    }

    /// Проверяет, есть ли у класса аннотация.
    pub fn has_annot(&self, name: &str) -> bool {
        self.annots.contains_key(name)
    }
}

/// Сравнивает классы по идентичности.
pub fn same(a: &CiRef, b: &CiRef) -> bool {
    Rc::ptr_eq(a, b)
}

/// Адрес класса (ключ словарей).
pub fn ci_key(c: &CiRef) -> usize {
    Rc::as_ptr(c) as usize
}

/// Таблица из скелета.
pub struct TableNode {
    /// Имя таблицы.
    pub name: String,
    /// Схема (база данных сервиса).
    pub schema: String,
}

/// Проект: скелет, классы всех модулей и индексы для поиска.
pub struct Project {
    /// Имя проекта.
    pub project: String,
    /// Поле `context` скелета.
    pub context: Json,
    /// ID всех методов скелета.
    pub method_nodes: HashSet<Rc<str>>,
    /// Классы: (модуль, полное имя) -> класс.
    pub classes: IndexMap<(Rc<str>, Rc<str>), CiRef>,
    by_module_simple: HashMap<(Rc<str>, Rc<str>), Vec<CiRef>>,
    /// Методы по ID скелета.
    pub methods_by_id: HashMap<Rc<str>, MiRef>,
    /// Файл -> (имя метода, строка начала) -> ID метода.
    pub method_by_start: HashMap<Rc<str>, HashMap<(Rc<str>, i64), Rc<str>>>,
    /// (файл, строка, колонка) -> ID места вызова.
    pub cs_at: HashMap<(Rc<str>, i64, i64), Rc<str>>,
    /// Место вызова -> вид ребра -> цели.
    pub cs_edges: HashMap<Rc<str>, HashMap<String, Vec<Rc<str>>>>,
    /// Таблицы скелета по ID.
    pub tables: IndexMap<Rc<str>, TableNode>,
    /// Файл класса сущности -> ID таблиц.
    pub tables_by_file: HashMap<String, Vec<Rc<str>>>,
    /// Модули проекта.
    pub modules: HashSet<String>,
}

fn js(v: &Json, k: &str) -> String {
    v.get(k).and_then(|x| x.as_str()).unwrap_or("").to_string()
}

fn ji(v: &Json, k: &str) -> i64 {
    v.get(k).and_then(|x| x.as_i64()).unwrap_or(0)
}

impl Project {
    /// Читает скелет и разбирает исходники Java из каталога `root`.
    pub fn load(skeleton_path: &str, root: &str) -> Result<Project, String> {
        let sk = load_json(skeleton_path)?;
        let nodes = sk
            .get("nodes")
            .and_then(|n| n.as_object())
            .ok_or("в скелете нет nodes")?;
        let mut p = Project {
            project: js(&sk, "project"),
            context: sk.get("context").cloned().unwrap_or(Json::Null),
            method_nodes: HashSet::new(),
            classes: IndexMap::new(),
            by_module_simple: HashMap::new(),
            methods_by_id: HashMap::new(),
            method_by_start: HashMap::new(),
            cs_at: HashMap::new(),
            cs_edges: HashMap::new(),
            tables: IndexMap::new(),
            tables_by_file: HashMap::new(),
            modules: HashSet::new(),
        };
        let mut files = Vec::new();
        for (k, n) in nodes {
            match n.get("kind").and_then(|x| x.as_str()).unwrap_or("") {
                "file" => {
                    let path = js(n, "path");
                    if path.ends_with(".java") {
                        files.push((js(n, "module"), path));
                    }
                }
                "method" => {
                    let id: Rc<str> = Rc::from(k.as_str());
                    p.method_nodes.insert(id.clone());
                    p.method_by_start
                        .entry(Rc::from(js(n, "file").as_str()))
                        .or_default()
                        .insert((Rc::from(js(n, "name").as_str()), ji(n, "line")), id);
                }
                "call_site" => {
                    p.cs_at.insert(
                        (Rc::from(js(n, "file").as_str()), ji(n, "line"), ji(n, "col")),
                        Rc::from(k.as_str()),
                    );
                }
                "data_resource" => {
                    let id: Rc<str> = Rc::from(k.as_str());
                    if let Some(origins) = n.get("origin").and_then(|o| o.as_array()) {
                        for o in origins {
                            p.tables_by_file.entry(js(o, "file")).or_default().push(id.clone());
                        }
                    }
                    p.tables.insert(
                        id,
                        TableNode {
                            name: js(n, "name"),
                            schema: js(n, "schema"),
                        },
                    );
                }
                "module" => {
                    p.modules.insert(js(n, "name"));
                }
                _ => {}
            }
        }
        files.sort();
        for (module, path) in files {
            let pf = jparse::parse_file(&format!("{root}/{path}")).map_err(|e| e.0)?;
            let module: Rc<str> = Rc::from(module.as_str());
            let file: Rc<str> = Rc::from(path.as_str());
            let pkg: Rc<str> = Rc::from(pf.pkg.as_str());
            for t in &pf.types {
                p.register(t.clone(), None, &module, &file, &pkg, &pf.imports);
            }
        }
        if let Some(edges) = sk.get("edges").and_then(|e| e.as_array()) {
            for e in edges {
                let t = js(e, "type");
                if matches!(
                    t.as_str(),
                    "calls"
                        | "runtime_dispatch"
                        | "remote_call"
                        | "data_access"
                        | "message_delivery"
                        | "creates"
                ) {
                    p.cs_edges
                        .entry(Rc::from(js(e, "source").as_str()))
                        .or_default()
                        .entry(t)
                        .or_default()
                        .push(Rc::from(js(e, "target").as_str()));
                }
            }
        }
        Ok(p)
    }

    fn register(
        &mut self,
        decl: Rc<ClassDecl>,
        outer: Option<CiRef>,
        module: &Rc<str>,
        file: &Rc<str>,
        pkg: &Rc<str>,
        imports: &Rc<Vec<Import>>,
    ) -> CiRef {
        let ci = ClassInfo::build(
            decl.clone(),
            module.clone(),
            file.clone(),
            pkg.clone(),
            imports.clone(),
            outer.clone(),
            None,
            None,
        );
        self.classes
            .insert((module.clone(), ci.fqn.clone()), ci.clone());
        self.by_module_simple
            .entry((module.clone(), ci.name.clone()))
            .or_default()
            .push(ci.clone());
        if let Some(o) = &outer {
            o.inner.borrow_mut().insert(ci.name.clone(), ci.clone());
        }
        let starts = self.method_by_start.get(file);
        for mi in ci.all_methods() {
            let id = starts.and_then(|s| s.get(&(mi.name.clone(), mi.decl.start)).cloned());
            if let Some(id) = &id {
                self.methods_by_id.insert(id.clone(), mi.clone());
            }
            *mi.id.borrow_mut() = id;
        }
        for inner in &decl.inner {
            self.register(inner.clone(), Some(ci.clone()), module, file, pkg, imports);
        }
        ci
    }

    // ------------------------------------------------------------ поиск типов

    /// Возвращает модули, классы которых видны коду модуля.
    pub fn visible_modules(module: &str) -> [&str; 2] {
        [module, "ts-common"]
    }

    fn class_at(&self, module: &str, fqn: &str) -> Option<CiRef> {
        self.classes
            .get(&(Rc::from(module), Rc::from(fqn)))
            .cloned()
    }

    /// Находит класс по полному имени, включая вложенные классы.
    pub fn lookup_fqn(&self, module: &str, fqn: &str) -> Option<CiRef> {
        for m in Self::visible_modules(module) {
            if let Some(ci) = self.class_at(m, fqn) {
                return Some(ci);
            }
        }
        let parts: Vec<&str> = fqn.split('.').collect();
        for i in (1..parts.len()).rev() {
            let outer = parts[..i].join(".");
            for m in Self::visible_modules(module) {
                if let Some(ci) = self.class_at(m, &outer) {
                    let mut cur = Some(ci);
                    for nm in &parts[i..] {
                        cur = cur.and_then(|c| c.inner.borrow().get(*nm).cloned());
                        if cur.is_none() {
                            break;
                        }
                    }
                    if cur.is_some() {
                        return cur;
                    }
                }
            }
        }
        None
    }

    /// Разрешает имя типа из кода в контексте класса `ctx`.
    ///
    /// Возвращает `None` для библиотечного типа.
    pub fn resolve(&self, tname: &str, ctx: &CiRef) -> Option<CiRef> {
        if tname.is_empty() {
            return None;
        }
        let base = strip_generics(tname).replace("[]", "").trim().to_string();
        if base.is_empty()
            || crate::values::is_prim_default(&base)
            || base == "void"
            || base == "?"
        {
            return None;
        }
        let module = ctx.module.clone();
        if base.contains('.') {
            if let Some(ci) = self.lookup_fqn(&module, &base) {
                return Some(ci);
            }
            let (first, rest) = base.split_once('.').unwrap_or((&base, ""));
            if let Some(c0) = self.resolve(first, ctx) {
                let mut cur = Some(c0);
                for nm in rest.split('.') {
                    cur = cur.and_then(|c| c.inner.borrow().get(nm).cloned());
                }
                return cur;
            }
            return None;
        }
        let mut c = Some(ctx.clone());
        while let Some(cc) = c {
            if *cc.name == *base && !cc.anon {
                return Some(cc);
            }
            if let Some(x) = cc.inner.borrow().get(base.as_str()) {
                return Some(x.clone());
            }
            let mut sc = self.super_of(&cc);
            while let Some(s) = sc {
                if let Some(x) = s.inner.borrow().get(base.as_str()) {
                    return Some(x.clone());
                }
                sc = self.super_of(&s);
            }
            c = cc.outer.clone();
        }
        let suffix = format!(".{base}");
        for (st, q) in ctx.imports.iter() {
            if !st && q.ends_with(&suffix) {
                return self.lookup_fqn(&module, q);
            }
        }
        if !ctx.pkg.is_empty() {
            if let Some(ci) = self.lookup_fqn(&module, &format!("{}.{}", ctx.pkg, base)) {
                return Some(ci);
            }
        } else {
            for m in Self::visible_modules(&module) {
                if let Some(list) = self.by_module_simple.get(&(Rc::from(m), Rc::from(base.as_str()))) {
                    for ci in list {
                        if ci.pkg.is_empty() {
                            return Some(ci.clone());
                        }
                    }
                }
            }
        }
        for (_, q) in ctx.imports.iter() {
            if let Some(head) = q.strip_suffix(".*") {
                if let Some(ci) = self.lookup_fqn(&module, &format!("{head}.{base}")) {
                    return Some(ci);
                }
            }
        }
        None
    }

    /// Возвращает суперкласс из проекта или `None` (с кэшем).
    pub fn super_of(&self, ci: &CiRef) -> Option<CiRef> {
        match &*ci.sup.borrow() {
            SuperCache::Known(v) => return v.clone(),
            SuperCache::InProgress => return None,
            SuperCache::Unknown => {}
        }
        *ci.sup.borrow_mut() = SuperCache::InProgress;
        let r = match (&ci.super_name, &*ci.kind) {
            (Some(n), k) if k != "interface" => {
                let ctx = ci.outer.clone().unwrap_or_else(|| ci.clone());
                self.resolve(n, &ctx)
            }
            _ => None,
        };
        let r = r.filter(|x| !Rc::ptr_eq(x, ci));
        *ci.sup.borrow_mut() = SuperCache::Known(r.clone());
        r
    }

    /// Возвращает интерфейсы проекта, которые реализует класс.
    pub fn ifaces_of(&self, ci: &CiRef) -> Vec<CiRef> {
        if let Some(v) = &*ci.ifaces.borrow() {
            return v.clone();
        }
        let mut res = Vec::new();
        for n in &ci.iface_names {
            let r = if !n.contains('.') {
                let ctx = ci.outer.clone().unwrap_or_else(|| ci.clone());
                self.resolve(n, &ctx)
            } else {
                self.resolve(n, ci)
            };
            if let Some(r) = r {
                if !Rc::ptr_eq(&r, ci) {
                    res.push(r);
                }
            }
        }
        *ci.ifaces.borrow_mut() = Some(res.clone());
        res
    }

    /// Возвращает все надтипы класса и сам класс, ближайшие первыми.
    pub fn supertypes(&self, ci: &CiRef) -> Vec<CiRef> {
        let mut out = Vec::new();
        let mut seen = HashSet::new();
        let mut st = std::collections::VecDeque::from([ci.clone()]);
        while let Some(c) = st.pop_front() {
            if !seen.insert(ci_key(&c)) {
                continue;
            }
            out.push(c.clone());
            if let Some(s) = self.super_of(&c) {
                st.push_back(s);
            }
            st.extend(self.ifaces_of(&c));
        }
        out
    }

    /// Проверяет, является ли `other` надтипом класса `ci`.
    pub fn is_subclass(&self, ci: &CiRef, other: &CiRef) -> bool {
        self.supertypes(ci).iter().any(|c| Rc::ptr_eq(c, other))
    }

    /// Находит поле в классе, его интерфейсах и суперклассах.
    pub fn find_field(&self, ci: &CiRef, name: &str) -> Option<FiRef> {
        let mut c = Some(ci.clone());
        while let Some(cc) = c {
            if let Some(f) = cc.fields.get(name) {
                return Some(f.clone());
            }
            for i in self.ifaces_of(&cc) {
                if let Some(f) = self.find_field(&i, name) {
                    return Some(f);
                }
            }
            c = self.super_of(&cc);
        }
        None
    }

    /// Возвращает нестатические поля класса и всех его родителей.
    pub fn all_fields(&self, ci: &CiRef) -> Vec<FiRef> {
        let mut chain = Vec::new();
        let mut c = Some(ci.clone());
        while let Some(cc) = c {
            c = self.super_of(&cc);
            chain.push(cc);
        }
        let mut out = Vec::new();
        for c in chain.iter().rev() {
            out.extend(c.fields.values().filter(|f| !f.is_static).cloned());
        }
        out
    }

    /// Возвращает методы с именем `name` по всем надтипам класса.
    pub fn find_methods(&self, ci: &CiRef, name: &str) -> Vec<MiRef> {
        let mut res = Vec::new();
        for c in self.supertypes(ci) {
            if let Some(ms) = c.methods.get(name) {
                res.extend(ms.iter().cloned());
            }
        }
        res
    }

    /// Возвращает конкретные классы модуля (и ts-common), реализующие `iface`.
    pub fn implementations(&self, iface: &CiRef, module: &str) -> Vec<CiRef> {
        let vis = Self::visible_modules(module);
        let mut out = Vec::new();
        for ((m, _), ci) in &self.classes {
            if vis.contains(&m.as_ref())
                && !Rc::ptr_eq(ci, iface)
                && &*ci.kind == "class"
                && !ci.anon
                && !ci.decl.mods.contains("abstract")
                && self.is_subclass(ci, iface)
            {
                out.push(ci.clone());
            }
        }
        out
    }
}
