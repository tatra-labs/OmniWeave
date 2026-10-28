"""G27's fence clauses are held to the corpus, and the corpus to ADR-4's own measurement. **D994.**

Two rules, both from scars this repository has already paid for:

1. **Every check is driven to FAIL at least once**, over a fixture document in `tmp_path`. A gate
   nobody has seen fail is a gate nobody knows runs -- C55's shape.
2. **The real corpus is asserted green**, which is the only statement that matters on a tree where
   every document the gate reads is frozen.

## The numbers this file pins, and why they are not decoration

ADR-4 decision 1 retires the charter's section D4 ` ```toml ` fence on four measured grounds, two
of which are exactly what clauses (a2) and (a3) compute: *"(a) seven rules there fail lint check 4
(`OW-P-004`), not nine, against zero in section 4.4"* and *"(b) One inline table spans a newline,
not two, and it is a `when` rather than a `then`."* So this file asserts seven and one, by locus
and by rule id -- the gate does not merely check the corpus, it reproduces the number the ADR was
decided on, and a drift in either direction means the ADR's record and the corpus have parted.

`repair.never-escalate-furniture` gets its own test, because ADR-4 singles it out: *"one of the
seven is dangerous rather than merely non-compliant ... reading `block.type`, which has no PDF
provider, so without `on_unknown = "match"` the furniture guard is silently off on the PDF path."*
A register that held a total rather than a list could not say that.

## What is deliberately NOT asserted here

`UNCHECKED_FENCES`'s reasons. The gate prints the list with per-language counts on every run, and a
language with neither a parser nor a row FAILS, so the coverage statement is checked by the gate
itself. Restating the reasons here would be the second home INV-21 forbids.

Specified in 11-repo-layout.md section 6.4 and :1575-1600, ADR-4 decisions 1 and 2, and
05-ingest-and-routing.md sections 4.5 and 5.1.
"""

from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path
from types import ModuleType
from typing import Final

import pytest

REPO_ROOT: Final = Path(__file__).resolve().parents[4]
CHARTER_D4_FENCE: Final = 2576
"""The opening line of the charter's section D4 ` ```toml ` fence, which ADR-4 retires."""
A2_LINE: Final = 2739
"""ADR-4 decision 1(b)'s one newline-spanning inline table: the `when` of the furniture rule."""


def _load() -> ModuleType:
    """Load `tools/gate_docs.py` by path. `tools/` is not a package and is not installed."""
    path = REPO_ROOT / "tools" / "gate_docs.py"
    spec = importlib.util.spec_from_file_location("gate_docs_under_test", path)
    if spec is None or spec.loader is None:  # pragma: no cover - a real path, a real loader
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    #  Registered before execution: the module body defines dataclasses, and `@dataclass` resolves
    #  `sys.modules[__name__]` through `__module__`, which gives `AttributeError` if it is absent.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gd: Final = _load()


