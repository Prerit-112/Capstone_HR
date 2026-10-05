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
    holiday_dates,
    leaves_in_window,
    next_week_window,
    parse_date,
    week_containing,
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
    {
        "type": "function",
        "function": {
            "name": "hr__scan_leave_balances",
            "description": (
                "LeaveBalance rows for one employee (or a sample employee if employee_id omitted), "
                "joined to LeaveType when the catalogue has rows. "
                "If LeaveType.list is empty, entitlements are unknown — do not invent numbers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "employee_id": {
                        "type": "string",
                        "description": "Employee id; if omitted, pick one active employee who has balances",
                    }
                },
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "hr__scan_holidays",
            "description": (
                "List HolidayList records and expand child holiday dates. "
                "If the catalogue is empty, say so — do not invent public holidays. "
                "Optionally pass as_of to suggest a Mon–Sun week that contains a holiday on or after as_of."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "as_of": {"type": "string", "description": "YYYY-MM-DD"},
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
    if name == "hr__scan_leave_balances":
        return _scan_balances(mcp, args)
    if name == "hr__scan_holidays":
        return _scan_holidays(mcp, args)
    return {"error": f"unknown helper {name}"}


def _scan_attendance(mcp: McpClient, args: dict[str, Any]) -> dict[str, Any]:
    resolved = resolve_attendance_window(args)
    if isinstance(resolved, str):
        return {"error": resolved}
    start, end = resolved
    as_of = parse_date(args.get("as_of")) or end

    leave_page = mcp.list_all("LeaveApplication.list", {"limit": 100}, max_pages=30)
    leaves = leave_page["items"]
    hol_page = mcp.list_all("HolidayList.list", {"limit": 100}, max_pages=10)
    hol_dates = holiday_dates(hol_page["items"])

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

    flags = flag_attendance(records, leaves=leaves, holiday_dates=hol_dates)
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
        "holiday_dates_loaded": sorted(d.isoformat() for d in hol_dates),
        "partial_error": leave_page.get("partial_error") or hol_page.get("partial_error"),
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


def _scan_balances(mcp: McpClient, args: dict[str, Any]) -> dict[str, Any]:
    emp_id = (args.get("employee_id") or "").strip() or None
    bal_page = mcp.list_all("LeaveBalance.list", {"limit": 100}, max_pages=20)
    type_page = mcp.list_all("LeaveType.list", {"limit": 100}, max_pages=5)
    types = type_page["items"]
    by_code = {(t.get("code") or "").strip(): t for t in types if t.get("code")}
    by_id = {str(t.get("id")): t for t in types if t.get("id")}

    rows = bal_page["items"]
    if emp_id:
        rows = [r for r in rows if str(r.get("employee_id") or "") == emp_id]
    else:
        counts: dict[str, int] = {}
        for r in rows:
            eid = str(r.get("employee_id") or "")
            if eid:
                counts[eid] = counts.get(eid, 0) + 1
        if counts:
            emp_id = max(counts, key=counts.get)
            rows = [r for r in rows if str(r.get("employee_id") or "") == emp_id]

    empty_types = len(types) == 0
    balances = []
    for r in rows:
        code = (r.get("leave_type") or "").strip()
        lt = by_id.get(str(r.get("leave_type_id") or "")) or by_code.get(code)
        balances.append(
            {
                "employee_id": str(r.get("employee_id") or ""),
                "leave_balance_id": str(r.get("id") or ""),
                "leave_type": code,
                "balance_days": r.get("balance_days"),
                "used_days": r.get("used_days"),
                "opening_balance": r.get("opening_balance"),
                "annual_entitlement": None if empty_types else (lt or {}).get("annual_entitlement"),
                "leave_type_matched": bool(lt),
            }
        )
    out: dict[str, Any] = {
        "employee_id": emp_id,
        "leave_type_catalogue_empty": empty_types,
        "leave_type_rows": len(types),
        "balances": balances,
        "partial_error": bal_page.get("partial_error") or type_page.get("partial_error"),
    }
    if empty_types:
        out["warning"] = (
            "LeaveType.list returned 0 rows. Report live LeaveBalance figures only; "
            "put entitlement gaps in uncertain — do not invent annual_entitlement."
        )
    if not balances:
        out["warning"] = (out.get("warning") or "") + " No LeaveBalance rows for the chosen employee."
    return out


def _scan_holidays(mcp: McpClient, args: dict[str, Any]) -> dict[str, Any]:
    as_of = parse_date(args.get("as_of")) or date.today()
    page = mcp.list_all("HolidayList.list", {"limit": 100}, max_pages=10)
    rows = page["items"]
    dates = holiday_dates(rows)
    holidays = []
    for row in rows:
        kids = row.get("holidays") or []
        if isinstance(kids, list):
            for h in kids:
                if not isinstance(h, dict):
                    continue
                d = parse_date(h.get("date"))
                if d is None:
                    continue
                holidays.append(
                    {
                        "date": d.isoformat(),
                        "description": h.get("description") or row.get("name"),
                        "list_id": str(row.get("id") or ""),
                    }
                )
    suggested = None
    future = sorted(d for d in dates if d >= as_of)
    pick = future[0] if future else (sorted(dates)[0] if dates else None)
    if pick is not None:
        w0, w1 = week_containing(pick)
        suggested = {
            "holiday_date": pick.isoformat(),
            "from_date": w0.isoformat(),
            "to_date": w1.isoformat(),
        }
    empty = len(dates) == 0
    out: dict[str, Any] = {
        "as_of": as_of.isoformat(),
        "catalogue_empty": empty,
        "holiday_list_rows": len(rows),
        "holidays": holidays,
        "suggested_week": suggested,
        "partial_error": page.get("partial_error"),
    }
    if empty:
        out["warning"] = (
            "HolidayList has no child holiday dates. Do not invent public holidays. "
            "Set claimed_success false and explain the empty catalogue in uncertain or refused."
        )
    return out
