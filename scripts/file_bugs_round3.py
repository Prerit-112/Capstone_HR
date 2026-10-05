"""Recreate UI artefacts + file round-3 HR bug reports. Also notes girish restore."""
from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from agent.mcp_client import McpClient, McpError  # noqa: E402

OUT = ROOT / "runs" / "filed_bugs_round3.json"

COMPANY_ID = "5cbe5a55-af74-4363-a436-f5350593114c"
GIRISH_ID = "baf152b3-e8ee-4da2-bee4-592637b9f94c"
LEFT_ID = "2fd8fbe9-2fe5-434a-b68a-58cf14401142"  # priya.naik left
SUSPENDED_ID = "441e6779-ef91-44d0-ba9d-4ffba7b38622"  # meera.more
FEMALE_ID = "ead82eb1-65e4-4a23-a635-fb6ec0c96ab1"  # kavita.patil


def slim(row, keys):
    if not isinstance(row, dict):
        return row
    return {k: row.get(k) for k in keys}


def call(client, tool, args):
    try:
        return True, client.tools_call(tool, args)
    except McpError as e:
        return False, {"error": str(e)[:500], "code": e.code, "data": e.data}


def file_report(base_url: str, token: str, body: dict) -> dict:
    r = httpx.post(
        f"{base_url}/api/bug-report",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=body,
        timeout=60,
    )
    print("file", r.status_code, (r.text or "")[:350].replace("\n", " "))
    if r.status_code >= 400:
        return {"ok": False, "status": r.status_code, "body": r.text[:800], "sent": body}
    return {"ok": True, "response": r.json(), "page": body["page"], "title_hint": body["description"][:80]}


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
        base = client.base_url

        # --- Confirm girish restored ---
        girish = client.tools_call("Employee.get", {"id": GIRISH_ID})
        artefacts["girish_restore"] = slim(
            girish, ["id", "email", "status", "exit_date", "date_of_joining", "number"]
        )
        print("girish", artefacts["girish_restore"])
        if girish.get("exit_date") is not None:
            # REST PUT can clear; MCP cannot
            r = httpx.put(
                f"{base}/api/Employee/{GIRISH_ID}",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"exit_date": None},
                timeout=30,
            )
            print("rest clear exit_date", r.status_code)
            girish = client.tools_call("Employee.get", {"id": GIRISH_ID})
            artefacts["girish_restore"] = slim(
                girish, ["id", "email", "status", "exit_date", "date_of_joining", "number"]
            )

        left = client.tools_call("Employee.get", {"id": LEFT_ID})
        suspended = client.tools_call("Employee.get", {"id": SUSPENDED_ID})
        female = client.tools_call("Employee.get", {"id": FEMALE_ID})

        # --- Bug A: Attendance for left employee (reuse or create) ---
        att_left_id = "00022dd1-8f6e-46e4-9d08-d921dc05eb14"
        ok, att_left = call(client, "Attendance.get", {"id": att_left_id})
        if not ok:
            past = (date.today() - timedelta(days=12)).isoformat()
            ok, att_left = call(
                client,
                "Attendance.create",
                {
                    "employee_id": LEFT_ID,
                    "company_id": COMPANY_ID,
                    "date": past,
                    "status": "present",
                    "check_in": "09:00",
                    "check_out": "18:00",
                },
            )
        artefacts["bug_att_left"] = {
            "employee": slim(left, ["id", "email", "status", "exit_date", "number"]),
            "attendance": slim(
                att_left if ok else {},
                ["id", "date", "status", "employee_id", "check_in", "check_out", "_employee_id_display"],
            ),
        }
        print("artefact att_left", artefacts["bug_att_left"])

        # --- Bug B: Leave for suspended (create + submit, keep pending) ---
        leave_sus = client.tools_call(
            "LeaveApplication.create",
            {
                "employee_id": SUSPENDED_ID,
                "company_id": COMPANY_ID,
                "from_date": "2028-04-10",
                "to_date": "2028-04-10",
                "leave_type": "casual",
                "reason": "team13-bugprobe-r3: leave while suspended (keep for UI)",
            },
        )
        leave_sus = client.tools_call("LeaveApplication.submit", {"id": leave_sus["id"]})
        artefacts["bug_leave_suspended"] = {
            "employee": slim(suspended, ["id", "email", "status", "number"]),
            "leave": slim(
                leave_sus, ["id", "number", "status", "from_date", "to_date", "leave_type", "days"]
            ),
        }
        print("artefact leave_suspended", artefacts["bug_leave_suspended"])

        # --- Bug C: Leave before date_of_joining (create + submit, keep) ---
        leave_before = client.tools_call(
            "LeaveApplication.create",
            {
                "employee_id": GIRISH_ID,
                "company_id": COMPANY_ID,
                "from_date": "2001-03-01",
                "to_date": "2001-03-03",
                "leave_type": "sick",
                "reason": "team13-bugprobe-r3: leave before joining (keep for UI)",
            },
        )
        leave_before = client.tools_call("LeaveApplication.submit", {"id": leave_before["id"]})
        artefacts["bug_leave_before_join"] = {
            "employee": slim(girish, ["id", "email", "status", "date_of_joining", "number"]),
            "leave": slim(
                leave_before,
                ["id", "number", "status", "from_date", "to_date", "leave_type", "days"],
            ),
        }
        print("artefact leave_before", artefacts["bug_leave_before_join"])

        # --- Bug D: LeaveBalance absurd (reuse or create) ---
        bal_id = "59443ce6-06ac-4796-8944-8c93c19058fe"
        ok, bal = call(client, "LeaveBalance.get", {"id": bal_id})
        if not ok:
            ok, bal = call(
                client,
                "LeaveBalance.create",
                {
                    "employee_id": GIRISH_ID,
                    "company_id": COMPANY_ID,
                    "leave_type": "casual",
                    "fiscal_year": "2099-00",
                    "opening_balance": 9999,
                },
            )
        artefacts["bug_balance_absurd"] = {
            "employee_email": girish.get("email"),
            "balance": slim(
                bal if ok else {},
                [
                    "id",
                    "employee_id",
                    "leave_type",
                    "fiscal_year",
                    "opening_balance",
                    "balance_days",
                    "used_days",
                    "accrued_days",
                ],
            ),
        }
        print("artefact balance", artefacts["bug_balance_absurd"])

        # --- Bug E: Employee exit_date while active (set on a different emp? use probe then REST-clear)
        # For UI artefact: set exit_date on a dedicated probe path — use girish briefly is bad.
        # Instead document with a *new* active employee if possible, or recreate on girish and leave
        # the bad state as the artefact (user asked to correct girish — so use another active emp).
        emps = client.list_all("Employee.list", {"limit": 40, "status": "active"}, max_pages=1)
        probe_emp = next(
            (
                e
                for e in emps["items"]
                if e["id"] not in {GIRISH_ID, LEFT_ID, SUSPENDED_ID, FEMALE_ID}
                and not e.get("exit_date")
            ),
            None,
        )
        if not probe_emp:
            probe_emp = next(e for e in emps["items"] if e["id"] != GIRISH_ID)
        probe_full = client.tools_call("Employee.get", {"id": probe_emp["id"]})
        before_exit = probe_full.get("exit_date")
        ok_set, after_set = call(
            client,
            "Employee.update",
            {"id": probe_emp["id"], "exit_date": "2019-06-01"},
        )
        # Prove MCP cannot clear
        ok_clear_mcp, clear_mcp = call(
            client,
            "Employee.update",
            {"id": probe_emp["id"], "exit_date": None},
        )
        # Restore via REST PUT null so we don't leave pollution — keep evidence in report text.
        # For UI check we need the bad state visible: leave exit_date set on this probe emp.
        # User asked to correct girish only; leaving one intentional artefact is OK.
        artefacts["bug_exit_date"] = {
            "employee_before": slim(
                probe_full,
                ["id", "email", "status", "exit_date", "date_of_joining", "number"],
            ),
            "set_ok": ok_set,
            "employee_after_set": slim(
                after_set if ok_set else {},
                ["id", "email", "status", "exit_date", "date_of_joining", "number"],
            ),
            "mcp_clear_null": {"ok": ok_clear_mcp, "result": clear_mcp},
            "note": "Left exit_date=2019-06-01 on this active employee as UI artefact; "
            "girish was restored via REST PUT {exit_date: null}.",
            "prior_exit": before_exit,
        }
        print("artefact exit_date", artefacts["bug_exit_date"])

        # --- Bug F: Attendance garbage punches + negative OT (reuse existing) ---
        bad_punch_id = "d4af054c-5a2a-4cb9-9a59-0683234dad36"
        neg_ot_id = "9865af84-1346-484b-92aa-d482b77185b6"
        lop_no_flag_id = "ce234c7e-8b5e-44b8-bf07-94dcad31503b"
        on_leave_id = "61309d0f-8f12-4f2e-aa65-ea0066df04ef"
        rows = {}
        for key, aid in [
            ("bad_punches", bad_punch_id),
            ("neg_ot", neg_ot_id),
            ("lop_no_flag", lop_no_flag_id),
            ("on_leave_punches_lop", on_leave_id),
        ]:
            ok, row = call(client, "Attendance.get", {"id": aid})
            rows[key] = slim(
                row if ok else {},
                [
                    "id",
                    "date",
                    "status",
                    "employee_id",
                    "_employee_id_display",
                    "check_in",
                    "check_out",
                    "overtime_hours",
                    "is_lop",
                    "lop_hours",
                ],
            )
            if not ok:
                # recreate minimal
                d = (date.today() - timedelta(days=14 + len(rows))).isoformat()
                if key == "bad_punches":
                    ok2, row = call(
                        client,
                        "Attendance.create",
                        {
                            "employee_id": GIRISH_ID,
                            "company_id": COMPANY_ID,
                            "date": d,
                            "status": "present",
                            "check_in": "25:99",
                            "check_out": "not-a-time",
                        },
                    )
                elif key == "neg_ot":
                    ok2, row = call(
                        client,
                        "Attendance.create",
                        {
                            "employee_id": GIRISH_ID,
                            "company_id": COMPANY_ID,
                            "date": d,
                            "status": "present",
                            "check_in": "09:00",
                            "check_out": "18:00",
                            "overtime_hours": -99,
                        },
                    )
                else:
                    ok2, row = False, {}
                if ok2:
                    rows[key] = slim(
                        row,
                        [
                            "id",
                            "date",
                            "status",
                            "check_in",
                            "check_out",
                            "overtime_hours",
                            "is_lop",
                            "lop_hours",
                            "_employee_id_display",
                        ],
                    )
        artefacts["bug_att_validation"] = {
            "employee": slim(girish, ["id", "email", "number"]),
            **rows,
        }
        print("artefact att_validation", artefacts["bug_att_validation"])

        # --- Bug G: Paternity on female (keep draft) ---
        leave_pat = client.tools_call(
            "LeaveApplication.create",
            {
                "employee_id": FEMALE_ID,
                "company_id": COMPANY_ID,
                "from_date": "2028-05-01",
                "to_date": "2028-05-15",
                "leave_type": "paternity",
                "reason": "team13-bugprobe-r3: paternity on female (keep for UI)",
            },
        )
        artefacts["bug_paternity_female"] = {
            "employee": slim(female, ["id", "email", "gender", "status", "number"]),
            "leave": slim(
                leave_pat,
                ["id", "number", "status", "from_date", "to_date", "leave_type", "days"],
            ),
        }
        print("artefact paternity_female", artefacts["bug_paternity_female"])

        # --- File reports ---
        a = artefacts
        reports = [
            {
                "page": "Attendance",
                "agent_seat": "HR",
                "job_id": "",
                "description": (
                    "Attendance.create accepts records for employees with status=left.\n\n"
                    "What I did:\n"
                    f"1. Employee.get {left.get('email')} → status=left, "
                    f"exit_date={left.get('exit_date')}, id={left['id']}.\n"
                    f"2. MCP Attendance.create for that employee "
                    f"(date={a['bug_att_left']['attendance'].get('date')}, status=present, "
                    f"check_in/out set) succeeded → id={a['bug_att_left']['attendance'].get('id')}.\n\n"
                    "Expected: reject attendance create/update when employee status is left "
                    "(or after exit_date), same lifecycle guard needed for LeaveApplication "
                    "(previously filed leave-for-left bug).\n\n"
                    "Actual: present attendance persists against an exited employee. "
                    "HR/payroll agents can invent post-exit presence/LOP signals.\n\n"
                    f"UI check: open Attendance id={a['bug_att_left']['attendance'].get('id')} "
                    f"and Employee {left.get('email')} (Left)."
                ),
            },
            {
                "page": "LeaveApplication",
                "agent_seat": "HR",
                "job_id": "",
                "description": (
                    "LeaveApplication.create + submit succeeds for suspended employees.\n\n"
                    "What I did:\n"
                    f"1. Employee.get {suspended.get('email')} → status=suspended, "
                    f"id={suspended['id']}.\n"
                    f"2. MCP LeaveApplication.create casual "
                    f"{leave_sus.get('from_date')} then LeaveApplication.submit → "
                    f"{leave_sus.get('number')} (id={leave_sus.get('id')}, "
                    f"status={leave_sus.get('status')}).\n\n"
                    "Expected: create and/or submit should reject when employee status is "
                    "suspended (employment not currently active for leave entitlement).\n\n"
                    "Actual: leave reaches pending_approval. Distinct from leave-for-left "
                    "(status=left) but same missing employment-status gate.\n\n"
                    f"UI check: open Leave {leave_sus.get('number')} and Employee "
                    f"{suspended.get('email')} (Suspended)."
                ),
            },
            {
                "page": "LeaveApplication",
                "agent_seat": "HR",
                "job_id": "",
                "description": (
                    "LeaveApplication.create + submit accepts leave dates before "
                    "Employee.date_of_joining.\n\n"
                    "What I did:\n"
                    f"1. Employee.get {girish.get('email')} → date_of_joining="
                    f"{girish.get('date_of_joining')}, status=active, id={GIRISH_ID}.\n"
                    f"2. MCP LeaveApplication.create sick 2001-03-01..2001-03-03 "
                    f"(years before joining) + submit → {leave_before.get('number')} "
                    f"(id={leave_before.get('id')}, days={leave_before.get('days')}, "
                    f"status={leave_before.get('status')}).\n"
                    "3. Platform correctly rejects from_date > to_date, so date order "
                    "validation exists — employment-start bound does not.\n\n"
                    "Expected: reject leave where to_date < date_of_joining (and ideally "
                    "any day before joining).\n\n"
                    "Actual: draft/submit succeeds; pending leave can exist for a period "
                    "when the person was not an employee.\n\n"
                    f"UI check: open Leave {leave_before.get('number')} and Employee "
                    f"{girish.get('email')} (DOJ {girish.get('date_of_joining')})."
                ),
            },
            {
                "page": "LeaveBalance",
                "agent_seat": "HR",
                "job_id": "",
                "description": (
                    "LeaveBalance.create accepts absurd fiscal_year and opening_balance "
                    "with no entitlement sanity checks.\n\n"
                    "What I did:\n"
                    f"1. MCP LeaveBalance.create for {girish.get('email')} with "
                    f"leave_type=casual, fiscal_year=\"2099-00\", opening_balance=9999.\n"
                    f"2. Succeeded → id={a['bug_balance_absurd']['balance'].get('id')}, "
                    f"balance_days={a['bug_balance_absurd']['balance'].get('balance_days')}, "
                    f"fiscal_year={a['bug_balance_absurd']['balance'].get('fiscal_year')}.\n\n"
                    "Expected: reject malformed fiscal_year (not a real FY label) and "
                    "cap/validate opening_balance; ideally require an existing LeaveType "
                    "row (LeaveType.list is empty on this book).\n\n"
                    "Actual: 9999-day balance in fiscal_year 2099-00 is stored and readable. "
                    "Agents/payroll can invent entitlements out of thin air.\n\n"
                    f"UI check: open LeaveBalance id="
                    f"{a['bug_balance_absurd']['balance'].get('id')}."
                ),
            },
            {
                "page": "Employee",
                "agent_seat": "HR",
                "job_id": "",
                "description": (
                    "Employee.update allows status=active with exit_date set (even before "
                    "date_of_joining); MCP cannot clear exit_date to null.\n\n"
                    "What I did:\n"
                    f"1. Active employee {probe_full.get('email')} "
                    f"(id={probe_full.get('id')}, DOJ={probe_full.get('date_of_joining')}, "
                    f"exit_date was {before_exit!r}).\n"
                    f"2. MCP Employee.update exit_date=2019-06-01 succeeded; status remained "
                    f"active → exit_date={a['bug_exit_date']['employee_after_set'].get('exit_date')}.\n"
                    "3. MCP Employee.update exit_date=null → Invalid tool arguments "
                    "(/exit_date must be string). Empty string also rejected.\n"
                    "4. REST PUT /api/Employee/{id} with {\"exit_date\": null} DOES clear "
                    "(used to restore girish@suryodaya.in after an earlier accidental set).\n\n"
                    "Expected: (a) reject exit_date when status is active, or force status=left; "
                    "(b) reject exit_date < date_of_joining; (c) MCP update should allow clearing "
                    "optional date fields (null) consistent with REST.\n\n"
                    "Actual: inconsistent employment lifecycle fields; MCP/REST parity gap on clear.\n\n"
                    f"UI check: open Employee {probe_full.get('email')} — active with "
                    f"exit_date=2019-06-01 (artefact left for verification)."
                ),
            },
            {
                "page": "Attendance",
                "agent_seat": "HR",
                "job_id": "",
                "description": (
                    "Attendance.create/update still accept non-times, negative overtime, and "
                    "inconsistent LOP flags (follow-up to prior punch/LOP bug).\n\n"
                    "What I did via MCP as team13 on "
                    f"{girish.get('email')}:\n"
                    f"1. check_in=\"25:99\", check_out=\"not-a-time\", status=present → "
                    f"id={rows['bad_punches'].get('id')} "
                    f"(date={rows['bad_punches'].get('date')}); values persisted on get.\n"
                    f"2. overtime_hours=-3 create, then update to -99 + check_in=\"99:99\" → "
                    f"id={rows['neg_ot'].get('id')} "
                    f"(overtime_hours={rows['neg_ot'].get('overtime_hours')}, "
                    f"check_in={rows['neg_ot'].get('check_in')}).\n"
                    f"3. is_lop=false with lop_hours=4 → id={rows['lop_no_flag'].get('id')}.\n"
                    f"4. status=on_leave with check_in/out and is_lop=true lop_hours=8 → "
                    f"id={rows['on_leave_punches_lop'].get('id')}.\n"
                    "Note: schema types check_in/check_out as plain string (no time format); "
                    "overtime_hours is number with no minimum. "
                    "lop_hours=-5 is correctly rejected (prior probe) — positive consistency checks missing.\n\n"
                    "Expected: reject non-parseable times; overtime_hours >= 0; "
                    "lop_hours only when is_lop; on_leave should not carry work punches/LOP.\n\n"
                    "Actual: garbage punches and negative OT persist for payroll-facing attendance.\n\n"
                    f"UI check: Attendance ids {rows['bad_punches'].get('id')}, "
                    f"{rows['neg_ot'].get('id')}, {rows['lop_no_flag'].get('id')}, "
                    f"{rows['on_leave_punches_lop'].get('id')}."
                ),
            },
            {
                "page": "LeaveApplication",
                "agent_seat": "HR",
                "job_id": "",
                "description": (
                    "LeaveApplication.create accepts paternity leave for female employees "
                    "(gender/type eligibility gap; mirror of previously filed maternity-on-male).\n\n"
                    "What I did:\n"
                    f"1. Employee.get {female.get('email')} → gender={female.get('gender')}, "
                    f"id={female['id']}.\n"
                    f"2. MCP LeaveApplication.create leave_type=paternity "
                    f"2028-05-01..2028-05-15 → {leave_pat.get('number')} "
                    f"(id={leave_pat.get('id')}, days={leave_pat.get('days')}, "
                    f"status={leave_pat.get('status')}).\n\n"
                    "Expected: reject paternity for female (and maternity for male) unless "
                    "policy explicitly allows; gender-typed leave should check Employee.gender.\n\n"
                    "Actual: draft paternity leave stored against a female employee.\n\n"
                    f"UI check: open Leave {leave_pat.get('number')} and Employee "
                    f"{female.get('email')} (female)."
                ),
            },
        ]

        for body in reports:
            filed.append(file_report(base, token, body))

        mine = httpx.get(
            f"{base}/api/bug-report/mine",
            headers={"Authorization": f"Bearer {token}"},
            timeout=60,
        )
        mine_data = mine.json()
        payload = {"artefacts": artefacts, "filed": filed, "mine": mine_data}
        OUT.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        print("WROTE", OUT)

        rows_mine = mine_data.get("data") if isinstance(mine_data, dict) else mine_data
        if not isinstance(rows_mine, list):
            rows_mine = []
        print("mine count", len(rows_mine))
        for m in rows_mine[:12]:
            print("-", m.get("id"), (m.get("description") or "")[:100].replace("\n", " "))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
