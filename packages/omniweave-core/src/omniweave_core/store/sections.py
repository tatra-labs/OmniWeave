"""`block_sec` -- the derived section prefix index, its `sec_path` codec, and the fanout limit.

Implements 07-store-and-retrieval.md section 3.6 (:556-578), whose DDL ships in
`schema/migrations/0003_index.sql:277-283` and whose one hard rule is the zero-padding:

> `sec_path` components are **zero-padded to four digits** (`/0001/0004/0002`), because a plain
> integer path makes `'/1/10' < '/1/2'` lexicographically and the range scan silently returns the
> wrong set. (07:571-573)

`block_sec` is a `[DER]` object: not an ordering authority and not an identity
(0003_index.sql:277-279), outside the `[SOR]` read contract, and named in
`ow store rebuild <object>`'s list (03-document-model.md:2477-2478). That last sentence is the
design constraint this module answers to -- the derivation reads committed `block` rows and writes
only `block_sec`, so it can be run from scratch, at any time, against a generation nobody is
writing. `derive_block_sec` is the function `ow store rebuild block_sec` wires at P7
(16-roadmap.md section 10); it parses no arguments and holds no CLI opinion.

## One computation, two shapes

07:577-578 -- *"`block_sec` is computed once and read twice: as an indexed prefix for retrieval,
and by the segmenter, which reads it to produce `segment.heading_path` (X26)"* -- is why the
module ships a codec and not just a writer. Retrieval's shape is
`sec_path >= lo AND sec_path < hi` over `block_sec_path` (`sec_path_range`). The segmenter's shape
is the ancestor chain (`sec_path_ancestors`), and it is recoverable **because every section's own
defining block carries a row where `block_id == sec_id`** -- see `plan_sections` for why that
invariant is forced rather than chosen.

## What is derived from what

03-document-model.md:817 fixes the precedence in one line: an explicit `section` block is *"an
**explicit** typed section from the source ... Emitted only when
`Capabilities.sections == "typed_levels"`. Where absent, the hierarchy is derived into `block_sec`
from `heading` blocks."* So a `section` block always opens a section and its extent is its own
subtree, while a `heading` block opens a section whose extent runs to the next heading at its level
or shallower. One stack in `plan_sections` handles both.

## What the plan does not say, and the reading taken

03:2255 hands *"its derivation rule, the skipped-level policy and `segment.heading_path`"* to
[structure extraction](06-structure-extraction.md), and 06 carries none of the three: its four
mentions of `block_sec` (:29, :825, :959, :978) all READ it and none defines it. Three rulings were
needed and each is argued where it is made -- the skipped-level policy in `plan_sections`, what
bounds a heading-opened section in `_enter`, and the upper bound of the range scan in
`sec_path_range`. Reported as a plan gap rather than guessed silently.

Stdlib only (INV-2). `import sqlite3` is legal here because this file is under `store/` and
`pyproject.toml`'s per-file-ignore covers TID251 there (INV-17); it is imported for the
`Connection` type the two database functions take and for nothing else -- this module opens no
connection, `store/sqlite.py` is the only module that does (ST1, 07:2721), and it starts no
transaction, because the `Unit` that called it IS the transaction (07:2717).

No clock is read and no id is minted: every number below comes from a `block` row or from a counter
this module advances inside the caller's transaction (02-architecture.md:392).

Tier T-PUBLIC, alongside the rest of `omniweave_core.store`.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from omniweave_core.canonical import canonical
from omniweave_core.errors import ResourceLimit, StoreError
from omniweave_core.model.block import BlockId
from omniweave_core.model.enums import Kind
from omniweave_core.model.records import Diag

__all__ = [
    "SEC_PATH_FANOUT",
    "SEC_PATH_LIMIT_NAME",
    "SEC_PATH_ROOT",
    "SEC_PATH_SENTINEL",
    "SEC_PATH_WIDTH",
    "SecBlock",
    "SecRow",
    "SectionReport",
    "derive_block_sec",
    "format_sec_path",
    "plan_sections",
    "read_sec_blocks",
    "sec_path_ancestors",
    "sec_path_components",
    "sec_path_range",
]

_FIX: Final = "ow store rebuild block_sec"


# ---------------------------------------------------------------------------
# The codec's constants. Every one of them is 07 section 3.6's.
# ---------------------------------------------------------------------------

SEC_PATH_ROOT: Final = "/"
"""The path of the implicit root section: depth 0, with the whole document under it.

