# ADR-7 — Every key in the driver system digests the whole of what it identifies

**Status:** Accepted · **Priority:** 9 of 12 · **Price:** 2 ed
**Discharges:** `04#Q2`, `04#Q5` (defect); `02#11` (adjacent)
**Charter errata claimed:** `E60`, `E61` (block `E60`-`E65`, four unused)
**Supersedes:** none
**Blocks / unblocks:** unblocks `04#Q2`'s own ordering condition, "**before the first out-of-tree caller exists**", and with it P3's exit ([16](../16-roadmap.md) §3: P3 ships `resolve()` and both DriverHosts, freeze week 22, exit week 26). Retires `R-T15`'s proposed early-warning counter `drivers.resolve_memo_collisions`† rather than satisfying it. The `[cost.measured]` rename is a `card_schema` change ([04](../04-driver-system.md) §5.2: "adding a key to a `[<port>]` sibling … `[cost.*]` … bump `card_schema`"), so it is free before P3's card-grammar freeze and a migration after. Blocks nothing upstream; ADR-1's bulk lock pass must take this ADR's naming ruling as input rather than coining against the current text.

## Context

Three of this ADR's rows are three instances of one defect: **a key in `omniweave_core.drivers` is narrower than the thing it identifies, so the wrong value is served with no symptom.** The register groups them for that reason — [17](../17-risks.md):791 gives the ADR's rationale as "Three ways the driver system can silently serve the wrong thing … All in `omniweave_core.drivers`".

**Row 1, `04#Q2`** ([17](../17-risks.md):600, verbatim): "`resolve()`'s memo key under-keys four `Requirement` fields | defect | `drivers` | a `requirement_digest` over the whole frozen `Requirement` | **before the first out-of-tree caller exists**; also `R-T15`, ADR-7". The charter memoises `resolve()` on a six-tuple ([charter](../_notes/charter.md):2170-2172):

```text
    # PURE. No imports, no network, no clock. Memoised on
    # (port, format, frozenset(floors.items()), max_cost_class, policy_digest, catalog_digest)
    # — 4,000 parts otherwise means 4,000 calls.
```

`Requirement` ([charter](../_notes/charter.md):2126-2136) has **eight** fields. The tuple omits `input_kind`, `requires_produces`, `granularity` and `pinned`. [04](../04-driver-system.md) §4.8 follows the charter and states the soundness condition instead: "at release 1 every caller holds all four constant per `(port, lane)`". [17](../17-risks.md):205 (`R-T15`) calls this "**the single most likely source of a silent wrong-driver bug in the plan**".

There is a mechanical reason the charter wrote a tuple and not the object: `Requirement.floors` is `Mapping[str, Scalar | frozenset[str]]` defaulting to `MappingProxyType({})`, and a `mappingproxy` is unhashable — verified by execution, `hash(MappingProxyType({}))` raises `TypeError: unhashable type: 'mappingproxy'`. **A frozen `Requirement` cannot be a dict key today.** Any fix must therefore produce a hashable projection, which is why "just memoise on the requirement" is not available and a digest is.

**Row 2, `02#11`** ([17](../17-risks.md):588, verbatim): "the persisted probe verdict cache has no validity key | gap | `drivers` | [04](../04-driver-system.md) enumerating `host_fingerprint`'s inputs — **a fingerprint omitting a GPU driver version serves a stale `ok` after a CUDA upgrade** | v0.1; ADR-7". Enumerating it turns up two further problems the row does not name.

| document | the key it prints | the name it uses |
|---|---|---|
| [02](../02-architecture.md) §2 row 9, §7 item 11; [18](../18-api-sketch.md):219; [glossary](../glossary.md):645 | `(driver_id, driver_version, card_sha256, host_fingerprint)` | `host_fingerprint` |
| [04](../04-driver-system.md) §4.7 (`$OMNIWEAVE_HOME/probe/<driver_id>/<version>/<env_digest>.json`); [09](../09-generation.md):117; [glossary](../glossary.md):579 | `(driver_id, version, env_digest)` — **no `card_sha256`** | `env_digest` |

