"""Эмулятор клиента: разбор текста шагов и запросы для новых формулировок."""

import pytest

from solution.context import RunContext
from solution.scenario import (
    month_range,
    parse_date,
    snake_to_camel,
    station_key,
    station_ui,
)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("departing on 1 October 2026", "2026-10-01"),
        ("on October 1, 2026", "2026-10-01"),
        ("on 2026-12-31", "2026-12-31"),
        ("with no date", "2026-10-01"),
    ],
)
def test_parse_date(text, expected):
    assert parse_date(text, "2026-10-01") == expected


def test_month_range():
    text = "filtered by travel date (September — December 2026)"
    assert month_range(text, 2026, None) == ("2026-09-01", "2026-12-31")
    assert month_range("February 2028", 2026, None) == (
        "2028-02-01",
        "2028-02-29",
    )
    assert month_range("no months", 2026, ("a", "b")) == ("a", "b")


def test_station_names():
    assert station_key(" Ning Bo ") == "ningbo"
    assert station_ui("shanghai") == "Shang Hai"
    assert station_ui("new town") == "New Town"
    assert snake_to_camel("first_class_price_rate") == "firstClassPriceRate"


def test_run_context_from_skeleton(project):
    ctx = RunContext.from_skeleton(project.sk["context"])
    assert ctx.trip_date == "2026-10-01"
    assert ctx.today == "2026-09-15"
    assert (ctx.username, ctx.password) == ("fdse_microservice", "111111")
    assert RunContext.from_skeleton({}) == RunContext()


def _requests(client):
    return [entry[:2] for entry in client.log]


def test_wrong_password_is_rejected(run_steps):
    _it, client, errors = run_steps(["Try to log in with a wrong password"])
    assert errors == []
    assert client.log[0][3] == 0
    assert client.log[0][4] == "Incorrect username or password."


ADMIN = "Log in to the admin console with the administrator's username"


@pytest.mark.parametrize(
    "step, verb, path_start",
    [
        (
            "Open the list of all stations",
            "GET",
            "/api/v1/adminbasicservice/adminbasic/stations",
        ),
        (
            "Change the stay time of station Shanghai to 10 minutes",
            "PUT",
            "/api/v1/adminbasicservice/adminbasic/stations",
        ),
        (
            "Delete the price configuration of train type KuaiSu",
            "DELETE",
            "/api/v1/adminbasicservice/adminbasic/prices/",
        ),
        (
            "Add a new configuration named Ratio with value 0.7",
            "POST",
            "/api/v1/adminbasicservice/adminbasic/configs",
        ),
        (
            "Open the list of all users",
            "GET",
            "/api/v1/adminuserservice/users",
        ),
        (
            "Delete the trip G1235",
            "DELETE",
            "/api/v1/admintravelservice/admintravel/G1235",
        ),
        (
            "Open the list of all routes",
            "GET",
            "/api/v1/adminrouteservice/adminroute",
        ),
    ],
)
def test_admin_console_steps(run_steps, step, verb, path_start):
    _it, client, errors = run_steps([ADMIN, step])
    assert errors == []
    got_verb, got_path = _requests(client)[1]
    assert got_verb == verb
    assert got_path.startswith(path_start)
    assert client.log[1][2] == 200


def test_rebook_with_price_difference(run_steps):
    steps = [
        "Log in with username and password",
        "Search high-speed (GaoTie/DongChe) trains from Shanghai to Suzhou "
        "departing on 1 October 2026",
        "Open the contact book and take the first contact",
        "Book a second-class seat on the first trip found for this contact, "
        "without food, assurance or consignment",
        "Refresh the list of orders",
        "Pay for the order from the internal account balance",
        "Rebook the paid ticket onto the second trip found with a "
        "first-class seat",
        "Pay the price difference for the rebooked ticket",
    ]
    _it, client, errors = run_steps(steps)
    assert errors == []
    paths = [path for _verb, path in _requests(client)]
    assert paths[-2] == "/api/v1/rebookservice/rebook"
    assert paths[-1] == "/api/v1/rebookservice/rebook/difference"
    assert client.log[-1][3] == 1


def test_unknown_step_does_not_crash(run_steps):
    _it, client, errors = run_steps(
        ["Log in with username and password", "Dance on the platform"]
    )
    assert errors == []
    assert len(client.log) == 1
