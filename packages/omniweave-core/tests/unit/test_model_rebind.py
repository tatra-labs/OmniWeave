"""The three rules, the worked example, P21, and the quarantine that has no `--force`.

Specified in 03-document-model.md section 6.5 (:1236-1302, the rule table and the carry
statements), section 6.6 (:1316-1370, the worked example and the failing case), P21 (:3009,
rebind stability), :1150-1165 (cite gaps and "a retired cite still resolves"), :1735-1745 (the
resegmentation case) and :2686-2695 (what a below-threshold rebind leaves behind).

**Four things here are load-bearing and the rest supports them.**

1. **P21 verbatim** -- `test_p21_...`. An identical re-parse carries every block and every cite,
   creates and retires nothing, and advances `doc.gen` by exactly one. The property is what a
   shipped citation rests on and its failure mode is silent (13-quality.md:867), so the assertion
   is over every cite rather than over the counters alone.
2. **The rules in isolation, and the cite behaviour that distinguishes them.** Rule 1 carries the
   cite and leaves `revision`; rule 2 carries the cite and bumps `revision`; rule 3 keeps the
   staged row's fresh cite and writes a `block_history` row with a reason and a `superseded_by`.
3. **Determinism.** The same two generations decided twice give byte-identical plans, and the
   plan does not move when the INPUT SEQUENCES are shuffled -- which is the real hazard, because
   a store hands the matcher whatever order its index scan produced. Skipping the pass is what
   codegraph priced at "4.3% of distinct edges wrong, in both directions, silently"
   (00-vision.md:591); an order-dependent matcher is the same defect wearing a green suite.
4. **No `--force`.** 03:1302 says "there is no `--force` anywhere in the framework", so the
   absence is asserted by reflection over every public callable in the module rather than by one
   hand-written call, and the named override is checked to be the only way past a quarantine.

**A defect in the plan's worked example, resolved here and reported.** 03:1361-1364 states
`carried = 4, revised = 2, created = 1, retired = 0` for a document whose gen-1 table (03:1320)
has ten blocks across two pages. The gen-2 table at 03:1343-1355 prints only page 0 (six rows:
three rule-1, two rule-2, one rule-3), and the five elided page-1 rows are all identical-digest
rule-1 carries -- `match_rate_by_page = {0: 1.0, 1: 1.0}` says so, since a page with no matched
head block could not report 1.0. So no reading of the example makes `carried` 4: it is 10 over
the whole document under this module's inclusive reading of `carried`, 5 over the printed rows,
and 8 (or 3) if `carried` excluded `revised`. The same paragraph is inconsistent with itself in
the other direction too: it calls the printed carries "the five carried blocks" (03:1357) and
then lists nine discarded staged cites, `d7#11`-`d7#16` and `d7#18`-`d7#20`, which is ten staged
rows for an eleven-block generation. The fixture below is therefore built from the two TABLES,
which are the definition sites for what each row does, and asserts the report the tables imply,
row by row and then in total.
"""

from __future__ import annotations

import dataclasses
import hashlib
import inspect
import re
from pathlib import Path

import pytest
from omniweave_core.model import rebind as rebind_module
from omniweave_core.model.block import Addr, BlockId, Cite
from omniweave_core.model.enums import Kind
from omniweave_core.model.rebind import (
    DEFAULT_THRESHOLD,
    REPARSE_RESEGMENTED,
    RETIREMENT_REASONS,
    BlockFacts,
    Carry,
    Create,
    MatchPlan,
    RebindReport,
    Retire,
    Rule,
    follow_supersession,
    match_generations,
    rebind,
)


def scrambled(rows: list[BlockFacts], seed: int) -> list[BlockFacts]:
    """A deterministic re-ordering of `rows`. blake2b, not `random`.

    `random` is TID251-banned across the repo ("Sampling is blake2b. Determinism is a gate, not a
    habit."), and the ban is right here even though this is a test: a shuffle that cannot be
    reproduced turns an order-dependence failure into a flake, which is the one failure mode this
    test exists to make loud. Keying the sort on a digest of `(seed, block_id)` gives a different
    permutation per seed and the same permutation on every machine and every run.
    """
    return sorted(
        rows,
        key=lambda row: hashlib.blake2b(f"{seed}:{row.block_id}".encode(), digest_size=8).digest(),
    )


# ---------------------------------------------------------------------------
# Fixture helpers. A `BlockFacts` by hand is eight fields of noise; these make the
# interesting field the only one a test has to write.
# ---------------------------------------------------------------------------


def digest(token: str) -> bytes:
    """A 16-byte stand-in for an `ow128` (03:1170). Distinct tokens are distinct digests.

    Not a real `content_digest`: the matcher compares digests for equality and never re-derives
    one, so a fixture that hashed real text would be testing `omniweave_core.identity` instead of
    this module. `identity.content_digest` is tested where it lives.
    """
    return token.encode("utf-8").ljust(16, b"\x00")[:16]


def facts(
    block_id: int,
    addr: str,
    cite: str,
    *,
    kind: Kind = Kind.PARAGRAPH,
    parent: int | None = None,
    ord_: int = 0,
    page: int = 0,
    content: str = "",
    revision: int = 0,
) -> BlockFacts:
    return BlockFacts(
        block_id=BlockId(block_id),
        addr=Addr(addr),
        cite=Cite(cite),
        kind=kind,
        parent=None if parent is None else BlockId(parent),
        ord=ord_,
        page=page,
        content_digest=digest(content or addr),
        revision=revision,
    )


def plan_of(head: list[BlockFacts], staged: list[BlockFacts], *, to_gen: int = 2) -> MatchPlan:
    return match_generations(head, staged, doc_ord=7, from_gen=to_gen - 1, to_gen=to_gen)


def carry_by_new_id(plan: MatchPlan, new_id: int) -> Carry:
    (carry,) = [c for c in plan.carries if c.new_id == new_id]
    return carry


# ---------------------------------------------------------------------------
# The three rules in isolation, and the cite behaviour that separates them
# ---------------------------------------------------------------------------


