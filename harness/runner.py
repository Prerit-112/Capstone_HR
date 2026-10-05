"""Harness runner: run → write journal to disk → then verify → then score."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.catalogue import Catalogue
from agent.loop import HrAgent
from agent.mcp_client import McpClient
from harness.verify import score_task

TASKS_DIR = Path(__file__).resolve().parent / "tasks"
RUNS_DIR = ROOT / "runs"
BUG_DIR = RUNS_DIR / "bug_candidates"


def load_task(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def list_tasks() -> list[Path]:
    return sorted(TASKS_DIR.glob("*.json"))


def build_client() -> McpClient:
    load_dotenv(ROOT / ".env")
    password = os.getenv("AS_PASSWORD", "")
    if not password:
        raise SystemExit("Set AS_PASSWORD in .env")
    return McpClient(
        base_url=os.getenv("AS_BASE_URL", "https://agentswitch.theschoolofai.in"),
        email=os.getenv("AS_EMAIL", "team13@theschoolofai.in"),
        password=password,
    )


def maybe_bug_candidate(journal, score: dict) -> None:
    """Heuristic: false_success or tool errors that look like platform bugs."""
    reasons = []
    if score.get("outcome") == "false_success":
        reasons.append("false_success")
    for s in journal.steps:
        if s.kind == "tool" and not s.ok and "tool_not_available" in (s.detail or ""):
            if "approve" in s.target.lower():
                reasons.append(f"approve_missing:{s.target}")
    if not reasons:
        return
    BUG_DIR.mkdir(parents=True, exist_ok=True)
    path = BUG_DIR / f"{journal.task_id}_{int(time.time())}.json"
    path.write_text(
        json.dumps(
            {
                "reasons": reasons,
                "task_id": journal.task_id,
                "score": score,
                "steps": [s.__dict__ for s in journal.steps],
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )


def run_one(task: dict, *, repeats: int = 1) -> list[dict]:
    client = build_client()
    results = []
    try:
        client.login()
        client.initialize()
        cat = Catalogue.from_tools_list(client.tools_list())
        from agent.llm import resolve_api_key

        if not resolve_api_key():
            raise SystemExit("Set GEMINI_API_KEY in .env")

        for r in range(repeats):
            if task.get("adversary") == "pre_write_conflict":
                from harness.adversary import ConflictHrAgent, restore_attendance

                agent = ConflictHrAgent(client, cat)
            else:
                agent = HrAgent(client, cat)
            client.clear_wire_log()
            agent._seen.clear()
            journal = agent.run(
                task["prompt"],
                task_id=task["id"],
                as_of=task.get("as_of") or date.today().isoformat(),
                allow_writes=bool(task.get("allow_writes")),
                write_allowlist=set(task["write_allowlist"]) if task.get("write_allowlist") else None,
            )

            # Disk BEFORE score (brief §8).
            run_dir = RUNS_DIR / f"{task['id']}__r{r}__{int(journal.started_at)}"
            run_dir.mkdir(parents=True, exist_ok=True)
            journal_path = run_dir / "journal.json"
            journal.save(journal_path)
            (run_dir / "task.json").write_text(json.dumps(task, indent=2), encoding="utf-8")

            score = score_task(task, journal, client)
            (run_dir / "score.json").write_text(json.dumps(score, indent=2, default=str), encoding="utf-8")
            maybe_bug_candidate(journal, score)
            results.append({"run_dir": str(run_dir), "score": score, "ended": journal.ended})
            print(json.dumps({"repeat": r, "outcome": score.get("outcome"), "ended": journal.ended, "run_dir": str(run_dir)}, indent=2), flush=True)

            restore = getattr(agent, "restore", None)
            if restore:
                from harness.adversary import restore_attendance

                try:
                    restore_attendance(client, restore)
                except Exception as e:
                    print(f"restore_attendance failed: {e}")
    finally:
        client.close()
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Team 13 HR harness")
    parser.add_argument("--task", default=None, help="Task id (filename without .json)")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args(argv)

    load_dotenv(ROOT / ".env")
    RUNS_DIR.mkdir(exist_ok=True)

    if args.list:
        for p in list_tasks():
            t = load_task(p)
            print(f"{t.get('id')}\t{t.get('verifier')}\t{t.get('family')}")
        return 0

    tasks = []
    if args.all:
        tasks = [load_task(p) for p in list_tasks()]
    elif args.task:
        path = TASKS_DIR / f"{args.task}.json"
        if not path.exists():
            raise SystemExit(f"missing task: {path}")
        tasks = [load_task(path)]
    else:
        raise SystemExit("Pass --task ID or --all (or --list)")

    all_results = []
    for t in tasks:
        print(f"\n=== {t['id']} ===")
        all_results.extend(run_one(t, repeats=args.repeats))

    summary_path = RUNS_DIR / f"summary_{int(time.time())}.json"
    summary_path.write_text(json.dumps(all_results, indent=2, default=str), encoding="utf-8")
    print(f"\nSummary: {summary_path}")
    _print_scoreboard(all_results)
    bad = [r for r in all_results if (r.get("score") or {}).get("outcome") == "false_success"]
    return 1 if bad else 0


def _print_scoreboard(results: list[dict]) -> None:
    print("\n=== scoreboard ===")
    for r in results:
        score = r.get("score") or {}
        print(f"{score.get('task_id')}\t{score.get('outcome')}\t{score.get('verifier')}")
    from collections import Counter

    c = Counter((r.get("score") or {}).get("outcome") for r in results)
    print(dict(c))


if __name__ == "__main__":
    raise SystemExit(main())
