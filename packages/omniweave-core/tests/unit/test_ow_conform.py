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
import os
import shutil
import subprocess  # noqa: TID251 -- the subject of this file is a tool that spawns.
import sys
from pathlib import Path

import pytest
from omniweave_conform.result import SUITES
from omniweave_core.drivers.card import load_card, read_card_bytes

REPO = Path(__file__).resolve().parents[4]
TOOL = REPO / "tools" / "ow_conform.py"
TEMPLATE = REPO / "packages/omniweave-conform/src/omniweave_conform/template"
PDF_CARD = REPO / "packages/omniweave-pdf/src/omniweave_pdf/driver.toml"
PDF_FIXTURES = REPO / "packages/omniweave-pdf/fixtures"

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


def _external_driver(root: Path) -> Path:
    """A driver project OUTSIDE this repository: its own package, card, `pyproject.toml` and
    fixtures under `root`, importable only through its author's `PYTHONPATH`. D923.

    Its code starts as the template's, the way a scaffold hands an author a working driver, under
    a package, class and driver id of its own; nothing in it names `omniweave_conform`.
    """
    package = root / "src" / "acme_plaintext"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    code = (TEMPLATE / "driver.py").read_text(encoding="utf-8")
    (package / "driver.py").write_text(code.replace("PlainTextParser", "AcmeParser"), "utf-8")
    card = (TEMPLATE / "driver.toml").read_text(encoding="utf-8")
    card = card.replace('id = "parse.text.plain"', 'id = "parse.text.acme"').replace(
        '"omniweave_conform.template.driver:PlainTextParser"', '"acme_plaintext.driver:AcmeParser"'
    )
    (package / "driver.toml").write_text(card, encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "acme-plaintext"\nversion = "0.1.0"\nlicense = "Apache-2.0"\n'
        'dependencies = ["omniweave-ports"]\n',
        encoding="utf-8",
    )
    shutil.copytree(TEMPLATE / "fixtures", root / "fixtures")
    return package / "driver.toml"


