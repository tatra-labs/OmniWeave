"""`omniweave_core.out.rules`: the rule runner's two passes and every way a rule can misbehave.

09-generation.md section 4.4 (the types, the bands, pass A and pass B), section 4.1 (only
`INTRODUCED`), section 14.1 (`MAX_FINDINGS_PER_RULE`) and section 14.4 (a rule that raises). The
rules are the reference target's from 18-api-sketch.md section 6.2, over the html carrier.
"""

from __future__ import annotations

import hashlib
import tomllib
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

import pytest
from omniweave_core.errors import ResourceLimit, TargetError
from omniweave_core.out import rules as rules_module
from omniweave_core.out.carrier import CarrierDoc, CarrierNode, tree
from omniweave_core.out.carrier.html import html_carrier
from omniweave_core.out.cites import NO_CITES, CiteResolver
from omniweave_core.out.constructs import ConstructTable
from omniweave_core.out.finding import Finding, Provenance, Severity
from omniweave_core.out.gate import GateStatus
from omniweave_core.out.job import ILFile
from omniweave_core.out.plan import OutUnit
from omniweave_core.out.report import OutReport
from omniweave_core.out.rules import Box, DocIndex, RuleCtx, RuleSpec, run_pack

SLOT = "a" * 64


@dataclass
class _Bundle:
    texts: dict[str, str]
    units: tuple[OutUnit, ...] = ()

    def __post_init__(self) -> None:
        self.units = tuple(
            OutUnit(id=f"u{n:02d}", ord=n, il_path=path)
            for n, path in enumerate(self.texts, start=1)
        )

    def text(self, il_path: str) -> str:
        return self.texts[il_path]


@dataclass
class _Ctx:
    doc: CarrierDoc | None
    unit: OutUnit | None
    index: DocIndex
    limits: Mapping[str, int] = field(default_factory=dict)
    cites: CiteResolver = NO_CITES

    def measure(self, n: CarrierNode) -> Box | None:  # noqa: ARG002 -- the protocol's shape.
        return None


def _mk(unit: OutUnit | None, doc: CarrierDoc | None, index: DocIndex) -> RuleCtx:
    return _Ctx(doc, unit, index)


def _carrier(path: str, text: str) -> CarrierDoc:
    return html_carrier(path, text, strict=False)


def _finding(ctx: RuleCtx, code: str, **fields: Any) -> Finding:
    base: dict[str, Any] = {
        "code": code,
        "severity": Severity.ERROR,
        "provenance": Provenance.INTRODUCED,
        "rule": "t@1",
        "unit": ctx.unit.id if ctx.unit else "",
        "msg": code,
        "fix": "ow out check --stage final",
    }
    base.update(fields)
    return Finding(**base)


def rule_no_script(ctx: RuleCtx) -> Iterator[Finding]:
    assert ctx.doc is not None
    for n in ctx.doc.select("html|script"):
        yield _finding(ctx, "OW_TARGET_SCRIPT_FORBIDDEN", at=n.at, el=n.el)


def rule_class_lower(ctx: RuleCtx) -> Iterator[Finding]:
    assert ctx.doc is not None
    for n in ctx.doc.select("@class"):
        if (n.attr("class") or "") != (n.attr("class") or "").lower():
            yield _finding(
                ctx,
                "OW_TARGET_CLASS_NOT_LOWER",
                severity=Severity.WARNING,
                examples=(n.attr("class") or "",),
            )


def rule_roster_els(ctx: RuleCtx) -> Iterator[Finding]:
    """A document rule: it sees every unit's stamped addresses, after pass A."""
    for unit in ctx.index.units:
        if not ctx.index.els.get(unit):
            yield _finding(ctx, "OW_TARGET_EL_MISSING", unit=unit, severity=Severity.WARNING)


SPECS = {
    "structure": (
        RuleSpec(
            "t.script@1", 1, "unit", frozenset({"OW_TARGET_SCRIPT_FORBIDDEN"}), rule_no_script
        ),
        RuleSpec(
            "t.class@1", 20, "node", frozenset({"OW_TARGET_CLASS_NOT_LOWER"}), rule_class_lower
        ),
    ),
    "document": (
        RuleSpec(
            "t.roster@1", 90, "document", frozenset({"OW_TARGET_EL_MISSING"}), rule_roster_els
        ),
    ),
}

