"""Every `MAX_*` ceiling in the framework, the one `MIN_SQLITE` floor, and `effective()`.

**A ceiling is never a target and never a setting** (INV-22, 01-principles.md). A `MAX_*` is a
number its own producer is built never to exceed, clampable **down** by a tenant and never
widenable: `effective = min(tenant_cap, declared, HOST_MAX)`, where `HOST_MAX` is the role name for
the constant in this module. Widening past a `MAX_*` is a fork, not a flag. A number a producer
overshoots by design is a `*_TARGET_*` and is not here — `SEGMENT_TARGET_TOKENS = 1200` is the
worked example, and `MAX_SEGMENT_TOKENS = 2048` is the ceiling that replaced it (charter section
6.10).

**Enforcement is not this module's job.** It happens at each read boundary with
`take(N+1)`-then-check, so a limit is never discovered after the memory is spent: you read
`MAX_ENTRY_BYTES + 1` bytes and refuse if the extra byte arrived, rather than allocating the bomb
and measuring it. A breach is `RESOURCE_LIMIT{limit}` naming **which knob would need raising**. A
card declaring a `[limits]` value above `HOST_MAX` is `CARD_INVALID` (DR20), enforced by the card
validator in `omniweave_core.drivers`, not here.

**This module carries no version constant, now or ever.** `SCHEMA` is a stamp with a two-release
deprecation window, not a ceiling; its sole code home is `omniweave_core.contract`
(`adr/0009-schema-single-home.md` decision 1, 02-architecture.md section 2 rows 2 and 7). A grep
gate rejects a version constant added here (store property ST23).

Tier T-PUBLIC: semver'd with `RELEASE`, documented, SDK-typed.

Specified in 02-architecture.md section 2 row 7; the ceilings themselves are set by charter section
6.10, 03-document-model.md section 14, 05-ingest-and-routing.md ("The container budget and the
recursion limit"), 09-generation.md section 14.1, 13-quality.md section 13.4 and 14-security.md
section 2.1, and each constant's docstring names its own.
"""

from __future__ import annotations

from typing import TypeVar as _TypeVar

_Bound = _TypeVar("_Bound", int, float)

__all__ = [
    "HARD_CEILING",
    "INLINE_MAX",
    "MAX_ASSET_BYTES",
    "MAX_ASSET_TOTAL_BYTES",
    "MAX_AUTO_PARALLEL",
    "MAX_BLOCKS_PER_DOC",
    "MAX_BLOCKS_PER_PAGE",
    "MAX_BLOCK_DEPTH",
    "MAX_BLOCK_TEXT_BYTES",
    "MAX_CARD_BENCHMARKS",
    "MAX_CARD_BINARIES",
    "MAX_CARD_BYTES",
    "MAX_CARD_CONFIG_PROPERTIES",
    "MAX_CARD_DEPTH",
    "MAX_CARD_FORMATS",
    "MAX_CARD_PINS",
    "MAX_CASSETTE_BYTES",
    "MAX_CASSETTE_BYTES_TOTAL",
    "MAX_CLUSTER_EDGES",
    "MAX_CONTAINER_DEPTH",
    "MAX_CONTAINER_TOTAL_BYTES",
    "MAX_CONTAINER_UNITS",
    "MAX_DEPS_PER_UNIT",
    "MAX_DRIFT_BAND",
    "MAX_ENTITY_DEGREE",
    "MAX_ENTRY_BYTES",
    "MAX_ENTRY_COUNT",
    "MAX_EXPANSION",
    "MAX_EXPANSION_TEXT_BYTES",
    "MAX_FILTER_DOC_KEYS",
    "MAX_FINDINGS_PER_RULE",
    "MAX_FOLDED_FINDINGS",
    "MAX_GRID_SLOTS",
    "MAX_IDENTITY_BYTES",
    "MAX_IL_DEPTH",
    "MAX_IL_FILE_BYTES",
    "MAX_IL_NODES",
    "MAX_IMAGE_PIXELS",
    "MAX_ITEMS_PER_SEGMENT",
    "MAX_LINKS_PER_BLOCK",
    "MAX_MARKERS_PER_UNIT",
    "MAX_MARKER_PAYLOAD_BYTES",
    "MAX_MARKS_PER_BLOCK",
    "MAX_MENTIONS_PER_DOC",
    "MAX_PARTIAL_FRAC",
    "MAX_PAYLOAD_BYTES",
    "MAX_QUERY_CHARS",
    "MAX_QUERY_REFS",
    "MAX_QUERY_TERMS",
    "MAX_RECORDS",
    "MAX_RECORD_DEPTH",
    "MAX_REDUCTION_BYTES",
    "MAX_REF_SITES_PER_BLOCK",
    "MAX_RENDER_PIXELS",
    "MAX_REPORT_BYTES",
    "MAX_RESIDENT_CELLS",
    "MAX_SEGMENT_BLOCKS",
    "MAX_SEGMENT_TOKENS",
    "MAX_SNAPSHOT_MS",
    "MAX_VIEW_BYTES",
    "MAX_XML_DEPTH",
    "MAX_XML_NODES",
    "MAX_X_BYTES",
    "MIN_SQLITE",
    "PREFILTER_MAX",
    "SEM_BLOCKS_PER_SEGMENT",
    "VEC_BRUTE_MAX",
    "effective",
]


