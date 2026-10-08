"""Saved run state.

A run has to survive the gap between "the agent wants to merge" and "a human clicked
approve in Slack an hour later". Those are two different HTTP requests, maybe in different
processes, so the whole conversation, pending tool calls included, is written to disk after
every step.

This is also why the engine runs its own tool-use loop. An SDK tool runner keeps its loop
in memory for the length of one call, and this one has to be able to pause.
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
    # True once a read tool has returned outside text. Saved with the run, so it survives a pause for approval.
    tainted: bool = False
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
            "tainted": self.tainted,
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

    def usage_summary(self, input_price: float = 0.0, output_price: float = 0.0) -> dict[str, Any]:
        """Token totals over every saved run, overall and per playbook.

        Prices are dollars per million tokens. With both at zero no cost is
        estimated and the cost fields are None.
        """
        by_playbook: dict[str, dict[str, int]] = {}
        for path in self.dir.glob("run_*.json"):
            run = Run(**json.loads(path.read_text(encoding="utf-8")))
            entry = by_playbook.setdefault(
                run.playbook, {"runs": 0, "input_tokens": 0, "output_tokens": 0}
            )
            entry["runs"] += 1
            entry["input_tokens"] += run.usage.get("input_tokens", 0)
            entry["output_tokens"] += run.usage.get("output_tokens", 0)

        def with_cost(entry: dict[str, int]) -> dict[str, Any]:
            cost = None
            if input_price or output_price:
                cost = round(
                    entry["input_tokens"] / 1e6 * input_price
                    + entry["output_tokens"] / 1e6 * output_price,
                    4,
                )
            return {**entry, "estimated_cost_usd": cost}

        total = {"runs": 0, "input_tokens": 0, "output_tokens": 0}
        for entry in by_playbook.values():
            for key in total:
                total[key] += entry[key]
        return {
            "total": with_cost(total),
            "by_playbook": {name: with_cost(e) for name, e in sorted(by_playbook.items())},
        }

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        paths = sorted(self.dir.glob("run_*.json"), key=lambda p: p.stat().st_mtime,
                       reverse=True)
        out = []
        for path in paths[:limit]:
            run = Run(**json.loads(path.read_text(encoding="utf-8")))
            out.append(run.public())
        return out
