# ADR-10 — The data artefacts ship as ZIP, the weight ceiling reads marginal, and `omniweave-conform` implements `eval`

**Status:** Accepted · **Priority:** 10 of 12 · **Price:** 2 ed, plus a one-time re-packaging of two artefacts (~15% on a ~240 MB download) that costs nothing if this lands before they are first published
**Discharges:** `11#OQ-1`, `11#OQ-2`; adjacent `11#OQ-12`
**Charter errata claimed:** `E78`, `E79` (block `E78`-`E83`, four unused)
**Supersedes:** none
**Blocks / unblocks:** unblocks a stdlib-only install reaching `omniweave-golden` and `omniweave-index` at all; unblocks `tools/gate_weights.py` having one reading of the column it gates; unblocks risk path **P2**'s weights mirror, which [17](../17-risks.md):301 makes conditional on this exit. Nothing waits on it in the other direction, but its deadline anchor is hard: **before the first `omniweave-golden` or `omniweave-index` artefact is published** ([16](../16-roadmap.md) W10.8, :923), because a container change after publication is a digest change and a digest mismatch is by construction a permanent failure that never triggers a fetch.

## Context

Three rows, quoted from [17-risks.md](../17-risks.md):666, :667 and :677:

> `11#OQ-1` | the `.tar.zst` data artefacts are unreachable from a stdlib-only install — a charter
> contradiction, since D1 struck `zstandard` from core and the lock lists `.ndjson.zst` as a rejected
> synonym, while `omniweave-golden` and `omniweave-index` ship `.tar.zst` | defect | `release` | an
> ADR against section 3.2. Three exits ranked: **(a) `.tar.gz`** or a ZIP of the same members, ~15% on
> a one-time ~240 MB download and the charter's own `unzip -p | jq` argument; (b) require a `zstd`
> binary on PATH; (c) give `omniweave-conform` a `zstandard` dependency, which is a **complete** fix
> only if `11#OQ-12` puts `ow eval` there. Recommendation (a). Until then `ow doctor` reports
> `golden: unavailable (no zstd decoder)` rather than failing at first use |
> v0.1; ADR-10; interacts with path **P2**'s weights mirror

> `11#OQ-2` | the weight-ceiling column needs a charter erratum: the lock says "measured from
> `RECORD` in a fresh environment", which reads as a closure, and the closure reading is
> arithmetically inconsistent | defect | `release` | one sentence in the lock and in section 3.2, plus
> `tools/gate_weights.py` printing both the per-row sum and the deduplicated union | v0.1; ADR-10

> `11#OQ-12` | which distribution implements `ow eval`, and therefore what may read the golden corpus?
> … one sentence in [10](../10-interfaces.md) naming the distribution that implements the `eval` group.
> **It changes the ranking of `11#OQ-1`'s three exits** | v0.1; ADR-10

