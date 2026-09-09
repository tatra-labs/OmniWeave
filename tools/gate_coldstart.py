"""G10 - cold start and the driver discovery cost budget, with the arithmetic shown.

**Two mechanisms live here and they are deliberately not the same mechanism.**

1. **The budgets are absolute and apply everywhere.** They are the charter's D1 cold-start
   ceilings (02-architecture.md section 5.5, 11-repo-layout.md section 2.3) and the six-row
   discovery cost budget of 04-driver-system.md section 4.4, which extends D1 as erratum E4
   because D1's single row - `driver discovery, 20 installed <= 20 ms` - cannot tell a
   20-distribution environment from a 328-distribution one, where step 1 alone costs 15.3 ms.
   A breach of one of these **fails CI on every machine**, because the number is a property of
   omniweave rather than of the runner.
2. **The per-OS baseline is for regression detection only.** 11-repo-layout.md section 6.4 splits
   G10 in two because a timing gate on a shared runner is otherwise a coin toss: the **hard**
   assertion is a deterministic module count from `python -X importtime -c "import
   omniweave_core"`, and the wall-clock assertion is a **25% band** against
   `eval/baselines/coldstart-<os>-<py>.json`, best-of-five after two warm-up runs. A baseline
   answers "did this change make it slower *here*", never "is this fast enough".

Conflating the two is the failure this docstring exists to prevent. A budget breach is a refusal.
A baseline drift is a regression report about one machine. And an environment with no recorded
baseline for its OS is **neither**: it is unmeasured, it says so, and it does not silently pass
(see `BaselineVerdict`).

**Measurement honesty.** This project asserts no number a measurement has not produced. Every
constant below is *transcribed* from a plan document and is labelled with its locus; every number
in the MEASURED section of a report was produced by this process on this machine, and the report
stamps the OS, the machine architecture, the Python version, the installed-distribution count and
the runner label so a reader can tell which is which. Recording a baseline on one machine produces
**one** row of the three the P1 exit criterion asks for (16-roadmap.md, `uv run
tools/gate_coldstart.py --record-baseline   # G10 baselines for 3 OSes`); the report prints the
three-OS coverage table on every run so a one-file directory cannot be mistaken for three.

**The 250 ms hard ceiling is not a failure.** Crossing it records
`Degradation(kind="discovery_slow")` naming the slowest step and the installed-distribution count
(04-driver-system.md section 4.4): a user with 900 installed distributions gets a slow catalog and
a report, not a refusal. This gate reproduces that asymmetry exactly - a budget row breach sets the
exit code, a hard-ceiling crossing emits a degradation record and does not. `Degradation` itself is
15-observability.md section 6.3's twenty-seven-member type and is **not** declared here; this
module emits a `HardCeilingCrossing` carrying the subset G10 can fill.

**What it cannot measure, it says is absent.** `Catalog.build()` lives in
`omniweave_core.drivers.catalog` (04-driver-system.md section 4.7) with `omniweave_core.discovery`
listed beside it in 11-repo-layout.md section 1.3; either may be unbuilt when this runs. The child
program tries both homes, reports `absent` when neither imports, and falls back to timing the two
steps that need no omniweave code at all - `entry_points()` and the `*.dist-info` validity key,
steps 1 and 2 of section 4.3, which together are the fixed cost the tightest row is dominated by.

Run it:

    uv run tools/gate_coldstart.py                    # check against budgets + this OS's baseline
    uv run tools/gate_coldstart.py --record-baseline  # measure and write this OS's baseline row
    uv run tools/gate_coldstart.py --json             # the whole report, machine-readable

Exit codes: `0` pass (a hard-ceiling crossing, an absent subject and a missing baseline are all
passes), `1` a budget breach or a baseline regression, `2` a usage error from argparse.

Specified in 04-driver-system.md sections 4.3 and 4.4, 02-architecture.md section 5.5,
11-repo-layout.md sections 2.3 and 6.4, 12-performance.md sections 2.3 and 2.4, and
16-roadmap.md's P1 exit criteria.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess  # noqa: TID251 - G10's subjects are cold-process facts; a spawn is the witness.
import sys
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

__all__ = [
    "BASELINE_SCHEMA",
    "BASELINE_TOLERANCE_PCT",
    "COLD_START_CEILINGS",
    "DISCOVERY_BUDGET",
    "DISCOVERY_STEPS",
    "GATE",
    "HARD_CEILING_KIND",
    "HARD_CEILING_MS",
    "MEASURABLE_CEILINGS",
    "MEASURED_RUNS",
    "REFERENCE_MACHINE",
    "TARGET_OPERATING_SYSTEMS",
    "WARMUP_RUNS",
    "BaselineVerdict",
    "BudgetRow",
    "ColdStartCeiling",
    "DiscoveryProbe",
    "DiscoveryStep",
    "Environment",
    "Finding",
    "HardCeilingCrossing",
    "Measurement",
    "ReferenceMachine",
    "Report",
    "Severity",
    "baseline_coverage",
    "baseline_path",
    "build_report",
    "check_cold_start_ceilings",
    "check_discovery_budget",
    "check_plan_arithmetic",
    "compare_to_baseline",
    "exit_code",
    "main",
    "measurement_named",
    "render",
]

GATE = "G10"
"""The gate identifier `tools/gates.toml` carries, and the one this file is named beside.

11-repo-layout.md section 6.4's row reads "G10 cold start vs the per-OS baseline, 25% band + a
hard module count" and puts it in the `test` job across all nine cells. Named here so a report is
self-identifying when it is pasted into a PR without its command line.
"""


# ---------------------------------------------------------------------------
# Severity - what a finding does to the exit code, and nothing else
# ---------------------------------------------------------------------------


class Severity:
    """The four things a finding can be. Only `FAIL` moves the exit code.

    The vocabulary is small on purpose, and each member is a distinction this gate turns on:

    * `FAIL` - an absolute budget was breached, or a recorded baseline was regressed against.
      The only member CI fails on.
    * `DEGRADED` - the 250 ms hard ceiling was crossed. 04-driver-system.md section 4.4 is
      explicit that this is **not** a failure, so it is not one here either.
    * `ABSENT` - a subject could not be measured because the code implementing it is unbuilt, or
      because no baseline exists for this OS yet. Reported loudly, never silently passed, and
      never confused with a regression.
    * `NOTE` - an observation a reviewer needs and no gate can decide, including the one place the
      plan's own arithmetic does not close (see `check_plan_arithmetic`).
    """

    FAIL = "FAIL"
    DEGRADED = "DEGRADED"
    ABSENT = "ABSENT"
    NOTE = "NOTE"


@dataclass(frozen=True, slots=True)
class Finding:
    """One line of the verdict: what it is about, what happened, and the locus that settles it."""

    severity: str
    subject: str
    message: str
    locus: str = ""

    def __str__(self) -> str:
        tail = f"  [{self.locus}]" if self.locus else ""
        return f"{self.severity:<9} {self.subject}: {self.message}{tail}"

    def to_json(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "subject": self.subject,
            "message": self.message,
            "locus": self.locus,
        }


# ---------------------------------------------------------------------------
# The reference machine and the nine measured discovery steps (section 4.3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReferenceMachine:
    """The machine every cost in `DISCOVERY_STEPS` and `DISCOVERY_BUDGET` was measured on.

    Carried as data rather than as prose because the whole point of section 4.4's table is that a
    cost scales with the **installed-distribution count**, not with omniweave: comparing a figure
    measured at 328 distributions against a runner holding 47 is not a comparison, and a report
    that prints both counts is the only one a reviewer can act on.
    """

    operating_system: str
    python: str
    installed_distributions: int
    thermal_state: str

    def to_json(self) -> dict[str, object]:
        return {
            "operating_system": self.operating_system,
            "python": self.python,
            "installed_distributions": self.installed_distributions,
            "thermal_state": self.thermal_state,
        }


REFERENCE_MACHINE = ReferenceMachine(
    operating_system="Windows",
    python="3.11.9",
    installed_distributions=328,
    thermal_state="warm",
)
"""Windows / CPython 3.11.9 / 328 installed distributions, warm.

