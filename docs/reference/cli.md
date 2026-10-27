# `ow` command reference

**GENERATED** by `ow surface emit --docs`. Do not edit: the `gates.reference_docs` job
assertion byte-diffs this directory, so a hand edit fails CI and the next emit overwrites it.

Generated from `omniweave.gen.cli_tree.commands()`, which is also what builds `ow`'s argparse tree.

Every command below is one Action of `omniweave.surface.registry.ACTIONS`. A flag's
`kind` is the type its value parses as; `switch` takes no value.

## `ow add`

Index files, directories or URLs into a corpus so ow_query can cite them; billable work defers with the command that approves it

Action: `add`

| argument | kind | detail |
|---|---|---|
| `source` | str | `SOURCE`; nargs `+` |
| `--dry-run` | switch | default `False` |
| `--schema` | str | `PATH`; a JSON Schema; sets unit.schema_requested |
| `--allow-cost` | int | `MICROS`; approve billable work up to this many micros |
| `--allow-egress` | str | `GRANT`; the grant id that permits a fetch |
| `--wait` | int | `S`; seconds to wait before reporting pending |

## `ow corpora`

List what this server can read and what is in each corpus: counts, formats, known gaps, freshness and the capability floor

Action: `corpora`, `corpus.coverage`

| argument | kind | detail |
|---|---|---|
| `corpus` | str | `CORPUS`; nargs `?` |
| `--detail` | str | one of `list`, `card`, `coverage`, `actions`; default `list` |
| `--summarize` | switch | write the corpus abstract, recording a producer |
| `--scope` | str | `SCOPE` |

## `ow cost`

Spend by driver over a corpus's ledger or one run, with what the cache saved, and the run's reconcile against its manifest

Action: `cost.report`

| argument | kind | detail |
|---|---|---|
| `--by` | str | `BY`; default `driver` |
| `--since` | str | `SINCE` |
| `--run` | str | `RUN` |
| `--verify` | switch | default `False` |

## `ow doc diff`

Compare two generations of one document: what carried, what was revised, what is new, and whether the newer generation was quarantined rather than committed

Action: `doc.diff`

| argument | kind | detail |
|---|---|---|
| `ref` | str | `REF` |
| `--from-gen` | int | `FROM_GEN` |
| `--to-gen` | int | `TO_GEN` |

## `ow doc grid`

Read one table as an exactly-once grid: every cell at its slot, the header row and column, and the merges that would otherwise be counted twice

Action: `doc.grid`

| argument | kind | detail |
|---|---|---|
| `ref` | str | `REF` |

## `ow doctor`

Check this deployment: every resolved configuration value with its source, the driver and toolchain probes, and a fix command for every warning

Action: `doctor`

| argument | kind | detail |
|---|---|---|
| `--runtime` | switch | default `False` |

## `ow eval bless`

Rewrite eval/inventory.toml from the test collection and append the BLESS.log row a fall in its counts needs; OMNIWEAVE_BLESS=1 and a reason are required

Action: `eval.bless`

| argument | kind | detail |
|---|---|---|
| `--counters` | switch | default `False` |
| `--inventory` | switch | default `False` |
| `--reason` | str | `REASON` |

## `ow eval publish`

Export the .oweval scoreboard into the committed eval/results tree, every row whatever its direction, or with --check report which files differ

Action: `eval.publish`

| argument | kind | detail |
|---|---|---|
| `--oweval` | str | `OWEVAL`; default `eval/omniweave.oweval` |
| `--results` | str | `RESULTS`; default `eval/results` |
| `--check` | switch | default `False` |

## `ow eval release-check`

Refuse a release on any unknown run, metric or perf row, and on any hard eval/gates.toml gate off its budget or unmeasured; --strict also on a suite never run

Action: `eval.release_check`

| argument | kind | detail |
|---|---|---|
| `--oweval` | str | `OWEVAL`; default `eval/omniweave.oweval` |
| `--gates` | str | `GATES`; default `eval/gates.toml` |
| `--strict` | switch | default `False` |

## `ow eval run`

Run eval suites over the metric register's subjects and write their runs and metrics to the .oweval in one transaction; this build measures four of seven

Action: `eval.run`

| argument | kind | detail |
|---|---|---|
| `--suite` | str | `SUITE` |
| `--deterministic-half` | switch | default `False` |
| `--subject` | str | `SUBJECT` |
| `--witness` | str | `WITNESS`; default `self` |
| `--cassette` | str | `CASSETTE`; default `off` |
| `--validate-judge` | switch | default `False` |
| `--emit` | str | `EMIT` |
| `--oweval` | str | `OWEVAL`; default `eval/omniweave.oweval` |
| `--gates` | str | `GATES`; default `eval/gates.toml` |

