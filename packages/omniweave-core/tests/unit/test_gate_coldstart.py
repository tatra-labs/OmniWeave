"""G10's constants are transcriptions, so these tests read the source document and compare.

Three kinds of test live here and they answer three different questions:

1. **Did the transcription survive?** Every number in `tools/gate_coldstart.py` came out of
   04-driver-system.md sections 4.3 and 4.4 or 02-architecture.md section 5.5. These tests parse
   those tables out of `_plan/` and compare cell for cell. A structural check would not catch a
   transposed digit, and this project's own recorded lesson is that a 1,810-line document once
   truncated to 491 and passed every structural check - so these assert content.
2. **Does the gate's arithmetic close?** Section 4.4 requires the arithmetic to be shown "so a
   reviewer can check the headroom rather than trust it", and the totals and headrooms it prints
   are re-derived from the terms rather than read from the table. One row does not close, and
   `test_the_warm_per_driver_budget_covers_its_own_cost` is a strict xfail that pins it.
3. **Does the gate refuse the right things?** A budget breach fails CI; the 250 ms hard ceiling
   degrades and never refuses; an unbaselined OS is neither. Those three are the whole point of
   the gate and each is asserted against a synthetic environment built to trip exactly one.

`_plan/` is `.gitignore`d, so every document-comparing test calls `plan.require()` first and skips
with a reason on a clean clone (13-quality.md section 2.2).
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st


def _repo_root(start: Path) -> Path:
    """The workspace root, found by walking up rather than by counting `parents[n]`."""
    for candidate in (start, *start.parents):
        if (candidate / "tools" / "layers.toml").is_file() and (candidate / "packages").is_dir():
            return candidate
    message = f"no omniweave workspace root above {start}"
    raise RuntimeError(message)


REPO_ROOT = _repo_root(Path(__file__).resolve())
TOOL_PATH = REPO_ROOT / "tools" / "gate_coldstart.py"

# The gate is a script in `tools/`, not a distribution, so there is no package to import it from.
# `spec_from_file_location` loads it by path - not `importlib.import_module`, which is banned
# outside `host/`, and not a `sys.path` mutation, which would leak into every later test.
_SPEC = importlib.util.spec_from_file_location("omniweave_gate_coldstart", TOOL_PATH)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover - the file is in this repository
    message = f"cannot load {TOOL_PATH}"
    raise RuntimeError(message)
gate = importlib.util.module_from_spec(_SPEC)
# Registered before execution because `@dataclass(slots=True)` resolves annotations through
# `sys.modules[cls.__module__].__dict__`; a module executed outside `sys.modules` fails there
# with an `AttributeError` on `None`, several frames away from the cause.
sys.modules[_SPEC.name] = gate
_SPEC.loader.exec_module(gate)


# ---------------------------------------------------------------------------
# Reading a markdown table out of a plan document
# ---------------------------------------------------------------------------


def _table_after(text: str, header_prefix: str) -> list[list[str]]:
    """The rows of the first markdown table whose header line starts with `header_prefix`.

    Returns body cells only - the header and the `|---|` separator are dropped - with each cell
    stripped. Line-oriented on purpose: the alternative is a markdown parser, and a dependency in
    a test that exists to prove a document says what a constant claims would be its own risk.
    """
    rows: list[list[str]] = []
    collecting = False
    for line in text.splitlines():
        stripped = line.strip()
        if not collecting:
            if stripped.startswith(header_prefix):
                collecting = True
            continue
        if not stripped.startswith("|"):
            break
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if all(set(cell) <= {"-", ":"} for cell in cells):
            continue
        rows.append(cells)
    return rows


def _plain(cell: str) -> str:
    """A markdown cell as plain text: backticks and bold markers removed, spaces collapsed."""
    return re.sub(r"\s+", " ", cell.replace("`", "").replace("**", "")).strip()


_NUMBER = re.compile(r"\d+(?:\.\d+)?")

# The plan writes the per-card product as "20 <U+00D7> 0.38". The sign is folded to an
# ASCII `x` before matching rather than written into a source literal: ruff's RUF001 rejects an
# ambiguous-unicode character in source, and this file is not one of the two the repository
# exempts (06-structure-extraction.md section 1.7 owns those, and for a different reason).
_MULTIPLICATION_SIGN = chr(0x00D7)
_PRODUCT = re.compile(r"(\d+)\s*x\s*(\d+(?:\.\d+)?)")


def _numbers(cell: str) -> list[float]:
    return [float(match.group()) for match in _NUMBER.finditer(cell)]


def _budget_rows(plan_text: str) -> list[list[str]]:
    return _table_after(plan_text, "| scenario | fixed | per-card |")


def _step_rows(plan_text: str) -> list[list[str]]:
    return _table_after(plan_text, "| # | step | mechanism | cost |")


# ---------------------------------------------------------------------------
# 1. The transcription, against the document
# ---------------------------------------------------------------------------


def test_the_six_budget_rows_are_the_plan_s_six_rows(plan) -> None:
    """`DISCOVERY_BUDGET`'s scenarios and count match section 4.4's table exactly."""
    plan.require()
    rows = _budget_rows(plan.text("04-driver-system.md"))
    assert len(rows) == len(gate.DISCOVERY_BUDGET) == 6, rows
    for row, transcribed in zip(rows, gate.DISCOVERY_BUDGET, strict=True):
        assert _plain(row[0]) == transcribed.scenario


def test_every_budget_and_headroom_matches_the_plan_cell_for_cell(plan) -> None:
    """Budget, headroom, fixed terms, per-card terms and total, per row, against the document."""
    plan.require()
    rows = _budget_rows(plan.text("04-driver-system.md"))
    for row, transcribed in zip(rows, gate.DISCOVERY_BUDGET, strict=True):
        scenario, fixed_cell, per_card_cell, total_cell, budget_cell, headroom_cell = row
        where = _plain(scenario)

        budget = _numbers(_plain(budget_cell))
        assert budget[0] == transcribed.budget_ms, f"{where}: budget"

        headroom = _numbers(headroom_cell)
        assert (headroom[0] if headroom else None) == transcribed.headroom, f"{where}: headroom"

        total = _numbers(total_cell)
        assert (total[0] if total else None) == transcribed.total_ms, f"{where}: total"

        fixed = _numbers(fixed_cell)
        if len(fixed) > 1 and fixed[-1] == pytest.approx(sum(fixed[:-1])):
            fixed = fixed[:-1]  # "16.3 + 1.2 + 0.2 = 17.7" prints its own sum
        assert tuple(fixed) == transcribed.fixed_terms, f"{where}: fixed terms"

        product = _PRODUCT.search(per_card_cell.replace(_MULTIPLICATION_SIGN, "x"))
        if product is not None:
            assert int(product.group(1)) == transcribed.cards, f"{where}: cards"
            assert (float(product.group(2)),) == transcribed.per_card_terms, f"{where}: per card"
        else:
            assert tuple(_numbers(per_card_cell)) == transcribed.per_card_terms, f"{where}: terms"
            assert transcribed.cards is None, f"{where}: cards"


def test_the_nine_step_costs_are_the_plan_s_nine_steps(plan) -> None:
    """`DISCOVERY_STEPS` matches section 4.3's table: number, step, mechanism and cost cell."""
    plan.require()
    rows = _step_rows(plan.text("04-driver-system.md"))
    assert len(rows) == len(gate.DISCOVERY_STEPS) == 9, rows
    for row, step in zip(rows, gate.DISCOVERY_STEPS, strict=True):
        number, name, mechanism, cost = row
        assert int(number) == step.number
        assert _plain(name) == step.step
        assert _plain(mechanism) == step.mechanism
        assert _plain(cost) == step.cost


