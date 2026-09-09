"""`owcheck`: each of its six clauses caught individually, and a clean generation passing all six.

The clause list is glossary.md:855's four -- "the parent/`ord` bijection, grid exactly-once, `rel`
referential integrity, and the verbatim-implies-retained-part rule" -- plus 03:2233's acyclicity
over `rel(continues)` and 03:1027's re-assertion of M-INV-5.

**Every clause is tested by breaking exactly one thing.** A checker that reported every generation
as broken would pass a test that only asserted failures, and one that reported every generation as
clean would pass a test that only asserted the happy path, so both directions are asserted for
each clause: `test_a_clean_generation_passes_all_six_clauses` is the other half of every test in
this file.

Specified in glossary.md:855, 03-document-model.md sections 1.1 (:69), 6.2, 10.1, 12.3 (:2233) and
12.4, 01-principles.md:327 (the verbatim clause and Q-G6) and 00-vision.md:706 (V01-5).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from omniweave_core.archive.owcheck import (
    BlockFacts,
    Clause,
    ClauseState,
    Generation,
    OwcheckReport,
    Violation,
    block_facts,
    origin_part,
    owcheck,
    owcheck_archive,
)
from omniweave_core.archive.owdoc import (
    BlockExport,
    DocHeader,
    GridRow,
    PartRow,
    export,
    open_owdoc,
)
from omniweave_core.model import (
    Addr,
    Block,
    BlockId,
    Cite,
    Kind,
    Layer,
    Method,
    OriginBytes,
    OriginNone,
    OriginPixels,
    Quad,
    Quote,
    RelKind,
    TextSpan,
    Trust,
)

_PART = "file"


def _facts(
    addr: str,
    page: int,
    ordinal: int,
    *,
    kind: Kind = Kind.PARAGRAPH,
    layer: Layer = Layer.BODY,
    quote: Quote = Quote.NORMALIZED,
    part: str | None = _PART,
) -> BlockFacts:
    return BlockFacts(
        addr=Addr(addr),
        page=page,
        ord=ordinal,
        kind=kind,
        layer=layer,
        quote=quote,
        origin_part=part,
    )


def _healthy_blocks() -> list[BlockFacts]:
    """A root, two page roots on two pages, and one child. Every clause is satisfied.

    `ord` is dense from 0 among SIBLINGS, and the siblings of a page root are every page root of
    the document (`block_sib` is `(doc_ord, gen, IFNULL(parent_id,-1), ord)`), so the two page
    roots carry 0 and 1 even though they are on different pages. 03:2188 is the sentence that
    settles it: "`addr`'s first step is a separate per-page counter (section 6.2) precisely so
    that nothing derives a name from `ord`".
    """
    return [
        _facts("doc", 0, 0, kind=Kind.DOCUMENT, quote=Quote.SYNTHETIC, part=None),
        _facts("p0/0", 0, 0),
        _facts("p0/0/0", 0, 0),
        _facts("p1/0", 1, 1),
    ]


def _healthy_grid() -> GridRow:
    """A 2x2 table whose top row is one merged cell. Every slot covered exactly once."""
    return GridRow(
        table=Addr("p0/0"),
        n_rows=2,
        n_cols=2,
        row_len=(2, 2),
        kind="data",
        cells=((0, 0, 1, 2), (1, 0, 1, 1), (1, 1, 1, 1)),
        has_merges=True,
    )


def _generation(**kw: Any) -> Generation:
    base: dict[str, Any] = {
        "blocks": _healthy_blocks(),
        "rels": (),
        "grids": (_healthy_grid(),),
        "retained_parts": frozenset({_PART}),
        "parts_known": True,
    }
    base.update(kw)
    return Generation(**base)


def _failed(report: OwcheckReport, clause: Clause) -> tuple[Violation, ...]:
    result = report.by_clause(clause)
    assert result.state is ClauseState.FAILED, f"{clause.value} did not fail: {result}"
    return result.violations


# ---------------------------------------------------------------------------
# The baseline. Without this, every failure test below is satisfied by a checker
# that fails everything.
# ---------------------------------------------------------------------------


def test_a_clean_generation_passes_all_six_clauses() -> None:
    report = owcheck(_generation())
    assert report.ok
    assert report.complete
    assert report.violations == ()
    assert [c.clause for c in report.clauses] == list(Clause)
    assert all(c.state is ClauseState.PASSED for c in report.clauses)


def test_every_clause_reports_how_many_subjects_it_looked_at() -> None:
    """A clause that passed over zero subjects and one that passed over 600,000 differ."""
    report = owcheck(_generation())
    assert report.by_clause(Clause.PARENT_ORD_BIJECTION).checked == 4
    assert report.by_clause(Clause.GRID_EXACTLY_ONCE).checked == 4
    assert report.by_clause(Clause.LAYER_INHERITED).checked == 1


# ---------------------------------------------------------------------------
# Clause 1 -- the parent / `ord` bijection.
# ---------------------------------------------------------------------------


def test_a_gap_in_a_sibling_ord_sequence_breaks_the_bijection() -> None:
    """P3: `ord` is dense from 0 AND unique among siblings. `block_sib` only gives uniqueness.

    `{0, 1, 3}` satisfies the UNIQUE index and violates the invariant, which is exactly why the
    density half has to be code.
    """
    blocks = _healthy_blocks()
    blocks[3] = _facts("p1/0", 1, 3)
    violations = _failed(owcheck(_generation(blocks=blocks)), Clause.PARENT_ORD_BIJECTION)
    assert any("not dense from 0" in v.detail for v in violations)


def test_two_siblings_sharing_an_ord_break_the_bijection() -> None:
    blocks = _healthy_blocks()
    blocks[3] = _facts("p1/0", 1, 0)
    violations = _failed(owcheck(_generation(blocks=blocks)), Clause.PARENT_ORD_BIJECTION)
    assert any("[0, 0]" in v.detail for v in violations)


def test_a_block_whose_parent_is_absent_breaks_the_bijection() -> None:
    """The referential half. `p0/9/0` names a parent `p0/9` that no block in the generation is."""
    blocks = [*_healthy_blocks(), _facts("p0/9/0", 0, 0)]
    violations = _failed(owcheck(_generation(blocks=blocks)), Clause.PARENT_ORD_BIJECTION)
    assert any("is not a block of this generation" in v.detail for v in violations)


def test_a_generation_with_two_roots_breaks_the_bijection() -> None:
    """03:1093: `doc` is the ONE block with `parent_id IS NULL`."""
    blocks = [*_healthy_blocks(), _facts("doc", 0, 1, kind=Kind.DOCUMENT, part=None)]
    violations = _failed(owcheck(_generation(blocks=blocks)), Clause.PARENT_ORD_BIJECTION)
    assert any("exactly one `document` root" in v.detail for v in violations)


def test_a_generation_with_no_root_breaks_the_bijection() -> None:
    blocks = [b for b in _healthy_blocks() if str(b.addr) != "doc"]
    violations = _failed(owcheck(_generation(blocks=blocks)), Clause.PARENT_ORD_BIJECTION)
    assert any("found 0" in v.detail for v in violations)


def test_an_unparseable_addr_is_a_violation_and_not_a_crash() -> None:
    """An archive is untrusted input. `owcheck` is the thing that says so, not the thing
    that dies of it; and the defect is reported once, by clause 1, not twice."""
    blocks = [*_healthy_blocks(), _facts("nonsense", 0, 0)]
    violations = _failed(owcheck(_generation(blocks=blocks)), Clause.PARENT_ORD_BIJECTION)
    assert any("does not parse" in v.detail for v in violations)


# ---------------------------------------------------------------------------
# Clause 2 -- grid exactly-once.
# ---------------------------------------------------------------------------


def test_a_grid_slot_claimed_twice_is_caught() -> None:
    """Two cells overlapping means `slot(r, c)` has two answers, which no consumer can resolve."""
    grid = GridRow(
        table=Addr("p0/0"),
        n_rows=2,
        n_cols=2,
        row_len=(2, 2),
        kind="data",
        cells=((0, 0, 2, 1), (1, 0, 1, 1), (0, 1, 1, 1), (1, 1, 1, 1)),
        has_merges=True,
    )
    violations = _failed(owcheck(_generation(grids=(grid,))), Clause.GRID_EXACTLY_ONCE)
    assert any("claimed 2 times" in v.detail for v in violations)
    assert any(v.addr == "p0/0/r1c0" for v in violations)


def test_a_grid_hole_is_caught() -> None:
    """ "Exactly once" is two failures, and a hole is the one a consumer reads past silently."""
    grid = GridRow(
        table=Addr("p0/0"),
        n_rows=2,
        n_cols=2,
        row_len=(2, 2),
        kind="data",
        cells=((0, 0, 1, 1), (0, 1, 1, 1), (1, 0, 1, 1)),
    )
    violations = _failed(owcheck(_generation(grids=(grid,))), Clause.GRID_EXACTLY_ONCE)
    assert any("covered by no origin cell" in v.detail for v in violations)
    assert any(v.addr == "p0/0/r1c1" for v in violations)


def test_a_cell_outside_the_declared_shape_is_caught() -> None:
    grid = GridRow(
        table=Addr("p0/0"),
        n_rows=1,
        n_cols=1,
        row_len=(1,),
        kind="data",
        cells=((0, 0, 1, 1), (5, 5, 1, 1)),
    )
    violations = _failed(owcheck(_generation(grids=(grid,))), Clause.GRID_EXACTLY_ONCE)
    assert any("outside the declared shape" in v.detail for v in violations)


def test_a_ragged_table_is_checked_against_row_len_and_not_n_cols() -> None:
    """The `table_meta` DDL: "n_cols = max(row_len); rows may be RAGGED"."""
    grid = GridRow(
        table=Addr("p0/0"),
        n_rows=2,
        n_cols=3,
        row_len=(3, 1),
        kind="data",
        cells=((0, 0, 1, 1), (0, 1, 1, 1), (0, 2, 1, 1), (1, 0, 1, 1)),
    )
    report = owcheck(_generation(grids=(grid,)))
    assert report.by_clause(Clause.GRID_EXACTLY_ONCE).state is ClauseState.PASSED


# ---------------------------------------------------------------------------
# Clause 3 -- `rel` referential integrity.
# ---------------------------------------------------------------------------


def test_a_rel_pointing_at_a_nonexistent_block_is_caught() -> None:
    """In the store this is an FK; in an archive an endpoint is an `addr`, which is never an FK
    target (INV-1, charter section 5 X40), so the check has to be code on this side."""
    rels = [(Addr("p0/0"), Addr("p9/9"), RelKind.NOTE_REF)]
    violations = _failed(owcheck(_generation(rels=rels)), Clause.REL_REFERENTIAL)
    assert any(v.addr == "p9/9" for v in violations)
    assert any("dst p9/9 is not a block" in v.detail for v in violations)


def test_a_rel_whose_source_is_missing_is_caught() -> None:
    rels = [(Addr("p9/9"), Addr("p0/0"), RelKind.CAPTION_OF)]
    violations = _failed(owcheck(_generation(rels=rels)), Clause.REL_REFERENTIAL)
    assert any("src p9/9" in v.detail for v in violations)


def test_a_self_loop_is_caught_for_every_rel_kind_and_not_only_continues() -> None:
    """The `rel` DDL calls the table "the CLOSED intra-document DAG", for all seven kinds."""
    rels = [(Addr("p0/0"), Addr("p0/0"), RelKind.HEADING_OF)]
    violations = _failed(owcheck(_generation(rels=rels)), Clause.REL_REFERENTIAL)
    assert any("self-loop" in v.detail for v in violations)


# ---------------------------------------------------------------------------
# Clause 4 -- verbatim implies a retained part. Q-G6, V01-5, INV-10.
# ---------------------------------------------------------------------------


def test_a_verbatim_block_whose_part_was_not_retained_is_caught() -> None:
    """V01-5: "zero Blocks claim `verbatim` without a non-NULL `part.store_ref`".

    The archive's spelling of `store_ref IS NULL` is a `parts[]` entry with `present: false`
    (03:2488), and the store's is the `part` DDL's "NULL => bytes were not retained".
    """
    blocks = _healthy_blocks()
    blocks[1] = _facts("p0/0", 0, 0, quote=Quote.VERBATIM)
    generation = _generation(blocks=blocks, retained_parts=frozenset())
    violations = _failed(owcheck(generation), Clause.VERBATIM_RETAINED_PART)
    assert violations[0].addr == "p0/0"
    assert violations[0].code == "OW_INTEGRITY_UNCHECKED"
    assert "not retained" in violations[0].detail


def test_a_verbatim_block_on_a_pixels_origin_is_caught() -> None:
    """The `part` DDL: "`pixels` and `none` can NEVER reach verbatim: nothing to re-read"."""
    blocks = _healthy_blocks()
    blocks[1] = _facts("p0/0", 0, 0, quote=Quote.VERBATIM, part=None)
    violations = _failed(owcheck(_generation(blocks=blocks)), Clause.VERBATIM_RETAINED_PART)
    assert "names no part" in violations[0].detail


def test_a_verbatim_block_whose_part_was_retained_passes() -> None:
    blocks = _healthy_blocks()
    blocks[1] = _facts("p0/0", 0, 0, quote=Quote.VERBATIM)
    report = owcheck(_generation(blocks=blocks))
    assert report.by_clause(Clause.VERBATIM_RETAINED_PART).state is ClauseState.PASSED
    assert report.by_clause(Clause.VERBATIM_RETAINED_PART).checked == 1


def test_a_subject_that_lists_no_parts_leaves_the_verbatim_clause_unchecked() -> None:
    """UNCHECKED is a third state and not a pass: answering "passed" would make Q-G6 a stamp."""
    blocks = _healthy_blocks()
    blocks[1] = _facts("p0/0", 0, 0, quote=Quote.VERBATIM)
    report = owcheck(_generation(blocks=blocks, parts_known=False, retained_parts=frozenset()))
    result = report.by_clause(Clause.VERBATIM_RETAINED_PART)
    assert result.state is ClauseState.UNCHECKED
    assert result.violations == ()
    assert "1 blocks claim VERBATIM" in result.reason
    assert report.ok, "an unverifiable clause does not make a generation broken"
    assert not report.complete, "and it does not make it verified either"


def test_an_unchecked_clause_emits_an_integrity_diag_row() -> None:
    """03:3222 makes it a `Diag`; 07:3193 puts it in `ABSENCE_BLOCKING_DIAGS`."""
    report = owcheck(_generation(parts_known=False))
    rows = report.diag_rows(doc_ord=4, gen=7)
    assert [r["code"] for r in rows] == ["OW_INTEGRITY_UNCHECKED"]
    assert rows[0]["doc_ord"] == 4
    assert rows[0]["gen"] == 7
    assert rows[0]["severity"] == "warning"
    assert rows[0]["fatal"] == 0
    assert rows[0]["detail"]["clause"] == "verbatim_retained_part"


def test_origin_part_is_none_for_exactly_the_two_variants_that_cannot_be_reread() -> None:
    assert origin_part(OriginBytes(part="f", start=0, length=1, codec="utf-8/strict")) == "f"
    assert origin_part(OriginPixels(page=1, quad=Quad(0, 0, 1, 0, 1, 1, 0, 1))) is None
    assert origin_part(OriginNone()) is None


# ---------------------------------------------------------------------------
# Clause 5 -- `rel(continues)` is acyclic. 03:2233.
# ---------------------------------------------------------------------------


def test_a_cycle_in_rel_continues_is_caught() -> None:
    """03:2233: "A `continues` chain is a path, never a cycle".

    A cycle does not produce a wrong reading order; it produces a serializer that does not
    terminate, because section 16.1 joins across `continues` when rendering body text.
    """
    rels = [
        (Addr("p0/0"), Addr("p1/0"), RelKind.CONTINUES),
        (Addr("p1/0"), Addr("p0/0"), RelKind.CONTINUES),
    ]
    violations = _failed(owcheck(_generation(rels=rels)), Clause.CONTINUES_ACYCLIC)
    assert "cycle" in violations[0].detail


def test_a_long_continues_chain_is_not_a_cycle() -> None:
    """A paragraph broken across many columns is a legal chain, and a long one.

    Also the reason the search is an explicit stack rather than recursion: 600 columns is legal
    and CPython's default recursion limit is 1,000.
    """
    blocks = [_facts("doc", 0, 0, kind=Kind.DOCUMENT, part=None)]
    blocks += [_facts(f"p{n}/0", n, n) for n in range(1200)]
    rels = [(Addr(f"p{n}/0"), Addr(f"p{n + 1}/0"), RelKind.CONTINUES) for n in range(1199)]
    report = owcheck(_generation(blocks=blocks, rels=rels, grids=()))
    assert report.by_clause(Clause.CONTINUES_ACYCLIC).state is ClauseState.PASSED
    assert report.by_clause(Clause.CONTINUES_ACYCLIC).checked == 1199


def test_a_cycle_reached_through_a_shared_tail_is_still_caught() -> None:
    """A diamond into a cycle: the colouring must not mark the cycle black on the first descent."""
    rels = [
        (Addr("p0/0"), Addr("p1/0"), RelKind.CONTINUES),
        (Addr("p0/0/0"), Addr("p1/0"), RelKind.CONTINUES),
        (Addr("p1/0"), Addr("p0/0"), RelKind.CONTINUES),
    ]
    violations = _failed(owcheck(_generation(rels=rels)), Clause.CONTINUES_ACYCLIC)
    assert violations


def test_a_cycle_in_another_rel_kind_is_not_this_clauses_business() -> None:
    """Only `continues` is asserted acyclic here (03:2233); the rest is `rel_referential`'s."""
    rels = [
        (Addr("p0/0"), Addr("p1/0"), RelKind.NOTE_REF),
        (Addr("p1/0"), Addr("p0/0"), RelKind.NOTE_REF),
    ]
    report = owcheck(_generation(rels=rels))
    assert report.by_clause(Clause.CONTINUES_ACYCLIC).state is ClauseState.PASSED