**`.tar.zst` has exactly one carrier and it is the immutable charter.** [charter.md](../_notes/charter.md)
§3.2, :164-167: "Both are `.tar.zst` + `manifest.toml` + `.sha256`, installed by digest into
`$OMNIWEAVE_HOME/`". Every plan restatement — [02](../02-architecture.md):275,
[13](../13-quality.md):376, [14](../14-security.md):1251, [16](../16-roadmap.md):923 and :1179 —
follows it under instruction. The same charter struck `zstandard` from core at :290 ("`compression.zstd`
is 3.14+, so zstd is a dependency across our whole floor"), banned it as a runtime dependency at :406,
and the lock rejects `.ndjson.zst` at [terminology.md](../_notes/terminology.md):536. The framework
ships two artefacts it tells an installed copy to fetch, verify and read, in a container that copy has
no decoder for.

**The plan has already made this decision once, one section away.** [11](../11-repo-layout.md) §3.2,
:919-923: "the bundle is `.tar.gz`, not `.tar.zst`: `tarfile` and `gzip` are standard library on every
supported Python, `compression.zstd` is 3.14+, and `ow targets install` lives in the `omniweave`
distribution whose closure contains no zstd decoder. That is the charter's own argument … applied to
the one artefact format the charter left unspecified — and OQ-1 records that the two data artefacts it
*did* specify are the sole remaining exception."

**Two readers, not one, and this is what settles the exit ranking.**

| artefact | read by | citation |
|---|---|---|
| `omniweave-golden` | the eval harness only: `ow eval fetch` installs it, `ow eval golden`, `ow conform --bench` and the calibrator consume it | [13](../13-quality.md) §4.1 :376, §4.6 :521, §12 :1679-1680, §13 :1780 |
| `omniweave-index` | the **runtime**: it is "readable **before install**", it is what `dist_sha256` in `omniweave.lock` is checked through, and `ow drivers` counts its stubs | [glossary.md](../glossary.md):750; [00](../00-vision.md):415 "only for consumers who installed through `omniweave-index`"; `V20-6` at [00](../00-vision.md):751; `K-12` at [17](../17-risks.md):393 |

`11#OQ-12` can move everything that reads the **corpus** into `omniweave-conform`. It cannot move
`omniweave-index`, which is read by the distribution that must not depend on `omniweave-conform`
([11](../11-repo-layout.md) §2.2, restated at :2578). So exit (c) is complete for one artefact of two,
by construction, whatever `ow eval`'s answer turns out to be.

**The weight ceiling.** [charter.md](../_notes/charter.md) §3.2's distribution table, :119-134, gives
one `ceiling` column: `omniweave-target-deck` at 1 MB, `omniweave-core` at 3 MB, and dependency rule 4
at :143 makes every `compile`-Port distribution — `-deck` included — depend on `omniweave-core`. Read
as a closure, a 1 MB row contains a 3 MB row. The lock still says "measured from `RECORD` in a fresh
environment" ([terminology.md](../_notes/terminology.md):502, [glossary.md](../glossary.md):1055, and a
third print at [D1-substrate.md](../_notes/rulings/D1-substrate.md):707), which is the closure reading;
[11](../11-repo-layout.md) §2.5, :745-755, states the marginal one, and §2.3's install-profile table at
:648 already computes marginally — `174 MB (44+40+30+60)`. The plan computes one way and defines the
other.

**Why these are decisions and not repairs.** The container cannot be edited — charter §1-8 is
immutable by its own §9 preamble — so the fix is an erratum plus a superseding home. The exit ranking
depends on an unrelated open question, which is why the two cannot be split across ADRs or across
time. And the ceiling column is a choice between two readings of one printed word where the losing
reading is not inconvenient but arithmetically impossible.

**One trap, named so nobody falls into it.** The plan uses *weight* in three unrelated senses:
installed-size ceilings (`tools/weights.toml`), **model** weights (olmocr's, path P2's mirror), and
the retrieval fusion weights `DEFAULT_WEIGHTS` ([07](../07-store-and-retrieval.md):1297) pinned as
`scorer=1` in `omniweave.index.lock`'s header ([07](../07-store-and-retrieval.md):1412, :3021). The
first two are this ADR's subject; **the third is not, and is not touched here.** Nothing below changes
`SCORER_VERSION`, `DEFAULT_WEIGHTS`, its five members or the `5.4/61` ceiling arithmetic
([07](../07-store-and-retrieval.md):3305), so no published confidence number is invalidated by
anything decided here. The overload is a lock finding and belongs to ADR-1.

## Decision

1. **Both data artefacts ship as a plain ZIP with `ZIP_DEFLATED` members**, keeping the three-file
   shape — `<name>-<version>.zip` + `manifest.toml` + `<name>-<version>.zip.sha256`, installed by
   digest into `$OMNIWEAVE_HOME/golden/<version>-<sha256>/`, re-verified on every use, a digest
   mismatch still a permanent failure that never triggers a fetch. This takes exit **(a)** as
   [17](../17-risks.md):666 words it — "`.tar.gz` **or a ZIP of the same members**" — and resolves
   which of the two.