def test_the_per_card_terms_are_the_step_costs_they_claim_to_be() -> None:
    """0.38 cold is step 7 + step 8; 0.08 warm is step 6 + step 8. Not two free-floating numbers.

    Section 4.3's steps 6 and 7 are alternatives - the card cache hit and the card cache miss -
    and section 4.4's two per-card figures are each one of them plus step 8's per-card read. If
    that decomposition is wrong, the budget rows are unrelated to the step table they were
    derived from, and no amount of matching the printed totals would show it.
    """
    steps = {step.number: step for step in gate.DISCOVERY_STEPS}
    cold = round(steps[7].per_card_ms + steps[8].per_card_ms, 2)
    warm = round(steps[6].per_card_ms + steps[8].per_card_ms, 2)
    assert cold == 0.38
    assert warm == 0.08
    assert gate.DISCOVERY_BUDGET[0].per_card_ms == cold
    assert gate.DISCOVERY_BUDGET[1].per_card_ms == cold
    assert gate.DISCOVERY_BUDGET[2].per_card_ms == warm
    assert gate.DISCOVERY_BUDGET[3].per_card_ms == cold
    assert gate.DISCOVERY_BUDGET[4].per_card_ms == warm


def test_the_cold_start_ceilings_match_the_d1_block(plan) -> None:
    """`COLD_START_CEILINGS` matches 02-architecture.md section 5.5's COLD-START BUDGETS block."""
    plan.require()
    text = plan.text("02-architecture.md")
    start = text.index("COLD-START BUDGETS")
    block = text[start : text.index("MEASURED DISCOVERY COSTS", start)]
    pattern = re.compile(r"^\s{2}(?P<subject>\S.*?)\s{2,}<=\s*(?P<ms>\d+) ms", re.MULTILINE)
    found = {
        match.group("subject").strip(): float(match.group("ms"))
        for match in pattern.finditer(block)
    }
    assert found, block
    transcribed = {row.subject: row.ceiling_ms for row in gate.COLD_START_CEILINGS}
    assert found == transcribed


