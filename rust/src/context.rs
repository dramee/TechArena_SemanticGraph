//! Условия прогона из поля `context` скелета.
//!
//! Скелет описывает дату поездок, показания системных часов и учётную запись
//! пассажира обычным текстом. Модуль извлекает эти значения, чтобы эмулятор
//! клиента и интерпретатор не держали их в коде. Если текст не удалось
//! разобрать, используются значения открытого пакета задачи.

use chrono::{NaiveDate, NaiveDateTime, NaiveTime};
use regex::Regex;
use serde_json::Value as Json;

const MONTHS: [&str; 12] = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
];

/// Время суток системных часов: в скелете не указано, любое утреннее время
/// до прогрева сервисов даёт те же ветки кода, что и в эталоне.
const CLOCK_TIME: (u32, u32) = (8, 5);

/// Дата поездок, системное время и учётные данные пассажира.
#[derive(Clone, Debug)]
pub struct RunContext {
    /// Дата поездок (`ГГГГ-ММ-ДД`).
    pub trip_date: String,
    /// Системная дата (`ГГГГ-ММ-ДД`).
    pub today: String,
    /// Имя пользователя.
    pub username: String,
    /// Пароль.
    pub password: String,
}

impl Default for RunContext {
    fn default() -> Self {
        RunContext {
            trip_date: "2026-10-01".to_string(),
            today: "2026-09-15".to_string(),
            username: "fdse_microservice".to_string(),
            password: "111111".to_string(),
        }
    }
}

/// Возвращает даты вида «1 October 2026» из текста в порядке появления.
fn dates_in(text: &str) -> Vec<NaiveDate> {
    let pat = format!(r"(?i)(\d{{1,2}})\s+({})\s+(\d{{4}})", MONTHS.join("|"));
    let Ok(re) = Regex::new(&pat) else {
        return Vec::new();
    };
    re.captures_iter(text)
        .filter_map(|m| {
            let month = MONTHS.iter().position(|x| m[2].eq_ignore_ascii_case(x))? as u32 + 1;
            NaiveDate::from_ymd_opt(m[3].parse().ok()?, month, m[1].parse().ok()?)
        })
        .collect()
}

fn group(re: &str, text: &str) -> Option<String> {
    Regex::new(re)
        .ok()?
        .captures(text)
        .map(|m| m[1].to_string())
}

impl RunContext {
    /// Возвращает системное время прогона.
    pub fn now(&self) -> NaiveDateTime {
        let day = NaiveDate::parse_from_str(&self.today, "%Y-%m-%d")
            .unwrap_or_else(|_| NaiveDate::from_ymd_opt(2026, 9, 15).unwrap_or_default());
        let time = NaiveTime::from_hms_opt(CLOCK_TIME.0, CLOCK_TIME.1, 0).unwrap_or_default();
        day.and_time(time)
    }

    /// Строит контекст из поля `context` скелета.
    pub fn from_skeleton(context: &Json) -> RunContext {
        let mut out = RunContext::default();
        let get = |k: &str| context.get(k).and_then(|v| v.as_str()).unwrap_or("");
        let date_text = get("date");
        let trip = group(r"booked for ([^;.]+)", date_text)
            .map(|t| dates_in(&t))
            .unwrap_or_default();
        let clock = group(r"clock is ([^;.]+)", date_text)
            .map(|t| dates_in(&t))
            .unwrap_or_default();
        if let Some(d) = trip.first() {
            out.trip_date = d.format("%Y-%m-%d").to_string();
        }
        if let Some(d) = clock.first() {
            out.today = d.format("%Y-%m-%d").to_string();
        }
        if let Ok(re) = Regex::new(r"user\s+([\w.@-]+)\s*/\s*(\S+?)[\s,;)]") {
            if let Some(m) = re.captures(get("account")) {
                out.username = m[1].to_string();
                out.password = m[2].to_string();
            }
        }
        out
    }
}