def test_a_driver_authored_outside_this_repository_passes_the_mandatory_tier(
    tmp_path: Path,
) -> None:
    """V10-12: *"a Driver authored outside this repository passes the eleven mandatory suites"*.

    The two cross-process suites are the ones an external driver exposes: their child must import
    the driver from the path its author set, and until D923 the child's `PYTHONPATH` was this
    repository's alone, so `idempotence` and `determinism` failed on a child that died at
    `activate()`. `licence` reads the author's own `pyproject.toml`.
    """
    card = _external_driver(tmp_path)
    assert REPO not in card.parents
    env = {**os.environ, "PYTHONPATH": str(tmp_path / "src")}
    done = subprocess.run(  # noqa: S603 -- argv is built here, from literals and tmp_path.
        [
            sys.executable,
            str(TOOL),
            "--card",
            str(card),
            "--fixtures",
            str(tmp_path / "fixtures"),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(REPO),
        env=env,
        timeout=TIMEOUT_S,
    )
    assert done.returncode == 0, f"exit {done.returncode}\n{done.stdout}\n{done.stderr}"
    external = json.loads(done.stdout)
    assert (external["driver_id"], external["mandatory"], external["passed"]) == (
        "parse.text.acme",
        "11/11",
        True,
    )
    suites = {row["suite"]: row for row in external["suites"]}  # type: ignore[union-attr]
    assert "cross-process compared" in str(suites["idempotence"]["summary"])  # type: ignore[index]
    assert "resolved graph 1 dists" in str(suites["licence"]["summary"])  # type: ignore[index]


SUBRIP = Path(__file__).resolve().parent / "external_driver_subrip"
"""An independent driver project, for SubRip subtitles: its own code, card, `pyproject.toml` and
fixtures, written against `omniweave_ports` alone (D967, a user ruling of 2026-10-23)."""


def test_an_independent_driver_for_another_format_passes_the_mandatory_tier(
    tmp_path: Path,
) -> None:
    """V10-12 with an independent implementation: D923's external driver was the template under
    new names. This one is a SubRip parser that shares no code with the template, run from a copy
    outside this repository, the way its author would: from the project's own directory, with
    `PYTHONPATH=src`. A relative entry broke the cross-process child until D967, since the child
    runs in another cwd."""
    project = tmp_path / "subrip-cues"
    shutil.copytree(SUBRIP, project, ignore=shutil.ignore_patterns("__pycache__"))
    assert REPO not in project.parents
    code = (project / "src" / "subrip_cues" / "driver.py").read_text(encoding="utf-8")
    template = (TEMPLATE / "driver.py").read_text(encoding="utf-8")
    assert "omniweave_conform" not in code
    #  The port contract forces signatures, imports and record keys on every driver; the
    #  template's own logic is its names, and none of them is here.
    own = ("PlainTextParser", "_PARAGRAPH_BREAK", "_TXT_SUFFIXES", "cursor_chars", "_NUL")
    assert all(name in template for name in own)
    assert not [name for name in own if name in code]
    assert "def cues(raw: bytes)" in code, "the cue grammar is this driver's own"
    env = {**os.environ, "PYTHONPATH": "src"}
    done = subprocess.run(  # noqa: S603 -- argv is built here, from literals and tmp_path.
        [
            sys.executable,
            str(TOOL),
            "--card",
            "src/subrip_cues/driver.toml",
            "--fixtures",
            "fixtures",
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(project),
        env=env,
        timeout=TIMEOUT_S,
    )
    assert done.returncode == 0, f"exit {done.returncode}\n{done.stdout}\n{done.stderr}"
    result = json.loads(done.stdout)
    assert (result["driver_id"], result["mandatory"], result["passed"]) == (
        "parse.subtitle.subrip",
        "11/11",
        True,
    )
    suites = {row["suite"]: row for row in result["suites"]}  # type: ignore[union-attr]
    assert "cross-process compared" in str(suites["idempotence"]["summary"])  # type: ignore[index]
    assert "origin_span=exact checked on 10 of 10 blocks" in str(
        suites["capability"]["summary"]  # type: ignore[index]
    )
    assert "resolved graph 1 dists" in str(suites["licence"]["summary"])  # type: ignore[index]


@pytest.mark.parametrize("target", ["docx", "pptx"])
def test_each_target_reader_passes_the_mandatory_tier_over_its_compiled_golden(
    tmp_path: Path, target: str
) -> None:
    """V10-10 (D968): a target's reader card, the sibling `parse/1` driver its read-back runs, is a
    driver like any other, so it goes through the kit, over the artefact its own compiler makes of
    the register's golden. D879 found pptx's failing `licence` on Pillow's MIT-CMU, G3's open
    question until a user ruling of 2026-10-19 (D884) admitted the id; both now pass 11/11."""
    import tomllib  # noqa: PLC0415

    from omniweave_conform.compile_harness import run_compile  # noqa: PLC0415
    from omniweave_core.host.activate import construct  # noqa: PLC0415

    register = tomllib.loads((REPO / "eval" / "gates.toml").read_text(encoding="utf-8"))
    (row,) = [one for one in register["target"] if one["target"] == target]
    card_path = REPO / row["card"]
    card = load_card(read_card_bytes(card_path), origin="entry_point", source=str(card_path))
    config = dict(row.get("config", {}))
    config.update({key: str(REPO / value) for key, value in row.get("paths", {}).items()})
    compiled = run_compile(construct(card, config), card, REPO / row["golden"], tmp_path / "work")
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / f"golden.{target}").write_bytes(compiled.body)
    done = _run("--card", str(REPO / row["read_back"]), "--fixtures", str(fixtures), "--json")
    assert done.returncode == 0, f"exit {done.returncode}\n{done.stdout}\n{done.stderr}"
    result = json.loads(done.stdout)
    assert (result["mandatory"], result["passed"]) == ("11/11", True), result
    suites = {row["suite"]: row for row in result["suites"]}  # type: ignore[union-attr]
    assert suites["licence"]["verdict"] == "pass"  # type: ignore[index]


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


# ---------------------------------------------------------------------------------------------
# The P3 demo: the kit against a real first-party driver, not only against its own template
# ---------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pdf_report() -> dict[str, object]:
    """One real run against `parse.pdf.pdfium`. Module-scoped: it spawns three children."""
    done = _run("--card", str(PDF_CARD), "--fixtures", str(PDF_FIXTURES), "--json")
    assert done.returncode == 0, f"exit {done.returncode}\n{done.stdout}\n{done.stderr}"
    return json.loads(done.stdout)


def test_the_pdf_driver_passes_the_mandatory_tier(pdf_report: dict[str, object]) -> None:
    """16-roadmap.md's P3 demo: `ow conform packages/omniweave-pdf --suites mandatory`.

    The template driver passing proves the kit runs. THIS proves the kit is worth running: a
    driver built against a real C library, with a real dependency graph, a real crash surface and
    a real glyph index space, held to the same twelve.
    """
    assert pdf_report["passed"] is True
    assert pdf_report["mandatory"] == "11/11"
    assert pdf_report["driver_id"] == "parse.pdf.pdfium"
    failures = {
        row["suite"]: row["failures"]
        for row in pdf_report["suites"]
        if row["failures"]  # type: ignore[index]
    }
    assert failures == {}, failures


def test_capability_proved_origin_span_on_every_block_of_every_fixture(
    pdf_report: dict[str, object],
) -> None:
    """**INV-10's `glyphs` branch, proved rather than declared.**

    03-document-model.md:3030 calls P7 "the only mechanism that makes a third party's honesty
    machine-checkable", and 16-roadmap.md:486 requires `capability` to prove `origin_span` on all
    three of its branches. The template proves `bytes`; this driver proves `glyphs`, through the
    `verify_origin()` hook the kit calls for a branch it cannot read unaided. The summary carries
    the count, and the count must be every block -- a partial proof is an unproved card.
    """
    rows = {row["suite"]: row for row in pdf_report["suites"]}  # type: ignore[index]
    summary = str(rows["capability"]["summary"])
    assert "origin_span=exact" in summary
    checked, _, total = summary.partition(" of ")
    count = int(checked.rsplit(" ", 1)[-1])
    blocks = int(total.split()[0])
    assert count == blocks > 0, summary
    assert rows["capability"]["verdict"] == "pass"


def test_the_pdf_driver_is_socket_blocked_and_writes_nowhere_but_tmp(
    pdf_report: dict[str, object],
) -> None:
    """pdfium is a C library with a filesystem API. The `sandbox` suite says it stayed put."""
    rows = {row["suite"]: row for row in pdf_report["suites"]}  # type: ignore[index]
    assert rows["sandbox"]["verdict"] == "pass"
    assert "socket-blocked" in str(rows["sandbox"]["summary"])
    assert "0 writes outside tmp" in str(rows["sandbox"]["summary"])


def test_the_pdf_drivers_dependency_graph_is_licence_clean(
    pdf_report: dict[str, object],
) -> None:
    """`pypdfium2` declares three things in one metadata string, and all of them must be allowed.

    04-driver-system.md:2081 scans "the resolved dependency graph and the import graph", and this
    is the first driver with a dependency graph worth scanning: pdfium bundles FreeType,
    libjpeg-turbo, lcms2, zlib and libopenjpeg (14-security.md:1527).
    """
    rows = {row["suite"]: row for row in pdf_report["suites"]}  # type: ignore[index]
    assert rows["licence"]["verdict"] == "pass", rows["licence"]["failures"]
    assert "tier=open" in str(rows["licence"]["summary"])


# ---------------------------------------------------------------------------------------------
# D890: a compile card's golden, through the real tool and its child

PPTX_CARD = REPO / "packages/omniweave-target-pptx/src/omniweave_target_pptx/driver.toml"
PPTX_GOLDEN = REPO / "fixtures/out/golden/pptx"


def test_a_compile_card_is_idempotent_and_deterministic_across_two_processes() -> None:
    """The pptx golden needs its `font_dir`, which `--config` hands the parent and the child
    alike, so the cross-process digest is of the same configuration."""
    done = _run(
        "--card",
        str(PPTX_CARD),
        "--fixtures",
        str(PPTX_GOLDEN),
        "--config",
        f"font_dir={PPTX_GOLDEN / 'fonts'}",
        "--json",
    )
    assert done.returncode in (0, 1), done.stderr
    report = json.loads(done.stdout)
    rows = {row["suite"]: row for row in report["suites"]}
    for suite in ("contract", "idempotence", "determinism"):
        assert rows[suite]["verdict"] == "pass", rows[suite]
    assert "cross-process compared" in rows["idempotence"]["summary"]
    assert any(note.startswith("cross-process: 1 fixtures") for note in report["children"])


def test_a_config_that_is_not_key_value_is_a_usage_error() -> None:
    done = _run("--template", "--config", "font_dir")
    assert done.returncode == 2
    assert "is not KEY=VALUE" in done.stderr
