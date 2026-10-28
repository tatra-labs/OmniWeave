"""`gates.invariant_register` is held to the register, and the register to the documents. **D992.**

The gate asserts eleven things and this file asserts the gate. Two rules, both from scars this
repository has already paid for:

1. **Every check is driven to FAIL at least once**, over a copy of the real register mutated by
   one field. A gate nobody has seen fail is a gate nobody knows runs -- C55's shape, recorded in
   `test_plan_lint.py`: "a gate that still runs, still exits 0, and no longer covers what it says
   it covers".
2. **The real register is asserted green**, and left byte-identical. The gate's value is that
   `tools/invariants.toml` passes today; a test suite that only exercises fixtures would pass on a
   repository whose register is broken.

## The one detector that has nothing to match

`collapse_generated` is ladder rule 2's second decidable case and it matches **no row** in the
register as committed. 11-repo-layout.md section 8.6 names that exact hazard as the one most
adopters drop -- "a regex that silently matches nothing turns every parametrized assertion below it
into a pass" -- so the detector is exercised here against a synthetic pair, in both directions:
collapsing when no parity gate is named, and not collapsing when one is. The day a row needs it,
the code is known to work rather than hoped to.

## What is deliberately NOT asserted here

The fold table's contents. `gate_invariants.py` applies it to 146 table cells on every run and a
wrong entry fails `check_members` against the source line, which is a stronger statement than any
table this file could restate. Transcribing it would be the second home INV-21 forbids.

Specified in 01-principles.md section 1e, ADR-2 decision 2, and 11-repo-layout.md:1637.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import sys
import tomllib
from pathlib import Path
from types import ModuleType
from typing import Final

import pytest

REPO_ROOT: Final = Path(__file__).resolve().parents[4]
REAL_REGISTER: Final = REPO_ROOT / "tools" / "invariants.toml"
PRINCIPLES: Final = REPO_ROOT / "docs" / "plan" / "01-principles.md"
INVARIANTS: Final = 25
"""ADR-2 decision 1. Asserted rather than imported, because the count is the thing in question."""


def _load() -> ModuleType:
    """Load `tools/gate_invariants.py` by path. `tools/` is not a package and is not installed."""
    path = REPO_ROOT / "tools" / "gate_invariants.py"
    spec = importlib.util.spec_from_file_location("gate_invariants_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    #  Registered before execution: a dataclass in the module body reads `sys.modules[__name__]`
    #  through `__module__` resolution, and an unregistered module gives `AttributeError` there.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gi: Final = _load()


@pytest.fixture
def register() -> dict[str, object]:
    """The real register, parsed. Read-only; every mutating test copies it first."""
    return tomllib.loads(REAL_REGISTER.read_text(encoding="utf-8"))


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A copy of the register, with the module repointed at it. Returns the copy's path."""
    copy = tmp_path / "invariants.toml"
    shutil.copy2(REAL_REGISTER, copy)
    monkeypatch.setattr(gi, "REGISTER", copy)
    return copy


def rewrite(path: Path, old: str, new: str) -> None:
    """One substitution, asserted unique, so a mutation test cannot silently mutate nothing."""
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"{text.count(old)} matches for {old!r}"
    path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")


def headlines(findings: list[object]) -> str:
    return "\n".join(str(getattr(one, "headline", one)) for one in findings)


#  ---------------------------------------------------------------------------------------------
#  The register as committed


def test_the_real_register_passes_every_check() -> None:
    """Rule 2. The gate's whole claim is about this file, so this is the load-bearing case."""
    assert gi.main([]) == 0


def test_the_real_register_is_left_byte_identical_by_a_full_run() -> None:
    before = REAL_REGISTER.read_bytes()
    gi.main([])
    assert REAL_REGISTER.read_bytes() == before, "a checker that writes is not a checker"


def test_the_register_holds_one_row_per_identifier_and_the_families_sum_to_them(
    register: dict[str, object],
) -> None:
    """The shape 11-repo-layout.md:2695 asks for, stated as arithmetic over the whole file."""
    families = register["family"]
    assert isinstance(families, list)
    rows = {str(row["id"]) for row in [*register["inv"], *register["member"]]}  # type: ignore[union-attr]
    assert len(rows) == len(register["inv"]) + len(register["member"])  # type: ignore[arg-type]
    assert sum(int(row["assigned"]) for row in families) == len(rows)
    assert len(register["inv"]) == INVARIANTS  # type: ignore[arg-type]


