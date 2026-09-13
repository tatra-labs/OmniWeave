"""The one `cache_key()`, the five layers, the six-clause read policy and the two GC sweeps.

02-architecture.md section 2 row 18 is this module's charter, and its exclusion is the sentence the
whole design turns on:

> | 18 | Cache | `omniweave_core.cache` | the one `cache_key()`; `CacheIndex`; `CacheLayer`
> (`blob`, `call`, `embed`, `render`, `signal`); `CacheVerdict`; the six-clause read policy;
> `put(entries, allowed_units=...)` with a runner-supplied allowlist | **being the record of
> completion** -- that is `work.status='done'` plus a matching `work.cache_key`. There is no `parse`
> or `derive` layer: if it is worth keeping it is a row | T-SCHEMA |

16-roadmap.md:544 schedules it as P4 W4.4. 08-runtime.md Part 4 opens by calling itself a
specification -- *"a reviewer may reject a PR that adds a key input, removes one, or reorders the
canonical groups without amending section 4.2's table"* -- so section 4.2's eleven rows are
transcribed here field by field and `test_cache.py` reads that table back out of the document.

**Nothing here runs.** The statements and the policy are here; `omniweave_core.store.cache` submits
them. Same boundary as `work.py` and `budget.py`, for the same reason.

## What is in the key, and what is deliberately not

The eleven inputs are in `cache_key()`. The absences are the part a reader gets wrong, so they are
asserted rather than described: `policy_digest` and `pricebook_digest` are **decision**-key inputs
and never artefact-key inputs, because repricing must not re-bill; `config_digest` is excluded
because it holds `runtime.**`, `store.**` and `observe.**`, so raising `max_workers` would re-bill
the corpus (I26); geometry is excluded so a parse driver's bbox jitter re-bills nothing;
`drivers.enabled` is excluded because which driver runs is already in the key through `producer.*`,
and classifying an allowlist as semantic would re-bill a corpus every time an operator enabled an
unrelated driver. And the wall clock, the run id, the generation, the hostname and `PYTHONHASHSEED`
are excluded for the reason that needs no argument.

Three inputs are **conditional**, and each condition is a cost decision:

* `producer.code_fingerprint` only when **not** `billed_api` -- including it for a billed driver
  re-bills a corpus on every refactor; excluding it for free work is graphify's
  `_EXTRACTOR_VERSION = "unknown"`, where every version of an extractor shares one namespace.
* `producer.deps_digest` only when **free** -- a pdfium or tokenizer bump changes free output with
  no source change, and the lockfile digest would invalidate the whole free tier on every unrelated
  dependency bump (F26).
* `config.digest_recipe` only when the operator **consumes Blocks** -- including it unconditionally
  makes a recipe bump invalidate parse `call` entries that never saw a digest.

## Three gaps this cell found

**D143** -- `08:1352`'s `unit_salt(unit: UnitRef, roots)` reads `unit.connector`,
`unit.walked_path` and `unit.locator`. `UnitRef` has five fields and none of them is any of those;
`unit.connector` is a roster **column**, and `walked_path` and `locator` appear nowhere in the
framework -- no column, no field, no second mention. `unit_salt()` here takes the three values
explicitly.

**D144** -- `consumes_blocks(ident)` is called once, at `08:1331`, and defined nowhere.
`CONSUMES_BLOCKS` below is a declared table over the five Ports and the five `op.*` steps, with the
rule stated.

**D145** -- `CacheVerdict` is named as seven members in prose (`08:1441`) and printed as a type
nowhere, and `CacheEntry` is named in `put()`'s signature and printed nowhere. Both are minted here
against the `cache_index` columns, which is the only other description of their contents.

Stdlib plus two intra-core imports (INV-2, G1). No `sqlite3`.

Tier T-SCHEMA: 02-architecture.md section 2 row 18.

Specified in 02-architecture.md section 2 row 18, 08-runtime.md Part 4 (:1261-1592) and
`0004_runtime.sql:155-183`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from posixpath import relpath
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Protocol, TypeAlias

from omniweave_core.canonical import sha256_canonical

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping, Sequence

    from omniweave_ports.types import UnitRef

    from omniweave_core.canonical import JsonValue
    from omniweave_core.drivers.card import DriverCard
    from omniweave_core.operator import OperatorIdentity, RunContext

__all__ = [
    "AGE_SWEEP_SQL",
    "CACHE_INDEX_COLUMNS",
    "CACHE_RECIPE_KEY",
    "CONSUMES_BLOCKS",
    "DEFAULT_CACHE_RECIPE",
    "GC_DEFAULT_DAYS",
    "GROWTH_BOUND_WORDS",
    "IN_CHUNK",
    "MAX_BYTES_UNBOUNDED",
    "NEVER_SWEEP_DAYS",
    "SIZE_SWEEP_SQL",
    "UPSERT_SQL",
    "BatchIndex",
    "BlobCheck",
    "CacheEntry",
    "CacheHit",
    "CacheIndex",
    "CacheLayer",
    "CacheProbe",
    "CacheVerdict",
    "Nonempty",
    "Repricer",
    "UnitKey",
    "cache_key",
    "cache_ns",
    "chunked",
    "consumes_blocks",
    "keys_for",
    "probe",
    "read_verdict",
    "reject_unallowed",
    "same_namespace",
    "unit_salt",
]


# ---------------------------------------------------------------------------------------------
# 1. The five layers, and why there are not seven.
# ---------------------------------------------------------------------------------------------


class CacheLayer(StrEnum):
    """The five `cache_index.layer` values. 0004_runtime.sql:158, 08:1265-1273.

    **`CacheLayer`, never `Layer`** -- the DDL says so in a comment, because `Layer` is L2's Block
    layer (charter section 5 X38) and one name over two closed domains is a bug that type-checks.

    **There is no `parse` layer and no `derive` layer**, and the absence is INV-1: *"if it is a row
    in the `.owstore` it is never also a blob in the cache."* The parse memo is three facts already
    in the store -- `work.status='done'`, a matching `work.cache_key`, and `doc(doc_key, gen)`
    present. 08:1276-1280 records what the earlier five-tier design cost: *"a re-derivation at a new
    `producer.schema_version` re-billed every VLM page, because the only record of that response was
    a block row."*

    `CALL` is the layer the framework is built around. It holds the driver's **raw response**, so a
    re-derivation within one store costs CPU-seconds instead of a re-bill -- on the reference corpus
    116,400 pages x 853 micros, about **$99 per re-derivation**. It does not cross stores:
    `cache_index` is created inside the `.owstore`, so a fresh store opens empty and every
    `billed_api` response is billed again.
    """

    BLOB = "blob"
    """Acquired source bytes for a non-`fs` connector; retained `part` bytes. 40 KB - 200 MB."""
    CALL = "call"
    """A driver invocation's raw response. The decisive layer; `[cache.max_bytes] call = 0`."""
    EMBED = "embed"
    """Vectors for a `(model_key, text_digest)`. An embedder is the second most expensive thing."""
    RENDER = "render"
    """Rasterised pages. 10.7 MB per 192-DPI A4 page, which is why rendering follows routing."""
    SIGNAL = "signal"
    """Computed `route_signal` values. The decision is microseconds; its 96-DPI raster is not."""


