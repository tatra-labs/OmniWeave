"""The input type of every listed Action -- one dataclass per published `inputSchema`.

`ActionSpec.inp` is a `type` (10:137), and four of the seven generated artefacts read it: the MCP
tool schema (10:208), the CLI argparse tree (10:210 -- *"`cli` tuples plus `inp` fields"*), the SDK
stubs (10:211) and `_DECLARED_ARG_KEYS` (10:500). A surface that declared its parameters in seven
places would be the defect INV-20 exists to prevent, arrived at from the inside, so the parameters
are declared once, here, as ordinary frozen dataclasses.

## DECLARATION ORDER IS THE PUBLISHED ORDER

10:231 fixes it: *"schema properties in declaration order (which is `dataclasses.fields` order,
itself stable)"*. Every class below is therefore written in the order 18:1258's published
`inputSchema` prints its properties, and reordering a field is a wire change that G25's byte-diff
will show. That is the whole reason the order is stated rather than left to a sort: a sorted schema
would put `corpus` before `query` and bury the one required parameter under an optional one.

## WHAT IS NOT HERE, AND WHY EACH ABSENCE IS DELIBERATE

- **No `refs` and no `schema` on `QueryIn`** (18:1322). Reference-shaped tokens are lifted into
  `Query.refs` by 07 section 5.2's sanitisation before the residue reaches FTS5, so an agent that
  pastes `d7#412` inside a question already has the identity channel; and a JSON Schema is an
  ingest-time fact, which is why `--schema` is a flag on `ow add`. 18:980 records that an earlier
  draft put it on `query` and calls that *"the single most consequential error a caller could
  inherit from an API reference"*.
- **No `corpora` list anywhere.** 10:388: *"One query addresses one corpus"*. The cross-corpus
  fan-out is the CLI's `--corpus a,b` and the SDK's `omniweave.corpora([...])`, and it is not
  reachable from `ow_query`, *"because a listed tool that silently fans out hides the
  incomparability of cross-corpus BM25 scores"*.
- **No `want_impact` on `OpenIn`** (18:1365). The MCP handler sets it by default when the ref is a
  single block, so one citation gets `ow:impact` without a knob and a 64-ref batch does not pay 192
  joins. A parameter would be a knob for a decision the arity already makes.
- **No `k`, `mode` or `fail_on`.** Those are `ow query` CLI flags (18:910). `want` is a packing
  preset on the surface and *"never changes `Query.mode`"* (10:420), which the planner owns.

## THE BOUNDS ARE CONSTANTS, AND ONE OF THEM IS IMPORTED

Every numeric bound the published schema prints is a `Final` here, so the generator reads the same
integer the handler enforces -- except `HARD_CEILING`, which already has a home in
`omniweave_core.answer.budget` (18:1729, *"one ceiling for every tool"*). `max_chars`' published
`maximum` is that constant and not a copy of it: INV-21 gives a name one home, and a surface that
re-spelled `24_000` would be a second one that drifts silently the day the packing ceiling moves.

A dataclass field carries no bound -- `context: int` does not say 0..8. The bounds live beside the
fields as constants because two consumers need them as values rather than as annotations: the schema
generator prints them, and the handler enforces them *"before any store read"* (10:379). A
validating type would satisfy neither; it would raise at construction, which is after the point
10:453 requires the check to happen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from omniweave_core.answer.budget import HARD_CEILING as _HARD_CEILING

if TYPE_CHECKING:
    from omniweave.route import RouteHints

__all__ = [
    "CONTEXT_DEFAULT",
    "CONTEXT_MAX",
    "CONTEXT_MIN",
    "CORPORA_DETAILS",
    "HARD_CEILING",
    "MAX_CHARS_MIN",
    "QUERY_MAX_CHARS",
    "REF_MAX",
    "SOURCE_MAX",
    "WANTS",
    "AddIn",
    "CorporaIn",
    "OpenIn",
    "QueryIn",
]


QUERY_MAX_CHARS: Final[int] = 4096
"""`ow_query`'s `query`, 10:374, enforced BEFORE any store read.

10:379 gives two reasons and only the first is jcodemunch's: an unbounded string forces a full FTS5
scan, and *"a 4,096-character question is not a question, it is a pasted document, and the right
answer to it is `ow_add`"*. Over the cap is `OW-A-008`, a success-shaped Answer whose `ow:blocking`
says so -- not a protocol error, because the caller asked a legible question badly rather than
issuing an illegible call.
"""

REF_MAX: Final[int] = 64
"""`ow_open`'s `ref` array bound, 18:1337's `maxItems`, enforced before any store read (10:453)."""

SOURCE_MAX: Final[int] = 256
"""`ow_add`'s `source` array bound, 10:485 and 18:1359's `maxItems`."""

CONTEXT_MIN: Final[int] = 0
CONTEXT_MAX: Final[int] = 8
CONTEXT_DEFAULT: Final[int] = 1
"""`ow_open`'s sibling window, 10:461. Zero is a legal request and means *"no siblings"*."""

