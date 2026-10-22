"""Эмулятор веб-клиента Train Ticket.

Шаг сценария (текст на английском) превращается в HTTP-запрос к шлюзу так,
как это делает веб-интерфейс ``ts-ui-dashboard``. Клиент помнит состояние
между шагами: токены ролей, найденные рейсы, контакты, заказы и объекты,
созданные администратором.
"""

import calendar
import re

from .context import MONTHS, RunContext
from .values import JList, JMap, LibObj
from .web import entry_request

STATION_UI = {
    "shanghai": "Shang Hai",
    "suzhou": "Su Zhou",
    "nanjing": "Nan Jing",
    "beijing": "Bei Jing",
    "ning bo": "Ning Bo",
    "ningbo": "Ning Bo",
    "hangzhou": "Hang Zhou",
    "taiyuan": "Tai Yuan",
    "wuxi": "Wu Xi",
    "xuzhou": "Xu Zhou",
}

# Учётная запись администратора, которую создаёт InitUser в ts-auth-service.
ADMIN_CREDENTIALS = ("admin", "222222")

# Пароль новой учётной записи при регистрации пассажира.
NEW_USER_PASSWORD = "111111"

ORDER_STATUS = {
    "notpaid": 0,
    "paid": 1,
    "collected": 2,
    "change": 3,
    "cancel": 4,
    "refunded": 5,
    "used": 6,
}

ASSURANCE_TYPES = {"first": 1, "second": 2, "third": 3}

SEAT_FIRST_CLASS = 2
SEAT_SECOND_CLASS = 3

# Буквы типов рейсов в порядке перечисления edu.fudan.common.entity.Type.
TRIP_TYPE_LETTERS = "GDZTK"

ORDINALS = {"first": 0, "second": 1, "third": 2, "fourth": 3, "fifth": 4}

# Минимальная мера сходства слов шага и обработчика для запасного подбора.
FALLBACK_MIN_SCORE = 0.35

_ORDINAL_TRIP = re.compile(
    r"\b(" + "|".join(ORDINALS) + r") (?:[\w()'-]+ )?trip\b"
)
_ROUTE_SEPARATORS = re.compile(r"\s*(?:—|–|→|->|-|,|\bto\b|\bvia\b)\s*")

_BASIC = "/api/v1/adminbasicservice/adminbasic"


def station_ui(name):
    """Возвращает название станции так, как его вводит пользователь в UI."""
    k = re.sub(r"\s+", " ", name.strip().lower())
    return (
        STATION_UI.get(k)
        or STATION_UI.get(k.replace(" ", ""))
        or name.strip().title()
    )


def station_key(name):
    """Возвращает ключ станции в базе: строчные буквы без пробелов."""
    return re.sub(r"\s+", "", name.strip().lower())


def parse_date(text, default):
    """Находит в тексте дату и возвращает её в виде ``ГГГГ-ММ-ДД``.

    Понимает «1 October 2026», «October 1, 2026» и «2026-10-01». Если даты
    в тексте нет, возвращает ``default``.
    """
    months = "|".join(MONTHS)
    m = re.search(r"(\d{1,2})\s+(" + months + r")\s+(\d{4})", text, re.I)
    if m:
        day, month, year = m.group(1), m.group(2), m.group(3)
        return "%s-%02d-%02d" % (year, MONTHS[month.lower()], int(day))
    m = re.search(r"(" + months + r")\s+(\d{1,2}),?\s+(\d{4})", text, re.I)
    if m:
        month, day, year = m.group(1), m.group(2), m.group(3)
        return "%s-%02d-%02d" % (year, MONTHS[month.lower()], int(day))
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    if m:
        return m.group(0)
    return default


def month_range(text, default_year, default):
    """Возвращает диапазон дат по названиям месяцев в тексте.

    «September — December 2026» даёт ``("2026-09-01", "2026-12-31")``.
    Если названий месяцев нет, возвращает ``default``.
    """
    found = [
        MONTHS[m.lower()]
        for m in re.findall(r"\b(" + "|".join(MONTHS) + r")\b", text, re.I)
    ]
    if not found:
        return default
    year_m = re.search(r"\b(\d{4})\b", text)
    year = int(year_m.group(1)) if year_m else default_year
    first, last = found[0], found[-1]
    last_day = calendar.monthrange(year, last)[1]
    return (
        "%d-%02d-01" % (year, first),
        "%d-%02d-%02d" % (year, last, last_day),
    )


def snake_to_camel(name):
    """Переводит имя колонки БД (``stay_time``) в имя поля JSON."""
    head, *rest = name.split("_")
    return head + "".join(p[:1].upper() + p[1:] for p in rest)


def _sorted_by_bought(orders):
    return sorted(orders, key=lambda o: o.get("boughtDate", ""))


class AdminEntity:
    """Объект админ-консоли: адреса запросов, таблицы БД и поля тела."""

    def __init__(self, name, pattern, path, delete_tpl, tables, fields):
        """Описывает объект; ``fields`` — колонки БД, попадающие в тело."""
        self.name = name
        self.pattern = re.compile(pattern)
        self.path = path
        self.delete_tpl = delete_tpl
        self.tables = tables
        self.fields = fields


ADMIN_ENTITIES = (
    AdminEntity(
        "price",
        r"\bprice config\w*|\bprices?\b",
        _BASIC + "/prices",
        "{id}",
        ("price_config",),
        (
            "id",
            "train_type",
            "route_id",
            "basic_price_rate",
            "first_class_price_rate",
        ),
    ),
    AdminEntity(
        "config",
        r"\bconfig\w*|\bsettings?\b",
        _BASIC + "/configs",
        "{name}",
        ("config",),
        ("name", "value", "description"),
    ),
    AdminEntity(
        "train",
        r"\btrain types?\b|\btrains?\b",
        _BASIC + "/trains",
        "{id}",
        ("train_type",),
        ("id", "name", "economy_class", "confort_class", "average_speed"),
    ),
    AdminEntity(
        "station",
        r"\bstations?\b",
        _BASIC + "/stations",
        "{id}",
        ("station",),
        ("id", "name", "stay_time"),
    ),
    AdminEntity(
        "contact",
        r"\bcontacts?\b",
        _BASIC + "/contacts",
        "{id}",
        ("contacts",),
        (
            "id",
            "account_id",
            "name",
            "document_type",
            "document_number",
            "phone_number",
        ),
    ),
    AdminEntity(
        "user",
        r"\busers?\b|\baccounts?\b|\bpassengers?\b",
        "/api/v1/adminuserservice/users",
        "{userId}",
        ("user",),
        (
            "user_id",
            "user_name",
            "password",
            "gender",
            "document_type",
            "document_num",
            "email",
        ),
    ),
    AdminEntity(
        "route",
        r"\broutes?\b",
        "/api/v1/adminrouteservice/adminroute",
        "{id}",
        ("route",),
        ("id", "start_station", "end_station"),
    ),
    AdminEntity(
        "trip",
        r"\btrips?\b|\btravels?\b",
        "/api/v1/admintravelservice/admintravel",
        "{tripId}",
        ("trip", "trip2"),
        (
            "route_id",
            "train_type_name",
            "start_station_name",
            "stations_name",
            "terminal_station_name",
            "start_time",
            "end_time",
        ),
    ),
    AdminEntity(
        "order",
        r"\borders?\b",
        "/api/v1/adminorderservice/adminorder",
        "{id}/{trainNumber}",
        ("orders", "orders_other"),
        (),
    ),
)

