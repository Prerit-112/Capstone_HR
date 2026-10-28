"""MCP tool-calling agent loop with re-read-before-write and refusal."""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from datetime import date
from typing import Any

from openai import OpenAI

from agent.capabilities import (
    is_refusal_prompt,
    missing_helpers,
    needed_helpers,
    nudge_for_missing,
    tools_for_task,
)
from agent.catalogue import KNOWN_BLOCKED, READ_TOOLS, WRITE_TOOLS, Catalogue
from agent.gemini_compat import serialize_tool_calls
from agent.helpers import HELPER_NAMES, run_helper
from agent.journal import RunJournal, Step
from agent.llm import (
    BudgetExhaustedError,
    build_llm_client,
    chat_with_fallback,
    estimate_message_tokens,
    resolve_fallbacks,
    resolve_model,
    resolve_task_token_limit,
)
from agent.mcp_client import McpClient, McpError
from agent.prompts import SYSTEM_PROMPT, user_message

# Tool payloads in the chat transcript (write tasks are the longest / last in suite).
_TOOL_CONTENT_LIMIT_READ = 8_000
_TOOL_CONTENT_LIMIT_WRITE = 3_500
_COMPACT_TOOL_LIMIT = 600
# Past this share of the task token limit, ask for the final answer and stop running tools.
_WRAP_UP_FRACTION = 0.6
_WRAP_UP_MESSAGE = (
    "Token budget for this task is nearly used. Do not call any more tools. "
    "Reply now with ONLY the final JSON object, using the data you already have; "
    "put anything you could not check in uncertain."
)


def _excerpt(obj: Any, limit: int = 800) -> str:
    s = obj if isinstance(obj, str) else json.dumps(obj, default=str)
    return s if len(s) <= limit else s[: limit - 3] + "..."


def _tool_content_limit(*, allow_writes: bool) -> int:
    raw = (os.getenv("LLM_TOOL_CONTENT_LIMIT") or "").strip()
    if raw:
        try:
            return max(500, int(raw))
        except ValueError:
            pass
    return _TOOL_CONTENT_LIMIT_WRITE if allow_writes else _TOOL_CONTENT_LIMIT_READ


def _slim_tool_payload(result: Any, *, allow_writes: bool) -> Any:
    """Drop bulky / display-only fields before they enter the LLM transcript."""
    if not isinstance(result, dict):
        return result
    skip = {
        "_transitions",
        "_next",
        "_permissions",
        "_can_create",
        "_display",
        "_company_id_display",
        "_employee_id_display",
        "_verify_with",
        "wire",
        "raw",
    }
    out: dict[str, Any] = {}
    for k, v in result.items():
        if k in skip or str(k).startswith("_"):
            continue
        if isinstance(v, list) and allow_writes and len(v) > 8:
            out[k] = v[:8]
            out[f"{k}_total"] = len(v)
        else:
            out[k] = v
    return out


def _compact_messages(messages: list[dict[str, Any]], *, allow_writes: bool) -> None:
    """Shrink older tool results in-place so write-task histories stay under budget."""
    if len(messages) < 8:
        return
    # Keep system + first user intact; compact tool messages except the last few.
    keep_tail = 4 if allow_writes else 6
    tool_idxs = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    if len(tool_idxs) <= keep_tail:
        return
    for i in tool_idxs[:-keep_tail]:
        content = messages[i].get("content") or ""
        if isinstance(content, str) and len(content) > _COMPACT_TOOL_LIMIT:
            messages[i]["content"] = content[: _COMPACT_TOOL_LIMIT - 20] + "...[compacted]"


