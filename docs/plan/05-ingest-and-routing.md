# 05 — Acquisition, Parsing and the Routing Engine

**In one paragraph.** Bytes become a document in four mechanical steps, each of which writes a row
before it spends anything: the host turns a `SourceLocator` into a per-invocation `Locator`, an
`acquire/1` driver turns that into an `owroster-items/1` stream, and the host commits that stream
as `unit` roster rows plus content-addressed blobs; content-first detection turns a blob into a
ranked `tuple[RankedGuess, ...]` and a `format_evidence` record; the router evaluates a
first-match-wins TOML policy over a flat `Evidence` record for one `(unit_part, lane)` and writes
an immutable `route_decision` naming the winning rule, its file and line, the read set it
consulted and the estimate it reserved; and `admit()` reserves that estimate against a durable
`BudgetLedger` before any driver runs. Escalation is monotone in `Rung`, evidence is acquired by a
`DemandPlan` in ascending `CostClass` so a clean born-digital page renders no raster and starts no
model server, and every number the router acts on is a registered `Signal` whose provider version
enters the decision's identity. This document specifies acquisition, detection, the rung and lane
model, the policy grammar and its evaluation order, every day-one escalation signal, the cost
model, replay, the quality loop, the failure taxonomy, and three documents traced part by part.

## What this document depends on and does not restate

| I depend on | Stated in | The contract in one line |
|---|---|---|
| `owdoc`, `Block`, `Quad`, `OriginSpan`, `Capabilities`, `PageKind`, the `doc`/`page` DDL | [03-document-model.md](03-document-model.md) | `doc.format_evidence` is TEXT holding the JSON §2.4 defines; `page.method` records the branch that ran on that page; `PageKind` is closed at `page\|slide\|sheet\|frame\|stream`. |
| Ports, `DriverCard`, `resolve()`, `DriverIO`, `[cost.model]`, probes, isolation, operator registration | [04-driver-system.md](04-driver-system.md) | `resolve()` is pure and never chooses; the router hands it a requirement and consumes a `Candidate`. `AcquireV1` is 04 §1.4's, verbatim: `enumerate(locator: Locator, io: DriverIO) -> DriverResult` emitting `owroster-items/1`, and `fetch(ref: UnitRef, io: DriverIO) -> DriverResult`. |
| `Segment`, the graph lanes, `unit_part = 'seg:<hex16>'` | [06-structure-extraction.md](06-structure-extraction.md) | The graph lanes reuse this document's grammar, loader, evaluator and linter verbatim under `surface = "graph"`. |
| The `unit`/`work` DDL, the claim, `cache_index`, the water mark, `Admission` | [08-runtime.md](08-runtime.md) | The Supervisor drains the roster; this document owns the roster's *states* and the router's rows. |
| `BudgetLedger`, `budget_reservation`, headroom computed in SQL | [08-runtime.md](08-runtime.md) | `admit()` calls it; this document owns what a denial means. |
| `Degradation` and its `kind` literal | [15-observability.md](15-observability.md) | One `Degradation` type for the whole framework. This document *raises* members (`budget`, `signal_unavailable`, `driver_unavailable`, `grant_missing`, `policy_pruned`, `rung_ceiling`, `quarantine`) and mints no parallel type; `RouteDecision.degradations` and `route_decision.degradations` carry a set of them, never a flag. |
| `Store`, `ingest_scope`, `stat` | [07-store-and-retrieval.md](07-store-and-retrieval.md) | Everything the router writes goes through `Store`; `sqlite3.connect` exists in exactly one module. |
| The `retrieval` surface of the same grammar | [07-store-and-retrieval.md](07-store-and-retrieval.md) | One grammar, one loader, one linter, three `surface` values. |
| Retention policy, consent records and deletion paths for personal-device connectors | [14-security.md](14-security.md) | Every connector in §1.3 whose source is a person's account attaches to that contract before it ships. |

Everything else below is this document's to specify.

---

# Part 1 — Acquisition

## 1.1 The source abstraction

Acquisition has one host-side input type and one output effect. The input is a `SourceLocator`; the
effect is `unit` rows plus blobs in the content-addressed store. Nothing else in the framework
converts a user-supplied string into a filesystem or network read. A driver never receives a
`SourceLocator`: the host projects one onto a ports-level `Locator` once per `INVOKE`, and it is the
`Locator` — never the `SourceLocator` — that crosses seam **S4**.

```python
# omniweave_core.ingest.locator — HOST-SIDE. stdlib only, because `ow add` constructs one of these
# before any driver is loaded. `omniweave_ports` does not import this module and no driver sees it.
class SourceKind(StrEnum):
    FILE      = "file"        # one path
    DIR       = "dir"         # a walked tree, with include/exclude globs
    URL       = "url"         # one http(s) fetch, no link following
    CRAWL     = "crawl"       # a bounded same-origin walk from a seed URL
    CONNECTOR = "connector"   # a named acquire driver over a third-party store
    STREAM    = "stream"      # bytes handed in by the caller; no re-read, no mtime

class TrustClass(StrEnum):
    INTERNAL           = "internal"
    UNTRUSTED_EXTERNAL = "untrusted_external"

@dataclass(frozen=True, slots=True)
class SourceLocator:
    kind: SourceKind
    ref: str                      # a path, a URL, or '<connector>:<connector-local id>'
    include: tuple[str, ...] = () # fnmatch globs against the path relative to roots.source
    exclude: tuple[str, ...] = ()
    recursive: bool = True
    follow_symlinks: bool = False # NEVER True for an untrusted tree: a symlink escapes [roots]
    max_depth: int = 32
    trust_class: TrustClass = TrustClass.INTERNAL
    since: int | None = None      # a connector cursor floor; ns since epoch, connector-interpreted
    options: Mapping[str, Scalar] = field(default_factory=dict)   # connector-specific, digested
```

