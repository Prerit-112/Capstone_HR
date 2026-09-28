"""Capture live MCP list pages into fixtures/ (no LLM)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from agent.mcp_client import McpClient

OUT = ROOT / "fixtures" / "live"


def main() -> int:
    password = os.getenv("AS_PASSWORD", "")
    if not password:
        print("Set AS_PASSWORD in .env")
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    with McpClient(
        base_url=os.getenv("AS_BASE_URL", "https://agentswitch.theschoolofai.in"),
        email=os.getenv("AS_EMAIL", "team13@theschoolofai.in"),
        password=password,
    ) as client:
        client.login()
        me = client.me()
        (OUT / "me.json").write_text(json.dumps(me, indent=2), encoding="utf-8")
        client.initialize()
        tools = client.tools_list()
        names = sorted(t["name"] for t in tools)
        (OUT / "tool_names.json").write_text(json.dumps(names, indent=2), encoding="utf-8")
        for tool, args in [
            ("LeaveApplication.list", {"limit": 100}),
            ("Employee.list", {"limit": 100, "status": "active"}),
            ("LeaveBalance.list", {"limit": 100}),
            ("HolidayList.list", {"limit": 20}),
        ]:
            page = client.list_all(tool, args, max_pages=20)
            safe = tool.replace(".", "_")
            (OUT / f"{safe}.json").write_text(json.dumps(page, indent=2, default=str), encoding="utf-8")
            print(f"{tool}: items={len(page['items'])} total={page['total']} pages={page['pages']}")

        # Attendance is huge — capture a few recent dates only.
        from datetime import date, timedelta

        att_items = []
        today = date.today()
        for i in range(7):
            d = (today - timedelta(days=i)).isoformat()
            page = client.list_all("Attendance.list", {"limit": 100, "date": d}, max_pages=5)
            att_items.extend(page["items"])
            print(f"Attendance.list date={d}: {len(page['items'])}")
        (OUT / "Attendance_list.json").write_text(
            json.dumps({"items": att_items, "total": len(att_items), "pages": 7, "partial_error": None}, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
