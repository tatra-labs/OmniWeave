"""`ow add` over unchanged files re-parses what a moved parse driver keys differently. D930.

D679 re-enters a settled unit whose parse driver moved its key (a `schema_version` bump, a
semantic config change), but only inside a run, and `ow add` opened no run when no file was
queued. So a driver bump over unchanged files re-parsed nothing. GR8's driver-version step passed
only when the step before it left a file inside the racy-mtime window, which queued it and opened
a run by accident; under load it did not, and the step failed (sixteen runs at once failed at
least ten).

Here the files are dated years back, so no change-detection ladder can queue them: the only thing
that can open the second run is the driver's moved key.
"""

from __future__ import annotations

import os
import shutil
import sqlite3  # noqa: TID251 -- the assertions read the store the children wrote.
import sys
from pathlib import Path

import pytest
from omniweave_core.host.subproc import Captured, run_captured

pytestmark = pytest.mark.conform

TIMEOUT_S = 180
PACKAGES = Path(__file__).resolve().parents[3]
MEMO = PACKAGES / "omniweave-office" / "fixtures" / "rich.docx"
PROJECT = (
    '[corpora.handbook]\npath = ".omniweave/index.owstore"\n'
    "[drivers]\nallow_unattested = true\nrequire_lock = false\ninproc = []\n"
)
BUMP = '\n[drivers."parse.office.anydoc".config]\nmax_asset_bytes = 33554431\n'
"""GR8's own bump: one byte under the card's default, so the effective config's digest moves."""

LONG_AGO = 1_000_000_000
"""2001-09-09, in seconds: far outside any racy-mtime window."""


def _ow(project: Path, *args: str) -> Captured:
    keep = {k: v for k, v in os.environ.items() if k not in {"PYTHONUTF8", "PYTHONIOENCODING"}}
    return run_captured(
        (sys.executable, "-m", "omniweave", *args),
        stdin=b"",
        cwd=str(project),
        env={**keep, "OMNIWEAVE_HOME": str(project / "owhome")},
        timeout_s=TIMEOUT_S,
    )


def _one(project: Path, sql: str) -> tuple[object, ...]:
    connection = sqlite3.connect(project / ".omniweave" / "index.owstore")
    try:
        row = connection.execute(sql).fetchone()
    finally:
        connection.close()
    return tuple(row)


def _head_gen(project: Path) -> int:
    return int(_one(project, "SELECT MAX(gen) FROM doc WHERE uri LIKE '%memo.docx'")[0])  # type: ignore[call-overload]


def _runs(project: Path) -> int:
    return int(_one(project, "SELECT count(*) FROM run")[0])  # type: ignore[call-overload]


def test_a_config_bump_over_an_unchanged_file_re_parses_it(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    memo = docs / "memo.docx"
    shutil.copy(MEMO, memo)
    os.utime(memo, (LONG_AGO, LONG_AGO))
    (tmp_path / "omniweave.toml").write_text(PROJECT, encoding="utf-8")

    first = _ow(tmp_path, "add", "docs")
    assert first.returncode == 0, first.stderr.decode("utf-8", "replace")
    before, runs = _head_gen(tmp_path), _runs(tmp_path)

    unchanged = _ow(tmp_path, "add", "docs")
    assert unchanged.returncode == 0, unchanged.stderr.decode("utf-8", "replace")
    assert (_head_gen(tmp_path), _runs(tmp_path)) == (before, runs), (
        "nothing moved, so no run opens and nothing re-parses"
    )

    with (tmp_path / "omniweave.toml").open("a", encoding="utf-8") as toml:
        toml.write(BUMP)
    bumped = _ow(tmp_path, "add", "docs")
    assert bumped.returncode == 0, bumped.stderr.decode("utf-8", "replace")
    assert _runs(tmp_path) == runs + 1, "the moved key opened a run over an unchanged file"
    assert _head_gen(tmp_path) > before, "and the run re-parsed it under the new config"

    settled = _ow(tmp_path, "add", "docs")
    assert settled.returncode == 0
    assert _runs(tmp_path) == runs + 1, "once re-parsed, the key no longer moves: no further run"
