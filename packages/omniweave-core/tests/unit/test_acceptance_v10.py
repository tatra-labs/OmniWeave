"""`tools/acceptance_v10.py`: v1.0's seventeen, rolled up. D835.

The verdict logic is `tools/acceptance_v01.py`'s, and `test_acceptance_v01.py` holds it. This
file holds the table to the plan: seventeen rows in order, every named file in the tree, a
coverage judgement that agrees with its instruments, and an exit of 1 until every row passes. It
also checks the machinery really is the v0.1 script's and not a copy.

Loaded by file path under the name it is run by, as `test_acceptance_v01.py` loads its tool.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from conftest import PlanDocs

REPO_ROOT = Path(__file__).resolve().parents[4]
TOOL = REPO_ROOT / "tools" / "acceptance_v10.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("acceptance_v10", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


a = _load()


def test_v10_11s_gap_text_describes_the_release_workflow_this_tree_has() -> None:
    """D1019. V10-11's gap used to call the `release` environment the remaining blocker, which
    D1016 discharged in the same cell as this test.

    A gap text is prose and no instrument reads it, which is exactly how V10-16's and V10-3's went
    stale and had to be re-measured (D1007, D1009). So this one is held against the workflow it
    describes: the condition is asserted as the literal both files carry, and if the publish half
    is ever ungated this test is what says the row is lying.
    """
    gate = "vars.OMNIWEAVE_RELEASE_PUBLISH == 'true'"
    row = next(one for one in a.CRITERIA if one.id == "V10-11")
    workflow = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    #  Over the LINES that are the key, not a substring search: the file's own header quotes the
    #  condition in prose, so `f"if: {gate}" in workflow` passes on a workflow where both real
    #  `if:` keys have been deleted -- which is what the mutation proved before this was fixed.
    gated = [one for one in workflow.splitlines() if one.strip() == f"if: {gate}"]
    assert len(gated) == 2, (
        f"release.yml gates {len(gated)} job(s) on the publish variable, not the two D1016 names"
    )
    assert gate in row.gap, "V10-11's gap text does not name the condition release.yml carries"
    assert "NOT NEEDED at v1.0" in row.gap, "the consequence a reader needs is the environment's"
    #  And the claim that makes it true: an environment gates only the jobs declaring one. Counted
    #  over lines that ARE the key, not occurrences of the words -- the header and the job's own
    #  name mention it too, which is how this first read 4.
    declaring = [one for one in workflow.splitlines() if one.strip() == "environment: release"]
    assert len(declaring) == 1, (
        "a second environment-gated job would make the skipped-publish argument incomplete"
    )


def test_only_v10_7_declares_a_reported_exit_and_only_for_the_breach() -> None:
    """D1008, implementing D924: *"A breached G22 bound is reported beside the runner and does not
    fail; a run that did not happen does."* `tools/gate_scale.py` exits 1 on a breach and 2 when
    it did not run, so exactly 1 is reported -- the line `ci.yml`'s nightly step already carries.

    Nothing else in the table may declare one. A non-zero exit reading as anything but FAIL is
    what would let a mistyped pytest node pass for green, so the exception stays one row wide.
    """
    declared = {
        (row.id, one.label): one.reported
        for row in a.CRITERIA
        for one in row.instruments
        if one.reported
    }
    assert declared == {("V10-7", "tools/gate_scale.py"): frozenset({1})}


def test_the_table_is_the_plans_seventeen_in_order() -> None:
    """16:985 and 00-vision.md section 9.2: V10-1 .. V10-17, nothing added, nothing dropped."""
    assert [row.id for row in a.CRITERIA] == [f"V10-{n}" for n in range(1, 18)]


def test_the_plan_prints_exactly_these_seventeen(plan: PlanDocs) -> None:
    """00-vision.md section 9.2's rows, read from the plan, are the table's ids."""
    plan.require()
    text = plan.text("00-vision.md")
    rows = [line for line in text.splitlines() if line.startswith("| V10-")]
    assert [line.split("|")[1].strip() for line in rows] == [row.id for row in a.CRITERIA]


def test_every_file_an_instrument_names_exists() -> None:
    """A pytest node names a file, and a tool names a script: each must be in the tree."""
    for row in a.CRITERIA:
        for instrument in row.instruments:
            named = [
                one.split("::", 1)[0]
                for one in instrument.argv
                if one.endswith(".py") or ".py::" in one
            ]
            for rel in named:
                assert (REPO_ROOT / rel).is_file(), f"{row.id}: {rel}"


def test_every_test_node_an_instrument_names_is_defined_in_its_file() -> None:
    """A misspelled `file::test` collects nothing and fails its row at acceptance time; it is
    cheaper to fail here. Each node's name must be a top-level `def` in that file."""
    for row in a.CRITERIA:
        for instrument in row.instruments:
            for one in instrument.argv:
                if ".py::" not in one:
                    continue
                rel, name = one.split("::", 1)
                tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
                defined = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
                assert name in defined, f"{row.id}: {one}"