class CacheVerdict(StrEnum):
    """*"'Cache hit' is a **policy**, not a lookup"* -- 08:1439-1441's seven members. **D145**.

    The plan names all seven in one prose line and prints no type, so this is their first
    declaration. Six of the seven are the read policy's clauses; `HIT` is the seventh and is what a
    lookup returns when no clause fires.

    Every one is counted. 08:1454 makes that the point: *"all six are counted, and
    `graph_observation` carries the five distinct miss shapes per `(run, pass, lane)` so 'is the
    cache working' is a query rather than a feeling."* graphify reported vintage, corruption and
    re-bill through `warnings.warn(RuntimeWarning)` -- filterable, unstructured and invisible under
    JSON logging.
    """

    HIT = "hit"
    MISS = "miss"
    """Clause 1: no entry."""
    MISS_CORRUPT = "miss_corrupt"
    """Clause 2: the blob does not parse, or its sha256 does not match `ref`. Self-healing."""
    MISS_PARTIAL = "miss_partial"
    """Clause 3: `partial = 1` and the caller did not pass `allow_partial`."""
    MISS_EMPTY = "miss_empty"
    """Clause 4: the decoded artefact fails the operator's `is_valid_nonempty`."""
    MISS_UNIT_MISMATCH = "miss_unit_mismatch"
    """Clause 5: the recorded `(unit_uri, unit_part)` is not the one asked for. A **bug report**."""
    HIT_LEGACY = "hit_legacy"
    """Clause 6: an older namespace, legacy reads allowed. Reported per run, with the count."""


MISS_VERDICTS: Final[tuple[CacheVerdict, ...]] = (
    CacheVerdict.MISS,
    CacheVerdict.MISS_CORRUPT,
    CacheVerdict.MISS_PARTIAL,
    CacheVerdict.MISS_EMPTY,
    CacheVerdict.MISS_UNIT_MISMATCH,
)
"""The five distinct miss shapes `graph_observation` carries per `(run, pass, lane)`. 08:1454."""


# ---------------------------------------------------------------------------------------------
# 2. `cache_key()` -- the composition, field by field. 08:1310-1348.
# ---------------------------------------------------------------------------------------------

CACHE_RECIPE_KEY: Final = "cache.recipe"
"""The config key holding `k`. **A bump namespaces; it never deletes** (08:1335).

Deleting on a recipe bump would discard `billed_api` entries an operator paid for, which is the
same asymmetry `cache_ns()` encodes and the same one I27's partial index makes structural.
"""

DEFAULT_CACHE_RECIPE: Final = 1
"""`omniweave.toml.example`'s `[cache] recipe = 1`. Read from config; this is the shipped value."""

CONSUMES_BLOCKS: Final[Mapping[str, bool]] = MappingProxyType(
    {
        "acquire": False,
        "parse": False,
        "derive": True,
        "embed": True,
        "compile": True,
        "op.identify": False,
        "op.converge": False,
        "op.lexicon": True,
        "op.resolve": True,
        "op.cluster": True,
    }
)
"""Which operators read Blocks, and therefore whose key carries `DIGEST_RECIPE`. **D144.**

`consumes_blocks(ident)` is called once in the plan, at 08:1331, and defined nowhere. The rule this
table applies is 08:1347's own justification read as a definition: `digest_recipe` is in the key
*"only if the operator consumes Blocks"*, because *"a digest-definition change moves every
`content_digest` a derive pass reads"* -- so the question is whether the operator's **input** is a
Block, not whether its output is one.

By that rule `acquire` and `parse` are out: `acquire` reads bytes and `parse` **produces** Blocks
from bytes. `derive`, `embed` and `compile` are in, because all three read committed Block rows.
Of the five `op.*` steps, `op.identify` reads a container's structure before any Block exists and
`op.converge` reads `dep` rows and digests rather than content; the three graph passes
(`op.lexicon`, `op.resolve`, `op.cluster`) read Blocks and segments.

Keyed by the operator's **first** segment for a Port operator (`'<port>.<family>'`) and by the whole
name for an `op.*` step, which is the grain 08:1341 fixes for `producer.operator`. Reported as a
gap; a third party cannot add an entry, and does not need to, because *"nobody outside core writes
an Operator"* (08:1896).
"""


def consumes_blocks(operator: str) -> bool:
    """Whether `DIGEST_RECIPE` belongs in this operator's cache key. **D144**, table above."""
    if operator in CONSUMES_BLOCKS:
        return CONSUMES_BLOCKS[operator]
    port = operator.split(".", 1)[0]
    if port in CONSUMES_BLOCKS:
        return CONSUMES_BLOCKS[port]
    raise ValueError(
        f"{operator!r} is neither '<port>.<family>' for a known Port nor one of the five op.* "
        f"steps, so whether it consumes Blocks is undeclared (see CONSUMES_BLOCKS)"
    )


