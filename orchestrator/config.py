"""Environment-driven configuration for the orchestrator service."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # so `python scripts/demo.py` picks up .env without an explicit export
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:  # python-dotenv is optional
    pass


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    model: str = os.getenv("DEVFLOW_MODEL", "claude-opus-5")
    effort: str = os.getenv("DEVFLOW_EFFORT", "high")
    max_tokens: int = _int("DEVFLOW_MAX_TOKENS", 32000)

    autonomy: str = os.getenv("DEVFLOW_AUTONOMY", "semi")
    max_iterations: int = _int("DEVFLOW_MAX_ITERATIONS", 25)
    max_tool_calls: int = _int("DEVFLOW_MAX_TOOL_CALLS", 60)

    data_dir: Path = Path(os.getenv("DEVFLOW_DATA_DIR", "./data")).resolve()
    workspace: Path = Path(os.getenv("DEVFLOW_WORKSPACE", "./sandbox/demo-repo")).resolve()
    mock: bool = os.getenv("DEVFLOW_MOCK", "1") == "1"

    service_token: str = os.getenv("DEVFLOW_SERVICE_TOKEN", "dev-local-token")
    approval_webhook: str = os.getenv("N8N_APPROVAL_WEBHOOK", "")

    # MCP servers the orchestrator launches over stdio, by logical name.
    mcp_servers: dict[str, list[str]] = field(
        default_factory=lambda: {
            "github": ["-m", "mcp_servers.github_server"],
            "jira": ["-m", "mcp_servers.jira_server"],
            "repo": ["-m", "mcp_servers.repo_server"],
        }
    )

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"


settings = Settings()
