-- 0004_runtime.sql -- the runtime ledger.
--
-- Object assignment: 07-store-and-retrieval.md section 3's migration table, whose 0004 row reads
-- "unit, work, work_done, cache_index, dep, cohort, cohort_member, budget_reservation, run,
-- service_observation, driver_observation, driver_card_cache, route_*". The twelve named tables are
-- transcribed from charter.md:3991-4256 (the "#### The roster, the queue and the claim" and
-- "#### The cache, the deps and the durable budget" DDL blocks) in that row's order, which is also
-- the charter's printed order. The route_* block is 05-ingest-and-routing.md section 7.1 (decision,
-- unit_decision, evidence), section 5.4 (signal), section 6.4 (spend), section 8.1-8.2 (quality,
-- threshold, scoreboard) -- NOT charter.md:2811-2932, which erratum E21 (charter.md:8721) retires in
-- favour of 05: "05 section 7.1 and section 8.2 own the shipped DDL and print five deviations".
--
-- P2 writes this DDL; P4 fills the rows (16-roadmap.md section 3, the 0004 row: "P2 creates them
-- empty; P4 fills them" -- empty of ROWS, not a blank file; 16-roadmap.md section 3.3: "W2.2
-- therefore writes the DDL for 0001-0004 in one strictly-ordered pass"). G27(b) applies every file
-- in numeric order to an empty file on MIN_SQLITE = (3, 42, 0) whether or not the tables have rows.
--
-- THIS FILE IS SELF-CONTAINED: measured, every REFERENCES clause below names a table this file
-- creates. The 0001 dependency 07 section 3's table records runs the other way -- block.decision_id
-- in 0001_init.sql is the one FORWARD foreign key in the shipped order (07 section 3, and
-- 05-ingest-and-routing.md:2647 "0004_runtime.sql creates every route_* table"). Two foreign keys
-- INSIDE this file are forward too: budget_reservation.run_id names `run` and
-- budget_reservation.decision_id names `route_decision`, both created below it because 07 section
-- 3's row fixes the order. All three are safe for the same reason and it is the reason 07 section 3
-- prints as a rule: a foreign key's parent is resolved at "the first DML on the child row, not
-- CREATE TABLE", and a migration writes no rows.
--
-- NO PRAGMA BLOCK HERE. The pragma sequence is 0001_init.sql's (03-document-model.md section 13.1,
-- charter.md:2295-2303) and its order is load-bearing (07 section 2.1); a second copy would be a
-- second home for one setting.
--
-- NO `migration` ROW HERE, and the omission is derived rather than assumed. `migration` is created
-- by 0003_index.sql (07 section 3.8), so 0001_init.sql and 0002_graph.sql *cannot* insert their own
-- rows -- the table does not exist when they run. The row is therefore the applier's, for every
-- file uniformly. The three facts 11-repo-layout.md section 5.1 says a later operator "cannot
-- re-derive" are, for this file: cost_class = 'ddl', resumable = 0, and unbackfilled_means = "not
-- applicable: 0004 is pure DDL and writes no rows, so there is nothing to backfill".
--
-- HOUSE STYLE: ASCII only, LF, `--` never an em-dash. The charter's decorative rules, arrows and
-- stars are folded to ASCII; every load-bearing comment is kept and cited.

-- =========================================================================================
-- THE ROSTER. One row per source document. 100k docs ~= 22 MB.  charter.md:3990-4016
-- =========================================================================================
CREATE TABLE unit (
  unit_uri       TEXT PRIMARY KEY,          -- canonical_uri(): realpath+normcase+'/'+strip \\?\
  connector      TEXT NOT NULL DEFAULT 'fs',
  cursor         TEXT,                      -- the connector's resume token FOR THIS UNIT
  state          TEXT NOT NULL CHECK (state IN ('discovered','acquiring','acquired','identified',
                                                'planned','running','settled','failed',
                                                'out_of_scope')),
  size INTEGER, mtime_ns INTEGER, indexed_at_ns INTEGER,   -- captured BEFORE the content read
  content_sha256 TEXT,                      -- sha256 over NORMALISED load-bearing bytes, hex.
  --   `_sha256`, NOT `_digest`: block.content_digest and segment.content_digest are 16-byte
  --   `ow128` BLOBs, and one name over two types is a join that silently never matches.
  normalizer     TEXT,                      -- NULL means raw bytes hashed; records OW-C-041
  media_type TEXT, format TEXT, bytes INTEGER,
  part_count     INTEGER,                   -- NULL until op.identify. Drives expansion.
  derived        TEXT NOT NULL DEFAULT '{}',-- the stat index's derived facts   (charter section 5 X25)
  -- EXTENDS THE CHARTER, and the extension is a column the plan names eight times as a column and
  -- never declares. 05-ingest-and-routing.md:110 and :172 both read "The host stamps
  -- `unit.trust_class` from `SourceLocator.trust_class`"; :1030 and :2848 have the audit sampler
  -- read it directly; :2140 registers `unit.trust_class` as an evidence key with domain
  -- {internal, untrusted_external}, cost FREE, est 0 ms and `null` = no. A 0-ms FREE `unit.*` fact
  -- is a roster-column read -- the same shape as `unit.bytes` and `unit.part_count`, both columns
  -- above. NOT NULL with NO DEFAULT because :2140's `null` = no means the key can never be UNKNOWN
  -- at routing time, and because both defaults the plan states are the HOST's per-connector
  -- decision, not one value: SourceLocator.trust_class defaults to INTERNAL (:70) while a card
  -- declaring `[capability.acquire] trust_class_declared = false` makes the host default the unit to
  -- `untrusted_external` (:116). A column default would silently pick one and make the other a
  -- forget-to-stamp bug that raises the audit sample nowhere.
  trust_class    TEXT NOT NULL CHECK (trust_class IN ('internal','untrusted_external')),
  acq_failure_class TEXT, acq_retry_after INTEGER,
  acq_attempts_total INTEGER NOT NULL DEFAULT 0, acq_attempts_today INTEGER NOT NULL DEFAULT 0,
  acq_last_attempt_at INTEGER,              -- the PERIOD STAMP for attempts_today
  stale_since    INTEGER,                   -- FIRST transition only; KEPT across a reset
  settled_gen INTEGER, last_seen_gen INTEGER NOT NULL,
  scope_rule     TEXT CHECK (scope_rule IN ('explicit','inherited') OR scope_rule IS NULL)
) STRICT;
CREATE INDEX unit_ready ON unit(state, last_seen_gen)
  WHERE state IN ('discovered','acquired','identified','planned');
