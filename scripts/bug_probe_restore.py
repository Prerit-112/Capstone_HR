"""Restore probe side-effects and keep one UI artefact for strongest new bugs."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from agent.mcp_client import McpClient, McpError  # noqa: E402

PROBE_EMP = "baf152b3-e8ee-4da2-bee4-592637b9f94c"
BALANCE_ABSURD = "59443ce6-06ac-4796-8944-8c93c19058fe"
BEFORE_JOIN_PENDING = "ab1652b4-990e-4d6b-a1d3-56093ba8f6b6"


def call(client, tool, args):
    try:
        return True, client.tools_call(tool, args)
    except Exception as e:
        data = getattr(e, "data", None)
        return False, {"error": str(e)[:400], "data": data}


def main() -> int:
    with McpClient(
        base_url=os.getenv("AS_BASE_URL", "https://agentswitch.theschoolofai.in"),
        email=os.getenv("AS_EMAIL", "team13@theschoolofai.in"),
        password=os.getenv("AS_PASSWORD", ""),
    ) as client:
        client.login()
        client.initialize()

        # Try clear exit_date variants
        for label, val in [
            ("empty", ""),
            ("omit_via_space", " "),
        ]:
            ok, r = call(client, "Employee.update", {"id": PROBE_EMP, "exit_date": val})
            print(label, ok, json.dumps(r if not ok else {k: r.get(k) for k in ["id", "status", "exit_date"]}, default=str)[:300])

        emp = client.tools_call("Employee.get", {"id": PROBE_EMP})
        print("EMP NOW", {k: emp.get(k) for k in ["email", "status", "exit_date", "date_of_joining"]})

        # Schema may not allow delete on LeaveBalance — try update used to neutralize? or leave artefact
        tools = [t["name"] for t in client.tools_list() if t["name"].startswith("LeaveBalance")]
        print("balance tools", tools)

        # Withdraw before-join pending if still open (keep one artefact intentionally)
        ok, leave = call(client, "LeaveApplication.get", {"id": BEFORE_JOIN_PENDING})
        print("before_join leave", ok, {k: leave.get(k) for k in ["number", "status", "from_date"]} if ok else leave)
        if ok and leave.get("status") == "pending_approval":
            # keep for UI check — do not withdraw
            print("KEEPING artefact", leave.get("number"))

        # Neutralize absurd balance if update allows huge used_days to zero net? better leave for UI
        ok, bal = call(client, "LeaveBalance.get", {"id": BALANCE_ABSURD})
        print("absurd bal", ok, {k: bal.get(k) for k in ["fiscal_year", "opening_balance", "balance_days", "leave_type", "employee_id"]} if ok else bal)

        # Recreate keep artefacts that were cancelled: leave before join + paternity female as drafts for UI
        # Also leave attendance bad punches / neg OT / left emp attendance

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
