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

import sqlite3
from typing import Final, NamedTuple

from omniweave_core.errors import StoreError
from omniweave_core.store import migrate
from omniweave_core.store.indexlock import LockFile, LockHeader, LockRow, read_lock

__all__ = [
    "DEFAULT_GROUP_LIMIT",
    "INDEX_REGISTER",
    "MS_PER_NS",
    "RESIDUE_TABLES",
    "ContainerShare",
    "DocDelta",
    "ExplainReport",
    "ExplainRow",
    "LockDiff",
    "RefGroup",
    "RegisteredIndex",
    "ResidueReport",
    "ResidueTable",
    "diff_lock",
    "diff_stores",
    "explain_indexes",
    "lock_rows",
    "residue",
]

_FIX_LOCK: Final = "ow store lock"
"""The command a caller runs when a receipt and a store disagree (07:3155)."""

_FIX_EXPLAIN: Final = "ow store explain --golden"
"""The verb whose golden output `explain_indexes` produces (07:956)."""

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