# ---------------------------------------------------------------------------
# Clause 6 -- M-INV-5, layer inheritance. 03:1021-1027.
# ---------------------------------------------------------------------------


def test_a_child_naming_a_layer_different_from_its_parents_is_caught() -> None:
    """M-INV-5, re-asserted over the whole generation (03:1027).

    The failure it prevents: `serialize(layers={BODY})` reaching a `body` paragraph inside an
    `annotation` comment, and having to choose between leaking a review comment into body text
    and making the layer filter a subtree walk.
    """
    blocks = _healthy_blocks()
    blocks[2] = _facts("p0/0/0", 0, 0, layer=Layer.ANNOTATION)
    violations = _failed(owcheck(_generation(blocks=blocks)), Clause.LAYER_INHERITED)
    assert violations[0].addr == "p0/0/0"
    assert violations[0].code == "OW_LAYER_NOT_INHERITED"


def test_a_page_root_may_name_its_own_layer() -> None:
    """The invariant's own carve-out: a page root's parent is the `document` root."""
    blocks = _healthy_blocks()
    blocks[1] = _facts("p0/0", 0, 0, kind=Kind.PAGE_HEADER, layer=Layer.FURNITURE)
    blocks[2] = _facts("p0/0/0", 0, 0, layer=Layer.FURNITURE)
    report = owcheck(_generation(blocks=blocks))
    assert report.by_clause(Clause.LAYER_INHERITED).state is ClauseState.PASSED


