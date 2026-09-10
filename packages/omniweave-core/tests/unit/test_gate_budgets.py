"""Q-G15 tested as a program: the register is the plan's, and the linter goes red on cue.

`tools/gate_budgets.py` is the only reader of `eval/perf.toml`, and between them they carry the
whole of what CI is willing to fail a build over on performance grounds. Two halves, and the second
is the one that earns the file:

* **the register is the plan's.** Every `id`, `value`, tolerance, `gate` and `process` below is a
  literal transcribed from the plan document that fixes it -- charter:7573-7630 for the ten charter
  rows, 12-performance.md:195-198 for the two the performance document adds, 13-quality.md:1916-1941
  for the three the quality document adds. The expected values are written out here rather than read
  from `eval/perf.toml`, because a test that reads its expectation out of the thing under test pins
  agreement and not value, and would pass just as happily on a register somebody edited by hand.
* **the linter goes red when it is shown a bad row.** A gate nobody has seen fail is a gate nobody
  has tested. Each defect the schema names -- an unknown key, both tolerances, neither, a `process`
  on a row that is not `rss.`, an `rss.` row with none, a duplicate id, a gate outside the
  vocabulary, a worst case over the tier ceiling -- is fed to `main()` as a real file and asserted
  to exit non-zero with the row named in the report.

The third thing this file asserts is that the gate is **not** a measurement runner. Its module
docstring makes that promise in as many words because `ow eval perf` sits next to it in the plan and
does measure; `test_the_gate_imports_nothing_that_could_measure_anything` is the promise as an
assertion over the import graph rather than as prose.

The gate is loaded by file path with `importlib.util`, never by `importlib.import_module` and never
by putting `tools/` on `sys.path` -- the discipline `test_gates_structural.py` states.

Specified in 12-performance.md section 2.4 (the row schema and the shipped rows),
12-performance.md:190-198, 13-quality.md section 2.9 (Q-G15's two clauses) and
13-quality.md section 13.5.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from fractions import Fraction
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import pytest


def _load(repo_root: Path) -> ModuleType:
    """Load `tools/gate_budgets.py` under a private name. See `test_gates_structural._load`."""
    path = repo_root / "tools" / "gate_budgets.py"
    spec = importlib.util.spec_from_file_location("_owgate_gate_budgets", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gate(repo_root: Path) -> ModuleType:
    return _load(repo_root)


@pytest.fixture(scope="module")
def register(gate: ModuleType, repo_root: Path) -> dict[str, Any]:
    """`eval/perf.toml`, parsed. That it parses at all is the first assertion of this file."""
    return dict(gate.load(repo_root / "eval" / "perf.toml"))


@pytest.fixture(scope="module")
def rows(register: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["id"]: row for row in register["budget"]}


# ---------------------------------------------------------------------------
# The register is the plan's
# ---------------------------------------------------------------------------

# (id, value, tol_pct, tol_abs, gate) exactly as the plan spells each row. `None` means the key is
# absent, which for the two tolerance columns is the whole point: a row carries one of them.
#
#   charter:7573-7630            the ten charter rows
#   12-performance.md:195-198    cold.ow_help_ms and discovery.20dists_ms, "Extends the charter"
#   13-quality.md:1916-1941      t0.gates_job_s, test.cell_ubuntu_311_s, golden.job_s
EXPECTED: tuple[tuple[str, int, int | None, int | None, str], ...] = (
    ("import.omniweave_core_ms", 62, 25, None, "pr"),
    ("cold.ow_version_ms", 118, 25, None, "pr"),
    ("cold.ow_help_ms", 190, 25, None, "pr"),
    ("discovery.20dists_ms", 16, 20, None, "pr"),
    ("conform.mandatory_tier_s", 240, None, 60, "pr"),
    ("contributor_parity_s", 420, None, 180, "pr"),
    ("parse.office.p50_ms", 5, 20, None, "nightly"),
    ("query.warm_p50_ms", 180, 20, None, "nightly"),
    ("store.bytes_per_block", 660, 10, None, "nightly"),
    ("rss.gen5000p_peak_bytes", 1_610_612_736, 10, None, "nightly"),
    ("rss.merged4mcell_peak_bytes", 4_294_967_296, 10, None, "nightly"),
    ("wal.bulk_index_peak_bytes", 2_147_483_648, None, 536_870_912, "nightly"),
    ("t0.gates_job_s", 128, None, 40, "pr"),
    ("test.cell_ubuntu_311_s", 185, None, 50, "pr"),
    ("golden.job_s", 190, None, 45, "pr"),
)


def test_the_register_holds_every_row_the_plan_states_and_no_other(
    register: dict[str, Any],
) -> None:
    """Fifteen ids, from three plan sites, and nothing invented.

    The count is the finding this file records rather than resolves: section 2.4's table renders
    twelve (12-performance.md:236-247), the charter's TOML holds ten (charter:7573-7630), and
    13-quality section 13.5 adds three more (13-quality.md:1916-1941). All fifteen are stated as
    `[[budget]]` rows of this file, so all fifteen are here. A sixteenth would be a row somebody
    invented, which is exactly what a register may not contain.

    The assertion is over the ARRAY and not over the `rows` mapping. Keying fifteen rows by `id`
    silently collapses a sixteenth row that duplicates one of them, so a register with a copied
    `[[budget]]` block reads as fifteen ids in the right order and this test -- the one whose name
    says "and no other" -- would pass on it.
    """
    assert [row["id"] for row in register["budget"]] == [row[0] for row in EXPECTED]


@pytest.mark.parametrize("expected", EXPECTED, ids=[row[0] for row in EXPECTED])
def test_each_row_carries_the_value_the_plan_fixes(
    rows: dict[str, dict[str, Any]],
    expected: tuple[str, int, int | None, int | None, str],
) -> None:
    """Transcription, checked figure by figure against a literal.

    A tolerance transcribed as the wrong kind is the subtle one: `wal.bulk_index_peak_bytes` at
    2 GiB +/-512 MiB absolute becomes, as a percentage, a bound that grows with the number it
    bounds -- and 12-performance.md:247 says why that is not a bound at all. So the two columns are
    asserted separately and an absent key is asserted absent.
    """
    budget_id, value, tol_pct, tol_abs, gate_class = expected
    row = rows[budget_id]
    assert row["value"] == value
    assert row.get("tol_pct") == tol_pct
    assert row.get("tol_abs") == tol_abs
    assert row["gate"] == gate_class


def test_process_is_on_the_two_rss_rows_and_nowhere_else(rows: dict[str, dict[str, Any]]) -> None:
    """12-performance.md:227: "Both shipped `rss.` rows declare `process = "worker"`".

    Added by ADR-11 D5 and recorded as charter section 9.2 `E88`; the charter's own TOML predates
    the key and shows neither row carrying it, which is the one place this register adds a key its
    transcription source does not show.
    """
    carrying = {row_id: row["process"] for row_id, row in rows.items() if "process" in row}
    assert carrying == {
        "rss.gen5000p_peak_bytes": "worker",
        "rss.merged4mcell_peak_bytes": "worker",
    }


def test_the_ratchet_key_is_on_the_one_row_two_plan_sites_put_it_on(
    rows: dict[str, dict[str, Any]],
) -> None:
    """charter:7622 and 12-performance.md:244's tolerance cell, "+/-10%, **ratchet**".

    The key is not in section 2.4's key table, which declares itself the schema's sole home and
    makes an unknown key a hard error. That contradiction is a finding; what this test pins is that
    the key appears on exactly the row the two sites that do state it put it on, so a later reader
    cannot find it spreading to rows nobody committed to a ratchet for.
    """
    ratcheted = sorted(row_id for row_id, row in rows.items() if row.get("ratchet"))
    assert ratcheted == ["store.bytes_per_block"]


def test_the_pacer_is_the_charters_and_names_the_one_pinned_machine(
    register: dict[str, Any],
) -> None:
    """charter:7567-7571, and 12-performance.md:1966 -- "the **only** machine a `Budget` may
    live on".

    12-performance.md:1966 also says "Every `eval/perf.toml` row ... names one", which no row can:
    the section 2.4 key table has no key for it and an unknown key is a hard error. The file names
    it once, here.
    """
    pacer = register["pacer"]
    assert pacer["runner"] == "ow-bench-1"
    assert pacer["instability_pct"] == 15
    assert pacer["work"] == "blake2b(64MiB) + a 2M int loop + 200k sqlite insert+select"
    assert pacer["rule"] == (
        "fail on 3 consecutive nightly runs above tolerance, comparing 7-run rolling medians"
    )


# ---------------------------------------------------------------------------
# The ceiling arithmetic, worked by hand and pinned
# ---------------------------------------------------------------------------

# (id, the worst case as an exact fraction, the ceiling, the unit the ceiling is stated in).
# Each worst case is the plan's own
# arithmetic: 12-performance.md:184-188 prints 77.5, 147.5 and 216 ms and 12-performance.md:195-198
# prints 237.5 and 19.2 ms; 13-quality.md:362-366 and :1924-1939 print 300, 600, 168, 235 and 235 s.
CEILING_ARITHMETIC: tuple[tuple[str, Fraction, int, str], ...] = (
    ("import.omniweave_core_ms", Fraction(155, 2), 80, "ms"),
    ("cold.ow_version_ms", Fraction(295, 2), 150, "ms"),
    ("cold.ow_help_ms", Fraction(475, 2), 250, "ms"),
    ("discovery.20dists_ms", Fraction(96, 5), 20, "ms"),
    ("query.warm_p50_ms", Fraction(216), 250, "ms"),
    ("conform.mandatory_tier_s", Fraction(300), 300, "s"),
    ("contributor_parity_s", Fraction(600), 600, "s"),
    ("t0.gates_job_s", Fraction(168), 180, "s"),
    ("test.cell_ubuntu_311_s", Fraction(235), 240, "s"),
    ("golden.job_s", Fraction(235), 240, "s"),
)


@pytest.mark.parametrize("tier", CEILING_ARITHMETIC, ids=[case[0] for case in CEILING_ARITHMETIC])
def test_the_worst_case_of_each_tiered_row_is_the_number_the_plan_printed(
    gate: ModuleType,
    rows: dict[str, dict[str, Any]],
    tier: tuple[str, Fraction, int, str],
) -> None:
    """`value + tolerance` is what the plan says it is, and it is inside the ceiling.

    Two rows land exactly on their ceiling -- `conform.mandatory_tier_s` at 300 s and
    `contributor_parity_s` at 600 s -- which is why 13-quality.md:365-366 makes the comparison
    non-strict: "tightening it to `<` would fail the charter rather than a mistake".

    The `unit` is asserted because the gate PRINTS it in the one sentence a breach produces --
    "exceeds the 240 ms ceiling" on a job budgeted in seconds sends a reader to look for a defect
    three orders of magnitude away from the one they have. Only `import.omniweave_core_ms` was
    pinned before, and then only as a side effect of a substring in `BAD_REGISTERS`.
    """
    budget_id, worst, ceiling, unit = tier
    assert gate.worst_case(rows[budget_id]) == worst
    assert gate.CEILINGS[budget_id].limit == ceiling
    assert gate.CEILINGS[budget_id].unit == unit
    assert worst <= ceiling


def test_the_arithmetic_is_exact_where_binary_floating_point_is_not(
    gate: ModuleType, rows: dict[str, dict[str, Any]]
) -> None:
    """Two shipped rows whose worst case a `float` gets wrong, and the gate gets right.

    `660 * (1 + 10 / 100)` is `726.0000000000001` in binary floating point -- the
    `store.bytes_per_block` row, the one P2 exists to measure. A ceiling set at its worst case
    would reject it for the base rather than for a defect. And `16 * 1.2` PRINTS as `19.2` while
    being a different number from the decimal 19.2, so a comparison that happened to be exact
    today would stop being exact under a value nobody thought they had changed.
    """
    assert 660 * (1 + 10 / 100) > 726  # the artefact, asserted rather than described
    assert gate.worst_case(rows["store.bytes_per_block"]) == Fraction(726)
    assert Fraction(16 * 1.2) != Fraction(96, 5)
    assert gate.worst_case(rows["discovery.20dists_ms"]) == Fraction(96, 5)


def test_a_row_with_no_stated_tier_is_named_rather_than_silently_passed(
    gate: ModuleType, rows: dict[str, dict[str, Any]], capsys: pytest.CaptureFixture[str]
) -> None:
    """13-quality.md:357-358 scopes clause 3 to "every row carrying a tier"; five rows carry none.

    Inventing a ceiling for `store.bytes_per_block` or either `rss.` row would be this gate making
    up a number, so the clause is silent on them -- and silence that is not printed is
    indistinguishable from a check that ran.
    """
    untiered = {row_id for row_id in rows if row_id not in gate.CEILINGS}
    assert untiered == {
        "parse.office.p50_ms",
        "store.bytes_per_block",
        "rss.gen5000p_peak_bytes",
        "rss.merged4mcell_peak_bytes",
        "wal.bulk_index_peak_bytes",
    }
    gate.main([])
    out = capsys.readouterr().out
    for row_id in untiered:
        assert row_id in out


# ---------------------------------------------------------------------------
# The gate on HEAD
# ---------------------------------------------------------------------------


def test_the_gate_is_green_on_the_shipped_register(
    gate: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    code = gate.main([])
    out = capsys.readouterr().out
    assert code == gate.EXIT_CLEAN, out
    assert "Q-G15 ok" in out
    assert "15 [[budget]] row(s), 15 distinct id(s)" in out
    assert out.isascii(), "the report must survive a cp1252 console"


def test_the_gate_imports_nothing_that_could_measure_anything(repo_root: Path) -> None:
    """The docstring's promise, as an assertion over the import graph.

    `ow eval perf` (W10.6, P10) measures: it runs the Pacer, opens a store and times things. This
    script lints one TOML file. The two names sit next to each other in 12-performance.md section
    2.4 and the day someone "adds a quick measurement" to the linter is the day a register defect
    and a performance regression start sharing an exit code. `time`, `sqlite3`, `subprocess`,
    `resource` and anything first-party are therefore absent, and absent by test.
    """
    source = (repo_root / "tools" / "gate_budgets.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    assert roots == {
        "__future__",
        "argparse",
        "collections",
        "dataclasses",
        "fractions",
        "pathlib",
        "re",
        "sys",
        "tomllib",
        "typing",
    }


# ---------------------------------------------------------------------------
# Non-vacuity: every defect the schema names, shown to the gate
# ---------------------------------------------------------------------------

GOOD_PACER: dict[str, Any] = {
    "work": "blake2b(64MiB) + a 2M int loop + 200k sqlite insert+select",
    "instability_pct": 15,
    "rule": "fail on 3 consecutive nightly runs above tolerance, comparing 7-run rolling medians",
    "runner": "ow-bench-1",
}

GOOD_TIMING: dict[str, Any] = {
    "id": "import.omniweave_core_ms",
    "value": 62,
    "tol_pct": 25,
    "gate": "pr",
}

GOOD_RSS: dict[str, Any] = {
    "id": "rss.gen5000p_peak_bytes",
    "value": 1_610_612_736,
    "tol_pct": 10,
    "gate": "nightly",
    "process": "worker",
}


def _scalar(value: object) -> str:
    """The TOML spelling of one value. Booleans before ints -- `bool` is an `int` in Python."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return repr(value)


