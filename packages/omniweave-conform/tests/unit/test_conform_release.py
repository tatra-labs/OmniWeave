"""`omniweave_conform.release`: what `ow eval release-check` refuses on, ruling by ruling. D840."""

from __future__ import annotations

import tomllib
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from omniweave_conform import entry
from omniweave_conform.release import (
    DECLARED_UNKNOWN,
    NOT_APPLICABLE,
    SUITES,
    Finding,
    Gate,
    check_release,
    hard_gates,
    latest,
)
from omniweave_conform.rollup import MACRO
from omniweave_core.drivers.card import MeasuredOn
from omniweave_core.errors import QualityError
from omniweave_core.store.oweval import (
    Batch,
    Corpus,
    Metric,
    Perf,
    Run,
    RunStatus,
    open_oweval,
    perf,
    run_statuses,
)
from omniweave_core.store.oweval import write as store

REPO = Path(__file__).resolve().parents[4]
_GATE_FIX = "fix the regression; a hard budget moves only by a reviewed eval/gates.toml diff"

_MEASURED = MeasuredOn(
    weights="n/a",
    weights_revision="n/a",
    runtime="pdfium",
    runtime_version="6721",
    sampling="{}",
    prompt_version="n/a",
    hardware="ow-bench-1",
    corpus="golden@2026.09",
    corpus_digest="sha256:" + "ab" * 32,
    harness_version="0.1.0",
)
_CORPUS = Corpus(
    corpus_id="golden",
    version="2026.09",
    corpus_digest="sha256:" + "ab" * 32,
    tier="A",
    n_docs=1,
    n_assertions=1,
    n_checked=1,
    document_redistributable=True,
    assertions_redistributable=True,
    publishable=True,
)
_PRIVATE = replace(_CORPUS, corpus_id="private", publishable=False)
_SPAN = {"metric": "span_exact_rate", "suite": "parse", "slice": "*", "kind": "hard"}
REGISTER = {
    "gate": [
        {**_SPAN, "budget": 1.0, "class": "blocking"},
        {
            "metric": "degradation_detection",
            "suite": "absence",
            "slice": "*",
            "kind": "hard",
            "budget": 1.0,
            "class": "blocking",
        },
    ]
}


def _run(run_id: str, **over: Any) -> Run:
    row = Run(
        run_id=run_id,
        suite="parse",
        corpus_id="golden",
        corpus_version="2026.09",
        corpus_digest="sha256:" + "ab" * 32,
        subject="parse.pdf.pdfium",
        subject_version="0.1.0",
        producer_id=None,
        measured_on=_MEASURED,
        timing_basis="in_process",
        witness="ci",
        cassette="required",
        policy_digest=None,
        pricebook_digest=None,
        harness_version="0.1.0",
        code_fingerprint="c0ffee",
        hardware="ow-bench-1",
        started_ns=1,
        ended_ns=2,
        status="ok",
        not_measured=("handwriting",),
        confounders=("one embedder",),
    )
    return replace(row, **over)


def _metric(run_id: str, metric: str = "span_exact_rate", **over: Any) -> Metric:
    row = Metric(
        run_id=run_id,
        metric=metric,
        value=1.0,
        n=40,
        ci_lo=0.91,
        ci_hi=1.0,
        method="exact",
        truth_kind="rendered",
        state="ok",
    )
    return replace(row, **over)


def _unknown(run_id: str, metric: str = "span_exact_rate", **over: Any) -> Metric:
    return _metric(
        run_id, metric, value=None, ci_lo=None, ci_hi=None, method="none", state="unknown", **over
    )


def _perf(run_id: str, status: str, budget_id: str = "B-parse-p50") -> Perf:
    return Perf(run_id, budget_id, 100, 100, 50, 0.5, None, None, status)


_PARSE = _run("r1")
_ABSENCE = _run("r2", suite="absence", subject="omniweave.absence")
_CLEAN = (
    (_PARSE, _ABSENCE),
    (_metric("r1"), _metric("r2", "degradation_detection")),
)


