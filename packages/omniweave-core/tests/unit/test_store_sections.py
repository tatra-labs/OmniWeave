"""`store/sections.py`: the `sec_path` codec, the derivation, the fanout limit, the range scan.

Four of these tests exist because they can fail, and each one is a specific way the shipped table
goes silently wrong rather than loudly wrong.

**The padding test asserts the negative half too.** 07-store-and-retrieval.md:571-573 is the whole
reason `block_sec` is not a plain integer path: *"a plain integer path makes `'/1/10' < '/1/2'`
lexicographically and the range scan silently returns the wrong set."* A test that only sorts the
padded output and finds it in numeric order passes just as well against a store with three
siblings, where padding and luck are indistinguishable. So every padding test here also sorts the
UNPADDED spelling of the same tree and asserts that it comes out wrong.

**The range-scan test runs the SQL, against a migrated store, over rows the derivation wrote.**
Asserting that `sec_path_range` returns a pair of strings tests the function; asserting that
`sec_path >= lo AND sec_path < hi` over `block_sec_path` returns exactly the subtree tests the
index. Only the second one can catch a bound that is off by one component.

**The idempotence test compares the SECOND derivation against the FIRST's stored rows.** That is
the property `ow store rebuild <object>` depends on (03-document-model.md:2477): a `[DER]` object
has to be rebuildable from scratch at any time, and "rebuildable" means the rebuild agrees with
what is there. The comparison is against rows read out of the database before the second run, held
in Python, so a mutation that changed both runs identically still fails the third assertion --
which pins the paths against literals written down here.

**The fanout test asserts the accepted case as well as the refused one.** 9,999 siblings is a
document; 10,000 is a disclosed truncation (07:573-575). A test that only checked the breach would
pass against an implementation that truncated at 3.

Specified in 07-store-and-retrieval.md section 3.6 (:556-578) and 03-document-model.md sections
12.4 (:2243-2262) and 13.1 (:2470-2478).
"""

from __future__ import annotations

import sqlite3  # noqa: TID251 -- the range scan is only real against a migrated store's index.
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

import pytest
from omniweave_core.errors import ResourceLimit, StoreError
from omniweave_core.model.records import Diag
from omniweave_core.store import migrate
from omniweave_core.store import reader as rd
from omniweave_core.store import sections as sec
from omniweave_core.store import sqlite as ow
from omniweave_core.store.types import Filters

NOW_NS = 1_757_400_000_000_000_000
"""A fixed clock.

`time.time()` is banned in library code, so a test may not read the ambient one."""

DIGEST = b"\x11" * 16


# ---------------------------------------------------------------------------------------------
# A real store, and the smallest seeding helpers that can hold a tree
# ---------------------------------------------------------------------------------------------


class Built(NamedTuple):
    path: Path
    writer: sqlite3.Connection


@pytest.fixture
def built(tmp_path: Path) -> Iterator[Built]:
    """A migrated `.owstore` with its writer held open, so `block_sec` and its index exist."""
    path = tmp_path / "index.owstore"
    writer = ow.connect(path)
    applied = migrate.apply_pending(writer, now_ns=NOW_NS)
    assert len(applied) == 4, f"expected four migrations, applied {len(applied)}"
    try:
        yield Built(path=path, writer=writer)
    finally:
        writer.close()


def _code(conn: sqlite3.Connection, domain: str, name: str) -> int:
    row = conn.execute(
        "SELECT ord FROM enum_val WHERE domain = ? AND name = ?", (domain, name)
    ).fetchone()
    assert row is not None, f"enum_val has no {domain}.{name}"
    return int(row[0])


def _scaffold(conn: sqlite3.Connection, *, doc_ord: int = 1, gen: int = 1) -> int:
    """One `producer`, one `doc` at `gen`, one `page`. Returns the `producer_id`."""
    conn.execute(
        "INSERT OR IGNORE INTO producer(operator, op_version, code_fingerprint, options_digest) "
        "VALUES('op.parse', 1, 'fp', X'00')"
    )
    producer_id = int(conn.execute("SELECT min(producer_id) FROM producer").fetchone()[0])
    conn.execute(
        "INSERT INTO doc(doc_ord, doc_key, source_sha256, uri, media_type, format, "
        "                format_evidence, source_bytes, gen, status, model_version, "
        "                declared, achieved) "
        "VALUES(?, ?, ?, ?, 'application/pdf', 'pdf', '{}', 1, ?, 'ok', '1.1', '{}', '{}')",
        (doc_ord, bytes([doc_ord]) * 16, DIGEST, f"file:///corpus/{doc_ord}.pdf", gen),
    )
    conn.execute(
        "INSERT OR IGNORE INTO page(doc_ord, gen, page, page_kind, method, producer_id) "
        "VALUES(?, ?, 0, ?, ?, ?)",
        (
            doc_ord,
            gen,
            _code(conn, "page_kind", "page"),
            _code(conn, "method", "native"),
            producer_id,
        ),
    )
    return producer_id