def _parse_final_json(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None
    # Strip optional fences
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None


class HrAgent:
    def __init__(
        self,
        mcp: McpClient,
        catalogue: Catalogue,
        *,
        model: str | None = None,
        max_steps: int | None = None,
        openai_client: OpenAI | None = None,
    ):
        self.mcp = mcp
        self.catalogue = catalogue
        self.model = model or resolve_model()
        self.model_chain = resolve_fallbacks(self.model)
        self.max_steps = max_steps or int(os.getenv("AGENT_MAX_STEPS", "10"))
        self.llm = openai_client if openai_client is not None else build_llm_client()
        # Cache of last-seen records for re-read-before-write.
        self._seen: dict[str, dict[str, Any]] = {}  # "Entity:id" -> record

    def run(
        self,
        prompt: str,
        *,
        task_id: str = "adhoc",
        as_of: str | None = None,
        allow_writes: bool = False,
        write_allowlist: set[str] | None = None,
    ) -> RunJournal:
        as_of = as_of or date.today().isoformat()
        run_id = f"{task_id}-{uuid.uuid4().hex[:8]}"
        journal = RunJournal(
            task_id=task_id,
            model=self.model,
            as_of=as_of,
            prompt=prompt,
            allow_writes=allow_writes,
        )

        tools = tools_for_task(
            self.catalogue,
            prompt,
            allow_writes=allow_writes,
            write_allowlist=write_allowlist,
        )
        name_map = {
            t["function"]["name"]: (
                t["function"]["name"]
                if t["function"]["name"].startswith("hr__")
                else Catalogue.wire_name(t["function"]["name"])
            )
            for t in tools
        }

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": user_message(prompt, as_of=as_of, allow_writes=allow_writes, run_id=run_id),
            },
        ]

        token_limit = resolve_task_token_limit()
        # Write tasks never wrap up early: stopping before the write is always a fail.
        wrap_up_at = token_limit if allow_writes else int(token_limit * _WRAP_UP_FRACTION)
        wrap_up = False
        tool_limit = _tool_content_limit(allow_writes=allow_writes)

        try:
            for _ in range(self.max_steps):
                _compact_messages(messages, allow_writes=allow_writes)
                next_call = estimate_message_tokens(messages, tools or None)
                if not wrap_up and journal.approx_tokens + next_call > wrap_up_at:
                    wrap_up = True
                    journal.add(
                        Step(
                            "guard",
                            "token_wrap_up",
                            True,
                            f"used {journal.approx_tokens} of {token_limit} tokens; asking for final JSON",
                        )
                    )
                    messages.append({"role": "user", "content": _WRAP_UP_MESSAGE})
                    next_call = estimate_message_tokens(messages, tools or None)
                # Hard ceiling: stop if the next billed call would push the task past the limit.
                if journal.approx_tokens + next_call > token_limit:
                    journal.error = (
                        f"token_budget: task used {journal.approx_tokens} tokens, next call "
                        f"~{next_call} would exceed limit {token_limit}"
                    )
                    journal.add(Step("error", "token_budget", False, journal.error))
                    return self._finish_after_llm_failure(
                        journal, as_of=as_of, ended_hint="token_budget"
                    )
                journal.calls += 1
                try:
                    resp, used_model = chat_with_fallback(
                        self.llm,
                        messages=messages,
                        tools=tools or None,
                        models=self.model_chain,
                        temperature=0.1,
                    )
                    if used_model != self.model:
                        journal.add(
                            Step(
                                "guard",
                                "llm_fallback",
                                True,
                                f"switched {self.model} -> {used_model} after rate/limit error",
                            )
                        )
                        self.model = used_model
                        journal.model = used_model
                except BudgetExhaustedError as e:
                    journal.error = f"llm: budget_exhausted: {e}"
                    journal.add(Step("error", "llm", False, journal.error))
                    journal.budget_exhausted = True
                    return self._finish_after_llm_failure(
                        journal, as_of=as_of, ended_hint="budget_exhausted"
                    )
                except Exception as e:
                    msg = str(e)
                    if "invalid tool" in msg.lower() or "invalid_function" in msg.lower():
                        journal.add(Step("error", "llm", False, f"retryable: {type(e).__name__}: {e}"))
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "The last tool call was rejected (invalid arguments). "
                                    "Call tools using only schema properties, or reply with the final JSON."
                                ),
                            }
                        )
                        continue
                    journal.error = f"llm: {type(e).__name__}: {e}"
                    journal.add(Step("error", "llm", False, journal.error))
                    return self._finish_after_llm_failure(journal, as_of=as_of)

                used = 0
                usage = getattr(resp, "usage", None)
                if usage is not None:
                    used = int(getattr(usage, "prompt_tokens", 0) or 0) + int(
                        getattr(usage, "completion_tokens", 0) or 0
                    )
                if used <= 0:
                    used = estimate_message_tokens(messages, tools or None)
                journal.approx_tokens += used

                choices = getattr(resp, "choices", None) or []
                if not choices:
                    journal.error = "llm: empty choices in chat completion"
                    journal.add(Step("error", "llm", False, journal.error))
                    return self._finish_after_llm_failure(journal, as_of=as_of)

                choice = choices[0]
                msg = choice.message
                tool_calls = msg.tool_calls or []

                if tool_calls and wrap_up:
                    journal.error = "token_budget: tool call after wrap-up request; finishing from data gathered"
                    journal.add(Step("error", "token_budget", False, journal.error))
                    return self._finish_after_llm_failure(journal, as_of=as_of, ended_hint="token_budget")

                if tool_calls:
                    messages.append(
                        {
                            "role": "assistant",
                            "content": msg.content or "",
                            "tool_calls": serialize_tool_calls(tool_calls),
                        }
                    )
                    for tc in tool_calls:
                        openai_name = tc.function.name
                        wire_name = name_map.get(openai_name, Catalogue.wire_name(openai_name))
                        try:
                            args = json.loads(tc.function.arguments or "{}")
                        except json.JSONDecodeError:
                            args = {}
                            result = {"error": "invalid_tool_arguments_json"}
                            journal.add(Step("tool", wire_name, False, "bad args json", args=args))
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tc.id,
                                    "content": json.dumps(result),
                                }
                            )
                            continue

                        result = self._dispatch_tool(
                            journal,
                            wire_name,
                            args,
                            allow_writes=allow_writes,
                            write_allowlist=write_allowlist,
                            run_id=run_id,
                        )
                        slim = _slim_tool_payload(result, allow_writes=allow_writes)
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": json.dumps(slim, default=str)[:tool_limit],
                            }
                        )
                    continue

                # Final text answer
                content = msg.content or ""
                parsed = _parse_final_json(content)
                if parsed is None:
                    journal.unusable_replies += 1
                    journal.add(Step("answer", "final", False, "unparseable json", result_excerpt=_excerpt(content)))
                    messages.append({"role": "assistant", "content": content})
                    messages.append(
                        {
                            "role": "user",
                            "content": "Your last reply was not valid JSON matching the required schema. Reply with ONLY the JSON object.",
                        }
                    )
                    continue

                refused = bool((parsed.get("refused") or {}).get("is_refusal"))
                if is_refusal_prompt(prompt) and not refused:
                    journal.add(Step("guard", "refusal_required", False, "ask is out of seat or unsupported"))
                    messages.append({"role": "assistant", "content": content})
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "This request cannot be completed from Team 13 HR tools "
                                "(missing app, missing approve transition, or no punch/geofence root-cause fields). "
                                "Reply with JSON: refused.is_refusal=true, claimed_success=false, "
                                "escalate_to naming admin/Approvals or the owning seat, and why."
                            ),
                        }
                    )
                    continue
                if not refused and not allow_writes:
                    missing = missing_helpers(prompt, journal.steps, as_of=as_of)
                    if missing and wrap_up:
                        self._backfill_helpers(journal, as_of=as_of)
                    elif missing:
                        journal.add(
                            Step(
                                "guard",
                                "helpers_required",
                                False,
                                f"missing helpers before final answer: {sorted(missing)}",
                            )
                        )
                        messages.append({"role": "assistant", "content": content})
                        messages.append(
                            {
                                "role": "user",
                                "content": nudge_for_missing(missing, as_of=as_of),
                            }
                        )
                        continue
                    parsed = _merge_helper_findings(parsed, journal.helper_results)

                journal.final_answer = parsed
                journal.claimed_success = bool(parsed.get("claimed_success"))
                journal.add(Step("answer", "final", True, result_excerpt=_excerpt(parsed)))
                journal.finish("refused" if refused else "done")
                journal.wire_log = self.mcp.dump_wire_log()
                return journal

            journal.error = journal.error or "max_steps reached without final JSON"
            journal.add(Step("error", "max_steps", False, journal.error))
            return self._finish_after_llm_failure(journal, as_of=as_of, ended_hint="max_steps")
        except Exception as e:
            journal.error = f"{type(e).__name__}: {e}"
            journal.add(Step("error", "uncaught", False, journal.error))
            return self._finish_after_llm_failure(journal, as_of=as_of)

    def _finish_after_llm_failure(
        self,
        journal: RunJournal,
        *,
        as_of: str,
        ended_hint: str | None = None,
    ) -> RunJournal:
        """Turn a mid-run LLM/transport failure into an honest evaluable answer when possible."""
        self._backfill_helpers(journal, as_of=as_of)
        recovered = _recover_final_answer(journal, as_of=as_of, error=journal.error or "llm_error")
        if recovered is not None:
            journal.final_answer = recovered
            journal.claimed_success = bool(recovered.get("claimed_success"))
            journal.add(Step("answer", "recovered", True, result_excerpt=_excerpt(recovered)))
            refused = bool((recovered.get("refused") or {}).get("is_refusal"))
            journal.finish("refused" if refused else (ended_hint or "llm_error"))
        else:
            journal.finish(ended_hint or "llm_error")
        journal.wire_log = self.mcp.dump_wire_log()
        return journal

    def _backfill_helpers(self, journal: RunJournal, *, as_of: str) -> None:
        """Run read helpers the ask needs but the model never called — MCP only, no LLM tokens."""
        if journal.allow_writes or is_refusal_prompt(journal.prompt):
            return
        # Two rounds: a non-empty holiday scan adds leave + attendance helpers.
        for _ in range(2):
            missing = set(missing_helpers(journal.prompt, journal.steps, as_of=as_of))
            missing |= set(needed_helpers(journal.prompt)) - set(journal.helper_results)
            if not missing:
                return
            for name in sorted(missing):
                try:
                    self._dispatch_tool(
                        journal,
                        name,
                        {"as_of": as_of},
                        allow_writes=False,
                        write_allowlist=None,
                        run_id="backfill",
                    )
                except Exception as e:
                    journal.add(Step("error", name, False, f"backfill failed: {e}"))

    def _dispatch_tool(
        self,
        journal: RunJournal,
        name: str,
        args: dict[str, Any],
        *,
        allow_writes: bool,
        write_allowlist: set[str] | None,
        run_id: str,
    ) -> Any:
        journal.tool_calls += 1

        if name in HELPER_NAMES or name.startswith("hr__"):
            try:
                result = run_helper(self.mcp, name, args)
                ok = not (isinstance(result, dict) and result.get("error"))
                if ok and isinstance(result, dict):
                    journal.helper_results[name] = result
                journal.add(
                    Step(
                        "tool",
                        name,
                        ok,
                        "" if ok else str(result.get("error")),
                        args=args,
                        result_excerpt=_excerpt(result),
                    )
                )
                return _helper_view_for_llm(name, result)
            except Exception as e:
                journal.add(Step("tool", name, False, str(e), args=args))
                return {"error": str(e)}

        # Block known approve paths even if somehow listed.
        if name in KNOWN_BLOCKED or "approve" in name.lower() or name.endswith(".reject"):
            detail = "role/platform: leave approve/reject not available to hr_user — escalate to admin/Approvals"
            journal.add(Step("refused", name, False, detail, args=args))
            return {
                "refused": True,
                "why": detail,
                "escalate_to": "admin or Approvals seat — LeaveApplication.approve* not in our MCP catalogue / requires admin",
            }

        writes = write_allowlist if write_allowlist is not None else set(WRITE_TOOLS)
        is_write = name in WRITE_TOOLS or name.split(".")[-1] in {
            "create",
            "update",
            "submit",
            "withdraw",
            "delete",
        } or ".cancel." in name

        if is_write and (not allow_writes or name not in writes):
            detail = f"guard: write {name} not permitted for this task"
            journal.add(Step("guard", name, False, detail, args=args))
            return {"refused": True, "why": detail, "escalate_to": "re-run task with allow_writes if intentional"}

        if name not in self.catalogue.tools and name not in READ_TOOLS and name not in WRITE_TOOLS:
            detail = f"tool_not_available for this seat: {name}"
            journal.add(Step("refused", name, False, detail, args=args))
            return {
                "refused": True,
                "why": detail,
                "escalate_to": "EA/admin or the seat that owns this app — cross-app data is out of scope for Team 13 HR",
            }

        try:
            args = self.catalogue.validate_args(name, args)
        except ValueError as e:
            journal.add(Step("guard", name, False, str(e), args=args))
            return {"error": str(e)}

        # Re-read before write when we have an id.
        if is_write and args.get("id"):
            entity = name.split(".")[0]
            get_tool = f"{entity}.get"
            if get_tool in self.catalogue.tools or get_tool in READ_TOOLS:
                try:
                    current = self.mcp.tools_call(get_tool, {"id": args["id"]})
                    key = f"{entity}:{args['id']}"
                    previous = self._seen.get(key)
                    journal.add(
                        Step(
                            "reread",
                            get_tool,
                            True,
                            "pre-write re-read",
                            args={"id": args["id"]},
                            result_excerpt=_excerpt(current, 400),
                        )
                    )
                    if previous is not None and _record_fingerprint(previous) != _record_fingerprint(current):
                        detail = "shared_book_conflict: record changed since last read — write aborted"
                        journal.add(Step("guard", name, False, detail, args=args))
                        return {
                            "refused": True,
                            "why": detail,
                            "escalate_to": "re-read and decide again; Team 12 may have edited this row",
                            "current": current,
                        }
                    self._seen[key] = current if isinstance(current, dict) else {"_raw": current}
                    if name == "Attendance.update" and isinstance(current, dict):
                        args = _enrich_attendance_update(args, current, run_id=run_id)
                    # Stamp provenance into free-text reason when present.
                    if "reason" in (self.catalogue.get(name).input_schema.get("properties") or {}):
                        stamp = f" [team13 agent {run_id}]"
                        existing = args.get("reason") or ""
                        if stamp.strip() not in existing:
                            args["reason"] = (existing + stamp).strip()
                except McpError as e:
                    journal.add(Step("reread", get_tool, False, str(e)))
                    return {"error": f"pre-write re-read failed: {e}"}

        try:
            result = self.mcp.tools_call(name, args)
            ok = True
            detail = ""
        except McpError as e:
            result = {"error": str(e), "code": e.code, "data": e.data}
            ok = False
            detail = str(e)

        # Cache authoritative .get snapshots only. List rows often differ in
        # display/_permissions/int-vs-bool fields and caused false conflicts.
        if ok and name.endswith(".get") and isinstance(result, dict) and result.get("id"):
            entity = name.split(".")[0]
            self._seen[f"{entity}:{result['id']}"] = result

        journal.add(
            Step(
                "tool",
                name,
                ok,
                detail,
                args=args,
                result_excerpt=_excerpt(result),
            )
        )
        return result