def test_the_reference_machine_is_the_one_the_numbers_came_from(plan) -> None:
    """328 distributions, Windows, 3.11.9, warm - and 15.3 ms for step 1 on it."""
    plan.require()
    text = plan.text("04-driver-system.md")
    assert "**328 installed distributions**, warm" in text
    assert "Windows / 3.11.9" in text
    assert gate.REFERENCE_MACHINE.installed_distributions == 328
    assert gate.REFERENCE_MACHINE.operating_system == "Windows"
    assert gate.REFERENCE_MACHINE.python == "3.11.9"
    assert gate.REFERENCE_MACHINE.thermal_state == "warm"
    assert gate.DISCOVERY_STEPS[0].fixed_ms == 15.3


def test_discovery_slow_is_a_member_of_the_closed_degradation_kind_literal(plan) -> None:
    """The kind this gate names must be one of 15-observability's twenty-seven, not a new one."""
    plan.require()
    text = plan.text("15-observability.md")
    assert f'"{gate.HARD_CEILING_KIND}"' in text
    assert "TWENTY-SEVEN, closed" in text
    hits = plan.grep(r"\| 9 \| `discovery_slow`")
    assert hits, "15-observability.md section 6.3's register row 9 should be discovery_slow"


def test_the_hard_ceiling_is_250_ms_and_the_plan_says_it_is_not_a_failure(plan) -> None:
    plan.require()
    text = plan.text("04-driver-system.md")
    assert "**250 ms**" in text
    assert "It is **not** a failure" in text
    assert gate.HARD_CEILING_MS == 250.0
    assert gate.DISCOVERY_BUDGET[-1].budget_ms == gate.HARD_CEILING_MS


def test_the_measurement_protocol_is_the_plan_s(plan) -> None:
    """Best-of-five after two warm-ups, 25% band - 11-repo-layout.md section 6.4, verbatim."""
    plan.require()
    # Whitespace-normalised over the whole document rather than line-grepped: the phrase is
    # hard-wrapped across two lines in section 6.4, and a line-oriented grep would report the
    # document had stopped saying it.
    text = re.sub(r"\s+", " ", plan.text("11-repo-layout.md"))
    assert "best-of-five after two warm-up runs" in text
    assert "25% band" in text
    assert "the module count from" in text
    assert gate.WARMUP_RUNS == 2
    assert gate.MEASURED_RUNS == 5
    assert gate.BASELINE_TOLERANCE_PCT == 25
    assert plan.grep(r"coldstart-<os>-<py>\.json", documents=("11-repo-layout.md",))


def test_the_module_cites_the_loci_it_transcribes_from() -> None:
    """A constant without its locus is a number nobody can check. The docstring carries them."""
    source = TOOL_PATH.read_text(encoding="utf-8")
    for locus in (
        "04-driver-system.md sections 4.3 and 4.4",
        "02-architecture.md section 5.5",
        "11-repo-layout.md sections 2.3 and 6.4",
        "16-roadmap.md's P1 exit criteria",
    ):
        assert locus in source, locus


def test_the_eval_perf_budgets_are_not_given_a_second_home_here() -> None:
    """INV-21: `eval/perf.toml`'s rows belong to `tools/gate_budgets.py`, and are cited not copied.

    The four budgets 12-performance.md section 2.4 sets under a G10 ceiling are the obvious thing
    to paste into this file, and pasting them would make two gates disagree the first time one
    moved. The docstring on `COLD_START_CEILINGS` says so; this asserts it still does.
    """
    source = TOOL_PATH.read_text(encoding="utf-8")
    assert "eval/perf.toml" in source
    assert "gate_budgets.py" in source
    assert "INV-21" in source
    assert "import.omniweave_core_ms = 62" in source  # cited inside the prose, once
    assert source.count("import.omniweave_core_ms") == 1


# ---------------------------------------------------------------------------
# 2. The arithmetic
# ---------------------------------------------------------------------------


