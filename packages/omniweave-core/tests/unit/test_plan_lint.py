"""`tools/plan_lint.py` against deliberate violations, because that is the whole point of it.

`_plan/_notes/build-defects.md` C55 (:5935-5984) is the row this file answers, and its closing
rule is the file's structure: *"before citing a command as evidence, run it against a deliberate
violation and check that it fails. `git diff` over an ignored path, a grep whose pattern cannot
match, a gate that skips on this platform (D114) and a test downstream of a call that never
returns (C41) are the same defect wearing four costumes -- a check that reports success because
it never looked."*

So every rule of `ow plan lint` is exercised **against a mutation that must fail it**, and the
mutations run against a FIXTURE tree built in `tmp_path` and never against the real `_plan/`. That
is why `plan_lint` takes the plan root as a parameter: a test that mutated settled law to prove
settled law is protected would be the defect it is testing for.

## The assertion this whole wave is about

`test_git_diff_over_the_ignored_plan_is_empty_while_the_gate_is_non_zero` initialises a real git
repository whose `.gitignore` holds the plan directory, commits it, mutates one byte of a settled
document, and asserts three things at once: `git diff HEAD -- <plan>/` prints nothing,
`git status --porcelain -- <plan>/` prints nothing, and `plan_lint.main()` returns `EXIT_FAIL`.
That is the measurement C55 recorded, reproduced, with a detector on the other side of it.

`test_the_manifest_is_not_itself_gitignored` is the correction C55 missed: its own proposal is
"one `_plan/PLAN.sha256`", and a manifest at that path would be matched by `.gitignore:3` and be
exactly as invisible as the thing it protects.

## The failure mode the region definition did NOT pick

`charter-frozen` digests everything strictly above the unique `## 9.` heading rather than a fixed
line count. `test_a_line_appended_at_the_end_of_section_eight_fails_where_a_fixed_count_would_not`
inserts a line immediately above the heading and asserts both halves in one test: the anchored
digest moves and the gate fails, and a digest over the ORIGINAL line count is byte-identical
before and after -- so the design that was not chosen would have passed. The test named
`test_a_second_section_nine_heading_fails_instead_of_silently_shrinking_the_region` covers the
anchored design's own failure mode from the other side.

## The allow-list, which is the part that can switch the gate off

`WRITABLE_NOTES` is checked twice over the REAL plan, following
`test_core_eager_surface.py`'s `FILLED_HOMES` and `test_p2_freeze.py`'s `FROZEN_SURFACES`: no row
is a placeholder (the path exists, the reason is a real sentence naming a writer, and the file was
written after every settled document was), and no row could ever name settled law. The covered
set is asserted to be a partition of the real tree, so a file in neither the manifest nor the
allow-list is a failure and not an escape.

Specified in `_plan/_notes/charter.md:8687-8689`, `:8711-8737`, `:8762` (E-Q2),
`_plan/18-api-sketch.md:3227-3252` and `_plan/_notes/build-defects.md:5935-5984` (C55).
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import re
import shutil
import subprocess  # noqa: TID251 -- a real `git diff` over a real ignored path IS the subject.
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Final

import pytest
from omniweave.surface import CLI_ABSENT, CLI_UNROSTERED
from omniweave_core import errors

REPO_ROOT: Final = Path(__file__).resolve().parents[4]
REAL_PLAN: Final = REPO_ROOT / "_plan"
REAL_MANIFEST: Final = REPO_ROOT / "tools" / "plan.sha256"
API_SKETCH: Final = REAL_PLAN / "18-api-sketch.md"
REAL_CHARTER: Final = REAL_PLAN / "_notes" / "charter.md"


def _load() -> ModuleType:
    """`tools/` is not an importable package, so the module is loaded by path.

    `tests/unit/test_gate_coldstart.py` and `test_gate_crash.py` take the same route for the same
    reason: the scripts are runnable files under `tools/`, not distribution modules.
    """
    path = REPO_ROOT / "tools" / "plan_lint.py"
    spec = importlib.util.spec_from_file_location("plan_lint_under_test", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


pl: Final = _load()


# ---------------------------------------------------------------------------
# The fixture plan tree. Never the real one.
# ---------------------------------------------------------------------------

# A charter small enough to read and shaped exactly like the real one where it matters: eight
# sections whose bytes are frozen, a `## 9.` heading whose line number is the boundary, a 9.2
# table of six-column rows with an anchor and a quoted phrase each, and a 9.4 that may grow.
#
# `OW-A-002  OW_FIXTURE_RETIRED` in section 1 is the E3 row's subject: it stands in for the real
# `OW-A-021` / `OW_INSTRUCTION_SHAPED_TEXT` pair, so the superseded-binding path is exercised
# without depending on the real charter's content.
FIXTURE_CHARTER: Final = """\
# The fixture charter

## 1. What this is

The first fixture sentence, which E1 quotes and which no later section may edit.

    OW-A-001  OW_FIXTURE_ALPHA
    OW-A-002  OW_FIXTURE_RETIRED

## 8. What a reviewer should reject

A second fixture sentence, which E2 quotes.

## 9. Errata -- the three statements above that the plan now supersedes

**Sections 1-8 are unchanged. Deliberately.** No line of 1-8 was edited, and none will be.

### 9.1 How to find out that a line you are reading is superseded

Each row quotes the charter's own distinctive phrase.

### 9.2 The record

| # | charter locus | search for this phrase | what it says | what supersedes it | why |
|---|---|---|---|---|---|
| <a id="e1"></a>**E1** | :5 | `The first fixture sentence` | one | two | three |
| <a id="e2"></a>**E2** | :12 | `A second fixture sentence` | one | two | three |
| <a id="e3"></a>**E3** | :8 | `OW-A-002  OW_FIXTURE_RETIRED` | one | two | three |

### 9.3 Checked and **not** superseded

Nothing else was reported stale.

### 9.4 Open questions on this record

| # | Open question | What closes it | Pre-committed fallback |
|---|---|---|---|
| **E-Q2** | Is there a check? | A `ow plan lint` rule. | The phrase is the locus. |
"""

FIXTURE_CLI_DOC: Final[str] = "# Interfaces\n\n" + "".join(
    f"- `ow {' '.join(spelling)}` is written down here so `cli-verbs` can see it.\n"
    for spelling in (*CLI_ABSENT, *CLI_UNROSTERED)
)
"""One line per exception-register row, GENERATED from the registers rather than typed.

