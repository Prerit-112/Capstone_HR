import json
from pathlib import Path

from agent.hr_rules import flag_attendance
from harness.verify import independent as ind

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def _att():
    return json.loads((FIX / "attendance_samples.json").read_text())


def test_null_punches():
    flags = {(f.attendance_id, f.reason) for f in flag_attendance(_att())}
    assert ("att-present-null", "present_with_null_punches") in flags


def test_checkout_before_checkin():
    flags = {(f.attendance_id, f.reason) for f in flag_attendance(_att())}
    assert ("att-punch-order", "check_out_before_check_in") in flags


def test_lop_zero_hours():
    flags = {(f.attendance_id, f.reason) for f in flag_attendance(_att())}
    assert ("att-lop-zero", "is_lop") in flags
    assert ("att-lop-zero", "is_lop_with_zero_hours") in flags


def test_absent_no_leave():
    flags = {(f.attendance_id, f.reason) for f in flag_attendance(_att(), leaves=[])}
    assert ("att-absent-no-leave", "absent_without_overlapping_leave") in flags


def test_absent_with_leave_ok():
    leave = [{
        "id": "L1",
        "employee_id": "emp-no-leave",
        "from_date": "2026-09-15",
        "to_date": "2026-09-15",
        "status": "approved",
    }]
    flags = {(f.attendance_id, f.reason) for f in flag_attendance(_att(), leaves=leave)}
    assert ("att-absent-no-leave", "absent_without_overlapping_leave") not in flags


def test_rules_match_verifier():
    att = _att()
    leave = json.loads((FIX / "leave_samples.json").read_text())
    a = {(f.attendance_id, f.reason) for f in flag_attendance(att, leaves=leave)}
    b = ind.expected_attendance_flags(att, leave)
    assert a == b


def test_present_on_holiday():
    from datetime import date

    rows = [{
        "id": "h1",
        "employee_id": "e1",
        "date": "2026-01-26",
        "status": "present",
        "check_in": "09:00",
        "check_out": "18:00",
        "is_lop": False,
    }]
    hol = {date(2026, 1, 26)}
    flags = {(f.attendance_id, f.reason) for f in flag_attendance(rows, holiday_dates=hol)}
    assert ("h1", "present_on_holiday") in flags
    assert ("h1", "present_on_holiday") in ind.expected_attendance_flags(rows, [], hol)


def test_lop_int_truthy():
    # live MCP sometimes sends is_lop as 0/1
    rows = [{
        "id": "x1",
        "employee_id": "e1",
        "date": "2026-09-17",
        "status": "present",
        "check_in": "09:00",
        "check_out": "18:00",
        "is_lop": 1,
        "lop_hours": 0,
    }]
    flags = {(f.attendance_id, f.reason) for f in flag_attendance(rows)}
    assert ("x1", "is_lop") in flags
    assert ("x1", "is_lop_with_zero_hours") in flags


def test_draft_leave_doesnt_cover():
    rows = [{
        "id": "a1",
        "employee_id": "e1",
        "date": "2026-09-15",
        "status": "absent",
        "check_in": None,
        "check_out": None,
        "is_lop": False,
    }]
    leave = [{
        "id": "L1",
        "employee_id": "e1",
        "from_date": "2026-09-15",
        "to_date": "2026-09-15",
        "status": "draft",
    }]
    flags = {(f.attendance_id, f.reason) for f in flag_attendance(rows, leaves=leave)}
    assert ("a1", "absent_without_overlapping_leave") in flags
