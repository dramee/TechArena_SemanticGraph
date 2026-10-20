"""Эмулятор клиента: шаги сценария (текст) -> HTTP-запросы к шлюзу, с запоминанием состояния между шагами
(токен, найденные рейсы, контакты, заказы ...), как это делает веб-интерфейс Train Ticket."""
import re, collections
from values import *
from web import entry_request
import lib

MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"])}

STATION_UI = {"shanghai": "Shang Hai", "suzhou": "Su Zhou", "nanjing": "Nan Jing", "beijing": "Bei Jing", "ning bo": "Ning Bo",
              "ningbo": "Ning Bo", "hangzhou": "Hang Zhou", "taiyuan": "Tai Yuan", "wuxi": "Wu Xi", "xuzhou": "Xu Zhou"}


def station_ui(name):
    k = re.sub(r"\s+", " ", name.strip().lower())
    return STATION_UI.get(k) or STATION_UI.get(k.replace(" ", "")) or name.strip().title()


def station_key(name):
    return re.sub(r"\s+", "", name.strip().lower())


def parse_date(text, default="2026-10-01"):
    m = re.search(r"(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(\d{4})", text, re.I)
    if m:
        return "%s-%02d-%02d" % (m.group(3), MONTHS[m.group(2).lower()], int(m.group(1)))
    return default


def raw(v):
    """Результат для клиента: значения интерпретатора -> обычные Python-структуры."""
    return v