def _judge(
    tmp_path: Path,
    runs: tuple[Run, ...] = _CLEAN[0],
    metrics: tuple[Metric, ...] = _CLEAN[1],
    perfs: tuple[Perf, ...] = (),
    *,
    register: dict[str, Any] = REGISTER,
    strict: bool = False,
) -> Any:
    tmp_path.mkdir(parents=True, exist_ok=True)
    connection = open_oweval(tmp_path / "e.oweval")
    try:
        store(
            connection,
            Batch(corpora=(_CORPUS, _PRIVATE), runs=runs, metrics=metrics, perf=perfs),
        )
        return check_release(connection, register, strict=strict)
    finally:
        connection.close()


def _kinds(judged: Any) -> list[tuple[str, str]]:
    return [(f.kind, f.names) for f in judged.findings]


# --- the store readers ------------------------------------------------------------------------


def test_the_readers_return_every_run_and_perf_row_unknown_ones_included(tmp_path: Path) -> None:
    connection = open_oweval(tmp_path / "e.oweval")
    try:
        store(
            connection,
            Batch(
                corpora=(_CORPUS,),
                runs=(_run("r2", status="unknown", started_ns=7), _run("r1")),
                perf=(_perf("r2", "unstable"), _perf("r1", "pass", "B-a")),
            ),
        )
        assert run_statuses(connection) == (
            RunStatus("r1", "parse", "parse.pdf.pdfium", "golden", 1, "ok", ("handwriting",)),
            RunStatus("r2", "parse", "parse.pdf.pdfium", "golden", 7, "unknown", ("handwriting",)),
        )
        assert perf(connection) == (_perf("r1", "pass", "B-a"), _perf("r2", "unstable"))
    finally:
        connection.close()


# --- ruling 1: the latest run ----------------------------------------------------------------


def _status(run_id: str, started_ns: int, **over: str) -> RunStatus:
    row = RunStatus(run_id, "parse", "parse.pdf.pdfium", "golden", started_ns, "ok", ())
    return replace(row, **over)


def test_latest_keeps_the_greatest_start_per_suite_subject_and_corpus() -> None:
    rows = (
        _status("a", 5),
        _status("b", 9),
        _status("c", 1, subject="parse.office.anydoc"),
        _status("d", 2, corpus_id="tier-b"),
        _status("e", 3, suite="extract"),
    )
    assert [run.run_id for run in latest(rows)] == ["b", "c", "d", "e"]


def test_latest_breaks_a_tie_on_start_by_run_id_whatever_the_order() -> None:
    assert [run.run_id for run in latest((_status("b", 5), _status("a", 5)))] == ["b"]
    assert [run.run_id for run in latest((_status("a", 5), _status("b", 5)))] == ["b"]


def test_a_clean_store_passes(tmp_path: Path) -> None:
    judged = _judge(tmp_path)
    assert judged.ok
    assert (judged.runs, judged.superseded, judged.gates, judged.findings) == (2, 0, 2, ())


def test_a_superseded_run_is_counted_and_never_judged(tmp_path: Path) -> None:
    """An older `ok` run's rows are in the view, so it is the scoreboard filter this holds."""
    lost, old = _run("r00", status="unknown", started_ns=0), _run("r0")
    judged = _judge(
        tmp_path,
        (lost, old, replace(_PARSE, started_ns=5), _ABSENCE),
        (_metric("r0", value=0.5), _unknown("r0", "order_acc"), *_CLEAN[1]),
        (_perf("r0", "fail"), _perf("r00", "unknown")),
    )
    assert judged.ok
    assert (judged.runs, judged.superseded) == (2, 2)


# --- rulings 2-4: unknown runs, metrics and perf rows ------------------------------------------


def test_an_unknown_latest_run_refuses_naming_what_it_did_not_measure(tmp_path: Path) -> None:
    judged = _judge(tmp_path, (_PARSE, replace(_ABSENCE, status="unknown")))
    assert not judged.ok
    assert judged.findings[0] == Finding(
        "run",
        "absence/omniweave.absence run r2",
        "status unknown; not measured: handwriting",
        "fix what stopped the run, then ow eval run --suite absence",
    )
    #  The view leaves an unknown run out, so its hard gate is unmeasured too.
    assert _kinds(judged) == [
        ("run", "absence/omniweave.absence run r2"),
        ("unmeasured", "hard gate degradation_detection@*"),
    ]


def test_an_unknown_parse_run_s_fix_names_its_driver_and_no_other_suite_s_does(
    tmp_path: Path,
) -> None:
    """D872: `ow eval run` takes `--subject` for a parse driver alone, so only there is it named."""
    judged = _judge(tmp_path, (replace(_PARSE, status="unknown"), _ABSENCE))
    assert judged.findings[0].fix == (
        "fix what stopped the run, then ow eval run --suite parse --subject parse.pdf.pdfium"
    )