def test_rule_one_carries_the_block_id_and_the_cite_and_leaves_revision_alone() -> None:
    """Rule 1: "equal `content_digest` under the same parent" (03:1257). `revision` unchanged."""
    root = facts(1, "doc", "d7#1", kind=Kind.DOCUMENT, content="root")
    head = [root, facts(2, "p0/0", "d7#2", parent=1, ord_=0, content="unchanged", revision=3)]
    staged = [
        facts(41, "doc", "d7#11", kind=Kind.DOCUMENT, content="root"),
        facts(42, "p0/0", "d7#12", parent=41, ord_=0, content="unchanged"),
    ]

    plan = plan_of(head, staged)

    carry = carry_by_new_id(plan, 42)
    assert carry.rule is Rule.DIGEST
    assert carry.old_id == 2
    assert carry.cite == "d7#2"  # the head's cite, not the staged row's fresh one
    assert (carry.bump, carry.revision) == (0, 3)
    assert (plan.carried(), plan.revised(), plan.created(), plan.retired()) == (2, 0, 0, 0)


def test_rule_one_matches_a_block_whose_addr_moved_because_the_digest_is_the_address() -> None:
    """The `page_footer` row of the worked example: `p0/3` becomes `p0/4` (03:1352-1355).

    "The row that would have broken under an ordinal identity is `page_footer`" -- under a
    position-bearing id every citation to it would point at the inserted paragraph instead.
    """
    head = [
        facts(1, "doc", "d7#1", kind=Kind.DOCUMENT, content="root"),
        facts(5, "p0/3", "d7#5", kind=Kind.PAGE_FOOTER, parent=1, ord_=3, content="page 1 of 2"),
    ]
    staged = [
        facts(41, "doc", "d7#11", kind=Kind.DOCUMENT, content="root"),
        facts(45, "p0/4", "d7#15", kind=Kind.PAGE_FOOTER, parent=41, ord_=4, content="page 1 of 2"),
    ]

    carry = carry_by_new_id(plan_of(head, staged), 45)

    assert (carry.rule, carry.old_id, carry.cite, carry.bump) == (Rule.DIGEST, 5, "d7#5", 0)


def test_rule_two_carries_the_cite_and_bumps_revision_by_exactly_one() -> None:
    """Rule 2: equal `addr` and `kind`, digest changed -> `revision += 1` (03:1258, :293)."""
    head = [
        facts(1, "doc", "d7#1", kind=Kind.DOCUMENT, content="root-v1"),
        facts(4, "p0/2", "d7#4", parent=1, ord_=2, content="text-v1", revision=1),
    ]
    staged = [
        facts(41, "doc", "d7#11", kind=Kind.DOCUMENT, content="root-v2"),
        facts(44, "p0/2", "d7#14", parent=41, ord_=2, content="text-v2"),
    ]

    plan = plan_of(head, staged)

    carry = carry_by_new_id(plan, 44)
    assert carry.rule is Rule.ADDR_KIND
    assert (carry.old_id, carry.cite) == (4, "d7#4")
    assert (carry.bump, carry.revision) == (1, 2)  # 1 at head + 1, not reset to 1
    assert plan.revised() == 2  # the root's subtree digest changed too (03:1345)
    assert plan.carried() == 2  # ... and both are carried: `carried` includes `revised`


def test_rule_two_needs_the_kind_to_match_and_not_only_the_addr() -> None:
    """Same `addr`, different `kind` is rule 3: the rule reads "equal `addr` **and** `kind`"."""
    head = [
        facts(1, "doc", "d7#1", kind=Kind.DOCUMENT, content="root"),
        facts(3, "p0/1", "d7#3", kind=Kind.HEADING, parent=1, ord_=1, content="one"),
    ]
    staged = [
        facts(41, "doc", "d7#11", kind=Kind.DOCUMENT, content="root"),
        facts(43, "p0/1", "d7#13", kind=Kind.TITLE, parent=41, ord_=1, content="two"),
    ]

    plan = plan_of(head, staged)

    assert [c.block_id for c in plan.creates] == [43]
    assert [(r.block_id, r.superseded_by) for r in plan.retires] == [(3, None)]


def test_rule_three_keeps_the_staged_fresh_cite_and_retires_the_old_row() -> None:
    """Rule 3: fresh id, fresh `n` from `doc.next_cite_n`, `revision` 0 (03:1260).

    The mint already happened -- the parse wrote the staged generation with fresh cites before the
    pass runs (03:1262) -- so what this asserts is that the pass does NOT re-point the fresh cite
    at anything and does not reuse a retired one.
    """
    head = [
        facts(1, "doc", "d7#1", kind=Kind.DOCUMENT, content="root"),
        facts(2, "p0/0", "d7#2", parent=1, ord_=0, content="gone"),
    ]
    staged = [
        facts(41, "doc", "d7#11", kind=Kind.DOCUMENT, content="root"),
        facts(42, "p0/0", "d7#12", kind=Kind.TABLE, parent=41, ord_=0, content="arrived"),
    ]

    plan = plan_of(head, staged)

    assert plan.creates == (Create(block_id=BlockId(42), cite=Cite("d7#12")),)
    assert plan.creates[0].rule is Rule.FRESH
    assert plan.creates[0].revision == 0
    assert plan.creates[0].cite not in {row.cite for row in head}
    (retired,) = plan.retires
    assert (retired.block_id, retired.doc_ord, retired.retired_gen) == (2, 7, 2)
    assert retired.reason == REPARSE_RESEGMENTED
    assert retired.reason in RETIREMENT_REASONS


def test_rule_one_beats_rule_two_when_both_could_match_the_same_staged_block() -> None:
    """The rules are ordered, not a set: an unchanged block must not spend a `revision`."""
    head = [
        facts(1, "doc", "d7#1", kind=Kind.DOCUMENT, content="root"),
        facts(2, "p0/0", "d7#2", parent=1, ord_=0, content="same"),
    ]
    staged = [
        facts(41, "doc", "d7#11", kind=Kind.DOCUMENT, content="root"),
        facts(42, "p0/0", "d7#12", parent=41, ord_=0, content="same"),
    ]

    assert carry_by_new_id(plan_of(head, staged), 42).rule is Rule.DIGEST


