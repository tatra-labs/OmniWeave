"""`ow store diff`, `ow store explain`, `ow store residue` -- the three read-only report verbs.

Three functions, three reports, no writes. Each is named after the `ow store` verb that will
call it at P7 (16-roadmap.md section 10); none of them parses an argument, opens a file or
prints, because the CLI does not exist yet and `tools/schemagen.py`'s docstring already fixes
the house answer for that ("`ow schema emit` before `ow` exists"). The fourth verb of W2.7,
`ow store export --portable`, is `omniweave_core.store.portable` -- see the note at the end of
this docstring for why it is a second module.

WHAT EACH VERB IS, AND THE LINE THAT FIXES IT
----------------------------------------------
* **`diff`** -- 07-store-and-retrieval.md:3155-3157: *"`ow store lock` writes it; `ow store
  verify --lock` re-derives it from the store and compares; `ow store diff` shows what an ingest
  changed. Committing the receipt gives a reviewer a diff that says 'these four documents were
  re-parsed and this one was removed'"*. The unit of the output is therefore a DOCUMENT, and the
  input is `omniweave.index.lock` -- which `store/indexlock.py` already reads, writes and merges.
  `diff_lock` is a diff of two receipts and `diff_stores` is that over two stores, through
  `store/verify.py`'s `derive_lock` -- the re-derivation the same sentence gives
  `ow store verify --lock`. `lock_rows` here is a delegation to it and not a second reading of
  the seven columns; see its docstring for why that matters more than the import it costs.

* **`explain`** -- 07:954-1006, section 3.13, the index register. ST17 (07:956, restated at
  07:3251 and 12-performance.md:1679): *"every shipped index is named in `tools/indexes.toml` with
  the statement it serves, and `ow store explain --golden` is byte-diff gated. An index whose
  statement no longer exists is deleted in the same PR; an index that appears in `sqlite_master`
  without a register row fails CI."* Byte-diff gated is the whole design constraint:
  `ExplainReport.render()` is sorted, LF-only and carries no clock, no path and no row count.

* **`residue`** -- 07:552-554: *"`ow store residue` prints `ref_unresolved` grouped by
  `name_norm`: **the residue is data, not a log line.**"*; 05-ingest-and-routing.md:816-819: the
  child units of a container *"count against `unit.derived["container_bytes"]`, which is what
  `ow store residue` reads to find a corpus that is 90% zip members"*; and 01-principles.md:796,
  INV-25: *"residue grows without bound -- `route_signal`, `quarantine`, `ref_attempt`,
  `block_history`"*, defended by `clear_old_permanent(30d)`, the `cache_index` sweep and every
  ceiling at `take(N+1)`. Three definition sites, one report: `ResidueReport` carries the four
  INV-25 tables with counts and ages, the `ref_unresolved` groups, and the container share.

THE CLOCK, AND WHY `residue` TAKES ONE
---------------------------------------
`time.time` and `datetime.now` are banned in library code, and the store takes the clock from its
caller everywhere already (`migrate.apply_pending(conn, *, now_ns)`, `SqliteReader(conn, *,
now_ns)`). `residue(connection, *, now_ns)` is the same seam: an age is `now_ns` minus a stored
stamp, and a report that read the ambient clock could not be reproduced from the store's bytes.
`diff` and `explain` take no clock at all -- neither output contains a time, which for `explain`
is what makes the golden form diffable and for `diff` is 01-principles.md:688's "no timestamps".

WHAT AN AGE IS IN THIS STORE -- and it is not always seconds
-------------------------------------------------------------
Of INV-25's four tables, exactly one carries a wall-clock stamp. `route_signal.computed_at` is
`INTEGER NOT NULL` in `0004_runtime.sql:410`, and the file's own convention fixes its unit: the
sibling `route_decision.decided_at` at `:358` is annotated *"wall ms, for humans and the 400-day
sweep ONLY"*, and every nanosecond column in the same file carries an `_ns` suffix
(`mtime_ns`, `indexed_at_ns`, `created_ns`, `last_hit_ns`, `built_ns`, `started_ns`). So `_at`
without a suffix is wall milliseconds, and `MS_PER_NS` converts.

The other three are stamped by GENERATION and not by a clock: `quarantine.at_gen`
(`0002_graph.sql:513`), `block_history.retired_gen` (`0001_init.sql:333`) and
`ref_attempt.last_tried_gen` (`0003_index.sql:265`). An "age" for those is a number of
generations, and `ResidueTable.age_unit` says which of the two a row is denominated in rather
than converting one into the other. **`ref_attempt.ts_a` is NOT a timestamp** -- it is the
`TextSpan` start of the reference occurrence, which `0003_index.sql:215-222` spells out at
length -- and reading it as one would print a plausible age that is a character offset.

WHY THE PROBE QUERIES ARE THIS MODULE'S, AND WHAT THAT COSTS -- see DEFECT 2
-----------------------------------------------------------------------------
`explain` has to run `EXPLAIN QUERY PLAN` over *something*. 07:960-990's register gives each index
an owner, a **Serves** cell that is prose (*"every `cite` resolution, on every surface"*) and a
**Shape** cell that is the index definition. It never prints a statement, and `tools/indexes.toml`
-- the register that 07:956 says holds "the statement it serves" -- does not exist in the tree
(`store/maintenance.py:68` records the same absence for the same register from the other side).
So `RegisteredIndex.probe` is derived from the **Shape** cell mechanically: equality on the
leading key columns, the partial index's own `WHERE` where it has one, and the `ORDER BY` the
Serves cell names. The register's twenty-nine rows, their tables, owners, serves and shapes are
transcribed and are not this module's; only `probe` is, and `test_store_inspect.py` asserts every
transcribed name and owner against `_plan/` so a future edit to the table cannot pass silently.

DEFECTS
--------
**DEFECT 1 -- 07:957 cannot be enforced against 07:960-990's table, because that table is not the
whole register.** ":957" says *"an index that appears in `sqlite_master` without a register row
fails CI"*. Section 3.13's table has twenty-nine rows and says so at 07:994 ("Twenty-nine index
rows"); the four shipped migrations create **seventy-six** indexes, of which twenty-six have a
register row -- `rel_src`, `mark_block`, `entity_rank`, `work_claimable`, `cache_gc`,
`route_decision_slice` and forty-four more are shipped indexes with no row in that table, and
three register rows (`artifact_cite_block`, `retrieval_event_ts`, `retrieval_event_bad`) name
objects no shipped migration creates. So :957's second clause is a rule about `tools/indexes.toml`,
which is corpus-wide and does not exist, and NOT about section 3.13's table, which is the query
path's subset. `explain_indexes` therefore checks the register FORWARD only -- every register row
must resolve to a live index -- and reports the reverse direction as `ExplainReport.unregistered`,
a list, without failing on it. When `tools/indexes.toml` lands, `INDEX_REGISTER` reads it and this
transcription becomes its cross-check (INV-21).

**DEFECT 2 -- the register names no statements.** See the section above. Reported.

**DEFECT 3 -- `anchor_corpus` is dominated by `anchor_name` and the planner proves it.** 07:970-971
registers both: `anchor_corpus` is `(name_norm, akind)` partial `scope = 'corpus'`, `anchor_name`
is `(name_norm, akind, scope, doc_ord)` with no predicate. The second is a superset of the first
with `scope` inside the key, so SQLite chooses `anchor_name` for the corpus-scope probe as well --
verified against a store with all four migrations applied. ST17's headline is *"every shipped index
is used"* (07:3251), and by that test `anchor_corpus` is not. `explain_indexes` reports it as
`unused` rather than as a failure, because the remedy (drop the index, or add `INDEXED BY` to the
corpus-scope query) is the plan owner's and not a report's. `test_store_inspect.py` pins it, so the
day the register changes on either side the test says which.

**DEFECT 4 -- 07:989 gives `dep_reverse` the shape `(kind, key, digest)`; three printed statements
give `(kind, key)`.** Already found and ruled from the other side --
`0004_runtime.sql:190-195` carries the ruling and the count -- and `INDEX_REGISTER` transcribes
the register cell as printed while the probe follows the shipped statement, which is what the
planner has to answer to.

**DEFECT 5 -- 07:1023-1029's `block`-row decomposition covers thirty-four of the table's forty
columns, so its ~324 B subtotal is short by whatever the other five cost.** The seven rows name
`text`; "fixed scalars (~20 small ints)"; `addr` + `cite`; `content_digest` + `layout_digest`;
`quad`; `origin_operator` + `origin_driver` + `os_part` + `os_extractor`; and `x` + `payload` +
`raw_kind`. `0001_init.sql:235-282` declares forty columns, and `label`, `os_path`, `os_codec`,
`score_kind` and `decision_id` appear in no row. They are not free: `os_codec` is `NOT NULL`
wherever `os_kind = 0` (`0001_init.sql:280`) and every text block this framework produces from a
byte origin carries `'utf-8/strict'` in it, thirteen bytes plus a serial byte on every such row --
about 4% of the stated subtotal, from one unlisted column. `store_sizing` reports them as the
`UNLISTED` row with an estimate of `--`, so the gap is visible instead of being folded into the
subtotal, and the total it computes says in `covers` that it includes them.

**DEFECT 6 -- 07:1037's "~636" is the sum of the printed rows and 07:1012's "~338 B/block" is a
measurement of something else, and the section reads as though they were commensurable.** 07:1010
calls 338 *"the measured figure"* and 07:1017 says the decomposition is *"At 660 B/block"*, but
the thirteen rows add to 636, which is neither. Nothing here is wrong arithmetic -- 636 really is
the row sum -- but a reader who takes 338 as the low end of the same quantity the table
decomposes is comparing a whole-file ratio against a hand-built estimate whose FTS and index rows
(07:1031-1033, ~202 B of the 636) may or may not have been in the 338. `store_sizing` reports
both denominators separately (`bytes_per_block` over the file, `record_bytes_per_block` over the
`block` rows alone) so a reviewer can see which one a figure is.

WHY `export --portable` IS A SECOND MODULE
-------------------------------------------
`omniweave_core.store.portable` writes one `.owdoc` per document (07:3092), so it imports
`omniweave_core.archive` and `omniweave_core.model` -- the block codec, the manifest, the frame
index and the enum vocabulary. The three verbs here import neither: a `residue()` caller pays for
`sqlite3`, `store/indexlock.py` and nothing else. Folding the exporter in would put the whole
archive codec behind every report import, which is the same argument `store/__init__.py` makes for
holding no backend and `omniweave_core/__init__.py` makes for the nine lazy names.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final, NamedTuple

from omniweave_core.errors import StoreError
from omniweave_core.store import migrate
from omniweave_core.store.indexlock import LockFile, LockHeader, LockRow, read_lock

__all__ = [
    "BLOCK_INDEXES",
    "CELLS",
    "CELL_KINDS",
    "COMPOSITIONS",
    "DECOMPOSITION",
    "DEFAULT_GROUP_LIMIT",
    "FIXTURE_CAVEAT",
    "INDEX_REGISTER",
    "MACHINE_CAVEAT",
    "MEASURED",
    "MIXED",
    "MS_PER_NS",
    "PARTIAL",
    "PROSE",
    "PROSE_KINDS",
    "RESIDUE_TABLES",
    "SIZING_STATES",
    "SUBTOTAL_ESTIMATE",
    "SUBTOTAL_LINE",
    "TOTAL_ESTIMATE",
    "TOTAL_LINE",
    "UNCHECKED",
    "UNLISTED",
    "ComponentCost",
    "CompositionSize",
    "ContainerShare",
    "DocDelta",
    "ExplainReport",
    "ExplainRow",
    "KindCount",
    "LockDiff",
    "RefGroup",
    "RegisteredIndex",
    "ResidueReport",
    "ResidueTable",
    "SizingReport",
    "StoreFiles",
    "diff_lock",
    "diff_stores",
    "explain_indexes",
    "lock_rows",
    "residue",
    "store_sizing",
]

_FIX_LOCK: Final = "ow store lock"
"""The command a caller runs when a receipt and a store disagree (07:3155)."""

_FIX_EXPLAIN: Final = "ow store explain --golden"
"""The verb whose golden output `explain_indexes` produces (07:956)."""

_FIX_SIZING: Final = "uv run tools/measure_store.py"
"""What a caller runs to reproduce a sizing refusal. There is no `ow store sizing` verb: D25's
standing pattern is a library function plus a `tools/` script now, and a P7 or P10 CLI later
(`tools/gate_crash.py` is the worked example, `tools/schemagen.py` the P1 precedent)."""

MS_PER_NS: Final = 1_000_000
"""Nanoseconds per millisecond. `route_signal.computed_at` is wall ms; `now_ns` is ns."""


# =============================================================================================
# 1. `ow store diff` -- what an ingest changed, in DOCUMENTS.
# =============================================================================================

_DIFF_HEADER: Final = LockHeader(scorer=0, segmenter="ow.diff", space="ow.diff")
"""A placeholder header for `derive_lock`, which returns a whole `LockFile` and needs one.

