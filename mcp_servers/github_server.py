"""MCP server exposing the GitHub operations the dev-flow agent is allowed to perform.

Run standalone:  python -m mcp_servers.github_server   (stdio transport)
"""

from __future__ import annotations

import base64
import difflib
from typing import Any

from mcp.server import MCPServer

from .backends import MOCK, err, github_client, ok, store

server = MCPServer("devflow-github")


def _repo(state: dict[str, Any], repo: str) -> dict[str, Any] | None:
    return state["github"]["repos"].get(repo)


# --------------------------------------------------------------------------
# read
# --------------------------------------------------------------------------

@server.tool()
def gh_list_issues(repo: str, state: str = "open") -> dict[str, Any]:
    """List issues in a GitHub repository.

    Args:
        repo: "owner/name", e.g. "acme/checkout-service".
        state: "open", "closed" or "all".
    """
    if MOCK:
        r = _repo(store.read(), repo)
        if r is None:
            return err("unknown repo " + repo)
        issues = [
            {k: i[k] for k in ("number", "title", "state", "labels", "author")}
            for i in r["issues"].values()
            if state == "all" or i["state"] == state
        ]
        return ok(issues=issues)
    with github_client() as c:
        resp = c.get("/repos/" + repo + "/issues", params={"state": state})
        resp.raise_for_status()
        return ok(issues=[
            {
                "number": i["number"],
                "title": i["title"],
                "state": i["state"],
                "labels": [lbl["name"] for lbl in i.get("labels", [])],
                "author": i["user"]["login"],
            }
            for i in resp.json()
            if "pull_request" not in i
        ])


@server.tool()
def gh_get_issue(repo: str, number: int) -> dict[str, Any]:
    """Fetch a single issue including its body and comment thread."""
    if MOCK:
        r = _repo(store.read(), repo)
        if r is None or str(number) not in r["issues"]:
            return err("issue not found: {}#{}".format(repo, number))
        return ok(issue=r["issues"][str(number)])
    with github_client() as c:
        issue = c.get("/repos/{}/issues/{}".format(repo, number))
        issue.raise_for_status()
        comments = c.get("/repos/{}/issues/{}/comments".format(repo, number))
        comments.raise_for_status()
        i = issue.json()
        return ok(issue={
            "number": i["number"],
            "title": i["title"],
            "body": i.get("body") or "",
            "state": i["state"],
            "labels": [lbl["name"] for lbl in i.get("labels", [])],
            "author": i["user"]["login"],
            "comments": [
                {"author": cm["user"]["login"], "body": cm["body"]}
                for cm in comments.json()
            ],
        })


@server.tool()
def gh_get_file(repo: str, path: str, ref: str = "") -> dict[str, Any]:
    """Read a file from the repository at a given branch or commit ref."""
    if MOCK:
        r = _repo(store.read(), repo)
        if r is None:
            return err("unknown repo " + repo)
        if path not in r["files"]:
            return err("{} not found in {}".format(path, repo))
        return ok(path=path, content=r["files"][path])
    with github_client() as c:
        params = {"ref": ref} if ref else {}
        resp = c.get("/repos/{}/contents/{}".format(repo, path), params=params)
        if resp.status_code == 404:
            return err("{} not found in {}".format(path, repo))
        resp.raise_for_status()
        payload = resp.json()
        return ok(
            path=path,
            sha=payload["sha"],
            content=base64.b64decode(payload["content"]).decode("utf-8", "replace"),
        )


@server.tool()
def gh_get_pull_request(repo: str, number: int) -> dict[str, Any]:
    """Fetch a pull request's metadata and unified diff -- the input to a code review."""
    if MOCK:
        r = _repo(store.read(), repo)
        if r is None or str(number) not in r["pulls"]:
            return err("PR not found: {}#{}".format(repo, number))
        return ok(pull_request=r["pulls"][str(number)])
    with github_client() as c:
        pr = c.get("/repos/{}/pulls/{}".format(repo, number))
        pr.raise_for_status()
        diff = c.get(
            "/repos/{}/pulls/{}".format(repo, number),
            headers={"Accept": "application/vnd.github.v3.diff"},
        )
        diff.raise_for_status()
        p = pr.json()
        return ok(pull_request={
            "number": p["number"],
            "title": p["title"],
            "body": p.get("body") or "",
            "head": p["head"]["ref"],
            "base": p["base"]["ref"],
            "state": p["state"],
            "diff": diff.text,
        })


