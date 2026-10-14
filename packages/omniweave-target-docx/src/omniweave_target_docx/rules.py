"""owflow/1's rules: the structural contract a flow document has, and no geometry. **D781.**

09-generation.md section 12.3 names six validator rules: heading level monotonicity, table cell
topology, footnote references resolving within the unit, list nesting depth, every `asset-slot:`
resolving, and no positioning construct. The last is the table's `pos.*` forbidden rows, which
`omniweave_core.out.conformance.table_pack()` reports with the table's closed set, so this module
holds the rest, in 09 section 4.4's bands.

## Rulings

1. **Heading monotonicity is checked within a unit.** A heading may go at most one level deeper
   than the heading before it in the same unit, and any number of levels shallower. A unit's
   first heading is free: the heading that precedes it is in another unit, and `DocIndex` carries
   no heading levels for a document-scope rule to read.
2. **A table is a grid its cells cover exactly.** Each row group (`thead`, a `tbody`, or the bare
   rows of a `table`) is laid out with `colspan` and `rowspan`, as HTML's table model does. A cell
   that overlaps another, a `rowspan` past its group's last row, and a row whose width differs from
   the first row's are each one finding naming the row. A span that is not a decimal integer from
   1 is reported here as well, after `int_text` has had its chance: `" 02"` is the normalize row's
   warning, `"two"` is this rule's error. `caption` is the first child or nothing, and a `tr`,
   `th` or `td` outside its parent is a topology error too.
3. **The list depth limit is WordprocessingML's nine levels.** `w:ilvl` runs 0 to 8, so `<ul>` or
   `<ol>` nested ten deep has no level to lower to. `RuleCtx.limits["list_depth_max"]` lowers it
   and never raises it. An `<li>` outside `<ul>`/`<ol>`, a `<dt>`/`<dd>` outside `<dl>`, any
   other child of a list container, and a `start` that is not a decimal integer on an `<ol>` are
   the same code, because each is a list WordprocessingML cannot number.
4. **A note resolves within its unit, both ways.** Every `<a data-ow-note>` names exactly one
   `<aside data-ow-footnote>` or `<aside data-ow-endnote>` in the same unit, every body is named
   by exactly one reference, a body id is unique, a reference is empty, and a body is a child of
   the unit's `<section>`. A body nobody references would lower to a note with no mark in the
   text, which Word does not have.
5. **`asset-slot:` resolving is two checks, at two times.** At check time the rule holds the
   grammar: an `<img>`'s `src` is `asset-slot:` and 64 hex, never a URL, a path or `data:`
   (`OW_TARGET_IL_ASSET_URI`). That the slot names a frozen asset is preflight 2's at lower time
   (`OW_TARGET_ASSET_UNFROZEN`), because `RuleCtx` carries no ledger: a rule declaring
   `needs={"assets"}` is a recorded skip on every check, which would hold every docx gate at
   `unverified` whether or not a unit has a picture.
6. **The content model is HTML's, narrowed to what WordprocessingML nests.** A paragraph, a
   heading, `pre`, `dt`, a caption and every inline mark hold inline content only. A block inside
   one, a `figcaption` outside `figure`, and a value outside its row's `canonical` (`text-align`,
   `dir`, a link's target) are `OW_TARGET_TEXT_INVALID`.
7. **A cite's kind and span are checked where the gate can say so** (D783). The compile already
   refuses a `data-ow-cite-kind` outside the four kinds and a `data-ow-cite-span` that is not
   `a:b` with `a < b`, as `OW_TARGET_IL_MALFORMED` (`run.out_compile` ruling 7). The rows that
   declare the two attributes arrived with D783, so a rule reports the same values with the
   same code at check time, where `ow out check` can name them before a compile is tried. D791
   moves that rule and the cite batch to `omniweave_core.out.conformance.cite_pack()`, every
   target's, under their docx rule ids.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from typing import Final

from omniweave_core.out import Finding, Provenance, RuleCtx, RuleSpec, Severity
from omniweave_core.out.carrier import CarrierNode, style_declarations

__all__ = ["BLOCKS", "LIST_DEPTH_MAX", "rules"]

LIST_DEPTH_MAX: Final = 9
"""Ruling 3: `w:ilvl` is 0-8."""

_HEADING: Final = re.compile(r"html\|h([1-6])")
_SPAN: Final = re.compile(r"[+]?0*[1-9][0-9]{0,3}")
"""A span `int_text` would settle: `" 02"` is a warning there and a width of 2 here."""
_SLOT: Final = re.compile(r"asset-slot:[0-9a-f]{64}")
_LINK: Final = re.compile(r"(?:https?:|mailto:)\S+|#u[0-9]{2,}/e[0-9]+")
_ALIGN: Final = frozenset({"start", "center", "end", "justify"})
_DIR: Final = frozenset({"ltr", "rtl"})
_LISTS: Final = frozenset({"html|ul", "html|ol"})
_GROUPS: Final = frozenset({"html|thead", "html|tbody"})
_CELLS: Final = frozenset({"html|th", "html|td"})
_NOTE_BODIES: Final = ("data-ow-footnote", "data-ow-endnote")
_INLINE_ONLY: Final = frozenset(
    {
        "html|p", "html|h1", "html|h2", "html|h3", "html|h4", "html|h5", "html|h6", "html|pre",
        "html|dt", "html|caption", "html|figcaption", "html|strong", "html|em", "html|u",
        "html|s", "html|code", "html|sub", "html|sup", "html|mark", "html|a", "html|span",
    }
)  # fmt: skip
BLOCKS: Final = frozenset(
    {
        "section", "h1", "h2", "h3", "h4", "h5", "h6", "p", "blockquote", "pre", "hr", "ul",
        "ol", "li", "dl", "dt", "dd", "table", "caption", "thead", "tbody", "tr", "th", "td",
        "figure", "figcaption", "div", "aside",
    }
)  # fmt: skip
"""owflow/1's block constructs by local name: the carrier's block set, this module's content
model and the lowering's split between a block and a run all read this one set."""
_BLOCKS: Final = frozenset(f"html|{b}" for b in BLOCKS)
_CONSTRUCTS: Final = "ow out constructs docx --construct"


