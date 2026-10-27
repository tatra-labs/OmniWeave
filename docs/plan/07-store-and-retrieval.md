# Storage, Indexing and Retrieval

**In one paragraph.** One SQLite file per corpus — `.omniweave/index.owstore` — holds L2's document
model, L3's knowledge graph, L4's index layer and the operational tables, with exactly two derived,
separately-deletable sidecars (`index.vec.owstore` for vectors, `events.owstore` for the query
ledger) so no query process ever needs a write handle on the index. SQLite is the **published read
interface and the swappable write implementation**: four Protocols — `Store`, `Reader`, `DocSink`,
`GraphSink`, 33 methods — are the distribution boundary, and `sqlite3.connect` appears in exactly one
module. Retrieval is **five Channels** (`identity · exact · lexical · structural · semantic`) fused
by weighted RRF at one key, `block_id`, with a `ceiling()` that shares its weight function with
`fuse()` so the confidence number cannot silently rescale. The planner is pure, its narrowing
strategy is a closed three-way choice decided by an exact `LIMIT PREFILTER_MAX+1` probe rather than a
histogram, and its Channel selection is authored in D4's rule grammar verbatim under
`surface = "retrieval"`. A zero result is `absent` only after fifteen absence gates. The index is a
cache, it is `.gitignore`d, and the one committed artefact is `omniweave.index.lock`.

This document is the authoritative specification for the physical store, its indexes, its
maintenance, the query path and the retrieval result. It depends on
[the document model](03-document-model.md) for `Block`, `addr`, `cite`, `content_digest`,
`OriginSpan` and the `0001_init.sql` DDL; on [structure extraction](06-structure-extraction.md) for
`segment`, `anchor`, `entity`, `edge` and the segmenter; on [the runtime](08-runtime.md) for `unit`,
`work`, `cache_index`, `dep` and the write scheduler; on [generation](09-generation.md) for
`artifact_cite`; and on [interfaces](10-interfaces.md) for how a `Response` becomes an Answer. It
does not duplicate any of them.

## 1. The storage engine decision

**SQLite, one file per corpus, at `MIN_SQLITE = (3, 42, 0)`.** Not a vector database, not a graph
engine, not Postgres-as-a-prerequisite, not DuckDB, not a flat mmap array beside a database.

The justification is not "SQLite is fast enough". It is that every alternative adds a **second
durability story, a second snapshot story, a second migration story and a second failure domain**
before a user has parsed one document. omniweave has to answer "which pages are missing and why"
with an indexed join (absence gate 9 reads `diag`), has to hold a single consistent read across
6-12 statements (a query touches five Channels plus hydration plus the coverage scan), and has to
survive `kill -9` mid-ingest. One transactional file gives all three. Two storage systems give none
of them without a distributed-transaction argument nobody wants to make about a laptop.

The evidence for the choice is measured, not asserted:

| Claim | Number | Source |
|---|---|---|
| Graph edges at scale in SQLite with sub-ms reads | 6.4M relationships | codegraph (`.codegraph/codegraph.db`) |
| FTS5 external-content as the lexical Channel, memory-bounded at search time | replaces a full-corpus in-memory BM25 model | LEANN `_build_bm25_fts5`; codegraph `nodes_fts`. The counter-example is jcodemunch: `storage/sqlite_store.py:40-211` has **no FTS5 and no virtual tables at all** and scores BM25 in Python over token tables, which is why its lexical channel cannot be memory-bounded |
| Parquet as an alternative primary | 27% smaller, ~2,000x slower to point-read (42.8 ms vs 20 us), and immutable | [the document model](03-document-model.md) |
| Neo4j Community | GPLv3 into a stack G3 keeps clean with a fail-not-warn denylist | licence scan |
| A row-per-vector layout in pure SQLite | 1072 ms vs 466 ms per million — 2.3x the cursor overhead of a segment layout | §3.9 derives the mechanism: 62 cursor steps against 250,000 |

### 1.1 What is interface and what is implementation

The **interface** is four Protocols in `omniweave_core.store`, 33 methods in total. Nothing else
crosses the boundary. Saying "the store boundary is four methods" understates it by an order of
magnitude and would misprice any decision to swap the backend.

```python
class Store(Protocol):               # the QUEUE boundary. Four methods. Never widened.
    def claim(self, batch: int, gen: int, worker: str, lease_ms: int) -> Sequence["WorkRow"]: ...
    def complete(self, row_id: int, gen: int, result: "StepResult") -> bool: ...
    def reap_expired_leases(self, now_ms: int) -> int: ...
    def counts_by_status(self) -> Mapping[str, int]: ...

class Reader(Protocol):              # the RETRIEVAL boundary. A Postgres T3 implements this.
    def snapshot(self) -> ContextManager["Snapshot"]: ...
    def capabilities(self) -> "IndexCaps": ...
    def narrow(self, s: "Snapshot", f: "Filters") -> "Narrowing": ...
    def channel(self, s: "Snapshot", spec: "ChannelSpec", n: "Narrowing") -> "ChannelResult": ...
    def hydrate(self, s: "Snapshot", ids: Sequence[int]) -> Sequence["Hit"]: ...
    def coverage(self, s: "Snapshot", f: "Filters") -> "Coverage": ...

# DocSink (11 methods) writes L2 and is specified in 03-document-model.md.
# GraphSink (12 methods) writes L3 and is specified in 06-structure-extraction.md.
```