07:3173 makes this the documented degenerate filter -- *"`sec_path_prefix = "/"` ... the range scan
degenerates to the whole corpus, which is `Narrowing.kind = "all"` -- a legal plan, not an error"*.
A document with no `heading` and no `section` block produces exactly one section, this one, which
is 03:2261-2262's *"a `none` driver produces a document with one implicit section"*.
"""

SEC_PATH_WIDTH: Final = 4
"""Digits per component. **The whole point of the table**, in 07:571-573's words.

Four, not "enough": the width and `SEC_PATH_FANOUT` are one decision seen twice, and
`format_sec_path` refuses a component that would not fit rather than emitting a key that sorts
wrong. A five-digit component is not a bigger number, it is an unsortable one.
"""

SEC_PATH_FANOUT: Final = 9_999
"""Child sections one section may have: `10 ** SEC_PATH_WIDTH - 1`.

07:573-575 -- *"a section with more than 9,999 siblings emits
`Diag(OW_RESOURCE_LIMIT, {limit: "SEC_PATH_FANOUT"})` and truncates the path at that depth rather
than producing an unsortable key."* It lives here rather than in `omniweave_core.limits` because
that module is *"every `MAX_*` ceiling"* (limits.py:1) with a test table asserting one row per
export, the plan never spells this knob `MAX_*`, and its value is not free: it IS
`10 ** SEC_PATH_WIDTH - 1`, so a copy in another module would be a second place for the padding
width to drift out of step with the digits actually emitted. Reported; if it moves, it moves as
`MAX_SEC_PATH_FANOUT` with its own row in that module's value table.
"""

SEC_PATH_LIMIT_NAME: Final = "SEC_PATH_FANOUT"
"""The `limit` key of the breach `Diag`, spelled once. 07:574 prints it verbatim."""

SEC_PATH_SENTINEL: Final = "\U0010ffff"
"""The upper bound of a prefix range: the prefix plus the highest codepoint there is.

The same constant and the same argument as `reader.py`'s `_PREFIX_SENTINEL` (:230-239), which is
already shipped and already serves `Filters.sec_path_prefix`. `sec_path_range` says why the
increment-the-last-component form the DDL prints is not used, and why the two must agree.
"""

_DEFAULT_HEADING_LEVEL: Final = 1
"""What a `heading` with no readable `payload.level` counts as.

