"""The generated CLI module is a fixed point of `ruff format`. **D906.**

G25 byte-diffs `omniweave/cli/__init__.py` against `gen.cli_tree.render()`, and the file is linted
and formatted like any other, so a render the formatter would rewrite fails one gate or the other.
Until D906 the generator decided at 96 columns and ruff at 100, and a help string of the wrong
length broke it. Each case here goes through `ruff format` in a child, so the conform tier
(Q-G25).
"""

from __future__ import annotations

import os
import sys

import pytest
from omniweave.gen.cli_tree import _field_lines, render
from omniweave_core.host.subproc import run_captured

pytestmark = pytest.mark.conform

TIMEOUT_S = 120


def _formatted(source: str) -> str:
    done = run_captured(
        (sys.executable, "-m", "ruff", "format", "--config", "line-length=100", "-"),
        stdin=source.encode("utf-8"),
        cwd=".",
        env=dict(os.environ),
        timeout_s=TIMEOUT_S,
    )
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    return done.stdout.decode("utf-8")


def test_every_field_length_around_the_line_width_survives_the_formatter() -> None:
    lines = ["X = ("]
    for width in range(80, 230):
        room = width - len('        help="",')
        for text in (("word " * 60)[:room], "x" * room):
            lines += ["    f(", *_field_lines("help", text, "        "), "    ),"]
    source = "\n".join([*lines, ")"]) + "\n"
    assert _formatted(source) == source


def test_the_rendered_module_survives_the_formatter() -> None:
    source = render().decode("utf-8")
    assert _formatted(source) == source
