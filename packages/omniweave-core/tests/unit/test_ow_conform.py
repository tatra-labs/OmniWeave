"""`tools/ow_conform.py` — the four measurements a library may not make, made.

The kit's own tests (`test_conform_suites.py`, `test_conform_kit.py`) supply the cross-process
values as a passing run would have produced them, because their subject is the SUITES. This file's
subject is the TOOL: it runs the real thing, spawns the real children, and asserts that the four
measurements which only exist here actually arrive.

Two of those are worth stating as claims rather than as coverage:

* **The segfault is real.** `ctypes.string_at(1)` dereferences address 1. It is an access
  violation on Windows and a SIGSEGV elsewhere -- not `sys.exit`, not an exception, and not
  something a `try`/`except` in the child can be talked out of. 04-driver-system.md:2082 wants the
  run to complete AROUND a crash, and a crash a parent can catch would not test that.
* **`purity` in a clean interpreter is the only place it is observable.** Once a process has
  imported the driver for its own reasons, `sys.modules` cannot say who did it
  (`test_discovery_never_imports.py:23-25`).

This file lives under `omniweave-core`'s tests rather than the kit's for the reason every other
`tools/` gate's test does: `tools/` is not a distribution, `packages/omniweave-core/tests/` is
where `test_gate_crash.py`, `test_gate_pins.py` and `test_plan_lint.py` already are, and a test
that spawns is not the kit's own property.

Specified in 04-driver-system.md section 8; ledger D25.
"""

from __future__ import annotations

import json
import subprocess  # noqa: TID251 -- the subject of this file is a tool that spawns.
import sys
from pathlib import Path

import pytest
from omniweave_conform.result import SUITES
from omniweave_core.drivers.card import load_card, read_card_bytes

REPO = Path(__file__).resolve().parents[4]
TOOL = REPO / "tools" / "ow_conform.py"
TEMPLATE = REPO / "packages/omniweave-conform/src/omniweave_conform/template"

TIMEOUT_S = 300
"""Generous: this test spawns three children, each of which spawns nothing further. Finite because
a test that can hang is a CI job that can hang."""


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- argv is built here, from literals.
        [sys.executable, str(TOOL), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(REPO),
        timeout=TIMEOUT_S,
    )


@pytest.fixture(scope="module")
def report() -> dict[str, object]:
    """One real run against the shipped template, as JSON. Module-scoped: it spawns."""
    done = _run("--template", "--json")
    assert done.returncode == 0, f"exit {done.returncode}\n{done.stdout}\n{done.stderr}"
    return json.loads(done.stdout)


def test_the_tool_exists_where_every_other_gate_lives() -> None:
    """D25's shape: the mechanism is in the package, the process control is in `tools/`."""
    assert TOOL.is_file()
    assert (TEMPLATE / "driver.toml").is_file()
    assert (TEMPLATE / "fixtures").is_dir()


def test_the_template_driver_passes_the_mandatory_tier_through_the_real_tool(
    report: dict[str, object],
) -> None:
    """04-driver-system.md:2332's own arithmetic, produced by running the thing.

    This is the strongest single statement the kit can make about itself: every one of the eleven
    mandatory suites, including the four halves that need a child process, green against a driver
    the plan prints and this repository ships.
    """
    assert report["passed"] is True
    assert report["mandatory"] == "11/11"
    assert report["driver_id"] == "parse.text.plain"
    failures = {
        row["suite"]: row["failures"]
        for row in report["suites"]
        if row["failures"]  # type: ignore[index]
    }
    assert failures == {}, failures


def test_quality_is_unknown_and_does_not_stop_the_run(report: dict[str, object]) -> None:
    """The twelfth suite is not mandatory, and a run that passes while it is unknown is correct."""
    rows = {row["suite"]: row for row in report["suites"]}  # type: ignore[index]
    assert rows["quality"]["verdict"] == "unknown"
    assert rows["quality"]["mandatory"] is False
    assert report["passed"] is True


def test_every_one_of_the_twelve_reported(report: dict[str, object]) -> None:
    """A run that lost a suite must not be able to print 11/11."""
    assert [row["suite"] for row in report["suites"]] == list(SUITES)  # type: ignore[index]


def test_the_children_that_only_a_process_can_run_actually_ran(
    report: dict[str, object],
) -> None:
    """The four measurements, each identified in the run's own notes.

    Asserted on the notes rather than only on the verdicts, because a suite reporting `pass` for
    a measurement it never received is exactly the failure this tool exists to prevent -- and the
    suites are written so that an absent measurement is a `fail`, which the previous test would
    have caught. This one says the measurement ARRIVED.
    """
    notes = " | ".join(str(note) for note in report["children"])  # type: ignore[index]
    assert "cross-process:" in notes and "PYTHONHASHSEED=1" in notes
    assert "segfault:" in notes
    assert "purity in a clean interpreter: pass" in notes


