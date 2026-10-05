import json
from datetime import date
from pathlib import Path

from agent.hr_rules import confirmation_due
from harness.verify import independent as ind

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def _emps():
    return json.loads((FIX / "employee_samples.json").read_text())


def test_due_soon():
    ids = {d.employee_id for d in confirmation_due(_emps(), date(2026, 9, 28))}
    assert "emp-due" in ids


def test_overdue_counts():
    emps = _emps()
    emps.append({
        "id": "emp-overdue",
        "first_name": "Old",
        "last_name": "P",
        "status": "active",
        "probation_end_date": "2025-05-26",
    })
    ids = {d.employee_id for d in confirmation_due(emps, date(2026, 9, 28))}
    assert "emp-overdue" in ids


def test_left_skipped():
    ids = {d.employee_id for d in confirmation_due(_emps(), date(2026, 9, 28))}
    assert "emp-left" not in ids


def test_far_out_skipped():
    ids = {d.employee_id for d in confirmation_due(_emps(), date(2026, 9, 28))}
    assert "emp-far" not in ids


def test_rules_match_verifier():
    emps = _emps()
    day = date(2026, 9, 28)
    assert {d.employee_id for d in confirmation_due(emps, day)} == ind.expected_confirmation(emps, day)


def test_suspended_skipped():
    emps = _emps()
    emps.append({
        "id": "emp-sus",
        "first_name": "Sus",
        "status": "suspended",
        "probation_end_date": "2026-09-20",
    })
    ids = {d.employee_id for d in confirmation_due(emps, date(2026, 9, 28))}
    assert "emp-sus" not in ids
