"""The pyright ceiling is held to the config it guards, and the config to the plan. **D997.**

`tools/pyright_ceiling.py` does not run `pyright` here. The shim fetches a Node runtime unless
`PYRIGHT_PYTHON_GLOBAL_NODE=1` finds one on PATH (11-repo-layout.md section 8.2), and a unit test
that downloaded a JavaScript runtime would be a test nobody can run offline -- which is the same
argument section 8.2 makes for keeping pyright out of the `parity` job. The real run is the `gates`
step; this file asserts the parts that are checkable without it:

* every check driven to FAIL over synthetic diagnostics, including the two directions of the
  ratchet and the two directions of the forward-reference set;
* `None` from `run_pyright` is NOT zero errors, which is the one confusion that would turn a
  broken shim into a clean tree;
* the `[tool.pyright]` table says what the plan and the ruling asked for, scope and mode;
* and every rule the table turns off carries a reason in the file that turns it off, because an
  override without an argument is an off switch.

Specified in 11-repo-layout.md sections 8.1 and 8.2, and a user ruling of 2026-10-27.
"""

from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import pytest

REPO_ROOT: Final = Path(__file__).resolve().parents[4]


def _load() -> ModuleType:
    path = REPO_ROOT / "tools" / "pyright_ceiling.py"
    spec = importlib.util.spec_from_file_location("pyright_ceiling_under_test", path)
    if spec is None or spec.loader is None:  # pragma: no cover - a real path, a real loader
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


pc: Final = _load()


def diag(rule: str, message: str = "x", file: str = "a.py", line: int = 0) -> dict[str, Any]:
    """One pyright diagnostic, in the shape `--outputjson` emits."""
    return {
        "severity": "error",
        "rule": rule,
        "message": message,
        "file": str(REPO_ROOT / file),
        "range": {"start": {"line": line, "character": 0}},
    }


def headlines(findings: list[Any]) -> str:
    return "\n".join(str(getattr(one, "headline", one)) for one in findings)


def at_ceiling() -> list[dict[str, Any]]:
    """Diagnostics that sit exactly at `CEILING`, with the forward names spread over the 45."""
    forward = sorted(pc.FORWARD)
    out: list[dict[str, Any]] = []
    for rule, count in pc.CEILING.items():
        for index in range(count):
            if rule == "reportUndefinedVariable":
                name = forward[index % len(forward)]
                out.append(diag(rule, f'"{name}" is not defined'))
            else:
                out.append(diag(rule))
    return out


#  ---------------------------------------------------------------------------------------------
#  The ratchet, both directions


def test_a_tree_at_the_ceiling_passes_every_check() -> None:
    _report, findings = pc.check_ceiling(at_ceiling())
    assert findings == [], headlines(findings)
    _report, findings = pc.check_forward_references(at_ceiling())
    assert findings == [], headlines(findings)


def test_one_more_error_in_any_rule_fails_and_names_the_rule() -> None:
    worse = [*at_ceiling(), diag("reportArgumentType")]
    _report, findings = pc.check_ceiling(worse)
    assert "reportArgumentType: 38 error(s) against a ceiling of 37." in headlines(findings)


def test_the_failure_carries_a_locus_so_it_starts_somewhere_rather_than_nowhere() -> None:
    """The first diagnostic of the rule that moved, repo-relative. A count with no locus is a
    number a reader has to go and find, which is a failure message that does half its job."""
    one_only = [one for one in at_ceiling() if one["rule"] != "reportUnusedImport"]
    one_only.extend(diag("reportUnusedImport", file="packages/x.py", line=41) for _ in range(2))
    _report, findings = pc.check_ceiling(one_only)
    rendered = "\n".join(one.render() for one in findings)
    assert "reportUnusedImport: 2 error(s) against a ceiling of 1." in rendered
    assert "first at packages/x.py:42" in rendered


