"""`ow store verify` and `ow doc verify` -- every store clause, as a report and not an exception.

**What this module IS.** The library behind two `ow` verbs that P7 wires (16-roadmap.md section 10);
the verbs are named in P2's exit criteria at 16-roadmap.md:435 and :420, which is a phase-ordering
fact and not an error -- the same shape as `tools/schemagen.py` running `ow schema emit` before `ow`
exists. `verify_store()` is `ow store verify`, `verify_doc()` is `ow doc verify`, and the four
documented flags are subsets of one clause set: `--fts` is `FTS_CLAUSES`, `--graph` is
`GRAPH_CLAUSES`, `--lock` is `LOCK_CLAUSES`, `--erased` is `ERASED_CLAUSES`, and no flag at all is
`DEFAULT_CLAUSES`. There is no argument parser here and no entry point.

**The headline clause and its rule.** 16-roadmap.md:435: *"`ow store verify` re-derives every
`content_digest` and every `content_sha256` from stored bytes and compares"*. Re-derives means what
it says: `block.content_digest` is recomputed with `omniweave_core.identity.content_digest` from the
row's own `kind`, `layer`, `text` and `payload` plus its children's digests, and a `part` or `asset`
sha256 is recomputed by streaming the CAS object through `hashlib` -- **never by asking a stored
value whether it equals itself.** A round trip that reads its expected value out of the database it
is checking cannot fail, and that is the entire failure this clause exists to catch.

**A report, not an exception.** Every clause returns what it checked, what it found and where, so
`ow doctor` can print a corrupt store rather than dying on its first surprise -- the same decision,
for the same reason, that `omniweave_core.archive.owcheck` records in its module docstring
(03:1027's "re-asserts", 03:3222's `Diag` rather than a crash). Only an **unusable** store raises:
`_require_store` refuses a file with no `block` table, because there is nothing there to report on.
`ClauseState` is imported from `owcheck` rather than redeclared: `passed` / `failed` / `unchecked`
is one three-valued vocabulary with one home, and an UNCHECKED clause is not a pass.

**`ow doc verify` is `owcheck` over one document.** `verify_doc` reads the six facts
`owcheck.BlockFacts` needs out of `block`, the `rel` edges, the grids and the retained `part` paths,
and calls `owcheck.owcheck()`. It re-implements no clause. That is 03:1020-1030's design working as
intended: `owcheck` takes rows a caller already has, so one implementation runs over a store and
over an archive, and `ClauseResult.clause` is a `StrEnum` value in both -- which is why this
module's `ClauseResult.clause` is typed `str` and carries either vocabulary.

THE FIFTEEN CLAUSES AND THEIR DEFINITION SITES
-----------------------------------------------
| clause | site |
|---|---|
| `block_digest` | 16-roadmap.md:435; the recipe is 03-document-model.md section 6.4 |
| `segment_digest` | 16-roadmap.md:435; the recipe is 06-structure-extraction.md:1002 |
| `cas_digest` | 16-roadmap.md:435 ("from stored bytes"); 07-store-and-retrieval.md:3184-3185 |
| `content_sha256` | 16-roadmap.md:435; the two hashes are related at 05-ingest-and-routing.md:258 |
| `generations` | 03-document-model.md:2691 -- a third generation means a sweep did not run |
| `retired_occurrences` | 03-document-model.md:2789 -- the deprecation census |
| `via_entity` | 07-store-and-retrieval.md:590 / `0003_index.sql:307-315` -- no FK to check it |
| `cover_bits` | 06-structure-extraction.md:779 -- `LENGTH(cover_bits) <> 64` is a corrupt store |
| `single_home` | 07-store-and-retrieval.md:3199-3211 (ST23 at :3262), 11-repo-layout.md:1196-1202 |
| `fts_integrity` | 07-store-and-retrieval.md:418; ST21 at :3260 |
| `fts_rowcount` | 07-store-and-retrieval.md:418 ("compares row counts"); ST21 |
| `graph_closure` | 06-structure-extraction.md:2394 -- recompute the closure from the log |
| `lock_markers` | 07-store-and-retrieval.md:3150; ST19 at :3253; D-03 at 15-observability.md:1516 |
| `lock_store_match` | 07-store-and-retrieval.md:3155 -- re-derive the receipt and compare |
| `erased_residue` | 14-security.md:1205-1210 -- the fourteen-location cascade |

**On the `# noqa: S608`s.** Six statements interpolate a table or column name. Every one of
those names comes from `sqlite_master`, from `PRAGMA table_info`, or from a module constant in
this file -- never from a caller, and never from a row's *value*. A verify that could not name a
table it discovered could not scan the schema for a second `schema` home at all, which is
07:3205's instruction in as many words ("every other table by PRAGMA table_info"). Every value
in every one of them is still a bind parameter. `store/reader.py:133-140` states the same rule
for its fourteen.

Stdlib only (INV-2). `import sqlite3` is legal here: this module is under `store/` (INV-17,
TID251). No clock, no ids: `now_ns` is the caller's, exactly as `migrate.apply_pending` and
`SqliteReader` take it.

Tier T-SCHEMA: 02-architecture.md section 2 row 25.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.archive.owcheck import (
    BlockFacts,
    ClauseState,
    Generation,
    OwcheckReport,
    owcheck,
)
from omniweave_core.archive.owdoc import GridRow
from omniweave_core.blobs import parse_ref
from omniweave_core.canonical import ow128
from omniweave_core.errors import StoreError, UsageError
from omniweave_core.identity import content_digest as ow_content_digest
from omniweave_core.limits import MAX_SEGMENT_BLOCKS
from omniweave_core.model import Kind, Layer, Quote, RelKind
from omniweave_core.model.block import Addr
from omniweave_core.store.indexlock import (
    LOCK_PATH,
    LockFile,
    LockHeader,
    LockRow,
    has_conflict_markers,
    read_lock,
)

if TYPE_CHECKING:  # pragma: no cover -- typing only, so `blobs` stays a use-time import for G17.
    from omniweave_core.blobs import BlobStore

__all__ = [
    "ALL_CLAUSES",
    "COVER_BITS_BYTES",
    "DEFAULT_CLAUSES",
    "ERASED_CLAUSES",
    "FTS_CLAUSES",
    "GRAPH_CLAUSES",
    "LOCK_CLAUSES",
    "MAX_LIVE_GENERATIONS",
    "ClauseResult",
    "ClauseState",
    "Finding",
    "VerifyClause",
    "VerifyReport",
    "derive_lock",
    "verify_doc",
    "verify_store",
]

# --------------------------------------------------------------------------------------------
# Constants, each with the line that fixes it
# --------------------------------------------------------------------------------------------

MAX_LIVE_GENERATIONS: Final = 2
"""*"the head plus at most one staged. A third would mean a sweep did not run"* (03:2691)."""

COVER_BITS_BYTES: Final = MAX_SEGMENT_BLOCKS // 8
"""*"EXACTLY `ceil(MAX_SEGMENT_BLOCKS/8)` = 64 B"* (`0002_graph.sql:220-221`, 06:779).

Derived from `limits.MAX_SEGMENT_BLOCKS` rather than written `64`, because two homes for one
number is what 18-api-sketch.md section 4 forbids and `MAX_SEGMENT_BLOCKS` is already the home.
`512 // 8` is exact, so `ceil` needs no rounding term -- and a future non-multiple-of-eight limit
would fail this file's own test rather than silently truncate the bitmap.
"""

_SEGMENT_DOMAIN: Final = b"ow.segment.1"
"""06-structure-extraction.md:1002's digest domain, spelled as `0002_graph.sql:153` prints it."""

_SCHEMA_KEY: Final = "schema"
_SCHEMA_HOME: Final = "index_state"
"""ADR-9 decision 3: `index_state.schema` is the sole disk home and `meta` never gains a key."""

_SCHEMA_COLUMN_EXEMPT: Final = MappingProxyType(
    {
        "run": (
            "`run.schema` is the SCHEMA MAJOR this run wrote, recorded per run "
            "(`0004_runtime.sql:245-248`). A per-run RECORD of what happened is not a home for "
            'what is true: the DDL excuses it in as many words -- "It is not a second home for '
            "the store's version\" -- and this constant is the transcription of that excusal, "
            "not a decision taken here."
        )
    }
)
"""The one shipped `schema` column that is not a second home, and the DDL line that excuses it.

A register, so it obeys the register rule: it transcribes and adds nothing. `test_store_verify.py`
pins its contents against a literal, so a migration that adds a second such column fails
`single_home` on a clean store until somebody writes down why -- which is the outcome ADR-9 wants,
since rejection criterion 19 makes "a second home for one config key" a rejection and a silent
allow-list is how that criterion stops being enforced.
"""

_SECOND_HOME: Final = "OW_SCHEMA_SECOND_HOME"
"""`OW-S-034` (07:3199, `codes.toml`). The one clause code this module can resolve to a numeral."""

_CONFLICT_MARKER_CODE: Final = "OW-S-061"
"""07:3150 and 15:1516 (D-03) name the NUMERAL and `codes.toml` carries no row for it.

Carried as the numeral rather than a symbol for that reason: inventing `OW_LOCK_CONFLICT_MARKED`
would put a symbol in the tree that the append-only register does not know, and the register is
not this wave's file. Reported; the row is owed to whoever next appends to `codes.toml`.
"""

_ERASURE_CODE: Final = "OW_ERASURE_INCOMPLETE"
"""`OW-S-070` (14:1208, `codes.toml`)."""

_INTEGRITY: Final = "OW_INTEGRITY_UNCHECKED"
"""The code 07:2584 and 07:3193 use for "the bytes that would settle this are not readable"."""

_STORE: Final = "OW_STORE"
"""`StoreError`'s class default, used where the plan allocates no symbol. See `owcheck`'s note."""

_FIX_VERIFY: Final = "ow store verify"
_FIX_REPAIR: Final = "ow store repair"
_FIX_LOCK: Final = "ow store lock"

