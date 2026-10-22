//! Десятичное число с показателем, как `decimal.Decimal` в Python.
//!
//! Используется для `BigDecimal`: сложение и вычитание сохраняют показатель
//! степени, поэтому `100.0 - 80` даёт `20.0`, как в Java и Python.

use std::cmp::Ordering;

/// Десятичное число `coef * 10^exp`.
#[derive(Clone, Copy, Debug)]
pub struct Dec {
    coef: i128,
    exp: i32,
}

/// Режим округления.
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Rounding {
    /// Половина — от нуля.
    HalfUp,
    /// Половина — к чётному.
    HalfEven,
}

fn pow10(n: u32) -> Option<i128> {
    10i128.checked_pow(n)
}

impl Dec {
    /// Создаёт число из целого.
    pub fn from_int(v: i64) -> Self {
        Dec {
            coef: v as i128,
            exp: 0,
        }
    }

    /// Разбирает строку как `Decimal(str)` (с показателем, если он есть).
    pub fn parse(text: &str) -> Option<Self> {
        let t = text.trim();
        let (neg, body) = match t.strip_prefix('-') {
            Some(r) => (true, r),
            None => (false, t.strip_prefix('+').unwrap_or(t)),
        };
        let (mant, e) = match body.find(['e', 'E']) {
            Some(i) => (&body[..i], body[i + 1..].parse::<i32>().ok()?),
            None => (body, 0),
        };
        let (int_part, frac) = match mant.split_once('.') {
            Some((a, b)) => (a, b),
            None => (mant, ""),
        };
        if int_part.is_empty() && frac.is_empty() {
            return None;
        }
        if !int_part.chars().chain(frac.chars()).all(|c| c.is_ascii_digit()) {
            return None;
        }
        let digits = format!("{int_part}{frac}");
        let coef: i128 = if digits.is_empty() {
            0
        } else {
            digits.parse().ok()?
        };
        Some(Dec {
            coef: if neg { -coef } else { coef },
            exp: e - frac.len() as i32,
        })
    }

    /// Точно переводит `f64`, как `Decimal(float)`.
    pub fn from_f64(v: f64) -> Self {
        if v.fract() == 0.0 && v.abs() < 1e30 {
            return Dec {
                coef: v as i128,
                exp: 0,
            };
        }
        let bits = v.to_bits();
        let neg = bits >> 63 == 1;
        let exp_bits = ((bits >> 52) & 0x7ff) as i32;
        let frac = bits & ((1u64 << 52) - 1);
        let (mut m, mut e) = if exp_bits == 0 {
            (frac as i128, -1074)
        } else {
            ((frac | (1u64 << 52)) as i128, exp_bits - 1075)
        };
        while m != 0 && m % 2 == 0 && e < 0 {
            m /= 2;
            e += 1;
        }
        let mut coef = m;
        let mut ok = true;
        for _ in 0..(-e) {
            match coef.checked_mul(5) {
                Some(c) => coef = c,
                None => {
                    ok = false;
                    break;
                }
            }
        }
        if !ok {
            return Dec::parse(&format!("{v:e}")).unwrap_or(Dec::from_int(0));
        }
        Dec {
            coef: if neg { -coef } else { coef },
            exp: e,
        }
    }

    /// Значение как `f64`.
    pub fn to_f64(&self) -> f64 {
        format!("{}e{}", self.coef, self.exp)
            .parse()
            .unwrap_or(0.0)
    }

    /// Целая часть (с отбрасыванием дробной), как `int(Decimal)`.
    pub fn to_i64(&self) -> i64 {
        if self.exp >= 0 {
            (self.coef * pow10(self.exp as u32).unwrap_or(1)) as i64
        } else {
            match pow10((-self.exp) as u32) {
                Some(p) => (self.coef / p) as i64,
                None => 0,
            }
        }
    }

    fn align(a: &Dec, b: &Dec) -> Option<(i128, i128, i32)> {
        let e = a.exp.min(b.exp);
        let ca = a.coef.checked_mul(pow10((a.exp - e) as u32)?)?;
        let cb = b.coef.checked_mul(pow10((b.exp - e) as u32)?)?;
        Some((ca, cb, e))
    }

    /// Сумма.
    pub fn add(&self, o: &Dec) -> Dec {
        match Dec::align(self, o) {
            Some((a, b, e)) => Dec { coef: a + b, exp: e },
            None => Dec::from_f64(self.to_f64() + o.to_f64()),
        }
    }

    /// Разность.
    pub fn sub(&self, o: &Dec) -> Dec {
        self.add(&o.neg())
    }

    /// Произведение.
    pub fn mul(&self, o: &Dec) -> Dec {
        match self.coef.checked_mul(o.coef) {
            Some(c) => Dec {
                coef: c,
                exp: self.exp + o.exp,
            },
            None => Dec::from_f64(self.to_f64() * o.to_f64()),
        }
    }

    /// Частное (приближённо).
    pub fn div(&self, o: &Dec) -> Dec {
        Dec::parse(&crate::values::py_float_repr(self.to_f64() / o.to_f64()))
            .unwrap_or(Dec::from_int(0))
    }

    /// Число с обратным знаком.
    pub fn neg(&self) -> Dec {
        Dec {
            coef: -self.coef,
            exp: self.exp,
        }
    }

    /// Модуль.
    pub fn abs(&self) -> Dec {
        Dec {
            coef: self.coef.abs(),
            exp: self.exp,
        }
    }

    /// Знак: -1, 0 или 1.
    pub fn signum(&self) -> i64 {
        self.coef.signum() as i64
    }

    /// Сравнивает по значению.
    pub fn cmp_dec(&self, o: &Dec) -> Ordering {
        match Dec::align(self, o) {
            Some((a, b, _)) => a.cmp(&b),
            None => self
                .to_f64()
                .partial_cmp(&o.to_f64())
                .unwrap_or(Ordering::Equal),
        }
    }

    /// Округляет до `places` знаков после точки.
    pub fn quantize(&self, places: i32, mode: Rounding) -> Dec {
        let target = -places;
        if self.exp >= target {
            let coef = self.coef * pow10((self.exp - target) as u32).unwrap_or(1);
            return Dec { coef, exp: target };
        }
        let p = pow10((target - self.exp) as u32).unwrap_or(1);
        let q = self.coef / p;
        let r = (self.coef % p).abs();
        let half = p / 2;
        let up = match r.cmp(&half) {
            Ordering::Greater => true,
            Ordering::Less => false,
            Ordering::Equal => match mode {
                Rounding::HalfUp => true,
                Rounding::HalfEven => q % 2 != 0,
            },
        };
        let q = if up {
            if self.coef < 0 { q - 1 } else { q + 1 }
        } else {
            q
        };
        Dec {
            coef: q,
            exp: target,
        }
    }

    /// Запись без показателя, как `format(d, "f")`.
    pub fn to_plain(&self) -> String {
        let neg = self.coef < 0;
        let digits = self.coef.abs().to_string();
        let mut out = String::new();
        if neg {
            out.push('-');
        }
        if self.exp >= 0 {
            out.push_str(&digits);
            for _ in 0..self.exp {
                out.push('0');
            }
            return out;
        }
        let places = (-self.exp) as usize;
        if digits.len() > places {
            out.push_str(&digits[..digits.len() - places]);
            out.push('.');
            out.push_str(&digits[digits.len() - places..]);
        } else {
            out.push_str("0.");
            for _ in 0..(places - digits.len()) {
                out.push('0');
            }
            out.push_str(&digits);
        }
        out
    }
}