CREATE INDEX unit_stale ON unit(stale_since) WHERE stale_since IS NOT NULL;
-- stat_fresh := size == st_size AND mtime_ns == st_mtime_ns
--                             AND st_mtime_ns + MTIME_GRANULARITY_NS(2e9) <= indexed_at_ns
-- D6 owns this predicate and its writer; D5's separate `unit_stat` table is STRUCK (section 5 X25).

-- =========================================================================================
-- THE QUEUE.  charter.md:4020-4072
-- =========================================================================================
CREATE TABLE work (
  id              INTEGER PRIMARY KEY,
  unit_uri        TEXT NOT NULL REFERENCES unit(unit_uri) ON DELETE CASCADE,
  unit_part       TEXT NOT NULL DEFAULT '',  -- '' folds NULL: NULLs are distinct in a UNIQUE index
  operator        TEXT NOT NULL,             -- '<port>.<family>' | 'op.<name>' (core-only)
  op_version      INTEGER NOT NULL,          -- the OPERATOR's schema_version int, matching
                                             --   producer.op_version, which is ALSO an INTEGER
  cache_key       TEXT NOT NULL,             -- RECORDED: a config change is a MISMATCH, not a reuse
  decision_id     TEXT REFERENCES route_decision(decision_id),   -- NULL for an `op.*` row
  sequence_id     TEXT,
  -- ---- DERIVED BY THE PLANNER FROM THE RESOLVED Candidate. Never edited elsewhere. (I22) ----
  driver          TEXT,                      -- the driver_id; NULL for an `op.*` row
  cost_class      TEXT NOT NULL CHECK (cost_class IN ('free','local_compute','billed_api')),
  dispatch_key    TEXT,                      -- sha256(driver||config_digest||isolation)[:16];
                                             --   NULL for an `op.*` row, AND A NULL BATCHES ALONE
  service         TEXT,                      -- NULL unless this unit needs a Service
  staged_gen      INTEGER,                   -- the torn-parse fix; NULL for part-granularity work
  status          TEXT NOT NULL CHECK (status IN ('pending','claimed','done','failed_transient',
                                                  'failed_permanent','deferred')),
  failure_class   TEXT, failure_message TEXT, retry_after INTEGER,
  attempts_total  INTEGER NOT NULL DEFAULT 0, attempts_today INTEGER NOT NULL DEFAULT 0,
  last_attempt_at INTEGER, stale_since INTEGER,
  claimed_by      TEXT,                      -- '<host>:<pid>:<process_create_time>'
  claimed_gen INTEGER, lease_expires INTEGER,
  cost_micros     INTEGER NOT NULL DEFAULT 0,
  queued_ms       INTEGER NOT NULL DEFAULT 0,  -- ALWAYS separate from ran_ms
  ran_ms          INTEGER NOT NULL DEFAULT 0,
  peak_rss_bytes  INTEGER NOT NULL DEFAULT 0,
  priority        INTEGER NOT NULL DEFAULT 0,  -- and it is ACTUALLY ORDERED BY
  -- AN `op.<name>` OPERATOR HAS NO DRIVER, NO ISOLATION AND NO ROUTE DECISION. `op.identify` is an
  -- ordinary operator that materialises part rows and `op.converge` must ship before the watcher;
  -- evaluate() never runs for either. Under NOT NULL columns neither could be enqueued without
  -- FABRICATING a route_decision row, which would then pollute route_scoreboard, route_spend and
  -- the resolution_report. The three columns are nullable TOGETHER, and the CHECKs make the pairing
  -- structural rather than a convention (charter.md:4046-4060):
  CHECK ((operator LIKE 'op.%') = (decision_id IS NULL)),
  CHECK ((decision_id IS NULL)  = (driver      IS NULL)),
  CHECK ((driver      IS NULL)  = (dispatch_key IS NULL))
  -- cost_class STAYS NOT NULL and an `op.*` row declares its own: op.identify and op.converge are
  -- 'free', op.cluster is 'local_compute'. A core-only step invokes no driver; it does not follow
  -- that it costs nothing.
) STRICT;
CREATE UNIQUE INDEX work_identity  ON work(unit_uri, unit_part, operator, op_version);
CREATE INDEX work_claimable ON work(cost_class, status, retry_after, priority DESC,
                                    dispatch_key, id)
  WHERE status IN ('pending','failed_transient');
