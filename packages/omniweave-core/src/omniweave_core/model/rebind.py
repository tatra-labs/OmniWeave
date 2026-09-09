"""`rebind()` -- re-parse identity as an explicit pass, and the pure matcher underneath it.

Implements 03-document-model.md section 6.5 (:1236-1300, the three rules and the statement-by-
statement carry) and section 6.6 (:1316-1370, the worked example and the failing case).
`02-architecture.md:248` lists `rebind()` under `omniweave_core.model`, so this is its home, and
`18-api-sketch.md:838` puts it on the same T-SCHEMA row as `Doc` and `serialize()`.

**One matcher, two consumers** (16-roadmap.md:417, 01-principles.md:651, 13-quality.md:832-845).
The module is split at exactly that seam:

* `match_generations()` is PURE. It takes two sequences of `BlockFacts` -- the fields the three
  rules read -- and returns a `MatchPlan`: every carry, every creation, every retirement, in a
  fixed order, with no store, no SQL and no I/O. This is the half `diff_deep()`
  (13-quality.md:835) re-uses; a semantic diff *is* this decision set (13:840-843).
* `rebind()` is thin. It reads the two generations through `RebindReadSide`, calls the matcher,
  and applies the decisions through `RebindWriteSide`. Both are structural `Protocol`s declared
  here: `model` must not import `store` (11-repo-layout.md's layer order), and the plan prints
  `rebind`'s first parameter unannotated (03:1252) precisely because the backend is swappable --
  the same reason `Snapshot.token` is typed `object` (07-store-and-retrieval.md:72-78).

**Why the pass exists at all.** codegraph measured 1,227 edges -- 4.3% of distinct edges -- wrong
in both directions, silently, from skipping the equivalent pass (00-vision.md:591, 03:1284). A
cite is a shipped, durable name; re-minting it on re-parse re-points every citation already in
someone's document. So identity carries and confidence does not: `trust`, `quote`, `score`,
`method`, `producer_id` and the spans on a carried row are the NEW generation's values (03:1296),
which is why nothing in `BlockFacts` mentions any of them.

**Three readings this module had to settle, because the plan states each only once.**

1. `carried` INCLUDES `revised`. The rule table's `block_id` column reads "carried" for rule 1
   and "carried" for rule 2 (03:1257-1259); 13-quality.md:840 says rule 2 "carries it and bumps
   `revision`"; P-3 (13:867) says a payload-only mutation makes `rebind()` carry "every
   `block_id` and every `cite`" while `revision` increments only on the mutated blocks; and
   03:1357 calls the worked example's three rule-1 plus two rule-2 rows "the five carried
   blocks". So `carried` counts every matched block and `revised` is the subset whose `revision`
   moved. The arithmetic that follows is asserted by the tests: `n_head == carried + retired` and
   `n_staged == carried + created`.
2. `match_rate_by_page` is computed over the HEAD generation's blocks, EXCLUDING the `document`
   root. Head-side is forced by the worked example, where page 0 gains a block and still reports
   `1.0` (03:1364) -- a staged-side rate would read 4/5. Excluding the root is forced by the
   failing case, where page 0 is re-segmented and reports exactly `0.0` (03:1367) even though the
   root, whose `page` is `0` "by convention ... where it carries no meaning" (03:281), still
   matches by rule 2. The root is counted in `carried`/`revised` -- the worked example's
   `revised = 2` is the root plus `p0/2` -- just not in the per-page rate.
3. `retired_gen` is `to_gen`, the generation a row was retired AT (glossary.md:242), which is
   also the generation `OW_CITE_RETIRED` names (03:1161-1163). The retired row itself stays at
   its old `gen` with `state = 1` (03:1276); those are two different numbers.

**What the quarantine is.** Below `threshold` the new generation is not committed: `doc.gen` is
not bumped, the staged rows stay durable and invisible for `ow doc diff`, and the override is
named per check -- `--allow-unexplained-rebind`, reaching this function as `allow_unexplained`.
There is no `--force` anywhere in the framework (03:1300-1302, 07:2930) and there is no `force`
parameter anywhere on this module's surface; `test_model_rebind.py` asserts that by reflection.
`rebind()` RETURNS the report rather than raising `OW_REBIND_UNEXPLAINED` (03:1368): the report is
what carries `match_rate_by_page` to the surface that must explain the refusal (00-vision.md:633),
so the raise belongs to `end_doc()`'s caller, and the symbol is exported here as one name.

Stdlib only, like everything under `omniweave_core.model` (INV-2, gate G1). This module is inside
one of the nine LAZY subpackages, so nothing eager may reach it (G17).

Tier T-SCHEMA: 02-architecture.md section 2 row 24.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import IntEnum
from types import MappingProxyType
from typing import Final, Protocol

from omniweave_core.model.block import Addr, BlockId, Cite
from omniweave_core.model.enums import Kind

# `Mapping`/`Sequence` are runtime imports and not `if TYPE_CHECKING:` ones, for the reason
# `model/block.py` records: `typing.get_type_hints()` over these dataclasses is how the tests and
# `ow schema emit` walk them, and a name that exists only for a type checker makes that raise.

__all__ = [
    "DEFAULT_THRESHOLD",
    "REBIND_UNEXPLAINED",
    "REPARSE_RESEGMENTED",
    "RETIREMENT_REASONS",
    "BlockFacts",
    "Carry",
    "Create",
    "MatchPlan",
    "RebindReadSide",
    "RebindReport",
    "RebindStore",
    "RebindWriteSide",
    "Retire",
    "Rule",
    "follow_supersession",
    "match_generations",
    "rebind",
]


DEFAULT_THRESHOLD: Final = 0.80
"""The quarantine threshold, from `rebind`'s printed default at 03-document-model.md:1252.