def test_an_unknown_run_that_names_nothing_says_so(tmp_path: Path) -> None:
    judged = _judge(tmp_path, (_PARSE, replace(_ABSENCE, status="unknown", not_measured=())))
    assert judged.findings[0].why == "status unknown; not measured: (none named)"


def test_a_partial_run_does_not_refuse(tmp_path: Path) -> None:
    assert _judge(tmp_path, (replace(_PARSE, status="partial"), _ABSENCE)).ok


def test_an_unknown_metric_refuses_once_even_under_a_hard_gate(tmp_path: Path) -> None:
    judged = _judge(tmp_path, metrics=(_unknown("r1"), _unknown("r1", "order_acc"), _CLEAN[1][1]))
    assert _kinds(judged) == [
        ("metric", "order_acc@__macro__ in parse/parse.pdf.pdfium run r1"),
        ("metric", "span_exact_rate@__macro__ in parse/parse.pdf.pdfium run r1"),
    ]
    assert {f.why for f in judged.findings} == {"UNKNOWN"}


def test_a_declared_unknown_metric_is_disclosed_and_does_not_refuse(tmp_path: Path) -> None:
    """D1017, a user ruling of 2026-10-29. `false_confident_zero`'s population is the whole
    answerable set, 13 against `min_slice_n = 30`, so no signature and no rerun can compute it.

    It is DISCLOSED and not refused: `ok` does not read `disclosed`, the report prints it, and the
    detail the run computed is kept -- a reader has to see "0 of 13", not merely that something was
    withheld.
    """
    run = replace(
        _ABSENCE,
        not_measured=(
            "false_confident_zero: 0 of 13 answerable question(s) answered absent, "
            "under min_slice_n = 30 (13:1088)",
        ),
    )
    #  `degradation_detection` must be present and scoring: the absence suite IS applicable,
    #  and a hard gate with no matching row refuses as unmeasured, which would mask the point.
    metrics = (*_CLEAN[1], _unknown("r2", "false_confident_zero"))
    judged = _judge(tmp_path, (_PARSE, run), metrics)
    assert judged.ok, [f.line for f in judged.findings]
    assert [f.kind for f in judged.disclosed] == ["declared-unknown"]
    shown = judged.disclosed[0]
    assert shown.names.startswith("false_confident_zero@")
    assert shown.why == (
        "UNKNOWN; 0 of 13 answerable question(s) answered absent, under min_slice_n = 30 (13:1088)"
    ), shown.why
    assert shown.fix == DECLARED_UNKNOWN["false_confident_zero"]
    assert "17 more answerable questions" in shown.fix, "the reason names what would fix it"


def test_an_undeclared_unknown_metric_on_the_same_run_still_refuses(tmp_path: Path) -> None:
    """The other direction, and the one that matters: the exception is one metric wide.

    The `absence` suite IS applicable and DOES run -- this is why D1017 is not `NOT_APPLICABLE`'s
    suite-level mechanism. `degradation_detection` sharing the run must still refuse when it is
    unknown, or declaring one rate would quietly retire the other.
    """
    metrics = (_unknown("r2", "false_confident_zero"), _unknown("r2", "degradation_detection"))
    judged = _judge(tmp_path, (_PARSE, _ABSENCE), (_CLEAN[1][0], *metrics))
    assert not judged.ok
    assert [f.names.split("@")[0] for f in judged.findings] == ["degradation_detection"]
    assert [f.names.split("@")[0] for f in judged.disclosed] == ["false_confident_zero"]


def test_exactly_one_metric_is_declared_unknown_and_its_reason_is_a_real_one() -> None:
    """The register is one row wide, and a reason that said nothing would make the mechanism a
    silent waiver. 13-quality.md:1088's floor and the deferral are both named in it."""
    assert set(DECLARED_UNKNOWN) == {"false_confident_zero"}, DECLARED_UNKNOWN
    reason = DECLARED_UNKNOWN["false_confident_zero"]
    assert "min_slice_n = 30" in reason and "13 questions" in reason
    assert "deferred past v1.0" in reason
    assert "Removing this row means publishing the rate" in reason, (
        "the register's own rule: the fix is the corpus, not the register"
    )


