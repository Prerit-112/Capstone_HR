"""Harness-only wrappers — never used in the production CLI agent."""
from __future__ import annotations

import time
from typing import Any

from agent.loop import HrAgent


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def attendance_update_payload(record: dict[str, Any], *, overtime_hours: float | None = None) -> dict[str, Any]:
    ot = _as_float(record.get("overtime_hours"), 0.0) if overtime_hours is None else float(overtime_hours)
    payload: dict[str, Any] = {
        "id": record["id"],
        "employee_id": record.get("employee_id"),
        "date": str(record.get("date") or "")[:10],
        "status": record.get("status"),
        "overtime_hours": ot,
    }
    # present rows reject an update that drops punches
    for k in ("check_in", "check_out", "shift"):
        if record.get(k) is not None:
            payload[k] = record.get(k)
    # Schema types: is_lop is boolean (live rows often store 0/1 ints).
    if record.get("is_lop") is not None:
        payload["is_lop"] = _as_bool(record.get("is_lop"))
    if record.get("lop_hours") is not None:
        payload["lop_hours"] = _as_float(record.get("lop_hours"), 0.0)

    status = str(payload.get("status") or "").strip().lower()
    if status == "present" and payload.get("check_in") is None and payload.get("check_out") is None:
        # Live book can hold present+null punches; API still rejects re-PUT without times.
        payload["check_in"] = "00:00"
        payload["check_out"] = "00:01"
    return payload


def attendance_conflict_payload(record: dict[str, Any]) -> dict[str, Any]:
    """Mutate a row enough to change the agent fingerprint without breaking API rules."""
    try:
        ot = float(record.get("overtime_hours") or 0)
    except (TypeError, ValueError):
        ot = 0.0
    # Flip overtime so fingerprint changes even when shift is already a team13 note.
    payload = attendance_update_payload(record, overtime_hours=0.0 if ot else 0.25)
    stamp = f"harness-conflict-{int(time.time())}"
    prior = (payload.get("shift") or "").strip()
    payload["shift"] = f"{prior} | {stamp}".strip(" |") if prior else stamp
    return payload


class ConflictHrAgent(HrAgent):
    """Mutate the live row after the agent has cached it, before its write.

    Proves the shared-book re-read abort. Restore `restore` after the run.
    """

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._poisoned = False
        self.restore: dict[str, Any] | None = None

    def _dispatch_tool(self, journal, name, args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "Attendance.update" and args.get("id") and not self._poisoned:
            rid = args["id"]
            try:
                current = self.mcp.tools_call("Attendance.get", {"id": rid})
            except Exception:
                current = None
            if isinstance(current, dict) and current.get("id"):
                self.restore = dict(current)
                self._seen[f"Attendance:{rid}"] = current
                payloads = [
                    attendance_conflict_payload(current),
                    # Minimal fallback if shift/extra fields are rejected.
                    {
                        "id": rid,
                        "employee_id": current.get("employee_id"),
                        "date": str(current.get("date") or "")[:10],
                        "status": current.get("status"),
                        "overtime_hours": 0.0
                        if _as_float(current.get("overtime_hours"), 0.0)
                        else 0.25,
                    },
                ]
                poisoned = False
                last_err: Exception | None = None
                for payload in payloads:
                    try:
                        self.mcp.tools_call("Attendance.update", payload)
                        self._poisoned = True
                        poisoned = True
                        break
                    except Exception as e:
                        last_err = e
                if not poisoned:
                    self.restore = None
                    from agent.journal import Step

                    journal.add(
                        Step(
                            "guard",
                            "adversary_poison",
                            False,
                            f"poison failed: {last_err}",
                            args={"id": rid},
                        )
                    )
        return super()._dispatch_tool(journal, name, args, **kwargs)


def restore_attendance(mcp, original: dict[str, Any] | None) -> None:
    if not original or not original.get("id"):
        return
    try:
        mcp.tools_call("Attendance.update", attendance_update_payload(original))
    except Exception:
        # Rows with invalid punches (check_out before check_in) reject a full re-PUT;
        # mirror the minimal poison payload so the overtime/shift change is undone.
        minimal: dict[str, Any] = {
            "id": original["id"],
            "employee_id": original.get("employee_id"),
            "date": str(original.get("date") or "")[:10],
            "status": original.get("status"),
            "overtime_hours": _as_float(original.get("overtime_hours"), 0.0),
        }
        if original.get("shift") is not None:
            minimal["shift"] = original.get("shift")
        mcp.tools_call("Attendance.update", minimal)
