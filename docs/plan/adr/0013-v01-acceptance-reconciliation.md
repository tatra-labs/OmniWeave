# ADR-13 — v0.1's acceptance set says what the built system can be measured against: five rulings on seven owed items

**Status:** Accepted · **Priority:** 13 of 13 · **Price:** 3.5 ed
**Deadline:** before the P7 exit ([16](../16-roadmap.md) §10, week 42) — v0.1 ships on [00](../00-vision.md) §9.1's seventeen criteria *"verbatim"* ([16](../16-roadmap.md):752-753), so a criterion that cannot pass as written blocks the release rather than a later phase
**Discharges:** no row of [17](../17-risks.md) §§7.3-7.4. Seven items the build ledger records as **owed to the plan**: `D615` item 7, `D629` item 5, `D313`, `D314`, `D375`, `D624` item 4, and the `D631` finding re-read against charter §5 C9
**Charter errata claimed:** `E96`, `E97` (block `E96`-`E101`, four unused)
**Supersedes:** none
**Blocks / unblocks:** unblocks the P7 exit list ([16](../16-roadmap.md):741-748), five of whose seven commands cannot pass as printed; moves `V01-11`, `V01-12` and `V01-15` from PARTIAL-by-construction to PARTIAL-by-measurement only. Waits on nothing. Touches `V01-11` beside [ADR-11](0011-eval-register-reconciliation.md)'s worker-scoped RSS ruling, and must be read after it.

## Context

**This ADR is a different kind from ADR-1 to ADR-12, and says so first.** Those twelve discharge the fifty-two `defect` rows the plan's audit found in [17](../17-risks.md) §§7.3-7.4 (§5 of this directory's README). None of the items below is one of those rows. Each was found by **building** the system and running v0.1's acceptance set against it, and each is recorded in `_notes/build-defects.md` with the words *"Owed to the plan"*. So `charter_defects_open` does not move whatever this ADR's status is, and `R-O9` does not see it. What it shares with the twelve is the question it asks: *"which of these two printed statements is binding, and what does the other one become"*.

`tools/acceptance_v01.py` reads, on this build: **PASS 11, PARTIAL 3, FAIL 0, UNMEASURED 3**. The three UNMEASURED are V01-10 and V01-11, which are slow and read PARTIAL under `--slow`, and V01-14, whose CI is off until P10. The PARTIAL rows are V01-3 (a 20-distribution environment and a pinned runner, neither of which exists before P10; D622), V01-12 and V01-15. **V01-11, V01-12 and V01-15 are PARTIAL because their own text cannot hold**, not because a measurement is missing. The sections below quote each item, then the plan sites it contradicts, re-verified line by line against the current plan documents.

### Item 1 — `V01-15`'s cite *"carrying a page"* over an office corpus (`D615` item 7, `D634`)

[00](../00-vision.md):716, verbatim: *"`first_answer_seconds` ≤ **600 s** *(new)*: on a clean 4-core machine with no GPU, offline after install, the sequence `ow install` → `ow add ~/docs` → `ow query "<question>"` returns an Answer with at least one `cite` carrying a page, over a folder of 100 born-digital office documents"*. [16](../16-roadmap.md):734-737 repeats it as P7's demo.

[03](../03-document-model.md) §12.5 (:2267-2282) defines five page kinds. The row that office documents fall under, at :2275: *"`stream` | there are no pages: HTML, markdown, code, plain text, email. Always `page = 0`"*. The row above it gives a slide a page (`slide` | *"a slide index"*), but the shipped office driver cannot produce one: `parse.office.anydoc` writes every document as one page of kind `stream`, because anydoc flattens a PPTX's slides into one block stream with no slide boundary in its model, and a DOCX has no page boxes. `omniweave_office/driver.py`'s `_page_record` records exactly that, rather than a made-up slide box. Measured in `D634`: over 100 generated agreements, a third each DOCX, PPTX and XLSX, every cited block is on a `stream` page, in every run.

`page` is 0-based and *"the original index"* (03:2271), so a cite's page number cannot tell a stream from a document's first page. Only `page_kind` can. The criterion is therefore **unsatisfiable by construction over its own corpus**. It is not failing for want of work.