def test_the_declared_metric_is_not_also_a_not_applicable_suite() -> None:
    """The two mechanisms must not overlap. `absence` runs and scores
    `degradation_detection`, so reporting the suite not-applicable would retire a number the
    project has, which is the distinction D987's docstring draws for `perf`."""
    assert "absence" not in NOT_APPLICABLE
    assert "absence" in SUITES


def test_an_unknown_metric_says_what_its_run_said_and_unverified_labels_name_their_fix(
    tmp_path: Path,
) -> None:
    """D913: a rate over labels nobody verified cannot be computed by running it again."""
    run = replace(
        _PARSE,
        not_measured=(
            "order_acc: 12 unverified assertion(s) ran and were not scored (13:1022)",
            "table_rel_acc: below min_slice_n in every slice",
            "span_exact_rate: vacuous",
        ),
    )
    metrics = (_unknown("r1", "order_acc"), _unknown("r1", "table_rel_acc"), _CLEAN[1][1])
    found = _judge(tmp_path, (run, _ABSENCE), metrics).findings
    order, table = [f for f in found if f.kind == "metric"]
    assert order.why == "UNKNOWN; 12 unverified assertion(s) ran and were not scored (13:1022)"
    assert order.fix == (
        'verify its labels: write checked = "verified" on each .assertions.toml row you confirm '
        "against its document, 30 or more a slice, then ow eval run --suite parse"
    )
    assert table.why == "UNKNOWN; below min_slice_n in every slice"
    assert table.fix == "fix what kept the metric from computing, then run its suite again"


def test_withheld_and_unranked_standings_are_not_outcomes(tmp_path: Path) -> None:
    runs = (
        replace(_PARSE, witness="self"),
        replace(_ABSENCE, corpus_id="private"),
    )
    assert _judge(tmp_path, runs).ok


@pytest.mark.parametrize("status", ["fail", "unstable", "stale", "unknown"])
def test_a_perf_row_not_pass_refuses(tmp_path: Path, status: str) -> None:
    judged = _judge(tmp_path, perfs=(_perf("r1", "pass", "B-a"), _perf("r1", status)))
    assert judged.findings == (
        Finding(
            "perf",
            "B-parse-p50 in run r1",
            f"status {status}",
            "fix the Runner or the regression the budget names, then run ow bench again",
        ),
    )


# --- rulings 5 and 6: hard gates ----------------------------------------------------------------


def test_a_hard_gate_off_its_budget_fails_naming_the_value(tmp_path: Path) -> None:
    judged = _judge(tmp_path, metrics=(_metric("r1", value=0.999), _CLEAN[1][1]))
    assert judged.findings == (
        Finding(
            "gate",
            "span_exact_rate@__macro__ in parse/parse.pdf.pdfium run r1",
            "0.999 is not the hard budget 1.0",
            _GATE_FIX,
        ),
    )


def test_a_hard_gate_is_equality_so_a_value_above_it_fails_too(tmp_path: Path) -> None:
    register = {"gate": [{**_SPAN, "budget": 0.5, "class": "blocking"}]}
    judged = _judge(tmp_path, metrics=(_metric("r1", value=1.0),), register=register)
    assert [f.why for f in judged.findings] == ["1.0 is not the hard budget 0.5"]


def test_a_hard_gate_judges_every_slice_its_glob_matches(tmp_path: Path) -> None:
    register = {"gate": [{**_SPAN, "slice": "pdf/*", "budget": 1.0, "class": "blocking"}]}
    metrics = (
        _metric("r1", slice_key="pdf/born_digital"),
        _metric("r1", slice_key="pdf/scanned", value=0.5),
        _metric("r1", slice_key="office", value=0.0),
        _metric("r1", slice_key="PDF/upper", value=0.0),
    )
    judged = _judge(tmp_path, metrics=metrics, register=register)
    assert _kinds(judged) == [
        ("gate", "span_exact_rate@pdf/scanned in parse/parse.pdf.pdfium run r1")
    ]


def test_a_hard_gate_matches_its_suite_and_metric_only(tmp_path: Path) -> None:
    runs = (_PARSE, _ABSENCE, _run("r3", suite="extract", subject="extract.x"))
    metrics = (
        *_CLEAN[1],
        _metric("r3", value=0.0),
        _metric("r1", "span_rate", value=0.0),
    )
    assert _judge(tmp_path, runs, metrics).ok


