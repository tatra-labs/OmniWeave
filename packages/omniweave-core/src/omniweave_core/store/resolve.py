"""`ow_open`'s resolver: an address the caller already holds, to the blocks it names. 10:437-470.

18:346: *"Resolve addresses the caller already holds -- no ranking, no fusion, no absence gates."*
So this is not a Channel and does not run through `retrieve()`. It reads the store directly,
inside the caller's `Snapshot`, and returns block ids in the order they were asked for; the ids
then go through the same `hydrate()` as a query's, so both surfaces carry the same provenance.

## THE LADDER

10:439: *"Five forms, tried **in this order**, first form that *resolves in the store* winning. A
form that parses but does not resolve continues down the ladder; if nothing resolves, the error
names every form that parsed."* `parse()` returns every form a string parses as, in ladder order,
and `resolve_one()` tries them until one resolves. A string can parse as several forms: `d7#412`
is a cite and also a string that could be a URI, so an unresolved cite falls through to form 5 and
the refusal then names both.

| form | spelling | resolves to |
|---|---|---|
| `cite` | `[<corpus>:]d<doc_ord>#<n>` | one block, following `block_history` if it was retired |
| `entity` | `[<corpus>:]e<n>` / `c<n>` / `k<n>` | not built; refused by name (D538) |
| `addr` | `<uri>#p<page>/<ord>` | one block of the head generation |
| `pages` | `<uri>#p<lo>-<hi>`, or `#p<n>` (D539) | every text block on those pages |
| `document` | `<uri>` | every text block of the document |

Both spans come back in `(page, ord)` order.

**A document is named by its URI or by its file name** (D537). 10:452's examples are
`policy.pdf#p14/3` and `policy.pdf`, and the store holds `file:///corpus/policy.pdf`. So an exact
`doc.uri` match is tried first, then the documents whose URI's last path segment is the string.
Two such documents are a refusal listing both, never a choice between them.

## RETIRED CITES

03:1159: *"A retired cite still resolves. `ow open --by-cite` follows `block_history.superseded_by`
and says so in the response. Where `superseded_by IS NULL` the answer is a stated refusal,
`OW-M-030 / OW_CITE_RETIRED`, naming the generation it was retired at and the reason -- never a
silent miss and never a nearby block."* `block_cite` is `UNIQUE(doc_ord, cite)` across
generations, so a retired cite still names exactly one row, and `model.rebind.follow_supersession`
walks the chain. `Located.superseded` carries the sentence the Answer prints.

## LAYERS AND CONTEXT

`layers` bounds what a page range or a document returns, and `context` siblings. A block addressed
by cite or addr is returned in any layer except `hidden`, which 10:471 makes reachable only by
naming it. Context is 10:463's: *"±K sibling Blocks in `(page, ord)` order **within the same
parent**, never crossing a document boundary and never crossing into another `Layer`"*.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from omniweave_core.errors import NotFoundError, OwError, UsageError
from omniweave_core.model.block import BlockId
from omniweave_core.model.rebind import Retire, follow_supersession
from omniweave_core.retrieve.channels import cite_doc_ord, normalise_query_text

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Mapping, Sequence

    from omniweave_core.model.enums import Layer
    from omniweave_core.store.reader import HydratedRow, SqliteReader

__all__ = [
    "EXAMPLES",
    "FORMS",
    "MAX_CONTEXT",
    "MAX_REFS",
    "Located",
    "Missed",
    "Opening",
    "Parsed",
    "fetch",
    "parse",
    "resolve_one",
]

FORMS: Final[tuple[str, ...]] = ("cite", "entity", "addr", "pages", "document")
"""10:443-450's five, in ladder order."""

EXAMPLES: Final[Mapping[str, str]] = {
    "cite": "d7#412",
    "entity": "e118",
    "addr": "policy.pdf#p14/3",
    "pages": "policy.pdf#p12-18",
    "document": "policy.pdf",
}
"""One example each, which 10:452's `OW-A-016` refusal lists. `mcp.tool.ow_open.ref_forms` spells
the same five (10:2497)."""

MAX_REFS: Final[int] = 64
"""10:437's `maxItems`, enforced before any store read (10:946)."""

MAX_CONTEXT: Final[int] = 8
"""10:461's cap on `context`."""

_CORPUS = r"(?:(?P<corpus>[A-Za-z0-9_.-]+):)?"
_CITE: Final = re.compile(_CORPUS + r"(?P<cite>d\d+#\d+)")
_ENTITY: Final = re.compile(_CORPUS + r"(?P<entity>[eck]\d+)")
_ADDR: Final = re.compile(r"(?P<uri>.+)#(?P<addr>p\d+(?:/[A-Za-z0-9]+)+)")
_PAGES: Final = re.compile(r"(?P<uri>.+)#p(?P<lo>\d+)(?:-(?P<hi>\d+))?")
_TEXT_ONLY: Final[str] = "b.text IS NOT NULL"
_MAX_HOPS: Final[int] = 32
"""A bound on one supersession chain. Each hop is a re-parse; thirty-two is corruption."""


