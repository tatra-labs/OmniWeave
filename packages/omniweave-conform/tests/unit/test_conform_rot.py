"""`omniweave_conform.rot`: Q-G27's two-release clock. D829."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest
from omniweave_conform.rot import RELEASES, Clock, gated, published, rot
from omniweave_conform.scoreboard import export, tree, write
from omniweave_core.drivers.card import MeasuredOn
from omniweave_core.errors import QualityError
from omniweave_core.store.oweval import Batch, Corpus, Metric, Run, open_oweval
from omniweave_core.store.oweval import write as store

if TYPE_CHECKING:
    from pathlib import Path

GATED = {"gate": [{"metric": "span_exact_rate", "slice": "*"}]}


def _row(metric: str, version: str, corpus_id: str = "golden", **over: Any) -> dict[str, Any]:
    return {"metric": metric, "corpus_id": corpus_id, "corpus_version": version, **over}


def _tree(*rows: dict[str, Any]) -> dict[str, str]:
    return {"parse/s.json": json.dumps(list(rows))}


def test_two_releases_are_the_edge_and_the_third_rots() -> None:
    assert RELEASES == 2
    two = rot(_tree(_row("field_acc", "2026.09"), _row("field_acc", "2026.12")), GATED)
    assert two == (Clock("field_acc", "golden", ("2026.09", "2026.12")),)
    assert not two[0].rotten
    three = rot(
        _tree(
            _row("field_acc", "2027.03"), _row("field_acc", "2026.09"), _row("field_acc", "2026.12")
        ),
        GATED,
    )
    assert three == (Clock("field_acc", "golden", ("2026.09", "2026.12", "2027.03")),)
    assert three[0].rotten


def test_a_gated_metric_runs_no_clock_whatever_its_row_says() -> None:
    """Ruling 1: a row in another slice, informational, or active from a future version."""
    register = {
        "gate": [
            {"metric": "order_acc", "slice": "office/*", "class": "informational"},
            {"metric": "source_reread_rate", "active_from": "v1.0", "budget_max": 0.25},
        ]
    }
    rows = [_row(m, v) for m in ("order_acc", "source_reread_rate") for v in ("a", "b", "c")]
    assert rot(_tree(*rows), register) == ()
    assert gated(register) == {"order_acc", "source_reread_rate"}


def test_each_corpus_runs_its_own_clock() -> None:
    """Ruling 2: four releases across two corpora are two clocks of two."""
    clocks = rot(
        _tree(
            _row("recall_at_10", "1", "golden"),
            _row("recall_at_10", "2", "golden"),
            _row("recall_at_10", "1", "bench_serve"),
            _row("recall_at_10", "3", "bench_serve"),
        ),
        GATED,
    )
    assert [(c.corpus_id, c.versions, c.rotten) for c in clocks] == [
        ("bench_serve", ("1", "3"), False),
        ("golden", ("1", "2"), False),
    ]


def test_a_release_counts_once_however_many_rows_it_published() -> None:
    files = {
        "parse/a.json": json.dumps([_row("field_acc", "1", slice_key=s) for s in "xyz"]),
        "parse/b.json": json.dumps([_row("field_acc", "1"), _row("field_acc", "2")]),
    }
    assert published(files) == {("field_acc", "golden"): frozenset({"1", "2"})}
    assert not rot(files, GATED)[0].rotten


def test_every_standing_counts() -> None:
    """Ruling 3: an UNKNOWN row and a WITHHELD one are on the board."""
    rows = [
        _row("field_acc", "1", standing="UNKNOWN", value=None),
        _row("field_acc", "2", standing="WITHHELD"),
        _row("field_acc", "3", standing="UNKNOWN", value=None),
    ]
    assert rot(_tree(*rows), GATED)[0].rotten


def test_the_line_names_the_metric_corpus_and_releases() -> None:
    clock = Clock("field_acc", "golden", ("1", "2", "3"))
    assert clock.line() == "field_acc on golden: 3 of 2 ungated release(s) (1, 2, 3)"


@pytest.mark.parametrize(
    ("files", "match"),
    [
        ({"p/s.json": "[{"}, r"p/s.json: not JSON \("),
        ({"p/s.json": "{}"}, "p/s.json: not a list of rows"),
        ({"p/s.json": "[1]"}, "row 1 does not name its metric, corpus_id, corpus_version"),
        ({"p/s.json": json.dumps([_row("m", "1"), {"metric": "m"}])}, "row 2 does not name"),
        ({"p/s.json": json.dumps([_row("", "1")])}, "row 1 does not name"),
        ({"p/s.json": json.dumps([{**_row("m", "1"), "corpus_id": 7}])}, "row 1 does not name"),
    ],
)
def test_an_unreadable_tree_is_refused(files: dict[str, str], match: str) -> None:
    """Ruling 5."""
    with pytest.raises(QualityError, match=match):
        rot(files, GATED)


@pytest.mark.parametrize(
    ("register", "match"),
    [
        ({"gate": {"metric": "m"}}, "`gate` is not an array of tables"),
        ({"gate": [{"metric": "m"}, {"slice": "*"}]}, r"\[\[gate\]\] #2 names no metric"),
        ({"gate": [{"metric": ""}]}, r"#1 names no metric"),
        ({"gate": ["m"]}, r"#1 names no metric"),
    ],
)
def test_a_register_row_with_no_metric_is_refused(register: dict[str, Any], match: str) -> None:
    with pytest.raises(QualityError, match=match):
        rot({}, register)


def test_no_register_rows_gate_nothing() -> None:
    assert gated({}) == frozenset()


# --- the published tree, end to end ----------------------------------------------------------

_MEASURED = MeasuredOn(
    weights="n/a",
    weights_revision="n/a",
    runtime="pdfium",
    runtime_version="6721",
    sampling="{}",
    prompt_version="n/a",
    hardware="ow-bench-1",
    corpus="golden",
    corpus_digest="sha256:" + "ab" * 32,
    harness_version="0.1.0",
)


def _release(version: str) -> tuple[Corpus, Run, Metric]:
    corpus = Corpus(
        corpus_id="golden",
        version=version,
        corpus_digest="sha256:" + "ab" * 32,
        tier="A",
        n_docs=1,
        n_assertions=1,
        n_checked=1,
        document_redistributable=True,
        assertions_redistributable=True,
        publishable=True,
    )
    run = Run(
        run_id=f"r{version}",
        suite="parse",
        corpus_id="golden",
        corpus_version=version,
        corpus_digest="sha256:" + "ab" * 32,
        subject="parse.pdf.pdfium",
        subject_version="0.1.0",
        producer_id=None,
        measured_on=replace(_MEASURED, corpus=f"golden@{version}"),
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
        fairness={},
    )
    metric = Metric(
        run_id=f"r{version}",
        metric="order_acc",
        value=0.9,
        n=40,
        ci_lo=0.77,
        ci_hi=0.96,
        method="closed_form",
        truth_kind="rendered",
        state="ok",
    )
    return corpus, run, metric


def test_an_exported_tree_reads_back_into_its_clocks(tmp_path: Path) -> None:
    """The view's `corpus_id` (D829) reaches the published row, and `tree()` reads it back."""
    releases = [_release(v) for v in ("2026.09", "2026.12", "2027.03")]
    connection = open_oweval(tmp_path / "e.oweval")
    try:
        store(
            connection,
            Batch(
                corpora=tuple(r[0] for r in releases),
                runs=tuple(r[1] for r in releases),
                metrics=tuple(r[2] for r in releases),
            ),
        )
        files = export(connection)
    finally:
        connection.close()
    root = tmp_path / "results"
    write(root, files)
    assert tree(root) == files
    assert sorted(files) == ["parse/parse.pdf.pdfium.json"]
    (clock,) = rot(tree(root), GATED)
    assert clock == Clock("order_acc", "golden", ("2026.09", "2026.12", "2027.03"))
    assert clock.rotten
    assert rot(tree(root), {"gate": [{"metric": "order_acc"}]}) == ()


def test_an_absent_tree_reads_as_no_files(tmp_path: Path) -> None:
    assert tree(tmp_path / "none") == {}


def test_a_tree_is_its_json_files_only(tmp_path: Path) -> None:
    """A README or an editor's stray file beside the results is not a results file."""
    files = _tree(_row("field_acc", "1"))
    write(tmp_path, files)
    (tmp_path / "parse" / "README.md").write_bytes(b"# not rows\n")
    (tmp_path / "parse" / "nested.json").mkdir()
    assert tree(tmp_path) == files