03:977 makes `heading.level` `{"type":"integer","minimum":1,"maximum":9}` and `DocSink.add_block`
enforces it, so a freshly written store cannot hold one -- but this is a `[DER]` rebuild that must
run against whatever the store already contains (03:2477), and refusing to rebuild the index
because one row of an old generation lost its payload would make the rebuild path useless exactly
when it is needed. The heading counts as level 1 and its row is still written.
"""


# ---------------------------------------------------------------------------
# The codec. Two functions, both tiny, and both are where the bug lives.
# ---------------------------------------------------------------------------


def format_sec_path(components: Sequence[int]) -> str:
    """`(1, 4, 2) -> '/0001/0004/0002'`, and `() -> '/'`.

    Zero-padded to `SEC_PATH_WIDTH`, because 07:571-573 says the unpadded form makes
    `'/1/10' < '/1/2'` and *"the range scan silently returns the wrong set"*. Padding is what makes
    the lexicographic order of the strings the numeric order of the components; every component
    having the same width is also what stops any sibling path being a string prefix of another,
    which is the property `sec_path_range` leans on.

    A component outside `1 .. SEC_PATH_FANOUT` is refused rather than emitted. 07:574's remedy for
    the overflow is to TRUNCATE the path -- that is `plan_sections`' job and cannot be done from
    here, where the parent is not in view -- and a component this function widened to five digits
    would sort below every four-digit sibling, which is the exact failure the padding exists to
    prevent.
    """
    if not components:
        return SEC_PATH_ROOT
    parts: list[str] = []
    for component in components:
        if not 1 <= component <= SEC_PATH_FANOUT:
            msg = (
                f"sec_path component {component} is outside 1..{SEC_PATH_FANOUT}: a component "
                f"wider than {SEC_PATH_WIDTH} digits sorts below every padded sibling (07:571-575)"
            )
            raise ResourceLimit(msg, limit=SEC_PATH_LIMIT_NAME, fix=_FIX)
        parts.append(f"{component:0{SEC_PATH_WIDTH}d}")
    return "/" + "/".join(parts)


def sec_path_components(path: str) -> tuple[int, ...]:
    """`'/0001/0004/0002' -> (1, 4, 2)`, and `'/' -> ()`. The inverse of `format_sec_path`.

    The round trip is exact in both directions for every path the writer can emit, which is what
    lets `sec_path_ancestors` rebuild the spine from a stored string rather than from a second walk
    over `block.parent_id`.
    """
    if path == SEC_PATH_ROOT:
        return ()
    if not path.startswith("/") or path.endswith("/"):
        raise StoreError(_malformed(path), fix=_FIX)
    parts = path[1:].split("/")
    if any(len(p) != SEC_PATH_WIDTH or not p.isdigit() for p in parts):
        raise StoreError(_malformed(path), fix=_FIX)
    return tuple(int(p) for p in parts)


def sec_path_range(prefix: str) -> tuple[str, str]:
    """The half-open `[lo, hi)` the index scan uses: `sec_path >= lo AND sec_path < hi`.

    **The bound is `prefix + U+10FFFF`, not the increment-the-last-component form the DDL prints,
    and the difference is a real bug at the last sibling `SEC_PATH_FANOUT` admits.** 07:573-574 and
    0003_index.sql:286-288 both say *"the prefix upper bound is the path with its last component
    incremented"*; that form carries at exactly 9,999. Incrementing `/0001/9999` gives
    `/0001/10000`, and `'/0001/10000' < '/0001/9999/0001'` because `'1' < '9'` at the seventh
    character -- so the widened range LOSES the whole subtree it was widened for. The sentinel form
    needs no carry, and over the padded alphabet the two agree on every other path: a descendant of
    `P` continues with `'/'` (U+002F), which is below U+10FFFF, and a non-descendant differs from
    `P` inside a fixed-width component, so it is either below `P` or above `P + U+10FFFF`.

    This is `reader.py`'s already-shipped ruling (`_PREFIX_SENTINEL`, :230-239) and not a new one.
    The two MUST agree: `SqliteReader._filters` builds `Filters.sec_path_prefix`'s bound with that
    constant and this module writes the rows it scans, so a disagreement would be a filter that
    quietly returns a different set than the writer's own notion of a subtree.

    The range is inclusive of the prefix itself, so scanning `/0001/0004` returns section 4's own
    heading block as well as its contents -- 07:1302's *"`b` is its own depth-0 ancestor"* on the
    read side, and `plan_sections` writes the row that makes it true.
    """
    if not prefix.startswith("/"):
        msg = (
            f"a sec_path prefix starts at the root: got {prefix!r}, want '/' or a padded path "
            f"like '/0003/0007' (07:1571)"
        )
        raise StoreError(msg, fix=_FIX)
    return prefix, prefix + SEC_PATH_SENTINEL


def sec_path_ancestors(path: str) -> tuple[str, ...]:
    """The spine as paths, root first, INCLUDING `path` itself: the segmenter's second shape.

    `'/0001/0004' -> ('/', '/0001', '/0001/0004')`. 07:1302 -- *"`spine(b)` comes from `block_sec`;
    `b` is its own depth-0 ancestor"* -- is why `path` is the last element rather than excluded: a
    spine that started at the parent would score the heading of section 4.2 against section 4's
    title and never against its own.

    Joined against `block_sec WHERE block_id = sec_id`, this is `segment.heading_path` (X26,
    07:577-578) in one indexed scan, with no second walk over `block.parent_id`. That is the
    "one computation, two shapes" clause discharged in the only place both readers can share.
    """
    components = sec_path_components(path)
    return tuple(format_sec_path(components[:n]) for n in range(len(components) + 1))


def _malformed(path: str) -> str:
    return (
        f"{path!r} is not a sec_path: every component is exactly {SEC_PATH_WIDTH} digits, "
        f"zero-padded, and the root is {SEC_PATH_ROOT!r} (07:571-573)"
    )


# ---------------------------------------------------------------------------
# What goes in and what comes out
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SecBlock:
    """One `block` row, narrowed to the five columns the derivation reads.

    Five and not the whole row, because the derivation is defined over the tree and the kind and
    nothing else -- and because a narrow input is what lets `plan_sections` be a pure function a
    test can drive with ten thousand synthetic siblings without ten thousand INSERTs.

    `kind` is the `enum_val` NAME (`'heading'`), never this build's `Kind` ordinal: 07:1655-1657
    resolves codes against the store's own seed and `reader.py:388-399` does the same, so a store
    seeded by an older build keeps answering in its own numbering. `level` is `payload.level` for a
    `heading` and `None` for everything else; `read_sec_blocks` says why it is not read off every
    row.
    """

    block_id: int
    parent_id: int | None
    ord: int
    kind: str
    level: int | None = None


@dataclass(frozen=True, slots=True)
class SecRow:
    """One `block_sec` row, column for column with 0003_index.sql:277-282.

    `sec_depth` is `len(sec_path_components(sec_path))` by construction and is stored anyway,
    because the DDL stores it: a scan that filtered on the covering `(sec_path, block_id)` index
    would otherwise have to parse the string to learn the depth the lexical scorer decays by
    (07:1294-1302).
    """

    block_id: int
    sec_id: int
    sec_depth: int
    sec_path: str


@dataclass(frozen=True, slots=True)
class SectionReport:
    """What `plan_sections` computed and `derive_block_sec` wrote.

    **It reports the diagnostics rather than writing them**, which is `owcheck`'s shape and for
    `owcheck`'s reason: `end_doc()` runs the derivation inside the one transaction it already owns,
    and it, not this module, decides what a breach does to `doc.status` (03:1824, and
    `archive/owcheck.py:203-212`). `diag_rows()` hands them over ready for the store's
    `INSERT INTO diag`.

    `sections` counts the section scopes opened below the root; `folded` counts the blocks whose
    path the fanout limit truncated. Both are zero on a document with no headings, which is a
    different statement from `rows == ()` and the two are asserted separately.
    """

    doc_ord: int
    gen: int
    rows: tuple[SecRow, ...]
    diags: tuple[Diag, ...] = ()
    sections: int = 0
    folded: int = 0

    def diag_rows(self) -> tuple[dict[str, Any], ...]:
        """The report as `diag` rows: column for column with `CREATE TABLE diag`.

        `doc_ord` and `gen` come from the report rather than from parameters, unlike
        `owcheck.Report.diag_rows(doc_ord=, gen=)`, because this derivation is always scoped to one
        generation and a caller free to pass another could file the diagnostic against the wrong
        document. `detail` goes through `canonical()` like every other JSON column in L2
        (`doc.py:361-370`), so a value that cannot be canonicalised is a refusal here rather than a
        column two readers disagree about.
        """
        return tuple(
            {
                "doc_ord": self.doc_ord,
                "gen": self.gen,
                "page": d.page,
                "block_id": None if d.block is None else int(d.block),
                "part": d.part,
                "code": d.code,
                "severity": d.severity,
                "component": d.component,
                "message": d.message,
                "detail": canonical(dict(d.detail)).decode("utf-8"),
                "fatal": int(d.fatal),
            }
            for d in self.diags
        )


@dataclass(slots=True)
class _Scope:
    """One open section on the derivation's stack. Mutable, because `children` counts up."""

    sec_id: int
    depth: int
    path: str
    level: int
    from_heading: bool
    children: int = 0
    overflowed: bool = False