@dataclass(frozen=True, slots=True)
class Parsed:
    """One form a ref string parses as. Only the fields that form uses are set."""

    form: str
    corpus: str | None = None
    cite: str | None = None
    uri: str | None = None
    addr: str | None = None
    pages: tuple[int, int] | None = None


@dataclass(frozen=True, slots=True)
class Located:
    """A ref that resolved: the blocks it names, in order, and the context around them."""

    ref: str
    form: str
    block_ids: tuple[int, ...]
    context_ids: frozenset[int] = frozenset()
    doc_ords: frozenset[int] = frozenset()
    superseded: str = ""


@dataclass(frozen=True, slots=True)
class Missed:
    """A ref that did not resolve, and the error the Answer carries for it."""

    ref: str
    error: OwError
    forms: tuple[str, ...] = field(default=())


def parse(ref: str) -> tuple[Parsed, ...]:
    """Every form `ref` parses as, in ladder order. Empty means `OW-A-016`."""
    text = normalise_query_text(ref.strip())
    if not text:
        return ()
    found: list[Parsed] = []
    if matched := _CITE.fullmatch(text):
        found.append(Parsed("cite", corpus=matched["corpus"], cite=matched["cite"]))
    if matched := _ENTITY.fullmatch(text):
        found.append(Parsed("entity", corpus=matched["corpus"]))
    if matched := _ADDR.fullmatch(text):
        found.append(Parsed("addr", uri=matched["uri"], addr=matched["addr"]))
    if matched := _PAGES.fullmatch(text):
        lo = int(matched["lo"])
        hi = int(matched["hi"]) if matched["hi"] else lo
        found.append(Parsed("pages", uri=matched["uri"], pages=(lo, hi)))
    found.append(Parsed("document", uri=text))
    return tuple(found)


def unparseable(ref: str) -> UsageError:
    """10:452's `OW-A-016`, listing the five forms with one example each."""
    forms = "; ".join(f"{form} {EXAMPLES[form]}" for form in FORMS)
    return UsageError(
        f"ref {ref!r} matches none of the five forms ({forms})",
        symbol="OW_REF_UNPARSEABLE",
        fix='ow_open ref="d7#412"',
    )


def resolve_one(
    connection: sqlite3.Connection,
    ref: str,
    *,
    context: int,
    layers: frozenset[int],
    hidden: int,
) -> Located | Missed:
    """One ref down the ladder. `layers` and `hidden` are `enum_val` codes."""
    forms = parse(ref)
    if not forms:
        return Missed(ref, unparseable(ref))
    misses: list[OwError] = []
    for parsed in forms:
        found = _try(connection, ref, parsed, context=context, layers=layers, hidden=hidden)
        if isinstance(found, Located):
            return found
        if found is not None:
            misses.append(found)
    return Missed(ref, _unresolved(ref, forms, misses), forms=tuple(p.form for p in forms))


def _unresolved(ref: str, forms: Sequence[Parsed], misses: Sequence[OwError]) -> OwError:
    """The most specific miss, or one naming every form that parsed (10:440)."""
    if misses:
        return misses[0]
    names = ", ".join(parsed.form for parsed in forms)
    return NotFoundError(
        f"ref {ref!r} parsed as {names} and none of them resolves in this store",
        symbol="OW_ADDR_NOT_FOUND",
        fix='ow_query query="..."   # search for it instead of addressing it',
    )


def _try(
    connection: sqlite3.Connection,
    ref: str,
    parsed: Parsed,
    *,
    context: int,
    layers: frozenset[int],
    hidden: int,
) -> Located | OwError | None:
    """One form. `None` is "did not resolve, try the next form"; an error is a stated refusal."""
    if parsed.form == "cite":
        return _cite(connection, ref, parsed, context=context, hidden=hidden, layers=layers)
    if parsed.form == "entity":
        return UsageError(
            f"ref {ref!r} is an entity, community or claim, and this build resolves blocks only",
            symbol="OW_REF_UNPARSEABLE",
            fix='ow_query query="..."   # the entity\'s name finds its mentions',
        )
    docs = _documents(connection, parsed.uri or "")
    if isinstance(docs, OwError):
        return docs
    if not docs:
        return None
    (doc_ord,) = docs
    if parsed.form == "addr":
        return _addr(
            connection, ref, doc_ord, parsed, context=context, hidden=hidden, layers=layers
        )
    return _span(connection, ref, doc_ord, parsed, layers=layers)


