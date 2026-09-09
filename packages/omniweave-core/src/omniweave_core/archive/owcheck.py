"""`owcheck` -- the structural invariants of one generation, as a report rather than an exception.

`owcheck`'s clause list is fixed by glossary.md:855: "the parent/`ord` bijection, grid
exactly-once, `rel` referential integrity, and the verbatim-implies-retained-part rule". Two more
clauses are named elsewhere in the same document and are here for the same reason: 03:2233 makes
`owcheck` assert acyclicity over `rel(continues)`, and 03:1027 makes it re-assert M-INV-5 (layer
inheritance) "over the whole generation". Six clauses, each with one definition site.

**It returns a report and does not raise per violation**, and that is 03:1027's word
"re-asserts" taken seriously in two places. 03:65-70 makes `owcheck` step 2 of `end_doc()`, which
runs inside the final transaction of a parse that may already be `status = partial`; and 03:3222
makes `OW_INTEGRITY_UNCHECKED` a `Diag` rather than a crash, because a diagnostic is a FIELD and
not an exception (the `CREATE TABLE diag` comment in the store's `0001_init.sql`). A
validator that raised on the first violation would report one problem out of forty and would make
a quarantined generation uninspectable, which is the opposite of what `ow doc diff` needs
(03:2694).

**A clause can be UNCHECKED, and that is a third state and not a pass.** The
verbatim-implies-retained-part clause needs to know which parts were retained; over an archive
whose `parts[]` is absent it cannot know, and answering "passed" would turn Q-G6 -- a HARD gate
at `span_exact_rate == 1.000` (01:327, V01-5) -- into a rubber stamp. `ClauseState.UNCHECKED`
carries `OW_INTEGRITY_UNCHECKED`, which is exactly the code 07:2584 and 07:3193 use for "the
bytes that would settle this are not readable".

**On the error codes.** `codes.toml` is append-only and this wave does not own it. It carries no
row for `OW_INTEGRITY_UNCHECKED` even though 03:3222 says it does, and none for
`OW_LAYER_NOT_INHERITED`; the four remaining clauses have no symbol allocated anywhere in the
plan. So a violation carries the symbol the plan names where it names one and the M-area default
`OW_MODEL` where it does not, and `Violation.clause` is always the discriminator a caller
branches on. `OwError.numeric()` degrades to `""` for a symbol with no register row, which
errors.py documents as designed. The rows are owed to W1.3. Reported.

Specified in 03-document-model.md sections 1.1, 12.3 and 12.4, glossary.md:855, 01-principles.md
section on verbatimness (:327) and 00-vision.md:706 (V01-5).

Stdlib only (INV-2). No `sqlite3` (INV-17): every clause runs over rows a caller already has, so
`owcheck` works identically against a store and against an archive -- which is the property that
lets `end_doc()` and `ow doc verify <archive>` share one implementation.

Tier T-SCHEMA: 02-architecture.md section 2 row 25.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

from omniweave_core.archive.owdoc import ROOT_ADDR, GridRow, OwdocReader, parent_addr
from omniweave_core.errors import ModelError
from omniweave_core.model import (
    Addr,
    Kind,
    Layer,
    OriginBytes,
    OriginGlyphs,
    OriginNodePath,
    OriginSpan,
    Quote,
    RelKind,
)

__all__ = [
    "BlockFacts",
    "Clause",
    "ClauseResult",
    "ClauseState",
    "Generation",
    "OwcheckReport",
    "Violation",
    "block_facts",
    "owcheck",
    "owcheck_archive",
]

_INTEGRITY: Final = "OW_INTEGRITY_UNCHECKED"
_LAYER: Final = "OW_LAYER_NOT_INHERITED"
_MODEL: Final = "OW_MODEL"


class Clause(StrEnum):
    """The six invariants, one member per definition site. Closed and append-only.

    Spelled as a `StrEnum` for the same reason the fifteen closed domains of 03 section 2.1 are:
    a report is serialised into a `diag.detail` JSON object and read back by `ow doc verify`, and
    a clause name that is a bare string in one place and an enum in another drifts.
    """

    PARENT_ORD_BIJECTION = "parent_ord_bijection"
    GRID_EXACTLY_ONCE = "grid_exactly_once"
    REL_REFERENTIAL = "rel_referential"
    VERBATIM_RETAINED_PART = "verbatim_retained_part"
    CONTINUES_ACYCLIC = "continues_acyclic"
    LAYER_INHERITED = "layer_inherited"


class ClauseState(StrEnum):
    """`passed`, `failed` or `unchecked`. Three states, and the third is the interesting one."""

    PASSED = "passed"
    FAILED = "failed"
    UNCHECKED = "unchecked"


@dataclass(frozen=True, slots=True)
class Violation:
    """One failure. `addr` is the address it is about; there is never a `block_id` (INV-8)."""

    clause: Clause
    code: str
    addr: str
    detail: str


@dataclass(frozen=True, slots=True)
class ClauseResult:
    """One clause's verdict, plus how many subjects it actually looked at.

    `checked` is not decoration: a clause that passed over zero subjects and a clause that
    passed over 600,000 are different facts, and `ow doc verify`'s output is unreadable without
    the second number. It is also what makes a silently-empty input visible.
    """

    clause: Clause
    state: ClauseState
    checked: int
    violations: tuple[Violation, ...] = ()
    reason: str = ""


@dataclass(frozen=True, slots=True)
class BlockFacts:
    """The seven facts the six clauses need. Deliberately not a `Block`.

    A `Block` carries thirty-two fields and a `BlockId`; every clause here is about position,
    containment and provenance, so passing the whole node would make the checker's input surface
    thirty-two fields wide and its `block_id`-freedom accidental rather than structural. This
    shape is also what lets one implementation run over a store cursor and over an archive
    frame: `block_facts()` builds it from a decoded wire record, and the store wave builds it
    from a row.
    """

    addr: Addr
    page: int
    ord: int
    kind: Kind
    layer: Layer
    quote: Quote
    origin_part: str | None


@dataclass(frozen=True, slots=True)
class Generation:
    """One generation as `owcheck` sees it.

    `retained_parts` is the set of `part.path` values whose `store_ref` is NOT NULL -- the
    "NULL => bytes were not retained" of the `part` DDL, which is the retention policy INV-10's
    verbatim branch reads. `parts_known` is False when the caller could not enumerate them at
    all, which makes the verbatim clause UNCHECKED rather than passed.
    """

    blocks: Sequence[BlockFacts]
    rels: Sequence[tuple[Addr, Addr, RelKind]] = ()
    grids: Sequence[GridRow] = ()
    retained_parts: frozenset[str] = frozenset()
    parts_known: bool = True
    x: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OwcheckReport:
    """Every clause's result. `ok` is true only when no clause FAILED.

    An UNCHECKED clause does not make `ok` false -- it makes `complete` false. Conflating the
    two is how a gate becomes a rubber stamp in one direction or unusable in the other: an
    archive exported without its parts is legitimately unverifiable on the verbatim clause and
    must still be importable, while a generation whose parent/`ord` bijection is broken must
    never commit.
    """

    clauses: tuple[ClauseResult, ...]

    @property
    def ok(self) -> bool:
        return all(c.state is not ClauseState.FAILED for c in self.clauses)

    @property
    def complete(self) -> bool:
        return all(c.state is ClauseState.PASSED for c in self.clauses)

    @property
    def violations(self) -> tuple[Violation, ...]:
        return tuple(v for clause in self.clauses for v in clause.violations)

    def by_clause(self, clause: Clause) -> ClauseResult:
        for result in self.clauses:
            if result.clause is clause:
                return result
        msg = f"no result for clause {clause!r}"
        raise KeyError(msg)

    def diag_rows(self, *, doc_ord: int, gen: int) -> tuple[dict[str, Any], ...]:
        """The report as `diag` rows, ready for `DocSink.diag()`. One row per violation.

        Column for column with `CREATE TABLE diag` in the store's `0001_init.sql`:
        `block_id` is deliberately absent (it is not an FK there, and an archive has no
        `block_id` at all), the addr goes into `detail`, `component` is this module, and `fatal`
        is 0 -- `owcheck` records, `end_doc()` decides. An UNCHECKED clause also emits a row, so
        that "nobody checked" is in the same table as "checked and wrong" and gate 9's
        `diag_code` index finds both.
        """
        rows: list[dict[str, Any]] = []
        for result in self.clauses:
            for violation in result.violations:
                rows.append(_diag_row(doc_ord, gen, violation.code, violation, result))
            if result.state is ClauseState.UNCHECKED:
                rows.append(
                    {
                        "doc_ord": doc_ord,
                        "gen": gen,
                        "page": None,
                        "part": None,
                        "code": _INTEGRITY,
                        "severity": "warning",
                        "component": "omniweave_core.archive.owcheck",
                        "message": f"clause {result.clause.value} was not checked",
                        "detail": {"clause": result.clause.value, "reason": result.reason},
                        "fatal": 0,
                    }
                )
        return tuple(rows)


def _diag_row(
    doc_ord: int, gen: int, code: str, violation: Violation, result: ClauseResult
) -> dict[str, Any]:
    return {
        "doc_ord": doc_ord,
        "gen": gen,
        "page": None,
        "part": None,
        "code": code,
        "severity": "error",
        "component": "omniweave_core.archive.owcheck",
        "message": violation.detail,
        "detail": {"clause": result.clause.value, "addr": violation.addr},
        "fatal": 0,
    }


def origin_part(origin: OriginSpan) -> str | None:
    """The part an `OriginSpan` names, or `None` for `pixels` and `none`.

    Those two "can NEVER reach verbatim: there is nothing to re-read" (the `part` DDL's INV-10
    comment), so `None` here is not missing data -- it is the fact the verbatim clause turns on.
    """
    if isinstance(origin, (OriginBytes, OriginNodePath, OriginGlyphs)):
        return origin.part
    return None


def block_facts(row: Any) -> BlockFacts:
    """`BlockFacts` from a `BlockImport` (what `OwdocReader.blocks()` yields).

    Typed `Any` because `BlockImport` and `Block` are two different shapes carrying the same
    seven facts and this function is the one adapter; the store wave's row is a third.
    """
    draft = row.draft
    return BlockFacts(
        addr=row.addr,
        page=row.page,
        ord=row.ord,
        kind=draft.kind,
        layer=draft.layer,
        quote=draft.quote,
        origin_part=origin_part(draft.origin),
    )


def owcheck(generation: Generation) -> OwcheckReport:
    """Run all six clauses. Never raises for a violation; see the module docstring."""
    by_addr = {str(b.addr): b for b in generation.blocks}
    return OwcheckReport(
        clauses=(
            _parent_ord_bijection(generation.blocks, by_addr),
            _grid_exactly_once(generation.grids),
            _rel_referential(generation.rels, by_addr),
            _verbatim_retained_part(generation),
            _continues_acyclic(generation.rels),
            _layer_inherited(generation.blocks, by_addr),
        )
    )


def owcheck_archive(reader: OwdocReader) -> OwcheckReport:
    """Run `owcheck` over an `.owdoc`, reading the same block stream `import_` reads.

    `retained_parts` comes from `manifest.parts[]`, where `present` is the archive's spelling of
    `store_ref IS NOT NULL` (03:2488). An archive with no `parts[]` at all leaves the verbatim
    clause UNCHECKED, because "no parts listed" and "no part retained" are different facts and
    only the second one is a violation.
    """
    blocks = [block_facts(row) for row in reader.blocks()]
    rels = [(r.src, r.dst, r.kind) for r in reader.rels()]
    parts = reader.manifest.parts
    retained = frozenset(str(p["path"]) for p in parts if p.get("present"))
    return owcheck(
        Generation(
            blocks=blocks,
            rels=rels,
            grids=tuple(reader.grids()),
            retained_parts=retained,
            parts_known=bool(parts),
        )
    )


# ---------------------------------------------------------------------------
# Clause 1 -- the parent / `ord` bijection. glossary.md:855, 03 section 6.2 rule 3.
# ---------------------------------------------------------------------------


def _parent_ord_bijection(
    blocks: Sequence[BlockFacts], by_addr: Mapping[str, BlockFacts]
) -> ClauseResult:
    """Exactly one root; every parent present; and every sibling set's `ord`s are `0..n-1`.

    The bijection is the second half and it is the half a store cannot express as a constraint:
    `block_sib` is a UNIQUE index, which forbids two siblings sharing an `ord` but permits the
    set `{0, 1, 3}`. Density from 0 is P3's rule for every block, including a `table_cell`, whose
    `ord` `DocSink` assigns in row-major origin order even though its ADDRESS step is `r<r>c<c>`
    (03:1121-1126). A gap means a block was dropped between minting and commit, and every
    consumer that walks children by index then silently stops early.
    """
    violations: list[Violation] = []
    children: dict[str | None, list[BlockFacts]] = {}
    roots = 0
    for block in blocks:
        addr = str(block.addr)
        try:
            parent = parent_addr(addr)
        except ModelError:
            # A malformed addr is a VIOLATION to report, not an exception to propagate: an
            # archive is untrusted input and this function is the thing that says so.
            violations.append(
                Violation(
                    Clause.PARENT_ORD_BIJECTION,
                    _MODEL,
                    addr,
                    f"addr {addr!r} does not parse under the section 6.2 grammar",
                )
            )
            continue
        if parent is None:
            roots += 1
            if addr != ROOT_ADDR:
                violations.append(
                    Violation(
                        Clause.PARENT_ORD_BIJECTION,
                        _MODEL,
                        addr,
                        "a parentless block whose addr is not the literal 'doc' (03:1093)",
                    )
                )
        elif str(parent) not in by_addr:
            violations.append(
                Violation(
                    Clause.PARENT_ORD_BIJECTION,
                    _MODEL,
                    addr,
                    f"parent {parent} is not a block of this generation",
                )
            )
        children.setdefault(None if parent is None else str(parent), []).append(block)
    if roots != 1 and blocks:
        violations.append(
            Violation(
                Clause.PARENT_ORD_BIJECTION,
                _MODEL,
                str(ROOT_ADDR),
                f"a generation has exactly one `document` root, found {roots} (03:1093)",
            )
        )
    for parent, siblings in children.items():
        ords = sorted(b.ord for b in siblings)
        if ords != list(range(len(ords))):
            violations.append(
                Violation(
                    Clause.PARENT_ORD_BIJECTION,
                    _MODEL,
                    parent or str(ROOT_ADDR),
                    f"sibling ords {ords} are not dense from 0 (P3); {len(ords)} children",
                )
            )
    return _result(Clause.PARENT_ORD_BIJECTION, len(blocks), violations)


# ---------------------------------------------------------------------------
# Clause 2 -- grid exactly-once. glossary.md:855, 03 section 10.1.
# ---------------------------------------------------------------------------


def _grid_exactly_once(grids: Sequence[GridRow]) -> ClauseResult:
    """Every `(r, c)` inside the declared shape is covered by exactly one origin cell.

    "Exactly once" is two failures in one clause and they must be reported separately: a slot
    claimed TWICE means two cells overlap and `slot(r, c)` has two answers, while a slot claimed
    ZERO times means a hole, and a consumer reading a row by index gets the next row's value.
    `grid_slot` is the materialised form of this map and is `[DER]` (03:2467), which is exactly
    why the property has to be checked against the ORIGIN cells rather than against the
    materialisation -- a rebuild of a wrong cover map produces a consistent wrong cover map.

    Raggedness is explicit: `row_len` is a per-row length (the `table_meta` DDL says "rows may
    be RAGGED"), so the shape is the union of `r x row_len[r]` and not `n_rows x n_cols`.
    """
    violations: list[Violation] = []
    checked = 0
    for grid in grids:
        table = str(grid.table)
        row_len = _row_lengths(grid)
        claims: dict[tuple[int, int], int] = {}
        for r, c, row_span, col_span in grid.cells:
            for dr in range(max(row_span, 1)):
                for dc in range(max(col_span, 1)):
                    claims[(r + dr, c + dc)] = claims.get((r + dr, c + dc), 0) + 1
        for slot, count in sorted(claims.items()):
            if count > 1:
                violations.append(
                    Violation(
                        Clause.GRID_EXACTLY_ONCE,
                        _MODEL,
                        f"{table}/r{slot[0]}c{slot[1]}",
                        f"slot ({slot[0]}, {slot[1]}) is claimed {count} times",
                    )
                )
        for r, length in enumerate(row_len):
            for c in range(length):
                checked += 1
                if (r, c) not in claims:
                    violations.append(
                        Violation(
                            Clause.GRID_EXACTLY_ONCE,
                            _MODEL,
                            f"{table}/r{r}c{c}",
                            f"slot ({r}, {c}) is covered by no origin cell",
                        )
                    )
        for slot in sorted(claims):
            if slot[0] >= len(row_len) or slot[1] >= row_len[slot[0]]:
                violations.append(
                    Violation(
                        Clause.GRID_EXACTLY_ONCE,
                        _MODEL,
                        f"{table}/r{slot[0]}c{slot[1]}",
                        f"slot ({slot[0]}, {slot[1]}) is outside the declared shape",
                    )
                )
    return _result(Clause.GRID_EXACTLY_ONCE, checked, violations)


def _row_lengths(grid: GridRow) -> tuple[int, ...]:
    if grid.row_len:
        return grid.row_len
    return tuple(grid.n_cols for _ in range(grid.n_rows))


# ---------------------------------------------------------------------------
# Clause 3 -- `rel` referential integrity. glossary.md:855.
# ---------------------------------------------------------------------------


def _rel_referential(
    rels: Sequence[tuple[Addr, Addr, RelKind]], by_addr: Mapping[str, BlockFacts]
) -> ClauseResult:
    """Both endpoints of every `rel` are blocks of this generation, and no `rel` is a self-loop.

    In the store this is an FK to `block(block_id)` and the schema enforces it. In an ARCHIVE it
    cannot be: an endpoint is an `addr`, and `addr` is never a foreign-key target (INV-1,
    charter section 5 X40) precisely because it is positional and generation-keyed. So the check
    that the DDL performs on one side of the round trip has to be performed by code on the
    other, and that asymmetry is the reason this clause exists at all.

    A self-loop is refused here rather than under the acyclicity clause because `rel` is a DAG
    for all seven kinds (the `CREATE TABLE rel` comment) and not only for `continues`.
    """
    violations: list[Violation] = []
    for src, dst, kind in rels:
        for role, endpoint in (("src", src), ("dst", dst)):
            if str(endpoint) not in by_addr:
                violations.append(
                    Violation(
                        Clause.REL_REFERENTIAL,
                        _MODEL,
                        str(endpoint),
                        f"rel({kind.value}) {role} {endpoint} is not a block of this generation",
                    )
                )
        if str(src) == str(dst):
            violations.append(
                Violation(
                    Clause.REL_REFERENTIAL,
                    _MODEL,
                    str(src),
                    f"rel({kind.value}) is a self-loop; rel is a DAG",
                )
            )
    return _result(Clause.REL_REFERENTIAL, len(rels), violations)


# ---------------------------------------------------------------------------
# Clause 4 -- verbatim implies a retained part. 01-principles.md:327, V01-5, INV-10.
# ---------------------------------------------------------------------------


def _verbatim_retained_part(generation: Generation) -> ClauseResult:
    """`quote == VERBATIM` requires an `os_kind` with a part AND that part retained.

    This is the clause `Q-G6` rests on. 01:327 gates `span_exact_rate` at **1.000** on a
    deterministic sample of n = 1000 blocks, "as a hard gate and not a metric", and V01-5 states
    the other half: "zero Blocks claim `verbatim` without a non-NULL `part.store_ref`". A
    verbatim claim is a promise that the text can be re-derived from retained bytes by one of
    INV-10's three re-verifiable branches, so a claim whose bytes are gone is not a weaker claim,
    it is an unfalsifiable one -- and `Quote` is an ordered `IntEnum` with `SYNTHETIC = 0` so
    that `min()` over a Segment returns the WEAKEST member, which is the bug this clause's
    existence pays for (01:329-334).

    `pixels` and `none` can never reach verbatim: there is nothing to re-read (the `part` DDL).

    UNCHECKED when the caller could not enumerate the retained parts. That is not a pass: see
    the module docstring.
    """
    verbatim = [b for b in generation.blocks if b.quote is Quote.VERBATIM]
    if not generation.parts_known:
        return ClauseResult(
            clause=Clause.VERBATIM_RETAINED_PART,
            state=ClauseState.UNCHECKED,
            checked=0,
            reason=(
                f"{len(verbatim)} blocks claim VERBATIM and this subject lists no parts, so "
                f"retention cannot be established"
            ),
        )
    violations: list[Violation] = []
    for block in verbatim:
        if block.origin_part is None:
            violations.append(
                Violation(
                    Clause.VERBATIM_RETAINED_PART,
                    _INTEGRITY,
                    str(block.addr),
                    "claims VERBATIM with an os_kind that names no part (pixels/none)",
                )
            )
        elif block.origin_part not in generation.retained_parts:
            violations.append(
                Violation(
                    Clause.VERBATIM_RETAINED_PART,
                    _INTEGRITY,
                    str(block.addr),
                    f"claims VERBATIM against part {block.origin_part!r}, whose bytes were "
                    f"not retained (store_ref IS NULL)",
                )
            )
    return _result(Clause.VERBATIM_RETAINED_PART, len(verbatim), violations)


# ---------------------------------------------------------------------------
# Clause 5 -- `rel(continues)` is acyclic. 03-document-model.md:2233.
# ---------------------------------------------------------------------------


def _continues_acyclic(rels: Sequence[tuple[Addr, Addr, RelKind]]) -> ClauseResult:
    """ "A `continues` chain is a path, never a cycle" (03:2233).

    `continues` is the one intra-document relation that means "these are one logical unit split
    into two blocks" (03:2237), and the serializer JOINS across it when rendering body text
    (section 16.1). A cycle therefore does not produce a wrong reading order -- it produces a
    serializer that does not terminate.

    Iterative depth-first search with three colours, not recursion: a paragraph broken across
    600 columns is a legal 600-long chain, and CPython's default recursion limit is 1,000.
    """
    edges: dict[str, list[str]] = {}
    for src, dst, kind in rels:
        if kind is RelKind.CONTINUES:
            edges.setdefault(str(src), []).append(str(dst))
    violations: list[Violation] = []
    seen: set[str] = set()
    for start in sorted(edges):
        if start in seen:
            continue
        cycle = _find_cycle(start, edges, seen)
        if cycle is not None:
            violations.append(
                Violation(
                    Clause.CONTINUES_ACYCLIC,
                    _MODEL,
                    cycle,
                    f"rel(continues) has a cycle reachable from {start}, through {cycle}",
                )
            )
    return _result(Clause.CONTINUES_ACYCLIC, sum(len(v) for v in edges.values()), violations)


def _find_cycle(start: str, edges: Mapping[str, Sequence[str]], seen: set[str]) -> str | None:
    """The first node on a cycle reachable from `start`, or `None`. Grey/black by explicit stack."""
    on_stack: set[str] = set()
    stack: list[tuple[str, Iterable[str]]] = [(start, iter(edges.get(start, ())))]
    on_stack.add(start)
    seen.add(start)
    while stack:
        node, children = stack[-1]
        advanced = False
        for child in children:
            if child in on_stack:
                return child
            if child not in seen:
                seen.add(child)
                on_stack.add(child)
                stack.append((child, iter(edges.get(child, ()))))
                advanced = True
                break
        if not advanced:
            on_stack.discard(node)
            stack.pop()
    return None


# ---------------------------------------------------------------------------
# Clause 6 -- M-INV-5, layer inheritance. 03-document-model.md:1021-1027.
# ---------------------------------------------------------------------------

_PAGE_ROOT_DEFAULT: Final = {
    Kind.PAGE_HEADER: Layer.FURNITURE,
    Kind.PAGE_FOOTER: Layer.FURNITURE,
    Kind.FOOTNOTE: Layer.NOTE,
    Kind.ENDNOTE: Layer.NOTE,
    Kind.SPEAKER_NOTE: Layer.NOTE,
    Kind.COMMENT: Layer.ANNOTATION,
}
"""`DocSink`'s page-root layer defaults, transcribed from 03-document-model.md:1023-1025.

Not used to CHECK a page root -- a page root's layer is the driver's to state, and a driver may
legitimately put a `paragraph` page root in `Layer.HIDDEN`. It is here because the mapping is
what makes the clause below only about non-page-roots, and a reader of this file would otherwise
have to go and find out why.
"""


def _layer_inherited(
    blocks: Sequence[BlockFacts], by_addr: Mapping[str, BlockFacts]
) -> ClauseResult:
    """A non-page-root block's `layer` equals its parent's. M-INV-5, re-asserted (03:1027).

    `add_block` refuses a violating draft with `OW_LAYER_NOT_INHERITED`, and this clause is the
    generation-wide re-assertion the same paragraph calls for. It is not tidiness: without
    inheritance, `serialize(layers={BODY})` has to decide what to do with a `body` paragraph
    inside an `annotation` comment -- render it, leaking a review comment into body text, or drop
    it, making the layer filter a subtree walk that costs an ancestor query per block. With
    inheritance the filter is a pure per-block predicate on an indexed column (03:1029-1033).

    A PAGE ROOT is exempt, which is the invariant's own carve-out: its parent is the `document`
    root, whose layer is not a fact about any page.
    """
    violations: list[Violation] = []
    checked = 0
    for block in blocks:
        addr = str(block.addr)
        if addr == ROOT_ADDR:
            continue
        try:
            parent = parent_addr(addr)
        except ModelError:
            # A malformed addr is clause 1's finding, and reporting it twice would double-count
            # one defect across two clauses. Skipping here keeps each violation in one place.
            continue
        if parent is None or str(parent) == ROOT_ADDR:
            continue
        owner = by_addr.get(str(parent))
        if owner is None:
            continue
        checked += 1
        if owner.layer is not block.layer:
            violations.append(
                Violation(
                    Clause.LAYER_INHERITED,
                    _LAYER,
                    addr,
                    f"layer {block.layer.value} differs from parent {parent}'s "
                    f"{owner.layer.value} (M-INV-5)",
                )
            )
    return _result(Clause.LAYER_INHERITED, checked, violations)


def _result(clause: Clause, checked: int, violations: Sequence[Violation]) -> ClauseResult:
    return ClauseResult(
        clause=clause,
        state=ClauseState.FAILED if violations else ClauseState.PASSED,
        checked=checked,
        violations=tuple(violations),
    )