Also the number 00-vision.md:591 names as "a 0.80 quarantine threshold" and the one
13-quality.md:1894 sizes `MAX_DRIFT_BAND` against, which is the second reason the rate compared
against it is document-wide rather than the minimum over pages: a 1,000-block document's 20-block
drift is 2%, and that reasoning only holds if the 20 blocks are weighed against the whole document.
"""

REBIND_UNEXPLAINED: Final = "OW_REBIND_UNEXPLAINED"
"""The `codes.toml` symbol a quarantine is reported under (03-document-model.md:1368, :3221).

Declared as a name rather than raised here, because the report is the return value. The register
row does not exist in `codes.toml` yet, and that file is not this work item's to edit.
"""

REPARSE_RESEGMENTED: Final = "reparse_resegmented"
"""The retirement reason `rebind()` writes. 03-document-model.md:1740 fixes the spelling.

It is the reason for every retirement this pass produces, the escalation case of 03:1763
included, because from the matcher's side both are the same fact: the staged generation contains
nothing that matches the row. The other three reasons in `RETIREMENT_REASONS` are written by
passes that are not this one -- a card upgrade, a source deletion, a compaction.
"""

RETIREMENT_REASONS: Final = frozenset(
    {REPARSE_RESEGMENTED, "driver_upgrade", "source_deleted", "compacted"}
)
"""`block_history.reason`'s four values, transcribed from the DDL comment at 03:2384.