Transcribed from 04-driver-system.md section 4.3 ("the charter's reference machine"), stated
identically in 02-architecture.md section 5.5's MEASURED DISCOVERY COSTS block. Nothing in this
file was measured on it; every figure attributed to it is a transcription, which is exactly why it
is a named record and not a comment.
"""


@dataclass(frozen=True, slots=True)
class DiscoveryStep:
    """One row of `Catalog.build()`'s nine-step cost table.

    `cost` is the plan's cost cell verbatim, because three of the nine rows are not a single
    number - step 3 is per directory, step 8 is a fixed part plus a per-card part - and a reader
    checking this file against the document needs the cell, not our reading of it. `fixed_ms` and
    `per_card_ms` are that reading, for the arithmetic.
    """

    number: int
    step: str
    mechanism: str
    cost: str
    fixed_ms: float
    per_card_ms: float


DISCOVERY_STEPS: tuple[DiscoveryStep, ...] = (
    DiscoveryStep(
        number=1,
        step="enumerate entry points",
        mechanism='importlib.metadata.entry_points(group="omniweave.drivers")',
        cost="15.3 ms",
        fixed_ms=15.3,
        per_card_ms=0.0,
    ),
    DiscoveryStep(
        number=2,
        step="compute the cache validity key",
        mechanism="os.scandir + stat of every *.dist-info",
        cost="1.01 ms",
        fixed_ms=1.01,
        per_card_ms=0.0,
    ),
    DiscoveryStep(
        number=3,
        step="scan OMNIWEAVE_DRIVER_PATH",
        mechanism="os.scandir, depth 1",
        cost="~0.1 ms per directory",
        fixed_ms=0.1,
        per_card_ms=0.0,
    ),
    DiscoveryStep(
        number=4,
        step="scan .omniweave/drivers/",
        mechanism="os.scandir, depth 1",
        cost="~0.1 ms",
        fixed_ms=0.1,
        per_card_ms=0.0,
    ),
    DiscoveryStep(
        number=5,
        step="load framework tombstones",
        mechanism="package data, 6 files at release 1",
        cost="~1.2 ms",
        fixed_ms=1.2,
        per_card_ms=0.0,
    ),
    DiscoveryStep(
        number=6,
        step="per card, cache hit",
        mechanism="json.loads(driver_card_cache.card_json)",
        cost="~0.05 ms",
        fixed_ms=0.0,
        per_card_ms=0.05,
    ),
    DiscoveryStep(
        number=7,
        step="per card, cache miss",
        mechanism="locate_file + tomllib.load + validate + card_sha256",
        cost="~0.35 ms (a 4 KB card)",
        fixed_ms=0.0,
        per_card_ms=0.35,
    ),
    DiscoveryStep(
        number=8,
        step="read the probe verdict cache",
        mechanism="one os.scandir of $OMNIWEAVE_HOME/probe/ plus a read per card",
        cost="~0.1 ms + ~0.03 ms per card",
        fixed_ms=0.1,
        per_card_ms=0.03,
    ),
    DiscoveryStep(
        number=9,
        step="catalog_digest",
        mechanism="sha256(canonical(sorted rows))",
        cost="~0.02 ms",
        fixed_ms=0.02,
        per_card_ms=0.0,
    ),
)
"""`Catalog.build()`'s nine steps, in order, with the cost of each on `REFERENCE_MACHINE`.

Transcribed from 04-driver-system.md section 4.3's table. Steps 1, 2 and 5 are the fixed cost;
6-8 are per card, and the two per-card rows are alternatives - 6 is the cache **hit** and 7 the
**miss**, so a warm build pays 6 and a cold one pays 7. That is where `DISCOVERY_BUDGET`'s two
per-card figures come from: 0.38 = 0.35 + 0.03 cold, 0.08 = 0.05 + 0.03 warm.

The table is here rather than in a comment because the gate prints it: section 4.4's mandate is
that the arithmetic be shown "so a reviewer can check the headroom rather than trust it", and the
headroom is unreviewable without the step costs it is built from.
"""


# ---------------------------------------------------------------------------
# The discovery cost budget - section 4.4's six rows, and the arithmetic
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BudgetRow:
    """One scenario of the discovery cost budget, carried as its terms rather than its totals.

    The columns are stored the way the plan prints them - `fixed_terms` is `16.3 + 1.2 + 0.2` and
    not `17.7` - because `check_plan_arithmetic` re-derives the printed total and the printed
    headroom from the terms and refuses a row where they disagree. A table that stores only its
    answers can be transcribed wrongly and still look right.

    `cards`, `total_ms` and `headroom` are `None` on the three rows that state a marginal cost or
    a ceiling rather than a scenario; a `None` there is a positive assertion that the plan prints
    an em dash in that cell, not a value we failed to transcribe.
    """

    scenario: str
    fixed_terms: tuple[float, ...]
    cards: int | None
    per_card_terms: tuple[float, ...]
    total_ms: float | None
    budget_ms: float
    headroom: float | None
    note: str = ""

    @property
    def fixed_ms(self) -> float | None:
        """The sum of the fixed terms, or `None` when the row states no fixed cost."""
        return round(sum(self.fixed_terms), 1) if self.fixed_terms else None

    @property
    def per_card_ms(self) -> float | None:
        """The per-card cost, at the two decimals the plan's per-card figures carry."""
        return round(sum(self.per_card_terms), 2) if self.per_card_terms else None

    @property
    def computed_total_ms(self) -> float | None:
        """`fixed + cards x per_card`, re-derived rather than read from `total_ms`."""
        fixed, per_card = self.fixed_ms, self.per_card_ms
        if fixed is None or per_card is None or self.cards is None:
            return None
        return round(fixed + self.cards * per_card, 1)

    @property
    def computed_headroom(self) -> float | None:
        """`budget / total`, at the one decimal the plan's headroom column carries."""
        total = self.computed_total_ms
        if total is None or total <= 0:
            return None
        return round(self.budget_ms / total, 1)

    @property
    def marginal_headroom(self) -> float | None:
        """`budget / per_card`, for the two rows budgeting a marginal driver rather than a run.

        The plan prints an em dash in their headroom column, so this is not a transcription: it is
        the check that a marginal budget is at least the marginal cost it budgets. On the warm row
        it comes out below 1.0, which is the defect `check_plan_arithmetic` reports.
        """
        per_card = self.per_card_ms
        if self.cards is not None or per_card is None or per_card <= 0:
            return None
        return round(self.budget_ms / per_card, 2)

    def arithmetic(self) -> str:
        """The row's own working, as one line a reviewer can check against section 4.4."""
        total, headroom, per_card = self.computed_total_ms, self.computed_headroom, self.per_card_ms
        if total is not None and headroom is not None and per_card is not None:
            terms = " + ".join(f"{term:g}" for term in self.fixed_terms)
            fixed = f"{terms} = {self.fixed_ms:g}" if len(self.fixed_terms) > 1 else terms
            return (
                f"({fixed}) + {self.cards} x {per_card:g} = {total:g} ms"
                f"  vs {self.budget_ms:g} ms  ->  {headroom:g}x headroom"
            )
        marginal = self.marginal_headroom
        if marginal is not None and per_card is not None:
            terms = " + ".join(f"{term:g}" for term in self.per_card_terms)
            return (
                f"{terms} = {per_card:g} ms per driver"
                f"  vs {self.budget_ms:g} ms  ->  {marginal:g}x headroom"
            )
        return f"no sum: {self.budget_ms:g} ms is a ceiling, not a total"

    def to_json(self) -> dict[str, object]:
        return {
            "scenario": self.scenario,
            "fixed_terms": list(self.fixed_terms),
            "fixed_ms": self.fixed_ms,
            "cards": self.cards,
            "per_card_terms": list(self.per_card_terms),
            "per_card_ms": self.per_card_ms,
            "total_ms": self.total_ms,
            "budget_ms": self.budget_ms,
            "headroom": self.headroom,
            "arithmetic": self.arithmetic(),
            "note": self.note,
        }