`Snapshot.token` is typed `object` and is **backend-private**. The SQLite implementation stores its
`sqlite3.Connection` there and is the only code that unwraps it, so INV-17 ("`sqlite3.connect`
appears in exactly one module") holds by construction *and* a Postgres `Reader` can construct a
`Snapshot` at all. Typing that field `sqlite3.Connection` would make T3 unrepresentable in the type
system — which is the premise the whole scale-out section rests on.

The **implementation** is everything else: the DDL in §3, the pragma order, the FTS5 options, the
maintenance schedule, the WAL valve, bulk windows, the temp-table narrowing probe, the `vec`
sidecar's `vseg` layout, and every index in §3.13. None of it appears in a signature. A caller that
reaches SQL outside `omniweave_core.store.sqlite` fails G24 and lint rule ST1.

There is a fifth boundary type here that is deliberately **not** one of the four Protocols: the
**`VectorBackend`**, declared by an `omniweave.backends` entry point plus a `backend.toml` read by
the same import-free loader as a DriverCard. It is a **Backend**, selected by name in config, never
a Port, never a DriverCard, never in `resolve()`. It is **not a fifth seam**: "seam" is the charter's
word for the four numbered process/FFI boundaries S1-S4 (charter §3.4, "The four seams, and no
fifth"), a fifth of those is a charter amendment, and a `VectorBackend` crosses none of them — it is
an in-process extension point behind a Protocol that is not on the T3 distribution boundary.

```python
class VectorBackend(Protocol):
    def manifest(self) -> "VecManifest": ...
    def upsert(self, model_key: str,
               rows: Iterable[tuple[bytes, bytes, bytes | None]]) -> int: ...  # digest, sig, full
    def search(self, model_key: str, q_sig: bytes, q_full: bytes | None, *, k: int,
               candidates: frozenset[bytes] | None) -> Sequence[tuple[bytes, float]]: ...
    def sweep(self, live: Callable[[], Iterable[bytes]]) -> int: ...
```

Four contract obligations, verified by `omniweave-conform`, each because a real system got it wrong:

1. **Filter pushdown is real** — `candidates` narrows *before* ranking, tested at 0.01 selectivity.
   LEANN post-filters metadata after ANN retrieval with no over-fetch, which is silent recall loss
   that presents as absence.
2. **Either epoch-immutable** (`search()` reads the version resolved at open) **or it returns
   `unavailable(rebuilding)`** — the afternoon-implementable floor. This is what replaced the
   rejected `index_epoch` + `epoch_lease` + reaper apparatus in the core schema.
3. **It declares a ceiling and REFUSES above it** rather than serving a slow query.
4. **recall@10 against exhaustive f32** on a fixed 50k fixture, with a committed floor.

There is no fifth write protocol anywhere: `DocSink` writes L2, `GraphSink` writes L3,
`Store.complete()` writes the queue, `VectorBackend.upsert()` writes vectors.

### 1.2 What it costs to swap

| Swap | What changes | What does not | Cost |
|---|---|---|---|
| SQLite → Postgres (T3) | one distribution implementing the four Protocols; a translated migration set; FTS5 → `tsvector`; `vseg` → `pgvector` or the identical BLOB layout; the narrowing TEMP table → an unlogged temp table | every caller, every type, every CLI verb, `block_id` allocation (the 16-bit shard prefix already ships), `omniweave.index.lock` | ~33 methods and ~40 DDL objects. **No operator change** — `[store] backend = "postgres"` and a path. That is the entire point of putting the boundary here. |
| stdlib vector scan → an ANN library | one `omniweave.backends` entry point + `backend.toml` | the store, the schema, `embed_space`, the semantic Channel's join, the four contract obligations | one distribution, shipped from its own repository exactly as a third-party Driver is |
| FTS5 → an external search service | `Reader.channel` for `lexical`, and the `exact` Channel's optional trigram rung | fusion, the ceiling, the Verdict, the planner | high, and unjustified: the lexical Channel would stop sharing the query's `Snapshot`, and ST2 ("one query = one snapshot") would become unenforceable |
| the `.owstore` → separate model and index files | nothing gains | — | rejected: it re-creates the model-plus-sync-layer failure the whole design refuses |

`omniweave-vector` is deliberately **not** a first-party distribution. Putting the ANN backend
inside `omniweave-graph` would force `tree-sitter` and a `<3.14` CPython ceiling onto anyone who
wants vectors.

## 2. Containers, pragmas and maintenance

```text
.omniweave/                              cache_root. NEVER inside source_root.
├── index.owstore                        L2 model + L3 graph + L4 index + ops.  THE file.
├── index.owstore-wal / -shm             healed at open above wal_heal_mb = 64
├── index.vec.owstore                    ATTACHed as `vec`. DERIVED. Deletable.
├── events.owstore                       retrieval_event. Per-user. DERIVED. Deletable.
├── cas/ab/cd/<sha256>                   retained `part` bytes, assets, page renders, IL bundles
├── jobs/<run_id>/…                      toolchain job directories
├── sessions/<key>.jsonl                 the serve journal
└── events/<run_id>.ndjson               the runtime event stream
omniweave.index.lock                     THE committed artefact (text, sorted, merge-driven)
.omniweave/policy.d/*.toml               D4's grammar, surface = "route" | "retrieval"
```

`rm -rf .omniweave` is a supported, documented, lossless operation, and every rule in this document
is subordinate to keeping that sentence true.

Both sidecars are SQLite, not raw files. A flat mmap array would add a second on-disk format with
its own torn-write, truncation and portability semantics for a benefit the `vseg` segment-BLOB
layout already delivers.

- **`index.vec.owstore` exists** because 3 KB/segment of float32 must not churn the writer's B-tree,
  WAL, backup and `VACUUM`.
- **`events.owstore` exists** because a query process opens the index `mode=ro` and *cannot* write
  it at all, and a read-write telemetry connection would take the index write lock on every query.
  When `cache_root` is itself read-only (a shared mount), the ledger falls back to
  `$OMNIWEAVE_HOME/events/<corpus_id>.owstore`; if that also fails the ledger is **off** and
  `ow doctor` says so, because telemetry never fails a query.
- **No transaction ever spans `main` and `vec`** (ST3). Atomic commit across attached databases does
  not hold in WAL mode. This is affordable because a vector row is only ever surfaced through an
  inner join to a live `segment` row in the *main* snapshot, so **a stale vector is invisible, never
  wrong** (ST4). Sweeps are an optimisation, not a correctness mechanism.

### 2.1 Pragmas, in this order, because the order is load-bearing

```python
CONN_PRAGMAS = (                     # per connection, IN THIS ORDER
    "busy_timeout = 5000",           # FIRST. journal_mode before this crashes a contended open.
    "foreign_keys = ON", "journal_mode = WAL", "synchronous = NORMAL",
    "cache_size = -64000", "temp_store = MEMORY", "mmap_size = 268435456")
INIT_PRAGMAS   = ("journal_size_limit = 67108864",)                  # persistent PER FILE
CREATE_PRAGMAS = ("page_size = 8192", "auto_vacuum = INCREMENTAL")   # CREATE time only
EVENT_PRAGMAS  = ("busy_timeout = 200", "journal_mode = WAL",        # events.owstore ONLY
                  "synchronous = OFF")
```

`busy_timeout` must be first because `journal_mode = WAL` itself touches the file and can raise
`SQLITE_BUSY` before the timeout is in effect — codegraph #238, an unreproducible startup crash.
`journal_size_limit` is required or the `-wal` file never shrinks below its high-water mark while a
connection lives: checkpoints fold frames back but leave the file at full size (codegraph #1431;
**25.6 GB** of leaked WAL observed across repeatedly-SIGKILLed sessions).

Two pragmas carry a second job beyond speed:

- **`temp_store = MEMORY`** is what makes the §6.1 narrowing probe legal on a `mode=ro` connection:
  an `INSERT` into a TEMP table is a write to the *temp* schema, and with an in-memory temp store
  there is no temp file to create, journal or leave behind on a read-only filesystem. The memory
  cost is bounded and sized in §4.5.
- **`mmap_size = 268435456`** (256 MB) is chosen to cover a full `vseg` scan at the stdlib backend's
  ceiling — 27.2 MB (§3.9) — plus the hot B-tree pages of a multi-GB store.

`EVENT_PRAGMAS` are deliberately weaker than the index's: `synchronous = OFF` and a 200 ms
`busy_timeout`, because a lost telemetry row is free and a blocked query is not. A `SQLITE_BUSY` on
the events file drops the batch and increments `store.events_dropped`.

`MIN_SQLITE = (3, 42, 0)` is the one declared floor in `omniweave_core.limits`, and it is three
features deep: STRICT tables need 3.37.0, `unixepoch()` needs 3.38.0, `unixepoch('subsec')` needs
3.42.0. `store/sqlite.py` refuses at open below it, naming `pip install omniweave-core[sqlite]`.

### 2.2 Maintenance: the four operations an unmaintained store silently loses

An embedded store that is only ever written and read degrades. Four maintenance operations run
**off the query path**, in the runtime's maintenance window ([the runtime](08-runtime.md) owns the
window; the operations, their statements and their bounds are this document's):

| Operation | Statement | Bound | Why it is not optional |
|---|---|---|---|
| planner statistics | `PRAGMA analysis_limit = 1000` then `PRAGMA optimize` | `analysis_limit` is the bound | codegraph: *"these pragmas are minutes of synchronous IO (a 95k-file kernel index)"* (`index.ts:677-712`), so they run off-thread with a **strictly smaller** inline fallback — never the same list run inline |
| FTS5 segment merge | `INSERT INTO block_fts(block_fts, rank) VALUES('merge', MERGE_PAGES)` | `MERGE_PAGES = 64`, at most `MERGE_STEPS = 16` per window | FTS5 writes one new segment per commit until `automerge` (left at its default, 4) folds them. An incrementally-written index accumulates segments, and the lexical Channel's p50 climbs with the **segment count**, not the row count |
| free-page reclaim | `PRAGMA incremental_vacuum(FREE_PAGES_PER_STEP)` | `FREE_PAGES_PER_STEP = 2048` (16 MB at `page_size = 8192`), triggered when `freelist_count / page_count > 0.25` | `auto_vacuum = INCREMENTAL` reclaims nothing on its own. A full re-parse retires one generation of every block, so the file holds up to ~2x its logical size until this runs. `ow store stats` prints `page_count` and `freelist_count` side by side |
| WAL fold | `foldNow()` — a full off-thread backfill, awaited | phase boundaries only (§10.5) | so the next phase never pages a bulk-write-sized WAL on the main thread |

`'optimize'` on an FTS5 table (`INSERT INTO block_fts(block_fts) VALUES('optimize')`) merges the
whole index into one segment and is **O(index)**. It runs only inside `ow store compact`, never in
the maintenance window and never on an interactive path. Likewise `VACUUM`: `ow store backup` is
`VACUUM INTO <path>` (atomic, no torn WAL) and `ow store compact` is a full `VACUUM` plus FTS
`'optimize'` plus `PRAGMA integrity_check`.

Both `VACUUM` and FTS `'optimize'` change physical row order, which is exactly why every Channel is
totally ordered on `(-score, (doc_ord, page, ord), block_id)` (ST7, D655) and why the ST7 property test VACUUMs.

`ow store repair`, named by ST13, is the recovery verb and is exactly four steps, in order:
(1) re-create every index named in `tools/indexes.toml` whose `sqlite_master` row is missing,
reading its DDL from `schema/` **by name** with a hard raise on a miss; (2) rebuild the FTS tables
(`INSERT INTO block_fts(block_fts) VALUES('rebuild')`) when `index_state.fts_state <> 'ok'`;
(3) run `PRAGMA foreign_key_check` and `PRAGMA integrity_check`; (4) re-derive `stat`. Only then is
`index_state.bulk_window` cleared.

## 3. The physical schema

Migrations apply **in numeric order to an empty file** on the declared `MIN_SQLITE` (gate G27b). The
order is the dependency order:

| File | Creates | Depends on |
|---|---|---|
| `0001_init.sql` | L2: `meta`, `enum_val`, `doc`, `page`, `producer`, `block`, `block_history`, `rel`, `mark`, `table_meta`, `cell`, `grid_slot`, `part`, `asset`, `block_asset`, `page_render`, `diag`, `block_fts` **and `block_fts`'s three sync triggers** | — |
| `0002_graph.sql` | L3: `segmenter`, `segment`, `segment_block`, `derive_pass`, `derive_run`, `derive_cover`, `entity`, `entity_alias`, `mention`, `edge`, `edge_evidence`, `claim`, `entity_merge`, `entity_band`, `anchor`, `relation_vocab`, `etype_vocab`, `quarantine`, `graph_history`, `community`, `community_member`, `community_report`, `graph_observation` | 0001 |
| `0003_index.sql` | **L4: this section** | 0002 |
| `0004_runtime.sql` | `unit`, `work`, `work_done`, `cache_index`, `dep`, `cohort`, `cohort_member`, `budget_reservation`, `run`, `service_observation`, `driver_observation`, `driver_card_cache`, `route_*` | 0001 |
| `0005_out.sql` | OUT: `artifact`, `artifact_unit`, `artifact_asset`, `artifact_cite`, `artifact_el` — the DDL is [generation](09-generation.md)'s | 0001 |

L4 reads three L3 objects — `segment`, `anchor` and `relation_vocab` — so L3 must be created first.
Under the earlier numbering, `0002` created an index on `segment`, a table `0003` had not created
yet, so `no such table: main.segment` aborted the migration and **neither file applied**.

The rule that follows from that failure is **three-way, not two-way**, and the third branch is a
SQLite-specific exception this document takes deliberately rather than leaves implicit:

| Object holding the forward reference | Name resolved at | Behaviour under `0001` → `0005` order |
|---|---|---|
| a **view** | first use | survives lazily — a `CREATE VIEW` naming a later file's table applies and only fails if it is selected from before that file runs |
| an **index** | `CREATE INDEX` | **aborts**, and takes G27b's whole run with it. This is the failure above, and it is why L3 precedes L4 |
| a **foreign key** | the first DML on the child row, **not** `CREATE TABLE` | survives — SQLite performs no DDL-time parent lookup, and a migration writes no rows |

**The one forward foreign key in the shipped order is `block.decision_id → route_decision`**, and it
is named here so nobody re-derives the hazard from the table above. `block` is created in
`0001_init.sql` ([the document model](03-document-model.md) §13.1) and every `route_*` table in
`0004_runtime.sql` ([routing](05-ingest-and-routing.md) §7.1, which prints the three tables and
names this file). Under `PRAGMA foreign_keys = ON` that `CREATE TABLE` still succeeds: the parent is
consulted when a non-NULL `decision_id` is written, which cannot happen until every migration has
applied. **The ordering stands and the rule gains the exception**, for three reasons stated so the
opposite resolution can be attacked: `0001_init.sql` is the L2 file and a routing table in it breaks
the layer-per-file correspondence the whole table above expresses; [routing](05-ingest-and-routing.md)
§7.1 is normative for `route_*` and already names `0004`, so hoisting them is a cross-document
renumbering with no defect to fix; and the exception is *checked* rather than assumed, by G27b
applying all five files in numeric order to an empty file and by §2.2's `ow store repair` running
`PRAGMA foreign_key_check` against the completed schema.

Legend: **[SOR]** system of record, part of the published read contract at this `SCHEMA` major;
**[DER]** derived and rebuildable by one command, not a read contract, droppable.

### 3.1 Schema compatibility: what a reader does with a file it did not write

`index_state.schema` holds `<major>.<minor>`, and it is the **only** place on disk that holds it —
`meta` never gains a `schema` key. The reader's own pair lives in `omniweave_core.contract`, as
`SCHEMA: int` (the major this build writes) and `SCHEMA_MINOR: int` (the minor), formatted
`f"{SCHEMA}.{SCHEMA_MINOR}"` at exactly one site, in `contract` itself. `SCHEMA_MINOR` resets to `0`
at a major bump, and it exists because two of the four rows below compare file minor against
**reader** minor. `omniweave_core.limits` holds no version constant, now or ever: it holds ceilings
and the one `MIN_SQLITE` floor ([architecture](02-architecture.md) §2 row 7). One code home and one
disk home — the same two [document model](03-document-model.md) §15.1 names.
There is one table and no `--force`:

| File vs reader | Behaviour |
|---|---|
| file major **>** reader major | **refuse at open**: `OW-S-030` / `OW_SCHEMA_AHEAD`, naming both versions and `pip install -U omniweave-core`. Silent misreading is the failure an operator cannot detect |
| file major **<** reader major | migrate forward on an exclusive write open. A `mode=ro` open **refuses** and names `ow store migrate` — a read must never mutate the file whose mtime the freshness check reads (§10.3) |
| equal major, file minor **>** reader minor | **serve reads.** Unknown `[DER]` objects are ignored; unknown `[SOR]` columns are not selected. **Writes refuse**, because a writer that does not know a column cannot maintain its invariant |
| equal major, file minor **<** reader minor | migrate forward (additive DDL only, by definition of a minor bump) |

A `[DER]` object may be dropped and re-created by a minor migration; an `[SOR]` object may not.
That is the whole operational meaning of the legend, and it is why every table below carries a tag.

### 3.2 What L4 adds and what it only reads

L4 **adds no second representation of anything** (INV-1). It reads `block`, `segment` and `anchor`
and adds indexes and occurrence tables over them.

```sql
-- ───── the SEGMENT is L3's. L4 READS IT and defines no second segmenter. ─────
CREATE INDEX segment_digest_ix  ON segment(content_digest) WHERE state = 0;
--   serves: the semantic Channel's inner join from a `vseg` digest back to a live segment,
--   and the corpus-wide embedding dedup (identical text is embedded once).
CREATE INDEX segment_doc        ON segment(doc_ord, gen, first_page) WHERE state = 0;
--   serves: `Filters.pages` and `Filters.doc_keys` narrowing on the segment side, and
--   `ow index segments`.
CREATE INDEX segment_restricted ON segment(restriction_bits) WHERE restriction_bits <> 0;
--   serves: absence gate 10 (`restricted_withheld`) counting, without scanning live segments.
--   PARTIAL because on a corpus with no restrictions this index holds zero rows and costs
--   zero bytes and zero write amplification.

-- The head-generation projection of the SEGMENT, the exact parallel of ow_block_head (03 §13.1).
-- A staged generation's segments are durable and INVISIBLE; this view is the mechanism, not a
-- convenience.
CREATE VIEW ow_segment_head AS
  SELECT s.* FROM segment s JOIN doc d ON d.doc_ord = s.doc_ord
   WHERE s.gen = d.gen AND s.state = 0;
```

**`ow_segment_head` is declared here, and this is its only home.** It belongs beside the L3 objects
L4 reads — `segment` and, through the semantic lift, `segment_block` — and it ships in
`0003_index.sql` with the three indexes above rather than in `0002_graph.sql`. `segment` is created
one file earlier, so the reference is **backward** and §3's forward-reference table does not come
into play at all. The view is part of the published read contract at this `SCHEMA` major, exactly as
`ow_block_head` ([the document model](03-document-model.md) §13.1) is, and the semantic Channel
joins through it rather than re-deriving `s.gen = d.gen AND s.state = 0` at each call site — the
same reason `ow_block_head` is a filter rather than a deduplication (§3.3). The charter's L3 DDL
prints the same statement with `USING (doc_ord)`; the join is spelled out here to match
`ow_block_head` clause for clause, and the two forms are identical in SQLite because `SELECT s.*` is
unaffected by `USING`'s column coalescing.

### 3.3 Lexical: the FTS5 configuration, and it is a retrieval decision

`block_fts`'s `CREATE VIRTUAL TABLE` statement lives in `0001_init.sql`
([the document model](03-document-model.md)). Its **options** are retrieval decisions and **this
document is normative for them**: 03 §13.1 prints the statement, its printed option list must carry
the set below, and neither document may change one without a `SCHEMA` major bump, because every
option below is load-bearing for a Channel:

```sql
-- 0001_init.sql, options owned by this document:                                        [DER]
CREATE VIRTUAL TABLE block_fts USING fts5(
  text,
  content='block', content_rowid='block_id',
  tokenize='unicode61 remove_diacritics 2',
  detail='full',            -- REQUIRED: instance offsets are what ChannelResult.spans carries
  columnsize=1);            -- REQUIRED: bm25() needs per-row length for its normalisation
```

| Option | Value | Consequence of the alternative |
|---|---|---|
| `content='block'` | external content | no second copy of the text (INV-1). The cost is §3.3's orphan hazard |
| `tokenize` | `unicode61 remove_diacritics 2` | version `1` mishandles multi-codepoint diacritic sequences; `0` makes `café` and `cafe` different terms |
| `detail` | `'full'` | `'column'` or `'none'` saves an estimated 30-50% of the FTS index but destroys instance offsets, so `Hit.span` becomes unavailable and sub-block highlighting and OUT citation-to-span both lose their input. Paying 30-50% of one index for sub-block addressing is the trade this framework exists to make |
| `columnsize` | `1` (default) | `columnsize=0` makes `bm25()` unusable, which is the lexical Channel |
| `prefix` | **none** | the rejected ~2.6x figure (770 MB vs 290 MB at 1M blocks) measures a `prefix='2 3'` index. A `tok*` query still works without one, scanning a term-index range; at `MAX_QUERY_TERMS = 64` that is affordable, and identity-tier prefix matching uses B-tree ranges on `block_cite`/`doc(uri)` instead |
| persistent `rank` | **never set** | a `rank` stored in the FTS config file would put part of the scorer outside `SCORER_VERSION`, so a scorer change would not invalidate a cached score. The lexical Channel passes `bm25()` explicitly in every statement |

The three sync triggers on `block` that maintain `block_fts` ship in `0001_init.sql` **alongside
the table**, not here; [the document model](03-document-model.md) §13.1 is normative for their text.
A trigger name is global in `sqlite_master` and the shipped DDL uses no `IF NOT EXISTS`, so printing
`block_fts_ai` a second time in `0003_index.sql` would abort G27(b) — "apply every migration in
numeric order to an empty file" — at `trigger block_fts_ai already exists`, and by the same
forward-reference rule that governs the migration order above, **neither file would apply**. Two
guards there are load-bearing and this document requires them: skip rows where `state <> 0`, skip
rows where `text IS NULL`, and make the `'delete'` command row carry the OLD values exactly as
indexed — an external-content table stores no text of its own, so a `'delete'` whose text differs
from what was indexed corrupts the index silently.

`head_fts` **is** this section's, table and trigger set together, and every trigger is named
explicitly, because `sqlite_master` has one namespace for all of them:

```sql
-- 0003_index.sql, this section's own statements:                                          [DER]
CREATE VIRTUAL TABLE head_fts USING fts5(          -- block.label: NULL on most rows ⇒ tiny
  label, content='block', content_rowid='block_id',
  tokenize='unicode61 remove_diacritics 2', detail='full', columnsize=1);
CREATE TRIGGER head_fts_ai AFTER INSERT ON block
  WHEN NEW.state = 0 AND NEW.label IS NOT NULL
  BEGIN INSERT INTO head_fts(rowid, label) VALUES (NEW.block_id, NEW.label); END;
CREATE TRIGGER head_fts_ad AFTER DELETE ON block
  WHEN OLD.state = 0 AND OLD.label IS NOT NULL
  BEGIN INSERT INTO head_fts(head_fts, rowid, label)
        VALUES ('delete', OLD.block_id, OLD.label); END;
CREATE TRIGGER head_fts_au AFTER UPDATE ON block BEGIN
  INSERT INTO head_fts(head_fts, rowid, label)
    SELECT 'delete', OLD.block_id, OLD.label WHERE OLD.state = 0 AND OLD.label IS NOT NULL;
  INSERT INTO head_fts(rowid, label)
    SELECT NEW.block_id, NEW.label        WHERE NEW.state = 0 AND NEW.label IS NOT NULL;
END;
```

The FTS5 column is named **`label`** because the `block` column is
([the document model](03-document-model.md) §13.1 declares `label TEXT`; ADR-1 decision 7 renamed it
from `title` so that `Kind.TITLE` keeps the word). An external-content FTS5 table resolves its column
names against `content='block'`, so `head_fts(title …)` over a table with no `title` column raises
`no such column: title` when `0003_index.sql` applies — which, by the forward-reference rule above,
takes G27(b)'s whole run with it. The name is one fact with one home: 03 §13.1's DDL.

Same two guards, same `'delete'`-carries-OLD rule, `label` substituted for `text`. `block_fts`'s set
and `head_fts`'s set both fire on `block` and maintain disjoint indexes, so their relative firing
order is irrelevant and neither reads the other's table.

**The orphan hazard, and the rule that closes it.** An external-content FTS5 table stores the
inverted index but reads the column values back out of `block`. If a `block` row disappears without
the `AFTER DELETE` trigger issuing a matching `'delete'` command, the FTS index keeps a term
posting whose content lookup finds nothing: queries return wrong results and
`INSERT INTO block_fts(block_fts) VALUES('integrity-check')` raises. The path that can do this is a
**foreign-key cascade**: whether an `ON DELETE CASCADE` action fires row triggers is governed by
`PRAGMA recursive_triggers`, which `CONN_PRAGMAS` does not set and which this document will not add
(it would change trigger semantics for every other table at once). So the rule is structural, not
pragmatic:

> **No FTS-bearing table is ever emptied by a cascade.** Deleting a document is
> `DELETE FROM block WHERE doc_ord = ?` **first**, in the same transaction as
> `DELETE FROM doc WHERE doc_ord = ?` second. A grep gate over `store/` rejects a `DELETE FROM doc`
> that is not immediately preceded by the explicit `block` delete, and `ow store verify --fts` runs
> `integrity-check` on both FTS tables plus `SELECT count(*) FROM block_fts` against the live block
> count. `ow store repair` step 2 is the remedy.

**`index_state.fts_state` is a three-state machine, and the lexical Channel reads it.** Nothing else
in the charter says who writes it or what a reader does with it:

| `fts_state` | Written when | Lexical Channel |
|---|---|---|
| `ok` | after a successful `'rebuild'`, or at the end of a bulk window that re-created the triggers and re-populated | runs normally |
| `building` | by `ow store repair` / a bulk window, **before** the first FTS DDL | `UNAVAILABLE(fts_building)` with `OW-S-032`, which **forces `degraded`** — never an empty lexical result presented as "no matches" |
| `stale` | by any writer that inserted `block` rows while the triggers were dropped and could not finish the repopulate | `UNAVAILABLE(fts_stale)`; `ow doctor` names `ow store repair` |

`fts_state` is written in the same transaction as the DDL that invalidates it, so a crash leaves the
pessimistic value. That is the point: an FTS index of unknown completeness must degrade the Verdict,
because a missing posting is indistinguishable from an absent phrase.

**Why a second FTS table rather than a second column on `block_fts`.** Verified on SQLite 3.45.1: a
single-column `bm25(t, w)` *accepts* a weight, but the weight enters the tf-saturation term rather
than acting as a field weight, so it cannot express "a heading match outranks a body match". The
remedy is not amending `block_fts` — that would be a rebuild of the largest index in the store for a
strictly worse result. `head_fts` plus **heading-spine propagation** lifts the paragraphs *under* a
matching heading, not merely the heading itself, and `block_fts` is untouched.

**Retiring a generation sets its blocks `state = 1` in the same transaction that advances
`doc.gen`**, so `block_fts_au` and `head_fts_au` remove them from both FTS tables and re-add
nothing. **The index layer never holds two generations.**
That is what makes `ow_block_head` a filter rather than a deduplication, and the lexical Channel applies it to the page bm25 ranks rather than to every match, which is the same answer at a third of the time on a corpus whose common words match half its blocks (D651).

### 3.4 Trigram: off by default, and a rung inside `exact` when on

`CHANNELS` is a closed five-tuple, so enabling trigram cannot add a sixth Channel. When
`[retrieval] trigram = true`, `0003_index.sql` additionally creates:

```sql
CREATE VIRTUAL TABLE block_tri USING fts5(         -- [DER] created ONLY when trigram = true
  text, content='block', content_rowid='block_id',
  tokenize='trigram remove_diacritics 1');
--   plus three triggers named block_tri_ai / block_tri_ad / block_tri_au, whose bodies are 03
--   §13.1's block_fts triggers with `block_tri` substituted for `block_fts`. They ship in this
--   same file as head_fts's set, so no name collides with 0001's. "The same three triggers" is not
--   a legal instruction: a trigger name is global in sqlite_master and CREATE TRIGGER is not
--   idempotent. The set is registered in tools/indexes.toml as conditional (§3.13).
```

It participates as **one ladder rung inside the `exact` Channel** at tier 35 — below a resolved
`anchor` definition (0) and a `ref_site` occurrence (1), above nothing — and it contributes
**membership, never a score**: a trigram hit is a substring match, and a `bm25()` over trigrams is a
number with no interpretation. `IndexCaps.has_trigram` tells the planner whether the rung exists;
`MIN_TRIGRAM_CHARS = 3` is refused below with a usage error, because a trigram index cannot match a
two-character needle. Its cost is **unverified** for the trigram tokenizer (the 2.6x figure measures
a prefix index), which is the honest reason it ships opt-in rather than a claim that it is
expensive.

### 3.5 Exact: the occurrence side of `anchor`

The `exact` Channel exists because `unicode61` destroys exactly the tokens a document query needs:
`§4.2(b)` becomes `4 · 2 · b`, `ISO-8601` becomes `iso · 8601`. `anchor` (what a document
*defines*) is L3's, in `0002_graph.sql`. L4 owns the **occurrence** side.

```sql
CREATE TABLE ref_site (               -- EVERY reference occurrence. NO status column, EVER. [SOR]
  name_norm TEXT NOT NULL,            -- normalize_key of the resolvable name. Same NAME as anchor's.
  akind     TEXT NOT NULL,            -- AnchorKind, the SAME closed vocabulary as anchor.akind
  doc_ord   INTEGER NOT NULL REFERENCES doc(doc_ord) ON DELETE CASCADE,
  block_id  INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  ts_a INTEGER NOT NULL, ts_b INTEGER NOT NULL,   -- a half-open TextSpan into block.text
  surface  TEXT NOT NULL,             -- '§ 4.2(b)' as written. DISPLAYED, never matched.
  scope    TEXT NOT NULL CHECK (scope IN ('document','corpus')),
  origin_operator TEXT NOT NULL, run_id INTEGER,
  PRIMARY KEY (name_norm, akind, block_id, ts_a)
) WITHOUT ROWID;
CREATE INDEX ref_site_block ON ref_site(block_id);
--   serves: hydration ("which references does this hit contain") and cascade locality.
CREATE INDEX ref_site_name  ON ref_site(name_norm, akind);
--   serves: the `exact` Channel's probe, and the `anchor_delta` join that retries the unresolved
--   set when a document's defined names change.
```

The span columns are `ts_a` / `ts_b`, not `a` / `b`, because the terminology lock reserves that pair
for a `TextSpan` and `os_*` for an `OriginSpan`, and this table's span is a `TextSpan`. **One
convention, stated once and linted:** a `TextSpan` is **half-open `[ts_a, ts_b)` in characters of
`block.text`**; an `OriginSpan`'s `os_a` is an **offset** and `os_b` is a **length**, in whatever
unit `os_kind` names (bytes for `bytes`, glyph index and count for `glyphs`). The asymmetry is
deliberate — `os_b` as a length is what makes the `glyphs` branch expressible at all, since a glyph
run has no meaningful end offset in the byte stream — and a semgrep rule rejects `os_a:os_b` slicing
and `text[ts_a:ts_a+ts_b]`.

`doc_ord` is denormalised onto `ref_site` **so the document-scope predicate is an index lookup and
not a correlated subquery.** That is the difference between a 2 ms and a 400 ms `exact` Channel on a
17-document corpus, and the gap widens linearly.

`MAX_REF_SITES_PER_BLOCK = 32`; a breach emits `Diag(OW_REFSITE_TRUNCATED)` and is counted.

```sql
CREATE VIEW ref_unresolved AS         -- resolution is BY STRING. No lifecycle, so it cannot go stale.
  SELECT s.name_norm, s.akind, s.doc_ord, s.block_id, s.ts_a, s.ts_b, s.surface, s.scope
  FROM ref_site s
  WHERE NOT EXISTS (
    SELECT 1 FROM anchor n JOIN doc dd ON dd.doc_ord = n.doc_ord
    WHERE n.name_norm = s.name_norm AND n.akind = s.akind
      AND n.gen = dd.gen                                     -- HEAD GENERATION ONLY
      AND (n.scope = 'corpus' OR n.doc_ord = s.doc_ord));    -- SCOPE IS HONOURED

CREATE VIEW ow_ref_resolved AS
  SELECT s.block_id AS src_block, n.block_id AS dst_block, s.name_norm, s.akind, s.ts_a, s.ts_b
  FROM ref_site s
  JOIN anchor n ON n.name_norm = s.name_norm AND n.akind = s.akind
  JOIN doc dd   ON dd.doc_ord = n.doc_ord AND n.gen = dd.gen      -- HEAD GENERATION ONLY
  WHERE n.scope = 'corpus' OR n.doc_ord = s.doc_ord;              -- SCOPE IS HONOURED
```

Both predicates in both views are load-bearing and both failed silently without them:

1. **`n.gen = dd.gen`** — without it a *retired* generation's anchor still satisfies the anti-join,
   so a reference "resolves" against text that is no longer the head.
2. **the scope clause** — without it a `scope='document'` anchor in document A resolves a `ref_site`
   in document B: "Figure 3" in one contract binding "Figure 3" in another. That is the single most
   common false merge in a document corpus, guarded for entities and, before this, wide open on the
   reference path.

`ref_unresolved` is a member of `canonical_projection()`, so a full build and an incremental build
agreed on the *same wrong answer* and gate G19 could never see it. A view over the right predicates
is the fix; a status column would only have recorded the wrong answer durably.

```sql
CREATE TABLE ref_attempt (            -- the FAILED TAIL only: written after a first failure. [DER]
  block_id INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  ts_a INTEGER NOT NULL, attempts INTEGER NOT NULL DEFAULT 1, last_tried_gen INTEGER,
  candidates TEXT NOT NULL DEFAULT '[]',   -- JSON array of near-miss cites
  PRIMARY KEY (block_id, ts_a)
) WITHOUT ROWID;
```

`ref_attempt` gives the hot retry set an index without introducing a status column that can lie.
`ow store residue` prints `ref_unresolved` grouped by `name_norm`: **the residue is data, not a log
line.**

### 3.6 Structural: the section prefix index and the block→block link table

```sql
CREATE TABLE block_sec (              -- [DER] a section PREFIX index. Not an identity, not an
  block_id  INTEGER PRIMARY KEY REFERENCES block(block_id) ON DELETE CASCADE,  -- ordering authority.
  sec_id    INTEGER NOT NULL,         -- the nearest heading/section block
  sec_depth INTEGER NOT NULL,
  sec_path  TEXT    NOT NULL          -- '/1/4/2' — "everything under §4.2" is a prefix range
) WITHOUT ROWID;
CREATE INDEX block_sec_path ON block_sec(sec_path, block_id);
--   serves: `Filters.sec_path_prefix` as a range scan (`sec_path >= '/1/4/2' AND sec_path <
--   '/1/4/3'`), and the lexical scorer's spine term. `block_id` is in the key so the scan is
--   covering and never touches `block`.
```

`sec_path` components are **zero-padded to four digits** (`/0001/0004/0002`), because a plain
integer path makes `'/1/10' < '/1/2'` lexicographically and the range scan silently returns the
wrong set. The prefix upper bound is the path with its last component incremented, and a section
with more than 9,999 siblings emits `Diag(OW_RESOURCE_LIMIT, {limit: "SEC_PATH_FANOUT"})` and
truncates the path at that depth rather than producing an unsortable key.

`block_sec` is computed once and read twice: as an indexed prefix for retrieval, and by the
segmenter, which reads it to produce `segment.heading_path` (X26). One computation, two shapes.

```sql
CREATE TABLE block_link (             -- block→block. `edge` is L3's entity→entity table.  [SOR]
  link_id     INTEGER PRIMARY KEY,
  src_block   INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  dst_block   INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  relation    TEXT    NOT NULL REFERENCES relation_vocab(relation),  -- OPEN vocabulary
  site_block  INTEGER REFERENCES block(block_id) ON DELETE CASCADE,  -- WHERE it was observed
  via_entity  INTEGER,                -- an entity_id when the relation is entity-mediated.
                                      -- Deliberately NO FK: L3 creates `entity` in a later
                                      -- migration and SQLite cannot add an FK by ALTER.
                                      -- `ow store verify` checks it.
  bound_by    TEXT,                   -- the anchor name_norm that RESOLVED this link; drives
                                      -- unbind. NULL ⇒ never unbound.
  weight      REAL    NOT NULL DEFAULT 1.0,
  ambiguous   INTEGER NOT NULL DEFAULT 0,   -- >1 target matched: KEPT, ranked down, never dropped
  producer_id INTEGER NOT NULL REFERENCES producer(producer_id),
  trust       INTEGER NOT NULL,       -- Trust ordinal. Absent ⇒ 0. Migrations only DOWNGRADE.
  score REAL, score_kind TEXT,
  origin_operator TEXT NOT NULL, origin_driver TEXT NOT NULL, driver_schema_v INTEGER NOT NULL,
  restriction_bits INTEGER NOT NULL DEFAULT 0,
  CHECK ((score IS NULL) = (score_kind IS NULL))
);
CREATE UNIQUE INDEX block_link_identity ON block_link(
  src_block, dst_block, relation, producer_id, IFNULL(site_block,-1), IFNULL(via_entity,-1));
--   serves: INSERT OR IGNORE. Without the IFNULL sentinels there is nothing to conflict on and
--   INSERT OR IGNORE degenerates to a plain INSERT (codegraph #1034: byte-identical duplicates
--   that inflated counts and flowed into callers). The installing migration MUST GROUP BY the
--   IDENTICAL expression, sentinels included.
CREATE INDEX block_link_out ON block_link(src_block, relation);
--   serves: the forward hop of Expand's frontier BFS. The left prefix covers src-only lookups,
--   which is why there is no separate single-column index.
CREATE INDEX block_link_in  ON block_link(dst_block, relation);
--   serves: the reverse hop, and `ow open`'s back-references ("what points at this block").
CREATE INDEX block_link_bound ON block_link(bound_by) WHERE bound_by IS NOT NULL;
--   serves: anchor_delta unbinding. PARTIAL because most links have no binding anchor.
CREATE INDEX block_link_restricted ON block_link(restriction_bits) WHERE restriction_bits <> 0;
--   serves: absence gate 10 on the traversal path.
```

**Deliberately absent:** single-column `src`/`dst` indexes. codegraph's migration v4 *drops* the
equivalents as dead weight on the write path; the two-column indexes cover them by left prefix. In
the same repository, dropping the four non-unique edge indexes for a bulk load measured
**2.8 s → 1.1 s** on a 224k-edge insert with ~0.3 s to re-create — which is the measured basis for
§10.6's bulk windows, and the reason the *unique* identity index is never among the dropped.
`MAX_LINKS_PER_BLOCK = 4096`, enforced at write.

An identity containing an `IFNULL` sentinel is **always a separate `CREATE UNIQUE INDEX`**, never
an inline `UNIQUE`/`PRIMARY KEY`: SQLite prohibits an expression in a table-level constraint, so the
inline form does not merely fail review, it fails `CREATE TABLE` (ST10, verified on 3.45.1).

### 3.7 The semantic Channel's write-time contract

```sql
CREATE TABLE embed_space (            -- a meta.json as a table WITH A UNIQUE CONSTRAINT   [SOR]
  space_id        INTEGER PRIMARY KEY,
  model_key       TEXT    NOT NULL UNIQUE,   -- sha256_canonical(the nine fields below)[:16]
  driver_id       TEXT    NOT NULL,          -- an embed/1 DriverId, e.g. 'embed.text.bge_m3'
  driver_schema_v INTEGER NOT NULL,
  model_id        TEXT    NOT NULL,
  model_rev       TEXT    NOT NULL,          -- an EXACT sha. '' or 'main' is REFUSED
  dim             INTEGER NOT NULL,
  metric          TEXT    NOT NULL CHECK (metric IN ('cosine','ip','l2')),
  normalize       INTEGER NOT NULL,
  pooling         TEXT    NOT NULL,
  doc_prompt_digest   BLOB NOT NULL,         -- applied ONCE, client side, at build
  query_prompt_digest BLOB NOT NULL,         -- applied ONCE, client side, at query
  sig_bits        INTEGER NOT NULL,          -- the binary signature WIDTH IN BITS; 0 = none
  storage         TEXT    NOT NULL CHECK (storage IN ('sig_only','sig_full')),
  backend         TEXT    NOT NULL,          -- an `omniweave.backends` entry-point name
  created_ns      INTEGER NOT NULL
);
```

The **nine identity fields** are `model_id`, `model_rev`, `dim`, `metric`, `normalize`, `pooling`,
`doc_prompt_digest`, `query_prompt_digest`, and `driver_id + driver_schema_v`. A search whose embed
Driver does not reproduce `model_key` is **refused with `OW-S-020`, printing both tuples** — on the
*search* path, not only the build path. LEANN ships the equivalent as an unconstrained `meta.json`;
making it a `UNIQUE` column is what turns "the query embedder drifted" from a silent recall collapse
into a refusal.

`sig_bits` **defaults to `dim`** — one sign bit per dimension is what binary quantisation of a
normalised vector produces — so the shipped `bge-m3` space at `dim = 768` has `sig_bits = 768` and a
**96-byte** signature. Every vector size in §4 derives from that identity, and §3.9's measured
ceiling was taken on exactly 96-byte signatures. `sig_bits = 0` means the space is `sig_full` with no
signature stage and `VEC_BRUTE_MAX` does not apply to it; the stdlib backend refuses such a space
outright, because an exhaustive f32 scan is what the signature stage exists to avoid.

`[retrieval.vec] storage = "auto"` resolves **once, at build time**, and the resolved value is
written to `embed_space.storage` and `vec_manifest` and never re-derived at query time:

```text
auto ⇒ sig_full   if live_segments <= VEC_BRUTE_MAX
                  and live_segments * (dim*4 + 112) <= [store] vec_full_max_bytes (2 GiB)
     ⇒ sig_only   otherwise
```

At `dim = 768` the first clause binds first: 250,000 segments of `sig_full` is 800 MB, so `auto`
means `sig_full` everywhere the stdlib backend will serve at all, and `sig_only` only where an ANN
backend has taken over. That is the intended reading — reranking is free precision when the corpus
is small enough to scan, and pointless when it is not.

`[capability.embed]` on a driver card therefore keeps only `dim`, `max_tokens` and `languages`. The
identity lives here, once.

### 3.8 Freshness, coverage, state, statistics, migrations

```sql
CREATE TABLE ingest_scope (           -- written by the enumerator / an acquire driver     [SOR]
  scope_id TEXT PRIMARY KEY,          -- the canonical URI PREFIX of the enumerated root
  discovered INTEGER NOT NULL, indexed INTEGER NOT NULL,
  skipped INTEGER NOT NULL, skipped_why TEXT NOT NULL DEFAULT '{}',
  scanned_at_ns INTEGER NOT NULL, complete INTEGER NOT NULL
);
-- AN ABSENT ROW MEANS "COVERAGE UNKNOWN", NEVER "NOTHING WAS EXCLUDED".  Gate 4 reads this.

CREATE TABLE index_state (k TEXT PRIMARY KEY, v TEXT NOT NULL);              -- [SOR]
-- corpus_id · shard_ord · schema · scorer_version · generation · fts_state{ok,building,stale}
-- · bulk_window · wal_baseline_bytes · last_full_index_ns · default_space_id · unicode_version

CREATE TABLE stat (k TEXT PRIMARY KEY, v INTEGER NOT NULL, computed_ns INTEGER NOT NULL);  -- [DER]
-- ONLY SCALAR COUNTS, for the over-fetch factor: live_blocks, live_segments, docs, per-kind
-- counts. NO HISTOGRAMS: the narrowing decision is EXACT, not estimated.
-- `docs` is  SELECT count(*) FROM doc WHERE format <> 'owjob'  — see NO_JOB_DOCS below.

CREATE TABLE migration (
  version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at_ns INTEGER NOT NULL,
  cost_class TEXT NOT NULL CHECK (cost_class IN ('ddl','backfill','rebuild')),
  resumable INTEGER NOT NULL, backfill_done INTEGER NOT NULL DEFAULT 0, backfill_total INTEGER,
  unbackfilled_means TEXT NOT NULL    -- REQUIRED PROSE. `ow doctor` prints it VERBATIM.
) STRICT;
```

**`ingest_scope.scope_id` is a URI prefix, and that is what makes gate 4 implementable.** There is
no `doc.scope_id` column and there must not be one — a document can be reached by two scans. The
containment test is `doc.uri GLOB scope_id || '*'`, evaluated over `doc` (thousands of rows, not
millions, so an unindexed scan is the right implementation). A query whose `Filters` name no
document scope reads **every** scope row; a query scoped to documents reads the scope rows
containing them. Gate 4 fires when any scope row in view has `discovered > indexed`, `complete = 0`,
**or does not exist**.

**`stat` has one writer and a staleness rule.** It is re-derived by the run-final converge pass
(`op.converge`) and by `ow index stats`, in one transaction per key, and it is the *only* input to
the over-fetch factor above `PREFILTER_MAX` (§6.1). Since a wrong over-fetch factor is a silent
recall loss, staleness fails expensive:

```text
STAT_MAX_AGE_NS = 86_400e9        # 24 h
age > STAT_MAX_AGE_NS  or  a key is missing
  ⇒ the over-fetch factor is the maximum clamp, 64, and this is recorded on the Verdict:
    Degradation(kind="stat_stale",
                message="stat is stale, so the over-fetch factor took its maximum clamp "
                        "of 64; re-derive it with `ow index stats`",
                fix_command="ow index stats")
```

`Degradation.message` is one sentence for a human and `knob`/`fix_command` carry the same fact
machine-readably ([15](15-observability.md) §6.3), so a bare command string is a `fix_command` and a
bare config key is a `knob` — never the `message`. Every `Degradation` constructed in this document
obeys that split, and [15](15-observability.md) §6.3's register is normative for which of the two a
given kind carries.

`stat` holds scalar counts and **no histograms**, because the narrowing decision (§6.1) is an exact
probe. A histogram would be a second, wrong answer to a question that already has an exact one.

**`NO_JOB_DOCS` — the job-document exclusion, one predicate stated once.** [Generation](09-generation.md)
§7.1 hangs a compile-produced asset off a **synthetic job document**: one `doc` row per compile job,
`format = 'owjob'`, `uri` `ow-job://<corpus>/<artifact_slug>/<job_digest>`. It is not a document a
user ingested and it must never be counted as one, so:

```python
# omniweave_core.store — the one spelling. Every site below appends it verbatim.
NO_JOB_DOCS: Final[str] = "doc.format <> 'owjob'"
```

`format` is `NOT NULL` on `doc` ([the document model](03-document-model.md) §13.1), so the predicate
is total and needs no `IFNULL`. **No index is added for it**: `doc` holds thousands of rows, not
millions (the same measurement that makes §3.8's `ingest_scope` GLOB an honest scan), and every
statement below already reads `doc`. The sites, exhaustively:

| Site | Where | Why the exclusion is required |
|---|---|---|
| `stat.docs`, and the per-kind counts' document denominator | this section; re-derived by `op.converge` and `ow index stats` | a job document would inflate the corpus size an operator reads and the denominator the over-fetch factor is clamped against |
| `ow store stats` | §2.2, §4.1 | the printed document count is the same number, from the same `stat` row |
| `corpus_card`'s document count and `verbatim_fraction` denominator | built once per `card_gen`, read by the MCP `card` mode | a job document has no blocks, so it would drive `verbatim_fraction` toward zero by adding to a denominator it can never contribute to |
| `Filters.formats` (§6.1) | the narrowing statement | `formats={"owjob"}` is a **usage error** naming `NO_JOB_DOCS`, not an empty result: `owjob` is minted by the job runner and is not a detectable format token ([ingest and routing](05-ingest-and-routing.md) §2.2), so selecting on it can only be a mistake |
| absence gate 4's scope roll-up (§6.8) | `doc.uri GLOB scope_id \|\| '*'` | vacuous in practice — `ow-job://` matches no enumerated scope prefix — and the predicate is still written, because "vacuous today" is how a silent miscount arrives |
| `ow store rm --doc <ord>` | [generation](09-generation.md) §7.1, **not here** | it **refuses** on a job document while any `artifact_asset` row references one of its assets, because `asset.doc_ord` cascades. Listed so the roster is exhaustive; the rule is 09's and is not restated |

**What does *not* carry it, and why that is not an oversight.** No Channel statement and no index in
§3.13 carries `NO_JOB_DOCS`: a job document carries **zero `block` rows**, and every Channel ranks
Blocks, so a job document is invisible to retrieval by construction rather than by predicate. Adding
the exclusion to the narrowing statement would put a `doc`-column test on the hottest join in the
store to exclude rows that cannot exist. The failure mode this closes is therefore a **count**, not a
hit: a synthetic document leaking into a corpus size, a coverage denominator or a card, where no
`Verdict` field would ever disclose it.

A migration whose estimated row-touch exceeds `WATCHDOG_MS / 2` **must** set `resumable = 1` and run
through the `work` queue. codegraph's counter-example is precise: 79 s of `CREATE INDEX` against a
60 s watchdog produced SIGKILL *after doing the work*, so the next start redid it. Every
`ADD COLUMN` is guarded with `PRAGMA table_info`. `unbackfilled_means` is required prose because a
half-backfilled column is a correctness question an operator must be able to answer without reading
the migration. One claim checked and found wrong: three binding
`ALTER TABLE … ADD COLUMN … NOT NULL` statements are **not** universally illegal — verified on
3.45.1, they raise only against a **non-empty** table. The remedy (ship those columns in
`0001_init.sql`) is right and adopted; the stated rule was not.

### 3.9 The `vec` sidecar

```sql
-- ═════ index.vec.owstore — ATTACHed as `vec`. [DER] Optional. Deletable. ═════
CREATE TABLE vec_manifest (k TEXT PRIMARY KEY, v TEXT NOT NULL);
-- corpus_id (≠ main.index_state.corpus_id ⇒ THE SIDECAR IS IGNORED, not read) · schema
-- · model_key · backend · backend_version · storage · sig_bits · dim · built_at_ns · rows
CREATE TABLE vseg (                   -- CONTIGUOUS SEGMENTS, never a row per vector.
  model_key TEXT NOT NULL, seg_no INTEGER NOT NULL, n INTEGER NOT NULL,
  digests BLOB NOT NULL,              -- n × 16 B segment content_digest, sorted
  sigs    BLOB NOT NULL,              -- n × (sig_bits/8) B, same order
  live    BLOB NOT NULL,              -- ceil(n/8) B bitmap; a swept row clears its bit
  PRIMARY KEY (model_key, seg_no)
);
CREATE TABLE vfull (                  -- storage='sig_full' only: an exact rerank of the top N
  model_key TEXT NOT NULL, segment_digest BLOB NOT NULL, v BLOB NOT NULL,   -- dim*4 B f32 LE
  PRIMARY KEY (model_key, segment_digest)
) WITHOUT ROWID;
CREATE TABLE vpending (               -- the re-embed set, MATERIALISED so it is a scan
  model_key TEXT NOT NULL, segment_digest BLOB NOT NULL, chars INTEGER NOT NULL,
  PRIMARY KEY (model_key, segment_digest)
) WITHOUT ROWID;
```

`VSEG_SIZE = 4096`. `RERANK_N = 1000`. `VEC_BRUTE_MAX = 250_000` **segments**.

**The ceiling is measured, and the arithmetic that follows from it is shown.** CPython 3.11,
96-byte signatures, XOR + `int.bit_count()` + a 512-entry heap: **200,000 signatures scanned in
81 ms**. Everything else is derived:

| Derived quantity | Arithmetic | Value |
|---|---|---|
| scan rate | 200,000 / 81 ms | **2,469 segments/ms** |
| memory bandwidth | 200,000 × 96 B / 81 ms | **237 MB/s** — the plausibility check on the measurement |
| extrapolation to 1M | 1,000,000 / 2,469 | **405 ms**, within 15% of the 466 ms/1M figure it was checked against |
| the shipped ceiling | 250,000 / 2,469 | **101 ms** — the charter's "~100 ms" |
| bytes read at the ceiling | ceil(250,000/4096) = 62 rows × (4096×16 + 4096×96 + 512) B | **62 rows, 27.2 MB** — inside `mmap_size` |
| the same data row-per-vector | 250,000 cursor steps against 62 | the mechanism behind the measured 2.3x (1072 ms vs 466 ms per million) |

**The budget boundary this exposes, stated rather than hidden.** The semantic Channel's own budget
is `channel_ms.semantic = 80`, so the scan alone exhausts it at 80 × 2,469 ≈ **197,500 segments** —
below the 250,000 refusal ceiling. There are therefore three bands, and `ow index vectors` prints
which one a corpus is in **at build time**, not once per query:

| `live_segments` | Behaviour |
|---|---|
| ≤ 197,000 | serves inside budget |
| 197,000 – 250,000 | serves, but expect `UNAVAILABLE(timeout)` and `degraded` on a cold page cache. `ow index vectors` emits `Degradation(kind="vector_scan_over_budget", message="this corpus is above the stdlib backend's budgeted scan; set [retrieval] backend to an ANN backend", knob="[retrieval] backend")` |
| > 250,000 | the stdlib backend **refuses** before running, `OW-S-022`, so the refusal costs nothing |

An honest refusal beats a five-second query nobody warned you about, and a disclosed 100 ms Channel
beats a silently-raised budget.

### 3.10 The `events` sidecar — the query ledger

```sql
CREATE TABLE retrieval_event (
  event_id INTEGER PRIMARY KEY, ts_ns INTEGER NOT NULL,
  corpus_id TEXT NOT NULL, surface TEXT NOT NULL,          -- cli | mcp | sdk | hook
  query_hash TEXT NOT NULL, query TEXT,
  plan_digest TEXT NOT NULL, policy_digest TEXT NOT NULL,
  scorer_version INTEGER NOT NULL, producer_version TEXT NOT NULL,
  narrowing_kind TEXT NOT NULL CHECK (narrowing_kind IN ('all','set','empty')),
  narrowing_n INTEGER NOT NULL, prefilter_exact INTEGER NOT NULL,
  channels TEXT NOT NULL, channel_ms TEXT NOT NULL DEFAULT '{}',
  space_id INTEGER, backend TEXT, overfetch REAL,
  returned_n INTEGER NOT NULL, matches_before_packing INTEGER NOT NULL,
  best_score REAL, score_ceiling REAL, confidence REAL, gap REAL,
  generated_share REAL NOT NULL DEFAULT 0.0,      -- §6.7. NOT NULL: 0.0 is a measured value
  verdict_state TEXT NOT NULL, gates TEXT NOT NULL DEFAULT '[]',
  degraded_because TEXT NOT NULL DEFAULT '[]',    -- JSON array of DegradeCause
  degradations TEXT NOT NULL DEFAULT '[]',        -- JSON array of Degradation. NOT the same list
  freshness TEXT NOT NULL, snapshot_gen INTEGER NOT NULL, shards_contributed TEXT,
  spend TEXT NOT NULL, micros INTEGER NOT NULL DEFAULT 0,
  latency_ms INTEGER NOT NULL
) STRICT;
CREATE INDEX retrieval_event_ts  ON retrieval_event(ts_ns);
--   serves: `ow store stats --since`, retention pruning.
CREATE INDEX retrieval_event_bad ON retrieval_event(ts_ns) WHERE verdict_state <> 'ok';
--   serves: "show me every query that degraded this week" — the one query an operator actually
--   runs. PARTIAL, so it is ~2% of the full index on a healthy store.
```

**Three columns carry what a `Verdict` says about degradation, and they are three because they
answer three different questions.** `gates` is the list of gate names that failed; `degraded_because`
is the `DegradeCause` per gate, in the same order, so `ow why absent` can be reconstructed from the
ledger alone; `degradations` is `Verdict.degradations` — the `Degradation` records
([15](15-observability.md) §6.3), which are not gate failures and do not line up with `gates` at all.
`stat_stale` and `pushdown_unavailable` are the read path's two common members and neither is an
absence gate, so before this column a degraded read that failed no gate left no trace in the ledger.
[15](15-observability.md) §6.3's carrier table already names "a `degradations` JSON TEXT column on
`route_decision`, on `artifact`, and on the query-ledger row"; this is that column.

**`generated_share` is `REAL NOT NULL DEFAULT 0.0`, and the default is honest** because §6.7 defines
`0.0` for an empty answer and for a corpus that has never ingested its own artefacts — the same
number, separated by `verdict_state`. It is written on **every** row, which is what makes Open
question F57 answerable by one `SELECT` rather than by a bespoke harness: the distribution question
is a scan over a retention window, which `retrieval_event_ts` already serves, so **no index is added
for it** and the index count in §3.13 is unchanged. A partial index on a threshold would be an index
on a number nobody has calibrated, which is the thing F57 exists to prevent.

Both columns are additive to a `[DER]` sidecar and therefore land in a **minor** schema bump (§3.1):
`events.owstore` is deletable, has no `[SOR]` reader contract, and both columns carry a real
`DEFAULT`, so §3.8's `ALTER TABLE … ADD COLUMN … NOT NULL` restriction does not bite — a defaulted
`ADD COLUMN` is legal against a non-empty table and needs no `unbackfilled_means`, because the
default *is* the correct historical value for a row written before the column existed.

Written through a **bounded in-memory queue (cap 4,096, drop-oldest with a counter)**, flushed on a
2 s timer and at exit — never inside the read snapshot, never on the response path. Retention
90 days, pruned by the flusher in `DELETE … LIMIT 5000` steps. `query` (the raw text) is stored only
when `[retrieval] event_log_query = true`; `query_hash` is always stored, so the scoreboard works on
a store that never retains a user's words. `[retrieval] event_log = false` disables the ledger
entirely, and the consequence is disclosed: `ow route scoreboard --surface retrieval` and Open
question F52 has no input. This is a **query ledger, not a second decision log**: query-time work
that persists nothing creates no `work` row and no `route_decision`.

### 3.11 The asset store and the CAS write protocol

The **asset store** is content-addressed on the filesystem, not in the database. `asset.store_ref`
and `part.store_ref` are `cas://ab/cd/<sha256>` references into `.omniweave/cas/`. **No inline
bytes, ever.** The schema for `asset`, `block_asset`, `part` and `page_render` is
[the document model](03-document-model.md)'s; the storage consequences are this document's.

The write protocol is four steps, and each one is there because the obvious three-step version has a
failure:

```text
1. write bytes to  cas/tmp/<uuid4>            same filesystem as cas/, ALWAYS
2. fsync the file, then close                 else a rename can outlive the data
3. os.replace(tmp, cas/ab/cd/<sha256>)        atomic within one filesystem; overwrite is a no-op
                                              because the name IS the digest
4. fsync the containing directory             else the rename can be lost on a crash (POSIX)
```

- **`cas/tmp/` is inside `cas/`** so step 3 is never cross-device. A cross-device `os.replace` raises
  `OSError(EXDEV)`, and a "download to the system temp dir then move" implementation fails on exactly
  the machines that separate `/tmp` — the ones with the least disk. D723: step 3 is skipped when the blob is already there. On Windows the overwrite is not a no-op: `MoveFileEx` over an existing file leaves the old one delete-pending for a moment, and a reader opening it then is denied (EACCES). Every free Pass of a document puts the same view body, so a worker was denied while the host re-put the blob for the next Pass, and GR8 failed 2 of 3 runs on it. A read also waits out such a denial for up to 200 ms, because two writers of one new blob can still race.
- **The two-level `ab/cd` fanout** bounds directory size: at 10M blobs a directory holds ~150
  entries, which keeps `readdir` cheap on every filesystem and keeps Windows Explorer usable.
- **A hash collision is not handled and does not need to be**, but a *content mismatch* is: `ow store
  fsck --cas` re-hashes a sampled `[cache] fsck_sample_frac = 0.01` of blobs per run and every blob a
  failed `--verify` touched. A mismatch is `Diag(OW_INTEGRITY_UNCHECKED)` on the owning `part`, which
  is a member of `ABSENCE_BLOCKING_DIAGS`, so it degrades a Verdict rather than corrupting a quote.
- **ENOSPC in step 1** aborts the unit with `OW_RESOURCE_LIMIT`; the temp file is unlinked by the
  startup sweep of `cas/tmp/`, which is also what cleans up after a SIGKILL between steps 1 and 3.
- `asset_identity` is `UNIQUE(doc_ord, sha256, IFNULL(origin_part,''))`, so the same logo appearing
  in 400 slides is one CAS blob and 400 `block_asset` rows.
- `page_render` is a derived, evictable cache keyed
  `(doc_ord, gen, page, dpi, renderer, renderer_version, colorspace)`. A decoded 192-DPI A4 page is
  **10.7 MB**; 5,000 of them is ~53 GB. That arithmetic is why rendering follows routing and is
  never a model field, and why `page_render` rows are swept by `last_used_ns`.
- `MAX_ASSET_BYTES = 268_435_456`. CAS is swept by `[cache.max_bytes] blob` and `render`, not by
  the store, and a sweep deletes the file **before** the row so a dangling row (recoverable) is the
  only reachable inconsistency, never a dangling file (a leak).

### 3.12 The cache tables

The **cache tables** are [the runtime](08-runtime.md)'s: one `cache_index` over five `CacheLayer`
values (`blob`, `call`, `embed`, `render`, `signal`), with `cache_gc`, `cache_unit` and `cache_ns`.
Two facts from that table are load-bearing here:

1. **There is no `parse` or `derive` cache layer.** If it is a row in the `.owstore` it is never
   also a blob in the cache (INV-1). The parse memo *is* `work.status='done'` plus a matching
   `work.cache_key` plus a `doc(doc_key, gen)` row.
2. The `embed` layer caches embedding responses keyed on `cache_key()`, so rebuilding a `vec`
   sidecar after `rm index.vec.owstore` costs CPU, not a re-bill. **The `vec` sidecar being
   deletable is only cheap because of this.**

### 3.13 The index register

ST17: **every shipped index is named in `tools/indexes.toml` with the statement it serves, and
`ow store explain --golden` is byte-diff gated.** An index whose statement no longer exists is
deleted in the same PR; an index that appears in `sqlite_master` without a register row fails CI.
The register carries an **owner** column, because three of the indexes the query path depends on are
created by another migration file and the register is corpus-wide, not file-scoped:

| Index | Table | Owner | Serves | Shape |
|---|---|---|---|---|
| `block_addr` | `block` | 0001 | `ow open addr=p14/3`; `rebind` positional match | UNIQUE `(doc_ord, gen, addr)` |
| `block_cite` | `block` | 0001 | every `cite` resolution, on every surface | UNIQUE `(doc_ord, cite)` — **gen-free** |
| `block_sib` | `block` | 0001 | sibling ordering; duplicate-ord detection | UNIQUE `(doc_ord, gen, IFNULL(parent_id,-1), ord)` |
| `block_read` | `block` | 0001 | full-document render = one range scan | `(doc_ord, gen, page, ord)` partial `state=0` |
| `block_parent` | `block` | 0001 | containment walk, neighbour expansion | `(parent_id, ord)` partial `state=0` |
| `block_kind` | `block` | 0001 | `Filters.kinds` narrowing | `(doc_ord, gen, kind, page, ord)` partial |
| `block_cdig` | `block` | 0001 | `rebind()` rule 1 (equal digest under one parent) | `(doc_ord, content_digest)` |
| `block_review` | `block` | 0001 | the human review queue | partial `trust < 2 AND state = 0` |
| `block_restricted` | `block` | 0001 | gate 10 counting | partial `restriction_bits <> 0` |
| `diag_code` | `diag` | 0001 | **absence gate 9** — the one indexed join nobody else has | `(code)` |
| `anchor_corpus` | `anchor` | 0002 | corpus-scope resolution | partial `scope = 'corpus'` |
| `anchor_name` | `anchor` | 0002 | document-scope resolution | `(name_norm, akind, scope, doc_ord)` |
| `segment_block_seg` | `segment_block` | 0002 | the semantic lift (`ord`-ordered members) | `(segment_id, ord)` |
| `mention_block` | `mention` | 0002 | §7.4 graph impact | `(block_id)` partial `state = 0` |
| `segment_digest_ix` | `segment` | 0003 | the semantic join; embedding dedup | partial `state = 0` |
| `segment_doc` | `segment` | 0003 | segment-side page/document narrowing | partial |
| `segment_restricted` | `segment` | 0003 | gate 10 | partial |
| `block_sec_path` | `block_sec` | 0003 | `sec_path` prefix range scan; the lexical spine term | `(sec_path, block_id)` |
| `block_link_identity` | `block_link` | 0003 | `INSERT OR IGNORE` | UNIQUE, 6 columns, 2 sentinels |
| `block_link_out` | `block_link` | 0003 | `Expand` forward hop | `(src_block, relation)` |
| `block_link_in` | `block_link` | 0003 | `Expand` reverse hop; back-references | `(dst_block, relation)` |
| `block_link_bound` | `block_link` | 0003 | `anchor_delta` unbind | partial `bound_by IS NOT NULL` |
| `block_link_restricted` | `block_link` | 0003 | gate 10 on traversal | partial |
| `ref_site_block` | `ref_site` | 0003 | hydration; cascade locality | `(block_id)` |
| `ref_site_name` | `ref_site` | 0003 | the `exact` Channel; `anchor_delta` retry | `(name_norm, akind)` |
| `dep_reverse` | `dep` | 0004 | §11.4 invalidation, one query | `(kind, key, digest)` |
| `artifact_cite_block` | `artifact_cite` | 09-generation | §7.4 artefact impact | `(block_id)` |
| `retrieval_event_ts` | `retrieval_event` | events | ledger scans, retention | `(ts_ns)` |
| `retrieval_event_bad` | `retrieval_event` | events | "what degraded" | partial `verdict_state <> 'ok'` |

Twenty-nine index rows. The three virtual tables and their trigger sets are registered as
*statements* rather than indexes, on the same byte-diff gate, and they carry **the same owner
column** — a trigger name is global in `sqlite_master`, so each set has exactly one owning
migration, and a trigger set always ships in the same file as the table it maintains:

| Statement set | Owner | Where it is specified |
|---|---|---|
| `block_fts` + `block_fts_ai` / `block_fts_ad` / `block_fts_au` | 0001 | [the document model](03-document-model.md) §13.1 for the trigger text; §3.3 for the option set |
| `head_fts` + `head_fts_ai` / `head_fts_ad` / `head_fts_au` | 0003 | §3.3, printed in full |
| `block_tri` + `block_tri_ai` / `block_tri_ad` / `block_tri_au` | 0003, **conditional** on `[retrieval] trigram = true` | §3.4; `tools/indexes.toml` marks the whole set conditional, so a store built with `trigram = false` neither creates the statements nor is faulted for their absence |

The four `WITHOUT ROWID` primary keys in `vec` are registered as statements on that gate too.

## 4. Sizing and the latency budget

Every number in this section scales off **blocks per page**, which is the framework's largest
unresolved envelope (F1). The measured figure is **~338 B/block**; one deliberately pessimistic
synthetic corpus measured **912 B/block including FTS**. The shipped nightly ratchet budget is
`store.bytes_per_block = 660` at ±10%, and this section uses 660 as the planning number and 338 as
the optimistic one. Both are printed, because a projection with one number hides its own error bar.

### 4.1 Bytes per block

At 660 B/block, decomposed so a reviewer can attack a line rather than the total. Every row is an
estimate from the column types and SQLite's varint encoding; the total is what the nightly ratchet
measures.

| Component | Bytes/block | Note |
|---|---:|---|
| `block` row: `text` | ~140 | corpus-dependent and dominant. A prose paragraph is ~300 B; a table cell is ~10 B. The 60-120 blocks/page envelope is that wide **because cells are Blocks**. |
| `block` row: fixed scalars (~20 small ints) + row header | ~35 | SQLite varint encoding; most are single-byte |
| `block` row: `addr` + `cite` | ~16 | `p14/3` and `d7#412` |
| `block` row: `content_digest` + `layout_digest` | ~34 | two 16-byte `ow128` BLOBs + headers |
| `block` row: `quad` | ~34 | 8 × i32 LE; NULL on non-geometric blocks |
| `block` row: `origin_operator`, `origin_driver`, `os_part`, `os_extractor` | ~60 | four TEXT columns. The largest avoidable cost, and deliberately not interned: interning provenance into a side table trades 60 B/block for a join on every hydration. |
| `block` row: `x` (`'{}'`), `payload` (NULL), `raw_kind` (NULL) | ~5 | |
| **`block` row subtotal** | **~324** | |
| nine `block` indexes | ~130 | `block_addr`, `block_cite`, `block_sib`, `block_read`, `block_parent`, `block_kind`, `block_cdig` carry the weight; `block_review` and `block_restricted` are partial and near-zero on a healthy corpus |
| `block_fts` inverted index + docsize | ~70 | external-content, so no second text copy; ~40-50% of tokenised text, at `detail='full'` |
| `head_fts` | ~2 | `block.label` is NULL on ≥95% of rows |
| `block_sec` row + `block_sec_path` | ~50 | |
| `segment_block` row | ~20 | `WITHOUT ROWID`, three columns |
| `mark`, `rel`, `ref_site` (sparse, amortised) | ~40 | ~0.3 marks and ~0.15 ref_sites per block on a legal corpus |
| **Total** | **~636** | inside the 660 ± 10% budget |

Three costs are deliberately **outside** that number, because they are not per-block and reporting
them inside it would hide them:

- **`part` retention** roughly **doubles corpus storage** at `[store] retain_parts = "when_citable"`
  (the shipped default). CAS lives on the filesystem, not in the `.owstore`, and `ow store stats`
  reports the two separately for exactly this reason.
- **Free pages.** A full re-parse retires one generation of every block, so between the re-parse and
  the next `PRAGMA incremental_vacuum` (§2.2) the file holds up to **2×** its logical size.
  `ow store stats` prints `page_count` and `freelist_count`, and the 0.25 ratio trigger bounds the
  steady state at **1.25×**.
- **WAL.** `journal_size_limit = 67108864` caps the `-wal` at 64 MB in the steady state; a bulk
  window is budgeted at `wal.bulk_index_peak_bytes = 2 GiB ± 512 MiB`. Disk headroom at open is
  therefore checked as `index_bytes × 0.25 + 2 GiB + [cache.max_bytes] blob`, and a shortfall is a
  refusal at open, not a failure mid-index.

### 4.2 Bytes per link, per edge, per embedding

| Object | Row | Indexes | Total | Note |
|---|---:|---:|---:|---|
| `block_link` (block→block) | ~110 B | ~70 B | **~180 B** | five indexes, two of them partial. `MAX_LINKS_PER_BLOCK = 4096` |
| `edge` (entity→entity, L3's) | ~120 B | ~80 B | **~200 B** | five indexes including `edge_identity` (6 columns) |
| `mention` | ~70 B | ~55 B | **~125 B** | four indexes; `MAX_MENTIONS_PER_DOC = 250_000` |
| `segment` | ~200 B | ~40 B | **~240 B** | `heading_path` JSON dominates |
| embedding, `storage = 'sig_only'` | 16 B digest + 96 B signature + 0.125 B live bit + ~0.01 B amortised `vseg` row header | in the same BLOB | **~112 B/segment** | at `sig_bits = dim = 768`. **Not 12 B**: one sign bit per dimension of a 768-dim vector is 768 bits, which is 96 **bytes** — the same 96-byte signature §3.9's ceiling was measured on |
| embedding, `storage = 'sig_full'` | + `dim × 4` B + 16 B key + ~12 B `model_key` + ~5 B header | `WITHOUT ROWID` PK | **~3.2 KB/segment** | at `dim = 768`: 112 + 3,105 = 3,217 B |
| a stored float32 vector in a conventional vector DB | `dim × 4` B + index overhead | — | ~3.35 KB/chunk | LEANN's 60M-chunk/201 GB row implies exactly this |

The planning ratio is **~30 blocks per Segment** on prose (`SEGMENT_TARGET_TOKENS = 1200` ≈ 4,800
characters ≈ 30 blocks at 140 B/block). A table above `TABLE_SYNOPSIS_CELLS = 20_000` collapses to
**one** synopsis segment, so **a merge-free 4M-cell sheet is 4,000,000 FTS rows, 4,000,000 citable
Blocks and 1 embedding.** That is the priced answer to the spreadsheet, and it is why the
segment-count column below is not simply blocks ÷ 30 on a spreadsheet-heavy corpus.

### 4.3 Total index size

Blocks at 660 B/block (planning) and 338 B/block (measured-optimistic), segments at blocks ÷ 30,
vectors at `sig_bits = 768`:

| Blocks | ≈ pages (at 90 blocks/page) | `.owstore` @660 | `.owstore` @338 | segments | `vec` sig_only | `vec` sig_full | CAS at `when_citable` |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 10,000 | ~110 | 6.6 MB | 3.4 MB | 333 | 37 KB | 1.1 MB | ~7 MB |
| 1,000,000 | ~11,000 | 660 MB | 338 MB | 33,333 | 3.7 MB | 107 MB | ~660 MB |
| 10,000,000 | ~110,000 | 6.6 GB | 3.4 GB | 333,333 | 37 MB | 1.1 GB | ~6.6 GB |
| 100,000,000 | ~1,100,000 | 66 GB | 34 GB | 3,333,333 | 373 MB | 10.7 GB | ~66 GB |

Add the steady-state overheads of §4.1: **×1.25 for free pages** and **+64 MB of WAL** on the
`.owstore` column, so the 10M-block planning figure to provision against is ~8.3 GB, not 6.6 GB.

Two hard boundaries fall inside that table and must be stated before a reader plans against it:

- **`VEC_BRUTE_MAX = 250_000` segments** ≈ 7.5M blocks. The shipped stdlib backend refuses above it
  (`OW-S-022`), and degrades against its own 80 ms budget above ~197,000 (§3.9). 10M blocks needs an
  ANN `VectorBackend`, or `vectors = "off"` — which is the shipped default anyway.
- **`PREFILTER_MAX = 200_000` blocks.** Above that the narrowing set is not materialised and the
  planner switches to over-fetch (§6.1). This is not a failure; it is a different, disclosed mode.

The 5,000-page reference figure, worked end to end: 5,000 A4 pages at 60-120 blocks/page is
**300k-600k blocks**, ~200 MB of `.owstore` with FTS5 and ~45 MB as a `.owdoc` archive.

### 4.4 The query latency budget

`[retrieval.budget] query_ms = 250` is the gate (G10's cold-start table carries the row
"`ow query`, warm store ≤ 250 ms"). The nightly performance budget is `query.warm_p50_ms = 180` at
±20%. The five per-Channel budgets **sum below the query budget net of hydration and the coverage
scan**:

```toml
[retrieval.budget]
query_ms = 250
hydration_reserve_ms = 40        # hydration + the coverage scan. NOT a channel; NOT schedulable.
channel_ms = { identity = 15, exact = 25, lexical = 50, structural = 40, semantic = 80 }
#              15 + 25 + 50 + 40 + 80 = 210,  + 40 reserved  = 250  against  query_ms = 250
```

`ow route lint` check 3 **refuses** a set for which
`sum(channel_ms) + hydration_reserve_ms > query_ms`. The reservation is a key rather than an
implicit gap because the gap is the part a reader silently spends: a `channel_ms` edit summing to
249 passes an arithmetic that only compares against `query_ms`, and hydration then runs past the
gate on every query that merely used its budgets. A set that sums above the query budget
guarantees a G10 breach and turns the honesty machinery into permanent noise, because every query
that merely used its budgets would report `degraded`.

**`query_ms` bounds the snapshot-held phase only, and there is a phase before it.** Embedding the
query text is an `embed/1` Driver call — a model load, possibly a network round trip — and it runs
**before `snapshot()` opens**, with its own deadline:

```text
phase 1  sanitise + lift refs + plan()          pure, µs, memoised
phase 2  embed the query (semantic only)        embed_ms = 120, OUTSIDE query_ms, OUTSIDE the snapshot
phase 3  snapshot → narrow → channels → hydrate → coverage      query_ms = 250
phase 4  fuse, build_verdict, pack, encode      after the snapshot closes
```

Phase 2 is outside the snapshot **because a held read transaction pins the WAL** (§10.4), and an
inference call inside one is precisely the futility-latch condition codegraph measured at 22 GB of
WAL and exit 137. An `embed` call that exceeds `embed_ms` yields
`semantic: UNAVAILABLE(embed_timeout)`, which forces `degraded`; it never extends the snapshot. This
split is why the semantic Channel's 80 ms budget covers only `VectorBackend.search` plus the join.

Warm p50, single store, page cache warm, `vectors = "off"` (four Channels). **These are estimates
derived from the per-Channel budgets and the measured scan rate, not measurements** — Open question
F50 is the measurement, and `ow bench query` is the instrument: *(Build note, D915: `ow bench query` runs, end to end. Over `ow add`'s store of `gen_5000p_pdf` at 200 pages, 8,401 blocks, warm p50 is 9.4 ms against this table's ~12 ms at 10k; at 5,000 pages, 210,001 blocks, it is 95 ms, about four times what the 10k and 1M rows interpolate, though inside B27's 180. The difference is the narrowing probe: with default filters a store past `PREFILTER_MAX` copies 200,001 rows into `tmp_narrow` on every query to prove the set is `all`, measured at 62 ms of the 95, where this table budgets narrowing at 3 ms for 1M. It is bounded, since the probe stops at the cap, so it should not grow with scale; a cheaper proof for unrestricted filters is F50's open remedy, not taken here. Measured on a developer machine, not `ow-bench-1`.)* *(Build note, D918: by a user ruling of 2026-10-21 the narrowing probe counts before it copies when `stat.live_blocks` is missing or at least the cap, and copies only a set under it; under the cap the copy is the probe, as before. The stat orders two exact statements and never decides the tag. At 210,001 blocks the probe fell from 62 to 46 ms and the warm query from 97 to about 68 ms on the same four queries, on a developer machine.)*

| Blocks | narrow | identity | exact | lexical | structural | hydrate + coverage | **p50** | notes |
|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 10,000 | <1 ms | <1 ms | 1 ms | 4 ms | 2 ms | 4 ms | **~12 ms** | everything resident |
| 1,000,000 | 3 ms | 1 ms | 2 ms | 14 ms | 6 ms | 9 ms | **~35 ms** | FTS5 top-k with 5× over-fetch |
| 10,000,000 | 25 ms | 2 ms | 4 ms | 45 ms | 18 ms | 14 ms | **~110 ms** | narrowing may exceed `PREFILTER_MAX` |
| 100,000,000 | — | — | — | — | — | — | **~150 ms** | T4 only: 10 shards × 10M in parallel, + `federate_ms = 40` |

At T4 the budget is **`query_ms` per shard plus `federate_ms = 40` for fan-out and rank-merge**. The
merge is 10 shards × `k = 20` = 200 items, microseconds; `federate_ms` is entirely transport and
straggler tolerance. **The fabric never waits past `federate_ms`**: a shard that misses it does not
contribute, absence gate 14 (`shard_unreachable`) fires, and `Verdict.shards_contributed` names it.
p99 at T4 is therefore bounded by `federate_ms`, not by the slowest shard — the opposite of the
usual fan-out failure, and the reason the deadline is a store-level constant rather than a client
retry.

With `vectors = "on"` and the stdlib backend, add the signature scan: **~40 ms at 100k segments,
~101 ms at 250k** (§3.9), which is why the semantic Channel's own budget is the largest of the five.

Cold start is a separate budget owned by [performance](12-performance.md):
`import.omniweave_core_ms = 62`, `cold.ow_version_ms = 118`, both at ±25% on three OSes.

### 4.5 What the query path costs in memory

Three allocations, all bounded, because a serve process runs several queries at once:

| Allocation | Size | Derivation |
|---|---:|---|
| the narrowing TEMP table at the cap | **≤ 4 MB per concurrent query** | 200,001 rows × (8 B integer key + ~4 B cell overhead) ≈ 2.4 MB of leaf pages, +~1% interior, rounded up. In memory, because `temp_store = MEMORY` |
| the page cache | **64 MB per connection** | `cache_size = -64000` |
| a full `vseg` scan | **27.2 MB, mmap'd, shared** | §3.9; not per-query, because `mmap_size` maps it once |

A serve process holding 16 concurrent read connections therefore budgets ~1 GB of page cache and
≤64 MB of temp — which is why the concurrency cap is a config key
([interfaces](10-interfaces.md) owns its value) and not "as many as arrive".

## 5. The retrieval model

### 5.1 Five Channels, not four

jcodemunch fuses **four** signals in `src/jcodemunch_mcp/retrieval/signal_fusion.py` — `lexical`,
`structural`, `similarity`, `identity` — with `DEFAULT_WEIGHTS = {identity: 2.0, similarity: 0.8,
lexical: 1.0, structural: 0.4}` and `DEFAULT_SMOOTHING = 60`. omniweave takes that mechanism whole
and makes two changes, both forced by documents rather than code:

1. **`identity` splits into `identity` and `exact`.** In a code index, an identity match is a symbol
   name. In a document corpus there are two different exact things: *this block* (a `cite`, an
   `addr`, a document URI, a title) and *this named thing inside a block* (`§4.2(b)`, `Fig. 3a`,
   `GL-4471`, a citekey). They have different sources (`block_cite`/`block_addr` versus
   `ref_site`/`anchor`), different ladders and different weights. Folding them would make the
   `exact` weight unreachable.
2. **`similarity` is renamed `semantic`**, because the Channel is not a similarity score — it is a
   segment-level embedding hit **projected onto blocks** (§5.6).

```python
CHANNELS = ("identity", "exact", "lexical", "structural", "semantic")

class ChannelStatus(StrEnum):
    OK="ok"; EMPTY="empty"; OFF="off"; UNAVAILABLE="unavailable"

class OffReason(StrEnum):            # CLOSED. The only legal `reason` when status is OFF
    VECTORS="vectors"                # [retrieval] vectors = "off"       ceiling-EXEMPT
    NOT_IN_PLAN="not_in_plan"        # plan() did not select the Channel ceiling-EXEMPT
    NOT_BUILT="not_built"            # the P-stage has not shipped it    ceiling-EXEMPT
    QUERY_DEADLINE="query_deadline"  # the query ran out of time (§5.3)  ceiling-BEARING
```

`ok`/`empty` contribute weight to the ceiling. `off` is an **operator choice** and is disclosed.
`unavailable` contributes nothing **and forces `degraded`** — and a Channel that raised reports
`unavailable` with a `reason`. There is no `except: return []` under `retrieve/`, enforced by
semgrep, because a swallowed exception is how a Channel failure becomes a confident zero (ST8).

**`OffReason` is closed at four members, and this is its sole home.** It is closed because
`ceiling()` **branches on it** (§5.3): exactly one member, `QUERY_DEADLINE`, is ceiling-bearing, so
a free-form string decides a published `confidence` number and a misspelling changes that number
with no error anywhere. `no-embeddings` is a rejected synonym of `vectors`
([terminology.md](_notes/terminology.md) §3); the rendered trailer form is `semantic:off(vectors)`.
A Channel author who wants a fifth `OFF` reason needs a lock row, a member here, and a ruling on
whether it is ceiling-bearing — deliberately, because that ruling is the arithmetic. `reason`
remains a free `str` for `EMPTY` and `UNAVAILABLE`, because no arithmetic reads those; the
`UNAVAILABLE` vocabulary is deliberately **not** closed here, since §6.8 gate 1 reads
`reason == "timeout"` and the gate table is normative on its own terms.

```python
@dataclass(frozen=True, slots=True)
class ChannelResult:
    name: str; status: ChannelStatus
    ranked: tuple[int, ...]                       # block_ids, deterministic order, duplicate-free
    rank_of: Mapping[int, int] = MappingProxyType({})       # see below. Empty ⇒ rank is positional
    spans: Mapping[int, TextSpan] = MappingProxyType({})    # FTS5 offsets: sub-block addressing
    grades: Mapping[int, str] = MappingProxyType({})        # identity: the tier ACTUALLY measured
    weight: float | None = None                   # explicit (INCLUDING 0.0) wins; 0.0 IS A VALUE
    reason: str = ""                              # REQUIRED when status != OK; an OffReason
                                                  #   member when status is OFF, free prose otherwise
    truncated_at_limit: bool = False
    ran_ms: int = 0; cost: Spend = Spend()
```

No field defaults to `...` anywhere in a shipped shape. `x = ...` is legal Python that binds
`Ellipsis`, so the field is neither required nor defaulted and every consumer type-checks against
`EllipsisType`. A default is a real value or the field is required; those are the only two options.

**`rank_of` is the one field this document adds to the charter's shape, and it exists because the
charter's own semantics are otherwise unrepresentable.** The semantic Channel's contract is "a
segment hit at rank *r* yields its member blocks **at rank *r***", so up to 64 blocks share one
rank; jcodemunch's loop derives rank positionally (`for rank_0, sid in enumerate(ch.ranked_ids)`),
which would instead spread those 64 blocks across 64 distinct ranks and destroy exactly the
region-level property the rule exists to preserve. `rank_of` carries the authoritative 1-based rank
per block; it is empty for every Channel but `semantic`, and `fuse()` reads
`c.rank_of.get(b) or (position of b in c.ranked) + 1`. See **Extends the charter**.

### 5.2 How each Channel is computed

**`identity`** — a ladder over exact and near-exact addresses of a *block or document*. The reported
grade is **the one actually measured**, never the tier that was asked for.

```python
IDENTITY_LADDER = {
    "cite_exact": 50, "addr_exact": 50, "doc_uri_exact": 50, "doc_key_prefix": 48,
    "title_exact": 45,               # casefold only
    "title_normalised": 40,          # needed MORE than case: NFKC, punctuation, separators
    "title_prefix": 30, "spine_segment": 20, "none": 0}
```

The **40 tier is the first thing a "simplification" deletes and it must not be.** Collapsing 40 into
50 lets a punctuation-different match *tie* a literal one and fall through to BM25 — measured in the
source system as a test fixture outranking the symbol it tests by 0.355 of ~58. The document
analogue is "Table 3.2 (revised)" tying with "Table 3.2". Resolution is
`block_cite` / `block_addr` / `doc(uri)` index lookups plus a `head_fts` title probe; cost is
sub-millisecond and the Channel's budget is 15 ms only because a `Query.refs` tuple may carry many
tokens.

**`exact`** — `Query.refs` (reference-shaped tokens lifted out of the query text before it reaches
FTS) resolved against `anchor` through `ow_ref_resolved`, plus every `ref_site` occurrence of the
same `name_norm`. Ranking is: definitions before occurrences; corpus scope before document scope;
then `(doc_ord, page, ord)`. The lifted shapes are `derive.xref.pattern`'s own, and an unbound `:scope_doc` admits every document's definitions (D674).

```sql
-- the exact Channel, ONE statement over ALL lifted refs, over the narrowed set
SELECT n.block_id, 0 AS tier FROM anchor n
  JOIN doc dd ON dd.doc_ord = n.doc_ord AND n.gen = dd.gen
  JOIN tmp_refs r ON r.name_norm = n.name_norm AND r.akind = n.akind
  WHERE n.scope = 'corpus' OR n.doc_ord = :scope_doc
UNION ALL
SELECT s.block_id, 1 AS tier FROM ref_site s
  JOIN tmp_refs r ON r.name_norm = s.name_norm AND r.akind = s.akind
ORDER BY tier, block_id;
```

The refs go into a TEMP table `tmp_refs`, not into N statements. `MAX_QUERY_REFS = 16` bounds it
anyway, but the one-statement form is what keeps a 16-ref query at one plan instead of sixteen, and
it is what makes the `exact` Channel's `ran_ms` a single measurable number.

**`lexical`** — the one place "D5 owns the BM25 weights" is discharged.

```python
W_BODY = 1.0 ; W_HEAD = 6.0 ; SPINE_DECAY = 0.6 ; LEX_OVERFETCH = 5
# lex(b) = W_BODY × bm25n(block_fts, b)
#        + W_HEAD × max over a in spine(b) of ( bm25n(head_fts, a) × SPINE_DECAY**depth(b,a) )
```

`spine(b)` comes from `block_sec`; `b` is its own depth-0 ancestor. `bm25n` is FTS5's `bm25()`
min-max normalised **within the Channel's own result set**, so the Channel's output is a rank and
the raw scale never leaves it. Over-fetch is **5× before re-rank**: a re-ranker that only sees the
base scorer's top-k cannot promote what the base scorer buried.

**The lexical Channel carries no identity bonus**, deliberately, and jcodemunch's
`_bm25_score_no_identity` (`signal_fusion.py:355-390`) is the precedent: a title-exact match is
`identity`'s tier 45 and adding it to `lex()` as well would double-count one piece of evidence into
two Channel weights, inflating both `score` and `ceiling` for the same fact.

Query sanitisation is a **semantic transform, not escaping**:

| Input | Transform | Why |
|---|---|---|
| `§ ¶ † ‡ · —` | → space | `unicode61` drops them anyway; keeping them creates empty tokens |
| soft hyphen, `-\n` | folded | a line-broken word must match its unbroken form |
| `" * ( ) : ^ -` and bare `AND OR NOT NEAR` | stripped | a user cannot inject FTS5 syntax |
| `§4.2(b)`, `Fig. 3a`, `GL-4471`, `d7#412` | **lifted out** to `Query.refs` | they belong to `exact`, and they are noise to FTS; one whose lookup finds nothing is searched as a phrase after all (D648) |
| CJK runs | bigrammed | `unicode61` does not segment CJK |
| an unknown `foo:bar` prefix | passes through as **plain text** | so `TODO:` returns results |

`MAX_QUERY_TERMS = 64`, `MAX_QUERY_REFS = 16`, `MAX_QUERY_CHARS = 4_000`. The field DSL is
`kind: page: doc: layer: trust: quote: sec: lang:`, each validated against its enum; an invalid value
is a usage error naming the legal set, never a silent drop. English stopwords leave the FTS terms when another term remains (D649).

**`structural`** — a bounded frontier BFS over `block_link`, seeded from the union of the `identity`
and `exact` ranked sets; when both of those are empty, from the ranked set of whichever scoring
Channels **precede it in this plan** — `lexical`, which precedes `structural` in every plan that
contains one (§6.2), plus `semantic` in a plan that places `semantic` first, as the `thematic` rule
does; and when no scoring Channel precedes it, from `tmp_narrow` itself. Choosing the seed is a
runtime step, but it can never run out of options, because the run order is fixed by `plan()` before
any Channel executes — there is no re-ordering at runtime and no plan in which `structural` is asked
for a seed that has not yet been computed.

`edge` — L3's entity→entity table — is **not** traversed by this Channel at v1; it is reachable only
through the `@provisional` `GraphView.neighbours()`, outside `retrieve()`, with no budget, weight,
ceiling contribution or `Verdict`. [16](16-roadmap.md) W8.9 (P8, 4 units) is the scheduled work that
adds the L3 half, and this section is what it will change.

```python
@dataclass(frozen=True, slots=True)
class Expand:                        # BOUNDED BY CONSTRUCTION
    relations: frozenset[str]        # REQUIRED, no default. NEVER "all relations".
    max_hops: int = 2                # HARD CAP 4
    beam: int = 64                   # per hop, ordered by (weight × trust) / log1p(degree)
    min_trust: Trust = Trust.INFERRED
    max_visited: int = 4096
    hub_cap: int = 4096              # a block with more links contributes at most hub_cap
                                     # neighbours, sampled by weight, and sets
                                     # degradations += [Degradation(kind="hub_capped", …)]
```

A Python frontier BFS over batched `WHERE src_block IN (…)`, with an explicit visited set,
cancellable at the top of each hop, joining `tmp_narrow`. **Not** a recursive CTE: SQLite has no
built-in visited set and no per-hop fan-out bound, so a recursive CTE over a cyclic reference graph
is unbounded by construction. No CSR sidecar, no materialised closure, no graph engine at v1.
`relations` has no default because "all relations" on a document graph reaches every block in the
corpus within three hops; a relation not present in `relation_vocab` is a usage error naming the
vocabulary, because silently traversing nothing is indistinguishable from a corpus with no links.

**`semantic`** — the query text is embedded in **phase 2**, before the snapshot (§4.4), with
`query_prompt_digest` applied client-side, signed to `sig_bits`, and handed to
`VectorBackend.search(model_key, q_sig, q_full, k=…, candidates=…)`. The result is a list of
`segment.content_digest` values, joined **inside the main snapshot** to live segments:

```sql
SELECT s.segment_id, s.content_digest FROM segment s JOIN doc d USING (doc_ord)
 WHERE s.content_digest IN (…) AND s.gen = d.gen AND s.state = 0;
```

That inner join is the **only** exit from the `vec` sidecar (ST4), which is what makes a stale
vector invisible rather than wrong. A `SQLITE_CORRUPT` or `SQLITE_NOTADB` raised while reading the
sidecar is caught **at the Channel boundary only** and reported as
`UNAVAILABLE(vec_unreadable)` — the one place a store-level exception becomes a Channel status
rather than propagating, and it is why the sidecar is deletable in the first place.

### 5.3 Fusion: the formula and the defaults

```python
DEFAULT_WEIGHTS = {"identity": 2.0, "exact": 1.2, "lexical": 1.0,
                   "semantic": 0.8, "structural": 0.4}
RRF_K = 60 ; SCORER_VERSION = 1      # ONE constant, in omniweave_core.retrieve

def _weight(ch, w) -> float: return ch.weight if ch.weight is not None else w.get(ch.name, 1.0)
def _rank(ch, b) -> int: ...          # ch.rank_of[b] if present else 1 + ch.ranked.index(b)
def fuse(chs, *, k=RRF_K, weights=DEFAULT_WEIGHTS) -> list["FusedHit"]: ...
def ceiling(chs, *, k=RRF_K, weights=DEFAULT_WEIGHTS) -> float: ...
```

```text
rank(c, b) is 1-BASED:  rank ∈ [1, len(c.ranked)]
score(b)   = Σ_c  _weight(c) / (k + rank(c, b))     over c.status == OK
ceiling    = Σ_c  _weight(c) / (k + 1)              over c.status in (OK, EMPTY)
                                                    OR (c.status is OFF and c.reason ==
                                                        OffReason.QUERY_DEADLINE)   # §5.1, closed
confidence = best_score / ceiling                    low_confidence < 0.35
```

Worked, at `k = 60`:

| Channel set | Σ weights | ceiling | value |
|---|---:|---|---:|
| all five OK | 5.4 | 5.4 / 61 | **0.08852** |
| four (semantic off, the shipped default) | 4.6 | 4.6 / 61 | **0.07541** |
| lexical + identity only | 3.0 | 3.0 / 61 | **0.04918** |

**Never hardcode `1/(k+1)`.** These weights are not normalised to sum to 1, so the ceiling genuinely
depends on which Channels ran — which is the point. A single top-ranked hit in a three-Channel
consensus is a different claim from a single top-ranked hit in one Channel, and the ceiling is what
makes `confidence` say so. jcodemunch's own docstring names the bug this prevents: *"Retrieval
confidence's `strength` term reads a RAW top-1 score, so without this it grades every fused search
against the BM25 curve and reports near-zero for a perfect result."*

**`OFF` is two different things and only one of them is ceiling-exempt.** `OFF(vectors)` and
`OFF(not_in_plan)` are operator choices: the Channel was never going to look, so its weight has no
business in a denominator that measures "we looked there". `OFF(query_deadline)` is a **runtime
shortfall** — the Channel was in the plan, the query ran out of time, and nothing looked. Exempting
it from the ceiling shrinks the denominator and makes a *worse* answer report *higher* confidence,
which is the exact inversion `ceiling()` exists to prevent. `ChannelResult.reason` is already
REQUIRED whenever `status != OK`, so the discrimination costs nothing. ST6's property test gains a
third half: **(c)** with a member at `OFF(query_deadline)`, `ceiling()` is unchanged from the
all-ran case and `confidence` is strictly lower than it would be with that member `OK`.

`rank` being 1-based matters because `ceiling` hardcodes `k + 1` as the best attainable term: a
0-based implementation silently yields `confidence > 1`.

**Both functions resolve weights through `_weight()`.** A ceiling that drifts from the scorer
silently rescales every confidence number in the product. ST6's property test is therefore stated in
**three halves**:

- (a) over Channel sets whose members are **all `OK`**, `fuse()[0].score == ceiling()` to 1e-12;
- (b) with **any `EMPTY`** member, `fuse()[0].score < ceiling()` **and** `confidence < 1`;
- (c) with a member at **`OFF(query_deadline)`**, `ceiling()` is unchanged from the all-ran case and
  `confidence` is strictly lower than it would be with that member `OK`.

Half (a)'s all-`OK` antecedent is **rarely satisfied on a real corpus**, because an empty `exact`
Channel is routine and any `EMPTY` member moves the case to half (b) — which is why the test as
originally written failed almost everywhere. `vectors = "off"` does **not** bear on half (a) at all:
it yields `OFF(OffReason.VECTORS)`, which is ceiling-exempt (§5.1), so the shipped default's ceiling
is the four-Channel `4.6 / 61` printed in the table above, not a five-Channel `5.4 / 61`. Reading it
as `EMPTY` instead would cap every default-configured query's `confidence` at `4.6 / 5.4 = 0.852`
and silently rescale every calibration threshold in [quality](13-quality.md). An `EMPTY` Channel's
weight in the ceiling is deliberate: it discloses "we looked there and found nothing", which is
exactly the confidence penalty an honest ceiling should carry. Nobody may "simplify" it to match
`fuse()`, and nobody may drop the `OFF(query_deadline)` carve-out.

```python
@dataclass(frozen=True, slots=True)
class FusedHit:
    block_id: int; score: float
    channel_contributions: Mapping[str, float]; channel_ranks: Mapping[str, int]
```

A total order on `(-score, (doc_ord, page, ord), block_id)` (ST7; D655 put reading order before `block_id`, which is minted in the order documents finish parsing, so each Channel hands `fuse()` `ChannelResult.order`). Ties broken by storage order are nondeterministic across
a `VACUUM` or an FTS5 `'optimize'` — both of which §2.2 schedules, so this is a live hazard and not a
theoretical one — and a property test shuffles SQL row order 100× and VACUUMs, asserting an identical
ranking. **A fusion returning only a score is one you cannot tune**: the per-Channel contributions
and ranks are what make `ow query --explain` and weight fitting possible at all.

**Rank fusion, never score blending.** A linear hybrid blend adds a raw `bm25()` in the tens to a
cosine in [0,1]: whichever Channel has the larger numeric range wins, a single-Channel hit scores on
the same additive scale as a consensus hit, and ties break on dict insertion order. Rank fusion is
scale-free and federates; score blending does neither. LEANN's un-normalised `vector_weight` is the
worked counter-example — the dial is not meaningful.

### 5.4 Why the fusion key is the Block

Three of the five Channels are natively block-shaped. `block_id` is the only foreign-key target for
a Block (INV-1) and `cite` is the only citable token (INV-8). `restriction_bits`, `withheld` and
`matches_before_packing` are all per-block quantities that a segment-keyed fusion would have to lift
twice. And the segment-keyed proposal's own second stage — "select blocks within the winning
segments using the per-block evidence the lexical and identity Channels already produced" — is a
*second* fusion at block level with the ceiling computed one level up, which is precisely the drift
`ceiling()` exists to prevent.

The real problem a segment key identifies — a 4M-cell sheet must not become 4M embeddings — is
solved by the table synopsis rule (§4.2) instead.

### 5.5 Weight tuning and per-query override

Three mechanisms, in precedence order, and there is no fourth:

1. **`ChannelResult.weight`** — an explicit float, **including `0.0`**, set by the Channel builder
   from the plan. This is the per-query override: `ChannelSpec.weight` flows into it. `0.0` is a
   value, not "unset", and `_weight()`'s three-level resolution (explicit → named default → 1.0)
   with `None` as the sentinel is what makes the distinction representable. jcodemunch calls this out
   as *"trivial and constantly botched"*.
2. **`[retrieval.weights]` in `omniweave.toml`** — the deployment default, one key per Channel.
   Changing it changes `config_digest` and therefore `plan_digest`, so every `retrieval_event` row
   records which weights produced it.
3. **`.omniweave/policy.d/*.toml` with `surface = "retrieval"`** — a first-match-wins `[[rule]]`
   whose `then` carries a `weights` map, so weights can be conditioned on query shape (`mode`,
   whether `refs` is non-empty, corpus size). This is D4's grammar verbatim; the loader, the
   subsumption linter and the isotonic threshold fitter are reused unchanged.

Fitting is offline and evidence-bound: `ow route scoreboard --surface retrieval` reads
`retrieval_event` joined to the golden-query set, and `ow route propose` fits **one dimension at a
time** by isotonic regression over the decision log. A learned ranker is rejected at v1: there are
no labels on day one and it destroys replay. Weights are pinned in `omniweave.index.lock`'s header
line (`scorer=1`), and an eval run against unpinned weights is published `UNRANKED`, never as a
number (Q-G8).

`W_HEAD = 6.0` and `SPINE_DECAY = 0.6` are **unfitted** and carried as F11: nDCG@10 over
`fixtures/store/golden-queries.jsonl` with `W_HEAD` swept across {1, 2, 4, 6, 12}, `toc_entry`
included and excluded. If the curve is flat, `head_fts` is dropped and the lexical Channel becomes
one term.

### 5.6 The semantic lift, and the cap that bites

A segment hit at rank *r* yields **its member blocks at rank *r*** — carried in `rank_of`, §5.1 —
so a region-level signal stays region-level and the block-level Channels break the tie. The cap is
`SEM_BLOCKS_PER_SEGMENT = 64`, and because `MAX_SEGMENT_BLOCKS = 512`, the cap **can bite for up to
448 blocks of a large segment**. The selection rule is therefore named, deterministic and disclosed:

> the first 64 members in `segment_block.ord` order — which is `(page, ord)` by construction — and a
> truncated lift sets `Degradation(kind="segment_lift_capped", parts_affected=…)`.

Without a named rule the semantic Channel's lift is nondeterministic in exactly the place ST7 is
supposed to be provable, and up to 87% of a large table segment's citable cells are unreachable
through it with nothing recording the fact.

There is one further rule the lift needs and nothing else states: **a semantic hit whose segment is
a table synopsis (`segment.synopsis_of IS NOT NULL`) lifts to the synopsis segment's own blocks and
never to the 4M cells it summarises.** The synopsis is what was embedded; pretending otherwise would
make a cosine hit on eight sampled rows into a claim about the whole sheet. `Diag(OW_TABLE_SYNOPSIS_ONLY)`
is already in `ABSENCE_BLOCKING_DIAGS`, so a query whose only evidence is a synopsis degrades.

## 6. The query planner

```python
def plan(q: Query, caps: "IndexCaps", pol: "RetrievalPolicy") -> "QueryPlan": ...

@dataclass(frozen=True, slots=True)
class QueryPlan:
    channels: tuple["ChannelSpec", ...]          # ordered; THE ORDER IS THE RUN ORDER
    filters: Filters; fusion: "FusionSpec"; pack: "PackSpec"
    gates: tuple[str, ...]                       # which absence gates apply to THIS plan
    short_circuit: str | None                    # 'identity>=50 and mode=cite'
    scorer_version: int; plan_digest: str; policy_digest: str
```

`plan()` is **pure**: no clock, no RNG, no environment, no IO, **no store read**. It is memoised on
`(mode, channel set, filter-field set, policy_digest, caps_digest)` and carries the same semgrep
bans as `evaluate()`. Everything the planner needs to know about the store arrives as `IndexCaps`,
which the `Reader` computed once at open.

**A plan is a template; execution binds it.** The memo key excludes the query text, so
`QueryPlan.channels` holds `ChannelSpec`s with `bind = None`, and `retrieve()` produces the executed
specs with `dataclasses.replace(spec, bind=ChannelInput(...))` after phase 2. `plan_digest` is
computed over the **unbound** specs, so two different queries of the same shape share a plan digest
and the scoreboard can slice by plan — which is the whole reason the planner is pure. Without this
split, `Reader.channel(s, spec, n)` has no way to receive the query text at all and the signature is
unimplementable.

There is **no cost-based optimiser and no join-order search**. Join-order search over an embedded
store is untestable and produces plan flips that present to a user as outages. The planner makes
exactly four decisions.

### 6.1 Decision 1 — narrowing, a closed three-way choice

```python
@dataclass(frozen=True, slots=True)
class Filters:                       # FILTERS NARROW. CHANNELS SCORE WITHIN THE NARROWED SET.
    doc_keys: frozenset[bytes] | None = None    # above MAX_FILTER_DOC_KEYS ⇒ tmp_docs, not IN(…)
    uri_prefix: str | None = None
    formats: frozenset[str] | None = None      # 'owjob' is a usage error (NO_JOB_DOCS, §3.8)
    kinds: frozenset[Kind] | None = None
    layers: frozenset[Layer] = frozenset({Layer.BODY})
    pages: range | None = None       # step MUST be 1; any other step is a usage error
    sec_path_prefix: str | None = None          # zero-padded, e.g. '/0003/0007' (§3.6)
    lang: str | None = None
    min_trust: Trust | None = None
    min_quote: Quote | None = None
    deny_methods: frozenset[Method] = frozenset()   # V10-17. EMPTY = no restriction (ST5).
    deny_restriction_bits: int = 0   # set by POLICY, never by the caller (DR17)
    gen: Literal["head"] | int = "head"

class Narrowing(NamedTuple):         # a TAGGED type. `if candidates:` is UNREPRESENTABLE.
    kind: Literal["all", "set", "empty"]
    table: str | None                # 'tmp_narrow' iff kind == 'set'
    n: int                           # EXACT when kind == 'set'
```

```sql
CREATE TEMP TABLE IF NOT EXISTS tmp_narrow(block_id INTEGER PRIMARY KEY) WITHOUT ROWID;
DELETE FROM tmp_narrow;
INSERT INTO tmp_narrow SELECT b.block_id FROM block b JOIN doc d USING (doc_ord)
  WHERE b.state=0 AND b.gen=d.gen AND b.layer IN (…) AND b.kind IN (…)
    AND (b.restriction_bits & :deny)=0 AND b.trust >= :trust
    AND b.method NOT IN (…)                    -- OMITTED ENTIRELY when deny_methods is empty
    LIMIT :cap;                                -- cap = PREFILTER_MAX+1
```

`PREFILTER_MAX = 200_000`. A `LIMIT PREFILTER_MAX + 1` probe gives an **exact** candidate set or
**proves** it is too big. No histogram, no independence assumption, no cost-based optimiser. TEMP
tables are verified to work on a `mode=ro` main connection, which is what makes exact prefiltering
possible at all; the proposed rule that "a read requiring a TEMP table fails CI" was checked and is
wrong.

Three mechanics the temp table needs and nothing else states:

- **`IF NOT EXISTS` plus `DELETE FROM`, not `CREATE`/`DROP`.** A TEMP table lives in the
  *connection's* temp schema, and a read connection is pooled and reused across queries; a bare
  `CREATE TEMP TABLE` fails on the second query on that connection. The `DELETE` is O(rows) on an
  in-memory B-tree and costs less than the `CREATE`.
- **One connection serves one query at a time.** The connection is checked out for the `Snapshot`'s
  lifetime and returned when it closes. That is the enforcement of the previous rule, and it is why
  §4.5 budgets the temp table per *concurrent query* rather than per process.
- **`Filters.doc_keys` above `MAX_FILTER_DOC_KEYS = 1024`** goes into a second temp table
  (`tmp_docs`) joined in, not into an `IN (…)` list; SQLite's parameter and expression-tree limits
  make a 100k-element `IN` list a parse-time failure rather than a slow query. `Filters.pages` must
  be a `range` of step 1 — any other step is a usage error, because a strided page filter has no
  index expression and would silently become a full scan.

**`deny_methods` is the `Method` predicate, and it is a filter rather than a weight on purpose.**
[vision](00-vision.md) §8 records the hazard — a corpus that ingests its own compiled output and
then cites itself as a source — and prices the down-weight that was the alternative: `WORTH_QUOTE`
scores `Quote.RECONSTRUCTED` at 0.85 and `WORTH_TRUST` scores `Trust.INFERRED` at 0.80, so a
re-imported artefact still competes at **0.85 × 0.80 = 0.68** of a source Block's byte share for the
same relevance. **0.68 is not
zero, and a down-weight is not an exclusion**: a well-written generated summary outranks a
badly-scanned source page whose own worth multiplier is lower. A `Filters` predicate narrows
*before* any Channel scores, so it cannot be outvoted by a fusion weight — which is exactly why the
resolution is here and not a new score term, a new table or a sixteenth absence gate.

Four mechanics:

- **It is a deny list, and empty means "no restriction", never "restrict to nothing"** (ST5). The
  field's type is `frozenset[Method]`, not `frozenset[Method] | None`, because there is no third
  state to represent; `deny_methods=frozenset()` and the field's absence are the same query.
- **`block.method` is an integer code**, not a string ([document model](03-document-model.md)'s
  `block` DDL), so the `NOT IN (…)` list binds the `enum_val` codes for the named members. They are
  resolved on the read connection when the narrowing statement is prepared — inside `retrieve()`,
  never inside `plan()`, whose memo key carries the filter **field** set and no filter values.
- **There is no index on `block.method` and none is added.** The clause rides the prefilter scan
  that `state`, `gen`, `layer`, `kind`, `trust` and `restriction_bits` already pay for, and a
  single-column index over a ten-member enum is a scan wearing a B-tree.
- **The caller sets it; policy may add to it, never remove from it.** Unlike
  `deny_restriction_bits` (DR17: policy only), `deny_methods` is a caller-expressible intent. The
  shipped spelling is `Query(filters=Filters(deny_methods=frozenset({Method.ROUNDTRIP})))`; a
  `retrieval` policy rule may union members in, and the effective set is `caller ∪ policy`, so a
  policy can only ever narrow further. D780: DR17's policy now has a carrier. `RetrievalPolicy.deny_restriction_bits` is `[licence] deny_restrictions` (D779) as a mask, which `ow query` and `ow serve` read through `retrieve.plan.deny_of()`, and `plan()` attaches it to every plan's filters. A caller's own non-zero value is still refused, never silently replaced, and a policy that denies nothing leaves the caller's filters object as it was. The mask is no part of a plan's shape: `plan_digest` does not move with it, as 07:1545 keeps filters out of the shape. *(Build note, D859: until D859 the mask reached the plan and nothing else. `execute()` narrowed, ran every Channel and scanned coverage on the caller's filters, so `[licence] deny_restrictions` barred no block, through `ow query`, `ow_query` or the SDK. The Channel input is now rebound to the plan's filters. `Verdict.withheld` had been a constant `{"rows": 0}`, so gate 10 could not fire: with the mask applied, an answer the policy emptied would have read as citable absence. `narrow()` now counts the narrowing statement's exclusion, as gate 10's row prescribes. That count, appended to `Narrowing` with defaults, is the distinct blocks the mask removed plus each denied bit's own count, exact rather than capped. A barred answer is `degraded` with `restricted_withheld`, naming the bits by `Restriction` member.)*

**The CLI spelling this predicate needs, stated as a requirement rather than assumed.** No flag on
`ow query` currently reaches `Filters.deny_methods`, so on the CLI the predicate is expressible only
through a policy rule — which is the wrong carrier for a per-query intent, and leaves `V10-17`
without a command line. [interfaces](10-interfaces.md) §6.1 owns the verb-and-flag table and is
the only place a flag may be declared, so this document states the surface it requires and adds
nothing:

| Requirement on [10](10-interfaces.md) | Value |
|---|---|
| flag | `--deny-method M[,M…]` on `ow query`, repeatable, comma-accepting |
| argument | lowercase `Method` member names; an unknown name is a usage error naming the ten members |
| maps to | `Filters.deny_methods = frozenset(Method(v) for v in values)` |
| the `V10-17` invocation | `ow query "…" --deny-method roundtrip` |
| disclosure | the flag is a `Filters` field like any other, so it is inside `plan_digest`'s filter **field** set and shows in `--explain` |

A named `Method` list rather than a `--no-generated` boolean, because `deny_methods` is a set over a
ten-member enum and a boolean can only ever express one of its subsets; `roundtrip` is the only
member anything asks for today, and Open question F56 is the one that would widen it. Until that row
exists in [10](10-interfaces.md) §6.1, the CLI has no spelling and this document claims none. *(Build note, D901: that row exists now -- 10 section 6.1's `ow query` row carries `--deny-method M[,M…]`, by a user ruling of 2026-10-19 -- and `ow query "…" --deny-method roundtrip` reaches `Filters.deny_methods`, so `V10-17` has its command line.)*

`Verdict.generated_share` (§6.7) is the instrument that makes the predicate checkable rather than
merely available: it reports the `Method.ROUNDTRIP` share of the evidence actually returned, so
`generated_share == 0.0` under the restriction and `> 0.0` without it is a single assertion over one
self-ingesting fixture corpus. That pair is `V10-17` and it discharges [vision](00-vision.md)'s
`V-Q5`.

Above `PREFILTER_MAX`, narrowing becomes an over-fetch factor `clamp(1/selectivity, 1, 64)` computed
from the scalar counts in `stat`, with §3.8's staleness rule forcing the maximum clamp on a stale
`stat`. If post-filtering leaves fewer than `k`, absence gate 11 (`filter_starved`) fires and the
Verdict is `degraded` — never a short list presented as the whole answer.

**"No restriction" is not "restrict to nothing"** (ST5). `Narrowing` is a tagged type and semgrep
bans `if narrowing:`. The counter-example is measured and quotable: in jcodemunch's
`build_structural_channel` (`signal_fusion.py:203-224`), `candidate_ids` was falsy-checked, so a
query matching nothing produced an empty candidate set that *skipped the filter* and let **every
symbol with nonzero PageRank** into the Channel — the whole repository returned, ranked by
centrality, labelled "Confident matches returned", with `absent` unreachable on both fusion paths.
The repository's own note is the lesson: *"a ranking channel with no gate is a confidence bug, not
just a relevance bug."* omniweave's fixture for this is a nonsense query that must return 0 hits and
`absent`.

### 6.2 Decision 2 — which Channels run, in what order, with what budget

Channels run inside one `Snapshot`, each with its own `budget_ms`, in an order fixed when the plan
is built. The order in `QueryPlan.channels` *is* the run order — there is no second, executed-order
field and no runtime re-ordering:

```text
identity (15 ms) → exact (25 ms) → lexical (50 ms) → structural (40 ms) → semantic (80 ms)
```

That is the canonical order, and it is the order of §4.4's latency table, of
`[retrieval.budget] channel_ms`, and of the `--explain` block in
[observability](15-observability.md). `identity` and `exact` lead because they are the cheapest and
because they are what `short_circuit` fires on. **`structural` is placed after `lexical` in every
plan that contains a `lexical` Channel**, so its fallback seed is always available; it is placed
before `lexical` only when the plan contains no `lexical` Channel at all (the `structural-only`
rule), where it is seeded from `identity` ∪ `exact` or from `tmp_narrow` itself.

The placement is therefore a function of **the channel set alone**, which is already in `plan()`'s
memo key `(mode, channel set, filter-field set, policy_digest, caps_digest)`. That is what keeps the
planner pure: whether `identity` ∪ `exact` will turn out empty is a property of the query *text*,
which the memo key deliberately excludes, so it is not knowable at plan time and no ordering rule
may depend on it. A rule that names its own channel list fixes that list's order — `thematic` runs
`semantic` before `structural` because there the semantic ranked set is the seed — and the one
constraint `ow route lint` enforces on a hand-authored list is that a list containing both `lexical`
and `structural` names `lexical` first. Open question F53 asks whether the no-lexical plan should
run `structural` early at all.

Channel selection is authored in D4's rule grammar verbatim, `surface = "retrieval"`:

```toml
# .omniweave/policy.d/10-builtin-retrieval.toml
surface     = "retrieval"
policy_name = "builtin:balanced"

[thresholds]
low_confidence   = 0.35
identity_certain = 50

[[rule]]
id = "cite-shortcircuit"
on_unknown = "skip"
[rule.when]
"query.mode" = "cite"
"query.has_refs" = true
[rule.then]
channels = ["identity", "exact"]
short_circuit = "identity>=@thresholds.identity_certain"
[rule.then.weights]
identity = 2.0
exact = 1.2

[[rule]]
id = "structural-only"
on_unknown = "skip"
[rule.when]
"query.mode" = "explore"
"query.text_terms" = { lte = 0 }
[rule.then]
channels = ["identity", "exact", "structural"]
gates = ["+similarity_only:off"]

[[rule]]
id = "thematic"
on_unknown = "defer"
[rule.when]
"query.text_terms" = { gte = 4 }
"query.has_refs" = false
"caps.has_vectors" = true
[rule.then]
channels = ["lexical", "semantic", "structural"]
[rule.then.weights]
semantic = 1.2

[[rule]]
id = "default"
on_unknown = "skip"
[rule.when]
[rule.then]
channels = ["identity", "exact", "lexical", "structural", "semantic"]
```

Every clause is one key per line and no inline table spans a newline, because G27a `tomllib.load`s
every TOML block printed in a plan document. First match wins, comparison clauses only,
`@thresholds.<name>` is a **compile-time substitution** and not an expression — which is what makes
a threshold learnable by one-dimensional isotonic regression. `on_unknown` is required on any rule
reading a nullable key, and missing evidence is three-valued: a clause over an unavailable key is
UNKNOWN and propagates by Kleene rules. "A rule reading a `None` key does not match" is
`except Exception: return {}` wearing a policy file. `ow route lint` resolves every key in every
`when` clause and in `[thresholds]` against the `SignalSpec` registry, so an unregistered key like
`query.has_refs` fails CI rather than silently never matching.

### 6.3 Decision 3 — the over-fetch factor

`LEX_OVERFETCH = 5` for the lexical Channel, always, before re-rank. For the semantic Channel the
over-fetch is the narrowing selectivity clamp, and it is **pushed into the backend** as
`candidates`, never applied afterwards: post-filtering an ANN result with no over-fetch is silent
recall loss that presents as absence, which is exactly what `filter_starved` exists to catch when
pushdown is unavailable. A backend whose `manifest()` does not declare pushdown gets
`candidates = None` and the over-fetch clamp instead, and the Verdict records
`Degradation(kind="pushdown_unavailable")` — so the recall risk is on the response, not in a
changelog.

### 6.4 Decision 4 — the two deadlines, and the difference is the whole Verdict

```text
* a Channel that exceeds ITS OWN budget_ms returns UNAVAILABLE(timeout) with what it has,
  which contributes nothing to the score and FORCES degraded;
* a Channel PRE-EMPTED BY THE QUERY DEADLINE reports its partial ranking with
  truncated_at_limit = True and status OK, and the remaining Channels are not run and report
  OFF(query_deadline) — an operator-visible disclosure, not a failure, AND IT KEEPS ITS CEILING
  WEIGHT (§5.3): a runtime shortfall must not shrink the denominator.
```

Absence gate 1 (`timed_out`) reads **only the first case**, plus a snapshot expiry. Without this
split, a plan that merely used its budgets made every query `degraded`, which turns the honesty
machinery into permanent noise. Because the Channel budgets sum below `query_ms` net of hydration,
the second case is a safety net rather than the norm.

A Channel's deadline is checked at **cancellation points it declares**, not by a timer thread:
`lexical` checks after each over-fetch page, `structural` at the top of each hop, `semantic` after
each `vseg` row, `exact` and `identity` between statements. A Channel with no cancellation point
inside a single SQL statement cannot be pre-empted mid-statement — `sqlite3.Connection.interrupt()`
is the only lever and it aborts the whole transaction, so it is used **only** for the snapshot
deadline (§6.5), never for a Channel budget. That is why the per-Channel budgets are generous
relative to the measured costs in §4.4: they must bound a statement, not interrupt one.

### 6.5 Early-exit rules

| Rule | Condition | Effect |
|---|---|---|
| `short_circuit` | the plan's expression evaluates true after a Channel completes — e.g. `identity>=50 and mode=cite` | remaining Channels report `OFF(short_circuit)`; fusion runs over what ran; the ceiling shrinks accordingly and `confidence` is computed against it |
| empty narrowing | `Narrowing.kind == "empty"` | **no Channel runs at all**; every Channel reports `OFF(narrowing_empty)`; the coverage scan and the fifteen gates still run, so the answer is `absent` **or** `degraded`, never a silent zero |
| query deadline | wall clock exceeds `query_ms` | §6.4 case two |
| snapshot expiry | the `Snapshot` has been open longer than `[retrieval] snapshot_ms` (default 2,000; ceiling `MAX_SNAPSHOT_MS = 5_000`) | `interrupt()` the connection, abort with `OW-S-010` / `OW_SNAPSHOT_EXPIRED`, Verdict `degraded`. This is a **WAL-valve safety parameter**, not a UX parameter — a held read transaction pins the WAL, and 30 s of pinned WAL is the precise condition that produced 22 GB of WAL and exit 137 in codegraph |
| `k` satisfied at the identity tier | `mode == "cite"` and every requested `ref` resolved at grade 50 | as `short_circuit` |
| backend ceiling | `live_segments > VEC_BRUTE_MAX` on the stdlib backend | the semantic Channel reports `UNAVAILABLE(ceiling)` with `OW-S-022` **before** running, so the refusal costs nothing |
| FTS unavailable | `index_state.fts_state <> 'ok'` | `lexical` reports `UNAVAILABLE(fts_building)` / `(fts_stale)` with `OW-S-032` before running (§3.3) |

`mode = "prove_absent"` disables every short-circuit in the table's first, fifth and sixth rows: an
absence claim is licensed by *all* Channels having looked, so the plan runs to completion even when a
grade-50 identity hit exists.

### 6.6 Five worked plans

Corpus `handbook`: 17 documents, 41,822 live blocks, 1,390 segments, `vectors = "off"` unless the
example says otherwise.

**These five are illustrations. The contract is §6.7 (the `Verdict` record) and §6.8 (the fifteen
gates).** Where a transcript below abbreviates — a gate ladder rendered as prose, a `DegradeCause`
without its `detail` — §6.8's table is what an implementation is written and tested against.

**(1) `ow query "parental leave notice period"` — the ordinary mixed query.**

```text
narrow      : Filters(layers={BODY}) → kind="set", n=38,104 (< PREFILTER_MAX ⇒ exact)
channels    : identity(15) exact(25) lexical(50) structural(40) semantic(80)
  identity  : EMPTY  — no cite, addr, uri or title matched.        weight counts in ceiling
  exact     : EMPTY  — no reference-shaped token in the query
  lexical   : OK, 214 ranked (5× over-fetch of k=20 → 100, re-ranked with the spine term)
  structural: EMPTY  — no seed from identity/exact, so it seeds from lexical's re-ranked top 100
              (available because lexical precedes it in the plan). None of those 100 blocks has a
              block_link row whose other endpoint is in tmp_narrow, so the frontier is empty at
              hop 1: ranked=0, status EMPTY, weight still counts in the ceiling
  semantic  : OFF(vectors_disabled)      ← an OPERATOR CHOICE, disclosed
ceiling     : (2.0 + 1.2 + 0.4 + 1.0) / 61 = 0.07541      ← semantic OFF contributes NOTHING
best_score  : 1.0/(60+1) = 0.01639  (lexical rank 1 only)
confidence  : 0.01639 / 0.07541 = 0.217  → VerdictState.LOW_CONFIDENCE  (< 0.35)
```

This is the shipped default's honest behaviour: one Channel produced the hit, three looked and found
nothing, and the Verdict says `low_confidence` rather than presenting a lone BM25 hit as consensus.

**(2) `ow open handbook:d7#412` — purely identity, short-circuited.**

```text
narrow      : kind="all"   (a cite lookup does not need a candidate set)
short_circuit: identity>=50 and mode=cite      → FIRES after Channel 1
  identity  : OK, ranked=(block 412's block_id,), grades={…: "cite_exact"}
  exact structural lexical semantic : OFF(short_circuit)
ceiling     : 2.0 / 61 = 0.03279
best_score  : 2.0 / 61 = 0.03279
confidence  : 1.000  → VerdictState.OK
latency     : ~2 ms (one UNIQUE index lookup + hydration)
```

A retired cite resolves through `block_history.superseded_by` and says so; where `superseded_by IS
NULL` the answer is a stated refusal, `OW-M-030 / OW_CITE_RETIRED`, naming the generation and the
reason — never a silent miss and never a nearby block.

**(3) `ow query 'sec:/0003/0007' --want related` — purely structural.**

The user asks for everything under §3.7 that cross-references anything, with no query text at all.
`sec:/0003/0007` is the field DSL of §5.2, not the `--scope` flag, so it is lifted into
`Filters.sec_path_prefix` and leaves `Query.text` empty and `text_terms = 0`. `want = "related"` is
the packing preset that promotes `Expand` from the neighbourhood to the primary result
([interfaces](10-interfaces.md) §3.2 owns the closed five-member `want` enum
`passages | table | fields | outline | related`); it is a surface preset and never changes
`Query.mode`, which stays `explore`.

```text
Query(text="", refs=(), mode="explore",
      filters=Filters(sec_path_prefix="/0003/0007", layers={BODY}),
      expand=Expand(relations=frozenset({"refers_to","cites","part_of"}), max_hops=2))
narrow      : block_sec_path range scan '/0003/0007' ≤ sec_path < '/0003/0008' → kind="set", n=1,204
plan rule   : "structural-only"  (mode=explore, text_terms=0)
  identity  : EMPTY
  exact     : EMPTY
  structural: OK — frontier BFS seeded from tmp_narrow itself (no identity seed and no lexical
              Channel in this plan), 2 hops, beam 64, joined to tmp_narrow at every hop so the
              traversal cannot leave §3.7. 311 ranked, ordered by (weight × trust)/log1p(degree).
  lexical semantic : OFF(not_in_plan)  ← the plan did not select them; disclosed, not a failure
ceiling     : (2.0 + 1.2 + 0.4) / 61 = 0.05902
best_score  : 0.4 / 61 = 0.00656
confidence  : 0.111 → LOW_CONFIDENCE
gates       : "similarity_only" is REMOVED from this plan's gate set (the rule's
              gates = ["+similarity_only:off"]), because the semantic Channel did not run
```

The low confidence is correct and is not a defect: two of the three Channels in the plan looked and
found nothing, and a structural-only answer *is* weaker evidence than a consensus. The surface
renders it as a list with the confidence stated, not as an error. Note the zero-padded `sec_path`
(§3.6) — the un-padded form would have made `/0003/0010` sort below `/0003/0002` and returned a
wrong set with no error.

**(4) `ow query "what does this corpus say about supply-chain concentration risk"` — purely
thematic, `vectors = "on"`, `dim=768`, 1,390 segments.**

```text
plan rule   : "thematic"  (text_terms=7 ≥ 4, has_refs=false, caps.has_vectors=true)
channels    : lexical(50) semantic(80) structural(40)      ← identity/exact NOT in the plan
phase 2     : query embedded in 34 ms of embed_ms=120, BEFORE the snapshot opened
  lexical   : EMPTY — none of {supply, chain, concentration, risk} occurs as a term; the corpus
              says "single-source dependency"
  semantic  : OK, 12 segments above threshold → lifted to blocks via rank_of at the segment's
              rank, first 64 members per segment in segment_block.ord order (no segment here
              exceeds 64, so no segment_lift_capped Degradation)
  structural: OK, 40 blocks reached from the semantic seed over {refers_to, cites}
ceiling     : (1.0 + 0.8 + 0.4) / 61 = 0.03607
best_score  : 0.8/61 + 0.4/(60+3) = 0.01311 + 0.00635 = 0.01946
confidence  : 0.540 → VerdictState.OK
```

If the semantic Channel had been the **only** Channel to produce results, **absence gate 15
(`similarity_only`) fires last** and the Verdict is `degraded`, not `absent`. Every gate above it
names something the caller can fix; a cosine zero is a statement about **the model**, not about the
corpus, and it must never be citable as absence.

**(5) `ow query --mode prove_absent "is liability capped at twelve months of fees"` — the absence
query, all fifteen gates.**

```text
narrow      : kind="set", n=38,104
channels    : all five run to completion (no short-circuit in prove_absent)
  every Channel: EMPTY
coverage    : Reader.coverage(snapshot, filters) — one pass over ingest_scope (by URI prefix),
              unit freshness, work counts in scope, and the diag join
gate 1  timed_out               pass  (no channel exceeded budget_ms; snapshot 41 ms of 2,000)
gate 2  channel_unavailable     pass  (all five OK/EMPTY; none UNAVAILABLE, none off-but-requested)
gate 3  store_changed_mid_query pass  (index_state.generation identical at plan and at pack)
gate 4  coverage_incomplete     FAIL  ingest_scope: discovered 17, indexed 16, complete=0
gate 5  pending_work_in_scope   FAIL  1 work row 'pending' for 2024-appendix.pdf
gate 6  source_edited_unindexed pass
gate 7  freshness_unknown       pass
gate 8  inputs_unreadable       pass
gate 9  parse_gap_in_scope      FAIL  diag_code join: OW_NEEDS_OCR on 2024-appendix.pdf p.12-15
gate 10 restricted_withheld     pass  (0 rows removed by deny_restriction_bits)
gate 11 filter_starved          pass
gate 12 truncated_by_packing    pass  (matches_before_packing = 0)
gate 13 space_mismatch          pass  (vectors off ⇒ no space to mismatch)
gate 14 shard_unreachable       pass  (not federated)
gate 15 similarity_only         pass  (semantic was not the only Channel that ran)
⇒ VerdictState.DEGRADED, gates=("coverage_incomplete","pending_work_in_scope","parse_gap_in_scope")
⇒ DegradeCause(gate="parse_gap_in_scope",
               detail="diag_code join: OW_NEEDS_OCR on 2024-appendix.pdf p.12-15",
               diag_codes=("OW_NEEDS_OCR",), where=((7, 12, 15),),
               fix="ow add 2024-appendix.pdf --allow-cost 40000")
```

**Gate 9 is the one nobody else has.** It is one indexed join against `diag` over
`ABSENCE_BLOCKING_DIAGS`, or `doc.status != 'ok'`, or a page whose method never ran — and
`CREATE INDEX diag_code` exists specifically so that join is a lookup. It turns "OCR failed on pages
12-15" from a confident zero into a `degraded` Verdict naming the pages and the exact command that
clears it.

### 6.7 The `Verdict` — the record retrieval returns

`Verdict` is the output of the honesty apparatus and the most-referenced type in this plan. It is
defined **once**, in `omniweave_core.retrieve.verdict`, alongside `VerdictState`, `DegradeCause`,
`ABSENCE_GATES`, `ABSENCE_BLOCKING_DIAGS` and `build_verdict()`; it is rendered by
`omniweave_core.answer`; and it is the Python source from which `schema/verdict-v1.json` is
generated and byte-diff gated by `G6`. `VerdictState` is the charter's and is **referenced, not
redefined** — its one `return VerdictState.ABSENT` site is INV-11's and SV8's whole mechanism.

```python
# VerdictState, ABSENCE_GATES and ABSENCE_BLOCKING_DIAGS are the CHARTER'S and live in
# omniweave_core.retrieve.verdict beside the shapes below. They are REFERENCED here, not
# redefined: `ok | low_confidence | absent | degraded`, the fifteen-member precedence tuple
# (§6.8), and the thirteen `Diag` codes gate 9 joins against.

MAX_DID_YOU_MEAN = 5

@dataclass(frozen=True, slots=True)
class DegradeCause:                  # ONE per gate that failed. NEVER a summary of several.
    gate: str                        # a member of ABSENCE_GATES. NOT free text (§6.8)
    detail: str                      # one line; `ow why absent` prints it VERBATIM
    diag_codes: tuple[str, ...] = () # ABSENCE_BLOCKING_DIAGS members behind it. Gate 9 only
    where: tuple[tuple[int, int, int], ...] = ()   # (doc_ord, page_lo, page_hi), INCLUSIVE
    fix: str = ""                    # THE EXACT COMMAND THAT CLEARS IT. Parsed against the
                                     # Action registry and invoked in-process, NEVER shelled
                                     # ([13](13-quality.md) §8.6). "" only where no command clears
                                     # it — gates 3 and 14, whose fix is "retry" and "wait"

@dataclass(frozen=True, slots=True)
class Verdict:
    # ── the state, and why ──────────────────────────────────────────────────
    state: VerdictState
    gates: tuple[str, ...]                       # every gate that FAILED, in ABSENCE_GATES order.
                                                 # NOT QueryPlan.gates — see "Two `gates`" below
    degraded_because: tuple[DegradeCause, ...]   # one per member of `gates`, IN THE SAME ORDER
    # ── the arithmetic (§5.3) ───────────────────────────────────────────────
    scanned: Mapping[str, int]                   # four closed keys, below
    best_score: float | None                     # fuse()[0].score. None iff no Channel ranked
    score_ceiling: float                         # ceiling(). NEVER hardcode 1/(k+1)
    confidence: float | None                     # best_score / score_ceiling. None with best_score
    scorer_version: int                          # SCORER_VERSION. A bump invalidates a scoreboard
    plan_digest: str                             # QueryPlan.plan_digest — slices the scoreboard by
                                                 # query SHAPE. `policy_digest` is NOT here: the
                                                 # event writer reads it off the QueryPlan
    # ── what looked ─────────────────────────────────────────────────────────
    channels: Mapping[str, ChannelStatus]        # ALL FIVE members of CHANNELS, ALWAYS present.
                                                 # A missing key would be indistinguishable from
                                                 # OFF, which is the disclosure this exists to make
    freshness: Literal["fresh","refreshing","stale","unknown","not_tracked"]   # §11.3 fact 5
    coverage: "Coverage"                         # §16. Gates 4-9 read it; one scan produced it
    withheld: Mapping[str, int]                  # gate 10's counts, keys below
    matches_before_packing: int                  # gate 12. AN EMPTY RESPONSE IS NOT AN EMPTY SEARCH
    # ── the identity of the read ────────────────────────────────────────────
    space: Mapping[str, str] | None              # None iff no semantic Channel ran. Keys below
    snapshot_gen: int                            # Snapshot.generation (§11.3 fact 1); gate 3's read
    federated: bool
    shards_contributed: str | None               # T4 only; None on a single store. Gate 14
    fusion_kind: Literal["rrf", "rank_merge"]    # "rank_merge" IFF federated (§12.3); else "rrf"
    did_you_mean: tuple[str, ...]                # ≤ MAX_DID_YOU_MEAN, below
    # ── additive to the charter's shape — see **Extends the charter** ───────
    generated_share: float = 0.0                 # V10-17 / 00#V-Q5. In [0.0, 1.0]
    degradations: tuple["Degradation", ...] = () # [15](15-observability.md)'s type

    @property
    def citable_as_absence(self) -> bool:        # THE ONE GATE. NEVER A SECOND RULE.
        return self.state is VerdictState.ABSENT

def build_verdict(**kw) -> Verdict: ...          # THE ONLY CONSTRUCTOR (§6.8)
```

**Twenty-two fields: the charter's twenty, plus `generated_share` and `degradations`.** The order
above is the charter's order so the two prints diff cleanly, and both additions are last, with real
defaults, so a positional construction written against the charter's shape still type-checks.

**`fusion_kind` is `Literal["rrf", "rank_merge"]`, and the charter's printed `"exact"` is superseded
here.** The non-federated value names the arithmetic that actually ran, and §5.3's arithmetic is
weighted RRF — `fuse()`, `ceiling()`, `RRF_K = 60` — so `"rrf"` is the name of the thing.
`"exact"` cannot be that name for two independent reasons: it is already the name of one of the five
`CHANNELS` (§5.1), so a reader seeing `fusion_kind = "exact"` beside `channels["exact"]` has to
decide which sense is meant on every read; and it describes no fusion this document performs, since
nothing about single-store fusion is exact. Every other emitter of the field in the plan already
prints `"rrf"` or `"rank_merge"`, [18](18-api-sketch.md) §1.3's `Answer.fusion_kind` included: the
two fields carry the same literal. They do **not** carry the same value under federation —
`CorpusSet.query` issues one `retrieve()` per corpus and rank-merges the results, so the merged
`Answer` reads `"rank_merge"` over contributing `Verdict`s that each read `"rrf"` — but the shapes
agree, so this correction removes a third shape rather than creating one. The supersession is
recorded as charter errata; nothing else in the type moves.

**Two `gates`, and confusing them is the easiest bug in this document.** `QueryPlan.gates` is the
set of gates that are **non-vacuous for this plan** — it is authored by a policy rule
(`gates = ["+similarity_only:off"]` in the `structural-only` rule, §6.2) and it is a *disclosure*,
not a switch. Every plan evaluates all fifteen; a gate outside `QueryPlan.gates` is one whose
precondition cannot hold, so it passes vacuously and can never appear in `Verdict.gates`.
`Verdict.gates` is the subset that **failed**. `state is ABSENT` therefore still requires all
fifteen to pass ([13](13-quality.md) P-11), and no plan can buy an absence claim by shortening a
list.

**The closed key sets.** Every key below is always present when its map is; an absent key is a bug,
not a zero, because "we did not measure" and "we measured zero" are the distinction this whole type
exists to preserve.

| Map | Keys | Value |
|---|---|---|
| `scanned` | `narrowed` | `Narrowing.n` when `kind == "set"`; `stat.live_blocks` when `kind == "all"`; `0` when `empty` |
| | `blocks` | distinct `block_id`s any Channel ranked, before fusion. The TypeScript SDK's `scannedBlocks` ([10](10-interfaces.md) §9.5) is this key |
| | `segments` | distinct `segment_id`s the semantic Channel touched; `0` when it did not run |
| | `docs` | distinct `doc_ord`s among the fused hits |
| `withheld` | a `Restriction` member name | blocks removed by **that** bit. A key is present only when its count is nonzero |
| | `rows` | distinct blocks removed by **any** bit. Reserved; never a `Restriction` name. **Gate 10 reads this key and no other**, because a block carrying two bits must not count twice |
| `space` | `space_id` `model_key` `backend` `dim` `metric` `storage` | the `embed_space` row and `VecManifest` for the space that actually ran, rendered as strings |
| | `coverage` | `complete` \| `partial` \| `unknown` — `partial` when `vec_manifest.rows` disagrees with `stat.live_segments` (§9.3 step 3). A partially-built sidecar is a **disclosed** recall shortfall, never a silent one |

**`did_you_mean` is a by-product, never a second query.** It carries, in order: identity candidates
that resolved at `IDENTITY_LADDER` tier 30 or 20 (`title_prefix`, `spine_segment`) — below the tier
the Channel reports as a hit — followed by lifted `Query.refs` whose `name_norm` matched no `anchor`
row but whose `akind` has one. Both sets are already computed by the `identity` and `exact` Channels
inside the snapshot; nothing re-runs, no Channel re-executes, and `MAX_DID_YOU_MEAN = 5` bounds the
render. It is a suggestion string and it is **never** evidence: it carries no `cite`, no score and
no ceiling contribution.

**Two `retrieval_event` columns are deliberately not `Verdict` fields.** `policy_digest` is read off
the `QueryPlan` by the event writer, because a policy identity is a property of the plan and putting
it on the answer would give two types the same fact. `gap` is `hits[0].score - hits[1].score`,
computed by the event writer from `Response.hits` and stored for the scoreboard only: a second
per-answer score on the honesty record would be a second number a caller could read as licensing a
citation, and there is exactly one citability rule. Both columns therefore have a producer and
neither widens this type.

**`generated_share` — the read-back loop's guard, and the second half of §6.1's `Method`
predicate.**

```text
generated_share = Σ chars(h) for h in Response.hits where method(h) is Method.ROUNDTRIP
                  ─────────────────────────────────────────────────────────────────────
                  Σ chars(h) for h in Response.hits
                  ⇒ 0.0 when the denominator is 0 (an empty answer has no generated share)
```

Three decisions the formula does not show:

- **It is computed over `Response.hits`, not over the rendered Answer.** [vision](00-vision.md)'s
  New-terms row reads the same way — "a `Response`'s evidence characters" — and names the
  rendered-characters form as the one it rejects. The reason is that the rendered set moves with a
  *display* budget — `Answer.render(max_chars=…)`, the packing cliff, the emission ledger's
  withholding — and a provenance number that changes when a caller narrows its terminal is not a
  fact about the corpus. The set here is the one `PackSpec` bounded: `k`, `max_blocks`,
  `max_chars`. The renderer reads the number; it does not recompute it.
- **`chars(h)` is `length(block.text)` taken at hydration, not `len(Hit.text)`.**
  `PackSpec.hydrate_text = False` makes every `Hit.text` `None`, and a provenance number that
  silently becomes `0.0` because the caller asked for ids only is the failure mode this instrument
  exists to catch. §7.2's hydration statement therefore selects `b.method` and `length(b.text)` in
  both modes — two integers per returned block, bounded by `PackSpec.max_blocks`.
- **`0.0` is reported for an empty answer and for a corpus that has never ingested its own
  artefacts, and those are the same number.** They are separated by `Verdict.state`, which already
  says whether anything was returned. Making the field `float | None` to distinguish them would put
  a second nullable on the honesty record for a distinction another field already carries.

V10-17's fixture is a self-ingesting corpus: `generated_share == 0.0` with
`Filters(deny_methods=frozenset({Method.ROUNDTRIP}))` and `> 0.0` without it, asserted in
[13](13-quality.md) §10.1. *(Build note, D857: asserted twice. Over a seeded store, a source paragraph and a read-back block both answer the question, and `generated_share` is the read-back's characters over both, recomputed from the hits. Denying `roundtrip`, the source alone answers and the share is 0.0. A read-back alone is 1.0. Over a real loop, a deck is checked, compiled and read back by `ow out back` into the store it was compiled from: asked about it the share is 1.0, and denied it is 0.0 with no hits. That half is Windows-only, as the pptx loop's S4 arm is.)*

**`build_verdict()` is the only constructor, and this is the whole of its state rule.**

```python
def _state(gate_failed, hits, confidence, fusion) -> VerdictState:
    """INLINED IN build_verdict(). Not a second entry point and not separately importable."""
    failed = [g for g in ABSENCE_GATES if gate_failed(g)]      # ALL FIFTEEN. No short-circuit
    if failed:                              return VerdictState.DEGRADED
    if not hits:                            return VerdictState.ABSENT   # ← THE ONE SITE
    if confidence < fusion.low_confidence:  return VerdictState.LOW_CONFIDENCE     # 0.35
    return VerdictState.OK
```

Four properties of those four lines:

- **A failed gate forces `DEGRADED` whether or not hits were returned.** Gates are not only about
  absence: a `space_mismatch` on a query that returned twenty hits still degrades, which is what
  makes the paired-damage suite ([13](13-quality.md) §8.6) assertable on damaged runs that still
  answer.
- **All fifteen gates are evaluated on every query. There is no short-circuit after the first
  failure.** Gates 4-9 read one `Coverage` object produced by one scan, so stopping early saves
  nothing measurable; `degradation_detection == 1.000` asserts that *the expected* gate appears in
  `Verdict.gates`, which a short-circuit would break the moment two gates fired; §6.6's worked plan
  (5) reports three fired gates whose numbers are 4, 5 and 9; and `ow why absent` is specified to
  print the whole ladder including what passed.
- **`ABSENT` is the residual, not a gate's output.** No gate forces it and no gate can. It is
  reached only by falling through all fifteen with an empty hit list, which is why one `return`
  statement is a sufficient enforcement point and why a sixteenth hazard is added as a gate rather
  than as an `or` inside `citable_as_absence()`.
- **`LOW_CONFIDENCE` is below `DEGRADED` in the ladder and that is deliberate.** A degraded answer
  with high confidence is still degraded: the confidence number describes the Channels that ran, and
  a gate describes whether they were allowed to see the corpus.

### 6.8 The fifteen absence gates, normatively

`ABSENCE_GATES` is the charter's fifteen-member tuple and its **order is the precedence order**.
This is the table that makes "fifteen gates" checkable: one row per gate, each with the read it
performs, the predicate that fires it, and the fixture that proves it fires. `V01-8` requires one
fixture per gate; they live under `fixtures/store/absence/`, one directory per row, named for the
row.

The precedence order is not arbitrary and it is not cost order. It runs **outward**: gates 1-3 ask
whether the search itself happened, gates 4-9 ask whether the corpus the search ran over is whole,
gates 10-12 ask whether the answer that came back is whole, and gates 13-15 ask whether the machinery
that produced it was the machinery the caller configured. Within each band the more general claim
precedes the more specific one, so the first `DegradeCause` a caller reads is the one that subsumes
the others.

| # | Gate | Precedence rationale | Read source | Fires when | Forced state | Fixture |
|---|---|---|---|---|---|---|
| 1 | `timed_out` | First, because a Channel that ran out of time did not look — every later gate would describe a corpus that was never searched | `ChannelResult.status` / `.reason`; the `Snapshot`'s age against `snapshot_ms` | any Channel is `UNAVAILABLE` with `reason == "timeout"` (§6.4 case **one**), **or** the snapshot expired (`OW-S-010`). A Channel at `OFF(query_deadline)` is **not** this gate | `DEGRADED` | `g01_timed_out` |
| 2 | `channel_unavailable` | Same class of fact as 1 — a Channel that could not run did not look — and separated from it only by the reason, so it reads second | `Verdict.channels`; `QueryPlan.channels`; `Query`'s explicit channel request | any Channel is `UNAVAILABLE` for a reason other than `timeout`, **or** a Channel the caller explicitly requested reports `OFF`, **or** a Channel raised (there is no bare `except` under `retrieve/`, INV-12) | `DEGRADED` | `g02_channel_unavailable` |
| 3 | `store_changed_mid_query` | Last of the "did the search happen" band: the Channels did look, but at a corpus that moved, so the gates below would read a different generation than the one that was scored | `index_state.generation` captured at plan and re-read at pack (§10.4, §11.3 fact 4) | the two reads differ. One counter answers both "the index changed" and "rows moved during the scan", because the `.owstore` has one writer | `DEGRADED` | `g03_store_changed` |
| 4 | `coverage_incomplete` | First corpus-shape gate. "The scan never finished" subsumes every narrower per-unit claim below it | `Coverage.discovered / .indexed / .complete / .scope_rows`, from the `ingest_scope` rows in view (`doc.uri GLOB scope_id \|\| '*'`, §3.8) | `scope_rows == 0` **or** `discovered > indexed` **or** `complete` is false. **No row means coverage UNKNOWN, never clean** | `DEGRADED` | `g04_coverage_incomplete` |
| 5 | `pending_work_in_scope` | A queued unit is a coverage hole with a completion date — a narrower claim than 4, and one whose fix is "wait or raise the budget" | `Coverage.pending_work`: `work.status IN ('pending','claimed')` for units inside the scope | `pending_work > 0` | `DEGRADED` | `g05_pending_work` |
| 6 | `source_edited_unindexed` | The corpus is complete and idle, but a source moved under it. Below 5 because a `work` row is a *known* hole and an edited source is an *inferred* one | `unit.size` / `.mtime_ns` against `doc.indexed_at_ns`, the `stat_fresh` predicate of §11.3 fact 5; at query time the size and mtime clauses over at most 2,000 indexed files in scope, most recently indexed first (D647) | `st_mtime_ns + MTIME_GRANULARITY_NS > indexed_at_ns` for any doc in scope — the racily-clean window, 2 s | `DEGRADED` | `g06_source_edited` |
| 7 | `freshness_unknown` | We could not even ask question 6. Below it because 6 is a positive finding and 7 is an absence of evidence | `Reader.coverage()`'s freshness roll-up, surfaced as `Verdict.freshness` | `freshness == "unknown"`. **`not_tracked` is deliberately not a failure**: an untracked source is disclosed, not refused | `DEGRADED` | `g07_freshness_unknown` |
| 8 | `inputs_unreadable` | Names a specific unit the scan should have read and could not, so it ranks below the not-knowing of 7 and above the parse-level detail of 9 | `Coverage.unreadable_units` | `unreadable_units > 0` | `DEGRADED` | `g08_inputs_unreadable` |
| 9 | `parse_gap_in_scope` | **The one nobody else has.** Last corpus-shape gate because it is the most specific: the scan finished, the units are fresh and readable, and the **parse** still left a hole. It is also the only gate that can name pages and print a command | one indexed join of `diag` against `ABSENCE_BLOCKING_DIAGS` over docs in scope (`CREATE INDEX diag_code` exists for exactly this), plus `doc.status <> 'ok'`, plus a page whose `method` never ran — grouped by `(doc, page range)` into `Coverage.gaps` | `Coverage.gaps != ()` | `DEGRADED` | `g09_parse_gap` |
| 10 | `restricted_withheld` | First result-shape gate. The corpus is sound; the answer is short because **policy** removed rows — a fact the caller can learn no other way, so it outranks the two retrieval shortfalls below it | the narrowing statement's `(b.restriction_bits & :deny)` exclusion count, aggregated into `Verdict.withheld` (§3.6's `block_restricted` partial index serves it without scanning live segments) | `withheld["rows"] > 0`. **Counted, never silent** | `DEGRADED` | `g10_restricted_withheld` |
| 11 | `filter_starved` | A narrowing that starved the ranker is a recall loss that presents as absence — the precise failure the ladder exists to intercept. Below 10 because it is a retrieval shortfall, not a policy one | the semantic Channel's over-fetch outcome and the post-filter survivor count; `VecManifest.pushdown` | a Channel that could **not** push its filter into the backend hit the over-fetch cap and post-filtering left fewer than `PackSpec.k` candidates. Vacuous where pushdown is available or no ANN ran | `DEGRADED` | `g11_filter_starved` |
| 12 | `truncated_by_packing` | The loss happened after ranking, at the last bound the caller controls, so it is the last result-shape gate | `Verdict.matches_before_packing` and `len(Response.hits)` | `matches_before_packing > 0 and len(hits) == 0`. **AN EMPTY RESPONSE IS NOT AN EMPTY SEARCH** | `DEGRADED` | `g12_truncated_by_packing` |
| 13 | `space_mismatch` | First machinery gate: a semantic Channel that ran against the wrong space produced numbers, not evidence. It is a configuration fact rather than a per-query one, and it is vacuous at `vectors = "off"` | `vec_manifest.model_key` and `.corpus_id` against the `embed_space` row for `index_state.default_space_id` and the configured `embed/1` Driver's nine-field tuple (§3.7, §9.3 step 5) | either disagrees — the same comparison that raises `OW-S-020` on the build path, so a mismatch degrades the **search** rather than only refusing the build | `DEGRADED` | `g13_space_mismatch` |
| 14 | `shard_unreachable` | T4 only and vacuous at T1-T3, so checking it late costs nothing on the store every reader actually has | `Verdict.federated`, `Verdict.shards_contributed`, the `federate_ms` fan-out result | `federated` and `shards_contributed` names fewer shards than the configured set. A shard that misses `federate_ms` does not contribute and is named here | `DEGRADED` | `g14_shard_unreachable` |
| 15 | `similarity_only` | **Checked last, and the order is the entire argument.** Every gate above names something the caller can fix; a cosine zero is a statement about **the model**, not about the corpus. Firing it earlier would mask a fixable cause behind an unfixable one | `Verdict.channels` | the only Channel with `status is OK` was `semantic`. Vacuous in any plan with no semantic Channel — which is what `gates = ["+similarity_only:off"]` discloses (§6.2, §6.6 plan 3) | `DEGRADED` | `g15_similarity_only` |

**Every row's forced state is `DEGRADED`, and that uniformity is the design.** There is one
citability rule and one `ABSENT` return site; a gate's only power is to take `ABSENT` off the table
and say why. A gate that could force some *other* state would be a second rule, which is exactly
what `citable_as_absence` refuses to grow.

**A gate that fires does not end the ladder, and no renderer may show one that did.** All fifteen
rows above are evaluated on every query, whatever fired before them: that is what makes §6.6's plan
(5) able to report three fired gates at once, and what makes an `Injector` targeting gate 13
assertable on a corpus that also has a parse gap. `build_verdict()`'s `_state` (§6.7) is written
that way — `failed = [g for g in ABSENCE_GATES if gate_failed(g)]`, the whole list, no
short-circuit. The ladder, its precedence and the one citability rule are this document's; a
renderer owns only the rendering, and it therefore has fifteen rows to print, passes included
([15](15-observability.md) §6.2).

**Fifteen gates against thirteen `Injector`s — the two counts measure different populations, and no
sixteenth Injector is owed.** [13](13-quality.md) §8.6 defines its `Injector` set as **one per
`Diag` code in `ABSENCE_BLOCKING_DIAGS`**, which is thirteen by construction. It is not, and was
never, one per gate. Only **six** of the fifteen gates are reachable by injecting a `Diag`; the
other nine are reached by manipulating store state, timing, policy or topology, and their fixtures
are built that way. The mapping:

| Gate | `Diag`-driven? | Injector(s) that reach it | How the fixture is built otherwise |
|---|---|---|---|
| 1 `timed_out` | yes | `stall` | — |
| 2 `channel_unavailable` | yes | `deny_probe` | — |
| 4 `coverage_incomplete` | yes | `drop_part` | — |
| 5 `pending_work_in_scope` | yes | `budget` | — |
| 9 `parse_gap_in_scope` | yes | `encrypt`, `strip_text_layer`, `chaos`, `downgrade_origin_span`, `mask_format`, `inflate`, `strip_integrity`, `synopsize` (eight) | — |
| 13 `space_mismatch` | yes | `rotate_embedder` | — |
| 3 `store_changed_mid_query` | **no** | — | a second connection commits between the plan read and the pack read |
| 6 `source_edited_unindexed` | **no** | — | `utime()` a tracked source after indexing |
| 7 `freshness_unknown` | **no** | — | a tracked source whose `stat()` raises `PermissionError` |
| 8 `inputs_unreadable` | **no** | — | a unit whose path is removed after `ingest_scope` was written |
| 10 `restricted_withheld` | **no** | — | a corpus with a nonzero `restriction_bits` and a policy that denies that bit |
| 11 `filter_starved` | **no** | — | a `VectorBackend` whose `manifest()` declares `pushdown = false`, plus a filter that survives < `k` |
| 12 `truncated_by_packing` | **no** | — | `PackSpec(max_chars=…)` below the smallest matching block |
| 14 `shard_unreachable` | **no** | — | F35's two-shard fixture with one shard stopped |
| 15 `similarity_only` | **no** | — | a `thematic` plan where `lexical` and `structural` are `EMPTY` and `semantic` is `OK` |

6 + 9 = 15 gate fixtures under `fixtures/store/absence/`; 13 `(Injector, fixture)` pairs under
[13](13-quality.md) §8.6. The two registers overlap on six rows and neither is a subset of the
other. `degradation_detection == 1.000` is a claim about the thirteen; `V01-8` is a claim about the
fifteen; both are now checkable, and this table is the join. **Nothing here asks
[13](13-quality.md) for a fourteenth or fifteenth Injector** — an Injector with no `Diag` behind it
would break that document's own defining rule for the set.

## 7. Result shaping

### 7.1 What `retrieve()` returns

```python
def retrieve(r: Reader, q: Query, pol: "RetrievalPolicy") -> "Response": ...

@dataclass(frozen=True, slots=True)
class Hit:
    block_id: int                       # the durable id; the only FK target for a Block
    cite: str                           # 'handbook:d7#412' — the prompt-safe token
    addr: str                           # 'p14/3' — the type-free path address
    score: float                        # the fused RRF score
    text: str | None                    # the evidence. None iff PackSpec.hydrate_text is False
    span: TextSpan | None               # sub-block offsets, when the producing Channel had them
    channel_contributions: Mapping[str, float]
    channel_ranks: Mapping[str, int]
    identity_grade: str                 # the tier ACTUALLY measured, e.g. 'title_normalised'
    segment_id: int | None
    trust: Trust
    quote: Quote
    byte_exact: bool                    # §8.2's one predicate, evaluated at one call site
    restriction_bits: int

@dataclass(frozen=True, slots=True)
class Response:
    hits: tuple[Hit, ...]
    verdict: Verdict
    cost: Spend
```

`Response` has exactly three fields. `Hit` has fourteen: the charter's thirteen plus `text`, which
this document adds because without it the evidence text has no carrier inside the snapshot —
see **Extends the charter**. Three things a reader might expect on `Hit` and will not find are
deliberate:

- **There is no per-hit confidence.** `confidence` is `best_score / ceiling` and is a property of the
  *answer*, on `Verdict`. A per-hit confidence would be a second number that licenses a citation,
  and there is exactly one citability rule (`Verdict.state is ABSENT` for absence; `byte_exact` for
  a verbatim quote).
- **The neighbourhood is not a separate field.** A neighbour reached by `Expand` **is a `Hit`** whose
  `channel_ranks` contains `"structural"` and nothing else — that is the predicate a consumer uses to
  separate primaries from neighbours, and it is stated here so nobody invents a flag. Adding a
  `neighbours` list would create a second shape for a block and a second place restriction filtering
  could be forgotten.
- **Impact is not on `Hit` at all.** "Which artefacts quote this block" is a different, explicitly
  requested read served by `ow open`, not by every search result — §7.4.

`Hit.span` is a `TextSpan` into the block's own `text`, taken from `ChannelResult.spans` when the
producing Channel had sub-block resolution (FTS5 instance offsets at `detail='full'`, a `ref_site`
`(ts_a, ts_b)` pair). It is the sub-block address a highlighter or an OUT citation uses; it is never
invented when the Channel had no offset.

`Hit.identity_grade` is **the tier actually measured**, not the tier requested — `"title_normalised"`
where a normalised title matched — so a reader can tell a punctuation-different match from a literal
one without re-running the ladder.

### 7.2 Hydration

`hydrate()` is one statement per batch of up to 512 ids, **inside the same `Snapshot`**:

```sql
SELECT b.block_id, b.cite, b.addr, b.page, b.kind, b.layer, b.text, b.trust, b.quote,
       b.restriction_bits, b.os_kind, b.os_part, sb.segment_id,
       b.method, length(b.text) AS chars,
       d.uri, d.achieved
  FROM block b
  JOIN doc d USING (doc_ord)
  LEFT JOIN segment_block sb ON sb.block_id = b.block_id
 WHERE b.block_id IN (…) AND b.state = 0 AND b.gen = d.gen;
```

`d.achieved` rides along because `byte_exact` is computed from it (§8) and re-querying `doc` per hit
would be N+1. A row that fails the `gen`/`state` predicate is **dropped and counted**, and a
non-zero drop count means the store advanced mid-query, which gate 3 reads.

`b.method` and `length(b.text)` ride along for two consumers that are neither of them `Hit` fields:
`RenderedBlock.method` ([18](18-api-sketch.md) §1.3, an `@stable` field of the rendered evidence row)
and `Verdict.generated_share` (§6.7). Both are selected **even when `PackSpec.hydrate_text` is
`False`**, which is what stops a provenance number from collapsing to `0.0` because a caller asked
for ids only; `length()` on a column SQLite is already reading costs nothing beyond the transfer of
one integer per returned block, and the row count is bounded by `PackSpec.max_blocks`. Neither
column widens `Hit`, which stays at fourteen fields.

Reading `b.text` here rather than after the snapshot closes is the whole reason `Hit.text` exists:
the alternative is that the Answer renderer re-reads block text through a `Doc` handle *after* the
transaction ends, at which point a committed re-index can hand it text from a different generation
than the one that was ranked and scored. Gate 3 would detect the generation change but the evidence
would already be wrong, and ST2 ("one query = one snapshot") would hold for the ranking and fail for
the payload.

### 7.3 Token budget

Retrieval's own bound is on `Query`, and it is a bound on **work**, not on prose:

```python
@dataclass(frozen=True, slots=True)
class Query:
    text: str = ""; refs: tuple[str, ...] = (); filters: Filters = Filters()
    mode: Literal["find","cite","explore","prove_absent"] = "find"
    k: int = 20; max_blocks: int = 60; max_chars: int = 24_000
    space_id: int | None = None
    expand: "Expand | None" = None
    budget: "QueryBudget | None" = None      # None => the retrieval policy's default budget
```

`k = 20` bounds fusion output; `max_blocks = 60` bounds hydration; `max_chars = 24_000` bounds the
text hydration reads, applied **per response, in `hits` order**, so the drop is deterministic and
the cut is at a block boundary. `Verdict.matches_before_packing` records how many blocks fused above
zero **before** any of these bounds applied — which is what makes absence gate 12
(`truncated_by_packing`) possible at all. **An empty response is not an empty search**, and reporting
the candidate pool as the answer is the specific lie that gate exists to prevent.

Everything downstream of that — the 24,000-character `HARD_CEILING`, the five `BUDGET_TIERS`, the
15% cliff, the reserve-then-render allocator, the drop order under pressure and the emission ledger
— belongs to [interfaces](10-interfaces.md) and is not restated here. The contract this document
owes it is exactly: a totally ordered `hits` tuple, each `Hit` carrying its own `text` and `span`, a
`Verdict` whose `matches_before_packing` and `withheld` are already computed, and a `Spend`.

`Query` has **no `corpora` field**. `retrieve()` takes one `Reader`, a `Reader` is one store, and a
store is one corpus. A surface asked to span corpora issues N calls and rank-merges them, disclosing
`fusion_kind = "rank_merge"`. Cross-corpus BM25 scores are incomparable for the same reason
cross-shard ones are, and pretending otherwise inside one `Query` would have hidden it.

### 7.4 Impact, as a named read rather than a field

"Which decks quote page 14 of this contract" is answered by three indexed queries in one snapshot:

```sql
-- artefact impact: what has this block been compiled into?
SELECT ac.artifact, ac.artifact_gen, ac.unit, ac.el, ac.kind, ac.verbatim
  FROM artifact_cite ac WHERE ac.block_id = :block_id;           -- index: artifact_cite_block
-- graph impact: what points at it, and how heavily?
SELECT relation, COUNT(*) FROM block_link WHERE dst_block = :block_id GROUP BY relation;
SELECT COUNT(*) FROM mention WHERE block_id = :block_id AND state = 0;
```

`artifact_cite` is [generation](09-generation.md)'s table and is the **authoritative** citation
channel; its `verbatim` bit is *proved*, never claimed. The surface that renders this is `ow open`'s
back-references section ([interfaces](10-interfaces.md)); the store's obligation is the three
indexes registered in §3.13 (`artifact_cite_block`, `block_link_in`, `mention_block`) and the
guarantee that all three are answerable in **one** snapshot — which is why they are in the corpus-wide
register even though two of them are created by other migration files.

### 7.5 The compact wire encoding — `owrows/1`

**Decision: omniweave ships a MUNCH-derived tabular encoding named `owrows/1`, applied only to the
structured half of a response, and never to the MCP Answer.**

jcodemunch's MUNCH (`SPEC_MUNCH.md`, 252 lines, "Version 1, stable since 1.54.0") is the right
mechanism and its savings are measured against tiktoken `cl100k_base` (`TOKEN_SAVINGS.md`):

| tool | encoder | JSON tokens | MUNCH tokens | saved |
|---|---|---:|---:|---:|
| `find_references` | `fr1` | 2,265 | 1,242 | 45.2% |
| `get_dependency_graph` | `dg1` | 1,702 | 998 | 41.4% |
| `get_call_hierarchy` | `ch1` | 4,133 | 2,238 | 45.9% |
| `search_symbols` | `ss1` | 4,545 | 2,754 | 39.4% |
| `get_repo_outline` | `ro1` | 4,642 | 2,277 | 50.9% |
| `get_hotspots` | `gen1` | 1,987 | 887 | 55.4% |

**Median 45.5%, mean 46.4%, min 39.4%, max 55.4%.** jcodemunch is dual-licensed (free personal,
commercial licence required), so omniweave takes the **pattern and the spec, not the code**: no
vendoring, no copied module, and `owrows/1` is specified here in full so it can be implemented from
this document. [Security and licensing](14-security.md) owns the licence register row.

The mechanism only pays on **row-shaped** results. omniweave's flagship payload is verbatim document
text inside fenced blocks, which a tabular encoding cannot compress at all. So the split is explicit
and structural:

| Payload | Encoding | Why |
|---|---|---|
| the evidence text (`ow:evidence`) | fenced UTF-8, never encoded | it is prose; MUNCH's own lesson |
| `hits` (14 columns × up to 20 rows, `text` excluded) | `owrows/1`, encoder `hit1` | dense, repetitive, prefix-heavy |
| the provenance rows (11 columns × up to 20 rows) | `owrows/1`, encoder `prov1` | the highest-ratio table in the product |
| `Expand` neighbourhood edges | `owrows/1`, encoder `nb1` | `(src, dst, relation, weight)` |
| `Verdict` scalars, gates, degradations | the scalars section of the same payload | one line of `key=value` |
| anything else | `owrows/1`, encoder `gen1` | the generic fallback |

`hit1` encodes thirteen of `Hit`'s fourteen columns; `text` is **never** a table cell, because a
multi-line document paragraph inside an RFC 4180 quoted field is both unreadable and larger than the
fence it replaces. It travels in the evidence section and the row carries its `cite`.

Envelope, taken from MUNCH with the vendor sigil changed:

```text
#owrows/1 action=ow_query enc=hit1

@1=handbook:d7#
@2=contracts/2024/

corpus=handbook gen=41 k=20 returned=9 confidence=0.217 verdict=low_confidence
__tables=h:hits:cite|page|score|ident|quote|trust|bx:str|int|float|str|str|str|bool

h,@1412,14,0.0164,none,verbatim,extracted,T
h,@1418,14,0.0161,none,reflowed,inferred,F
```

Rules, all of which are MUNCH's and all of which are load-bearing:

- **Deterministic** — the same `Response` encodes to the same bytes. Column order is fixed per
  encoder id; the legend is built by descending prefix frequency with ties broken lexicographically.
- **Round-trippable** — a decoder reconstructs top-level keys, column order and per-column types for
  every tier-1 encoder. `__tables` carries `<tag>:<key>:<col>|<col>:<type>|<type>`; `__stypes`
  carries the scalar type map. Decode coercion is MUNCH's: `int()`/`float()` leave the string
  unchanged on `ValueError`, `bool` is `T → True` and anything else `False`, and an empty field
  always decodes to `None`.
- **Line-oriented** — sections separated by a single blank line, so `splitlines()` tokenises it. The
  first non-header section whose first line matches `^[a-z],` is a table section; any other is the
  scalars section, or the legend if it begins with `@`.
- **Fail-open** — any client that cannot decode asks for `encoding = "json"` and gets JSON. A
  decoder must reject a payload whose first line does not start with `#owrows/`, and **must ignore
  unknown scalar keys**, so additive changes keep version `1` and breaking ones bump `#owrows/2`.
- **Size-justified** — `encoding = "auto"` encodes, measures, and emits the compact form only if it
  saves ≥ 15%; `[retrieval] encoding_threshold` overrides. Small payloads fall back to JSON
  automatically.
- **Legend handles are dense and 1-based**; `@N<rest>` expands by prefix substitution; an unquoted
  literal runs to end of line; RFC 4180 quoting inside table rows; `T`/`F` are the booleans.

**Where it is exposed, and where it is not.** The MCP front door returns an Answer: one content
block, no `outputSchema`, ≤ 24,000 characters. `owrows/1` therefore **never appears on the MCP
wire** — encoding a text document as a table would save nothing and cost the reader everything. It
is exposed on the SDK and CLI structured paths, where the consumer is a program:
`encoding = "auto" | "rows" | "json"` on the SDK call, defaulting to `"json"`, and the CLI's
structured render selects it. Wiring the surface is [interfaces](10-interfaces.md)'s; the encoder
registry, the envelope grammar and the threshold are this document's.

**The savings figure is jcodemunch's, not ours, until measured.** `ow bench encoding` runs the
golden query set through `hit1`, `prov1`, `nb1` and `gen1` and publishes a per-encoder ratio with
`n` and a confidence interval, with a committed floor in `eval/gates.toml`. Claiming 45.5% for
omniweave's shapes before that runs would be exactly the kind of borrowed number this plan refuses
(Open question F51).

## 8. Byte-exact retrieval

### 8.1 The cached-originals store and offset addressing

Byte-exactness is not a promise, it is a **re-verifiable property**, and the machinery is three
pieces:

1. **`part`** — named byte streams of the original container, hash-pinned, keyed `(doc_ord, path)`,
   with `store_ref` a `cas://ab/cd/<sha256>` reference. `store_ref IS NULL` means the bytes were not
   retained.
2. **`.omniweave/cas/`** — the content-addressed store those refs point into, with §3.11's four-step
   write protocol. Deleting it is legal; it costs the `verbatim` tier and is disclosed, never
   silently downgraded.
3. **`OriginSpan`** on every Block — a tagged union `bytes | nodepath | glyphs | pixels | none`,
   never zero-defaulted, nullable as a whole.

**The addressing convention, stated once because two of them coexist by design:**

| Span | Fields | Semantics | Slice |
|---|---|---|---|
| `TextSpan` | `ts_a`, `ts_b` | **half-open, in characters of `block.text`** | `text[ts_a:ts_b]` |
| `OriginSpan` | `os_a`, `os_b` | **offset and LENGTH**, in the unit `os_kind` names | `part[os_a:os_a+os_b]` |

The asymmetry is deliberate: a glyph run has no meaningful *end offset* in a byte stream, so the
`glyphs` branch needs a count, and a single convention would force either a fake end offset or a
per-kind special case at every call site. A semgrep rule rejects `part[os_a:os_b]` and
`text[ts_a:ts_a+ts_b]`, which are the two ways to get this wrong, and `os_b == 0` is a
`CHECK`-rejected value rather than a sentinel — an empty span is `os_kind = 'none'`.

A `mention` row's `ts_a`/`ts_b` come from **one** function, `ground(block_text, quote)`
([06](06-structure-extraction.md) §1.7), which recovers them in `block.text` coordinates through
`normalize_k`'s back-map. There is no CHECK constraint on the predicate — it needs `normalize_k` and
SQLite cannot call it — so 06's P-GROUND property test is the enforcement, and a `mention` written by
any other path is a bug with no database-level detector.

`quote = 'verbatim'` requires `part.store_ref IS NOT NULL` **and** one of exactly three
re-verifiable branches (INV-10). [document model](03-document-model.md) §7.2 is the home of these
three predicates; the table below reproduces them for the store's own re-verification and defines
nothing. All three normalise under `nfc()` — defined in
[structure extraction](06-structure-extraction.md) §1.7, `unicodedata.normalize("NFC", s)` and
nothing else — and **none** under `normalize_k`, which casefolds and would let a block reading
`"abc"` prove itself byte-exact against source bytes reading `"ABC"`:

| `os_kind` | The proof | Producer at release 1 |
|---|---|---|
| `bytes` | `nfc(part_bytes[os_a : os_a + os_b].decode(*os_codec.split("/", 1))) == block.text` — decode under the recorded `os_codec`, then NFC and nothing else | flat text, HTML, code, Markdown |
| `nodepath` | `nfc(node_text(part, os_path)) == block.text` | OOXML/ODF, once a driver emits a child-index path |
| `glyphs` | re-extracting glyphs `[os_a, os_a + os_b)` from `part` with the **recorded** `os_extractor` (e.g. `pdftext@0.6`) reproduces `block.text` under NFC | the PDF text layer |

`pixels` and `none` can **never** reach `verbatim`: there is nothing to re-read. A byte range is
right for flat text and wrong for containers — a byte offset into `word/document.xml` is destroyed
by any attribute reordering on re-serialisation, which is why the OOXML branch is a child-index path
(ppt-master's `SourceRefRecord.source_path: tuple[int, ...]`, `authoring_roundtrip.py:87-88`).

**The honest consequence at release 1**, stated because a user will hit it: the shipped office
parser declares `origin_span = "none"` — a measurement, not modesty; verified against the pinned
wheel's source, `_collections/anydoc/src/model/block.rs:5-38` defines `Block` as **eight** variants
(`Heading`, `Paragraph`, `List`, `Table`, `BlockQuote`, `CodeBlock`, `Rule`, `Math`) with no source
address of any kind — only `Asset` carries `origin_part` (`src/model/asset.rs:15`). The charter's D3
says "nine"; ADR-8 D8.1 counted the enum and the conclusion is unchanged. So **every DOCX/ODT/RTF/EPUB/CSV Block is `quote = normalized` and
`verbatim` is unreachable on the office path**, while the PDF path reaches `verbatim` through the
`glyphs` branch. `corpus_card.verbatim_fraction` discloses this **before any query runs**.

`[store] retain_parts` controls retention: `always | when_citable | never`. The shipped default is
`when_citable` — retain a `part` iff the producing driver declared `origin_span` in
`{exact, normalized}` for it. Retention roughly **doubles corpus storage**, which is F32: if the
achieved-exact fraction lands under ~20%, retention becomes opt-in per corpus and `never` becomes
the default, with `verbatim` disclosed as unreachable rather than quietly absent.

### 8.2 The rule for when reconstructed text may be returned instead

Reconstructed text is **always** returnable and **never** labelled exact. There is one predicate,
evaluated at one call site:

```python
def byte_exact(hit, doc, fmt) -> bool:
    return (hit.quote is Quote.VERBATIM
            and doc.achieved.origin_span == "exact"
            and "citation" not in doc.achieved.forfeits
            and SERIALIZER_CAPS[fmt])
```

Four properties, each of which was got wrong somewhere in the collection:

1. **It reads `doc.achieved`, never a driver card.** A card cannot know what a *particular* PDF
   permitted; `achieved` may be lower than `declared` and never higher.
2. **It is one call site**, proved in CI by re-reading `part.store_ref` and byte-comparing every
   block the renderer labelled exact. `Q-G6` gates `span_exact_rate` at **1.000** on a deterministic
   sample of n = 1,000 blocks — a hard gate, not a metric.
3. **It does not re-read the part on the hot path.** A read of `cas/` per hit would put filesystem
   latency inside the 250 ms query budget for a property that is already provable from stored
   fields. Re-verification on demand is `ow doc verify` and `ow open --verify`, which return a
   `QuoteVerdict` of `match | source_ahead | mismatch | source_unavailable`. **`source_ahead` must
   not read as corruption**: the source file is newer than the index and the slice still matches.
   Both sides decode with the **same codec and error policy** — decode symmetry is an invariant, not
   a convention, and `os_codec` records the policy per Block.
4. **A header claiming a tier is keyed on `min(quote)` over the rendered set** — the *weakest*
   member, because `Quote` is an ordered `IntEnum` with `SYNTHETIC = 0` and `VERBATIM = 4`. Under a
   declaration-ordered enum with `VERBATIM` first, `MIN()` returned the *best* tier present and one
   verbatim block made a whole segment pass the byte-exactness gate for its reflowed and synthetic
   members. A block worse than the header's tier is marked inline.

The three branches of `ow open --verify` and what each means for the caller:

| Outcome | Condition | Caller's action |
|---|---|---|
| `match` | the re-read slice equals `block.text` under the recorded codec and normaliser | quote it verbatim |
| `source_ahead` | the slice matches but the source file's `sha256`/`mtime_ns` differs from `part` | quote it, and say the source has moved on. **Not corruption**; jcodemunch #400 is the decode-symmetry bug that made this look like one |
| `mismatch` | the slice differs | refuse the verbatim claim, emit `Diag(OW_INTEGRITY_UNCHECKED)`, degrade the Verdict |
| `source_unavailable` | `store_ref IS NULL`, or the CAS blob is gone | the block is still returnable as `normalized`; `byte_exact` was already false, because it requires `store_ref IS NOT NULL` |

**Defanging does not create an exception.** Chat-template sentinels matched by form
(`<\|[A-Za-z0-9_.\-]{1,64}\|>`) are defanged **on a copy**; a defanged block is emitted as
`normalized`, marked, and counted, so the `verbatim` invariant stays absolute rather than being
traded away. `ow open --raw` (CLI and SDK only, never MCP) is the escape hatch.

## 9. Vectors

### 9.1 Optional, and off by default

**`[retrieval] vectors = "off"` is the shipped default, permanently, and it is not deferred.** Most
first runs get four Channels and a Verdict that says `semantic: off`. That is a visible product
limitation and the correct one; the alternatives are a five-second query on a cold model load, or
numpy inside `omniweave-core`, which INV-2 forbids.

Embeddings are an `embed/1` **Driver** — they have a model identity that enters index metadata, a
`(dim, metric, normalization)` contract the store must match, a cost class and a licence. The ANN
index is a **Backend**. Those are two different extension boundaries and conflating them is what
makes an embedding model unswappable.

One claim that was checked and does **not** survive: "graphify measured 0.497 recall@10 on LOCOMO at
zero embedding cost." `graphify/BENCHMARKS.md`'s own fairness rules read *"One shared local embedder
where the system allows it: BGE-m3"*, and its LOCOMO table lists the primary `graph-expand`
configuration at **~$1.40 ingest cost**, against `$0 (shared index)` for the dense-RAG and BM25
baselines. The `vectors = "off"` default survives on its own merits; that particular evidence for it
does not, and it is recorded here so nobody re-imports it.

### 9.2 The embedding model contract

The nine identity fields of `embed_space` (§3.7) are the contract. Three of them are the ones
systems usually omit and then cannot debug:

- **`model_rev` is an exact sha.** `''` or `'main'` is refused at card-validation time (G8's
  `revision="main"` grep). docling's own layout-model `revision` defaults to `"main"`, which is
  precisely the un-pinnable case.
- **`doc_prompt_digest` and `query_prompt_digest`** — asymmetric-prompt models (`"query: "` /
  `"passage: "`) produce silently mismatched spaces if the prompt is applied at build and not at
  query, or twice. The prompt is applied **once, client side**, and its digest is part of identity.
- **`pooling` and `normalize`** — mean-pooled and CLS-pooled vectors of the same model are different
  spaces.

`segment.content_digest` is the embedding key, so **identical text is embedded once corpus-wide**.
Its inputs are the segmenter identity, `heading_path` and the member blocks' `content_digest`s in
`ord` order; `segment_id`, `block_id`, `addr`, `cite`, `page`, geometry, `producer_id`, `trust` and
`origin_operator` are deliberately **not** inputs. Every input is a stored field, so a
`segment_recipe` bump is a **re-digest pass**, never a re-parse.

This dedup is a covert channel in a shared store: two tenants observe each other's embeddings as a
timing difference. **v1 is store-per-tenant** (F27); row-level tenancy is not designed and no plan
document may assume it.

### 9.3 Re-embedding on model change

`model_key` changes ⇒ a new `space_id` ⇒ the old vectors are **not deleted and not read**.

```text
1. `ow index vectors --space <model_key>` inserts an `embed_space` row (refusing a duplicate
   `model_key`), resolves `storage = "auto"` by §3.7's rule, and sets
   `index_state.default_space_id` only on success.
2. `vpending` is filled by one INSERT-SELECT: every live segment digest with no `vseg` entry for
   the new `model_key`. It is MATERIALISED, so the build loop is a scan with a resumable cursor
   and not an anti-join re-evaluated per batch.
3. The build drains `vpending` in `VSEG_SIZE = 4096` batches through the `embed` cache layer, so a
   rebuild after `rm index.vec.owstore` costs CPU, not a re-bill.
4. `vec_manifest` is rewritten last. A `vec_manifest.corpus_id` that disagrees with
   `main.index_state.corpus_id` means the sidecar is **IGNORED, not read**.
5. A search whose configured embed Driver does not reproduce `model_key` is refused with
   `OW-S-020`, printing both nine-field tuples. Absence gate 13 (`space_mismatch`) reads the same
   comparison, so a mismatch is `degraded`, never a confident zero.
6. The old space's rows are swept by `VectorBackend.sweep(live)` at the next maintenance window, or
   by deleting the sidecar. Nothing on the read path depends on the sweep having happened.
```

Step 3's interruption behaviour is the one that matters operationally: because `vpending` is a
materialised set and the drain deletes each batch's rows in the same transaction that writes its
`vseg` row, a `kill -9` mid-build leaves a consistent partial index. The sidecar is usable — the
semantic Channel simply misses the un-embedded segments — but `vec_manifest.rows` disagrees with
`stat.live_segments`, which is what `ow doctor` reports and what `Verdict.space` discloses as
`coverage=partial`. It is never a silent partial recall.

A `digest_recipe` bump invalidates every content-addressed cache in the fleet and is budgeted at
**at most annually**; it is serviced by a re-digest pass because every digest input is a stored
field.

### 9.4 Selective recomputation, and exactly when it is the wrong trade

LEANN's result is real and worth stating precisely: a pruned graph plus recomputation of only
the nodes on the search path gives **60M chunks in 6 GB instead of 201 GB — 97% less storage, no
accuracy loss**, improving with size (91% at 2.1M, 95% at 38k, 97% at 60M). Derived: the pruned CSR
graph costs **~100 B/node** against ~3.35 KB/chunk stored, consistent with `--graph-degree 32`
(32 × 4 B = 128 B).

**`mode = "recompute"` does not ship as a first-party mode at v1.**

| Objection | The number |
|---|---|
| It is a second correctness surface | recall depends on graph pruning *and* on the recomputation path agreeing with the build path — two places to be wrong, one of which only fails at query time |
| Query p99 becomes a function of a model load | 64-200 chunk embeddings per query at `complexity=64, beam_width=1`; ~100-200 ms/query on GPU **after the daemon is warm**, seconds on CPU |
| It requires a resident daemon | one embedding server per (model, mode, provider options, passages file, metric) signature, TTL 900 s, a port registry in `~/.leann/servers`, and a two-layer lock for the check-then-start race. The charter's §6.11 bans a long-lived local IPC daemon for embedding |
| The incremental story does not hold | HNSW has "limited incremental support" — LEANN's own MCP tool flips its default to `ivf` for this reason. A pruned-graph index that cannot be incrementally updated forces a full rebuild per ingest, which is the dominant cost at scale |
| Zero implementations at v1 | an abstraction with no user |

**Where it belongs is behind the `VectorBackend` Protocol**, which is exactly wide enough to
hold it:
`search()` receives `q_full` and `candidates` and returns `(digest, score)` pairs — a recomputing
backend satisfies that signature without any core change, and obligation (3) forces it to declare
its own ceiling and refuse above it.

**Right trade:** a cold, large, single-user personal corpus where storage binds and latency does
not — 10M+ segments, a handful of queries per hour, a warm GPU. **Wrong trade, and it is omniweave's
default case:** a hot corpus, a multi-tenant or CI service, a p99 budget, no GPU, or any deployment
where `import omniweave_core` must stay under 80 ms and no daemon may be resident. The decisive
number is §4.3's: at 1M blocks the whole `sig_only` sidecar is **3.7 MB**, so recomputation trades
3.7 MB for a model server. **The storage objection it answers does not exist at the scale the
default configuration serves**; it becomes real above ~10M segments, which is exactly where a
third-party `VectorBackend` takes over anyway.

Two further things omniweave takes from LEANN and one it refuses:

- **Taken:** the offset map as a **table, not a pickle**. LEANN's `dict[str, int]` at 10M entries is
  1-1.5 GB of interpreter objects loaded per shard at searcher construction; sharding bounds it and
  does not eliminate it. omniweave's equivalent is `part` plus `block.os_a`/`os_b` in the same
  SQLite store, with a covering index.
- **Taken:** the metadata contract — everything needed to reproduce a query, recorded in the index.
  `embed_space` is that contract with a `UNIQUE` constraint on it.
- **Refused:** `pickle` for the sync snapshot and the offset map (an arbitrary-code-execution
  surface and a brittle format), and full-corpus re-hash on every freshness check.

## 10. Concurrency and durability

### 10.1 The write model

**One writer per store, one thread per connection, one transaction per unit** (INV-17).

- `sqlite3.connect` appears in exactly one module (ST1), enforced by G24 *and* a monkeypatch test.
- The **store thread** is the only holder of a `Connection` in a process. Every write reaches it as
  a transaction closure on a bounded queue. This upgrades the module rule into a module-**and-thread**
  rule and deletes the cross-thread-connection failure class outright.
- Cross-process exclusion is a scoped lock named `store.write`, whose holder identity is
  `(host, pid, process_create_time)` — the third component is what stops a recycled pid from
  looking like a live holder.
- Wait times are passed **per call**, not configured globally: `INTERACTIVE_WAIT_MS = 2_000`,
  `BATCH_WAIT_MS = 60_000`. A lock timeout is a UX decision: codegraph's 120 s wait *"presented as a
  frozen, hung agent"* and was cut to 5 s.
- **Enqueue before attempting the lock.** An interactive `ow add` writes its `work` row in a short
  transaction and returns; it does not sit for 60 s behind a batch writer.

`Store.complete()` is the only mutation entry point on the queue boundary, and one unit's derived
rows, its `work` transition, its `dep` rows, its reservation commit and its spend row commit
**together or not at all**.

### 10.2 Durability

`synchronous = NORMAL` for the general case. **ST14: a `BILLED_API` commit is durable** —
`synchronous = FULL` is set *before* `BEGIN` for that transaction, and a test asserts the pragma
value at commit time for a billed operator and `NORMAL` for a free one. One fsync against a VLM call
is free; re-billing 116,400 pages because a laptop lid closed is not.

### 10.3 Reads: the `connect_readonly` ladder

```text
a `-wal` sidecar exists      → mode=ro
no `-wal` sidecar            → mode=ro&immutable=1
```

The ladder exists because a plain read-write open **creates** the WAL sidecars and moves the very
mtime the freshness check reads. A read that perturbs freshness is a read that makes gate 6
(`source_edited_unindexed`) fire on its own observation. `immutable=1` is correct only when there is
no WAL, because it tells SQLite the file cannot change and therefore that no WAL need be consulted —
using it while a `-wal` exists returns pre-WAL data, which is a silent stale read rather than an
error.

### 10.4 Snapshot isolation, and a query running during a re-index commit

**One `BEGIN DEFERRED` for the whole query** — every Channel, hydration and the coverage scan
(ST2). Without it, a 6-12 statement retrieval sees up to twelve snapshots and fusion mixes
generations. The test is explicit: a full re-index is committed between Channel 1 and Channel 5 and
the results must be identical.

```python
@dataclass(frozen=True, slots=True)
class Snapshot:
    token: object                    # BACKEND-PRIVATE AND OPAQUE
    generation: int; corpus_id: str; schema: int; vec_attached: bool; opened_ns: int
```

A `BEGIN DEFERRED` does not actually acquire the read snapshot until the first statement, so
`snapshot()` issues `BEGIN DEFERRED` followed immediately by `SELECT v FROM index_state WHERE
k='generation'` — one row, which both opens the snapshot and populates `Snapshot.generation` from
inside it. Without that first read, two Channels could still straddle a commit.

WAL gives the reader a consistent view from that first read without blocking the writer, so a
re-index commit during a query is **invisible to that query** — not "mostly invisible": the writer
appends WAL frames the reader's snapshot does not include. Three consequences:

1. **The reader must not hold the snapshot open indefinitely.** A held read transaction **pins the
   WAL**, which is the precise condition the futility latch exists for. `MAX_SNAPSHOT_MS = 5_000` is
   the ceiling in `limits.py`; `[retrieval] snapshot_ms` clamps *below* it, default 2,000. Exceeding
   it interrupts and aborts with `OW-S-010` and `verdict = degraded`. **The reader's deadline is a
   WAL-valve safety parameter, not a UX parameter** — which is also why the query embedding runs in
   phase 2, outside the snapshot (§4.4). D687: one `interrupt()` is not sticky -- fired during the snapshot's own setup reads or between two statements it is discarded, and the next statement ran unbounded -- so an expired snapshot interrupts again every `INTERRUPT_REPEAT_MS = 10` until it closes, refuses before the body when setup spent the budget, and never reads an interrupt as an absent `index_state` table.
2. **`vec` is outside the snapshot.** No transaction spans `main` and `vec` (ST3), so a vector
   written during the query might be seen. It cannot be *wrong*, because the only exit from `vec` is
   an inner join to a live `segment` row inside the main snapshot (ST4).
3. **Gate 3 compares generations across the snapshot boundary.** `plan()` runs before
   `snapshot()`; the Answer is rendered after it closes. `store_changed_mid_query` compares
   `index_state.generation` read at plan time with the value read after the snapshot closes. For a
   single-writer `.owstore` one generation counter answers both "the index changed" and "the corpus
   moved during the scan".

### 10.5 The WAL valve

Ported whole from codegraph, with all eight properties and its verified constants:

```python
DEFAULT_WAL_VALVE_MB   = 256    # soft: growth past this → off-thread PASSIVE checkpoint
HARD_CAP_MULTIPLIER    = 2      # hard: growth past 2× soft → PAUSE the writer
FILE_CAP_MULTIPLIER    = 4      # file: WAL file past 4× soft → pause AND truncate
MAX_PAUSED_BACKFILL_PASSES = 20
CHECK_INTERVAL_MS      = 2000
# [store] wal_valve_mb = 0  ⇒  clamp(db_bytes / 4, 256 MB, 2 GB)
# [store] wal_heal_mb  = 64 ⇒  heal an oversized WAL at every open
```

Why it exists, in numbers, all measured in codegraph:

| Observation | Value |
|---|---|
| Share of all disk I/O caused by default autocheckpointing during a bulk index | **~95%** |
| Bulk index on HDD-class storage (150 random IOPS): default vs deferred | **19+ min → 45 s** |
| WAL:DB ratio under unbounded deferral | **5.9 GB WAL against a ~340 MB DB** |
| First post-parse read against a multi-GB WAL | **>60 s main-thread block** → watchdog SIGKILL |
| Worst observed WAL under a pinned reader, **with the valve running** | **22 GB, then exit 137** |
| Worst leaked WAL across repeatedly-killed sessions, no heal-on-open | **25.6 GB** |
| A 7-file incremental sync on a large index, HDD, autocheckpoint on | **2 minutes at 0-2% CPU** |

The four subtleties, each a rule and not a detail:

1. **The trigger cannot be WAL file size.** A WAL file's size never shrinks; after a full backfill
   the writer's next commit restarts the WAL from the top and recycles frames inside the same file,
   so a size-triggered valve fires forever once the file passes its threshold — measured at ~9 min
   per 160 files. The valve tracks `wal_baseline_bytes`, refreshed whenever a checkpoint reports
   `log == checkpointed`, and triggers on **growth beyond that baseline**. *Any governor built on a
   monotone-non-decreasing observable needs this transform*; omniweave has the same shape in three
   more places — index size vs live blocks, CAS size vs live entries, `work` rows vs pending.
2. **One in-flight pass is not enough on a saturated disk.** Every concurrent PASSIVE pass is stale
   by the time it finishes; with the writer parked the next pass covers everything and the WAL wraps
   on the following commit. **The pause is the disk's honest catch-up cost**, and it is the correct
   terminal mode rather than a failure.
3. **TRUNCATE only at a parked barrier.** A truncate checkpoint against an *active* writer wins the
   lock race and then blocks that writer for its whole backfill — past the writer's 5 s
   `busy_timeout`, failing the index with "database is locked". The chop happens only where the
   writer is *provably* parked, awaiting the promise the valve returns.
4. **The futility latch.** Two give-ups ⇒ 60 s cooldown ⇒ degrade to un-valved, with an armed log
   line and a heartbeat (ST16, I9). It exists because **the mitigation made things strictly worse
   than no mitigation**: a worker thread and a fresh connection per pass at every boundary turned a
   pinned resolution phase from slow into OOM-killed, at an envelope the pre-valve build survived.

The **phase-boundary fold** is the other half: `foldNow()` backfills the whole WAL off-thread,
awaited, between bulk phases — after parsing, before the first resolution read.

### 10.6 Bulk windows

A **bulk window** drops only **non-UNIQUE secondary** indexes and the FTS triggers for a bulk load.
The measured payoff is codegraph's: dropping four non-unique edge indexes took a 224k-edge
`INSERT OR IGNORE` stream from **2.8 s to 1.1 s**, with ~0.3 s to re-create — one B-tree paid
instead of five. The rules:

- Index DDL is read from `schema/` **by name**, with a hard raise on a miss. Reconstructing a
  dropped index from memory is how an index comes back subtly different.
- **The UNIQUE identity index is never dropped.** Dropping it makes duplicate insertion possible
  during exactly the window nobody is watching.
- `index_state.bulk_window` is written **before the first DDL**, and `fts_state = 'building'` with
  it. An open marker at store open **refuses to serve** (ST13, `OW-S-031`) and names
  `ow store repair`; a SIGKILL test asserts it.
- The loop yields at the top of each body so the event loop and the watchdog heartbeat keep turning.
- `[store] bulk_windows = true` is the default; `wal.bulk_index_peak_bytes = 2 GiB ± 512 MiB` is a
  nightly **absolute** budget, not a percentage, because the failure it guards against is 5.9 GB
  then 22 GB.

### 10.7 Multi-process access and the file watcher

| Pair | Interaction | Outcome |
|---|---|---|
| reader ∥ reader | WAL, independent `mode=ro` connections | no contention |
| reader ∥ writer | WAL | no contention; the reader sees its snapshot. The **only** coupling is the pinned WAL (§10.5) |
| writer ∥ writer | `store.write` scoped lock | the loser waits its passed timeout, then reports **store busy** (exit 7) naming host, pid and age — never a silent retry loop |
| query ∥ telemetry | separate files | a `mode=ro` query process physically cannot write the index; `retrieval_event` goes to `events.owstore` through a bounded drop-oldest queue |
| query ∥ query, on the events file | `events.owstore` write lock, `busy_timeout = 200` | contention is real (N query processes, one events file) and its resolution is to **drop the batch** and count it. §2.1's `EVENT_PRAGMAS` exist for this row |
| watcher ∥ interactive `ow add` | both writers | the watcher holds `store.write` with `BATCH_WAIT_MS`; `ow add` **enqueues first** and takes the lock with `INTERACTIVE_WAIT_MS = 2_000`. The queue row is durable, so losing the race costs latency, not work |
| watcher ∥ query | writer ∥ reader | none, except that a query holding a snapshot for 2 s while the watcher commits a large batch pins that much WAL — bounded by `snapshot_ms`, and that is why `snapshot_ms` is clamped below `MAX_SNAPSHOT_MS` |

A watcher may **never auto-run billed work**: `[drivers.cost] auto_refresh_classes = ["free"]`. A
file-change storm therefore cannot spend money, and the worst case is queue depth, which
`queue_high_water = 50_000` / `queue_low_water = 25_000` bounds with hysteresis rather than a
barrier.

**Lock contention under a watcher, in the shape it actually takes.** The watcher wakes on every
filesystem event, so the pathological case is hundreds of short lock holds, not one long one. Three
mechanisms bound it and all three are needed: the debounce window coalesces events before a batch is
formed ([the runtime](08-runtime.md) owns its value); the batch takes `store.write` **once** per
batch, not once per file; and an interactive writer that loses the race has already durably enqueued
its work, so the cost is 2 s of `INTERACTIVE_WAIT_MS` and a queued row, never a lost command.
codegraph's measured counter-example: a 7-file incremental sync taking **2 minutes at 0-2% CPU**
because each file's commit paid its own autocheckpoint.

## 11. Incremental update semantics at the store level

### 11.1 What a commit is

| Scope | Transaction | Boundary |
|---|---|---|
| one page of a parse | `DocSink.end_page()` | commits `page` + its `block` rows + `mark`/`cell`/`rel`/`asset` links + `diag` rows |
| one generation advance | one transaction | sets `doc.gen`, sets the previous generation's blocks `state = 1` (so the FTS triggers remove them **in the same transaction**), writes `block_history` rows, bumps `index_state.generation` |
| one unit of derived work | one transaction | derived rows + the `work` transition + `dep` rows + the reservation commit + the spend row |
| a document-granularity parse | staged | writes at `staged_gen = doc.gen + 1`; readers resolve at the committed `doc.gen`; the bump is one `UPDATE` inside the completing transaction; abandoned generations are swept at startup through `ON DELETE CASCADE` |

The staged generation closes the torn-parse hole: L2 commits one transaction per page and a driver
may declare `granularity = "document"`, so a crash after page 40 of 200 leaves 40 committed pages
under a `pending` work row, which on resume duplicates or trips `block_addr`'s UNIQUE index. One
integer column fixes it, and a kill-mid-document test asserts the previous generation still resolves
while the staged one is swept. The sweep is the one place a cascade is allowed to remove `block`
rows — and it therefore runs `INSERT INTO block_fts(block_fts) VALUES('rebuild')` afterwards unless
it deleted zero rows, because §3.3's rule admits no exception.

**Group commit** is the single stated exception to one-transaction-per-unit: at
`store_group_commit_ms = 20`, **only** work-row transitions that write **zero derived rows** are
batched. It is safe because a crash means re-checking the cache and reaching the same outcome.

### 11.2 Generation counters, and there are three kinds

| Counter | Scope | Meaning |
|---|---|---|
| `gen` | per `doc_key` | **the parse generation, and nothing else.** Bare `gen` means this everywhere |
| `generation` | per store, in `index_state` | the monotonic **run** counter; `Snapshot.generation` carries it; gate 3 compares it |
| `staged_gen`, `artifact_gen`, `card_gen`, `at_gen`, `retired_gen`, `built_gen`, `last_seen_gen` | various | every other generation counter carries a qualifying prefix, so a reader can never mistake one for the parse generation |

The previous parse generation is **retained** until the next successful parse, so yesterday's
citation still resolves and reports `superseded_by`. `rebind()` decides identity across generations
by three rules — equal `content_digest` under the same parent carries the `block_id` **and the
`cite`**; equal `addr` and `kind` with a changed digest carries both and increments `revision`;
neither mints a new `block_id` and a fresh `cite` `n` from `doc.next_cite_n`. **Carrying the cite is
the point of the pass**: re-minting on re-parse would re-point every citation already shipped in
someone's document. Below `threshold` the new generation is **quarantined, not committed**, and the
override is named per check (`--allow-unexplained-rebind`), never one `--force`.

### 11.3 How a reader knows it read a consistent view

Five facts, all carried on the response, all recorded in `retrieval_event`:

1. **`Snapshot.generation`** captured by the first statement inside `BEGIN DEFERRED` (§10.4),
   surfaced as `Verdict.snapshot_gen`.
2. **`Snapshot.schema`** and **`Snapshot.corpus_id`**, asserted against `index_state` at open under
   §3.1's compatibility table. A major above the reader's is **refused**, naming the version and the
   upgrade command; silent misreading is the failure an operator cannot detect, and there is no
   `--force`.
3. **`Snapshot.vec_attached`** — whether the sidecar was present *and* its `corpus_id` matched. A
   mismatch means the sidecar is ignored, not read, and gate 13 fires.
4. **Gate 3** — `index_state.generation` compared across the snapshot boundary (§10.4).
5. **`Verdict.freshness`** ∈ `fresh | refreshing | stale | unknown | not_tracked`, from the `unit`
   roster's `stat_fresh` predicate:
   `size == st_size AND mtime_ns == st_mtime_ns AND st_mtime_ns + 2e9 <= indexed_at_ns`. The 2 s
   grace is `MTIME_GRANULARITY_NS` and it is what makes "racily clean" detectable. `not_tracked` is
   **deliberately not a gate**: it is disclosed, not refused.

### 11.4 Invalidation is one query, never a sweep

```sql
SELECT DISTINCT d.dependent_id FROM dep d JOIN changed c
  ON c.kind = d.kind AND c.key = d.key WHERE d.digest <> c.new_digest;   -- index: dep_reverse
```

`dep` rows are of closed kind `unit | part | name | cohort | policy | service_model`;
`MAX_DEPS_PER_UNIT = 256`, and past it the operator **must** declare a cohort dep — coarser, always
safe, over-invalidating on purpose. The `name` kind keys on `'(akind):(name_norm)'` from `anchor`,
whose `scope` column resolves the document-versus-corpus ambiguity.

The **converge pass** (`op.converge`) is the run-final step that computes the `anchor_delta`, applies
the `dep` reverse index, re-derives `stat`, runs the per-unit attribution guard and enqueues what
changed. **It must ship before the watcher**, because it is the invariant a watcher breaks silently:
skipping the equivalent pass measured **4.3% of distinct edges wrong, in both directions, silently**
(codegraph CG-33). Added names retry the unresolved set on `ref_site_name`; removed names **unbind**
every `edge` and `block_link` carrying that `bound_by` — and only a row carrying `bound_by` may be
unbound, because we never delete what we cannot restore.

Convergence is gated, not asserted: **G19** builds a 300-document fixture through 40 scripted
mutations and diffs the `.owdoc` **exports** against a full rebuild into a second store. It diffs
exports rather than tables because an archive contains no `block_id`, so the allocation-order
normalisation that could hide a bug is not needed at all. *(Build note, D880: G19 still indexes through `tools/p2_stub_parse.py`, which takes `doc_key` as an argument and keys it by uri. Through the product's `ow add` it could not pass. A file edited in place and added again hashes to a new `doc_key`, so `begin_doc` opens a second `doc` row at `gen = 1`, and the old version's blocks stay live under the same uri. A full rebuild holds one. This is ledger D40, recorded at P2 as needing a ruling on which identity survives an edit, and still unruled. `packages/omniweave/tests/conform/test_add_edit_identity.py` pins both halves through real `ow add` children: an identical re-add is one document, and an edit is two.)* *(Correction, D882: D880 was wrong that the old version stays live. D645 retires it: `discover.REPLACED_SCAN_SQL` names a document whose file now holds other bytes, its blocks leave `state = 0`, it carries `x.ow.retired`, and `block_history` records each block. D880 had read every block regardless of `state`. What D40 still leaves open is cite durability: the edit is a new `doc_ord`, so no cite carries, where 03's worked example re-parses the same `doc_ord` at `gen = 2`. Whether G19 holds through `ow add` is unmeasured, not impossible. The test now pins all three facts.)* *(Build note, D905: D40 is resolved by a user ruling of 2026-10-19 -- `doc_key` is the file's place in its corpus, so an edit through `ow add` is the same `doc_ord` at its next generation and an unchanged paragraph keeps its cite (`test_add_edit_identity.py`). `retire_replaced` now retires only a document whose file's new bytes failed to parse. 06:2299's REMOVED arm (`converge.unbind_removed_names`) and the retirement of a defined term the head no longer defines (`converge.retire_undefined_entities`) keep GR8's incremental store equal to a full rebuild through edits. G19 still indexes through its own harness; moving it to `ow add` is the next cell.)*

## 12. Scale-out

### 12.1 `block_id` and the sharding key

```text
block_id := (minting_shard_ord << 48) | sequence          # 16 bits / 48 bits, 63-bit total
```

- **single store**: `shard_ord = 0`, so ids are literally 1, 2, 3 — zero bytes, human-readable.
- **fabric**: 65,536 shards × 2.81e14 blocks each.
- `CHECK ((block_id >> 48) = <shard_ord>)` on every shard's `block` table, **with the ordinal
  interpolated as a literal by the migration at CREATE time** (`= 0` at shard 0) and **re-asserted
  at open** against `index_state.shard_ord`. A bind parameter is prohibited in a CHECK body
  (verified on 3.45.1), which is why it is a generated literal plus an open-time assertion.
- **placement**: `jump_consistent_hash(int.from_bytes(doc_key[:8], 'big'), n_shards)` — about twelve
  lines.
- **Minting is not placement.** A document may migrate; its `block_id`s keep their prefix forever
  (ST20). There are **no cross-shard foreign keys**, and a document never spans a shard.
- `GlobalRef = (corpus_id: str, block_id: int)` is the **only** reference type that may cross a store
  boundary. `corpus_id` is TEXT everywhere — the corpus *name*, matching `[a-z0-9][a-z0-9_-]{0,31}`.

The asymmetry decides it: reserving 16 bits costs **zero bytes at shard 0**, while adding the prefix
later rewrites every foreign key in every deployed store.

### 12.2 The four tiers

| Tier | Shape | Envelope | What changes |
|---|---|---|---|
| **T1** | one store | ≤ ~1M blocks, `vectors = "off"` | nothing; this is the default |
| **T2** | one store + the full WAL valve + an ANN `VectorBackend` | ~50M blocks (**~5M** if F1 resolves at ~300 blocks/page) | one config key and one installed backend |
| **T3** | Postgres behind the same four Protocols | beyond one file's practical envelope | `[store] backend = "postgres"`. **No operator change** — that is the entire point of making the store the distribution boundary |
| **T4** | a fabric of shards | beyond one server | federation by **rank** fusion |

### 12.3 What federation looks like

A federated query is N per-shard `retrieve()` calls issued in parallel, each producing its own
Channel set, its own fusion and its own `Verdict`, rank-merged at the surface inside
`federate_ms = 40` (§4.4). It discloses `fusion_kind = "rank_merge"` and `shards_contributed`.

**Two BM25 indexes with different corpus statistics produce incomparable scores.** The bias toward
small shards is **disclosed**, never fixed by a global `term_df` table nobody can keep consistent —
a distributed statistic whose staleness biases ranking silently and whose repair is a full scan buys
the appearance of exactness and nothing else.

The rank-merge is deliberately the *simplest* thing that is honest: interleave by per-shard rank,
break ties on `(corpus_id, block_id)`, and recompute `confidence` against the **minimum** per-shard
ceiling, because a merged answer is no stronger than the weakest evidence base that contributed to
it. Absence gate 14 (`shard_unreachable`) fires when any shard in scope did not answer inside
`federate_ms`. Gate 4 (`coverage_incomplete`) needs a **global** discovered-versus-indexed count and
is F35's open question: if it does not hold at federation scale, coverage becomes per-shard and the
Verdict reports `coverage: unknown` naming the shard, rather than a global count no shard can
compute.

### 12.4 What breaks first, in order

1. **`VEC_BRUTE_MAX = 250_000` segments** (~7.5M blocks) — the stdlib vector backend refuses, and
   degrades against its own budget above ~197,000 (§3.9). First thing to hit, and it hits with a
   named refusal rather than a slow query.
2. **`PREFILTER_MAX = 200_000` blocks** in the narrowed set — narrowing stops being exact and
   becomes an over-fetch clamp. Not a failure; a disclosed mode change, with `filter_starved`
   catching the case where it under-delivers.
3. **FTS5 segment count**, not row count. An index written incrementally for months without §2.2's
   `'merge'` step accumulates segments and the lexical Channel's p50 climbs until it breaches its
   50 ms budget — the one degradation in this list that is caused by *not running maintenance*
   rather than by size.
4. **The lexical Channel's 50 ms budget** on a merged index, somewhere between 10M and 30M blocks
   depending on term selectivity. It reports `UNAVAILABLE(timeout)` and forces `degraded` —
   visible, not silent.
5. **WAL amplification during a bulk re-index.** The cost scales with the **existing** database
   size, not the change size, so small syncs on big indexes hurt most. This is what the valve's
   proportional threshold exists for, and it is the first thing that makes a *correct* system feel
   broken.
6. **One writer.** A single `store.write` lock caps ingest throughput at one process. `subproc`
   Driver hosts parallelise the *work*; the commit is serialised by design.
7. **Backup and `VACUUM`** on a multi-tens-of-GB file. `VACUUM INTO` needs free space equal to the
   final file, which at 66 GB is a provisioning fact and not a runtime one.

### 12.5 The honest statement

**The v1 design serves a single `.owstore` well up to ~10M blocks — roughly 110,000 pages, or a
5,000-page legal matter twenty times over — with `vectors = "off"` or an ANN Backend installed.**
Between 10M and 50M blocks it works with the valve, an ANN Backend and an operator who understands
the bulk-window mechanics. Above that, T3 or T4, and the plan says so rather than implying the file
scales forever. Every number in that sentence carries F1's envelope, and **F1 is two variables that
move different quantities.** `blocks/page` moves the **page equivalence only**: at ~300 blocks/page
the same ~10M-block ceiling is ~33,000 pages rather than ~110,000. `bytes/block` moves storage, peak
RSS and `VEC_BRUTE_MAX`'s block equivalence, which is derived at 140 B/block. **Neither moves the
10M-50M block ceiling itself**, because that ceiling is denominated in blocks and set by the lexical
Channel's 50 ms budget on a merged index (§12.4 item 4). `store.bytes_per_block` is the nightly
ratchet that tells us before a user does.

## 13. Portability

### 13.1 An index as a movable artefact

The `.owstore` is a single file. Copying it to another machine works, and four things make that
true rather than merely usually true:

- **`block_id` carries its minting shard forever**, so ids do not collide after a move.
- **`corpus_id` is a name, not a path.** `vec_manifest.corpus_id ≠ index_state.corpus_id` means the
  sidecar is ignored, not read.
- **The two sidecars are derived and deletable.** Move `index.owstore` alone and the vectors rebuild
  from the `embed` cache layer; the query ledger is per-user and does not travel.
- **The on-disk format is byte-identical across architectures.** SQLite's file format is
  endian-neutral, and the two places omniweave writes raw binary declare their own byte order:
  `vfull.v` is `dim × 4` B **f32 little-endian**, and `vseg.sigs` is a bit string with no
  multi-byte interpretation at all. `page_size = 8192` travels with the file.

Three portability hazards that are *not* automatic, with their rules:

| Hazard | Rule |
|---|---|
| the destination has an older SQLite | refuse at open below `MIN_SQLITE = (3, 42, 0)`, naming the feature (STRICT tables, `unixepoch('subsec')`) and `pip install omniweave-core[sqlite]` |
| the destination has a **different Unicode version** | `normalize_key` and `normalize_k` are NFKC/NFC fixpoints, so their output can change for rare codepoints between CPython builds. `index_state.unicode_version` records `unicodedata.unidata_version` at build. On a mismatch, the store still opens and serves, and emits `Diag(OW_UNICODE_DRIFT)` (`OW-S-033`) naming `ow index rebuild --derived`; `ref_site`, `anchor` and `block_sec` are all `[DER]` or re-derivable, so the remedy is a derived-layer rebuild and never a re-parse. This is disclosed rather than refused because the affected population is rare codepoints, and refusing a whole corpus over a possible name-normalisation difference is worse than reporting it |
| a case-insensitive or path-length-limited filesystem | CAS paths are lower-case hex and two levels deep, so the longest path is `cache_root` + 71 characters, inside Windows' 260-character `MAX_PATH` for any sane root; a case-insensitive filesystem is harmless because hex digests are already lower-case only |

`ow store backup` is a `VACUUM INTO` (atomic, no torn WAL). `ow store export --portable` writes
**one `.owdoc` per document** as a *transport* artefact — a plain ZIP that `unzip -l` and `jq` both
read with no external tool. An archive contains **no `block_id`**: every internal reference in it is
an `addr`, and import assigns fresh ids. That is what makes an archive portable between stores and
what makes the G19 export-diff sound. `import(export(store)) == store` over the fixture corpus is
gate **G6**, per INV-1.

### 13.2 Git, and the merge-driver question — decided

**The `.owstore` is never committed.** It is in the shipped `.gitignore`; a tracked store is
`OW-S-060` and `ow doctor` **fails**.

**A union merge driver for the index is rejected.** The evidence is direct: graphify registers a git
merge driver whose implementation, at `graphify/cli.py:2572`, is `_nx.compose(G_cur, G_oth)` — a
pure union that loads `_base_path` and never uses it. **A node deleted on one branch and untouched
on the other comes back.** Its caps, at `graphify/cli.py:2547-2548`, are
`_MERGE_MAX_BYTES = 50 MB` and `_MERGE_MAX_NODES = 100_000` — two to three orders of magnitude
below a real corpus, so on anything the size of a document index the driver aborts the merge
anyway. A merge strategy that is wrong at small scale and inoperative at large scale is not a
strategy.

**What is committed is `omniweave.index.lock`,** and a merge driver is registered **for that path
only**:

```text
# schema=1 scorer=1 segmenter=derive.segment.spine@3:9c1e space=bge-m3@a1b2c3/768/cosine/i8
<doc_key hex>  <gen>  <status>  <n_blocks>  <n_segments>  <root content_digest>  <uri>
```

Sorted by `doc_key`, byte-stable, **no timestamps**, ~200 B/document (~3 MB at 20,000 documents). D677: the header's `segmenter` is the store's own, never the caller's: `<driver_id>@<driver_schema_v>:<params_digest hex[:4]>` over the segmenters behind the live head-generation Segments the rows count, sorted and `+`-joined when there is more than one, `none` when there is none.
The merge driver is a **sort-merge by `doc_key`**:

| Case | Resolution |
|---|---|
| identical line on both sides | union |
| a line present on one side and absent from **base** | added; take it |
| a line present in **base** and absent from one side | **deleted; it stays deleted** |
| conflicting lines for one `doc_key` | a **real conflict** a human resolves |
| the header line differs | a **real conflict**: `schema`, `scorer` or `space` changed, and merging two corpora indexed by different scorers silently is exactly the drift the header exists to catch |

That third row is exactly the property `nx.compose` throws away, and it is the reason the driver is
written rather than borrowed.

**Installing it is part of the decision, because a merge driver does not travel with a clone.**
`.gitattributes` is committed and versioned; `git config merge.owlock.driver` is *local*, so a fresh
clone has the attribute and not the driver, and git then falls back to its default text merge:

```text
# .gitattributes  (committed)
omniweave.index.lock merge=owlock -diff

# installed by `ow store git-install`, checked by `ow doctor`
git config merge.owlock.name   "omniweave index lock sort-merge"
git config merge.owlock.driver "ow store merge-lock %O %A %B %L %P"
```

The fallback is safe **because it is loud**: git's text merge on a sorted line file with distinct
keys resolves most cases and writes conflict markers for the rest, and
`ow store verify --lock` **refuses** any file containing `<<<<<<<`, `=======` or `>>>>>>>` with
`OW-S-061`, so an unresolved merge cannot be mistaken for a valid receipt. `ow doctor` reports a
missing driver as a warning naming `ow store git-install`, not as a failure, because the fallback is
detectable.

`ow store lock` writes it; `ow store verify --lock` re-derives it from the store and compares;
`ow store diff` shows what an ingest changed. Committing the receipt gives a reviewer a diff that
says "these four documents were re-parsed and this one was removed" without shipping a 6 GB binary
through git, and it gives CI a byte-diff gate on the corpus itself.

## 14. Failure modes, enumerated

Each mechanism above is answered here for the four questions that matter: at scale, on hostile
input, on partial failure, and under concurrency. A row with no rule is a defect; there are none.

**Hostile and adversarial input.** Every bound is a named constant, and every breach is a stated
outcome rather than a slow query:

| Input | Bound | Outcome |
|---|---|---|
| a 200,000-term query | `MAX_QUERY_TERMS = 64`, `MAX_QUERY_CHARS = 4_000` | usage error naming the limit; the residue is **not** silently truncated, because a truncated query returns confident wrong results |
| 10,000 reference-shaped tokens | `MAX_QUERY_REFS = 16` | usage error. The `exact` Channel is one statement over `tmp_refs` (§5.2) precisely so that even the maximum is one plan |
| an FTS5 injection attempt (`a OR b NEAR(c)`, `"x" *`) | sanitisation strips specials and bare boolean keywords | the operators become literal text; `foo:bar` with an unknown prefix passes through as plain text so `TODO:` works |
| `sec_path_prefix = "/"` | none needed | the range scan degenerates to the whole corpus, which is `Narrowing.kind = "all"` — a legal plan, not an error |
| `Filters.doc_keys` with 100,000 entries | `MAX_FILTER_DOC_KEYS = 1024`, then `tmp_docs` | above the cap it becomes a temp-table join, never a 100k-element `IN` list, which is a parse-time failure |
| `Filters.pages = range(0, 10**9, 7)` | step must be 1 | usage error; a strided page filter has no index expression |
| `Expand(relations={"anything"})`, `max_hops=99` | `relation_vocab` FK check, `max_hops` hard cap 4, `beam`, `max_visited`, `hub_cap` | an unknown relation is a usage error naming the vocabulary; the caps are enforced at construction, so an unbounded traversal is unrepresentable |
| a single block of 50 MB of text | `MAX_BLOCK_CHARS` ([the document model](03-document-model.md)) | refused at parse, so retrieval never sees it. `max_chars = 24_000` bounds what hydration reads regardless |
| a query embedding driver that hangs | `embed_ms = 120`, **outside the snapshot** | `semantic: UNAVAILABLE(embed_timeout)`, `degraded`. It cannot pin the WAL, which is the whole reason phase 2 exists |
| a document with 4M cells | `TABLE_SYNOPSIS_CELLS = 20_000` → one synopsis segment | 4M FTS rows, 4M citable Blocks, 1 embedding, and §5.6's rule that the synopsis never lifts to the cells |
| `Filters.formats = {"owjob"}` | `NO_JOB_DOCS` (§3.8) | usage error naming the predicate, never an empty result — `owjob` is minted, never detected, so selecting on it can only be a mistake |

**Partial failure.** The rule in every row is the same one: a component that cannot answer says
`UNAVAILABLE` with a reason and forces `degraded`; it never returns an empty list.

| Failure | Detected by | Result |
|---|---|---|
| `block_fts` corrupt | the Channel's exception boundary; `integrity-check` in `ow store verify --fts` | `lexical: UNAVAILABLE(fts_corrupt)`, `degraded`. ST8's fault-injection test asserts exactly this rather than `absent` |
| FTS orphaned by a cascade | §3.3's structural rule + the grep gate + `integrity-check` | prevented; remedied by `ow store repair` step 2 |
| `index.vec.owstore` corrupt or truncated | `SQLITE_CORRUPT`/`SQLITE_NOTADB` at the Channel boundary (§5.2) | `semantic: UNAVAILABLE(vec_unreadable)`, `degraded`; `rm index.vec.owstore` is the documented fix |
| `vec_manifest.corpus_id` mismatch | at attach | the sidecar is **ignored, not read**; `Snapshot.vec_attached = False`; gate 13 |
| the `vec` build was killed mid-drain | `vec_manifest.rows` vs `stat.live_segments` | the sidecar serves what it has; `Verdict.space` reports `coverage=partial`; never silent partial recall (§9.3) |
| a CAS blob is missing | `byte_exact` already required `store_ref IS NOT NULL`; `ow open --verify` | `source_unavailable`; the block is returnable as `normalized` |
| a CAS blob's bytes changed | `ow store fsck --cas` sampling; a failed `--verify` | `Diag(OW_INTEGRITY_UNCHECKED)`, which is in `ABSENCE_BLOCKING_DIAGS`, so the Verdict degrades |
| `stat` stale or missing | `computed_ns` age vs `STAT_MAX_AGE_NS` | the over-fetch factor takes the maximum clamp (64) and `Degradation(kind="stat_stale")` is recorded — fail expensive, never wrong |
| a crash inside a bulk window | `index_state.bulk_window` written before the first DDL | open **refuses to serve** (`OW-S-031`) and names `ow store repair` (ST13) |
| a migration killed mid-backfill | `migration.backfill_done` vs `backfill_total`, `resumable` | resumes through the `work` queue; `unbackfilled_means` prose tells the operator what a half-backfilled column means (ST18) |
| the events file is unwritable | the flusher's `SQLITE_BUSY`/`SQLITE_READONLY` | the batch is dropped and counted; the query is unaffected |
| a shard does not answer | `federate_ms` | gate 14, `shards_contributed` names it; the fabric never waits past the deadline |
| a **second home for `SCHEMA`** reappears — a `meta.schema` key, or a `schema` column on another `[SOR]` table | `ow store verify`'s single-homedness check (below) | refuse: `OW-S-034` / `OW_SCHEMA_SECOND_HOME`, naming the offending table and key. Two homes that disagree is a misread file no operator can detect |

**Single-homedness, and why it is an absence check.** `SCHEMA` has exactly one code home,
`omniweave_core.contract` (`SCHEMA` and `SCHEMA_MINOR`, §3.1), and exactly one disk home,
`index_state`, key `schema`, value `<major>.<minor>` (§3.8). `ow store verify` gains one check in its
**default, unflagged set**:

```text
single_homedness:
  1. `meta` holds no row with k = 'schema'.
  2. No [SOR] table other than `index_state` carries a `schema` key or column
     (`meta`-shaped tables by k; every other table by PRAGMA table_info).
  breach ⇒ OW-S-034 / OW_SCHEMA_SECOND_HOME, naming the table and the key.
```

It is an **absence** check rather than a comparison because with one home there is nothing to
compare. The defect it guards — "a migration that writes one and not the other" — can only recur as a
second home reappearing, so the check is written against the recurrence and not against the symptom.
`omniweave_core.limits` holds no version constant, now or ever; `SCHEMAS_SUPPORTED` is not added,
because §3.1's four-row table is already a total function of the four version components and a
supported-set would be the first of the two to drift. The `OW-S-034` numeral is allocated here, in
`tools/codes.toml`, alongside `OW-S-030` … `OW-S-033`.

**At scale** is §12.4's ordered list; **under concurrency** is §10.7's matrix. The two rows a
reviewer should push on: a query holding a snapshot while a watcher commits a large batch pins that
much WAL, bounded only by `snapshot_ms` — which is why that value is a safety parameter; and N query
processes contending on one events file is resolved by **dropping telemetry**, counted so the drop
rate is visible.

## 15. Store invariants ST1-ST24

Each is falsifiable and names its enforcer. A reviewer may reject a pull request on any of them
without further argument.

| # | Invariant | Enforced by |
|---|---|---|
| ST1 | `sqlite3.connect` appears in exactly one module | G24 + the lint rule + a monkeypatch test |
| ST2 | One query = one snapshot | Channel functions take `Snapshot`, never `Store`/`Connection` (pyright); a test commits a full re-index between Channel 1 and Channel 5 and asserts identical results, **including `Hit.text`** |
| ST3 | No transaction spans `main` and `vec` | a grep gate over BEGIN-scoped statement groups |
| ST4 | A stale vector is invisible, never wrong | the semantic Channel's only exit is an inner join `vseg.digests[i] = segment.content_digest` inside the main snapshot; sweeps are an optimisation |
| ST5 | "No restriction" is not "restrict to nothing" | `Narrowing` is tagged; semgrep bans `if narrowing:`; a nonsense-query fixture asserts 0 hits and `absent`, never the corpus ranked by centrality |
| ST6 | `fuse()` and `ceiling()` share `_weight()`, `rank` is 1-based, and `OFF(query_deadline)` keeps its ceiling weight while `OFF(vectors)` / `OFF(not_in_plan)` / `OFF(not_built)` do not | the three-part property test of §5.3, halves (a)/(b)/(c) |
| ST7 | Every Channel, and `fuse()`, is totally ordered on `(-score, (doc_ord, page, ord), block_id)`: two ingests of one folder rank alike (D655) | a property test shuffles SQL row order 100×, VACUUMs **and runs FTS `'optimize'`**, asserting an identical ranking |
| ST8 | A Channel failure is never a confident zero | no bare `except` under `retrieve/` (semgrep); a fault-injection test corrupts `block_fts` and asserts `degraded`, not `absent` |
| ST9 | `absent` requires all fifteen gates | `build_verdict` is the sole constructor; one fixture per gate; semgrep asserts one `return VerdictState.ABSENT` site |
| ST10 | Every derived row's identity is a schema constraint, and an identity containing an `IFNULL` sentinel is always a separate `CREATE UNIQUE INDEX` | a `<table>_identity` UNIQUE INDEX per derived table; the installing migration GROUP BYs the identical expression; a double-insert test; G27b applies every migration to an empty file |
| ST11 | An operator's re-run replaces only rows whose `origin_operator` is its own | `NOT NULL` on every derived row; a grep gate over every `DELETE FROM` under `store/` for the predicate |
| ST12 | Incremental converges with a full rebuild | **G19** — the gate row owns the fixture size and the batch count |
| ST13 | A crash inside a bulk window is visible, never silently served | `index_state.bulk_window` written **before** the first DDL; open refuses and names `ow store repair`; a SIGKILL test |
| ST14 | A `BILLED_API` commit is durable | `synchronous = FULL` set **before** `BEGIN` for that transaction; a test asserts the pragma at commit time |
| ST15 | A reader cannot pin the WAL indefinitely | `MAX_SNAPSHOT_MS` in the snapshot context manager, enforced by `interrupt()`; the query embedding is outside the snapshot |
| ST16 | A governor that cannot help gets out of the way | the futility latch: 2 give-ups ⇒ 60 s cooldown ⇒ degrade to un-valved, with an armed log line and a heartbeat |
| ST17 | Every shipped index is used and every hot query's plan is reviewed | `tools/indexes.toml` with an owner column; `ow store explain --golden` byte-diff gated |
| ST18 | Every migration declares its cost class, resumability and what an un-backfilled row means | `NOT NULL` in a STRICT table; the loader refuses a `> WATCHDOG_MS/2` migration that is not resumable |
| ST19 | The store is never committed | the shipped `.gitignore`; `ow doctor` fails with `OW-S-060`; `ow store verify --lock` refuses a conflict-marked receipt with `OW-S-061` |
| ST20 | `block_id` carries its minting shard forever | a CREATE-time literal `CHECK ((block_id >> 48) = <shard_ord>)`, re-asserted at open; an append-only shard registry |

Four invariants added by this document, in the same form and enforced the same way:

| # | Invariant | Enforced by |
|---|---|---|
| ST21 | **No FTS-bearing table is ever emptied by a foreign-key cascade.** | a grep gate requiring an explicit `DELETE FROM block WHERE doc_ord = ?` immediately before any `DELETE FROM doc`; `ow store verify --fts` runs `integrity-check` on `block_fts` and `head_fts` and compares row counts; the staged-generation sweep (§11.1) `'rebuild'`s after a non-zero delete |
| ST22 | **No `embed/1` Driver call happens inside a read snapshot.** | pyright: the phase-2 embed function does not take a `Snapshot`; semgrep bans a `DriverHost.invoke` call inside a `with reader.snapshot()` block; a test asserts a 3 s stub embedder does not extend `Snapshot.opened_ns`-to-close beyond `snapshot_ms` |
| ST23 | **`SCHEMA` has one code home and one disk home, and neither gains a second.** | `ow store verify`'s single-homedness check in its default set (§14): `meta` holds no `schema` key and no other `[SOR]` table carries one, breach `OW-S-034`; a grep gate rejects a version constant added to `omniweave_core.limits`; a migration fixture that writes `meta.schema` is asserted to fail `verify` |
| ST24 | **A store built from the shipped migrations carries exactly one `schema` stamp, and it is this build's.** | `G27(b)`'s assertion at the **end** of the `0001` → `0005` run on `MIN_SQLITE` — not after `0001_init.sql`, which is two migrations before `index_state` exists: `index_state` holds exactly one `schema` row whose value equals `f"{SCHEMA}.{SCHEMA_MINOR}"` read from `omniweave_core.contract`, and `meta` holds no `schema` key |

## 16. Types this document defines

The charter names these in signatures without giving them shapes. They are fixed here and listed in
**New terms** for the lock.

```python
@dataclass(frozen=True, slots=True)
class IndexCaps:                      # what plan() may know about the store. Read once, at open.
    schema: str; scorer_version: int  # schema is '<major>.<minor>' (§3.1)
    channels: frozenset[str]          # which of the five CAN run at all in this store
    has_head_fts: bool; has_trigram: bool; fts_state: str
    space_id: int | None; vec_backend: str | None; vec_ceiling: int; vec_pushdown: bool
    live_blocks: int; live_segments: int; docs: int      # from `stat`
    stat_age_ns: int                  # > STAT_MAX_AGE_NS ⇒ the over-fetch factor is 64 (§3.8)
    shard_ord: int; federated: bool
    caps_digest: str                  # sha256_canonical of every field above; memoises plan()

@dataclass(frozen=True, slots=True)
class ChannelInput:                   # the QUERY material, bound AFTER plan() (§6)
    terms: tuple[str, ...] = ()       # sanitised, ≤ MAX_QUERY_TERMS
    refs: tuple[tuple[str, str], ...] = ()        # (name_norm, akind), ≤ MAX_QUERY_REFS
    idents: tuple[str, ...] = ()      # candidate cites, addrs, uris, titles
    scope_doc: int | None = None
    q_sig: bytes | None = None        # from phase 2. NEVER computed inside the snapshot.
    q_full: bytes | None = None
    expand: "Expand | None" = None

@dataclass(frozen=True, slots=True)
class ChannelSpec:                    # one row of QueryPlan.channels; the order IS the run order
    name: str                         # a member of CHANNELS
    budget_ms: int                    # this Channel's own deadline (§6.4 case one)
    limit: int                        # channel-local top-N BEFORE fusion
    overfetch: int                    # multiplier applied before re-rank; 1 = none
    weight: float | None              # explicit (0.0 included) wins over [retrieval.weights]
    params: Mapping[str, Scalar]      # e.g. {"expand_hops": 2}; flat scalars only
    bind: ChannelInput | None = None  # None in a QueryPlan; set by retrieve(). NOT in plan_digest.

@dataclass(frozen=True, slots=True)
class FusionSpec:
    k: int = RRF_K
    weights: Mapping[str, float] = MappingProxyType(DEFAULT_WEIGHTS)
    low_confidence: float = 0.35

@dataclass(frozen=True, slots=True)
class PackSpec:                       # what RETRIEVAL bounds. The Answer allocator is D9's.
    k: int; max_blocks: int; max_chars: int
    hydrate_text: bool = True         # False ⇒ every Hit.text is None
    with_spans: bool = True

@dataclass(frozen=True, slots=True)
class QueryBudget:
    query_ms: int = 250               # the SNAPSHOT-HELD phase only (§4.4)
    hydration_reserve_ms: int = 40    # hydration + the coverage scan. NOT a Channel, NOT
                                      # schedulable; lint check 3 reads it (§4.4)
    embed_ms: int = 120               # phase 2, OUTSIDE query_ms and outside the snapshot
    snapshot_ms: int = 2_000          # clamped BELOW MAX_SNAPSHOT_MS = 5_000
    federate_ms: int = 40             # T4 only: fan-out + rank-merge + straggler tolerance
    channel_ms: Mapping[str, int] = MappingProxyType(
        {"identity": 15, "exact": 25, "lexical": 50, "structural": 40, "semantic": 80})
    max_micros: int = 0               # 0 = no billable work on the query path

@dataclass(frozen=True, slots=True)
class RetrievalPolicy:                # D4's loaded policy, surface = "retrieval"
    rules: tuple["Rule", ...]; thresholds: Mapping[str, float]
    policy_name: str; policy_digest: str

@dataclass(frozen=True, slots=True)
class Coverage:                       # what Reader.coverage() returns; feeds gates 4-9
    discovered: int; indexed: int; partial: int; failed: int; skipped: int
    complete: bool
    scope_rows: int                   # 0 ⇒ NO ingest_scope row in view ⇒ coverage UNKNOWN, gate 4
    pending_work: int; stale_units: int; unreadable_units: int
    gaps: tuple["DegradeCause", ...]  # gate 9's diag join, already grouped by (doc, page range)

@dataclass(frozen=True, slots=True)
class VecManifest:                    # the `vec` sidecar's identity, read at attach
    corpus_id: str; schema: int; model_key: str
    backend: str; backend_version: str
    storage: Literal["sig_only", "sig_full"]; sig_bits: int; dim: int
    built_at_ns: int; rows: int
    pushdown: bool                    # obligation (1); False ⇒ the over-fetch clamp + Degradation
```

`Hit` and `Response` are in §7.1, with the query path they belong to. `Verdict`, `DegradeCause` and
`build_verdict()` are in §6.7 and the fifteen `ABSENCE_GATES` in §6.8, with the planner and the gate
ladder they belong to; `VerdictState`, `ABSENCE_GATES` and `ABSENCE_BLOCKING_DIAGS` are the
charter's and are referenced rather than redefined.

## Extends the charter

Twelve decisions this document makes where the charter is silent on a detail the store needs,
**six additive fields** where the charter's stated semantics are not representable in the shape it
gives, and **one printed value corrected** — the only row below that overrides the charter rather
than completing it. Each is made in the charter's spirit and is flagged so a reviewer can attack it
individually.

| # | Extension | Why the charter forces it |
|---|---|---|
| 1 | **`ChannelResult.rank_of`** (§5.1) — `Mapping[int, int]`, default empty | The charter states "a segment hit at rank *r* yields its member blocks **at rank *r***" and gives `ChannelResult` only a positional `ranked` tuple. jcodemunch's fuse loop derives rank by `enumerate`, which spreads 64 co-ranked blocks over 64 ranks and destroys the region-level property the rule exists to create. Following the charter therefore requires a place to put the rank. Additive, real default, only the semantic Channel populates it |
| 2 | **`Hit.text`** (§7.1) — `str \| None`, `None` iff `PackSpec.hydrate_text is False` | The charter's `Hit` has no carrier for evidence text and `Response` has three fields. Without `text`, the Answer renderer must re-read block text after the snapshot closes, so the ranking obeys ST2 and the payload does not — a committed re-index between the two hands back text from a different generation than was scored. Fourteen fields, not thirteen |
| 3 | **`ChannelSpec.bind`** (§6, §16) — `ChannelInput \| None`, excluded from `plan_digest` | `Reader.channel(s, spec, n)` is the charter's signature and `plan()` is pure and memoised on query *shape*. With no field for query material, the signature cannot be implemented. `bind` is `None` in a plan and set by `retrieve()`, so the digest still keys on shape |
| 4 | **FTS5 option set** (§3.3) — `detail='full'`, `columnsize=1`, no `prefix`, no persistent `rank` | The charter fixes the tokenizer and the external-content design and is silent on the options that decide whether `Hit.span` and `bm25()` exist at all |
| 5 | **The FTS cascade rule and `fts_state` machine** (§3.3, ST21) | The charter declares `ON DELETE CASCADE` on `block` *and* trigger-maintained external-content FTS, which are incompatible without a rule; and it names `fts_state{ok,building,stale}` without a writer or a reader |
| 6 | **Phase 2: the query embedding outside the snapshot** (§4.4, ST22) | The charter puts the semantic Channel inside the one `BEGIN DEFERRED` and separately declares that a held read pins the WAL. An inference call inside the snapshot is the futility-latch condition; the phase split is the only way to obey both |
| 7 | **Maintenance** (§2.2) — `PRAGMA optimize`, FTS `'merge'`, `incremental_vacuum`, and `ow store repair`'s four steps | The charter sets `auto_vacuum = INCREMENTAL` with nothing that vacuums, ships FTS5 with nothing that merges, and names `ow store repair` without defining it |
| 8 | **`sig_bits = dim`, `storage = "auto"`'s resolution rule, the three vector bands** (§3.7, §3.9) | The charter's measured ceiling is on **96-byte** signatures and its config key is `[retrieval.vec] storage = "auto"` with no resolution rule. Deriving `sig_bits` from `dim` is what makes the 96 bytes and the 250,000 ceiling one arithmetic |
| 9 | **`sec_path` zero-padding** (§3.6) | The charter's `'/1/4/2'` example is lexicographically unsortable past nine siblings, and the index it feeds is a range scan |
| 10 | **`ingest_scope.scope_id` as a URI prefix** (§3.8) | Gate 4 must select "scope rows in view" and there is no `doc → scope` link anywhere; a prefix `GLOB` over `doc` is the only implementable containment test |
| 11 | **`owrows/1`** (§7.5) | The charter specifies the Answer and the `Response` and nothing about a compact structured encoding. The constraint that keeps it inside the charter is that it never touches the MCP Answer and never encodes evidence text |
| 12 | **`ST21`-`ST24`** and the codes `OW-S-030` … `OW-S-034`, `OW-S-061` | Each names a hazard the charter's own mechanisms create and does not yet number. `ST23`/`ST24` and `OW-S-034` are ADR-9's single-homedness pair, and the charter's own `SCHEMA` sentence is corrected by erratum `E72` rather than here |
| 13 | **The per-component byte decomposition, the per-scale latency estimate, the T4 budget, the memory budget** (§4) | The charter carries the totals and the gates; the decompositions are derived here so a reviewer can attack a line, and the latency table is labelled an estimate with F50 as its measurement |
| 14 | **The four shipped retrieval policy rules** (§6.2) | The charter says the policy is D4's grammar verbatim with `surface = "retrieval"` and gives no rules. These four are the shipped starting set; they are data, and `ow route lint` validates every key against the `SignalSpec` registry |
| 15 | **`Verdict.generated_share`** (§6.7) — `float`, default `0.0`, domain `[0.0, 1.0]` | The charter's `Verdict` has no carrier for it, and `V10-17` makes "`generated_share` is reported on every `Verdict`" a v1.0 release criterion with a written test in [13](13-quality.md) §10.1. Without the field the criterion has no subject. Additive, real default, last in the shape |
| 16 | **`Verdict.degradations`** (§6.7) — `tuple[Degradation, ...]`, default `()` | Four documents already say a `Degradation` is *recorded on the `Verdict`*: this document's §3.8 (`stat_stale`) and §6.3 (`pushdown_unavailable`), [10](10-interfaces.md)'s `ow:trailer` row, and [glossary](glossary.md)'s carrier column. `schema/verdict-v1.json` is `$ref`'d for `degradation` from the MCP Answer schema ([18](18-api-sketch.md) §3), so the `$def` lives on this type either way. The charter's shape omits it and its own prose requires it |
| 17 | **`Filters.deny_methods`** (§6.1) — `frozenset[Method]`, default `frozenset()` | The charter ships `WORTH_QUOTE` and `WORTH_TRUST` down-weights and no filter predicate over `Method`, so "answer from source documents only" is inexpressible and a generated summary at 0.68 relative worth can still outrank a scanned source page. [vision](00-vision.md) §8 names this document as the owner and `V10-17`/`00#V-Q5` as the criteria. A deny list, because the empty set must mean "no restriction" (ST5) |
| 18 | **All fifteen gates are evaluated on every query; there is no short-circuit after the first failure** (§6.7) | The charter fixes the precedence *order* and is silent on whether evaluation stops at the first failure. Both `Verdict.gates` and `Verdict.degraded_because` are plural, `degradation_detection == 1.000` asserts that *the expected* gate is present rather than the first one, §6.6's worked plan (5) reports gates 4, 5 and 9 together, and gates 4-9 all read one `Coverage` object produced by one scan, so stopping early saves nothing measurable |
| 19 | **`Verdict.fusion_kind` is `Literal["rrf", "rank_merge"]`** (§6.7), superseding the charter's printed `Literal["exact", "rank_merge"]` | **This row corrects the charter rather than extending it, and it is the only one that does.** `"exact"` is emitted by no document: §5.3's non-federated arithmetic is weighted RRF (`fuse()`, `ceiling()`, `RRF_K = 60`), `"exact"` is already the name of one of the five `CHANNELS` (§5.1) so the two senses collide on every read, and [18](18-api-sketch.md) §1.3's `Answer.fusion_kind` already prints `Literal["rrf","rank_merge"]` — the same literal, though not the same value under federation, since a rank-merged `Answer` reads `"rank_merge"` over contributing `Verdict`s that each read `"rrf"`. Keeping the charter's literal would leave one field with two shapes and reserve a channel name for a fusion mode. Recorded as charter errata |

## Open questions

Each names the measurement that closes it and the pre-committed fallback. Nothing here blocks
implementation; everything here is a number someone must produce, or a charter defect a reviewer
must rule on.

| # | Question | What closes it | Pre-committed fallback |
|---|---|---|---|
| **F1** (charter) | **The blocks-per-page envelope.** Estimated 60-120/page; measured 338 B/block, one synthetic corpus at 912 B/block. Every number in §4 scales off it | `fixtures/gen/gen_5000p_pdf.py` plus ten real 200-page documents, counting Blocks per page **including cells**, with `store.bytes_per_block` as a nightly ratchet | If dense corpora land at ~300/page, retune the 8,192-block frame target, the peak-RSS gate and every projection in §4.3: the page equivalence in §12.5 falls from ~110,000 to ~33,000 pages, and every storage, frame and RSS projection moves with `bytes/block`. The 10M-50M **block** ceiling is unchanged: it is denominated in blocks and set by §12.4 item 4 |
| **F9** (charter) | Does binary quantisation to `sig_bits = dim` plus an exact rerank of the top 1,000 hold recall on document segments? | `gate_vec_recall.py`: recall@10 of `sig → top-1000 → f32 rerank` against exhaustive f32 on a fixed 50k fixture | Below 0.95, the stdlib backend ships `sig_full` only, with a smaller ceiling |
| **F10** (charter) | Which ANN library clears G3 and ships pure wheels for 9 cells? Two candidates declare permissive licences and neither is in the mined collection | G3's three scans against the candidate plus wheel availability, **before the vector phase starts** | `vector.brute` plus the 250k refusal |
| **F11** (charter) | Is `W_HEAD = 6.0` with `SPINE_DECAY = 0.6` right, or does heading propagation promote tables of contents above the sections they name? | nDCG@10 over `fixtures/store/golden-queries.jsonl` with `W_HEAD` swept across {1, 2, 4, 6, 12}, `toc_entry` in and out | If the curve is flat, drop `head_fts` and the lexical Channel becomes one term |
| **F32** (charter) | Should `part` bytes be retained by default, and what does retention actually cost? | Measure the fraction of Blocks achieving `origin_span: exact` across the driver roster, plus the storage delta on the 100k reference ingest | Under ~20% achieved-exact, `retain_parts = "never"` becomes the default and `corpus_card.verbatim_fraction` prints the consequence before any query runs |
| **F35** (charter) | Does the fifteen-gate Verdict hold at federation scale? Gate 4 needs a **global** discovered-versus-indexed count | Run the absence suite against a two-shard fixture with one shard deliberately unreachable | `coverage_incomplete` becomes per-shard and the Verdict reports `coverage: unknown` with the shard named |
| **F50** (new) | **The per-scale latency table in §4.4 is an estimate, not a measurement.** The only measured retrieval numbers in this plan are the 81 ms signature scan and the 250 ms gate | `ow bench query` over generated corpora at 10k / 100k / 1M / 10M blocks on the pinned `ow-bench-1` runner, reporting p50/p95/p99 per Channel, the narrowing probe and hydration separately | If lexical p50 at 10M exceeds its 50 ms budget, the budget is raised and one of `structural`/`semantic` is cut, since `ow route lint` refuses a sum ≥ `query_ms`; the fix is never to raise `query_ms` past the G10 row |
| **F51** (new) | **What does `owrows/1` actually save on omniweave's shapes?** 45.5% is jcodemunch's median on code-search results, and `hit1`/`prov1` rows are wider and less prefix-redundant | `ow bench encoding` over the golden query set per encoder id, publishing a ratio with `n` and a confidence interval | If the median saving is under 25%, ship `gen1` only and drop the three tier-1 encoders — a threshold gate on an encoding nobody benefits from is pure maintenance |
| **F52** (new) | **What is the real distribution of narrowed-set size, and is `PREFILTER_MAX = 200_000` the right cut?** The probe's cost is linear in the cap and its benefit is exactness | Instrument `retrieval_event.narrowing_n` and `prefilter_exact` over a month of real queries on the reference corpora (requires `[retrieval] event_log = true`) | If the p95 narrowed set is far below 200k, lower the cap and save the probe's tail latency; if it routinely exceeds it, the over-fetch clamp is the common path and needs its own eval slice rather than being the exception |
| **F53** (new) | **Should a plan with no `lexical` Channel run `structural` early at all?** In every plan that contains `lexical` the order is settled — `lexical` then `structural` (§6.2) — so the only open placement is the `structural-only` plan, where §6.2 puts `structural` third on seedability grounds rather than ordering strictly by measured p50 cost | `ow bench query --explain` measuring per-Channel `ran_ms` on `structural-only` plans and the frequency with which `short_circuit` fires before `structural` | If `short_circuit` fires on under ~5% of those queries, order every plan strictly by measured p50 cost and let `structural` seed from `tmp_narrow` whenever nothing precedes it |
| **F54** (new) | **What does FTS5 `detail='full'` actually cost?** §4.1 budgets `block_fts` at ~70 B/block and the 30-50% saving from `detail='column'` is an estimate from the format, not a measurement | Build the 1M-block reference corpus twice, at `detail='full'` and `detail='column'`, and diff `dbstat` for the FTS shadow tables; measure `Hit.span` availability in both | If `full` costs more than 40% of total index size, `detail` becomes a build-time choice with `IndexCaps.has_spans = False` on a `column` index and `Hit.span = None` disclosed — never a silently absent span |
| **F55** (new) | **Does the `'merge'` step keep the lexical Channel inside its budget over months of incremental writes?** §12.4 item 3 is a predicted degradation with no measurement | `ow bench incremental` ([12](12-performance.md) §7.1, which is authoritative for these figures): **10,000 successive single-document ingests into a 1M-block store, sampled every 500** — `SELECT count(*)` over `block_fts_data`'s segment rows, `lexical` p50 **and** p95, and total index bytes at each sample — **run twice, with and without the maintenance window**. 10,000 rather than 1,000 because F55 asks about *months* of writes: at `automerge = 4` and `MERGE_STEPS = 16`, a thousand single-document writes is roughly one month of a deployed roster, so a 1,000-ingest soak can only return a null result on the exact question | If p50 or p95 still climbs on the run without the window, `automerge` rises from 4 and `MERGE_STEPS` from 16, in that order; if it still climbs, a scheduled `'optimize'` inside `ow store compact` becomes a documented weekly operation rather than an on-demand verb |
| **F56** (new) | **Does `deny_methods` need an allow-list twin?** §6.1 ships one predicate, a deny list, on the reasoning that the only expressed need is "not `ROUNDTRIP`". An allow list (`only_methods`) would express "OCR pages only" for a review workflow, and the two together raise an interaction question — whether `only_methods` and `deny_methods` intersect or the deny wins — that one predicate does not have | `retrieval_event` slicing on which `Filters` fields real queries set, over the same month F52 instruments, plus the review-surface backlog: how many requests name a positive `Method` set rather than a negative one | If fewer than ~5% of filtered queries would want a positive set, the deny list stands alone. Otherwise `only_methods` is added with the rule **deny wins on intersection**, pre-committed here so the interaction is decided before the field exists |
| **F57** (new) | **What is the real distribution of `generated_share` on a corpus that ingests its own output?** §6.7 defines the number and [13](13-quality.md) §10.1 asserts only that it is `0.0` under the restriction and `> 0.0` without it. Nothing says what value should worry an operator | `retrieval_event.generated_share` (§3.10 — the column exists, so this is one `SELECT` and not a bespoke harness) over the 30-task run [17](17-risks.md) F19 builds, on a corpus deliberately seeded with its own compiled decks at 10%, 25% and 50% of blocks | If the median `generated_share` exceeds the seeded block share at any level, the down-weight is under-priced and `WORTH_QUOTE`/`WORTH_TRUST` are refit before any threshold is added — a warning banner on a number nobody has calibrated is noise |

**Three charter defects.** The document follows the charter on items 1 and 3 and records them; it
**departs** from the charter on item 2, where the lock has already been changed:

1. **Eleven names in charter signatures and DDL have no §2 terminology row** — `IndexCaps`,
   `ChannelSpec`, `FusionSpec`, `PackSpec`, `QueryBudget`, `RetrievalPolicy`, `Coverage`,
   `VecManifest`, `Hit`, `Response` and the table `stat`. The lock's own bidirectional CI check
   (G27c, direction 1) fails on every one of them. This document shapes them (§16, §7.1) and lists
   them in **New terms** so the next lock revision closes the gap; it does not rename anything.
2. **The key the charter prints as `[retrieval.vec] max_blocks = 250000` (charter `:612`, `:4440`)
   is `[retrieval.vec] max_segments`.** `VEC_BRUTE_MAX = 250_000` is a ceiling on **segments** and
   the measurement behind it counted signatures, one per segment, so the charter's name states the
   wrong unit and the naming rule ("a count is a bare plural") puts the unit in the name.
   [ADR-1](adr/0001-terminology-lock-bulk-pass.md) decision 7 row 3 made the rename: the lock
   carries `max_segments` ([terminology](_notes/terminology.md):1008) and `tools/config_axes.toml`
   carries the pattern. `PackSpec.max_blocks = 60` keeps its name — that one really is a Block
   count (§16) — which is why this was a collision and not a typo.
3. **The semantic lift's equal ranks are unrepresentable in `ChannelResult`.** Recorded as
   extension 1 above rather than only here, because the fix had to ship in the main text for the
   Channel to be implementable at all.

**One assignment-versus-charter discrepancy.** The brief for this document names **four** retrieval
signals (lexical, structural, semantic, identity), which is jcodemunch's set. The charter is binding
and specifies **five Channels**, splitting `identity` into `identity` and `exact`, with
`DEFAULT_WEIGHTS` carrying five entries and the ceiling arithmetic (`5.4/61`) depending on it. This
document follows the charter; §5.1 states the split and why documents force it. No contradiction
exists inside the charter itself.

## New terms

Terms this document introduces or shapes, for merging into `_notes/terminology.md` §2.

| Term | Kind | Definition |
|---|---|---|
| `ChannelInput` | type | The **query material** bound to a `ChannelSpec` after `plan()` returns: sanitised terms, lifted `(name_norm, akind)` refs, identity candidates, the scope document, and the phase-2 query signature and full vector. It is excluded from `plan_digest`, which is what lets a pure planner be memoised on query *shape* while `Reader.channel(s, spec, n)` still receives the query. |
| `ChannelSpec` | type | One row of `QueryPlan.channels`: the Channel name, its **own** `budget_ms`, a channel-local `limit`, an over-fetch multiplier, an optional explicit weight (`0.0` included), flat scalar params, and a `bind: ChannelInput \| None`. The tuple's order **is** the run order. |
| `Coverage` | type | What `Reader.coverage()` returns and what absence gates 4-9 read: discovered/indexed/partial/failed/skipped counts, a `complete` bit, **`scope_rows`** (0 means coverage is *unknown*, not clean), pending work, stale and unreadable unit counts, and the already-grouped `DegradeCause` rows from gate 9's `diag` join. |
| `DegradeCause` | type | One absence gate's explanation, and one is emitted per gate that failed: the gate name (a member of `ABSENCE_GATES`, never free text), a one-line `detail` printed verbatim by `ow why absent`, the `ABSENCE_BLOCKING_DIAGS` codes behind it, the `(doc_ord, page_lo, page_hi)` ranges it covers, and **the exact command that clears it**. `fix` is parsed against the `ow` Action registry and invoked in-process, never shelled; it is `""` only for the two gates no command clears. Shaped in §6.7. |
| `deny_methods` | field | `Filters`' predicate over `Method`: a `frozenset[Method]` of producing methods excluded from the narrowed set, empty by default. It is the mechanism `V10-17` and `00#V-Q5` require — `deny_methods={Method.ROUNDTRIP}` is "answer from source documents only" — and it is a **filter** rather than a score term because a filter narrows before any Channel scores and therefore cannot be outvoted by a fusion weight. Empty means *no restriction*, never *restrict to nothing* (ST5). The effective set is `caller ∪ policy`; policy may only narrow further. |
| `did_you_mean` | field | `Verdict`'s bounded suggestion list (`MAX_DID_YOU_MEAN = 5`): identity candidates that resolved at `IDENTITY_LADDER` tier 30 or 20 — below the tier the Channel reports as a hit — followed by lifted `Query.refs` whose `name_norm` matched no `anchor` row of the same `akind`. Both sets are by-products of Channels that already ran inside the snapshot; **nothing re-runs**. A suggestion carries no `cite`, no score and no ceiling contribution, so it can never be cited. |
| `embed_ms` | cfg | The **phase-2** deadline: the time allowed to embed a query, spent **before** `snapshot()` opens and therefore outside `query_ms`. An `embed/1` call inside a read snapshot pins the WAL, which is the futility-latch condition, so the phase boundary is an invariant (ST22) and not a scheduling detail. |
| `federate_ms` | cfg | The T4 fan-out deadline: fan-out, rank-merge and straggler tolerance for a federated query. A shard that misses it does not contribute, absence gate 14 fires, and `shards_contributed` names it — so p99 at T4 is bounded by this constant and not by the slowest shard. |
| `FusionSpec` | type | The fusion parameters of one plan: `k` (default `RRF_K = 60`), the weight map, and the `low_confidence` threshold (0.35). |
| `Hit` | type | One ranked retrieval result: `block_id`, `cite`, `addr`, `score`, **`text`**, `span`, per-Channel contributions and ranks, the identity grade **actually measured**, `segment_id`, `trust`, `quote`, `byte_exact` and `restriction_bits`. Fourteen fields. It carries no per-hit confidence (that is `Verdict`'s), no neighbour list (a neighbour **is** a `Hit` whose `channel_ranks` holds only `structural`) and no impact (a named read, §7.4). |
| `IndexCaps` | type | What `plan()` may know about a store, read once at open: schema and scorer version, which Channels can run at all, FTS availability and state, the vector space, backend, ceiling and pushdown bit, the scalar counts from `stat` with their age, the shard ordinal, and a `caps_digest` that memoises the planner. **The planner never reads the store**, so this is the whole of its knowledge. |
| `NO_JOB_DOCS` | const | The job-document exclusion, `"doc.format <> 'owjob'"`, held as one string in `omniweave_core.store` and appended verbatim by every statement that counts documents — `stat.docs`, `ow store stats`, `corpus_card`'s document count, absence gate 4's scope roll-up. A `format = 'owjob'` document is the synthetic job row [generation](09-generation.md) §7.1 hangs a compile-produced asset off; it carries zero `block` rows, so it is invisible to every Channel by construction and the predicate exists for **counts**, not for hits. `Filters.formats = {"owjob"}` is a usage error naming it. |
| `owrows/1` | proto | The compact tabular wire encoding for the **structured half** of a retrieval response — hits, provenance rows, neighbourhood edges — derived from jcodemunch's MUNCH **pattern and spec, not its code** (it is dual-licensed). Line-oriented, deterministic, round-trippable, fail-open, and gated on a ≥ 15% saving. **Never applied to evidence text and never on the MCP wire**, where an Answer is one content block. Encoder ids `hit1`, `prov1`, `nb1`, `gen1`; a breaking change bumps `#owrows/2` and unknown scalar keys are ignored at version 1. |
| `owrows` encoder id | concept | The short mnemonic naming one `owrows/1` schema (`hit1`, `prov1`, `nb1`, `gen1`). A decoder selects its rehydration routine by this id; a new response shape adds an id rather than changing an existing one. |
| `PackSpec` | type | What **retrieval** bounds: `k`, `max_blocks`, `max_chars`, and whether to hydrate text and spans. `hydrate_text = False` makes every `Hit.text` `None`. The Answer allocator, its tiers and its cliff are `10-interfaces.md`'s and are not here. |
| `QueryBudget` | type | The deadlines of one query: `query_ms` (the snapshot-held phase), **`hydration_reserve_ms`** (the named 40 ms reservation for hydration plus the coverage scan — not a Channel, not schedulable, and what `ow route lint` check 3 adds to `sum(channel_ms)` before comparing against `query_ms`, §4.4), `embed_ms` (phase 2, outside it), `snapshot_ms` (clamped below `MAX_SNAPSHOT_MS`), `federate_ms` (T4), the per-Channel `channel_ms` map, and `max_micros` (0 = no billable work on the query path). |
| `rank_of` | column | `ChannelResult`'s authoritative 1-based rank per `block_id`, empty for every Channel but `semantic`. It is what makes "a segment hit at rank *r* yields its member blocks at rank *r*" representable; with a positional rank only, 64 co-ranked blocks would occupy 64 distinct ranks and the region-level signal would be destroyed. |
| `RetrievalPolicy` | type | D4's loaded, digested policy at `surface = "retrieval"`: first-match-wins rules, thresholds, a name and a `policy_digest`. Same grammar, same loader, same subsumption linter, same isotonic fitter as the routing surface. |
| `Response` | type | What `retrieve()` returns, and exactly three fields: a totally ordered `hits` tuple, the `Verdict`, and the `Spend`. Everything a caller might want as a fourth field is either on `Hit`, on `Verdict`, or a separately named read. |
| `scanned` | field | `Verdict`'s four-key scan census, closed and always complete: `narrowed` (the candidate-set size, or `stat.live_blocks` when narrowing is `all` and `0` when it is `empty`), `blocks` (distinct `block_id`s any Channel ranked, before fusion — the TypeScript SDK's `scannedBlocks`), `segments` (distinct segments the semantic Channel touched) and `docs` (distinct `doc_ord`s among the fused hits). A missing key is a bug, not a zero: "we did not measure" and "we measured zero" are the distinction the whole type preserves. |
| `stat` | table | Scalar counts only — `live_blocks`, `live_segments`, `docs`, per-kind counts — with `computed_ns`. **No histograms**, because the narrowing decision is an exact probe. Re-derived by `op.converge` and `ow index stats`; past `STAT_MAX_AGE_NS` the over-fetch factor takes its maximum clamp and the Verdict records `stat_stale`. |
| `VecManifest` | type | The `vec` sidecar's identity, read at attach: `corpus_id` (a mismatch means the sidecar is **ignored, not read**), schema, `model_key`, backend and version, storage class, signature width, dimension, build time, row count, and the `pushdown` bit that decides whether `candidates` narrows before ranking. |
| `Verdict` | type | The retrieval honesty record, **shaped here** at §6.7 in twenty-two fields: the state and the gates that failed with a `DegradeCause` each; the fusion arithmetic (`scanned`, `best_score`, `score_ceiling`, `confidence`, `scorer_version`, `plan_digest`); what looked (`channels` with all five keys always present, `freshness`, `coverage`, `withheld`, `matches_before_packing`); the identity of the read (`space`, `snapshot_gen`, `federated`, `shards_contributed`, `fusion_kind`, `did_you_mean`); and two fields additive to the charter's shape, **`generated_share`** and **`degradations`**. `state is ABSENT` is the single rule that licenses an absence claim, and `build_verdict()` is the only constructor. |
| `wal_baseline_bytes` | column | The `index_state` key holding the WAL size at the last **confirmed-complete** backfill. The valve triggers on **growth beyond this baseline**, never on absolute file size, because a WAL file's size never shrinks and a size-triggered valve fires forever once the file passes its threshold. |
| `block_tri` | table | The optional trigram FTS5 table, created only at `[retrieval] trigram = true`. It is **one rung inside the `exact` Channel** at tier 35, contributing membership and never a score, gated by `IndexCaps.has_trigram` and floored at `MIN_TRIGRAM_CHARS = 3`. Enabling it never adds a sixth Channel. |
