"""L3's ONLY writer: `GraphSink`'s twelve methods, its seven Drafts and its five id `NewType`s.

Implements 06-structure-extraction.md section 1.7 (:337-400), which prints the twelve signatures
and, at :381-384, names this file as the home of every type they mention: *"the seven Drafts live
in `omniweave_core/store/graph.py` beside `GraphSink`, are frozen and slotted, and are host-side
reconstructions of `owgraph-items/1` frames -- a driver never imports them, exactly as a `parse/1`
driver never imports `BlockDraft`."* `store/__init__.py` declares the Protocol these types complete;
this module is where they live and where the SQLite implementation of the Protocol lives with them.

**A DRAFT PROPOSES; THE RUNNER DECIDES** (06:378). Every Draft carries what the driver KNOWS and
nothing it must not choose: no `*_id`, no trust beyond a CLAIM, no `restriction_bits`, no
`producer_id`, no taint, and no cite for a row it is minting. The sink stamps all of it.

## The four properties the signatures carry rather than assert (06:386-392)

* **There is no `drop()`.** `quarantine()` is the only disposal path (GR10, INV-25), so
  "the rejected draft is kept VERBATIM in `payload`" is a type-level fact rather than a convention.
  01-principles.md:744 names the violation in as many words -- *"A violation looks like a
  `GraphSink.drop()`"* -- and `test_store_graph.py` asserts that no public method on
  `SqliteGraphSink` issues a `DELETE`, so the property is checked over the SOURCE and not only over
  the twelve names.
* **Every id-returning method mints its id INSIDE the sink** (GR11), so no Draft can name one. That
  is why `entity`, `mention`, `edge` and `claim` return an id and `alias`, `anchor` and `xref`
  return `None`: the last three name their subject by a `TmpRef` the sink resolves.
* **`cover` is a method on the open run**, so a cover row commits or vanishes with the items it
  describes (GR3), and it requires an `empty_reason` when the cite set produced nothing --
  "the set produced nothing" and "nobody looked" are different answers and the schema refuses to
  confuse them (01-principles.md:838-841, `derive_cover.empty_reason`).
* **`RunStatus` narrows the charter's `status: str`** to the same five values as the `derive_run`
  CHECK, so a runner cannot report a state the store cannot hold (06:391-393). A declared narrowing
  with a stated reason completes the charter rather than contradicting it; `store/__init__.py`'s
  `GraphSink` docstring already records that ruling.

## One run is one transaction, and the sink does not own the connection

`StoreThread` is the only holder of a `Connection` in a process (INV-17, 07:2722), and a `Unit` is
one `BEGIN IMMEDIATE` ... `COMMIT` around one closure. A run is therefore driven INSIDE one `Unit`:
the runner submits `Unit(name="derive.<pass>", run=lambda conn: drive(SqliteGraphSink(conn)))`, and
`end_run()` is the last statement before the store thread's `COMMIT`. That is what 06:373's
"COMMITS ONE TXN" buys -- a cover row and the items it describes land together or not at all -- and
it is bought without a second transaction manager. This module opens no connection and closes none;
it issues no `BEGIN`, no `COMMIT` and, anywhere, no `DELETE`.

## What the DDL decides, and this module obeys

`store/schema/migrations/0002_graph.sql` is the authority on every column, CHECK, UNIQUE and
foreign key written here, and two of its decisions shape the code rather than merely constrain it:

1. **0002 ships NO trigger mirroring `MAX_TRUST_BY_METHOD`** onto entity/mention/edge/claim, and
   its header says why -- the ceiling lives in Python and a literal SQL copy would be the second
   truth the parity requirement forbids. So **the clamp is applied here**, in `_clamp`, and an
   over-claim writes an `OW_GRAPH_TRUST_CLAMPED` quarantine row carrying the driver's ORIGINAL
   claim (06:690, 03:1621) while the row itself is written at the ceiling. Measurable, not silently
   corrected.
2. **`quarantine.code` has no CHECK**, because the code resolves against append-only `codes.toml`
   and a constraint would freeze the register into the migration. So `quarantine()` accepts any
   non-empty symbol; the fourteen this sink itself raises are the constants below.

## Two normalisers, and they are not interchangeable

`normalize_key` is the BLOCKING-KEY normaliser and `normalize_k` is the GROUNDING normaliser; their
docstrings in `omniweave_core.ident` say so and the names differ by four characters on purpose.
This module picks deliberately at four sites:

* `entity.key` -- `normalize_key`. The DDL calls the column *"normalize_key(canonical surface). A
  BLOCKING key, NOT an id"* (0002:242) and 06:107 makes it GR7.
* `entity_alias.name_norm` and `anchor.name_norm` -- `normalize_key`. 0002:291 fixes it as *"ONE
  SPELLING for a normalised name across `anchor`, `ref_site` and here"*.
* `ground()` -- `normalize_k`, and only through `ground()`. 03:2930 makes `ground()` *"the only
  producer of a `ts_a`/`ts_b` anywhere in this plan"* and forbids its two callers from touching
  `normalize_k` or `str.find` themselves: an offset `.find()` returns lives in normalised space,
  a `TextSpan` lives in `block.text`'s space, and carrying one to the other through the back-map is
  `ground()`'s whole job.

Stdlib only (INV-2 / G1). `import sqlite3` is legal here and only here-ish: `pyproject.toml`'s
per-file-ignore covers `store/*.py` (INV-17 / TID251).

Tier T-SCHEMA: 02-architecture.md section 2 row 26.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, Literal, NewType, get_args

from omniweave_core.canonical import JsonValue, canonical, ow128, sha256_canonical
from omniweave_core.errors import GraphError
from omniweave_core.ident import normalize_k, normalize_key
from omniweave_core.limits import MAX_ITEMS_PER_SEGMENT, MAX_SEGMENT_BLOCKS
from omniweave_core.model.block import BlockId, Cite
from omniweave_core.model.enums import (
    MAX_TRUST_BY_METHOD,
    AliasKind,
    AnchorKind,
    ClaimStatus,
    Lane,
    Method,
    TimePrecision,
    Trust,
    enum_val_rows,
)
from omniweave_core.model.records import Diag
from omniweave_core.model.spans import TextSpan
from omniweave_core.operator import SpendVector

__all__ = [
    "OW_GRAPH_COVERED_GROUND",
    "OW_GRAPH_DANGLING_CITE",
    "OW_GRAPH_DANGLING_TMP",
    "OW_GRAPH_ETYPE_OUT_OF_VOCAB",
    "OW_GRAPH_INJECTION_SUSPECT",
    "OW_GRAPH_ITEM_BUDGET",
    "OW_GRAPH_LABEL_TOO_LONG",
    "OW_GRAPH_OUT_OF_SCOPE_BLOCK",
    "OW_GRAPH_QUOTE_AMBIGUOUS",
    "OW_GRAPH_TRUST_CLAMPED",
    "OW_GRAPH_UNGROUNDED",
    "OW_GRAPH_UNPARSED_ITEM",
    "QUARANTINED_ID",
    "QUARANTINE_ROW_KINDS",
    "AliasDraft",
    "AnchorDraft",
    "ClaimDraft",
    "ClaimId",
    "EdgeDraft",
    "EdgeId",
    "EntityDraft",
    "EntityId",
    "Grounded",
    "MentionDraft",
    "MentionId",
    "PassIdentity",
    "RunId",
    "RunReport",
    "RunStatus",
    "SegmentRef",
    "SpendVector",
    "SqliteGraphSink",
    "TmpRef",
    "XrefDraft",
    "ground",
]


# ---------------------------------------------------------------------------------------------
# 1. The ids, the status domain and the two provenance records. 06:339-352.
# ---------------------------------------------------------------------------------------------

RunId = NewType("RunId", int)
"""`derive_run.run_id`. Minted by `begin_run`, never named by a Draft (GR11)."""

EntityId = NewType("EntityId", int)
"""`entity.entity_id` -- a DURABLE surrogate, assigned once per `(scope, etype, key)` (06:117)."""

MentionId = NewType("MentionId", int)
"""`mention.mention_id`."""

EdgeId = NewType("EdgeId", int)
"""`edge.edge_id`."""

ClaimId = NewType("ClaimId", int)
"""`claim.claim_id`.

The five are distinct `NewType`s so an `EntityId` cannot be passed where a `MentionId` belongs.
A `NewType` erases at runtime -- `EntityId(3) == MentionId(3)` and `type(EntityId(3)) is int` --
so the distinction is a TYPE-CHECK-time one, which is the point: the defect it prevents (an id from
one table used as a key into another) is a defect a reader cannot see and a type checker can.
`test_store_graph.py` asserts the five are five distinct objects with distinct
`__supertype__`-bearing identities, and records in a comment that the runtime cannot do more.
"""

RunStatus = Literal["ok", "partial", "empty", "failed", "quarantined"]
"""`derive_run.status`, narrowed from the charter's `status: str` (06:339, :391-393).

The five values are exactly `derive_run`'s CHECK list (0002:196), and the narrowing exists so a
runner cannot report a state the store cannot hold.
"""

QUARANTINED_ID: Final[int] = 0
"""What an id-returning method returns when the draft was quarantined instead of written.

**Extends the plan.** 06:363 says `mention` *"grounds a `quote`, else quarantines"* and still types
the return `MentionId`; nothing in the plan says what comes back on the quarantine arm. Raising is
wrong -- 06:462 is explicit that *"a CHECK violation is an exception and a quarantine is data --
and a malformed draft must produce data"*, and INV-25 forbids turning a retained rejection into a
control-flow event. So the four id-returning methods return this sentinel, which is unrepresentable
as a real row: every L3 id column is `INTEGER PRIMARY KEY`, whose rowids begin at 1, so `0` can
never collide with a written row. A caller that ignores the return value loses nothing -- the
quarantine row and the `RunReport.quarantined` count carry the fact -- and a caller that checks it
gets a total answer without a `None` arm on four signatures the plan prints without one.
"""

QUARANTINE_ROW_KINDS: Final[frozenset[str]] = frozenset(
    {"entity", "alias", "mention", "edge", "claim", "anchor", "xref", "merge"}
)
"""`quarantine.row_kind`'s CHECK list (0002:504-505), transcribed so the sink refuses early.