**It is never rendered and never compared.** `LockHeader`'s `segmenter` and `space` are owned by
`omniweave.toml` and the embed space, not by the store, which is exactly why
`verify.derive_lock` takes the header from its caller (`_store_header` substitutes only the two
fields `index_state` actually holds). `diff_stores` compares documents and 07:3130 makes a header
difference a separate finding, so a diff over two stores has no header to compare and this value
exists only to satisfy the signature. `_TOKEN_RE` in `indexlock` requires printable ASCII, which
is why it is a token and not the empty string.
"""


def lock_rows(connection: sqlite3.Connection) -> tuple[LockRow, ...]:
    """The `omniweave.index.lock` rows this store implies, in `doc_key` byte order.

    **A delegation, not a second derivation** (INV-21). `store/verify.py`'s `derive_lock` is the
    re-derivation `ow store verify --lock` performs -- 07:3155 puts the two verbs in one sentence
    (*"`ow store verify --lock` re-derives it from the store and compares; `ow store diff` shows
    what an ingest changed"*), so they must agree by construction and not by review. Two
    independent readings of the seven columns would disagree the first time one of them learned
    about a new `[DER]` table, and the disagreement would show up as a phantom document change in
    a review comment.

    `derive_lock`'s ruling on a document with no `document` block is **the 16 zero bytes**, not a
    raise: a receipt that names the document and reads "no root" is more useful to a reviewer
    than a receipt that cannot be produced at all. `diff` inherits that ruling rather than
    imposing a second one, and `portable.export_portable` -- which genuinely cannot write an
    archive for such a document -- reports it in its own `skipped` list.

    **The import is function-scope, and PLC0415 is suppressed deliberately.** `verify.py` pulls
    in `archive.owcheck`, `archive.owdoc`, `canonical` and `identity`; `residue()` and
    `explain_indexes()` need none of them, and a module-scope import would put the whole verify
    surface behind every report. This is the same shape as `config.py`'s two cross-module shims
    and `omniweave_core/__init__.py`'s nine `__getattr__` arms -- an explicit, argument-free
    import statement, not a dispatch through `importlib` (which semgrep bans outside `host/`).
    """
    from omniweave_core.store.verify import derive_lock  # noqa: PLC0415 -- see the docstring.

    return derive_lock(connection, header=_DIFF_HEADER).rows


ADDED: Final = "added"
"""A `doc_key` the receipt did not carry before. A first ingest of a document."""

REMOVED: Final = "removed"
"""A `doc_key` the receipt carried and no longer does. 07:3157's *"this one was removed"*."""

REPARSED: Final = "reparsed"
"""`gen` moved. 07:3157's *"these four documents were re-parsed"*; `doc.gen` is
*"the parse generation, and nothing else"* (07:2919)."""

CHANGED: Final = "changed"
"""Some other column moved while `gen` did not -- a derived-layer rebuild, a status correction,
or a re-segmentation, none of which is a re-parse. The plan's sentence names two arms and this
is the third the format forces: `n_segments` and `status` are receipt columns that a
`ow index rebuild --derived` legitimately moves at a fixed `gen` (07:3086), and folding those
into "re-parsed" would tell a reviewer a document was re-read when it was not."""

_CHANGE_ORDER: Final[tuple[str, ...]] = (REPARSED, CHANGED, ADDED, REMOVED)
"""Render order for `sentence()`: the plan's own clause order puts re-parsed first (07:3157)."""

_COMPARED_FIELDS: Final[tuple[str, ...]] = (
    "gen",
    "status",
    "n_blocks",
    "n_segments",
    "content_digest",
    "uri",
)
"""Every `LockRow` field except `doc_key`, which is the identity the two sides are joined on."""


class DocDelta(NamedTuple):
    """One document's change. The unit of `ow store diff`'s output (07:3155-3157).

    `before` and `after` are the whole rows, so a caller that wants to print "gen 3 -> gen 4"
    has both without a second lookup; `fields` names the columns that moved, in `LockRow` field
    order, and is empty for `added` and `removed`.
    """

    doc_key: bytes
    uri: str
    change: str
    before: LockRow | None
    after: LockRow | None
    fields: tuple[str, ...] = ()


class LockDiff(NamedTuple):
    """What an ingest changed, as documents. Sorted by `doc_key` bytes, like the receipt itself.

    `header_changed` is separate from the rows because 07:3130 makes a header difference its own
    conflict: `schema`, `scorer` or `space` moving means the two receipts were produced by
    different scorers, and a document-level diff between them compares numbers that are not
    commensurable. `diff_stores` leaves it `False`, because a store does not carry the header's
    `scorer`/`segmenter`/`space` tokens -- they are `omniweave.toml`'s and the embed space's.
    """

    deltas: tuple[DocDelta, ...]
    header_changed: bool = False

    @property
    def unchanged(self) -> bool:
        """True when nothing moved at all -- neither a document nor the header."""
        return not self.deltas and not self.header_changed

    def of(self, change: str) -> tuple[DocDelta, ...]:
        """Every delta of one kind, in `doc_key` order."""
        return tuple(d for d in self.deltas if d.change == change)

    def counts(self) -> dict[str, int]:
        """`{change: n}` for all four arms, INCLUDING the zeros.

        All four keys are always present for the same reason `ResidueReport` reports a zero:
        a caller cannot tell "no documents were removed" from "this report does not know about
        removals" if the key is simply absent.
        """
        counts = dict.fromkeys(_CHANGE_ORDER, 0)
        for delta in self.deltas:
            counts[delta.change] += 1
        return counts

    def sentence(self) -> str:
        """The reviewer-facing line 07:3156-3157 asks for, with the zero clauses dropped.

        *"these four documents were re-parsed and this one was removed"* is the shape; the
        wording here is `4 documents re-parsed, 1 removed`, which carries the same two facts in
        a form that does not have to inflect a numeral. A diff with no rows says so in words
        rather than returning an empty string, because an empty string in a review comment is
        indistinguishable from a tool that failed to run.
        """
        counts = self.counts()
        parts = [
            f"{counts[c]} {'document' if counts[c] == 1 else 'documents'} {_WORD[c]}"
            for c in _CHANGE_ORDER
            if counts[c]
        ]
        if self.header_changed:
            parts.append("the lock header changed")
        if not parts:
            return "no documents changed"
        return ", ".join(parts)


_WORD: Final[dict[str, str]] = {
    ADDED: "added",
    REMOVED: "removed",
    REPARSED: "re-parsed",
    CHANGED: "changed without a re-parse",
}
"""The prose for one arm. `re-parsed` is hyphenated because 07:3157 hyphenates it."""


def diff_lock(before: LockFile | str, after: LockFile | str) -> LockDiff:
    """Diff two `omniweave.index.lock` receipts, by document.

    Either side may be the file's TEXT, which `read_lock` parses -- that is what `ow store diff`
    holds when it reads `HEAD:omniweave.index.lock` out of git and the working tree's copy, and
    parsing here rather than at the call site keeps the CRLF normalisation and the conflict-marker
    refusal (`read_lock`, 11-repo-layout.md:490-493) on both inputs.

    **Whole-row equality is not used and a field list is computed instead**, which is the one
    place this differs from `merge_lock`. The merge driver compares rendered lines byte-for-byte
    because it must not rewrite bytes it does not understand (`store/indexlock.py`); a diff has
    the opposite job -- a reviewer needs to know that `gen` moved and `uri` did not.
    """
    left = read_lock(before) if isinstance(before, str) else before
    right = read_lock(after) if isinstance(after, str) else after
    return LockDiff(
        deltas=_diff_rows(left.rows, right.rows),
        header_changed=left.header != right.header,
    )


def diff_stores(before: sqlite3.Connection, after: sqlite3.Connection) -> LockDiff:
    """Diff two stores, by document, through the receipt they would each write.

    The two connections are ordinarily the same corpus before and after an ingest -- a backup
    taken with `maintenance.backup()` and the live file. Going through `lock_rows` rather than
    joining the two databases is deliberate: `ATTACH` would need both files writable by one
    connection and would make the diff depend on `block_id`s, which are per-store and are exactly
    what a portable comparison must not read (07:3078).
    """
    return LockDiff(deltas=_diff_rows(lock_rows(before), lock_rows(after)))


def _diff_rows(before: tuple[LockRow, ...], after: tuple[LockRow, ...]) -> tuple[DocDelta, ...]:
    """The three-way walk over two `doc_key`-sorted row sets, in `doc_key` byte order."""
    left = {row.doc_key: row for row in before}
    right = {row.doc_key: row for row in after}
    deltas: list[DocDelta] = []
    for key in sorted(left.keys() | right.keys()):
        old = left.get(key)
        new = right.get(key)
        if new is None and old is not None:
            deltas.append(DocDelta(key, old.uri, REMOVED, old, None))
            continue
        if old is None and new is not None:
            deltas.append(DocDelta(key, new.uri, ADDED, None, new))
            continue
        if old is None or new is None:  # pragma: no cover -- the key came from the union
            continue
        fields = tuple(f for f in _COMPARED_FIELDS if getattr(old, f) != getattr(new, f))
        if not fields:
            continue
        change = REPARSED if "gen" in fields else CHANGED
        deltas.append(DocDelta(key, new.uri, change, old, new, fields))
    return tuple(deltas)


# =============================================================================================
# 2. `ow store explain --golden` -- the index register, and one query plan per row.
# =============================================================================================


class RegisteredIndex(NamedTuple):
    """One row of 07:960-990's register, plus the probe this module derives from its Shape cell.

    `name`, `table`, `owner`, `serves` and `shape` are TRANSCRIBED. `owner` is the register's own
    column and it is a string rather than an int because three of its values are not migration
    numbers: `09-generation` and `events` name a document and a sidecar file, which is precisely
    the case 07:958-959 introduces the column for ("the register is corpus-wide, not
    file-scoped").
    """

    name: str
    table: str
    owner: str
    serves: str
    shape: str
    probe: str


INDEX_REGISTER: Final[tuple[RegisteredIndex, ...]] = (
    RegisteredIndex(
        "block_addr",
        "block",
        "0001",
        "`ow open addr=p14/3`; `rebind` positional match",
        "UNIQUE `(doc_ord, gen, addr)`",
        "SELECT block_id FROM block WHERE doc_ord = ? AND gen = ? AND addr = ?",
    ),
    RegisteredIndex(
        "block_cite",
        "block",
        "0001",
        "every `cite` resolution, on every surface",
        "UNIQUE `(doc_ord, cite)` -- **gen-free**",
        "SELECT block_id FROM block WHERE doc_ord = ? AND cite = ?",
    ),
    RegisteredIndex(
        "block_sib",
        "block",
        "0001",
        "sibling ordering; duplicate-ord detection",
        "UNIQUE `(doc_ord, gen, IFNULL(parent_id,-1), ord)`",
        "SELECT block_id FROM block WHERE doc_ord = ? AND gen = ? "
        "AND IFNULL(parent_id,-1) = ? ORDER BY ord",
    ),
    RegisteredIndex(
        "block_read",
        "block",
        "0001",
        "full-document render = one range scan",
        "`(doc_ord, gen, page, ord)` partial `state=0`",
        "SELECT block_id FROM block WHERE doc_ord = ? AND gen = ? AND state = 0 ORDER BY page, ord",
    ),
    RegisteredIndex(
        "block_parent",
        "block",
        "0001",
        "containment walk, neighbour expansion",
        "`(parent_id, ord)` partial `state=0`",
        "SELECT block_id FROM block WHERE parent_id = ? AND state = 0 ORDER BY ord",
    ),
    RegisteredIndex(
        "block_kind",
        "block",
        "0001",
        "`Filters.kinds` narrowing",
        "`(doc_ord, gen, kind, page, ord)` partial",
        "SELECT block_id FROM block WHERE doc_ord = ? AND gen = ? AND kind = ? AND state = 0 "
        "ORDER BY page, ord",
    ),
    RegisteredIndex(
        "block_cdig",
        "block",
        "0001",
        "`rebind()` rule 1 (equal digest under one parent)",
        "`(doc_ord, content_digest)`",
        "SELECT block_id FROM block WHERE doc_ord = ? AND content_digest = ?",
    ),
    RegisteredIndex(
        "block_review",
        "block",
        "0001",
        "the human review queue",
        "partial `trust < 2 AND state = 0`",
        "SELECT block_id FROM block WHERE doc_ord = ? AND gen = ? AND trust < 2 AND state = 0 "
        "ORDER BY page",
    ),
    RegisteredIndex(
        "block_restricted",
        "block",
        "0001",
        "gate 10 counting",
        "partial `restriction_bits <> 0`",
        "SELECT count(*) FROM block WHERE restriction_bits <> 0",
    ),
    RegisteredIndex(
        "diag_code",
        "diag",
        "0001",
        "**absence gate 9** -- the one indexed join nobody else has",
        "`(code)`",
        "SELECT count(*) FROM diag WHERE code = ?",
    ),
    RegisteredIndex(
        "anchor_corpus",
        "anchor",
        "0002",
        "corpus-scope resolution",
        "partial `scope = 'corpus'`",
        "SELECT block_id FROM anchor WHERE scope = 'corpus' AND name_norm = ? AND akind = ?",
    ),
    RegisteredIndex(
        "anchor_name",
        "anchor",
        "0002",
        "document-scope resolution",
        "`(name_norm, akind, scope, doc_ord)`",
        "SELECT block_id FROM anchor WHERE name_norm = ? AND akind = ? AND scope = ?",
    ),
    RegisteredIndex(
        "segment_block_seg",
        "segment_block",
        "0002",
        "the semantic lift (`ord`-ordered members)",
        "`(segment_id, ord)`",
        "SELECT block_id FROM segment_block WHERE segment_id = ? ORDER BY ord",
    ),
    RegisteredIndex(
        "mention_block",
        "mention",
        "0002",
        "section 7.4 graph impact",
        "`(block_id)` partial `state = 0`",
        "SELECT mention_id FROM mention WHERE block_id = ? ORDER BY ts_a",
    ),
    RegisteredIndex(
        "segment_digest_ix",
        "segment",
        "0003",
        "the semantic join; embedding dedup",
        "partial `state = 0`",
        "SELECT segment_id FROM segment WHERE content_digest = ? AND state = 0",
    ),
    RegisteredIndex(
        "segment_doc",
        "segment",
        "0003",
        "segment-side page/document narrowing",
        "partial",
        "SELECT segment_id FROM segment WHERE doc_ord = ? AND gen = ? AND state = 0 "
        "ORDER BY first_page",
    ),
    RegisteredIndex(
        "segment_restricted",
        "segment",
        "0003",
        "gate 10",
        "partial",
        "SELECT count(*) FROM segment WHERE restriction_bits <> 0",
    ),
    RegisteredIndex(
        "block_sec_path",
        "block_sec",
        "0003",
        "`sec_path` prefix range scan; the lexical spine term",
        "`(sec_path, block_id)`",
        "SELECT block_id FROM block_sec WHERE sec_path >= ? AND sec_path < ?",
    ),
    RegisteredIndex(
        "block_link_identity",
        "block_link",
        "0003",
        "`INSERT OR IGNORE`",
        "UNIQUE, 6 columns, 2 sentinels",
        "SELECT link_id FROM block_link WHERE src_block = ? AND dst_block = ? AND relation = ? "
        "AND producer_id = ? AND IFNULL(site_block,-1) = ? AND IFNULL(via_entity,-1) = ?",
    ),
    RegisteredIndex(
        "block_link_out",
        "block_link",
        "0003",
        "`Expand` forward hop",
        "`(src_block, relation)`",
        "SELECT weight FROM block_link WHERE src_block = ? AND relation = ?",
    ),
    RegisteredIndex(
        "block_link_in",
        "block_link",
        "0003",
        "`Expand` reverse hop; back-references",
        "`(dst_block, relation)`",
        "SELECT src_block FROM block_link WHERE dst_block = ? AND relation = ?",
    ),
    RegisteredIndex(
        "block_link_bound",
        "block_link",
        "0003",
        "`anchor_delta` unbind",
        "partial `bound_by IS NOT NULL`",
        "SELECT link_id FROM block_link WHERE bound_by = ?",
    ),
    RegisteredIndex(
        "block_link_restricted",
        "block_link",
        "0003",
        "gate 10 on traversal",
        "partial",
        "SELECT count(*) FROM block_link WHERE restriction_bits <> 0",
    ),
    RegisteredIndex(
        "ref_site_block",
        "ref_site",
        "0003",
        "hydration; cascade locality",
        "`(block_id)`",
        "SELECT name_norm FROM ref_site WHERE block_id = ?",
    ),
    RegisteredIndex(
        "ref_site_name",
        "ref_site",
        "0003",
        "the `exact` Channel; `anchor_delta` retry",
        "`(name_norm, akind)`",
        "SELECT block_id FROM ref_site WHERE name_norm = ? AND akind = ?",
    ),
    RegisteredIndex(
        "dep_reverse",
        "dep",
        "0004",
        "section 11.4 invalidation, one query",
        "`(kind, key, digest)`",
        "SELECT dependent_id FROM dep WHERE kind = ? AND key = ?",
    ),
    RegisteredIndex(
        "artifact_cite_block",
        "artifact_cite",
        "09-generation",
        "section 7.4 artefact impact",
        "`(block_id)`",
        "SELECT artifact_id FROM artifact_cite WHERE block_id = ?",
    ),
    RegisteredIndex(
        "retrieval_event_ts",
        "retrieval_event",
        "events",
        "ledger scans, retention",
        "`(ts_ns)`",
        "SELECT event_id FROM retrieval_event WHERE ts_ns >= ?",
    ),
    RegisteredIndex(
        "retrieval_event_bad",
        "retrieval_event",
        "events",
        '"what degraded"',
        "partial `verdict_state <> 'ok'`",
        "SELECT event_id FROM retrieval_event WHERE verdict_state <> 'ok'",
    ),
)
"""07:960-990's twenty-nine index rows, transcribed, plus one probe query each (DEFECT 2).

The order is the plan table's own printed order and NOT alphabetical, because a register is a
transcription and re-sorting it makes the two documents diff badly. `explain_indexes` sorts by
name when it renders, which is where the byte-diff gate needs the order and where the plan's row
order is not a fact about the store.
"""

_MIGRATION_OWNERS: Final[dict[str, int]] = {"0001": 1, "0002": 2, "0003": 3, "0004": 4}
"""Register owners that name a shipped migration, mapped to `migration.version`.

`0003_index.sql:435` declares `migration(version INTEGER PRIMARY KEY, ...)`, so the applied set
is a set of ints and a register cell spelled `0001` has to be resolved against it. Every other
owner value -- `09-generation`, `events` -- names something that is not one of the four shipped
files, which is `PENDING` below and never a failure.
"""

OK: Final = "ok"
"""The registered index exists and the planner chose it for the register's own probe."""

UNUSED: Final = "unused"
"""The registered index exists and the planner chose a DIFFERENT index (or none). ST17's
*"every shipped index is used"* (07:3251) is the clause this reports against; see DEFECT 3."""

MISSING: Final = "missing"
"""The owning migration is applied and `sqlite_master` has no such index. **A failure.**

07:957: *"an index whose statement no longer exists is deleted in the same PR"* -- the register
and the schema disagreeing is the condition ST17 exists to catch, and reporting it as a skip
would make `explain --golden` byte-identical before and after an index was silently dropped.
"""

PENDING: Final = "pending"
"""The owning migration is not applied to this store, or the owner is not a shipped migration.

Three register rows are in this state on every P2 store and legitimately so: `artifact_cite` is
09-generation's table and lands in `0005_out.sql` at P9, and `retrieval_event` lives in
`events.owstore`, a separate database file (07 section 3.10). Reported, never failed on, and
NEVER silent -- a pending row is a line in the golden output like any other.
"""


class ExplainRow(NamedTuple):
    """One register row's verdict: its status and the plan SQLite actually produced.

    `plan` is the `EXPLAIN QUERY PLAN` detail column, one string per node, in the order SQLite
    emitted them -- that order is the plan tree and is part of what the golden gate watches. It
    is empty for `missing` and `pending`, where no statement was run; `reason` carries the
    sentence in those two cases and is empty otherwise.
    """

    index: RegisteredIndex
    status: str
    plan: tuple[str, ...] = ()
    reason: str = ""

    @property
    def used(self) -> tuple[str, ...]:
        """Every index name the plan mentions, sorted -- what the planner actually reached for."""
        found = {
            word
            for detail in self.plan
            for word in detail.replace("(", " ").replace(")", " ").split()
        }
        return tuple(sorted(found & _ALL_REGISTERED))


_ALL_REGISTERED: Final[frozenset[str]] = frozenset(i.name for i in INDEX_REGISTER)
"""Register names, for `ExplainRow.used`'s token filter."""


class ExplainReport(NamedTuple):
    """Every register row's plan, plus the indexes `sqlite_master` holds and nobody registered.

    `unregistered` is reported and not failed on -- see DEFECT 1. `failures` is exactly the
    `missing` rows, which is 07:957's enforceable half.
    """

    rows: tuple[ExplainRow, ...]
    unregistered: tuple[str, ...]

    @property
    def failures(self) -> tuple[ExplainRow, ...]:
        """The register rows whose index the applied schema does not have. 07:957."""
        return tuple(r for r in self.rows if r.status == MISSING)

    @property
    def ok(self) -> bool:
        """True when no register row is `missing`. The gate's exit-0 predicate."""
        return not self.failures

    def render(self) -> str:
        """The byte-diff gated golden form (07:956). Sorted, LF-only, one trailing newline.

        Five properties make it diffable, and each is a thing deliberately NOT in the output:
        no clock, no file path, no row count, no `sqlite_version()` and no register row order
        from the plan document. What IS in it is the register name, the table, the owner, the
        status and the plan text -- which is exactly the set that moves when a plan flips.

        Sorting is by index NAME, ASCII, which is stable under every locale because every
        register name is lower-case ASCII with underscores. The unregistered list is sorted the
        same way and is emitted last, so a new index appended to a migration moves one line at
        the end of the file rather than renumbering the body.
        """
        lines = ["# ow store explain --golden"]
        for row in sorted(self.rows, key=lambda r: r.index.name):
            tail = " ; ".join(row.plan) if row.plan else row.reason
            lines.append(
                f"{row.index.name}\t{row.index.table}\t{row.index.owner}\t{row.status}\t{tail}"
            )
        for name in sorted(self.unregistered):
            lines.append(f"# unregistered\t{name}")
        return "\n".join(lines) + "\n"


def explain_indexes(connection: sqlite3.Connection) -> ExplainReport:
    """`EXPLAIN QUERY PLAN` for every row of `INDEX_REGISTER`, deterministically (07:956).

    The verb this becomes at P7 is `ow store explain --golden`, whose output is byte-diff gated;
    `ExplainReport.render()` is that output and this function is what fills it.

    **Nothing here binds a real value.** Every probe's parameters are `NULL`, because the query
    planner's choice is a function of the schema and of `sqlite_stat1`, never of a bound value --
    SQLite prepares the statement before it sees one. Binding a real id would make the golden
    output depend on the fixture that produced it, which is the one thing a byte-diff gate must
    not tolerate.

    **A register row whose index is absent is a reported failure and never a skip** (07:957): the
    row is emitted with `status = missing` and lands in `ExplainReport.failures`, so
    `render()` differs and `ok` is `False`. A row whose OWNER migration is not applied is
    `pending` instead, which is the honest verdict for `artifact_cite_block` on a P2 store and is
    still a line in the output.
    """
    live = _live_indexes(connection)
    applied = migrate.applied_versions(connection)
    rows: list[ExplainRow] = []
    for entry in INDEX_REGISTER:
        version = _MIGRATION_OWNERS.get(entry.owner)
        if version is None or version not in applied:
            rows.append(ExplainRow(entry, PENDING, (), _pending_reason(entry, version)))
            continue
        if entry.name not in live:
            rows.append(
                ExplainRow(
                    entry,
                    MISSING,
                    (),
                    f"migration {entry.owner} is applied and sqlite_master has no index "
                    f"{entry.name!r} on {entry.table!r} (07-store-and-retrieval.md:957)",
                )
            )
            continue
        plan = _query_plan(connection, entry)
        status = OK if entry.name in ExplainRow(entry, OK, plan).used else UNUSED
        rows.append(ExplainRow(entry, status, plan))
    return ExplainReport(rows=tuple(rows), unregistered=_unregistered(live))


def _pending_reason(entry: RegisteredIndex, version: int | None) -> str:
    """Why a register row could not be checked against this store. Never "skipped"."""
    if version is None:
        return (
            f"owner {entry.owner!r} is not one of the four shipped migrations, so "
            f"{entry.table!r} is not a table of this database file "
            f"(07-store-and-retrieval.md:958)"
        )
    return f"migration {entry.owner} is not applied to this store"


def _query_plan(connection: sqlite3.Connection, entry: RegisteredIndex) -> tuple[str, ...]:
    """The `detail` column of `EXPLAIN QUERY PLAN`, in emitted order.

    A failure to prepare is re-raised as a `StoreError` naming the register row, because a probe
    that does not compile is this module's defect and not the store's -- and an `OperationalError`
    escaping from a report function would read as a corrupt database.
    """
    parameters = [None] * entry.probe.count("?")
    try:
        cursor = connection.execute("EXPLAIN QUERY PLAN " + entry.probe, parameters)
    except sqlite3.Error as exc:
        raise StoreError(
            f"the register probe for index {entry.name!r} did not compile against this store: "
            f"{exc}",
            fix=_FIX_EXPLAIN,
        ) from exc
    return tuple(str(row[3]) for row in cursor.fetchall())


def _live_indexes(connection: sqlite3.Connection) -> frozenset[str]:
    """Every index `sqlite_master` holds, including the ones SQLite creates for itself."""
    return frozenset(
        str(name)
        for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
    )


def _unregistered(live: frozenset[str]) -> tuple[str, ...]:
    """Live indexes with no register row, minus SQLite's own `sqlite_autoindex_*`.

    An autoindex is not a shipped index: SQLite mints one for every `UNIQUE` or non-`INTEGER`
    `PRIMARY KEY` declared inline, so it has no `CREATE INDEX` statement to register and
    07:956's "every shipped index is named" cannot reach it. See DEFECT 1 for why the rest are
    reported rather than failed on.
    """
    return tuple(sorted(n for n in live - _ALL_REGISTERED if not n.startswith("sqlite_autoindex_")))


# =============================================================================================
# 3. `ow store residue` -- INV-25's four tables, `ref_unresolved`, and the container share.
# =============================================================================================

GENERATION: Final = "generation"
"""`ResidueTable.age_unit` for a table stamped by `gen` and not by a clock."""

WALL_MS: Final = "wall_ms"
"""`ResidueTable.age_unit` for `route_signal.computed_at`. See the module docstring."""


class _ResidueSpec(NamedTuple):
    """One INV-25 table and the column an operator measures its growth against."""

    table: str
    age_column: str
    age_unit: str
    why: str


RESIDUE_TABLES: Final[tuple[_ResidueSpec, ...]] = (
    _ResidueSpec(
        "route_signal",
        "computed_at",
        WALL_MS,
        "the routing raster cache; F37 names its disk growth against the sweep rate as open",
    ),
    _ResidueSpec(
        "quarantine",
        "at_gen",
        GENERATION,
        "rejected graph drafts, KEPT rather than deleted (0002_graph.sql:496)",
    ),
    _ResidueSpec(
        "ref_attempt",
        "last_tried_gen",
        GENERATION,
        "the failed tail of reference resolution, written only after a first failure",
    ),
    _ResidueSpec(
        "block_history",
        "retired_gen",
        GENERATION,
        "retirement rows, one per block a re-parse superseded",
    ),
)
"""INV-25's four tables, in 01-principles.md:796's printed order.

*"residue grows without bound -- `route_signal`, `quarantine`, `ref_attempt`, `block_history`"*.
The order is the invariant's own and is not sorted, for the same reason `INDEX_REGISTER` is not:
a register is a transcription. The `age_column` cell is this module's, chosen as the only
non-identity integer each table carries -- and `ref_attempt.ts_a` is deliberately NOT it; see
the module docstring.
"""

DEFAULT_GROUP_LIMIT: Final = 100
"""How many `ref_unresolved` groups `residue()` returns by default. **This number is ours.**

07:553 says `ow store residue` prints `ref_unresolved` grouped by `name_norm` and fixes no
ceiling, and INV-25's defence list ends with *"every ceiling at `take(N+1)`"*
(01-principles.md:796) -- which is a pattern and not a value. Reading an unbounded number of
groups out of a table the same invariant says grows without bound would reproduce the bug the
report exists to show, so there is a ceiling; it is a parameter, the caller can raise it, and
`ResidueReport.truncated` says when it bound. The N+1 read is what makes `truncated` exact
rather than a guess from `len(groups) == limit`.
"""


class ResidueTable(NamedTuple):
    """One INV-25 table's growth: how many rows, and how far back they go.

    `oldest` and `newest` are the raw column values, in `age_unit`'s unit, and are `None` on an
    empty table. `oldest_age_ns` is filled only for `WALL_MS`, because subtracting a generation
    number from a nanosecond clock would produce a number with no meaning.
    """

    table: str
    rows: int
    age_column: str
    age_unit: str
    why: str
    oldest: int | None = None
    newest: int | None = None
    oldest_age_ns: int | None = None

    @property
    def empty(self) -> bool:
        """True when the table holds no rows. **Distinct from "this table was not read".**"""
        return self.rows == 0


class RefGroup(NamedTuple):
    """One `name_norm`'s unresolved references. 07:553's grouping, exactly.

    `akinds` and `docs` are the distinct anchor kinds and documents the group spans; a name that
    is unresolved in one document is a typo, and the same name unresolved in forty is a missing
    corpus-scope anchor. `surface` is one example as written, which `ref_site.surface` says is
    "DISPLAYED, never matched" (0003_index.sql:225) -- it is in the report so an operator can
    read the group, and it is never the key.
    """

    name_norm: str
    sites: int
    akinds: tuple[str, ...]
    docs: int
    surface: str


class ContainerShare(NamedTuple):
    """How much of the corpus is container members. 05-ingest-and-routing.md:816-819.

    *"their bytes count against `unit.derived["container_bytes"]`, which is what `ow store
    residue` reads to find a corpus that is 90% zip members."* `share` is that 90% as a
    fraction of unit COUNT and `byte_share` as a fraction of `unit.bytes`, because the sentence
    names both quantities in one clause ("bytes count against ... a corpus that is 90% zip
    members") and they answer different questions: ten thousand tiny members and one enormous
    one are the same corpus by bytes and very different corpora by work.
    """

    units: int
    container_units: int
    container_bytes: int
    total_bytes: int

    @property
    def share(self) -> float:
        """Container members as a fraction of all units. `0.0` on an empty roster."""
        return 0.0 if self.units == 0 else self.container_units / self.units

    @property
    def byte_share(self) -> float:
        """Container-member bytes as a fraction of all unit bytes. `0.0` when nothing is sized."""
        return 0.0 if self.total_bytes == 0 else self.container_bytes / self.total_bytes


class ResidueReport(NamedTuple):
    """What `ow store residue` prints: data, not a log line (07:553).

    `tables` always carries all four INV-25 rows, `groups` may be empty and `truncated` says
    whether the group ceiling bound. A store with no residue at all produces a report whose four
    tables each say `rows = 0` -- not an empty tuple, which a caller could not tell from a read
    that failed.
    """

    tables: tuple[ResidueTable, ...]
    groups: tuple[RefGroup, ...]
    unresolved_sites: int
    containers: ContainerShare
    truncated: bool = False

    @property
    def total_rows(self) -> int:
        """Every INV-25 row in the store. The one number that answers "is it growing?"."""
        return sum(t.rows for t in self.tables)

    def table(self, name: str) -> ResidueTable:
        """One INV-25 table by name, raising rather than returning `None` for an unknown one."""
        for row in self.tables:
            if row.table == name:
                return row
        raise KeyError(f"{name!r} is not one of INV-25's four tables (01-principles.md:796)")


_REF_GROUP_SQL: Final = """
SELECT name_norm, akind, doc_ord, surface, count(*)
  FROM ref_unresolved
 GROUP BY name_norm, akind, doc_ord, surface
 ORDER BY name_norm, akind, doc_ord, surface
"""
"""`ref_unresolved` at its finest grouping, folded to `name_norm` in Python.

Grouping in SQL to `name_norm` alone and reaching for `group_concat(DISTINCT akind)` would make
the report's `akinds` cell depend on SQLite's row order, which no gate would notice until the
day it changed. The four-column `GROUP BY` with a total `ORDER BY` is deterministic, and folding
it costs one pass over a set that is already grouped.
"""

_CONTAINER_SQL: Final = """
SELECT count(*),
       count(json_extract(derived, '$.container_bytes')),
       coalesce(sum(json_extract(derived, '$.container_bytes')), 0),
       coalesce(sum(bytes), 0)
  FROM unit
"""
"""The container share, in one pass. `unit.derived` is `TEXT NOT NULL DEFAULT '{}'` JSON.

`count(<expr>)` counts non-NULL results, so the second column is the number of units that
actually carry the key rather than the number of rows -- `json_extract` returns NULL for an
absent path, which is what makes the distinction free.
"""


def residue(
    connection: sqlite3.Connection,
    *,
    now_ns: int,
    limit: int = DEFAULT_GROUP_LIMIT,
) -> ResidueReport:
    """The residue report: INV-25's four tables, `ref_unresolved` by `name_norm`, and containers.

    Becomes `ow store residue` at P7. Read-only, and the clock is the caller's (see the module
    docstring) -- `now_ns` is used for exactly one thing, the wall-clock age of the oldest
    `route_signal` row, and a caller that does not care may pass any int.

    **Every one of the four tables appears in the report even when it is empty**, with
    `rows = 0` and a `None` age. INV-25 is a claim about growth, and "this table is empty" and
    "this report does not cover that table" are the two answers an operator must be able to tell
    apart; an absent row conflates them. 07:553's *"the residue is data, not a log line"* is the
    same instruction from the other side -- a log line prints when something happened, and data
    is there when nothing did.
    """
    if limit < 1:
        raise StoreError(
            f"residue(limit={limit}) must be at least 1: a report that returns no groups cannot "
            f"be told from a corpus with no unresolved references",
            fix="ow store residue",
        )
    tables = tuple(_residue_table(connection, spec, now_ns=now_ns) for spec in RESIDUE_TABLES)
    groups, sites, truncated = _ref_groups(connection, limit=limit)
    return ResidueReport(
        tables=tables,
        groups=groups,
        unresolved_sites=sites,
        containers=_container_share(connection),
        truncated=truncated,
    )


def _residue_table(
    connection: sqlite3.Connection, spec: _ResidueSpec, *, now_ns: int
) -> ResidueTable:
    """One INV-25 table's count and age extremes, in one statement.

    The column name is interpolated, and it is safe for the reason S608 cannot see: `spec` comes
    from `RESIDUE_TABLES`, a module constant of four literals, and nothing reaches this function
    from a caller. The same shape and the same reason are in `maintenance._fts_command`.
    """
    # S608: `spec` is one of `RESIDUE_TABLES`' four literals and nothing reaches this function
    # from a caller; ruff cannot see the provenance across the call.
    sql = f"SELECT count(*), min({spec.age_column}), max({spec.age_column}) FROM {spec.table}"  # noqa: S608
    rows, oldest, newest = connection.execute(sql).fetchone()
    age_ns: int | None = None
    if spec.age_unit == WALL_MS and oldest is not None:
        age_ns = now_ns - int(oldest) * MS_PER_NS
    return ResidueTable(
        table=spec.table,
        rows=int(rows),
        age_column=spec.age_column,
        age_unit=spec.age_unit,
        why=spec.why,
        oldest=None if oldest is None else int(oldest),
        newest=None if newest is None else int(newest),
        oldest_age_ns=age_ns,
    )


def _ref_groups(
    connection: sqlite3.Connection, *, limit: int
) -> tuple[tuple[RefGroup, ...], int, bool]:
    """`ref_unresolved` folded to `name_norm`, ranked, and cut at `limit` with a `take(N+1)`.

    The rank is `(-sites, name_norm)`: the worst offender first, ties broken by the name so the
    order is total and the report is reproducible. `sites` is every unresolved occurrence and is
    returned separately from the group count, because a hundred groups of one and one group of a
    hundred are the same total and completely different problems.
    """
    folded: dict[str, dict[str, object]] = {}
    total = 0
    for name_norm, akind, doc_ord, surface, count in connection.execute(_REF_GROUP_SQL):
        total += int(count)
        entry = folded.setdefault(
            str(name_norm),
            {"sites": 0, "akinds": set(), "docs": set(), "surface": str(surface)},
        )
        entry["sites"] = int(entry["sites"]) + int(count)  # type: ignore[call-overload]
        akinds: set[str] = entry["akinds"]  # type: ignore[assignment]
        akinds.add(str(akind))
        docs: set[int] = entry["docs"]  # type: ignore[assignment]
        docs.add(int(doc_ord))
    ranked = sorted(folded.items(), key=lambda kv: (-int(kv[1]["sites"]), kv[0]))  # type: ignore[call-overload]
    truncated = len(ranked) > limit
    groups = tuple(
        RefGroup(
            name_norm=name,
            sites=int(entry["sites"]),  # type: ignore[call-overload]
            akinds=tuple(sorted(entry["akinds"])),  # type: ignore[arg-type]
            docs=len(entry["docs"]),  # type: ignore[arg-type]
            surface=str(entry["surface"]),
        )
        for name, entry in ranked[:limit]
    )
    return groups, total, truncated


def _container_share(connection: sqlite3.Connection) -> ContainerShare:
    """The container-member share of the roster. 05-ingest-and-routing.md:818."""
    units, container_units, container_bytes, total_bytes = connection.execute(
        _CONTAINER_SQL
    ).fetchone()
    return ContainerShare(
        units=int(units),
        container_units=int(container_units),
        container_bytes=int(container_bytes),
        total_bytes=int(total_bytes),
    )


STATUS_VALUES: Final[tuple[str, ...]] = (OK, UNUSED, MISSING, PENDING)
"""The four `ExplainRow.status` values, so a caller can switch on them exhaustively."""

AGE_UNITS: Final[tuple[str, ...]] = (GENERATION, WALL_MS)
"""The two `ResidueTable.age_unit` values."""

CHANGES: Final[tuple[str, ...]] = _CHANGE_ORDER
"""The four `DocDelta.change` values, in `sentence()`'s render order."""


# =============================================================================================
# 4. STORE SIZING -- `store.bytes_per_block`, and 07:1021-1037's decomposition MEASURED.
# =============================================================================================
#
# WHY THIS LIVES IN `inspect.py` AND NOT IN A NEW `store/sizing.py`
# ------------------------------------------------------------------
# INV-21, one fact one home (01-principles.md:766). This file is already the store's reporting
# home: `residue()` counts rows across four tables and `ContainerShare` already divides one byte
# total by another and calls the quotient a share (05-ingest-and-routing.md:816-819). A sizing
# report is that same act over a different denominator, and it reuses two things this module owns
# outright -- `INDEX_REGISTER`, from which `BLOCK_INDEXES` DERIVES the nine `block` indexes
# 07:1031 charges for rather than transcribing that list a second time, and the house rule that a
# report returns a value object and never prints. A separate module would have had to import
# `INDEX_REGISTER` from here anyway, which is the tell that the fact already lives here.
#
# WHAT THE PLAN ASKS FOR, AND WHY A SCALAR WOULD NOT ANSWER IT
# --------------------------------------------------------------
# 07:1017: *"At 660 B/block, decomposed so a reviewer can attack a line rather than the total."*
# So `store_sizing` returns a TABLE with an ESTIMATED column, transcribed from 07:1023-1037, and a
# MEASURED column beside it, per component. 07:1023 states the reason the total alone is
# uninformative in its own words: *"corpus-dependent and dominant. A prose paragraph is ~300 B; a
# table cell is ~10 B. The 60-120 blocks/page envelope is that wide **because cells are Blocks**."*
# Every aggregate here is therefore reported next to the composition that produced it
# (`CompositionSize`), and a caller that prints one number without the composition has thrown away
# the only variable that moves it.
#
# HOW A BYTE IS COUNTED, AND WHY NOT WITH `dbstat`
# --------------------------------------------------
# `dbstat` is a compile-time-optional virtual table (`SQLITE_ENABLE_DBSTAT_VTAB`), and CPython's
# bundled SQLite is built without it on at least Windows/msvc -- observed on the 3.43.1 that
# `store/sqlite.py`'s `refuse_old_sqlite` treats as the floor. It answers a question nothing else
# can, namely how many PAGES an index occupies, so it is detected and used when present; when it
# is absent the components that need it are reported `UNCHECKED` WITH THE REASON, never silently
# folded into a total and never quietly passed. That third state is `store/verify.py`'s
# `_unchecked()` pattern and the reason is the same one 07:3184-3185 gives: "I could not read
# them" must not read like "they were fine".
#
# The per-COLUMN numbers need no `dbstat`, because SQLite's record format is specified and
# arithmetic. A table b-tree cell is `[payload-size varint][rowid varint][header][body]`; the
# header is its own length as a varint followed by one serial-type varint per column; the body is
# each column's bytes in order, and NULL and the integers 0 and 1 cost ZERO body bytes because
# their serial type carries the value (serial types 0, 8, 9). `_payload_sql` and
# `_serial_width_sql` express that encoding as SQL, so the measurement is one pass over the table
# and is exact for the record rather than a sample. What it does NOT include is the b-tree's own
# overhead -- cell pointers, page headers, free space, overflow chaining -- which is exactly why
# `SizingReport.bytes_per_block` (the whole file over the block count) is reported separately and
# is the figure 12-performance.md:244's ratchet names. The two disagree by the b-tree's slack, and
# that gap is a fact about the store rather than an error in either number.
#
# WHAT THIS MODULE DELIBERATELY DOES NOT DO
# -------------------------------------------
# It does not decide whether a budget was met. 12-performance.md:1966 makes `ow-bench-1` the only
# machine a Budget may live on, so a comparison against 660 is an INDICATION and whoever prints it
# owes the reader that sentence. `tools/measure_store.py` is where it is printed; this file
# supplies no verdict, no baseline and no exit code.


MEASURED: Final = "measured"
"""A `ComponentCost` whose measured figure covers everything its plan row names."""

PARTIAL: Final = "partial"
"""Measured over PART of what the plan row names. `covers` says which part, in words.

The plan's rows are not all one object. 07:1034 charges the `block_sec` row and the
`block_sec_path` index together; the row is a table this module encodes exactly and the index
needs `dbstat`. Folding a half-measurement into `MEASURED` would understate the component with no
signal at all, and calling the whole row `UNCHECKED` would throw away a number actually obtained.
"""

UNCHECKED: Final = "unchecked"
"""No measurement was possible. `reason` says why, in the voice of `verify.py`'s `_unchecked()`."""

SIZING_STATES: Final[tuple[str, ...]] = (MEASURED, PARTIAL, UNCHECKED)
"""The three `ComponentCost.state` values, so a caller can switch on them exhaustively."""


PROSE: Final = "prose"
CELLS: Final = "cells"
MIXED: Final = "mixed"

COMPOSITIONS: Final[tuple[str, ...]] = (PROSE, CELLS, MIXED)
"""The three compositions every aggregate is reported against.

07:1023 is why there are three and not one: *"A prose paragraph is ~300 B; a table cell is ~10 B.
The 60-120 blocks/page envelope is that wide **because cells are Blocks**."* A single
bytes-per-block figure over a corpus whose prose/cell mix was chosen by whoever wrote the fixture
is a number about the fixture, so the mix is reported beside the aggregate every time.
"""

PROSE_KINDS: Final[frozenset[str]] = frozenset({"heading", "paragraph"})
"""`enum_val` names counted as prose. Two, and they are the left-hand side of 07:1023's example.

Not `title`, not `list_item`, not `caption`: each is prose to a reader and each would move the
number, so the set is the narrow one the split was defined over and a corpus carrying them shows
them in `SizingReport.kinds` as neither prose nor cells. Widening this set is a decision about
what the measurement MEANS, and it belongs to whoever makes it explicitly.
"""

CELL_KINDS: Final[frozenset[str]] = frozenset({"table_cell"})
"""`enum_val` names counted as cells. `Kind.TABLE_CELL`, ordinal 10 (`0001_init.sql:104`)."""


BLOCK_INDEXES: Final[tuple[str, ...]] = tuple(
    row.name for row in INDEX_REGISTER if row.table == "block"
)
"""The nine `block` indexes 07:1031 charges ~130 B/block for -- DERIVED, not transcribed twice.

07:1031 names seven that "carry the weight" plus `block_review` and `block_restricted`, which is
exactly the set of `INDEX_REGISTER` rows whose `table` is `block`. Deriving it means that the day
the register gains or loses a `block` index this component's coverage moves with it (INV-21); a
second literal list would have gone stale in silence while the estimate still read ~130.
"""

_FTS_SHADOWS: Final[tuple[str, ...]] = ("_data", "_idx", "_docsize", "_content", "_config")
"""The shadow tables an fts5 virtual table ships. `dbstat` reports each under its own name, so an
FTS component's page cost is the sum over `<name><shadow>` for every shadow that exists."""


# --------------------------------------------------------------------------------------------
# 4.1 The record encoding, as SQL. See the section header for why this and not `dbstat`.
# --------------------------------------------------------------------------------------------

_IDENT_RE: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
"""Every identifier interpolated into a statement below is checked against this first.

The names come from `PRAGMA table_info` -- the store's own schema, not a caller's string -- and
`_require_ident` runs anyway, because "it came from the schema" is an argument about today's
callers while a regex is an argument about the statement.
"""

_INT_WIDTHS: Final[tuple[tuple[int, int], ...]] = (
    (127, 1),
    (32_767, 2),
    (8_388_607, 3),
    (2_147_483_647, 4),
    (140_737_488_355_327, 6),
)
"""SQLite serial types 1-6: an integer's body width by magnitude. There is no five-byte form --
serial type 5 is SIX bytes -- which is why this is a table and not `(bits + 7) // 8`."""

_VARINT_BOUNDS: Final[tuple[int, ...]] = (
    127,
    16_383,
    2_097_151,
    268_435_455,
    34_359_738_367,
    4_398_046_511_103,
    562_949_953_421_311,
)
"""Inclusive upper bound of a 1-, 2- ... 7-byte SQLite varint. Larger values take 8 or 9 bytes and
`_varint_width_sql` answers 8 past the end of the table, which no `rowid` in this schema reaches:
`CHECK ((block_id >> 48) = 0)` (`0001_init.sql:281`) bounds it at 2**48."""

_TEXT_1B: Final = 57
"""Longest text/blob body whose serial type still fits one varint byte. Text is `2n+13` and blob
is `2n+12`; both clear 127 at n = 57 and neither does at n = 58."""

_TEXT_2B: Final = 8_185
"""...and two varint bytes: `2*8185 + 13 = 16383`, the last value a two-byte varint holds."""

_TEXT_3B: Final = 1_048_569
"""...and three."""


def _require_ident(name: str) -> str:
    """Refuse an identifier that is not a bare SQL name before it reaches a statement."""
    if not _IDENT_RE.match(name):
        raise StoreError(
            f"{name!r} is not a bare SQL identifier, and this module interpolates column and "
            f"table names into statements",
            fix=_FIX_SIZING,
        )
    return name


def _varint_width_sql(expr: str) -> str:
    """A SQL expression for how many bytes SQLite's varint encoding gives `expr`."""
    arms = " ".join(
        f"WHEN ({expr}) <= {bound} THEN {width}"
        for width, bound in enumerate(_VARINT_BOUNDS, start=1)
    )
    return f"CASE {arms} ELSE {len(_VARINT_BOUNDS) + 1} END"


def _payload_sql(column: str) -> str:
    """A SQL expression for one column's BODY bytes in the record format.

    NULL costs zero bytes and so do the integers 0 and 1: serial types 0, 8 and 9 carry the value
    in the type itself. That is not a rounding. `state`, `revision`, `restriction_bits`, `gen` and
    `layer` are 0 on very nearly every row of a healthy store, and charging each of them a byte
    would inflate 07:1024's "~20 small ints" row by a fifth against the file it is measured over.
    """
    col = _require_ident(column)
    ints = " ".join(
        f"WHEN {col} BETWEEN {-bound - 1} AND {bound} THEN {w}" for bound, w in _INT_WIDTHS
    )
    return (
        f"CASE typeof({col})"
        " WHEN 'null' THEN 0"
        " WHEN 'real' THEN 8"
        f" WHEN 'integer' THEN (CASE WHEN {col} IN (0, 1) THEN 0 {ints} ELSE 8 END)"
        f" ELSE length(CAST({col} AS BLOB)) END"
    )


def _serial_width_sql(column: str) -> str:
    """A SQL expression for the bytes one column costs in the record HEADER (its serial type)."""
    col = _require_ident(column)
    body = _payload_sql(col)
    return (
        f"CASE WHEN typeof({col}) IN ('text', 'blob') THEN"
        f" (CASE WHEN ({body}) <= {_TEXT_1B} THEN 1"
        f" WHEN ({body}) <= {_TEXT_2B} THEN 2"
        f" WHEN ({body}) <= {_TEXT_3B} THEN 3 ELSE 4 END)"
        " ELSE 1 END"
    )


def _header_sql(widths: str) -> str:
    """Total header bytes given the summed serial-type widths -- solved, not approximated.

    The header's first field is the header's OWN length as a varint, so the length includes itself
    and `H = W + varint_width(H)` is implicit. It is solved by trying each varint width in
    increasing order, which terminates because `varint_width` is monotone in its argument.
    """
    arms = " ".join(
        f"WHEN ({widths}) + {width} <= {bound} THEN ({widths}) + {width}"
        for width, bound in enumerate(_VARINT_BOUNDS[:3], start=1)
    )
    return f"CASE {arms} ELSE ({widths}) + 4 END"


class _Column(NamedTuple):
    """One column of a table, and whether it is the rowid alias.

    `INTEGER PRIMARY KEY` IS the rowid: the record stores a NULL in its place, so it costs one
    header byte and no body. Charging it its integer width would double-count the rowid the cell
    already carries as its own varint, and would add roughly 4 B/block to 07:1024's row for free.
    """

    name: str
    rowid_alias: bool


def _columns_of(connection: sqlite3.Connection, table: str) -> tuple[_Column, ...]:
    """Every column of `table`, in declaration order, with the rowid alias flagged.

    `PRAGMA table_info` gives `(cid, name, type, notnull, dflt_value, pk)`. A column is the rowid
    alias when it is the sole primary key AND its declared type is exactly `INTEGER` -- `pk = 1`
    on a two-column primary key is a position within the key and not an alias, and
    `sqlite_schema`'s own `WITHOUT ROWID` tables have no alias at all.
    """
    name = _require_ident(table)
    rows = connection.execute(f"PRAGMA table_info({name})").fetchall()
    pk_columns = [row for row in rows if int(row[5]) > 0]
    alias = ""
    if len(pk_columns) == 1 and str(pk_columns[0][2]).strip().upper() == "INTEGER":
        alias = str(pk_columns[0][1])
    return tuple(_Column(str(row[1]), str(row[1]) == alias) for row in rows)


def _is_without_rowid(connection: sqlite3.Connection, table: str) -> bool:
    """True when `table` is `WITHOUT ROWID`, whose rows live in an index b-tree and carry no rowid.

    Read off the DDL text in `sqlite_schema` because SQLite exposes no pragma for it. The check is
    on the whole statement rather than its tail: `0001_init.sql:408` and `0003_index.sql:282` both
    put a trailing comment after the clause, so anchoring at the end would answer False for `part`
    and `block_sec`, and each of those would then be charged a rowid varint it does not have.
    """
    row = connection.execute(
        "SELECT sql FROM sqlite_schema WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return bool(row) and "WITHOUT ROWID" in str(row[0]).upper()


def _cell_bytes_sql(columns: Sequence[_Column], *, without_rowid: bool) -> str:
    """A SQL expression for one row's total b-tree CELL bytes, header and body and varints.

    The two b-tree cell layouts differ in exactly one field. A table b-tree cell is
    `[payload-size varint][rowid varint][payload]`; an index b-tree cell -- which is what a
    `WITHOUT ROWID` table's rows are -- is `[payload-size varint][payload]` with the key columns
    inside the payload like any other. Both are computed here; neither includes the two-byte cell
    pointer in the page's array or any page-level slack, which is the b-tree overhead
    `SizingReport.bytes_per_block` picks up and this expression cannot see.
    """
    bodies = [f"({_payload_sql(c.name)})" for c in columns if not c.rowid_alias]
    widths = [("1" if c.rowid_alias else f"({_serial_width_sql(c.name)})") for c in columns]
    body = " + ".join(bodies) if bodies else "0"
    header = _header_sql(" + ".join(widths) if widths else "0")
    payload = f"(({header}) + ({body}))"
    cell = f"{payload} + ({_varint_width_sql(payload)})"
    if not without_rowid:
        cell = f"{cell} + ({_varint_width_sql('rowid')})"
    return cell


def _table_bytes(connection: sqlite3.Connection, table: str) -> tuple[int, int]:
    """`(rows, record bytes)` for one whole table, or `(0, 0)` when the table does not exist.

    A missing table is zero and not an error: `0003_index.sql` ships `ref_site` and `block_sec`,
    and a store migrated only as far as 0001 legitimately has neither. `residue()` takes the
    opposite line for INV-25's four tables because their ABSENCE is the thing it reports on; here
    the question is how many bytes they occupy, and a table that does not exist occupies none.
    """
    columns = _columns_of(connection, table)
    if not columns:
        return (0, 0)
    cell = _cell_bytes_sql(columns, without_rowid=_is_without_rowid(connection, table))
    # S608: `table` is a module-constant literal and every column name came from
    # `PRAGMA table_info` through `_require_ident`; nothing here reaches a caller's string.
    sql = f"SELECT count(*), coalesce(sum({cell}), 0) FROM {_require_ident(table)}"  # noqa: S608
    rows, total = connection.execute(sql).fetchone()
    return (int(rows), int(total))


# --------------------------------------------------------------------------------------------
# 4.2 The decomposition. TRANSCRIBED from 07:1021-1037; only the measurement is this module's.
# --------------------------------------------------------------------------------------------

_SCALAR_COLUMNS: Final[tuple[str, ...]] = (
    "doc_ord",
    "gen",
    "page",
    "parent_id",
    "ord",
    "kind",
    "layer",
    "revision",
    "os_kind",
    "os_a",
    "os_b",
    "ts_a",
    "ts_b",
    "producer_id",
    "method",
    "trust",
    "score",
    "quote",
    "driver_schema_v",
    "restriction_bits",
    "state",
)
"""07:1024's *"~20 small ints"*, named. There are twenty-one, and `score` is a REAL rather than an
int -- the plan's parenthetical is an order of magnitude and not a census, so the list is the
schema's (`0001_init.sql:235-282`) and the count is reported rather than argued with."""


class _ComponentSpec(NamedTuple):
    """One row of 07:1021-1037, plus what has to be measured to answer it.

    `component`, `plan_line` and `estimated` are TRANSCRIBED. Everything else is this module's
    reading of what the row's prose names: which `block` columns, which whole tables, which
    `sqlite_schema` objects only `dbstat` can weigh, and which fts5 tables' shadow families.
    """

    key: str
    component: str
    plan_line: int
    estimated: float
    columns: tuple[str, ...] = ()
    tables: tuple[str, ...] = ()
    objects: tuple[str, ...] = ()
    fts: tuple[str, ...] = ()
    row_overhead: bool = False


DECOMPOSITION: Final[tuple[_ComponentSpec, ...]] = (
    _ComponentSpec(
        "text",
        "`block` row: `text`",
        1023,
        140.0,
        columns=("text",),
    ),
    _ComponentSpec(
        "scalars",
        "`block` row: fixed scalars (~20 small ints) + row header",
        1024,
        35.0,
        columns=_SCALAR_COLUMNS,
        row_overhead=True,
    ),
    _ComponentSpec(
        "addr_cite",
        "`block` row: `addr` + `cite`",
        1025,
        16.0,
        columns=("addr", "cite"),
    ),
    _ComponentSpec(
        "digests",
        "`block` row: `content_digest` + `layout_digest`",
        1026,
        34.0,
        columns=("content_digest", "layout_digest"),
    ),
    _ComponentSpec(
        "quad",
        "`block` row: `quad`",
        1027,
        34.0,
        columns=("quad",),
    ),
    _ComponentSpec(
        "provenance",
        "`block` row: `origin_operator`, `origin_driver`, `os_part`, `os_extractor`",
        1028,
        60.0,
        columns=("origin_operator", "origin_driver", "os_part", "os_extractor"),
    ),
    _ComponentSpec(
        "x_payload_raw",
        "`block` row: `x` (`'{}'`), `payload` (NULL), `raw_kind` (NULL)",
        1029,
        5.0,
        columns=("x", "payload", "raw_kind"),
    ),
    _ComponentSpec(
        "block_indexes",
        "nine `block` indexes",
        1031,
        130.0,
        objects=BLOCK_INDEXES,
    ),
    _ComponentSpec(
        "block_fts",
        "`block_fts` inverted index + docsize",
        1032,
        70.0,
        fts=("block_fts",),
    ),
    _ComponentSpec(
        "head_fts",
        "`head_fts`",
        1033,
        2.0,
        fts=("head_fts",),
    ),
    _ComponentSpec(
        "block_sec",
        "`block_sec` row + `block_sec_path`",
        1034,
        50.0,
        tables=("block_sec",),
        objects=("block_sec_path",),
    ),
    _ComponentSpec(
        "segment_block",
        "`segment_block` row",
        1035,
        20.0,
        tables=("segment_block",),
    ),
    _ComponentSpec(
        "sparse",
        "`mark`, `rel`, `ref_site` (sparse, amortised)",
        1036,
        40.0,
        tables=("mark", "rel", "ref_site"),
    ),
)
"""07:1023-1036's thirteen component rows. The subtotal (07:1030) and the total (07:1037) are
COMPUTED and are not rows here, because a transcribed subtotal that disagreed with the rows above
it would be a second definition site for the same fact (rule: count definition sites)."""

UNLISTED: Final = "unlisted"
"""The key of the row this module ADDS, for `block` columns 07:1023-1029 does not name.

**This is a reported defect, not an invention.** See `DEFECT 5` in the module docstring: the
plan's seven `block`-row rows cover thirty-four of the table's forty columns, and the remaining
five (`label`, `os_path`, `os_codec`, `score_kind`, `decision_id`) are charged to nothing. They
are not free -- `os_codec` alone is `'utf-8/strict'`, thirteen bytes on every text block with a
byte origin -- so the row exists with NO estimate and a measured figure, which lets a reviewer see
the gap rather than have it silently added to the subtotal.
"""

SUBTOTAL_LINE: Final = 1030
SUBTOTAL_ESTIMATE: Final = 324.0
"""07:1030, *"**`block` row subtotal** | **~324**"*."""

TOTAL_LINE: Final = 1037
TOTAL_ESTIMATE: Final = 636.0
"""07:1037, *"**Total** | **~636** | inside the 660 ± 10% budget"*.

The 660 is NOT transcribed here. It is a `[[budget]]` row and `eval/perf.toml` is its register
(12-performance.md:244, charter.md:7617-7622); a second copy in library code would be a second
definition site for a number the plan gives one home. `tools/measure_store.py` reads it there.
"""


# --------------------------------------------------------------------------------------------
# 4.3 What the report is
# --------------------------------------------------------------------------------------------


class StoreFiles(NamedTuple):
    """The three files a `.owstore` is, sized SEPARATELY.

    **The WAL is never folded into the database file's number.** A measurement taken with a fat
    WAL is a different measurement, and the plan already knows it: `wal.bulk_index_peak_bytes`
    exists as its own `[[budget]]` row at 12-performance.md:250 *"**absolute, not a percentage**,
    because a percentage of a growing number is not a bound: codegraph measured **5.9 GB of WAL
    against a 340 MB DB**, then 22 GB and exit 137."* A `bytes_per_block` computed over db + WAL
    on a store mid-bulk-index would read 18x its steady-state value, and a ratchet fed that number
    would never recover. So `db_bytes` is the ratchet's numerator, `total_bytes` is the disk's
    answer, and both are printed.

    `wal_present` and `shm_present` are separate from the sizes because a zero-byte WAL and no WAL
    at all are different states -- SQLite creates and truncates the sidecar rather than deleting
    it while any connection is open -- and an operator reading "0" needs to know which.
    """

    path: str
    db_bytes: int
    wal_bytes: int
    shm_bytes: int
    wal_present: bool
    shm_present: bool

    @property
    def total_bytes(self) -> int:
        """Everything on disk for this store. Not the ratchet's numerator; see the docstring."""
        return self.db_bytes + self.wal_bytes + self.shm_bytes


class KindCount(NamedTuple):
    """One `enum_val` kind's population and record cost.

    `name` is read out of the store's own `enum_val` table rather than out of `model.Kind`, which
    keeps this module free of the model import and, more usefully, makes the report readable for a
    store written by a newer `model_version` than the reader's (03 section 4.2 makes adding a Kind
    a MINOR). A kind ordinal with no `enum_val` row is reported as `kind:<ord>` rather than
    dropped, because a block that cannot be named is exactly the one a reviewer needs to see.
    """

    name: str
    ordinal: int
    blocks: int
    live: int
    text_bytes: int
    row_bytes: int

    @property
    def bytes_per_block(self) -> float:
        """Record bytes per block of this kind. `0.0` when the kind has no rows."""
        return 0.0 if self.blocks == 0 else self.row_bytes / self.blocks


class CompositionSize(NamedTuple):
    """One of contract F4's three compositions, sized. See `COMPOSITIONS` for why three.

    `row_bytes` is the record cost of the group's blocks; there is deliberately no per-composition
    FILE figure, because the file's indexes, FTS and free pages cannot be attributed to a subset
    of rows without inventing an allocation rule. `share` is the group's fraction of all blocks,
    which is the number that makes the aggregate interpretable.
    """

    composition: str
    kinds: tuple[str, ...]
    blocks: int
    text_bytes: int
    row_bytes: int
    corpus_blocks: int

    @property
    def bytes_per_block(self) -> float:
        """Record bytes per block within this composition. `0.0` on an empty group."""
        return 0.0 if self.blocks == 0 else self.row_bytes / self.blocks

    @property
    def text_bytes_per_block(self) -> float:
        """07:1023's own quantity: *"A prose paragraph is ~300 B; a table cell is ~10 B."*"""
        return 0.0 if self.blocks == 0 else self.text_bytes / self.blocks

    @property
    def share(self) -> float:
        """This composition's fraction of all blocks in the store. `0.0` on an empty store."""
        return 0.0 if self.corpus_blocks == 0 else self.blocks / self.corpus_blocks


class ComponentCost(NamedTuple):
    """One row of 07:1021-1037, estimated beside measured. The unit of the attackable table.

    `estimated` is `None` on exactly one row, `UNLISTED`, which the plan does not carry. `measured`
    is `None` when `state` is `UNCHECKED`. `covers` is prose and says what the measured number is
    over -- it is the field that keeps `PARTIAL` from reading like a smaller `MEASURED`.
    """

    key: str
    component: str
    plan_line: int
    estimated: float | None
    measured: float | None
    state: str
    covers: str = ""
    reason: str = ""

    @property
    def delta(self) -> float | None:
        """`measured - estimated`, or `None` when either side is missing."""
        if self.measured is None or self.estimated is None:
            return None
        return self.measured - self.estimated


class SizingReport(NamedTuple):
    """What a sizing run found. Read-only, clock-free, and carrying no verdict.

    No `ok` field and no budget: 12-performance.md:1966 makes `ow-bench-1` the only machine a
    Budget may live on, so nothing computed here can be a pass or a fail. `render()` prints the
    numbers and the labels that qualify them; `tools/measure_store.py` prints the comparison and
    the sentence that says a comparison is not a verdict.
    """

    files: StoreFiles
    blocks: int
    live_blocks: int
    pages: int
    documents: int
    kinds: tuple[KindCount, ...]
    compositions: tuple[CompositionSize, ...]
    components: tuple[ComponentCost, ...]
    page_size: int
    page_count: int
    freelist_pages: int
    dbstat: bool
    dbstat_reason: str = ""

    @property
    def bytes_per_block(self) -> float:
        """The `store.bytes_per_block` quantity: the DATABASE FILE over the block count.

        The database file and not the file plus its WAL -- `StoreFiles`' docstring works out why,
        and `bytes_per_block_on_disk` is the other number for a caller that wants it. `0.0` on a
        store with no blocks, because a ratio with a zero denominator is not "infinite bytes per
        block", it is "this corpus does not answer the question".
        """
        return 0.0 if self.blocks == 0 else self.files.db_bytes / self.blocks

    @property
    def bytes_per_block_on_disk(self) -> float:
        """The same ratio over db + `-wal` + `-shm`. Reported so the WAL's weight is visible."""
        return 0.0 if self.blocks == 0 else self.files.total_bytes / self.blocks

    @property
    def record_bytes_per_block(self) -> float:
        """Summed `block` record bytes over blocks -- the subtotal row, without b-tree slack."""
        row = self.component("subtotal")
        return 0.0 if row.measured is None else row.measured

    @property
    def blocks_per_page(self) -> float:
        """Blocks per PAGE of the corpus. **A property of this corpus, never F1's answer.**

        F1 is *"the blocks-per-page envelope"* and 03-document-model.md:3086 states what closes
        it: `fixtures/gen/gen_5000p_pdf.py` **plus ten real 200-page documents** -- a 10-K, a court
        filing, a scientific review, a spreadsheet-heavy report. A number measured over a
        synthetic fixture whose paragraph and cell counts a person chose is a number about that
        person's choice. `render()` prints the qualification on the same line as the figure, not
        in a footnote, because a footnote is what gets quoted without.
        """
        return 0.0 if self.pages == 0 else self.blocks / self.pages

    def composition(self, name: str) -> CompositionSize:
        """One composition by name, raising rather than returning `None` for an unknown one."""
        for row in self.compositions:
            if row.composition == name:
                return row
        raise KeyError(f"{name!r} is not one of {COMPOSITIONS}")

    def component(self, key: str) -> ComponentCost:
        """One decomposition row by key, raising for an unknown one."""
        for row in self.components:
            if row.key == key:
                return row
        raise KeyError(f"{key!r} is not a row of 07:1021-1037's decomposition")

    def kind(self, name: str) -> KindCount:
        """One kind's counts by `enum_val` name, raising for a kind this store has no rows of."""
        for row in self.kinds:
            if row.name == name:
                return row
        raise KeyError(f"this store has no blocks of kind {name!r}")

    def render(self) -> str:
        """The whole report as LF-only text, sorted, with no clock and no absolute path in it.

        Byte-stable for a given store, like `ExplainReport.render()` and for the same reason: a
        report a reviewer diffs between two runs must not move for reasons unrelated to the store.
        The store's name is printed and its directory is not, so two runs in two tempdirs render
        identically.
        """
        return "\n".join(_render_lines(self)) + "\n"


# --------------------------------------------------------------------------------------------
# 4.4 Measuring it
# --------------------------------------------------------------------------------------------

WAL_SUFFIX: Final = "-wal"
SHM_SUFFIX: Final = "-shm"
"""SQLite's two sidecars. `store/sqlite.py:225` states the property that makes them worth sizing:
*"a plain read-write open of a WAL-mode database creates `-shm` and `-wal` whether or not any
pragma is issued"*, so their absence is information and so is their presence at zero bytes."""

_NO_DBSTAT: Final = (
    "this SQLite was built without SQLITE_ENABLE_DBSTAT_VTAB, so no page-level cost is available "
    "for indexes or FTS shadow tables"
)
"""The degraded path's reason string, in `verify._unchecked()`'s register: what could not be
read, and why, rather than a silence that reads like a zero."""


def _store_files(path: Path) -> StoreFiles:
    """Size the `.owstore` and each sidecar, separately. A missing file is 0 and `present=False`."""
    wal = path.with_name(path.name + WAL_SUFFIX)
    shm = path.with_name(path.name + SHM_SUFFIX)
    return StoreFiles(
        path=path.name,
        db_bytes=path.stat().st_size if path.exists() else 0,
        wal_bytes=wal.stat().st_size if wal.exists() else 0,
        shm_bytes=shm.stat().st_size if shm.exists() else 0,
        wal_present=wal.exists(),
        shm_present=shm.exists(),
    )


def _dbstat_pages(connection: sqlite3.Connection) -> tuple[dict[str, int] | None, str]:
    """`{object name: bytes}` from `dbstat`, or `(None, reason)` when the build has no `dbstat`.

    The probe is a query and not a `compile_options` scan, because a compile option that is
    present and a virtual table that resolves are two different claims and only the second one is
    the one being relied on. `sqlite3.OperationalError` is the exact failure -- SQLite reports a
    missing eponymous virtual table as `no such table: dbstat` -- and it is caught rather than
    allowed out, because a sizing report that cannot weigh indexes is degraded and not broken.
    """
    try:
        rows = connection.execute("SELECT name, sum(pgsize) FROM dbstat GROUP BY name").fetchall()
    except sqlite3.OperationalError as exc:
        return (None, f"{_NO_DBSTAT} ({exc})")
    return ({str(name): int(size or 0) for name, size in rows}, "")


def _objects_present(connection: sqlite3.Connection, names: Sequence[str]) -> tuple[str, ...]:
    """Which of `names` exist in `sqlite_schema` at all, as tables, indexes or virtual tables."""
    if not names:
        return ()
    marks = ", ".join("?" for _ in names)
    # S608: `marks` is a run of bind placeholders; every value is bound, not interpolated.
    sql = f"SELECT name FROM sqlite_schema WHERE name IN ({marks})"  # noqa: S608
    return tuple(sorted(str(row[0]) for row in connection.execute(sql, tuple(names))))


def _fts_shadow_names(connection: sqlite3.Connection, base: str) -> tuple[str, ...]:
    """Every shadow table an fts5 table `base` actually shipped, plus `base` itself if present.

    An fts5 virtual table stores nothing under its own name -- the bytes are in `<base>_data`,
    `_idx`, `_docsize`, `_content` and `_config` -- and which of those exist depends on the
    options: `block_fts` is external-content (07:1032, *"external-content, so no second text
    copy"*), so it has no `_content` table and asking `dbstat` for one would return nothing
    rather than fail. Both are handled by listing what is there.
    """
    candidates = [base, *(base + suffix for suffix in _FTS_SHADOWS)]
    return _objects_present(connection, candidates)


def _scan_blocks(
    connection: sqlite3.Connection,
) -> tuple[dict[int, tuple[int, int, int, int]], dict[str, int], int, int]:
    """One pass over `block`. Returns per-kind counts and the corpus-wide column-group totals.

    The per-kind tuple is `(blocks, live, text body bytes, record bytes)` and the second return is
    `{group key: bytes}` over the seven `block`-row groups of 07:1023-1029 plus `UNLISTED`. The
    last two are the summed record bytes and the summed per-row overhead.

    **Charging rule, stated because the plan's table does not state it.** Each column is charged
    its BODY plus its own serial-type byte, to the group that names it; the row's remaining
    varints -- the header's own length, the payload size, the rowid, and the one serial byte the
    `INTEGER PRIMARY KEY` costs -- go to the `scalars` group, because that is the only row of
    07:1023-1029 that says *"+ row header"* (07:1024). Every byte of the record is charged exactly
    once under this rule, which is what makes the measured subtotal add up to the measured cell.
    """
    columns = _columns_of(connection, "block")
    by_group: dict[str, tuple[str, ...]] = {
        spec.key: tuple(c for c in spec.columns if c in {col.name for col in columns})
        for spec in DECOMPOSITION
        if spec.columns
    }
    claimed = {name for names in by_group.values() for name in names}
    by_group[UNLISTED] = tuple(
        col.name for col in columns if col.name not in claimed and not col.rowid_alias
    )
    keys = tuple(by_group)

    def group_sql(key: str) -> str:
        names = by_group[key]
        if not names:
            return "0"
        return " + ".join(f"(({_payload_sql(n)}) + ({_serial_width_sql(n)}))" for n in names)

    cell = _cell_bytes_sql(columns, without_rowid=False)
    charged = " + ".join(f"({group_sql(key)})" for key in keys)
    selects = ", ".join(f"sum({group_sql(key)})" for key in keys)
    # S608: every interpolated name came from `PRAGMA table_info` through `_require_ident`, and
    # every literal in the CASE arms is a module constant. No caller string reaches this SQL.
    sql = (
        f"SELECT kind, count(*), sum(state = 0), sum({_payload_sql('text')}), sum({cell}), "  # noqa: S608
        f"sum(({cell}) - ({charged})), {selects} FROM block GROUP BY kind ORDER BY kind"
    )
    per_kind: dict[int, tuple[int, int, int, int]] = {}
    totals: dict[str, int] = dict.fromkeys(keys, 0)
    record_bytes = 0
    overhead = 0
    for row in connection.execute(sql):
        per_kind[int(row[0])] = (int(row[1]), int(row[2]), int(row[3]), int(row[4]))
        record_bytes += int(row[4])
        overhead += int(row[5])
        for offset, key in enumerate(keys, start=6):
            totals[key] += int(row[offset])
    return (per_kind, totals, record_bytes, overhead)


def _kind_names(connection: sqlite3.Connection) -> dict[int, str]:
    """`{ordinal: name}` from the store's own `enum_val`. See `KindCount` for why not `model`."""
    return {
        int(ord_): str(name)
        for ord_, name in connection.execute(
            "SELECT ord, name FROM enum_val WHERE domain = 'kind' ORDER BY ord"
        )
    }


def _compositions(kinds: Sequence[KindCount], corpus_blocks: int) -> tuple[CompositionSize, ...]:
    """The three F4 groups, folded out of the per-kind counts. One store, measured once."""
    members: dict[str, frozenset[str]] = {
        PROSE: PROSE_KINDS,
        CELLS: CELL_KINDS,
        MIXED: frozenset(row.name for row in kinds),
    }
    out: list[CompositionSize] = []
    for name in COMPOSITIONS:
        chosen = [row for row in kinds if row.name in members[name]]
        out.append(
            CompositionSize(
                composition=name,
                kinds=tuple(sorted(row.name for row in chosen)),
                blocks=sum(row.blocks for row in chosen),
                text_bytes=sum(row.text_bytes for row in chosen),
                row_bytes=sum(row.row_bytes for row in chosen),
                corpus_blocks=corpus_blocks,
            )
        )
    return tuple(out)


def _per(total: float, blocks: int) -> float:
    """`total / blocks`, or `0.0` on an empty corpus. See `bytes_per_block` for why not infinity."""
    return 0.0 if blocks == 0 else total / blocks


def _one_component(
    connection: sqlite3.Connection,
    spec: _ComponentSpec,
    *,
    blocks: int,
    group_bytes: Mapping[str, int],
    overhead: int,
    pages_by_name: Mapping[str, int] | None,
    dbstat_reason: str,
) -> ComponentCost:
    """Measure one row of 07:1021-1037, degrading to `PARTIAL` or `UNCHECKED` with a reason."""
    measured = 0.0
    covers: list[str] = []
    if spec.columns:
        measured += group_bytes.get(spec.key, 0)
        covers.append(f"{len(spec.columns)} `block` column(s)")
    if spec.row_overhead:
        measured += overhead
        covers.append("the row's header, payload and rowid varints")
    for table in spec.tables:
        rows, table_bytes = _table_bytes(connection, table)
        measured += table_bytes
        covers.append(f"`{table}` ({rows} row(s))")

    wanted: list[str] = list(_objects_present(connection, spec.objects))
    for base in spec.fts:
        wanted.extend(_fts_shadow_names(connection, base))
    absent = tuple(n for n in (*spec.objects, *spec.fts) if n not in wanted)
    if wanted and pages_by_name is None:
        state = PARTIAL if covers else UNCHECKED
        return ComponentCost(
            key=spec.key,
            component=spec.component,
            plan_line=spec.plan_line,
            estimated=spec.estimated,
            measured=_per(measured, blocks) if covers else None,
            state=state,
            covers="; ".join(covers),
            reason=f"{dbstat_reason or _NO_DBSTAT}: {', '.join(sorted(wanted))} unweighed",
        )
    if wanted and pages_by_name is not None:
        measured += sum(pages_by_name.get(name, 0) for name in wanted)
        covers.append(f"{len(wanted)} object(s) via dbstat")
    if absent and not wanted:
        covers.append(f"{', '.join(absent)} not in this store")
    return ComponentCost(
        key=spec.key,
        component=spec.component,
        plan_line=spec.plan_line,
        estimated=spec.estimated,
        measured=_per(measured, blocks),
        state=MEASURED,
        covers="; ".join(covers),
    )


def _components(
    connection: sqlite3.Connection,
    *,
    blocks: int,
    group_bytes: Mapping[str, int],
    record_bytes: int,
    overhead: int,
    pages_by_name: Mapping[str, int] | None,
    dbstat_reason: str,
) -> tuple[ComponentCost, ...]:
    """Every row of the decomposition, plus `UNLISTED`, the subtotal and the total.

    The subtotal and the total are COMPUTED from the rows above them and are not transcribed
    numbers with a second life -- 07:1030 and 07:1037 supply the ESTIMATE for each, which is the
    only half of those two rows the plan owns.
    """
    rows = [
        _one_component(
            connection,
            spec,
            blocks=blocks,
            group_bytes=group_bytes,
            overhead=overhead,
            pages_by_name=pages_by_name,
            dbstat_reason=dbstat_reason,
        )
        for spec in DECOMPOSITION
    ]
    unlisted = ComponentCost(
        key=UNLISTED,
        component="`block` row: columns 07:1023-1029 does not name",
        plan_line=0,
        estimated=None,
        measured=_per(group_bytes.get(UNLISTED, 0), blocks),
        state=MEASURED,
        covers="`label`, `os_path`, `os_codec`, `score_kind`, `decision_id` -- see DEFECT 5",
    )
    subtotal = ComponentCost(
        key="subtotal",
        component="**`block` row subtotal**",
        plan_line=SUBTOTAL_LINE,
        estimated=SUBTOTAL_ESTIMATE,
        measured=_per(record_bytes, blocks),
        state=MEASURED,
        covers="every `block` column and every per-row varint; NOT b-tree page slack",
    )
    contributing = [*rows, unlisted]
    degraded = [row for row in contributing if row.state != MEASURED]
    total = ComponentCost(
        key="total",
        component="**Total**",
        plan_line=TOTAL_LINE,
        estimated=TOTAL_ESTIMATE,
        measured=sum(row.measured or 0.0 for row in contributing),
        state=MEASURED if not degraded else PARTIAL,
        covers="the sum of the rows above, INCLUDING the unlisted columns the plan omits",
        reason=(
            ""
            if not degraded
            else f"{len(degraded)} row(s) could not be measured in full: "
            f"{', '.join(row.key for row in degraded)}"
        ),
    )
    return (*rows[:7], unlisted, subtotal, *rows[7:], total)


def store_sizing(connection: sqlite3.Connection, *, path: Path) -> SizingReport:
    """Size a store: files, blocks, compositions, and 07:1021-1037's decomposition measured.

    Read-only. Takes `path` as well as `connection` because three of the numbers are not in the
    database at all -- the `.owstore`'s own size and its two sidecars' -- and asking SQLite for
    `page_count * page_size` would answer a different question: it omits the WAL entirely and it
    counts free pages the file has already given back. Both figures are reported, and the gap
    between them is a fact about the store (see `SizingReport`).

    **`bytes_per_block` here is a measurement and never a verdict.** 12-performance.md:1966 makes
    `ow-bench-1` the only machine a `[[budget]]` may live on; a number from any other machine is a
    number, and the comparison against `store.bytes_per_block = 660` belongs to a caller that
    prints that sentence alongside it (`tools/measure_store.py` does).

    **`blocks_per_page` is a property of the corpus, never F1's answer.** 03-document-model.md:3086
    is explicit that closing F1 takes the generator PLUS ten real 200-page documents, and this
    function will happily divide by whatever `page` rows it finds. `render()` says so on the line.

    Degrades rather than failing when `dbstat` is absent: `SizingReport.dbstat` is False,
    `dbstat_reason` says why, and every component that needed page-level accounting reports
    `PARTIAL` or `UNCHECKED` with the same reason attached to it (`store/verify.py`'s
    `_unchecked()` register).
    """
    pages_by_name, dbstat_reason = _dbstat_pages(connection)
    per_kind, group_bytes, record_bytes, overhead = _scan_blocks(connection)
    names = _kind_names(connection)
    kinds = tuple(
        KindCount(
            name=names.get(ordinal, f"kind:{ordinal}"),
            ordinal=ordinal,
            blocks=counts[0],
            live=counts[1],
            text_bytes=counts[2],
            row_bytes=counts[3],
        )
        for ordinal, counts in sorted(per_kind.items())
    )
    blocks = sum(row.blocks for row in kinds)
    page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
    page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
    freelist = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
    return SizingReport(
        files=_store_files(path),
        blocks=blocks,
        live_blocks=sum(row.live for row in kinds),
        pages=int(connection.execute("SELECT count(*) FROM page").fetchone()[0]),
        documents=int(connection.execute("SELECT count(*) FROM doc").fetchone()[0]),
        kinds=kinds,
        compositions=_compositions(kinds, blocks),
        components=_components(
            connection,
            blocks=blocks,
            group_bytes=group_bytes,
            record_bytes=record_bytes,
            overhead=overhead,
            pages_by_name=pages_by_name,
            dbstat_reason=dbstat_reason,
        ),
        page_size=page_size,
        page_count=page_count,
        freelist_pages=freelist,
        dbstat=pages_by_name is not None,
        dbstat_reason=dbstat_reason,
    )


# --------------------------------------------------------------------------------------------
# 4.5 Rendering it. Every qualification is on the line it qualifies -- see `SizingReport.render`.
# --------------------------------------------------------------------------------------------

FIXTURE_CAVEAT: Final = (
    "a property of THIS corpus, not F1's answer -- 03-document-model.md:3086 needs the "
    "generator PLUS ten real 200-page documents"
)
"""Printed on the `blocks/page` line itself. F1 splits: bytes/block is the store variable and
blocks/page is the corpus variable, and only the first of them can be answered by a fixture."""

MACHINE_CAVEAT: Final = (
    "a MEASUREMENT, not a budget verdict: 12-performance.md:1966 makes ow-bench-1 the only "
    "machine a [[budget]] may live on"
)
"""Printed by every caller that puts a number next to `store.bytes_per_block`. It lives here so
the library and `tools/measure_store.py` cannot drift into two different disclaimers."""


def _render_lines(report: SizingReport) -> list[str]:
    """`SizingReport.render()`'s body. Split out so the properties above stay readable."""
    files = report.files
    out = [
        f"store sizing  {files.path}",
        f"  database          {files.db_bytes:>14,} B",
        f"  {WAL_SUFFIX:<16}  {files.wal_bytes:>14,} B  "
        f"{'present' if files.wal_present else 'absent'}  (NOT folded into bytes/block)",
        f"  {SHM_SUFFIX:<16}  {files.shm_bytes:>14,} B  "
        f"{'present' if files.shm_present else 'absent'}",
        f"  on disk           {files.total_bytes:>14,} B",
        f"  pages             {report.page_count:>14,} x {report.page_size} B, "
        f"{report.freelist_pages:,} free",
        "",
        f"documents {report.documents:,}   corpus pages {report.pages:,}   "
        f"blocks {report.blocks:,} ({report.live_blocks:,} live)",
        f"blocks/page        {report.blocks_per_page:>10.2f}   {FIXTURE_CAVEAT}",
        f"bytes/block        {report.bytes_per_block:>10.2f}   database file / blocks",
        f"bytes/block+wal    {report.bytes_per_block_on_disk:>10.2f}   "
        f"database + {WAL_SUFFIX} + {SHM_SUFFIX} / blocks",
        f"record B/block     {report.record_bytes_per_block:>10.2f}   `block` rows only, "
        f"no index, no FTS, no b-tree slack",
        "",
        "composition        blocks     share    rec B/blk   text B/blk   (07:1023: prose ~300 B, "
        "cell ~10 B)",
    ]
    for row in report.compositions:
        out.append(
            f"  {row.composition:<14} {row.blocks:>7,}  {row.share * 100:>7.2f}%  "
            f"{row.bytes_per_block:>10.2f}   {row.text_bytes_per_block:>10.2f}"
        )
    out.extend(["", "by kind            blocks       live     rec B/blk   text bytes"])
    for kind in report.kinds:
        out.append(
            f"  {kind.name:<14} {kind.blocks:>9,}  {kind.live:>9,}  "
            f"{kind.bytes_per_block:>10.2f}   {kind.text_bytes:>12,}"
        )
    out.extend(
        [
            "",
            f"dbstat             {'available' if report.dbstat else 'ABSENT'}"
            + (f"  {report.dbstat_reason}" if report.dbstat_reason else ""),
            "",
            "decomposition (07:1021-1037)" + " " * 48 + "line   estimated    measured  state",
        ]
    )
    for cost in report.components:
        line = "    --" if cost.plan_line == 0 else f"{cost.plan_line:>6}"
        estimate = "      --" if cost.estimated is None else f"{cost.estimated:>8.1f}"
        value = "        --" if cost.measured is None else f"{cost.measured:>10.2f}"
        out.append(f"  {cost.component:<74}{line}  {estimate}  {value}  {cost.state}")
        if cost.reason:
            out.append(f"        reason: {cost.reason}")
    return out