DISCOVERY_BUDGET: tuple[BudgetRow, ...] = (
    BudgetRow(
        scenario="20 drivers, 20 installed distributions, cold",
        fixed_terms=(2.2,),
        cards=20,
        per_card_terms=(0.38,),
        total_ms=9.8,
        budget_ms=20.0,
        headroom=2.0,
        note="G10, unchanged",
    ),
    BudgetRow(
        scenario="20 drivers, 328 installed distributions, cold",
        fixed_terms=(16.3, 1.2, 0.2),
        cards=20,
        per_card_terms=(0.38,),
        total_ms=25.3,
        budget_ms=45.0,
        headroom=1.8,
    ),
    BudgetRow(
        scenario="20 drivers, 328 installed distributions, warm",
        fixed_terms=(17.7,),
        cards=20,
        per_card_terms=(0.08,),
        total_ms=19.3,
        budget_ms=25.0,
        headroom=1.3,
        note="the tightest row, and deliberately so",
    ),
    BudgetRow(
        scenario="per additional installed driver, cold",
        fixed_terms=(),
        cards=None,
        per_card_terms=(0.35, 0.03),
        total_ms=None,
        budget_ms=0.4,
        headroom=None,
    ),
    BudgetRow(
        scenario="per additional installed driver, warm",
        fixed_terms=(),
        cards=None,
        per_card_terms=(0.05, 0.03),
        total_ms=None,
        budget_ms=0.06,
        headroom=None,
    ),
    BudgetRow(
        scenario="hard ceiling, any environment",
        fixed_terms=(),
        cards=None,
        per_card_terms=(),
        total_ms=None,
        budget_ms=250.0,
        headroom=None,
    ),
)
"""The six rows of 04-driver-system.md section 4.4, transcribed cell for cell.

**The warm 328-distribution row is the tightest at 1.3x and that is the design.** The plan says
why, and the reason is the whole argument for gating this at all: it is "the row a regression
would show up in first, because it is dominated by a single `entry_points()` call whose cost is a
property of the environment rather than of omniweave". A regression in omniweave's own per-card
work moves the cold rows, which have 1.8-2.0x of slack to hide in; a regression in *how much of
the environment discovery touches* moves the warm row, which has 5.7 ms of slack in total.

Row 1's 20 ms is D1's original row, unchanged by E4 - the budget widens for the environments D1
did not describe, never for the one it did. Row 6's 250 ms is the hard ceiling, and it is the one
row whose breach is not a failure: see `HardCeilingCrossing`.
"""

HARD_CEILING_MS = 250.0
"""The discovery hard ceiling, in milliseconds, for any environment.

Row 6 of `DISCOVERY_BUDGET`, named separately because it is the only budget in this file whose
breach is not a refusal, and because three other things in the plan are also 250 ms - `ow --help`,
`ow query` warm and G26's warm hook p95 - so the constant a reader reaches for has to say which.
"""

HARD_CEILING_KIND = "discovery_slow"
"""The `Degradation.kind` recorded when discovery crosses `HARD_CEILING_MS`.

One of the twenty-seven closed members of 15-observability.md section 6.3's `DegradationKind`, and
row 9 of its register, whose explain command is `ow drivers explain --discovery`. The literal is
here so this gate's report can name what the runtime would record; the **type** is 15's and is not
redeclared here (INV-21).
"""


@dataclass(frozen=True, slots=True)
class HardCeilingCrossing:
    """What the runtime would record, and what this gate prints, above `HARD_CEILING_MS`.

    Not a `Degradation`: that record is 15-observability.md section 6.3's ten-field type and its
    code home is not this file. This carries the three facts 04-driver-system.md section 4.4
    requires the degradation to name - the slowest step, the installed-distribution count and the
    measured total - so a report reads the same whether the crossing was seen by a gate or by a
    user's run.

    Constructing one never sets the exit code. A user with 900 installed distributions gets a slow
    catalog and a report, not a refusal, and a gate that refused where the runtime degrades would
    be asserting a rule the framework does not hold.

    `slowest_step` is the slowest of the steps **this observer could time**. The runtime sees all
    nine of section 4.3's steps and is the authority; a gate that only reached steps 1 and 2
    names the slowest of those two and says so rather than claiming a breakdown it does not have.
    """

    kind: str
    measured_ms: float
    slowest_step: str
    installed_distributions: int

    @property
    def message(self) -> str:
        """The one sentence a human reads, naming the step and the count."""
        return (
            f"discovery took {self.measured_ms:.1f} ms, above the {HARD_CEILING_MS:g} ms hard "
            f"ceiling; slowest step {self.slowest_step!r} over "
            f"{self.installed_distributions} installed distributions"
        )

    def to_json(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "measured_ms": self.measured_ms,
            "slowest_step": self.slowest_step,
            "installed_distributions": self.installed_distributions,
            "message": self.message,
            "is_failure": False,
        }


# ---------------------------------------------------------------------------
# The charter's cold-start ceilings (D1), which are absolute everywhere
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ColdStartCeiling:
    """One row of the D1 cold-start table: a subject, its ceiling and how it is timed.

    `basis` is 12-performance.md section 1.1's vocabulary - `in_process` excludes interpreter
    startup, `spawn_inclusive` includes it - and it is a field rather than a comment because two
    rows here are only meaningful under one of the two, and a report that does not say which has
    not reported anything.
    """

    subject: str
    ceiling_ms: float
    basis: str
    gate: str
    note: str = ""

    def to_json(self) -> dict[str, object]:
        return {
            "subject": self.subject,
            "ceiling_ms": self.ceiling_ms,
            "basis": self.basis,
            "gate": self.gate,
            "note": self.note,
        }


COLD_START_CEILINGS: tuple[ColdStartCeiling, ...] = (
    ColdStartCeiling(
        subject="import omniweave_core",
        ceiling_ms=80.0,
        basis="in_process",
        gate="G10",
        note="INV-3; measured with -X importtime",
    ),
    ColdStartCeiling(
        subject="ow --version",
        ceiling_ms=150.0,
        basis="spawn_inclusive",
        gate="G10",
    ),
    ColdStartCeiling(
        subject="ow --help",
        ceiling_ms=250.0,
        basis="spawn_inclusive",
        gate="G10",
        note="the verb tree is generated data",
    ),
    ColdStartCeiling(
        subject="driver discovery, 20 installed",
        ceiling_ms=20.0,
        basis="in_process",
        gate="G10",
        note="dist-info only; imports nothing. Extended by E4 - see DISCOVERY_BUDGET",
    ),
    ColdStartCeiling(
        subject="ow query, warm store",
        ceiling_ms=250.0,
        basis="in_process",
        gate="G10",
    ),
    ColdStartCeiling(
        subject="ow hook prompt, warm",
        ceiling_ms=250.0,
        basis="spawn_inclusive",
        gate="G26",
        note="p95, not best-of-five; G26's subject and not measured here",
    ),
)
"""The charter's D1 cold-start budgets, transcribed.

Printed identically in 02-architecture.md section 5.5, 11-repo-layout.md section 2.3 and
00-vision.md V01-3. Two of the six rows are outside what this gate can measure at P1 - `ow query`
needs a warm store and `ow hook prompt` is G26's subject on a p95 rather than a best-of-five - and
both are reported ABSENT rather than quietly dropped.

**The `eval/perf.toml` budgets are deliberately not here.** 12-performance.md section 2.4 sets
`import.omniweave_core_ms = 62` +/-25%, `cold.ow_version_ms = 118` +/-25%, `cold.ow_help_ms = 190`
+/-25% and `discovery.20dists_ms = 16` +/-20% so that budget x (1 + tol) lands just inside the
ceiling and a breach fires before the gate does. That file is `tools/gate_budgets.py`'s subject
under Q-G15; copying its rows here would be INV-21's second home for one fact, and the two gates
would then disagree the first time a budget moved.
"""

MEASURABLE_CEILINGS: frozenset[str] = frozenset(
    {"import omniweave_core", "ow --version", "ow --help"}
)
"""The `COLD_START_CEILINGS` subjects this gate has an instrument for at P1.

`driver discovery, 20 installed` is checked through `DISCOVERY_BUDGET` instead, because E4's whole
point is that one number cannot describe both a 20-distribution and a 328-distribution
environment. `ow query, warm store` needs a store P1 does not build. `ow hook prompt, warm` is
G26's, on a p95 rather than a best-of-five, and a gate that quietly measured it on a different
statistic would be reporting a different number under the same name.
"""


# ---------------------------------------------------------------------------
# The baseline: what it stamps, where it lives, and the three-OS coverage claim
# ---------------------------------------------------------------------------