def _block(
    conn: sqlite3.Connection,
    producer_id: int,
    *,
    block_id: int,
    parent_id: int | None = None,
    ord_: int = 0,
    kind: str = "paragraph",
    level: int | None = None,
    doc_ord: int = 1,
    gen: int = 1,
    state: int = 0,
) -> None:
    """One `block` row with a real `parent_id`. `os_kind = none`, so neither os CHECK applies."""
    payload = None if level is None else f'{{"level":{level}}}'
    conn.execute(
        "INSERT INTO block(block_id, doc_ord, gen, page, addr, cite, parent_id, ord, kind, "
        "                  layer, text, content_digest, os_kind, producer_id, method, trust, "
        "                  quote, origin_operator, origin_driver, driver_schema_v, payload, "
        "                  state) "
        "VALUES(?, ?, ?, 0, ?, ?, ?, ?, ?, ?, 'hello', ?, ?, ?, ?, 2, 4, 'op.parse', 'drv', 1, "
        "       ?, ?)",
        (
            block_id,
            doc_ord,
            gen,
            f"p0/{block_id}",
            f"d{doc_ord}#{block_id}",
            parent_id,
            ord_,
            _code(conn, "kind", kind),
            _code(conn, "layer", "body"),
            DIGEST,
            _code(conn, "origin_span_kind", "none"),
            producer_id,
            _code(conn, "method", "native"),
            payload,
            state,
        ),
    )


def _twelve_sibling_tree(conn: sqlite3.Connection, producer_id: int) -> None:
    """`document` -> one `H1` -> twelve `H2`s, each followed in reading order by one paragraph.

    Twelve is the smallest count that makes the trap visible: with nine or fewer siblings the
    unpadded and the padded orders agree, and the test would pass on a broken implementation.

    Every block is a CHILD of the document and the sections come from `ord` alone -- heading
    `100 + n` at `ord = 2n - 1`, its paragraph `200 + n` at `ord = 2n` -- because that is the
    shape a markdown or a PDF driver emits: `#` levels carry the hierarchy and containment does
    not (03:817, and `_enter`'s ruling on what bounds a heading).
    """
    _block(conn, producer_id, block_id=1, kind="document")
    _block(conn, producer_id, block_id=2, parent_id=1, ord_=0, kind="heading", level=1)
    for n in range(1, 13):
        _block(
            conn,
            producer_id,
            block_id=100 + n,
            parent_id=1,
            ord_=2 * n - 1,
            kind="heading",
            level=2,
        )
        _block(conn, producer_id, block_id=200 + n, parent_id=1, ord_=2 * n)


def _paths(conn: sqlite3.Connection) -> dict[int, str]:
    return {int(b): str(p) for b, p in conn.execute("SELECT block_id, sec_path FROM block_sec")}


def _rows(conn: sqlite3.Connection) -> list[tuple[int, int, int, str]]:
    return [
        (int(a), int(b), int(c), str(d))
        for a, b, c, d in conn.execute(
            "SELECT block_id, sec_id, sec_depth, sec_path FROM block_sec ORDER BY block_id"
        )
    ]


B = sec.SecBlock


# ---------------------------------------------------------------------------------------------
# The codec, and the lexicographic trap it exists to close
# ---------------------------------------------------------------------------------------------


def test_format_sec_path_zero_pads_to_four_digits_and_the_root_is_a_bare_slash() -> None:
    """07:571 prints `/0001/0004/0002` and 07:3173 makes `'/'` the whole-corpus prefix."""
    assert sec.format_sec_path(()) == "/"
    assert sec.format_sec_path((1,)) == "/0001"
    assert sec.format_sec_path((1, 4, 2)) == "/0001/0004/0002"
    assert sec.format_sec_path((9999,)) == "/9999"
    assert sec.sec_path_components("/0001/0004/0002") == (1, 4, 2)
    assert sec.sec_path_components("/") == ()


