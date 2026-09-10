"""`tools/p2_demo.py` -- P2's demo runner, and the four things about it that can be pinned.

16-roadmap.md:434-440 is five assertions and the script runs all five, so most of what this file
can assert is what a run REPORTS. Four groups, and each exists because the corresponding
mistake is one this project has already made once -- the fourth of them in a mutation pass over
this very file:

1. **The frame arithmetic, pinned to literals.** Clause 3 exists because
   `blocks/000063.ndjson` does not exist in a small corpus, and a demo that quietly checked frame
   0 and printed the roadmap's sentence would be the exact failure the clause is written against.
   The arithmetic that decides which frame is reachable is therefore pure, exported and pinned
   here at `7940` and `63` -- numbers written out, not recomputed from
   `FRAME_TARGET_BLOCKS` by the test, because a test that re-derives its expected value from the
   thing under test pins agreement and not value.
2. **Exit 2 is not exit 1.** `tools/gate_crash.py`'s own suite makes the same distinction and
   11-repo-layout.md section 6.8's refusal of a check that cannot fail is why: a demo that could
   not run must never read as a demo whose clauses held.
3. **A half-enforced clause says which half.** The `NOT enforced:` line is the whole reason
   `Check` has two fields instead of one, and `.github/workflows/ci.yml`'s G28 step is the
   worked example. A report that dropped it would still pass every other assertion here.

4. **Every clause is made to FAIL.** Groups 1-3 above assert what a HEALTHY run prints, and a
   mutation pass proved that is not enough: with only those groups on the file, every single
   predicate inside clauses 1-5 could be deleted -- the root-cite comparison, the page-row count,
   the `origin_driver` stamp, INV-10's byte re-derivation, the frame's `sha256`, the
   `ZIP_DEFLATED` demand, `block_history` being empty, the crash gate's own exit code -- and the
   suite stayed green, because "clause N printed PASS over a healthy store" is true of a clause
   that checks nothing at all. Section 6 therefore damages a store, a `.owdoc` and a stand-in
   crash gate on purpose and asserts that the matching clause reports the matching FINDING by its
   text. A clause that stopped checking now goes red.

Plus one plan-text assertion, because clause 5 disagrees with a roadmap sentence and the
disagreement has to be anchored to the document rather than to this author's reading:
03-document-model.md's rule table says an edited paragraph's cite is **carried**.

**WHY THE END-TO-END TEST CAN SKIP, AND WHEN IT MAY NOT.**
`fixtures/gen/gen_5000p_pdf.py` (F1) and `tools/p2_stub_parse.py` (F2) are separate work items
landing in the same wave, so a tree without them must skip rather than fail. But `EXIT_NOT_RUN`
is *also* what `main` returns when the demo raises anything in `(MissingContractError, ValueError,
KeyError, OSError)`, which is most of the ways a defect inside the script shows up -- and a bare
`skip` on `EXIT_NOT_RUN` turns every one of those into a green run. That is not hypothetical: a
mutation that stopped clause 5 editing its paragraph crashed the ingest, exited 2, and this file
reported `2 skipped, 16 passed`. So the skip is now CONDITIONAL on a contract file being genuinely
absent from disk, and `EXIT_NOT_RUN` with all three scripts present is a failure with the reason
quoted.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
import zipfile
from collections.abc import Sequence
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final, NamedTuple

import pytest
from omniweave_core.archive.frames import FRAMES_MEMBER, frame_member
from omniweave_core.archive.owdoc import REQUIRED_KEYS
from omniweave_core.store import sqlite as ow
from omniweave_core.store.verify import ClauseResult, ClauseState, VerifyClause, VerifyReport

# `tools/p2_demo.py` is a script and not a distribution, so `spec_from_file_location` loads it --
# the same mechanism `test_gate_crash.py` uses, and for the same two reasons: not
# `importlib.import_module`, which is banned outside `host/`, and not a `sys.path` mutation,
# which would leak into every later test in the session.
REPO_ROOT = Path(__file__).resolve().parents[4]
TOOL_PATH = REPO_ROOT / "tools" / "p2_demo.py"

_SPEC = importlib.util.spec_from_file_location("omniweave_p2_demo", TOOL_PATH)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover -- the file is in this repository.
    message = f"cannot load {TOOL_PATH}"
    raise RuntimeError(message)
demo = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = demo
_SPEC.loader.exec_module(demo)


def _run(argv: list[str]) -> tuple[int, str]:
    """The demo, with its report captured. Nothing here writes to the real stdout."""
    buffer = StringIO()
    code = demo.main(argv, out=buffer)
    return code, buffer.getvalue()


def _absent_contracts() -> tuple[str, ...]:
    """The scripts the demo drives that are not on disk yet, named as the report names them.

    The three are loaded at `p2_demo` import time and are `None` when their file is missing, so
    this is a statement about the tree and not about the run. It is what separates "F2 has not
    landed" -- a legitimate skip while a sibling work item is in flight -- from "the demo raised",
    which `main` also reports as `EXIT_NOT_RUN` and which must never read as a skip.
    """
    return tuple(
        path.name
        for module, path in (
            (demo.GEN, demo.GEN_PATH),
            (demo.STUB, demo.STUB_PATH),
            (demo.GATE, demo.GATE_CRASH_PATH),
        )
        if module is None
    )


def _skip_only_if_a_contract_is_missing(code: int, report: str) -> None:
    """Allow `EXIT_NOT_RUN` to skip a test only while a contract file is genuinely absent.

    A demo that exits 2 with F1, F2 and `gate_crash.py` all present did not decline to run: it
    raised, and `main` catches `MissingContractError`, `ValueError`, `KeyError` and `OSError`
    alike. Skipping on that is the shape 11-repo-layout.md section 6.8 refuses -- a check that
    reports success because it never ran.
    """
    if code != demo.EXIT_NOT_RUN:
        return
    said = [line for line in report.splitlines() if "DID NOT RUN" in line]
    reason = said[-1] if said else report[-200:]
    absent = _absent_contracts()
    assert absent, (
        f"the demo exited {demo.EXIT_NOT_RUN} although F1, F2 and tools/gate_crash.py are all on "
        f"disk, so it RAISED rather than declined to run: {reason}"
    )
    pytest.skip(f"{', '.join(absent)} is not on disk yet; the demo did not run: {reason}")


# ---------------------------------------------------------------------------------------------
# 1. The frame arithmetic
# ---------------------------------------------------------------------------------------------


def test_the_member_the_roadmap_names_is_the_sixty_third_frame() -> None:
    """`blocks/000063.ndjson` -- 16-roadmap.md:439's spelling, six digits, from frames.py:151."""
    assert demo.ROADMAP_FRAME == 63
    assert frame_member(demo.ROADMAP_FRAME) == "blocks/000063.ndjson"