@dataclass(slots=True)
class _Walk:
    """The DFS's accumulators in one object, so `_enter` stays a function of the node."""

    stack: list[_Scope]
    component: str
    rows: list[SecRow] = field(default_factory=list)
    diags: list[Diag] = field(default_factory=list)
    sections: int = 0
    folded: int = 0


_NO_SCOPE: Final = -1
"""`_enter`'s answer for "this block opened no subtree-bounded section". Not a stack index."""


# ---------------------------------------------------------------------------
# The derivation
# ---------------------------------------------------------------------------


def plan_sections(
    blocks: Iterable[SecBlock], *, doc_ord: int, gen: int, component: str | None = None
) -> SectionReport:
    """One `SecRow` per block, from explicit `section` blocks and derived from `heading` blocks.

    The walk is one pre-order DFS over `parent_id`/`ord` with one stack of open sections, and three
    rules decide everything:

    1. **An explicit `section` opens a section bounded by its own subtree** -- 03:817 makes it
       authoritative where it exists. It is pushed before its own row is written and popped after
       its last descendant, so a `heading` inside it nests UNDER it instead of replacing it, which
       is what "the two together are consistent" has to mean when a driver emits both. Nothing else
       is defensible: a heading that could pop a typed section would let a `##` in the source
       silently outrank a structural level the source actually declared.
    2. **A `heading` opens a section that runs to the next heading at its level or shallower**, and
       `_enter` argues what bounds it when a container ends first.
    3. **The skipped-level policy is "nest, do not invent".** 03:2255 defers this to a document
       that never makes the call, so: `H1` then `H3` puts the `H3` at DEPTH 2, not depth 3. Depth
       comes from the stack and never from the level number. The alternative -- pad the path with a
       phantom component per skipped level -- would put a component in `sec_path` that no block
       defines, so the table would carry a path with no row where `block_id == sec_id` and the
       segmenter's `heading_path` would have a hole in it. It would also make `sec_depth` mean two
       different things in one column: nesting for some rows, source levels for others.

    **Every block gets a row, including the section-opening blocks themselves, and a section's own
    block carries `block_id == sec_id`.** 07:1302 fixes this -- *"`spine(b)` comes from
    `block_sec`; `b` is its own depth-0 ancestor"* -- and the read side needs it twice. A heading
    filed under its PARENT's path would fall outside the range scan for its own section, so
    "everything under section 4.2" would return the section without its title; and the segmenter
    could not find the block that names a path at all, because `block_id == sec_id` is the only
    thing in this table that tells a section's defining block from its contents.

    The document's own root block is the depth-0 section: path `/`, `sec_depth = 0`, `sec_id`
    itself. That is 03:2261-2262's *"one implicit section"*, and it is why a document with no
    headings produces a well-formed row per block instead of zero rows.

    `component` names the module the `Diag` is attributed to. It defaults to this one and exists so
    a rebuild can say it was the rebuild, and not the parse, that found the breach.
    """
    by_id = {b.block_id: b for b in blocks}
    children = _child_lists(by_id)
    roots = children.get(None, [])
    if not roots:
        return SectionReport(doc_ord=doc_ord, gen=gen, rows=())

    root = next((b for b in roots if b.kind == Kind.DOCUMENT), roots[0])
    stack = [_Scope(sec_id=root.block_id, depth=0, path=SEC_PATH_ROOT, level=0, from_heading=False)]
    state = _Walk(stack=stack, component=component or __name__)

    # (node, floor) enters a block; (None, index) closes an explicit section's subtree.
    work: list[tuple[SecBlock | None, int]] = [(node, 0) for node in reversed(roots)]
    seen: set[int] = set()
    while work:
        node, floor = work.pop()
        if node is None:
            del stack[floor:]
            continue
        if node.block_id in seen:  # a parent cycle owcheck would quarantine: do not spin on it
            continue
        seen.add(node.block_id)
        opened = _enter(state, node, floor)
        child_floor = floor if opened == _NO_SCOPE else opened
        if opened != _NO_SCOPE:
            work.append((None, opened))
        work.extend((child, child_floor) for child in reversed(children.get(node.block_id, [])))

    return SectionReport(
        doc_ord=doc_ord,
        gen=gen,
        rows=tuple(sorted(state.rows, key=lambda r: r.block_id)),
        diags=tuple(state.diags),
        sections=state.sections,
        folded=state.folded,
    )