A frozenset and not an `enum_val` domain: `reason` is `TEXT NOT NULL` with no closed-domain
trigger (`schema/migrations/0001_init.sql:332-336`), so it is not one of the fifteen ordinal
vocabularies of `model/enums.py` and must not grow an ordinal here.
"""


class Rule(IntEnum):
    """Which of the three rules matched. The member values ARE the plan's rule numbers.

    03-document-model.md:1256-1260 is the table. `DIGEST` is rule 1 (equal `content_digest` under
    the same parent), `ADDR_KIND` is rule 2 (equal `addr` and `kind`), `FRESH` is rule 3
    (neither). An `IntEnum` rather than a `StrEnum` because the numbers are how the plan and every
    review of it refer to these rules, and no wire format carries this value: it is a decision the
    pass makes and reports, never a stored column, so it has no `enum_val` ordinal to protect.
    """

    DIGEST = 1
    ADDR_KIND = 2
    FRESH = 3


@dataclass(frozen=True, slots=True)
class BlockFacts:
    """The fields the three rules read, and nothing else.

    A deliberately small projection of `Block`, for two reasons. The matcher is pure, so it must
    be constructible from a golden import as easily as from a `SELECT` (13-quality.md:835-838).
    And every field a rule does NOT read would be a field a reader could mistake for one that
    matters: identity carries, confidence does not (03:1296), so `trust`, `quote`, `score`,
    `method` and `producer_id` are absent on purpose.

    `page` is here for one consumer only, `RebindReport.match_rate_by_page` (03:1249). `revision`
    is here because rule 2's result is `revision + 1` and a `Carry` reports the resulting value
    rather than the bump.

    `content_digest` is validated non-empty and not for its width: `ow128` is 16 bytes (03:1170)
    but the matcher only ever compares digests for equality, and the width is
    `omniweave_core.identity`'s to state. Geometry is deliberately not a digest input (03:249), so
    a block that only moved on the page matches rule 1 and keeps its cite.
    """

    block_id: BlockId
    addr: Addr
    cite: Cite
    kind: Kind
    parent: BlockId | None
    ord: int
    page: int
    content_digest: bytes
    revision: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.content_digest, bytes) or not self.content_digest:
            msg = f"content_digest must be non-empty bytes, got {self.content_digest!r}"
            raise ValueError(msg)
        for name in ("ord", "page", "revision"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                msg = f"{name} must be a non-negative int, got {value!r}"
                raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class Carry:
    """One matched pair: the durable row moves forward and takes the staged row's content.

    The two ids are not interchangeable and the order of the two statements is mandatory
    (03:1264-1280). `new_id` -- the staged row -- is DELETEd first, because `block_addr` is
    `UNIQUE(doc_ord, gen, addr)` and moving `old_id` to `to_gen` while the staged row still holds
    that addr is a constraint violation. Only then is `old_id` UPDATEd. A carried `block_id` must
    be the OLD row's, because L3 and L4 rows from the head generation reference it, and this is
    the one and only `UPDATE` of a committed Block in the framework (03:310-315).

    `revision` is the RESULTING value (`old.revision + bump`), so a writer never has to decide
    whether `revision = revision + :bump` or a literal is the safe statement. `bump` is 0 for
    rule 1 and 1 for rule 2 with a changed digest -- 03:293 fixes the trigger as "same `addr`
    + `kind`, changed digest", so a rule-2 match whose digest is unchanged (which happens when
    rule 1 missed only because the block's parent has no head counterpart) carries with `bump` 0
    and is not counted as revised.
    """

    rule: Rule
    old_id: BlockId
    new_id: BlockId
    cite: Cite
    revision: int
    bump: int


@dataclass(frozen=True, slots=True)
class Create:
    """A staged row that matched nothing and therefore stays exactly as the parse wrote it.

    Rule 3's `cite` column reads "fresh `n` from `doc.next_cite_n`" (03:1260) and the mint has
    ALREADY happened: the parse wrote the staged generation with fresh ids and fresh cites before
    this pass runs (03:1262, and the worked example's created row is `block_id 47 / d7#17` at
    03:1352). So there is nothing for this decision to write, which is why `RebindWriteSide` has
    no `create` method. It exists as a decision because the count is reported, and because the
    cites of the carried rows' staged twins become permanent gaps in `next_cite_n`
    (03:1157-1159) -- a gap is correct, and this record is what says which numbers did not.
    """

    block_id: BlockId
    cite: Cite
    rule: Rule = Rule.FRESH
    revision: int = 0


@dataclass(frozen=True, slots=True)
class Retire:
    """A head row nothing matched: `state = 1` plus a `block_history` row (03:1260, 03:310).

    The five fields are `block_history`'s five columns (03:2382-2385 /
    `schema/migrations/0001_init.sql:332-336`). `superseded_by` is NULL when there is no
    defensible successor, which the DDL comment states in those words, and the successor rule is
    conservative on purpose: a retired cite that resolved to an unrelated neighbour is exactly
    what 03:1163 forbids ("never a silent miss and never a nearby block").
    `match_generations()` names a successor only when a rule-3 CREATED block of the SAME `kind`
    appears under the same carried parent -- the resegmentation signature of 03:1740, where "the
    inputs are retired through `block_history` with `reason='reparse_resegmented'` and
    `superseded_by` pointing at" the merged block. A plain deletion produces no created sibling
    and therefore no successor.

    `retired_gen` is `to_gen`, the generation the row was retired AT (glossary.md:242). The row's
    own `gen` does not move: retired ids stay at their old generation with `state = 1` (03:1276).
    """

    block_id: BlockId
    doc_ord: int
    retired_gen: int
    superseded_by: BlockId | None
    reason: str = REPARSE_RESEGMENTED


@dataclass(frozen=True, slots=True)
class RebindReport:
    """`rebind()`'s output. The field set is 03-document-model.md:1245-1250, verbatim and in order.

    Ten fields and no eleventh, which is why the document-wide rate the quarantine turns on is a
    METHOD (`match_rate()`) rather than a field: it is `carried / (carried + retired)`, derivable
    from the counters, and adding it as a field would put one quantity in two places.

    `quarantined` means "not committed" and nothing else. A run below `threshold` that was cleared
    by `--allow-unexplained-rebind` reports `quarantined = False`, because the generation IS the
    head afterwards; that it was unexplained stays visible as `match_rate() < threshold`, so no
    information is lost by not overloading the flag.
    """

    doc_ord: int
    from_gen: int
    to_gen: int
    carried: int
    revised: int
    created: int
    retired: int
    match_rate_by_page: Mapping[int, float]
    quarantined: bool
    threshold: float

    def match_rate(self) -> float:
        """The document-wide fraction of head blocks that matched: `carried / n_head`.

        `1.0` when the head generation has no rows at all, which is the first-ingest case the
        worked example calls "a no-op: `g_h = 0` has no rows, so `created = 10`" and then commits
        (03:1338-1339). A first ingest must not quarantine, and a zero denominator is the only
        way it could.
        """
        head = self.carried + self.retired
        return 1.0 if head == 0 else self.carried / head


@dataclass(frozen=True, slots=True)
class MatchPlan:
    """The full decision set, ordered and store-free. The half P10's golden differ re-uses.

    Three sequences, each in a deterministic order: `carries` and `creates` in the staged
    generation's traversal order (parents before children, then `ord`, then `block_id`), `retires`
    in the head generation's `(page, ord, block_id)` order. No set or dict iteration order reaches
    any of them -- 13-quality.md:840-843 makes this object a snapshot diff, and a diff whose row
    order moved between two runs over the same inputs would fail its own golden.
    """

    doc_ord: int
    from_gen: int
    to_gen: int
    carries: tuple[Carry, ...] = ()
    creates: tuple[Create, ...] = ()
    retires: tuple[Retire, ...] = ()
    match_rate_by_page: Mapping[int, float] = field(default_factory=lambda: MappingProxyType({}))

    def carried(self) -> int:
        """Every matched block, rule 1 and rule 2 together. See this module's reading 1."""
        return len(self.carries)

    def revised(self) -> int:
        """The carried subset whose `revision` moved -- rule 2 with a changed digest (03:293)."""
        return sum(1 for carry in self.carries if carry.bump)

    def created(self) -> int:
        return len(self.creates)

    def retired(self) -> int:
        return len(self.retires)

    def match_rate(self) -> float:
        """`carried / n_head`, or `1.0` on an empty head. `RebindReport.match_rate()`'s twin."""
        head = self.carried() + self.retired()
        return 1.0 if head == 0 else self.carried() / head

    def report(
        self, *, threshold: float = DEFAULT_THRESHOLD, allow_unexplained: bool = False
    ) -> RebindReport:
        """Project the plan onto the plan's ten-field report, deciding the quarantine.

        Strictly below, never at: "Below `threshold` the new generation is **quarantined**"
        (03:1300). A run exactly at the threshold commits.
        """
        if not 0.0 <= threshold <= 1.0:
            msg = f"threshold is a rate in [0.0, 1.0], got {threshold!r}"
            raise ValueError(msg)
        unexplained = self.match_rate() < threshold
        return RebindReport(
            doc_ord=self.doc_ord,
            from_gen=self.from_gen,
            to_gen=self.to_gen,
            carried=self.carried(),
            revised=self.revised(),
            created=self.created(),
            retired=self.retired(),
            match_rate_by_page=self.match_rate_by_page,
            quarantined=unexplained and not allow_unexplained,
            threshold=threshold,
        )


