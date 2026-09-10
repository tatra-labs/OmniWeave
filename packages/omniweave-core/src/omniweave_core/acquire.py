"""`acquire.fs.local`: the filesystem enumerator, the `unit` roster writer and the stat triple.

W3.8 of 16-roadmap.md:527 -- *"`acquire.fs`, the unit roster writer, `canonical_uri()`, the stat
index, `--scope`"* -- whose estimation basis is the sentence this module is organised around:
*"~22 MB of roster per 100k documents; the realpath / normcase / `\\\\?\\`-stripping normalisation
is the whole correctness surface and the reason `canonical_uri()` is one function"*.

**There is no normalisation in this file.** `canonical_uri()` is already built, in
`omniweave_core.identity`, and this module calls it at exactly two sites and no third:
`locator_for()` projects the root and `roster_row_of()` mints the `unit_uri`. That is not
tidiness: a walked path is normalised once, by the one function, or two spellings of one file
become two `unit` rows and every downstream join splits. `test_acquire.py` asserts the absence
structurally -- no `realpath`, no `normcase`, no `resolve(`, no `\\\\?\\` literal appears in this
module's source -- because the estimation basis names a second normaliser as the failure mode and a
comment saying "do not add one" is not a check.

## Where this driver lives, and why it is here rather than in a distribution of its own

The plan answers this twice and the two answers differ, so both are recorded and the reading that
ships is stated:

* [05-ingest-and-routing.md](../../../../../_plan/05-ingest-and-routing.md):278 -- *"Release 1
  ships four `acquire/1` drivers in the `omniweave` distribution"* -- with `acquire.fs.local` in
  the `day 1` column at :289.
* 02-architecture.md:329-334 -- *"`acquire/1` is a live Port with **no in-tree implementation** at
  release 1 ... Filesystem discovery is core-side, in `omniweave/run/discover.py`, which owns the
  connector cursors, and `unit.connector` defaults to `'fs'`. A shipped `acquire.fs.local` could
  not live in the `omniweave` distribution in any case: rule 3 would then demand the row
  `["omniweave_ports"]` for a package that also holds the Supervisor."* 02-architecture.md:1498,
  17-risks.md:887 and [ADR-3](../../../../../_plan/adr/0003-shipped-configuration.md):110-115 all
  restate it, and `tools/layers.toml`'s own header already transcribes the consequence: *"acquire/1
  is a live Port with no in-tree implementation at release 1, so there is no fifteenth"* line.

02 wins: it is the paragraph ADR-3 promotes to *"its sole superseding home"*, it is what
`tools/layers.toml` and `first_party.toml` are already built against, and the alternative would add
a fifteenth distribution row that 11-repo-layout.md section 1.2's fourteen-row table and section
3.2's fourteen-line `layers.toml` both forbid. So the fs walk is **host-side code, not a routed
driver**, exactly as 04-driver-system.md:2579 files it: *"the filesystem walk | it is the
enumerator, not a routed implementation | `omniweave/run/discover.py`"*.

That leaves the path. 02-architecture.md:472 homes the roster writer in `omniweave.run.discover`,
and `packages/omniweave/src/omniweave/` is a bare skeleton whose `run/` package is P4's (W4.3,
16-roadmap.md:543). A P3 work item cannot write into a P4 module that does not exist, so the
library half lands here, in `omniweave_core`, where 11-repo-layout.md section 2.1's four tests for
core membership put it: stdlib only, no loop, needed by more than one distribution's worth of
caller, and the sole home of a fact. **Choosing this path is our engineering call and not a plan
claim** -- 11-repo-layout.md section 1.3's tree of `omniweave-core` lists no `acquire.py` and no
`ingest/` package, while 05-ingest-and-routing.md:47 names a module `omniweave_core.ingest.locator`
that the tree also does not list. Both are reported.

## The two halves, and the seam between them

The file is in two parts and the seam is 04-driver-system.md section 1.5 obligation 2 -- *"the
driver proposes, the host commits ... no `block_id`, `unit_uri`, `segment_id` or `entity_id` ever
crosses the wire from a driver"*:

**The driver-shaped half** is `iter_candidates()` and `FsLocal`. It walks, stats, applies the
scope guards and emits `owroster-items/1` `candidate` records addressed by a per-invocation `tmp`
id and a *connector-local stable id* -- 05:152's *"the only identity a driver supplies and it is
**not** a `unit_uri`"*. It imports `omniweave_ports` and nothing else of ours, which is the import
set `tools/layers.toml` rule 3 would give it if it ever moved into a distribution of its own.

**The host half** is `roster_row_of()`, `write_roster()` and the tally. It mints the `unit_uri`
through `canonical_uri()` (obligation 2), stamps `unit.trust_class` from the caller's
`TrustClass` (obligation 3, 05:110 and :172), owns `unit.state` (05:378's state machine), and
writes `unit` plus one `ingest_scope` row. It is the only half that imports `omniweave_core`.

`FsLocal` therefore satisfies `omniweave_ports.ports.AcquireV1` structurally without ever being
able to mint a durable identity: it has no `canonical_uri` in scope by construction, because the
records it builds carry no field to put one in.

## Three properties this module exists to get right

**1. The stat triple is captured BEFORE the content read.** 02-architecture.md:472 --
*"the stat triple `(size, mtime_ns, indexed_at_ns)` **captured before the content read**"* -- and
05:344, which gives the reason as *"the stat triple is captured BEFORE the content read (charter
D6), so a write racing the read is caught"*. `fetch_local()` stats, then reads, and the read is an
injected callable so that the ordering is observable from a test rather than merely intended:
stat-after-read yields a triple that says the file was unchanged when it was not, and the next
incremental run then skips a document that changed mid-read. `stat_fresh()`'s third clause is the
other half of the same defence -- a file modified inside the mtime granularity window of the last
index cannot be *proven* unchanged, so it is not fresh.

**2. The roster upsert refreshes `last_seen_gen` and `cursor` and NOTHING ELSE.** That is 05:400
rule 5 verbatim, and it is load-bearing rather than terse: if enumeration overwrote
`size`/`mtime_ns`/`indexed_at_ns`, then `stat_fresh()` would compare the freshly written triple
against the very `stat` it was written from, be true for every unit forever, and no changed
document would ever be re-indexed. The narrow `SET` list is what keeps the stored triple a
*record of the last indexing* rather than a record of the last walk.

**3. `ingest_scope` accounts for every in-scope path.** 02-architecture.md:472 --
*"plus one `ingest_scope` row recording discovered vs indexed vs skipped"*. `ScopeTally` refuses
to be constructed unless `discovered == indexed + skipped` and `skipped == sum(skipped_why)`,
because a scan that discovers 100 and rosters 60 with no skipped row is forty silently lost
documents, and 07-store-and-retrieval.md:2184's absence gate 4 reads exactly these three numbers.
The plan does not print the summation rule; see `ScopeTally` for what it does print and how the
reading was derived.

Specified in 05-ingest-and-routing.md sections 1.1-1.5 (the `Locator` projection at :80-118, the
`owroster-items/1` record shapes at :128-190, the enumerate loop at :191-234, unit identity at
:235-275, `acquire.fs.local`'s roster row at :289, change detection at :337-377, the state machine
and the `[ingest]` block at :378-478), 02-architecture.md:329-334 and :472, 04-driver-system.md
sections 1.4-1.5 and 2.4, 07-store-and-retrieval.md section 3.8, and 16-roadmap.md:527.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Final, NamedTuple, Protocol

from omniweave_ports.types import (
    ArtifactKind,
    ArtifactRef,
    DriverError,
    DriverIO,
    DriverMetrics,
    DriverResult,
    FailureClass,
    Locator,
    ProbeEnv,
    ProbeStatus,
    ProbeVerdict,
    Scalar,
    UnitRef,
)

from omniweave_core.config import KEYS
from omniweave_core.errors import PolicyRefusal, StoreError
from omniweave_core.identity import canonical_uri
from omniweave_core.store.sqlite import BATCH_WAIT_MS, StoreThread, Unit

__all__ = [
    "CONNECTOR",
    "CURSOR_SEP",
    "DEFAULT_EXCLUDE",
    "DEFAULT_FOLLOW_SYMLINKS",
    "DEFAULT_HIDDEN",
    "DEFAULT_INCLUDE",
    "DEFAULT_MAX_DEPTH",
    "DEFAULT_MAX_UNIT_BYTES",
    "DISCOVERED",
    "LOCATOR_SCHEME",
    "MAX_UNITS_PER_CALL",
    "MTIME_GRANULARITY_NS",
    "PLAN_BATCH",
    "SCOPE_RULES",
    "SCOPE_UPSERT_SQL",
    "SKIP_PATH_OUTSIDE_ROOTS",
    "SKIP_REASONS",
    "SKIP_TOO_LARGE",
    "SKIP_UNREADABLE",
    "TMP_FIRST",
    "UNIT_COLUMNS",
    "UNIT_UPSERT_SQL",
    "CandidateRecord",
    "FetchedRecord",
    "FsLocal",
    "IngestGuards",
    "RosterRow",
    "Scope",
    "ScopeTally",
    "StatTriple",
    "Tally",
    "TrustClass",
    "fetch_local",
    "in_scope",
    "iter_candidates",
    "locator_for",
    "read_bounded",
    "refuse_unmigrated",
    "roster_row_of",
    "scan",
    "scope_id_for",
    "stat_fresh",
    "walk_order",
    "write_roster",
]


class _Rows(Protocol):
    """What a roster transaction needs of the store thread's connection, and no more.

    **`import sqlite3` is banned outside `omniweave_core/store/`** (INV-17 / ST1, enforced as an
    `ast` check by `tools/gate_semgrep.py:276`), and this module is outside it. `Unit.run` is
    typed `Callable[[sqlite3.Connection], object]` in `store/sqlite.py`, which is legal there and
    unwritable here -- so the closures below annotate their one parameter structurally. Two
    methods, because a batch of roster upserts is one `executemany` and the coverage row is one
    `execute`, and a wider Protocol would be a claim about a boundary this module does not own.
    """

    def execute(self, sql: str, parameters: Mapping[str, object] = ..., /) -> Any: ...

    def executemany(self, sql: str, parameters: Sequence[Mapping[str, object]], /) -> Any: ...


# --------------------------------------------------------------------------------------------
# 1. The constants, each transcribed from one plan line
# --------------------------------------------------------------------------------------------

CONNECTOR: Final[str] = "fs"
"""`unit.connector`'s value for this enumerator.

