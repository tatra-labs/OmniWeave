# ADR-3 — The shipped configuration: thirteen enabled drivers, one flattening rule, and `ow doctor` green on a fresh install

**Status:** Accepted · **Priority:** 2 of 12 · **Price:** 4 ed
**Deadline:** before the P1 exit ([16](../16-roadmap.md) §3, week 22) — [17](../17-risks.md):346
**Discharges:** `04#Q1`, `04#Q8`, `05#2`, `05#3`, `02#5`, `15#1` (defect); `05#5`, `03#Q7`, `04#Q12` (adjacent)
**Charter errata claimed:** `E36`, `E37`, `E38`, `E39` (block `E36`-`E41`, [adr/README.md](README.md) §6)
**Supersedes:** none. `15#1` supersedes `05#5`'s one-member framing ([17](../17-risks.md):711)
**Blocks / unblocks:** unblocks `V01-15` ([00](../00-vision.md):716), which cannot be run while `ow doctor` fails as printed; unblocks `G18` and `ow route lint` check 1 on the shipped example. Named mitigation for `R-A8` ([17](../17-risks.md):269).

## Context

`V01-15` requires that on a clean 4-core machine, offline after install, `ow install` → `ow add
~/docs` → `ow query` returns a cited Answer in ≤ 600 s ([00](../00-vision.md):716, and
`first_answer_seconds` at :880). **As printed the first step fails.** `ow doctor` exits 1 only on "a
condition that makes omniweave unable to run at all", of which [10](../10-interfaces.md):1749-1752
lists six, two of them driver-activation conditions.

The shipped `omniweave.toml` (charter `:501-560`) names **ten** ids in `[drivers] enabled` and
`[targets] enabled = ["pptx"]`. [17](../17-risks.md):599 — "`04#Q1` | the shipped `[drivers] enabled`
cannot satisfy `[targets] enabled`; `parse.deck.native` has no distribution row | defect | `release` |
… **Until then `ow doctor` on a fresh install is expected to fail**". A second gap is larger: the
repaired routing policy ([05](../05-ingest-and-routing.md) §4.4) names five drivers and **two are not
in the ten** — `parse.text.builtin` (:1392) and `parse.fields.lift` (:1567). The second is unenabled
**on purpose**: :1560 comments "parse.fields.lift is NOT in [drivers] enabled and its OpenRAIL-M
weights compute to" a forbidden tier ([04](../04-driver-system.md):2492). So `ow doctor`'s
"named-but-unenabled driver" condition, which [10](../10-interfaces.md):1751 states with **no scope**,
fails the shipped configuration by design as well as by omission. That is the real blocker, and no
register row names it.

