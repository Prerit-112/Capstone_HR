"""Follow-up: confirm list shapes + strengthen round-3 candidates."""
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

OUT = ROOT / "runs" / "bug_probe_round3b.json"


def note(results, title, **kw):
    results.append({"title": title, **kw})
    print("===", title, "===")
    print(json.dumps(kw, indent=2, default=str)[:2500])


def call(client, tool, args):
    try:
        return True, client.tools_call(tool, args)
    except McpError as e:
        return False, {"error": str(e)[:500], "code": e.code, "data": e.data}
    except Exception as e:
        return False, {"error": str(e)[:500]}


def main() -> int:
    results = []
    with McpClient(
        base_url=os.getenv("AS_BASE_URL", "https://agentswitch.theschoolofai.in"),
        email=os.getenv("AS_EMAIL", "team13@theschoolofai.in"),
        password=os.getenv("AS_PASSWORD", ""),
    ) as client:
        client.login()
        client.initialize()

        ok, page = call(client, "LeaveApplication.list", {"limit": 2})
        note(
            results,
            "leave_list_shape",
            ok=ok,
            keys=sorted(page.keys()) if isinstance(page, dict) else type(page).__name__,
            total=page.get("total") if isinstance(page, dict) else None,
            data_n=len(page.get("data") or []) if isinstance(page, dict) else None,
            items_n=len(page.get("items") or []) if isinstance(page, dict) else None,
            sample_keys=sorted((page.get("data") or page.get("items") or [{}])[0].keys())[:30]
            if isinstance(page, dict) and (page.get("data") or page.get("items"))
            else None,
            first={
                k: (page.get("data") or page.get("items") or [{}])[0].get(k)
                for k in ["id", "number", "status", "from_date", "to_date", "employee_id"]
            }
            if isinstance(page, dict) and (page.get("data") or page.get("items"))
            else None,
        )

        ok, page = call(
            client,
            "Attendance.list",
            {"limit": 5, "employee_id": "baf152b3-e8ee-4da2-bee4-592637b9f94c"},
        )
        note(
            results,
            "att_list_shape",
            ok=ok,
            keys=sorted(page.keys()) if isinstance(page, dict) else type(page).__name__,
            total=page.get("total") if isinstance(page, dict) else None,
            data_n=len(page.get("data") or []) if isinstance(page, dict) else None,
            sample=[
                {k: x.get(k) for k in ["id", "date", "status", "check_in", "check_out", "overtime_hours", "is_lop", "lop_hours"]}
                for x in (page.get("data") or [])[:5]
            ]
            if isinstance(page, dict)
            else page,
        )

        # Confirm artefacts from round3
        for label, eid in [
            ("att_left", "00022dd1-8f6e-46e4-9d08-d921dc05eb14"),
            ("att_on_leave_punches", "61309d0f-8f12-4f2e-aa65-ea0066df04ef"),
            ("att_neg_ot", "9865af84-1346-484b-92aa-d482b77185b6"),
            ("att_bad_punches", "d4af054c-5a2a-4cb9-9a59-0683234dad36"),
            ("att_lop_no_flag", "ce234c7e-8b5e-44b8-bf07-94dcad31503b"),
        ]:
            ok, r = call(client, "Attendance.get", {"id": eid})
            note(
                results,
                f"get_{label}",
                ok=ok,
                row={
                    k: r.get(k)
                    for k in [
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
                    ]
                }
                if ok and isinstance(r, dict)
                else r,
            )

        for label, lid in [
            ("leave_suspended", "b2d3919d-afa2-4435-9aa1-075b0c3b1f8e"),  # cancelled?
            ("leave_before_join", "9b13c808-a78d-4795-b73f-e10642f94b43"),
            ("paternity_female", "728b53c0-b58a-4898-9fba-878b95e1a949"),
        ]:
            ok, r = call(client, "LeaveApplication.get", {"id": lid})
            note(
                results,
                f"get_{label}",
                ok=ok,
                row={
                    k: r.get(k)
                    for k in [
                        "id",
                        "number",
                        "status",
                        "leave_type",
                        "from_date",
                        "to_date",
                        "days",
                        "employee_id",
                        "_employee_id_display",
                        "reason",
                    ]
                }
                if ok and isinstance(r, dict)
                else r,
            )

        # Left employee current state + attendance against them
        ok, left = call(client, "Employee.get", {"id": "2fd8fbe9-2fe5-434a-b68a-58cf14401142"})
        note(
            results,
            "left_emp_now",
            ok=ok,
            row={
                k: left.get(k)
                for k in [
                    "id",
                    "email",
                    "status",
                    "date_of_joining",
                    "exit_date",
                    "relieving_date",
                    "first_name",
                    "last_name",
                ]
            }
            if ok and isinstance(left, dict)
            else left,
        )

        # Suspended emp + try SUBMIT leave (stronger than create draft)
        ok, created = call(
            client,
            "LeaveApplication.create",
            {
                "employee_id": "441e6779-ef91-44d0-ba9d-4ffba7b38622",
                "company_id": "5cbe5a55-af74-4363-a436-f5350593114c",
                "from_date": "2028-03-01",
                "to_date": "2028-03-01",
                "leave_type": "casual",
                "reason": "team13-bugprobe-r3b: submit while suspended",
            },
        )
        note(
            results,
            "suspended_create2",
            ok=ok,
            row={k: created.get(k) for k in ["id", "number", "status"]} if ok and isinstance(created, dict) else created,
        )
        if ok and isinstance(created, dict) and created.get("id"):
            ok_s, submitted = call(client, "LeaveApplication.submit", {"id": created["id"]})
            note(
                results,
                "suspended_submit",
                ok=ok_s,
                row={k: submitted.get(k) for k in ["id", "number", "status"]}
                if ok_s and isinstance(submitted, dict)
                else submitted,
            )
            # withdraw if pending
            if ok_s:
                call(client, "LeaveApplication.withdraw", {"id": created["id"]})
            else:
                call(client, "LeaveApplication.cancel.draft.cancelled", {"id": created["id"]})

        # Leave before joining — also try submit
        probe_emp = "baf152b3-e8ee-4da2-bee4-592637b9f94c"
        ok, emp = call(client, "Employee.get", {"id": probe_emp})
        note(
            results,
            "probe_emp",
            row={k: emp.get(k) for k in ["id", "email", "date_of_joining", "status", "gender"]}
            if ok and isinstance(emp, dict)
            else emp,
        )
        ok, created = call(
            client,
            "LeaveApplication.create",
            {
                "employee_id": probe_emp,
                "company_id": "5cbe5a55-af74-4363-a436-f5350593114c",
                "from_date": "2001-02-01",
                "to_date": "2001-02-03",
                "leave_type": "sick",
                "reason": "team13-bugprobe-r3b: submit before joining",
            },
        )
        if ok and isinstance(created, dict) and created.get("id"):
            ok_s, submitted = call(client, "LeaveApplication.submit", {"id": created["id"]})
            note(
                results,
                "before_join_submit",
                create={k: created.get(k) for k in ["id", "number", "from_date", "days"]},
                submit_ok=ok_s,
                submit={k: submitted.get(k) for k in ["id", "number", "status"]}
                if ok_s and isinstance(submitted, dict)
                else submitted,
            )
            if ok_s:
                call(client, "LeaveApplication.withdraw", {"id": created["id"]})
            else:
                call(client, "LeaveApplication.cancel.draft.cancelled", {"id": created["id"]})
        else:
            note(results, "before_join_create_fail", result=created)

        # HolidayList.create — discover required fields from schema
        tools = client.tools_list()
        for name in ("HolidayList.create", "LeaveBalance.create", "Attendance.create", "Employee.update"):
            t = next((x for x in tools if x.get("name") == name), None)
            schema = (t or {}).get("inputSchema") or (t or {}).get("input_schema")
            note(results, f"schema_{name}", schema=schema)

        # Retry LeaveBalance.create with string fiscal_year
        ok, r = call(
            client,
            "LeaveBalance.create",
            {
                "employee_id": probe_emp,
                "company_id": "5cbe5a55-af74-4363-a436-f5350593114c",
                "leave_type": "casual",
                "fiscal_year": "2099-00",
                "opening_balance": 9999,
            },
        )
        note(
            results,
            "balance_create_string_fy",
            ok=ok,
            result={k: r.get(k) for k in ["id", "fiscal_year", "opening_balance", "balance_days", "leave_type"]}
            if ok and isinstance(r, dict)
            else r,
        )

        # Attendance update: mutate punches to inverted after create
        ok, att = call(
            client,
            "Attendance.get",
            {"id": "9865af84-1346-484b-92aa-d482b77185b6"},
        )
        if ok and isinstance(att, dict):
            ok_u, upd = call(
                client,
                "Attendance.update",
                {
                    "id": att["id"],
                    "overtime_hours": -99,
                    "check_in": "99:99",
                },
            )
            note(
                results,
                "att_update_worse",
                ok=ok_u,
                result={k: upd.get(k) for k in ["id", "overtime_hours", "check_in", "check_out"]}
                if ok_u and isinstance(upd, dict)
                else upd,
            )

        # Employee.update: left with future exit? or active with exit_date set
        ok, r = call(
            client,
            "Employee.update",
            {
                "id": probe_emp,
                "exit_date": "2020-01-01",
            },
        )
        note(
            results,
            "emp_set_exit_while_active",
            ok=ok,
            result={k: r.get(k) for k in ["id", "email", "status", "exit_date"]}
            if ok and isinstance(r, dict)
            else r,
        )
        if ok and isinstance(r, dict) and r.get("exit_date"):
            # clear exit_date if possible
            ok2, r2 = call(client, "Employee.update", {"id": probe_emp, "exit_date": None})
            note(
                results,
                "emp_clear_exit",
                ok=ok2,
                result={k: r2.get(k) for k in ["id", "status", "exit_date"]}
                if ok2 and isinstance(r2, dict)
                else r2,
            )

    OUT.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print("WROTE", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
