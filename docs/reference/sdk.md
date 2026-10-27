# SDK and Action reference

**GENERATED** by `ow surface emit --docs`. Do not edit: the `gates.reference_docs` job
assertion byte-diffs this directory, so a hand edit fails CI and the next emit overwrites it.

Generated from `omniweave.surface.registry.ACTIONS`, the one declaration every surface is generated from.

One section per Action. `mcp` is the tool name an MCP client sees, `--` for an Action
that is human-only; `cli` is the command words. The four booleans are the Action's own
declaration and are what the MCP annotations and the CLI's refusals are built from.

## `add`

Index files, directories or URLs into a corpus so ow_query can cite them; billable work defers with the command that approves it

| property | value |
|---|---|
| cli | `ow add` |
| mcp | `ow_add` |
| listed in | default, full |
| read_only | False |
| idempotent | True |
| open_world | True |
| destructive | False |
| cost class | `billed_api` |
| input | `AddIn` |
| output | `AddReport` |

| input field | type | default |
|---|---|---|
| `source` | `str \| tuple[str, ...]` | -- |
| `corpus` | `str \| None` | None |
| `dry_run` | `bool` | False |

When to reach for it: the answer is not indexed yet.

## `corpora`

List what this server can read and what is in each corpus: counts, formats, known gaps, freshness and the capability floor

| property | value |
|---|---|
| cli | `ow corpora` |
| mcp | `ow_corpora` |
| listed in | default, full |
| read_only | True |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `CorporaIn` |
| output | `CorporaReport` |

| input field | type | default |
|---|---|---|
| `corpus` | `str \| None` | None |
| `detail` | `str` | 'list' |

When to reach for it: you do not know what exists yet.

## `corpus.coverage`

What a scope holds and what is missing from it: discovered against indexed, the gap list behind a low or absent verdict, and the command that clears each gap

| property | value |
|---|---|
| cli | `ow corpora` |
| mcp | `ow_coverage` |
| listed in | full |
| read_only | True |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `CoverageIn` |
| output | `Coverage` |

| input field | type | default |
|---|---|---|
| `corpus` | `str \| None` | None |
| `scope` | `str \| None` | None |

When to reach for it: ow_query said absent and you need to know why.

## `cost.report`

Spend by driver over a corpus's ledger or one run, with what the cache saved, and the run's reconcile against its manifest

| property | value |
|---|---|
| cli | `ow cost` |
| mcp | `ow_cost` |
| listed in | full |
| read_only | True |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `CostIn` |
| output | `CostReport` |

| input field | type | default |
|---|---|---|
| `by` | `str` | 'driver' |
| `since` | `str \| None` | None |
| `run` | `str \| None` | None |
| `corpus` | `str \| None` | None |
| `verify` | `bool` | False |

When to reach for it: you want to know what a corpus or a run cost, and which driver spent it.

## `doc.diff`

Compare two generations of one document: what carried, what was revised, what is new, and whether the newer generation was quarantined rather than committed

| property | value |
|---|---|
| cli | `ow doc diff` |
| mcp | `ow_diff` |
| listed in | full |
| read_only | True |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `DiffIn` |
| output | `RebindReport` |

| input field | type | default |
|---|---|---|
| `ref` | `str` | -- |
| `corpus` | `str \| None` | None |
| `from_gen` | `int \| None` | None |
| `to_gen` | `int \| None` | None |

When to reach for it: the document was re-indexed and you need what moved.

## `doc.grid`

Read one table as an exactly-once grid: every cell at its slot, the header row and column, and the merges that would otherwise be counted twice

| property | value |
|---|---|
| cli | `ow doc grid` |
| mcp | `ow_grid` |
| listed in | full |
| read_only | True |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `GridIn` |
| output | `Grid` |

| input field | type | default |
|---|---|---|
| `ref` | `str` | -- |
| `corpus` | `str \| None` | None |

When to reach for it: you hold a table cite and need cells, not prose.

## `doctor`

Check this deployment: every resolved configuration value with its source, the driver and toolchain probes, and a fix command for every warning

| property | value |
|---|---|
| cli | `ow doctor` |
| mcp | `ow_doctor` |
| listed in | full |
| read_only | True |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `DoctorIn` |
| output | `DoctorReport` |

