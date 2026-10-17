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
    "ArtifactListing",
    "ArtifactsReport",
    "AssetListing",
    "AssetsReport",
    "BackReport",
    "CodeRow",
    "CompileReport",
    "ConstructBake",
    "ConstructListing",
    "ConstructsReport",
    "CorporaReport",
    "CorpusCard",
    "CostListing",
    "CostReport",
    "DoctorFinding",
    "DoctorReport",
    "EvalBlessReport",
    "EvalPublishReport",
    "EvalReleaseCheckReport",
    "EvalReleaseFinding",
    "Gap",
    "GraphDoctorReport",
    "HooksCheckReport",
    "InstallReport",
    "NormalizeReport",
    "NormalizedRow",
    "OutCheckReport",
    "RestrictedItem",
    "ScaffoldReport",
    "ScaffoldUnit",
    "ServeReport",
    "SkillsReport",
    "SlotOwner",
    "SlotUser",
    "StampReport",
    "StampedUnit",
    "SurfaceReport",
    "TargetListing",
    "TargetsReport",
    "VerifiedClass",
    "VerifyReport",
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

    - **`achieved` is `None` for a corpus with no indexed document** (D860), as
      `store.card.capability_floor()` returns it and `ow_corpora` has always printed it: the
      bottom of every ladder would claim the corpus incapable rather than unread.
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
    achieved: Capabilities | None
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
    vocabulary"*. `scope_id` is the `ingest_scope` row's id, which `ow queue status --scope <id>`
    takes. It is `str | None` (D862): `ingest_scope.scope_id` is `TEXT`, D555's prefix of the one
    directory added, and `null` when the sources were not one directory -- what `ow add` and
    `ow_add` have always emitted, against an `int` the type had said.

    The deadline is `[serve] add_deadline_ms`, default 20,000 (10:1120). `ow_add` always returns
    inside it, with `deadline_reached = True` and everything still in flight under `pending` with
    `reason = "in_progress"` -- because *"a call that blocks until a 900-page scan finishes is a
    call the host kills, after which the agent has no receipt at all and the ingest is still
    running"*.
    """

    scope_id: str | None
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
class GraphDoctorReport:
    """What `ow graph doctor` returns: `DoctorReport`'s three tuples, for the graph alone. D702.

    06:2519 prints the verb, *"Pass-level operability"*, and 15:1561 makes it a subsystem doctor
    that `ow doctor` names rather than re-runs. The shape is `DoctorReport`'s without the
    configuration, for the same reason: `failed` being non-empty is the exit 1, a warning never
    fails, and the three are disjoint and their union is every check that ran.
    """

    ok: tuple[DoctorFinding, ...]
    warned: tuple[DoctorFinding, ...]
    failed: tuple[DoctorFinding, ...]


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


@dataclass(frozen=True, slots=True)
class TargetListing:
    """One artefact kind this deployment knows: what `ow out targets` prints a row of. D761.

    `omniweave_core.out.card.TargetRow`'s fields, plus `enabled`: whether `[targets] enabled`
    lists the kind (09-generation.md section 1's artefact-kind allowlist). It is a separate class
    so the registry's type graph does not import `omniweave_core.out`, the reason
    `HooksCheckReport` gives for the same arrangement.
    """

    target: str
    driver: str
    implemented: bool
    reason: str
    enabled: bool
    determinism: tuple[str, ...]
    carrier: str
    il: str
    fidelity: str
    laws: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TargetsReport:
    """What `ow_targets` / `ow out targets` returns: every compile card, one row each. D761.

    10-interfaces.md's `full` roster: "which artefact kinds this deployment can compile, and their
    determinism class". A kind can compile when it is `implemented` and `enabled`. Each row says
    which of the two is missing, so a `video` row names its reason rather than vanishing.
    """

    targets: tuple[TargetListing, ...]


@dataclass(frozen=True, slots=True)
class ArtifactListing:
    """One sealed artefact generation, as `ow out list` prints it. D769.

    10's roster row names three things, and they are all here: the artefact, its gate
    status, and `read_back_doc_ord`, the foreign key that closes the loop. The digests are
    the row's own and are `ow out verify`'s business, so they are not repeated.
    """

    slug: str
    artifact_gen: int
    parent_artifact_gen: int | None
    origin: str
    target: str
    compile_driver: str
    delivery: str
    gate_status: str
    media_type: str
    path: str
    byte_len: int
    restriction_bits: int
    read_back_doc_ord: int | None
    sealed_at_ns: int


@dataclass(frozen=True, slots=True)
class ArtifactsReport:
    """What `ow_artifacts` / `ow out list` returns: one corpus's sealed artefacts. D769."""

    corpus: str
    artifacts: tuple[ArtifactListing, ...]


@dataclass(frozen=True, slots=True)
class OutCheckReport:
    """What `ow out check` decides: the stage, the gate status and the exit. D766.

    The findings are `validation/<stage>.json`'s, at `report_path`. `--render json` prints
    that whole document (09 section 4.2), so this is the summary an SDK caller reads, and
    the status is returned, never raised (10 section 9.3).
    """

    stage: str
    target: str
    status: str
    exit: int
    report_path: str
    errors: int
    warnings: int
    infos: int


@dataclass(frozen=True, slots=True)
class RestrictedItem:
    """One barred source the restriction aggregate named: an asset or a cited block. D773."""

    what: str
    id: int
    bits: int
    cite: str | None


@dataclass(frozen=True, slots=True)
class CompileReport:
    """What `ow out compile` decided, and the artefact it sealed when it sealed one. D773.

    A closed gate is a status and an exit, never a raise (10 section 9.3): `exit` is
    09 section 15's, `path` is `None` and nothing was lowered. `hit` is the lookup-before-build's
    answer: the bytes are an earlier compile's, placed again and not rebuilt (OUT12).
    """

    target: str
    slug: str
    delivery: str
    status: str
    exit: int
    artifact_gen: int | None = None
    path: str | None = None
    sha256: str | None = None
    hit: bool = False
    postflight: str | None = None
    restricted: tuple[RestrictedItem, ...] = ()


@dataclass(frozen=True, slots=True)
class AssetListing:
    """One frozen asset of one artefact, with its licence and its named restrictions. D778."""

    asset_id: int
    sha256: str
    slot: str
    role: str
    units: tuple[str, ...]
    media_type: str
    byte_len: int
    doc_ord: int
    licence: str | None
    spdx: str | None
    restriction_bits: int
    restrictions: tuple[str, ...]
    """Each set bit's `Restriction` name, lower-case; an unallocated bit is `bit_<n>`."""


@dataclass(frozen=True, slots=True)
class SlotUser:
    """One artefact generation that slots the bytes `--slot` names. D778."""

    slug: str
    artifact_gen: int
    role: str
    units: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SlotOwner:
    """One corpus document that owns an `asset` row of those bytes. D778."""

    doc_ord: int
    uri: str
    asset_id: int


@dataclass(frozen=True, slots=True)
class AssetsReport:
    """What `ow out assets` read: one artefact's ledger, or one slot's users and owners. D778."""

    slug: str | None
    artifact_gen: int | None
    slot: str | None
    assets: tuple[AssetListing, ...] = ()
    users: tuple[SlotUser, ...] = ()
    owners: tuple[SlotOwner, ...] = ()


@dataclass(frozen=True, slots=True)
class BackReport:
    """What `ow out back` restored, and whether the contract moved since the seal. D777.

    `contract_unchanged` compares the artefact's recorded `constructs_digest` with the installed
    table's. On a difference the rows that moved cannot be listed: 09 section 3.6 counts them from
    the artefact's recorded table version, and nothing records that version (D776).

    D788: the loop is closed first. The sealed bytes are read back by the card's `read_back`
    into a corpus document, and the IL's addresses are mapped to its blocks.
    """

    slug: str
    from_gen: int
    artifact_gen: int
    job_dir: str
    run_id: str
    contract_unchanged: bool
    recorded_digest: str
    installed_digest: str
    units: tuple[str, ...]
    read_back: str = ""
    """The card's `[compile.round_trip] read_back`: the parse driver that closes the loop. D788."""
    read_back_doc_ord: int | None = None
    """The document the generation was read back as; `None` while the loop is open."""
    els: int = 0
    """The `artifact_el` rows mapping the IL's addresses to that document's blocks."""
    loop_open: str = ""
    """Why the loop is open; `""` once `read_back_doc_ord` is set."""


@dataclass(frozen=True, slots=True)
class VerifiedClass:
    """One declared determinism class and what the recompile found: `held`, `differs`, or
    `unchecked` for a class no comparison here can reach. D774."""

    name: str
    held: str


@dataclass(frozen=True, slots=True)
class VerifyReport:
    """What `ow out verify` found: R1 class by class, and R7's two counts. D774.

    A law that fails is a status and an exit, 8, never a raise (10 section 9.3).
    """

    slug: str
    artifact_gen: int
    exit: int
    r1: bool
    classes: tuple[VerifiedClass, ...]
    r7: bool
    units_sealed: int
    unit_count: int


@dataclass(frozen=True, slots=True)
class NormalizedRow:
    """One unit and one `normalize` row: how many values were rewritten. D768."""

    unit: str
    construct: str
    count: int


@dataclass(frozen=True, slots=True)
class NormalizeReport:
    """What `ow out normalize` did. Nothing changed is a success that wrote nothing. D768."""

    written: tuple[str, ...]
    changed: tuple[NormalizedRow, ...]


@dataclass(frozen=True, slots=True)
class StampedUnit:
    """One unit a stamp wrote: the addresses it minted, in document order. D767."""

    unit: str
    addresses: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StampReport:
    """What `ow out stamp` did. Nothing minted is a success that wrote nothing. D767."""

    written: tuple[str, ...]
    units: tuple[StampedUnit, ...]
    stale_lock: bool


@dataclass(frozen=True, slots=True)
class ScaffoldUnit:
    """One commissioned unit of a scaffolded JobDir: `OutUnit`'s four plan-time fields. D765."""

    id: str
    ord: int
    il_path: str
    anchor: str


@dataclass(frozen=True, slots=True)
class ScaffoldReport:
    """What `ow out scaffold` returns: the JobDir it wrote and the roster it commissioned. D765.

    `job_dir` is absolute. `artifact_gen` is the proposed generation, one past the corpus
    store's newest; the seal allocates the real one (09 section 5.4).
    """

    job_dir: str
    run_id: str
    target: str
    slug: str
    artifact_gen: int
    corpus: str
    traceparent: str
    units: tuple[ScaffoldUnit, ...]


@dataclass(frozen=True, slots=True)
class ConstructBake:
    """A `bake` row's `{ renderer, dpi, role }`. D762."""

    renderer: str
    dpi: int
    role: str


@dataclass(frozen=True, slots=True)
class ConstructListing:
    """One ConstructTable row, as `ow out constructs` prints it. D762.

    `omniweave_core.out.constructs.Construct`'s fields, plus `group` (the id's first dotted
    segment, 09-generation.md section 3.3's `--group`) and `numeric`, the register's spelling of
    `code`, resolved at render time as the table's own file comment says. A separate class for
    `TargetListing`'s reason: the registry's type graph does not import `omniweave_core.out`.
    """

    id: str
    group: str
    disposition: str
    round_trip: str
    code: str
    numeric: str
    since: str
    selector: str
    canonical: str | None
    maps_to: str | None
    normalizes_to: str | None
    normalizer: str | None
    bake: ConstructBake | None
    forbidden_when: str | None
    msg: str | None
    severity: str | None
    visible: bool


@dataclass(frozen=True, slots=True)
class ConstructsReport:
    """What `ow out constructs <target>` returns: the target's table and the rows selected. D762.

    09-generation.md section 3.3. `agent_doc_tokens_max` is the card's ceiling on the
    `--format md` document, counted in CI and never at runtime (`omniweave_core.out.agentdoc`).
    """

    target: str
    driver: str
    il: str
    carrier: str
    version: int
    digest: str
    agent_doc_tokens_max: int
    ignore: tuple[str, ...]
    rows: tuple[ConstructListing, ...]


@dataclass(frozen=True, slots=True)
class EvalPublishReport:
    """What `ow eval publish` returns. D833.

    `files` and `rows` are the export's: every `<suite>/<subject>.json` the `.oweval` publishes,
    and how many rows they hold. `changed` is Q-G19's byte clause, `scoreboard.stale()`: each
    file whose committed bytes differed from the export, were missing, or were extra. `written`
    says whether the tree was rewritten to match. It never is under `--check`, and never when
    nothing differed.
    """

    files: tuple[str, ...]
    rows: int
    changed: tuple[str, ...]
    written: bool


@dataclass(frozen=True, slots=True)
class EvalBlessReport:
    """What `ow eval bless --inventory` returns. D846.

    13-quality.md:1847 makes the verb OW-Q-013's fix. `inventory` and `log` are the two files it
    wrote. `row` is the `BLESS.log` line it appended, without its LF. `fell` names each area whose
    tests or properties fell, the decreases the row blesses, and `changed` names every area that
    moved. `tests` is the new collection's count.
    """

    inventory: str
    log: str
    row: str
    fell: tuple[str, ...]
    changed: tuple[str, ...]
    tests: int


@dataclass(frozen=True, slots=True)
class EvalRunRow:
    """One subject's run in `ow eval run`'s report. D868.

    `value` is the metric's rate over `n` sampled claims, or `None` when the subject claimed
    nothing and the rate is vacuous, which writes no metric row. `parsed` and `refused` are the
    fixtures the driver parsed and the ones it refused, each refusal named with its class.
    """

    run_id: str
    subject: str
    slice: str
    corpus: str
    metric: str
    value: float | None
    n: int
    parsed: int
    refused: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvalRunReport:
    """What `ow eval run` returns. D868.

    `suite` is the suite measured and `oweval` the store its rows went into, in one transaction.
    `runs` is one row per subject.
    """

    suite: str
    oweval: str
    runs: tuple[EvalRunRow, ...]


@dataclass(frozen=True, slots=True)
class EvalReleaseFinding:
    """One reason `ow eval release-check` refuses a release. D840.

    `kind` is what was judged: `run` (a latest run whose status is `unknown`), `metric` (an
    `UNKNOWN` scoreboard row), `perf` (an `eval_perf` row not `pass`), `gate` (a hard gate's value
    off its budget), `unmeasured` (a hard gate no row measured) or `suite` (under `--strict`, a
    suite with no run). `names` says which, `why` what was found, and `fix` what clears it.
    """

    kind: str
    names: str
    why: str
    fix: str


@dataclass(frozen=True, slots=True)
class EvalReleaseCheckReport:
    """What `ow eval release-check` returns. D840.

    13-quality.md:1881: *"exit 0 iff zero `unknown`, zero hard-gate failures"*. `ok` is exactly
    that: no finding. `runs` is how many latest runs were judged and `superseded` how many older
    ones a later run of the same suite, subject and corpus replaced. `gates` is how many hard,
    blocking `eval/gates.toml` rows were held. `strict` says whether a suite with no run was a
    finding.
    """

    ok: bool
    strict: bool
    runs: int
    superseded: int
    gates: int
    findings: tuple[EvalReleaseFinding, ...]


@dataclass(frozen=True, slots=True)
class CostListing:
    """One `ow cost` row: 15-observability.md section 5.4's ten columns. D838, D839.

    `key` is the row's value of the slicing `CostReport.by` names: a driver under `--by driver`,
    a provider, a lane, a rung, a slice or a UTC date otherwise. `omniweave.run.cost.RowCost`'s
    fields, kept as a separate class so the registry's type graph does not import the runtime,
    the reason `TargetListing` gives for the same arrangement.
    """

    key: str
    cost_class: str
    units: int
    calls: int
    tokens_in: int
    tokens_out: int
    gpu_ms: int
    micros: int
    hits: int
    saved: int


@dataclass(frozen=True, slots=True)
class CostReport:
    """What `ow_cost` / `ow cost` returns: spend, sliced, and what the cache saved. D838, D839.

    10-interfaces.md's `full` roster: *"spend by driver, corpus and window, plus
    `would_have_been_micros_if_uncached`"*. `total_micros` is the sum of the `micros` column and
    `saved_micros` of the `saved` column (15 section 5.4: *"checkable rather than decorative"*).
    `billed_micros` is `Σ route_spend.micros` over the window; `manifest_billed_micros` is the
    run manifest's own figure, and `None` unless `run_id` names a run whose manifest reads.
    `by` is the slicing, and `since` the `--since` duration as given, or `None`.
    """

    corpus: str
    by: str
    since: str | None
    run_id: str | None
    rows: tuple[CostListing, ...]
    total_micros: int
    saved_micros: int
    billed_micros: int
    manifest_billed_micros: int | None