def test_a_hard_gate_nothing_measured_refuses_as_unmeasured(tmp_path: Path) -> None:
    judged = _judge(tmp_path, (_PARSE,), (_CLEAN[1][0],))
    assert judged.findings == (
        Finding(
            "unmeasured",
            "hard gate degradation_detection@*",
            "no absence run measured it",
            "run the gate's suite: ow eval run --suite absence",
        ),
    )


def test_floors_ceilings_and_informational_rows_are_not_hard_gates() -> None:
    register = {
        "gate": [
            {**_SPAN, "budget": 1.0, "class": "blocking"},
            {**_SPAN, "kind": "floor", "budget": 0.9, "class": "blocking"},
            {**_SPAN, "kind": "ceiling", "budget": 0.1, "class": "blocking"},
            {**_SPAN, "budget": 1.0, "class": "informational"},
        ]
    }
    assert hard_gates(register) == (Gate("span_exact_rate", "parse", "*", 1.0),)
    assert hard_gates({}) == ()


def test_an_integer_budget_is_a_number() -> None:
    register = {"gate": [{**_SPAN, "budget": 1, "class": "blocking"}]}
    assert hard_gates(register) == (Gate("span_exact_rate", "parse", "*", 1.0),)


@pytest.mark.parametrize(
    ("row", "match"),
    [
        ({"metric": None}, "#1 has no string metric"),
        ({"suite": ""}, "#1 has no string suite"),
        ({"slice": 3}, "#1 has no string slice"),
        ({"budget": True}, "#1 has no numeric budget"),
        ({"budget": "1.0"}, "#1 has no numeric budget"),
    ],
)
def test_a_hard_row_the_check_cannot_read_is_refused(row: dict[str, Any], match: str) -> None:
    gate = {**_SPAN, "budget": 1.0, "class": "blocking", **row}
    with pytest.raises(QualityError, match=match) as raised:
        hard_gates({"gate": [gate]})
    assert (
        raised.value.fix
        == "mend eval/gates.toml's [[gate]] row, then run ow eval release-check again"
    )


def test_a_register_whose_gate_is_not_an_array_of_tables_is_refused() -> None:
    with pytest.raises(QualityError, match="`gate` is not an array of tables"):
        hard_gates({"gate": {"metric": "x"}})
    with pytest.raises(QualityError, match=r"\[\[gate\]\] #2 is not a table"):
        hard_gates({"gate": [{"kind": "floor"}, "span_exact_rate"]})


def test_the_shipped_register_names_its_five_hard_gates() -> None:
    """D870 added `citability_violations`, 13:1094's hard count at 0; D902 added R2's
    `address_survival` at 1.000, and D903 portability's `cell_identity`, each by a user ruling."""
    shipped = tomllib.loads((REPO / "eval" / "gates.toml").read_text(encoding="utf-8"))
    assert {(g.metric, g.suite, g.slice, g.budget) for g in hard_gates(shipped)} == {
        ("span_exact_rate", "parse", "*", 1.0),
        ("degradation_detection", "absence", "*", 1.0),
        ("citability_violations", "retrieve", "*", 0.0),
        ("address_survival", "roundtrip", "*", 1.0),
        ("cell_identity", "portability", "*", 1.0),
    }


# --- ruling 7: --strict ------------------------------------------------------------------------


def test_strict_names_each_suite_with_no_run_in_order(tmp_path: Path) -> None:
    assert _judge(tmp_path / "lax", strict=False).ok
    judged = _judge(tmp_path / "strict", strict=True)
    missing = [s for s in SUITES if s not in ("parse", "absence")]
    assert _kinds(judged) == [("suite", suite) for suite in missing]
    assert judged.findings[0] == Finding(
        "suite", "extract", "no run at all", "run the suite: ow eval run --suite extract"
    )


def test_strict_passes_when_all_seven_suites_ran(tmp_path: Path) -> None:
    runs = tuple(
        _run(f"s{at}", suite=suite, subject=f"{suite}.subject") for at, suite in enumerate(SUITES)
    )
    metrics = (_metric("s0"), _metric(f"s{SUITES.index('absence')}", "degradation_detection"))
    judged = _judge(tmp_path, runs, metrics, strict=True)
    assert judged.ok
    assert judged.runs == len(SUITES)


