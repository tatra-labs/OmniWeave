"""`bench/serve/`'s one option: `--tasks`, which 16-roadmap.md:745's P7 exit command passes.

`uv run pytest bench/serve -q --tasks all` is the command. `none` (the default) runs the harness's
own tests and no task; `all` runs every catalogue task; a comma-separated list runs those ids. A
task run needs the scripted agent, which W7.7a does not ship, so a run that selects tasks is where
that absence is reported (`test_harness.py`).
"""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--tasks",
        default="none",
        help="bench/serve tasks to run: none (default), all, or comma-separated task ids",
    )
