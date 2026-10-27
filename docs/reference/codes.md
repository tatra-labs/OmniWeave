# `OW-` error code reference

**GENERATED** by `ow surface emit --docs`. Do not edit: the `gates.reference_docs` job
assertion byte-diffs this directory, so a hand edit fails CI and the next emit overwrites it.

Generated from `codes.toml`, the register G13 holds append-only against the previous tag.

## Areas

| area | what it covers |
|---|---|
| `A` | {'error_class': 'SurfaceError', 'default_symbol': 'OW_SURFACE', 'covers': 'answer, serve and the agent surfaces'} |
| `C` | {'error_class': 'ConfigError', 'default_symbol': 'OW_CONFIG', 'covers': 'configuration, startup only'} |
| `D` | {'error_class': 'DriverHostError', 'default_symbol': 'OW_DRIVER_HOST', 'covers': 'driver resolution and the driver host'} |
| `G` | {'error_class': 'GraphError', 'default_symbol': 'OW_GRAPH', 'covers': 'graph'} |
| `M` | {'error_class': 'ModelError', 'default_symbol': 'OW_MODEL', 'covers': 'model and L2'} |
| `P` | {'error_class': 'PolicyRefusal', 'default_symbol': 'OW_POLICY', 'covers': 'policy and licence refusals'} |
| `Q` | {'error_class': 'QualityError', 'default_symbol': 'OW_QUALITY', 'covers': 'quality, cassette, eval'} |
| `R` | {'error_class': 'RouteError', 'default_symbol': 'OW_ROUTE', 'covers': 'runtime, budget, cache, routing'} |
| `S` | {'error_class': 'StoreError', 'default_symbol': 'OW_STORE', 'covers': 'store'} |
| `T` | {'error_class': 'TargetError', 'default_symbol': 'OW_TARGET', 'covers': 'OUT targets and constructs'} |

## Codes (193)

### `OW-A-001` -- `OW_NO_CORPUS_CONFIGURED`

no corpus configured

### `OW-A-002` -- `OW_CORPUS_NOT_FOUND`

corpus not found (lists the [corpora] names)

### `OW-A-003` -- `OW_TOOL_NOT_LISTED`

names the config key and the env var

### `OW-A-004` -- `OW_ACTION_NOT_ENABLED`

action not enabled

### `OW-A-005` -- `OW_COST_APPROVAL_REQUIRED`

action requires --allow-cost

### `OW-A-006` -- `OW_HUMAN_ONLY_ACTION`

unreachable from an agent surface [isError, no retry]

### `OW-A-007` -- `OW_PATH_OUTSIDE_ROOTS`

path outside every [roots] source [isError, no retry]

### `OW-A-008` -- `OW_QUERY_TOO_LONG`

query too long

### `OW-A-009` -- `OW_SCOPE_MATCHED_NOTHING`



### `OW-A-010` -- `OW_RESPONSE_TRUNCATED`

response truncated by budget

### `OW-A-011` -- `OW_CITATION_FORFEITED`

the driver forfeits citation (names the driver)

### `OW-A-012` -- `OW_SPANMAP_UNAVAILABLE`

block not citable (names the serializer)

### `OW-A-013` -- `OW_PARSE_GAP_IN_SCOPE`

names the pages and the fix

### `OW-A-014` -- `OW_CITE_AMBIGUOUS_CORPUS`

lists the qualified candidates. NEVER a silent resolve

### `OW-A-015` -- `OW_CROSS_CORPUS_UNSUPPORTED`

one query addresses one corpus; name it

### `OW-A-016` -- `OW_REF_UNPARSEABLE`



### `OW-A-017` -- `OW_SCHEMA_SUBSET_VIOLATION`

add(schema=…) outside the closed subset

Raised by `UsageError`.

### `OW-A-018` -- `OW_SECTION_NOT_DROPPABLE`

Answer.render(sections=…) naming a never-dropped section

Raised by `UsageError`.

### `OW-A-019` -- `OW_READONLY_HANDLE`

add on a readonly=True handle

Raised by `UsageError`.

### `OW-A-020` -- `OW_UNTRUSTED_DEFANGED`

markers defanged in a served block (count + cite)

### `OW-A-021` -- `OW_UNTRUSTED_INSTRUCTION_SHAPED`



### `OW-A-022` -- `OW_SERVE_OVERLOADED`

the server is at an admission ceiling and the call was not started: either [serve] max_concurrent_queries snapshots are held with max_queued_queries already waiting (10:958), or max_sessions stateful sessions exist and a new initialize was refused (10:2399). Carries a retry_after_ms computed from the observed p95, so it is a WAIT and never a rejection of the request itself

Clears with:

```console
$ ow config set serve.max_queued_queries <n>   # or retry after retry_after_ms
```

Raised by `ResourceLimit`.

### `OW-A-023` -- `OW_BAD_SCOPE_FORM`

scope matching none of the four shapes

Raised by `UsageError`.

### `OW-A-024` -- `OW_BAD_FILTER_VALUE`

a Filters value outside its enum

Raised by `UsageError`.

### `OW-A-025` -- `OW_UNKNOWN_RELATION`

an Expand.relations member absent from relation_vocab

Raised by `UsageError`.

### `OW-A-026` -- `OW_UNKNOWN_CODE`

explain() on an unregistered code

Raised by `NotFoundError`.

### `OW-A-027` -- `OW_EVAL_NOT_INSTALLED`



### `OW-A-028` -- `OW_SURFACE_REGISTRY_INVALID`

the Action registry failed one of its eleven import-time checks (names every failing row)

Raised by `SurfaceError`.

### `OW-A-030` -- `OW_HOOK_NOT_RESOLVABLE`

hook command not resolvable

