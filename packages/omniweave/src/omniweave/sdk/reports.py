"""The report types two listed Actions return, and the wire form of each. 18-api-sketch.md 1.4.

18:671: *"Each is what one entry point returns. They exist so no caller parses prose, and every one of them
is also a row in a `schema/*.json` a `--render json` consumer validates against"*.

This module exists because `ActionSpec.out` is a `type` (10:137) and two of the four listed
Actions declare an `outputSchema`. 10:230 emits `schema/corpora-out-v1.json` and
`schema/add-out-v1.json` *"from the `out` model types"*, and `omniweave_core/store/card.py`
already records where the first one is reflected from: it says `corpora-out-v1.json` is reflected
from `omniweave.sdk:CorpusCard` and not from the stored row. W6.8 wrote that sentence against a
module that did not exist yet; this is it.

## WHY THESE ARE NOT `CorpusCardRow`

`omniweave_core.store.card.CorpusCardRow` is one `corpus_card` row as the TABLE stores it, JSON
columns still JSON. `CorpusCard` is one row as a READER receives it, and the difference is exactly
three fields: `readable`, `reason` and `card_stale`. 10:1092 puts them *"on the row rather than in a
side channel, so a client that iterates `corpora` cannot miss them"*, and they are properties of a
read rather than of a card -- a card cannot record that it was unreadable. Two types, one per side
of that boundary, is not a rival home; one type carrying both would have to lie on one side.

`Gap` is imported rather than re-declared. 18:697 prints it inside this section and
`omniweave_core.store.card` prints it as 18:699's seven fields, because absence gate 9 reads it
inside the store and the store may not import this distribution. One name, one home, imported
upward.

## THE ONE PLACE 10 AND 18 DISAGREE, AND WHICH ONE SHIPPED

`truncated` is declared in both documents and in different places. 18:690 makes it the last field of
`CorpusCard`, *"on the row, not a side channel"*; 10:1097 makes it *"a top-level boolean rather than
a count"* and 10:1040's wire form prints it beside `degradations` and `schema`, outside the
`corpora` array.

**Shipped: the top-level flag, on `CorporaReport` alone.** `truncated` is a property of the LISTING
-- whether `CORPORA_LIST_MAX` cut it off -- and not of any corpus in it, so a per-row copy would
carry the same value on every row and a reader would have no way to know which copy was
authoritative. 10:1097's own argument is about the listing rather than about a corpus: *"a count of
rows nobody can name is not actionable"*. D292 is the entry, and 18:687's field is the one not
taken.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal

from omniweave_core.model import Capabilities, Producer
from omniweave_core.observe.degradation import Degradation
from omniweave_core.store.card import Gap
from omniweave_ports import CostClass

__all__ = [
    "SCHEMA_VERSION",
    "SEVERITIES",
    "AddCompleted",
    "AddPending",
    "AddReport",
    "CorporaReport",
    "CorpusCard",
    "Gap",
]


SCHEMA_VERSION: Final[int] = 1
"""The `schema` field both wire forms carry, 10:1040 and 10:1112.

It is an integer and not a semver string, and it is the payload's own version rather than the
store's `SCHEMA`: 11:1101 makes the MCP tool shape a `RELEASE` MAJOR concern, so this number moves
when a published output property is removed and not when the store migrates.
"""

SEVERITIES: Final[tuple[str, ...]] = ("info", "warning", "error")
"""`Gap.severity`'s three members, 18:699's `Literal`.

