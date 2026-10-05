"""Independent verifiers — MUST NOT import agent.hr_rules."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any


def parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def next_week_window(as_of: date) -> tuple[date, date]:
    days_until_next_monday = (7 - as_of.weekday()) % 7
    if days_until_next_monday == 0:
        days_until_next_monday = 7
    start = as_of + timedelta(days=days_until_next_monday)
    end = start + timedelta(days=6)
    return start, end


def overlaps(from_date: Any, to_date: Any, window_start: date, window_end: date) -> bool:
    fd, td = parse_date(from_date), parse_date(to_date)
    if fd is None or td is None:
        return False
    return fd <= window_end and td >= window_start


COUNTS_AS_OUT = frozenset({"approved", "pending_approval"})


def expected_on_leave(leaves: list[dict], window_start: date, window_end: date) -> set[str]:
    """Return set of leave record ids expected in on_leave findings."""
    ids: set[str] = set()
    for row in leaves:
        status = (row.get("status") or "").strip().lower()
        if status not in COUNTS_AS_OUT:
            continue
        if overlaps(row.get("from_date"), row.get("to_date"), window_start, window_end):
            ids.add(str(row.get("id") or ""))
    return {i for i in ids if i}


def punch_order_bad(check_in: Any, check_out: Any) -> bool:
    if not check_in or not check_out:
        return False
    ci, co = str(check_in).strip(), str(check_out).strip()
    if len(ci) >= 4 and len(co) >= 4 and ci[:2].isdigit() and co[:2].isdigit():
        return co < ci
    return False


def leave_covers(leaves: list[dict], employee_id: str, day: date) -> bool:
    for row in leaves:
        if str(row.get("employee_id") or "") != employee_id:
            continue
        if (row.get("status") or "").strip().lower() not in COUNTS_AS_OUT:
            continue
        if overlaps(row.get("from_date"), row.get("to_date"), day, day):
            return True
    return False


def expected_attendance_flags(
    records: list[dict],
    leaves: list[dict],
    holiday_dates: set[date] | None = None,
) -> set[tuple[str, str]]:
    """Set of (attendance_id, reason)."""
    holiday_dates = holiday_dates or set()
    flags: set[tuple[str, str]] = set()
    for row in records:
        aid = str(row.get("id") or "")
        if not aid:
            continue
        eid = str(row.get("employee_id") or "")
        day = parse_date(row.get("date"))
        status = (row.get("status") or "").strip().lower()
        check_in, check_out = row.get("check_in"), row.get("check_out")
        is_lop = bool(row.get("is_lop"))
        lop_hours = row.get("lop_hours")

        if status == "present" and not check_in and not check_out:
            flags.add((aid, "present_with_null_punches"))
        if punch_order_bad(check_in, check_out):
            flags.add((aid, "check_out_before_check_in"))
        if status == "absent" and day is not None and not leave_covers(leaves, eid, day):
            flags.add((aid, "absent_without_overlapping_leave"))
        if is_lop:
            flags.add((aid, "is_lop"))
            try:
                if lop_hours is not None and float(lop_hours) == 0.0:
                    flags.add((aid, "is_lop_with_zero_hours"))
            except (TypeError, ValueError):
                pass
        if day is not None and day in holiday_dates and status == "present":
            flags.add((aid, "present_on_holiday"))
    return flags


def holiday_dates_from_lists(rows: list[dict]) -> set[date]:
    """Child holiday days only — parent from/to is the list validity span."""
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


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def expected_balance_ids(balances: list[dict], employee_id: str) -> set[str]:
    ids: set[str] = set()
    for row in balances:
        if str(row.get("employee_id") or "") != employee_id:
            continue
        bid = str(row.get("id") or "")
        if bid:
            ids.add(bid)
    return ids


def balance_days_by_id(balances: list[dict]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for row in balances:
        bid = str(row.get("id") or "")
        if bid:
            out[bid] = _num(row.get("balance_days"))
    return out


def expected_confirmation(
    employees: list[dict],
    as_of: date,
    *,
    lookback_days: int | None = None,
    lookahead_days: int = 30,
) -> set[str]:
    end = as_of + timedelta(days=lookahead_days)
    start = (as_of - timedelta(days=lookback_days)) if lookback_days is not None else None
    ids: set[str] = set()
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
        ids.add(str(emp.get("id") or ""))
    return {i for i in ids if i}


def compare_sets(expected: set, reported: set, *, label: str) -> dict:
    missing = expected - reported
    extra = reported - expected
    # Churn: if expected and reported differ, caller may mark indeterminate when
    # a second live re-fetch also differs. Here we report the diff.
    return {
        "label": label,
        "expected_count": len(expected),
        "reported_count": len(reported),
        "missing": sorted(missing, key=str)[:50],
        "extra": sorted(extra, key=str)[:50],
        "match": not missing,  # supersets OK for extras? Plan: penalty for misses. extras noted.
        "strict_match": not missing and not extra,
    }
