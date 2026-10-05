"""Harness-only wrappers — never used in the production CLI agent."""
from __future__ import annotations

from typing import Any

from agent.loop import HrAgent


def attendance_update_payload(record: dict[str, Any], *, overtime_hours: float | None = None) -> dict[str, Any]:
    ot = overtime_hours
    if ot is None:
        try:
            ot = float(record.get("overtime_hours") or 0)
        except (TypeError, ValueError):
            ot = 0.0
    payload = {
        "id": record["id"],
        "employee_id": record.get("employee_id"),
        "date": str(record.get("date") or "")[:10],
        "status": record.get("status"),
        "overtime_hours": ot,
    }
    # present rows reject an update that drops punches
    for k in ("check_in", "check_out", "shift", "is_lop", "lop_hours"):
        if record.get(k) is not None:
            payload[k] = record.get(k)
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
                self.restore = current
                self._seen[f"Attendance:{rid}"] = current
                try:
                    ot = float(current.get("overtime_hours") or 0)
                except (TypeError, ValueError):
                    ot = 0.0
                payload = attendance_update_payload(current, overtime_hours=0.0 if ot else 0.25)
                try:
                    self.mcp.tools_call("Attendance.update", payload)
                    self._poisoned = True
                except Exception:
                    self.restore = None
        return super()._dispatch_tool(journal, name, args, **kwargs)


def restore_attendance(mcp, original: dict[str, Any] | None) -> None:
    if not original or not original.get("id"):
        return
    payload = attendance_update_payload(original)
    mcp.tools_call("Attendance.update", payload)