U1 = '<section data-ow-el="u01/e1"><p class="A">a</p><p class="B">b</p><script>x</script></section>'
U2 = '<section><p data-ow-cite="d7#4 d7#5">c</p><img src="asset-slot:' + SLOT + '"></section>'


def _run(
    texts: dict[str, str], pack: Mapping[str, Any] = SPECS, **kwargs: Any
) -> rules_module.PackRun:
    base: dict[str, Any] = {"carrier": _carrier, "stage": "final", "met": frozenset(), "fixes": {}}
    base.update(kwargs)
    return run_pack(pack, _Bundle(texts), _mk, **base)


# ---------------------------------------------------------------------------
# RuleSpec, ruling 2
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("order", "scope", "codes", "needs", "match"),
    [
        (0, "unit", {"X"}, set(), "order is 1-89"),
        (90, "node", {"X"}, set(), "order is 1-89"),
        (89, "document", {"X"}, set(), "order is 90-99"),
        (100, "document", {"X"}, set(), "order is 90-99"),
        (1, "page", {"X"}, set(), "scope"),
        (1, "unit", set(), set(), "every code"),
        (1, "unit", {"X"}, {"fonts"}, "needs"),
    ],
)
def test_a_rule_spec_sits_in_its_scopes_band(
    order: int, scope: str, codes: set[str], needs: set[str], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        RuleSpec("r@1", order, scope, frozenset(codes), rule_no_script, needs=frozenset(needs))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The two passes
# ---------------------------------------------------------------------------


def test_pass_a_folds_each_unit_and_pass_b_reads_the_completed_index() -> None:
    run = _run({"il/u01.html": U1, "il/u02.html": U2})
    by_code = {(f.code, f.unit): f for f in run.findings.findings}
    assert by_code[("OW_TARGET_SCRIPT_FORBIDDEN", "u01")].at == "il/u01.html:1:66"
    assert by_code[("OW_TARGET_CLASS_NOT_LOWER", "u01")].count == 2, "folded per unit"
    assert by_code[("OW_TARGET_CLASS_NOT_LOWER", "u01")].examples == ("A", "B")
    assert ("OW_TARGET_EL_MISSING", "u02") in by_code, "pass B saw u02 had no address"
    assert ("OW_TARGET_EL_MISSING", "u01") not in by_code
    assert set(run.timings) == {"t.script@1", "t.class@1", "t.roster@1"}
    assert run.index.els == {"u01": frozenset({"u01/e1"}), "u02": frozenset()}
    assert run.index.cites["u02"] == frozenset({"d7#4", "d7#5"})
    assert run.index.slots["u02"] == frozenset({SLOT})
    section = html_carrier("il/u01.html", U1, strict=True).root()
    assert dict(run.index.nsigs) == {"u01/e1": section.nsig}, "D743: one nsig a stamped element"
    assert (run.index.markers, dict(run.index.value_occurrences)) == ((), {})


def test_rules_run_in_order_then_id() -> None:
    seen: list[str] = []

    def mark(name: str) -> Any:
        def rule(ctx: RuleCtx) -> Iterable[Finding]:  # noqa: ARG001
            seen.append(name)
            return ()

        return rule

    pack = {
        "b": (
            RuleSpec("b@1", 20, "unit", frozenset({"X"}), mark("b20")),
            RuleSpec("a@1", 20, "unit", frozenset({"X"}), mark("a20")),
        ),
        "a": (
            RuleSpec("z@1", 5, "unit", frozenset({"X"}), mark("z5")),
            RuleSpec("d@1", 95, "document", frozenset({"X"}), mark("d95")),
        ),
    }
    _run({"il/u01.html": "<section></section>"}, pack)
    assert seen == ["z5", "a20", "b20", "d95"]


def test_order_zero_short_circuits_one_unit_and_not_the_run() -> None:
    calls: list[str] = []

    def count(ctx: RuleCtx) -> Iterable[Finding]:
        assert ctx.unit is not None
        calls.append(ctx.unit.id)
        return ()

    pack = {"g": (RuleSpec("c@1", 1, "unit", frozenset({"X"}), count),)}
    run = _run(
        {"il/u01.html": "<section><p>a</section>", "il/u02.html": "<section></section>"}, pack
    )
    assert calls == ["u02"]
    (malformed,) = run.findings.findings
    assert (malformed.code, malformed.unit, malformed.severity) == (
        "OW_TARGET_IL_MALFORMED",
        "u01",
        Severity.ERROR,
    )
    assert malformed.at == "il/u01.html:1:14"
    assert malformed.fix.startswith("ow out check --stage unit --unit u01")


def test_a_refused_parse_is_malformed_too_and_a_ceiling_is_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run({"il/u01.html": "<!DOCTYPE html><section></section>"}, {})
    assert [f.code for f in run.findings.findings] == ["OW_TARGET_IL_MALFORMED"]
    monkeypatch.setattr(tree, "MAX_IL_FILE_BYTES", 5)
    with pytest.raises(ResourceLimit):
        _run({"il/u01.html": "<section></section>"})


# ---------------------------------------------------------------------------
# A misbehaving rule (rulings 4-6)
# ---------------------------------------------------------------------------


def test_a_forged_provenance_stops_the_run() -> None:
    def forge(ctx: RuleCtx) -> Iterable[Finding]:
        return [_finding(ctx, "X", provenance=Provenance.INHERITED)]

    with pytest.raises(TargetError) as caught:
        _run(
            {"il/u01.html": "<section></section>"},
            {"g": (RuleSpec("f@1", 1, "unit", frozenset({"X"}), forge),)},
        )
    assert caught.value.code() == "OW_TARGET_RULE_FORGED_PROVENANCE"


def test_a_rule_cannot_launder_a_framework_finding_through_the_crash_code() -> None:
    def launder(ctx: RuleCtx) -> Iterable[Finding]:
        return [_finding(ctx, "OW_TARGET_RULE_RAISED", provenance=Provenance.FRAMEWORK)]

    with pytest.raises(TargetError, match="may only emit introduced"):
        _run(
            {"il/u01.html": "<section></section>"},
            {"g": (RuleSpec("f@1", 1, "unit", frozenset({"X"}), launder),)},
        )


def test_a_rule_that_raises_is_a_framework_error_and_the_run_goes_on() -> None:
    def crash(ctx: RuleCtx) -> Iterable[Finding]:  # noqa: ARG001
        raise KeyError("boom")

    pack = {"g": (RuleSpec("c@1", 1, "unit", frozenset({"X"}), crash),), **SPECS}
    run = _run({"il/u01.html": U1}, pack)
    raised = [f for f in run.findings.findings if f.code == "OW_TARGET_RULE_RAISED"]
    assert len(raised) == 1
    assert (raised[0].provenance, raised[0].severity, raised[0].rule) == (
        Provenance.FRAMEWORK,
        Severity.ERROR,
        "c@1",
    )
    assert "KeyError" in raised[0].msg
    assert any(f.code == "OW_TARGET_SCRIPT_FORBIDDEN" for f in run.findings.findings), (
        "the run went on"
    )


def test_a_runaway_rule_is_cut_at_the_ceiling_and_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rules_module, "MAX_FINDINGS_PER_RULE", 3)

    def flood(ctx: RuleCtx) -> Iterable[Finding]:
        return [_finding(ctx, "X", el=f"u01/e{n}") for n in range(5)]

    pack = {"g": (RuleSpec("flood@1", 1, "unit", frozenset({"X"}), flood),)}
    run = _run({"il/u01.html": "<section></section>", "il/u02.html": "<section></section>"}, pack)
    assert sum(f.count for f in run.findings.findings) == 3
    assert [(t.kind, t.rule, t.before, t.after) for t in run.findings.truncations] == [
        ("rule", "flood@1", 10, 3)
    ]