def unit_salt(
    connector: str, *, walked_path: str = "", locator: str = "", source_root: str = ""
) -> str:
    """`content.salt` -- 08:1349-1362, with the three inputs passed rather than read. **D143**.

    The plan prints `unit_salt(unit: UnitRef, roots: Roots)` and reads `unit.connector`,
    `unit.walked_path` and `unit.locator` off it. `UnitRef` has five fields -- `uri`, `part`,
    `content_sha256`, `byte_len`, `media_type` -- and its docstring explains why it is that narrow:
    *"the host mints every durable identity, which is what makes a fragment portable between
    stores."* `connector` is a `unit` roster column; `walked_path` and `locator` are named nowhere
    else in the framework. So the values are arguments here and the caller is the runner, which is
    the only component that has all three.

    **The `fs` branch uses the WALKED path and not `realpath`'s output**, and 08:1364 is emphatic:
    *"two symlink aliases of one file are two units with two salts and two cache entries, because a
    corpus that lists a document twice under two names has two documents as far as citation is
    concerned."* That is also why the path cannot be recovered from `unit_uri` -- `canonical_uri()`
    has already applied realpath, which destroys exactly the distinction the salt preserves. It is
    the sharpest statement of D143: the roster stores the resolved path and the salt needs the
    unresolved one.

    Relative to `roots.source` and POSIX-separated, so *"the same unit in two checkouts is one cache
    entry"* -- an absolute path would destroy portability across checkouts, which is why
    `roots.source` is classified `operational` rather than `semantic`.
    """
    if connector == "fs":
        if not walked_path or not source_root:
            raise ValueError(
                "an fs unit's salt is its walked path relative to roots.source; both are required"
            )
        return relpath(walked_path.replace("\\", "/"), source_root.replace("\\", "/"))
    if not locator:
        raise ValueError(
            f"a {connector!r} unit's salt is '<connector>/<locator>' and the locator is empty"
        )
    return f"{connector}/{locator}"


def cache_key(
    unit: UnitRef,
    ident: OperatorIdentity,
    card: DriverCard | None,
    ctx: RunContext,
    *,
    salt: str,
    recipe: int = DEFAULT_CACHE_RECIPE,
) -> str:
    """08:1316-1332, transcribed. One function, and every `cache_key` column holds its output.

    `salt` is a keyword argument rather than a `unit_salt(unit, ctx.roots)` call inside, for D143's
    reason: the three values that salt needs are not on `UnitRef` and not on `RunContext`. `recipe`
    likewise comes from `[cache] recipe` through the caller's config rather than from a module
    constant, because a constant would make the knob a lie.

    `card.identity.schema_version` and not `card.schema_version`: the plan writes the short form
    and `DriverCard` nests the `[driver]` table as `DriverIdentity`, which is where `id`, `port`,
    `version`, `schema_version`, `granularity` and `replay_class` live. A nesting difference, not a
    disagreement -- and it is checked, because the value reaches this function through a card the
    tests parse from real TOML rather than through a stub.

    The three canonical groups -- `content`, `producer`, `config` -- and their order are part of the
    specification: 08:1263 says a PR that reorders them without amending the table is rejectable.
    `sha256_canonical` is what turns the mapping into bytes, and **it** is part of the
    specification too (08:1375-1381): sorted keys, `allow_nan=False`, three distinct encodings for
    absent / null / the empty string, and no `str()` fallback ever -- a `str()` fallback yields
    address-bearing reprs and therefore a permanent silent 100% cache miss (I12).

    **`card=None` is the `op.*` row, and it is one recipe rather than two. D164.** `work.cache_key`
    is `TEXT NOT NULL` on every row (`0004_runtime.sql:97`) and five operators -- `op.identify`,
    `op.converge`, `op.lexicon`, `op.resolve`, `op.cluster` -- have no card at all: 04-driver-
    system.md:2580 files them as *"core-only Operators"* whose `work` rows carry NULL `decision_id`,
    `driver` and `dispatch_key`, and a card is a `driver.toml` a core operator does not have. The
    three values this function reads off a card are all knowable without one, so `None` supplies
    them rather than branching to a second recipe: `cost_class` is `free` (08:2307 names four of the
    five and `op.cluster` is `local_compute`, which changes neither `cheap` nor `free` here),
    `schema_version` is `ident.op_version` -- the same integer, and 03:396's `Producer` is the same
    type under L5's name -- and `deps_digest` is absent, because a core operator has no third-party
    dependency set to pin. The body's three groups and their key order are untouched, which is what
    keeps 08:1263's *"a PR that reorders them without amending the table is rejectable"* true of the
    `op.*` row as well.
    """
    free = card is None or (card.cost_model is not None and card.cost_model.cost_class == "free")
    cheap = card is None or card.cost_model is None or card.cost_model.cost_class != "billed_api"
    digest_recipe: int | None = None
    if consumes_blocks(ident.operator):
        from omniweave_core.archive.manifest import DIGEST_RECIPE  # noqa: PLC0415 -- see below.

        # Imported here and not at module scope: `DIGEST_RECIPE` is `omniweave_core.archive`'s,
        # which is one of the nine LAZY names (11-repo-layout.md section 1.3) and is the whole
        # `.owdoc` codec. A module-level import would put that package on the path of every
        # cache-key computation, which happens once per unit per operator. The same device
        # `config.py`'s two cross-module shims use, and for the same reason: it keeps G17 true.
        digest_recipe = DIGEST_RECIPE

    body: dict[str, JsonValue] = {
        "k": recipe,
        "content": {
            "digest": unit.content_sha256,
            "salt": salt,
            "part": unit.part or "",
        },
        "producer": {
            "operator": ident.operator,
            "schema_version": ident.op_version if card is None else card.identity.schema_version,
            "code_fingerprint": ident.code_fingerprint if cheap else None,
            "deps_digest": None if card is None else (card.deps.digest if free else None),
        },
        "config": {
            "driver": ident.options_digest.hex(),
            "run": ctx.semantic_digest,
            "digest_recipe": digest_recipe,
        },
    }
    return sha256_canonical(body)


# ---------------------------------------------------------------------------------------------
# 3. Namespacing -- two tiers, chosen by who pays for a miss. 08:1420-1437.
# ---------------------------------------------------------------------------------------------