### Item 2 — `V01-11` names a fork trigger its own fixture cannot fire (`D629` item 5)

[00](../00-vision.md):712: *"Peak RSS on the 5,000-page fixture ≤ **1,610,612,736 bytes** (1.5 GiB) ± 10% | `rss.gen5000p_peak_bytes`; a breach fires `vendor/anydoc/FORK-TRIGGER.md`"*. The charter's budget row (charter:7600-7605) carries the same note: *"THE FORK-TRIGGER GATE. anydoc marshals eagerly into Python objects and py.detach does not cover the marshal. A breach fires vendor/anydoc/FORK-TRIGGER.md."*

- The 5,000-page fixture is `fixtures/gen/gen_5000p_pdf.py`'s output, a **PDF**.
- `vendor/anydoc/FORK-TRIGGER.md` says *"PDF is excluded from the card's twelve formats and `to_document()` refuses it outright"*. So `parse.pdf.pdfium` parses the fixture, and anydoc never sees it.
- pdfium's card caps its worker at `memory_mb = 1024`, below the row's 1.5 GiB, so the worker is killed before the row can breach.
- The row therefore bounds a driver it does not name, and it can never fire the tripwire it does name.

[12](../12-performance.md):228 already scopes the row to `process = "worker"`, and [ADR-11](0011-eval-register-reconciliation.md) made RSS budgets worker-scoped. What neither says is *which* worker, or where anydoc's tripwire goes. F2 (charter:8589), the measurement that tripwire belongs to, names *"`ow bench inproc` over `fixtures/office-200` … plus the `rss.gen5000p_peak_bytes` nightly budget"*. That is an office corpus and a PDF budget in one cell.

`D629` also found the row read two-sided. `Budget.breaches` flagged the first 42 MB worker as *"outside"* the band, while 00:712 prints the criterion as `≤`. The measured worker peak is **551,612,416 B**.

### Item 3 — `V01-12`'s `instructions` cap and its seventh artefact (`D313`, `D314`)

[00](../00-vision.md):713: *"`tools/list` for `profile=default, compact_schemas=true` ≤ **1,900 tokens** …, per-tool ≤ 700, `instructions` ≤ 1,000 chars; all **seven** generated agent-facing artefacts byte-identical"*.

- **The cap.** [10](../10-interfaces.md):909-911 asserts `len(s) <= 1000` *"for all four `variant × profile` combinations"*. Measured (`D313`):

  | variant | profile | characters |
  |---|---|---:|
  | A | `default` | 977 |
  | B | `default` | 996 |
  | A | `full` | 1,031 |
  | B | `full` | 1,050 |

  10:907's own fix (*"resolved by the generator dropping the `Decks, reports, video` sentence"*) recovers 80 characters against an overshoot of 111. Its 118-character deferral line is 132 as emitted.
  - The 1,000 figure is a convention and not a limit. 10:866-868 gives jcodemunch's `_MCP_INSTRUCTIONS_MAX_CHARS = 1000` as *"the precedent"*.
  - V01-12 scopes its whole row to `profile=default`, where both variants pass.
- **The seventh artefact.** 10:203 says *"`ow surface emit --check` byte-diffs them"*, all seven. Artefact 2, the `instructions` string, has no path in any document (`D314`). It is delivered on `initialize` and never written, which is the reason it survives tool deferral (10:863). What gates it instead is 10:2596's frozen `instructions_chars` baseline plus the cap test.

### Item 4 — P7's exit list names commands that do not exist (`D375`, `D624` item 4)