Eight, and `cover` is deliberately not among them: a cover row is written by the runner from the
Segment it was handed, so a bad cover cite is the runner's defect and raises, while every kind here
originates in a driver's frame and is DATA.
"""

# The fourteen quarantine codes and the one Diag code this sink itself raises. 06:684-698 is the
# table; `quarantine.code`'s comment in 0002_graph.sql transcribes the same list.
#
# WHY THESE ARE CONSTANTS HERE AND NOT LOOKUPS INTO `codes.toml`. The register is the home of the
# symbol-to-numeric mapping and it is append-only, but it does not yet carry a single `OW_GRAPH_*`
# quarantine row -- `codes.toml` holds one graph symbol, `OW_GRAPH_DISABLED`, and it is an `OW-C-*`
# config row. Resolving a code against the register at write time would therefore refuse every
# quarantine this sink exists to write. The rows are owed (see this wave's report); until they land
# these constants are the spelling, and `quarantine()` validates only that the code is non-empty,
# exactly as the DDL does -- 0002:509 declines a CHECK for the same reason.
OW_GRAPH_UNGROUNDED: Final = "OW_GRAPH_UNGROUNDED"
OW_GRAPH_DANGLING_CITE: Final = "OW_GRAPH_DANGLING_CITE"
OW_GRAPH_DANGLING_TMP: Final = "OW_GRAPH_DANGLING_TMP"
OW_GRAPH_OUT_OF_SCOPE_BLOCK: Final = "OW_GRAPH_OUT_OF_SCOPE_BLOCK"
OW_GRAPH_COVERED_GROUND: Final = "OW_GRAPH_COVERED_GROUND"
OW_GRAPH_ITEM_BUDGET: Final = "OW_GRAPH_ITEM_BUDGET"
OW_GRAPH_TRUST_CLAMPED: Final = "OW_GRAPH_TRUST_CLAMPED"
OW_GRAPH_LABEL_TOO_LONG: Final = "OW_GRAPH_LABEL_TOO_LONG"
OW_GRAPH_INJECTION_SUSPECT: Final = "OW_GRAPH_INJECTION_SUSPECT"
OW_GRAPH_ETYPE_OUT_OF_VOCAB: Final = "OW_GRAPH_ETYPE_OUT_OF_VOCAB"
OW_GRAPH_UNPARSED_ITEM: Final = "OW_GRAPH_UNPARSED_ITEM"
OW_GRAPH_QUOTE_AMBIGUOUS: Final = "OW_GRAPH_QUOTE_AMBIGUOUS"

_MAX_LABEL_CHARS: Final = 200
"""`EntityDraft.title` above this quarantines `OW_GRAPH_LABEL_TOO_LONG` (06:414, :691, :2154).

PRIVATE, and that is a report rather than a choice: INV-21 says a declared ceiling has one home in
`limits.py`, and this one has no row there. The plan states the number three times and names it
never, so there is nothing to transcribe into `limits.py` without inventing a name. The underscore
keeps this from reading as a second public declaration; the required edit is in this wave's report.
"""

_CITE_GRAMMAR: Final = re.compile(r"\A(?:[^:]*:)?d(?P<doc_ord>\d+)#(?P<n>\d+)\Z")
"""`[<corpus>:]d<doc_ord>#<n>` -- 03:274. The `doc_ord` capture is what makes a cite lookup an
index seek on `block_cite (doc_ord, cite)` instead of a full scan of `block`."""

_ETYPE_GRAMMAR: Final = re.compile(r"\A[a-z][a-z0-9_]{0,31}\Z")
"""06:316. *"A 32-character lower-case identifier cannot carry a delimiter, a sentinel or a
newline, so no rendering of the `etypes` array can be steered."*"""

_COVER_BITMAP_BYTES: Final = MAX_SEGMENT_BLOCKS // 8
"""64. `derive_cover.cover_bits` is *"EXACTLY ceil(MAX_SEGMENT_BLOCKS/8) = 64 B"* (0002:219)."""

_ENTITY_MENTION_DIGEST_DOMAIN: Final = b"ow.entity.1"
"""The `ow128` domain for `entity.mention_digest`.

**Extends the plan.** 06:122 and 0002:257 call the column *"a merkle over live mention digests"*
and name no domain and no recipe, while `mention.digest`'s recipe is printed in full at 06:192.
The column is `BLOB NOT NULL`, so a value is required at the first `entity()` call, before any
mention exists. The recipe used here is `ow128(b'ow.entity.1', [<hex mention digests, sorted>])`:
sorted rather than insertion-ordered because the set is what the digest names, and hex because
`canonical()`'s grammar is JSON's and has no bytes. Reported as a plan gap.
"""

_METHOD_ORD: Final[Mapping[str, int]] = MappingProxyType(
    {name: ordinal for domain, ordinal, name in enum_val_rows() if domain == "method"}
)
"""`Method` member name -> the integer `derive_run.method` stores.

Read off `enum_val_rows()`, which 03 section 2.1 makes *"THE SINGLE SITE THAT APPLIES the ordinal
rule"*. A second literal table here would be a second truth about what a stored `2` means.
"""


# `SpendVector` moved to `omniweave_core.operator` with P4's runtime vocabulary, and is imported
# above rather than re-declared. It was written here at P2 because `end_run(status, spend)` needed
# the eight attributes while `Spend` -- 05-ingest-and-routing.md:2366-2374, `omniweave.route`'s and
# therefore an import `tools/layers.toml` forbids core in either direction -- had no home and
# still has none. P4's `StepMetrics` needs the same shape, `store/` is one of the nine LAZY names,
# and a type the runner's vocabulary depends on cannot live behind a lazy import of the store. Its
# reasoning travelled with it; it stays in this module's `__all__`, so `from
# omniweave_core.store.graph import SpendVector` is unchanged for every caller that had it.


@dataclass(frozen=True, slots=True)
class SegmentRef:
    """What the selector handed out (06 section 2.1); gen-fencing's baseline (06 section 10.3).

    Transcribed from 06:344-347. `uncovered` is the 64-byte cover bitmap and is `None` for a free
    Pass, which has no floor: a free Pass may write on ground a cheaper Pass already covered
    because there is no cheaper Pass. `content_digest` is `segment.content_digest` as it stood when
    the selector ran, and `begin_run` stores it as `derive_run.input_digest` so gen-fencing at
    `end_run` has something to compare against.
    """

    segment_id: int
    doc_ord: int
    gen: int
    content_digest: bytes
    uncovered: bytes | None


@dataclass(frozen=True, slots=True)
class PassIdentity:
    """The provenance the SINK stamps. No Draft field can reach any of it. 06:349-352.

    `decision_id` is the `route_decision` row and is NULL for a free Pass; `prompt_fp` is a billed
    Pass's prompt fingerprint and is a `paid_key` input (05 section 4.6). Both are nullable because
    a free Pass has neither, and both are on the identity rather than on a Draft because
    charter.md:5444 makes this sink *"the ONLY place `restriction_bits` / `origin_driver` /
    `producer_id` are stamped"*.
    """

    pass_id: str
    producer_id: int
    method: Method
    origin_operator: str
    origin_driver: str
    driver_schema_v: int
    cost_class: str
    decision_id: str | None = None
    prompt_fp: bytes | None = None


@dataclass(frozen=True, slots=True)
class RunReport:
    """What `end_run` returns and `ow graph plan` / `ow graph residue` read. 06:376-384.

    `inputs` counts every draft offered to the sink, `emitted` the rows written and `quarantined`
    the rows retained instead; the last two are what `derive_run.n_items` and `n_quarantined` hold.
    `coverage_frac` is the deterministic-first metric section 2.4 reports as coverage.
    `grounded_frac` is billed-Passes-only -- `1 - the OW_GRAPH_UNGROUNDED share` -- and is `None`
    for a free Pass and for a billed Pass that attempted no grounding, because a rate over zero
    attempts is not 1.0 and is not 0.0.

    `spend` is the physical vector. No micros anywhere in it (INV-15).
    """

    run_id: int
    pass_id: str
    status: RunStatus
    inputs: int
    emitted: int
    quarantined: int
    covered: int
    cover_empty: int
    coverage_frac: float
    grounded_frac: float | None
    xrefs_bound: int
    xrefs_unresolved: int
    spend: SpendVector


# ---------------------------------------------------------------------------------------------
# 2. The seven Drafts. 06:396-471.
# ---------------------------------------------------------------------------------------------

TmpRef = NewType("TmpRef", str)
"""`'e1'` -- LOCAL to one invocation. Never persisted, never a cite, never an id (06:402).

*"A Pass names its own proposed entities with per-invocation tokens and names blocks by `cite`, so
it can forge neither a `block_id` nor an `entity_id`"* (06:621-623). A `TmpRef` referenced but
never defined quarantines `OW_GRAPH_DANGLING_TMP` -- the whole Segment (06:626, :686).
"""

Grounded = tuple[Cite, TextSpan] | tuple[Cite, str]
"""`(cite, span)` XOR `(cite, quote)`. 06:403-407.

The union cannot hold both, so "span and quote together" is unrepresentable rather than a
validation branch, and the two arms discriminate on `isinstance(x[1], TextSpan)` -- never by
inspecting a string.
"""


@dataclass(frozen=True, slots=True)
class EntityDraft:
    """A proposed entity. Upserted on `UNIQUE (scope, etype, key)` (06:362).

    Transcribed from 06:409-418. `key` is the driver's surface and `normalize_key()` is applied BY
    THE SINK; `trust_claim` is A CLAIM, clamped by `MAX_TRUST_BY_METHOD` with the over-claim
    RECORDED; `scope` is the WORD and the sink maps it to `entity.scope`'s integer encoding, which
    is the structural half of the `scoped_label_crossdoc` guard -- a Draft cannot name another
    document's scope because it never supplies a number (06:154-160).

    **`tmp` extends the plan, and it is the one field added to a printed shape.** 06:409-418 prints
    `EntityDraft` without any `TmpRef`, while `AliasDraft`, `MentionDraft`, `EdgeDraft` and
    `ClaimDraft` all address their entity BY `TmpRef` and 06:624-626 puts the resolution in the
    sink (*"A `TmpRef` referenced but never defined quarantines the whole Segment"*), as do
    02:488, glossary.md:863 and 16-roadmap.md:774, which prices *"`Draft` and per-invocation `tmp`
    id resolution"* as this sink's work. Four definition sites put the tmp table in the sink
    against one printed shape that gives the sink no way to populate it. The alternatives were
    worse: binding the Nth `entity()` call to `TmpRef(f"e{n}")` would MIS-BIND silently for any
    pass that spells its tokens differently, and a mis-bound mention is a wrong entity on a right
    span, which is the defect class this file exists to prevent. The field is appended and
    defaulted, so every construction the plan prints still type-checks and still runs; `None` means
    the entity defines no token and no other Draft may reference it. Reported.
    """

    key: str
    etype: str
    title: str
    scope: Literal["document", "corpus"]
    trust_claim: Trust
    raw_etype: str | None = None
    description: str | None = None
    score: float | None = None
    score_kind: str | None = None
    tmp: TmpRef | None = None