02-architecture.md:331 and :472 both fix it: *"`unit.connector` defaults to `'fs'`"*, and the
column carries `DEFAULT 'fs'` in `0004_runtime.sql:47`. It is written explicitly all the same --
a column default is a store fact and this is the enumerator's claim about itself, and 05:136 makes
the value checkable ("checked against the card's own id, so one connector cannot mint into
another's namespace").
"""

LOCATOR_SCHEME: Final[str] = "file"
"""`Locator.scheme` for `SourceKind.FILE` and `SourceKind.DIR` alike (05:87's table row).

Both kinds project onto `file`; the difference between one path and a walked tree is
`SourceLocator.recursive`, not the scheme. `canonical_uri()` reads this scheme and produces the
bare PATH form -- no `file:` prefix -- which is what 05:87's *"`canonical_uri()`'s path form of
`ref`"* means.
"""

DISCOVERED: Final[str] = "discovered"
"""`unit.state` for a freshly rostered unit.

02-architecture.md:472 (*"`state='discovered'`"*) and the first node of 05:381's state machine.
`op.identify` cannot run yet -- there are no bytes -- which is why the roster writer never sets
`content_sha256`, `part_count` or `format`.
"""

CURSOR_SEP: Final[str] = "\x00"
"""The separator inside `acquire.fs.local`'s cursor: `<relpath>\\0<inode>` (05:289).

A NUL, because it is the one byte a POSIX or Windows path cannot contain -- so the two halves are
recoverable by `split` with no escaping, and 05:131's own example record spells it `\\u0000`.
"""

MTIME_GRANULARITY_NS: Final[int] = 2_000_000_000
"""`MTIME_GRANULARITY_NS(2e9)` from 05:339 and `0004_runtime.sql:84`.

Two seconds, which is FAT's mtime granularity and the coarsest a mounted filesystem still hands
out. It appears only in `stat_fresh()`'s third clause.
"""

DEFAULT_INCLUDE: Final[tuple[str, ...]] = ("**/*",)
DEFAULT_EXCLUDE: Final[tuple[str, ...]] = (
    "**/.git/**",
    "**/node_modules/**",
    "**/.omniweave/**",
    "**/~$*",
)
DEFAULT_FOLLOW_SYMLINKS: Final[bool] = False
DEFAULT_MAX_DEPTH: Final[int] = 32
DEFAULT_MAX_UNIT_BYTES: Final[int] = 2_147_483_648
DEFAULT_HIDDEN: Final[bool] = False
"""The `[ingest]` defaults, transcribed from 05:435-447.

`max_unit_bytes` is 2 GiB and `05:437`'s comment says where it is enforced: *"Enforced in
enumerate, then by a bounded read"* -- both halves are in this module (`iter_candidates` refuses a
candidate above it before `fetch` is ever called; `read_bounded` reads `limit + 1` bytes and
raises if the extra byte arrives). `~$*` is Office's lock-file prefix.

**These are module constants and not `config.KEYS` rows, and that is a gap rather than a choice.**
`omniweave_core.config.KEYS` carries `cache corpora drivers graph licence limits observe retrieval
roots runtime schema serve services store targets` and no `ingest` table at all, while 05:433-478
specifies `[ingest]` and `[ingest.url]` in full and says every key *"carries an `OMNIWEAVE_*` twin
and is classified for `tools/config_axes.toml` (G18) -- all `operational` except `normalize`"*.
`config.py` is not this wave's file; the required rows are reported.
"""

MAX_UNITS_PER_CALL: Final[int] = 5_000
"""`[acquire] max_units_per_call` (04-driver-system.md:616, 05:210).

*"a million-file tree is 200 invocations rather than one, each of which the water mark can end
early"*. `iter_candidates()` stops after this many `candidate` records and the last one's
`next_cursor` is where the next `INVOKE` resumes -- so the bound is what makes the walk restartable
rather than what makes it incomplete.
"""

PLAN_BATCH: Final[int] = int(KEYS["runtime.plan_batch"].default)  # type: ignore[arg-type]
"""`[runtime] plan_batch = 512` -- roster rows per transaction (02-architecture.md:472).

Read from `config.KEYS` rather than restated, so the number has one home; `store/sqlite.py` reads
`[store] wal_heal_mb` and `[retrieval] snapshot_ms` the same way and for the same reason.
"""

TMP_FIRST: Final[str] = "c/000001"
"""The first `candidate` record's `tmp` id.

05:133: *"the per-invocation record address, unique within one `enumerate` and **dense from
`c/000001`**"*. Dense means the host can detect a dropped line by arithmetic, which is why the
counter restarts at 1 on every `INVOKE` and why it is not a path or a hash.
"""

SKIP_TOO_LARGE: Final[str] = "too_large"
SKIP_UNREADABLE: Final[str] = "unreadable"
SKIP_PATH_OUTSIDE_ROOTS: Final[str] = "path_outside_roots"
SKIP_REASONS: Final[frozenset[str]] = frozenset(
    {SKIP_TOO_LARGE, SKIP_UNREADABLE, SKIP_PATH_OUTSIDE_ROOTS}
)
"""The keys this enumerator writes into `ingest_scope.skipped_why`.

`skipped_why` is `TEXT NOT NULL DEFAULT '{}'` (07 section 3.8) -- a JSON map of reason to count --
and **no plan document enumerates its vocabulary**. 05:773 and :3048 name one member for the
container walker (a zip-slip member path), and 05:328/:374 name `too_large` and `filtered` as
`unit.acq_failure_class` values, which is a different column. So this is a THREE-MEMBER set for
this connector rather than a closed framework vocabulary, and it is deliberately not a `StrEnum`:
inventing a closed vocabulary the plan does not state would be the defect, and a later connector
adding `zip_slip` must not have to widen a core enum to do it.

`too_large` is 05:328's pre-fetch guard. `unreadable` is an `OSError` on the `stat` -- a file
deleted or permission-revoked between `scandir` and `stat`, which is 07:2229's *"a unit whose path
is removed after `ingest_scope` was written"* observed one step earlier. `path_outside_roots` is
`OW_PATH_OUTSIDE_ROOTS` / `OW-A-007`, raised where 05:70 puts it: *"a symlink in an untrusted tree
is the cheapest way out of `[roots] source`, and `OW_PATH_OUTSIDE_ROOTS` is a refusal, not a
warning"*.
"""

SCOPE_RULES: Final[tuple[str, ...]] = ("explicit", "inherited")
"""`unit.scope_rule`'s CHECK domain, from `0004_runtime.sql:81`.

**Declared by the charter's DDL and by no plan prose anywhere.** A grep of `_plan/*.md` finds
`scope_rule` in the DDL transcription and nowhere else, so the column has a constraint and no
stated semantics. The reading taken here is the only one under which the two values differ: a path
the operator named is `explicit`, a member the walk found under it is `inherited`. `scan()` takes
it as a parameter defaulting to `"inherited"` and `NULL` stays legal, because the DDL permits it
and "unknown" is the honest value for a caller that has no opinion. Reported.
"""


# --------------------------------------------------------------------------------------------
# 2. The value types
# --------------------------------------------------------------------------------------------


class TrustClass(StrEnum):
    """The enum behind `unit.trust_class`. 05:57-59.

    *"It is **not** `TrustTier` (a driver-supply-chain fact) and **not** `Trust` (a Block's
    provenance tier). Three enums, three jobs."* (05:75-77.)

    It never crosses S4: 05:110 and :172 both say *"The host stamps `unit.trust_class` from
    `SourceLocator.trust_class`"*, which is obligation 3, and 05:112-118 gives the consequence --
    *"a connector can neither raise nor lower its own audit sample"*. `INTERNAL` is
    `SourceLocator.trust_class`'s own default (05:70); the `untrusted_external` default belongs to
    a card declaring `[capability.acquire] trust_class_declared = false` (05:116), which is why
    `0004_runtime.sql:76` gives the column NOT NULL and no DEFAULT.
    """

    INTERNAL = "internal"
    UNTRUSTED_EXTERNAL = "untrusted_external"


@dataclass(frozen=True, slots=True)
class Scope:
    """The runtime's ingest scope: roots, globs and a corpus.

    **Two definition sites, and they disagree by one field.** 02-architecture.md:471 prints the
    constructor as `Scope(roots, include, exclude)` -- three members -- while
    `_plan/_notes/terminology.md`:763 (the terminology lock, homing the type at 08-runtime.md
    section 1.3) and 03-document-model.md:2817 both describe it as *"roots, globs and a corpus"*.
    08-runtime.md itself never prints the type; its only mention is :413, *"Scope is the unit of
    cancellation because it is the unit somebody actually withdraws"*. So `corpus` is a fourth
    field with a default, which keeps 02:471's positional spelling constructing unchanged and
    keeps the lock's member present. The divergence is reported rather than smoothed.

    `include` and `exclude` are `fnmatch` globs against the path relative to `roots.source`
    (05:63). They appear here AND in `[ingest]` (05:435-436) because they are the same fact at two
    layers: `[ingest]` is the configured default and a `Scope` is what one invocation resolved to.
    05:105 fixes which one is authoritative -- the globs *"are re-applied by the host's enumerate
    loop, which is the authoritative guard: a driver that ignores them can waste syscalls but can
    never widen the scope"*.

    This type is 08-runtime.md's and P4's `omniweave.run` is where `run(scope, ctx)` will take it;
    it is declared here because W3.8 needs the walk's input at P3 and nothing else declares it yet.
    """

    roots: tuple[str, ...]
    include: tuple[str, ...] = DEFAULT_INCLUDE
    exclude: tuple[str, ...] = DEFAULT_EXCLUDE
    corpus: str | None = None

    def __post_init__(self) -> None:
        """A scope with no root walks nothing, which is never what a caller meant."""
        if not self.roots:
            raise ValueError("a Scope names at least one root (02-architecture.md:471)")


@dataclass(frozen=True, slots=True)
class IngestGuards:
    """The `[ingest]` guards the enumerate loop applies, per 05:433-447.

    Separate from `Scope` because 02-architecture.md:471's `Scope` carries three fields and these
    are four more; folding them in would widen a type two other documents describe. They are the
    pre-fetch guards of 05:196 -- *"per candidate, before any fetch: glob, depth, hidden, skip and
    size guards"* -- and 05:325-332's ordering is why `max_unit_bytes` lives here rather than in a
    routing rule: *"`GATE` evaluates on a `unit` row in state `identified`, which is after
    `fetch()` -- so a rule cannot be what keeps a 2 GB file from being read."*

    `follow_symlinks` defaults to `False` for 05:70's reason and is never `True` for an untrusted
    tree. It bounds the WALK; it does not bound identity -- `canonical_uri()` calls `realpath`
    unconditionally, so a symlink and its target are one `unit_uri` whether or not the walk
    descended the link.
    """

    follow_symlinks: bool = DEFAULT_FOLLOW_SYMLINKS
    max_depth: int = DEFAULT_MAX_DEPTH
    max_unit_bytes: int = DEFAULT_MAX_UNIT_BYTES
    hidden: bool = DEFAULT_HIDDEN

    def __post_init__(self) -> None:
        if self.max_depth < 1:
            raise ValueError("max_depth is at least 1: a root's own entries are depth 1")
        if self.max_unit_bytes < 1:
            raise ValueError("max_unit_bytes is a positive byte ceiling")


class StatTriple(NamedTuple):
    """`(size, mtime_ns, indexed_at_ns)` -- `unit`'s three stat columns.

    02-architecture.md:472 names it *"the stat triple `(size, mtime_ns, indexed_at_ns)` **captured
    before the content read**"* and `0004_runtime.sql:54` carries the same three columns with the
    same comment. `indexed_at_ns` is the third member and it is NOT a member the filesystem
    supplies: it is when this run indexed the unit, injected by the caller, because `time.time` is
    banned in library code (02-architecture.md:392) and a clock is a parameter.

    D5's separate `unit_stat` table is struck (`0004_runtime.sql:85`, charter section 5 X25), so
    "the stat index" of 16-roadmap.md:527 is these three columns plus `unit.derived`, and there is
    no fourth table to write.
    """

    size: int
    mtime_ns: int
    indexed_at_ns: int


@dataclass(frozen=True, slots=True)
class CandidateRecord:
    """One `candidate` record of `owroster-items/1`. 05:128-160.

    **Metadata only.** 05:399 rule 4: *"`enumerate` emits metadata only. A `candidate` record
    never carries bytes."* And four classes of key are absent by construction (05:161-176), each
    because the host owns the fact: no `unit_uri`, no `trust_class`, no `state`/`gen`/
    `last_seen_gen`, and no money. That absence is the whole point of the type -- 05:152 says the
    `id` is *"the only identity a driver supplies and it is **not** a `unit_uri`"* -- so the
    dataclass has no field any of them could be written to, and `record()` cannot emit one.

    `stable_id` is the wire key `id`; the field is renamed because `id` shadows a builtin, and the
    rename is one-way and local -- `record()` writes `"id"`.

    `next_cursor` is *"the resume token **after** this record"* (05:137) and for this connector it
    is `<relpath>\\0<inode>` (05:289). `None` would mean "not resumable", which this connector is
    not allowed to say: it declares `addressing = "uri_with_cursor"` and 05:137 makes emitting
    `null` under that declaration a conformance failure.
    """

    tmp: str
    stable_id: str
    connector: str = CONNECTOR
    next_cursor: str | None = None
    size: int | None = None
    mtime_ns: int | None = None
    etag: str | None = None
    media_type_hint: str | None = None
    labels: Mapping[str, Scalar] = field(default_factory=dict)

    def record(self) -> dict[str, object]:
        """The NDJSON object, in 05:130-132's own key order."""
        return {
            "t": "candidate",
            "tmp": self.tmp,
            "id": self.stable_id,
            "connector": self.connector,
            "next_cursor": self.next_cursor,
            "size": self.size,
            "mtime_ns": self.mtime_ns,
            "etag": self.etag,
            "media_type_hint": self.media_type_hint,
            "labels": dict(self.labels),
        }