def _enter(state: _Walk, node: SecBlock, floor: int) -> int:
    """Open whatever section `node` opens, write its row, return the scope index to close after it.

    `_NO_SCOPE` means "nothing to close": only an explicit `section` bounds itself by its subtree.

    **A heading-opened section is bounded by the nearest enclosing explicit `section`, or by the
    document, and NOT by the container it happens to sit in.** This is the second of the rulings
    03:2255 defers to a document that does not make them, and the tempting rule -- a heading's
    section ends where its container's child list ends -- is wrong for the shape most of the corpus
    has. 03:814 makes the `document` block's children *page roots*, so in any paged format every
    heading sits inside a per-page container; ending sections at container exit would close every
    section at every page boundary and make "everything under section 4.2" mean "everything under
    section 4.2 on page 12". So containment bounds only an explicit `section`, whose subtree really
    is its extent (03:817), and a heading runs until a heading at its level or shallower, or until
    the explicit section around it closes.

    The cost is stated rather than hidden: a `heading` inside a `table_cell` or a `footnote` opens
    a section that outlives the cell. The plan attaches no layer or kind restriction anywhere --
    03:817 says "derived from `heading` blocks" with no qualification -- and inventing one here
    would be a rule with no definition site behind it.

    `floor` is the index of the innermost scope a heading may NOT pop, which is why the pop loop
    tests `len(stack) - 1 > floor`: an explicit section's own index becomes the floor inside its
    subtree, and index 0 -- the implicit root section -- is the floor everywhere else, so the stack
    can never empty.
    """
    opened = _NO_SCOPE
    if node.kind == Kind.SECTION:
        if _push(state, node, level=0, from_heading=False):
            opened = len(state.stack) - 1
    elif node.kind == Kind.HEADING:
        level = node.level if node.level is not None else _DEFAULT_HEADING_LEVEL
        while (
            len(state.stack) - 1 > floor
            and state.stack[-1].from_heading
            and state.stack[-1].level >= level
        ):
            state.stack.pop()
        _push(state, node, level=level, from_heading=True)
    _row(state, node)
    return opened


