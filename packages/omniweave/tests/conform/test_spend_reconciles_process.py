"""A real `ow add` reconciles under `ow cost --verify`: every parse attempt has its bill. D854.

15-observability.md section 5.4's `--verify` runs I30's two self-checks (D853). Until D854 a real
ingest wrote no `route_spend` row at all: the parse operator's `StepMetrics` carried no `Spend`, so
every finished parse row named a decision with nothing on the bill, and the second check failed
every run. Three drivers' documents are ingested here by real children, and the run must verify.
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
DOCUMENTS = {
    "contract.pdf": PACKAGES / "omniweave-pdf" / "fixtures" / "gen02p.pdf",
    "memo.docx": PACKAGES / "omniweave-office" / "fixtures" / "rich.docx",
    "notes.txt": PACKAGES / "omniweave-office" / "fixtures" / "text" / "notes.txt",
}
PROJECT = (
    '[corpora.handbook]\npath = ".omniweave/index.owstore"\n'
    "[drivers]\nallow_unattested = true\nrequire_lock = false\ninproc = []\n"
)


def _ow(project: Path, *args: str) -> Captured:
    keep = {k: v for k, v in os.environ.items() if k not in {"PYTHONUTF8", "PYTHONIOENCODING"}}
    return run_captured(
        (sys.executable, "-m", "omniweave", *args),
        stdin=b"",
        cwd=str(project),
        env={**keep, "OMNIWEAVE_HOME": str(project / "owhome")},
        timeout_s=TIMEOUT_S,
    )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    docs = tmp_path / "docs"
    docs.mkdir()
    for name, source in DOCUMENTS.items():
        shutil.copy(source, docs / name)
    (tmp_path / "omniweave.toml").write_text(PROJECT, encoding="utf-8")
    return tmp_path


def _rows(project: Path, sql: str) -> list[tuple[object, ...]]:
    connection = sqlite3.connect(project / ".omniweave" / "index.owstore")
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()


def test_a_real_ingest_bills_every_parse_attempt_and_verifies(project: Path) -> None:
    added = _ow(project, "add", "docs")
    assert added.returncode == 0, added.stderr.decode("utf-8", "replace")
    assert _rows(
        project,
        "SELECT d.driver, COUNT(*) FROM route_spend AS s JOIN route_decision AS d"
        " USING (decision_id) GROUP BY 1 ORDER BY 1",
    ) == [("parse.office.anydoc", 1), ("parse.pdf.pdfium", 1), ("parse.text.builtin", 1)]
    verified = _ow(project, "cost", "--verify")
    out = verified.stdout.decode("utf-8", "replace")
    assert verified.returncode == 0, out + verified.stderr.decode("utf-8", "replace")
    #  D855: the run's op rows are its, though completion cleared their claimed_gen.
    assert [line.split()[:3] for line in out.splitlines() if line.startswith("op.")] == [
        ["op.identify", "free", "3"]
    ]
    assert [
        line.rsplit("  ", 1)[-1] for line in out.splitlines() if line.startswith("verify: run")
    ] == [
        "OK",
        "OK",
    ]


PRICEBOOK = (
    'version = 1\ncurrency = "USD"\neffective_from = "2026-10-22"\n'
    "[local]\nwall_ms_micros = 1.0\ncpu_ms_micros = 2.0\n"
)
"""A book that prices the two time dimensions, so a parse bill is money and not a measured zero."""


def test_a_priced_ingest_bills_the_host_s_time_and_still_reconciles(project: Path) -> None:
    """D921, V10-13: the host meters each worker's wall and CPU time from outside, so a
    `PriceBook` that rates them prices every parse, and `ow cost --verify` reconciles a bill that
    is not 0 == 0. Each attempt's `micros` is its own wall and CPU at the book's two rates."""
    (project / ".omniweave").mkdir()
    (project / ".omniweave" / "pricebook.toml").write_text(PRICEBOOK, encoding="utf-8")
    added = _ow(project, "add", "docs")
    assert added.returncode == 0, added.stderr.decode("utf-8", "replace")
    rows = _rows(
        project,
        "SELECT d.driver, s.wall_ms, s.cpu_ms, s.micros FROM route_spend AS s"
        " JOIN route_decision AS d USING (decision_id) ORDER BY 1",
    )
    assert [driver for driver, *_ in rows] == [
        "parse.office.anydoc",
        "parse.pdf.pdfium",
        "parse.text.builtin",
    ]
    for driver, wall_ms, cpu_ms, micros in rows:
        assert int(wall_ms) > 0, f"{driver}: the host measured no wall time"  # type: ignore[call-overload]
        assert int(micros) == int(wall_ms) + 2 * int(cpu_ms), driver  # type: ignore[call-overload]
    verified = _ow(project, "cost", "--verify")
    out = verified.stdout.decode("utf-8", "replace")
    assert verified.returncode == 0, out + verified.stderr.decode("utf-8", "replace")
    assert [
        line.rsplit("  ", 1)[-1] for line in out.splitlines() if line.startswith("verify: run")
    ] == ["OK", "OK"]