| input field | type | default |
|---|---|---|
| `runtime` | `bool` | False |

When to reach for it: something is misconfigured and you need the command.

## `eval.bless`

Rewrite eval/inventory.toml from the test collection and append the BLESS.log row a fall in its counts needs; OMNIWEAVE_BLESS=1 and a reason are required

| property | value |
|---|---|
| cli | `ow eval bless` |
| mcp | -- |
| listed in | -- |
| read_only | False |
| idempotent | False |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `EvalBlessIn` |
| output | `EvalBlessReport` |

| input field | type | default |
|---|---|---|
| `counters` | `bool` | False |
| `inventory` | `bool` | False |
| `reason` | `str \| None` | None |

When to reach for it: tests were removed on purpose and Q-G24 refuses the decrease.

## `eval.publish`

Export the .oweval scoreboard into the committed eval/results tree, every row whatever its direction, or with --check report which files differ

| property | value |
|---|---|
| cli | `ow eval publish` |
| mcp | -- |
| listed in | -- |
| read_only | False |
| idempotent | True |
| open_world | False |
| destructive | True |
| cost class | `free` |
| input | `EvalPublishIn` |
| output | `EvalPublishReport` |

| input field | type | default |
|---|---|---|
| `oweval` | `str` | 'eval/omniweave.oweval' |
| `results` | `str` | 'eval/results' |
| `check` | `bool` | False |

When to reach for it: a nightly or release eval run finished and the scoreboard must move.

## `eval.release_check`

Refuse a release on any unknown run, metric or perf row, and on any hard eval/gates.toml gate off its budget or unmeasured; --strict also on a suite never run

| property | value |
|---|---|
| cli | `ow eval release-check` |
| mcp | -- |
| listed in | -- |
| read_only | True |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `EvalReleaseCheckIn` |
| output | `EvalReleaseCheckReport` |

| input field | type | default |
|---|---|---|
| `oweval` | `str` | 'eval/omniweave.oweval' |
| `gates` | `str` | 'eval/gates.toml' |
| `strict` | `bool` | False |

When to reach for it: a release is about to be tagged and every eval result must be known.

## `eval.run`

Run eval suites over the metric register's subjects and write their runs and metrics to the .oweval in one transaction; this build measures four of seven

| property | value |
|---|---|
| cli | `ow eval run` |
| mcp | -- |
| listed in | -- |
| read_only | False |
| idempotent | False |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `EvalRunIn` |
| output | `EvalRunReport` |

| input field | type | default |
|---|---|---|
| `suite` | `str \| None` | None |
| `deterministic_half` | `bool` | False |
| `subject` | `str \| None` | None |
| `witness` | `str` | 'self' |
| `cassette` | `str` | 'off' |
| `validate_judge` | `bool` | False |
| `emit` | `str \| None` | None |
| `oweval` | `str` | 'eval/omniweave.oweval' |
| `gates` | `str` | 'eval/gates.toml' |

When to reach for it: the eval store needs the measurements a release check will judge.

## `explain`

Resolve an OW-* code or symbol to what it means and the exact command that clears it; reads no corpus, so it answers on a machine with no store at all

| property | value |
|---|---|
| cli | `ow explain` |
| mcp | `ow_explain` |
| listed in | full |
| read_only | True |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `ExplainIn` |
| output | `CodeRow` |

| input field | type | default |
|---|---|---|
| `code` | `str` | -- |

When to reach for it: you have a code from an error and need what clears it.

## `graph.doctor`

Check the graph's operability: the residue signals against their thresholds, the trust clamp, the entropy gate, anchor counts, candidate pairs and report states

| property | value |
|---|---|
| cli | `ow graph doctor` |
| mcp | -- |
| listed in | -- |
| read_only | True |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `GraphDoctorIn` |
| output | `GraphDoctorReport` |

| input field | type | default |
|---|---|---|
| `check` | `str \| None` | None |
| `corpus` | `str \| None` | None |

When to reach for it: an ingest finished and you need to know whether the graph is healthy.

## `graph.locate`

Find where on the page an entity, claim, edge or mention was witnessed: one location per witness, with its page, its span and its polygon or the reason none

