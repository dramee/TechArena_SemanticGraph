//! Временная утилита сверки: дамп AST всех файлов в каноническом виде.

use std::fmt::Write as _;
use std::io::Read;
use trainticket_graph::jparse::*;

fn jstr(s: &str) -> String {
    let mut out = String::from("\"");
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{8}' => out.push_str("\\b"),
            '\u{c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 || (c as u32) > 0x7e => {
                let mut buf = [0u16; 2];
                for u in c.encode_utf16(&mut buf) {
                    let _ = write!(out, "\\u{:04x}", u);
                }
            }
            c => out.push(c),
        }
    }
    out.push('"');
    out
}

fn opt(s: &Option<impl AsRef<str>>) -> String {
    match s {
        Some(v) => v.as_ref().to_string(),
        None => "None".to_string(),
    }
}

fn lit(k: &LitKind, v: &LitVal) -> String {
    match (k, v) {
        (_, LitVal::Float(f)) => format!("F{:016x}", f.to_bits()),
        (_, LitVal::Int(i)) => format!("I{i}"),
        (_, LitVal::Bool(b)) => format!("B{}", if *b { 1 } else { 0 }),
        (_, LitVal::Null) => "N".to_string(),
        (LitKind::Char, LitVal::Str(s)) => format!("C{}", jstr(s)),
        (_, LitVal::Str(s)) => format!("S{}", jstr(s)),
    }
}

fn es(xs: &[E]) -> String {
    xs.iter().map(|x| e(Some(x))).collect::<Vec<_>>().join(" ")
}

fn e(x: Option<&E>) -> String {
    let Some(x) = x else { return "_".to_string() };
    match &**x {
        Expr::Lit(k, v) => format!("(Lit {})", lit(k, v)),
        Expr::Name { id, line, col } => format!("(Name {id} {line}:{col})"),
        Expr::FieldAcc { obj, name, line, col } => {
            format!("(Field {} {name} {line}:{col})", e(Some(obj)))
        }
        Expr::Call { obj, name, args, line, col } => {
            format!("(Call {} {name} [{}] {line}:{col})", e(obj.as_ref()), es(args))
        }
        Expr::New { ty, args, body, line, col, outer } => {
            let b = body.as_ref().map(|c| cls(c)).unwrap_or("_".to_string());
            format!("(New {ty} [{}] {line}:{col} {} {b})", es(args), e(outer.as_ref()))
        }
        Expr::NewArray { ty, dims, init } => {
            let d = dims.iter().map(|d| e(d.as_ref())).collect::<Vec<_>>().join(" ");
            let i = init.as_ref().map(|i| format!("[{}]", es(i))).unwrap_or("_".to_string());
            format!("(NewArray {ty} [{d}] {i})")
        }
        Expr::ArrayLit(el) => format!("(Arr [{}])", es(el)),
        Expr::Index { obj, idx } => format!("(Index {} {})", e(Some(obj)), e(Some(idx))),
        Expr::Unary { op, e: x } => format!("(Unary {op} {})", e(Some(x))),
        Expr::Postfix { op, e: x } => format!("(Postfix {op} {})", e(Some(x))),
        Expr::Binary { op, l, r } => format!("(Bin {op} {} {})", e(Some(l)), e(Some(r))),
        Expr::Assign { op, target, value } => {
            format!("(Assign {op} {} {})", e(Some(target)), e(Some(value)))
        }
        Expr::Cond { c, a, b } => format!("(Cond {} {} {})", e(Some(c)), e(Some(a)), e(Some(b))),
        Expr::Cast { ty, e: x } => format!("(Cast {ty} {})", e(Some(x))),
        Expr::InstanceOf { e: x, ty, bind } => {
            format!("(InstOf {} {ty} {})", e(Some(x)), opt(bind))
        }
        Expr::Lambda { params, body } => {
            let b = match body {
                LambdaBody::Block(s0) => s(Some(s0)),
                LambdaBody::Expr(x) => e(Some(x)),
            };
            let ps = params.iter().map(|p| p.to_string()).collect::<Vec<_>>().join(" ");
            format!("(Lambda [{ps}] {b})")
        }
        Expr::MethodRef { obj, name } => format!("(MRef {} {name})", e(Some(obj))),
        Expr::This => "(This)".to_string(),
        Expr::Super => "(Super)".to_string(),
        Expr::ClassLit(ClassLitTy::Name(n)) => format!("(ClassLit {n})"),
        Expr::ClassLit(ClassLitTy::Expr(x)) => format!("(ClassLit {})", e(Some(x))),
        Expr::TypeExpr(t) => format!("(TypeExpr {t})"),
        Expr::SwitchExpr(st) => format!("(SwitchExpr {})", s(Some(st))),
    }
}