def cache_ns(
    cost_class: str, *, operator: str, op_version: int, code_fingerprint: str, config_digest: str
) -> str:
    """The namespace a cache entry is pruned within. Three shapes, two tiers. 08:1422-1424.

    ```
    FREE          op/<operator>/v<op_version>-c<code_fingerprint>/
    LOCAL_COMPUTE op/<operator>/v<op_version>-c<code_fingerprint>/cfg/<config_digest>/
    BILLED_API    cfg/<config_digest>/
    ```

    **A `billed_api` namespace is keyed on config alone**, and the asymmetry is graphify's
    (`cache.py:1179`, `prune_semantic_cache`) read as a correction rather than a quirk: *"two hosts
    with different prompts sharing one output directory must not each delete the other's entries and
    re-bill extraction on every alternation."* A billed namespace that also carried the code
    fingerprint would be swept apart by two developers on one machine.

    The enforcement is not this string. I27 is the `cache_ns` **partial index**, declared `WHERE
    cost_class='free'`, so the automatic sweep's query cannot see a billed row at all -- structural,
    not a policy. Deleting one needs `ow cache prune --allow-rebill`, which prints the row count and
    the `would_have_been_micros` it is about to discard. `--ignore-cache` is **struck**: it named
    the whole five-layer index, which made it an unnamed authorisation to re-bill.
    """
    if cost_class == "billed_api":
        return f"cfg/{config_digest}/"
    stem = f"op/{operator}/v{op_version}-c{code_fingerprint}/"
    if cost_class == "free":
        return stem
    if cost_class == "local_compute":
        return f"{stem}cfg/{config_digest}/"
    raise ValueError(f"{cost_class!r} is not one of the three CostClass members")


GROWTH_BOUND_WORDS: Final = "live units x configurations seen"
"""What `ow cache stat` prints, **in these words**. 08:1426.

16-roadmap.md:544 makes the phrasing an acceptance criterion for W4.4 rather than a nicety: the
growth bound is what an operator uses to predict a disk, and a paraphrase that said "entries" or
"documents" would describe a different quantity.
"""


# ---------------------------------------------------------------------------------------------
# 4. `CacheEntry` -- one `cache_index` row. **D145**.
# ---------------------------------------------------------------------------------------------

CACHE_INDEX_COLUMNS: Final[tuple[str, ...]] = (
    "cache_key",
    "recipe",
    "layer",
    "cost_class",
    "ref",
    "bytes",
    "unit_uri",
    "unit_part",
    "driver",
    "driver_schema_v",
    "config_digest",
    "origin_operator",
    "spend_json",
    "micros",
    "partial",
    "created_ns",
    "last_hit_ns",
    "hits",
)
"""`cache_index`'s eighteen columns, in the DDL's order (0004_runtime.sql:155-170)."""


@dataclass(frozen=True, slots=True)
class CacheEntry:
    """One `cache_index` row. **D145**: `put()`'s signature names the type and prints no fields.

    **Every row carries the `Spend` that produced it and its price at creation** (08:1307). A hit
    *"replays the Spend and re-prices it from the current `PriceBook`, which is the only way to do
    cost accounting when 90% of calls are hits, and the only source of
    `cost.would_have_been_micros_if_uncached`."* `spend_json` is canonical JSON and carries **no
    currency** (INV-15); `micros` beside it is the price at creation and is re-derived on every hit.

    `unit_uri` and `unit_part` are on the row for read-policy clause 5, which is the only clause
    that is a bug report rather than a miss: a recorded unit that is not the one asked for means a
    key collision or a poisoned write.

    `ref` is a `cas://ab/cd/<sha256>` reference into `omniweave_core.blobs`' CAS, and the bytes live
    there exactly once. 08:1294-1302 answers the INV-1 objection about the `render` layer: the
    `page_render` table is the *lookup* path and `cache_index` at `layer='render'` is the
    *accounting and GC* path, which is two indexes over one representation rather than two
    representations.
    """

    cache_key: str
    layer: CacheLayer
    cost_class: str
    ref: str
    bytes: int
    unit_uri: str
    unit_part: str
    driver: str
    driver_schema_v: int
    config_digest: str
    origin_operator: str
    spend_json: str
    micros: int
    partial: bool = False
    recipe: int = DEFAULT_CACHE_RECIPE
    hits: int = 0

    def __post_init__(self) -> None:
        """The DDL's two CHECKs, plus the width rule `work.cache_key` has no CHECK for."""
        if self.layer not in tuple(CacheLayer):
            raise ValueError(f"{self.layer!r} is not one of the five CacheLayer members")
        if self.cost_class not in ("free", "local_compute", "billed_api"):
            raise ValueError(f"{self.cost_class!r} is not one of the three CostClass members")
        if len(self.cache_key) != _CACHE_KEY_HEX_LEN:
            raise ValueError("cache_key is the 64-char hex output of cache_key()")
        if self.bytes < 0 or self.micros < 0:
            raise ValueError("bytes and micros are quantities")


_CACHE_KEY_HEX_LEN: Final = 64
"""`sha256_canonical` hex. The same number `omniweave_core.operator.CACHE_KEY_HEX_LEN` holds.

Private and duplicated on purpose, which is the one place in this file that needs the argument: a
module-level `from omniweave_core.operator import CACHE_KEY_HEX_LEN` would make every cache import
pull the runner's vocabulary and, through it, `omniweave_core.model`. `test_cache.py` asserts the
two are equal, so the duplication is checked rather than trusted -- and both are `len(sha256 hex)`,
which is a property of the algorithm rather than a decision either module owns.
"""


def reject_unallowed(
    entries: Sequence[CacheEntry], allowed_units: frozenset[tuple[str, str]]
) -> tuple[CacheEntry, ...]:
    """The poisoning allowlist. 08:1465-1478. Returns the entries that are **not** allowed.

    `allowed_units` is *"runner-supplied, never driver-supplied"* and is the set of
    `(unit_uri, unit_part)` pairs in the Batch just dispatched. This makes I13 structural rather
    than a review rule, and **the second half of the mechanism is that `DriverIO` carries no cache
    handle at all** -- a driver cannot write to the cache even incorrectly.

    The threat is concrete and graphify names it (`cache.py:1385`, issue #1757): *"semantic nodes
    can legitimately mention another corpus file, but a model must not be able to replace that
    file's complete cache entry unless the file was part of the current extraction batch."* An LLM
    enrichment pass handed pages 12-14 of one document must not be able to replace the parse record
    of a document it was never given.

    Returns the rejects rather than raising, because 08:1469 says an offending entry is *"rejected
    and recorded"*: the write proceeds for the entries that are allowed, and the rejects are
    counted. A raise would let one poisoned entry discard a Batch's worth of legitimate ones.
    """
    return tuple(
        entry for entry in entries if (entry.unit_uri, entry.unit_part) not in allowed_units
    )


