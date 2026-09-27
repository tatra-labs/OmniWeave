"""`tools/acceptance_v01.py`: the roll-up's rules, never its verdicts.

The verdicts are what the instruments say on the day, and a test that pinned them would have to be
edited every time a clause landed. What is pinned is that the table is the plan's seventeen in
order, that every file an instrument names exists (a renamed test must not turn a row into a
pointer at nothing), and that a partial criterion can never read PASS.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
TOOL = REPO_ROOT / "tools" / "acceptance_v01.py"


def _load() -> object:
    spec = importlib.util.spec_from_file_location("acceptance_v01", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


a = _load()


def test_the_table_is_the_plans_seventeen_in_order() -> None:
    """16:750: *"adds nothing to it and subtracts nothing from it"*."""
    ids = [row.id for row in a.CRITERIA]  # type: ignore[attr-defined]
    assert ids == [f"V01-{n}" for n in range(1, 18)]


def test_every_file_an_instrument_names_exists(tmp_path: Path) -> None:
    """A pytest node names a file, and a tool names a script: each must be in the tree."""
    for row in a._with_workspace(tmp_path):  # type: ignore[attr-defined]
        for instrument in row.instruments:
            named = [
                one.split("::", 1)[0]
                for one in instrument.argv
                if one.endswith(".py") or ".py::" in one
            ]
            for rel in named:
                assert (REPO_ROOT / rel).is_file(), f"{row.id}: {rel}"


@pytest.mark.parametrize(
    ("coverage", "exits", "verdict"),
    [
        ("full", [0, 0], "PASS"),
        ("partial", [0, 0], "PARTIAL"),
        ("full", [0, 1], "FAIL"),
        ("partial", [5], "FAIL"),
        ("full", None, "UNMEASURED"),
    ],
)
def test_the_verdict_is_the_coverage_and_the_exits(
    coverage: str, exits: list[int] | None, verdict: str
) -> None:
    """A green run over a partial criterion is PARTIAL, never PASS; any non-zero exit -- pytest's 5,
    "no tests collected", included -- is FAIL; an instrument not run is UNMEASURED."""
    row = a.Criterion(  # type: ignore[attr-defined]
        "V01-x",
        "t",
        (a.tool("x.py"),),  # type: ignore[attr-defined]
        a.Coverage(coverage),  # type: ignore[attr-defined]
        "" if coverage == "full" else "a clause",
    )
    assert str(a.judge(row, exits)) == verdict  # type: ignore[attr-defined]


def test_a_criterion_nothing_measures_is_unmeasured_whatever_else() -> None:
    row = a.Criterion("V01-x", "t", (), a.Coverage.NONE, "nothing measures it")  # type: ignore[attr-defined]
    assert str(a.judge(row, None)) == "UNMEASURED"  # type: ignore[attr-defined]


def test_the_gap_travels_with_the_coverage() -> None:
    """A partial row that did not say which clause is missing would be a PARTIAL nobody can act on,
    and a full row carrying a gap would contradict itself."""
    with pytest.raises(ValueError, match="gap is required"):
        a.Criterion("V01-x", "t", (a.tool("x.py"),), a.Coverage.PARTIAL)  # type: ignore[attr-defined]
    with pytest.raises(ValueError, match="gap is required"):
        a.Criterion("V01-x", "t", (a.tool("x.py"),), a.Coverage.FULL, "a clause")  # type: ignore[attr-defined]
    with pytest.raises(ValueError, match="coverage NONE"):
        a.Criterion("V01-x", "t", (a.tool("x.py"),), a.Coverage.NONE, "x")  # type: ignore[attr-defined]


def test_the_slow_row_writes_nothing_into_the_tree(tmp_path: Path) -> None:
    """V01-10's measurement regenerates a 5,000-page PDF; pointed at the scratch directory, the
    tree's `fixtures/generated/` is never touched by an acceptance run."""
    (v0110,) = [row for row in a._with_workspace(tmp_path) if row.id == "V01-10"]  # type: ignore[attr-defined]
    (instrument,) = v0110.instruments
    assert instrument.slow
    assert str(tmp_path / "gen_5000p.pdf") in instrument.argv
    assert str(tmp_path / "store") in instrument.argv


def test_anything_short_of_every_row_passing_exits_one(capsys: pytest.CaptureFixture[str]) -> None:
    """V01-11 has no instrument, so this runs nothing and is instant. UNMEASURED is not accepted."""
    assert a.main(["--only", "V01-11"]) == 1  # type: ignore[attr-defined]
    assert "UNMEASURED V01-11" in capsys.readouterr().out