def _documents(connection: sqlite3.Connection, uri: str) -> tuple[int, ...] | OwError:
    """The one document `uri` names: exact URI first, then file name (D537). Two is a refusal."""
    row = connection.execute("SELECT doc_ord FROM doc WHERE uri = ?", (uri,)).fetchone()
    if row is not None:
        return (int(row[0]),)
    if "/" in uri or ":" in uri:
        return ()
    rows = connection.execute(
        "SELECT doc_ord, uri FROM doc WHERE uri = ? OR uri LIKE ? ESCAPE '\\' ORDER BY doc_ord",
        (uri, "%/" + _like(uri)),
    ).fetchall()
    if len(rows) > 1:
        named = ", ".join(str(r[1]) for r in rows[:5])
        return UsageError(
            f"{uri!r} names {len(rows)} documents: {named}",
            symbol="OW_REF_UNPARSEABLE",
            fix=f'ow_open ref="{rows[0][1]}"   # the full uri',
        )
    return tuple(int(r[0]) for r in rows)


def _like(text: str) -> str:
    """`text` as a literal `LIKE` operand."""
    return "".join("\\" + ch if ch in "\\%_" else ch for ch in text)


def _cite(
    connection: sqlite3.Connection,
    ref: str,
    parsed: Parsed,
    *,
    context: int,
    hidden: int,
    layers: frozenset[int],
) -> Located | OwError | None:
    cite = parsed.cite or ""
    doc_ord = cite_doc_ord(cite)
    row = connection.execute(
        "SELECT block_id FROM block WHERE doc_ord = ? AND cite = ?", (doc_ord, cite)
    ).fetchone()
    if row is None:
        return None
    wanted = int(row[0])
    live = _live(connection, wanted)
    note = ""
    if live is None:
        followed = _follow(connection, ref, wanted)
        if not isinstance(followed, tuple):
            return followed
        live, note = followed
    return _single(
        connection, ref, "cite", live, context=context, hidden=hidden, layers=layers, note=note
    )


def _follow(
    connection: sqlite3.Connection, ref: str, block_id: int
) -> tuple[int, str] | OwError | None:
    """The live successor of a retired block and the sentence saying so, or `OW-M-030`.

    Reads the chain one `block_history` row at a time, at most `_MAX_HOPS` of them, and hands it
    to `follow_supersession`, which owns the walk and the cycle refusal.
    """
    chain: list[Retire] = []
    current: int | None = block_id
    while current is not None and len(chain) < _MAX_HOPS:
        row = connection.execute(
            "SELECT block_id, doc_ord, retired_gen, superseded_by, reason FROM block_history "
            "WHERE block_id = ?",
            (current,),
        ).fetchone()
        if row is None:
            break
        chain.append(
            Retire(
                block_id=BlockId(int(row[0])),
                doc_ord=int(row[1]),
                retired_gen=int(row[2]),
                superseded_by=None if row[3] is None else BlockId(int(row[3])),
                reason=str(row[4]),
            )
        )
        current = chain[-1].superseded_by
    if not chain:
        return None
    first = chain[0]
    successor = follow_supersession(chain, BlockId(block_id))
    if successor is None or _live(connection, successor) is None:
        return NotFoundError(
            f"{ref} was retired at generation {first.retired_gen} ({first.reason}) and has no "
            f"defensible successor",
            symbol="OW_CITE_RETIRED",
            fix='ow_query query="..."   # search for what the cite said; no nearby block is given',
        )
    new = connection.execute("SELECT cite FROM block WHERE block_id = ?", (successor,)).fetchone()
    return successor, (
        f"{ref} was retired at generation {first.retired_gen} ({first.reason}); shown is its "
        f"successor {new[0]}"
    )


def _live(connection: sqlite3.Connection, block_id: int) -> int | None:
    row = connection.execute(
        "SELECT block_id FROM ow_block_head WHERE block_id = ?", (block_id,)
    ).fetchone()
    return None if row is None else int(row[0])


def _addr(
    connection: sqlite3.Connection,
    ref: str,
    doc_ord: int,
    parsed: Parsed,
    *,
    context: int,
    hidden: int,
    layers: frozenset[int],
) -> Located | OwError | None:
    row = connection.execute(
        "SELECT block_id FROM ow_block_head WHERE doc_ord = ? AND addr = ?", (doc_ord, parsed.addr)
    ).fetchone()
    if row is None:
        return NotFoundError(
            f"no block at {parsed.addr} in the head generation of {parsed.uri}",
            symbol="OW_ADDR_NOT_FOUND",
            fix=f'ow_open ref="{parsed.uri}#p{parsed.addr[1:].split("/", 1)[0]}"'
            if parsed.addr
            else 'ow_open ref="<uri>"',
        )
    return _single(
        connection, ref, "addr", int(row[0]), context=context, hidden=hidden, layers=layers
    )