def test_the_segfault_child_really_dies(report: dict[str, object]) -> None:
    """A crash is one row; a hang is the run. The note names which happened."""
    notes = " | ".join(str(note) for note in report["children"])  # type: ignore[index]
    assert "this process continued" in notes
    assert "neither crashed nor returned" not in notes, "a hang, which the row forbids"


def test_the_badge_is_the_string_the_plan_prints() -> None:
    """04-driver-system.md:2395, field by field, from a real run."""
    done = _run("--template", "--badge")
    assert done.returncode == 0, done.stderr
    badge = done.stdout.strip().splitlines()[-1]
    assert badge.startswith("omniweave-conform ")
    assert " mandatory 11/11 pass " in badge
    assert " quality unknown " in badge
    assert "card sha256:" in badge
    assert badge.count("·") == 3


def test_bench_refuses_by_naming_what_is_missing_rather_than_writing_an_empty_block() -> None:
    """13-quality.md:1749 makes the SHAPE of the number non-optional.

    A `[quality]` block of zeroes would be a measurement claim nobody made, so the flag refuses
    and says which command produces the corpus it needs.
    """
    done = _run("--template", "--bench")
    assert done.returncode == 2
    assert "ow eval fetch" in done.stderr
    assert "P10" in done.stderr


def test_a_missing_card_is_a_usage_error_and_not_a_failed_run() -> None:
    """Exit 2 for "could not read", 1 for "read it and it failed". They are different answers."""
    done = _run("--card", str(REPO / "does-not-exist.toml"))
    assert done.returncode == 2
    assert "no such card" in done.stderr


def test_write_refuses_a_card_whose_author_filled_in_a_kit_region(tmp_path: Path) -> None:
    """DR13, through the tool: `--write` checks before it writes, and refuses rather than clobbers.

    The card is copied first, so the shipped template is never the subject of a write test.
    """
    card = tmp_path / "driver.toml"
    card.write_bytes(
        (TEMPLATE / "driver.toml").read_bytes() + b'\n[quality]\nkit_version = "9.9.9"\n'
    )
    done = _run("--card", str(card), "--fixtures", str(TEMPLATE / "fixtures"), "--write")
    assert done.returncode == 1
    assert "--write refused" in done.stdout
    assert "DR13" in done.stdout
    assert card.read_bytes().endswith(b'kit_version = "9.9.9"\n'), "refused means unchanged"


def test_write_fills_in_the_kit_regions_and_the_card_then_reloads_attested(
    tmp_path: Path,
) -> None:
    """The end of 04-driver-system.md section 9 step 4: "wrote ... and attestation into <card>".

    And then the loop closes: the written card loads, and the loader's independent recomputation
    of `attestation` agrees with what the tool wrote.
    """
    card = tmp_path / "driver.toml"
    card.write_bytes((TEMPLATE / "driver.toml").read_bytes())
    done = _run("--card", str(card), "--fixtures", str(TEMPLATE / "fixtures"), "--write")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "wrote [quality] and attestation into" in done.stdout

    written = load_card(read_card_bytes(card), origin="driver_path", source=str(card))
    assert written.attested, "the loader must recompute to the value the tool wrote"
    assert written.quality.suites["card"] == "pass"
    assert written.quality.suites["quality"] == "unknown"


def test_a_card_written_by_the_tool_still_passes_a_second_run(tmp_path: Path) -> None:
    """The one thing 04:2386-2389 warns about: a card edited mid-loop that nothing re-reads.

    A second run over the written card must still pass -- and the `card` suite's freshness
    assertion must see the file the run actually validated.
    """
    card = tmp_path / "driver.toml"
    card.write_bytes((TEMPLATE / "driver.toml").read_bytes())
    first = _run("--card", str(card), "--fixtures", str(TEMPLATE / "fixtures"), "--write")
    assert first.returncode == 0, first.stdout + first.stderr
    second = _run("--card", str(card), "--fixtures", str(TEMPLATE / "fixtures"), "--json")
    assert second.returncode == 0, second.stdout + second.stderr
    report = json.loads(second.stdout)
    assert report["mandatory"] == "11/11"
    rows = {row["suite"]: row for row in report["suites"]}
    assert "attestation ok" in rows["card"]["summary"]