def rules() -> Mapping[str, Sequence[RuleSpec]]:
    """The hand-written half of the pack; the driver adds `table_pack()`'s half."""
    return {
        "structure": (
            RuleSpec(
                "docx.unit.root@1", 10, "unit", frozenset({"OW_TARGET_UNIT_MALFORMED"}), unit_root
            ),
            RuleSpec(
                "docx.el.unique@1", 11, "unit", frozenset({"OW_TARGET_EL_DUPLICATE"}), el_unique
            ),
        ),
        "grammar": (
            RuleSpec(
                "docx.heading.levels@1",
                40,
                "unit",
                frozenset({"OW_TARGET_HEADING_SKIP"}),
                heading_levels,
            ),
            RuleSpec(
                "docx.table.topology@1",
                41,
                "unit",
                frozenset({"OW_TARGET_TABLE_TOPOLOGY"}),
                table_topology,
            ),
            RuleSpec(
                "docx.list.nesting@1",
                42,
                "unit",
                frozenset({"OW_TARGET_LIST_MALFORMED"}),
                list_nesting,
            ),
            RuleSpec(
                "docx.note.resolves@1",
                43,
                "unit",
                frozenset({"OW_TARGET_NOTE_UNRESOLVED"}),
                note_resolves,
            ),
            RuleSpec(
                "docx.flow.content@1",
                44,
                "unit",
                frozenset({"OW_TARGET_TEXT_INVALID"}),
                flow_content,
            ),
            RuleSpec(
                "docx.media.src@1",
                45,
                "unit",
                frozenset({"OW_TARGET_IL_ASSET_URI"}),
                media_src,
            ),
        ),
    }


# ---------------------------------------------------------------------------------------------
# order 10-19: the structural contract
# ---------------------------------------------------------------------------------------------