def _push(state: _Walk, node: SecBlock, *, level: int, from_heading: bool) -> bool:
    """Open a section under the current one, or fold into it when the fanout limit says no.

    07:573-575: past `SEC_PATH_FANOUT` siblings the section *"emits
    `Diag(OW_RESOURCE_LIMIT, {limit: "SEC_PATH_FANOUT"})` and truncates the path at that depth
    rather than producing an unsortable key."* Truncating at that depth means the 10,000th sibling
    and everything under it take the PARENT's `sec_id`, depth and path: the rows stay well-formed
    and sortable, the subtree stays findable under its grandparent, and what is lost is one level
    of resolution, disclosed. It is a `Diag` and not a raise because a hundred-thousand-heading
    document is a document and not a usage error -- and because `fatal=True` already makes
    `doc.status` `partial`, so the loss reaches `corpus_card` before any query runs (03:1824).

    The diagnostic fires ONCE per overflowing parent, on the first sibling that does not fit. One
    row per excess sibling would put 90,000 rows in `diag` to say one thing, and `CREATE INDEX
    diag_code` is what the absence contract reads (0001_init.sql:469).
    """
    parent = state.stack[-1]
    parent.children += 1
    if parent.children > SEC_PATH_FANOUT:
        state.folded += 1
        if not parent.overflowed:
            parent.overflowed = True
            state.diags.append(_fanout_diag(state.component, parent, node))
        return False
    prefix = "" if parent.depth == 0 else parent.path
    state.stack.append(
        _Scope(
            sec_id=node.block_id,
            depth=parent.depth + 1,
            path=f"{prefix}/{parent.children:0{SEC_PATH_WIDTH}d}",
            level=level,
            from_heading=from_heading,
        )
    )
    state.sections += 1
    return True