`cli-verbs` fails on a register row no document writes, which is the ratchet that stops
`CLI_UNROSTERED` becoming a permanent excuse list. A fixture tree carrying none of those
sentences would fail every run against it for a reason that has nothing to do with the rule
under test, so the fixture writes them -- and GENERATING the document means a row added to
either register cannot make this fixture stale, which is the same reason `build_plan` already
iterates `WRITABLE_NOTES` instead of re-listing it.
"""

FIXTURE_DOCS: Final[dict[str, str]] = {
    "10-interfaces.md": FIXTURE_CLI_DOC,
    "00-vision.md": "# Vision\n\nV10-17 is a release criterion.\n",
    "01-principles.md": "# Principles\n\n`OW-A-002` `OW_FIXTURE_LIVE` is the live spelling.\n",
    "README.md": "# The fixture plan\n\nTwo documents, one charter.\n",
    "glossary.md": "# Glossary\n\nNothing is defined here.\n",
    "adr/0001-a-decision.md": "# ADR-1\n\nDecided.\n",
    "_notes/terminology.md": "# Terminology\n\nOne name per concept.\n",
}


def build_plan(root: Path) -> Path:
    """A fixture plan tree: settled documents, a charter, and every allow-listed working file.

    The writable files are created by ITERATING `WRITABLE_NOTES` rather than by re-listing it, so
    a row added to the allow-list cannot make this fixture stale.
    """
    for rel, text in FIXTURE_DOCS.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
    charter = root / pl.CHARTER_REL
    charter.parent.mkdir(parents=True, exist_ok=True)
    charter.write_text(FIXTURE_CHARTER, encoding="utf-8", newline="\n")
    for rel in pl.WRITABLE_NOTES:
        working = root / rel
        working.parent.mkdir(parents=True, exist_ok=True)
        working.write_text(f"# {rel}\n\nThis project writes this file every wave.\n", "utf-8")
    return root


def bless(plan: Path, manifest: Path, reason: str = "fixture") -> str:
    """Bless the fixture and return what `--bless` printed."""
    out = io.StringIO()
    code = pl.main(
        ["--plan-root", str(plan), "--manifest", str(manifest), "--bless", "--reason", reason],
        out=out,
    )
    assert code == pl.EXIT_CLEAN, out.getvalue()
    return out.getvalue()


def run(plan: Path, manifest: Path) -> tuple[int, str]:
    """Run every rule and return `(exit code, report)`."""
    out = io.StringIO()
    code = pl.main(["--plan-root", str(plan), "--manifest", str(manifest)], out=out)
    return code, out.getvalue()


@pytest.fixture(autouse=True, scope="module")
def _the_real_plan_is_left_byte_identical() -> Iterator[None]:
    """No test in this file may write to settled law, and this is what proves none did.

    The claim used to be a sentence in a docstring. `_plan/` is gitignored (`.gitignore:3`), so
    git could not restore a file a runaway test damaged -- which is C55's exposure, one level up
    from the gate. Digesting the whole tree before and after the module costs one pass over ~5 MB.
    """
    before = pl.build_manifest(REAL_PLAN)
    yield
    after = pl.build_manifest(REAL_PLAN)
    assert after.documents == before.documents, "a test in this file changed a settled document"
    assert after.charter_digest == before.charter_digest, "a test in this file changed the charter"
    assert after.heading_line == before.heading_line


@pytest.fixture
def blessed(tmp_path: Path) -> tuple[Path, Path]:
    """A fixture plan tree and a manifest blessed from it, which passes before any mutation."""
    plan = build_plan(tmp_path / "plan")
    manifest = tmp_path / "tools" / "plan.sha256"
    bless(plan, manifest)
    code, report = run(plan, manifest)
    assert code == pl.EXIT_CLEAN, report
    return plan, manifest


# ---------------------------------------------------------------------------
# 1. The gate is green on the tree it ships with, and the fixture is a real plan
# ---------------------------------------------------------------------------


def test_the_real_plan_passes_every_rule_against_the_committed_manifest() -> None:
    """The gate this repository ships runs clean on the tree it ships with.

    It is the only test here that runs all four rules against the real `_plan/`, and it only
    READS it. Twelve others read the real tree as well -- its charter, 18-api-sketch.md's clause
    table, the committed manifest -- and none of them writes to it: the module-scoped
    `_the_real_plan_is_left_byte_identical` fixture proves that mechanically rather than in prose.
    """
    out = io.StringIO()
    code = pl.main(["--plan-root", str(REAL_PLAN), "--manifest", str(REAL_MANIFEST)], out=out)
    assert code == pl.EXIT_CLEAN, out.getvalue()
    for rule in pl.RULES:
        assert f"ok   {rule}" in out.getvalue(), out.getvalue()


def test_a_fixture_tree_blessed_from_itself_passes_all_five_rules(blessed) -> None:
    """The baseline. Without it every mutation test below could be passing for the wrong reason."""
    plan, manifest = blessed
    code, report = run(plan, manifest)
    assert code == pl.EXIT_CLEAN, report
    assert "5 rules, 0 findings" in report
    assert "3 rows, 3 phrases resolved" in report


def test_the_report_names_every_rule_so_a_failure_says_which_one_failed(blessed) -> None:
    plan, manifest = blessed
    _, report = run(plan, manifest)
    assert set(pl.RULES) == {
        "charter-frozen",
        "documents-frozen",
        "errata-phrases",
        "codes-unique",
        "cli-verbs",
    }
    for rule in pl.RULES:
        assert rule in report, report


# ---------------------------------------------------------------------------
# 2. documents-frozen, against three deliberate violations
# ---------------------------------------------------------------------------


def test_one_mutated_byte_in_a_settled_document_fails_and_names_the_file_and_the_rule(
    blessed,
) -> None:
    """C55's mutation, at one byte. `git` cannot see it; this must."""
    plan, manifest = blessed
    victim = plan / "00-vision.md"
    original = victim.read_bytes()
    victim.write_bytes(original.replace(b"V10-17", b"V10-18"))
    assert len(victim.read_bytes()) == len(original)

    code, report = run(plan, manifest)
    assert code == pl.EXIT_FAIL, report
    assert "FAIL documents-frozen: 00-vision.md:" in report
    assert "pinned" in report


def test_a_deleted_settled_document_fails_and_names_it(blessed) -> None:
    plan, manifest = blessed
    (plan / "adr" / "0001-a-decision.md").unlink()
    code, report = run(plan, manifest)
    assert code == pl.EXIT_FAIL, report
    assert "adr/0001-a-decision.md: pinned in the manifest and not on disk" in report


def test_an_added_unlisted_file_fails_rather_than_silently_escaping(blessed) -> None:
    """A newly added settled document gets COVERED by failing, which is the whole design."""
    plan, manifest = blessed
    (plan / "19-a-new-document.md").write_text("# Nineteen\n", encoding="utf-8", newline="\n")
    code, report = run(plan, manifest)
    assert code == pl.EXIT_FAIL, report
    assert "19-a-new-document.md: is in neither the manifest nor the writable allow-list" in report


def test_a_file_this_project_writes_may_change_without_failing_the_gate(blessed) -> None:
    """The other side of the allow-list: the ledger grows every wave and must not cry wolf."""
    plan, manifest = blessed
    ledger = plan / "_notes" / "build-defects.md"
    ledger.write_text(ledger.read_text(encoding="utf-8") + "\n### C56. A new row\n", "utf-8")
    code, report = run(plan, manifest)
    assert code == pl.EXIT_CLEAN, report


def test_an_allow_listed_file_that_vanished_is_a_stale_row_and_fails(blessed) -> None:
    """A row left behind after a file was removed exempts nothing and reads as coverage."""
    plan, manifest = blessed
    (plan / "_notes" / "m0-was-skipped.md").unlink()
    code, report = run(plan, manifest)
    assert code == pl.EXIT_FAIL, report
    assert "_notes/m0-was-skipped.md: on the writable allow-list and not on disk" in report


def test_the_charter_is_covered_by_its_own_rule_and_never_pinned_as_a_whole_document(
    blessed,
) -> None:
    """A whole-file digest over `charter.md` would fail on every legitimate erratum."""
    _, manifest = blessed
    text = manifest.read_text(encoding="utf-8")
    assert f"{pl.RULE_DOCUMENTS}  " in text
    assert f"{pl.RULE_DOCUMENTS}  " not in "".join(
        line for line in text.splitlines(keepends=True) if pl.CHARTER_REL in line
    )
    parsed = pl.parse_manifest(text, manifest)
    assert pl.CHARTER_REL not in parsed.documents
    assert parsed.charter_digest


def test_pinning_the_charter_as_a_document_is_itself_a_finding(blessed) -> None:
    """Belt and braces: if a future bless ever wrote that row, the gate says so by name."""
    plan, manifest = blessed
    parsed = pl.parse_manifest(manifest.read_text(encoding="utf-8"), manifest)
    forged = pl.Manifest(
        version=parsed.version,
        charter_digest=parsed.charter_digest,
        region_last_line=parsed.region_last_line,
        heading_line=parsed.heading_line,
        documents={**parsed.documents, pl.CHARTER_REL: "0" * 64},
    )
    findings, _ = pl.check_documents_frozen(plan, forged, pl.plan_files(plan))
    details = [f.detail for f in findings if f.path == pl.CHARTER_REL]
    assert any("charter-frozen owns it" in detail for detail in details), findings


# ---------------------------------------------------------------------------
# 3. charter-frozen: 1-8 is frozen, 9 may grow, and the region definition is tested both ways
# ---------------------------------------------------------------------------


def test_a_mutation_inside_charter_sections_one_to_eight_fails(blessed) -> None:
    plan, manifest = blessed
    charter = plan / pl.CHARTER_REL
    charter.write_bytes(
        charter.read_bytes().replace(b"A second fixture sentence", b"A revised fixture sentence")
    )
    code, report = run(plan, manifest)
    assert code == pl.EXIT_FAIL, report
    assert "FAIL charter-frozen" in report
    assert "sections 1-8 digest" in report


def test_a_mutation_inside_charter_section_nine_passes_because_the_errata_may_grow(
    blessed,
) -> None:
    """`charter.md:8689` freezes 1-8 and `:8762`'s E-Q1 keeps section 9 growable."""
    plan, manifest = blessed
    charter = plan / pl.CHARTER_REL
    charter.write_text(
        charter.read_text(encoding="utf-8") + "\nA later stage appended this to 9.4.\n",
        encoding="utf-8",
        newline="\n",
    )
    code, report = run(plan, manifest)
    assert code == pl.EXIT_CLEAN, report


def test_a_line_appended_at_the_end_of_section_eight_fails_where_a_fixed_count_would_not(
    blessed,
) -> None:
    """The failure mode of the design that was NOT picked, asserted in the same test.

    A fixed count of N covers lines 1..N. A line inserted after old line N but before the section
    9 heading leaves those lines byte-identical, so a fixed-count digest does not move and never
    covers the new line of section 1-8. The anchored region grows with the section and fails.
    """
    plan, manifest = blessed
    charter = plan / pl.CHARTER_REL
    before = charter.read_bytes()
    lines = before.splitlines(keepends=True)
    heading = next(
        n for n, raw in enumerate(lines, 1) if pl.SECTION_9_HEADING.match(raw.decode("utf-8"))
    )
    fixed_count = heading - 1
    fixed_before = hashlib.sha256(b"".join(lines[:fixed_count])).hexdigest()

    smuggled = [
        *lines[: heading - 1],
        b"A ninth section-8 rule, smuggled in.\n",
        *lines[heading - 1 :],
    ]
    charter.write_bytes(b"".join(smuggled))

    after = charter.read_bytes().splitlines(keepends=True)
    fixed_after = hashlib.sha256(b"".join(after[:fixed_count])).hexdigest()
    assert fixed_after == fixed_before, (
        "the fixed-count design must be shown to MISS this, or this test proves nothing"
    )

    anchored_before, _ = pl.frozen_region(before)
    anchored_after, matches = pl.frozen_region(charter.read_bytes())
    assert matches == (heading + 1,)
    assert pl.digest(anchored_after) != pl.digest(anchored_before)

    code, report = run(plan, manifest)
    assert code == pl.EXIT_FAIL, report
    assert "FAIL charter-frozen" in report
    assert f"heading is at :{heading + 1}, pinned at :{heading}" in report