# ---------------------------------------------------------------------------
# The one floor
# ---------------------------------------------------------------------------

MIN_SQLITE: tuple[int, int, int] = (3, 42, 0)
"""The one declared **floor** beside the `MAX_*` ceilings.

STRICT tables need 3.37, `unixepoch()` needs 3.38 and `unixepoch('subsec')` needs 3.42; shipped DDL
and shipped SQL use all three, so the highest of them is the floor. `store/sqlite.py` refuses at
open below it, naming `pip install omniweave-core[sqlite]`, and doctor check `D-01` reports it.

Set by charter section 6.10; stated in 07-store-and-retrieval.md section 2.1.
"""


# ---------------------------------------------------------------------------
# The clamp
# ---------------------------------------------------------------------------


def effective(
    tenant_cap: _Bound | None,
    declared: _Bound | None,
    host_max: _Bound,
) -> _Bound:
    """`effective = min(tenant_cap, declared, HOST_MAX)` — the three-way clamp, and nothing else.

    `tenant_cap` is `omniweave.toml`'s `[limits]` value for this ceiling, `declared` is a
    DriverCard's `[limits]` value, and `host_max` is the constant in this module. `None` means the
    party did not speak, which is not the same as `0`.

    A tenant may clamp **below** a ceiling and never above; `[limits]` in `omniweave.toml` says so
    in its own comment, and a card declaring above `HOST_MAX` is `CARD_INVALID` (DR20). That
    rejection belongs to the card validator in `omniweave_core.drivers` — this function takes the
    minimum, so an over-declaration is harmless here rather than silently honoured, and the caller
    that must refuse it still has to.

    This function does not enforce anything: enforcement is at each read boundary with
    `take(N+1)`-then-check (02-architecture.md section 2 row 7).

    Specified in charter section 6.10, INV-22 (01-principles.md) and 04-driver-system.md section
    4.3.
    """
    result = host_max
    if tenant_cap is not None and tenant_cap < result:
        result = tenant_cap
    if declared is not None and declared < result:
        result = declared
    return result


# ---------------------------------------------------------------------------
# The driver card
# 04-driver-system.md section 4.5 (erratum E6), which owns these seven. They are the only ceilings
# in this module bounding a file a THIRD PARTY wrote and the loader parses BEFORE any trust decision
# has been made, so each is enforced `take(N+1)`-then-check and each breach is `CARD_INVALID` naming
# the key and the cap -- never a `RESOURCE_LIMIT`, because a card is a contract and a malformed one
# is refused rather than clamped.
# ---------------------------------------------------------------------------

MAX_CARD_BYTES: int = 65_536
"""64 KiB: one `driver.toml`, as read from disk.

The largest first-party card is `parse.page.olmocr` with its benchmark rows at ~8 KB, and 64 KiB is
8x that. The loader reads `MAX_CARD_BYTES + 1` bytes and refuses if the extra byte arrived, so a
card bomb is never allocated: discovery parses attacker-adjacent TOML in a process INV-3 holds to
80 ms, and an unbounded read there is a denial of service against `ow --version`.

Set by 04-driver-system.md section 4.5.
"""

MAX_CARD_DEPTH: int = 6
"""Table nesting depth inside a card.

The deepest legal path in the grammar is `quality.benchmark[].measured_on.<field>` at 4, so 6 is one
doubling of headroom over the deepest thing a valid card can say. It bounds the loader's own
recursion, which is the half that matters: `tomllib` will happily build a thousand-deep mapping, and
the validator that walks it is what would exhaust the stack.

Set by 04-driver-system.md section 4.5.
"""

MAX_CARD_FORMATS: int = 64
"""Members of `[capability] formats` on one card.

anydoc's twelve media types (04-driver-system.md section 10.1) is the widest first-party card, and
64 covers a plausible universal decoder without letting one card's format list dominate the
computed `unit.format` domain every enabled card contributes to.

Set by 04-driver-system.md section 4.5.
"""