## `ow explain`

Resolve an OW-* code or symbol to what it means and the exact command that clears it; reads no corpus, so it answers on a machine with no store at all

Action: `explain`

| argument | kind | detail |
|---|---|---|
| `code` | str | `CODE` |

## `ow graph doctor`

Check the graph's operability: the residue signals against their thresholds, the trust clamp, the entropy gate, anchor counts, candidate pairs and report states

Action: `graph.doctor`

| argument | kind | detail |
|---|---|---|
| `--check` | str | `CHECK` |

## `ow graph locate`

Find where on the page an entity, claim, edge or mention was witnessed: one location per witness, with its page, its span and its polygon or the reason none

Action: `graph.locate`

| argument | kind | detail |
|---|---|---|
| `--entity` | str | `ENTITY` |
| `--claim` | str | `CLAIM` |
| `--edge` | int | `EDGE` |
| `--mention` | int | `MENTION` |

## `ow graph merge`

Record that two entities are one, with a reason, and settle the graph again: the closure, the communities and the salience, as an ingest would

Action: `graph.merge`

| argument | kind | detail |
|---|---|---|
| `first` | str | `FIRST` |
| `second` | str | `SECOND` |
| `--reason` | str | `REASON` |

## `ow graph merges`

Show the resolution decision log: each closure's members, and every merge or split decision with its stage, score, guards and the generation it was decided in

Action: `graph.merges`

| argument | kind | detail |
|---|---|---|
| `--entity` | str | `ENTITY` |

## `ow graph plan`

Show, per billed lane, how much the free passes covered, the share a billed pass would be handed, and the calls and tokens that projects, before anything runs

Action: `graph.plan`

Takes no argument.

## `ow graph residue`

Show what the graph could not place: unresolved references grouped by kind and name, and quarantined rows grouped by code and kind

Action: `graph.residue`

| argument | kind | detail |
|---|---|---|
| `--akind` | str | `AKIND` |

## `ow graph review`

Show what the graph holds below extracted, weakest first: fuzzy-merged closures, tainted and overloaded entities, and the mentions and edges to check

Action: `graph.review`

| argument | kind | detail |
|---|---|---|
| `--over-merge` | switch | default `False` |

## `ow graph split`

Record that one entity is two or more, named by the blocks each is witnessed in, with a reason, and settle the graph again as an ingest would

Action: `graph.split`

| argument | kind | detail |
|---|---|---|
| `entity` | str | `ENTITY` |
| `--into` | str | `INTO` |
| `--reason` | str | `REASON` |

## `ow graph types`

List the entity-type vocabulary with each type's live entities, or promote proposed types into it, with a reason

Action: `graph.types`

| argument | kind | detail |
|---|---|---|
| `--promote` | str | `PROMOTE` |
| `--reason` | str | `REASON` |
| `--propose` | switch | default `False` |

## `ow graph why`

List every entity, edge and claim the graph says one block asserts, each with its span in the block's text

Action: `graph.why`

| argument | kind | detail |
|---|---|---|
| `--cite` | str | `CITE` |

## `ow hooks check`

Run each installed hook command as its host would, with a probe payload in a scratch project, and say which failed and why

Action: `hooks.check`

Takes no argument.

## `ow install`

Wire agent hosts to omniweave: the MCP entry, one permission wildcard, the instruction block, hooks and the core skill, each recorded in a receipt

Action: `install`

| argument | kind | detail |
|---|---|---|
| `--target` | str | `TARGET`; default `auto` |
| `--location` | str | `LOCATION` |
| `--hooks` | str | `HOOKS` |
| `--skills` | str | `SKILLS` |
| `--allow-cli` | switch | default `False` |
| `--check` | switch | default `False` |
| `--print-config` | str | `PRINT_CONFIG` |
| `--dry-run` | switch | default `False` |
| `--yes` | switch | default `False` |

## `ow open`

Fetch the exact passages behind an address you already hold: a cite, a page range, or a whole document

Action: `open`

| argument | kind | detail |
|---|---|---|
| `ref` | str | `REF`; nargs `+`; 'd7#412' \| 'handbook:d7#412' \| 'policy.pdf#p14/3' \| 'policy.pdf#p12-18' \| 'policy.pdf' |
| `--context` | int | `CONTEXT`; default `1` |
| `--layers` | csv | `LAYERS` |
| `--max-chars` | int | `MAX_CHARS` |
| `--raw` | switch | the retained bytes, without the packer's rendering |
| `--want-impact` | switch | ow:impact for a batch; a single-block ref gets it anyway |

