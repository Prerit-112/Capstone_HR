"""Locally reproduce late-suite LLM pressure that caused platform not_evaluable.

Uses a flaky OpenAI-compatible wrapper (429 twice, then real Gemini) so retries
and recovery paths are exercised against the live MCP book.

Usage:
  .venv\\Scripts\\python.exe scripts/simulate_platform_llm_pressure.py
  .venv\\Scripts\\python.exe scripts/simulate_platform_llm_pressure.py --task write_conflict_abort
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

# Simulate platform: single model, hard retries, small inter-task pause.
os.environ.setdefault("LLM_RETRIES_PER_MODEL", "5")
os.environ.setdefault("LLM_BACKOFF_SECONDS", "1")
os.environ.setdefault("LLM_INTER_TASK_SLEEP", "1")


class PressureClient:
    """Proxy that injects transient 429s on the first N chat calls."""

    def __init__(self, inner, *, fail_first: int = 2):
        self._inner = inner
        self._fail_first = fail_first
        self._calls = 0
        self.chat = self

    @property
    def completions(self):
        return self

    def create(self, **kwargs):
        self._calls += 1
        if self._calls <= self._fail_first:

            class RateLimitError(Exception):
                pass

            raise RateLimitError(f"Error code: 429 simulated pressure call={self._calls}")
        return self._inner.chat.completions.create(**kwargs)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--task",
        action="append",
        default=None,
        help="Task id (repeatable). Default: the three platform-failing tasks.",
    )
    parser.add_argument("--fail-first", type=int, default=2, help="How many initial 429s per agent")
    args = parser.parse_args()
    tasks = args.task or ["robust_as_of_window", "write_conflict_abort", "write_fix_attendance"]

    from agent.llm import build_llm_client
    from agent.loop import HrAgent
    from harness.adversary import ConflictHrAgent
    from harness.runner import build_client, load_task, TASKS_DIR, RUNS_DIR
    from harness.verify import score_task
    import json
    from datetime import date

    real = build_llm_client()
    mcp = build_client()
    mcp.ensure_token()
    mcp.initialize()
    from agent.catalogue import Catalogue

    cat = Catalogue.from_tools_list(mcp.tools_list())
    RUNS_DIR.mkdir(exist_ok=True)

    outcomes = []
    for tid in tasks:
        task = load_task(TASKS_DIR / f"{tid}.json")
        pressure = PressureClient(real, fail_first=args.fail_first)
        if task.get("adversary") == "pre_write_conflict":
            agent = ConflictHrAgent(mcp, cat, openai_client=pressure)
        else:
            agent = HrAgent(mcp, cat, openai_client=pressure)
        mcp.clear_wire_log()
        agent._seen.clear()
        print(f"\n=== pressure:{tid} (fail_first={args.fail_first}) ===", flush=True)
        journal = agent.run(
            task["prompt"],
            task_id=task["id"],
            as_of=task.get("as_of") or date.today().isoformat(),
            allow_writes=bool(task.get("allow_writes")),
            write_allowlist=set(task["write_allowlist"]) if task.get("write_allowlist") else None,
        )
        run_dir = RUNS_DIR / f"{tid}__pressure__{int(time.time())}"
        run_dir.mkdir(parents=True, exist_ok=True)
        journal.save(run_dir / "journal.json")
        score = score_task(task, journal, mcp)
        (run_dir / "score.json").write_text(json.dumps(score, indent=2, default=str), encoding="utf-8")
        print(
            json.dumps(
                {
                    "task": tid,
                    "outcome": score.get("outcome"),
                    "ended": journal.ended,
                    "llm_calls_through_proxy": pressure._calls,
                    "run_dir": str(run_dir),
                },
                indent=2,
            ),
            flush=True,
        )
        outcomes.append(score.get("outcome"))
        restore = getattr(agent, "restore", None)
        if restore:
            from harness.adversary import restore_attendance

            try:
                restore_attendance(mcp, restore)
            except Exception as e:
                print(f"restore failed: {e}", flush=True)

    mcp.close()
    bad = [o for o in outcomes if o in {"not_evaluable", "false_success", "fail"}]
    print("\npressure outcomes:", outcomes)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
