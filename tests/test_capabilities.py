from agent.capabilities import (
    attendance_has_past_coverage,
    missing_helpers,
    needed_helpers,
    nudge_for_missing,
    tools_for_task,
)
from agent.catalogue import Catalogue, ToolSpec
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


def test_tools_for_refusal_empty():
    cat = Catalogue(tools={})
    assert tools_for_task(cat, "Work order WO-441 is late. Reschedule.") == []


def test_tools_for_bar_helpers_only():
    cat = Catalogue(
        tools={
            "Employee.list": ToolSpec(
                name="Employee.list",
                description="list",
                input_schema={"type": "object", "properties": {}},
            ),
            "Attendance.list": ToolSpec(
                name="Attendance.list",
                description="list",
                input_schema={"type": "object", "properties": {}},
            ),
        }
    )
    tools = tools_for_task(
        cat,
        "Who is on leave next week, whose attendance does not look right, and who is due for confirmation?",
    )
    names = {t["function"]["name"] for t in tools}
    assert names == {
        "hr__scan_leave_window",
        "hr__scan_attendance_flags",
        "hr__scan_confirmation_due",
    }
    assert "Employee__list" not in names


def test_tools_for_write_includes_attendance():
    cat = Catalogue(
        tools={
            "Attendance.get": ToolSpec(
                name="Attendance.get",
                description="get",
                input_schema={"type": "object", "properties": {"id": {}}},
            ),
            "Attendance.list": ToolSpec(
                name="Attendance.list",
                description="list",
                input_schema={"type": "object", "properties": {"date": {}}},
            ),
            "Attendance.update": ToolSpec(
                name="Attendance.update",
                description="update",
                input_schema={"type": "object", "properties": {"id": {}, "status": {}}},
            ),
            "Employee.list": ToolSpec(
                name="Employee.list",
                description="list",
                input_schema={"type": "object", "properties": {}},
            ),
        }
    )
    tools = tools_for_task(
        cat,
        "Find one Attendance row that looks wrong and Attendance.update it to absent.",
        allow_writes=True,
        write_allowlist={"Attendance.update"},
    )
    names = {t["function"]["name"] for t in tools}
    assert names == {"hr__find_attendance_to_fix", "Attendance__get", "Attendance__update"}


def test_find_attendance_to_fix_prefers_null_punches():
    from agent.helpers import run_helper

    rows = [
        {"id": "a1", "employee_id": "e1", "date": "2026-09-01", "status": "present",
         "check_in": "18:00", "check_out": "09:00"},
        {"id": "a2", "employee_id": "e2", "date": "2026-09-02", "status": "absent"},
        {"id": "a3", "employee_id": "e3", "date": "2026-09-03", "status": "present",
         "check_in": None, "check_out": None},
    ]

    class Mcp:
        def list_all(self, tool, args, **_kw):
            assert tool == "Attendance.list"
            assert "date" not in args
            return {"items": rows, "partial_error": None}

    out = run_helper(Mcp(), "hr__find_attendance_to_fix", {})
    ids = [c["attendance_id"] for c in out["candidates"]]
    assert ids == ["a3", "a1"]
    assert out["candidates"][0]["reason"] == "present_with_null_punches"


def test_find_attendance_to_fix_empty_warns():
    from agent.helpers import run_helper

    class Mcp:
        def list_all(self, *_a, **_kw):
            return {"items": [{"id": "a1", "status": "present", "check_in": "09:00", "check_out": "18:00"}]}

    out = run_helper(Mcp(), "hr__find_attendance_to_fix", {})
    assert out["candidates"] == []
    assert "do not invent" in out["warning"]
