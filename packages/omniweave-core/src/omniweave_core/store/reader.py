"""`Reader` over one `.owstore` connection: the whole P2 -> P6 retrieval edge, six methods wide.

16-roadmap.md:1034 bounds P6 to *"retrieval reads `Reader`, `block_fts` and `block_sec`, and
nothing else"*, so everything the query path will ever be able to ask a store it asks through the
six signatures `store/__init__.py` freezes (07-store-and-retrieval.md:63-68). This module is the
SQLite implementation of those six. It opens no connection of its own -- `store/sqlite.py` is the
only module that connects (ST1, 07:2721) -- and it delegates `snapshot()` to that module's
already-shipped `snapshot()` rather than reimplementing `BEGIN DEFERRED` plus its first read.

## The six-row P2/P6 ruling, with the line that decides each row

The `Reader` PROTOCOL is frozen and complete at P2 (16-roadmap.md:428). Some of its IMPLEMENTATION
is P6's, because 16-roadmap.md:466-470 excludes from P2 *"lexical scoring beyond the FTS5 table
existing -- no `W_HEAD`, no `SPINE_DECAY`, no sanitiser ... No `Verdict`, no `Answer`. No vector
column."* Six methods, one ruling each:
1. **`snapshot` -- ALL OF IT.** 07:2777-2782 fixes the mechanism and `sqlite.snapshot()`
   implements it; this method adds only the issuing-Reader bookkeeping that lets the other five
   refuse a foreign token.
2. **`capabilities` -- ALL OF IT.** Every field is a read of `index_state`, `stat`,
   `sqlite_master` or `PRAGMA database_list` (07:3271-3280), and *"read once, at open"* (07:3272)
   is honoured by reading it in `__init__`. `scorer_version` is reported and not interpreted:
   16-roadmap.md:468 bans the constants that would give it meaning.
3. **`narrow` -- ALL OF IT.** Argued at length in `store/__init__.py`'s docstring: the three-way
   tag is MEASURED by 07:1585-1591's `LIMIT PREFILTER_MAX + 1` probe, and 07:1592-1597 forecloses
   the planner reading -- *"No histogram, no independence assumption, no cost-based optimiser."*
4. **`channel` -- `identity`, `exact` and `lexical`.** `structural` and `semantic` report
   `off` / `not_built`. The per-Channel argument is below; P2 shipped `exact` alone and P6 W6.2b
   added the other two, each in the cell that could first supply its missing input.
5. **`hydrate` -- THE ROW, all of it.** It cannot return `Hit`: four of `Hit`'s fourteen fields
   (`score`, `channel_contributions`, `channel_ranks`, `identity_grade`) are fusion outputs
   (07:2250-2265), and 07:3348 homes `Hit` with the query path. It returns `Hydration`, a
   `Sequence` of the SELECT's own rows -- see that class.
6. **`coverage` -- THE COUNTS.** `gaps` is `tuple[DegradeCause, ...]` and `DegradeCause` is
   07:1989's, with the gate ladder 16-roadmap.md:468 excludes from P2, so `gaps=()`. Every count
   is a real read, including the three over `work` and `unit`, which P2 creates and leaves empty
   (16-roadmap.md:406).

**Why `channel` refuses two of five, and why it refuses with a STATUS rather than an exception.**
07:1198-1199 gives the vocabulary (`ChannelStatus` = `ok | empty | off | unavailable`) and
07:1201-1205 closes the `off` reasons at four members, of which `NOT_BUILT="not_built"` is
*"the P-stage has not shipped it"*. 16-roadmap.md:114 uses exactly that pair for exactly this
situation -- *"The `structural` and `semantic` channels return `ChannelStatus.OFF` with
`reason = "not_built"`, which the Answer discloses in its verdict line"*. A `NotImplementedError`
would make the limitation an outage; an empty `ok` would make it a confident zero, which is ST8's
and 07:1670-1680's whole subject. `off` is disclosed and contributes nothing to the ceiling
(07:1218-1222), which is the honest arithmetic.

* **`identity` -- SHIPPED at W6.2b, and the reason it could not ship at P2 was the 40 tier.**
  07:1269 fixes the resolution as *"`block_cite` / `block_addr` / `doc(uri)` index lookups **plus a
  `head_fts` title probe**"*, and no user string reaches FTS5 unsanitised -- 07:1318, *"a user
  cannot inject FTS5 syntax"* -- through a sanitiser 16-roadmap.md:468 excludes from P2 by name. The
  tempting move was to ship the index-lookup tiers and skip the title tiers, and 07:1264-1268
  forbids precisely that: *"The **40 tier** is the first thing a 'simplification' deletes and it
  must not be ... Collapsing 40 into 50 lets a punctuation-different match TIE a literal one and
  fall through to BM25."* A truncated ladder is a recall loss that presents as a confident match,
  so the ladder was all-or-nothing and waited for `retrieve/channels.py`'s `grade_title()`.
* **`exact` -- implemented, and it is the exception the edge needed.** It needs no scorer and no
  sanitiser: `ChannelInput.refs` arrives as `(name_norm, akind)` pairs already through
  `normalize_key` (07:3286, 07:480), its statement is printed whole at 07:1273-1281, and its
  ranking is *"definitions before occurrences; corpus scope before document scope; then
  `(doc_ord, page, ord)`"* (07:1271-1272) -- a total order over columns, not a score. So P6
  inherits a working Channel to fuse against rather than a stub. At P2 `anchor` and `ref_site` are
  empty (16-roadmap.md:114), so it returns `empty` on a stock store; `empty` is not `off`, and the
  difference is that `empty` means the statement RAN.
* **`lexical` -- SHIPPED at W6.2b.** `block_fts` existed at P2 (0001_init.sql:484) and nothing
  scored over it: `lex(b)` is `W_BODY`, `W_HEAD` and `SPINE_DECAY` (07:1294-1296), all three named
  in 16-roadmap.md:468's exclusion, and its input is sanitised query text. W6.2a homed the three
  weights and the sanitiser; `_lexical` below spends them.
* **`structural` -- SHIPPED at W6.2c.** A bounded frontier BFS seeded from `identity` and
  `exact` (07:1327-1332), which is why it waited for them: a Channel whose first act is to read
  another Channel's output cannot be built before that output exists. `ChannelInput` gained a
  `seeds` field to carry it (D246); the last rung of 07's seed ladder, `tmp_narrow` itself, needed
  no field because the `Narrowing` already carries it.
* **`semantic` -- SHIPPED at W6.2d, and it still answers `unavailable` on a stock store.**
  *"No vector column"* (16-roadmap.md:468) is a P2 fact; `[retrieval] vectors = "off"` is a
  permanent v1 default (07:2596). The Channel exists, calls `VectorBackend.search()` and lifts
  segments to blocks; with no backend selected and no sidecar attached it says so, and saying so
  is the difference between `OFF(vectors)` (an operator choice, ceiling-exempt) and a Channel
  nobody wrote.

**`IndexCaps.channels` reports the STORE fact and is deliberately NOT intersected with what this
backend implements.** The tempting narrowing -- advertise only `exact`, so `plan()` never selects a
Channel that cannot run -- would silence the disclosure 16-roadmap.md:114 requires: a Channel
absent from `channels` is `OffReason.NOT_IN_PLAN`, which reads as an operator choice, while
`NOT_BUILT` reads as a shipped limitation, and R-A6 (17-risks.md:270) turns on the Verdict
DISCLOSING it -- *"`off` is an operator choice, it is printed, and it contributes nothing to the
ceiling."* So `channels` answers *"which of the five CAN run at all in this store"* (07:3275) from
`sqlite_master` and the attach state, and `channel()` answers "and has this build shipped it".

## Three things this module is careful not to become

**A second `sqlite3.connect`.** It takes a `sqlite3.Connection` and never opens one. `import
sqlite3` is legal here with no `noqa` -- ruff's TID251 per-file-ignore covers `store/*.py`
(pyproject.toml), which is INV-17's allowance -- and the import is for the type and for
`sqlite3.Error`, nothing else.

**A clock.** `IndexCaps.stat_age_ns` is an age, and an age is not an ambient fact: `now_ns` is a
required keyword argument to `__init__`, matching `migrate.apply_pending(conn, *, now_ns)` and the
rest of the store. `capabilities()` takes no arguments and is *"read once, at open"* (07:3272), so
the open moment's clock is the only clock the field could honestly carry -- and a caller who wants
a fresher `stat_age_ns` reopens the `Reader`, which is what "read once" means.

**A second home for a P6 type.** `ChannelResult`, `ChannelStatus`, `OffReason` and `Hit` all
belong to `omniweave_core.retrieve` (18-api-sketch.md:841). `channel()` therefore returns
`ChannelOutcome` -- a stand-in whose `status` is a plain
`Literal["ok","empty","off","unavailable"]` rather than a new enum, so it is VALUE-COMPATIBLE with
07:1198's `ChannelStatus` (a `StrEnum` member equals its value) and nothing has to be renamed when
`retrieve` ships the real record. This mirrors what `store/types.py` does for `DegradeCause`: name
the absent owner, do not mint a rival. `CHANNELS` itself is no longer copied: P6 W6.1 gave it a
public home, and `_CHANNELS`'s own deletion condition -- that the moment `retrieve` exported
the tuple this became an import and the constant went -- is discharged here.

**The import that makes the package graph a cycle, and why the MODULE graph is still acyclic.**
`store/reader.py` now imports `omniweave_core.retrieve.channels`, and `omniweave_core.retrieve`
imports `omniweave_core.store.types`. That is a cycle between the two PACKAGES and not between any
two modules: `retrieve/channels.py` imports `errors`, `ident` and `limits` and no `store` module at
all, and `store/__init__.py` does not import this module, so every real import order terminates.
The alternative was a second `grade_title()` and a second `IDENTITY_LADDER` inside the store, which
is the drift 13:1072 names -- and the ladder is the one table in the system where a second copy
would silently change a published `confidence`.

## Defects and omissions found while writing this, all reported

1. **`Filters.lang` names no shipped column.** 07:1573 declares `lang: str | None`; no migration
   creates a `lang` column on `block`, `doc`, `page` or `segment` (grep over all four migrations
   matches only `[capability.embed] languages`). A silent ignore would widen every language-scoped
   query to the whole corpus -- a recall error in the direction that presents as a confident
   answer -- so `narrow()` REFUSES a non-`None` `lang` with a `UsageError` naming the defect. 07's
   own house rule for an unsatisfiable filter value is *"a usage error naming the legal set, never
   a silent drop"* (07:1290).
2. **`NO_JOB_DOCS` has no code home.** 07:766 says *"`omniweave_core.store` -- the one spelling"*
   and `store/__init__.py` does not export it; `store/maintenance.py`'s DEFECT 4 already reported
   the same gap and deferred `stat.docs` over it. `coverage()` cannot defer: 07:757 lists
   *"absence gate 4's scope roll-up"* among the predicate's exhaustive sites. `_NO_JOB_DOCS` below
   is therefore private and carries its own deletion condition; the required edit is reported.
3. **`STAT_MAX_AGE_NS` is a plan-named constant absent from `limits.py`.** 07:731 defines
   `STAT_MAX_AGE_NS = 86_400e9`. Nothing here needs it -- `stat_age_ns` is an age and the
   comparison belongs to the over-fetch factor, which is P6's -- so it is reported and not
   worked around.
4. **`Coverage.partial` and `.failed` have no stated source.** `discovered`, `indexed`, `skipped`
   and `complete` are `ingest_scope` columns of the same names (07:686-691) and `partial`/`failed`
   are not. `doc.status` is the only column in the schema holding those two words
   (0001_init.sql:161), so they are counted from it; `skipped` is taken from `ingest_scope.skipped`
   rather than from `doc.status = 'skipped'` because a column of that exact name sits in the table
   gate 4 reads, next to `skipped_why`. Both readings are recorded rather than assumed.
5. **The `exact` statement's printed `ORDER BY` is narrower than its own prose.** 07:1281 prints
   `ORDER BY tier, block_id`; 07:1271-1272 requires *"definitions before occurrences; corpus scope
   before document scope; then `(doc_ord, page, ord)`"*, which `tier, block_id` cannot express
   (`block_id` is an allocation order, not a reading order). The prose is followed and the printed
   clause is extended; `block_id` stays as the final tiebreak so the order is total.

**On the fourteen `# noqa: S608`s.** Every statement in this module is built by interpolating one
of three things and nothing else: a module-level table-name constant (`_TMP_NARROW`, `_TMP_DOCS`,
`_TMP_REFS`), the `_NO_JOB_DOCS` predicate constant, or a `?,?,?` placeholder run from
`_placeholders(n)` -- an integer count turned into question marks. **No caller value is ever
interpolated**: every `Filters` field, every ref and every id travels as a bound parameter, which
is also what makes `enum_val`-code resolution (07:1655-1657) a bind rather than a literal. S608
cannot see the difference between a placeholder run and a value, so it is suppressed at each site
rather than globally, and this paragraph is the reason a reader gets instead of fourteen repeated
comments.

Stdlib only (INV-2 / G1). Inside one of the nine LAZY subpackages (11-repo-layout.md section 1.3),
so `import omniweave_core` must not reach it -- G17.

Tier T-INTERNAL: `Reader` is the PUBLIC Protocol; this class is the backend behind it.
Specified in 07-store-and-retrieval.md sections 1.1, 3.3, 3.8, 6.1, 7.1, 7.2, 10.4 and 11.3.
"""

from __future__ import annotations

import math
import sqlite3
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from itertools import groupby
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal

from omniweave_core.canonical import sha256_canonical
from omniweave_core.errors import StoreError, UsageError
from omniweave_core.limits import (
    MAX_FILTER_DOC_KEYS,
    MAX_QUERY_REFS,
    PREFILTER_MAX,
    SEM_BLOCKS_PER_SEGMENT,
    VEC_BRUTE_MAX,
)
from omniweave_core.model.enums import Kind, Layer, Method, OsKind, Quote, Trust
from omniweave_core.model.spans import TextSpan
from omniweave_core.retrieve import CHANNELS
from omniweave_core.retrieve.channels import (
    FTS_SYNTAX,
    IDENTITY_LADDER,
    SPINE_DECAY,
    W_BODY,
    W_HEAD,
    cite_doc_ord,
    grade_title,
    normalise_query_text,
)
from omniweave_core.store import sqlite as ow
from omniweave_core.store.types import (
    ChannelSpec,
    Coverage,
    Expand,
    Filters,
    IndexCaps,
    Narrowing,
    Snapshot,
    VecManifest,
)
from omniweave_core.store.vectors import parse_manifest

if TYPE_CHECKING:
    from omniweave_core.store import VectorBackend

__all__ = [
    "ChannelOutcome",
    "HydratedRow",
    "Hydration",
    "SqliteReader",
]


# ---------------------------------------------------------------------------
# Constants. Each is a transcription with its line, or private with a stated owner.
# ---------------------------------------------------------------------------

_IMPLEMENTED_CHANNELS: Final = frozenset({"identity", "exact", "lexical", "structural", "semantic"})
"""Which of `CHANNELS` THIS BUILD can run, as opposed to which the store supports.

The one-line edit site for each retrieval cell: widening this frozenset is what turns an
`off`/`not_built` outcome into a real Channel run, and the ruling for each name is in the module
docstring. P2 held `{"exact"}`; W6.2b added `identity` and `lexical`, W6.2c `structural` and
W6.2d `semantic` -- the last of the five, and the only one that can be shipped and still
report `unavailable` on every store, because it needs a `VectorBackend` and a matching `vec`
sidecar before it can look at anything.
"""