CREATE INDEX work_leases ON work(lease_expires) WHERE status = 'claimed';
CREATE INDEX work_unit   ON work(unit_uri);
-- NO COUNTER TABLE: `SELECT status, count(*) FROM work GROUP BY status` is exact and cannot drift.
-- OW-S-014 is charter.md:4072's allocation and has no codes.toml row yet -- reported to the owner.
CREATE TRIGGER work_no_live_delete BEFORE DELETE ON work
  WHEN OLD.status IN ('pending','claimed','failed_transient')
  BEGIN SELECT RAISE(ABORT,'OW-S-014 refusing to delete a live work row'); END;

CREATE TABLE work_done (   -- the compaction archive: preserves EXACTLY resume + the shrink guard
  unit_uri TEXT NOT NULL, unit_part TEXT NOT NULL DEFAULT '',
  operator TEXT NOT NULL, op_version INTEGER NOT NULL,
  cache_key TEXT NOT NULL, gen INTEGER NOT NULL,
  rows_written INTEGER NOT NULL, cost_micros INTEGER NOT NULL,
  PRIMARY KEY (unit_uri, unit_part, operator, op_version)
) WITHOUT ROWID;                                     -- ~90 B/row against work's ~250 B

-- =========================================================================================
-- ONE CACHE INDEX, FIVE LAYERS, ONE GC, ONE BILL.  charter.md:4121-4146
-- =========================================================================================
CREATE TABLE cache_index (
  cache_key    TEXT PRIMARY KEY,
  recipe       INTEGER NOT NULL,              -- a bump NAMESPACES. It NEVER deletes.
  layer        TEXT NOT NULL CHECK (layer IN ('blob','call','embed','render','signal')),
  --   `CacheLayer`, never `Layer` -- that name is L2's Block layer (charter section 5 X38)
  cost_class   TEXT NOT NULL CHECK (cost_class IN ('free','local_compute','billed_api')),
  ref          TEXT NOT NULL,                 -- 'cas://ab/cd/<sha256>'
  bytes        INTEGER NOT NULL,
  unit_uri TEXT NOT NULL, unit_part TEXT NOT NULL DEFAULT '',   -- read-policy clause 5
  driver TEXT NOT NULL, driver_schema_v INTEGER NOT NULL, config_digest TEXT NOT NULL,
  origin_operator TEXT NOT NULL,              -- OWNERSHIP. Never conflated with confidence.
  spend_json   TEXT NOT NULL,                 -- the Spend that produced it -- REPLAYED ON EVERY HIT
  micros       INTEGER NOT NULL,              -- priced at creation; RE-PRICED on hit from PriceBook
  partial      INTEGER NOT NULL DEFAULT 0,    -- read-policy clause 3
  created_ns INTEGER NOT NULL, last_hit_ns INTEGER NOT NULL, hits INTEGER NOT NULL DEFAULT 0
) STRICT;
CREATE INDEX cache_gc   ON cache_index(cost_class, last_hit_ns);
CREATE INDEX cache_unit ON cache_index(unit_uri, unit_part, layer);
-- I27 IS THIS PARTIAL PREDICATE, not a policy: an automatic sweep never deletes a `billed_api`
-- entry because the namespace index it scans holds only free ones (charter.md:4670,
-- 08-runtime.md:1433, 12-performance.md:876).
CREATE INDEX cache_ns   ON cache_index(driver, driver_schema_v, recipe) WHERE cost_class='free';
-- THERE IS NO `parse` OR `derive` LAYER. If it is a row in the .owstore it is NEVER also a blob in
-- the cache (INV-1). The parse memo IS work.status='done' AND a matching work.cache_key AND
-- doc(doc_key, gen) present  (07 section 3.12 clause 1).
-- The `call` layer caches THE DRIVER'S RAW RESPONSE, not derived rows -- which is what makes a
-- re-derivation WITHIN one store cost CPU-seconds. It does NOT cross stores: this table is created
-- inside the .owstore, so a fresh store opens with an empty cache (charter erratum E5, :8725).

CREATE TABLE dep (
  dependent_id INTEGER NOT NULL REFERENCES work(id) ON DELETE CASCADE,
  kind   TEXT NOT NULL CHECK (kind IN ('unit','part','name','cohort','policy','service_model')),
  key    TEXT NOT NULL,      -- uri | 'uri#p41' | 'figure:3.1' | cohort_id | 'route:<digest>'
  digest TEXT NOT NULL,      -- the value OBSERVED when the dependent was derived
  PRIMARY KEY (dependent_id, kind, key)
) WITHOUT ROWID;
-- TWO COLUMNS, NOT THREE, and the plan disagrees with itself about which. charter.md:4156,
-- 12-performance.md:1118 (`CREATE INDEX dep_reverse ON dep(kind, key)`) and 12-performance.md:1400
-- ("ONE query on dep_reverse(kind, key)") all print two; 07-store-and-retrieval.md:989's index
-- register gives the Shape cell as `(kind, key, digest)`. Three printed statements against one
-- summary cell in a register table, so the statement wins. Reported to the owner.
CREATE INDEX dep_reverse ON dep(kind, key);
-- Invalidation is ONE QUERY, never a sweep (07 section 11.4, 08-runtime.md:1818):
--   SELECT DISTINCT d.dependent_id FROM dep d JOIN changed c
--     ON c.kind=d.kind AND c.key=d.key WHERE d.digest <> c.new_digest;
-- MAX_DEPS_PER_UNIT = 256, enforced in Store.complete(). Past it the operator MUST declare a cohort
-- dep -- coarser, always safe, over-invalidating on purpose. The `name` dep kind keys on
-- '(akind):(name_norm)' from the `anchor` table, whose `scope` column resolves the
-- document-vs-corpus ambiguity; D6's separate `defines` table is STRUCK (charter section 5 X24).