def test_reaching_the_roadmaps_frame_takes_seven_thousand_nine_hundred_and_forty_pages() -> None:
    """The number clause 3 prints when it cannot open the member the roadmap names.

    Written out rather than recomputed. `63 * 8192 + 1 = 516,097` blocks are needed and one
    document root is not a page's, so `ceil(516096 / 65) = 7,940`. A test that wrote
    `ROADMAP_FRAME * FRAME_TARGET_BLOCKS` on the right-hand side would agree with the function
    however the function was wrong.
    """
    assert demo.pages_for_frame(63, blocks_per_page=65) == 7940


def test_one_page_fewer_than_that_does_not_reach_the_frame_and_one_more_does() -> None:
    """The boundary, from both sides. A ceiling that rounded the wrong way passes neither half.

    `7,940 * 65 + 1 = 516,101` blocks, whose last block is ordinal 516,100 and lands in frame 63.
    `7,939 * 65 + 1 = 516,036`, whose last is 516,035 and lands in frame 62.
    """
    assert demo.frame_index_of(7940 * 65 + 1 - 1) == 63
    assert demo.frame_index_of(7939 * 65 + 1 - 1) == 62


def test_the_first_block_of_a_frame_and_the_last_block_of_the_one_before_it() -> None:
    """Integer division at the join, pinned with literals on both sides of 516,096."""
    assert demo.frame_index_of(516_095) == 62
    assert demo.frame_index_of(516_096) == 63
    assert demo.frame_index_of(0) == 0


def test_the_frame_arithmetic_refuses_nonsense_rather_than_returning_it() -> None:
    """A negative ordinal or a zero page size would silently produce a frame number."""
    with pytest.raises(ValueError, match="non-negative"):
        demo.frame_index_of(-1)
    with pytest.raises(ValueError, match="positive"):
        demo.pages_for_frame(63, blocks_per_page=0)


def test_this_fixtures_page_is_sixty_five_blocks_and_thirty_two_of_its_runs_are_eight() -> None:
    """`FIXTURE_BLOCKS_PER_PAGE`, against F1's own constants. Skips when F1 is not on disk.

    The coalescing is the point: F1 emits `PARAGRAPHS_PER_PAGE * LINES_PER_PARAGRAPH` = 32 body
    runs and F3 folds each paragraph's four runs into ONE block, so a page is 8 paragraph blocks
    and not 32. Getting that wrong multiplies every frame number in clause 3's advice by four.
    """
    if demo.GEN is None:
        pytest.skip(f"{demo.GEN_PATH} is not on disk yet (F1 lands in this wave)")
    assert demo.predicted_blocks_per_page(demo.GEN) == demo.FIXTURE_BLOCKS_PER_PAGE == 65
    assert demo.GEN.PARAGRAPHS_PER_PAGE * demo.GEN.LINES_PER_PARAGRAPH == 32


# ---------------------------------------------------------------------------------------------
# 2. Exit 2 is not exit 1
# ---------------------------------------------------------------------------------------------


def test_a_page_count_below_one_is_a_demo_that_did_not_run() -> None:
    """Exit 2 and a named reason, not a traceback and not a green run over zero pages."""
    code, report = _run(["--pages", "0"])
    assert code == demo.EXIT_NOT_RUN
    assert "DID NOT RUN" in report


def test_a_kill_point_count_below_one_is_a_demo_that_did_not_run() -> None:
    """Clause 4 with zero points would report `crash ok` over nothing at all."""
    code, report = _run(["--kill-points", "0"])
    assert code == demo.EXIT_NOT_RUN
    assert "DID NOT RUN" in report


def test_a_missing_contract_module_is_exit_two_and_names_the_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """F1 absent must be "did not run", never "no clause failed".

    Monkeypatched rather than asserted against the tree, because the tree's answer changes the
    day the other agent's file lands and this property must not.
    """
    monkeypatch.setattr(demo, "GEN", None)
    code, report = _run(["--pages", "1", "--workspace", str(tmp_path)])
    assert code == demo.EXIT_NOT_RUN
    assert "fixtures/gen/gen_5000p_pdf.py" in report
    assert "F1" in report


