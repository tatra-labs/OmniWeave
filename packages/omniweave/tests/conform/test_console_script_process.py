"""The `ow` and `omniweave` console scripts, run as the installed executables. 18:874; D619.

`conform` because it starts processes (13-quality.md section 2.7). The scripts are what
`pyproject.toml`'s `[project.scripts]` installs, so this test finds them the way a shell and G10
do, with `shutil.which()`, and skips with the reason when this environment was synced without the
`omniweave` distribution's entry points (a `uv sync` older than W7.8l's pyproject).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from omniweave_core.contract import RELEASE
from omniweave_core.host.subproc import Captured, run_captured

pytestmark = pytest.mark.conform

TIMEOUT_S = 60


def _script(name: str, *args: str) -> Captured:
    found = shutil.which(name)
    if found is None:
        pytest.skip(f"{name!r} is not on PATH: re-sync the environment to install the script")
    return run_captured(
        (found, *args), stdin=b"", cwd=str(Path.cwd()), env=dict(os.environ), timeout_s=TIMEOUT_S
    )


def test_ow_and_omniweave_are_one_script_printing_one_version_line() -> None:
    """18:874: *"`ow` and `omniweave` are the same console script; there is no other alias."*"""
    ow = _script("ow", "--version")
    omniweave = _script("omniweave", "--version")
    assert (ow.returncode, omniweave.returncode) == (0, 0)
    assert ow.stdout == omniweave.stdout
    assert ow.stdout.decode("ascii").startswith(f"omniweave {RELEASE}  contract ")


def test_the_script_dispatches_a_root_and_refuses_a_word_that_is_not_one() -> None:
    assert _script("ow", "explain", "OW-A-013").returncode == 0
    refused = _script("ow", "frobnicate")
    assert refused.returncode == 1
    assert b"invalid choice: 'frobnicate'" in refused.stderr


def test_the_script_routes_a_global_flag_written_before_the_root() -> None:
    """D624: `ow --render json explain ...` reaches `explain`, as 18:887 says it may."""
    before = _script("ow", "--render", "json", "explain", "OW-A-013")
    after = _script("ow", "explain", "OW-A-013", "--render", "json")
    assert before.returncode == after.returncode == 0
    assert before.stdout == after.stdout
    assert before.stdout.startswith(b'{"schema": 1, "numeric": "OW-A-013"')