def test_a_digest_matching_two_candidates_resolves_by_nearest_ord() -> None:
    """03:1288: "resolved by nearest `ord` and the loser falls through to rule 2"."""
    head = [
        facts(1, "doc", "d7#1", kind=Kind.DOCUMENT, content="root"),
        facts(2, "p0/0", "d7#2", parent=1, ord_=0, content="twin"),
        facts(3, "p0/1", "d7#3", parent=1, ord_=1, content="twin"),
    ]
    staged = [
        facts(41, "doc", "d7#11", kind=Kind.DOCUMENT, content="root"),
        facts(43, "p0/1", "d7#13", parent=41, ord_=1, content="twin"),
    ]

    plan = plan_of(head, staged)

    carry = carry_by_new_id(plan, 43)
    assert carry.old_id == 3  # ord 1, not the lower-id ord-0 row
    assert [r.block_id for r in plan.retires] == [2]  # the loser is left for rule 2, then retires


# ---------------------------------------------------------------------------
# P21 -- rebind stability. 03:3009, verbatim.
# ---------------------------------------------------------------------------


def two_page_head() -> list[BlockFacts]:
    """The worked example's first ingest, 03:1320-1330: ten blocks, `gen = 1`, cites `d7#1`-`d7#10`.

    Ids, addrs, cites, parents, ords, pages and kinds are transcribed from that table. The five
    page-1 rows the gen-2 table elides are here because `match_rate_by_page[1]` proves they exist
    (03:1364).
    """
    return [
        facts(1, "doc", "d7#1", kind=Kind.DOCUMENT, content="root-v1"),
        facts(2, "p0/0", "d7#2", kind=Kind.TITLE, parent=1, ord_=0, content="msa"),
        facts(3, "p0/1", "d7#3", kind=Kind.HEADING, parent=1, ord_=1, content="definitions"),
        facts(4, "p0/2", "d7#4", kind=Kind.PARAGRAPH, parent=1, ord_=2, content="in-this-v1"),
        facts(5, "p0/3", "d7#5", kind=Kind.PAGE_FOOTER, parent=1, ord_=3, content="page-1-of-2"),
        facts(6, "p1/0", "d7#6", kind=Kind.CONTAINER, parent=1, ord_=4, page=1, content="column"),
        facts(7, "p1/0/0", "d7#7", kind=Kind.HEADING, parent=6, ord_=0, page=1, content="fees"),
        facts(8, "p1/0/1", "d7#8", kind=Kind.TABLE, parent=6, ord_=1, page=1, content="fee-table"),
        facts(
            9,
            "p1/0/1/r0c0",
            "d7#9",
            kind=Kind.TABLE_CELL,
            parent=8,
            ord_=0,
            page=1,
            content="segment",
        ),
        facts(
            10,
            "p1/0/1/r0c1",
            "d7#10",
            kind=Kind.TABLE_CELL,
            parent=8,
            ord_=1,
            page=1,
            content="fy2024",
        ),
    ]


def restage(head: list[BlockFacts], *, id_base: int = 40, cite_base: int = 10) -> list[BlockFacts]:
    """The same document parsed again: identical addrs, kinds and digests, FRESH ids and cites.

    "The parse has already written the staged generation `g_t` with *fresh* ids for every block"
    (03:1262), and every staged cite is a fresh `n` from `doc.next_cite_n` (03:1147). Re-using an
    id or a cite here would make the whole suite test nothing, because equality on either would do
    the matcher's work for it.
    """
    remap = {row.block_id: BlockId(id_base + index + 1) for index, row in enumerate(head)}
    return [
        dataclasses.replace(
            row,
            block_id=remap[row.block_id],
            cite=Cite(f"d7#{cite_base + index + 1}"),
            parent=None if row.parent is None else remap[row.parent],
        )
        for index, row in enumerate(head)
    ]


def test_p21_an_identical_reparse_carries_every_block_and_every_cite() -> None:
    """P21, 03:3009: `carried == n_blocks`, `created == 0`, `retired == 0`, every cite preserved.

    The generation bump is asserted through the store fake rather than derived from the report,
    because "advanced by exactly 1" is a statement about what was written, not about what was
    computed.
    """
    head = two_page_head()
    store = FakeStore(head_gen=1, generations={1: head, 2: restage(head)})

    report = rebind(store, 7, 2)

    assert report.carried == len(head)
    assert (report.revised, report.created, report.retired) == (0, 0, 0)
    assert not report.quarantined
    assert report.match_rate() == 1.0
    assert {carry.cite for carry in store.carried} == {row.cite for row in head}
    assert {carry.rule for carry in store.carried} == {Rule.DIGEST}
    assert store.committed == [(7, 2)]
    assert store.head_gen == 2  # exactly one generation, exactly once


def test_p21_holds_when_the_reparse_only_moves_geometry() -> None:
    """Geometry is deliberately not a digest input (03:249), so a shifted page still carries.

    `BlockFacts` carries no `quad` at all, which IS the assertion: there is no field through
    which geometry could reach a rule. The test states the consequence so a future field addition
    has to argue with a named property rather than with an omission.
    """
    assert "quad" not in {f.name for f in dataclasses.fields(BlockFacts)}
    assert "layout_digest" not in {f.name for f in dataclasses.fields(BlockFacts)}


def test_the_first_ingest_is_a_no_op_that_creates_everything_and_still_commits() -> None:
    """03:1338: "`rebind` (a no-op: `g_h = 0` has no rows, so `created = 10`)", then `gen = 1`.

    An empty head must not quarantine, and a zero denominator is the only way it could.
    """
    staged = restage(two_page_head(), id_base=0, cite_base=0)
    store = FakeStore(head_gen=0, generations={0: [], 1: staged})

    report = rebind(store, 7, 1)

    assert (report.carried, report.revised, report.created, report.retired) == (0, 0, 10, 0)
    assert report.match_rate() == 1.0
    assert report.match_rate_by_page == {}
    assert not report.quarantined
    assert store.head_gen == 1


# ---------------------------------------------------------------------------
# The worked example. 03:1343-1364, field by field.
# ---------------------------------------------------------------------------


