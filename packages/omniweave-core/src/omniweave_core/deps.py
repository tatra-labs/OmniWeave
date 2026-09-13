"""The `dep` reverse index: six closed kinds, three population paths, and one query.

02-architecture.md section 2 row 20 is this module's charter, and the exclusion column is the half
that explains the rest of it:

> | 20 | Deps | `omniweave_core.deps` | `Dep`, the closed `DepKind` (`unit`, `part`, `name`,
> `cohort`, `policy`, `service_model`), `record_deps`, `invalidate(delta)` as **one query** over
> the reverse index, `cohort_digest` | **observing a driver's reads -- impossible by design
> (INV-6), so a driver declares a `witness_set` or takes a cohort digest and pays** |
> `invalidate(delta) -> set[int]` | T-SCHEMA |

16-roadmap.md:546 schedules it as P4 W4.6. 08-runtime.md section 5.6(a) (:1812-1846) and
07-store-and-retrieval.md section 11.4 (:2951-2970) are the specification;
`0004_runtime.sql:184-217` is the table, the index and the two cohort tables.

## Why this exists at all, in one measured number

codegraph skipped the equivalent pass and measured **4.3% of its distinct edges wrong, in both
directions, silently, forever until a full rebuild** (CG-33; 12-performance.md:1117,
17-risks.md:857, 08:1852). 08:13 is the ordering claim this module discharges: *"incremental
CORRECTNESS rests on the `dep` reverse index and the `anchor_delta`, not on the cache key;
incremental SPEED rests on the cache key."* A cache key answers *"have I computed this exact input
before"*; it cannot answer *"did something this derivation read change underneath it"*, because the
thing that changed is not in the key. That question has one answer here and one in
`omniweave/run/converge.py`.

## The population paths are three because observation is zero

08:1824-1826: *"`dep` rows are populated three ways, because **observing** a driver's reads
cannot be built: `DriverIO` carries no store handle by design (INV-6), so the host cannot see what a
cross-document derivation read. There is no `DeriveIO.read_unit()`; no such type exists."*

| path | who supplies it | this module |
|---|---|---|
| runner-known inputs | the runner records what it fed the driver | `runner_deps()` |
| a declared `witness_set` | of the N it was given, the M each item consulted | `witness_deps()` |
| a cohort merkle | the runner, for corpus work that declares neither | `cohort_deps()` |

`record_deps()` is where the three meet, and it is the only function here that can refuse.

**A Witness set is a subset declaration, not a discovery** (08:1831-1839). A driver cannot name a
unit it was never given, because it has no store handle and no enumeration: the runner assembles the
input set and hands it over, and the witness set says *"of the N you gave me, item X consulted these
M"*. That is why it is cheaper than a cohort -- it narrows the runner's own over-approximation from
N to M -- and why `witness_deps()` refuses a witness naming something outside the invocation's
inputs, *"on the same rule and for the same reason as `cache.put(allowed_units=...)`"*.

**A driver never computes its own cohort digest, and `tools/layers.toml` is why.** 04:733 says a
corpus-granularity driver may *"accept a Cohort digest"*, and `accept` is the operative verb: a
driver distribution's allowed import roots are `["omniweave_ports"]` **exactly** (rule 3), so
`cohort_digest()` is unreachable from driver code by construction. The runner computes it and hands
it over, which is also what makes the digest one function rather than one per driver.

## What `changed` is, and the relation nobody declares (D175)

The invalidation query is printed three times -- 07:2954, 08:1817, `0004_runtime.sql:198` -- and all
three read:

```sql
SELECT DISTINCT d.dependent_id FROM dep d JOIN changed c
  ON c.kind = d.kind AND c.key = d.key WHERE d.digest <> c.new_digest;   -- index: dep_reverse
```

`changed(kind, key, new_digest)` is a relation **no migration creates and no document describes
creating**. It cannot be a permanent table: it is one pass's delta, it is discarded when the pass
ends, and a durable copy would be a second answer to "what moved" living beside the roster's.

So it is a TEMP table, and the plan supplies its own idiom for one rather than leaving it to taste:
07:1601-1603, for `tmp_narrow`, fixes **`IF NOT EXISTS` plus `DELETE FROM`, never `CREATE`/`DROP`**,
because *"a TEMP table lives in the connection's temp schema, and a read connection is pooled and
reused across queries; a bare `CREATE TEMP TABLE` fails on the second query on that connection"*.
`omniweave_core.store.reader` already implements that shape for three tables. `CHANGED_DDL` below is
the fourth, and `omniweave_core.store.deps` runs the three statements inside **one** `Unit` for the
same reason `SqliteCacheIndex.get_many()` chunks inside one: a delta materialised in one transaction
and joined in another is a delta that can be read against two index states.

## Deletion has no digest, and that is representable exactly once (D176)

06:2328's invalidation matrix has a row for *"a whole document deleted (`ow store rm --doc d7`)"*,
whose dependents must be re-derived. The query above can only see a key the caller puts in
`changed`, and a deleted unit has no new digest to put there. No document names a sentinel.

`ABSENT_DIGEST` is the empty string, and it is sound rather than conventional: `Dep.__post_init__`
refuses an empty digest, so no recorded row can ever hold one, so `d.digest <> c.new_digest` is
**necessarily** true for every dep on an absent key. The sentinel is unequal to everything by
construction rather than by luck, and a digest column that admitted `''` on both sides would make
deletion the one change that silently invalidates nothing.

## What is deliberately not here

**The converge pass.** 02:75 homes `op.converge` in `omniweave/run/converge.py` -- *"the
anchor_delta, the dep delta, the attribution guard"* -- and 07:2963 gives it the run-final job of
computing all three and enqueueing what changed. This module answers one question (*which work rows
did this delta invalidate*); deciding what to do about them, re-deriving `stat`, and the
`anchor_delta` over the `anchor` table are that module's.

**`dep_statements()`.** It shipped at P2 in `omniweave_core.store.queue`, with both of 08:2491's
refusals, because `complete()` needed the `dep_rows` participant slot before it had a producer.
This module is the producer; `omniweave_core.store.deps.dep_rows()` is the `Contribution` that
joins them. `DEP_KINDS` moves here and `store/queue.py` imports it, which is the move that file's
own docstring predicted: *"02-architecture.md:244 homes `Dep`, `DepKind` and `record_deps` there,
not in `omniweave_core.work`, which is why `DEP_KINDS` did not travel with the work vocabulary at
W4.1."*

**The ceiling's enforcement in `Store.complete()`.** 08:1840 puts `MAX_DEPS_PER_UNIT` there and
`dep_statements()` enforces it there. `record_deps()` enforces it **as well**, one layer earlier, so
that the operator learns before the transaction opens; the two raise the same class with the same
`fix`, and a test asserts it.

Stdlib plus three intra-core imports (INV-2, G1). No `sqlite3`: the statements here are text, and
the only thing that executes them is `omniweave_core.store.deps`.

Tier T-SCHEMA: 02-architecture.md section 2 row 20.

Specified in 02-architecture.md section 2 row 20, 08-runtime.md section 5.6(a) (:1812-1846),
07-store-and-retrieval.md section 11.4 (:2951-2970), 04-driver-system.md section 2.5 (:726-740) and
`0004_runtime.sql:184-217`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, Protocol, TypeAlias

from omniweave_core.canonical import sha256_canonical
from omniweave_core.errors import ResourceLimit, StoreError
from omniweave_core.limits import MAX_DEPS_PER_UNIT

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

__all__ = [
    "ABSENT_DIGEST",
    "CHANGED_CLEAR_SQL",
    "CHANGED_COLUMNS",
    "CHANGED_DDL",
    "CHANGED_INSERT_SQL",
    "CHANGED_TABLE",
    "COHORT_ID_HEX",
    "COHORT_PREFIX",
    "DEP_KINDS",
    "INVALIDATE_SQL",
    "Change",
    "Cohort",
    "Dep",
    "DepIndex",
    "DepKind",
    "Witness",
    "cohort_deps",
    "cohort_digest",
    "cohort_of",
    "invalidate",
    "name_digest",
    "name_key",
    "part_key",
    "policy_key",
    "record_deps",
    "runner_deps",
    "service_model_key",
    "unit_key",
    "witness_deps",
]


# --------------------------------------------------------------------------------------------
# 1. The closed domain. One home, and `store/queue.py` now imports it from here.
# --------------------------------------------------------------------------------------------

DepKind: TypeAlias = Literal["unit", "part", "name", "cohort", "policy", "service_model"]
"""`dep.kind`'s CHECK as a type. 07:2958 and 08:2818 print the six in this order."""