def test_every_invariant_row_reads_invariant_and_not_principle(register: dict[str, object]) -> None:
    """ADR-2 decision 1: the five that said `principle` moved, and none may move back."""
    forces = {str(row["force"]) for row in register["inv"]}  # type: ignore[union-attr]
    assert forces == {"invariant"}


def test_adding_a_row_makes_every_sentence_that_says_twenty_five_a_finding(
    isolated: Path,
) -> None:
    """A5's expected value is derived from the rows, which is the whole forcing function: "a pull
    request that adds `INV-26` and forgets a paragraph fails here".

    The mutation is a row and not a document. With twenty-six rows the nine sentences that say
    twenty-five all become findings at once -- and the register's own `[[absent]]` row for INV-26
    becomes a finding too, which is the second half of the same mechanism.
    """
    text = isolated.read_text(encoding="utf-8")
    block = text[text.index('[[inv]]\nid          = "INV-2"') :].split("\n\n", 1)[0]
    isolated.write_text(
        text + "\n\n" + block.replace('"INV-2"', '"INV-26"') + "\n",
        encoding="utf-8",
        newline="\n",
    )
    register = tomllib.loads(isolated.read_text(encoding="utf-8"))
    findings = gi.check_count(register)
    assert findings, "twenty-six rows and nine sentences saying twenty-five cannot both be right"
    assert 'says "twenty-five invariants" and the register holds 26' in headlines(findings)
    assert "INV-26 is listed as absent and has a row." in headlines(gi.check_absent(register))


#  ---------------------------------------------------------------------------------------------
#  A1 - bidirectional coverage


def test_a_row_without_a_heading_fails_and_names_it(isolated: Path) -> None:
    rewrite(isolated, '\nid          = "INV-25"', '\nid          = "INV-99"')
    findings = gi.check_bidirectional(tomllib.loads(isolated.read_text(encoding="utf-8")))
    assert findings, "a row for a section that does not exist has to fail"
    assert "INV-99" in headlines(findings)
    assert "INV-25" in headlines(findings), "and the orphaned heading has to be named too"


def test_a_duplicated_row_fails_even_though_both_copies_have_a_heading(isolated: Path) -> None:
    text = isolated.read_text(encoding="utf-8")
    block = text[text.index('[[inv]]\nid          = "INV-2"') :].split("\n\n", 1)[0]
    isolated.write_text(text + "\n\n" + block + "\n", encoding="utf-8", newline="\n")
    findings = gi.check_bidirectional(tomllib.loads(isolated.read_text(encoding="utf-8")))
    assert "INV-2 has 2 rows" in headlines(findings)


def test_a_row_whose_title_is_not_the_headings_fails(isolated: Path) -> None:
    rewrite(isolated, 'title       = "One name, one type, one home"', 'title       = "One name"')
    findings = gi.check_bidirectional(tomllib.loads(isolated.read_text(encoding="utf-8")))
    assert "INV-21: the row's title is not the heading's." in headlines(findings)


def test_the_heading_scan_is_not_vacuous() -> None:
    """d0's lesson, applied to A1: if the regex matched nothing, A1 would report every row
    orphaned and no heading missing -- which looks like a failure, so the trap here is the
    opposite one. Twenty-five headings, asserted directly against the document."""
    found = re.findall(r"^### (INV-\d+) ", PRINCIPLES.read_text(encoding="utf-8"), re.MULTILINE)
    assert len(found) == INVARIANTS
    assert len(set(found)) == INVARIANTS


#  ---------------------------------------------------------------------------------------------
#  A2 and A3 - ladder rule 1 and the arithmetic


def test_a_row_below_min_enforcers_fails(isolated: Path) -> None:
    rewrite(isolated, 'enforcers   = ["G10", "G17", "G23"]', 'enforcers   = ["G10"]')
    rewrite(
        isolated,
        'classes     = ["G"]\nindependent = 3\n\n[[inv]]\nid          = "INV-4"',
        'classes     = ["G"]\nindependent = 1\n\n[[inv]]\nid          = "INV-4"',
    )
    findings = gi.check_ladder_rule_one(tomllib.loads(isolated.read_text(encoding="utf-8")))
    assert "INV-3: independent = 1, min_enforcers = 2." in headlines(findings)