| property | value |
|---|---|
| cli | `ow graph locate` |
| mcp | `ow_locate` |
| listed in | full |
| read_only | True |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `LocateIn` |
| output | `Located` |

| input field | type | default |
|---|---|---|
| `entity` | `str \| None` | None |
| `claim` | `str \| None` | None |
| `edge` | `int \| None` | None |
| `mention` | `int \| None` | None |
| `corpus` | `str \| None` | None |

When to reach for it: an answer cited an entity or a claim and you need the page.

## `graph.merge`

Record that two entities are one, with a reason, and settle the graph again: the closure, the communities and the salience, as an ingest would

| property | value |
|---|---|
| cli | `ow graph merge` |
| mcp | -- |
| listed in | -- |
| read_only | False |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `MergeIn` |
| output | `Decided` |

| input field | type | default |
|---|---|---|
| `first` | `str` | -- |
| `second` | `str` | -- |
| `reason` | `str \| None` | None |
| `corpus` | `str \| None` | None |

When to reach for it: resolution left one party as two, and you know they are one.

## `graph.merges`

Show the resolution decision log: each closure's members, and every merge or split decision with its stage, score, guards and the generation it was decided in

| property | value |
|---|---|
| cli | `ow graph merges` |
| mcp | -- |
| listed in | -- |
| read_only | True |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `MergesIn` |
| output | `MergeLog` |

| input field | type | default |
|---|---|---|
| `entity` | `str \| None` | None |
| `corpus` | `str \| None` | None |

When to reach for it: two entities are one, or are not, and you need why.

## `graph.plan`

Show, per billed lane, how much the free passes covered, the share a billed pass would be handed, and the calls and tokens that projects, before anything runs

| property | value |
|---|---|
| cli | `ow graph plan` |
| mcp | -- |
| listed in | -- |
| read_only | True |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `GraphPlanIn` |
| output | `GraphPlan` |

| input field | type | default |
|---|---|---|
| `corpus` | `str \| None` | None |

When to reach for it: you are about to enable a billed pass and need to know what it would cost.

## `graph.residue`

Show what the graph could not place: unresolved references grouped by kind and name, and quarantined rows grouped by code and kind

| property | value |
|---|---|
| cli | `ow graph residue` |
| mcp | -- |
| listed in | -- |
| read_only | True |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `ResidueIn` |
| output | `GraphResidue` |

| input field | type | default |
|---|---|---|
| `akind` | `str \| None` | None |
| `corpus` | `str \| None` | None |

When to reach for it: a reference never links, or extracted rows went missing, and you need which.

## `graph.review`

Show what the graph holds below extracted, weakest first: fuzzy-merged closures, tainted and overloaded entities, and the mentions and edges to check

| property | value |
|---|---|
| cli | `ow graph review` |
| mcp | -- |
| listed in | -- |
| read_only | True |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `ReviewIn` |
| output | `Review` |

| input field | type | default |
|---|---|---|
| `over_merge` | `bool` | False |
| `corpus` | `str \| None` | None |

When to reach for it: you are about to trust the graph and want to see its weakest rows first.

## `graph.split`

Record that one entity is two or more, named by the blocks each is witnessed in, with a reason, and settle the graph again as an ingest would

| property | value |
|---|---|
| cli | `ow graph split` |
| mcp | -- |
| listed in | -- |
| read_only | False |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `SplitIn` |
| output | `Decided` |

| input field | type | default |
|---|---|---|
| `entity` | `str` | -- |
| `into` | `str \| None` | None |
| `reason` | `str \| None` | None |
| `corpus` | `str \| None` | None |

When to reach for it: resolution made one party of two, and you can show where each is witnessed.

## `graph.types`

List the entity-type vocabulary with each type's live entities, or promote proposed types into it, with a reason

| property | value |
|---|---|
| cli | `ow graph types` |
| mcp | -- |
| listed in | -- |
| read_only | False |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `TypesIn` |
| output | `TypeVocab` |

| input field | type | default |
|---|---|---|
| `promote` | `str \| None` | None |
| `reason` | `str \| None` | None |
| `propose` | `bool` | False |
| `corpus` | `str \| None` | None |

When to reach for it: a tuning run proposed entity types and you have decided which to keep.

## `graph.why`