@dataclass(frozen=True, slots=True)
class FetchedRecord:
    """The single `fetched` record `fetch()` emits beside the `raw_bytes` blob. 05:141-148.

    *"`fetched` therefore carries no identity at all: `fetch` is invoked with a host-built
    `UnitRef` and the `RESULT` frame's `unit_index` says which unit it answers"* (05:184-186).

    `content_sha256` is over the *normalised load-bearing bytes* and `source_sha256` over the raw
    bytes. For every format this connector reaches at P3 they are equal, because 05:271's
    normaliser table gives *"everything else | none | raw bytes are hashed"* -- and 05:261 says
    that case sets `unit.normalizer = NULL` and records `OW-C-041`, a code with no `codes.toml`
    row. Reported; this module writes neither column, so it raises nothing.
    """

    content_sha256: str
    source_sha256: str
    bytes: int
    blob_ref: str
    media_type_hint: str | None = None
    etag: str | None = None
    fetched_at_ns: int = 0

    def record(self) -> dict[str, object]:
        """The NDJSON object, in 05:135-136's own key order."""
        return {
            "t": "fetched",
            "content_sha256": self.content_sha256,
            "source_sha256": self.source_sha256,
            "bytes": self.bytes,
            "blob_ref": self.blob_ref,
            "media_type_hint": self.media_type_hint,
            "etag": self.etag,
            "fetched_at_ns": self.fetched_at_ns,
        }


@dataclass(frozen=True, slots=True)
class RosterRow:
    """One `unit` row as the host is about to write it. Every column here is the host's.

    02-architecture.md:472's cell, column by column: `unit_uri = canonical_uri(path)`,
    `connector='fs'`, `state='discovered'`, and the stat triple. `trust_class` is stamped from
    `SourceLocator.trust_class` (obligation 3) and `last_seen_gen` from the run's generation
    (05:365-368's deletion rule reads it). `derived` carries the candidate's `labels` and its
    `etag` -- 05:139 *"a flat `Mapping[str, Scalar]` written to `unit.derived`"*, 05:135 *"opaque,
    stored on `unit.derived["etag"]`"*.

    `content_sha256`, `normalizer`, `media_type`, `format`, `bytes` and `part_count` are absent:
    a `discovered` unit has had no bytes read, and writing a NULL into a column another state owns
    is how a state machine acquires a second writer.
    """

    unit_uri: str
    cursor: str | None
    stat: StatTriple
    trust_class: TrustClass
    last_seen_gen: int
    connector: str = CONNECTOR
    state: str = DISCOVERED
    derived: Mapping[str, object] = field(default_factory=dict)
    scope_rule: str | None = None

    def __post_init__(self) -> None:
        if self.scope_rule is not None and self.scope_rule not in SCOPE_RULES:
            raise ValueError(
                f"unit.scope_rule is one of {SCOPE_RULES} or NULL "
                f"(0004_runtime.sql:81); got {self.scope_rule!r}"
            )

    def params(self) -> dict[str, object]:
        """The named parameters of `UNIT_UPSERT_SQL`.

        `derived` is serialised with sorted keys and no spaces: `unit.derived` is a TEXT column
        holding JSON, and two runs over one unchanged tree must produce byte-identical rows or
        `ow store diff` reports a difference that is not one.
        """
        return {
            "unit_uri": self.unit_uri,
            "connector": self.connector,
            "cursor": self.cursor,
            "state": self.state,
            "size": self.stat.size,
            "mtime_ns": self.stat.mtime_ns,
            "indexed_at_ns": self.stat.indexed_at_ns,
            "derived": json.dumps(self.derived, sort_keys=True, separators=(",", ":")),
            "trust_class": str(self.trust_class),
            "last_seen_gen": self.last_seen_gen,
            "scope_rule": self.scope_rule,
        }


