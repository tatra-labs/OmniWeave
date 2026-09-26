"""The report types two listed Actions return, and the wire form of each. 18-api-sketch.md 1.4.

18:671: *"Each is what one entry point returns. They exist so no caller parses prose, and every
one of them is also a row in a `schema/*.json` a `--render json` consumer validates against"*.

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
    "DOCTOR_SEVERITIES",
    "SCHEMA_VERSION",
    "SEVERITIES",
    "AddCompleted",
    "AddPending",
    "AddReport",
    "CodeRow",
    "CorporaReport",
    "CorpusCard",
    "DoctorFinding",
    "DoctorReport",
    "Gap",
    "HooksCheckReport",
    "InstallReport",
    "ServeReport",
    "SkillsReport",
    "SurfaceReport",
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

DOCTOR_SEVERITIES: Final[tuple[str, ...]] = ("ok", "warning", "error")
"""`DoctorFinding.severity`'s three members, 18:747's `Literal`, and it is NOT `SEVERITIES`.

The two tuples differ in exactly one member and the difference is not cosmetic. A `Gap` is a
roll-up of `diag` rows that were RECORDED, so its weakest member is `info` -- something was written
down that a reader may want. A `DoctorFinding` is one probe's verdict and every probe returns one,
so its weakest member is `ok` -- nothing to do. A vocabulary whose weakest member means *"a fact"*
and one whose weakest member means *"no finding"* cannot be the same closed set, and folding them
would make `severity == "ok"` unspellable on one side and `severity == "info"` meaningless on the
other.

They are therefore two names in one module, which INV-21 permits and D297 records: one name, one
home is a rule about a NAME, and these are two. What would breach it is a single `SEVERITIES` that
both types annotated against, because then a reader could not tell which three a field admits.
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


@dataclass(frozen=True, slots=True)
class DoctorFinding:
    """One probe's verdict, and the command that clears it. 18:745, `@stable`.

    `fix` is a required string that is empty ONLY at `severity = "ok"` (18:748), which is the same
    shape `AddPending.approve` takes and for the same reason: 10:1436 says `ow doctor`
    *"never fails on a warning"*, so a warning a caller cannot act on is a line of output that
    costs attention and returns nothing. The emptiness rule is not enforced by this type -- a
    dataclass cannot make one field's emptiness depend on another's value without raising at
    construction, which is after the point a report is assembled -- so it is the assembler's, and
    `ow doctor`'s own test is where it is asserted.
    """

    check: str
    detail: str
    severity: Literal["ok", "warning", "error"]
    fix: str


@dataclass(frozen=True, slots=True)
class DoctorReport:
    """What `ow doctor` / `ow_doctor` returns. 18:737, `@stable`.

    **Three tuples and not one with a severity filter**, which is 18:740's shape: `failed` being
    non-empty is what makes `ow doctor` exit 1, and a caller that had to filter a flat list to
    learn that would be re-deriving the exit code the process already computed. The three are
    disjoint by construction and their union is every probe that ran.

    `config_sources` is every resolved key mapped to where it came from, which is
    `ow show-config`'s payload (10:1437, *"prints every resolved value with its source"*) carried
    on this report rather than duplicated into a second one: the question a `doctor` run answers is
    almost always *"which file set this?"*, and a report that made the operator run a second
    command to find out would be answering half of it.

    The two digests are the pair 02 section 8 draws apart: `config_digest` covers every resolved
    value and moves when a comment-only edit changes a file, while `semantic_digest` covers the
    values a decision reads and is what a cache key may contain. Both, because a support thread
    needs to know whether the configuration changed and a cache needs to know whether it MATTERED.
    """

    ok: tuple[DoctorFinding, ...]
    warned: tuple[DoctorFinding, ...]
    failed: tuple[DoctorFinding, ...]
    config_sources: Mapping[str, str]
    config_digest: str
    semantic_digest: str


@dataclass(frozen=True, slots=True)
class HooksCheckReport:
    """What `ow hooks check` returns: the exit (10:1432's 0/1) and 18:2991-2997's table as lines.

    The per-probe facts are `omniweave.hooks.check.Report`'s. They are not carried here because
    importing that module into the registry's type graph costs the surface a dozen modules for a
    report no MCP host is sent: the Action is unlisted, and the schema prints listed tools only.
    """

    exit_code: int
    lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InstallReport:
    """What `ow install` and `ow uninstall` return: the exit code, and the lines they print.

    Human-only Actions (10:53) have no MCP payload to shape, so the report is the transcript
    18:2973-2989 prints and the exit the table at 10:1483-1492 gives it -- 0, 1, or 9 for
    `--check`. The per-path detail is the install receipt's, which is the record; a second copy
    here would be a second place for it to disagree.
    """

    exit_code: int
    lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ServeReport:
    """What `ow serve` returns when its transport closes: 10:1426's 0/1/9 and the lines.

    `SkillsReport`'s shape, for its reason: the row has no `mcp_name`, since starting the transport
    is not a call over it, so there is no MCP payload to shape.
    """

    exit_code: int
    lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SurfaceReport:
    """What `ow surface emit` returns: 10:1430's 0/1 and the lines -- the paths it wrote, or with
    `--check` the findings that fail G25.

    `ServeReport`'s shape, for its reason: the row has no `mcp_name` (10:52's row 1 -- the
    artefacts it writes ARE omniweave's steering surface), so there is no MCP payload to shape.
    """

    exit_code: int
    lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SkillsReport:
    """What `ow skills install` and `ow skills remove` return: 10:1429's 0/1/2 and the lines.

    `InstallReport`'s shape, for its reason: neither Action has an `mcp_name`, so there is no MCP
    payload to shape, and the per-directory record is `skills-lock.json`'s.
    """

    exit_code: int
    lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CodeRow:
    """One `codes.toml` row as a reader receives it. 18:751, `@stable`.

    `ow explain <CODE>` accepts either spelling -- `OW-A-013` or `OW_PARSE_GAP_IN_SCOPE` (10:1438)
    -- and this row carries BOTH, because the two are the same register entry under two indexes and
    a report that returned only the one it was asked for would make a caller that logged the numeric
    unable to search for the symbol. `Gap` already ships both spellings for exactly this reason
    (10:1085's *"both spellings of every code"*), so this is that rule applied to the register
    itself rather than to a roll-up of it.

    `owner_doc` is the plan document that owns the code's block -- `10-interfaces.md` for the
    `OW-A-0xx` range (10:299) -- and it is on the row because the fix for a code whose `fix` is a
    design decision rather than a command is to read the section that allocated it. It is the one
    field with no counterpart in `Gap`, which is a corpus fact; a code is a repository fact.
    """

    numeric: str
    symbol: str
    meaning: str
    fix: str
    owner_doc: str