# ---------------------------------------------------------------------------------------------
# 5. The read policy -- six clauses, in order. 08:1439-1458.
# ---------------------------------------------------------------------------------------------


def read_verdict(
    entry: CacheEntry | None,
    *,
    asked_for: tuple[str, str],
    blob_ok: bool = True,
    nonempty: bool = True,
    allow_partial: bool = False,
    in_current_namespace: bool = True,
    allow_legacy: bool = False,
) -> CacheVerdict:
    """The six clauses, evaluated in the plan's order. *"A hit is a policy, not a lookup."*

    The order is the specification. Clause 2 precedes clause 4 because an artefact that does not
    parse cannot be asked whether it is empty; clause 5 precedes clause 6 because a unit mismatch
    is a bug report and must not be reported as a vintage; and clause 3 precedes clause 4 because a
    `partial` entry that is also empty is refused for the reason the caller can act on.

    **Clause 2 is self-healing with no flag.** A corrupt entry is counted into
    `manifest.cache.corrupt_entries` *"and overwritten on the next success"*; graphify re-billed a
    corrupt entry every run until #2405 counted it. **Clause 6 exists because dropping
    pre-fingerprinting entries would re-bill a whole corpus**, and it is reported per run -- *"this
    corpus may mix extraction vintages"* -- with the count.

    The caller supplies the facts this function cannot compute: whether the blob parses and its
    digest matches (`blob_ok`), whether the decoded artefact passes the operator's
    `is_valid_nonempty` (`nonempty`), and whether the entry is in the current namespace. Each is a
    question only the caller's layer can answer, and a policy that tried to answer them would need
    a blob store, a codec and an Operator.
    """
    if entry is None:
        return CacheVerdict.MISS
    if not blob_ok:
        return CacheVerdict.MISS_CORRUPT
    if entry.partial and not allow_partial:
        return CacheVerdict.MISS_PARTIAL
    if not nonempty:
        return CacheVerdict.MISS_EMPTY
    if (entry.unit_uri, entry.unit_part) != asked_for:
        return CacheVerdict.MISS_UNIT_MISMATCH
    if not in_current_namespace:
        return CacheVerdict.HIT_LEGACY if allow_legacy else CacheVerdict.MISS
    return CacheVerdict.HIT


# ---------------------------------------------------------------------------------------------
# 6. Size bounds and GC -- three mechanisms, and the first alone bounds nothing. 08:1485-1540.
# ---------------------------------------------------------------------------------------------

NEVER_SWEEP_DAYS: Final = 0
"""`[cache] gc.billed_after_days = 0` means **never**, not immediately. 08:1502."""

MAX_BYTES_UNBOUNDED: Final = 0
"""`[cache.max_bytes] call = 0` means **unbounded**, and it is a decision rather than an oversight.

08:1521: a layer whose bound is `0` is skipped by the size sweep entirely, *"because those are the
two layers where a miss costs money"*. The `call` layer's only bound is then the disk-headroom
refusal, and `ow cache stat` prints its size beside the free-disk figure so the operator sees it
coming.
"""

GC_DEFAULT_DAYS: Final[Mapping[str, int]] = MappingProxyType(
    {"free_after_days": 7, "local_after_days": 90, "billed_after_days": NEVER_SWEEP_DAYS}
)
"""`omniweave.toml.example`'s `[cache] gc`, transcribed. 08:1502."""

UPSERT_SQL: Final = """
INSERT INTO cache_index(
    cache_key, recipe, layer, cost_class, ref, bytes, unit_uri, unit_part,
    driver, driver_schema_v, config_digest, origin_operator, spend_json, micros,
    partial, created_ns, last_hit_ns, hits)
VALUES(:cache_key, :recipe, :layer, :cost_class, :ref, :bytes, :unit_uri, :unit_part,
       :driver, :driver_schema_v, :config_digest, :origin_operator, :spend_json, :micros,
       :partial, :now_ns, :now_ns, :hits)
ON CONFLICT(cache_key) DO UPDATE SET
    ref=excluded.ref, bytes=excluded.bytes, spend_json=excluded.spend_json,
    micros=excluded.micros, partial=excluded.partial, last_hit_ns=excluded.last_hit_ns
"""
"""A write, and an **overwrite** on conflict, because two read clauses require one.

Clause 2 says a corrupt entry is *"overwritten on the next success -- self-healing with no flag"*
and clause 4 says the same of an empty one. A plain `INSERT` would raise on the primary key and an
`INSERT OR IGNORE` would leave the corruption in place forever, which is graphify's behaviour
before #2405: it re-billed a corrupt entry every run.

`created_ns` is deliberately **not** in the `DO UPDATE SET` list: an overwrite replaces the bytes
and the price, and the row keeps the age the GC sweeps on. `hits` is likewise untouched, so a
self-heal does not reset a popular entry's history.
"""

AGE_SWEEP_SQL: Final = """
DELETE FROM cache_index
 WHERE cost_class = :cost_class
   AND last_hit_ns < :now_ns - :after_days * 86400000000000
   AND cache_key NOT IN (SELECT cache_key FROM work WHERE status IN ('pending','claimed'))
"""
"""08:1493-1499's age sweep, verbatim, one query per layer's cost class. Index: `cache_gc`.

**The `NOT IN` subquery is the concurrency answer** and both sweeps carry it: a key referenced by a
live `work` row is never swept, so *"a concurrently-claimed unit's memo is never swept out from
under it"* (08:1536). A hit on a row deleted between probe and read is clause 2 and self-heals.

`86400000000000` is nanoseconds per day written out, because `last_hit_ns` is nanoseconds and a
`* 86400 * 1000000000` in SQL is three chances to drop a zero.
"""

SIZE_SWEEP_SQL: Final = """
WITH ordered AS (
  SELECT cache_key, bytes,
         SUM(bytes) OVER (ORDER BY last_hit_ns DESC, cache_key) AS running
    FROM cache_index
   WHERE layer = :layer AND cost_class <> 'billed_api'
     AND cache_key NOT IN (SELECT cache_key FROM work WHERE status IN ('pending','claimed')))
DELETE FROM cache_index WHERE cache_key IN (SELECT cache_key FROM ordered WHERE running > :bound)
"""
"""08:1510-1519's size sweep, verbatim. **This is what actually enforces `[cache.max_bytes]`.**

08:1507 states why age alone ships nothing: *"at 10.7 MB per rendered page, one 2,000-page ingest
puts 21 GB in the `render` layer inside its `local_after_days = 90` window and blows straight past
`render = 20 GiB`."*

LRU by `last_hit_ns` **descending** with a running sum, so the rows kept are the most recently
touched and everything past the bound goes. `cost_class <> 'billed_api'` is I27 again, spelled in
the statement as well as in the index: *"an automatic sweep NEVER re-bills."*
"""


