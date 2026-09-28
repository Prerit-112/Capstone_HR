"""Capability detection — which scan helpers a prompt needs.

Keyword domains, not a single canned query. Refusal / out-of-seat prompts
need no helpers.
"""
from __future__ import annotations

from datetime import date, timedelta

from agent.helpers import DEFAULT_ATT_LOOKBACK, HELPER_NAMES, resolve_attendance_window
from agent.hr_rules import next_week_window, parse_date

_DOMAIN_HELPERS: list[tuple[tuple[str, ...], str]] = [
    (
        (
            "attendance",
            "punch",
            "check_in",
            "check_out",
            "check-in",
            "check-out",
            "is_lop",
            "lop",
            "does not look right",
            "doesn't look right",
            "abnormal",
            "exception",
        ),
        "hr__scan_attendance_flags",
    ),
    (
        (
            "confirmation",
            "probation",
            "probation_end",
            "due for confirmation",
        ),
        "hr__scan_confirmation_due",
    ),
    (
        (
            "on leave",
            "time off",
            "pending_approval",
            "next week",
            "who is out",
            "leave application",
            "overlapping leave",
            "approved or pending",
        ),
        "hr__scan_leave_window",
    ),
]

_REFUSAL_HINTS = (
    "work order",
    "bom",
    "manufacturing",
    "general ledger",
    "gl entry",
    "invoice",
    "approve every",
    "approve all",
    "geofence",
    "why was",
    "root cause",
)


def needed_helpers(prompt: str) -> frozenset[str]:
    p = (prompt or "").lower()
    if any(h in p for h in _REFUSAL_HINTS) and not any(
        k in p for k in ("attendance", "leave", "confirmation", "probation")
    ):
        return frozenset()
    need: set[str] = set()
    for keywords, helper in _DOMAIN_HELPERS:
        if any(k in p for k in keywords):
            need.add(helper)
    if (
        "leave" in p
        and "hr__scan_leave_window" not in need
        and "balance" not in p
        and "entitlement" not in p
        and "accrual" not in p
    ):
        need.add("hr__scan_leave_window")
    return frozenset(need)


def helpers_called(steps: list) -> frozenset[str]:
    names: set[str] = set()
    for s in steps:
        target = getattr(s, "target", None) or (s.get("target") if isinstance(s, dict) else None)
        if target in HELPER_NAMES:
            names.add(target)
    return frozenset(names)


def attendance_has_past_coverage(steps: list, as_of: str | None) -> bool:
    """True if a successful attendance scan covers days on/before as_of."""
    as_of_d = parse_date(as_of) or date.today()
    for s in steps:
        target = getattr(s, "target", None) or (s.get("target") if isinstance(s, dict) else None)
        ok = getattr(s, "ok", None) if not isinstance(s, dict) else s.get("ok")
        if target != "hr__scan_attendance_flags" or not ok:
            continue
        args = getattr(s, "args", None) if not isinstance(s, dict) else s.get("args")
        args = dict(args or {})
        if "as_of" not in args and as_of:
            args = {**args, "as_of": as_of}
        resolved = resolve_attendance_window(args)
        if isinstance(resolved, str):
            # as_of-only with no from/to counts as lookback once helper runs that way
            if args.get("as_of") or as_of:
                return True
            continue
        start, end = resolved
        if start <= as_of_d:
            return True
    return False


def missing_helpers(prompt: str, steps: list, *, as_of: str | None = None) -> frozenset[str]:
    need = needed_helpers(prompt)
    called = helpers_called(steps)
    missing = set(need - called)
    if "hr__scan_attendance_flags" in need and not attendance_has_past_coverage(steps, as_of):
        missing.add("hr__scan_attendance_flags")
    return frozenset(missing)


def nudge_for_missing(missing: frozenset[str], *, as_of: str) -> str:
    as_of_d = parse_date(as_of) or date.today()
    att_from = (as_of_d - timedelta(days=DEFAULT_ATT_LOOKBACK)).isoformat()
    att_to = as_of_d.isoformat()
    w0, w1 = next_week_window(as_of_d)
    lines = [
        "Before final JSON: call the required scan helpers with the right windows. "
        "Attendance quality = past recorded days; leave 'next week' = future leave window. Call:"
    ]
    if "hr__scan_attendance_flags" in missing:
        lines.append(
            f'- hr__scan_attendance_flags with as_of="{as_of_d.isoformat()}" '
            f"(or from_date=\"{att_from}\", to_date=\"{att_to}\"). "
            f"Do not use {w0.isoformat()}..{w1.isoformat()} for attendance."
        )
    if "hr__scan_confirmation_due" in missing:
        lines.append(f'- hr__scan_confirmation_due with as_of="{as_of_d.isoformat()}"')
    if "hr__scan_leave_window" in missing:
        lines.append(
            f'- hr__scan_leave_window with as_of="{as_of_d.isoformat()}" '
            f"(next week {w0.isoformat()} .. {w1.isoformat()})"
        )
    lines.append("Then reply with ONLY the final JSON object.")
    return "\n".join(lines)