BASELINE_SCHEMA = 1
"""The version of the baseline file's own shape, bumped when a recorded key changes meaning.

A baseline is compared against by a later build of this gate, so a silently reshaped file is a
comparison against a field that no longer means what it did. A file whose `baseline_schema` is not
this one is reported ABSENT - unmeasured, re-record it - and never FAIL.
"""

BASELINE_TOLERANCE_PCT = 25
"""The wall-clock band, in percent, a measurement may drift from its baseline before G10 fails.

11-repo-layout.md section 6.4, and OQ-4 on the same page records that the 25% figure is
**inherited, not measured** - nobody has yet characterised the runner-class variance it absorbs.
Transcribed rather than tuned: this gate is not the place that number gets decided.
"""

WARMUP_RUNS = 2
"""Runs discarded before measuring.

11-repo-layout.md section 6.4's protocol is "best-of-five after two warm-up runs". The warm-ups
exist to warm the OS page cache and the `.pyc` tree, which is what "warm" means in every figure in
this file, `REFERENCE_MACHINE`'s included.
"""

MEASURED_RUNS = 5
"""Runs kept, of which the **minimum** is the measurement.

Best-of-N, not the mean or the median: on a shared runner the distribution's tail is other
tenants' work, and the minimum is the closest observable estimate of the cost of the code under
test. It is also the statistic that makes a 25% band meaningful, since a mean over a noisy runner
drifts by more than 25% for reasons no commit caused.
"""

TARGET_OPERATING_SYSTEMS: tuple[str, ...] = ("Darwin", "Linux", "Windows")
"""The three `platform.system()` values the P1 exit criterion's "3 OSes" names.

Sorted, and matched against the nine `test` cells of 11-repo-layout.md section 6.4. The gate
prints coverage against this tuple on every run: one machine can only ever record one of the
three, and an `eval/baselines/` directory holding one file is not "baselines for 3 OSes" however
the command that wrote it was spelled.
"""


class BaselineVerdict:
    """The four outcomes of comparing a measurement to a baseline, kept distinct on purpose.

    * `WITHIN_BAND` - measured, compared, inside +/-25%.
    * `REGRESSED` - measured, compared, above the band. The only one that fails.
    * `IMPROVED` - measured, compared, below the band. Not a failure; it is a re-bless prompt,
      because a baseline left stale hides the next regression under the old slack.
    * `NO_BASELINE` - no file for this OS and Python. **Neither a pass nor a failure**: the gate
      must not fail CI on a platform that has never been baselined, and must not pretend a
      platform it has never measured is inside a band.

    Collapsing `NO_BASELINE` into either of the other two is the specific defect this class exists
    to prevent: as a pass it makes a new OS look gated when it is not, and as a failure it makes
    adding an OS to the matrix impossible without first hand-writing a file nobody measured.
    """

    WITHIN_BAND = "WITHIN_BAND"
    REGRESSED = "REGRESSED"
    IMPROVED = "IMPROVED"
    NO_BASELINE = "NO_BASELINE"


@dataclass(frozen=True, slots=True)
class Environment:
    """The stamp on a baseline: what machine produced these numbers, and against what.

    Every field is load-bearing for a comparison. `operating_system` and `python` name the file.
    `machine` is the CPU architecture, because an arm64 and an x86-64 runner of the same OS are
    not the same measurement. `installed_distributions` is the field that makes section 4.4's
    table readable at all - a figure measured at 328 distributions and a figure measured at 47 are
    not comparable, and the report has to say so rather than divide them.

    `runner` is read from `OMNIWEAVE_RUNNER` and defaults to `"unpinned"`: 11-repo-layout.md
    section 6.4 requires the runner label to be pinned in the workflow (a **Runner class pin**) so
    that a runner-image change surfaces as one deliberate re-bless in `eval/BLESS.log` rather than
    as nine mysterious failures. It is not `platform.node()` - a developer's hostname is not a fact
    this repository wants committed, and it is not the fact the pin is asking for.
    """

    operating_system: str
    operating_system_release: str
    machine: str
    python: str
    python_implementation: str
    installed_distributions: int
    runner: str

    @property
    def python_tag(self) -> str:
        """`<major>.<minor>` - the `<py>` half of `coldstart-<os>-<py>.json`."""
        return ".".join(self.python.split(".")[:2])

    def to_json(self) -> dict[str, object]:
        return {
            "operating_system": self.operating_system,
            "operating_system_release": self.operating_system_release,
            "machine": self.machine,
            "python": self.python,
            "python_implementation": self.python_implementation,
            "installed_distributions": self.installed_distributions,
            "runner": self.runner,
        }


def baseline_path(baselines_dir: Path, env: Environment) -> Path:
    """`eval/baselines/coldstart-<os>-<py>.json` for this environment.

    The name is 11-repo-layout.md section 6.4's verbatim, lowercased: one file per (OS, Python),
    which is what makes "no baseline for this OS" an observable state rather than a missing key
    inside a shared file that a reader would have to notice.
    """
    return baselines_dir / f"coldstart-{env.operating_system.lower()}-{env.python_tag}.json"


_BASELINE_NAME = re.compile(r"^coldstart-(?P<os>[a-z0-9_]+)-(?P<py>\d+\.\d+)\.json$")


def baseline_coverage(baselines_dir: Path) -> dict[str, tuple[str, ...]]:
    """Which of `TARGET_OPERATING_SYSTEMS` have a recorded baseline, and under which Pythons.

    Printed on every run, because the P1 exit criterion says "G10 baselines for 3 OSes" and one
    machine records one. A directory with one file is one third of that criterion, and this is the
    function that refuses to let the difference go unstated.
    """
    found: dict[str, list[str]] = {name: [] for name in TARGET_OPERATING_SYSTEMS}
    if baselines_dir.is_dir():
        for path in sorted(baselines_dir.glob("coldstart-*.json")):
            match = _BASELINE_NAME.match(path.name)
            if match is None:
                continue
            for name in TARGET_OPERATING_SYSTEMS:
                if name.lower() == match.group("os"):
                    found[name].append(match.group("py"))
    return {name: tuple(sorted(pythons)) for name, pythons in found.items()}


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Measurement:
    """One measured quantity, or one stated reason it could not be measured.

    `value` is `None` exactly when `absent_because` is set, and a report renders those two states
    differently on purpose: a missing number and a number of zero are not the same claim, and this
    project's rule is that an unmeasured subject says so rather than defaulting.

    `unit` is part of the record because the baseline file is read back by a later build: a bare
    float named `import omniweave_core` is not a measurement, it is a number.
    """

    name: str
    unit: str
    value: float | None
    samples: tuple[float, ...] = ()
    absent_because: str = ""

    @property
    def measured(self) -> bool:
        return self.value is not None

    def to_json(self) -> dict[str, object]:
        return {
            "name": self.name,
            "unit": self.unit,
            "value": self.value,
            "samples": list(self.samples),
            "absent_because": self.absent_because,
        }


def measurement_named(measurements: tuple[Measurement, ...], name: str) -> Measurement | None:
    """The measurement with this name, or `None`. The name is the report's stable key."""
    for item in measurements:
        if item.name == name:
            return item
    return None


IMPORT_SUBJECT = "import omniweave_core"
MODULE_COUNT_SUBJECT = "import omniweave_core module count"
STEP_ONE_SUBJECT = "discovery step 1: entry_points"
STEP_TWO_SUBJECT = "discovery step 2: dist-info validity key"
CATALOG_SUBJECT = "Catalog.build()"


@dataclass(frozen=True, slots=True)
class DiscoveryProbe:
    """What one fresh interpreter observed about discovery on this machine.

    Steps 1 and 2 of 04-driver-system.md section 4.3 need no omniweave code, so they are measurable
    at P1 whatever else is unbuilt. `catalog_build_ms` is `None` until `Catalog` lands in one of
    its two homes, and `catalog_error` then says which of the three reasons applies - neither home
    imports, the class has no `build()`, or the call raised.
    """

    entry_points_ms: float
    entry_points_found: int
    validity_key_ms: float
    installed_distributions: int
    catalog_home: str | None
    catalog_build_ms: float | None
    catalog_error: str