# ---------------------------------------------------------------------------
# The pure matcher. 03 section 6.5's three rules, and nothing else.
# ---------------------------------------------------------------------------


def match_generations(
    head: Sequence[BlockFacts],
    staged: Sequence[BlockFacts],
    *,
    doc_ord: int,
    from_gen: int,
    to_gen: int,
) -> MatchPlan:
    """Decide, for two generations of one document, what carries, what is fresh and what retires.

    Pure: no store, no SQL, no I/O, no clock. `head` is the committed generation `from_gen`
    (empty on a first ingest) and `staged` is the generation `to_gen` the parse has just written
    with fresh ids and fresh cites.

    **Order matters and is fixed.** Rule 1 is "equal `content_digest` under the same parent"
    (03:1257), and "the same parent" is the parent's CARRIED id (03:1287) -- so a block cannot be
    matched before its parent is, and the walk is top-down through the staged forest, siblings in
    `ord` order. Within rule 1, "a digest matching more than one candidate under the same parent
    is resolved by nearest `ord` and the loser falls through to rule 2" (03:1288). Rule 2 is one
    lookup on `block_addr(doc_ord, gen, addr)` (03:1289), which is `UNIQUE`, so it yields at most
    one candidate. Both probes are O(1) per block, which is what makes the pass affordable inside
    `end_doc()`; this implementation keeps that shape, with dicts standing in for the two indexes
    `block_cdig` and `block_addr` (03:2366-2367).

    Raises `ValueError` on input a committed generation cannot hold: a duplicate `block_id`, a
    duplicate `addr` within one generation (`block_addr` is UNIQUE), or a `parent` that names no
    block in its own generation. The matcher validates rather than coping, because each of those
    would silently change a decision -- a dangling parent, for instance, would make every rule-1
    candidate under it invisible and quietly retire a whole subtree.
    """
    head_rows = _validated(head, "head")
    staged_rows = _validated(staged, "staged")

    by_parent_digest: dict[tuple[BlockId | None, bytes], list[BlockFacts]] = {}
    by_addr: dict[Addr, BlockFacts] = {}
    for row in head_rows:
        by_parent_digest.setdefault((row.parent, row.content_digest), []).append(row)
        by_addr[row.addr] = row

    claimed: set[BlockId] = set()
    # staged block_id -> the head id it will wear after the pass, or None when it has no head
    # counterpart. A created block keeps its own staged id, which is a valid parent for its own
    # children but can never be a head row's `parent_id`, so rule 1 under it is unreachable.
    head_of: dict[BlockId, BlockId | None] = {}
    carries: list[Carry] = []
    creates: list[Create] = []

    for row in _top_down(staged_rows):
        match = _match_one(row, head_of, by_parent_digest, by_addr, claimed)
        if match is None:
            head_of[row.block_id] = None
            creates.append(Create(block_id=row.block_id, cite=row.cite))
            continue
        old, rule = match
        claimed.add(old.block_id)
        head_of[row.block_id] = old.block_id
        bump = 1 if rule is Rule.ADDR_KIND and old.content_digest != row.content_digest else 0
        carries.append(
            Carry(
                rule=rule,
                old_id=old.block_id,
                new_id=row.block_id,
                cite=old.cite,
                revision=old.revision + bump,
                bump=bump,
            )
        )

    retires = _retirements(head_rows, staged_rows, head_of, claimed, doc_ord=doc_ord, to_gen=to_gen)
    return MatchPlan(
        doc_ord=doc_ord,
        from_gen=from_gen,
        to_gen=to_gen,
        carries=tuple(carries),
        creates=tuple(creates),
        retires=retires,
        match_rate_by_page=_match_rate_by_page(head_rows, claimed),
    )


