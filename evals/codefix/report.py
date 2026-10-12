"""Turn the attempts file into a report.

    python -m evals.codefix.report evals/results/codefix_ollama_qwen2.5-coder_7b.jsonl

With the number of tasks and repeats this benchmark has, intervals are wide, and the report says so instead of
ranking set-ups on a difference the data cannot support. Two comparisons are given: the pass rate with a Wilson
interval for each set-up, and a paired sign test across tasks, which asks whether one set-up solved more tasks
than another on the tasks where they differed.
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ORDER = ["fix_plain", "fix_tdd", "fix_context"]


def wilson(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = wins / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def sign_test(better: int, worse: int) -> float:
    """Two-sided exact p-value that the split of the differing tasks is a fair coin."""
    n = better + worse
    if n == 0:
        return 1.0
    k = min(better, worse)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def pct(x: float) -> str:
    return f"{x:.0%}"


def build(rows: list[dict]) -> str:
    model = rows[0].get("model", "unknown") if rows else "unknown"
    variants = [v for v in ORDER if any(r["variant"] == v for r in rows)]
    tasks = sorted({r["task"] for r in rows})
    out: list[str] = [f"# Code-fix benchmark: {model}", ""]

    out += [f"{len(rows)} attempts, {len(tasks)} tasks, {len(variants)} set-ups. A task counts as solved only when "
            "every hidden test passes.", "",
            "| set-up | solved | 95% interval | seconds (mean) | tool calls (mean) | tokens (mean) | tested before editing | edited existing tests |",
            "|---|---|---|---|---|---|---|---|"]
    for v in variants:
        group = [r for r in rows if r["variant"] == v]
        wins = sum(r["solved"] for r in group)
        lo, hi = wilson(wins, len(group))
        out.append(
            f"| {v} | {wins}/{len(group)} ({pct(wins / len(group))}) | {pct(lo)} to {pct(hi)} "
            f"| {statistics.mean(r['seconds'] for r in group):.0f} | {statistics.mean(r['tool_calls'] for r in group):.1f} "
            f"| {statistics.mean(r['input_tokens'] + r['output_tokens'] for r in group):,.0f} "
            f"| {pct(sum(r['tested_before_editing'] for r in group) / len(group))} "
            f"| {pct(sum(bool(r['tests_modified']) for r in group) / len(group))} |"
        )

    out += ["", "## By task", "", "Solved attempts out of the repeats for each task.", "",
            "| task | " + " | ".join(variants) + " |", "|---|" + "---|" * len(variants)]
    by = defaultdict(list)
    for r in rows:
        by[(r["task"], r["variant"])].append(r["solved"])
    for t in tasks:
        cells = [f"{sum(by[(t, v)])}/{len(by[(t, v)])}" if by[(t, v)] else "-" for v in variants]
        out.append(f"| {t} | " + " | ".join(cells) + " |")

    out += ["", "## Comparing set-ups", "",
            "Each task gets a solve rate per set-up (solved attempts over repeats). The sign test counts the tasks "
            "where one set-up has the higher rate and ignores ties.", "",
            "| comparison | tasks better | tasks worse | tied | sign test p |", "|---|---|---|---|---|"]
    rate = {k: sum(v) / len(v) for k, v in by.items()}
    for i, a in enumerate(variants):
        for b in variants[i + 1:]:
            better = sum(1 for t in tasks if rate.get((t, b), 0) > rate.get((t, a), 0))
            worse = sum(1 for t in tasks if rate.get((t, b), 0) < rate.get((t, a), 0))
            tied = len(tasks) - better - worse
            out.append(f"| {b} against {a} | {better} | {worse} | {tied} | {sign_test(better, worse):.2f} |")

    failures = defaultdict(int)
    for r in rows:
        if not r["solved"]:
            failures[r["status"] if r["status"] != "completed" else "finished but wrong"] += 1
    if failures:
        out += ["", "## How the unsolved attempts ended", ""]
        out += [f"- {k}: {v}" for k, v in sorted(failures.items(), key=lambda kv: -kv[1])]

    cheats = [r for r in rows if r["tests_modified"]]
    safety = sum(r["denied_calls"] + r["malformed_calls"] for r in rows)
    out += ["", "## Safety and behaviour", "",
            f"- Attempts that edited an existing test: {len(cheats)} of {len(rows)} "
            f"({sum(bool(r['solved']) for r in cheats)} of those still passed the hidden tests).",
            f"- Calls outside the playbook's tools or malformed: {safety} across all attempts.",
            f"- Edits to files outside src/ and tests/: {sum(bool(r['other_files_changed']) for r in rows)} attempts.",
            f"- Wrote a source file without reading it first: {sum(r['wrote_without_reading'] > 0 for r in rows)} attempts.",
            f"- Total tokens: {sum(r['input_tokens'] + r['output_tokens'] for r in rows):,}. "
            f"Total model time: {sum(r['seconds'] for r in rows) / 3600:.1f} hours."]
    return "\n".join(out) + "\n"


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: python -m evals.codefix.report <attempts.jsonl>")
    path = Path(sys.argv[1])
    rows = load(path)
    if not rows:
        sys.exit("no attempts in " + str(path))
    text = build(rows)
    path.with_suffix(".md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