def worked_example_staged() -> list[BlockFacts]:
    """The re-signed PDF of 03:1341-1355: one paragraph gains a clause, one is inserted.

    Page 0 is the gen-2 table verbatim -- `p0/3` is the NEW paragraph and the footer has moved to
    `p0/4` -- and page 1 is unchanged, which is what `match_rate_by_page = {0: 1.0, 1: 1.0}`
    requires. Ids 41-51 and cites `d7#11`-`d7#21`: eleven, not the ten the plan prints, because
    the generation has eleven blocks (see this module's docstring).
    """
    return [
        facts(41, "doc", "d7#11", kind=Kind.DOCUMENT, content="root-v2"),
        facts(42, "p0/0", "d7#12", kind=Kind.TITLE, parent=41, ord_=0, content="msa"),
        facts(43, "p0/1", "d7#13", kind=Kind.HEADING, parent=41, ord_=1, content="definitions"),
        facts(44, "p0/2", "d7#14", kind=Kind.PARAGRAPH, parent=41, ord_=2, content="in-this-v2"),
        facts(47, "p0/3", "d7#17", kind=Kind.PARAGRAPH, parent=41, ord_=3, content="inserted"),
        facts(45, "p0/4", "d7#15", kind=Kind.PAGE_FOOTER, parent=41, ord_=4, content="page-1-of-2"),
        facts(
            46, "p1/0", "d7#16", kind=Kind.CONTAINER, parent=41, ord_=5, page=1, content="column"
        ),
        facts(48, "p1/0/0", "d7#18", kind=Kind.HEADING, parent=46, ord_=0, page=1, content="fees"),
        facts(
            49, "p1/0/1", "d7#19", kind=Kind.TABLE, parent=46, ord_=1, page=1, content="fee-table"
        ),
        facts(
            50,
            "p1/0/1/r0c0",
            "d7#20",
            kind=Kind.TABLE_CELL,
            parent=49,
            ord_=0,
            page=1,
            content="segment",
        ),
        facts(
            51,
            "p1/0/1/r0c1",
            "d7#21",
            kind=Kind.TABLE_CELL,
            parent=49,
            ord_=1,
            page=1,
            content="fy2024",
        ),
    ]


def test_the_worked_example_decides_every_row_the_way_the_plan_prints_it() -> None:
    """03:1343-1355, one assertion per printed row: rule, `block_id`, `cite`, `revision`."""
    plan = plan_of(two_page_head(), worked_example_staged())
    by_new = {carry.new_id: carry for carry in plan.carries}

    # (staged id, rule, carried block_id, carried cite, resulting revision) -- the gen-2 table.
    assert (by_new[41].rule, by_new[41].old_id, by_new[41].cite, by_new[41].revision) == (
        Rule.ADDR_KIND,
        1,
        "d7#1",
        1,
    )
    assert (by_new[42].rule, by_new[42].old_id, by_new[42].cite, by_new[42].revision) == (
        Rule.DIGEST,
        2,
        "d7#2",
        0,
    )
    assert (by_new[43].rule, by_new[43].old_id, by_new[43].cite, by_new[43].revision) == (
        Rule.DIGEST,
        3,
        "d7#3",
        0,
    )
    assert (by_new[44].rule, by_new[44].old_id, by_new[44].cite, by_new[44].revision) == (
        Rule.ADDR_KIND,
        4,
        "d7#4",
        1,
    )
    assert plan.creates == (Create(block_id=BlockId(47), cite=Cite("d7#17")),)
    assert (by_new[45].rule, by_new[45].old_id, by_new[45].cite, by_new[45].revision) == (
        Rule.DIGEST,
        5,
        "d7#5",
        0,
    )
    # The five elided page-1 rows, all identical-digest carries.
    assert {(by_new[n].old_id, by_new[n].cite) for n in (46, 48, 49, 50, 51)} == {
        (6, "d7#6"),
        (7, "d7#7"),
        (8, "d7#8"),
        (9, "d7#9"),
        (10, "d7#10"),
    }
    assert all(by_new[n].rule is Rule.DIGEST for n in (46, 48, 49, 50, 51))


def test_the_worked_example_reports_the_counts_the_two_tables_imply() -> None:
    """03:1361-1364, corrected: `carried` is 10 over the whole document, not 4.

    `revised = 2` (the root plus `p0/2`), `created = 1`, `retired = 0` and
    `match_rate_by_page = {0: 1.0, 1: 1.0}` are the plan's own numbers and hold exactly. The
    module docstring records why `carried = 4` cannot be reconciled under any reading.
    """
    report = plan_of(two_page_head(), worked_example_staged()).report()

    assert (report.doc_ord, report.from_gen, report.to_gen) == (7, 1, 2)
    assert (report.carried, report.revised, report.created, report.retired) == (10, 2, 1, 0)
    assert dict(report.match_rate_by_page) == {0: 1.0, 1: 1.0}
    assert (report.quarantined, report.threshold) == (False, DEFAULT_THRESHOLD)


def test_the_worked_example_discards_the_staged_cites_of_every_carried_row() -> None:
    """03:1357-1359: the staged rows for the carried blocks are deleted, so their cites are gaps.

    The gap is correct -- "a gap is correct ... it is a retirement, or a cite minted for a staged
    row that `rebind()` then discarded" (03:1157) -- and what must never happen is a carried row
    wearing the staged cite.
    """
    plan = plan_of(two_page_head(), worked_example_staged())
    staged_cites = {row.cite for row in worked_example_staged()}

    gaps = staged_cites - {create.cite for create in plan.creates}

    assert len(gaps) == 10
    assert gaps.isdisjoint({carry.cite for carry in plan.carries})
    assert {create.cite for create in plan.creates} == {"d7#17"}


def test_the_counters_partition_both_generations() -> None:
    """`n_head == carried + retired` and `n_staged == carried + created`, on the example.

    This is the arithmetic that makes reading 1 of the module docstring checkable: if `carried`
    excluded `revised`, both identities would fail by exactly the number of rule-2 matches.
    """
    head, staged = two_page_head(), worked_example_staged()
    report = plan_of(head, staged).report()

    assert len(head) == report.carried + report.retired
    assert len(staged) == report.carried + report.created