@dataclass(frozen=True, slots=True)
class AliasDraft:
    """An observed surface for an entity. 06:420-424.

    `alias_kind` is DISJOINT from `akind` and keeps its own column name and its own `enum_val`
    domain (06:127-129): one domain holds one vocabulary, because `enum_val`'s
    `PRIMARY KEY (domain, ord)` has room for exactly one.
    """

    entity: TmpRef
    surface: str
    alias_kind: Literal["canonical", "variant", "abbrev", "expansion", "translit", "llm", "user"]
    trust_claim: Trust


@dataclass(frozen=True, slots=True)
class MentionDraft:
    """One occurrence of an entity in one block. 06:426-439.

    A `quote` form is GROUNDED by the sink through `ground()`: the offsets come back through
    `normalize_k`'s back-map, in `block.text` coordinates, NEVER `.find()`'s own offsets.

    * not found -> quarantine `OW_GRAPH_UNGROUNDED`, the draft KEPT verbatim;
    * found > 1x -> the FIRST occurrence, plus `Diag(OW_GRAPH_QUOTE_AMBIGUOUS)` carrying the count;
    * found, but the span does not normalise back to the quote (a boundary inside an expansion)
      -> also `OW_GRAPH_UNGROUNDED`. `ground()` never widens a span to make one fit.
    """

    entity: TmpRef
    at: Grounded
    surface: str
    trust_claim: Trust
    score: float | None = None
    score_kind: str | None = None


@dataclass(frozen=True, slots=True)
class EdgeDraft:
    """An entity-to-entity relationship and WHERE IT WAS SEEN. 06:441-450.

    `observed` is required and not derived: it is neither endpoint's definition site, and it is
    graphify's required-on-edges `source_file` done properly (06:47). `bound_by` is the anchor
    `name_norm` that resolved the edge and is what drives `unbind`; `weight` defaults to 1.0.
    """

    src: TmpRef
    dst: TmpRef
    relation: str
    observed: Grounded
    trust_claim: Trust
    role: str | None = None
    weight: float = 1.0
    score: float | None = None
    score_kind: str | None = None
    bound_by: str | None = None


@dataclass(frozen=True, slots=True)
class ClaimDraft:
    """An assertion about an entity. 06:452-465.

    `object_entity` XOR `object_literal`; a literal HAS a datatype; `(t_start OR t_end)` IFF
    `t_precision`. ALL THREE are CHECKed in the DDL *and* validated in the sink, *"because a CHECK
    violation is an exception and a quarantine is data -- and a malformed draft must produce
    data"* (06:462-464).
    """

    subject: TmpRef
    object_entity: TmpRef | None
    object_literal: str | None
    object_datatype: str | None
    claim_type: str
    predicate: str
    description: str
    status: Literal["asserted", "denied", "suspected", "superseded"]
    observed: Grounded
    trust_claim: Trust
    t_start: str | None = None
    t_end: str | None = None
    t_precision: Literal["year", "month", "day", "datetime"] | None = None
    score: float | None = None
    score_kind: str | None = None


@dataclass(frozen=True, slots=True)
class AnchorDraft:
    """What a document DEFINES. 06:467-471.

    `surface` is as written: DISPLAYED, never matched. There is no confidence column on `anchor` --
    an anchor is observed, not judged (06:114) -- so this Draft carries no `trust_claim`, and a
    second definition of one `(name_norm, akind)` in one generation quarantines
    `OW_GRAPH_UNPARSED_ITEM` with BOTH surfaces in the payload, because the document is ambiguous
    and picking one silently is wrong (06:115-118).
    """

    name: str
    akind: AnchorKind
    at: Grounded
    scope: Literal["document", "corpus"]
    surface: str


@dataclass(frozen=True, slots=True)
class XrefDraft:
    """A reference OCCURRENCE. 06:473-477.

    *"-> an edge(bound_by=name_norm) when the name resolves against `anchor`, else a `ref_site`
    row. THE PASS DOES NOT DECIDE WHICH. The sink resolves and reports the split as
    `RunReport.xrefs_bound` / `xrefs_unresolved`."*
    """

    name: str
    akind: AnchorKind
    at: Grounded
    surface: str


# ---------------------------------------------------------------------------------------------
# 3. `ground()` -- the ONE grounding algorithm. 06:565-618.
# ---------------------------------------------------------------------------------------------


def ground(block_text: str, quote: str) -> tuple[int, int, int] | None:
    """-> `(ts_a, ts_b, occurrences)` in BLOCK.TEXT coordinates, or `None` when absent.

    `ts_a`/`ts_b` are half-open offsets into `block_text` such that `block_text[ts_a:ts_b]` is the
    slice (07 section 9.2). The offsets come back through `normalize_k`'s back-map; they are NEVER
    the offsets `.find()` returned, which live in normalised space. The returned span is checked to
    normalise back to the quote before it is returned, so a caller receives a RIGHT span or `None`.

    Transcribed from 06:565-590, which prints the body. Two lines carry the defect the plan spent a
    fix-ledger entry on. **Both endpoints map through the back-map entry of a character INSIDE the
    match**; `back[end]` -- the entry of the character AFTER it -- is wrong in both directions:

    * truncation: `block_text="the file"` with a U+FB01 ligature and `quote="the f"` gives
      `back[5] == 4` and the span `"the "`, which does not contain the matched text at all;
    * over-inclusion: `block_text="ab" + 3 x U+200B + "c"` and `quote="ab"` gives `back[2] == 5`,
      putting three invisible characters inside the span. `back[end - 1] + 1` gives 2.

    And the round-trip post-condition is asserted HERE, at the one producer, rather than only in
    section 11's P-GROUND fixtures: `back[end - 1] + 1` turns every mid-expansion match from a
    truncated span into a SUPERSET span, and a superset is still not the quote. `normalize_k("Stra"
    + eszett + "e")[0]` is `"strasse"`, so the quote `"se"` matches at normalised index 5 and the
    tightest honest span is the eszett plus `e`, which normalises to `"sse"`. Widening silently
    would record a citation the reader can see is longer than the claim; `None` records that the
    corpus could not witness the claim as written, which is true and is repairable by re-running
    one Pass.

    **Home.** 06 section 1.7 prints this function inside `ident.py`'s own cluster but gives it no
    `# omniweave_core/...` module comment, unlike `normalize_k`, `nfc` and `fold_common`, which all
    carry one. Its two declared callers are `GraphSink.mention` (here) and the router's
    `FieldGrounding` (03:2930-2937), which has no module yet. It lives here because this is the
    only caller that exists; when `FieldGrounding` lands, moving it beside `normalize_k` in
    `omniweave_core.ident` is one edit and this module re-exports it. Reported.
    """
    hay, back = normalize_k(block_text)
    needle, _ = normalize_k(quote)
    if not needle:
        return None  # an empty quote is OW_GRAPH_UNGROUNDED, never a match
    # The counting loop `.find()` cannot provide. Overlapping occurrences are counted; the FIRST is
    # the one grounded, which is 06 section 1.7's stated rule (and N5's open question).
    hits: list[int] = []
    i = hay.find(needle)
    while i != -1:
        hits.append(i)
        i = hay.find(needle, i + 1)
    if not hits:
        return None
    i0 = hits[0]
    end = i0 + len(needle)  # half-open, in NORMALISED space; `needle` is non-empty
    ts_a = back[i0]
    ts_b = back[end - 1] + 1
    if normalize_k(block_text[ts_a:ts_b])[0] != needle:
        return None  # OW_GRAPH_UNGROUNDED. Never widened, never guessed.
    return ts_a, ts_b, len(hits)


# ---------------------------------------------------------------------------------------------
# 4. Internal helpers -- payload canonicalisation and the resolved-block record.
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Block:
    """The columns of one `block` row this sink reads. Never returned to a caller."""

    block_id: int
    doc_ord: int
    text: str
    quote: int
    restriction_bits: int


def _json_safe(value: object) -> JsonValue:
    """Render one Draft field into `canonical()`'s grammar without losing it.

    `quarantine.payload` holds *"THE REJECTED DRAFT, canonical JSON, VERBATIM"* (0002:507) and
    `canonical()`'s grammar is JSON's -- no bytes, no enums, no tuples, no dataclasses -- with no
    `str()` fallback anywhere, ever (I12). So each shape gets an explicit, reversible rendering:
    `bytes` to hex, an `Enum` to its value, a `TextSpan` to `[a, b]`. A shape with no rendering
    raises from `canonical()` rather than being stringified into a payload nobody can read back.
    """
    if isinstance(value, bool | int | float | str) or value is None:
        return value
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, Enum):
        return _json_safe(value.value)
    if isinstance(value, TextSpan):
        return [value.a, value.b]
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, Sequence):
        return [_json_safe(item) for item in value]
    message = f"a Draft field of type {type(value).__name__} has no canonical-JSON rendering"
    raise GraphError(message, symbol=OW_GRAPH_UNPARSED_ITEM, fix="ow graph residue")


def _draft_payload(draft: object) -> Mapping[str, JsonValue]:
    """One Draft as the mapping `quarantine.payload` stores. Field order is the class's."""
    if not is_dataclass(draft) or isinstance(draft, type):
        return {"value": _json_safe(draft)}
    return {f.name: _json_safe(getattr(draft, f.name)) for f in fields(draft)}


def _json_text(obj: Mapping[str, JsonValue]) -> str:
    """Canonical JSON as the `TEXT` a JSON column holds."""
    return canonical(dict(obj)).decode("utf-8")


def _derive_precision(t_start: str | None, t_end: str | None) -> str | None:
    """`claim.t_precision` from the shape of the ISO-8601 string. `None` when there is no time.

    `TimePrecision`'s docstring (`model/enums.py`, citing 06:1450 and 06:2535) states the rule:
    *"DERIVED BY THE SINK from the shape of the ISO-8601 string -- four characters is `year`, seven
    is `month` -- and never asked of a model, because the precision is already in the string and a
    second place to be wrong is a second thing to be wrong."* Partial dates are permitted, so the
    length IS the precision; anything longer than a bare date is `datetime`.
    """
    stamp = t_start if t_start is not None else t_end
    if stamp is None:
        return None
    lengths = {4: TimePrecision.YEAR, 7: TimePrecision.MONTH, 10: TimePrecision.DAY}
    return str(lengths.get(len(stamp), TimePrecision.DATETIME).value)


# ---------------------------------------------------------------------------------------------
# 5. The SQL, in one place. Every statement names its columns; none of them is built by hand.
# ---------------------------------------------------------------------------------------------