# ---------------------------------------------------------------------------------------------
# 6. The batch cache-check -- hits PLUS the outstanding work list. 08:1760-1800.
# ---------------------------------------------------------------------------------------------


IN_CHUNK: Final = 900
"""How many keys ride in one `WHERE cache_key IN (...)`. 08:1793.

*"the `IN` list is chunked at 900 to stay under SQLite's `SQLITE_MAX_VARIABLE_NUMBER` floor."*
The floor and not the ceiling: 3.32 raised the compiled default to 32,766, but a distribution may
build with the historic 999 and the value is not queryable from `sqlite3` without
`SQLITE_LIMIT_VARIABLE_NUMBER`, which the stdlib module does not expose. 900 leaves room for the
statement's own bound parameters and is one number rather than a per-build probe.
"""


def chunked(keys: Sequence[str], size: int = IN_CHUNK) -> Iterator[tuple[str, ...]]:
    """`keys` in runs of at most `size`, in order. The `IN`-list bound, as an iterator.

    An iterator rather than a list of lists because the caller executes each chunk as it arrives
    and a 100k-key probe should not materialise its own partition first.
    """
    if size < 1:
        raise ValueError("a chunk holds at least one key")
    for start in range(0, len(keys), size):
        yield tuple(keys[start : start + size])


UnitKey: TypeAlias = tuple[str, str]
"""`(unit_uri, unit_part)`. 08:2856, and the key `allowed_units` and `verdicts` already use.

The glossary calls it *"the pair that keys the pending set, the cache write allowlist and the
per-part retry semaphore. Not a `UnitRef`, which additionally carries `content_sha256`, the
connector and the walked path."* Declared here rather than in `omniweave_ports.types` because it is
not a wire type: no driver ever sends or receives one, and `reject_unallowed()` above has been
spelling it `tuple[str, str]` since this cell's first half.
"""


class BatchIndex(Protocol):
    """`CacheIndex` plus the one read `08:1791` requires. **D170.**

    *"One indexed query per Batch, not one per unit ... the caller never issues N lookups."*
    `CacheIndex.get(key)` cannot express that, and `02-architecture.md` row 18's boundary cell --
    `CacheIndex.get/put` -- names no batch read. A separate Protocol rather than a sixth method on
    `CacheIndex`, so that a caller who only needs a lookup still declares only a lookup, and so the
    widening is visible at the type rather than buried in a method list.
    """

    def get_many(self, keys: Sequence[str]) -> Mapping[str, CacheEntry]:
        """Every row among `keys` that exists, by key. Absent keys are absent from the mapping."""
        ...


BlobCheck: TypeAlias = "Callable[[CacheEntry], bool]"
"""Clause 2: does the blob parse, and does its sha256 match `ref`? 08's table, row 2.

A callable because the answer needs a blob store and a codec, and `08:1439`'s whole point is that
the six clauses are *"the cache's business"* while these two facts are not computable from a
`cache_index` row. `omniweave_core.blobs` could answer the digest half here, but not the parse
half -- that is the layer's codec -- so both travel together as one question the caller owns.
"""

Nonempty: TypeAlias = "Callable[[CacheEntry], bool]"
"""Clause 4: does the decoded artefact pass the operator's `is_valid_nonempty`? 08's table, row 4.

`Operator.is_valid_nonempty(ref)` is `08:245-249`'s *"There is no empty success"* on the read path,
and `omniweave_core.operator.Operator` is a Protocol this module must not import: `cache.py` is on
the path of every key computation and `operator.py` opens the runner's whole vocabulary.
"""

Repricer: TypeAlias = "Callable[[str], int]"
"""`spend_json -> micros`, at the **current** `PriceBook`. INV-15's one indirection.

`08:1307`: a hit *"replays the Spend and re-prices it from the current `PriceBook`, which is the
only way to do cost accounting when 90% of calls are hits, and the only source of
`cost.would_have_been_micros_if_uncached`."* `PriceBook` and `Spend.micros(book)` live in
`omniweave.route.spend`, which `tools/layers.toml` forbids core from importing -- the same wall
`StepMetrics.spend` hit at D139. So the re-pricing arrives as a callable and `cache_index.micros`
(the price at creation) is the fallback when no caller supplies one.
"""


def same_namespace(entry: CacheEntry, *, driver: str, driver_schema_v: int, recipe: int) -> bool:
    """Clause 6's namespace test, against the tuple the **index** is built on. **D171.**

    `08:1424` is explicit that the string `cache_ns()` returns is not what enforces anything:
    *"The enforcement is not this string. I27 is the `cache_ns` **partial index**, declared `WHERE
    cost_class='free'`, so the automatic sweep's query cannot see a billed row at all --
    structural, not a policy."* That index is
    `cache_ns ON cache_index(driver, driver_schema_v, recipe) WHERE cost_class='free'`, so the
    namespace a row actually belongs to is those three columns, and this is the comparison a
    pruning sweep makes.

    **It is not `cache_ns()`'s five inputs, and it cannot be.** That function takes
    `(cost_class, operator, op_version, code_fingerprint, config_digest)` and `cache_index` carries
    three of the five: `cost_class`, `origin_operator` and `config_digest`. `op_version` and
    `code_fingerprint` are on no column, so a row's `cache_ns()` string is not derivable from the
    row. Two namespaces, two tuples, one name. Recorded as **D171**; this is the index's.
    """
    return (
        entry.driver == driver
        and entry.driver_schema_v == driver_schema_v
        and entry.recipe == recipe
    )


_HIT_VERDICTS: Final[frozenset[CacheVerdict]] = frozenset(
    {CacheVerdict.HIT, CacheVerdict.HIT_LEGACY}
)
"""The two verdicts that answer a unit. Every other member leaves it outstanding.

The same pair `pipeline.HIT_VERDICTS` holds, and the duplication is deliberate for the reason
`_CACHE_KEY_HEX_LEN`'s is: importing it from `omniweave.run.pipeline` is the layer violation, and
importing it the other way would put the middleware's vocabulary on every key computation.
`test_cache.py` asserts the two are equal.
"""