DEP_KINDS: Final[tuple[DepKind, ...]] = (
    "unit",
    "part",
    "name",
    "cohort",
    "policy",
    "service_model",
)
"""The six, verbatim from `0004_runtime.sql:186`, and the ORDER `record_deps()` sorts by.

The order is the DDL's, not alphabetical, and it is load-bearing in exactly one place: a stable dep
ordering makes a plan's statement boundaries reproducible, which is what `complete_boundaries()`
enumerates and what the crash matrix replays. Alphabetical would have been equally stable and would
have been a second opinion about a printed list.
"""

ABSENT_DIGEST: Final = ""
"""The `changed.new_digest` of a key that no longer exists. D176; see the module docstring.

Unequal to every recorded digest **by construction**, because `Dep.__post_init__` refuses an empty
one. A deleted unit, a retired part and a removed anchor name all reach the reverse index as a
`Change` carrying this, and the `d.digest <> c.new_digest` predicate is then necessarily true.
"""

COHORT_PREFIX: Final = "coh_"
COHORT_ID_HEX: Final = 24
"""`cohort_id = 'coh_' || sha256_canonical(merkle)[:24]` -- 08:1830, `0004_runtime.sql:206`."""


# --------------------------------------------------------------------------------------------
# 2. The key shapes. One function per kind, because `dep.key` is five different strings.
# --------------------------------------------------------------------------------------------