So the same key has two names and two arities, and the lock carries `host_fingerprint` inside its *Capability probe* row ([terminology](../_notes/terminology.md):166) with no `env_digest` row at all, while the glossary carries both as separate rows. And [04](../04-driver-system.md) §4.7's printed recipe reproduces the exact defect `02#11` names — `"cuda": ctypes.util.find_library("cuda") is not None` is a **boolean**, so a CUDA 12.4 to 12.6 upgrade does not move the digest and a cached `ok` survives it. A second staleness hole sits beside it: `"which": {n: shutil.which(n) ...}` digests a **path**, so `apt upgrade tesseract-ocr` in place moves nothing either. [02](../02-architecture.md) §7 item 11 says the fingerprint covers "the resolved **version** of each declared binary dependency"; [04](../04-driver-system.md) §4.7 digests the path. Neither is implementable as the other.

**Row 3, `04#Q5`** ([17](../17-risks.md):603, verbatim): "`measured_on` names two types on one card | defect | `drivers` | rename the cost block's keys to `hardware` and `hardware_spawn`, leaving `MeasuredOn` the only `measured_on` | v0.1; ADR-7". `[cost.measured].measured_on` is a free string ([charter](../_notes/charter.md):1850-1851, [04](../04-driver-system.md):962-963); `[[quality.benchmark]].measured_on` is the frozen ten-field `MeasuredOn` ([13](../13-quality.md):1663). It belongs with the other two because it is the same shape: `[cost.measured]`'s `measured_on` **is** the validity key of a cost number — the answer to "on what hardware is this p50 true?" — and as free text nothing can compare it to the running host.

**Why a decision and not a repair.** Each row has a stated closer, and taking all three costs about a day. What needs deciding is the rule they share, because the plan has no statement of it: [04](../04-driver-system.md) §4.8 chose to *follow the charter and declare a soundness condition*, which is a legitimate and deliberate reading, and §4.7 chose a cheaper GPU fact than [02](../02-architecture.md) §7 asked for. Reversing both means overriding two written positions, and overriding a written position is what an ADR is for.

## Decision

**D7.1 — `resolve()` memoises on `(requirement_digest, policy_digest, catalog_digest)`.** `Requirement` gains one derived field, computed at construction and covering **every** field the dataclass declares:

```python
@dataclass(frozen=True, slots=True)
class Requirement:
    ...                                  # the eight fields, unchanged
    digest: str = field(init=False, compare=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "digest", sha256(canonical({
            f.name: _jsonable(getattr(self, f.name))
            for f in fields(self) if f.name != "digest"
        })).hexdigest())
```

`_jsonable` sorts a `frozenset` into a list and takes `.value` from a `StrEnum`; everything else is already a `Scalar`. `canonical()` is [04](../04-driver-system.md) §New terms' one canonicaliser, `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()` — no second recipe. Iterating `fields(self)` rather than a written-out key list is load-bearing: **a ninth field added to `Requirement` enters the digest without anyone remembering to add it**, which is the property `04#Q2` exists because the tuple did not have.

Measured cost: the canonical form of the worked `Requirement` at [02](../02-architecture.md):466 is **187 bytes** and its `sha256` takes **3.58 µs** (timed here, 20,000 iterations). [04](../04-driver-system.md):1357 bounds a run at "fewer than 128 distinct requirements", so the whole-run cost is **under 0.5 ms**, paid once per `Requirement` construction rather than once per `resolve()` call. `RESOLVE_MEMO_MAX = 512` and the LRU on `Catalog` are unchanged; the key is now three strings instead of a six-tuple containing a set.

[04](../04-driver-system.md) §4.8's soundness paragraph is **struck**, not weakened: with the digest there is no condition left to state, and a paragraph saying "this holds today" is exactly what a third-party caller will not read.

**D7.2 — the probe cache's key is `(driver_id, driver_version, card_sha256, env_digest)`, and `env_digest` is the only name for it.** Three sub-rulings:

1. **`env_digest` wins the name.** [04](../04-driver-system.md) §4.7 is the only home that prints an executable recipe, it is the name in the on-disk path and in [09](../09-generation.md):117, and it is honest about scope in a way `host_fingerprint` is not — the digest covers an environment, not a host. `host_fingerprint` is retired: [glossary](../glossary.md):645 becomes an alias row pointing at `env_digest`, and [02](../02-architecture.md) §2 row 9, §7 item 11, §New terms:1563 and [18](../18-api-sketch.md):219 are re-worded.
2. **`card_sha256` is in the key.** Three documents print it and one does not; the deciding argument is not the count but [04](../04-driver-system.md):1133's own blind spot for the catalog key — "the developer's own workflow". A card edited in place under an unchanged `[driver] version` changes `[hardware] needs_binaries`, `[config]` and probe-relevant declarations while every other key component holds. The path becomes `$OMNIWEAVE_HOME/probe/<driver_id>/<version>/<card_sha256>/<env_digest>.json`; `os.replace` from a same-directory `.tmp` is unchanged.
3. **`env_digest` digests identities, not presences.** The recipe at [04](../04-driver-system.md) §4.7 gains two changes and nothing else:

```python
def _ident(p: str | None) -> tuple[str, int, int] | None:      # realpath, size, mtime_ns
    if p is None: return None
    st = os.stat(rp := os.path.realpath(p)); return (rp, st.st_size, st.st_mtime_ns)

env_digest = sha256(canonical({
    "platform": sys.platform,
    "machine":  platform.machine(),
    "python":   f"{sys.version_info.major}.{sys.version_info.minor}",
    "which":    {n: _ident(shutil.which(n))                    # was: the bare path
                 for n in sorted(card.hardware.needs_binaries)},
    "cuda":     _ident(ctypes.util.find_library("cuda")),      # was: a bool
    "epoch":    int(os.environ.get("OMNIWEAVE_PROBE_EPOCH", "0")),
})).hexdigest()
```

`os.path.realpath` on Linux resolves `libcuda.so.1` to `libcuda.so.<driver version>`, so the driver version enters the digest as a name; `(st_size, st_mtime_ns)` catches the platforms where it does not (`nvcuda.dll`) and catches an in-place binary upgrade on every platform. **`libcuda` is never loaded and no framework is imported** — `ProbeEnv.gpu_present`'s "NOT torch" constraint ([04](../04-driver-system.md):148) is untouched, and `probe()` still runs only in a worker. Cost is one `os.stat` per declared binary plus one; [04](../04-driver-system.md):1119 already prices `os.scandir` + `stat` over **328** distributions at **1.01 ms**, so a per-card handful is under 50 µs. The `ok`/`degraded`-for-the-life-of-the-digest and `unavailable`-for-`probe_ttl_s = 600` table is unchanged, and `OMNIWEAVE_PROBE_EPOCH` stays as the escape hatch for what stat cannot see.

**D7.3 — the cost block's keys are renamed.** `[cost.measured].measured_on` becomes `hardware`; `measured_on_spawn` becomes `hardware_spawn`. `timing_basis` already carries the in-process-versus-spawn distinction the `_spawn` suffix duplicates, and `MeasuredOn`'s own tenth field is named `hardware` ([terminology](../_notes/terminology.md):320), so the rename makes one word mean one thing across the card instead of two. After it, **`measured_on` on a `driver.toml` is always a `MeasuredOn`**, and a loader that reads the wrong one gets a missing key rather than a `str` where it expects a record.

**D7.4 — two charter errata are claimed from ADR-7's block (`E60`-`E65`).** Rows written here; a later stage inserts them into [charter](../_notes/charter.md) §9.2. Neither is a re-issue of any of D1-D10: D3's rulings on purity, filter order and zero-candidate resolutions are untouched by all four decisions above.

| # | charter locus | search phrase | what the charter says | what supersedes it |
|---|---|---|---|---|
| **E60** | :2170-2172 | `frozenset(floors.items()), max_cost_class` | `resolve()` is "Memoised on `(port, format, frozenset(floors.items()), max_cost_class, policy_digest, catalog_digest)`" | **ADR-7 D7.1.** `(requirement_digest, policy_digest, catalog_digest)`; sole home [04](../04-driver-system.md) §4.8. The tuple omits four of `Requirement`'s eight fields and `Requirement` is unhashable as printed, so the tuple was forced rather than chosen |
| **E61** | :1850-1851 | `measured_on_spawn = "x86_64-linux` | `[cost.measured]` carries `measured_on` and `measured_on_spawn` as free hardware strings | **ADR-7 D7.3.** `hardware` and `hardware_spawn`; sole home [04](../04-driver-system.md) §3's card. `measured_on` on a card is thereafter always the frozen ten-field `MeasuredOn` |

