"""Replicate platform mid-run llm_error and ensure we stay evaluable."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from agent.catalogue import Catalogue
from agent.journal import RunJournal, Step
from agent.loop import (
    HrAgent,
    _compact_messages,
    _enrich_attendance_update,
    _recover_final_answer,
    _slim_tool_payload,
)
from agent.llm import BudgetExhaustedError
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


def test_slim_tool_payload_drops_display_fields():
    raw = {
        "id": "a1",
        "status": "present",
        "_permissions": {"write": True},
        "_display": "noise",
        "items": list(range(20)),
    }
    slim = _slim_tool_payload(raw, allow_writes=True)
    assert slim["id"] == "a1"
    assert "_permissions" not in slim
    assert len(slim["items"]) == 8
    assert slim["items_total"] == 20


def test_compact_messages_shortens_old_tools():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "go"},
    ]
    for i in range(8):
        messages.append({"role": "assistant", "content": "", "tool_calls": [{"id": f"c{i}"}]})
        messages.append({"role": "tool", "tool_call_id": f"c{i}", "content": "Z" * 2000})
    _compact_messages(messages, allow_writes=True)
    tool_lens = [len(m["content"]) for m in messages if m.get("role") == "tool"]
    assert any(n < 2000 for n in tool_lens[:-4])
    assert all(n == 2000 for n in tool_lens[-4:])


def test_agent_sets_budget_exhausted_flag(monkeypatch):
    monkeypatch.setattr("agent.llm.time.sleep", lambda *_a, **_k: None)
    monkeypatch.setenv("LLM_RETRIES_PER_MODEL", "1")
    monkeypatch.setenv("LLM_BACKOFF_SECONDS", "0.01")
    monkeypatch.setenv("LLM_TASK_TOKEN_LIMIT", "100000")

    class DeadLlm:
        def __init__(self):
            self.chat = self

        @property
        def completions(self):
            return self

        def create(self, **_kwargs):
            raise BudgetExhaustedError("HTTP 429 budget_exhausted")

    from agent.catalogue import ToolSpec

    cat = Catalogue(
        tools={
            "Employee.list": ToolSpec(
                name="Employee.list",
                description="list",
                input_schema={"type": "object", "properties": {}},
            ),
        }
    )
    agent = HrAgent(FakeMcp(), cat, openai_client=DeadLlm(), max_steps=3)
    journal = agent.run("Refuse this manufacturing work order.", task_id="refuse_out_of_seat")
    assert journal.budget_exhausted is True
    assert journal.ended == "budget_exhausted"


def test_agent_stops_on_cumulative_task_token_limit(monkeypatch):
    """Stop before the next LLM call once prompt+completion usage hits the task ceiling."""
    monkeypatch.setenv("LLM_TASK_TOKEN_LIMIT", "5000")

    class UsageLlm:
        def __init__(self):
            self.calls = 0
            self.chat = self

        @property
        def completions(self):
            return self

        def create(self, **_kwargs):
            self.calls += 1
            # First call burns the whole task budget; second must not be billed.
            if self.calls == 1:
                resp = _tool_response("hr__scan_leave_window", {"as_of": "2026-10-05"})
                resp.usage = SimpleNamespace(prompt_tokens=4800, completion_tokens=300)
                return resp
            resp = _text_response(
                '{"findings":{"on_leave":[],"attendance_flags":[],"confirmation_due":[]},'
                '"actions_taken":[],"uncertain":[],'
                '"refused":{"is_refusal":false,"why":"","escalate_to":""},'
                '"claimed_success":false,"as_of":"2026-10-05"}'
            )
            resp.usage = SimpleNamespace(prompt_tokens=50, completion_tokens=20)
            return resp

    from agent.catalogue import Catalogue

    llm = UsageLlm()
    agent = HrAgent(FakeMcp(), Catalogue(tools={}), openai_client=llm, max_steps=5)

    def fake_dispatch(journal, name, args, **kwargs):
        journal.tool_calls += 1
        journal.helper_results[name] = {"on_leave": []}
        journal.add(Step("tool", name, True, args=args))
        return {"on_leave": []}

    agent._dispatch_tool = fake_dispatch  # type: ignore[method-assign]

    journal = agent.run(
        "Who is on leave next week, whose attendance does not look right, and who is due for confirmation?",
        task_id="token_cap",
        as_of="2026-10-05",
    )
    assert journal.ended == "token_budget"
    assert llm.calls == 1
    assert journal.approx_tokens >= 5000
    assert "token_budget" in journal.error
    assert journal.final_answer is not None  # partial recovery from helpers


def test_agent_skips_call_that_would_exceed_task_limit(monkeypatch):
    """A prompt larger than the remaining budget is never sent."""
    monkeypatch.setenv("LLM_TASK_TOKEN_LIMIT", "1000")

    class NeverLlm:
        def __init__(self):
            self.calls = 0
            self.chat = self

        @property
        def completions(self):
            return self

        def create(self, **_kwargs):
            self.calls += 1
            raise AssertionError("LLM must not be called")

    from agent.catalogue import Catalogue

    llm = NeverLlm()
    agent = HrAgent(FakeMcp(), Catalogue(tools={}), openai_client=llm, max_steps=3)
    journal = agent.run("x" * 8000, task_id="token_cap")
    assert journal.ended == "token_budget"
    assert llm.calls == 0


class BalanceMcp(FakeMcp):
    def list_all(self, tool, arguments=None, **kw):
        if tool == "LeaveBalance.list":
            items = [
                {"id": "b1", "employee_id": "e1", "leave_type": "casual", "balance_days": 4, "used_days": 1},
                {"id": "b2", "employee_id": "e1", "leave_type": "sick", "balance_days": 6, "used_days": 0},
            ]
        elif tool == "Employee.list":
            items = [{"id": "e1", "status": "active", "first_name": "Asha"}]
        else:
            items = []
        return {"items": items, "total": len(items), "pages": 1, "partial_error": None}


BALANCE_PROMPT = (
    "Pick one active employee who has a LeaveBalance row. Put every LeaveBalance for that "
    "person in findings.leave_balances."
)


class ScriptedUsageLlm:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.messages_seen: list = []
        self.chat = self

    @property
    def completions(self):
        return self

    def create(self, **kwargs):
        self.calls += 1
        self.messages_seen.append(list(kwargs.get("messages") or []))
        resp, tokens = self.responses.pop(0)
        resp.usage = SimpleNamespace(prompt_tokens=tokens, completion_tokens=0)
        return resp


def test_token_cap_backfills_missing_helper_without_llm(monkeypatch):
    """Model never calls the balance helper; recovery fetches it over MCP so findings are complete."""
    monkeypatch.setenv("LLM_TASK_TOKEN_LIMIT", "20000")
    llm = ScriptedUsageLlm([
        (_text_response("thinking..."), 9000),
        (_text_response("still thinking..."), 10500),
    ])
    agent = HrAgent(BalanceMcp(), Catalogue(tools={}), openai_client=llm, max_steps=6)
    journal = agent.run(BALANCE_PROMPT, task_id="cap_balance_check", as_of="2026-10-05")
    assert journal.ended == "token_budget"
    assert llm.calls == 2
    assert any(s.target == "token_wrap_up" for s in journal.steps)
    rows = journal.final_answer["findings"]["leave_balances"]
    assert {r["leave_balance_id"] for r in rows} == {"b1", "b2"}
    assert journal.final_answer["claimed_success"] is False


def test_wrap_up_blocks_further_tool_calls(monkeypatch):
    """Past the wrap-up threshold a tool call is not executed; the task ends from gathered data."""
    monkeypatch.setenv("LLM_TASK_TOKEN_LIMIT", "20000")
    llm = ScriptedUsageLlm([
        (_tool_response("hr__scan_leave_balances", {}), 13000),
        (_tool_response("hr__scan_leave_balances", {"employee_id": "zzz"}, call_id="c2"), 500),
    ])
    agent = HrAgent(BalanceMcp(), Catalogue(tools={}), openai_client=llm, max_steps=6)
    journal = agent.run(BALANCE_PROMPT, task_id="cap_balance_check", as_of="2026-10-05")
    assert journal.ended == "token_budget"
    assert llm.calls == 2
    helper_steps = [s for s in journal.steps if s.target == "hr__scan_leave_balances"]
    assert len(helper_steps) == 1
    wrap_msgs = [m for m in llm.messages_seen[1] if m.get("role") == "user"]
    assert "Do not call any more tools" in str(wrap_msgs[-1]["content"])
    rows = journal.final_answer["findings"]["leave_balances"]
    assert len(rows) == 2


def test_wrap_up_final_answer_gets_backfilled_helpers(monkeypatch):
    """A final JSON given during wrap-up is accepted and merged with helper data fetched directly."""
    monkeypatch.setenv("LLM_TASK_TOKEN_LIMIT", "20000")
    final = (
        '{"findings":{"on_leave":[],"attendance_flags":[],"confirmation_due":[],"leave_balances":[]},'
        '"actions_taken":[],"uncertain":["LeaveType empty"],'
        '"refused":{"is_refusal":false,"why":"","escalate_to":""},'
        '"claimed_success":false,"as_of":"2026-10-05"}'
    )
    llm = ScriptedUsageLlm([
        (_text_response("hmm"), 13000),
        (_text_response(final), 500),
    ])
    agent = HrAgent(BalanceMcp(), Catalogue(tools={}), openai_client=llm, max_steps=6)
    journal = agent.run(BALANCE_PROMPT, task_id="cap_balance_check", as_of="2026-10-05")
    assert journal.ended == "done"
    assert llm.calls == 2
    assert len(journal.final_answer["findings"]["leave_balances"]) == 2


def test_write_tasks_do_not_wrap_up_early(monkeypatch):
    monkeypatch.setenv("LLM_TASK_TOKEN_LIMIT", "20000")
    final = (
        '{"findings":{"on_leave":[],"attendance_flags":[],"confirmation_due":[]},'
        '"actions_taken":[],"uncertain":[],'
        '"refused":{"is_refusal":false,"why":"","escalate_to":""},'
        '"claimed_success":false,"as_of":"2026-10-05"}'
    )
    llm = ScriptedUsageLlm([(_text_response("hmm"), 13000), (_text_response(final), 500)])
    agent = HrAgent(BalanceMcp(), Catalogue(tools={}), openai_client=llm, max_steps=6)
    journal = agent.run("Fix one attendance row.", task_id="w", as_of="2026-10-05", allow_writes=True)
    assert not any(s.target == "token_wrap_up" for s in journal.steps)
    assert all("Do not call any more tools" not in str(m.get("content")) for m in llm.messages_seen[1])