def _validated(rows: Iterable[BlockFacts], side: str) -> tuple[BlockFacts, ...]:
    """The three things a committed generation cannot hold. See `match_generations`'s docstring."""
    ordered = tuple(rows)
    seen_ids: set[BlockId] = set()
    seen_addrs: set[Addr] = set()
    for row in ordered:
        if row.block_id in seen_ids:
            msg = f"{side}: block_id {row.block_id} appears twice"
            raise ValueError(msg)
        if row.addr in seen_addrs:
            msg = f"{side}: addr {row.addr!r} appears twice; block_addr is UNIQUE per generation"
            raise ValueError(msg)
        seen_ids.add(row.block_id)
        seen_addrs.add(row.addr)
    for row in ordered:
        if row.parent is not None and row.parent not in seen_ids:
            msg = f"{side}: block {row.block_id} names parent {row.parent}, which is not in it"
            raise ValueError(msg)
    return ordered


def _top_down(rows: Sequence[BlockFacts]) -> list[BlockFacts]:
    """The staged forest, parents before children, siblings by `(ord, block_id)`.

    A pre-order walk from the parentless rows -- `parent` is NULL exactly on the one
    `Kind.DOCUMENT` root per `(doc_ord, gen)` (03:283), but nothing here requires exactly one,
    because the golden differ may hand the matcher a subtree. `_validated` has already proved
    every `parent` resolves, so the walk reaches every row and cannot loop: an id cycle would
    leave those rows unreached, and the length check below turns that into an error rather than a
    silently short plan. A stack rather than `list.pop(0)`, because a 600k-block generation
    (`MAX_BLOCKS_PER_DOC`) makes the difference between O(n) and O(n^2).
    """
    children: dict[BlockId | None, list[BlockFacts]] = {}
    for row in rows:
        children.setdefault(row.parent, []).append(row)
    for siblings in children.values():
        siblings.sort(key=lambda row: (row.ord, row.block_id))

    walk: list[BlockFacts] = []
    stack = list(reversed(children.get(None, ())))
    while stack:
        row = stack.pop()
        walk.append(row)
        stack.extend(reversed(children.get(row.block_id, ())))
    if len(walk) != len(rows):
        msg = f"the containment spine is not a forest: {len(rows) - len(walk)} rows unreachable"
        raise ValueError(msg)
    return walk