## `ow out assets`

List a sealed artefact's frozen assets with their licences and restrictions, or every artefact and document that holds one asset's bytes

Action: `out.assets`

| argument | kind | detail |
|---|---|---|
| `--slug` | str | `SLUG` |
| `--gen` | int | `GEN` |
| `--slot` | str | `SLOT` |
| `--explain` | switch | default `False` |

## `ow out back`

Read a sealed artefact back into the corpus once, then restore its retained IL, Brief and assets into a JobDir for its next generation

Action: `out.back`

| argument | kind | detail |
|---|---|---|
| `slug` | str | `SLUG` |
| `--gen` | int | `GEN` |

## `ow out check`

Run the target's rules over a JobDir's IL at one stage, write validation/<stage>.json, and print each finding with its fix

Action: `out.check`

| argument | kind | detail |
|---|---|---|
| `--stage` | str | `STAGE` |
| `--unit` | str | `UNIT` |
| `--job` | str | `JOB` |
| `--target` | str | `TARGET` |

## `ow out compile`

Lower a JobDir whose final gate passed into its artefact in an S4 worker, seal the artifact row, and place the bytes under [roots] output

Action: `out.compile`

| argument | kind | detail |
|---|---|---|
| `--accept-manual` | switch | default `False` |
| `--job` | str | `JOB` |

## `ow out constructs`

Print a target's construct table, a line a row, one row in full, or as the agent document an IL author writes against (--format md)

Action: `out.constructs`

| argument | kind | detail |
|---|---|---|
| `target` | str | `TARGET` |
| `--format` | str | `FORMAT`; default `text` |
| `--group` | str | `GROUP` |
| `--construct` | str | `CONSTRUCT` |

## `ow out list`

List the compiled artefacts sealed in a corpus, with each generation's gate status, delivery and read_back_doc_ord

Action: `out.list`

| argument | kind | detail |
|---|---|---|
| `--slug` | str | `SLUG` |

## `ow out normalize`

Apply each normalize row's normalizer to the IL values it selects, through the transactional splice, all units or none

Action: `out.normalize`

| argument | kind | detail |
|---|---|---|
| `--stage` | str | `STAGE` |
| `--unit` | str | `UNIT` |
| `--construct` | str | `CONSTRUCT` |
| `--job` | str | `JOB` |

## `ow out scaffold`

Create the JobDir one artefact is authored in: job.json with the roster the Brief commissions, the frozen brief.md, il/il.toml and empty assets

Action: `out.scaffold`

| argument | kind | detail |
|---|---|---|
| `target` | str | `TARGET` |
| `--brief` | str | `BRIEF` |
| `--slug` | str | `SLUG` |

## `ow out stamp`

Mint a data-ow-el address on every citable, text-bearing IL element that has none, never renumbering one, all units or none

Action: `out.stamp`

| argument | kind | detail |
|---|---|---|
| `--job` | str | `JOB` |

## `ow out targets`

List the artefact kinds this deployment can compile, whether each is implemented and enabled, and the determinism class its card declares

Action: `out.targets`

Takes no argument.

## `ow out verify`

Recompile a sealed artefact from its retained IL in an S4 worker and compare it at its declared determinism classes (R1), and count its units (R7)

Action: `out.verify`

| argument | kind | detail |
|---|---|---|
| `--job` | str | `JOB` |

## `ow query`

Ask an indexed corpus a question and get cited passages, a verdict, and the gaps that could be hiding an answer

Action: `query`

| argument | kind | detail |
|---|---|---|
| `query` | str | `QUERY` |
| `--scope` | str | `SCOPE`; 'policy.pdf' \| 'policy.pdf#p12-40' \| 'd7' \| 'contracts/2025/**' |
| `--want` | str | one of `passages`, `table`, `fields`, `outline`, `related`; default `passages` |
| `--max-rung` | str | one of `gate`, `decode`, `repair`, `page`, `regen`, `degrade`, `enrich` |
| `--max-chars` | int | `MAX_CHARS` |
| `--k` | int | `N`; candidates per channel before fusion |
| `--mode` | str | one of `find`, `cite`, `explore`, `prove_absent`; the planner's mode; never set by --want |
| `--fail-on` | str | `STATE[,STATE]`; exit 3 on absent, 4 on degraded, instead of 0 |
| `--explain` | switch | print the routing decision with the answer |
| `--deny-method` | append | `M[,M]`; leave out blocks a Method made, e.g. roundtrip; repeatable |