CREATE TABLE cohort (
  cohort_id TEXT PRIMARY KEY,   -- 'coh_' || sha256_canonical(the member merkle)[:24]
  name TEXT NOT NULL, member_count INTEGER NOT NULL, member_sha256 TEXT NOT NULL,
  --   `_sha256` for the same reason as unit.content_sha256: community.member_digest is an `ow128`
  --   BLOB and this is a sha256_canonical hex string. Two types, two names.
  built_gen INTEGER NOT NULL, built_ns INTEGER NOT NULL
) STRICT;
CREATE TABLE cohort_member (
  cohort_id TEXT NOT NULL REFERENCES cohort(cohort_id) ON DELETE CASCADE,
  unit_uri TEXT NOT NULL, unit_part TEXT NOT NULL DEFAULT '', content_sha256 TEXT NOT NULL,
  PRIMARY KEY (cohort_id, unit_uri, unit_part)
) WITHOUT ROWID;

-- =========================================================================================
-- DURABLE BUDGET. Closes the in-memory-ledger hole AND the cross-process over-admission hole:
-- sum(held, dim='calls', scope='provider') IS the in-flight count.  charter.md:4179-4197
-- =========================================================================================
CREATE TABLE budget_reservation (
  reservation_id TEXT PRIMARY KEY,           -- 'res_' || sha256_canonical(identity)[:24]
  run_id TEXT NOT NULL REFERENCES run(run_id) ON DELETE CASCADE,
  work_id INTEGER NOT NULL REFERENCES work(id) ON DELETE CASCADE,
  decision_id TEXT NOT NULL REFERENCES route_decision(decision_id),
  dim TEXT NOT NULL CHECK (dim IN ('micros','tokens_in','tokens_out','calls','gpu_ms','wall_ms',
                                   'cpu_ms','bytes_egress')),
  amount INTEGER NOT NULL,                   -- the p95 CEILING
  scope TEXT NOT NULL CHECK (scope IN ('run','corpus','unit','part','operator','provider')),
  scope_key TEXT NOT NULL DEFAULT '',
  claimed_gen INTEGER NOT NULL,
  expires_ms INTEGER NOT NULL,               -- == the work row's lease_expires
  state TEXT NOT NULL CHECK (state IN ('held','committed','released'))
) STRICT;
CREATE INDEX res_open   ON budget_reservation(dim, scope, scope_key) WHERE state='held';
CREATE INDEX res_expiry ON budget_reservation(expires_ms)            WHERE state='held';
-- headroom(dim,scope,key) = limit - sum(held) - sum(committed), COMPUTED IN SQL, never cached in an
-- attribute. The lease reaper releases expired reservations IN THE SAME TRANSACTION. (I29)

CREATE TABLE run (
  run_id TEXT PRIMARY KEY, generation INTEGER NOT NULL,   -- a monotonic INTEGER, NEVER a clock
  trigger TEXT NOT NULL CHECK (trigger IN ('cli','hook','upstream','watch','mcp','sdk')),
  --                                        the last two widened by charter section 5 C15
  argv TEXT NOT NULL,
  config_digest TEXT NOT NULL,      -- the FULL effective config: the manifest + the full-scan latch
  semantic_digest TEXT NOT NULL,    -- the NARROW projection that enters cache keys
  policy_digest TEXT NOT NULL, pricebook_digest TEXT NOT NULL, lock_digest TEXT NOT NULL,
  omniweave_version TEXT NOT NULL, contract INTEGER NOT NULL, schema INTEGER NOT NULL,
  --   `run.schema` is the SCHEMA MAJOR this run wrote, recorded per run. It is not a second home
  --   for the store's version: index_state.schema is the only place on disk holding
  --   '<major>.<minor>' (07 section 3.1, ADR-9), and `meta` never gains a `schema` key.
  started_ns INTEGER NOT NULL, ended_ns INTEGER,
  needs_full_scan INTEGER NOT NULL DEFAULT 0,   -- the latch; cleared only by a full reconcile
  events_dropped INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL CHECK (status IN ('running','ok','partial','failed','interrupted',
                                         'abandoned')),
  --   `run.status` is a SECOND closed vocabulary spelled `status` and it is deliberately NOT an
  --   enum_val domain; the enum_val domain is `claim_status`, over claim.status (03 section 2.1).
  manifest_path TEXT NOT NULL
) STRICT;