`omniweave_core.model.SEVERITIES` carries the same three for `Diag`, which is not a second home: a
gap IS a `diag` roll-up (10:1085, *"`gaps` is derived from the `diag` table"*), so the two agreeing
is the point rather than a duplication. This binding exists so a surface consumer need not import
the document model to name them.
"""


@dataclass(frozen=True, slots=True)
class CorpusCard:
    """One `corpus_card` row plus the three read-time degradations. 18:677, `@stable`.

    Six fields carry more weight than their size suggests (10:1075) and two are worth restating
    here, because a caller who misreads either draws a false conclusion from a true payload:

    - **`achieved` is the MIN over indexed drivers**, not a card's claim -- the corpus's real
      capability floor. Serve reads `doc.achieved` per document for the byte-exactness predicate;
      this aggregate is what an agent uses to decide whether verbatim quoting is possible in this
      corpus at all.
    - **`verbatim_fraction` is printed before any query runs.** 10:1080: at release 1 the office
      path reaches `quote = normalized` and no higher, so a DOCX-only corpus discloses `0.0` here
      *"rather than letting an agent discover it one refused quote at a time"*.

    `abstract` is `None` unless a human ran `ow corpora --summarize`, and `abstract_producer`
    carries the resolved `Producer` when one did (10:1089) -- *"so a reader can tell which model's
    prose they are reading"*. 10:90 is why there is no agent-facing path to writing it.
    """

    name: str
    default: bool
    readable: bool
    reason: str | None
    card_stale: bool
    card_gen: int
    built_at_ns: int
    writer_version: str
    counts: Mapping[str, int]
    formats: Mapping[str, int]
    langs: Mapping[str, int]
    date_range: Mapping[str, str | None]
    outline: tuple[str, ...]
    top_terms: tuple[str, ...]
    achieved: Capabilities
    trust_hist: Mapping[str, int]
    quote_hist: Mapping[str, int]
    verbatim_fraction: float
    restriction_bits: int
    embedding: Mapping[str, Any] | None
    gaps: tuple[Gap, ...]
    abstract: str | None
    abstract_producer: Producer | None


@dataclass(frozen=True, slots=True)
class CorporaReport:
    """`ow_corpora`'s payload: 10:1040's wire form, which is a tuple of cards plus three fields.

    `degradations` is here and not on the card for the same reason `truncated` is: a degradation
    raised while LISTING (a corpus whose file is locked, a card this build cannot read) belongs to
    the read, and 10:1019 owns what happens *"at scale, on a broken store, and on a corpus this
    build cannot read"*. A per-corpus degradation reaches the caller through `readable` and
    `reason`, which are on the row precisely so it cannot be missed.
    """

    corpora: tuple[CorpusCard, ...]
    truncated: bool
    degradations: tuple[Degradation, ...]
    schema: int = SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class AddCompleted:
    """One document `ow_add` finished inside its deadline. 18:722, `@stable`.

    `achieved_origin_span` is the single capability field the report carries, and it is the one an
    agent needs before it quotes: `glyphs` and `exact` support a byte-exact quote, `none` does not.
    The other capability axes are the corpus card's.
    """

    uri: str
    doc_ord: int
    gen: int
    pages: int
    blocks: int
    achieved_origin_span: Literal["exact", "normalized", "none", "glyphs", "pixels"]


@dataclass(frozen=True, slots=True)
class AddPending:
    """One document `ow_add` did NOT run, and the exact command that would. 18:727, `@stable`.

    `approve` is a REQUIRED string, which 18:1527 names as *"the mechanism behind `add` never runs
    billable work implicitly: a deferral the caller cannot authorise is a dead end, and a required
    field is how that becomes unrepresentable"*. It is empty only for `reason = "in_progress"`,
    where there is nothing to approve because nothing is deferred.
    """

    uri: str
    reason: str
    cost_class: CostClass
    est_micros: int
    approve: str


@dataclass(frozen=True, slots=True)
class AddReport:
    """The roster's own report, not a queue receipt. 18:706, `@stable`; wire form at 10:1112.

    **There is no `verdict` field**, and 18:1525 gives the reason: `ow_add` writes the roster rather
    than the queue, so it has no verdict to report -- *"`deadline_reached` plus the four counts plus
    `pending[].reason` say everything a `verdict` enum would have, without inventing a fifth state
    vocabulary"*. `scope_id` is an integer because it is the `ingest_scope` row id and
    `ow queue status --scope <id>` takes it.

    The deadline is `[serve] add_deadline_ms`, default 20,000 (10:1120). `ow_add` always returns
    inside it, with `deadline_reached = True` and everything still in flight under `pending` with
    `reason = "in_progress"` -- because *"a call that blocks until a 900-page scan finishes is a
    call the host kills, after which the agent has no receipt at all and the ingest is still
    running"*.
    """

    scope_id: int
    corpus: str
    discovered: int
    unchanged: int
    queued: int
    skipped: int
    completed: tuple[AddCompleted, ...]
    pending: tuple[AddPending, ...]
    degradations: tuple[Degradation, ...]
    deadline_reached: bool
    schema: int = SCHEMA_VERSION

    @property
    def plan(self) -> tuple[AddPending, ...]:
        """18:715's alias for `pending`, and the charter's own spelling.

        `c.add([...], dry_run=True).plan` is how the charter and 10 section 9.1 write it. One field,
        two names, *"and the alias exists because a dry run's whole content IS the plan"*. A
        property rather than a second field, so the two spellings cannot disagree.
        """
        return self.pending
