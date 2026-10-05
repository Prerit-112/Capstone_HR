"""CLI: one-shot HR agent against live AgentSwitch MCP."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Allow `python -m agent.cli` from repo root.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.catalogue import Catalogue
from agent.loop import HrAgent
from agent.mcp_client import McpClient


def build_client() -> McpClient:
    load_dotenv(ROOT / ".env")
    base = os.getenv("AS_BASE_URL", "https://agentswitch.theschoolofai.in")
    email = os.getenv("AS_EMAIL", "team13@theschoolofai.in")
    password = os.getenv("AS_PASSWORD", "")
    if not password:
        print("Set AS_PASSWORD in .env (see .env.example).", file=sys.stderr)
        sys.exit(2)
    return McpClient(base_url=base, email=email, password=password)


def format_answer(answer: dict[str, Any] | None, *, ended: str, error: str) -> str:
    """Human-readable report — what a user expects to see."""
    lines: list[str] = []
    if error:
        lines.append(f"Run failed ({ended}): {error}")
        return "\n".join(lines)
    if not answer:
        lines.append(f"No structured answer (ended={ended}).")
        return "\n".join(lines)

    as_of = answer.get("as_of") or "?"
    findings = answer.get("findings") or {}
    refused = answer.get("refused") or {}
    uncertain = answer.get("uncertain") or []

    lines.append(f"As of {as_of}")
    lines.append("")

    if refused.get("is_refusal"):
        lines.append("REFUSED")
        lines.append(f"  Why: {refused.get('why') or '(not stated)'}")
        lines.append(f"  Escalate to: {refused.get('escalate_to') or '(not stated)'}")
        lines.append("")

    leave = findings.get("on_leave") or []
    lines.append(f"On leave next week: {len(leave)}")
    if not leave:
        lines.append("  (none found)")
    for row in leave:
        name = row.get("name") or row.get("employee_id") or "?"
        lines.append(
            f"  - {name}: {row.get('from_date')} → {row.get('to_date')} "
            f"[{row.get('status')}] leave={row.get('leave_id')}"
        )

    lines.append("")
    flags = findings.get("attendance_flags") or []
    lines.append(f"Attendance that does not look right: {len(flags)}")
    if not flags:
        lines.append("  (none found)")
    for row in flags:
        lines.append(
            f"  - {row.get('date')}: {row.get('reason')} "
            f"(employee={row.get('employee_id')}, attendance={row.get('attendance_id')})"
        )

    lines.append("")
    due = findings.get("confirmation_due") or []
    lines.append(f"Due for confirmation: {len(due)}")
    if not due:
        lines.append("  (none found)")
    for row in due:
        name = row.get("name") or row.get("employee_id") or "?"
        lines.append(f"  - {name}: probation_end_date={row.get('probation_end_date')}")

    bals = findings.get("leave_balances") or []
    if bals:
        lines.append("")
        lines.append(f"Leave balances: {len(bals)}")
        for row in bals:
            lines.append(
                f"  - {row.get('leave_type')}: balance_days={row.get('balance_days')} "
                f"entitlement={row.get('annual_entitlement')} id={row.get('leave_balance_id')}"
            )

    week = findings.get("holiday_week")
    hols = findings.get("holidays") or []
    if week or hols:
        lines.append("")
        lines.append(f"Holiday week: {week}")
        for h in hols:
            lines.append(f"  - {h}")

    if uncertain:
        lines.append("")
        lines.append("Notes / uncertain:")
        for u in uncertain:
            lines.append(f"  - {u}")

    actions = answer.get("actions_taken") or []
    if actions:
        lines.append("")
        lines.append("Actions taken:")
        for a in actions:
            lines.append(f"  - {a}")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Team 13 HR agent (AgentSwitch MCP)")
    parser.add_argument("prompt", nargs="?", help="Question for the agent")
    parser.add_argument("--as-of", default=None, help="YYYY-MM-DD (default: today)")
    parser.add_argument("--allow-writes", action="store_true")
    parser.add_argument("--task-id", default="cli")
    parser.add_argument("--save", default=None, help="Path to save run journal JSON")
    parser.add_argument("--json", action="store_true", help="Also print raw JSON envelope")
    parser.add_argument("--whoami", action="store_true", help="Print /api/auth/me and exit")
    parser.add_argument("--list-tools", action="store_true", help="Print HR allowlisted tools and exit")
    args = parser.parse_args(argv)

    load_dotenv(ROOT / ".env")
    client = build_client()
    try:
        client.login()
        if args.whoami:
            print(json.dumps(client.me(), indent=2))
            return 0

        init = client.initialize()
        tools = client.tools_list()
        cat = Catalogue.from_tools_list(tools)

        if args.list_tools:
            allowed = cat.allowed_for_task(allow_writes=args.allow_writes)
            print(
                json.dumps(
                    {
                        "server": init.get("serverInfo"),
                        "count": len(allowed),
                        "tools": [t.name for t in allowed],
                    },
                    indent=2,
                )
            )
            return 0

        if not args.prompt:
            parser.error("prompt is required unless --whoami / --list-tools")

        from agent.llm import resolve_api_key

        if not resolve_api_key():
            print("Set GEMINI_API_KEY in .env", file=sys.stderr)
            return 2

        agent = HrAgent(client, cat)
        journal = agent.run(
            args.prompt,
            task_id=args.task_id,
            as_of=args.as_of or date.today().isoformat(),
            allow_writes=args.allow_writes
            or os.getenv("AGENT_ALLOW_WRITES", "").lower() in {"1", "true", "yes"},
        )

        print(format_answer(journal.final_answer, ended=journal.ended, error=journal.error))
        print()
        print(
            f"(ended={journal.ended}, model={journal.model}, "
            f"tools={journal.tool_calls}, {journal.seconds:.0f}s)"
        )

        if args.json:
            out = {
                "ended": journal.ended,
                "claimed_success": journal.claimed_success,
                "final_answer": journal.final_answer,
                "steps": len(journal.steps),
                "tool_calls": journal.tool_calls,
                "calls": journal.calls,
                "seconds": journal.seconds,
                "error": journal.error,
            }
            print()
            print(json.dumps(out, indent=2, default=str))

        save_path = args.save
        if save_path is None:
            runs = ROOT / "runs"
            runs.mkdir(exist_ok=True)
            save_path = str(runs / f"{journal.task_id}_{int(journal.started_at)}.json")
        journal.save(Path(save_path))
        print(f"\nSaved journal: {save_path}", file=sys.stderr)
        return 0 if journal.ended in {"done", "refused"} else 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
