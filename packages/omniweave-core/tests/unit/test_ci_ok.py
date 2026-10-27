"""`tools/ci_ok.py`: the one required status check, and the four ways it must not pass. **D989.**

11-repo-layout.md section 6.2 fixes the design -- exactly one required check, running
`if: always()` and inspecting the `needs` context -- and the register's `ci-ok.skips_declared` row
fixes what it asserts. The reason this test exists at all is in the workflow comment the script
replaced: *"a required check that reports green when a job failed is the one defect this whole
design exists to prevent"*, so every way of reporting green wrongly gets a case here.

The last test is the parity one: `EXPECTED` in the script and `needs:` in `ci.yml` are two copies
of one list, and this file holds them together rather than trusting either.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any, Final

import pytest

REPO: Final = Path(__file__).resolve().parents[4]
SCRIPT: Final = REPO / "tools" / "ci_ok.py"
WORKFLOW: Final = REPO / ".github" / "workflows" / "ci.yml"


def _load() -> Any:
    name = "ci_ok_under_test"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


CI_OK: Final = _load()


def _needs(**over: str) -> dict[str, object]:
    """Every job successful, then whatever the case overrides."""
    out: dict[str, object] = {job: {"result": "success"} for job in CI_OK.EXPECTED}
    for job, result in over.items():
        out[job] = {"result": result}
    return out


def test_every_job_successful_is_the_only_clean_run() -> None:
    assert CI_OK.findings(_needs()) == []


def test_toolchains_skipped_is_the_one_allowed_skip() -> None:
    """Section 6.2: a required `toolchains` would block every PR that does not touch TypeScript."""
    assert CI_OK.findings(_needs(toolchains="skipped")) == []


@pytest.mark.parametrize("job", sorted(set(CI_OK.EXPECTED) - CI_OK.SKIPPABLE))
def test_any_other_job_skipped_is_a_finding(job: str) -> None:
    """Ruling 2: SKIPPABLE is a literal set, so no second job may quietly join it."""
    assert CI_OK.findings(_needs(**{job: "skipped"})) == [f"{job}=skipped"]


@pytest.mark.parametrize("result", ["cancelled", "failure", "", "SUCCESS", "neutral"])
def test_only_the_literal_success_passes(result: str) -> None:
    """Ruling 1: `if: always()` fires on cancellation, and a truthiness check would read an
    aborted matrix as green. A result nobody anticipated fails rather than passing."""
    assert CI_OK.findings(_needs(gates=result)) == [f"gates={result}"]


def test_an_empty_needs_context_is_not_a_pass() -> None:
    """Ruling 3, and the failure mode of every required check: nothing to judge is not success."""
    found = CI_OK.findings({})
    assert found, "an empty context passed, which is worse than having no check"
    assert "no result reported for" in found[0]
    assert all(job in found[0] for job in CI_OK.EXPECTED)


def test_a_job_nobody_declared_is_a_finding() -> None:
    """A `needs` list that grew without this script knowing is a check judging the wrong set."""
    found = CI_OK.findings({**_needs(), "nightly": {"result": "success"}})
    assert found == ["a result for nightly, which this check does not know about"]


def test_a_malformed_result_is_a_finding_and_never_an_exception() -> None:
    """GitHub passes an object per job; a string, a null or a missing `result` is still judged."""
    for raw in ("success", None, {}, {"outputs": {}}):
        assert CI_OK.findings({**_needs(), "gates": raw}) == ["gates=None"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, {}),
        ("", {}),
        ("   ", {}),
        ("not json", {}),
        ("[]", {}),
        ('"a string"', {}),
        ('{"gates": {"result": "success"}}', {"gates": {"result": "success"}}),
    ],
)
def test_the_context_is_parsed_or_treated_as_empty(raw: str | None, expected: dict) -> None:
    """Ruling 3 again: an unparseable context is the empty one, which fails. Never a traceback --
    a required check that crashes is a required check nobody can read."""
    assert CI_OK.parse(raw) == expected


def test_main_exits_zero_only_when_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEEDS", json.dumps(_needs()))
    assert CI_OK.main([]) == 0
    monkeypatch.setenv("NEEDS", json.dumps(_needs(crash="cancelled")))
    assert CI_OK.main([]) == 1
    monkeypatch.delenv("NEEDS")
    assert CI_OK.main([]) == 1, "no NEEDS at all is ruling 3's case"


def test_the_scripts_expected_list_is_the_workflows_needs_list() -> None:
    """The parity check: two copies of one list, held together here.

    `ci_ok.py` is stdlib-only by ruling 4 -- a required check may not depend on an installed YAML
    parser -- so the workflow's list is read with a narrow regex over the `ci-ok` block rather
    than parsed.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    block = text[text.index("\n  ci-ok:") :]
    found = re.search(r"needs:\s*\n?\s*\[([^\]]+)\]", block)
    assert found, "ci.yml's ci-ok job has no needs: list in the shape this test reads"
    declared = tuple(one.strip() for one in found.group(1).replace("\n", " ").split(","))
    assert declared == CI_OK.EXPECTED, (declared, CI_OK.EXPECTED)


def test_the_workflow_runs_the_script_and_keeps_no_fallback() -> None:
    """D989 deleted the jq filter. Two implementations of one gate is how they diverge."""
    text = WORKFLOW.read_text(encoding="utf-8")
    block = text[text.index("\n  ci-ok:") :]
    assert "python3 tools/ci_ok.py" in block
    assert "jq -r" not in block, "the inline reimplementation is gone"
    assert "if [ -f tools/ci_ok.py ]" not in block, "and so is the guard that stood in for it"