_HEX_DIGITS: Final = frozenset("0123456789abcdef")
_SHA256_HEX_LEN: Final = 64
_DOC_KEY_BYTES: Final = 16
"""`doc.doc_key` is `sha256(NORMALIZED source bytes)[:16]` (`0001_init.sql:150`)."""

_ROOT_ADDR: Final = "doc"
"""03:816 -- the document root block's `addr` is the literal `doc`."""

_VOCAB_TABLE: Final = "ow_verify_vocab"
"""The name of the TEMP `fts5vocab` shadow this module creates and drops. See `_indexed_rowids`."""


class VerifyClause(StrEnum):
    """The fifteen clauses, one member per definition site. Closed and append-only.

    A `StrEnum` for the reason `owcheck.Clause` is one: a clause name reaches an operator through
    `ow doctor` output and a `diag.detail` JSON object, and a name that is a bare string in one
    place and an enum in another drifts. The values are disjoint from `owcheck.Clause`'s six, so
    one `VerifyReport` can carry both vocabularies without collision --
    `test_store_verify.py` asserts that disjointness rather than trusting it.
    """

    BLOCK_DIGEST = "block_digest"
    SEGMENT_DIGEST = "segment_digest"
    CAS_DIGEST = "cas_digest"
    CONTENT_SHA256 = "content_sha256"
    GENERATIONS = "generations"
    RETIRED_OCCURRENCES = "retired_occurrences"
    VIA_ENTITY = "via_entity"
    COVER_BITS = "cover_bits"
    SINGLE_HOME = "single_home"
    FTS_INTEGRITY = "fts_integrity"
    FTS_ROWCOUNT = "fts_rowcount"
    GRAPH_CLOSURE = "graph_closure"
    LOCK_MARKERS = "lock_markers"
    LOCK_STORE_MATCH = "lock_store_match"
    ERASED_RESIDUE = "erased_residue"


FTS_CLAUSES: Final = frozenset({VerifyClause.FTS_INTEGRITY, VerifyClause.FTS_ROWCOUNT})
"""`--fts` (07:418)."""

GRAPH_CLAUSES: Final = frozenset({VerifyClause.GRAPH_CLOSURE})
"""`--graph` (06:2394)."""

LOCK_CLAUSES: Final = frozenset({VerifyClause.LOCK_MARKERS, VerifyClause.LOCK_STORE_MATCH})
"""`--lock` (07:3150, :3155)."""

ERASED_CLAUSES: Final = frozenset({VerifyClause.ERASED_RESIDUE})
"""`--erased` (14:1205)."""

DEFAULT_CLAUSES: Final = (
    frozenset(VerifyClause) - FTS_CLAUSES - GRAPH_CLAUSES - LOCK_CLAUSES - (ERASED_CLAUSES)
)
"""The unflagged set. 07:3203 puts single-homedness *"in its default, unflagged set"*, and the
four flags name the four subsets above; everything else is therefore default by subtraction, which
is what keeps a newly added clause from silently defaulting to unreachable."""

ALL_CLAUSES: Final = frozenset(VerifyClause)


# --------------------------------------------------------------------------------------------
# The report
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Finding:
    """One thing found wrong. `where` names the subject in the store's own terms.

    `code` is the `codes.toml` SYMBOL where the plan allocates one and the numeral where it
    allocates only a numeral (`OW-S-061`); `clause` is always the discriminator a caller
    branches on, which is `owcheck.Violation`'s rule and the reason it survives an unallocated
    code.
    """

    clause: str
    code: str
    where: str
    detail: str


@dataclass(frozen=True, slots=True)
class ClauseResult:
    """One clause's verdict, what it looked at, and what it found.

    `checked` is not decoration: a clause that passed over zero rows and one that passed over
    600,000 are different facts, and it is what makes a silently-empty subject visible. `counts`
    carries a census -- 03:2789's *"counts remaining occurrences so a corpus owner can see when
    they hit zero"* is a number and not a verdict, and a clause with nothing to fail still has
    something to report.
    """

    clause: str
    state: ClauseState
    checked: int
    findings: tuple[Finding, ...] = ()
    reason: str = ""
    counts: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VerifyReport:
    """Every clause's result. `ok` is true only when no clause FAILED.

    An UNCHECKED clause does not make `ok` false -- it makes `complete` false, which is
    `OwcheckReport`'s split and is here for the same reason: a store whose CAS was not supplied
    is legitimately unverifiable on the digest clause and must still be openable, while a store
    with two `schema` homes must never be served.

    `at_ns` is the caller's clock. Nothing in this module reads one (the semgrep bank bans it in
    library code), and a report an operator prints without a timestamp is a report they cannot
    file against a run.
    """

    clauses: tuple[ClauseResult, ...]
    at_ns: int

    @property
    def ok(self) -> bool:
        return all(c.state is not ClauseState.FAILED for c in self.clauses)

    @property
    def complete(self) -> bool:
        return all(c.state is ClauseState.PASSED for c in self.clauses)

    @property
    def findings(self) -> tuple[Finding, ...]:
        return tuple(f for clause in self.clauses for f in clause.findings)

    def by_clause(self, clause: str) -> ClauseResult:
        """The one result for `clause`, by its `StrEnum` value or the equal plain string."""
        for result in self.clauses:
            if result.clause == clause:
                return result
        msg = f"no result for clause {clause!r}"
        raise KeyError(msg)


def _passed(clause: VerifyClause, checked: int, **counts: int) -> ClauseResult:
    return ClauseResult(clause, ClauseState.PASSED, checked, counts=dict(counts))


def _result(
    clause: VerifyClause, checked: int, findings: Sequence[Finding], **counts: int
) -> ClauseResult:
    state = ClauseState.FAILED if findings else ClauseState.PASSED
    return ClauseResult(clause, state, checked, tuple(findings), counts=dict(counts))


def _unchecked(clause: VerifyClause, reason: str, *, checked: int = 0) -> ClauseResult:
    return ClauseResult(clause, ClauseState.UNCHECKED, checked, reason=reason)


# --------------------------------------------------------------------------------------------
# The two entry points
# --------------------------------------------------------------------------------------------


def verify_store(
    connection: sqlite3.Connection,
    *,
    now_ns: int,
    clauses: Iterable[str] = DEFAULT_CLAUSES,
    blobs: BlobStore | None = None,
    lock_text: str | None = None,
    uri_root: str | None = None,
) -> VerifyReport:
    """`ow store verify`. Run each selected clause and return what every one of them found.

    `clauses` is any iterable of clause names, so `--fts` is `verify_store(conn, now_ns=t,
    clauses=FTS_CLAUSES)` and `--fts --lock` is the union; a name that is not a `VerifyClause`
    is a `UsageError`, because a flag misspelled in a script must not silently verify nothing.

    `blobs` is the CAS. Without it the digest clause over `part` and `asset` is UNCHECKED and
    not passed: those rows' bytes live outside the database, and "I could not read them" is a
    third state (07:3184-3185's *"a CAS blob's bytes changed"* is exactly what goes unnoticed
    when a missing CAS reads as a pass).

    `lock_text` is `omniweave.index.lock` as read off disk. Reading files is the CLI's job and
    not this module's -- `LOCK_PATH` says where it lives -- so `--lock` without it is UNCHECKED.
    `uri_root` is the root the receipt's uris were written relative to, which `derive_lock` takes
    for the same reason: the comparison has to re-derive the same spelling `ow ingest` wrote.

    Raises `StoreError` only for a store that cannot be reported on at all.
    """
    _require_store(connection)
    wanted = _selected(clauses)
    runners: dict[VerifyClause, Any] = {
        VerifyClause.BLOCK_DIGEST: lambda: _block_digest(connection),
        VerifyClause.SEGMENT_DIGEST: lambda: _segment_digest(connection),
        VerifyClause.CAS_DIGEST: lambda: _cas_digest(connection, blobs),
        VerifyClause.CONTENT_SHA256: lambda: _content_sha256(connection),
        VerifyClause.GENERATIONS: lambda: _generations(connection),
        VerifyClause.RETIRED_OCCURRENCES: _retired_occurrences,
        VerifyClause.VIA_ENTITY: lambda: _via_entity(connection),
        VerifyClause.COVER_BITS: lambda: _cover_bits(connection),
        VerifyClause.SINGLE_HOME: lambda: _single_home(connection),
        VerifyClause.FTS_INTEGRITY: lambda: _fts_integrity(connection),
        VerifyClause.FTS_ROWCOUNT: lambda: _fts_rowcount(connection),
        VerifyClause.GRAPH_CLOSURE: lambda: _graph_closure(connection),
        VerifyClause.LOCK_MARKERS: lambda: _lock_markers(lock_text),
        VerifyClause.LOCK_STORE_MATCH: lambda: _lock_store_match(connection, lock_text, uri_root),
        VerifyClause.ERASED_RESIDUE: lambda: _erased_residue(connection),
    }
    results = tuple(runners[clause]() for clause in VerifyClause if clause in wanted)
    return VerifyReport(clauses=results, at_ns=now_ns)


def verify_doc(connection: sqlite3.Connection, doc_ord: int, gen: int) -> VerifyReport:
    """`ow doc verify` -- `owcheck` over one generation of one document, out of the store.

    **This runs no clause of its own.** `omniweave_core.archive.owcheck` already implements the
    six structural invariants (glossary.md:855's four, plus 03:2233's `continues` acyclicity and
    03:1027's layer inheritance) and takes rows rather than a connection precisely so that one
    implementation serves a store and an archive; re-deriving them here would be the second home
    03:1027 exists to prevent. This function's whole job is the adapter `owcheck.block_facts`
    names -- *"the store wave builds it from a row"*.

    `gen` is explicit and not read from `doc.gen`, because a staged generation is exactly the
    thing worth verifying before `end_doc()` publishes it (03 section 2.9), and defaulting to the
    head would make the interesting case unreachable.

    Takes no `now_ns`: `owcheck` has no clock either, and a structural report over rows that are
    already durable has nothing to stamp that the caller's own run manifest does not.
    """
    _require_store(connection)
    report = owcheck(_generation(connection, doc_ord, gen))
    return VerifyReport(clauses=tuple(_from_owcheck(report)), at_ns=0)


