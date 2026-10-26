# omniweave, in fifteen minutes

omniweave indexes documents into a local SQLite corpus, keeps page and polygon provenance for every
passage, serves cited passages to an agent over MCP, and compiles agent output back into editable
PPTX and DOCX. It is local-first and makes no network call by default.

This document is the file to read before the code. It is **not** a copy of the design record: the
nineteen plan documents are the design record and they grow, while this file is short on purpose
and is held to the code by a test — `packages/omniweave-core/tests/unit/test_architecture_doc.py`
parses the tables below, imports every symbol they name, and checks every command, gate and
register file against its register. The table cannot drift from the code without the suite going
red, which is the only reason a document like this is worth writing.

## 1. The one-way flow

Seven layers, and data moves in one direction. The names are the ones the code uses.

```text
L0  acquire   bytes in, content-addressed, canonicalised
L1  parse     a driver reads bytes and emits BlockDrafts over a frame protocol
L2  store     the host writes rows: the pivot every other layer reads
L3  graph     segments, entities, claims -- derived, never authoritative
L4  retrieve  channels -> fuse -> ceiling -> a Verdict that explains a zero
SERVE         the CLI, the SDK and the MCP tools, all generated from one registry
L6  out       compile an artefact, then read it back as an ordinary document
```

Three properties hold that shape together, and each is enforced rather than intended.

**A driver never holds a store handle.** A `parse/1` driver gets blobs in and returns drafts out;
the host stamps provenance after the driver returns. That is why `omniweave_ports` has an empty
dependency list and why a third-party driver cannot pin the framework.

**A cite is a durable public name.** `d1#3` names one block, survives a re-parse of an edited
document, and may appear in somebody else's document — so it is minted once and rebound, never
renumbered.

**A zero is explained or it is not reported.** Retrieval that finds nothing runs fifteen absence
gates before it may say so; a gate that fires makes the answer `degraded` with a cause and a fix
command, and only a genuinely empty result reads `absent`. `omniweave_core.retrieve.verdict` has
exactly one site that returns the absent state, deliberately.

## 2. The distributions

One box is one wheel. `deps` includes first-party edges, because a reader who cannot see them
cannot check `tools/layers.toml` against this table.

| dist | import package | what it ships | deps |
|---|---|---|---|
| `omniweave-ports` | `omniweave_ports` | the third-party-facing type surface and four of the five Port protocols | none |
| `omniweave-core` | `omniweave_core` | the host: digests, identity, errors, limits, config, probes, discovery, resolution, the store and the lazy subpackages | ports |
| `omniweave` | `omniweave` | the CLI, the SDK, the surface registry and its generators, the router, the Supervisor, the planner, the host graph passes, install and hooks | core, ports, office |
| `omniweave-office` | `omniweave_office` | `parse.office.anydoc` across the office family | ports, anydoc |
| `omniweave-pdf` | `omniweave_pdf` | `parse.pdf.pdfium` — text layer, glyph runs, page geometry, rasters | ports, pypdfium2 |
| `omniweave-serve` | `omniweave_serve` | the MCP stdio and http transports | core, ports, mcp |
| `omniweave-graph` | `omniweave_graph` | the free `derive/1` passes | ports |
| `omniweave-llm` | `omniweave_llm` | the billed `derive/1` passes, reaching a model through the service seam | ports |
| `omniweave-target-pptx` | `omniweave_target_pptx` | `compile.pptx.native` and `parse.pptx.native` | core, ports, python-pptx |
| `omniweave-target-docx` | `omniweave_target_docx` | `compile.docx.native` and `parse.docx.native` | core, ports, python-docx |
| `omniweave-target-deck` | `omniweave_target_deck` | `compile.deck.native` — a card and a toolchain spec, no renderer | core, ports |
| `omniweave-target-video` | `omniweave_target_video` | `compile.video.native`, declared and not implemented | core, ports |
| `omniweave-vision` | `omniweave_vision` | `parse.page.olmocr`, and nothing else | ports, torch |
| `omniweave-conform` | `omniweave_conform` | the conformance suites, the testkit, the eval harness, the reducers, the cassette codec and the scoreboard | core, ports, pytest |
| `omniweave-langchain` | `omniweave_langchain` | the LangChain loader, retriever and tool adapter. An attachment: separately versioned, not on the release train | core, ports, langchain |