# ---------------------------------------------------------------------------
# Resegmentation, and the retired cite that still resolves
# ---------------------------------------------------------------------------


def resegmentation_head() -> list[BlockFacts]:
    """A page whose first block is furniture the upgraded driver will drop.

    Three page-0 blocks under the root: a `page_header` at `p0/0` and two paragraphs at `p0/1`
    and `p0/2`. The header is here so the merged paragraph below lands at an addr the head
    generation holds with a DIFFERENT kind, which is what makes it a rule-3 block rather than a
    rule-2 carry -- `test_a_merge_that_keeps_an_input_addr_and_kind_is_a_rule_2_carry` is the
    other half of that fork, and the plan conflict behind it.
    """
    return [
        facts(1, "doc", "d7#1", kind=Kind.DOCUMENT, content="root-v1"),
        facts(2, "p0/0", "d7#2", kind=Kind.PAGE_HEADER, parent=1, ord_=0, content="running-head"),
        facts(3, "p0/1", "d7#3", parent=1, ord_=1, content="first-half"),
        facts(4, "p0/2", "d7#4", parent=1, ord_=2, content="second-half"),
    ]


def resegmentation_plan() -> MatchPlan:
    """Two head paragraphs merged into one new block: 03:1735-1742's row, as a fixture.

    "the merged block is a **new** block with a fresh id and cite; the inputs are retired through
    `block_history` with `reason='reparse_resegmented'` and `superseded_by` pointing at it".

    The upgraded driver destroys the running head and rejoins the paragraph that was split around
    it, so the merged block is the page's first block at `p0/0` -- an addr the head holds as a
    `page_header`, so no rule carries it and rule 3 mints nothing because the parse already did.
    """
    staged = [
        facts(41, "doc", "d7#11", kind=Kind.DOCUMENT, content="root-v2"),
        facts(42, "p0/0", "d7#12", parent=41, ord_=0, content="first-half second-half"),
    ]
    return plan_of(resegmentation_head(), staged)


def test_a_merge_creates_a_new_block_and_retires_both_inputs_to_it() -> None:
    """03:1740, both halves: the merged block is new, and both inputs point at it."""
    plan = resegmentation_plan()

    assert [create.block_id for create in plan.creates] == [42]
    assert [(r.block_id, r.superseded_by, r.reason) for r in plan.retires] == [
        (2, None, REPARSE_RESEGMENTED),
        (3, 42, REPARSE_RESEGMENTED),
        (4, 42, REPARSE_RESEGMENTED),
    ]
    assert plan.carried() == 1  # the root only: its addr and kind survive, its digest changed
    assert plan.revised() == 1


def test_the_dropped_furniture_block_is_retired_with_no_successor() -> None:
    """The destroyed running head has no successor of its kind, so `superseded_by` is NULL.

    "NULL = retired with no defensible successor" (`schema/migrations/0001_init.sql:334`). A
    successor of another `kind` would be a guess, and a `page_header` cite resolving to a
    paragraph is the "nearby block" 03:1163 forbids.
    """
    (header, *_) = resegmentation_plan().retires

    assert (header.block_id, header.superseded_by) == (2, None)


def test_a_merge_that_keeps_an_input_addr_and_kind_is_a_rule_2_carry() -> None:
    """Where 03:1258 and 03:1740 collide the rule table wins, and the collision is real.

    A merge whose output keeps the first input's `addr` and `kind` -- the ordinary case, because
    `addr` is positional and a merged block starts where its first input did -- satisfies rule 2
    exactly: same `addr`, same `kind`, changed digest. So it carries that input's `block_id` AND
    its cite and bumps `revision`, instead of minting the fresh id 03:1740 describes. For a
    re-parse that is the right answer: 03:1763's composition table lists "Rebind -- section 6.5"
    as its own row, so section 8.5(a)'s merge composition governs a merge OPERATOR inside one
    generation, not the matcher deciding identity across two. The absorbed input gets no
    successor, because a merge and a deletion are indistinguishable from digests alone.
    """
    head = [
        facts(1, "doc", "d7#1", kind=Kind.DOCUMENT, content="root-v1"),
        facts(2, "p0/0", "d7#2", parent=1, ord_=0, content="first-half", revision=4),
        facts(3, "p0/1", "d7#3", parent=1, ord_=1, content="second-half"),
    ]
    staged = [
        facts(41, "doc", "d7#11", kind=Kind.DOCUMENT, content="root-v2"),
        facts(42, "p0/0", "d7#12", parent=41, ord_=0, content="first-half second-half"),
    ]

    plan = plan_of(head, staged)

    carry = carry_by_new_id(plan, 42)
    assert (carry.rule, carry.old_id, carry.cite, carry.revision) == (
        Rule.ADDR_KIND,
        2,
        "d7#2",
        5,
    )
    assert plan.creates == ()
    assert [(r.block_id, r.superseded_by) for r in plan.retires] == [(3, None)]


def test_a_deletion_retires_with_no_successor_rather_than_naming_a_neighbour() -> None:
    """03:1163 forbids resolving a retired cite to "a nearby block", so NULL is the honest answer.

    `superseded_by` is "NULL = retired with no defensible successor"
    (`schema/migrations/0001_init.sql:334`), and a plain deletion has none.
    """
    head = [
        facts(1, "doc", "d7#1", kind=Kind.DOCUMENT, content="root-v1"),
        facts(2, "p0/0", "d7#2", parent=1, ord_=0, content="kept"),
        facts(3, "p0/1", "d7#3", parent=1, ord_=1, content="deleted"),
    ]
    staged = [
        facts(41, "doc", "d7#11", kind=Kind.DOCUMENT, content="root-v2"),
        facts(42, "p0/0", "d7#12", parent=41, ord_=0, content="kept"),
    ]

    plan = plan_of(head, staged)

    assert [(r.block_id, r.superseded_by) for r in plan.retires] == [(3, None)]