MAX_CARD_BINARIES: int = 16
"""Members of `[hardware] needs_binaries` on one card.

Not only a shape cap. Every declared binary costs one `shutil.which` plus one `os.stat` inside
`env_digest` (04-driver-system.md section 4.7), which is on the probe-cache key path, so this is
what keeps that digest's cost a handful of microseconds rather than a function of what a card felt
like declaring.

Set by 04-driver-system.md section 4.5.
"""

MAX_CARD_PINS: int = 256
"""Members of `[deps] pins` on one card.

The pins digest is `sha256(canonical(sorted(deps.pins)))` and enters the cache key only for a
`cost.model.class = "free"` driver (04-driver-system.md section 2.8), so the cap bounds a sort and a
canonical encoding performed once per card per catalog build.

Set by 04-driver-system.md section 4.5.
"""

MAX_CARD_BENCHMARKS: int = 64
"""`[[quality.benchmark]]` rows on one card.

The golden corpus has fewer than 20 slices, so a card claiming more than 64 benchmark rows claims
more slices than exist to measure. Each row additionally requires a complete ten-field `MeasuredOn`
and `n >= 30`, so this bounds the most expensive validation the loader performs.

Set by 04-driver-system.md section 4.5.
"""

MAX_CARD_CONFIG_PROPERTIES: int = 32
"""Properties in a card's `[config]` table.

The closed JSON-Schema subset of 04-driver-system.md section 2.7 admits `properties` at the root
only, so this bounds the whole config surface of one driver. It is also what keeps `ow show-config`
renderable: every key is printed with its source, and a finite type lattice over a bounded property
set is what makes that a table rather than a tree walk.

Set by 04-driver-system.md sections 2.7 and 4.5.
"""


# ---------------------------------------------------------------------------
# Acquisition: the container budget and the recursion limit
# 05-ingest-and-routing.md, which owns the `limits.py` container block. Values are anydoc's measured
# ones (`anydoc/src/package/limits.rs`, MIT), because that is the only complete attack taxonomy for
# OOXML, ODF and legacy-binary formats in the mined collection.
# ---------------------------------------------------------------------------

MAX_ENTRY_BYTES: int = 134_217_728
"""128 MiB: one container member, decompressed.

The single-entry decompression bomb. Read `MAX_ENTRY_BYTES + 1` and refuse if the extra byte
arrived; the central directory's declared size is a cheap pre-filter and the read is *also* capped,
because a liar in the directory must not pass (14-security.md section 2.2).

Set by 05-ingest-and-routing.md; reused at a second enforcement site by 14-security.md section 2.1.
"""

MAX_CONTAINER_TOTAL_BYTES: int = 536_870_912
"""512 MiB decompressed from one container **tree**, charged before per-member work.

One accumulator threaded through the whole recursion, not a per-level counter: two 300 MB siblings
inside one 512 MB budget must fail on the second, not pass twice. A cache hit costs nothing and is
not charged, which is what makes the budget both safe and non-annoying on legitimate OOXML packages
that reference one part from many relationships (14-security.md section 2.2).

Carries the same number as `MAX_ASSET_TOTAL_BYTES` and is **not** the same ceiling; the `CONTAINER`
prefix is what keeps them apart (glossary.md, INV-21). anydoc's own spelling for it,
`MAX_TOTAL_BYTES`, is struck.

Set by 05-ingest-and-routing.md.
"""

MAX_ENTRY_COUNT: int = 100_000
"""Members visited in one container tree — the entry-count flood.

Set by 05-ingest-and-routing.md; anydoc's value.
"""

MAX_CONTAINER_DEPTH: int = 3
"""A zip in a zip in a zip. The fourth refuses.

markitdown's default-registered `ZipConverter` recurses through the same dispatcher with no depth
tracking at all, which is the precedent this closes.

Set by 05-ingest-and-routing.md.
"""

MAX_CONTAINER_UNITS: int = 10_000
"""Child units one container may mint.

It bounds **one** container; nothing bounds 10,000 containers, so the corpus-level bound is
`producer_should_pause()`, not a constant (05-ingest-and-routing.md).

Set by 05-ingest-and-routing.md.
"""

MAX_IDENTITY_BYTES: int = 65_536
"""One container identity part, read in the **host**.

Set by 05-ingest-and-routing.md.
"""


# ---------------------------------------------------------------------------
# L2, the document model
# 03-document-model.md section 14. Five of these are set by charter section 6.10 and the rest are
# 03's own.
# ---------------------------------------------------------------------------

MAX_ASSET_BYTES: int = 268_435_456
"""256 MiB: **one** embedded asset, streamed with a content-length pre-check.

The CAS is swept by `[cache.max_bytes] blob` and `render`, not by this ceiling.

Set by charter section 6.10; tabled in 03-document-model.md section 14 and 14-security.md section
2.1.
"""

