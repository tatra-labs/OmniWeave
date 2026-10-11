"""`compile.docx.native` against its golden fixture, through the conformance `target` suite.

`fixtures/out/golden/docx/` is owflow/1's golden: two units that use every `exact` row of the
table (R5 asks for each), a manual region (so the gate is `manual-required` and the compile a
draft), a cite with its kind and span, two notes and a frozen picture. D784.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from omniweave_conform.result import Verdict
from omniweave_conform.suites.target.suite import run_target
from omniweave_core.drivers.card import DriverCard, load_card
from omniweave_core.out.constructs import Disposition, RoundTrip
from omniweave_core.out.gate import GateStatus
from omniweave_target_docx.driver import CARD, DocxCompiler, table

GOLDEN = Path(__file__).resolve().parents[4] / "fixtures" / "out" / "golden" / "docx"


def _card() -> DriverCard:
    card = load_card(CARD.read_bytes(), origin="driver_path", source=str(CARD))
    assert isinstance(card, DriverCard)
    return card


def test_the_golden_is_written_against_the_table_that_ships() -> None:
    """A table change moves the digest, and the golden is regenerated with it."""
    il = tomllib.loads((GOLDEN / "il" / "il.toml").read_text(encoding="utf-8"))
    assert il["constructs_digest"] == table().digest()


def test_every_declared_law_is_checked_or_says_why_not(tmp_path: Path) -> None:
    report = run_target(DocxCompiler(), _card(), table(), GOLDEN, workdir=tmp_path / "work")
    assert (report.target, report.gate) == ("docx", GateStatus.MANUAL_REQUIRED)
    assert {o.law: o.status for o in report.laws} == {
        "r1": "checked",
        "r2": "unknown",
        "r3": "unknown",
        "r4": "not-applicable",
        "r5": "unknown",
        "r6": "unknown",
        "r7": "checked",
    }
    assert report.law("r1").verdict is Verdict.PASS, "part and byte, twice, one package"
    assert report.law("r7").verdict is Verdict.PASS
    r5 = report.law("r5")
    assert r5.result is not None and r5.result.passed, "every exact row used, and seen"
    assert "ow.el exempt" in r5.reason
    assert "read_back" in report.law("r2").reason
    assert report.verdict is Verdict.UNKNOWN, "R2, R3 and R6 wait on parse.docx.native"


def test_the_golden_uses_every_exact_row() -> None:
    """R5's third clause, stated over the fixture directly: a row it never uses is a gap."""
    compiler = DocxCompiler()
    used: set[str] = set()
    for name in ("u01.html", "u02.html"):
        doc = compiler.carrier(f"il/{name}", (GOLDEN / "il" / name).read_text(encoding="utf-8"))
        for row in table().rows:
            if row.selector and doc.select(row.selector):
                used.add(row.id)
    exact = {
        r.id
        for r in table().rows
        if r.round_trip is RoundTrip.EXACT and r.disposition is not Disposition.NORMALIZE
    }
    assert exact - used == set()