def test_twelve_siblings_sort_numerically_when_padded_and_wrongly_when_they_are_not() -> None:
    """The trap 07:571-573 names, both halves. The second half is what makes the first mean it.

    *"a plain integer path makes `'/1/10' < '/1/2'` lexicographically and the range scan silently
    returns the wrong set."* Sorting twelve padded paths and finding numeric order proves nothing
    on its own -- a broken implementation that emitted one-digit components would agree with it up
    to nine. So the same twelve components are also spelled the unpadded way, and that sort is
    asserted to be WRONG, with the exact inversion the plan prints called out by name.
    """
    padded = [sec.format_sec_path((1, n)) for n in range(1, 13)]
    assert sorted(padded) == padded, "the padded form must sort in numeric order"
    assert padded.index("/0001/0002") < padded.index("/0001/0010")
    assert sorted(padded)[-1] == "/0001/0012"

    unpadded = [f"/1/{n}" for n in range(1, 13)]
    assert sorted(unpadded) != unpadded, "if this ever passes, the trap is not being tested"
    assert sorted(["/1/10", "/1/2"]) == ["/1/10", "/1/2"], "07:571's exact inversion"
    assert sorted(unpadded)[-1] == "/1/9", "numeric order would end at 12, lexical ends at 9"


def test_a_component_too_wide_to_sort_is_refused_rather_than_widened() -> None:
    """`format_sec_path` cannot truncate -- the parent is not in view -- so it refuses.

    A five-digit component sorts below every four-digit sibling, which is the exact failure the
    padding exists to prevent, so emitting one would be worse than raising. `ResourceLimit` names
    the knob (`errors.py:203-206`), which is what 07:574 spells `SEC_PATH_FANOUT`.
    """
    with pytest.raises(ResourceLimit) as caught:
        sec.format_sec_path((1, 10_000))
    assert caught.value.limit == "SEC_PATH_FANOUT"
    with pytest.raises(ResourceLimit):
        sec.format_sec_path((0,))


def test_a_malformed_sec_path_is_refused_by_the_decoder_in_both_directions() -> None:
    """The codec is a bijection over well-formed paths, so a mis-shaped string is an error."""
    for bad in ("0001", "/1/2", "/0001/", "/0001/000a", ""):
        with pytest.raises(StoreError):
            sec.sec_path_components(bad)
    with pytest.raises(StoreError):
        sec.sec_path_range("0001")


def test_the_range_bound_is_the_sentinel_and_it_survives_the_carry_the_increment_form_loses() -> (
    None
):
    """07:573 prints "increment the last component"; that form loses the 9,999th subtree.

    Incrementing `/0001/9999` gives `/0001/10000`, and `'1' < '9'` at the seventh character puts
    it BELOW `/0001/9999/0001` -- so the widened range excludes everything it was widened for.
    Both bounds are computed here and compared against the same descendant, so the test says which
    one is right rather than merely asserting the shipped one.
    """
    lo, hi = sec.sec_path_range("/0001/9999")
    descendant = "/0001/9999/0001"
    assert lo <= descendant < hi

    increment_form = "/0001/10000"
    assert not (lo <= descendant < increment_form), "the DDL's printed bound loses the subtree"


def test_the_reader_and_the_writer_agree_on_the_bound_because_a_disagreement_is_a_wrong_set() -> (
    None
):
    """`reader._prefix_bounds` scans what this module writes, so the two bounds must be one bound.

    `SqliteReader._filters` (reader.py:881-884) builds `Filters.sec_path_prefix`'s range with
    `_PREFIX_SENTINEL`. If this module ever adopted the DDL's increment form the filter would
    quietly return a different set than the writer's own notion of a subtree, and nothing else in
    the suite would notice.
    """
    for prefix in ("/", "/0001", "/0001/9999", "/0003/0007/0001"):
        assert sec.sec_path_range(prefix) == rd._prefix_bounds(prefix)


def test_a_heading_is_its_own_depth_zero_ancestor_in_the_ancestor_chain__07_1302() -> None:
    """07:1302: *"`spine(b)` comes from `block_sec`; `b` is its own depth-0 ancestor."*"""
    assert sec.sec_path_ancestors("/0001/0004") == ("/", "/0001", "/0001/0004")
    assert sec.sec_path_ancestors("/") == ("/",)
    assert sec.sec_path_ancestors("/0001/0004")[-1] == "/0001/0004"


# ---------------------------------------------------------------------------------------------
# The derivation, in memory
# ---------------------------------------------------------------------------------------------