# ---------------------------------------------------------------------------
# The report as a whole.
# ---------------------------------------------------------------------------


def test_a_report_collects_every_violation_rather_than_raising_at_the_first() -> None:
    """03:69 makes `owcheck` a step of `end_doc()`, and 03:3222 makes its finding a `Diag`.

    A validator that raised would report one problem out of many and would make a quarantined
    generation uninspectable, which is the opposite of what `ow doc diff` needs (03:2694).
    """
    blocks = _healthy_blocks()
    blocks[3] = _facts("p1/0", 1, 5, layer=Layer.HIDDEN)
    generation = _generation(
        blocks=blocks,
        rels=[(Addr("p0/0"), Addr("gone"), RelKind.NOTE_REF)],
        grids=(
            GridRow(
                table=Addr("p0/0"),
                n_rows=1,
                n_cols=2,
                row_len=(2,),
                kind="data",
                cells=((0, 0, 1, 1),),
            ),
        ),
    )
    report = owcheck(generation)
    assert not report.ok
    failed = {c.clause for c in report.clauses if c.state is ClauseState.FAILED}
    assert failed == {
        Clause.PARENT_ORD_BIJECTION,
        Clause.REL_REFERENTIAL,
        Clause.GRID_EXACTLY_ONCE,
    }
    assert len(report.violations) >= 3