def test_the_three_exit_codes_are_distinct() -> None:
    """0, 1 and 2 mean three different things and `gate_crash.py` says why two of them differ."""
    assert len({demo.EXIT_CLEAN, demo.EXIT_FAIL, demo.EXIT_NOT_RUN}) == 3


# ---------------------------------------------------------------------------------------------
# 3. The report says which half
# ---------------------------------------------------------------------------------------------


def _check(clause: int, *, ok: bool, deferred: str = "") -> object:
    return demo.Check(
        clause=clause,
        title=f"clause {clause}",
        ok=ok,
        enforced="the half that ran",
        deferred=deferred,
    )


def test_a_clause_that_enforced_half_prints_which_half_even_when_it_passed() -> None:
    """A passing half-check is the dangerous one, so `NOT enforced:` prints on a PASS too."""
    buffer = StringIO()
    code = demo._report(
        [_check(3, ok=True, deferred="the roadmap's own frame is unreachable")],
        (),
        0.1,
        demo._emitter(buffer),
    )
    report = buffer.getvalue()
    assert code == demo.EXIT_CLEAN
    assert "PASS" in report
    assert "NOT enforced: the roadmap's own frame is unreachable" in report


def test_a_clause_that_enforced_all_of_its_sentence_prints_no_not_enforced_line() -> None:
    """Otherwise the line would be decoration rather than a statement about this run."""
    buffer = StringIO()
    demo._report([_check(1, ok=True)], (), 0.1, demo._emitter(buffer))
    assert "NOT enforced:" not in buffer.getvalue()


def test_one_failing_clause_makes_the_run_fail_and_the_final_line_names_it() -> None:
    """Exit 1, and the clause number in the last line: a CI log is read from the bottom."""
    buffer = StringIO()
    code = demo._report([_check(1, ok=True), _check(2, ok=False)], (), 0.1, demo._emitter(buffer))
    report = buffer.getvalue()
    assert code == demo.EXIT_FAIL
    assert "p2 demo FAIL  clause(s) 2 did not hold" in report


def test_a_skipped_clause_is_reported_rather_than_silently_absent() -> None:
    """`--skip 4` must leave a mark. A clause that vanished from the table reads as a clause
    that passed, which is the same lie as a check that cannot fail."""
    buffer = StringIO()
    demo._report([_check(1, ok=True)], (4,), 0.1, demo._emitter(buffer))
    report = buffer.getvalue()
    assert "SKIPPED" in report
    assert "--skip 4" in report


def test_the_note_cap_counts_every_finding_it_declines_to_list() -> None:
    """A wrong byte offset produces one finding per block; the cap must not shrink the count."""
    findings = [f"finding {n}" for n in range(50)]
    capped = demo._capped(findings)
    assert len(capped) == demo.MAX_NOTES + 1
    assert capped[-1] == f"... and {50 - demo.MAX_NOTES} more finding(s) not listed (MAX_NOTES)"
    assert demo._capped(findings[:3]) == tuple(findings[:3])


# ---------------------------------------------------------------------------------------------
# 4. Clause 5's disagreement with the roadmap, anchored to the plan
# ---------------------------------------------------------------------------------------------


def test_the_plan_says_an_edited_paragraph_carries_its_cite(plan: object) -> None:
    """03-document-model.md's rule table, read rather than paraphrased.

    Clause 5 asserts the rule-2 outcome and reports 16-roadmap.md:438-440's "fresh `n` ... and
    leave a `block_history` row" as refuted. That claim rests on two lines of one document, so
    the test reads them: rule 2's row is *"equal `addr` **and** `kind`, digest changed"* with
    `carried` in the `cite` column, and the worked example's edited paragraph reports
    `retired = 0`.
    """
    plan.require()  # type: ignore[attr-defined]
    text = plan.text("03-document-model.md")  # type: ignore[attr-defined]
    rule_two = [
        line
        for line in text.splitlines()
        if line.startswith("| 2 |") and "addr" in line and "kind" in line
    ]
    assert len(rule_two) == 1, f"expected one rule-2 row in 03's rebind table, found {rule_two}"
    cells = [cell.strip() for cell in rule_two[0].strip("|").split("|")]
    assert cells[3] == "carried", (
        f"rule 2's cite column reads {cells[3]!r}. Clause 5 asserts it is 'carried'; if the plan "
        f"changed, the clause and its NOT-enforced line must change with it"
    )
    assert "`carried = 4, revised = 2, created = 1, retired = 0`" in text, (
        "03's worked example no longer reports retired = 0 for a one-paragraph edit"
    )


# ---------------------------------------------------------------------------------------------
# 5. End to end
# ---------------------------------------------------------------------------------------------


