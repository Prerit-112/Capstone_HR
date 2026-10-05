"""Run journal: claim separate from truth (S18-inspired, MCP-shaped)."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Step:
    kind: str  # tool | answer | refused | guard | reread | error
    target: str = ""
    ok: bool = True
    detail: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    result_excerpt: str = ""
    ts: float = field(default_factory=time.time)


@dataclass
class RunJournal:
    task_id: str
    harness: str = "hr_mcp"
    model: str = ""
    as_of: str = ""
    prompt: str = ""
    allow_writes: bool = False
    steps: list[Step] = field(default_factory=list)
    final_answer: dict[str, Any] | None = None
    claimed_success: bool = False
    ended: str = ""  # done | max_steps | llm_error | refused | guard
    error: str = ""
    calls: int = 0
    tool_calls: int = 0
    unusable_replies: int = 0
    seconds: float = 0.0
    started_at: float = field(default_factory=time.time)
    wire_log: list[dict[str, Any]] = field(default_factory=list)
    helper_results: dict[str, Any] = field(default_factory=dict)

    def add(self, step: Step) -> None:
        self.steps.append(step)

    def finish(self, ended: str) -> None:
        self.ended = ended
        self.seconds = time.time() - self.started_at

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, default=str), encoding="utf-8")
