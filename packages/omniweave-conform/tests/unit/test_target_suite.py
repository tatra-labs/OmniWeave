"""The `target` suite: the reference target's laws against its golden fixture, and each law broken.

09-generation.md section 11.4. The golden fixture is `fixtures/out/golden/owtext/`. Each failing
case changes exactly one thing: the target, its card, its table or a copy of the fixture.
"""

from __future__ import annotations

import dataclasses
import hashlib
import shutil
import tomllib
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from omniweave_conform.result import Verdict
from omniweave_conform.suites.target.owtext.driver import HERE, OwTextCompiler
from omniweave_conform.suites.target.owtext.normalizers import lower_ascii
from omniweave_conform.suites.target.suite import (
    ASSETS,
    GOLDEN_CLOCK_NS,
    TargetReport,
    run_target,
)
from omniweave_core.drivers.card import DriverCard, load_card
from omniweave_core.out.constructs import ConstructTable
from omniweave_core.out.finding import Finding, Provenance, Severity
from omniweave_core.out.gate import GateStatus
from omniweave_core.out.job import ILBundle, Job
from omniweave_core.out.ledger import LedgerRow, ledger_digest, slot
from omniweave_core.out.plan import Plan, UnitOutcome
from omniweave_core.out.receipt import Receipt
from omniweave_core.out.rules import RuleSpec
from omniweave_ports import ArtifactRef, DriverResult

GOLDEN = Path(__file__).resolve().parents[4] / "fixtures" / "out" / "golden" / "owtext"
NORMALIZERS = {"lower_ascii": lower_ascii}
RAW_TABLE = tomllib.loads((HERE / "constructs.toml").read_text(encoding="utf-8"))
TABLE = ConstructTable.parse(RAW_TABLE, NORMALIZERS, source="constructs.toml")


def _card() -> DriverCard:
    card = load_card(
        (HERE / "driver.toml").read_bytes(), origin="driver_path", source="driver.toml"
    )
    assert isinstance(card, DriverCard)
    return card


CARD = _card()


def run(tmp_path: Path, **over: Any) -> TargetReport:
    return run_target(
        over.get("compiler", OwTextCompiler()),
        over.get("card", CARD),
        over.get("table", TABLE),
        over.get("golden", GOLDEN),
        workdir=tmp_path / "work",
    )


def golden_copy(tmp_path: Path, **files: str) -> Path:
    copy = tmp_path / "golden"
    shutil.copytree(GOLDEN, copy)
    for name, text in files.items():
        (copy / "il" / name).write_text(text, encoding="utf-8", newline="")
    return copy


# ---------------------------------------------------------------------------
# The reference target against its own golden fixture
# ---------------------------------------------------------------------------


def test_the_reference_target_reports_every_law(tmp_path: Path) -> None:
    report = run(tmp_path)
    assert (report.target, report.gate) == ("owtext", GateStatus.MANUAL_REQUIRED)
    assert {o.law: o.status for o in report.laws} == {
        "r1": "checked",
        "r2": "not-applicable",
        "r3": "not-applicable",
        "r4": "not-applicable",
        "r5": "unknown",
        "r6": "unknown",
        "r7": "checked",
    }
    assert report.law("r1").verdict is Verdict.PASS
    assert report.law("r7").verdict is Verdict.PASS
    r5 = report.law("r5")
    assert r5.result is not None and r5.result.passed, "clauses 3 and 4 hold"
    assert "attr.ow-el exempt" in r5.reason
    assert report.verdict is Verdict.UNKNOWN, "a law nobody could check is never a pass"


def test_the_scratch_jobdir_has_its_job_with_the_fixed_clock_and_the_pinned_cites(
    tmp_path: Path,
) -> None:
    """Rulings 10 and 11 (D784): a target may read its clock from `job.json`, and the Plan
    carries each cite at the generation `cites.json` resolves it at, as a compile pins it."""
    run(tmp_path)
    job = Job.load(tmp_path / "work" / "job")
    assert job.determinism.clock_ns == GOLDEN_CLOCK_NS
    assert dict(job.plan.cites) == {"d7#1": 1}
    assert job.plan.ledger_digest == ledger_digest([])