def unit_key(unit_uri: str) -> str:
    """A `unit` dep's key: another document's `canonical_uri`, unchanged.

    `0004_runtime.sql:187` prints the five key shapes as `uri | 'uri#p41' | 'figure:3.1' |
    cohort_id | 'route:<digest>'`; this is the first. A function rather than a bare string so that
    every key shape has one site, which is what makes `part_key()`'s separator un-guessable.
    """
    return _nonempty(unit_uri, "unit_uri")


def part_key(unit_uri: str, unit_part: str) -> str:
    """A `part` dep's key: `'uri#p41'`. `0004_runtime.sql:187`.

    An empty `unit_part` is a `unit` dep, not a `part` dep with an empty suffix, and this raises
    rather than minting `'uri#'`: `unit_part TEXT NOT NULL DEFAULT ''` means the empty string is the
    *whole unit* everywhere in the schema (`cohort_member`, `cache_index`, `work`), so `'uri#'`
    would be a second spelling of `unit_key(uri)` that the reverse index could not join to it.
    """
    if not unit_part:
        raise StoreError(
            f"part_key({unit_uri!r}, '') has no part: the empty unit_part IS the whole unit",
            fix="record a unit dep with unit_key() when the derivation read the whole unit",
        )
    return f"{_nonempty(unit_uri, 'unit_uri')}#{unit_part}"


def name_key(akind: str, name_norm: str) -> str:
    """A `name` dep's key: `'figure:3.1'` -- `f"{akind}:{name_norm}"`. 07:2958.

    07:2958 spells it `'(akind):(name_norm)'` and `0004_runtime.sql:187` gives the worked example
    `'figure:3.1'`; the example settles the parentheses as the prose's placeholder notation rather
    than literal characters. `akind` is `AnchorKind`'s lower-case member name -- the fourteen of
    `0002_graph.sql:472-481`, the SAME vocabulary as `ref_site.akind` -- and the reason that matters
    is on record: `anchor` once said `citation_key` where `ref_site` said `citekey`, and every
    citation-key reference was therefore permanently unresolved with nothing reporting it.

    `0004_runtime.sql:201-203`: the kind keys *"on `'(akind):(name_norm)'` from the `anchor` table,
    whose `scope` column resolves the document-vs-corpus ambiguity"*. The scope is therefore NOT in
    the key: a document-scoped and a corpus-scoped `figure:3.1` are one reverse-index key, and it is
    `anchor.scope` on the read side that decides which references a definition may resolve.
    """
    return f"{_nonempty(akind, 'akind')}:{_nonempty(name_norm, 'name_norm')}"