# The child program that times the two discovery steps needing no omniweave code, counts the
# installed distributions, and - if either home for `Catalog` has landed - times `Catalog.build()`.
#
# It runs in a FRESH interpreter for every repetition on purpose. `importlib.metadata` keeps an
# lru_cached directory index per process, so a second `entry_points()` call in the same process
# measures that cache and not the mechanism 04-driver-system.md section 4.3 attributes 15.3 ms to.
# "Warm" in this plan means the OS page cache is warm, never that the process already did the work.
_DISCOVERY_PROBE = r"""
import json, os, sys, time
from importlib.metadata import entry_points

start = time.perf_counter()
found = list(entry_points(group="omniweave.drivers"))
entry_points_ms = (time.perf_counter() - start) * 1000.0

roots = [p for p in sys.path if p and os.path.isdir(p)]
start = time.perf_counter()
installed = 0
for root in roots:
    try:
        entries = list(os.scandir(root))
    except OSError:
        continue
    for entry in entries:
        if entry.name.endswith((".dist-info", ".egg-info")):
            try:
                entry.stat()
            except OSError:
                continue
            installed += 1
validity_key_ms = (time.perf_counter() - start) * 1000.0

home = None
build_ms = None
error = "neither omniweave_core.drivers.catalog nor omniweave_core.discovery exports Catalog"
Catalog = None
try:
    from omniweave_core.drivers.catalog import Catalog
    home = "omniweave_core.drivers.catalog"
except ImportError:
    try:
        from omniweave_core.discovery import Catalog
        home = "omniweave_core.discovery"
    except ImportError:
        Catalog = None
if Catalog is not None:
    build = getattr(Catalog, "build", None)
    if build is None:
        error = home + ".Catalog has no build()"
    else:
        try:
            start = time.perf_counter()
            build()
            build_ms = (time.perf_counter() - start) * 1000.0
            error = ""
        except Exception as exc:
            error = "{}.Catalog.build() raised {}: {}".format(home, type(exc).__name__, exc)

print(json.dumps({
    "entry_points_ms": entry_points_ms,
    "entry_points_found": len(found),
    "validity_key_ms": validity_key_ms,
    "installed_distributions": installed,
    "catalog_home": home,
    "catalog_build_ms": build_ms,
    "catalog_error": error,
}))
"""

_IMPORTTIME_LINE = re.compile(
    r"^import time:\s+(?P<self>[\d-]+)\s*\|\s+(?P<cumulative>[\d-]+)\s*\|\s*(?P<module>\S+)\s*$"
)


def _run_child(source: str, *, flags: tuple[str, ...] = ()) -> tuple[str, str]:
    """`python <flags> -c <source>` in a fresh interpreter, returning `(stdout, stderr)`.

    A fresh interpreter is not an implementation detail here: every subject this gate measures is
    a statement about what a *cold process* does, and once this process has imported
    `omniweave_core` for its own reasons neither `sys.modules` nor `-X importtime` can answer the
    question any more.
    """
    completed = subprocess.run(  # noqa: S603 - a fixed argv, no shell, argv[0] is sys.executable.
        [sys.executable, *flags, "-c", source],
        capture_output=True,
        text=True,
        check=False,
        timeout=300.0,
    )
    if completed.returncode != 0:
        message = f"child exited {completed.returncode}\n--- stderr ---\n{completed.stderr}"
        raise RuntimeError(message)
    return completed.stdout, completed.stderr


def _probe_once() -> DiscoveryProbe:
    """One fresh-interpreter discovery observation."""
    stdout, _ = _run_child(_DISCOVERY_PROBE)
    payload = json.loads(stdout.strip().splitlines()[-1])
    build_ms = payload["catalog_build_ms"]
    return DiscoveryProbe(
        entry_points_ms=float(payload["entry_points_ms"]),
        entry_points_found=int(payload["entry_points_found"]),
        validity_key_ms=float(payload["validity_key_ms"]),
        installed_distributions=int(payload["installed_distributions"]),
        catalog_home=payload["catalog_home"],
        catalog_build_ms=None if build_ms is None else float(build_ms),
        catalog_error=str(payload["catalog_error"]),
    )


def _probe_discovery() -> DiscoveryProbe:
    """Best-of-five over the discovery probe, a fresh interpreter per repetition."""
    for _ in range(WARMUP_RUNS):
        _probe_once()
    samples = [_probe_once() for _ in range(MEASURED_RUNS)]
    builds = [sample.catalog_build_ms for sample in samples if sample.catalog_build_ms is not None]
    return replace(
        samples[-1],
        entry_points_ms=min(sample.entry_points_ms for sample in samples),
        validity_key_ms=min(sample.validity_key_ms for sample in samples),
        catalog_build_ms=min(builds) if builds else None,
    )


def _importtime_of(module: str) -> tuple[float, int]:
    """`(cumulative ms attributed to `module`, module count)` from `-X importtime`.

    The count is **baseline-subtracted**: a virtualenv injects a `.pth` finder, `sitecustomize`
    and, on Windows, `pywin32_bootstrap` before any user code runs, and counting those as modules
    the import pulled in makes the hard assertion a property of the venv rather than of the change
    under review. 11-repo-layout.md section 6.4 names the raw command; both counts are available
    from the trace and the gate compares the attributed one. Departing here in the open rather
    than in silence, because a hard assertion that moves when nothing changed is a hard assertion
    nobody keeps.
    """
    _, stderr = _run_child(f"import {module}", flags=("-X", "importtime"))
    _, baseline_stderr = _run_child("pass", flags=("-X", "importtime"))
    baseline = {
        match.group("module")
        for line in baseline_stderr.splitlines()
        if (match := _IMPORTTIME_LINE.match(line)) is not None
    }
    cumulative_us = 0.0
    attributed: set[str] = set()
    for line in stderr.splitlines():
        match = _IMPORTTIME_LINE.match(line)
        if match is None:
            continue
        name = match.group("module")
        if name not in baseline:
            attributed.add(name)
        if name == module:
            cumulative_us = float(match.group("cumulative"))
    return cumulative_us / 1000.0, len(attributed)


def _measure_import(module: str) -> tuple[Measurement, Measurement]:
    """Best-of-five `-X importtime` cost of `import <module>`, and its attributed module count."""
    for _ in range(WARMUP_RUNS):
        _importtime_of(module)
    timings: list[float] = []
    counts: list[int] = []
    for _ in range(MEASURED_RUNS):
        milliseconds, count = _importtime_of(module)
        timings.append(milliseconds)
        counts.append(count)
    return (
        Measurement(
            name=f"import {module}",
            unit="ms",
            value=min(timings),
            samples=tuple(timings),
        ),
        Measurement(
            name=f"import {module} module count",
            unit="modules",
            value=float(min(counts)),
            samples=tuple(float(count) for count in counts),
        ),
    )


def _measure_spawn(argv: tuple[str, ...], name: str) -> Measurement:
    """Best-of-five `spawn_inclusive` wall time for a console command, or why it is absent."""
    executable = shutil.which(argv[0])
    if executable is None:
        return Measurement(
            name=name,
            unit="ms",
            value=None,
            absent_because=f"{argv[0]!r} is not on PATH; the CLI distribution is unbuilt",
        )
    command = [executable, *argv[1:]]
    timings: list[float] = []
    for index in range(WARMUP_RUNS + MEASURED_RUNS):
        start = time.perf_counter()
        completed = subprocess.run(  # noqa: S603 - argv resolved through shutil.which, no shell.
            command, capture_output=True, text=True, check=False, timeout=300.0
        )
        elapsed = (time.perf_counter() - start) * 1000.0
        if completed.returncode != 0:
            return Measurement(
                name=name,
                unit="ms",
                value=None,
                absent_because=f"{' '.join(argv)} exited {completed.returncode}",
            )
        if index >= WARMUP_RUNS:
            timings.append(elapsed)
    return Measurement(name=name, unit="ms", value=min(timings), samples=tuple(timings))


def observe_environment(probe: DiscoveryProbe) -> Environment:
    """The stamp for this machine, taking the distribution count from the probe that counted it."""
    return Environment(
        operating_system=platform.system(),
        operating_system_release=platform.release(),
        machine=platform.machine(),
        python=platform.python_version(),
        python_implementation=platform.python_implementation(),
        installed_distributions=probe.installed_distributions,
        runner=os.environ.get("OMNIWEAVE_RUNNER", "unpinned"),
    )