[16](../16-roadmap.md):741-748:
```bash
uv run ow surface emit --check                       # G25: seven artefacts byte-identical
uv run tools/gate_hook_latency.py                    # G26: p95 <= 250 ms warm / 1 s cold
uv run ow install --check && uv run ow uninstall --check     # byte-identity reversal
uv run pytest bench/serve -q --tasks all
uv run tools/gate_schema_budget.py                   # SV2: 1900 total / 700 per tool / 1000 chars
uv run tools/gate_listed_subset_enabled.py           # SV1
uv run tools/acceptance_v01.py                       # V01-1 .. V01-17 from 00-vision.md 9.1
```
- **Line 744.** [10](../10-interfaces.md):1428 gives `ow uninstall` no `--check`. W7.5's *"`ow install | uninstall | --check`"* ([16](../16-roadmap.md):719) is three verbs, not two verbs with a flag each. And `ow install --check` *"exits 9 when not configured"* (10:1780), so on a clean machine `&&` never reaches the second command. The reversal the comment names is 10 §7.4's G-install symmetry gate. It runs as `packages/omniweave/tests/unit/test_gate_install.py`, and end to end as `bench/serve/first_answer.py`'s reversal (`D634`).
- **Lines 746-747.** `tools/gates.toml` is *"THE authority on how many gates there are"* and has no row for SV1 or SV2. So a `tools/gate_*.py` without a row is a gate the register does not know, and one with a row takes a `G` number, which is an ADR (`D375`).
  - SV2 is enforced today by `packages/omniweave/tests/unit/test_gen_budget.py`.
  - SV1 is enforced by `test_surface_registry.py` and `test_surface_startup.py` (`-k sv1`).
  - G25's own register row already rules the neighbouring case: *"No tools/ script is named by the plan; the emitter is `gen/` inside the CLI distribution, not a tools/ gate."*

### Item 5 — the `--render json` error object spells the symbol `symbol` (`D631`)

- **Charter §5 C9, as the charter restates it at :748:** *"`code` IS THE SYMBOL on the wire and in storage, never the numeric OW-T-311 (§5 C9). The numeric is the human form"*. At :6864-6866: *"§5 C9 makes the SYMBOL the stored and wire form and the numeric the human form — and this list previously had no symbols at all, while §6.1 mandated returning a NUMERIC on the MCP wire, which C9 forbids."*
- **[10](../10-interfaces.md):1539-1540's `--render json` error object:** `{"schema":1,"error":{"code":"OW-A-002","symbol":"OW_CORPUS_NOT_FOUND","message":"…","fix":"…"}}`. It puts the **numeric** under `code`, which is exactly what C9 forbids.
- **[18](../18-api-sketch.md):898's `--json-errors` object:** `code`, `numeric`, `message`, `fix`, `exit`. That is C9-conformant.
- **What shipped.** W7.8x followed each document for its own flag, so the build now prints two error objects in which `code` means different things (`D631`). The ledger recorded the conflict as owed. Read against C9, it is not a conflict between two documents: it is **10:1539 against the charter**, and the charter is immutable.

**Why this is a decision rather than a repair.** Each item has two readings a careful implementer could defend. Items 1 and 2 need a criterion to change what it asks, and a criterion is what v0.1 ships on *"verbatim"*. So choosing is a ruling, and a ruling is what an ADR is for.

## Decision

**D13.1 — `V01-15`'s cite clause reads by page kind.** [00](../00-vision.md):716's *"at least one `cite` carrying a page"* becomes *"at least one `cite` that `ow open` resolves, carrying its page wherever the cited page's `page_kind` is not `stream` ([03](../03-document-model.md) §12.5)"*. The same edit applies to [00](../00-vision.md):894's `first_answer_seconds` row and [16](../16-roadmap.md):736. A PDF, a scan or a document whose driver emits slides still owes a page. An office document from a driver that has none owes a resolvable cite, which is what a user needs from it.
- **Sole home:** 00:716.
- **The instrument:** `bench/serve/first_answer.py` already reports `paged` and the page kinds, and judges it this way. Its exit changes from *"`paged` is reported, not required"* to *"`paged` is required unless every cited page is `stream`"*.