def cohort_key(cohort_id: str) -> str:
    """A `cohort` dep's key: the `cohort_id` itself, prefix checked.

    `0004_runtime.sql:206` makes the prefix part of the identity (`'coh_' || ...`), so an id that
    does not carry it is not a cohort id, and a `dep` row keyed on a bare digest would never join to
    the `cohort` table a converge pass reads to find the members.
    """
    if not cohort_id.startswith(COHORT_PREFIX):
        raise StoreError(
            f"cohort id {cohort_id!r} does not start with {COHORT_PREFIX!r}",
            fix="build the id with cohort_of(), which prefixes it",
        )
    return cohort_id


def policy_key(policy_digest: str) -> str:
    """A `policy` dep's key: `'route:<policy_digest>'`. `0004_runtime.sql:187`.

    The panel that fixed the shape also fixed what it buys: *"a policy change invalidates decisions,
    never artifacts (D4)"* (`_notes/panels/D6-runtime-systems.md:464`). The digest is both the key's
    body and the dep's `digest`, which looks redundant and is not -- the key is what the reverse
    index joins on and the digest is what the `<>` compares -- so a policy dep is the one kind where
    a changed value necessarily means a changed key, and it invalidates through the JOIN missing
    rather than through the comparison.
    """
    return f"route:{_nonempty(policy_digest, 'policy_digest')}"


def service_model_key(service: str) -> str:
    """A `service_model` dep's key: the Service NAME, e.g. `'vlm.olmocr'`.

    `_notes/panels/D6-runtime-systems.md:465` is the only place the shape is printed: key
    `vlm.olmocr`, digest `(model_id, model_rev)`, and the question it answers is *"a model upgrade
    invalidates exactly what used it"*. The name rather than the model id is right for the same
    reason 02 row 15 gives -- *"a Service is **named and never routed**"* -- so the identity that
    persists across an upgrade is the name, and the thing that moves under it is the digest.
    """
    return _nonempty(service, "service")


def name_digest(definitions: Iterable[str]) -> str:
    """A `name` dep's digest: sha256 over the **sorted definition set** for that name.

    `_notes/panels/D6-runtime-systems.md:463`. Sorted and de-duplicated, because the set is the
    fact: two documents defining `figure:3.1` in either walk order is one definition set, and a
    digest that moved with the order would re-derive every dependent on a re-walk that changed
    nothing.

    This is the value that makes 08:1848's *"the corpus grew and now this citation resolves"* a
    comparison rather than a guess, and the empty set has a digest too -- a name whose last
    definition was removed moves to `name_digest(())`, which is a change and not an absence.
    """
    return sha256_canonical(sorted(set(definitions)))


def _nonempty(value: str, field: str) -> str:
    if not value:
        raise StoreError(
            f"a dep key's {field} is empty",
            fix="pass the identifier the derivation actually read",
        )
    return value


# --------------------------------------------------------------------------------------------
# 3. `Dep` and `Change` -- the two sides of the `<>`.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Dep:
    """One input a derivation read **outside its own unit**, and the digest it read.

    Three fields and not four: `dependent_id` is the `work.id` the row hangs off and it is supplied
    by `complete()`, not by the producer, because the producer does not know its own row id until
    the planner has written it. `0004_runtime.sql:192-195` records the separate ruling that the
    table carries three non-key columns rather than the four an index register's summary cell
    printed.

    **The digest is what was OBSERVED when the dependent was derived** (`0004_runtime.sql:188`), not
    what is true now. That tense is the whole mechanism: `invalidate()` compares a recorded past
    against a supplied present, and a row re-stamped from the present on every walk would compare
    itself against itself and report clean forever. `run/discover.py`'s `ACQUIRED_SQL` carries the
    same rule for the stat triple, for the same reason.
    """

    kind: DepKind
    key: str
    digest: str

    def __post_init__(self) -> None:
        if self.kind not in DEP_KINDS:
            raise StoreError(
                f"dep kind {self.kind!r} is outside {DEP_KINDS}",
                fix="use one of the six dep kinds the dep CHECK declares",
            )
        if not self.key:
            raise StoreError("a dep key is empty", fix="build the key with this module's *_key()")
        if not self.digest:
            raise StoreError(
                f"dep {self.kind}:{self.key} has an empty digest",
                fix="record the digest the derivation observed; '' is ABSENT_DIGEST and is a "
                "change-side sentinel only",
            )

    @property
    def row(self) -> tuple[str, str, str]:
        """`(kind, key, digest)` -- exactly what `dep_statements()` takes."""
        return (self.kind, self.key, self.digest)

    @property
    def target(self) -> tuple[str, str]:
        """`(kind, key)` -- the reverse index's tuple, and this row's identity under the PK."""
        return (self.kind, self.key)