def test_every_printed_total_and_headroom_is_reproducible_from_its_terms() -> None:
    """`check_plan_arithmetic` finds no FAIL: every sum in section 4.4 closes as printed."""
    failures = [
        finding
        for finding in gate.check_plan_arithmetic()
        if finding.severity == gate.Severity.FAIL
    ]
    assert failures == [], [str(finding) for finding in failures]


def test_the_arithmetic_line_shows_the_working_and_not_just_the_answer() -> None:
    """Section 4.4's mandate: a reviewer checks the headroom rather than trusting it."""
    row = gate.DISCOVERY_BUDGET[1]
    line = row.arithmetic()
    for fragment in ("16.3 + 1.2 + 0.2 = 17.7", "20 x 0.38", "25.3 ms", "45 ms", "1.8x"):
        assert fragment in line, line
    assert gate.DISCOVERY_BUDGET[-1].arithmetic().startswith("no sum")


def test_the_warm_328_distribution_row_is_the_tightest() -> None:
    """1.3x, and it is row 3 - the property the plan calls deliberate."""
    scenarios = [row for row in gate.DISCOVERY_BUDGET if row.computed_headroom is not None]
    tightest = min(scenarios, key=lambda row: row.computed_headroom)
    assert tightest is gate.DISCOVERY_BUDGET[2]
    assert tightest.computed_headroom == 1.3
    assert "warm" in tightest.scenario
    assert all(row.computed_headroom >= 1.3 for row in scenarios)


def test_the_tightest_row_is_reported_with_the_reason_it_is_tight() -> None:
    """The gate prints why the warm row is the one a regression shows up in first."""
    notes = [
        finding.message
        for finding in gate.check_plan_arithmetic()
        if finding.subject == "tightest scenario"
    ]
    assert len(notes) == 1
    assert "entry_points()" in notes[0]
    assert "property of the environment rather than of omniweave" in notes[0]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "04-driver-system.md section 4.4 row 5 budgets 0.06 ms for a per-driver warm cost its own "
        "terms put at 0.05 + 0.03 = 0.08 ms, where the cold row sets 0.4 ms against 0.38. The "
        "figures are transcribed verbatim rather than corrected; this xfail lands when that row "
        "is amended in the plan and DISCOVERY_BUDGET is amended with it."
    ),
)
def test_the_warm_per_driver_budget_covers_its_own_cost() -> None:
    row = gate.DISCOVERY_BUDGET[4]
    assert row.budget_ms >= row.per_card_ms


def test_the_warm_per_driver_defect_is_reported_as_a_note_and_never_as_a_failure() -> None:
    """A defect in a document this gate does not own must not make G10 permanently red."""
    findings = gate.check_plan_arithmetic()
    defects = [finding for finding in findings if "defect in the source table" in finding.message]
    assert len(defects) == 1
    assert defects[0].severity == gate.Severity.NOTE
    assert defects[0].subject == "per additional installed driver, warm"
    assert defects[0].locus == "04-driver-system.md section 4.4"
    assert gate.exit_code(tuple(findings)) == 0


@given(
    fixed=st.floats(min_value=0.0, max_value=1e6, allow_nan=False),
    cards=st.integers(min_value=0, max_value=100_000),
    per_card=st.floats(min_value=0.0, max_value=1e6, allow_nan=False),
    budget=st.floats(min_value=0.0, max_value=1e9, allow_nan=False),
)
def test_a_budget_row_never_raises_on_a_degenerate_scenario(
    fixed: float, cards: int, per_card: float, budget: float
) -> None:
    """Zero totals, zero budgets and huge card counts produce a value or `None`, never an error.

    `computed_headroom` divides. A scenario with no cost is not a scenario a gate should crash on,
    and `arithmetic()` runs on every invocation before any measurement has been taken.
    """
    row = gate.BudgetRow(
        scenario="synthetic",
        fixed_terms=(fixed,),
        cards=cards,
        per_card_terms=(per_card,),
        total_ms=None,
        budget_ms=budget,
        headroom=None,
    )
    total = row.computed_total_ms
    headroom = row.computed_headroom
    assert total is None or total >= 0.0
    assert headroom is None or headroom >= 0.0
    assert isinstance(row.arithmetic(), str)


# ---------------------------------------------------------------------------
# 3. What the gate refuses, and what it deliberately does not
# ---------------------------------------------------------------------------


def _environment(installed: int) -> object:
    return gate.Environment(
        operating_system="Linux",
        operating_system_release="6.1.0",
        machine="x86_64",
        python="3.11.9",
        python_implementation="CPython",
        installed_distributions=installed,
        runner="ow-bench-1",
    )


