"""`compile.text.owtext`: the reference target, run through the framework that gates it.

09-generation.md section 12.5 and 18-api-sketch.md section 6.2. The card loads through
`load_card()`, the table through `ConstructTable.load()` with the target's own normalizers, and
every check runs through `omniweave_core.out.compile.check()`: the framework's half, with the
target supplying only a carrier, a pack and an estimator that is absent.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path

import pytest
from omniweave_conform.harness import MemoryBlobStore, make_io
from omniweave_conform.suites.target.owtext.driver import HERE, OwTextCompiler
from omniweave_conform.suites.target.owtext.normalizers import lower_ascii
from omniweave_core.drivers.card import load_card
from omniweave_core.errors import TargetError, explain
from omniweave_core.model.enums import Kind, Quote
from omniweave_core.out.brief import BRIEF_SCHEMA, parse_brief
from omniweave_core.out.cites import CitedBlock
from omniweave_core.out.compile import CheckResult, CompileV1, check
from omniweave_core.out.constructs import ConstructTable
from omniweave_core.out.gate import GateStatus
from omniweave_core.out.job import ILBundle
from omniweave_core.out.plan import Plan
from omniweave_core.out.receipt import ArtefactDeterminism
from omniweave_core.out.roundtrip import applicable
from omniweave_ports import ArtifactKind, ProbeStatus

CONSTRUCTS = ConstructTable.load(HERE / "constructs.toml", {"lower_ascii": lower_ascii})
CARD = load_card((HERE / "driver.toml").read_bytes(), origin="driver_path", source="driver.toml")
IL_TOML = (
    'schema = "omniweave.out-il/1"\nil = "owtext/1"\nconstructs_digest = "'
    + CONSTRUCTS.digest()
    + '"\n\n[[unit]]\nid = "u01"\nord = 1\nfile = "u01.html"\n\n'
    '[[unit]]\nid = "u02"\nord = 2\nfile = "u02.html"\n'
)
CLEAN = {
    "u01.html": (
        '<section data-ow-el="u01/e1"><p data-ow-el="u01/e2" data-ow-cite="d7#1">Revenue rose</p>'
        "</section>"
    ),
    "u02.html": '<section data-ow-el="u02/e1"><p class="lead">Margins held</p></section>',
}
BRIEF = parse_brief(
    f"{BRIEF_SCHEMA}\n## canvas\n- format: 16:9\n- unit: slide\n## communication\n"
    "- primary_language: en-GB\n## direction\n## density\n- per_unit: light\n## motion\n"
    "- level: static\n## typography\n## rhythm\n## forbidden\n",
    baseline=(),
)


class _Cites:
    def __init__(self) -> None:
        self.batches: list[tuple[str, ...]] = []

    def by_cite(self, cite: str) -> CitedBlock | None:
        return self.by_cites((cite,))[cite]

    def by_cites(self, cites: tuple[str, ...]) -> Mapping[str, CitedBlock | None]:
        self.batches.append(cites)
        known = CitedBlock("d7#1", 101, 7, 1, "Revenue rose", Quote.VERBATIM, 0)
        return {c: known if c == "d7#1" else None for c in cites}


def _job(tmp_path: Path, **files: str) -> Path:
    il = tmp_path / "il"
    il.mkdir(parents=True, exist_ok=True)
    for name, text in {"il.toml": IL_TOML, **CLEAN, **files}.items():
        (il / name).write_text(text, encoding="utf-8", newline="")
    return tmp_path


def _check(
    tmp_path: Path, files: Mapping[str, str] | None = None, cites: _Cites | None = None
) -> CheckResult:
    return check(
        _job(tmp_path, **(files or {})),
        OwTextCompiler(),
        target="owtext",
        constructs=CONSTRUCTS,
        stage="final",
        cites=cites if cites is not None else _Cites(),
    )


# ---------------------------------------------------------------------------
# The card and the table
# ---------------------------------------------------------------------------


def test_the_card_names_the_table_it_ships_with() -> None:
    compile_ = dict(CARD.compile_sibling)  # type: ignore[union-attr]
    assert compile_["target"] == "owtext"
    assert compile_["constructs_digest"] == CONSTRUCTS.digest()
    assert (compile_["bake"], compile_["measure"], compile_["citations"]) == (
        "unavailable",
        "none",
        "sidecar",
    )


def test_the_cards_laws_are_the_ones_its_fidelity_permits() -> None:
    round_trip = dict(CARD.compile_sibling)["round_trip"]  # type: ignore[union-attr]
    claim = applicable(round_trip["laws"], round_trip["fidelity"])  # type: ignore[index]
    assert claim.applies == ("r1", "r5", "r6", "r7")
    assert claim.not_applicable == ("r2", "r3", "r4")


def test_the_table_is_ten_rows_and_carries_the_mandatory_three() -> None:
    ids = {row.id for row in CONSTRUCTS.rows}
    assert len(CONSTRUCTS.rows) == 10
    assert {"attr.ow-cite", "attr.ow-el", "elem.ow-manual"} <= ids


def test_every_code_the_table_names_is_registered() -> None:
    for row in CONSTRUCTS.rows:
        assert explain(row.code).symbol == row.code


def test_the_kind_map_names_real_kinds() -> None:
    kinds = tomllib.loads((HERE / "kind_map.toml").read_text(encoding="utf-8"))["kind"]
    assert {Kind(value) for value in kinds.values()} == {Kind.SECTION, Kind.PARAGRAPH}
    assert set(kinds) <= {row.id for row in CONSTRUCTS.rows}


@pytest.mark.parametrize("value", ["Lead", "LEAD", "lead", "Ärger", "Mixed Case Ünïcode", ""])
def test_the_normalizer_is_idempotent_and_ascii_only(value: str) -> None:
    once = lower_ascii(value)
    assert lower_ascii(once) == once
    assert [c for c in once if not c.isascii()] == [c for c in value if not c.isascii()]


def test_the_compiler_is_a_compile_v1_that_probes_ok() -> None:
    compiler: CompileV1 = OwTextCompiler()
    assert compiler.PORT == "compile/1"
    assert OwTextCompiler.probe(None).status is ProbeStatus.OK  # type: ignore[arg-type]
    assert compiler.measure() is None


# ---------------------------------------------------------------------------
# The rules, through the framework
# ---------------------------------------------------------------------------


def test_a_clean_bundle_passes_with_its_cites_resolved_in_one_batch_per_unit(
    tmp_path: Path,
) -> None:
    cites = _Cites()
    result = _check(tmp_path, cites=cites)
    assert (result.status, result.exit) == (GateStatus.PASSED, 0)
    assert cites.batches == [("d7#1",)]


def test_without_a_resolver_the_cite_rule_is_a_recorded_skip(tmp_path: Path) -> None:
    result = check(
        _job(tmp_path), OwTextCompiler(), target="owtext", constructs=CONSTRUCTS, stage="final"
    )
    assert (result.status, result.exit) == (GateStatus.UNVERIFIED, 64)
    assert [(s.rule, s.needs) for s in result.report.skipped_checks] == [
        ("owtext.attr.ow-cite@1", "cites")
    ]


@pytest.mark.parametrize(
    ("u01", "code"),
    [
        (
            '<section data-ow-el="u01/e1"><p>x</p><script>alert(1)</script></section>',
            "OW_TARGET_SCRIPT_FORBIDDEN",
        ),
        (
            '<section data-ow-el="u01/e1"><p data-ow-el="u01/e1">x</p></section>',
            "OW_TARGET_EL_DUPLICATE",
        ),
        (
            '<section><style>p{}</style><p id="intro">x</p></section>',
            "OW_TARGET_ID_WITH_STYLE",
        ),
        (
            '<section><p data-ow-cite="d7#1 d7#9">x</p></section>',
            "OW_TARGET_CITE_UNRESOLVED",
        ),
    ],
)
def test_each_error_rule_fails_the_gate(tmp_path: Path, u01: str, code: str) -> None:
    result = _check(tmp_path, {"u01.html": u01})
    assert result.status is GateStatus.FAILED
    assert [f.code for f in result.report.findings] == [code]


def test_an_id_without_a_style_block_is_native(tmp_path: Path) -> None:
    result = _check(tmp_path, {"u01.html": '<section><p id="intro">x</p></section>'})
    assert result.status is GateStatus.PASSED


def test_upper_case_classes_fold_into_one_warning_with_its_canonical(tmp_path: Path) -> None:
    u02 = "<section>" + "".join(f'<p class="Lead{n}">x</p>' for n in range(5)) + "</section>"
    result = _check(tmp_path, {"u02.html": u02})
    assert result.status is GateStatus.PASSED, "a normalize row is a warning, never an error"
    [finding] = result.report.findings
    assert (finding.code, finding.count, finding.canonical) == (
        "OW_TARGET_CLASS_NOT_LOWER",
        5,
        "lower-case ASCII class names",
    )
    assert finding.examples == ("Lead0", "Lead1", "Lead2")
    assert result.introduced_warning_count == 1


# ---------------------------------------------------------------------------
# lower(), postflight(), project()
# ---------------------------------------------------------------------------


def _plan(bundle: ILBundle) -> Plan:
    return Plan(
        schema="omniweave.out-plan/1",
        target="owtext",
        slug="memo",
        artifact_gen=1,
        delivery="release",
        units=bundle.units,
        unit_count=len(bundle.units),
        brief=BRIEF,
        corpus="acme",
        cites={},
        gate_status=GateStatus.PASSED,
        il_digest=bundle.il_digest,
        constructs_digest=CONSTRUCTS.digest(),
        ledger_digest="sha256:" + "0" * 64,
        brief_digest=BRIEF.digest(),
        card_sha256="sha256:" + "4" * 64,
    )


def _lowered(tmp_path: Path, **files: str) -> tuple[bytes, Plan, Path]:
    job = _job(tmp_path, **files)
    compiler = OwTextCompiler()
    bundle = ILBundle.load(job / "il", carrier=compiler.carrier, constructs=CONSTRUCTS)
    plan = _plan(bundle)
    io = make_io(MemoryBlobStore(tmp_path / "kit"), tmp_path / "io")
    result = compiler.lower(plan, bundle, None, io)  # type: ignore[arg-type]
    [ref] = result.produced
    assert ref.kind == ArtifactKind.ARTIFACT
    body = ref.inline if ref.inline is not None else b""
    path = tmp_path / "memo.txt"
    path.write_bytes(body)
    return body, plan, path


def test_lower_writes_each_unit_in_plan_order(tmp_path: Path) -> None:
    body, _, _ = _lowered(tmp_path)
    assert body == b"== u01 ==\nRevenue rose\n== u02 ==\nMargins held\n"


def test_postflight_describes_the_artefact_and_never_decides_the_gate(tmp_path: Path) -> None:
    body, plan, path = _lowered(tmp_path)
    receipt = OwTextCompiler().postflight(str(path), plan)
    assert receipt.output["bytes"] == len(body)
    assert receipt.determinism == (ArtefactDeterminism.PART, ArtefactDeterminism.BYTE)
    assert len(receipt.part_digest) == 64
    assert receipt.gate_status is plan.gate_status
    assert {c.name: c.value for c in receipt.checks}["bake_used"] == "enforced-at-build"


def test_an_unreachable_bake_is_refused_before_a_byte(tmp_path: Path) -> None:
    """Driver ruling 3: preflight check 5 against `bake = "unavailable"`."""
    shadowed = '<section><p style="text-shadow: 1px 1px #000">x</p></section>'
    with pytest.raises(TargetError, match="text-shadow") as caught:
        _lowered(tmp_path, **{"u02.html": shadowed})
    assert caught.value.code() == "OW_TARGET_BAKE_UNAVAILABLE"


def test_project_refuses_by_the_card_key() -> None:
    with pytest.raises(TargetError, match="project = false") as caught:
        OwTextCompiler().project(None, None)  # type: ignore[arg-type]
    assert caught.value.code() == "OW_TARGET_PROJECT_UNAVAILABLE"
