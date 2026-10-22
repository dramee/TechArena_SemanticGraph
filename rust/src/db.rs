//! Разбор mysqldump (состояние БД перед сценарием) в структуры в памяти.

use std::cell::RefCell;
use std::io::Read;
use std::rc::Rc;

use indexmap::IndexMap;
use regex::Regex;

use crate::values::{Shared, Value, rs, shared};

/// Строка таблицы: колонка -> значение.
pub type Row = Shared<IndexMap<Rc<str>, Value>>;

/// Таблица базы данных: имя, колонки и строки.
pub struct Table {
    /// База данных сервиса.
    pub db: Rc<str>,
    /// Имя таблицы.
    pub name: Rc<str>,
    /// Колонки.
    pub cols: Vec<Rc<str>>,
    /// Строки.
    pub rows: Vec<Row>,
}

/// Таблицы по именам.
pub type Tables = IndexMap<Rc<str>, Shared<Table>>;

/// Делает независимую копию всех таблиц (как `copy.deepcopy`).
pub fn deep_copy(tables: &Tables) -> Tables {
    tables
        .iter()
        .map(|(k, t)| {
            let t = t.borrow();
            let rows = t
                .rows
                .iter()
                .map(|r| Rc::new(RefCell::new(r.borrow().clone())))
                .collect();
            (
                k.clone(),
                shared(Table {
                    db: t.db.clone(),
                    name: t.name.clone(),
                    cols: t.cols.clone(),
                    rows,
                }),
            )
        })
        .collect()
}

fn scalar(tok: &str) -> Value {
    if tok.eq_ignore_ascii_case("NULL") {
        return Value::Null;
    }
    if let Some(v) = parse_py_int(tok) {
        return Value::Int(v);
    }
    match tok.trim().replace('_', "").parse::<f64>() {
        Ok(f) if !tok.trim().is_empty() => Value::Float(f),
        _ => rs(Rc::from(tok)),
    }
}

fn parse_py_int(tok: &str) -> Option<i64> {
    let t = tok.trim();
    let body = t.strip_prefix(['-', '+']).unwrap_or(t);
    if body.is_empty() || !body.chars().all(|c| c.is_ascii_digit()) {
        return None;
    }
    t.parse().ok()
}

/// Разбирает список кортежей из `INSERT … VALUES`.
fn parse_values(s: &[char]) -> Vec<Vec<Value>> {
    let n = s.len();
    let mut rows = Vec::new();
    let mut i = 0;
    while i < n {
        if s[i] != '(' {
            i += 1;
            continue;
        }
        i += 1;
        let mut row = Vec::new();
        loop {
            if s[i] == '\'' {
                let mut j = i + 1;
                let mut buf = String::new();
                loop {
                    let ch = s[j];
                    if ch == '\\' {
                        let nx = s[j + 1];
                        buf.push(match nx {
                            'n' => '\n',
                            't' => '\t',
                            'r' => '\r',
                            '0' => '\0',
                            'b' => '\u{8}',
                            'Z' => '\u{1a}',
                            c => c,
                        });
                        j += 2;
                    } else if ch == '\'' {
                        if j + 1 < n && s[j + 1] == '\'' {
                            buf.push('\'');
                            j += 2;
                        } else {
                            j += 1;
                            break;
                        }
                    } else {
                        buf.push(ch);
                        j += 1;
                    }
                }
                row.push(rs(Rc::from(buf.as_str())));
                i = j;
            } else {
                let mut j = i;
                while s[j] != ',' && s[j] != ')' {
                    j += 1;
                }
                let tok: String = s[i..j].iter().collect();
                row.push(scalar(tok.trim()));
                i = j;
            }
            if s[i] == ',' {
                i += 1;
                continue;
            }
            if s[i] == ')' {
                i += 1;
                break;
            }
        }
        rows.push(row);
    }
    rows
}

/// Разбирает дамп `mysqldump` (можно `.gz`) в таблицы по именам.
pub fn parse_dump(path: &str) -> Result<Tables, String> {
    let bytes = std::fs::read(path).map_err(|e| format!("{path}: {e}"))?;
    let raw = if path.ends_with(".gz") {
        let mut out = Vec::new();
        flate2::read::GzDecoder::new(&bytes[..])
            .read_to_end(&mut out)
            .map_err(|e| format!("{path}: {e}"))?;
        out
    } else {
        bytes
    };
    let text = String::from_utf8_lossy(&raw).replace("\r\n", "\n");
    let re_db = Regex::new(r"^-- DB (\S+)").map_err(|e| e.to_string())?;
    let re_create = Regex::new(r"^CREATE TABLE `(\w+)`").map_err(|e| e.to_string())?;
    let re_col = Regex::new(r"^\s+`(\w+)` ").map_err(|e| e.to_string())?;
    let re_insert =
        Regex::new(r"^INSERT INTO `(\w+)` VALUES (.*);$").map_err(|e| e.to_string())?;
    let mut tables: Tables = IndexMap::new();
    let mut db: Rc<str> = Rc::from("");
    let mut cur: Option<Shared<Table>> = None;
    for line in text.split('\n') {
        if let Some(m) = re_db.captures(line) {
            db = Rc::from(&m[1]);
            continue;
        }
        if let Some(m) = re_create.captures(line) {
            let t = shared(Table {
                db: db.clone(),
                name: Rc::from(&m[1]),
                cols: Vec::new(),
                rows: Vec::new(),
            });
            tables.insert(Rc::from(&m[1]), t.clone());
            cur = Some(t);
            continue;
        }
        if let Some(t) = &cur {
            let empty = t.borrow().rows.is_empty();
            if empty {
                if let Some(m) = re_col.captures(line) {
                    let st = line.trim();
                    if !(st.starts_with("PRIMARY")
                        || st.starts_with("KEY")
                        || st.starts_with("CONSTRAINT"))
                    {
                        t.borrow_mut().cols.push(Rc::from(&m[1]));
                    }
                }
            }
        }
        if let Some(m) = re_insert.captures(line) {
            let t = tables
                .get(&m[1])
                .cloned()
                .ok_or_else(|| format!("нет таблицы {}", &m[1]))?;
            let chars: Vec<char> = m[2].chars().collect();
            let mut t = t.borrow_mut();
            for r in parse_values(&chars) {
                let mut row = IndexMap::new();
                for (c, v) in t.cols.iter().zip(r) {
                    row.insert(c.clone(), v);
                }
                t.rows.push(shared(row));
            }
        }
    }
    Ok(tables)
}
