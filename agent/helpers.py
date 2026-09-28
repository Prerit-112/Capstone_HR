"""Local scan helpers — correct pagination + hr_rules, exposed as LLM tools.

The raw Attendance.list date filter is equality on `date` (not check_in).
Leave list date filters are equality, not overlap. These helpers hide that.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from agent.hr_rules import (
    confirmation_due,
    flag_attendance,
    leaves_in_window,
    next_week_window,
    parse_date,
)
from agent.mcp_client import McpClient

DEFAULT_ATT_LOOKBACK = 14

HELPER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "hr__scan_attendance_flags",
            "description": (
                "Scan attendance for abnormalities on recorded days. "
                "Default window: as_of-lookback_days .. as_of (lookback_days default 14). "
                "Attendance quality checks use PAST days ending at as_of — do NOT pass a future "
                "'next week' leave window here (that is for hr__scan_leave_window). "
                "Fetches Attendance.list per day (date filter is equality) and flags "
                "present_with_null_punches, check_out_before_check_in, "
                "absent_without_overlapping_leave, is_lop, is_lop_with_zero_hours, present_on_holiday."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "as_of": {
                        "type": "string",
                        "description": "YYYY-MM-DD. If from/to omitted, scans as_of-lookback .. as_of",
                    },
                    "lookback_days": {
                        "type": "integer",
                        "description": "Days before as_of when using default window",
                        "default": 14,
                    },
                    "from_date": {"type": "string", "description": "YYYY-MM-DD start (optional)"},
                    "to_date": {"type": "string", "description": "YYYY-MM-DD end (optional)"},
                },
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "hr__scan_confirmation_due",
            "description": (
                "List active employees due or overdue for confirmation: "
                "probation_end_date on or before as_of+lookahead_days (default 30). "
                "Excludes left/suspended. Prefer this over manually scanning Employee.list."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "as_of": {"type": "string", "description": "YYYY-MM-DD"},
                    "lookahead_days": {"type": "integer", "default": 30},
                },
                "required": ["as_of"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "hr__scan_leave_window",
            "description": (
                "List approved/pending_approval leave overlapping [from_date, to_date]. "
                "Paginates LeaveApplication.list and applies overlap client-side "
                "(server date filters are equality, not range). "
                "If from_date/to_date omitted, uses next calendar week after as_of. "
                "This is the tool for future leave windows — not for attendance quality."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "as_of": {"type": "string", "description": "YYYY-MM-DD; used if window omitted"},
                    "from_date": {"type": "string"},
                    "to_date": {"type": "string"},
                },
                "required": [],
                "additionalProperties": False,
            },
        },
    },
]

HELPER_NAMES = frozenset(t["function"]["name"] for t in HELPER_TOOLS)


def _daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def resolve_attendance_window(args: dict[str, Any]) -> tuple[date, date] | str:
    start = parse_date(args.get("from_date"))
    end = parse_date(args.get("to_date"))
    as_of = parse_date(args.get("as_of"))
    lookback = int(args.get("lookback_days") or DEFAULT_ATT_LOOKBACK)
    if start is not None and end is not None:
        if end < start:
            return "to_date before from_date"
        return start, end
    if as_of is not None:
        return as_of - timedelta(days=lookback), as_of
    return "provide as_of, or both from_date and to_date"


def run_helper(mcp: McpClient, name: str, args: dict[str, Any]) -> Any:
    if name == "hr__scan_attendance_flags":
        return _scan_attendance(mcp, args)
    if name == "hr__scan_confirmation_due":
        return _scan_confirmation(mcp, args)
    if name == "hr__scan_leave_window":
        return _scan_leave(mcp, args)
    return {"error": f"unknown helper {name}"}


def _scan_attendance(mcp: McpClient, args: dict[str, Any]) -> dict[str, Any]:
    resolved = resolve_attendance_window(args)
    if isinstance(resolved, str):
        return {"error": resolved}
    start, end = resolved
    as_of = parse_date(args.get("as_of")) or end

    leave_page = mcp.list_all("LeaveApplication.list", {"limit": 100}, max_pages=30)
    leaves = leave_page["items"]

    records: list[dict] = []
    days_with_data = []
    for day in _daterange(start, end):
        page = mcp.list_all(
            "Attendance.list",
            {"limit": 100, "date": day.isoformat()},
            max_pages=10,
        )
        if page["items"]:
            days_with_data.append({"date": day.isoformat(), "count": len(page["items"])})
        records.extend(page["items"])

    flags = flag_attendance(records, leaves=leaves)
    future_only = start > as_of
    out: dict[str, Any] = {
        "from_date": start.isoformat(),
        "to_date": end.isoformat(),
        "as_of": as_of.isoformat(),
        "future_only": future_only,
        "attendance_rows_scanned": len(records),
        "days_with_data": days_with_data,
        "flags": [
            {
                "employee_id": f.employee_id,
                "date": f.date,
                "reason": f.reason,
                "attendance_id": f.attendance_id,
            }
            for f in flags
        ],
        "partial_error": leave_page.get("partial_error"),
    }
    if future_only:
        out["warning"] = (
            "Window is entirely after as_of; attendance usually has no rows yet. "
            f'Retry with as_of="{as_of.isoformat()}" (defaults to last {DEFAULT_ATT_LOOKBACK} days) '
            "or an explicit past from_date/to_date. Leave next-week windows belong on hr__scan_leave_window."
        )
    return out


def _scan_confirmation(mcp: McpClient, args: dict[str, Any]) -> dict[str, Any]:
    as_of = parse_date(args.get("as_of"))
    if as_of is None:
        return {"error": "as_of required as YYYY-MM-DD"}
    lookahead = int(args.get("lookahead_days") or 30)
    employees: list[dict] = []
    for status in ("active", "on_leave"):
        page = mcp.list_all("Employee.list", {"limit": 100, "status": status}, max_pages=20)
        employees.extend(page["items"])
    due = confirmation_due(employees, as_of, lookahead_days=lookahead)
    with_ped = sum(1 for e in employees if e.get("probation_end_date"))
    return {
        "as_of": as_of.isoformat(),
        "lookahead_days": lookahead,
        "employees_scanned": len(employees),
        "with_probation_end_date": with_ped,
        "confirmation_due": [
            {
                "employee_id": d.employee_id,
                "name": d.name,
                "probation_end_date": d.probation_end_date,
            }
            for d in due
        ],
    }


def _scan_leave(mcp: McpClient, args: dict[str, Any]) -> dict[str, Any]:
    as_of = parse_date(args.get("as_of")) or date.today()
    start = parse_date(args.get("from_date"))
    end = parse_date(args.get("to_date"))
    if start is None or end is None:
        start, end = next_week_window(as_of)

    leave_page = mcp.list_all("LeaveApplication.list", {"limit": 100}, max_pages=30)
    leaves = leave_page["items"]
    emp_page = mcp.list_all("Employee.list", {"limit": 100, "status": "active"}, max_pages=20)
    emp_map = {e["id"]: e for e in emp_page["items"] if e.get("id")}

    found = leaves_in_window(leaves, start, end, employees_by_id=emp_map)
    return {
        "window": {"from_date": start.isoformat(), "to_date": end.isoformat()},
        "leaves_scanned": len(leaves),
        "on_leave": [
            {
                "employee_id": x.employee_id,
                "name": x.name,
                "from_date": x.from_date,
                "to_date": x.to_date,
                "status": x.status,
                "leave_id": x.leave_id,
            }
            for x in found
        ],
        "partial_error": leave_page.get("partial_error"),
    }