def test_a_second_section_nine_heading_fails_instead_of_silently_shrinking_the_region(
    blessed,
) -> None:
    """The anchored design's own failure mode, made an assertion rather than an assumption."""
    plan, manifest = blessed
    charter = plan / pl.CHARTER_REL
    text = charter.read_text(encoding="utf-8")
    charter.write_text(
        text.replace("## 8. What a reviewer", "## 9. A decoy\n\n## 8. What a reviewer", 1),
        encoding="utf-8",
        newline="\n",
    )
    code, report = run(plan, manifest)
    assert code == pl.EXIT_FAIL, report
    assert "FAIL charter-frozen" in report
    assert "matches 2 lines" in report
    assert "exactly one defines the frozen boundary" in report


def test_deleting_the_section_nine_heading_altogether_fails_rather_than_digesting_the_file(
    blessed,
) -> None:
    plan, manifest = blessed
    charter = plan / pl.CHARTER_REL
    charter.write_text(
        charter.read_text(encoding="utf-8").replace("## 9. Errata", "## Errata", 1),
        encoding="utf-8",
        newline="\n",
    )
    code, report = run(plan, manifest)
    assert code == pl.EXIT_FAIL, report
    assert "matches 0 lines" in report


def test_the_frozen_boundary_is_the_line_the_real_charter_itself_names() -> None:
    """The two numbers this wave's brief stated, verified against the document.

    `charter.md:8687` is the section 9 heading and `:8689` opens the paragraph that freezes 1-8.
    Both are read out of the file here rather than transcribed, and the *pinned* boundary in the
    committed manifest is asserted against the one found in the text.
    """
    charter = REAL_CHARTER.read_bytes()
    _, matches = pl.frozen_region(charter)
    assert matches == (8687,), matches
    lines = REAL_CHARTER.read_text(encoding="utf-8").splitlines()
    assert lines[8686].startswith("## 9. Errata")
    assert lines[8688].startswith("**Sections 1-8 are unchanged. Deliberately.**")
    pinned = pl.parse_manifest(REAL_MANIFEST.read_text(encoding="utf-8"), REAL_MANIFEST)
    assert pinned.heading_line == 8687
    assert pinned.region_last_line == 8686


# ---------------------------------------------------------------------------
# 4. errata-phrases: E-Q2's sentence, and nothing more than E-Q2's sentence
# ---------------------------------------------------------------------------


def test_an_erratum_phrase_that_no_longer_resolves_fails_and_reports_the_line_as_advisory(
    blessed,
) -> None:
    """E-Q2: *"fails on a miss, reporting the row's line number as advisory rather than
    authoritative"*. Both halves of that sentence are asserted."""
    plan, manifest = blessed
    charter = plan / pl.CHARTER_REL
    charter.write_text(
        charter.read_text(encoding="utf-8").replace(
            "`The first fixture sentence`", "`A phrase no section of 1-8 contains`", 1
        ),
        encoding="utf-8",
        newline="\n",
    )
    code, report = run(plan, manifest)
    assert code == pl.EXIT_FAIL, report
    assert "FAIL errata-phrases" in report
    assert "E1 quotes 'A phrase no section of 1-8 contains'" in report
    assert pl.PHRASE_MISS in report
    assert "ADVISORY and not the locus" in report


def test_a_phrase_that_moved_inside_sections_one_to_eight_is_advisory_drift_and_not_a_failure(
    blessed,
) -> None:
    """A line number moves; the phrase is the locus. Failing on the hint would contradict E-Q2."""
    plan, manifest = blessed
    charter = plan / pl.CHARTER_REL
    charter.write_text(
        charter.read_text(encoding="utf-8").replace("| :5 |", "| :4000 |", 1),
        encoding="utf-8",
        newline="\n",
    )
    code, report = run(plan, manifest)
    # The edit is inside section 9, which may grow, so NOTHING fails: charter-frozen does not
    # cover the region, and errata-phrases treats the stale locus as the hint E-Q2 says it is.
    assert code == pl.EXIT_CLEAN, report
    assert "FAIL" not in report
    assert "advisory drift (not a failure" in report
    assert "E1 phrase at :5, locus cell says ':4000'" in report


def test_the_phrase_resolves_against_sections_one_to_eight_and_not_against_the_row_that_quotes_it(
    tmp_path: Path,
) -> None:
    """The vacuity this rule would otherwise have: every row quotes its own phrase.

    Resolved against the whole file, a row's phrase always matches the row, so the rule could
    never fail -- C13's family. The frozen region excludes section 9, so it can.
    """
    plan = build_plan(tmp_path / "plan")
    charter = plan / pl.CHARTER_REL
    text = charter.read_text(encoding="utf-8")
    charter.write_text(
        text.replace(
            "The first fixture sentence, which E1 quotes and which no later section may edit.",
            "This sentence replaces the one E1 quotes.",
            1,
        ),
        encoding="utf-8",
        newline="\n",
    )
    whole = charter.read_text(encoding="utf-8")
    assert "The first fixture sentence" in whole, "the row still quotes it -- that is the trap"

    findings, _ = pl.check_errata_phrases(plan)
    assert [f.rule for f in findings] == [pl.RULE_ERRATA]
    assert pl.PHRASE_MISS in findings[0].detail


def test_the_row_count_comes_from_the_table_and_a_heading_that_disagrees_is_a_failure(
    blessed,
) -> None:
    """A sentence whose count contradicts its own enumeration is a defect, not a rounding."""
    plan, _ = blessed
    charter = plan / pl.CHARTER_REL
    charter.write_text(
        charter.read_text(encoding="utf-8").replace(
            "## 9. Errata -- the three statements", "## 9. Errata -- the four statements", 1
        ),
        encoding="utf-8",
        newline="\n",
    )
    findings, _ = pl.check_errata_phrases(plan)
    details = [f.detail for f in findings]
    assert any("claims 4 statements and its own table holds 3 rows" in d for d in details), details


def test_the_real_charters_heading_count_agrees_with_its_own_table() -> None:
    """Derived, not transcribed: 23 rows, anchors E1..E23 dense and unique, heading says 23."""
    text = REAL_CHARTER.read_text(encoding="utf-8")
    rows = pl.errata_rows(text)
    claimed, heading = pl.heading_claim(text)
    assert len(rows) == 23, len(rows)
    assert claimed == len(rows), (claimed, len(rows), heading)
    numbers = sorted(int(row.anchor[1:]) for row in rows)
    assert numbers == list(range(1, 24)), numbers
    assert len({row.code for row in rows}) == len(rows)


def test_the_six_column_rows_survive_an_escaped_pipe_inside_a_code_span() -> None:
    """Charter `E22` prints ``Rung \\| None``; a naive split reads that row as seven cells."""
    row = '| <a id="e22"></a>**E22** | :2485-2486 | `a: b;` | `Rung \\| None` | five | six |'
    cells = pl.markdown_cells(row)
    assert len(cells) == pl.ERRATA_ROW_CELLS
    assert cells[3] == "`Rung | None`"
    real = [r for r in pl.errata_rows(REAL_CHARTER.read_text(encoding="utf-8")) if r.code == "E22"]
    assert real and real[0].phrase == "rung_reached: Rung; wanted_driver:"


# ---------------------------------------------------------------------------
# 5. codes-unique: 18-api-sketch.md:3227-3244's clauses, and its one derived exclusion
# ---------------------------------------------------------------------------


def test_a_numeric_bound_to_a_second_live_symbol_fails_and_reports_every_site(blessed) -> None:
    """*"fails on: any numeric bound to two distinct symbols"* (18:3242), *"reports: every binding
    site -- file, line, symbol"* (18:3243)."""
    plan, manifest = blessed
    (plan / "glossary.md").write_text(
        "# Glossary\n\n`OW-A-001` `OW_FIXTURE_BETA` is a second spelling.\n",
        encoding="utf-8",
        newline="\n",
    )
    bless(plan, manifest, "re-bless so only codes-unique can fail")
    code, report = run(plan, manifest)
    assert code == pl.EXIT_FAIL, report
    assert "FAIL codes-unique" in report
    assert "OW-A-001 binds to 2 symbols" in report
    assert "OW_FIXTURE_ALPHA at _notes/charter.md:7" in report
    assert "OW_FIXTURE_BETA at glossary.md:3" in report


