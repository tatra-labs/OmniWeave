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
4. **`channel` -- `exact` ONLY.** `identity`, `lexical`, `structural` and `semantic` report
   `off` / `not_built`. The per-Channel argument is below.
5. **`hydrate` -- THE ROW, all of it.** It cannot return `Hit`: four of `Hit`'s fourteen fields
   (`score`, `channel_contributions`, `channel_ranks`, `identity_grade`) are fusion outputs
   (07:2250-2265), and 07:3348 homes `Hit` with the query path. It returns `Hydration`, a
   `Sequence` of the SELECT's own rows -- see that class.
6. **`coverage` -- THE COUNTS.** `gaps` is `tuple[DegradeCause, ...]` and `DegradeCause` is
   07:1989's, with the gate ladder 16-roadmap.md:468 excludes from P2, so `gaps=()`. Every count
   is a real read, including the three over `work` and `unit`, which P2 creates and leaves empty
   (16-roadmap.md:406).

**Why `channel` refuses four of five, and why it refuses with a STATUS rather than an exception.**
07:1198-1199 gives the vocabulary (`ChannelStatus` = `ok | empty | off | unavailable`) and
07:2236-2240 closes the `off` reasons at four members, of which `NOT_BUILT="not_built"` is
*"the P-stage has not shipped it"*. 16-roadmap.md:114 uses exactly that pair for exactly this
situation -- *"The `structural` and `semantic` channels return `ChannelStatus.OFF` with
`reason = "not_built"`, which the Answer discloses in its verdict line"*. A `NotImplementedError`
would make the limitation an outage; an empty `ok` would make it a confident zero, which is ST8's
and 07:1670-1680's whole subject. `off` is disclosed and contributes nothing to the ceiling
(07:1218-1222), which is the honest arithmetic.

* **`identity` -- refused, and the reason is the 40 tier.** 07:1269 fixes the resolution as
  *"`block_cite` / `block_addr` / `doc(uri)` index lookups **plus a `head_fts` title probe**"*, and
  no user string reaches FTS5 unsanitised (07:1284-1292, *"a user cannot inject FTS5 syntax"*) --
  a sanitiser 16-roadmap.md:468 excludes from P2 by name. The tempting move is to ship the five
  index-lookup tiers and skip the two title tiers, and 07:1264-1268 forbids precisely that:
  *"The **40 tier** is the first thing a 'simplification' deletes and it must not be ...
  Collapsing 40 into 50 lets a punctuation-different match TIE a literal one and fall through to
  BM25."* A truncated ladder is a recall loss that presents as a confident match, so the ladder is
  all-or-nothing and P2 has none of it.
* **`exact` -- implemented, and it is the exception the edge needed.** It needs no scorer and no
  sanitiser: `ChannelInput.refs` arrives as `(name_norm, akind)` pairs already through
  `normalize_key` (07:3286, 07:480), its statement is printed whole at 07:1273-1281, and its
  ranking is *"definitions before occurrences; corpus scope before document scope; then
  `(doc_ord, page, ord)`"* (07:1271-1272) -- a total order over columns, not a score. So P6
  inherits a working Channel to fuse against rather than a stub. At P2 `anchor` and `ref_site` are
  empty (16-roadmap.md:114), so it returns `empty` on a stock store; `empty` is not `off`, and the
  difference is that `empty` means the statement RAN.
* **`lexical` -- refused.** `block_fts` exists at P2 (0001_init.sql:484) and nothing scores over it:
  `lex(b)` is `W_BODY`, `W_HEAD` and `SPINE_DECAY` (07:1294-1296), all three named in
  16-roadmap.md:468's exclusion, and its input is sanitised query text.
* **`structural` -- refused.** A bounded frontier BFS seeded from `identity` and `exact`
  (07:1298-1306), so it cannot be built before the Channels that seed it.
* **`semantic` -- refused.** *"No vector column"* (16-roadmap.md:468); `vec` is never attached at
  P2, so `IndexCaps.channels` also omits it, and the refusal here is the second half of the same
  fact.

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

**A second home for a P6 type.** `ChannelResult`, `ChannelStatus`, `OffReason`, `Hit` and `CHANNELS`
all belong to `omniweave_core.retrieve` (18-api-sketch.md:841) and none of them exists yet.
`channel()` therefore returns `ChannelOutcome` -- a stand-in whose `status` is a plain
`Literal["ok","empty","off","unavailable"]` rather than a new enum, so it is VALUE-COMPATIBLE with
07:1198's `ChannelStatus` (a `StrEnum` member equals its value) and nothing has to be renamed when
P6 lands. `_CHANNELS` is private for the same reason. This mirrors what `store/types.py` does for
`DegradeCause`: name the absent owner, do not mint a rival.

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

import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal

from omniweave_core.canonical import sha256_canonical
from omniweave_core.errors import StoreError, UsageError
from omniweave_core.limits import MAX_FILTER_DOC_KEYS, MAX_QUERY_REFS, PREFILTER_MAX, VEC_BRUTE_MAX
from omniweave_core.model.enums import Kind, Layer, Method, OsKind, Quote, Trust
from omniweave_core.model.spans import TextSpan
from omniweave_core.store import sqlite as ow
from omniweave_core.store.types import (
    ChannelSpec,
    Coverage,
    Filters,
    IndexCaps,
    Narrowing,
    Snapshot,
)

__all__ = [
    "ChannelOutcome",
    "HydratedRow",
    "Hydration",
    "SqliteReader",
]


# ---------------------------------------------------------------------------
# Constants. Each is a transcription with its line, or private with a stated owner.
# ---------------------------------------------------------------------------