@dataclass(frozen=True, slots=True)
class Change:
    """One `changed` row: a `(kind, key)` and the digest that is true **now**.

    A `Change` is not "this differs from what was recorded" -- it is "this is the current value".
    The query does the differing, which is why one delta can be joined against every dependent in
    the store in one statement, and why a caller cannot accidentally narrow it to the rows it
    already believed were stale.

    `new_digest` is `ABSENT_DIGEST` for a key that no longer exists (D176).
    """

    kind: DepKind
    key: str
    new_digest: str

    def __post_init__(self) -> None:
        if self.kind not in DEP_KINDS:
            raise StoreError(
                f"change kind {self.kind!r} is outside {DEP_KINDS}",
                fix="use one of the six dep kinds the dep CHECK declares",
            )
        if not self.key:
            raise StoreError(
                "a change key is empty", fix="build the key with this module's *_key()"
            )

    @property
    def target(self) -> tuple[str, str]:
        """`(kind, key)` -- what the reverse index joins on."""
        return (self.kind, self.key)

    @property
    def absent(self) -> bool:
        """Whether this change says the key is *gone* rather than *different*. D176."""
        return self.new_digest == ABSENT_DIGEST


# --------------------------------------------------------------------------------------------
# 4. The three population paths.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Witness:
    """One row of a `witness_set` artefact: a foreign `(unit_uri, unit_part, token)` tuple.

    04:570 fixes the payload -- *"the foreign `(unit_uri, unit_part, token)` tuples each item
    consulted"* -- and the column beside it fixes the consumer and the stakes: produced by
    `derive.derive`, consumed by *"the host (`dep` rows)"*, and it is **the only way a driver
    contributes deps**.

    `token` is the driver's own label for *what* it read inside that unit and it reaches no `dep`
    row: `dep`'s granularity is the unit or the part, never the block (`_notes/panels/
    D6-runtime-systems.md:479` -- *"a derive operator reading 500 blocks from one other document
    writes ONE dep row"*). It is carried here because the artefact carries it, and because a
    witness that named no token would be indistinguishable from one the driver forgot to narrow.
    """

    unit_uri: str
    unit_part: str = ""
    token: str = ""

    @property
    def unit(self) -> tuple[str, str]:
        """`(unit_uri, unit_part)` -- the same tuple `cache.put(allowed_units=...)` checks."""
        return (self.unit_uri, self.unit_part)


@dataclass(frozen=True, slots=True)
class Cohort:
    """A corpus-granularity input set, digested. `0004_runtime.sql:205-217`.

    `member_sha256` is the merkle and `cohort_id` is `'coh_' || sha256_canonical(merkle)[:24]`; the
    DDL's own comment explains why the column is spelled `_sha256` rather than `_digest`, *"for the
    same reason as `unit.content_sha256`: `community.member_digest` is an `ow128` BLOB and this is a
    `sha256_canonical` hex string. Two types, two names."*

    **A cohort dep re-derives the whole cohort on any member change -- correct by construction and
    expensive on purpose** (08:1839). That is the trade it exists to make: a driver that will not
    narrow its reads pays for all of them.
    """

    cohort_id: str
    name: str
    member_count: int
    member_sha256: str


def cohort_digest(members: Iterable[tuple[str, str, str]]) -> str:
    """The member merkle: `sha256_canonical` over `(unit_uri, unit_part, content_sha256)`, sorted.

    08:1830 fixes the inputs and the ordering -- *"over `(unit_uri, unit_part, content_sha256)` in
    sorted order"* -- and 04:733 the same. Sorted, so that the runner's enumeration order cannot
    change the id of a set it did not change; de-duplicated, because a member listed twice is one
    member and a count is not part of the identity.

    **No document fixes the tree shape, and this is a flat canonical hash of the sorted list.** The
    word "merkle" in 08:1828 promises a tree; the only property anything here needs of it is that
    any member change changes the digest, which a flat hash has. The shape stays private on purpose:
    `cohort_id` is a `dep.key` compared only against other keys **in the same store**, never across
    stores and never by a driver (which cannot import this module at all -- `tools/layers.toml`
    rule 3), so nothing outside this function can observe which of the two it is.
    """
    rows = sorted({(uri, part, sha) for uri, part, sha in members})
    return sha256_canonical([list(row) for row in rows])


