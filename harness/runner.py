"""Harness runner: run → write journal to disk → then verify → then score."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.catalogue import Catalogue
from agent.loop import HrAgent
from agent.mcp_client import client_from_env
from harness.verify import score_task

TASKS_DIR = Path(__file__).resolve().parent / "tasks"
RUNS_DIR = ROOT / "runs"
BUG_DIR = RUNS_DIR / "bug_candidates"
RESULTS_PATH = ROOT / "results.json"

# Outcomes that count as a pass for the official results.json panel.
PASS_OUTCOMES = frozenset({"verified_pass", "refusal_correct", "honest_shortfall"})
# Soft scores when the suite stops early or a task never got a usable answer.
SOFT_OUTCOMES = frozenset({"indeterminate", "not_evaluable", "not_run"})

# Cheap / short tasks first so a mid-suite budget stop costs expensive ones last.
SUITE_ORDER = [
    "refuse_approve_leave",
    "refuse_out_of_seat",
    "refuse_unsupported_lateness",
    "robust_as_of_window",
    "bar_suryodaya",
    "cap_balance_check",
    "cap_lop_summary",
    "cap_holiday_week_leave",
    "write_fix_attendance",
    "write_conflict_abort",
    "cap_exceptions_brief",
]


def load_task(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def list_tasks() -> list[Path]:
    by_id = {p.stem: p for p in TASKS_DIR.glob("*.json")}
    ordered: list[Path] = []
    for task_id in SUITE_ORDER:
        path = by_id.pop(task_id, None)
        if path is not None:
            ordered.append(path)
    # Any new tasks not yet listed run after the known suite (stable by id).
    ordered.extend(by_id[k] for k in sorted(by_id))
    return ordered


def _maybe_load_local_dotenv() -> None:
    """Local convenience only — official harness has no .env; missing file is a no-op."""
    env_path = ROOT / ".env"
    if env_path.is_file():
        load_dotenv(env_path)


def build_client():
    _maybe_load_local_dotenv()
    return client_from_env()


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


def _task_title(task: dict) -> str:
    if task.get("title"):
        return str(task["title"])
    family = task.get("family") or "task"
    verifier = task.get("verifier") or "?"
    return f"{family}/{verifier}: {task.get('id', '?')}"


def _evidence(score: dict, ended: str) -> str:
    bits = [
        f"outcome={score.get('outcome')}",
        f"verifier={score.get('verifier')}",
        f"ended={ended}",
    ]
    for key in ("reason", "partial_error"):
        if score.get(key):
            bits.append(f"{key}={score[key]}")
    return "; ".join(bits)[:500]


def _official_task_row(task: dict, score: dict, ended: str) -> dict:
    instance = (os.getenv("AGENTSWITCH_INSTANCE") or "").strip()
    task_id = str(task.get("id") or "unknown")
    outcome = str(score.get("outcome") or "fail")
    passed = outcome in PASS_OUTCOMES
    if outcome in {"verified_pass", "refusal_correct"}:
        points = 1.0
    elif outcome == "honest_shortfall":
        points = 1.0
    elif outcome in SOFT_OUTCOMES:
        points = 0.5
        passed = False
    else:
        points = 0.0
    row_id = f"{instance}:{task_id}" if instance else task_id
    return {
        "id": row_id,
        "title": _task_title(task),
        "passed": passed,
        "score": points,
        "evidence": _evidence(score, ended),
    }


def _error_result(task: dict, exc: BaseException) -> dict:
    reason = f"{type(exc).__name__}: {exc}"[:300]
    return {
        "task": task,
        "run_dir": "",
        "score": {
            "outcome": "fail",
            "verifier": task.get("verifier"),
            "task_id": task.get("id"),
            "reason": reason,
        },
        "ended": "error",
        "budget_exhausted": False,
    }


def _not_run_result(task: dict, reason: str) -> dict:
    """Remaining suite tasks after a hard budget_exhausted stop."""
    return {
        "task": task,
        "run_dir": "",
        "score": {
            "outcome": "not_run",
            "verifier": task.get("verifier"),
            "task_id": task.get("id"),
            "reason": reason[:300],
        },
        "ended": "not_run",
        "budget_exhausted": False,
    }


def write_results_json(task_rows: list[dict]) -> Path:
    passed_n = sum(1 for t in task_rows if t.get("passed"))
    instance = (os.getenv("AGENTSWITCH_INSTANCE") or "local").strip() or "local"
    payload = {
        "tasks": task_rows,
        "summary": f"{instance}: {passed_n}/{len(task_rows)} tasks passed",
    }
    RESULTS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return RESULTS_PATH


def run_one(task: dict, *, repeats: int = 1) -> list[dict]:
    client = build_client()
    results = []
    try:
        client.ensure_token()
        client.initialize()
        cat = Catalogue.from_tools_list(client.tools_list())
        from agent.llm import resolve_api_key

        if not resolve_api_key():
            raise RuntimeError("Set OPENAI_API_KEY (official harness) or GEMINI_API_KEY (local)")

        for r in range(repeats):
            if task.get("adversary") == "pre_write_conflict":
                from harness.adversary import ConflictHrAgent

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
            results.append(
                {
                    "task": task,
                    "run_dir": str(run_dir),
                    "score": score,
                    "ended": journal.ended,
                    "budget_exhausted": bool(journal.budget_exhausted),
                }
            )
            print(
                json.dumps(
                    {
                        "repeat": r,
                        "outcome": score.get("outcome"),
                        "ended": journal.ended,
                        "run_dir": str(run_dir),
                    },
                    indent=2,
                ),
                flush=True,
            )

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
    parser.add_argument("--all", action="store_true", help="Run all tasks (default when no --task)")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args(argv)

    _maybe_load_local_dotenv()
    RUNS_DIR.mkdir(exist_ok=True)

    if args.list:
        for p in list_tasks():
            t = load_task(p)
            print(f"{t.get('id')}\t{t.get('verifier')}\t{t.get('family')}")
        return 0

    tasks = []
    if args.task:
        path = TASKS_DIR / f"{args.task}.json"
        if not path.exists():
            raise SystemExit(f"missing task: {path}")
        tasks = [load_task(path)]
    else:
        # Official harness: `python -m harness.runner` with no args → all tasks.
        tasks = [load_task(p) for p in list_tasks()]

    if not tasks:
        raise SystemExit("No tasks found under harness/tasks/")

    all_results: list[dict] = []
    official_rows: list[dict] = []
    # Pace LLM calls across a full suite (platform rate limits hit the last tasks).
    try:
        inter_task_sleep = float((os.getenv("LLM_INTER_TASK_SLEEP") or "0").strip() or "0")
    except ValueError:
        inter_task_sleep = 0.0
    if inter_task_sleep <= 0 and (os.getenv("OPENAI_BASE_URL") or "").strip() and (os.getenv("OPENAI_API_KEY") or "").strip():
        inter_task_sleep = 2.0
    budget_stop_reason: str | None = None
    try:
        for i, t in enumerate(tasks):
            if budget_stop_reason:
                print(f"\n=== {t['id']} (not_run) ===", flush=True)
                batch = [_not_run_result(t, budget_stop_reason)]
                all_results.extend(batch)
                for r in batch:
                    official_rows.append(
                        _official_task_row(r["task"], r.get("score") or {}, r.get("ended") or "")
                    )
                write_results_json(official_rows)
                continue
            if i and inter_task_sleep > 0:
                time.sleep(inter_task_sleep)
            print(f"\n=== {t['id']} ===", flush=True)
            try:
                batch = run_one(t, repeats=args.repeats)
            except Exception as e:
                print(f"TASK ERROR {t.get('id')}: {e}", flush=True)
                traceback.print_exc()
                batch = [_error_result(t, e)]
                from agent.llm import is_budget_exhausted

                if is_budget_exhausted(e):
                    budget_stop_reason = (
                        f"suite stopped after {t.get('id')}: budget_exhausted ({type(e).__name__}: {e})"
                    )[:300]
            all_results.extend(batch)
            for r in batch:
                official_rows.append(
                    _official_task_row(r["task"], r.get("score") or {}, r.get("ended") or "")
                )
                if r.get("budget_exhausted") or (r.get("ended") or "") == "budget_exhausted":
                    budget_stop_reason = (
                        f"suite stopped after {t.get('id')}: LLM budget_exhausted"
                    )
            # Incremental write so a timeout/kill still leaves partial results.
            write_results_json(official_rows)
        if budget_stop_reason:
            print(f"\nBUDGET STOP: {budget_stop_reason}", flush=True)
    finally:
        write_results_json(official_rows)

    summary_path = RUNS_DIR / f"summary_{int(time.time())}.json"
    summary_path.write_text(json.dumps(all_results, indent=2, default=str), encoding="utf-8")
    print(f"\nSummary: {summary_path}")
    print(f"Results: {RESULTS_PATH}")

    _print_scoreboard(all_results)
    bad = [r for r in all_results if (r.get("score") or {}).get("outcome") == "false_success"]
    if bad:
        print(f"note: {len(bad)} false_success outcome(s); results.json still written", flush=True)
    # Official runner scores from results.json; always exit 0 after writing it.
    return 0


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