MAX_ASSET_TOTAL_BYTES: int = 536_870_912
"""512 MiB: one document's **whole** retained asset set.

**Derived, not copied, and the arithmetic matters.** anydoc's constant is 134_217_728, which is
smaller than the charter's per-asset `MAX_ASSET_BYTES` of 268_435_456 — so under anydoc's number a
single legal maximum-size asset could never be retained and the first ceiling a document tripped
would be the wrong one. Set to `MAX_CONTAINER_TOTAL_BYTES` instead: two maximal assets fit, the
per-asset ceiling binds for a single fat image, and the archive budget stays the outermost bound.

Set by 14-security.md section 2.1.
"""

MAX_GRID_SLOTS: int = 4_000_000
"""One table's materialised cover map.

Closes `<table:table-column table:number-columns-repeated="1073741824"/>` — a 60-byte cell asking
for a billion columns.

**Provisional, and known non-firing on the fixture that matters.** On the charter's celebrated
4M-cell sheet this ceiling does **not** fire, because 4,000,000 is not greater than 4,000,000, and
the sheet is therefore *admitted* (03-document-model.md section 14.1). That is deliberate: charter
deferred item **F29** — the sub-page commit boundary — is the unrun measurement behind both this
constant and `MAX_BLOCKS_PER_PAGE`, and 12-performance.md section 5 states the consequence plainly:
**a pessimistic answer moves two constants, not one**, because a page admitted by one and unbounded
by the other is the shape of the failure. Do not move this number alone.

Set by charter section 6.10; tabled in 03-document-model.md section 14 and 14-security.md section
2.1.
"""

MAX_EXPANSION: int = 4_000_000
"""A table's charged span **area** — repeat-expansion positions, charged before expanding.

**Equal to `MAX_GRID_SLOTS` and asserted equal**, so a table cannot build and then fail to store.
This is what stops `rowspan="99999"` in a three-row HTML table.

Set by 03-document-model.md section 14; also charter section 6.10 and 14-security.md section 2.1.
"""

MAX_SEGMENT_BLOCKS: int = 512
"""L3's segment ceiling, and the reason `MARK_HYDRATE_WINDOW` is 512.

Exact rather than approximate, because `derive_cover.cover_bits` is sized off it:
`ceil(512/8) = 64` bytes, always. Widening it rather than forking is a violation of INV-22. The
segmenter's `n_blocks + 1 >= MAX_SEGMENT_BLOCKS` rule means a Segment holds at most 511 blocks.

Set by charter section 6.10; used in 06-structure-extraction.md section 2.
"""

MAX_BLOCKS_PER_DOC: int = 8_388_608
"""`2**23`: one document, chosen as twice the charter's celebrated 4M-cell sheet.

At the 660 B/block budget that is 5.5 GB of store for one document, which is the largest single
document omniweave admits. The pre-committed answer to the F29 residue is this ceiling plus a
`RESOURCE_LIMIT` refusal naming the knob, rather than a speculative sub-page unit
(12-performance.md section 5, 08-runtime.md section 14).

Set by 03-document-model.md section 14. 14-security.md section 2.1's register lists the same
constant with the value cell `tier-set`, which is not a number; 03 is the site that sets it.
"""

MAX_BLOCKS_PER_PAGE: int = 4_194_304
"""`2**22`: one page, and therefore **one transaction**.

**Provisional. The number sits 4.9% above a known-failing fixture and the measurement behind it has
not been run.** It is chosen so the charter's 4M-cell sheet is admissible with 4.9% headroom, and
the cost is stated rather than hidden: at 660 B/block that page is a ~2.8 GB WAL and, at 182k
blocks/s, a ~23 s commit against `loop_lag_max_ms = 250` — a 92x breach and R-T13's own detection
trigger.

This is charter deferred item **F29**, the sub-page commit boundary. The charter's own resolution is
exactly this refusal rather than a speculative sub-page unit, and 03-document-model.md section
14.1's hostile-input row says **admitted**, not refused, for the same fixture: F29 is the spike, not
a refusal that already ships. A fix must move **both** this constant and `MAX_GRID_SLOTS`
(12-performance.md section 5).

Set by 03-document-model.md section 14.
"""

MAX_BLOCK_TEXT_BYTES: int = 1_048_576
"""1 MiB: one block's `text`. Four times `INLINE_MAX`, so any block arriving inline is already
inside it.

A longer run is **split** into sibling blocks joined by `rel(continues)` with
`Diag(OW_TEXT_SPLIT, info)`, never truncated — which is what happens to a 400 MB minified JS file
arriving as one `code` block.

Set by 03-document-model.md section 14. 07-store-and-retrieval.md section 14 refers to the same
ceiling as `MAX_BLOCK_CHARS`; that spelling has no definition site and is not coined here.
"""

