"""Turn the test-writing attempts file into a report.

    python -m evals.testgen.report evals/results/testgen_ollama_qwen2.5-coder_7b.jsonl

The headline number is the mean kill rate over all attempts, where an attempt with invalid tests (they fail on the
correct module, or there are none) counts as 0. Reporting only the valid ones would flatter a model that often
writes broken tests.
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ORDER = ["write_plain", "write_method"]


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build(rows: list[dict]) -> str:
    model = rows[0].get("model", "unknown") if rows else "unknown"
    variants = [v for v in ORDER if any(r["variant"] == v for r in rows)]
    tasks = sorted({r["task"] for r in rows})
    out = [f"# Test-writing benchmark: {model}", "",
           f"{len(rows)} attempts on {len(tasks)} modules. Kill rate is the share of deliberately broken versions of the "
           "module that at least one of the agent's tests fails on. Tests that fail on the correct module, or are missing, "
           "score 0.", "",
           "| set-up | attempts | valid tests | mean kill rate | mean tests | mean assertions | seconds (mean) | tokens (mean) |",
           "|---|---|---|---|---|---|---|---|"]
    for v in variants:
        g = [r for r in rows if r["variant"] == v]
        out.append(
            f"| {v} | {len(g)} | {sum(r['valid'] for r in g)}/{len(g)} | {statistics.mean(r['kill_rate'] for r in g):.0%} "
            f"| {statistics.mean(r['tests'] for r in g):.1f} | {statistics.mean(r['assertions'] for r in g):.1f} "
            f"| {statistics.mean(r['seconds'] for r in g):.0f} "
            f"| {statistics.mean(r['input_tokens'] + r['output_tokens'] for r in g):,.0f} |"
        )

    out += ["", "## By module", "", "Kill rate, with the number of mutants in brackets.", "",
            "| module | " + " | ".join(variants) + " |", "|---|" + "---|" * len(variants)]
    cell = defaultdict(list)
    mutants = {}
    for r in rows:
        cell[(r["task"], r["variant"])].append(r["kill_rate"] if r["valid"] else 0.0)
        mutants[r["task"]] = r["mutants"]
    for t in tasks:
        cells = [f"{statistics.mean(cell[(t, v)]):.0%}" if cell[(t, v)] else "-" for v in variants]
        out.append(f"| {t} ({mutants[t]}) | " + " | ".join(cells) + " |")

    invalid = Counter(r["why_invalid"] for r in rows if not r["valid"])
    if invalid:
        out += ["", "## Why tests were invalid", ""] + [f"- {k or 'unknown'}: {v}" for k, v in invalid.most_common()]
    survivors = Counter(s for r in rows if r["valid"] for s in r["survivors"])
    if survivors:
        out += ["", "## Bugs the tests most often missed", ""]
        out += [f"- {name}: survived {n} times" for name, n in survivors.most_common(8)]
    out += ["", "## Behaviour", "",
            f"- Attempts that changed the module under test: {sum(r['src_modified'] for r in rows)} (their edits were thrown away before grading).",
            f"- Attempts that ran their tests at least once: {sum(r['ran_tests'] > 0 for r in rows)} of {len(rows)}."]
    return "\n".join(out) + "\n"


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: python -m evals.testgen.report <attempts.jsonl>")
    path = Path(sys.argv[1])
    rows = load(path)
    if not rows:
        sys.exit("no attempts in " + str(path))
    text = build(rows)
    path.with_suffix(".md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