def cohort_of(name: str, members: Iterable[tuple[str, str, str]]) -> Cohort:
    """Build a `Cohort` from its members. The id is derived; nothing may pass one in.

    `member_count` is the count of DISTINCT members, so it agrees with the `cohort_member` rows the
    store will hold -- its PRIMARY KEY is `(cohort_id, unit_uri, unit_part)`, so a duplicate member
    is one row there and counting the input list would report a number the table cannot reach.
    """
    rows = sorted({(uri, part, sha) for uri, part, sha in members})
    merkle = sha256_canonical([list(row) for row in rows])
    return Cohort(
        cohort_id=f"{COHORT_PREFIX}{sha256_canonical(merkle)[:COHORT_ID_HEX]}",
        name=_nonempty(name, "name"),
        member_count=len(rows),
        member_sha256=merkle,
    )


def runner_deps(inputs: Mapping[tuple[str, str], str]) -> tuple[Dep, ...]:
    """Path 1: what the runner fed the driver. `unit` when the part is empty, `part` otherwise.

    08:1827: *"the runner records what it fed the driver ... always, for `unit` and `part` deps."*
    Always, because this path needs no cooperation: the runner assembled the inputs, so it can
    always name them, and it is the only one of the three that is never absent.

    The mapping is `(unit_uri, unit_part) -> content digest`, which is the tuple `cache_index`,
    `cohort_member` and `Witness` all key on, so an input set can be handed to this function, to
    `cache.put(allowed_units=...)` and to `witness_deps()` without being re-shaped between them.
    """
    out: list[Dep] = []
    for (uri, part), digest in inputs.items():
        if part:
            out.append(Dep(kind="part", key=part_key(uri, part), digest=digest))
        else:
            out.append(Dep(kind="unit", key=unit_key(uri), digest=digest))
    return tuple(out)


def witness_deps(
    witnesses: Iterable[Witness],
    *,
    inputs: Mapping[tuple[str, str], str],
) -> tuple[Dep, ...]:
    """Path 2: the driver's declared subset of `inputs`. Refuses anything outside it.

    08:1831-1839 is the whole argument and the refusal is its last sentence: *"it cannot be forged
    into naming something outside the batch: `Store.complete()` rejects a `dep` row whose key is not
    in the invocation's input set, on the same rule and for the same reason as
    `cache.put(allowed_units=...)`"*. The rule is enforced here as well as there, because here the
    offending witness is still in hand and the message can name it; by `complete()` it is a key.

    **The digest comes from `inputs`, never from the witness.** A driver names *which* of the units
    it was given an item consulted; what those units contained is the runner's observation, and a
    driver-supplied digest would let a driver record a dep that can never invalidate by recording
    the digest it wishes were current.
    """
    out: list[Dep] = []
    for witness in witnesses:
        if witness.unit not in inputs:
            raise StoreError(
                f"witness {witness.unit_uri!r} part {witness.unit_part!r} is outside the "
                f"invocation's input set of {len(inputs)} units",
                fix="declare a witness only for a unit the runner actually supplied; a driver "
                "cannot name a unit it was never given",
            )
        digest = inputs[witness.unit]
        if witness.unit_part:
            out.append(
                Dep(
                    kind="part",
                    key=part_key(witness.unit_uri, witness.unit_part),
                    digest=digest,
                )
            )
        else:
            out.append(Dep(kind="unit", key=unit_key(witness.unit_uri), digest=digest))
    return tuple(out)


def cohort_deps(cohort: Cohort) -> tuple[Dep, ...]:
    """Path 3: one dep for the whole input set. 08:1839.

    ONE row, whatever the member count, which is the point: an operator whose dep set would exceed
    `MAX_DEPS_PER_UNIT` declares this instead and the reverse index goes from 257 keys to one. The
    digest is the merkle, so any member change moves it and re-derives the whole cohort.
    """
    return (Dep(kind="cohort", key=cohort_key(cohort.cohort_id), digest=cohort.member_sha256),)