_CHANNELS: Final = ("identity", "exact", "lexical", "structural", "semantic")
"""07:1196's `CHANNELS`, PRIVATE because its public home is `omniweave_core.retrieve`.

18-api-sketch.md:841 puts `CHANNELS` in `omniweave_core.retrieve` beside `fuse()` and `ceiling()`,
and that module holds a docstring and nothing else at P2. `IndexCaps.channels` cannot be computed
without the five names, so they are transcribed here under a private name; the moment `retrieve`
exports the tuple this becomes an import and the constant goes.
"""

_IMPLEMENTED_CHANNELS: Final = frozenset({"exact"})
"""Which of `_CHANNELS` THIS BUILD can run, as opposed to which the store supports.

The one-line edit site for P6: widening this frozenset is what turns an `off`/`not_built` outcome
into a real Channel run, and the ruling for each of the other four is in the module docstring.
"""

_OFF_NOT_BUILT: Final = "not_built"
"""`OffReason.NOT_BUILT` (07:2238), *"the P-stage has not shipped it"*, and ceiling-EXEMPT.

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

    07:1225-1235's `ChannelResult` has ten fields and four of them cannot exist at P2: `rank_of`
    is the semantic Channel's shared-rank carrier (07:1240-1248), `grades` is the identity
    ladder's measured tier, `weight` is fusion's, and `cost` is a `Spend`
    (05-ingest-and-routing.md:2370, P4's). `ChannelResult` itself lives in
    `omniweave_core.retrieve` (18-api-sketch.md:841), which is P6's and empty. So this is the
    narrowest shape the four refusals and the one implemented Channel actually need.

    **`status` is a `Literal` of `ChannelStatus`'s four VALUES, not a new enum** (07:1198-1199).
    `ChannelStatus` is a `StrEnum`, so `ChannelStatus.OFF == "off"` is `True` and P6 can compare
    against these outcomes without a conversion shim -- which is the property that makes a string
    stand-in preferable to a rival enum carrying the same members.

    `reason` is REQUIRED when `status != "ok"` (07:1232) and `__post_init__` enforces it: an
    unexplained refusal is the surprise 16-roadmap.md:114 says the Answer must disclose. For `off`
    it is an `OffReason` value, a closed four-member domain *"because `ceiling()` branches on it"*
    (07:2242-2245); for `empty` and `unavailable` it is free prose, deliberately (07:2251-2254).

    `ranked` is *"deterministic order, duplicate-free"* (07:1228) and the constructor checks the
    second half, because a Channel that ranks one block twice gives it two RRF contributions.
    """

    name: str
    status: Literal["ok", "empty", "off", "unavailable"]
    ranked: tuple[int, ...] = ()
    spans: Mapping[int, TextSpan] = MappingProxyType({})
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
    ) -> None:
        """Bind to `connection` and read `IndexCaps` ONCE, at open (07:3272).

        `now_ns` is required and has no default: `IndexCaps.stat_age_ns` is an age, and the store
        takes its clock from its caller everywhere else (`migrate.apply_pending(conn, *, now_ns)`).
        `snapshot_ms` is passed straight through to `sqlite.snapshot()`, which clamps it below
        `MAX_SNAPSHOT_MS` and reads `[retrieval] snapshot_ms` when it is `None`.
        """
        self._connection = connection
        self._snapshot_ms = snapshot_ms
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

        `vec_backend` and `vec_pushdown` come from the sidecar's `vec_manifest` (07:3339-3351) and
        the sidecar is never attached at P2 (*"No vector column"*, 16-roadmap.md:468), so they are
        `None` and `False`; the read that would fill them belongs with whatever ATTACHes `vec`, and
        `store/sqlite.py`'s `snapshot()` records the same contract for `Snapshot.vec_attached`.
        `federated` is T4's (07 section 12) and no shipped table can make it true.

        `fts_state` defaults to `stale` and not to `ok` when the key is missing. The three-state
        machine is written *"in the same transaction as the DDL that invalidates it, so a crash
        leaves the pessimistic value"* (0003_index.sql:413-418), and a store with no row at all is
        exactly as unknown as a crashed one -- *"a missing posting is indistinguishable from an
        absent phrase"*.
        """
        connection = self._connection
        objects = _objects(connection)
        state = _index_state_map(connection)
        stats = _stat_rows(connection)
        vec_attached = any(
            str(row[1]) == "vec" for row in connection.execute("PRAGMA database_list")
        )
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
            "vec_backend": None,
            "vec_ceiling": VEC_BRUTE_MAX if vec_attached else 0,
            "vec_pushdown": False,
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
            vec_backend=None,
            vec_ceiling=VEC_BRUTE_MAX if vec_attached else 0,
            vec_pushdown=False,
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

        Four of the five report `off` / `not_built` at P2 and the module docstring argues each one
        separately. `exact` runs; see `_exact`.

        **A `Narrowing` of `kind="empty"` short-circuits every Channel**, including the ones that
        would run. That is the tagged type doing its job: an empty narrowed set is a PROVEN empty
        result, and scoring over it is the jcodemunch failure in the other direction.
        """
        connection = self._bound(s)
        if spec.name not in _CHANNELS:
            msg = (
                f"{spec.name!r} is not one of the five Channels {_CHANNELS}: ChannelSpec.name is "
                f"a member of CHANNELS (07:3295), and the five are closed by 07:1196"
            )
            raise UsageError(msg, fix="name one of identity, exact, lexical, structural, semantic")
        if spec.name not in _IMPLEMENTED_CHANNELS:
            return ChannelOutcome(
                name=spec.name,
                status="off",
                reason=_OFF_NOT_BUILT,
            )
        if n.kind == "empty":
            return ChannelOutcome(
                name=spec.name,
                status="empty",
                reason="the narrowed set is empty, so there is nothing inside it to rank",
            )
        return self._exact(connection, spec, n)

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