@dataclass(frozen=True, slots=True)
class ScopeTally:
    """One `ingest_scope` row: what a scan discovered versus indexed versus skipped, and why.

    The DDL is 07-store-and-retrieval.md section 3.8's, transcribed at `0003_index.sql:393`, and
    the comment above it is the contract: *"AN ABSENT ROW MEANS 'COVERAGE UNKNOWN', NEVER 'NOTHING
    WAS EXCLUDED'. Absence gate 4 reads this and fires when any scope row in view has
    discovered > indexed, complete = 0, OR DOES NOT EXIST."*

    **The summation rule is derived, and here is the derivation.** No plan document states one.
    07:1946 prints a failing gate as `ingest_scope: discovered 17, indexed 16, complete=0` and
    names no `skipped` figure; 07:2184 gives gate 4's trigger as `discovered > indexed`. Two
    readings of `discovered` fit that: every directory entry the walk touched, or every path that
    was in scope. Under the first, an ordinary run with the shipped `exclude` defaults
    (`**/.git/**`, `**/node_modules/**`) always reports `discovered > indexed` and gate 4 degrades
    every corpus, which makes the gate carry no information -- so `discovered` counts paths that
    passed the globs, the hidden rule and the depth bound, and a glob-excluded path is not
    discovered at all. What remains is either rostered (`indexed`) or refused by a guard
    (`skipped`), so `discovered == indexed + skipped` -- and `__post_init__` enforces it, because
    a scan that discovers 100 and rosters 60 with no skipped row is forty documents lost in
    silence.

    `skipped == sum(skipped_why.values())` for the same reason one step down: a count without a
    reason is a number nobody can act on, and 05:773's *"skipped and **counted** in
    `ingest_scope.skipped_why`"* puts the reason and the count in the same sentence.

    `discovered` counts CANDIDATE RECORDS and not distinct `unit_uri`s. Two spellings of one file
    -- a junction and its target -- are two candidates and one unit, and deduplicating in the
    enumerator would need a set of every uri in the corpus, against 05:208's bound of *"one record
    plus one 512-row batch"*. 05:400 rule 5's `ON CONFLICT` upsert is where they converge, which
    is the same mechanism that makes two concurrent `ow ingest` processes converge. Reported: the
    plan does not say which the column counts.

    `complete` is `0` for a scan that stopped early -- `max_units_per_call`, a backpressure pause
    (05:427), a cancelled run -- and 05:371 is why it matters: *"An **incomplete** scan never
    marks anything out of scope."*
    """

    scope_id: str
    discovered: int
    indexed: int
    skipped: int
    scanned_at_ns: int
    complete: bool
    skipped_why: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("discovered", "indexed", "skipped"):
            if getattr(self, name) < 0:
                raise ValueError(f"ingest_scope.{name} is a count")
        if self.discovered != self.indexed + self.skipped:
            raise ValueError(
                f"ingest_scope arithmetic: discovered {self.discovered} != indexed "
                f"{self.indexed} + skipped {self.skipped}; a discovered path is either "
                f"rostered or refused, and the difference is documents lost in silence"
            )
        total = sum(self.skipped_why.values())
        if total != self.skipped:
            raise ValueError(
                f"ingest_scope.skipped_why sums to {total} and skipped is {self.skipped}; "
                f"every skip carries its reason (05-ingest-and-routing.md:773)"
            )

    def params(self) -> dict[str, object]:
        """The named parameters of `SCOPE_UPSERT_SQL`."""
        return {
            "scope_id": self.scope_id,
            "discovered": self.discovered,
            "indexed": self.indexed,
            "skipped": self.skipped,
            "skipped_why": json.dumps(
                dict(self.skipped_why), sort_keys=True, separators=(",", ":")
            ),
            "scanned_at_ns": self.scanned_at_ns,
            "complete": int(self.complete),
        }


class Tally:
    """The mutable accumulator behind one `ScopeTally`.

    Deliberately not a frozen dataclass: a streaming scan counts as it goes, and the alternative
    -- rebuilding a frozen record per candidate -- would allocate once per document across a
    100k-document walk to express the same three integers. `freeze()` is where the value type
    appears, and it is the only place the arithmetic is checked, so a caller cannot get a
    `ScopeTally` whose numbers do not add up.

    **`freeze()` only balances for a full `scan()`.** The two halves fill different counters:
    `iter_candidates()` calls `discover()` and `skip()`, and only the host half calls `roster()`
    -- because "was it rostered" is a question a driver cannot answer (obligation 2). A tally
    driven by `iter_candidates()` alone therefore has `discovered > indexed + skipped` and
    `freeze()` raises, which is the correct outcome rather than an inconvenience: `ingest_scope`
    is the host's row (`ports.py:66`, 04:339), and a driver-side coverage number would be the
    connector reporting the figure the host exists to check. `FsLocal.enumerate` keeps its tally
    local and discards it for exactly that reason.
    """

    __slots__ = ("_complete", "_discovered", "_indexed", "_why")

    def __init__(self) -> None:
        self._discovered = 0
        self._indexed = 0
        self._why: dict[str, int] = {}
        self._complete = False

    @property
    def discovered(self) -> int:
        return self._discovered

    @property
    def indexed(self) -> int:
        return self._indexed

    @property
    def skipped(self) -> int:
        return sum(self._why.values())

    @property
    def skipped_why(self) -> Mapping[str, int]:
        return dict(self._why)

    @property
    def complete(self) -> bool:
        return self._complete

    def discover(self) -> None:
        """One path passed the globs, the hidden rule and the depth bound."""
        self._discovered += 1

    def roster(self) -> None:
        """One discovered path became a `unit` row."""
        self._indexed += 1

    def skip(self, reason: str) -> None:
        """One discovered path was refused by a guard, with its reason."""
        if reason not in SKIP_REASONS:
            raise ValueError(f"{reason!r} is not one of this connector's {sorted(SKIP_REASONS)}")
        self._why[reason] = self._why.get(reason, 0) + 1

    def finish(self) -> None:
        """The walk ran to exhaustion. Only then is `ingest_scope.complete` 1."""
        self._complete = True

    def freeze(self, scope_id: str, *, scanned_at_ns: int) -> ScopeTally:
        """The `ingest_scope` row, with its arithmetic checked."""
        return ScopeTally(
            scope_id=scope_id,
            discovered=self._discovered,
            indexed=self._indexed,
            skipped=self.skipped,
            skipped_why=self.skipped_why,
            scanned_at_ns=scanned_at_ns,
            complete=self._complete,
        )


# --------------------------------------------------------------------------------------------
# 3. The driver-shaped half: the walk, the guards, the `candidate` stream
# --------------------------------------------------------------------------------------------


def walk_order(relpath: str) -> tuple[str, ...]:
    """The total order the walk emits in, as a sortable key.

    The walk is depth-first with each directory's entries sorted by name, and that order is
    exactly lexicographic order on the tuple of path segments -- which is *not* lexicographic
    order on the joined string. `a/b` and `a.txt` are the witness: `"a" < "a.txt"` so the walk
    descends `a/` first and emits `a/b` before `a.txt`, while `"a.txt" < "a/b"` as strings,
    because `.` (0x2E) sorts below `/` (0x2F).

    That difference is the whole reason this function exists. Cursor resumption compares against
    a stored `<relpath>` and 05:208 requires `enumerate` to be resumable *"from any emitted
    `next_cursor`"*; a string compare would silently skip or re-emit a run of files whenever a
    directory name is a prefix of a sibling file name. A skip-until-seen resume would be immune
    to the ordering but not to deletion -- if the cursor's own path is gone, nothing is ever seen
    and the whole remaining tree is dropped -- so the compare is on this key.
    """
    return tuple(relpath.split("/"))