## `ow serve`

Serve the MCP surface to an agent host over stdio, from the [serve] configuration startup step 5 resolves; runs until the host closes the stream

Action: `serve`

| argument | kind | detail |
|---|---|---|
| `--mcp` | switch | default `False` |
| `--http` | switch | default `False` |
| `--host` | str | `HOST` |
| `--port` | int | `PORT` |
| `--path` | str | `PATH` |
| `--api-key` | str | `API_KEY` |
| `--stateless` | switch | default `False` |
| `--session-timeout` | int | `SESSION_TIMEOUT` |
| `--profile` | str | `PROFILE` |

## `ow skills check`

Say whether the installed skills are this release's: a stale or missing core skill fails, an outdated or orphaned on-demand one is reported

Action: `skills.check`

| argument | kind | detail |
|---|---|---|
| `--check` | switch | default `False` |

## `ow skills hash`

Print the sha256-bundle-1 digest, file count and byte count of every skill bundle this release ships, for a release PR to pin

Action: `skills.hash`

Takes no argument.

## `ow skills install`

Copy a shipped skill bundle into every discovered agent-host skills directory, verified on its whole-bundle digest and recorded in skills-lock.json

Action: `skills.install`

| argument | kind | detail |
|---|---|---|
| `name` | str | `NAME`; nargs `+` |

## `ow skills ls`

List the skills this release ships, with tier and digest, and which agent-host skills directories hold each one and on whose record

Action: `skills.ls`

Takes no argument.

## `ow skills remove`

Take a skill out of every directory skills-lock.json says ow skills install put it in, on its digest; a modified or foreign copy is kept

Action: `skills.remove`

| argument | kind | detail |
|---|---|---|
| `name` | str | `NAME`; nargs `+` |
| `--yes` | switch | default `False` |

## `ow skills update`

Refresh every skill skills-lock.json records to this release's bundle and prune the ones this release no longer ships; a modified copy is kept

Action: `skills.update`

Takes no argument.

## `ow skills verify`

Re-hash every skill bundle skills-lock.json says was installed and name each mismatch: expected digest, observed digest, first differing path

Action: `skills.verify`

| argument | kind | detail |
|---|---|---|
| `--all` | switch | default `False` |

## `ow surface emit`

Write the artefacts generated from this registry, or with --check byte-diff them against the committed files and fail on any drift (gate G25)

Action: `surface.emit`

| argument | kind | detail |
|---|---|---|
| `--check` | switch | default `False` |
| `--bless` | switch | default `False` |
| `--docs` | switch | default `False` |

## `ow trace export`

Rebuild one run's spans from its event shards as OTLP JSON: a file, one request per line, a collector's /v1/traces, or printed with --dry-run --print-payload

Action: `trace.export`

| argument | kind | detail |
|---|---|---|
| `--run` | str | `RUN` |
| `--since` | str | `SINCE` |
| `--file` | str | `FILE` |
| `--otlp` | str | `OTLP` |
| `--dry-run` | switch | default `False` |
| `--print-payload` | switch | default `False` |
| `--max-batch` | int | `MAX_BATCH`; default `512` |

## `ow trace prune`

Remove the event shards older than [observe] retain_days, or --older-than, or with --dry-run name them; a shard the platform holds open is left

Action: `trace.prune`

| argument | kind | detail |
|---|---|---|
| `--older-than` | str | `OLDER_THAN` |
| `--dry-run` | switch | default `False` |

## `ow trace stat`

Count what one run's event shards hold, or every run's: records per kind, spans and wall per name, dropped records, and each shard's bytes and deflate ratio

Action: `trace.stat`

| argument | kind | detail |
|---|---|---|
| `--run` | str | `RUN` |

## `ow trace tree`

Print one run's spans as a tree with each duration, its point records under them, narrowed to a unit, a depth or the slow spans

Action: `trace.tree`

| argument | kind | detail |
|---|---|---|
| `run_id` | str | `RUN_ID` |
| `--unit` | str | `UNIT` |
| `--depth` | int | `DEPTH` |
| `--slow` | int | `SLOW` |

## `ow uninstall`

Take omniweave out of agent hosts exactly: every path the install receipt names, on its digest, and never the corpus index

Action: `uninstall`

| argument | kind | detail |
|---|---|---|
| `--target` | str | `TARGET`; default `all` |
| `--location` | str | `LOCATION` |
| `--keep-cli` | switch | default `False` |
| `--yes` | switch | default `False` |
