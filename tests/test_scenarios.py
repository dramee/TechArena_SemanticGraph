"""Ответы на сценарии S0–S7: эталон S0 и подтверждённые ответы S1–S7."""

import hashlib
import json
import os

import pytest

from solution.tools.compare import RELATIONS

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _by_relation(edges):
    out = {rel: set() for rel in RELATIONS}
    for e in edges:
        out[e["relation"]].add((e["source"], e["target"]))
    return out


def test_s0_matches_gold_exactly(answer):
    edges, errors = answer("S0")
    with open(os.path.join(ROOT, "gold", "S0.json"), encoding="utf-8") as f:
        gold = json.load(f)["scenarios"]["S0"]
    got = _by_relation(edges)
    assert errors == []
    assert got["executes"] == {("scenario:S0", m) for m in gold["methods"]}
    for rel in ("calls", "remote", "data"):
        assert got[rel] == {tuple(pair) for pair in gold[rel]}, rel


with open(os.path.join(DATA, "expected_edges.json"), encoding="utf-8") as f:
    EXPECTED = json.load(f)


@pytest.mark.parametrize("sid", sorted(EXPECTED))
def test_answer_matches_confirmed_result(answer, sid):
    """Ответы S1–S7 дали на платформе 1.000; любое изменение — регрессия."""
    edges, errors = answer(sid)
    assert errors == []
    got = _by_relation(edges)
    for rel in RELATIONS:
        lines = sorted(f"{a} {b}" for a, b in got[rel])
        digest = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
        assert len(lines) == EXPECTED[sid][rel]["count"], (sid, rel)
        assert digest == EXPECTED[sid][rel]["sha256"], (sid, rel)