def in_scope(relpath: str, scope: Scope, guards: IngestGuards) -> bool:
    """The glob, hidden and depth guards, for one path relative to the scope root.

    `include` and `exclude` are `fnmatch` globs against the relative path (05:63), matched
    case-sensitively: `fnmatch.fnmatch` lower-cases both sides through `os.path.normcase` on
    Windows, which would make one pattern behave differently on two platforms and put a second
    case fold in the code path `canonical_uri()` already owns. Exclude wins over include, because
    05:436's shipped `exclude` list is a list of things that must not be indexed and an `include`
    of `**/*` matches all of them.

    **One documented widening of `fnmatch`, and it is ours rather than the plan's.** A pattern
    beginning `**/` is also matched against the path with that prefix removed. Without it the
    shipped default `exclude = [..., "**/node_modules/**", ...]` (05:436) does not exclude a
    `node_modules/` directory at the top of the scope root: `fnmatch` translates `**/x/**` to the
    regular expression `.*/x/.*`, and `node_modules/react/index.js` has no leading separator to
    match `.*/`. `.git` and `.omniweave` escape the same hole only because they are dotfiles and
    `hidden = false` catches them, which leaves `node_modules` -- the one non-dotted member of the
    list -- genuinely unexcluded at the root. Reported.

    `hidden = false` excludes a path *"unless named explicitly"* (05:447): a dot-prefixed segment
    anywhere in the relative path excludes it, unless an `include` pattern names that segment
    literally rather than through a wildcard.
    """
    segments = relpath.split("/")
    if len(segments) > guards.max_depth:
        return False
    hidden_here = not guards.hidden and any(part.startswith(".") for part in segments)
    named = any(_names_hidden_explicitly(pattern, segments) for pattern in scope.include)
    if hidden_here and not named:
        return False
    if not any(_glob(relpath, pattern) for pattern in scope.include):
        return False
    return not any(_glob(relpath, pattern) for pattern in scope.exclude)


def _glob(relpath: str, pattern: str) -> bool:
    """`fnmatchcase`, plus the documented `**/` relaxation of `in_scope`."""
    if fnmatchcase(relpath, pattern):
        return True
    return pattern.startswith("**/") and fnmatchcase(relpath, pattern[3:])


def _names_hidden_explicitly(pattern: str, segments: Sequence[str]) -> bool:
    """Whether `pattern` names this path's dotted segments literally.

    05:447's `hidden = false` says dotfiles are excluded *"unless named explicitly"*, and the
    distinction that makes the sentence mean anything is literal versus wildcard: `include =
    [".github/**"]` is a caller asking for `.github`, while `include = ["**/*"]` is not a caller
    asking for `.ssh/id_rsa`. So every dotted segment of the path must appear verbatim as a
    segment of the pattern.
    """
    literal = frozenset(pattern.split("/"))
    return all(part in literal for part in segments if part.startswith("."))


def iter_candidates(
    locator: Locator,
    scope: Scope,
    guards: IngestGuards,
    *,
    tally: Tally,
    max_units: int = MAX_UNITS_PER_CALL,
    scandir: Callable[[str], Iterable[os.DirEntry[str]]] = os.scandir,
) -> Iterator[CandidateRecord]:
    """Walk `locator.target` and emit `owroster-items/1` `candidate` records.

    **This is the driver-shaped half and it mints no durable identity.** It knows the relative
    path and the inode; it does not know, and cannot express, a `unit_uri`, a `trust_class` or a
    `state` (04-driver-system.md section 1.5 obligation 2, 05:161-176). `canonical_uri` is not
    called anywhere below this line.

    The loop is 05:191-234's, in its order: entries buffered per directory and sorted by name,
    `walk_order` deciding what a cursor has already covered, then *"per candidate, before any
    fetch: glob, depth, hidden, skip and size guards"* (05:196). The generator yields; it never
    materialises a list, which is what makes 05:208's *"Peak host residency is one record plus one
    512-row batch -- a few hundred KiB -- whatever the corpus size"* true of this function and not
    merely of its caller. A backpressure pause is the caller stopping its `for` loop, which is
    05:427's *"the host **stops reading** the `owroster-items/1` stream between 512-row batches"*
    expressed as a generator rather than as a flag.

    `tally.finish()` is called only if the walk exhausts the tree without hitting `max_units`, so
    a truncated call cannot be mistaken for a complete scan -- 05:371, *"An **incomplete** scan
    never marks anything out of scope"*.

    `scandir` is injected for the same reason `store/sqlite.py` injects `factory`: it is the seam
    a test uses to observe the order the walk reads directories in, and it is `os.scandir` in
    every production call.

    A `stat` that raises is a `skipped_why["unreadable"]` and not a crash: a file can be deleted
    between the `scandir` and the `stat`, and a corpus scan that dies on one vanished temp file is
    a scan nobody can run twice.
    """
    root = Path(locator.target)
    after = walk_order(locator.cursor.split(CURSOR_SEP, 1)[0]) if locator.cursor else None
    emitted = 0
    for relpath, entry, depth in _walk(root, guards, scandir=scandir):
        if not in_scope(relpath, scope, guards):
            continue
        if after is not None and walk_order(relpath) <= after:
            continue
        tally.discover()
        try:
            info = entry.stat(follow_symlinks=guards.follow_symlinks)
        except OSError:
            tally.skip(SKIP_UNREADABLE)
            continue
        if info.st_size > guards.max_unit_bytes:
            # 05:325-330 mechanism 1: refused BEFORE `fetch` is called, so no blob is written and
            # no bytes are read. Mechanism 2 is `read_bounded`, for the `size = null` case.
            tally.skip(SKIP_TOO_LARGE)
            continue
        emitted += 1
        yield CandidateRecord(
            tmp=f"c/{emitted:06d}",
            stable_id=relpath,
            connector=CONNECTOR,
            next_cursor=f"{relpath}{CURSOR_SEP}{_inode(entry, info)}",
            size=info.st_size,
            mtime_ns=info.st_mtime_ns,
            labels={"walk_depth": depth},
        )
        if emitted >= max_units:
            return
    tally.finish()


def _walk(
    root: Path,
    guards: IngestGuards,
    *,
    scandir: Callable[[str], Iterable[os.DirEntry[str]]],
) -> Iterator[tuple[str, os.DirEntry[str], int]]:
    """Depth-first, each directory's entries sorted by name; yields `(relpath, entry, depth)`.

    Explicitly stacked rather than recursive, because `[ingest] max_depth = 32` bounds the tree
    and not the interpreter, and a 32-deep recursion that a caller raised to 4,096 would be a
    `RecursionError` in the middle of a corpus scan.

    `depth` is the number of segments in the relative path, which is what 05:132's own example
    record means by `"labels":{"walk_depth":2}` for `docs/q3-10k.pdf`. A root-level file is
    depth 1.

    **A directory is descended at its own position in the sort, not after its siblings' files**,
    and the difference is what makes `walk_order` an honest description of the emission order. A
    stack of directory *listings* would yield every file of one directory and only then descend,
    which puts `a.txt` before `a/b` while `walk_order` puts `a/b` first -- and a cursor compared
    against a total order the walk does not actually follow re-emits or skips a run of files on
    every resume. So the stack holds ITERATORS, and pushing a child suspends the parent mid-list.

    A directory whose `scandir` raises is skipped silently HERE. A directory is not a unit, so an
    unreadable one is a coverage fact rather than a skipped document -- reported: 07 section 3.8's
    three counters have no place for "a directory the walk could not open", and `skipped_why`
    counts documents.

    **A SYMLINK TO A DIRECTORY IS NOT A DOCUMENT EITHER, and that needs its own clause.**
    `entry.is_dir(follow_symlinks=False)` is *false* for a directory symlink, so with the shipped
    `follow_symlinks = false` (05:443) such an entry falls straight through to the `yield` and
    becomes a `candidate`; `canonical_uri()` then resolves it and the host mints a `unit_uri` for
    a DIRECTORY -- a `discovered` row with a directory's size that no `fetch` can ever read. Not
    descending a link is not a licence to index it, so a link whose target is a directory is
    skipped here, in the same silence and for the same reason as a directory. Two consequences
    worth stating: a self-referential link (`loop -> .`) used to arrive at the host half as an
    `OW_PATH_OUTSIDE_ROOTS` refusal, which counted a *document* that never existed and named the
    wrong cause; and a link to a subdirectory *inside* the tree used to pass containment and be
    rostered outright. `entry.is_symlink()` is answered from the same `scandir` record as
    `is_dir`, so the extra `is_dir(follow_symlinks=True)` costs a `stat` only for entries that
    really are links. A link to a FILE is still a candidate -- that is 05:243's "a link and its
    target are one unit" -- and a file link out of the tree is still the host half's refusal.
    """
    stack: list[tuple[str, Iterator[os.DirEntry[str]]]] = [("", _listing(str(root), scandir))]
    while stack:
        prefix, entries = stack[-1]
        entry = next(entries, None)
        if entry is None:
            stack.pop()
            continue
        relpath = f"{prefix}{entry.name}"
        depth = relpath.count("/") + 1
        try:
            is_dir = entry.is_dir(follow_symlinks=guards.follow_symlinks)
        except OSError:
            continue
        if is_dir:
            if depth < guards.max_depth:
                stack.append((f"{relpath}/", _listing(entry.path, scandir)))
            continue
        try:
            if entry.is_symlink() and entry.is_dir(follow_symlinks=True):
                continue
        except OSError:
            continue
        yield relpath, entry, depth


