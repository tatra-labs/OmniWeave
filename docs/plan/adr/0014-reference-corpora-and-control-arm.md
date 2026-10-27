# ADR-14 — `bench/serve/`'s corpora, tasks, control arm and agent are specified well enough to build: seven rulings on what D602 and RK-Q4 leave open

**Status:** Accepted (2026-09-29, with D14.7 added at acceptance) · **Priority:** 14 of 14 · **Price:** 10.5 ed
**Deadline:** before the P7 exit ([16](../16-roadmap.md) §10, week 42). `uv run pytest bench/serve -q --tasks all` is one of the seven exit commands ([16](../16-roadmap.md):745), and it is the only one that fails on this build. It fails by design: it names `D602` and runs no task.
**Discharges:** one open question of [17](../17-risks.md) §Open questions, `RK-Q4` (17:961-973). Two items the build ledger records as **owed to the plan**: `D602`'s corpora, and its control-arm toolset (the same question as RK-Q4, reached from the build side). Also one internal contradiction found while drafting: the Cassette's recording sites (Item 4).
**Charter errata claimed:** `E102`, `E103` (block `E102`-`E107`, four unused)
**Supersedes:** none
**Blocks / unblocks:** unblocks W7.7b (the scripted agent, its Cassettes, and the corpora; `D602`'s *"next cell"*). It makes 22 of the 30 tasks runnable at P7. The 8 `damaged` tasks wait on 13 §8.6's Injector set, which is P6's absence suite and is not built (D14.2 part 4). It reads after [ADR-13](0013-v01-acceptance-reconciliation.md), whose D13.4 kept `--tasks all` in the exit list *"as printed"* because it *"waits on `D602`'s corpora and the scripted agent, which are work to be done, not a conflict"*. This ADR is the part of that work that is a decision rather than a build.

## Context

**Like ADR-13, this is not one of the fifty-two audit rows.** RK-Q4 is one of 17's own eight open questions (17:468), and `D602` was found by building. So `charter_defects_open` does not move whatever this ADR's status is. What it shares with ADR-1 to ADR-13 is the question: *which printed statement binds, and what does the other one become*.

The instrument, 13 §8.8, verbatim (13:1360-1363): *"The instrument is **30 scripted tasks** over three reference corpora (`F20`: a 5,000-page legal matter, a 137-document data room, a 60-document personal archive), driven by a scripted agent with a fixed tool budget"*. The four task classes are 8 / 8 / 6 / 8 (13:1365-1370). The pairing rule, the `Control guard` and the dated gate rows (13:1372-1397, :1944-1963) are fully specified, and W7.7a built all of them: `bench/serve/serve_harness.py`'s `outcome()`, `report()`, `mcnemar_worse()` and `ControlGuard`, and the catalogue schema in `tasks.toml`. Their numbers are in the ledger's W7.7a batch (14 of 14 mutants caught). **What is not specified is everything the harness runs *on*.** Five items follow, each re-verified against the current plan documents.

### Item 1 — the three corpora exist nowhere, and the rules that govern fixtures do not say which rules they fall under (`D602`)

- 13:1361 and charter:8607 (F20) name three corpora by shape: *"a 5,000-page legal matter, a 137-document data room, a 60-document personal archive"*. F20's own row adds one word, *"three **real** corpora"*, and its measurement is the budget tiers re-keyed onto block counts (12:405, 17:515), due at **v1.0**.
- None of the three is in the tree. `fixtures/` holds `gen/`, `generated/` and `incremental/`, with no `docs/`, no `index.toml` and no `cassettes/` (35 MB in all).
- 13 §4.1's tiers (13:433-438) put a byte in the repository under Tier A: *"≤ 64 MB total, ≤ 4 MB per binary"*. A real 5,000-page matter does not fit, and neither would a 137-document room of real filings with exhibits. Tier B, `omniweave-golden`, does not exist. Tier C is a pointer manifest, and 13:486 forbids a fixture *"fetched at test time"*.
- 13 §4.2 (13:459) makes `generated` the **preferred** provenance whenever *"a phenomenon can be synthesised"*, and gives *"a 5,000-page PDF"* as its own example. 13:464-470 makes real scans non-negotiable, because *"a wholly synthetic corpus flatters the parser"*.
- `D602`'s objection to writing the catalogue now: *"a task is a question with a known answer over a known document, so thirty invented against documents nobody has would be ground truth by assertion"*.

So one printed statement says **real**. Two printed rules make real corpora of this size uncommittable, and prefer generated ones. None of them says which of the three is binding for the v0.1 harness.

### Item 2 — thirty tasks need an answer key, and the `damaged` class needs a mechanism that does not exist

- A task is `{id, class, corpus, source, prompt, expect}` graded by casefolded `contains` / `forbids` substrings, never by a model judge (W7.7a's *"Decided here"* list).
- 13 §4.5 (13:550-570) makes an assertion set a derivative work in its own right: `derived_from_sha256` on every assertion, and a refusal above *"`min(2000 chars, 10%)` of any one source document"* quoted.
- The `damaged` class is *"one `Injector` applied"* (13:1370). 13 §8.6 defines thirteen Injectors (13:2118). **None is built**: no module defines one, and P6's exit command `ow eval run --suite absence` (16:690) is not a verb (`ow eval` is not in the generated tree).

### Item 3 — the control arm is a comparison, not a configuration (`RK-Q4`)

17:961-973, verbatim: *"What is **not** specified anywhere is the control arm's own toolset: which host tools it has (`Read`, `Grep`, a shell), which converter it uses per format, and its stopping rule. … a control arm using a *bad* converter rigs `R-E2`'s trigger in our favour. **Closes:** [quality](../13-quality.md) naming the control arm's converter per format and its stopping rule, with the bias recorded: **use the best available converter for each format**"*.

The harness already fixes the host tools' **names** (`serve_harness.py`: `HOST_READ = "Read"`, `HOST_GREP = "Grep"`, `HOST_SHELL = "Bash"`, and `SHELL_READERS`, D601). 13:1362's *"fixed tool budget"* prints no number.

### Item 4 — the scripted agent's model calls have no Cassette site

- 13:1402-1403: *"**every model call goes through a Cassette**, the scripted agent included"*. 17:267 (R-A3's mitigation) repeats it.
- 13 §7.3 (13:971-973): *"A Cassette is … recorded at exactly two sites: `DriverIO.service()` and `omniweave_core.modelserver`. Those are **the only two outbound model channels a driver has** (INV-6), so there is no third place a model call can hide"*. Charter:7050-7053 says the same, and `omniweave_core/cassette.py`'s `SEAMS` is exactly that pair.
- The scripted agent is not a driver. Its model calls are the agent's own turns, and they pass through neither seam. So 13:1402 requires a recording that 13:971 says has nowhere to happen.
- The workspace lock holds no model client, and nothing in the tree makes a model call over the network.

### Item 5 — `V-Q2` closes `V01-15` on corpora `V01-15` does not use

[00](../00-vision.md):806-811 (V-Q2): *"*Closes:* the V01-15 acceptance test on the three reference corpora named in F20"*. [00](../00-vision.md):716 (V01-15 itself), as ADR-13 D13.1 left it: *"over a folder of 100 born-digital office documents"*, and `bench/serve/first_answer.py` measures exactly that folder (`D634`).

## Decision

**D14.1 — the v0.1 reference corpora are generated to F20's three shapes, with one real public-domain scanned slice; F20's measurement on real corpora stays at v1.0.**
1. **Three committed generators** under `fixtures/gen/`, each writing into a cache directory at test time. Nothing they write is committed as bytes, so Tier A's 64 MB is untouched. Their outputs are pinned by sha256 in `fixtures/gen/EXPECTED.sha256`, as `gen_5000p_pdf.py`'s already is.

   | corpus id | shape | content |
   |---|---|---|
   | `legal_matter` | 5,000 pages over ~120 born-digital PDFs | pleadings, an MSA and its amendments with numbered sections, correspondence, deposition transcripts |
   | `data_room` | 137 documents | DOCX, XLSX and PPTX from `first_answer.py`'s office generator, plus PDFs; supplier agreements, cap tables, board decks |
   | `personal_archive` | 60 documents | letters, statements and receipts. Generated because a real personal archive can be neither public domain nor consented |

2. **Every fact a task asks about is planted by its generator**, the way `first_answer.py` plants agreement 042. The answer key and the documents come from one source, so the key is ground truth **by construction**. That is `D602`'s objection met rather than waived. The assertion set's provenance is `authored` (13:459), and it is redistributable because it quotes nothing third-party.
3. **The scanned slice is real** (13:464-470): 12 US federal public-domain scans under 17 U.S.C. §105 (13:460), committed under `fixtures/docs/` as Tier A bytes, each ≤ 4 MB, each with a `.meta.toml` and a generated `fixtures/index.toml` row (`Q-G1`). They are filed into `legal_matter` as exhibits.
   - The slice exists because the harness's born-digital/scanned split (13:1399-1401) is exactly where an agent *should* re-read, and a generated scan would flatter both arms.
   - **Sourcing is a maintainer action**, reviewed under 13 §4.2's `public_domain` row, and nothing fetches them at test time.
4. **F20 is unchanged.** Its question, *"are the budget tiers right for documents"*, is a v1.0 measurement over three **real** corpora, and generated stand-ins cannot answer it. The v0.1 corpora bear F20's shapes, not its authority. `eval_run.corpus_digest` names the generated corpora, and no number they produce may be reported as F20's.
- **Sole home:** 13 §8.8, whose :1361 sentence names the generated stand-ins and points at this ruling.

**D14.2 — the thirty tasks, and what the `damaged` class waits on.**
1. **The split** is 13:1365-1370's, by class, across the three corpora:

   | class | `legal_matter` | `data_room` | `personal_archive` | n |
   |---|---:|---:|---:|---:|
   | `citation` | 4 | 2 | 2 | 8 |
   | `retrieval` | 2 | 4 | 2 | 8 |
   | `absence` | 2 | 2 | 2 | 6 |
   | `damaged` | 3 | 3 | 2 | 8 |
   | **total** | 11 | 11 | 8 | 30 |

2. **Six tasks have `source = "scanned"`**, all in `legal_matter` over the real slice, so the scanned half of 13:1399's split has an n. Their answers are authored against the scan by a contributor. They carry `derived_from_sha256` and obey 13:560's quotation limit.
3. **An `absence` task's expectation is a named cause.** `contains` holds the absence (*"no … arbitration in Singapore"*), and `forbids` holds the invented answer. This is `false_confident_zero` on the agent surface (13:1369).
4. **A `damaged` task applies an Injector from 13 §8.6 and re-implements none.** The Injector set's sole home is the absence suite (13:2118, INV-21). The harness imports it. It does not own a second copy.
   - **Interim position with pre-committed fallback:** until the absence suite exists, `--tasks all` runs the 22 undamaged tasks and reports the 8 as UNMEASURED, naming the missing Injectors, and `test_a_task_run_needs_…` fails on them by name.
   - **Fallback:** if the absence suite has not landed by the P7 exit, the P7 exit command passes on 22 tasks with the eight printed as owed, and the `Control guard`'s first nightly run is over 22 pairs. Its `n` is printed beside its p-value, so a reader sees the loss of power.

**D14.3 — the control arm is a configuration: the same agent with the server removed, the best converter per format, a twelve-call budget.** This closes RK-Q4.
1. **One agent, two arms, one difference.** Both arms use the same model, sampling, system prompt, host tools, converters and tool budget.
   - The omniweave arm additionally has `omniweave-serve` over stdio: its `tools/list`, tool names prefixed `mcp__omniweave__` as a host prefixes them (10:898), and its `instructions` string delivered on `initialize` exactly as a host receives it.
   - The control arm has neither. Nothing else differs, so a difference in `task_accuracy` is the server's.
2. **Host tools are `Read`, `Grep` and `Bash`, emulated in-process by the harness**, read-only, rooted at the corpus directory, with no network and no real shell.
   - `Bash` runs only `SHELL_READERS` (D601), parsed and executed by the harness, and refuses every other command.
   - `Read` returns at most 2,000 lines per call, with `offset` and `limit`, which is the host's own window.
   - The names are the host's the harness already counts (D601), because Claude Code is the first `AgentTarget`.
3. **Converters, best available per format, and the same for both arms.**

   | format | what `Read` returns |
   |---|---|
   | PDF | each page's text layer via pypdfium2, the engine `parse.pdf.pdfium` uses. A page with no text layer is returned as its page image, as a host's `Read` renders a PDF page |
   | DOCX, XLSX, PPTX | anydoc's text, the engine `parse.office.anydoc` uses |
   | text, markdown, CSV | the bytes, UTF-8 |

   **The bias, recorded as 17:971 requires.** The control arm converts with the engines omniweave itself trusts, and falls back to vision where omniweave has no OCR. It therefore cannot be the straw man RK-Q4 warns about. A difference between the arms is retrieval, provenance and absence, never conversion quality, and that is the comparison R-E2's trigger (17:220) reads.
4. **The stopping rule.** A task ends when the model returns a turn with no tool call, and that turn's text is the graded answer. The fixed tool budget of 13:1362 is **12 calls per task**, identical in both arms.
   - Twelve gives the control arm room for several `Grep` → `Read` cycles, so the budget is not what decides.
   - A task that spends its twelfth call is graded on its last text and flagged `budget_exhausted` in the report. Exhaustion is counted per arm, never hidden.
- **Sole home:** 13 §8.8, as a configuration table beside the task-class table.

**D14.4 — the scripted agent records at a third Cassette site, `bench.agent`, which only `bench/` can reach.**
1. **13 §7.3's *"exactly two sites"* and charter:7052's *"the only two outbound model channels a driver has"* are statements about the framework.** They stay true of everything that ships. The scripted agent is not a driver, and `bench/` is not shipped.
2. **Everything else is 13 §7.3's, unchanged:**
   - the key `sha256_canonical({service, model_key, prompt_digest, sampling, payload_digest, contract})`, with `service = "agent"` and `contract = ("bench.agent", HARNESS_MAJOR)`;
   - storage under `fixtures/cassettes/agent/`;
   - redaction;
   - the three modes;
   - staleness;
   - the orphan sweep;
   - the caps, 256 KiB per interaction and 32 MiB in all (13:1896-1897).
   - `prompt_digest` covers the canonical messages and tool definitions. A committed recording holds the response and the key's inputs, not the request body. The request is re-derivable from the fixtures and the harness, and a request carrying page images would breach the per-file cap for no reviewer's benefit.
3. **`omniweave_core.cassette.Seam` is not extended.** The site lives in `bench/serve/`, which is outside every shipped distribution, so no shipped module can import it.
   - It reuses core's `sha256_canonical` key recipe, `CassetteMode`, `MAX_CASSETTE_BYTES`, header redaction and the `<service>/<key[:2]>/<key>.json` layout.
   - It writes its own record envelope, because core's `Interaction` and `ContractIdentity` are typed to the two framework seams, and widening them is the rejected alternative below.
4. **The model** is configured, not hard-coded (D14.7), and recorded in `MeasuredOn.model_key`, at temperature 0 where the model takes one and at its own default where it refuses the parameter, as `claude-sonnet-5` and the GPT-5 family do (D650). A change of model is a re-record, reviewed like a golden change (13:983). **The committed recordings' default is `claude-sonnet-5`**, a host-class model, because the harness stands in for a host.
   - The clients are stdlib `urllib`, in `bench/serve/`. No SDK enters the lock, and G3 does not move.
5. **Recording and replay.**
   - Recording runs in `allow` mode with whatever provider D14.7's configuration names. A key, where the provider needs one, is read from an environment variable and 13:981's redaction keeps it out of every file.
   - CI and the nightly two-arm job run `required`, where a miss is `OW-Q-004` and never a live call (13:982). CI's `golden` job audits the recordings without a model (`run.py --audit-cassettes`: decode, key, place, caps), and the nightly job replays them over the full-scale corpora, which do not fit a pull request's four minutes (D650).
   - **The consequence, stated rather than discovered:** any change to omniweave's answer bytes changes the next turn's request, so it is a miss until re-recorded. That is 13:1402's *"a tool-description change is a reviewable cassette diff"*, extended to every byte the agent reads.
   - A full re-record is at most 30 tasks × 2 arms × 13 turns = 780 calls.
- **Sole home:** 13 §7.3, whose site sentence gains the harness clause, with 13:1402 pointing at it.

**D14.5 — `V-Q2` closes on `V01-15`'s own corpus, and the three reference corpora report `first_answer_seconds` without gating it.**
- [00](../00-vision.md):808-809's *"on the three reference corpora named in F20"* becomes *"on V01-15's own folder of 100 born-digital office documents (`bench/serve/first_answer.py`); `first_answer_seconds` over each of D14.1's three corpora is reported beside it and gates nothing"*.
- 00:716 is unchanged, and it is the criterion.
- **Sole home:** 00 §Open questions, V-Q2.

**D14.7 — the harness is accessible, configurable, and has a fast profile.** Added at acceptance, from the maintainer's direction that everything be *"accessible, customizable, but providing an efficiency option, and usable"*.
1. **Accessible.** The default, `cassette = "required"`, replays the committed Cassettes and calls no provider at all: no key, no network, no GPU, which is the `contributor-parity` claim (13:986-989) extended to the harness. The provider and model still name the recordings, because they are in every key. Recording is provider-neutral, with two live providers:
   - `anthropic`, the Messages API;
   - `openai`, the Chat Completions wire, which also serves local model servers (Ollama, vLLM, llama.cpp, LM Studio), so recording needs no paid key.
2. **Configurable.** One file, `bench/serve/agent.toml`, holds every knob:
   - `[agent]`: `provider`, `model`, `base_url`, `api_key_env`, `temperature`, `max_tokens`, `tool_budget = 12`;
   - `[run]`: `arms`, `tasks`, `scale`, `workers`, `cassette`.
   - Every key has an `OW_BENCH_<KEY>` environment twin and a flag, resolved flag > environment > file > default, which is R-A8's precedence (17:272).
   - The report prints each resolved value with its source.
   - A changed provider, model or budget is a different Cassette key, so it records beside the committed set and can never be mistaken for it.
3. **A fast profile.** `scale = "full"` is D14.1's shapes, and the only scale with committed recordings and a reportable number. `scale = "quick"` keeps every planted fact and all thirty tasks, and cuts the filler about twentyfold (`legal_matter` at 250 pages).
   - Generated corpora and their ingested stores are cached by `(generator digest, scale)` under `$OMNIWEAVE_HOME/bench-cache/`, so a re-run skips generation and `ow add`.
   - `workers` runs tasks in parallel, one isolated agent each.
   - `--tasks` takes ids, classes or corpora.
   - A `quick` row is watermarked `scale: quick`, and never enters a gate or a published number.
4. **Usable.** One command, `uv run bench/serve/run.py`, beside the pytest entry of 16:745, prints a plain report. Every refusal names its fix:
   - no key: the variable to set, or `--provider replay`;
   - a Cassette miss: the `--record` command;
   - an unreachable local server: its `base_url`.
- **Sole home:** `bench/serve/agent.toml`'s own comments, with 13 §8.8 pointing at it.

**D14.6 — two charter errata are claimed from ADR-14's block (`E102`-`E107`).** The rows are written here, and a later stage inserts them into charter §9.2, as for ADR-1 to ADR-13. Neither re-issues any of D1-D10.

| # | charter locus | search phrase | what the charter says | what supersedes it |
|---|---|---|---|---|
| **E102** | :7050-7053 | `the only two outbound model channels a driver` | Cassettes are intercepted at two sites, *"so coverage is complete by construction"* | **ADR-14 D14.4.** True of every shipped model call. `bench/serve/`'s scripted agent records at a third, bench-only site, `bench.agent`, under the same key, storage, modes and caps. Sole home [13](../13-quality.md) §7.3 |
| **E103** | :8607 | `Run bench/serve/ against three real corpora` | F20's measurement, over three real corpora | **ADR-14 D14.1.** Unchanged in substance, and scoped. F20 is measured at v1.0 over three real corpora, and the v0.1 harness's generated stand-ins with F20's shapes never report as F20. Sole home [17](../17-risks.md)'s F20 row |

## Alternatives rejected

### D14.1: source three real corpora now, into Tier B or C

This is the reading F20's *"real"* invites, and it is the right corpus for F20's own question.
- Tier B does not exist, and building `omniweave-golden` (a versioned ZIP artefact, a fetch path, digest re-verification; 13:436) is its own work item.
- Tier C is a pointer, and 13:486 forbids fetching at test time, so the nightly job could not run the tasks.
- A real legal matter's party filings are not public domain even where its opinions are, so its licence review is per document.
- Above all, every answer key over a real corpus is authored by reading it. That is thirty `authored` assertion sets, where planted facts cost nothing and cannot drift from their documents.
Rejected for v0.1. It is exactly what F20 does at v1.0.

### D14.1: an all-generated corpus, scans included

It is the cheapest option, and it keeps Tier A empty. But 13:464-470 is explicit that generated scans have *"no feeder skew, no bleed-through … no staple shadow"*, and the scanned slice of 13:1399 is where the harness's most important reading happens. Rejected. Twelve real scans are the least that makes the slice mean something.

### D14.3: give the control arm a deliberately plain converter (`pdftotext`, or no DOCX support)

It is closer to *"whatever the host happens to use"*. But that is precisely what 17:966-969 calls rigging R-E2 in omniweave's favour. And no plain converter is in the lock without a new licence review (G3). Rejected.

### D14.3: no tool budget, and stop only on a final answer

It is the most host-like option. But a control arm that loops on `Grep` would never end, a Cassette set would be unbounded, and 13:1362 prints *"a fixed tool budget"*. Rejected.

### D14.4: make the scripted agent a script, with no model

This would need no Cassette, no key and no network. But F19's mis-pick rate (charter:8606) and `source_reread_rate` are measurements of a model's choices. A scripted pick measures the script. Rejected.

### D14.4: add `bench.agent` to `omniweave_core.cassette.Seam`

It would be one enum and one code path. But it puts a bench-only site into `omniweave-core`, the package INV-2 keeps to the framework's own vocabulary, and it lets shipped code name it. Rejected. The key recipe and the storage layout are shared as functions, not as a seam.

## Consequences

| obligation | document and locus | price |
|---|---|---|
| the three generators, their `EXPECTED.sha256` rows, and planted-fact tables | `fixtures/gen/gen_legal_matter.py`, `gen_data_room.py`, `gen_personal_archive.py` | 3.0 ed |
| the twelve public-domain scans, their `.meta.toml` sidecars, and the generated `fixtures/index.toml` (`Q-G1`'s first rows) | `fixtures/docs/`, `fixtures/index.toml` | 1.0 ed, a maintainer's review included |
| the thirty tasks; six authored against scans | `bench/serve/tasks.toml`; `test_harness.py`'s strict xfail becomes a pass | 1.5 ed |
| the agent loop, the in-process host tools and the converters; the two arms | `bench/serve/agent.py`, `host_tools.py` | 2.0 ed |
| the `bench.agent` Cassette site and the `urllib` client; record and replay | `bench/serve/agent_cassette.py`; `fixtures/cassettes/agent/` | 1.0 ed |
| D14.7: three providers, `agent.toml` with its environment twins and flags, the `quick` scale, the corpus and store cache, parallel tasks, `run.py` and its refusals | `bench/serve/models.py`, `agent.toml`, `run.py` | 1.0 ed |
| 13 §8.8's corpus sentence and configuration table; §7.3's site sentence; :1402's pointer | [13](../13-quality.md):1361, §8.8, :971-973, :1402 | 0.3 ed |
| V-Q2's closure | [00](../00-vision.md):808-809 | 0.1 ed |
| RK-Q4 marked closed; F20's row scoped | [17](../17-risks.md):961-973, :515 | 0.1 ed |
| the two charter errata inserted | charter §9.2 | 0.1 ed |
| the index row; `D602` marked discharged | this directory's README §7; `_notes/build-defects.md` | 0.1 ed |
| **total** | | **10.2 ed**, rounded to 10.5 for the review round-trip |

All plan edits keep their line counts, as ADR-13's did. About 2,900 citations in the code point into these documents by line number.

**What becomes harder.**
- **Every retrieval or rendering change re-records the harness.** The nightly job is `required`, so an answer change it has not seen fails it. That is the price of a reproducible adoption number. The re-record needs the maintainer's key and at most 780 calls.
- **The v0.1 numbers are over generated documents.** Planted facts in synthetic prose are easier to retrieve than the same facts in a real data room. A reader must not read v0.1's `task_accuracy` as a claim about real corpora; that claim is F20's at v1.0.
- **The `damaged` class waits on P6's Injectors.** If they are late, the first `Control guard` runs over 22 pairs rather than 30.

**What a future reader must not do.**
- Must not let a shipped module import `bench.agent`'s site, or count it among 13 §7.3's framework seams.
- Must not give either arm a converter the other lacks.
- Must not report a number over D14.1's corpora as F20's.
- Must not re-implement an Injector in `bench/serve/` to unblock the `damaged` class.

## Open

**Which provider and model make the committed recordings.**
- Replay needs nothing. Recording needs a provider: a paid key, or a local server under `openai`. Which one the committed set uses is a cost and access question the maintainer owns.
- **Closes:** the first committed recording, whose `MeasuredOn.model_key` states it.
- **Fallback:** any host-class model at temperature 0 serves. The model is one `agent.toml` key, and a change is a re-record.

**The Injector set** (D14.2 part 4).
- **Closes:** P6's absence suite, `ow eval run --suite absence` (16:690).
- **Fallback:** D14.2's 22-task P7 exit, with the eight printed as owed.

**Whether the emulated host predicts real hosts** (RK-Q8, 17:1020-1030, and 16's R-Q2).
- The scripted agent has Claude Code's tool names, window and PDF behaviour. It is not Claude Code, and F19 is ultimately a question about real MCP hosts.
- **Closes:** at v1.0, one real-host run of the thirty tasks per `AgentTarget`, compared against the scripted arm's mis-pick rate.
- **Fallback:** if a real host's rate differs from the scripted one by more than one Wilson width, the scripted rate is reported as the harness's and F19's decision reads the real host's.
