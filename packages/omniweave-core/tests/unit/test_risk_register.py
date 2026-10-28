"""The risk register is held to 17-risks.md, and its five rules to the register. **D998.**

Two rules, both from scars this repository has already paid for:

1. **Every check is driven to FAIL at least once**, over a copy of the real register mutated by one
   field. A gate nobody has seen fail is a gate nobody knows runs.
2. **The real register is asserted green**, and left byte-identical. The register's whole claim is
   that `tools/risks.toml` *is* 17-risks.md section 3's sixty rows; a suite that only exercised
   fixtures would pass on a repository whose register had drifted.

## The numbers this file pins

Section 1's five rules, measured over the committed register: **21** of the 60 indicators resolve
and **39** carry an `[[unmetered]]` declaration; **20** rows score at or above 12 and every one
carries a contingency; **13** kill criteria are defined and all 13 are reached; **six** compound
paths each have at least two member rows; and section 1.2's derived risks column matches the
register's sets and counts for all **ten** roles, with the order matching for **nine**.

That last one is a finding and not a formality. Section 1.2's `licence` cell lists its `R-L*` rows
before its `R-E*` ones, where the other nine roles and section 3's own table order put Ecosystem
before Legal -- one hand-ordered cell in a frozen document, declared in `ORDER_EXCEPTION`, and a
second divergence fails.

Specified in 17-risks.md sections 1, 1.1, 1.2, 3, 4, 5 and 7, and ADR-2 decision 2 (`RK-Q1`).
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
import tomllib
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import pytest

REPO_ROOT: Final = Path(__file__).resolve().parents[4]
REAL_REGISTER: Final = REPO_ROOT / "tools" / "risks.toml"
DOC: Final = REPO_ROOT / "docs" / "plan" / "17-risks.md"

RISKS: Final = 60
RESOLVING_INDICATORS: Final = 21
UNMETERED_ROWS: Final = 39
HIGH_SCORE_ROWS: Final = 20
KILL_CRITERIA: Final = 13
COMPOUND_PATHS: Final = 6
OWNER_ROLES: Final = 10


def _load() -> ModuleType:
    path = REPO_ROOT / "tools" / "risk_register.py"
    spec = importlib.util.spec_from_file_location("risk_register_under_test", path)
    if spec is None or spec.loader is None:  # pragma: no cover - a real path, a real loader
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rr: Final = _load()


@pytest.fixture
def register() -> dict[str, Any]:
    return tomllib.loads(REAL_REGISTER.read_text(encoding="utf-8"))


@pytest.fixture
def rows(register: dict[str, Any]) -> list[dict[str, Any]]:
    return register["risk"]


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A copy of the register, with the module repointed at it."""
    copy = tmp_path / "risks.toml"
    shutil.copy2(REAL_REGISTER, copy)
    monkeypatch.setattr(rr, "REGISTER", copy)
    return copy