def measure_all() -> tuple[Environment, tuple[Measurement, ...], DiscoveryProbe]:
    """Every number this machine can produce, with a stated reason for every one it cannot."""
    probe = _probe_discovery()
    env = observe_environment(probe)
    import_ms, module_count = _measure_import("omniweave_core")
    measurements = (
        import_ms,
        module_count,
        _measure_spawn(("ow", "--version"), "ow --version"),
        _measure_spawn(("ow", "--help"), "ow --help"),
        Measurement(name=STEP_ONE_SUBJECT, unit="ms", value=probe.entry_points_ms),
        Measurement(name=STEP_TWO_SUBJECT, unit="ms", value=probe.validity_key_ms),
        Measurement(
            name=CATALOG_SUBJECT,
            unit="ms",
            value=probe.catalog_build_ms,
            absent_because="" if probe.catalog_build_ms is not None else probe.catalog_error,
        ),
    )
    return env, measurements, probe


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------

BUDGET_LOCUS = "04-driver-system.md section 4.4"
STEPS_LOCUS = "04-driver-system.md section 4.3"
CEILING_LOCUS = "02-architecture.md section 5.5 / 00-vision.md V01-3"
BASELINE_LOCUS = "11-repo-layout.md section 6.4"

ROW_ONE_INSTALLED = 20
"""The installed-distribution count row 1 of `DISCOVERY_BUDGET` describes.

A precondition, not a threshold: row 1's 20 ms budget is only a statement about an environment
holding 20 installed distributions, and applying it to a machine holding 328 would be comparing a
measurement to a budget set for a different environment.
"""


def check_plan_arithmetic() -> list[Finding]:
    """Re-derive every printed total and headroom in section 4.4 from the terms beside it.

    This runs on every invocation and needs no machine, because it is the half of "with the
    arithmetic shown so a reviewer can check the headroom rather than trust it" that a reviewer
    should not have to do by hand. A transcription error in `DISCOVERY_BUDGET` fails here rather
    than silently changing what the gate enforces.

    **One row does not close, and it is the plan's own arithmetic, not the transcription's.** Row
    5 - "per additional installed driver, warm" - derives `0.05 + 0.03` and budgets `0.06 ms`, so
    the budget sits 0.02 ms *below* the cost it budgets, where row 4 sets 0.4 ms against
    0.35 + 0.03 = 0.38. Both figures are transcribed exactly as printed; the mismatch is reported
    as a NOTE naming it, and not as a FAIL, because failing here would make G10 permanently red
    over a defect in a document this gate does not own.
    `tests/unit/test_gate_coldstart.py` pins it with a strict xfail, so amending
    04-driver-system.md section 4.4 forces this file to be amended with it.
    """
    findings: list[Finding] = []
    for row in DISCOVERY_BUDGET:
        computed_total = row.computed_total_ms
        if row.total_ms is not None and computed_total != row.total_ms:
            findings.append(
                Finding(
                    Severity.FAIL,
                    row.scenario,
                    f"printed total {row.total_ms:g} ms, terms give {computed_total}",
                    BUDGET_LOCUS,
                )
            )
        computed_headroom = row.computed_headroom
        if row.headroom is not None and computed_headroom != row.headroom:
            findings.append(
                Finding(
                    Severity.FAIL,
                    row.scenario,
                    f"printed headroom {row.headroom:g}x, terms give {computed_headroom}x",
                    BUDGET_LOCUS,
                )
            )
        marginal = row.marginal_headroom
        if marginal is not None and marginal < 1.0:
            findings.append(
                Finding(
                    Severity.NOTE,
                    row.scenario,
                    f"the plan budgets {row.budget_ms:g} ms for a cost its own terms put at "
                    f"{row.per_card_ms} ms ({marginal:g}x) - a defect in the source table, "
                    f"transcribed verbatim and not corrected here",
                    BUDGET_LOCUS,
                )
            )
    scenarios = [row for row in DISCOVERY_BUDGET if row.computed_headroom is not None]
    tightest = min(scenarios, key=lambda row: row.computed_headroom or 0.0)
    findings.append(
        Finding(
            Severity.NOTE,
            "tightest scenario",
            f"{tightest.scenario} at {tightest.computed_headroom}x - the row a regression shows "
            f"up in first, being dominated by one entry_points() call whose cost is a property "
            f"of the environment rather than of omniweave",
            BUDGET_LOCUS,
        )
    )
    return findings


def check_discovery_budget(
    env: Environment, measurements: tuple[Measurement, ...]
) -> tuple[list[Finding], HardCeilingCrossing | None]:
    """Compare what this machine measured against section 4.4, and never against a row it is not.

    Two rules, and the second is the one that keeps the report honest:

    1. **The hard ceiling applies everywhere**, so it is checked against whatever total this
       machine could produce - `Catalog.build()` when it exists, and otherwise the measured floor
       of steps 1 and 2, which bounds the total from below and is therefore still a sound witness
       for a crossing. Crossing it yields a `HardCeilingCrossing` and never a FAIL.
    2. **A scenario row is checked only in the environment it describes.** Row 1 is 20 installed
       distributions and rows 2-3 are 328; this machine has whatever it has. Dividing a figure
       measured at one count by a budget set at another is not a comparison, so a row whose
       precondition does not hold is reported ABSENT with both counts printed, and the baseline
       band is what covers regression here instead.
    """
    findings: list[Finding] = []
    step_one = measurement_named(measurements, STEP_ONE_SUBJECT)
    step_two = measurement_named(measurements, STEP_TWO_SUBJECT)
    build = measurement_named(measurements, CATALOG_SUBJECT)

    steps = [item for item in (step_one, step_two) if item is not None and item.value is not None]
    floor_ms = sum(item.value or 0.0 for item in steps)
    slowest = max(steps, key=lambda item: item.value or 0.0).name if steps else "unknown"

    complete = build is not None and build.value is not None
    total_ms = (build.value or 0.0) if (complete and build is not None) else floor_ms
    if not complete:
        reason = build.absent_because if build is not None else "no probe ran"
        findings.append(
            Finding(
                Severity.ABSENT,
                CATALOG_SUBJECT,
                f"{reason}; falling back to the measured floor of steps 1+2 ({floor_ms:.2f} ms), "
                f"which bounds the total from below",
                STEPS_LOCUS,
            )
        )

    crossing: HardCeilingCrossing | None = None
    if total_ms > HARD_CEILING_MS:
        crossing = HardCeilingCrossing(
            kind=HARD_CEILING_KIND,
            measured_ms=total_ms,
            slowest_step=slowest,
            installed_distributions=env.installed_distributions,
        )
        findings.append(Finding(Severity.DEGRADED, "hard ceiling", crossing.message, BUDGET_LOCUS))

    row = DISCOVERY_BUDGET[0]
    if env.installed_distributions <= ROW_ONE_INSTALLED and complete:
        over = total_ms > row.budget_ms
        findings.append(
            Finding(
                Severity.FAIL if over else Severity.NOTE,
                row.scenario,
                f"{total_ms:.2f} ms against a {row.budget_ms:g} ms budget"
                + ("" if over else f" ({row.budget_ms / max(total_ms, 1e-9):.1f}x headroom)"),
                BUDGET_LOCUS,
            )
        )
    else:
        findings.append(
            Finding(
                Severity.ABSENT,
                "scenario rows",
                f"this machine has {env.installed_distributions} installed distributions and "
                f"{'a' if complete else 'no'} Catalog.build() timing; section 4.4's rows describe "
                f"{ROW_ONE_INSTALLED} and {REFERENCE_MACHINE.installed_distributions} "
                f"distributions, so no row's precondition holds and none is asserted",
                BUDGET_LOCUS,
            )
        )

    if step_one is not None and step_one.value is not None:
        findings.append(
            Finding(
                Severity.NOTE,
                "step 1 vs the reference machine",
                f"{step_one.value:.2f} ms at {env.installed_distributions} distributions here, "
                f"against {DISCOVERY_STEPS[0].cost} at "
                f"{REFERENCE_MACHINE.installed_distributions} on "
                f"{REFERENCE_MACHINE.operating_system} / {REFERENCE_MACHINE.python} "
                f"({REFERENCE_MACHINE.thermal_state}) - an observation, not an assertion",
                STEPS_LOCUS,
            )
        )
    return findings, crossing