def _as_boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _enrich_attendance_update(args: dict[str, Any], current: dict[str, Any], *, run_id: str) -> dict[str, Any]:
    """Fill required Attendance.update fields from the live row so present-without-punches is not sent."""
    out = dict(args)
    for key in ("employee_id", "date", "company_id"):
        if out.get(key) in (None, "") and current.get(key) is not None:
            out[key] = current[key]
    if out.get("date") is not None:
        out["date"] = str(out["date"])[:10]

    status = str(out.get("status") if out.get("status") is not None else current.get("status") or "").strip().lower()
    # present rows reject updates that drop punches
    if status == "present":
        for key in ("check_in", "check_out"):
            if out.get(key) in (None, "") and current.get(key) is not None:
                out[key] = current[key]
    else:
        # Keep punches when correcting to absent unless the model explicitly cleared them.
        for key in ("check_in", "check_out", "overtime_hours"):
            if key not in out and current.get(key) is not None:
                out[key] = current[key]

    # Closed schema: is_lop must be boolean; live rows often store 0/1.
    if "is_lop" in out:
        out["is_lop"] = _as_boolish(out["is_lop"])
    if "lop_hours" in out and out["lop_hours"] is not None:
        try:
            out["lop_hours"] = float(out["lop_hours"])
        except (TypeError, ValueError):
            out["lop_hours"] = 0.0
    if "overtime_hours" in out and out["overtime_hours"] is not None:
        try:
            out["overtime_hours"] = float(out["overtime_hours"])
        except (TypeError, ValueError):
            out["overtime_hours"] = 0.0

    if not (out.get("shift") or "").strip():
        prior = (current.get("shift") or "").strip()
        note = f"team13 agent correction: {run_id}"
        out["shift"] = prior if prior.startswith("team13 agent correction") else note
    return out