def test_a_retired_cite_resolves_through_superseded_by() -> None:
    """ "**A retired cite still resolves.** `ow open --by-cite` follows
    `block_history.superseded_by`" (03:1159)."""
    plan = resegmentation_plan()

    assert follow_supersession(plan.retires, BlockId(3)) == 42
    assert follow_supersession(plan.retires, BlockId(4)) == 42
    assert follow_supersession(plan.retires, BlockId(42)) == 42  # a live id resolves to itself


def test_a_chain_of_two_retirements_resolves_to_the_live_block() -> None:
    """A successor can itself be retired by a later re-parse; the hop follows through."""
    history = [
        Retire(block_id=BlockId(2), doc_ord=7, retired_gen=2, superseded_by=BlockId(42)),
        Retire(block_id=BlockId(42), doc_ord=7, retired_gen=3, superseded_by=BlockId(90)),
    ]

    assert follow_supersession(history, BlockId(2), live=[BlockId(90)]) == 90


def test_a_retirement_with_no_successor_anywhere_in_the_chain_resolves_to_none() -> None:
    """Where the chain ends at NULL the caller owes `OW-M-030 / OW_CITE_RETIRED` (03:1161)."""
    history = [
        Retire(block_id=BlockId(2), doc_ord=7, retired_gen=2, superseded_by=BlockId(42)),
        Retire(block_id=BlockId(42), doc_ord=7, retired_gen=3, superseded_by=None),
    ]

    assert follow_supersession(history, BlockId(2)) is None


def test_a_supersession_cycle_terminates_instead_of_looping() -> None:
    history = [
        Retire(block_id=BlockId(2), doc_ord=7, retired_gen=2, superseded_by=BlockId(3)),
        Retire(block_id=BlockId(3), doc_ord=7, retired_gen=2, superseded_by=BlockId(2)),
    ]

    with pytest.raises(ValueError, match="supersession cycle"):
        follow_supersession(history, BlockId(2))


# ---------------------------------------------------------------------------
# The quarantine, and the override that is named per check
# ---------------------------------------------------------------------------


class FakeStore:
    """A hand-written `RebindStore`. Records what was applied; applies nothing to any real row.

    Not a mock library and not a real SQLite store: the wiring to the real store is the next
    wave's, and what has to be checked here is that a quarantine writes NOTHING -- which a
    recording fake states better than a database, because "nothing" is a property of the call
    sequence.
    """

    def __init__(self, *, head_gen: int, generations: dict[int, list[BlockFacts]]) -> None:
        self.head_gen = head_gen
        self.generations = generations
        self.carried: list[Carry] = []
        self.retired: list[Retire] = []
        self.committed: list[tuple[int, int]] = []
        self.reads: list[tuple[int, int]] = []

    def doc_generation(self, doc_ord: int) -> int:
        assert doc_ord == 7
        return self.head_gen

    def blocks_at_gen(self, doc_ord: int, gen: int) -> list[BlockFacts]:
        assert doc_ord == 7
        self.reads.append((doc_ord, gen))
        return list(self.generations[gen])

    def carry_forward(self, carry: Carry) -> None:
        self.carried.append(carry)

    def retire(self, retirement: Retire) -> None:
        self.retired.append(retirement)

    def commit_generation(self, doc_ord: int, gen: int) -> None:
        self.committed.append((doc_ord, gen))
        self.head_gen = gen


def resegmented_page_zero() -> FakeStore:
    """The failing case of 03:1366-1370: a driver upgrade re-segments page 0 into lines.

    "Every digest differs, no `addr` survives with its kind, `match_rate_by_page[0] = 0.0`, and
    the generation is **quarantined** ... `doc.gen` stays at 2 and every existing citation keeps
    resolving." The four page-0 blocks become four `line` blocks at the same addrs, so the addrs
    exist but their kinds do not match, which is what "no `addr` survives with its kind" means.
    """
    head = two_page_head()
    staged = [
        facts(41, "doc", "d7#11", kind=Kind.DOCUMENT, content="root-v2"),
        facts(42, "p0/0", "d7#12", kind=Kind.CONTAINER, parent=41, ord_=0, content="line-group"),
        facts(43, "p0/0/0", "d7#13", parent=42, ord_=0, content="line-a"),
        facts(44, "p0/0/1", "d7#14", parent=42, ord_=1, content="line-b"),
        facts(45, "p0/0/2", "d7#15", parent=42, ord_=2, content="line-c"),
        *[
            dataclasses.replace(
                row,
                block_id=BlockId(row.block_id + 40),
                cite=Cite(f"d7#{row.block_id + 10}"),
                parent=BlockId(41 if row.parent == 1 else row.parent + 40),
            )
            for row in head
            if row.page == 1
        ],
    ]
    return FakeStore(head_gen=1, generations={1: head, 2: staged})


def test_a_below_threshold_reparse_is_quarantined_and_writes_absolutely_nothing() -> None:
    """03:2690: "durable, invisible, inspectable by `ow doc diff`" -- so no carry, no bump."""
    store = resegmented_page_zero()

    report = rebind(store, 7, 2)

    assert report.quarantined
    assert report.match_rate_by_page[0] == 0.0
    assert report.match_rate_by_page[1] == 1.0
    assert report.match_rate() < report.threshold
    assert (store.carried, store.retired, store.committed) == ([], [], [])
    assert store.head_gen == 1  # `doc.gen` did not move, so every existing cite still resolves


def test_only_the_named_override_clears_a_quarantine() -> None:
    """`--allow-unexplained-rebind`, "named per check" (03:1300-1302), reaching us by keyword."""
    store = resegmented_page_zero()

    report = rebind(store, 7, 2, allow_unexplained=True)

    assert not report.quarantined
    assert report.match_rate() < report.threshold  # still unexplained, and the report says so
    assert store.committed == [(7, 2)]
    assert len(store.carried) == report.carried
    assert len(store.retired) == report.retired