### `OW-A-031` -- `OW_SKILL_HASH_MISMATCH`

skill bundle hash mismatch

### `OW-A-032` -- `OW_INSTALL_CONFIG_UNPARSEABLE`

backed up to <path>.backup

### `OW-A-033` -- `OW_INSTALL_RECEIPT_LOCKED`



### `OW-A-040` -- `OW_HTTP_BIND_UNAUTHENTICATED`

non-loopback bind without --api-key [A REFUSAL]. The listener does not open: a warning on a line nobody reads is how an unauthenticated corpus reaches the network (10:2340). A LOOPBACK bind with no key is the sanctioned case and is one of exactly two loopback TCP endpoints the framework allows

Clears with:

```console
$ ow serve --http --api-key <key>   # or set OMNIWEAVE_API_KEY, or bind 127.0.0.1
```

Raised by `UsageError`.

### `OW-A-041` -- `OW_HTTP_ORIGIN_REJECTED`

the DNS-rebinding guard: an Origin header present and not in [serve] allowed_origins (default EMPTY, so ANY Origin is rejected - an MCP client is not a browser and sends none), or a Host whose name is neither a literal loopback address nor a member of [serve] allowed_hosts. Answered 403 BEFORE the API-key comparison, and the body names no origin, no host and no code

Clears with:

```console
$ ow config set serve.allowed_origins <the origin>   # or serve.allowed_hosts for a Host
```

### `OW-A-042` -- `OW_LOCATOR_AMBIGUOUS`



### `OW-A-043` -- `OW_SERVE_COPYLEFT_NETWORK`

ow serve --http refusing at listener start when any driver in [drivers] enabled computes to a tier carrying copyleft_network. The shipped acknowledgement covers a LOCAL run; a listening transport engages the clause the ack disclaims. The refusal names every offending driver, its SPDX expression and the licence_sha256 the ack is bound to. stdio and ow query are unaffected

Clears with:

```console
$ ow config set drivers.enabled <the roster without it>   # or serve over stdio
```

Raised by `PolicyRefusal`.

### `OW-A-044` -- `OW_UNSUPPORTED_LOCATOR_SCHEME`



### `OW-C-042` -- `OW_GRAPH_DISABLED`

Corpus.graph() with [graph] enabled = false

Raised by `ConfigError`.

### `OW-C-043` -- `OW_SQLITE_TOO_OLD`

SQLite below MIN_SQLITE

Raised by `ConfigError`.

### `OW-D-009` -- `OW_DRIVER_FORMAT_UNSUPPORTED`



### `OW-D-010` -- `OW_CARD_INVALID`

a driver.toml the loader refuses: an unknown top-level table or key, a value outside a closed vocabulary, a section 4.5 cap breach naming the key and the cap, a [limits] value above HOST_MAX (DR20), a [config] keyword outside the closed JSON-Schema subset, an empty [deprecation] or [licence.weights], revision="main", or a benchmark row with n < 30 or an incomplete measured_on

Clears with:

```console
$ ow drivers check <path/to/driver.toml>
```

Raised by `DriverHostError`.

### `OW-D-011` -- `OW_CARD_ENTRYPOINT_MALFORMED`

[driver] entrypoint is not <dotted.module>:<Attr> - it lacks exactly one ':' or carries a '/'. The entry-point VALUE is a colon-free dotted package and is a different name with a different grammar; activate() is the only site that resolves the colon form

Clears with:

```console
$ ow drivers check <path/to/driver.toml>
```

Raised by `DriverHostError`.

### `OW-D-012` -- `OW_CARD_SCHEMA_TOO_NEW`

card_schema is above max(CARDS_SUPPORTED): the card is well-formed in a grammar this build does not implement, so the fix is an upgrade and never an edit to the card

Clears with:

```console
$ pip install --upgrade omniweave-core
```

Raised by `DriverHostError`.

### `OW-D-013` -- `OW_DRIVER_DUPLICATE_ID`

two distributions declare one driver id and no [drivers.resolve] row says which wins. Both distributions are named, because the operator cannot write the disambiguation without knowing both. A duplicate id NEVER wins silently (DR3): DataFlow's registry, keyed on a bare __name__, is first-wins and silent, so one plugin vanishes with no diagnostic

Clears with:

```console
$ ow config set drivers.resolve."<id>" <distribution>
```

Raised by `DriverHostError`.

### `OW-D-024` -- `OW_FORMAT_TOKEN_COLLISION`

a media type mapping to two format tokens across enabled cards: two [capability.parse] format_tokens pairs give one media_type two tokens, which would make routing's format_token_for(media_type) ambiguous. Refused at ACTIVATION, naming both drivers and both pairs, rather than resolved by precedence

Clears with:

```console
$ ow config set drivers.enabled <the one driver of the pair to keep>
```

Raised by `DriverHostError`.

### `OW-D-051` -- `OW_DRIVER_MESSAGE_UNCLASSIFIED`

a driver failure reached tier 3 of the classifier - neither a structured FailureClass nor a status code - so the raw message was matched against the substring table. Recorded as a warning Diag naming the raw string: fail toward retryable, and report the gap

Clears with:

```console
$ ow doctor --deep --render json   # attach the report so the message gains a tier-1 or tier-2 classification
```

Raised by `DriverHostError`.

### `OW-D-052` -- `OW_DRIVER_PORT_UNSUPPORTED`

this core does not implement that Port major at all. The first filter in resolve()'s order, and the reason both majors of a Port can coexist in a catalog while only one is resolvable

### `OW-D-053` -- `OW_DRIVER_PORT_MISMATCH`

the caller asked for derive/1 and the card is a parse/1 - a caller bug, raised as a rejection rather than an exception so a mis-wired policy rule produces a report instead of a traceback. Not redundant beside PORT_UNSUPPORTED: that one means the major is unimplemented, this one means the port is the wrong port