@dataclass(frozen=True, slots=True)
class CacheHit:
    """One decoded hit inside a `CacheProbe`. 08:2852.

    *"the artefact ref, the replayed `Spend`, the re-priced `micros` and the `CacheVerdict` (`hit`
    or `hit_legacy`)."* `spend_json` rather than a `Spend`, for `Repricer`'s reason: the type lives
    in a distribution core may not import, and the row holds canonical JSON with **no currency**
    (INV-15), which is exactly what a re-pricer wants as input.

    `index` is the hit's position in the probed sequence, and it is what makes `08:1778`'s *"Order
    preserved"* a property of the record rather than of a convention: a caller widening a narrowed
    batch back to its original shape reads positions, not identities.
    """

    index: int
    key: str
    unit: UnitRef
    verdict: CacheVerdict
    ref: str
    bytes: int
    spend_json: str
    micros: int

    def __post_init__(self) -> None:
        if self.verdict not in _HIT_VERDICTS:
            raise ValueError(f"{self.verdict!r} is a miss; a CacheHit records a hit")
        if self.index < 0:
            raise ValueError("index is a position in the probed sequence")


@dataclass(frozen=True, slots=True)
class CacheProbe:
    """What ONE call over a claimed Batch returns. 08:1774-1781, field for field.

    The signature is the artefact, and `08:1762` says whose: graphify's
    `check_semantic_cache(...) -> (cached_nodes, cached_edges, cached_hyperedges, uncached_files)`
    -- *"One call returns reusable output **and** the remaining work."* The typed form keeps that
    property and adds the three the untyped one could not carry: which clause fired for every
    non-hit, the legacy count, and what the hits would have cost.

    **`hits` and `outstanding` partition the probed units.** `08:2110` states it as a property of
    the `call` span's attributes -- *"`cached` and `outstanding` sum to `units`"* -- and
    `__post_init__` enforces it, because a probe that lost a unit would dispatch a batch narrower
    than the work it was claimed for and the missing unit's `work` row would sit `claimed` until its
    lease expired.

    `queries` is not in the printed block. It is here because property 1 -- *"One indexed query per
    Batch, not one per unit"* -- is the reason this type exists at all, and a number a test can
    assert is the difference between a property and an intention.
    """

    hits: tuple[CacheHit, ...]
    outstanding: tuple[UnitRef, ...]
    verdicts: Mapping[UnitKey, CacheVerdict]
    legacy: int
    would_have_been_micros: int
    queries: int = 0

    def __post_init__(self) -> None:
        """08:2110's property 3, and the two counts that are derived rather than reported."""
        if len(self.hits) + len(self.outstanding) != len(self.verdicts):
            raise ValueError(
                f"{len(self.hits)} hits + {len(self.outstanding)} outstanding against "
                f"{len(self.verdicts)} verdicts: cached and outstanding sum to units (08:2110)"
            )
        counted = sum(1 for hit in self.hits if hit.verdict is CacheVerdict.HIT_LEGACY)
        if counted != self.legacy:
            raise ValueError(f"legacy says {self.legacy} and {counted} hits are hit_legacy")
        if self.would_have_been_micros != sum(hit.micros for hit in self.hits):
            raise ValueError("would_have_been_micros is the sum over hits at the current PriceBook")

    @property
    def misses(self) -> Mapping[CacheVerdict, int]:
        """Every non-hit verdict with its count. What `manifest.cache` and `graph_observation` read.

        `08:1453` wants the five distinct miss shapes per `(run, pass, lane)` so that *"is the cache
        working"* is a query rather than a feeling, and `08:1798` names the three manifest fields
        this feeds. Zeros are dropped: a shape that did not occur is absent, and the manifest's own
        `_ordered()` is what makes the reported map total.
        """
        counts: dict[CacheVerdict, int] = {}
        for verdict in self.verdicts.values():
            if verdict not in _HIT_VERDICTS:
                counts[verdict] = counts.get(verdict, 0) + 1
        return counts

    def ordered(self, units: Sequence[UnitRef]) -> tuple[CacheVerdict, ...]:
        """`verdicts` re-projected onto `units`' order, for a caller that thinks in positions.

        `08:1779` prints `verdicts` as a `Mapping[UnitKey, CacheVerdict]` and a middleware layer
        wants a tuple parallel to its batch -- `pipeline.CacheDecision` says so in its own
        docstring. One stored representation and one derived, rather than two stored: a mapping and
        a tuple that could disagree about one unit is the drift a probe exists to prevent.
        """
        return tuple(self.verdicts[(unit.uri, unit.part)] for unit in units)


def keys_for(
    units: Sequence[UnitRef],
    ident: OperatorIdentity,
    card: DriverCard | None,
    ctx: RunContext,
    *,
    salts: Sequence[str],
    recipe: int = DEFAULT_CACHE_RECIPE,
) -> tuple[str, ...]:
    """One `cache_key()` per unit, in order. The only place a probe's keys come from.

    `salts` is parallel to `units` and is required rather than derived, which is **D143**:
    `unit_salt()`'s three inputs are not on a `UnitRef` and the runner is the only component that
    holds all three. A `probe()` that computed its own salts would have to guess, and `08:1364`
    says what a guessed salt costs -- two symlink aliases of one file collapsing into one cache
    entry, and therefore into one document.
    """
    if len(salts) != len(units):
        raise ValueError(f"{len(salts)} salts against {len(units)} units; they are parallel")
    return tuple(
        cache_key(unit, ident, card, ctx, salt=salt, recipe=recipe)
        for unit, salt in zip(units, salts, strict=True)
    )


def _always(entry: CacheEntry) -> bool:
    """The default answer to clauses 2 and 4 for a caller with no blob store and no Operator.

    `True` and not `False`, because the two clauses are *refusals*: a caller that cannot check
    whether a blob parses has not thereby learned that it does not. A default of `False` would turn
    every hit into a `miss_corrupt` and silently disable the cache for anyone who had not wired both
    answerers -- which is the failure mode `manifest.cache.corrupt_entries` exists to make loud.
    """
    del entry
    return True