def _from_owcheck(report: OwcheckReport) -> Iterable[ClauseResult]:
    """`owcheck`'s results in this module's shape. Nothing is recomputed; `Violation` renames.

    `owcheck.Violation.addr` becomes `Finding.where` and `.detail` stays `.detail`: the two types
    differ only in that one is addressed by `addr` (an archive has no `block_id`) and the other
    by whatever the clause's subject is. Keeping two names for one field would be worse than the
    rename, which is why `Finding` does not simply reuse `Violation`.
    """
    for result in report.clauses:
        yield ClauseResult(
            clause=result.clause.value,
            state=result.state,
            checked=result.checked,
            findings=tuple(
                Finding(v.clause.value, v.code, v.addr, v.detail) for v in result.violations
            ),
            reason=result.reason,
        )


def _selected(clauses: Iterable[str]) -> frozenset[VerifyClause]:
    """Resolve names to members, refusing an unknown one by name."""
    known = {clause.value: clause for clause in VerifyClause}
    wanted: set[VerifyClause] = set()
    for name in clauses:
        member = known.get(str(name))
        if member is None:
            raise UsageError(
                f"{name!r} is not a verify clause; the fifteen are {sorted(known)}",
                fix=_FIX_VERIFY,
            )
        wanted.add(member)
    return frozenset(wanted)


def _require_store(connection: sqlite3.Connection) -> None:
    """Refuse a file that is not an omniweave store. The one raise on the happy path's edge.

    A corrupt store must be *describable*, so every clause below reports; a file with no `block`
    table is not a corrupt store but a different file, and reporting fifteen UNCHECKED clauses
    against it would be a plausible-looking answer to a question that was never asked.
    """
    if not _has_table(connection, "block"):
        raise StoreError(
            "this database has no `block` table, so it is not an omniweave store",
            fix="ow store init",
        )


def _has_table(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?", (name,)
    ).fetchone()
    return row is not None


def _columns(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    return tuple(str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})"))


def _user_tables(connection: sqlite3.Connection) -> tuple[str, ...]:
    """Every real table, `sqlite_*` and the FTS5 shadow tables excluded.

    An FTS5 virtual table brings five `<name>_data`/`_idx`/`_content`/`_docsize`/`_config`
    shadows whose columns are FTS5's, not the schema's; scanning them for a `schema` column
    would be scanning SQLite's internals for an omniweave invariant.
    """
    shadows = tuple(f"_{suffix}" for suffix in ("data", "idx", "content", "docsize", "config"))
    names = [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        )
    ]
    return tuple(
        name for name in names if not name.startswith("sqlite_") and not name.endswith(shadows)
    )


# --------------------------------------------------------------------------------------------
# Clause 1 -- `block.content_digest`, re-derived. 16-roadmap.md:435, 03 section 6.4.
# --------------------------------------------------------------------------------------------


def _block_digest(connection: sqlite3.Connection) -> ClauseResult:
    """Recompute every `block.content_digest` with `identity.content_digest` and compare.

    **The recipe is not restated here.** `omniweave_core.identity.content_digest` is 03 section
    6.4's one implementation and this clause calls it with the row's own columns, which is what
    makes the check falsifiable: a digest column edited in place disagrees with the recipe, and a
    recipe edited in place disagrees with every row in the corpus. Hand-rolling the hash here
    would produce a check that passes whenever the two hand-rolls agree -- including when both
    are wrong.

    The children are read exactly as `DocSink._closure_pass` writes them (`store/doc.py:1940-1948`
    -- `WHERE parent_id = ? AND gen = ? ORDER BY ord`), because a verify that ordered them
    differently would report every container in the store. `state` is deliberately not filtered:
    the writer does not filter it either, and a tombstoned child that vanished from the digest
    input would make a retirement rewrite its parent's identity.

    Memory is one dict of `(parent_id, gen) -> [(ord, digest)]` over the corpus -- `O(blocks)`
    with a 16-byte value, so ~24 MB of digests at 600k blocks. Two scans and no per-row query is
    what keeps this affordable; the alternative, one child query per container, is a second scan
    per level of nesting.
    """
    children: dict[tuple[int, int], list[tuple[int, bytes]]] = {}
    for row in connection.execute(
        "SELECT parent_id, gen, ord, content_digest FROM block WHERE parent_id IS NOT NULL"
    ):
        children.setdefault((int(row[0]), int(row[1])), []).append((int(row[2]), bytes(row[3])))

    findings: list[Finding] = []
    checked = 0
    for row in connection.execute(
        "SELECT block_id, gen, cite, kind, layer, text, payload, content_digest FROM block"
    ):
        checked += 1
        block_id, gen, cite = int(row[0]), int(row[1]), str(row[2])
        payload = None if row[6] is None else json.loads(row[6])
        kids = sorted(children.get((block_id, gen), ()))
        derived = ow_content_digest(int(row[3]), int(row[4]), row[5], payload, [d for _, d in kids])
        stored = bytes(row[7])
        if stored != derived:
            findings.append(
                Finding(
                    VerifyClause.BLOCK_DIGEST,
                    _INTEGRITY,
                    cite,
                    f"stored content_digest {stored.hex()} but the recipe over this row's kind, "
                    f"layer, text, payload and {len(kids)} children gives {derived.hex()}",
                )
            )
    return _result(VerifyClause.BLOCK_DIGEST, checked, findings, containers=len(children))


# --------------------------------------------------------------------------------------------
# Clause 2 -- `segment.content_digest`, re-derived. 06-structure-extraction.md:1002.
# --------------------------------------------------------------------------------------------


def _segment_digest(connection: sqlite3.Connection) -> ClauseResult:
    """Recompute every `segment.content_digest` from 06:1002's recipe and compare.

    ```text
    ow128(b'ow.segment.1', [segmenter.driver_id, segmenter.driver_schema_v,
      segmenter.params_digest, heading_path, [b.content_digest for b in members in (page, ord)]])
    ```

    **Two encodings 06:1002 does not state, and why each is resolved the way it is.**
    `params_digest` and the member digests are BLOBs and `canonical()` has no `bytes` arm, so the
    recipe as printed is not directly executable. Both are rendered as lower-case hex, which is
    the convention `identity.content_digest` already uses for its `children` and which
    `store/doc.py:346` records in as many words -- *"`identity.content_digest()` embeds its
    children as hex: `canonical()` has no `bytes` arm"*. Choosing the same convention twice is a
    convention; choosing a different one here would be a second one. Reported as a plan defect.

    **Member order is 06:1002's `(page, ord)` and not the DDL comment's "in ord".**
    `0002_graph.sql:153-154` says *"member content_digests in ord"* inside a comment, and a
    comment is not a definition site; 06:1002 is prose in the section that owns the segmenter.
    The two agree whenever `segment_block.ord` was assigned in reading order, which is what it
    means, so the clause also reports the disagreement rather than silently preferring one.

    P2 ships no `segment` rows (16-roadmap.md:449, "the tables exist and are empty"), so this
    clause normally passes over zero rows -- which is exactly why `checked` is in the report.
    """
    if not _has_table(connection, "segment") or not _has_table(connection, "segmenter"):
        return _unchecked(
            VerifyClause.SEGMENT_DIGEST, "this store has no `segment` table (schema below 0002)"
        )
    findings: list[Finding] = []
    checked = 0
    disagreements = 0
    for row in connection.execute(
        "SELECT s.segment_id, s.heading_path, s.content_digest, g.driver_id, g.driver_schema_v, "
        "g.params_digest FROM segment s JOIN segmenter g ON g.segmenter_id = s.segmenter_id"
    ):
        checked += 1
        segment_id = int(row[0])
        members, in_ord = _segment_members(connection, segment_id)
        if not in_ord:
            disagreements += 1
        try:
            heading_path = json.loads(str(row[1]))
        except json.JSONDecodeError:
            findings.append(
                Finding(
                    VerifyClause.SEGMENT_DIGEST,
                    _STORE,
                    f"segment {segment_id}",
                    f"heading_path is not the JSON array the DDL declares: {row[1]!r}",
                )
            )
            continue
        derived = ow128(
            _SEGMENT_DOMAIN,
            [
                str(row[3]),
                int(row[4]),
                bytes(row[5]).hex(),
                heading_path,
                [digest.hex() for digest in members],
            ],
        )
        stored = bytes(row[2])
        if stored != derived:
            findings.append(
                Finding(
                    VerifyClause.SEGMENT_DIGEST,
                    _INTEGRITY,
                    f"segment {segment_id}",
                    f"stored content_digest {stored.hex()} but 06:1002's recipe over "
                    f"{len(members)} members gives {derived.hex()}",
                )
            )
    return _result(
        VerifyClause.SEGMENT_DIGEST, checked, findings, member_order_disagreements=disagreements
    )


def _segment_members(
    connection: sqlite3.Connection, segment_id: int
) -> tuple[tuple[bytes, ...], bool]:
    """The member digests in 06:1002's `(page, ord)` order, and whether `segment_block.ord` agrees.

    The second value is the DDL comment's reading tested against the definition site's, per row
    rather than per corpus: they differ only where `segment_block.ord` was not assigned in
    reading order, which is a fact about that segment and belongs in that segment's report.
    """
    rows = [
        (int(r[0]), int(r[1]), int(r[2]), bytes(r[3]))
        for r in connection.execute(
            "SELECT b.page, b.ord, sb.ord, b.content_digest FROM segment_block sb "
            "JOIN block b ON b.block_id = sb.block_id WHERE sb.segment_id = ?",
            (segment_id,),
        )
    ]
    by_reading = sorted(rows, key=lambda r: (r[0], r[1]))
    by_member = sorted(rows, key=lambda r: r[2])
    return tuple(r[3] for r in by_reading), [r[3] for r in by_reading] == [r[3] for r in by_member]