def _render(rows: list[dict[str, Any]], *, pacer: dict[str, Any] | None = GOOD_PACER) -> str:
    """A whole register as text, so the gate is shown a real file and not a dict it trusts."""
    parts: list[str] = []
    if pacer is not None:
        parts.append("[pacer]")
        parts.extend(f"{key} = {_scalar(value)}" for key, value in pacer.items())
        parts.append("")
    for row in rows:
        parts.append("[[budget]]")
        parts.extend(f"{key} = {_scalar(value)}" for key, value in row.items())
        parts.append("")
    return "\n".join(parts)


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "perf.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_the_synthetic_baseline_is_clean_so_a_red_below_means_the_mutation(
    gate: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Every case below mutates this register. If the baseline were dirty they would all pass."""
    code = gate.main(["--perf", str(_write(tmp_path, _render([GOOD_TIMING, GOOD_RSS])))])
    assert code == gate.EXIT_CLEAN, capsys.readouterr().out


def _mutate(base: dict[str, Any], **changes: Any) -> dict[str, Any]:
    """A copy of a good row with keys added, replaced, or -- with `None` -- removed."""
    row = dict(base)
    for key, value in changes.items():
        if value is None:
            row.pop(key, None)
        else:
            row[key] = value
    return row


BAD_REGISTERS: tuple[tuple[str, list[dict[str, Any]], str], ...] = (
    # An unknown key. 12-performance.md:214 -- a hard error at load, no exceptions.
    ("unknown key", [_mutate(GOOD_TIMING, tolerance_pct=25)], "tolerance_pct"),
    # Both tolerances. 12-performance.md:214 -- mutually exclusive.
    ("both tolerances", [_mutate(GOOD_TIMING, tol_abs=5)], "tolerance keys"),
    # Neither tolerance. Same line -- exactly one is required.
    ("no tolerance", [_mutate(GOOD_TIMING, tol_pct=None)], "tolerance keys"),
    # `process` on a row that is not `rss.`. 12-performance.md:224 -- rejected on any other row.
    ("process off an rss row", [_mutate(GOOD_TIMING, process="worker")], "does not start"),
    # An `rss.` row with no `process`. 13-quality.md:368-374, the OOM at hour six.
    ("rss row with no process", [_mutate(GOOD_RSS, process=None)], "no `process`"),
    # `process` outside the closed vocabulary.
    ("process out of vocabulary", [_mutate(GOOD_RSS, process="supervisor_pool")], "vocabulary"),
    # A duplicate id. 12-performance.md:219 -- unique across the file. The second wins in every
    # dict a reader builds, and the first is a budget that is never checked.
    ("duplicate id", [GOOD_TIMING, dict(GOOD_TIMING)], "duplicate id"),
    # A gate outside {pr, nightly}. There is no third CI job to fail.
    ("gate out of vocabulary", [_mutate(GOOD_TIMING, gate="weekly")], "'weekly'"),
    # An id outside `[a-z0-9_.]{1,64}`.
    ("id out of grammar", [_mutate(GOOD_TIMING, id="Import.Core-MS")], "not `[a-z0-9_."),
    ("id too long", [_mutate(GOOD_TIMING, id="a" * 65)], "not `[a-z0-9_."),
    # `value = true` satisfies `isinstance(v, int)` in Python and would budget one millisecond.
    ("boolean value", [_mutate(GOOD_TIMING, value=True)], "not `int | float`"),
    ("boolean tolerance", [_mutate(GOOD_TIMING, tol_pct=True)], "not an `int`"),
    ("tol_pct over 100", [_mutate(GOOD_TIMING, tol_pct=150)], "outside 0-100"),
    ("tol_pct negative", [_mutate(GOOD_TIMING, tol_pct=-5)], "outside 0-100"),
    ("tol_pct not an int", [_mutate(GOOD_TIMING, tol_pct=12.5)], "not an `int`"),
    ("tol_abs not a number", [_mutate(GOOD_TIMING, tol_pct=None, tol_abs="60s")], "tol_abs"),
    ("ratchet not a boolean", [_mutate(GOOD_TIMING, ratchet="yes")], "not a boolean"),
    ("note not a string", [_mutate(GOOD_TIMING, note=7)], "not a string"),
    ("missing id", [_mutate(GOOD_TIMING, id=None)], "missing required key 'id'"),
    ("missing value", [_mutate(GOOD_TIMING, value=None)], "missing required key 'value'"),
    ("missing gate", [_mutate(GOOD_TIMING, gate=None)], "missing required key 'gate'"),
    # The ceiling clause. 62 +25% is 77.5 ms against V01-3's 80; 70 +25% is 87.5 and is over it.
    ("worst case over the tier ceiling", [_mutate(GOOD_TIMING, value=70)], "exceeds the 80 ms"),
    # The same clause on an absolute tolerance: 240 + 60 = 300 is the ceiling exactly, 240 + 61
    # is over it. This is the pair that fixes the non-strict comparison as non-strict.
    (
        "absolute tolerance one over the ceiling",
        [{"id": "conform.mandatory_tier_s", "value": 240, "tol_abs": 61, "gate": "pr"}],
        "exceeds the 300 s",
    ),
)


@pytest.mark.parametrize("bad", BAD_REGISTERS, ids=[case[0] for case in BAD_REGISTERS])
def test_the_gate_goes_red_on_a_bad_row(
    gate: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    bad: tuple[str, list[dict[str, Any]], str],
) -> None:
    """Each defect the schema names, fed to `main()` as a real file on disk.

    The assertion is not only the exit code. A gate that fails without naming the row and the key
    sends a reader to a fifteen-row register with a boolean, so the expected fragment is asserted
    in the report too.
    """
    case, bad_rows, expected = bad
    code = gate.main(["--perf", str(_write(tmp_path, _render(bad_rows)))])
    out = capsys.readouterr().out
    assert code == gate.EXIT_FAIL, f"{case}: expected a failure, got:\n{out}"
    assert expected in out, f"{case}: the report does not name the defect:\n{out}"
    assert "Q-G15 FAIL" in out


def test_a_register_with_no_rows_fails_rather_than_passing_vacuously(
    gate: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An empty register is the failure a green linter looks exactly like."""
    code = gate.main(["--perf", str(_write(tmp_path, _render([])))])
    out = capsys.readouterr().out
    assert code == gate.EXIT_FAIL
    assert "no `[[budget]]` rows at all" in out