MAX_MARKS_PER_BLOCK: int = 4_096
"""The mark array — a `mark` array of 10**6 zero-width anchors.

The same 4,096 as `MAX_LINKS_PER_BLOCK`, and the `maxItems` in 03-document-model.md section 3.2.

Set by 03-document-model.md section 14.
"""

MAX_BLOCK_DEPTH: int = 64
"""The containment spine, matching `os_path`'s 64-element ceiling and bounding `addr` under its
512-char CHECK.

50,000 nested `<div>`s do not refuse the document: the 65th level is **flattened** into its ancestor
with `Diag(OW_DEPTH_FLATTENED, warning)`, because refusing a document over a stylistic nesting is
worse than losing the nesting.

Set by 03-document-model.md section 14.
"""

MAX_PAYLOAD_BYTES: int = 16_384
"""`canonical(payload)` per block: a payload is kind-specific facts, not a document.

Set by 03-document-model.md section 14.
"""

MAX_X_BYTES: int = 16_384
"""`canonical(x)` per block: a third party's annotation, not a second document.

`x` is not a digest input, so an `x` map carrying a megabyte per block cannot be used to force cache
churn either.

Set by 03-document-model.md section 14.
"""

MAX_RESIDENT_CELLS: int = 65_536
"""Out-of-order cells held resident in `build_grid`.

Set by 03-document-model.md section 14, whose section 10.2 owns the algorithm.
"""

MAX_VIEW_BYTES: int = 67_108_864
"""64 MiB: one `serialize()` result — the one thing about a `Doc` that is fully resident.

Serializing a whole 5,000-page document materialises the whole view: ~600k blocks x ~250 chars is
~150 MB of Python string plus a `SpanMap` of 600k intervals at 24 B. Checked **incrementally as the
serializer appends**, not after the memory is spent, with `RESOURCE_LIMIT{MAX_VIEW_BYTES}` naming
the knob. Whole-document rendering is therefore a page-ranged loop by construction.

Set by 03-document-model.md section 14 (section 13.5 has the arithmetic).
"""

INLINE_MAX: int = 262_144
"""256 KiB: a driver-protocol body. Above it, a blob reference travels instead of the bytes.

Fuzzed in `omniweave_core.host.wire` alongside `header_len <= 1 MiB` and a JSON depth of 32.

Set by charter section 6.10; tabled in 03-document-model.md section 14.
"""


# ---------------------------------------------------------------------------
# Hostile markup, legacy records and rasterisation
# 14-security.md section 2.1. The five anydoc constants charter section 6.10 does not name and
# 05-ingest-and-routing.md has not already adopted, plus the two pixel ceilings.
#
# 05-ingest-and-routing.md says `MAX_XML_DEPTH`, `MAX_XML_NODES`, `MAX_GRID_SLOTS`, `MAX_EXPANSION`
# and `MAX_EXPANSION_TEXT_BYTES` are enforced *inside* `parse.office.anydoc` and "the host does not
# duplicate them"; 14-security.md section 8, glossary.md and the terminology lock all say the five
# are "added to `omniweave_core.limits`". They are declared here, which is what three of the four
# documents ask for, and what 18-api-sketch.md section 3's "every `MAX_*` is in `limits.py`"
# requires.
# Declaring is not enforcing, so 05's split survives: the driver is still the only enforcement site.
# ---------------------------------------------------------------------------

MAX_XML_DEPTH: int = 256
"""Pathological XML nesting. anydoc's value.

Set by 14-security.md section 2.1.
"""

MAX_XML_NODES: int = 2_000_000
"""DOM memory exhaustion. **Measured**: ~400 B/node x 2M is ~800 MB, sized to stay near the
archive budget.

Set by 14-security.md section 2.1; anydoc's value.
"""

MAX_EXPANSION_TEXT_BYTES: int = 67_108_864
"""64 MiB: repeat-expansion **bytes** — a second, independent budget beside `MAX_EXPANSION`.

The first bounds positions and only this one bounds memory. With `MAX_GRID_SLOTS` it is one of the
two ceilings a from-scratch implementation always misses, and both are the ODS/XLSX amplification
vectors.

Set by 14-security.md section 2.1; anydoc's value.
"""

MAX_RECORD_DEPTH: int = 64
"""Legacy CFB record nesting (`.doc` / `.ppt` / `.xls`). anydoc's value.

Set by 14-security.md section 2.1.
"""

MAX_RECORDS: int = 16_000_000
"""Legacy record-stream flood. anydoc's value.

Set by 14-security.md section 2.1.
"""