def test_a_heading_carries_its_own_section_and_not_its_parents__07_1302() -> None:
    """The row for a heading has `block_id == sec_id`, and that is what the read side needs.

    Filed under its parent's path instead, the heading of section 4.2 would fall outside the range
    scan for section 4.2 -- "everything under 4.2" would return the section without its title --
    and `block_id == sec_id` is the only thing in the table that tells a section's defining block
    from its contents, so the segmenter could not rebuild `heading_path` at all.
    """
    report = sec.plan_sections(
        [
            B(1, None, 0, "document"),
            B(2, 1, 0, "heading", 1),
            B(3, 1, 1, "paragraph"),
        ],
        doc_ord=1,
        gen=1,
    )
    heading = next(r for r in report.rows if r.block_id == 2)
    assert (heading.sec_id, heading.sec_depth, heading.sec_path) == (2, 1, "/0001")
    body = next(r for r in report.rows if r.block_id == 3)
    assert (body.sec_id, body.sec_path) == (2, "/0001")
    assert sec.sec_path_ancestors(heading.sec_path)[0] == sec.SEC_PATH_ROOT


def test_a_document_with_no_headings_at_all_gets_one_well_formed_row_per_block() -> None:
    """03:2261-2262: *"a `none` driver produces a document with one implicit section."*

    Not zero rows and not a crash. The implicit section is the `document` block itself, at depth 0
    on path `/`, which is also 07:3173's whole-corpus prefix.
    """
    report = sec.plan_sections(
        [B(1, None, 0, "document"), B(2, 1, 0, "paragraph"), B(3, 1, 1, "paragraph")],
        doc_ord=7,
        gen=3,
    )
    assert [r.block_id for r in report.rows] == [1, 2, 3]
    assert {(r.sec_id, r.sec_depth, r.sec_path) for r in report.rows} == {(1, 0, "/")}
    assert (report.sections, report.folded, report.diags) == (0, 0, ())
    assert (report.doc_ord, report.gen) == (7, 3)


def test_a_skipped_heading_level_nests_one_deeper_and_never_invents_a_component() -> None:
    """The skipped-level ruling: depth comes from the stack, never from the level number.

    03:2255 defers the policy to 06-structure-extraction.md, which does not make the call. `H1`
    then `H3` gives depth 2, so every component of every `sec_path` is a section some block
    defines -- a phantom component would be a path with no row where `block_id == sec_id`, and
    `segment.heading_path` would have a hole where the segmenter looked for a title.
    """
    report = sec.plan_sections(
        [B(1, None, 0, "document"), B(2, 1, 0, "heading", 1), B(3, 1, 1, "heading", 3)],
        doc_ord=1,
        gen=1,
    )
    deep = next(r for r in report.rows if r.block_id == 3)
    assert (deep.sec_depth, deep.sec_path) == (2, "/0001/0001")
    defined = {r.sec_path for r in report.rows if r.block_id == r.sec_id}
    for row in report.rows:
        assert set(sec.sec_path_ancestors(row.sec_path)) <= defined | {sec.SEC_PATH_ROOT}


def test_a_heading_section_is_not_closed_by_the_page_root_it_happens_to_sit_in() -> None:
    """03:814 makes the `document`'s children page roots, so containment cannot bound a heading.

    Ending a heading's section at its container's last child would close every section at every
    page boundary, and "everything under section 4.2" would mean "everything under section 4.2 on
    page 12". The block on the second page root must still be in the first page's section.
    """
    report = sec.plan_sections(
        [
            B(1, None, 0, "document"),
            B(10, 1, 0, "container"),
            B(11, 10, 0, "heading", 1),
            B(20, 1, 1, "container"),
            B(21, 20, 0, "paragraph"),
        ],
        doc_ord=1,
        gen=1,
    )
    carried = next(r for r in report.rows if r.block_id == 21)
    assert (carried.sec_id, carried.sec_path) == (11, "/0001")