def test_a_symbol_bound_to_two_numerics_fails_because_the_rule_runs_in_both_directions(
    blessed,
) -> None:
    """*"Both directions, because a symbol that drifted onto a second numeric is the same build
    failure seen from the other end"* (18:3242)."""
    plan, manifest = blessed
    (plan / "glossary.md").write_text(
        "# Glossary\n\n`OW-A-009` `OW_FIXTURE_ALPHA` drifted onto a second numeric.\n",
        encoding="utf-8",
        newline="\n",
    )
    bless(plan, manifest, "re-bless so only codes-unique can fail")
    code, report = run(plan, manifest)
    assert code == pl.EXIT_FAIL, report
    assert "OW_FIXTURE_ALPHA binds to 2 numerics" in report


def test_a_comma_in_the_separator_is_not_a_binding(blessed) -> None:
    """18:3241's not-a-binding clause: commas join independent pairs in a prose list, and
    admitting one is what makes an adjacency rule report phantom collisions."""
    plan, manifest = blessed
    (plan / "glossary.md").write_text(
        "# Glossary\n\n`OW-A-001` `OW_FIXTURE_ALPHA`, `OW-A-009` `OW_FIXTURE_GAMMA`\n",
        encoding="utf-8",
        newline="\n",
    )
    bless(plan, manifest, "re-bless so only codes-unique can fail")
    code, report = run(plan, manifest)
    assert code == pl.EXIT_CLEAN, report
    sites = list(pl.bindings("`OW-A-001` `OW_A_ALPHA`, `OW-A-009`", "x"))
    assert [(s.numeric, s.symbol) for s in sites] == [("OW-A-001", "OW_A_ALPHA")]


def test_prose_between_a_numeric_and_a_symbol_is_not_a_binding() -> None:
    """The separator class admits no letters, so both token orders are safe to accept."""
    assert list(pl.bindings("`OW_FOO_BAR` and `OW-A-001`", "x")) == []
    assert [s.symbol for s in pl.bindings("`OW_FOO_BAR` (`OW-A-001`)", "x")] == ["OW_FOO_BAR"]


def test_a_binding_superseded_by_a_charter_errata_row_is_excluded_and_the_exclusion_is_printed(
    blessed,
) -> None:
    """The real plan's only collision is `OW-A-021`, which charter `E18` records as a RENAME.

    The exclusion is read out of section 9 rather than hand-written, so 18:3359's "the documented
    exception list is **empty**" stays true -- and every dropped site is printed, because a silent
    exclusion is the off switch this whole wave is about.
    """
    plan, manifest = blessed
    code, report = run(plan, manifest)
    assert code == pl.EXIT_CLEAN, report
    # Two sites, and both are named: the section-1 print the rename retired, and the E3 row
    # that retires it. Dropping the PAIR rather than the numeric is why both go.
    assert "2 superseded" in report
    assert "OW-A-002 OW_FIXTURE_RETIRED at _notes/charter.md:8" in report
    assert "OW-A-002 OW_FIXTURE_RETIRED at _notes/charter.md:28" in report
    assert "not a hand-written exception list" in report


def test_deleting_the_errata_row_turns_the_superseded_binding_back_into_a_failure(
    blessed,
) -> None:
    """The exclusion cannot be an off switch: it exists only while the charter row does."""
    plan, _ = blessed
    charter = plan / pl.CHARTER_REL
    charter.write_text(
        "".join(
            line
            for line in charter.read_text(encoding="utf-8").splitlines(keepends=True)
            if 'id="e3"' not in line
        ).replace("the three statements", "the two statements"),
        encoding="utf-8",
        newline="\n",
    )
    findings, _ = pl.check_codes_unique(plan)
    assert [f.rule for f in findings] == [pl.RULE_CODES], findings
    assert "OW-A-002 binds to 2 symbols" in findings[0].detail


def test_a_third_symbol_on_a_superseded_numeric_still_fails(blessed) -> None:
    """The exclusion drops one PAIR, never a numeric. Otherwise it would be an amnesty."""
    plan, _ = blessed
    (plan / "glossary.md").write_text(
        "# Glossary\n\n`OW-A-002` `OW_FIXTURE_THIRD` arrived later.\n",
        encoding="utf-8",
        newline="\n",
    )
    findings, notes = pl.check_codes_unique(plan)
    assert [f.rule for f in findings] == [pl.RULE_CODES], (findings, notes)
    assert "OW-A-002 binds to 2 symbols" in findings[0].detail
    assert "OW_FIXTURE_LIVE" in findings[0].detail
    assert "OW_FIXTURE_THIRD" in findings[0].detail


def test_the_corpus_is_the_plans_own_corpus_clause_and_excludes_snapshots(tmp_path: Path) -> None:
    """18:3238: *"`_plan/*.md` plus `_plan/_notes/charter.md` and `_plan/_notes/terminology.md`;
    snapshots under `_plan/_notes/.snapshots/` are excluded"*."""
    plan = build_plan(tmp_path / "plan")
    snapshot = plan / "_notes" / ".snapshots" / "s1-pre" / "00-vision.md"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text("`OW-A-001` `OW_FIXTURE_STALE`\n", encoding="utf-8", newline="\n")
    corpus = pl.codes_corpus(plan)
    assert corpus == (
        "00-vision.md",
        "01-principles.md",
        "10-interfaces.md",
        "README.md",
        "glossary.md",
        pl.CHARTER_REL,
        pl.TERMINOLOGY_REL,
    ), corpus
    assert not any(".snapshots" in rel for rel in corpus)
    findings, _ = pl.check_codes_unique(plan)
    assert findings == [], "a stale snapshot must not report a collision"

    real = pl.codes_corpus(REAL_PLAN)
    assert len(real) == 23, real
    assert real[:2] == ("00-vision.md", "01-principles.md")


def test_the_token_shapes_are_the_ones_the_plan_prints_rather_than_the_ones_we_wrote() -> None:
    """Rule 5: both sides of `SCAN_NUMERIC == errors.NUMERIC_RE` come from us, so that equality
    pins agreement and not value. The VALUE is pinned against 18-api-sketch.md's own cell."""
    row = next(
        line
        for line in API_SKETCH.read_text(encoding="utf-8").splitlines()
        if line.startswith("   | **tokens** |")
    )
    assert "OW-[A-Z]-" in row and "d{3}" in row, row
    assert "OW_[A-Z0-9_]{3,}" in row, row
    assert pl.SCAN_NUMERIC.pattern == r"OW-[A-Z]-\d{3}"
    assert pl.SCAN_SYMBOL.pattern == r"OW_[A-Z0-9_]{3,}"
    separator = next(
        line
        for line in API_SKETCH.read_text(encoding="utf-8").splitlines()
        if line.startswith("   | **binding** |")
    )
    cell = re.search(r"`(\[\\s\\x60.*?\{0,6\})`", separator)
    assert cell is not None, separator
    # The one difference is the markdown escape on the pipe, which a table cell needs and a
    # regex does not. `\x60` is left as the plan spells it, so this is character for character.
    assert pl.BINDING_SEPARATOR.pattern == cell.group(1).replace(r"\|", "|")


def test_the_register_half_of_codes_unique_is_not_reimplemented_here() -> None:
    """18:3246-3252 makes `codes-unique` and `ow explain --check` two halves of one pair.

    The register half already exists, so a second implementation would give one fact two homes
    (INV-21). This asserts the existing home is real and that `plan_lint` never reads `codes.toml`.
    """
    assert callable(errors.check_register)
    assert errors.check_register() == (), "the shipped register must be clean"
    source = (REPO_ROOT / "tools" / "plan_lint.py").read_text(encoding="utf-8")
    assert "codes.toml" not in source.split('"""', 2)[2], (
        "the prose half must not read the register"
    )
    assert "check_register" in source, "and it must cite where the other half lives"


# ---------------------------------------------------------------------------
# 6. THE ASSERTION THIS WAVE IS ABOUT: git cannot see it, and this can
# ---------------------------------------------------------------------------