**D13.2 — `rss.gen5000p_peak_bytes` bounds the worker that parses its fixture, as a one-sided ceiling, and anydoc's tripwire moves to an office budget.** Three sub-rulings:
1. **The row bounds the S4 worker of the driver the catalog resolves for `gen_5000p_pdf`**, which is `parse.pdf.pdfium` on the shipped roster. It is measured by the host's job-wide sample (`Worker.peak_rss()`, `D629`) and written to `work.peak_rss_bytes`. A card whose `memory_mb` sits below the row makes the row unreachable for that driver, and the row says so rather than implying a breach is possible.
2. **Every RSS row in [12](../12-performance.md) §4.1 is a one-sided ceiling**: a measurement passes at or below `value × (1 + tol_pct/100)`. The ± in 00:712 is the tolerance's width, not a lower bound. A worker using less memory is never a breach.
3. **The fork-trigger clause leaves this row.**
   - 00:712's *"a breach fires `vendor/anydoc/FORK-TRIGGER.md`"*, 12:245, 12:591 and the charter note are struck.
   - A new nightly budget row, `rss.office200_peak_bytes`, carries it instead: the peak RSS of `parse.office.anydoc`'s worker over `fixtures/office-200`, the corpus F2 already names. Its value is set at 1,610,612,736 until F2 measures it.
   - **Interim position with pre-committed fallback:** `fixtures/office-200` did not exist (`D196`); `fixtures/gen/gen_office200.py` generates it and `tools/ow_bench.py inproc` measures the row (`D656`). Until it did, the tripwire has no automated gate, and FORK-TRIGGER.md's clause 2 (*"`ow bench inproc` over `fixtures/office-200`"*) is run by hand before each release.
   - **Fallback:** if `fixtures/office-200` does not exist by the P10 exit, when CI returns, the tripwire is re-homed to `parse.office.p50_ms` (charter:7594), the one office budget that runs, with its `note` carrying the clause. The move is recorded in FORK-TRIGGER.md.

**D13.3 — `V01-12` is the default profile's, and artefact 2 is gated by its baseline rather than by a byte-diff.**
- **The cap.** The 1,000-character cap binds `profile = "default"`, both variants. That is 00:713's own scope, and the only profile a host sees unless it opts in.
  - [10](../10-interfaces.md):909-911 is amended to the two default variants.
  - `profile = "full"` gets its own ceiling, **1,100 characters**: the measured 1,050 plus 50, against the next deferral-line change.
  - 10:898 and 10:907 are corrected to 132 characters and 1,031/1,050.
- **Artefact 2.** [10](../10-interfaces.md):203 and 00:713 become *"the six file artefacts byte-identical (G25), and the `instructions` string held to the frozen `instructions_chars` baseline (10:2596) and the cap"*. The sole home is 10 §2.3.

**D13.4 — P7's exit list names what exists.** [16](../16-roadmap.md):741-748 becomes:
```bash
uv run ow surface emit --check                       # G25: six file artefacts byte-identical
uv run tools/gate_hook_latency.py                    # G26: p95 <= 250 ms warm / 1 s cold
uv run pytest packages/omniweave/tests/unit/test_gate_install.py   # G-install: byte-identity reversal
uv run pytest bench/serve -q --tasks all
uv run pytest packages/omniweave/tests/unit/test_gen_budget.py     # SV2
uv run pytest packages/omniweave/tests/unit/test_surface_registry.py packages/omniweave/tests/unit/test_surface_startup.py -k sv1   # SV1
uv run tools/acceptance_v01.py                       # V01-1 .. V01-17 from 00-vision.md 9.1
```
- **SV1 and SV2 take no `G` row and no `tools/` script.** That is G25's precedent, applied one artefact over.
- **`ow uninstall --check` is not created.** A flag no document declares, added so that an exit command can pass, would be the plan following the code's accident.
- **`--tasks all` stays as printed.** It waits on `D602`'s corpora and the scripted agent, which are work to be done, not a conflict.

**D13.5 — both error objects spell the symbol `code`, as charter §5 C9 requires.**
- [10](../10-interfaces.md):1539-1540's object becomes `{"schema":1,"error":{"code":"OW_CORPUS_NOT_FOUND","numeric":"OW-A-002","message":"…","fix":"…"}}`.
- [18](../18-api-sketch.md):898's `--json-errors` object is unchanged: `code`, `numeric`, `message`, `fix`, `exit`.
- One error vocabulary, in which `code` means the same thing on both flags and on the MCP wire. The sole home is 10 §6.3, which 18 §2.1 cites.

**D13.6 — two charter errata are claimed from ADR-13's block (`E96`-`E101`).** The rows are written here, and a later stage inserts them into charter §9.2. Neither re-issues any of D1-D10. D6's budget mechanism and D2's page model are untouched; only what one budget row is attached to changes.