_REQUIRED_OBJECTS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "identity": ("block_cite", "block_addr"),
        "exact": ("anchor", "ref_site"),
        "lexical": ("block_fts",),
        "structural": ("block_link", "relation_vocab"),
        "semantic": ("segment", "segment_block"),
    }
)
"""What each implemented Channel's statements NAME, so a missing one is `unavailable` and not a
`sqlite3.OperationalError` crossing the boundary.

The same object lists `_store_channels` reads, and deliberately the same: 07:3275's
`IndexCaps.channels` answers *"which of the five CAN run at all in this store"*, and a planner
that ignored it would otherwise reach `no such table: block_fts` here. An exception would be an
outage where the truth is a store built by an earlier migration set -- and 07:1198's vocabulary
has a member for exactly that reading. `head_fts` and `block_sec` are NOT in `identity`'s or
`lexical`'s row: both are boosts over a Channel that still answers without them, so their absence
narrows the ladder and flattens the spine term rather than stopping the Channel.
"""

_SPINE_MAX_HOPS: Final = 16
"""How far `spine(b)` walks up `block_sec` before it stops. Not a plan constant; a termination one.

`SPINE_DECAY ** 16` is 2.8e-4, below the resolution of a min-max normalised score, so the cap
removes nothing a rank could see. It exists because `block_sec.sec_id` is an ordinary INTEGER
column with no CHECK forbidding a cycle, and an unbounded walk over a cyclic `block_sec` is a hang
inside a 50 ms Channel budget rather than a wrong answer.
"""

_EXPAND_MAX_HOPS: Final = 4
"""`Expand.max_hops`'s HARD CAP (07:1345, 18:2832), clamped HERE and not on the dataclass.

`store/types.py` prints the cap as a comment and enforces nothing, which is deliberate and stated
there: it is a clamp at the traversal and not a field constraint. So the traversal owns it, and a
caller who asks for 99 hops gets 4 rather than a `ValueError` -- the ceiling is what keeps an
unbounded traversal unrepresentable, and refusing the request would only move the unboundedness
into the caller's retry.
"""

_SEGMENT_LIFT_CAPPED: Final = "segment_lift_capped"
"""Row 20 of the closed twenty-seven, and the cap that bites.

07:1513-1515: *"The cap is `SEM_BLOCKS_PER_SEGMENT = 64`, and because `MAX_SEGMENT_BLOCKS =
512`, the cap **can bite for up to 448 blocks of a large segment**. The selection rule is
therefore named, deterministic and disclosed."* And without the record, 07:1519 -- *"up to
87% of a large table segment's citable cells are unreachable through it with nothing
recording the fact"*.
"""

_PUSHDOWN_UNAVAILABLE: Final = "pushdown_unavailable"
"""What a backend declaring `VecManifest.pushdown = False` costs, disclosed.

07:104-107 is contract obligation (1) and names the system that got it wrong: *"LEANN post-filters
metadata after ANN retrieval with no over-fetch, which is silent recall loss that presents as
absence."* A backend that cannot push the filter gets the over-fetch clamp instead, and absence
gate 11 (`filter_starved`) reads `VecManifest.pushdown` by name (07:2191).
"""

_VEC_UNREADABLE: Final = "vec_unreadable"
"""07:1373-1376's one exception-to-status conversion in the whole store.

*"A `SQLITE_CORRUPT` or `SQLITE_NOTADB` raised while reading the sidecar is caught **at the Channel
boundary only** and reported as `UNAVAILABLE(vec_unreadable)` -- the one place a store-level
exception becomes a Channel status rather than propagating, and it is why the sidecar is deletable
in the first place."* 07:3189 gives the documented fix: `rm index.vec.owstore`.
"""

_HUB_CAPPED: Final = "hub_capped"
"""The `Degradation.kind` an over-`hub_cap` block sets (07:1351), row 19 of the closed twenty-seven.

15:1090 is the register row -- *"a block above `Expand.hub_cap = 4096` contributed
a weight-sampled subset of its neighbours"* -- and it is one of the seven that FORCE `degraded`
(15:1107). The literal lives here as a string because the `Degradation` TYPE is
15-observability.md's sole property (charter erratum E15) and `omniweave_core.observe.degradation`
does not exist yet; the caller constructs the record from this kind, exactly as
`drivers/catalog.py`'s `UNPINNED_DEGRADATION` already does.
"""

_TIMEOUT: Final = "timeout"
"""The `UNAVAILABLE` reason absence gate 1 reads, and the only one it reads (07:1221-1222).

*"`reason` remains a free `str` for `EMPTY` and `UNAVAILABLE` ... since §6.8 gate 1 reads
`reason == "timeout"` and the gate table is normative on its own terms."* So this one string is
load-bearing in a way the other reason prose is not, and it is a constant for that reason alone.
"""

_ID_BATCH: Final = 512
"""How many block ids go into one `IN (...)` list.

NOT `_HYDRATE_BATCH`, which is 07:2310's number for a different statement. This one is only
SQLite's bound-parameter ceiling kept well clear; the two being equal is a coincidence and a change
to either must not be read as a change to both.
"""

_OFF_NOT_BUILT: Final = "not_built"
"""`OffReason.NOT_BUILT` (07:1204), *"the P-stage has not shipped it"*, and ceiling-EXEMPT.

The value and not the member, because `OffReason` is `omniweave_core.retrieve`'s (18:841) and a
`StrEnum` member compares equal to its value -- so P6's `reason == OffReason.NOT_BUILT` holds
against this string without a conversion.
"""

_NO_JOB_DOCS: Final = "doc.format <> 'owjob'"
"""07:766's predicate, PRIVATE, and DEFECT 2 of the module docstring is its deletion condition.

07:766 declares `omniweave_core.store` the one home and that module does not export it. This copy
is private so that no second PUBLIC home exists to drift; `coverage()` needs it because 07:757
lists absence gate 4's scope roll-up among the predicate's exhaustive sites.
"""

_HYDRATE_BATCH: Final = 512
"""07:2310: *"`hydrate()` is one statement per batch of up to 512 ids"*.

Not a `limits.py` entry, and that is not an omission: no plan site gives this number a CONSTANT
NAME, and `limits.py` holds declared ceilings by name (INV-21). `MARK_HYDRATE_WINDOW` is a
different 512 (limits.py:362, mark hydration) and is not this one.
"""

_TMP_NARROW: Final = "tmp_narrow"
_TMP_DOCS: Final = "tmp_docs"
_TMP_REFS: Final = "tmp_refs"

_PREFIX_SENTINEL: Final = "\U0010ffff"
"""The upper bound of a prefix range scan: the prefix plus the highest codepoint there is.

`sec_path`'s DDL prints the alternative -- *"the prefix upper bound is the path with its last
component incremented"* (0003_index.sql:286-291) -- and that form breaks on the carry it documents
two lines later: incrementing `/0001/9999` gives `/0001/10000`, which sorts BELOW
`/0001/9999/0001`, so the range silently loses the rows it was widened for. `prefix || U+10FFFF`
needs no carry and is the same set for every path the zero-padding admits. Used for `Filters`'
`uri_prefix` too, so one rule covers both prefix filters.
"""

_LIVE_STATES: Final = ("pending", "claimed")
"""07:2185: `Coverage.pending_work` counts `work.status IN ('pending','claimed')` in scope."""


# ---------------------------------------------------------------------------
# What crosses back. Three shapes, none of them a P6 type wearing a P6 name.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ChannelOutcome:
    """One Channel's result, narrowed to what P2 can honestly fill. NOT `ChannelResult`.

    07:1225-1235's `ChannelResult` has ten fields and two of them still cannot exist here:
    `weight` is fusion's and `cost` is a `Spend` (05-ingest-and-routing.md:2370, P4's).
    `ChannelResult` itself lives in `omniweave_core.retrieve` (18-api-sketch.md:841). So this is
    the narrowest shape the five implemented Channels actually need.

    **`rank_of` was the third and W6.2d gave it a producer.** 07:1243-1250 calls it *"the one field
    this document adds to the charter's shape, and it exists because the charter's own semantics
    are otherwise unrepresentable"*: a segment hit at rank *r* yields its member blocks AT RANK
    *r*, so up to 64 blocks share one rank, and a positional rank would spread them over 64 ranks
    and destroy the region-level property the rule exists to create. It is *"empty for every
    Channel but `semantic`"*, and `fuse()` reads `c.rank_of.get(b) or (position of b in c.ranked)
    + 1` -- which is why an empty mapping is a real value here and not an omission.

    **`grades` was the fourth and W6.2b gave it a producer.** P2 omitted it because the identity
    ladder had none; 07:1231 declares it *"the tier ACTUALLY measured"* and 07:2296 says why the
    word matters -- *"not the tier requested ... so a reader can tell a punctuation-different match
    from a literal one without re-running the ladder"*. `__post_init__` therefore checks both
    halves of "measured": every graded block is one this Channel actually ranked, and every tier
    name is a member of `IDENTITY_LADDER`, because `Hit.identity_grade` is printed and a name the
    ladder does not define would read as a tier nobody can rank against.

    **`status` is a `Literal` of `ChannelStatus`'s four VALUES, not a new enum** (07:1198-1199).
    `ChannelStatus` is a `StrEnum`, so `ChannelStatus.OFF == "off"` is `True` and P6 can compare
    against these outcomes without a conversion shim -- which is the property that makes a string
    stand-in preferable to a rival enum carrying the same members.

    `reason` is REQUIRED when `status != "ok"` (07:1232) and `__post_init__` enforces it: an
    unexplained refusal is the surprise 16-roadmap.md:114 says the Answer must disclose. For `off`
    it is an `OffReason` value, a closed four-member domain *"because `ceiling()` branches on it"*
    (07:1214); for `empty` and `unavailable` it is free prose, deliberately (07:2251-2254).

    `ranked` is *"deterministic order, duplicate-free"* (07:1228) and the constructor checks the
    second half, because a Channel that ranks one block twice gives it two RRF contributions.

    **`degradations` carries `Degradation.kind` STRINGS and not `Degradation` records**, for the
    same reason `drivers/catalog.py`'s `UNPINNED_DEGRADATION` does: the type is
    15-observability.md's sole property (charter erratum E15), `omniweave_core.observe.degradation`
    does not exist yet, and a second declaration here would be the rival INV-21 forbids. It is not
    in `ChannelResult`'s ten fields either -- 07:1351 says the traversal *"sets `degradations +=
    [Degradation(kind="hub_capped", ...)]"* without saying onto what, and a Channel that truncated
    a hub has to be able to say so before whatever assembles the `Verdict` can print it. D248.
    """

    name: str
    status: Literal["ok", "empty", "off", "unavailable"]
    ranked: tuple[int, ...] = ()
    rank_of: Mapping[int, int] = MappingProxyType({})
    spans: Mapping[int, TextSpan] = MappingProxyType({})
    grades: Mapping[int, str] = MappingProxyType({})
    degradations: tuple[str, ...] = ()
    reason: str = ""
    truncated_at_limit: bool = False

    def __post_init__(self) -> None:
        if self.status != "ok" and not self.reason:
            msg = (
                f"channel {self.name!r} reports {self.status!r} with no reason: 07:1232 makes "
                f"`reason` REQUIRED when status is not OK, because a Channel that did not look "
                f"has to say why or the Verdict cannot disclose it"
            )
            raise ValueError(msg)
        if len(set(self.ranked)) != len(self.ranked):
            msg = (
                f"channel {self.name!r} ranked a block twice; `ranked` is duplicate-free (07:1228)"
            )
            raise ValueError(msg)
        ungraded = sorted(set(self.grades) - set(self.ranked))
        if ungraded:
            msg = (
                f"channel {self.name!r} graded blocks it did not rank ({ungraded}): `grades` is "
                f"the tier ACTUALLY measured (07:1231), so a grade for a block the Channel did "
                f"not return is a tier nothing measured"
            )
            raise ValueError(msg)
        unranked = sorted(set(self.rank_of) - set(self.ranked))
        if unranked:
            msg = (
                f"channel {self.name!r} gave ranks to blocks it did not rank ({unranked}): "
                f"`rank_of` is the authoritative rank PER RANKED BLOCK (07:1248), not a second "
                f"result set"
            )
            raise ValueError(msg)
        if any(rank < 1 for rank in self.rank_of.values()):
            msg = (
                f"channel {self.name!r} reports a rank below 1; `fuse()` reads `rank_of.get(b) or "
                f"(position + 1)` (07:1249-1250), so 0 is both a falsy sentinel and an illegal "
                f"1-based rank"
            )
            raise ValueError(msg)
        unknown = sorted(set(self.grades.values()) - set(IDENTITY_LADDER))
        if unknown:
            msg = (
                f"channel {self.name!r} reports tiers {unknown}, which IDENTITY_LADDER (07:1259) "
                f"does not define; Hit.identity_grade is printed (07:2296) and an undefined tier "
                f"has no rank to be read against"
            )
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class HydratedRow:
    """One row of 07:2312-2321's hydration SELECT. NOT a `Hit`.

    `Hit` (07:2250-2265) has fourteen fields and four of them are fusion outputs -- `score` is
    *"the fused RRF score"*, `channel_contributions` and `channel_ranks` are per-Channel maps and
    `identity_grade` is the ladder's measured tier -- so no store read can construct one, and
    07:3348 homes `Hit` with the query path for that reason.

    The distinction is the plan's own, not a workaround. 07:2325-2332 selects two columns that are
    *"two consumers that are neither of them `Hit` fields"*: `b.method` for `RenderedBlock.method`
    and `length(b.text)` for `Verdict.generated_share`, both *"selected EVEN WHEN
    `PackSpec.hydrate_text` is `False`"* so a provenance number cannot collapse to `0.0` because a
    caller asked for ids only. A row type that is not `Hit` is what the SELECT already was.

    `achieved` stays the stored JSON text. It *"rides along because `byte_exact` is computed from
    it (section 8)"* (07:2322), and 07:2263 puts `byte_exact` at *"one call site"*, which is
    section 8.2's -- P6's, not this module's -- so the column is carried and not interpreted.

    `kind`, `layer`, `method` and `os_kind` are decoded from their stored integers through
    `enum_val`, the registry those codes mean nothing without (0001_init.sql:94). `trust` and
    `quote` are `IntEnum`s whose *"ord IS the member's integer"* (0001_init.sql:114), so they are
    constructed directly from the column.
    """

    block_id: int
    cite: str
    addr: str
    page: int
    kind: Kind
    layer: Layer
    text: str | None
    trust: Trust
    quote: Quote
    restriction_bits: int
    os_kind: OsKind
    os_part: str | None
    segment_id: int | None
    method: Method
    chars: int | None
    uri: str
    achieved: str


class Hydration(tuple[HydratedRow, ...]):
    """The hydrated rows, plus the drop count `Sequence[Hit]` has no room for.

    07:2323-2324: *"A row that fails the `gen`/`state` predicate is **dropped and counted**, and a
    non-zero drop count means the store advanced mid-query, which gate 3 reads."* The frozen
    signature is `hydrate(self, s, ids) -> Sequence["Hit"]` and widening it is an ADR rather than a
    patch (16-roadmap.md:428), so the count rides on a `tuple` SUBCLASS: the return value is a
    `Sequence` by inheritance and the extra fact is an attribute, which costs the boundary nothing.

    `dropped` counts requested ids that produced no row -- a tombstoned block, a superseded
    generation, or an id that never existed. All three are one fact from the caller's side: the id
    it ranked is not in this snapshot's head generation.
    """

    dropped: int
    """How many requested ids produced no row. `__slots__` is impossible here: a subtype of the
    variable-length `tuple` cannot declare one (`TypeError: nonempty __slots__ not supported for
    subtype of 'tuple'`, measured on CPython 3.12), so the attribute lives in an instance
    `__dict__`. One dict per hydration call, bounded by `PackSpec.max_blocks`, is not the
    per-object cost `slots=True` exists to avoid elsewhere in the store."""

    def __new__(cls, rows: Sequence[HydratedRow] = (), *, dropped: int = 0) -> Hydration:
        self = super().__new__(cls, rows)
        self.dropped = dropped
        return self