def git(repo: Path, *args: str) -> str:
    """`git` in `repo`, with identity and signing forced so a temp repo can commit."""
    exe = shutil.which("git")
    assert exe is not None, "git is required: this test's whole subject is what git cannot see"
    done = subprocess.run(  # noqa: S603
        [
            exe,
            "-c",
            "user.name=plan lint test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode in (0, 1), (args, done.returncode, done.stdout, done.stderr)
    return done.stdout


def test_git_diff_over_the_ignored_plan_is_empty_while_the_gate_is_non_zero(tmp_path: Path) -> None:
    """C55, reproduced, with the detector on the other side of it.

    *"`git diff HEAD -- _plan/` is empty"* was cited as evidence for four waves. It is empty for
    every possible content of an ignored directory. This asserts all three facts on ONE mutation:
    `git diff` sees nothing, `git status --porcelain` sees nothing, and `plan_lint` fails.
    """
    repo = tmp_path / "repo"
    (repo / "tools").mkdir(parents=True)
    plan = build_plan(repo / "_plan")
    manifest = repo / "tools" / "plan.sha256"
    bless(plan, manifest, "fixture repo")
    (repo / ".gitignore").write_text("_plan/\n", encoding="utf-8", newline="\n")

    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "the fixture plan and its manifest")

    ignored = git(repo, "check-ignore", "-v", "--", "_plan/00-vision.md")
    assert ".gitignore:1:_plan/" in ignored, ignored
    assert git(repo, "status", "--porcelain") == "", "the tree must be clean before the mutation"

    victim = plan / "00-vision.md"
    victim.write_bytes(victim.read_bytes().replace(b"V10-17", b"V10-18"))

    assert git(repo, "diff", "HEAD", "--", "_plan/") == "", "git cannot see an ignored path"
    assert git(repo, "status", "--porcelain", "--", "_plan/") == ""
    assert git(repo, "status", "--porcelain") == "", "nor can a bare status"

    code, report = run(plan, manifest)
    assert code == pl.EXIT_FAIL, report
    assert "00-vision.md" in report and pl.RULE_DOCUMENTS in report


def test_the_manifest_is_not_itself_gitignored() -> None:
    """The correction C55 missed: `_plan/PLAN.sha256` would be matched by `.gitignore:3` too.

    Asserted twice -- structurally, that the shipped manifest is outside the plan root; and
    behaviourally, that `git check-ignore` in THIS repository ignores the plan and not the
    manifest.
    """
    assert not pl.DEFAULT_MANIFEST.is_relative_to(pl.DEFAULT_PLAN_ROOT)
    assert pl.DEFAULT_MANIFEST.parent.name == "tools"

    exe = shutil.which("git")
    assert exe is not None
    # `git check-ignore -q` exits 0 when the path IS ignored and 1 when it is not.
    for target, expected in (("_plan/README.md", 0), ("tools/plan.sha256", 1)):
        done = subprocess.run(  # noqa: S603
            [exe, "check-ignore", "-q", "--", target],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert done.returncode == expected, (target, done.returncode, done.stderr)
    assert REAL_MANIFEST.is_file()


# ---------------------------------------------------------------------------
# 7. The allow-list, checked twice over the REAL plan
# ---------------------------------------------------------------------------


def test_every_writable_row_names_a_file_this_project_actually_writes() -> None:
    """Without this the allow-list is a way to switch the gate off.

    Four properties per row, following `test_core_eager_surface.py`'s
    `test_the_filled_homes_are_really_filled`: the path exists, the reason is a real sentence
    naming a writer, the path is under `_notes/`, and the file was written AFTER every settled
    document -- which is C55's own mtime evidence, used here as the one mechanical witness that a
    row describes a working file rather than law somebody wanted exempted.
    """
    settled = [*REAL_PLAN.glob("*.md"), *(REAL_PLAN / "adr").glob("*.md")]
    assert len(settled) == 21 + 13, len(settled)
    newest_settled = max(path.stat().st_mtime for path in settled)

    assert pl.WRITABLE_NOTES, "an empty allow-list would make this test vacuous"
    for rel, reason in pl.WRITABLE_NOTES.items():
        path = REAL_PLAN / rel
        assert path.is_file(), f"{rel} is on the allow-list and does not exist"
        assert path.stat().st_size > 0, f"{rel} is empty"
        assert rel.startswith("_notes/"), rel
        assert len(reason) >= 60, f"{rel}'s reason is too short to be a reason: {reason!r}"
        assert reason.rstrip().endswith("."), f"{rel}'s reason is not a sentence"
        assert any(word in reason for word in ("wave", "ledger", "recorder", "stage")), (
            f"{rel}'s reason names no writer: {reason!r}"
        )
        assert path.stat().st_mtime > newest_settled, (
            f"{rel} is older than the newest settled document, so nothing here witnesses that "
            "this project writes it. If the tree was copied and mtimes were reset, re-establish "
            "the evidence rather than deleting this assertion."
        )


def test_no_allow_list_row_could_ever_switch_off_settled_law() -> None:
    """The other direction, and it runs inside the gate too, not only here."""
    assert pl.no_row_switches_off_settled_law() == ()
    assert frozenset({pl.CHARTER_REL, pl.TERMINOLOGY_REL}) == pl.NEVER_WRITABLE_NOTES
    for rel in pl.WRITABLE_NOTES:
        assert rel not in pl.NEVER_WRITABLE_NOTES
        assert "/" in rel and not rel.startswith(pl.SNAPSHOTS_PREFIX)
        assert not rel.startswith("adr/")


@pytest.mark.parametrize(
    "forged",
    [
        pytest.param("00-vision.md", id="a numbered document"),
        pytest.param("adr/0001-terminology-lock-bulk-pass.md", id="an adr"),
        pytest.param("_notes/charter.md", id="the charter"),
        pytest.param("_notes/terminology.md", id="the terminology lock"),
        pytest.param("_notes/.snapshots/s12d-pre/charter.md", id="a snapshot"),
    ],
)
def test_a_forged_allow_list_row_over_settled_law_is_reported_by_the_gate_itself(
    monkeypatch: pytest.MonkeyPatch, forged: str
) -> None:
    """The guard is not only a test: `documents-frozen` reports it, so an edited allow-list
    cannot go green on the machine that edited it."""
    monkeypatch.setitem(pl.WRITABLE_NOTES, forged, "a reason somebody wrote to get past a gate.")
    messages = pl.no_row_switches_off_settled_law()
    assert any(forged in message for message in messages), messages


def test_the_covered_set_is_a_difference_and_partitions_the_real_tree() -> None:
    """Computed, never declared -- and every file under `_plan/` lands in exactly one bucket."""
    paths = pl.plan_files(REAL_PLAN)
    manifest = pl.parse_manifest(REAL_MANIFEST.read_text(encoding="utf-8"), REAL_MANIFEST)
    settled = set(pl.settled_documents(paths))
    writable = set(pl.WRITABLE_NOTES)

    assert len(paths) == 575, len(paths)
    assert len(writable) == 10, len(writable)
    assert len(settled) == len(paths) - len(writable) - 1
    assert settled == set(manifest.documents)
    assert settled | writable | {pl.CHARTER_REL} == set(paths)
    assert settled & writable == set()
    assert pl.CHARTER_REL not in settled and pl.CHARTER_REL not in writable
    assert len([rel for rel in paths if rel.startswith(pl.SNAPSHOTS_PREFIX)]) == 423


# ---------------------------------------------------------------------------
# 8. Exit 2 is "the gate did not run", and it is never confused with exit 1
# ---------------------------------------------------------------------------


def test_a_missing_manifest_is_exit_two_and_never_a_pass(tmp_path: Path) -> None:
    plan = build_plan(tmp_path / "plan")
    code, report = run(plan, tmp_path / "nowhere" / "plan.sha256")
    assert code == pl.EXIT_NOT_RUN, report
    assert "DID NOT RUN" in report
    assert "nothing to compare against" in report


def test_a_plan_root_that_is_not_a_directory_is_exit_two(blessed, tmp_path: Path) -> None:
    _, manifest = blessed
    code, report = run(tmp_path / "no-such-plan", manifest)
    assert code == pl.EXIT_NOT_RUN, report
    assert "plan root is not a directory" in report


def test_an_empty_plan_root_is_exit_two_because_every_rule_would_be_vacuous(
    blessed, tmp_path: Path
) -> None:
    _, manifest = blessed
    empty = tmp_path / "empty"
    empty.mkdir()
    code, report = run(empty, manifest)
    assert code == pl.EXIT_NOT_RUN, report
    assert "would be vacuous" in report


def test_an_unreadable_charter_is_exit_two_and_not_a_silent_pass(blessed) -> None:
    plan, manifest = blessed
    (plan / pl.CHARTER_REL).unlink()
    code, report = run(plan, manifest)
    assert code == pl.EXIT_NOT_RUN, report
    assert "cannot read _notes/charter.md" in report


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        pytest.param("version  9\n", "version 9", id="a version we do not read"),
        pytest.param(
            "charter-frozen  " + "0" * 64 + "  _notes/charter.md  region=1-5  heading=9\n",
            "disagree",
            id="a region and heading that disagree",
        ),
        pytest.param("version  1\n", "no `charter-frozen` row", id="no charter row"),
        pytest.param(
            "version  1\ncharter-frozen  "
            + "0" * 64
            + "  _notes/charter.md  region=1-5  heading=6\n",
            "would be vacuous",
            id="no document rows",
        ),
        pytest.param(
            "version  1\ndocuments-frozen  nothex  00-vision.md\n",
            "not a lowercase hex sha256",
            id="a digest that is not one",
        ),
        pytest.param("version  1\nsomething-else  1  2\n", "cannot read the row", id="a junk row"),
    ],
)
def test_an_unparseable_manifest_is_exit_two_rather_than_a_half_read_pass(
    tmp_path: Path, row: str, expected: str
) -> None:
    """*"a half-read manifest is a gate that reports success because it never looked"*."""
    plan = build_plan(tmp_path / "plan")
    manifest = tmp_path / "plan.sha256"
    manifest.write_text(row, encoding="utf-8", newline="\n")
    code, report = run(plan, manifest)
    assert code == pl.EXIT_NOT_RUN, report
    assert expected in report