List every entity, edge and claim the graph says one block asserts, each with its span in the block's text

| property | value |
|---|---|
| cli | `ow graph why` |
| mcp | -- |
| listed in | -- |
| read_only | True |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `WhyIn` |
| output | `Observed` |

| input field | type | default |
|---|---|---|
| `cite` | `str \| None` | None |
| `corpus` | `str \| None` | None |

When to reach for it: you hold a block cite and need what it asserts.

## `hooks.check`

Run each installed hook command as its host would, with a probe payload in a scratch project, and say which failed and why

| property | value |
|---|---|
| cli | `ow hooks check` |
| mcp | `ow_hooks_check` |
| listed in | -- |
| read_only | True |
| idempotent | True |
| open_world | True |
| destructive | False |
| cost class | `free` |
| input | `HooksCheckIn` |
| output | `HooksCheckReport` |

When to reach for it: a hook seems silent and you need to know whether it runs.

## `install`

Wire agent hosts to omniweave: the MCP entry, one permission wildcard, the instruction block, hooks and the core skill, each recorded in a receipt

| property | value |
|---|---|
| cli | `ow install` |
| mcp | -- |
| listed in | -- |
| read_only | False |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `InstallIn` |
| output | `InstallReport` |

| input field | type | default |
|---|---|---|
| `target` | `str` | 'auto' |
| `location` | `str \| None` | None |
| `hooks` | `str \| None` | None |
| `skills` | `str \| None` | None |
| `allow_cli` | `bool` | False |
| `check` | `bool` | False |
| `print_config` | `str \| None` | None |
| `dry_run` | `bool` | False |
| `yes` | `bool` | False |

When to reach for it: an agent host should reach omniweave and does not yet.

## `open`

Fetch the exact passages behind an address you already hold: a cite, a page range, or a whole document

| property | value |
|---|---|
| cli | `ow open` |
| mcp | `ow_open` |
| listed in | default, full |
| read_only | True |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `OpenIn` |
| output | `Answer` |

| input field | type | default |
|---|---|---|
| `ref` | `str \| tuple[str, ...]` | -- |
| `corpus` | `str \| None` | None |
| `context` | `int` | 1 |
| `layers` | `tuple[str, ...] \| None` | None |
| `max_chars` | `int \| None` | None |

When to reach for it: you have an id, not a question.

## `out.assets`

List a sealed artefact's frozen assets with their licences and restrictions, or every artefact and document that holds one asset's bytes

| property | value |
|---|---|
| cli | `ow out assets` |
| mcp | -- |
| listed in | -- |
| read_only | True |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `AssetsIn` |
| output | `AssetsReport` |

| input field | type | default |
|---|---|---|
| `slug` | `str \| None` | None |
| `gen` | `int \| None` | None |
| `slot` | `str \| None` | None |
| `explain` | `bool` | False |
| `corpus` | `str \| None` | None |

When to reach for it: a compile was restricted, or you need to know where an asset is reused.

## `out.back`

Read a sealed artefact back into the corpus once, then restore its retained IL, Brief and assets into a JobDir for its next generation

| property | value |
|---|---|
| cli | `ow out back` |
| mcp | -- |
| listed in | -- |
| read_only | False |
| idempotent | False |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `BackIn` |
| output | `BackReport` |

| input field | type | default |
|---|---|---|
| `slug` | `str` | -- |
| `gen` | `int \| None` | None |
| `corpus` | `str \| None` | None |

When to reach for it: you need to edit an artefact omniweave already sealed.

## `out.check`

Run the target's rules over a JobDir's IL at one stage, write validation/<stage>.json, and print each finding with its fix

| property | value |
|---|---|
| cli | `ow out check` |
| mcp | -- |
| listed in | -- |
| read_only | False |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `CheckIn` |
| output | `OutCheckReport` |

| input field | type | default |
|---|---|---|
| `stage` | `str \| None` | None |
| `unit` | `str \| None` | None |
| `job` | `str \| None` | None |
| `target` | `str \| None` | None |

When to reach for it: you authored IL and need the gate's verdict before going on.

## `out.compile`

Lower a JobDir whose final gate passed into its artefact in an S4 worker, seal the artifact row, and place the bytes under [roots] output

