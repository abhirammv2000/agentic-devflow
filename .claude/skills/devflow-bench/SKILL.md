---
name: devflow-bench
description: Run, read or extend DevFlow's agent benchmarks (bug fixing graded by hidden tests, test writing graded by mutation). Use when asked to evaluate a model or a prompt change on DevFlow, add a benchmark task, or explain a result.
---

# DevFlow benchmarks

Two benchmarks live in `evals/`. Both run the real DevFlow engine and MCP repo tools on small Python projects and
grade the result by running code, never by reading what the model said.

| | `evals/codefix` | `evals/testgen` |
|---|---|---|
| Agent's job | fix a bug described in a ticket | write unit tests for a module |
| Graded by | hidden tests the agent never sees | how many deliberately broken copies of the module the tests catch |
| Set-ups compared | `fix_plain`, `fix_tdd`, `fix_context` | `write_plain`, `write_method` |

## Run one

1. Check the tasks are fair first: `python -m evals.codefix.validate` and `python -m evals.testgen.validate`.
2. Point DevFlow at a model, for example a local one: `DEVFLOW_PROVIDER=ollama DEVFLOW_MODEL=qwen2.5-coder:7b`.
   Ollama has to be running. Do not point this at a paid API unless the user says so; a full run is many calls.
3. `python -m evals.codefix.run` (or `evals.testgen.run`). Results append to `evals/results/<suite>_<model>.jsonl`.
   An interrupted run resumes. Attempts where the provider failed are not saved, on purpose.
4. `python -m evals.codefix.report evals/results/codefix_<model>.jsonl` writes a markdown report next to it.

An attempt on a 7B model on a CPU takes about 5 to 10 minutes, so a full run is hours. Do not run other heavy
jobs at the same time, because the latency column will be wrong.

## Reading a result

- Temperature is 0, so repeating an attempt gives almost the same answer. Repeats do not add statistical power.
  More tasks do.
- With 12 tasks the intervals are wide. The report gives a Wilson interval per set-up and a paired sign test.
  If the interval overlaps, say the data cannot separate the set-ups. Do not rank them.
- A solved task means every hidden test passed. If `tests_modified` is set the agent changed an existing test, which
  cannot help it because grading uses the hidden file.

## Add a task

Copy a folder under `evals/codefix/tasks/` (or `evals/testgen/tasks/`), then run the validator. A code-fix task needs a
ticket, a buggy repo with at least one failing visible test, a reference solution, and hidden tests that contain every
visible test. A test-writing task needs a module, mutants that each change behaviour, and reference tests that kill all
of them. The validator rejects a task where the bug is already fixed, the solution fails, or a mutant is not a real bug.
