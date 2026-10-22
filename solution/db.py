"""Разбор mysqldump (состояние БД перед сценарием) в структуры в памяти."""

import gzip
import re

# Экранирование символов в строковых литералах mysqldump.
MYSQL_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "0": "\0",
    "b": "\b",
    "Z": "\x1a",
}


class Table:
    """Таблица базы данных: имя, колонки и строки-словари."""

    def __init__(self, db, name, cols):
        """Создаёт пустую таблицу ``name`` базы ``db`` с колонками."""
        self.db, self.name, self.cols = db, name, cols
        # Строки как словари «колонка -> значение».
        self.rows = []

    def __repr__(self):
        """Возвращает краткое описание таблицы."""
        return f"Table({self.db}.{self.name}, {len(self.rows)} rows)"


def _parse_values(s):
    """Разбирает список кортежей из ``INSERT … VALUES``.

    ``(1,'a',NULL),(2,'b',3.5)`` даёт ``[[1, 'a', None], [2, 'b', 3.5]]``.
    """
    rows, i, n = [], 0, len(s)
    while i < n:
        if s[i] != "(":
            i += 1
            continue
        i += 1
        row = []
        while True:
            c = s[i]
            if c == "'":
                j, buf = i + 1, []
                while True:
                    ch = s[j]
                    if ch == "\\":
                        nx = s[j + 1]
                        buf.append(
                            {
                                "n": "\n",
                                "t": "\t",
                                "r": "\r",
                                "0": "\0",
                                "b": "\b",
                                "Z": "\x1a",
                            }.get(nx, nx)
                        )
                        j += 2
                    elif ch == "'":
                        if j + 1 < n and s[j + 1] == "'":
                            buf.append("'")
                            j += 2
                        else:
                            j += 1
                            break
                    else:
                        buf.append(ch)
                        j += 1
                row.append("".join(buf))
                i = j
            else:
                j = i
                while s[j] not in ",)":
                    j += 1
                tok = s[i:j].strip()
                if tok.upper() == "NULL":
                    row.append(None)
                else:
                    try:
                        row.append(int(tok))
                    except ValueError:
                        try:
                            row.append(float(tok))
                        except ValueError:
                            row.append(tok)
                i = j
            if s[i] == ",":
                i += 1
                continue
            if s[i] == ")":
                i += 1
                break
        rows.append(row)
    return rows


def parse_dump(path):
    """Разбирает дамп ``mysqldump`` (можно ``.gz``) в словарь таблиц.

    Имена таблиц в дампе уникальны между базами сервисов, поэтому ключ —
    имя таблицы без имени базы.
    """
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as f:
        text = f.read()
    tables, db, cur = {}, None, None
    for line in text.split("\n"):
        m = re.match(r"-- DB (\S+)", line)
        if m:
            db = m.group(1)
            continue
        m = re.match(r"CREATE TABLE `(\w+)`", line)
        if m:
            cur = Table(db, m.group(1), [])
            tables[cur.name] = cur
            continue
        if cur is not None and not cur.rows:
            m = re.match(r"\s+`(\w+)` ", line)
            if m and not line.strip().startswith(
                ("PRIMARY", "KEY", "CONSTRAINT")
            ):
                cur.cols.append(m.group(1))
        m = re.match(r"INSERT INTO `(\w+)` VALUES (.*);$", line)
        if m:
            t = tables[m.group(1)]
            for r in _parse_values(m.group(2)):
                t.rows.append(dict(zip(t.cols, r)))
    return tables
