"""`omniweave_core.out.compile.check`: the framework's half of the compile call order, end to end.

09-generation.md section 2 (the call order, `CompileV1`'s seven methods, no `validate()`) and
section 4.3 (four stages, one report path each). The target is a small owtext-like `CompileV1`
written here: the html carrier, three rules, an optional estimator. Every cell built since D737
runs: the carrier, the ConstructTable, `ILBundle`, `run_pack()`, the report and the gate.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import ClassVar

import pytest
from omniweave_core.errors import TargetError
from omniweave_core.model.doc import Doc
from omniweave_core.out.carrier import CarrierDoc, CarrierNode
from omniweave_core.out.carrier.html import html_carrier
from omniweave_core.out.compile import check
from omniweave_core.out.constructs import ConstructTable
from omniweave_core.out.finding import Finding, Provenance, Severity
from omniweave_core.out.gate import GateStatus, gate_status
from omniweave_core.out.job import ILBundle
from omniweave_core.out.ledger import AssetLedger
from omniweave_core.out.marker import Payload, format_marker
from omniweave_core.out.plan import Plan
from omniweave_core.out.receipt import Receipt
from omniweave_core.out.report import OutReport, parse_digest
from omniweave_core.out.rules import Box, RuleCtx, RuleSpec, TextMeasure
from omniweave_ports import DriverIO, DriverResult, ProbeEnv, ProbeStatus, ProbeVerdict, Scalar

TABLE = """\
schema = "omniweave.out-constructs/1"
carrier = "html"
il = "owtext/1"
version = 1
unknown_construct = "forbidden"

[[construct]]
id = "attr.ow-cite"
selector = "@data-ow-cite"
disposition = "native"
round_trip = "exact"
canonical = "cite tokens"
maps_to = "lower.cites:sidecar"
code = "OW_TARGET_CITE_MALFORMED"
since = "0.1.0"

[[construct]]
id = "attr.ow-el"
selector = "@data-ow-el"
disposition = "native"
round_trip = "exact"
canonical = "u<NN>e<NN>"
maps_to = "lower.ids:passthrough"
code = "OW_TARGET_EL_DUPLICATE"
since = "0.1.0"

[[construct]]
id = "elem.ow-manual"
selector = "html|div[data-ow-manual]"
disposition = "native"
round_trip = "exact"
canonical = "a ManualReason"
maps_to = "lower.manual:placeholder"
code = "OW_TARGET_MANUAL_REASON_UNKNOWN"
since = "0.1.0"