def test_an_explicit_section_wins_over_a_derived_one_and_the_two_nest_consistently() -> None:
    """03:817: an explicit `section` is authoritative; a heading is the fallback *"where absent"*.

    So a `heading` inside a typed `section` nests UNDER it rather than replacing it. The other
    reading -- a level-1 heading pops the typed section -- would let a `##` in the source outrank a
    structural level the source actually declared. The explicit section's extent is its own
    subtree, which is why the trailing paragraph is back at the root.
    """
    report = sec.plan_sections(
        [
            B(1, None, 0, "document"),
            B(2, 1, 0, "section"),
            B(3, 2, 0, "heading", 1),
            B(4, 2, 1, "paragraph"),
            B(5, 1, 1, "section"),
            B(6, 5, 0, "paragraph"),
            B(7, 1, 2, "paragraph"),
        ],
        doc_ord=1,
        gen=1,
    )
    by_id = {r.block_id: r for r in report.rows}
    assert (by_id[2].sec_id, by_id[2].sec_path) == (2, "/0001")
    assert (by_id[3].sec_id, by_id[3].sec_path) == (3, "/0001/0001"), "the heading nests under it"
    assert by_id[4].sec_path == "/0001/0001"
    assert (by_id[5].sec_id, by_id[5].sec_path) == (5, "/0002"), "the next typed section"
    assert by_id[7].sec_path == "/", "an explicit section's extent is its own subtree"
    assert report.sections == 3


def test_nine_thousand_nine_hundred_and_ninety_nine_siblings_are_accepted() -> None:
    """The accepted half of 07:573-575. Without it a truncation at 3 would pass the breach test."""
    blocks = [B(1, None, 0, "document")]
    blocks += [B(i + 2, 1, i, "heading", 1) for i in range(sec.SEC_PATH_FANOUT)]
    report = sec.plan_sections(blocks, doc_ord=1, gen=1)
    assert report.sections == 9_999
    assert (report.folded, report.diags) == (0, ())
    assert report.rows[-1].sec_path == "/9999"
    paths = [r.sec_path for r in report.rows if r.sec_depth == 1]
    assert sorted(paths) == paths, "9,999 padded siblings still sort in numeric order"


def test_the_ten_thousandth_sibling_emits_the_diag_and_truncates_rather_than_raising() -> None:
    """07:573-575, verbatim: `Diag(OW_RESOURCE_LIMIT, {limit: "SEC_PATH_FANOUT"})` and truncate.

    The overflowing section keeps the PARENT's `sec_id`, depth and path -- that is what "truncates
    the path at that depth" means -- and one diagnostic is filed per overflowing parent, not one
    per excess sibling: `CREATE INDEX diag_code` is what the absence contract reads
    (0001_init.sql:469) and 90,000 rows saying one thing would drown it.
    """
    blocks = [B(1, None, 0, "document")]
    blocks += [B(i + 2, 1, i, "heading", 1) for i in range(sec.SEC_PATH_FANOUT + 1)]
    report = sec.plan_sections(blocks, doc_ord=4, gen=2)

    assert report.sections == 9_999
    assert report.folded == 1
    overflowed = next(r for r in report.rows if r.block_id == 10_001)
    assert (overflowed.sec_id, overflowed.sec_depth, overflowed.sec_path) == (1, 0, "/")

    assert len(report.diags) == 1
    diag = report.diags[0]
    assert isinstance(diag, Diag)
    assert diag.code == "OW_RESOURCE_LIMIT"
    assert diag.detail["limit"] == "SEC_PATH_FANOUT"
    assert diag.fatal is True, "03:1824 -- a limit breach is never swallowed"
    assert int(diag.block or 0) == 10_001

    row = report.diag_rows()[0]
    assert (row["doc_ord"], row["gen"], row["block_id"]) == (4, 2, 10_001)
    assert row["fatal"] == 1
    assert '"limit":"SEC_PATH_FANOUT"' in row["detail"].replace(" ", "")


def test_a_second_overflowing_sibling_does_not_file_a_second_diagnostic() -> None:
    """One row per overflowing parent. Asserted separately, because the latch is a live branch."""
    blocks = [B(1, None, 0, "document")]
    blocks += [B(i + 2, 1, i, "heading", 1) for i in range(sec.SEC_PATH_FANOUT + 5)]
    report = sec.plan_sections(blocks, doc_ord=1, gen=1)
    assert (report.folded, len(report.diags)) == (5, 1)


def test_a_parent_cycle_is_walked_once_instead_of_forever() -> None:
    """`owcheck` quarantines a broken parent bijection; the derivation must not hang before it.

    A `[DER]` rebuild runs against whatever is on disk (03:2477), including a generation whose
    tree is damaged, so the walk carries a visited set rather than trusting the DDL's one CHECK
    (`parent_id <> block_id`, 0001_init.sql:269), which forbids only the length-1 cycle.
    """
    report = sec.plan_sections(
        [B(1, None, 0, "document"), B(2, 3, 0, "paragraph"), B(3, 2, 0, "paragraph")],
        doc_ord=1,
        gen=1,
    )
    assert [r.block_id for r in report.rows] == [1], "the cycle is unreachable, not looped over"


