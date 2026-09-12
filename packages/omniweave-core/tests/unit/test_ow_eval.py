"""Q-G6 as a program: `eval/gates.toml`'s shape, the verdict, and the run on this repository.

`tools/ow_eval.py` is `16-roadmap.md:519`'s P3 exit line —
`uv run ow eval golden --check span_exact_rate   # Q-G6, hard, at 1.000`.

Three subjects here, and they are deliberately separate:

* **the register**, `eval/gates.toml`. `11-repo-layout.md:2693` forbids it from naming a row
  `tools/gates.toml` owns and vice versa, and `13-quality.md:1082` requires an owner and a
  `review_by` on every row. Both are checked, because a register is only worth what its shape
  guarantees.
* **`verdict()`**, which is where the budget lives. It is separated from the measurement on
  purpose — a `MetricResult` that knew its own floor would be a floor with two homes — so it gets
  tested against a synthetic result rather than against a driver.
* **the run**, end to end, over the two shipped drivers. Slow-ish and worth it: it is the only
  test that proves `parse.pdf.pdfium` actually re-verifies 630 spans and that
  `parse.office.anydoc` reports `vacuous` rather than a green 1.0000.

The vacuous case is the one to watch. `13-quality.md:661` says Q-G6 "holds **vacuously**" on every
office slice at release 1, and `17-risks.md` R-T16 registers that as a risk: *"The framework's two
hardest fidelity gates are both green on the format family most users will bring first."* The
mitigation is disclosure, so the tests below assert that the office slice **appears in the report**
and says `vacuous` — a run that quietly omitted it would pass while hiding exactly what R-T16 says
must be visible.
"""

from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