def _match_one(
    row: BlockFacts,
    head_of: Mapping[BlockId, BlockId | None],
    by_parent_digest: Mapping[tuple[BlockId | None, bytes], Sequence[BlockFacts]],
    by_addr: Mapping[Addr, BlockFacts],
    claimed: set[BlockId],
) -> tuple[BlockFacts, Rule] | None:
    """Rule 1, then rule 2, then neither. 03-document-model.md:1256-1260 and :1286-1290."""
    if row.parent is None:
        parent_key: BlockId | None = None
        parent_known = True
    else:
        parent_key = head_of[row.parent]
        parent_known = parent_key is not None

    if parent_known:
        candidates = [
            candidate
            for candidate in by_parent_digest.get((parent_key, row.content_digest), ())
            if candidate.block_id not in claimed
        ]
        if candidates:
            nearest = min(
                candidates,
                key=lambda candidate: (
                    abs(candidate.ord - row.ord),
                    candidate.ord,
                    candidate.block_id,
                ),
            )
            return nearest, Rule.DIGEST

    by_position = by_addr.get(row.addr)
    if by_position is not None and by_position.kind == row.kind:
        if by_position.block_id in claimed:
            return None
        return by_position, Rule.ADDR_KIND
    return None


def _retirements(
    head_rows: Sequence[BlockFacts],
    staged_rows: Sequence[BlockFacts],
    head_of: Mapping[BlockId, BlockId | None],
    claimed: set[BlockId],
    *,
    doc_ord: int,
    to_gen: int,
) -> tuple[Retire, ...]:
    """Every unclaimed head row, in `(page, ord, block_id)` order, with its successor decided.

    The successor rule is `Retire`'s docstring: a created block of the same `kind` under the same
    carried parent, nearest `ord`, else NULL. Nearest-`ord` ties break on `ord` then `block_id`,
    so two head rows merged into one created block both name it and the order of the head input
    cannot change the answer.
    """
    created_by_parent: dict[BlockId | None, list[BlockFacts]] = {}
    for row in staged_rows:
        if head_of.get(row.block_id) is not None:
            continue  # carried: it wears an old id and is not anybody's successor
        if row.parent is None:
            created_by_parent.setdefault(None, []).append(row)
            continue
        under = head_of[row.parent]
        if under is None:
            continue  # its own parent has no head counterpart, so no head row is its sibling
        created_by_parent.setdefault(under, []).append(row)

    retires: list[Retire] = []
    for row in sorted(head_rows, key=lambda r: (r.page, r.ord, r.block_id)):
        if row.block_id in claimed:
            continue
        successors = [
            candidate
            for candidate in created_by_parent.get(row.parent, ())
            if candidate.kind == row.kind
        ]
        successor = (
            min(
                successors,
                key=lambda candidate: (
                    abs(candidate.ord - row.ord),
                    candidate.ord,
                    candidate.block_id,
                ),
            ).block_id
            if successors
            else None
        )
        retires.append(
            Retire(
                block_id=row.block_id,
                doc_ord=doc_ord,
                retired_gen=to_gen,
                superseded_by=successor,
            )
        )
    return tuple(retires)