def test_classes_of_only_r_class_fails_rule_one(isolated: Path) -> None:
    rewrite(
        isolated,
        'classes     = ["L", "G"]\nindependent = 3',
        'classes     = ["R"]\nindependent = 3',
    )
    findings = gi.check_ladder_rule_one(tomllib.loads(isolated.read_text(encoding="utf-8")))
    assert "which rule 1 forbids on its own" in headlines(findings)


def test_a_class_off_the_ladder_fails_and_does_not_take_the_order_check_down_with_it(
    isolated: Path,
) -> None:
    """The first run of this test raised `ValueError: 'Z' is not in list` out of `ladder.index`,
    so the gate printed no finding at all. A checker that raises reports nothing, which is worse
    than a checker that misses one thing."""
    rewrite(
        isolated,
        'classes     = ["G"]\nindependent = 3\n\n[[inv]]\nid          = "INV-4"',
        'classes     = ["Z"]\nindependent = 3\n\n[[inv]]\nid          = "INV-4"',
    )
    findings = gi.check_ladder_rule_one(tomllib.loads(isolated.read_text(encoding="utf-8")))
    assert "class(es) not on the ladder: ['Z']" in headlines(findings)
    assert "not in ladder order" not in headlines(findings)


def test_classes_out_of_ladder_order_fails(isolated: Path) -> None:
    rewrite(
        isolated,
        'classes     = ["L", "G"]\nindependent = 3',
        'classes     = ["G", "L"]\nindependent = 3',
    )
    findings = gi.check_ladder_rule_one(tomllib.loads(isolated.read_text(encoding="utf-8")))
    assert "not in ladder order" in headlines(findings)


def test_the_arithmetic_fails_on_an_independent_that_does_not_add_up(isolated: Path) -> None:
    rewrite(
        isolated,
        'classes     = ["G"]\nindependent = 3\n\n[[inv]]\nid          = "INV-4"',
        'classes     = ["G"]\nindependent = 4\n\n[[inv]]\nid          = "INV-4"',
    )
    findings = gi.check_arithmetic(tomllib.loads(isolated.read_text(encoding="utf-8")))
    assert "independent = 4, len(enforcers) + len(sites) = 3 + 0" in headlines(findings)


def test_an_enforcer_listed_twice_fails_because_it_is_one_enforcer(isolated: Path) -> None:
    """Both halves of A3 fire on this one edit, and that is the honest outcome: the list is wrong
    whether `independent` was bumped to match it or not."""
    rewrite(isolated, 'enforcers   = ["G1", "G4", "G9"]', 'enforcers   = ["G1", "G4", "G9", "G9"]')
    findings = gi.check_arithmetic(tomllib.loads(isolated.read_text(encoding="utf-8")))
    assert "INV-2: enforcers lists an entry twice." in headlines(findings)


#  ---------------------------------------------------------------------------------------------
#  A4 - ladder rule 2, and the detector with nothing to match


def test_rule_two_collapses_two_references_to_one_semgrep_bank() -> None:
    """Case (a), in isolation: two entries that resolve to one bank are one enforcer."""
    collapsed = gi.collapse_semgrep(
        ["G8", "G24"], ["tools/semgrep/omniweave.yaml"], frozenset({"G8", "G24"})
    )
    assert collapsed == 2, "three references to one bank are one enforcer, so two are discounted"
    assert gi.collapse_semgrep(["G8"], [], frozenset({"G8"})) == 0
    assert gi.collapse_semgrep(["G1", "G4"], [], frozenset({"G8"})) == 0


def test_rule_twos_semgrep_case_can_fail_a_row_that_looks_like_it_has_two(isolated: Path) -> None:
    rewrite(
        isolated,
        'enforcers   = ["G11", "DR1"]\nsites       = ["tools/semgrep/omniweave.yaml"]',
        'enforcers   = ["G8"]\nsites       = ["tools/semgrep/omniweave.yaml"]',
    )
    rewrite(
        isolated,
        'classes     = ["L", "G", "X"]\nindependent = 3',
        'classes     = ["L", "G", "X"]\nindependent = 2',
    )
    findings = gi.check_ladder_rule_two(tomllib.loads(isolated.read_text(encoding="utf-8")))
    assert "1 independent enforcer(s) after rule 2" in headlines(findings)