def probe(
    units: Sequence[UnitRef],
    keys: Sequence[str],
    *,
    index: BatchIndex,
    layer: CacheLayer,
    blob_ok: BlobCheck = _always,
    nonempty: Nonempty = _always,
    reprice: Repricer | None = None,
    in_namespace: Callable[[CacheEntry], bool] | None = None,
    allow_partial: bool = False,
    allow_legacy: bool = False,
) -> CacheProbe:
    """The batch cache-check: hits, the outstanding list, and which clause fired for every miss.

    `08:1783` prints the signature as
    `probe(units, ident, card, ctx, *, layer, allow_partial=False)`, and **three of the six read
    clauses cannot be evaluated from those four arguments**: the lookup needs a `CacheIndex`,
    clause 2 needs a blob store and a codec, and clause 4 needs the Operator's `is_valid_nonempty`.
    `RunContext` carries none of the three -- it has `roots`, `clock`, `cancel`, `admission`,
    `services`, `budget`, `events` and five digests, and `08:300-317` defends its having no store
    handle at length. So the index and the two answerers are parameters, and `keys` replaces
    `(ident, card, ctx)` because `keys_for()` is the one place a key is computed and its salts are
    D143's. Recorded as **D172**.

    `layer` *"is not a caller's choice"* (`08:1786`): `with_cache` passes the operator's layer from
    section 2.4's table and an operator with no layer never calls this at all. It is taken here to
    be recorded **and checked**: a row that matched the key but sits in another layer is a key
    collision, and it is reported as `miss_unit_mismatch` -- clause 5's shape one level up, which is
    the clause the plan calls *"a bug report"* rather than a miss.

    **Three properties a naive `get(key)` loop does not have** (`08:1789-1800`), each observable on
    the returned record:

    1. *"One indexed query per Batch"* -- `queries` counts the `IN` chunks, so a 256-unit batch
       reports `1` and a test can say so.
    2. *"`outstanding` is what gets dispatched"* -- a tuple of `UnitRef` in the probed order, and
       `hits` plus `outstanding` partition the batch.
    3. *"Every miss carries its clause"* -- `verdicts` covers every unit, and `misses` counts the
       five shapes that make `manifest.cache.corrupt_entries`, `legacy_vintage_hits` and
       `rebilled_units` computable.

    `reprice=None` falls back to `cache_index.micros`, the price at creation. That is the honest
    default rather than zero: a probe with no `PriceBook` still knows what the entry cost when it
    was written, and reporting `0` would make `would_have_been_micros_if_uncached` read as "the
    cache saved nothing" on exactly the runs where it saved the most.
    """
    if len(keys) != len(units):
        raise ValueError(f"{len(keys)} keys against {len(units)} units; they are parallel")
    distinct = tuple(dict.fromkeys(keys))
    rows = index.get_many(distinct) if distinct else {}
    queries = sum(1 for _ in chunked(distinct)) if distinct else 0

    hits: list[CacheHit] = []
    outstanding: list[UnitRef] = []
    verdicts: dict[UnitKey, CacheVerdict] = {}
    for position, (unit, key) in enumerate(zip(units, keys, strict=True)):
        entry = rows.get(key)
        asked = (unit.uri, unit.part)
        verdict = read_verdict(
            entry,
            asked_for=asked,
            blob_ok=entry is None or blob_ok(entry),
            nonempty=entry is None or nonempty(entry),
            allow_partial=allow_partial,
            in_current_namespace=entry is None or in_namespace is None or in_namespace(entry),
            allow_legacy=allow_legacy,
        )
        if verdict in _HIT_VERDICTS and entry is not None and entry.layer is not layer:
            verdict = CacheVerdict.MISS_UNIT_MISMATCH
        if verdict in _HIT_VERDICTS and entry is not None:
            hits.append(
                CacheHit(
                    index=position,
                    key=key,
                    unit=unit,
                    verdict=verdict,
                    ref=entry.ref,
                    bytes=entry.bytes,
                    spend_json=entry.spend_json,
                    micros=entry.micros if reprice is None else reprice(entry.spend_json),
                )
            )
        else:
            outstanding.append(unit)
        verdicts[asked] = verdict
    return CacheProbe(
        hits=tuple(hits),
        outstanding=tuple(outstanding),
        verdicts=verdicts,
        legacy=sum(1 for hit in hits if hit.verdict is CacheVerdict.HIT_LEGACY),
        would_have_been_micros=sum(hit.micros for hit in hits),
        queries=queries,
    )


class CacheIndex(Protocol):
    """The cache boundary. 02-architecture.md row 18's four calls.

    A `Protocol`, like `Store` and `BudgetLedger`, so `omniweave_core.store.cache.SqliteCacheIndex`
    satisfies it structurally and nothing in core grows an import edge into the store.

    **This is not the record of completion.** Row 18's exclusion column is explicit: that is
    `work.status='done'` plus a matching `work.cache_key`, and *"if it is worth keeping it is a
    row."* A `CacheIndex` that could answer "has this unit been done" would be the second home for a
    fact the `work` table owns.
    """

    def get(self, key: str) -> CacheEntry | None:
        """The row, or `None`. The **policy** is `read_verdict()`'s; this is the lookup."""
        ...

    def put(
        self, entries: Sequence[CacheEntry], *, allowed_units: frozenset[tuple[str, str]]
    ) -> int:
        """Write the allowed entries; return how many were written. 08:1465.

        Ordering is fixed by 08:1480: the CAS blob is written and fsynced **before** its
        `cache_index` row, so a crash leaves an unreferenced blob -- swept by mark-and-sweep --
        rather than an index row pointing at nothing. Deletion is the mirror image.
        """
        ...

    def sweep(
        self, *, now_ns: int, gc_days: Mapping[str, int], max_bytes: Mapping[str, int]
    ) -> int:
        """The age sweep then the size sweep. Returns the rows deleted."""
        ...

    def touch(self, key: str) -> bool:
        """Advance `last_hit_ns` and increment `hits`. **D146**: the LRU has no other writer.

        Called after the read policy returns `HIT` or `HIT_LEGACY`, never on a miss. Unwritten,
        `last_hit_ns == created_ns` forever and the size sweep's LRU degrades to a FIFO.
        """
        ...

    def stat(self) -> Mapping[str, tuple[int, int]]:
        """`layer -> (rows, bytes)`. What `ow cache stat` prints beside `GROWTH_BOUND_WORDS`."""
        ...
