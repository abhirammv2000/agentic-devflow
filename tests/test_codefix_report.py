"""The report's statistics, checked against values worked out by hand."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evals.codefix.report import build, sign_test, wilson  # noqa: E402


def test_wilson_interval_known_values():
    lo, hi = wilson(0, 10)
    assert lo == 0.0 and abs(hi - 0.2775) < 0.001
    lo, hi = wilson(5, 10)
    assert abs(lo - 0.2366) < 0.001 and abs(hi - 0.7634) < 0.001
    assert wilson(0, 0) == (0.0, 0.0)


def test_wilson_interval_gets_narrower_with_more_data():
    narrow = wilson(50, 100)
    wide = wilson(5, 10)
    assert narrow[1] - narrow[0] < wide[1] - wide[0]


def test_sign_test():
    assert sign_test(0, 0) == 1.0
    assert abs(sign_test(5, 0) - 0.0625) < 1e-9      # 2 * (1/32)
    assert abs(sign_test(3, 3) - 1.0) < 1e-9
    assert abs(sign_test(8, 2) - 0.109375) < 1e-9    # 2 * (1 + 10 + 45) / 1024


def row(task, variant, solved, **extra):
    base = {
        "task": task, "variant": variant, "model": "test:model", "status": "completed", "solved": solved,
        "seconds": 10.0, "tool_calls": 4, "input_tokens": 1000, "output_tokens": 100,
        "tested_before_editing": True, "tests_modified": [], "denied_calls": 0, "malformed_calls": 0,
        "other_files_changed": [], "wrote_without_reading": 0, "repeat": 0,
    }
    base.update(extra)
    return base


def test_report_counts_and_flags():
    rows = [
        row("a", "fix_plain", False), row("b", "fix_plain", False), row("c", "fix_plain", True),
        row("a", "fix_tdd", True), row("b", "fix_tdd", True, tests_modified=["tests/test_b.py"]), row("c", "fix_tdd", True),
    ]
    text = build(rows)

    assert "| fix_plain | 1/3 (33%)" in text
    assert "| fix_tdd | 3/3 (100%)" in text
    assert "| fix_tdd against fix_plain | 2 | 0 | 1 |" in text
    assert "Attempts that edited an existing test: 1 of 6 (1 of those still passed the hidden tests)" in text
    assert "| a | 0/1 | 1/1 |" in text


def test_report_describes_unsolved_attempts():
    rows = [row("a", "fix_plain", False, status="failed"), row("b", "fix_plain", False)]
    text = build(rows)
    assert "- failed: 1" in text
    assert "- finished but wrong: 1" in text