2. **Members are read only through [14](../14-security.md) §2.2's bounded reader**, with `confine()`
   on every member name and `extractall` still semgrep-banned ([14](../14-security.md):1698). ZIP is
   the container that reader is written for — its pre-filter is `central_directory.uncompressed_size(name)`
   and its read is `cap+1` bytes by name — so this makes [14](../14-security.md):1251's existing
   promise true rather than aspirational, under one implementation, one semgrep rule and one zip-slip
   fixture set shared with `.owdoc`.
3. **The `ceiling` column reads marginal.** A row is the distribution's own installed files plus the
   third-party closure it introduces, **excluding first-party siblings**, each counted in its own row
   — [11](../11-repo-layout.md) §2.5's `Marginal weight`. `aggregate_mb = 250` for
   `omniweave[recommended]` is the **only** union number. `tools/gate_weights.py` prints the per-row
   sum **and** the deduplicated union on every run, pass or fail, so the gap between them is never
   inferred.
4. **`omniweave-conform` implements the `eval` Action group**, and the registry does not move. Every
   `eval` row stays in `ACTIONS` in `omniweave` unconditionally with its `inp`/`out` types there
   ([10](../10-interfaces.md) §2.1, :141); the dispatcher lazily imports `omniweave_conform` and, when
   it is absent, refuses in the established shape naming `pip install omniweave-conform` — the shape
   of the "no driver for `.pdf`" refusal at [11](../11-repo-layout.md):710. The code is the next free
   numeral in 10's `OW-A-0xx` block, allocated by 10 in `codes.toml`. **The registry may not vary with
   what is installed**: the seven agent-facing surfaces are generated from `ACTIONS` and byte-diff
   gated ([10](../10-interfaces.md) §11, :2358), so an Action registering itself from
   `omniweave-conform` would make `ow surface emit --check` pass or fail by environment.
5. **`ow doctor` gains one row, `D-27`** in [15](../15-observability.md) §9's register (after `D-26`,
   :1536), severity `info`, printing the golden corpus's state and never failing the run. Its value
   carries the pre-committed interim position: `golden: unavailable (no zstd decoder)` for as long as
   a published artefact is still `.tar.zst`, then `golden: not installed — ow eval fetch
   omniweave-golden@<version>` once decision 1 is applied, at which point the first branch is dead
   code deleted with the last `.tar.zst` artefact.
6. **Risk path P2's weights mirror uses this channel and this container.**
   [17](../17-risks.md):297-302 proposes mirroring olmocr's weights "by digest into the same
   `.tar.zst` + `manifest.toml` + `.sha256` channel `omniweave-golden` already uses", with an OQ-1
   caveat. The caveat is discharged in the mirror's favour and in the strongest form: the mirror is
   read by `omniweave-vision`, a **runtime** distribution, so it could never have used `.tar.zst` at
   all. The mirror is a third artefact of this family, in this container, read by this reader; its
   name and refresh cadence remain path P2's own decision and are not fixed here.
7. **Charter errata `E78` and `E79`**, claimed from ADR-10's block (`E78`-`E83`,
   [README](README.md) §6), in the five-part shape [11](../11-repo-layout.md) §8.4 requires:

   | # | `E78` — the container | `E79` — the ceiling column |
   |---|---|---|
   | 1 | [charter.md](../_notes/charter.md) §3.2, :164-167 | [charter.md](../_notes/charter.md) §3.2, the table at :119-134 and the aggregate rule at :169-171 |
   | 2 | "Both are `.tar.zst` + `manifest.toml` + `.sha256`, installed by digest into `$OMNIWEAVE_HOME/`, re-verified on every use" | the unlabelled fourth column, read together with the lock's "measured from `RECORD` in a fresh environment" |
   | 3 | "Both are a plain ZIP with `ZIP_DEFLATED` members + `manifest.toml` + `.sha256`" — sole home [11](../11-repo-layout.md) §3.2 | the column is **marginal**, `aggregate_mb` is the only union — sole home [11](../11-repo-layout.md) §2.5 |
   | 4 | `E78` | `E79` |
   | 5 | re-issue: **none**. [D1-substrate.md](../_notes/rulings/D1-substrate.md) states the distribution split and never states this container | re-issue: **D1**. [D1-substrate.md](../_notes/rulings/D1-substrate.md):707 carries the Weight-ceiling definition verbatim and is a third print site of the losing reading |

