"""`omniweave_conform.scoreboard`: the published tree and Q-G19. D828."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest
from omniweave_conform.scoreboard import REQUIRED, check, export, stale, write
from omniweave_core.drivers.card import MeasuredOn
from omniweave_core.errors import QualityError
from omniweave_core.store.oweval import Batch, Corpus, Metric, Run, open_oweval
from omniweave_core.store.oweval import write as store

if TYPE_CHECKING:
    from pathlib import Path

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

CORPUS = Corpus(
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
        fairness={"judge_kappa": 0.81},
    )
    return replace(row, **over)


def _metric(run_id: str, **over: Any) -> Metric:
    row = Metric(
        run_id=run_id,
        metric="order_acc",
        value=0.9,
        n=40,
        ci_lo=0.77,
        ci_hi=0.96,
        method="closed_form",
        truth_kind="rendered",
        state="ok",
    )
    return replace(row, **over)


def _oweval(tmp_path: Path, runs: tuple[Run, ...], metrics: tuple[Metric, ...]) -> Any:
    tmp_path.mkdir(parents=True, exist_ok=True)
    connection = open_oweval(tmp_path / "e.oweval")
    store(connection, Batch(corpora=(CORPUS,), runs=runs, metrics=metrics))
    return connection


@pytest.fixture
def published(tmp_path: Path) -> dict[str, str]:
    connection = _oweval(
        tmp_path,
        (_run("r1"), _run("r2", subject="parse.office.anydoc"), _run("r3", status="unknown")),
        (
            _metric("r1"),
            _metric("r1", metric="table_rel_acc", state="regressed", value=0.6),
            _metric(
                "r1",
                metric="field_acc",
                state="unknown",
                value=None,
                ci_lo=None,
                ci_hi=None,
                method="none",
            ),
            _metric("r2"),
            _metric("r3"),
        ),
    )
    try:
        return export(connection)
    finally:
        connection.close()


def test_one_file_per_suite_and_subject(published: dict[str, str]) -> None:
    assert sorted(published) == ["parse/parse.office.anydoc.json", "parse/parse.pdf.pdfium.json"]


def test_a_row_carries_the_view_and_its_runs_fields(published: dict[str, str]) -> None:
    rows = json.loads(published["parse/parse.pdf.pdfium.json"])
    order = next(r for r in rows if r["metric"] == "order_acc")
    assert set(REQUIRED) <= set(order)
    assert order["standing"] == "RANKED"
    assert order["measured_on"]["runtime"] == "pdfium"
    assert order["not_measured"] == ["handwriting"]
    assert order["confounders"] == ["one embedder"]
    assert order["fairness"] == {"judge_kappa": 0.81}
    assert order["run_id"] == "r1"
    assert (order["corpus_id"], order["corpus_version"]) == ("golden", "2026.09")


def test_every_direction_is_published(published: dict[str, str]) -> None:
    """Section 11.3: no filter, no draft. A regressed row and an UNKNOWN one are rows."""
    rows = json.loads(published["parse/parse.pdf.pdfium.json"])
    states = {r["metric"]: (r["standing"], r["value"]) for r in rows}
    assert states == {
        "field_acc": ("UNKNOWN", None),
        "order_acc": ("RANKED", 0.9),
        "table_rel_acc": ("RANKED", 0.6),
    }


def test_an_unknown_run_is_left_out_by_the_view(published: dict[str, str]) -> None:
    rows = [r for text in published.values() for r in json.loads(text)]
    assert "r3" not in {r["run_id"] for r in rows}


def test_the_bytes_are_canonical(published: dict[str, str]) -> None:
    text = published["parse/parse.pdf.pdfium.json"]
    assert text.endswith("\n")
    rows = json.loads(text)
    assert [r["metric"] for r in rows] == ["field_acc", "order_acc", "table_rel_acc"]
    assert json.dumps(rows, sort_keys=True, indent=2, ensure_ascii=False) + "\n" == text


def test_the_same_oweval_writes_the_same_bytes(tmp_path: Path) -> None:
    one = _oweval(tmp_path / "a", (_run("r1"),), (_metric("r1"),))
    two = _oweval(tmp_path / "b", (_run("r1"),), (_metric("r1"),))
    try:
        assert export(one) == export(two)
    finally:
        one.close()
        two.close()


# --- Q-G19 -----------------------------------------------------------------------------------


def _row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "suite": "parse",
        "subject": "s",
        "metric": "m",
        "slice_key": "__macro__",
        "value": 0.5,
        "n": 40,
        "ci_lo": 0.3,
        "ci_hi": 0.7,
        "method": "closed_form",
        "truth_kind": "human",
        "measured_on": {"runtime": "x"},
        "witness": "ci",
        "unpinned": False,
        "entrant_bias": False,
        "not_measured": ["handwriting"],
        "confounders": ["one embedder"],
        "standing": "RANKED",
    }
    row.update(over)
    return row


@pytest.mark.parametrize(
    ("over", "match"),
    [
        ({"not_measured": []}, "not_measured empty"),
        ({"confounders": []}, "confounders empty"),
        ({"measured_on": {}}, "not a MeasuredOn"),
        ({"value": None}, r"\['value'\] null with method 'closed_form'"),
        ({"method": "none"}, "a number on a row whose method is none"),
    ],
)
def test_q_g19_refuses_an_empty_or_inconsistent_row(over: dict[str, Any], match: str) -> None:
    with pytest.raises(QualityError, match=match):
        check([_row(**over)])


def test_q_g19_refuses_a_missing_field() -> None:
    row = _row()
    del row["witness"]
    with pytest.raises(QualityError, match=r"missing \['witness'\]"):
        check([row])


def test_an_unknown_row_has_no_number() -> None:
    check([_row(value=None, ci_lo=None, ci_hi=None, method="none", standing="UNKNOWN")])


def test_export_refuses_a_run_with_no_scope(tmp_path: Path) -> None:
    connection = _oweval(tmp_path, (_run("r1", not_measured=()),), (_metric("r1"),))
    try:
        with pytest.raises(QualityError, match="not_measured empty"):
            export(connection)
    finally:
        connection.close()


def test_a_subject_that_leaves_its_directory_is_refused(tmp_path: Path) -> None:
    connection = _oweval(tmp_path, (_run("r1", subject="../x"),), (_metric("r1"),))
    try:
        with pytest.raises(QualityError, match="cannot name a results file"):
            export(connection)
    finally:
        connection.close()


# --- the byte clause -------------------------------------------------------------------------


def test_stale_names_changed_missing_and_extra_files(
    tmp_path: Path, published: dict[str, str]
) -> None:
    root = tmp_path / "results"
    write(root, published)
    assert stale(root, published) == ()
    changed = dict(published)
    changed["parse/parse.pdf.pdfium.json"] = changed["parse/parse.pdf.pdfium.json"].replace(
        "0.9", "0.91"
    )
    assert stale(root, changed) == ("parse/parse.pdf.pdfium.json",)
    (root / "parse" / "old.json").write_text("[]\n", encoding="utf-8")
    assert stale(root, published) == ("parse/old.json",)
    fewer = {k: v for k, v in published.items() if "anydoc" not in k}
    assert "parse/parse.office.anydoc.json" in stale(root, fewer)
    assert stale(tmp_path / "none", published) == tuple(sorted(published))