def unit_root(ctx: RuleCtx) -> Iterator[Finding]:
    """`ow.unit`: the root is one `<section>`, and no other `<section>` is inside it."""
    if ctx.doc is None or ctx.unit is None:
        return
    root = ctx.doc.root()
    if root.tag != "html|section":
        yield _root(ctx, root, f"the unit root is <{_local(root.tag)}>; owflow/1's is <section>")
    for n, _, _ in _walk(root):
        if n.tag == "html|section":
            yield _root(ctx, n, "a <section> inside the unit: one unit is one section")


def el_unique(ctx: RuleCtx) -> Iterator[Finding]:
    """OUT21: `data-ow-el` is minted once and refuses on a duplicate."""
    if ctx.doc is None or ctx.unit is None:
        return
    seen: dict[str, str] = {}
    for n in ctx.doc.select("@data-ow-el"):
        el = n.attr("data-ow-el") or ""
        if el in seen:
            yield _finding(
                ctx,
                n,
                rule="docx.el.unique@1",
                code="OW_TARGET_EL_DUPLICATE",
                construct="ow.el",
                msg=f"data-ow-el={el!r} appears at {seen[el]} and {n.at}",
            )
        else:
            seen[el] = n.at


# ---------------------------------------------------------------------------------------------
# order 40-59: grammar and value
# ---------------------------------------------------------------------------------------------


def heading_levels(ctx: RuleCtx) -> Iterator[Finding]:
    """Ruling 1: no `h1` to `h3` jump within a unit."""
    if ctx.doc is None or ctx.unit is None:
        return
    previous: int | None = None
    for n, _, _ in _walk(ctx.doc.root()):
        m = _HEADING.fullmatch(n.tag)
        if m is None:
            continue
        level = int(m[1])
        if previous is not None and level > previous + 1:
            yield _finding(
                ctx,
                n,
                rule="docx.heading.levels@1",
                code="OW_TARGET_HEADING_SKIP",
                construct=f"block.h{level}",
                msg=f"<h{level}> follows <h{previous}>: a heading goes at most one level "
                "deeper than the one before it",
            )
        previous = level


def table_topology(ctx: RuleCtx) -> Iterator[Finding]:
    """Ruling 2: every table's row groups are grids its cells cover exactly."""
    if ctx.doc is None or ctx.unit is None:
        return
    for n, parent, _ in _walk(ctx.doc.root()):
        if n.tag == "html|tr" and parent not in {"html|table", *_GROUPS}:
            yield _topology(ctx, n, f"<tr> inside <{_local(parent)}>, not a table or row group")
        elif n.tag in _CELLS and parent != "html|tr":
            yield _topology(ctx, n, f"<{_local(n.tag)}> inside <{_local(parent)}>, not a <tr>")
        elif n.tag in _GROUPS | {"html|caption"} and parent != "html|table":
            yield _topology(ctx, n, f"<{_local(n.tag)}> inside <{_local(parent)}>, not <table>")
    for table in ctx.doc.select("html|table"):
        yield from _table(ctx, table)


def _table(ctx: RuleCtx, table: CarrierNode) -> Iterator[Finding]:
    children = list(table.children())
    bare: list[CarrierNode] = []
    for i, child in enumerate(children):
        if child.tag == "html|caption" and i != 0:
            yield _topology(ctx, child, "<caption> is the first child of its <table> or absent")
        elif child.tag in _GROUPS:
            yield from _grid(ctx, [r for r in child.children() if r.tag == "html|tr"])
        elif child.tag == "html|tr":
            bare.append(child)
        elif child.tag != "html|caption":
            yield _topology(ctx, child, f"<{_local(child.tag)}> is not a part of a <table>")
    if bare:
        yield from _grid(ctx, bare)


