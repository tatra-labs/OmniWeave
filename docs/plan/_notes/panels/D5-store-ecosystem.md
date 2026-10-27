# D5 — Storage, indexing, retrieval and query planning

**Panel:** D5. **Prior:** ecosystem / operator / TCO advocate. **Status:** proposal.

---

## Headline

**The `.owstore` SQLite file is the *published read interface* and merely the *swappable write
implementation*: one file per corpus that any language can open read-only against a byte-diff-gated
`schema/store-v1.sql`, written only through four small protocols (`Store`, `Index`, `VectorIndex`,
`DocSink`) so Postgres slots in at T3 without an operator changing a line. Retrieval is five
channels — `lexical · exact · identity · structural · similarity` — fused by weighted RRF with a
computed ceiling, planned by a pure `plan(Query, IndexCapabilities, Policy) -> QueryPlan` whose
rules use D4's grammar verbatim so an operator learns one policy language for the whole framework,
executed inside exactly one WAL read snapshot, and answered with a twelve-gate verdict in which
"not found" is a *provable* claim and a licence filter, a failed OCR pass, or a truncated response
each force `degraded` rather than a confident zero. Embeddings are an operator and the ANN index is
a `Backend` behind an entry point; omniweave ships a zero-dependency binary-signature scanner I
measured at 2 ms/10k and 466 ms/1M blocks which *refuses above 250k blocks with a named remedy*,
because the alternative to an honest ceiling is a five-second query nobody warned you about.**

The corollary that drives everything below: **an index is a cache with a public schema.** It is
never committed to git, always rebuildable by one command, and every channel in it is individually
droppable — dropping one changes the *verdict*, never the honesty of the answer.

---

## 0. Conflicts, and corrections I am obliged to make as schema owner

Three items. The first is a genuine contradiction between two binding rulings; the second is a
mechanical defect in binding DDL that I must fix rather than copy; the third is cosmetic and
recorded so nobody re-derives it.