`TrustClass` is the enum behind `unit.trust_class`. It is **not** `TrustTier` (a driver-supply-chain
fact) and **not** `Trust` (a Block's provenance tier). Three enums, three jobs.
`follow_symlinks` defaults to `False` because a symlink in an untrusted tree is the cheapest way out
of `[roots] source`, and `OW_PATH_OUTSIDE_ROOTS` (`OW-A-007`) is a refusal, not a warning.

### From a user string to a `Locator`

`ow add`, `ow ingest`, a hook, the watcher and `ow_add` all build a `SourceLocator` — `ow_add` through
`resolve_locator(s) -> SourceLocator`, the fail-closed classifier
[14-security.md](14-security.md) §4.2 specifies, which refuses `file:`, `data:`, `ftp:`, `gopher:` and
`jar:` **at the locator** with `OW_UNSUPPORTED_LOCATOR_SCHEME` (`OW-A-044`) and `confine()`s a bare
path to `[roots] source` before any `stat`. `SourceLocator` is therefore the only type that crosses
the user-string-to-read boundary (14's **B1**), and it stops in the host.

Per invocation the host projects it onto `Locator{scheme, target, cursor, since_ns}`
([04](04-driver-system.md) §1.3), whose `scheme` must be a member of the driver's
`[capability.acquire] schemes`:

| `SourceKind` | `Locator.scheme` | `Locator.target` |
|---|---|---|
| `file`, `dir` | `file` | `canonical_uri()`'s path form of `ref` — `realpath`, `normcase`, forward slashes |
| `url` | `http` or `https`, from the parsed URL | the normalised absolute URL of §1.2's `url` row |
| `crawl` | `http` or `https` | the seed URL; the frontier is the driver's own state, serialised into `next_cursor` |
| `connector` | the connector family segment of `ref` — `imessage`, `slack`, `drive` | the `<connector-local id>` half of `ref` |
| `stream` | `stream` | `''`; the bytes ride in the `INVOKE` body and there is nothing to address |

Every other field on the `SourceLocator` reaches the driver — or does not — by exactly one route, and
the routes are exhaustive:

| `SourceLocator` field | where it goes |
|---|---|
| `since` | `Locator.since_ns` |
| the resume token | `Locator.cursor`, read from the last committed `unit.cursor` (§1.4). Persisted across runs only where the card declares `[acquire] cursor_opaque = true` |
| `include`, `exclude`, `recursive`, `max_depth`, `follow_symlinks` | `HELLO.effective_config`, so they enter `config_digest` — **and** they are re-applied by the host's enumerate loop, which is the authoritative guard: a driver that ignores them can waste syscalls but can never widen the scope |
| `options` | `HELLO.effective_config`, digested as `options_digest`; a secret named by `[ingest] password_file` is excluded from both digests |
| `trust_class` | **nowhere.** The host stamps `unit.trust_class` from it (04 §1.5 obligation 3: a driver never forges provenance or trust) |

Two consequences worth stating. Two scopes over one tree with different `include` globs compile to two
`config_digest`s and therefore two `subproc` workers, which is correct rather than wasteful — the glob
is part of what the walked-path cache salt distinguishes. And because `trust_class` never crosses S4,
a connector can neither raise nor lower its own audit sample: a card declaring
`[capability.acquire] trust_class_declared = false` makes the host default the unit to
`untrusted_external`, which *raises* the sample from `0.005` to `0.05` (§8.1).

### The `acquire/1` Port

The Port's signatures are [04-driver-system.md](04-driver-system.md) §1.4's and are not restated here:
`AcquireV1.enumerate(locator: Locator, io: DriverIO) -> DriverResult`, emitting `owroster-items/1`,
and `AcquireV1.fetch(ref: UnitRef, io: DriverIO) -> DriverResult`, both in `omniweave_ports/ports.py`
beside the `probe` classmethod and the static-config `__init__` every Port declares. What this
document owns is the *stream's* record shapes and the host-side enumerate loop that consumes them —
not the protocol.

### The `owroster-items/1` record shapes

Two record types on one NDJSON stream, in the same shape as `owdoc-fragment/1` and for the same
reason: a driver addresses its own findings by a per-invocation `tmp` id and the host mints every
durable identity (04 §1.5 obligation 2, charter §5 X1). `enumerate` emits a run of `candidate`
records; `fetch` emits exactly one `fetched` record, beside the `raw_bytes` artefact it names.

```jsonc
// enumerate -> `roster_items`. METADATA ONLY: a candidate record never carries bytes.
{"t":"candidate","tmp":"c/000417","id":"docs/q3-10k.pdf","connector":"fs",
 "next_cursor":"docs/q3-10k.pdf\u000012934771","size":184320,
 "mtime_ns":1756944000000000000,"etag":null,"media_type_hint":"application/pdf",
 "labels":{"walk_depth":2}}

// fetch -> one `fetched` record beside the `raw_bytes` CAS blob it wrote.
{"t":"fetched","content_sha256":"9f2c…","source_sha256":"a41b…","bytes":184320,
 "blob_ref":"cas://9f/2c/9f2c…","media_type_hint":"application/pdf","etag":null,
 "fetched_at_ns":1757030400123456789}
```

| field | on | meaning |
|---|---|---|
| `t` | both | `candidate` or `fetched`. An unknown `t` is a protocol error the host's reader refuses; it is never skipped, because a silently ignored record is a silently missing document |
| `tmp` | candidate | the per-invocation record address, unique within one `enumerate` and dense from `c/000001`. It is what a `LOG` frame refers to and it never reaches the store |
| `id` | candidate | the **connector-local stable id**: a path relative to `Locator.target`, a Drive file id, a message `guid`, a `channel/ts`. The host mints `unit_uri = canonical_uri(locator, id)` (§1.2). This is the only identity a driver supplies and it is not a `unit_uri` |
| `connector` | candidate | the driver's family segment — `fs`, `url`, `imessage` — which becomes the `unit_uri` scheme for `SourceKind.CONNECTOR`. Checked against the card's own id, so one connector cannot mint into another's namespace |
| `next_cursor` | candidate | the resume token **after** this record. `null` means this connector is not resumable, and a card declaring `[capability.acquire] addressing = "uri_with_cursor"` while emitting `null` fails the `acquire` conformance suite |
| `size` | candidate | `null` when the source cannot say without a fetch; the pre-fetch guard then falls through to the bounded read in `fetch` |
| `mtime_ns` | candidate | the `stat_fresh` triple's mtime member (§1.4); `null` for a source with no modification time |
| `etag` | both | an HTTP `ETag`, a Drive `revisionId`, a Slack thread `ts` — opaque, stored on `unit.derived["etag"]` |
| `media_type_hint` | both | a **hint**. It never wins over magic bytes: it enters detection at ladder step 7, `basis = "declared"`, confidence 0.30 (§2.1) |
| `labels` | candidate | a flat `Mapping[str, Scalar]` written to `unit.derived`. Not a place to smuggle a digest or a price |
| `content_sha256` | fetched | over the **normalised load-bearing bytes**, 64 hex chars (§1.2) |
| `source_sha256` | fetched | over the **raw** bytes as delivered → `doc.source_sha256` |
| `bytes` | fetched | the raw byte count actually read |
| `blob_ref` | fetched | `cas://ab/cd/<sha256>`, written through `io.blobs.put()` under the bounded read below |
| `fetched_at_ns` | fetched | when the bytes were read — retention's input, and what distinguishes a `304` from a re-read |

Four classes of key are **absent by construction**, each because the host owns the fact:

- **no `unit_uri`.** The host calls `canonical_uri()` on `(Locator, id)`. This is obligation 2 —
  no `block_id`, `unit_uri`, `segment_id` or `entity_id` ever crosses the wire *from* a driver — and
  it is what makes a roster stream portable between stores and stops a connector minting a sibling's
  primary key.
- **no `trust_class`.** The host stamps `unit.trust_class` from `SourceLocator.trust_class`
  (obligation 3).
- **no `state`, `gen` or `last_seen_gen`.** Roster state is the host's state machine (§1.5), and a
  driver that could write it could resurrect an `out_of_scope` unit.
- **no money.** `DriverMetrics` carries `bytes_read` and the other physical units; a connector reports
  `Spend`, never micros (INV-15).

`fetched` therefore carries no identity at all: `fetch` is invoked with a host-built `UnitRef` and the
`RESULT` frame's `unit_index` says which unit it answers. A connector recovers its own id from
`UnitRef.uri` by inspection, which is possible because `canonical_uri()`'s connector form is
`<connector>://<stable connector id>` and its container-child form appends an encoded fragment
(§1.2) — the connector-local half is recoverable by construction, so the host never hands a driver
back a row it wrote.

`SourceKind.STREAM` is the one kind whose `unit_uri` cannot be minted from a `candidate` record, because
`stream://sha256/<source_sha256>` needs the digest (§1.2). Its roster row is therefore written in the
`fetched` batch rather than the `candidate` batch, its `id` is the `tmp` id, and `next_cursor` is
`null` — a stream is never resumable and never re-read.

### The host's enumerate loop, and what bounds its memory

The stream shape is forced by two facts: the roster commits at 512 rows per transaction with no
planning phase, and `DriverIO` carries no store handle, so a connector cannot know when to stop — the
host stops reading. `owroster-items/1` rides as an `ArtifactRef` on the single `RESULT` frame
`omniweave-driver/1` allows per unit (charter frame table row 6; 04 §6.2), inline under
`INLINE_MAX = 262_144` bytes and a CAS blob above it, and the host reads it **line by line**:

```
open the roster_items artefact           # a stream, never a materialised list
buffer 512 `candidate` records -> one transaction (the ON CONFLICT upsert of §1.3 rule 5)
  between batches: producer_should_pause(claimable)?
      yes -> STOP READING THE STREAM. Keep the last committed record's `next_cursor`.
      no  -> continue
per candidate, before any fetch: glob, depth, hidden, skip and size guards (below)
```

Peak host residency is one record plus one 512-row batch — a few hundred KiB — whatever the corpus
size, and that is what bounds memory. Resumption is a fresh `INVOKE` with `Locator.cursor` set to the
kept token, which is why `enumerate` **must** be resumable from any emitted `next_cursor`;
`[acquire] max_units_per_call = 5000` bounds one call, so a million-file tree is 200 invocations
rather than one, each of which the water mark can end early. A connector that emits its whole
enumeration as a single record, or that buffers the corpus before emitting its first, defeats all of
this and may not declare `[capability.acquire] streaming = true`.

`enumerate` and `fetch` are split because change detection needs metadata without paying for bytes. A
connector that cannot enumerate without reading its container (an mbox is one file; an iMessage
`chat.db` is one file holding thousands of logical units) declares `granularity = "corpus"` on its
card and emits one `candidate` record per logical unit while reading the container once; the split is
about the *host's* cost model, not the number of syscalls.

**The size guard runs in `enumerate` and `fetch`, never at `GATE`.** `GATE` evaluates on a `unit` row
in state `identified`, which is after `fetch()` — so a rule cannot be what keeps a 2 GB file from
being read. Two mechanisms, in this order:

1. The host's enumerate loop refuses a candidate whose `size > ingest.max_unit_bytes` **before
   calling `fetch`**: `unit.state = 'failed'`, `acq_failure_class = 'too_large'`, no blob written.
2. `fetch` reads `max_unit_bytes + 1` bytes and raises
   `DriverError(TOO_LARGE, limit="ingest.max_unit_bytes")` if the extra byte arrives. This is the
   `size = null` case and the lying-`Content-Length` case; a declared length is attacker-supplied.

`gate.too-large` survives as the belt-and-braces rule for a unit acquired under a larger earlier cap,
and it is the only path on which the failure table's "the bytes are never read" is false.

## 1.2 Unit identity

`unit.unit_uri` is the roster's primary key and the join key for every downstream row. It is produced
**in the host** by `canonical_uri()` in `omniweave_core.identity`, over the invocation's `Locator` and
the candidate record's connector-local `id`:

| kind | `canonical_uri()` | why |
|---|---|---|
| `file`, `dir` | `realpath` → `normcase` → forward slashes → strip a Windows `\\?\` prefix | two spellings of one path must not make two units; `normcase` is what makes `C:\A\B.PDF` and `c:/a/b.pdf` one row |
| `url` | scheme+host lower-cased, default port dropped, path percent-normalised, fragment dropped, query **kept and sorted by key** | a fragment never changes the bytes; a query usually does |
| `connector` | `<connector>://<stable connector id>` — a Drive file id, a message `guid`, a Slack `channel/ts` | a title or a folder path is not an identity; both move |
| `stream` | `stream://sha256/<source_sha256>` | a stream has no external name, so its content *is* its name |

A **container child** appends a fragment: `<parent unit_uri>#<kind>/<path>`, where `kind` is `att`,
`zip`, `msg` or `part`, and `<path>` is percent-encoded with `/` `#` `?` `%` and every byte outside
`[A-Za-z0-9._~-]` escaped — so a member named `a#b/c` cannot forge a sibling's identity, and a
non-UTF-8 member name is representable. A fragment over 512 bytes is truncated to its first 400
encoded bytes plus `~<sha256(full path)[:16]>`, which bounds `unit_uri` and keeps two long members
distinct.

The cache salt is the walked path **relative to `roots.source`** (charter §5 X25), so a checkout at a
different absolute path reuses the cache; `unit_uri` itself is absolute. Two keys, deliberately.

`unit.content_sha256` is over the **normalised load-bearing bytes**; `doc.source_sha256` is the raw
bytes. Normalisation exists so a PDF re-saved with a new `/ModDate`, or a DOCX round-tripped through a
different producer, is not a new document. The normaliser is per format, recorded in
`unit.normalizer`; NULL means the raw bytes were hashed and records `OW-C-041`.

| format | normaliser | drops |
|---|---|---|
| `pdf` | `pdf_trailer_v1` | `/ModDate`, `/CreationDate`, `/ID`, XMP `xmp:MetadataDate`, linearisation hint tables |
| OPC (`docx`/`pptx`/`xlsx`) | `opc_v1` | ZIP local-header timestamps, `docProps/app.xml` `TotalTime`/`Revision`, `cp:lastModifiedBy`, `w:rsid*` |
| ODF/EPUB | `ocf_v1` | ZIP timestamps, `meta.xml` `dc:date`, `meta:editing-duration` |
| everything else | *none* | — raw bytes are hashed |

A normaliser is **read-only and total**: it digests a projection of the bytes and never rewrites the
stored blob. It runs under the same bounds as a container identity read (§2.5): at most 64 KiB of any
metadata part, no DTD, no entity expansion. If it raises, the raw digest is used and a `Diag` is
recorded; the failure mode is "re-parse a document we could have skipped", never "treat two documents
as one".

## 1.3 The connector roster

Release 1 ships four `acquire/1` drivers in the `omniweave` distribution. The rest are out of tree,
and this table is the *specification* of what each must do — the format knowledge ported from LEANN's
`apps/` and markitdown's converter set, not their scripts. LEANN's readers `sqlite3.connect` straight
at a live application database (`LEANN/apps/history_data/history.py:52`) with `except Exception` around
the label map (`:111`, `:198`), which is the opposite of this framework's posture; markitdown's breadth
(`_outlook_msg_converter`, `_rss_converter`, `_youtube_converter`, `_wikipedia_converter`,
`_bing_serp_converter`, `_ipynb_converter`) is what is worth porting, and its
`DocumentConverterResult = (markdown, title)` is what to leave behind.

| driver id | source of truth | enumerate unit | cursor | change detection | day 1 |
|---|---|---|---|---|---|
| `acquire.fs.local` | a walked tree | one file | `<relpath>\0<inode>` at the last emitted record | `stat_fresh` triple | **yes** |
| `acquire.url.http` | one URL | one response body | — | `If-None-Match` / `If-Modified-Since`, then `content_sha256` | **yes** |
| `acquire.crawl.http` | a seed URL | one page | the frontier's serialised BFS state | per-URL `ETag`, plus same-origin and `max_pages` bounds | **yes** |
| `acquire.stream.inline` | caller bytes | one blob | — | none — a stream is always new | **yes** |
| `acquire.mail.mbox` | an mbox file | one message | `<file>\0<byte offset>` | file `stat_fresh` + per-message `Message-ID` | no |
| `acquire.mail.applemail` | `~/Library/Mail/**/*.emlx` | one `.emlx` | the last `.emlx` path in sorted order | per-file `stat_fresh`. The **first line of an `.emlx` is a decimal byte count, not content** (`LEANN/apps/email_data/email.py:172`); LEANN's own mbox conversion writes `From <name> <body>` on one line (`:178`), corrupting every `From ` delimiter | no |
| `acquire.chat.imessage` | `~/Library/Messages/chat.db` | one `chat` thread | `max(message.ROWID)` | monotonic `ROWID`. `message.date` is **nanoseconds since 2001-01-01 UTC** on macOS ≥ 10.13 and seconds before it — discriminate on magnitude, and use a UTC epoch: `imessage_data/imessage_reader.py:59` builds a naive local `datetime(2001,1,1)` and is wrong by the host's UTC offset | no |
| `acquire.chat.slack` | the Slack Web API through an MCP server | one channel-day | `<channel>\0<oldest ts>` | Slack `ts` is monotonic per channel | no |
| `acquire.chat.wechat` | a WeChatTweak JSON export directory | one contact | `<contact>\0<last msg id>` | export directory `stat_fresh` | no |
| `acquire.browser.chromium` | `<profile>/History` (SQLite) | one visited URL's content, not the row | `max(urls.last_visit_time)` | monotonic WebKit visit time (µs since 1601-01-01; subtract 11 644 473 600 s — `history.py:57`). **The DB is copied before reading — Chrome holds it open** | no |
| `acquire.export.chatgpt` | a ChatGPT export `.zip` / `.html` | one conversation | `<zip sha256>\0<conversation index>` | archive `content_sha256` | no |
| `acquire.export.claude` · `.gemini` · `.qwen` | a vendor export | one conversation | as above | as above | no |
| `acquire.social.twitter` | bookmarks via an MCP server | one bookmark | the API's own cursor | an opaque API cursor | no |
| `acquire.mail.outlook` | `.msg` (an OLE compound file) | one message | `<file>` | file `stat_fresh` | no |
| `acquire.feed.rss` | an RSS/Atom feed | one item | `<feed>\0<newest guid>` | per-item `guid`, then `content_sha256` | no |
| `acquire.wiki.mediawiki` | a MediaWiki API | one article | `<title>\0<revid>` | `revid` is monotonic | no |
| `acquire.video.youtube` | a video id | one transcript | — | transcript revision, else `content_sha256` | no |
| `acquire.repo.git` | a working tree at a commit | one tracked file | the commit sha | `git status --porcelain` plus the commit sha | no |
| `acquire.object.s3` | a bucket prefix | one object | the `ContinuationToken` | `ETag` + `Content-Length` | no |

Six rules bind every connector, day-one or not.

1. **A credential is read from the OS keystore or an env var named by the card, never from a config
   file and never logged.** A missing credential is `ProbeVerdict(UNAVAILABLE)` naming it, so
   `resolve()` rejects the driver instead of failing halfway through a corpus.
2. **A connector that reads a live application database copies it first.** Chromium's `History` and
   Messages' `chat.db` are held open by the owning application; a direct read is either `SQLITE_BUSY`
   or a torn snapshot. Copy, read the copy, delete the copy — recorded as `bytes_read`, not as a
   hidden cost.
3. **`trust_class = untrusted_external` unless the operator says otherwise.** `acquire.url.http`,
   `acquire.crawl.http`, `acquire.feed.rss`, `acquire.wiki.mediawiki` and `acquire.social.twitter`
   default to it, which raises the audit sample from `[audit] rate = 0.005` to
   `untrusted_external_rate = 0.05` — the only bound the framework has on trusting that a text layer
   matches its pixels.
4. **`enumerate` emits metadata only.** A `candidate` record never carries bytes. A connector that
   must fetch to know a size emits `size = null`, and the pre-fetch guard falls through to the
   bounded read in `fetch`.
5. **Enumeration is idempotent under concurrency.** Roster writes are
   `INSERT INTO unit(...) VALUES(...) ON CONFLICT(unit_uri) DO UPDATE SET last_seen_gen =
   max(last_seen_gen, excluded.last_seen_gen), cursor = excluded.cursor` — so two `ow ingest`
   processes over the same scope converge instead of racing, and neither resets a state machine the
   other advanced.
6. **A logical unit is expanded by exactly one process.** A container or corpus-granularity unit is
   claimed by the same enqueue-before-lock transition every other unit uses: the expanding process
   moves the parent to `acquiring` in one transaction, and a second process that observes `acquiring`
   with an unexpired lease skips it. Without this, two workers mint two child sets for one mbox and
   the `ON CONFLICT` upsert hides the doubled `bytes_read`.

## 1.4 Change detection

Three mechanisms, tried in this order, at three prices. A ladder, not a choice.

```
stat_fresh   size == st_size AND mtime_ns == st_mtime_ns
             AND st_mtime_ns + MTIME_GRANULARITY_NS(2e9) <= indexed_at_ns        [0 bytes read]
             * the third clause is the point: a file modified inside the mtime granularity window
               of the last index cannot be PROVEN unchanged, so it is NOT fresh. The stat triple is
               captured BEFORE the content read (charter §D6), so a write racing the read is caught.
cursor       the connector's own monotonic token (ROWID, revid, ts, ETag)        [1 round trip]
digest       content_sha256 over normalised load-bearing bytes                   [full read]
```

`stat_fresh` is the only mechanism that costs nothing and the only one available to the `fs`
connector, which is 100% of the reference ingest. It is also the only one that can be wrong in the
unsafe direction — a file rewritten in place with identical size inside one mtime tick — and the third
clause is what closes that. `ow ingest --verify-digests` promotes every unit to the digest rung for one
run; the run manifest records that it did. A settled unit failing only that clause is hashed against its doc's raw digest instead of re-parsed (D645).

For `acquire.url.http` the cursor rung is a **conditional request**: `If-None-Match` from
`unit.derived["etag"]`, else `If-Modified-Since` from `unit.mtime_ns`. A `304` costs one round trip and
zero body bytes and is recorded as `unchanged_cursor`. A `200` whose `content_sha256` equals the stored
one is recorded as `unchanged_digest` and does **not** mint a new `gen` — a server that ignores
conditional requests must not re-parse a corpus every hour.

A cursor is stored on `unit.cursor` — **per unit, not per connector** — because enumeration can be
interrupted at any point and the resume token that matters belongs to the last unit actually
committed. A connector-wide cursor in a separate table goes stale against a partially committed batch,
which is the failure LEANN's per-index `meta.json` has.

**Deletion.** `unit.last_seen_gen` is stamped on every discovery pass. A unit whose
`last_seen_gen < run.generation` after a **complete** scan of its scope (`ingest_scope.complete = 1`)
is marked `state = 'out_of_scope'` with `acq_failure_class = 'unseen'`; its blocks are **not** deleted,
because a shipped `cite` must still resolve. `ow store gc --unseen-for <days>` is the only path that
removes them, and it prints the `cite` count it is about to retire. An **incomplete** scan never marks
anything out of scope: `ingest_scope`'s absent-row rule — "coverage unknown, never nothing was
excluded" — applies to partial rows too. `out_of_scope` carries two causes and
`acq_failure_class` is what distinguishes them: `'unseen'` (it disappeared) and `'filtered'` (the
pre-fetch glob, size or `skip` guard excluded it).

## 1.5 The ingest queue contract

The roster is the queue's input; the queue is [08-runtime.md](08-runtime.md)'s. What this document
owns is the state machine on `unit.state` and who may advance it. The nine states are the charter's
`unit.state` CHECK constraint verbatim — there is no `partial` state, because `partial` is a
`doc.status`, and a unit whose parts partly failed reaches `settled`.

```
              ow add / ow ingest / a hook / the watcher / ow_add
                                |
                                v
     +------- discovered ----- op.identify cannot run yet: no bytes
     |             |  acquire/1 fetch()        (an acquire.* driver; cost_class from its card)
     |             v
     |        acquiring ---+--> failed        (acq_failure_class, acq_retry_after)
     |             |       +--> out_of_scope  (acq_failure_class='filtered')
     |             v
     |        acquired ----- DETECTION runs here. FREE. No driver invoked.
     |             |  op.identify   (an operator; cost_class='free'; no route_decision)
     |             v
     |       identified ---- unit.part_count is NOT NULL; part rows may be expanded
     |             |  the router: evaluate() per (part, lane) -> route_decision rows
     |             v
     |         planned ----- work rows exist, admitted or deferred
     |             |  the Supervisor claims
     |             v
     |         running ---+--> settled  (every part terminal; doc.status in ok|partial)
     +--> out_of_scope    +--> failed   (a permanent FailureClass, no doc row)
          ('unseen')      settled --> discovered when stat_fresh fails: stale_since stamped (D645)
```

Five rules make this contract usable by a hook, an agent and a human without three code paths.

1. **Enqueue-before-lock** (charter §5 X31). `ow_add` writes `unit` rows plus one `ingest_scope` row
   in a single transaction and only then spawns a detached `ow ingest --scope <scope_id>` child. A
   caller that dies between the write and the spawn loses the *drain*, never the *work*: the next
   `ow ingest` picks up every `discovered` row.
2. **A read never blocks on a refresh.** `omniweave-serve` may write roster rows and read `work`
   state; it may not import `omniweave` and therefore cannot route or drain. There is exactly one
   drain implementation and it is `ow ingest`.
3. **`trigger.kind` is stamped on the `run` row and is an evidence key.**
   `cli | hook | upstream | watch | mcp | sdk`. `gate.watcher-may-not-bill` and
   `gate.agent-triggered-may-not-bill` clamp `max_cost_class` to `local_compute` for `watch`, `mcp`
   and `sdk`, so an agent calling `ow_add` cannot spend money a human did not approve by typing
   `ow add --allow-cost <micros>`. This is why `RouteHints` has no budget field.
4. **Acquisition retries are counted separately from parse retries.** `unit.acq_attempts_total`,
   `acq_attempts_today` and `acq_last_attempt_at` are the acquire-side twins of `work.attempts_*`. A
   rate-limited connector must not consume a document's parse retry budget.
5. **Backpressure pauses discovery, never drops it.** `producer_should_pause(claimable)` is the
   `queue_high_water = 50000` / `queue_low_water = 25000` hysteresis; on a pause the host **stops
   reading the `owroster-items/1` stream** between 512-row batches and keeps the last committed
   record's `next_cursor`, and the next `INVOKE` resumes from it. A connector that buffers its whole
   enumeration before emitting a first record breaks this and fails the `acquire` conformance
   suite.

### `[ingest]` — the configuration block

`omniweave.toml` has no acquisition section; this one is additive. Every key carries an
`OMNIWEAVE_*` twin and is classified for `tools/config_axes.toml` (G18) — all `operational` except
`normalize`, which defines `unit.content_sha256` and therefore the identity of every document.

```toml
[ingest]
include         = ["**/*"]              # fnmatch, relative to roots.source
exclude         = ["**/.git/**", "**/node_modules/**", "**/.omniweave/**", "**/~$*"]
follow_symlinks = false                 # a symlink escapes [roots]; OW-A-007 is a refusal
max_depth       = 32
max_unit_bytes  = 2_147_483_648         # 2 GiB. Enforced in enumerate, then by a bounded read.
max_parts       = 10_000                # above it: GATE refuse unless --accept-partial (D644 reads it)
normalize       = true                  # SEMANTIC: it defines unit.content_sha256
verify_digests  = false                 # promote every unit to the digest rung for this run
hidden          = false                 # dotfiles are excluded unless named explicitly
password_file   = ""                    # a TOML map of unit_uri glob -> OS-keystore secret name

[ingest.url]
allow              = false              # DENY BY DEFAULT (docling's enable_remote_fetch, inverted)
allow_hosts        = []                 # an explicit allowlist; [] with allow=true means "any public"
allow_ports        = [80, 443]          # graphify validates the SCHEME and never the PORT
deny_host_suffixes = [".internal", ".local", ".cluster.local", ".svc", ".consul"]
max_fetch_bytes    = 52_428_800         # 50 MB — graphify/graphify/security.py:22
max_text_bytes     = 10_485_760         # 10 MB for html/text — security.py:23
connect_timeout_ms = 5_000
read_timeout_ms    = 30_000
max_redirects      = 5                  # each hop re-validated; a redirect to a private IP refuses
user_agent         = "omniweave/<RELEASE> (+https://omniweave.dev/bot)"

[ingest.crawl]
max_pages      = 200
max_depth      = 3
same_origin    = true                   # false requires an allow_hosts entry per extra origin
respect_robots = true
delay_ms       = 500
```

**Passwords.** `[ingest] password_file` points at a TOML file mapping a `unit_uri` glob to a secret
*name*; the name resolves through the OS keystore, never through the file. `--password-file <path>`
overrides it for one invocation ([ADR-15](adr/0015-encrypted-pdfs-and-document-passwords.md) D15.3: and `OW_SECRET_<NAME>`). The secret reaches the driver as `DriverIO` config (D15.4: through the invocation's host-deleted tmpdir; `DriverIO` keeps its four fields), is excluded from
`config_digest` and from `options_digest`, and never appears in an event, a `Diag` or the run
manifest. A successful open records `Diag(OW_DOC_DECRYPTED)` and sets `doc.x.ow.decrypted = true`;
`unit.encrypted` is recomputed as `false` after the successful open, because the document is now
readable.

### URL and crawl safety

`acquire.url.http` and `acquire.crawl.http` implement graphify's SSRF design plus the three gaps
`mine-risk.md` §11.1 names in it. Six properties, all mechanical:

1. `_ALLOWED_SCHEMES = {"http", "https"}` (`graphify/graphify/security.py:20`). `file:`, `data:`,
   `ftp:` and `gopher:` are refused **at the locator**, not at the fetch — markitdown's `convert_uri`
   accepts `file:` (`markitdown/packages/markitdown/src/markitdown/_markitdown.py:419`), which turns
   any string a model emits into an arbitrary local read.
2. **The port is validated.** `grep -n "port" graphify/graphify/security.py` returns only plumbing —
   nothing checks `parsed.port` — so `http://public.example:6379/` reaches a public host fronting
   Redis, SMTP or memcached, and HTTP request-smuggling into a line-based protocol is the classic
   exploitation. `[ingest.url] allow_ports` is an allowlist and everything else refuses.
3. **One DNS resolution, then connect to the validated IP.** A pre-flight `getaddrinfo()` followed by
   the stdlib's own second resolution at connect time is a TOCTOU hole; graphify resolves twice
   (fail-closed both times, but two lookups and two error paths). Here `validate_url` is
   scheme/host-shape only, and the connection classes — subclasses of
   `http.client.HTTPConnection`/`HTTPSConnection` — resolve **once**, validate, and connect to that
   exact address; the TLS variant sets `server_hostname` to the original hostname so SNI and
   certificate validation still work. `socket.getaddrinfo` is **never** monkey-patched: that is
   thread-unsafe under concurrent fetches.
4. **One IP classifier, shared by the host-shape check and the connect-time check**, failing closed on
   the *first* blocked address rather than trying the next — a hostname with both a public and a
   private A record is refused entirely. It rejects `is_private`, `is_reserved`, `is_loopback`,
   `is_link_local`, plus RFC 6598 CGN `100.64.0.0/10` (which `is_private` misses and which covers
   Alibaba Cloud's `100.100.100.200` metadata endpoint), and it **unwraps** RFC 6052 NAT64
   `64:ff9b::/96` to the embedded IPv4 before deciding, because Python marks that prefix
   `is_reserved` while it carries legitimate public traffic and a naive check breaks IPv6-only
   networks (`security.py:83-100`).
5. **Names are filtered as well as addresses.** graphify's `_BLOCKED_HOSTS` is
   `{"metadata.google.internal", "metadata.google.com"}` — GCP only. `deny_host_suffixes` closes the
   general case, which is any future metadata service on a publicly-resolving internal name.
6. **Byte caps are enforced with a bounded read.** Read `max_fetch_bytes + 1`; if the extra byte
   arrives, raise `DriverError(TOO_LARGE, limit="ingest.url.max_fetch_bytes")`. Every redirect hop
   re-runs 1-5, the scheme may not change away from `http(s)`, and a chain that revisits a URL already
   in the chain is refused as a loop.

**Robots.** `acquire.crawl.http` fetches `/robots.txt` once per origin per run and caches the parse
for the run. The longest matching `Disallow` for `user_agent`, else for `*`, wins (RFC 9309 §2.2.2). A
`4xx` on `/robots.txt` is *allow all* and a `401`/`403` is *disallow all* (RFC 9309 §2.3.1.3); a
`Crawl-delay` larger than `[ingest.crawl] delay_ms` raises the delay. `respect_robots = false` is
refused unless `[ingest.url] allow_hosts` names every origin explicitly, so "ignore robots" cannot be
a corpus-wide default.

---

# Part 2 — Format detection

## 2.1 Content first, extension last, never a single-candidate guess

Detection produces a **ranked tuple**, not a value. Every enabled driver's `sniff()` may contribute,
the host merges, and the winner plus every loser lands in `doc.format_evidence` so a wrong route is
diagnosable from the store alone.

`StreamHint` and `FormatGuess` are declared once, in `omniweave_ports`
([04](04-driver-system.md) §1.3): `StreamHint` is
`(filename, extension, declared_media_type, byte_len)` and `FormatGuess` is
`(media_type, format_token, confidence, consumed_bytes)`. Neither carries a `basis` and neither
carries `trust_class` — `TrustClass` is this document's and `omniweave_ports`' `layers.toml` row is
`[]`. The host wraps each guess:

```python
# omniweave/route/detect.py — HOST side, never in omniweave_ports.
Basis = Literal["magic", "container_identity", "content_probe",
                "extension", "declared", "driver_sniff"]

@dataclass(frozen=True, slots=True)
class RankedGuess:
    """A FormatGuess plus what only the host can say about it. This is what ranks, what enters
    `doc.format_evidence`, and what the ladder in 05 §2.1 emits."""
    guess: FormatGuess
    basis: Basis
    detail: str                      # 'PK\x03\x04 + OPC officeDocument -> wordprocessingml.document'
```

`confidence` is a plain float and `FormatGuess` is **not** a registered `Signal`, so RT5/RT6's
calibration gates do not apply: a sniffer's confidence is an ordering key inside detection, never a
number a rule compares against a `@thresholds` value.

The ladder runs once per unit at the `acquired → identified` transition, entirely FREE:

```
0.  bytes == 0                                     -> format='empty', GATE refuse, corrupt_input
1.  read HEAD = the first 8192 bytes (one read; the stream is NEVER advanced past it)
2.  magic-byte table over HEAD                     -> basis='magic',              confidence 0.99
3.  if the magic names a CONTAINER (ZIP/OLE/gzip/tar/mbox) -> open it, read its OWN identity part
                                                   -> basis='container_identity', confidence 0.98
4.  every ENABLED parse driver whose card declares detects = true gets sniff(HEAD, hint)
                                                   -> basis='driver_sniff',       confidence CLAMPED 0.95
5.  content probes for signature-free text formats (2.3)
                                                   -> basis='content_probe',      confidence 0.60-0.90
6.  extension, from an explicit table              -> basis='extension',          confidence 0.40
7.  hint.declared_media_type                       -> basis='declared',           confidence 0.30
8.  nothing                                        -> format='unknown', GATE refuse, unsupported_format
```

Candidates are ranked by **`(basis_rank, -confidence, format_token)`** over the `RankedGuess` — `magic`
< `container_identity` < `driver_sniff` < `content_probe` < `extension` < `declared` — which is a total
order, so detection is deterministic across a re-run and across drivers loading in a different order.
Basis outranks confidence rather than the reverse because the confidence bands per basis are disjoint
by construction (0.99, 0.98, ≤ 0.95, 0.60-0.90, 0.40, 0.30) and a driver's contribution is **stamped**
`driver_sniff` by the host rather than self-declared: a driver returning `confidence = 0.95` must lose
to the host's own signature and must beat a content probe, and one comparison rule gives both. Ties
broken by insertion order are the same class of bug as ties broken by storage order in a retrieval
fusion.

**A third-party sniffer is untrusted input.** Step 4 is an extension point a hostile or merely buggy
driver could use to claim every document, so it is bounded four ways: its `confidence` is clamped to
**0.95**, below both `magic` and `container_identity`, so a real signature always wins; it may return
at most **8** guesses (the rest are dropped and counted); a `sniff()` that raises, or that exceeds a
**5 ms** budget, is abandoned and recorded as
`Degradation(kind="signal_unavailable", wanted_driver=<id>)`; and `consumed_bytes` lets the host
assert the stream was not advanced. The conformance `detect` suite passes a non-seekable wrapper and
asserts the position is unchanged. *(Build note, D967: step 4 is still not run (D568), and an independent driver measured what that costs. A SubRip parser written against the ports alone passed all eleven mandatory suites, and `ow add` could not route its format. The host read every `.srt` as `txt` by content probe, and `resolve()` refused a card whose formats missed it (`format_unsupported`). A new format reaches the router under its own token only once step 4 runs. Separately, a worker imports a driver from the installed environment and inherits no `PYTHONPATH`, by design, so a project card's code must be installed.)*

## 2.2 The detection table

Ordered as evaluated. Every row is checkable against a file with `xxd`.

| # | test on HEAD | format | media type | notes |
|---|---|---|---|---|
| 1 | `%PDF-` **anywhere in the first 1024 bytes** | `pdf` | `application/pdf` | not a prefix test: ISO 32000 implementations accept leading junk and real corpora contain it (`anydoc/src/formats/detect.rs`) |
| 2 | `7B 5C 72 74 66` (`{\rtf`) prefix | `rtf` | `application/rtf` | the group that must open every RTF |
| 3 | `D0 CF 11 E0 A1 B1 1A E1` | *container* | — | [MS-CFB]; go to 2.5 OLE |
| 4 | `50 4B 03 04` (`PK..`) | *container* | — | go to 2.5 ZIP |
| 5 | `1F 8B` | *container* | — | gzip; go to 2.5 archives |
| 6 | `ustar` at offset 257 | *container* | — | tar |
| 7 | `37 7A BC AF 27 1C` / `52 61 72 21 1A 07` / `FD 37 7A 58 5A` | *container* | — | 7z, rar, xz; go to 2.5 |
| 8 | `89 50 4E 47 0D 0A 1A 0A` | `png` | `image/png` | |
| 9 | `FF D8 FF` | `jpeg` | `image/jpeg` | |
| 10 | `RIFF` + `WEBP` at 8 | `webp` | `image/webp` | |
| 11 | `49 49 2A 00` / `4D 4D 00 2A` | `tiff` | `image/tiff` | multi-page: `part_count` from the IFD chain |
| 12 | `BM` + a header-size field of 12, 40, 108 or 124 at offset 14 | `bmp` | `image/bmp` | `BM` alone is two ASCII letters and matches prose |
| 13 | `GIF87a` / `GIF89a` | `gif` | `image/gif` | `part_count` from the image-descriptor count; `page_kind='frame'` |
| 14 | an `ftyp` box at offset 4 | `mp4` | `video/mp4` | `page_kind='frame'` |
| 15 | `OggS` / `fLaC` / `ID3` / `FF Fx` / `RIFF`+`WAVE` at 8 | `ogg`/`flac`/`mp3`/`wav` | audio | `page_kind='stream'` |
| 16 | `1A 45 DF A3` | `matroska` | `video/x-matroska` | |
| 17 | `SQLite format 3` + `00` | `sqlite` | `application/vnd.sqlite3` | refused at GATE unless a connector named it: a database is a *source*, not a document |
| 18 | `From ` at offset 0 **and** an RFC 5322 header block within 8 KiB | `mbox` | `application/mbox` | *container*; go to 2.5 |
| 19 | an RFC 5322 header block at offset 0 with `Received:` or `Message-ID:` | `eml` | `message/rfc822` | *container*; go to 2.5 |
| 20 | `%!PS-Adobe` | `ps` | `application/postscript` | refused: no licence-clean interpreter ships |
| 21 | a UTF-8/UTF-16 BOM, or valid UTF-8 with no C0 controls but tab/CR/LF | *text* | — | go to 2.3 content probes |

Anything else with a byte in `0x00-0x08` or `0x0E-0x1F` in HEAD is **binary and unrecognised** →
`format = 'unknown'`. The framework never runs a text decoder over a binary blob to see what happens;
that is how markitdown's `PlainTextConverter` turns a corrupt PDF into a document of mojibake.

`unit.format` and `doc.format` hold a **format token**, not a media type, because the mapping is
one-to-many in both directions: `application/zip` is five formats and `doc` has a legacy alias.
Core's token set is forty-eight at release 1 and `unit.format`'s **domain** is that set ∪ the union of
the `token` fields of `[capability.parse] format_tokens` over enabled drivers — see §5.1. The domain
is **computed, never closed**: a third party's token joins it by enabling the card, and nothing in
this document may compare against the literal 48 where the computed domain is meant. Core's
forty-eight are generated into `enum_val` under the domain `format`:

```
pdf docx doc pptx ppt xlsx xls csv tsv rtf odt ods odp epub html xhtml xml md txt json jsonl
ipynb svg eml msg mbox png jpeg webp tiff bmp gif mp4 matroska mp3 wav flac ogg ps sqlite
zip tar gz sevenz rar xz          (containers — never a parse target, only an expansion source)
empty unknown                     (two terminal non-formats, so a GATE rule can name them)
```

Forty-eight tokens, and **every one of them is named by a rule in §4.4** — with no card contributing
a token, the union of the `unit.format` literals across all `GATE` and `DECODE` rules equals this set
exactly. Check 10 asserts that union against the **computed** domain rather than against the literal
48, so enabling a card that contributes `warc` raises both sides together and the check still holds.
That check is why a third party adding a format cannot get a silent non-route: it adds a `sniff()`
contribution, a `[capability] formats` entry, a `[capability.parse] format_tokens` **pair** and a
policy rule, or the linter fails naming the driver and the unnamed tokens. Check 2 additionally resolves
every literal a `str`-dtype signal is compared against against that signal's `SignalSpec.domain`, so a
rule naming `"wordprocessingml"` instead of `"docx"` fails the linter rather than silently matching
nothing — which is precisely how marker's `PageHeader` spelling silently disabled its own furniture
guard.

**The media-type-to-token mapping, which the computed domain needs.**
`format_token_for(media_type: str) -> str | None`, in `omniweave/route/detect.py`, is a total lookup
built from exactly two sources, both keyed on the media type each `FormatGuess` carries:

| source | shape | contributes |
|---|---|---|
| core's table | 48 rows, `media_type -> token`, generated from this section's detection table and §2.3's probe table | the forty-eight |
| every enabled card's `[capability.parse] format_tokens` | a list of `{media_type, token}` **pairs** ([04](04-driver-system.md) §2.2) | one row per pair |

The card key is pair-shaped precisely so this lookup can be built: a card's `[capability] formats`
holds media types and nothing else in the card would say which token each maps to, so a bare token
list would leave `format_token_for` undefined on every driver-contributed media type. Two enabled
cards pairing one `media_type` with different `token`s is a card-activation error (`OW-D-024`,
[04](04-driver-system.md) §2.2) naming both drivers and both pairs, which is what keeps the lookup
single-valued and total. A `FormatGuess` whose `format_token` is not in the union is dropped with
`Diag(OW_DETECT_UNKNOWN_TOKEN)` naming the driver, because a token no policy can name is a silent
non-route; a `FormatGuess` whose `media_type` and `format_token` disagree with the card's own pair is
the same drop, and the `capability` conformance suite fails the card for it first.

## 2.3 Content probes and ambiguity resolution

Signature-free text formats need probes. Each returns a confidence and is bounded to the first 1024
bytes of HEAD, except CSV, which needs a newline. Comments are stripped before the XML/HTML regex
ladder runs, or an HTML tag inside an XML comment decides the format (docling's ladder,
`docling/datamodel/document.py:488-562`).

| probe | test | confidence |
|---|---|---|
| ipynb | JSON with top-level `nbformat` **and** `cells` | 0.95 |
| xhtml | `<?xml` in the first 1000 chars **and** `xhtml` present | 0.90 |
| svg | an `<svg` element with an `xmlns` of `http://www.w3.org/2000/svg` | 0.90 |
| xml | `<?xml`, or a `<!DOCTYPE ROOT …>` / `<ROOT` pair | 0.85 |
| html | an optional script element, then one of `<!doctype html`, `<html`, `<head`, `<body` | 0.85 |
| jsonl | every one of the first 8 non-blank lines parses as a JSON *object* | 0.80 |
| json | the whole HEAD is a prefix of one JSON value and byte 0 is `{` or `[` | 0.75 |
| csv / tsv | contains a newline; `csv.Sniffer().sniff()` succeeds; the delimiter is comma, semicolon, tab or pipe; ≥2 columns on ≥3 consecutive lines. A tab delimiter yields `tsv`, everything else `csv` | 0.70 |
| md | the extension is one of `.md .markdown .qmd .rmd`, **and** a heading, list or fence token appears | 0.65 |
| txt | valid text and no other probe fired | 0.50 |

Markdown is deliberately extension-gated: content-probing Markdown makes `.xyz` Markdown, which
docling explicitly documents as a thing not to do.

**Ambiguity resolution — four cases, four outcomes.** The ranking in §2.1 already picks the winner;
these four cases say what *else* happens.

1. **One candidate above 0.90 and no other above 0.60.** `format_evidence.ambiguous = false`.
2. **Two candidates within 0.05 of each other, both above 0.60.** The ranking rule decides, the loser
   is kept in `format_evidence.rejected`, and `Diag(OW_FORMAT_AMBIGUOUS)` is recorded. The route
   proceeds. This is the `csv`-vs-`txt` and `html`-vs-`xml` case and it is not worth a refusal.
3. **The winner's `basis` is `extension` or `declared`.** The unit is routed, `doc.confidence` records
   `format_basis = "weak"`, and the `fields` and `table` lanes are **refused** for it — a schema
   extraction over a format guessed from a filename is a fabricated answer waiting to happen.
4. **Magic bytes contradict the extension.** The magic wins, always, and
   `Diag(OW_FORMAT_EXTENSION_MISMATCH)` names both. This is the `.pdf` that is really a `.docx` and
   the `.txt` that is really a 400 MB SQLite file. Recorded *on the doc*, so a reviewer finds every
   one with one query.

## 2.4 `doc.format_evidence` — the exact JSON

Byte-canonical, sorted keys, `allow_nan=False`. `rejected[]` carries a flattened `RankedGuess` plus
one extra key, `superseded_by`, naming the basis that beat it.

```json
{
  "v": 1,
  "chosen": {"format": "docx",
             "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
             "confidence": 0.98, "basis": "container_identity",
             "detail": "OPC rel officeDocument -> /word/document.xml; root w:document",
             "consumed_bytes": 8192},
  "rejected": [{"format": "zip", "confidence": 0.99, "basis": "magic", "detail": "PK 03 04",
                "consumed_bytes": 4, "superseded_by": "container_identity"}],
  "hint": {"extension": ".doc", "media_type_hint": "application/msword"},
  "ambiguous": false,
  "extension_mismatch": true,
  "container": {"depth": 0, "member_path": null},
  "providers": [{"driver": "parse.office.anydoc", "driver_version": "0.2.4", "guesses": 1}]
}
```

## 2.5 Container formats

A container is a format whose *contents* are the documents. Four kinds, four identity rules, one
shared budget.

**ZIP.** Read the ZIP's own identity part, never the member names alone. `mimetype` — stored
uncompressed as the first member — *is* the identity for ODF and EPUB OCF. For OPC, resolve the
package-level `officeDocument` relationship in `_rels/.rels`, read the content type of the part it
designates from `[Content_Types].xml`, and **fall back to that part's mandated root element** when the
content types are stale or generic, which is what non-Microsoft producers ship. docling's
`"word/document.xml" in names` heuristic (`docling/datamodel/document.py:564-588`) is one level too
shallow and mis-detects those. If neither a mimetype part nor a resolvable relationship exists, the
format is `zip` and it is expanded as an archive.

**The identity read is itself bounded, in the host.** `mimetype`, `_rels/.rels` and
`[Content_Types].xml` are read at most **64 KiB** each under the bounded-read-then-check rule, and any
of them containing `<!DOCTYPE` or `<!ENTITY` in those bytes is refused outright with
`DriverError(RESOURCE_LIMIT, limit="MAX_IDENTITY_BYTES")`. No legitimate OPC or ODF identity part has
a DTD, and `xml.etree.ElementTree`'s default parser *does* expand internal entities, so billion-laughs
otherwise reaches the **host** through detection rather than only the driver. This is the one XML bound
this document owns; `MAX_XML_DEPTH` and `MAX_XML_NODES` are the driver's.

**OLE compound file.** Open the CFB and scan the root storage for the stream each binary Office format
mandates, case-insensitively (producers ship `WORKBOOK` and `BOOK`): `WordDocument` → `doc`,
`PowerPoint Document` → `ppt`, `Workbook`/`Book` → `xls`. A root storage containing
`EncryptedPackage` sets `unit.encrypted = true` and leaves `format = 'unknown'`, and the unit is
refused as `encrypted` by `gate.encrypted` — the inner format is genuinely unknowable and guessing it
produces a wrong `failure_class`. A `.msg` is an OLE file whose root storage holds
`__properties_version1.0` and `__substg1.0_*` streams; it is a container, not a `doc`.

**Email.** `eml` and `msg` are expanded, not parsed: the message becomes one unit whose parts are the
body (`text/plain` preferred, `text/html` when that is all there is) plus one child unit per
attachment at `<parent>#att/<n>/<encoded filename>`, each with its own detection pass. `mbox` is a
container of `eml`. An attachment's `trust_class` is **inherited from the message and never
upgraded**: an internal-looking DOCX attached to an external email is external.

**Archives.** `zip`, `tar`, `gz`, `sevenz`, `xz` and `rar` expand to child units at
`<parent>#zip/<encoded member path>`. Every member path is sanitised: an absolute path, a drive
letter, a `..` segment, or a name whose realpath escapes the extraction root is **skipped and
counted** in `ingest_scope.skipped_why` — never written. This is zip-slip, and DataFlow ships
**eleven** unguarded `extractall()` calls (`dataflow/cli_funcs/cli_webui.py:229,236,294,301`, six
`statics/pipelines/*` files, `dataflow/utils/kbc/mineru_api_caller.py:27`).

### The container budget and the recursion limit

markitdown's `ZipConverter` recurses through the same dispatcher with **no depth tracking, no entry
count cap, no per-entry size cap, no total-decompressed cap and no path sanitisation** — it calls
`zipObj.read(name)` into memory for every member and re-enters `convert_stream`
(`markitdown/packages/markitdown/src/markitdown/converters/_zip_converter.py:96-116`) — and it is
registered by default. anydoc's `src/package/limits.rs` is the correction and its values are the floor
here, because real-world documents sit orders of magnitude below every one of them.

```python
# omniweave_core/limits.py — CEILINGS. effective = min(tenant_cap, declared, HOST_MAX).
MAX_ENTRY_BYTES            = 134_217_728    # 128 MiB, one member decompressed  (limits.rs)
MAX_CONTAINER_TOTAL_BYTES  = 536_870_912    # 512 MiB from one container tree   (limits.rs)
MAX_ENTRY_COUNT            = 100_000        # members visited in one tree       (limits.rs)
MAX_CONTAINER_DEPTH        = 3              # a zip in a zip in a zip. The fourth refuses.
MAX_CONTAINER_UNITS        = 10_000         # child units one container may mint
MAX_IDENTITY_BYTES         = 65_536         # one container identity part, read in the HOST
```

`MAX_XML_DEPTH = 256`, `MAX_XML_NODES = 2_000_000`, `MAX_GRID_SLOTS = 4_000_000`, `MAX_EXPANSION` and
`MAX_EXPANSION_TEXT_BYTES` are enforced *inside* `parse.office.anydoc` and surface as
`RESOURCE_LIMIT{limit}`; they are the driver's fixed limits, not the host's, and the host does not
duplicate them.

Four enforcement rules, and the first is the one that matters:

1. **Bounded read, then check.** Read `MAX_ENTRY_BYTES + 1`; if the extra byte arrived, refuse. You
   never allocate the bomb. A post-hoc length check has already spent the memory, which is the
   difference between a refusal and an OOM kill.
2. **The tree budget is charged before per-member work, and it is one accumulator for the whole
   expansion tree** — a `ContainerBudget` threaded through the recursion, not a per-level counter,
   exactly as anydoc threads `self.total_read` (`src/package/archive.rs`). Two 300 MB siblings inside
   one 512 MB budget must fail on the second, not pass twice.
3. **A limit breach is fatal and may not be swallowed.** `DriverError(RESOURCE_LIMIT)` is never caught
   by the container walker's per-member `except`, which catches only `UNSUPPORTED_FORMAT` and
   `CORRUPT_INPUT`. anydoc's `is_fatal()` exists so a "try the optional part, ignore failures" helper
   cannot absorb a bomb.
4. **The expansion is charged to acquisition and enqueued through the water mark.**
   `MAX_CONTAINER_UNITS` bounds one container; nothing bounds 10,000 containers, so the corpus-level
   bound is `producer_should_pause()`, not a constant. Child units are written 512 rows per
   transaction like any other enumeration, and their bytes count against
   `unit.derived["container_bytes"]`, which is what `ow store residue` reads to find a corpus that is
   90% zip members. Exactly one process expands a given container (§1.3 rule 6).

A container's own `unit` row reaches `settled` with **no `doc` row at all** and zero blocks: it is a
directory, not a document. There is therefore nothing for the `empty_result` rule in Part 9 to
exempt, and `PageKind` needs no `container` member. Its children carry
`unit.derived["container_parent"]` and a non-zero `format_evidence.container.depth`.

---

# Part 3 — Rungs and lanes (what a "tier" is)

The blueprint's numbered tiers `0..3` plus `S` are struck: a number conflates spend with capability
and is the wrong join key for a scoreboard. What replaces it is `Rung` × `Lane` × driver, where `Rung`
says how far down the escalation we are and the driver's `[cost.model]` says what it costs. A cheap
high-capability driver and an expensive low-capability one are both expressible; under a number
neither was.

| `Rung` | what runs | cost per part | good at | day-1 driver | terminal? |
|---|---|---|---|---|---|
| `GATE` = 0 | nothing. Limits, encryption, format, corpus filters, trigger clamps, lane admission. | 0 | refusing before spending; turning a filter *verdict* into a signal instead of an exclusion | — (host) | on `refuse`/`skip` |
| `DECODE` = 1 | deterministic decode of a text layer, office XML or a text format | office **4.4 ms** median, 14/14 formats, 94 of 100 documents judged (`anydoc/README.md` benchmark table); PDF **8 ms/page target**, `ow conform` writes the measurement | native reading order, byte-exact spans on the PDF glyph branch, tables with real spans | `parse.office.anydoc`, `parse.text.builtin`, `parse.pdf.pdfium` | office/text: **yes** |
| `REPAIR` = 2 | surgical per-block repair on an otherwise-good part | one crop call per flagged block, and **N block calls are ~7× a single full-part call** on llama.cpp (`marker/marker/builders/ocr.py:76-84`) | fixing three garbled lines without re-reading a clean page | `parse.page.olmocr` (crop mode) | no |
| `PAGE` = 3 | one full-part model call | olmocr p50 **2.4 s** (charter §D6 reference ingest); 854 micros at the §6.2 pricebook | scans, broken text layers, handwriting, math-dense pages, anything where context matters | `parse.page.olmocr` | no |
| `REGEN` = 4 | regeneration of the failed subset on a temperature ladder | 1-3× a `PAGE` call, strictly serial | repeat loops, truncation, invalid structured output | the same driver, a new attempt | no |
| `DEGRADE` = 5 | a different, **cheaper** strategy, always marked `degraded` | at or below `DECODE` | producing a citable partial instead of a hole | `parse.pdf.pdfium` | yes |
| `ENRICH` = 6 | a cross-part / cross-block model pass, scoped by block type, non-fatal | varies; billed | captions, table repair, math notation, cross-page joins | `derive.*` (see [06](06-structure-extraction.md)) | yes |

Because `promote_frac = 0.0` in `balanced`, the 7× arithmetic is why the shipped policy promotes on
*any* flagged block instead of repairing block by block; `--profile fast` sets `0.5` and takes the
other side of the same trade, which is marker's own split (`marker/marker/builders/line.py:465-481`).

Four properties a reviewer should be able to state from memory:

- **`REPAIR` is structurally unavailable on the PDF path at release 1, and the policy makes that
  mechanical rather than prose.** Block-level repair needs `block.type`, which on PDF needs a layout
  detector, and every candidate is licence-blocked: `surya/surya/settings.py:153` points the layout
  detector at `hf://datalab-to/surya_layout2` under a `MODEL_LICENSE` whose clause 2(c) is a
  competitor bar with no threshold and whose clause 8 is viral on Output (`marker/MODEL_LICENSE`,
  `surya/MODEL_LICENSE` and `lift/MODEL_LICENSE` are byte-identical at md5
  `e1f69b64dee2f1641a9b1ab12adf24d6`). `layout.class_hist` is therefore absent, `block.type` is
  UNKNOWN on PDF, and `repair.never-escalate-furniture` declares `on_unknown = "match"` → every PDF
  block is `not_eligible` for `REPAIR`. Office formats reach `REPAIR` fully, because their
  `block.type` is in the XML. Every affected decision records `cause = "layout_unavailable"`.
- **`DEGRADE` is a forward move.** It has a higher `Rung` than `PAGE` while running a cheaper driver.
  That is the entire reason `Rung` and `Spend` are separate types: `child.rung > parent.rung` stays
  enforceable (RT8's trigger) while the cost goes down.
- **`ENRICH` is non-fatal by construction.** A failed `ENRICH` leaves the part at whatever it achieved
  and records a `Degradation`; it never demotes `doc.status`.
- **A rung is not a driver.** `parse.page.olmocr` serves `REPAIR`, `PAGE` and `REGEN`; the rung changes
  the render profile and the acceptors, not the executable.

## 3.1 Lanes are independent passes over the same part

A `Lane` is a question asked of a part, and the five parse lanes ask different questions that must be
answerable at the same time. `text` is mandatory and always admitted. `table`, `math`, `fields` and
`caption` are **admitted by a lane-admission modifier** (§4.2) at `GATE` or `DECODE`-select, and each
admitted lane then runs its own rung loop with its own first-match-wins rule list and its own
`route_decision` rows — which is exactly what the charter's identity index anticipates by including
`lane` in the key.

This is not decoration; it is what makes the shipped policy coherent. Under a single first-match-wins
list per rung, `decode.skip-block-recheck-on-clean-parts` matching would prevent
`decode.math-dense-part` from ever being tested, so a clean math-dense page would silently lose its
math lane. Per-lane lists remove the interference entirely, and they are also what keeps a `text`-lane
part from paying for `table.grid_score`: the `DemandPlan` is keyed `(rung, lane, phase)`, so a signal
read only by a `table`-lane rule is computed only for parts in the `table` lane.

| lane | admitted when | what it produces | release-1 producer |
|---|---|---|---|
| `text` | always | the part's Blocks in reading order | `parse.office.anydoc`, `parse.text.builtin`, `parse.pdf.pdfium`, `parse.page.olmocr` |
| `table` | `block.type = "table"` (office) **or** `geometry.ruled_regions >= 1` (PDF) | table Blocks with real row/column spans | the `text` driver, then a `REPAIR` crop OCR |
| `math` | `math.font_hit` **or** `math.part_frac > @thresholds.math_part_frac` | `formula` Blocks with a notation set | `ENRICH`, see [06](06-structure-extraction.md) |
| `fields` | `unit.schema_requested` **or** `corpus.is_form` | a JSON object plus one `FieldGrounding` per leaf | **no `open`-tier driver at release 1** (§4.4) |
| `caption` | a part with a `picture`/`figure` Block and no adjacent caption text | caption Blocks | `ENRICH` |

Two consequences stated plainly. A **borderless PDF table** has no `geometry.ruled_regions` and no
`block.type`, so the `table` lane does not engage on it at release 1 and its cells arrive as ordinary
text Blocks in reading order; the decision records `cause = "layout_unavailable"` and the loss is a
number in the scoreboard rather than a rumour. And the `caption` lane engages on office formats only,
for the same reason `REPAIR` does.

### Render profiles are per rung, not per document

A VLM sees pixels, not points, so a profile is a **pixel floor on the short edge plus a pixel-area
ceiling**, and the DPI is derived per page. lift is the only repo in the collection that gets this
right — `MIN_PDF_IMAGE_DIM = 692`, `IMAGE_DPI = 96` (`lift/lift/settings.py:11-12`) and
`scale_dpi = max((692 / min_page_dim) * 72, 96)` (`lift/lift/input.py:27-50`) — so an A5 scan is
scaled *up* to the floor. marker and docling are DPI-only, so the same A5 scan silently gets a tiny
image. The two profiles are `[render.structure]` (692 px floor) and `[render.glyph]` (1384 px floor);
`then.render` selects one, and where two matching rules ask for different profiles the **more
expensive one wins** (`glyph` > `structure`), so accumulation is deterministic.

The arithmetic, so a reviewer can check a render: US Letter is 612 × 792 pt, so the structure profile
gives `max((692/612)·72, 96) = max(81.4, 96) = 96` DPI → 816 × 1056 px (short edge 816 ≥ 692), and the
glyph profile gives `max((1384/612)·72, 96) = 162.8` DPI → 1384 × 1791 px. A5 is 420 × 595 pt, so
structure gives `(692/420)·72 = 118.6` DPI → exactly 692 px on the short edge, scaled **up**.

`binarize = false`, always: Ollama-OCR renders at a bare 72 DPI and then Otsu-binarises, which
destroys the antialiasing every VLM in the collection was trained on. `patch_snap = 28` matches the
vision patch grid so the encoder does not pad. `area_max_px = 6_291_456` is applied by scaling down
*after* the short-edge floor is met — a US Letter glyph render is 2.48 Mpx and an A3 glyph render
2.71 Mpx, both under it — and when the two conflict the ceiling wins and `render.short_edge_px`
records what was actually delivered, which is the number a rule and the cost estimator may read.

---

# Part 4 — The routing policy engine

## 4.1 The policy is data

A `RoutePolicy` is the merged, compiled, frozen, content-addressed form of six TOML layers. Its
`policy_digest` enters every `route_decision`. There is no routing code branching on a format name
anywhere in the framework; `ow route lint` and a semgrep rule banning a format literal under
`omniweave/route/` are the enforcers.

**Six layers, higher PREPENDS.** First match wins, so prepending makes the higher layer win with no
precedence arithmetic at all.

| layer | location | owner | may set |
|---|---|---|---|
| `builtin` | in-package, immutable | omniweave | everything |
| `site` | `/etc/omniweave/policy.d/*.toml`, `%PROGRAMDATA%\omniweave\policy.d\*.toml` | the platform team | everything, including `Grant`s |
| `project` | `.omniweave/policy.d/*.toml` | the repo | rules, thresholds, budgets at or below site *(Build note, D935: until now `ow add` and `ow ingest` compiled the builtin layer alone, so no project rule routed anything. `route.policy.project_layers()` loads `.omniweave/policy.d/*.toml` in basename order and skips a `retrieval` or `graph` file. `run.routing.route_layers()` prepends them, ahead of the `[ingest] max_parts` scalar, and `policy_digest` covers them. The same run had two more gaps. The catalog was built without the project root, so a card under `.omniweave/drivers/` was "not installed". And a parse worker's HELLO named no `card_source`, so such a card was routed to and never started. Both are closed, with `config.project_root()` shared by `ow doctor`, `ow out` and ingest. The card's code must be installed: a worker has no `PYTHONPATH`, and DR9 grants an unattested driver no in-process run.)* |
| `profile` | a named overlay, `--profile fast\|balanced\|thorough\|offline` | the repo | threshold and rule overlays |
| `request` | `route_hints` on the API / MCP / CLI | the agent | a `RouteHints`, nothing else |
| `pin` | a `[[pin]]` block in `policy.d` | ops | one `(unit, part?, lane) -> driver` plus `reason` and `expires` |

**Six layers, and there is deliberately no seventh.** A `driver` layer was considered and refused:
below `builtin` it cannot pre-empt a builtin `DECODE` rule and therefore does not solve the case
that motivates it, above `builtin` it would let an installed wheel redirect spend, and `[[pin]]`'s
typed `PinRejected` already gives a driver author a per-unit demonstration path. A third party's
route lands through publish step 8's `project`-layer fragment
([drivers](04-driver-system.md) §9) and through an operator's copy of it.

Within a layer, files load in lexicographic order of basename and rules concatenate in file order.
Every file declares `surface = "route"`; a file without it, or with an unknown surface, fails to load
— which is what lets the routing, retrieval and graph policies share one directory without any of them
silently governing the others.

Merge is **concatenation of `[[rule]]` blocks and last-write-wins on scalars** (`[thresholds]`,
`[budget.*]`, `[audit]`, `[slice]`, `[render.*]`). A `project` layer may only *lower* a budget: a
`micros_max` above the site layer's is `OW-P-020` at load, not a silent clamp. `[[pin]]` blocks are
honoured or refused, never ignored — `PinRejected{driver, reason}` is a typed return, and the reasons
are exactly `driver_not_enabled`, `licence_tier`, `probe_unavailable`, `expired`, `rung_below_parent`.

## 4.2 The rule grammar — closed, total, comparison-only

```
rule    := { id, rung, lane?, when, then, comment?, on_unknown?, expect_unavailable?,
             expires?, canary? }
when    := clause | {any_of:[clause,…]} | {all_of:[clause,…]} | {none_of:[clause,…]}   # 1 level
clause  := { <evidence_key>: test, … }                       # implicit AND across keys
test    := scalar                                            # equality shorthand
         | { eq|ne|lt|lte|gt|gte : number | string | "@thresholds.<name>" }
         | { in|not_in : [scalar, …] }
         | { exists : bool }                                 # TOTAL: never yields UNKNOWN
then    := { driver?, driver_by?, lane?, deny_lanes?, escalate_to?, skip_rungs?, sequence?,
             outcome?, failure_class?, terminal?, cause_from?, reason?, render?,
             max_cost_class?, flag_blocks? }
outcome := "ok" | "ok_partial" | "refuse" | "skip" | "not_eligible"
on_unknown := "skip" | "match" | "defer"        # REQUIRED iff the rule reads a nullable key
expect_unavailable := bool                      # default false. Declares that `then.driver` is
                                                #   deliberately absent from [drivers] enabled.
```

No arithmetic, no indexing, no user functions, no dotted import paths, no `eval`. A rule that needs a
derived quantity gets a `Signal`, not a grammar feature — and this is checked to be sufficient: none
of the eight escalation ladders catalogued in `mine-parse.md` §B2 needs arithmetic over more than one
evidence key. `@thresholds.<name>` is a **compile-time substitution** from `[thresholds]`, not an
expression, which is precisely what makes a threshold learnable by one-dimensional isotonic regression
over the decision log. A hand-rolled predicate language with arithmetic forfeits both interval-box
subsumption linting and that fit, for 1,500 LoC and a strictly smaller checkable surface.

`{exists: bool}` is **total** — it tests the presence of a value, so it is defined on UNKNOWN and a
rule whose `when` consists only of `exists` tests needs no `on_unknown`. That is what lets
`degrade.budget-exhausted` read `budget.exhausted` without one.

**`expect_unavailable = true` declares an absence instead of hiding one.** A `[[rule]]` may name a
`then.driver` that `[drivers] enabled` does not list only by declaring it. The declaration has three
mechanical effects and no others. (a) `ow doctor`'s exit-1 "named-but-unenabled driver" condition
([10](10-interfaces.md) §7.5) downgrades to a **warning naming the rule id**, so a fresh install
exits 0 with the absence stated rather than failing on a driver the operator was never asked to
consent to (INV-5). (b) `ow route lint` check 6 reports the rule as a warning rather than an error.
(c) `ow route lint` check 14 makes the declaration self-retiring: `expect_unavailable = true` on a
rule whose driver **is** enabled is an error, so the day an open-tier driver ships, the line that
excused its absence fails the build instead of rotting into a permanent excuse. It is a rule-level
key rather than a `then` key because it describes the rule's release-1 reachability, not the action
the rule takes. One rule in the shipped policy carries it — `fields.extract` (§4.4) — and its
comment is what the key now makes machine-readable. `expect_unavailable` is coined by
[ADR-3](adr/0003-shipped-configuration.md) decision 2 and takes its terminology-lock row through
[ADR-1](adr/0001-terminology-lock-bulk-pass.md)'s bulk pass.

**`rule.lane` and `then.lane` are different keys doing different jobs**, and conflating them is the
mistake a reader will make. `rule.lane` (default `"text"`) says **which lane's rule list this rule
belongs to**; `then.lane` **admits** a lane for this part, adding it to the set of lanes whose loops
will run.

### Actions and modifiers, and why first-match-wins alone is not enough

The charter's own `GATE` block contains four rules that must *all* take effect on one part — two cost
clamps, a lane admission for forms and a lane admission for a supplied schema — which a single
first-match-wins list cannot deliver. So `then` keys split into two kinds:

| kind | keys | how they combine at one `(rung, lane, phase)` |
|---|---|---|
| **action** | `driver`, `driver_by`, `escalate_to`, `sequence`, `terminal`, `outcome ∈ {ok, ok_partial, refuse, skip}`, `failure_class`, `cause_from` | **first match wins.** Exactly one action per `(rung, lane, phase)`; later matching action rules are not tested. |
| **modifier** | `max_cost_class`, `lane`, `deny_lanes`, `render`, `skip_rungs`, `flag_blocks`, `outcome = "not_eligible"` | **every matching rule contributes**, by a per-key monoid: `max_cost_class` takes the minimum, `render` the more expensive profile, `lane`/`deny_lanes`/`skip_rungs` a set union, `flag_blocks` a logical OR, `not_eligible` a set union of excluded block ids. `deny_lanes` is applied after every `lane`, so a denial always wins. |

`reason` is legal on both. A rule whose `then` contains neither an action nor a modifier is a load
error (`OW-P-013`) — that is what a rule consisting only of `reason` was, and it is how the draft
`gate.untrusted-raises-audit` rule silently pre-empted every later `GATE` rule while doing nothing:
the untrusted-external audit rate is applied by the audit sampler directly from `unit.trust_class`
(§8.1) and needs no rule at all.

The modifier set is a pure function of `(policy_digest, evidence)`, both already in the decision's
identity, so it needs no column: `ow route explain` recomputes it exactly from the stored read set.

**`then` key semantics, stated once.**

| key | meaning |
|---|---|
| `driver` | the `driver_id` to run at this rung. Passed to `resolve()` as a requirement; a rejection is a typed `resolution_report` row, never a fallback. |
| `driver_by` | `"cheapest_admissible"` — opt-in estimator-driven selection among admissible candidates. **Not the default**: olmocr's own published `<$200/1M pages` (`olmocr/README.md`) against a naive `gpu_ms` estimate is 3.4× apart (charter §7 F6), and selection on an unreconciled estimator is a cost bug with a proof. |
| `lane` | **admit** a lane. `gate.form-admits-fields` is the `corpus.is_form` case. A lane admitted at rung `R` begins its own rung loop at `R + 1`, because the rungs below it have already run for this part. |
| `deny_lanes` | remove lanes from the admitted set, unconditionally. §2.3's weak-format-basis rule is the only shipped user. |
| `escalate_to` | the child `Rung`. The compiler **rejects a backward value at load**, so RT8's trigger is a second enforcer rather than the only one. |
| `skip_rungs` | rungs whose evaluation is skipped for this `(part, lane)`. Always strictly greater than the current rung; a member at or below it is a load error. |
| `sequence` | `{max_parts = N}` — bind the following parts into one driver session, amortising `[cost.model] per_session`. One decision per part, all sharing a `sequence_id`. |
| `outcome` | `ok` and `ok_partial` settle the `(part, lane)`. `refuse` fails it permanently with `failure_class`. `skip` puts the unit out of scope, and a `skip` rule **must** record `{reason, key, threshold}`. `not_eligible` is a modifier: it excludes *blocks* from the rung without touching the part. |
| `terminal` | **stops rule evaluation for this `(part, lane)`.** It settles at the rung reached; no later rung is entered and no later rule at this rung is tested. |
| `cause_from = "when"` | populate `route_decision.cause` with the clause that fired, rendered as `garble.score=0.71>=0.50`. |
| `render` | `"structure"` or `"glyph"` — which profile the driver receives. |
| `max_cost_class` | a **clamp**, established at `GATE` and carried down every rung. It can only lower. |
| `flag_blocks` | write the matching block ids to `route_decision.flagged_blocks` for the `REPAIR` and `ENRICH` rungs. |

`terminal` stops evaluation rather than merely forbidding escalation, and the difference matters:
under the weaker reading, `decode.office-native` (terminal) is followed at the same rung and lane by
`decode.part-text-unusable` (`on_unknown = "match"`, because every `pdfium` key is UNKNOWN on a DOCX),
which would try to escalate a part that may not escalate. Stopping evaluation makes the contradiction
unreachable instead of refusing the policy that contains it, and nothing is lost: `GATE` clamps are
always already applied, because the rung loop is monotone and `GATE` precedes `DECODE`.

**`terminal` does not make the named driver unreplaceable**, and that distinction is what keeps
`decode.text-native` (§4.4) from locking a third party out of the ten text tokens.
`terminal = true` ends rule evaluation at that rung; it does not make the named driver
unreplaceable. For a format **inside** the 48, a third-party driver becomes reachable when the
operator prepends a rule that pre-empts the builtin one — layers **prepend** and first match wins
(§4.1), so a `project`-layer rule naming the same `unit.format` set wins with no precedence
arithmetic. `ow drivers scaffold` emits that fragment as publish **step 8**, and
`ow drivers add --enable` prints the exact path it must be copied to ([drivers](04-driver-system.md)
§9); INV-5 keeps the operator in the loop, because enabling a driver and redirecting a route are two
decisions and the second is the one that can move money. For a format **outside** the 48 the same
prepend applies, one step later: the card's `format_tokens` pair admits the token to the computed
domain (§5.1) and only then can a rule spell it — [04](04-driver-system.md) §9 step 8b walks that
case end to end.

**Settling.** A `(part, lane)` settles when `terminal` fires, when an `outcome` other than
`not_eligible` fires with no `escalate_to`, or when the rung loop reaches `ENRICH` with nothing left to
match — in the last case at the highest rung that produced a decision, with that decision's outcome,
defaulting to `ok`. A part with no matching action rule at any rung is impossible by construction:
`decode.no-rule-matched` is the catch-all, and lint check 10 proves it unreachable.

## 4.3 Evaluation order, the demand plan, and what `on_unknown` actually does

```
compile(layers) --> RoutePolicy{rules, thresholds, budgets, audit, slice, render, policy_digest}
                      |  reachability prune -> subsumption lint -> threshold substitution
                      |  DemandPlan per (rung, lane, phase), grouped by CostClass ascending
                      |  driver.unavailable resolved ONCE over the reachable driver set
                      v
lanes = {"text"}                                            # text is mandatory
for rung in GATE, DECODE, REPAIR, PAGE, REGEN, DEGRADE, ENRICH:   # monotone, never revisited
    for lane in sorted(lanes):                              # a total order: deterministic
        if rung in skipped[lane] or settled[lane]: continue
        if rung <= admitted_at[lane]: continue              # a lane starts at admitted_at + 1
        for phase in (select, settle):
            plan = policy.demand[(rung, lane, phase)]
            for group in plan.groups:                       # FREE, then LOCAL_COMPUTE, then BILLED
                compute(group) into Evidence                # route_signal cache first, per (key,ver)
                d, mods = evaluate(policy, ev, hints, rung, lane, phase)   # PURE
                if d.matched and not plan.deferrals_pending(ev): break
            apply mods                                      # clamps, lane admissions, block flags
            lanes |= mods.admit_lanes ; lanes -= mods.deny_lanes
            if not d.matched: continue
            write route_decision                            # BEFORE anything runs
            a = admit(d, ledger)                            # IMPURE. Reserves. May write exhausted.
            if a is Deferred: leave the work row claimable; continue the drain
            run the driver; record route_spend; run the acceptors
```

**The demand plan.** For each `(rung, lane, phase)` the compiler takes the union of the read sets of
every reachable rule and partitions it by `CostClass`, ascending. Groups are computed in order and the
rules re-evaluated after each; **a rule matches only on resolved values.** Two mechanisms then decide
whether to stop early:

- If an action rule matches on the FREE group alone, evaluation stops there — unless a rule *earlier
  in file order* at this `(rung, lane, phase)` is currently UNKNOWN and declares
  `on_unknown = "defer"`, in which case the group holding its missing keys is promoted (still
  ascending, still under the `GATE` clamp) and evaluation restarts. That is `plan.deferrals_pending`.
  It is the whole reason a scanned page pays 15 ms for `ink.tiles` before spending 2.4 s of GPU, and
  the whole reason a clean page does not: `decode.pdf-text-layer` precedes
  `decode.blank-part-escape` in file order, so on a clean page there is no earlier deferring rule and
  the LOCAL group is never touched.
- Once every group in the plan has been computed, a key that is *still* UNKNOWN is genuinely
  unavailable — no provider serves this format, or the provider raised or timed out — and the rule's
  `on_unknown` decides.

| value | meaning | when to use it |
|---|---|---|
| `skip` | the rule does not match; evaluation continues to the next rule at this `(rung, lane, phase)`. | the rule is an optimisation or a cheaper-path shortcut, and not firing is safe. |
| `match` | the rule matches and its `then` applies. | the `then` is conservative — escalate to a cheap reading, or `not_eligible`. `ow route lint` check 9 **rejects** `match` on a rule whose `then.driver` declares `class = "billed_api"`, which is what makes "an unavailable signal can never spend money" mechanical. |
| `defer` | compute this rule's keys before letting a later rule win (above). If the key is still unavailable afterwards, `defer` degrades to `skip` and records `Degradation(kind="signal_unavailable")` naming the key and its provider. | the key is computable but expensive, and deciding without it would either overspend or silently pass a page. |

Because a plan holds finitely many groups and each is computed at most once, evaluation terminates
with no deferral counter. `defer` is the *evidence* mechanism; `Deferred(dim)` from `admit()` is the
*budget* mechanism. Two names for two things, and `evaluate()` only ever produces the first.

**The two phases are derived, not declared.** `SignalSpec.requires` names the rungs whose **driver
output** a signal reads — not the rungs at which something similar could be computed. `decode.char_count`
is `requires = ()` because pdfium answers `FPDFText_CountChars` from the source bytes; `garble.score`
and `ink.coverage` are `requires = (DECODE,)` because they read the decoded text and the emitted line
boxes. A rule belongs to the **settle** phase of rung `R` iff any key in its read set has `R` in
`requires`, and to `R`'s **select** phase otherwise. So `decode.part-text-unusable` settles *after*
`parse.pdf.pdfium` has run and does not shadow `decode.pdf-text-layer` in the select phase, even
though both declare `rung = "DECODE"`. There is no new grammar key: `ow route lint --explain` prints
each rule's derived phase, and check 7 rejects a rule that reads a key requiring a rung strictly
greater than its own — the only way this can go wrong.

Seven properties this order buys, each falsifiable:

1. **A clean born-digital page computes zero `LOCAL_COMPUTE` signals** (INV-13, RT4). At `DECODE`'s
   select phase in the `text` lane the FREE group yields `unit.format = "pdf"` and
   `decode.char_count > 0`; `decode.pdf-text-layer` matches with no earlier deferring rule; the
   `LOCAL_COMPUTE` group holding `ink.tiles` is never reached. The `service_attaches`,
   `page_renders` and `signal_computations` counters are **exact** — a deviation of one fails the gate.
2. **A lane's signals are not charged to another lane.** The plan key includes `lane`, so
   `table.grid_score` is computed only for parts in the `table` lane and `verify.grounded_field_frac`
   only for parts in the `fields` lane. Without the lane in the key every `text`-lane part in the
   corpus pays up to 30 ms for a table judge it will never read.
3. **`driver.unavailable` is resolved once, before evaluation, and `evaluate()` stays pure.** The
   compiler takes the union of every reachable rule's `then.driver`, calls `resolve()` on each — which
   is pure — and writes one boolean per driver into `Evidence`. The result is memoised on
   `(policy_digest, caps_digest)`. Without this, `degrade.driver-unavailable` would need a live
   resolution inside `evaluate()` and RT1 would be unenforceable.
4. **Sampling is rejected.** `{head, stride, cap}` produces a *wrong prior* on exactly the document
   that motivates per-page routing: a 40-page scanned appendix at pages 2,900-2,940 of a 4,000-page
   report is missed by a stride of 32. Demand planning is exact and costs less, because on a clean
   page it computes nothing at all.
5. **Reachability pruning is a lint, not an optimisation.** A rule whose condition box is subsumed by
   an earlier action rule at the same `(rung, lane, phase)` can never fire; it is a silently disabled
   guard, which is worse than a missing rule. `ow route lint` reports `OW-P-011` and the compiler
   drops it from the demand plan with a recorded `Degradation(kind="policy_pruned")`. Subsumption is
   computed over interval boxes, which is decidable precisely because the grammar is
   comparison-only. Modifier rules are exempt: they are *meant* to overlap.
6. **The decision row is written before the driver runs, and the write is idempotent under
   concurrency.** `route_decision` is append-only and immutable, and the insert is
   `INSERT … ON CONFLICT(content_sha256, unit_part, lane, rung, policy_digest, pricebook_digest,
   hints_digest, read_set_digest) DO NOTHING RETURNING decision_id`, followed by a re-select on
   conflict. Two `ow ingest` processes that compute the same decision converge on one row, because a
   decision is a pure function of its identity. `route_spend` is what accumulates per attempt. A crash
   mid-parse leaves a complete record of what was decided and why, and `ow why` answers from the store
   with no live process. A `GATE` refusal writes a row with `driver = ''` — the empty string, meaning
   "no driver ran", the same convention `Spend.provider` uses for local.
7. **Budget is not in `evaluate()`.** `evaluate()` takes `(policy, evidence, hints, rung, lane, phase)`
   and nothing else — no ledger, no `RunContext`, no clock. Exhaustion re-enters as the evidence key
   `budget.exhausted`, written by `admit()` and read by the `DEGRADE` rules. That is INV-14, and it is
   why a budget change can never alter *which* rung a document would have taken, only whether it ran.

### Long units: 10,000 parts, five lanes, and a budget that spans runs

A unit at the `max_parts` ceiling produces one `route_decision` per `(part, lane, rung)` that decided.
The measured shape on the §10.1 corpus is 1.07 lanes and 1.4 deciding rungs per part, so a 10,000-part
unit is ~15,000 decision rows at ~240 B = **3.6 MB**, plus one `route_signal` row per *computed*
signal: a clean part computes 5, so 50,000 rows at ~90 B = **4.5 MB**. Both are affordable; neither is
the 48-rows-per-part figure a reader might infer from §5.1, because the demand plan computes only what
a reachable rule reads.

Three rules keep that correct as well as affordable. Part rows and their decisions are written **512
per transaction**, the same batch size as roster enumeration, so no transaction holds a 10,000-row
write and the water mark can stop expansion between batches. The per-unit budget's scope key is
`unit_uri`, and headroom is computed in SQL against the durable `budget_reservation` rows, so a unit
routed across three `ow ingest` invocations sees one cumulative cap rather than three fresh ones. And
`unit.part_count`'s provider cost is `linear_per_byte` for container formats — `FPDF_GetPageCount` is
O(1), but counting messages in an mbox is a full scan — so `op.identify` records its `Spend` on
`route_signal` under `unit.part_count` and is charged to acquisition, not to a part.

### `slice_key`, exactly

`slice_key` is the `/`-joined rendering of `[slice] by` in declaration order, with `~` for an
unavailable component: `pdf/workiva/true/en`, `docx/~/true/de`. `~` is chosen because it sorts after
every alphanumeric and cannot collide with a format token or an ISO-639-1 code. Beyond
`max_slices = 512` distinct keys in one generation the 513th and later fold into the literal
`~overflow`, and `ow route scoreboard` prints the fold count — a scoreboard that silently grows a row
per producer string is a view nobody reads.

## 4.4 The shipped policy, complete

Forty rules. `rung = "GATE"` and the other `Rung` literals are written `SCREAMING_SNAKE` because
`.omniweave/policy.d/*.toml` is an **author-facing config artefact and not a wire** — the author
reads the spelling against §4.2's ladder. The compiler accepts exactly that spelling and rejects a
lower-case `Rung` at load (`OW-P-023`, on the path that already rejects a backward `escalate_to`),
so there is one authored form rather than two, and every *generated* artefact — `schema/*.json`,
`ow route explain --render json`, `ow surface emit` — emits the lower-case member name the
terminology lock requires. The lock's §1 `enum member` row gains the scope that says so; the
substance is [ADR-4](adr/0004-shipped-routing-policy.md) decision 3 and the row itself is
[ADR-1](adr/0001-terminology-lock-bulk-pass.md)'s to write (Open question 1, closed).

**The shipped `[drivers] enabled` is thirteen ids, and this policy is linted against exactly those**
([ADR-3](adr/0003-shipped-configuration.md) decision 1). Ten of them were the shipped list before
that decision; three are additions, each because a driver the shipped configuration already commits
to had no activation row. The card facts — distribution, licence tier, isolation, cost class — are
[04](04-driver-system.md) §10.1's roster and are not restated here; this table is the activation set
`ow route lint` check 6, `ow doctor` and `resolve()` read.

| # | driver id | port | why it is enabled |
|---|---|---|---|
| 1 | `parse.office.anydoc` | `parse/1` | the office family; `decode.office-native` names it by id with `terminal = true` |
| 2 | `parse.pdf.pdfium` | `parse/1` | the PDF glyph branch, and the only driver that can answer `decode.char_count` from the source bytes |
| 3 | `parse.page.olmocr` | `parse/1` | named so the shipped escalation rule **can** fire; where `omniweave-vision` is absent `resolve()` returns a named `PROBE_UNAVAILABLE` rejection, never a silent no-op |
| 4 | **`parse.text.builtin`** | `parse/1` | **added.** The ten text-family tokens `decode.text-native` names — HTML, Markdown, XML, JSON, JSONL, notebook, TSV, SVG and the two plain-text tokens — had no producer without it (Open question 2). Stdlib-only, in `omniweave-office` |
| 5 | **`compile.pptx.native`** | `compile/1` | **added.** `[targets] enabled = ["pptx"]` implies it through §D8's target matrix, and a Target is implemented by exactly two Drivers |
| 6 | **`parse.pptx.native`** | `parse/1` | **added.** The `pptx` target's `read_back` half, the second of those two |
| 7 | `derive.segment.spine` | `derive/1` | the segmentation pass |
| 8 | `derive.anchor.native` | `derive/1` | `[graph.passes] enable` names it |
| 9 | `derive.anchor.defterm` | `derive/1` | `[graph.passes] enable` names it |
| 10 | `derive.xref.native` | `derive/1` | `[graph.passes] enable` names it |
| 11 | `derive.xref.pattern` | `derive/1` | `[graph.passes] enable` names it |
| 12 | `derive.entity.table` | `derive/1` | `[graph.passes] enable` names it |
| 13 | `derive.entity.gazetteer` | `derive/1` | `[graph.passes] enable` names it |

`parse.deck.native` is **not** in the list — `deck` is absent from `[targets] enabled`, so nothing
implies it — and `parse.fields.lift` is deliberately absent, which is what §4.2's
`expect_unavailable` declares rather than hides. The charter's own `[drivers] enabled` at `:505-512` still prints
the ten-id form; it is superseded by the thirteen under charter erratum **`E36`**, whose sole home is
[04](04-driver-system.md) §10.1's roster and which a later stage writes into §9.2. This table is that
roster's **activation set** and restates the ids only — the card facts stay in §10.1. Until the
erratum lands the charter and these two documents disagree, and they are what `ow doctor`,
`ow route lint` checks 6 and 14, and `resolve()` are specified against.

**The fence's first comment line is a rule with an enforcer.** `G27(a2)` asserts that, after
`tomllib.loads` succeeds, no physical line of a ` ```toml ` fence in the charter or a plan document
ends at brace depth >= 1 ([11](11-repo-layout.md) §1.8). The clause is **lexical rather than a parse
check** because the construct it catches is legal TOML — a newline inside an inline table falls
inside an array literal and `tomllib` accepts it — so no semantic checker operating on a loaded
`dict` can see it. Forty rules are written below without one multi-line inline table; where a value
needs the room the house form is a sub-table.

```toml
# omniweave/route/policies/00-builtin-route.toml   (layer: builtin)
# ONE KEY PER LINE. `;` is not a TOML separator, an inline table may not span a newline,
# and this file gates money.
surface        = "route"
policy_name    = "builtin:balanced"
policy_version = 1
schema         = "omniweave.policy/1"

[slice]
by = ["unit.format", "unit.producer_family", "decode.has_text_span", "corpus.lang"]
max_slices = 512

[budget.per_part]                    # the runaway-part guard. FIRST EXHAUSTED DIMENSION WINS.
micros     = 6_000                   # $0.006 — two p95-reserved olmocr attempts plus change
tokens_out = 24_000                  # 3 x olmocr MAX_TOKENS=8000 (olmocr/pipeline.py:107)
calls      = 3                       # THE DIMENSION THAT BINDS FIRST on this pricebook (6.3)
gpu_ms     = 12_000

[budget.per_unit]                    # base + per_part x part_count, clamped. NO EXPRESSIONS.
micros_base     = 4_000
micros_per_part = 3_000              # >= parse.page.olmocr's reserved_micros 2,732 (10, lint check 13)
micros_max      = 16_000_000         # 4,000 + 3,000 x 5,000 = 15,004,000: the largest priced document
wall_ms         = 600_000
bytes_egress    = 0                  # 0 = NO hosted escalation without a site-layer Grant
on_exhausted    = ["spill_to_free", "partial", "defer"]

[audit]
rate = 0.005
salt = "2026-09-a"
reference = "parse.page.olmocr"
min_audit_n = 30
regress_at = 0.08
release_at = 0.048                   # hysteresis = regress_at x 0.6
auto_demote = true
demote_ttl_days = 30
untrusted_external_rate = 0.05       # applied by the SAMPLER from unit.trust_class, not by a rule

[calibration]
eval_set_id = ""
max_age_days = 30

[render.structure]
short_edge_min_px = 692              # lift settings.py:12 MIN_PDF_IMAGE_DIM
area_max_px = 6_291_456
patch_snap = 28
binarize = false

[render.glyph]
short_edge_min_px = 1384             # 2 x the structure floor: tokens scale with pixels
area_max_px = 6_291_456
patch_snap = 28
binarize = false

[thresholds]                         # the learnable numbers. `ow route propose` fits these per slice.
garble_escalate = 0.50
garble_recheck = 0.05
garble_min_chars = 50                # marker min_garbled_text_chars (line.py:110-114)
ink_coverage_min = 0.25              # marker layout_coverage_threshold (line.py:35-39)
overlap_max = 0.50                   # marker overlap_line_fraction_threshold (line.py:45-51)
blank_page_tiles = 4
promote_frac = 0.0                   # balanced: ANY flagged block promotes the part (fast: 0.5)
empty_block_area_min = 0.01          # marker min_ocr_block_area_fraction (line.py:97-101)
empty_block_containment = 0.75       # marker empty_block_contained_threshold (line.py:103-108)
grounded_field_min = 0.60
table_grid_min = 0.75                # marker balanced min_recon_score (table.py:37-43; fast 0.50)
math_char_frac = 0.02                # marker inline_math_min_unicode_frac (equation.py:63-65)
math_part_frac = 0.30                # marker inline_math_doc_ratio (equation.py:67-71)
cid_ratio_max = 0.10
replacement_ratio_max = 0.02         # marker table_recon.py:27 _GARBLE_CHAR_FRAC
run_length_sequence = 8
max_parts = 10_000                   # NOT learnable: [ingest] max_parts sets it (D644)
# ═════════════════ GATE — nothing has been decoded. Twelve rules. ═════════════════
[[rule]]
id   = "gate.empty"
rung = "GATE"
when = { "unit.format" = "empty" }
then = { outcome = "refuse", failure_class = "corrupt_input", reason = "zero-byte-file" }

[[rule]]
id      = "gate.encrypted"
rung    = "GATE"
comment = """unit.encrypted is NON-NULLABLE and detection-provided (5.3): the CFB/OPC
EncryptedPackage case and the PDF trailer /Encrypt case are both byte-scannable, so this rule
needs no on_unknown and cannot be silently off on a password-protected DOCX."""
when = { "unit.encrypted" = true }
then = { outcome = "refuse", failure_class = "encrypted", reason = "ow-add-password-file" }

[[rule]]
id      = "gate.corrupt"
rung    = "GATE"
comment = "unit.corrupt is the container-level structural check the format's spec mandates (5.3)."
when = { "unit.corrupt" = true }
then = { outcome = "refuse", failure_class = "corrupt_input" }

[[rule]]
id      = "gate.unsupported-source"
rung    = "GATE"
comment = "A database is a SOURCE, not a document; PostScript has no licence-clean interpreter."
when = { "unit.format" = { in = ["unknown", "sqlite", "ps"] } }
then = { outcome = "refuse", failure_class = "unsupported_format" }

[[rule]]
id      = "gate.unsupported-media"
rung    = "GATE"
comment = """No audio or video driver is in [drivers] enabled at release 1, so refusing at GATE is
both cheap and honest. The remedy the message names is `pip install omniweave-media`."""
when = { "unit.format" = { in = ["mp4", "matroska", "mp3", "wav", "flac", "ogg"] } }
then = { outcome = "refuse", failure_class = "unsupported_format", reason = "no-media-driver" }

[[rule]]
id      = "gate.too-large"
rung    = "GATE"
comment = "Belt and braces. The real guard is the pre-fetch check plus the bounded read in 1.1."
when = { "unit.bytes" = { gt = 2_147_483_648 } }
then = { outcome = "refuse", failure_class = "too_large", reason = "ingest.max_unit_bytes" }

[[rule]]
id      = "gate.too-many-parts"
rung    = "GATE"
comment = "unit.part_count is NOT NULL by the time the router runs: op.identify precedes routing."
when = { "unit.part_count" = { gt = "@thresholds.max_parts" } }
then = { outcome = "refuse", failure_class = "resource_limit", reason = "ingest.max_parts", cause_from = "when" }

[[rule]]
id      = "gate.watcher-may-not-bill"
rung    = "GATE"
comment = "graphify watch.py: FREE runs now, LOCAL_COMPUTE within headroom, BILLED_API never."
when = { "trigger.kind" = "watch" }
then = { max_cost_class = "local_compute" }

[[rule]]
id      = "gate.agent-triggered-may-not-bill"
rung    = "GATE"
comment = """An ow_add arriving over MCP or the SDK is not the cost consent a human gave by
typing. `ow add --allow-cost <micros>` is the approval path, and it is CLI-only because
RouteHints correctly has no budget field. (charter 5 C15)"""
when = { "trigger.kind" = { in = ["mcp", "sdk"] } }
then = { max_cost_class = "local_compute" }

[[rule]]
id         = "gate.form-admits-fields"
rung       = "GATE"
on_unknown = "skip"
comment = """olmocr's PdfFilter drops every form and every non-English document by default with a
logger.info only, behind --apply_filter (action="store_true", off). Ours runs always, its verdict
ADMITS A LANE, and any rule mapping a verdict to skip records {reason, key, threshold}."""
when = { "corpus.is_form" = true }
then = { lane = "fields", render = "structure" }

[[rule]]
id   = "gate.schema-admits-fields"
rung = "GATE"
when = { "unit.schema_requested" = true }
then = { lane = "fields", render = "structure" }

[[rule]]
id      = "gate.weak-format-basis-denies-extraction"
rung    = "GATE"
comment = """2.3 case 3, as a rule rather than as prose. A schema extraction or a table
reconstruction over a format guessed from a filename is a fabricated answer waiting to happen."""
when = { "unit.format_basis" = { in = ["extension", "declared"] } }
then = { deny_lanes = ["fields", "table"], reason = "weak-format-basis" }

# ═════════════════ DECODE, select, lane = text. Eight rules, and their ORDER IS LOAD-BEARING.
[[rule]]
id      = "decode.office-native"
rung    = "DECODE"
comment = """The format list is EXACTLY parse.office.anydoc's declared [capability] formats
(anydoc/README.md supported-formats table: Word .doc/.docx, PowerPoint .ppt/.pptx, Excel
.xls/.xlsx, OpenDocument, RTF, EPUB, CSV, PDF) minus pdf. Lint check 11 asserts the equality, so
this list cannot drift into naming a format the driver refuses. Native formats have a canonical
reading order; never re-infer it and never funnel them through a PDF renderer. marker subclasses
PdfProvider for DOCX/PPTX/XLSX/EPUB/HTML and renders to a temp A4 PDF, destroying speaker notes,
comments, tracked changes, OMML math, numbering restarts, footnote linkage and true logical order
BEFORE parsing starts. terminal = true STOPS EVALUATION."""
when = { "unit.format" = { in = ["doc", "docx", "ppt", "pptx", "xls", "xlsx", "odt", "ods", "odp", "rtf", "epub", "csv"] } }
then = { driver = "parse.office.anydoc", terminal = true }

[[rule]]
id      = "decode.text-native"
rung    = "DECODE"
comment = """anydoc does NOT convert HTML, Markdown, XML, JSON or notebooks, so routing them there
would name a format its card refuses. parse.text.builtin is the stdlib-only driver that serves
them, shipped in omniweave-office (04 section 10.1). tsv is here rather than with csv because a sniffed delimiter is the text
driver's job. terminal = true stops the fall-through to a paid rung; it does NOT lock a third party
out of these ten tokens, because a project-layer rule prepends and first match wins (4.2, and
publish step 8 in 04 section 9)."""
when = { "unit.format" = { in = ["html", "xhtml", "xml", "md", "txt", "json", "jsonl", "ipynb", "tsv", "svg"] } }
then = { driver = "parse.text.builtin", terminal = true }

[[rule]]
id      = "decode.container-expanded"
rung    = "DECODE"
comment = """A container's children were minted at acquire (2.5). The container itself gets no doc
row and no blocks, so there is nothing to decode and nothing for the empty_result rule to catch."""
when = { "unit.format" = { in = ["zip", "tar", "gz", "sevenz", "rar", "xz", "eml", "msg", "mbox"] } }
then = { outcome = "ok", terminal = true, reason = "container-expanded" }

[[rule]]
id         = "decode.pdf-text-layer"
rung       = "DECODE"
on_unknown = "defer"                 # decode.char_count is pdfium's; compute it, do not guess
comment    = """FIRST among the PDF rules, and that position is what makes INV-13 true: because no
EARLIER rule at this (rung, lane, phase) declares defer, a clean page decides from the FREE group
and the LOCAL_COMPUTE group holding ink.tiles is never computed."""
when = { "unit.format" = "pdf", "decode.char_count" = { gt = 0 } }
then = { driver = "parse.pdf.pdfium" }

[[rule]]
id         = "decode.blank-part-escape"
rung       = "DECODE"
on_unknown = "defer"
comment = """The licence-free replacement for marker's blank-page escape (line.py:343-345), which
reads the LAYOUT MODEL's block count; ours reads ink. 15 ms of CPU to avoid a 2,400 ms GPU call is
a 160x trade, which is why this rule precedes decode.no-text-layer and why its `defer` is what
promotes the LOCAL group on a part with no text layer."""
when = { "ink.tiles" = { lte = "@thresholds.blank_page_tiles" } }
then = { outcome = "ok", terminal = true, reason = "blank-part" }

[[rule]]
id         = "decode.no-text-layer"
rung       = "DECODE"
on_unknown = "defer"
comment = "A scanned page. There is nothing to decode, so this goes straight to PAGE."
when = { "unit.format" = "pdf", "decode.char_count" = 0 }
then = { escalate_to = "PAGE", driver = "parse.page.olmocr", render = "glyph", reason = "no-text-layer" }

[[rule]]
id   = "decode.raster-image"
rung = "DECODE"
when = { "unit.format" = { in = ["png", "jpeg", "webp", "tiff", "bmp", "gif"] } }
then = { escalate_to = "PAGE", driver = "parse.page.olmocr", render = "glyph", reason = "raster-source" }

[[rule]]
id      = "decode.no-rule-matched"
rung    = "DECODE"
comment = """UNREACHABLE BY CONSTRUCTION: lint check 10 asserts the union of unit.format literals
across GATE and DECODE equals the format-token domain exactly. It exists so that an out-of-tree
format added without a rule fails LOUDLY on its first document instead of settling with no
decision, which is the failure a coverage lint can only catch in CI."""
when = { "unit.bytes" = { gte = 0 } }
then = { outcome = "refuse", failure_class = "unsupported_format", reason = "no-decode-rule" }

# ═════════════════ DECODE, settle, lane = text. Three actions, three lane admissions.
[[rule]]
id      = "decode.part-text-unusable"
rung    = "DECODE"
comment = """marker/marker/builders/line.py:225-235 — four signals ANDed there, so ANY failing
here. Signal 2 (surya OCRErrorPredictor) and signal 3 (layout coverage) are BOTH Datalab-licensed
(MODEL_LICENSE md5 e1f69b64dee2f1641a9b1ab12adf24d6); garble.score and ink.coverage are the
licence-free replacements. THE THRESHOLDS ARE OURS, NOT MARKER'S — its numbers were calibrated
against its classifier's score distribution. on_unknown='match' is legal here only because
parse.page.olmocr declares cost.class='local_compute' (lint check 9), and it fires only after the
LOCAL group has actually been computed (4.3)."""
on_unknown = "match"
when.any_of = [
  { "decode.line_count"          = { eq  = 0 } },
  { "garble.score"               = { gte = "@thresholds.garble_escalate" } },
  { "ink.coverage"               = { lt  = "@thresholds.ink_coverage_min" } },
  { "geometry.overlap_line_frac" = { gt  = "@thresholds.overlap_max" } },
]
then = { escalate_to = "PAGE", driver = "parse.page.olmocr", render = "glyph", cause_from = "when" }

[[rule]]
id      = "decode.broken-font-encoding"
rung    = "DECODE"
comment = """A CID-keyed font with no ToUnicode CMap yields glyph ids, not characters. anydoc
receives a DOCUMENT-LEVEL boolean from pdf-inspector and only log::warn!s it
(src/formats/pdf.rs:26-29); the per-part fraction is work omniweave does."""
on_unknown = "match"
when.any_of = [
  { "decode.cid_ratio"         = { gt = "@thresholds.cid_ratio_max" } },
  { "decode.replacement_ratio" = { gt = "@thresholds.replacement_ratio_max" } },
]
then = { escalate_to = "PAGE", driver = "parse.page.olmocr", render = "glyph", cause_from = "when" }

[[rule]]
id         = "decode.skip-block-recheck-on-clean-parts"
rung       = "DECODE"
on_unknown = "skip"
comment    = "marker block_garbled_check_min_page_score = 0.05 (line.py:116-121), as a rung skip."
when = { "garble.score" = { lt = "@thresholds.garble_recheck" } }
then = { skip_rungs = ["REPAIR"] }

[[rule]]
id         = "decode.admit-table-lane"
rung       = "DECODE"
on_unknown = "skip"
comment    = """A MODIFIER: it admits a lane and takes no action, so it coexists with whichever
action rule above fired. block.type covers office formats exactly; geometry.ruled_regions covers
RULED PDF tables. A BORDERLESS PDF TABLE MATCHES NEITHER and its cells arrive as ordinary text
blocks — named here rather than implied, and recorded as cause='layout_unavailable'."""
when.any_of = [
  { "block.type"              = "table" },
  { "geometry.ruled_regions"  = { gte = 1 } },
]
then = { lane = "table", reason = "table-region-present" }

[[rule]]
id         = "decode.admit-math-lane"
rung       = "DECODE"
on_unknown = "skip"
comment    = """marker equation.py:63-71 — a math font name is a high-precision signal; otherwise
math_chars/len(text) > 0.02 per block, and above 30% flagged blocks the whole part is flagged,
because math-heavy pages scatter inline math into ordinary prose."""
when.any_of = [
  { "math.font_hit"  = true },
  { "math.part_frac" = { gt = "@thresholds.math_part_frac" } },
]
then = { lane = "math", reason = "math-dense" }

[[rule]]
id         = "decode.admit-caption-lane"
rung       = "DECODE"
on_unknown = "skip"
comment    = "block.type has no PDF provider at release 1, so this admits on office formats only."
when = { "block.type" = { in = ["picture", "figure", "diagram"] } }
then = { lane = "caption", reason = "uncaptioned-figure" }

# ═════════════════ lane = table ═════════════════
[[rule]]
id         = "table.grid-unresolved"
rung       = "REPAIR"
lane       = "table"
on_unknown = "skip"
comment    = """marker/processors/table.py:104-126 — reconstruct from the char-level page, then gate
on the composite judge score (0.75 balanced / 0.50 fast) and fall back to a crop OCR below it. The
score is a MEASURE, not a probability: kind='measure', so RT6's calibration gate does not apply and
must not be demanded."""
when = { "table.grid_score" = { lt = "@thresholds.table_grid_min" } }
then = { driver = "parse.page.olmocr", render = "glyph", flag_blocks = true, cause_from = "when" }

# ═════════════════ lane = math ═════════════════
[[rule]]
id      = "math.flag-for-enrich"
rung    = "REPAIR"
lane    = "math"
comment = """The math lane FLAGS; the ENRICH pass that renders notation is 06's derive.math.*.
Naming a driver here that [drivers] enabled does not list would make every math part degrade."""
when = { "unit.bytes" = { gte = 0 } }
then = { escalate_to = "ENRICH", flag_blocks = true, reason = "math-notation" }

# ═════════════════ lane = caption ═════════════════
[[rule]]
id      = "caption.flag-for-enrich"
rung    = "REPAIR"
lane    = "caption"
comment = "As the math lane: flag here, ENRICH in 06."
when = { "unit.bytes" = { gte = 0 } }
then = { escalate_to = "ENRICH", flag_blocks = true, reason = "figure-caption" }

# ═════════════════ lane = fields ═════════════════
[[rule]]
id      = "fields.extract"
rung    = "PAGE"
lane    = "fields"
expect_unavailable = true              # THE ONE RULE IN THIS FILE THAT CARRIES IT (4.2). Without
                                       #   it `ow doctor` exits 1 on a fresh install; with it the
                                       #   absence is a warning naming this rule, and lint check 14
                                       #   fails the day parse.fields.lift becomes enabled.
comment = """parse.fields.lift is NOT in [drivers] enabled and its OpenRAIL-M weights compute to
licence tier `restricted`, which [licence] allow_tiers = ["open"] refuses. At release 1 this rule
therefore ALWAYS resolves to driver.unavailable and the fields lane degrades with a named driver
and a named licence reason — which is the honest outcome, and the reason the lane's rules ship
anyway: the day an open-tier constrained-decoding driver exists, this is the only line that
changes. The text lane is unaffected and still produces the page."""
when = { "unit.bytes" = { gte = 0 } }
then = { driver = "parse.fields.lift", render = "glyph" }

[[rule]]
id         = "fields.ungrounded"
rung       = "PAGE"
lane       = "fields"
on_unknown = "skip"
comment    = """lift's own adversarial benchmark: 90.2% per field but 20.9% FULL-DOCUMENT
(lift/README.md, 225 documents / ~11k scored fields), with no verification layer in the open
weights. The cross-check is free because DECODE already ran."""
when = { "verify.grounded_field_frac" = { lt = "@thresholds.grounded_field_min" } }
then = { escalate_to = "REGEN", render = "glyph", cause_from = "when" }

# ═════════════════ REPAIR, lane = text ═════════════════
[[rule]]
id         = "repair.never-escalate-furniture"
rung       = "REPAIR"
on_unknown = "match"
comment    = """A MODIFIER (outcome='not_eligible' excludes BLOCKS), so it composes with
repair.empty-box-needs-ink instead of pre-empting it. marker/builders/line.py:125-135
block_ocr_skip_types: page headers/footers are dropped from output by default, so OCRing them
wastes a VLM call, and a single flagged footer forces an otherwise-clean document to spawn the
inference server. THE LITERALS ARE `Kind` WIRE VALUES — the lower-case member names; marker's own
`PageHeader` spelling is not a value in this vocabulary under any casing, which is how it silently
disabled its own guard. on_unknown='match' is load-bearing: block.type has NO PDF provider at
release 1, so on PDF this matches for every block and REPAIR is structurally unavailable rather
than silently unguarded."""
when = { "block.type" = { in = ["page_header", "page_footer", "picture", "figure", "diagram", "table", "form", "toc", "formula", "chemical"] } }
then = { outcome = "not_eligible", reason = "layout_unavailable" }

[[rule]]
id         = "repair.empty-box-needs-ink"
rung       = "REPAIR"
on_unknown = "skip"
comment    = """marker line.py:400-445 — only OCR an EMPTY layout box when it is at least 1% of the
page, is not at least 75% contained in a text-bearing sibling (line-numbered transcripts), and
actually has ink."""
when.all_of = [
  { "block.char_count" = 0 },
  { "block.area_frac"  = { gte = "@thresholds.empty_block_area_min" } },
  { "block.sibling_containment" = { lt = "@thresholds.empty_block_containment" } },
  { "block.has_ink"    = true },
]
then = { driver = "parse.page.olmocr", render = "glyph", flag_blocks = true, reason = "empty-inked-box" }

[[rule]]
id         = "repair.promote-to-part"
rung       = "REPAIR"
on_unknown = "skip"
comment    = "One full-part request is ~7x cheaper than N block requests on llama.cpp (ocr.py:76-84)."
when = { "block.flagged_frac" = { gt = "@thresholds.promote_frac" } }
then = { escalate_to = "PAGE", driver = "parse.page.olmocr", render = "glyph", reason = "promotion" }

# ═════════════════ PAGE / REGEN, lane = text ═════════════════
[[rule]]
id      = "page.collapse-to-sequence"
rung    = "PAGE"
comment = "If most parts escalated, per-part routing has lost: pay the per-session cost once."
when = { "doc.escalated_part_frac" = { gt = 0.80 }, "unit.part_count" = { lte = 64 } }
then = { driver = "parse.page.olmocr", sequence = { max_parts = 64 }, reason = "de-escalation" }

[[rule]]
id      = "page.stable-run-becomes-a-sequence"
rung    = "PAGE"
comment = """Long-horizon layout stability, used for AMORTISATION and never for skipping evidence.
Eight consecutive parts on the same (rung, driver) means the per-session model load should be paid
once, not eight times. Sampling remains rejected: this changes batching, not what is measured."""
when = { "doc.rung_run_length" = { gte = "@thresholds.run_length_sequence" } }
then = { driver = "parse.page.olmocr", sequence = { max_parts = 64 }, reason = "stable-run" }

[[rule]]
id         = "page.output-invalid"
rung       = "PAGE"
on_unknown = "match"
comment    = """Acceptor failures. repetition_penalty stays 1.0 — real documents repeat.
on_unknown='match' means a PAGE result we cannot verify is treated as invalid and regenerated,
which is the safe direction and costs at most one extra attempt."""
when.any_of = [
  { "verify.repeat_ngram_max" = { gte = 12 } },
  { "verify.finish_reason"    = { ne  = "stop" } },
  { "verify.token_saturation" = { gte = 0.98 } },
  { "verify.parse_ok"         = false },
  { "verify.nonempty"         = false },
]
then = { escalate_to = "REGEN", cause_from = "when" }

# ═════════════════ REGEN -> DEGRADE. These three apply in EVERY lane. ═════════════════
[[rule]]
id      = "degrade.budget-exhausted"
rung    = "REGEN"
comment = "budget.exhausted is written by admit(), so evaluate() never reads the ledger (INV-14)."
when = { "budget.exhausted" = { exists = true } }
then = { escalate_to = "DEGRADE", driver = "parse.pdf.pdfium", outcome = "ok_partial", reason = "budget-exhausted" }

[[rule]]
id         = "degrade.attempts-exhausted"
rung       = "REGEN"
on_unknown = "skip"
comment = "Unlimited-OCR/infer.py:229 writes an empty text field for a part that failed 5 retries."
when = { "verify.attempts_exhausted" = true }
then = { escalate_to = "DEGRADE", driver = "parse.pdf.pdfium", outcome = "ok_partial", reason = "regen-exhausted" }

[[rule]]
id      = "degrade.driver-unavailable"
rung    = "REGEN"
comment = """omniweave-vision absent, a probe UNAVAILABLE, or a licence tier outside
[licence] allow_tiers. resolve() returns a NAMED rejection, never a silent no-op, and the part
degrades to the text layer with the gap disclosed rather than returning a hole. This is also the
rule that catches fields.extract at release 1."""
when = { "driver.unavailable" = true }
then = { escalate_to = "DEGRADE", driver = "parse.pdf.pdfium", outcome = "ok_partial", reason = "driver-unavailable" }
```

A `--profile fast` overlay changes no rule:

```toml
# omniweave/route/policies/50-profile-fast.toml   (layer: profile, active under --profile fast)
surface        = "route"
policy_name    = "builtin:fast"
policy_version = 1
schema         = "omniweave.policy/1"

[thresholds]
promote_frac    = 0.5                # marker block_ocr_promote_fraction: repair, do not promote
garble_escalate = 0.65
table_grid_min  = 0.50               # marker fast-mode min_recon_score (table.py:37-43)

[budget.per_part]
micros     = 2_000
tokens_out = 8_000
calls      = 1
```

## 4.5 `ow route lint`

A policy that gates money must not be able to name something that does not exist. Fourteen mechanical
checks; the first three are the charter's and the rest fall out of this document's grammar.

| # | check | code |
|---|---|---|
| 1 | every key in `[slice] by`, in a `when` clause and in `[thresholds]` resolves against the `SignalSpec` registry | `OW-P-001` |
| 2 | every literal compared against a `str`-dtype signal is a member of that signal's `frozenset[str]` domain — for `unit.format`, against the computed domain (core's 48 ∪ the enabled cards' contributed `format_tokens` tokens, §5.1), never against the literal 48 | `OW-P-002` |
| 3 | `sum([retrieval.budget] channel_ms) + [retrieval.budget] hydration_reserve_ms <= query_ms` — the `retrieval` surface's check, specified in [07](07-store-and-retrieval.md) §4.4, which owns `hydration_reserve_ms` | `OW-P-003` |
| 4 | every rule reading a nullable key declares `on_unknown`; a rule whose `when` is `exists`-only does not need one | `OW-P-004` |
| 5 | every `escalate_to` is strictly greater than the rule's own `rung`, and every `skip_rungs` member is strictly greater | `OW-P-005` |
| 6 | every `driver` and every `[[pin]]` target names a `driver_id` present in `omniweave.toml [drivers] enabled` (§4.4's thirteen) — **a warning, not an error, for a rule declaring `expect_unavailable = true`** (§4.2), which is `fields.extract`'s deliberate state at release 1 and the only such rule shipped | `OW-P-006` |
| 7 | no rule reads a key whose `requires` contains a rung strictly greater than the rule's own `rung` | `OW-P-010` |
| 8 | no **action** rule is subsumed by an earlier action rule at the same `(rung, lane, phase)` — an unfirable guard. Modifier rules are exempt | `OW-P-011` |
| 9 | no rule declares `on_unknown = "match"` while its `then.driver` declares `[cost.model] class = "billed_api"` | `OW-P-012` |
| 10 | the union of `unit.format` literals across `GATE` and `DECODE` rules equals **the computed domain** — core's 48 ∪ the enabled cards' contributed `format_tokens` tokens (§5.1) — exactly. Both directions are the check: a domain member no rule at any layer names fails, and the linter names the driver that contributed it; a rule literal outside the domain fails as check 2 | `OW-P-014` |
| 11 | for every rule with both a `unit.format` clause and a `then.driver`, every named token is in that driver's **served token set** — `{format_token_for(m) for m in [capability] formats}` ∪ its `format_tokens` tokens, [04](04-driver-system.md) §2.2. Compared token-to-token: `[capability] formats` holds media types and a rule holds tokens, so the card's token-side projection is the only comparable of the right type | `OW-P-015` |
| 12 | every rule's `then` contains at least one action key or one modifier key | `OW-P-013` |
| 13 | for every enabled driver a `PAGE`- or `REGEN`-rung rule can select, `[budget.per_unit] micros_per_part >= card.reserved_micros` and `[budget.per_part] micros >= card.reserved_micros` — a per-unit cap that grows more slowly than the reservation denies parts the operator can afford, and it is the shipped default that had this defect | `OW-P-021` |
| 14 | no rule declares `expect_unavailable = true` while its `then.driver` **is** present in `omniweave.toml [drivers] enabled` (§4.4's thirteen, the same set check 6 reads) — the declaration is an exemption from check 6 and `ow doctor`'s exit-1 condition, so it must expire the day the driver ships rather than persist as an unexamined excuse | `OW-P-024` |

Check 10 is the one that would have caught the largest class of silent bug: `mp3`, `eml`, `zip`,
`doc` and six more tokens exist in the detection vocabulary, and a policy that never names them
routes them nowhere. Its target is the **computed** domain and not the literal 48, and the difference
is load-bearing: a check equal to core's 48 would fail a third party's `warc` card whichever way its
author turned — naming `warc` in a rule would push the literal union to 49 and fail, omitting the rule
would leave a domain member unnamed and fail — so the token would be unroutable by construction. The
walk is [04](04-driver-system.md) §9 step 8b.

**Eight of the fourteen also run over documentation.** `G27(a3)` runs checks 1, 2, 4, 5, 7, 9, 10
and 12 over every ` ```toml ` fence in the charter or a plan document that parses to a table
containing a `[[rule]]` array, against the shipped registry and the shipped `[drivers] enabled`
([11](11-repo-layout.md) §1.8). Checks 3, 6, 11, 13 and 14 are excluded because each reads something
a documentation fence has no standing to carry — `retrieval.toml`, an enabled driver's card, the
shipped `[drivers] enabled`, or a `[budget.*]` block. `a3` cannot run before `ow route lint` itself ships at P5, so from P1 the gate
harness carries a **standalone check 4** instead, reading nullability from §5.1's `null` column
parsed out of the markdown table rather than by importing `omniweave.route`; that column is
therefore load-bearing for a gate as well as for the linter. At the P5 exit the standalone check is
**deleted** and `a3` replaces it wholesale — two implementations of one check are never maintained
in parallel ([ADR-4](adr/0004-shipped-routing-policy.md) decision 2).

`ow route lint --calibration` additionally asserts every `kind = "classifier"` signal's ECE at or
below 0.05 and Brier at or below 0.08 on the held-out set named by `[calibration] eval_set_id`, and
fails the build on a regression (RT6). `ow route lint --explain <rule-id>` prints the rule's derived
phase, whether it is an action or a modifier, its read set with each key's `cost_class`, nullability
and resolved provider, and the demand-plan group it lands in.

## 4.6 The four types `evaluate()` touches, and what makes INV-14 checkable

INV-14 says routing is pure: `evaluate()` sees no ledger, no clock, no RNG, no environment, no IO
and no `RunContext`. A purity claim is only checkable if the types on both sides of the function are
printed, because purity is a property of a **signature** plus what the argument types can reach.
These four are that signature. Two are frozen values, one is a mutable record with a read log and no
public mapping, and the fourth is the request layer that cannot widen anything.

```python
# omniweave/route/eval.py — PURE. semgrep bans `time.`, `random.`, `os.environ`, `importlib` and
# `open(` in this module, and a property test evaluates 10,000 fixtures twice in shuffled order and
# asserts identity (RT1).

def evaluate(policy: "RoutePolicy", ev: "Evidence", hints: "RouteHints",
             rung: Rung, lane: str,
             phase: Literal["select", "settle"]) -> tuple["RouteDecision", "Modifiers"]: ...

# omniweave/route/estimate.py — PURE over (decision, catalog, book). It is the ONLY step that sees
# a PriceBook, which is why `pricebook_digest` is in the decision's identity and why `evaluate()`
# needs no price argument to stay replayable. It is also where `driver_by = "cheapest_admissible"`
# resolves, because selection on an estimate is an ESTIMATOR decision by definition (§4.2).
def price(d: "RouteDecision", catalog: "Catalog", book: "PriceBook") -> "RouteDecision": ...

# omniweave/route/admit.py — IMPURE, and the only impure half of routing. It runs strictly AFTER
# the `route_decision` row is written (§4.3 property 6), so a budget can never change which rung
# was chosen — only whether it ran (RT9).
def admit(d: "RouteDecision", ledger: "BudgetLedger") -> "Admitted | Deferred | Degraded": ...
```

**Why the signature has three more parameters than the charter's.** The charter prints
`evaluate(policy, ev, hints) -> RouteDecision`. This document's rung loop (§4.3) evaluates one
`(rung, lane, phase)` at a time and unpacks two values, because the action/modifier split (§4.2)
means one call yields at most one action and *every* matching modifier. The three-argument,
single-return form is superseded by the six-argument, two-value form printed here; nothing else
about the call changes, and `RouteDecision` is still what a `route_decision` row is written from.

### `Evidence` — a record with a read log, deliberately not a dataclass

```python
# omniweave/route/evidence.py
class Evidence:
    """The flat, namespaced, scalar-valued record of Signal values for ONE (unit, part).

    NOT a frozen dataclass, and not a Mapping. It is a handle over a read log that the demand plan
    fills group by group (§4.3), so freezing it would say something false about what it holds —
    the same reason `Doc` and `Grid` are not dataclasses ([12](12-performance.md) §4.2 rule 2).
    There is no `__getitem__`, no `keys()`, no `items()` and no `__contains__`: a third party must
    be able to add `garble.acme_blur` without a core release, and the policy must be able to name a
    key core has never heard of, so the accessor is by string and the registry does the checking."""

    __slots__ = ("_v", "_read", "_scope")

    # ---- the only accessor. Reading is what puts a key in the read set (RT3). ----
    def read(self, key: str) -> Scalar: ...
        # Returns None for UNKNOWN — uncomputable, no provider for this format, or the provider
        # raised or timed out. Three-valued: None is not a default and compares equal to nothing.
        # APPENDS to the read log, so the read set is an OBSERVATION and not a declaration a
        # programmer can forget to update.

    def computed(self, key: str) -> bool: ...
        # Whether a group holding `key` has already run — "computed and unavailable" against "not
        # computed yet". `DemandPlan.deferrals_pending(ev)` (§4.3) is the ONLY caller, and it must
        # not go through `read()`: a planner probe is not a read and may not enter the read set.

    def read_set(self) -> tuple[tuple[str, str, Scalar], ...]: ...
        # (key, provider_version, value) triples, IN READ ORDER, for the winning path and nothing
        # else. `provider_version` is the version of the provider §5.2's per-format resolution
        # actually chose, which is why an `officexml` bump does not invalidate a PDF decision.

    def read_set_digest(self) -> str: ...
        # sha256_canonical(read_set()), allow_nan=False. One of the eight identity columns (§7.1).

    # ---- the only writer, and it is never called from `route/eval.py` ----
    def put(self, key: str, value: Scalar, *, provider_version: str,
            unavailable_reason: str | None = None) -> None: ...
        # Three callers, all outside `evaluate()`: the signal computer, as each `CostClass` group
        # runs; the compiler's pre-evaluation resolution probe, which writes one
        # `driver.unavailable` boolean per reachable driver so `evaluate()` needs no live
        # `resolve()` (§4.3 property 3); and `admit()`, which writes `budget.exhausted` — the single
        # channel by which budget reaches routing (RT9, §6.4). `unavailable_reason` is stored so
        # "we tried and could not" is a cacheable fact in `route_signal` rather than a re-attempt
        # every run (§5.4).
```

**How `Evidence` makes purity checkable, precisely.** `evaluate()` cannot obtain a value except
through `read()`, `read()` returns a `Scalar`, and every `Scalar` in the record was put there by a
registered `SignalSpec` provider before the call. There is therefore no path from `evaluate()` to a
clock, a socket, a document's text or a ledger — not by convention, but because the type exposes no
other method. It is also what makes `ow route replay` free: a stored `route_evidence` payload
reconstitutes an `Evidence`, and re-running `evaluate()` over it needs no source bytes, no driver
and no network.

### `RouteDecision` — what one `(part, lane, rung)` decided, before anything ran

```python
# omniweave/route/decision.py
@dataclass(frozen=True, slots=True)
class RouteDecision:
    # ── identity: EXACTLY the eight columns of `route_decision_identity` (§7.1). Every one an
    #    INPUT; nothing about WHEN the decision was made appears here. ──
    content_sha256: str          # keyed on CONTENT, not `unit_uri`: the same PDF in three folders
                                 # is one decision and one parse.
    unit_part: str               # '' for a unit-grain decision. '' folds NULL, because NULLs are
                                 # distinct in a UNIQUE index.
    lane: str                    # a `LANES` member. In the key, so a part's `text` and `table`
                                 # decisions are separate rows that age out and re-price apart.
    rung: Rung
    policy_digest: str
    pricebook_digest: str        # filled by `price()`; a price change makes a NEW decision row
                                 # rather than silently rewriting history (§6.2).
    hints_digest: str            # over the `RouteHints` below, plus the CLI-only `--allow-cost`
                                 # and `--max-rung` values (§7.3).
    read_set_digest: str

    # ── what the winning rule said. `evaluate()` fills all of these. ──
    matched: bool                # False == no action rule matched at this (rung, lane, phase); the
                                 # loop in §4.3 continues and writes no row.
    rule_id: str
    rule_origin: str             # 'project:.omniweave/policy.d/10-route.toml:41'. `ow route
                                 # explain` and [15](15-observability.md) §6.2's escalation report
                                 # both print it, which is why it is a column and not a log line.
    driver: str                  # '' == no driver ran, the same convention `Spend.provider` uses
                                 # for local. A `GATE` refusal writes a row with driver = ''.
    driver_by: Literal["cheapest_admissible"] | None
    escalate_to: Rung | None     # strictly greater than `rung`; the compiler rejects a backward
                                 # value at load (`OW-P-005`), so RT8's trigger is the second
                                 # enforcer rather than the only one.
    terminal: bool               # stops rule evaluation for this (part, lane) at this rung (§4.2).
    outcome: Literal["ok", "ok_partial", "refuse", "skip"] | None
    failure_class: str | None    # set iff outcome == "refuse"; a member of the charter's
                                 # thirteen-member `FailureClass` enum (Part 9).
    sequence_max_parts: int | None      # from `then.sequence`; the planner mints the `sequence_id`.
    cause: str | None            # rendered from the clause that fired when the rule declares
                                 # `cause_from = "when"`: 'garble.score=0.71>=0.50'. A GENERATED
                                 # string, so "why it escalated" is a `GROUP BY` and not a log grep
                                 # ([15](15-observability.md) §6.2).
    reason: str | None           # the rule's own `reason`; mandatory on a `skip` rule (§4.2).
    slice_key: str               # the '/'-joined `[slice] by` rendering, '~' per unavailable
                                 # component (§4.3). A pure function of the policy and the evidence,
                                 # so it is decided here and never recomputed by the scoreboard.
    pinned: bool                 # a `[[pin]]` won. The row is excluded from `route_scoreboard`.
    flagged_blocks: tuple[int, ...] = ()           # from `then.flag_blocks`, for REPAIR and ENRICH.
    degradations: tuple["Degradation", ...] = ()   # a SET, not a flag: a part can be budget-
                                 # degraded AND signal-degraded, and both survive into the run
                                 # manifest and the serve envelope (§6.5). `Degradation` is
                                 # [15](15-observability.md)'s type; this document mints no second
                                 # one.

    # ── filled by `price()` (§6.3), between `evaluate()` and the row write. ──
    cost_class: CostClass = CostClass.FREE      # the driver's declared `[cost.model] class`, frozen
                                 # at decision time: it is the `cost_class` label on
                                 # `ow_spend_micros_total` and the `class` column of
                                 # `ow cost --by driver`, and reading it from the live catalog would
                                 # re-label history after a card upgrade.
    est_spend: Spend = Spend()   # per_part x (scaling.key_value / reference) ** exponent, plus the
                                 # per_session term unless the card declares a `service` (§6.3).
    est_micros: int = 0          # est_spend.micros(book). `Spend.micros` is still the only place
                                 # money appears (INV-15); this field is its result, not a second
                                 # pricer.
    reserved_micros: int = 0     # the p95 CEILING: the output-proportional dimensions multiplied by
                                 # `tokens_out_p95_multiple`, then priced. What `admit()` holds, and
                                 # what `ow route lint` check 13 compares `micros_per_part` against.

    def decision_id(self) -> str: ...
        # 'dec_' || sha256_canonical(<the eight identity fields>)[:24]. DERIVED, which is what makes
        # the insert idempotent under concurrency: two `ow ingest` processes computing the same
        # decision converge on one row (§4.3 property 6).
```

Four things the table carries that this type deliberately does not, each because it is not part of
what was *decided*: `audit_selected`, because the sampler needs `unit_uri`, which is not in the
identity and which `evaluate()` must never see (RT2); `grant_id`, which `admit()` step 3 issues;
`admission`, which is `admit()`'s own verdict; and `decided_at`, which exists for humans and
retention only. One whole family is absent for a different reason: `render`, `max_cost_class`,
`skip_rungs`, `deny_lanes` and the admitted lane set are **modifiers**, and the modifier set is a
pure function of `(policy_digest, evidence)` — both already in the identity — so `ow route explain`
recomputes it exactly from the stored read set and it needs neither a field nor a column (§4.2).

### `Modifiers` — the other half of one `evaluate()` call

```python
@dataclass(frozen=True, slots=True)
class Modifiers:
    """Every matching modifier rule contributes; the combination is per key, and each key's monoid
    is the one §4.2's table states. Not first-match-wins — which is what lets one part take four
    GATE modifiers at once, the case a single ordered list cannot deliver."""
    max_cost_class: CostClass = CostClass.BILLED_API   # MINIMUM. A clamp: it can only lower.
    admit_lanes: frozenset[str] = frozenset()          # set UNION over matching rules
    deny_lanes: frozenset[str] = frozenset()           # set UNION, applied AFTER every admit_lanes,
                                                       # so a denial always wins
    render: Literal["structure", "glyph"] | None = None   # the MORE EXPENSIVE profile wins
    skip_rungs: frozenset[Rung] = frozenset()          # set UNION; every member strictly greater
                                                       # than the rule's own rung (`OW-P-005`)
    flag_blocks: bool = False                          # logical OR
    not_eligible: frozenset[int] = frozenset()         # set UNION of excluded block ids. The
                                                       # modifier form of `outcome`: it excludes
                                                       # BLOCKS from the rung without touching the
                                                       # part, which is how `REPAIR` is made
                                                       # structurally unavailable on PDF (Part 3).
    rule_ids: tuple[str, ...] = ()                     # every modifier rule that contributed, in
                                                       # file order. `ow route explain` prints them.
```

### `RouteHints` — the `request` layer, and the field it does not have

```python
@dataclass(frozen=True, slots=True)
class RouteHints:
    """The `request` merge layer (§4.1). It RESTRICTS and never widens, which is what makes it safe
    to accept from an agent over MCP or the SDK."""
    lane: str | None = None                 # `request.lane`
    max_rung: Rung | None = None            # `request.max_rung`; a part that would have escalated
                                            # past it records `Degradation(kind="rung_ceiling")`
    prefer_capability: str | None = None    # `request.prefer_capability`, a `Capabilities` key
    deadline_ms: int | None = None          # `request.deadline_ms`
    schema: Mapping | None = None           # `request.schema_present` IS its presence, and it is
                                            # what admits the `fields` lane
    # IT HAS NO budget, egress OR licence FIELD, AND THEREFORE CANNOT WIDEN ANYTHING. `--allow-cost`
    # is CLI-only for exactly this reason (§7.3), and the absence IS the mechanism: there is nothing
    # to validate at the MCP boundary because there is no field to send.
```

---

# Part 5 — The escalation signals

Every number the router acts on is a registered `Signal`. Registration is a `SignalSpec` row read from
a `signals.toml` by the same import-free `tomllib` loader that reads a `DriverCard`, so registration
executes no provider code — INV-4's rule, applied to providers. A provider is declared by an
`omniweave.signals` entry point plus a `signals.toml`; it is **not** a `DriverCard` (no capability
floors, never in `resolve()`) and is selected by name, exactly like a `VectorBackend`. The four
shipped providers are `builtin` (in `omniweave`, stdlib only), `pdfium` (in `omniweave-pdf`),
`officexml` (in `omniweave-office`) and `vision` (in `omniweave-vision`, which registers nothing at
release 1 because `layout.class_hist` has no licence-clean weights).

## 5.1 The day-one registry

**This section is the sole home of the signal registry.** The charter's 23-row day-one table at
`:2498` is superseded by the per-key table below under charter erratum **`E38`**, which a later
stage writes into §9.2 ([ADR-3](adr/0003-shipped-configuration.md) decision 4). That is what
discharges Open question 3: `block.flagged_frac` is registered here, part-scoped, `measure`, FREE,
nullable, `req = REPAIR`, so the shipped policy passes `ow route lint` check 1 against this table.
A second registration of any key — in the charter, in another plan document, or in a driver's
`signals.toml` beyond the provider rows §5.2 governs — is a defect, not an override.

`cost` is the `CostClass`. **`est` is a declared budget, not a measurement**: `SignalSpec.est` is
author-declared exactly as `[cost.model]` is, and `ow conform --bench` overwrites it into
`signals.lock` on `x86_64-linux 8c/16GiB, US Letter, structure profile`, exactly as `[cost.measured]`
overwrites a card's. A provider whose measured p50 exceeds its declared `est` by more than 2× fails
`ow drivers check`. `null` says whether the key can be UNKNOWN at routing time — the column
`ow route lint` check 4 reads. `req` is `SignalSpec.requires`, and it names the rungs whose **driver
output** the signal reads (§4.3), not the rungs at which something similar could be computed.

**One `domain` in this table is not a literal.** `unit.format`'s domain is **computed, not literal**:
core's 48 tokens ∪ the union of the `token` fields of `[capability.parse] format_tokens` — a list of
`{media_type, token}` pairs, [04](04-driver-system.md) §2.2 — over every driver in
`[drivers] enabled`. The union is taken at policy-compile time and enters `policy_digest`, so a rule
naming a driver-contributed token resolves under lint checks 2, 10 and 11 exactly as a builtin token
does, and disabling the driver makes the same rule fail the linter rather than silently match nothing.
`enum_val`'s `format` domain is seeded from the same union.

**The registration record, which every row of the table below instantiates.**

```python
# omniweave/route/evidence.py — read by the import-free `tomllib` loader, never by importing a
# provider (INV-4). One instance per (key, provider): `unit.part_count` has three, disjoint by
# `serves`, and the registry resolves the pair at read time (5.2).

class ComputedDomain(Enum):
    """A domain that is not a literal in `signals.toml` because it depends on which drivers are
    enabled. Resolved at policy-compile time and folded into `policy_digest`, so a rule naming a
    driver-contributed token lints exactly as a builtin token does."""
    FORMAT_TOKENS = "format_tokens"     # core's 48 union the `token` fields of the enabled cards'
                                        # `[capability.parse] format_tokens` (5.1 above; 04 2.2).
                                        # `unit.format` is its only member in the day-one registry.

@dataclass(frozen=True, slots=True)
class SignalSpec:
    key: str                            # "<group>.<name>", both [a-z][a-z0-9_]*. The `key` column.
    scope: Literal["unit", "part", "block", "doc"]          # the `scope` column
    kind: Literal["fact", "measure", "classifier", "count"] # the `kind` column
    dtype: Literal["bool", "int", "float", "str"]           # the `dtype` column
    domain: tuple[float, float] | frozenset[str] | ComputedDomain | None
    # ^ the `domain` column. A float pair is INCLUSIVE ON BOTH ENDS; a `frozenset[str]` is what
    #   `ow route lint` check 2 tests a rule's literals against; `None` is a bool or an unbounded
    #   int. Registration REFUSES kind="classifier" whose domain is not [0.0, 1.0] closed on both
    #   ends (RT5) — a softmax legitimately returns 0.0 and 1.0.
    cost_class: CostClass               # the `cost` column: FREE | LOCAL_COMPUTE | BILLED_API.
                                        # The demand plan (4.3) groups by this, ascending.
    est: Spend                          # the `est` column, as a Spend and not a scalar ms: a
                                        # DECLARED BUDGET, overwritten into `signals.lock` by
                                        # `ow conform --bench`. A measured p50 above 2x `est`
                                        # fails `ow drivers check`.
    provider: str                       # an `omniweave.signals` entry-point name. SINGULAR: a key
                                        # served by several providers is several rows (5.2).
    version: str                        # provider semver. ENTERS THE READ SET, so a decision names
                                        # exactly which code produced each value (7.1).
    serves: frozenset[str] = frozenset()          # the format tokens this provider answers `key`
                                        # for; empty means every format. Two providers claiming one
                                        # (key, format) is `OW-P-022` at startup, not a precedence
                                        # puzzle (5.2).
    requires: tuple[Rung, ...] = ()     # the `req` column: rungs whose DRIVER OUTPUT this signal
                                        # reads. It is what derives a rule's select/settle phase
                                        # (4.3) and what lint check 7 (`OW-P-010`) tests.
    nullable: bool = True               # the `null` column, inverted. False means the key can never
                                        # be UNKNOWN at routing time, so a rule reading it needs no
                                        # `on_unknown` — lint check 4 (`OW-P-004`) reads this field.
                                        # Uncomputable is None; NEVER a default value.
```

Three fields carry the whole three-valued discipline and are worth naming together: `nullable` is
what lint check 4 reads, `requires` is what derives the phase and what check 7 reads, and `domain`
is what check 2 reads. A signal that gets any of the three wrong fails a lint rather than producing
a wrong route, which is the reason the registration is data rather than a decorator.

| key | scope | kind | dtype | domain | cost | est | null | req | provider(s) |
|---|---|---|---|---|---|---|---|---|---|
| `unit.format` | unit | fact | str | **computed** — core's 48 tokens ∪ the `token` fields of the enabled cards' `[capability.parse] format_tokens` (see the paragraph above this table) | FREE | 0.4 ms | no | — | builtin |
| `unit.format_basis` | unit | fact | str | `{magic, container_identity, content_probe, extension, declared, driver_sniff}` | FREE | 0 | no | — | builtin |
| `unit.bytes` | unit | count | int | [0, 2^63) | FREE | 0 | no | — | builtin |
| `unit.part_count` | unit | count | int | [0, 2^31) | FREE | 6 ms | no | — | pdfium · officexml · builtin |
| `unit.encrypted` | unit | fact | bool | — | FREE | 0.5 ms | **no** | — | pdfium · builtin ([ADR-15](adr/0015-encrypted-pdfs-and-document-passwords.md) D15.2) |
| `unit.corrupt` | unit | fact | bool | — | FREE | 0.6 ms | **no** | — | builtin |
| `unit.producer_family` | unit | fact | str | ~30 members plus `und` | FREE | 0.3 ms | **yes** | — | builtin |
| `unit.needs_ocr_parts` | unit | count | int | [0, 2^31) | FREE | 3 ms | **yes** | — | pdfium |
| `unit.trust_class` | unit | fact | str | `{internal, untrusted_external}` | FREE | 0 | no | — | builtin |
| `unit.schema_requested` | unit | fact | bool | — | FREE | 0 | no | — | builtin |
| `corpus.is_form` | unit | fact | bool | — | FREE | 2 ms | **yes** | — | pdfium · officexml |
| `corpus.lang` | unit | fact | str | ISO-639-1 plus `und` | FREE | 9 ms | **yes** | DECODE | builtin |
| `corpus.spam_score` | unit | classifier | float | [0.0, 1.0] | FREE | 0.5 ms | **yes** | DECODE | builtin |
| `corpus.dup_of` | unit | fact | str | — | FREE | 0.1 ms | **yes** | — | builtin |
| `decode.char_count` | part | count | int | [0, 2^31) | FREE | 1.1 ms | **yes** | — | pdfium · officexml |
| `decode.line_count` | part | count | int | [0, 2^31) | FREE | 1.1 ms | **yes** | — | pdfium · officexml |
| `decode.has_text_span` | part | fact | bool | — | FREE | 0 | **yes** | — | pdfium · officexml |
| `decode.cid_ratio` | part | measure | float | [0.0, 1.0] | FREE | 1.8 ms | **yes** | — | pdfium |
| `decode.replacement_ratio` | part | measure | float | [0.0, 1.0] | FREE | 0.2 ms | **yes** | DECODE | builtin |
| `decode.stream_monotonicity` | part | measure | float | [0.0, 1.0] | FREE | 0.9 ms | **yes** | DECODE | pdfium |
| `geometry.overlap_line_frac` | part | measure | float | [0.0, 1.0] | FREE | 2.4 ms | **yes** | DECODE | pdfium |
| `geometry.ruled_regions` | part | count | int | [0, 4096] | FREE | 1.5 ms | **yes** | — | pdfium |
| `garble.score` | part | classifier | float | [0.0, 1.0] | FREE | 0.4 ms | **yes** | DECODE | builtin |
| `math.font_hit` | part | fact | bool | — | FREE | 0.3 ms | **yes** | — | pdfium · officexml |
| `math.part_frac` | part | measure | float | [0.0, 1.0] | FREE | 0.6 ms | **yes** | DECODE | builtin · officexml |
| `table.grid_score` | part | **measure** | float | [0.0, 1.0] | FREE | 4-30 ms | **yes** | DECODE | pdfium · officexml |
| `ink.tiles` | part | count | int | [0, 2^31) | LOCAL_COMPUTE | 15 ms | **yes** | — | pdfium |
| `ink.coverage` | part | measure | float | [0.0, 1.0] | LOCAL_COMPUTE | 16 ms | **yes** | DECODE | pdfium |
| `render.short_edge_px` | part | measure | float | [0, 65536] | FREE | 0.1 ms | **yes** | — | pdfium |
| `layout.class_hist` | part | count | int | [0, 2^31) | LOCAL_COMPUTE | — | **yes** | — | **none (day 1)** |
| `block.type` | block | fact | str | the `Kind` wire values | FREE | 0 | **yes** | DECODE | officexml; **none on PDF** |
| `block.char_count` | block | count | int | [0, 2^31) | FREE | 0 | **yes** | DECODE | builtin |
| `block.area_frac` | block | measure | float | [0.0, 1.0] | FREE | 0 | **yes** | DECODE | builtin |
| `block.sibling_containment` | block | measure | float | [0.0, 1.0] | FREE | 0.1 ms | **yes** | DECODE | builtin |
| `block.has_ink` | block | fact | bool | — | LOCAL_COMPUTE | 0.4 ms | **yes** | — | pdfium |
| `block.flagged_frac` | **part** | measure | float | [0.0, 1.0] | FREE | 0 | **yes** | REPAIR | builtin |
| `verify.repeat_ngram_max` | part | count | int | [0, 2^31) | FREE | 0.6 ms | **yes** | PAGE | builtin |
| `verify.finish_reason` | part | fact | str | `{stop, length, content_filter, error}` | FREE | 0 | **yes** | PAGE | builtin |
| `verify.token_saturation` | part | measure | float | [0.0, 1.0] | FREE | 0 | **yes** | PAGE | builtin |
| `verify.parse_ok` | part | fact | bool | — | FREE | 0.3 ms | **yes** | PAGE | builtin |
| `verify.nonempty` | part | fact | bool | — | FREE | 0 | **yes** | PAGE | builtin |
| `verify.attempts_exhausted` | part | fact | bool | — | FREE | 0 | **yes** | REGEN | builtin |
| `verify.grounded_field_frac` | unit | measure | float | [0.0, 1.0] | FREE | 4 ms | **yes** | PAGE | builtin |
| `agree.decode_vs_page` | part | measure | float | [0.0, 1.0] | FREE | 1.2 ms | **yes** | DECODE, PAGE | builtin |
| `doc.escalated_part_frac` | doc | measure | float | [0.0, 1.0] | FREE | 0 | no | — | builtin |
| `doc.rung_run_length` | doc | count | int | [0, 2^31) | FREE | 0 | no | — | builtin |
| `driver.unavailable` | part | fact | bool | — | FREE | 0 | no | — | builtin |
| `budget.exhausted` | part / unit | fact | bool | — | FREE | 0 | **yes** | — | `admit()` |
| `trigger.kind` | unit | fact | str | `{cli,hook,upstream,watch,mcp,sdk}` | FREE | 0 | no | — | builtin |
| `request.lane` | unit | fact | str | the `LANES` registry | FREE | 0 | **yes** | — | builtin |
| `request.max_rung` | unit | count | int | [0, 6] | FREE | 0 | **yes** | — | builtin |
| `request.prefer_capability` | unit | fact | str | the `Capabilities` key set | FREE | 0 | **yes** | — | builtin |
| `request.deadline_ms` | unit | count | int | [0, 2^31) | FREE | 0 | **yes** | — | builtin |
| `request.schema_present` | unit | fact | bool | — | FREE | 0 | no | — | builtin |

Fifty-four keys. Three are registered and **read by no shipped rule**, deliberately:
`corpus.spam_score`, `corpus.dup_of` and `agree.decode_vs_page`. olmocr's `PdfFilter` maps the first
two classes of verdict to a document-level *exclusion* with a `logger.info`
(`olmocr/olmocr/filter/filter.py:14-112`, a 12-word SEO lexicon at threshold 0.004), which is the
anti-pattern the charter names; here they are slice axes and hooks for a site-layer rule, and
`ow route scoreboard --by corpus.dup_of` is how an operator finds a corpus that is 40% duplicates.
`agree.decode_vs_page` is read by the quality writer (§8.1), not by `evaluate()`. `request.*` is
enumerated key by key rather than globbed, because `ow route lint` check 1 cannot resolve a glob.

## 5.2 Provider resolution: one key, several providers, disjoint formats

`SignalSpec.provider` in the charter is a single entry-point name, and three rows above need more
than one: `unit.part_count` comes from `FPDF_GetPageCount` on a PDF and from a sheet count on an
XLSX, and `math.part_frac` is a font-and-text computation on a PDF and an `m:oMath` element count in
`word/document.xml`. Rather than duplicate keys per format — which would put `math.part_frac_pdf`
into a policy file and make every rule format-aware — a `signals.toml` entry declares which formats
its provider serves:

```toml
# omniweave-office/src/omniweave_office/signals.toml
[signal."math.part_frac"]
serves  = ["docx", "pptx", "odt", "odp", "epub"]
version = "1.0.0"
kind    = "measure"
dtype   = "float"
domain  = [0.0, 1.0]
cost_class = "free"
requires   = ["DECODE"]
nullable   = true
est = { cpu_ms = 1 }
```

Three rules make this safe. **Registration refuses an overlapping claim**: two providers naming the
same `(key, format)` is `OW-P-022` at startup, not a precedence puzzle, so exactly one provider serves
a key for a given `unit.format`. **A format no provider claims yields UNKNOWN**, which is the
three-valued path and not a default. And **the read set records the resolved provider's version**, so
`read_set_digest` still names exactly which code produced each value and a decision taken on a PDF is
not invalidated by an `officexml` version bump. `ow route lint --explain` prints the provider resolved
per format, which is how a reviewer sees at a glance that `block.type` has no PDF row.

This is what closes the OMML hole: `math.font_hit` and `math.part_frac` on the office path are an
element count over `m:oMath` / `m:oMathPara` (Word, PowerPoint) and `math:math` (ODF, EPUB) against
the paragraph count, which is a few lines in the provider that already parses that XML — so
`decode.admit-math-lane` fires on a DOCX rather than reading UNKNOWN.

## 5.3 How each signal is computed, and how it lies

The false-positive column is the load-bearing one: a signal with an unnamed failure mode is a signal
nobody can tune.

| signal | computation | named false positives, and what absorbs them |
|---|---|---|
| `unit.encrypted` | **detection-provided and non-nullable**, from three byte-scannable facts: a CFB root storage holding `EncryptedPackage` (binary Office and encrypted OOXML), an OCF `META-INF/manifest.xml` carrying `encryption-data`, and an `/Encrypt` reference in a PDF trailer or XRef-stream dictionary. A residual false *negative* — a PDF whose `/Encrypt` the scan misses — surfaces as pdfium's `FPDF_ERR_PASSWORD` at `DECODE` and becomes `DriverError(ENCRYPTED)` | a PDF with `/Encrypt` and an empty owner password is technically encrypted and practically readable; [ADR-15](adr/0015-encrypted-pdfs-and-document-passwords.md) D15.2 reads it, because the `pdfium` provider answers whether the file opens. Printed before that ruling: `[ingest] password_file` accepts an empty secret and why a successful open **recomputes the key as `false`** rather than overriding the rule |
| `unit.corrupt` | **detection-provided and non-nullable**: the container-level structural check the format's own specification mandates, and nothing deeper — no `%%EOF` and no locatable xref or XRef stream (PDF), a bad or truncated ZIP central directory, a CFB whose FAT chain does not close, a truncated `mimetype` member. Deep or per-page corruption is *not* this key; it surfaces as a per-part `DECODE` failure and `doc.status = 'partial'` | a PDF with a broken xref that pdfium reconstructs successfully is refused here and would have parsed. The escape is `ow add --accept-partial`, and the rate is visible because `gate.corrupt` decisions carry `reason` |
| `unit.producer_family` | the format-appropriate producer string, bucketed to ~30 families by an exact-prefix table: PDF `/Producer`, OPC `docProps/app.xml` `<Application>`, ODF `meta:generator`, HTML `<meta name="generator">`. Unrecognised is `und`, never NULL for a format that has the field. It is the strongest cheap layout-pathology predictor and therefore the natural slice axis | a re-saved document carries the *last* producer, not the original — a Workiva 10-K printed through Acrobat reads `acrobat`. The consequence is a slice that mixes two pathologies, which shows up as high within-slice variance in `ow route scoreboard` |
| `decode.char_count` `line_count` `has_text_span` | one provider call over the text layer or the office XML; `requires = ()` because pdfium answers `FPDFText_CountChars` from the source bytes | none — they are counts |
| `decode.cid_ratio` | the fraction of glyph runs whose font has no `ToUnicode` CMap, has a partial one, or is CID-keyed with no mapping, over pdfium font data. Precedent, not source: `anydoc/src/formats/pdf.rs:26-29` receives a *document-level boolean* from the external `pdf-inspector` crate and only `log::warn!`s it | a decorative symbol font (a bullet dingbat, a logo glyph) is legitimately unmapped, which is why the threshold is 0.10 and not 0.0. A part that is entirely math in a Type 1 symbol font reads as fully broken; the `math` lane is admitted on the same part, which is the right answer anyway |
| `decode.replacement_ratio` | U+FFFD, private-use code points and stray C0 controls over the decoded text. `marker/marker/processors/table_recon.py:27` uses the same test at `_GARBLE_CHAR_FRAC = 0.02`, which is where the threshold comes from | a document quoting U+FFFD, and CJK in a PUA-mapped legacy font (Big5 extensions). The CJK case is real and is why `corpus.lang` is a slice axis: the threshold is fitted per slice, so a Chinese corpus gets its own number |
| `decode.stream_monotonicity` | the fraction of adjacent line pairs whose character-stream order agrees with their geometric order, compared **within a detected column band**. This is the signal behind marker's measured **75% (char stream) vs 56% (learned head)** reading-order result (`marker/builders/line.py:76-84`) | a multi-column page whose char stream is column-major reads as non-monotone under a naive top-to-bottom comparison — hence the band. A page whose bands cannot be detected returns `None`, not a low number: "we could not tell" and "the stream is scrambled" are different facts |
| `geometry.overlap_line_frac` | marker's signal 4, verbatim (`line.py:266-298`), and the one of its four page signals that was **never** licence-at-risk, because `check_line_overlaps` reads only line bboxes and the page polygon. `intersect_counts = (intersection_matrix > 0.1).sum(axis=1)`; `over_intersecting = (intersect_counts > 2).sum()`; value = `over_intersecting / len(lines)`. **It returns exactly 1.0 when any line bbox escapes `page.polygon.expand(5, 5)`** — marker's separate early-out, which returns a boolean and has no other encoding in a `[0,1]` signal | `> 2` and not `> 0` because inline math (stacked radical and fraction spans) and dense figure labels legitimately overlap a neighbour or two; marker's own comment says so. A full-page watermark text layer and a two-up scan sharing one PDF page both trip it — and both are genuinely worth escalating, so the false positive is benign |
| `geometry.ruled_regions` | closed axis-aligned rectangles formed by the part's vector path objects, with collinear segments merged under a **2.5 pt** gap (marker's own `table_recon` tolerance) and rectangles under 1% of the page area discarded. It exists to give the `table` lane a region on PDF without a layout model | a page border, a pull-quote box and a form field each read as a region, so the `table` lane is admitted on parts that hold no table. The cost of that false positive is bounded and visible: `table.grid_score` on a non-table region scores low on `purity` and *would* escalate, which is exactly why `@thresholds.table_grid_min` is per-slice learnable. **The false negative is the expensive one:** a borderless table yields 0 and the lane never engages (§3.1) |
| `math.font_hit` `math.part_frac` | PDF: `marker/marker/processors/equation.py:63-71` — a math font name returns immediately (high precision); otherwise `math_chars / len(text) > 0.02` per block, and above 30% flagged blocks the whole part is flagged. Office: an `m:oMath` / `math:math` element count over the paragraph count (§5.2) | a chemistry paper's subscript-heavy prose and a table of part numbers flag as math. The consequence is an `ENRICH` pass that emits no `math` blocks — non-fatal by construction |
| `table.grid_score` | marker has **no** table-structure model. `reconstruct_table_html(lines)` returns `(html, score)` and the caller gates on `min_recon_score` (`table.py:104-126`). The composite is `(purity + no_compound + fill + hdr + 2*one_span) / 6` (`table_recon.py:188-212`), with `one_span` double-weighted; five grid candidates are swept and the best kept. It needs a **region** and the **char-level** decode, so it is computed only for parts in the `table` lane, and `parse.pdf.pdfium` retains the char-level page for the `DECODE` settle phase and releases it immediately after | a two-column layout inside a ruled box scores well on `one_span` and `fill`; a legitimately ragged table (merged cells, a spanning subtotal row) scores badly on `purity` and escalates a table that was fine. The second is the expensive direction, and it is why the threshold is per-slice learnable — filings from one `unit.producer_family` are consistently ragged. `kind = "measure"`, deliberately not `"classifier"`: it is a heuristic composite with no ground-truth distribution, so demanding an ECE gate on it would only be satisfied by a lie |
| `doc.rung_run_length` | the length of the current run of consecutive parts that decided the same `(rung, driver)`. Zero cost: a counter the router already maintains to write `doc.escalated_part_frac` | none. It exists for **amortisation, never for evidence skipping** — the charter rejects `signal_sampling {head, stride, cap}` permanently, on the measurement that a stride of 32 misses a 40-page scanned appendix at pages 2,900-2,940 of a 4,000-page report |
| `agree.decode_vs_page` | `requires = (DECODE, PAGE)`. When a part escalates you have already paid for two independent readings of the same pixels, so the normalised edit distance between them costs nothing and lands exactly on the population where the cheap driver is suspect | `TruthKind = "agreement"`, and it may **never** populate an accuracy column: two readings agreeing is not evidence that either is right. Its job is to find slices where escalation changed *nothing* (a threshold too low) and slices where escalation changed *everything* (a text layer that should never have been trusted) |
| `verify.*` | `olmocr/olmocr/repeatdetect.py`'s streaming n-gram counter for `repeat_ngram_max`; the provider's own `finish_reason`; `tokens_out / max_tokens` for saturation; a schema or fence parse for `parse_ok`; a non-whitespace test for `nonempty`; the attempt counter for `attempts_exhausted` | a legal document with a genuinely repeated clause trips `repeat_ngram_max >= 12`. `repetition_penalty` stays **1.0** — real documents repeat — so the guard is the detector, and its cost when wrong is one extra `REGEN` attempt bounded by `[budget.per_part] calls = 3` |

### `garble.score` — the licence-free replacement for surya's OCR-error model

surya ships a DistilBERT classifier pointed at `s3://ocr_error_detection/2025_02_18`
(`surya/surya/settings.py:137`) under a `MODEL_LICENSE` this framework cannot ship. `garble.score` is
a **fitted logistic regression over seven CPU features**, pure Python in the `builtin` provider, with
a bundled coefficient file:

| feature | computation |
|---|---|
| `cid_frac` | `decode.cid_ratio`, reused, not recomputed |
| `replacement_frac` | `decode.replacement_ratio`, reused |
| `oob_char_frac` | characters outside the part's dominant Unicode block |
| `dict_miss_rate` | tokens absent from a 40k-word list for `corpus.lang`, over alphabetic tokens |
| `single_char_token_frac` | one-character tokens over all tokens — broken CMaps produce these |
| `char_5gram_logprob` | mean log-probability under a bundled character 5-gram model for the language |
| `vowelless_run_frac` | run-length-normalised fraction of 5+-character alphabetic runs with no vowel |

`kind = "classifier"`, so registration refuses it unless its declared domain is `[0.0, 1.0]` **closed
on both ends** — a softmax legitimately returns 0.0 and 1.0 (RT5). **Calibration is a CI gate** (RT6:
ECE at most 0.05, Brier at most 0.08 on a held-out set; a regression fails the build), because
marker's `>= 0.05` recheck gate is meaningless against an uncalibrated probability. **Keep the score,
never the label:** `surya/surya/ocr_error/schema.py` documents `scores` as existing for exactly that
— "lets callers gate expensive follow-up work on confidence instead of just the argmax label".

*False positives, named:* code listings (`dict_miss_rate` and `single_char_token_frac` both spike),
chemical formulae, gene sequences, tables of part numbers, and any language whose 5-gram model is
absent — `corpus.lang = "und"` sets that feature to its **training mean** rather than to zero, which
is the difference between "unknown language" and "definitely garbage". Below
`@thresholds.garble_min_chars = 50` characters the verdict is not trusted at all and the signal
returns `None` (marker's `min_garbled_text_chars`, `line.py:110-114`), which is why
`decode.part-text-unusable` declares `on_unknown = "match"`: a short part escalates to a cheap reading
rather than passing silently.

### `ink.tiles` and `ink.coverage` — replacing a licensed detector with actual ink

These replace marker's `layout_coverage`, which needs the Datalab layout detector. The substitution is:
**keep marker's threshold (0.25, `line.py:35-39`), replace the detector's *opinion* with actual ink.**
Render the part at the `structure` profile in **grayscale**, threshold at 0.85 relative luminance, and
reduce 8×8 pixel tiles with a **min-pool** — a tile is inked if *any* pixel in it is dark. The
reduction is three C-level passes and no third-party array library, because `omniweave` depends on
core, ports and office only:

```
render     -> 816x1056 grayscale bytes at 96 DPI  (=861,696 B)                ~12 ms  (pdfium)
translate  -> one byte per pixel, 0x00 or 0x01 (bytes.translate, one pass)     ~0.6 ms
reduce     -> per tile row: OR 8 raster rows as big ints (int.from_bytes),
              then 3 shift-ORs to fold 8 columns into 1, then take every 8th   ~1.4 ms
              byte -> a 102 x 132 = 13,464-tile bitmap
                                                                              ----------
                                                                              ~15 ms declared budget
```

A **min**-pool and not a box average: a single one-pixel stroke across an 8×8 tile averages to 0.875
relative luminance and would be discarded, which is exactly the thin serif text a scan needs to keep.

- `ink.tiles` is the count of inked tiles, out of 13,464 for US Letter at the structure profile. At or
  below `@thresholds.blank_page_tiles = 4` the part is blank and `decode.blank-part-escape` terminates
  on it. `requires = ()`: no decode needed.
- `ink.coverage` is inked tiles that intersect a text-layer line bbox, over all inked tiles.
  `requires = (DECODE,)`, because it needs those line boxes. Below `0.25` means "there is ink here the
  text layer does not explain": a figure with baked-in text, a scanned insert, a stamp, a signature.

*False positives:* a page that is one large photograph with a caption — the photo's ink is not
explained by the text layer, coverage collapses, and the part escalates to a `PAGE` call that re-reads
the caption it already had. **This is the single most expensive false positive in the shipped policy.**
It is bounded by `[budget.per_part] micros = 6_000`, and it is *visible*, because
`agree.decode_vs_page` on those parts is high and the slice shows low `escalation_divergence` — which
is exactly the evidence `ow route propose` reads to raise `ink_coverage_min` for that slice.

### The layout-class hole, and handwriting

`layout.class_hist` is absent at release 1 and every decision that would have read it records
`cause = "layout_unavailable"`. Two of the four classes it would have provided are recovered without a
model: **math**, by `math.font_hit` / `math.part_frac`, and **ruled table structure**, by
`geometry.ruled_regions` plus `table.grid_score`. The other two are not, and the recovery of tables is
partial: a borderless PDF table is not detected (§3.1).

**Handwriting is not detected at release 1, and this document says so rather than implying otherwise.**
A fully handwritten page routes correctly by accident: it has no text layer, so `decode.no-text-layer`
sends it to `PAGE`. The failure case is a *handwritten annotation on a born-digital page* — clean text
layer, low `garble.score`, annotation invisible. `ink.coverage` is the only signal that would catch it
and it is `LOCAL_COMPUTE`, so on a clean page the demand plan correctly never computes it. A real,
priced hole; see Open questions and [17-risks.md](17-risks.md).

## 5.4 The signal cache

```sql
CREATE TABLE route_signal (
    content_sha256 TEXT NOT NULL, unit_part TEXT NOT NULL DEFAULT '',
    signal_key TEXT NOT NULL, signal_version TEXT NOT NULL,
    value BLOB, unavailable_reason TEXT, compute_ms INTEGER NOT NULL, computed_at INTEGER NOT NULL,
    PRIMARY KEY (content_sha256, unit_part, signal_key, signal_version)
) WITHOUT ROWID;
```

Keyed on **content**, so identical bytes never recompute, and **per signal rather than per suite**, so
one signal's version bump invalidates one row and not the other fifty-three. Writes are
`INSERT OR REPLACE`, which is safe under concurrency because the value is a pure function of the key.
`unavailable_reason` is stored alongside `value` because "we tried and could not" is a cacheable fact
— otherwise every run re-attempts a signal whose provider is not installed. The decision itself is
microseconds; the 96-DPI raster is not, which is why this table exists and `route_decision` is not the
cache. `[cache.max_bytes] signal = 2_147_483_648` and `[cache] gc.local_after_days = 90` govern the
raster side through `cache_index` layer `render`; the `route_signal` rows themselves are ~90 B each,
and only *computed* signals get a row — a clean born-digital part writes five (§4.3).
`--ignore-evidence-cache` re-computes them and can only ever spend `free`/`local_compute` — it is not
`--allow-rebill`, which is the flag that costs money and prints the count and the
`would_have_been_micros` it is about to discard. One flag per hazard.

---

# Part 6 — The cost model

## 6.1 Seven physical units, and no driver prices anything

```python
@dataclass(frozen=True, slots=True)
class Spend:
    wall_ms: int = 0; cpu_ms: int = 0; gpu_ms: int = 0
    tokens_in: int = 0; tokens_out: int = 0; calls: int = 0; bytes_egress: int = 0
    provider: str = ""                        # "" == local
    def __add__(self, other: "Spend") -> "Spend": ...
    def micros(self, book: "PriceBook") -> int: ...      # THE ONLY PLACE MONEY APPEARS (INV-15)
```

`DriverMetrics` has no currency field and `[cost.*]` on a card has none either. A contributor on a
rented A100 cannot know your GPU-hour cost, and if they guess, every estimate in your fleet is wrong
in a way you cannot audit. Seven units and not six: `bytes_egress` is separate from `calls` because it
is the dimension a `Grant` gates, and its budget defaults to **0** so the first hosted escalation is a
deliberate act. `wall_ms` is priced at 0.0 by default. It is in the vector because it is the dimension
a *deadline* is expressed in, and because a `wall_ms` budget is the only guard against a driver that is
free and slow; pricing it would double-count CPU on a single-tenant machine.

## 6.2 `.omniweave/pricebook.toml` — operator-owned, versioned, digested

Every rate below is `micros per unit`, and every one shows its arithmetic. A micro is 10⁻⁶ of the
`currency`. The two local rates are **examples of the shape, not omniweave's prices**: an operator
substitutes their own, and the arithmetic is printed so a substitution can be checked.

```toml
version        = 3
currency       = "USD"
effective_from = 2026-09-01

[local]
# 0.0334 $/vCPU-h / 3.6e6 ms-per-h = 9.2778e-9 $/ms = 0.0092778 micros/ms  (example: a c7i vCPU)
cpu_ms_micros       = 0.00928
# 1.28 $/h for one A10G / 3.6e6 = 3.5556e-7 $/ms = 0.35556 micros/ms       (example: g5.xlarge)
gpu_ms_micros       = 0.3556
wall_ms_micros      = 0.0            # 0.0 = UNPRICED, which is not the same as free
bytes_egress_micros = 0.0

[provider.parasail]
# olmocr/README.md "Verified External Providers": the highest of the three listed resellers
tokens_in_micros    = 0.10           # $0.10/1M tokens = 1e-7 $/token = 0.10 micros/token
tokens_out_micros   = 0.20           # $0.20/1M tokens
calls_micros        = 0.0
bytes_egress_micros = 0.00009        # 0.09 $/GB / 1e9 B = 9e-11 $/B = 9e-5 micros/B

[provider.openai]
tokens_in_micros    = 0.15
tokens_out_micros   = 0.60
calls_micros        = 0.0
bytes_egress_micros = 0.00009
```

The two rates to check hardest are the local ones, because an error there is invisible: at
`gpu_ms_micros = 0.3556` and olmocr's p50 of 2.4 s, one `PAGE` call is `2400 × 0.3556 = 853.4` micros
≈ $0.00085/page, and the charter's 116,400-escalated-page reference ingest is
`116,400 × 853.4 = 99.3e6` micros ≈ **$99** — inside the charter's `$23-$80` reference band once
server-side Coalescing (a 1.5×-4× band, measured nowhere; charter §7 F7) is counted, and within a
factor of olmocr's own `<$200/1M pages` headline. Both of those are *unreconciled anchors*, which is
why `driver_by = "cheapest_admissible"` is opt-in.

`pricebook_digest` enters `route_decision`'s identity, so a price change makes a *new* decision row
rather than silently rewriting history — and `ow route replay --pricebook <old>` re-prices the whole
log against the previous book for $0. The `PriceBook` *is* the shadow prices; a separate `[objective]`
block would have been two versioned artefacts for one job. D734 reads the book: `ow ingest` loads `.omniweave/pricebook.toml` beside the store when there is one, and `PriceBook.digest` (`sha256_canonical` over the book, each rate as typed) is the run's `pricebook_digest`. The runner prices each attempt at commit, in `route_spend`'s writer. A paid attempt is `Spend.micros(book)`. A hit bills 0, and its `would_have_been_micros` is the Spend it replays, priced. The generation's bill is summed from `route_spend` into the manifest's cost block and the run report. With no book every attempt stays unpriced.

**`parse.page.olmocr` declares `class = "local_compute"`, and this is load-bearing.** It runs weights
you host and its `bytes_egress` is 0, so it is priced by `gpu_ms` through `[local]`. A hosted olmocr is
a *different driver id*, `parse.page.olmocr_hosted`, declaring `class = "billed_api"`,
`provider = "parasail"` and `bytes_egress > 0`, which `[budget.per_unit] bytes_egress = 0` blocks
without a `Grant`. That split is what makes `gate.watcher-may-not-bill`'s clamp to `local_compute`
mean "a watcher may still escalate locally", which is the charter's stated intent, and it is what makes
`ow route lint` check 9 satisfiable by the shipped policy.

## 6.3 How a driver declares its cost function

`[cost.model]` on the `DriverCard` is **author-declared and structural**; `[cost.measured]` is written
by `ow conform` and author values there are rejected. Only the author knows whether the driver loads a
model once per session; only the kit can measure what it then costs.

```toml
[cost.model]
class   = "local_compute"           # free | local_compute | billed_api — kit-VERIFIED
shape   = "linear_per_part"         # constant | linear_per_part | linear_per_byte | linear_per_token
unit    = "part"
per_part    = { gpu_ms = 2400, cpu_ms = 120, tokens_in = 1800, tokens_out = 1100, calls = 1 }
per_session = { wall_ms = 31_000 }  # model load / warm-up. WALL, NOT GPU: see below.
scaling     = { key = "render.short_edge_px", exponent = 2.0, reference = 1384 }
tokens_out_p95_multiple = 3.2       # `ow drivers check` FAILS if this is understated
max_retries = 0                     # a driver MAY NOT retry internally; retry is the runtime's
service     = "model:olmocr"        # ⇒ the estimator OMITS per_session entirely
```

The estimate for one decision:

```
est_spend       = per_part x (scaling.key_value / scaling.reference)^exponent
                  + (per_session / |sequence|   IF the card declares no `service`, else 0)
est_micros      = est_spend.micros(pricebook)
reserved_micros = est_spend with its OUTPUT-PROPORTIONAL dimensions x tokens_out_p95_multiple,
                  priced                                                    <- THE p95 CEILING
```

Three clauses that are easy to get wrong and that the Part 10 traces depend on:

- **`|sequence|` is the number of parts sharing a `sequence_id`; an unsequenced part is 1.** But when
  the card declares `service = "<name>"`, the `per_session` term is **omitted entirely**, because the
  model load belongs to the service — paid once per run, recorded on the run manifest, visible in the
  `service_attaches` counter. Charging it per decision double-counts it; charging it per sequence
  under-counts the unsequenced case. `parse.page.olmocr` declares a service, so its sequence rules
  save **wall time** (4 × 31 s = 124 s against `[budget.per_unit] wall_ms = 600_000`) and zero micros,
  which is exactly why `wall_ms` is in the `Spend` vector at all.
- **The p95 multiple applies to `gpu_ms` as well as `tokens_out`.** On a decode-bound VLM, GPU time is
  proportional to output tokens, so reserving the mean `gpu_ms` against a p95 `tokens_out` reserves a
  number that cannot occur. `tokens_in`, `calls` and `bytes_egress` are reserved at their declared
  values; they are input-proportional and known before the call.
- **`scaling` is one evidence key, one exponent, one reference value** — not an expression. The
  exponent-2 default on `render.short_edge_px` encodes the thing every VLM cost model gets wrong:
  tokens scale with *pixels*, so a 1384-px render costs 4× a 692-px one, and an A3 engineering drawing
  at the glyph profile is not "a page".

`max_retries = 0` is a contract, not a suggestion: olmocr's own pipeline is `MAX_TOKENS = 8000`
(`olmocr/olmocr/pipeline.py:107`) × `--max_page_retries 8` (`:1221`) = 64,000 output tokens per page,
which is $0.0128 at Parasail's $0.20/1M — a 64× amplification over the $0.0002/page headline, fired
**in parallel** on an idle queue at `--max_concurrent_requests 1600` (`:1223`). In omniweave a retry is
a `Rung` (`REGEN`), strictly serial per `(unit_part, lane)` behind a semaphore of 1, and charged to the
same per-part budget.

**Which dimension actually stops a runaway part, spelled out, because the arithmetic is not obvious.**
Reservations are released on commit (§6.4), so a retry chain does *not* accumulate p95 reservations:
attempt 1 reserves 2,732 and commits 854, attempt 2 sees `6000 − 854 = 5146` of headroom, attempt 3
sees `6000 − 1708 = 4292`, and the `micros` dimension alone would permit **five** attempts before
`6000 − 3416 = 2584 < 2732`. What binds first on this pricebook is `[budget.per_part] calls = 3`. That
is the honest statement, and it is not a retreat to "budget as a retry count": `calls` is one
*dimension of a priced vector*, checked by the same reservation machinery as `micros` and `gpu_ms`,
and the first exhausted dimension wins. A retry *counter inside a driver* cannot bound spend when
per-attempt cost varies 100× with page density; a declared `calls` ceiling alongside a declared
`micros` ceiling can, and on a denser pricebook or a larger render it is `micros` that binds. Both are
printed by `ow route explain`, which names the dimension that fired.

## 6.4 Budgets: declared per dimension, first exhausted dimension wins

`[budget.per_part]` and `[budget.per_unit]` live in `.omniweave/policy.d/*.toml` and **nowhere else**.
`omniweave.toml [budget]` holds admission only (`max_inflight`), so there is exactly one home for a
currency cap and no undefined precedence — and a `Degradation.message` can name a key that exists. A
CI test resolves every quoted config key in every `Degradation.message` template against the config
and policy schemas and fails on a miss.

```
the per_unit micros limit = clamp(micros_base + micros_per_part x unit.part_count, 0, micros_max)
every other per_unit dimension is a scalar and is not scaled by part_count
per-part dimensions are charged per (unit_part, lane): two lanes on one part have two budgets
```

`admit(d, ledger)` is the only impure half of routing:

```
1. clamp:   d.driver's cost_class above the GATE-established max_cost_class
            -> Degraded(Degradation(kind="budget", unit_dim="max_cost_class", …))
2. licence: compute_tier(card) not in [licence] allow_tiers -> Degraded(kind="driver_unavailable")
3. egress:  est_spend.bytes_egress > 0 with no site-layer Grant -> Degraded(kind="grant_missing")
4. reserve reserved_micros and every other declared dimension against budget_reservation,
   per (dim, scope, scope_key), with headroom computed IN SQL
5. the first dimension whose headroom is below the request -> Deferred(dim)
6. otherwise Admitted, with a durable reservation row whose expiry == the work row's lease_expires
```

Step 1 uses `kind = "budget"` with `unit_dim = "max_cost_class"` rather than a new `Degradation.kind`
member: the charter's `kind` literal is closed, a cost-class clamp is a spend refusal, and inventing a
parallel member for it would be the second `Degradation` type §5 X21 forbids.

**A reservation denial is not exhaustion.** Step 5 returns `Deferred(dim)`, the work row stays
claimable and `cost_micros` is unchanged; on commit, the gap between `reserved_micros` and the
`route_spend` row's actual `micros` is released **in the same transaction**, which can lift the very
denial that just fired. `budget.exhausted` is written into `Evidence` — and `on_exhausted` therefore
consulted — only when a deferred row is re-offered with **no sibling reservation still in flight for
the same scope key**. Without that clause a p95 reservation model degrades the second half of every
document while spending a third of the cap, which is exactly what the §10.3 trace makes visible.

The cost of a p95 model is worth stating plainly: at `tokens_out_p95_multiple = 3.2`, in-flight
reservations consume 3.2× the eventual spend, so effective concurrency against a per-unit cap is
roughly a third of nominal. Release-on-commit is what buys it back; the alternative — reserving the
mean — overdraws half the time against a *durable* ledger, and a durable overdraw is a bill.

Reservations are durable **rows**, so a crash cannot leak headroom and two scheduler processes cannot
each admit 2 and show the provider 4.

### `route_spend` — the authority on what was actually paid

The reservation is a promise; this row is the bill. It is written by the runner on **every attempt**,
in the same transaction as the derived rows, the `work` transition, the `dep` rows and the
reservation commit (I20), which is what makes `Σ route_spend.micros == manifest.cost.billed_micros`
hold **exactly** rather than within a tolerance. *(Build note, D854: a parse attempt now writes its row. Until D854 the parse operator's `StepMetrics` carried no `Spend`, and D733 writes a row only for a measured one, so a real `ow add` wrote no `route_spend` row and `ow cost --verify` (D853) failed every run. The operator now hands on the unit's `DriverResult.metrics` as the attempt's `Spend`; negatives are clamped, and a unit absent from the report is a measured zero. The first-party drivers report no physical metrics, so every parse bill is a zero today, and a book pricing wall or CPU time would price nothing. A failed parse attempt still writes no row.)*

```sql
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
    outcome TEXT NOT NULL,                     -- the `Outcome` wire value ([08](08-runtime.md) §1.3)
    PRIMARY KEY (decision_id, attempt)
);
```

Four consequences worth stating, because each is a query somebody writes.

- **An `op.*` step has no row here at all.** `route_spend.decision_id` is `NOT NULL`, and the `work`
  table's pairing CHECKs make an `op.*` row's `decision_id` NULL, so a core-only step *cannot* have a
  spend row. Its cost is `work.cost_micros`, which is why summing `work.cost_micros` is not the bill:
  it would double-count every routed row ([15](15-observability.md) §5.1).
- **`gpu_ms` here is not always measured.** A Service-backed driver cannot see the server's GPU time,
  so the runner apportions `service_observation.gpu_ms` across that Service's requests by `wall_ms`,
  with the integer-division residue assigned to the largest request ([15](15-observability.md) §5.3).
  A corpus total is exact; a per-document figure inside a coalesced batch is an estimate, and
  `ow cost` prints it with a tilde.
- **The `tokens_out` ratchet counter reads this column**, which is the gate that moves when a prompt
  or a driver version changes output length ([12](12-performance.md) §2.4).
- **One decision, several rows.** `[budget.per_part] calls = 3` is spent across attempts on one
  decision; escalation adds *decisions*, not attempts. So the per-document view is one row per
  attempt per rung, and every consumer aggregates. D733 writes the row: `run.spend_rows` is `SqliteStore.complete()`'s `spend_row` participant, empty since P2, and `ow ingest` wires it. A completion writes one when its work row names a decision and its `StepMetrics` carry a Spend. `None` writes none, because nothing measured is not a zero bill. The attempt is the decision's next. A hit is `was_cache_hit = 1` with the Spend it replays. `micros` is the runner's, 0 until a `PriceBook` prices it. The billed derive rows and the band's row carry their Spend. A parse row does not yet, so the self-check that every priced row has a spend row stays unwired.

## 6.5 Graceful degradation when a budget dies mid-document

`on_exhausted = ["spill_to_free", "partial", "defer"]` is tried in order, per `(part, lane)`, and the
first that applies wins. This is what turns "the money ran out on page 63 of 188" from a truncated
corpus into a disclosed one.

| step | what it does | what the part ends up as |
|---|---|---|
| `spill_to_free` | re-evaluate at `DEGRADE` with `max_cost_class = "free"`. In the shipped policy that is `degrade.budget-exhausted` → `parse.pdf.pdfium`. | `ok_partial`, `degraded = 1`, `page.method` records the branch — **when the free driver produces blocks.** A free attempt returning zero blocks is `FAILED_PERMANENT{EMPTY_RESULT}` before anything is cached ([runtime](08-runtime.md) §1.3, which owns the no-empty-success rule; §1.6 carries only the `empty_result` `FailureClass` row), and `on_exhausted` advances to its next member; §10.3's part 6 is exactly that path. |
| `partial` | settle the part with whatever it achieved; no further attempt | `ok_partial` with a `Degradation(kind="budget")` |
| `defer` | leave the work row claimable with `retry_after = NULL` | `deferred`; nothing is written |

Three properties that make this honest rather than merely tidy:

1. **Nothing is silently dropped.** Unlimited-OCR writes an empty text field for a part that failed
   five retries (`infer.py:229`); that is a hole indistinguishable from a blank page. Here the part
   carries `degraded = 1`, `doc.status = 'partial'`, and `ow_query` reports `verdict = degraded` for
   any answer that reads it.
2. **The message names the knob that would actually raise *this* limit.** Under §10.3's site-layer
   override (`micros_per_part = 800`), for a 6-part unit the
   binding number is `micros_base + micros_per_part × 6 = 8_800`, nowhere near `micros_max`, so the
   message names `micros_per_part`:
   `"[budget.per_unit].micros_per_part gives 8800 for 6 parts; exhausted at 6270/8800 after part 5/6;
   raise micros_per_part, pass --allow-cost, or set on_exhausted=['defer'] in
   .omniweave/policy.d/00-builtin-route.toml"`. Naming `micros_max` there would name a knob whose
   change does nothing.
3. **Degradation is a set, not a flag.** `route_decision.degradations` is a JSON array of
   `Degradation` records; a part can be budget-degraded *and* signal-degraded, and both survive into
   the run manifest and the serve envelope.

## 6.6 The cost of routing itself

| item | cost | note |
|---|---|---|
| `evaluate()` over the shipped policy | ~50 µs (declared budget; `ow bench route` measures) | pure atom walking over 40 rules; memoised on the compiled policy |
| FREE signals, clean born-digital part | ~2 ms | the charter's reference-ingest number; five signals (§4.3 property 1) |
| `route_decision` + `route_evidence` + `route_spend` write | ~0.12 ms | inside the unit's one transaction |
| `admit()` reservation | ~0.15 ms | one `INSERT`, one headroom `SELECT` |
| routing ledger storage | ~1 GB per million parts | ~240 B decision + ~600 B deduplicated evidence + ~120 B spend, falling to ~360 MB after the 30-day evidence sweep (charter §D4) |
| a routing microservice | **rejected** | ~50 µs of atom walking and a few ms of CPU signals do not need a network hop, a second deploy artefact, or a second failure domain |

---

# Part 7 — Determinism and replay

## 7.1 A decision's identity is its inputs

Three tables carry it, and they are printed here rather than globbed as `route_*` because
`block.decision_id` is a foreign key into the first of them ([03](03-document-model.md) §13.1) and a
foreign key needs a declared target. `0004_runtime.sql` creates every `route_*` table
([07](07-store-and-retrieval.md) §3); `route_signal` is §5.4's, `route_spend` is §6.4's,
`route_threshold` and the `route_scoreboard` view are §8.2's.

```sql
CREATE TABLE route_decision (
    decision_id      TEXT PRIMARY KEY,         -- 'dec_' || sha256_canonical(identity)[:24]
    -- ── the eight identity columns, and nothing else in this block is one ──
    content_sha256   TEXT NOT NULL,            -- 64-char hex over the unit's NORMALISED load-
                                               --   bearing source bytes. `_sha256`, never
                                               --   `_digest`: `block.content_digest` is a 16-byte
                                               --   `ow128` BLOB and a BLOB never equals a TEXT.
    unit_part        TEXT NOT NULL DEFAULT '', -- '' folds NULL (NULLs are distinct in a UNIQUE)
    lane             TEXT NOT NULL,            -- a `LANES` member
    rung             INTEGER NOT NULL,         -- the `Rung` INTEGER value, not its name (Open 1)
    policy_digest    TEXT NOT NULL,
    pricebook_digest TEXT NOT NULL,
    hints_digest     TEXT NOT NULL,
    read_set_digest  TEXT NOT NULL,            -- over the READ SET ONLY: the (key, provider
                                               --   version, value) triples the winning path
                                               --   consulted, in read order (§7.1 below)
    -- ── what the winning rule said. Written from `RouteDecision` (§4.6). ──
    driver           TEXT NOT NULL,            -- '' == no driver ran; a GATE refusal writes ''
    cost_class       TEXT NOT NULL             -- FROZEN at decision time: the `cost_class` label on
        CHECK (cost_class IN ('free','local_compute','billed_api')),   -- `ow_spend_micros_total`
                                               --   and the `class` column of `ow cost --by driver`
                                               --   ([15](15-observability.md) §4.2, §5.4). Reading it
                                               --   from the live catalog re-labels history after a
                                               --   card upgrade.
    rule_id          TEXT NOT NULL,
    rule_origin      TEXT NOT NULL,            -- 'project:.omniweave/policy.d/route.toml:41'
    cause            TEXT,                     -- 'garble.score=0.71>=0.50', from `cause_from`.
                                               --   GENERATED, so "why it escalated" is a GROUP BY
    reason           TEXT,                     -- the rule's own `reason`. Nullable, but a `skip`
                                               --   rule must record {reason, key, threshold} (§4.2)
    slice_key        TEXT NOT NULL,            -- '/'-joined `[slice] by`, '~' per component (§4.3)
    flagged_blocks   TEXT,                     -- JSON array of block ids (REPAIR, ENRICH)
    sequence_id      TEXT,                     -- minted by the planner; one per bound run of parts
    parent_decision_id TEXT REFERENCES route_decision(decision_id) ON DELETE CASCADE,
    evidence_digest  TEXT NOT NULL REFERENCES route_evidence(evidence_digest),
    -- ── the estimate, written by `price()` BEFORE `admit()` runs ──
    est_spend        TEXT NOT NULL,            -- canonical JSON of `Spend`, all seven dimensions
    est_micros       INTEGER NOT NULL,
    reserved_micros  INTEGER NOT NULL,         -- the p95 CEILING, not the mean (§6.3)
    -- ── written after the row exists: `admit()`'s verdict and the sampler's ──
    admission        TEXT NOT NULL             -- `micros IS NULL` on the spend join means DEFERRED;
        CHECK (admission IN ('admitted','deferred','degraded')),   -- `micros = 0` means a free
                                               --   driver ran. [15](15-observability.md) §5.2
                                               --   selects this column so the two are separable.
    audit_selected   INTEGER NOT NULL DEFAULT 0,   -- DERIVED, never random: blake2b(unit_uri ||
                                               --   part || salt) % 10000 < rate x 10000 (RT2)
    pinned           INTEGER NOT NULL DEFAULT 0,   -- a `[[pin]]` won; excluded from the scoreboard
    grant_id         TEXT,                     -- non-null IFF est_spend.bytes_egress > 0 (§7.3)
    degraded         INTEGER NOT NULL DEFAULT 0,   -- rung = DEGRADE, or any `Degradation` recorded
    degradations     TEXT NOT NULL DEFAULT '[]',   -- JSON array of `Degradation`: a SET, not a flag
    generation       INTEGER NOT NULL,         -- the run's `generation`. AN INTEGER, NEVER A CLOCK.
    decided_at       INTEGER NOT NULL          -- wall ms, for humans and the 400-day sweep ONLY
);
-- INV-13 / RT8, and it CANNOT be a CHECK: "subqueries prohibited in CHECK constraints" (verified on
-- SQLite 3.45.1), so the DDL that tried was unrunnable and would have left the routing migration
-- unapplied with INV-13 unenforced. It is a generated trigger, with CI parity against the policy
-- compiler's rejection of a backward `escalate_to` (`OW-P-005`). Two enforcers, one truth.
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
-- The primary key IS the per-document index: a `GROUP BY unit_uri` over
-- [15](15-observability.md) §5.2's `spend_attribution` view is a prefix range scan of it, which is
-- why that view adds no index of its own. It is also the only table holding `unit_uri` on the
-- routing side — `route_decision` is keyed on CONTENT, so one blob in three folders is one decision
-- and three rows here.

CREATE TABLE route_evidence (             -- refcounted and content-addressed, so identical read
    evidence_digest TEXT PRIMARY KEY,     --   sets share one blob and it ages out on its own
    payload BLOB,                         -- deflate(canonical JSON of the read set). NULLABLE, and
                                          --   that is what reconciles the two retentions: blobs age
                                          --   out at 30 days and decision rows at 400, so the sweep
                                          --   NULLS the payload and stamps `swept_at` rather than
                                          --   deleting the row, which would break `route_decision`'s
                                          --   NOT NULL foreign key into it. A swept decision still
                                          --   names the read set it was taken over; it just cannot
                                          --   be replayed. Rows whose decisions are `audit_selected`,
                                          --   `pinned`, `degraded` or in a REGRESSED slice are never
                                          --   swept (§8.4).
    swept_at INTEGER,                     -- NULL while the payload is live. `ow route replay` prints
                                          --   the window it could actually cover.
    first_seen_at INTEGER NOT NULL, refcount INTEGER NOT NULL DEFAULT 1,
    CHECK ((payload IS NULL) = (swept_at IS NOT NULL))
);
```

`route_decision_identity` is eight columns, every one of them an *input*. Nothing about *when* the
decision was made is in the key;
`decided_at` exists for humans and retention only, and `generation` is an integer, never a clock. Three
consequences:

- **Identical bytes never re-bill.** The key is `content_sha256`, not `unit_uri`, so the same PDF in
  three folders is one decision and one parse.
- **A new signal provider does not invalidate decisions that never consulted it.** `read_set_digest`
  covers the **read set only** — the `(key, provider_version, value)` triples the winning path
  actually consulted, in read order. Installing `omniweave-vision` and gaining `layout.class_hist`
  leaves every born-digital page's decision valid, because those decisions never read it. The same
  property makes §5.2's per-format providers safe: a PDF decision's read set names the `pdfium`
  version, so an `officexml` release does not touch it.
- **The lane is in the key, so a part's `text` and `table` decisions are separate rows** that age out,
  replay and re-price independently.

What makes `read_set_digest` trustworthy is the accessor, printed in §4.6: `Evidence.read()` is the
only way to obtain a value and it appends to the read log, so the read set is an *observation* rather
than a declaration a programmer can forget to update. `evidence_digest` is `NOT NULL` for the same
reason — a decision whose evidence blob has been swept still names the blob it was taken over, and the
30-day sweep may not delete the evidence for a decision somebody is arguing about (§8.4).

## 7.2 Replay

```
ow route explain  <unit> [--part N] [--lane L]
     the winning ACTION rule, its file:line, every MODIFIER rule that also matched, the read set
     with resolved provider versions, the cause string, the estimate, the reservation, the
     admission, the dimension that bound, and every rule that was TESTED AND DID NOT MATCH with
     the clause that failed. This is `ow why` for one (part, lane).

ow route replay    [--since <gen>] [--slice <key>] [--policy <path>] [--pricebook <path>]
     re-runs evaluate() over stored route_evidence payloads. PURE, so it needs no source bytes, no
     driver and no network, and it costs $0 for the entire history. Prints a decision diff:
     unchanged / changed-rule / changed-driver / changed-rung / changed-lane-set, with the micros
     delta per slice.

ow route simulate  <policy> --corpus <name>
     replay plus the PriceBook, reporting the counterfactual bill. This is how a threshold change is
     reviewed before it is committed.

ow route audit     [--slice <key>]
     lists the deterministically-selected audit decisions and their route_quality rows.
```

Replay is byte-exact because `evaluate()` is pure: its signature takes no `RunContext`, semgrep bans
`time.`, `random.`, `os.environ`, `importlib` and `open(` in `route/eval.py`, and a property test
evaluates 10,000 fixtures twice in shuffled order and asserts identity (RT1). All sampling is
`blake2b(unit_uri || part || salt) % 10000 < rate × 10000` — a pure function of the unit and the
policy's salt, so `audit_selected` is **derived, never random**, and a cross-process determinism test
asserts two processes select the same set (RT2). The lane loop iterates `sorted(lanes)` for the same
reason: a set iteration order is not a specification.

What replay does **not** promise: that re-running the *driver* reproduces the same bytes. That is the
card's `replay_class` (`byte_exact | seeded | unpinnable`) and a different axis. A `PAGE` decision
replays identically; the olmocr call it authorises does not, unless a Cassette is in play.

## 7.3 Overrides — seven, each named for its hazard

There is no `--force` anywhere in the framework, because an override whose scope is "skip whatever
complained" is an off switch.

| override | who may set it | what it changes | recorded as |
|---|---|---|---|
| `[[pin]]` in `policy.d` | ops | one `(unit, part?, lane) -> driver`, with a mandatory `reason` and `expires` | `route_decision.pinned = 1`; the row is excluded from `route_scoreboard` |
| `--max-rung <RUNG>` | anyone | a ceiling on escalation for this invocation | `hints_digest`; a part that would have escalated past it records `Degradation(kind="rung_ceiling")` |
| `--allow-cost <micros>` | **CLI only** | raises the per-unit micros cap for this invocation | `hints_digest` plus the run manifest. Not available over MCP or the SDK, because `RouteHints` has no budget field |
| `--allow-egress <grant-id>` | the site layer must have issued the `Grant` | permits `bytes_egress > 0` | `route_decision.grant_id`, non-null **iff** `bytes_egress > 0`; the `dpa_ref` is printed in the run manifest of every document that egressed |
| `--accept-partial` | anyone | a unit above `ingest.max_parts`, or one `gate.corrupt` refused, proceeds — parts beyond the cap unrouted | `Degradation(kind="budget")` naming the cap, or `kind="signal_unavailable"` naming `unit.corrupt` |
| `--ignore-evidence-cache` | anyone | re-computes `route_signal` rows | `run.argv`; can only ever spend `free`/`local_compute` |
| `--allow-rebill` | anyone | permits a `billed_api` re-run despite a `call`-layer cache hit | prints the hit count and the `would_have_been_micros` it is about to discard |

A pin is **honoured or refused, never silently ignored**: `PinRejected{driver, reason}` is a typed
return, not an `Optional`. A pin whose target driver is not in `[drivers] enabled` fails
`ow route lint` check 6 at load, so the refusal happens before a run rather than during one.

---

# Part 8 — The quality feedback loop

## 8.1 Four verdict sources, one of which never scores

| `route_quality.source` | where it comes from | cost | enters `route_scoreboard`? |
|---|---|---|---|
| `self` | the driver's own confidence | 0 | **never.** Stored, and excluded by the view's own `WHERE` (RT12) |
| `agree` | `agree.decode_vs_page` on every escalated part | 0 | yes, as `escalation_divergence` |
| `audit` | a deterministically sampled reference run at `[audit] reference` | `rate × corpus` | yes, as `divergence` |
| `feedback` | a human or an agent marking an answer wrong, carrying a `cite` | 0 | yes, as `complaints` |

`self` is excluded because a driver grading its own work is the one measurement guaranteed to be
correlated with its errors. It is stored anyway, because the *gap* between `self` and `audit` is itself
a diagnostic: a driver whose self-confidence is high exactly where `audit` divergence is high is
miscalibrated, and that is a card bug worth filing.

`audit` sampling is `blake2b(unit_uri || part || salt) % 10000 < rate × 10000` with `rate = 0.005`,
and the sampler substitutes `untrusted_external_rate = 0.05` when `unit.trust_class` is
`untrusted_external`. That substitution happens **in the sampler**, reading the evidence key directly
— there is no rule for it, because a rule that only sets `reason` does nothing (§4.2) and a rule that
matched at `GATE` would pre-empt the lane admissions. The reference driver is named in the policy, so
an audit is a *second, more expensive reading* of a sampled part and its cost is a line in the budget
rather than a surprise.

```sql
CREATE TABLE route_quality (              -- NOT `route_verdict`: `Verdict` is the RETRIEVAL honesty
    quality_id INTEGER PRIMARY KEY,       --   record ([07](07-store-and-retrieval.md) §6) and one
                                          --   name may not carry two types
    decision_id TEXT NOT NULL REFERENCES route_decision(decision_id) ON DELETE CASCADE,
    source TEXT NOT NULL CHECK (source IN ('self','agree','audit','feedback')),
    metric TEXT NOT NULL,                 -- 'norm_edit_agreement' | 'grounded_frac' | 'thumb'
    agreement REAL,                       -- [0.0, 1.0]; the scoreboard reports 1.0 - agreement
    polarity INTEGER,                     -- `feedback` only: -1 wrong, +1 right
    ref_driver TEXT,                      -- `audit` only: the `[audit] reference` driver that ran
    detail TEXT, created_at INTEGER NOT NULL
);
CREATE INDEX route_quality_decision ON route_quality(decision_id);
```

`source = 'self'` rows are **written and never scored**: the exclusion is the scoreboard's, not the
writer's, so the `self`-versus-`audit` gap stays queryable as a card diagnostic (RT12).

## 8.2 The scoreboard's zero value is UNKNOWN

`route_scoreboard` rolls up per `(slice_key, rule_id, driver)` with a three-valued `state`:

```
audited_n < route_threshold['audit.min_audit_n']   ->  'UNKNOWN'
divergence > route_threshold['audit.regress_at']   ->  'REGRESSED'
otherwise                                          ->  'OK'
```

The thresholds are **rows**, not bind parameters, because a SQLite view may not contain a bind
parameter (verified on 3.45.1). The policy loader writes all three `route_threshold` rows in the same
transaction that installs `policy_digest`, or refuses to install; `ow doctor` fails on an empty table.
That is what keeps the view byte-diff gateable while its `state` column still moves when the policy
does. **A missing threshold row makes the comparison NULL, which falls through to `'OK'`** — hence the
loader's all-or-refuse rule.

On day one an operator sees a wall of `UNKNOWN` across every slice, which is the truth: at
`rate = 0.005` and `min_audit_n = 30`, a slice needs `30 / 0.005 = 6,000` decisions before it says
anything. `escalation_divergence` populates far sooner, because `agree` fires on every escalated part.

```sql
CREATE TABLE route_threshold (k TEXT PRIMARY KEY, v REAL NOT NULL);
-- Exactly three rows, written by the policy loader from the compiled policy's `[audit]` block in
-- the SAME transaction that installs `policy_digest`, or the install refuses:
--   'audit.min_audit_n'  30      'audit.regress_at'  0.08      'audit.release_at'  0.048
-- `ow doctor` check D-12 ([15](15-observability.md) §9.2) fails on a missing row, because a missing
-- row makes the comparison below NULL and NULL falls through to 'OK' — a silent all-clear.

CREATE VIEW route_scoreboard AS
WITH q AS (        -- ONE ROW PER DECISION. Pre-aggregated, because `route_quality` and
                   -- `route_spend` are BOTH one-to-many on `decision_id`, and joining both to
                   -- `route_decision` in one FROM multiplies every row by the other's cardinality.
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
```

Four properties of that text are load-bearing, and three of them are places a "simplification" would
put a wrong number in front of an operator.

1. **The two children are pre-aggregated, and they must be.** `route_quality` holds up to four rows
   per decision and `route_spend` one per attempt; joining both directly to `route_decision` yields
   their Cartesian product, so an escalated, audited, retried part would multiply its own `micros`
   by its quality-row count and its `audited_n` by its attempt count. The `WITH` clauses reduce each
   child to one row per decision first, which is why every outer aggregate is a plain `SUM`.
2. **`self` is filtered inside `q`, not in the outer `WHERE`.** A predicate on `v.source` in the
   outer `WHERE` turns the `LEFT JOIN` back into an inner join for every decision whose only quality
   row is `self` — and those decisions would vanish from `decisions_n` and from `micros` entirely,
   which is a scoreboard that under-reports both its population and its bill.
3. **Every count is `COALESCE`d to 0 before it is compared.** `SUM()` over an all-NULL left join is
   NULL, `NULL < 30` is NULL, and a NULL `CASE` arm falls through to `'OK'`. Without the coalesce a
   slice with *no* audit evidence at all would report `'OK'` — the exact failure D-12 guards against
   from the other side.
4. **The view contains no bind parameter.** "Parameters are not allowed in views" (verified on SQLite
   3.45.1), so the thresholds are rows and the text is fixed. That is what keeps it byte-diff
   gateable while `state` still moves when the policy does.

**This supersedes the charter's printed view.** The charter's §"Routing DDL" prints the direct
two-`LEFT JOIN` form; it is the same view with defects 1, 2 and 3 above, and the plan's live form is
the one printed here. The charter's §9 errata row `E21` records that correction, and names this
view the deviation that returns wrong numbers rather than merely fewer columns.

## 8.3 What the loop actually does — and what is v2

**Ships at release 1.** The `agree` writer, the `audit` sampler and its reference runs, the `feedback`
ingest path, `route_scoreboard`, `route_threshold`, `ow route scoreboard`, and exactly one automatic
write:

> **`auto_demote`.** A slice whose `state = 'REGRESSED'` for two consecutive scoreboard evaluations is
> automatically moved to the **more expensive** driver, with `demote_ttl_days = 30` and hysteresis
> (`release_at = regress_at × 0.6 = 0.048`). The demotion writer accepts only a `then.driver` of
> strictly greater cost rank; a test attempts a promotion and asserts refusal (RT13). The write is a
> `[[rule]]` block in a generated `.omniweave/policy.d/90-auto-demote.toml` carrying an `expires`
> field, so it is visible in a `git diff`, expires on its own, and is reverted by deleting a file. The
> writer holds the store's write transaction for the duration, writes through
> `atomic_write(tmp.<pid> + rename)`, and **refuses if the file is tracked and dirty** — an automatic
> write must never clobber a human's uncommitted edit to the same file.

Demotion and not promotion, because the two directions have asymmetric consequences: demoting costs
money and produces better output, while promoting saves money and may produce silently worse output —
and the evidence that would justify it is exactly the expensive measurement you were trying to avoid.

**Ships at release 1, human in the loop.** `ow route propose` fits one `[thresholds]` entry per slice
by **one-dimensional isotonic regression** over the decision log — possible only because
`@thresholds.<name>` is a compile-time substitution rather than an expression — and emits a **TOML diff
a human commits**. The objective, stated so it can be checked: for threshold `t` on signal `s` within
one slice, the label is `1 - agree.decode_vs_page` on the decisions that escalated (plus `audit`
divergence where present), and the fit maximises `Σ divergence_avoided(t) - Σ micros(t)` — both terms
already in the same unit, because the `PriceBook` converted one of them — with monotonicity in `t`
making the fit isotonic rather than a grid search. The report prints
`(n, ci95, method, slice_key, corpus_digest, MeasuredOn, witness)` for every number, per INV-19; a
slice at `UNKNOWN` yields **no proposal at all** rather than a proposal with no evidence.
`ow route promote` applies a reviewed diff. Neither writes without a commit.

**v2, explicitly.** Multi-dimensional threshold fitting — two thresholds moving together — and
per-slice *rule ordering* proposals. Both need the joint distribution that one-dimensional isotonic
regression avoids needing, and neither has a corpus large enough to fit it at release 1.

**Permanently rejected.** A learned end-to-end router. There are no labels on day one, and the label
you need — *which driver would have been right* — is the expensive thing you were avoiding computing.
It cannot be linted, diffed, or explained to a customer whose bill doubled on Tuesday, and it destroys
replay.

## 8.4 Storage and retention

Evidence blobs age out at 30 days; decision rows at 400 days, which is what makes a year-over-year
comparison possible. The two retentions meet at one column: `route_decision.evidence_digest` is
`NOT NULL`, so the sweep **nulls `route_evidence.payload` and stamps `swept_at`** rather than deleting
the row (§7.1). A swept decision still names the read set it was taken over and still prices, sums
and slices; it is only `ow route replay` that cannot re-run it, and that command prints the window it
actually covered. Rows that are `audit_selected`, `pinned`, `degraded`, or in a `REGRESSED` slice
are **never** aged out — the sweep may not delete the evidence for a decision somebody is arguing
about. `route_evidence` is refcounted and content-addressed, so identical read sets share one blob;
`route_unit_decision` survives a `work` row's deletion, so cost provenance outlives the queue.

---

# Part 9 — Failure handling

Every row is detected at a named point, produces a named `FailureClass` from the charter's thirteen-member
enum, and ends in a named state. Nothing here is an exception that escapes to a caller.

| input | detected at | `FailureClass` | outcome | the message names |
|---|---|---|---|---|
| **0-byte file** | detection step 0 → `unit.format = 'empty'` → `gate.empty` | `corrupt_input` | `unit.state='failed'`; no `doc` row | the path and `[ingest] exclude` |
| **2 GB file, size known** | the **pre-fetch** guard in the enumerate loop | `too_large` | `failed`; **the bytes are never read** | `[ingest] max_unit_bytes` |
| **2 GB file, `size = None`** | the bounded read in `fetch()` (`max+1`) | `too_large` | `failed`; at most `max+1` bytes are read and no blob is committed | `[ingest] max_unit_bytes` |
| **encrypted PDF, no password** | detection → `unit.encrypted` (a trailer `/Encrypt` reference) → `gate.encrypted` | `encrypted` | `failed`, permanent | how to store the password on this OS, and the `password_file` line ([ADR-15](adr/0015-encrypted-pdfs-and-document-passwords.md) D15.5) |
| **encrypted PDF the scan missed** | `DECODE`, pdfium `FPDF_LoadDocument` → `FPDF_ERR_PASSWORD` | `encrypted` | `failed`, permanent | as above |
| **encrypted PDF, password supplied** | acquire, via `[ingest] password_file` → `OW_SECRET_<NAME>` or the OS keystore (ADR-15 D15.3); an unchanged file is re-read once a line maps it | — | routed normally; `Diag(OW_DOC_DECRYPTED)`, `doc.x.ow.decrypted = true`, `unit.encrypted` recomputed `false` | — |
| **password-protected OOXML** | detection, from the OLE root storage containing `EncryptedPackage`; `unit.encrypted = true`, `format` stays `unknown` | `encrypted` | `failed`, permanent. The inner format is unknowable and guessing it produces a wrong `failure_class` | that the container is CFB-encrypted and the inner format is unknowable |
| **corrupt PDF** (no locatable xref, truncated) | detection → `unit.corrupt` → `gate.corrupt` | `corrupt_input` | `failed`, permanent; `--accept-partial` overrides and lets pdfium try its reconstruction | the structural check that failed, and `--accept-partial` |
| **partially corrupt PDF** (pages 1-40 fine, 41 unreadable) | per part, at `DECODE` | — | page 41 → `page.status='failed'`; `doc.status='partial'`; every other page normal | which pages failed, as a range: `"pages 41, 44-46 of 188"` |
| **10,000-page PDF** | GATE, from `unit.part_count` (NOT NULL: `op.identify` precedes routing) | `resource_limit` | `failed`, or routed under `--accept-partial` with a `Degradation` naming the cap | `[ingest] max_parts`: the count, the cap it was read under, and the value that admits it; the unchanged file is re-read once the cap covers it (D644) |
| **4,000-page PDF** (below the cap) | — | — | routed part by part, 512 part rows and decisions per transaction; the water mark bounds expansion; **no barrier**, so it never stalls a corpus | — |
| **extension lies** (`.pdf` that is a DOCX) | detection, ambiguity case 4 | — | routed by the magic bytes; `Diag(OW_FORMAT_EXTENSION_MISMATCH)` on the doc | both the claimed and the detected format |
| **a format guessed only from its extension** | detection, ambiguity case 3 → `gate.weak-format-basis-denies-extraction` | — | routed in the `text` lane; the `fields` and `table` lanes denied | `unit.format_basis` and the two denied lanes |
| **a SQLite database named `.txt`** | detection row 17 → `gate.unsupported-source` | `unsupported_format` | `failed` — a database is a source, not a document | the connector that would read it |
| **an `.mp4`** | detection row 14 → `gate.unsupported-media` | `unsupported_format` | `failed`, permanent | `pip install omniweave-media` |
| **a format token with no DECODE rule** | `decode.no-rule-matched`; unreachable in CI by lint check 10 | `unsupported_format` | `failed`, permanent | the token and that no rule names it |
| **a hostile `sniff()`** (a driver claiming 1.0 on every stream) | the detection ladder's clamp | — | the guess is capped at 0.95 and loses to any magic or container identity; a raise or a 5 ms overrun drops it entirely | the driver id and `Degradation(kind="signal_unavailable")` |
| **an XML bomb in `[Content_Types].xml`** | the host's container-identity read | `resource_limit` | `failed`; refused on the `<!DOCTYPE`/`<!ENTITY` test before any parse | `MAX_IDENTITY_BYTES` |
| **zip bomb** | the container walk, bounded read | `resource_limit` | `failed`, fatal, **never swallowed** by the per-member `except` | `MAX_ENTRY_BYTES` / `MAX_CONTAINER_TOTAL_BYTES` |
| **zip nested 4 deep** | the container walk depth counter | `resource_limit` | `failed` | `MAX_CONTAINER_DEPTH` |
| **zip-slip member path** | the container walk path sanitiser | — | that member is skipped and **counted** in `ingest_scope.skipped_why`; the rest proceed | the count of skipped members |
| **10,000 members inside each of 10,000 containers** | `producer_should_pause()` | — | discovery pauses at `queue_high_water`; nothing is dropped | the water-mark keys |
| **two processes expanding one mbox** | the `acquiring` transition (§1.3 rule 6) | — | one expands, the other skips; no doubled `bytes_read` | the lease holder |
| **XML bomb inside a DOCX body** | inside `parse.office.anydoc` | `resource_limit` | `failed` | `MAX_XML_DEPTH` / `MAX_XML_NODES` |
| **a spreadsheet with a 4M-cell repeat expansion** | inside the driver | `resource_limit` | `failed` | `MAX_GRID_SLOTS` / `MAX_EXPANSION_TEXT_BYTES` |
| **a driver crash** (SIGSEGV in a native decoder) | the `subproc` host | `driver_crashed` | one unit fails; `adapt_batch` drops the batch to 1 for the retry to localise the poison unit; 3 crashes in 60 s quarantines the driver | the quarantine and `ow drivers explain` |
| **a driver that never returns** | `progress_ms` (15 s with no `progress()` call), then `wall_ms_hard` | `timeout` | SIGTERM, SIGKILL at +5 s, the whole **process group** reaped; both recorded | which deadline fired |
| **`omniweave-vision` not installed** | the pre-evaluation resolution probe (§4.3) | — | `driver.unavailable` → `degrade.driver-unavailable` → `parse.pdf.pdfium`, `ok_partial`, `degraded` | `pip install omniweave-vision` |
| **a driver whose weights are `restricted` tier** | `admit()` step 2, against `[licence] allow_tiers` | — | the same path; this is `fields.extract`'s release-1 state | the tier, the licence sha and `[licence] allow_tiers` |
| **a rate-limited connector** | acquire | `rate_limited` | `unit.acq_retry_after` set from `Retry-After`; the **parse** retry budget is untouched | when it will retry |
| **a URL resolving to a private IP, or to port 6379** | the connection class's single resolution, before connect | `auth` | refused; no socket is opened. `auth` and not `unsupported_format`: the fetch was not authorised | the resolved address, `[ingest.url] allow_hosts` and `allow_ports` |
| **an unsupported but known format** (`.ps`, `.dwg`) | detection | `unsupported_format` | `failed`, permanent | the driver that would handle it, if one exists out of tree |
| **`ok` with zero blocks** | the host, after the driver returns | `empty_result` | `FAILED_PERMANENT` **before anything is cached** — a driver may never return an empty success | that the driver returned an empty result |

Three cross-cutting rules this table depends on:

1. **Status, not exception, for a per-document outcome.** `doc.status` is one of
   `ok | partial | failed | skipped`, with `page.status` per page. A failure is a row, not a stack
   trace, and a 100k-document ingest does not stop because document 40,000 is a corrupt fax. docling
   reaches the same shape by commenting out its `raise` lines
   (`docling/datamodel/document.py:137-207`); here it is the contract.
2. **The recoverable/fatal split is policy, not judgement.** Producer quirks are recovered and
   *logged*; only real impossibilities are `DriverError`s. `RESOURCE_LIMIT` is the one class no
   recovery helper may swallow.
3. **`NEEDS_OCR` is routing data, not a failure.** `DriverError(cls=NEEDS_OCR, pages=(4,7,8,9))`
   carries the page list, feeds `unit.needs_ocr_parts`, and escalates exactly those parts. anydoc's
   two-stage design is the precedent: a cheap content-stream scan **over-reports by design**
   (`anydoc/src/formats/pdf.rs`), and a second pass that actually attempts extraction on just the
   flagged pages confirms. Cheap detector proposes, expensive confirmer disposes, and only the flagged
   subset pays for the confirmation.

---

# Part 10 — Three documents through the router

Priced with the §6.2 pricebook: `gpu_ms_micros = 0.3556`, `cpu_ms_micros = 0.00928`,
`wall_ms_micros = 0.0`. `parse.page.olmocr` declares `per_part = {gpu_ms 2400, cpu_ms 120,
tokens_out 1100, calls 1}`, `service = "model:olmocr"` (so no `per_session` term) and
`tokens_out_p95_multiple = 3.2`, giving

```
est_micros      = 2400 x 0.3556 + 120 x 0.00928 = 853.44 + 1.11  =  854
reserved_micros = 2400 x 3.2 x 0.3556 + 1.11    = 2730.8 + 1.11  = 2732      (p95 on gpu_ms)
```

## 10.1 A 188-page 10-K, born digital, with 12 scanned exhibits

The document docling cannot route: `do_ocr` is a document boolean, so a 188-page filing with 12
scanned exhibits either pays VLM prices for 188 pages or returns garbage for 12.

```
GATE     unit.format=pdf  format_basis=magic  bytes=14.2MB  encrypted=false  corrupt=false
         part_count=188  producer_family='workiva'  trigger.kind='cli'  trust_class='internal'
         No GATE action rule matches; no modifier fires either, so max_cost_class stays
         'billed_api' and lanes = {text}.
         signals computed: 10 FREE.  rasters: 0.  services attached: 0.
         per_unit micros limit = clamp(4000 + 3000x188, 0, 16000000) = 568,000

parts 1-42, 55-176  (164 parts: clean body text)
  DECODE select   FREE group: decode.char_count=3180 > 0 -> decode.pdf-text-layer
                  * decode.blank-part-escape reads ink.tiles (LOCAL, UNKNOWN) with
                    on_unknown='defer', but it is LATER in file order than the rule that matched,
                    so plan.deferrals_pending is false, the LOCAL group is never computed and no
                    raster is rendered. THAT ORDERING IS WHAT MAKES INV-13 TRUE.
                  -> driver=parse.pdf.pdfium, lane 'text'
  DECODE settle   garble.score=0.02  geometry.overlap_line_frac=0.06  decode.cid_ratio=0.00
                  ink.coverage NOT COMPUTED: decode.part-text-unusable is an any_of and three FREE
                  clauses already resolved it to false, so no earlier rule defers and the LOCAL
                  group is skipped.
                  action  -> decode.skip-block-recheck-on-clean-parts (0.02 < 0.05) -> REPAIR skipped
                  modifiers -> decode.admit-table-lane: block.type UNKNOWN on PDF and
                    geometry.ruled_regions=0 -> on_unknown='skip', no admission.
                    decode.admit-math-lane: math.font_hit=false, math.part_frac=0.001 -> no.
                  outcome  ok, rung reached 1.  5 FREE signals + 8 ms decode = ~13 ms.  0 micros.

parts 43-54  (12 scanned exhibits)
  DECODE select   FREE group: decode.char_count=0.  decode.pdf-text-layer false.
                  decode.blank-part-escape's ink.tiles is UNKNOWN, it declares defer, and it is
                  EARLIER than decode.no-text-layer -> the LOCAL group runs: one 96-DPI grayscale
                  render, 15 ms.  ink.tiles=9,240 of 13,464 > 4, so the escape does not fire.
                  15 ms of CPU to avoid a 2,400 ms GPU call is a 160x trade.
                  -> decode.no-text-layer -> escalate_to=PAGE  driver=parse.page.olmocr
                     render='glyph'  cause='no-text-layer'
  admit           est 854, reserved 2,732.  12 x 2,732 = 32,784 against 568,000 -> all Admitted.
                  Per part: reserved 2,732 < [budget.per_part] micros 6,000; reserved gpu_ms
                  7,680 < 12,000; calls 1 of 3.
  PAGE settle     verify.finish_reason='stop'  repeat_ngram_max=3  token_saturation=0.14
                  parse_ok=true  nonempty=true -> page.output-invalid does not match
                  agree.decode_vs_page NOT COMPUTED: it requires DECODE, and DECODE produced nothing
  outcome         ok at rung 3.  actual gpu_ms 2,410 -> 858 micros/part.  On commit, 2,732-858 =
                  1,874 micros released per part.
  * part 47 only  verify.repeat_ngram_max=18 >= 12 -> page.output-invalid -> REGEN at temperature
                  0.2, SERIAL behind a semaphore of 1.  attempt 2: repeat_ngram_max=4,
                  finish_reason='stop' -> ok at rung 4.  part 47 costs 1,716 micros and 2 of its 3
                  calls.  A third attempt would still be permitted ([budget.per_part] micros has
                  6,000-1,716 = 4,284 of headroom against a 2,732 reservation); a FOURTH is refused
                  by the `calls = 3` dimension, and on this pricebook `calls` is what binds (6.3).
  doc.rung_run_length reaches 8 at part 50 -> page.stable-run-becomes-a-sequence binds parts 50-54
                  into one sequence_id.  Because the card declares service='model:olmocr', the
                  per_session term is 0 and the saving is WALL TIME, not micros: the 31 s model load
                  is paid once per run by the service, and the sequence saves 4 x 31 s = 124 s
                  against [budget.per_unit] wall_ms = 600,000.

part 177  (a full-page photograph with a caption — THE KNOWN FALSE POSITIVE)
  DECODE select   char_count=84 > 0 -> parse.pdf.pdfium
  DECODE settle   garble.score=0.03 -> does NOT clear 0.05, so REPAIR is not skipped.
                  decode.part-text-unusable is FIRST in file order, three of its FREE clauses are
                  false and ink.coverage is LOCAL and UNKNOWN, so the any_of is UNKNOWN and it
                  DEFERS: the planner promotes the LOCAL group (16 ms) -> ink.coverage=0.11 < 0.25
                  -> the clause is TRUE on real evidence and on_unknown is never consulted at all.
                  -> escalate_to=PAGE  cause='ink.coverage=0.11<0.25'
  outcome         ok at rung 3.  858 micros spent to re-read an 84-character caption.
                  agree.decode_vs_page = 0.94 — HIGH agreement on an escalated part, which is
                  exactly the evidence `ow route propose` reads to raise ink_coverage_min for the
                  slice `pdf/workiva/true/en`.

parts 178-188  clean, as the body.
DOCUMENT TOTAL  escalated_part_frac = 13/188 = 0.069 -> page.collapse-to-sequence never fires
                signals: 188 x ~5 FREE, plus 13 LOCAL renders.  services attached: 1.
                decisions: 202 rows (188 DECODE + 13 PAGE + 1 REGEN) at ~240 B = 48 KB.
                GPU: 14 x 2.41 s = 33.7 s.  spend: 14 x 858 = 12,012 micros = $0.0120.
                Under a document boolean the same file is 188 x 858 = 161,304 micros = $0.161 —
                13.4x the metered cost, and PAYABLE under the shipped 568,000 cap, so the 13.4x is
                the whole argument.  The pre-S10 default (micros_per_part = 800, micros_max =
                250,000) put 161,304 above a 154,400 limit and would have degraded the last few
                pages: that was a budget defect, not an argument (4.4, lint check 13).
```

## 10.2 A 40-page DOCX with tracked changes, comments and OMML math

```
GATE     unit.format='docx'  basis='container_identity'
         detail='OPC rel officeDocument -> /word/document.xml; root w:document'
         extension_mismatch=false (the file is named .docx).
         unit.encrypted=false — DETECTION established it from the absence of an OCF
         encryption-data element and of a CFB EncryptedPackage, so gate.encrypted needs no
         on_unknown and is not silently off on this format.  unit.corrupt=false: the ZIP central
         directory closes.  10 FREE signals.  0 rasters.  lanes = {text}.
op.identify -> part_count = 1  (granularity='document' on the card, so unit_part = '')

DECODE select
         decode.office-native matches on unit.format in [doc, docx, ppt, pptx, xls, xlsx, odt,
         ods, odp, rtf, epub, csv] -> driver=parse.office.anydoc  terminal=true
         * lint check 11 asserts that list is exactly anydoc's declared [capability] formats, so
           this rule cannot name a format the driver refuses — which is what routing `html` or
           `md` here would have done.
         * TERMINAL STOPS EVALUATION at this rung. marker subclasses PdfProvider for DOCX and
           renders to a temp A4 PDF, destroying speaker notes, comments, tracked changes, OMML
           math, numbering restarts, footnote linkage and true logical order BEFORE parsing
           starts. Stopping evaluation — rather than only forbidding escalation — is what makes
           decode.part-text-unusable's on_unknown='match' unreachable here instead of a
           contradiction the linter would have to refuse.
         staged_gen = doc.gen + 1  (granularity='document': the torn-parse fix)

DECODE settle (modifiers only — terminal stopped the ACTION search, not the modifier scan for
         this rung, because a lane admission is not an escalation)
         decode.admit-math-lane: math.part_frac resolves through the `officexml` provider (5.2) —
         9 m:oMath elements over 118 paragraphs = 0.076.  Below @thresholds.math_part_frac 0.30,
         but math.font_hit is true (an OMML element is a font-independent hit on this provider)
         -> lane 'math' ADMITTED.  This is what the per-format provider mechanism buys: under a
         pdfium-only registration both keys would be UNKNOWN and the math lane would never engage
         on a DOCX even though OMML is explicit in word/document.xml.
         decode.admit-table-lane: block.type='table' on 3 blocks -> lane 'table' ADMITTED.
         decode.admit-caption-lane: 2 picture blocks with no adjacent caption -> ADMITTED.
         lanes = {text, math, table, caption}; each begins its own loop at REPAIR (DECODE+1).

lane math      REPAIR: math.flag-for-enrich -> escalate_to=ENRICH, flag_blocks (9 formula blocks).
               ENRICH has no rule here; 06 owns the pass. The flags are in flagged_blocks.
lane table     REPAIR: table.grid-unresolved reads table.grid_score, which the `officexml`
               provider computes exactly from w:tbl gridSpan/vMerge — 1.00 on all three tables,
               above 0.75 -> no match, no crop OCR, no cost.
lane caption   REPAIR: caption.flag-for-enrich -> ENRICH, flag_blocks (2 picture blocks).

outcome  text lane: ok at rung 1.  4.4 ms median decode (anydoc/README.md benchmark).  0 GPU-ms.
         0 micros for the whole document; four lanes, four decision rows, ~960 B.
         Blocks: 612, including 47 comment blocks at layer='annotation' and 12 tracked-change
         blocks; math emits 9 `formula` blocks with `math=[]`, because anydoc declares math = [].
DISCLOSED  doc.achieved.origin_span = 'none', so every block is quote='normalized' and `verbatim`
           is unreachable on the office path at release 1 (charter §D3, verified against
           anydoc/src/model/block.rs: eight variants, no source address of any kind).
           corpus_card.verbatim_fraction discloses it BEFORE any query runs. The trigger is named:
           vendor/anydoc/FORK-TRIGGER.md clause 1 is "emit a w:p / a:t child-index path per
           block"; the day that lands, the card key becomes 'exact' and the tier opens.
```

## 10.3 A 6-page scanned invoice with a JSON Schema, on a nearly-spent budget

The corpus carries a **`site`-layer** `[budget.per_unit]` override — `micros_base = 4_000`,
`micros_per_part = 800`, `micros_max = 12_000` — an operator's deliberately tight budget on an
invoice corpus. Every number below is under that override, not under the shipped default of §4.4,
and that is the point: the mechanism this trace demonstrates is reachable whenever an operator
lowers a budget, which §4.1 permits at `site` and at `project`.

`ow add invoice.pdf --schema po.schema.json`, with `clamp(4000 + 800x6, 0, 12000) = 8,800` for the
unit and **2,000 micros already spent this run** against that scope key.

```
GATE     unit.format='pdf'  format_basis='magic'  part_count=6  schema_requested=true
         action: no GATE action rule matches.
         modifiers, ALL of which apply because a modifier is not first-match-wins:
           gate.schema-admits-fields   -> lane 'fields', render 'structure'
           gate.form-admits-fields     -> corpus.is_form=true (pypdf get_form_text_fields(),
                                          olmocr filter.py:30-31) -> lane 'fields' again (a set
                                          union, so idempotent), render 'structure'
           gate.weak-format-basis-...  -> format_basis is 'magic', so it does NOT fire and the
                                          fields lane is not denied
         * olmocr's PdfFilter would have DROPPED this document entirely, with a logger.info only,
           behind --apply_filter which is action="store_true" and off by default. Here the verdict
           admits a lane.
         corpus.spam_score=0.001 is computed and read by NO rule (5.1).  trigger.kind='cli'.
         lanes = {text, fields}.  headroom = 8,800 - 2,000 = 6,800

lane fields, PAGE
         fields.extract -> driver='parse.fields.lift'.  The pre-evaluation resolution (4.3) already
         resolved it: lift's weights are OpenRAIL-M, compute_tier is `restricted`, and
         [licence] allow_tiers = ["open"] refuses it -> driver.unavailable = true.
         -> degrade.driver-unavailable at REGEN -> DEGRADE, ok_partial,
            Degradation(kind='driver_unavailable', wanted_driver='parse.fields.lift',
                        message names the tier, the licence sha and [licence] allow_tiers)
         COST: ZERO. The lane never reached admit() with a billable driver.
         * The lane's rules ship anyway: fields.ungrounded, verify.grounded_field_frac,
           @thresholds.grounded_field_min, FieldGrounding{path, value, grounded, part, text_span}
           with `number` and `boolean` leaves EXCLUDED from grounding, and the three
           non-negotiables the charter carries from lift — make_properties_nullable before
           constrained decoding (lift/lift/model/vllm.py:26-45; without it the grammar FORCES the
           model to invent values), an explicit minItems on every array, repetition_penalty = 1.0.
           The day an open-tier constrained-decoding driver exists, `fields.extract`'s driver id is
           the only line that changes. Until then this is a DISCLOSED lane, not a silent one.

lane text, parts 1-6, DECODE
         char_count=0 -> decode.blank-part-escape defers -> ink.tiles=9,102 > 4
         -> decode.no-text-layer -> PAGE
         * the text lane runs regardless of the fields lane, which is why the document still
           produces citable page text.

admission, drain pass by drain pass — RESERVATION DENIAL IS NOT EXHAUSTION
  pass 1   p1 reserve 2,732 -> headroom 4,068.  p2 reserve 2,732 -> 1,336.
           p3 requests 2,732 > 1,336 -> Deferred(micros).  Siblings ARE in flight, so
           budget.exhausted is NOT written and on_exhausted is NOT consulted.
           p1 commits 854 -> release 1,878.  p2 commits 854 -> release 1,878.  headroom 5,092.
  pass 2   p3 reserve 2,732 -> 2,360.  p4 denied.  p3 commits -> release -> headroom 4,238.
  pass 3   p4 reserve 2,732 -> 1,506.  p5 denied.  p4 commits -> release -> headroom 3,384.
  pass 4   p5 reserve 2,732 ->   652.  p6 denied.  p5 commits -> release -> headroom 2,530.
  pass 5   p6 requests 2,732 > 2,530 and NOTHING is in flight for this scope key
           -> budget.exhausted IS written into Evidence for part 6.

PAGE settle, parts 1-5
         verify.finish_reason='stop', parse_ok=true, nonempty=true -> page.output-invalid no match.
         agree.decode_vs_page NOT COMPUTED: DECODE produced nothing on a scanned page.

part 6
  REGEN->  degrade.budget-exhausted matches on {exists = true} -> escalate_to=DEGRADE
  DEGRADE  on_exhausted[0]='spill_to_free': re-evaluate at max_cost_class='free'
           -> driver=parse.pdf.pdfium  outcome='ok_partial'  reason='budget-exhausted'
           this is a scanned page, so pdfium yields 0 characters -> the DRIVER returns ok with zero
           blocks -> the HOST converts that to FAILED_PERMANENT(EMPTY_RESULT) BEFORE anything is
           cached -> on_exhausted[1]='partial': part 6 settles as ok_partial with no blocks.

outcome  doc.status='partial'.  degraded=1 on two decisions (part 6 budget, fields lane licence).
         Actual spend 2,000 + 5 x 854 = 6,270 of 8,800 — 71% of the cap, and part 6 still failed.
         THAT GAP IS THE p95 RESERVATION MODEL AND IT IS THE PRICE OF NEVER OVERDRAWING A DURABLE
         LEDGER (6.4).
         Degradation(kind='budget', unit_dim='micros', spent=6270, limit=8800, rung_reached=PAGE,
                     parts_affected=(6,))
         message: "[budget.per_unit].micros_per_part gives 8800 for 6 parts; exhausted at 6270/8800
                   after part 5/6; raise micros_per_part, pass --allow-cost, or set
                   on_exhausted=['defer'] in .omniweave/policy.d/00-builtin-route.toml"
         * 8,800 is the SITE-LAYER override declared above this trace, not the shipped default of
           4.4, which gives clamp(4000 + 3000x6, 0, 16000000) = 22,000 and never exhausts on this
           document.  The message names micros_per_part because that is the knob binding HERE.
         CLI exit code 5.  The line printed:
           ow add invoice.pdf --allow-cost 12000     (est. $0.0009 to finish part 6)
         and `ow_query` over this document returns verdict='degraded' with OW-A-013
         OW_PARSE_GAP_IN_SCOPE naming page 6 and that same command.
         * One unparsed part is a DISCLOSED gap with a page number and a fix, not a hole.
           Unlimited-OCR writes an empty text field here (infer.py:229).
```

---

# Part 11 — Router invariants RT1-RT14: where each is discharged

`RT1`-`RT14` are stated in the charter and are not restated. This document owns the router layer and,
through it, `INV-13` and `INV-14`: [01-principles.md](01-principles.md)'s owning-document table binds
them here, and its division of labour is explicit — where a layer invariant is the enforcer of a
framework invariant, that document names it and this one discharges it. What belongs here is the map
from invariant to the section a reviewer opens, so a pull request that weakens one is caught by name.
`RT3`, `RT7`, `RT9`, `RT10` and `RT11` had their substance in this document and no label; the rows
below are the labels. The table is the same shape as [04](04-driver-system.md) §12's for DR1-DR24 and
[07](07-store-and-retrieval.md) §15's for ST1-ST20.

| RT | discharged by | the mechanism, in one line |
|---|---|---|
| RT1 | §4.3 properties 3 and 7; §7.2 | `evaluate(policy, evidence, hints, rung, lane, phase)` takes no ledger, no clock and no `RunContext`; `driver.unavailable` is resolved into `Evidence` **once, before** evaluation so no live `resolve()` is needed inside it; semgrep bans `time.`, `random.`, `os.environ`, `importlib` and `open(` in `route/eval.py`, and a property test evaluates 10,000 fixtures twice in shuffled order |
| RT2 | §7.2; §8.1 | every sample is `blake2b(unit_uri ‖ part ‖ salt) % 10000 < rate × 10000`, so `audit_selected` is **derived, never random**; the `untrusted_external_rate = 0.05` substitution happens in the sampler, reading `unit.trust_class` directly, and not in a rule |
| RT3 | §7.1; §5.2 | `Evidence.read()` is the only accessor and appends to the read log — no `__getitem__`, no public mapping — so the read set is an observation rather than a declaration a programmer can forget. `read_set_digest` covers the `(key, provider_version, value)` triples the winning path consulted **and nothing else**, and §5.2's per-format resolution is what puts the *resolved* provider's version into the triple |
| RT4 | §4.3 (the demand plan), properties 1 and 2 | the compiler emits a `DemandPlan` per `(rung, lane, phase)` from the union of the reachable rules' read sets, partitioned by `CostClass` ascending and computed group by group; a clean born-digital page never reaches the `LOCAL_COMPUTE` group, and `service_attaches` / `page_renders` / `signal_computations` are **exact** — ±1 fails the gate |
| RT5 | §5.1; §2.1 | every `kind = "classifier"` row in the day-one registry declares `domain = [0.0, 1.0]`, closed on both ends; `FormatGuess.confidence` is deliberately **not** a registered `Signal`, so a sniffer's number is an ordering key and never a threshold comparand; `table.grid_score` is `kind = "measure"` rather than a classifier whose calibration gate could only be met by a lie |
| RT6 | §4.5; §5.3 | `ow route lint --calibration` asserts ECE ≤ 0.05 and Brier ≤ 0.08 for every classifier signal against `[calibration] eval_set_id` and fails the build on a regression; §5.3 names each signal's false-positive mode, which is what makes a threshold tunable rather than folkloric |
| RT7 | §4.3 (`on_unknown`); §4.5 checks 4 and 9; §4.2 | `on_unknown ∈ {skip, match, defer}` is **required** on any rule reading a nullable key (`OW-P-004`); `{exists: bool}` is total and therefore exempt; `defer` degrades to `skip` and records `Degradation(kind="signal_unavailable")` naming the key and its provider; check 9 (`OW-P-012`) refuses `match` on a rule whose `then.driver` declares `class = "billed_api"`, which is what makes "an unavailable signal can never spend money" mechanical |
| RT8 | §4.2 (`escalate_to`, `skip_rungs`); §4.5 check 5; Part 3 | the compiler rejects a backward `escalate_to` and a `skip_rungs` member at or below the rule's own rung **at load** (`OW-P-005`), which is CI parity for the charter's `route_decision_monotone` trigger rather than a second opinion; `DEGRADE = 5` is a forward move on `Rung` while running a cheaper driver, which is the whole reason `Rung` and `Spend` are separate types |
| RT9 | §4.3 property 7; §6.4 | exhaustion re-enters as the evidence key `budget.exhausted`, **written by `admit()`** and read only by the `DEGRADE` rules; `admit()` is the sole impure half of routing and runs strictly after `route_decision` is written, so a budget change can never alter which rung a document would have taken |
| RT10 | §6.4; §6.5 | `admit()` step 5 returns `Deferred(dim)`: the `work` row stays claimable and `cost_micros` is unchanged, so a denial is never a failure. The reservation is a durable `budget_reservation` row whose expiry equals the work row's `lease_expires`, headroom is computed **in SQL**, and the reserved-minus-actual gap is released in the commit transaction |
| RT11 | §6.4; Part 3; Part 9 | per-part dimensions are charged per `(unit_part, lane)`, so a whole `REGEN` chain shares one `[budget.per_part]` — `calls = 3` is the dimension that binds first on the shipped pricebook; Part 3's rung table declares `REGEN` **strictly serial**, and Part 9's driver-crash row is what localises a poison unit by retrying at `batch = 1` |
| RT12 | §8.1; §8.2 | `route_quality.source = 'self'` is stored and excluded by `route_scoreboard`'s own `WHERE source IN ('agree','audit','feedback')`; the *gap* between `self` and `audit` is kept deliberately, as a card diagnostic rather than an accuracy input |
| RT13 | §8.3 | the demotion writer accepts only a `then.driver` of strictly greater cost rank, under `demote_ttl_days = 30` and `release_at = regress_at × 0.6` hysteresis; a promotion attempt is refused, and a pinned decision is excluded from the scoreboard that would justify one |
| RT14 | **not this document** — [04-driver-system.md](04-driver-system.md) §7 and §4.5, where the card loader owns it | the card loader refuses a driver whose `[licence.weights] weights_revision` is absent or `"main"`. 05 *depends* on that and enforces none of it: `[render.*]` and `parse.page.olmocr`'s `[cost.model]` are only reproducible against pinned weights, and §5.2's `signals.toml` `version` is the provider-side analogue for code rather than for a model. No signal provider ships weights at release 1 — which is exactly why `vision` registers nothing (§5.1) |

**What this document adds to the router layer.** Three mechanisms above have no charter register id and
are enforced anyway, because each is a lint check over the grammar rather than a new invariant: the
action/modifier split (§4.2, check 12 / `OW-P-013`), the derived `select`/`settle` phase (§4.3, check 7
/ `OW-P-010`), and per-format signal-provider resolution (§5.2, `OW-P-022` at startup). None weakens an
RT row; each closes a gap where the charter's own shipped policy is not evaluable as written (Open
question 4). Minting `RT15`+ would extend the charter's own register, which is a charter amendment on
[01-principles.md](01-principles.md) §1b's five-part path and not something a plan document does alone.

---

## Open questions

1. **`Rung` casing in a policy file: closed, and the instrument is the lock rather than the
   charter.** `SCREAMING_SNAKE` is the authored spelling. `rung = "GATE"`, `escalate_to = "PAGE"`,
   `skip_rungs = ["REPAIR"]` and `--max-rung <RUNG>` are correct as §4.4 writes them, because
   `.omniweave/policy.d/*.toml` is an author-facing config artefact and not a wire. **Closed** by
   [ADR-4](adr/0004-shipped-routing-policy.md) decision 3, which corrects the instrument this item
   named: the charter states no casing rule at all — the convention is
   [terminology.md](_notes/terminology.md) §1's `enum member` row and its §3 rejection row, and the
   charter defers to the lock explicitly — so what changes is the **lock**. Its §1 row loses "there
   is no exception" and gains a scope: the lower-case wire value governs JSON, generated schemas, DB
   columns and every byte-diff-gated generated artefact, and not an author-facing config artefact
   (`policy.d/*.toml`, `omniweave.toml`, `pricebook.toml`, `retrieval.toml`). §3's "an upper-case
   `Rung` on the wire" row is **unchanged** — its qualifier is already the right scope. That row is
   [ADR-1](adr/0001-terminology-lock-bulk-pass.md)'s to write; a lock row coined outside its bulk
   pass fails the lock's own CI rule 1 in both directions. No wire is violated today:
   `route_decision.rung` is stored as an INTEGER and every generated artefact emits the lower-case
   member name, and the compiler rejects the lower-case authored spelling at load (`OW-P-023`, §4.4).
2. **`parse.text.builtin` has no charter row.** `[drivers] enabled` lists `parse.office.anydoc`,
   `parse.pdf.pdfium` and `parse.page.olmocr`, and anydoc's declared formats (Word, PowerPoint,
   Excel, OpenDocument, RTF, EPUB, CSV, PDF) do **not** include HTML, Markdown, XML, JSON, JSONL,
   notebooks, TSV or SVG — which the charter's own `decode.office-native` rule nevertheless routes to
   it. Ten format tokens therefore have no producer. I have specified `parse.text.builtin`, a
   stdlib-only `parse/1` driver shipping in `omniweave-office`, and lint check 11 to prevent the
   recurrence. **Closed:** the row ships — [04](04-driver-system.md) §10.1 carries
   `parse.text.builtin` in the release-1 roster, in `omniweave-office`, stdlib-only, serving the ten
   tokens `decode.text-native` names — and it is **enabled**, as row 4 of §4.4's thirteen
   ([ADR-3](adr/0003-shipped-configuration.md) decision 1): a roster row without an activation row
   is a driver that can never run (INV-5), which is the half of this defect the original item
   missed. Lint check 11 prevents the recurrence.
3. **`block.flagged_frac` is read by the charter's shipped policy and absent from its day-one signal
   registry**, so the builtin policy fails `ow route lint` check 1 as the charter writes it. I have
   registered it (part-scoped, `requires = (REPAIR,)`, FREE, nullable). **Closed** by
   [ADR-3](adr/0003-shipped-configuration.md) decision 4, by naming the sole home rather than by a
   new mechanism: §5.1 is the sole home of the signal registry and carries `block.flagged_frac`
   plus the seven other additions, and the charter's 23-row day-one table at `:2498` is retired by
   erratum `E38`. Neither of this item's two branches is taken — the charter's table is not amended
   row by row, and the key is not renamed, because seven other keys are in the same position and a
   registry with two homes is the defect underneath all eight.
4. **The charter's shipped policy is retired law, and the defect counts this item stated were
   wrong: closed.** [ADR-4](adr/0004-shipped-routing-policy.md) decision 1 retires the charter's §D4
   ` ```toml ` fence **in whole rather than clause by clause**, in favour of §4.4 as its sole home,
   under charter §9 erratum `E42`. Four measured grounds: (a) **seven** rules there fail lint check 4
   (`OW-P-004`), not nine, against **zero** in §4.4 — and one of the seven is dangerous rather than
   merely non-compliant, `repair.never-escalate-furniture` reading `block.type`, which has no PDF
   provider, so without `on_unknown = "match"` the furniture guard is silently off on the PDF path
   and one flagged footer spawns the inference server for a clean document (§4.4's copy carries the
   declaration and a comment saying it is load-bearing). (b) **One** inline table spans a newline,
   not two, and it is a `when` rather than a `then`. (c) Four `GATE` rules must all take effect on
   one part, which a single first-match-wins list cannot deliver — §4.2's action/modifier split is
   what resolves it, and those four rules are why the split exists at all. (d) Fifteen rules against
   forty. A reader who reaches that block looking for the shipped policy is reading retired law.
   **The correction that matters for the enforcer:** the newline-spanning construct is **legal
   TOML** — the newline falls inside an array literal — so `tomllib` accepts it, and all
   seventy-three ` ```toml ` fences in the charter and in `00`-`18` parse. Nothing in the corpus
   fails to parse, so the `tomllib.load` gate this item asked for would have caught none of it, and
   charter §8's rejection criterion 21 names a failure the corpus does not have. The closing
   enforcers are instead the **lexical** clause `G27(a2)` for the one-key-per-line rule (§4.4) and
   `G27(a3)` with its P1 interim standalone check 4 for the `on_unknown` rule (§4.5).
5. **`Degradation.kind` needs one new member: closed, and the one-member framing was wrong.**
   `rung_ceiling` (a part that would have escalated past `--max-rung`) has no existing member that
   means it; `budget` would be a lie and `pin` names a different mechanism. Every other degradation
   this document raises maps onto an existing member, including the `max_cost_class` clamp (§6.4
   step 1). **Closed** by [ADR-3](adr/0003-shipped-configuration.md) decision 4, which supersedes
   this item's "one new member" framing: the literal was short by **eleven**, not one, and
   [15](15-observability.md) §6.3 now prints the **twenty-seven**-member `DegradationKind` and owns
   the count, `rung_ceiling` among them. The charter's sixteen-member form is already retired by
   erratum `E15`, so nothing is owed here and no member is minted in this document — §6.4 and §7.3
   construct `Degradation(kind="rung_ceiling")` against 15's literal.
6. **A handwritten annotation on a born-digital page is undetectable at release 1.** The only signal
   that would catch it (`ink.coverage`) is `LOCAL_COMPUTE`, and the demand plan correctly never
   computes it on a clean page. **Closing evidence:** either a licence-clean layout detector landing,
   which reopens `layout.class_hist` and `REPAIR` on PDF (charter §7 F4); or a measurement showing the
   annotation rate in a real corpus is high enough to justify promoting `ink.tiles` to the FREE group
   for a named slice — which costs 15 ms on *every* part and needs the number first.
7. **A borderless PDF table does not engage the `table` lane.** `geometry.ruled_regions` finds ruled
   tables only, and `block.type` has no PDF provider. **Closing evidence:** measure the ruled fraction
   of tables in a real corpus per document class. Above ~70% ruled, the gap is acceptable and named;
   below it, a column-projection region detector (marker's own `table_recon` sweep, applied to find
   the region rather than the grid) becomes a release-1 signal rather than a v2 one. Both directions
   are cheap; neither should be chosen without the number.
8. **The `[cost.model] scaling` exponent default.** I have set `exponent = 2.0` against
   `render.short_edge_px`, on the reasoning that VLM tokens scale with pixels. No repo in the
   collection measures it. **Closing evidence:** an `ow conform --bench` sweep of one driver at 692,
   980 and 1384 px short edge reporting `tokens_in` per part; if the fitted exponent is below 1.5 the
   default is wrong and every A3 estimate is low. This is charter §7 F6 pointed at one axis.
9. **Every `est` in the §5.1 registry is a declared budget, not a measurement**, because nothing has
   been built. **Closing evidence:** `ow conform --bench` writing `signals.lock` on the reference
   hardware; the 2× declared-vs-measured gate then makes the column self-correcting. The two ratios
   the shipped policy actually depends on are `ink.tiles` (15 ms) against a `PAGE` call (2,400 ms) —
   the 160× trade that justifies `decode.blank-part-escape`'s file position — and `table.grid_score`
   (up to 30 ms) against `[budget.per_part]`.
10. **Connector cursors have no cross-connector reconciliation.** `unit.cursor` is per unit, which is
    right for resume, but there is no answer to "this Slack channel was re-keyed upstream and every
    cursor is now invalid". **Closing evidence:** whether `run.needs_full_scan` (the existing latch)
    is sufficient, or whether a connector needs a declared `cursor_epoch` that invalidates its whole
    cursor set on change. I lean on the latch: a connector that re-keys is rare enough to justify one
    full scan.
11. **The `route_*` DDL printed here deviates from the charter's in five places, and charter §9
    errata `E21` covers all five.** (a) `route_decision.cost_class` is **added**, because
    `ow_spend_micros_total`'s `cost_class` label and `ow cost --by driver`'s `class` column
    ([15](15-observability.md) §4.2, §5.4) have no other historical source, and reading it from the
    live catalog would re-label every past decision after a card upgrade. (b)
    `route_decision.reason` is **added**, because §4.2 requires a `skip` rule to record
    `{reason, key, threshold}` and `cause` carries only the clause that fired. (c)
    `route_scoreboard` is **rewritten** to pre-aggregate its two one-to-many children and to filter
    `self` inside the aggregate — §8.2's four properties give the arithmetic. (d) There is
    deliberately **no** `route_decision.dispatch_key`, although the charter's `I22` names it
    alongside `driver` and `cost_class` as a column the `work` row must agree with:
    `dispatch_key = sha256(driver‖config_digest‖isolation)[:16]` mixes the decision's `driver` with
    the *run's* config digest and isolation, neither of which is a routing input, so storing it
    would put a non-input in the decision's row. `I22`'s third column is checked against the
    planner's derivation from `route_decision.driver` instead. (e) `route_evidence.payload` is
    **nullable**, against the charter's `NOT NULL`, because a `NOT NULL` payload under a `NOT NULL`
    `evidence_digest` foreign key makes the 30-day blob sweep unable to run at all against 400-day
    decision rows — the sweep nulls the payload and stamps `swept_at` instead (§7.1, §8.4).
    **Closing evidence:** `E21` is written and covers (a)-(e), so what stays open is only a ruling
    on whether (a) and (b) belong in a sidecar rather than on the decision.

## New terms

Each needs a row in `terminology.md` §2. All are defined at their point of use above, except where a
row names another document as the owner.

| term | kind | one line |
|---|---|---|
| `SourceKind` | enum | `file \| dir \| url \| crawl \| connector \| stream` — the six acquisition source kinds. |
| `SourceLocator` | type | The frozen **host-side** input to acquisition: kind, ref, globs, depth, trust class, cursor floor. Built by `ow add` and `resolve_locator()`; the host projects it onto a ports-level `Locator` per invocation. A driver never sees one. |
| `TrustClass` | enum | `internal \| untrusted_external` — the enum behind `unit.trust_class`. Not `TrustTier`, not `Trust`. |
| `AcquireV1` | proto | The `acquire/1` Port, owned and printed by [04](04-driver-system.md) §1.4: `probe`, a static-config `__init__`, `enumerate(locator, io) -> DriverResult` and `fetch(ref, io) -> DriverResult`. Listed here only so the lock's owner column points at 04. |
| `UnitCandidate` | type | The `{"t":"candidate"}` record shape of `owroster-items/1` (§1.1): `tmp`, the connector-local `id`, `connector`, `next_cursor`, size, mtime, etag, hint, labels. Metadata only, and never a `unit_uri`. |
| `AcquiredUnit` | type | The `{"t":"fetched"}` record shape of `owroster-items/1` (§1.1): both digests, the byte count, the `cas://` blob ref, the hint, the etag and `fetched_at_ns`. Carries no identity — `RESULT.unit_index` says which unit it answers. |
| `StreamHint` | type | What the host knows before any sniffer looks: `(filename, extension, declared_media_type, byte_len)`. Four fields, declared once in `omniweave_ports` ([04](04-driver-system.md) §1.3). A hint, never an authority, and it carries **no** `trust_class`. |
| `FormatGuess` | type | One detection candidate as a driver may state it: `(media_type, format_token, confidence, consumed_bytes)`. Four fields, declared once in `omniweave_ports` ([04](04-driver-system.md) §1.3). No `basis` and no `detail`; a third party's `confidence` is clamped to 0.95. |
| `RankedGuess` | type | The **host-side** wrapper `(guess, basis, detail)` around a `FormatGuess` (§2.1). What ranks, what enters `doc.format_evidence`, and what §2.1's ladder emits. Host-side because `basis` is the host's classification and `omniweave_ports`' `layers.toml` row is `[]`. |
| `Basis` | type | The **host's** classification of how a format guess was obtained: `magic \| container_identity \| content_probe \| extension \| declared \| driver_sniff`. Six members. Not a `FormatGuess` field, and a driver may never assert it — `driver_sniff` is the member the host stamps on a driver's contribution. Lives in `omniweave/route/detect.py`. |
| `format_token_for()` | function | `format_token_for(media_type) -> str \| None` in `omniweave/route/detect.py` — the total media-type-to-token lookup over core's 48-row table ∪ one row per `{media_type, token}` pair in the enabled cards' `[capability.parse] format_tokens`. Single-valued because two cards pairing one media type with two tokens is `OW-D-024` at activation (§2.2). |
| computed format-token domain | derived set | `unit.format`'s domain: core's 48 ∪ the `token` fields of every enabled card's `format_tokens`, taken at policy-compile time and entering `policy_digest`. Lint checks 2, 10 and 11 resolve against it and never against the literal 48 (§5.1, §4.5). |
| `OW-P-021` | code | Lint check 13: a shipped `[budget.per_unit] micros_per_part` or `[budget.per_part] micros` below an enabled driver's `card.reserved_micros` (§4.5). |
| `OW-D-024` | code | A media type mapping to two format tokens across enabled cards (§2.2). |
| `OW_DETECT_UNKNOWN_TOKEN` | diag | A `FormatGuess` whose `format_token` is outside `unit.format`'s computed domain; the guess is dropped and the driver named (§2.2). |
| **action rule** / **modifier rule** | concept | The two kinds of `[[rule]]`. An action is first-match-wins per `(rung, lane, phase)`; a modifier contributes from every matching rule under a per-key monoid (§4.2). |
| `DemandPlan` | type | Per `(rung, lane, phase)`, the reachable rules' read set grouped by `CostClass` ascending. |
| `RouteDecision` | type | What one `(part, lane, rung)` decided, printed in §4.6: the eight identity fields, what the winning rule said, and the estimate `price()` attached. `evaluate()` returns it and a `route_decision` row is written from it, **before any driver runs**. It has no `render`, `max_cost_class` or `skip_rungs` field — those are `Modifiers`. |
| `Modifiers` | type | The second value `evaluate()` returns: the accumulated modifier rules for one `(rung, lane, phase)`, combined per key by the monoids of §4.2 (minimum, set union, more-expensive-wins, logical OR). A pure function of `(policy_digest, evidence)`, so it is recomputed by `ow route explain` and stored in no column. |
| `ComputedDomain` | enum | A `SignalSpec.domain` that is not a literal because it depends on which drivers are enabled. One member at release 1, `FORMAT_TOKENS`, resolved at policy-compile time and folded into `policy_digest` (§5.1). |
| `price()` | function | `price(decision, catalog, book) -> RouteDecision` in `omniweave/route/estimate.py` — the pure step between `evaluate()` and the row write that attaches `cost_class`, `est_spend`, `est_micros` and `reserved_micros`, and that resolves `driver_by = "cheapest_admissible"`. It is the **only** routing step that sees a `PriceBook`, which is what lets `evaluate()` stay replayable with no price argument (§4.6, §6.3). |
| `Evidence.computed()` | method | Whether a demand-plan group holding a key has already run — "computed and unavailable" against "not computed yet". `DemandPlan.deferrals_pending()` is its only caller, and it does not append to the read log, because a planner probe is not a read (§4.6). |
| `ContainerBudget` | type | The single decompression accumulator threaded through one container expansion tree. |
| `CostShape` | enum | `constant \| linear_per_part \| linear_per_byte \| linear_per_token` — the `[cost.model] shape` values. |
| `MAX_CONTAINER_TOTAL_BYTES` | const | 512 MiB decompressed from one container tree. |
| `MAX_CONTAINER_DEPTH` | const | 3. A zip in a zip in a zip; the fourth refuses. |
| `MAX_CONTAINER_UNITS` | const | 10,000 child units one container may mint. |
| `MAX_IDENTITY_BYTES` | const | 64 KiB. One container identity part, read in the host, with no DTD and no entity expansion. |
| `MTIME_GRANULARITY_NS` | const | 2 × 10⁹. The window inside which `stat_fresh` cannot prove a file unchanged. Named in the charter's `unit` DDL comment; it needs a §2 row. |
| `omniweave.signals` | entry-point | The signal-provider group. A provider is declared by this plus a `signals.toml`, read by the import-free card loader; it is never a `DriverCard` and never enters `resolve()`. |
| `signals.toml` | file | A signal provider's `SignalSpec` rows, as data, including `serves` — the format tokens this provider answers a key for (§5.2). |
| `signals.lock` | file | The committed artefact `ow conform --bench` writes: the measured p50 per `SignalSpec.est`, on named hardware. |
| `serves` | field | `SignalSpec`'s new per-provider format list. Overlapping claims for one `(key, format)` are `OW-P-022` at startup — renumbered from `OW-P-021`, which lint check 13 now carries (§4.5). |
| `parse.text.builtin` | driver id | The stdlib-only `parse/1` driver for the ten text-family format tokens anydoc does not serve. Ships in `omniweave-office` ([04](04-driver-system.md) §10.1); Open question 2 is closed. |
| `rung_ceiling` | member | A `Degradation.kind`: a part that would have escalated past `--max-rung`. Distinct from `pin`. **Owned by [15](15-observability.md) §6.3**, whose twenty-seven-member literal already carries it; this document raises it and mints nothing (Open question 5). |
| `expect_unavailable` | cfg | A `[[rule]]` key, default `false`: `then.driver` is deliberately absent from `[drivers] enabled`, so `ow doctor`'s exit-1 condition and lint check 6 downgrade to a warning naming the rule, and lint check 14 errors the day the driver is enabled (§4.2). Coined by [ADR-3](adr/0003-shipped-configuration.md) decision 2. |
| `unit.format_basis` · `geometry.ruled_regions` · `math.font_hit` · `math.part_frac` · `table.grid_score` · `doc.rung_run_length` · `driver.unavailable` · `block.flagged_frac` | Signal | Eight additions to the charter's day-one registry, all FREE, each with a named provider. |
| `request.lane` · `request.max_rung` · `request.prefer_capability` · `request.deadline_ms` · `request.schema_present` | Signal | The charter's `request.*` glob, enumerated, because `ow route lint` cannot resolve a glob. |