def check_cold_start_ceilings(measurements: tuple[Measurement, ...]) -> list[Finding]:
    """Every D1 ceiling this gate has an instrument for, plus a stated absence for the rest."""
    findings: list[Finding] = []
    for ceiling in COLD_START_CEILINGS:
        if ceiling.subject not in MEASURABLE_CEILINGS:
            findings.append(
                Finding(
                    Severity.ABSENT,
                    ceiling.subject,
                    f"not measured by {GATE} at P1: {ceiling.note or 'no instrument'}",
                    CEILING_LOCUS,
                )
            )
            continue
        measurement = measurement_named(measurements, ceiling.subject)
        if measurement is None or measurement.value is None:
            reason = measurement.absent_because if measurement is not None else "not measured"
            findings.append(Finding(Severity.ABSENT, ceiling.subject, reason, CEILING_LOCUS))
            continue
        over = measurement.value > ceiling.ceiling_ms
        findings.append(
            Finding(
                Severity.FAIL if over else Severity.NOTE,
                ceiling.subject,
                f"{measurement.value:.1f} ms {'over' if over else 'under'} a "
                f"{ceiling.ceiling_ms:g} ms ceiling ({ceiling.basis})",
                CEILING_LOCUS,
            )
        )
    return findings


def _recorded_value(baseline: dict[str, object], name: str) -> float | None:
    """The baselined value for `name`, or `None` when the file does not carry one."""
    measurements = baseline.get("measurements")
    if not isinstance(measurements, dict):
        return None
    row = measurements.get(name)
    if not isinstance(row, dict):
        return None
    value = row.get("value")
    return float(value) if isinstance(value, (int, float)) else None


MINIMUM_SAMPLES_FOR_A_SPREAD = 2
"""Below two runs there is no spread to report, only a single number.

A separate constant from `MEASURED_RUNS` because it bounds what a *read* baseline must carry, not
what a new measurement takes: an older file, or one recorded under a different `MEASURED_RUNS`,
still has a readable spread and should still get the note.
"""


def _recorded_samples(baseline: dict[str, object], name: str) -> tuple[float, ...]:
    """The individual runs behind a baselined value, for `_noise_finding`."""
    measurements = baseline.get("measurements")
    if not isinstance(measurements, dict):
        return ()
    row = measurements.get(name)
    if not isinstance(row, dict):
        return ()
    samples = row.get("samples")
    if not isinstance(samples, list):
        return ()
    return tuple(float(value) for value in samples if isinstance(value, (int, float)))


def _noise_finding(measurement: Measurement, samples: tuple[float, ...]) -> Finding | None:
    """A NOTE when the baseline's own five runs already spread wider than the band.

    Derived entirely from recorded measurements - it introduces no threshold of its own and it
    changes no verdict. It exists because a percentage band is only a statement about drift when
    the quantity is large relative to the runner's jitter, and at P1 `import omniweave_core` is
    around 1.3 ms on this machine, where five consecutive best-of-five runs move by more than 25%
    for reasons no commit caused. 12-performance.md section 2.4 already treats the mirror case as
    a real failure mode - `wal.bulk_index_peak_bytes` takes `tol_abs` "because a percentage of a
    growing number is not a bound" - and this note is the evidence a reviewer needs to decide
    whether the same argument runs the other way for a very small one. The band itself stays at
    11-repo-layout.md section 6.4's 25%: this gate reports, it does not retune.
    """
    if len(samples) < MINIMUM_SAMPLES_FOR_A_SPREAD:
        return None
    low, high = min(samples), max(samples)
    if low <= 0:
        return None
    spread_pct = (high - low) / low * 100.0
    if spread_pct <= BASELINE_TOLERANCE_PCT:
        return None
    return Finding(
        Severity.NOTE,
        measurement.name,
        f"the baseline's own {len(samples)} runs span {low:.2f}..{high:.2f} "
        f"{measurement.unit} ({spread_pct:.0f}% spread), wider than the "
        f"+/-{BASELINE_TOLERANCE_PCT}% band, so a verdict on this subject reports runner jitter "
        f"as well as drift",
        BASELINE_LOCUS,
    )


def _band_finding(measurement: Measurement, before: float) -> Finding:
    """The 25% wall-clock band for one measurement against its baselined value."""
    now = measurement.value or 0.0
    band = abs(before) * BASELINE_TOLERANCE_PCT / 100.0
    if now > before + band:
        verdict, severity = BaselineVerdict.REGRESSED, Severity.FAIL
    elif now < before - band:
        verdict, severity = BaselineVerdict.IMPROVED, Severity.NOTE
    else:
        verdict, severity = BaselineVerdict.WITHIN_BAND, Severity.NOTE
    return Finding(
        severity,
        measurement.name,
        f"{verdict}: {now:.2f} {measurement.unit} against {before:.2f} "
        f"+/-{BASELINE_TOLERANCE_PCT}% ({before - band:.2f}..{before + band:.2f})",
        BASELINE_LOCUS,
    )


def _count_finding(measurement: Measurement, before: float) -> Finding:
    """The hard module-count assertion: a count may fall and be re-blessed, never grow."""
    now = measurement.value or 0.0
    if now > before:
        verdict, severity = BaselineVerdict.REGRESSED, Severity.FAIL
    elif now < before:
        verdict, severity = BaselineVerdict.IMPROVED, Severity.NOTE
    else:
        verdict, severity = BaselineVerdict.WITHIN_BAND, Severity.NOTE
    return Finding(
        severity,
        measurement.name,
        f"{verdict}: {now:g} modules against a baseline of {before:g} (hard assertion: a count "
        f"may fall and be re-blessed, never grow)",
        BASELINE_LOCUS,
    )


def compare_to_baseline(
    baseline: dict[str, object] | None, measurements: tuple[Measurement, ...]
) -> list[Finding]:
    """The 25% band and the hard module count, against the baseline recorded for **this** OS.

    `NO_BASELINE` is a first-class outcome, reported once with the command that fixes it. It is
    not a pass dressed as one and it is not a failure: 11-repo-layout.md section 6.4's band is a
    statement about drift on one machine, and there is no drift to measure against a machine
    nobody has measured.

    The module count is the **hard** half of the split gate, and it is asserted as `<=` rather
    than `==`. Growth is what regresses - a new eager import in core is the failure mode G10 and
    G17 both exist for - while a shrink is an improvement that should be re-blessed rather than
    refused, and refusing it would make removing an import require a baseline edit first.
    """
    if baseline is None:
        return [
            Finding(
                Severity.ABSENT,
                "baseline",
                f"{BaselineVerdict.NO_BASELINE}: nothing recorded for this OS and Python. Run "
                f"`uv run tools/gate_coldstart.py --record-baseline`. Unmeasured is neither a "
                f"pass nor a regression",
                BASELINE_LOCUS,
            )
        ]
    if baseline.get("baseline_schema") != BASELINE_SCHEMA:
        return [
            Finding(
                Severity.ABSENT,
                "baseline",
                f"{BaselineVerdict.NO_BASELINE}: baseline_schema "
                f"{baseline.get('baseline_schema')!r} is not {BASELINE_SCHEMA}; re-record rather "
                f"than compare against a field that changed meaning",
                BASELINE_LOCUS,
            )
        ]
    findings: list[Finding] = []
    for measurement in measurements:
        before = _recorded_value(baseline, measurement.name)
        if before is None:
            continue
        if measurement.value is None:
            findings.append(
                Finding(
                    Severity.ABSENT,
                    measurement.name,
                    f"baselined at {before:g} but not measurable now: "
                    f"{measurement.absent_because or 'no reason recorded'}",
                    BASELINE_LOCUS,
                )
            )
        elif measurement.unit == "modules":
            findings.append(_count_finding(measurement, before))
        else:
            findings.append(_band_finding(measurement, before))
            noise = _noise_finding(measurement, _recorded_samples(baseline, measurement.name))
            if noise is not None:
                findings.append(noise)
    return findings


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Report:
    """Everything one run produced: the stamp, the numbers, the coverage and the verdict."""

    recorded_at: str
    environment: Environment
    measurements: tuple[Measurement, ...]
    probe: DiscoveryProbe
    coverage: dict[str, tuple[str, ...]]
    baseline_file: Path
    baseline_present: bool
    hard_ceiling_crossing: HardCeilingCrossing | None
    findings: tuple[Finding, ...]

    def to_json(self) -> dict[str, object]:
        """The report as plain JSON - the `--json` output and the baseline file's contents."""
        crossing = self.hard_ceiling_crossing
        return {
            "gate": GATE,
            "baseline_schema": BASELINE_SCHEMA,
            "recorded_at": self.recorded_at,
            "environment": self.environment.to_json(),
            "reference_machine": REFERENCE_MACHINE.to_json(),
            "tolerance_pct": BASELINE_TOLERANCE_PCT,
            "warmup_runs": WARMUP_RUNS,
            "measured_runs": MEASURED_RUNS,
            "statistic": "min",
            "measurements": {item.name: item.to_json() for item in self.measurements},
            "budget": [row.to_json() for row in DISCOVERY_BUDGET],
            "cold_start_ceilings": [row.to_json() for row in COLD_START_CEILINGS],
            "coverage": {name: list(pythons) for name, pythons in self.coverage.items()},
            "hard_ceiling_crossing": crossing.to_json() if crossing is not None else None,
            "findings": [finding.to_json() for finding in self.findings],
        }