| property | value |
|---|---|
| cli | `ow out compile` |
| mcp | -- |
| listed in | -- |
| read_only | False |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `CompileIn` |
| output | `CompileReport` |

| input field | type | default |
|---|---|---|
| `accept_manual` | `bool` | False |
| `job` | `str \| None` | None |

When to reach for it: ow out check --stage final passed and you want the artefact.

## `out.constructs`

Print a target's construct table, a line a row, one row in full, or as the agent document an IL author writes against (--format md)

| property | value |
|---|---|
| cli | `ow out constructs` |
| mcp | -- |
| listed in | -- |
| read_only | True |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `ConstructsIn` |
| output | `ConstructsReport` |

| input field | type | default |
|---|---|---|
| `target` | `str` | -- |
| `format` | `str` | 'text' |
| `group` | `str \| None` | None |
| `construct` | `str \| None` | None |

When to reach for it: you are about to author IL for a target and need what it accepts.

## `out.list`

List the compiled artefacts sealed in a corpus, with each generation's gate status, delivery and read_back_doc_ord

| property | value |
|---|---|
| cli | `ow out list` |
| mcp | `ow_artifacts` |
| listed in | full |
| read_only | True |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `ArtifactsIn` |
| output | `ArtifactsReport` |

| input field | type | default |
|---|---|---|
| `slug` | `str \| None` | None |
| `corpus` | `str \| None` | None |

When to reach for it: you want to know which artefacts were compiled and how they stand.

## `out.normalize`

Apply each normalize row's normalizer to the IL values it selects, through the transactional splice, all units or none

| property | value |
|---|---|
| cli | `ow out normalize` |
| mcp | -- |
| listed in | -- |
| read_only | False |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `NormalizeIn` |
| output | `NormalizeReport` |

| input field | type | default |
|---|---|---|
| `stage` | `str \| None` | None |
| `unit` | `str \| None` | None |
| `construct` | `str \| None` | None |
| `job` | `str \| None` | None |

When to reach for it: a check warned of a normalize row and you want its fix applied.

## `out.scaffold`

Create the JobDir one artefact is authored in: job.json with the roster the Brief commissions, the frozen brief.md, il/il.toml and empty assets

| property | value |
|---|---|
| cli | `ow out scaffold` |
| mcp | -- |
| listed in | -- |
| read_only | False |
| idempotent | False |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `ScaffoldIn` |
| output | `ScaffoldReport` |

| input field | type | default |
|---|---|---|
| `target` | `str` | -- |
| `brief` | `str \| None` | None |
| `slug` | `str \| None` | None |
| `corpus` | `str \| None` | None |

When to reach for it: you have a confirmed Brief and are about to author IL for a target.

## `out.stamp`

Mint a data-ow-el address on every citable, text-bearing IL element that has none, never renumbering one, all units or none

| property | value |
|---|---|
| cli | `ow out stamp` |
| mcp | -- |
| listed in | -- |
| read_only | False |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `StampIn` |
| output | `StampReport` |

| input field | type | default |
|---|---|---|
| `job` | `str \| None` | None |

When to reach for it: you authored units and need element addresses before checking.

## `out.targets`

List the artefact kinds this deployment can compile, whether each is implemented and enabled, and the determinism class its card declares

| property | value |
|---|---|
| cli | `ow out targets` |
| mcp | `ow_targets` |
| listed in | full |
| read_only | True |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `TargetsIn` |
| output | `TargetsReport` |

When to reach for it: you want to know which artefacts `ow out compile` can make here.

## `out.verify`

Recompile a sealed artefact from its retained IL in an S4 worker and compare it at its declared determinism classes (R1), and count its units (R7)

| property | value |
|---|---|
| cli | `ow out verify` |
| mcp | -- |
| listed in | -- |
| read_only | True |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `VerifyIn` |
| output | `VerifyReport` |

| input field | type | default |
|---|---|---|
| `job` | `str \| None` | None |

When to reach for it: you need proof a sealed artefact is what its retained IL compiles to.

## `query`

Ask an indexed corpus a question and get cited passages, a verdict, and the gaps that could be hiding an answer

| property | value |
|---|---|
| cli | `ow query` |
| mcp | `ow_query` |
| listed in | default, full |
| read_only | True |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `local_compute` |
| input | `QueryIn` |
| output | `Answer` |