CREATE TABLE service_observation (
  run_id TEXT NOT NULL, name TEXT NOT NULL, config_digest TEXT NOT NULL,
  model_id TEXT NOT NULL, model_rev TEXT, base_url TEXT NOT NULL,
  lifecycle TEXT NOT NULL CHECK (lifecycle IN ('attached','spawned','failed','quarantined',
                                               'evicted')),
  capacity INTEGER NOT NULL, peak_inflight INTEGER NOT NULL DEFAULT 0,
  requests INTEGER NOT NULL DEFAULT 0, units INTEGER NOT NULL DEFAULT 0,
  gpu_ms INTEGER NOT NULL DEFAULT 0, health_failures INTEGER NOT NULL DEFAULT 0,
  cold_start_ms INTEGER, queue_p50_ms INTEGER, queue_p95_ms INTEGER,
  log_tail TEXT,                              -- THE SERVER'S OWN log tail on a failure
  PRIMARY KEY (run_id, name, config_digest)
) STRICT;

CREATE TABLE driver_observation (   -- the operability artefact: who ran, what it cost, how it died
  run_id TEXT NOT NULL, driver TEXT NOT NULL, driver_version TEXT NOT NULL,
  port TEXT NOT NULL, card_sha256 TEXT NOT NULL,
  isolation TEXT NOT NULL CHECK (isolation IN ('inproc','subproc','wasm')),
  licence_tier TEXT NOT NULL CHECK (licence_tier IN ('open','restricted','commercial','forbidden')),
  outcome TEXT NOT NULL, failure_class TEXT,
  units INTEGER NOT NULL DEFAULT 0, wall_ms_total INTEGER NOT NULL DEFAULT 0,
  cost_micros_total INTEGER NOT NULL DEFAULT 0,   -- the RUNNER priced this, not the driver
  peak_rss_bytes INTEGER NOT NULL DEFAULT 0,
  crashes INTEGER NOT NULL DEFAULT 0, quarantined INTEGER NOT NULL DEFAULT 0,
  observation_id INTEGER PRIMARY KEY        -- A SURROGATE. The natural key contains an IFNULL
  --   sentinel, which SQLite prohibits in a table-level PRIMARY KEY, and a STRICT table cannot be
  --   WITHOUT ROWID with an expression key either. The identity is the index below (ST10).
) STRICT;
CREATE UNIQUE INDEX driver_observation_identity ON driver_observation(
  run_id, driver, driver_version, outcome, IFNULL(failure_class,''));

CREATE TABLE driver_card_cache (    -- validity key MEASURED at 1.01 ms for 328 dists
  prefix TEXT NOT NULL, dist_name TEXT NOT NULL, dist_version TEXT NOT NULL,
  card_path TEXT NOT NULL, mtime_ns INTEGER NOT NULL, size INTEGER NOT NULL,
  card_json TEXT NOT NULL, card_sha256 TEXT NOT NULL,
  PRIMARY KEY (prefix, dist_name, dist_version, card_path)
) WITHOUT ROWID;