MAX_IMAGE_PIXELS: int = 89_478_485
"""The image decompression bomb: a 64,000 x 64,000 PNG is 260 KB compressed and 16 GB decoded.

Pillow's own `Image.MAX_IMAGE_PIXELS` default, `int(1024**3 // 4 // 3)`; about 341 MB at 4 B/px.

Set by 14-security.md section 2.1.
"""

MAX_RENDER_PIXELS: int = 40_000_000
"""The page-raster bomb: a PDF MediaBox of 200 in x 200 in at 300 DPI is 3.6 Gpx, about 14 GB.

**Derived**: A4 at 600 DPI is 4962 x 7016 = 34.8 Mpx, so 40 Mpx admits the highest DPI any shipped
policy uses and refuses everything above it.

Set by 14-security.md section 2.1.
"""


# ---------------------------------------------------------------------------
# L3/L4: structure extraction and the graph
# charter section 6.10's named maxima, used by 06-structure-extraction.md.
# ---------------------------------------------------------------------------

MAX_SEGMENT_TOKENS: int = 2048
"""The real ceiling the segmenter refuses to cross.

INV-22's worked example: `MAX_SEGMENT_TOKENS = 1200` was a **target** wearing a ceiling's name,
because the segmenter emits *after* crossing it, so the total lands above it by design. The
resolution is `SEGMENT_TARGET_TOKENS = 1200` — which is not in this module, because a target is not
a maximum — plus this number, and only this one is enforceable by `take(N+1)`-then-check. A single
block larger than it is its own segment, with `Diag(OW_RESOURCE_LIMIT, {limit:
"MAX_SEGMENT_TOKENS"})`: a disclosed refusal to split a block.

Set by charter section 6.10.
"""

MAX_REF_SITES_PER_BLOCK: int = 32
"""Occurrence rows per block on the `ref_site` side of `anchor`.

A breach emits `Diag(OW_REFSITE_TRUNCATED)` and is counted, never silent.

Set by charter section 6.10; enforced at write per 07-store-and-retrieval.md section 4.
"""

MAX_LINKS_PER_BLOCK: int = 4096
"""`block_link` rows out of one block, enforced at write.

Set by charter section 6.10.
"""

MAX_ENTITY_DEGREE: int = 4096
"""Entity overload: a template string that became an entity.

Crossing it with `doc_count` still at 1 is the signature, and the entity is excluded from ranking
and clustering while its mentions are kept — `OW_GRAPH_ENTITY_OVERLOADED`.

Set by charter section 6.10; 06-structure-extraction.md section 1.3 owns the detection.
"""

MAX_MENTIONS_PER_DOC: int = 250_000
"""Mention rows one document may produce; a breach is `OW_GRAPH_ITEM_BUDGET` naming the knob.

Set by charter section 6.10.
"""

MAX_ITEMS_PER_SEGMENT: int = 2048
"""Items one extraction pass may return for one Segment.

The answer to "emit 100,000 entities named ACME". `[graph] max_items_per_segment = 512` clamps below
it (06-structure-extraction.md section 3).

Set by charter section 6.10.
"""

MAX_CLUSTER_EDGES: int = 8_000_000
"""Above it `op.cluster` **refuses** with `OW_GRAPH_TOO_LARGE`, naming the cap and the driver seam.

Measured, not guessed: about 1.5 us/edge/sweep in a pure-CPython loop is ~12 s for one sweep at this
size (B42) and ~60 s for a five-sweep run, which is why the refusal sits at 8M edges and not 80M.
The escape above it is the `omniweave-driver-leiden` seam.

Set by charter section 6.10; measured in 12-performance.md section 2.
"""


# ---------------------------------------------------------------------------
# Retrieval and serve
# 07-store-and-retrieval.md and 10-interfaces.md; the four non-`MAX_` names are charter section
# 6.10's own spellings and are listed there among "the named maxima".
# ---------------------------------------------------------------------------

MAX_SNAPSHOT_MS: int = 5_000
"""The ceiling on one read transaction's life.

`[retrieval] snapshot_ms` clamps below it, default 2,000.

**A WAL-valve safety parameter, not a UX parameter.** A held read transaction pins the WAL, and 30 s
of pinned WAL is the precise condition that produced 22 GB of WAL and exit 137 in codegraph.
Exceeding it `interrupt()`s the connection and aborts with `OW-S-010` / `OW_SNAPSHOT_EXPIRED` and a
`degraded` Verdict — it aborts rather than serving.

Set by charter section 6.10; 07-store-and-retrieval.md section 12 owns the mechanism.
"""