@pytest.fixture
def document(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """One fixture document, with the gate's scope narrowed to it.

    `REPO` moves too, so a failure message names a path relative to `tmp_path` and no test reads
    this repository's own documents by accident.
    """
    made = tmp_path / "99-fixture.md"
    made.write_text("", encoding="utf-8", newline="\n")
    monkeypatch.setattr(gd, "REPO", tmp_path)
    monkeypatch.setattr(gd, "documents", lambda: (made,))
    monkeypatch.setattr(gd, "policy_documents", lambda: (made,))
    monkeypatch.setattr(gd, "FENCE_FLOOR", 0)
    monkeypatch.setattr(gd, "TOML_FENCE_FLOOR", 0)
    monkeypatch.setattr(gd, "PARSE_EXEMPT", ())
    monkeypatch.setattr(gd, "A2_EXPECTED", ())
    monkeypatch.setattr(gd, "A3_EXPECTED", ())
    return made


def fence(language: str, body: str) -> str:
    return f"```{language}\n{body}\n```\n"


def headlines(findings: list[object]) -> str:
    return "\n".join(str(getattr(one, "headline", one)) for one in findings)


#  ---------------------------------------------------------------------------------------------
#  The corpus as committed


def test_the_real_corpus_passes_every_clause() -> None:
    """Rule 2, and the load-bearing case: every document the gate reads is frozen, so the only
    thing that can change is the gate."""
    assert gd.main([]) == 0


def test_the_scope_is_the_record_and_not_the_deliberation() -> None:
    """93 of `_notes/panels/`'s fences do not parse and every one is a faithful quotation of a
    partial snippet. A gate over them would be an instruction to falsify the record."""
    scope = {path.relative_to(REPO_ROOT).as_posix() for path in gd.documents()}
    assert "docs/plan/_notes/charter.md" in scope, "a2 and a3 are worded over the charter"
    assert "docs/plan/01-principles.md" in scope
    assert "docs/ARCHITECTURE.md" in scope
    assert not [one for one in scope if "_notes/panels" in one or "_notes/rulings" in one]
    assert all((REPO_ROOT / one).is_file() for one in scope)
    policy = {path.relative_to(REPO_ROOT).as_posix() for path in gd.policy_documents()}
    assert policy <= scope, "a2's scope cannot reach a document clause (a) does not parse"


def test_the_charter_and_the_nineteen_hold_the_fence_count_adr_four_measured() -> None:
    """ADR-4 decision 1: *"all seventy-three ` ```toml ` fences in the charter and in 00-18
    parse."* Seventy-four now -- 01-principles.md section 1e's `tools/invariants.toml` example was
    written by ADR-2, after ADR-4 took its count -- and the gate's floor says so in its docstring
    rather than carrying the stale number."""
    toml_fences = [
        one
        for document in gd.policy_documents()
        for one in gd.fences(document)
        if one.language == "toml"
    ]
    assert len(toml_fences) == 74
    assert len(toml_fences) >= gd.TOML_FENCE_FLOOR


#  ---------------------------------------------------------------------------------------------
#  Clause (a)


def test_a_fence_that_does_not_parse_fails_and_names_its_parser(document: Path) -> None:
    document.write_text(fence("toml", "key = [1, 2"), encoding="utf-8", newline="\n")
    _report, findings = gd.check_clause_a()
    assert "is a ` ```toml ` fence that does not parse" in headlines(findings)
    assert "TOMLDecodeError" in headlines(findings)


def test_each_of_the_three_parsers_is_wired_to_its_own_language(document: Path) -> None:
    for language, broken in (("toml", "a ="), ("json", "{"), ("python", "def (:")):
        document.write_text(fence(language, broken), encoding="utf-8", newline="\n")
        _report, findings = gd.check_clause_a()
        assert findings, f"{language} is not actually parsed"
        assert f"```{language} ` fence" in headlines(findings)


def test_a_fence_language_with_neither_a_parser_nor_a_row_fails(document: Path) -> None:
    """The coverage statement is the clause's weakest point, so an unlisted language is a finding
    rather than a silent skip."""
    document.write_text(fence("cobol", "DISPLAY 'HI'."), encoding="utf-8", newline="\n")
    _report, findings = gd.check_clause_a()
    assert "neither a parser nor a row in UNCHECKED_FENCES" in headlines(findings)


def test_a_listed_unchecked_language_is_counted_and_not_checked(document: Path) -> None:
    document.write_text(fence("sql", "SELECT FROM WHERE ;;"), encoding="utf-8", newline="\n")
    report, findings = gd.check_clause_a()
    assert findings == []
    assert "sql 1" in "\n".join(report)


def test_the_fence_floor_makes_every_finding_below_it_vacuous_rather_than_absent(
    document: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Clause d0's lesson. A scanner that matched nothing would report nothing and exit 0."""
    monkeypatch.setattr(gd, "FENCE_FLOOR", 5)
    document.write_text(fence("toml", "a = 1"), encoding="utf-8", newline="\n")
    _report, findings = gd.check_clause_a()
    assert "the fence scanner matched 1 fence(s), floor is 5." in headlines(findings)
    assert "vacuous" in "\n".join(one.render() for one in findings)


def test_a_parse_exemption_that_parses_now_fails_so_the_list_shrinks(
    document: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        gd, "PARSE_EXEMPT", (("99-fixture.md", 1, 2, "a reason nobody needs any more"),)
    )
    document.write_text(fence("toml", "a = 1"), encoding="utf-8", newline="\n")
    _report, findings = gd.check_clause_a()
    assert "PARSE_EXEMPT 99-fixture.md:1 parses now" in headlines(findings)


def test_a_parse_exemption_silences_exactly_its_own_locus(
    document: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gd, "PARSE_EXEMPT", (("99-fixture.md", 1, 2, "the first fence"),))
    document.write_text(fence("toml", "a =") + fence("toml", "b ="), encoding="utf-8", newline="\n")
    _report, findings = gd.check_clause_a()
    assert len(findings) == 1
    assert "99-fixture.md:4" in headlines(findings), "the SECOND fence still fails"


def test_every_parse_exemption_is_a_real_finding_and_no_row_is_a_placeholder() -> None:
    """The allow-list is the dangerous part. Each row has to be a locus that really does not parse,
    its `why` has to say something, and the loci have to be distinct."""
    assert len(gd.PARSE_EXEMPT) == 11
    loci = [(path, line) for path, line, _offending, _why in gd.PARSE_EXEMPT]
    assert len(set(loci)) == len(loci)
    for path, line, offending, why in gd.PARSE_EXEMPT:
        target = REPO_ROOT / path
        assert target.is_file(), path
        lines = target.read_text(encoding="utf-8").splitlines()
        assert lines[line - 1].strip().startswith("```"), f"{path}:{line} is not a fence opener"
        assert 0 < offending <= len(lines), f"{path}:{offending}"
        assert offending > line, "the offending line is inside the fence, below its opener"
        assert len(why) > 12, f"{path}:{line} has a placeholder reason"
    #  The real run proves the other direction: a row that parses now fails the gate.
    assert gd.check_clause_a()[1] == []


#  ---------------------------------------------------------------------------------------------
#  Clause (a2)


def test_a_line_ending_inside_braces_fails_even_though_the_fence_parses(document: Path) -> None:
    """The clause's whole reason: `tomllib` accepts this and always would have."""
    body = 'when = { "block.type" = { in = ["a",\n                               "b"] } }'
    assert tomllib.loads(body), "the fixture has to be LEGAL toml or it tests clause (a)"
    document.write_text(fence("toml", body), encoding="utf-8", newline="\n")
    _report, findings = gd.check_clause_a2()
    assert "99-fixture.md:2 ends at brace depth 2" in headlines(findings)


def test_a_brace_inside_a_comment_or_a_string_is_not_a_brace(document: Path) -> None:
    body = "\n".join(
        (
            "a = 1  # { this brace is a comment",
            'b = "{ this one is a basic string"',
            "c = '{ this one is a literal string'",
            'd = """',
            "{ and this one spans lines",
            '"""',
            "e = 2",
        )
    )
    assert tomllib.loads(body)
    document.write_text(fence("toml", body), encoding="utf-8", newline="\n")
    _report, findings = gd.check_clause_a2()
    assert findings == [], headlines(findings)


def test_a_backslash_escape_is_honoured_in_a_basic_string_and_not_in_a_literal_one() -> None:
    r"""`'c:\path\'` is a complete TOML literal string: literal strings have no escapes. Treating
    the two alike would swallow the rest of the line and lose every brace on it."""
    depth, multiline = gd._walk_line(r"a = 'c:\path\' , b = {", 0, None)
    assert multiline is None
    assert depth == 1, "the brace after the literal string has to be seen"
    depth, _multiline = gd._walk_line(r'a = "he said \" { \" " , b = 1', 0, None)
    assert depth == 0, "the brace inside the escaped quotes is inside the string"


def test_a_closed_line_is_not_a_finding_however_deep_it_went(document: Path) -> None:
    document.write_text(
        fence("toml", "a = { b = { c = 1 } }\nd = 2"), encoding="utf-8", newline="\n"
    )
    _report, findings = gd.check_clause_a2()
    assert findings == []


def test_an_a2_expectation_that_closes_now_fails_so_the_list_shrinks(
    document: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gd, "A2_EXPECTED", (("99-fixture.md", 2, "retired law"),))
    document.write_text(fence("toml", "a = { b = 1 }"), encoding="utf-8", newline="\n")
    _report, findings = gd.check_clause_a2()
    assert "A2_EXPECTED 99-fixture.md:2 no longer ends at depth >= 1" in headlines(findings)


def test_the_one_expected_a2_finding_is_adr_fours_measurement_by_locus() -> None:
    """ADR-4 decision 1(b): *"One inline table spans a newline, not two, and it is a `when` rather
    than a `then`."* One row, in the retired fence, and the line still reads as a `when`."""
    assert len(gd.A2_EXPECTED) == 1
    path, line, why = gd.A2_EXPECTED[0]
    assert path == "docs/plan/_notes/charter.md"
    assert line == A2_LINE
    assert "E42" in why, "the row has to name the erratum that retires the fence it is in"
    text = (REPO_ROOT / path).read_text(encoding="utf-8").splitlines()[line - 1]
    assert text.lstrip().startswith("when ="), text
    assert gd.check_clause_a2()[1] == [], "and it is the only one"


#  ---------------------------------------------------------------------------------------------
#  Clause (a3) - the standalone check 4


def test_a_rule_reading_a_nullable_key_without_on_unknown_fails(
    document: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gd, "nullability", lambda: {"block.type": True})
    body = '[[rule]]\nid = "r1"\nwhen = { "block.type" = { in = ["a"] } }\n'
    document.write_text(fence("toml", body), encoding="utf-8", newline="\n")
    _report, findings = gd.check_clause_a3()
    assert "rule 'r1' reads nullable block.type and declares no `on_unknown` (OW-P-004)" in (
        headlines(findings)
    )


def test_declaring_on_unknown_satisfies_check_four(
    document: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gd, "nullability", lambda: {"block.type": True})
    body = '[[rule]]\nid = "r1"\non_unknown = "match"\nwhen = { "block.type" = { in = ["a"] } }\n'
    document.write_text(fence("toml", body), encoding="utf-8", newline="\n")
    _report, findings = gd.check_clause_a3()
    assert findings == []


def test_an_exists_only_when_does_not_need_on_unknown(
    document: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Check 4's own exception, in its own words: *"a rule whose `when` is `exists`-only does not
    need one."* An `exists` test cannot read UNKNOWN."""
    monkeypatch.setattr(gd, "nullability", lambda: {"block.type": True})
    body = '[[rule]]\nid = "r1"\nwhen = { "block.type" = { exists = true } }\n'
    document.write_text(fence("toml", body), encoding="utf-8", newline="\n")
    _report, findings = gd.check_clause_a3()
    assert findings == []


def test_a_non_nullable_key_needs_nothing(document: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gd, "nullability", lambda: {"unit.format": False})
    body = '[[rule]]\nid = "r1"\nwhen = { "unit.format" = { in = ["pdf"] } }\n'
    document.write_text(fence("toml", body), encoding="utf-8", newline="\n")
    _report, findings = gd.check_clause_a3()
    assert findings == []


def test_the_combinators_are_descended_into() -> None:
    """How the set was found: a walk that missed `all_of` reported six check-4 failures where
    ADR-4 measured seven, because `regen.output-invalid` reads its five keys through one."""
    nested = {"all_of": [{"a.b": {"gt": 1}}, {"any_of": [{"c.d": {"exists": True}}]}]}
    assert sorted(key for key, _clause in gd.signal_keys_read(nested)) == ["a.b", "c.d"]
    assert {"all_of", "any_of"} <= gd.COMBINATORS


def test_an_a3_expectation_that_passes_now_fails_so_the_list_shrinks(
    document: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gd, "nullability", lambda: {"block.type": True})
    monkeypatch.setattr(gd, "A3_EXPECTED", (("99-fixture.md", 1, "r1", "block.type"),))
    body = '[[rule]]\nid = "r1"\non_unknown = "match"\nwhen = { "block.type" = { in = ["a"] } }\n'
    document.write_text(fence("toml", body), encoding="utf-8", newline="\n")
    _report, findings = gd.check_clause_a3()
    assert "A3_EXPECTED 99-fixture.md:1 'r1' passes check 4 now" in headlines(findings)


def test_a_vacuous_null_column_is_a_finding_and_not_a_pass(
    document: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The column is load-bearing for this gate as well as for the linter (ADR-4 decision 2), so a
    table that stops parsing has to fail rather than make check 4 silently universal."""
    monkeypatch.setattr(gd, "nullability", dict)
    document.write_text(fence("toml", '[[rule]]\nid = "r1"\n'), encoding="utf-8", newline="\n")
    _report, findings = gd.check_clause_a3()
    assert "section 5.1's `null` column parsed to nothing" in headlines(findings)


def test_the_null_column_is_read_out_of_the_table_and_finds_both_values() -> None:
    null = gd.nullability()
    assert len(null) == 54, "section 5.1's registry rows"
    assert sum(null.values()) == 41
    assert null["block.type"] is True
    assert null["unit.format"] is False, "a bolded `**no**` cell reads as no"


def test_the_seven_expected_findings_are_adr_fours_measurement_rule_by_rule() -> None:
    """ADR-4 decision 1(a): seven in the charter's retired fence, **zero** in section 4.4's
    forty."""
    assert len(gd.A3_EXPECTED) == 7
    assert {path for path, _line, _rule, _key in gd.A3_EXPECTED} == {
        "docs/plan/_notes/charter.md"
    }, "every one is in the retired fence; section 4.4's forty pass"
    assert {line for _path, line, _rule, _key in gd.A3_EXPECTED} == {CHARTER_D4_FENCE}
    rules = [rule for _path, _line, rule, _key in gd.A3_EXPECTED]
    assert len(set(rules)) == 7, "one row per rule"
    assert gd.check_clause_a3()[1] == [], "and they are the only seven"


def test_the_dangerous_one_of_the_seven_is_identifiable_in_the_register() -> None:
    """ADR-4 singles it out: *"one of the seven is dangerous rather than merely non-compliant,
    `repair.never-escalate-furniture` reading `block.type`, which has no PDF provider, so without
    `on_unknown = "match"` the furniture guard is silently off on the PDF path and one flagged
    footer spawns the inference server for a clean document."* A register holding a total could not
    say that, which is why the rows are `(id, key)` pairs."""
    rows = {rule: key for _path, _line, rule, key in gd.A3_EXPECTED}
    assert rows["repair.never-escalate-furniture"] == "block.type"
    assert gd.nullability()["block.type"] is True


def test_section_four_fours_forty_rules_are_the_zero_half_of_the_measurement() -> None:
    """The other side of decision 1(a), computed rather than asserted: the fence that replaces the
    retired one has forty rules and no check-4 finding."""
    found = {
        one.where: rules
        for one, rules in gd.rule_fences()
        if one.document.name == "05-ingest-and-routing.md"
    }
    assert len(found) == 1
    assert len(next(iter(found.values()))) == 40
    assert not [row for row in gd.A3_EXPECTED if "05-ingest" in row[0]]


#  ---------------------------------------------------------------------------------------------
#  Clause (c), and the two clauses this script does not carry


def test_clause_c_is_read_from_the_register_and_is_off() -> None:
    report, findings = gd.clause_c_state()
    assert findings == []
    assert "registered and OFF, blocked_by ADR-1" in "\n".join(report)


def test_enabling_clause_c_in_the_register_fails_until_the_clause_is_implemented(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-1 decision 6 puts the clause here with `enabled = false` so its absence is visible. A
    register that turns it on while nothing runs it would be the opposite."""
    register = tmp_path / "gates.toml"
    register.write_text(
        '[[gate]]\nid = "G27"\n[[gate.clause]]\nid = "c"\nasserts = "x"\nenabled = true\n',
        encoding="utf-8",
        newline="\n",
    )
    monkeypatch.setattr(gd, "GATES", register)
    _report, findings = gd.clause_c_state()
    assert "clause (c) is enabled in the register and this script does not run it" in headlines(
        findings
    )


def test_the_register_row_moved_this_script_from_planned_to_runner() -> None:
    """tools/gates.toml's forcing function: landing a runner forces a register edit rather than
    leaving a row pointing at a file nobody wrote."""
    gates = tomllib.loads((REPO_ROOT / "tools" / "gates.toml").read_text(encoding="utf-8"))
    row = next(one for one in gates["gate"] if str(one["id"]) == "G27")
    assert "tools/gate_docs.py" in row["runner"]
    assert "tools/gate_migrations.py" in row["runner"], "clause (b) stays where it is"
    assert "runner_planned" not in row
    for clause in row["clause"]:
        if str(clause["id"]) in {"a", "a2", "a3", "c", "d"}:
            assert clause["runner"] == ["tools/gate_docs.py"]


def test_the_gate_says_which_clause_it_does_not_carry(capsys: pytest.CaptureFixture[str]) -> None:
    """A check that bounds its own coverage says what it dropped, on its own line.

    Clause (d)'s line came out at D995, which is this test's own ratchet: it asserted
    `clause (d)  NOT IN THIS SCRIPT` until the d0-d4 walk landed, and now asserts the opposite in
    both directions. Clause (b) stays named, because `tools/gate_migrations.py` carries it and a
    reader of this script's output should not have to infer that.
    """
    assert gd.main([]) == 0
    printed = capsys.readouterr().out
    assert "clause (b)  NOT IN THIS SCRIPT" in printed
    assert "clause (d)  NOT IN THIS SCRIPT" not in printed, "d0-d4 landed at D995"
    for clause in ("(a)", "(a2)", "(a3)", "(c)", "(d0)", "(d1)", "(d2)", "(d3)", "(d4)"):
        assert f"clause {clause}" in printed, clause


#  ---------------------------------------------------------------------------------------------
#  Clause (d) - d0 the walk found something, d1 symbols, d2 registers, d3 links, d4 the count


@pytest.fixture
def walk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """One fixture document, with clause (d)'s walk narrowed to it and every list emptied."""
    made = tmp_path / "99-walk.md"
    made.write_text("", encoding="utf-8", newline="\n")
    #  `REPO` stays pointed at the repository: every register d2 resolves against lives there, and
    #  a fixture that moved it would be exercising a gate with no registers. `_where` is what lets
    #  a document outside the tree still produce a locus. `ROOTS` is emptied because d0's
    #  roots-present assertion is about the real corpus, not about a one-line fixture.
    monkeypatch.setattr(gd, "walk_documents", lambda: (made,))
    monkeypatch.setattr(gd, "ROOTS", ())
    monkeypatch.setattr(gd, "D1_DECLARED", ())
    monkeypatch.setattr(gd, "D2_PLANNED_PATHS", frozenset())
    monkeypatch.setattr(gd, "D2_NON_OVERRIDE_ENV", frozenset())
    monkeypatch.setattr(gd, "D2_UNDOCUMENTED_KEYS", frozenset())
    monkeypatch.setattr(gd, "_register_value", lambda _key: 0)
    return made


#  --- d0 and d1 ---------------------------------------------------------------------------------


def test_the_real_walk_resolves_every_symbol_it_checks() -> None:
    """Rule 2 for clause (d): the corpus is frozen, so the only thing that can change is d1."""
    _report, findings = gd.check_clause_d1()
    assert findings == [], headlines(findings)


def test_d0s_floor_is_met_only_with_the_import_expansion() -> None:
    """The floor's own job. Section 8.6 counts "588 dotted names plus 32 names expanded out of
    `from <root> import (...)` lines", and over this corpus the two halves are 503 and 45. A d1
    that skipped the expansion comes in at 503 against a floor of 520 and FAILS rather than
    passing quietly -- which is why the expansion cannot be dropped as an optimisation."""
    report, _findings = gd.check_clause_d1()
    checked = int(report[0].split()[2])
    expanded = sum(len(gd.expanded_imports(one)) for one in gd.walk_documents())
    floor = gd._register_value("symbol_floor")
    assert checked >= floor
    assert expanded > 0
    assert checked - expanded < floor, (
        "if this ever holds the other way the floor has stopped forcing the expansion, and the "
        "number to raise is symbol_floor"
    )


def test_a_symbol_that_does_not_resolve_fails_and_names_the_locus(walk: Path) -> None:
    walk.write_text("See `omniweave_core.retrieve.nosuch`.\n", encoding="utf-8", newline="\n")
    _report, findings = gd.check_clause_d1()
    assert "99-walk.md:1 omniweave_core.retrieve.nosuch does not resolve." in headlines(findings)


def test_a_filename_is_not_a_symbol(walk: Path) -> None:
    """d1's first rule. Every one of these matches section 8.6's own regex and none is a module."""
    walk.write_text(
        "`omniweave.toml`, `omniweave.index.lock`, `omniweave.toml.example`, `omniweave.d.ts`\n",
        encoding="utf-8",
        newline="\n",
    )
    report, findings = gd.check_clause_d1()
    assert findings == [], headlines(findings)
    assert "a path, by its tail 4" in "\n".join(report)


def test_an_entry_point_group_is_not_a_module(walk: Path) -> None:
    """d1's second rule, read from the workspace rather than listed in the script."""
    groups = gd.entry_point_groups()
    assert "omniweave.drivers" in groups, "the workspace declares it; the gate reads it"
    assert not gd._resolve_dotted("omniweave.drivers"), "and importing it is the wrong question"
    walk.write_text("`omniweave.drivers`\n", encoding="utf-8", newline="\n")
    report, findings = gd.check_clause_d1()
    assert findings == []
    assert "an entry-point group 1" in "\n".join(report)


def test_the_roadmap_escape_is_a_scheduled_row_and_not_an_allowlist(walk: Path) -> None:
    """Section 8.6 makes the escape "a declared-and-not-yet-built row in 16-roadmap.md's milestone
    table ... not a comment or an allowlist file, so an unbuilt symbol is always also a scheduled
    one". The fixture names a symbol the roadmap names and one it does not."""
    roadmap = (gd.PLAN / "16-roadmap.md").read_text(encoding="utf-8")
    assert "omniweave.backends" in roadmap, "an unbuilt symbol the roadmap schedules"
    assert not gd._resolve_dotted("omniweave.backends")
    walk.write_text(
        "`omniweave.backends` and `omniweave_core.nowhere.NoSuchThing`\n",
        encoding="utf-8",
        newline="\n",
    )
    _report, findings = gd.check_clause_d1()
    assert len(findings) == 1
    assert "omniweave_core.nowhere.NoSuchThing" in headlines(findings)


def test_the_roadmap_escape_matches_the_whole_name_and_not_a_prefix(walk: Path) -> None:
    """Section 8.6's own failure example is the argument. It prints
    `omniweave_core.retrieve.rerank` as what a d1 finding looks like, and that name's prefix is a
    real built module -- so an escape that matched a prefix would let the plan's own example pass.
    The escape is the exact dotted name, which is also what "a row declaring the symbol" means.

    `omniweave_core.out` is the fixture because the roadmap names it in two rows and does not name
    any attribute of it."""
    roadmap = (gd.PLAN / "16-roadmap.md").read_text(encoding="utf-8")
    assert "omniweave_core.out" in roadmap
    assert "omniweave_core.out.NoSuchThing" not in roadmap
    walk.write_text("`omniweave_core.out.NoSuchThing`\n", encoding="utf-8", newline="\n")
    _report, findings = gd.check_clause_d1()
    assert "omniweave_core.out.NoSuchThing does not resolve." in headlines(findings)


def test_the_import_expansion_checks_each_name_rather_than_discarding_the_line(
    walk: Path,
) -> None:
    """Section 8.6: "a `from <root> import (A, B)` line in a fenced `python` block is expanded to
    `root.A`, `root.B`, `root.C` before the check, so an import list is verified name by name
    rather than discarded as one bare root"."""
    walk.write_text(
        "```python\nfrom omniweave_ports import CostClass, NoSuchName\n```\n",
        encoding="utf-8",
        newline="\n",
    )
    names = [name for name, _line in gd.expanded_imports(walk)]
    assert names == ["omniweave_ports.CostClass", "omniweave_ports.NoSuchName"]
    _report, findings = gd.check_clause_d1()
    assert len(findings) == 1
    assert "omniweave_ports.NoSuchName" in headlines(findings)


def test_the_expansion_survives_a_fence_that_does_not_parse(walk: Path) -> None:
    """Clause (a) owns the parse failure and has its own declared exceptions. Dropping those
    fences here would silently lose their import lines, and 18-api-sketch.md -- which contributes
    35 of the corpus's 45 -- holds two of the eleven."""
    walk.write_text(
        "```python\nclass X: a=1\n       b=2\nfrom omniweave_ports import CostClass\n```\n",
        encoding="utf-8",
        newline="\n",
    )
    names = [name for name, _line in gd.expanded_imports(walk)]
    assert names == ["omniweave_ports.CostClass"]


def test_a_declared_row_that_resolves_now_fails_so_the_list_shrinks(
    walk: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        gd, "D1_DECLARED", (("omniweave_core.limits", "99-walk.md:1", "a stale row"),)
    )
    walk.write_text("`omniweave_core.limits`\n", encoding="utf-8", newline="\n")
    _report, findings = gd.check_clause_d1()
    assert "D1_DECLARED omniweave_core.limits resolves now" in headlines(findings)


def test_every_declared_row_says_what_the_name_is_and_none_is_a_placeholder() -> None:
    """The allow-list is the dangerous part, so each row is checked against the document it cites
    and against the four kinds the list is allowed to hold."""
    assert len(gd.D1_DECLARED) == 14
    assert len({one[0] for one in gd.D1_DECLARED}) == 14
    for dotted, where, why in gd.D1_DECLARED:
        path, _, line = where.rpartition(":")
        target = REPO_ROOT / path
        assert target.is_file(), where
        text = target.read_text(encoding="utf-8").splitlines()[int(line) - 1]
        assert dotted in text, f"{where} does not name {dotted}"
        assert len(why) > 20, f"{dotted} has a placeholder reason"
        assert not gd._resolve_dotted(dotted), f"{dotted} resolves; the row is stale"


def test_the_one_drift_row_records_the_right_symbol_beside_the_wrong_one() -> None:
    """02-architecture.md:486 names `omniweave_core.model.DocSink`, which is not where `DocSink`
    is. The row is the only one in the list that says DRIFT, and it carries the right answer, so
    the erratum can be written from the register rather than rediscovered."""
    drift = [one for one in gd.D1_DECLARED if one[2].startswith("DRIFT:")]
    assert len(drift) == 1
    dotted, where, why = drift[0]
    assert dotted == "omniweave_core.model.DocSink"
    assert where.startswith("docs/plan/02-architecture.md:")
    assert "omniweave_core.store.doc.DocSink" in why
    assert gd._resolve_dotted("omniweave_core.store.doc.DocSink"), "the right answer resolves"


#  --- d2 ----------------------------------------------------------------------------------------


def test_the_real_walk_resolves_every_hard_d2_family() -> None:
    _report, findings = gd.check_clause_d2()
    assert findings == [], headlines(findings)


def test_the_nine_invariant_families_resolve_against_the_register_d992_committed() -> None:
    """The strongest single number in clause (d): 1,438 occurrences, zero unresolved. Before
    `tools/invariants.toml` existed, 11-repo-layout.md's own inventory entry said this clause "is
    otherwise unimplementable"."""
    report, _findings = gd.check_clause_d2()
    hard = next(line for line in report if "clause (d2) hard:" in line)
    assert "invariant families 1438" in hard


def test_an_unregistered_gate_or_assertion_or_invariant_fails(walk: Path) -> None:
    walk.write_text(
        "`G999` and `gates.no_such_assertion` and `INV-99` and `M-INV-9`\n",
        encoding="utf-8",
        newline="\n",
    )
    _report, findings = gd.check_clause_d2()
    printed = headlines(findings)
    assert "G999 is not in tools/gates.toml." in printed
    assert "gates.no_such_assertion is not a [[job_assertion]] name." in printed
    assert "INV-99 is not in tools/invariants.toml." in printed
    assert "M-INV-9 is not in tools/invariants.toml." in printed


def test_a_budget_row_is_not_reported_as_an_unregistered_assertion() -> None:
    """`conform.mandatory_tier_s` is `eval/perf.toml`'s and matches the `<job>.<name>` shape. A
    check reading only `tools/gates.toml` reported it five times over the corpus."""
    held = gd._d2_registers()
    assert "conform.mandatory_tier_s" in held.assertions
    assert "gates.invariant_register" in held.assertions


def test_a_filename_is_not_a_job_assertion(walk: Path) -> None:
    """`gates.toml` matches `<job>.<name>` exactly. PATH_TAILS already carries the rule."""
    walk.write_text("`gates.toml` and `eval/gates.toml`\n", encoding="utf-8", newline="\n")
    _report, findings = gd.check_clause_d2()
    assert "gates.toml is not a [[job_assertion]] name" not in headlines(findings)


def test_a_register_path_that_is_neither_a_file_nor_declared_fails(walk: Path) -> None:
    walk.write_text("`tools/no_such_register.toml`\n", encoding="utf-8", newline="\n")
    _report, findings = gd.check_clause_d2()
    assert "tools/no_such_register.toml is neither a file nor a declared planned register" in (
        headlines(findings)
    )


def test_every_planned_register_path_is_still_absent_and_still_cited() -> None:
    """Nineteen registers and scripts the plan names and nothing has written. Both directions: a
    row whose file now exists is stale, and a row no document cites is stale too.

    Twenty until D998, when `tools/risks.toml` landed and this test went red -- which is the row's
    whole purpose, so the fix was to delete it in the commit that created the file."""
    assert len(gd.D2_PLANNED_PATHS) == 19
    corpus = "\n".join(one.read_text(encoding="utf-8") for one in gd.walk_documents())
    for one in sorted(gd.D2_PLANNED_PATHS):
        assert not (REPO_ROOT / one).exists(), f"{one} exists; delete the row"
        assert one in corpus, f"no document cites {one}; delete the row"


def test_an_env_var_that_overrides_nothing_needs_a_row(walk: Path) -> None:
    walk.write_text("`OMNIWEAVE_MADE_UP`\n", encoding="utf-8", newline="\n")
    _report, findings = gd.check_clause_d2()
    assert "OMNIWEAVE_MADE_UP is not a config override and is not declared" in headlines(findings)


def test_the_eight_non_override_env_vars_are_not_in_the_override_map() -> None:
    """`[env]` maps a CONFIG KEY to the variable that overrides it, and all 135 of its rows are
    derived from the key. These eight override nothing, so the map is the wrong home."""
    held = gd._d2_registers()
    assert len(gd.D2_NON_OVERRIDE_ENV) == 8
    assert not (gd.D2_NON_OVERRIDE_ENV & held.overrides)
    corpus = "\n".join(one.read_text(encoding="utf-8") for one in gd.walk_documents())
    for one in sorted(gd.D2_NON_OVERRIDE_ENV):
        assert one in corpus, f"no document names {one}; delete the row"


def test_the_two_ratchets_fail_a_rise_and_an_untightened_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both directions, over the real gaps. A rise means a document started naming something
    nobody scheduled; a ceiling nobody lowered is a number nobody is watching."""
    monkeypatch.setattr(gd, "_register_value", lambda _key: 0)
    _report, findings = gd._d2_ratchets({"ow made up"}, set())
    assert "ow verbs: 1 unresolved against a ceiling of 0." in headlines(findings)
    monkeypatch.setattr(gd, "_register_value", lambda _key: 5)
    _report, findings = gd._d2_ratchets({"ow made up"}, {"OW-X-001"})
    printed = headlines(findings)
    assert "ow verbs: 1 unresolved and the ceiling is still 5." in printed
    assert "OW-* codes: 1 unresolved and the ceiling is still 5." in printed


def test_the_ratchet_ceilings_are_the_measured_gaps_and_live_in_the_register() -> None:
    """Section 8.6 puts d0's floor in `tools/gates.toml` "so raising it is a reviewable act and
    lowering it is visible". The two ceilings are there for the same reason and are measured,
    not chosen: 146 verb spellings against `ACTIONS`' 51, 291 codes against `codes.toml`'s 193."""
    _hard, verb_gap, code_gap, _findings = gd._d2_scan()
    assert len(verb_gap) == gd._register_value("verb_gap_max")
    assert len(code_gap) == gd._register_value("code_gap_max")
    assert gd._register_value("verb_gap_max") > 0, "a ceiling of zero would be a hard check"


def test_the_distribution_count_reports_the_drift_section_eight_six_predicted() -> None:
    """Section 8.6: "a PR adding a fifteenth distribution and forgetting to update the prose fails
    on all three files at once, with the count it found and the count it expected in the message."
    That PR landed. The workspace holds fifteen; the prose says fourteen, and thirteen in the
    excluding-core form. The check asserts the drift is UNIFORM -- one distribution, both forms --
    because anything else is two errors rather than one stale number."""
    report, findings = gd._d2_distributions()
    assert findings == [], headlines(findings)
    line = next(one for one in report if "distributions:" in one)
    disk = len(list((REPO_ROOT / "packages").glob("*/pyproject.toml")))
    assert f"{disk} on disk" in line
    assert gd._register_value("dist_count_disk") == disk
    assert gd._register_value("dist_count_prose") == disk - 1


def test_a_count_in_neither_prose_form_fails(walk: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gd, "_register_value", lambda key: 14 if "prose" in key else 15)
    walk.write_text("twelve distributions\n", encoding="utf-8", newline="\n")
    _report, findings = gd._d2_distributions()
    assert "a document spells a distribution count of [12]" in headlines(findings)


def test_the_config_key_check_runs_in_the_decidable_direction_only() -> None:
    """NOT "every `[section] key` in prose resolves": that spelling is shared by a config key, a
    DriverCard field and a policy block, and 73 of 134 matches over this corpus are card fields.
    The decidable direction is the register's own."""
    report, findings = gd._d2_config_keys()
    assert findings == [], headlines(findings)
    assert "135 in the register" in "\n".join(report)
    assert len(gd.D2_UNDOCUMENTED_KEYS) == 5


def test_a_register_key_no_document_names_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gd, "D2_UNDOCUMENTED_KEYS", frozenset())
    _report, findings = gd._d2_config_keys()
    assert "config key(s) no document names" in headlines(findings)


#  --- d3 ----------------------------------------------------------------------------------------


def test_every_relative_link_and_section_reference_in_the_walk_resolves() -> None:
    """3,176 links and 1,793 section cross-references, zero unresolved. D991's move is what made
    this true: its commit computed the transitive link closure rather than picking documents."""
    report, findings = gd.check_clause_d3()
    assert findings == [], headlines(findings)
    line = report[0]
    assert "3176 relative link(s)" in line
    assert "1793 section cross-reference(s)" in line


def test_a_dangling_relative_link_fails(walk: Path) -> None:
    walk.write_text("[gone](no-such-file.md)\n", encoding="utf-8", newline="\n")
    _report, findings = gd.check_clause_d3()
    assert "links to no-such-file.md, which does not exist." in headlines(findings)


def test_a_section_reference_to_a_heading_that_does_not_exist_fails(walk: Path) -> None:
    target = walk.parent / "98-target.md"
    target.write_text("## 1.1 Here\n", encoding="utf-8", newline="\n")
    walk.write_text("[t](98-target.md) section 9.9\n", encoding="utf-8", newline="\n")
    _report, findings = gd.check_clause_d3()
    assert "cites 98-target.md section 9.9, which has no heading." in headlines(findings)


def test_a_section_reference_resolves_against_a_family_of_headings(walk: Path) -> None:
    """The prefix rule, and it is not a loosening. 08-runtime.md numbers its headings `### 1.1`
    under a `## Part 1` title and has no `## 1` at all, so a reference to its section 1 names the
    section-1 family. An equality test reports four findings over the real corpus and every one of
    them is a correct reference."""
    target = walk.parent / "98-target.md"
    target.write_text("## Part 1\n\n### 1.1 Here\n", encoding="utf-8", newline="\n")
    walk.write_text("[t](98-target.md) section 1\n", encoding="utf-8", newline="\n")
    _report, findings = gd.check_clause_d3()
    assert findings == []


#  --- d4 ----------------------------------------------------------------------------------------


def test_d4_emits_the_count_as_the_counter_section_eight_six_names() -> None:
    report, findings = gd.check_clause_d4(548)
    assert findings == []
    assert "docs_symbols_checked = 548" in report[0]
    assert gd.COUNTER == "docs_symbols_checked"


def test_the_counter_row_exists_and_ratchets_the_rise_while_the_floor_holds_the_fall() -> None:
    """Both directions, by different mechanisms, and that is the point. `ratchet` fails a RISE,
    which is section 8.6's prose-noise worry; the FALL -- "a document that stops naming things to
    make the gate quiet" -- is `symbol_floor`. One count, two questions, no second home."""
    counters = tomllib.loads((REPO_ROOT / "eval" / "counters.toml").read_text(encoding="utf-8"))
    row = next(one for one in counters["counter"] if one["id"] == gd.COUNTER)
    assert row["class"] == "ratchet"
    assert 0 < row["tolerance"] < 1
    assert row["source"] == "ci"
    assert gd._register_value("symbol_floor") > 0


def test_a_missing_counter_row_is_a_finding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gd, "COUNTER", "no_such_counter")
    _report, findings = gd.check_clause_d4(1)
    assert "eval/counters.toml holds no `no_such_counter` row." in headlines(findings)


def test_a_stray_argument_is_a_usage_error_and_not_a_pass() -> None:
    assert gd.main(["--fix"]) == 2
