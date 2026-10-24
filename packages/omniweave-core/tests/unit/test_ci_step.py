"""`tools/ci_step.py`: CI steps' verdicts over a saved `gh run view --json jobs`. D974, D975.

The tool reads the verdicts through `gh`; these tests hand it a saved document instead, so they
need no network. Loaded by file path, as every `tools/` gate's test loads its tool.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[4]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ci_step", REPO / "tools" / "ci_step.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


tool = _load()

PDFIUM = "Q-G4 pdfium axis (nightly) -- the same shapes under the previous pdfium minor"
BUILD_STEPS = (
    "28 files, zero platform wheels",
    "G2 -- the fourteen weight ceilings and the 250 MB [recommended] union",
    "section 6.6 step 4 -- build.wheelhouse_profiles",
)


def _golden(conclusion: str | None, *, step: str = PDFIUM) -> dict[str, Any]:
    return {
        "name": "golden (Reductions + Counters + Cassette replay)",
        "conclusion": "success",
        "steps": [
            {"name": "Q-G4 -- shape byte-identical across the nine cells", "conclusion": "success"},
            {"name": step, "conclusion": conclusion},
        ],
    }


def _build(*conclusions: str) -> dict[str, Any]:
    return {
        "name": "build (G2, build.reproducible, build.first_party_manifest, ...)",
        "steps": [
            {"name": name, "conclusion": conclusion}
            for name, conclusion in zip(BUILD_STEPS, conclusions, strict=True)
        ],
    }


@pytest.mark.parametrize(
    ("conclusion", "code"),
    [("success", 0), ("failure", 1), ("skipped", 2), ("cancelled", 2), (None, 2)],
)
def test_the_verdict_is_the_pdfium_steps_own(conclusion: str | None, code: int) -> None:
    """A skipped or cancelled step, or one with no conclusion, did not run, and is never a pass."""
    assert tool.judge([_golden(conclusion)])[0] == code


def test_another_job_failing_does_not_move_the_verdict() -> None:
    gates = {"name": "gates (G1 ...)", "conclusion": "failure", "steps": []}
    assert tool.judge([gates, _golden("success")]) == (0, [f"{PDFIUM}: success"])


def test_a_missing_job_or_step_did_not_run() -> None:
    assert tool.judge([])[0] == 2
    assert tool.judge([_golden("success", step="Q-G4 something else")])[0] == 2


def test_several_steps_take_the_worst_verdict_and_print_each() -> None:
    """V10-2 names three `build` steps (D975); one failure fails it, one skip makes it not run."""
    assert tool.judge([_build("success", "success", "success")], "build (", BUILD_STEPS) == (
        0,
        [f"{name}: success" for name in BUILD_STEPS],
    )
    assert tool.judge([_build("success", "failure", "success")], "build (", BUILD_STEPS)[0] == 1
    assert tool.judge([_build("skipped", "failure", "success")], "build (", BUILD_STEPS)[0] == 2


def test_a_prefix_naming_several_jobs_judges_every_one() -> None:
    """V10-17 names a matrix's three macOS cells (D976): one red cell fails it, and each line
    names its cell."""
    step = "the test suite, T1 and T2 -- everything not marked conform"

    def cell(python: str, conclusion: str) -> dict[str, Any]:
        return {
            "name": f"test (macos-latest {python})",
            "steps": [{"name": step, "conclusion": conclusion}],
        }

    green = [cell(py, "success") for py in ("py3.12", "py3.13", "py3.14")]
    code, lines = tool.judge(green, "test (macos-latest", (step,))
    assert code == 0
    assert lines == [
        f"test (macos-latest {py}): {step}: success" for py in ("py3.12", "py3.13", "py3.14")
    ]
    assert (
        tool.judge([*green[:2], cell("py3.14", "failure")], "test (macos-latest", (step,))[0] == 1
    )


def test_v10_17s_self_ingesting_test_cannot_skip_where_ci_runs_it() -> None:
    """A green macOS cell proves V10-17's corpus test passed there only if the test cannot skip:
    D926 lifted a stale named-pipe skip, and none may return unnoticed. It carries no `conform`
    mark, so it is in the T1/T2 step V10-17 reads."""
    source = (REPO / "packages/omniweave-target-pptx/tests/unit/test_pptx_out_loop.py").read_text(
        encoding="utf-8"
    )
    above, body = source.split(
        "def test_a_corpus_holding_its_own_deck_reports_its_generated_share", 1
    )
    decorators = above.rstrip().rsplit("\n\n", 1)[-1]
    body = body.split("\ndef ", 1)[0]
    head = source.split("\ndef ", 1)[0]
    for text in (decorators, body, head):
        assert "skip" not in text and "xfail" not in text
    assert "pytestmark" not in source and "mark.conform" not in source


def test_main_reads_a_saved_document(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    saved = tmp_path / "jobs.json"
    saved.write_text(json.dumps({"jobs": [_golden("success")]}), encoding="utf-8")
    assert tool.main(["--jobs-json", str(saved)]) == 0
    assert capsys.readouterr().out.startswith(f"V10-14 ok  {saved}\n")
    saved.write_text(json.dumps({"jobs": [_golden("failure")]}), encoding="utf-8")
    assert tool.main(["--jobs-json", str(saved)]) == 1
    assert tool.main(["--jobs-json", str(tmp_path / "absent.json")]) == 2
    saved.write_text(json.dumps({"jobs": [_build("success", "success", "success")]}), "utf-8")
    argv = ["--jobs-json", str(saved), "--label", "V10-2", "--job", "build ("]
    assert tool.main([*argv, *(f"--step={name}" for name in BUILD_STEPS)]) == 0
    assert capsys.readouterr().out.splitlines()[-4].startswith("V10-2 ok  ")


def test_a_push_run_is_the_newest_green_one_and_a_nightly_the_newest_finished(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The nightly cancels push runs in its concurrency group, and a cancelled run measured
    nothing; a nightly is judged step by step, so a red one still counts (D975)."""
    asked: list[tuple[str, ...]] = []
    monkeypatch.setattr(tool, "_gh", lambda *args: asked.append(args) or '[{"databaseId": 7}]')
    assert tool.latest_run("push") == "7"
    assert tool.latest_run("schedule") == "7"
    statuses = [args[args.index("--status") + 1] for args in asked]
    events = [args[args.index("--event") + 1] for args in asked]
    assert (statuses, events) == (["success", "completed"], ["push", "schedule"])


def test_the_steps_it_reads_are_the_ones_ci_yml_runs() -> None:
    """Each prefix is a step's name in `ci.yml`, so a rename cannot leave a row reading nothing:
    the schedule-gated pdfium step in `golden` (D966), and the three `build` steps of V10-2."""
    workflow = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    golden = workflow.split("\n  golden:\n", 1)[1].split("\n  conform:\n", 1)[0]
    assert golden.split("\n", 1)[0].strip().startswith(f'name: "{tool.JOB}')
    step = golden.split(f'- name: "{tool.STEP}', 1)[1].split("\n      - ", 1)[0]
    assert "if: github.event_name == 'schedule'" in step
    assert "--pdfium-minors 2 --cells 9" in step
    build = workflow.split("\n  build:\n", 1)[1].split("\n  ci-ok:\n", 1)[0]
    assert build.split("\n", 1)[0].strip().startswith('name: "build (')
    for name in BUILD_STEPS:
        assert f'- name: "{name}' in build, name