## Alternatives rejected

### Keep the charter's tuple and extend it by four fields

At its best this is the cheapest correct fix and the most conservative: it changes one line, keeps the key legible in a debugger, and needs no new digest recipe. Rejected because it repeats the defect's own mechanism. The tuple was already the *complete* set of fields when it was written; it went stale because `Requirement` grew and nothing linked the two. A ten-tuple goes stale the same way on the eleventh field, and `04#Q2`'s deadline — before an out-of-tree caller exists — is precisely the point after which nobody reviewing a `Requirement` change can see the memo key. Deriving from `fields()` is the only form that cannot drift.

### Keep the tuple and add `drivers.resolve_memo_collisions` as `R-T15` proposes

Genuinely strong, and it is the register's own printed early warning ([17](../17-risks.md):205): digest the whole frozen `Requirement`, compare it against the memo hit, and count the disagreements. Rejected because it computes the digest anyway — the entire cost of D7.1 — and then uses it to *observe* a wrong answer instead of preventing one. A monitoring counter for a defect whose fix costs the same as the counter is a strictly worse trade, and this one signals after the wrong driver has already run and billed.

### Make `Requirement.floors` a `tuple[tuple[str, Scalar | tuple[str, ...]], ...]` so the object hashes

The narrowest fix to the root cause: no digest, no canonicaliser, `Requirement` becomes hashable and *is* the memo key, and hashability is then checked by the type system rather than by a convention. This was the closest call in the ADR. Rejected on two grounds. `floors` is a **mapping** at every read site (`floors["text_span"]`, [04](../04-driver-system.md) §2.1's `>=` / `⊇` comparison table) and a tuple-of-pairs forces every one of them through a rebuild; and the digest is needed regardless, because `resolution_report.requirement_json` ([charter](../_notes/charter.md):2937) already serialises the whole `Requirement` canonically once per row — D7.1 reuses that serialisation rather than adding one. Had `requirement_json` not existed, this option would have won.

### Put a `MeasuredOn` in `[cost.measured]` instead of renaming its strings

The principled reading, and close enough to be worth stating in full: INV-19 requires `(n, ci95, method, slice_key, corpus_digest, MeasuredOn, witness)` on **every published number** ([01](../01-principles.md):517), a card's `p50_ms_per_unit` is a published number, [13](../13-quality.md):1713 already assigns the kit-written `[cost.measured]` block `witness = "self"`, and a free string is exactly the "cost number on hardware the card does not name" that [04](../04-driver-system.md):2050 says the publish gate exists to stop. Rejected because `MeasuredOn` is **frozen and defaultless by design** — a partial construction is a `TypeError`, which is `Q-G8`'s whole mechanism ([13](../13-quality.md):93) — and five of its ten fields (`weights`, `weights_revision`, `prompt_version`, `corpus`, `corpus_digest`) are meaningless for a free CPU decoder's wall-clock median. Filling them with sentinels defeats the gate it is being borrowed from. **Pre-committed fallback, so this is not merely deferred:** the day `ow conform` or `eval_scoreboard` ranks a cost number *across* cards, `hardware` must become a structured record and this ADR is superseded by the ADR that does it. Until then a cost number is compared only against the same card's own history, where a string that changes is signal enough.

### Add a GPU driver version to `env_digest` by calling `cuDriverGetVersion` through `ctypes`

The direct answer to `02#11`: one C call, no framework, the exact integer. Rejected because it `dlopen`s a vendor driver library **in the host process**, which is the one thing [04](../04-driver-system.md) §4.7 organises the entire probe architecture to avoid — probing happens in a discardable worker precisely so a broken install cannot take the host down, and a segfault inside `libcuda` on load is not catchable. `realpath` plus `stat` gets the same discriminating power from the filesystem at about 10 µs.

## Consequences

| obligation | document and locus | price |
|---|---|---|
| `Requirement` gains `digest`; §4.8's "The memo, and its known under-keying" paragraph is rewritten and its soundness condition struck; Q2 moves to *closed* | [04](../04-driver-system.md) §4.8:1345-1355, §Open questions Q2:2589-2596 | 0.5 ed |
| §4.7's `env_digest` fence gains `_ident`; the path grows a `card_sha256` segment; E5's summary line at :33 is unchanged | [04](../04-driver-system.md) §4.7:1258-1272 | 0.3 ed |
| `[cost.measured]`'s two keys renamed in the printed card and in the publish-gate row | [04](../04-driver-system.md):962-963, :2050 | 0.2 ed |
| `host_fingerprint` re-worded to `env_digest`, and the key's arity corrected to four | [02](../02-architecture.md) §2 row 9:233, §7 item 11:1531-1539, §New terms:1563; [18](../18-api-sketch.md):219; [12](../12-performance.md):368, :706; [16](../16-roadmap.md):350 | 0.4 ed |
| `R-T15`'s early-warning column loses `drivers.resolve_memo_collisions`† and gains the property test that replaces it; its mitigation column becomes the discharge note | [17](../17-risks.md):205 | 0.2 ed |
| `04#Q2`, `04#Q5` and `02#11` marked discharged | [17](../17-risks.md):600, :603 and :588, in that order | 0.1 ed |
| a testkit property in the `capability` suite: two `Requirement`s differing only in `granularity` resolve to different `Resolution`s, and the same for each of `input_kind`, `requires_produces` and `pinned` | [13](../13-quality.md)'s conformance suites; built in P3 | 0.3 ed |

**Types that change shape.** `Requirement` gains a field — it is `T-CONTRACT` ([02](../02-architecture.md) §2 row 13), so this must land before P3's freeze (week 22) or it is a `CONTRACT` bump. `DriverCard`'s `[cost.measured]` loses two keys and gains two: a `card_schema` bump under [04](../04-driver-system.md) §5.2, free while `card_schema = 1` is unreleased and a migration after. **A future reader must not** treat `[cost.measured].hardware` as comparable across cards; it is a label, not a machine identity, until the fallback above fires.

**A risk loses an enforcer and gains a better one.** `R-T15`'s falsifier moves from a runtime counter (post-hoc, per-run, requires someone to look) to a compile-time impossibility plus four property tests. That is a strict improvement in strength and a strict loss in *observability*: if the digest is ever wrong, nothing counts it. Recorded deliberately — the digest covering `fields()` is what makes the loss acceptable, and narrowing it back to a written key list reopens `R-T15` at its original score of 3 x 4.

**Two coordination obligations on other ADRs.** (a) **ADR-1** must add lock rows for `env_digest` and `requirement_digest`, must **not** coin a fresh `host_fingerprint` row, and must fix [terminology](../_notes/terminology.md):166's *Capability probe* row, which names `host_fingerprint` in prose. (b) **ADR-3** touches [04](../04-driver-system.md) §3's shipped card for `04#Q12`; D7.3 edits the same fence. Same file, adjacent lines, so the two land in one PR or ADR-3 rebases.

**What becomes harder.** Reading a memo key in a debugger: `('a3f1…', 'b7c2…', 'd9e0…')` says nothing, where the old tuple said `('parse/1', 'pdf', …)`. The mitigation is already shipped and costs nothing extra — `resolution_report.requirement_json` holds the whole requirement in canonical JSON per row, and `ow drivers explain` reads it.

## Open

**`resolution_digest` has no printed recipe anywhere.** It is the primary key of `resolution_report` ([charter](../_notes/charter.md):2937-2941), it is `DR4`'s replay evidence ([charter](../_notes/charter.md):2273), it is printed in two worked examples ([04](../04-driver-system.md):2278, :2296) — and [04](../04-driver-system.md)'s own "Extends the charter" note E14 defines exactly four digest recipes (`card_sha256`, `attestation`, `config_digest`, the pins digest) and this is not one of them. D7.1 makes it nearly free to state, since `requirement_digest` is the natural first component. Deliberately **not** decided here: it belongs to no row in [17](../17-risks.md) §§7.3-7.4, and inventing scope is how an ADR partition stops being auditable. What closes it: a fifth row in that table, written in the same change that lands D7.1. Filed as a foreign defect.
