import json
from pathlib import Path

from agent.hr_rules import flag_attendance
from harness.verify import independent as ind

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def _rows():
    return json.loads((FIX / "attendance_samples.json").read_text(encoding="utf-8"))


def test_null_punches():
    got = {(f.attendance_id, f.reason) for f in flag_attendance(_rows())}
    assert ("att-present-null", "present_with_null_punches") in got


def test_punch_order():
    got = {(f.attendance_id, f.reason) for f in flag_attendance(_rows())}
    assert ("att-punch-order", "check_out_before_check_in") in got


def test_lop_zero():
    got = {(f.attendance_id, f.reason) for f in flag_attendance(_rows())}
    assert ("att-lop-zero", "is_lop") in got
    assert ("att-lop-zero", "is_lop_with_zero_hours") in got


def test_absent_no_leave():
    got = {(f.attendance_id, f.reason) for f in flag_attendance(_rows(), leaves=[])}
    assert ("att-absent-no-leave", "absent_without_overlapping_leave") in got


def test_absent_covered():
    leave = [{
        "id": "L1",
        "employee_id": "emp-no-leave",
        "from_date": "2026-09-15",
        "to_date": "2026-09-15",
        "status": "approved",
    }]
    got = {(f.attendance_id, f.reason) for f in flag_attendance(_rows(), leaves=leave)}
    assert ("att-absent-no-leave", "absent_without_overlapping_leave") not in got


def test_verifier_matches_rules():
    att = _rows()
    leave = json.loads((FIX / "leave_samples.json").read_text(encoding="utf-8"))
    a = {(f.attendance_id, f.reason) for f in flag_attendance(att, leaves=leave)}
    assert a == ind.expected_attendance_flags(att, leave)
