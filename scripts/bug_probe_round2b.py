"""Follow-up probes after schema discovery."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from agent.mcp_client import McpClient  # noqa: E402

OUT = ROOT / "runs" / "bug_probe_round2b.json"


def main() -> int:
    results: list[dict] = []

    def note(title: str, **kw):
        results.append({"title": title, **kw})
        print("===", title, "===")
        print(json.dumps(kw, indent=2, default=str)[:2000])

    with McpClient(
        base_url=os.getenv("AS_BASE_URL", "https://agentswitch.theschoolofai.in"),
        email=os.getenv("AS_EMAIL", "team13@theschoolofai.in"),
        password=os.getenv("AS_PASSWORD", ""),
    ) as client:
        client.login()
        client.initialize()

        emp_id = "baf152b3-e8ee-4da2-bee4-592637b9f94c"
        company_id = "5cbe5a55-af74-4363-a436-f5350593114c"

        lefts = client.list_all("Employee.list", {"limit": 5, "status": "left"}, max_pages=1)
        left = lefts["items"][0]
        note(
            "left_employee",
            **{
                k: left.get(k)
                for k in [
                    "id",
                    "email",
                    "status",
                    "first_name",
                    "last_name",
                    "date_of_joining",
                    "relieving_date",
                    "probation_end_date",
                ]
            },
        )
        left_full = client.tools_call("Employee.get", {"id": left["id"]})
        note(
            "left_employee_get",
            keys=sorted(left_full.keys()) if isinstance(left_full, dict) else type(left_full).__name__,
            status=left_full.get("status"),
            email=left_full.get("email"),
            relieving_date=left_full.get("relieving_date"),
            exit_date=left_full.get("exit_date"),
            last_working_day=left_full.get("last_working_day"),
        )

        # Confirm leave for left still exists / recreate if cleaned
        leaves_left = client.list_all(
            "LeaveApplication.list",
            {"limit": 20, "employee_id": left["id"]},
            max_pages=1,
        )
        note(
            "leaves_for_left_emp",
            count=len(leaves_left["items"]),
            samples=[
                {
                    k: x.get(k)
                    for k in ["number", "id", "status", "from_date", "to_date", "reason"]
                }
                for x in leaves_left["items"][:5]
            ],
        )

        # Multi-year leave (boolean half_day omitted)
        for label, args in [
            (
                "multi_year",
                {
                    "employee_id": emp_id,
                    "from_date": "2027-01-01",
                    "to_date": "2040-12-31",
                    "leave_type": "casual",
                    "reason": "team13-bugprobe: multi-year",
                },
            ),
            (
                "half_multi",
                {
                    "employee_id": emp_id,
                    "from_date": "2027-03-01",
                    "to_date": "2027-03-05",
                    "leave_type": "sick",
                    "reason": "team13-bugprobe: half multi",
                    "half_day": True,
                },
            ),
            (
                "past_year",
                {
                    "employee_id": emp_id,
                    "from_date": "2010-01-01",
                    "to_date": "2010-12-31",
                    "leave_type": "casual",
                    "reason": "team13-bugprobe: past calendar year",
                },
            ),
            (
                "maternity_male_long",
                {
                    "employee_id": emp_id,
                    "from_date": "2027-09-01",
                    "to_date": "2027-12-31",
                    "leave_type": "maternity",
                    "reason": "team13-bugprobe: maternity on male probe emp",
                },
            ),
        ]:
            try:
                r = client.tools_call("LeaveApplication.create", args)
                note(
                    label,
                    ok=True,
                    created={
                        k: r.get(k)
                        for k in [
                            "id",
                            "number",
                            "days",
                            "half_day",
                            "status",
                            "leave_type",
                            "from_date",
                            "to_date",
                        ]
                    },
                )
                try:
                    client.tools_call("LeaveApplication.cancel.draft.cancelled", {"id": r["id"]})
                    note(f"{label}_cleanup", cancelled=r["id"])
                except Exception as e:
                    note(f"{label}_cleanup_fail", error=str(e)[:200], id=r.get("id"))
            except Exception as e:
                note(label, ok=False, error=str(e)[:400])

        # Balance stats + LeaveType entitlements
        bals = client.list_all("LeaveBalance.list", {"limit": 100}, max_pages=20)
        items = bals["items"]
        note(
            "balance_stats",
            total=len(items),
            book_total=bals["total"],
            neg=sum(1 for x in items if (x.get("balance_days") or 0) < 0),
            zero=sum(1 for x in items if (x.get("balance_days") or 0) == 0),
            pos=sum(1 for x in items if (x.get("balance_days") or 0) > 0),
            accrued_pos=sum(1 for x in items if (x.get("accrued_days") or 0) > 0),
            opening_pos=sum(1 for x in items if (x.get("opening_balance") or 0) > 0),
            sample_fields={
                k: items[0].get(k)
                for k in [
                    "opening_balance",
                    "accrued_days",
                    "carried_forward",
                    "used_days",
                    "encashed_days",
                    "balance_days",
                    "leave_type",
                    "fiscal_year",
                ]
            }
            if items
            else None,
        )

        ltypes = client.list_all("LeaveType.list", {"limit": 50}, max_pages=1)
        note(
            "leave_types",
            count=len(ltypes["items"]),
            rows=[
                {
                    k: x.get(k)
                    for k in [
                        "id",
                        "name",
                        "code",
                        "annual_entitlement",
                        "accrual_frequency",
                        "accrual_per_period",
                        "is_active",
                    ]
                }
                for x in ltypes["items"][:15]
            ],
        )

        # LeaveBalance.update cannot set balance_days (not in schema) — try used_days bump
        if items:
            bal = items[0]
            try:
                u = client.tools_call(
                    "LeaveBalance.update",
                    {"id": bal["id"], "used_days": float(bal.get("used_days") or 0) + 10},
                )
                note(
                    "balance_used_bump",
                    ok=True,
                    before={
                        k: bal.get(k)
                        for k in ["used_days", "balance_days", "accrued_days", "opening_balance"]
                    },
                    after={
                        k: u.get(k)
                        for k in ["used_days", "balance_days", "accrued_days", "opening_balance"]
                    },
                )
                # restore
                client.tools_call(
                    "LeaveBalance.update",
                    {"id": bal["id"], "used_days": bal.get("used_days")},
                )
            except Exception as e:
                note("balance_used_bump", ok=False, error=str(e)[:300])

        # Submit path when balance negative — recreate if prior withdraw
        sample = next((x for x in items if (x.get("balance_days") or 0) < 0), None)
        if sample:
            try:
                created = client.tools_call(
                    "LeaveApplication.create",
                    {
                        "employee_id": sample["employee_id"],
                        "from_date": "2027-08-15",
                        "to_date": "2027-08-15",
                        "leave_type": sample.get("leave_type") or "casual",
                        "reason": "team13-bugprobe: neg balance submit 2",
                    },
                )
                submitted = client.tools_call("LeaveApplication.submit", {"id": created["id"]})
                note(
                    "submit_neg_balance_repro",
                    ok=True,
                    balance={
                        k: sample.get(k)
                        for k in ["id", "employee_id", "leave_type", "balance_days", "used_days"]
                    },
                    leave={
                        k: submitted.get(k)
                        for k in ["id", "number", "status", "days", "leave_type"]
                    },
                )
                # leave artefact for UI — withdraw to be polite unless we want to keep
                try:
                    client.tools_call("LeaveApplication.withdraw", {"id": created["id"]})
                    note("submit_neg_cleanup", withdrawn=created["id"])
                except Exception as e:
                    note("submit_neg_cleanup_fail", error=str(e)[:200])
            except Exception as e:
                note("submit_neg_balance_repro", ok=False, error=str(e)[:400])

        # Cleanup leftover from round2
        for lid, tool in [
            ("9f659ebd-cc28-4284-8333-aa53efabfc4f", "LeaveApplication.cancel.draft.cancelled"),
            ("2abd592b-7c84-4bc6-a5bc-33ab586d327a", "LeaveApplication.cancel.draft.cancelled"),
            ("31a1e169-0321-4973-ba12-6daeb83226e5", "LeaveApplication.withdraw"),
        ]:
            try:
                client.tools_call(tool, {"id": lid})
                note("cleanup", id=lid, tool=tool, ok=True)
            except Exception as e:
                note("cleanup", id=lid, tool=tool, ok=False, error=str(e)[:200])

        # Existing extreme leave details
        extreme = client.tools_call(
            "LeaveApplication.get", {"id": "76bda086-6e9f-49c0-856a-f3d6fa131d6d"}
        )
        note(
            "existing_extreme_get",
            **{
                k: extreme.get(k)
                for k in [
                    "number",
                    "days",
                    "half_day",
                    "from_date",
                    "to_date",
                    "leave_type",
                    "status",
                    "employee_id",
                    "_employee_id_display",
                    "reason",
                ]
            },
        )

        # Attendance create on holiday?
        hol = client.list_all("HolidayList.list", {"limit": 20}, max_pages=1)
        note(
            "holidays",
            count=len(hol["items"]),
            sample=[
                {k: h.get(k) for k in h.keys() if not str(k).startswith("_")}
                for h in hol["items"][:3]
            ],
        )

    OUT.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print("WROTE", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