# --------------------------------------------------------------------------
# write
# --------------------------------------------------------------------------

@server.tool()
def gh_comment_issue(repo: str, number: int, body: str) -> dict[str, Any]:
    """Post a comment on an issue or pull request."""
    if MOCK:
        def _do(state):
            r = _repo(state, repo)
            if r is None:
                return err("unknown repo " + repo)
            target = r["issues"].get(str(number)) or r["pulls"].get(str(number))
            if target is None:
                return err("{}#{} not found".format(repo, number))
            target.setdefault("comments", []).append(
                {"author": "devflow-agent", "body": body}
            )
            return ok(commented_on="{}#{}".format(repo, number))
        return store.mutate(_do)
    with github_client() as c:
        resp = c.post(
            "/repos/{}/issues/{}/comments".format(repo, number), json={"body": body}
        )
        resp.raise_for_status()
        return ok(commented_on="{}#{}".format(repo, number), url=resp.json()["html_url"])


@server.tool()
def gh_set_labels(repo: str, number: int, labels: list[str]) -> dict[str, Any]:
    """Replace the label set on an issue (used by the triage playbook)."""
    if MOCK:
        def _do(state):
            r = _repo(state, repo)
            if r is None or str(number) not in r["issues"]:
                return err("issue not found: {}#{}".format(repo, number))
            r["issues"][str(number)]["labels"] = labels
            return ok(labels=labels)
        return store.mutate(_do)
    with github_client() as c:
        resp = c.put(
            "/repos/{}/issues/{}/labels".format(repo, number), json={"labels": labels}
        )
        resp.raise_for_status()
        return ok(labels=[lbl["name"] for lbl in resp.json()])


@server.tool()
def gh_create_branch(repo: str, name: str, base: str = "") -> dict[str, Any]:
    """Create a new branch off base (defaults to the repository's default branch)."""
    if MOCK:
        def _do(state):
            r = _repo(state, repo)
            if r is None:
                return err("unknown repo " + repo)
            src = base or r["default_branch"]
            if src not in r["branches"]:
                return err("base branch {} does not exist".format(src))
            if name in r["branches"]:
                return err("branch {} already exists".format(name))
            r["branches"][name] = {"sha": r["branches"][src]["sha"], "from": src}
            return ok(branch=name, base=src)
        return store.mutate(_do)
    with github_client() as c:
        target_base = base
        if not target_base:
            repo_info = c.get("/repos/" + repo)
            repo_info.raise_for_status()
            target_base = repo_info.json()["default_branch"]
        ref = c.get("/repos/{}/git/ref/heads/{}".format(repo, target_base))
        ref.raise_for_status()
        resp = c.post(
            "/repos/{}/git/refs".format(repo),
            json={"ref": "refs/heads/" + name, "sha": ref.json()["object"]["sha"]},
        )
        resp.raise_for_status()
        return ok(branch=name, base=target_base)


@server.tool()
def gh_commit_file(
    repo: str, branch: str, path: str, content: str, message: str
) -> dict[str, Any]:
    """Create or update a single file on a branch and commit it.

    Returns the unified diff that was applied, so the change is visible in the
    run's audit trail without a second round trip.
    """
    if MOCK:
        def _do(state):
            r = _repo(state, repo)
            if r is None:
                return err("unknown repo " + repo)
            if branch not in r["branches"]:
                return err(
                    "branch {} does not exist; call gh_create_branch first".format(branch)
                )
            before = r["files"].get(path, "")
            r["files"][path] = content
            r["branches"][branch]["sha"] = "mock{}".format(abs(hash(content)) % 10 ** 7)
            diff = "".join(
                difflib.unified_diff(
                    before.splitlines(keepends=True),
                    content.splitlines(keepends=True),
                    fromfile="a/" + path,
                    tofile="b/" + path,
                )
            )
            return ok(path=path, branch=branch, message=message, diff=diff)
        return store.mutate(_do)
    with github_client() as c:
        existing = c.get(
            "/repos/{}/contents/{}".format(repo, path), params={"ref": branch}
        )
        payload: dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(content.encode()).decode(),
            "branch": branch,
        }
        if existing.status_code == 200:
            payload["sha"] = existing.json()["sha"]
        resp = c.put("/repos/{}/contents/{}".format(repo, path), json=payload)
        resp.raise_for_status()
        return ok(path=path, branch=branch, commit=resp.json()["commit"]["sha"])


