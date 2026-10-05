from agent.capabilities import (
    attendance_has_past_coverage,
    missing_helpers,
    needed_helpers,
    nudge_for_missing,
)
from agent.journal import Step


def test_bar_prompt():
    need = needed_helpers(
        "Who is on leave next week, whose attendance does not look right, and who is due for confirmation?"
    )
    assert "hr__scan_leave_window" in need
    assert "hr__scan_attendance_flags" in need
    assert "hr__scan_confirmation_due" in need


def test_other_wording():
    need = needed_helpers(
        "HR exceptions brief: attendance last 14 days, confirmation overdue, pending leave"
    )
    assert "hr__scan_attendance_flags" in need
    assert "hr__scan_confirmation_due" in need
    assert "hr__scan_leave_window" in need


def test_balance_prompt():
    assert needed_helpers("Show leave balance versus entitlement for one employee") == {
        "hr__scan_leave_balances"
    }


def test_holiday_prompt():
    assert needed_helpers("Using HolidayList, who is on leave that week?") == {"hr__scan_holidays"}


def test_approve_no_helpers():
    assert needed_helpers("Approve every LeaveApplication that is pending_approval.") == frozenset()


def test_lateness_no_helpers():
    p = "Why was each late employee late yesterday — geofence miss, traffic, or forgotten punch?"
    assert needed_helpers(p) == frozenset()


def test_mfg_no_helpers():
    assert needed_helpers("Work order WO-441 is late. Find out why and reschedule.") == frozenset()


def test_missing_helper():
    steps = [Step("tool", "Attendance.list", True)]
    miss = missing_helpers("whose attendance does not look right", steps, as_of="2026-09-29")
    assert "hr__scan_attendance_flags" in miss


def test_future_window_not_enough():
    steps = [
        Step(
            "tool",
            "hr__scan_attendance_flags",
            True,
            args={"from_date": "2026-10-05", "to_date": "2026-10-11"},
        )
    ]
    assert not attendance_has_past_coverage(steps, "2026-09-29")
    miss = missing_helpers("whose attendance does not look right", steps, as_of="2026-09-29")
    assert "hr__scan_attendance_flags" in miss


def test_past_window_ok():
    steps = [
        Step(
            "tool",
            "hr__scan_attendance_flags",
            True,
            args={"from_date": "2026-09-15", "to_date": "2026-09-29"},
        ),
        Step("tool", "hr__scan_confirmation_due", True, args={"as_of": "2026-09-29"}),
    ]
    assert missing_helpers("attendance anomalies and confirmation due", steps, as_of="2026-09-29") == frozenset()


def test_as_of_only():
    steps = [Step("tool", "hr__scan_attendance_flags", True, args={"as_of": "2026-09-29"})]
    assert attendance_has_past_coverage(steps, "2026-09-29")


def test_nudge_text():
    text = nudge_for_missing(
        frozenset({"hr__scan_attendance_flags", "hr__scan_confirmation_due"}),
        as_of="2026-09-29",
    )
    assert "hr__scan_attendance_flags" in text
    assert "2026-09-15" in text