fn ss(xs: &[S]) -> String {
    xs.iter().map(|x| s(Some(x))).collect::<Vec<_>>().join(" ")
}

fn s(x: Option<&S>) -> String {
    let Some(x) = x else { return "_".to_string() };
    match &**x {
        Stmt::Block { stmts, line } => format!("{{{line} {}}}", ss(stmts)),
        Stmt::LocalVar { ty, decls, line } => {
            let d = decls
                .iter()
                .map(|(n, i)| format!("{n}={}", e(i.as_ref())))
                .collect::<Vec<_>>()
                .join(" ");
            format!("(Local {ty} [{d}] {line})")
        }
        Stmt::ExprStmt { e: x, line } => format!("(Expr {} {line})", e(Some(x))),
        Stmt::If { c, then, els, line } => {
            format!("(If {} {} {} {line})", e(Some(c)), s(Some(then)), s(els.as_ref()))
        }
        Stmt::While { c, body, line } => format!("(While {} {} {line})", e(Some(c)), s(Some(body))),
        Stmt::DoWhile { body, c, line } => format!("(Do {} {} {line})", s(Some(body)), e(Some(c))),
        Stmt::For { init, c, update, body, line } => format!(
            "(For [{}] {} [{}] {} {line})",
            ss(init),
            e(c.as_ref()),
            es(update),
            s(Some(body))
        ),
        Stmt::ForEach { ty, name, iter, body, line } => {
            format!("(ForEach {ty} {name} {} {} {line})", e(Some(iter)), s(Some(body)))
        }
        Stmt::Return { e: x, line } => format!("(Return {} {line})", e(x.as_ref())),
        Stmt::Throw { e: x, line } => format!("(Throw {} {line})", e(Some(x))),
        Stmt::Break { label } => format!("(Break {})", opt(label)),
        Stmt::Continue { label } => format!("(Continue {})", opt(label)),
        Stmt::Try { res, body, catches, fin, line } => {
            let r = res
                .iter()
                .map(|(n, v)| format!("{}={}", opt(n), e(Some(v))))
                .collect::<Vec<_>>()
                .join(" ");
            let c = catches
                .iter()
                .map(|(ts, n, b)| {
                    let t = ts.iter().map(|x| x.to_string()).collect::<Vec<_>>().join("|");
                    format!("<{t} {n} {}>", s(Some(b)))
                })
                .collect::<Vec<_>>()
                .join(" ");
            format!("(Try [{r}] {} [{c}] {} {line})", s(Some(body)), s(fin.as_ref()))
        }
        Stmt::Switch { e: x, cases, line } => {
            let c = cases
                .iter()
                .map(|(labs, st)| {
                    let l = match labs {
                        None => "default".to_string(),
                        Some(l) => es(l),
                    };
                    format!("<{l} : {}>", ss(st))
                })
                .collect::<Vec<_>>()
                .join(" ");
            format!("(Switch {} [{c}] {line})", e(Some(x)))
        }
        Stmt::Sync { e: x, body } => format!("(Sync {} {})", e(Some(x)), s(Some(body))),
        Stmt::Labeled { label, stmt } => format!("(Label {label} {})", s(Some(stmt))),
        Stmt::LocalClass(c) => format!("(LocalClass {})", cls(c)),
        Stmt::Assert { c, m } => format!("(Assert {} {})", e(Some(c)), e(m.as_ref())),
        Stmt::Empty => "(Empty)".to_string(),
    }
}

