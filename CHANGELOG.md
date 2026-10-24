# 0.1.0 - unreleased

The first release. omniweave indexes documents into a local SQLite corpus, keeping page and
polygon provenance. It serves cited passages to an agent over MCP, and compiles agent output back
into editable PPTX and DOCX. It is local-first and makes no network calls by default.

## What ships

- **Fourteen distributions on one release train**, all `py3-none-any`:
  - `omniweave`: the `ow` CLI, the SDK, and the router, supervisor and planner.
  - `omniweave-core` and `omniweave-ports`, the core and the driver-facing types. Neither has
    any third-party dependency.
  - Drivers and targets, installed as extras (`pip install "omniweave[recommended]"` adds MCP
    serving, PDF and PPTX).
- **Parsing:**
  - PDF through pdfium;
  - the office family (DOCX, PPTX, XLSX and others) through anydoc;
  - ten text formats through the standard library;
  - native DOCX and PPTX readers that round-trip with their compilers;
  - scanned pages through a vision model (`omniweave-vision`). This is a billed call, and it
    waits for your approval.
- **Serving.** `ow serve --mcp` speaks stdio, and `ow serve --http --api-key <key>` speaks MCP
  Streamable HTTP. The default profile lists `ow_add`, `ow_corpora`, `ow_open` and `ow_query`,
  and the full profile lists thirteen tools. `llms.txt` describes every tool and is generated
  from the same registry.
- **Compiling.** `compile.pptx.native` and `compile.docx.native`. Two compiles of the 40-unit
  golden are equal on all nine CI cells: three OSes, three Python versions.
- **Wiring an agent.** `ow install --target auto` writes the agent's configuration and records
  the sha256 of each file it writes. `ow uninstall` restores each file byte for byte.
- **Guarantees, each held by a gate:**
  - a passage claimed as verbatim matches its stored source exactly;
  - an export and re-import reproduces the store exactly;
  - a process killed at any statement boundary of a store commit converges on restart;
  - an incremental re-index equals a full one;
  - `ow cost --by driver` reconciles with the run manifest's spend to the micro-unit.
- **A third-party driver** written against `omniweave-ports` alone passes all eleven mandatory
  conformance suites, provided its format is one the host already detects (see below).

## Known limitations

- **A third-party driver cannot add a new file format yet.** Format detection does not ask
  drivers to sniff their own formats (step 4 of the detection ladder). A driver for a format the
  host does not already recognise installs and passes conformance, but `ow add` cannot route its
  files to it. This is deferred past 1.0.
- **Accuracy rates are not published.** The parse suite scores ordering, tables and fields
  against labelled fixtures, but those labels are drafted and not yet human-verified. Until they
  are, `ow eval release-check` reports every accuracy rate as unknown. `structure_f1` and
  `doc_acc` have no harness yet.
- **Honesty measures are partial:**
  - `degradation_detection` covers 4 of the 13 planned damage types;
  - `false_confident_zero` is measured over 13 questions, below the minimum sample, so it reads
    unknown;
  - `hallucination_rate` does not apply, because no field-extraction driver ships;
  - judge agreement (Q-G20) needs 100 double-labelled items and is deferred past 1.0.
- **Performance figures are indications, not budgets.** They come from a developer workstation
  and GitHub-hosted runners: warm `ow query` p50 was 95 ms on a 5,000-page, 210,001-block store.
  The pinned benchmark machine the budgets are defined on does not exist yet. The 100,000-unit
  scale run executes nightly on a hosted runner as an indication.
- **Very large spreadsheets are refused.** A sheet of about 4 million cells exceeds anydoc's
  `max_xml_nodes` limit, and the office worker's 1 GiB memory limit is reached from about 280,000
  cells. Both limits are kept as shipped.
- **Two compile targets are declared but not implemented.** `compile.deck.native` and
  `compile.video.native` refuse with their reason.
- **The query ledger is off.** The `events.owstore` sidecar, and `ow doctor`'s D-14 check of it,
  are deferred past 1.0.
- **The agent adoption benchmark is incomplete.** Six scanned-document tasks wait on
  public-domain scans. Four citation tasks need re-recording after a retrieval change, and their
  replay fails until then.