-- =========================================================================================
-- THE ROUTING LEDGER.  05-ingest-and-routing.md sections 5.4, 6.4, 7.1, 8.1, 8.2.
-- Erratum E21 (charter.md:8721) retires charter.md:2808-2932 in favour of these: route_decision
-- GAINS `cost_class` and `reason`, route_evidence.payload becomes NULLABLE and gains `swept_at`,
-- route_scoreboard is REWRITTEN to pre-aggregate each one-to-many child in its own CTE, and there
-- is deliberately NO route_decision.dispatch_key (against I22). The identity index, the
-- route_decision_monotone trigger and thresholds-are-rows are unchanged.
-- =========================================================================================
CREATE TABLE route_decision (
    decision_id      TEXT PRIMARY KEY,         -- 'dec_' || sha256_canonical(identity)[:24]
    -- ---- the eight identity columns, and nothing else in this block is one ----
    content_sha256   TEXT NOT NULL,            -- 64-char hex over the unit's NORMALISED load-
                                               --   bearing source bytes. `_sha256`, never
                                               --   `_digest`: block.content_digest is a 16-byte
                                               --   `ow128` BLOB and a BLOB never equals a TEXT.
    unit_part        TEXT NOT NULL DEFAULT '', -- '' folds NULL (NULLs are distinct in a UNIQUE)
    lane             TEXT NOT NULL,            -- a `LANES` member
    rung             INTEGER NOT NULL,         -- the `Rung` INTEGER value, not its name
    policy_digest    TEXT NOT NULL,
    pricebook_digest TEXT NOT NULL,
    hints_digest     TEXT NOT NULL,
    read_set_digest  TEXT NOT NULL,            -- over the READ SET ONLY: the (key, provider
                                               --   version, value) triples the winning path
                                               --   consulted, in read order
    -- ---- what the winning rule said. Written from `RouteDecision` (05 section 4.6). ----
    driver           TEXT NOT NULL,            -- '' == no driver ran; a GATE refusal writes ''
    cost_class       TEXT NOT NULL             -- FROZEN at decision time: the cost_class label on
        CHECK (cost_class IN ('free','local_compute','billed_api')),   -- ow_spend_micros_total and
                                               --   the `class` column of `ow cost --by driver`
                                               --   (15 section 4.2, 5.4). Reading it from the live
                                               --   catalog re-labels history after a card upgrade.
    rule_id          TEXT NOT NULL,
    rule_origin      TEXT NOT NULL,            -- 'project:.omniweave/policy.d/route.toml:41'
    cause            TEXT,                     -- 'garble.score=0.71>=0.50', from `cause_from`.
                                               --   GENERATED, so "why it escalated" is a GROUP BY
    reason           TEXT,                     -- the rule's own `reason`. Nullable, but a `skip`
                                               --   rule must record {reason, key, threshold}
    slice_key        TEXT NOT NULL,            -- '/'-joined `[slice] by`, '~' per component
    flagged_blocks   TEXT,                     -- JSON array of block ids (REPAIR, ENRICH)
    sequence_id      TEXT,                     -- minted by the planner; one per bound run of parts
    parent_decision_id TEXT REFERENCES route_decision(decision_id) ON DELETE CASCADE,
    evidence_digest  TEXT NOT NULL REFERENCES route_evidence(evidence_digest),
    -- ---- the estimate, written by price() BEFORE admit() runs ----
    est_spend        TEXT NOT NULL,            -- canonical JSON of `Spend`, all seven dimensions
    est_micros       INTEGER NOT NULL,
    reserved_micros  INTEGER NOT NULL,         -- the p95 CEILING, not the mean (05 section 6.3)
    -- ---- written after the row exists: admit()'s verdict and the sampler's ----
    admission        TEXT NOT NULL             -- `micros IS NULL` on the spend join means DEFERRED;
        CHECK (admission IN ('admitted','deferred','degraded')),   -- `micros = 0` means a free
                                               --   driver ran. 15 section 5.2 selects this column
                                               --   so the two are separable.
    audit_selected   INTEGER NOT NULL DEFAULT 0,   -- DERIVED, never random: blake2b(unit_uri ||
                                               --   part || salt) % 10000 < rate * 10000 (RT2)
    pinned           INTEGER NOT NULL DEFAULT 0,   -- a `[[pin]]` won; excluded from the scoreboard
    grant_id         TEXT,                     -- non-null IFF est_spend.bytes_egress > 0
    degraded         INTEGER NOT NULL DEFAULT 0,   -- rung = DEGRADE, or any `Degradation` recorded
    degradations     TEXT NOT NULL DEFAULT '[]',   -- JSON array of `Degradation`: a SET, not a flag
    generation       INTEGER NOT NULL,         -- the run's `generation`. AN INTEGER, NEVER A CLOCK.
    decided_at       INTEGER NOT NULL          -- wall ms, for humans and the 400-day sweep ONLY
);
-- INV-13 / RT8, and it CANNOT be a CHECK: "subqueries prohibited in CHECK constraints" (verified on
-- SQLite 3.45.1), so the DDL that tried was unrunnable and would have left the routing migration
-- unapplied with INV-13 unenforced. It is a generated trigger, with CI parity against the policy
-- compiler's rejection of a backward `escalate_to` (OW-P-005). Two enforcers, one truth.
-- OW-R-030 is charter.md:2854's allocation and has no codes.toml row yet -- reported to the owner.
CREATE TRIGGER route_decision_monotone BEFORE INSERT ON route_decision
  WHEN NEW.parent_decision_id IS NOT NULL
   AND NEW.rung <= (SELECT rung FROM route_decision WHERE decision_id = NEW.parent_decision_id)
  BEGIN SELECT RAISE(ABORT,'OW-R-030 escalation is not monotone'); END;

CREATE UNIQUE INDEX route_decision_identity ON route_decision(
    content_sha256, unit_part, lane, rung,
    policy_digest, pricebook_digest, hints_digest, read_set_digest);
CREATE INDEX route_decision_slice  ON route_decision(slice_key, rule_id, driver);  -- the scoreboard
CREATE INDEX route_decision_audit  ON route_decision(decided_at) WHERE audit_selected = 1;
CREATE INDEX route_decision_parent ON route_decision(parent_decision_id);

CREATE TABLE route_unit_decision (        -- SURVIVES `work` row deletion, so cost provenance
    unit_uri TEXT NOT NULL,               --   outlives the queue after `work_compact_above`
    unit_part TEXT NOT NULL DEFAULT '', lane TEXT NOT NULL,
    decision_id TEXT NOT NULL REFERENCES route_decision(decision_id) ON DELETE CASCADE,
    first_seen_at INTEGER NOT NULL,
    PRIMARY KEY (unit_uri, unit_part, lane, decision_id)
) WITHOUT ROWID;
-- The primary key IS the per-document index: a `GROUP BY unit_uri` over 15 section 5.2's
-- spend_attribution view is a prefix range scan of it, which is why that view adds no index of its
-- own. It is also the only table holding `unit_uri` on the routing side -- route_decision is keyed
-- on CONTENT, so one blob in three folders is one decision and three rows here.

CREATE TABLE route_evidence (             -- refcounted and content-addressed, so identical read
    evidence_digest TEXT PRIMARY KEY,     --   sets share one blob and it ages out on its own
    payload BLOB,                         -- deflate(canonical JSON of the read set). NULLABLE, and
                                          --   that is what reconciles the two retentions: blobs age
                                          --   out at 30 days and decision rows at 400, so the sweep
                                          --   NULLS the payload and stamps `swept_at` rather than
                                          --   deleting the row, which would break route_decision's
                                          --   NOT NULL foreign key into it. A swept decision still
                                          --   names the read set it was taken over; it just cannot
                                          --   be replayed. Rows whose decisions are audit_selected,
                                          --   pinned, degraded or in a REGRESSED slice are never
                                          --   swept (05 section 8.4).
    swept_at INTEGER,                     -- NULL while the payload is live. `ow route replay` prints
                                          --   the window it could actually cover.
    first_seen_at INTEGER NOT NULL, refcount INTEGER NOT NULL DEFAULT 1,
    CHECK ((payload IS NULL) = (swept_at IS NOT NULL))
);