# ---------------------------------------------------------------------------
# needs and final_only (ruling 7)
# ---------------------------------------------------------------------------


def test_an_unmet_need_is_one_recorded_skip_and_the_rule_never_runs() -> None:
    calls: list[str] = []

    def cites(ctx: RuleCtx) -> Iterable[Finding]:  # noqa: ARG001
        calls.append("ran")
        return ()

    pack = {
        "g": (
            RuleSpec(
                "c@1", 80, "unit", frozenset({"X"}), cites, needs=frozenset({"cites", "assets"})
            ),
        )
    }
    texts = {"il/u01.html": "<section></section>", "il/u02.html": "<section></section>"}
    run = _run(texts, pack, fixes={"cites": "ow open --corpus c1"})
    assert calls == []
    assert [(s.rule, s.needs, s.fix) for s in run.skipped] == [
        ("c@1", "assets", rules_module._NEED_FIX),
        ("c@1", "cites", "ow open --corpus c1"),
    ]
    met = _run(texts, pack, met=frozenset({"cites", "assets"}))
    assert (calls, met.skipped) == (["ran", "ran"], ())


def test_a_final_only_rule_waits_for_the_final_stage() -> None:
    calls: list[str] = []

    def late(ctx: RuleCtx) -> Iterable[Finding]:  # noqa: ARG001
        calls.append("ran")
        return ()

    pack = {"g": (RuleSpec("l@1", 95, "document", frozenset({"X"}), late, final_only=True),)}
    _run({"il/u01.html": "<section></section>"}, pack, stage="early")
    assert calls == []
    _run({"il/u01.html": "<section></section>"}, pack, stage="final")
    assert calls == ["ran"]