_INSERT_RUN: Final = """
INSERT INTO derive_run (segment_id, pass_id, at_gen, producer_id, method, origin_operator,
                        origin_driver, driver_schema_v, cost_class, decision_id, input_digest,
                        cache_key, status, n_items, n_quarantined, spend)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'failed', 0, 0, '{}')
"""
# `status` starts at 'failed' and `end_run` overwrites it. The placeholder is unobservable -- a run
# is one transaction, so a crash before `end_run` rolls the row back with everything else -- and
# 'failed' is chosen so that the one way it could ever be read is the safe way round.

_SELECT_BLOCK: Final = """
SELECT block_id, doc_ord, text, quote, restriction_bits
FROM block WHERE doc_ord = ? AND cite = ? AND state = 0
"""

_SELECT_ENTITY: Final = "SELECT entity_id FROM entity WHERE scope = ? AND etype = ? AND key = ?"

_SELECT_ETYPE: Final = "SELECT 1 FROM etype_vocab WHERE etype = ?"

_SELECT_ENTITY_KEY: Final = "SELECT key FROM entity WHERE entity_id = ?"

_NEXT_ENTITY_ID: Final = "SELECT IFNULL(MAX(entity_id), 0) + 1 FROM entity"
_NEXT_CLAIM_ID: Final = "SELECT IFNULL(MAX(claim_id), 0) + 1 FROM claim"
# `entity.canonical_id` is a NOT NULL self-reference and `entity.cite` / `claim.cite` are NOT NULL
# derivations of the id, so both rows need their id BEFORE the INSERT. SQLite enforces a foreign
# key immediately, so `canonical_id` cannot be back-filled after the fact. Assigning MAX + 1 inside
# the run's transaction is safe because the store thread holds the write lock for its whole length
# (INV-17), so no second writer can take the id between the SELECT and the INSERT.

_INSERT_ENTITY: Final = """
INSERT INTO entity (entity_id, cite, scope, etype, key, title, raw_etype, canonical_id,
                    resolution_trust, resolution_method, trust, taint, restriction_bits,
                    frequency, degree, doc_count, mention_digest, description, summary, state, x)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, 0, 0, 0, 0, 0, ?, ?, NULL, 0, '{}')
"""

_LOWER_ENTITY_TRUST: Final = "UPDATE entity SET trust = MIN(trust, ?) WHERE entity_id = ?"

_STAMP_ENTITY_BITS: Final = """
UPDATE entity SET restriction_bits = restriction_bits | ?, mention_digest = ?
WHERE entity_id = ?
"""

_LIVE_MENTION_DIGESTS: Final = """
SELECT digest FROM mention WHERE entity_id = ? AND state = 0 ORDER BY mention_id
"""

_INSERT_ALIAS: Final = """
INSERT INTO entity_alias (entity_id, name_norm, surface, alias_kind, run_id, trust, taint,
                          doc_count)
VALUES (?, ?, ?, ?, ?, ?, 0, 1)
ON CONFLICT (entity_id, name_norm, alias_kind)
DO UPDATE SET trust = MIN(entity_alias.trust, excluded.trust)
"""
# MIN and never MAX: *"A migration may only downgrade"* (06:88), and corroboration is not
# promotion. An alias seen twice cannot talk its way up a tier.

_INSERT_MENTION: Final = """
INSERT OR IGNORE INTO mention (entity_id, block_id, segment_id, ts_a, ts_b, surface, run_id,
                               trust, score, score_kind, taint, restriction_bits, digest, state)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, 0)
"""

_SELECT_MENTION: Final = """
SELECT mention_id FROM mention
WHERE block_id = ? AND ts_a = ? AND ts_b = ? AND entity_id = ? AND run_id = ?
"""

_SELECT_RELATION: Final = "SELECT symmetric FROM relation_vocab WHERE relation = ?"

_SELECT_EDGE: Final = """
SELECT edge_id FROM edge
WHERE src_entity = ? AND dst_entity = ? AND relation = ? AND observed_block = ?
  AND IFNULL(ts_a, -1) = ? AND run_id = ?
"""

_INSERT_EDGE: Final = """
INSERT INTO edge (src_entity, dst_entity, relation, role, observed_block, ts_a, ts_b, bound_by,
                  weight, combined_degree, corroborations, run_id, trust, score, score_kind,
                  taint, restriction_bits, x)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1, ?, ?, ?, ?, 0, ?, '{}')
"""

_CORROBORATE_EDGE: Final = "UPDATE edge SET corroborations = corroborations + 1 WHERE edge_id = ?"
# CORROBORATION IS NOT PROMOTION (06:199-200): the counter moves and `trust` never does.

_SELECT_CLAIM: Final = """
SELECT claim_id FROM claim
WHERE subject_entity = ? AND IFNULL(object_entity, -1) = ? AND IFNULL(object_literal, '') = ?
  AND claim_type = ? AND observed_block = ? AND ts_a = ? AND run_id = ?
"""

_INSERT_CLAIM: Final = """
INSERT INTO claim (claim_id, cite, subject_entity, object_entity, object_literal, object_datatype,
                   claim_type, predicate, description, status, t_start, t_end, t_precision,
                   observed_block, ts_a, ts_b, quote_tier, run_id, trust, score, score_kind,
                   taint, restriction_bits, x)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, '{}')
"""

_SELECT_ANCHOR: Final = """
SELECT surface FROM anchor WHERE doc_ord = ? AND gen = ? AND name_norm = ? AND akind = ?
"""

_INSERT_ANCHOR: Final = """
INSERT INTO anchor (doc_ord, gen, name_norm, akind, surface, block_id, entity_id, scope, run_id)
VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)
"""

_INSERT_REF_SITE: Final = """
INSERT OR IGNORE INTO ref_site (name_norm, akind, doc_ord, block_id, ts_a, ts_b, surface, scope,
                                origin_operator, run_id)
VALUES (?, ?, ?, ?, ?, ?, ?, 'document', ?, ?)
"""
# `scope` is the OCCURRENCE's and is always 'document': a reference occurs inside exactly one
# document. Both reference views (`ref_unresolved` and `ow_ref_resolved`, 0003:248-262) read
# `anchor.scope` and never `ref_site.scope`, so this column steers no resolution; writing 'corpus'
# here would claim a reach an occurrence does not have. Reported: the column's meaning is stated
# nowhere and `XrefDraft` carries no scope to copy.

_XREF_RESOLVES: Final = """
SELECT 1 FROM anchor n JOIN doc dd ON dd.doc_ord = n.doc_ord
WHERE n.name_norm = ? AND n.akind = ? AND n.gen = dd.gen
  AND (n.scope = 'corpus' OR n.doc_ord = ?)
LIMIT 1
"""
# The `ow_ref_resolved` predicate, clause for clause (0003:257-262): HEAD GENERATION ONLY, and
# SCOPE IS HONOURED. Restated here rather than selected from the view so the split `RunReport`
# reports is the same split the view will report later; 0003's own comment records that both
# predicates *"failed silently without them"*.

_SELECT_SEGMENT_ORD: Final = "SELECT ord FROM segment_block WHERE block_id = ? AND segment_id = ?"

_SELECT_COVER: Final = """
SELECT cover_bits FROM derive_cover WHERE segment_id = ? AND lane = ? AND run_id = ?
"""

_UPSERT_COVER: Final = """
INSERT INTO derive_cover (segment_id, lane, run_id, cover_bits, n_covered, empty_reason)
VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT (segment_id, lane, run_id)
DO UPDATE SET cover_bits = excluded.cover_bits, n_covered = excluded.n_covered,
              empty_reason = excluded.empty_reason
"""

_INSERT_QUARANTINE: Final = """
INSERT INTO quarantine (code, run_id, row_kind, payload, block_id, detail, at_gen)
VALUES (?, ?, ?, ?, ?, ?, ?)
"""

_INSERT_DIAG: Final = """
INSERT INTO diag (doc_ord, gen, page, block_id, part, code, severity, component, message, detail,
                  fatal)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_FINISH_RUN: Final = """
UPDATE derive_run SET status = ?, n_items = ?, n_quarantined = ?, spend = ? WHERE run_id = ?
"""

_SEGMENT_BLOCKS: Final = "SELECT n_blocks FROM segment WHERE segment_id = ?"


# ---------------------------------------------------------------------------------------------
# 6. The closed vocabularies this module validates against, read off the enums (INV-21).
# ---------------------------------------------------------------------------------------------

_RUN_STATUSES: Final[frozenset[str]] = frozenset(get_args(RunStatus))
"""`RunStatus`'s five values as a runtime set, off the `Literal` itself so the two cannot drift."""

_LANES: Final[frozenset[str]] = frozenset(member.value for member in Lane)
"""The `lane` domain, from `Lane` and not from a second list (INV-21). `derive_cover.lane` stores
the LOWER-CASE MEMBER NAME, which for a `StrEnum` is the member's own value (0002:214-217)."""

_ALIAS_KINDS: Final[frozenset[str]] = frozenset(member.value for member in AliasKind)
"""`entity_alias.alias_kind`'s seven, DISJOINT from `akind` (06:127-129)."""

_ANCHOR_KINDS: Final[frozenset[str]] = frozenset(member.value for member in AnchorKind)
"""`anchor.akind` and `ref_site.akind` -- the SAME vocabulary on both sides of the join."""

_CLAIM_STATUSES: Final[frozenset[str]] = frozenset(member.value for member in ClaimStatus)
"""`claim.status`'s four, under the `claim_status` domain name (0002:400-402)."""


def _spend_json(spend: SpendVector) -> Mapping[str, JsonValue]:
    """`derive_run.spend` -- *"canonical JSON of Spend. NO DOLLARS HERE"* (0002:203).

    The seven physical units and `provider`, and nothing else: `Spend.micros(book)` is the only
    place money appears in the framework (INV-15) and this column may not carry its output.
    """
    return {
        "wall_ms": spend.wall_ms,
        "cpu_ms": spend.cpu_ms,
        "gpu_ms": spend.gpu_ms,
        "tokens_in": spend.tokens_in,
        "tokens_out": spend.tokens_out,
        "calls": spend.calls,
        "bytes_egress": spend.bytes_egress,
        "provider": spend.provider,
    }


def _score_pair(score: float | None, score_kind: str | None) -> bool:
    """`CHECK ((score IS NULL) = (score_kind IS NULL))` -- *"an unnamed 0.7 is not a measurement"*.

    Validated in the sink as well as in the DDL so a malformed draft produces DATA rather than an
    `IntegrityError` (06:462-464). `score_kind` is additionally *"resolved against
    tools/scorekinds.toml AT WRITE"* (06:418, 03:584); that register is not in the tree, so the
    pairing is what this wave can enforce. Reported.
    """
    return (score is None) == (score_kind is None)


