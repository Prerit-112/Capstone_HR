"""Documented HR judgment rules.

These thresholds are the agent's policy. The harness verifiers reimplement
the same semantics independently (they must NOT import this module).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Iterable


# --- configurable windows ---

# Confirmation: anyone with probation_end_date on or before as_of+lookahead,
# and not left/suspended. Overdue counts as due (no short lookback floor).
CONFIRMATION_LOOKAHEAD_DAYS = 30
CONFIRMATION_LOOKBACK_DAYS: int | None = None

# Statuses that count as "on leave" for planning questions.
# Confirmed against live book during Day-1; adjust if AgentSwitch adds/renames.
COUNTS_AS_OUT: frozenset[str] = frozenset({"approved", "pending_approval"})

# Statuses that are leave applications but do NOT mean the person is out.
NOT_CONFIRMED_OUT: frozenset[str] = frozenset({"draft", "cancelled", "rejected", "canceled"})


def parse_date(value: str | date | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    s = str(value).strip()[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def next_week_window(as_of: date) -> tuple[date, date]:
    """Monday–Sunday of the calendar week after the week containing as_of."""
    # weekday: Mon=0 … Sun=6
    days_until_next_monday = (7 - as_of.weekday()) % 7
    if days_until_next_monday == 0:
        days_until_next_monday = 7
    start = as_of + timedelta(days=days_until_next_monday)
    end = start + timedelta(days=6)
    return start, end


def overlaps(from_date: date | str | None, to_date: date | str | None, window_start: date, window_end: date) -> bool:
    """Leave overlaps window iff from_date <= window_end and to_date >= window_start.

    Required because AgentSwitch LeaveApplication.list date filters are equality,
    not range overlap (Bug 2). List wide, filter here.
    """
    fd = parse_date(from_date)
    td = parse_date(to_date)
    if fd is None or td is None:
        return False
    return fd <= window_end and td >= window_start


def employee_display_name(emp: dict[str, Any] | None) -> str:
    if not emp:
        return ""
    first = (emp.get("first_name") or "").strip()
    last = (emp.get("last_name") or "").strip()
    return f"{first} {last}".strip() or emp.get("email") or emp.get("id") or ""


@dataclass
class LeaveFinding:
    employee_id: str
    name: str
    from_date: str
    to_date: str
    status: str
    leave_id: str


def leaves_in_window(
    leaves: Iterable[dict[str, Any]],
    window_start: date,
    window_end: date,
    *,
    employees_by_id: dict[str, dict[str, Any]] | None = None,
    counts_as_out: frozenset[str] = COUNTS_AS_OUT,
) -> list[LeaveFinding]:
    employees_by_id = employees_by_id or {}
    out: list[LeaveFinding] = []
    for row in leaves:
        status = (row.get("status") or "").strip().lower()
        if status not in counts_as_out:
            continue
        if not overlaps(row.get("from_date"), row.get("to_date"), window_start, window_end):
            continue
        eid = str(row.get("employee_id") or "")
        emp = employees_by_id.get(eid)
        out.append(
            LeaveFinding(
                employee_id=eid,
                name=employee_display_name(emp),
                from_date=str(row.get("from_date") or "")[:10],
                to_date=str(row.get("to_date") or "")[:10],
                status=status,
                leave_id=str(row.get("id") or row.get("name") or ""),
            )
        )
    return out


@dataclass
class AttendanceFlag:
    employee_id: str
    date: str
    reason: str
    attendance_id: str


def _punch_order_bad(check_in: str | None, check_out: str | None) -> bool:
    if not check_in or not check_out:
        return False
    # Times are free text (HH:MM or HH:MM:SS). Compare lexicographically when both look like times.
    ci = str(check_in).strip()
    co = str(check_out).strip()
    if len(ci) >= 4 and len(co) >= 4 and ci[:2].isdigit() and co[:2].isdigit():
        return co < ci
    return False


def leave_covers_day(
    leaves: Iterable[dict[str, Any]],
    employee_id: str,
    day: date,
    *,
    counts_as_out: frozenset[str] = COUNTS_AS_OUT,
) -> bool:
    for row in leaves:
        if str(row.get("employee_id") or "") != employee_id:
            continue
        status = (row.get("status") or "").strip().lower()
        if status not in counts_as_out:
            continue
        if overlaps(row.get("from_date"), row.get("to_date"), day, day):
            return True
    return False


def flag_attendance(
    records: Iterable[dict[str, Any]],
    *,
    leaves: Iterable[dict[str, Any]] | None = None,
    holiday_dates: set[date] | None = None,
) -> list[AttendanceFlag]:
    """First-cut abnormality signals (gap report §2). Each flag cites a reason + id."""
    leaves = list(leaves or [])
    holiday_dates = holiday_dates or set()
    flags: list[AttendanceFlag] = []

    for row in records:
        eid = str(row.get("employee_id") or "")
        day = parse_date(row.get("date"))
        day_s = str(row.get("date") or "")[:10]
        aid = str(row.get("id") or "")
        status = (row.get("status") or "").strip().lower()
        check_in = row.get("check_in")
        check_out = row.get("check_out")
        is_lop = bool(row.get("is_lop"))
        lop_hours = row.get("lop_hours")

        if status == "present" and not check_in and not check_out:
            flags.append(AttendanceFlag(eid, day_s, "present_with_null_punches", aid))

        if _punch_order_bad(check_in, check_out):
            flags.append(AttendanceFlag(eid, day_s, "check_out_before_check_in", aid))

        if status == "absent" and day is not None and not leave_covers_day(leaves, eid, day):
            flags.append(AttendanceFlag(eid, day_s, "absent_without_overlapping_leave", aid))

        if is_lop:
            flags.append(AttendanceFlag(eid, day_s, "is_lop", aid))
            try:
                if lop_hours is not None and float(lop_hours) == 0.0:
                    flags.append(AttendanceFlag(eid, day_s, "is_lop_with_zero_hours", aid))
            except (TypeError, ValueError):
                pass

        if day is not None and day in holiday_dates and status == "present":
            flags.append(AttendanceFlag(eid, day_s, "present_on_holiday", aid))

    return flags


@dataclass
class ConfirmationFinding:
    employee_id: str
    name: str
    probation_end_date: str


def confirmation_due(
    employees: Iterable[dict[str, Any]],
    as_of: date,
    *,
    lookback_days: int | None = CONFIRMATION_LOOKBACK_DAYS,
    lookahead_days: int = CONFIRMATION_LOOKAHEAD_DAYS,
) -> list[ConfirmationFinding]:
    """Employees whose probation_end_date is due or overdue.

    Default: any probation_end_date <= as_of + lookahead_days (includes all
    overdue). Pass lookback_days to also require ped >= as_of - lookback.
    """
    end = as_of + timedelta(days=lookahead_days)
    start = (as_of - timedelta(days=lookback_days)) if lookback_days is not None else None
    out: list[ConfirmationFinding] = []
    for emp in employees:
        status = (emp.get("status") or "").strip().lower()
        if status in {"left", "suspended"}:
            continue
        ped = parse_date(emp.get("probation_end_date"))
        if ped is None:
            continue
        if ped > end:
            continue
        if start is not None and ped < start:
            continue
        out.append(
            ConfirmationFinding(
                employee_id=str(emp.get("id") or ""),
                name=employee_display_name(emp),
                probation_end_date=ped.isoformat(),
            )
        )
    return out


def holiday_dates(rows: Iterable[dict[str, Any]]) -> set[date]:
    """Child holiday days only — parent from/to is the list span, not every day off."""
    out: set[date] = set()
    for row in rows:
        kids = row.get("holidays") or []
        if isinstance(kids, list):
            for h in kids:
                if not isinstance(h, dict):
                    continue
                d = parse_date(h.get("date"))
                if d is not None:
                    out.add(d)
        d = parse_date(row.get("holiday_date"))
        if d is not None:
            out.add(d)
    return out


def week_containing(day: date) -> tuple[date, date]:
    start = day - timedelta(days=day.weekday())
    return start, start + timedelta(days=6)


def empty_answer(*, as_of: str, refused: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "findings": {
            "on_leave": [],
            "attendance_flags": [],
            "confirmation_due": [],
            "leave_balances": [],
            "holidays": [],
            "holiday_week": None,
        },
        "actions_taken": [],
        "uncertain": [],
        "refused": refused
        or {"is_refusal": False, "why": "", "escalate_to": ""},
        "claimed_success": False,
        "as_of": as_of,
    }
