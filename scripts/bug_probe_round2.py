"""Ad-hoc live probes for unfiled AgentSwitch HR bugs. Do not auto-file."""
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

from agent.mcp_client import McpClient  # noqa: E402

OUT = ROOT / "runs" / "bug_probe_round2.json"


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


def main() -> int:
    password = os.getenv("AS_PASSWORD", "")
    if not password:
        print("Set AS_PASSWORD in .env")
        return 2

    results: list[dict] = []

    def note(title: str, **kw):
        results.append({"title": title, **kw})
        print("===", title, "===")
        print(json.dumps(kw, indent=2, default=str)[:1800])

    with McpClient(
        base_url=os.getenv("AS_BASE_URL", "https://agentswitch.theschoolofai.in"),
        email=os.getenv("AS_EMAIL", "team13@theschoolofai.in"),
        password=password,
    ) as client:
        client.login()
        me = client.me()
        note("me", email=me.get("email"), roles=me.get("roles"))
        client.initialize()

        import httpx

        token = client._token
        r = httpx.get(
            f"{client.base_url}/api/bug-report/mine",
            headers={"Authorization": f"Bearer {token}"},
            timeout=60,
        )
        mine = r.json() if r.status_code == 200 else {"http": r.status_code, "text": r.text[:500]}
        if isinstance(mine, list):
            note(
                "filed_bugs",
                count=len(mine),
                descriptions=[
                    (m.get("description") or m.get("title") or str(m))[:160] for m in mine[:10]
                ],
            )
        else:
            note("filed_bugs", raw=mine)

        emps = client.list_all("Employee.list", {"limit": 50, "status": "active"}, max_pages=2)
        emp = next(
            (e for e in emps["items"] if "prakash" in (e.get("email") or "").lower()),
            emps["items"][0] if emps["items"] else None,
        )
        if not emp:
            print("No employees")
            return 1
        note("probe_employee", **slim(emp, ["id", "email", "status", "company_id"]))
        company_id = emp["company_id"]
        eid = emp["id"]

        # 1) Absurd multi-year leave
        try:
            created = unwrap(
                client.tools_call(
                    "LeaveApplication.create",
                    {
                        "employee_id": eid,
                        "company_id": company_id,
                        "from_date": "2027-01-01",
                        "to_date": "2040-12-31",
                        "leave_type": "casual",
                        "reason": "team13-bugprobe: absurd multi-year leave",
                        "half_day": 0,
                    },
                )
            )
            note(
                "extreme_leave_create",
                ok=True,
                created=slim(
                    created if isinstance(created, dict) and "id" in created else created.get("data", created),
                    ["id", "number", "days", "from_date", "to_date", "status", "half_day"],
                ),
            )
            row = created if isinstance(created, dict) and created.get("id") else (created or {}).get("data", {})
            lid = row.get("id") if isinstance(row, dict) else None
            if lid:
                try:
                    unwrap(client.tools_call("LeaveApplication.cancel.draft.cancelled", {"id": lid}))
                    note("extreme_leave_cleanup", cancelled=lid)
                except Exception as e:
                    note("extreme_leave_cleanup_fail", error=str(e)[:300], id=lid)
        except Exception as e:
            note("extreme_leave_create", ok=False, error=str(e)[:500])

        # 2) half_day=1 spanning multiple days
        try:
            created = unwrap(
                client.tools_call(
                    "LeaveApplication.create",
                    {
                        "employee_id": eid,
                        "company_id": company_id,
                        "from_date": "2027-03-01",
                        "to_date": "2027-03-05",
                        "leave_type": "sick",
                        "reason": "team13-bugprobe: half_day with multi-day",
                        "half_day": 1,
                    },
                )
            )
            row = created if isinstance(created, dict) and created.get("id") else (created or {}).get("data", created)
            note(
                "half_day_multiday",
                ok=True,
                created=slim(row, ["id", "number", "days", "half_day", "from_date", "to_date", "status"]),
            )
            lid = row.get("id") if isinstance(row, dict) else None
            if lid:
                try:
                    unwrap(client.tools_call("LeaveApplication.cancel.draft.cancelled", {"id": lid}))
                except Exception as e:
                    note("half_day_cleanup_fail", error=str(e)[:200], id=lid)
        except Exception as e:
            note("half_day_multiday", ok=False, error=str(e)[:500])

        # 3) Bogus leave_type
        try:
            created = unwrap(
                client.tools_call(
                    "LeaveApplication.create",
                    {
                        "employee_id": eid,
                        "company_id": company_id,
                        "from_date": "2027-04-01",
                        "to_date": "2027-04-01",
                        "leave_type": "banana_leave",
                        "reason": "team13-bugprobe: invalid leave_type",
                    },
                )
            )
            row = created if isinstance(created, dict) and created.get("id") else (created or {}).get("data", created)
            note("bogus_leave_type", ok=True, created=slim(row, ["id", "number", "leave_type", "status", "days"]))
            lid = row.get("id") if isinstance(row, dict) else None
            if lid:
                try:
                    unwrap(client.tools_call("LeaveApplication.cancel.draft.cancelled", {"id": lid}))
                except Exception:
                    pass
        except Exception as e:
            note("bogus_leave_type", ok=False, error=str(e)[:500])

        # 4) Overlapping leaves same employee
        try:
            a = unwrap(
                client.tools_call(
                    "LeaveApplication.create",
                    {
                        "employee_id": eid,
                        "company_id": company_id,
                        "from_date": "2027-05-10",
                        "to_date": "2027-05-12",
                        "leave_type": "casual",
                        "reason": "team13-bugprobe: overlap A",
                    },
                )
            )
            b = unwrap(
                client.tools_call(
                    "LeaveApplication.create",
                    {
                        "employee_id": eid,
                        "company_id": company_id,
                        "from_date": "2027-05-11",
                        "to_date": "2027-05-13",
                        "leave_type": "sick",
                        "reason": "team13-bugprobe: overlap B",
                    },
                )
            )
            ra = a if isinstance(a, dict) and a.get("id") else (a or {}).get("data", a)
            rb = b if isinstance(b, dict) and b.get("id") else (b or {}).get("data", b)
            note(
                "overlapping_leaves",
                ok=True,
                a=slim(ra, ["id", "number", "status", "from_date", "to_date"]),
                b=slim(rb, ["id", "number", "status", "from_date", "to_date"]),
            )
            for row in (ra, rb):
                lid = row.get("id") if isinstance(row, dict) else None
                if lid:
                    try:
                        unwrap(client.tools_call("LeaveApplication.cancel.draft.cancelled", {"id": lid}))
                    except Exception:
                        pass
        except Exception as e:
            note("overlapping_leaves", ok=False, error=str(e)[:500])

        # 5) Negative LeaveBalance update
        bals = client.list_all("LeaveBalance.list", {"limit": 50, "employee_id": eid}, max_pages=2)
        note(
            "existing_balances_for_emp",
            count=len(bals["items"]),
            samples=[
                slim(x, ["id", "leave_type", "balance_days", "used_days", "accrued_days"])
                for x in bals["items"][:5]
            ],
        )
        # Also count negative balances book-wide
        all_bals = client.list_all("LeaveBalance.list", {"limit": 100}, max_pages=10)
        neg = [x for x in all_bals["items"] if (x.get("balance_days") or 0) < 0]
        note(
            "negative_balances_bookwide",
            scanned=len(all_bals["items"]),
            negative_count=len(neg),
            samples=[
                slim(x, ["id", "employee_id", "leave_type", "balance_days", "used_days"])
                for x in neg[:8]
            ],
        )
        if bals["items"]:
            bal = bals["items"][0]
            before = bal.get("balance_days")
            try:
                upd = unwrap(
                    client.tools_call(
                        "LeaveBalance.update",
                        {"id": bal["id"], "balance_days": -99},
                    )
                )
                row = upd if isinstance(upd, dict) and "balance_days" in upd else (upd or {}).get("data", upd)
                note(
                    "negative_balance_update",
                    ok=True,
                    before=before,
                    after=row.get("balance_days") if isinstance(row, dict) else row,
                    id=bal["id"],
                )
                try:
                    unwrap(
                        client.tools_call(
                            "LeaveBalance.update",
                            {"id": bal["id"], "balance_days": before},
                        )
                    )
                except Exception as e:
                    note("balance_restore_fail", error=str(e)[:200])
            except Exception as e:
                note("negative_balance_update", ok=False, error=str(e)[:500])

        # 6) Duplicate attendance same day
        att_date = (date.today() - timedelta(days=3)).isoformat()
        existing = client.list_all(
            "Attendance.list", {"limit": 20, "date": att_date, "employee_id": eid}, max_pages=1
        )
        note(
            "att_existing",
            date=att_date,
            count=len(existing["items"]),
            ids=[x.get("id") for x in existing["items"][:3]],
        )
        try:
            a1 = unwrap(
                client.tools_call(
                    "Attendance.create",
                    {
                        "employee_id": eid,
                        "company_id": company_id,
                        "date": att_date,
                        "status": "present",
                        "check_in": "09:00",
                        "check_out": "18:00",
                    },
                )
            )
            r1 = a1 if isinstance(a1, dict) and a1.get("id") else (a1 or {}).get("data", a1)
            note("att_create_1", ok=True, created=slim(r1, ["id", "status", "date"]))
            a2 = unwrap(
                client.tools_call(
                    "Attendance.create",
                    {
                        "employee_id": eid,
                        "company_id": company_id,
                        "date": att_date,
                        "status": "absent",
                    },
                )
            )
            r2 = a2 if isinstance(a2, dict) and a2.get("id") else (a2 or {}).get("data", a2)
            note("att_duplicate_create", ok=True, created=slim(r2, ["id", "status", "date", "employee_id"]))
        except Exception as e:
            note("att_duplicate", ok=False, error=str(e)[:500])

        # 7) Leave for left employee
        lefts = client.list_all("Employee.list", {"limit": 20, "status": "left"}, max_pages=1)
        if lefts["items"]:
            left = lefts["items"][0]
            try:
                c = unwrap(
                    client.tools_call(
                        "LeaveApplication.create",
                        {
                            "employee_id": left["id"],
                            "company_id": left.get("company_id") or company_id,
                            "from_date": "2027-06-01",
                            "to_date": "2027-06-01",
                            "leave_type": "casual",
                            "reason": "team13-bugprobe: leave for left employee",
                        },
                    )
                )
                row = c if isinstance(c, dict) and c.get("id") else (c or {}).get("data", c)
                note(
                    "leave_for_left_employee",
                    ok=True,
                    emp=left.get("email"),
                    created=slim(row, ["id", "number", "status"]),
                )
                lid = row.get("id") if isinstance(row, dict) else None
                if lid:
                    try:
                        unwrap(client.tools_call("LeaveApplication.cancel.draft.cancelled", {"id": lid}))
                    except Exception:
                        pass
            except Exception as e:
                note("leave_for_left_employee", ok=False, error=str(e)[:400], emp=left.get("email"))
        else:
            note("leave_for_left_employee", ok=None, reason="no left employees")

        # 8) days override mismatch
        try:
            c = unwrap(
                client.tools_call(
                    "LeaveApplication.create",
                    {
                        "employee_id": eid,
                        "company_id": company_id,
                        "from_date": "2027-07-01",
                        "to_date": "2027-07-03",
                        "leave_type": "casual",
                        "reason": "team13-bugprobe: days override",
                        "days": 99,
                    },
                )
            )
            row = c if isinstance(c, dict) and c.get("id") else (c or {}).get("data", c)
            note(
                "days_override",
                ok=True,
                created=slim(row, ["id", "days", "from_date", "to_date", "number"]),
            )
            lid = row.get("id") if isinstance(row, dict) else None
            if lid:
                try:
                    unwrap(client.tools_call("LeaveApplication.cancel.draft.cancelled", {"id": lid}))
                except Exception:
                    pass
        except Exception as e:
            note("days_override", ok=False, error=str(e)[:400])

        # 9) negative lop_hours
        try:
            d = (date.today() - timedelta(days=4)).isoformat()
            c = unwrap(
                client.tools_call(
                    "Attendance.create",
                    {
                        "employee_id": eid,
                        "company_id": company_id,
                        "date": d,
                        "status": "present",
                        "check_in": "09:00",
                        "check_out": "17:00",
                        "is_lop": True,
                        "lop_hours": -5,
                    },
                )
            )
            row = c if isinstance(c, dict) and c.get("id") else (c or {}).get("data", c)
            note(
                "neg_lop_hours",
                ok=True,
                created=slim(
                    row, ["id", "date", "status", "is_lop", "lop_hours", "check_in", "check_out"]
                ),
            )
        except Exception as e:
            note("neg_lop_hours", ok=False, error=str(e)[:400])

        # 10) Existing extreme leave already on book
        extreme = [
            x
            for x in client.list_all("LeaveApplication.list", {"limit": 50}, max_pages=3)["items"]
            if (x.get("days") or 0) > 100
        ]
        note(
            "existing_extreme_leaves",
            count=len(extreme),
            samples=[
                slim(x, ["number", "id", "days", "from_date", "to_date", "half_day", "leave_type", "status", "reason"])
                for x in extreme[:5]
            ],
        )

        # 11) leave_type_id null prevalence
        leaves = client.list_all("LeaveApplication.list", {"limit": 100}, max_pages=2)
        null_type_id = sum(1 for x in leaves["items"] if x.get("leave_type_id") is None and x.get("leave_type"))
        note(
            "leave_type_id_null",
            scanned=len(leaves["items"]),
            leave_type_set_but_id_null=null_type_id,
        )

        # 12) Submit leave when balance is zero/negative (if we can find such emp)
        if neg:
            sample = neg[0]
            try:
                c = unwrap(
                    client.tools_call(
                        "LeaveApplication.create",
                        {
                            "employee_id": sample["employee_id"],
                            "company_id": company_id,
                            "from_date": "2027-08-10",
                            "to_date": "2027-08-10",
                            "leave_type": sample.get("leave_type") or "casual",
                            "reason": "team13-bugprobe: submit with negative balance",
                        },
                    )
                )
                row = c if isinstance(c, dict) and c.get("id") else (c or {}).get("data", c)
                lid = row.get("id") if isinstance(row, dict) else None
                submit_res = None
                if lid:
                    try:
                        submit_res = unwrap(client.tools_call("LeaveApplication.submit", {"id": lid}))
                    except Exception as e:
                        submit_res = {"error": str(e)[:400]}
                    # cleanup: cancel if still draft, withdraw if pending
                    for tool in (
                        "LeaveApplication.cancel.draft.cancelled",
                        "LeaveApplication.withdraw",
                    ):
                        try:
                            unwrap(client.tools_call(tool, {"id": lid}))
                            break
                        except Exception:
                            continue
                note(
                    "submit_with_negative_balance",
                    ok=True,
                    balance=slim(sample, ["id", "employee_id", "leave_type", "balance_days"]),
                    created=slim(row, ["id", "number", "status", "days"]),
                    submit=submit_res if not isinstance(submit_res, dict) else slim(submit_res, ["id", "status", "number"]) or submit_res,
                )
            except Exception as e:
                note("submit_with_negative_balance", ok=False, error=str(e)[:400])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print("WROTE", OUT, "n=", len(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