def test_a_manifest_that_pins_a_document_twice_is_exit_two(tmp_path: Path) -> None:
    plan = build_plan(tmp_path / "plan")
    manifest = tmp_path / "plan.sha256"
    bless(plan, manifest)
    text = manifest.read_text(encoding="utf-8")
    duplicated = next(line for line in text.splitlines() if line.startswith(pl.RULE_DOCUMENTS))
    manifest.write_text(text + duplicated + "\n", encoding="utf-8", newline="\n")
    code, report = run(plan, manifest)
    assert code == pl.EXIT_NOT_RUN, report
    assert "is pinned twice" in report


def test_the_three_exit_codes_are_distinct_and_a_rule_failure_is_one() -> None:
    """1 and 2 are distinguished because a human needs to know which. 18:3244 spells
    `codes-unique`'s failure exit as `2`; that number is this repository's "did not run", so the
    divergence is stated in the module docstring rather than smoothed away here."""
    assert (pl.EXIT_CLEAN, pl.EXIT_FAIL, pl.EXIT_NOT_RUN) == (0, 1, 2)
    docstring = pl.__doc__ or ""
    assert "18-api-sketch.md:3244" in docstring
    assert "the gate did not run" in docstring


# ---------------------------------------------------------------------------
# 9. --bless: loud, reasoned, deterministic
# ---------------------------------------------------------------------------


def test_bless_refuses_without_a_reason(tmp_path: Path) -> None:
    """*"A `--bless` that can be run absent-mindedly is how a manifest stops meaning anything."*"""
    plan = build_plan(tmp_path / "plan")
    out = io.StringIO()
    code = pl.main(
        ["--plan-root", str(plan), "--manifest", str(tmp_path / "m.sha256"), "--bless"], out=out
    )
    assert code == pl.EXIT_NOT_RUN, out.getvalue()
    assert "--bless needs --reason" in out.getvalue()
    assert not (tmp_path / "m.sha256").exists(), "a refused bless must write nothing"


def test_bless_writes_the_reason_into_the_manifest_where_a_diff_will_show_it(
    tmp_path: Path,
) -> None:
    plan = build_plan(tmp_path / "plan")
    manifest = tmp_path / "plan.sha256"
    bless(plan, manifest, "ADR-13 approved the amendment; charter E24 records it")
    text = manifest.read_text(encoding="utf-8")
    assert "# blessed-because: ADR-13 approved the amendment; charter E24 records it" in text
    assert "tools/plan.sha256" in text
    assert ".gitignore:3" in text


def test_bless_names_every_digest_it_changes_adds_and_removes(tmp_path: Path) -> None:
    """It prints nothing quietly, so a bless that covered more than the author meant is visible."""
    plan = build_plan(tmp_path / "plan")
    manifest = tmp_path / "plan.sha256"
    first = bless(plan, manifest, "the first bless")
    assert "FIRST BLESS: 7 documents" in first, first

    (plan / "00-vision.md").write_text("# Vision\n\nEdited.\n", encoding="utf-8", newline="\n")
    (plan / "02-new.md").write_text("# Two\n", encoding="utf-8", newline="\n")
    (plan / "glossary.md").unlink()
    charter = plan / pl.CHARTER_REL
    charter.write_text(
        charter.read_text(encoding="utf-8").replace("A second fixture", "A rewritten fixture"),
        encoding="utf-8",
        newline="\n",
    )
    second = bless(plan, manifest, "the second bless")
    assert "changed:  00-vision.md" in second
    assert "added:    02-new.md" in second
    assert "removed:  glossary.md" in second
    assert "CHARTER SECTIONS 1-8 CHANGED" in second
    assert "charter.md:8689 says no line of 1-8 is ever edited" in second


def test_bless_reports_when_no_digest_changed(tmp_path: Path) -> None:
    plan = build_plan(tmp_path / "plan")
    manifest = tmp_path / "plan.sha256"
    bless(plan, manifest, "one")
    assert "NO DIGEST CHANGED" in bless(plan, manifest, "two")


def test_bless_is_deterministic_so_a_manifest_diff_is_a_real_diff(tmp_path: Path) -> None:
    """No timestamp, sorted rows: a re-bless with the same reason is byte-identical."""
    plan = build_plan(tmp_path / "plan")
    one, two = tmp_path / "one.sha256", tmp_path / "two.sha256"
    bless(plan, one, "same reason")
    bless(plan, two, "same reason")
    assert one.read_bytes() == two.read_bytes()


def test_the_shipped_manifest_is_the_one_bless_would_write_for_the_real_plan() -> None:
    """The committed manifest is current: every digest in it is the tree's digest today.

    This is the gate's own job, asserted from the other end -- the rows are compared, not the
    reason line, because that is the human half.
    """
    fresh = pl.build_manifest(REAL_PLAN)
    pinned = pl.parse_manifest(REAL_MANIFEST.read_text(encoding="utf-8"), REAL_MANIFEST)
    assert fresh.documents == pinned.documents
    assert fresh.charter_digest == pinned.charter_digest
    assert fresh.heading_line == pinned.heading_line
    assert len(fresh.documents) == 564, len(fresh.documents)


def test_the_manifest_row_grammar_round_trips(tmp_path: Path) -> None:
    plan = build_plan(tmp_path / "plan")
    built = pl.build_manifest(plan)
    text = pl.format_manifest(built, "round trip")
    parsed = pl.parse_manifest(text, "memory")
    assert parsed == built
    assert re.search(r"(?m)^version  1$", text)
    assert re.search(
        r"(?m)^charter-frozen  [0-9a-f]{64}  _notes/charter\.md  region=1-\d+  heading=\d+$", text
    )


# ---------------------------------------------------------------------------
# 10. The verb, the register, and the file name
# ---------------------------------------------------------------------------


def test_the_plan_names_this_verb_at_the_two_lines_the_module_cites() -> None:
    """`ow plan lint` is transcribed, not invented. Both loci are read out of the plan."""
    charter_lines = REAL_CHARTER.read_text(encoding="utf-8").splitlines()
    assert "`ow plan lint` rule that resolves each row's quoted phrase" in charter_lines[8761]
    assert "**E-Q2**" in charter_lines[8761]
    sketch = API_SKETCH.read_text(encoding="utf-8").splitlines()
    assert "`ow plan lint` rule `codes-unique`" in sketch[3226]
    assert "because reading has now failed twice" in sketch[3226]


def test_this_script_is_not_in_the_gate_glob_because_no_gates_toml_row_names_it() -> None:
    """The register finding, made an assertion so it cannot be quietly undone.

    `test_gates_register.py` fails on any `tools/gate_*.py` that `tools/gates.toml` does not name.
    No `G` row names `ow plan lint`, and this wave did not invent one, so the script is named
    outside that glob. If a human adds a row later, this test is what says the file must be
    renamed in the same change.
    """
    script = REPO_ROOT / "tools" / "plan_lint.py"
    assert script.is_file()
    assert not script.name.startswith("gate_"), "a gate_*.py needs a tools/gates.toml row"
    register = (REPO_ROOT / "tools" / "gates.toml").read_text(encoding="utf-8")
    assert "plan_lint" not in register, "there is now a row: rename the script to gate_plan.py"
    assert "ow plan lint" not in register
    on_disk = {path.name for path in (REPO_ROOT / "tools").glob("gate_*.py")}
    assert "gate_plan.py" not in on_disk


# ---------------------------------------------------------------------------
# 11. The adversarial pass: the mutations the sixty-three tests above left green
#
# Every test in this section was written against a mutation of `tools/plan_lint.py` that the
# tests above did not kill, and each names its mutation. C55's rule is that a check must be run
# against a deliberate violation before it is cited as evidence; a test suite is a check.
# ---------------------------------------------------------------------------

#: The `codes-unique` clause table in `_plan/18-api-sketch.md`, line by line, with a marker
#: unique to each row. Citations in `tools/plan_lint.py` and in this file resolve into this
#: table, and four of them were off by one to five lines when this section was written: the
#: separator class was cited at `:3237` (a `|---|---|` rule), the corpus clause at `:3235` (a
#: blank line), the `reports` clause at `:3242` (the `fails on` row) and the `exit` clause at
#: `:3243` (the `reports` row). A citation that nothing resolves is a citation that rots quietly.
CLAUSE_LINES: Final[dict[int, str]] = {
    3227: "`ow plan lint` rule `codes-unique`, because reading has now failed twice",
    3238: "| **corpus** |",
    3239: "| **tokens** |",
    3240: "| **binding** |",
    3241: "| **not a binding** |",
    3242: "| **fails on** |",
    3243: "| **reports** |",
    3244: "| **exit** |",
    3359: "the documented exception list is **empty**",
}

#: The same, for `_plan/_notes/charter.md`. `:8687` and `:8689` are pinned in section 3 as well,
#: because they are the frozen boundary itself.
CHARTER_LINES: Final[dict[int, str]] = {
    6883: "OW-A-021  OW_INSTRUCTION_SHAPED_TEXT",
    8687: "## 9. Errata",
    8689: "**Sections 1-8 are unchanged. Deliberately.**",
    8711: "### 9.2 The record",
    8713: "| # | charter locus | search for this phrase |",
    8762: "**E-Q2**",
}

CITATION: Final = re.compile(r"18(?:-api-sketch\.md)?:(\d{4})(?:-(\d{4}))?")
CLAUSE_TABLE: Final = range(3236, 3245)


