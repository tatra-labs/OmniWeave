-- 0001_eval.sql -- `.oweval`, the evaluation store: a SEPARATE SQLite file (13-quality.md
-- section 2.10, charter section D10). Not a migration of `.owstore`: eval rows are deleted and
-- corpus rows are not, and one eval run spans many stores. Its own forward-only chain, versioned
-- by `PRAGMA user_version`, which `omniweave_core.store.oweval` writes after this file applies.
--
-- The charter's DDL, verbatim but for two tables. `eval_run` gains `not_measured` and
-- `confounders`, which 13 section 11.1 makes required fields of every published row, sourced from
-- "the run", and which the charter gives no column (D814). `eval_perf` takes 12-performance.md
-- section 7.4's column names and nullability and keeps the charter's foreign key and CHECK:
--   * `peak_wal_bytes`, as 12 spells it at :1579 and :1624, beside `peak_rss_bytes`;
--   * both NULLable: a reading that was not taken is NULL, never 0 (05:2122's rule), and a peak
--     RSS is unmeasurable where `host.subproc.peak_rss_bytes` returns None;
--   * `REFERENCES eval_run ON DELETE CASCADE`, which 13:1720's prune cascades through, and the
--     five `EvalStatus` values as a CHECK.
--
-- One writer (13:380): `ow eval import`, in one transaction. No test process opens this file.

CREATE TABLE eval_corpus (
  corpus_id TEXT NOT NULL, version TEXT NOT NULL,      -- ('omniweave-golden','2026.09')
  corpus_digest TEXT NOT NULL,                          -- sha256 over sorted (relpath,sha256),
  tier TEXT NOT NULL CHECK (tier IN ('A','B','C','D')), --   NUL-framed
  n_docs INTEGER NOT NULL, n_assertions INTEGER NOT NULL, n_checked INTEGER NOT NULL,
  document_redistributable   INTEGER NOT NULL,
  assertions_redistributable INTEGER NOT NULL,
  publishable INTEGER NOT NULL,        -- may its numbers reach the PUBLIC scoreboard?
  PRIMARY KEY (corpus_id, version)
) STRICT, WITHOUT ROWID;

CREATE TABLE eval_run (
  run_id TEXT PRIMARY KEY,
  suite TEXT NOT NULL CHECK (suite IN ('parse','extract','retrieve','absence','roundtrip',
                                       'portability','perf')),
  corpus_id TEXT NOT NULL, corpus_version TEXT NOT NULL, corpus_digest TEXT NOT NULL,
  subject TEXT NOT NULL,                                -- a driver id, a profile, or a Runner
  subject_version TEXT NOT NULL,
  producer_id INTEGER,                                  -- Producer, when the subject is ours
  measured_on TEXT NOT NULL,                            -- MeasuredOn as canonical JSON. NOT NULL.
  timing_basis TEXT NOT NULL CHECK (timing_basis IN ('in_process','spawn_inclusive',
                                                     'server_attached')),
  witness TEXT NOT NULL CHECK (witness IN ('ci','self','third_party')),
  unpinned INTEGER NOT NULL DEFAULT 0,                  -- 1 when weights_revision is not a sha
  entrant_bias INTEGER NOT NULL DEFAULT 0,              -- subject.vendor == corpus.vendor. OURS TOO.
  cassette TEXT NOT NULL CHECK (cassette IN ('off','allow','required')),
  policy_digest TEXT, pricebook_digest TEXT, harness_version TEXT NOT NULL,
  code_fingerprint TEXT NOT NULL, hardware TEXT NOT NULL,
  fairness TEXT NOT NULL DEFAULT '{}',                  -- one model per role, one embedder, budgets
  spend_micros INTEGER NOT NULL DEFAULT 0,
  degradations TEXT NOT NULL DEFAULT '[]',
  started_ns INTEGER NOT NULL, ended_ns INTEGER,
  status TEXT NOT NULL CHECK (status IN ('ok','partial','unknown')),
  not_measured TEXT NOT NULL DEFAULT '[]',              -- D814: 13 section 11.1's two "the run"
  confounders TEXT NOT NULL DEFAULT '[]'                --   fields Q-G19 requires non-empty
) STRICT;

CREATE TABLE eval_assertion (            -- olmOCR-Bench's record, generalised
  assertion_id TEXT PRIMARY KEY,
  corpus_id TEXT NOT NULL, corpus_version TEXT NOT NULL,
  doc TEXT NOT NULL, page INTEGER,
  type TEXT NOT NULL,                    -- baseline present absent order table math format
                                         -- footnote + ours: cell_rel field span cite roundtrip
  spec TEXT NOT NULL,                    -- JSON: TableTest's up/down/left/right/top_heading/...
  addr TEXT,                             -- the type-free address; the owdoc evaluator resolves it
  evaluable_in TEXT NOT NULL CHECK (evaluable_in IN ('owdoc','text','both')),
  max_diffs INTEGER NOT NULL DEFAULT 0,
  checked TEXT CHECK (checked IN ('verified','rejected')),   -- NULL RUNS BUT NEVER SCORES
  derived_from_sha256 TEXT NOT NULL,     -- the licence chain FOR THE ASSERTION ITSELF
  slices TEXT NOT NULL DEFAULT '[]'
) STRICT;

CREATE TABLE eval_verdict (              -- the grain everything aggregates from
  run_id TEXT NOT NULL REFERENCES eval_run(run_id) ON DELETE CASCADE,
  assertion_id TEXT NOT NULL REFERENCES eval_assertion(assertion_id),
  evaluator TEXT NOT NULL CHECK (evaluator IN ('owdoc','text')),
  passed INTEGER NOT NULL, score REAL,
  explanation TEXT NOT NULL DEFAULT '',  -- olmOCR-Bench prints WHY. SO DO WE.
  slice_key TEXT NOT NULL, wall_ms INTEGER NOT NULL DEFAULT 0, micros INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (run_id, assertion_id, evaluator)
) STRICT, WITHOUT ROWID;
CREATE INDEX eval_verdict_slice ON eval_verdict(run_id, slice_key);

CREATE TABLE eval_metric (
  run_id TEXT NOT NULL REFERENCES eval_run(run_id) ON DELETE CASCADE,
  metric TEXT NOT NULL, slice_key TEXT NOT NULL DEFAULT '__macro__',
  value REAL, n INTEGER NOT NULL, ci_lo REAL, ci_hi REAL,
  method TEXT NOT NULL CHECK (method IN ('closed_form','exact','resampled','none')),
  truth_kind TEXT NOT NULL CHECK (truth_kind IN ('human','rendered','native_run','synth_ocr',
                                                 'agreement','self')),
  state TEXT NOT NULL CHECK (state IN ('ok','regressed','unknown')),   -- UNKNOWN IS THE ZERO VALUE
  PRIMARY KEY (run_id, metric, slice_key)
) STRICT, WITHOUT ROWID;
-- truth_kind='agreement' and 'self' may NEVER populate an accuracy column (Q-G9).
-- truth_kind='native_run' may ONLY anchor a FIDELITY metric, never recall/coverage/classification.

CREATE TABLE eval_calibration (
  eval_set_id TEXT NOT NULL, score_kind TEXT NOT NULL, producer_id INTEGER NOT NULL,
  slice_key TEXT NOT NULL, bucket INTEGER NOT NULL,
  bucket_lo REAL NOT NULL, bucket_hi REAL NOT NULL,
  n INTEGER NOT NULL, n_correct INTEGER NOT NULL,
  p_hat REAL NOT NULL, wilson_lo REAL NOT NULL, wilson_hi REAL NOT NULL,
  ece REAL, brier REAL,                                  -- NULL for ordinal signals
  label_sources TEXT NOT NULL,                           -- '["synth_ocr:L3","human"]'
  measured_at_ns INTEGER NOT NULL, harness_version TEXT NOT NULL,
  PRIMARY KEY (eval_set_id, score_kind, producer_id, slice_key, bucket)
) STRICT, WITHOUT ROWID;

CREATE TABLE eval_counter (
  run_id TEXT NOT NULL REFERENCES eval_run(run_id) ON DELETE CASCADE,
  counter TEXT NOT NULL, scope TEXT NOT NULL, value INTEGER NOT NULL,
  PRIMARY KEY (run_id, counter, scope)) STRICT, WITHOUT ROWID;

CREATE TABLE eval_perf (
  run_id TEXT NOT NULL REFERENCES eval_run(run_id) ON DELETE CASCADE,
  budget_id TEXT NOT NULL,
  pacer_before_ns INTEGER NOT NULL, pacer_after_ns INTEGER NOT NULL, work_ns INTEGER NOT NULL,
  time_ratio REAL NOT NULL,                              -- work_ns / mean(pacer_before, after)
  peak_rss_bytes INTEGER, peak_wal_bytes INTEGER,        -- NULL: not measured. Never 0 (D814)
  status TEXT NOT NULL CHECK (status IN ('pass','fail','unstable','stale','unknown')),
  PRIMARY KEY (run_id, budget_id)) STRICT, WITHOUT ROWID;

CREATE TABLE eval_flake (
  test_id TEXT NOT NULL, day TEXT NOT NULL,
  runs INTEGER NOT NULL, fails INTEGER NOT NULL, reran_green INTEGER NOT NULL,
  PRIMARY KEY (test_id, day)) STRICT, WITHOUT ROWID;

-- THE PUBLISHING VIEW. UNKNOWN is the zero value, exactly as route_scoreboard.
CREATE VIEW eval_scoreboard AS
SELECT m.metric, m.slice_key, r.suite, r.subject, r.subject_version, r.corpus_version,
       r.witness, r.unpinned, r.entrant_bias, m.value, m.ci_lo, m.ci_hi, m.n, m.method,
       m.truth_kind, c.publishable,
       CASE WHEN m.state = 'unknown'                              THEN 'UNKNOWN'
            WHEN c.publishable = 0                                THEN 'WITHHELD'
            WHEN r.witness <> 'ci' OR r.unpinned = 1
              OR r.entrant_bias = 1
              OR m.truth_kind IN ('agreement','self')             THEN 'UNRANKED'
            ELSE 'RANKED' END AS standing
FROM eval_metric m
JOIN eval_run r USING (run_id)
JOIN eval_corpus c ON c.corpus_id = r.corpus_id AND c.version = r.corpus_version
WHERE r.status <> 'unknown';