### `OW-D-054` -- `OW_DRIVER_ID_COLLISION_UNQUALIFIED`

two distributions declare the same driver id and no [drivers.resolve] row disambiguates, so resolve() refuses the unqualified id rather than picking one. The registration-time half of the same fact is OW-D-013 OW_DRIVER_DUPLICATE_ID: a raise at registration and a rejection at resolution are two sites, not one

### `OW-D-055` -- `OW_DRIVER_TOMBSTONED`

the id is in the shipped tombstone set, refused with the quoted reason from the tombstone card. Installation is not consent: a tombstoned driver present on disk is still not resolvable

### `OW-D-056` -- `OW_DRIVER_DEPRECATED_REMOVED`

RELEASE >= the card's [deprecation] removed_in, so the driver is past the release at which it stops resolving. Below removed_in the card still runs and records a deprecation Degradation instead

### `OW-D-057` -- `OW_DRIVER_PRODUCES_INSUFFICIENT`

the requirement's requires_produces is not a subset of the card's [capability] produces, so the driver cannot emit something the caller declared it needs

### `OW-D-058` -- `OW_DRIVER_CAPABILITY_BELOW_FLOOR`

a requested capability floor is not met by the card's [capability.*] declaration, compared per the field semantics of section 2.2 - ladders by rank, sets by superset, booleans by implication, and forfeits inverted

### `OW-D-059` -- `OW_DRIVER_GRANULARITY_MISMATCH`

the requirement named a granularity and the card does not offer it. Checked only when requested, so a requirement that names none cannot be refused on this gate

### `OW-D-060` -- `OW_DRIVER_NO_WITNESS_SET`

a billed corpus-granularity requirement reached a driver with neither a witness set nor a cohort, so the spend would be unattributable

### `OW-D-061` -- `OW_DRIVER_LICENCE_TIER_NOT_ALLOWED`

the tier compute_tier() derives from the card's licence facts is not in [licence] allow_tiers. The tier is always computed and never declared (DR15), so this cannot be cleared by editing the card. Also carries the local [licence] jurisdiction and fields_of_use exclusions, which the plan gives no code of their own

### `OW-D-062` -- `OW_DRIVER_LICENCE_ACK_MISSING`

a restricted-or-above driver has no acknowledgement row in omniweave.acks.toml. A fresh install of a restricted driver is refused twice over - once by the tier allowlist and once by the missing ack

### `OW-D-063` -- `OW_DRIVER_LICENCE_ACK_STALE`

the acknowledgement exists but its recorded licence_sha256 no longer matches the installed licence text, so the operator acknowledged different terms than the ones now on disk. The refusal prints both digests

### `OW-D-064` -- `OW_DRIVER_COST_CLASS_NOT_PERMITTED`

the card's cost class is not in [drivers.cost] allow_classes - a billed_api driver on a host that permits only free ones. 08-runtime.md:2073 prints this condition under the spelling OW_DRIVER_COST_CLASS_FORBIDDEN; the member name at 04-driver-system.md:1565 is the definition site and governs

### `OW-D-065` -- `OW_DRIVER_NOT_IN_LOCKFILE`

require_lock is set and the driver has no row in omniweave.lock, so a card appeared that the lockfile never pinned

### `OW-D-066` -- `OW_DRIVER_UNATTESTED`

the card's recomputed attestation does not match the recorded one and the requirement did not explicitly pin the driver. Attestation is tamper-evidence and not authentication, so a pin is the sanctioned override

### `OW-D-067` -- `OW_DRIVER_HARDWARE_ABSENT`

the card's [requires] hardware is not satisfiable on this host - no GPU, or too little VRAM for the declared floor

### `OW-D-068` -- `OW_DRIVER_BINARY_ABSENT`

a binary the card declares it needs is not on PATH. The other half of the hardware-satisfiable gate, split from HARDWARE_ABSENT because the fix is an install and not a machine

### `OW-D-069` -- `OW_DRIVER_ISOLATION_NOT_PERMITTED`

no isolation mode the card can run under is grantable under policy - wasm is in the vocabulary and not built at v1, so the grantable set is inproc and subproc

### `OW-D-070` -- `OW_DRIVER_TRUST_INSUFFICIENT`

an operator named this id in [drivers] inproc but its computed trust does not clear the six conjuncts inproc requires, so the config line is refused loudly rather than silently ignored. A card that merely REQUESTS inproc is degraded to subproc instead, recording Degradation(kind="isolation_shortfall")

### `OW-D-071` -- `OW_DRIVER_QUARANTINED`

the driver was quarantined earlier in this run after a crash, so it is not offered again for the remainder of the run

### `OW-D-072` -- `OW_DRIVER_PROBE_UNAVAILABLE`

the capability probe returned status unavailable. missing[] is machine-actionable and fix_hint is printed, so the refusal names the thing to install. Runs in a worker that imports the driver's own dependencies and never the framework's

### `OW-D-073` -- `OW_CARD_CODE_MISMATCH`

the loaded class or the worker's HELLO_ACK disagrees with the card on port, schema_version, driver_id or version. Checked twice on purpose - an inproc driver has no HELLO_ACK, an exec driver has no importable class, and a subproc worker may be a different build than the card the host read from disk. Refused BEFORE any work

### `OW-G-001` -- `OW_GRAPH_TOO_LARGE`

op.cluster refuses a graph above MAX_CLUSTER_EDGES = 8,000,000 node pairs: pure-Python Louvain stops at the cap, and omniweave-driver-leiden is the driver seam named above it

Clears with:

```console
$ ow config set graph.passes.enable <the roster without the Pass writing the most edges>   # or omniweave-driver-leiden, the seam above MAX_CLUSTER_EDGES
```

Raised by `GraphError`.

### `OW-M-030` -- `OW_CITE_RETIRED`



### `OW-M-031` -- `OW_BLOCK_REDACTED`



### `OW-M-032` -- `OW_ADDR_NOT_FOUND`

no block at that addr in the head generation

Raised by `NotFoundError`.

### `OW-M-033` -- `OW_FRAGMENT_DANGLING_TMP`

a fragment references a tmp id it never defined, or defines one twice; the whole document fails

Raised by `ModelError`.

### `OW-M-034` -- `OW_FRAGMENT_OUT_OF_SCOPE`

a fragment names a page outside the PartSelector it was given; nothing is committed

Raised by `ModelError`.

### `OW-M-035` -- `OW_ASSET_DIGEST_MISMATCH`

an asset whose claimed sha256 disagrees with the stream the host hashed; the asset is rejected, because a content-addressed store with an unverified writer is a substitution oracle

Clears with:

```console
$ re-export the asset and freeze it again
```

Raised by `ModelError`.

### `OW-P-001` -- `OW_POLICY_KEY_UNKNOWN`

a key in `[slice] by` or in a `when` clause that no SignalSpec registers

### `OW-P-002` -- `OW_POLICY_LITERAL_OFF_DOMAIN`

a literal compared against a str-dtype signal that is not in that signal's domain

### `OW-P-004` -- `OW_POLICY_ON_UNKNOWN_MISSING`

a rule reading a nullable key without an `on_unknown`; an exists-only `when` is exempt

### `OW-P-005` -- `OW_POLICY_RUNG_NOT_FORWARD`

an escalate_to or a skip_rungs member at or below the rule's own rung

Raised by `PolicyRefusal`.

### `OW-P-010` -- `OW_POLICY_KEY_NEEDS_LATER_RUNG`

a rule reading a key whose `requires` names a rung strictly greater than the rule's own

### `OW-P-011` -- `OW_POLICY_RULE_UNREACHABLE`

an action rule subsumed by an earlier action rule at the same (rung, lane, phase)

### `OW-P-013` -- `OW_POLICY_RULE_DOES_NOTHING`

a rule whose `then` holds neither an action key nor a modifier key

Raised by `PolicyRefusal`.

### `OW-P-014` -- `OW_POLICY_FORMAT_UNROUTED`

a format token in the computed domain that no GATE or DECODE rule names

### `OW-P-016` -- `OW_EGRESS_GRANT_MISSING`

a URL source with bytes_egress = 0

Raised by `PolicyRefusal`.

### `OW-P-020` -- `OW_POLICY_BUDGET_RAISED`

a project layer raising a budget above the site layer's

Raised by `PolicyRefusal`.

### `OW-P-022` -- `OW_SIGNAL_PROVIDER_CONFLICT`

two signal providers claim one (key, format), or disagree about a per-key column

Raised by `PolicyRefusal`.

### `OW-P-023` -- `OW_POLICY_RUNG_SPELLING`

a lower-case Rung literal in a policy file

Raised by `PolicyRefusal`.

### `OW-P-030` -- `OW_POLICY_EGRESS_DENIED`



### `OW-P-031` -- `OW_POLICY_PRIVATE_DESTINATION`



### `OW-P-032` -- `OW_POLICY_WEIGHTS_UNPINNED`



### `OW-Q-012` -- `OW_GOLDEN_CHURN_UNEXPLAINED`

unexplained golden churn: a pages or outline change with an empty shape delta, or a shape delta the page-wise sums of pages contradict; a non-deterministic reducer, an order leak or a rollup that disagrees with the counters it sums to. There is no override (D819)

Clears with:

```console
$ ow eval golden --explain <file>
```

Raised by `QualityError`.

### `OW-Q-013` -- `OW_TEST_INVENTORY_DECREASED`

the test inventory decreased in an area: fewer tests or properties were collected than eval/inventory.toml holds at the base, and the change adds no BLESS.log row for the inventory, so a skipif, a broken marker or a deleted conftest.py may have removed them silently (Q-G24)

Clears with:

```console
$ OMNIWEAVE_BLESS=1 ow eval bless --inventory --reason '<why the tests went>'
```

Raised by `QualityError`.

### `OW-Q-014` -- `OW_TEST_MISPLACED`

a test marked for a tier lives outside that tier's directory, or a test file inside a tier's directory does not carry its marker, so the tier selection runs it in the wrong job (Q-G25)

Clears with:

```console
$ move the test, do not move the marker
```

Raised by `QualityError`.

### `OW-R-030` -- `OW_ROUTE_ESCALATION_NOT_MONOTONE`

a route_decision child row at a rung at or below its parent's

### `OW-R-031` -- `OW_ROUTE_SPEND_UNRECONCILED`

a run's bill does not reconcile: route_spend disagrees with its manifest, or a finished decided work row has no spend row

### `OW-S-010` -- `OW_SNAPSHOT_EXPIRED`



### `OW-S-016` -- `OW_STORE_BUSY`

another writer holds the corpus

Raised by `StoreBusy`.

### `OW-S-030` -- `OW_SCHEMA_AHEAD`



### `OW-S-033` -- `OW_UNICODE_DRIFT`



### `OW-S-034` -- `OW_SCHEMA_SECOND_HOME`



### `OW-S-060` -- `OW_STORE_TRACKED_IN_GIT`

a .owstore file is tracked in git: a corpus committed to a repository

Clears with:

```console
$ git rm --cached -- <the tracked .owstore paths>
```

### `OW-S-070` -- `OW_ERASURE_INCOMPLETE`



