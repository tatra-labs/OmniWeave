"""`compile.pptx.native` against its golden fixture, through the conformance `target` suite. D805.

`fixtures/out/golden/pptx/` is owsvg/1's golden: two slides that use every `exact` row of the
table (R5 asks for each), a manual region (so the gate is `manual-required` and the compile a
draft), a cite with its kind and span, and a frozen picture. Its text names `Probe Sans`, the face
`fontkit` writes, so the measurement band runs rather than skips and the gate is not `unverified`.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from fontkit import tiny_font, write_font  # type: ignore[import-not-found]  # tests/fontkit.py
from omniweave_conform.result import Verdict
from omniweave_conform.suites.target.suite import run_target
from omniweave_core.drivers.card import DriverCard, load_card
from omniweave_core.out.constructs import Disposition, RoundTrip
from omniweave_core.out.gate import GateStatus
from omniweave_core.out.job import elided
from omniweave_ports import ArtifactRef, DriverResult
from omniweave_target_pptx.back.driver import PptxReader
from omniweave_target_pptx.driver import CARD, PptxCompiler, table

GOLDEN = Path(__file__).resolve().parents[4] / "fixtures" / "out" / "golden" / "pptx"
UNITS = ("u01.svg", "u02.svg")
HOSTED = {
    "paint.flood-color": "svg|feDropShadow",
    "paint.flood-opacity": "svg|feDropShadow",
    "effect.deviation": "svg|feDropShadow, svg|feGaussianBlur",
    "effect.orient": "svg|marker",
    "effect.marker-width": "svg|marker",
    "effect.marker-height": "svg|marker",
    "effect.marker-units": "svg|marker",
    "effect.ref-x": "svg|marker",
    "effect.ref-y": "svg|marker",
    "style.flood-color": "svg|feDropShadow",
    "style.flood-opacity": "svg|feDropShadow",
}
"""Each attribute row only a non-exact element holds, and the elements that hold it."""


def _card() -> DriverCard:
    card = load_card(CARD.read_bytes(), origin="driver_path", source=str(CARD))
    assert isinstance(card, DriverCard)
    return card


def _measured(tmp_path: Path) -> PptxCompiler:
    """The golden's face, `Probe Sans`, so every text is measured."""
    fonts = tmp_path / "fonts"
    write_font(fonts, "probe.ttf", tiny_font("Probe Sans"))
    return PptxCompiler(font_dirs=[str(fonts)])


def _docs() -> list[Any]:
    compiler = PptxCompiler()
    return [
        compiler.carrier(f"il/{name}", (GOLDEN / "il" / name).read_text(encoding="utf-8"))
        for name in UNITS
    ]


def test_the_golden_is_written_against_the_table_that_ships() -> None:
    """A table change moves the digest, and the golden is regenerated with it."""
    il = tomllib.loads((GOLDEN / "il" / "il.toml").read_text(encoding="utf-8"))
    assert il["constructs_digest"] == table().digest()


def test_every_declared_law_is_checked_or_says_why_not(tmp_path: Path) -> None:
    report = run_target(
        _measured(tmp_path),
        _card(),
        table(),
        GOLDEN,
        workdir=tmp_path / "work",
        reader=PptxReader(),
    )
    assert (report.target, report.gate) == ("pptx", GateStatus.MANUAL_REQUIRED)
    assert {o.law: o.status for o in report.laws} == {
        "r1": "checked",
        "r2": "checked",
        "r3": "unknown",
        "r4": "unknown",
        "r5": "unknown",
        "r6": "unknown",
        "r7": "checked",
    }
    assert report.law("r1").verdict is Verdict.PASS, "part and byte, twice, one package"
    assert report.law("r2").verdict is Verdict.PASS, "every address read back, in place"
    assert report.law("r7").verdict is Verdict.PASS
    r5 = report.law("r5")
    assert r5.result is not None and r5.result.passed, "every exact row used, and seen"
    assert "ow.el exempt" in r5.reason
    assert "project = false" in report.law("r3").reason
    assert "compiled from IL alone" in report.law("r4").reason
    assert report.verdict is Verdict.UNKNOWN, "R3, R4, R5's reader clauses and R6 wait"


def test_unmeasured_the_golden_is_unverified_and_nothing_is_lowered(tmp_path: Path) -> None:
    """Without the face its text names, a skipped measurement keeps the gate from passing."""
    report = run_target(
        PptxCompiler(), _card(), table(), GOLDEN, workdir=tmp_path / "work", reader=PptxReader()
    )
    assert report.gate is GateStatus.UNVERIFIED
    assert not (tmp_path / "work" / "r1-a").exists()


def test_without_a_reader_r2_says_why_not(tmp_path: Path) -> None:
    report = run_target(_measured(tmp_path), _card(), table(), GOLDEN, workdir=tmp_path / "work")
    r2 = report.law("r2")
    assert (r2.status, r2.reason) == (
        "unknown",
        "r2 reads the artefact back, and no read_back driver was given",
    )
    assert "compiled from IL alone" in report.law("r4").reason, "with a reader or without"


class _Forgetful(PptxReader):
    """A read_back that loses one address: R2 must say which."""

    def parse(self, unit: Any, parts: Any, io: Any) -> Any:
        result = super().parse(unit, parts, io)
        [ref] = result.produced
        body = ref.inline if ref.inline is not None else io.blobs.open(ref.blob).read()
        lost = body.replace(b',"x":{"x.ow.el":"u02/e9"}', b"")
        return DriverResult(outcome="ok", produced=(ArtifactRef.of("doc_fragment", lost, io),))


def test_a_reader_that_loses_an_address_fails_r2_naming_it(tmp_path: Path) -> None:
    report = run_target(
        _measured(tmp_path),
        _card(),
        table(),
        GOLDEN,
        workdir=tmp_path / "work",
        reader=_Forgetful(),
    )
    r2 = report.law("r2")
    assert r2.verdict is Verdict.FAIL
    assert r2.result is not None
    assert [(f.kind, f.subject) for f in r2.result.failures] == [("missing", "u02/e9")]


def test_the_golden_uses_every_exact_row() -> None:
    """R5's third clause, stated over the fixture directly: a row it never uses is a gap."""
    used = {
        row.id
        for doc in _docs()
        for row in table().rows
        if row.selector and doc.select(row.selector)
    }
    exact = {
        r.id
        for r in table().rows
        if r.round_trip is RoundTrip.EXACT and r.disposition is not Disposition.NORMALIZE
    }
    assert exact - used == set()


def test_an_attribute_only_a_non_exact_element_holds_is_no_more_exact_than_it() -> None:
    """D805: `il_digest_rt` elides a filter primitive or a marker whole, so an attribute that only
    they hold could never move it, and the row says `normalized`, as its hosts do."""
    rows = {r.id: r for r in table().rows}
    assert {i: rows[i].round_trip for i in HOSTED} == dict.fromkeys(HOSTED, RoundTrip.NORMALIZED)
    hosts = {s.strip() for spec in HOSTED.values() for s in spec.split(",")}
    assert hosts <= set(elided(table())), "each host is elided whole"
    seen = set()
    for doc in _docs():
        for row_id, spec in HOSTED.items():
            holders = {id(n) for s in spec.split(",") for n in doc.select(s.strip())}
            for node in doc.select(rows[row_id].selector):
                assert id(node) in holders, (row_id, node.tag)
                seen.add(row_id)
    assert seen == set(HOSTED) - {"style.flood-color", "style.flood-opacity"}, (
        "the golden holds them"
    )
