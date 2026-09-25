"""`ow_corpora` over `tools/call`: what exists, what is in it, and what is missing. 10 section 4.

10:1003: *"An agent must be able to answer *what exists, what is in it, and what is missing from
it* without reading anything."* The four `detail` modes are 10:1007-1012's four budgets:

| `detail` | answers | source here |
|---|---|---|
| `list` (default) | what can this server read? | `[corpora]`, and each store's newest card |
| `card` | is the answer likely to be in here? | one store's `corpus_card` row, whole |
| `coverage` | `ow_query` said absent -- is that true? | the card's `gaps` and a live `Coverage` |
| `actions` | what else can this server do? | not served (D551) |

## THE SHAPE ON THE WIRE

One text content block holding one JSON object, 10:1044's `{"corpora": [...], "truncated": ...,
"degradations": [...], "schema": 1}`. There is no `outputSchema` in `tools/list` and so no
`structuredContent` (D549); `schema/corpora-out-v1.json` is the `--render json` contract. The
object is compact JSON, because `list` is budgeted at ~40 characters a corpus (10:1009).

## THE THREE READ-TIME DEGRADATIONS, ON THE ROW

10:1092: *"`readable` / `reason` / `card_stale` are section 4.1's three degradations, on the row
rather than in a side channel, so a client that iterates `corpora` cannot miss them."*
- A store that will not open is listed with `readable: false` and its own message, *"never omitted
  and never fatal"* (10:1031-1032).
- A store with no card, or a card older than its newest `doc.gen`, is `card_stale: true`, and
  the command that refreshes it is in `degradations`. The card is never rebuilt here: *"a stale card
  is never presented as current, and it is never silently recomputed inside a read call"*
  (10:1039). Nothing in this build writes a card yet (D550), so every real corpus reads stale.

## WHAT A LIST ROW HOLDS

`corpora-out-v1.json` requires twenty-three fields of every entry, and a full entry is ~1,200
characters: sixty-four of them are not 10:1025's *"~2,600 characters"*. So a `list` row carries the
identity, the three degradations and the counts, and `card` carries the whole entry (D552).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.errors import OwError
from omniweave_core.store import card as store_card
from omniweave_core.store import reader as store_reader
from omniweave_core.store import sqlite as store_sqlite
from omniweave_core.store.types import Filters

from omniweave_serve.answers import refusal, text_result

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from omniweave_core.store.card import CardRead, CorpusCardRow

__all__ = ["CORPORA_LIST_MAX", "CORPORA_TOOL", "DETAILS", "SCHEMA_VERSION", "respond"]

CORPORA_TOOL: Final[str] = "ow_corpora"
DETAILS: Final[tuple[str, ...]] = ("list", "card", "coverage", "actions")
"""10:1007-1012's four modes, in the table's order. `list` is the default (10:2505)."""

CORPORA_LIST_MAX: Final[int] = 64
"""10:1023: `detail="list"` is capped at sixty-four entries, and the cut sets `truncated`."""

SCHEMA_VERSION: Final[int] = 1
"""10:1071's `"schema": 1`."""

_ARGUMENTS: Final[frozenset[str]] = frozenset({"corpus", "detail"})
_WILDCARD: Final[str] = "*"


@dataclass(frozen=True, slots=True)
class _Store:
    """One declared corpus and what its store said."""

    name: str
    default: bool
    read: CardRead


def respond(
    arguments: Mapping[str, Any],
    *,
    corpora: Mapping[str, Path],
    default: str | None,
    now_ns: int,
) -> dict[str, Any]:
    """The `tools/call` result for one set of `ow_corpora` arguments. Never `isError` (10:920)."""
    refused = _check(arguments)
    if refused is not None:
        return refused
    detail = arguments.get("detail", "list")
    named = arguments.get("corpus")
    if detail == "actions":
        return refusal(
            "",
            "detail=actions reads every Action's summary and decision, which no file this "
            "server loads carries",
            "ow_corpora detail=list",
        )
    if detail == "list":
        return _json(_listed(corpora, default, named))
    chosen = _one(corpora, named or default, detail)
    if isinstance(chosen, dict):
        return chosen
    name, path = chosen
    entry = _Store(name=name, default=name == default, read=store_card.inspect(path))
    if detail == "card":
        return _json(_document([_full(entry)], [entry]))
    return _json(_coverage(entry, path, now_ns))


