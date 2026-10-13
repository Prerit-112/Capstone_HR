"""Replicate platform mid-run llm_error and ensure we stay evaluable."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from agent.catalogue import Catalogue
from agent.journal import RunJournal, Step
from agent.loop import HrAgent, _enrich_attendance_update, _recover_final_answer
from harness.verify import verify_write_conflict


class FakeMcp:
    def dump_wire_log(self):
        return []


class FlakyLlm:
    """Fails with a retryable-looking error after N successful completions."""

    def __init__(self, scripts: list[Any], *, fail_on_call: int):
        self.scripts = list(scripts)
        self.fail_on_call = fail_on_call
        self.calls = 0
        self.chat = self

    @property
    def completions(self):
        return self

    def create(self, **_kwargs):
        self.calls += 1
        if self.calls == self.fail_on_call:
            class RateLimitError(Exception):
                pass

            raise RateLimitError("Error code: 429 quota exhausted")
        if not self.scripts:
            raise RuntimeError("no more scripted LLM responses")
        return self.scripts.pop(0)


def _tool_response(name: str, args: dict, call_id: str = "c1"):
    tc = SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=__import__("json").dumps(args)),
    )
    msg = SimpleNamespace(content="", tool_calls=[tc])
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _text_response(text: str):
    msg = SimpleNamespace(content=text, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def test_enrich_attendance_keeps_punches_for_present():
    current = {
        "id": "a1",
        "employee_id": "e1",
        "date": "2026-09-24",
        "status": "present",
        "check_in": "09:00",
        "check_out": "18:00",
        "shift": None,
    }
    out = _enrich_attendance_update({"id": "a1", "status": "present"}, current, run_id="t-1")
    assert out["employee_id"] == "e1"
    assert out["check_in"] == "09:00"
    assert out["check_out"] == "18:00"
    assert "team13 agent correction" in out["shift"]


def test_enrich_attendance_absent_keeps_existing_punches():
    current = {
        "id": "a1",
        "employee_id": "e1",
        "date": "2026-09-24",
        "status": "present",
        "check_in": "08:00",
        "check_out": "06:00",
        "shift": "old",
    }
    out = _enrich_attendance_update({"id": "a1", "status": "absent"}, current, run_id="write_fix-abc")
    assert out["status"] == "absent"
    assert out["check_in"] == "08:00"
    assert out["employee_id"] == "e1"


def test_recover_conflict_makes_write_conflict_pass():
    j = RunJournal(task_id="write_conflict_abort", as_of="2026-10-05")
    j.add(
        Step(
            "guard",
            "Attendance.update",
            False,
            "shared_book_conflict: record changed since last read — write aborted",
            args={"id": "a1", "status": "absent"},
        )
    )
    j.error = "llm: RateLimitError: 429"
    ans = _recover_final_answer(j, as_of="2026-10-05", error=j.error)
    assert ans is not None
    assert ans["claimed_success"] is False
    assert ans["refused"]["is_refusal"] is True
    j.final_answer = ans
    j.claimed_success = False
    j.ended = "refused"
    score = verify_write_conflict(j)
    assert score["outcome"] == "verified_pass"


def test_recover_helpers_avoids_empty_not_evaluable():
    j = RunJournal(task_id="robust_as_of_window", as_of="2026-09-18")
    j.helper_results["hr__scan_leave_window"] = {"on_leave": []}
    j.helper_results["hr__scan_attendance_flags"] = {"flags": []}
    j.helper_results["hr__scan_confirmation_due"] = {"confirmation_due": []}
    j.add(Step("tool", "hr__scan_leave_window", True))
    ans = _recover_final_answer(j, as_of="2026-09-18", error="llm: RateLimitError: 429")
    assert ans is not None
    assert ans["claimed_success"] is False
    assert ans["findings"]["on_leave"] == []
    # With a final answer present, bar verifier will not return not_evaluable.
    j.final_answer = ans
    j.ended = "llm_error"
    assert j.final_answer


def test_agent_recovers_when_llm_dies_after_conflict(monkeypatch):
    monkeypatch.setattr("agent.llm.time.sleep", lambda *_a, **_k: None)
    monkeypatch.setenv("LLM_RETRIES_PER_MODEL", "1")
    monkeypatch.setenv("LLM_BACKOFF_SECONDS", "0.01")

    from agent.catalogue import ToolSpec

    cat = Catalogue(
        tools={
            "Attendance.update": ToolSpec(
                name="Attendance.update",
                description="update attendance",
                input_schema={"type": "object", "properties": {"id": {}, "status": {}}},
            ),
            "Attendance.get": ToolSpec(
                name="Attendance.get",
                description="get attendance",
                input_schema={"type": "object", "properties": {"id": {}}},
            ),
        }
    )
    # OpenAI-safe tool name uses double underscore.
    scripts = [
        _tool_response("Attendance__update", {"id": "a1", "status": "absent"}),
    ]
    llm = FlakyLlm(scripts, fail_on_call=2)  # second chat (after tool) dies
    agent = HrAgent(FakeMcp(), cat, openai_client=llm, max_steps=6)

    def fake_dispatch(journal, name, args, **kwargs):
        journal.tool_calls += 1
        if name == "Attendance.update":
            detail = "shared_book_conflict: record changed since last read — write aborted"
            journal.add(Step("guard", "Attendance.update", False, detail, args=args))
            return {
                "refused": True,
                "why": detail,
                "escalate_to": "re-read and decide again; Team 12 may have edited this row",
            }
        journal.add(Step("tool", name, True, args=args))
        return {"ok": True}

    agent._dispatch_tool = fake_dispatch  # type: ignore[method-assign]

    journal = agent.run(
        "Find one Attendance row and update it to absent; abort on conflict.",
        task_id="write_conflict_abort",
        as_of="2026-10-05",
        allow_writes=True,
        write_allowlist={"Attendance.update"},
    )
    assert journal.final_answer is not None
    assert journal.final_answer["refused"]["is_refusal"] is True
    assert journal.claimed_success is False
    score = verify_write_conflict(journal)
    assert score["outcome"] == "verified_pass"