def _single(
    connection: sqlite3.Connection,
    ref: str,
    form: str,
    block_id: int,
    *,
    context: int,
    hidden: int,
    layers: frozenset[int],
    note: str = "",
) -> Located | OwError:
    """One addressed block, its context, and the `hidden` rule for an addressed block."""
    row = connection.execute(
        "SELECT doc_ord, parent_id, layer, page, ord FROM ow_block_head WHERE block_id = ?",
        (block_id,),
    ).fetchone()
    doc_ord, parent, layer = int(row[0]), row[1], int(row[2])
    if layer == hidden and hidden not in layers:
        return UsageError(
            f"{ref} is on the hidden layer, which is returned only when asked for by name",
            symbol="OW_REF_UNPARSEABLE",
            fix=f'ow_open ref="{ref}" layers=["hidden"]',
        )
    before, after = _siblings(connection, block_id, parent, layer, context) if context else ((), ())
    ordered = (*before, block_id, *after)
    return Located(
        ref=ref,
        form=form,
        block_ids=ordered,
        context_ids=frozenset((*before, *after)),
        doc_ords=frozenset({doc_ord}),
        superseded=note,
    )


def _siblings(
    connection: sqlite3.Connection, block_id: int, parent: object, layer: int, k: int
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """±K text-bearing siblings under the same parent and in the same layer, `(page, ord)` order."""
    if parent is None:
        return (), ()
    rows = connection.execute(
        f"SELECT b.block_id FROM ow_block_head b WHERE b.parent_id = ? AND b.layer = ? "  # noqa: S608
        f"AND ({_TEXT_ONLY} OR b.block_id = ?) ORDER BY b.page, b.ord, b.block_id",
        (parent, layer, block_id),
    ).fetchall()
    ids = [int(r[0]) for r in rows]
    at = ids.index(block_id)
    return tuple(ids[max(0, at - k) : at]), tuple(ids[at + 1 : at + 1 + k])


def _span(
    connection: sqlite3.Connection,
    ref: str,
    doc_ord: int,
    parsed: Parsed,
    *,
    layers: frozenset[int],
) -> Located | None:
    """A page range or a whole document: its text blocks in `layers`, in `(page, ord)` order."""
    where = ["b.doc_ord = ?", _TEXT_ONLY, f"b.layer IN ({', '.join('?' * len(layers))})"]
    params: list[object] = [doc_ord, *sorted(layers)]
    if parsed.pages is not None:
        where.append("b.page BETWEEN ? AND ?")
        params.extend(parsed.pages)
    rows = connection.execute(
        f"SELECT b.block_id FROM ow_block_head b WHERE {' AND '.join(where)} "  # noqa: S608
        f"ORDER BY b.page, b.ord, b.block_id",
        params,
    ).fetchall()
    if not rows:
        return None
    return Located(
        ref=ref,
        form=parsed.form,
        block_ids=tuple(int(r[0]) for r in rows),
        doc_ords=frozenset({doc_ord}),
    )


@dataclass(frozen=True, slots=True)
class Opening:
    """Everything `pack_open()` reads, from ONE snapshot: the ladder's results and their rows.

    `rows` is keyed by `block_id` and holds every block any `Located` names, hydrated by the same
    `hydrate()` a query uses, so an opened block and a retrieved one carry the same provenance.
    `freshness` is `execute.freshness()` over the corpus-wide `Coverage`, the roll-up a query's
    Verdict prints; `open` has no Verdict and still says whether the store matches the disk.
    """

    results: tuple[Located | Missed, ...]
    rows: Mapping[int, HydratedRow]
    indexed_blocks: int
    generation: int
    freshness: str


def fetch(
    reader: SqliteReader, refs: Sequence[str], *, context: int, layers: frozenset[Layer]
) -> Opening:
    """Resolve, hydrate and read coverage inside one `Snapshot` (ST2, 07:2758)."""
    from omniweave_core.retrieve.execute import freshness  # noqa: PLC0415 -- store -> retrieve
    from omniweave_core.store.types import Filters  # noqa: PLC0415

    with reader.snapshot() as s:
        results = reader.resolve_refs(s, refs, context=context, layers=layers)
        wanted = list(
            dict.fromkeys(
                block_id
                for found in results
                if isinstance(found, Located)
                for block_id in found.block_ids
            )
        )
        rows = reader.hydrate(s, wanted)
        coverage = reader.coverage(s, Filters())
        generation = s.generation
    return Opening(
        results=results,
        rows={row.block_id: row for row in rows},
        indexed_blocks=reader.capabilities().live_blocks,
        generation=generation,
        freshness=freshness(coverage),
    )