| # | charter locus | search phrase | what the charter says | what supersedes it |
|---|---|---|---|---|
| **E96** | :7600-7605 | `THE FORK-TRIGGER GATE` | `rss.gen5000p_peak_bytes`'s note: *"A breach fires vendor/anydoc/FORK-TRIGGER.md"* | **ADR-13 D13.2.** The row bounds the S4 worker of the driver resolved for `gen_5000p_pdf`, as a one-sided ceiling. The fork trigger moves to `rss.office200_peak_bytes`. Sole home [12](../12-performance.md) §4.1 |
| **E97** | :8589 | `plus the rss.gen5000p_peak_bytes nightly budget` | F2's measurement names the PDF budget beside an office corpus | **ADR-13 D13.2.** *"plus the `rss.office200_peak_bytes` nightly budget"*. Sole home [17](../17-risks.md)'s F2 row |

## Alternatives rejected

### D13.1: make the office driver emit a page per slide

This is the strongest alternative, because it makes the criterion true rather than rewording it.
- 03 §12.5 already has a `slide` kind, and a PPTX cite that says *"slide 7"* is what a user wants.
- Rejected because the flattening is inside anydoc's Rust model (`src/formats/pptx`). Recovering slide boundaries is a fork, and the fork has its own tripwire, which has not fired.
- It would also still leave DOCX, a third of the corpus, pageless: a DOCX's pages are a layout engine's output, and this framework runs none.

**Close.** If the fork fires for F2's reason, this becomes the natural first change after the single-buffer return, and D13.1's `stream` exception then applies to DOCX and XLSX alone.

### D13.1: change the corpus to office plus PDF

This keeps *"carrying a page"* verbatim, and a mixed folder is more realistic.
- Rejected because it moves the criterion off the thing it measures. `first_answer_seconds` is the time to a first cited answer for the common case the vision names, a folder of office documents.
- A PDF in the folder makes the page clause pass by the needle's luck, not by the office path working.

### D13.2: keep the fork trigger on `gen_5000p_pdf` by routing the PDF through anydoc