# --------------------------------------------------------------------------------------------
# 5. `record_deps()` -- where the three paths meet, and the only thing here that refuses.
# --------------------------------------------------------------------------------------------


def record_deps(
    *contributions: Iterable[Dep],
    allowed_keys: frozenset[str] | None = None,
    limit: int = MAX_DEPS_PER_UNIT,
) -> tuple[Dep, ...]:
    """Merge the population paths into the rows one `complete()` will write. 02 row 20.

    Variadic over *iterables* rather than over deps, because the three paths are three calls and
    what a caller has is three sequences: `record_deps(runner_deps(inputs), witness_deps(...))`
    reads as the merge it is, and a caller with one path passes one.

    **A second row for one `(kind, key)` with a DIFFERENT digest is refused, not resolved.** `dep`'s
    PRIMARY KEY is `(dependent_id, kind, key)` and `dep_statements()` writes `INSERT OR IGNORE`,
    so the two would reach the store as one row holding whichever digest was ordered first -- and
    which one that is depends on the argument order, not on anything a reader could reason about.
    The same shape as `admit()`'s two-reservations-one-id refusal: when one identity is minted twice
    with two values, the write silently keeps one and the invariant it was protecting is gone. An
    identical duplicate is de-duplicated in silence, because that is one fact stated twice.

    **The cap is enforced here as well as in `Store.complete()`**, and `limit` exists so that
    `[runtime] max_deps_per_unit` (18:1677 -- *"clamps below `MAX_DEPS_PER_UNIT`"*) can be honoured
    by a caller that read the config. The raise is `ResourceLimit` naming the same knob and the same
    fix as `dep_statements()`, because 08:1840 makes the remedy part of the error: *"`ow drivers
    explain` prints the fix: declare a cohort dep, which is coarser, always safe, and
    over-invalidating deliberately."*

    The result is sorted by `(DEP_KINDS.index(kind), key)` so that one input set produces one
    statement order, which is what makes a crash-matrix boundary reproducible.
    """
    seen: dict[tuple[str, str], Dep] = {}
    for contribution in contributions:
        for dep in contribution:
            previous = seen.get(dep.target)
            if previous is not None and previous.digest != dep.digest:
                raise StoreError(
                    f"dep {dep.kind}:{dep.key} was recorded twice with two digests "
                    f"({previous.digest!r} and {dep.digest!r})",
                    fix="record one digest per (kind, key): the dep PRIMARY KEY holds one row and "
                    "INSERT OR IGNORE would keep whichever arrived first",
                )
            seen[dep.target] = dep
    if allowed_keys is not None:
        for dep in seen.values():
            if dep.key not in allowed_keys:
                raise StoreError(
                    f"dep key {dep.key!r} is outside the invocation's input set of "
                    f"{len(allowed_keys)} keys",
                    fix="record a dep only on an input the invocation actually read",
                )
    if len(seen) > limit:
        raise ResourceLimit(
            f"this derivation declared {len(seen)} deps and the ceiling is {limit}",
            limit="[runtime] max_deps_per_unit",
            fix="declare a cohort dep instead: coarser, always safe, over-invalidating on purpose",
        )
    return tuple(sorted(seen.values(), key=lambda dep: (DEP_KINDS.index(dep.kind), dep.key)))


# --------------------------------------------------------------------------------------------
# 6. Invalidation -- one query, never a sweep.
# --------------------------------------------------------------------------------------------

CHANGED_TABLE: Final = "ow_changed"
"""The TEMP table the printed query calls `changed`. D175; see the module docstring.

Prefixed `ow_` rather than named `changed`, because a TEMP table shares a namespace with the main
schema for unqualified lookups: an unprefixed `changed` in `temp` would shadow a future `changed`
in `main` silently, and every other temp table in this codebase (`tmp_narrow`, `tmp_docs`,
`tmp_refs`) already carries a prefix that says which schema it lives in. `INVALIDATE_SQL` keeps the
printed query's `changed c` alias so that a reader grepping for the plan's text finds this.
"""

CHANGED_COLUMNS: Final = ("kind", "key", "new_digest")
"""The three columns the printed query's `c` alias reads. 07:2954-2955."""