def test_the_demo_runs_all_five_clauses_over_a_two_page_corpus(tmp_path: Path) -> None:
    """The whole script, at the smallest corpus that still has two pages to rebind across.

    `--in-process` for clause 4: the real signal is `tools/gate_crash.py`'s own subject and its
    own suite asserts it, and spawning children here would make this test the slowest in the
    unit tree for a property it does not own.

    **All five clauses are asserted green.** An earlier revision of this file exempted clause 2,
    because `BlobStore.put` used to corrupt any blob containing `0x0A` on Windows -- `os.open`
    without `os.O_BINARY` -- and the clause correctly reported that as a failure. `blobs.py:143`
    now carries `_O_BINARY` and `blobs.py:594` passes it, so the exemption has outlived its
    defect and keeping it would leave clause 2 the one clause whose verdict nothing reads.

    **What this test cannot do, and section 6 does instead.** Every assertion here is about a
    HEALTHY store, so it catches a clause that fails and never a clause that stopped checking.
    Section 6 owns that half.
    """
    code, report = _run(["--pages", "2", "--workspace", str(tmp_path), "--in-process", "--keep"])
    _skip_only_if_a_contract_is_missing(code, report)

    for clause in demo.CLAUSES:
        assert f"\n  {clause} " in report, f"clause {clause} is missing from the report table"
    verdicts = _verdicts(report)
    assert verdicts.keys() == set(demo.CLAUSES)
    for clause in demo.CLAUSES:
        assert verdicts[clause] == "PASS", f"clause {clause} failed:\n{report}"
    assert code == demo.EXIT_CLEAN, f"every clause passed and the run exited {code}"


def test_the_demo_reports_which_frame_clause_three_actually_opened(tmp_path: Path) -> None:
    """The clause-3 rule, at a corpus that cannot reach `blocks/000063.ndjson`.

    A run that printed 16-roadmap.md:439's sentence over frame 0 would pass every other
    assertion in this file. What this pins is that it named the member it opened, said the
    roadmap's own member was unreachable, and printed the page count that would reach it.
    """
    code, report = _run(
        ["--pages", "2", "--workspace", str(tmp_path), "--in-process", "--skip", "4"]
    )
    _skip_only_if_a_contract_is_missing(code, report)
    assert "frame checked: blocks/000000.ndjson" in report
    assert "blocks/000063.ndjson does not exist" in report
    assert "--pages 7940" in report
    assert "--skip 4 was passed" in report, "a skipped clause left no mark in the table"
    assert "SIGKILL the writer mid-commit" not in report, "clause 4 ran despite --skip 4"


def _verdicts(report: str) -> dict[int, str]:
    """`{clause: 'PASS'|'FAIL'}` off the printed table, so the test reads what a human reads."""
    found: dict[int, str] = {}
    for line in report.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].isdigit() and parts[1] in {"PASS", "FAIL"}:
            found[int(parts[0])] = parts[1]
    return found


# ---------------------------------------------------------------------------------------------
# 6. Every clause, made to FAIL
# ---------------------------------------------------------------------------------------------
#
# Sections 1-5 assert what a healthy run prints. That is exactly the assertion a clause which
# checks nothing also satisfies, and a mutation pass proved it: deleting the root-cite
# comparison, the page-row count, the `origin_driver` stamp, INV-10's byte re-derivation, the
# frame's `sha256`, the `ZIP_DEFLATED` demand, `block_history` being empty, or the crash gate's
# own exit code left this file green in every case. Everything below damages one input on
# purpose and asserts the clause reports the matching finding BY ITS TEXT -- because
# `not check.ok` alone is satisfied by any failure at all, including one the damage caused
# somewhere else.

INGEST_PAGES: Final = 2
"""Two pages, which is the smallest corpus with a second page to rebind across."""

MANGLED: Final = "this text is not what the retained part bytes say"
"""What a block's `text` is overwritten with to make INV-10's bytes branch disagree."""


class Ingested(NamedTuple):
    """One completed `p2_demo` ingest, built once per module and copied per damaging test."""

    root: Path
    path: Path
    cas: Path
    pdf: Path
    key: bytes
    producer_id: int
    record: Any


@pytest.fixture(scope="module")
def ingested(tmp_path_factory: pytest.TempPathFactory) -> Ingested:
    """`p2_demo`'s own clause-1 ingest, run once.

    Module-scoped because it is the same work the demo does at start-up and eleven tests want a
    store to damage; each of those copies it first, so no test can see another's damage.
    """
    for module, path in ((demo.GEN, demo.GEN_PATH), (demo.STUB, demo.STUB_PATH)):
        if module is None:
            pytest.skip(f"{path.name} is not on disk yet")
    root = tmp_path_factory.mktemp("p2-demo-ingest")
    pdf = Path(demo.GEN.generate(root / "gen.pdf", pages=INGEST_PAGES))
    key = hashlib.sha256(pdf.read_bytes()).digest()[:16]
    path, cas, producer_id = demo._fresh_store(root, demo.STUB)
    record = demo._ingest(path, cas, producer_id=producer_id, stub=demo.STUB, pdf=pdf, key=key)
    return Ingested(
        root=root, path=path, cas=cas, pdf=pdf, key=key, producer_id=producer_id, record=record
    )


def _copy(store: Ingested, into: Path) -> tuple[Path, Path]:
    """A private copy of the whole workspace, so a test may damage it and nothing else.

    The whole directory and not just the `.owstore`: a WAL left beside it is part of the store's
    state, and copying the file alone would silently copy a different database.
    """
    work = into / "store"
    shutil.copytree(store.root, work)
    return work / "index.owstore", work / "cas"


def _damage(path: Path, statements: Sequence[tuple[str, tuple[Any, ...]]]) -> None:
    """Run write statements against a copied store. `ow.connect`, so no test imports `sqlite3`."""
    connection = ow.connect(path)
    try:
        for sql, parameters in statements:
            connection.execute(sql, parameters)
        connection.commit()
    finally:
        connection.close()


def _notes(check: Any) -> str:
    """One clause's notes as one string, so an assertion names the finding and not an index."""
    return "\n".join(check.notes)