def test_a_violation_row_carries_an_addr_and_never_a_block_id() -> None:
    """INV-8. A `diag` row's `block_id` column is deliberately not an FK and is not set here."""
    blocks = _healthy_blocks()
    blocks[2] = _facts("p0/0/0", 0, 0, layer=Layer.ANNOTATION)
    rows = owcheck(_generation(blocks=blocks)).diag_rows(doc_ord=1, gen=2)
    assert rows
    for row in rows:
        assert "block_id" not in row
        assert row["component"] == "omniweave_core.archive.owcheck"
        assert set(row) == {
            "doc_ord",
            "gen",
            "page",
            "part",
            "code",
            "severity",
            "component",
            "message",
            "detail",
            "fatal",
        }


def test_asking_for_a_clause_that_is_not_in_the_report_raises() -> None:
    report = OwcheckReport(clauses=())
    with pytest.raises(KeyError):
        report.by_clause(Clause.REL_REFERENTIAL)


# ---------------------------------------------------------------------------
# `owcheck` over an archive, which is the same block stream `import_` reads.
# ---------------------------------------------------------------------------


def _block(
    addr: str,
    page: int,
    ordinal: int,
    *,
    bid: int,
    kind: Kind = Kind.PARAGRAPH,
    quote: Quote = Quote.NORMALIZED,
    origin: Any = None,
) -> Block:
    return Block(
        id=BlockId(bid),
        addr=Addr(addr),
        cite=Cite(f"d1#{bid}"),
        doc_ord=1,
        gen=2,
        page=page,
        parent=None,
        ord=ordinal,
        kind=kind,
        raw_kind=None,
        layer=Layer.BODY,
        label=None,
        text="hi" if kind is not Kind.DOCUMENT else None,
        content_digest=bytes(16),
        layout_digest=None,
        revision=0,
        quad=None,
        origin=origin
        if origin is not None
        else OriginBytes(part=_PART, start=0, length=2, codec="utf-8/strict"),
        span=TextSpan(0, 2) if kind is not Kind.DOCUMENT else None,
        producer_id=1,
        method=Method.NATIVE,
        trust=Trust.EXTRACTED,
        quote=quote,
        origin_operator="parse.text",
        origin_driver="omniweave.parse.text",
        driver_schema_v=1,
    )