def test_every_clause_line_this_gate_cites_holds_the_clause_it_is_cited_for() -> None:
    """The mutation: none needed. Four of these citations were WRONG when this was written.

    A `file:line` citation into settled law is a claim, and this project's rule is that a claim
    gets a check. Both halves are asserted: the table above resolves against the document, and
    every `18...:NNNN` either file cites is one of that table's clauses when it falls inside the
    table -- which is what catches a citation aimed at a `|---|---|` rule or at a blank line.
    """
    lines = API_SKETCH.read_text(encoding="utf-8").splitlines()
    for number, marker in CLAUSE_LINES.items():
        assert marker in lines[number - 1], (number, lines[number - 1][:120])

    sources = (
        (REPO_ROOT / "tools" / "plan_lint.py").read_text(encoding="utf-8"),
        Path(__file__).read_text(encoding="utf-8"),
    )
    cited: set[int] = set()
    for text in sources:
        for match in CITATION.finditer(text):
            cited.update(int(group) for group in match.groups() if group is not None)
    assert cited, "no citations found -- this test would be vacuous"
    for number in sorted(cited):
        assert lines[number - 1].strip(), f"18-api-sketch.md:{number} is a blank line"
        if number in CLAUSE_TABLE:
            assert number in CLAUSE_LINES, (
                f"18-api-sketch.md:{number} is inside the clause table and is not one of its "
                f"clauses: {lines[number - 1][:80]!r}"
            )


def test_every_charter_line_this_gate_cites_holds_what_it_is_cited_for() -> None:
    """The mutation: none needed. The charter half of the same claim.

    `:8713` is the six-column header the row parser indexes against, and `:6883` is the retired
    spelling `E18` supersedes -- the one line whose content makes `codes-unique`'s derived
    exclusion non-empty.
    """
    lines = REAL_CHARTER.read_text(encoding="utf-8").splitlines()
    for number, marker in CHARTER_LINES.items():
        assert marker in lines[number - 1], (number, lines[number - 1][:120])
    header = pl.markdown_cells(lines[8712])
    assert len(header) == pl.ERRATA_ROW_CELLS
    assert header[2] == "search for this phrase"


def test_the_gitignore_line_this_gate_cites_is_the_line_that_ignores_the_plan() -> None:
    """The mutation: reorder `.gitignore` so `_plan/` is no longer its third line.

    Nothing failed. `.gitignore:3` is cited in the module docstring, in the manifest's own header
    and in what `--bless` PRINTS to a human, and all of those became false at once. The citation
    is load-bearing here in a way it is not elsewhere: it is the evidence that the directory this
    gate protects is invisible to git.
    """
    lines = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert lines[2].strip() == "_plan/", lines[:6]
    assert pl.DEFAULT_PLAN_ROOT.name == "_plan"
    for where, text in (
        ("the module docstring", pl.__doc__ or ""),
        ("the manifest header", pl.MANIFEST_HEADER),
        ("the shipped manifest", REAL_MANIFEST.read_text(encoding="utf-8")),
    ):
        assert ".gitignore:3" in text, where


def test_the_pinned_digest_is_sha256_over_every_byte_and_not_over_a_first_block() -> None:
    """The mutation: digest `read_bytes(...)[:4096]` in both `--bless` and the check.

    All sixty-three tests stayed green once the manifest was re-blessed in the same change --
    C55's shape exactly: a gate that still runs, still exits 0, and no longer covers what it says
    it covers. Every fixture document is smaller than one block, so no fixture could show it. The
    digest is pinned against `hashlib` over the WHOLE file -- the one side of this equality that
    does not come from us -- and over a document large enough that a truncation at any plausible
    block size changes the answer.
    """
    manifest = pl.parse_manifest(REAL_MANIFEST.read_text(encoding="utf-8"), REAL_MANIFEST)
    biggest = max(manifest.documents, key=lambda rel: (REAL_PLAN / rel).stat().st_size)
    data = (REAL_PLAN / biggest).read_bytes()
    assert len(data) > 100_000, (biggest, len(data))
    assert manifest.documents[biggest] == hashlib.sha256(data).hexdigest()
    assert pl.digest(data) == hashlib.sha256(data).hexdigest()
    for block in (512, 4096, 65536):
        assert hashlib.sha256(data[:block]).hexdigest() != manifest.documents[biggest]

    charter = REAL_CHARTER.read_bytes()
    region = b"".join(charter.splitlines(keepends=True)[: manifest.region_last_line])
    assert len(region) > 100_000, len(region)
    assert manifest.charter_digest == hashlib.sha256(region).hexdigest()


def test_a_byte_changed_at_the_far_end_of_a_long_document_fails(tmp_path: Path) -> None:
    """The same mutation, made visible at the fixture level.

    Every other `documents-frozen` mutation here lands in the first line of a forty-byte file, so
    a gate that read one block would have passed all of them. This document is longer than
    sixteen blocks and the byte that moves is its last.
    """
    plan = build_plan(tmp_path / "plan")
    long_doc = plan / "02-a-long-settled-document.md"
    body = "".join(
        f"Line {n:05d} of a settled document longer than one read block.\n" for n in range(1200)
    )
    long_doc.write_text(f"# Long\n\n{body}", encoding="utf-8", newline="\n")
    manifest = tmp_path / "plan.sha256"
    bless(plan, manifest)
    code, report = run(plan, manifest)
    assert code == pl.EXIT_CLEAN, report

    before = long_doc.read_bytes()
    assert len(before) > 16 * 4096, len(before)
    mutated = bytearray(before)
    mutated[-2:-1] = b"X"
    long_doc.write_bytes(bytes(mutated))
    assert len(long_doc.read_bytes()) == len(before), "one byte, not one line"

    code, report = run(plan, manifest)
    assert code == pl.EXIT_FAIL, report
    assert "FAIL documents-frozen: 02-a-long-settled-document.md:" in report


@pytest.mark.parametrize(
    "replacement",
    [
        pytest.param("THE FIRST FIXTURE SENTENCE", id="the same letters in another case"),
        pytest.param("the first fixture sentence", id="one letter in another case"),
        pytest.param("The first fixture sentenc", id="the last character dropped"),
        pytest.param("The first fixture sentiment", id="the tail rewritten"),
    ],
)
def test_a_phrase_that_only_nearly_resolves_in_sections_one_to_eight_still_fails(
    blessed: tuple[Path, Path], replacement: str
) -> None:
    """The mutations: `region.lower().find(phrase.lower())`, and `region.find(phrase[:12])`.

    Both stayed green: every existing miss test replaces the phrase with text sharing no prefix
    and no letters with it, so a case-folded or prefix-only search misses it too. E-Q2's sentence
    is *"resolves each row's quoted phrase against `charter.md` and fails on a miss"*, and a
    phrase that differs in one letter's case, or in its last character, is a miss.
    """
    plan, manifest = blessed
    charter = plan / pl.CHARTER_REL
    text = charter.read_text(encoding="utf-8")
    original = "The first fixture sentence, which E1 quotes"
    assert text.count(original) == 1, "the section 1 sentence, not the row that quotes it"
    charter.write_text(
        text.replace(original, f"{replacement}, which E1 quotes", 1),
        encoding="utf-8",
        newline="\n",
    )
    assert "`The first fixture sentence`" in charter.read_text(encoding="utf-8"), "row intact"

    code, report = run(plan, manifest)
    assert code == pl.EXIT_FAIL, report
    assert "FAIL errata-phrases" in report
    assert pl.PHRASE_MISS in report


def test_the_allow_list_is_matched_exactly_and_never_by_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The mutation: `not any(rel.startswith(row) for row in WRITABLE_NOTES)`.

    It stayed green because no row on the list today is a prefix of another path -- so the suite
    proved the allow-list wide enough and never proved it narrow enough. Under prefix matching a
    single `_notes/` row switches every rule off for the charter, the terminology lock and all
    423 snapshots at once, which is the off switch `WRITABLE_NOTES`'s comment says it is not.
    """
    row = next(iter(pl.WRITABLE_NOTES))
    assert pl.settled_documents((row,)) == (), "an exact row is exempt"
    near = (f"{row}.bak", row.removesuffix(".md"), f"{row}/nested.md")
    assert pl.settled_documents(near) == near, "a path that merely extends a row is settled law"

    monkeypatch.setitem(pl.WRITABLE_NOTES, "_notes/", "a directory row, which is an off switch.")
    covered = pl.settled_documents(
        (pl.TERMINOLOGY_REL, "_notes/.snapshots/s12d-pre/charter.md", "00-vision.md", row)
    )
    assert covered == (pl.TERMINOLOGY_REL, "_notes/.snapshots/s12d-pre/charter.md", "00-vision.md")
    assert pl.CHARTER_REL not in covered, "the charter is charter-frozen's, by region"


def test_a_forged_allow_list_row_fails_the_gate_itself_and_not_only_its_own_unit_test(
    blessed: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mutation: drop `no_row_switches_off_settled_law()` from `check_documents_frozen`.

    It stayed green because the only test of that guard calls the FUNCTION. The
    `NEVER_WRITABLE_NOTES` docstring says the guard *"runs inside the gate as well as inside the
    tests"*, and that sentence was the only thing asserting it -- prose, not a check. This runs
    the gate.
    """
    plan, manifest = blessed
    monkeypatch.setitem(
        pl.WRITABLE_NOTES, pl.TERMINOLOGY_REL, "a reason somebody wrote to get past a gate."
    )
    code, report = run(plan, manifest)
    assert code == pl.EXIT_FAIL, report
    assert f"FAIL {pl.RULE_DOCUMENTS}" in report
    assert "is named by 18-api-sketch.md:3238's corpus and is never writable" in report