**C1 — `omniweave-core` purity vs. the `owdoc` dependency list (D1 × D2).** D1 §Spec, *Core
purity*: `omniweave-core` "depends on nothing outside the standard library, enforced by a gate that
resolves it in a clean environment and asserts exactly one distribution", and D1's concrete
`pyproject.toml` says `dependencies = []   # ENFORCED BY GATE G1. Amending this amends D1.` D2 §Spec
¶1 states the opposite: "`omniweave-core` depends on `pydantic`, `zstandard` and stdlib `sqlite3`",
and D2's layout comment reads `owdoc/  # omniweave-core. pydantic + zstandard + stdlib sqlite3.
~15 MB.` D2 additionally specifies `content_digest = blake3_128(...)`, and `blake3` is not in the
standard library either. **This is not D5's call to make**, and the minimum amendment is for the
charter to pick one and re-render the other ruling's dependency line.

D5 is written to be correct under **either** reading. Every line of `omniweave_core.store` and
`omniweave_core.retrieve` uses only `sqlite3`, `json`, `hashlib`, `array`, `struct`, `heapq`,
`unicodedata`, `re` and `tomllib`. `content_digest` and `layout_digest` are consumed as opaque
16-byte `BLOB`s and are never recomputed here. My only ask of the charter is that `sqlite3` remain
importable from core — which holds under both readings.

**C2 — three binding `ALTER TABLE` statements cannot execute.** D3's *"Store DDL D3 requires of D5"*
block and D4's *"No driver runs unrouted"* line specify:

```sql
ALTER TABLE block ADD COLUMN origin_driver    TEXT    NOT NULL;                                 -- D3
ALTER TABLE block ADD COLUMN driver_schema_v  INTEGER NOT NULL;                                 -- D3
ALTER TABLE work  ADD COLUMN decision_id TEXT NOT NULL REFERENCES route_decision(decision_id);  -- D4
```

SQLite refuses all three. Verified on this machine (SQLite 3.45.1 / CPython 3.11.9): each raises
`Cannot add a NOT NULL column with default value NULL`. D3's third column
(`restriction_bits INTEGER NOT NULL DEFAULT 0`) executes fine. **This is a presentation defect, not
a design defect, and D5 corrects it without changing one semantic:** all four columns ship inside
`0001_init.sql`'s base `block` and `work` definitions, so a fresh install never runs an `ALTER`;
the upgrade path for a pre-existing store is `ADD COLUMN … NOT NULL DEFAULT ''` (resp. `DEFAULT 0`)
followed by a resumable backfill migration, with the `CHECK` installed by SQLite's documented
12-step table rebuild. The column names, types, defaults and meanings are exactly as D3 and D4
wrote them, and `block_restricted` stays a partial index on `restriction_bits <> 0`.

**C3 — store path and extension.** D1's `omniweave.toml.example` sets
`[store] path = ".omniweave/index.db"`; D2 names the format `.owstore`. D5 keeps D1's config key
and changes the *default value* to `".omniweave/index.owstore"`, accepting any path.

**A non-conflict I want on the record.** D1 bans "a long-lived local IPC daemon for parsing,
embedding or indexing" and then pre-authorises the escape: "if a later decision needs one it is a
unix socket or named pipe at 0600, never a loopback port." I do **not** take the escape. §11
declines LEANN's embedding daemon on operational-cost grounds, not on ruling grounds, and the door
D1 left open stays open for whoever wants to argue it later.

---

## 1. Invariants (S1–S22)

An invariant with no enforcer is a comment. The right-hand column is the load-bearing one.

| # | Invariant | Enforced by |
|---|---|---|
| **S1** | `omniweave_core.store` is the only module that calls `sqlite3.connect`. | D1's lint rule inherited verbatim, as a semgrep rule in `tools/semgrep/omniweave.yaml`; plus a test that imports every first-party module with `sqlite3.connect` monkeypatched to raise, and asserts nothing outside `store/` trips it. |
| **S2** | **One query = one read snapshot.** Every channel and the final row fetch run inside a single `BEGIN DEFERRED` on one connection. | Channel functions take `Snapshot`, never `Store` and never `Connection` — a type-level constraint checked by pyright. A test opens a query, commits a full re-index from a second process between channel 1 and channel 5, and asserts the result is identical to the uncontended run. This is the most commonly botched detail in hybrid retrieval and in WAL it is free. |
| **S3** | No transaction ever spans `main` and the attached `vec` database. | SQLite's atomic-commit-across-attached-databases guarantee **does not hold in WAL mode**. The vector writer owns its own connection; a test greps every `BEGIN`-scoped statement group for a `vec.` reference alongside a `main.` write. |
| **S4** | A vector hit is trusted only if its `content_digest` is present in the current snapshot; a stale vector is invisible, never wrong. | The similarity channel's only exit is an inner join `vec.vseg.digests[i] = block.content_digest` through `block_cdig_all`. There is no code path that returns a vector hit without it. Sweeps are an optimisation, not a correctness mechanism. |
| **S5** | `state == "absent"` is the **only** value that licenses an absence claim, and it requires all twelve gates of §8 to pass. | `build_verdict()` is the sole constructor of `Verdict`; `Verdict.state` has no setter; serve's citation path branches on `state == absent` and nothing else — so a new hazard is expressed by forcing `degraded`, never by adding a second rule to keep in sync. |
| **S6** | `fuse()` and `ceiling()` resolve channel weights through one shared `_channel_weight()`. | A perfect-consensus property test: build N channels in which one id is rank 1 in all of them and assert `fuse()[0].score == ceiling()` to 1e-12. A ceiling that drifts from the scorer silently rescales every confidence number in the product. |
| **S7** | Every channel returns a **total order**, tie-broken on `(-score, block_id)`. | A property test shuffles each channel's SQL row order 100× and asserts an identical fused ranking; `ChannelResult.__post_init__` asserts `ranked_ids` is duplicate-free. |
| **S8** | `candidate_ids is None` (no restriction) is distinct from `frozenset()` (restrict to nothing). | The type is `frozenset[int] \| None`; semgrep bans `if candidate_ids:` under `retrieve/`; a regression test asserts a nonsense query with an empty candidate set returns zero rows rather than the corpus ranked by centrality. |
| **S9** | A channel failure is `unavailable` + `degraded`, never an empty result. | No bare `except` under `retrieve/` (semgrep). `ChannelResult.outcome` is `ok \| off \| unavailable` with a required `reason` on the latter two. A fault-injection test corrupts the FTS5 index and asserts the response is `degraded`, not a confident zero. |
| **S10** | An operator's re-index replaces only rows whose `origin_operator` is its own. | `origin_operator NOT NULL` on every derived row — D2 already requires it on `block` and `rel`; D5 adds it to `anchor`, `term_ref` and `xref`. Every eviction statement under `store/` is filtered on it, checked by a grep gate over `DELETE FROM`. |
| **S11** | An incremental index converges to the same state as a full rebuild. | `gate_convergence.py`: index a 200-document fixture corpus incrementally in 40 batches, index it fully into a second store, diff **every table** modulo `block_id` and timestamps. Runtime invariant I5. codegraph measured **4.3% of distinct edges wrong, in both directions, silently, forever** without the equivalent pass. |
| **S12** | Every shipped index is used, and every hot query's plan is reviewed. | `tools/indexes.toml` names each index, the statement that uses it, and the row-count regime. `omniweave store explain --golden` renders `EXPLAIN QUERY PLAN` for all shipped statements into `schema/expected/query-plans.txt`, byte-diff gated exactly like D1's G6. A plan regression appears in a PR diff instead of in a support ticket. |
| **S13** | Every migration declares its cost class, whether it backfills, and **what an un-backfilled row means to a reader**. | `migration.unbackfilled_means TEXT NOT NULL` — required prose that `omniweave doctor` prints verbatim. A migration whose estimated row-touch exceeds `WATCHDOG_MS / 2` must set `resumable = 1` and execute through the `work` table; the loader refuses otherwise. |
| **S14** | The store is never committed to a repository. | `omniweave init` writes `.omniweave/*.owstore*` and `.omniweave/*.vec.db*` into `.gitignore`; `omniweave doctor` fails with `OW-S-070` if `git ls-files` reports a tracked store. The committable artefact is the text projection of §15. |
| **S15** | Safety and resource caps are constants; policy may clamp below, never above. | `retrieve/limits.py` exports `MAX_*`; every load computes `effective = min(policy, MAX_*)`; a test sets each knob above its constant and asserts the constant wins. D1: *"Limits are a ceiling, not a setting."* |
| **S16** | Dropping any channel changes the **verdict**, never the honesty of the answer. | `IndexCapabilities` is three-valued per channel; a test drops the vector sidecar, then `anchor`, then the FTS index, and asserts the response stays well-formed with the right channel state and the right gate firing. |
| **S17** | Rows withheld by a licence filter are disclosed. | Gate 10. `restriction_bits` narrowing is a *counted* filter and `verdict.withheld.restricted` is non-zero whenever it fired. D3-17 makes restrictions travel; D5 makes their effect on retrieval visible, because a licence filter that looks like absence is the worst possible failure of both systems at once. |
| **S18** | A read never perturbs freshness. | D1's `connect_readonly` ladder inherited verbatim (`mode=ro` when a WAL sidecar exists, `mode=ro&immutable=1` when it does not); freshness derives from `work` and `doc_head` rows, never from file mtimes; a test asserts a query does not change `st_mtime_ns` of the store file. |
| **S19** | `scorer_version` and `plan_digest` appear on every response and every `retrieval_event` row. | Constructor-required fields plus the golden-output CLI test. *"0.8 under scorer v1" is a measurable statement; "0.8" is not.* |
| **S20** | `block_id` is globally unique across every shard of a fabric, forever, without coordination. | The 16-bit minting-shard prefix (§4), a `CHECK ((block_id >> 48) = :shard_ord)` on every shard's `block` table, and an append-only `shard_registry` in which an ordinal is never reused. |
| **S21** | A query never reads a superseded generation unless it asks. | `block_fts` and every index-layer table hold **current-generation, live, text-bearing blocks only**; the `rebind` pass deletes superseded rows in the same transaction that advances `doc_head`. Historical generations are reachable only through the explicit `--gen` path, documented as slower and non-FTS. |
| **S22** | The published read schema is a versioned contract. | `schema/store-v1.sql` is generated from `store/schema.sql` plus migrations, committed, and byte-diff gated. `omniweave-conform`'s `store_readonly` suite runs the full retrieval golden suite against a connection opened `mode=ro` on a copy, so any read requiring a temp table, a custom SQL function, or a write fails CI. Breaking the schema is a `SCHEMA` major bump with a two-release deprecation window. |

---

## 2. Concrete shape

### 2.1 Three artefacts, one directory

```
.omniweave/                          # cache_root; NEVER inside source_root (D1 startup error)
├── index.owstore                    # main: L2 blocks + L4 indexes + work + route. THE file.
├── index.owstore-wal                #   healed at open above 64 MB (25.6 GB observed, codegraph)
├── index.owstore-shm
├── index.vec.db                     # ATTACHed as `vec`. Optional. Separately deletable.
├── index.vec.db-wal
├── cas/ab/cd/<sha256>               # blobs: retained `part` bytes, `asset` bytes, page renders
├── jobs/<run_id>/…                  # D1's toolchain job directories
└── portable/                        # the committable TEXT projection (§15). Opt-in.
    ├── manifest.json
    └── d/<doc_key[:2]>/<doc_key>.ndjson.zst

Three artefacts, three lifecycles, one directory. `rm -rf .omniweave` is a supported, documented,
lossless operation, and every decision below is subordinate to keeping that sentence true.
```

### 2.2 Pragmas and the connection ladder

```python
# omniweave_core/store/pragmas.py — THE only place these appear.
INIT_PRAGMAS = (                       # persistent, per FILE; applied at create and at heal
    "journal_size_limit = 67108864",   # 64 MB == WAL_HEAL_THRESHOLD_BYTES
)
CONN_PRAGMAS = (                       # per CONNECTION, IN THIS ORDER
    "busy_timeout = 5000",             # FIRST. journal_mode before this crashes a contended
                                       #   open (codegraph #238). D2 already fixed the order.
    "foreign_keys = ON",
    "journal_mode = WAL",
    "synchronous = NORMAL",
    "cache_size = -64000",             # 64 MB page cache
    "temp_store = MEMORY",
    "mmap_size = 268435456",           # 256 MB
)
# jcodemunch's INIT/CONN split, taken. codegraph's ordering and values, taken verbatim.

def connect_readonly(path: Path) -> sqlite3.Connection:
    """D1's ladder, verbatim. Opening a WAL database `mode=ro` CREATES the -wal/-shm sidecars
    and moves the mtime a freshness check reads; `immutable=1` against a LIVE WAL raises
    'no such table', and a caller mapping that to 'no embeddings' states a FALSE ABSENCE
    about a corpus that was just embedded."""
    if path.with_name(path.name + "-wal").exists():
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    return sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)

# Two named wait budgets, passed per call, never a module constant. (jcodemunch repeats
# wait_seconds=60.0 at four call sites while its own comments call a 60 s wait the outcome
# to avoid.)
INTERACTIVE_WAIT_MS = 2_000    # a query, a hook, an MCP call
BATCH_WAIT_MS       = 60_000   # an index run, a migration, a compaction
```

### 2.3 Four protocols, disjoint jobs

```python
# ── omniweave_core/store/protocol.py ─────────────────────────────────────────────
# D1 promised `Store` would stay four methods and it does: RETRIEVAL IS A SEPARATE
# PROTOCOL, so the distribution boundary never grows a read API.

class Store(Protocol):
    """The T1/T2/T3 distribution boundary. EXACTLY mine-runtime.md §7.10.2's four methods.
    Nothing is ever added here."""
    def claim(self, batch: int, gen: int, worker: str, lease_ms: int) -> Sequence[WorkRow]: ...
    def complete(self, row_id: int, gen: int, result: StepResult) -> bool: ...  # False ⇒ superseded
    def reap_expired_leases(self, now_ms: int) -> int: ...
    def counts_by_status(self) -> Mapping[str, int]: ...

class Index(Protocol):
    """The RETRIEVAL boundary. Six methods. A Postgres/T3 backend implements this."""
    def snapshot(self) -> ContextManager["Snapshot"]: ...
    def capabilities(self) -> "IndexCapabilities": ...
    def channel(self, spec: "ChannelSpec", snap: "Snapshot") -> "ChannelResult": ...
    def fetch(self, ids: Sequence[BlockId], snap: "Snapshot") -> Sequence["Hit"]: ...
    def coverage(self, scope: "NarrowSpec", snap: "Snapshot") -> "Coverage": ...
    def stats(self) -> Mapping[str, int]: ...

class VectorIndex(Protocol):
    """The ANN Backend seam — D3 reserved the word `Backend` for D5 and this is it. Four
    methods, because four methods is what a third party can implement in an afternoon.
    Reference implementations: `vector.sqlite.brute` (first-party, stdlib) and
    `vector.usearch` (separate repo, CI-tested against the same conformance suite)."""
    def manifest(self) -> "VecManifest": ...
    def upsert(self, model_key: str,
               rows: Iterable[tuple[bytes, bytes, bytes | None]]) -> int: ...   # (digest, sig, full)
    def search(self, model_key: str, q_sig: bytes, q_full: bytes | None, *, k: int,
               candidate_digests: frozenset[bytes] | None) -> Sequence[tuple[bytes, float]]: ...
    def sweep(self, live: Callable[[], Iterable[bytes]]) -> int: ...

# D2's DocSink is the write protocol and is unchanged. There is no fifth protocol.

@dataclass(frozen=True, slots=True)
class Snapshot:
    """One WAL read transaction, held for the whole query. NOT thread-safe by construction:
    one Snapshot, one connection, one query."""
    conn: "sqlite3.Connection"   # the ONLY place a Connection is visible outside store/
    generation: int              # index_state['generation'] as of BEGIN
    corpus_id: str
    schema: int
    vec_attached: bool
    opened_ns: int

@dataclass(frozen=True, slots=True)
class IndexCapabilities:
    lexical:    Literal["ok", "off", "unavailable"]
    exact:      Literal["ok", "off", "unavailable"]
    identity:   Literal["ok", "off", "unavailable"]
    structural: Literal["ok", "off", "unavailable"]
    similarity: Literal["ok", "off", "unavailable"]
    reason:     Mapping[str, str]     # required for every non-"ok" entry
    # "off" is an OPERATOR CHOICE and is disclosed. "unavailable" is a DEGRADATION.
    # Collapsing those two is how a RAG system reports a model's silence as a corpus fact.
    blocks: int; documents: int; vec_model_key: str | None; scorer_version: int
```

### 2.4 DDL — the index layer (`0002_index.sql`), additive to D2's `.owstore`

```sql
-- ════════ omniweave L4. Every object here is DERIVED and REBUILDABLE. SCHEMA = 1. ════════
-- D2's tables are untouched except where §0/C2 corrects a defective ALTER.

-- ---- generation head ------------------------------------------------------------------
-- D2 gives every (doc_key, gen) its own doc_ord, so "the current document" is a MAX() over
-- doc_key. A correlated MAX per query is unaffordable at 10M documents. This is that index.
CREATE TABLE doc_head (
  doc_key       BLOB    PRIMARY KEY,
  doc_ord       INTEGER NOT NULL REFERENCES doc(doc_ord) ON DELETE CASCADE,
  gen           INTEGER NOT NULL,
  indexed_at_ns INTEGER NOT NULL,
  block_count   INTEGER NOT NULL DEFAULT 0
) WITHOUT ROWID;
CREATE INDEX doc_head_ord ON doc_head(doc_ord);

-- ---- lexical channel -------------------------------------------------------------------
-- D2 declares block_fts and delegates: "D5 owns the BM25 weights."
-- D5 declares it BYTE-FOR-BYTE AS D2 WROTE IT, and here is why, measured on this machine
-- (SQLite 3.45.1, 1,000,000 synthetic 75-word blocks, 20k-word random vocabulary):
--       option                FTS index    build     single-term p50
--       (none)                  290 MB      54 s          31.8 ms
--       prefix='2 3'            770 MB     155 s          39.2 ms
-- A 2.65x index and a 2.9x build for a query that is already 32 ms is not a trade I will
-- make on an operator's behalf. `term*` still works without a prefix index (FTS5 scans the
-- term-index range); the prefix index only accelerates it. `[retrieval] fts_prefix = "2 3"`
-- exists for someone who measures their own corpus and wants it.
CREATE VIRTUAL TABLE block_fts USING fts5(
  text, content='block', content_rowid='block_id',
  tokenize='unicode61 remove_diacritics 2');
-- Triggers: D2's three, with the two guards D2's sketch omits (tombstones and NULL text).
CREATE TRIGGER block_fts_ai AFTER INSERT ON block
  WHEN NEW.state = 0 AND NEW.text IS NOT NULL
  BEGIN INSERT INTO block_fts(rowid, text) VALUES (NEW.block_id, NEW.text); END;
CREATE TRIGGER block_fts_ad AFTER DELETE ON block WHEN OLD.text IS NOT NULL
  BEGIN INSERT INTO block_fts(block_fts, rowid, text)
        VALUES ('delete', OLD.block_id, OLD.text); END;
CREATE TRIGGER block_fts_au AFTER UPDATE ON block BEGIN
  INSERT INTO block_fts(block_fts, rowid, text) VALUES ('delete', OLD.block_id, OLD.text);
  INSERT INTO block_fts(rowid, text) SELECT NEW.block_id, NEW.text
    WHERE NEW.state = 0 AND NEW.text IS NOT NULL;
END;
-- The 'delete' command-row idiom is the mandatory external-content ritual; get it wrong and
-- the index silently accumulates ghosts (codegraph §3.2 item 4).
-- Single-column table ⇒ `bm25(block_fts)` needs no weights. Field weighting is NOT done here
-- (see the heading trick in §5); a second copy of every block's text is not on the table.

-- ---- exact / reference channel: the document analogue of codegraph's LIKE channel --------
-- FTS5's unicode61 tokenizer destroys precisely the tokens a document reader searches for:
--   '§4.2(b)' -> 4 · 2 · b     'ISO-8601' -> iso · 8601     'GL-4471' -> gl · 4471
-- codegraph's rule generalises: WHEN THE TOKENIZER IS THE CONSTRAINT, ADD A CHANNEL.
CREATE TABLE term_ref (
  norm     TEXT    NOT NULL,      -- NFKC + casefold + punctuation-class collapse. Lookup key.
  surface  TEXT    NOT NULL,      -- '§ 4.2(b)' as written. Displayed; never matched.
  kind     TEXT    NOT NULL,      -- section|clause|figure|table|equation|citekey|identifier|
                                  -- defined_term|footnote|exhibit
  block_id INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  a INTEGER NOT NULL, b INTEGER NOT NULL,          -- D2's TextSpan into block.text
  role     TEXT    NOT NULL CHECK (role IN ('definition','reference')),
  origin_operator TEXT NOT NULL,                   -- S10
  PRIMARY KEY (norm, block_id, a, role)
) WITHOUT ROWID;
CREATE INDEX term_ref_block ON term_ref(block_id);
CREATE INDEX term_ref_kind  ON term_ref(kind, norm);
-- MAX_TERM_REFS_PER_BLOCK = 32; a breach emits Diag(OW_TERMREF_TRUNCATED) and is counted.

-- ---- identity / resolution: codegraph's definitionDelta, translated to documents ---------
CREATE TABLE anchor (            -- the corpus-wide RESOLVABLE-NAME table
  norm     TEXT    NOT NULL,
  kind     TEXT    NOT NULL,
  block_id INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  doc_ord  INTEGER NOT NULL,
  origin_operator TEXT NOT NULL,
  PRIMARY KEY (norm, kind, block_id)
) WITHOUT ROWID;
CREATE INDEX anchor_lookup ON anchor(norm, kind, doc_ord);

-- codegraph's `unresolved_refs` table with a pending/failed status lifecycle becomes a VIEW,
-- because our resolution is by NORMALISED STRING rather than by scope-aware name resolution:
-- the retry is then always correct, never stale, and there is no status column to get wrong.
CREATE VIEW xref_unresolved AS
  SELECT r.norm, r.kind, r.block_id, r.a, r.b
  FROM term_ref r
  WHERE r.role = 'reference'
    AND NOT EXISTS (SELECT 1 FROM anchor d WHERE d.norm = r.norm AND d.kind = r.kind);
-- "the corpus grew and now this citation resolves" is a bounded query, not a re-index.
-- `omniweave store residue` prints it grouped by norm — the residue is data, not a log line.

CREATE TABLE xref (              -- resolved cross-document references
  src_block_id INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  dst_block_id INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  norm TEXT NOT NULL, kind TEXT NOT NULL,
  ambiguous INTEGER NOT NULL DEFAULT 0,   -- >1 anchor matched: kept, ranked down, NEVER dropped
  trust INTEGER NOT NULL,                 -- D2's Trust ordinal; absent ⇒ 0 (ambiguous)
  origin_operator TEXT NOT NULL,
  PRIMARY KEY (src_block_id, dst_block_id, norm, kind, origin_operator)
) WITHOUT ROWID;
CREATE INDEX xref_dst ON xref(dst_block_id, kind);
-- Identity in the SCHEMA, or INSERT OR IGNORE is a plain INSERT with nothing to conflict on
-- (codegraph #1034: byte-identical duplicate rows that inflated counts and flowed into
-- callers). Nullable identity columns are NOT NULL DEFAULT '' or IFNULL-folded.

-- ---- structural channel: sections as a prefix-range index --------------------------------
-- This is NOT a re-litigation of D2's rejected `ord_path`. That proposal would have REPLACED
-- `ord` as the representation of reading order. `block_sec` is a derived, rebuildable index
-- over the section hierarchy: it holds no identity, no ordering authority, and
-- `omniweave store rebuild --sec` recreates it from `parent_id` + `rel(heading_of)`.
CREATE TABLE block_sec (
  block_id  INTEGER PRIMARY KEY REFERENCES block(block_id) ON DELETE CASCADE,
  sec_id    INTEGER NOT NULL,          -- the nearest heading/section block
  sec_depth INTEGER NOT NULL,
  sec_path  TEXT    NOT NULL           -- '/1/4/2' — "everything under §4.2" is a prefix range
) WITHOUT ROWID;
CREATE INDEX block_sec_path ON block_sec(sec_path, block_id);
CREATE INDEX block_sec_sec  ON block_sec(sec_id);
-- D2 ships block_parent(parent_id, ord) and rel_dst(dst_id, kind). D5 adds the missing half:
CREATE INDEX rel_src ON rel(src_id, kind);

-- Optional, OFF by default: a CAPPED 2-hop closure over a NAMED, SMALL relation set.
-- Not a graph engine, not general reachability. See §12.
CREATE TABLE reach (
  src INTEGER NOT NULL, dst INTEGER NOT NULL, kind TEXT NOT NULL, hops INTEGER NOT NULL,
  PRIMARY KEY (src, kind, dst)
) WITHOUT ROWID;
CREATE INDEX reach_dst ON reach(dst, kind);
-- MAX_REACH_ROWS = 20 * block_count. A breach TRUNCATES the table, stamps reach_enabled = 0,
-- falls traversal back to the recursive CTE, and reports the fallback in degradations[] on
-- every affected response. A governor that cannot help must get out of the way (I9).

-- ---- similarity joins on content_digest, so it needs the corpus-wide index ---------------
-- D2 ships block_cdig ON block(doc_ord, content_digest) for rebind. Retrieval needs this one.
CREATE INDEX block_cdig_all ON block(content_digest, block_id) WHERE state = 0;

-- ---- freshness, coverage, and the racily-clean stat fastpath -----------------------------
CREATE TABLE unit_stat (
  unit_uri       TEXT    NOT NULL,
  salt           TEXT    NOT NULL,   -- keyed by SALT, not by path: one file hashed under two
  size           INTEGER NOT NULL,   --   roots in one run must not poison the index (#1989)
  mtime_ns       INTEGER NOT NULL,
  indexed_at_ns  INTEGER NOT NULL,   -- ★ captured BEFORE the content read
  content_digest BLOB    NOT NULL,
  derived        TEXT    NOT NULL DEFAULT '{}',  -- page_count, media_type, needs_ocr:
  PRIMARY KEY (unit_uri, salt)                   -- co-located, so ONE invalidation clears all
) WITHOUT ROWID;
-- stat_fresh(rec, st) := rec.size == st.st_size
--                    AND rec.mtime_ns == st.st_mtime_ns
--                    AND st.st_mtime_ns + MTIME_GRANULARITY_NS <= rec.indexed_at_ns
-- MTIME_GRANULARITY_NS = 2e9. Without the third clause an agent writing files inside one
-- mtime tick — the actual workload — is invisible forever. One column buys the property.
-- Staging is codegraph's: stat gates hash gates parse, each one gating the next.

CREATE TABLE ingest_scope (      -- jcodemunch's index_coverage_meta, as a table
  scope_id      TEXT PRIMARY KEY,
  discovered    INTEGER NOT NULL, indexed INTEGER NOT NULL, skipped INTEGER NOT NULL,
  skipped_why   TEXT    NOT NULL DEFAULT '{}',   -- {"too_large":12,"unsupported":3,"cap":1975}
  scanned_at_ns INTEGER NOT NULL,
  complete      INTEGER NOT NULL   -- 0 ⇒ the SCAN ITSELF was partial.
);
-- An ABSENT row means "coverage unknown", never "nothing was excluded". A user once received
-- confident zero-results over ~1,975 unindexed files and left; this table is that gate's input.

-- ---- index state, and the FTS build flag-pair (LEANN's lesson, BOTH halves) --------------
CREATE TABLE index_state (k TEXT PRIMARY KEY, v TEXT NOT NULL);
-- generation · corpus_id · scorer_version · fts_state ∈ {ok, building, stale} · reach_enabled
-- · vec_model_key · last_full_index_ns · wal_baseline_bytes · shard_ord
-- ★ fts_state = 'building' at open ⇒ the lexical channel is `unavailable` with OW-S-041
--   naming `omniweave store repair --fts`. LEANN corrects its illegal BUILD combination in
--   code and leaves the illegal SEARCH combination as a README sentence — a footgun that
--   returns silently wrong results. Validate from the stamped state, at open, every time.

-- ---- migrations, with the operator-facing columns ----------------------------------------
CREATE TABLE migration (
  version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at_ns INTEGER NOT NULL,
  cost_class TEXT NOT NULL CHECK (cost_class IN ('ddl','backfill','rebuild')),
  resumable INTEGER NOT NULL,
  backfill_done INTEGER NOT NULL DEFAULT 0, backfill_total INTEGER,
  unbackfilled_means TEXT NOT NULL     -- REQUIRED PROSE. `omniweave doctor` prints it verbatim.
);

-- ---- retrieval telemetry: one row per query. REIMPLEMENTED from mine-graph.md §4.7. -------
CREATE TABLE retrieval_event (
  event_id INTEGER PRIMARY KEY,
  ts_ns INTEGER NOT NULL, tool TEXT NOT NULL, query_hash TEXT NOT NULL, query TEXT,
  plan_digest TEXT NOT NULL, scorer_version INTEGER NOT NULL,
  producer_version TEXT NOT NULL,    -- ★ on EVERY row, so a later bug fix never needs a
                                     --   ledger-trust pass to decide which rows to believe
  channels TEXT NOT NULL,            -- JSON {"lexical":"ok","similarity":"off",...}
  verdict_state TEXT NOT NULL, degraded_because TEXT NOT NULL DEFAULT '[]',
  returned_n INTEGER NOT NULL, matches_before_packing INTEGER NOT NULL,
  best_score REAL, score_ceiling REAL, top1 TEXT, top2 TEXT, gap REAL,
  corpus_freshness TEXT NOT NULL, snapshot_gen INTEGER NOT NULL,
  latency_ms INTEGER NOT NULL, channel_ms TEXT NOT NULL DEFAULT '{}',
  shards_contributed TEXT            -- '3 of 4' when federated; NULL for a single store
);
CREATE INDEX retrieval_event_ts  ON retrieval_event(ts_ns);
CREATE INDEX retrieval_event_bad ON retrieval_event(ts_ns) WHERE verdict_state <> 'ok';
-- Written on a SEPARATE write connection through a bounded in-memory queue (cap 4096,
-- drop-oldest with a counter), flushed on a 2 s timer and at process exit — NEVER inside the
-- read snapshot and NEVER on the response path. Telemetry that can slow a query is telemetry
-- that gets turned off. Retention 90 days, swept by `omniweave store gc`.

-- ---- inherited, placed here so nobody invents a second copy -------------------------------
-- D3: driver_card_cache · driver_observation · resolution_report                    (verbatim)
-- D4: route_decision · route_unit_decision · route_evidence · route_signal ·
--     route_spend · route_verdict · route_pin + the route_scoreboard VIEW           (verbatim)
-- D4's retention policy (evidence 30 d, decisions 400 d, never sweeping audit-selected,
-- pinned, degraded, or REGRESSED-slice rows) is implemented by `omniweave store gc`, which
-- is the ONLY writer permitted to delete a route row.
```

### 2.5 DDL — the vector sidecar (`vec`)

```sql
-- ════════ .omniweave/index.vec.db, ATTACHed as `vec`. Optional. Deletable. ════════
CREATE TABLE vec_manifest (k TEXT PRIMARY KEY, v TEXT NOT NULL);
-- LEANN's meta.json portability contract as rows, plus the two things LEANN omits:
--   corpus_id      MUST equal main.index_state.corpus_id or the sidecar is IGNORED, not read
--   store_schema   the SCHEMA int it was built against
-- and the identity that matters:
--   model_key = sha256(canonical{model_id, model_rev, dims, metric, normalize,
--                                prompt_template_digest, driver, driver_schema_v})[:16]
--   model_id · model_rev (an exact sha; "main" is a load error, D4-R14) · dims · metric ·
--   normalize · prompt_template_digest · driver · driver_version ·
--   storage_mode ∈ {sig_only, sig_full} · sig_bits · built_at_ns · rows
-- ★ Prompt templates are applied ONCE, client-side, before embedding, and are IN model_key.
--   LEANN's double-templating guard, made structural instead of procedural.

-- Signatures live in CONTIGUOUS, APPEND-ONLY SEGMENTS, never one row per block. Measured on
-- this machine: scanning 1,000,000 96-byte signatures one row at a time costs 1072 ms; the
-- same data in 4096-signature segments costs 466 ms. SQLite cursor overhead, not arithmetic,
-- is the dominant cost, and a row-per-vector layout is the mistake that hides it.
CREATE TABLE vseg (
  model_key TEXT NOT NULL, seg_no INTEGER NOT NULL,
  n       INTEGER NOT NULL,
  digests BLOB NOT NULL,     -- n * 16 bytes: D2's blake3-128 content_digest, sorted
  sigs    BLOB NOT NULL,     -- n * (sig_bits/8) bytes, same order
  live    BLOB NOT NULL,     -- ceil(n/8) byte bitmap; a swept row clears its bit
  PRIMARY KEY (model_key, seg_no)
);
CREATE TABLE vfull (         -- present only when storage_mode = 'sig_full'
  model_key TEXT NOT NULL, content_digest BLOB NOT NULL,
  v BLOB NOT NULL,           -- dims * 4 bytes, float32 LE
  PRIMARY KEY (model_key, content_digest)
) WITHOUT ROWID;
CREATE TABLE vpending (      -- the re-embed set, MATERIALISED so it is a scan, not an anti-join
  model_key TEXT NOT NULL, content_digest BLOB NOT NULL, chars INTEGER NOT NULL,
  PRIMARY KEY (model_key, content_digest)
) WITHOUT ROWID;
```

**Keyed on `content_digest`, not `block_id`. This settles D2's open question**, and the reason is
D2's own digest recipe. `content_digest` excludes geometry, spans, `producer_id`, `marks` and `x`,
so: (a) a driver upgrade with bbox jitter re-embeds nothing; (b) a formatting-only fix does not
re-bill an embedding — D2's recipe says so in its own comment; (c) five thousand identical running
headers share one vector row for free; (d) after `rebind`, the re-embed set is exactly
`{digests now live} \ {digests already embedded}`, one anti-join that never touches a `block_id`
and that is correct whether `rebind` carried the id or not. This is LEANN's
`passage_id_scheme ∈ {sequential, content_hash}` fork resolved to `content_hash`, with D2's digest
as the hash. The cost is named and capped: expanding one digest back to its blocks is a fan-out,
bounded by `MAX_DIGEST_FANOUT = 8`, and `verdict.collapsed_duplicates` reports what was elided.

### 2.6 Retrieval types

```python
# ── omniweave_core/retrieve/ ──────────────────────────────────────────────────────
Scalar = str | int | float | bool | None

@dataclass(frozen=True, slots=True)
class NarrowSpec:
    """Filters NARROW; channels SCORE WITHIN the narrowed set. Pushed into EVERY channel,
    including the vector one — LEANN post-filters an ANN result with no over-fetch, which is
    silent recall loss shaped exactly like absence."""
    doc_keys: frozenset[bytes] | None = None
    uri_prefix: str | None = None
    kinds:  frozenset[str] | None = None
    layers: frozenset[str] = frozenset({"body"})     # D2's Layer
    pages:  tuple[int, int] | None = None
    sec_path_prefix: str | None = None
    lang: str | None = None
    trust_min: int = 0                               # D2's Trust ordinal
    quote_min: str | None = None                     # 'verbatim' for a citation request
    restriction_mask: int = 0                        # D3 Restriction bits to EXCLUDE
    gen: Literal["head"] | int = "head"              # S21
    def selectivity(self, stats) -> float: ...       # drives the vector over-fetch factor

@dataclass(frozen=True, slots=True)
class Query:
    raw: str = ""
    terms: tuple[str, ...] = ()      # sanitised (see the transform below)
    refs:  tuple[str, ...] = ()      # reference-shaped: '§4.2(b)', 'Fig. 3', 'GL-4471', 'd7#412'
    narrow: NarrowSpec = NarrowSpec()
    k: int = 20
    mode: Literal["find", "cite", "explore", "prove_absent"] = "find"
    channels: frozenset[str] | None = None   # None ⇒ the planner decides
    max_blocks: int | None = None; max_chars: int | None = None

@dataclass(frozen=True, slots=True)
class ChannelSpec:
    name: Literal["lexical","exact","identity","structural","similarity"]
    weight: float; limit: int; budget_ms: int
    args: Mapping[str, Scalar] = MappingProxyType({})

@dataclass(frozen=True, slots=True)
class QueryPlan:
    plan_digest: str
    channels: tuple[ChannelSpec, ...]   # ordered CHEAPEST FIRST; the order IS the run order
    narrow: NarrowSpec
    fuse: "FusionSpec"                  # k, weights, ceiling
    pack: "PackSpec"
    gates: tuple[str, ...]              # which absence gates apply to THIS plan
    short_circuit: str | None           # e.g. "identity>=50 and mode=cite"
    scorer_version: int; policy_digest: str

def plan(q: Query, caps: IndexCapabilities, pol: "RetrievalPolicy") -> QueryPlan: ...
    # PURE. No clock, no RNG, no I/O, no store, no RunContext. Memoised on
    # (mode, channels, narrow-field set, policy_digest, caps_digest).
    # Same purity discipline, and the same semgrep rules, as D4's evaluate().

@dataclass(frozen=True, slots=True)
class ChannelResult:
    name: str
    outcome: Literal["ok", "off", "unavailable"]
    ranked_ids: tuple[BlockId, ...]     # ONLY blocks that MATCHED. Total order guaranteed.
    grades: Mapping[BlockId, str] = ... # identity channel: the tier it ACTUALLY measured
    raw:    Mapping[BlockId, float] = ...  # debug only; never fused
    reason: str = ""                    # REQUIRED when outcome != "ok"
    ran_ms: int = 0
    truncated_at_limit: bool = False    # ★ feeds absence gate 9

@dataclass(frozen=True, slots=True)
class FusedHit:
    block_id: BlockId
    score: float
    channel_contributions: Mapping[str, float]
    channel_ranks: Mapping[str, int]
    # A fusion function that returns only a score is a fusion function you cannot tune.

def fuse(channels, *, k: int = 60, weights) -> list[FusedHit]: ...
def ceiling(channels, *, k: int = 60, weights) -> float: ...
#   score(s) = Σ_c  w_c / (k + rank(c, s))         ceiling = Σ_c w_c / (k + 1)
#   Weights are NOT normalised to 1, so the ceiling DEPENDS ON WHICH CHANNELS RAN. Never
#   hardcode 1/(k+1). fuse() and ceiling() share _channel_weight() (S6).
#   weight=None ⇒ named default ⇒ 1.0.  weight=0.0 is a MEANING, not an absence.
```

### 2.7 `omniweave.toml` — the operator's whole retrieval surface

```toml
[store]
backend      = "sqlite"                # sqlite (shipped) | postgres (T3) | fabric (T4)
path         = ".omniweave/index.owstore"
synchronous  = "normal"                # normal | full — see §9 on the re-bill window
wal_valve_mb = 0                       # 0 = auto: clamp(db_bytes/4, 256 MB, 2 GB)

[retrieval]
vectors    = "off"                     # off | on.  THE DEFAULT IS OFF. See §11.
scorer     = 1                         # scorer_version; bumped when ANY formula changes
fusion_k   = 60
fts_prefix = ""                        # "" = no prefix index (measured 2.65x size; §2.4)
event_log  = true                      # retrieval_event, 90-day retention

[retrieval.weights]                    # per-KEY validation with per-KEY fallback; never
identity   = 2.0                       # all-or-nothing, and a bad key warns and keeps default
exact      = 1.2
lexical    = 1.0
similarity = 0.8
structural = 0.4
# ceiling, all five channels: 5.4/61 = 0.0885 ; without similarity: 4.6/61 = 0.0754

[retrieval.budget]
query_ms   = 250                       # D1 gate G10: "omniweave query, warm store <= 250 ms"
channel_ms = { lexical = 60, exact = 40, identity = 20, structural = 60, similarity = 120 }
overfetch  = 5                         # codegraph's 5x-before-rerank, as a knob
max_blocks = 60
max_chars  = 24000

[retrieval.vectors]
model_key  = ""                        # empty ⇒ adopt vec_manifest's. A MISMATCH is gate 12.
backend    = "vector.sqlite.brute"     # an `omniweave.backends` entry-point name
storage    = "auto"                    # auto | sig_only | sig_full — stamped, validated at open
max_blocks = 250000                    # the stdlib backend's MEASURED ceiling. Above it,
                                       # REFUSE with OW-S-052 naming the remedy. Never a
                                       # silent five-second query.

[retrieval.policy]
path = "retrieval.toml"                # D4's rule grammar, verbatim. One policy language.
                                       # Layers: builtin < site < project < profile < request.
```

### 2.8 A worked `omniweave query explain`

```
$ omniweave query explain "what does §4.2(b) say about retention" --need quote=verbatim

plan sha256:8c31…  policy sha256:44ab…  scorer v1  caps sha256:d0f1…

QUERY TRANSFORM  (a SEMANTIC transform, not escaping — codegraph #173)
  raw    : what does §4.2(b) say about retention
  refs   : ['§4.2(b)']                       -> exact channel, weight x2 (rule ref.boost:12)
  terms  : ["say","retention"]               -> 'what','does','about' dropped (function-word
           stoplist: they are never evidence a block was NAMED, and they poison idf)
  fts    : "say"* OR "retention"*            -> FTS5 specials and AND/OR/NOT/NEAR stripped so
                                                a user cannot inject FTS syntax
  narrow : layers={body}  gen=head  quote>=verbatim  restriction_mask=0x0  -> 41,203 of 512,880

CHANNELS (run order = cheapest first; budget 250 ms)
  exact       w 2.4   limit 100   budget 40 ms    term_ref.norm = 's4.2(b)'
  identity    w 2.0   limit  60   budget 20 ms    anchor + cite/addr grammar
  lexical     w 1.0   limit 100   budget 60 ms    bm25(block_fts) over the narrowed set
  structural  w 0.4   limit 100   budget 60 ms    heading hits -> block_sec prefix expansion
  similarity  —       OFF                         [retrieval] vectors = "off"

FUSION  weighted RRF k=60  ceiling 4.6/61 = 0.07541  (four channels; similarity did not run)
PACK    max_blocks 60  max_chars 24000  keystone-protected elision
GATES   1 timeout · 2 channel_requested_absent · 4 coverage · 5 pending_in_scope · 6 freshness
        7 parse_incomplete · 8 truncated_by_pack · 10 restricted_withheld · 11 similarity_only
        (3 index_rebuilt and 9 filter_exhausted do not apply: single store, no ANN channel)

$ omniweave query "…" --json | jq .verdict
{ "state": "degraded", "degraded_because": [
    {"gate":"parse_incomplete","detail":"3 documents in scope have diag OW_NEEDS_OCR on 41 pages",
     "fix":"omniweave parse --rung PAGE --uri s3://legal/2019/*.pdf"} ],
  "scanned": {"blocks": 41203, "documents": 118},
  "best_score": 0.0619, "score_ceiling": 0.07541, "scorer_version": 1,
  "channels": {"lexical":"ok","exact":"ok","identity":"ok","structural":"ok","similarity":"off"},
  "freshness": "fresh", "snapshot_gen": 41,
  "coverage": {"discovered": 1204, "indexed": 1204, "skipped": 0, "complete": true},
  "withheld": {"restricted": 0, "collapsed_duplicates": 0},
  "matches_before_packing": 96, "did_you_mean": ["§4.2(a)", "§4.12(b)"] }
```

`best_score 0.0619` against `ceiling 0.07541` is 82% of achievable — and without the ceiling it
reads as 0.06, i.e. "nothing found", against a BM25-shaped confidence curve. That is the bug the
ceiling exists to kill, and it is why `fuse()` and `ceiling()` ship as a pair.

---

## 3. Is SQLite the interface or the implementation?

**Both, split by direction, and the split is the whole ecosystem argument.**

**SQLite is the interface for readers.** `schema/store-v1.sql` is generated, committed, byte-diff
gated (D1's G6 mechanism), and documented as a *supported read API at the `SCHEMA` major*. A data
team opens `.omniweave/index.owstore` read-only from Go, DuckDB, Metabase, R or `sqlite3` and joins
`block` to `doc` to `route_spend` without our SDK, without a server, and without asking us. Breaking
it is a `SCHEMA` major bump with a migration and a two-release deprecation window, announced like a
`CONTRACT` bump. This is not a courtesy: it is the thing that makes an omniweave index a *corporate
asset* rather than a vendor artefact, and it is worth more to adoption than any API we could write.

**SQLite is the implementation for writers.** `omniweave_core.store` is the only module that opens
a connection (D1's lint rule, S1). The `Store` / `Index` / `VectorIndex` / `DocSink` protocols are
the backend seam. A Postgres backend is **not** required to be SQL-compatible with the SQLite one —
only *logically* compatible, proven by running the identical conformance suite against both.

**Enforcement, and the honest limitation.** `omniweave-conform`'s `store_readonly` suite runs the
full retrieval golden suite against a copy opened `mode=ro`, so any first-party read that needs a
temp table, a custom SQL function, or a write fails CI — which is what keeps the published schema
sufficient rather than merely present. The limitation I will state rather than paper over: **FTS5
`bm25()` and Postgres `ts_rank_cd()` are different scorers.** Fused scores are therefore not
comparable across backends. Consequences, all shipped: `scorer_version` includes the backend
identity; a `route_verdict` / `retrieval_event` history does not survive a backend migration and the
upgrade guide says so; and the cross-backend CI gate asserts a **rank-correlation floor** (Kendall
τ ≥ 0.90 on the 400-query golden set), never identity. Anyone who promises you identity across two
BM25 implementations has not run the comparison.

---

## 4. Identity, keys, and the one decision that cannot be deferred

D2 asked: *"Does a T3 (Postgres) tier need a different `block_id` allocation scheme? … if T3 is in
scope for v1, `block_id` becomes a 64-bit composite (shard, sequence) and that must be decided
before any FK ships."* **It must, and here it is.**

```
block_id  :=  (minting_shard_ord << 48) | sequence
              ├─ bits 63..48 : 16-bit MINTING shard ordinal, from the append-only
              │                shard_registry. Assigned ONCE at mint. Never reused.
              └─ bits 47..0  : per-shard monotonic sequence — 281,474,976,710,655 blocks

T1/T2 (one store):        shard_ord = 0, so laptop block_ids are 1, 2, 3 … and the scheme is
                          invisible. `sqlite3` output is still readable by a human.
T3/T4 (a fabric):         every shard mints under its own ordinal. 65,536 shards x 281 T blocks.
Enforced by:              CHECK ((block_id >> 48) = :shard_ord) on every shard's block table (S20),
                          asserted at open against index_state['shard_ord'].
Costs today:              zero bytes, zero code, one CHECK constraint.
Costs if deferred:        every FK in D2 (mark, cell, grid_slot, block_asset, rel, xref, anchor,
                          term_ref, block_sec, page_render, D7's edges) plus every embedding row
                          in every deployed store.
```

**Placement is separate from minting.** A document's *current* shard is
`jump_consistent_hash(int.from_bytes(doc_key[:8], "big"), n_shards)` — Lamping–Veach jump consistent
hash, about twelve lines of stdlib arithmetic, no dependency, which moves only `1/n` of documents
when a shard is added. A document may migrate between placement shards; its `block_id`s keep their
minting prefix forever, so uniqueness survives every reshard. **A document never spans a shard**,
which is what makes a reshard a document-granular copy, resumable through the `work` table, and
what makes `DELETE FROM doc WHERE doc_key = ?` a complete erasure inside one shard.

Everything else follows D2 verbatim: `block_id` is the only FK target, `addr` is the type-free
address, `cite` is the only id that may enter a prompt, `doc_key` is the content identity and the
shard key.

---

## 5. Five channels, and how they coexist

They coexist because **they all key on `block_id`, they all live under one snapshot, they are all
written by operators carrying `origin_operator`, and each is individually droppable.** That last
property is the ecosystem one: `omniweave store drop --channel similarity` is a supported operation
that changes the *verdict*, never the honesty of the answer.

| channel | mechanism | storage | when it earns its cost |
|---|---|---|---|
| **lexical** | `bm25(block_fts)` over the narrowed set, over-fetched 5× before fusion | +290 MB/M blocks (measured, §11) | always. It is the cheapest true-positive generator in existence. |
| **exact** | `term_ref.norm` equality + prefix | ~40 B/block amortised | `§4.2(b)`, `GL-4471`, `ISO-8601`, `Fig. 3`, `Exhibit C`. FTS5's tokenizer destroys every one of these. |
| **identity** | graded ladder over `anchor`, `doc.uri`, `cite`, `addr` | ~2 B/block | "open d7#412", "the Q3 retention memo". Weighted highest because an exact name hit is almost always what was wanted. |
| **structural** | heading hits → `block_sec` prefix expansion; `rel` / `xref` / `reach` traversal | ~20 B/block | "what is under §4", "what cites this", "the caption of that figure". |
| **similarity** | binary-signature scan + optional exact rerank | 0, or 130 B/block, or 3.2 kB/block | thematic queries with no lexical or structural anchor. **Off by default.** §11. |

**The heading trick, and why there is no second copy of any block's text.** Multi-column BM25 and
jcodemunch's `_FIELD_REPS` token-repetition weighting both require duplicating text into the index.
For documents there is a cheaper answer that is also *better*: run the same FTS5 query narrowed to
heading kinds (`kind IN (title, heading, section, caption, toc_entry)` — a small percentage of
blocks), then expand each heading hit to its subtree through `block_sec.sec_path`'s prefix range,
and contribute the result to the **structural** channel. Zero extra storage, and it hands the
response "the section this answer is under" for free, which the serve layer needs anyway.

**The identity ladder** — jcodemunch's structure, documents' vocabulary, and its warning kept:

```
50  exact       query == doc.title, casefold only
50  exact       query == a `cite` ('d7#412') or an `addr` ('p14/3', 'p14/3/r2c5')
50  exact       query == a defined term's surface form, casefold only
40  normalized  matched only after NFKC + punctuation strip + whitespace collapse
30  prefix      title or heading starts with the query
20  segment     an ancestor heading chain contains the query as a WHOLE segment
 0  none
```

The 40 tier is the whole point and is the first thing a "simplification" deletes. Collapsing it into
50 let a pytest fixture named `state` tie with the class `_State` and win on BM25 — a test fixture
outranking the symbol it tests **by 0.355 points out of ~58**. The document analogue is
`Appendix A` (a heading) tying with `appendix-a.pdf` (a filename). `Hit.identity_grade` reports the
grade that was **actually measured**; "exact" that includes punctuation-stripping is not exact.

**Query transform, not escaping.** `::` → whitespace was codegraph's; ours is: `§`/`¶` are kept as
`kind` hints and stripped from the FTS term, soft hyphens and line-break hyphenation artifacts are
folded, `AND|OR|NOT|NEAR` and FTS5 specials `'"*():^` are stripped so a user cannot inject FTS
syntax, a function-word stoplist is applied to `terms` but **never** to `refs`, CJK runs are
character-bigrammed, and — the detail that matters most for adoption — **an unknown `foo:bar` prefix
passes through as plain text**, so someone searching `TODO:` or `Rev:` gets results instead of a
parse error.

---

## 6. The query planner

```python
def plan(q: Query, caps: IndexCapabilities, pol: RetrievalPolicy) -> QueryPlan
```

Pure, memoised, printable, and **written in D4's rule grammar** — first-match-wins ordered
`[[rule]]` blocks with closed comparison clauses, `@thresholds.<name>` substitution, and the same
Kleene `on_unknown` discipline. That is a deliberate ecosystem decision: an operator who learned
`route.toml` can read `retrieval.toml` without learning a second language, `omniweave route lint`'s
subsumption linter works on it unchanged, and D4's one-dimensional isotonic threshold fitter can fit
retrieval thresholds from `retrieval_event` history for free.

```toml
# retrieval.toml (builtin:balanced, abridged; the real file is ~120 lines)
policy_version = 1
schema = "omniweave.retrieve/1"

[thresholds]
overfetch = 5 ; short_circuit_grade = 50 ; heading_expand_max = 400
vec_overfetch_min = 5 ; vec_overfetch_max = 40 ; low_confidence_frac = 0.35

[[rule]]
id = "chan.similarity-off"
comment = "off is an OPERATOR CHOICE and is disclosed; unavailable is a DEGRADATION."
when = { "caps.similarity" = "off" }
then = { drop_channel = "similarity", gate_off = ["filter_exhausted", "similarity_only"] }

[[rule]]
id = "chan.reference-boost"
comment = "A reference-shaped token is nearly as decisive as an identity hit and strictly more
decisive than BM25 — FTS5 cannot even represent it."
when = { "q.refs_n" = { gt = 0 } }
then = { weight = { exact = 2.4 }, channel_on = ["exact"] }

[[rule]]
id = "chan.cite-short-circuit"
comment = "`omniweave get d7#412` must not scan 96 MB of signatures."
when = { "q.mode" = "cite", "identity.top_grade" = { gte = "@thresholds.short_circuit_grade" } }
then = { short_circuit = true }

[[rule]]
id = "chan.vector-overfetch-by-selectivity"
comment = "LEANN post-filters an ANN result with NO over-fetch: silent recall loss shaped
exactly like absence. Over-fetch by the inverse selectivity, clamped, and if the channel still
comes back fully filtered, gate 9 fires."
on_unknown = "match"
when = { "narrow.selectivity" = { lt = 1.0 } }
then = { overfetch_by = "1/narrow.selectivity", clamp = ["@thresholds.vec_overfetch_min",
                                                        "@thresholds.vec_overfetch_max"] }

[[rule]]
id = "chan.prove-absent-drops-similarity"
comment = "A zero from a cosine ranking is a statement about the MODEL, not about the corpus,
and it must not be citable as one."
when = { "q.mode" = "prove_absent" }
then = { drop_channel = "similarity" }
```

Execution: channels run in plan order, cheapest first, all inside one `Snapshot` (S2), each with its
own `budget_ms`; a channel that exceeds its budget returns `unavailable(timeout)` with whatever it
has and fires gate 1. `short_circuit` skips the remainder and records why in `plan.short_circuit`,
so `omniweave get d7#412` costs one index seek rather than a signature scan.

---

## 7. Fusion

Weighted RRF, reimplemented from `mine-graph.md` §4.3's *description* (see §17 on licensing):

```python
def _channel_weight(ch, effective) -> float:
    return ch.weight if ch.weight is not None else effective.get(ch.name, 1.0)

def fuse(channels, *, k=60, weights):
    acc: dict[BlockId, FusedHit] = {}
    for ch in channels:
        if ch.outcome != "ok":
            continue
        w = _channel_weight(ch, weights)
        for rank0, bid in enumerate(ch.ranked_ids):
            contrib = w / (k + rank0 + 1)
            h = acc.setdefault(bid, FusedHit(bid, 0.0, {}, {}))
            h.score += contrib
            h.channel_contributions[ch.name] = contrib
            h.channel_ranks[ch.name] = rank0 + 1
    return sorted(acc.values(), key=lambda h: (-h.score, h.block_id))   # S7

def ceiling(channels, *, k=60, weights):
    total = sum(max(0.0, _channel_weight(ch, weights)) for ch in channels if ch.outcome == "ok")
    return total / (k + 1) if total > 0 else 0.0
```

Three properties I will not trade away:

1. **`ceiling()` is a peer of `fuse()`, sharing `_channel_weight()`.** Weights are not normalised to
   sum to 1, so the ceiling depends on which channels actually ran: 0.0885 with all five, 0.0754
   with four, 0.0492 with lexical+identity alone. Report a raw 0.049 against a BM25-shaped
   confidence curve and a *perfect* two-channel result reads as "nothing found". `confidence =
   best_score / ceiling`, and `low_confidence` is `confidence < 0.35`.
2. **`FusedHit` carries `channel_contributions` and `channel_ranks`.** A fusion function that
   returns only a score is a fusion function you cannot tune, cannot debug, and cannot feed to the
   threshold fitter.
3. **Ranks federate; scores do not.** BM25 scores from two shards with different corpus statistics
   are incomparable; ranks are merely biased. That is the entire reason §14's fabric fuses on ranks
   and reports `shards_contributed` rather than blending, and it is why LEANN's linear blend of
   `bm25()` tens against a cosine distance is the anti-pattern: `vector_weight = 0.5` there means
   "whichever channel has the larger numeric range wins".

---

## 8. The verdict — twelve gates, and why each exists

`result_count == 0` becomes `absent` **only** after passing twelve gates in precedence order; any
failure forces `degraded` (S5). Gates 1–6 and 8 are jcodemunch's, restated for documents; 7, 9, 10
and 12 have no counterpart anywhere and are the reason this contract is worth building.

| # | Gate | Why a zero here is a lie |
|---|---|---|
| 1 | `timed_out` | a channel hit `budget_ms`; part of the corpus was not scored |
| 2 | `channel_requested_absent` | the caller asked for a channel whose capability is `unavailable` |
| 3 | `index_rebuilt_since_plan` | **federated only** — shards are separate snapshots. Single-store queries cannot fail this, because S2 gives them one snapshot. |
| 4 | `coverage_incomplete` | `ingest_scope.discovered > indexed`, or `complete = 0`, or the row is missing. A corpus that dropped files at index time reports the same digest as the source; a user got confident zeros over ~1,975 unindexed files and moved to another tool. |
| 5 | `pending_work_in_scope` | `work` rows `pending`/`claimed` whose `unit_uri` falls inside the narrow scope |
| 6 | `freshness == "unknown"` | whether the index lags the source is unestablished, and an absence claim rests entirely on that. `not_tracked` is deliberately NOT here, or every plain-folder index loses absence evidence outright. |
| 7 | **`parse_incomplete`** | **the document gate nobody has.** Any doc in scope with `doc.status IN ('partial','failed')`, or a `diag` row in scope carrying `OW_NEEDS_OCR`, `OW_ENCRYPTED`, `OW_TIMEOUT`, `OW_TRUNCATED_BY_BUDGET`, `OW_RESOURCE_LIMIT`, `OW_ORIGIN_SPAN_DOWNGRADE`. "OCR failed on pages 12–40" must make absence unprovable, and D2 handed me `diag.code` precisely so this gate could read it. The message names the pages and the `omniweave parse --rung PAGE` command that fixes it. |
| 8 | `matches_before_packing > 0` | the response is packed after ranking, so a token budget can empty it while matches were found. **An empty response is not an empty search.** |
| 9 | **`filter_exhausted`** | the vector channel returned `limit` rows and **all** were removed by the post-filter — LEANN's named bug, promoted to a gate. Silent recall loss shaped exactly like absence. |
| 10 | **`restricted_withheld`** | D3's `restriction_bits` removed rows from the response. A licence filter that looks like absence is the worst failure of both systems at once; the count is disclosed and the message names the ack that would admit them. |
| 11 | `similarity_only` | checked **second-to-last**, because every gate above names something the caller can fix. A zero from a cosine ranking rests on embedding geometry: a block can exist and still score at or below zero against the query vector. That is a statement about the model, not about the corpus. |
| 12 | **`embedding_model_changed`** | `vec_manifest.model_key ≠ [retrieval.vectors] model_key`, or `vec_manifest.corpus_id ≠ index_state.corpus_id`. Checked last because it is a permanent property of the artefact, not a fixable scan condition, and the fix (`omniweave index vectors --rebuild`) is expensive enough that the operator should see the ten cheaper causes first. |

`Verdict.degraded_because` is a list of `{gate, detail, fix}` records, and **`fix` is the exact
command that clears it** — D1's error-message rule, applied to a verdict rather than an exception.

---

## 9. Concurrency, snapshot isolation, durability

**Snapshot isolation is the question with a one-line answer that everyone gets wrong.** WAL gives a
reader a consistent snapshot *for the duration of a transaction*. Almost every hybrid retriever runs
each channel in its own implicit transaction, so channel 1 sees generation 5 and channel 5 sees
generation 6 and the fused ranking describes a corpus that never existed. S2 fixes it: one
`BEGIN DEFERRED`, held across every channel and the final `fetch`, released on exit. The re-index
proceeds at full speed the whole time — that is what WAL is for. The snapshot's generation is
recorded in the response, and a query that runs longer than `MAX_SNAPSHOT_MS = 30_000` is aborted
with `OW-S-031` rather than pinning the WAL (see the valve's futility latch below).

**The `main`/`vec` seam is where snapshot isolation genuinely does not extend.** A multi-database
read transaction in WAL mode takes two independent snapshots, and a commit spanning two attached
WAL databases is not atomic. Rather than fight it I made it irrelevant: **no transaction ever spans
the two (S3)**, vector rows are keyed on `content_digest`, and a vector hit is only ever surfaced
through an inner join to a block in the *main* snapshot (S4). A vector row for a digest that no
longer exists is invisible; a block whose digest has no vector row simply does not appear in the
similarity channel and `vpending` says so. Cross-file atomicity is not needed because the sidecar is
a cache and is designed as one.

**Write contention under a watcher.** The trigger hierarchy is D1/mine-runtime's — tool-call hook,
VCS hook or connector cursor, filesystem watcher last — and the store's contribution is to make the
watcher's write footprint trivial:

- **A watcher writes `work` rows and nothing else.** One `INSERT OR IGNORE` per changed unit against
  `work_identity`, in one short transaction per debounce batch. It never writes a block, never
  touches FTS5, and never holds the write lock for more than a few milliseconds.
- **Enqueue *before* attempting the lock** (graphify's ordering, the one everyone gets backwards).
  If the indexer holds the lock, the watcher returns immediately having lost nothing, because the
  holder's next `claim()` is a superset of the contender's change set. This is what makes
  graphify's `.pending_changes` file, its three-phase drain and its `_PENDING_DRAIN_MAX_PASSES = 20`
  unnecessary: **the table is the queue.**
- **The indexer's transaction unit is one page** (D2's `DocSink.end_page()`), so the writer releases
  the lock hundreds of times per document.
- **FTS5 is the real write hot spot, and it gets a stamped flag pair.** Measured: rebuilding
  `block_fts` over 1M blocks costs 54 s; doing it through triggers during a bulk load costs
  substantially more. So: `BULK_FTS_THRESHOLD = 50_000` blocks in one run selects the bulk path —
  drop the triggers, bulk load, `INSERT INTO block_fts(block_fts) VALUES('rebuild')`, restore. The
  flag `index_state['fts_state']` goes `ok → building → ok`, and **an open that sees `building`
  marks the lexical channel `unavailable` with `OW-S-041` naming `omniweave store repair --fts`.**
  LEANN corrects its illegal *build* combination in code and leaves the illegal *search* combination
  as a README sentence; validating from the stamped state at open is the missing half.

**The WAL valve — all eight properties, because each has a measured failure behind it.** Ported from
`codegraph/src/db/wal-valve.ts`, MIT, with attribution:

```
1. autocheckpoint DEFERRED during a bulk phase   default checkpointing was ~95% of ALL disk I/O:
                                                 45 s vs 19+ min on 150-IOPS storage
2. GROWTH-relative trigger, never size-absolute  a WAL file's SIZE NEVER SHRINKS; the writer's
   baselined on sizeAtLastFullBackfill           next commit restarts it from the top. A
                                                 size trigger fires forever (~9 min/160 files)
3. threshold PROPORTIONAL and clamped            clamp(db_bytes/4, 256 MB, 2 GB). A flat 256 MB
                                                 cost 111 s of folding on a kernel-scale index
4. off-thread PASSIVE checkpoint, own connection PASSIVE never blocks the writer; off-thread
                                                 keeps the liveness heartbeat turning
5. writer BACKPRESSURE at 2x soft, released      "the pause is the disk's honest catch-up cost —
   only by a FULL backfill                       the correct terminal mode when hardware
                                                 genuinely cannot keep up with the append rate"
6. TRUNCATE tier at 4x soft                      5.9 GB WAL against a 340 MB DB, observed
7. FUTILITY LATCH: 2 give-ups ⇒ 60 s cooldown    a pinned reader turned a slow index into an
   ⇒ degrade to un-valved behaviour              OOM-kill: 22 GB WAL, exit 137, at an envelope
                                                 the PRE-VALVE build survived (I9)
8. journal_size_limit + AT-OPEN HEAL above 64 MB a SIGKILLed process leaves an arbitrarily large
                                                 WAL; before the heal existed, 25.6 GB observed
```

`MAX_SNAPSHOT_MS` exists precisely to bound property 7's trigger: a long-lived query pins the WAL,
and a retrieval layer that can pin the WAL indefinitely will eventually OOM the indexer.

**Durability, stated plainly.** `synchronous = NORMAL` under WAL means a power loss or OS crash
cannot corrupt the database but can lose the last committed transactions. For blocks that is
correct and free: the index is derived, the `work` rows for those units are still `pending`, and
re-running the command recovers exactly. **The honest cost is billing.** `route_spend` rows are
written in the same transaction as the `work` completion, so losing the transaction loses the
completion *and* the spend record — the unit is re-claimed and **re-billed**. The exposure is
bounded by `max_inflight[BILLED_API]`, which D1's example config sets to 2, so a power loss can
cost at most two units of billable work. Operators who prefer the roughly 10× write slowdown set
`[store] synchronous = "full"`, which is documented with that number rather than hidden.

---

## 10. Incremental update, and convergence

Four mechanisms, each from a repo that paid for it:

1. **Content identity, not `(size, mtime)`.** `unit_stat` with the racily-clean predicate (§2.4).
   Staging is codegraph's: stat gates hash gates parse. graphify's per-format normalisers strip
   PDF `/ModDate`, OOXML `w:rsid*` and `docProps` timestamps, EXIF, and Markdown frontmatter before
   hashing, so a metadata-only touch never re-bills a VLM pass; a normaliser that throws falls back
   to raw bytes and records `OW_NORMALIZER_FAILED`.
2. **Tier-scoped replacement keyed on `origin_operator` (S10).** graphify's `build_merge` shape: a
   free structure re-extraction after one keystroke must not delete the LLM-derived rows for that
   unit. Deletion is an *explicit* list, never inferred — graphrag computes `deleted_inputs` and
   consumes it nowhere.
3. **`ResolutionDelta` — codegraph's `definitionDelta`, translated.** After a batch, compute the set
   of `anchor.norm` values whose row-set changed (a per-document symmetric difference of
   `(norm, kind)` pairs). Every `term_ref` whose `norm` is in the delta is re-resolved, **including
   references in documents that were not touched this run**, because resolution picks among all
   same-named definitions corpus-wide. A body-only edit leaves the delta empty, which is the common
   case and free. Without it, incremental and full diverge and nobody notices for months: codegraph
   measured **4.3% of distinct edges wrong, in both directions, silently.**
4. **`omniweave index` and `omniweave update` differ in exactly two places** — the source
   enumerator and a trailing merge. graphrag's twenty-odd indexing workflows contain *zero*
   incremental logic; delta awareness lives in one loader and eight mergers. Copy the factoring, not
   the mergers.

**The gate that makes it real (S11):** `gate_convergence.py` indexes a 200-document fixture corpus
incrementally in 40 batches and fully into a second store, then diffs every table modulo `block_id`
and timestamps. It runs on every PR touching `store/`, and it is the invariant a watcher will break
silently if it is not there.

**Vector incrementality is free by construction**, because the key is `content_digest`: after
`rebind`, the re-embed set is one anti-join into `vpending`. This is the direct answer to
mine-runtime open question 2 (*"where does the vector index's non-incrementality go?"*): it goes
away, because we key on content rather than on position and we never build a graph that must be
rebuilt. graphrag re-embeds the whole corpus per update and physically copies the whole index
(`_copy_previous_output` on a 50 GB index copies 50 GB to add one document); we copy nothing.

---

## 11. Vectors: an operator, a Backend, and a measured ceiling

**Embeddings are an operator (D3's `embed/1` Port) and the ANN index is a Backend. Core ships zero
embedding code, zero torch, zero numpy, zero faiss.** `pip install omniweave` gives working
retrieval with `similarity: "off"` disclosed in every response, and graphify's own numbers are the
justification: **0.497 recall@10 on LOCOMO and 76% on LongMemEval-S at zero embedding cost, tying
dense RAG.** Vectors earn their keep on thematic queries with no lexical or structural anchor — a
narrower slice than RAG-first designs assume.

**The default backend, `vector.sqlite.brute`, is binary quantization + segment scan.** Store one
sign bit per dimension (96 B at 768 dims), scan with `(a ^ b).bit_count()` on Python ints — a
single C-level operation per block — and optionally rerank the top 512 with exact float32 cosine.
All measurements below are mine, on this machine (Windows 11, CPython 3.11.9, 768-dim / 96-byte
signatures, top-512 heap):

```
                                       stdlib, row-per-vector   stdlib, 4096-per-segment   numpy 2.4
  10,000 blocks                                       ~2 ms                       ~2 ms          —
 100,000 blocks                                       100 ms                       47 ms          —
1,000,000 blocks                                     1072 ms                      466 ms      182 ms
10,000,000 blocks                                        —                       5112 ms     2112 ms

  exact float32 rerank of 512 x 768, pure Python: 12.4 ms
  storage: sig_only 96 B/block + ~34 B key overhead ;  sig_full adds 3072 B/block at 768 dims
```

Four decisions fall straight out of that table:

- **Segments, not rows.** `vseg` holds 4096 signatures in one contiguous BLOB. The 2.3× speedup at
  1M is pure SQLite cursor overhead; a row-per-vector layout is the mistake that hides it.
- **`VEC_BRUTE_MAX_BLOCKS = 250_000`, and above it the backend *refuses*** with `OW-S-052` naming
  the remedy (`pip install omniweave-vector-usearch`, or set `[retrieval] vectors = "off"`). At 250k
  the scan is ~120 ms, which fits inside D1's 250 ms warm-query budget alongside the lexical
  channel. A silent five-second query is a worse product than an honest refusal, and this is the
  D1 capability-probe pattern applied to a storage decision.
- **Storage mode is a validated, stamped flag pair** (LEANN's lesson, both halves): `sig_full` below
  `VEC_FULL_MAX_BLOCKS = 2_000_000` (≈6 GB) so a laptop gets exact rerank; `sig_only` above, where
  the verdict reports `similarity: approximate`. The illegal search combination is refused **from
  the stamped manifest at open**, not documented in a README.
- **Recall is a CI gate, not a claim.** `gate_vec_recall.py` asserts recall@10 of the
  signature+rerank path against exhaustive float32 search on a fixed 50k-block fixture, with a
  floor committed per release. I will not quote a recall number I have not measured on our corpus.

**Why I decline LEANN's selective recomputation**, despite admiring it. Its storage economics are
real (201 GB → 6 GB at 60M chunks, ~100 B/chunk) — and binary signatures reach **96 B/block through
a completely different mechanism with none of the operational surface**: no `embedding_server_manager.py`
(908 lines), no ZMQ, no 900 s daemon TTL, no port scanning from 5557, no two-layer `threading.Lock`
+ `flock` locking, no stale-lock recovery by age-or-pid-liveness, no 64–200 chunk embeddings per
query, and no GPU on the query path. LEANN pays all of that to move the bill from storage to query
time; we get the storage win and keep the query local. D1 also pre-authorised the daemon channel
(a 0600 unix socket) if someone later wants to argue for it — I am not spending the operator's
budget on it now.

**Third-party ANN is the flagship proof of the Backend seam.** `omniweave.backends` entry points,
a `backend.toml` card read by D3's import-free loader (`kind = "vector"`, never a Port — D3 reserved
`Backend` for D5 and this is the whole of it), and `omniweave-conform`'s `backend` suite: manifest
round-trip, upsert idempotence, filter pushdown, sweep correctness, recall floor, and a refusal test
above its own declared ceiling. `vector.usearch` lives in its own repository as the reference
implementation, which is exactly how we prove an outsider can write one in an afternoon.

---

## 12. How the graph is stored, and how multi-hop stays fast

**An edge table with schema-enforced identity, plus a capped closure for the two traversals that
actually need to be fast. Not a graph engine, not a CSR adjacency blob as the primary.**

- **Intra-document containment is `parent_id` + `ord` and intra-document relations are D2's closed
  seven-kind `rel` table.** D5 adds the missing `rel_src ON rel(src_id, kind)` index; D2 shipped
  only `rel_dst`.
- **Cross-document references are `xref`, with identity in the schema** (`INSERT OR IGNORE` is a
  plain INSERT with nothing to conflict on — codegraph #1034) and `ambiguous` kept rather than
  dropped. D7's entity, claim, community and community-report tables sit beside it and key on
  `block_id`; **D5 owns the tables, D7 owns the rows via `origin_operator`.** That split is what
  lets D7 ship a new extractor without a store migration.
- **Multi-hop to depth 3** is a recursive CTE over `(src_id, kind, dst_id)` covering indexes.
  codegraph indexes **6.4 million relationships in SQLite with sub-millisecond reads**, which is the
  evidence that this is enough; and its own justification discipline applies — `idx_edges_source`
  and `idx_edges_target` are *deliberately omitted* because the `(source, kind)` and `(target, kind)`
  composites cover them by left-prefix scan and the narrow indexes are dead weight on writes.
- **Beyond depth 3, or for a hot "what cites this, transitively" query**, `reach` materialises a
  2-hop closure over a **named, small** relation set (`cites`, `supersedes`, `derived_from`,
  `continues`), maintained incrementally, capped at `MAX_REACH_ROWS = 20 × block_count`. A breach
  truncates the table, stamps `reach_enabled = 0`, falls back to the CTE, and reports the fallback in
  `degradations[]` on every affected response. A governor that cannot help must get out of the way.
- **A CSR adjacency snapshot is a legitimate *derived artefact*** for batch PageRank or Leiden
  clustering — `omniweave graph export --csr` — and is never the source of truth, because it cannot
  be incrementally updated without a rewrite. graphify's `graph.json` + in-memory NetworkX as the
  primary store is the anti-pattern, and its authors' own caps say so in a constant: typical
  `< 5 MB / < 50k nodes`, hard caps `50 MB / 100k nodes` — two to three orders below our target.

**Why not a real graph engine.** Neo4j, Kùzu or DuckDB-PGQ would each add a second storage system,
a second backup and restore story, a second migration story, a second set of pragmas, and — for
Neo4j Community — a GPLv3 licence into a stack D1 keeps Apache-2.0-clean with a deny-list gate. The
measured evidence says the edge table suffices at the scale we can currently prove. If a workload
later needs true unbounded traversal, it arrives as a `Backend`, not as a rewrite.

---

## 13. Migrations, at a size where migrations hurt

Numbered, described, idempotent, and honest about backfill (codegraph's discipline), with two
additions that matter at 40 GB:

- **`unbackfilled_means` is a required prose column (S13)** and `omniweave doctor` prints it
  verbatim. codegraph's v9 comment — *"every reader unions the flag with the path-only check, so an
  un-backfilled database keeps exactly the pre-#1500 behavior"* — is the model: when a migration
  cannot backfill, make the column a **monotone hint that unions with the old signal**.
- **A migration whose estimated row-touch exceeds `WATCHDOG_MS / 2` must be resumable and must run
  through the `work` table.** Four `CREATE INDEX` statements at ~20 s each is 79 s against a 60 s
  liveness watchdog, which got codegraph **SIGKILLed right after doing the work** — the most
  expensive failure available is one that discards completed work. So a backfill migration enqueues
  chunked `work` rows, yields every 1,000 items at the *top* of the loop body so `continue`
  fast-paths still hit it, reports `omniweave doctor` progress as `migration 7: 62% backfilled`,
  and survives a kill.
- Every `ALTER TABLE ... ADD COLUMN` is guarded with `PRAGMA table_info(...)` (SQLite has no
  `IF NOT EXISTS` for it), every index create is `IF NOT EXISTS`, and every dedup `DELETE` before a
  new `UNIQUE` index uses a `GROUP BY` **exactly matching the index expression** — including the
  `IFNULL` sentinels, or the migration silently leaves duplicates behind.

---

## 14. From a 10k-block laptop to a 10B-block cluster

| tier | corpus | store | writers | similarity | what changes | what breaks first |
|---|---|---|---|---|---|---|
| **T1** | 10k–1M blocks | one `.owstore`, WAL | 1 process, asyncio + a process pool | `vector.sqlite.brute`, `sig_full` | nothing. `pip install omniweave` | nothing. Query p50 ~35 ms. |
| **T2** | 1M–50M blocks | one `.owstore`, WAL + the full valve | N workers, one host, claim/lease | `sig_only`, or a third-party ANN backend | `[store] wal_valve_mb`, `max_inflight` | the brute scan (250k), then FTS build time (54 s/M), then WAL growth |
| **T3** | 50M–1B blocks | Postgres, one database | N hosts, `SELECT … FOR UPDATE SKIP LOCKED` | a hosted ANN backend | `[store] backend = "postgres"`. **No operator changes.** | `ts_rank_cd` ≠ `bm25()`: quality history resets (§3) |
| **T4** | 1B–10B blocks | a **fabric** of shards, each T1/T2/T3 | per-shard, independent | per-shard | `[store] backend = "fabric"` + a catalog | rank-fusion bias across shards; tail latency = slowest shard |

**Sharding.** The key is `doc_key`, placement is jump consistent hash (§4), a document never spans a
shard. Consequences worth having: a shard is independently rebuildable, backup-able and deletable; a
reshard is a document-granular copy driven by `work` rows; and right-to-erasure is
`DELETE FROM doc WHERE doc_key = ?` in exactly one shard — followed by `omniweave store vacuum`,
because a `DELETE` frees pages without shrinking the file, which is a compliance-relevant fact that
belongs in the docs and not in a support ticket.

**Federation.**

```toml
[store]
backend = "fabric"

[[store.fabric.shard]]
name = "legal-2019"; dsn = "sqlite:///mnt/idx/legal-2019.owstore"
required = true;     timeout_ms = 400
[[store.fabric.shard]]
name = "web-crawl";  dsn = "postgresql://idx-3/omniweave"
required = false;    timeout_ms = 800   # best-effort; a miss is a DEGRADATION, never silence
```

A federated query broadcasts the same `Query` and `k × fanout_overfetch` to every shard, then fuses
**on ranks** — the property that makes RRF federate where score-blending cannot, because two BM25
indexes with different corpus statistics produce incomparable scores. The bias is real (RRF over
per-shard ranks favours small shards) and it is disclosed rather than hidden:
`verdict.shards_contributed = "3 of 4"`, and **a federated verdict is `degraded` if any shard is
`degraded`, timed out, or unreachable** — gate 3. That roll-up is the thing every federated search
gets wrong, and getting it right is the difference between a fabric an agent can trust and one it
cannot.

**Honest limits.** Global BM25 idf is not available across shards; `anchor` resolution across shards
requires a broadcast, so `xref_unresolved` is per-shard and a cross-shard citation resolves only
through a periodic catalog build. Both are stated in the fabric documentation, both have a `verdict`
disclosure, and neither is pretended away.

---

## 15. Git: the index is a cache; ship a text projection instead

**The `.owstore` is never committed (S14).** graphify's own merge driver is the argument against
its own idea: `nx.compose` is a pure union that **ignores the merge base**, so a node deleted on one
branch and untouched on the other comes back; the driver's caps are 50 MB / 100k nodes; and typical
graphs are expected under 5 MB / 50k nodes. That is two to three orders below a real document
corpus, and a binary SQLite file is unmergeable at any size.

**But "don't commit it" is not an answer, so here is the answer.** `omniweave index export
--portable` writes text that git already merges correctly, at a granularity git already understands:

```
.omniweave/portable/
├── manifest.json                      # pretty-printed: SCHEMA, corpus_id, scorer_version,
│                                      # digest_recipe, counts, per-shard registry, driver set
└── d/<doc_key[:2]>/<doc_key>.ndjson.zst   # ONE FILE PER DOCUMENT: blocks, marks, rels, grids,
                                           # anchors, term_refs. addr-referenced, never block_id.
```

**One file per document is the whole trick.** Two branches that index different documents produce
disjoint file sets and git merges them with no custom driver, no merge attribute, and no union
semantics to get wrong. Two branches that re-index the *same* document produce a real conflict on
one file, which is correct, because they genuinely disagree. `omniweave index import` rebuilds a
`.owstore` from it deterministically, and it reuses D2's `.owdoc` frame codec, so the projection
costs almost no new code and inherits D2's `import(export(store)) == store` CI gate.

Three properties this buys and a committed database does not: a code review can *read the diff* of
what re-indexing changed; a CI job can rebuild the index from the projection and assert equality
with a fresh index; and a contributor with no corpus access can run the test suite. The store,
meanwhile, stays a cache — which is what makes `rm -rf .omniweave` safe and `omniweave index
--rebuild` a supported one-command recovery, gated in CI by `rebuild == incremental` (S11).

---

## 16. Operability surface

```
omniweave query <text> [--k 20] [--mode find|cite|explore|prove_absent] [--json]
omniweave query explain <text>            evidence, channels, narrowing, fusion, gates, estimate
omniweave get <cite|addr|uri>             the short-circuit path: one index seek
omniweave store doctor                    schema, migrations (+ unbackfilled_means), fts_state,
                                          vec manifest vs config, WAL size vs baseline, coverage,
                                          tracked-in-git check, disk headroom, index sizes
omniweave store stats [--by kind|doc|op]  rows, bytes and index bytes per table
omniweave store explain --golden          EXPLAIN QUERY PLAN for every shipped statement (S12)
omniweave store verify [--deep]           FK integrity, FTS5 ghost scan, digest spot-check,
                                          orphan CAS blobs, vseg/live-bitmap consistency
omniweave store repair --fts | --sec | --anchor | --reach
omniweave store gc                        route + event retention, CAS refcount sweep, vec sweep
omniweave store vacuum [--into <path>]    the ONLY thing that shrinks the file. Says so.
omniweave store backup <path>             sqlite3 online backup API: consistent, no writer pause
omniweave store residue                   xref_unresolved grouped by norm — the residue is data
omniweave store migrate [--resume]        resumable through `work`
omniweave index [--rebuild] | update | vectors [--rebuild|--mode sig_only|sig_full]
omniweave index export --portable | import
omniweave forget <uri|doc_key> [--and-blobs]
omniweave store drop --channel similarity|structural|exact
```

**Error codes**, `OW-S-nnn`, append-only in `codes.toml`, every message ending in the exact command
that clears it:

```
OW-S-001 store not found                    -> omniweave index
OW-S-010 SCHEMA newer than this reader       names both ints and the upgrade command
OW-S-011 migration pending / partially backfilled   prints unbackfilled_means verbatim
OW-S-020 FTS5 unavailable in this interpreter -> pip install 'omniweave[sqlite]'   (D1's remedy)
OW-S-021 sqlite_version < 3.35 (no UPDATE…RETURNING): the fallback claim path is in use
OW-S-030 database is locked past BATCH_WAIT   names the holder (host:pid:create_time)
OW-S-031 snapshot exceeded MAX_SNAPSHOT_MS    the query was aborted to release the WAL
OW-S-040 WAL above the hard cap; writer paused  names bytes, baseline and the valve setting
OW-S-041 fts_state='building'                -> omniweave store repair --fts
OW-S-050 vec manifest corpus_id mismatch: the sidecar is ignored, not read
OW-S-051 vec model_key mismatch vs config    -> omniweave index vectors --rebuild
OW-S-052 corpus above the backend's declared ceiling -> install an ANN backend, or vectors="off"
OW-S-060 shard unreachable                    names the shard and required=true|false
OW-S-070 store is tracked by git             -> git rm --cached + omniweave init
```

**Cold-start budget (D1 gate G10, `omniweave query, warm store ≤ 250 ms`)**, with what I expect to
spend, from the measurements above: process + `import omniweave_core` ≤ 80 ms; open + pragmas +
capability read ≤ 8 ms; plan (memoised) < 1 ms; four channels ≤ 60 ms at 1M blocks (lexical p50 is
31.8 ms measured); fuse + verdict < 2 ms; `fetch` of 60 blocks ≤ 6 ms; pack ≤ 5 ms. **≈ 162 ms with
similarity off; ≈ 630 ms at 1M blocks with the stdlib similarity channel on** — which is exactly why
`vectors = "off"` is the default and why the brute backend has a 250k ceiling.

---

## 17. Licensing

- **jcodemunch-mcp is unusable in any form.** Its Dual-Use Licence v1.1 §3 bars use *"within a
  for-profit organization to support revenue-generating activities"* and bars publishing any
  derivative to a package registry. It is also the repo with the most original retrieval thinking in
  the collection. **Every idea I take from it — weighted RRF with a ceiling, the identity score
  ladder, the four-state verdict and its gates, four-valued freshness, `ranking_events`, keystone
  entropy pruning, the `None`-vs-empty candidate discipline — is reimplemented from the *design
  descriptions* in `mine-graph.md` §4 and `mine-serve.md`, without reading, copying or adapting the
  source text or structure.** `omniweave_core/retrieve/PROVENANCE.md` records, per mechanism, the
  idea, its source, and the fact that the implementation is original; it is a required review item
  on every PR touching `retrieve/`, and no file under `retrieve/` is vendored from anywhere.
- **codegraph (MIT)**: pragmas, the WAL valve, the FTS5 external-content pattern, migration
  discipline, over-fetch-before-rerank, the query transform, `definitionDelta`. Vendorable with
  attribution; recorded in `THIRD_PARTY.md` (D1's generated file). Note the upstream gap D1 will
  care about: codegraph's `grammars/kotlin/` ships `parser.c` with **no LICENSE file** — irrelevant
  to D5 because we take no grammar, and recorded so nobody takes one later.
- **LEANN (MIT)**: the `meta.json` portability contract, the storage/compute flag pair, the
  passage-id-scheme fork. Its four `third_party/` submodules are empty in this checkout and
  `libzmq`'s licence (MPL-2.0 recently, LGPL-with-static-exception historically) is unverified —
  another reason not to take the daemon.
- **graphrag (MIT, maintenance mode)** and **graphify (Apache-2.0 + NOTICE)**: designs only; the
  `NOTICE` file is carried if any graphify code is taken.
- **Zero new runtime dependencies from D5.** `sqlite3`, `json`, `hashlib`, `heapq`, `array`,
  `struct`, `unicodedata`, `re`, `tomllib`. No numpy, no faiss, no hnswlib, no Neo4j, no
  `sqlite-vec` extension (a loadable C extension in core would breach D1's G1 and G9 and would need
  a per-platform build matrix D1 explicitly refused).

---

## 18. Cost, and build order

**≈ 16 engineer-weeks for one senior engineer**, plus a standing ~0.15 FTE owning the golden query
set, the query-plan goldens and the recall gate. Roughly 5,200 LoC of Python plus ~700 lines of SQL.

1. **Weeks 1–3 · the store.** Pragmas, `connect_readonly`, `0001_init` (with C2's corrections),
   migrations + `migration` table, `DocSink` implementation, `Store`'s four methods with the
   no-`RETURNING` fallback, `unit_stat`, `doc_head`, `index_state`. **Deliverable:
   `omniweave index . && omniweave store stats`.** S1, S13, S18, S20.
2. **Weeks 4–6 · lexical + the verdict.** `block_fts` and triggers, the bulk/incremental FTS flag
   pair, `Snapshot`, the lexical channel, `build_verdict` with all twelve gates, `ingest_scope`,
   `retrieval_event`. **Deliverable: `omniweave query` that can honestly say "not found".** S2, S5,
   S9, S19, S21.
3. **Weeks 7–9 · the other three free channels and fusion.** `term_ref`, `anchor`, `xref`,
   `block_sec`, the query transform, the identity ladder, `fuse`/`ceiling`, `plan()` and
   `retrieval.toml`, `omniweave query explain`. **Deliverable: hybrid retrieval with a tunable,
   explainable ranking.** S6, S7, S8, S12, S16.
4. **Weeks 10–12 · durability and convergence.** The full WAL valve, `ResolutionDelta`,
   `gate_convergence.py`, `store verify`/`repair`/`gc`/`vacuum`/`backup`, `OW-S-*` and
   `store doctor`. **Deliverable: an index that survives a bulk load on a slow disk and converges
   with a full rebuild.** S10, S11, S15.
5. **Weeks 13–14 · vectors as a Backend.** `omniweave.backends` + `backend.toml`, the `vec` sidecar,
   `vector.sqlite.brute`, `vpending`, the recall and refusal gates, and `vector.usearch` in its own
   repository as the third-party proof. S3, S4.
6. **Weeks 15–16 · portability and scale-out.** `index export/import --portable`, the shard prefix
   and `shard_registry`, the Postgres backend behind the same conformance suite, `fabric` scatter
   with rank fusion and the degraded roll-up. S14, S22.

**Runtime overhead of the index layer itself**, over D2's bare `.owstore`: `block_fts` +290 MB/M
blocks (measured); `term_ref` + `anchor` + `block_sec` ≈ +62 B/block; `vec` 0 / 130 B / 3.2 kB per
block by mode; `retrieval_event` ≈ 300 B/query at 90-day retention; D4's route rows ≈ 1 GB/M parts
falling to ~360 MB after its sweep. **Memory:** `cache_size` 64 MB + `mmap_size` 256 MB per
connection, plus one 393 KB segment buffer during a similarity scan. Nothing in the retrieval path
holds the corpus in RAM, by construction.

---

## Tradeoffs

- **A public read schema is a public constraint.** Every table above is now something an outside
  dashboard may depend on, and a `SCHEMA` major bump becomes a customer-visible event with a
  deprecation window. I am trading refactoring freedom for the ability to say "your data team can
  just open the file", and I think that is the highest-value trade available to this framework.
- **One file per corpus makes `VACUUM` a cliff.** A 40 GB store needs 40 GB of free space and a
  writer pause to compact. `vacuum --into` mitigates; nothing removes it. Multi-file layouts avoid
  it and cost the portability property.
- **The stdlib similarity ceiling is 250k blocks.** A user with 5M blocks and no ability to install
  a native package gets `similarity: "off"` and four channels. That is a real product limitation and
  the correct one; the alternative is a five-second query or numpy in core.
- **`content_digest`-keyed vectors trade a fan-out for free dedup and free incrementality.** A
  digest shared by 5,000 running headers collapses to one vector; expansion is capped at 8 and
  disclosed. On a corpus of near-identical boilerplate documents, similarity recall genuinely
  suffers, and the fix (`MAX_DIGEST_FANOUT`) is a knob, not a solution.
- **Rank fusion across shards is biased toward small shards.** Disclosed via
  `shards_contributed`, not fixed. Fixing it needs global corpus statistics, which needs a catalog
  build, which is a service — and a service is the thing this design exists to avoid at T1–T3.
- **Twelve gates means most real answers are `degraded`.** On day one, on a corpus with any scanned
  PDF, gate 7 fires constantly. That is the truth, and it will read as noise until operators learn
  that `degraded` means "usable, but I could not prove absence". The alternative is a confident zero.
- **`synchronous = NORMAL` can re-bill up to `max_inflight[BILLED_API]` units** after a power loss.
  Priced, bounded, and switchable at roughly 10× write cost.
- **Two policy files (`route.toml`, `retrieval.toml`) is one more artefact to own.** Sharing D4's
  grammar and linter is what keeps it from being one more *language*.
- **The `reach` table is a cache that can be wrong-by-staleness between the write and the
  incremental maintenance pass.** It is off by default and its fallback is always correct, so the
  failure mode is "slower", not "wrong" — but it is one more thing to invalidate.

---

## Failure modes

1. **The 10M-block file-size projection is unresolved by a factor of 3–10×.** D2 projects 3.3 GB;
   codegraph's kernel measurements extrapolate to 10–40 GB; my own synthetic measurement lands at
   912 B/block including FTS (622 B of text + 290 B of index) with a pessimistic random vocabulary.
   If the real figure is 40 GB, `mmap_size = 256 MB` and `cache_size = 64 MB` become the binding
   constraints and T2 arrives at 5M blocks rather than 50M. **The gate that settles it:** `G-SIZE`
   indexes ten real 200-page documents and records bytes-per-block per table, per release.
2. **The input that breaks it: one document with millions of blocks.** A 4M-cell spreadsheet is 4M
   ordinary blocks (D2's design, and the right one), all in one `doc_key`, therefore all in one
   shard, and D2's `DocSink.end_page()` commits a page at a time — so it is one enormous
   transaction, one enormous WAL growth spike, and a `sec_path` with 4M rows under one section. The
   valve pauses the writer, which is correct, and the query planner's narrowing by `doc_keys`
   becomes useless because there is one key. The fabric cannot help. My honest answer today is a
   `MAX_BLOCKS_PER_DOC` refusal with `OW_RESOURCE_LIMIT` naming the knob; the real fix is a sub-page
   commit boundary, which D2 lists as its own open question.
3. **A hot-loop watcher on a corpus of large PDFs.** Every save re-stats, re-hashes 200 MB, and
   enqueues. `unit_stat`'s racily-clean fastpath avoids the hash when the file truly did not change,
   but a tool that rewrites a PDF with identical content and a new `/ModDate` defeats it unless the
   normaliser catches that specific producer's quirk. The observable symptom is a re-index storm; the
   mitigation is D4's `gate.watcher-may-not-bill`, which caps the damage at free work.
4. **A pinned reader plus a bulk index.** A long-lived MCP session holding a snapshot prevents WAL
   checkpointing; the valve escalates, fails, latches, and degrades to un-valved growth. That is by
   design (I9) and it still means the WAL grows unbounded until the reader exits. `MAX_SNAPSHOT_MS`
   bounds a single query but not a client that opens a fresh snapshot every 20 seconds forever.
5. **`term_ref` explodes on the wrong corpus.** A patent portfolio or a statute is nearly all
   reference tokens; at 32 refs/block the table is ~2.5 kB/block and dwarfs everything else. The cap
   makes it bounded, not cheap, and the truncation `Diag` will be 40,000 warnings nobody opens.
6. **Fusion weights are mine, not yours.** `{identity 2.0, exact 1.2, lexical 1.0, similarity 0.8,
   structural 0.4}` are transferred from a *code-search* tuning and my `exact` weight is asserted,
   not fitted. On a corpus with no reference vocabulary, `exact` contributes nothing and the ceiling
   silently drops the confidence denominator for every query. The `retrieval_event` log plus D4's
   isotonic fitter is the path to fixing this, and it needs traffic we will not have on day one.
7. **The absence contract is only as good as `ingest_scope`.** A connector that forgets to write its
   coverage row makes gate 4 unreachable, and the response reads `ok` over an incomplete corpus —
   exactly jcodemunch's 1,975-file incident, reintroduced through the connector boundary. The
   conformance suite for `acquire` drivers must assert the row; that is a D3 obligation I am
   creating and should say so out loud.
8. **A backend that lies about filter pushdown.** A third-party `VectorIndex` that ignores
   `candidate_digests` and post-filters instead produces recall loss shaped like absence, and gate 9
   only catches the total-wipeout case. The conformance suite tests pushdown with a synthetic
   selectivity of 0.01; a backend that passes the test and regresses later is undetected.
9. **A Postgres T3 migration silently resets every quality number.** `ts_rank_cd` is not `bm25()`,
   `scorer_version` changes, and every `route_scoreboard` cell goes `UNKNOWN`. This is documented
   and it is still going to surprise the first operator who does it on a Friday.
10. **Two writers via two `.owstore` paths for one corpus.** Nothing in SQLite prevents a second
    process from indexing the same source into a second file and both being served. `corpus_id` in
    `index_state` detects a mismatched `vec` sidecar but not a duplicated store. `omniweave doctor`
    warns; it cannot prevent.

---

## Why I reject the alternatives

- **A vector database (Qdrant / Weaviate / pgvector) as a core component.** It adds a service to
  install, a port to secure, a second backup story, a second upgrade path, and a second failure
  domain — before a user has parsed one document. graphrag's *pluggability* is right and its
  default is not: with an embedded default, the vector index is a file you can delete. pgvector is
  the right T3 answer and arrives as a `Backend`, not as a prerequisite.
- **A dedicated graph engine (Neo4j / Kùzu / DuckDB-PGQ).** codegraph indexes 6.4M relationships in
  SQLite with sub-millisecond reads; the edge table plus a capped closure covers the traversals
  documents actually need. Neo4j Community is GPLv3 into a stack D1 keeps Apache-2.0-clean with a
  fail-not-warn deny-list gate, and every engine here is a second storage system with its own
  operational surface. If unbounded traversal is ever needed it arrives as a `Backend`.
- **LEANN's selective recomputation as the default vector story.** Its storage economics are real
  and I match them by a different route (96 B/block signatures vs its ~100 B/chunk pruned CSR)
  without a 908-line embedding-server manager, a ZMQ socket, a 900 s daemon TTL, two-layer locking
  with stale-lock recovery, or 64–200 chunk embeddings on every query. LEANN also states that HNSW
  has *"limited incremental support"* — its own MCP tool defaults to `ivf` for that reason — so a
  pruned-graph index forces a full rebuild per ingest, which is the dominant cost at scale.
- **graphify's committed `graph.json` and its union merge driver.** The authors' own constants cap
  the design at 50 MB / 100k nodes with typical graphs under 5 MB / 50k nodes, two to three orders
  below the target; `nx.compose` ignores the merge base, so a deletion on one branch is resurrected;
  and the artefact is a whole-graph JSON that conflicts on every co-edit. One text file per
  document, which git merges natively with no driver at all, gets the committable property without
  any of that.
- **graphify's deliberate no-vectors position as a permanent stance.** Right as a *default* — its
  LongMemEval-S tie at zero embedding cost is the strongest evidence in the collection and it is why
  `vectors = "off"` ships that way. Wrong as an architecture: "documents about a theme with no
  shared vocabulary" has no lexical or structural anchor to follow, and refusing to have a
  similarity channel means the verdict can never distinguish "we have no vectors" from "we looked".
  The three-valued `off` / `unavailable` / `ok` capability is what makes deliberate absence honest
  rather than merely absent.
- **A separate index file per channel (an FTS file, a graph file, a vector file).** Four files means
  four snapshots, four backup semantics, four half-consistent states after a crash, and no
  cross-channel filter pushdown in one query. The one exception I *do* make — the `vec` sidecar — is
  justified because it is the only channel that is optional, the only one whose bytes dwarf
  everything else, and the only one whose staleness is harmless (S4). One exception with a stated
  reason beats a principle applied four times.
- **Making `Store` a fat interface with reads on it.** D1 promised four methods and meant it: the
  distribution boundary must stay small enough that a Postgres implementation is a weekend. Reads
  are a separate protocol with a separate implementer, and the published SQL schema means most
  readers need neither.
- **Committing the SQLite index to git, with or without a merge driver.** A binary file git cannot
  merge, cannot diff, and cannot review, that grows to tens of gigabytes, whose merge semantics
  would have to be invented, and whose sole benefit — a contributor gets a warm index on clone — is
  delivered better by the text projection plus one `omniweave index import`.
- **An in-memory lexical index (jcodemunch's Python-loop BM25 over the whole table).** Three of five
  repos in the mine converged independently on an on-disk inverted index, and LEANN's own comment
  says why it replaced its in-memory scorer: *"memory-bounded at search time … replaces
  BM25Scorer's full-corpus-in-memory model."*
- **Score blending across channels (LEANN's `vector_weight` hybrid).** It linearly combines SQLite
  `bm25()` values in the tens with a cosine distance, so `vector_weight = 0.5` means "whichever
  channel has the larger numeric range wins", a document found by one channel scores on the same
  additive scale as one found by all four, and ties break on dict insertion order. Rank fusion is
  scale-free, federates correctly, and is the only mechanism here for which consensus beats a strong
  single-channel score.
- **A retrieval microservice.** ~35 ms of index reads do not need a network hop, a second deploy
  artefact, a second failure domain, or an auth story — and it would forfeit the property that
  `pip install omniweave && omniweave query` works on a laptop with no daemon, which is the entire
  adoption argument.
- **`prefix='2 3'` on `block_fts`, which I intended to ship until I measured it.** 770 MB versus
  290 MB of FTS index and 155 s versus 54 s of build time at 1M blocks, to take a 31.8 ms query to
  39.2 ms. It stays available as `[retrieval] fts_prefix` for someone who measures their own corpus.
  I include this because it is the clearest illustration of the rule the whole proposal runs on:
  **an index option you have not measured on your own corpus is a cost you are imposing on your
  users without their knowledge.**