### `OW-S-071` -- `OW_REKEY_INTERRUPTED`



### `OW-T-001` -- `OW_TARGET_CONSTRUCT_UNMAPPED`

a maps_to that does not resolve in lower/

### `OW-T-002` -- `OW_TARGET_CONSTRUCT_UNDECLARED`

a lowering symbol with no ConstructTable row

### `OW-T-003` -- `OW_TARGET_CHECK_SKIPPED`

a rule's needs was unmet; the gate is unverified

### `OW-T-004` -- `OW_TARGET_RULE_FORGED_PROVENANCE`

a rule emitted a non-INTRODUCED provenance (§4.1)

### `OW-T-005` -- `OW_TARGET_UNIT_UNCLASSIFIED`

a unit landed in no UnitOutcome; FATAL

### `OW-T-006` -- `OW_TARGET_FINDINGS_TRUNCATED`

a rule passed MAX_FINDINGS_PER_RULE, or the report re-folded

### `OW-T-007` -- `OW_TARGET_SELECTOR_INVALID`

a selector, a forbidden_when or a select() literal that does not parse as §3.1's carrier selector grammar; raised, never an empty match

### `OW-T-008` -- `OW_TARGET_BRIEF_INVALID`

a Brief parse_brief() refuses: line 1 is not the brief/1 comment, a line outside the two productions, a missing, unknown or repeated section, a missing required key, a closed value outside its set, a primary_language that is not canonical BCP-47 or is und or script-less Chinese, an untagged prohibition outside the ConstructTable's baseline, or a malformed ## template

Clears with:

```console
$ ow out check --target <target> --stage early   # names the Brief line; the authoring agent does not edit the Brief
```

Raised by `TargetError`.

### `OW-T-009` -- `OW_TARGET_CONSTRUCTS_INVALID`

a constructs.toml ConstructTable.load() refuses: an unknown key, a missing or forbidden key for the row's disposition, a normalize row not pointing at a native row, a normalizer the target does not ship, a duplicate id, a missing mandatory attribute, or unknown_construct other than forbidden

Clears with:

```console
$ ow out constructs <target>   # loads the table and names the row and the key
```

Raised by `TargetError`.

### `OW-T-010` -- `OW_TARGET_RULE_RAISED`

a rule raised instead of returning findings; run_pack() records one framework error naming the rule and the exception type, the run goes on, and the gate is failed

Clears with:

```console
$ ow out check --target <target> --stage final --json   # names the rule; report it to its target
```

Raised by `TargetError`.

### `OW-T-011` -- `OW_TARGET_IL_TOML_INVALID`

an il/il.toml ILBundle.load() refuses: unreadable, another schema, no il or constructs_digest, an origin other than project, an unknown key, a [[unit]] that is not an OutUnit with a basename file, ords that are not 1..n, a repeated id or file, or a template.nsig line that is not 8 hex

Clears with:

```console
$ ow out scaffold <target>   # writes il.toml; the authoring agent adds [[unit]] rows
```

Raised by `TargetError`.

### `OW-T-101` -- `OW_TARGET_CITE_UNRESOLVED`

a data-ow-cite naming no block in this corpus, at --stage final

### `OW-T-102` -- `OW_TARGET_CITE_NOT_VERBATIM`

kind="quote" over text that is not the block's span

### `OW-T-103` -- `OW_TARGET_CITE_MALFORMED`

a data-ow-cite value that is not a space-separated list of cite tokens

Clears with:

```console
$ ow out check --stage unit --unit <unit>
```

### `OW-T-112` -- `OW_TARGET_IL_ASSET_URI`

an http(s)/file:/data:/path in IL text

### `OW-T-141` -- `OW_TARGET_MARKER_UNRESOLVED`

assert_clean() found a marker at compile

### `OW-T-151` -- `OW_TARGET_MARKER_AMBIGUOUS`

multiple text candidates and no prev

### `OW-T-152` -- `OW_TARGET_MARKER_ORPHAN`

no element carries the marker's el

### `OW-T-153` -- `OW_TARGET_MARKER_STALE`

the element's nsig moved since placement

### `OW-T-154` -- `OW_TARGET_MARKER_BUDGET`

MAX_MARKERS_PER_UNIT exceeded

### `OW-T-210` -- `OW_TARGET_FILL_NOT_UPPER_HEX`

the reference normalize row

### `OW-T-211` -- `OW_TARGET_CLASS_NOT_LOWER`

owtext/1's normalize row: a class attribute that is not lower-case ASCII; a warning, folded

Clears with:

```console
$ ow out normalize <il file>
```

### `OW-T-212` -- `OW_TARGET_CITE_SPACING`

owflow/1's normalize row: a data-ow-cite list with more than one space between tokens, or any at either end; a warning, folded

Clears with:

```console
$ ow out normalize --construct ow.cite.spacing
```

### `OW-T-213` -- `OW_TARGET_SPAN_NOT_CANONICAL`

owflow/1's normalize rows: a colspan or rowspan written with a sign, a space or a leading zero; a warning, folded

Clears with:

```console
$ ow out normalize --construct table.colspan.form
```

### `OW-T-214` -- `OW_TARGET_LANG_CASE`

owflow/1's normalize row: a lang tag outside BCP-47's conventional case; a warning, folded

Clears with:

```console
$ ow out normalize --construct lang.tag.case
```

### `OW-T-215` -- `OW_TARGET_LENGTH_UNIT`

owsvg/1's normalize rows: a user-unit length or font size written with a px suffix, which an owsvg/1 user unit already is; a warning, folded

Clears with:

```console
$ ow out normalize --construct geom.x.px
```

### `OW-T-216` -- `OW_TARGET_OPACITY_PERCENT`