## Alternatives rejected

### `.tar.gz`, which is the spelling both `11#OQ-1` and §7.6 lead with

Argued at its best this is the closest call in the ADR. `tarfile` and `gzip` are standard library
exactly as `zipfile` is; it is already the Toolchain bundle's container ([11](../11-repo-layout.md)
§3.2, :919), so it would give the framework one archive spelling for everything the charter left
unspecified; and streaming decompression bounds memory without a directory to trust.

Rejected on the reader. [14](../14-security.md):1251 already promises these two artefacts are read by
§2.2's bounded reader, and that reader is written against a **central directory**: a declared
per-member uncompressed size as a pre-filter, then a `cap+1` read of that member **by name**. A tar
has no central directory and no addressable member, so `.tar.gz` means a second bounded reader, a
second semgrep target and a second fixture set beside the zip-slip, symlink, ADS and device-name
fixtures at [14](../14-security.md):1698. It also declines the charter's argument in the charter's own
words — `unzip -p x.owdoc blocks/000063.ndjson | jq` ([charter.md](../_notes/charter.md):290) — for an
analogy to it. The Toolchain-bundle precedent is narrower than it looks: that bundle is one esbuild
output read once by `ow targets install` and never by the bounded reader, so it is precedent for "a
stdlib container", not for "tar".

### Exit (b) — require a `zstd` binary on `PATH`

At its best: no repackaging, the charter's spelling intact, the best compression on the one artefact
where 240 MB hurts, and CI already resolves `zstandard` as a dev dependency
([charter.md](../_notes/charter.md):406), so the gate harness is unchanged.

Rejected because it converts a data-format decision into an ambient-environment dependency —
`ow doctor` must probe for a binary and the corpus becomes unavailable on a bare Windows host
([11](../11-repo-layout.md):2473-2474) — and because a subprocess's output cannot be charged against
`MAX_CONTAINER_TOTAL_BYTES`, so [14](../14-security.md) §2.2's decompression-bomb bound is lost on the
one archive we fetch over the network.

### Exit (c) — give `omniweave-conform` a `zstandard` dependency

At its best this is genuinely strong, and decision 4 makes it stronger. `zstandard` is already
permitted dev-only ([charter.md](../_notes/charter.md):406); `omniweave-conform` never appears in a
runtime closure ([11](../11-repo-layout.md) :274, :609-613); and with `ow eval` implemented there,
every reader of `omniweave-golden` is inside `omniweave-conform`. For that artefact it is a
**complete** fix at zero cost to a runtime user and zero download growth — exactly the promotion
`11#OQ-12` predicted, moving (c) from third place to second.

Rejected on the second artefact, which the promotion cannot reach. `omniweave-index` is read before
install and by the runtime distribution ([glossary.md](../glossary.md):750,
[00](../00-vision.md):415), and `omniweave` must not depend on `omniweave-conform`. So (c) fixes at
most one of the two and leaves one artefact family with two containers, two decoders and two
`ow doctor` probes — the shape [charter.md](../_notes/charter.md):8677 item 19 rejects. **This is the
precise sense in which `11#OQ-12` changes the ranking and still does not change the outcome**, and why
the two questions had to be answered in one document.

### Split the containers — `.tar.zst` for golden, ZIP for the index

At its best it puts the compression where the bytes are (~240 MB against a small stub index) and costs
a runtime user nothing, since only conform reads the compressed one. Rejected for (c)'s reason stated
as a design rather than a consequence: two containers for one artefact family, and a `manifest.toml`
whose meaning depends on which artefact it sits beside — to save ~15% of a download taken twice a year
([13](../13-quality.md) §11, :1575).

### Read the `ceiling` column as a closure and renumber instead

At its best: "installed size" in plain English *means* closure, it is what a user asking "how big is
`omniweave-target-deck`" wants to know, and the marginal reading forces a reader to sum rows to answer
the obvious question.