def _conflict_step(journal: RunJournal) -> Step | None:
    for step in reversed(journal.steps):
        blob = f"{step.detail or ''} {step.result_excerpt or ''}"
        if "shared_book_conflict" in blob:
            return step
    return None


def _empty_findings() -> dict[str, Any]:
    return {
        "on_leave": [],
        "attendance_flags": [],
        "confirmation_due": [],
        "leave_balances": [],
        "holidays": [],
        "holiday_week": None,
    }


def _recover_final_answer(journal: RunJournal, *, as_of: str, error: str) -> dict[str, Any] | None:
    """Build an honest final JSON from journal state after LLM failure.

    Returns None only when there is nothing useful to report (no tools, no conflict).
    """
    conflict = _conflict_step(journal)
    has_helpers = bool(journal.helper_results)
    has_tools = any(s.kind in {"tool", "reread", "guard", "refused"} for s in journal.steps)
    if conflict is None and not has_helpers and not has_tools:
        return None

    base: dict[str, Any] = {
        "findings": _empty_findings(),
        "actions_taken": [],
        "uncertain": [f"run interrupted: {error}"] if error else ["run interrupted before final model reply"],
        "refused": {"is_refusal": False, "why": "", "escalate_to": ""},
        "claimed_success": False,
        "as_of": as_of,
    }
    base = _merge_helper_findings(base, journal.helper_results)

    if conflict is not None:
        base["refused"] = {
            "is_refusal": True,
            "why": conflict.detail or "shared_book_conflict: record changed since last read — write aborted",
            "escalate_to": "Team 12 (Payroll) or admin — shared-book conflict; re-read and decide again",
        }
        base["claimed_success"] = False
        return base

    # Prefer honest shortfall over inventing success after a crash.
    base["claimed_success"] = False
    return base


