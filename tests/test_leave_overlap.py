import json
from datetime import date
from pathlib import Path

from agent.hr_rules import leaves_in_window, next_week_window, overlaps
from harness.verify import independent as ind

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def test_overlap_midspan():
    assert overlaps("2026-11-10", "2026-11-15", date(2026, 11, 12), date(2026, 11, 12))


def test_overlap_outside():
    assert not overlaps("2026-11-10", "2026-11-15", date(2026, 11, 1), date(2026, 11, 2))


def test_next_week_monday():
    assert next_week_window(date(2026, 9, 28)) == (date(2026, 10, 5), date(2026, 10, 11))


def test_next_week_sunday():
    assert next_week_window(date(2026, 9, 27)) == (date(2026, 9, 28), date(2026, 10, 4))


def test_leaves_status_and_overlap():
    rows = json.loads((FIX / "leave_samples.json").read_text(encoding="utf-8"))
    hit = leaves_in_window(rows, date(2026, 10, 12), date(2026, 10, 12))
    ids = {x.leave_id for x in hit}
    assert "b1e2d154-963c-4d1e-ab61-d7eaae4cd6e1" in ids
    assert "aa4dd201-a18f-48a1-afa4-f97ff26481f1" not in ids


def test_verifier_matches_rules():
    rows = json.loads((FIX / "leave_samples.json").read_text(encoding="utf-8"))
    a, b = date(2026, 9, 28), date(2026, 10, 4)
    assert {x.leave_id for x in leaves_in_window(rows, a, b)} == ind.expected_on_leave(rows, a, b)