# ---------------------------------------------------------------------------
# The index and the report
# ---------------------------------------------------------------------------

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
id = "elem.p"
selector = "html|p"
disposition = "native"
round_trip = "exact"
canonical = "block text"
maps_to = "lower.text:paragraph"
code = "OW_TARGET_TEXT_INVALID"
since = "0.1.0"
"""


def test_construct_counts_come_from_the_table() -> None:
    table = ConstructTable.parse(tomllib.loads(TABLE), {}, source="constructs.toml")
    run = _run({"il/u01.html": U1, "il/u02.html": U2}, {}, constructs=table)
    assert run.index.construct_counts["u01"] == {"elem.p": 2, "attr.ow-el": 1}
    assert run.index.construct_counts["u02"] == {"elem.p": 1, "attr.ow-cite": 1}


def test_the_run_feeds_the_report_and_its_gate() -> None:
    texts = {"il/u01.html": U1, "il/u02.html": U2}
    files = tuple(
        ILFile(p.removeprefix("il/"), hashlib.sha256(t.encode()).hexdigest(), len(t))
        for p, t in texts.items()
    )

    def report(run: rules_module.PackRun) -> OutReport:
        return OutReport.build(
            stage="final",
            target="owtext",
            constructs_digest="sha256:" + "0" * 64,
            files=files,
            units=("u01", "u02"),
            findings=run.findings,
            skipped=run.skipped,
            timings=run.timings,
        )

    assert report(_run(texts)).gate()[0] is GateStatus.FAILED
    clean = {
        "il/u01.html": '<section data-ow-el="u01/e1"></section>',
        "il/u02.html": '<section data-ow-el="u02/e1"></section>',
    }
    assert report(_run(clean)).gate() == (GateStatus.PASSED, 0)
    pack = {
        "g": (
            RuleSpec(
                "m@1", 60, "node", frozenset({"X"}), lambda _ctx: (), needs=frozenset({"measure"})
            ),
        )
    }
    assert report(_run(clean, pack)).gate()[0] is GateStatus.UNVERIFIED, (
        "OUT3: a skip is never a pass"
    )


class _Ticks:
    """A clock that advances one millisecond a reading: the injected `Clock` (ruling 9)."""

    def __init__(self) -> None:
        self.now = 0

    def monotonic_ns(self) -> int:
        self.now += 1_000_000
        return self.now

    def wall_ns(self) -> int:
        return 0


def test_rule_timings_are_read_from_the_injected_clock() -> None:
    texts = {"il/u01.html": U1, "il/u02.html": U2}
    run = _run(texts, clock=_Ticks())
    assert run.timings == {"t.class@1": 2, "t.roster@1": 1, "t.script@1": 2}