fn ann(a: &[Annot]) -> String {
    format!(
        "[{}]",
        a.iter()
            .map(|x| format!("@{}({})", x.name, x.args))
            .collect::<Vec<_>>()
            .join(" ")
    )
}

fn sorted(m: &std::collections::HashSet<String>) -> String {
    let mut v: Vec<&String> = m.iter().collect();
    v.sort();
    v.iter().map(|x| x.as_str()).collect::<Vec<_>>().join(",")
}

fn pylist(v: &Option<Vec<String>>) -> String {
    match v {
        None => "None".to_string(),
        Some(v) => format!(
            "[{}]",
            v.iter().map(|x| format!("'{x}'")).collect::<Vec<_>>().join(", ")
        ),
    }
}

fn b(v: bool) -> &'static str {
    if v { "True" } else { "False" }
}

fn cls(c: &ClassDecl) -> String {
    let mut parts = vec![format!(
        "CLASS {} {} fqn={} ext={} impls={} tp={} anon={} {}-{} mods={} {}",
        c.kind,
        c.name,
        c.fqn,
        opt(&c.ext),
        c.impls.join(","),
        pylist(&c.tparams),
        b(c.anon),
        c.line,
        c.end,
        sorted(&c.mods),
        ann(&c.annots)
    )];
    for f in &c.fields {
        parts.push(format!(
            "FIELD {} {} {} mods={} {} {}",
            f.ty,
            f.name,
            f.line,
            sorted(&f.mods),
            ann(&f.annots),
            e(f.init.as_ref())
        ));
    }
    for m in &c.methods {
        let ps = m
            .params
            .iter()
            .map(|p| format!("{}:{}:{}:{}", p.ty, p.name, b(p.varargs), ann(&p.annots)))
            .collect::<Vec<_>>()
            .join(",");
        parts.push(format!(
            "METHOD {} ret={} {}-{} start={} ctor={} tp={} ({}) mods={} {} {}",
            m.name,
            opt(&m.ret),
            m.line,
            m.end,
            m.start,
            b(m.ctor),
            b(m.tparams),
            ps,
            sorted(&m.mods),
            ann(&m.annots),
            s(m.body.as_ref())
        ));
    }
    for (st, blk) in &c.inits {
        parts.push(format!("INIT {} {}", b(*st), s(Some(blk))));
    }
    for i in &c.inner {
        parts.push(format!("INNER {}", cls(i)));
    }
    for en in &c.enums {
        let body = en.body.as_ref().map(|c| cls(c)).unwrap_or("_".to_string());
        parts.push(format!("ENUM {} {} [{}] {}", en.name, en.line, es(&en.args), body));
    }
    parts.join("\n")
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let root = &args[1];
    let mut gz = flate2::read::GzDecoder::new(std::fs::File::open(&args[2]).unwrap());
    let mut text = String::new();
    gz.read_to_string(&mut text).unwrap();
    let sk: serde_json::Value = serde_json::from_str(&text).unwrap();
    let mut files: Vec<String> = sk["nodes"]
        .as_object()
        .unwrap()
        .values()
        .filter(|n| n["kind"] == "file" && n["path"].as_str().unwrap().ends_with(".java"))
        .map(|n| n["path"].as_str().unwrap().to_string())
        .collect();
    files.sort();
    let mut out = String::new();
    for path in files {
        let pf = parse_file(&format!("{root}/{path}")).unwrap();
        let imps = pf
            .imports
            .iter()
            .map(|(st, q)| format!("({}, '{}')", b(*st), q))
            .collect::<Vec<_>>()
            .join(", ");
        let _ = writeln!(out, "FILE {path} pkg={} imports=[{imps}]", pf.pkg);
        for t in &pf.types {
            let _ = writeln!(out, "{}", cls(t));
        }
    }
    std::fs::write(&args[3], out).unwrap();
}