def build_report(baselines_dir: Path) -> Report:
    """Measure, check, and assemble everything a reader or a JSON consumer needs."""
    env, measurements, probe = measure_all()
    path = baseline_path(baselines_dir, env)
    baseline: dict[str, object] | None = None
    if path.is_file():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        baseline = loaded if isinstance(loaded, dict) else None
    budget_findings, crossing = check_discovery_budget(env, measurements)
    findings = (
        *check_plan_arithmetic(),
        *check_cold_start_ceilings(measurements),
        *budget_findings,
        *compare_to_baseline(baseline, measurements),
    )
    return Report(
        recorded_at=datetime.now(tz=UTC).isoformat(timespec="seconds"),
        environment=env,
        measurements=measurements,
        probe=probe,
        coverage=baseline_coverage(baselines_dir),
        baseline_file=path,
        baseline_present=baseline is not None,
        hard_ceiling_crossing=crossing,
        findings=findings,
    )


def exit_code(findings: tuple[Finding, ...]) -> int:
    """`1` iff some finding is a FAIL. A degradation, an absence and a note are all `0`."""
    return 1 if any(finding.severity == Severity.FAIL for finding in findings) else 0


def _emit(line: str = "") -> None:
    """Write one report line.

    `sys.stdout.write` rather than `print`: the repository lints with ruff's `T20`, which bans
    `print` repo-wide, and a gate that has to be exempted from a lint rule to report its own
    result is a gate whose exemption outlives the reason for it.
    """
    sys.stdout.write(f"{line}\n")


def render(report: Report) -> None:
    """Print the whole report, arithmetic first, as 04-driver-system.md section 4.4 requires."""
    env = report.environment
    _emit(f"{GATE} - cold start and the driver discovery cost budget")
    _emit("=" * 98)
    _emit()
    _emit("MEASURED ON (this machine, this run)")
    _emit(
        f"  {env.operating_system} {env.operating_system_release} / {env.machine} / "
        f"{env.python_implementation} {env.python} / "
        f"{env.installed_distributions} installed distributions / runner {env.runner}"
    )
    _emit(
        f"  every budget below was measured on {REFERENCE_MACHINE.operating_system} / "
        f"{REFERENCE_MACHINE.python} / {REFERENCE_MACHINE.installed_distributions} distributions "
        f"({REFERENCE_MACHINE.thermal_state}) and is TRANSCRIBED here, not re-measured"
    )
    _emit()
    _emit("Catalog.build() STEP COSTS - 04-driver-system.md section 4.3, transcribed")
    for step in DISCOVERY_STEPS:
        _emit(f"  {step.number}. {step.step:<34} {step.cost:<26} {step.mechanism}")
    _emit()
    _emit("THE DISCOVERY COST BUDGET - 04-driver-system.md section 4.4, with the arithmetic")
    for row in DISCOVERY_BUDGET:
        note = f"   ({row.note})" if row.note else ""
        _emit(f"  {row.scenario}{note}")
        _emit(f"      {row.arithmetic()}")
    _emit()
    _emit("D1 COLD-START CEILINGS - absolute, and checked on every machine")
    for ceiling in COLD_START_CEILINGS:
        instrument = "measured here" if ceiling.subject in MEASURABLE_CEILINGS else "not measured"
        _emit(
            f"  {ceiling.subject:<34} <= {ceiling.ceiling_ms:>6.0f} ms  "
            f"{ceiling.basis:<16} {ceiling.gate:<5} {instrument}"
        )
    _emit()
    _emit("MEASURED")
    for measurement in report.measurements:
        if measurement.value is None:
            _emit(f"  {measurement.name:<44} {'ABSENT':>10}  {measurement.absent_because}")
        else:
            _emit(f"  {measurement.name:<44} {measurement.value:>10.2f} {measurement.unit}")
    _emit(
        f"  {'omniweave.drivers entry points found':<44} "
        f"{report.probe.entry_points_found:>10} entries"
    )
    _emit()
    _emit(
        f"BASELINE COVERAGE - the P1 exit criterion asks for "
        f"{len(TARGET_OPERATING_SYSTEMS)} OSes; one machine records one"
    )
    for name in TARGET_OPERATING_SYSTEMS:
        pythons = report.coverage.get(name, ())
        marker = "recorded" if pythons else "NOT RECORDED"
        detail = f" (python {', '.join(pythons)})" if pythons else ""
        here = "  <- this machine" if name == env.operating_system else ""
        _emit(f"  {name:<10} {marker}{detail}{here}")
    _emit(f"  file for this machine: {report.baseline_file}")
    _emit()
    _emit("FINDINGS")
    for finding in report.findings:
        _emit(f"  {finding}")
    _emit()
    failures = [finding for finding in report.findings if finding.severity == Severity.FAIL]
    _emit(f"{GATE}: {'FAIL' if failures else 'PASS'} ({len(failures)} failing findings)")


def write_baseline(path: Path, report: Report) -> None:
    """Write this OS's baseline row: LF-terminated, sorted, with a trailing newline.

    `newline="\\n"` is 11-repo-layout.md section 1.9 rule 2: a generator taking the platform
    default emits CRLF on Windows, and every `--check` gate in the repository then disagrees
    byte-for-byte with the same file written on Linux, for reasons no change caused.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(report.to_json(), handle, indent=2, sort_keys=True)
        handle.write("\n")


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, run the gate, print the report, and return the exit code."""
    parser = argparse.ArgumentParser(
        prog="gate_coldstart.py",
        description=(
            f"{GATE}: assert the D1 cold-start ceilings and 04-driver-system.md section 4.4's "
            f"discovery cost budget, then compare against this OS's recorded baseline."
        ),
    )
    parser.add_argument(
        "--record-baseline",
        action="store_true",
        help=(
            "measure and write eval/baselines/coldstart-<os>-<py>.json for THIS OS. One machine "
            "records one of the three rows the P1 exit criterion names; the coverage table says "
            "which."
        ),
    )
    parser.add_argument(
        "--baselines-dir",
        type=Path,
        default=None,
        help="where baselines live (default: <repo root>/eval/baselines)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="print the whole report as JSON instead of as text",
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent
    baselines_dir: Path = args.baselines_dir or repo_root / "eval" / "baselines"
    report = build_report(baselines_dir)

    if args.record_baseline:
        path = report.baseline_file
        write_baseline(path, report)
        kept = tuple(
            finding
            for finding in report.findings
            if not (finding.subject == "baseline" and finding.severity == Severity.ABSENT)
        )
        recorded = Finding(
            Severity.NOTE,
            "baseline",
            f"recorded for {report.environment.operating_system} / python "
            f"{report.environment.python_tag} at {path}",
            BASELINE_LOCUS,
        )
        report = replace(
            report,
            findings=(*kept, recorded),
            coverage=baseline_coverage(baselines_dir),
            baseline_present=True,
        )

    if args.as_json:
        _emit(json.dumps(report.to_json(), indent=2, sort_keys=True))
    else:
        render(report)
    return exit_code(report.findings)


if __name__ == "__main__":
    raise SystemExit(main())