def test_a_register_with_no_pacer_fails_because_time_is_a_ratio(
    gate: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """charter:7567-7571. Without the Pacer block a timing row is a number on an unnamed host."""
    code = gate.main(["--perf", str(_write(tmp_path, _render([GOOD_TIMING], pacer=None)))])
    out = capsys.readouterr().out
    assert code == gate.EXIT_FAIL
    assert "no `[pacer]` table" in out


def test_a_pacer_that_names_no_runner_fails(
    gate: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """12-performance.md:1966 -- `ow-bench-1` is the only machine a Budget may live on, and
    `[pacer] runner` is the only key in the file that can say so."""
    pacer = {key: value for key, value in GOOD_PACER.items() if key != "runner"}
    code = gate.main(["--perf", str(_write(tmp_path, _render([GOOD_TIMING], pacer=pacer)))])
    out = capsys.readouterr().out
    assert code == gate.EXIT_FAIL
    assert "missing key 'runner'" in out


def test_an_unknown_top_level_table_fails(
    gate: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`eval/counters.toml`'s rows are a different register (12-performance.md:249-256), and a
    `[[counter]]` block pasted in here would be a set of gates nothing runs."""
    text = _render([GOOD_TIMING]) + '\n[[counter]]\nid = "cache_misses"\nclass = "exact"\n'
    code = gate.main(["--perf", str(_write(tmp_path, text))])
    out = capsys.readouterr().out
    assert code == gate.EXIT_FAIL
    assert "unknown top-level key 'counter'" in out


# ---------------------------------------------------------------------------
# Exit code 2: the gate did not run
# ---------------------------------------------------------------------------


def test_a_missing_register_is_did_not_run_and_not_clean(
    gate: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The distinction 1 and 2 exist for: "row 7 is wrong" is a claim about a row that was read."""
    code = gate.main(["--perf", str(tmp_path / "absent.toml")])
    out = capsys.readouterr().out
    assert code == gate.EXIT_NOT_RUN
    assert "DID NOT RUN" in out


def test_a_register_that_is_not_toml_is_did_not_run(
    gate: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = gate.main(["--perf", str(_write(tmp_path, "[[budget]\nid = \n"))])
    out = capsys.readouterr().out
    assert code == gate.EXIT_NOT_RUN
    assert "not parseable TOML" in out


def test_an_unknown_argument_is_did_not_run_rather_than_ignored(gate: ModuleType) -> None:
    """A gate that ignores an argument it does not understand runs the wrong check silently."""
    assert gate.main(["--measure"]) == gate.EXIT_NOT_RUN


def test_the_three_exit_codes_are_the_documented_ones(gate: ModuleType) -> None:
    """0 clean, 1 a budget row is bad, 2 the gate did not run."""
    assert (gate.EXIT_CLEAN, gate.EXIT_FAIL, gate.EXIT_NOT_RUN) == (0, 1, 2)


# ---------------------------------------------------------------------------
# The shapes a register can take that are not a row at all
#
# Every case below was found by mutation: the gate was broken on purpose and the suite above
# stayed green, which means a real defect of that shape would have shipped. `_render` cannot
# produce any of them -- it always writes well-formed `[[budget]]` blocks -- so each one is
# spelled as TOML by hand.
# ---------------------------------------------------------------------------

PACER_TEXT: Final = "\n".join(
    ["[pacer]", *(f"{key} = {_scalar(value)}" for key, value in GOOD_PACER.items()), ""]
)


def test_a_budget_array_that_is_empty_is_not_a_clean_run(
    gate: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`budget = []` is the vacuous green that `_render([])` does not reach.

    The two spellings of "this register has no rows" are not the same text. Omitting every
    `[[budget]]` block leaves the key absent, which the gate caught; writing the key as an empty
    array leaves it present, and a presence check reports a clean register on a file that gates
    nothing. That is exactly the failure 12-performance.md:207 and this gate's own fourth clause
    exist to prevent -- "a linter whose subject silently disappeared reports the same green as a
    linter that checked fifteen rows" -- and it survived until it was tried.
    """
    code = gate.main(["--perf", str(_write(tmp_path, "budget = []\n\n" + PACER_TEXT))])
    out = capsys.readouterr().out
    assert code == gate.EXIT_FAIL, out
    assert "no `[[budget]]` rows at all" in out


def test_a_budget_key_that_is_not_an_array_is_reported_and_not_a_traceback(
    gate: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`budget = 5` used to raise `TypeError` out of the report writer.

    A gate that tracebacks has told CI nothing it can act on: no finding, no `DID NOT RUN` line
    and no exit code of the gate's own choosing, and a caller that imports `main()` rather than
    running the script gets an exception where it asked for an integer. The three exit codes are
    the whole of the output contract, so a register whose `budget` key is a scalar has to land on
    one of them.
    """
    code = gate.main(["--perf", str(_write(tmp_path, "budget = 5\n\n" + PACER_TEXT))])
    out = capsys.readouterr().out
    assert code == gate.EXIT_FAIL, out
    assert "not an array of tables" in out


def test_a_row_that_is_not_a_table_is_named_rather_than_skipped(
    gate: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`budget = [1, 2]`: two entries, no `id` between them, and nothing to lint.

    `check()` filters the array down to the entries that are tables before it lints them, and the
    entries it drops are reported by a separate clause. Deleting that clause left every test above
    green -- the filter alone is silent, and silence on a register of two garbage rows is the same
    output as a register of two good ones.
    """
    code = gate.main(["--perf", str(_write(tmp_path, "budget = [1, 2]\n\n" + PACER_TEXT))])
    out = capsys.readouterr().out
    assert code == gate.EXIT_FAIL, out
    assert out.count("not a table") == 2, out
    assert "Q-G15 FAIL  2 finding(s)" in out


def test_an_id_with_a_trailing_newline_is_not_the_id_it_renders_as(
    gate: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`$` in Python's `re` also matches before a trailing newline. `\\Z` does not.

    `id = "import.omniweave_core_ms\\n"` passed `^[a-z0-9_.]{1,64}$`, so the gate accepted it,
    counted it as one distinct id and exited clean. The row it describes is unreachable: it is not
    equal to `import.omniweave_core_ms`, so `_check_uniqueness` scores it as a different budget,
    and every consumer that resolves a `budget_id` -- a scoreboard row, a risk indicator
    (17-risks.md:56), a bless entry -- misses it. The register would carry a budget nothing gates,
    and the gate would say so in no way at all.

    The second assertion is about the report rather than the verdict. The id is data out of the
    file under test, so interpolating it raw puts its newline inside the gate's own `FAIL` line and
    lets the defect choose how the defect is printed. It is quoted instead.
    """
    text = PACER_TEXT + '\n[[budget]]\nid = "import.omniweave_core_ms\\n"\nvalue = 62\n'
    text += 'tol_pct = 25\ngate = "pr"\n'
    code = gate.main(["--perf", str(_write(tmp_path, text))])
    out = capsys.readouterr().out
    assert code == gate.EXIT_FAIL, out
    assert "not `[a-z0-9_." in out
    assert "[[budget]] #1 ('import.omniweave_core_ms\\n')" in out, out


def test_every_defect_in_a_register_is_reported_and_not_only_the_first(
    gate: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A gate that stops at the first bad row is a gate somebody runs four times.

    Making `check()` return as soon as one row produced a finding left every case in
    `BAD_REGISTERS` green, because each of them carries exactly one defect. The cost is not only
    the round trips: `_check_uniqueness` runs after the per-row loop, so an early return means a
    register with any other defect in it never has its ids checked for uniqueness at all -- and a
    duplicate `id` is the defect whose whole nature is that the file still looks right.

    Three defects, in three clauses, one of them the file-wide one.
    """
    bad = [
        _mutate(GOOD_TIMING, tolerance_pct=25),
        _mutate(GOOD_RSS, process=None),
        dict(GOOD_TIMING),
    ]
    code = gate.main(["--perf", str(_write(tmp_path, _render(bad)))])
    out = capsys.readouterr().out
    assert code == gate.EXIT_FAIL, out
    assert "tolerance_pct" in out, out
    assert "no `process`" in out, out
    assert "duplicate id" in out, out
    assert "Q-G15 FAIL  3 finding(s)" in out, out


def test_the_ceiling_arithmetic_reads_a_decimal_and_not_the_float_it_is_stored_as(
    gate: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`Fraction(str(v))`, not `Fraction(v)` -- and the shipped rows cannot tell the difference.

    Every `value` and every `tol_abs` in `eval/perf.toml` today is an integer, and `Fraction(240)`
    and `Fraction("240")` are the same number, so dropping the `str()` from `_decimal` left the
    whole file above green -- including the test named for exactness, two of whose four assertions
    are about plain Python rather than about the gate. The schema admits a float (`value` is
    `int | float`, 12-performance.md:220, and the first note in the register quotes anydoc's 4.4 ms
    median), so the claim needs a row that a float gets wrong.

    `240.05 + 59.95` is exactly 300 as a decimal and lands exactly on `conform.mandatory_tier_s`'s
    300 s ceiling, which 13-quality.md:365-366 makes a PASS. Read as binary doubles the same two
    numbers sum to a hair over 300, and the gate would be failing a row for the base it was
    written in.
    """
    assert gate.worst_case({"value": 4.4, "tol_abs": 0.1}) == Fraction(45, 10)
    assert Fraction(4.4) + Fraction(0.1) != Fraction(45, 10)  # the artefact, asserted
    row = {"id": "conform.mandatory_tier_s", "value": 240.05, "tol_abs": 59.95, "gate": "pr"}
    assert gate.worst_case(row) == Fraction(300)
    code = gate.main(["--perf", str(_write(tmp_path, _render([row])))])
    out = capsys.readouterr().out
    assert code == gate.EXIT_CLEAN, out