@server.tool()
def gh_open_pull_request(
    repo: str, head: str, title: str, body: str, base: str = ""
) -> dict[str, Any]:
    """Open a pull request from head into base (default branch when omitted)."""
    if MOCK:
        def _do(state):
            r = _repo(state, repo)
            if r is None:
                return err("unknown repo " + repo)
            if head not in r["branches"]:
                return err("branch {} does not exist".format(head))
            number = state["github"]["next_pr"]
            state["github"]["next_pr"] += 1
            target = base or r["default_branch"]
            r["pulls"][str(number)] = {
                "number": number,
                "title": title,
                "body": body,
                "head": head,
                "base": target,
                "state": "open",
                "merged": False,
                "reviews": [],
                "comments": [],
                "diff": _synthetic_diff(r, head),
            }
            return ok(
                pull_request=number,
                url="https://github.com/{}/pull/{}".format(repo, number),
                head=head,
                base=target,
            )
        return store.mutate(_do)
    with github_client() as c:
        target = base
        if not target:
            repo_info = c.get("/repos/" + repo)
            repo_info.raise_for_status()
            target = repo_info.json()["default_branch"]
        resp = c.post(
            "/repos/{}/pulls".format(repo),
            json={"title": title, "body": body, "head": head, "base": target},
        )
        resp.raise_for_status()
        p = resp.json()
        return ok(pull_request=p["number"], url=p["html_url"], head=head, base=target)


def _synthetic_diff(repo_state: dict[str, Any], branch: str) -> str:
    """Mock mode has no real git history, so record the branch tip's file set."""
    return "\n".join(
        "--- a/{p}\n+++ b/{p}".format(p=p) for p in sorted(repo_state["files"])
    )


@server.tool()
def gh_review_pull_request(repo: str, number: int, event: str, body: str) -> dict[str, Any]:
    """Submit a pull request review.

    Args:
        event: "COMMENT", "APPROVE" or "REQUEST_CHANGES".
    """
    if event not in {"COMMENT", "APPROVE", "REQUEST_CHANGES"}:
        return err("event must be COMMENT, APPROVE or REQUEST_CHANGES")
    if MOCK:
        def _do(state):
            r = _repo(state, repo)
            if r is None or str(number) not in r["pulls"]:
                return err("PR not found: {}#{}".format(repo, number))
            r["pulls"][str(number)]["reviews"].append(
                {"reviewer": "devflow-agent", "event": event, "body": body}
            )
            return ok(reviewed="{}#{}".format(repo, number), event=event)
        return store.mutate(_do)
    with github_client() as c:
        resp = c.post(
            "/repos/{}/pulls/{}/reviews".format(repo, number),
            json={"event": event, "body": body},
        )
        resp.raise_for_status()
        return ok(reviewed="{}#{}".format(repo, number), event=event)


@server.tool()
def gh_merge_pull_request(repo: str, number: int, method: str = "squash") -> dict[str, Any]:
    """Merge a pull request. Irreversible -- always gated behind human approval."""
    if MOCK:
        def _do(state):
            r = _repo(state, repo)
            if r is None or str(number) not in r["pulls"]:
                return err("PR not found: {}#{}".format(repo, number))
            pr = r["pulls"][str(number)]
            pr["state"] = "closed"
            pr["merged"] = True
            return ok(merged="{}#{}".format(repo, number), method=method)
        return store.mutate(_do)
    with github_client() as c:
        resp = c.put(
            "/repos/{}/pulls/{}/merge".format(repo, number),
            json={"merge_method": method},
        )
        resp.raise_for_status()
        return ok(merged="{}#{}".format(repo, number), method=method)


if __name__ == "__main__":
    server.run()