This is technically impossible: anydoc refuses PDF by design (FORK-TRIGGER.md, and `parse.office.anydoc`'s twelve formats). Stated so that no one retries it.

### D13.2: delete the RSS row

This is simpler: the row cannot breach under pdfium's `memory_mb`, so it measures nothing new.
- Rejected because the row is the only whole-document RSS measurement on the shipped path, and its number is real: 551,612,416 B.
- `memory_mb` can be raised on a card, and the row is what would notice.

### D13.3: trim the `full` text to 1,000

This keeps one cap.
- Rejected because each trim removes steering or a tool name, and every candidate was checked:
  - The deferral line cannot drop `ow_corpora`, because variant B tells the agent to call it first.
  - The cite-form and untrusted-content sentences are safety text.
  - Only the first paragraph's lag sentence is expendable, and it recovers 44 of 50.
- A cap that exists by precedent does not outrank the text it caps.

### D13.3: give artefact 2 a committed file

This makes G25's *"seven"* literal.
- Rejected because a committed copy of a string whose bytes the baseline already pins is a second home.
- It would also be a byte-diff on text no host ever reads from disk.

### D13.4: register SV1 and SV2 as `G29` and `G30`, each with a `tools/` script

This is the most literal reading of 16:746-747, and a numbered gate is harder to delete than a test.
- Rejected on `D375`'s reasoning: each would be a script that runs one pytest file, taking an ADR-numbered row to wrap it.
- G25's register row already refused the same shape.
- **Close.** If CI's `gates` job ever needs to schedule SV1 and SV2 apart from the unit tier, this becomes the right answer, and it is one ADR.

### D13.5: keep 10:1539's object and change 18:898 to match it

This means one edit, to the flag nobody has shipped against.
- Rejected because the charter is immutable and C9 is unambiguous, so 10 would still be wrong.

## Consequences

| obligation | document and locus | price |
|---|---|---|
| V01-15's cite clause, and the glossary row and demo that repeat it | [00](../00-vision.md):716, :894; [16](../16-roadmap.md):736 | 0.2 ed |
| `first_answer.py`'s exit requires `paged` unless every cited page is `stream`; a test per branch | `bench/serve/first_answer.py`, `test_first_answer.py` | 0.3 ed |
| `rss.gen5000p_peak_bytes`'s note and scope; RSS rows one-sided; the new `rss.office200_peak_bytes` row | [00](../00-vision.md):712; [12](../12-performance.md) §4.1, :228, :245, :591; `eval/perf.toml` | 0.5 ed |
| FORK-TRIGGER.md clause 2 re-pointed; the P10 fallback recorded in it | `vendor/anydoc/FORK-TRIGGER.md` | 0.2 ed |
| `measure_store.py --gate-rss` names the resolved driver and its `memory_mb` beside the verdict | `tools/measure_store.py` | 0.3 ed |
| SV2's scope and the `full` ceiling; the corrected arithmetic; artefact 2's gate | [10](../10-interfaces.md):203, :898, :907-911; `gen/budget.py`'s `full` ceiling; `test_gen_instructions.py`'s two xfails become passes | 0.5 ed |
| V01-12's artefact clause | [00](../00-vision.md):713 | 0.1 ed |
| P7's exit list | [16](../16-roadmap.md):741-748 | 0.1 ed |
| 10:1539-1540's example; `switches.error_object()` swaps `code`/`symbol` for `code`/`numeric`; the seven `test_*_verb.py` error-object tests | [10](../10-interfaces.md) §6.3; `omniweave/surface/switches.py` | 0.5 ed |
| the two charter errata inserted | charter §9.2 | 0.1 ed |
| `acceptance_v01.py`'s V01-11, V01-12 and V01-15 gap texts rewritten to what remains (clean machine, `ow-bench-1`) | `tools/acceptance_v01.py` | 0.2 ed |
| the index row, and `D313`, `D314`, `D375`, `D615` §7, `D624` §4, `D629` §5 and `D631` marked discharged | this directory's README §7; `_notes/build-defects.md` | 0.1 ed |
| **total** | | **3.1 ed**, rounded to 3.5 for the review round-trip |

**Types that change shape.** One: the `--render json` error object's `error` member renames `symbol` to `numeric` and changes what `code` holds.
- It is a public surface frozen at P7 ([16](../16-roadmap.md) §10's *"Frozen at the end of P7"* lists the Answer and `ActionSpec`, not the error object, but a script parsing it is a consumer).
- So D13.5 must land before v0.1 ships, or it is a breaking change after.
- No schema file publishes the error object today, so no `schema/` file moves.

**What becomes harder.**
- **V01-15 can pass on an all-office corpus with no page.** A future reader must not take that as evidence that office cites are page-addressable; the page kinds are printed beside the verdict for that reason.
- **anydoc's tripwire is manual until `fixtures/office-200` exists.** The fallback bounds how long.
- **The `full` profile's ceiling is 10% above the default's.** A future reader must not raise the default's to match: the default is what every host sees.

**What a future reader must not do.**
- Must not add `ow uninstall --check` to make 16:744's old text pass.
- Must not read a `stream` page 0 as "page 1".
- Must not attach the fork trigger to any PDF budget.

## Open

**`fixtures/office-200` did not exist** (`D196`); `fixtures/gen/gen_office200.py` generates it since `D656`.
- **Closes:** the fixture, with F2's `ow bench inproc` over it.
- **Fallback:** D13.2's re-homing to `parse.office.p50_ms` at the P10 exit.

**`V01-15`'s clean 4-core machine.** Nothing in the build can provide one. `first_answer.py` prints the machine it ran on and never calls it clean.
- **Closes:** the `contributor-parity` container of V01-14, which is *"a clean container with no network, no GPU, no Node"* (00:715). It is the natural host for a 4-core-capped run once CI returns at P10.
- **Fallback:** until then, V01-15 is PARTIAL on the machine clause alone, and a measured 22.8-27.0 s against 600 s (`D634`) is the indication.

**Whether `profile = "full"` is ever the default for a host.**
- If one ships it as a default, D13.3's premise that the default profile is what every host sees fails. The `full` ceiling then drops to 1,000, and the text is trimmed as the rejected alternative describes.
- **Closes:** any `AgentTarget` whose `install` writes `profile = "full"`.
- **Checked:** none does today.
