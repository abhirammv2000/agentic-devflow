"""MCP server exposing Jira ticketing operations.

Run standalone:  python -m mcp_servers.jira_server   (stdio transport)
"""

from __future__ import annotations

from typing import Any

from mcp.server import MCPServer

from .backends import MOCK, adf, err, jira_client, ok, store

server = MCPServer("devflow-jira")

WORKFLOW = ["To Do", "In Progress", "In Review", "Done"]


@server.tool()
def jira_create_issue(
    project: str,
    summary: str,
    description: str,
    issue_type: str = "Task",
    priority: str = "Medium",
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """Create a Jira ticket.

    Args:
        project: project key, e.g. "OPS" or "ENG".
        issue_type: "Bug", "Task" or "Story".
        priority: "Highest", "High", "Medium", "Low".
    """
    if MOCK:
        def _do(state):
            counters = state["jira"]["next"]
            n = counters.get(project, 1)
            counters[project] = n + 1
            key = "{}-{}".format(project, n)
            state["jira"]["issues"][key] = {
                "key": key,
                "project": project,
                "summary": summary,
                "description": description,
                "type": issue_type,
                "priority": priority,
                "labels": labels or [],
                "status": "To Do",
                "comments": [],
                "links": [],
            }
            return ok(key=key, status="To Do")
        return store.mutate(_do)
    with jira_client() as c:
        fields: dict[str, Any] = {
            "project": {"key": project},
            "summary": summary,
            "description": adf(description),
            "issuetype": {"name": issue_type},
            "priority": {"name": priority},
        }
        if labels:
            fields["labels"] = labels
        resp = c.post("/issue", json={"fields": fields})
        resp.raise_for_status()
        return ok(key=resp.json()["key"])


@server.tool()
def jira_get_issue(key: str) -> dict[str, Any]:
    """Fetch a Jira ticket by key, e.g. "ENG-14"."""
    if MOCK:
        issue = store.read()["jira"]["issues"].get(key)
        if issue is None:
            return err("no such Jira issue: " + key)
        return ok(issue=issue)
    with jira_client() as c:
        resp = c.get("/issue/" + key)
        if resp.status_code == 404:
            return err("no such Jira issue: " + key)
        resp.raise_for_status()
        f = resp.json()["fields"]
        return ok(issue={
            "key": key,
            "summary": f.get("summary"),
            "status": (f.get("status") or {}).get("name"),
            "type": (f.get("issuetype") or {}).get("name"),
            "priority": (f.get("priority") or {}).get("name"),
            "labels": f.get("labels", []),
            "description": _flatten_adf(f.get("description")),
        })


@server.tool()
def jira_search(text: str = "", status: str = "", project: str = "") -> dict[str, Any]:
    """Find tickets by free text, status and/or project key.

    In live mode this is translated to JQL; in mock mode it filters the local store.
    """
    if MOCK:
        results = []
        for issue in store.read()["jira"]["issues"].values():
            if project and issue["project"] != project:
                continue
            if status and issue["status"] != status:
                continue
            haystack = (issue["summary"] + " " + issue["description"]).lower()
            if text and text.lower() not in haystack:
                continue
            results.append(
                {k: issue[k] for k in ("key", "summary", "status", "priority", "type")}
            )
        return ok(issues=results)
    clauses = []
    if project:
        clauses.append('project = "{}"'.format(project))
    if status:
        clauses.append('status = "{}"'.format(status))
    if text:
        clauses.append('text ~ "{}"'.format(text.replace('"', "")))
    jql = " AND ".join(clauses) or "order by created DESC"
    with jira_client() as c:
        resp = c.get("/search", params={"jql": jql, "maxResults": 25})
        resp.raise_for_status()
        return ok(issues=[
            {
                "key": i["key"],
                "summary": i["fields"].get("summary"),
                "status": (i["fields"].get("status") or {}).get("name"),
            }
            for i in resp.json().get("issues", [])
        ])


@server.tool()
def jira_comment(key: str, body: str) -> dict[str, Any]:
    """Add a comment to a Jira ticket."""
    if MOCK:
        def _do(state):
            issue = state["jira"]["issues"].get(key)
            if issue is None:
                return err("no such Jira issue: " + key)
            issue["comments"].append({"author": "devflow-agent", "body": body})
            return ok(commented_on=key)
        return store.mutate(_do)
    with jira_client() as c:
        resp = c.post("/issue/{}/comment".format(key), json={"body": adf(body)})
        resp.raise_for_status()
        return ok(commented_on=key)


@server.tool()
def jira_transition(key: str, to_status: str) -> dict[str, Any]:
    """Move a ticket to another workflow status, e.g. "In Progress" or "Done"."""
    if MOCK:
        def _do(state):
            issue = state["jira"]["issues"].get(key)
            if issue is None:
                return err("no such Jira issue: " + key)
            if to_status not in WORKFLOW:
                return err("status must be one of " + ", ".join(WORKFLOW))
            issue["status"] = to_status
            return ok(key=key, status=to_status)
        return store.mutate(_do)
    with jira_client() as c:
        available = c.get("/issue/{}/transitions".format(key))
        available.raise_for_status()
        match = next(
            (
                t
                for t in available.json()["transitions"]
                if t["to"]["name"].lower() == to_status.lower()
            ),
            None,
        )
        if match is None:
            names = [t["to"]["name"] for t in available.json()["transitions"]]
            return err(
                "no transition to '{}' from the current status; available: {}".format(
                    to_status, ", ".join(names)
                )
            )
        resp = c.post(
            "/issue/{}/transitions".format(key), json={"transition": {"id": match["id"]}}
        )
        resp.raise_for_status()
        return ok(key=key, status=to_status)


@server.tool()
def jira_link_pull_request(key: str, url: str, title: str = "") -> dict[str, Any]:
    """Attach a pull request URL to a ticket as a remote link."""
    if MOCK:
        def _do(state):
            issue = state["jira"]["issues"].get(key)
            if issue is None:
                return err("no such Jira issue: " + key)
            issue["links"].append({"url": url, "title": title or url})
            return ok(key=key, linked=url)
        return store.mutate(_do)
    with jira_client() as c:
        resp = c.post(
            "/issue/{}/remotelink".format(key),
            json={"object": {"url": url, "title": title or url}},
        )
        resp.raise_for_status()
        return ok(key=key, linked=url)


def _flatten_adf(node: Any) -> str:
    """Best-effort ADF -> plain text, so Claude reads descriptions as prose."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        if node.get("type") == "text":
            return node.get("text", "")
        return "".join(_flatten_adf(child) for child in node.get("content", []))
    if isinstance(node, list):
        return "".join(_flatten_adf(child) for child in node)
    return ""


if __name__ == "__main__":
    server.run()