CREATE TABLE route_signal (               -- THE cache that matters: the raster, not the decision
    content_sha256 TEXT NOT NULL, unit_part TEXT NOT NULL DEFAULT '',
    signal_key TEXT NOT NULL, signal_version TEXT NOT NULL,
    value BLOB, unavailable_reason TEXT, compute_ms INTEGER NOT NULL, computed_at INTEGER NOT NULL,
    PRIMARY KEY (content_sha256, unit_part, signal_key, signal_version)
) WITHOUT ROWID;
-- PER-SIGNAL, not per-suite: one signal's version bump must not invalidate the other fifty-three.
-- `unavailable_reason` sits beside `value` because "we tried and could not" is a cacheable fact --
-- otherwise every run re-attempts a signal whose provider is not installed (05 section 5.4).

CREATE TABLE route_spend (
    decision_id TEXT NOT NULL REFERENCES route_decision(decision_id) ON DELETE CASCADE,
    attempt INTEGER NOT NULL,                  -- 1-based. A REGEN is a NEW decision with a parent,
                                               --   so `attempt` counts retries WITHIN one decision.
    provider TEXT NOT NULL DEFAULT '',         -- '' == local, the same convention as `Spend`
    -- the seven physical dimensions, in the order `Spend` declares them. NO CURRENCY HERE (INV-15).
    wall_ms INTEGER NOT NULL DEFAULT 0, cpu_ms INTEGER NOT NULL DEFAULT 0,
    gpu_ms INTEGER NOT NULL DEFAULT 0, tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0, calls INTEGER NOT NULL DEFAULT 0,
    bytes_egress INTEGER NOT NULL DEFAULT 0,
    micros INTEGER NOT NULL DEFAULT 0,         -- `Spend.micros(book)`, priced by the RUNNER
    was_cache_hit INTEGER NOT NULL DEFAULT 0,  -- a hit replays the cached `Spend` and bills 0
    would_have_been_micros INTEGER NOT NULL DEFAULT 0,   -- what the hit would have cost at the
                                               --   CURRENT PriceBook; sums into the run manifest's
                                               --   `cost.would_have_been_micros_if_uncached`
    outcome TEXT NOT NULL,                     -- the `Outcome` wire value (08 section 1.3)
    PRIMARY KEY (decision_id, attempt)
);

CREATE TABLE route_quality (              -- NOT `route_verdict`: `Verdict` is the RETRIEVAL honesty
    quality_id INTEGER PRIMARY KEY,       --   record (07 section 6) and one name may not carry two
                                          --   types (charter section 5 X14)
    decision_id TEXT NOT NULL REFERENCES route_decision(decision_id) ON DELETE CASCADE,
    source TEXT NOT NULL CHECK (source IN ('self','agree','audit','feedback')),
    metric TEXT NOT NULL,                 -- 'norm_edit_agreement' | 'grounded_frac' | 'thumb'
    agreement REAL,                       -- [0.0, 1.0]; the scoreboard reports 1.0 - agreement
    polarity INTEGER,                     -- `feedback` only: -1 wrong, +1 right
    ref_driver TEXT,                      -- `audit` only: the `[audit] reference` driver that ran
    detail TEXT, created_at INTEGER NOT NULL
);
CREATE INDEX route_quality_decision ON route_quality(decision_id);
-- `source = 'self'` rows are WRITTEN AND NEVER SCORED: the exclusion is the scoreboard's, not the
-- writer's, so the self-versus-audit gap stays queryable as a card diagnostic (RT12).

CREATE TABLE route_threshold (k TEXT PRIMARY KEY, v REAL NOT NULL);
-- Exactly three rows, written by the policy loader from the compiled policy's `[audit]` block in
-- the SAME transaction that installs `policy_digest`, or the install refuses:
--   'audit.min_audit_n'  30      'audit.regress_at'  0.08      'audit.release_at'  0.048
-- `ow doctor` check D-12 (15 section 9.2) fails on a missing row, because a missing row makes the
-- comparison below NULL and NULL falls through to 'OK' -- a silent all-clear.
-- THE THRESHOLDS ARE ROWS AND NOT BIND PARAMETERS because "parameters are not allowed in views"
-- (verified on SQLite 3.45.1). That is what keeps the view byte-diff gateable (Q-G19) while its
-- `state` column still moves when the policy does.