# --------------------------------------------------------------------------------------------
# Clause 3 -- the CAS digests, re-derived from the stored bytes. 16-roadmap.md:435, 07:3184.
# --------------------------------------------------------------------------------------------


def _cas_digest(connection: sqlite3.Connection, blobs: BlobStore | None) -> ClauseResult:
    """Stream every retained `part` and `asset` blob and compare the hash to the row and the path.

    Three failures, reported apart because they have three different remedies:

    1. `store_ref` and `sha256` disagree **inside one row** -- the reference names a different
       object from the column beside it. `blobs.parse_ref` is the parser and refuses a malformed
       reference by grammar (it is the path-confinement boundary, `blobs.py:171`), so a
       hand-edited row cannot make this clause open an arbitrary file.
    2. the object is **missing** -- *"a CAS blob is missing"* (07:3183), `store_ref IS NOT NULL`
       with nothing behind it.
    3. the bytes **hash to something else** -- *"a CAS blob's bytes changed"* (07:3184). The hash
       is taken over what is on disk and compared against the ROW, which is the whole point of
       16-roadmap.md:435: `blobs.verify()` re-hashes an object against *its own name* and can
       therefore never catch a row whose `sha256` was edited.

    UNCHECKED without a `BlobStore`, and UNCHECKED is not a pass: see the module docstring.
    """
    rows = list(_cas_rows(connection))
    if blobs is None:
        return _unchecked(
            VerifyClause.CAS_DIGEST,
            f"{len(rows)} retained blobs and no CAS supplied, so their bytes cannot be re-hashed",
        )
    findings: list[Finding] = []
    for table, where, sha256, store_ref in rows:
        try:
            referenced = parse_ref(store_ref)
        except UsageError as exc:
            findings.append(Finding(VerifyClause.CAS_DIGEST, _STORE, where, str(exc)))
            continue
        if referenced != sha256:
            findings.append(
                Finding(
                    VerifyClause.CAS_DIGEST,
                    _INTEGRITY,
                    where,
                    f"{table}.sha256 is {sha256.hex()} but store_ref names {referenced.hex()}",
                )
            )
        if not blobs.has(referenced):
            findings.append(
                Finding(
                    VerifyClause.CAS_DIGEST,
                    _INTEGRITY,
                    where,
                    f"no CAS object at {store_ref}: the row is dangling",
                )
            )
            continue
        actual = _hash_blob(blobs, referenced)
        if actual != referenced:
            findings.append(
                Finding(
                    VerifyClause.CAS_DIGEST,
                    _INTEGRITY,
                    where,
                    f"the object at {store_ref} hashes to {actual.hex()}: its bytes changed",
                )
            )
        elif actual != sha256:
            findings.append(
                Finding(
                    VerifyClause.CAS_DIGEST,
                    _INTEGRITY,
                    where,
                    f"{table}.sha256 is {sha256.hex()} but the stored bytes hash to {actual.hex()}",
                )
            )
    return _result(VerifyClause.CAS_DIGEST, len(rows), findings)


def _cas_rows(connection: sqlite3.Connection) -> Iterable[tuple[str, str, bytes, str]]:
    """`(table, where, sha256, store_ref)` for every row whose bytes were retained.

    `part.store_ref` is nullable -- *"NULL => bytes were not retained"* -- and a NULL is a
    retention decision, never a fault, so those rows are not subjects here. `asset.store_ref` is
    `NOT NULL` (*"NO INLINE BYTES, EVER"*), so every asset row is one.
    """
    for row in connection.execute(
        "SELECT doc_ord, path, sha256, store_ref FROM part WHERE store_ref IS NOT NULL"
    ):
        yield "part", f"part d{int(row[0])}:{row[1]}", bytes(row[2]), str(row[3])
    for row in connection.execute("SELECT asset_id, sha256, store_ref FROM asset"):
        yield "asset", f"asset {int(row[0])}", bytes(row[1]), str(row[2])


def _hash_blob(blobs: BlobStore, digest: bytes) -> bytes:
    """sha256 over the object's bytes, streamed. The bytes are never resident."""
    hasher = hashlib.sha256()
    with blobs.open(digest) as handle:
        while chunk := handle.read(1 << 20):
            hasher.update(chunk)
    return hasher.digest()


# --------------------------------------------------------------------------------------------
# Clause 4 -- every `content_sha256`. 16-roadmap.md:435, 05-ingest-and-routing.md:258.
# --------------------------------------------------------------------------------------------


def _content_sha256(connection: sqlite3.Connection) -> ClauseResult:
    """Every `content_sha256` column: its shape, and `unit`'s agreement with `doc.doc_key`.

    **The honest reading of "re-derives every `content_sha256` from stored bytes".** A
    `content_sha256` is *"over the unit's NORMALISED load-bearing bytes"* (`0004_runtime.sql:53`,
    05:258) and those bytes are the **source file**, which is outside the store by construction --
    `[roots] source` is not `[roots] state`. So there is nothing in the database to re-hash, and a
    clause that claimed to re-derive it would be claiming to have read a file it never opened.

    What the store does hold is the *other* digest of the same bytes: `doc.doc_key` is
    *"sha256(NORMALIZED source bytes)[:16]"* (`0001_init.sql:150`) and 05:258 fixes the two as
    hashes of one normalisation -- *"`unit.content_sha256` is over the normalised load-bearing
    bytes; `doc.source_sha256` is the raw bytes"*. So `fromhex(unit.content_sha256)[:16]` **is**
    `doc.doc_key` for the document that unit produced, and 16-roadmap.md:435's "and compares" is
    that comparison. It is guarded on the two rows naming the same normaliser: a unit hashed raw
    (`normalizer IS NULL`, `OW-C-041`) and a document hashed under `pdf_trailer_v1` are two
    different byte streams and their digests are *supposed* to differ.

    Every column literally named `content_sha256` is also shape-checked at 64 lower-case hex
    characters. The columns are discovered through `PRAGMA table_info` rather than listed, so a
    migration that adds a sixth one is covered the day it lands instead of the day someone
    remembers this file.

    A row is named by its **primary key** and never by `rowid`: four of the tables carrying this
    column are `WITHOUT ROWID` (`route_signal`, `cohort_member`, `unit` is `STRICT` with a TEXT
    key), and `SELECT rowid` against one of those raises `no such column: rowid`. The primary key
    is also the name an operator can act on.
    """
    findings: list[Finding] = []
    checked = 0
    for table in _user_tables(connection):
        if "content_sha256" not in _columns(connection, table):
            continue
        key = _primary_key(connection, table)
        columns = ", ".join([*key, "content_sha256"])
        for row in connection.execute(
            f"SELECT {columns} FROM {table} WHERE content_sha256 IS NOT NULL"  # noqa: S608
        ):
            checked += 1
            value = row[-1]
            if not _is_sha256_hex(str(value)):
                named = ", ".join(f"{name}={row[i]!r}" for i, name in enumerate(key))
                findings.append(
                    Finding(
                        VerifyClause.CONTENT_SHA256,
                        _STORE,
                        f"{table}({named})" if key else table,
                        f"content_sha256 is {value!r}, not 64 lower-case hex characters",
                    )
                )
    compared = 0
    if _has_table(connection, "unit"):
        for uri, content, doc_key in connection.execute(
            "SELECT u.unit_uri, u.content_sha256, d.doc_key FROM unit u JOIN doc d "
            "ON d.uri = u.unit_uri WHERE u.content_sha256 IS NOT NULL "
            "AND u.normalizer IS d.normalizer"
        ):
            if not _is_sha256_hex(str(content)):
                continue
            compared += 1
            derived = bytes.fromhex(str(content))[:_DOC_KEY_BYTES]
            if derived != bytes(doc_key):
                findings.append(
                    Finding(
                        VerifyClause.CONTENT_SHA256,
                        _INTEGRITY,
                        str(uri),
                        f"unit.content_sha256 truncates to {derived.hex()} but the document it "
                        f"produced has doc_key {bytes(doc_key).hex()}; one normalisation cannot "
                        f"have two digests (05:258)",
                    )
                )
    return _result(VerifyClause.CONTENT_SHA256, checked, findings, unit_doc_pairs=compared)


def _is_sha256_hex(value: str) -> bool:
    return len(value) == _SHA256_HEX_LEN and set(value) <= _HEX_DIGITS