# --- clause 1 --------------------------------------------------------------------------------


def test_clause_one_holds_over_the_store_the_stub_driver_actually_wrote(
    ingested: Ingested,
) -> None:
    """The positive control. Without it every negative below could pass by failing always."""
    check = demo._clause1(ingested.path, ingested.record, INGEST_PAGES, demo.STUB, demo.GEN)
    assert check.ok, _notes(check)
    assert check.clause == 1


def test_clause_one_fails_when_the_page_rows_do_not_match_the_pages_generated(
    ingested: Ingested,
) -> None:
    """A driver that dropped a page must not read as a driver that ingested every page."""
    check = demo._clause1(ingested.path, ingested.record, INGEST_PAGES + 1, demo.STUB, demo.GEN)
    assert not check.ok
    assert f"{INGEST_PAGES} page row(s) for {INGEST_PAGES + 1} generated page(s)" in _notes(check)


def test_clause_one_fails_when_a_block_carries_another_drivers_stamp(
    ingested: Ingested, tmp_path: Path
) -> None:
    """`origin_driver` is one of D3's ownership columns (03:302-304); a foreign row is a finding.

    The rows are stamped by the sink and are unwritable by a driver, so the only way to make one
    foreign is to write it behind the sink's back -- which is what this does.
    """
    path, _cas = _copy(ingested, tmp_path)
    _damage(
        path,
        [
            (
                "UPDATE block SET origin_driver = 'parse.pdf.somebody-else' "
                "WHERE block_id = (SELECT min(block_id) FROM block)",
                (),
            )
        ],
    )
    check = demo._clause1(path, ingested.record, INGEST_PAGES, demo.STUB, demo.GEN)
    assert not check.ok
    assert "1 block(s) carry an origin_driver other than" in _notes(check)


def test_clause_one_fails_when_the_root_block_does_not_carry_the_first_cite(
    ingested: Ingested, tmp_path: Path
) -> None:
    """`d1#1` is 03:1146's literal: the first document is `d1` and its root takes `n = 1`."""
    path, _cas = _copy(ingested, tmp_path)
    _damage(path, [("UPDATE block SET cite = 'd1#409' WHERE parent_id IS NULL", ())])
    check = demo._clause1(path, ingested.record, INGEST_PAGES, demo.STUB, demo.GEN)
    assert not check.ok
    assert "not ('d1#1', 'doc')" in _notes(check)


def test_the_blocks_per_page_prediction_is_read_off_the_generator_it_is_handed() -> None:
    """`predicted_blocks_per_page` must DERIVE, and a module with F1's real numbers cannot say so.

    `predicted_blocks_per_page(GEN) == FIXTURE_BLOCKS_PER_PAGE == 65` is true of a function that
    returns the constant, which is the one thing `FIXTURE_BLOCKS_PER_PAGE`'s own docstring says
    the derivation exists to prevent. So the module handed in here is not F1: one page root, one
    heading, three paragraphs, one table and a 2x5 grid is `1 + 1 + 3 + 1 + 10 = 16`.
    """
    fake = SimpleNamespace(PARAGRAPHS_PER_PAGE=3, TABLE_ROWS=2, TABLE_COLS=5)
    assert demo.predicted_blocks_per_page(fake) == 16


# --- clause 2 --------------------------------------------------------------------------------


def test_the_three_verify_clauses_the_roadmap_sentence_is_about_are_named_and_are_three() -> None:
    """16-roadmap.md:435 is about digests, so `REQUIRED_VERIFY_CLAUSES` is three names, written out.

    A set emptied by accident would make clause 2 pass over a `verify_store` report in which
    nothing was PASSED at all, and no other assertion in this file would notice.
    """
    assert sorted(str(clause) for clause in demo.REQUIRED_VERIFY_CLAUSES) == [
        "block_digest",
        "cas_digest",
        "content_sha256",
    ]


def test_clause_two_reports_a_block_whose_text_the_retained_bytes_do_not_support(
    ingested: Ingested, tmp_path: Path
) -> None:
    """INV-10's bytes branch, made to disagree. This is the half `verify_store` cannot do.

    The re-derivation reads the PDF back out of the CAS and decodes the window the block's
    `OriginSpan` names, so overwriting one VERBATIM block's `text` must produce that block's
    cite and the INV-10 message. A re-derivation that compared the row's `text` to itself --
    both sides out of the same store -- would stay silent here, which is why the assertion is
    on the message and not on `check.ok`: the edited row fails the digest clause too.
    """
    path, cas = _copy(ingested, tmp_path)
    connection = ow.connect(path)
    try:
        verbatim = demo._ordinals(connection, "quote")["verbatim"]
        by_bytes = demo._ordinals(connection, "origin_span_kind")["bytes"]
        block_id, cite = connection.execute(
            "SELECT block_id, cite FROM block WHERE doc_ord = ? AND gen = ? AND quote = ? "
            "AND os_kind = ? AND text IS NOT NULL ORDER BY block_id",
            (ingested.record.doc_ord, ingested.record.gen, verbatim, by_bytes),
        ).fetchone()
        connection.execute("UPDATE block SET text = ? WHERE block_id = ?", (MANGLED, block_id))
        connection.commit()
    finally:
        connection.close()

    check = demo._clause2(path, cas, ingested.record)
    assert not check.ok
    assert "INV-10's bytes branch fails for a VERBATIM block" in _notes(check)
    assert f"{cite}: part[" in _notes(check)