ADMIN_OPERATIONS = (
    ("delete", r"\b(?:delete|remove)\b"),
    ("update", r"\b(?:update|modify|change|edit|rename|set)\b"),
    ("add", r"\b(?:add|create|insert)\b"),
)

# Изменения полей при обновлении объекта: шаблон, поле, преобразование.
ADMIN_UPDATES = (
    (r"stay time (?:of |to )?(\d+)", "stayTime", int),
    (r"(\d+) second-class", "economyClass", int),
    (r"(\d+) first-class seats", "confortClass", int),
    (r"average speed (?:of |to )?(\d+)", "averageSpeed", int),
    (r"basic (?:price )?rate (?:of |to )?([\d.]+)", "basicPriceRate", float),
    (
        r"first-class (?:price )?rate (?:of |to )?([\d.]+)",
        "firstClassPriceRate",
        float,
    ),
    (r"\bvalue (?:of |to )?([\w.]+)", "value", str),
    (r"\bemail (?:to )?(\S+@\S+)", "email", str),
    (r"\bphone(?: number)? (?:to )?(\d+)", "phoneNumber", str),
)


class Client:
    """Пользователь веб-интерфейса: выполняет шаги сценария по очереди."""

    def __init__(self, it, scenario):
        """Создаёт клиента для интерпретатора ``it`` и сценария."""
        self.it = it
        self.web = it.web
        self.S = scenario
        self.ctx = RunContext.from_skeleton(it.p.sk.get("context"))
        self.user = (self.ctx.username, self.ctx.password)
        self.user_id = None
        self.token = None
        # Токены по ролям: администратор и пассажир входят независимо.
        self.tokens = {}
        self.role = "user"
        self.override_role = None
        self.is_admin = False
        self.new_user = None
        # Тип поезда, с которым сейчас работает клиент: gaotie или other.
        self.kind = "gaotie"
        self.trips = []
        self.trip = None
        self.trip_kind = None
        self.contacts = []
        self.contact = None
        self.new_contact = None
        self.food = None
        self.station_stores = None
        self.store_station = "suzhou"
        self.orders = {"gaotie": [], "other": []}
        self.initial_orders = {"gaotie": set(), "other": set()}
        self.order = None
        self.orders_opened = []
        self.consign = None
        self.route_id = None
        self.route_stations = None
        self.created_trip_ids = []
        self.admin_created = {}
        self.log = []
        self.last_status = None
        self.search_from = "Shang Hai"
        self.search_to = "Su Zhou"
        self.search_date = self.ctx.trip_date
        self.from_k, self.to_k = "shanghai", "suzhou"
        self.adv = None
        self.new_order_ids = []
        self.booked_kind = None
        self.last_booking = None
        self.last_rebook = None
        it.known_passwords[self.ctx.username] = self.ctx.password
        it.known_passwords[ADMIN_CREDENTIALS[0]] = ADMIN_CREDENTIALS[1]
        self._seed_orders()

    # ---------------------------------------------------------------- запросы

    def api(self, verb, path, body=None, query=None):
        """Отправляет запрос через шлюз и возвращает тело ответа."""
        b = JMap(body) if isinstance(body, dict) else body
        tok = self.tokens.get(self.override_role or self.role)
        auth = {"Authorization": "Bearer " + str(tok)} if tok else {}
        hdr = LibObj("HttpHeaders", map=JMap(auth))
        r = entry_request(self.web, verb, path, b, query, hdr)
        if r is None:
            self.log.append((verb, path, "no handler"))
            return None
        data = r.f.get("body")
        status = r.f.get("status")
        code = status.f.get("code") if isinstance(status, LibObj) else 200
        self.last_status = code
        is_dict = isinstance(data, dict)
        self.log.append(
            (
                verb,
                path,
                code,
                data.get("status") if is_dict else None,
                data.get("msg") if is_dict else None,
            )
        )
        return data

    def _seed_orders(self):
        t = self.it.tables
        self.initial_orders["gaotie"] = {r["id"] for r in t["orders"].rows}
        self.initial_orders["other"] = {
            r["id"] for r in t["orders_other"].rows
        }

    # --------------------------------------------------------- вспомогательное

    @staticmethod
    def data(resp, default=None):
        """Возвращает поле ``data`` ответа вида ``Response``."""
        if isinstance(resp, dict):
            return resp.get("data", default)
        return default

    def svc(self, kind=None):
        """Возвращает имя сервиса рейсов для типа поезда."""
        if (kind or self.kind) == "other":
            return "travel2service"
        return "travelservice"

    def order_svc(self, kind=None):
        """Возвращает префикс адресов сервиса заказов для типа поезда."""
        if (kind or self.kind) == "other":
            return "/api/v1/orderOtherService/orderOther"
        return "/api/v1/orderservice/order"

    @staticmethod
    def kind_of_trip_id(tid):
        """Определяет тип поезда по номеру рейса (G и D — скоростные)."""
        return "gaotie" if tid and tid[0] in "GD" else "other"

    def is_admin_context(self, t):
        """Проверяет, выполняет ли шаг администратор."""
        return "admin" in t or self.role == "admin"

    # ----------------------------------------------------- интерпретация шага

    def step(self, n, text):
        """Выполняет шаг сценария номер ``n`` и возвращает тело ответа."""
        t = text.lower()
        for rx, fn in self.RULES:
            if re.search(rx, t):
                # Административные шаги идут с токеном администратора.
                admin_rule = fn.__name__.startswith("s_admin_")
                if (admin_rule or "admin" in t) and "log in" not in t:
                    self.override_role = "admin"
                else:
                    self.override_role = None
                try:
                    return fn(self, text, t)
                finally:
                    self.override_role = None
        return self.fallback(text, t)

    # -------------------------------- запасной вариант для новых формулировок

    STOP = {
        "the",
        "a",
        "an",
        "of",
        "for",
        "on",
        "in",
        "to",
        "with",
        "and",
        "or",
        "by",
        "from",
        "at",
        "is",
        "are",
        "this",
        "that",
        "their",
        "they",
        "them",
        "it",
        "as",
        "all",
        "first",
        "new",
        "order",
        "orders",
    }

    @staticmethod
    def _words(txt):
        txt = re.sub(r"([a-z])([A-Z])", r"\1 \2", txt)
        return [
            w[:-1] if w.endswith("s") and len(w) > 3 else w
            for w in re.findall(r"[a-z]+", txt.lower())
        ]

    def _ctx_values(self):
        """Значения из состояния клиента по именам переменных и полей."""
        order = self.order if isinstance(self.order, dict) else {}
        contact = self.contact if isinstance(self.contact, dict) else {}
        return {
            "accountid": self.user_id,
            "userid": self.user_id,
            "loginid": self.user_id,
            "orderid": order.get("id"),
            "tripid": self.trip_id(self.trip) if self.trip else None,
            "trainnumber": order.get("trainNumber"),
            "contactsid": contact.get("id"),
            "routeid": self.route_id,
            "date": self.search_date,
            "traveldate": self.search_date,
            "departuretime": self.search_date,
            "startstation": self.from_k,
            "startplace": self.from_k,
            "from": self.from_k,
            "endstation": self.to_k,
            "endplace": self.to_k,
            "to": self.to_k,
            "seattype": SEAT_FIRST_CLASS,
        }

    def _fallback_body(self, ptype, ci):
        """Строит тело запроса из полей DTO и известного состояния."""
        dto = self.it.p.resolve(ptype, ci)
        if dto is None:
            return JMap()
        values = self._ctx_values()
        body = {}
        for f in self.it.p.all_fields(dto):
            v = values.get(f.name.lower())
            if v is not None:
                body[f.name] = v
        return JMap(body)

    def fallback(self, text, t):
        """Подбирает обработчик для шага, не распознанного правилами.

        Обработчик выбирается по общим словам шага с именем метода, классом
        и путём. Переменные пути и тело запроса заполняются из состояния
        клиента.
        """
        words = {
            w for w in self._words(text) if w not in self.STOP and len(w) > 2
        }
        best, best_score = None, 0.0
        for hs in self.web.handlers.values():
            for verb, tpl, mi, ci in hs:
                literal = " ".join(x for x in tpl if not x.startswith("{"))
                doc = (
                    set(self._words(mi.name))
                    | set(self._words(literal))
                    | set(self._words(ci.name))
                )
                common = words & doc
                if not common:
                    continue
                score = len(common) / (len(words) ** 0.5 * len(doc) ** 0.5)
                if score > best_score:
                    best, best_score = (verb, tpl, mi, ci), score
        if best is None or best_score < FALLBACK_MIN_SCORE:
            self.it.warn("unrecognized step: " + text[:60])
            return None
        verb, tpl, mi, ci = best
        values = self._ctx_values()
        segments = []
        for seg in tpl:
            if seg.startswith("{"):
                name = seg[1:-1].split(":")[0]
                segments.append(str(values.get(name.lower()) or "1"))
            else:
                segments.append(seg)
        body = None
        for ptype, _pname, annots in mi.params:
            if "RequestBody" in annots:
                body = self._fallback_body(ptype, ci)
        path = "/" + "/".join(segments)
        if self.is_admin_context(t) or "/admin" in path:
            self.override_role = "admin"
        try:
            return self.api(verb or "GET", path, body)
        finally:
            self.override_role = None

    # ---------------------------------------------------------------- аккаунт

    def s_register(self, text, t):
        """Регистрирует нового пассажира."""
        m = re.search(
            r"(?:username|user name|named)\s+['\"]?([A-Za-z0-9_]{3,})", text
        )
        name = m.group(1) if m else "newuser01"
        body = {
            "userName": name,
            "password": NEW_USER_PASSWORD,
            "gender": 1,
            "documentType": 1,
            "documentNum": "ID123456",
            "email": name + "@example.com",
        }
        self.new_user = (name, NEW_USER_PASSWORD)
        self.it.known_passwords[name] = NEW_USER_PASSWORD
        return self.api("POST", "/api/v1/userservice/users/register", body)

    def s_login(self, text, t):
        """Входит пассажиром, новым пользователем или администратором."""
        if "admin" in t:
            self.user = ADMIN_CREDENTIALS
            self.is_admin = True
        elif "new username" in t or "with the new" in t:
            self.user = self.new_user or self.user
            self.is_admin = False
        else:
            if not (self.new_user and "new" in t):
                self.user = (self.ctx.username, self.ctx.password)
            self.is_admin = False
        password = self.user[1]
        if re.search(r"\b(?:wrong|incorrect|invalid|bad)\b", t):
            password = password + "-wrong"
        body = {
            "username": self.user[0],
            "password": password,
            "verificationCode": "",
        }
        r = self.api("POST", "/api/v1/users/login", body)
        d = self.data(r)
        if isinstance(d, dict):
            self.role = "admin" if self.is_admin else "user"
            if not self.is_admin:
                self.user_id = d.get("userId")
            self.token = d.get("token")
            self.tokens[self.role] = d.get("token")
        return r

    def s_verify_code(self, text, t):
        """Запрашивает картинку с кодом подтверждения входа."""
        return self.api("GET", "/api/v1/verifycode/generate")

    # --------------------------------------------------------------- контакты

    def s_contacts(self, text, t):
        """Открывает книгу контактов и при необходимости берёт первый."""
        r = self.api(
            "GET", f"/api/v1/contactservice/contacts/account/{self.user_id}"
        )
        d = self.data(r)
        if isinstance(d, list):
            self.contacts = d
            if d and ("first contact" in t or "take" in t):
                self.contact = d[0]
        return r

    def s_add_contact(self, text, t):
        """Добавляет контакт пассажиру или через админ-консоль."""
        if "companion" in t:
            name = "Companion"
        elif "themselves" in t:
            name = self.user[0]
        else:
            name = "Contact"
        kind = "COMP" if "companion" in t else "SELF"
        body = {
            "accountId": self.user_id,
            "name": name,
            "documentType": 1,
            "documentNumber": "ID-" + kind + "-001",
            "phoneNumber": "13800000000",
        }
        if self.is_admin_context(t):
            return self.api("POST", _BASIC + "/contacts", body)
        r = self.api("POST", "/api/v1/contactservice/contacts", body)
        d = self.data(r)
        if isinstance(d, dict):
            self.new_contact = d
            if "themselves" in t or not self.contact:
                self.contact = d
        return r

    # ------------------------------------------------------------------ поиск

    def route_of(self, t):
        """Находит в тексте пару станций «from X to Y»."""
        m = re.search(
            r"from\s+([a-z ]+?)\s+to\s+([a-z ]+?)"
            r"(?:\s+(?:departing|on|with|via)\b|[,.(]|$)",
            t,
        )
        if m:
            return station_ui(m.group(1)), station_ui(m.group(2))
        return self.search_from, self.search_to

    def s_search(self, text, t):
        """Ищет рейсы между станциями на дату."""
        other = re.search(r"\bregular\b|'other'|\bother\b", t)
        kind = "other" if other else "gaotie"
        self.kind = kind
        self.search_from, self.search_to = self.route_of(t)
        self.search_date = parse_date(text, self.ctx.trip_date)
        body = {
            "startPlace": self.search_from,
            "endPlace": self.search_to,
            "departureTime": self.search_date + " 00:00:00",
        }
        r = self.api("POST", f"/api/v1/{self.svc(kind)}/trips/left", body)
        d = self.data(r)
        self.trips = d if isinstance(d, list) else []
        self.trip = self.trips[0] if self.trips else None
        self.trip_kind = kind
        self.from_k = station_key(self.search_from)
        self.to_k = station_key(self.search_to)
        if isinstance(self.trip, dict):
            self.from_k = self.trip.get("startStation") or self.from_k
            self.to_k = self.trip.get("terminalStation") or self.to_k
        return r

    def trip_id(self, trip):
        """Возвращает номер рейса (G1234) из ответа поиска."""
        if not isinstance(trip, dict):
            return None
        tid = trip.get("tripId")
        if isinstance(tid, dict):
            return str(tid.get("type")) + str(tid.get("number"))
        return tid

    def _trip_by_ordinal(self, t):
        """Рейс из последнего поиска по порядковому слову («second trip»)."""
        m = _ORDINAL_TRIP.search(t)
        if m:
            idx = ORDINALS[m.group(1)]
            if len(self.trips) > idx:
                return self.trips[idx]
        return None

    def s_trip_details(self, text, t):
        """Открывает сведения о выбранном рейсе."""
        trip = self._trip_by_ordinal(t) or self.trip
        if "new trip" in t and self.trips:
            created = [
                x
                for x in self.trips
                if self.trip_id(x) in self.created_trip_ids
            ]
            trip = (created or self.trips)[0]
        tid = self.trip_id(trip) if trip else None
        if tid is None and self.created_trip_ids:
            tid = self.created_trip_ids[-1]
        if tid is None:
            return None
        self.trip = trip
        kind = self.kind_of_trip_id(tid)
        self.kind = kind
        body = {
            "tripId": tid,
            "travelDate": self.search_date,
            "from": self.from_k,
            "to": self.to_k,
        }
        return self.api("POST", f"/api/v1/{self.svc(kind)}/trip_detail", body)

    def s_adv_search(self, text, t):
        """Выполняет расширенный поиск: дешёвые, быстрые, мало остановок.

        Тело несёт дату без времени: только тогда запрос мест к order-service
        находит заказы на эту дату, как в эталоне.
        """
        self.search_from, self.search_to = self.route_of(t)
        self.from_k = station_key(self.search_from)
        self.to_k = station_key(self.search_to)
        self.search_date = parse_date(text, self.ctx.trip_date)
        if "cheapest" in t:
            which = "cheapest"
        elif "quickest" in t:
            which = "quickest"
        else:
            which = "minStation"
        body = {
            "startPlace": self.search_from,
            "endPlace": self.search_to,
            "departureTime": self.search_date,
        }
        r = self.api(
            "POST", f"/api/v1/travelplanservice/travelPlan/{which}", body
        )
        if which == "cheapest":
            d = self.data(r)
            self.adv = d if isinstance(d, list) else []
            self.trips = []
            if self.adv:
                first = self.adv[0]
                tid = first.get("tripId") if isinstance(first, dict) else None
                if not isinstance(tid, str) and isinstance(first, dict):
                    tid = self.trip_id(first)
                if isinstance(tid, str):
                    self.trip = {"tripId": tid, "_adv": first}
                    self.kind = self.kind_of_trip_id(tid)
                    self.trip_kind = self.kind
        return r

    def s_transfer(self, text, t):
        """Ищет рейсы с пересадкой на промежуточной станции."""
        via = re.search(r"transfer at ([a-z ]+?)[ (,.]", t)
        via_ui = station_ui(via.group(1)) if via else "Su Zhou"
        body = {
            "startStation": self.search_from or "Shang Hai",
            "viaStation": via_ui,
            "endStation": self.search_to or "Nan Jing",
            "travelDate": parse_date(text, self.ctx.trip_date),
            "trainType": 0,
        }
        return self.api(
            "POST", "/api/v1/travelplanservice/travelPlan/transferResult", body
        )

    # -------------------------------------------------------------------- еда

    def s_food_menu(self, text, t):
        """Открывает меню еды выбранного рейса."""
        tid = self.trip_id(self.trip)
        if not tid:
            return None
        path = "/api/v1/foodservice/foods/%s/%s/%s/%s" % (
            self.search_date,
            self.from_k,
            self.to_k,
            tid,
        )
        r = self.api("GET", path)
        self.food = self.data(r)
        return r

    def s_food_stores(self, text, t):
        """Открывает список магазинов еды на станции."""
        m = re.search(r"at ([a-z ]+?) station", t)
        st = station_key(m.group(1)) if m else "suzhou"
        r = self.api(
            "POST",
            "/api/v1/stationfoodservice/stationfoodstores",
            JList([st]),
        )
        self.station_stores = self.data(r)
        self.store_station = st
        return r

    # ----------------------------------------------------------- бронирование

    def s_book(self, text, t):
        """Бронирует место на выбранном рейсе для контакта."""
        trip = self._trip_by_ordinal(t) or self.trip
        tid = self.trip_id(trip)
        if not tid and isinstance(trip, dict):
            tid = trip.get("tripId")
        if not tid:
            return None
        kind = self.kind_of_trip_id(tid)
        self.kind = kind
        contact = self.contact
        if ("new contact" in t or "companion" in t) and self.new_contact:
            contact = self.new_contact
        if re.search(r"first-class|first class", t):
            seat = SEAT_FIRST_CLASS
        else:
            seat = SEAT_SECOND_CLASS
        body = {
            "accountId": self.user_id,
            "contactsId": (
                contact.get("id") if isinstance(contact, dict) else None
            ),
            "tripId": tid,
            "seatType": seat,
            "date": self.search_date,
            "from": self.from_k,
            "to": self.to_k,
            "assurance": 0,
            "foodType": 0,
            "stationName": "",
            "storeName": "",
            "foodName": "",
            "foodPrice": 0.0,
            "handleDate": None,
            "consigneeName": None,
            "consigneePhone": None,
            "consigneeWeight": 0.0,
            "isWithin": False,
        }
        am = re.search(r"assurance \(insurance\) of the (\w+) type", t)
        refused = re.search(r"(no|without) assurance", t)
        listed_refusal = "without food, assurance" in t or "no assurance" in t
        if am and (not refused or not listed_refusal):
            body["assurance"] = ASSURANCE_TYPES.get(am.group(1), 1)
        if re.search(r"without food, assurance (or|and) consignment", t):
            body["assurance"] = 0
        no_food = re.search(r"(no|without) food", t)
        station_food = re.search(
            r"food from a station store|station food|with food from", t
        )
        if re.search(r"food on the train", t) and not no_food:
            tf = None
            if isinstance(self.food, dict):
                tf = self.food.get("trainFoodList")
            f0 = tf[0] if isinstance(tf, list) and tf else {}
            body.update(
                foodType=1,
                foodName=f0.get("foodName", "Soup"),
                foodPrice=float(f0.get("price", 3.0) or 0),
                stationName="",
                storeName="",
            )
        elif station_food and not no_food:
            body.update(foodType=2, **self._first_station_food())
        cm = re.search(r"consignment of ([\d.]+)\s*kg", t)
        if cm and not re.search(r"(no|without) (luggage )?consignment", t):
            body.update(
                handleDate=self.ctx.today,
                consigneeName="Consignee",
                consigneePhone="13800000001",
                consigneeWeight=float(cm.group(1)),
            )
        if kind == "other":
            path = "/api/v1/preserveotherservice/preserveOther"
        else:
            path = "/api/v1/preserveservice/preserve"
        r = self.api("POST", path, body)
        self.booked_kind = kind
        self.last_booking = body
        return r

    def _first_station_food(self):
        """Первое блюдо первого магазина на станции (как выбирает UI)."""
        stores = self.station_stores
        out = dict(
            stationName=self.store_station,
            storeName="",
            foodName="",
            foodPrice=0.0,
        )
        if isinstance(stores, list) and stores:
            s0 = stores[0]
            out["storeName"] = s0.get("storeName", "")
            fl = s0.get("foodList") or []
            if fl:
                out["foodName"] = fl[0].get("foodName", "")
                out["foodPrice"] = float(fl[0].get("price", 0) or 0)
        elif isinstance(self.food, dict):
            fm = self.food.get("foodStoreListMap") or {}
            for k, v in fm.items():
                if v:
                    out["stationName"] = k
                    out["storeName"] = v[0].get("storeName", "")
                    fl = v[0].get("foodList") or []
                    if fl:
                        out["foodName"] = fl[0].get("foodName", "")
                        out["foodPrice"] = float(fl[0].get("price", 0) or 0)
                    break
        return out

    # ----------------------------------------------------------------- заказы

    def order_list_kind(self, t):
        """Определяет, список заказов какого типа поездов открыт."""
        if re.search(r"high-speed|gaotie|dongche", t):
            return "gaotie"
        if re.search(r"regular|'other'|other type", t):
            return "other"
        return self.kind

    def s_orders(self, text, t):
        """Обновляет список заказов с фильтрами статуса и дат."""
        kind = self.order_list_kind(t)
        q = {
            "loginId": self.user_id,
            "enableStateQuery": False,
            "enableTravelDateQuery": False,
            "enableBoughtDateQuery": False,
            "travelDateStart": None,
            "travelDateEnd": None,
            "boughtDateStart": None,
            "boughtDateEnd": None,
            "state": 0,
        }
        if re.search(r"status", t):
            m = re.search(r"'(\w+)' status", t)
            name = (m.group(1) if m else "").lower()
            q.update(enableStateQuery=True, state=ORDER_STATUS.get(name, 1))
        if re.search(r"travel date", t):
            year = int(self.ctx.trip_date[:4])
            default = (self.ctx.today[:8] + "01", "%d-12-31" % year)
            start, end = month_range(text, year, default)
            q.update(
                enableTravelDateQuery=True,
                travelDateStart=start,
                travelDateEnd=end,
            )
        if re.search(r"purchase date|bought date|purchase", t):
            q.update(
                enableBoughtDateQuery=True,
                boughtDateStart=self.ctx.today,
                boughtDateEnd=self.ctx.today,
            )
        r = self.api("POST", self.order_svc(kind) + "/refresh", q)
        d = self.data(r)
        if isinstance(d, list):
            self.orders[kind] = d
            for o in d:
                oid = o.get("id")
                known = oid in self.initial_orders[kind]
                if not known and oid not in self.new_order_ids:
                    self.new_order_ids.append(oid)
        return r

    def new_orders(self, kind):
        """Возвращает заказы, созданные в этом сценарии."""
        return [
            o
            for o in self.orders.get(kind, [])
            if o.get("id") not in self.initial_orders[kind]
        ]

    def pick_new_order(self, t, kind):
        """Выбирает заказ по тексту шага: первый, второй или последний."""
        news = self.new_orders(kind) or list(self.orders.get(kind, []))
        if not news:
            return None
        news = _sorted_by_bought(news)
        if "second" in t and len(news) > 1:
            return news[1]
        if "first" in t:
            return news[0]
        if "latest" in t:
            return news[-1]
        return news[0] if len(news) == 1 else news[-1]

    def s_open_order(self, text, t):
        """Открывает заказ из списка."""
        kind = self.kind
        o = self.pick_new_order(t, kind)
        if o is None:
            return None
        self.order = o
        self.orders_opened.append(o)
        return self.api("GET", f"{self.order_svc(kind)}/{o['id']}")

    def s_order_price(self, text, t):
        """Запрашивает цену текущего заказа."""
        if not self.order:
            return None
        return self.api("GET", f"{self.order_svc()}/price/{self.order['id']}")

    def cur_order(self, t=""):
        """Текущий заказ: по тексту шага или последний открытый/новый."""
        o = self.order
        news = self.new_orders(self.kind)
        if "second" in t and len(news) > 1:
            return _sorted_by_bought(news)[1]
        if "first" in t and news:
            return _sorted_by_bought(news)[0]
        if o is None and news:
            o = news[-1]
        return o

    def s_pay(self, text, t):
        """Оплачивает неоплаченный заказ с внутреннего счёта."""
        if not self.order or "new order" in t:
            o = self.cur_order(t)
        else:
            o = self.order
        unpaid = _sorted_by_bought(
            x for x in self.new_orders(self.kind) if x.get("status") == 0
        )
        if "first" in t and "order" in t and unpaid:
            o = unpaid[0]
        elif "second" in t and len(unpaid) > 1:
            o = unpaid[1]
        elif "new order" in t and unpaid:
            o = unpaid[-1]
        elif unpaid:
            o = unpaid[0]
        if o is None:
            return None
        self.order = o
        body = {
            "userId": self.user_id,
            "orderId": o["id"],
            "tripId": o.get("trainNumber"),
        }
        r = self.api("POST", "/api/v1/inside_pay_service/inside_payment", body)
        self.mark(o, ORDER_STATUS["paid"], r)
        return r

    def mark(self, o, status, r):
        """Меняет статус заказа у клиента, если сервер ответил успехом."""
        ok = isinstance(r, dict) and r.get("status") == 1
        if ok and isinstance(o, dict):
            o["status"] = status

    def s_collect(self, text, t):
        """Получает билет по заказу."""
        o = self.order
        if o is None:
            return None
        r = self.api(
            "GET", f"/api/v1/executeservice/execute/collected/{o['id']}"
        )
        self.mark(o, ORDER_STATUS["collected"], r)
        return r

    def s_enter(self, text, t):
        """Проходит на станцию (посадка в поезд) по заказу."""
        o = self.order
        if o is None:
            return None
        r = self.api(
            "GET", f"/api/v1/executeservice/execute/execute/{o['id']}"
        )
        self.mark(o, ORDER_STATUS["used"], r)
        return r

    def s_refund_calc(self, text, t):
        """Узнаёт сумму возврата при отмене заказа."""
        o = self.order
        if o is None:
            return None
        return self.api(
            "GET", f"/api/v1/cancelservice/cancel/refound/{o['id']}"
        )

    def s_cancel(self, text, t):
        """Отменяет заказ."""
        o = self.order
        if o is None:
            return None
        r = self.api(
            "GET", f"/api/v1/cancelservice/cancel/{o['id']}/{self.user_id}"
        )
        self.mark(o, ORDER_STATUS["cancel"], r)
        return r

    def s_rebook(self, text, t):
        """Переоформляет билет на другой рейс или класс."""
        o = self.order
        if o is None:
            return None
        trip_id = o.get("trainNumber")
        other_trip = self._trip_by_ordinal(t)
        if other_trip is not None:
            trip_id = self.trip_id(other_trip)
        seat = SEAT_SECOND_CLASS if "second-class" in t else SEAT_FIRST_CLASS
        body = {
            "loginId": self.user_id,
            "orderId": o["id"],
            "oldTripId": o.get("trainNumber"),
            "tripId": trip_id,
            "seatType": seat,
            "date": self.search_date,
        }
        self.last_rebook = body
        return self.api("POST", "/api/v1/rebookservice/rebook", body)

    def s_rebook_difference(self, text, t):
        """Доплачивает разницу в цене после переоформления."""
        if self.last_rebook is None:
            return None
        return self.api(
            "POST", "/api/v1/rebookservice/rebook/difference", self.last_rebook
        )

    def s_book_or_rebook(self, text, t):
        """Выбирает между бронированием и переоформлением по началу шага."""
        if re.match(r"^(try to )?rebook", t):
            return self.s_rebook(text, t)
        return self.s_book(text, t)

    # ------------------------------------------------------- багаж, страховка

    def s_consign_order(self, text, t):
        """Открывает запись о перевозке багажа по заказу."""
        o = self.order
        if o is None:
            return None
        r = self.api("GET", f"/api/v1/consignservice/consigns/order/{o['id']}")
        d = self.data(r)
        if isinstance(d, dict):
            self.consign = d
        return r

    def s_consign_account(self, text, t):
        """Открывает все записи о багаже пассажира."""
        return self.api(
            "GET", f"/api/v1/consignservice/consigns/account/{self.user_id}"
        )

    def s_assurance_record(self, text, t):
        """Открывает страховку заказа."""
        o = self.order
        if o is None:
            return None
        return self.api(
            "GET", f"/api/v1/assuranceservice/assurance/orderid/{o['id']}"
        )

    def s_assurance_types(self, text, t):
        """Открывает список видов страховки."""
        return self.api("GET", "/api/v1/assuranceservice/assurances/types")

    def s_consign_price(self, text, t):
        """Узнаёт цену перевозки багажа заданного веса."""
        m = re.search(r"([\d.]+)\s*kg", t)
        w = m.group(1) if m else "1"
        within = "true" if "within" in t else "false"
        return self.api(
            "GET", f"/api/v1/consignpriceservice/consignprice/{w}/{within}"
        )

    def s_change_consignee(self, text, t):
        """Меняет получателя багажа в записи о перевозке."""
        c = self.consign
        if not isinstance(c, dict):
            return None
        body = dict(c)
        body["consignee"] = "NewConsignee"
        body["phone"] = "13900000002"
        return self.api("PUT", "/api/v1/consignservice/consigns", body)

    # ---------------------------------------------------------- администратор

    def s_admin_station(self, text, t):
        """Добавляет станцию."""
        m = re.search(r"station ([a-z ]+?) with a stay time of (\d+)", t)
        if m:
            name, stay = station_key(m.group(1)), int(m.group(2))
        else:
            nm = re.search(r"station ([a-z ]+?)(?:\s+with\b|[,.(]|$)", t)
            st = re.search(r"stay time of (\d+)", t)
            name = station_key(nm.group(1)) if nm else "newstation"
            stay = int(st.group(1)) if st else 5
        body = {"id": name, "name": name, "stayTime": stay}
        self.admin_created["station"] = body
        return self.api("POST", _BASIC + "/stations", body)

    def s_admin_train(self, text, t):
        """Добавляет тип поезда."""
        nm = re.search(r"train type (\w+)", text)
        name = nm.group(1) if nm else "NewTrainType"
        economy = re.search(r"(\d+) second-class", t)
        comfort = re.search(r"(\d+) first-class", t)
        speed = re.search(r"speed of (\d+)", t)
        body = {
            "id": name,
            "name": name,
            "economyClass": int(economy.group(1)) if economy else 100,
            "confortClass": int(comfort.group(1)) if comfort else 30,
            "averageSpeed": int(speed.group(1)) if speed else 300,
        }
        self.admin_created["train"] = body
        return self.api("POST", _BASIC + "/trains", body)

    @staticmethod
    def _route_stations_of(t):
        """Станции маршрута из «route A — B — C with distances …»."""
        m = re.search(r"route (.+?) with distances", t)
        if not m:
            return None
        names = [s for s in _ROUTE_SEPARATORS.split(m.group(1)) if s.strip()]
        return [station_key(s) for s in names] if len(names) > 1 else None

    def s_admin_route(self, text, t):
        """Добавляет маршрут со станциями и расстояниями."""
        ds = re.search(r"distances ([\d, and]+)", t)
        dist = re.findall(r"\d+", ds.group(1)) if ds else ["0", "100", "250"]
        stations = self._route_stations_of(t) or [
            "shanghai",
            "suzhou",
            "ningbo",
        ]
        self.route_stations = stations
        body = {
            "loginId": self.user_id,
            "id": "",
            "stationList": ",".join(stations),
            "distanceList": ",".join(dist),
            "startStation": stations[0],
            "endStation": stations[-1],
        }
        r = self.api("POST", "/api/v1/adminrouteservice/adminroute", body)
        d = self.data(r)
        if isinstance(d, dict):
            self.route_id = d.get("id")
        self.admin_created["route"] = body
        return r

    def s_admin_price(self, text, t):
        """Добавляет тарифы для типа поезда на маршруте."""
        tt = re.search(r"train type (\w+)", text)
        basic = re.search(r"basic rate ([\d.]+)", t)
        first = re.search(r"first-class rate ([\d.]+)", t)
        body = {
            "trainType": tt.group(1) if tt else "GaoTieSix",
            "routeId": self.route_id,
            "basicPriceRate": float(basic.group(1)) if basic else 0.5,
            "firstClassPriceRate": float(first.group(1)) if first else 1.2,
        }
        self.admin_created["price"] = body
        return self.api("POST", _BASIC + "/prices", body)

    def _trip_stations(self, t):
        """Начальная, промежуточные и конечная станции нового рейса."""
        m = re.search(
            r"from ([a-z ]+?) via ([a-z ,]+?) to ([a-z ]+?)"
            r"(?:[,.(]|$|\s+dep)",
            t,
        )
        if m:
            via = [
                station_key(s)
                for s in re.split(r",|\band\b", m.group(2))
                if s.strip()
            ]
            return station_key(m.group(1)), via, station_key(m.group(3))
        if self.route_stations:
            st = self.route_stations
            return st[0], st[1:-1], st[-1]
        return "shanghai", ["suzhou"], "ningbo"

    def s_admin_trip(self, text, t):
        """Добавляет рейс на маршрут."""
        tid = re.search(r"trip (\w+) of type (\w+)", text)
        times = re.findall(r"(\d\d:\d\d)", text)
        start, via, end = self._trip_stations(t)
        trip_id = tid.group(1) if tid else "G9101"
        depart = times[0] if times else "09:00"
        arrive = times[1] if len(times) > 1 else "12:00"
        body = {
            "loginId": self.user_id,
            "tripId": trip_id,
            "trainTypeName": tid.group(2) if tid else "GaoTieSix",
            "routeId": self.route_id,
            "startStationName": start,
            "stationsName": ",".join(via),
            "terminalStationName": end,
            "startTime": "2013-05-04 " + depart + ":00",
            "endTime": "2013-05-04 " + arrive + ":00",
        }
        self.created_trip_ids.append(trip_id)
        self.admin_created["trip"] = body
        return self.api("POST", "/api/v1/admintravelservice/admintravel", body)

    def s_admin_orders(self, text, t):
        """Открывает список всех заказов системы."""
        return self.api("GET", "/api/v1/adminorderservice/adminorder")

    @staticmethod
    def _admin_entity(t):
        """Объект админ-консоли, упомянутый в шаге первым."""
        best = None
        for ent in ADMIN_ENTITIES:
            m = ent.pattern.search(t)
            if m and (best is None or m.start() < best[0]):
                best = (m.start(), ent)
        return best[1] if best else None

    def _admin_rows(self, ent):
        rows = []
        for table in ent.tables:
            if table in self.it.tables:
                rows.extend(self.it.tables[table].rows)
        return rows

    @staticmethod
    def _row_names(ent, row):
        """Имена, по которым объект можно упомянуть в тексте шага."""
        if ent.name == "trip":
            letter = TRIP_TYPE_LETTERS[int(row.get("type") or 0)]
            return [letter + str(row.get("number"))]
        keys = ("name", "user_name", "train_type", "document_number", "id")
        return [str(row[k]) for k in keys if row.get(k)]

    def _admin_target(self, ent, t):
        """Находит объект, упомянутый в шаге или созданный ранее."""
        if ent.name == "order":
            return self.order if isinstance(self.order, dict) else None
        rows = self._admin_rows(ent)
        flat = re.sub(r"\s+", "", t)
        best, best_len = None, 0
        for row in rows:
            for name in self._row_names(ent, row):
                key = re.sub(r"\s+", "", name.lower())
                if len(key) >= 3 and key in flat and len(key) > best_len:
                    best, best_len = row, len(key)
        if best is not None:
            return best
        created = self.admin_created.get(ent.name)
        if created is not None:
            for row in rows:
                camel = {snake_to_camel(k): v for k, v in row.items()}
                same = all(
                    camel.get(k) == v for k, v in created.items() if k in camel
                )
                if same:
                    return row
        return rows[0] if rows else None

    def _route_body(self, row):
        """Тело изменения маршрута: станции и расстояния через запятую."""
        rid = row["id"]
        tables = self.it.tables

        def joined(table, value, order):
            items = [r for r in tables[table].rows if r["route_id"] == rid]
            items.sort(key=lambda r: r[order])
            return ",".join(str(r[value]) for r in items)

        return {
            "id": rid,
            "stationList": joined(
                "route_stations", "stations", "stations_order"
            ),
            "distanceList": joined(
                "route_distances", "distances", "distances_order"
            ),
            "startStation": row.get("start_station"),
            "endStation": row.get("end_station"),
        }

    def _admin_body(self, ent, row):
        """Тело запроса изменения: значения объекта, как их показывает UI."""
        if ent.name == "route":
            return self._route_body(row)
        if ent.name == "order":
            body = {snake_to_camel(k): v for k, v in row.items()}
            if "fromStation" in body:
                body["from"] = body.pop("fromStation")
            if "toStation" in body:
                body["to"] = body.pop("toStation")
            return body
        body = {snake_to_camel(k): row[k] for k in ent.fields if k in row}
        if ent.name == "trip":
            body["tripId"] = self._row_names(ent, row)[0]
        return body

    def _admin_delete_path(self, ent, row):
        values = {}
        for k, v in row.items():
            values[k] = v
            values[snake_to_camel(k)] = v
        if ent.name == "trip":
            values["tripId"] = self._row_names(ent, row)[0]
        return ent.path + "/" + ent.delete_tpl.format(**values)

    def s_admin_crud(self, text, t):
        """Список, добавление, изменение и удаление в админ-консоли."""
        if not self.is_admin_context(t):
            self.override_role = None
            return self.fallback(text, t)
        ent = self._admin_entity(t)
        if ent is None:
            return self.fallback(text, t)
        op, first_pos = "list", None
        for name, pattern in ADMIN_OPERATIONS:
            m = re.search(pattern, t)
            if m and (first_pos is None or m.start() < first_pos):
                op, first_pos = name, m.start()
        if op == "list":
            return self.api("GET", ent.path)
        if op == "add":
            return self._admin_add(ent, text, t)
        row = self._admin_target(ent, t)
        if row is None:
            return None
        if op == "delete":
            return self.api("DELETE", self._admin_delete_path(ent, row))
        body = self._admin_body(ent, row)
        for pattern, field, conv in ADMIN_UPDATES:
            m = re.search(pattern, t)
            if m and field in body:
                body[field] = conv(m.group(1))
        verb = "POST" if ent.name == "route" else "PUT"
        return self.api(verb, ent.path, body)

    def _admin_add(self, ent, text, t):
        """Добавляет объект через админ-консоль."""
        specific = {
            "station": self.s_admin_station,
            "train": self.s_admin_train,
            "route": self.s_admin_route,
            "price": self.s_admin_price,
            "trip": self.s_admin_trip,
        }
        if ent.name in specific:
            return specific[ent.name](text, t)
        name = re.search(r"(?:named|called|name)\s+['\"]?([\w.-]+)", text)
        label = name.group(1) if name else "New" + ent.name.title()
        if ent.name == "config":
            value = re.search(r"\bvalue\s+([\w.]+)", t)
            body = {
                "name": label,
                "value": value.group(1) if value else "0",
                "description": label,
            }
        elif ent.name == "contact":
            body = {
                "accountId": self.user_id,
                "name": label,
                "documentType": 1,
                "documentNumber": "ID-ADMIN-001",
                "phoneNumber": "13800000000",
            }
        elif ent.name == "user":
            self.it.known_passwords[label] = NEW_USER_PASSWORD
            body = {
                "userName": label,
                "password": NEW_USER_PASSWORD,
                "gender": 1,
                "documentType": 1,
                "documentNum": "ID-ADMIN-001",
                "email": label + "@example.com",
            }
        else:
            row = self._admin_target(ent, t)
            body = self._admin_body(ent, row) if row else {}
        self.admin_created[ent.name] = body
        return self.api("POST", ent.path, body)

    # Порядок важен: более специфичные правила стоят раньше.
    RULES = [
        (r"register a new", s_register),
        (r"log in|login", s_login),
        (r"add a (new )?station", s_admin_station),
        (r"add a new train type", s_admin_train),
        (r"add a new route", s_admin_route),
        (r"add a price configuration", s_admin_price),
        (r"add a new high-speed trip|add a new trip", s_admin_trip),
        (r"list of all orders", s_admin_orders),
        (r"add a (new )?contact", s_add_contact),
        (r"advanced search", s_adv_search),
        (r"trips with a transfer|transfer at", s_transfer),
        (r"^search", s_search),
        (r"open the details of", s_trip_details),
        (r"food menu", s_food_menu),
        (r"food stores", s_food_stores),
        (r"contact book", s_contacts),
        (r"^book|^rebook the|book one|book a|book another", s_book_or_rebook),
        (r"refresh the list of orders", s_orders),
        (r"open the (first |second )?(new )?order", s_open_order),
        (r"price of the order", s_order_price),
        (r"price difference|pay the difference", s_rebook_difference),
        (r"^pay", s_pay),
        (r"collect the ticket", s_collect),
        (r"enter the station", s_enter),
        (r"how much would be refunded", s_refund_calc),
        (r"try to cancel|^cancel", s_cancel),
        (r"try to rebook|^rebook", s_rebook),
        (
            r"luggage consignment record|consignment of the order"
            r"|look up the luggage consignment of",
            s_consign_order,
        ),
        (r"consignments registered on the account", s_consign_account),
        (
            r"assurance \(insurance\) record|assurance record",
            s_assurance_record,
        ),
        (r"assurance types", s_assurance_types),
        (
            r"consignment within the region costs|what a .* consignment",
            s_consign_price,
        ),
        (r"change the consignee", s_change_consignee),
        (r"verification code|captcha", s_verify_code),
        (
            r"\b(?:list|delete|remove|update|modify|change|edit|rename|add"
            r"|create|open|view|show|browse)\b",
            s_admin_crud,
        ),
    ]
