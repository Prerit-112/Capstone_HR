from agent.capabilities import (
    attendance_has_past_coverage,
    missing_helpers,
    needed_helpers,
    nudge_for_missing,
)
from agent.journal import Step


def test_bar_needs_three():
    p = "Who is on leave next week, whose attendance does not look right, and who is due for confirmation?"
    need = needed_helpers(p)
    assert need >= {
        "hr__scan_leave_window",
        "hr__scan_attendance_flags",
        "hr__scan_confirmation_due",
    }


def test_exceptions_brief():
    p = "HR exceptions brief: attendance last 14 days, confirmation overdue, pending leave"
    need = needed_helpers(p)
    assert "hr__scan_attendance_flags" in need
    assert "hr__scan_confirmation_due" in need
    assert "hr__scan_leave_window" in need


def test_balance_skip():
    assert needed_helpers("Show leave balance versus entitlement for one employee") == frozenset()


def test_mfg_skip():
    assert needed_helpers("Work order WO-441 is late. Find out why and reschedule.") == frozenset()


def test_missing():
    steps = [Step("tool", "Attendance.list", True)]
    assert "hr__scan_attendance_flags" in missing_helpers(
        "whose attendance does not look right", steps, as_of="2026-09-29"
    )


def test_future_att_scan_still_missing():
    p = "whose attendance does not look right"
    steps = [
        Step(
            "tool",
            "hr__scan_attendance_flags",
            True,
            args={"from_date": "2026-10-05", "to_date": "2026-10-11"},
        )
    ]
    assert "hr__scan_attendance_flags" in missing_helpers(p, steps, as_of="2026-09-29")
    assert attendance_has_past_coverage(steps, "2026-09-29") is False


def test_past_att_scan_clears():
    p = "attendance anomalies and confirmation due"
    steps = [
        Step(
            "tool",
            "hr__scan_attendance_flags",
            True,
            args={"from_date": "2026-09-15", "to_date": "2026-09-29"},
        ),
        Step("tool", "hr__scan_confirmation_due", True, args={"as_of": "2026-09-29"}),
    ]
    assert missing_helpers(p, steps, as_of="2026-09-29") == frozenset()


def test_as_of_only_att_counts():
    steps = [Step("tool", "hr__scan_attendance_flags", True, args={"as_of": "2026-09-29"})]
    assert attendance_has_past_coverage(steps, "2026-09-29") is True


def test_nudge():
    text = nudge_for_missing(
        frozenset({"hr__scan_attendance_flags", "hr__scan_confirmation_due"}),
        as_of="2026-09-29",
    )
    assert "hr__scan_attendance_flags" in text
    assert "2026-09-15" in text
    assert "2026-10-05" in text  # tells model not to use next week for att