def _inode(entry: os.DirEntry[str], info: os.stat_result) -> int:
    """The inode half of 05:289's `<relpath>\\0<inode>` cursor, on both platforms.

    `os.DirEntry.stat()` on Windows answers from the `FindFirstFile` data the directory scan
    already returned, and that record carries no file index -- so `st_ino` comes back **0**, for
    every file, and a cursor built from it would name the same inode for the whole corpus. The
    size and mtime in that cached record are correct and are what the candidate carries; only the
    inode needs a real `stat`, and only where it came back 0.

    That costs one extra syscall per file on Windows and none on POSIX. It is worth paying because
    the inode is the half of the cursor that distinguishes "the file I stopped at" from "a
    different file since created at that path", and a cursor that cannot make that distinction is
    a cursor whose second field is decoration. A `stat` that raises leaves it 0 rather than losing
    the candidate: the relpath is what resumption compares (`walk_order`), so a missing inode
    degrades the cursor and never breaks it.
    """
    if info.st_ino:
        return info.st_ino
    try:
        return Path(entry.path).stat().st_ino
    except OSError:
        return 0


def _listing(
    absolute: str, scandir: Callable[[str], Iterable[os.DirEntry[str]]]
) -> Iterator[os.DirEntry[str]]:
    """One directory's entries, sorted by name; empty when it cannot be opened.

    Sorted eagerly rather than streamed: determinism is the requirement (`os.scandir` order is
    the filesystem's) and a directory listing is bounded by one directory, not by the corpus.
    """
    try:
        return iter(sorted(scandir(absolute), key=lambda item: item.name))
    except OSError:
        return iter(())


def read_bounded(path: Path, limit: int) -> bytes:
    """Read at most `limit` bytes, refusing at `limit + 1`. 05:330-332, mechanism 2.

    *"`fetch` reads `max_unit_bytes + 1` bytes and raises `DriverError(TOO_LARGE,
    limit="ingest.max_unit_bytes")` if the extra byte arrives. This is the `size = null` case and
    the lying-`Content-Length` case; a declared length is attacker-supplied."*

    The extra byte is the point: reading exactly `limit` cannot distinguish a file of `limit`
    bytes from a file of a terabyte.
    """
    with path.open("rb") as handle:
        body = handle.read(limit + 1)
    if len(body) > limit:
        raise DriverError(
            cls=FailureClass.TOO_LARGE,
            message=f"{path.name} exceeds ingest.max_unit_bytes={limit}",
            limit="ingest.max_unit_bytes",
        )
    return body


def fetch_local(
    path: Path,
    *,
    indexed_at_ns: int,
    max_unit_bytes: int = DEFAULT_MAX_UNIT_BYTES,
    read: Callable[[Path, int], bytes] = read_bounded,
) -> tuple[StatTriple, bytes]:
    """Stat, THEN read. The order is the contract and it is the only reason this function exists.

    02-architecture.md:472: the stat triple is *"**captured before the content read**"*. 05:344
    gives the failure the order prevents: *"The stat triple is captured BEFORE the content read
    (charter D6), so a write racing the read is caught."* Stat-after-read produces a triple that
    describes the file as it was *after* the writer finished -- so `stat_fresh()` on the next run
    compares the new size and the new mtime against themselves, reports fresh, and the document
    that changed mid-read is never re-indexed. The bytes in the store are then a torn copy that
    nothing will ever notice.

    `read` is injected. In production it is `read_bounded`; a host that streams a 2 GiB file into
    the CAS in chunks passes its own, and `test_acquire.py` passes one that mutates the file
    before returning -- which is what makes the ORDER observable rather than merely asserted.

    Returns the pre-read triple and the bytes. It does not hash, name, or store them: `unit`'s
    `content_sha256` is over *normalised* bytes (05:257) and the normaliser is per format, so
    digesting here would put a second identity recipe in the enumerator.
    """
    info = path.stat()
    triple = StatTriple(size=info.st_size, mtime_ns=info.st_mtime_ns, indexed_at_ns=indexed_at_ns)
    return triple, read(path, max_unit_bytes)


def stat_fresh(stored: StatTriple, observed: StatTriple) -> bool:
    """The zero-byte rung of 05:337-347's change-detection ladder, all three clauses.

    ```
    stat_fresh   size == st_size AND mtime_ns == st_mtime_ns
                 AND st_mtime_ns + MTIME_GRANULARITY_NS(2e9) <= indexed_at_ns
    ```

    `stored` is the `unit` row; `observed` is a fresh `stat` -- so `stored.size` is `size`,
    `observed.size` is `st_size`, and `observed.indexed_at_ns` is unread, because the third
    clause compares the *fresh* mtime against the *stored* index time.

    **The third clause is the point** (05:341-343): *"a file modified inside the mtime granularity
    window of the last index cannot be PROVEN unchanged, so it is NOT fresh"*. It is what closes
    the one direction this rung can be wrong in -- *"a file rewritten in place with identical size
    inside one mtime tick"* (05:350) -- and dropping it would turn a free check into a silent
    staleness bug. Note it is not symmetric: a unit indexed *before* its own mtime settled is
    re-read, which costs a parse and never loses a document.
    """
    return (
        stored.size == observed.size
        and stored.mtime_ns == observed.mtime_ns
        and observed.mtime_ns + MTIME_GRANULARITY_NS <= stored.indexed_at_ns
    )


# --------------------------------------------------------------------------------------------
# 4. The host half: `Locator` projection, identity, the roster and the scope row
# --------------------------------------------------------------------------------------------


def locator_for(
    root: Path | str, *, cursor: str | None = None, since_ns: int | None = None
) -> Locator:
    """Project a `file`/`dir` source onto the per-invocation `Locator` 05:80-88's table gives.

    `scheme = "file"` for both kinds; `target = canonical_uri()`'s path form of the root. The
    projection is the host's and happens *"once per `INVOKE`"* (05:41-45): a driver never receives
    a `SourceLocator`, and it is the `Locator` -- never the `SourceLocator` -- that crosses S4.

    `cursor` is *"read from the last committed `unit.cursor`"* (05:104) and `since_ns` is
    `SourceLocator.since`. Neither is interpreted here.
    """
    return Locator(
        scheme=LOCATOR_SCHEME,
        target=canonical_uri(root),
        cursor=cursor,
        since_ns=since_ns,
    )


def scope_id_for(locator: Locator) -> str:
    """`ingest_scope.scope_id` -- *"the canonical URI PREFIX of the enumerated root"*.

    07-store-and-retrieval.md section 3.8 and `0003_index.sql:394`. The trailing `/` is not
    decoration: the containment test is `doc.uri GLOB scope_id || '*'`, so a `scope_id` of
    `c:/a/docs` would match every document under a sibling `c:/a/docs2` and gate 4 would read a
    coverage row that does not belong to the corpus in view.

    **A root whose path contains a GLOB metacharacter breaks that test and this function cannot
    fix it.** SQLite's `GLOB` has no `ESCAPE` clause, so a directory literally named `docs[1]`
    produces a `scope_id` whose `[1]` is a character class and whose `GLOB` selects the wrong
    documents -- or none. 07 section 3.8 states the predicate and 07:3372 defends it as *"the only
    implementable containment test"*; neither addresses escaping. Reported: the fix is a
    predicate, not a prefix, and the predicate is 07's to change.
    """
    return locator.target.rstrip("/") + "/"


def roster_row_of(
    locator: Locator,
    candidate: CandidateRecord,
    *,
    indexed_at_ns: int,
    last_seen_gen: int,
    trust_class: TrustClass = TrustClass.INTERNAL,
    scope_rule: str | None = None,
) -> RosterRow:
    """Mint the `unit_uri` and stamp every host-owned column. THE ONLY SITE THAT MINTS ONE.

    One of the module's two `canonical_uri()` call sites -- `locator_for()` is the other, and it
    projects the root rather than minting a unit identity.

    04-driver-system.md section 1.5 obligation 2 in one function: *"The host calls
    `canonical_uri()` on `(Locator, id)`. This is obligation 2 ... and it is what makes a roster
    stream portable between stores and stops a connector minting a sibling's primary key"*
    (05:163-166). Obligation 3 is the `trust_class` parameter: it comes from the caller's
    `SourceLocator`, never from the record.

    `canonical_uri(locator, id)` does the whole of 05:239's `file`/`dir` row -- realpath,
    normcase, forward slashes, `\\\\?\\` stripped -- and refuses an `id` that is not relative to
    the locator target, which is how a connector-supplied path is stopped from re-rooting itself
    (`identity.py:134-143`). There is no normalisation here and there must not be.

    **The containment check that `realpath` makes necessary.** `canonical_uri` resolves symlinks,
    so a link inside the tree pointing at `/etc/shadow` mints a `unit_uri` outside the scope root
    even though the walk never left it. 05:70 makes that a refusal and not a warning --
    `OW_PATH_OUTSIDE_ROOTS`, `OW-A-007` -- so the minted uri is tested against the scope prefix
    and a `PolicyRefusal` is raised. `scan()` catches it and counts it; `omniweave_core.paths.
    confine()` (14-security.md:275) is the framework's general answer and does not exist yet, so
    this is a prefix test on the already-canonical uri, which is exactly the comparison
    `confine()` will make and not a second policy.
    """
    unit_uri = canonical_uri(locator, candidate.stable_id)
    prefix = scope_id_for(locator)
    if not unit_uri.startswith(prefix):
        raise PolicyRefusal(
            f"{candidate.stable_id!r} resolves to {unit_uri!r}, outside the scope root "
            f"{prefix!r}: a symlink is the cheapest way out of [roots] source",
            symbol="OW_PATH_OUTSIDE_ROOTS",
            fix="ow ingest --no-follow-symlinks, or remove the link from the tree",
        )
    derived: dict[str, object] = dict(candidate.labels)
    if candidate.etag is not None:
        derived["etag"] = candidate.etag
    return RosterRow(
        unit_uri=unit_uri,
        cursor=candidate.next_cursor,
        stat=StatTriple(
            size=candidate.size or 0,
            mtime_ns=candidate.mtime_ns or 0,
            indexed_at_ns=indexed_at_ns,
        ),
        trust_class=trust_class,
        last_seen_gen=last_seen_gen,
        connector=candidate.connector,
        derived=derived,
        scope_rule=scope_rule,
    )