def _grid(ctx: RuleCtx, rows: Sequence[CarrierNode]) -> Iterator[Finding]:
    """HTML's table model over one row group: lay each cell out, then compare the widths."""
    taken: set[tuple[int, int]] = set()
    widths: list[int] = []
    for r, row in enumerate(rows):
        c = 0
        for cell in row.children():
            if cell.tag not in _CELLS:
                continue
            while (r, c) in taken:
                c += 1
            cols, down = _span(cell, "colspan"), _span(cell, "rowspan")
            if cols is None or down is None:
                yield _topology(ctx, cell, "colspan and rowspan are decimal integers from 1")
                cols, down = cols or 1, down or 1
            if r + down > len(rows):
                yield _topology(ctx, cell, f"rowspan={down} runs past its group's last row")
            slots = {(r + dr, c + dc) for dr in range(down) for dc in range(cols)}
            if slots & taken:
                yield _topology(ctx, cell, "this cell overlaps a cell spanning into its row")
            taken |= slots
            c += cols
        widths.append(max((cc + 1 for rr, cc in taken if rr == r), default=0))
    if widths:
        for row, width in zip(rows, widths, strict=True):
            if width != widths[0]:
                yield _topology(
                    ctx, row, f"this row covers {width} columns and the group's first {widths[0]}"
                )


def _span(cell: CarrierNode, name: str) -> int | None:
    value = cell.attr(name)
    if value is None:
        return 1
    stripped = value.strip()
    return int(stripped) if _SPAN.fullmatch(stripped) else None


def list_nesting(ctx: RuleCtx) -> Iterator[Finding]:
    """Ruling 3: depth within the limit, and each list part inside its own container."""
    if ctx.doc is None or ctx.unit is None:
        return
    limit = min(ctx.limits.get("list_depth_max", LIST_DEPTH_MAX), LIST_DEPTH_MAX)
    for n, parent, depth in _walk(ctx.doc.root()):
        if n.tag in _LISTS and depth > limit:
            yield _list(ctx, n, f"a list nested {depth} deep; WordprocessingML numbers {limit}")
        if n.tag == "html|li" and parent not in _LISTS:
            yield _list(ctx, n, f"<li> inside <{_local(parent)}>, not <ul> or <ol>")
        if n.tag in {"html|dt", "html|dd"} and parent != "html|dl":
            yield _list(ctx, n, f"<{_local(n.tag)}> inside <{_local(parent)}>, not <dl>")
        if n.tag in _LISTS:
            for child in n.children():
                if child.tag != "html|li":
                    yield _list(ctx, child, f"<{_local(child.tag)}> directly inside a list")
        if n.tag == "html|dl":
            for child in n.children():
                if child.tag not in {"html|dt", "html|dd"}:
                    yield _list(ctx, child, f"<{_local(child.tag)}> directly inside <dl>")
        start = n.attr("start")
        if start is not None and (n.tag != "html|ol" or not start.isdecimal()):
            yield _list(ctx, n, f"start={start!r}: a decimal integer, on <ol> only")


def note_resolves(ctx: RuleCtx) -> Iterator[Finding]:
    """Ruling 4: references and bodies pair one to one within the unit."""
    if ctx.doc is None or ctx.unit is None:
        return
    bodies: dict[str, CarrierNode] = {}
    for body, parent, _ in _walk(ctx.doc.root()):
        kinds = [k for k in _NOTE_BODIES if body.tag == "html|aside" and body.attr(k) is not None]
        if not kinds:
            continue
        note = body.attr(kinds[0]) or ""
        if note in bodies:
            yield _note(ctx, body, f"note id {note!r} names two bodies")
        bodies.setdefault(note, body)
        if parent != "html|section":
            yield _note(ctx, body, "a note body is a child of the unit's <section>")
    refs = ctx.doc.select("html|a[data-ow-note]")
    counted = Counter(r.attr("data-ow-note") or "" for r in refs)
    for ref in refs:
        note = ref.attr("data-ow-note") or ""
        if note not in bodies:
            yield _note(ctx, ref, f"note {note!r} has no body in this unit")
        if ref.text_content().strip() or list(ref.children()):
            yield _note(ctx, ref, "a note reference is empty; Word numbers the mark itself")
    for note, body in bodies.items():
        if counted[note] != 1:
            yield _note(ctx, body, f"note {note!r} is referenced {counted[note]} times, not once")