def _measurements(*, step_one: float, step_two: float, build: float | None) -> tuple[object, ...]:
    return (
        gate.Measurement(name=gate.STEP_ONE_SUBJECT, unit="ms", value=step_one),
        gate.Measurement(name=gate.STEP_TWO_SUBJECT, unit="ms", value=step_two),
        gate.Measurement(
            name=gate.CATALOG_SUBJECT,
            unit="ms",
            value=build,
            absent_because="" if build is not None else "Catalog is unbuilt",
        ),
    )


def test_crossing_the_hard_ceiling_degrades_and_does_not_refuse() -> None:
    """900 installed distributions gets a slow catalog and a report, not a refusal."""
    env = _environment(900)
    measurements = _measurements(step_one=280.0, step_two=9.0, build=310.0)
    findings, crossing = gate.check_discovery_budget(env, measurements)

    assert crossing is not None
    assert crossing.kind == "discovery_slow"
    assert crossing.installed_distributions == 900
    assert crossing.slowest_step == gate.STEP_ONE_SUBJECT
    assert "900 installed distributions" in crossing.message
    assert gate.STEP_ONE_SUBJECT in crossing.message
    assert crossing.to_json()["is_failure"] is False

    degraded = [f for f in findings if f.severity == gate.Severity.DEGRADED]
    assert len(degraded) == 1
    assert gate.exit_code(tuple(findings)) == 0


def test_a_budget_breach_in_the_environment_the_row_describes_fails() -> None:
    """20 installed distributions and a 30 ms build breaches row 1's 20 ms budget."""
    env = _environment(20)
    measurements = _measurements(step_one=2.0, step_two=0.2, build=30.0)
    findings, crossing = gate.check_discovery_budget(env, measurements)

    assert crossing is None
    failures = [f for f in findings if f.severity == gate.Severity.FAIL]
    assert len(failures) == 1
    assert failures[0].subject == gate.DISCOVERY_BUDGET[0].scenario
    assert "20 ms budget" in failures[0].message
    assert gate.exit_code(tuple(findings)) == 1


def test_a_row_is_not_asserted_in_an_environment_it_does_not_describe() -> None:
    """97 installed distributions is neither 20 nor 328, so no scenario row is asserted."""
    env = _environment(97)
    measurements = _measurements(step_one=8.0, step_two=1.0, build=30.0)
    findings, _ = gate.check_discovery_budget(env, measurements)

    assert [f for f in findings if f.severity == gate.Severity.FAIL] == []
    absent = [f for f in findings if f.subject == "scenario rows"]
    assert len(absent) == 1
    assert absent[0].severity == gate.Severity.ABSENT
    assert "97 installed distributions" in absent[0].message
    assert "20 and 328" in absent[0].message


def test_an_unbuilt_catalog_is_absent_and_the_floor_still_witnesses_the_ceiling() -> None:
    """No `Catalog` yet: the gate says so, falls back to steps 1+2, and still catches a crossing."""
    env = _environment(900)
    measurements = _measurements(step_one=300.0, step_two=5.0, build=None)
    findings, crossing = gate.check_discovery_budget(env, measurements)

    absent = [f for f in findings if f.subject == gate.CATALOG_SUBJECT]
    assert len(absent) == 1
    assert absent[0].severity == gate.Severity.ABSENT
    assert "Catalog is unbuilt" in absent[0].message
    assert "bounds the total from below" in absent[0].message
    assert crossing is not None
    assert crossing.measured_ms == pytest.approx(305.0)
    assert gate.exit_code(tuple(findings)) == 0


def test_a_breached_ceiling_fails_and_an_unmeasurable_subject_does_not() -> None:
    """`import omniweave_core` over 80 ms fails; a missing `ow` is ABSENT."""
    measurements = (
        gate.Measurement(name="import omniweave_core", unit="ms", value=95.0),
        gate.Measurement(name="ow --version", unit="ms", value=None, absent_because="no ow"),
        gate.Measurement(name="ow --help", unit="ms", value=None, absent_because="no ow"),
    )
    findings = gate.check_cold_start_ceilings(measurements)
    failures = [f for f in findings if f.severity == gate.Severity.FAIL]
    assert [f.subject for f in failures] == ["import omniweave_core"]
    assert "over a 80 ms ceiling" in failures[0].message
    absent = {f.subject for f in findings if f.severity == gate.Severity.ABSENT}
    assert {"ow --version", "ow --help", "ow query, warm store", "ow hook prompt, warm"} <= absent


# ---------------------------------------------------------------------------
# 4. The baseline, and the three states that are not "regressed"
# ---------------------------------------------------------------------------


