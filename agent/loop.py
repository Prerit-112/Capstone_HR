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

from agent.capabilities import missing_helpers, nudge_for_missing
from agent.catalogue import KNOWN_BLOCKED, READ_TOOLS, WRITE_TOOLS, Catalogue
from agent.gemini_compat import serialize_tool_calls
from agent.helpers import HELPER_NAMES, HELPER_TOOLS, run_helper
from agent.journal import RunJournal, Step
from agent.llm import build_llm_client, chat_with_fallback, resolve_fallbacks, resolve_model
from agent.mcp_client import McpClient, McpError
from agent.prompts import SYSTEM_PROMPT, user_message


def _excerpt(obj: Any, limit: int = 800) -> str:
    s = obj if isinstance(obj, str) else json.dumps(obj, default=str)
    return s if len(s) <= limit else s[: limit - 3] + "..."


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
        self.max_steps = max_steps or int(os.getenv("AGENT_MAX_STEPS", "24"))
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

        tools = self.catalogue.openai_tools(
            allow_writes=allow_writes,
            write_allowlist=write_allowlist,
        )
        # Prefer scan helpers for exception briefs (correct date paging + rules).
        tools = list(HELPER_TOOLS) + tools
        name_map = {t["function"]["name"]: Catalogue.wire_name(t["function"]["name"]) for t in tools}
        for h in HELPER_TOOLS:
            name_map[h["function"]["name"]] = h["function"]["name"]

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": user_message(prompt, as_of=as_of, allow_writes=allow_writes, run_id=run_id),
            },
        ]

        try:
            for _ in range(self.max_steps):
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
                except Exception as e:
                    journal.error = f"llm: {type(e).__name__}: {e}"
                    journal.add(Step("error", "llm", False, journal.error))
                    journal.finish("llm_error")
                    journal.wire_log = self.mcp.dump_wire_log()
                    return journal

                choice = resp.choices[0]
                msg = choice.message
                tool_calls = msg.tool_calls or []

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
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": json.dumps(result, default=str)[:12000],
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
                # Capability guard: don't accept success/empty claims without scan helpers.
                if not refused:
                    missing = missing_helpers(prompt, journal.steps, as_of=as_of)
                    if missing:
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

                journal.final_answer = parsed
                journal.claimed_success = bool(parsed.get("claimed_success"))
                journal.add(Step("answer", "final", True, result_excerpt=_excerpt(parsed)))
                journal.finish("refused" if refused else "done")
                journal.wire_log = self.mcp.dump_wire_log()
                return journal

            journal.finish("max_steps")
            journal.wire_log = self.mcp.dump_wire_log()
            return journal
        except Exception as e:
            journal.error = str(e)
            journal.finish("llm_error")
            journal.wire_log = self.mcp.dump_wire_log()
            return journal

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
                return result
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

        # Cache gets/lists samples for conflict detection.
        if ok and name.endswith(".get") and isinstance(result, dict) and result.get("id"):
            entity = name.split(".")[0]
            self._seen[f"{entity}:{result['id']}"] = result
        if ok and name.endswith(".list") and isinstance(result, dict):
            for row in result.get("data") or result.get("items") or []:
                if isinstance(row, dict) and row.get("id"):
                    entity = name.split(".")[0]
                    self._seen[f"{entity}:{row['id']}"] = row

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


def _record_fingerprint(record: Any) -> str:
    if not isinstance(record, dict):
        return repr(record)
    # Ignore volatile fields if present.
    skip = {"updated_at", "modified", "_transitions"}
    slim = {k: v for k, v in sorted(record.items()) if k not in skip}
    return json.dumps(slim, sort_keys=True, default=str)
