"""Вспомогательные инструменты: IoU и сборка диагностических сдач."""

from solution.tools.compare import iou
from solution.tools.make_probe import apply_edits


def test_iou_follows_platform_rules():
    assert iou(set(), set()) == 1.0
    assert iou({1}, set()) == 0.0
    assert iou({1, 2, 3}, {2, 3, 4, 5}) == 2 / 5


def test_apply_edits_adds_and_removes_edges():
    answer = {
        "project": "p",
        "scenarios": {
            "S1": {
                "edges": [
                    {"source": "a", "relation": "calls", "target": "b"},
                    {"source": "a", "relation": "calls", "target": "c"},
                ]
            }
        },
    }
    edits = {
        "S1": {
            "add": [["x", "calls", "y"], ["a", "calls", "b"]],
            "remove": [["a", "calls", "c"]],
        }
    }
    got = apply_edits(answer, edits)["scenarios"]["S1"]["edges"]
    triples = [(e["source"], e["relation"], e["target"]) for e in got]
    assert triples == [("a", "calls", "b"), ("x", "calls", "y")]
    assert len(answer["scenarios"]["S1"]["edges"]) == 2