def test_one_fewer_error_fails_so_the_ceiling_is_tightened_in_the_same_change() -> None:
    """A ratchet nobody tightens is a number nobody is watching -- `tools/gates.toml`'s argument
    for G27 clause d2's two ceilings, in the same words."""
    better = [one for one in at_ceiling() if one["rule"] != "reportUnusedImport"]
    _report, findings = pc.check_ceiling(better)
    assert "reportUnusedImport: 0 error(s) and the ceiling is still 1." in headlines(findings)
    assert "fix: lower it to 0" in "\n".join(one.render() for one in findings)


def test_a_rule_with_no_row_at_all_fails_however_small_the_total() -> None:
    """The reason the ceiling is per rule. A total-only ratchet reports no change when twelve
    errors of one class are traded for twelve of another."""
    traded = [one for one in at_ceiling() if one["rule"] != "reportArgumentType"]
    traded.extend(diag("reportCallIssue") for _ in range(37))
    assert len(traded) == sum(pc.CEILING.values())
    _report, findings = pc.check_ceiling(traded)
    printed = headlines(findings)
    assert "reportCallIssue: 37 error(s), and the rule is not in CEILING at all." in printed
    assert "reportArgumentType: 0 error(s) and the ceiling is still 37." in printed


def test_the_report_prints_every_rule_against_its_ceiling() -> None:
    report, _findings = pc.check_ceiling(at_ceiling())
    printed = "\n".join(report)
    for rule in pc.CEILING:
        assert rule in printed, rule
    assert f"ceiling {sum(pc.CEILING.values())} over {len(pc.CEILING)}" in printed


#  ---------------------------------------------------------------------------------------------
#  The forward references, pinned to their names and not merely counted


def test_an_undefined_name_that_is_not_a_declared_forward_reference_fails() -> None:
    """A typo in an annotation is an undefined name too, and a count alone would let it through at
    the cost of one real forward reference being fixed somewhere else."""
    planted = [one for one in at_ceiling() if one["rule"] != "reportUndefinedVariable"]
    planted.extend(diag("reportUndefinedVariable", '"DocRecrod" is not defined') for _ in range(45))
    _report, findings = pc.check_forward_references(planted)
    assert "not declared forward references: DocRecrod" in headlines(findings)


def test_a_forward_name_nothing_names_any_more_fails_so_the_set_shrinks() -> None:
    dropped = [
        one
        for one in at_ceiling()
        if one["rule"] != "reportUndefinedVariable" or "Frame" not in str(one["message"])
    ]
    _report, findings = pc.check_forward_references(dropped)
    assert "FORWARD name(s) nothing names any more" in headlines(findings)
    assert "Frame" in headlines(findings)


def test_every_forward_name_is_cited_at_a_use_site_with_its_plan_reference() -> None:
    """The set is not an allow-list of convenience: each name has to be a forward reference a
    module actually writes, with the `# noqa: F821` the linter needed for the same reason."""
    sources = [
        one
        for one in sorted((REPO_ROOT / "packages").rglob("*.py"))
        if "tests" not in one.parts and "fixtures" not in one.parts
    ]
    corpus = {one: one.read_text(encoding="utf-8") for one in sources}
    for name in sorted(pc.FORWARD):
        cited = [
            path
            for path, text in corpus.items()
            if f": {name}" in text or f"-> {name}" in text or f"[{name}]" in text
        ]
        assert cited, f"{name} is in FORWARD and no module names it"
    #  And the mechanism is the one the linter already needed: F821 suppressions with a citation.
    doc = (REPO_ROOT / "packages/omniweave-core/src/omniweave_core/model/doc.py").read_text(
        encoding="utf-8"
    )
    assert "noqa: F821" in doc
    assert "have no module yet" in doc, "the document's own sentence about these names"


#  ---------------------------------------------------------------------------------------------
#  `None` is not zero