def test_no_baseline_is_neither_a_pass_nor_a_regression() -> None:
    """A platform nobody has measured is unmeasured, and the finding names the fix."""
    measurements = _measurements(step_one=8.0, step_two=1.0, build=None)
    findings = gate.compare_to_baseline(None, measurements)
    assert len(findings) == 1
    assert findings[0].severity == gate.Severity.ABSENT
    assert gate.BaselineVerdict.NO_BASELINE in findings[0].message
    assert "--record-baseline" in findings[0].message
    assert gate.exit_code(tuple(findings)) == 0


def test_a_baseline_from_another_schema_is_absent_not_a_failure() -> None:
    baseline = {"baseline_schema": gate.BASELINE_SCHEMA + 1, "measurements": {}}
    findings = gate.compare_to_baseline(
        baseline, _measurements(step_one=8.0, step_two=1.0, build=None)
    )
    assert [f.severity for f in findings] == [gate.Severity.ABSENT]
    assert "re-record" in findings[0].message
    assert gate.exit_code(tuple(findings)) == 0


def _baseline(name: str, value: float) -> dict[str, object]:
    return {
        "baseline_schema": gate.BASELINE_SCHEMA,
        "measurements": {name: {"name": name, "unit": "ms", "value": value}},
    }


@pytest.mark.parametrize(
    ("recorded", "now", "verdict", "severity"),
    [
        (100.0, 100.0, "WITHIN_BAND", "NOTE"),
        (100.0, 125.0, "WITHIN_BAND", "NOTE"),
        (100.0, 125.1, "REGRESSED", "FAIL"),
        (100.0, 74.9, "IMPROVED", "NOTE"),
        (100.0, 75.0, "WITHIN_BAND", "NOTE"),
    ],
)
def test_the_25_percent_band_fails_only_above_it(
    recorded: float, now: float, verdict: str, severity: str
) -> None:
    """Exactly +25% is inside; a hair over is a regression; below the band is a re-bless prompt."""
    measurement = gate.Measurement(name=gate.STEP_ONE_SUBJECT, unit="ms", value=now)
    findings = gate.compare_to_baseline(_baseline(gate.STEP_ONE_SUBJECT, recorded), (measurement,))
    assert len(findings) == 1
    assert findings[0].severity == severity
    assert findings[0].message.startswith(verdict)


@given(
    recorded=st.floats(min_value=0.001, max_value=1e6, allow_nan=False),
    factor=st.floats(min_value=0.0, max_value=10.0, allow_nan=False),
)
def test_the_band_fails_exactly_when_the_measurement_is_above_it(
    recorded: float, factor: float
) -> None:
    """The band's only failing side is the high one, at any magnitude."""
    now = recorded * factor
    measurement = gate.Measurement(name=gate.STEP_ONE_SUBJECT, unit="ms", value=now)
    findings = gate.compare_to_baseline(_baseline(gate.STEP_ONE_SUBJECT, recorded), (measurement,))
    failed = findings[0].severity == gate.Severity.FAIL
    assert failed == (now > recorded * (1 + gate.BASELINE_TOLERANCE_PCT / 100.0))


@pytest.mark.parametrize(
    ("recorded", "now", "severity"),
    [(120.0, 121.0, "FAIL"), (120.0, 120.0, "NOTE"), (120.0, 119.0, "NOTE")],
)
def test_the_module_count_may_fall_and_never_grow(
    recorded: float, now: float, severity: str
) -> None:
    """The hard half of the split gate: a new eager import in core is what regresses."""
    name = "import omniweave_core module count"
    baseline = {
        "baseline_schema": gate.BASELINE_SCHEMA,
        "measurements": {name: {"name": name, "unit": "modules", "value": recorded}},
    }
    measurement = gate.Measurement(name=name, unit="modules", value=now)
    findings = gate.compare_to_baseline(baseline, (measurement,))
    assert findings[0].severity == severity
    assert "may fall and be re-blessed, never grow" in findings[0].message


def test_a_baselined_subject_that_stopped_being_measurable_is_absent_not_a_pass() -> None:
    """`ow` disappearing from PATH must not read as "within band" against its recorded number."""
    name = "ow --version"
    baseline = {
        "baseline_schema": gate.BASELINE_SCHEMA,
        "measurements": {name: {"name": name, "unit": "ms", "value": 118.0}},
    }
    measurement = gate.Measurement(name=name, unit="ms", value=None, absent_because="no ow")
    findings = gate.compare_to_baseline(baseline, (measurement,))
    assert findings[0].severity == gate.Severity.ABSENT
    assert "baselined at 118" in findings[0].message
    assert "no ow" in findings[0].message


