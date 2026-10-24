"""V10-1 .. V10-17: v1.0's acceptance set, rolled up from the instruments that measure it. **D835.**

16-roadmap.md:985 runs this as P10's last exit criterion: `uv run tools/acceptance_v10.py  # V10-1
.. V10-17 from 00-vision.md 9.2`. 00-vision.md section 9.2 (:720-740) is its content: this script
adds no criterion and drops none. Like `tools/acceptance_v01.py` it measures nothing itself. Every
row names the gates and tests that already measure it, runs them, and reports what they could and
could not say.

**One machinery, two tables.** The verdicts, the table types, the runner and `judge()` are
`tools/acceptance_v01.py`'s, loaded from beside this file. A second copy would be a second
definition of what PASS means. The four verdicts are that file's: PASS, PARTIAL (green, but a
clause nothing asserts, named), FAIL (an instrument exited non-zero) and UNMEASURED.

**Exit 0 only when all seventeen are PASS.** When D835 wrote this none was; V10-9 is the first
(D911). The rest are PARTIAL at best or have no instrument, because what v1.0 is measured by did
not exist:
- a release tag;
- the 14-wheel build;
- the Tier A and golden corpora;
- the nine-cell matrix and the pinned runner;
- a `--strict` pass of `ow eval release-check`, which needs the three suites no harness measures.

The P10 exit command is meant to fail until v1.0 is actually accepted, and the report says which
clause each row is missing.

## Where the coverage judgments come from

Each row's coverage and gap were read off the instruments' bodies in D835, not off their names,
and every file a row names is asserted to exist (`test_acceptance_v10.py`). They are declarations,
and a reviewer checks them the way a register row is checked. A row moves up a coverage level in
the commit that lands its instrument.

    uv run tools/acceptance_v10.py              # every row but the slow ones
    uv run tools/acceptance_v10.py --slow       # also G19, G22, GR8, damage, an ingest (minutes)
    uv run tools/acceptance_v10.py --only V10-5,V10-16
    uv run tools/acceptance_v10.py --json

Exit codes: `0` all seventeen PASS, `1` any row is not PASS, `2` a usage error from argparse.

Specified in 00-vision.md section 9.2 (:720-740) and 16-roadmap.md section 13 (:976-985).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import asdict
from pathlib import Path
from types import ModuleType

__all__ = [
    "CRITERIA",
    "V01",
    "Coverage",
    "Criterion",
    "Instrument",
    "Verdict",
    "evaluate",
    "judge",
    "main",
]


def _v01() -> ModuleType:
    """`tools/acceptance_v01.py`, by path, under the name it runs by."""
    path = Path(__file__).with_name("acceptance_v01.py")
    spec = importlib.util.spec_from_file_location("acceptance_v01", path)
    if spec is None or spec.loader is None:  # pragma: no cover -- the file is beside this one
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V01 = _v01()
Coverage = V01.Coverage
Criterion = V01.Criterion
Instrument = V01.Instrument
Verdict = V01.Verdict
judge = V01.judge
evaluate = V01.evaluate
tool = V01.tool
pytest = V01.pytest
module = V01.module

CORE = "packages/omniweave-core/tests/unit"
CLI = "packages/omniweave/tests/unit"
CONF = "packages/omniweave-conform/tests/unit"
T3 = "packages/omniweave/tests/conform"
CORE_T3 = "packages/omniweave-core/tests/conform"


# ---------------------------------------------------------------------------
# The seventeen, in 00-vision.md:724-740's order. Criterion text is abridged, never restated.
# ---------------------------------------------------------------------------

CRITERIA: tuple[Criterion, ...] = (
    Criterion(
        "V10-1",
        "every G row and all 27 Q-G gates green on the tag; ow eval release-check: zero unknown",
        (
            pytest(f"{CORE}/test_gates_register.py", label="the G register: dense, runners exist"),
            tool("ow_eval.py", "golden", "--check", "span_exact_rate"),
            tool("gate_budgets.py"),
            tool("gate_gate_rot.py"),
            tool("gate_measured_on.py"),
            tool("gate_results.py"),
            tool("gate_placement.py"),
            tool("gate_metric_rot.py"),
            tool("gate_flake.py", "--window", "30d"),
            tool("gate_bless.py"),
            tool("gate_fixtures.py"),
            tool("gate_inventory.py"),
            tool("gate_leakage.py"),
            module("omniweave", "surface", "emit", "--check"),
            pytest(
                f"{CONF}/test_conform_release.py",
                f"{CLI}/test_eval_release_check_verb.py",
                label="ow eval release-check refuses on unknown and on hard gates (D840)",
            ),
            pytest(f"{CORE}/test_gate_parity.py", label="Q-G22's gate and its blocker (D842)"),
            pytest(f"{CORE}/test_gate_frozen_stability.py", label="Q-G4's gate, on cells (D849)"),
            Instrument(
                "pytest ow eval run, then ow eval release-check exits 0 (D868-D872)",
                (
                    "-m",
                    "pytest",
                    "-q",
                    "-p",
                    "no:cacheprovider",
                    f"{T3}/test_eval_run_process.py",
                ),
                slow=True,
            ),
        ),
        Coverage.PARTIAL,
        "no `v*` tag to be green on; `ow eval run` measures parse, absence, retrieve, "
        "roundtrip and portability, every hard gate holds over them, and `ow eval release-check` "
        "refuses only the drafted labels' unverified rates (D868-D871, D903, D913); `--strict` "
        "also refuses extract and perf, which no harness measures (D872), "
        "and no "
        "`.oweval` is committed for a tag; G13 has no runner, and G25, a CI step and not a "
        "`tools/` script, is `ow surface emit --check`, run here (D960). "
        "G29 forces two of its four faults, a driver bug and a crash, with no budget denial "
        "or quarantine to force (D936); Q-G16 has no instrument and Q-G20, which needs 100 "
        "double-labelled items, is deferred past v1.0 (D971, a user ruling of 2026-10-23); "
        "Q-G26 runs its assertion "
        "clause only (D875), Q-G2 runs without "
        "its orphan-cassette sweep, and "
        "Q-G8, 19 and 25 run their static halves only; Q-G22's gate runs the T1/T2 suite and "
        "Q-G4's reads the CI cells, so this row runs their tests and not them. The `gates` CI "
        "job runs on every push and nightly (D886, D908). This row runs the Q-G "
        "scripts that exist, and the register test, not every G runner",
    ),
    Criterion(
        "V10-2",
        "14 sdists and 14 wheels, py3-none-any; weight ceilings; [recommended] <= 250 MB",
        (
            tool("gate_weights.py"),
            pytest(f"{CORE}/test_gates_packaging.py", f"{CORE}/test_sdist_shape.py"),
            tool("check_build.py", slow=True),
        ),
        Coverage.PARTIAL,
        "tools/check_build.py builds the 28 artefacts twice and checks every wheel `py3-none-any` "
        "and the two passes byte-identical (D874). CI's `build` job measures the rest: "
        "tools/check_wheelhouse.py installs the three offline profiles from the built wheels and "
        "runs G2's measured half and the 250 MB `[recommended]` union over them (D897-D899); "
        "this row runs the declared half and the build here. `ow doctor --runtime`'s vision size "
        "(D-19) is unbuilt",
    ),
    Criterion(
        "V10-3",
        "accuracy floors from eval/gates.toml: structure_f1, order_acc, table_rel_acc, ...",
        (),
        Coverage.NONE,
        "eval/gates.toml carries no accuracy floor. `ow eval run --suite parse` now scores "
        "`order_acc`, `table_rel_acc` and `field_acc` from a fixture's `.assertions.toml` over "
        "the Markdown `ow` serves (D912). D913 drafted 110 labels over 14 fixtures, every one "
        "passing and none verified, so every rate is unknown until a reviewer signs them; "
        "`structure_f1` and `doc_acc` have no harness",
    ),
    Criterion(
        "V10-4",
        "honesty ceilings: hallucination_rate, false_confident_zero, degradation_detection == 1",
        (
            tool("ow_damage.py", "--deterministic-half", slow=True),
            pytest(
                f"{CONF}/test_conform_removal.py",
                label="the removal half's populations and removed corpora (D933)",
            ),
            Instrument(
                "pytest no answerable question answered absent, over real stores (D933)",
                (
                    "-m",
                    "pytest",
                    "-q",
                    "-p",
                    "no:cacheprovider",
                    f"{T3}/test_absence_removal.py",
                ),
                slow=True,
            ),
        ),
        Coverage.PARTIAL,
        "degradation_detection is measured over the 4 built Injectors of 13, in the paired-damage "
        "half and as `ow eval run --suite absence` (D869); the other nine damage features this "
        "build does not have, and are disclosed as such (D964, a user ruling of 2026-10-23). "
        "citability_violations is a hard row "
        "measured over the adoption catalogue (D870), which V10-1's instrument runs. "
        "false_confident_zero is a ceiling row computed by the removal half (D933): the "
        "catalogue's 13 answerable questions asked of their corpora, and again with each "
        "planted answer deleted. None is answered absent, but 13 is under min_slice_n, so the "
        "rate is unknown and release-check refuses it; no question at all reads absent, so "
        "absent_recall is 0 of 17. hallucination_rate is not applicable at v1.0: it is defined "
        "over field extraction and no field-extraction driver ships (`parse.fields.lift` is a "
        "tombstone with no successor), D971, a user ruling of 2026-10-23",
    ),
    Criterion(
        "V10-5",
        "every published number carries its provenance tuple; a short MeasuredOn is a TypeError",
        (
            tool("gate_measured_on.py"),
            tool("gate_results.py"),
            pytest(f"{CORE}/test_card.py", "-k", "measured_on", label="MeasuredOn's construction"),
            pytest(f"{CORE}/test_calibration.py", label="Q-G14's shape over CalStatus"),
        ),
        Coverage.PARTIAL,
        "`eval/results/` holds 12 rows from 9 runs of `ow eval run` on a developer machine "
        "(D922), each with its ten-field MeasuredOn, and both static gates hold over them; a "
        "card's [[quality.benchmark]] row cannot load without a complete MeasuredOn, and no "
        "shipped card carries one. A number in docs or release notes is scanned by nothing, "
        "and the tree is to be republished from the release commit",
    ),
    Criterion(
        "V10-6",
        "ow query warm p50 <= 180 ms under G10's 250; parse and WAL and RSS budgets",
        (
            tool("gate_budgets.py"),
            pytest(
                f"{CORE}/test_retrieve_plan.py::"
                "test_the_shipped_budgets_fit_under_query_ms_with_the_hydration_reserve",
                f"{CORE}/test_retrieve_plan.py::"
                "test_a_budget_whose_channels_outspend_the_query_deadline_is_refused",
                f"{CLI}/test_route_checks.py::"
                "test_the_shipped_retrieval_budget_sits_exactly_on_the_boundary",
                f"{CLI}/test_route_checks.py::test_one_millisecond_over_is_a_finding",
                label="the budgets fit the deadline, statically",
            ),
            pytest(
                f"{CLI}/test_bench_query.py",
                label="`ow bench query`'s set, harness and report (D915)",
            ),
        ),
        Coverage.PARTIAL,
        "`ow bench query` runs (D915): over `ow add`'s store of gen_5000p_pdf, 210,001 blocks, "
        "warm p50 measured 95 ms on a developer machine, inside 180, end-to-end only. It runs "
        "nightly on a GitHub-hosted runner and is kept as an eval_perf row (D916, a user ruling "
        "of 2026-10-21), whose status stays unknown: `ow-bench-1` and the Pacer's seven-run "
        "median do not exist. The `parse` subject is blocked, and the 4M-cell sheet's fixture "
        "exists (D929) but no shipped reader admits it: anydoc refuses it on max_xml_nodes, and "
        "the office worker's RSS (~3.7 KB a cell) passes its 1 GiB from ~280k cells. That sheet is "
        "a declared v1.0 limitation (F2), with the shipped limits kept (D964, a user ruling of "
        "2026-10-23)",
    ),
    Criterion(
        "V10-7",
        "a nightly 100k-roster run within queue_high_water and 600 MB supervisor RSS",
        (
            # G22's whole run was about 21 minutes here (the ledger's measurement) and is about
            # two since D917, inside a 90-minute nightly cell; the hour is the older margin.
            Instrument("tools/gate_scale.py", ("tools/gate_scale.py",), slow=True, timeout_s=3600),
            pytest(f"{CLI}/test_gate_scale.py", label="G22's mechanism, 40-300 units"),
        ),
        Coverage.PARTIAL,
        "G22 runs nightly on a GitHub-hosted runner as a labelled indication (D924, a user "
        "ruling of 2026-10-21), whose breach is reported and not a verdict; no ow-bench-1 runs "
        "it. The run is op.identify only, and the default asserts high_water "
        "plus one plan batch rather than the literal bound (`--strict` overshoots "
        "structurally). Throughput passes 2,000 on the median since D919's group commit, "
        "2,651 transitions/s over seven local runs (870 after D917's claim rulings, 504 "
        "before), but two of the seven fell under it, on a workstation and not the nightly",
    ),
    Criterion(
        "V10-8",
        "incremental == full: 300 documents, 40 mutations; the graph at 60 and 20 steps",
        (
            tool("gate_incremental.py", slow=True),
            tool("gate_incremental.py", "--through-add", "--subset", "v10-acceptance", slow=True),
            tool("gate_incremental_graph.py", slow=True),
            pytest(
                f"{CORE}/test_gate_incremental.py",
                f"{CORE}/test_fixture_incremental.py",
                f"{CLI}/test_gate_incremental_graph.py",
            ),
            pytest(
                "packages/omniweave/tests/conform/test_add_edit_identity.py",
                label="what a real `ow add` does with an edited file (D880, D882, D905)",
            ),
        ),
        # D964, a user ruling of 2026-10-23: 'identical' is content identity, the same blocks with
        # every cite resolving, which G19 fails on over the full 300/40 (the first instrument).
        # Generation and revision counters are parse history and excluded; --strict, which folds
        # them back in (D187), stays a report.
        Coverage.FULL,
        "",
    ),
    Criterion(
        "V10-9",
        "pptx, deck and docx reach GateStatus passed; video unimplemented with its reason",
        (
            pytest(
                "packages/omniweave-target-pptx/tests/unit/test_pptx_golden.py",
                "packages/omniweave-target-docx/tests/unit/test_docx_golden.py",
                "packages/omniweave-target-video/tests/unit/test_video_driver.py",
                "packages/omniweave-target-deck/tests/unit/test_deck_driver.py",
                label="the target goldens, and video's and deck's cards",
            ),
            pytest(
                "packages/omniweave-target-pptx/tests/unit/test_golden40.py::"
                "test_the_conformance_suite_releases_the_deck_its_gate_passed",
                f"{CONF}/test_target_suite.py",
                label="the suite's release gate: pptx's 40-unit golden, docx's less its manual "
                "unit (D911)",
            ),
            pytest(
                f"{CLI}/test_out_targets_verb.py::test_the_text_form_says_which_of_the_two_stops_a_kind",
                f"{CORE}/test_out_conformance.py::"
                "test_a_bake_row_is_an_error_while_the_cards_bake_is_unavailable",
                f"{CONF}/test_target_owtext.py::test_an_unreachable_bake_is_refused_before_a_byte",
                label="video's reason and the unavailable bake",
            ),
            pytest(
                "packages/omniweave-target-pptx/tests/unit/test_pptx_target.py::"
                "test_an_unavailable_bake_names_both_exits_and_each_one_clears_it",
                f"{CORE}/test_out_manual.py::"
                "test_the_bake_exits_name_the_reason_and_the_flag_the_gate_clears_with",
                label="the bake error's two exits, each clearing it (D876)",
            ),
        ),
        # FULL by two rulings, each in the plan's notes. Deck ships at `implemented = false` with
        # its reason, like video: a user ruling of 2026-10-21 took 16-roadmap.md R-Q8's fallback
        # (D910), so pptx and docx are the targets that must pass. And `passed` is the suite's
        # release gate (D911): a golden carries an `ow:manual` region by design, since R5 needs
        # every exact row exercised, so its own gate is manual-required; set aside, docx's
        # remainder passes and compiles as a release, and pptx's 40-unit golden passes outright.
        # The bake exits are asserted on pptx and owtext, the targets with a bake row (D876).
        Coverage.FULL,
        "",
    ),
    Criterion(
        "V10-10",
        "round-trip: two compiles of the 40-unit golden equal at part on all 9 cells",
        (
            pytest(
                f"{CLI}/test_run_out_back.py::"
                "test_the_document_is_an_ordinary_parse_carrying_the_artefacts_bits",
                f"{CLI}/test_run_out_compile.py::test_an_unresolved_cite_is_refused_before_lower",
                f"{CLI}/test_run_out_compile.py::"
                "test_the_plan_lowered_carries_each_cite_pinned_at_its_generation",
                label="the read-back and the pinned cites, one cell",
            ),
            tool("check_out_determinism.py"),
            tool("ow_portability.py"),
            pytest(
                "packages/omniweave-conform/tests/conform/test_out_determinism_process.py::"
                "test_the_forty_unit_golden_compiles_to_one_part_digest_five_ways",
                "packages/omniweave-target-pptx/tests/unit/test_golden40.py",
                label="the 40-unit golden: generated, pinned, gated, compiled five ways (D881)",
            ),
            pytest(
                f"{CORE}/test_ow_conform.py",
                "-k",
                "reader_passes",
                label="each target's reader card through the kit, over its compiled golden (D968)",
            ),
        ),
        # D968: every clause is measured. OUT13's in-cell half compiles the register's goldens
        # and the 40-unit deck twice and under three PYTHONHASHSEEDs to one part_digest (D878,
        # D881); every CI test cell, three OSes by three Pythons, holds them to
        # eval/portability.toml (D903, D914); and both reader cards pass the kit's mandatory
        # tier over their own compiled goldens, pptx's licence clear since D884 admitted
        # Pillow's MIT-CMU (D879 had found it failing).
        Coverage.FULL,
        "",
    ),
    Criterion(
        "V10-11",
        "the previous two releases' template Drivers load against HEAD (G16)",
        (
            tool("gate_contract.py", "--releases", "2", "--offline"),
            pytest(f"{CORE}/test_gate_contract.py", label="G16 over two locally tagged commits"),
        ),
        Coverage.PARTIAL,
        "there is no `v*` tag, so the gate loads no previous release and passes vacuously",
    ),
    Criterion(
        "V10-12",
        "a Driver authored outside this repository passes the eleven mandatory suites",
        (
            tool("ow_conform.py", "--template"),
            pytest(f"{CORE}/test_ow_conform.py", "-k", "mandatory_tier or bench_refuses"),
        ),
        # D967, a user ruling of 2026-10-23: an independent driver is v1.0's evidence and a third
        # party's run comes after release. `external_driver_subrip/` is a SubRip parser that
        # shares no code with the template, and it passes 11/11 from a copy outside the checkout,
        # run from its own directory with `PYTHONPATH=src` (D923 ran the template under new
        # names). `quality` is not mandatory: `--bench` refuses until `ow eval fetch`. Ingesting
        # a new format through `ow add` needs two things beyond the kit, recorded in D967: the
        # driver installed in the environment (a worker inherits no PYTHONPATH, by design), and
        # drivers' `sniff()` in detection (05:567 step 4, deferred by D568).
        Coverage.FULL,
        "",
    ),
    Criterion(
        "V10-13",
        "money reconciles: ow cost --by driver equals the manifest's spend rows to 0 micros",
        (
            pytest(
                f"{CLI}/test_run_manifest.py",
                "-k",
                "reconcile or counterfactual or op_spend or total_micros",
                label="the manifest's spend arithmetic",
            ),
            pytest(
                f"{CLI}/test_billed_run.py::"
                "test_a_priced_run_bills_each_call_and_records_what_the_cache_saved",
                f"{CLI}/test_spend_rows.py",
                label="billed calls priced and their cache savings recorded",
            ),
            pytest(
                f"{CLI}/test_cost_verb.py",
                label="ow cost --by driver, its reconcile and --verify (D838, D853)",
            ),
            pytest(
                f"{T3}/test_spend_reconciles_process.py",
                label="a real ow add verifies under ow cost --verify, unpriced and priced (D854, "
                "D921)",
            ),
        ),
        # D964, a user ruling of 2026-10-23: a real `ow add` priced by wall and CPU time reconciles
        # to 0 micros (D921, D945). The free segment and derive passes are host-metered but have
        # no route_decision, which every route_spend row keys on (D665), so their spend is out of
        # v1.0's scope and disclosed; a pass_spend table comes after. CPU under one accounting
        # tick reads 0 on Windows, a platform's resolution and not a reconciliation gap.
        Coverage.FULL,
        "",
    ),
    Criterion(
        "V10-14",
        "the frozen golden's shape is byte-identical across two pdfium minors x 9 cells",
        (
            pytest(
                f"{CONF}/test_conform_golden.py",
                f"{CORE}/test_ow_golden.py",
                label="the Tier-A goldens and their bless (D848)",
            ),
            pytest(f"{CORE}/test_gate_frozen_stability.py", label="Q-G4's gate, on cells (D849)"),
            Instrument(
                "pytest this machine's cell: a real ingest, its goldens and its shapes (T3)",
                (
                    "-m",
                    "pytest",
                    "-q",
                    "-p",
                    "no:cacheprovider",
                    f"{CORE_T3}/test_golden_process.py",
                    f"{CORE_T3}/test_frozen_stability_process.py",
                ),
                slow=True,
            ),
        ),
        Coverage.PARTIAL,
        "the goldens exist (D848: 26 documents, 78 Reductions), and Q-G4's "
        "tools/gate_frozen_stability.py (D849) compares the shapes each cell emits with them; "
        "this machine is one cell, which the conform tier holds to the goldens. Since D931 each "
        "of the nine `test` cells emits its shapes and the `golden` job compares all nine at one "
        "pinned pdfium (13:673-677's fallback); two cells matched locally (win32 py3.12, linux "
        "py3.13). The pdfium axis is one nightly cell (D966, a user ruling of 2026-10-23): on the "
        "schedule `golden` installs pypdfium2 5.12.1 (pdfium 152) over the lock's 5.13.0 (153), "
        "emits a tenth cell and compares two builds across the nine. 152 and 153 emitted "
        "byte-identical shapes on win32 py3.12 here; the row waits on that nightly's first green "
        "run on master",
    ),
    Criterion(
        "V10-15",
        "ow install records each path's post-write sha256; ow uninstall restores byte-identity",
        (
            tool("gate_install.py"),
            pytest(
                f"{CLI}/test_install_receipt.py",
                f"{CLI}/test_install_verbs.py",
                f"{T3}/test_install_verbs_process.py",
            ),
        ),
        # D971: G35 is law. ADR-16, accepted on 2026-10-23 (a user ruling), allocated the number
        # and section 6.4's row, and its D16.3 makes the fixture home the gate's definition: a CI
        # runner may not write into a person's agent configuration, so "never a real host's
        # config" is the measurement and not its gap. Every written path is held to a receipt row
        # and each file's newest sha256_after to its bytes (D856), on all nine cells (D920).
        Coverage.FULL,
        "",
    ),
    Criterion(
        "V10-16",
        "the harness scores a dropped page, a transposed table and a fabricated quote exactly",
        (
            pytest(
                f"{CONF}/test_conform_judge.py::test_a_dropped_page_fails_exactly_its_assertions",
                f"{CONF}/test_conform_judge.py::"
                "test_a_transposed_table_fails_every_relation_while_every_string_passes",
                f"{CONF}/test_conform_judge.py::"
                "test_a_fabricated_quote_fails_alone_and_prints_both_strings",
                label="Q-G23's three planted defects (D827)",
            ),
            pytest(
                f"{CONF}/test_conform_cells.py::"
                "test_a_transposed_table_fails_every_cell_rel_on_the_owdoc_evaluator",
                label="the transposed table's cell_rel half, on the owdoc evaluator (D877)",
            ),
            pytest(
                f"{CONF}/test_conform_cell_rel_parsed.py",
                label="cell_rel over a parsed DOCX, the table and its transpose (D932)",
            ),
        ),
        Coverage.PARTIAL,
        "the planted defects are synthetic stand-ins for sec-exhibit-scan and "
        "xlsx-merged-4m-cells, which are not in the tree. Since D932 the parse suite hands "
        "judge() each labelled fixture's parsed Doc, and a transposed table in a real parsed DOCX "
        "fails every cell_rel while the untouched one passes; no committed label is a cell_rel "
        "yet, and table_rel_acc rolls up the text evaluator's verdicts only (D816 ruling 1), so a "
        "cell_rel's owdoc verdict is recorded and not in that rate (13:1262's hallucination_rate "
        "claim was dropped by ruling, D900: 13:1096 defines it over field assertions)",
    ),
    Criterion(
        "V10-17",
        "retrieval can exclude ROUNDTRIP Blocks; generated_share is on every Verdict",
        (
            pytest(
                f"{CORE}/test_retrieve_plan.py::test_the_deny_methods_twin_is_the_callers_to_set",
                f"{CORE}/test_store_reader.py::test_the_filters_that_narrow_actually_narrow",
                label="the method filter narrows",
            ),
            tool("schemagen.py", "emit", "--check"),
            pytest(
                f"{CORE}/test_retrieve_execute.py",
                "-k",
                "generated_share or read_back",
                label="generated_share over a seeded read-back: its exact share, and 0.0 denied",
            ),
            pytest(
                "packages/omniweave-target-pptx/tests/unit/test_pptx_out_loop.py::"
                "test_a_corpus_holding_its_own_deck_reports_its_generated_share",
                label="a corpus holding its own compiled deck: 1.0 open, 0.0 denied (D857)",
            ),
            pytest(
                "packages/omniweave/tests/unit/test_query_verb.py::"
                "test_deny_method_roundtrip_reaches_the_filters",
                label="the CLI spelling: ow query ... --deny-method roundtrip (D901)",
            ),
        ),
        Coverage.PARTIAL,
        "the self-ingesting corpus is no longer skipped off Windows (D926: the pptx loop's S4 arm "
        "ran on Linux once a stale named-pipe skip was lifted); it has passed on Windows and "
        "Linux, and its first macOS run is CI's (the CLI spelling, `--deny-method roundtrip`, "
        "is D901's)",
    ),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="acceptance_v10", description=(__doc__ or "").split("\n", 1)[0]
    )
    parser.add_argument(
        "--slow", action="store_true", help="also run G19, G22, GR8 and the damage suite"
    )
    parser.add_argument("--only", default="", help="comma-separated criterion ids")
    parser.add_argument("--json", action="store_true", help="print the results as JSON")
    args = parser.parse_args(argv)
    wanted = {one.strip() for one in args.only.split(",") if one.strip()}
    rows = [one for one in CRITERIA if not wanted or one.id in wanted]
    unknown = wanted - {one.id for one in rows}
    if unknown:
        parser.error(f"unknown criterion id(s): {', '.join(sorted(unknown))}")
    results = [evaluate(one, slow=args.slow) for one in rows]
    if args.json:
        sys.stdout.write(json.dumps([asdict(one) for one in results], indent=2) + "\n")
    else:
        for result, criterion in zip(results, rows, strict=True):
            sys.stdout.write(f"{result.verdict:<10} {result.id:<6} {criterion.text}\n")
            for ran in result.ran:
                shown = f"exit {ran['exit']:<3} {ran['seconds']:>6} s  {ran['instrument']}"
                sys.stdout.write(f"             {shown}\n")
            if result.gap:
                sys.stdout.write(f"             gap: {result.gap}\n")
        tally = {
            verdict: sum(1 for one in results if one.verdict is verdict) for verdict in Verdict
        }
        shown = "  ".join(f"{verdict} {count}" for verdict, count in tally.items())
        sys.stdout.write(f"V10: {shown}  of {len(results)}\n")
    return 0 if all(one.verdict is Verdict.PASS for one in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