def test_a_block_whose_parent_is_out_of_scope_still_gets_a_row() -> None:
    """Dropping it would leave a live block with no `block_sec` row, which reads as an absence."""
    report = sec.plan_sections(
        [B(1, None, 0, "document"), B(9, 77, 0, "paragraph")], doc_ord=1, gen=1
    )
    assert {r.block_id for r in report.rows} == {1, 9}


# ---------------------------------------------------------------------------------------------
# The derivation, against a migrated store
# ---------------------------------------------------------------------------------------------


def test_derive_block_sec_writes_one_row_per_live_block_of_the_generation(built: Built) -> None:
    """One row per live block (07:559-563), read off `block` and not off `ow_block_head`.

    The derivation runs inside `end_doc`, where the staged generation is `doc.gen + 1` and
    invisible through the view (0001_init.sql:328-330, 03:75-80). This store's `doc.gen` is 1 and
    the blocks are written at gen 2, so a derivation that read the view would write nothing.
    """
    conn = built.writer
    conn.execute("BEGIN IMMEDIATE")
    producer_id = _scaffold(conn, gen=1)
    conn.execute(
        "INSERT OR IGNORE INTO page(doc_ord, gen, page, page_kind, method, producer_id) "
        "VALUES(1, 2, 0, ?, ?, ?)",
        (_code(conn, "page_kind", "page"), _code(conn, "method", "native"), producer_id),
    )
    _block(conn, producer_id, block_id=1, kind="document", gen=2)
    _block(conn, producer_id, block_id=2, parent_id=1, ord_=0, kind="heading", level=1, gen=2)
    _block(conn, producer_id, block_id=3, parent_id=1, ord_=1, gen=2)
    _block(conn, producer_id, block_id=4, parent_id=1, ord_=2, gen=2, state=1)
    conn.execute("COMMIT")

    conn.execute("BEGIN IMMEDIATE")
    report = sec.derive_block_sec(conn, 1, 2)
    conn.execute("COMMIT")

    assert len(report.rows) == 3
    assert _rows(conn) == [(1, 1, 0, "/"), (2, 2, 1, "/0001"), (3, 2, 1, "/0001")]
    assert 4 not in _paths(conn), "a tombstoned block is not a live block"


def test_the_range_scan_returns_exactly_the_subtree_and_excludes_the_prefix_sibling(
    built: Built,
) -> None:
    """The index, not the function: `sec_path >= ? AND sec_path < ?` over `block_sec_path`.

    The tree is one `H1` with twelve `H2` children, which is the smallest shape where the trap
    bites. Scanning section 1's FIRST child must return that child and its paragraph and nothing
    else -- in particular not the TENTH child, whose unpadded path `/1/10` has `/1/1` as a string
    prefix. The second half of the test runs the same bound against the unpadded spelling and
    asserts it returns the wrong set, so the first half is padding and not luck.
    """
    conn = built.writer
    conn.execute("BEGIN IMMEDIATE")
    producer_id = _scaffold(conn)
    _twelve_sibling_tree(conn, producer_id)
    sec.derive_block_sec(conn, 1, 1)
    conn.execute("COMMIT")

    paths = _paths(conn)
    assert paths[101] == "/0001/0001" and paths[110] == "/0001/0010"

    lo, hi = sec.sec_path_range("/0001/0001")
    found = {
        int(row[0])
        for row in conn.execute(
            "SELECT block_id FROM block_sec WHERE sec_path >= ? AND sec_path < ?", (lo, hi)
        )
    }
    assert found == {101, 201}, "the first H2 and its paragraph, and nothing else"
    assert 110 not in found and 210 not in found, "the tenth sibling is not in the first's subtree"

    whole = {
        int(row[0])
        for row in conn.execute(
            "SELECT block_id FROM block_sec WHERE sec_path >= ? AND sec_path < ?",
            sec.sec_path_range("/0001"),
        )
    }
    assert whole == {2} | {100 + n for n in range(1, 13)} | {200 + n for n in range(1, 13)}
    assert 1 not in whole, "the document root sits at '/' and is above section 1"

    unpadded = sorted(f"/1/{n}" for n in range(1, 13))
    u_lo, u_hi = sec.sec_path_range("/1/1")
    caught = [p for p in unpadded if u_lo <= p < u_hi]
    assert caught == ["/1/1", "/1/10", "/1/11", "/1/12"], "unpadded, the bound is simply wrong"