def test_the_baseline_file_is_named_per_os_and_python() -> None:
    """`coldstart-<os>-<py>.json` - 11-repo-layout.md section 6.4's name, for each of the three."""
    for system, expected in (
        ("Windows", "coldstart-windows-3.11.json"),
        ("Linux", "coldstart-linux-3.11.json"),
        ("Darwin", "coldstart-darwin-3.11.json"),
    ):
        env = gate.Environment(
            operating_system=system,
            operating_system_release="x",
            machine="x86_64",
            python="3.11.9",
            python_implementation="CPython",
            installed_distributions=1,
            runner="unpinned",
        )
        assert gate.baseline_path(Path("eval/baselines"), env).name == expected


def test_coverage_reports_three_rows_and_names_the_two_this_machine_cannot_record(
    tmp_path: Path,
) -> None:
    """One machine records one row of three, and the report never rounds that up."""
    assert gate.baseline_coverage(tmp_path / "missing") == {
        "Darwin": (),
        "Linux": (),
        "Windows": (),
    }
    (tmp_path / "coldstart-linux-3.11.json").write_text("{}", encoding="utf-8")
    (tmp_path / "coldstart-linux-3.12.json").write_text("{}", encoding="utf-8")
    (tmp_path / "coldstart-plan9-3.12.json").write_text("{}", encoding="utf-8")
    coverage = gate.baseline_coverage(tmp_path)
    assert coverage == {"Darwin": (), "Linux": ("3.11", "3.12"), "Windows": ()}
    assert sum(1 for pythons in coverage.values() if pythons) == 1
    assert set(coverage) == set(gate.TARGET_OPERATING_SYSTEMS)


def test_a_recorded_baseline_carries_the_stamp_a_comparison_needs(tmp_path: Path) -> None:
    """OS, release, architecture, Python, distribution count, runner, protocol and statistic.

    Everything a later run needs to decide whether the comparison it is about to make is a
    comparison at all. A baseline missing the distribution count would let a 328-distribution
    figure be banded against a 20-distribution one with no way to notice.
    """
    env = _environment(328)
    report = gate.Report(
        recorded_at="2026-09-06T00:00:00+00:00",
        environment=env,
        measurements=_measurements(step_one=15.3, step_two=1.01, build=None),
        probe=gate.DiscoveryProbe(
            entry_points_ms=15.3,
            entry_points_found=0,
            validity_key_ms=1.01,
            installed_distributions=328,
            catalog_home=None,
            catalog_build_ms=None,
            catalog_error="unbuilt",
        ),
        coverage=gate.baseline_coverage(tmp_path),
        baseline_file=tmp_path / "coldstart-linux-3.11.json",
        baseline_present=False,
        hard_ceiling_crossing=None,
        findings=(),
    )
    path = gate.baseline_path(tmp_path, env)
    gate.write_baseline(path, report)

    raw = path.read_bytes()
    assert raw.endswith(b"\n")
    assert b"\r" not in raw, "11-repo-layout.md section 1.9 rule 2: generators write LF"

    written = json.loads(raw.decode("utf-8"))
    assert written["gate"] == "G10"
    assert written["baseline_schema"] == gate.BASELINE_SCHEMA
    assert written["tolerance_pct"] == 25
    assert written["warmup_runs"] == 2
    assert written["measured_runs"] == 5
    assert written["statistic"] == "min"
    assert written["environment"] == {
        "operating_system": "Linux",
        "operating_system_release": "6.1.0",
        "machine": "x86_64",
        "python": "3.11.9",
        "python_implementation": "CPython",
        "installed_distributions": 328,
        "runner": "ow-bench-1",
    }
    assert written["reference_machine"]["installed_distributions"] == 328
    assert len(written["budget"]) == 6
    assert gate.compare_to_baseline(written, report.measurements) != []


def test_the_written_baseline_round_trips_into_a_within_band_comparison(tmp_path: Path) -> None:
    """A baseline compared against the run that produced it is WITHIN_BAND, never a regression."""
    env = _environment(50)
    measurements = _measurements(step_one=8.0, step_two=1.0, build=None)
    report = gate.Report(
        recorded_at="2026-09-06T00:00:00+00:00",
        environment=env,
        measurements=measurements,
        probe=gate.DiscoveryProbe(
            entry_points_ms=8.0,
            entry_points_found=0,
            validity_key_ms=1.0,
            installed_distributions=50,
            catalog_home=None,
            catalog_build_ms=None,
            catalog_error="unbuilt",
        ),
        coverage={},
        baseline_file=tmp_path / "x.json",
        baseline_present=False,
        hard_ceiling_crossing=None,
        findings=(),
    )
    path = gate.baseline_path(tmp_path, env)
    gate.write_baseline(path, report)
    written = json.loads(path.read_text(encoding="utf-8"))
    findings = gate.compare_to_baseline(written, measurements)
    assert findings
    assert all(f.severity == gate.Severity.NOTE for f in findings)
    assert all(f.message.startswith(gate.BaselineVerdict.WITHIN_BAND) for f in findings)