CREATE VIEW route_scoreboard AS
WITH q AS (        -- ONE ROW PER DECISION. Pre-aggregated, because route_quality and route_spend
                   -- are BOTH one-to-many on `decision_id`, and joining both to route_decision in
                   -- one FROM multiplies every row by the other's cardinality.
    SELECT decision_id,
           SUM(source='audit')                                          AS audited_n,
           SUM(CASE WHEN source='audit' THEN 1.0-agreement ELSE 0 END)  AS divergence_sum,
           SUM(source='agree')                                          AS agreed_n,
           SUM(CASE WHEN source='agree' THEN 1.0-agreement ELSE 0 END)  AS agree_sum,
           SUM(source='feedback' AND polarity<0)                        AS complaints
      FROM route_quality
     WHERE source IN ('agree','audit','feedback')     -- NEVER 'self' (RT12). Filtering HERE and not
     GROUP BY decision_id                             --   in the outer WHERE is what keeps a
), sp AS (                                            --   decision whose only quality row is
    SELECT decision_id, SUM(micros) AS micros         --   'self' in `decisions_n` and in `micros`.
      FROM route_spend GROUP BY decision_id
)
SELECT d.slice_key, d.rule_id, d.driver,
       COUNT(*)                                                  AS decisions_n,
       COALESCE(SUM(q.audited_n), 0)                             AS audited_n,
       CASE WHEN COALESCE(SUM(q.audited_n),0) > 0
            THEN SUM(q.divergence_sum) / SUM(q.audited_n) END    AS divergence,
       CASE WHEN COALESCE(SUM(q.agreed_n),0) > 0
            THEN SUM(q.agree_sum) / SUM(q.agreed_n) END          AS escalation_divergence,
       COALESCE(SUM(q.complaints), 0)                            AS complaints,
       COALESCE(SUM(sp.micros), 0)                               AS micros,
       CASE WHEN COALESCE(SUM(q.audited_n),0)
                 < (SELECT v FROM route_threshold WHERE k='audit.min_audit_n') THEN 'UNKNOWN'
            WHEN COALESCE(SUM(q.audited_n),0) > 0
                 AND SUM(q.divergence_sum) / SUM(q.audited_n)
                 > (SELECT v FROM route_threshold WHERE k='audit.regress_at') THEN 'REGRESSED'
            ELSE 'OK' END                                        AS state
FROM route_decision d
LEFT JOIN q  ON q.decision_id  = d.decision_id
LEFT JOIN sp ON sp.decision_id = d.decision_id
WHERE d.pinned = 0                                    -- a pinned decision may not justify a demotion
GROUP BY d.slice_key, d.rule_id, d.driver;
-- UNKNOWN IS THE ZERO VALUE. On day one an operator sees a wall of UNKNOWN, which is the truth: at
-- rate = 0.005 and min_audit_n = 30 a slice needs 6,000 decisions before it says anything. Every
-- count is COALESCEd to 0 BEFORE it is compared, because SUM() over an all-NULL left join is NULL,
-- `NULL < 30` is NULL, and a NULL CASE arm falls through to 'OK' (05 section 8.2 property 3).

-- resolution_report: ONE ROW PER RESOLUTION, not per unit. charter.md:2937, inside the same
-- "#### Routing DDL" block as the seven route_* tables above, and specified by 04-driver-system.md
-- section 4.7 (glossary.md:962's `Specified in`). 07 section 3's 0004 row globs that block as
-- `route_*` and the glob loses this one name; no other migration row in that table names it either,
-- and its only foreign-key-free dependency is `run_id`, whose table is created above. Landed here
-- because the alternative is a table with no migration at all. Reported to the owner.
CREATE TABLE resolution_report (
    run_id TEXT NOT NULL, resolution_digest TEXT NOT NULL, port TEXT NOT NULL,
    requirement_json TEXT NOT NULL, report_json TEXT NOT NULL,   -- candidates + every rejection
    first_seen_ms INTEGER NOT NULL, hits INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (run_id, resolution_digest)
) STRICT;

-- spend_attribution: 15-observability.md section 5.2, printed there and nowhere else. I30 requires
-- every micro to name exactly one (unit, part, decision, attempt); this is the join that makes that
-- queryable, "so nobody writes it twice". Every one of its three inputs -- route_unit_decision,
-- route_decision, route_spend -- is created above, so the reference is backward and 07 section 3's
-- forward-reference table does not come into play. 07 section 3's 0004 row does not name it (it is
-- not `route_*`) and no other row does; landed here for the same reason as resolution_report.
-- NO INDEX IS ADDED, and 15 section 5.2 says why: route_unit_decision is WITHOUT ROWID with
-- PRIMARY KEY (unit_uri, unit_part, lane, decision_id), so a per-document lookup is a prefix range
-- scan of the primary key, and route_decision_slice already serves the per-driver and per-slice
-- group-bys.
CREATE VIEW spend_attribution AS
SELECT u.unit_uri, u.unit_part, u.lane,
       d.decision_id, d.rung, d.driver, d.cost_class, d.slice_key, d.pinned,
       d.grant_id, d.admission,
       s.attempt, s.provider, s.outcome, s.was_cache_hit,
       s.wall_ms, s.cpu_ms, s.gpu_ms, s.tokens_in, s.tokens_out, s.calls, s.bytes_egress,
       s.micros, s.would_have_been_micros,
       d.generation, d.decided_at
FROM route_unit_decision u
JOIN route_decision d ON d.decision_id = u.decision_id
LEFT JOIN route_spend s ON s.decision_id = d.decision_id;
-- The LEFT JOIN is correct: a `deferred` decision has no spend row, and a per-document report that
-- silently dropped deferred decisions would show a document as free when it was in fact refused.
-- `d.admission` is selected so a reader can tell `micros IS NULL` (deferred) from `micros = 0` (a
-- free driver ran). Unlike route_scoreboard it does NOT filter `pinned`, which is why the bill is
-- summed here and never there (15 section 5.2, glossary.md:1040).