PREFILTER_MAX: int = 200_000
"""Blocks in an exact narrowed set. A `LIMIT PREFILTER_MAX + 1` probe **proves** the set is too big.

Above it the narrowing set is not materialised and narrowing becomes an over-fetch factor
`clamp(1/selectivity, 1, 64)` instead. The probe is the `take(N+1)`-then-check discipline in SQL: it
proves the bound rather than discovering it after the memory is spent. F52 is the open question of
whether 200,000 is the right cut.

Set by charter section 6.10; 07-store-and-retrieval.md section 6.1 owns the three-way choice.
"""

VEC_BRUTE_MAX: int = 250_000
"""**Segments** — about 7.5M blocks — above which the shipped stdlib vector backend refuses.

The refusal costs nothing: the semantic Channel reports `UNAVAILABLE(ceiling)` with `OW-S-022`
**before** running. Measured, not guessed: B28's 281 ms against a 250 ms ceiling at exactly this
size, growing linearly and silently. `[retrieval.vec] max_segments` clamps below it.

Set by charter section 6.10; measured in 12-performance.md section 2.
"""

HARD_CEILING: int = 24_000
"""Characters in one packed Answer — the framework ceiling every packing tier clamps below.

The effective value is `min(requested, tier.max_chars, HARD_CEILING)`; a request can never raise it.
About 7,620 tokens at the framework's tokenizer-free conversion. Three orders of magnitude below
`MAX_VIEW_BYTES`, which is why the Answer path never approaches a whole-document serialisation.

Set by charter section 6.10; 10-interfaces.md section 3.2 owns the packing tiers.
"""

SEM_BLOCKS_PER_SEGMENT: int = 64
"""Blocks of one Segment the semantic Channel may contribute to a single Answer.

A **retrieval** constant and not a packing key: putting it in `[serve.packing]` would give one
number two homes (18-api-sketch.md section 4). It can bite, because `MAX_SEGMENT_BLOCKS` is 512. It
is the survivor of D5's dropped `MAX_CHUNK_BLOCKS = 64`, which lost to D7's `MAX_SEGMENT_BLOCKS =
512` as the segment ceiling.

Set by charter section 6.10's note; 07-store-and-retrieval.md section 8 owns the use.
"""

MAX_QUERY_CHARS: int = 4_000
"""Characters of `Query.text`, enforced **before any store read**.

Over-length input is not raised on: the query returns a success-shaped `Answer` carrying
`OW_QUERY_TOO_LONG` (`OW-A-008`) in `ow:blocking`. The residue is never silently truncated, because
a truncated query returns confident wrong results.

Set by 07-store-and-retrieval.md section 5.4; printed in 18-api-sketch.md section 1.2.
"""

MAX_QUERY_TERMS: int = 64
"""Sanitised terms in one query.

It is also why the FTS index ships with no `prefix` option: a `tok*` query still works by scanning a
term-index range, and at 64 terms that is affordable against a measured ~2.6x index-size cost.

Set by 07-store-and-retrieval.md section 5.4; printed in 18-api-sketch.md section 1.2.
"""

MAX_QUERY_REFS: int = 16
"""Reference-shaped tokens in one query.

They go into a TEMP table `tmp_refs`, not into N statements.

The `exact` Channel is one statement over `tmp_refs` precisely so that even the maximum is one plan.

Set by 07-store-and-retrieval.md section 5.4; printed in 18-api-sketch.md section 1.2.
"""

MAX_FILTER_DOC_KEYS: int = 1024
"""`Filters.doc_keys` entries that may travel as an `IN (...)` list.

Above the cap they become a second temp table `tmp_docs` and a join — never a 100k-element `IN`
list, which is a parse-time failure. This ceiling changes the **plan**, it does not refuse the
query.

Set by 07-store-and-retrieval.md section 6.
"""


# ---------------------------------------------------------------------------
# The runtime
# ---------------------------------------------------------------------------

MAX_AUTO_PARALLEL: int = 96
"""**A cap, not a default**, on automatically derived request parallelism against a model server.

`refill_target = min(service_capacity, MAX_AUTO_PARALLEL, cfg.max_inflight, ...)`. It is the cap
*past the knee* — past a B200's, not at a small card's — so it never reads as a target to hit.

Set by charter section 6.10; 08-runtime.md section 6 and 12-performance.md section 8 own the
arithmetic.
"""

MAX_DEPS_PER_UNIT: int = 256
"""`dep` rows one unit may record. Enforced in `Store.complete()`, which **raises**.

Past it the operator **must** declare a cohort dep — coarser, always safe, over-invalidating on
purpose. `[runtime] max_deps_per_unit` clamps below it. The reverse index makes invalidation one
query rather than a sweep, which is what this ceiling protects.

Set by charter section 6.10; 07-store-and-retrieval.md section 11.4 owns the mechanism.
"""


# ---------------------------------------------------------------------------
# The OUT framework
# 09-generation.md section 14.1. Each carries its arithmetic, because an orphan ceiling gets
# raised by
# whoever hits it first. (Section 14.1's prose says "these seven"; its table prints eight rows.)
# ---------------------------------------------------------------------------