MAX_CHARS_MIN: Final[int] = 1000
"""The published `minimum` on both retrievers' `max_chars`, 18:1290.

There is no `MAX_CHARS_MAX` constant beside it. The published `maximum` is `HARD_CEILING`, bound
below, and the effective value is `min(requested, tier.max_chars, HARD_CEILING)` (10:478) -- a
request above the tier is honoured at the tier and disclosed, never refused.
"""

HARD_CEILING: Final[int] = _HARD_CEILING
"""The published `maximum`, re-exported rather than re-spelled. 18:1729, *"one ceiling for every
tool"*.

It is the same object `omniweave_core.answer.budget` defines, bound here so the schema generator
reads the published bounds from one module without importing the packer. `omniweave_core.retrieve`
re-exports `RRF_K` and `SCORER_VERSION` on the same terms and for the same reason (07:1382): a
binding is not a second home, and `24_000` written twice would be."""

WANTS: Final[tuple[str, ...]] = ("passages", "table", "fields", "outline", "related")
"""`want`'s five members in 18:1275's published order, which is 10:424's table order.

10:434: an unknown value is a validation error naming the five, *"never a silent fall-back to
`passages`, because a caller who asked for `table` and got prose has been lied to"*. The default is
the first member, which is why the tuple is ordered rather than a frozenset.
"""

CORPORA_DETAILS: Final[tuple[str, ...]] = ("list", "card", "coverage", "actions")
"""`ow_corpora`'s `detail`, 18:1352. `actions` is how an agent discovers the narrow-Action catalog
(18:1367), which is what makes an unlisted Action reachable without listing it."""


@dataclass(frozen=True, slots=True)
class QueryIn:
    """`ow_query` / `ow query`. 18:1258's published `inputSchema`, in its published order.

    `route_hints` is the one non-scalar field and it is `omniweave.route.RouteHints` rather than a
    surface type of its own. 05:2019 makes that type a RESTRICTION -- it has no `budget`, no
    `egress` and no `licence` field -- which is *"what makes it safe to accept from an agent over
    MCP or the SDK"*. A second, surface-local hint shape would be a rival home for a type whose
    safety property is exactly its field list.

    The published object exposes three of `RouteHints`' five fields (`lane`, `max_rung`,
    `deadline_ms`) under `additionalProperties: false`. That is a narrowing the schema generator
    performs, not a different type: 18:1322 strikes `schema` from this surface by name, and
    `prefer_capability` is a driver-selection hint with no agent-facing meaning.
    """

    query: str
    corpus: str | None = None
    scope: str | None = None
    want: str = WANTS[0]
    route_hints: RouteHints | None = None
    max_chars: int | None = None


@dataclass(frozen=True, slots=True)
class OpenIn:
    """`ow_open` / `ow open`. 18:1335's published `inputSchema`.

    `ref` is `str | tuple[str, ...]` because the schema is a `oneOf` of a string and an array, and
    the singular form is the common one: an agent resolving one citation should not have to wrap it.
    The five ref forms and their resolution order are 10:437's and are enforced by the handler, not
    by this type -- a form that parses but does not resolve continues down the ladder, which is a
    store fact and cannot be decided at construction.

    `layers` is the only path to `Layer.HIDDEN` (10:468), whose `WORTH_LAYER` weight is `0.0`, so no
    other route can pack it into an Answer. It is `advanced` and therefore stripped from the compact
    schema, which 10:471 argues is correct rather than merely cheap: *"an agent that needs hidden
    layers knows it does"*.
    """

    ref: str | tuple[str, ...]
    corpus: str | None = None
    context: int = CONTEXT_DEFAULT
    layers: tuple[str, ...] | None = None
    max_chars: int | None = None


@dataclass(frozen=True, slots=True)
class CorporaIn:
    """`ow_corpora` / `ow corpora`. 18:1349's published `inputSchema`.

    Two optional parameters and no `advanced` member, which is why 10:356 records that this tool is
    *"unchanged by compaction"* -- and why it is still the second-cheapest of the four at 189 tokens
    despite carrying the longest description in the set. Prose compresses at ~3.2 chars/token and
    JSON Schema does not.

    `summarize` is absent by construction and not by omission. 10:90 works the decision: the
    abstract is returned by this tool's own payload, so *"an agent that could write it could write
    the prose its own next call reads"*. It is the CLI's `ow corpora --summarize`, one flag on the
    human surface, and `abstract_producer` records which model wrote it when one did.
    """

    corpus: str | None = None
    detail: str = CORPORA_DETAILS[0]


@dataclass(frozen=True, slots=True)
class AddIn:
    """`ow_add` / `ow add`. 18:1356's published `inputSchema`.

    The one listed writer, and the parameter that is NOT here is why it survives 10:54's row 2:
    there is no `allow_cost`. 10:1131 states it -- *"`ow add --allow-cost <micros>` is the approval
    path and is CLI-only, because `RouteHints` correctly has no budget field"*. Billable work
    defers rather than spends, and the response carries the pending cost with the exact command that
    approves it, which is the `Degradation`-shaped deferral row 2 asks for.

    `dry_run` is `advanced` and returns the same `add-out-v1` shape with `queued = 0` and a
    populated `pending` (10:487), *"so a caller can price an ingest without starting one"*.
    """

    source: str | tuple[str, ...]
    corpus: str | None = None
    dry_run: bool = False