def test_the_root_prefix_degenerates_to_the_whole_corpus__07_3173(built: Built) -> None:
    """07:3173: *"the range scan degenerates to the whole corpus ... a legal plan, not an
    error."*
    """
    conn = built.writer
    conn.execute("BEGIN IMMEDIATE")
    producer_id = _scaffold(conn)
    _twelve_sibling_tree(conn, producer_id)
    sec.derive_block_sec(conn, 1, 1)
    conn.execute("COMMIT")

    everything = int(
        conn.execute(
            "SELECT count(*) FROM block_sec WHERE sec_path >= ? AND sec_path < ?",
            sec.sec_path_range(sec.SEC_PATH_ROOT),
        ).fetchone()[0]
    )
    assert everything == int(conn.execute("SELECT count(*) FROM block_sec").fetchone()[0]) == 26


def test_the_shipped_reader_narrows_on_the_rows_the_derivation_wrote(built: Built) -> None:
    """The P2 -> P6 edge, end to end: `Filters.sec_path_prefix` over a derived index.

    16-roadmap.md:1034 bounds retrieval to *"`Reader`, `block_fts` and `block_sec`, and nothing
    else"*. `block_fts` ships with its triggers; this asserts the third one is real -- that
    `SqliteReader.narrow` counts exactly the subtree this module derived, through its own bound.
    """
    conn = built.writer
    conn.execute("BEGIN IMMEDIATE")
    producer_id = _scaffold(conn)
    _twelve_sibling_tree(conn, producer_id)
    sec.derive_block_sec(conn, 1, 1)
    conn.execute("COMMIT")

    reader = rd.SqliteReader(ow.connect_readonly(built.path), now_ns=NOW_NS)
    with reader.snapshot() as state:
        assert reader.narrow(state, Filters(sec_path_prefix="/0001/0001")).n == 2
        assert reader.narrow(state, Filters(sec_path_prefix="/0001/0010")).n == 2
        assert reader.narrow(state, Filters(sec_path_prefix="/0001")).n == 25
        assert reader.narrow(state, Filters(sec_path_prefix="/0002")).n == 0


def test_re_deriving_produces_byte_identical_rows_and_sweeps_a_stale_one(built: Built) -> None:
    """`ow store rebuild <object>` depends on this: a `[DER]` object rebuilds from scratch
    (03:2477).

    Three assertions and each catches something different. The second run's rows are compared
    against the FIRST run's, read out of the database and held in Python, so a derivation that
    drifted between runs fails. They are also compared against paths written down HERE, so a
    mutation that changed both runs the same way still fails -- an equality whose two sides both
    come out of the store under test cannot fail. And a row planted over a block that IS re-derived
    is corrected, which is the overwrite half.

    The sweep half -- a row for a block the second run does not produce -- is the next test, and it
    is a separate test because it is a separate mutation: dropping the DELETE and writing
    `INSERT OR REPLACE` passes everything here and fails there.
    """
    conn = built.writer
    conn.execute("BEGIN IMMEDIATE")
    producer_id = _scaffold(conn)
    _twelve_sibling_tree(conn, producer_id)
    sec.derive_block_sec(conn, 1, 1)
    conn.execute("COMMIT")
    first = _rows(conn)

    conn.execute("BEGIN IMMEDIATE")
    conn.execute("UPDATE block_sec SET sec_path = '/9999', sec_depth = 1 WHERE block_id = 201")
    sec.derive_block_sec(conn, 1, 1)
    conn.execute("COMMIT")
    second = _rows(conn)

    assert second == first
    assert (2, 2, 1, "/0001") in second, "a literal the store cannot move"
    assert (110, 110, 2, "/0001/0010") in second
    assert (201, 101, 2, "/0001/0001") in second, "the planted row was corrected, not kept"
    assert len(second) == 26