def test_clause_two_fails_when_the_re_derivation_had_nothing_at_all_to_compare(
    ingested: Ingested, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Zero comparisons is a check that cannot fail, and 11-repo-layout.md section 6.8 refuses one.

    `_redrive_bytes` is replaced rather than the store emptied, because the claim under test is
    `_clause2`'s guard and not the query: a clause that reported PASS over `compared == 0` would
    be reporting that a re-derivation it never performed held.
    """
    monkeypatch.setattr(demo, "_redrive_bytes", lambda *_: (0, 0, []))
    check = demo._clause2(ingested.path, ingested.cas, ingested.record)
    assert not check.ok
    assert "a check that cannot fail" in _notes(check)


def test_clause_two_fails_when_a_required_verify_clause_did_not_run(
    ingested: Ingested, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`VerifyReport.ok` is true over an UNCHECKED clause, so clause 2 must not read `ok` alone.

    The report is the real one with `block_digest` demoted to UNCHECKED, which is exactly the
    shape a clause that silently stopped running would produce.
    """
    real = demo.verify_store

    def hobbled(connection: Any, **kwargs: Any) -> VerifyReport:
        report = real(connection, **kwargs)
        return VerifyReport(
            clauses=tuple(
                ClauseResult(result.clause, ClauseState.UNCHECKED, 0, reason="it never ran")
                if result.clause == VerifyClause.BLOCK_DIGEST
                else result
                for result in report.clauses
            ),
            at_ns=report.at_ns,
        )

    monkeypatch.setattr(demo, "verify_store", hobbled)
    check = demo._clause2(ingested.path, ingested.cas, ingested.record)
    assert not check.ok
    assert "required clause(s) not PASSED: block_digest" in _notes(check)


# --- clause 3 --------------------------------------------------------------------------------


def _wire_record() -> str:
    """One NDJSON line carrying `owdoc`'s `REQUIRED_KEYS` and nothing else."""
    return json.dumps(dict.fromkeys(sorted(REQUIRED_KEYS)))


def _archive(
    into: Path,
    *,
    lines: Sequence[str],
    sha256: str | None = None,
    blocks: int | None = None,
    compress: int = zipfile.ZIP_DEFLATED,
) -> Path:
    """A minimal `.owdoc`: one frame member and the `frames.json` row that declares it.

    Built here rather than exported from a store because the three things clause 3 asserts about
    an archive -- the declared `sha256` over the UNCOMPRESSED bytes (03:2633), the declared block
    count, and `ZIP_DEFLATED` -- are all things a real export gets right by construction. An
    archive that only ever agrees with itself cannot show that the clause is looking.
    """
    member = frame_member(0)
    raw = "".join(f"{line}\n" for line in lines).encode("utf-8")
    declared = [
        {
            "path": member,
            "blocks": len(lines) if blocks is None else blocks,
            "sha256": hashlib.sha256(raw).hexdigest() if sha256 is None else sha256,
        }
    ]
    path = into / "fabricated.owdoc"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(FRAMES_MEMBER, json.dumps(declared), zipfile.ZIP_DEFLATED)
        archive.writestr(member, raw, compress)
    return path


def _exports(monkeypatch: pytest.MonkeyPatch, archive: Path) -> None:
    """Make `_clause3` read `archive` instead of exporting one. The seam is stated, not hidden."""
    monkeypatch.setattr(
        demo,
        "export_portable",
        lambda *_, **__: SimpleNamespace(artefacts=(SimpleNamespace(path=archive),), skipped=()),
    )


def test_clause_three_holds_over_a_well_formed_frame(
    ingested: Ingested, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The positive control for the three negatives below."""
    _exports(monkeypatch, _archive(tmp_path, lines=[_wire_record(), _wire_record()]))
    check = demo._clause3(ingested.path, ingested.cas, tmp_path / "export", 65)
    assert check.ok, _notes(check)
    assert "2 NDJSON line(s)" in check.enforced


def test_clause_three_fails_when_the_frame_does_not_hash_to_what_frames_json_declares(
    ingested: Ingested, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """03:2633's `sha256` is over the UNCOMPRESSED bytes, which is what lets a reader verify one
    member without inflating the archive. A clause that compared it to itself would pass here."""
    _exports(monkeypatch, _archive(tmp_path, lines=[_wire_record()], sha256="00" * 32))
    check = demo._clause3(ingested.path, ingested.cas, tmp_path / "export", 65)
    assert not check.ok
    assert "frames.json declares 0000000000000000 (03:2633)" in _notes(check)


def test_clause_three_fails_when_frames_json_miscounts_the_member(
    ingested: Ingested, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A frame index that disagrees with the frame is a corpus a reader cannot page through."""
    _exports(monkeypatch, _archive(tmp_path, lines=[_wire_record()], blocks=7))
    check = demo._clause3(ingested.path, ingested.cas, tmp_path / "export", 65)
    assert not check.ok
    assert "frames.json claims 7 block(s)" in _notes(check)
    assert "the member holds 1 line(s)" in _notes(check)


def test_clause_three_fails_when_the_frame_needs_a_decompressor_the_stdlib_lacks(
    ingested: Ingested, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """16-roadmap.md:439's "with no external decompressor installed", as a member-level claim.

    `ZIP_STORED` here rather than a zstd member because `zipfile` cannot write one; what the
    assertion pins is that the clause reads `compress_type` at all, which is the only thing
    standing between the roadmap sentence and an archive a reader would need zstd to open.
    """
    _exports(monkeypatch, _archive(tmp_path, lines=[_wire_record()], compress=zipfile.ZIP_STORED))
    check = demo._clause3(ingested.path, ingested.cas, tmp_path / "export", 65)
    assert not check.ok
    assert "has compress_type 0, not ZIP_DEFLATED (8)" in _notes(check)


def test_a_frame_line_that_is_not_an_object_or_that_lacks_a_wire_key_is_a_finding() -> None:
    """`| jq .` is an assertion about every line, and `REQUIRED_KEYS` is `archive/owdoc.py`'s."""
    assert demo._jq_findings("blocks/000000.ndjson", [_wire_record()]) == []
    assert demo._jq_findings("m", ["[1, 2]"]) == ["m:1 is a list, not an object"]
    short = json.dumps(dict.fromkeys(sorted(REQUIRED_KEYS - {"c"})))
    assert demo._jq_findings("m", [_wire_record(), short]) == ["m:2 is missing ['c']"]


# --- clause 4 --------------------------------------------------------------------------------


def _gate(code: int, report: str) -> SimpleNamespace:
    """A stand-in for `tools/gate_crash.py` that exits and reports what the test tells it to.

    Clause 4 delegates the whole sentence to that script, so the only thing `_clause4` itself
    owns is the delegation: the argv it builds and the verdict it takes back. A stand-in is the
    only way to see either, because the real gate converges on this tree and a clause that
    ignored its exit code would look identical to one that read it.
    """
    seen: list[list[str]] = []

    def main(argv: list[str], *, out: Any) -> int:
        seen.append(list(argv))
        out.write(report)
        return code

    return SimpleNamespace(EXIT_CLEAN=0, main=main, seen=seen)


def test_clause_four_fails_when_the_crash_gate_reports_a_divergence(tmp_path: Path) -> None:
    """16-roadmap.md:437 is `gate_crash.py`'s verdict; a clause that dropped it proves nothing."""
    gate = _gate(1, "crash FAIL  point 2/3 diverged on table block\n")
    check = demo._clause4(tmp_path / "crash", gate, points=3, in_process=True)
    assert not check.ok
    assert "tools/gate_crash.py exited 1" in _notes(check)
    assert "diverged on table block" in _notes(check)


def test_clause_four_passes_only_because_the_gate_said_so_and_quotes_it(tmp_path: Path) -> None:
    """The positive control, plus the argv: `--points` and `--in-process` are the clause's own."""
    gate = _gate(0, "crash ok  3 kill-and-verify cycle(s)\n")
    check = demo._clause4(tmp_path / "crash", gate, points=3, in_process=False)
    assert check.ok, _notes(check)
    assert "crash ok  3 kill-and-verify cycle(s)" in check.enforced
    assert "a real uncatchable signal" in check.enforced
    assert gate.seen == [["--workspace", str(tmp_path / "crash"), "--points", "3"]]

    kept = _gate(0, "crash ok\n")
    demo._clause4(tmp_path / "crash", kept, points=1, in_process=True)
    assert kept.seen == [["--workspace", str(tmp_path / "crash"), "--points", "1", "--in-process"]]


# --- clause 5 --------------------------------------------------------------------------------


def _before(path: Path, record: Any) -> dict[int, tuple[str, str, int, Any]]:
    """The gen-1 live blocks, read the way `_run`'s `clause5` thunk reads them."""
    connection = ow.connect_readonly(path)
    try:
        return demo._live_blocks(connection, record.doc_ord, record.gen)
    finally:
        connection.close()


def _reparse(store: Ingested, path: Path, cas: Path, workspace: Path, **overrides: Any) -> Any:
    """`_clause5` over a copied store, with the one argument a test wants changed."""
    arguments: dict[str, Any] = {
        "producer_id": store.producer_id,
        "stub": demo.STUB,
        "gen": demo.GEN,
        "pdf": store.pdf,
        "key": store.key,
        "before": _before(path, store.record),
        "workspace": workspace,
    }
    arguments.update(overrides)
    return demo._clause5(path, cas, **arguments)


def test_the_one_paragraph_patch_rewrites_exactly_one_run_and_not_one_byte_more(
    ingested: Ingested,
) -> None:
    """F1's CLASSIC cross-reference table is absolute byte offsets, so the patch preserves length.

    The window is asserted from both sides: inside it the bytes are the marker, outside it not
    one byte moved. A patch that wrote nothing at all -- which is how clause 5 would come to
    assert that cites carry across an edit that never happened -- fails the second assertion.
    """
    data = ingested.pdf.read_bytes()
    parsed = demo.STUB.parse_pdf(data)
    patched, replacement = demo._patch_one_paragraph(data, parsed, demo.GEN)
    body = [run for run in parsed[0].runs if run.size_pt == demo.GEN.BODY_SIZE_PT]
    target = body[int(demo.GEN.LINES_PER_PARAGRAPH)]
    low = int(target.byte_start)
    high = low + int(target.byte_len)

    assert len(patched) == len(data)
    assert patched != data
    assert replacement.startswith(demo.EDIT_MARKER)
    assert patched[low:high] == replacement.encode("ascii")
    assert patched[:low] == data[:low]
    assert patched[high:] == data[high:]


def test_clause_five_holds_when_one_paragraph_is_edited_and_re_parsed(
    ingested: Ingested, tmp_path: Path
) -> None:
    """The positive control: 03:1256-1260's rule 2 carries the cite and bumps the revision."""
    path, cas = _copy(ingested, tmp_path)
    check = _reparse(ingested, path, cas, tmp_path)
    assert check.ok, _notes(check)
    assert "revision 1" in check.enforced


def test_clause_five_fails_when_the_re_parse_did_not_publish_a_second_generation(
    ingested: Ingested, tmp_path: Path
) -> None:
    """A quarantined re-parse leaves `doc.gen` where it was (03:1298-1302) and must not read green.

    A `doc_key` that is not the gen-1 key opens a SECOND document at `gen = 1` instead, which is
    the same observable and is the outcome `SECOND_GEN` exists to name.
    """
    path, cas = _copy(ingested, tmp_path)
    check = _reparse(ingested, path, cas, tmp_path, key=b"\x5a" * 16)
    assert not check.ok
    assert "not 2: the re-parse quarantined" in _notes(check)


def test_clause_five_fails_when_a_block_history_row_appeared_after_a_text_only_edit(
    ingested: Ingested, tmp_path: Path
) -> None:
    """03:1358's worked example reports `retired = 0`, so one retirement row is the whole finding.

    16-roadmap.md:438-440 predicts exactly this row and 03 refutes it; the clause asserts 03.
    Either way it is only an assertion if a row that IS there makes the clause fail.
    """
    path, cas = _copy(ingested, tmp_path)
    before = _before(path, ingested.record)
    _damage(
        path,
        [
            (
                "INSERT INTO block_history(block_id, doc_ord, retired_gen, superseded_by, reason)"
                " VALUES ((SELECT min(block_id) FROM block), ?, 1, NULL, 'reparse_resegmented')",
                (ingested.record.doc_ord,),
            )
        ],
    )
    check = _reparse(ingested, path, cas, tmp_path, before=before)
    assert not check.ok
    assert "block_history row(s) after a text-only edit" in _notes(check)


def test_clause_five_fails_when_a_block_was_retired_by_a_text_only_edit(
    ingested: Ingested, tmp_path: Path
) -> None:
    """`state = 1` is a tombstone (0001_init.sql:267) and a paragraph edit retires nothing."""
    path, cas = _copy(ingested, tmp_path)
    before = _before(path, ingested.record)
    _damage(
        path,
        [("UPDATE block SET state = 1 WHERE block_id = (SELECT max(block_id) FROM block)", ())],
    )
    check = _reparse(ingested, path, cas, tmp_path, before=before)
    assert not check.ok
    assert "block(s) at state = 1 after a text-only edit" in _notes(check)


# --- the run, and the workspace it owns -------------------------------------------------------


def test_main_exits_one_when_a_clause_failed_and_not_only_report_does(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`_report`'s verdict has to reach the shell, and `_report`'s own test cannot show that.

    Two sites decide the exit code on a failing clause -- `_report`, and `main`'s `return` of
    what `_report` gave it -- and section 3 covers only the first. A `main` that computed the
    report and then returned `EXIT_CLEAN` would leave CI green over a table that says FAIL.
    """
    monkeypatch.setattr(demo, "_run", lambda *_: ([_check(2, ok=False)], []))
    code, report = _run(["--workspace", str(tmp_path)])
    assert code == demo.EXIT_FAIL
    assert "p2 demo FAIL  clause(s) 2 did not hold" in report


def test_main_exits_zero_when_every_clause_held(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The other half, so the test above cannot pass by making `main` always fail."""
    monkeypatch.setattr(demo, "_run", lambda *_: ([_check(1, ok=True)], []))
    code, report = _run(["--workspace", str(tmp_path)])
    assert code == demo.EXIT_CLEAN
    assert "p2 demo ok" in report


def _workspace_probe(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Record the workspace `main` made for itself, and leave a non-empty tree inside it."""
    made: list[Path] = []

    def fake_run(_args: Any, workspace: Path, _emit: Any) -> tuple[list[Any], list[int]]:
        made.append(workspace)
        (workspace / "export").mkdir(parents=True, exist_ok=True)
        (workspace / "export" / "gen.pdf").write_bytes(b"%PDF-1.7\n")
        return [_check(1, ok=True)], []

    monkeypatch.setattr(demo, "_run", fake_run)
    return made


def test_the_demo_removes_the_temporary_workspace_it_made_for_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 5,000-page run builds a store, a CAS and a `.owdoc` per invocation. They must not stay.

    The workspace is `mkdtemp`'s, so its name is new every run and no later run recreates or
    reuses it -- which is what makes its ABSENCE a fact this test can read. It is populated
    first, because removing an empty directory and removing a tree are different operations.
    """
    made = _workspace_probe(monkeypatch)
    code, _ = _run([])
    assert code == demo.EXIT_CLEAN
    assert len(made) == 1
    assert not made[0].exists(), f"{made[0]} outlived the run that owned it"


def test_keep_leaves_the_workspace_on_disk_for_the_developer_who_asked_for_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--keep` is the flag a developer reaches for to open the store the demo just built."""
    made = _workspace_probe(monkeypatch)
    code, _ = _run(["--keep"])
    assert code == demo.EXIT_CLEAN
    try:
        assert made[0].is_dir(), "--keep was passed and the workspace was removed anyway"
        assert (made[0] / "export" / "gen.pdf").is_file()
    finally:
        shutil.rmtree(made[0], ignore_errors=True)
