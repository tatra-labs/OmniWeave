"""`python -m omniweave install | uninstall` as a child process: the cycle a user types, measured.

This is the first cell in which `ow install` can be typed at all (D467): the rows exist, the
generated parser carries the flags, and `__main__` dispatches the two roots. The child gets a
scratch `HOME`, `USERPROFILE` and `OMNIWEAVE_HOME` and an empty piped stdin, which is the
detached run a script or a CI job makes. The null-device stdin that found D472 is the unit test's.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from omniweave_core.host.subproc import Captured, run_captured

pytestmark = pytest.mark.conform

#  Named, not `auto`: the child inherits this machine's PATH, which has `cursor` on it (D479).
CHECK = ("install", "--check", "--target", "claude-code")


def _tree(root: Path) -> dict[str, bytes | None]:
    return {
        one.relative_to(root).as_posix(): (one.read_bytes() if one.is_file() else None)
        for one in sorted(root.rglob("*"))
    }


def _ow(tmp: Path, *args: str) -> Captured:
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    home = tmp / "home"
    env.update(HOME=str(home), USERPROFILE=str(home), OMNIWEAVE_HOME=str(tmp / "owhome"))
    argv = [sys.executable, "-m", "omniweave", *args]
    return run_captured(argv, stdin=b"", cwd=str(tmp / "proj"), env=env, timeout_s=120)


def test_install_check_uninstall_from_argv_leave_the_home_as_it_was(tmp_path: Path) -> None:
    (tmp_path / "home").mkdir()
    (tmp_path / "proj").mkdir()
    before = _tree(tmp_path / "home")
    install = ["install", "--target", "claude-code", "--location", "global", "--hooks", "context"]

    refused = _ow(tmp_path, "install", "--target", "auto")
    assert refused.returncode == 1
    assert b"--hooks and --skills have no default" in refused.stdout

    detached = _ow(tmp_path, *install, "--skills", "none")
    assert detached.returncode == 1, detached
    assert b"Write this plan?" not in detached.stdout
    assert _tree(tmp_path / "home") == before

    assert _ow(tmp_path, *CHECK).returncode == 9
    wrote = _ow(tmp_path, *install, "--skills", "none", "--yes")
    assert wrote.returncode == 0, wrote
    assert "wrote 4 entries · receipt".encode() in wrote.stdout
    checked = _ow(tmp_path, *CHECK)
    assert checked.returncode == 0, checked
    assert checked.stdout.decode("utf-8").startswith("claude-code global   configured    mcp ok")

    unasked = _ow(tmp_path, "uninstall", "--yes")
    assert unasked.returncode == 1
    assert b"there is no terminal to ask on" in unasked.stdout
    removed = _ow(tmp_path, "uninstall", "--location", "global", "--yes")
    assert removed.returncode == 0, removed
    assert _ow(tmp_path, *CHECK).returncode == 9
    assert _tree(tmp_path / "home") == before


def test_the_output_is_utf_8_into_a_pipe(tmp_path: Path) -> None:
    """Measured two cells ago: into a pipe, Python on Windows writes cp1252 by default."""
    (tmp_path / "home").mkdir()
    (tmp_path / "proj").mkdir()
    done = _ow(tmp_path, "install", "--target", "claude-code", "--location", "global",
               "--hooks", "none", "--skills", "none", "--yes")  # fmt: skip
    assert done.returncode == 0, done
    assert "·".encode() in done.stdout
    done.stdout.decode("utf-8")


def test_an_undispatched_root_still_names_what_is(tmp_path: Path) -> None:
    (tmp_path / "home").mkdir()
    (tmp_path / "proj").mkdir()
    #  `serve` was the example until W7.3p dispatched it; `query` is still refused (no retrieve()).
    refused = _ow(tmp_path, "query", "what is indexed")
    assert refused.returncode == 70
    named = b"only `ow hook`, `ow hooks`, `ow install`, `ow serve`, `ow skills`, `ow uninstall` are"
    assert named in refused.stderr


def test_hooks_check_runs_the_installed_hooks_the_receipt_names(tmp_path: Path) -> None:
    """10:2078, from argv: the six commands read back from the file the receipt names, run."""
    (tmp_path / "home").mkdir()
    (tmp_path / "proj").mkdir()
    assert _ow(tmp_path, "hooks", "check").returncode == 1
    installed = _ow(tmp_path, "install", "--target", "claude-code", "--location", "global",
                    "--hooks", "steer", "--skills", "none", "--yes")  # fmt: skip
    assert installed.returncode == 0, installed
    checked = _ow(tmp_path, "hooks", "check")
    #  Text-mode stdout on Windows writes CRLF, as every Python CLI there does.
    text = checked.stdout.decode("utf-8").replace("\r\n", "\n")
    assert checked.returncode == 0, text + checked.stderr.decode("utf-8", "replace")
    assert text.startswith("claude-code global  ~/.claude/settings.json\n")
    assert text.count("resolved · exit 0") == 6
