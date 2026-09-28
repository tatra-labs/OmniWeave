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

## THE DOCUMENT IS CORE'S

Since W7.8j the three documents are built by `omniweave_core.store.card` (`corpora_list`,
`corpora_card`, `corpora_coverage`), and this module keeps what is the server's alone: the argument
refusals and the one text block. `ow corpora` builds the same documents, so the CLI and the server
cannot drift (SV19, 10:101-102), and neither imports the other (02:356).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.store import card as store_card

from omniweave_serve.answers import refusal, text_result

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

__all__ = ["CORPORA_LIST_MAX", "CORPORA_TOOL", "DETAILS", "SCHEMA_VERSION", "respond"]

CORPORA_TOOL: Final[str] = "ow_corpora"
DETAILS: Final[tuple[str, ...]] = ("list", "card", "coverage", "actions")
"""10:1007-1012's four modes, in the table's order. `list` is the default (10:2505)."""

CORPORA_LIST_MAX: Final[int] = store_card.CORPORA_LIST_MAX
"""10:1023's cap. The document is `store.card`'s since W7.8j, so `ow corpora` prints it too."""

SCHEMA_VERSION: Final[int] = store_card.CORPORA_SCHEMA_VERSION
"""10:1071's `"schema": 1`."""

_ARGUMENTS: Final[frozenset[str]] = frozenset({"corpus", "detail"})


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
        return _json(store_card.corpora_list(corpora, default=default, named=named))
    chosen = _one(corpora, named or default, detail)
    if isinstance(chosen, dict):
        return chosen
    name, path = chosen
    if detail == "card":
        return _json(store_card.corpora_card(name, path, default=default))
    return _json(store_card.corpora_coverage(name, path, default=default, now_ns=now_ns))


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
    if str(named).endswith(store_card.WILDCARD):
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


def _json(document: Mapping[str, Any]) -> dict[str, Any]:
    """One text block of compact JSON (D549)."""
    return text_result(json.dumps(document, ensure_ascii=False, separators=(",", ":")))