# ---------------------------------------------------------------------------
# Small readers over the connection. Every one is a single statement.
# ---------------------------------------------------------------------------


def _objects(connection: sqlite3.Connection) -> frozenset[str]:
    """Every name in `sqlite_master`: tables, views, indexes and triggers alike.

    `IndexCaps` asks four presence questions (`block_fts`, `head_fts`, `block_tri`, `block_link`)
    and they are of three different object kinds, so the set is taken once and untyped rather than
    four `type='table'` probes that would silently answer `False` for a view.
    """
    return frozenset(str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master"))


def _index_state_map(connection: sqlite3.Connection) -> Mapping[str, str]:
    """All of `index_state` as a mapping. Eleven keys at most (0003_index.sql:407-409)."""
    return {str(k): str(v) for k, v in connection.execute("SELECT k, v FROM index_state")}


def _enum_codes(connection: sqlite3.Connection, domain: str) -> Mapping[str, int]:
    """`{member name: ord}` for one `enum_val` domain, read on the READ CONNECTION.

    07:1655-1657 is explicit that this is where the resolution happens: *"`block.method` is an
    integer code ... so the `NOT IN (...)` list binds the `enum_val` codes for the named members.
    They are resolved on the read connection when the narrowing statement is prepared -- inside
    `retrieve()`, never inside `plan()`."* Reading the ordinals off the Python enums instead would
    make a store built by an older `enum_val` seed answer a query with this build's numbering,
    which is exactly the drift `enum_val` exists to make impossible.
    """
    rows = connection.execute("SELECT name, ord FROM enum_val WHERE domain = ?", (domain,))
    return {str(name): int(ord_) for name, ord_ in rows}


def _stat_rows(connection: sqlite3.Connection) -> Mapping[str, tuple[int, int]]:
    """`{key: (value, computed_ns)}` for the whole `stat` table (07:692-698)."""
    rows = connection.execute("SELECT k, v, computed_ns FROM stat")
    return {str(k): (int(v), int(c)) for k, v, c in rows}


def _one_int(connection: sqlite3.Connection, sql: str, params: Sequence[object] = ()) -> int:
    """The first column of the first row as an `int`, or 0 when the statement returned nothing."""
    row = connection.execute(sql, tuple(params)).fetchone()
    return 0 if row is None or row[0] is None else int(row[0])


def _placeholders(n: int) -> str:
    """`?,?,?` for an `IN (...)` list of `n` bound values."""
    return ",".join("?" * n)


def _fts_safe(term: str) -> str:
    """One sanitised term, made inert for FTS5 a second time. Belt over `retrieve.channels`'s.

    The terms this module receives came through `sanitize()`, which already strips `FTS_SYNTAX`
    (07:1318, *"a user cannot inject FTS5 syntax"*). This runs the same strip again because the
    `Reader` boundary takes a `ChannelInput` from whoever built it, not from the sanitiser by
    construction -- `ChannelSpec.bind` is a plain field (07:3300) and a caller assembling one by
    hand is a supported thing to do. Doing it twice costs a string scan; not doing it puts query
    text into an FTS5 expression.
    """
    out = term
    for char in FTS_SYNTAX:
        out = out.replace(char, " ")
    return " ".join(out.split())


def _fts_match(terms: Sequence[str]) -> str:
    """The terms as ONE FTS5 expression: each a quoted literal, joined by `OR`.

    **`OR` and not FTS5's implicit `AND`.** `MAX_QUERY_TERMS` is 64 and a 64-term conjunction
    matches nothing in any real corpus, so an implicit-AND lexical Channel would report `EMPTY` for
    every sentence-shaped query -- absence produced by a tokeniser rather than by the corpus, which
    is the whole failure §6.8's gate ladder exists to prevent. Filtering is `narrow()`'s job
    (07:1585-1591) and ranking is this Channel's: bm25 already ranks a block matching four terms
    above one matching one, so the disjunction loses no precision it has any way to report.

    Each term is quoted, which makes it an FTS5 string literal rather than a fragment of the
    expression grammar; a term that still held a space after `_fts_safe` becomes a phrase, which is
    the narrower reading and never a syntax error.
    """
    quoted = [f'"{safe}"' for safe in (_fts_safe(term) for term in terms) if safe]
    return " OR ".join(quoted)


def _minmax(raw: Mapping[int, float]) -> dict[int, float]:
    """07:1303's `bm25n`: *"min-max normalised **within the Channel's own result set**"*.

    The input is already sign-flipped: SQLite's `bm25()` returns a NEGATIVE score where a better
    match is more negative, so every caller passes `-bm25(...)` and higher is better here.

    A one-element set, or a set where every score ties, normalises to `1.0` rather than to `0.0`.
    Both are defensible arithmetic and only one is defensible retrieval: the blocks are all equally
    the best this Channel found, and mapping them to zero would let `W_HEAD`'s spine term decide
    the whole ranking of a query whose body scores were unanimous.
    """
    if not raw:
        return {}
    low = min(raw.values())
    high = max(raw.values())
    if high <= low:
        return dict.fromkeys(raw, 1.0)
    return {block_id: (value - low) / (high - low) for block_id, value in raw.items()}


def _spines(
    connection: sqlite3.Connection, ids: Sequence[int]
) -> Mapping[int, tuple[tuple[int, int], ...]]:
    """`spine(b)` from `block_sec`, as `((block, depth), ...)` with `b` its own depth-0 ancestor.

    07:1299: *"`spine(b)` comes from `block_sec`; `b` is its own depth-0 ancestor."* `block_sec`
    gives each block its NEAREST section (`sec_id`), so the spine is that pointer followed
    repeatedly -- a section block has a `block_sec` row of its own naming its parent section. The
    walk is breadth-first by level so the whole frontier is one `IN (...)` statement per hop rather
    than one per block: a 100-candidate spine walk is at most `_SPINE_MAX_HOPS` statements.

    A row whose `sec_id` is its own `block_id` is a top-level section and ends the chain; so does a
    repeat, because `block_sec` has no CHECK that forbids a cycle and a cycle here would be a hang
    rather than a wrong number. `block_sec` may not exist at all (it is 0003's), and then every
    chain is just `((b, 0),)` -- the spine term flattens to the block's own head score, which is
    what "no section index" honestly means.
    """
    parent: dict[int, int] = {}
    pending = set(ids)
    seen: set[int] = set()
    for _ in range(_SPINE_MAX_HOPS):
        todo = sorted(pending - seen)
        if not todo:
            break
        seen.update(todo)
        pending = set()
        for start in range(0, len(todo), _ID_BATCH):
            chunk = todo[start : start + _ID_BATCH]
            rows = connection.execute(
                f"SELECT block_id, sec_id FROM block_sec "  # noqa: S608
                f"WHERE block_id IN ({_placeholders(len(chunk))})",
                chunk,
            )
            for block_id, sec_id in rows:
                if int(sec_id) != int(block_id):
                    parent[int(block_id)] = int(sec_id)
                    pending.add(int(sec_id))
    chains: dict[int, tuple[tuple[int, int], ...]] = {}
    for block_id in ids:
        chain = [(block_id, 0)]
        walked = {block_id}
        current = block_id
        while len(chain) <= _SPINE_MAX_HOPS:
            nxt = parent.get(current)
            if nxt is None or nxt in walked:
                break
            walked.add(nxt)
            chain.append((nxt, len(chain)))
            current = nxt
        chains[block_id] = tuple(chain)
    return chains


def _reading_order(
    connection: sqlite3.Connection, ids: Sequence[int]
) -> Mapping[int, tuple[int, int, int]]:
    """`{block_id: (doc_ord, page, ord)}` over the head generation -- the tie-break both new
    Channels sort by.

    07:1271-1272 names `(doc_ord, page, ord)` as `exact`'s third key and it is the only total,
    MEANINGFUL order the store has: `block_id` is *"a DURABLE surrogate"* (0001_init.sql:236) and
    sorting ties by it would order two equally-graded blocks by when they were ingested. A block
    missing from the map was retired between the Channel's statement and this one, and sorts first
    rather than raising -- it will be dropped and counted by `hydrate()`, which is where 07:2323
    says that fact is reported.
    """
    order: dict[int, tuple[int, int, int]] = {}
    for start in range(0, len(ids), _ID_BATCH):
        chunk = list(ids[start : start + _ID_BATCH])
        rows = connection.execute(
            f"SELECT block_id, doc_ord, page, ord FROM ow_block_head "  # noqa: S608
            f"WHERE block_id IN ({_placeholders(len(chunk))})",
            chunk,
        )
        for block_id, doc_ord, page, ord_ in rows:
            order[int(block_id)] = (int(doc_ord), int(page), int(ord_))
    return order


def _prefix_bounds(prefix: str) -> tuple[str, str]:
    """The half-open `[prefix, prefix + U+10FFFF)` range a prefix filter becomes.

    See `_PREFIX_SENTINEL` for why the sentinel and not the increment-the-last-component form the
    `block_sec` DDL prints.
    """
    return prefix, prefix + _PREFIX_SENTINEL


# ---------------------------------------------------------------------------
# The Reader
# ---------------------------------------------------------------------------


class SqliteReader:
    """The SQLite `Reader`. Six methods, one connection, and it opens nothing.

    **It takes a connection rather than a path**, because `store/sqlite.py` owns every open
    (`connect`, `connect_readonly`, and the pragma order that makes the narrowing probe legal on a
    `mode=ro` mount -- 07:186-190). A `Reader` that opened its own file would be a second
    `sqlite3.connect` and INV-17 would stop holding by construction.

    **One connection serves one query at a time** (07:1604-1607): *"The connection is checked out
    for the `Snapshot`'s lifetime and returned when it closes."* `tmp_narrow`, `tmp_docs` and
    `tmp_refs` live in that connection's TEMP schema, which is why they are `CREATE TEMP TABLE IF
    NOT EXISTS` plus `DELETE FROM` rather than `CREATE`/`DROP` -- *"a read connection is pooled and
    reused across queries; a bare `CREATE TEMP TABLE` fails on the second query on that
    connection"* (07:1601-1603).

    **Every method that takes a `Snapshot` refuses one this `Reader` did not issue and one that has
    closed.** 07:75-78 types `Snapshot.token` as an opaque `object` so a Postgres backend can build
    one at all, and the corollary is that a token is only meaningful to the backend that minted it:
    handing this `Reader` another store's `Snapshot` would otherwise read THIS file under THAT
    file's generation, which is a silent wrong answer rather than an error. The liveness half is
    the same argument in time rather than in space -- 07:2789-2793's deadline means a `Snapshot`
    outlives its transaction as a Python object, and reading through a rolled-back one reads
    whatever the connection is doing now.
    """

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        now_ns: int,
        snapshot_ms: int | None = None,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        vectors: VectorBackend | None = None,
    ) -> None:
        """Bind to `connection` and read `IndexCaps` ONCE, at open (07:3272).

        `now_ns` is required and has no default: `IndexCaps.stat_age_ns` is an age, and the store
        takes its clock from its caller everywhere else (`migrate.apply_pending(conn, *, now_ns)`).
        `snapshot_ms` is passed straight through to `sqlite.snapshot()`, which clamps it below
        `MAX_SNAPSHOT_MS` and reads `[retrieval] snapshot_ms` when it is `None`.

        `monotonic_ns` is a DURATION source and not a clock, which is the distinction that makes it
        legal here at all: `store/sqlite.py`'s own `snapshot()` takes the same parameter with the
        same default and the same reason, which `store/sqlite.py:44-45` states as a duration not
        being a wall reading -- and a test can
        spend a Channel's budget without spending the wall time. `now_ns` above is the wall clock
        and stays required; these are two different facts and the store has never conflated them.

        `vectors` is the `VectorBackend` the config named, ALREADY SELECTED. 18-api-sketch.md:1708
        makes `[retrieval] vec.backend` (18:1708) *"an `omniweave.backends` entry-point name,
        selected **by
        name in config only** -- a Backend is never resolved and never in `resolve()`"*, so the
        selection happens once, outside, and this class receives the result -- the same shape as
        the connection it does not open. `None` is the shipped default because
        `[retrieval] vectors = "off"` is (07:2596), and it makes the semantic Channel
        `unavailable` rather than absent.
        """
        self._connection = connection
        self._snapshot_ms = snapshot_ms
        self._monotonic_ns = monotonic_ns
        self._vectors = vectors
        self._live: list[Snapshot] = []
        self._kinds = _enum_codes(connection, "kind")
        self._layers = _enum_codes(connection, "layer")
        self._methods = _enum_codes(connection, "method")
        self._os_kinds = _enum_codes(connection, "origin_span_kind")
        self._caps = self._read_capabilities(now_ns)

    # -- 1. snapshot -------------------------------------------------------

    def snapshot(self) -> AbstractContextManager[Snapshot]:
        """One `BEGIN DEFERRED` for the whole query (ST2), delegated to `sqlite.snapshot()`.

        07:2758-2762 is the rule and 07:2777-2782 is the mechanism -- `BEGIN DEFERRED` followed
        IMMEDIATELY by `SELECT v FROM index_state WHERE k='generation'`, because a deferred
        transaction does not acquire its read view until its first statement. `store/sqlite.py`
        already implements exactly that, with the `MAX_SNAPSHOT_MS` interrupt and the exit-time
        elapsed check, so this method adds one thing and only one: it records the `Snapshot` as
        LIVE and issued by this `Reader`, which is what lets the other five refuse a token they
        cannot honour.

        Written as a plain method returning a context manager rather than as a `@contextmanager`
        generator, so the annotation is 07:63's `AbstractContextManager[Snapshot]` verbatim rather
        than the `Iterator[Snapshot]` a decorated generator declares.
        """
        return self._snapshot()

    @contextmanager
    def _snapshot(self) -> Iterator[Snapshot]:
        with ow.snapshot(self._connection, snapshot_ms=self._snapshot_ms) as state:
            self._live.append(state)
            try:
                yield state
            finally:
                self._live = [live for live in self._live if live is not state]

    # -- 2. capabilities ---------------------------------------------------

    def capabilities(self) -> IndexCaps:
        """What `plan()` may know about this store. READ ONCE, AT OPEN (07:3272).

        Returns the object built in `__init__`, so two calls are the same object and neither
        touches the connection. That is not an optimisation: `caps_digest` *"memoises `plan()`"*
        (07:3280), and a digest that could change between two calls inside one process would make
        the memo key describe a store state the plan was not built against.
        """
        return self._caps

    def _read_capabilities(self, now_ns: int) -> IndexCaps:
        """The seventeen fields of 07:3273-3280, each from the source that owns it.

        `caps_digest` is *"sha256_canonical of every field above; memoises `plan()`"* (07:3280), so
        it is computed with `omniweave_core.canonical`'s `sha256_canonical` and not hand-rolled --
        one canonicaliser, and the one whose grammar refuses a `str()` fallback (INV-21, I12).
        The digest input is a MAPPING keyed by field name rather than a positional tuple: canonical
        JSON sorts keys (`canonical.py`'s docstring), so the digest is stable under a field
        reordering that `types.py` warns is a behaviour change -- which makes the digest more
        robust than the ordering, not less. `channels` becomes a sorted list because a `frozenset`
        is outside canonical JSON's grammar and its iteration order is not stable across processes.

        `vec_backend` and `vec_pushdown` come from the sidecar's `vec_manifest` (07:3339-3348)
        and W6.2d fills them: `_read_vec_manifest` below is the read, and it is here rather than in
        the Channel because 07:3272 is *"read once, at open"* and `caps_digest` memoises `plan()`.
        **`vec_attached` here means attached AND matching**, which is one condition more than
        `store/sqlite.py`'s `snapshot()` applies -- that module records the second half as owed to
        *"whoever ATTACHes the sidecar"* and nothing attaches one yet, so the Reader applies it and
        the two will agree when the attach path lands.
        `federated` is T4's (07 section 12) and no shipped table can make it true.

        `fts_state` defaults to `stale` and not to `ok` when the key is missing. The three-state
        machine is written *"in the same transaction as the DDL that invalidates it, so a crash
        leaves the pessimistic value"* (0003_index.sql:413-418), and a store with no row at all is
        exactly as unknown as a crashed one -- *"a missing posting is indistinguishable from an
        absent phrase"*.
        """
        connection = self._connection
        objects = _objects(connection)
        self._objects = objects
        state = _index_state_map(connection)
        stats = _stat_rows(connection)
        self._vec, self._vec_reason = self._read_vec_manifest(
            connection, str(state.get("corpus_id", ""))
        )
        vec_attached = self._vec is not None
        space_id = int(state["default_space_id"]) if "default_space_id" in state else None
        channels = self._store_channels(objects, vec_attached, space_id)

        fields: Mapping[str, bool | int | str | list[str] | None] = {
            "schema": state.get("schema", ""),
            "scorer_version": int(state.get("scorer_version", 0)),
            "channels": sorted(channels),
            "has_head_fts": "head_fts" in objects,
            "has_trigram": "block_tri" in objects,
            "fts_state": state.get("fts_state", "stale"),
            "space_id": space_id,
            "vec_backend": self._vec.backend if self._vec else None,
            "vec_ceiling": VEC_BRUTE_MAX if vec_attached else 0,
            "vec_pushdown": bool(self._vec and self._vec.pushdown),
            "live_blocks": stats.get("live_blocks", (0, 0))[0],
            "live_segments": stats.get("live_segments", (0, 0))[0],
            "docs": stats.get("docs", (0, 0))[0],
            "stat_age_ns": self._stat_age_ns(stats, now_ns),
            "shard_ord": int(state.get("shard_ord", 0)),
            "federated": False,
        }
        return IndexCaps(
            schema=str(fields["schema"]),
            scorer_version=int(state.get("scorer_version", 0)),
            channels=channels,
            has_head_fts="head_fts" in objects,
            has_trigram="block_tri" in objects,
            fts_state=str(fields["fts_state"]),
            space_id=space_id,
            vec_backend=self._vec.backend if self._vec else None,
            vec_ceiling=VEC_BRUTE_MAX if vec_attached else 0,
            vec_pushdown=bool(self._vec and self._vec.pushdown),
            live_blocks=stats.get("live_blocks", (0, 0))[0],
            live_segments=stats.get("live_segments", (0, 0))[0],
            docs=stats.get("docs", (0, 0))[0],
            stat_age_ns=self._stat_age_ns(stats, now_ns),
            shard_ord=int(state.get("shard_ord", 0)),
            federated=False,
            caps_digest=sha256_canonical(fields),
        )

    @staticmethod
    def _store_channels(
        objects: frozenset[str], vec_attached: bool, space_id: int | None
    ) -> frozenset[str]:
        """*"Which of the five CAN run at all in this store"* (07:3275) -- a STORE fact.

        Not a fact about this build; see the module docstring for why intersecting it with
        `_IMPLEMENTED_CHANNELS` would convert a disclosed limitation into a silent one.

        * `identity` needs `block_cite` and `block_addr`, both `0001_init.sql`'s (:320-321).
        * `exact` needs `anchor` (0002) and `ref_site` (0003), the two halves of its one statement.
        * `lexical` needs `block_fts`. `fts_state` is reported separately, because a `building` or
          `stale` index is a Channel that CAN run and must report `unavailable` when it does
          (0003_index.sql:413-418) -- a different fact from one that cannot run at all.
        * `structural` needs `block_link`; `edge` is *"not traversed by this Channel at v1"*
          (07:1308-1310), so L3's absence does not remove the Channel from the store.
        * `semantic` needs the `vec` sidecar ATTACHED and a `default_space_id` to join through.
          `[retrieval] vectors = "off"` is a config choice, disclosed by the planner as
          `OffReason.VECTORS` (02-architecture.md:499), and is not this field's business.
        """
        present = set()
        if {"block_cite", "block_addr"} <= objects:
            present.add("identity")
        if {"anchor", "ref_site"} <= objects:
            present.add("exact")
        if "block_fts" in objects:
            present.add("lexical")
        if "block_link" in objects:
            present.add("structural")
        if vec_attached and space_id is not None:
            present.add("semantic")
        return frozenset(present)

    @staticmethod
    def _stat_age_ns(stats: Mapping[str, tuple[int, int]], now_ns: int) -> int:
        """The age of the OLDEST of the three scalar counts, and `now_ns` when any is missing.

        07:729-731: *"`age > STAT_MAX_AGE_NS` **or a key is missing** ⇒ the over-fetch factor is
        the maximum clamp, 64."* `stat_age_ns` is the only carrier `IndexCaps` gives that rule, so
        a missing key has to produce an age above the threshold rather than a comfortable zero: a
        never-computed key is treated as computed at time 0, which is what `now_ns - 0` says.
        Taking the OLDEST rather than the newest is the same fail-expensive reading -- *"a wrong
        over-fetch factor is a silent recall loss, so staleness fails expensive"* (07:733).
        """
        oldest = now_ns
        for key in ("live_blocks", "live_segments", "docs"):
            computed_ns = stats.get(key, (0, 0))[1]
            oldest = min(oldest, computed_ns)
        return now_ns - oldest

    # -- the Snapshot guard ------------------------------------------------

    def _bound(self, state: Snapshot) -> sqlite3.Connection:
        """The connection behind `state`, or a refusal. Every `Snapshot`-taking method starts here.

        Three checks, in the order a wrong answer gets worse: a value that is not a `Snapshot` at
        all, a `Snapshot` whose token is another backend's or another store's, and one this
        `Reader` issued but whose transaction has ended. The middle one is the load-bearing one --
        `Snapshot.token` is `object` by design (07:75-78), so nothing in the type system stops a
        caller threading store A's snapshot through store B's reader, and the result would be a
        consistent-looking read of the wrong file.
        """
        if not isinstance(state, Snapshot):
            msg = (
                f"{type(state).__name__} is not a Snapshot: every read but `capabilities()` is "
                f"inside one BEGIN DEFERRED (ST2, 07:2758-2762)"
            )
            raise StoreError(msg, fix="open one with `with reader.snapshot() as s:`")
        if state.token is not self._connection:
            msg = (
                "this Snapshot was issued by another Reader: `Snapshot.token` is backend-private "
                "(07:72-78), so reading THIS store through it would answer under ANOTHER store's "
                "generation and corpus_id, which is a wrong answer rather than an error"
            )
            raise StoreError(msg, fix="open the snapshot on the Reader you are querying")
        if not any(live is state for live in self._live):
            msg = (
                f"this Snapshot has closed: its read transaction ended at generation "
                f"{state.generation}, and a statement issued now would run outside it and see "
                f"whatever has been committed since (07:2770-2775)"
            )
            raise StoreError(msg, fix="do the read inside the `with reader.snapshot()` block")
        return self._connection

    # -- 3. narrow ---------------------------------------------------------

    def narrow(self, s: Snapshot, f: Filters) -> Narrowing:
        """FILTERS NARROW; CHANNELS SCORE WITHIN THE NARROWED SET (07:1564).

        The three-way tag is MEASURED, not chosen. 07:1585-1591 prints the statement and 07:1593
        prints the rule: *"A `LIMIT PREFILTER_MAX + 1` probe gives an **exact** candidate set or
        **proves** it is too big. No histogram, no independence assumption, no cost-based
        optimiser."* So `n` rows come back capped at `PREFILTER_MAX + 1`, and the tag is a
        function of the count: `empty` at zero, `set` at or below the cap, `all` above it.

        **`kind="empty"` and `kind="all"` mean opposite things** (ST5, 07:1666-1680), which is why
        `Narrowing` is tagged and why `if narrowing:` is banned: jcodemunch's falsy check turned a
        query that matched nothing into a Channel over the whole repository, ranked by centrality
        and labelled *"Confident matches returned"*.

        **A filter set that is empty short-circuits before any statement runs.** `doc_keys`,
        `formats`, `kinds` and `layers` are `frozenset | None` (or, for `layers`, a `frozenset`
        defaulting to `{Layer.BODY}`): `None` means no restriction and an EMPTY set means restrict
        to nothing, because with a `None` in the type there is no third state to fold them into.
        That asymmetry is ST5's own, stated for `deny_methods` at 07:1637-1640 -- the field there
        is `frozenset[Method]` and NOT `| None` *"because there is no third state to represent"*,
        which only says what it says if the `| None` fields DO have three.

        **The TEMP table is `IF NOT EXISTS` plus `DELETE FROM`** (07:1601-1603) and it is a write
        to the temp schema, which `temp_store = MEMORY` makes legal on a `mode=ro` connection
        (07:186-190). That pragma's second job is the reason this method works at all on a
        read-only mount.
        """
        connection = self._bound(s)
        self._refuse_bad_filters(f)
        empty_field = self._empty_filter_field(f)
        if empty_field is not None:
            return Narrowing(kind="empty", table=None, n=0)

        where, params = self._narrow_predicates(f)
        joins = self._narrow_joins(f)
        connection.execute(
            f"CREATE TEMP TABLE IF NOT EXISTS {_TMP_NARROW}"
            f"(block_id INTEGER PRIMARY KEY) WITHOUT ROWID"
        )
        connection.execute(f"DELETE FROM {_TMP_NARROW}")  # noqa: S608
        if f.doc_keys is not None and len(f.doc_keys) > MAX_FILTER_DOC_KEYS:
            self._fill_tmp_docs(connection, f.doc_keys)
        cap = PREFILTER_MAX + 1
        connection.execute(
            f"INSERT INTO {_TMP_NARROW} "  # noqa: S608
            f"SELECT b.block_id FROM block b JOIN doc d USING (doc_ord){joins} "
            f"WHERE {' AND '.join(where)} LIMIT ?",
            (*params, cap),
        )
        n = _one_int(connection, f"SELECT count(*) FROM {_TMP_NARROW}")  # noqa: S608
        if n == 0:
            return Narrowing(kind="empty", table=None, n=0)
        if n >= cap:
            return Narrowing(kind="all", table=None, n=n)
        return Narrowing(kind="set", table=_TMP_NARROW, n=n)

    @staticmethod
    def _refuse_bad_filters(f: Filters) -> None:
        """The three usage errors 07 section 6.1 names, plus DEFECT 1's fourth.

        * `formats` containing `'owjob'` is *"a **usage error** naming `NO_JOB_DOCS`, not an empty
          result"* (07:754), because `owjob` is minted by the job runner and is not a detectable
          format token, so selecting on it can only be a mistake.
        * `pages` must be a `range` of step 1: *"any other step is a usage error, because a strided
          page filter has no index expression and would silently become a full scan"* (07:1613).
        * `gen` is `Literal["head"] | int`; anything else is neither.
        * `lang` names no column in any shipped migration -- see DEFECT 1 in the module docstring.
        """
        if f.formats is not None and "owjob" in f.formats:
            msg = (
                "Filters.formats names 'owjob', which is a synthetic job document's format and "
                "never a detectable one (NO_JOB_DOCS, 07:754): selecting on it can only be a "
                "mistake, so it is refused rather than answered with an empty result"
            )
            raise UsageError(msg, fix="drop 'owjob' from --format")
        if f.pages is not None and f.pages.step != 1:
            msg = (
                f"Filters.pages has step {f.pages.step}; a page filter must be a contiguous "
                f"range, because a strided one has no index expression and would silently "
                f"become a full scan (07:1613-1615)"
            )
            raise UsageError(msg, fix="pass a contiguous --pages range")
        if not (f.gen == "head" or isinstance(f.gen, int)):
            msg = f"Filters.gen is {f.gen!r}; it is the literal 'head' or a parse generation int"
            raise UsageError(msg, fix="--gen head")
        if f.lang is not None:
            msg = (
                "Filters.lang is declared at 07:1573 and no shipped migration creates a language "
                "column on block, doc, page or segment, so the filter cannot be applied. It is "
                "refused rather than ignored, because ignoring it would widen the query to the "
                "whole corpus and return a confident answer from the wrong population"
            )
            raise UsageError(msg, fix="drop --lang until the column ships")

    @staticmethod
    def _empty_filter_field(f: Filters) -> str | None:
        """The name of the first positively-empty set filter, or `None`.

        A short circuit and not an optimisation: the probe would return zero rows anyway, and the
        point of returning before it runs is that `kind="empty"` is a PROVEN empty rather than a
        measured one, so no statement, no TEMP table and no `LIMIT` scan are paid for a set whose
        emptiness is a property of the request.
        """
        for name, value in (
            ("doc_keys", f.doc_keys),
            ("formats", f.formats),
            ("kinds", f.kinds),
            ("layers", f.layers),
        ):
            if value is not None and len(value) == 0:
                return name
        return None

    def _narrow_joins(self, f: Filters) -> str:
        """The two optional joins the narrowing statement may need."""
        joins = ""
        if f.sec_path_prefix is not None:
            joins += " JOIN block_sec bs ON bs.block_id = b.block_id"
        if f.doc_keys is not None and len(f.doc_keys) > MAX_FILTER_DOC_KEYS:
            joins += f" JOIN {_TMP_DOCS} td ON td.doc_key = d.doc_key"
        return joins

    def _fill_tmp_docs(self, connection: sqlite3.Connection, doc_keys: frozenset[bytes]) -> None:
        """`Filters.doc_keys` above `MAX_FILTER_DOC_KEYS` becomes a second TEMP table (07:1608).

        *"SQLite's parameter and expression-tree limits make a 100k-element `IN` list a parse-time
        failure rather than a slow query"* -- so the cap changes the PLAN and never refuses the
        query.
        """
        connection.execute(
            f"CREATE TEMP TABLE IF NOT EXISTS {_TMP_DOCS}(doc_key BLOB PRIMARY KEY) WITHOUT ROWID"
        )
        connection.execute(f"DELETE FROM {_TMP_DOCS}")  # noqa: S608
        connection.executemany(
            f"INSERT OR IGNORE INTO {_TMP_DOCS}(doc_key) VALUES (?)",  # noqa: S608
            [(key,) for key in sorted(doc_keys)],
        )

    def _narrow_predicates(self, f: Filters) -> tuple[list[str], list[object]]:
        """07:1587-1591's `WHERE`, extended to all thirteen `Filters` fields.

        The printed statement abbreviates its own predicate list with an ellipsis and covers six
        fields; `Filters` has thirteen and 07:1564 says filters NARROW, so every field that names
        a shipped column is applied. Two details the printed form fixes and this keeps:

        * **`b.method NOT IN (...)` is OMITTED ENTIRELY when `deny_methods` is empty** (07:1590),
          which is ST5 in the SQL: an empty deny list is no restriction, never a restriction to
          nothing, and an emitted `NOT IN ()` would be the second reading.
        * **The enum codes are resolved on the read connection** (07:1655-1657) through
          `enum_val`, never from this build's Python enums.

        `gen = "head"` is `b.gen = d.gen`, the head-generation projection every reader goes
        through (0001_init.sql:328-330); an explicit int pins the parse generation instead, which
        is what lets a superseded citation still resolve (07:2925-2928).
        """
        where: list[str] = ["b.state = 0"]
        params: list[object] = []

        if f.gen == "head":
            where.append("b.gen = d.gen")
        else:
            where.append("b.gen = ?")
            params.append(int(f.gen))

        where.append(f"b.layer IN ({_placeholders(len(f.layers))})")
        params.extend(self._codes(self._layers, f.layers, "layer"))

        if f.kinds is not None:
            where.append(f"b.kind IN ({_placeholders(len(f.kinds))})")
            params.extend(self._codes(self._kinds, f.kinds, "kind"))

        where.append("(b.restriction_bits & ?) = 0")
        params.append(int(f.deny_restriction_bits))

        if f.min_trust is not None:
            where.append("b.trust >= ?")
            params.append(int(f.min_trust))
        if f.min_quote is not None:
            where.append("b.quote >= ?")
            params.append(int(f.min_quote))

        if f.deny_methods:
            where.append(f"b.method NOT IN ({_placeholders(len(f.deny_methods))})")
            params.extend(self._codes(self._methods, f.deny_methods, "method"))

        if f.pages is not None:
            where.append("b.page >= ? AND b.page < ?")
            params.extend((f.pages.start, f.pages.stop))

        if f.doc_keys is not None and len(f.doc_keys) <= MAX_FILTER_DOC_KEYS:
            where.append(f"d.doc_key IN ({_placeholders(len(f.doc_keys))})")
            params.extend(sorted(f.doc_keys))

        if f.formats is not None:
            where.append(f"d.format IN ({_placeholders(len(f.formats))})")
            params.extend(sorted(f.formats))

        if f.uri_prefix is not None:
            low, high = _prefix_bounds(f.uri_prefix)
            where.append("d.uri >= ? AND d.uri < ?")
            params.extend((low, high))

        if f.sec_path_prefix is not None:
            low, high = _prefix_bounds(f.sec_path_prefix)
            where.append("bs.sec_path >= ? AND bs.sec_path < ?")
            params.extend((low, high))

        return where, params

    @staticmethod
    def _codes(domain: Mapping[str, int], members: frozenset[object], name: str) -> list[int]:
        """The `enum_val` ordinals for `members`, sorted, refusing a member the store never seeded.

        A member missing from `enum_val` is not a filter that matches nothing -- it is a store
        whose seed is older than this build's enum, and answering the query would silently drop
        every row of that kind. `enum_val.ord` is append-only (03 section 2.1), so the condition is
        real and one-directional.
        """
        codes: list[int] = []
        for member in sorted(str(m) for m in members):
            if member not in domain:
                msg = (
                    f"this store's enum_val has no {name} member {member!r}: its seed predates "
                    f"this build, and filtering on a code it cannot hold would silently drop "
                    f"every row of that {name}"
                )
                raise StoreError(msg, fix="ow store migrate")
            codes.append(domain[member])
        return sorted(codes)

    # -- 4. channel --------------------------------------------------------

    def channel(self, s: Snapshot, spec: ChannelSpec, n: Narrowing) -> ChannelOutcome:
        """Run one Channel, or say legibly why this build does not.

        The dispatch is a closed five-way over 07:1196's `CHANNELS`; a sixth name is a usage error
        rather than a silent `off`, because `ChannelSpec.name` is *"a member of `CHANNELS`"*
        (07:3295) and an unknown Channel in a plan is a planner bug the store should surface.

        All five run; the module docstring argues each one. See `_identity`, `_exact`,
        `_lexical`, `_structural` and `_semantic`. `semantic` is the one that reports
        `unavailable` on every stock store, because `[retrieval] vectors = "off"` is the shipped
        default permanently (07:2596) -- which is a configuration fact and not a build one.

        **The order of the three checks is the order of the three different facts.** An unknown
        name is a planner bug (`UsageError`); a known name this build has not shipped is
        `OFF(not_built)`, ceiling-exempt and disclosed; a shipped Channel whose tables this store
        does not carry is `UNAVAILABLE`, which forces `degraded` -- a store fact, not a build one.
        The empty narrowing comes last because it is the only one of the four that is about the
        QUERY, and a Channel that could not have run anyway must say so before it says the
        candidate set was empty.

        **A `Narrowing` of `kind="empty"` short-circuits every Channel**, including the ones that
        would run. That is the tagged type doing its job: an empty narrowed set is a PROVEN empty
        result, and scoring over it is the jcodemunch failure in the other direction.
        """
        connection = self._bound(s)
        refusal = self._refuse(spec, n)
        if refusal is not None:
            return refusal
        if spec.name == "identity":
            return self._identity(connection, spec, n)
        if spec.name == "lexical":
            return self._lexical(connection, spec, n)
        if spec.name == "structural":
            return self._structural(connection, spec, n)
        if spec.name == "semantic":
            return self._semantic(connection, spec, n)
        return self._exact(connection, spec, n)

    def _refuse(self, spec: ChannelSpec, n: Narrowing) -> ChannelOutcome | None:
        """The four pre-flight answers, or `None` when the Channel should actually run.

        Split out of `channel()` so the dispatch reads as a dispatch. The ORDER is the argument and
        it is `channel()`'s docstring; this method only carries it out.
        """
        if spec.name not in CHANNELS:
            msg = (
                f"{spec.name!r} is not one of the five Channels {CHANNELS}: ChannelSpec.name is "
                f"a member of CHANNELS (07:3295), and the five are closed by 07:1196"
            )
            raise UsageError(msg, fix="name one of identity, exact, lexical, structural, semantic")
        if spec.name not in _IMPLEMENTED_CHANNELS:
            return ChannelOutcome(name=spec.name, status="off", reason=_OFF_NOT_BUILT)
        missing = [name for name in _REQUIRED_OBJECTS[spec.name] if name not in self._objects]
        if missing:
            return ChannelOutcome(
                name=spec.name,
                status="unavailable",
                reason=f"this store carries no {', '.join(missing)}",
            )
        if n.kind == "empty":
            return ChannelOutcome(
                name=spec.name,
                status="empty",
                reason="the narrowed set is empty, so there is nothing inside it to rank",
            )
        return None

    def _identity(
        self, connection: sqlite3.Connection, spec: ChannelSpec, n: Narrowing
    ) -> ChannelOutcome:
        """07:1254-1270's ladder: three index lookups and a `head_fts` title probe, graded.

        *"A ladder over exact and near-exact addresses of a block or document. The reported grade
        is **the one actually measured**, never the tier that was asked for."* (07:1254-1255.) The
        ladder itself, and the four-answer `grade_title()` that measures its title half, live in
        `omniweave_core.retrieve.channels` -- 07:1259 prints `IDENTITY_LADDER` inside §5.2, which is
        the query path's section, and a second copy here is the drift that would let 40 and 45 tie.

        **The strongest measured tier wins per block, not the first ident tried.** A query carrying
        both `d7#412` and the document's title can reach one block twice; `ranked` is
        duplicate-free (07:1228) so one of the two grades has to go, and taking the higher is the
        only choice consistent with *"the tier ACTUALLY measured"* -- the cite lookup DID measure
        50, and reporting 40 because a title probe ran second would understate evidence the Channel
        holds.

        **The order is the ladder, then reading order.** `IDENTITY_LADDER` descending is the whole
        point of the Channel; `(doc_ord, page, ord)` breaks ties, because two blocks at tier 50 in
        the same document should come back in the order a reader would meet them and not in
        `block_id` order, which is ingest order.

        Six of the ladder's nine tiers are reachable and D241 records why the other three are not:
        `doc_key_prefix` has no spelling for a prefix of sixteen binary bytes, `spine_segment` is
        named once and defined nowhere, and `addr_exact` needs a document scope -- that last one is
        reachable HERE whenever `ChannelInput.scope_doc` is set, which is the half of D241's first
        clause this cell could discharge.
        """
        bind = spec.bind
        idents = () if bind is None else bind.idents
        if not idents:
            return ChannelOutcome(
                name=spec.name,
                status="empty",
                reason="the query carried no cite, addr, uri or title candidate",
            )
        narrow_join = ""
        if n.kind == "set":
            narrow_join = f" JOIN {_TMP_NARROW} tn ON tn.block_id = b.block_id"
        scope_doc = None if bind is None else bind.scope_doc
        graded: dict[int, str] = {}
        for ident in idents:
            for block_id, tier in self._probe_ident(
                connection, ident, scope_doc=scope_doc, narrow_join=narrow_join, limit=spec.limit
            ):
                held = graded.get(block_id)
                if held is None or IDENTITY_LADDER[tier] > IDENTITY_LADDER[held]:
                    graded[block_id] = tier
        if not graded:
            return ChannelOutcome(
                name=spec.name,
                status="empty",
                reason="no cite, addr, uri or title matched",
            )
        order = _reading_order(connection, sorted(graded))
        ranked = sorted(
            graded,
            key=lambda block_id: (
                -IDENTITY_LADDER[graded[block_id]],
                order.get(block_id, (0, 0, 0)),
                block_id,
            ),
        )
        truncated = spec.limit > 0 and len(ranked) > spec.limit
        if truncated:
            ranked = ranked[: spec.limit]
        return ChannelOutcome(
            name=spec.name,
            status="ok",
            ranked=tuple(ranked),
            grades=MappingProxyType({block_id: graded[block_id] for block_id in ranked}),
            truncated_at_limit=truncated,
        )

    def _probe_ident(
        self,
        connection: sqlite3.Connection,
        ident: str,
        *,
        scope_doc: int | None,
        narrow_join: str,
        limit: int,
    ) -> list[tuple[int, str]]:
        """One ident down the ladder, stopping at the first rung that measured something.

        The rungs are tried strongest first and the first one that matched is the answer, which is
        what makes the reported grade the MEASURED one: a cite that resolved is tier 50 and its
        block is not then handed to a title probe that might grade it 30.

        The cite rung supplies BOTH columns of `block_cite` -- `UNIQUE INDEX block_cite ON
        block(doc_ord, cite)` (0001_init.sql:306) -- by parsing the `doc_ord` out of the cite
        string itself. Without that the equality on `cite` alone cannot use the index and 07:1269's
        *"sub-millisecond"* lookup is a full scan of `block`. D240.

        The addr rung runs only under a document scope, for the same two-column reason and one
        more: `p14/3` is document-relative by construction, so a corpus-wide `addr` equality would
        match one block per document and call all of them tier 50. `block_addr` is
        `(doc_ord, gen, addr)`, and `ow_block_head` supplies the `gen`.

        Nothing here validates the ident's SHAPE first. A title tried against `block_cite` is one
        index probe that misses, which is cheaper than a second copy of `retrieve.channels`'s three
        shape patterns and cannot disagree with them.
        """
        text = normalise_query_text(ident)
        doc_ord = cite_doc_ord(text)
        if doc_ord is not None:
            rows = connection.execute(
                f"SELECT b.block_id FROM ow_block_head b{narrow_join} "  # noqa: S608
                f"WHERE b.doc_ord = ? AND b.cite = ?",
                (doc_ord, text),
            ).fetchall()
            return [(int(row[0]), "cite_exact") for row in rows]
        if scope_doc is not None:
            rows = connection.execute(
                f"SELECT b.block_id FROM ow_block_head b{narrow_join} "  # noqa: S608
                f"WHERE b.doc_ord = ? AND b.addr = ?",
                (scope_doc, text),
            ).fetchall()
            if rows:
                return [(int(row[0]), "addr_exact") for row in rows]
        by_uri = self._probe_doc_uri(connection, text, narrow_join)
        if by_uri is not None:
            return [(by_uri, "doc_uri_exact")]
        return self._probe_title(connection, text, narrow_join, limit)

    def _probe_doc_uri(
        self, connection: sqlite3.Connection, uri: str, narrow_join: str
    ) -> int | None:
        """`doc(uri)` at tier 50 -- and the ONE block a document-level identity resolves to.

        07:1254 says the ladder is over *"a block **or document**"* and `ChannelResult.ranked` is
        `block_ids` (07:1228), so a matched document has to become blocks. It becomes exactly one:
        the document root block (`addr = 'doc'`, 0001_init.sql:240) when it exists, otherwise the
        first block in reading order.

        The alternative -- every block of the document at tier 50 -- is the one that breaks the
        arithmetic. `fuse()` gives rank 1 the weight `2.0/61` and a 41,822-block document would put
        41,822 blocks above every other Channel's first hit, so a `--scope` that matched one URI
        would return that document and nothing else with `confidence = 1.000`. One block is an
        ADDRESS, which is what a tier-50 identity hit is; the rest of the document is what
        `structural` and `hydrate()` are for.

        Returning `None` when the document has no block in view is deliberate and is D239's shape
        avoided: the Channel then reports `EMPTY` rather than `OK` with an empty ranking.
        """
        row = connection.execute("SELECT doc_ord FROM doc WHERE uri = ?", (uri,)).fetchone()
        if row is None:
            return None
        found = connection.execute(
            f"SELECT b.block_id FROM ow_block_head b{narrow_join} WHERE b.doc_ord = ? "  # noqa: S608
            f"ORDER BY (b.addr <> 'doc'), b.page, b.ord, b.block_id LIMIT 1",
            (int(row[0]),),
        ).fetchone()
        return None if found is None else int(found[0])

    def _probe_title(
        self, connection: sqlite3.Connection, ident: str, narrow_join: str, limit: int
    ) -> list[tuple[int, str]]:
        """07:1269's *"`head_fts` title probe"*, graded by `grade_title()` into 45 / 40 / 30.

        Two steps, and the split is the whole design. FTS5 finds CANDIDATES -- every labelled block
        sharing a token with the ident -- and `grade_title()` decides the tier by comparing the
        strings exactly. An FTS5 match is not itself a grade: `unicode61 remove_diacritics 2` folds
        case and diacritics and nothing else, so it cannot tell `"Table 3.2"` from `"Table 3-2"`
        from `"Table 3.2 (revised)"`, which are 45, 40 and 30 and are the three the 40 tier exists
        to keep apart (07:1264-1268).

        The probe is disjunctive for the same reason `_fts_match` is, and additionally because the
        30 tier is symmetric: `"Table 3.2 (revised)"` as the IDENT and `"Table 3.2"` as the label is
        a prefix match, and a conjunction over the ident's tokens would never surface the shorter
        label as a candidate at all.

        `head_fts` is 0003's and a store without it has no title tiers; the three index rungs still
        answer, so the Channel narrows rather than fails. `IndexCaps.has_head_fts` is the store fact
        that says which (07:3275).
        """
        if not self._caps.has_head_fts:
            return []
        match = _fts_match(ident.split())
        if not match:
            return []
        rows = connection.execute(
            f"SELECT b.block_id, b.label FROM head_fts h "  # noqa: S608
            f"JOIN ow_block_head b ON b.block_id = h.rowid{narrow_join} "
            f"WHERE head_fts MATCH ? ORDER BY bm25(head_fts) LIMIT ?",
            (match, max(limit, 1)),
        ).fetchall()
        graded: list[tuple[int, str]] = []
        for block_id, label in rows:
            tier = grade_title(ident, "" if label is None else str(label))
            if tier != "none":
                graded.append((int(block_id), tier))
        return graded

    def _lexical(
        self, connection: sqlite3.Connection, spec: ChannelSpec, n: Narrowing
    ) -> ChannelOutcome:
        """07:1294-1302's `lex(b)`, which is where *"D5 owns the BM25 weights"* is discharged.

        ```
        lex(b) = W_BODY x bm25n(block_fts, b)
               + W_HEAD x max over a in spine(b) of ( bm25n(head_fts, a) x SPINE_DECAY**depth(b,a) )
        ```

        **`fts_state` is read BEFORE anything runs.** 07:1823 and 0003_index.sql:413-418 make it a
        three-state machine this Channel is the reader of: `building` and `stale` are
        `UNAVAILABLE(fts_building)` / `(fts_stale)` and force `degraded`, because 07:433 --
        *"a missing posting is indistinguishable from an absent phrase"* -- and the whole of
        §6.8's gate ladder turns on that distinction. `unavailable` and not `empty`, because
        `empty` means the statement RAN.

        **The candidate set is the body matches, and only those.** 07:1300 leaves it to the
        implementation -- `bm25n` is normalised *"within the Channel's own result set"* -- and the
        two wider readings both break. Admitting `head_fts` matches directly returns container
        blocks whose `text` is NULL, which `hydrate()` cannot render; admitting their DESCENDANTS
        returns a whole section for a two-word heading, which is the `Expand` frontier of 07:1327
        and belongs to `structural` with its own weight. So the spine term is a BOOST over blocks
        the body scorer found, never a producer of new ones.

        **The head probe is not joined to `tmp_narrow` and the body probe is.** An ancestor heading
        is evidence about a candidate, not a candidate: a `Filters(layers={BODY})` query excludes
        heading blocks from the answer and must not thereby lose the spine term, which is six times
        the body weight. Narrowing bounds what is RETURNED (07:1585-1591), and only the body probe
        returns anything.

        **Over-fetch is already in `spec.limit`.** `plan()` computes `limit = q.k * overfetch`
        (07:3297 plus `LEX_OVERFETCH = 5`), so `k=20` arrives here as 100 and the re-rank sees five
        times what fusion will keep -- 07:1304: *"a re-ranker that only sees the base scorer's top-k
        cannot promote what the base scorer buried"*. This method does not multiply again.

        `spans` stays empty. 07:2291 sources it from *"FTS5 instance offsets at `detail='full'`"*,
        and those offsets are reachable only through the C `fts5_api` (`xInstCount` / `xInst`),
        which `sqlite3` does not surface -- there is no SQL function that returns them. D243. The
        rule that decides the behaviour is 07:2293's: a span *"is never invented when the Channel
        had no offset"*.
        """
        state = self._caps.fts_state
        if state != "ok":
            return ChannelOutcome(name=spec.name, status="unavailable", reason=f"fts_{state}")
        bind = spec.bind
        terms = () if bind is None else bind.terms
        match = _fts_match(terms)
        if not match:
            return ChannelOutcome(
                name=spec.name,
                status="empty",
                reason="no query term survived sanitisation, so there is nothing to match",
            )
        narrow_join = ""
        if n.kind == "set":
            narrow_join = f" JOIN {_TMP_NARROW} tn ON tn.block_id = f.rowid"
        cap = max(spec.limit, 1)
        rows = connection.execute(
            f"SELECT f.rowid, bm25(block_fts) FROM block_fts f "  # noqa: S608
            f"JOIN ow_block_head b ON b.block_id = f.rowid{narrow_join} "
            f"WHERE block_fts MATCH ? ORDER BY bm25(block_fts) LIMIT ?",
            (match, cap + 1),
        ).fetchall()
        if not rows:
            return ChannelOutcome(
                name=spec.name,
                status="empty",
                reason="no block's text carries any of the query terms",
            )
        truncated = len(rows) > cap
        body = _minmax({int(rowid): -float(score) for rowid, score in rows[:cap]})
        head = self._head_scores(connection, match, cap)
        chains = _spines(connection, sorted(body))
        lex = {
            block_id: W_BODY * body[block_id]
            + W_HEAD
            * max(
                (head.get(sec, 0.0) * SPINE_DECAY**depth for sec, depth in chains[block_id]),
                default=0.0,
            )
            for block_id in body
        }
        order = _reading_order(connection, sorted(lex))
        ranked = sorted(
            lex,
            key=lambda block_id: (-lex[block_id], order.get(block_id, (0, 0, 0)), block_id),
        )
        return ChannelOutcome(
            name=spec.name,
            status="ok",
            ranked=tuple(ranked),
            truncated_at_limit=truncated,
        )

    def _head_scores(
        self, connection: sqlite3.Connection, match: str, cap: int
    ) -> Mapping[int, float]:
        """`bm25n(head_fts, a)` for every labelled block the query reaches, normalised among them.

        Normalised within the HEAD result set and not within the body's: `lex(b)` adds two
        normalised quantities, so each has to be a rank within its own scale or `W_HEAD = 6.0` is
        multiplying a number whose units came from the other index. `block_fts` indexes `text` and
        `head_fts` indexes `label` (0003_index.sql:97-99) and their bm25 magnitudes are not
        comparable: a four-word label and a four-hundred-word paragraph differ by the length
        normalisation `columnsize=1` exists to supply.

        Bounded by the same `cap` as the body probe. The 101st-best heading of a query whose top
        100 bodies all sit under it would lose its boost -- a real, bounded recall cost, taken
        because the alternative is an unbounded scan of `head_fts` inside a 50 ms budget and
        because a heading that ranks below a hundred others is weak evidence by construction.
        """
        if not self._caps.has_head_fts:
            return {}
        rows = connection.execute(
            "SELECT f.rowid, bm25(head_fts) FROM head_fts f "
            "JOIN ow_block_head b ON b.block_id = f.rowid "
            "WHERE head_fts MATCH ? ORDER BY bm25(head_fts) LIMIT ?",
            (match, cap),
        ).fetchall()
        return _minmax({int(rowid): -float(score) for rowid, score in rows})

    @staticmethod
    def _read_vec_manifest(
        connection: sqlite3.Connection, corpus_id: str
    ) -> tuple[VecManifest | None, str]:
        """The sidecar's identity, or `None` plus the reason the semantic Channel will report.

        Three ways to get `None`, and they are three different facts a Verdict has to be able to
        tell apart:

        1. **Nothing attached.** The ordinary case, because 07:2596 makes
           `[retrieval] vectors = "off"` the shipped default permanently.
        2. **Attached and unreadable.** 07:1373-1376's `SQLITE_CORRUPT` / `SQLITE_NOTADB`, reported
           as `vec_unreadable` with `rm index.vec.owstore` as the documented fix (07:3189). Caught
           here as well as at the Channel because the manifest read is itself a sidecar read.
        3. **Attached, readable, belonging to another corpus.** 07:3190 and 07:790: *"`corpus_id`
           (!= `main.index_state.corpus_id` => THE SIDECAR IS IGNORED, not read)"*. Ignored is not
           an error and not a rebuild -- the vectors are derived and the store is authoritative --
           and absence gate 13 (`space_mismatch`) is what makes it visible.

        `ValueError` is caught beside `sqlite3.DatabaseError` because `vec_manifest` is a `(k, v)`
        TEXT table: a truncated write leaves a row whose `v` is not an integer, which is the same
        corruption arriving through `int()` instead of through the pager.

        The eleven fields are mapped by `store/vectors.py`'s `parse_manifest` and not here: that
        module writes the table and this one reads it, and two parsers of one `(k, v)` schema is
        the drift INV-21 forbids.
        """
        attached = any(str(row[1]) == "vec" for row in connection.execute("PRAGMA database_list"))
        if not attached:
            return None, "no vec sidecar is attached: [retrieval] vectors is off"
        try:
            rows = {
                str(k): str(v) for k, v in connection.execute("SELECT k, v FROM vec.vec_manifest")
            }
            found = rows.get("corpus_id", "")
            if found != corpus_id:
                return None, (
                    f"the vec sidecar carries corpus_id {found!r} and this store is "
                    f"{corpus_id!r}, so the sidecar is ignored and not read"
                )
            manifest = parse_manifest(rows)
        except (sqlite3.DatabaseError, ValueError):
            return None, _VEC_UNREADABLE
        return manifest, ""

    def _semantic(
        self, connection: sqlite3.Connection, spec: ChannelSpec, n: Narrowing
    ) -> ChannelOutcome:
        """07:1364-1376's Channel: a backend call, one join back, and a capped lift to blocks.

        **The embedding is not computed here and cannot be.** 07:1364-1366 puts it in phase 2,
        *"before the snapshot"*, with `query_prompt_digest` applied client-side, and ST22 is why:
        the query embedding is a Driver call, a Driver call inside a held read transaction pins the
        WAL, and a pinned WAL is the futility-latch condition. So `q_sig` arrives on
        `ChannelInput` and a Channel that finds it `None` reports that phase 2 did not run rather
        than running it late.

        **The join back is the only exit from the sidecar.** 07:1368-1372 prints the statement and
        calls it *"the **only** exit from the `vec` sidecar (ST4), which is what makes a stale
        vector invisible rather than wrong"*. `search()` returns segment CONTENT DIGESTS, never
        `segment_id`s, and this method resolves them against live segments inside the main
        snapshot; a backend that returned ids would make that join an identity and the staleness
        undetectable.

        **The table-synopsis rule is honoured by not doing something.** 07:1523-1525: *"a semantic
        hit whose segment is a table synopsis (`segment.synopsis_of IS NOT NULL`) lifts to the
        synopsis segment's own blocks and never to the 4M cells it summarises."* The lift reads
        `segment_block` for the hit segment and follows no `synopsis_of` edge, so the rule holds by
        construction -- which is worth saying, because the way to break it is to add a helpful join.

        **A store-level exception becomes a Channel status exactly here and nowhere else**
        (07:1373-1376). The catch is narrow -- `sqlite3.DatabaseError`, which is `SQLITE_CORRUPT`
        and `SQLITE_NOTADB`'s Python class -- and it returns `unavailable`, which forces
        `degraded`; an `except: return []` would make a corrupt sidecar a confident zero, which is
        ST8's whole subject and what `retrieve/`'s semgrep ban exists for.
        """
        ready = self._vec_ready(spec)
        if isinstance(ready, ChannelOutcome):
            return ready
        vectors, vec, q_sig = ready
        bind = spec.bind
        degradations: list[str] = []
        candidates: frozenset[bytes] | None = None
        if n.kind == "set" and vec.pushdown:
            candidates = self._candidate_digests(connection)
        elif n.kind == "set":
            degradations.append(_PUSHDOWN_UNAVAILABLE)
        over = 1 if candidates is not None else max(spec.overfetch, 1)
        try:
            hits = vectors.search(
                vec.model_key,
                q_sig,
                None if bind is None else bind.q_full,
                k=max(spec.limit, 1) * over,
                candidates=candidates,
            )
        except sqlite3.DatabaseError:
            return ChannelOutcome(name=spec.name, status="unavailable", reason=_VEC_UNREADABLE)
        if not hits:
            return ChannelOutcome(
                name=spec.name,
                status="empty",
                reason="the vector backend matched no segment",
            )
        live = self._live_segments(connection, [digest for digest, _score in hits])
        ranked, rank_of = self._lift(connection, hits, live, n, degradations)
        if not ranked:
            return ChannelOutcome(
                name=spec.name,
                status="empty",
                reason=(
                    "every segment the backend matched is retired, superseded or outside the "
                    "narrowed set"
                ),
            )
        truncated = spec.limit > 0 and len(ranked) > spec.limit
        if truncated:
            ranked = ranked[: spec.limit]
            rank_of = {block_id: rank_of[block_id] for block_id in ranked}
        return ChannelOutcome(
            name=spec.name,
            status="ok",
            ranked=tuple(ranked),
            rank_of=MappingProxyType(dict(rank_of)),
            degradations=tuple(degradations),
            truncated_at_limit=truncated,
        )

    def _vec_ready(
        self, spec: ChannelSpec
    ) -> tuple[VectorBackend, VecManifest, bytes] | ChannelOutcome:
        """The backend, its manifest and the query signature -- or the refusal that stops the
        Channel first.

        Three things can stop it and each names a different missing piece, because the three have
        three different fixes: select a backend, attach (or rebuild) the sidecar, or run phase 2.
        All three are `unavailable` and never `empty` -- `empty` says the backend ran and matched
        nothing, which is a claim about the corpus, and none of these three looked at it.

        Returning the three values it proved present, rather than a `None`, is what keeps
        `_semantic` from re-checking them: a refusal and the material that makes the Channel
        runnable are the same question asked once.
        """
        if self._vectors is None:
            return ChannelOutcome(
                name=spec.name,
                status="unavailable",
                reason="no VectorBackend was selected: [retrieval] vectors is off",
            )
        if self._vec is None:
            return ChannelOutcome(name=spec.name, status="unavailable", reason=self._vec_reason)
        if spec.bind is None or spec.bind.q_sig is None:
            return ChannelOutcome(
                name=spec.name,
                status="unavailable",
                reason=(
                    "the query carries no embedding: phase 2 embeds before the snapshot opens "
                    "(ST22) and it did not run"
                ),
            )
        return self._vectors, self._vec, spec.bind.q_sig

    @staticmethod
    def _candidate_digests(connection: sqlite3.Connection) -> frozenset[bytes]:
        """The live segment digests the narrowed set touches -- contract obligation (1)'s input.

        07:104-105: *"`candidates` narrows **before** ranking, tested at 0.01 selectivity"*. The
        set is computed here rather than by the backend because `tmp_narrow` is the Reader's TEMP
        table and the backend may not be SQLite at all; a digest is the only identifier the two
        sides share, which is the same property that makes the join back the sidecar's only exit.

        Only called when the narrowing is a `set`. A `kind="all"` narrowing is the PROOF that the
        candidate set could not be enumerated (07:1585-1591), so there is nothing to push and
        pushing `None` is the honest report -- not a `pushdown_unavailable`, which names the
        BACKEND's limitation and not the query's.
        """
        rows = connection.execute(
            f"SELECT DISTINCT s.content_digest FROM segment s "  # noqa: S608
            f"JOIN doc d ON d.doc_ord = s.doc_ord "
            f"JOIN segment_block sb ON sb.segment_id = s.segment_id "
            f"JOIN {_TMP_NARROW} tn ON tn.block_id = sb.block_id "
            f"WHERE s.gen = d.gen AND s.state = 0"
        )
        return frozenset(bytes(row[0]) for row in rows)

    @staticmethod
    def _live_segments(
        connection: sqlite3.Connection, digests: Sequence[bytes]
    ) -> Mapping[bytes, int]:
        """07:1368-1370's statement, transcribed, batched at `_ID_BATCH`.

        ```sql
        SELECT s.segment_id, s.content_digest FROM segment s JOIN doc d USING (doc_ord)
         WHERE s.content_digest IN (...) AND s.gen = d.gen AND s.state = 0;
        ```

        A digest the backend returned and this statement does not is a STALE vector: the segment it
        described has been retired or superseded since the sidecar was built. It is dropped
        silently and the ranks close up behind it, which is 07:1372's *"makes a stale vector
        invisible rather than wrong"* -- the sidecar is derived, so a row it holds that the store
        does not is the sidecar being out of date and never the store being incomplete.
        """
        found: dict[bytes, int] = {}
        for start in range(0, len(digests), _ID_BATCH):
            chunk = list(digests[start : start + _ID_BATCH])
            rows = connection.execute(
                f"SELECT s.content_digest, s.segment_id FROM segment s "  # noqa: S608
                f"JOIN doc d ON d.doc_ord = s.doc_ord "
                f"WHERE s.content_digest IN ({_placeholders(len(chunk))}) "
                f"AND s.gen = d.gen AND s.state = 0",
                chunk,
            )
            for digest, segment_id in rows:
                found[bytes(digest)] = int(segment_id)
        return found

    @staticmethod
    def _lift(
        connection: sqlite3.Connection,
        hits: Sequence[tuple[bytes, float]],
        live: Mapping[bytes, int],
        n: Narrowing,
        degradations: list[str],
    ) -> tuple[list[int], dict[int, int]]:
        """07:1509-1517's lift: a segment at rank *r* yields its member blocks AT RANK *r*.

        The rank is 1-based and counted over the segments that SURVIVED the live join, so a stale
        digest costs its successors nothing -- rank 2 means "the second segment this store still
        holds", which is the number `fuse()` divides by.

        `SEM_BLOCKS_PER_SEGMENT = 64` with `MAX_SEGMENT_BLOCKS = 512` means *"the cap **can bite
        for up to 448 blocks** of a large segment"*, so the selection rule is named and
        deterministic: *"the first 64 members in `segment_block.ord` order -- which is `(page,
        ord)` by construction -- and a truncated lift sets `Degradation(kind=
        "segment_lift_capped", parts_affected=...)"*.

        **The cap is applied AFTER the narrowing join, not before.** 07:1561 makes narrowing prior
        to every Channel -- filters narrow, Channels score within the narrowed set -- and a cap
        applied first would let a filter that happens to exclude members 1 to 64 turn a ranked
        segment into zero blocks, which is a silent absence with a confident rank attached to it.
        On an unfiltered query the two readings coincide, which is the case 07:1519's 87% figure is
        computed over.

        `segment_block.block_id` is a PRIMARY KEY, which 0002_graph.sql:165 calls exactly one
        segment per block with overlap unrepresentable -- so no block can arrive twice and
        `ranked` is duplicate-free by the schema rather than by a check here.
        """
        narrow_join = ""
        if n.kind == "set":
            narrow_join = f" JOIN {_TMP_NARROW} tn ON tn.block_id = sb.block_id"
        ranked: list[int] = []
        rank_of: dict[int, int] = {}
        rank = 0
        for digest, _score in hits:
            segment_id = live.get(digest)
            if segment_id is None:
                continue
            rank += 1
            members = [
                int(row[0])
                for row in connection.execute(
                    f"SELECT sb.block_id FROM segment_block sb "  # noqa: S608
                    f"JOIN ow_block_head b ON b.block_id = sb.block_id{narrow_join} "
                    f"WHERE sb.segment_id = ? ORDER BY sb.ord LIMIT ?",
                    (segment_id, SEM_BLOCKS_PER_SEGMENT + 1),
                )
            ]
            if len(members) > SEM_BLOCKS_PER_SEGMENT:
                members = members[:SEM_BLOCKS_PER_SEGMENT]
                if _SEGMENT_LIFT_CAPPED not in degradations:
                    degradations.append(_SEGMENT_LIFT_CAPPED)
            for block_id in members:
                if block_id in rank_of:
                    continue
                ranked.append(block_id)
                rank_of[block_id] = rank
        return ranked, rank_of

    def _structural(
        self, connection: sqlite3.Connection, spec: ChannelSpec, n: Narrowing
    ) -> ChannelOutcome:
        """07:1327-1362's bounded frontier BFS over `block_link`. Four ceilings, none optional.

        07:1352-1356: *"A Python frontier BFS over batched `WHERE src_block IN (...)`, with an
        explicit visited set, cancellable at the top of each hop, joining `tmp_narrow`. **Not** a
        recursive CTE: SQLite has no built-in visited set and no per-hop fan-out bound, so a
        recursive CTE over a cyclic reference graph is unbounded by construction."* Every clause
        of that sentence is a line below, and the ceilings compose: `max_hops` bounds the loop,
        `beam` bounds each hop's fan-out, `max_visited` bounds the whole traversal, and `hub_cap`
        bounds any one block's contribution.

        **The forward hop only.** `block_link_out(src_block, relation)` is the index this statement
        uses and 07:984 gives `block_link_in` a different job -- *"`Expand` reverse hop;
        back-references"* -- which §7.4 spends on `ow open`, outside `retrieve()`. A Channel that
        walked both directions would double the fan-out at every hop against caps chosen for one.

        **`edge` is not traversed.** 07:1337-1339: *"not traversed by this Channel at v1; it is
        reachable only through the `@provisional` `GraphView.neighbours()`, outside `retrieve()`"*,
        and 16-roadmap.md W8.9 is the scheduled work that adds the L3 half.

        **Over its OWN `budget_ms` this returns `UNAVAILABLE(timeout)` and discards what it had.**
        That is W6.1's two-deadline split seen from inside a Channel: 07:1817 gives the Channel
        budget `UNAVAILABLE(timeout)` and forces `degraded`, while the QUERY deadline is the other
        case entirely -- `OK` with `truncated_at_limit`. Returning a partial ranking here would
        merge the two cases into one and absence gate 1, which reads `reason == "timeout"` and
        nothing else (07:1221), would have nothing to read. `structural` is also the first Channel
        that can honour 07:1804's rule at all: *"`structural` at the top of each hop"* is a
        cancellation point between statements, and the other three are single statements that
        `interrupt()` could only abort by taking the whole transaction with them.
        """
        bind = spec.bind
        expand = None if bind is None else bind.expand
        if expand is None:
            return ChannelOutcome(
                name=spec.name,
                status="unavailable",
                reason="no Expand was bound, so nothing says which relations to traverse",
            )
        self._check_relations(connection, expand.relations)
        seeds = self._seed(
            connection,
            () if bind is None else bind.seeds,
            n,
            max_visited=expand.max_visited,
        )
        if seeds is None:
            return ChannelOutcome(
                name=spec.name,
                status="unavailable",
                reason=(
                    "no Channel preceded this one and the narrowing proved only that the "
                    "candidate set is too big to enumerate, so the traversal has no bounded "
                    "place to start"
                ),
            )
        if not seeds:
            return ChannelOutcome(
                name=spec.name,
                status="empty",
                reason="the seed set is empty, so the frontier is empty before hop 1",
            )

        walk = self._traverse(connection, spec, n, expand, seeds)
        if walk is None:
            return ChannelOutcome(name=spec.name, status="unavailable", reason=_TIMEOUT)
        reached, degradations, truncated = walk
        if not reached:
            return ChannelOutcome(
                name=spec.name,
                status="empty",
                reason="no block_link row reaches the narrowed set from the seed",
            )
        order = _reading_order(connection, sorted(reached))
        ranked = sorted(
            reached,
            key=lambda block_id: (
                -reached[block_id],
                order.get(block_id, (0, 0, 0)),
                block_id,
            ),
        )
        if spec.limit > 0 and len(ranked) > spec.limit:
            ranked, truncated = ranked[: spec.limit], True
        return ChannelOutcome(
            name=spec.name,
            status="ok",
            ranked=tuple(ranked),
            degradations=tuple(degradations),
            truncated_at_limit=truncated,
        )

    def _traverse(
        self,
        connection: sqlite3.Connection,
        spec: ChannelSpec,
        n: Narrowing,
        expand: Expand,
        seeds: tuple[int, ...],
    ) -> tuple[dict[int, float], list[str], bool] | None:
        """The hop loop itself. `None` means this Channel spent its own `budget_ms`.

        Returns `(reached, degradations, truncated)`. `truncated` is `True` when a CEILING cut the
        frontier -- the per-hop `beam` or `max_visited` -- and not only when `spec.limit` cut the
        output, because `truncated_at_limit` means the shortfall was the plan's and not the
        corpus's, and a beam cut is exactly that. `max_hops` running out does NOT set it: a
        two-hop `Expand` that stops at two hops got what it asked for.

        The four ceilings are checked in the order that makes each one cheap. `max_visited` and an
        empty frontier end the loop before a statement runs; the budget is checked next, at
        07:1804's *"top of each hop"*; `hub_cap` is inside `_reach`, where the row group is; and
        `beam` is applied after the hop, because a beam is a choice among what was found and
        pushing it into the SQL would make it a per-SOURCE limit instead of a per-HOP one.

        **`visited` bounds what is EXPANDED; it does not bound what is RANKED.** The two are
        different questions and conflating them loses a result the plan's own transcript requires:
        07:1892-1896 seeds the traversal from `tmp_narrow` itself and reports 311 ranked blocks,
        every one of which is inside `tmp_narrow` and therefore already a seed. So a block reached
        from another block ranks even when it was a seed, while the frontier only ever carries
        blocks that have not been expanded before -- which is what makes a cyclic reference graph
        terminate. `reached` is bounded by `max_hops x beam` because the beam is applied before
        the recording, so the two bounds compose rather than one leaking past the other.
        """
        started = self._monotonic_ns()
        budget_ns = max(spec.budget_ms, 0) * 1_000_000
        narrow_join = ""
        if n.kind == "set":
            narrow_join = f" JOIN {_TMP_NARROW} tn ON tn.block_id = l.dst_block"
        relations = sorted(expand.relations)
        visited = set(seeds)
        reached: dict[int, float] = {}
        degradations: list[str] = []
        frontier: list[int] = list(seeds)
        truncated = False
        for _hop in range(min(expand.max_hops, _EXPAND_MAX_HOPS)):
            if not frontier or len(visited) >= expand.max_visited:
                break
            if budget_ns and self._monotonic_ns() - started >= budget_ns:
                return None
            fresh = self._reach(
                connection,
                frontier,
                relations=relations,
                min_trust=int(expand.min_trust),
                narrow_join=narrow_join,
                hub_cap=expand.hub_cap,
                degradations=degradations,
            )
            if not fresh:
                break
            ordered = sorted(fresh, key=lambda block_id: (-fresh[block_id], block_id))
            if len(ordered) > expand.beam:
                ordered, truncated = ordered[: expand.beam], True
            for block_id in ordered:
                if block_id not in reached or fresh[block_id] > reached[block_id]:
                    reached[block_id] = fresh[block_id]
            frontier = [block_id for block_id in ordered if block_id not in visited]
            room = expand.max_visited - len(visited)
            if len(frontier) > room:
                frontier, truncated = frontier[:room], True
            visited.update(frontier)
        return reached, degradations, truncated

    @staticmethod
    def _check_relations(connection: sqlite3.Connection, relations: frozenset[str]) -> None:
        """Both halves of 07:1360-1362, as two usage errors rather than two silent traversals.

        *"`relations` has no default because 'all relations' on a document graph reaches every
        block in the corpus within three hops; a relation not present in `relation_vocab` is a
        usage error naming the vocabulary, because silently traversing nothing is indistinguishable
        from a corpus with no links."*

        The second half is the one that would otherwise be invisible. A misspelled relation makes
        the `IN (...)` list match nothing, the Channel reports `EMPTY`, absence gate 2 does not
        fire because `EMPTY` is not `UNAVAILABLE`, and the Verdict says the corpus has no links --
        which it may be full of. `relation_vocab` is an OPEN vocabulary (0003_index.sql:302) whose
        rows a driver may add, so the check is a read of the table and never a frozen tuple here.
        """
        if not relations:
            msg = (
                "Expand.relations is empty and the field has no default: 'all relations' on a "
                "document graph reaches every block in the corpus within three hops (07:1360)"
            )
            raise UsageError(msg, fix="name the relations to traverse, e.g. {'refers_to'}")
        known = {str(row[0]) for row in connection.execute("SELECT relation FROM relation_vocab")}
        unknown = sorted(set(relations) - known)
        if unknown:
            msg = (
                f"{unknown} are not in this store's relation_vocab, which holds {sorted(known)}: "
                f"silently traversing nothing is indistinguishable from a corpus with no links "
                f"(07:1361)"
            )
            raise UsageError(msg, fix="name a relation this store's relation_vocab carries")

    @staticmethod
    def _seed(
        connection: sqlite3.Connection,
        seeds: tuple[int, ...],
        n: Narrowing,
        *,
        max_visited: int,
    ) -> tuple[int, ...] | None:
        """The last rung of 07:1327-1332's seed ladder, and `None` when even that is unavailable.

        The first three rungs -- `identity` u `exact`, then whichever scoring Channels precede this
        one in the plan -- are `retrieve()`'s to choose, because only it has the other Channels'
        output; they arrive in `ChannelInput.seeds` (D246). This method owns the fourth, *"when no
        scoring Channel precedes it, from `tmp_narrow` itself"*, and the one case the ladder does
        not cover: a `Narrowing` of `kind="all"` has no `tmp_narrow` to read, because it is the
        PROOF that the candidate set was too big to enumerate (07:1585-1591). Seeding a traversal
        from a set that could not be listed is the unbounded traversal `Expand` exists to prevent,
        so the answer is `None` and the Channel reports `unavailable` -- a statement about this
        query's shape, never about the corpus.

        The `tmp_narrow` read is bounded by `max_visited` and ordered by `(doc_ord, page, ord)`.
        Bounded, because a seed the traversal could never visit is work with no possible effect on
        the result; ordered by reading order, because the bound decides WHICH blocks seed and
        `block_id` order would make that decision by ingest time.
        """
        if seeds:
            return tuple(dict.fromkeys(int(block_id) for block_id in seeds))
        if n.kind != "set":
            return None
        rows = connection.execute(
            f"SELECT tn.block_id FROM {_TMP_NARROW} tn "  # noqa: S608
            f"JOIN ow_block_head b ON b.block_id = tn.block_id "
            f"ORDER BY b.doc_ord, b.page, b.ord, b.block_id LIMIT ?",
            (max(max_visited, 1),),
        ).fetchall()
        return tuple(int(row[0]) for row in rows)

    @staticmethod
    def _reach(
        connection: sqlite3.Connection,
        frontier: Sequence[int],
        *,
        relations: Sequence[str],
        min_trust: int,
        narrow_join: str,
        hub_cap: int,
        degradations: list[str],
    ) -> dict[int, float]:
        """One hop: `{neighbour: (weight x trust) / log1p(degree)}`, batched, unfiltered.

        Every destination the allowlist, `min_trust`, the head generation and `tmp_narrow` admit,
        including ones the traversal has already visited -- the caller decides which of those may
        be expanded again and which may be ranked, and those are two different decisions (see
        `_traverse`).

        **`degree` is the SOURCE block's eligible out-degree**, and the reason is in the statement
        rather than in the formula. 07:1894 and 18:2834 give the ordering as
        `(weight x trust) / log1p(degree)` without saying whose degree, and the two readings are
        both defensible in the abstract -- the source's is PageRank's out-degree division, the
        destination's is an IDF-shaped penalty on a block everything points at. What decides it
        here is that the source's degree is ALREADY IN HAND: it is the size of this row group, so
        the hop stays *"batched `WHERE src_block IN (...)`"* (07:1352), one statement, while the
        destination's degree needs a second statement per hop against a 40 ms budget. It is also
        the same count `hub_cap` compares against one line below, so "hub" means one thing in both
        places rather than two. D249.

        **Eligible, not total.** The degree counted is the neighbours this hop could actually
        contribute -- after the relation allowlist, `min_trust`, the head-generation join and
        `tmp_narrow` -- because that is exactly what 07:1349 caps: *"a block with more links
        contributes at most `hub_cap` neighbours"*.

        **`hub_cap` truncates by weight, deterministically.** 07:1350 says *"sampled by weight"*;
        the statement is ordered by `weight DESC, dst_block`, so the kept subset is the top
        `hub_cap` and a re-run of the same query over the same store returns the same set. A
        weighted RANDOM sample would satisfy the word "sampled" and break ST7, which is the
        property the whole store is arranged around.
        """
        fresh: dict[int, float] = {}
        for start in range(0, len(frontier), _ID_BATCH):
            chunk = list(frontier[start : start + _ID_BATCH])
            rows = connection.execute(
                f"SELECT l.src_block, l.dst_block, l.weight, l.trust "  # noqa: S608
                f"FROM block_link l "
                f"JOIN ow_block_head b ON b.block_id = l.dst_block{narrow_join} "
                f"WHERE l.src_block IN ({_placeholders(len(chunk))}) "
                f"AND l.relation IN ({_placeholders(len(relations))}) AND l.trust >= ? "
                f"ORDER BY l.src_block, l.weight DESC, l.dst_block",
                (*chunk, *relations, min_trust),
            ).fetchall()
            for _src, group in groupby(rows, key=lambda row: row[0]):
                edges = [(int(dst), float(weight), int(trust)) for _s, dst, weight, trust in group]
                degree = len(edges)
                if degree > hub_cap:
                    edges = edges[:hub_cap]
                    if _HUB_CAPPED not in degradations:
                        degradations.append(_HUB_CAPPED)
                penalty = math.log1p(degree)
                for dst, weight, trust in edges:
                    score = weight * trust / penalty
                    if dst not in fresh or score > fresh[dst]:
                        fresh[dst] = score
        return fresh

    def _exact(
        self, connection: sqlite3.Connection, spec: ChannelSpec, n: Narrowing
    ) -> ChannelOutcome:
        """07:1273-1281's one statement over ALL lifted refs, over the narrowed set.

        *"The refs go into a TEMP table `tmp_refs`, not into N statements. `MAX_QUERY_REFS = 16`
        bounds it anyway, but the one-statement form is what keeps a 16-ref query at one plan
        instead of sixteen, and it is what makes the `exact` Channel's `ran_ms` a single measurable
        number."* (07:1283-1285.)

        The ranking is 07:1271-1272's prose rather than the printed `ORDER BY tier, block_id` --
        see DEFECT 5. `tier` is definitions (`anchor`, 0) before occurrences (`ref_site`, 1);
        `scope_rank` is corpus (0) before document (1); then `(doc_ord, page, ord)`, which is
        reading order, with `block_id` last so the order is total and therefore deterministic
        (07:1228).

        Both branches read through `ow_block_head`, the head-generation projection
        (0001_init.sql:328-330). `ref_site` carries no `gen` column of its own, so without that
        join a retired generation's occurrence would rank -- the same failure `ref_unresolved`'s
        `n.gen = dd.gen` predicate closes on the anchor side (0003_index.sql:250-252).

        `spans` carries `ref_site`'s `(ts_a, ts_b)` as a `TextSpan`, which is exactly what
        `ChannelResult.spans` is for -- *"sub-block addressing"* (07:1229), and 07:2287-2290 names
        *"a `ref_site` `(ts_a, ts_b)` pair"* as one of its two sources. An `anchor` row has no span
        and contributes none; a span is *"never invented when the Channel had no offset"*.
        """
        bind = spec.bind
        refs = () if bind is None else bind.refs
        if not refs:
            return ChannelOutcome(
                name=spec.name,
                status="empty",
                reason="no reference-shaped tokens were lifted out of the query",
            )
        if len(refs) > MAX_QUERY_REFS:
            msg = (
                f"{len(refs)} refs were bound to the exact Channel and MAX_QUERY_REFS is "
                f"{MAX_QUERY_REFS}; the ceiling is what keeps the Channel at one statement"
            )
            raise UsageError(msg, fix="lift fewer refs out of the query")

        connection.execute(
            f"CREATE TEMP TABLE IF NOT EXISTS {_TMP_REFS}"
            f"(name_norm TEXT NOT NULL, akind TEXT NOT NULL, PRIMARY KEY (name_norm, akind)) "
            f"WITHOUT ROWID"
        )
        connection.execute(f"DELETE FROM {_TMP_REFS}")  # noqa: S608
        connection.executemany(
            f"INSERT OR IGNORE INTO {_TMP_REFS}(name_norm, akind) VALUES (?, ?)",  # noqa: S608
            [(str(name), str(akind)) for name, akind in refs],
        )

        narrow_join = ""
        if n.kind == "set":
            narrow_join = f" JOIN {_TMP_NARROW} tn ON tn.block_id = b.block_id"
        scope_doc = None if bind is None else bind.scope_doc
        rows = connection.execute(
            "SELECT block_id, ts_a, ts_b FROM ("  # noqa: S608
            "  SELECT b.block_id AS block_id, 0 AS tier,"
            "         CASE a.scope WHEN 'corpus' THEN 0 ELSE 1 END AS scope_rank,"
            "         NULL AS ts_a, NULL AS ts_b, b.doc_ord AS doc_ord, b.page AS page,"
            "         b.ord AS ord"
            "    FROM anchor a"
            "    JOIN doc dd ON dd.doc_ord = a.doc_ord AND a.gen = dd.gen"
            f"    JOIN {_TMP_REFS} r ON r.name_norm = a.name_norm AND r.akind = a.akind"
            f"    JOIN ow_block_head b ON b.block_id = a.block_id{narrow_join}"
            "   WHERE a.scope = 'corpus' OR a.doc_ord = ?"
            "  UNION ALL"
            "  SELECT b.block_id, 1,"
            "         CASE s.scope WHEN 'corpus' THEN 0 ELSE 1 END,"
            "         s.ts_a, s.ts_b, b.doc_ord, b.page, b.ord"
            "    FROM ref_site s"
            f"    JOIN {_TMP_REFS} r ON r.name_norm = s.name_norm AND r.akind = s.akind"
            f"    JOIN ow_block_head b ON b.block_id = s.block_id{narrow_join}"
            ") ORDER BY tier, scope_rank, doc_ord, page, ord, block_id",
            (scope_doc,),
        ).fetchall()

        ranked: list[int] = []
        spans: dict[int, TextSpan] = {}
        seen: set[int] = set()
        for block_id, ts_a, ts_b in rows:
            key = int(block_id)
            if key in seen:
                continue
            seen.add(key)
            ranked.append(key)
            if ts_a is not None and ts_b is not None:
                spans[key] = TextSpan(int(ts_a), int(ts_b))

        truncated = spec.limit > 0 and len(ranked) > spec.limit
        if truncated:
            ranked = ranked[: spec.limit]
            spans = {b: span for b, span in spans.items() if b in set(ranked)}
        if not ranked:
            return ChannelOutcome(
                name=spec.name,
                status="empty",
                reason="no anchor or ref_site row carries any of the bound refs",
            )
        return ChannelOutcome(
            name=spec.name,
            status="ok",
            ranked=tuple(ranked),
            spans=MappingProxyType(dict(spans)),
            truncated_at_limit=truncated,
        )

    # -- 5. hydrate --------------------------------------------------------

    def hydrate(self, s: Snapshot, ids: Sequence[int]) -> Hydration:
        """07:2312-2321's statement, batched at 512, INSIDE the caller's `Snapshot`.

        The statement is transcribed as printed, including the two columns that are not `Hit`
        fields (`b.method` and `length(b.text)`) and `d.achieved`, which *"rides along because
        `byte_exact` is computed from it and re-querying `doc` per hit would be N+1"* (07:2322).

        **The `gen`/`state` predicate is in the statement and its misses are counted**
        (07:2323-2324): a row that fails it is dropped, and a non-zero drop count means the store
        advanced mid-query. `Hydration.dropped` carries it.

        **Rows come back in the CALLER's id order.** The ids are a fused ranking; SQL returns an
        `IN (...)` result in whatever order the query plan produces, and re-sorting to the request
        is what stops the ranking being silently replaced by `block_id` order. Duplicate ids
        collapse to one row and are counted once, because hydrating one block twice would put it
        in the Answer twice.

        Being inside the caller's snapshot is the whole point: 07:2334-2340 says reading `b.text`
        here rather than after the transaction closes is *"the whole reason `Hit.text` exists"*,
        since a re-index committed in between would hand the renderer text from a different
        generation than the one that was ranked.
        """
        connection = self._bound(s)
        wanted: list[int] = []
        seen: set[int] = set()
        for raw in ids:
            block_id = int(raw)
            if block_id not in seen:
                seen.add(block_id)
                wanted.append(block_id)
        if not wanted:
            return Hydration((), dropped=0)

        found: dict[int, HydratedRow] = {}
        for start in range(0, len(wanted), _HYDRATE_BATCH):
            batch = wanted[start : start + _HYDRATE_BATCH]
            rows = connection.execute(
                "SELECT b.block_id, b.cite, b.addr, b.page, b.kind, b.layer, b.text, b.trust, "  # noqa: S608
                "       b.quote, b.restriction_bits, b.os_kind, b.os_part, sb.segment_id, "
                "       b.method, length(b.text) AS chars, d.uri, d.achieved "
                "  FROM block b "
                "  JOIN doc d USING (doc_ord) "
                "  LEFT JOIN segment_block sb ON sb.block_id = b.block_id "
                f" WHERE b.block_id IN ({_placeholders(len(batch))}) "
                "   AND b.state = 0 AND b.gen = d.gen",
                tuple(batch),
            ).fetchall()
            for row in rows:
                found[int(row[0])] = self._hydrated_row(row)

        ordered = tuple(found[block_id] for block_id in wanted if block_id in found)
        return Hydration(ordered, dropped=len(wanted) - len(ordered))

    def _hydrated_row(self, row: Sequence[object]) -> HydratedRow:
        """One SELECT row, with its four `enum_val` codes decoded back to members."""
        return HydratedRow(
            block_id=int(row[0]),  # type: ignore[call-overload]
            cite=str(row[1]),
            addr=str(row[2]),
            page=int(row[3]),  # type: ignore[call-overload]
            kind=Kind(self._member(self._kinds, int(row[4]), "kind")),  # type: ignore[call-overload]
            layer=Layer(self._member(self._layers, int(row[5]), "layer")),  # type: ignore[call-overload]
            text=None if row[6] is None else str(row[6]),
            trust=Trust(int(row[7])),  # type: ignore[call-overload]
            quote=Quote(int(row[8])),  # type: ignore[call-overload]
            restriction_bits=int(row[9]),  # type: ignore[call-overload]
            os_kind=OsKind(self._member(self._os_kinds, int(row[10]), "origin_span_kind")),  # type: ignore[call-overload]
            os_part=None if row[11] is None else str(row[11]),
            segment_id=None if row[12] is None else int(row[12]),  # type: ignore[call-overload]
            method=Method(self._member(self._methods, int(row[13]), "method")),  # type: ignore[call-overload]
            chars=None if row[14] is None else int(row[14]),  # type: ignore[call-overload]
            uri=str(row[15]),
            achieved=str(row[16]),
        )

    @staticmethod
    def _member(domain: Mapping[str, int], code: int, name: str) -> str:
        """The `enum_val` member name for `code`, refusing a code the store cannot explain.

        The reverse of `_codes`, and refused for the same reason: a stored code with no `enum_val`
        row means the seed and the rows disagree, and guessing a member would put a wrong `Kind` or
        `Method` on a Block that then reaches an Answer.
        """
        for member, ord_ in domain.items():
            if ord_ == code:
                return member
        msg = (
            f"this store holds {name} code {code}, which its own enum_val does not name: the "
            f"seed and the rows disagree, and a guessed member would reach an Answer"
        )
        raise StoreError(msg, fix="ow store verify")

    # -- 6. coverage -------------------------------------------------------

    def coverage(self, s: Snapshot, f: Filters) -> Coverage:
        """The counts absence gates 4-9 read (07:3332), and `scope_rows == 0` is the important one.

        07:695: *"AN ABSENT ROW MEANS 'COVERAGE UNKNOWN', NEVER 'NOTHING WAS EXCLUDED'."* So a
        store with no `ingest_scope` row returns `scope_rows=0` and `complete=False`, which is gate
        4 firing (07:2184) rather than a clean bill of health -- and reporting `complete=True` over
        zero rows, which a vacuous `all()` would do, is exactly the confident zero the field
        exists to prevent.

        **Which scope rows are in view** is 07:706-708: *"A query whose `Filters` name no document
        scope reads **every** scope row; a query scoped to documents reads the scope rows
        containing them."* The containment test is the plan's own, `doc.uri GLOB scope_id || '*'`
        (07:704), *"evaluated over `doc` (thousands of rows, not millions, so an unindexed scan is
        the right implementation)"*, and it carries `NO_JOB_DOCS` because 07:757 lists gate 4's
        scope roll-up among that predicate's sites.

        The two `Filters` fields that constitute a DOCUMENT SCOPE are `doc_keys` and `uri_prefix`
        -- the two that name documents by identity or by location, which is what a `scope_id` URI
        prefix can contain. `formats`, `kinds`, `layers` and the rest narrow WITHIN documents and
        do not locate them, so they leave the scope roll-up alone; ruling recorded because the plan
        says "name no document scope" without enumerating the fields.

        **`pending_work`, `stale_units` and `unreadable_units` restrict by `uri_prefix` only**, and
        the reason is a schema fact rather than a choice: `work` joins `unit` by `unit_uri` and
        there is no `doc` -> `unit` key anywhere in the four migrations, so `doc_keys` cannot reach
        them. P2 creates both tables and leaves them empty (16-roadmap.md:406), so the restriction
        is exercised and not yet load-bearing; recorded so P4 does not read the absence as a
        decision.

        `unreadable_units` counts `unit.state = 'failed'`. 07:2229 gives the case gate 8 exists for
        -- *"a unit whose path is removed after `ingest_scope` was written"* -- which is an acquire
        that failed, and `failed` is the `unit.state` member that records it (0004_runtime.sql:50).
        `stale_units` counts `unit.stale_since IS NOT NULL`, which is the column the partial index
        `unit_stale` exists to serve.
        """
        connection = self._bound(s)
        doc_where, doc_params = self._doc_scope(f)

        scope_sql = (
            "SELECT discovered, indexed, skipped, complete FROM ingest_scope"
            if doc_where is None
            else "SELECT discovered, indexed, skipped, complete FROM ingest_scope AS sc "  # noqa: S608
            " WHERE EXISTS (SELECT 1 FROM doc"
            f"   WHERE {doc_where} AND {_NO_JOB_DOCS}"
            "     AND doc.uri GLOB sc.scope_id || '*')"
        )
        scope_rows = connection.execute(scope_sql, tuple(doc_params)).fetchall()

        discovered = sum(int(row[0]) for row in scope_rows)
        indexed = sum(int(row[1]) for row in scope_rows)
        skipped = sum(int(row[2]) for row in scope_rows)
        complete = bool(scope_rows) and all(int(row[3]) != 0 for row in scope_rows)

        status_where = _NO_JOB_DOCS if doc_where is None else f"{doc_where} AND {_NO_JOB_DOCS}"
        by_status = {
            str(status): int(count)
            for status, count in connection.execute(
                f"SELECT status, count(*) FROM doc WHERE {status_where} GROUP BY status",  # noqa: S608
                tuple(doc_params),
            )
        }

        unit_where, unit_params = self._unit_scope(f)
        pending_work = _one_int(
            connection,
            "SELECT count(*) FROM work JOIN unit USING (unit_uri) "  # noqa: S608
            f"WHERE work.status IN ({_placeholders(len(_LIVE_STATES))}) AND {unit_where}",
            (*_LIVE_STATES, *unit_params),
        )
        stale_units = _one_int(
            connection,
            f"SELECT count(*) FROM unit WHERE stale_since IS NOT NULL AND {unit_where}",  # noqa: S608
            unit_params,
        )
        unreadable_units = _one_int(
            connection,
            f"SELECT count(*) FROM unit WHERE state = 'failed' AND {unit_where}",  # noqa: S608
            unit_params,
        )

        return Coverage(
            discovered=discovered,
            indexed=indexed,
            partial=by_status.get("partial", 0),
            failed=by_status.get("failed", 0),
            skipped=skipped,
            complete=complete,
            scope_rows=len(scope_rows),
            pending_work=pending_work,
            stale_units=stale_units,
            unreadable_units=unreadable_units,
            gaps=(),
        )

    @staticmethod
    def _doc_scope(f: Filters) -> tuple[str | None, list[object]]:
        """The `doc`-level predicate of a `Filters` DOCUMENT SCOPE, or `None` for no scope."""
        clauses: list[str] = []
        params: list[object] = []
        if f.doc_keys is not None:
            if not f.doc_keys:
                return "1 = 0", []
            clauses.append(f"doc.doc_key IN ({_placeholders(len(f.doc_keys))})")
            params.extend(sorted(f.doc_keys))
        if f.uri_prefix is not None:
            low, high = _prefix_bounds(f.uri_prefix)
            clauses.append("doc.uri >= ? AND doc.uri < ?")
            params.extend((low, high))
        if not clauses:
            return None, []
        return " AND ".join(clauses), params

    @staticmethod
    def _unit_scope(f: Filters) -> tuple[str, list[object]]:
        """The `unit`-level predicate, which only `uri_prefix` can express. See `coverage`."""
        if f.uri_prefix is None:
            return "1 = 1", []
        low, high = _prefix_bounds(f.uri_prefix)
        return "unit.unit_uri >= ? AND unit.unit_uri < ?", [low, high]
