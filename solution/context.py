"""Условия прогона из поля ``context`` скелета.

Скелет описывает дату поездок, показания системных часов и учётную запись
пассажира обычным текстом. Модуль извлекает эти значения, чтобы эмулятор
клиента и интерпретатор не держали их в коде. Если текст не удалось
разобрать, используются значения открытого пакета задачи.
"""

import dataclasses
import datetime
import re

MONTHS = {
    name: number
    for number, name in enumerate(
        (
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
        ),
        start=1,
    )
}

# Время суток системных часов в скелете не указано. Любое утреннее время
# до прогрева сервисов даёт те же ветки кода, что и в эталоне.
CLOCK_TIME = datetime.time(8, 5)

_DAY_MONTH_YEAR = re.compile(
    r"(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(\d{4})", re.I
)


def _dates_in(text):
    """Возвращает даты вида «1 October 2026» из текста в порядке появления."""
    out = []
    for m in _DAY_MONTH_YEAR.finditer(text or ""):
        out.append(
            datetime.date(
                int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1))
            )
        )
    return out


@dataclasses.dataclass(frozen=True)
class RunContext:
    """Дата поездок, системное время и учётные данные пассажира."""

    trip_date: str = "2026-10-01"
    today: str = "2026-09-15"
    username: str = "fdse_microservice"
    password: str = "111111"

    @property
    def now(self):
        """Возвращает системное время прогона как ``datetime``."""
        day = datetime.date.fromisoformat(self.today)
        return datetime.datetime.combine(day, CLOCK_TIME)

    @classmethod
    def from_skeleton(cls, context):
        """Строит контекст из словаря ``context`` скелета."""
        context = context or {}
        values = {}
        date_text = context.get("date", "")
        trip = re.search(r"booked for ([^;.]+)", date_text)
        clock = re.search(r"clock is ([^;.]+)", date_text)
        trip_dates = _dates_in(trip.group(1)) if trip else []
        clock_dates = _dates_in(clock.group(1)) if clock else []
        if trip_dates:
            values["trip_date"] = trip_dates[0].isoformat()
        if clock_dates:
            values["today"] = clock_dates[0].isoformat()
        account = re.search(
            r"user\s+([\w.@-]+)\s*/\s*(\S+?)[\s,;)]",
            context.get("account", ""),
        )
        if account:
            values["username"] = account.group(1)
            values["password"] = account.group(2)
        return cls(**values)
