"""Tool catalogue: allowlists + closed-schema argument validation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# HR seat read surface — bar + capability work without overfitting to three tools.
READ_TOOLS = frozenset(
    {
        "Employee.list",
        "Employee.get",
        "LeaveApplication.list",
        "LeaveApplication.get",
        "Attendance.list",
        "Attendance.get",
        "LeaveBalance.list",
        "LeaveBalance.get",
        "LeaveType.list",
        "LeaveType.get",
        "HolidayList.list",
        "HolidayList.get",
    }
)

# Writes only when a task sets allow_writes and names the tool.
WRITE_TOOLS = frozenset(
    {
        "Attendance.create",
        "Attendance.update",
        "LeaveApplication.create",
        "LeaveApplication.update",
        "LeaveApplication.submit",
        "LeaveApplication.withdraw",
        "LeaveApplication.cancel.draft.cancelled",
    }
)

# Known absent / role-blocked — agent must refuse + escalate, never invent.
KNOWN_BLOCKED = frozenset(
    {
        "LeaveApplication.approve",
        "LeaveApplication.approve.pending_approval.approved",
        "LeaveApplication.reject",
        "LeaveApplication.reject.pending_approval.rejected",
    }
)


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class Catalogue:
    tools: dict[str, ToolSpec] = field(default_factory=dict)

    @classmethod
    def from_tools_list(cls, raw: list[dict[str, Any]]) -> "Catalogue":
        cat = cls()
        for t in raw:
            name = t.get("name") or ""
            schema = t.get("inputSchema") or t.get("input_schema") or {"type": "object", "properties": {}}
            cat.tools[name] = ToolSpec(
                name=name,
                description=t.get("description") or "",
                input_schema=schema,
            )
        return cat

    def has(self, name: str) -> bool:
        return name in self.tools

    def get(self, name: str) -> ToolSpec | None:
        return self.tools.get(name)

    def allowed_for_task(
        self,
        *,
        allow_writes: bool = False,
        write_allowlist: frozenset[str] | set[str] | None = None,
    ) -> list[ToolSpec]:
        """Intersect seat catalogue with our HR surface."""
        allowed: list[ToolSpec] = []
        writes = write_allowlist if write_allowlist is not None else WRITE_TOOLS
        for name, spec in sorted(self.tools.items()):
            if name in READ_TOOLS:
                allowed.append(spec)
            elif allow_writes and name in writes and name in WRITE_TOOLS:
                allowed.append(spec)
        return allowed

    def validate_args(self, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        """Closed-schema check: reject keys not in the tool's properties."""
        args = dict(arguments or {})
        spec = self.tools.get(name)
        if spec is None:
            raise ValueError(f"tool_not_in_catalogue: {name}")
        schema = spec.input_schema or {}
        props = schema.get("properties") or {}
        additional = schema.get("additionalProperties", True)
        if additional is False:
            unknown = [k for k in args if k not in props]
            if unknown:
                raise ValueError(f"closed_schema_violation for {name}: unknown keys {unknown}")
        required = schema.get("required") or []
        missing = [k for k in required if k not in args]
        if missing:
            raise ValueError(f"missing_required for {name}: {missing}")
        return args

    def openai_tools(
        self,
        *,
        allow_writes: bool = False,
        write_allowlist: frozenset[str] | set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """OpenAI-compatible function tool list from the allowlisted catalogue."""
        out = []
        for spec in self.allowed_for_task(allow_writes=allow_writes, write_allowlist=write_allowlist):
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": spec.name.replace(".", "__"),  # OpenAI names: no dots in some clients
                        "description": spec.description or spec.name,
                        "parameters": spec.input_schema
                        if spec.input_schema.get("type")
                        else {"type": "object", "properties": spec.input_schema.get("properties", {})},
                    },
                }
            )
        return out

    @staticmethod
    def wire_name(openai_name: str) -> str:
        """Map OpenAI-safe name back to AgentSwitch tool name."""
        if "__" in openai_name:
            return openai_name.replace("__", ".")
        return openai_name