def _primary_key(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    """The primary-key columns in key order. `table_info`'s `pk` is 1-based; 0 means not a key."""
    rows = [(int(row[5]), str(row[1])) for row in connection.execute(f"PRAGMA table_info({table})")]
    return tuple(name for position, name in sorted(rows) if position > 0)


# --------------------------------------------------------------------------------------------
# Clause 5 -- at most two live generations. 03-document-model.md:2691.
# --------------------------------------------------------------------------------------------


def _generations(connection: sqlite3.Connection) -> ClauseResult:
    """*"the head plus at most one staged. A third would mean a sweep did not run"* (03:2691).

    Counted over `page` and not over `block`, because `page` is what the sweep deletes: 03:2691's
    own next row calls `page` *"the cascade root: deleting 5,000 `page` rows cascades `block`"*.
    A generation whose blocks are tombstoned (`state = 1`) but whose `page` rows are still there
    is precisely the un-swept generation this clause is looking for, and counting live blocks
    would miss it.
    """
    findings: list[Finding] = []
    checked = 0
    for doc_ord, alive, generations in connection.execute(
        "SELECT doc_ord, count(DISTINCT gen), group_concat(DISTINCT gen) FROM page GROUP BY doc_ord"
    ):
        checked += 1
        if int(alive) > MAX_LIVE_GENERATIONS:
            findings.append(
                Finding(
                    VerifyClause.GENERATIONS,
                    _STORE,
                    f"d{int(doc_ord)}",
                    f"{int(alive)} generations are alive ({generations}); at most "
                    f"{MAX_LIVE_GENERATIONS} -- the head plus one staged -- is bounded, so a "
                    f"staged-generation sweep did not run",
                )
            )
    return _result(VerifyClause.GENERATIONS, checked, findings)


# --------------------------------------------------------------------------------------------
# Clause 6 -- the deprecation census. 03-document-model.md:2789.
# --------------------------------------------------------------------------------------------


def _retired_occurrences() -> ClauseResult:
    """*"counts remaining occurrences so a corpus owner can see when they hit zero"* (03:2789).

    A **census**, not a verdict: 03:2785-2792's phase 2 is "writers stop, readers still read",
    and a surviving occurrence at that phase is expected. Zero is the milestone, not the
    requirement, so this clause reports counts and never fails on a non-zero one.

    UNCHECKED today, and the reason is a file that does not exist. 03:2792 makes the retirement
    register `tools/wirekeys.toml` -- *"the wire key is moved to `tools/wirekeys.toml`'s
    `retired` table and is never reused"* -- and there is no such file in the tree; `enum_val`
    carries no retired flag either, so nothing in the store says which key or which ordinal has
    been retired. Answering "zero occurrences" against an empty question would be a rubber stamp
    of exactly the kind `ClauseState.UNCHECKED` exists to refuse.
    """
    return _unchecked(
        VerifyClause.RETIRED_OCCURRENCES,
        "the retirement register 03:2792 names (`tools/wirekeys.toml`, `retired`) does not exist "
        "and `enum_val` carries no retired flag, so there is no set of retired things to count",
    )


# --------------------------------------------------------------------------------------------
# Clause 7 -- `block_link.via_entity`. 07-store-and-retrieval.md:590.
# --------------------------------------------------------------------------------------------


def _via_entity(connection: sqlite3.Connection) -> ClauseResult:
    """Every non-NULL `block_link.via_entity` names a row in `entity`.

    *"DELIBERATELY NO FOREIGN KEY; `ow store verify` checks it instead"* (`0003_index.sql:307-315`,
    07:590). The column is the one place in the schema where referential integrity is a clause
    here rather than a constraint there, so this clause is not belt-and-braces over an FK -- it
    is the only enforcement that exists.

    The DDL's own note records that the stated *reason* for the absent FK is stale under the
    shipped numbering (`entity` is created in `0002`, one file **earlier** than `block_link`).
    The decision stands as printed and so does this clause; only the justification needs
    rewriting, and it is not this file's to rewrite.
    """
    if not _has_table(connection, "block_link") or not _has_table(connection, "entity"):
        return _unchecked(VerifyClause.VIA_ENTITY, "this store has no `block_link` table")
    checked = int(
        connection.execute(
            "SELECT count(*) FROM block_link WHERE via_entity IS NOT NULL"
        ).fetchone()[0]
    )
    findings = [
        Finding(
            VerifyClause.VIA_ENTITY,
            _STORE,
            f"block_link {int(link_id)}",
            f"via_entity is {int(via)} and no `entity` row has that entity_id; the column "
            f"carries no foreign key, so nothing else would have caught this",
        )
        for link_id, via in connection.execute(
            "SELECT link_id, via_entity FROM block_link WHERE via_entity IS NOT NULL "
            "AND via_entity NOT IN (SELECT entity_id FROM entity)"
        )
    ]
    return _result(VerifyClause.VIA_ENTITY, checked, findings)


# --------------------------------------------------------------------------------------------
# Clause 8 -- `cover_bits` is exactly 64 bytes. 06-structure-extraction.md:779.
# --------------------------------------------------------------------------------------------


def _cover_bits(connection: sqlite3.Connection) -> ClauseResult:
    """*"`LENGTH(cover_bits) <> 64` is a corrupt store and `ow store verify` says so"* (06:779).

    The blob is one bit per block in `segment_block.ord` order and is sized on the **ceiling**
    (`MAX_SEGMENT_BLOCKS / 8`) rather than on the segment, so a short blob is not a compact
    encoding of a small segment -- it is a bitmap whose high bits are missing, and 06:768's
    `cheaper & member` then reads zeros for blocks that are covered. GR2's *"zero billed items on
    covered ground"* rests on the bitmap being complete, so a wrong length is a re-bill and not a
    cosmetic defect.

    `LENGTH()` over a BLOB is a byte count in SQLite, which is what the plan's expression means;
    the same expression over TEXT would be characters, and `cover_bits` is `BLOB NOT NULL`.
    """
    if not _has_table(connection, "derive_cover"):
        return _unchecked(VerifyClause.COVER_BITS, "this store has no `derive_cover` table")
    checked = int(connection.execute("SELECT count(*) FROM derive_cover").fetchone()[0])
    findings = [
        Finding(
            VerifyClause.COVER_BITS,
            _STORE,
            f"derive_cover segment {int(segment_id)} lane {lane} run {int(run_id)}",
            f"cover_bits is {int(size)} bytes, not {COVER_BITS_BYTES}: the bitmap is not "
            f"ceil(MAX_SEGMENT_BLOCKS/8) and a missing high bit reads as uncovered ground",
        )
        for segment_id, lane, run_id, size in connection.execute(
            "SELECT segment_id, lane, run_id, length(cover_bits) FROM derive_cover "
            "WHERE length(cover_bits) <> ?",
            (COVER_BITS_BYTES,),
        )
    ]
    return _result(VerifyClause.COVER_BITS, checked, findings)


# --------------------------------------------------------------------------------------------
# Clause 9 -- SCHEMA is single-homed. 07:3199-3211, ST23, 11:1196-1202, ADR-9 decision 4.
# --------------------------------------------------------------------------------------------


def _single_home(connection: sqlite3.Connection) -> ClauseResult:
    """`meta` holds no `schema` key, no other table carries one, and `index_state` holds one row.

    07:3203-3211, printed as a three-line pseudocode block, plus ST24's row count:

    ```text
    single_homedness:
      1. `meta` holds no row with k = 'schema'.
      2. No [SOR] table other than `index_state` carries a `schema` key or column
         (`meta`-shaped tables by k; every other table by PRAGMA table_info).
      breach => OW-S-034 / OW_SCHEMA_SECOND_HOME, naming the offending table and the key.
    ```

    **It is an absence check and not a comparison** (07:3207): with one home there is nothing to
    compare, and the defect it guards -- *"a migration that writes one and not the other"* -- can
    only recur as a second home reappearing.

    Two implementation notes on the printed text:

    * a **`meta`-shaped** table is any table whose columns are exactly `(k, v)`, which is how
      07:3205 says to tell them apart ("by k"), so `index_state`'s sibling shape is detected
      structurally rather than by a hard-coded list of two names. The key check has **no**
      exemption: rule 1 is absolute.
    * every table is scanned for a `schema` **column**, `[SOR]` or not, minus
      `_SCHEMA_COLUMN_EXEMPT`. Scanning only the `[SOR]` set is not implementable -- the
      classification lives in `-- [SOR]` DDL comments, which `_strip_sql_comments` removes and
      which are not a definition site anyway -- and a `schema` column on a `[DER]` table would
      be a second home an operator reads just as readily. Scanning everything found exactly one
      false positive, `run.schema`, whose DDL excuses it in as many words; that excusal is
      transcribed into `_SCHEMA_COLUMN_EXEMPT` and pinned by a test, so the next such column
      fails this clause on a clean store rather than being waved through.

    The **value** is not compared with `contract.SCHEMA_STRING`. That assertion is G27(b)'s, at
    the end of a migration run over an empty file (ST24, 11:1196-1202); a store legitimately on
    an older schema is `OW-S-030`'s business at open, not a corruption. `tools/gate_migrations.py`
    makes the same absence assertion against a freshly migrated file, and this clause is that
    assertion *"on a real store rather than comparing two copies"* (11:1202).
    """
    findings: list[Finding] = []
    checked = 0
    for table in _user_tables(connection):
        if table == _SCHEMA_HOME:
            continue
        columns = _columns(connection, table)
        if _SCHEMA_KEY in columns and table not in _SCHEMA_COLUMN_EXEMPT:
            findings.append(
                Finding(
                    VerifyClause.SINGLE_HOME,
                    _SECOND_HOME,
                    f"{table}.{_SCHEMA_KEY}",
                    f"{table} carries a `{_SCHEMA_KEY}` column; the sole disk home is "
                    f"`{_SCHEMA_HOME}.{_SCHEMA_KEY}` (ADR-9). Two homes that disagree is a "
                    f"misread file no operator can detect",
                )
            )
        if tuple(columns) != ("k", "v"):
            continue
        checked += 1
        query = f"SELECT v FROM {table} WHERE k = ?"  # noqa: S608
        for (value,) in connection.execute(query, (_SCHEMA_KEY,)):
            findings.append(
                Finding(
                    VerifyClause.SINGLE_HOME,
                    _SECOND_HOME,
                    f"{table}.k = '{_SCHEMA_KEY}'",
                    f"{table} holds a `{_SCHEMA_KEY}` key ({value!r}); the sole disk home is "
                    f"`{_SCHEMA_HOME}.{_SCHEMA_KEY}` (ADR-9 decision 3, ST23)",
                )
            )
    if _has_table(connection, _SCHEMA_HOME):
        checked += 1
        stamps = [
            str(row[0])
            for row in connection.execute(
                f"SELECT v FROM {_SCHEMA_HOME} WHERE k = ?",  # noqa: S608
                (_SCHEMA_KEY,),
            )
        ]
        if len(stamps) != 1:
            findings.append(
                Finding(
                    VerifyClause.SINGLE_HOME,
                    _SECOND_HOME,
                    f"{_SCHEMA_HOME}.k = '{_SCHEMA_KEY}'",
                    f"{_SCHEMA_HOME} holds {len(stamps)} rows keyed `{_SCHEMA_KEY}` ({stamps}); "
                    f"ST24 requires exactly one, and a second row is a second answer",
                )
            )
    return _result(VerifyClause.SINGLE_HOME, checked, findings)


# --------------------------------------------------------------------------------------------
# Clauses 10 and 11 -- FTS. 07-store-and-retrieval.md:418, ST21 at :3260.
# --------------------------------------------------------------------------------------------

_FTS_SUBJECTS: Final = (("block_fts", "text"), ("head_fts", "label"), ("block_tri", "text"))
"""The FTS-bearing tables and the `block` column each indexes.

`block_tri` exists only when `[retrieval] trigram = true` (07 section 3.4), so its absence is
normal and not a finding; `head_fts` arrives with `0003_index.sql`.
"""


def _fts_integrity(connection: sqlite3.Connection) -> ClauseResult:
    """*"`ow store verify --fts` runs `integrity-check`"* on every FTS-bearing table (07:418).

    **The DEFAULT form is run and the `rank = 1` form is not, and that is measured rather than
    chosen.** FTS5 spells the check `INSERT INTO t(t) VALUES('integrity-check')`, which verifies
    that the index is internally consistent, and `INSERT INTO t(t, rank) VALUES(...,1)`, which
    additionally requires the index to match the **whole** external content table. The shipped
    triggers deliberately do not index the whole content table -- `0001_init.sql:505-508`'s two
    guards skip `state <> 0` and `text IS NULL`, and 03:2432-2447 is normative for them -- so
    every legitimate omniweave store has content rows with no posting *by design*. Measured on
    SQLite 3.43.1 over a store holding one container (`text IS NULL`) and one paragraph: the
    default reports ok and `rank = 1` raises `database disk image is malformed` on both
    `block_fts` and `head_fts`. A clause that ran `rank = 1` would fail every store in the
    fleet, which is `test_store_verify.py`'s pinned evidence.

    The default form does not, on its own, see an orphaned posting -- also measured. That is
    `_fts_rowcount`'s clause, and the two together are 07:418's *"runs `integrity-check` ... plus
    `SELECT count(*)` against the live block count"*: the plan asks for both because neither
    alone is sufficient, and this is which half catches what.

    This clause WRITES -- an FTS5 command is spelled as an `INSERT` -- so on a read-only
    connection it is UNCHECKED rather than failed. That is not a loophole: `SQLITE_READONLY` is
    "nobody checked", and reporting it as a pass is what the third state exists to prevent.
    """
    findings: list[Finding] = []
    checked = 0
    for table, _column in _FTS_SUBJECTS:
        if not _has_table(connection, table):
            continue
        checked += 1
        try:
            connection.execute(f"INSERT INTO {table}({table}) VALUES('integrity-check')")
        except sqlite3.OperationalError as exc:
            if "readonly" in str(exc):
                return _unchecked(
                    VerifyClause.FTS_INTEGRITY,
                    f"integrity-check is an FTS5 INSERT and this connection is read-only: {exc}",
                    checked=checked,
                )
            findings.append(_fts_finding(table, exc))
        except sqlite3.DatabaseError as exc:
            findings.append(_fts_finding(table, exc))
    return _result(VerifyClause.FTS_INTEGRITY, checked, findings)


def _fts_finding(table: str, exc: Exception) -> Finding:
    return Finding(
        VerifyClause.FTS_INTEGRITY,
        _INTEGRITY,
        table,
        f"integrity-check raised {type(exc).__name__}: {exc}. "
        f"The lexical Channel reports UNAVAILABLE(fts_corrupt) and degrades (07:3187); "
        f"`{_FIX_REPAIR}` step 2 is the remedy",
    )


def _fts_rowcount(connection: sqlite3.Connection) -> ClauseResult:
    """*"compares `SELECT count(*) FROM block_fts` against the live block count"* (07:418) -- as a
    comparison of the two rowid SETS, because the count the plan prints is vacuous.

    **Measured, on SQLite 3.43.1.** For an external-content FTS5 table a scan that needs no index
    is answered out of the **content** table, so `SELECT count(*) FROM block_fts` returns the
    number of `block` rows whatever the index holds: with three postings and zero blocks it
    returns zero, and the plan's comparison passes over a completely orphaned index. The
    comparison is therefore made against `fts5vocab(main, <table>, 'instance')`, which reads the
    index itself, and it reports both directions -- a posting whose block is gone (ST21's
    orphan) and a live block with no posting (a repopulate that did not finish, which is what
    `index_state.fts_state = 'stale'` records). The counts the plan asks for are in `counts`.

    The vocab table is created in **`temp`**, so `main` is not modified and the clause runs
    against a read-only connection; it is dropped again in a `finally`.
    """
    findings: list[Finding] = []
    checked = 0
    counts: dict[str, int] = {}
    for table, column in _FTS_SUBJECTS:
        if not _has_table(connection, table):
            continue
        checked += 1
        try:
            indexed = _indexed_rowids(connection, table)
        except sqlite3.DatabaseError as exc:
            return _unchecked(
                VerifyClause.FTS_ROWCOUNT,
                f"fts5vocab over {table} is unavailable in this SQLite build: {exc}",
                checked=checked,
            )
        live = {
            int(row[0])
            for row in connection.execute(
                f"SELECT block_id FROM block WHERE state = 0 AND {column} IS NOT NULL"  # noqa: S608
            )
        }
        counts[f"{table}_indexed"] = len(indexed)
        counts[f"{table}_live"] = len(live)
        findings.extend(_fts_set_findings(table, indexed, live))
    return _result(VerifyClause.FTS_ROWCOUNT, checked, findings, **counts)


def _fts_set_findings(table: str, indexed: frozenset[int], live: frozenset[int]) -> list[Finding]:
    findings: list[Finding] = []
    orphans = sorted(indexed - live)
    missing = sorted(live - indexed)
    if orphans:
        findings.append(
            Finding(
                VerifyClause.FTS_ROWCOUNT,
                _INTEGRITY,
                table,
                f"{len(orphans)} postings survive their block (first: {orphans[:8]}). An "
                f"external-content index whose content lookup finds nothing returns wrong "
                f"results; `{_FIX_REPAIR}` step 2 rebuilds it (ST21)",
            )
        )
    if missing:
        findings.append(
            Finding(
                VerifyClause.FTS_ROWCOUNT,
                _INTEGRITY,
                table,
                f"{len(missing)} live blocks have no posting (first: {missing[:8]}). A missing "
                f"posting is indistinguishable from an absent phrase, so the index is "
                f"incomplete rather than merely stale; `{_FIX_REPAIR}` step 2 is the remedy",
            )
        )
    return findings


def _indexed_rowids(connection: sqlite3.Connection, table: str) -> frozenset[int]:
    """The rowids the FTS INDEX actually holds, read through a TEMP `fts5vocab` shadow.

    `fts5vocab`'s three-argument form takes the database name, so the shadow can live in `temp`
    and leave `main` byte-identical -- which is what lets a verify run against a read-only store
    without a schema write. Dropped in `finally` so a second clause, or a second call, does not
    find it there.
    """
    connection.execute(f"DROP TABLE IF EXISTS temp.{_VOCAB_TABLE}")
    connection.execute(
        f"CREATE VIRTUAL TABLE temp.{_VOCAB_TABLE} USING fts5vocab(main, {table}, 'instance')"
    )
    try:
        return frozenset(
            int(row[0])
            for row in connection.execute(
                f"SELECT DISTINCT doc FROM temp.{_VOCAB_TABLE}"  # noqa: S608
            )
        )
    finally:
        connection.execute(f"DROP TABLE IF EXISTS temp.{_VOCAB_TABLE}")


# --------------------------------------------------------------------------------------------
# Clause 12 -- the entity closure. 06-structure-extraction.md:2394.
# --------------------------------------------------------------------------------------------


def _graph_closure(connection: sqlite3.Connection) -> ClauseResult:
    """*"recomputes the closure from the log and byte-compares"* (06:2394, GR6's CI check).

    The log is `entity_merge`; the derived value is `entity.canonical_id`, which
    `0002_graph.sql:456-458` defines as *"the path-compressed union-find closure over polarity=+1
    rows, honouring polarity=-1 as a blocking pair"*. This clause recomputes the **partition** --
    the connected components of the live positive pairs -- and asserts three things about the
    stored column:

    1. every member of a component shares one `canonical_id`;
    2. a `canonical_id` is itself canonical (`canonical_id(canonical_id(e)) == canonical_id(e)`),
       which is what "closure" means and what a stale half-recompute breaks first;
    3. no live `polarity = -1` pair -- a **user split**, the one construct that survives a later
       automatic merge -- shares a `canonical_id`.

    **What it deliberately does not recompute is which member wins.** The survivor rule is
    `min(merge_hops, -len(alias_set), key)` over a total order stated at 06:1735-1760, and it
    belongs to `op.resolve`; re-deriving it here would put a second implementation of L3's
    resolver inside the store's verifier, which is the second home INV-21 forbids. The partition
    is the part of the closure that is a *fact about the log*, and it is the part a stale
    `canonical_id` gets wrong.
    """
    if not _has_table(connection, "entity") or not _has_table(connection, "entity_merge"):
        return _unchecked(VerifyClause.GRAPH_CLOSURE, "this store has no `entity` table")
    canonical = {
        int(row[0]): int(row[1])
        for row in connection.execute("SELECT entity_id, canonical_id FROM entity")
    }
    parent: dict[int, int] = {}
    positive = [
        (int(row[0]), int(row[1]))
        for row in connection.execute(
            "SELECT loser_id, winner_id FROM entity_merge "
            "WHERE polarity = 1 AND retired_at_gen IS NULL"
        )
    ]
    for loser, winner in positive:
        _union(parent, loser, winner)
    findings: list[Finding] = []
    for entity_id, canon in sorted(canonical.items()):
        if canonical.get(canon, canon) != canon:
            findings.append(
                Finding(
                    VerifyClause.GRAPH_CLOSURE,
                    _STORE,
                    f"e{entity_id}",
                    f"canonical_id {canon} is itself merged away into "
                    f"{canonical.get(canon)}: the closure was not path-compressed",
                )
            )
    for loser, winner in positive:
        if canonical.get(loser) != canonical.get(winner):
            findings.append(
                Finding(
                    VerifyClause.GRAPH_CLOSURE,
                    _STORE,
                    f"e{loser}/e{winner}",
                    f"a live positive entity_merge row joins them, but their canonical_ids are "
                    f"{canonical.get(loser)} and {canonical.get(winner)}: the stored closure "
                    f"does not match the log",
                )
            )
    for loser, winner in connection.execute(
        "SELECT loser_id, winner_id FROM entity_merge "
        "WHERE polarity = -1 AND retired_at_gen IS NULL"
    ):
        if canonical.get(int(loser)) == canonical.get(int(winner)):
            findings.append(
                Finding(
                    VerifyClause.GRAPH_CLOSURE,
                    _STORE,
                    f"e{int(loser)}/e{int(winner)}",
                    "a polarity=-1 row forbids this merge and the two share a canonical_id: a "
                    "human split was overwritten by a later automatic merge",
                )
            )
    return _result(
        VerifyClause.GRAPH_CLOSURE, len(canonical), findings, positive_pairs=len(positive)
    )


def _union(parent: dict[int, int], a: int, b: int) -> None:
    """Union-find with path compression, over ints. Iterative: a chain can be corpus-deep."""
    root_a, root_b = _find(parent, a), _find(parent, b)
    if root_a != root_b:
        parent[max(root_a, root_b)] = min(root_a, root_b)


def _find(parent: dict[int, int], node: int) -> int:
    root = node
    while parent.get(root, root) != root:
        root = parent[root]
    while parent.get(node, node) != node:
        parent[node], node = root, parent[node]
    return root


# --------------------------------------------------------------------------------------------
# Clauses 13 and 14 -- the receipt. 07-store-and-retrieval.md:3150 and :3155.
# --------------------------------------------------------------------------------------------


def _lock_markers(lock_text: str | None) -> ClauseResult:
    """*"refuses any file containing `<<<<<<<`, `=======` or `>>>>>>>` with `OW-S-061`"* (07:3150).

    The detector is `indexlock.has_conflict_markers`, not a second regex here: the marker
    grammar is the merge driver's and lives with it. This clause is the refusal, which is a
    different thing from the detection -- *"an unresolved merge cannot be mistaken for a valid
    receipt"* (07:3149), and ST19 at :3253 and D-03 at 15:1516 both name the numeral it carries.

    `OW-S-061` has no `codes.toml` row, so the numeral is carried literally. See
    `_CONFLICT_MARKER_CODE`.
    """
    if lock_text is None:
        return _unchecked(VerifyClause.LOCK_MARKERS, f"no {LOCK_PATH} text was supplied to verify")
    if has_conflict_markers(lock_text):
        return _result(
            VerifyClause.LOCK_MARKERS,
            1,
            [
                Finding(
                    VerifyClause.LOCK_MARKERS,
                    _CONFLICT_MARKER_CODE,
                    LOCK_PATH,
                    f"the receipt contains a git conflict marker and is refused: an unresolved "
                    f"merge is not a valid receipt. Resolve it or rerun `{_FIX_LOCK}`",
                )
            ],
        )
    return _passed(VerifyClause.LOCK_MARKERS, 1)


def _lock_store_match(
    connection: sqlite3.Connection, lock_text: str | None, uri_root: str | None = None
) -> ClauseResult:
    """*"`ow store verify --lock` re-derives it from the store and compares"* (07:3155).

    The comparison is over **rendered lines**, byte for byte, because that is what the receipt
    is: a committed text artefact whose diff a reviewer reads (07:3156-3158). Comparing parsed
    values would let two spellings of one number compare equal and hide the drift the file
    exists to show -- the same argument the merge driver makes for treating a row as opaque text
    (07:3132).

    **The header is compared on the two fields the store actually holds.** `schema` and `scorer`
    come from `index_state`; `segmenter` and `space` are *"opaque tokens owned elsewhere"*
    (`indexlock`'s docstring, INV-21) with no rendering in this tree and no row in a P2 store, so
    they are carried through from the file rather than re-derived, and the clause says so in
    `counts`. Inventing a rendering here would be a second home for two facts.
    """
    if lock_text is None:
        return _unchecked(
            VerifyClause.LOCK_STORE_MATCH, f"no {LOCK_PATH} text was supplied to verify"
        )
    if has_conflict_markers(lock_text):
        return _unchecked(
            VerifyClause.LOCK_STORE_MATCH,
            f"{LOCK_PATH} is refused for its conflict markers, so it was not compared",
        )
    try:
        on_disk = read_lock(lock_text)
    except StoreError as exc:
        return _result(
            VerifyClause.LOCK_STORE_MATCH,
            0,
            [Finding(VerifyClause.LOCK_STORE_MATCH, _STORE, LOCK_PATH, str(exc))],
        )
    derived = derive_lock(connection, header=on_disk.header, uri_root=uri_root)
    findings = list(_compare_lock(on_disk, derived))
    return _result(
        VerifyClause.LOCK_STORE_MATCH,
        len(derived.rows),
        findings,
        rows_on_disk=len(on_disk.rows),
    )


def _compare_lock(on_disk: LockFile, derived: LockFile) -> Iterable[Finding]:
    """Line-by-line, keyed on `doc_key` hex, which is the receipt's own sort key."""
    if on_disk.header.render() != derived.header.render():
        yield Finding(
            VerifyClause.LOCK_STORE_MATCH,
            _STORE,
            f"{LOCK_PATH} header",
            f"the receipt says {on_disk.header.render()!r} and the store derives "
            f"{derived.header.render()!r}",
        )
    theirs = {row.doc_key.hex(): row for row in on_disk.rows}
    ours = {row.doc_key.hex(): row for row in derived.rows}
    for key in sorted(set(theirs) | set(ours)):
        if key not in ours:
            yield Finding(
                VerifyClause.LOCK_STORE_MATCH,
                _STORE,
                key,
                f"the receipt lists this document and the store has no `doc` row for it: "
                f"{theirs[key].render()!r}",
            )
        elif key not in theirs:
            yield Finding(
                VerifyClause.LOCK_STORE_MATCH,
                _STORE,
                key,
                f"the store holds this document and the receipt does not list it: "
                f"{ours[key].render()!r}",
            )
        elif theirs[key].render() != ours[key].render():
            yield Finding(
                VerifyClause.LOCK_STORE_MATCH,
                _STORE,
                key,
                f"the receipt line is {theirs[key].render()!r} and the store derives "
                f"{ours[key].render()!r}",
            )


def derive_lock(
    connection: sqlite3.Connection, *, header: LockHeader, uri_root: str | None = None
) -> LockFile:
    """The `omniweave.index.lock` this store implies. `ow store lock` writes it; verify compares.

    Every column is a stored field (`indexlock`'s FORMAT block enumerates the seven and their
    definition sites), so the receipt is re-derivable without a re-parse:

    * `doc_key`, `gen`, `status` -- the `doc` row.
    * `uri` -- `doc.uri`, with `uri_root` stripped from its front when the caller gives one and
      the uri starts with it. An `fs` document's uri is its canonical ABSOLUTE path, and a receipt
      committed with absolute paths differs on every line between two checkouts of one corpus, so
      the merge driver would see a conflict per document (D591). `uri_root` is the corpus source
      root's `scope_id` form (`acquire.scope_id_for`, trailing `/` included), so a sibling
      `docs2/` is never mistaken for a child of `docs/`. A uri outside the root is kept whole.
    * `n_blocks` -- live blocks at the head generation. `ow_block_head` is the projection that
      means "the head, live" (`0001_init.sql:328-331`) and is used rather than a hand-written
      predicate, so the receipt counts what a reader would see.
    * `n_segments` -- live segments at the head generation, or 0 where `segment` does not exist.
    * the root `content_digest` -- the `document` block's, found by `addr = 'doc'` (03:816). A
      document with no root block yields the 16 zero bytes, which `LockRow.validate` accepts as
      a digest and a reviewer reads as "no root", rather than making the whole receipt
      underivable.

    `header` is the caller's, for the reason `_lock_store_match` documents: two of its four
    fields are owned elsewhere. `index_state`'s `schema` and `scorer_version` override the two
    that the store does hold, so a receipt claiming the wrong scorer is caught.
    """
    header = _store_header(connection, header)
    rows: list[LockRow] = []
    has_segment = _has_table(connection, "segment")
    for doc_ord, doc_key, gen, status, uri in connection.execute(
        "SELECT doc_ord, doc_key, gen, status, uri FROM doc ORDER BY doc_key"
    ):
        n_blocks = int(
            connection.execute(
                "SELECT count(*) FROM ow_block_head WHERE doc_ord = ?", (doc_ord,)
            ).fetchone()[0]
        )
        n_segments = 0
        if has_segment:
            n_segments = int(
                connection.execute(
                    "SELECT count(*) FROM segment WHERE doc_ord = ? AND gen = ? AND state = 0",
                    (doc_ord, gen),
                ).fetchone()[0]
            )
        root = connection.execute(
            "SELECT content_digest FROM block WHERE doc_ord = ? AND gen = ? AND addr = ?",
            (doc_ord, gen, _ROOT_ADDR),
        ).fetchone()
        rows.append(
            LockRow(
                doc_key=bytes(doc_key),
                gen=int(gen),
                status=str(status),
                n_blocks=n_blocks,
                n_segments=n_segments,
                content_digest=bytes(root[0]) if root is not None else bytes(_DOC_KEY_BYTES),
                uri=_receipt_uri(str(uri), uri_root),
            )
        )
    rows.sort(key=lambda row: row.doc_key)
    return LockFile(header=header, rows=tuple(rows))


def _receipt_uri(uri: str, root: str | None) -> str:
    """`doc.uri` as the receipt spells it: relative to `root` when under it, else whole.

    The uri equal to the root with its slash is not "under" it -- a document is a file, never the
    root -- so a strip that would leave the empty string (which `LockRow.validate` refuses) keeps
    the uri whole instead.
    """
    if root and uri.startswith(root) and len(uri) > len(root):
        return uri[len(root) :]
    return uri


def _store_header(connection: sqlite3.Connection, header: LockHeader) -> LockHeader:
    """The caller's header with the two fields `index_state` actually holds substituted in."""
    if not _has_table(connection, _SCHEMA_HOME):
        return header
    state = {
        str(row[0]): str(row[1])
        for row in connection.execute(f"SELECT k, v FROM {_SCHEMA_HOME}")  # noqa: S608
    }
    schema = state.get(_SCHEMA_KEY, "")
    scorer = state.get("scorer_version", "")
    return LockHeader(
        scorer=int(scorer) if scorer.isdigit() else header.scorer,
        segmenter=header.segmenter,
        space=header.space,
        schema=int(schema.split(".")[0]) if schema.split(".")[0].isdigit() else header.schema,
    )


# --------------------------------------------------------------------------------------------
# Clause 15 -- the erasure cascade. 14-security.md:1205-1210.
# --------------------------------------------------------------------------------------------

_ERASED_REASONS: Final = ("erased:", "redacted:")
"""*"every `block_history` row with an `erased:` or `redacted:` reason"* (14:1205)."""


def _erased_residue(connection: sqlite3.Connection) -> ClauseResult:
    """*"re-derives the cascade ... and fails if any of rows 1 to 11 holds content"* (14:1207).

    The cascade is fourteen locations (14:1190-1204). **Row 1 is checked here and rows 2 to 11
    are not**, and the split is a schema fact rather than a scoping preference: row 1 is keyed on
    `block_id` and is entirely inside `block` and `block_fts`, while rows 2 to 11 are keyed on
    the erased document's `(unit, part)` and are re-derived from the `erasure` row's
    `targets_json` -- the two-phase intent table of 14:1215-1225, which **this schema does not
    create**. Guessing the mapping from a `block_history` row to a `cache_index` key would be
    inventing the erasure protocol inside its own verifier.

    So: a surviving row-1 residue FAILS with `OW_ERASURE_INCOMPLETE` (`OW-S-070`, 14:1208); an
    erased row whose other ten locations cannot be reached leaves the clause UNCHECKED, naming
    the missing table. A store with no erased rows PASSES over zero subjects, which is the state
    every P2 store is in.
    """
    if not _has_table(connection, "block_history"):
        return _unchecked(VerifyClause.ERASED_RESIDUE, "this store has no `block_history` table")
    erased = [
        (int(row[0]), str(row[1]))
        for row in connection.execute("SELECT block_id, reason FROM block_history")
        if str(row[1]).startswith(_ERASED_REASONS)
    ]
    findings: list[Finding] = []
    for block_id, reason in erased:
        row = connection.execute(
            "SELECT cite, text FROM block WHERE block_id = ?", (block_id,)
        ).fetchone()
        if row is not None and row[1] is not None:
            findings.append(
                Finding(
                    VerifyClause.ERASED_RESIDUE,
                    _ERASURE_CODE,
                    str(row[0]),
                    f"block_history says {reason!r} and `block.text` still holds "
                    f"{len(str(row[1]))} characters: cascade location 1 is not clear",
                )
            )
    if findings:
        return _result(VerifyClause.ERASED_RESIDUE, len(erased), findings)
    if erased and not _has_table(connection, "erasure"):
        return _unchecked(
            VerifyClause.ERASED_RESIDUE,
            f"{len(erased)} erased blocks: cascade location 1 is clear, and locations 2 to 11 "
            f"are keyed on the `erasure` row's targets_json (14:1215-1225), which this schema "
            f"does not create",
            checked=len(erased),
        )
    return _passed(VerifyClause.ERASED_RESIDUE, len(erased))


# --------------------------------------------------------------------------------------------
# `ow doc verify` -- reading one generation into `owcheck.Generation`
# --------------------------------------------------------------------------------------------


def _generation(connection: sqlite3.Connection, doc_ord: int, gen: int) -> Generation:
    """One generation as `owcheck` wants it: facts, `rel` edges, grids and the retained parts.

    Four queries and no clause logic. `state` is not filtered: `owcheck`'s parent/`ord` bijection
    is over the generation as written (a tombstoned sibling still occupies its `ord`, which is
    what makes the bijection checkable at all), and 03:1027 says "over the whole generation".

    `kind`, `layer` and `rel.kind` are decoded through **`enum_val`**, the store's own registry,
    exactly as `SqliteReader._member` does and for its reason: *"reading the ordinals off the
    Python enums instead would make a store built by an older `enum_val` seed answer with this
    build's numbering, which is exactly the drift `enum_val` exists to make impossible"*
    (`reader.py:394-396`). `Kind` and `Layer` are `StrEnum`s, so an ordinal is not even a valid
    value for them. `quote` is not decoded that way: it is an ordered `IntEnum` whose *"ord IS
    the member's integer"* (`0001_init.sql:114`), which is what makes `min()` over a segment
    return the weakest member.
    """
    kinds = _enum_names(connection, "kind")
    layers = _enum_names(connection, "layer")
    rel_kinds = _enum_names(connection, "rel_kind")
    blocks = [
        BlockFacts(
            addr=Addr(str(row[0])),
            page=int(row[1]),
            ord=int(row[2]),
            kind=Kind(_name(kinds, int(row[3]), "kind")),
            layer=Layer(_name(layers, int(row[4]), "layer")),
            quote=Quote(int(row[5])),
            origin_part=None if row[6] is None else str(row[6]),
        )
        for row in connection.execute(
            "SELECT addr, page, ord, kind, layer, quote, os_part FROM block "
            "WHERE doc_ord = ? AND gen = ? ORDER BY page, ord",
            (doc_ord, gen),
        )
    ]
    rels = [
        (Addr(str(row[0])), Addr(str(row[1])), RelKind(_name(rel_kinds, int(row[2]), "rel_kind")))
        for row in connection.execute(
            "SELECT s.addr, d.addr, r.kind FROM rel r "
            "JOIN block s ON s.block_id = r.src_id JOIN block d ON d.block_id = r.dst_id "
            "WHERE r.doc_ord = ? AND r.gen = ?",
            (doc_ord, gen),
        )
    ]
    retained = frozenset(
        str(row[0])
        for row in connection.execute(
            "SELECT path FROM part WHERE doc_ord = ? AND store_ref IS NOT NULL", (doc_ord,)
        )
    )
    known = bool(
        connection.execute("SELECT count(*) FROM part WHERE doc_ord = ?", (doc_ord,)).fetchone()[0]
    )
    return Generation(
        blocks=blocks,
        rels=rels,
        grids=tuple(_grids(connection, doc_ord, gen)),
        retained_parts=retained,
        parts_known=known,
    )


def _enum_names(connection: sqlite3.Connection, domain: str) -> Mapping[int, str]:
    """`{ord: member name}` for one `enum_val` domain, read off the store and not off Python."""
    return {
        int(row[0]): str(row[1])
        for row in connection.execute("SELECT ord, name FROM enum_val WHERE domain = ?", (domain,))
    }


def _name(domain: Mapping[int, str], code: int, what: str) -> str:
    """The member name for `code`, refusing a code the store's own `enum_val` cannot explain.

    Refused rather than guessed, which is `SqliteReader._member`'s rule: a stored code with no
    `enum_val` row means the seed and the rows disagree, and a guessed member would put a wrong
    `Kind` into a report an operator acts on.
    """
    name = domain.get(code)
    if name is None:
        raise StoreError(
            f"this store holds {what} code {code}, which its own enum_val does not name: the "
            f"seed and the rows disagree, and a guessed member would reach a verify report",
            fix=_FIX_REPAIR,
        )
    return name


def _grids(connection: sqlite3.Connection, doc_ord: int, gen: int) -> Iterable[GridRow]:
    """`table_meta` plus its origin `cell` geometry, as `owcheck`'s grid clause reads it.

    `grid_slot` is deliberately not read: 03:2467 classifies it `[DER]` and the clause exists
    precisely to check the origin cells rather than the materialised cover map, because *"a
    rebuild of a wrong cover map produces a consistent wrong cover map"* (`owcheck`'s clause 2).

    `table_meta.kind` is an ordinal into the `table_kind` domain and `GridRow.kind` is the name,
    so it is decoded through `enum_val` -- the store's own name-to-ord registry -- and never
    through a literal pair here.
    """
    kinds = {
        int(row[0]): str(row[1])
        for row in connection.execute("SELECT ord, name FROM enum_val WHERE domain = 'table_kind'")
    }
    for row in connection.execute(
        "SELECT t.block_id, b.addr, t.n_rows, t.n_cols, t.row_len, t.header_rows, t.header_cols, "
        "t.kind, t.recon_strategy, t.recon_score, t.has_merges, t.native_part, t.native_sha256 "
        "FROM table_meta t JOIN block b ON b.block_id = t.block_id "
        "WHERE b.doc_ord = ? AND b.gen = ?",
        (doc_ord, gen),
    ):
        cells = tuple(
            (int(c[0]), int(c[1]), int(c[2]), int(c[3]))
            for c in connection.execute(
                "SELECT r, c, row_span, col_span FROM cell WHERE table_id = ? ORDER BY r, c",
                (int(row[0]),),
            )
        )
        yield GridRow(
            table=Addr(str(row[1])),
            n_rows=int(row[2]),
            n_cols=int(row[3]),
            row_len=tuple(int(n) for n in json.loads(str(row[4]))),
            kind=kinds.get(int(row[7]), str(row[7])),
            cells=cells,
            header_rows=int(row[5]),
            header_cols=int(row[6]),
            recon_strategy=None if row[8] is None else str(row[8]),
            recon_score=None if row[9] is None else float(row[9]),
            has_merges=bool(row[10]),
            native_part=None if row[11] is None else str(row[11]),
            native_sha256=None if row[12] is None else bytes(row[12]).hex(),
        )