class _Source:
    def __init__(self, rows: Sequence[BlockExport], parts: Sequence[Any]) -> None:
        self._rows = tuple(rows)
        self._parts = tuple(parts)

    def header(self) -> DocHeader:
        return DocHeader(
            doc_key="cd" * 16,
            gen=2,
            status="ok",
            source={},
            declared={},
            achieved={},
        )

    def blocks(self) -> Sequence[BlockExport]:
        return self._rows

    def rels(self) -> Sequence[Any]:
        return ()

    def grids(self) -> Sequence[Any]:
        return ()

    def parts(self) -> Sequence[Any]:
        return self._parts

    def assets(self) -> Sequence[Any]:
        return ()

    def views(self) -> Sequence[Any]:
        return ()

    def diags(self) -> Sequence[Any]:
        return ()

    def toc(self) -> Sequence[Any]:
        return ()


def _write(tmp_path: Path, *, verbatim: bool, retained: bool) -> Path:
    rows = [
        BlockExport(
            block=_block("doc", 0, 0, bid=1, kind=Kind.DOCUMENT, origin=OriginNone()), producer=0
        ),
        BlockExport(
            block=_block(
                "p0/0", 0, 0, bid=2, quote=Quote.VERBATIM if verbatim else Quote.NORMALIZED
            ),
            producer=0,
        ),
    ]
    parts = [(PartRow(path=_PART, sha256="ab" * 32, byte_len=2, present=retained), b"hi")]
    target = tmp_path / f"{verbatim}-{retained}.owdoc"
    export(_Source(rows, parts), target)
    return target