def _helper_view_for_llm(name: str, result: Any) -> Any:
    """Keep the model context small; full helper payload is on the journal."""
    if not isinstance(result, dict):
        return result
    view = dict(result)
    # Tighter caps — full rows stay on the journal for scoring/recovery.
    for key, cap in (("flags", 12), ("confirmation_due", 12), ("on_leave", 12), ("balances", 12)):
        rows = view.get(key)
        if isinstance(rows, list) and len(rows) > cap:
            view[key] = rows[:cap]
            view[f"{key}_total"] = len(rows)
            view["note"] = (
                "Full helper rows are stored by the agent and copied into findings. "
                "Do not subsample or invent extra rows."
            )
    return view


def _merge_helper_findings(parsed: dict[str, Any], helper_results: dict[str, Any]) -> dict[str, Any]:
    findings = dict(parsed.get("findings") or {})
    att = helper_results.get("hr__scan_attendance_flags")
    if isinstance(att, dict) and isinstance(att.get("flags"), list):
        findings["attendance_flags"] = att["flags"]
    leave = helper_results.get("hr__scan_leave_window")
    if isinstance(leave, dict) and isinstance(leave.get("on_leave"), list):
        findings["on_leave"] = leave["on_leave"]
    conf = helper_results.get("hr__scan_confirmation_due")
    if isinstance(conf, dict) and isinstance(conf.get("confirmation_due"), list):
        findings["confirmation_due"] = conf["confirmation_due"]
    bals = helper_results.get("hr__scan_leave_balances")
    if isinstance(bals, dict) and isinstance(bals.get("balances"), list):
        findings["leave_balances"] = bals["balances"]
        if bals.get("leave_type_catalogue_empty"):
            notes = list(parsed.get("uncertain") or [])
            msg = "LeaveType.list is empty; annual_entitlement unknown"
            if msg not in notes:
                notes.append(msg)
            parsed["uncertain"] = notes
    hol = helper_results.get("hr__scan_holidays")
    if isinstance(hol, dict):
        if isinstance(hol.get("holidays"), list):
            findings["holidays"] = hol["holidays"]
        week = hol.get("suggested_week")
        if isinstance(week, dict):
            findings["holiday_week"] = {"from_date": week.get("from_date"), "to_date": week.get("to_date")}
        if hol.get("catalogue_empty"):
            parsed["claimed_success"] = False
            notes = list(parsed.get("uncertain") or [])
            msg = "HolidayList has no child holiday dates"
            if msg not in notes:
                notes.append(msg)
            parsed["uncertain"] = notes
    parsed["findings"] = findings
    return parsed


def _record_fingerprint(record: Any) -> str:
    if not isinstance(record, dict):
        return repr(record)
    # Ignore volatile / display-only fields; normalize types that flip between list/get.
    skip = {
        "updated_at",
        "modified",
        "_transitions",
        "_next",
        "_permissions",
        "_can_create",
        "_display",
        "_company_id_display",
        "_employee_id_display",
        "_verify_with",
    }
    slim: dict[str, Any] = {}
    for k, v in sorted(record.items()):
        if k in skip or str(k).startswith("_"):
            continue
        if k == "is_lop":
            slim[k] = _as_boolish(v)
        elif k in {"lop_hours", "overtime_hours"} and v is not None:
            try:
                slim[k] = float(v)
            except (TypeError, ValueError):
                slim[k] = v
        elif k == "date" and v is not None:
            slim[k] = str(v)[:10]
        else:
            slim[k] = v
    return json.dumps(slim, sort_keys=True, default=str)
