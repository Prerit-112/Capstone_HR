"""Round-3 live probes for unfiled AgentSwitch HR bugs. Discuss before filing."""
from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from agent.mcp_client import McpClient, McpError  # noqa: E402

OUT = ROOT / "runs" / "bug_probe_round3.json"

EMP_ID = "baf152b3-e8ee-4da2-bee4-592637b9f94c"  # prakash.salunkhe
COMPANY_ID = "5cbe5a55-af74-4363-a436-f5350593114c"
LEFT_EMP = "2fd8fbe9-2fe5-434a-b68a-58cf14401142"  # anil.patil left


def unwrap(res):
    if isinstance(res, dict) and "structuredContent" in res:
        return res["structuredContent"]
    if isinstance(res, dict) and "content" in res:
        for c in res["content"]:
            if c.get("type") == "text":
                try:
                    return json.loads(c["text"])
                except Exception:
                    pass
    return res


def slim(row, keys):
    if not isinstance(row, dict):
        return row
    return {k: row.get(k) for k in keys}


def call(client, tool, args):
    try:
        r = unwrap(client.tools_call(tool, args))
        return True, r
    except McpError as e:
        return False, {"error": str(e)[:500], "code": e.code, "data": e.data}
    except Exception as e:
        return False, {"error": str(e)[:500]}


def cancel_leave(client, lid, status_hint=None):
    if not lid:
        return
    for tool in (
        "LeaveApplication.cancel.draft.cancelled",
        "LeaveApplication.withdraw",
    ):
        ok, _ = call(client, tool, {"id": lid})
        if ok:
            return tool
    return None


