"""MCP server giving the agent a sandboxed working copy: read, edit, search,
diff and a narrowly allow-listed test runner.

Everything is confined to DEVFLOW_WORKSPACE. Paths that resolve outside it are
rejected, and only commands whose first token is on ALLOWED_COMMANDS may run.

Run standalone:  python -m mcp_servers.repo_server   (stdio transport)
"""

from __future__ import annotations

import difflib
import fnmatch
import json
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

from mcp.server import MCPServer

from .backends import DATA_DIR, err, ok

server = MCPServer("devflow-repo")

WORKSPACE = Path(os.getenv("DEVFLOW_WORKSPACE", "./sandbox/demo-repo")).resolve()
BASELINE = DATA_DIR / "workspace_baseline.json"

# The agent may run tests and linters. It may not run arbitrary shell.
ALLOWED_COMMANDS = {"pytest", "python", "python3", "npm", "npx", "ruff", "mypy"}
TEST_TIMEOUT_SECONDS = 120
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", ".pytest_cache"}
MAX_READ_BYTES = 200_000


def _resolve(rel: str) -> Path:
    """Resolve a workspace-relative path, refusing anything that escapes the root."""
    candidate = (WORKSPACE / rel).resolve()
    if candidate != WORKSPACE and WORKSPACE not in candidate.parents:
        raise ValueError("path escapes the workspace: " + rel)
    return candidate


def _iter_files():
    for path in WORKSPACE.rglob("*"):
        if path.is_file() and not any(part in SKIP_DIRS for part in path.parts):
            yield path


def _baseline() -> dict[str, str]:
    if BASELINE.exists():
        return json.loads(BASELINE.read_text(encoding="utf-8"))
    return {}


def _remember_baseline(rel: str, content: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data = _baseline()
    data.setdefault(rel, content)
    BASELINE.write_text(json.dumps(data, indent=2), encoding="utf-8")


@server.tool()
def repo_list_files(pattern: str = "*") -> dict[str, Any]:
    """List files in the working copy, optionally filtered by a glob such as "src/*.py"."""
    files = sorted(
        str(p.relative_to(WORKSPACE)).replace("\\", "/") for p in _iter_files()
    )
    if pattern and pattern != "*":
        files = [f for f in files if fnmatch.fnmatch(f, pattern)]
    return ok(workspace=str(WORKSPACE), files=files)


@server.tool()
def repo_read_file(path: str) -> dict[str, Any]:
    """Read a file from the working copy."""
    try:
        target = _resolve(path)
    except ValueError as exc:
        return err(str(exc))
    if not target.is_file():
        return err("no such file: " + path)
    if target.stat().st_size > MAX_READ_BYTES:
        return err("file is larger than {} bytes; read it in pieces".format(MAX_READ_BYTES))
    return ok(path=path, content=target.read_text(encoding="utf-8", errors="replace"))


@server.tool()
def repo_search(pattern: str, glob: str = "*") -> dict[str, Any]:
    """Regex-search the working copy. Returns up to 100 matching lines with line numbers."""
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        return err("invalid regex: " + str(exc))
    matches: list[dict[str, Any]] = []
    for path in _iter_files():
        rel = str(path.relative_to(WORKSPACE)).replace("\\", "/")
        if glob != "*" and not fnmatch.fnmatch(rel, glob):
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(lines, 1):
            if rx.search(line):
                matches.append({"file": rel, "line": n, "text": line.strip()[:200]})
                if len(matches) >= 100:
                    return ok(matches=matches, truncated=True)
    return ok(matches=matches, truncated=False)


@server.tool()
def repo_write_file(path: str, content: str) -> dict[str, Any]:
    """Create or overwrite a file in the working copy and return the resulting diff.

    Writes stay local -- publishing them is a separate, separately-gated step
    (gh_commit_file / gh_open_pull_request).
    """
    try:
        target = _resolve(path)
    except ValueError as exc:
        return err(str(exc))
    before = target.read_text(encoding="utf-8") if target.is_file() else ""
    _remember_baseline(path, before)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    diff = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            content.splitlines(keepends=True),
            fromfile="a/" + path,
            tofile="b/" + path,
        )
    )
    return ok(path=path, bytes_written=len(content.encode()), diff=diff or "(no change)")


@server.tool()
def repo_diff() -> dict[str, Any]:
    """Unified diff of every change this agent has made to the working copy."""
    chunks = []
    for rel, before in sorted(_baseline().items()):
        try:
            target = _resolve(rel)
        except ValueError:
            continue
        after = target.read_text(encoding="utf-8") if target.is_file() else ""
        if after == before:
            continue
        chunks.append(
            "".join(
                difflib.unified_diff(
                    before.splitlines(keepends=True),
                    after.splitlines(keepends=True),
                    fromfile="a/" + rel,
                    tofile="b/" + rel,
                )
            )
        )
    return ok(diff="\n".join(chunks) or "(working copy is clean)", changed=len(chunks))


@server.tool()
def repo_run_tests(command: str = "python -m pytest -q") -> dict[str, Any]:
    """Run the project's tests or a linter in the working copy.

    Only commands starting with one of: pytest, python, python3, npm, npx, ruff,
    mypy are permitted. Output is truncated to the last 6000 characters.
    """
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return err("could not parse command: " + str(exc))
    if not argv:
        return err("empty command")
    if argv[0] not in ALLOWED_COMMANDS:
        return err(
            "command '{}' is not allow-listed; permitted: {}".format(
                argv[0], ", ".join(sorted(ALLOWED_COMMANDS))
            )
        )
    try:
        proc = subprocess.run(
            argv,
            cwd=WORKSPACE,
            capture_output=True,
            text=True,
            timeout=TEST_TIMEOUT_SECONDS,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return err("command timed out after {}s".format(TEST_TIMEOUT_SECONDS))
    except FileNotFoundError:
        return err("executable not found: " + argv[0])
    output = (proc.stdout + proc.stderr)[-6000:]
    return ok(command=command, exit_code=proc.returncode, passed=proc.returncode == 0,
              output=output)


if __name__ == "__main__":
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    server.run()
