"""D400 as a test: what 10:1913's append discipline actually does with N concurrent writers.

This file is `conform` rather than `unit` because it spawns processes, which is the tier rule
13-quality.md section 2.7 states and `pyproject.toml` repeats. Processes are not an implementation
detail here -- they are the whole claim. 10:1913 says a record cannot be split by *"an interleaved
append from a second server process"*, and a second process is the only thing that can test it.

**The assertion is about the instrument, not the platform.** On POSIX, `O_APPEND` makes the
offset-update-plus-write atomic and nothing is lost; on Windows the CRT emulates it as a seek plus a
write and records are silently overwritten. Both pass, because what is asserted is that whatever
went missing is *accounted for* -- by `gaps`, which this cell added for exactly this reason. A test
that asserted loss would fail on the platform the plan was written for, and a test that asserted no
loss would fail here and tell us nothing we did not already measure.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from omniweave.hooks.session import CONTROL_DIR, SESSIONS_DIR, read

NOW: int = 1_800_000_000_000_000_000
WRITERS: int = 4
EACH: int = 200

pytestmark = pytest.mark.conform


def _writer_script(tmp_path: Path) -> Path:
    """A child that appends `EACH` records with a caller-supplied `pid` and a dense `seq`.

    `pid` is passed rather than read from `os.getpid()` so the reader's per-writer spans are
    deterministic: what is under test is the file, not the operating system's pid allocator.
    """
    script = tmp_path / "writer.py"
    script.write_text(
        textwrap.dedent(f"""
            import sys
            from pathlib import Path

            sys.path[:0] = {json.dumps([str(Path(entry)) for entry in sys.path])}

            from omniweave.hooks.session import append

            root, writer = Path(sys.argv[1]), int(sys.argv[2])
            for index in range({EACH}):
                append(root, "k", {{"pad": "x" * 400}}, at_ns={NOW}, pid=writer, seq=index)
            """),
        encoding="utf-8",
    )
    return script


def test_concurrent_appends_are_either_intact_or_counted_and_never_silently_lost(
    tmp_path: Path,
) -> None:
    """The plan's own instrument reports zero while 23% of records disappear. This one does not.

    10:1912 gives the reader one defence -- *"skips and counts malformed lines"* -- and it is a
    defence against splitting. Measured on this machine at two writers: 138 of 600 records gone and
    **zero** malformed lines. `gaps` is what makes the difference between those two numbers a
    reading rather than a silence.
    """
    root = tmp_path / CONTROL_DIR / SESSIONS_DIR
    root.mkdir(parents=True)
    script = _writer_script(tmp_path)

    children = [
        subprocess.Popen([sys.executable, str(script), str(root), str(writer)])  # noqa: S603
        for writer in range(WRITERS)
    ]
    for child in children:
        child.wait()

    journal = read(root, "k", now_ns=NOW)
    offered = WRITERS * EACH
    missing = offered - len(journal.records)

    assert all(child.returncode == 0 for child in children)
    assert missing >= 0
    #  Every writer's last record can be lost invisibly -- a gap needs a survivor on both sides --
    #  so the accounted-for figure is allowed to fall short by at most one record per writer.
    assert journal.gaps + journal.skipped + WRITERS >= missing


def test_every_surviving_record_is_a_whole_record(tmp_path: Path) -> None:
    """The half of 10:1913 that does hold: a survivor is never a fragment of two writers' lines."""
    root = tmp_path / CONTROL_DIR / SESSIONS_DIR
    root.mkdir(parents=True)
    script = _writer_script(tmp_path)

    children = [
        subprocess.Popen([sys.executable, str(script), str(root), str(writer)])  # noqa: S603
        for writer in range(WRITERS)
    ]
    for child in children:
        child.wait()

    journal = read(root, "k", now_ns=NOW)

    assert journal.records
    assert all(record["pad"] == "x" * 400 for record in journal.records)
    assert all(0 <= int(record["seq"]) < EACH for record in journal.records)