Three further rows are missing entries in shipped files — `05#2` (:612, "`parse.text.builtin` has no
charter row; ten format tokens have no producer"), `05#3` (:613, "`block.flagged_frac` is read by the
shipped policy and absent from the signal registry … as printed the builtin policy fails `ow route
lint` check 1") and `02#5` (:582, "`acquire/1` has no shipped driver and section 3.1 implies one").
Two are already repaired in a plan document and only the immutable charter still carries the defect:
[05](../05-ingest-and-routing.md) §5.1 registers `block.flagged_frac` at :2079 (part-scoped, `measure`,
FREE, nullable, `req = REPAIR`) against the charter's 23-row day-one table at `:2498`, and
[05](../05-ingest-and-routing.md):3296 records `parse.text.builtin` as **closed** — it is in
[04](../04-driver-system.md) §10.1's roster. `15#1` ([17](../17-risks.md):711) is likewise
dischargeable: [15](../15-observability.md) §6.3 at :964 prints the **twenty-seven**-member
`DegradationKind` literal and owns the count, and charter erratum `E15` already retires the
sixteen-member form, so `stat_stale` no longer type-errors.

**`04#Q8` does not say what the register says it says, and its prescribed fix would break `G18`.**
[17](../17-risks.md):606 reads "two `drivers.*` keys are missing from `tools/config_axes.toml` …
add `"drivers.*.config"` and `"drivers.resolve.*"` to the key list". `drivers.*.config` **is already
present**, in `[semantic]` at charter `:4413`, and the glob-arity comment at `:4393` uses it as its
own worked example; [02](../02-architecture.md):1382 says so too. [04](../04-driver-system.md)
§Open questions Q8 read only the `[operational]` list. Adding it again would put two globs on one key,
which charter `:4396` declares "a G18 FAILURE, not a precedence puzzle".

The real defect is that **G18 has no stated key-enumeration rule**, and the answer flips on it. The
shipped example and the two axis lists were parsed and matched:

| flattening rule | keys | uncovered | double-matched | patterns matching nothing |
|---|---|---|---|---|
| an inline table is **one leaf key**, a quoted dotted key is **one segment** | 117 | 0 | 0 | 0 |
| descend into inline tables and split quoted keys on `.` | 131 | 14 | 0 | 4 |

Under the first, the sixty patterns cover the example **exactly** and G18 passes today. Under the
second it fails fourteen times over and four patterns are dead. Nothing in the charter says which
holds, so `04#Q8` is undecidable rather than wrong.

**This is a decision, not a repair.** `ow doctor`'s activation check has a scope nobody has stated,
and stating it is what makes `V01-15` runnable; and `04#Q8` cannot be applied as written without
introducing the failure it claims to fix.

## Decision

**1. `[drivers] enabled` goes from ten ids to thirteen.** Add `parse.text.builtin` (`05#2`;
[04](../04-driver-system.md) §10.1 already carries it in `omniweave-office`, stdlib-only, serving the
ten text-family tokens `decode.text-native` names), and `compile.pptx.native` and
`parse.pptx.native` (`04#Q1(a)`, the two Drivers a Target is implemented by). `parse.deck.native` is
**not** added — `deck` is absent from `[targets] enabled` — but §D1's `omniweave-target-deck` layout
row gains it, which is `04#Q1(b)`.

**2. `ow doctor`'s activation check gets a scope, and a rule may declare an expected absence.**
The exit-1 condition at [10](../10-interfaces.md):1751 reads exactly three sources: every `driver =`
in the compiled routing policy, every `[graph.passes] enable` member, and every Driver a `[targets]
enabled` entry implies through §D8's target matrix. A `[[rule]]` may declare `expect_unavailable =
true`, in which case a named-but-unenabled driver is a **warning naming the rule**, not an exit — the
rule at [05](../05-ingest-and-routing.md):1567 takes it, and :1560's prose comment becomes the key
that carries it. `ow route lint` gains check 14: `expect_unavailable = true` on a rule whose driver
**is** enabled is an error, so the declaration cannot rot into a permanent excuse. The key is a name
coined here and takes a lock row through ADR-1, which is why ADR-1 is priority 1.

**3. `tools/config_axes.toml` gains a flattening rule, not two keys.** Its header block gains, beside
the glob-arity paragraph at charter `:4392-4398`:

```toml
# KEY ENUMERATION, so "covers omniweave.toml.example EXACTLY" is decidable:
#   An INLINE TABLE is ONE key: `drivers.max_workers = {free=4,...}` is the key
#   `drivers.max_workers`, not three. A key quoted because it holds dots is ONE
#   SEGMENT: `[drivers."parse.pdf.pdfium"] config` matches `drivers.*.config`.

[drivers.resolve]                      # in omniweave.toml.example, DR3: a duplicate id
"parse.office.anydoc" = "omniweave-office"   #   never wins silently
```

`drivers.*.config` is **not** added — it is already at `:4413`. `drivers.resolve.*` **is** added to
`[operational]`, together with the example stanza above, because a pattern matching no key fails the
same "neither over" clause. That is 118 keys against 61 patterns, one pattern per key.

**4. `05#3` and `15#1` are discharged by naming the sole home, not by a new mechanism.**
[05](../05-ingest-and-routing.md) §5.1 is the sole home of the signal registry and carries
`block.flagged_frac` plus the seven other additions ([05](../05-ingest-and-routing.md):3410); the
charter's 23-row table at `:2498` is retired by `E38`. [15](../15-observability.md) §6.3 is the sole
home of `DegradationKind` at twenty-seven members and already holds erratum `E15`, so `15#1` needs no
new erratum and `05#5`'s "needs a `rung_ceiling` member" framing is superseded.

**5. `02#5`: `acquire/1` is a live Port with no in-tree implementation at release 1.** Filesystem
discovery is core-side in `omniweave/run/discover.py`, `unit.connector` defaults to `'fs'`, and
charter §3.1's parenthetical "(fs, url, connectors)" at `:100` is loose prose retired by `E39`.
[11](../11-repo-layout.md) §1.2's distribution table stays at fourteen rows and
[02](../02-architecture.md) §3.2's `layers.toml` stays at fourteen lines. This follows
[02](../02-architecture.md):1482-1492's traced scenario (a): a shipped `acquire.fs.local` cannot live
in the `omniweave` distribution because G4 rule 3 would then demand the row `["omniweave_ports"]` for
a package that also holds the Supervisor.

**6. `03#Q7` (adjacent): `Kind.SECTION` stays, with a stated vacancy.** No driver in
[04](../04-driver-system.md) §10.1's roster declares `Capabilities.sections = "typed_levels"`, so the
member has no release-1 producer. It is kept because `Kind` is the framework's closed **read**
vocabulary, not the shipped roster's write set: a third-party EPUB or DITA driver may lawfully declare
`typed_levels`, and withdrawing it would make a lawful driver unable to express its output. The
vacancy is stated in [04](../04-driver-system.md) §10.1's roster note and excluded by name from
`V01-17`'s scope — the "stated vacancy" branch [17](../17-risks.md):595 offers.

**7. `04#Q12` (adjacent): one synthetic `commercial` DriverCard lands in the licence unit tests with
`compute_tier`.** Release 1 ships no `commercial`-tier driver, so without it the tier is specified and
never executed.

**8. `R-A8` is discharged on its first trigger and explicitly deferred on its second.**
[17](../17-risks.md):269 names two: "`ow doctor` failing on a fresh install; **or** more than two
config keys needing to change before `ow query` returns an Answer". Decisions 1-3 close the first. The
second is a measurement nobody has run — `V01-15` is its instrument, and [15](../15-observability.md)
§10.1 (:1566-1600) shows the shipped defaults already answer over born-digital office documents with
zero edits while a scanned corpus reports `parse_gap_in_scope`. **Interim position:** the defaults are
not widened. **Pre-committed fallback:** if `V01-15` on the three F20 reference corpora
([00](../00-vision.md):808) needs more than two edits, the response is `ow init --profile
{laptop,server,ci}` — three files, one selector — **not** a wider default, because widening a default
re-bills every corpus whose `semantic` keys move.

## Alternatives rejected

**Apply `04#Q8` as the register writes it.** It is the register's own closer, it is one line, and the
register is the authoritative scope. Rejected on measurement: `drivers.*.config` is at charter `:4413`
and a second copy is a double match, which charter `:4396` calls a G18 failure outright; and
`drivers.resolve.*` with no `[drivers.resolve]` stanza in the example is a pattern matching nothing,
which the same "neither over nor under" clause rejects. The register's fix would take G18 from passing
to failing twice. This is the sharpest reason an ADR exists rather than a patch.

**Scope `ow doctor`'s activation check to exclude the routing policy.** Simplest possible fix: read
only `[graph.passes] enable` and `[targets] enabled`, and the shipped configuration passes with no new
key. Genuinely close, and it is what a reader would guess [10](../10-interfaces.md):1751 already means.
Rejected because it removes the only pre-flight check on the policy's driver names, so a rule naming a
driver that is not installed at all reaches `resolve()` at ingest time and surfaces as a per-part
`Degradation(kind='driver_unavailable')` ([05](../05-ingest-and-routing.md):3177) after the user has
waited. `ow doctor` exists to move that discovery before the run, and `expect_unavailable` keeps the
check while admitting the one deliberate absence.

**Enable `parse.fields.lift` and let the licence gate refuse it.** INV-5's gate order would reject it
on tier anyway, so the doctor check would pass and nothing would run. Rejected because it inverts the
charter's reading of activation — "installation is not consent" (INV-5) — and naming a driver whose
licence the operator may not accept in the shipped default is exactly the consent the invariant
withholds. It would also make `ow show-config` print an enabled driver that can never run.

**Withdraw `Kind.SECTION` now.** [03](../03-document-model.md):3005 argues it well: `enum_val.ord` is
append-only (§2.1), so withdrawing after the first `model_version` freeze costs a retired ordinal
forever, and this ADR sits before that freeze. Close enough to be worth stating. Rejected because the
cost is asymmetric the other way: a kept member with no writer costs nothing at read time while a
withdrawn one cannot be re-added without a new ordinal, and `sections = "typed_levels"` is a card
field the framework invites third parties to set.

**Ship the two `[drivers] enabled` additions and defer the doctor scope.** Rejected because
`parse.fields.lift` would still fail the check, so `V01-15` still cannot be run — the row count is
necessary and not sufficient, which is why decisions 1 and 2 must land together.

## Consequences

| # | obligation | price |
|---|---|---|
| 1 | `[drivers] enabled` 10 → 13 ids; §D1's `omniweave-target-deck` row gains `parse.deck.native`; the two `pptx` `driver.toml`s ship. Sole home: [04](../04-driver-system.md) §10.1 plus [11](../11-repo-layout.md) §1.2 | 0.5 ed |
| 2 | `expect_unavailable` on `[[rule]]`: the policy grammar in [05](../05-ingest-and-routing.md) §4.2 gains the key, `ow route lint` gains check 14, [10](../10-interfaces.md) §7.5 gains the check's three sources, and ADR-1's pass takes the lock row | 1 ed |
| 3 | `tools/config_axes.toml` gains the enumeration comment and `drivers.resolve.*`; `omniweave.toml.example` gains the `[drivers.resolve]` stanza; `tools/gate_config_axes.py` implements the enumerator | 1.5 ed |
| 4 | four errata into charter §9.2 by a later stage; the `05` §5.1 and `15` §6.3 sole-home statements recorded | 0.5 ed |
| 5 | one synthetic `commercial` card in the licence unit tests; the `Kind.SECTION` vacancy note in [04](../04-driver-system.md) §10.1 and its exclusion from `V01-17` | 0.5 ed |

**Charter errata, written here for a later stage.** `E36` — `:505-512`, the ten-id `[drivers]
enabled`, superseded by thirteen; sole home [04](../04-driver-system.md) §10.1. `E37` — `:4425-4450`,
the `[operational]` key list, which gains `drivers.resolve.*`, and `:4392-4398`, which gains the
enumeration rule. `E38` — `:2498`, the 23-row day-one signal registry, superseded by
[05](../05-ingest-and-routing.md) §5.1's per-key table. `E39` — `:100`, "L0 ACQUIRE acquire/1 drivers
(fs, url, connectors)", superseded by [02](../02-architecture.md) §3.1's core-side `discover.py`.

**Ordering.** ADR-1 renames `[retrieval.vec] max_blocks` to `max_segments`, which is a
`tools/config_axes.toml` pattern at charter `:4440`. **Consequence 3 must be written against
`retrieval.vec.max_segments`**, and ADR-1's priority 1 makes that ordering already correct.

**What becomes harder.** Adding a `[[rule]]` that names an unshipped driver now costs an
`expect_unavailable` declaration and a lint check that fails the day the driver ships. Adding a config
key now costs a pattern **and** a line in `omniweave.toml.example` — G18's "exactly" clause is
bidirectional and this ADR makes both directions enforceable for the first time. A future reader must
not re-add `drivers.*.config` to `[operational]`: it is at `:4413`, and the second copy is a gate
failure.

## Open

**What `ow doctor` prints on a fresh install.** This ADR fixes the exit-1 conditions and does not
enumerate the warnings, which depend on the host. **Interim position:** `V01-15`'s acceptance fixture
asserts only `exit == 0` and that no warning names a driver in `[drivers] enabled`. **Fallback:** if
warning volume on a clean 4-core machine exceeds ten lines, the fixture pins the byte-exact output the
way `ow surface emit` pins the front door, and the pinned block lives in [10](../10-interfaces.md)
§7.5. The evidence that closes it is the first `V01-15` run — which this ADR is what makes possible.

**Whether `R-A8`'s second trigger holds on a scanned corpus.** Unmeasured, and `V01-15`'s corpus is
"100 born-digital office documents" ([00](../00-vision.md):880), which cannot exercise it. The measure
is `V01-15` re-run against F20's 5,000-page legal matter ([00](../00-vision.md):808); the fallback is
decision 8's three profiles.
