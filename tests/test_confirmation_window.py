import json
from datetime import date
from pathlib import Path

from agent.hr_rules import confirmation_due
from harness.verify import independent as ind

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def test_due_and_overdue():
    emps = json.loads((FIX / "employee_samples.json").read_text(encoding="utf-8"))
    ids = {d.employee_id for d in confirmation_due(emps, date(2026, 9, 28))}
    assert "emp-due" in ids
    emps.append({
        "id": "emp-overdue",
        "first_name": "Old",
        "last_name": "P",
        "status": "active",
        "probation_end_date": "2025-05-26",
    })
    ids = {d.employee_id for d in confirmation_due(emps, date(2026, 9, 28))}
    assert "emp-overdue" in ids


def test_skip_left():
    emps = json.loads((FIX / "employee_samples.json").read_text(encoding="utf-8"))
    ids = {d.employee_id for d in confirmation_due(emps, date(2026, 9, 28))}
    assert "emp-left" not in ids


def test_skip_far():
    emps = json.loads((FIX / "employee_samples.json").read_text(encoding="utf-8"))
    ids = {d.employee_id for d in confirmation_due(emps, date(2026, 9, 28))}
    assert "emp-far" not in ids


def test_verifier_matches_rules():
    emps = json.loads((FIX / "employee_samples.json").read_text(encoding="utf-8"))
    day = date(2026, 9, 28)
    assert {d.employee_id for d in confirmation_due(emps, day)} == ind.expected_confirmation(emps, day)