# ---------------------------------------------------------------------------
# 5. End to end, on this machine
# ---------------------------------------------------------------------------


def test_the_gate_runs_records_one_row_and_reports_the_other_two_as_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--record-baseline` writes this OS's file and the report still says two OSes are missing.

    This is the P1 exit criterion's command, and the thing it must not do is let one file read as
    "G10 baselines for 3 OSes". It spawns interpreters - that is the only witness for a
    cold-process measurement - so it is slower than its neighbours here on purpose.
    """
    code = gate.main(["--record-baseline", "--baselines-dir", str(tmp_path)])
    assert code == 0
    written = sorted(path.name for path in tmp_path.glob("coldstart-*.json"))
    assert len(written) == 1

    payload = json.loads((tmp_path / written[0]).read_text(encoding="utf-8"))
    assert payload["environment"]["installed_distributions"] > 0
    assert payload["measurements"]["import omniweave_core"]["value"] is not None

    out = capsys.readouterr().out
    assert "NOT RECORDED" in out
    assert out.count("NOT RECORDED") == 2
    assert "with the arithmetic" in out
    assert "0.35 + 0.03 = 0.38 ms per driver" in out
    assert out.rstrip().endswith("G10: PASS (0 failing findings)")


def test_a_second_run_finds_the_recorded_baseline_and_classifies_every_subject(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """After recording, the next run compares rather than reporting NO_BASELINE.

    It asserts the *classification*, not the verdict. Whether the second run lands inside the
    25% band is a property of this machine's timing stability and not of any code under test -
    at P1 `import omniweave_core` is around 1.3 ms here and five consecutive best-of-five runs
    move by more than 25%, which is what `_noise_finding` reports and what OQ-4 records as
    uncharacterised. A test that asserted PASS would be asserting the runner was quiet.
    """
    assert gate.main(["--record-baseline", "--baselines-dir", str(tmp_path)]) == 0
    capsys.readouterr()

    report = gate.build_report(tmp_path)
    assert report.baseline_present
    assert not any(
        finding.subject == "baseline" and finding.severity == gate.Severity.ABSENT
        for finding in report.findings
    )
    verdicts = {
        gate.BaselineVerdict.WITHIN_BAND,
        gate.BaselineVerdict.REGRESSED,
        gate.BaselineVerdict.IMPROVED,
    }
    classified = {
        finding.subject
        for finding in report.findings
        if finding.locus == "11-repo-layout.md section 6.4"
        and any(finding.message.startswith(verdict) for verdict in verdicts)
    }
    assert "import omniweave_core" in classified
    assert "import omniweave_core module count" in classified
    assert gate.STEP_ONE_SUBJECT in classified
    assert gate.STEP_TWO_SUBJECT in classified


def test_a_noisier_subject_than_its_own_band_is_reported_as_such() -> None:
    """A baseline whose five recorded runs span wider than 25% says so beside its verdict."""
    name = gate.STEP_ONE_SUBJECT
    baseline = {
        "baseline_schema": gate.BASELINE_SCHEMA,
        "measurements": {
            name: {"name": name, "unit": "ms", "value": 1.0, "samples": [1.0, 1.1, 1.9]}
        },
    }
    findings = gate.compare_to_baseline(
        baseline, (gate.Measurement(name=name, unit="ms", value=1.05),)
    )
    assert len(findings) == 2
    assert findings[0].message.startswith(gate.BaselineVerdict.WITHIN_BAND)
    assert findings[1].severity == gate.Severity.NOTE
    assert "90% spread" in findings[1].message
    assert "runner jitter" in findings[1].message


def test_a_quiet_subject_gets_no_noise_note() -> None:
    """The note fires on evidence, not on every row: a tight baseline produces one finding."""
    name = gate.STEP_ONE_SUBJECT
    baseline = {
        "baseline_schema": gate.BASELINE_SCHEMA,
        "measurements": {
            name: {"name": name, "unit": "ms", "value": 100.0, "samples": [100.0, 101.0, 102.0]}
        },
    }
    findings = gate.compare_to_baseline(
        baseline, (gate.Measurement(name=name, unit="ms", value=101.0),)
    )
    assert len(findings) == 1
