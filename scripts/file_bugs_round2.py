"""Recreate UI artefacts + file bug reports 1–3 (round 2)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from agent.mcp_client import McpClient  # noqa: E402

OUT = ROOT / "runs" / "filed_bugs_round2.json"


def main() -> int:
    password = os.getenv("AS_PASSWORD", "")
    if not password:
        print("Set AS_PASSWORD")
        return 2

    artefacts: dict = {}
    filed: list = []

    with McpClient(
        base_url=os.getenv("AS_BASE_URL", "https://agentswitch.theschoolofai.in"),
        email=os.getenv("AS_EMAIL", "team13@theschoolofai.in"),
        password=password,
    ) as client:
        client.login()
        client.initialize()
        token = client._token
        assert token

        # --- Artefact for Bug 1: leave for left employee ---
        lefts = client.list_all("Employee.list", {"limit": 5, "status": "left"}, max_pages=1)
        left = lefts["items"][0]
        leave1 = client.tools_call(
            "LeaveApplication.create",
            {
                "employee_id": left["id"],
                "from_date": "2027-06-15",
                "to_date": "2027-06-15",
                "leave_type": "casual",
                "reason": "team13-bugprobe: leave for left employee (keep for UI)",
            },
        )
        artefacts["bug1_left_employee"] = {
            "employee": {
                "id": left["id"],
                "email": left.get("email"),
                "status": left.get("status"),
                "exit_date": left.get("exit_date"),
                "name": f"{left.get('first_name','')} {left.get('last_name','')}".strip(),
            },
            "leave": {
                k: leave1.get(k)
                for k in ["id", "number", "status", "from_date", "to_date", "leave_type", "days"]
            },
        }
        print("artefact bug1", artefacts["bug1_left_employee"])

        # --- Artefact for Bug 2: submit with negative balance ---
        bals = client.list_all("LeaveBalance.list", {"limit": 50}, max_pages=2)
        neg = next(x for x in bals["items"] if (x.get("balance_days") or 0) < 0)
        leave2 = client.tools_call(
            "LeaveApplication.create",
            {
                "employee_id": neg["employee_id"],
                "from_date": "2027-08-20",
                "to_date": "2027-08-20",
                "leave_type": neg.get("leave_type") or "casual",
                "reason": "team13-bugprobe: submit with negative balance (keep for UI)",
            },
        )
        submitted = client.tools_call("LeaveApplication.submit", {"id": leave2["id"]})
        emp2 = client.tools_call("Employee.get", {"id": neg["employee_id"]})
        artefacts["bug2_neg_balance"] = {
            "balance": {
                k: neg.get(k)
                for k in [
                    "id",
                    "employee_id",
                    "leave_type",
                    "balance_days",
                    "used_days",
                    "opening_balance",
                    "accrued_days",
                    "fiscal_year",
                ]
            },
            "employee_email": emp2.get("email"),
            "leave": {
                k: submitted.get(k)
                for k in ["id", "number", "status", "from_date", "to_date", "leave_type", "days"]
            },
            "book_stats": {
                "balances_scanned": bals["total"],
                "note": "Prior probe: 294/294 LeaveBalance rows negative with opening=0 accrued=0",
            },
        }
        print("artefact bug2", artefacts["bug2_neg_balance"])

        # --- Artefact for Bug 3: weak leave validation (half_day multi-day) ---
        # Use a different active employee to avoid overlap with prakash drafts
        emps = client.list_all("Employee.list", {"limit": 30, "status": "active"}, max_pages=1)
        prakash_id = "baf152b3-e8ee-4da2-bee4-592637b9f94c"
        other = next(
            (e for e in emps["items"] if e["id"] != prakash_id and e["id"] != left["id"]),
            emps["items"][0],
        )
        leave3a = client.tools_call(
            "LeaveApplication.create",
            {
                "employee_id": other["id"],
                "from_date": "2027-03-01",
                "to_date": "2027-03-05",
                "leave_type": "sick",
                "half_day": True,
                "reason": "team13-bugprobe: half_day multi-day (keep for UI)",
            },
        )
        leave3b = client.tools_call(
            "LeaveApplication.create",
            {
                "employee_id": prakash_id,
                "from_date": "2027-09-01",
                "to_date": "2027-12-31",
                "leave_type": "maternity",
                "reason": "team13-bugprobe: maternity on male (keep for UI)",
            },
        )
        prakash = client.tools_call("Employee.get", {"id": prakash_id})
        extreme = client.tools_call(
            "LeaveApplication.get", {"id": "76bda086-6e9f-49c0-856a-f3d6fa131d6d"}
        )
        artefacts["bug3_weak_validation"] = {
            "half_day_multiday": {
                k: leave3a.get(k)
                for k in [
                    "id",
                    "number",
                    "status",
                    "from_date",
                    "to_date",
                    "days",
                    "half_day",
                    "leave_type",
                    "employee_id",
                ]
            },
            "half_day_employee_email": other.get("email"),
            "maternity_on_male": {
                k: leave3b.get(k)
                for k in [
                    "id",
                    "number",
                    "status",
                    "from_date",
                    "to_date",
                    "days",
                    "leave_type",
                    "employee_id",
                ]
            },
            "male_employee": {
                "id": prakash_id,
                "email": prakash.get("email"),
                "gender": prakash.get("gender"),
            },
            "existing_extreme": {
                k: extreme.get(k)
                for k in [
                    "id",
                    "number",
                    "days",
                    "half_day",
                    "from_date",
                    "to_date",
                    "leave_type",
                    "status",
                    "_employee_id_display",
                ]
            },
        }
        print("artefact bug3", artefacts["bug3_weak_validation"])

        reports = [
            {
                "page": "LeaveApplication",
                "agent_seat": "HR",
                "job_id": "",
                "description": (
                    "LeaveApplication.create accepts leave for employees with status=left.\n\n"
                    "What I did:\n"
                    f"1. Employee.list status=left → {left.get('email')} "
                    f"(id={left['id']}, status=left, exit_date={left.get('exit_date')}).\n"
                    f"2. MCP LeaveApplication.create for that employee on 2027-06-15 "
                    f"(casual) succeeded → {leave1.get('number')} "
                    f"(id={leave1.get('id')}, status=draft).\n"
                    "3. Earlier identical probe produced LA-2026-00575 (later cancelled).\n\n"
                    "Expected: create/submit should reject when employee status is left "
                    "(or exit_date is set), same as other HR systems that block leave for exited staff.\n\n"
                    "Actual: draft leave is created and remains writable. Agents can book future leave "
                    "for people who have already left the company.\n\n"
                    f"UI check: open Leave {leave1.get('number')} and Employee {left.get('email')} "
                    "(status left)."
                ),
            },
            {
                "page": "LeaveApplication",
                "agent_seat": "HR",
                "job_id": "",
                "description": (
                    "LeaveApplication.submit succeeds even when LeaveBalance for that leave_type "
                    "is already negative; no entitlement check.\n\n"
                    "What I did:\n"
                    f"1. LeaveBalance.list shows systemic negatives — sample id={neg['id']} "
                    f"employee_id={neg['employee_id']} ({emp2.get('email')}) "
                    f"leave_type={neg.get('leave_type')} balance_days={neg.get('balance_days')} "
                    f"used_days={neg.get('used_days')} opening_balance={neg.get('opening_balance')} "
                    f"accrued_days={neg.get('accrued_days')} fiscal_year={neg.get('fiscal_year')}.\n"
                    "2. Prior full scan: 294/294 LeaveBalance rows had balance_days < 0 "
                    "(opening=0, accrued=0, used>0).\n"
                    f"3. MCP LeaveApplication.create + submit for that employee/leave_type on "
                    f"2027-08-20 → {submitted.get('number')} "
                    f"(id={submitted.get('id')}, status={submitted.get('status')}).\n"
                    "4. Same pattern earlier: LA-2026-00577 / LA-2026-00581 (withdrawn after probe).\n\n"
                    "Expected: submit (and ideally create) should reject or hard-block when "
                    "requested days exceed available balance_days for that leave_type.\n\n"
                    "Actual: leave moves to pending_approval with no balance guard. "
                    "Payroll/HR agents cannot trust LeaveBalance as a gate.\n\n"
                    f"UI check: open Leave {submitted.get('number')} and LeaveBalance id={neg['id']}."
                ),
            },
            {
                "page": "LeaveApplication",
                "agent_seat": "HR",
                "job_id": "",
                "description": (
                    "LeaveApplication.create accepts inconsistent leave spans / types "
                    "(no max duration, half_day on multi-day, maternity on male).\n\n"
                    "What I did via MCP as team13:\n"
                    f"1. half_day=true spanning 2027-03-01..2027-03-05 for "
                    f"{other.get('email')} → {leave3a.get('number')} "
                    f"(id={leave3a.get('id')}, days={leave3a.get('days')}, "
                    f"half_day={leave3a.get('half_day')}, status=draft).\n"
                    f"2. leave_type=maternity for male employee "
                    f"{prakash.get('email')} (gender={prakash.get('gender')}) "
                    f"2027-09-01..2027-12-31 → {leave3b.get('number')} "
                    f"(id={leave3b.get('id')}, days={leave3b.get('days')}, status=draft).\n"
                    "3. Past full-year leave 2010-01-01..2010-12-31 accepted "
                    "(LA-2026-00579, days=365; cancelled after probe).\n"
                    "4. Already on shared book (not ours): LA-2026-00573 "
                    f"(id={extreme.get('id')}) paternity days={extreme.get('days')} "
                    f"half_day={extreme.get('half_day')} "
                    f"from={extreme.get('from_date')} to={extreme.get('to_date')} "
                    f"employee={extreme.get('_employee_id_display')}.\n\n"
                    "Expected: reject or constrain — e.g. half_day only for single-day; "
                    "cap max span; maternity only for eligible gender/employment rules; "
                    "block absurd multi-year / decade-old ranges.\n\n"
                    "Actual: drafts persist with impossible/ineligible combinations. "
                    "Same validation gap family as Attendance punch/LOP bugs, on Leave.\n\n"
                    f"UI check: {leave3a.get('number')}, {leave3b.get('number')}, "
                    "and existing LA-2026-00573."
                ),
            },
        ]

        for body in reports:
            r = httpx.post(
                f"{client.base_url}/api/bug-report",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=60,
            )
            print("file status", r.status_code, r.text[:400])
            if r.status_code >= 400:
                filed.append({"ok": False, "status": r.status_code, "body": r.text[:800], "sent": body})
            else:
                data = r.json()
                filed.append({"ok": True, "response": data, "page": body["page"]})

        mine = httpx.get(
            f"{client.base_url}/api/bug-report/mine",
            headers={"Authorization": f"Bearer {token}"},
            timeout=60,
        )
        mine_data = mine.json()
        payload = {"artefacts": artefacts, "filed": filed, "mine": mine_data}
        OUT.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        print("WROTE", OUT)
        if isinstance(mine_data, dict):
            rows = mine_data.get("data") or []
        else:
            rows = mine_data
        print("mine count", len(rows) if isinstance(rows, list) else mine_data)
        for m in (rows[:8] if isinstance(rows, list) else []):
            print("-", m.get("id"), (m.get("description") or "")[:90].replace("\n", " "))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
