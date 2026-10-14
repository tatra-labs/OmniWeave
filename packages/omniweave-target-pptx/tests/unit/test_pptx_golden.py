"""`compile.pptx.native` against its golden fixture, through the conformance `target` suite. D805.

`fixtures/out/golden/pptx/` is owsvg/1's golden: two slides that use every `exact` row of the
table (R5 asks for each), a manual region (so the gate is `manual-required` and the compile a
draft), a cite with its kind and span, and a frozen picture. Its text names `Probe Sans`, the face
`fontkit` writes, so the measurement band runs rather than skips and the gate is not `unverified`.
Its `edit/` is `u02` with one word changed, which R4(b) recompiles (D808).
"""

from __future__ import annotations

import dataclasses
import shutil
import tomllib
import zipfile
from collections import Counter
from io import BytesIO
from pathlib import Path
from typing import Any

from fontkit import tiny_font, write_font  # type: ignore[import-not-found]  # tests/fontkit.py
from omniweave_conform.result import Verdict
from omniweave_conform.suites.target.suite import run_target
from omniweave_core.drivers.card import DriverCard, load_card
from omniweave_core.out.constructs import Disposition, RoundTrip
from omniweave_core.out.gate import GateStatus
from omniweave_core.out.job import elided
from omniweave_core.out.opc import write_opc
from omniweave_core.out.plan import UnitOutcome
from omniweave_ports import ArtifactKind, ArtifactRef, DriverResult
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
    return PptxCompiler(font_dir=str(fonts))


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
        "r4": "checked",
        "r5": "unknown",
        "r6": "unknown",
        "r7": "checked",
    }
    assert report.law("r1").verdict is Verdict.PASS, "part and byte, twice, one package"
    assert report.law("r2").verdict is Verdict.PASS, "every address read back, in place"
    assert report.law("r7").verdict is Verdict.PASS
    assert report.law("r4").verdict is Verdict.PASS, "D808: zero edits copy, an edit stays local"
    r5 = report.law("r5")
    assert r5.result is not None and r5.result.passed, "every exact row used, and seen"
    assert "ow.el exempt" in r5.reason
    assert "project = false" in report.law("r3").reason
    assert report.verdict is Verdict.UNKNOWN, "R3, R5's reader clauses and R6 wait"


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
    assert report.law("r4").verdict is Verdict.PASS, "R4 reads nothing back"


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


class _Drifting(PptxCompiler):
    """A compile whose next generation moves a copied slide's bytes: R4 must say which."""

    def lower(self, plan: Any, il: Any, ledger: Any, io: Any) -> Any:
        result = super().lower(plan, il, ledger, io)
        if plan.artifact_gen == 1:
            return result
        [ref] = [r for r in result.produced if r.kind == ArtifactKind.ARTIFACT]
        body = ref.inline if ref.inline is not None else io.blobs.open(ref.blob).read()
        with zipfile.ZipFile(BytesIO(body)) as zf:
            members = {i.filename: zf.read(i) for i in zf.infolist()}
        members["ppt/slides/slide1.xml"] += b"\n"
        drifted = ArtifactRef.of("artifact", write_opc(members), io)
        rest = tuple(r for r in result.produced if r is not ref)
        return DriverResult(outcome="ok", produced=(drifted, *rest))


def test_a_copied_part_that_moved_fails_r4_naming_its_unit(tmp_path: Path) -> None:
    """D808: R4(a) and R4(b) each compare u01's slide with its source's, and both see it move."""
    fonts = tmp_path / "fonts"
    write_font(fonts, "probe.ttf", tiny_font("Probe Sans"))
    report = run_target(
        _Drifting(font_dir=str(fonts)), _card(), table(), GOLDEN, workdir=tmp_path / "work"
    )
    r4 = report.law("r4")
    assert r4.verdict is Verdict.FAIL
    assert r4.result is not None
    assert [(f.kind, f.subject) for f in r4.result.failures] == [
        ("bytes-moved", "u01"),
        ("bytes-moved", "u01"),
    ]


class _Rebuilding(PptxCompiler):
    """A compile whose next generation reports an untouched unit rebuilt."""

    def postflight(self, artifact: str, plan: Any) -> Any:
        receipt = super().postflight(artifact, plan)
        if plan.artifact_gen == 1:
            return receipt
        units = {**receipt.units, "u01": UnitOutcome.REBUILT}
        return dataclasses.replace(receipt, units=units, counts=Counter(units.values()))


def test_a_unit_the_compile_rebuilds_untouched_fails_r4(tmp_path: Path) -> None:
    """D808: R4 reads the receipt's outcomes, so (a) finds u01 not copied and (b) not local."""
    fonts = tmp_path / "fonts"
    write_font(fonts, "probe.ttf", tiny_font("Probe Sans"))
    report = run_target(
        _Rebuilding(font_dir=str(fonts)), _card(), table(), GOLDEN, workdir=tmp_path / "work"
    )
    r4 = report.law("r4")
    assert r4.result is not None
    assert [(f.kind, f.subject) for f in r4.result.failures] == [
        ("not-copied", "u01"),
        ("not-local", "u01"),
    ]


def test_without_an_edit_r4_says_what_it_did_not_check(tmp_path: Path) -> None:
    golden = tmp_path / "golden"
    shutil.copytree(GOLDEN, golden)
    shutil.rmtree(golden / "edit")
    report = run_target(_measured(tmp_path), _card(), table(), golden, workdir=tmp_path / "work")
    r4 = report.law("r4")
    assert (r4.status, r4.reason) == (
        "unknown",
        "R4(a) holds; R4(b) recompiles the golden's edit/, which it does not carry",
    )
    assert r4.result is not None and r4.result.passed
    drifting = _Drifting(font_dir=str(tmp_path / "fonts"))
    failed = run_target(drifting, _card(), table(), golden, workdir=tmp_path / "again")
    assert failed.law("r4").verdict is Verdict.FAIL, "R4(a) failing is an answer, not unknown"


def test_an_edit_that_changes_nothing_fails_r4(tmp_path: Path) -> None:
    """D808: R4(b) over an `edit/` that leaves its unit as it was would hold of no edit."""
    golden = tmp_path / "golden"
    shutil.copytree(GOLDEN, golden)
    shutil.copyfile(golden / "il" / "u02.svg", golden / "edit" / "u02.svg")
    report = run_target(_measured(tmp_path), _card(), table(), golden, workdir=tmp_path / "work")
    r4 = report.law("r4")
    assert r4.result is not None
    assert [(f.kind, f.subject) for f in r4.result.failures] == [("unedited", "u02")]


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