def test_a_finding_prints_as_one_line() -> None:
    finding = Finding("perf", "B-x in run r1", "status stale", "fix")
    assert finding.line == "perf        B-x in run r1: status stale"


# --- the entry point ---------------------------------------------------------------------------


_RETRIEVE = _run("r3", suite="retrieve", subject="omniweave")
_NO_VIOLATION = _metric("r3", "citability_violations", value=0.0)
"""The shipped register's third hard gate, met (D870)."""
_ROUNDTRIP = _run("r4", suite="roundtrip", subject="compile.docx.native")
_SURVIVED = _metric("r4", "address_survival", value=1.0, slice_key="docx")
"""The shipped register's fourth hard gate, met: every docx address survived (D902)."""
_PORTABLE = _run("r5", suite="portability", subject="omniweave")
_IDENTICAL = _metric("r5", "cell_identity", value=1.0, slice_key="shape")
"""The fifth, met: every shape identical to its frozen value (D903)."""


def _files(
    tmp_path: Path,
    *runs: Run,
    metrics: tuple[Metric, ...] = (*_CLEAN[1], _NO_VIOLATION, _SURVIVED, _IDENTICAL),
) -> Path:
    connection = open_oweval(tmp_path / "e.oweval")
    try:
        store(
            connection,
            Batch(
                corpora=(_CORPUS,),
                runs=runs or (*_CLEAN[0], _RETRIEVE, _ROUNDTRIP, _PORTABLE),
                metrics=metrics,
            ),
        )
    finally:
        connection.close()
    (tmp_path / "gates.toml").write_bytes((REPO / "eval" / "gates.toml").read_bytes())
    return tmp_path


def test_the_entry_point_returns_builtins(tmp_path: Path) -> None:
    root = _files(
        tmp_path,
        metrics=(_metric("r1", value=0.5), _CLEAN[1][1], _NO_VIOLATION, _SURVIVED, _IDENTICAL),
    )
    done = entry.release_check(
        oweval=str(root / "e.oweval"), gates=str(root / "gates.toml"), strict=False
    )
    assert done == {
        "ok": False,
        "runs": 5,
        "superseded": 0,
        "gates": 5,
        "findings": [
            {
                "kind": "gate",
                "names": "span_exact_rate@__macro__ in parse/parse.pdf.pdfium run r1",
                "why": "0.5 is not the hard budget 1.0",
                "fix": _GATE_FIX,
            }
        ],
        #  D987: present and empty. A store with no `extract` run discloses nothing, and the key
        #  is in the contract either way so a reader never has to guess whether it was omitted or
        #  there was nothing to say.
        "disclosed": [],
    }


def test_the_entry_point_passes_a_clean_store_and_strict_reaches_it(tmp_path: Path) -> None:
    root = _files(tmp_path)
    paths = {"oweval": str(root / "e.oweval"), "gates": str(root / "gates.toml")}
    assert entry.release_check(**paths, strict=False)["ok"] is True
    findings = entry.release_check(**paths, strict=True)["findings"]
    assert isinstance(findings, list)
    assert len(findings) == len(SUITES) - 5


@pytest.mark.parametrize(("missing", "fix"), [("e.oweval", "--oweval"), ("gates.toml", "--gates")])
def test_the_entry_point_refuses_a_missing_file_and_creates_none(
    tmp_path: Path, missing: str, fix: str
) -> None:
    root = _files(tmp_path)
    (root / missing).unlink()
    with pytest.raises(QualityError, match="no file at") as raised:
        entry.release_check(
            oweval=str(root / "e.oweval"), gates=str(root / "gates.toml"), strict=False
        )
    assert fix in raised.value.fix
    assert not (root / missing).exists()


def test_one_element_that_did_not_survive_refuses_the_release(tmp_path: Path) -> None:
    """D902: R2 is hard at 1.000, so 0.5 on one target is a gate finding."""
    lost = _metric("r4", "address_survival", value=0.5, slice_key="docx")
    root = _files(tmp_path, metrics=(*_CLEAN[1], _NO_VIOLATION, lost, _IDENTICAL))
    done = entry.release_check(
        oweval=str(root / "e.oweval"), gates=str(root / "gates.toml"), strict=False
    )
    assert done["ok"] is False
    (finding,) = done["findings"]  # type: ignore[misc]
    assert finding["names"] == "address_survival@docx in roundtrip/compile.docx.native run r4"
    assert finding["why"] == "0.5 is not the hard budget 1.0"