@pytest.fixture(scope="session")
def runner(repo_root: Path) -> ModuleType:
    """`tools/ow_eval.py`, loaded by path and never put on `sys.path`."""
    path = repo_root / "tools" / "ow_eval.py"
    spec = importlib.util.spec_from_file_location("_owtool_eval", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def register(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "eval" / "gates.toml"
    assert path.is_file(), "eval/gates.toml is the metric register (11-repo-layout.md:394)"
    return tomllib.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# the register
# ---------------------------------------------------------------------------


def test_every_metric_row_carries_an_owner_and_a_review_date(register: dict[str, Any]) -> None:
    """13-quality.md:1082: "every gate row carries an owner and a `review_by`, and a row past its
    date fails (`Q-G17`). There is no `--warn-only` anywhere"."""
    rows = register.get("gate", [])
    assert rows, "the register names no metric"
    for row in rows:
        assert row.get("owner"), f"{row.get('metric')} has no owner"
        assert row.get("review_by"), f"{row.get('metric')} has no review_by"
        assert row.get("class") in {"blocking", "informational"}, row.get("metric")


def test_a_floor_with_no_definition_is_not_a_gate(register: dict[str, Any]) -> None:
    """13-quality.md:1087, in as many words. Every row names how it is computed."""
    for row in register.get("gate", []):
        assert row.get("computed", "").strip(), f"{row.get('metric')} states no definition"


def test_a_hard_row_carries_no_guard_band(register: dict[str, Any]) -> None:
    """There is no band below 1.000 to be inside. 13-quality.md:36 names what a band here would
    be: "a byte-exactness claim degrades into an accuracy percentage and nobody notices it fell"."""
    for row in register.get("gate", []):
        if row.get("kind") == "hard":
            assert "guard" not in row, f"{row.get('metric')} is hard and has a guard band"


def test_neither_register_names_a_row_the_other_owns(
    register: dict[str, Any], repo_root: Path
) -> None:
    """11-repo-layout.md:2693 states the rule and 394 states the reason: two files with the same
    name hold two different kinds of gate, and the distinction is load-bearing."""
    g_series = tomllib.loads((repo_root / "tools" / "gates.toml").read_text(encoding="utf-8"))
    g_ids = {str(row.get("id", "")) for row in g_series.get("gate", [])}
    metrics = {str(row.get("metric", "")) for row in register.get("gate", [])}
    assert not (g_ids & metrics)
    assert all(not metric.startswith("G") or not metric[1:].isdigit() for metric in metrics)


def test_every_subject_names_a_card_and_fixtures_that_exist(
    register: dict[str, Any], repo_root: Path
) -> None:
    for row in register.get("subject", []):
        assert (repo_root / str(row["card"])).is_file(), row
        assert (repo_root / str(row["fixtures"])).is_dir(), row
        assert str(row.get("why", "")).strip(), f"{row.get('driver')} says nothing about why"


def test_the_vacuous_slice_is_a_subject_on_purpose(register: dict[str, Any]) -> None:
    """R-T16's mitigation is disclosure, so the office slice must be measured and reported rather
    than left out for having nothing to say."""
    drivers = {str(row.get("driver")) for row in register.get("subject", [])}
    assert "parse.office.anydoc" in drivers
    assert "parse.pdf.pdfium" in drivers


# ---------------------------------------------------------------------------
# the verdict
# ---------------------------------------------------------------------------


def result(runner: ModuleType, value: float | None) -> Any:  # noqa: ARG001
    """A synthetic `MetricResult`, so `verdict()` is tested without running a driver.

    `runner` is unused by the body and is not decoration: taking it makes the fixture run first,
    and loading `tools/ow_eval.py` is what puts `packages/*/src` on `sys.path`. Without it the
    import below resolves only when some other test happened to load the runner already, which is
    a test that passes depending on collection order.
    """
    from omniweave_conform.evaluate import MetricResult  # noqa: PLC0415 - after sys.path is set

    return MetricResult(
        metric="span_exact_rate",
        state="vacuous" if value is None else "measured",
        value=value,
        numerator=0,
        denominator=0 if value is None else 10,
        sampled=0 if value is None else 10,
        blocks_seen=10,
        failures=(),
    )


def row(runner: ModuleType, kind: str = "hard", budget: float = 1.0) -> Any:
    return runner.GateRow(
        metric="span_exact_rate",
        kind=kind,
        budget=budget,
        guard=None,
        row_class="blocking",
        owner="quality",
        review_by="2026-12-10",
        sample_n=1000,
    )


@pytest.mark.parametrize(("value", "ok"), [(1.0, True), (0.9999, False), (0.0, False)])
def test_a_hard_row_is_equality_and_not_a_floor(runner: ModuleType, value: float, ok: bool) -> None:
    """ "a hard gate at 1.000, never a metric" (13-quality.md:36). 0.9999 is red."""
    assert runner.verdict(row(runner), result(runner, value))[0] is ok


def test_a_vacuous_measurement_does_not_fail(runner: ModuleType) -> None:
    """It has nothing to fail with. The denominator is a claim count and nobody claimed."""
    ok, why = runner.verdict(row(runner), result(runner, None))
    assert ok
    assert "vacuous" in why


@pytest.mark.parametrize(
    ("kind", "budget", "value", "ok"),
    [
        ("floor", 0.9, 0.95, True),
        ("floor", 0.9, 0.8, False),
        ("ceiling", 0.02, 0.01, True),
        ("ceiling", 0.02, 0.05, False),
    ],
)
def test_floor_and_ceiling_rows_compare_in_their_own_directions(
    runner: ModuleType, kind: str, budget: float, value: float, ok: bool
) -> None:
    """No row uses these at P3 and both are implemented, because section 8.3's table is mostly
    floors and ceilings and a runner that only knew `hard` would fail on the first one added."""
    assert runner.verdict(row(runner, kind, budget), result(runner, value))[0] is ok


# ---------------------------------------------------------------------------
# end to end
# ---------------------------------------------------------------------------


def test_q_g6_passes_on_this_repository(runner: ModuleType, capsys: Any) -> None:
    """THE EXIT LINE. Runs both shipped drivers over their own fixtures and re-verifies every
    block that claims verbatimness."""
    assert runner.main(["golden", "--check", "span_exact_rate"]) == 0
    out = capsys.readouterr().out
    assert "pdf/born_digital" in out
    assert "1.0000" in out


def test_the_office_slice_reports_vacuous_rather_than_a_green_one(
    runner: ModuleType, capsys: Any
) -> None:
    """R-T16's whole mitigation. A vacuous slice that printed 1.0000 would be the framework's
    hardest fidelity gate reporting success on a corpus where nothing was under it."""
    runner.main(["golden", "--check", "span_exact_rate"])
    out = capsys.readouterr().out
    office = next(line for line in out.splitlines() if "office " in line)
    assert "vacuous" in office
    assert "1.0000" not in office


def test_refusals_are_counted_and_named(runner: ModuleType, capsys: Any) -> None:
    """A fixture set contains its abuse cases on purpose. Swallowing refusals would let this metric
    report a clean 1.0000 for a driver that refused everything it was shown."""
    runner.main(["golden", "--check", "span_exact_rate"])
    out = capsys.readouterr().out
    assert "refused" in out
    assert "no_text_layer.pdf (needs_ocr)" in out


def test_the_corpus_bookkeeping_is_not_fed_to_a_driver(runner: ModuleType, capsys: Any) -> None:
    """`EXPECTED.sha256` and `README.md` sit beside the fixtures and are not documents. Before
    `harness.NOT_INPUTS` existed the kit parsed them and recorded the refusal, which is noise in a
    count a reader is supposed to be able to scan for a real one."""
    runner.main(["golden", "--check", "span_exact_rate"])
    out = capsys.readouterr().out
    assert "EXPECTED.sha256" not in out
    assert "README.md" not in out


# ---------------------------------------------------------------------------
# usage
# ---------------------------------------------------------------------------


def test_an_unknown_metric_is_exit_two_and_lists_what_is_known(
    runner: ModuleType, capsys: Any
) -> None:
    assert runner.main(["golden", "--check", "no_such_metric"]) == 2
    out = capsys.readouterr().out
    assert "span_exact_rate" in out


def test_a_row_with_no_implementation_is_an_error_and_not_a_skip(
    runner: ModuleType, tmp_path: Path, capsys: Any
) -> None:
    """A register row nobody computes is a claim that something is under a gate when it is not."""
    register = tmp_path / "gates.toml"
    register.write_text(
        '[[gate]]\nmetric = "structure_f1"\nkind = "floor"\nbudget = 0.9\n'
        'class = "blocking"\nowner = "quality"\nreview_by = "2026-12-10"\ncomputed = "F1."\n',
        encoding="utf-8",
    )
    code = runner.main(["golden", "--check", "structure_f1", "--register", str(register)])
    assert code == 2
    assert "no implementation" in capsys.readouterr().out


def test_a_missing_register_is_exit_two(runner: ModuleType, tmp_path: Path) -> None:
    assert (
        runner.main(
            ["golden", "--check", "span_exact_rate", "--register", str(tmp_path / "nope.toml")]
        )
        == 2
    )
