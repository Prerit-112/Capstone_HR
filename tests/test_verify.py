from datetime import date

from agent.hr_rules import holiday_dates, week_containing
from agent.journal import RunJournal, Step
from agent.loop import _merge_helper_findings
from harness.verify import verify_write_conflict
from harness.verify.independent import (
    expected_balance_ids,
    holiday_dates_from_lists,
)


def test_child_holiday_not_span():
    rows = [{
        "id": "L1",
        "from_date": "2026-01-01",
        "to_date": "2026-12-31",
        "holidays": [{"date": "2026-01-26", "description": "Republic Day"}],
    }]
    assert holiday_dates(rows) == {date(2026, 1, 26)}
    assert holiday_dates_from_lists(rows) == {date(2026, 1, 26)}


def test_empty_kids():
    rows = [{"from_date": "2026-01-01", "to_date": "2026-12-31", "holidays": []}]
    assert holiday_dates_from_lists(rows) == set()


def test_week_bounds():
    assert week_containing(date(2026, 1, 26)) == (date(2026, 1, 26), date(2026, 2, 1))
    assert week_containing(date(2026, 10, 7)) == (date(2026, 10, 5), date(2026, 10, 11))


def test_balance_filter():
    rows = [
        {"id": "b1", "employee_id": "e1", "balance_days": -1},
        {"id": "b2", "employee_id": "e2", "balance_days": 3},
    ]
    assert expected_balance_ids(rows, "e1") == {"b1"}


def test_conflict_ok():
    j = RunJournal(task_id="write_conflict_abort")
    j.claimed_success = False
    j.ended = "refused"
    j.final_answer = {
        "findings": {},
        "claimed_success": False,
        "refused": {
            "is_refusal": True,
            "why": "shared_book_conflict: record changed",
            "escalate_to": "re-read; Team 12 may have edited this row",
        },
        "uncertain": ["row changed between get and write"],
    }
    j.add(Step("guard", "Attendance.update", False, "shared_book_conflict: record changed since last read — write aborted"))
    assert verify_write_conflict(j)["outcome"] == "verified_pass"


def test_conflict_lied():
    j = RunJournal(task_id="write_conflict_abort")
    j.claimed_success = True
    j.ended = "done"
    j.final_answer = {"claimed_success": True, "refused": {"is_refusal": False}}
    j.add(Step("tool", "Attendance.update", True, args={"id": "x"}))
    assert verify_write_conflict(j)["outcome"] == "false_success"


def test_merge_flags():
    parsed = {"findings": {"attendance_flags": [{"attendance_id": "x", "reason": "is_lop"}]}}
    helpers = {
        "hr__scan_attendance_flags": {
            "flags": [
                {"attendance_id": "a", "reason": "is_lop"},
                {"attendance_id": "b", "reason": "present_with_null_punches"},
            ]
        }
    }
    out = _merge_helper_findings(parsed, helpers)
    assert len(out["findings"]["attendance_flags"]) == 2


def test_merge_empty_holiday():
    parsed = {"claimed_success": True, "findings": {}, "uncertain": []}
    out = _merge_helper_findings(parsed, {"hr__scan_holidays": {"catalogue_empty": True, "holidays": []}})
    assert out["claimed_success"] is False
    assert any("HolidayList" in u for u in out["uncertain"])


def test_merge_empty_types():
    parsed = {"findings": {}, "uncertain": []}
    helpers = {
        "hr__scan_leave_balances": {
            "leave_type_catalogue_empty": True,
            "balances": [{"leave_balance_id": "b1", "balance_days": -1}],
        }
    }
    out = _merge_helper_findings(parsed, helpers)
    assert out["findings"]["leave_balances"][0]["leave_balance_id"] == "b1"
    assert any("LeaveType" in u for u in out["uncertain"])


def test_compare_sets_missing():
    from harness.verify.independent import compare_sets

    c = compare_sets({"a", "b"}, {"a"}, label="x")
    assert not c["match"]
    assert c["missing"] == ["b"]


def test_fingerprint_skips_noise():
    from agent.loop import _record_fingerprint

    a = {"id": "1", "status": "present", "updated_at": "t1", "_transitions": ["x"]}
    b = {"id": "1", "status": "present", "updated_at": "t2", "_transitions": ["y"]}
    assert _record_fingerprint(a) == _record_fingerprint(b)


def test_att_payload_keeps_punches():
    from harness.adversary import attendance_update_payload

    row = {
        "id": "a1",
        "employee_id": "e1",
        "date": "2026-09-24",
        "status": "present",
        "check_in": "09:00",
        "check_out": "18:00",
        "overtime_hours": 0,
        "is_lop": 0,
    }
    p = attendance_update_payload(row, overtime_hours=0.25)
    assert p["check_in"] == "09:00"
    assert p["check_out"] == "18:00"
    assert p["overtime_hours"] == 0.25