def rewrite(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"{text.count(old)} matches for {old!r}"
    path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")


def reread(path: Path) -> list[dict[str, Any]]:
    return tomllib.loads(path.read_text(encoding="utf-8"))["risk"]


def unmetered(path: Path) -> list[dict[str, Any]]:
    return tomllib.loads(path.read_text(encoding="utf-8")).get("unmetered", [])


def headlines(findings: list[Any]) -> str:
    return "\n".join(str(getattr(one, "headline", one)) for one in findings)


#  ---------------------------------------------------------------------------------------------
#  The register as committed


def test_the_real_register_passes_every_rule() -> None:
    assert rr.main([]) == 0


def test_a_full_run_leaves_the_register_byte_identical() -> None:
    before = REAL_REGISTER.read_bytes()
    rr.main([])
    assert REAL_REGISTER.read_bytes() == before, "a checker that writes is not a checker"


def test_the_register_is_section_threes_sixty_rows(rows: list[dict[str, Any]]) -> None:
    assert len(rows) == RISKS
    assert len({one["id"] for one in rows}) == RISKS
    #  Section 3's five subsections, and the register's `category` is the subheading.
    assert {one["category"] for one in rows} == {
        "technical",
        "ecosystem",
        "legal",
        "operational",
        "adoption",
    }


def test_every_row_is_checked_against_its_own_source_line(rows: list[dict[str, Any]]) -> None:
    """Sixty rows transcribed by hand would rot, so none of them is trusted."""
    _report, findings = rr.check_sources(rows)
    assert findings == [], headlines(findings)
    assert all(one["source"].startswith("docs/plan/17-risks.md:") for one in rows)


def test_a_stray_argument_is_a_usage_error() -> None:
    assert rr.main(["--fix"]) == 2


#  ---------------------------------------------------------------------------------------------
#  S3, the floor


def test_the_floor_fails_before_any_rule_reports_on_an_empty_set() -> None:
    """A loader that returned nothing would make every rule pass over nothing."""
    _report, findings = rr.check_floor([])
    assert f"the register holds 0 `[[risk]]` row(s); section 3 holds {RISKS}." in headlines(
        findings
    )


def test_a_duplicated_id_fails(isolated: Path) -> None:
    text = isolated.read_text(encoding="utf-8")
    block = text[text.index('[[risk]]\nid          = "R-T2"') :].split("\n\n", 1)[0]
    isolated.write_text(text + "\n\n" + block + "\n", encoding="utf-8", newline="\n")
    _report, findings = rr.check_floor(reread(isolated))
    assert "R-T2 appears in 2 rows." in headlines(findings)


#  ---------------------------------------------------------------------------------------------
#  Rule 1


def test_rule_one_resolves_twenty_one_and_declares_thirty_nine(
    rows: list[dict[str, Any]], register: dict[str, Any]
) -> None:
    report, findings = rr.check_indicators(rows, register["unmetered"])
    assert findings == [], headlines(findings)
    assert f"{RESOLVING_INDICATORS} indicator(s) resolve" in report[0]
    assert f"{UNMETERED_ROWS} declared unmetered" in report[0]
    assert len(register["unmetered"]) == UNMETERED_ROWS


def test_an_indicator_that_resolves_nowhere_and_is_not_declared_fails(isolated: Path) -> None:
    rewrite(isolated, 'indicator   = "store.bytes_per_block"', 'indicator   = "made.up.thing"')
    _report, findings = rr.check_indicators(reread(isolated), unmetered(isolated))
    assert "indicator 'made.up.thing' resolves in none of rule 1's registers" in headlines(findings)


def test_a_declared_row_whose_indicator_resolves_now_fails_so_the_list_shrinks(
    isolated: Path,
) -> None:
    """The forcing function. Nine of the eleven `counter_owed` rows become resolvable the moment
    13-quality.md's and 15-observability.md's owed ids land in `eval/counters.toml`."""
    rows = reread(isolated)
    for row in rows:
        if row["id"] == "R-T1":
            row["indicator"] = "G3"
    _report, findings = rr.check_indicators(rows, unmetered(isolated))
    assert "resolves in gate and the row still has an [[unmetered]] declaration" in headlines(
        findings
    )


def test_a_declaration_for_a_row_that_is_not_in_the_register_fails(isolated: Path) -> None:
    text = isolated.read_text(encoding="utf-8")
    isolated.write_text(
        text + '\n[[unmetered]]\nrisk  = "R-Z9"\nkind  = "store_column"\nnames = "nothing"\n',
        encoding="utf-8",
        newline="\n",
    )
    _report, findings = rr.check_indicators(reread(isolated), unmetered(isolated))
    assert "[[unmetered]] R-Z9 is not a row of this register." in headlines(findings)


def test_a_declaration_whose_kind_has_no_reason_fails(isolated: Path) -> None:
    """An override without an argument is an off switch, so `kind` has to name one of the eleven
    reasons `KIND_REASON` carries -- and those live beside the check, not in the register."""
    rewrite(
        isolated,
        'kind  = "counter_owed"\nnames = "owdoc.unknown_kind_rate"',
        'kind  = "because_i_said_so"\nnames = "owdoc.unknown_kind_rate"',
    )
    _report, findings = rr.check_indicators(reread(isolated), unmetered(isolated))
    assert "kind 'because_i_said_so' has no row in KIND_REASON" in headlines(findings)


def test_every_declared_kind_has_a_reason_and_every_reason_is_used(
    register: dict[str, Any],
) -> None:
    kinds = {one["kind"] for one in register["unmetered"]}
    assert kinds <= set(rr.KIND_REASON), sorted(kinds - set(rr.KIND_REASON))
    assert set(rr.KIND_REASON) == kinds, "a reason nothing uses is a reason nobody reviews"
    for kind, reason in rr.KIND_REASON.items():
        assert len(reason) > 40, kind


def test_every_counter_owed_row_carries_the_daggered_id_the_document_marked(
    register: dict[str, Any],
) -> None:
    """Section 3's dagger: an id that "does not yet exist and is added to `eval/counters.toml` or
    `eval/perf.toml` by 13-quality.md (metrics) and 15-observability.md (event fields) in the same
    change that merges this document". That change did not happen.

    Seventeen rows carry a dagger SOMEWHERE in their trigger (eighteen marks in all, because one
    cell names two unbuilt ids). Nine of them are `counter_owed`; the rest carry a dagger beside a
    secondary clause while their leading instrument resolves -- `R-T2` on `store.bytes_per_block`,
    `R-T16` on `span_exact_rate`, `R-L1` on `G3`. The containment is asserted in the direction
    that can rot: a `counter_owed` row whose cell has no dagger would be a declaration with no
    document behind it.
    """
    owed = [one for one in register["unmetered"] if one["kind"] == "counter_owed"]
    assert len(owed) == 9
    dagger = {one["id"] for one in register["risk"] if "(unbuilt)" in one["trigger"]}
    assert len(dagger) == 17
    assert sum(one["trigger"].count("(unbuilt)") for one in register["risk"]) == 18
    assert {one["risk"] for one in owed} <= dagger


#  ---------------------------------------------------------------------------------------------
#  Rule 2


def test_rule_two_holds_over_twenty_rows(rows: list[dict[str, Any]]) -> None:
    report, findings = rr.check_scores(rows)
    assert findings == [], headlines(findings)
    assert f"{HIGH_SCORE_ROWS} row(s) at or above {rr.HIGH_SCORE}" in report[0]


def test_a_high_scoring_row_with_no_contingency_fails(isolated: Path) -> None:
    rows = reread(isolated)
    worst = max(rows, key=lambda one: one["likelihood"] * one["impact"])
    worst["contingency"] = ""
    _report, findings = rr.check_scores(rows)
    assert f"{worst['id']}: scores" in headlines(findings)
    assert "carries no contingency" in headlines(findings)


def test_a_score_off_section_twos_scale_fails(isolated: Path) -> None:
    rows = reread(isolated)
    rows[0]["impact"] = 9
    _report, findings = rr.check_scores(rows)
    assert "section 2's scales are 1..5." in headlines(findings)


#  ---------------------------------------------------------------------------------------------
#  Rule 3


def test_rule_three_resolves_the_one_key_a_section_three_cell_cites(
    rows: list[dict[str, Any]],
) -> None:
    """One of sixty, and that is faithful: section 3's table has no questions column, so an array
    populated by guessing which of 162 keys each row relates to would be invention."""
    report, findings = rr.check_scores(rows)
    assert findings == []
    report, findings = rr.check_questions(rows)
    assert findings == [], headlines(findings)
    assert "1 question key(s) cited, 162 defined" in report[0]


def test_a_question_key_in_no_section_seven_row_fails(isolated: Path) -> None:
    rows = reread(isolated)
    rows[0]["questions"] = ["99#Q99"]
    _report, findings = rr.check_questions(rows)
    assert "question key '99#Q99' is in no section 7.2-7.4 row." in headlines(findings)


#  ---------------------------------------------------------------------------------------------
#  Rule 4


def test_rule_four_holds_over_the_ten_roles_and_the_derived_column(
    register: dict[str, Any], rows: list[dict[str, Any]]
) -> None:
    report, findings = rr.check_owners(register, rows)
    assert findings == [], headlines(findings)
    assert f"{OWNER_ROLES} role(s)" in report[0]
    assert len(register["register"]["owner_roles"]) == OWNER_ROLES


def test_an_owner_off_the_ten_roles_fails(isolated: Path) -> None:
    rows = reread(isolated)
    rows[0]["owner"] = "nobody"
    _report, findings = rr.check_owners(tomllib.loads(isolated.read_text(encoding="utf-8")), rows)
    assert "owner 'nobody' is not one of the ten roles." in headlines(findings)


def test_a_review_window_wider_than_the_register_allows_fails(isolated: Path) -> None:
    rows = reread(isolated)
    rows[0]["review_by"] = "2027-06-01"
    _report, findings = rr.check_owners(tomllib.loads(isolated.read_text(encoding="utf-8")), rows)
    assert "review_every_days is 90" in headlines(findings)


def test_a_row_past_its_review_date_fails_because_rule_four_is_the_rot_clock(
    isolated: Path,
) -> None:
    """Section 1 rule 4, and `Q-G17` deliberately does not read this file: "the register's rot
    clock is rule 4 of `gates.risk_register`, and one clock per register is the point of not having
    two homes for one key." There is no non-blocking mode and no bypass flag."""
    rows = reread(isolated)
    rows[0]["reviewed_at"] = "2020-01-01"
    rows[0]["review_by"] = "2020-03-31"
    _report, findings = rr.check_owners(tomllib.loads(isolated.read_text(encoding="utf-8")), rows)
    assert "review_by 2020-03-31 has passed." in headlines(findings)


def test_a_hand_edited_derived_cell_fails(isolated: Path) -> None:
    """Section 1.2: "A hand-edited cell fails `gates.risk_register`." The register is mutated here
    rather than the frozen document, which is the same comparison from the other side."""
    rows = reread(isolated)
    for row in rows:
        if row["id"] == "R-T1":
            row["owner"] = "release"
    _report, findings = rr.check_owners(tomllib.loads(isolated.read_text(encoding="utf-8")), rows)
    printed = headlines(findings)
    assert "section 1.2's model cell is not the register's rows for that owner." in printed
    assert "section 1.2's release cell is not the register's rows for that owner." in printed


def test_the_one_order_exception_is_licence_and_a_second_would_fail() -> None:
    """The finding this check reports on its first run. Nine roles' cells are in section 3's table
    order; `licence`'s lists `R-L*` before `R-E*`."""
    assert set(rr.ORDER_EXCEPTION) == {"licence"}
    assert "Ecosystem before Legal" in rr.ORDER_EXCEPTION["licence"]
    text = DOC.read_text(encoding="utf-8")
    cell = next(line for line in text.splitlines() if line.startswith("| `licence` |"))
    assert cell.index("R-L1") < cell.index("R-E6"), "the document's order, which the row records"


#  ---------------------------------------------------------------------------------------------
#  Rule 5 and the paths


def test_rule_five_holds_in_both_directions(rows: list[dict[str, Any]]) -> None:
    report, findings = rr.check_kills(rows)
    assert findings == [], headlines(findings)
    assert f"{KILL_CRITERIA} criterion/criteria in section 5, all reached" in report[0]


def test_a_kill_value_in_no_section_five_row_fails(isolated: Path) -> None:
    rows = reread(isolated)
    rows[0]["kill"] = ["K-99"]
    _report, findings = rr.check_kills(rows)
    assert "kill 'K-99' is in no section 5 row." in headlines(findings)


def test_a_criterion_no_row_can_reach_fails(isolated: Path) -> None:
    """ "A kill criterion nothing can reach is decoration." """
    rows = [one for one in reread(isolated) if "K-13" not in one["kill"]]
    for row in rows:
        row["kill"] = [one for one in row["kill"] if one != "K-13"]
    _report, findings = rr.check_kills(rows)
    assert "kill criterion/criteria no row can reach: K-13" in headlines(findings)


def test_every_compound_path_has_at_least_two_member_rows(rows: list[dict[str, Any]]) -> None:
    report, findings = rr.check_paths(rows)
    assert findings == [], headlines(findings)
    assert f"{COMPOUND_PATHS} path(s)" in report[0]


def test_a_path_with_one_member_fails(isolated: Path) -> None:
    rows = reread(isolated)
    for row in rows:
        if row["id"] == "R-T12":
            row["paths"] = []
    _report, findings = rr.check_paths(rows)
    assert "P1 has 1 member row(s); section 4 asserts at least 2." in headlines(findings)


def test_a_path_in_no_section_four_heading_fails(isolated: Path) -> None:
    rows = reread(isolated)
    rows[0]["paths"] = ["P9"]
    _report, findings = rr.check_paths(rows)
    assert "path 'P9' is in no section 4 heading." in headlines(findings)


#  ---------------------------------------------------------------------------------------------
#  The fold, and the register row that names this runner


def test_the_fold_is_applied_and_the_dagger_is_spelled_rather_than_dropped() -> None:
    """Section 3 defines the dagger, so the fold spells it `(unbuilt)` instead of dropping a
    character a reader needs."""
    assert rr.fold(chr(0x2020)) == "(unbuilt)"
    assert rr.fold("a " + chr(0x2014) + " b") == "a -- b"
    assert rr.fold("x" + chr(0x00A0) + "y") == "x y"
    assert rr.fold("a |" + chr(0x2192) + "| b") == "a | -> | b"
    folded = rr.fold("\\|")
    assert folded == "|", "a markdown cell escapes a pipe; a TOML string does not"


def test_the_register_row_names_this_runner_and_keeps_its_two_second_budget() -> None:
    gates = tomllib.loads((REPO_ROOT / "tools" / "gates.toml").read_text(encoding="utf-8"))
    row = next(one for one in gates["job_assertion"] if one["name"] == "gates.risk_register")
    assert row["runner"] == ["tools/risk_register.py"]
    assert row["budget_s"] == 2, "17-risks.md section 1.1 budgets it at 2 s"
    assert row["job"] == "gates"
    assert row["owner"] == "release"


def test_this_script_is_named_outside_the_gate_glob_because_it_is_a_job_assertion() -> None:
    """`test_gates_register.py` fails on a `tools/gate_*.py` the register does not name by path,
    and this row is a `[[job_assertion]]` rather than a `G` row. `tools/plan_lint.py` and
    `tools/pyright_ceiling.py` are named outside the glob for the same reason."""
    assert (REPO_ROOT / "tools" / "risk_register.py").is_file()
    assert not (REPO_ROOT / "tools" / "gate_risks.py").exists()


def test_the_ci_step_runs_the_runner_and_its_tripwire_is_retired() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "run: uv run tools/risk_register.py" in workflow
    assert "gates.risk_register NOT ENFORCED" not in workflow
    assert "wire gates.risk_register" not in workflow