The ports/core split is physical, not stylistic. `omniweave-ports` is versioned by Port major
rather than by the release version, so a driver's floor is a Port range and a core upgrade is never
blocked by a driver's resolver constraint.

## 3. Where to look

Every symbol in this table imports, and the test proves it.

| to understand | read |
|---|---|
| the surface a driver writes against | `omniweave_ports.types.FailureClass`, `omniweave_ports.CostClass` |
| what a document is | `omniweave_core.model.block.Block`, `omniweave_core.model.doc.Doc` |
| the closed vocabularies | `omniweave_core.model.enums.Kind`, `omniweave_core.model.enums.Layer` |
| a table's exactly-once grid | `omniweave_core.model.grid.build_grid` |
| how a driver declares itself | `omniweave_core.drivers.card.DriverCard`, `omniweave_core.drivers.card.load_card` |
| how drivers are found | `omniweave_core.discovery` |
| the store, and reading it back | `omniweave_core.store.sqlite.connect_readonly`, `omniweave_core.store.docread.StoreDocReader` |
| retrieval's four steps | `omniweave_core.retrieve.channels`, `omniweave_core.retrieve.fuse`, `omniweave_core.retrieve.ceiling`, `omniweave_core.retrieve.verdict` |
| every agent-facing surface | `omniweave.surface.registry.ACTIONS` |
| how a pass is chosen and paid for | `omniweave.route.evidence`, `omniweave.route.rung` |
| what the evaluator measures | `omniweave_conform.labels.load`, `omniweave_conform.judge.judge`, `omniweave_conform.rollup.rollup`, `omniweave_conform.structure.score` |
| the statistics every number carries | `omniweave_conform.stats.macro` |
| the benchmark registry | `omniweave.run.bench.SUBJECTS` |
| why time is injected, never read | `omniweave_core.clock.Clock` |

Two rules explain most of what looks unusual in the tree. `omniweave_core` has no third-party
dependency and a gate proves it, so anything that needs one lives in a driver distribution. And
nothing in library code reads the clock: a `Clock` is passed in, because a test that cannot control
time measures the machine instead of the code.

## 4. The registers

A register is a committed file that some gate reads. Editing one is a reviewed act; the gate is
what makes the register load-bearing rather than documentation.

| file | holds |
|---|---|
| `tools/gates.toml` | the CI gate series, one row each, with an owner and a review date |
| `eval/gates.toml` | the metric gates: the budget, the guard band and the definition of every published number |
| `tools/layers.toml` | the import layering, derived from the entry points |
| `tools/weights.toml` | the per-distribution installed-size ceilings |
| `tools/licences.toml` | what omniweave itself may depend on |
| `tools/vendor.toml` | every vendored artefact, with its digest and its notice |
| `tools/egress.toml` | every URL and host literal in shipped code |
| `tools/events.toml` | the structured events a run may emit |
| `tools/config_axes.toml` | every configuration axis, and which ones a cache key reads |
| `tools/redact.toml` | what never reaches a log |
| `codes.toml` | every `OW-` error code; append-only against the previous tag |
| `eval/inventory.toml` | the test inventory, byte-diffed against collection |

## 5. Running it

```console
$ uv sync --frozen --all-packages --group dev
$ uv run pytest -n auto -m "not conform"      # the fast tiers
$ uv run pytest -m conform                    # the conformance tier, separately
$ uv run ow doctor                            # every resolved config value, with its source
$ uv run ow add <path> && uv run ow query "a question"
$ uv run ow eval run && uv run ow eval release-check
```

The gates run in CI and every one of them is runnable here. `G1` proves the core's dependency
closure, `G2` the weight ceilings, `G3` the licence policy over three graphs, `G16` that the last
releases' driver cards still load, `G19` that an incremental re-index equals a full one, `G22` the
scale run, `G25` that every generated surface matches its registry, and `G27` that the documents
themselves are machine-checked — this file included.

## 6. What is not here yet

The release notes carry the full list; three absences shape the code more than the rest. No
confidence signal is calibrated, so no digit is rendered anywhere. Vector retrieval is off by
default and ships no encoder. And format detection does not ask drivers to sniff their own formats,
so a third-party driver can add a reader for a format the host already recognises and not a new
one.