Rejected because the renumbering is not available: charter §3.2's table is immutable, and making the
closure reading consistent means rewriting the numbers in it. The plan also already computes
marginally where it computes at all — [11](../11-repo-layout.md) §2.3's `174 MB (44+40+30+60)` — and
`aggregate_mb` already exists as the union number, so the closure reading needs a second union concept
to say what one number says today.

## Consequences

| edit | locus | price |
|---|---|---|
| errata `E78` and `E79` drafted for §9.2 | [charter.md](../_notes/charter.md) §9.2 (inserted by a later stage) | 0.3 ed |
| container spelling, five restatements | [02](../02-architecture.md):275, [13](../13-quality.md):376, [14](../14-security.md):1251, [16](../16-roadmap.md):923 and :1179 | 0.3 ed |
| OQ-1 and OQ-2 struck for a pointer here; §3.2's `.tar.gz` paragraph gains the clause that the data artefacts are ZIP and the Toolchain bundle is not | [11](../11-repo-layout.md) :919-923, :2457-2478, :2481-2487 | 0.3 ed |
| §2.5 becomes normative rather than corrective; §2.6's `gate_weights.py` prints both numbers always | [11](../11-repo-layout.md) §2.5, :745-755 | 0.2 ed |
| the `eval` group's dispatch rule and one `OW-A-0xx` row in `codes.toml` | [10](../10-interfaces.md) §2, §11 | 0.4 ed |
| `D-27` | [15](../15-observability.md) §11, after :1536 | 0.1 ed |
| path P2's mirror sentence loses its OQ-1 caveat | [17](../17-risks.md):297-302 | 0.1 ed |
| `Weight ceiling` gains "marginal"; `Marginal weight` is added (already proposed by [11](../11-repo-layout.md) §New terms); a rejected-synonym row is added for `.tar.zst` for a first-party data artefact | [terminology.md](../_notes/terminology.md):502 and :536, [glossary.md](../glossary.md):749-750, :1055 | carried by ADR-1 |
| D1's New-terms Weight-ceiling line re-issued | [D1-substrate.md](../_notes/rulings/D1-substrate.md):707 | 0.1 ed |

**1.8 ed of edits against the 2 ed [17](../17-risks.md) §7.6 prices**, with the balance in the
re-packaging below.

- **The re-packaging is free before publication and expensive after.** `omniweave-golden` is built at
  [16](../16-roadmap.md) W10.8 (:923, phase P10) and `omniweave-index` at the V20-6 line (:1179). If
  this ADR lands first, the packager is written once and the only cost is ~15% on the download. If it
  lands after, both artefacts are re-packaged **and** their digests change — and a digest change is,
  by the charter's own rule at :164-167, a permanent failure that never triggers a fetch, so every
  installed copy must be told to re-fetch by hand. That asymmetry is the whole reason a priority-10
  ADR carries a hard ordering anchor.
- **~15% is a ceiling, not a measurement.** [11](../11-repo-layout.md):2470 estimates it; a ~240 MB
  corpus that is largely already-compressed PDF and scan data will lose less. This ADR does not
  re-measure it and does not need to — the number is a one-time download delta under either exit.
- **What becomes harder.** Any future artefact that genuinely needs zstd must amend charter §3.2
  against `E78` *and* name the distribution whose closure carries the decoder *and* show that row's
  weight. Compression choices become a weight-table question, which is the point.
- **What a future reader must not do.** Re-propose zstd for an artefact a **runtime** install reads —
  the argument is closed on `omniweave-index`, not on compression ratios. And do not read anything
  here as touching `DEFAULT_WEIGHTS`, `SCORER_VERSION` or `scorer=1`: three unrelated senses of
  "weight" meet in this ADR and only two of them are its subject.

## Open

**Whether `omniweave-index` needs a container at all.** It is described everywhere as a single
`index.json` of card stubs ([glossary.md](../glossary.md):750), and a bare `.json` + `.sha256` would
remove one archive read from the pre-install path. Not decided here because the artefact's member list
has never been printed: [11](../11-repo-layout.md) §7.1's published-artefact table (:1723) names it as
a release asset and stops. **What closes it:** 11 §7 printing its members. The ZIP shape above is
correct under either answer, and a single-member ZIP costs one central-directory record.
