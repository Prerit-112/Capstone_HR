import json
from datetime import date
from pathlib import Path

from agent.hr_rules import leaves_in_window, next_week_window, overlaps
from harness.verify import independent as ind

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def test_mid_range_hits():
    # bug 2: equality filters miss this on the server
    assert overlaps("2026-11-10", "2026-11-15", date(2026, 11, 12), date(2026, 11, 12))


def test_no_hit_outside():
    assert not overlaps("2026-11-10", "2026-11-15", date(2026, 11, 1), date(2026, 11, 2))


def test_next_week_from_mon():
    assert next_week_window(date(2026, 9, 28)) == (date(2026, 10, 5), date(2026, 10, 11))


def test_next_week_from_sun():
    assert next_week_window(date(2026, 9, 27)) == (date(2026, 9, 28), date(2026, 10, 4))


def test_pending_in_window_draft_out():
    rows = json.loads((FIX / "leave_samples.json").read_text())
    hit = {x.leave_id for x in leaves_in_window(rows, date(2026, 10, 12), date(2026, 10, 12))}
    assert "b1e2d154-963c-4d1e-ab61-d7eaae4cd6e1" in hit
    assert "aa4dd201-a18f-48a1-afa4-f97ff26481f1" not in hit


def test_agent_and_verifier_same_ids():
    rows = json.loads((FIX / "leave_samples.json").read_text())
    a, b = date(2026, 9, 28), date(2026, 10, 4)
    assert {x.leave_id for x in leaves_in_window(rows, a, b)} == ind.expected_on_leave(rows, a, b)