| input field | type | default |
|---|---|---|
| `query` | `str` | -- |
| `corpus` | `str \| None` | None |
| `scope` | `str \| None` | None |
| `want` | `str` | 'passages' |
| `route_hints` | `RouteHints \| None` | None |
| `max_chars` | `int \| None` | None |

When to reach for it: you have a question, not an id.

## `serve`

Serve the MCP surface to an agent host over stdio, from the [serve] configuration startup step 5 resolves; runs until the host closes the stream

| property | value |
|---|---|
| cli | `ow serve` |
| mcp | -- |
| listed in | -- |
| read_only | False |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `ServeIn` |
| output | `ServeReport` |

| input field | type | default |
|---|---|---|
| `mcp` | `bool` | False |
| `http` | `bool` | False |
| `host` | `str \| None` | None |
| `port` | `int \| None` | None |
| `path` | `str \| None` | None |
| `api_key` | `str \| None` | None |
| `stateless` | `bool` | False |
| `session_timeout` | `int \| None` | None |
| `profile` | `str \| None` | None |

When to reach for it: an agent host's MCP entry starts omniweave.

## `skills.check`

Say whether the installed skills are this release's: a stale or missing core skill fails, an outdated or orphaned on-demand one is reported

| property | value |
|---|---|
| cli | `ow skills check` |
| mcp | `ow_skills_check` |
| listed in | -- |
| read_only | True |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `SkillsCheckIn` |
| output | `SkillsReport` |

| input field | type | default |
|---|---|---|
| `check` | `bool` | False |

When to reach for it: the router skill may be older than this release.

## `skills.hash`

Print the sha256-bundle-1 digest, file count and byte count of every skill bundle this release ships, for a release PR to pin

| property | value |
|---|---|
| cli | `ow skills hash` |
| mcp | `ow_skills_hash` |
| listed in | -- |
| read_only | True |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `SkillsHashIn` |
| output | `SkillsReport` |

When to reach for it: a release needs the skill digests it ships.

## `skills.install`

Copy a shipped skill bundle into every discovered agent-host skills directory, verified on its whole-bundle digest and recorded in skills-lock.json

| property | value |
|---|---|
| cli | `ow skills install` |
| mcp | -- |
| listed in | -- |
| read_only | False |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `SkillsInstallIn` |
| output | `SkillsReport` |

| input field | type | default |
|---|---|---|
| `name` | `str \| tuple[str, ...]` | -- |

When to reach for it: a route needs a skill body that is not installed yet.

## `skills.ls`

List the skills this release ships, with tier and digest, and which agent-host skills directories hold each one and on whose record

| property | value |
|---|---|
| cli | `ow skills ls` |
| mcp | `ow_skills_ls` |
| listed in | -- |
| read_only | True |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `SkillsLsIn` |
| output | `SkillsReport` |

When to reach for it: you need to know which skills are installed and where.

## `skills.remove`

Take a skill out of every directory skills-lock.json says ow skills install put it in, on its digest; a modified or foreign copy is kept

| property | value |
|---|---|
| cli | `ow skills remove` |
| mcp | -- |
| listed in | -- |
| read_only | False |
| idempotent | True |
| open_world | False |
| destructive | True |
| cost class | `free` |
| input | `SkillsRemoveIn` |
| output | `SkillsReport` |

| input field | type | default |
|---|---|---|
| `name` | `str \| tuple[str, ...]` | -- |
| `yes` | `bool` | False |

When to reach for it: a skill ow skills install placed should go.

## `skills.update`

Refresh every skill skills-lock.json records to this release's bundle and prune the ones this release no longer ships; a modified copy is kept

| property | value |
|---|---|
| cli | `ow skills update` |
| mcp | -- |
| listed in | -- |
| read_only | False |
| idempotent | True |
| open_world | False |
| destructive | True |
| cost class | `free` |
| input | `SkillsUpdateIn` |
| output | `SkillsReport` |

When to reach for it: ow skills check said update available or removed.

## `skills.verify`

Re-hash every skill bundle skills-lock.json says was installed and name each mismatch: expected digest, observed digest, first differing path