def _check(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    """Every argument refusal, before any store is opened (10:946)."""
    unknown = sorted(set(arguments) - _ARGUMENTS)
    if unknown:
        return refusal(
            "",
            f"ow_corpora takes no argument {', '.join(unknown)}; its arguments are corpus, detail",
            "call ow_corpora with the arguments tools/list publishes",
        )
    detail = arguments.get("detail", "list")
    if detail not in DETAILS:
        return refusal("", f"detail must be one of {', '.join(DETAILS)}", "omit detail")
    corpus = arguments.get("corpus")
    if corpus is not None and (not isinstance(corpus, str) or not corpus):
        return refusal("", "corpus must be a non-empty string", "omit corpus")
    return None


def _one(
    corpora: Mapping[str, Path], named: object, detail: str
) -> tuple[str, Path] | dict[str, Any]:
    """The one corpus `card` and `coverage` read.

    10:1027-1028: *"accept exactly one corpus and refuse a wildcard"*.
    """
    declared = ", ".join(sorted(corpora)) or "none"
    if named is None:
        return refusal(
            "OW-A-001" if not corpora else "",
            f"detail={detail} reads one corpus and none was named or is the default; "
            f"declared: {declared}",
            f'ow_corpora detail={detail} corpus="<name>"',
        )
    if str(named).endswith(_WILDCARD):
        return refusal(
            "",
            f"detail={detail} accepts exactly one corpus and refuses a wildcard",
            f'ow_corpora detail=list corpus="{named}"',
        )
    path = corpora.get(str(named))
    if path is None:
        return refusal(
            "OW-A-002",
            f"corpus {named!r} is not in [corpora]; declared: {declared}",
            "ow_corpora",
        )
    return str(named), path


def _listed(corpora: Mapping[str, Path], default: str | None, named: object) -> dict[str, Any]:
    """10:1023-1024's list: `default` first, then `card_gen` descending, then name, at most 64."""
    names = sorted(corpora)
    if isinstance(named, str):
        prefix = named.removesuffix(_WILDCARD)
        names = (
            [n for n in names if n.startswith(prefix)]
            if named.endswith(_WILDCARD)
            else [n for n in names if n == named]
        )
    stores = [
        _Store(name=name, default=name == default, read=store_card.inspect(corpora[name]))
        for name in names
    ]
    stores.sort(key=lambda s: (not s.default, -_gen(s.read.row), s.name))
    shown = stores[:CORPORA_LIST_MAX]
    return _document([_row(entry) for entry in shown], shown, truncated=len(stores) > len(shown))


def _gen(row: CorpusCardRow | None) -> int:
    return -1 if row is None else row.card_gen


def _document(
    rows: list[dict[str, Any]], stores: list[_Store], *, truncated: bool = False
) -> dict[str, Any]:
    """10:1044's envelope, with a refresh command for every stale card."""
    degradations = [
        f"card_stale: {entry.name}: ow index update --corpus {entry.name}"
        for entry in stores
        if entry.read.readable and entry.read.stale
    ]
    return {
        "corpora": rows,
        "truncated": truncated,
        "degradations": degradations,
        "schema": SCHEMA_VERSION,
    }


def _head(entry: _Store) -> dict[str, Any]:
    """The identity and the three degradations, which every row carries."""
    row = entry.read.row
    return {
        "name": entry.name,
        "default": entry.default,
        "readable": entry.read.readable,
        "reason": entry.read.reason,
        "card_stale": entry.read.readable and entry.read.stale,
        "card_gen": 0 if row is None else row.card_gen,
    }


def _counts(row: CorpusCardRow | None) -> dict[str, int]:
    """10:1051's seven counts, or none: a card that does not exist has no counts to show."""
    if row is None:
        return {}
    return {
        "docs_indexed": row.docs_indexed,
        "docs_discovered": row.docs_discovered,
        "docs_partial": row.docs_partial,
        "docs_failed": row.docs_failed,
        "pages": row.pages,
        "blocks": row.blocks,
        "bytes": row.bytes,
    }


def _row(entry: _Store) -> dict[str, Any]:
    """A `list` row: identity, degradations, counts and the honesty number (D552)."""
    row = entry.read.row
    out = {**_head(entry), "counts": _counts(row)}
    if row is not None:
        out["verbatim_fraction"] = row.verbatim_fraction
    return out


def _full(entry: _Store) -> dict[str, Any]:
    """A `card` entry: every field of 10:1047's entry, in its order."""
    row = entry.read.row
    head = _head(entry)
    if row is None:
        return {**head, "counts": {}}
    return {
        **head,
        "built_at_ns": row.built_at_ns,
        "writer_version": row.writer_version,
        "counts": _counts(row),
        "formats": json.loads(row.formats_json),
        "langs": json.loads(row.langs_json),
        "date_range": json.loads(row.date_range_json),
        "outline": json.loads(row.outline_json),
        "top_terms": json.loads(row.top_terms_json),
        "achieved": json.loads(row.achieved_json),
        "trust_hist": json.loads(row.trust_hist_json),
        "quote_hist": json.loads(row.quote_hist_json),
        "verbatim_fraction": row.verbatim_fraction,
        "restriction_bits": row.restriction_bits,
        "embedding": None if row.embedding_json is None else json.loads(row.embedding_json),
        "gaps": json.loads(row.gaps_json),
        "abstract": row.abstract,
        "abstract_producer": entry.read.producer,
    }


def _coverage(entry: _Store, path: Path, now_ns: int) -> dict[str, Any]:
    """10:1011's `coverage`: the card's `gaps` and a live read of what absence gates 4-9 read."""
    head = _head(entry)
    row = entry.read.row
    gaps = [] if row is None else json.loads(row.gaps_json)
    live: dict[str, Any] | None = None
    reason = entry.read.reason
    if entry.read.readable:
        try:
            live = _live(path, now_ns)
        except OwError as error:
            reason = str(error)
    rows = [{**head, "reason": reason, "gaps": gaps, "coverage": live}]
    return _document(rows, [entry])


def _live(path: Path, now_ns: int) -> dict[str, Any]:
    """`Reader.coverage()` over the whole corpus, in one snapshot."""
    connection = store_sqlite.connect_readonly(path)
    try:
        reader = store_reader.SqliteReader(connection, now_ns=now_ns)
        with reader.snapshot() as s:
            coverage = reader.coverage(s, Filters())
    finally:
        connection.close()
    return {
        "discovered": coverage.discovered,
        "indexed": coverage.indexed,
        "partial": coverage.partial,
        "failed": coverage.failed,
        "skipped": coverage.skipped,
        "complete": coverage.complete,
        "scope_rows": coverage.scope_rows,
        "pending_work": coverage.pending_work,
        "stale_units": coverage.stale_units,
        "unreadable_units": coverage.unreadable_units,
        "gaps": [
            {
                "gate": gap.gate,
                "detail": gap.detail,
                "fix": gap.fix,
                "codes": list(gap.diag_codes),
            }
            for gap in coverage.gaps
        ],
    }


def _json(document: Mapping[str, Any]) -> dict[str, Any]:
    """One text block of compact JSON (D549)."""
    return text_result(json.dumps(document, ensure_ascii=False, separators=(",", ":")))
