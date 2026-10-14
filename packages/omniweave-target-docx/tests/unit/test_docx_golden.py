"""`compile.docx.native` against its golden fixture, through the conformance `target` suite.

`fixtures/out/golden/docx/` is owflow/1's golden: two units that use every `exact` row of the
table (R5 asks for each), a manual region (so the gate is `manual-required` and the compile a
draft), a cite with its kind and span, two notes and a frozen picture. D784.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from omniweave_conform.result import Verdict
from omniweave_conform.suites.target.suite import run_target
from omniweave_core.drivers.card import DriverCard, load_card
from omniweave_core.out.constructs import Disposition, RoundTrip
from omniweave_core.out.gate import GateStatus
from omniweave_ports import ArtifactRef, DriverResult
from omniweave_target_docx.driver import CARD, DocxCompiler, table
from omniweave_target_docx.read.driver import DocxReader

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
    report = run_target(
        DocxCompiler(), _card(), table(), GOLDEN, workdir=tmp_path / "work", reader=DocxReader()
    )
    assert (report.target, report.gate) == ("docx", GateStatus.MANUAL_REQUIRED)
    assert {o.law: o.status for o in report.laws} == {
        "r1": "checked",
        "r2": "checked",
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
    assert report.law("r2").verdict is Verdict.PASS, "D787: every address read back, in place"
    assert "project = false" in report.law("r3").reason
    assert report.verdict is Verdict.UNKNOWN, "R3, R5's reader clauses and R6 are not checked"


def test_without_a_reader_r2_says_why_not(tmp_path: Path) -> None:
    report = run_target(DocxCompiler(), _card(), table(), GOLDEN, workdir=tmp_path / "work")
    r2 = report.law("r2")
    assert (r2.status, r2.reason) == (
        "unknown",
        "r2 reads the artefact back, and no read_back driver was given",
    )


class _Forgetful(DocxReader):
    """A read_back that loses one address: R2 must say which."""

    def parse(self, unit: Any, parts: Any, io: Any) -> Any:
        result = super().parse(unit, parts, io)
        [ref] = result.produced
        body = ref.inline if ref.inline is not None else io.blobs.open(ref.blob).read()
        lost = body.replace(b',"x":{"x.ow.el":"u01/e4"}', b"")
        return DriverResult(outcome="ok", produced=(ArtifactRef.of("doc_fragment", lost, io),))


def test_a_reader_that_loses_an_address_fails_r2_naming_it(tmp_path: Path) -> None:
    report = run_target(
        DocxCompiler(), _card(), table(), GOLDEN, workdir=tmp_path / "work", reader=_Forgetful()
    )
    r2 = report.law("r2")
    assert r2.verdict is Verdict.FAIL
    assert r2.result is not None
    assert [(f.kind, f.subject) for f in r2.result.failures] == [("missing", "u01/e4")]


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
