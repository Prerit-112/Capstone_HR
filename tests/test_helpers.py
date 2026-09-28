from agent.helpers import resolve_attendance_window, run_helper


class FakeMcp:
    def __init__(self, att=None, leave=None, emps=None):
        self.att = att or {}
        self.leave = leave or []
        self.emps = emps or []

    def list_all(self, tool, arguments=None, **kw):
        arguments = arguments or {}
        if tool == "Attendance.list":
            items = list(self.att.get(arguments.get("date"), []))
            return {"items": items, "total": len(items), "pages": 1, "partial_error": None}
        if tool == "LeaveApplication.list":
            return {"items": list(self.leave), "total": len(self.leave), "pages": 1, "partial_error": None}
        if tool == "Employee.list":
            st = arguments.get("status")
            items = [e for e in self.emps if not st or e.get("status") == st]
            return {"items": items, "total": len(items), "pages": 1, "partial_error": None}
        return {"items": [], "total": 0, "pages": 0, "partial_error": None}


def test_att_by_date():
    mcp = FakeMcp(att={
        "2026-09-16": [{
            "id": "a1",
            "employee_id": "e1",
            "date": "2026-09-16",
            "status": "present",
            "check_in": "18:00",
            "check_out": "09:00",
            "is_lop": False,
        }]
    })
    out = run_helper(mcp, "hr__scan_attendance_flags", {"from_date": "2026-09-16", "to_date": "2026-09-16"})
    assert out["attendance_rows_scanned"] == 1
    assert any(f["reason"] == "check_out_before_check_in" for f in out["flags"])


def test_att_as_of_lookback():
    from datetime import date
    start, end = resolve_attendance_window({"as_of": "2026-09-29"})
    assert end == date(2026, 9, 29)
    assert start == date(2026, 9, 15)


def test_att_future_warns():
    out = run_helper(
        FakeMcp(),
        "hr__scan_attendance_flags",
        {"from_date": "2026-10-05", "to_date": "2026-10-11", "as_of": "2026-09-29"},
    )
    assert out["future_only"] is True
    assert "warning" in out


def test_att_empty():
    out = run_helper(FakeMcp(), "hr__scan_attendance_flags", {"from_date": "2026-09-15", "to_date": "2026-09-15"})
    assert out["attendance_rows_scanned"] == 0
    assert out["flags"] == []


def test_conf_overdue():
    mcp = FakeMcp(emps=[
        {"id": "e1", "first_name": "Girish", "last_name": "", "status": "active", "probation_end_date": "2025-05-26"},
        {"id": "e2", "first_name": "Far", "status": "active", "probation_end_date": "2027-01-01"},
    ])
    out = run_helper(mcp, "hr__scan_confirmation_due", {"as_of": "2026-09-29"})
    ids = {r["employee_id"] for r in out["confirmation_due"]}
    assert ids == {"e1"}


def test_leave_window():
    mcp = FakeMcp(
        leave=[
            {"id": "L1", "employee_id": "e1", "from_date": "2026-10-12", "to_date": "2026-10-12", "status": "pending_approval"},
            {"id": "L2", "employee_id": "e1", "from_date": "2026-08-01", "to_date": "2026-08-02", "status": "approved"},
        ],
        emps=[{"id": "e1", "first_name": "Girish", "status": "active"}],
    )
    out = run_helper(mcp, "hr__scan_leave_window", {"from_date": "2026-10-06", "to_date": "2026-10-12"})
    assert len(out["on_leave"]) == 1
    assert out["on_leave"][0]["leave_id"] == "L1"