def main() -> int:
    password = os.getenv("AS_PASSWORD", "")
    if not password:
        print("Set AS_PASSWORD in .env")
        return 2

    results: list[dict] = []

    def note(title: str, **kw):
        results.append({"title": title, **kw})
        print("===", title, "===")
        print(json.dumps(kw, indent=2, default=str)[:2000])

    with McpClient(
        base_url=os.getenv("AS_BASE_URL", "https://agentswitch.theschoolofai.in"),
        email=os.getenv("AS_EMAIL", "team13@theschoolofai.in"),
        password=password,
    ) as client:
        client.login()
        client.initialize()

        # Catalogue snapshot: transition / write tools we care about
        tools = client.tools_list()
        names = sorted(t.get("name", "") for t in tools)
        note(
            "catalogue_hr_slice",
            leave=[n for n in names if n.startswith("LeaveApplication.")],
            attendance=[n for n in names if n.startswith("Attendance.")],
            balance=[n for n in names if n.startswith("LeaveBalance.")],
            holiday=[n for n in names if n.startswith("HolidayList.")],
            leave_type=[n for n in names if n.startswith("LeaveType.")],
            employee=[n for n in names if n.startswith("Employee.")],
        )

        # --- A) Attendance for left employee ---
        past = (date.today() - timedelta(days=5)).isoformat()
        ok, r = call(
            client,
            "Attendance.create",
            {
                "employee_id": LEFT_EMP,
                "company_id": COMPANY_ID,
                "date": past,
                "status": "present",
                "check_in": "09:00",
                "check_out": "18:00",
            },
        )
        note("att_for_left_employee", ok=ok, result=slim(r, ["id", "date", "status", "employee_id", "error", "code"]) if ok else r)
        if ok and isinstance(r, dict) and r.get("id"):
            note("att_for_left_artefact", id=r["id"], date=past)

        # --- B) Attendance present + on_leave mismatch fields ---
        d_b = (date.today() - timedelta(days=6)).isoformat()
        ok, r = call(
            client,
            "Attendance.create",
            {
                "employee_id": EMP_ID,
                "company_id": COMPANY_ID,
                "date": d_b,
                "status": "on_leave",
                "check_in": "09:00",
                "check_out": "18:00",
                "is_lop": True,
                "lop_hours": 8,
            },
        )
        note(
            "att_on_leave_with_punches_and_lop",
            ok=ok,
            result=slim(
                r,
                ["id", "date", "status", "check_in", "check_out", "is_lop", "lop_hours", "error", "code"],
            )
            if ok
            else r,
        )

        # --- C) Negative / absurd overtime ---
        d_c = (date.today() - timedelta(days=7)).isoformat()
        ok, r = call(
            client,
            "Attendance.create",
            {
                "employee_id": EMP_ID,
                "company_id": COMPANY_ID,
                "date": d_c,
                "status": "present",
                "check_in": "09:00",
                "check_out": "18:00",
                "overtime_hours": -3,
            },
        )
        note("att_negative_overtime", ok=ok, result=slim(r, ["id", "overtime_hours", "error", "code"]) if ok else r)

        # --- D) Invalid punch strings ---
        d_d = (date.today() - timedelta(days=8)).isoformat()
        ok, r = call(
            client,
            "Attendance.create",
            {
                "employee_id": EMP_ID,
                "company_id": COMPANY_ID,
                "date": d_d,
                "status": "present",
                "check_in": "25:99",
                "check_out": "not-a-time",
            },
        )
        note("att_invalid_punch_strings", ok=ok, result=slim(r, ["id", "check_in", "check_out", "error", "code"]) if ok else r)

        # --- E) Leave for suspended employee ---
        sus = client.list_all("Employee.list", {"limit": 20, "status": "suspended"}, max_pages=1)
        note("suspended_emps", count=len(sus["items"]), samples=[slim(x, ["id", "email", "status"]) for x in sus["items"][:3]])
        if sus["items"]:
            s = sus["items"][0]
            ok, r = call(
                client,
                "LeaveApplication.create",
                {
                    "employee_id": s["id"],
                    "company_id": s.get("company_id") or COMPANY_ID,
                    "from_date": "2027-07-01",
                    "to_date": "2027-07-01",
                    "leave_type": "casual",
                    "reason": "team13-bugprobe-r3: leave for suspended",
                },
            )
            note("leave_for_suspended", ok=ok, emp=slim(s, ["id", "email", "status"]), result=slim(r, ["id", "number", "status", "error", "code"]) if ok else r)
            if ok and isinstance(r, dict) and r.get("id"):
                cancel_leave(client, r["id"])

        # --- F) Leave before date_of_joining ---
        emp = unwrap(client.tools_call("Employee.get", {"id": EMP_ID}))
        note("probe_emp", **slim(emp, ["id", "email", "date_of_joining", "status", "gender", "sex"]))
        ok, r = call(
            client,
            "LeaveApplication.create",
            {
                "employee_id": EMP_ID,
                "company_id": COMPANY_ID,
                "from_date": "2000-01-10",
                "to_date": "2000-01-12",
                "leave_type": "casual",
                "reason": "team13-bugprobe-r3: leave before joining",
            },
        )
        note("leave_before_joining", ok=ok, doj=emp.get("date_of_joining"), result=slim(r, ["id", "number", "days", "from_date", "status", "error", "code"]) if ok else r)
        if ok and isinstance(r, dict) and r.get("id"):
            cancel_leave(client, r["id"])

        # --- G) Paternity on female (if we can find one) ---
        females = []
        page = client.list_all("Employee.list", {"limit": 50, "status": "active"}, max_pages=3)
        for e in page["items"]:
            g = (e.get("gender") or e.get("sex") or "").lower()
            if g in ("female", "f", "woman"):
                females.append(e)
        note("female_emps_found", count=len(females), samples=[slim(x, ["id", "email", "gender", "sex"]) for x in females[:3]])
        if females:
            f = females[0]
            ok, r = call(
                client,
                "LeaveApplication.create",
                {
                    "employee_id": f["id"],
                    "company_id": f.get("company_id") or COMPANY_ID,
                    "from_date": "2027-10-01",
                    "to_date": "2027-10-15",
                    "leave_type": "paternity",
                    "reason": "team13-bugprobe-r3: paternity on female",
                },
            )
            note("paternity_on_female", ok=ok, emp=slim(f, ["id", "email", "gender", "sex"]), result=slim(r, ["id", "number", "leave_type", "days", "status", "error", "code"]) if ok else r)
            if ok and isinstance(r, dict) and r.get("id"):
                cancel_leave(client, r["id"])

        # --- H) Cross-company mismatch ---
        companies = set()
        for e in page["items"]:
            if e.get("company_id"):
                companies.add(e["company_id"])
        note("companies_seen", companies=list(companies)[:5])
        other_co = next((c for c in companies if c != COMPANY_ID), None)
        if other_co:
            ok, r = call(
                client,
                "LeaveApplication.create",
                {
                    "employee_id": EMP_ID,
                    "company_id": other_co,
                    "from_date": "2027-11-01",
                    "to_date": "2027-11-01",
                    "leave_type": "casual",
                    "reason": "team13-bugprobe-r3: cross-company",
                },
            )
            note("leave_cross_company", ok=ok, emp_company=COMPANY_ID, used_company=other_co, result=slim(r, ["id", "number", "company_id", "employee_id", "status", "error", "code"]) if ok else r)
            if ok and isinstance(r, dict) and r.get("id"):
                cancel_leave(client, r["id"])

        # --- I) Update pending leave dates (mutate after submit) ---
        ok, created = call(
            client,
            "LeaveApplication.create",
            {
                "employee_id": EMP_ID,
                "company_id": COMPANY_ID,
                "from_date": "2027-12-01",
                "to_date": "2027-12-01",
                "leave_type": "casual",
                "reason": "team13-bugprobe-r3: mutate after submit",
            },
        )
        note("mutate_create", ok=ok, result=slim(created, ["id", "number", "status"]) if ok else created)
        if ok and isinstance(created, dict) and created.get("id"):
            ok_s, submitted = call(client, "LeaveApplication.submit", {"id": created["id"]})
            note("mutate_submit", ok=ok_s, status=submitted.get("status") if isinstance(submitted, dict) else submitted)
            ok_u, updated = call(
                client,
                "LeaveApplication.update",
                {
                    "id": created["id"],
                    "from_date": "2027-12-10",
                    "to_date": "2027-12-20",
                    "reason": "team13-bugprobe-r3: mutated dates while pending",
                },
            )
            note(
                "mutate_pending_dates",
                ok=ok_u,
                result=slim(updated, ["id", "status", "from_date", "to_date", "days", "error", "code"]) if ok_u else updated,
            )
            cancel_leave(client, created["id"])

        # --- J) LeaveBalance.create absurd ---
        ok, r = call(
            client,
            "LeaveBalance.create",
            {
                "employee_id": EMP_ID,
                "company_id": COMPANY_ID,
                "leave_type": "casual",
                "fiscal_year": 2099,
                "opening_balance": 9999,
                "accrued_days": 0,
                "used_days": 0,
            },
        )
        note("balance_create_absurd", ok=ok, result=slim(r, ["id", "balance_days", "opening_balance", "fiscal_year", "leave_type", "error", "code"]) if ok else r)

        # --- K) HolidayList empty + create? ---
        hol = client.list_all("HolidayList.list", {"limit": 20}, max_pages=1)
        note("holiday_list", count=len(hol["items"]), total=hol.get("total"), sample=hol["items"][:2])
        # discover create schema args via a minimal attempt
        ok, r = call(
            client,
            "HolidayList.create",
            {
                "company_id": COMPANY_ID,
                "name": "team13-probe-holiday",
                "date": "2027-01-26",
            },
        )
        note("holiday_create", ok=ok, result=r if not ok else slim(r, ["id", "name", "date", "error", "code"]))

        # --- L) LeaveType empty still? ---
        lt = client.list_all("LeaveType.list", {"limit": 50}, max_pages=1)
        note("leave_type_list", count=len(lt["items"]), total=lt.get("total"), sample=lt["items"][:3])

        # --- M) Attendance.list date filter semantics (equality vs range) ---
        # create a known attendance if needed, then query with surrounding dates
        d_m = (date.today() - timedelta(days=9)).isoformat()
        ok, att = call(
            client,
            "Attendance.create",
            {
                "employee_id": EMP_ID,
                "company_id": COMPANY_ID,
                "date": d_m,
                "status": "absent",
            },
        )
        note("att_filter_seed", ok=ok, date=d_m, result=slim(att, ["id", "date", "status"]) if ok else att)
        # try range-like filters if schema allows from_date/to_date or date_from
        for label, args in [
            ("exact", {"date": d_m, "employee_id": EMP_ID, "limit": 20}),
            ("wrong_day", {"date": (date.today() - timedelta(days=10)).isoformat(), "employee_id": EMP_ID, "limit": 20}),
            ("from_to", {"from_date": d_m, "to_date": d_m, "employee_id": EMP_ID, "limit": 20}),
            ("date_gte", {"date": d_m, "employee_id": EMP_ID, "limit": 20}),
        ]:
            ok_f, listed = call(client, "Attendance.list", args)
            items = listed.get("items", []) if isinstance(listed, dict) else []
            note(
                f"att_list_{label}",
                ok=ok_f,
                total=listed.get("total") if isinstance(listed, dict) else None,
                n=len(items) if ok_f else None,
                error=None if ok_f else listed,
            )

        # --- N) Employee.update: set active left emp back? read-only probe of left then try leave submit path already done ---
        ok, r = call(
            client,
            "Employee.update",
            {"id": LEFT_EMP, "status": "active"},
        )
        note("employee_resurrect_left", ok=ok, result=slim(r, ["id", "status", "email", "error", "code"]) if ok else r)
        if ok and isinstance(r, dict) and r.get("status") == "active":
            # restore left
            ok2, r2 = call(client, "Employee.update", {"id": LEFT_EMP, "status": "left"})
            note("employee_restore_left", ok=ok2, status=r2.get("status") if isinstance(r2, dict) else r2)

        # --- O) half_day true with days forced / unpaid leave type ---
        for label, args in [
            (
                "comp_off",
                {
                    "employee_id": EMP_ID,
                    "company_id": COMPANY_ID,
                    "from_date": "2028-01-05",
                    "to_date": "2028-01-05",
                    "leave_type": "compensatory",
                    "reason": "team13-bugprobe-r3: compensatory",
                },
            ),
            (
                "unpaid",
                {
                    "employee_id": EMP_ID,
                    "company_id": COMPANY_ID,
                    "from_date": "2028-01-06",
                    "to_date": "2028-01-06",
                    "leave_type": "unpaid",
                    "reason": "team13-bugprobe-r3: unpaid",
                },
            ),
            (
                "earned",
                {
                    "employee_id": EMP_ID,
                    "company_id": COMPANY_ID,
                    "from_date": "2028-01-07",
                    "to_date": "2028-01-07",
                    "leave_type": "earned",
                    "reason": "team13-bugprobe-r3: earned",
                },
            ),
        ]:
            ok, r = call(client, "LeaveApplication.create", args)
            note(f"leave_type_{label}", ok=ok, result=slim(r, ["id", "number", "leave_type", "status", "error", "code"]) if ok else r)
            if ok and isinstance(r, dict) and r.get("id"):
                cancel_leave(client, r["id"])

        # --- P) Submit then withdraw then re-submit same dates? create new ---
        # Already know overlap works. Try: create draft, cancel, create same dates again
        ok1, a = call(
            client,
            "LeaveApplication.create",
            {
                "employee_id": EMP_ID,
                "company_id": COMPANY_ID,
                "from_date": "2028-02-01",
                "to_date": "2028-02-02",
                "leave_type": "sick",
                "reason": "team13-bugprobe-r3: cancel then recreate A",
            },
        )
        if ok1 and isinstance(a, dict) and a.get("id"):
            cancel_leave(client, a["id"])
            ok2, b = call(
                client,
                "LeaveApplication.create",
                {
                    "employee_id": EMP_ID,
                    "company_id": COMPANY_ID,
                    "from_date": "2028-02-01",
                    "to_date": "2028-02-02",
                    "leave_type": "sick",
                    "reason": "team13-bugprobe-r3: cancel then recreate B",
                },
            )
            note(
                "recreate_after_cancel",
                first=slim(a, ["id", "number", "status"]),
                second_ok=ok2,
                second=slim(b, ["id", "number", "status", "error", "code"]) if ok2 else b,
            )
            if ok2 and isinstance(b, dict) and b.get("id"):
                cancel_leave(client, b["id"])
        else:
            note("recreate_after_cancel", first_ok=ok1, first=a)

        # --- Q) Pagination: limit=1 total consistency ---
        ok, page1 = call(client, "LeaveApplication.list", {"limit": 1})
        ok2, page2 = call(client, "LeaveApplication.list", {"limit": 1, "offset": 1})
        note(
            "leave_pagination",
            page1_ok=ok,
            total=page1.get("total") if isinstance(page1, dict) else None,
            n1=len(page1.get("items", [])) if isinstance(page1, dict) else None,
            page2_ok=ok2,
            n2=len(page2.get("items", [])) if isinstance(page2, dict) else None,
            id1=(page1.get("items") or [{}])[0].get("id") if isinstance(page1, dict) else None,
            id2=(page2.get("items") or [{}])[0].get("id") if isinstance(page2, dict) else None,
            err=None if ok else page1,
        )

        # --- R) Attendance for date with approved leave still present ---
        # Find any approved leave overlapping a past date, or create pending and mark attendance present
        leaves = client.list_all(
            "LeaveApplication.list",
            {"limit": 50, "employee_id": EMP_ID, "status": "approved"},
            max_pages=2,
        )
        note(
            "approved_leaves_for_emp",
            count=len(leaves["items"]),
            samples=[slim(x, ["id", "number", "from_date", "to_date", "status"]) for x in leaves["items"][:5]],
        )

        # --- S) is_lop=false but lop_hours>0 ---
        d_s = (date.today() - timedelta(days=11)).isoformat()
        ok, r = call(
            client,
            "Attendance.create",
            {
                "employee_id": EMP_ID,
                "company_id": COMPANY_ID,
                "date": d_s,
                "status": "present",
                "check_in": "09:00",
                "check_out": "17:00",
                "is_lop": False,
                "lop_hours": 4,
            },
        )
        note(
            "att_lop_hours_without_flag",
            ok=ok,
            result=slim(r, ["id", "is_lop", "lop_hours", "status", "error", "code"]) if ok else r,
        )

        # --- T) Employee.create minimal / weird ---
        ok, r = call(
            client,
            "Employee.create",
            {
                "company_id": COMPANY_ID,
                "first_name": "Team13",
                "last_name": "Probe",
                "email": f"team13.probe.{int(date.today().strftime('%Y%m%d'))}@corp.in",
                "date_of_joining": "2026-01-01",
                "status": "left",
                "exit_date": "2025-01-01",
            },
        )
        note("employee_create_left_before_join", ok=ok, result=slim(r, ["id", "email", "status", "date_of_joining", "exit_date", "error", "code"]) if ok else r)

    OUT.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print("WROTE", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