owsvg/1's normalize rows: an opacity written as a percentage, whose canonical form is a fraction 0-1; a warning, folded

Clears with:

```console
$ ow out normalize --construct paint.opacity.percent
```

### `OW-T-311` -- `OW_TARGET_BLEND_REQUIRES_BAKE`

the reference bake row

### `OW-T-312` -- `OW_TARGET_SHADOW_REQUIRES_BAKE`

owtext/1's bake row: text-shadow has no native mapping and needs a bake the card says is unavailable

Clears with:

```console
$ ow out normalize <il file>   # drop the shadow
```

### `OW-T-400` -- `OW_TARGET_IL_MALFORMED`

an IL file the carrier's parse refuses or had to recover: order 0, one error a problem at its position, and the unit's remaining rules are skipped

Clears with:

```console
$ ow out check --target <target> --stage unit --unit <id>   # after repairing the named line
```

Raised by `TargetError`.

### `OW-T-401` -- `OW_TARGET_SCRIPT_FORBIDDEN`

<script> or an event attribute

### `OW-T-402` -- `OW_TARGET_ID_WITH_STYLE`

the reference conditional prohibition

### `OW-T-403` -- `OW_TARGET_UNIT_MALFORMED`

a unit's root is not the one element its target's unit construct names

Clears with:

```console
$ ow out check --stage unit --unit <unit>
```

### `OW-T-404` -- `OW_TARGET_TEXT_INVALID`

block text that is not NFC, or that nests a block element

Clears with:

```console
$ ow out check --stage unit --unit <unit>
```

### `OW-T-405` -- `OW_TARGET_EL_DUPLICATE`

two elements with one data-ow-el

### `OW-T-406` -- `OW_TARGET_CLASS_INVALID`

a class attribute outside its construct's canonical form

Clears with:

```console
$ ow out check --stage unit --unit <unit>
```

### `OW-T-410` -- `OW_TARGET_FILL_INVALID`

the reference native row's grammar

### `OW-T-411` -- `OW_TARGET_PROJECT_UNAVAILABLE`

project() with project = false on the card

Raised by `TargetError`.

### `OW-T-412` -- `OW_TARGET_CONSTRUCT_NOT_IN_TABLE`

an element, attribute or style property no row of the target's ConstructTable declares: unknown_construct = "forbidden" (D781)

Clears with:

```console
$ ow out constructs <target>   # the constructs its IL has
```

### `OW-T-413` -- `OW_TARGET_HEADING_SKIP`

a heading more than one level deeper than the heading before it in its unit, an h1 followed by an h3

Clears with:

```console
$ ow out check --stage unit --unit <unit>
```

### `OW-T-414` -- `OW_TARGET_TABLE_TOPOLOGY`

a table whose cells do not cover one grid exactly: rows of different widths, overlapping cells, a rowspan past its group, a span that is not an integer from 1, or a row or cell outside its parent

Clears with:

```console
$ ow out check --stage unit --unit <unit>
```

### `OW-T-415` -- `OW_TARGET_NOTE_UNRESOLVED`

a note reference with no body in its unit, a body referenced other than once, a duplicate note id, a reference with content, or a body that is not a child of the unit's section

Clears with:

```console
$ ow out check --stage unit --unit <unit>
```

### `OW-T-416` -- `OW_TARGET_LIST_MALFORMED`