def test_the_threshold_is_strictly_below_so_a_run_exactly_at_it_commits() -> None:
    """ "**Below** `threshold`" (03:1300). Four of five head blocks carried is exactly 0.80."""
    head = [
        facts(1, "doc", "d7#1", kind=Kind.DOCUMENT, content="root"),
        *[
            facts(2 + n, f"p0/{n}", f"d7#{2 + n}", parent=1, ord_=n, content=f"b{n}")
            for n in range(4)
        ],
    ]
    staged = [
        facts(41, "doc", "d7#11", kind=Kind.DOCUMENT, content="root"),
        *[
            facts(42 + n, f"p0/{n}", f"d7#{12 + n}", parent=41, ord_=n, content=f"b{n}")
            for n in range(3)
        ],
        facts(45, "p0/3", "d7#15", kind=Kind.TABLE, parent=41, ord_=3, content="new"),
    ]
    plan = plan_of(head, staged)

    assert plan.match_rate() == pytest.approx(0.8)
    assert not plan.report(threshold=0.80).quarantined
    assert plan.report(threshold=0.81).quarantined


def test_the_report_names_the_threshold_it_was_judged_against() -> None:
    """A report that did not carry its own threshold would make a quarantine unexplainable."""
    plan = plan_of(two_page_head(), worked_example_staged())

    assert plan.report(threshold=0.5).threshold == 0.5
    with pytest.raises(ValueError, match=r"rate in \[0.0, 1.0\]"):
        plan.report(threshold=1.5)


def test_there_is_no_force_parameter_anywhere_on_the_module_surface() -> None:
    """03:1302: "there is no `--force` anywhere in the framework". By reflection, not by example.

    Every public callable and every dataclass field is checked, because a `force` that arrived on
    a record would be as effective an override as one on the function.
    """
    offenders: list[str] = []
    for name, obj in vars(rebind_module).items():
        if name.startswith("_"):
            continue
        if inspect.isfunction(obj):
            offenders += [
                f"{name}({param})"
                for param in inspect.signature(obj).parameters
                if "force" in param
            ]
        if dataclasses.is_dataclass(obj):
            offenders += [f"{name}.{f.name}" for f in dataclasses.fields(obj) if "force" in f.name]

    assert offenders == []


