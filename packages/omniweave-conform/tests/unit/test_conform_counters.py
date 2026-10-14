"""`omniweave_conform.counters`: `eval/counters.toml` and the exact-or-ratchet judgement. D823."""

from __future__ import annotations

from pathlib import Path

import pytest
from omniweave_conform.counters import (
    RUN_SOURCES,
    SOURCES,
    CounterRow,
    Counters,
    judge,
    load_counters,
)
from omniweave_core.errors import QualityError

REPO = Path(__file__).resolve().parents[4]
REGISTER = REPO / "eval" / "counters.toml"

CHARTER_FIFTEEN = {
    "blocks_written": ("exact", None),
    "pages_committed": ("exact", None),
    "page_renders": ("exact", None),
    "signal_computations": ("exact", None),
    "subprocess_spawns": ("exact", None),
    "service_attaches": ("exact", None),
    "driver_activations": ("exact", None),
    "escalations": ("exact", None),
    "degradations": ("exact", None),
    "llm_calls": ("exact", None),
    "cache_hits": ("exact", None),
    "cache_misses": ("exact", None),
    "rebilled_units": ("exact", None),
    "tokens_out": ("ratchet", 0.02),
    "store_rows_read": ("ratchet", 0.05),
}
"""charter:7516-7562, transcribed by hand here and in the file, so the two agree or a test fails."""


@pytest.fixture(scope="module")
def register() -> Counters:
    return load_counters(REGISTER)


def _row(**over: object) -> CounterRow:
    kw: dict[str, object] = {"id": "x", "cls": "exact", "source": "manifest"}
    kw.update(over)
    return CounterRow(**kw)  # type: ignore[arg-type]


# --- the committed register ------------------------------------------------------------------


def test_the_register_is_the_charters_fifteen_and_the_ci_row(register: Counters) -> None:
    rows = {row.id: (row.cls, row.tolerance) for row in register.rows}
    assert {k: v for k, v in rows.items() if k in CHARTER_FIFTEEN} == CHARTER_FIFTEEN
    assert set(rows) - set(CHARTER_FIFTEEN) == {"ci.job_seconds.*"}
    assert rows["ci.job_seconds.*"] == ("ratchet", 0.25)
    assert (register.owner, register.review_by) == ("team@particle6.com", "2027-06-01")


def test_every_row_names_a_source_and_only_ci_is_ci(register: Counters) -> None:
    assert {row.source for row in register.rows} <= set(SOURCES)
    assert [row.id for row in register.rows if row.source == "ci"] == ["ci.job_seconds.*"]
    sourced = {row.id: row.source for row in register.rows}
    assert {k for k, v in sourced.items() if v == "route_spend"} == {
        "llm_calls",
        "rebilled_units",
        "tokens_out",
    }
    assert sourced["driver_activations"] == "driver_observation"


def test_run_sourced_leaves_ci_out(register: Counters) -> None:
    """13:1989: a `ci` row is read for shape and compared against nothing."""
    run = register.run_sourced()
    assert len(run) == 15
    assert all(row.source in RUN_SOURCES for row in run)
    assert "ci" not in RUN_SOURCES


def test_a_ci_job_falls_under_the_family(register: Counters) -> None:
    row = register.row_for("ci.job_seconds.test-ubuntu-3.11")
    assert row is not None
    assert row.id == "ci.job_seconds.*"
    assert register.row_for("cache_hits") is not None
    assert register.row_for("no_such_counter") is None


# --- the schema ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("over", "match"),
    [
        ({"cls": "approximate"}, "not exact or ratchet"),
        ({"source": "vibes"}, "source 'vibes'"),
        ({"tolerance": 0.1}, "exact and carries a tolerance"),
        ({"cls": "ratchet"}, "needs a tolerance"),
        ({"cls": "ratchet", "tolerance": 0.0}, "needs a tolerance"),
        ({"cls": "ratchet", "tolerance": 1.0}, "needs a tolerance"),
    ],
)
def test_a_malformed_row_is_refused(over: dict[str, object], match: str) -> None:
    with pytest.raises(QualityError, match=match):
        _row(**over)


def _file(tmp_path: Path, body: str, *, gate: bool = True) -> Path:
    head = '[gate]\nowner = "o@x"\nreview_by = "2027-01-01"\n' if gate else ""
    path = tmp_path / "counters.toml"
    path.write_text(head + body, encoding="utf-8")
    return path


def test_a_malformed_file_is_refused(tmp_path: Path) -> None:
    row = '[[counter]]\nid = "a"\nclass = "exact"\nsource = "manifest"\n'
    with pytest.raises(QualityError, match="no \\[gate\\] owner"):
        load_counters(_file(tmp_path, row, gate=False))
    with pytest.raises(QualityError, match=r"repeats \['a'\]"):
        load_counters(_file(tmp_path, row + row))
    with pytest.raises(QualityError, match=r"unknown keys \['budget'\]"):
        load_counters(_file(tmp_path, row + "budget = 3\n"))
    assert len(load_counters(_file(tmp_path, row)).rows) == 1


# --- the judgement ---------------------------------------------------------------------------


def test_exact_fails_a_delta_of_one_either_way() -> None:
    row = _row()
    assert judge(row, 40, 40) == "pass"
    assert judge(row, 40, 41) == "fail"
    assert judge(row, 40, 39) == "fail"


def test_a_ratchet_fails_a_rise_past_its_tolerance_and_passes_a_fall() -> None:
    row = _row(cls="ratchet", tolerance=0.05)
    assert judge(row, 1000, 1050) == "pass"
    assert judge(row, 1000, 1051) == "fail"
    assert judge(row, 1000, 10) == "pass"
    assert judge(row, 0, 0) == "pass"
    assert judge(row, 0, 1) == "fail"


def test_a_negative_count_is_refused() -> None:
    with pytest.raises(QualityError, match="not negative"):
        judge(_row(), -1, 0)