UNIT_COLUMNS: Final[tuple[str, ...]] = (
    "unit_uri",
    "connector",
    "cursor",
    "state",
    "size",
    "mtime_ns",
    "indexed_at_ns",
    "derived",
    "trust_class",
    "last_seen_gen",
    "scope_rule",
)
"""The `unit` columns a `discovered` row carries, in `0004_runtime.sql:45-82`'s own order."""

UNIT_UPSERT_SQL: Final[str] = (
    f"INSERT INTO unit({', '.join(UNIT_COLUMNS)}) "
    f"VALUES({', '.join(':' + name for name in UNIT_COLUMNS)}) "
    "ON CONFLICT(unit_uri) DO UPDATE SET "
    "last_seen_gen = max(last_seen_gen, excluded.last_seen_gen), cursor = excluded.cursor"
)
"""05:395-398 rule 5, verbatim in its `SET` list and its conflict target.

*"Enumeration is idempotent under concurrency. Roster writes are `INSERT INTO unit(...)
VALUES(...) ON CONFLICT(unit_uri) DO UPDATE SET last_seen_gen = max(last_seen_gen,
excluded.last_seen_gen), cursor = excluded.cursor` -- so two `ow ingest` processes over the same
scope converge instead of racing, and neither resets a state machine the other advanced."*

**What the `SET` list omits is load-bearing and easy to "fix" into a bug.** It does not refresh
`size`, `mtime_ns` or `indexed_at_ns`. If it did, the stored triple would be re-stamped from the
current `stat` on every walk, `stat_fresh(stored, observed)` would then compare a triple against
the very `stat` it was just written from, every unit would be fresh forever, and no changed
document would be re-indexed again. The stored triple is a record of the last *indexing*, not of
the last *walk*, and only the acquisition path may move it. It also does not touch `state`, for
05:170's reason: *"a driver that could write it could resurrect an `out_of_scope` unit"*.
"""

SCOPE_UPSERT_SQL: Final[str] = (
    "INSERT INTO ingest_scope(scope_id, discovered, indexed, skipped, skipped_why, "
    "scanned_at_ns, complete) "
    "VALUES(:scope_id, :discovered, :indexed, :skipped, :skipped_why, :scanned_at_ns, :complete) "
    "ON CONFLICT(scope_id) DO UPDATE SET "
    "discovered = excluded.discovered, indexed = excluded.indexed, skipped = excluded.skipped, "
    "skipped_why = excluded.skipped_why, scanned_at_ns = excluded.scanned_at_ns, "
    "complete = excluded.complete"
)
"""The `ingest_scope` write. The plan prints the DDL (07 section 3.8) and not this statement.

Every column is replaced from the new scan, because `ingest_scope` is a statement about the LAST
scan of that prefix and a merged row would claim a coverage no single scan achieved: `max()`ing
`complete` would let an interrupted scan inherit a previous run's `complete = 1` and re-enable the
`out_of_scope` marking 05:371 forbids it. `scanned_at_ns` moving with the row is what makes the
replacement legible afterwards.
"""


def write_roster(
    thread: StoreThread,
    rows: Iterable[RosterRow],
    *,
    tally: Tally | None = None,
    scope_id: str | None = None,
    scanned_at_ns: int = 0,
    plan_batch: int = PLAN_BATCH,
    wait_ms: int = BATCH_WAIT_MS,
) -> tuple[int, ScopeTally | None]:
    """Commit `rows` at `plan_batch` rows per transaction, and the `ingest_scope` row with the last.

    02-architecture.md:472: *"at `[runtime] plan_batch = 512` rows per transaction; plus one
    `ingest_scope` row recording discovered vs indexed vs skipped"*.

    **The coverage row rides in the FINAL transaction, and it is frozen after the last row and
    before that transaction opens.** That ordering is the whole reason this function takes the
    mutable `Tally` rather than a finished `ScopeTally`: `rows` is the generator `scan()` returns,
    so the counters are not final until it is exhausted, and a caller that froze the tally first
    would record `complete = 0` on every successful scan. A caller that instead wrote the coverage
    row in a *second* transaction would leave a window in which the roster is complete and the
    store still says coverage unknown -- and 07 section 3.8's absence rule makes that window read
    as "coverage UNKNOWN", which is a `DEGRADED` verdict on a corpus that is actually fine.

    The same placement is 05:411 rule 1 for the small case -- *"`ow_add` writes `unit` rows plus
    one `ingest_scope` row in a single transaction"* (10-interfaces.md:1114,
    18-api-sketch.md:405) -- which a caller gets by passing a `plan_batch` no smaller than the row
    count.

    `rows` is consumed lazily, one batch at a time, so 05:208's *"one record plus one 512-row
    batch"* bound survives the last step.

    `wait_ms` defaults to `BATCH_WAIT_MS` (60 s) rather than `INTERACTIVE_WAIT_MS`: a corpus scan
    is the batch case of 07:2726-2729's *"passed per call, never global"* pair, and a roster write
    that gave up after two seconds would abandon a scan a human is not waiting on.

    Returns `(roster statements executed, the coverage row written or None)`. The first is not the
    number of rows *changed*: the `ON CONFLICT` upsert makes those different numbers, and the
    honest count of "what changed" is a `SELECT`, not a `rowcount`.
    """
    if plan_batch < 1:
        raise ValueError("plan_batch is a positive row count per transaction")
    if (tally is None) != (scope_id is None):
        raise ValueError(
            "tally and scope_id are given together: an ingest_scope row is keyed by its "
            "scope_id (07-store-and-retrieval.md section 3.8) and a tally without one has "
            "nowhere to land"
        )
    written = 0
    batch: list[Mapping[str, object]] = []
    for row in rows:
        batch.append(row.params())
        if len(batch) >= plan_batch:
            written += _commit(thread, batch, None, wait_ms)
            batch = []
    frozen = (
        None
        if tally is None or scope_id is None
        else tally.freeze(scope_id, scanned_at_ns=scanned_at_ns)
    )
    written += _commit(thread, batch, frozen, wait_ms)
    return written, frozen


def _commit(
    thread: StoreThread,
    batch: Sequence[Mapping[str, object]],
    tally: ScopeTally | None,
    wait_ms: int,
) -> int:
    """One transaction: `len(batch)` roster upserts, then at most one `ingest_scope` upsert."""
    if not batch and tally is None:
        return 0
    params = list(batch)
    scope_params = None if tally is None else tally.params()

    def run(connection: _Rows) -> None:
        if params:
            connection.executemany(UNIT_UPSERT_SQL, params)
        if scope_params is not None:
            connection.execute(SCOPE_UPSERT_SQL, scope_params)

    thread.run(Unit(name="acquire.fs.local roster", run=run, cost_class="free", wait_ms=wait_ms))
    return len(params)


def scan(
    locator: Locator,
    scope: Scope,
    guards: IngestGuards,
    *,
    indexed_at_ns: int,
    last_seen_gen: int,
    tally: Tally,
    trust_class: TrustClass = TrustClass.INTERNAL,
    scope_rule: str | None = "inherited",
    max_units: int = MAX_UNITS_PER_CALL,
) -> Iterator[RosterRow]:
    """The two halves joined: `candidate` records in, `unit` rows out, every skip counted.

    This is 05:191-197's loop with the identity step in the middle, and it stays a generator so
    that `write_roster` can batch it at 512 without either side holding the corpus.

    `PolicyRefusal(OW_PATH_OUTSIDE_ROOTS)` from `roster_row_of` is caught and counted rather than
    propagated: one symlink pointing out of the tree must not end a corpus scan, and 05:70 makes
    the *unit* a refusal, not the *run*. The count is in `skipped_why` where an operator can see
    it, which is the difference between a refusal and a silence.

    `scope_rule` defaults to `"inherited"` because every row this function produces is a member of
    a walked tree rather than a path the operator named -- see `SCOPE_RULES` for why that reading
    is an inference and not a citation.
    """
    for candidate in iter_candidates(locator, scope, guards, tally=tally, max_units=max_units):
        try:
            row = roster_row_of(
                locator,
                candidate,
                indexed_at_ns=indexed_at_ns,
                last_seen_gen=last_seen_gen,
                trust_class=trust_class,
                scope_rule=scope_rule,
            )
        except PolicyRefusal:
            tally.skip(SKIP_PATH_OUTSIDE_ROOTS)
            continue
        tally.roster()
        yield row


