# FORK-TRIGGER — `anydoc`

A fork trigger is **the written, testable condition under which omniweave takes ownership of a
vendored dependency** ([glossary](../../_plan/glossary.md), "Fork trigger"). It is *a priced option,
not a cost paid before shipping*: nothing in this file is work anyone is doing today, and the whole
value of writing it down is that the day a condition fires, the response is already decided and
already costed.

16-roadmap.md:1137 fixes the shape — **two named clauses** — and 16-roadmap.md:1130 fixes the bar:
*"Every vendored component has a `FORK-TRIGGER.md` naming a **testable** condition."* Testable means
a command in this repository answers it, so each clause below names the command.

**What a fork costs, stated once so no clause has to restate it.** A fork is a Rust crate omniweave
then owns forever: a compiled build on nine CI cells, a `cargo` toolchain in the release pipeline, a
second security surface to patch, and the end of NG-9 — 00-vision.md:434, *"Not a compiled-code
owner. Exactly one compiled dependency exists, it is someone else's published `abi3` wheel, and we
do not build it."* Firing a clause is therefore a decision, not an automatic consequence; what the
clause guarantees is that the decision is **made**, with the evidence in hand, rather than deferred
by not noticing.

---

## Clause 1 — anydoc emits a source address per Block

**The condition.** `anydoc::Block` gains a per-block source address — a `w:p` / `a:t` child-index
path, an OPC part plus node path, or any other address that resolves back into the source package.

**The test.**

    uv run pytest packages/omniweave-office/tests/unit/test_office_card.py \
                  -k origin_span_is_none_and_the_reason_is_checkable

That test reads the eight `Block` variants out of the installed wheel's own type stub and asserts
that **none** of them carries an address field. It is written to fail the day this clause fires,
which is the only form of tripwire that cannot be forgotten. The vendored warrant is
`src/model/block.rs`, and 03-document-model.md:1564 states the count: eight variants — `Heading`,
`Paragraph`, `List`, `Table`, `BlockQuote`, `CodeBlock`, `Rule`, `Math` — *none carrying a source
address*, while `Asset` alone carries `origin_part` (`src/model/asset.rs:14-15`).

**What changes, and it is not a fork.** This clause is the one whose response is *cheaper* than a
fork: if upstream ships the address, omniweave reads it. `driver.toml`'s `origin_span` becomes
`"exact"`, `os.k` becomes `"nodepath"` — INV-10's second branch, `nfc(node_text(part, path))`, which
has no producer at release 1 — and the `VERBATIM` tier opens on the office path. 00-vision.md:173
names this as the clause that "opens the tier", 09-generation.md:2256 makes it the reason a `pptx`
artefact's `read_back` blocks cannot be `verbatim` today, and 05-ingest-and-routing.md:3229 records
it in the worked trace beside the disclosure it lifts.

**The fork is the fallback, not the plan.** Ownership is taken only if the address is *refused*
upstream and the `VERBATIM` tier on office documents is judged to be worth a compiled build. The
first change in such a fork is the one already named: emit the child-index path, nothing else.

**What this clause does NOT license.** It does not license inferring an address. A `w:p` index
reconstructed by re-parsing the package on omniweave's side would be an address omniweave computed,
not one the decoder recorded, and INV-10 is a statement about what the *extractor* saw. Until the
decoder records it, `origin_span = "none"` is the honest card and `corpus_card.verbatim_fraction`
discloses the consequence before any query runs.

---

## Clause 2 — F2's marshal breach

**The condition.** `rss.gen5000p_peak_bytes` exceeds **1 610 612 736 bytes (1.5 GiB) ± 10 %** on the
nightly run. 12-performance.md:245 states the mechanism and the verdict in one row: *"anydoc marshals
eagerly into Python objects and `py.detach` does not cover the marshal, so this row is the fork's
tripwire and not merely a budget."* 00-vision.md:712 carries it as V01-11 and 12-performance.md:591
as the parse ceiling.

**The test.**

    uv run ow bench inproc      # 12-performance.md:1471 — wall, peak RSS and GIL-held fraction
                                #   at max_inproc in {1,2,4,8}, over fixtures/office-200,
                                #   against the pure-Rust path

**Why this is a fork and clause 1 is not.** `py.detach` (`python/src/lib.rs:194`, the vendored
warrant for the whole S1 seam) releases the GIL around *the decode* and nothing else. The marshal
that follows — the whole `Document`, every `Block`, every `Asset`'s bytes, turned into Python
objects in one call — runs with the GIL held and allocates a full copy of the document in the host's
address space. That is R-T17 (17-risks.md:210) in full: `Isolation.INPROC` buys a saved IPC hop
against a full copy, and at `max_inproc = 2` the copy may dominate the hop.

The fix is upstream-shaped and omniweave cannot write it from Python: a **single-buffer return** — a
streaming or zero-copy handover that does not materialise the document twice — which is exactly what
04-driver-system.md:1832 and 16-roadmap.md:1177 name as the fork's first change. DP9 (P3 exit, week
26) is the decision point and the Parse lead is the owner.

**The cheaper response that must be tried first.** Dropping `parse.office.anydoc` from
`[isolation] inproc` costs one config line and moves the driver to S4, where the marshal happens in
a worker process whose RSS is bounded by `memory_mb` and reaped on exit. That is not a fork and it
is not a regression in correctness — only in latency, and only by one IPC hop per document against
anydoc's 4.4 ms median decode. **A fork is justified only when that hop has been measured and is the
binding cost**, which is what `ow bench inproc` is for.

---

## Not clauses, and the distinction is deliberate

Three conditions in the plan touch this dependency and pull a **different lever**. They are listed
here because a reader looking for "what happens if anydoc goes wrong" will otherwise assume this
file is the only answer, and would then read two clauses as covering five situations.

| condition | where | the lever it pulls |
|---|---|---|
| ≥ 3 platform-support issues attributable to `firecrawl-anydoc` in the first two releases, **or** an `abi3` break on a supported cell | R-E5, 17-risks.md:223 | **DP13**, two releases after v1.0: move office behind an `omniweave[office]` extra. The dependency row is the only thing that changes; the laptop-minimum profile *drops* from 44 MB to 29 MB. Not a fork |
| upstream is abandoned or the crate is yanked | 16-roadmap.md:1130's exit rule | the wheel is pinned exactly and this tree is the source at that pin, so the corpus keeps decoding. The response is a scheduled decision, not an outage |
| `pdf-inspector` reintroduces an unbounded parser | 14-security.md:1517, 1759 | not reachable from this driver: PDF is excluded from the card's twelve formats and `to_document()` refuses it outright. See `NOTICE` section 3 |

## Review

This file is reviewed whenever the `firecrawl-anydoc` pin moves, which `tools/gate_pins.py` makes a
visible event, and whenever a clause's test changes shape. `tools/gate_vendor.py` asserts that this
file exists, that both clauses still name a runnable command, and that the digests in
`anydoc.sha256` still describe the tree — because a fork trigger over source nobody can verify is a
promise about bytes that may already have changed.