def test_a_row_for_a_block_that_is_no_longer_live_is_swept_by_the_re_derivation(
    built: Built,
) -> None:
    """The DELETE, not the INSERT, is what makes `block_sec` match the generation it indexes.

    `block_sec` is one row per LIVE block (07:559-563) and 03:2477 makes it rebuildable from
    scratch, so a row for a block tombstoned since the last derivation must be gone afterwards.
    An `INSERT OR REPLACE` with no DELETE gets every re-derived row right and leaves that one
    behind -- a block the range scan keeps returning after the store stopped serving it. That
    mutation survives the idempotence test above, which is why this one exists.

    `state = 1` and not a `DELETE FROM block` because *"there is no DELETE"* (0001_init.sql:266);
    the FK's `ON DELETE CASCADE` would otherwise do this module's job for it and prove nothing.
    """
    conn = built.writer
    conn.execute("BEGIN IMMEDIATE")
    producer_id = _scaffold(conn)
    _twelve_sibling_tree(conn, producer_id)
    sec.derive_block_sec(conn, 1, 1)
    conn.execute("COMMIT")
    assert 212 in _paths(conn)

    conn.execute("BEGIN IMMEDIATE")
    conn.execute("UPDATE block SET state = 1 WHERE block_id = 212")
    report = sec.derive_block_sec(conn, 1, 1)
    conn.execute("COMMIT")

    assert 212 not in _paths(conn), "a tombstoned block keeps no block_sec row"
    assert len(report.rows) == 25
    assert _paths(conn)[211] == "/0001/0011", "every other row is untouched"


def test_a_second_document_is_not_touched_by_the_first_documents_derivation(built: Built) -> None:
    """The DELETE is scoped through the FK, because `block_sec` carries no `doc_ord` column."""
    conn = built.writer
    conn.execute("BEGIN IMMEDIATE")
    producer_id = _scaffold(conn, doc_ord=1)
    _block(conn, producer_id, block_id=1, kind="document", doc_ord=1)
    _scaffold(conn, doc_ord=2)
    _block(conn, producer_id, block_id=50, kind="document", doc_ord=2)
    _block(conn, producer_id, block_id=51, parent_id=50, kind="heading", level=1, doc_ord=2)
    sec.derive_block_sec(conn, 2, 1)
    sec.derive_block_sec(conn, 1, 1)
    conn.execute("COMMIT")

    assert _paths(conn) == {1: "/", 50: "/", 51: "/0001"}


def test_a_kind_code_the_stores_own_enum_val_cannot_name_is_refused(built: Built) -> None:
    """`reader.py:1133-1144`'s refusal, for its reason, and here it is a wrong ANSWER not a crash.

    A stored code with no `enum_val` row means the seed and the rows disagree. Guessing "not a
    section" would flatten a real hierarchy into one implicit section that answers every prefix
    query with the whole document -- a confident wrong set, which is the one outcome the section
    index exists to prevent.
    """
    conn = built.writer
    conn.execute("BEGIN IMMEDIATE")
    producer_id = _scaffold(conn)
    _block(conn, producer_id, block_id=1, kind="document")
    conn.execute("UPDATE block SET kind = 9999 WHERE block_id = 1")
    conn.execute("COMMIT")

    with pytest.raises(StoreError, match="enum_val"):
        sec.derive_block_sec(conn, 1, 1)


def test_a_heading_with_an_unreadable_payload_still_gets_a_row_at_level_one(built: Built) -> None:
    """A `[DER]` rebuild runs against what is on disk; refusing would break the one repair path."""
    conn = built.writer
    conn.execute("BEGIN IMMEDIATE")
    producer_id = _scaffold(conn)
    _block(conn, producer_id, block_id=1, kind="document")
    _block(conn, producer_id, block_id=2, parent_id=1, ord_=0, kind="heading", level=2)
    conn.execute("UPDATE block SET payload = 'not json' WHERE block_id = 2")
    _block(conn, producer_id, block_id=3, parent_id=1, ord_=1, kind="heading", level=1)
    sec.derive_block_sec(conn, 1, 1)
    conn.execute("COMMIT")

    assert _paths(conn) == {1: "/", 2: "/0001", 3: "/0002"}, "level 1 closes the degraded level 1"


def test_the_derivation_opens_no_connection_and_commits_nothing(built: Built) -> None:
    """ST1 (07:2721) and 07:2717: the `Unit` IS the transaction, so this function must not end one.

    Asserted by effect: the caller's transaction is rolled back after the derivation ran, and the
    rows are gone. A `COMMIT` inside `derive_block_sec` would leave them behind.
    """
    source = Path(sec.__file__).read_text(encoding="utf-8")
    assert "sqlite3.connect(" not in source
    conn = built.writer
    conn.execute("BEGIN IMMEDIATE")
    producer_id = _scaffold(conn)
    _block(conn, producer_id, block_id=1, kind="document")
    sec.derive_block_sec(conn, 1, 1)
    assert _paths(conn) == {1: "/"}
    conn.execute("ROLLBACK")
    assert _paths(conn) == {}