def _claim_shape(d: ClaimDraft) -> bool:
    """Two of `claim`'s three CHECKs plus its `status` domain, over one draft. 0002:414-417.

    `(object_entity IS NULL) <> (object_literal IS NULL)` -- bipartite; and
    `(object_literal IS NULL) = (object_datatype IS NULL)` -- a literal HAS a datatype. The third,
    `(t_start IS NOT NULL OR t_end IS NOT NULL) = (t_precision IS NOT NULL)`, holds by
    construction because the sink DERIVES `t_precision` from the timestamps.
    """
    bipartite = (d.object_entity is None) != (d.object_literal is None)
    typed = (d.object_literal is None) == (d.object_datatype is None)
    named = d.status in _CLAIM_STATUSES
    return bipartite and typed and named and _score_pair(d.score, d.score_kind)


def _mention_merkle(digests: Sequence[bytes]) -> bytes:
    """`entity.mention_digest` -- a merkle over live mention digests. See the domain's docstring."""
    return ow128(_ENTITY_MENTION_DIGEST_DOMAIN, sorted(digest.hex() for digest in digests))


# ---------------------------------------------------------------------------------------------
# 7. The sink. Twelve public methods, and there is no thirteenth.
# ---------------------------------------------------------------------------------------------


class SqliteGraphSink:
    """The SQLite implementation of `GraphSink`. Twelve public methods, and no way to drop a row.

    Constructed with the store thread's `Connection` INSIDE a `Unit`, so `begin_run` .. `end_run`
    is one `BEGIN IMMEDIATE` .. `COMMIT` and every row this sink writes commits with every other
    (see this module's docstring). It satisfies the frozen `GraphSink` Protocol structurally --
    `store/__init__.py` declares it and `test_store_graph.py` compares the two surfaces method by
    method and parameter by parameter -- and it deliberately exposes nothing else: a thirteenth
    public method fails a test.

    **Nothing here can dispose of a row.** There is no `drop`, no `delete`, no `discard` and no
    `skip`; `quarantine()` is the only path a rejected draft can take, every internal rejection
    goes through `_reject` into it, and no statement in this module is a `DELETE`.
    01-principles.md:723-745 is the invariant and :744 names the violation in as many words --
    *"A violation looks like a `GraphSink.drop()`"*. The owner-scoped replacement `DELETE`s of
    06 section 10.2 belong to the maintenance path, filtered on `origin_operator` (ST11).

    **The order of a draft's checks is fixed and each one is a different fact.** Budget, then
    shape, then vocabulary, then the `TmpRef`, then scope, then existence, then grounding, then
    the trust clamp -- so a draft that is both over budget and ungrounded quarantines under the
    first reason a reader would act on, and `ow graph residue` grouped by code stays readable.
    """

    # -- lifecycle -----------------------------------------------------------------------------

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._seg: SegmentRef | None = None
        self._pass: PassIdentity | None = None
        self._allowed: frozenset[Cite] = frozenset()
        self._run_id = 0
        self._closed = False
        self._tmps: dict[str, EntityId] = {}
        self._blocks: dict[str, _Block | None] = {}
        self._covered: set[int] = set()
        self._inputs = 0
        self._emitted = 0
        self._quarantined = 0
        self._cover_empty = 0
        self._attempts = 0
        self._ungrounded = 0
        self._xrefs_bound = 0
        self._xrefs_unresolved = 0
        self._dangled: list[str] = []

    def begin_run(self, seg: SegmentRef, p: PassIdentity, allowed_cites: frozenset[Cite]) -> RunId:
        """Open one `derive_run` and fix the cite scope for its whole length.

        **`allowed_cites` IS the injection and cache-poisoning control** (GR9), lifted from
        graphify's `cache.put(entries, allowed_units=...)`. A draft naming a cite outside the set
        is quarantined `OW_GRAPH_OUT_OF_SCOPE_BLOCK` and KEPT, and 06:360-361 fixes the mechanism:
        *"Enforced by the SIGNATURE, not by a later audit."* Taking the set here rather than
        checking it per call is what makes that true -- there is no path to an L3 row that has not
        been handed the set first.

        `uncovered` is validated to the exact bitmap width, because *"a 513-block segment is a
        REFUSAL, never a truncation -- 'zero billed items on covered ground' rests on this bitmap
        being complete"* (0002:222-224).
        """
        if self._seg is not None or self._closed:
            raise GraphError(
                "this GraphSink already has a run; one sink drives one run",
                symbol=OW_GRAPH_UNPARSED_ITEM,
                fix="construct a new SqliteGraphSink for the next run",
            )
        if seg.uncovered is not None and len(seg.uncovered) != _COVER_BITMAP_BYTES:
            raise GraphError(
                f"SegmentRef.uncovered is {len(seg.uncovered)} bytes; the cover bitmap is exactly "
                f"{_COVER_BITMAP_BYTES} (ceil(MAX_SEGMENT_BLOCKS / 8))",
                symbol=OW_GRAPH_UNPARSED_ITEM,
                fix="hand the selector's own 64-byte bitmap through unchanged",
            )
        self._seg = seg
        self._pass = p
        self._allowed = allowed_cites
        cursor = self._connection.execute(
            _INSERT_RUN,
            (
                seg.segment_id,
                p.pass_id,
                seg.gen,
                p.producer_id,
                _METHOD_ORD[p.method.name.lower()],
                p.origin_operator,
                p.origin_driver,
                p.driver_schema_v,
                p.cost_class,
                p.decision_id,
                seg.content_digest,
                _cache_key(seg, p, allowed_cites),
            ),
        )
        self._run_id = int(cursor.lastrowid or 0)
        return RunId(self._run_id)

    def end_run(self, status: RunStatus, spend: SpendVector) -> RunReport:
        """Finish the `derive_run` row and report. The store thread's `COMMIT` follows.

        A dangling `TmpRef` overrides the status the runner asked for: 06:626 says a `TmpRef`
        referenced but never defined *"quarantines the whole Segment"* and 06:686 repeats it, so
        the run cannot report `ok` while a draft in it named an entity that was never proposed.
        The rows already written STAY -- retirement is never deletion and quarantine is never a
        drop -- so the correction is a status plus retained rows, never a rollback of the items
        that were fine.
        """
        self._require_open()
        if status not in _RUN_STATUSES:
            raise GraphError(
                f"{status!r} is not one of derive_run.status's five values",
                symbol=OW_GRAPH_UNPARSED_ITEM,
                fix=f"pass one of {sorted(_RUN_STATUSES)}",
            )
        seg = self._segment()
        identity = self._identity()
        final: RunStatus = "quarantined" if self._dangled else status
        self._connection.execute(
            _FINISH_RUN,
            (final, self._emitted, self._quarantined, _json_text(_spend_json(spend)), self._run_id),
        )
        report = RunReport(
            run_id=self._run_id,
            pass_id=identity.pass_id,
            status=final,
            inputs=self._inputs,
            emitted=self._emitted,
            quarantined=self._quarantined,
            covered=len(self._covered),
            cover_empty=self._cover_empty,
            coverage_frac=self._coverage_frac(seg),
            grounded_frac=self._grounded_frac(identity),
            xrefs_bound=self._xrefs_bound,
            xrefs_unresolved=self._xrefs_unresolved,
            spend=spend,
        )
        self._closed = True
        return report

    # -- the seven item methods ----------------------------------------------------------------

    def entity(self, d: EntityDraft) -> EntityId:
        """Upsert on `UNIQUE (scope, etype, key)` and bind `d.tmp` to the minted id.

        **This is the only binding mechanism a Pass has** (06:628-634): *"A Pass binds to an
        existing entity by proposing it again."* No draft field names an `entity_id` and none may
        be added, so a `derive.claim.llm` run emitting `EntityDraft(key="acme_holdings_ltd",
        etype="org", scope="corpus")` binds its claim's subject to the existing `e412` without
        ever naming it -- which is why the `claim` lane's prompt renders entity SURFACES rather
        than entity cites.

        On an upsert the existing row's `title` and `description` are kept and only `trust` moves,
        downward: an entity is a DURABLE row two Passes may converge on (06:150-152), so a second
        Pass may weaken the claim and may never strengthen it.
        """
        self._require_open()
        self._inputs += 1
        refusal = self._entity_refusal(d)
        if refusal is not None:
            return EntityId(self._reject("entity", refusal, d, self._entity_detail(d, refusal)))
        trust = self._clamp("entity", d, d.trust_claim)
        scope = 0 if d.scope == "corpus" else self._segment().doc_ord
        key = normalize_key(d.key)
        found = self._connection.execute(_SELECT_ENTITY, (scope, d.etype, key)).fetchone()
        entity_id = (
            self._converge(int(found[0]), trust)
            if found is not None
            else self._mint_entity(d, scope, key, trust)
        )
        if d.tmp is not None:
            self._tmps[str(d.tmp)] = entity_id
        self._emitted += 1
        return entity_id

    def alias(self, d: AliasDraft) -> None:
        """Record one observed surface. `name_norm` is `normalize_key(surface)`.

        *"every observed surface is an `entity_alias`"* (06:47), and the table is the fix for
        graphrag keying its graph on `clean_str(name.upper())`, under which an entity whose
        spelling drifted between chunks silently became two nodes.
        """
        self._require_open()
        self._inputs += 1
        if not self._budget("alias", d):
            return
        if d.alias_kind not in _ALIAS_KINDS:
            self._reject("alias", OW_GRAPH_UNPARSED_ITEM, d, {"alias_kind": d.alias_kind})
            return
        entity_id = self._tmp("alias", d, d.entity)
        if entity_id is None:
            return
        trust = self._clamp("alias", d, d.trust_claim)
        self._connection.execute(
            _INSERT_ALIAS,
            (
                entity_id,
                normalize_key(d.surface),
                d.surface,
                d.alias_kind,
                self._run_id,
                int(trust),
            ),
        )
        self._emitted += 1

    def mention(self, d: MentionDraft) -> MentionId:
        """Ground the draft and write one `mention`. The BRIDGE table, and the only one (GR15).

        `mention` is *"the only table in the framework referencing both a `block_id` and an
        `entity_id`"* (06:232-235), which is what makes the provenance chain of 06 section 8 a
        fixed-length walk rather than a search. This method never touches `normalize_k` or
        `str.find` itself: `ground()` carries the offset from normalised space into `block.text`
        space through the back-map, and 03:2930 makes it *"the only producer of a `ts_a`/`ts_b`
        anywhere in this plan"*.
        """
        self._require_open()
        self._inputs += 1
        if not self._budget("mention", d):
            return MentionId(QUARANTINED_ID)
        if not _score_pair(d.score, d.score_kind):
            return MentionId(self._reject("mention", OW_GRAPH_UNPARSED_ITEM, d))
        entity_id = self._tmp("mention", d, d.entity)
        if entity_id is None:
            return MentionId(QUARANTINED_ID)
        located = self._locate("mention", d, d.at)
        if located is None:
            return MentionId(QUARANTINED_ID)
        return self._write_mention(d, entity_id, located)

    def edge(self, d: EdgeDraft) -> EdgeId:
        """Write one `edge`, or corroborate the one already there.

        A `symmetric` relation is stored with `src_entity < dst_entity`, *"so `co_occurs_with`
        cannot appear twice"* (06:322), and the symmetry is read off `relation_vocab` rather than
        guessed -- the vocabulary is DATA because *"an enum generated from a Python enum at
        migration time cannot express 'a driver may declare a new relation'"* (06:300).
        A second draft with the same identity increments `corroborations` and moves nothing else:
        *"Corroboration increments `corroborations`; it NEVER raises trust"* (06:199-200).
        """
        self._require_open()
        self._inputs += 1
        if not self._budget("edge", d):
            return EdgeId(QUARANTINED_ID)
        symmetric = self._connection.execute(_SELECT_RELATION, (d.relation,)).fetchone()
        if symmetric is None or not _score_pair(d.score, d.score_kind):
            return EdgeId(self._reject("edge", OW_GRAPH_UNPARSED_ITEM, d, {"relation": d.relation}))
        endpoints = self._endpoints(d, bool(int(symmetric[0])))
        if endpoints is None:
            return EdgeId(QUARANTINED_ID)
        located = self._locate("edge", d, d.observed)
        if located is None:
            return EdgeId(QUARANTINED_ID)
        return self._write_edge(d, endpoints, located)

    def claim(self, d: ClaimDraft) -> ClaimId:
        """Write one `claim`, with `t_precision` DERIVED and `quote_tier` copied.

        The three CHECKs 0002:414-417 carries are validated here as well, *"because a CHECK
        violation is an exception and a quarantine is data -- and a malformed draft must produce
        data"* (06:462-464). `quote_tier` is the one deliberate denormalisation in L3: the source
        block's `Quote` ordinal, copied at write time so a byte-exactness filter over claims is an
        index range scan rather than a join through `observed_block` per candidate (06:227-231).

        **`t_precision` is derived and the draft's own value is only ever CHECKED against it.**
        `TimePrecision`'s docstring is the deciding site -- *"DERIVED BY THE SINK from the shape of
        the ISO-8601 string ... and never asked of a model, because the precision is already in
        the string and a second place to be wrong is a second thing to be wrong"* (06:1450,
        06:2535) -- while 06:459 prints the field on the Draft. Both hold if the sink derives and
        refuses a disagreement: a draft whose `t_precision` contradicts its own timestamps
        quarantines `OW_GRAPH_UNPARSED_ITEM` carrying the derived value, rather than being silently
        overwritten.
        """
        self._require_open()
        self._inputs += 1
        if not self._budget("claim", d):
            return ClaimId(QUARANTINED_ID)
        precision = _derive_precision(d.t_start, d.t_end)
        if not _claim_shape(d) or (d.t_precision is not None and d.t_precision != precision):
            return ClaimId(self._reject("claim", OW_GRAPH_UNPARSED_ITEM, d, {"derived": precision}))
        subject = self._tmp("claim", d, d.subject)
        obj = None if d.object_entity is None else self._tmp("claim", d, d.object_entity)
        if subject is None or (d.object_entity is not None and obj is None):
            return ClaimId(QUARANTINED_ID)
        located = self._locate("claim", d, d.observed)
        if located is None:
            return ClaimId(QUARANTINED_ID)
        return self._write_claim(d, subject, obj, located, precision)

    def anchor(self, d: AnchorDraft) -> None:
        """Record what the document DEFINES. A second definition in one generation quarantines.

        *"A second definition of one `(name_norm, akind)` in one generation quarantines
        `OW_GRAPH_UNPARSED_ITEM` with BOTH surfaces in the payload -- the document is ambiguous and
        picking one silently is wrong"* (06:115-118). The stored surface goes into `detail` and the
        rejected draft into `payload`, so both spellings are in the one row.
        """
        self._require_open()
        self._inputs += 1
        if not self._budget("anchor", d):
            return
        if str(d.akind) not in _ANCHOR_KINDS:
            self._reject("anchor", OW_GRAPH_UNPARSED_ITEM, d, {"akind": str(d.akind)})
            return
        located = self._locate("anchor", d, d.at)
        if located is None:
            return
        seg = self._segment()
        name_norm = normalize_key(d.name)
        clash = self._connection.execute(
            _SELECT_ANCHOR, (seg.doc_ord, seg.gen, name_norm, str(d.akind))
        ).fetchone()
        if clash is not None:
            self._reject("anchor", OW_GRAPH_UNPARSED_ITEM, d, {"already_defined": str(clash[0])})
            return
        self._connection.execute(
            _INSERT_ANCHOR,
            (
                seg.doc_ord,
                seg.gen,
                name_norm,
                str(d.akind),
                d.surface,
                located[0].block_id,
                d.scope,
                self._run_id,
            ),
        )
        self._emitted += 1

    def xref(self, d: XrefDraft) -> None:
        """Record one reference OCCURRENCE and count whether the name resolves.

        `ref_site` has *"NO status column, EVER"* (0003:206): resolution is by string, so
        `ref_unresolved` is an anti-join VIEW and there is no lifecycle to go stale. This method
        therefore always writes the occurrence and reports the split through
        `RunReport.xrefs_bound` / `xrefs_unresolved`, computed with the view's own predicate.

        **The `edge(bound_by=...)` arm is not constructible from this Draft, and that is a plan
        defect rather than a decision.** 06:474-477 says the sink resolves an `XrefDraft` to
        *"an edge(bound_by=name_norm) when the name resolves against `anchor`, else a `ref_site`
        row"*, but an `edge` needs `src_entity` and `dst_entity`, an `XrefDraft` carries neither,
        and the resolving `anchor` row need not carry an `entity_id` -- the column is nullable and
        `anchor()` leaves it NULL. The occurrence and the split are what this Draft determines;
        binding an edge needs the entity context only the `xref` Pass has. Reported.
        """
        self._require_open()
        self._inputs += 1
        if not self._budget("xref", d):
            return
        if str(d.akind) not in _ANCHOR_KINDS:
            self._reject("xref", OW_GRAPH_UNPARSED_ITEM, d, {"akind": str(d.akind)})
            return
        located = self._locate("xref", d, d.at)
        if located is None:
            return
        block, ts_a, ts_b = located
        name_norm = normalize_key(d.name)
        self._connection.execute(
            _INSERT_REF_SITE,
            (
                name_norm,
                str(d.akind),
                block.doc_ord,
                block.block_id,
                ts_a,
                ts_b,
                d.surface,
                self._identity().origin_operator,
                self._run_id,
            ),
        )
        resolved = self._connection.execute(
            _XREF_RESOLVES, (name_norm, str(d.akind), block.doc_ord)
        ).fetchone()
        if resolved is None:
            self._xrefs_unresolved += 1
        else:
            self._xrefs_bound += 1
        self._emitted += 1

    # -- coverage, disposal and diagnostics ----------------------------------------------------

    def cover(self, lane: str, cites: Sequence[Cite], *, empty_reason: str | None = None) -> None:
        """Claim ground for `lane`. **Coverage, or a REASON** (GR3).

        01-principles.md:840-841 lists `GraphSink.cover` *"requiring `empty_reason` when the cite
        set produced nothing"* among INV-25's schema-level enforcers, and `derive_cover`'s own
        comment says what the column buys: *"NOT NULL => covered with ZERO items. doctor reports
        the rate"* (0002:227-228). So an empty cite set with no reason RAISES rather than writing a
        row nobody can tell apart from "nobody looked". This is the runner's bug, not a driver's
        frame, and the one thing INV-25 forbids is a disposal *nothing records*.

        A cite outside the Segment raises for the same reason: the runner builds this set from the
        Segment it was handed, so a stray cite is a runner defect -- and `quarantine.row_kind` has
        no `cover` member to record it as data (its CHECK list is `QUARANTINE_ROW_KINDS`).
        """
        self._require_open()
        if lane not in _LANES:
            raise GraphError(
                f"{lane!r} is not a member of the `lane` domain",
                symbol=OW_GRAPH_UNPARSED_ITEM,
                fix=f"pass one of {sorted(_LANES)}",
            )
        if not cites and empty_reason is None:
            raise GraphError(
                f"cover({lane!r}) claims an empty cite set and gives no empty_reason: "
                f"'the set produced nothing' and 'nobody looked' are different answers",
                symbol=OW_GRAPH_UNPARSED_ITEM,
                fix='cover(lane, (), empty_reason="no candidate spans in this segment")',
            )
        seg = self._segment()
        bits = bytearray(self._cover_bits(lane))
        for cite in cites:
            ordinal = self._cover_ord(cite)
            bits[ordinal // 8] |= 1 << (ordinal % 8)
            self._covered.add(ordinal)
        if not cites:
            self._cover_empty += 1
        self._connection.execute(
            _UPSERT_COVER,
            (
                seg.segment_id,
                lane,
                self._run_id,
                bytes(bits),
                sum(byte.bit_count() for byte in bits),
                empty_reason,
            ),
        )

    def quarantine(self, row_kind: str, code: str, payload: Mapping[str, Any], **d: Any) -> None:
        """Retain a rejected draft. **THE ONLY DISPOSAL PATH** (GR10, INV-25).

        graphrag DELETES these -- `filter_orphan_relationships` -- and 0002:496-498 records why
        omniweave does not: *"A HALLUCINATED NAME IS VERY OFTEN A REAL ENTITY THE EXTRACTOR FAILED
        TO EMIT A ROW FOR. KEEP IT."* The draft is stored VERBATIM as canonical JSON, `code` is the
        `codes.toml` symbol and never the numeric, and `at_gen` is the Segment's generation so
        `ow graph residue` can group a run's residue by the text it was reading.

        `**d` is the plan's own spelling (06:370-371). `block_id` is lifted out of it into the
        column of that name -- it is a foreign key and an index target -- and every other keyword,
        plus anything under a `detail` mapping, lands in `detail`.
        """
        self._require_open()
        if row_kind not in QUARANTINE_ROW_KINDS:
            raise GraphError(
                f"{row_kind!r} is not one of quarantine.row_kind's eight values",
                symbol=OW_GRAPH_UNPARSED_ITEM,
                fix=f"pass one of {sorted(QUARANTINE_ROW_KINDS)}",
            )
        if not code:
            raise GraphError(
                "quarantine.code is NOT NULL and holds the codes.toml SYMBOL",
                symbol=OW_GRAPH_UNPARSED_ITEM,
                fix="pass a code, e.g. OW_GRAPH_UNGROUNDED",
            )
        extra = dict(d)
        block_id = extra.pop("block_id", None)
        nested = extra.pop("detail", {})
        detail = {str(k): _json_safe(v) for k, v in extra.items()}
        if isinstance(nested, Mapping):
            detail.update({str(k): _json_safe(v) for k, v in nested.items()})
        self._connection.execute(
            _INSERT_QUARANTINE,
            (
                code,
                self._run_id,
                row_kind,
                _json_text({str(k): _json_safe(v) for k, v in payload.items()}),
                None if block_id is None else int(block_id),
                _json_text(detail),
                self._segment().gen,
            ),
        )
        self._quarantined += 1

    def diag(self, d: Diag) -> None:
        """Record one diagnostic against the Segment's document.

        `Diag` is RECORDED; `OwError` is RAISED (03:1806-1808), and `d.code` holds the SYMBOL from
        `codes.toml` and never the numeric -- `Diag.__post_init__` already refuses that spelling.
        `doc_ord` and `gen` come from the `SegmentRef` because `Diag` carries neither: a diagnostic
        is about a place in a document, and the run knows which document it is reading.
        """
        self._require_open()
        seg = self._segment()
        self._connection.execute(
            _INSERT_DIAG,
            (
                seg.doc_ord,
                seg.gen,
                d.page,
                None if d.block is None else int(d.block),
                d.part,
                d.code,
                d.severity,
                d.component,
                d.message,
                _json_text({str(k): _json_safe(v) for k, v in d.detail.items()}),
                int(d.fatal),
            ),
        )

    # -- private: run state --------------------------------------------------------------------

    def _require_open(self) -> None:
        """Refuse every method before `begin_run` and after `end_run`."""
        if self._closed:
            raise GraphError(
                "this run is finished; end_run has already written its derive_run row",
                symbol=OW_GRAPH_UNPARSED_ITEM,
                fix="construct a new SqliteGraphSink for the next run",
            )
        if self._seg is None:
            raise GraphError(
                "no open run: begin_run fixes the Segment, the identity and allowed_cites",
                symbol=OW_GRAPH_UNPARSED_ITEM,
                fix="call begin_run(seg, p, allowed_cites) first",
            )

    def _segment(self) -> SegmentRef:
        seg = self._seg
        if seg is None:  # pragma: no cover -- every caller runs `_require_open` first
            raise GraphError("no open run", symbol=OW_GRAPH_UNPARSED_ITEM, fix="begin_run first")
        return seg

    def _identity(self) -> PassIdentity:
        identity = self._pass
        if identity is None:  # pragma: no cover -- set with `_seg` and never cleared alone
            raise GraphError("no open run", symbol=OW_GRAPH_UNPARSED_ITEM, fix="begin_run first")
        return identity

    def _coverage_frac(self, seg: SegmentRef) -> float:
        """Covered blocks over the Segment's own block count. 0.0 when the Segment has none."""
        row = self._connection.execute(_SEGMENT_BLOCKS, (seg.segment_id,)).fetchone()
        total = 0 if row is None else int(row[0])
        return 0.0 if total <= 0 else len(self._covered) / total

    def _grounded_frac(self, p: PassIdentity) -> float | None:
        """`1 - the OW_GRAPH_UNGROUNDED share`, for a billed Pass that attempted grounding.

        `None` for a free Pass (06:381 says billed only) and `None` when no draft carried a quote:
        a rate over zero attempts is not 1.0, and reporting 1.0 there would read as perfect
        grounding on a run that grounded nothing.
        """
        if p.cost_class != "billed_api" or self._attempts == 0:
            return None
        return 1.0 - (self._ungrounded / self._attempts)

    # -- private: the checks, in the order a draft meets them ----------------------------------

    def _budget(self, row_kind: str, draft: object) -> bool:
        """`MAX_ITEMS_PER_SEGMENT`. A breach quarantines `OW_GRAPH_ITEM_BUDGET` naming the knob.

        06:2154's row for this defence: *"emit 100,000 entities named ACME": OW_GRAPH_ITEM_BUDGET,
        naming the knob*. The count is rows WRITTEN by this run, so a run that quarantined a
        thousand drafts has not spent its budget on them.
        """
        if self._emitted < MAX_ITEMS_PER_SEGMENT:
            return True
        self._reject(
            row_kind,
            OW_GRAPH_ITEM_BUDGET,
            draft,
            {"limit": "MAX_ITEMS_PER_SEGMENT", "value": MAX_ITEMS_PER_SEGMENT},
        )
        return False

    def _entity_refusal(self, d: EntityDraft) -> str | None:
        """The first reason this `EntityDraft` cannot be written, or `None`.

        One function so the ORDER is visible in one place: budget, then the label ceiling, then the
        etype charset and vocabulary, then the score pairing.
        """
        if self._emitted >= MAX_ITEMS_PER_SEGMENT:
            return OW_GRAPH_ITEM_BUDGET
        if len(d.title) > _MAX_LABEL_CHARS:
            return OW_GRAPH_LABEL_TOO_LONG
        if _ETYPE_GRAMMAR.match(d.etype) is None or not self._etype_known(d.etype):
            return OW_GRAPH_ETYPE_OUT_OF_VOCAB
        if not _score_pair(d.score, d.score_kind):
            return OW_GRAPH_UNPARSED_ITEM
        return None

    @staticmethod
    def _entity_detail(d: EntityDraft, refusal: str) -> Mapping[str, JsonValue]:
        """The `detail` that makes an `EntityDraft` refusal actionable without reading `payload`."""
        if refusal == OW_GRAPH_LABEL_TOO_LONG:
            return {"title_chars": len(d.title), "limit": _MAX_LABEL_CHARS}
        if refusal == OW_GRAPH_ETYPE_OUT_OF_VOCAB:
            return {"etype": d.etype}
        if refusal == OW_GRAPH_ITEM_BUDGET:
            return {"limit": "MAX_ITEMS_PER_SEGMENT", "value": MAX_ITEMS_PER_SEGMENT}
        return {}

    def _etype_known(self, etype: str) -> bool:
        """Whether `etype_vocab` carries this etype. An unregistered one is out of vocabulary."""
        return self._connection.execute(_SELECT_ETYPE, (etype,)).fetchone() is not None

    def _tmp(self, row_kind: str, draft: object, ref: TmpRef) -> EntityId | None:
        """Resolve a `TmpRef`, or quarantine `OW_GRAPH_DANGLING_TMP` and remember that it dangled.

        06:624-627: *"A `TmpRef` referenced but never defined quarantines the whole Segment with
        `OW_GRAPH_DANGLING_TMP` -- graphrag's `filter_orphan_relationships` turned into a hard gate
        with a counter, keeping the rows instead of dropping them, because a hallucinated entity
        name is very often a real entity the extractor failed to emit a row for."* The quarantine
        row NAMES what dangled, in `detail`, and `end_run` forces the run's status to
        `quarantined`: that is the "whole Segment" half of the rule.
        """
        found = self._tmps.get(str(ref))
        if found is not None:
            return found
        self._dangled.append(str(ref))
        self._reject(row_kind, OW_GRAPH_DANGLING_TMP, draft, {"dangling_tmp": str(ref)})
        return None

    def _locate(self, row_kind: str, draft: object, at: Grounded) -> tuple[_Block, int, int] | None:
        """Turn a `Grounded` into `(block, ts_a, ts_b)`, or quarantine the reason it cannot be.

        Three refusals, three codes, and the order is scope before existence before grounding: a
        cite outside `allowed_cites` is `OW_GRAPH_OUT_OF_SCOPE_BLOCK` (GR9) whether or not the
        block exists, because the containment answer must not depend on what else is in the store;
        a cite in scope naming no live row is `OW_GRAPH_DANGLING_CITE`; and a quote the block's own
        text cannot witness is `OW_GRAPH_UNGROUNDED`.
        """
        cite, where = at
        if cite not in self._allowed:
            self._reject(row_kind, OW_GRAPH_OUT_OF_SCOPE_BLOCK, draft, {"cite": str(cite)})
            return None
        block = self._block(cite)
        if block is None:
            self._reject(row_kind, OW_GRAPH_DANGLING_CITE, draft, {"cite": str(cite)})
            return None
        if isinstance(where, TextSpan):
            return self._bounded(row_kind, draft, cite, block, where)
        return self._ground_quote(row_kind, draft, cite, block, where)

    def _bounded(
        self, row_kind: str, draft: object, cite: Cite, block: _Block, span: TextSpan
    ) -> tuple[_Block, int, int] | None:
        """The `span` arm of `_locate`. The host takes the offsets on trust and bounds-checks them.

        06:662-664 is why this arm is weaker than the quote arm and still legal: *"`span` means the
        host takes the driver's offsets on trust and can only bounds-check them; `quote` means the
        host locates the item itself against the block's own bytes."* `TextSpan.__post_init__` has
        already refused a negative or inverted pair, so what is left is the upper bound.
        """
        if span.b <= len(block.text):
            return block, span.a, span.b
        self._reject(
            row_kind,
            OW_GRAPH_UNGROUNDED,
            draft,
            {"cite": str(cite), "span": [span.a, span.b], "text_chars": len(block.text)},
        )
        return None

    def _ground_quote(
        self, row_kind: str, draft: object, cite: Cite, block: _Block, quote: str
    ) -> tuple[_Block, int, int] | None:
        """The `quote` arm of `_locate`: one `ground()` call and its three outcomes."""
        self._attempts += 1
        hit = ground(block.text, quote)
        if hit is None:
            self._ungrounded += 1
            self._reject(row_kind, OW_GRAPH_UNGROUNDED, draft, {"cite": str(cite), "quote": quote})
            return None
        ts_a, ts_b, occurrences = hit
        if occurrences > 1:
            self.diag(
                Diag(
                    code=OW_GRAPH_QUOTE_AMBIGUOUS,
                    severity="warning",
                    component="store.graph",
                    message=f"{quote!r} occurs {occurrences} times in {cite}; grounded the first",
                    block=BlockId(block.block_id),
                    detail={"occurrences": occurrences, "cite": str(cite)},
                )
            )
        return block, ts_a, ts_b

    def _clamp(self, row_kind: str, draft: object, claim: Trust) -> Trust:
        """Apply `MAX_TRUST_BY_METHOD`. An over-claim is RECORDED, never silently corrected.

        0002's header states that this file ships no trigger for the clamp -- *"Writing them as
        literal SQL here would create the second truth the parity requirement exists to forbid,
        because the ceiling lives in Python"* -- so this method is the enforcer. The quarantine row
        carries the driver's ORIGINAL claim (06:690), which is what makes over-claiming measurable
        in `ow graph doctor` instead of invisible. **The clamp is a ceiling, never a floor**: a
        draft claiming below the ceiling is written at its own claim.
        """
        method = self._identity().method
        ceiling = MAX_TRUST_BY_METHOD[method]
        if claim <= ceiling:
            return claim
        self._reject(
            row_kind,
            OW_GRAPH_TRUST_CLAMPED,
            draft,
            {"claimed": int(claim), "ceiling": int(ceiling), "method": method.value},
        )
        return ceiling

    def _reject(
        self,
        row_kind: str,
        code: str,
        draft: object,
        detail: Mapping[str, JsonValue] | None = None,
    ) -> int:
        """Route one internal rejection through the public `quarantine()`. Returns the sentinel.

        Every refusal in this module goes through here, so *"quarantine is the only disposal
        path"* is a property of the code rather than of a review: there is no second way out of a
        check, and a new check cannot invent one without adding a call to this method.
        """
        self.quarantine(row_kind, code, _draft_payload(draft), detail=dict(detail or {}))
        return QUARANTINED_ID

    # -- private: writes -----------------------------------------------------------------------

    def _converge(self, entity_id: int, trust: Trust) -> EntityId:
        """A second Pass proposing an entity that already exists. Trust may only go down."""
        self._connection.execute(_LOWER_ENTITY_TRUST, (int(trust), entity_id))
        return EntityId(entity_id)

    def _mint_entity(self, d: EntityDraft, scope: int, key: str, trust: Trust) -> EntityId:
        """Insert a new `entity` row, minting its id, its `cite` and its self-referential head."""
        entity_id = EntityId(int(self._connection.execute(_NEXT_ENTITY_ID).fetchone()[0]))
        self._connection.execute(
            _INSERT_ENTITY,
            (
                entity_id,
                f"e{entity_id}",
                scope,
                d.etype,
                key,
                d.title,
                d.raw_etype,
                entity_id,
                _METHOD_ORD[self._identity().method.name.lower()],
                int(trust),
                _mention_merkle(()),
                d.description,
            ),
        )
        return entity_id

    def _write_mention(
        self, d: MentionDraft, entity_id: EntityId, located: tuple[_Block, int, int]
    ) -> MentionId:
        """The `mention` INSERT plus the entity roll-up it implies."""
        block, ts_a, ts_b = located
        trust = self._clamp("mention", d, d.trust_claim)
        digest = ow128(b"ow.mention.1", [self._entity_key(entity_id), block.block_id, ts_a, ts_b])
        cursor = self._connection.execute(
            _INSERT_MENTION,
            (
                entity_id,
                block.block_id,
                self._segment().segment_id,
                ts_a,
                ts_b,
                d.surface,
                self._run_id,
                int(trust),
                d.score,
                d.score_kind,
                block.restriction_bits,
                digest,
            ),
        )
        written = cursor.rowcount != 0
        self._roll_up(entity_id, block.restriction_bits, trust)
        if not written:
            existing = self._connection.execute(
                _SELECT_MENTION, (block.block_id, ts_a, ts_b, entity_id, self._run_id)
            ).fetchone()
            return MentionId(int(existing[0]))
        self._emitted += 1
        return MentionId(int(cursor.lastrowid or 0))

    def _endpoints(self, d: EdgeDraft, symmetric: bool) -> tuple[EntityId, EntityId] | None:
        """Resolve an edge's two `TmpRef`s, refuse a self-edge, and order a symmetric pair."""
        src = self._tmp("edge", d, d.src)
        dst = self._tmp("edge", d, d.dst)
        if src is None or dst is None:
            return None
        if src == dst:
            self._reject("edge", OW_GRAPH_UNPARSED_ITEM, d, {"self_edge": int(src)})
            return None
        if symmetric and src > dst:
            return dst, src
        return src, dst

    def _write_edge(
        self,
        d: EdgeDraft,
        endpoints: tuple[EntityId, EntityId],
        located: tuple[_Block, int, int],
    ) -> EdgeId:
        """The `edge` INSERT, or the corroboration of the row already carrying this identity."""
        src, dst = endpoints
        block, ts_a, ts_b = located
        found = self._connection.execute(
            _SELECT_EDGE, (src, dst, d.relation, block.block_id, ts_a, self._run_id)
        ).fetchone()
        if found is not None:
            self._connection.execute(_CORROBORATE_EDGE, (int(found[0]),))
            return EdgeId(int(found[0]))
        cursor = self._connection.execute(
            _INSERT_EDGE,
            (
                src,
                dst,
                d.relation,
                d.role,
                block.block_id,
                ts_a,
                ts_b,
                d.bound_by,
                d.weight,
                self._run_id,
                int(self._clamp("edge", d, d.trust_claim)),
                d.score,
                d.score_kind,
                block.restriction_bits,
            ),
        )
        self._emitted += 1
        return EdgeId(int(cursor.lastrowid or 0))

    def _write_claim(
        self,
        d: ClaimDraft,
        subject: EntityId,
        obj: EntityId | None,
        located: tuple[_Block, int, int],
        precision: str | None,
    ) -> ClaimId:
        """The `claim` INSERT, or the id of the row already carrying this identity."""
        block, ts_a, ts_b = located
        found = self._connection.execute(
            _SELECT_CLAIM,
            (
                subject,
                -1 if obj is None else int(obj),
                "" if d.object_literal is None else d.object_literal,
                d.claim_type,
                block.block_id,
                ts_a,
                self._run_id,
            ),
        ).fetchone()
        if found is not None:
            return ClaimId(int(found[0]))
        claim_id = ClaimId(int(self._connection.execute(_NEXT_CLAIM_ID).fetchone()[0]))
        self._connection.execute(
            _INSERT_CLAIM,
            (
                claim_id,
                f"k{claim_id}",
                subject,
                obj,
                d.object_literal,
                d.object_datatype,
                d.claim_type,
                d.predicate,
                d.description,
                d.status,
                d.t_start,
                d.t_end,
                precision,
                block.block_id,
                ts_a,
                ts_b,
                block.quote,
                self._run_id,
                int(self._clamp("claim", d, d.trust_claim)),
                d.score,
                d.score_kind,
                block.restriction_bits,
            ),
        )
        self._emitted += 1
        return claim_id

    def _roll_up(self, entity_id: EntityId, restriction_bits: int, trust: Trust) -> None:
        """OR the block's `restriction_bits` upward and re-merkle `entity.mention_digest`.

        `entity.trust` is `MIN` over live mentions and `restriction_bits` is the OR over them
        (06:119-120), and both are properties this sink can maintain incrementally. `frequency`,
        `degree` and `doc_count` are NOT touched: they are computed over the whole `canonical_id`
        closure and GR16 makes the recount a post-run assertion that FAILS THE RUN on disagreement
        (06:181-190), so a per-mention increment here would be a second and wrong answer.
        """
        rows = self._connection.execute(_LIVE_MENTION_DIGESTS, (entity_id,)).fetchall()
        merkle = _mention_merkle(tuple(bytes(row[0]) for row in rows))
        self._connection.execute(_STAMP_ENTITY_BITS, (restriction_bits, merkle, entity_id))
        self._connection.execute(_LOWER_ENTITY_TRUST, (int(trust), entity_id))

    # -- private: reads ------------------------------------------------------------------------

    def _block(self, cite: Cite) -> _Block | None:
        """Resolve a `cite` to its live `block` row, memoised for the run.

        The `doc_ord` comes out of the cite's own grammar (03:274), which turns the lookup into a
        seek on `block_cite (doc_ord, cite)` rather than a scan of `block`.
        """
        key = str(cite)
        if key in self._blocks:
            return self._blocks[key]
        match = _CITE_GRAMMAR.match(key)
        found: _Block | None = None
        if match is not None:
            row = self._connection.execute(
                _SELECT_BLOCK, (int(match.group("doc_ord")), key)
            ).fetchone()
            if row is not None:
                found = _Block(
                    block_id=int(row[0]),
                    doc_ord=int(row[1]),
                    text="" if row[2] is None else str(row[2]),
                    quote=int(row[3]),
                    restriction_bits=int(row[4]),
                )
        self._blocks[key] = found
        return found

    def _cover_ord(self, cite: Cite) -> int:
        """The `segment_block.ord` a cite occupies -- *"IS the cover_bits bit index"* (06:112)."""
        block = self._block(cite)
        seg = self._segment()
        row = (
            None
            if block is None
            else self._connection.execute(
                _SELECT_SEGMENT_ORD, (block.block_id, seg.segment_id)
            ).fetchone()
        )
        if row is None:
            raise GraphError(
                f"cover() names {cite}, which is not a member of segment {seg.segment_id}: the "
                f"cover bitmap is indexed by segment_block.ord and has no bit for it",
                symbol=OW_GRAPH_UNPARSED_ITEM,
                fix="pass only cites the selector handed out for this Segment",
            )
        return int(row[0])

    def _cover_bits(self, lane: str) -> bytes:
        """This run's existing bitmap for `lane`, or a fresh 64-byte zero bitmap."""
        seg = self._segment()
        row = self._connection.execute(
            _SELECT_COVER, (seg.segment_id, lane, self._run_id)
        ).fetchone()
        return bytes(_COVER_BITMAP_BYTES) if row is None else bytes(row[0])

    def _entity_key(self, entity_id: EntityId) -> str:
        """`entity.key` -- `mention.digest`'s first input (06:192)."""
        row = self._connection.execute(_SELECT_ENTITY_KEY, (entity_id,)).fetchone()
        return "" if row is None else str(row[0])


def _cache_key(seg: SegmentRef, p: PassIdentity, allowed_cites: frozenset[Cite]) -> str:
    """`derive_run.cache_key` -- a 64-char `sha256_canonical` hex string.

    0002:189-194 fixes the TYPE and the reason: *"THE SAME TYPE AND THE SAME FUNCTION AS EVERY
    OTHER cache_key in the framework ... a 16-byte BLOB here under the same column name meant a
    reader could not tell whether a derive pass's cache identity was the key `with_cache` looks
    up. It is."* The FUNCTION is `omniweave_core.cache.cache_key()`, which is P4's and does not
    exist yet, and the INPUTS are printed nowhere. The identity computed here is the one the
    column's own comment implies -- the pass, its schema version, the input digest, the prompt
    fingerprint and the cite scope -- through `sha256_canonical`, which is what every other
    `cache_key` in the framework is built on. Reported; when `cache.cache_key()` lands this
    becomes one call to it.
    """
    return sha256_canonical(
        {
            "pass_id": p.pass_id,
            "driver_schema_v": p.driver_schema_v,
            "input_digest": seg.content_digest.hex(),
            "prompt_fp": None if p.prompt_fp is None else p.prompt_fp.hex(),
            "allowed_cites": sorted(str(cite) for cite in allowed_cites),
        }
    )