def test_a_section_nine_row_with_too_few_cells_is_exit_two_rather_than_a_silent_skip(
    blessed: tuple[Path, Path],
) -> None:
    """The mutation: `continue` where `errata_rows` raises on a short row.

    It stayed green because no test had ever damaged a row's shape. `ERRATA_ROW_CELLS`'s
    docstring says a narrower row *"is a row this parser has mis-read, which is EXIT_NOT_RUN and
    never a silent skip"* -- and under the mutation the run exits 1 with a count mismatch, which
    reads as a defect in the charter rather than as a parser that stopped parsing.
    """
    plan, manifest = blessed
    charter = plan / pl.CHARTER_REL
    text = charter.read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if 'id="e2"' in line)
    charter.write_text(
        text.replace(row, '| <a id="e2"></a>**E2** | :12 | `A second fixture sentence` |', 1),
        encoding="utf-8",
        newline="\n",
    )
    code, report = run(plan, manifest)
    assert code == pl.EXIT_NOT_RUN, report
    assert "is a section 9.2 row with 3 cells, not 6" in report


def test_the_frozen_region_is_the_anchored_one_because_the_manifest_cannot_disagree(
    blessed: tuple[Path, Path],
) -> None:
    """The mutation: digest `lines[: manifest.region_last_line]` instead of the anchored region.

    It stayed green, and it is EQUIVALENT rather than uncaught -- for a reason worth pinning,
    because it is what the anchored design leans on. `_parse_charter_row` refuses a manifest whose
    `region=1-N` and `heading=M` are not adjacent, and `charter-frozen` fails when the heading on
    disk is not the pinned one; between them, `N` is the line above the heading whenever a digest
    is compared at all. Drop either half -- the variant that also removes the heading check does
    exactly that -- and `test_a_line_appended_at_the_end_of_section_eight...` goes red.
    """
    plan, manifest = blessed
    parsed = pl.parse_manifest(manifest.read_text(encoding="utf-8"), manifest)
    assert parsed.region_last_line + 1 == parsed.heading_line
    charter = (plan / pl.CHARTER_REL).read_bytes()
    region, matches = pl.frozen_region(charter)
    assert matches == (parsed.heading_line,)
    assert region == b"".join(charter.splitlines(keepends=True)[: parsed.region_last_line])

    text = manifest.read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if line.startswith(pl.RULE_CHARTER))
    shifted = row.replace(
        f"region=1-{parsed.region_last_line}", f"region=1-{parsed.region_last_line - 1}"
    )
    manifest.write_text(text.replace(row, shifted, 1), encoding="utf-8", newline="\n")
    code, report = run(plan, manifest)
    assert code == pl.EXIT_NOT_RUN, report
    assert "disagree" in report


# ---------------------------------------------------------------------------------------------
# Rule 5, `cli-verbs`: 11 section 8.6 clause d2's CLI half
# ---------------------------------------------------------------------------------------------


def test_every_cli_spelling_the_real_plan_writes_resolves_against_the_register() -> None:
    """d2's own assertion, over the tree this repository ships.

    *"every … `ow <group> <verb>` … named in a document exists in its register"*. The register is
    `omniweave.surface.registry`'s four CLI constants and this is the first run in which the claim
    is a check rather than a sentence: 185 spellings over 23 documents, every one of them resolved,
    absent by declaration, or unrostered with a defect number beside it.
    """
    findings, notes = pl.check_cli_verbs(REAL_PLAN)
    assert findings == [], [f.render() for f in findings]
    assert "0 unresolved" in notes[0], notes[0]


def test_the_note_reports_the_corpus_and_both_exception_registers() -> None:
    _, notes = pl.check_cli_verbs(REAL_PLAN)
    assert "43 roots" in notes[0]
    assert f"{len(CLI_ABSENT)} absent" in notes[0]
    assert f"{len(CLI_UNROSTERED)} unrostered" in notes[0]
    assert len(notes) == 1 + len(CLI_UNROSTERED), "every owed row is named, not counted"


def test_every_unrostered_row_is_a_spelling_the_real_plan_actually_writes() -> None:
    """The ratchet, from the other side: a row recording a defect must have one."""
    written = set()
    for rel in pl.codes_corpus(REAL_PLAN):
        text = (REAL_PLAN / rel).read_text(encoding="utf-8")
        written.update(words for words, _, _ in pl.cli_spellings(text, rel))
    for spelling in (*CLI_ABSENT, *CLI_UNROSTERED):
        assert spelling in written, f"ow {' '.join(spelling)} is registered and never written"


def test_cli_verbs_fails_on_a_verb_no_roster_carries(blessed: tuple[Path, Path]) -> None:
    """d2's worked example, run for real: *"`ow store rebalance` — not in the ACTIONS registry"*."""
    plan, _ = blessed
    (plan / "07-store.md").write_text(
        "# Store\n\nRun `ow store reshard` when a shard grows.\n", encoding="utf-8", newline="\n"
    )
    findings, _ = pl.check_cli_verbs(plan)
    assert len(findings) == 1
    assert "ow store reshard -- no-such-verb" in findings[0].detail
    assert "nearest: ow store" in findings[0].detail
    assert findings[0].path == "07-store.md:3"


def test_cli_verbs_fails_on_a_root_the_group_registry_does_not_declare(
    blessed: tuple[Path, Path],
) -> None:
    plan, _ = blessed
    (plan / "07-store.md").write_text(
        "# Store\n\n`ow frobnicate` is not a thing.\n", encoding="utf-8", newline="\n"
    )
    findings, _ = pl.check_cli_verbs(plan)
    assert [f.detail.split(" --")[0] for f in findings] == ["ow frobnicate"]
    assert "no-such-root" in findings[0].detail


def test_cli_verbs_fails_on_a_register_row_no_document_writes(
    blessed: tuple[Path, Path],
) -> None:
    """The ratchet. A `CLI_UNROSTERED` row is a defect record, so it must go when the defect does.

    Without this half the register only ever grows, and a register that only grows stops describing
    the documents it was built from -- which is the C41/C55/D114 family: a check that silently
    stops covering the thing it exists to cover.
    """
    plan, _ = blessed
    interfaces = plan / "10-interfaces.md"
    kept = [
        line
        for line in interfaces.read_text(encoding="utf-8").splitlines()
        if "ow resume" not in line
    ]
    interfaces.write_text("\n".join(kept) + "\n", encoding="utf-8", newline="\n")
    findings, _ = pl.check_cli_verbs(plan)
    assert len(findings) == 1
    assert "CLI_UNROSTERED carries 'ow resume'" in findings[0].detail
    assert "strike the row with the sentence that needed it" in findings[0].detail


def test_cli_verbs_is_green_on_the_fixture_before_any_mutation(blessed: tuple[Path, Path]) -> None:
    plan, _ = blessed
    findings, _ = pl.check_cli_verbs(plan)
    assert findings == []


def test_a_spelling_is_read_only_from_a_span_that_starts_with_it() -> None:
    """Outside a code span the plan writes `ow` as an ordinary word, and a span that merely
    CONTAINS one is usually prose about it."""
    text = (
        "Run `ow store verify` now. Say ow store frobnicate in prose, or `see ow store nonsense`.\n"
    )
    assert [words for words, _, _ in pl.cli_spellings(text, "x.md")] == [("store", "verify")]


def test_a_spelling_stops_at_the_first_token_that_is_not_a_word() -> None:
    """A flag, a quoted question and a `<placeholder>` all end a spelling instead of joining it."""
    text = (
        '`ow query "<question>" --corpus N`\n'
        "`ow store rm --doc <ord>`\n"
        "`ow graph merge e412 e997 --reason '...'`\n"
        "`ow surface emit --check`\n"
    )
    assert [words for words, _, _ in pl.cli_spellings(text, "x.md")] == [
        ("query",),
        ("store", "rm"),
        ("graph", "merge", "e412", "e997"),
        ("surface", "emit"),
    ]


def test_the_line_number_reported_is_the_line_the_spelling_is_on() -> None:
    text = "one\ntwo\n`ow doctor` is on line three\n"
    assert [(w, p, n) for w, p, n in pl.cli_spellings(text, "x.md")] == [(("doctor",), "x.md", 3)]


def test_the_rule_is_named_in_the_report_like_the_other_four(blessed: tuple[Path, Path]) -> None:
    plan, manifest = blessed
    code, report = run(plan, manifest)
    assert code == pl.EXIT_CLEAN
    assert "ok   cli-verbs" in report
    assert pl.RULE_CLI == "cli-verbs"