def test_a_goldens_assets_are_the_ledger_its_compile_reads(tmp_path: Path) -> None:
    """Ruling 9: each file under `assets/` is a frozen image, slotted for the unit naming it."""
    copy = golden_copy(tmp_path)
    data = b"GIF89a-not-read-by-owtext"
    sha = hashlib.sha256(data).hexdigest()
    (copy / ASSETS).mkdir()
    (copy / ASSETS / "logo.gif").write_bytes(data)
    u02 = (copy / "il" / "u02.html").read_text(encoding="utf-8")
    (copy / "il" / "u02.html").write_text(
        u02.replace("Margins held.", f"Margins held. {slot(sha)}"), encoding="utf-8", newline=""
    )
    run(tmp_path, golden=copy)
    job = Job.load(tmp_path / "work" / "job")
    assert job.plan.ledger_digest == ledger_digest([LedgerRow(1, sha, slot(sha), "image", "u02")])


def test_the_fixture_itself_is_never_written(tmp_path: Path) -> None:
    before = sorted(p.relative_to(GOLDEN) for p in GOLDEN.rglob("*"))
    run(tmp_path)
    assert sorted(p.relative_to(GOLDEN) for p in GOLDEN.rglob("*")) == before
    assert (tmp_path / "work" / "job" / "validation" / "final.json").is_file()


# ---------------------------------------------------------------------------
# Each law, broken one way
# ---------------------------------------------------------------------------


class _Unstable(OwTextCompiler):
    """A `lower()` that stamps a counter: two compiles of one bundle differ."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def lower(self, plan: Plan, il: ILBundle, ledger: Any, io: Any) -> Any:
        self.calls += 1
        result = super().lower(plan, il, ledger, io)
        [ref] = result.produced
        body = (ref.inline or b"") + f"build {self.calls}\n".encode()
        return DriverResult(outcome="ok", produced=(ArtifactRef.of("artifact", body, io),))


def test_an_unstable_lower_fails_r1_at_both_declared_classes(tmp_path: Path) -> None:
    report = run(tmp_path, compiler=_Unstable())
    r1 = report.law("r1").result
    assert r1 is not None
    assert [(f.kind, f.subject) for f in r1.failures] == [("differs", "byte"), ("differs", "part")]
    assert report.verdict is Verdict.FAIL


def test_a_declared_class_the_suite_cannot_measure_fails_r1(tmp_path: Path) -> None:
    capability = {**dict(CARD.compile_capability), "determinism": ["part", "byte", "render"]}
    card = dataclasses.replace(CARD, compile_capability=capability)
    r1 = run(tmp_path, card=card).law("r1").result
    assert r1 is not None
    assert [(f.kind, f.subject) for f in r1.failures] == [("unmeasured", "render")]


class _Misreported(OwTextCompiler):
    """A `postflight()` that reports every unit native, the manual one included."""

    def postflight(self, artifact: str, plan: Plan) -> Receipt:
        receipt = super().postflight(artifact, plan)
        units = dict.fromkeys(receipt.units, UnitOutcome.NATIVE)
        return dataclasses.replace(receipt, units=units, counts={UnitOutcome.NATIVE: len(units)})


def test_a_receipt_the_classifier_disagrees_with_fails_r7(tmp_path: Path) -> None:
    r7 = run(tmp_path, compiler=_Misreported()).law("r7").result
    assert r7 is not None
    assert r7.kinds() == {"receipt-disagrees"}


def test_an_exact_row_the_golden_never_uses_fails_r5(tmp_path: Path) -> None:
    """Without the manual region, `elem.ow-manual` is exact and unexercised."""
    u02 = (GOLDEN / "il" / "u02.html").read_text(encoding="utf-8")
    plain = u02.replace(
        '  <div data-ow-el="u02/e3" data-ow-manual="unverifiable_data">a chart nobody can verify'
        "</div>\n",
        "",
    )
    report = run(tmp_path, golden=golden_copy(tmp_path, **{"u02.html": plain}))
    assert report.gate is GateStatus.PASSED
    r5 = report.law("r5")
    assert r5.status == "checked" and r5.result is not None
    assert [(f.kind, f.subject) for f in r5.result.failures] == [
        ("exact-invisible", "elem.ow-manual"),
        ("exact-unexercised", "elem.ow-manual"),
    ]


def test_an_exact_row_il_digest_rt_cannot_see_fails_r5(tmp_path: Path) -> None:
    """A lossy row over `html|p` elides every paragraph, so `elem.p`'s mutation is invisible."""
    raw = {
        **RAW_TABLE,
        "construct": [
            *RAW_TABLE["construct"],
            {
                "id": "elem.p.lossy",
                "selector": "html|p",
                "disposition": "native",
                "round_trip": "lossy",
                "canonical": "a paragraph",
                "maps_to": "lower.text:paragraph",
                "code": "OW_TARGET_TEXT_INVALID",
                "since": "0.1.0",
            },
        ],
    }
    table = ConstructTable.parse(raw, NORMALIZERS, source="constructs.toml")
    r5 = run(tmp_path, table=table).law("r5")
    assert r5.status == "checked" and r5.result is not None
    assert ("exact-invisible", "elem.p") in {(f.kind, f.subject) for f in r5.result.failures}