def test_rule_twos_generated_case_collapses_a_pair_with_no_parity_gate() -> None:
    """Case (b), the detector that matches no committed row. Exercised in both directions."""
    generated = {"schema.json": "tools/events.toml"}
    assert gi.collapse_generated(["G20"], ["schema.json", "tools/events.toml"], generated) == 1
    assert gi.collapse_generated(["G20"], ["schema.json"], generated) == 0
    with_parity = generated | {"schema.json:parity": "G20"}
    assert gi.collapse_generated(["G20"], ["schema.json", "tools/events.toml"], with_parity) == 0, (
        "a named parity gate is the 'unless' in assertion 4; the pair then counts as two"
    )
    assert gi.collapse_generated([], ["schema.json", "tools/events.toml"], with_parity) == 1, (
        "the parity gate has to be LISTED on the row, not merely exist in the table"
    )


#  ---------------------------------------------------------------------------------------------
#  A5 - the count


def test_a_prose_count_that_disagrees_with_the_register_fails(
    isolated: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = tmp_path / "made-up.md"
    document.write_text("The plan is twenty-four invariants.\n", encoding="utf-8", newline="\n")
    monkeypatch.setattr(gi, "plan_scope", lambda: (document,))
    monkeypatch.setattr(gi, "REPO", tmp_path)
    findings = gi.check_count(tomllib.loads(isolated.read_text(encoding="utf-8")))
    assert 'says "twenty-four invariants" and the register holds 25' in headlines(findings)


def test_a_count_exempt_row_silences_exactly_its_own_phrase_and_nothing_else(
    isolated: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = tmp_path / "made-up.md"
    document.write_text(
        "Four invariants added by this document. And three invariants elsewhere.\n",
        encoding="utf-8",
        newline="\n",
    )
    monkeypatch.setattr(gi, "plan_scope", lambda: (document,))
    monkeypatch.setattr(gi, "REPO", tmp_path)
    register = tomllib.loads(isolated.read_text(encoding="utf-8"))
    register["count_exempt"] = [{"file": "made-up.md", "phrase": "Four invariants", "why": "x"}]
    findings = gi.check_count(register)
    assert "Four invariants" not in headlines(findings)
    assert "three invariants" in headlines(findings)


def test_the_count_scan_ignores_a_qualified_phrase() -> None:
    """ "five framework-wide invariants" is INV-21..INV-25 and "eighteen graph invariants" is the
    GR series. The scan is the bare form for that reason, and this pins it."""
    assert gi._COUNT.search("five framework-wide invariants") is None
    assert gi._COUNT.search("eighteen graph invariants") is None
    assert gi._COUNT.search("nine invariant prefixes") is not None
    found = gi._COUNT.search("the twenty-five invariants")
    assert found is not None and found.group(1) == "twenty-five"


def test_the_scan_scope_is_the_plan_and_the_adrs_and_never_the_notes() -> None:
    """The charter's "Twenty properties." is superseded by erratum E30 and stands as printed; a
    scan that reached it would demand the record be rewritten to keep a gate quiet."""
    scope = {path.relative_to(REPO_ROOT).as_posix() for path in gi.plan_scope()}
    assert "docs/plan/01-principles.md" in scope
    assert "docs/plan/adr/0002-invariant-and-gate-registers.md" in scope
    assert "docs/ARCHITECTURE.md" in scope
    assert not [one for one in scope if "_notes" in one]
    assert all((REPO_ROOT / one).is_file() for one in scope)


#  ---------------------------------------------------------------------------------------------
#  S1 and S2 - families and members


def test_a_family_whose_assigned_count_is_wrong_fails(isolated: Path) -> None:
    rewrite(isolated, 'prefix    = "GR"', 'prefix    = "GR"\n#  mutated below')
    rewrite(
        isolated, 'rows      = "member"\nassigned  = 18', 'rows      = "member"\nassigned  = 17'
    )
    findings = gi.check_families(tomllib.loads(isolated.read_text(encoding="utf-8")))
    assert "GR: assigned = 17, rows = 18." in headlines(findings)


def test_listing_inv_before_m_inv_fails_because_the_longest_match_must_win(
    isolated: Path,
) -> None:
    text = isolated.read_text(encoding="utf-8")
    start = text.index('[[family]]\nprefix    = "M-INV"')
    end = text.index('[[family]]\nprefix    = "DR"')
    m_inv, inv = text[start:end].split('[[family]]\nprefix    = "INV"')
    swapped = text[:start] + '[[family]]\nprefix    = "INV"' + inv + m_inv + text[end:]
    isolated.write_text(swapped, encoding="utf-8", newline="\n")
    findings = gi.check_families(tomllib.loads(swapped))
    assert "longest match does not win" in headlines(findings)


def test_a_member_whose_family_is_not_its_longest_match_fails(isolated: Path) -> None:
    rewrite(
        isolated,
        'id          = "M-INV-3"\nfamily      = "M-INV"',
        'id          = "M-INV-3"\nfamily      = "INV"',
    )
    findings = gi.check_members(tomllib.loads(isolated.read_text(encoding="utf-8")))
    assert "M-INV-3: family = 'INV', longest match is 'M-INV'." in headlines(findings)


def test_a_title_that_is_not_the_folded_source_cell_fails(isolated: Path) -> None:
    """S2, and the reason the register carries a `source` at all: 151 rows transcribed by hand
    would rot, so none of them is trusted."""
    rewrite(
        isolated,
        'title       = "A duplicate driver id never wins silently."',
        'title       = "A duplicate driver id wins silently."',
    )
    findings = gi.check_members(tomllib.loads(isolated.read_text(encoding="utf-8")))
    assert "DR3: title is not the folded source cell." in headlines(findings)


def test_a_source_line_that_does_not_name_the_identifier_fails(isolated: Path) -> None:
    rewrite(
        isolated,
        'source      = "docs/plan/_notes/charter.md:2270"',
        'source      = "docs/plan/_notes/charter.md:2271"',
    )
    findings = gi.check_members(tomllib.loads(isolated.read_text(encoding="utf-8")))
    assert "DR1: source docs/plan/_notes/charter.md:2271 does not name it." in headlines(findings)


def test_an_identifier_in_both_arrays_fails(isolated: Path) -> None:
    rewrite(
        isolated,
        'id          = "DR1"\nfamily      = "DR"',
        'id          = "INV-1"\nfamily      = "DR"',
    )
    findings = gi.check_members(tomllib.loads(isolated.read_text(encoding="utf-8")))
    assert "INV-1 appears in 2 rows across the arrays." in headlines(findings)


def test_every_member_rows_source_is_one_of_the_three_documents_that_assign_numbers(
    register: dict[str, object],
) -> None:
    """Not a mutation test: a statement about where the register is allowed to read from. A row
    sourced from a document that does not assign that prefix's numbers is a transcription from
    somewhere a reviewer would not think to check."""
    allowed = {
        "docs/plan/_notes/charter.md",
        "docs/plan/07-store-and-retrieval.md",
        "docs/plan/03-document-model.md",
    }
    for row in register["member"]:  # type: ignore[union-attr]
        where = str(row["source"]).rpartition(":")[0]
        assert where in allowed, f"{row['id']} sourced from {where}"


#  ---------------------------------------------------------------------------------------------
#  S3 and S4 - enforcers and sites


def test_an_enforcer_that_resolves_nowhere_fails(isolated: Path) -> None:
    rewrite(isolated, 'enforcers   = ["G1", "G4", "G9"]', 'enforcers   = ["G1", "G4", "G999"]')
    findings = gi.check_enforcers(tomllib.loads(isolated.read_text(encoding="utf-8")))
    assert "INV-2: enforcer G999 is not in tools/gates.toml." in headlines(findings)


def test_an_unknown_quality_gate_fails_against_the_document_that_numbers_them(
    isolated: Path,
) -> None:
    rewrite(isolated, 'enforcers   = ["Q-G6"]', 'enforcers   = ["Q-G99"]')
    findings = gi.check_enforcers(tomllib.loads(isolated.read_text(encoding="utf-8")))
    assert "enforcer Q-G99 is not in 13-quality.md section 14." in headlines(findings)


def test_a_site_that_neither_resolves_nor_is_scheduled_fails(isolated: Path) -> None:
    rewrite(
        isolated,
        'sites       = ["omniweave_ports.DriverIO", "omniweave_core.host.subproc"]',
        'sites       = ["omniweave_ports.NoSuchThing", "omniweave_core.host.subproc"]',
    )
    findings = gi.check_sites(tomllib.loads(isolated.read_text(encoding="utf-8")))
    assert "site omniweave_ports.NoSuchThing neither resolves nor is scheduled" in headlines(
        findings
    )


def test_a_scheduled_site_that_now_resolves_fails_so_the_list_shrinks(isolated: Path) -> None:
    rewrite(isolated, 'site  = "omniweave_core.route.eval"', 'site  = "omniweave_core.limits"')
    rewrite(
        isolated,
        'sites       = ["omniweave_core.route.eval", "tools/semgrep/omniweave.yaml"]',
        'sites       = ["omniweave_core.limits", "tools/semgrep/omniweave.yaml"]',
    )
    findings = gi.check_sites(tomllib.loads(isolated.read_text(encoding="utf-8")))
    assert "omniweave_core.limits resolves and still has an [[unbuilt_site]] row" in headlines(
        findings
    )


def test_a_scheduled_site_naming_a_phase_the_roadmap_does_not_have_fails(isolated: Path) -> None:
    rewrite(isolated, 'phase = "P5"', 'phase = "P77"')
    findings = gi.check_sites(tomllib.loads(isolated.read_text(encoding="utf-8")))
    assert "phase P77 is not in 16-roadmap.md" in headlines(findings)


def test_site_resolution_accepts_a_path_as_well_as_a_symbol() -> None:
    assert gi._resolves("tools/semgrep/omniweave.yaml")
    assert not gi._resolves("tools/semgrep/does-not-exist.yaml")
    assert gi._resolves("omniweave_core.limits")
    assert not gi._resolves("omniweave_core.limits.NO_SUCH_CONSTANT")


#  ---------------------------------------------------------------------------------------------
#  S5 and S6 - the two declared exception tables


def test_an_absent_row_for_an_identifier_that_now_exists_fails(isolated: Path) -> None:
    rewrite(isolated, 'id    = "RT15"', 'id    = "RT14"')
    findings = gi.check_absent(tomllib.loads(isolated.read_text(encoding="utf-8")))
    assert "RT14 is listed as absent and has a row." in headlines(findings)


def test_an_absent_row_whose_citation_moved_fails(isolated: Path) -> None:
    rewrite(
        isolated,
        'cites = "docs/plan/01-principles.md:868"',
        'cites = "docs/plan/01-principles.md:869"',
    )
    findings = gi.check_absent(tomllib.loads(isolated.read_text(encoding="utf-8")))
    assert "INV-26: docs/plan/01-principles.md:869 no longer names it." in headlines(findings)


def test_a_stale_count_exemption_fails(isolated: Path) -> None:
    rewrite(isolated, 'phrase = "Four invariants"', 'phrase = "Eleven invariants"')
    findings = gi.check_count_exempt(tomllib.loads(isolated.read_text(encoding="utf-8")))
    assert "no longer says 'Eleven invariants'" in headlines(findings)


def test_both_deliberately_absent_identifiers_are_cited_and_neither_has_a_row(
    register: dict[str, object],
) -> None:
    """The two are the whole list, and the list being short is what makes it reviewable."""
    absent = {str(row["id"]) for row in register["absent"]}  # type: ignore[union-attr]
    assert absent == {"RT15", "INV-26"}
    held = {str(row["id"]) for row in [*register["inv"], *register["member"]]}  # type: ignore[union-attr]
    assert not absent & held


#  ---------------------------------------------------------------------------------------------
#  The runner column, and the register that names it


def test_the_register_row_moved_this_script_from_planned_to_runner() -> None:
    """tools/gates.toml's own forcing function: landing a runner forces a register edit rather
    than leaving a row pointing at a file nobody wrote -- and the other direction is asserted
    too, because a path in both columns would make the rule unfalsifiable."""
    gates = tomllib.loads((REPO_ROOT / "tools" / "gates.toml").read_text(encoding="utf-8"))
    row = next(
        one for one in gates["job_assertion"] if str(one["name"]) == "gates.invariant_register"
    )
    assert row.get("runner") == ["tools/gate_invariants.py"]
    assert "runner_planned" not in row
    assert int(row["budget_s"]) == 2, "ADR-2 decision 2 budgets it at 2 s"


def test_the_ci_step_runs_the_script_rather_than_a_tripwire() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "run: uv run tools/gate_invariants.py" in workflow
    assert "gates.invariant_register NOT ENFORCED" not in workflow