def test_owcheck_runs_over_an_archive_and_passes_a_clean_one(tmp_path: Path) -> None:
    with open_owdoc(_write(tmp_path, verbatim=True, retained=True)) as reader:
        report = owcheck_archive(reader)
    assert report.ok
    assert report.complete
    assert report.by_clause(Clause.VERBATIM_RETAINED_PART).checked == 1


def test_owcheck_over_an_archive_catches_an_unretained_verbatim_claim(tmp_path: Path) -> None:
    """The whole clause, end to end: a real archive whose `parts[]` says `present: false`."""
    with open_owdoc(_write(tmp_path, verbatim=True, retained=False)) as reader:
        report = owcheck_archive(reader)
    assert not report.ok
    violations = _failed(report, Clause.VERBATIM_RETAINED_PART)
    assert violations[0].addr == "p0/0"


def test_block_facts_reads_the_seven_facts_off_a_decoded_wire_record(tmp_path: Path) -> None:
    """One adapter, so a store cursor and an archive frame reach the same six clauses."""
    with open_owdoc(_write(tmp_path, verbatim=True, retained=True)) as reader:
        rows = [block_facts(row) for row in reader.blocks()]
    assert [str(f.addr) for f in rows] == ["doc", "p0/0"]
    assert rows[1].kind is Kind.PARAGRAPH
    assert rows[1].layer is Layer.BODY
    assert rows[1].quote is Quote.VERBATIM
    assert rows[1].origin_part == _PART
    assert rows[0].origin_part is None