@pytest.mark.parametrize(
    ("u01", "gate"),
    [
        (
            '<section data-ow-el="u01/e1"><p>x</p><script>alert(1)</script></section>',
            GateStatus.FAILED,
        ),
        ('<section><p data-ow-cite="d7#404">x</p></section>', GateStatus.FAILED),
    ],
)
def test_a_golden_that_fails_its_gate_lowers_nothing(
    tmp_path: Path, u01: str, gate: GateStatus
) -> None:
    report = run(tmp_path, golden=golden_copy(tmp_path, **{"u01.html": u01}))
    assert report.gate is gate
    for law in ("r1", "r5", "r6", "r7"):
        outcome = report.law(law)
        assert outcome.status == "unknown" and "lower() is unreachable" in outcome.reason
    assert not (tmp_path / "work" / "r1-a").exists()


def test_a_narrow_claim_can_pass_and_its_narrowness_is_visible(tmp_path: Path) -> None:
    """09 section 11.4: `laws = ["r1"]` is visible as a weak claim rather than an unremarked one."""
    compile_ = dict(CARD.compile_sibling)
    narrow = {**compile_, "round_trip": {**dict(compile_["round_trip"]), "laws": ["r1", "r7"]}}  # type: ignore[arg-type]
    report = run(tmp_path, card=dataclasses.replace(CARD, compile_sibling=narrow))
    assert report.verdict is Verdict.PASS
    assert [o.law for o in report.laws if o.status == "not-applicable"] == [
        "r2",
        "r3",
        "r4",
        "r5",
        "r6",
    ]


# ---------------------------------------------------------------------------
# Ruling 18 (D911): the release gate, the golden's manual units set aside
# ---------------------------------------------------------------------------

_PLAIN_U02 = (
    '<section data-ow-el="u02/e1">\n  <p data-ow-el="u02/e2">Margins held.</p>\n</section>\n'
)
_MANUAL_U01 = (
    '<section data-ow-el="u01/e1">\n'
    '  <div data-ow-el="u01/e2" data-ow-manual="unverifiable_data">a chart</div>\n</section>\n'
)


def test_the_release_is_the_golden_less_its_manual_unit_compiled_as_a_release(
    tmp_path: Path,
) -> None:
    report = run(tmp_path)
    assert (report.gate, report.release) == (GateStatus.MANUAL_REQUIRED, GateStatus.PASSED)
    release = tmp_path / "work" / "release"
    assert sorted(p.name for p in (release / "il").iterdir()) == ["il.toml", "u01.html"]
    roster = tomllib.loads((release / "il" / "il.toml").read_text(encoding="utf-8"))
    assert roster["unit"] == [{"id": "u01", "ord": 1, "file": "u01.html"}]
    assert {k: v for k, v in roster.items() if k != "unit"} == {
        k: v
        for k, v in tomllib.loads((GOLDEN / "il" / "il.toml").read_text(encoding="utf-8")).items()
        if k != "unit"
    }
    plan = Job.load(release).plan
    assert (plan.delivery, plan.gate_status, plan.unit_count) == ("release", GateStatus.PASSED, 1)