def _match_rate_by_page(
    head_rows: Sequence[BlockFacts], claimed: set[BlockId]
) -> Mapping[int, float]:
    """Matched head blocks over head blocks, per page, excluding the parentless root.

    Reading 2 of the module docstring: head-side because of 03:1364, root-excluded because of
    03:1367. A page with no non-root head block has no key -- an absent rate is not `0.0`, and
    03:2686-2695's quarantine must not be triggered by a page that had nothing to match.
    """
    totals: dict[int, int] = {}
    matched: dict[int, int] = {}
    for row in head_rows:
        if row.parent is None:
            continue
        totals[row.page] = totals.get(row.page, 0) + 1
        if row.block_id in claimed:
            matched[row.page] = matched.get(row.page, 0) + 1
    return MappingProxyType(
        {page: matched.get(page, 0) / total for page, total in sorted(totals.items())}
    )


def follow_supersession(
    retires: Iterable[Retire], block_id: BlockId, *, live: Iterable[BlockId] = ()
) -> BlockId | None:
    """Resolve a retired `block_id` to the live block that superseded it, or `None`.

    "**A retired cite still resolves.** `ow open --by-cite` follows `block_history.superseded_by`
    and says so in the response. Where `superseded_by IS NULL` the answer is a stated refusal,
    `OW-M-030 / OW_CITE_RETIRED`" (03:1159-1163). This function is the hop-following half; the
    refusal is the surface's, because only the surface can name the generation and the reason in
    the response, and `None` here is exactly the `superseded_by IS NULL` case.

    A chain of two retirements resolves to the live block rather than to the intermediate one --
    a re-parse can retire a block that was itself a successor -- and a cycle terminates instead of
    looping: `block_history` is written by this pass and a cycle would be corruption, so it is
    reported as one rather than hung on. `live` is optional and is a cross-check, not the source
    of truth: when given, a successor that is neither live nor itself retired raises.
    """
    by_id = {row.block_id: row for row in retires}
    live_ids = frozenset(live)
    seen: set[BlockId] = set()
    current = block_id
    while current in by_id:
        if current in seen:
            msg = f"block_history supersession cycle through block {current}"
            raise ValueError(msg)
        seen.add(current)
        successor = by_id[current].superseded_by
        if successor is None:
            return None
        if live_ids and successor not in live_ids and successor not in by_id:
            msg = f"block {current} is superseded by {successor}, which is neither live nor retired"
            raise ValueError(msg)
        current = successor
    return current