def test_the_printed_signature_is_the_plans_signature() -> None:
    """03:1252 prints `rebind(store, doc_ord, to_gen, *, threshold=0.80)`.

    `allow_unexplained` is an ADDITION and is reported as one: the plan names
    `--allow-unexplained-rebind` (00-vision.md:644, 02-architecture.md:996) but never says how the
    flag reaches this function, and threading it through `threshold` would make the report lie
    about which threshold was applied. It is keyword-only with a `False` default, so every call
    the plan prints still type-checks and still means the same thing.
    """
    parameters = inspect.signature(rebind).parameters

    assert list(parameters) == ["store", "doc_ord", "to_gen", "threshold", "allow_unexplained"]
    assert parameters["threshold"].default == DEFAULT_THRESHOLD
    assert parameters["threshold"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["allow_unexplained"].default is False
    assert parameters["allow_unexplained"].kind is inspect.Parameter.KEYWORD_ONLY


def test_the_report_field_set_is_the_plans_field_set_in_the_plans_order() -> None:
    """03:1245-1250, transcribed. A report that grew a field would be a second tolerance to drift.

    Read out of the plan rather than restated, so the assertion cannot agree with a wrong
    dataclass by construction.
    """
    plan_text = _plan_lines(1244, 1251)
    printed: list[str] = []
    for line in plan_text:
        body = line.split("#", 1)[0].strip()
        if not body or body.startswith(("@", "class")):
            continue
        printed += [chunk.split(":")[0].strip() for chunk in body.split(";") if ":" in chunk]

    assert printed == [f.name for f in dataclasses.fields(RebindReport)]


def _plan_lines(first: int, last: int) -> list[str]:
    """`_plan/03-document-model.md` lines `[first, last)`, 1-based, as the plan numbers them.

    `_plan/` is read-only settled law; reading it in a test is how a transcription stays honest.
    The repo root is found from this file, not from the working directory.
    """
    root = Path(__file__).resolve().parents[4]
    text = (root / "_plan" / "03-document-model.md").read_text(encoding="utf-8").splitlines()
    return text[first - 1 : last - 1]


# ---------------------------------------------------------------------------
# Determinism -- the defect the estimation basis cites
# ---------------------------------------------------------------------------


def test_the_same_two_generations_decide_the_same_way_twice() -> None:
    head, staged = two_page_head(), worked_example_staged()

    first, second = plan_of(head, staged), plan_of(head, staged)

    assert first.carries == second.carries
    assert first.creates == second.creates
    assert first.retires == second.retires
    assert dict(first.match_rate_by_page) == dict(second.match_rate_by_page)


def test_the_decisions_do_not_depend_on_the_order_the_rows_arrive_in() -> None:
    """A store hands the matcher whatever its index scan produced, so the order is not ours.

    Twenty shuffles of both sequences, including the resegmentation shape where two head rows
    compete for one successor and the twin-digest shape where two candidates compete for one
    staged block. An order-dependent matcher is the exact defect the estimation basis prices at
    "4.3% of distinct edges wrong, in both directions, silently" (00-vision.md:591).
    """
    head, staged = two_page_head(), worked_example_staged()
    baseline = plan_of(head, staged)

    for seed in range(20):
        again = plan_of(scrambled(head, seed), scrambled(staged, seed))
        assert again.carries == baseline.carries
        assert again.creates == baseline.creates
        assert again.retires == baseline.retires


def test_the_nearest_ord_tie_break_does_not_depend_on_the_head_order() -> None:
    """Two head candidates with one digest under one parent is where order-dependence hides.

    The worked example has no such pair, so the shuffle above cannot see a matcher that took
    "whichever candidate the scan yielded first". This fixture does: `p0/0` and `p0/1` carry the
    same digest, only one staged block claims it, and 03:1288 fixes the answer as the nearest
    `ord` regardless of which order the rows arrived in.
    """
    head = [
        facts(1, "doc", "d7#1", kind=Kind.DOCUMENT, content="root"),
        facts(2, "p0/0", "d7#2", parent=1, ord_=0, content="twin"),
        facts(3, "p0/1", "d7#3", parent=1, ord_=1, content="twin"),
        facts(4, "p0/2", "d7#4", parent=1, ord_=2, content="twin"),
    ]
    staged = [
        facts(41, "doc", "d7#11", kind=Kind.DOCUMENT, content="root"),
        facts(42, "p0/1", "d7#12", parent=41, ord_=1, content="twin"),
    ]

    for seed in range(20):
        plan = plan_of(scrambled(head, seed), scrambled(staged, seed))
        assert carry_by_new_id(plan, 42).old_id == 3
        assert [r.block_id for r in plan.retires] == [2, 4]


def test_the_merge_successor_does_not_depend_on_the_head_order_either() -> None:
    """Two retired rows competing for one successor is where an unstable tie-break would show."""
    baseline = resegmentation_plan()

    assert [(r.block_id, r.superseded_by) for r in baseline.retires] == [
        (2, None),
        (3, 42),
        (4, 42),
    ]
    staged = [
        facts(41, "doc", "d7#11", kind=Kind.DOCUMENT, content="root-v2"),
        facts(42, "p0/0", "d7#12", parent=41, ord_=0, content="first-half second-half"),
    ]
    for seed in range(10):
        again = plan_of(scrambled(resegmentation_head(), seed), scrambled(staged, seed))
        assert again.retires == baseline.retires


def test_the_retirements_are_ordered_by_page_then_ord() -> None:
    """A plan is a diff (13-quality.md:840), and a diff whose row order moves fails its golden."""
    head = [
        facts(1, "doc", "d7#1", kind=Kind.DOCUMENT, content="root"),
        facts(2, "p1/0", "d7#2", parent=1, ord_=1, page=1, content="a"),
        facts(3, "p0/0", "d7#3", parent=1, ord_=0, page=0, content="b"),
        facts(4, "p1/1", "d7#4", parent=1, ord_=0, page=1, content="c"),
    ]
    staged = [facts(41, "doc", "d7#11", kind=Kind.DOCUMENT, content="root")]

    plan = plan_of(head, staged)

    assert [r.block_id for r in plan.retires] == [3, 4, 2]


# ---------------------------------------------------------------------------
# Boundary discipline: what the matcher refuses, and what it is made of
# ---------------------------------------------------------------------------


def test_every_type_in_the_module_is_frozen_and_slotted() -> None:
    """`BlockDraft` is the ONE mutable type in the framework (03:91), and it is not here.

    Asserted over the whole module rather than per class, so a record cannot arrive mutable by
    omission -- which is exactly how it would arrive.
    """
    for name, obj in vars(rebind_module).items():
        if not dataclasses.is_dataclass(obj) or not isinstance(obj, type):
            continue
        params = obj.__dataclass_params__
        assert params.frozen, f"{name} is not frozen"
        assert getattr(obj, "__slots__", None) is not None, f"{name} is not slotted"


def test_the_module_imports_no_store_and_no_third_party_name() -> None:
    """`model` may not depend on `store` (INV-2 for the dependency, layers for the direction).

    The protocols exist precisely so this holds: the store implements them structurally and
    neither side imports the other.
    """
    source = Path(rebind_module.__file__).read_text(encoding="utf-8")
    imports = re.findall(r"^(?:from|import)\s+([\w.]+)", source, flags=re.MULTILINE)

    assert [name for name in imports if name.startswith("omniweave_core.store")] == []
    assert all(
        name.startswith(("omniweave_core.", "__future__"))
        or name in {"collections.abc", "dataclasses", "enum", "types", "typing"}
        for name in imports
    ), imports


def test_a_digest_that_is_not_bytes_is_refused_at_construction() -> None:
    """A `str` digest compares unequal to every stored `bytes` digest, so every rule would miss.

    The failure would look like a total re-segmentation rather than like a type error, which is
    why it is refused at construction instead of being allowed to reach a rule.
    """
    for bad in ("", b"", "not-bytes"):
        with pytest.raises(ValueError, match="non-empty bytes"):
            BlockFacts(
                block_id=BlockId(1),
                addr=Addr("doc"),
                cite=Cite("d7#1"),
                kind=Kind.DOCUMENT,
                parent=None,
                ord=0,
                page=0,
                content_digest=bad,  # type: ignore[arg-type]
            )


def test_a_duplicate_addr_within_one_generation_is_refused() -> None:
    """`block_addr` is `UNIQUE(doc_ord, gen, addr)` (03:2366), so two rows cannot share one."""
    head = [
        facts(1, "doc", "d7#1", kind=Kind.DOCUMENT, content="root"),
        facts(2, "p0/0", "d7#2", parent=1, ord_=0, content="a"),
        facts(3, "p0/0", "d7#3", parent=1, ord_=1, content="b"),
    ]

    with pytest.raises(ValueError, match="block_addr is UNIQUE"):
        plan_of(head, [facts(41, "doc", "d7#11", kind=Kind.DOCUMENT, content="root")])


def test_a_parent_that_names_no_row_in_its_own_generation_is_refused() -> None:
    """A dangling parent would make every rule-1 candidate under it invisible, silently."""
    staged = [
        facts(41, "doc", "d7#11", kind=Kind.DOCUMENT, content="root"),
        facts(42, "p0/0", "d7#12", parent=99, ord_=0, content="orphan"),
    ]

    with pytest.raises(ValueError, match="names parent 99"):
        plan_of([], staged, to_gen=1)


def test_rebind_refuses_a_to_gen_that_is_not_ahead_of_the_head() -> None:
    """The staged generation is `doc.gen + 1` (03:1318); re-binding onto the head is not a pass."""
    store = FakeStore(head_gen=2, generations={2: two_page_head()})

    with pytest.raises(ValueError, match="must be ahead of the head generation"):
        rebind(store, 7, 2)


def test_rebind_reads_the_head_and_the_staged_generation_and_nothing_else() -> None:
    """Two reads, not a scan per block: the pass is O(blocks) with two index probes each (03:1290).

    Also asserts it does NOT go through `ow_block_head`, which cannot see a staged generation
    (03:2378) -- the read is by generation number, and both numbers are asked for explicitly.
    """
    head = two_page_head()
    store = FakeStore(head_gen=1, generations={1: head, 2: restage(head)})

    rebind(store, 7, 2)

    assert store.reads == [(7, 1), (7, 2)]