def test_a_withheld_first_unit_leaves_the_roster_renumbered(tmp_path: Path) -> None:
    golden = golden_copy(tmp_path, **{"u01.html": _MANUAL_U01, "u02.html": _PLAIN_U02})
    report = run(tmp_path, golden=golden)
    assert (report.gate, report.release) == (GateStatus.MANUAL_REQUIRED, GateStatus.PASSED)
    roster = tomllib.loads(
        (tmp_path / "work" / "release" / "il" / "il.toml").read_text(encoding="utf-8")
    )
    assert roster["unit"] == [{"id": "u02", "ord": 1, "file": "u02.html"}]


def test_a_golden_that_passes_its_own_gate_is_its_own_release(tmp_path: Path) -> None:
    report = run(tmp_path, golden=golden_copy(tmp_path, **{"u02.html": _PLAIN_U02}))
    assert (report.gate, report.release) == (GateStatus.PASSED, GateStatus.PASSED)
    assert not (tmp_path / "work" / "release").exists()


def test_with_every_unit_manual_there_is_nothing_to_release(tmp_path: Path) -> None:
    report = run(tmp_path, golden=golden_copy(tmp_path, **{"u01.html": _MANUAL_U01}))
    assert (report.gate, report.release) == (GateStatus.MANUAL_REQUIRED, GateStatus.NOT_PROVIDED)


def test_a_failed_golden_has_no_release_to_set_apart(tmp_path: Path) -> None:
    bad = '<section data-ow-el="u01/e1"><p>x</p><script>alert(1)</script></section>'
    report = run(tmp_path, golden=golden_copy(tmp_path, **{"u01.html": bad}))
    assert (report.gate, report.release) == (GateStatus.FAILED, GateStatus.FAILED)


class _TwoOrNone(OwTextCompiler):
    """A document-scope rule that refuses a roster of one: withholding the manual unit is what
    breaks the remainder, as pptx's link to the withheld slide does."""

    def rules(self) -> Mapping[str, Sequence[RuleSpec]]:
        def both(ctx: Any) -> Iterator[Finding]:
            if len(ctx.index.units) < 2:
                yield Finding(
                    code="OW_TARGET_REFERENCE_UNRESOLVED",
                    severity=Severity.ERROR,
                    provenance=Provenance.INTRODUCED,
                    rule="test.two@1",
                    unit="",
                    construct="",
                    msg="u01 names u02",
                    fix="ow out check --stage final",
                )

        spec = RuleSpec(
            "test.two@1", 90, "document", frozenset({"OW_TARGET_REFERENCE_UNRESOLVED"}), both
        )
        return {**super().rules(), "document": (spec,)}


def test_a_remainder_that_fails_its_gate_is_that_release(tmp_path: Path) -> None:
    """The golden's own gate is manual-required; set apart, the remainder is checked alone."""
    report = run(tmp_path, compiler=_TwoOrNone())
    assert (report.gate, report.release) == (GateStatus.MANUAL_REQUIRED, GateStatus.FAILED)
    assert not (tmp_path / "work" / "release-compile").exists()


class _Drafting(OwTextCompiler):
    """A `postflight()` that writes a draft receipt whatever the Plan asked for."""

    def postflight(self, artifact: str, plan: Plan) -> Receipt:
        receipt = super().postflight(artifact, plan)
        return dataclasses.replace(
            receipt, delivery="draft", gate_status=GateStatus.MANUAL_REQUIRED
        )


def test_a_release_compile_whose_receipt_is_not_a_release_is_unverified(tmp_path: Path) -> None:
    assert run(tmp_path, compiler=_Drafting()).release is GateStatus.UNVERIFIED