class Client:
    TODAY = "2026-09-15"

    def __init__(self, it, scenario):
        self.it = it
        self.web = it.web
        self.S = scenario
        self.text_all = " ".join([scenario.get("title", ""), scenario.get("description", "")] +
                                 [s.get("action", "") for s in scenario.get("steps", [])]).lower()
        self.user = ("fdse_microservice", "111111")
        self.user_id = None
        self.token = None                         # токен текущей роли
        self.tokens = {}                          # роль -> токен (администратор и пассажир входят независимо)
        self.role = "user"
        self.override_role = None
        self.is_admin = False
        self.new_user = None
        self.kind = "gaotie"                      # gaotie | other: тип поезда, с которым сейчас работает клиент
        self.trips = []                           # последний результат поиска (список dict)
        self.trip = None                          # выбранный рейс
        self.trip_kind = None
        self.contacts = []
        self.contact = None
        self.new_contact = None
        self.food = None                          # ответ меню еды
        self.orders = {"gaotie": [], "other": []}
        self.initial_orders = {"gaotie": set(), "other": set()}
        self.order = None                         # текущий заказ (dict)
        self.orders_opened = []                   # заказы, открытые по шагам «Open the ... new order»
        self.consign = None
        self.route_id = None
        self.log = []
        self.last_status = None
        self.search_from = "Shang Hai"
        self.search_to = "Su Zhou"
        self.search_date = "2026-10-01"
        self.from_k, self.to_k = "shanghai", "suzhou"
        self.adv = None
        self.new_order_ids = []
        self.booked_kind = None
        self._seed_orders()

    # ------------------------------------------------------------------ запросы
    def api(self, verb, path, body=None, query=None):
        b = JMap(body) if isinstance(body, dict) else body
        tok = self.tokens.get(self.override_role or self.role)
        hdr = LibObj("HttpHeaders", map=JMap({"Authorization": "Bearer " + str(tok)} if tok else {}))
        r = entry_request(self.web, verb, path, b, query, hdr)
        if r is None:
            self.log.append((verb, path, "no handler"))
            return None
        data = r.f.get("body")
        code = r.f["status"].f.get("code") if isinstance(r.f.get("status"), LibObj) else 200
        self.last_status = code
        self.log.append((verb, path, code, (data.get("status") if isinstance(data, dict) else None), (data.get("msg") if isinstance(data, dict) else None)))
        return data

    def _seed_orders(self):
        t = self.it.tables
        self.initial_orders["gaotie"] = {r["id"] for r in t["orders"].rows}
        self.initial_orders["other"] = {r["id"] for r in t["orders_other"].rows}

    # ------------------------------------------------------------------ вспомогательное
    @staticmethod
    def data(resp, default=None):
        if isinstance(resp, dict):
            return resp.get("data", default)
        return default

    def svc(self, kind=None):
        return "travel2service" if (kind or self.kind) == "other" else "travelservice"

    def order_svc(self, kind=None):
        return "/api/v1/orderOtherService/orderOther" if (kind or self.kind) == "other" else "/api/v1/orderservice/order"

    @staticmethod
    def kind_of_trip_id(tid):
        return "gaotie" if tid and tid[0] in "GD" else "other"

    # ------------------------------------------------------------------ интерпретация шага
    def step(self, n, text):
        t = text.lower()
        for rx, fn in self.RULES:
            if re.search(rx, t):
                # административные шаги выполняются с токеном администратора, остальные — с токеном текущей роли
                self.override_role = "admin" if (getattr(fn, "__name__", "").startswith("s_admin_") or re.search(r"admin", t))                     and "log in" not in t else None
                try:
                    return fn(self, text, t)
                finally:
                    self.override_role = None
        return self.fallback(text, t)

    # ------------------------------------------------------------------ запасной вариант для незнакомых формулировок
    STOP = {"the", "a", "an", "of", "for", "on", "in", "to", "with", "and", "or", "by", "from", "at", "is", "are", "this", "that",
            "their", "they", "them", "it", "as", "all", "first", "new", "order", "orders"}

    @staticmethod
    def _words(txt):
        txt = re.sub(r"([a-z])([A-Z])", r" ", txt)
        return [w[:-1] if w.endswith("s") and len(w) > 3 else w for w in re.findall(r"[a-z]+", txt.lower())]

    def fallback(self, text, t):
        """Шаг не распознан правилами: выбрать обработчик по пересечению слов с именем метода и путём и вызвать его
        с типовыми аргументами (идентификаторы — из состояния клиента)."""
        words = {w for w in self._words(text) if w not in self.STOP and len(w) > 2}
        best, bs = None, 0.0
        for module, hs in self.web.handlers.items():
            for verb, tpl, mi, ci in hs:
                doc = set(self._words(mi.name)) | set(self._words(" ".join(x for x in tpl if not x.startswith("{")))) | set(self._words(ci.name))
                common = words & doc
                if not common:
                    continue
                sc = len(common) / (len(words) ** 0.5 * len(doc) ** 0.5)
                if sc > bs:
                    best, bs = (module, verb, tpl, mi, ci), sc
        if best is None or bs < 0.35:
            self.it.warn("unrecognized step: " + text[:60])
            return None
        module, verb, tpl, mi, ci = best
        ctx = {"accountId": self.user_id, "userId": self.user_id, "loginId": self.user_id, "id": self.user_id,
               "orderId": (self.order or {}).get("id") if isinstance(self.order, dict) else None,
               "tripId": self.trip_id(self.trip) if self.trip else None}
        pv = {}
        for seg in tpl:
            if seg.startswith("{"):
                nm = seg[1:-1].split(":")[0]
                pv[nm] = str(ctx.get(nm) or "1")
        path = "/" + "/".join(pv.get(seg[1:-1].split(":")[0], seg) if seg.startswith("{") else seg for seg in tpl)
        body = None
        for pt, pn, an in mi.params:
            if "RequestBody" in an:
                body = JMap()
        return self.api(verb or "GET", path, body)

    # --- аккаунт
    def s_register(self, text, t):
        name = "newuser01"
        body = {"userName": name, "password": "111111", "gender": 1, "documentType": 1,
                "documentNum": "ID123456", "email": "newuser01@example.com"}
        self.new_user = (name, "111111")
        return self.api("POST", "/api/v1/userservice/users/register", body)

    def s_login(self, text, t):
        if "admin" in t:
            self.user = ("admin", "222222")
            self.is_admin = True
        elif "new username" in t or "with the new" in t:
            self.user = self.new_user or self.user
            self.is_admin = False
        else:
            if self.is_admin or self.token is None or "passenger" in t or True:
                if not (self.new_user and "new" in t):
                    self.user = ("fdse_microservice", "111111")
            self.is_admin = False
        r = self.api("POST", "/api/v1/users/login", {"username": self.user[0], "password": self.user[1], "verificationCode": ""})
        d = self.data(r)
        if isinstance(d, dict):
            self.role = "admin" if self.is_admin else "user"
            if not self.is_admin:
                self.user_id = d.get("userId")
            self.token = d.get("token")
            self.tokens[self.role] = d.get("token")
        return r

    # --- контакты
    def s_contacts(self, text, t):
        r = self.api("GET", f"/api/v1/contactservice/contacts/account/{self.user_id}")
        d = self.data(r)
        if isinstance(d, list):
            self.contacts = d
            if d and ("first contact" in t or "take" in t):
                self.contact = d[0]
        return r

    def s_add_contact(self, text, t):
        body = {"accountId": self.user_id, "name": "Companion" if "companion" in t else (self.user[0] if "themselves" in t else "Contact"),
                "documentType": 1, "documentNumber": "ID-" + ("COMP" if "companion" in t else "SELF") + "-001", "phoneNumber": "13800000000"}
        r = self.api("POST", "/api/v1/contactservice/contacts", body)
        d = self.data(r)
        if isinstance(d, dict):
            self.new_contact = d
            if "themselves" in t or not self.contact:
                self.contact = d
        return r

    # --- поиск
    def route_of(self, t):
        m = re.search(r"from\s+([a-z ]+?)\s+to\s+([a-z ]+?)(?:\s+(?:departing|on|with|via)\b|[,.(]|$)", t)
        if m:
            return station_ui(m.group(1)), station_ui(m.group(2))
        return self.search_from, self.search_to

    def s_search(self, text, t):
        kind = "other" if re.search(r"regular|'other'|other", t) else "gaotie"
        self.kind = kind
        self.search_from, self.search_to = self.route_of(t)
        self.search_date = parse_date(text)
        body = {"startPlace": self.search_from, "endPlace": self.search_to, "departureTime": self.search_date + " 00:00:00"}
        r = self.api("POST", f"/api/v1/{self.svc(kind)}/trips/left", body)
        d = self.data(r)
        self.trips = d if isinstance(d, list) else []
        self.trip = self.trips[0] if self.trips else None
        self.trip_kind = kind
        self.from_k, self.to_k = station_key(self.search_from), station_key(self.search_to)
        if isinstance(self.trip, dict):
            self.from_k = self.trip.get("startStation") or self.from_k
            self.to_k = self.trip.get("terminalStation") or self.to_k
        return r

    def trip_id(self, trip):
        if not isinstance(trip, dict):
            return None
        tid = trip.get("tripId")
        if isinstance(tid, dict):
            return str(tid.get("type")) + str(tid.get("number"))
        return tid

    def s_trip_details(self, text, t):
        trip = self.trip
        if "second" in t and len(self.trips) > 1:
            trip = self.trips[1]
        if "new trip" in t and self.trips:
            trip = self.trips[0]
        tid = self.trip_id(trip) if trip else None
        if tid is None and self.S.get("_g9101"):
            tid = "G9101"
        if tid is None:
            return None
        self.trip = trip
        kind = self.kind_of_trip_id(tid)
        self.kind = kind
        body = {"tripId": tid, "travelDate": self.search_date, "from": self.from_k, "to": self.to_k}
        return self.api("POST", f"/api/v1/{self.svc(kind)}/trip_detail", body)

    def s_adv_search(self, text, t):
        self.search_from, self.search_to = self.route_of(t)
        self.from_k, self.to_k = station_key(self.search_from), station_key(self.search_to)
        self.search_date = parse_date(text)
        which = "cheapest" if "cheapest" in t else ("quickest" if "quickest" in t else "minStation")
        body = {"startPlace": self.search_from, "endPlace": self.search_to, "departureTime": self.search_date}
        r = self.api("POST", f"/api/v1/travelplanservice/travelPlan/{which}", body)
        if which == "cheapest":
            d = self.data(r)
            self.adv = d if isinstance(d, list) else []
            self.trips = []
            if self.adv:
                first = self.adv[0]
                tid = first.get("tripId") if isinstance(first, dict) else None
                tid = tid if isinstance(tid, str) else (self.trip_id(first) if isinstance(first, dict) else None)
                if isinstance(tid, str):
                    self.trip = {"tripId": tid, "_adv": first}
                    self.kind = self.kind_of_trip_id(tid)
                    self.trip_kind = self.kind
        return r

    def s_transfer(self, text, t):
        via = re.search(r"transfer at ([a-z ]+?)[ (,.]", t)
        via_ui = station_ui(via.group(1)) if via else "Su Zhou"
        body = {"startStation": self.search_from or "Shang Hai", "viaStation": via_ui, "endStation": self.search_to or "Nan Jing",
                "travelDate": parse_date(text), "trainType": 0}
        return self.api("POST", "/api/v1/travelplanservice/travelPlan/transferResult", body)

    # --- еда
    def s_food_menu(self, text, t):
        tid = self.trip_id(self.trip)
        if not tid:
            return None
        r = self.api("GET", f"/api/v1/foodservice/foods/{self.search_date}/{self.from_k}/{self.to_k}/{tid}")
        self.food = self.data(r)
        return r

    def s_food_stores(self, text, t):
        m = re.search(r"at ([a-z ]+?) station", t)
        st = station_key(m.group(1)) if m else "suzhou"
        r = self.api("POST", "/api/v1/stationfoodservice/stationfoodstores", JList([st]))
        self.station_stores = self.data(r)
        self.store_station = st
        return r

    # --- бронирование
    def s_book(self, text, t):
        tid = self.trip_id(self.trip) or (self.trip.get("tripId") if isinstance(self.trip, dict) else None)
        if not tid:
            return None
        kind = self.kind_of_trip_id(tid)
        self.kind = kind
        contact = self.contact
        if ("new contact" in t or "companion" in t) and self.new_contact:
            contact = self.new_contact
        seat = 2 if re.search(r"first-class|first class", t) else 3
        body = {"accountId": self.user_id, "contactsId": contact.get("id") if isinstance(contact, dict) else None,
                "tripId": tid, "seatType": seat, "date": self.search_date, "from": self.from_k, "to": self.to_k,
                "assurance": 0, "foodType": 0, "stationName": "", "storeName": "", "foodName": "", "foodPrice": 0.0,
                "handleDate": None, "consigneeName": None, "consigneePhone": None, "consigneeWeight": 0.0, "isWithin": False}
        am = re.search(r"assurance \(insurance\) of the (\w+) type", t)
        if am and not re.search(r"(no|without) assurance", t) or (am and "without food, assurance" not in t and "no assurance" not in t):
            body["assurance"] = {"first": 1, "second": 2, "third": 3}.get(am.group(1), 1) if am else 0
        if re.search(r"without food, assurance|no assurance|without assurance|without food or assurance", t):
            body["assurance"] = 0 if not am else body["assurance"]
        if re.search(r"without food, assurance or consignment|without food, assurance and consignment", t):
            body["assurance"] = 0
        if re.search(r"with food on the train|food on the train", t) and not re.search(r"(no|without) food", t):
            tf = (self.food or {}).get("trainFoodList") if isinstance(self.food, dict) else None
            f0 = tf[0] if isinstance(tf, list) and tf else {}
            body.update(foodType=1, foodName=f0.get("foodName", "Soup"), foodPrice=float(f0.get("price", 3.0) or 0), stationName="", storeName="")
        elif re.search(r"food from a station store|station food|with food from", t) and not re.search(r"(no|without) food", t):
            sf = self._first_station_food()
            body.update(foodType=2, **sf)
        cm = re.search(r"consignment of ([\d.]+)\s*kg", t)
        if cm and not re.search(r"(no|without) (luggage )?consignment", t):
            body.update(handleDate=self.TODAY, consigneeName="Consignee", consigneePhone="13800000001", consigneeWeight=float(cm.group(1)))
        r = self.api("POST", "/api/v1/preserveotherservice/preserveOther" if kind == "other" else "/api/v1/preserveservice/preserve", body)
        self.booked_kind = kind
        self.last_booking = body
        return r

    def _first_station_food(self):
        stores = getattr(self, "station_stores", None)
        st = getattr(self, "store_station", "suzhou")
        out = dict(stationName=st, storeName="", foodName="", foodPrice=0.0)
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

    # --- заказы
    def order_list_kind(self, t):
        if re.search(r"high-speed|gaotie|dongche", t):
            return "gaotie"
        if re.search(r"regular|'other'|other type", t):
            return "other"
        return self.kind

    def s_orders(self, text, t):
        kind = self.order_list_kind(t)
        q = {"loginId": self.user_id, "enableStateQuery": False, "enableTravelDateQuery": False, "enableBoughtDateQuery": False,
             "travelDateStart": None, "travelDateEnd": None, "boughtDateStart": None, "boughtDateEnd": None, "state": 0}
        if re.search(r"status", t):
            m = re.search(r"'(\w+)' status", t)
            st = {"paid": 1, "cancel": 4, "notpaid": 0, "collected": 2, "refunded": 5, "used": 6, "change": 3}.get((m.group(1) if m else "").lower(), 1)
            q.update(enableStateQuery=True, state=st)
        if re.search(r"travel date", t):
            q.update(enableTravelDateQuery=True, travelDateStart="2026-09-01", travelDateEnd="2026-12-31")
        if re.search(r"purchase date|bought date|purchase", t):
            q.update(enableBoughtDateQuery=True, boughtDateStart=self.TODAY, boughtDateEnd=self.TODAY)
        r = self.api("POST", self.order_svc(kind) + "/refresh", q)
        d = self.data(r)
        if isinstance(d, list):
            self.orders[kind] = d
            new = [o for o in d if o.get("id") not in self.initial_orders[kind] and o.get("id") not in self.new_order_ids]
            for o in new:
                self.new_order_ids.append(o["id"])
        return r

    def new_orders(self, kind):
        return [o for o in self.orders.get(kind, []) if o.get("id") not in self.initial_orders[kind]]

    def pick_new_order(self, t, kind):
        news = self.new_orders(kind)
        if not news:
            news = [o for o in self.orders.get(kind, [])]
        if not news:
            return None
        news = sorted(news, key=lambda o: o.get("boughtDate", ""))
        if "second" in t and len(news) > 1:
            return news[1]
        if "first" in t:
            return news[0]
        return news[-1] if "latest" in t else news[0] if len(news) == 1 else news[-1]

    def s_open_order(self, text, t):
        kind = self.kind
        o = self.pick_new_order(t, kind)
        if o is None:
            return None
        self.order = o
        self.orders_opened.append(o)
        return self.api("GET", f"{self.order_svc(kind)}/{o['id']}")

    def s_order_price(self, text, t):
        if not self.order:
            return None
        return self.api("GET", f"{self.order_svc()}/price/{self.order['id']}")

    def cur_order(self, t=""):
        """Текущий заказ для оплаты/отмены: по тексту или последний открытый/новый."""
        if re.search(r"the new order|new order", t) and self.orders_opened and False:
            return self.orders_opened[-1]
        o = self.order
        news = self.new_orders(self.kind)
        if "second" in t and len(news) > 1:
            return sorted(news, key=lambda x: x.get("boughtDate", ""))[1]
        if "first" in t and news:
            return sorted(news, key=lambda x: x.get("boughtDate", ""))[0]
        if o is None and news:
            o = news[-1]
        return o

    def refresh_current(self, o):
        """Свежие данные заказа из БД клиента (после оплаты и т.п.)."""
        return o

    def s_pay(self, text, t):
        o = self.cur_order(t) if not self.order or "new order" in t else self.order
        # оплачиваем «текущий» неоплаченный заказ
        cands = [x for x in self.new_orders(self.kind) if x.get("status") == 0]
        if "first" in t and "order" in t and cands:
            o = sorted(cands, key=lambda x: x.get("boughtDate", ""))[0]
        elif "second" in t and len(cands) > 1:
            o = sorted(cands, key=lambda x: x.get("boughtDate", ""))[1]
        elif "new order" in t and cands:
            o = sorted(cands, key=lambda x: x.get("boughtDate", ""))[-1]
        elif cands:
            o = sorted(cands, key=lambda x: x.get("boughtDate", ""))[0]
        if o is None:
            return None
        self.order = o
        body = {"userId": self.user_id, "orderId": o["id"], "tripId": o.get("trainNumber")}
        r = self.api("POST", "/api/v1/inside_pay_service/inside_payment", body)
        self.mark(o, 1, r)
        return r

    def mark(self, o, status, r):
        """Клиент обновляет статус у себя, если сервер ответил успехом (как перерисовка списка в UI)."""
        if isinstance(r, dict) and r.get("status") == 1 and isinstance(o, dict):
            o["status"] = status

    def s_collect(self, text, t):
        o = self.order
        if o is None:
            return None
        r = self.api("GET", f"/api/v1/executeservice/execute/collected/{o['id']}")
        self.mark(o, 2, r)
        return r

    def s_enter(self, text, t):
        o = self.order
        if o is None:
            return None
        r = self.api("GET", f"/api/v1/executeservice/execute/execute/{o['id']}")
        self.mark(o, 6, r)
        return r

    def s_refund_calc(self, text, t):
        o = self.order
        if o is None:
            return None
        return self.api("GET", f"/api/v1/cancelservice/cancel/refound/{o['id']}")

    def s_cancel(self, text, t):
        o = self.order
        if o is None:
            return None
        r = self.api("GET", f"/api/v1/cancelservice/cancel/{o['id']}/{self.user_id}")
        self.mark(o, 4, r)
        return r

    def s_rebook(self, text, t):
        o = self.order
        if o is None:
            return None
        trip_id = o.get("trainNumber")
        if "second high-speed trip" in t and len(self.trips) > 1:
            trip_id = self.trip_id(self.trips[1])
        seat = 3 if re.search(r"second-class", t) else 2
        body = {"loginId": self.user_id, "orderId": o["id"], "oldTripId": o.get("trainNumber"), "tripId": trip_id,
                "seatType": seat, "date": self.search_date}
        return self.api("POST", "/api/v1/rebookservice/rebook", body)

    # --- багаж / страховка
    def s_consign_order(self, text, t):
        o = self.order
        if o is None:
            return None
        r = self.api("GET", f"/api/v1/consignservice/consigns/order/{o['id']}")
        d = self.data(r)
        if isinstance(d, dict):
            self.consign = d
        return r

    def s_consign_account(self, text, t):
        return self.api("GET", f"/api/v1/consignservice/consigns/account/{self.user_id}")

    def s_assurance_record(self, text, t):
        o = self.order
        if o is None:
            return None
        return self.api("GET", f"/api/v1/assuranceservice/assurance/orderid/{o['id']}")

    def s_assurance_types(self, text, t):
        return self.api("GET", "/api/v1/assuranceservice/assurances/types")

    def s_consign_price(self, text, t):
        m = re.search(r"([\d.]+)\s*kg", t)
        w = m.group(1) if m else "1"
        within = "true" if "within" in t else "false"
        return self.api("GET", f"/api/v1/consignpriceservice/consignprice/{w}/{within}")

    def s_change_consignee(self, text, t):
        c = self.consign
        if not isinstance(c, dict):
            return None
        body = dict(c)
        body["consignee"] = "NewConsignee"
        body["phone"] = "13900000002"
        return self.api("PUT", "/api/v1/consignservice/consigns", body)

    # --- администратор
    def s_admin_station(self, text, t):
        m = re.search(r"station ([a-z ]+?) with a stay time of (\d+)", t)
        name = station_key(m.group(1)) if m else "ningbo"
        stay = int(m.group(2)) if m else 5
        return self.api("POST", "/api/v1/adminbasicservice/adminbasic/stations", {"id": name, "name": name, "stayTime": stay})

    def s_admin_train(self, text, t):
        m = re.search(r"train type (\w+) with (\d+) second-class and (\d+) first-class seats and an average speed of (\d+)", t)
        name = re.search(r"train type (\w+)", text).group(1)
        e, c, sp = (int(m.group(2)), int(m.group(3)), int(m.group(4))) if m else (100, 30, 300)
        return self.api("POST", "/api/v1/adminbasicservice/adminbasic/trains", {"id": name, "name": name, "economyClass": e, "confortClass": c, "averageSpeed": sp})

    def s_admin_route(self, text, t):
        ds = re.search(r"distances ([\d, and]+)", t)
        dist = re.findall(r"\d+", ds.group(1)) if ds else ["0", "100", "250"]
        stations = ["shanghai", "suzhou", "ningbo"]
        body = {"loginId": self.user_id, "id": "", "stationList": ",".join(stations), "distanceList": ",".join(dist),
                "startStation": stations[0], "endStation": stations[-1]}
        r = self.api("POST", "/api/v1/adminrouteservice/adminroute", body)
        d = self.data(r)
        if isinstance(d, dict):
            self.route_id = d.get("id")
        return r

    def s_admin_price(self, text, t):
        tt = re.search(r"train type (\w+)", text)
        basic = re.search(r"basic rate ([\d.]+)", t)
        first = re.search(r"first-class rate ([\d.]+)", t)
        body = {"trainType": tt.group(1) if tt else "GaoTieSix", "routeId": self.route_id,
                "basicPriceRate": float(basic.group(1)) if basic else 0.5, "firstClassPriceRate": float(first.group(1)) if first else 1.2}
        return self.api("POST", "/api/v1/adminbasicservice/adminbasic/prices", body)

    def s_admin_trip(self, text, t):
        tid = re.search(r"trip (\w+) of type (\w+)", text)
        times = re.findall(r"(\d\d:\d\d)", text)
        body = {"loginId": self.user_id, "tripId": tid.group(1) if tid else "G9101", "trainTypeName": tid.group(2) if tid else "GaoTieSix",
                "routeId": self.route_id, "startStationName": "shanghai", "stationsName": "suzhou", "terminalStationName": "ningbo",
                "startTime": "2013-05-04 " + (times[0] if times else "09:00") + ":00",
                "endTime": "2013-05-04 " + (times[1] if len(times) > 1 else "12:00") + ":00"}
        self.S["_g9101"] = True
        return self.api("POST", "/api/v1/admintravelservice/admintravel", body)

    def s_admin_orders(self, text, t):
        return self.api("GET", "/api/v1/adminorderservice/adminorder")

    # порядок важен: более специфичные правила раньше
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
        (r"^book|^rebook the|book one|book a|book another", None),   # заполняется ниже
        (r"refresh the list of orders", s_orders),
        (r"open the (first |second )?(new )?order", s_open_order),
        (r"price of the order", s_order_price),
        (r"^pay", s_pay),
        (r"collect the ticket", s_collect),
        (r"enter the station", s_enter),
        (r"how much would be refunded", s_refund_calc),
        (r"try to cancel|^cancel", s_cancel),
        (r"try to rebook|^rebook", s_rebook),
        (r"luggage consignment record|consignment of the order|look up the luggage consignment of", s_consign_order),
        (r"consignments registered on the account", s_consign_account),
        (r"assurance \(insurance\) record|assurance record", s_assurance_record),
        (r"assurance types", s_assurance_types),
        (r"consignment within the region costs|what a .* consignment", s_consign_price),
        (r"change the consignee", s_change_consignee),
    ]


def _book_rule(self, text, t):
    if re.match(r"^(try to )?rebook", t):
        return Client.s_rebook(self, text, t)
    return Client.s_book(self, text, t)


Client.RULES = [(rx, (_book_rule if fn is None else fn)) for rx, fn in Client.RULES]