[[construct]]
id = "elem.script"
selector = "html|script"
disposition = "forbidden"
round_trip = "dropped"
code = "OW_TARGET_SCRIPT_FORBIDDEN"
msg = "executable content"
since = "0.1.0"
"""
CONSTRUCTS = ConstructTable.parse(tomllib.loads(TABLE), {}, source="constructs.toml")


def rule_no_script(ctx: RuleCtx) -> Iterator[Finding]:
    assert ctx.doc is not None and ctx.unit is not None
    for n in ctx.doc.select("html|script"):
        yield Finding(
            code="OW_TARGET_SCRIPT_FORBIDDEN",
            severity=Severity.ERROR,
            provenance=Provenance.INTRODUCED,
            rule="owtext.elem.script@1",
            unit=ctx.unit.id,
            msg="<script> is forbidden",
            fix=f"ow out normalize {ctx.unit.il_path} --drop html|script",
            at=n.at,
        )


def rule_capacity(ctx: RuleCtx) -> Iterator[Finding]:
    """A measurement rule: it states its model, and an overflow is an error."""
    assert ctx.doc is not None and ctx.unit is not None
    for n in ctx.doc.select("html|p"):
        box = ctx.measure(n)
        if box is not None and box.overflow:
            yield Finding(
                code="OW_TARGET_TEXT_OVERFLOW",
                severity=Severity.ERROR,
                provenance=Provenance.INTRODUCED,
                rule="owtext.text.capacity@1",
                unit=ctx.unit.id,
                msg="single-line width per paragraph; wrapping is not modeled",
                fix=f"ow out check --stage unit --unit {ctx.unit.id}",
                at=n.at,
            )


class _Overflowing:
    """A `TextMeasure` that says every paragraph longer than 5 characters overflows."""

    def box(self, n: CarrierNode) -> Box | None:
        width = float(len(n.text_content()))
        return Box(advance=width, height=1.0, ascent=1.0, descent=0.0, lines=1, overflow=width > 5)


class _OwText:
    """A `CompileV1` with no `validate()`: the framework runs its rules."""

    PORT: ClassVar[str] = "compile/1"
    SCHEMA_VERSION: ClassVar[int] = 1
    estimator: ClassVar[TextMeasure | None] = None

    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict:  # noqa: ARG003 -- the protocol's shape.
        return ProbeVerdict(status=ProbeStatus.OK, detail="stdlib html.parser only")

    def __init__(self, **config: Scalar) -> None:
        self.config = config

    def carrier(self, path: str, text: str) -> CarrierDoc:
        return html_carrier(path, text, strict=False)

    def rules(self) -> Mapping[str, Sequence[RuleSpec]]:
        return {
            "structure": (
                RuleSpec(
                    "owtext.elem.script@1",
                    1,
                    "unit",
                    frozenset({"OW_TARGET_SCRIPT_FORBIDDEN"}),
                    rule_no_script,
                ),
            ),
            "measure": (
                RuleSpec(
                    "owtext.text.capacity@1",
                    60,
                    "node",
                    frozenset({"OW_TARGET_TEXT_OVERFLOW"}),
                    rule_capacity,
                    needs=frozenset({"measure"}),
                ),
            ),
        }

    def measure(self) -> TextMeasure | None:
        return self.estimator

    def lower(self, plan: Plan, il: ILBundle, ledger: AssetLedger, io: DriverIO) -> DriverResult:
        raise NotImplementedError

    def postflight(self, artifact: str, plan: Plan) -> Receipt:
        raise NotImplementedError

    def project(self, doc: Doc, io: DriverIO) -> ILBundle:
        raise NotImplementedError


class _Measured(_OwText):
    estimator: ClassVar[TextMeasure | None] = _Overflowing()


IL_TOML = (
    'schema = "omniweave.out-il/1"\nil = "owtext/1"\nconstructs_digest = "sha256:'
    + "7" * 64
    + '"\n\n'
    '[[unit]]\nid = "u01"\nord = 1\nfile = "u01.html"\n\n'
    '[[unit]]\nid = "u02"\nord = 2\nfile = "u02.html"\n'
)
CLEAN = {
    "u01.html": '<section data-ow-el="u01/e1"><p>short</p></section>',
    "u02.html": "<section><p>tiny</p></section>",
}


def _job(tmp_path: Path, **files: str) -> Path:
    il = tmp_path / "il"
    il.mkdir(parents=True, exist_ok=True)
    for name, text in {"il.toml": IL_TOML, **CLEAN, **files}.items():
        (il / name).write_text(text, encoding="utf-8", newline="")
    return tmp_path


def test_a_clean_bundle_passes_and_the_report_is_on_disk(tmp_path: Path) -> None:
    job = _job(tmp_path)
    result = check(job, _Measured(), target="owtext", constructs=CONSTRUCTS, stage="final")
    assert (result.status, result.exit, result.introduced_warning_count) == (
        GateStatus.PASSED,
        0,
        0,
    )
    assert result.path == job / "validation" / "final.json"
    loaded = OutReport.load(result.path)
    assert loaded is not None and loaded.gate() == (GateStatus.PASSED, 0)
    assert loaded.summary == {"units": 2, "clean": 2, "warned": 0, "blocked": 0}
    assert set(loaded.rule_timings_ms) == {"owtext.elem.script@1", "owtext.text.capacity@1"}


def test_an_error_fails_the_gate_with_its_exit(tmp_path: Path) -> None:
    job = _job(tmp_path, **{"u02.html": "<section><p>tiny</p><script>x</script></section>"})
    result = check(job, _Measured(), target="owtext", constructs=CONSTRUCTS, stage="final")
    assert (result.status, result.exit) == (GateStatus.FAILED, 8)
    assert [f.code for f in result.report.findings] == ["OW_TARGET_SCRIPT_FORBIDDEN"]
    assert result.report.findings[0].unit == "u02"


def test_the_estimator_is_the_compilers_and_ctx_measure_delegates_to_it(tmp_path: Path) -> None:
    job = _job(tmp_path, **{"u01.html": "<section><p>much too long</p></section>"})
    result = check(job, _Measured(), target="owtext", constructs=CONSTRUCTS, stage="final")
    assert [f.code for f in result.report.findings] == ["OW_TARGET_TEXT_OVERFLOW"]


def test_no_estimator_is_a_recorded_skip_and_never_a_pass(tmp_path: Path) -> None:
    """OUT3: the measurement rule cannot run, so the gate is unverified, exit 64."""
    result = check(_job(tmp_path), _OwText(), target="owtext", constructs=CONSTRUCTS, stage="final")
    assert (result.status, result.exit) == (GateStatus.UNVERIFIED, 64)
    assert [(s.rule, s.needs) for s in result.report.skipped_checks] == [
        ("owtext.text.capacity@1", "measure")
    ]


@pytest.mark.parametrize(
    ("stage", "unit", "units"),
    [("early", None, 2), ("first-unit", None, 1), ("unit", "u02", 1)],
)
def test_each_diagnostic_stage_checks_its_roster_and_is_non_final(
    tmp_path: Path, stage: str, unit: str | None, units: int
) -> None:
    job = _job(tmp_path, **{"u02.html": "<section><script>x</script></section>"})
    result = check(job, _Measured(), target="owtext", constructs=CONSTRUCTS, stage=stage, unit=unit)
    assert result.status is GateStatus.NON_FINAL
    assert result.path.name == f"{stage}.json"
    assert result.report.summary["units"] == units
    scripted = any(f.code == "OW_TARGET_SCRIPT_FORBIDDEN" for f in result.report.findings)
    assert scripted == (stage != "first-unit"), "first-unit checks u01 alone"


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"stage": "unit", "unit": "u09"}, "needs u09"),
        ({"stage": "final", "plan_units": ("u01", "u02", "u03")}, "in the plan only \\['u03'\\]"),
        ({"stage": "final", "plan_units": ("u01",)}, "in the bundle only \\['u02'\\]"),
    ],
)
def test_a_stage_without_its_roster_is_refused(
    tmp_path: Path, kwargs: dict[str, object], match: str
) -> None:
    with pytest.raises(TargetError, match=match) as caught:
        check(_job(tmp_path), _Measured(), target="owtext", constructs=CONSTRUCTS, **kwargs)  # type: ignore[arg-type]
    assert caught.value.code() == "OW_TARGET_ROSTER_MISMATCH"


def test_the_plans_roster_when_it_agrees_is_checked_normally(tmp_path: Path) -> None:
    result = check(
        _job(tmp_path),
        _Measured(),
        target="owtext",
        constructs=CONSTRUCTS,
        stage="final",
        plan_units=("u02", "u01"),
    )
    assert result.status is GateStatus.PASSED


def test_a_corrupt_marker_leaves_the_gate_unverified(tmp_path: Path) -> None:
    bad = (
        "<!-- OWC1:v1 el=u01/e1 nsig=00000000 id=k-00000000 "
        "ts=2026-09-03T11:04:00Z p=bm90IGpzb24 -->"
    )
    job = _job(
        tmp_path, **{"u01.html": f'<section data-ow-el="u01/e1">\n{bad}\n<p>short</p></section>'}
    )
    result = check(job, _Measured(), target="owtext", constructs=CONSTRUCTS, stage="final")
    assert result.status is GateStatus.UNVERIFIED
    assert [(s.rule, s.needs) for s in result.report.skipped_checks] == [("ow.marker@1", "marker")]
    assert result.report.markers == ({"el": "u01/e1", "id": "k-00000000", "state": "corrupt"},)


def test_a_pending_marker_is_reported_and_does_not_move_the_gate(tmp_path: Path) -> None:
    doc = html_carrier("il/u01.html", CLEAN["u01.html"], strict=True)
    line = format_marker(
        doc, "u01/e1", "00000000", "2026-09-03T11:04:00Z", Payload(note="x", sev="ask", by="agent")
    )
    job = _job(
        tmp_path, **{"u01.html": f'<section data-ow-el="u01/e1">\n{line}\n<p>short</p></section>'}
    )
    result = check(job, _Measured(), target="owtext", constructs=CONSTRUCTS, stage="final")
    assert result.status is GateStatus.PASSED, (
        "a marker is a delivery question, asserted at compile"
    )
    assert [m["state"] for m in result.report.markers] == ["pending"]


def test_an_edit_after_the_check_makes_the_report_stale(tmp_path: Path) -> None:
    job = _job(tmp_path)
    result = check(job, _Measured(), target="owtext", constructs=CONSTRUCTS, stage="final")
    (job / "il" / "u02.html").write_text("<section><p>edited</p></section>", encoding="utf-8")
    bundle = ILBundle.load(job / "il", carrier=_OwText().carrier, constructs=CONSTRUCTS)
    assert (
        gate_status(OutReport.load(result.path), parse_digest(bundle.il_digest))[0]
        is GateStatus.STALE
    )