CHANGED_DDL: Final = (
    f"CREATE TEMP TABLE IF NOT EXISTS {CHANGED_TABLE}"
    "(kind TEXT NOT NULL, key TEXT NOT NULL, new_digest TEXT NOT NULL,"
    " PRIMARY KEY (kind, key)) WITHOUT ROWID"
)
"""`IF NOT EXISTS`, never `CREATE`/`DROP` -- 07:1601-1603's rule, for 07:1601-1603's reason.

`WITHOUT ROWID` on `(kind, key)` for the same reason `tmp_narrow` is: the table exists to be joined
on its key and nothing ever selects it by rowid. The PRIMARY KEY also makes the delta a *set* --
`INSERT OR REPLACE` below means a caller that observes one key twice records the later observation
rather than two rows that would each match the same dep and be collapsed by the `DISTINCT` anyway.

No CHECK on `kind`: `Change.__post_init__` holds the domain, the table lives for one statement, and
a CHECK here would be a second copy of `DEP_KINDS` that no migration governs.
"""

CHANGED_CLEAR_SQL: Final = f"DELETE FROM {CHANGED_TABLE}"  # noqa: S608 -- a constant
"""*"The `DELETE` is O(rows) on an in-memory B-tree and costs less than the `CREATE`"* (07:1603)."""

CHANGED_INSERT_SQL: Final = (
    f"INSERT OR REPLACE INTO {CHANGED_TABLE}(kind, key, new_digest) VALUES(?, ?, ?)"
)

INVALIDATE_SQL: Final = (
    "SELECT DISTINCT d.dependent_id FROM dep d "  # noqa: S608 -- a constant
    f"JOIN {CHANGED_TABLE} c ON c.kind = d.kind AND c.key = d.key "
    "WHERE d.digest <> c.new_digest"
)
"""The query, transcribed from 07:2954-2955 / 08:1817-1818 / `0004_runtime.sql:198-199`.

Three printed copies agree character for character apart from whitespace, and the only edit here is
the table name (D175). `dep_reverse ON dep(kind, key)` is the index it plans on, which is what makes
this one query rather than a sweep: the join drives from the delta, so the cost is O(delta) and
not O(deps in the store). 12-performance.md:1400 budgets it as *"ONE query on
`dep_reverse(kind, key)`"*.

`DISTINCT` because one work row can hold up to `MAX_DEPS_PER_UNIT` deps and several of them can
change in one delta; the answer is a set of work rows, not a count of reasons.
"""


class DepIndex(Protocol):
    """What `invalidate()` needs of a store: one method, one query.

    Deliberately not `runtime_checkable`, like `cache.BatchIndex` and for the same reason -- a
    structural check on a Protocol with one method would pass for anything with a `dependents`
    attribute, so the check that matters is the one pyright does at the call site.

    `Sequence` and positional-only, because the implementation names the parameter for the delta and
    a named Protocol parameter would promise that spelling to every implementor; `BudgetLedger`
    learned that at W4.5.
    """

    def dependents(self, changes: Sequence[Change], /) -> frozenset[int]:
        """The `work.id`s whose recorded digest differs from `changes`. One statement."""
        ...


def invalidate(delta: Sequence[Change], *, index: DepIndex) -> frozenset[int]:
    """Which work rows this delta invalidates. 02 row 20's `invalidate(delta) -> set[int]`.

    **An empty delta asks nothing.** Materialising zero rows and joining against them returns the
    empty set at the cost of three statements and a transaction; returning early is the same answer.
    A converge pass over a body-only edit has an empty `anchor_delta` and frequently an empty dep
    delta too (08:1853 -- *"the common case, and free"*), so this is the ordinary path rather than a
    guard against misuse.

    `index` is the divergence from the printed signature and it is not a defect: row 20's Public
    surface column abbreviates every row (row 19 prints `BudgetLedger.reserve/commit/release/
    headroom` with no arguments at all), and a query needs a store to run against. What the printed
    signature does fix is the RETURN: a set of `work.id`s, which is what `dependent_id` is, so the
    caller's next move is a `work` transition and never a second lookup to find out what these are.

    Frozen, because the answer is a query result: a caller that added to it would be adding to
    nothing the store knows about.
    """
    if not delta:
        return frozenset()
    return index.dependents(tuple(delta))