| property | value |
|---|---|
| cli | `ow skills verify` |
| mcp | `ow_skills_verify` |
| listed in | -- |
| read_only | True |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `SkillsVerifyIn` |
| output | `SkillsReport` |

| input field | type | default |
|---|---|---|
| `all` | `bool` | False |

When to reach for it: an installed skill may have been edited or damaged.

## `surface.emit`

Write the artefacts generated from this registry, or with --check byte-diff them against the committed files and fail on any drift (gate G25)

| property | value |
|---|---|
| cli | `ow surface emit` |
| mcp | -- |
| listed in | -- |
| read_only | False |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `SurfaceEmitIn` |
| output | `SurfaceReport` |

| input field | type | default |
|---|---|---|
| `check` | `bool` | False |
| `bless` | `bool` | False |
| `docs` | `bool` | False |

When to reach for it: the Action registry changed and its generated surfaces must follow.

## `trace.export`

Rebuild one run's spans from its event shards as OTLP JSON: a file, one request per line, a collector's /v1/traces, or printed with --dry-run --print-payload

| property | value |
|---|---|
| cli | `ow trace export` |
| mcp | -- |
| listed in | -- |
| read_only | False |
| idempotent | True |
| open_world | True |
| destructive | True |
| cost class | `free` |
| input | `TraceExportIn` |
| output | `TraceExportReport` |

| input field | type | default |
|---|---|---|
| `run` | `str \| None` | None |
| `since` | `str \| None` | None |
| `file` | `str \| None` | None |
| `otlp` | `str \| None` | None |
| `dry_run` | `bool` | False |
| `print_payload` | `bool` | False |
| `max_batch` | `int` | 512 |

When to reach for it: a run must be read in a tracing tool, or its spans checked offline.

## `trace.prune`

Remove the event shards older than [observe] retain_days, or --older-than, or with --dry-run name them; a shard the platform holds open is left

| property | value |
|---|---|
| cli | `ow trace prune` |
| mcp | -- |
| listed in | -- |
| read_only | False |
| idempotent | True |
| open_world | False |
| destructive | True |
| cost class | `free` |
| input | `TracePruneIn` |
| output | `TracePruneReport` |

| input field | type | default |
|---|---|---|
| `older_than` | `str \| None` | None |
| `dry_run` | `bool` | False |

When to reach for it: the events directory has grown and retention is owed, by hand or by cron.

## `trace.stat`

Count what one run's event shards hold, or every run's: records per kind, spans and wall per name, dropped records, and each shard's bytes and deflate ratio

| property | value |
|---|---|
| cli | `ow trace stat` |
| mcp | -- |
| listed in | -- |
| read_only | True |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `TraceStatIn` |
| output | `TraceStatReport` |

| input field | type | default |
|---|---|---|
| `run` | `str \| None` | None |

When to reach for it: a trace is bigger or slower than expected, or the sample rate is in question.

## `trace.tree`

Print one run's spans as a tree with each duration, its point records under them, narrowed to a unit, a depth or the slow spans

| property | value |
|---|---|
| cli | `ow trace tree` |
| mcp | -- |
| listed in | -- |
| read_only | True |
| idempotent | True |
| open_world | False |
| destructive | False |
| cost class | `free` |
| input | `TraceTreeIn` |
| output | `TraceTreeReport` |

| input field | type | default |
|---|---|---|
| `run_id` | `str` | -- |
| `unit` | `str \| None` | None |
| `depth` | `int \| None` | None |
| `slow` | `int \| None` | None |

When to reach for it: a run was slow or failed and where it went wrong is the question.

## `uninstall`

Take omniweave out of agent hosts exactly: every path the install receipt names, on its digest, and never the corpus index

| property | value |
|---|---|
| cli | `ow uninstall` |
| mcp | -- |
| listed in | -- |
| read_only | False |
| idempotent | True |
| open_world | False |
| destructive | True |
| cost class | `free` |
| input | `UninstallIn` |
| output | `InstallReport` |

| input field | type | default |
|---|---|---|
| `target` | `str` | 'all' |
| `location` | `str \| None` | None |
| `keep_cli` | `bool` | False |
| `yes` | `bool` | False |

When to reach for it: an agent host should stop reaching omniweave.