# --------------------------------------------------------------------------------------------
# 5. The driver-shaped surface: `AcquireV1`, satisfied structurally
# --------------------------------------------------------------------------------------------


class FsLocal:
    """`acquire.fs.local` as an `omniweave_ports.ports.AcquireV1`. THE DRIVER-SHAPED HALF.

    Structural conformance, not inheritance: `AcquireV1` is a plain `Protocol`
    (04-driver-system.md section 1.4) and 04 section 1.2 is explicit that there is *"no base
    class, no registration decorator"*. `DriverBase`'s `@runtime_checkable` pair -- `PORT` and
    `SCHEMA_VERSION` -- are declared because `activate()` compares them with the card's `port` and
    `schema_version` before any work runs.

    **Read this class as a specification of the seam, not as a shipped driver.** 02-architecture.md
    :329 says `acquire/1` has no in-tree implementation at release 1 and the fs walk is host-side;
    the module docstring records the conflict with 05:278 and why 02 wins. What this class is for
    is to keep the host half honest: `enumerate()` can only emit what `CandidateRecord` can hold,
    and `CandidateRecord` has no field for a `unit_uri`, a `trust_class` or a `state`. If the fs
    walk ever does become a distribution of its own -- 17-risks.md:887's *"A first-party `acquire`
    distribution -- which grows the distribution table to fifteen rows and `layers.toml` to
    fifteen lines"* -- this class moves and nothing above it changes, because it imports no
    `omniweave_core` name.

    Two things it deliberately does not do. It does not hash: `content_sha256` is over normalised
    bytes and the normaliser is per format (05:257-271), so the digest is the host's. And it does
    not retry: obligation 4, *"A driver never retries internally"* -- `[cost.model] max_retries =
    0` is the only value a first release accepts.
    """

    PORT: Final[str] = "acquire/1"
    SCHEMA_VERSION: Final[int] = 1

    def __init__(self, **config: Scalar) -> None:
        """STATIC CONFIG ONLY: loads no model and opens no file (04 section 1.2).

        The `[ingest]` guards arrive as scalars and become an `IngestGuards`. Nothing is stat'ed,
        opened or resolved here -- *"a 100%-cache-hit run constructs nothing at all"*.
        """
        self._guards = IngestGuards(
            follow_symlinks=bool(config.get("follow_symlinks", DEFAULT_FOLLOW_SYMLINKS)),
            max_depth=int(config.get("max_depth", DEFAULT_MAX_DEPTH)),  # type: ignore[arg-type]
            max_unit_bytes=int(
                config.get("max_unit_bytes", DEFAULT_MAX_UNIT_BYTES)  # type: ignore[arg-type]
            ),
            hidden=bool(config.get("hidden", DEFAULT_HIDDEN)),
        )
        self._include = _globs(config.get("include"), DEFAULT_INCLUDE)
        self._exclude = _globs(config.get("exclude"), DEFAULT_EXCLUDE)

    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict:
        """*"MUST NOT download, spawn or write"* (04 section 1.4).

        The filesystem is always available, so the verdict is unconditional `OK`. It reads nothing
        off `env` -- a probe that stat'ed a configured root would be answering "is this corpus
        present" in the slot that asks "can this driver run", and the probe result is cached per
        `(driver_id, version, card_sha256, env_digest)` where a corpus is not a member.
        """
        del env
        return ProbeVerdict(status=ProbeStatus.OK, detail="stdlib os.scandir")

    def enumerate(self, locator: Locator, io: DriverIO) -> DriverResult:
        """Emit `owroster-items/1` as one `ArtifactRef`. 04 section 1.4, 05:128-190.

        NDJSON, one `candidate` object per line, built through `ArtifactRef.of` so the
        invocation's `max_output_bytes` ceiling is applied at the one site that applies it
        (04 section 6.5). `io.cancelled()` is checked at every loop top, which is where
        04 section 6.5 puts it.

        The records carry no identity and no bytes. `Tally` is local to this call and is thrown
        away: `ingest_scope` is the host's row (04:339, `ports.py:66`), and a driver that reported
        its own coverage would be reporting the number the host is supposed to check.
        """
        tally = Tally()
        scope = Scope(roots=(locator.target,), include=self._include, exclude=self._exclude)
        lines: list[bytes] = []
        for candidate in iter_candidates(locator, scope, self._guards, tally=tally):
            if io.cancelled():
                break
            lines.append(json.dumps(candidate.record(), separators=(",", ":")).encode("utf-8"))
        body = b"\n".join(lines) + (b"\n" if lines else b"")
        ref = ArtifactRef.of(ArtifactKind.ROSTER_ITEMS, body, io)
        return DriverResult(
            outcome="ok",
            produced=(ref,),
            metrics=DriverMetrics(calls=1, bytes_read=0),
        )

    def fetch(self, ref: UnitRef, io: DriverIO) -> DriverResult:
        """Materialise one unit's bytes into the CAS, emitting one `fetched` record.

        *"Idempotent on `content_sha256`"* (04 section 1.4): the digest is over the bytes, so a
        second `fetch` of an unchanged file writes the same blob under the same name and the CAS
        `put` is a no-op.

        `UnitRef.uri` is host-built and already canonical, which is why this method needs no
        `Locator`: 05:181-186 -- *"A connector recovers its own id from `UnitRef.uri` by
        inspection ... so the host never hands a driver back a row it wrote."*

        The stat triple this reads is discarded, and that is correct rather than wasteful: the
        triple that reaches `unit` is the one captured before the content read on the host side,
        and a driver cannot write a roster column (obligation 2).

        **The returned `ArtifactRef` is the RECORD, not the bytes.** 05:129 -- *"Two record types
        on one NDJSON stream"* -- so a `fetched` record is an `owroster-items/1` line like a
        `candidate` is, and it travels as `roster_items`. The bytes went to the CAS through
        `io.blobs.put()` and are named by `blob_ref`, which is what *"beside the `raw_bytes` CAS
        blob it wrote"* (05:134) means: `raw_bytes` is the blob's kind in the store, not a second
        copy on the wire.

        `content_sha256` equals `source_sha256` here and that is not a shortcut. 05:271's
        normaliser table gives *"everything else | none | raw bytes are hashed"*, and the two
        columns diverge only for a format with a normaliser -- pdf, OPC, ODF/EPUB -- which this
        connector does not identify and may not choose. 05:261 says the NULL-normaliser case
        records `OW-C-041`; there is no `codes.toml` row for that code, so nothing is recorded
        here and the gap is reported.
        """
        path = Path(ref.uri)
        _, body = fetch_local(
            path,
            indexed_at_ns=0,
            max_unit_bytes=self._guards.max_unit_bytes,
        )
        digest = hashlib.sha256(body).hexdigest()
        record = FetchedRecord(
            content_sha256=digest,
            source_sha256=digest,
            bytes=len(body),
            blob_ref=io.blobs.put(body),
            media_type_hint=ref.media_type,
        )
        return DriverResult(
            outcome="ok",
            produced=(
                ArtifactRef.of(
                    ArtifactKind.ROSTER_ITEMS,
                    json.dumps(record.record(), separators=(",", ":")).encode("utf-8"),
                    io,
                ),
            ),
            metrics=DriverMetrics(calls=1, bytes_read=len(body)),
        )


def _globs(value: object, fallback: tuple[str, ...]) -> tuple[str, ...]:
    """A card's `[config]` scalars are flat, so a glob list arrives as a comma-separated string.

    04 section 2.7's `[config]` is a closed JSON-Schema subset over `Scalar`, which has no array
    member, so a driver taking a list takes a string and splits it. An empty string means "use the
    shipped default" rather than "match nothing": an `include` of `()` would walk a tree and emit
    nothing, which is indistinguishable from an empty corpus and is never what a caller meant.
    """
    if value is None or value == "":
        return fallback
    return tuple(part for part in str(value).split(",") if part)


def refuse_unmigrated(thread: StoreThread) -> None:
    """Refuse a store whose `unit` and `ingest_scope` tables do not exist yet.

    The roster writer's two tables are created by `0004_runtime.sql` and `0003_index.sql`, and a
    scan against a store missing either would fail per statement, in the middle of a transaction,
    with a message naming SQLite's table rather than the operator's problem. `store/migrate.py`
    owns applying them; this only says which two are missing and what clears it.
    """

    def run(connection: _Rows) -> frozenset[str]:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN "
            "('unit', 'ingest_scope')"
        ).fetchall()
        return frozenset(row[0] for row in rows)

    present = thread.run(Unit(name="acquire.fs.local tables", run=run))
    missing = sorted({"unit", "ingest_scope"} - set(present))  # type: ignore[arg-type]
    if missing:
        raise StoreError(
            f"the roster writer needs {', '.join(missing)}; this store has not been migrated",
            fix="ow store migrate",
        )