def _row(state: _Walk, node: SecBlock) -> None:
    """The block's own row, taken from whatever section is open over it."""
    scope = state.stack[-1]
    state.rows.append(
        SecRow(
            block_id=node.block_id,
            sec_id=scope.sec_id,
            sec_depth=scope.depth,
            sec_path=scope.path,
        )
    )


def _fanout_diag(component: str, parent: _Scope, node: SecBlock) -> Diag:
    """`Diag(OW_RESOURCE_LIMIT, {limit: "SEC_PATH_FANOUT"})`, spelled as 07:574 prints it."""
    message = (
        f"section {parent.path} has more than {SEC_PATH_FANOUT} child sections; block "
        f"{node.block_id} and every sibling after it keep the parent's sec_path rather than a "
        f"component too wide to sort (07:573-575)"
    )
    return Diag(
        code=ResourceLimit.SYMBOL,
        severity="warning",
        component=component,
        message=message,
        block=BlockId(node.block_id),
        detail={
            "limit": SEC_PATH_LIMIT_NAME,
            "sec_path": parent.path,
            "sec_depth": parent.depth,
            "siblings": SEC_PATH_FANOUT,
        },
        fatal=True,
    )


def _child_lists(by_id: Mapping[int, SecBlock]) -> dict[int | None, list[SecBlock]]:
    """`{parent_id: children in (ord, block_id) order}`, with an out-of-scope parent read as root.

    `ord` is *"position among siblings == READING ORDER"* (0001_init.sql:243) and `block_id` breaks
    a tie, so the walk is total and its output is byte-identical across runs -- which is exactly
    what `ow store rebuild` needs from a `[DER]` object (03:2477).

    A block whose `parent_id` is not in scope becomes a root rather than being dropped. It happens
    on a rebuild over a generation whose parent row was tombstoned, and dropping it would leave a
    live block with no `block_sec` row at all -- a hole the range scan would report as an absence
    rather than as damage.
    """
    children: dict[int | None, list[SecBlock]] = {}
    for block in by_id.values():
        parent = block.parent_id if block.parent_id in by_id else None
        children.setdefault(parent, []).append(block)
    for kids in children.values():
        kids.sort(key=lambda b: (b.ord, b.block_id))
    return children


# ---------------------------------------------------------------------------
# The store side
# ---------------------------------------------------------------------------

_READ_BLOCKS: Final = (
    "SELECT block_id, parent_id, ord, kind, payload FROM block "
    "WHERE doc_ord = ? AND gen = ? AND state = 0 ORDER BY block_id"
)

_DELETE_SCOPE: Final = (
    "DELETE FROM block_sec WHERE block_id IN "
    "(SELECT block_id FROM block WHERE doc_ord = ? AND gen = ?)"
)

_INSERT_ROW: Final = (
    "INSERT INTO block_sec(block_id, sec_id, sec_depth, sec_path) VALUES(?, ?, ?, ?)"
)


def read_sec_blocks(connection: sqlite3.Connection, doc_ord: int, gen: int) -> list[SecBlock]:
    """The live blocks of one generation, as the derivation's five columns.

    **`block` and not `ow_block_head`.** The view joins `b.gen = d.gen` (0001_init.sql:328-330) and
    the derivation runs inside `end_doc`, where the staged generation is `doc.gen + 1` and
    deliberately invisible (03:75-80). Reading through the view there would derive the index of the
    generation being replaced. `state = 0` is the view's other half and is kept, because 07:559-563
    is one row per live block.

    **`payload` is parsed only for a `heading`.** 03:979-981 refuses `Block.payload` outright,
    because *"materialising a JSON object per block would put a `json.loads` on every row of a
    600k-block scan for a field two consumers read"*, and the argument applies here word for word:
    the only key this module reads is `heading.level`, so only heading rows pay for it.
    """
    names = _kind_names(connection)
    heading = names.get(Kind.HEADING.value)
    blocks: list[SecBlock] = []
    for block_id, parent_id, ord_, kind_code, payload in connection.execute(
        _READ_BLOCKS, (doc_ord, gen)
    ):
        code = int(kind_code)
        blocks.append(
            SecBlock(
                block_id=int(block_id),
                parent_id=None if parent_id is None else int(parent_id),
                ord=int(ord_),
                kind=_kind_name(names, code),
                level=_heading_level(payload) if code == heading else None,
            )
        )
    return blocks


