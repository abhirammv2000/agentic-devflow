"""Durable run state.

A run has to survive the gap between "the agent wants to merge" and "a human
clicked approve in Slack an hour later", and those two moments are different
HTTP requests -- possibly different processes. So the entire conversation,
including the pending tool calls, is serialised to disk after every step.

That requirement is also why the engine drives a manual tool-use loop rather
than the SDK tool runner: the runner's loop lives in memory for the duration of
one call, and this one has to be suspendable.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .config import settings

STATUS_RUNNING = "running"
STATUS_AWAITING_APPROVAL = "awaiting_approval"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


@dataclass
class Run:
    id: str
    playbook: str
    inputs: dict[str, Any]
    autonomy: str
    provider: str = ""
    status: str = STATUS_RUNNING
    messages: list[dict[str, Any]] = field(default_factory=list)
    pending: dict[str, Any] | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    error: str = ""
    iterations: int = 0
    tool_calls: int = 0
    usage: dict[str, int] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def log(self, kind: str, **detail: Any) -> None:
        self.events.append({"ts": time.time(), "kind": kind, **detail})

    def add_usage(self, input_tokens: int, output_tokens: int) -> None:
        self.usage["input_tokens"] = self.usage.get("input_tokens", 0) + input_tokens
        self.usage["output_tokens"] = self.usage.get("output_tokens", 0) + output_tokens

    def public(self) -> dict[str, Any]:
        """The view n8n and humans get: no raw transcript, just what happened."""
        return {
            "run_id": self.id,
            "playbook": self.playbook,
            "status": self.status,
            "summary": self.summary,
            "error": self.error,
            "autonomy": self.autonomy,
            "provider": self.provider,
            "inputs": self.inputs,
            "iterations": self.iterations,
            "tool_calls": self.tool_calls,
            "usage": self.usage,
            "pending_approvals": (self.pending or {}).get("approvals", []),
            "actions": [e for e in self.events if e["kind"] == "tool_result"],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class RunStore:
    def __init__(self, directory: Path | None = None) -> None:
        self.dir = directory or settings.runs_dir
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, run_id: str) -> Path:
        return self.dir / (run_id + ".json")

    def create(self, playbook: str, inputs: dict[str, Any], autonomy: str) -> Run:
        run = Run(
            id="run_" + uuid.uuid4().hex[:12],
            playbook=playbook,
            inputs=inputs,
            autonomy=autonomy,
        )
        self.save(run)
        return run

    def save(self, run: Run) -> None:
        run.updated_at = time.time()
        self._path(run.id).write_text(
            json.dumps(asdict(run), indent=2, default=str), encoding="utf-8"
        )

    def load(self, run_id: str) -> Run | None:
        path = self._path(run_id)
        if not path.exists():
            return None
        return Run(**json.loads(path.read_text(encoding="utf-8")))

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        paths = sorted(self.dir.glob("run_*.json"), key=lambda p: p.stat().st_mtime,
                       reverse=True)
        out = []
        for path in paths[:limit]:
            run = Run(**json.loads(path.read_text(encoding="utf-8")))
            out.append(run.public())
        return out
