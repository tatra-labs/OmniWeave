"""G29, the redaction canary: a page's text reaches no artefact when its driver fails. D936.

15-observability.md:1447: a corpus *"whose every page contains the canary `OWCANARY-7f3a91`"*
is ingested *"with a forced driver crash, a forced budget denial, a forced quarantine and a
forced exception inside a driver frame that holds page text in a local"*, and every produced
artefact is grepped: the canary may appear in the `quarantine` payload and nowhere else. A second
assertion covers the traceback channel: *"no artefact contains it *and* `unit.failed` carries the
type name"*.

## Where this file is

11:1572 and 15:1447 write the path as `tests/test_no_content_in_artefacts.py` and name no
`tests/` root, and `tools/gates.toml` recorded the ambiguity for whoever landed the test. It is
here because it spawns `ow`, which makes it T3, and Q-G25 puts a T3 test under `tests/conform/`.

## What is forced, and what is not yet

Two faults, each a hostile driver from `omniweave_conform.canary` that holds the page in a local:
- `BugParser`, whose `int(page_text)` exception carries the page (D934's leak path);
- `CrashParser`, which writes the page to stderr and exits with no frame.

Each is named by a project card and given the corpus's `txt` by a project route rule (D935).

Not forced, because nothing in this build can force them:
- the **budget denial**: `ow add --allow-cost` is refused as unserved, and a billed card is
  deferred at routing before a driver holds any page;
- the **quarantine**: it is a derive draft's, and no derive pass in a model-free run produces
  one, so no payload is written for the canary to be allowed in.

Not grepped, because this build does not produce them; `test_the_artefacts_not_built_are_absent`
fails the day one appears, so the grep grows with it:
- the NDJSON event shards: `ow add` constructs no `NdjsonSink`;
- `{run_id}.paths.json`;
- `ow trace export --file`.

What is grepped: both commands' console, every byte under the project's `.omniweave/` but the
content store (`cas/`, the retained source, which is the document itself), the home and
`OMNIWEAVE_HOME` trees, and every text cell of every table in the store.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from omniweave.route.policy import POLICY_D
from omniweave.run.operators.parse import UNANSWERED
from omniweave_conform.canary import CANARY, CRASH_STATUS
from omniweave_core.config import SHIPPED_DRIVERS
from omniweave_core.host.subproc import run_captured
from omniweave_core.store import sqlite as ow

pytestmark = pytest.mark.conform

REPO = Path(__file__).resolve().parents[4]
TEMPLATE = REPO / "packages/omniweave-conform/src/omniweave_conform/template/driver.toml"
PAGES = {
    "receipt.txt": f"Total due {CANARY} on receipt\n",
    "note.txt": f"A note that says {CANARY} twice: {CANARY}\n",
}
"""15:1448: every page carries the canary. A text file is one page."""

FAULTS = {
    "bug": ("BugParser", "driver_bug"),
    "crash": ("CrashParser", "driver_crashed"),
}


def _project(root: Path, fault: str) -> tuple[Path, str]:
    """A project whose `txt` goes to the fault's canary driver, through a card and a rule."""
    cls, _failure = FAULTS[fault]
    driver = f"parse.text.canary{fault}"
    project = root / "project"
    (project / "docs").mkdir(parents=True)
    card = TEMPLATE.read_text(encoding="utf-8")
    for old, new in (
        ('id = "parse.text.plain"', f'id = "{driver}"'),
        ("omniweave_conform.template.driver:PlainTextParser", f"omniweave_conform.canary:{cls}"),
    ):
        assert card.count(old) == 1, old
        card = card.replace(old, new)
    cards = project / ".omniweave" / "drivers" / fault
    cards.mkdir(parents=True)
    (cards / "driver.toml").write_text(card, encoding="utf-8")
    enabled = ", ".join(f'"{one}"' for one in (*SHIPPED_DRIVERS, driver))
    (project / "omniweave.toml").write_text(
        '[corpora.docs]\npath = ".omniweave/docs.owstore"\n[serve]\ndefault_corpus = "docs"\n'
        "[drivers]\nallow_unattested = true\nrequire_lock = false\ninproc = []\n"
        f"enabled = [{enabled}]\n",
        encoding="utf-8",
    )
    (project / POLICY_D).mkdir(parents=True)
    (project / POLICY_D / "10-canary.toml").write_text(
        'surface = "route"\n\n[[rule]]\nid = "g29.canary"\nrung = "DECODE"\n'
        'when = { "unit.format" = { in = ["txt"] } }\n'
        f'then = {{ driver = "{driver}", terminal = true }}\n',
        encoding="utf-8",
    )
    for name, text in PAGES.items():
        (project / "docs" / name).write_text(text, encoding="utf-8")
    return project, driver