def test_the_machinery_is_acceptance_v01s() -> None:
    """One definition of PASS: the types and `judge` are v0.1's, loaded, not copied."""
    v01 = a.V01
    assert a.Criterion is v01.Criterion
    assert a.Coverage is v01.Coverage
    assert a.Verdict is v01.Verdict
    assert a.judge is v01.judge
    assert a.evaluate is v01.evaluate
    assert a.module is v01.module


def test_v10_1_runs_g25_as_the_ci_step_runs_it() -> None:
    """D960: G25 is a CI step, `ow surface emit --check`, and not a `tools/` script, so V10-1
    runs the step. The `gates` job's G25 step (`.github/workflows/ci.yml`) is the same command."""
    (v10_1,) = (row for row in a.CRITERIA if row.id == "V10-1")
    argvs = [one.argv for one in v10_1.instruments]
    assert ("-m", "omniweave", "surface", "emit", "--check") in argvs
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "then uv run ow surface emit --check" in workflow
    assert "G13 has no runner" in v10_1.gap
    assert not any(f"G25 {verb} no runner" in v10_1.gap for verb in ("has", "have"))


def test_the_rows_the_2026_10_23_rulings_settled() -> None:
    """D964: V10-8 claims content identity over the full 300/40, and V10-13 the reconciliation,
    with free passes out of scope; V10-4 and V10-6 keep their other gaps and cite the ruling."""
    rows = {row.id: row for row in a.CRITERIA}
    assert rows["V10-8"].coverage is a.Coverage.FULL
    assert ("tools/gate_incremental.py",) in [one.argv for one in rows["V10-8"].instruments]
    assert rows["V10-13"].coverage is a.Coverage.FULL
    #  D967: the independent SubRip driver is V10-12's evidence, selected by its pytest -k.
    assert rows["V10-12"].coverage is a.Coverage.FULL
    #  D971: G35 is law, and hallucination_rate is not applicable at v1.0.
    assert rows["V10-15"].coverage is a.Coverage.FULL
    assert "hallucination_rate is not applicable at v1.0" in rows["V10-4"].gap
    assert "Q-G20" in rows["V10-1"].gap and "deferred past v1.0" in rows["V10-1"].gap
    #  D968: V10-10, its reader cards now through the kit.
    assert rows["V10-10"].coverage is a.Coverage.FULL
    assert any("reader_passes" in one.argv for one in rows["V10-10"].instruments)
    (selector,) = [one.argv for one in rows["V10-12"].instruments if "-k" in one.argv]
    assert "mandatory_tier" in selector[selector.index("-k") + 1]
    tests = Path(__file__).with_name("test_ow_conform.py").read_text(encoding="utf-8")
    assert "def test_an_independent_driver_for_another_format_passes_the_mandatory_tier(" in tests
    for row in ("V10-4", "V10-6"):
        assert rows[row].coverage is a.Coverage.PARTIAL
        assert "a user ruling of 2026-10-23" in rows[row].gap


def test_no_row_claims_full_coverage_it_does_not_have() -> None:
    """A FULL row has no gap and at least one instrument; every other row names its gap."""
    for row in a.CRITERIA:
        if row.coverage is a.Coverage.FULL:
            assert row.instruments and not row.gap, row.id
        else:
            assert row.gap, row.id


def test_every_row_names_at_least_one_instrument() -> None:
    """D980 took the last empty one. V10-3 carried `()` until `tools/label_review.py` landed, and
    a row with no instrument is a row whose verdict is a declaration and nothing else. A new row
    arriving without one should turn this red rather than report UNMEASURED quietly."""
    assert [row.id for row in a.CRITERIA if not row.instruments] == []


def test_anything_short_of_every_row_passing_exits_one(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The P10 exit criterion is meant to fail until v1.0 is accepted. V10-7 is the cheap way to
    see it: its instruments are all slow, so none runs here and the row reports UNMEASURED."""
    assert a.main(["--only", "V10-7"]) == 1
    out = capsys.readouterr().out
    assert "UNMEASURED V10-7" in out
    assert out.splitlines()[-1].startswith("V10: PASS 0  PARTIAL 0  FAIL 0  UNMEASURED 1  of 1")


def test_a_slow_row_is_unmeasured_without_slow(capsys: pytest.CaptureFixture[str]) -> None:
    """V10-7's 100k-roster run takes minutes, so it is not run, and the row says how to run it."""
    assert a.main(["--only", "V10-7"]) == 1
    out = capsys.readouterr().out
    assert "UNMEASURED V10-7" in out
    assert "gap: slow: pass --slow." in out
    assert "exit " not in out


def test_json_prints_every_result(capsys: pytest.CaptureFixture[str]) -> None:
    """A row whose instruments were all skipped prints an empty `ran`, not a missing key."""
    assert a.main(["--json", "--only", "V10-7"]) == 1
    rows = json.loads(capsys.readouterr().out)
    assert [(row["id"], row["verdict"], row["ran"]) for row in rows] == [
        ("V10-7", "UNMEASURED", []),
    ]


def test_an_unknown_id_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as stop:
        a.main(["--only", "V10-99"])
    assert stop.value.code == 2