def derive_block_sec(connection: sqlite3.Connection, doc_ord: int, gen: int) -> SectionReport:
    """Rebuild `block_sec` for one generation from its `block` rows. Returns the report.

    Read the tree, plan the sections, replace the scope's rows. It is the whole of
    `ow store rebuild block_sec` for one document (03:2477 lists the object; 16-roadmap.md section
    10 owns the verb), and it is what `DocSink.end_doc`'s closure pass calls once the generation's
    blocks are staged.

    **It replaces rather than merges, and that is what makes re-derivation idempotent.** The DELETE
    is scoped by a subquery over `block` rather than by a column on `block_sec`, because the table
    has four columns and none of them is `doc_ord` (0003_index.sql:277-282): it is keyed by
    `block_id` and reached through the FK. Scoping it any other way would either leave a stale row
    behind for a block tombstoned since the last derivation, or reach into another document's rows.

    **No transaction is opened and none is committed.** 07:2717 -- the `Unit` IS the transaction --
    so a caller that wants this atomic with the rest of `end_doc` gets it by construction, and a
    rebuild that wants a transaction of its own opens one around the call.
    """
    report = plan_sections(read_sec_blocks(connection, doc_ord, gen), doc_ord=doc_ord, gen=gen)
    connection.execute(_DELETE_SCOPE, (doc_ord, gen))
    connection.executemany(
        _INSERT_ROW,
        [(r.block_id, r.sec_id, r.sec_depth, r.sec_path) for r in report.rows],
    )
    return report


def _kind_names(connection: sqlite3.Connection) -> Mapping[str, int]:
    """`{member name: ord}` for the `kind` domain, read off the STORE's own `enum_val` seed.

    Never off this build's `Kind`: `enum_val.ord` is append-only (03 section 2.1) and 07:1655-1657
    resolves codes on the connection for exactly this reason. `reader.py:388-399` is the precedent
    and this is the same query.
    """
    rows = connection.execute("SELECT name, ord FROM enum_val WHERE domain = 'kind'")
    return {str(name): int(code) for name, code in rows}


def _kind_name(names: Mapping[str, int], code: int) -> str:
    """The `enum_val` name for a stored `block.kind`, refusing a code the store cannot explain.

    `reader.py:1133-1144`'s refusal, for its reason: a code with no `enum_val` row means the seed
    and the rows disagree, and guessing "not a section" would silently flatten a real hierarchy
    into one implicit section that answers every prefix query with the whole document.
    """
    for name, ord_ in names.items():
        if ord_ == code:
            return name
    msg = (
        f"this store holds kind code {code}, which its own enum_val does not name: deriving "
        f"block_sec over it would silently flatten the section hierarchy"
    )
    raise StoreError(msg, fix="ow store migrate")


def _heading_level(payload: str | None) -> int:
    """`payload.level` as an int, or `_DEFAULT_HEADING_LEVEL` when the column cannot supply one.

    `bool` is rejected before `int` because `True` is an `int` in Python and a `{"level": true}`
    payload would otherwise become level 1 by arithmetic accident rather than by this rule.
    """
    if not payload:
        return _DEFAULT_HEADING_LEVEL
    try:
        loaded = json.loads(payload)
    except ValueError:
        return _DEFAULT_HEADING_LEVEL
    if not isinstance(loaded, dict):
        return _DEFAULT_HEADING_LEVEL
    level = loaded.get("level")
    if isinstance(level, bool) or not isinstance(level, int) or level < 1:
        return _DEFAULT_HEADING_LEVEL
    return level