def test_a_run_that_produced_nothing_readable_is_not_a_clean_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one confusion that would turn a broken shim into a pass. `main` exits 2, not 0."""
    monkeypatch.setattr(pc, "run_pyright", lambda: None)
    assert pc.main([]) == pc.EXIT_NOT_RUN


def test_a_stray_argument_is_a_usage_error() -> None:
    assert pc.main(["--fix"]) == pc.EXIT_NOT_RUN


#  ---------------------------------------------------------------------------------------------
#  The config this gate guards


@pytest.fixture
def pyright_table() -> dict[str, object]:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    table = data["tool"]["pyright"]
    assert isinstance(table, dict)
    return table


def test_the_table_declares_strict_and_not_a_mode_that_flatters_the_tree(
    pyright_table: dict[str, object],
) -> None:
    """11-repo-layout.md section 8.1's table says strict. `standard` reports 91 errors here and
    strict reports 1,722, so declaring `standard` would record a number that looks finished and
    hide a gap of 1,631."""
    assert pyright_table["typeCheckingMode"] == "strict"
    assert pyright_table["pythonVersion"] == "3.12"
    assert pyright_table["pythonPlatform"] == "All", (
        "locks.py imports fcntl under a platform guard; checking one platform hides the other"
    )


def test_the_scope_is_the_rulings_and_the_test_tier_is_out(
    pyright_table: dict[str, object],
) -> None:
    """A user ruling of 2026-10-27: `packages/*/src` and `tools`, tests excluded."""
    assert pyright_table["include"] == ["packages", "tools"]
    excluded = pyright_table["exclude"]
    assert isinstance(excluded, list)
    assert "**/tests" in excluded
    assert "vendor" in excluded, "third-party source at a recorded SHA is not ours to type"


def test_every_rule_the_table_turns_off_carries_its_reason_in_the_same_file(
    pyright_table: dict[str, object],
) -> None:
    """An override without an argument is an off switch. Nine rules are off and each is named in a
    comment in `pyproject.toml` -- four of them because pyright asks for a breach of an invariant
    (INV-3 and G17's lazy core, ST6's shared `_weight`, INV-12's narrowing of untrusted input)."""
    off = sorted(key for key, value in pyright_table.items() if value is False)
    assert len(off) == 9, off
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    table = text[text.index("[tool.pyright]") :]
    for rule in off:
        line = next(one for one in table.splitlines() if one.startswith(f"{rule} ="))
        index = table.index(line)
        before = table[:index]
        #  The reason sits in the comment block above the rule, within the last 40 lines.
        context = "\n".join(before.splitlines()[-40:])
        assert "#" in context, rule
    for cited in ("INV-3", "G17", "ST6", "INV-23", "INV-12", "INV-21"):
        assert cited in table, f"the overrides' argument cites {cited} and it is missing"


def test_the_five_unknown_type_rules_are_off_together_because_they_are_one_finding(
    pyright_table: dict[str, object],
) -> None:
    """1,566 of strict's 1,722 are these, and they are a full-annotation pass over working library
    code rather than a defect: the signatures a caller reads are annotated throughout."""
    for rule in (
        "reportUnknownArgumentType",
        "reportUnknownVariableType",
        "reportUnknownMemberType",
        "reportUnknownParameterType",
        "reportUnknownLambdaType",
    ):
        assert pyright_table[rule] is False, rule


def test_this_script_is_named_outside_the_gate_glob_because_no_row_names_it() -> None:
    """`test_gates_register.py` fails on any `tools/gate_*.py` the register does not name, and
    there is no row to add: no `G<n>` covers pyright and the `[[job_assertion]]` count is nine at
    release 1 by ADR-2. `tools/plan_lint.py` set the precedent for exactly this."""
    assert (REPO_ROOT / "tools" / "pyright_ceiling.py").is_file()
    assert not (REPO_ROOT / "tools" / "gate_pyright.py").exists()
    register = tomllib.loads((REPO_ROOT / "tools" / "gates.toml").read_text(encoding="utf-8"))
    assert len(register["job_assertion"]) == 9, "ADR-2 decision 2 fixed the count at nine"


def test_the_ci_step_runs_the_ceiling_rather_than_a_bare_pyright() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "run: uv run tools/pyright_ceiling.py" in workflow
    assert "pyright NOT ENFORCED" not in workflow
    assert "\n          then uv run pyright\n" not in workflow