def test_one_part_that_differs_on_this_cell_refuses_the_release(tmp_path: Path) -> None:
    """D903: portability is hard at 1.000, so one differing part on one target is a finding."""
    moved = _metric("r5", "cell_identity", value=0.975, slice_key="shape")
    root = _files(tmp_path, metrics=(*_CLEAN[1], _NO_VIOLATION, _SURVIVED, moved))
    done = entry.release_check(
        oweval=str(root / "e.oweval"), gates=str(root / "gates.toml"), strict=False
    )
    assert done["ok"] is False
    (finding,) = done["findings"]  # type: ignore[misc]
    assert finding["names"] == "cell_identity@shape in portability/omniweave run r5"
    assert finding["why"] == "0.975 is not the hard budget 1.0"


# ---------------------------------------------------------------------------
# D1023: a thin slice beside a macro that computed is disclosed, not refused
# ---------------------------------------------------------------------------


def _thin(run_id: str, metric: str, key: str, n: int) -> Metric:
    """A slice under `min_slice_n`, as 13:406 requires one: `method = none`, no value."""
    return _unknown(run_id, metric, slice_key=key, n=n)


def test_a_thin_slice_beside_a_computed_macro_is_disclosed(tmp_path: Path) -> None:
    """D1023, a user ruling of 2026-10-30.

    13:406 REQUIRES the thin slice's own row so it *"never silently drops out of the macro mean"*,
    and ruling 3 refused every `UNKNOWN` row. Both held only until a corpus had a fat slice and a
    thin one at once -- which is D1002's one-coarse-slice-per-family exactly. On the shipped corpus
    that was eighteen rows, and eighteen refusals for the honest report the register asked for.
    """
    rows = (
        *_CLEAN[1],
        _metric("r1", "structure_f1", slice_key=MACRO, n=33, value=0.954),
        _metric("r1", "structure_f1", slice_key="office/labelled", n=33, value=0.954),
        _thin("r1", "structure_f1", "office/docx", 6),
        _thin("r1", "structure_f1", "office/xls", 1),
    )
    judged = _judge(tmp_path, metrics=rows)
    assert _kinds(judged) == [], "a thin slice refuses nothing"
    thin = [f for f in judged.disclosed if f.kind == "under-min-slice"]
    assert [f.names.split("@")[1].split(" in ")[0] for f in thin] == ["office/docx", "office/xls"]
    assert "6 of 30 (13:406), and the macro computed" in thin[0].why
    assert judged.ok


def test_an_unknown_macro_still_refuses_and_takes_its_slices_with_it(tmp_path: Path) -> None:
    """The narrowness, driven. A metric whose HEADLINE is unknown has measured nothing anyone may
    read, so neither it nor its slices are excused -- otherwise a metric with no fat slice at all
    would disclose its way to exit 0, which is the hole this ruling must not open."""
    rows = (
        *_CLEAN[1],
        _unknown("r1", "structure_f1", slice_key=MACRO, n=0),
        _thin("r1", "structure_f1", "office/docx", 6),
    )
    judged = _judge(tmp_path, metrics=rows)
    assert [name for _kind, name in _kinds(judged)] != [], "an unknown macro refuses"
    refused = {name.split("@")[1].split(" in ")[0] for _kind, name in _kinds(judged)}
    assert refused == {MACRO, "office/docx"}
    assert not judged.ok


def test_a_slice_unknown_for_another_reason_is_not_excused(tmp_path: Path) -> None:
    """`method = "none"` with `0 < n` is what says "under min_slice_n" and nothing else does. A row
    that is unknown with a method, or with no population at all, is a different gap."""
    rows = (
        *_CLEAN[1],
        _metric("r1", "structure_f1", slice_key=MACRO, n=33, value=0.954),
        _metric(
            "r1",
            "structure_f1",
            slice_key="office/docx",
            n=6,
            value=None,
            ci_lo=None,
            ci_hi=None,
            method="exact",
            state="unknown",
        ),
        _thin("r1", "structure_f1", "office/odp", 0),
    )
    judged = _judge(tmp_path, metrics=rows)
    refused = {name.split("@")[1].split(" in ")[0] for _kind, name in _kinds(judged)}
    assert refused == {"office/docx", "office/odp"}, "neither is an under-min row"
    assert not judged.ok