def flow_content(ctx: RuleCtx) -> Iterator[Finding]:
    """Ruling 6: inline-only parents hold no block, and three values hold their canonical form."""
    if ctx.doc is None or ctx.unit is None:
        return
    for n, parent, _ in _walk(ctx.doc.root()):
        if n.tag in _BLOCKS and parent in _INLINE_ONLY:
            yield _text(
                ctx,
                n,
                f"<{_local(n.tag)}> inside <{_local(parent)}>, which holds inline content only",
            )
        if n.tag == "html|figcaption" and parent != "html|figure":
            yield _text(ctx, n, "<figcaption> is inside <figure> only")
        align = [v for prop, v in style_declarations(n.attr("style") or "") if prop == "text-align"]
        if align and align[-1].strip().lower() not in _ALIGN:
            yield _text(ctx, n, f"text-align: {align[-1]!r} is not start, center, end or justify")
        direction = n.attr("dir")
        if direction is not None and direction not in _DIR:
            yield _text(ctx, n, f"dir={direction!r} is ltr or rtl")
        href = n.attr("href")
        if n.tag == "html|a" and href is not None and _LINK.fullmatch(href) is None:
            yield _text(ctx, n, f"href={href!r} is an http(s): or mailto: URI, or #<data-ow-el>")


def media_src(ctx: RuleCtx) -> Iterator[Finding]:
    """Ruling 5's check-time half: `src` is `asset-slot:` and 64 hex."""
    if ctx.doc is None or ctx.unit is None:
        return
    for n in ctx.doc.select("html|img[src]"):
        src = n.attr("src") or ""
        if _SLOT.fullmatch(src) is None:
            yield _finding(
                ctx,
                n,
                rule="docx.media.src@1",
                code="OW_TARGET_IL_ASSET_URI",
                construct="media.img",
                msg=f"src={src[:80]!r} is not asset-slot:<sha256 hex>; freeze the asset and "
                "write its slot",
            )


# ---------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------


def _finding(
    ctx: RuleCtx, n: CarrierNode, *, rule: str, code: str, construct: str, msg: str
) -> Finding:
    return Finding(
        code=code,
        severity=Severity.ERROR,
        provenance=Provenance.INTRODUCED,
        rule=rule,
        unit=ctx.unit.id if ctx.unit is not None else "",
        construct=construct,
        msg=msg,
        fix=f"{_CONSTRUCTS} {construct}",
        at=n.at,
        el=n.el,
    )


def _root(ctx: RuleCtx, n: CarrierNode, msg: str) -> Finding:
    return _finding(
        ctx,
        n,
        rule="docx.unit.root@1",
        code="OW_TARGET_UNIT_MALFORMED",
        construct="ow.unit",
        msg=msg,
    )


def _topology(ctx: RuleCtx, n: CarrierNode, msg: str) -> Finding:
    return _finding(
        ctx,
        n,
        rule="docx.table.topology@1",
        code="OW_TARGET_TABLE_TOPOLOGY",
        construct="table.table",
        msg=msg,
    )


def _list(ctx: RuleCtx, n: CarrierNode, msg: str) -> Finding:
    return _finding(
        ctx,
        n,
        rule="docx.list.nesting@1",
        code="OW_TARGET_LIST_MALFORMED",
        construct="list.li",
        msg=msg,
    )


def _note(ctx: RuleCtx, n: CarrierNode, msg: str) -> Finding:
    return _finding(
        ctx,
        n,
        rule="docx.note.resolves@1",
        code="OW_TARGET_NOTE_UNRESOLVED",
        construct="note.ref",
        msg=msg,
    )


def _text(ctx: RuleCtx, n: CarrierNode, msg: str) -> Finding:
    return _finding(
        ctx,
        n,
        rule="docx.flow.content@1",
        code="OW_TARGET_TEXT_INVALID",
        construct="block.p",
        msg=msg,
    )


def _walk(root: CarrierNode) -> Iterator[tuple[CarrierNode, str, int]]:
    """Each element below `root` in document order, with its parent's tag and its list depth:
    the number of `<ul>`/`<ol>` that contain it, itself included. One pass, iterative."""
    stack = [(c, root.tag, 0) for c in reversed(list(root.children()))]
    while stack:
        node, parent, outer = stack.pop()
        depth = outer + (node.tag in _LISTS)
        yield node, parent, depth
        stack.extend((c, node.tag, depth) for c in reversed(list(node.children())))


def _local(tag: str) -> str:
    return tag.partition("|")[2] or tag or "nothing"