a list nested past the declared depth (nine, WordprocessingML's levels), a list item outside its container, another child inside one, or a start that is not a decimal integer on an ol

Clears with:

```console
$ ow out check --stage unit --unit <unit>
```

### `OW-T-417` -- `OW_TARGET_POSITIONING_FORBIDDEN`

a positioning or geometry construct in a flow carrier's IL: position, float, an offset, a transform, a z-index, a width or height, a page break, or align

Clears with:

```console
$ ow out constructs docx --group pos
```

### `OW-T-418` -- `OW_TARGET_CONSTRUCT_FORBIDDEN`

a construct the target's ConstructTable declares forbidden, with no more specific code; the row's msg says what to write instead

Clears with:

```console
$ ow out constructs <target> --construct <id>
```

### `OW-T-419` -- `OW_TARGET_CANVAS_MISMATCH`

an owsvg/1 slide whose root viewBox is not '0 0 W H' in positive integers, whose W or H is outside a PowerPoint slide's 96-5376 user units, whose root transform, width or height rescales it, or whose W:H is not the Brief's canvas format (D789)

Clears with:

```console
$ ow out constructs pptx --construct canvas.viewbox
```

### `OW-T-420` -- `OW_TARGET_GEOMETRY_INVALID`

an owsvg/1 length, point list or aspect value outside its row's grammar: a negative width, a polygon of two points, an unknown preserveAspectRatio

Clears with:

```console
$ ow out constructs pptx --group geom
```

### `OW-T-421` -- `OW_TARGET_PATH_INVALID`

owsvg/1 path data that is incomplete or outside SVG's command grammar: a path not starting with M, a command missing an argument

Clears with:

```console
$ ow out constructs pptx --construct geom.d
```

### `OW-T-422` -- `OW_TARGET_TRANSFORM_INVALID`

an owsvg/1 transform outside the four operations DrawingML can hold (translate, scale, rotate, matrix), a skew or shear, or a matrix on text

Clears with:

```console
$ ow out constructs pptx --construct geom.transform
```

### `OW-T-423` -- `OW_TARGET_OPACITY_INVALID`

an owsvg/1 opacity that is not a number from 0 to 1

Clears with:

```console
$ ow out constructs pptx --group paint
```

### `OW-T-424` -- `OW_TARGET_STROKE_INVALID`

an owsvg/1 stroke value outside its row's grammar: a negative width, a dash array with a zero or negative entry, an unknown cap, join or vector-effect

Clears with:

```console
$ ow out constructs pptx --group stroke
```

### `OW-T-425` -- `OW_TARGET_FONT_INVALID`

an owsvg/1 text property outside its row's grammar: a font size DrawingML cannot hold, a weight that is not 100-900, text-anchor on a tspan

Clears with:

```console
$ ow out constructs pptx --group text
```

### `OW-T-426` -- `OW_TARGET_GRADIENT_INVALID`

an owsvg/1 gradient DrawingML cannot hold: fewer than two stops, offsets that decrease, coordinates outside the bounding box, a focus outside the circle

Clears with:

```console
$ ow out constructs pptx --group def
```

### `OW-T-427` -- `OW_TARGET_REFERENCE_UNRESOLVED`

an owsvg/1 url(#id) or href="#id" naming no local definition of the kind it needs, or a link target that is neither #u<NN> nor https:

Clears with:

```console
$ ow out constructs pptx --construct geom.href
```

### `OW-T-428` -- `OW_TARGET_EFFECT_INVALID`

an owsvg/1 filter, marker or clip path DrawingML cannot hold: more than one effect primitive, a marker on a shape that is not a line or path, a clip on a shape that is not an image

Clears with:

```console
$ ow out constructs pptx --group effect
```

### `OW-T-429` -- `OW_TARGET_TEXT_OFF_CANVAS`

an owsvg/1 <text> whose measured lines run past the slide's viewBox, under measure.py's shaping: single-line width per positioned line, vertical wrapping not modeled (D793)

Clears with:

```console
$ ow out constructs pptx --construct text.text
```

### `OW-T-430` -- `OW_TARGET_TYPE_SIZE_UNDECLARED`

a type size within 2 user units of no typography anchor in the Brief, counted across the deck: the second occurrence a warning, the third an error, as RuleCtx.limits["undeclared_size_max"] = 2 sets (D794)

Clears with:

```console
$ ow out check --stage final   # after naming the size in brief.md's ## typography
```

### `OW-T-501` -- `OW_TARGET_PACKAGE_CORRUPT`

a member does not decompress; names it

### `OW-T-502` -- `OW_TARGET_UNIT_COUNT_MISMATCH`

output units ≠ plan.unit_count; prints both

### `OW-T-503` -- `OW_TARGET_DANGLING_REL`

a relationship target that is not a member

### `OW-T-504` -- `OW_TARGET_CONTENT_TYPE_GAP`

a part with no declared content type

### `OW-T-505` -- `OW_TARGET_NORMALIZE_AT_COMPILE`

a normalize construct reached lower() without --accept-normalization

### `OW-T-506` -- `OW_TARGET_ASSET_UNFROZEN`

preflight 2

### `OW-T-507` -- `OW_TARGET_ROSTER_MISMATCH`

ILBundle.load() for the bundle-versus-filesystem difference (§3.2, §3.7), preflight 3 for the Plan-versus-bundle one; names the ids in each of the three directions

### `OW-T-508` -- `OW_TARGET_TOO_MANY_UNITS`

preflight 4

### `OW-T-509` -- `OW_TARGET_BAKE_UNAVAILABLE`

preflight 5

### `OW-T-510` -- `OW_TARGET_GEN_CONTENDED`

§5.4 rule 2

### `OW-T-511` -- `OW_TARGET_ARTIFACT_SEALED`

an UPDATE or DELETE of a sealed artifact row, refused by 0005_out.sql's triggers: OUT edits always write a new artifact_gen and a sealed generation is never patched (OUT24)

Clears with:

```console
$ ow out compile --target <target>   # a new artifact_gen; the sealed row stays as it is
```

Raised by `TargetError`.

### `OW-T-512` -- `OW_TARGET_IL_MOVED`

an IL file's bytes differ from the row the gate passed when the compile freezes the bundle into CAS, or the row is past MAX_IL_FILE_BYTES: the compile never seals bytes no gate saw

Clears with:

```console
$ ow out check --stage final
```

Raised by `TargetError`.

### `OW-T-513` -- `OW_TARGET_MANUAL_REASON_UNKNOWN`

a data-ow-manual value outside ManualReason: a framework error finding, so the gate fails instead of asking a human to act on an undefined reason

Clears with:

```console
$ ow out constructs --construct ow:manual
```

### `OW-T-514` -- `OW_TARGET_NOT_IMPLEMENTED`

a call into a target whose card says [compile] implemented = false; the refusal carries the card's reason (D760, appended under 09 section 15's "+" rule)

Clears with:

```console
$ ow out targets
```

Raised by `TargetError`.

### `OW-T-515` -- `OW_TARGET_UNKNOWN`

a target no discovered compile card declares; the refusal names the kinds the cards found do declare (D762, appended under 09 section 15's "+" rule)

Clears with:

```console
$ ow out targets
```

Raised by `NotFoundError`.

### `OW-T-516` -- `OW_CONSTRUCT_UNKNOWN`

a --group or --construct no row of the target's ConstructTable carries; the refusal names the groups or the ids the table has (D762)

Clears with:

```console
$ ow out constructs <target>
```

Raised by `NotFoundError`.

### `OW-T-517` -- `OW_TARGET_AMBIGUOUS`

two or more compile cards declare one target, so which table documents it is not this verb's choice; the refusal names every driver (D762)

Clears with:

```console
$ keep one card for the target on OMNIWEAVE_DRIVER_PATH or in .omniweave/drivers/
```

Raised by `ConfigError`.

### `OW-T-518` -- `OW_TARGET_JOB_INVALID`

a job.json Job.load() refuses: unreadable, another schema, an unknown or missing key at any level (a nullable one included), a value outside its grammar, a Plan that Plan refuses, or an embedded Brief that does not digest to plan.brief_digest (D763, closing 09 Q11)

Clears with:

```console
$ ow explain OW-T-518
```

Raised by `TargetError`.

### `OW-T-519` -- `OW_TARGET_SLUG_INVALID`

an artefact slug that is not lower-case letters, digits and hyphens, 1 to 64 long: it becomes the JobDir's <slug>@<gen> segment and artifact.slug, and the plan gives it no grammar (D764)

Clears with:

```console
$ ow out scaffold <target> --slug q3-board
```

Raised by `TargetError`.

### `OW-T-520` -- `OW_TARGET_JOB_EXISTS`

a JobDir, or its staged copy, already exists where a scaffold would write one: a scaffold never writes over a JobDir (D764)

Clears with:

```console
$ ow out scaffold <target> --slug <slug>   # a fresh run id
```

Raised by `TargetError`.

### `OW-T-521` -- `OW_TARGET_STAMP_LOCKED`

il/.stamp.lock is held by a stamp younger than 300 s: two stampers would both mint max(existing ordinal) + 1 (D767)

Clears with:

```console
$ wait for the other ow out stamp, or delete il/.stamp.lock if no stamp runs
```

Raised by `TargetError`.

### `OW-T-522` -- `OW_TARGET_STAMP_REFUSED`

a unit ow out stamp cannot write: its read had to recover, its bytes do not decode, or the stamped text does not reparse; nothing was written (D767)

Clears with:

```console
$ ow out check --stage unit --unit <id>
```

Raised by `TargetError`.

### `OW-T-523` -- `OW_TARGET_NORMALIZE_STALE`

ow out normalize was given a stage whose validation/<stage>.json is absent, unreadable, or describes other bytes than the bundle's (D768)

Clears with:

```console
$ ow out check --stage <stage>
```

Raised by `TargetError`.

### `OW-T-524` -- `OW_TARGET_NORMALIZE_REFUSED`

a normalize nothing may write: a normalizer that is not idempotent on a value or is not loaded, a row selecting an element or a style sub-property, an attribute without quotes, or a unit that does not read or reparse (D768)

Clears with:

```console
$ ow out check --stage early
```

Raised by `TargetError`.

### `OW-T-525` -- `OW_TARGET_JOB_CHANGED`

a compile worker found a JobDir other than the one the host gated: its il_digest, constructs_digest or ledger_digest is not the Plan's, so nothing is lowered (D771)

Clears with:

```console
$ ow out check --stage final
```

Raised by `TargetError`.

### `OW-T-526` -- `OW_TARGET_COMPILE_FAILED`

a compile worker answered with a failure that is not a target refusal: it crashed, timed out, ran past a resource limit or raised a bug, or never answered; nothing was sealed and no artefact was placed (D772)

Clears with:

```console
$ ow explain OW-T-526
```

Raised by `TargetError`.

### `OW-T-527` -- `OW_TARGET_VERIFY_INPUTS`

ow out verify was asked to recompile an artefact over inputs other than the ones it was sealed over: the JobDir names another slug or target, its Brief or ledger digests otherwise, or the installed card or construct table is not the one that compiled it (D774)

Clears with:

```console
$ ow out verify --job <the JobDir that compiled it>
```

Raised by `TargetError`.

### `OW-T-528` -- `OW_TARGET_ASSET_FORMAT`

a frozen asset whose bytes the target cannot hold: for docx, a picture that is not PNG, JPEG, GIF, BMP or TIFF; refused by preflight before a byte is written (D782)

Clears with:

```console
$ ow out assets --slot <slot>   # then freeze the picture in a format the target holds
```

Raised by `TargetError`.

### `OW-T-529` -- `OW_TARGET_READ_BACK_FAILED`

ow out back ran the target's read_back over a sealed artefact and could not close the loop: the worker failed, its fragment was refused, an address stood on two blocks or named no sealed unit, or the store quarantined the read-back as a re-parse of a document it already held; read_back_doc_ord stays NULL and no artifact_el row is written (D788)

Clears with:

```console
$ ow explain OW-T-529
```

Raised by `TargetError`.

### `OW-T-530` -- `OW_TARGET_COPY_MOVED`

an edit's compile classified a unit passthrough or cloned_passthrough, whose part the card's unit_part names, and that part is not byte for byte the part its source_ord lowered to in the parent generation, or one of the two packages lacks it; nothing is sealed (D809)

Clears with:

```console
$ ow explain OW-T-530
```

Raised by `TargetError`.

### `OW-T-531` -- `OW_TARGET_TOOLCHAIN_MISSING`

a Toolchain target cannot run: no node satisfies its node_range on the ladder (OMNIWEAVE_NODE, an installed runtime, node on PATH), its bundle is not installed, or the child exited 64 because its own runtime is missing; the target is pruned, never an ImportError (D810)

Clears with:

```console
$ ow targets install <name>
```

Raised by `CapabilityMissing`.

### `OW-T-532` -- `OW_TARGET_TOOLCHAIN_DIGEST`

an installed Toolchain bundle does not hash to the register's full sha256, or is too large to verify; it is not run and nothing is fetched (D810)

Clears with:

```console
$ ow targets install <name>   # a fresh copy, verified against the register
```

Raised by `TargetError`.

### `OW-T-533` -- `OW_TARGET_TOOLCHAIN_FAILED`

a Toolchain child broke omniweave-target/1: it would not start, its bundle held no entry, a stdout line was not a JSON object or stdout passed 1 MiB, its first frame was not its ready, it answered with something other than progress and one result, it missed its deadline, or its exit status disagreed with its receipt; the child is reaped and nothing is sealed (D810)

Clears with:

```console
$ ow explain OW-T-533
```

Raised by `TargetError`.
