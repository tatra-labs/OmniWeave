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

**Exit 0 only when all seventeen are PASS.** Today none is. Fifteen rows are PARTIAL at best and
two have no instrument at all, because what v1.0 is measured by does not exist yet:
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
        "no `v*` tag to be green on; `ow eval run` measures parse, absence, retrieve and "
        "roundtrip and `ow eval release-check` passes over them (D868-D871), but `--strict` "
        "refuses on extract, portability and perf, which no harness measures (D872), and no "
        "`.oweval` is committed for a tag; G13 and G25 have no runner "
        "and G29 is planned only; Q-G16 and 20 have no instrument, Q-G26 runs its assertion "
        "clause only (D875), Q-G2 runs without "
        "its orphan-cassette sweep, and "
        "Q-G8, 19 and 25 run their static halves only; Q-G22's gate runs the T1/T2 suite and "
        "Q-G4's reads the CI cells, so this row runs their tests and not them; the `gates` CI "
        "job is off. This row runs the Q-G "
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
        "and the two passes byte-identical (D874), but the weight ceilings are checked as "
        "declared, not measured: the 250 MB union needs `--measure` over an installed "
        "`[recommended]` environment, the three offline wheelhouse profiles are unwired, and "
        "`ow doctor --runtime`'s vision size (D-10) is unbuilt",
    ),
    Criterion(
        "V10-3",
        "accuracy floors from eval/gates.toml: structure_f1, order_acc, table_rel_acc, ...",
        (),
        Coverage.NONE,
        "eval/gates.toml carries no accuracy floor and no Tier A corpus exists to score; "
        "`omniweave_conform.rollup` computes the rates (D816) over nothing yet",
    ),
    Criterion(
        "V10-4",
        "honesty ceilings: hallucination_rate, false_confident_zero, degradation_detection == 1",
        (tool("ow_damage.py", "--deterministic-half", slow=True),),
        Coverage.PARTIAL,
        "degradation_detection runs over 4 of 13 Injectors and the deterministic half only, "
        "now as `ow eval run --suite absence` too (D869); citability_violations is a hard row "
        "measured over the adoption catalogue (D870), which V10-1's instrument runs; "
        "hallucination_rate and false_confident_zero have no gate row and nothing computes them "
        "over a corpus",
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
        "no `eval/results/` tree is committed yet, so both static gates pass over nothing; a "
        "number published outside it (a card's [quality] block, docs, release notes) is "
        "scanned by nothing",
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
        ),
        Coverage.PARTIAL,
        "every timing is unmeasured: the `query` and `parse` bench subjects are blocked, no "
        "4M-cell fixture exists, and `ow-bench-1`, the Pacer's seven-run median and the nightly "
        "do not; what runs is the static budget arithmetic",
    ),
    Criterion(
        "V10-7",
        "a nightly 100k-roster run within queue_high_water and 600 MB supervisor RSS",
        (
            # G22's whole run is about 21 minutes here (the ledger's measurement) inside a 90-
            # minute nightly cell, so the runner's 600 s default would fail it on time alone.
            Instrument("tools/gate_scale.py", ("tools/gate_scale.py",), slow=True, timeout_s=3600),
            pytest(f"{CLI}/test_gate_scale.py", label="G22's mechanism, 40-300 units"),
        ),
        Coverage.PARTIAL,
        "no nightly; the run is op.identify only, and the default asserts high_water plus one "
        "plan batch rather than the literal bound (`--strict` overshoots structurally)",
    ),
    Criterion(
        "V10-8",
        "incremental == full: 300 documents, 40 mutations; the graph at 60 and 20 steps",
        (
            tool("gate_incremental.py", slow=True),
            tool("gate_incremental_graph.py", slow=True),
            pytest(
                f"{CORE}/test_gate_incremental.py",
                f"{CORE}/test_fixture_incremental.py",
                f"{CLI}/test_gate_incremental_graph.py",
            ),
            pytest(
                "packages/omniweave/tests/conform/test_add_edit_identity.py",
                label="what a real `ow add` does with an edited file (D880, D882)",
            ),
        ),
        Coverage.PARTIAL,
        "G19 indexes through `tools/p2_stub_parse.py` and a DocSink, not the product's `ow add`, "
        "and reports gen and revision differences without failing on them unless --strict (D187). "
        "Whether G19 holds through `ow add` is unmeasured: there an edited file re-added is a new "
        "doc_ord with its predecessor retired (D645), so the live text is right but no cite "
        "carries across an edit, as 03's worked example says it should (D40, pinned by D880 and "
        "corrected by D882)",
    ),
    Criterion(
        "V10-9",
        "pptx, deck and docx reach GateStatus passed; video unimplemented with its reason",
        (
            pytest(
                "packages/omniweave-target-pptx/tests/unit/test_pptx_golden.py",
                "packages/omniweave-target-docx/tests/unit/test_docx_golden.py",
                "packages/omniweave-target-video/tests/unit/test_video_driver.py",
                label="the target goldens and video's card",
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
        Coverage.PARTIAL,
        "the pptx and docx goldens reach MANUAL_REQUIRED, not passed; omniweave-target-deck is a "
        "skeleton with no driver; the bake error's two exits are asserted on pptx and owtext, the "
        "targets with a bake row (D876)",
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
            pytest(
                "packages/omniweave-conform/tests/conform/test_out_determinism_process.py::"
                "test_the_forty_unit_golden_compiles_to_one_part_digest_five_ways",
                "packages/omniweave-target-pptx/tests/unit/test_golden40.py",
                label="the 40-unit golden: generated, pinned, gated, compiled five ways (D881)",
            ),
        ),
        Coverage.PARTIAL,
        "OUT13's in-cell half runs over the register's goldens and over the 40-unit deck "
        "`fixtures/gen/gen_golden40.py` generates: twice here and under three PYTHONHASHSEEDs in "
        "fresh processes, one part_digest across 116 parts (D878, D881). The nine OS/Python cells "
        "run nowhere, and of the reader cards docx's passes the testkit's mandatory tier and "
        "pptx's fails licence on Pillow's MIT-CMU, G3's open question (D879)",
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
        Coverage.PARTIAL,
        "the template driver is authored inside this repository and no external one exists; "
        "`--bench` refuses until `ow eval fetch`, so no [quality] block or MeasuredOn is written",
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
                label="a real ow add verifies under ow cost --verify (D854)",
            ),
        ),
        Coverage.PARTIAL,
        "a real `ow add` of three drivers' documents reconciles under `ow cost --verify` (D854), "
        "but the first-party drivers report no physical metrics, so every parse bill is a "
        "measured zero and a PriceBook pricing wall or CPU time would price nothing; "
        "no run is priced, so the 0-micro equality is "
        "0 == 0; and no test reads every manifest a run emits",
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
        "this machine is one cell, which the conform tier holds to the goldens. No CI job emits "
        "two pdfium builds or the nine cells (the `golden` job and the `test` matrix are off), "
        "so the gate has never read enough cells to run, and the row rests on F31",
    ),
    Criterion(
        "V10-15",
        "ow install records each path's post-write sha256; ow uninstall restores byte-identity",
        (
            pytest(
                f"{CLI}/test_gate_install.py",
                f"{CLI}/test_install_receipt.py",
                f"{CLI}/test_install_verbs.py",
                f"{T3}/test_install_verbs_process.py",
            ),
        ),
        Coverage.PARTIAL,
        "every written path is held to a receipt row and each file's newest sha256_after to its "
        "bytes, over a fixture home (D856), never a real host's config; G-install has no gate row "
        "(D484) and no CI",
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
        ),
        Coverage.PARTIAL,
        "the planted defects are synthetic stand-ins for sec-exhibit-scan and "
        "xlsx-merged-4m-cells, which are not in the tree; cell_rel runs over a hand-built Doc's "
        "Grid (D877), and no suite yet hands judge() a parsed Doc (13:1262's hallucination_rate "
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
        ),
        Coverage.PARTIAL,
        "the self-ingesting corpus is asserted on Windows only, as the pptx loop's S4 arm is, so a "
        "Linux or macOS cell skips it; and the CLI has no spelling for `deny_methods` (07:1663), "
        "so the restriction is an SDK caller's",
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