# ---------------------------------------------------------------------------
# The thin half: two structural protocols and the pass itself.
# ---------------------------------------------------------------------------


class RebindReadSide(Protocol):
    """What `rebind()` reads. The smallest slice of the store the pass needs.

    Structural, and deliberately not `omniweave_core.store.Reader` (07:57-70): that Protocol is
    the RETRIEVAL boundary and its six methods are frozen, `model` may not import `store` at all,
    and a T3 Postgres backend has to be able to satisfy this without either side knowing about the
    other. `blocks_at_gen` returns `BlockFacts`, not `Block`, so a backend can answer it with one
    projection over `block_addr`/`block_cdig` rather than hydrating marks it will not read.
    """

    def doc_generation(self, doc_ord: int) -> int:
        """`doc.gen` -- the head generation. `0` for a document whose first parse is staged."""
        ...

    def blocks_at_gen(self, doc_ord: int, gen: int) -> Sequence[BlockFacts]:
        """Every non-retired block of one generation, staged generations included.

        NOT through `ow_block_head` (03:2378): the staged generation is invisible to that view by
        design, and this pass is the one caller that must see both.
        """
        ...


class RebindWriteSide(Protocol):
    """What `rebind()` writes. Three methods, each one transaction step inside `end_doc()`.

    There is no `create`: a rule-3 block is already durable, written by the parse with its own
    fresh id and cite, so committing the generation is the whole of its write (see `Create`).
    """

    def carry_forward(self, carry: Carry) -> None:
        """DELETE the staged row, then UPDATE the durable row forward. `Carry` says why in order."""
        ...

    def retire(self, retirement: Retire) -> None:
        """`state = 1` on the head row plus one `block_history` row. Never a DELETE (03:310)."""
        ...

    def commit_generation(self, doc_ord: int, gen: int) -> None:
        """`UPDATE doc SET gen = :gen` -- the single statement that makes a generation visible."""
        ...


class RebindStore(RebindReadSide, RebindWriteSide, Protocol):
    """Both sides. `rebind`'s `store` parameter, which the plan prints unannotated (03:1252)."""


def rebind(
    store: RebindStore,
    doc_ord: int,
    to_gen: int,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    allow_unexplained: bool = False,
) -> RebindReport:
    """Re-parse identity, as an explicit pass. 03-document-model.md:1252, section 6.5.

    Runs inside `end_doc()`'s single transaction and AFTER the closure pass, because a
    `content_digest` read from an uncommitted generation is not final until the cross-page
    containers have been closed (03:1230-1234). Nothing here opens a transaction: the caller owns
    it, so a crash mid-pass leaves the generation staged and the previous head answering
    (03:2688).

    Application order is carries, then retirements, then the `doc.gen` bump. The bump is last
    because it is the commit: until it runs, every decision above it is invisible to a reader
    going through `ow_block_head`.

    On a quarantine NOTHING is applied -- not the carries, not the retirements, not the bump --
    and the report says so. The staged rows stay durable and invisible for `ow doc diff`
    (03:2686-2695). `allow_unexplained` is `--allow-unexplained-rebind` and is the ONLY way past
    it other than a re-parse; there is no `--force` anywhere in the framework (03:1302).

    `threshold` and `allow_unexplained` are keyword-only, so this call cannot acquire an override
    by positional accident -- which is the shape 01-principles.md's named-override rule asks for.
    """
    from_gen = store.doc_generation(doc_ord)
    if to_gen <= from_gen:
        msg = f"to_gen {to_gen} must be ahead of the head generation {from_gen}"
        raise ValueError(msg)
    plan = match_generations(
        store.blocks_at_gen(doc_ord, from_gen),
        store.blocks_at_gen(doc_ord, to_gen),
        doc_ord=doc_ord,
        from_gen=from_gen,
        to_gen=to_gen,
    )
    report = plan.report(threshold=threshold, allow_unexplained=allow_unexplained)
    if report.quarantined:
        return report
    for carry in plan.carries:
        store.carry_forward(carry)
    for retirement in plan.retires:
        store.retire(retirement)
    store.commit_generation(doc_ord, to_gen)
    return report