MAX_IL_FILE_BYTES: int = 4_194_304
"""4 MiB: one IL file, checked with `take(N+1)`-then-check at the read boundary.

`MAX_IL_NODES` x a mean 40 source bytes per element. The same ceiling as `MAX_IL_NODES`, expressed
in the unit the reader hits first.

Set by 09-generation.md section 14.1.
"""

MAX_IL_NODES: int = 100_000
"""Nodes in one unit's IL tree.

At about 1 KB of parsed node — an `Element` with an attrib dict and text, plus the `el`/`nsig` index
entry — one unit's tree peaks near 100 MB, which is the per-unit memory the runner is built for and,
because the runner is streaming, the whole-roster peak too.

Set by 09-generation.md section 14.1.
"""

MAX_IL_DEPTH: int = 128
"""IL nesting, checked **during** the parse walk and not after.

The carrier walk, the canonicalizer and the serializer each add about 3 Python frames per level, so
128 levels is about 384 frames against CPython's default 1000-frame limit, leaving headroom for the
caller. No legitimate slide or flow document nests 128 deep.

Set by 09-generation.md section 14.1.
"""

MAX_FINDINGS_PER_RULE: int = 5_000
"""Findings one rule may emit before folding, at about 400 B each — 2 MB for one rule.

Per rule rather than per report, so one runaway rule cannot consume the budget of the other 59.
A truncation records an entry naming the rule and the count and turns the gate `unverified` — never
`passed`, because the truncated tail may contain errors.

Set by 09-generation.md section 14.1.
"""

MAX_FOLDED_FINDINGS: int = 20_000
"""Findings in a folded report: 20,000 x ~400 B is 8 MB, which is `MAX_REPORT_BYTES`.

Beyond it the report re-folds on a coarser key rather than truncating.

Set by 09-generation.md section 14.1.
"""

MAX_REPORT_BYTES: int = 8_388_608
"""8 MiB: the size at which `validation/final.json` stops being a file an agent can read and starts
being a file it must page through.

Enforced by the second fold, **never** by truncating the JSON.

Set by 09-generation.md section 14.1.
"""

MAX_MARKER_PAYLOAD_BYTES: int = 4_096
"""One `OWC1` marker payload: a note, not a document. Encodes to at most 10,927 marker characters.

Set by 09-generation.md section 14.1.
"""

MAX_MARKERS_PER_UNIT: int = 256
"""Open notes on one unit. A unit with 256 of them needs a conversation, not a 257th note.

Set by 09-generation.md section 14.1.
"""


# ---------------------------------------------------------------------------
# Quality and eval
# 13-quality.md section 13.4. Five constants; `MAX_DRIFT_BAND`'s consumer is the conformance kit.
# ---------------------------------------------------------------------------

MAX_DRIFT_BAND: float = 0.02
"""The ceiling on the kit-measured `drift_band` a `seeded` `ReplayClass` may declare.

Above it the card must declare `unpinnable`. Without a ceiling, `seeded` absorbs `unpinnable` by
declaration and the three-valued enum collapses to a boolean. Chosen so a 1,000-block document's
drift stays below `rebind()`'s quarantine threshold, and therefore below the point at which a
re-parse stops carrying its ids.

Set by 13-quality.md section 13.4. Its consumer lives in the kit, not in core.
"""

MAX_REDUCTION_BYTES: int = 262_144
"""256 KiB per Reduction file — `Q-G2`'s cap, and the **binding** constraint on `outline` and
`pages`.

The 500-page suppression rule is only a pre-check. It implies about 1,190 committed pages for a
`pages` file and about 2,730 committed blocks — 23 to 46 pages — for an `outline` file. A reduction
over the cap is **suppressed with its count recorded**, never truncated.

Set by 13-quality.md section 13.4.
"""

MAX_CASSETTE_BYTES: int = 262_144
"""256 KiB: one committed Cassette. The same number as `MAX_REDUCTION_BYTES`, reused deliberately —
both are committed artefacts a human must be able to diff.

Set by 13-quality.md section 13.4.
"""

MAX_CASSETTE_BYTES_TOTAL: int = 33_554_432
"""32 MiB: the whole Cassette store, sized to sit inside Tier A's 64 MB rather than beside it.

Set by 13-quality.md section 13.4.
"""

MAX_PARTIAL_FRAC: float = 0.02
"""Above this share of missing verdicts, a `partial` run's affected metrics become `unknown`.

`unknown` is what `ow eval release-check` refuses on, which is why `SKIP` is not a state anywhere in
13-quality.md.

Set by 13-quality.md section 13.4.
"""