def _ow(project: Path, *argv: str) -> tuple[int, str]:
    keep = {k: v for k, v in os.environ.items() if k not in {"PYTHONUTF8", "PYTHONIOENCODING"}}
    home = project.parent / "home"
    done = run_captured(
        (sys.executable, "-m", "omniweave", *argv),
        stdin=b"",
        cwd=str(project),
        env={
            **keep,
            "HOME": str(home),
            "USERPROFILE": str(home),
            "OMNIWEAVE_HOME": str(project.parent / "owhome"),
        },
        timeout_s=600,
    )
    shown = (done.stdout + done.stderr).decode("utf-8", "replace")
    return (-1 if done.returncode is None else done.returncode), shown


def _files(project: Path) -> list[Path]:
    """Every file G29 greps: the project's `.omniweave/` but `cas/`, and both home trees."""
    state = project / ".omniweave"
    roots = (state, project.parent / "home", project.parent / "owhome")
    found = [
        path
        for root in roots
        if root.is_dir()
        for path in root.rglob("*")
        if path.is_file() and (state / "cas") not in path.parents
    ]
    assert found, "nothing was produced to grep"
    return sorted(found)


def _cells(store: Path) -> dict[str, list[str]]:
    """Every text cell of every table, keyed by table, through a read-only connection."""
    connection = ow.connect_readonly(store)
    try:
        tables = [
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return {
            table: [
                cell.decode("utf-8", "replace") if isinstance(cell, bytes) else cell
                for row in connection.execute(f'SELECT * FROM "{table}"')  # noqa: S608
                for cell in row
                if isinstance(cell, str | bytes)
            ]
            for table in tables
        }
    finally:
        connection.close()


@pytest.mark.parametrize("fault", sorted(FAULTS))
def test_a_failing_driver_leaves_its_page_in_no_artefact(tmp_path: Path, fault: str) -> None:
    project, driver = _project(tmp_path, fault)
    code, added = _ow(project, "add", "docs")
    assert code == 0, added[-3000:]
    assert f"route     {len(PAGES)} planned ({driver} {len(PAGES)})" in added, added[-3000:]
    _code, queried = _ow(project, "query", "Total due")
    for name, console in (("ow add", added), ("ow query", queried)):
        assert CANARY not in console, f"{name}'s console carries the page"
    leaked = [str(path) for path in _files(project) if CANARY.encode() in path.read_bytes()]
    assert leaked == [], f"the page reached {leaked}"
    cells = _cells(project / ".omniweave" / "docs.owstore")
    assert [table for table, values in cells.items() if any(CANARY in v for v in values)] == []


@pytest.mark.parametrize("fault", sorted(FAULTS))
def test_the_failure_names_its_class_and_its_place_not_the_page(tmp_path: Path, fault: str) -> None:
    """15:1455's second assertion: the failure is recorded, by type and class, and without text."""
    project, driver = _project(tmp_path, fault)
    assert _ow(project, "add", "docs")[0] == 0
    connection = ow.connect_readonly(project / ".omniweave" / "docs.owstore")
    try:
        rows = connection.execute(
            "SELECT failure_class, failure_message FROM work WHERE driver = ?", (driver,)
        ).fetchall()
    finally:
        connection.close()
    _cls, failure = FAULTS[fault]
    assert len(rows) == len(PAGES)
    assert {str(row[0]) for row in rows} == {failure}
    messages = sorted(str(row[1]) for row in rows)
    if fault == "bug":
        for message in messages:
            assert message.startswith("ValueError at canary.py:"), message
            assert message.endswith(" in parse"), message
    else:
        #  A worker holding both pages dies on one: that unit names the exit status, and the one
        #  it never reached says so (D936) rather than nothing. Two workers name it twice.
        died = f"worker died without a frame, exit status {CRASH_STATUS}"
        assert set(messages) <= {died, UNANSWERED}, messages
        assert died in messages, messages


def test_the_artefacts_not_built_are_absent(tmp_path: Path) -> None:
    """The three artefacts 15:1450-1452 greps that this build does not produce. The day one is,
    this fails, and the grep above must grow to read it."""
    project, _driver = _project(tmp_path, "bug")
    assert _ow(project, "add", "docs")[0] == 0
    state = project / ".omniweave"
    assert not (state / "events").exists(), "ow add writes event shards now: grep them"
    assert not list(state.rglob("*.paths.json")), "a paths.json exists now: grep it"
