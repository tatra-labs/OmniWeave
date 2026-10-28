"""G27 clauses (a), (a2) and (a3) - the fenced blocks of the design record, machine-checked.

`tools/gates.toml` states G27 as *"documents machine-checked: fences parse (a), one key per
physical line (a2), `[[rule]]` fences linted (a3), migrations dense-unique-ordered (b), terminology
(c), symbols and registers (d)"*. Clause (b) is `tools/gate_migrations.py` and has been for some
time. This script is clauses (a), (a2) and (a3), plus clause (c)'s registered-off line. **Clause
(d) is not in this script yet**: 11-repo-layout.md section 8.6 gives it five checks d0-d4 over a
walk of `docs/ARCHITECTURE.md` and `docs/plan/*.md`, its ARCHITECTURE.md half already runs at the
test tier (`packages/omniweave-core/tests/unit/test_architecture_doc.py`, D986), and the walk is
the next cell. The gate prints that on its own line rather than leaving a reader to infer it: a
check that bounds its own coverage says what it dropped.

## Clause (a) - every fenced block parses under the parser its fence names

Three parsers, all stdlib: `tomllib` for ` ```toml `, `json` for ` ```json `, `ast` for
` ```python `. A fence naming anything else is COUNTED AND NOT CHECKED, and the count is printed
per language, because the honest statement of this clause's coverage is a number a reader can
compare against the corpus. ` ```jsonc ` is the one that looks checkable and is not: JSONC has no
stdlib parser, the fences carry `...` elisions, and a hand-rolled comment stripper would be a
second implementation of a parser the repository does not own -- INV-23's rejection criterion, the
same argument ADR-4 makes for deleting the standalone check 4 at the P5 exit.

`FENCE_FLOOR` is clause d0's lesson applied here. A fence scanner whose regex stopped matching
would report zero findings over zero fences and exit 0, which is exactly the C55 shape this
repository has paid for three times. The floor is asserted before any finding is reported.

## Clause (a2) - lexical, and that is the whole point

11-repo-layout.md:1576: *"After `tomllib.loads` succeeds on a ` ```toml ` fence in `charter.md` or
a plan document, `tools/gate_docs.py` walks the source text and requires the running count of `{`
minus `}`, outside comments and strings, to be zero at the end of every physical line."* A semantic
checker cannot see this: it reads a loaded `dict`, and TOML 1.0.0 permits a newline inside braces
where it falls inside a value. The charter's own D4 block is exactly that shape -- legal TOML, so
`tomllib` accepts it and always would have.

**The one expected finding is declared, not tolerated.** ADR-4 decision 1 measured this corpus:
*"One inline table spans a newline, not two, and it is a `when` rather than a `then`"*, in the
charter's section D4 fence, which the same decision **retires in whole** in favour of
05-ingest-and-routing.md section 4.4 under charter section 9 erratum `E42`. The charter's sections
1-8 are frozen -- *"No line of 1-8 was edited ... and none will be"* -- so the finding cannot be
fixed and is not a defect to fix: it is retired law, and `A2_EXPECTED` is the register of that.
The check runs both ways. A finding anywhere else fails, and an `A2_EXPECTED` row that stops being
a finding fails too, so the list can only shrink.

## Clause (a3) - the P1 interim standalone check 4

ADR-4 decision 2 and 05-ingest-and-routing.md:1797: `a3` runs `ow route lint` checks 1, 2, 4, 5, 7,
9, 10 and 12 over every ` ```toml ` fence that parses to a table containing a `[[rule]]` array, and
`ow route lint` ships at P5. *"From P1 the gate harness carries a standalone check 4 instead,
reading nullability from section 5.1's `null` column parsed out of the markdown table rather than
by importing `omniweave.route`; that column is therefore load-bearing for a gate as well as for the
linter."* At the P5 exit this standalone check is **deleted** in the same commit that lands `a3` --
pre-committed, because two implementations of one check is charter section 8 rejection criterion 19.

Check 4 is `OW-P-004`: *"every rule reading a nullable key declares `on_unknown`; a rule whose
`when` is `exists`-only does not need one"*. The seven expected findings are ADR-4 decision 1's own
measurement -- *"(a) seven rules there fail lint check 4 (`OW-P-004`), not nine, against zero in
section 4.4 -- and one of the seven is dangerous rather than merely non-compliant,
`repair.never-escalate-furniture` reading `block.type`"* -- so this clause does not merely check the
corpus, it reproduces the number the ADR was decided on. Both directions again: a rule that starts
failing fails the gate, and a declared row that stops failing fails it too.

## Clause (c) - registered and off

ADR-1 decision 6 requires the terminology lock's clause to sit in `tools/gates.toml` with
`enabled = false` and a `blocked_by` note *"so its absence is visible rather than assumed"*, until
four conditions hold. This script reads that row rather than restating it, and prints the state it
finds. It never runs the clause, because a `--warn-only` is what section 6.8 says there is none of.

Exit 0 clean, 1 with one `G27 FAIL` block per finding, 2 on a usage error.
Specified in 11-repo-layout.md section 6.4 and :1575-1600, ADR-4 decisions 1 and 2,
05-ingest-and-routing.md sections 4.5 and 5.1, and 16-roadmap.md:159 (P1 W1.12).
"""

from __future__ import annotations

import ast
import collections
import importlib
import json
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Final

REPO: Final[Path] = Path(__file__).resolve().parents[1]
PLAN: Final[Path] = REPO / "docs" / "plan"
CHARTER: Final[Path] = PLAN / "_notes" / "charter.md"
ROUTING: Final[Path] = PLAN / "05-ingest-and-routing.md"
GATES: Final[Path] = REPO / "tools" / "gates.toml"

PREFIX: Final = "G27"
FAIL_INDENT: Final = "    "

FENCE_FLOOR: Final = 450
"""Clause d0's lesson: a scanner that matched nothing would report no finding and exit 0.

Measured at 637 fences over the scope below, of which 264 name one of the three parsers. Set well
under the total so an ordinary edit does not fail the gate, and far enough above zero that a broken
fence regex cannot satisfy it."""

TOML_FENCE_FLOOR: Final = 60
"""The same guard for clause a2 and a3's narrower scope, measured at 74.

ADR-4 decision 1 counted **73** *"` ```toml ` fences in the charter and in `00`-`18`"*. The extra
one is 01-principles.md section 1e's `tools/invariants.toml` example, which ADR-2 wrote after ADR-4
took its count. Recorded rather than corrected: the ADR's number was true when it was measured, and
the gate reports what it finds."""

_FENCE_OPEN: Final = re.compile(r"^(`{3,})([A-Za-z0-9_+-]*)\s*$")
_FENCE_CLOSE: Final = re.compile(r"^`{3,}\s*$")
_SIGNAL_ROW: Final = re.compile(r"^\|\s*`([a-z][a-z0-9_]*\.[a-z][a-z0-9_]*)`\s*\|")
_CELL: Final = re.compile(r"(?<!\\)\|")
_NUMBERED: Final = re.compile(r"^\d\d-")

SIGNAL_COLUMNS: Final = 10
"""05-ingest-and-routing.md section 5.1's header: key, scope, kind, dtype, domain, cost, est, null,
req, provider(s). `null` is index 7 and is the column check 4 reads."""
NULL_COLUMN: Final = 7

COMBINATORS: Final = frozenset({"all", "any", "not", "all_of", "any_of", "none_of"})
"""A `when` key that holds other clauses rather than naming a signal. The charter's section D4
fence spells them `all_of` / `any_of`; section 4.4's spells them the same way. A walk that missed
them would find six check-4 failures where ADR-4 measured seven -- which is how this set was
found."""

UNCHECKED_FENCES: Final[dict[str, str]] = {
    "jsonc": (
        "JSONC has no stdlib parser; the fences carry `...` elisions, and a hand-rolled comment "
        "stripper would be a second implementation of a parser this repository does not own"
    ),
    "sql": (
        "a dialect check needs a connection and a schema; applying DDL out of a document is a "
        "side effect a document gate has no standing to take"
    ),
    "yaml": "no yaml parser in any dependency group, and core may not grow one (INV-2)",
    "text": "not a language",
    "console": "a transcript of a session, not a program",
    "bash": "no stdlib parser; `bash -n` would need bash on every runner, including Windows",
    "markdown": "the document's own language, quoted",
    "abnf": "a grammar, quoted from its own RFC",
    "typescript": "the second language is TypeScript and its parser lives in `toolchains/`",
    "ts": "as `typescript`",
    "js": "as `typescript`",
    "rust": "quoted from a mined repository, not a language this project builds",
    "xml": "a fragment, not a document, so `ElementTree` would reject a correct quotation",
    "jsonl": "one JSON value per line; the fences elide lines, so the file is not the lines",
    "ebnf": "a grammar, quoted",
    "diff": "not a language",
    "": "an unlabelled fence names no parser, so clause (a) has nothing to apply",
}
"""Every fence language this script counts and does not check, each saying why.

The clause is *"every fenced block parses under the parser its fence names"*, so a fence naming no
language, or naming one no parser here implements, is outside it. Printed with its count on every
run: a reader comparing this list against the corpus is the only check on whether the clause's
coverage is what it claims, and a silently unchecked language would be the hole."""

PARSE_EXEMPT: Final[tuple[tuple[str, int, int, str], ...]] = (
    #  (document, the fence's opening line, the offending line, why)
    #  ---- the aligned one-line class body. A `class X(StrEnum): A="a"; B="b"` whose members
    #  continue on the next line at the column of the first member is a column layout, not python.
    ("docs/plan/_notes/charter.md", 1230, 1247, "`class Layer(StrEnum):`, members aligned"),
    ("docs/plan/03-document-model.md", 96, 110, "the same block, in its sole home"),
    ("docs/plan/_notes/charter.md", 5974, 5977, "`class Provenance(StrEnum):`, members aligned"),
    ("docs/plan/09-generation.md", 779, 782, "the same block, in its sole home"),
    #  ---- a member or a docstring at a column inside an aligned block
    ("docs/plan/_notes/charter.md", 2399, 2463, "`def read_set_digest` under a comment column"),
    ("docs/plan/_notes/charter.md", 7275, 7351, "a docstring at an aligned field block's column"),
    ("docs/plan/18-api-sketch.md", 260, 461, "a docstring at an aligned field block's column"),
    ("docs/plan/18-api-sketch.md", 675, 718, "a docstring at an aligned field block's column"),
    #  ---- the rest, one cause each
    ("docs/plan/_notes/charter.md", 4257, 4326, "a box-drawing tree diagram in a python fence"),
    ("docs/plan/03-document-model.md", 1873, 1889, "four `def`s split by `;`, not python"),
    ("docs/plan/15-observability.md", 1344, 1346, "a quoted fragment of another project's code"),
)
"""The eleven python fences that do not parse, every one in a frozen document.

The shape of this list is the one `plan_lint.py`'s docstring argues for and the one
`test_core_eager_surface.py`'s `FILLED_HOMES` and `test_p2_freeze.py`'s `FROZEN_SURFACES` already
use twice: an explicit list, one row per locus, each naming WHY, and the check run in both
directions so a row that stops being a finding fails the gate. The alternative -- widening the
clause until these pass -- would be a clause that no longer says what it says.

Ten of the eleven are typography: a design record aligns a one-line class body or a field block
into columns a reader can scan, and python's grammar does not allow it. The eleventh is a verbatim
quotation of another project's source, which cannot be made to parse without falsifying the quote.
Fixing any of them means editing `charter.md` sections 1-8 (*"No line of 1-8 was edited ... and
none will be"*) or a document `tools/plan.sha256` pins -- a `--bless` whose recorded reason would
be "to satisfy a formatter"."""

A2_EXPECTED: Final[tuple[tuple[str, int, str], ...]] = (
    (
        "docs/plan/_notes/charter.md",
        2739,
        "the `when` clause of `repair.never-escalate-furniture`, in the section D4 fence ADR-4 "
        "decision 1 retires IN WHOLE under charter erratum E42",
    ),
)
"""ADR-4 decision 1's measurement, as a register: *"One inline table spans a newline, not two, and
it is a `when` rather than a `then`."* Retired law in a frozen region, so the finding stands and
the gate reports it as expected rather than as a defect."""

CHARTER_D4: Final = "docs/plan/_notes/charter.md"
"""The one document every A3_EXPECTED row names, spelled once so the rows fit a reader's eye."""

A3_EXPECTED: Final[tuple[tuple[str, int, str, str], ...]] = (
    #  (document, the fence's opening line, the rule id, the nullable key it reads)
    (CHARTER_D4, 2576, "gate.form-is-a-signal-not-an-exclusion", "corpus.is_form"),
    (CHARTER_D4, 2576, "decode.pdf-text-layer", "decode.char_count"),
    (CHARTER_D4, 2576, "decode.blank-part-escape", "ink.tiles"),
    (CHARTER_D4, 2576, "repair.never-escalate-furniture", "block.type"),
    (CHARTER_D4, 2576, "repair.promote-to-part", "block.flagged_frac"),
    (CHARTER_D4, 2576, "regen.output-invalid", "verify.finish_reason"),
    (CHARTER_D4, 2576, "degrade.marked-fallback", "verify.attempts_exhausted"),
)
"""The seven ADR-4 decision 1 counted, every one in the retired section D4 fence and none in
05-ingest-and-routing.md section 4.4's forty.

*"(a) seven rules there fail lint check 4 (`OW-P-004`), not nine, against zero in section 4.4 --
and one of the seven is dangerous rather than merely non-compliant,
`repair.never-escalate-furniture` reading `block.type`, which has no PDF provider, so without
`on_unknown = "match"` the furniture guard is silently off on the PDF path and one flagged footer
spawns the inference server for a clean document."* The row for that rule is why this list is
`(id, key)` pairs and not a count: the dangerous one has to be identifiable in the register, not
merely included in a total.

A rule reading several nullable keys is one row, naming the first in sorted order, because the
finding is about the rule."""

ROOTS: Final[tuple[str, ...]] = ("omniweave_core", "omniweave_ports", "omniweave")
"""d0's second half: the three roots have to be among what the scan found.

A scan can match five hundred `omniweave_core.retrieve.*` names, satisfy the floor, and never
touch the type surface a third-party driver writes against -- which is section 8.6's own argument
for why d1's module group is a `*` and not a `+`."""

COUNTER: Final = "docs_symbols_checked"
"""d4's Counter name, in section 8.6's spelling."""

PATH_TAILS: Final[frozenset[str]] = frozenset(
    {"toml", "lock", "json", "yaml", "yml", "md", "py", "sql", "txt", "example", "ts", "cfg", "ini"}
)
"""d1's first exclusion rule: a dotted tail that is a file extension makes the name a PATH.

`omniweave.toml`, `omniweave.index.lock`, `omniweave.toml.example` and `omniweave.d.ts` all match
section 8.6's own symbol regex and none of them is a symbol. 97 occurrences over the corpus, and a
rule rather than a list because the next configuration file would otherwise need a row."""

_RESOLVED: Final[dict[str, bool]] = {}
"""`_resolve_dotted`'s memo. 503 checked names over 40 documents, with heavy repetition."""

_SYMBOL: Final = re.compile(r"`(omniweave(?:_[a-z]+)*(?:\.[a-z_]+)*(?:\.[A-Za-z_]\w*)?)`")
r"""Section 8.6's d1 row, verbatim: `^omniweave(_[a-z]+)*(\.[a-z_]+)*(\.[A-Za-z_]\w*)?$`."""

_IMPORT_LINE: Final = re.compile(
    r"from\s+(omniweave(?:_[a-z]+)*(?:\.[a-z_]+)*)\s+import\s+\(?([^)\n]+)\)?"
)
_GATE_ID: Final = re.compile(r"`(G\d+)`")
_JOB_ASSERTION: Final = re.compile(r"`((?:gates|build|conform|versions|toolchains)\.[a-z_]+)`")
r"""A `[[job_assertion]]` name is `<job>.<assertion>`, and the job half is one of section 6.2's.

Anchored on the job names rather than on `\w+\.\w+` because the loose form matches
`gates.toml` -- a filename -- and reports it as an assertion nobody registered."""

_REGISTER_PATH: Final = re.compile(
    r"`((?:tools|eval|schema)/[a-z_0-9./-]+\.(?:toml|json|yaml|py)|codes\.toml)`"
)
_VERB: Final = re.compile(r"`ow ([a-z]+)(?: ([a-z][a-z-]*))?`")
"""`ow <group> <verb>`. The CLI spells a verb with hyphens and `ACTIONS` with underscores, so
`ow eval release-check` resolves against `eval.release_check`."""

_ENV: Final = re.compile(r"`(OMNIWEAVE_[A-Z0-9_]+)`")
_CODE: Final = re.compile(r"`(OW-[A-Z]-\d+|OW_[A-Z][A-Z0-9_]{3,})`")
_LINK: Final = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s#]+)(?:#[^)\s]*)?\)")
_SECTION_REF: Final = re.compile(
    r"\]\((?P<target>[0-9A-Za-z_./-]+\.md)\)\s*(?:\u00a7|section\s)\s?(?P<section>\d+(?:\.\d+)*)"
)
_HEADING_NUMBER: Final = re.compile(r"^#{2,6}\s+(\d+(?:\.\d+)*)[.)]?\s", re.MULTILINE)
_DIST_COUNT: Final = re.compile(
    r"\b(twelve|thirteen|fourteen|fifteen|sixteen|seventeen)\s+"
    r"(?:first-party\s+)?distributions?\b",
    re.IGNORECASE,
)
_DIST_ROW: Final = re.compile(r"^\| `(omniweave(?:-[a-z0-9-]+)?)` \|", re.MULTILINE)
"""One row of either `dist` table of 11-repo-layout.md section 1.2, by its first column."""
_ATTACHMENT_PARAGRAPH: Final = (
    "**The attachment distributions, separately versioned and outside the fourteen.**"
)
"""The sentence between section 1.2's two tables, which is what splits them."""
NUMBER_WORDS_VALUE: Final[dict[str, int]] = {
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
}

D1_DECLARED: Final[tuple[tuple[str, str, str], ...]] = (
    #  ---- a document names it IN ORDER TO SAY it does not exist. The `[[absent]]` shape
    #  `tools/invariants.toml` already uses, for the same reason.
    (
        "omniweave.operators",
        "docs/plan/01-principles.md:1068",
        "a reserved entry-point group, 'created deliberately never' (02-architecture.md:892); "
        "P-2's own worked example of an abstraction with one implementation",
    ),
    (
        "omniweave.sinks",
        "docs/plan/01-principles.md:1089",
        "AP-2's rejected example: 'a third extension point created for one implementation'",
    ),
    (
        "omniweave.exporters",
        "docs/plan/04-driver-system.md:76",
        "the sentence is 'there is no `omniweave.exporters`'",
    ),
    (
        "omniweave_core.retrieve.rerank",
        "docs/plan/11-repo-layout.md:2384",
        "section 8.6's own d1 FAILURE-MESSAGE example, printed to show what a finding looks like",
    ),
    #  ---- a key in a manifest, not a symbol. Four on one line of the run-manifest listing.
    (
        "omniweave.contract",
        "docs/plan/15-observability.md:257",
        "a run-manifest key, not a module",
    ),
    (
        "omniweave.schema",
        "docs/plan/15-observability.md:257",
        "a run-manifest key, not a module",
    ),
    (
        "omniweave.config_digest",
        "docs/plan/15-observability.md:257",
        "a run-manifest key, not a module",
    ),
    (
        "omniweave.corpus_id",
        "docs/plan/15-observability.md:257",
        "a run-manifest key, not a module",
    ),
    #  ---- a drift in a frozen document, with the right answer recorded beside it
    (
        "omniweave_core.model.DocSink",
        "docs/plan/02-architecture.md:486",
        "DRIFT: `DocSink` ships at `omniweave_core.store.doc.DocSink`, which is where "
        "docs/ARCHITECTURE.md and test_architecture_doc.py resolve it. The document is frozen, so "
        "the correction is an erratum the repository owner owes, not an edit this gate can make",
    ),
    #  ---- unbuilt, and named in no 16-roadmap.md row, so d1's escape does not reach them
    (
        "omniweave_conform.testkit",
        "docs/plan/02-architecture.md:271",
        "the driver testkit; P3 builds it and the roadmap names it in no work-item row",
    ),
    (
        "omniweave_core.paths",
        "docs/plan/14-security.md:1834",
        "the path-containment module; unbuilt and unscheduled",
    ),
    (
        "omniweave_core.model.payload",
        "docs/plan/03-document-model.md:991",
        "the payload submodule; unbuilt and unscheduled",
    ),
    (
        "omniweave_core.model.taint",
        "docs/plan/04-driver-system.md:2581",
        "the taint submodule; unbuilt and unscheduled",
    ),
    (
        "omniweave_core.store.crypto",
        "docs/plan/14-security.md:1012",
        "the at-rest encryption module; unbuilt and unscheduled",
    ),
)
"""The fourteen names that survive d1's three rules, each saying WHAT IT IS.

Four are identifiers a document names in order to say they do not exist, four are manifest keys,
one is a drift in a frozen document with the right symbol recorded beside it, and five are unbuilt
with no roadmap row to escape through. Checked in both directions: a row that resolves, or that no
document names any more, fails the gate, so the list can only shrink."""

D2_PLANNED_PATHS: Final[frozenset[str]] = frozenset(
    {
        "tools/scorekinds.toml",
        "tools/lock_allow.toml",
        "tools/wirekeys.toml",
        "tools/embeddings.toml",
        "tools/indexes.toml",
        "tools/toolchains.toml",
        "tools/threats.toml",
        "tools/metrics.toml",
        "tools/codes.toml",
        "tools/migration_lint.py",
        "tools/gate_graph_schema.py",
        "tools/count_schema.py",
        "tools/gen_glossary.py",
        "tools/lock_check.py",
        "eval/quarantine.toml",
        "eval/degradations.toml",
        "schema/drivers-check-out-v1.json",
        "schema/metric-v1.json",
        "schema/degradation-v1.json",
    }
)
"""Nineteen registers and scripts the plan names and nothing has written yet.

It was twenty until D998 landed `tools/risks.toml`, which is this list working as intended: the
row's own test asserts both directions, so the register appearing failed the gate and the fix was
to delete the row in the commit that created the file.

`tools/codes.toml` is the odd one: the register is at the repository root as `codes.toml`, and
ADR-9:180 writes it `tools/codes.toml`. Recorded here rather than silently resolved to the root
file, because resolving it would hide a one-word error in an ADR."""

D2_NON_OVERRIDE_ENV: Final[frozenset[str]] = frozenset(
    {
        "OMNIWEAVE_API_KEY",
        "OMNIWEAVE_BLESS",
        "OMNIWEAVE_DRIVER_PATH",
        "OMNIWEAVE_ENFORCE",
        "OMNIWEAVE_HOME",
        "OMNIWEAVE_HOOK_TTL",
        "OMNIWEAVE_PROBE_EPOCH",
        "OMNIWEAVE_TRACEPARENT",
    }
)
"""Eight `OMNIWEAVE_*` variables that override no configuration key, so `[env]` is the wrong home.

`tools/config_axes.toml`'s `[env]` table maps a CONFIG KEY to the variable that overrides it, and
all 135 of its rows are derived from the key. These eight are not overrides: a provider credential
(which this project reads from the environment and never from a file), a dev escape hatch for a
non-Python driver (02-architecture.md:890 row 16), a hook enforcement switch, a hook TTL, the probe
cache epoch, W3C trace context, the home directory and the bless switch. Each needs its own home
and none of them is this one.

Two of the eight are named in 16-roadmap.md, and that is NOT why they are here. The roadmap escape
is d1's, for a symbol something will build; an environment variable a roadmap row mentions is not
thereby an override of a configuration key, so the escape must not reach this family. A census
that let it through reported six where there are eight."""

D2_UNDOCUMENTED_KEYS: Final[frozenset[str]] = frozenset(
    {
        "serve.max_queued_queries",
        "services.*.autostart",
        "services.*.batch_wait_ms",
        "services.*.capacity",
        "services.*.max_batch",
    }
)
"""Five of the register's 135 config keys that no document names.

The other 130 are named, so this is the short tail rather than a hole. All five are serve-side or
service-side knobs whose owning document numbers them in a table d2's scan does not reach; a row
here says so rather than letting the count drift."""

__all__ = [
    "A2_EXPECTED",
    "A3_EXPECTED",
    "COUNTER",
    "D1_DECLARED",
    "D2_NON_OVERRIDE_ENV",
    "D2_PLANNED_PATHS",
    "D2_UNDOCUMENTED_KEYS",
    "PARSE_EXEMPT",
    "PATH_TAILS",
    "ROOTS",
    "UNCHECKED_FENCES",
    "Fence",
    "Finding",
    "brace_depth_findings",
    "check_clause_a",
    "check_clause_a2",
    "check_clause_a3",
    "check_clause_d1",
    "check_clause_d2",
    "check_clause_d3",
    "check_clause_d4",
    "clause_c_state",
    "documents",
    "entry_point_groups",
    "expanded_imports",
    "fences",
    "main",
    "nullability",
    "policy_documents",
    "rule_fences",
    "signal_keys_read",
    "walk_documents",
]


@dataclass(frozen=True, slots=True)
class Fence:
    """One fenced block: where it opens, what language it names, and its body."""

    document: Path
    language: str
    line: int
    body: str

    @property
    def where(self) -> str:
        return f"{self.document.relative_to(REPO).as_posix()}:{self.line}"


@dataclass(frozen=True, slots=True)
class Finding:
    headline: str
    detail: tuple[str, ...] = ()

    def render(self) -> str:
        return "\n".join((f"{PREFIX} FAIL: {self.headline}", *self.detail))


def _where(document: Path) -> str:
    """A document's locus for a failure message: repo-relative, or its name if it is not under
    the repository. A fixture tree in `tmp_path` is the second case, and a gate that raised
    `ValueError` there would be a gate its own tests could not drive to fail."""
    try:
        return document.relative_to(REPO).as_posix()
    except ValueError:
        return document.name


def _table(parsed: dict[str, object], key: str) -> list[dict[str, object]]:
    """One table array of a parsed TOML document, as rows.

    A missing or malformed key reads as no rows, so a register this gate cannot parse produces a
    finding from the check that needed it rather than a traceback before any finding is printed.
    """
    rows = parsed.get(key, [])
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


#  ---------------------------------------------------------------------------------------------
#  The corpus


def documents() -> tuple[Path, ...]:
    """Clause (a)'s scope: the committed design record, and not the deliberation behind it.

    The charter and the nineteen because a2 and a3 are worded over exactly those ("a ` ```toml `
    fence in `charter.md` or a plan document"); `README.md`, `glossary.md`, the ADRs and
    `docs/ARCHITECTURE.md` because they are the same record and carry fences on the same terms.

    NOT `_notes/panels/`, `_notes/rulings/` or the rest of `_notes/`. Those record a deliberation
    and quote other people's code: 93 of their fences do not parse, and every one of them is a
    faithful quotation of a partial snippet. A gate over them would be an instruction to falsify
    the record, which is the same reason `gate_invariants.py`'s A5 stops at the same boundary.
    """
    return (
        CHARTER,
        *sorted(path for path in PLAN.glob("*.md") if _NUMBERED.match(path.name)),
        PLAN / "README.md",
        PLAN / "glossary.md",
        *sorted((PLAN / "adr").glob("*.md")),
        REPO / "docs" / "ARCHITECTURE.md",
    )


def policy_documents() -> tuple[Path, ...]:
    """a2's and a3's scope, in the plan's own words: `charter.md` or a plan document."""
    return (
        CHARTER,
        *sorted(path for path in PLAN.glob("*.md") if _NUMBERED.match(path.name)),
    )


def fences(document: Path) -> list[Fence]:
    """Every fenced block, by its opening line.

    The closing run is matched on its own line and the opening run's length is remembered, because
    a nested four-backtick fence holding a three-backtick one is a shape the plan uses and a naive
    scanner closes the outer fence on the inner one's opener.
    """
    found: list[Fence] = []
    opener: str | None = None
    language, start, body = "", 0, []
    for number, line in enumerate(document.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if opener is None:
            matched = _FENCE_OPEN.match(stripped)
            if matched is not None:
                opener, language, start, body = matched.group(1), matched.group(2), number, []
            continue
        if _FENCE_CLOSE.match(stripped) and len(stripped) >= len(opener):
            found.append(Fence(document, language, start, "\n".join(body)))
            opener = None
            continue
        body.append(line)
    return found


#  ---------------------------------------------------------------------------------------------
#  Clause (a)


def check_clause_a() -> tuple[list[str], list[Finding]]:
    parsers = {"toml": tomllib.loads, "json": json.loads, "python": ast.parse}
    exempt = {(path, line): why for path, line, _offending, why in PARSE_EXEMPT}
    counted: dict[str, int] = {}
    checked = 0
    findings: list[Finding] = []
    seen: set[tuple[str, int]] = set()
    for document in documents():
        if not document.is_file():
            findings.append(Finding(f"clause (a)'s scope names {document} and it is not a file."))
            continue
        for fence in fences(document):
            counted[fence.language] = counted.get(fence.language, 0) + 1
            parser = parsers.get(fence.language)
            if parser is None:
                if fence.language not in UNCHECKED_FENCES:
                    findings.append(
                        Finding(
                            f"{fence.where} names fence language {fence.language!r}, which has "
                            "neither a parser nor a row in UNCHECKED_FENCES.",
                            (
                                FAIL_INDENT
                                + "fix: add a parser, or a row saying why the clause does not "
                                + "reach it. An unlisted language is an unchecked one.",
                            ),
                        )
                    )
                continue
            checked += 1
            key = (fence.document.relative_to(REPO).as_posix(), fence.line)
            try:
                parser(fence.body)
            except (tomllib.TOMLDecodeError, json.JSONDecodeError, SyntaxError, ValueError) as why:
                seen.add(key)
                if key in exempt:
                    continue
                findings.append(
                    Finding(
                        f"{fence.where} is a ` ```{fence.language} ` fence that does not parse: "
                        f"{type(why).__name__}: {str(why).splitlines()[0][:90]}",
                        (
                            FAIL_INDENT
                            + "fix: the fence, or -- if the document is frozen and the block is "
                            + "quoted or typographic -- a PARSE_EXEMPT row saying which.",
                        ),
                    )
                )
    total = sum(counted.values())
    if total < FENCE_FLOOR:
        findings.insert(
            0,
            Finding(
                f"the fence scanner matched {total} fence(s), floor is {FENCE_FLOOR}.",
                (
                    FAIL_INDENT
                    + "every finding below is vacuous until this holds: a scanner that matches "
                    + "nothing reports nothing and exits 0.",
                ),
            ),
        )
    for path, line, _offending, why in PARSE_EXEMPT:
        if (path, line) not in seen:
            findings.append(
                Finding(
                    f"PARSE_EXEMPT {path}:{line} parses now ({why}).",
                    (FAIL_INDENT + "fix: delete the row. The list may shrink and never grow.",),
                )
            )
    report = [
        f"  clause (a)  {checked} fence(s) parsed under their own parser, "
        f"{len(PARSE_EXEMPT)} declared exception(s)",
        "  not checked "
        + ", ".join(
            f"{language or '(unlabelled)'} {count}"
            for language, count in sorted(counted.items())
            if language not in {"toml", "json", "python"}
        ),
    ]
    return report, findings


#  ---------------------------------------------------------------------------------------------
#  Clause (a2)


def _skip_string(line: str, index: int, quote: str) -> int:
    """Past the closing quote of a single-line string, or to the end of the line.

    A backslash escapes the next character inside a BASIC string only: TOML's literal strings,
    `'...'`, have no escapes at all, so treating one uniformly would read `'c:\\path\\'` as
    unterminated and swallow the rest of the line.
    """
    while index < len(line):
        if quote == '"' and line[index] == "\\":
            index += 2
            continue
        if line[index] == quote:
            return index + 1
        index += 1
    return index


def _walk_line(line: str, depth: int, multiline: str | None) -> tuple[int, str | None]:
    """One physical line of a toml fence, returning the brace depth and string state it leaves."""
    index = 0
    while index < len(line):
        rest = line[index:]
        if multiline is not None:
            if rest.startswith(multiline):
                multiline = None
                index += 3
            else:
                index += 1
            continue
        if rest.startswith(('"""', "'" * 3)):
            multiline = rest[:3]
            index += 3
            continue
        character = rest[0]
        if character in "\"'":
            index = _skip_string(line, index + 1, character)
            continue
        if character == "#":
            break
        if character == "{":
            depth += 1
        elif character == "}":
            depth = max(0, depth - 1)
        index += 1
    return depth, multiline


def brace_depth_findings(body: str, first_line: int) -> list[tuple[int, int]]:
    """Every physical line that ends at brace depth >= 1, as `(line number, depth)`.

    A lexical walk, which is the clause. Outside a string, `#` opens a comment to end of line; a
    run of three quote characters opens a multi-line string and a single one opens a single-line
    string; and a backslash escapes the next character inside a basic string only, because TOML's
    literal strings have no escapes.
    """
    findings: list[tuple[int, int]] = []
    depth = 0
    multiline: str | None = None
    for offset, line in enumerate(body.splitlines()):
        depth, multiline = _walk_line(line, depth, multiline)
        if multiline is None and depth >= 1:
            findings.append((first_line + 1 + offset, depth))
    return findings


def check_clause_a2() -> tuple[list[str], list[Finding]]:
    expected = {(path, line): why for path, line, why in A2_EXPECTED}
    seen: set[tuple[str, int]] = set()
    scanned = 0
    findings: list[Finding] = []
    for document in policy_documents():
        for fence in fences(document):
            if fence.language != "toml":
                continue
            scanned += 1
            relative = fence.document.relative_to(REPO).as_posix()
            for line, depth in brace_depth_findings(fence.body, fence.line):
                seen.add((relative, line))
                if (relative, line) in expected:
                    continue
                findings.append(
                    Finding(
                        f"{relative}:{line} ends at brace depth {depth}, inside the ` ```toml ` "
                        f"fence at {fence.where}.",
                        (
                            FAIL_INDENT
                            + "the charter's four-times-stated style rule is \"a sub-table, NOT a "
                            + 'multi-line inline table". `tomllib` accepts this and always would; '
                            + "that is why the clause is lexical.",
                            FAIL_INDENT + "fix: a sub-table, or one line.",
                        ),
                    )
                )
    if scanned < TOML_FENCE_FLOOR:
        findings.insert(
            0, Finding(f"clause (a2) scanned {scanned} toml fence(s), floor is {TOML_FENCE_FLOOR}.")
        )
    for path, line, why in A2_EXPECTED:
        if (path, line) not in seen:
            findings.append(
                Finding(
                    f"A2_EXPECTED {path}:{line} no longer ends at depth >= 1 ({why}).",
                    (FAIL_INDENT + "fix: delete the row. The list may shrink and never grow.",),
                )
            )
    return [
        f"  clause (a2) {scanned} toml fence(s) walked, {len(A2_EXPECTED)} expected finding(s) "
        "(ADR-4 decision 1, charter erratum E42)"
    ], findings


#  ---------------------------------------------------------------------------------------------
#  Clause (a3) - the P1 interim standalone check 4


def nullability() -> dict[str, bool]:
    """05-ingest-and-routing.md section 5.1's `null` column, by signal key.

    Parsed out of the markdown table and not imported: ADR-4 decision 2's interim form is explicit
    that the standalone check reads the column *"rather than by importing `omniweave.route`"*, and
    `omniweave.route` does not exist until P5.
    """
    found: dict[str, bool] = {}
    for line in ROUTING.read_text(encoding="utf-8").splitlines():
        matched = _SIGNAL_ROW.match(line)
        if matched is None:
            continue
        cells = [one.strip() for one in _CELL.split(line.strip().strip("|"))]
        if len(cells) != SIGNAL_COLUMNS:
            continue
        null = cells[NULL_COLUMN].replace("*", "").strip().lower()
        if null in {"yes", "no"}:
            found[matched.group(1)] = null == "yes"
    return found


def signal_keys_read(when: object) -> list[tuple[str, object]]:
    """Every `(signal key, clause)` a `when` reads, descending through the combinators."""
    if not isinstance(when, dict):
        return []
    found: list[tuple[str, object]] = []
    for key, clause in when.items():
        if key in COMBINATORS:
            nested = clause if isinstance(clause, list) else [clause]
            for one in nested:
                found.extend(signal_keys_read(one))
            continue
        found.append((key, clause))
    return found


def rule_fences() -> list[tuple[Fence, list[dict[str, object]]]]:
    """Every toml fence in a3's scope that parses to a table containing a `[[rule]]` array."""
    found: list[tuple[Fence, list[dict[str, object]]]] = []
    for document in policy_documents():
        for fence in fences(document):
            if fence.language != "toml":
                continue
            try:
                parsed = tomllib.loads(fence.body)
            except tomllib.TOMLDecodeError:
                #  Clause (a) owns the parse failure; this clause reads what parses.
                continue
            rules = parsed.get("rule")
            if isinstance(rules, list):
                found.append((fence, [one for one in rules if isinstance(one, dict)]))
    return found


def check_clause_a3() -> tuple[list[str], list[Finding]]:
    null = nullability()
    expected = {(path, line, rule) for path, line, rule, _key in A3_EXPECTED}
    seen: set[tuple[str, int, str]] = set()
    findings: list[Finding] = []
    fence_count = 0
    rule_count = 0
    if not null:
        findings.append(
            Finding(
                "section 5.1's `null` column parsed to nothing, so check 4 is vacuous.",
                (
                    FAIL_INDENT
                    + "the column is load-bearing for this gate as well as for `ow route "
                    + "lint` (ADR-4 decision 2).",
                ),
            )
        )
    for fence, rules in rule_fences():
        fence_count += 1
        rule_count += len(rules)
        relative = fence.document.relative_to(REPO).as_posix()
        for rule in rules:
            identifier = str(rule.get("id", "<no id>"))
            read = signal_keys_read(rule.get("when"))
            if not read:
                continue
            if all(isinstance(one, dict) and set(one) == {"exists"} for _key, one in read):
                #  Check 4's own exception: an `exists`-only `when` cannot read UNKNOWN.
                continue
            nullable = sorted({key for key, _one in read if null.get(key, False)})
            if not nullable or "on_unknown" in rule:
                continue
            key = (relative, fence.line, identifier)
            seen.add(key)
            if key in expected:
                continue
            findings.append(
                Finding(
                    f"{relative}:{fence.line} rule {identifier!r} reads nullable "
                    f"{', '.join(nullable)} and declares no `on_unknown` (OW-P-004).",
                    (
                        FAIL_INDENT
                        + "check 4: every rule reading a nullable key declares `on_unknown`; a "
                        + "rule whose `when` is `exists`-only does not need one.",
                    ),
                )
            )
    for path, line, rule, key in A3_EXPECTED:
        if (path, line, rule) not in seen:
            findings.append(
                Finding(
                    f"A3_EXPECTED {path}:{line} {rule!r} passes check 4 now (it read {key}).",
                    (FAIL_INDENT + "fix: delete the row. The list may shrink and never grow.",),
                )
            )
    return [
        f"  clause (a3) standalone check 4 over {fence_count} `[[rule]]` fence(s), {rule_count} "
        f"rule(s), {len(null)} registry row(s) ({sum(null.values())} nullable), "
        f"{len(A3_EXPECTED)} expected finding(s)"
    ], findings


#  ---------------------------------------------------------------------------------------------
#  Clause (d) - d0 the walk found something, d1 symbols, d2 registers, d3 links, d4 the count


def walk_documents() -> tuple[Path, ...]:
    """Clause (d)'s scope, in section 8.6's own words: `docs/ARCHITECTURE.md` and `docs/plan/*.md`.

    The ADRs are in, because an ADR amends a plan document and names the same symbols on the same
    terms; `_notes/` is out, for the reason `documents()` gives above.
    """
    return (
        REPO / "docs" / "ARCHITECTURE.md",
        *sorted(PLAN.glob("*.md")),
        *sorted((PLAN / "adr").glob("*.md")),
    )


def _register_value(key: str) -> int:
    """One integer from G27's row. The floor and the two ceilings live beside the row, not here."""
    register = tomllib.loads(GATES.read_text(encoding="utf-8"))
    rows = register.get("gate", [])
    row = next((one for one in rows if isinstance(one, dict) and str(one.get("id")) == "G27"), None)
    if row is None:
        return -1
    clauses = row.get("clause", [])
    for clause in clauses:
        if isinstance(clause, dict) and key in clause:
            value = clause[key]
            if isinstance(value, int):
                return value
    return -1


def _resolve_dotted(dotted: str) -> bool:
    """Import the longest importable prefix, then `getattr` the rest. Memoised per process."""
    if dotted in _RESOLVED:
        return _RESOLVED[dotted]
    parts = dotted.split(".")
    found = False
    for cut in range(len(parts), 0, -1):
        try:
            target = importlib.import_module(".".join(parts[:cut]))
        except ImportError:
            continue
        found = True
        for attribute in parts[cut:]:
            if not hasattr(target, attribute):
                found = False
                break
            target = getattr(target, attribute)
        break
    _RESOLVED[dotted] = found
    return found


def entry_point_groups() -> frozenset[str]:
    """Every entry-point group the workspace declares, read from the pyprojects.

    d1's second exclusion rule. `omniweave.drivers` matches the symbol shape and is not a module:
    it is the name of a group `importlib.metadata` reads, so importing it is the wrong question.
    Read from `packages/*/pyproject.toml` rather than listed here, so a group added to a
    distribution is known to this gate without anyone editing it.
    """
    found: set[str] = set()
    for pyproject in sorted((REPO / "packages").glob("*/pyproject.toml")):
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        project = data.get("project", {})
        if isinstance(project, dict):
            entries = project.get("entry-points", {})
            if isinstance(entries, dict):
                found.update(entries)
    return frozenset(found)


def expanded_imports(document: Path) -> list[tuple[str, int]]:
    """`from <root> import (A, B)` in a python fence, expanded to `root.A` and `root.B`.

    Section 8.6 requires it in those words, and the `symbol_floor` is why it cannot be skipped:
    "588 dotted names plus 32 names expanded out of `from <root> import (...)` lines". Without the
    expansion the scan comes in under the floor and d0 fails, which is the floor doing its job.

    An unparseable fence falls back to a regex over the source. Clause (a) owns the parse failure
    and has its own declared exceptions; discarding those fences here would silently drop the
    import lines in them, and `18-api-sketch.md` -- which contributes 35 of the 45 -- holds two.
    """
    found: list[tuple[str, int]] = []
    for fence in fences(document):
        if fence.language != "python":
            continue
        try:
            tree = ast.parse(fence.body)
        except SyntaxError:
            for matched in _IMPORT_LINE.finditer(fence.body):
                for name in matched.group(2).split(","):
                    bare = name.strip().split(" as ")[0].strip()
                    if bare and bare != "*":
                        found.append((f"{matched.group(1)}.{bare}", fence.line))
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if not node.module.startswith("omniweave"):
                continue
            for alias in node.names:
                if alias.name != "*":
                    found.append((f"{node.module}.{alias.name}", fence.line))
    return found


def check_clause_d1() -> tuple[list[str], list[Finding]]:
    """d0 and d1 together, because d0's floor is a statement about d1's scan.

    Three exclusion rules, each a rule and not a list, because each generalises:

    * **a filename is not a symbol.** `omniweave.toml`, `omniweave.index.lock` and
      `omniweave.toml.example` all match section 8.6's own regex, and importing them is nonsense.
      The test is the dotted tail against `PATH_TAILS`. 97 occurrences.
    * **an entry-point group is not a module** -- `entry_point_groups()`. 22 occurrences.
    * **the roadmap escape**, which is section 8.6's only sanctioned one: "a declared-and-not-yet-
      built row in `docs/plan/16-roadmap.md`'s milestone table ... not a comment or an allowlist
      file, so an unbuilt symbol is always also a scheduled one". 15 occurrences.

    What is left is `D1_DECLARED`, and its rows are statements rather than tolerance.
    """
    floor = _register_value("symbol_floor")
    groups = entry_point_groups()
    roadmap = (PLAN / "16-roadmap.md").read_text(encoding="utf-8")
    declared = {dotted: why for dotted, _where, why in D1_DECLARED}
    seen: set[str] = set()
    checked = 0
    excluded: dict[str, int] = {}
    roots: set[str] = set()
    findings: list[Finding] = []
    for document in walk_documents():
        text = document.read_text(encoding="utf-8")
        candidates = [
            (found.group(1), text[: found.start()].count("\n") + 1)
            for found in _SYMBOL.finditer(text)
        ]
        candidates.extend(expanded_imports(document))
        for dotted, line in candidates:
            roots.add(dotted.split(".")[0])
            if "." not in dotted:
                #  d0 owns the bare roots and d4 does not count them: section 8.6 says 1,619 of
                #  them "would drown d4's ratchet in prose noise".
                excluded["a bare root"] = excluded.get("a bare root", 0) + 1
                continue
            if dotted.rsplit(".", 1)[1] in PATH_TAILS:
                excluded["a path, by its tail"] = excluded.get("a path, by its tail", 0) + 1
                continue
            if dotted in groups:
                excluded["an entry-point group"] = excluded.get("an entry-point group", 0) + 1
                continue
            checked += 1
            if _resolve_dotted(dotted):
                continue
            if dotted in roadmap:
                excluded["scheduled in 16-roadmap.md"] = (
                    excluded.get("scheduled in 16-roadmap.md", 0) + 1
                )
                continue
            seen.add(dotted)
            if dotted in declared:
                continue
            findings.append(
                Finding(
                    f"{_where(document)}:{line} {dotted} does not resolve.",
                    (
                        FAIL_INDENT
                        + "fix: the document, a row in 16-roadmap.md scheduling the symbol, or a "
                        + "D1_DECLARED row saying what it is if it is not a symbol at all.",
                    ),
                )
            )
    if checked < floor:
        findings.insert(
            0,
            Finding(
                f"d0: the symbol scan checked {checked} name(s), floor is {floor}.",
                (
                    FAIL_INDENT
                    + "every assertion below is vacuous until this holds. If the number fell "
                    + "just short, the `from <root> import (...)` expansion is what to check.",
                ),
            ),
        )
    missing_roots = sorted(set(ROOTS) - roots)
    if missing_roots:
        findings.append(Finding(f"d0: root(s) the scan never matched: {missing_roots}"))
    for dotted, where, why in D1_DECLARED:
        if dotted not in seen:
            findings.append(
                Finding(
                    f"D1_DECLARED {dotted} resolves now, or no document names it ({where}: {why}).",
                    (FAIL_INDENT + "fix: delete the row. The list may shrink and never grow.",),
                )
            )
    report = [
        f"  clause (d0) {checked} symbol(s) checked, floor {floor}; "
        f"the three roots present, {len(roots) - len(ROOTS)} other import package(s) named",
        "  clause (d1) excluded by rule: "
        + ", ".join(f"{reason} {count}" for reason, count in sorted(excluded.items()))
        + f"; {len(D1_DECLARED)} declared",
    ]
    return report, findings


@dataclass(frozen=True, slots=True)
class _D2Registers:
    """Every register d2 resolves against, read once.

    `assertions` is the union of two: a `<job>.<name>` spelling is ambiguous between a
    `[[job_assertion]]` and a budget row -- `conform.mandatory_tier_s` is `eval/perf.toml`'s and
    `gates.invariant_register` is `tools/gates.toml`'s -- so both registers are the register, and a
    check reading only one reports a budget row as an assertion nobody declared.
    """

    gates: frozenset[str]
    assertions: frozenset[str]
    invariants: frozenset[str]
    invariant_scan: re.Pattern[str]
    codes: frozenset[str]
    overrides: frozenset[str]
    actions: frozenset[str]
    action_groups: frozenset[str]
    roadmap: str


def _d2_registers() -> _D2Registers:
    register = tomllib.loads(GATES.read_text(encoding="utf-8"))
    perf = tomllib.loads((REPO / "eval" / "perf.toml").read_text(encoding="utf-8"))
    invariants = tomllib.loads((REPO / "tools" / "invariants.toml").read_text(encoding="utf-8"))
    codes = tomllib.loads((REPO / "codes.toml").read_text(encoding="utf-8"))
    axes = tomllib.loads((REPO / "tools" / "config_axes.toml").read_text(encoding="utf-8"))
    actions = frozenset(importlib.import_module("omniweave.surface.registry").ACTIONS)
    held = {str(row["id"]) for row in (*_table(invariants, "inv"), *_table(invariants, "member"))}
    held |= {str(row["id"]) for row in _table(invariants, "absent")}
    return _D2Registers(
        gates=frozenset(str(row["id"]) for row in _table(register, "gate")),
        assertions=frozenset(
            {str(row["name"]) for row in _table(register, "job_assertion")}
            | {str(row["id"]) for row in _table(perf, "budget")}
        ),
        invariants=frozenset(held),
        invariant_scan=re.compile(
            "|".join(f"(?:{row['pattern']})" for row in _table(invariants, "family"))
        ),
        codes=frozenset(
            {str(row["numeric"]) for row in _table(codes, "code")}
            | {str(row["symbol"]) for row in _table(codes, "code")}
        ),
        overrides=frozenset(str(one) for one in axes["env"].values()),
        actions=actions,
        action_groups=frozenset(one.split(".")[0] for one in actions),
        roadmap=(PLAN / "16-roadmap.md").read_text(encoding="utf-8"),
    )


def _d2_hard_families(
    text: str, where: str, held: _D2Registers, hard: dict[str, int]
) -> list[Finding]:
    """The five families that resolve against their own register today, over one document."""

    def locate(matched: re.Match[str]) -> str:
        return f"{where}:{text[: matched.start()].count(chr(10)) + 1}"

    def count(name: str) -> None:
        hard[name] = hard.get(name, 0) + 1

    findings: list[Finding] = []
    for matched in _GATE_ID.finditer(text):
        count("G<n>")
        if matched.group(1) not in held.gates:
            findings.append(
                Finding(f"{locate(matched)} {matched.group(1)} is not in tools/gates.toml.")
            )
    for matched in _JOB_ASSERTION.finditer(text):
        if matched.group(1).rsplit(".", 1)[1] in PATH_TAILS:
            #  `gates.toml` is a filename and matches the shape. PATH_TAILS already carries the
            #  rule that a dotted tail which is a file extension makes the name a path.
            continue
        count("[[job_assertion]]")
        if matched.group(1) not in held.assertions:
            findings.append(
                Finding(f"{locate(matched)} {matched.group(1)} is not a [[job_assertion]] name.")
            )
    for matched in held.invariant_scan.finditer(text):
        count("invariant families")
        if matched.group(0) not in held.invariants:
            findings.append(
                Finding(
                    f"{locate(matched)} {matched.group(0)} is not in tools/invariants.toml.",
                    (
                        FAIL_INDENT
                        + "fix: a row for it, or an [[absent]] row if the document names it in "
                        + "order to say it does not exist.",
                    ),
                )
            )
    for matched in _REGISTER_PATH.finditer(text):
        count("register paths")
        one = matched.group(1)
        if (REPO / one).exists() or one in D2_PLANNED_PATHS:
            continue
        findings.append(
            Finding(
                f"{locate(matched)} {one} is neither a file nor a declared planned register.",
                (FAIL_INDENT + "fix: the path, or a D2_PLANNED_PATHS row with its phase.",),
            )
        )
    for matched in _ENV.finditer(text):
        count("OMNIWEAVE_*")
        one = matched.group(1)
        if one in held.overrides or one in D2_NON_OVERRIDE_ENV:
            continue
        findings.append(
            Finding(
                f"{locate(matched)} {one} is not a config override and is not declared.",
                (
                    FAIL_INDENT
                    + "tools/config_axes.toml's [env] maps a CONFIG KEY to its override; an "
                    + "OMNIWEAVE_* that overrides nothing needs a D2_NON_OVERRIDE_ENV row.",
                ),
            )
        )
    return findings


def _d2_gap_families(
    text: str, held: _D2Registers, hard: dict[str, int], verbs: set[str], codes: set[str]
) -> None:
    """The two that do not resolve at v1.0. They accumulate a GAP rather than a finding; the
    ceilings beside G27's row turn the gap into a verdict."""
    for matched in _VERB.finditer(text):
        group, verb = matched.group(1), matched.group(2)
        spelled = f"ow {group} {verb}" if verb else f"ow {group}"
        resolved = (
            f"{group}.{verb.replace('-', '_')}" in held.actions
            if verb
            else group in held.actions or group in held.action_groups
        )
        if resolved:
            hard["ow verbs (resolved)"] = hard.get("ow verbs (resolved)", 0) + 1
        elif spelled not in held.roadmap:
            verbs.add(spelled)
    for matched in _CODE.finditer(text):
        one = matched.group(1)
        if one in held.codes:
            hard["OW-* (resolved)"] = hard.get("OW-* (resolved)", 0) + 1
        elif one not in held.roadmap:
            codes.add(one)


def _d2_scan() -> tuple[dict[str, int], set[str], set[str], list[Finding]]:
    """One walk of the corpus for every d2 family: the hard counts, the two gaps, the findings.

    One walk and not seven. Each document is read once and every pattern runs over that text, so
    the cost is one pass and every count in the report comes from the same read.
    """
    held = _d2_registers()
    findings: list[Finding] = []
    verb_gap: set[str] = set()
    code_gap: set[str] = set()
    hard: dict[str, int] = {}
    for document in walk_documents():
        text = document.read_text(encoding="utf-8")
        where = _where(document)
        findings.extend(_d2_hard_families(text, where, held, hard))
        _d2_gap_families(text, held, hard, verb_gap, code_gap)
    return hard, verb_gap, code_gap, findings


def _d2_ratchets(verb_gap: set[str], code_gap: set[str]) -> tuple[list[str], list[Finding]]:
    """The two families that do not resolve at v1.0, as ratchets against the register's ceilings.

    Both directions. A rise fails, because a document started naming something nobody scheduled;
    and a ceiling nobody tightened fails too, because a ratchet that is never lowered is a number
    nobody is watching.
    """
    report: list[str] = []
    findings: list[Finding] = []
    for name, gap, key in (
        ("ow verbs", verb_gap, "verb_gap_max"),
        ("OW-* codes", code_gap, "code_gap_max"),
    ):
        ceiling = _register_value(key)
        report.append(f"  clause (d2) {name}: {len(gap)} unresolved, ceiling {ceiling}")
        if len(gap) > ceiling:
            findings.append(
                Finding(
                    f"{name}: {len(gap)} unresolved against a ceiling of {ceiling}.",
                    (
                        FAIL_INDENT + f"new: {sorted(gap)[:6]}",
                        FAIL_INDENT
                        + "fix: build it, schedule it in 16-roadmap.md, or raise the ceiling in "
                        + "tools/gates.toml -- which is a reviewable act, which is the point.",
                    ),
                )
            )
        elif len(gap) < ceiling:
            findings.append(
                Finding(
                    f"{name}: {len(gap)} unresolved and the ceiling is still {ceiling}.",
                    (
                        FAIL_INDENT
                        + "fix: lower the ceiling. A ratchet that is never tightened is a number "
                        + "nobody is watching.",
                    ),
                )
            )
    return report, findings


ATTACHMENT_KEY: Final = "attachment"
"""`[tool.omniweave] attachment = true`, the key a member uses to say it is not a distribution.

11-repo-layout.md section 1.2: *"The attachment distributions, separately versioned and **outside
the fourteen**"*. D909's build note names this key and lists who reads it -- *"G5, the build check,
the wheelhouse and `gen_first_party.py` read that key, so the release still builds 28 files"* --
and `tools/check_build.py` ruling 4 is the same sentence from the other end: *"An attachment is not
one of the 28."* This check reads it for the same reason: a count of distributions that counted
attachments would disagree with the prose, with `check_build.py`, and with the release."""


def _members() -> tuple[tuple[str, bool], ...]:
    """Every workspace member, with whether it declares itself an attachment."""
    out: list[tuple[str, bool]] = []
    for path in sorted((REPO / "packages").glob("*/pyproject.toml")):
        table = tomllib.loads(path.read_text(encoding="utf-8"))
        tool = table.get("tool")
        mine = tool.get("omniweave", {}) if isinstance(tool, dict) else {}
        attachment = bool(mine.get(ATTACHMENT_KEY, False)) if isinstance(mine, dict) else False
        out.append((path.parent.name, attachment))
    return tuple(out)


def _section_1_2_tables() -> tuple[frozenset[str], frozenset[str]]:
    """Section 1.2's two `dist` columns: the distributions, then the attachments.

    The paragraph between them is what splits the tables, and it is quoted rather than counted:
    *"The attachment distributions, separately versioned and outside the fourteen."* A rename of
    that sentence leaves both sets empty, which the caller reports as a finding rather than as two
    tables that happen to agree with the workspace.
    """
    text = (REPO / "docs" / "plan" / "11-repo-layout.md").read_text(encoding="utf-8")
    heading = text.find("### 1.2 ")
    end = text.find("### 1.3 ", heading + 1)
    if heading < 0 or end < 0:
        return frozenset(), frozenset()
    split = text.find(_ATTACHMENT_PARAGRAPH, heading, end)
    if split < 0:
        return frozenset(), frozenset()
    halves = (text[heading:split], text[split:end])
    return tuple(  # type: ignore[return-value]
        frozenset(found.group(1) for found in _DIST_ROW.finditer(half)) for half in halves
    )


def _d2_distributions() -> tuple[list[str], list[Finding]]:
    """The distribution-count check, which section 8.6 calls "the one that keeps section 1.10
    honest".

    **D999 corrected what this counts.** It counted `packages/*/pyproject.toml` and called the
    answer "distributions on disk", which made fifteen members disagree with a prose that says
    fourteen, and the gate reported a plan erratum that does not exist: `omniweave-langchain` is an
    ATTACHMENT, section 1.2's second table lists it as one of five, and section 1.2's own words are
    *"separately versioned and outside the fourteen"*. The prose was right, `check_build.py` ruling
    4 had already drawn the same line for the 28 artefacts, and the gate was measuring a different
    population from the one the sentence is about. It now counts members that do not declare
    `[tool.omniweave] attachment = true`, which is fourteen, and the discrepancy is gone.

    The membership check below is what would have caught that, and is the reason the count is no
    longer the whole check: every member is in exactly one of section 1.2's two tables, by name. A
    fifteenth DISTRIBUTION landing fails the count and names itself; an attachment landing fails
    the membership check until the second table lists it. Section 8.6's predicted case and the case
    that actually happened are different findings now, where before they were one number.
    """
    report: list[str] = []
    findings: list[Finding] = []
    members = _members()
    disk = sum(1 for _name, attachment in members if not attachment)
    attached = sorted(name for name, attachment in members if attachment)
    expected_disk = _register_value("dist_count_disk")
    prose = _register_value("dist_count_prose")
    spelled = collections.Counter()
    for document in walk_documents():
        text = document.read_text(encoding="utf-8")
        for matched in _DIST_COUNT.finditer(text):
            spelled[NUMBER_WORDS_VALUE.get(matched.group(1).lower(), 0)] += 1
    report.append(
        f"  clause (d2) distributions: {disk} on disk, prose says "
        + ", ".join(f"{count}x{said}" for said, count in sorted(spelled.items()))
        + f" (register records disk {expected_disk}, prose {prose} and {prose - 1} excluding core; "
        + f"{len(attached)} attachment(s) outside the count: {', '.join(attached) or 'none'})"
    )
    if disk != expected_disk:
        findings.append(
            Finding(
                f"{disk} distribution(s) on disk and tools/gates.toml records {expected_disk}.",
                (
                    FAIL_INDENT
                    + "fix: `dist_count_disk`, in the same change that adds or removes the "
                    + "distribution -- and the prose, which is the check's whole point.",
                ),
            )
        )
    #  The prose says the count two ways. 11-repo-layout.md section 1.2's heading is a TOTAL
    #  ("the fourteen distributions"); :2690 and glossary.md:653 are the first-party release
    #  manifest's count, "the thirteen first-party distributions OTHER THAN `omniweave-core`",
    #  which is the total minus one. A count in neither form is a document that disagrees with the
    #  register, whichever of the two is wrong.
    off = sorted(said for said in spelled if said not in {prose, prose - 1})
    if off:
        findings.append(
            Finding(
                f"a document spells a distribution count of {off}; the recorded prose counts are "
                f"{prose} (total) and {prose - 1} (excluding core).",
                (
                    FAIL_INDENT
                    + "fix: the prose, or the recorded counts if a distribution landed or left.",
                ),
            )
        )
    if prose != disk:
        findings.append(
            Finding(
                f"the prose count {prose} and the workspace's {disk} disagree.",
                (
                    FAIL_INDENT
                    + "section 8.6 wrote this check for exactly this: a distribution landed or "
                    + "left and the prose did not follow. Amend the prose under `plan_lint "
                    + "--bless`, or `dist_count_prose` if the prose is the half that is right.",
                ),
            )
        )
    findings.extend(_d2_membership(members))
    return report, findings


def _d2_membership(members: tuple[tuple[str, bool], ...]) -> list[Finding]:
    """Every member in exactly one of section 1.2's two tables, on the side its own key claims.

    The count alone cannot tell "a fifteenth distribution landed unrecorded" from "an attachment
    landed and was recorded", and reading the first as the second is the error D999 corrected. This
    reads the two tables by name, so each case is its own finding with its own fix.
    """
    findings: list[Finding] = []
    listed, listed_attachments = _section_1_2_tables()
    if not listed:
        return [
            Finding(
                "section 1.2's two tables could not be read, so no membership was checked.",
                (
                    FAIL_INDENT
                    + "fix: the split is the paragraph beginning "
                    + f"{_ATTACHMENT_PARAGRAPH[:40]!r}; a reworded one needs this check reworded "
                    + "with it. A silent empty set here is d0's lesson over again.",
                ),
            )
        ]
    for name, attachment in members:
        where = listed_attachments if attachment else listed
        other = listed if attachment else listed_attachments
        side = "second (attachments)" if attachment else "first (distributions)"
        if name in where:
            continue
        said = f"and section 1.2's {'first' if attachment else 'second'} table lists it"
        findings.append(
            Finding(
                f"`{name}` belongs in section 1.2's {side} table and is not there"
                + (f", {said}" if name in other else ""),
                (
                    FAIL_INDENT
                    + "fix: the table, or `[tool.omniweave] attachment` in the member's own "
                    + "pyproject.toml -- the key is what decides which table it belongs in.",
                ),
            )
        )
    #  The FIRST table only. Section 1.2's second table is a schedule as much as a roster -- "these
    #  five publish later than the fourteen", and four of the five have no directory yet -- so an
    #  attachment row with nothing on disk is the document being ahead, which is its job. A
    #  DISTRIBUTION row with nothing on disk is the fourteen disagreeing with the fourteen.
    strays = sorted(listed - {name for name, _a in members})
    if strays:
        findings.append(
            Finding(
                f"section 1.2's first table lists {strays}, which no "
                "`packages/*/pyproject.toml` provides.",
                (
                    FAIL_INDENT
                    + "fix: the table, if the distribution was dropped; or move the row to the "
                    + "second table, if it became an attachment. A scheduled attachment belongs "
                    + "there and is not a finding.",
                ),
            )
        )
    return findings


def _d2_config_keys() -> tuple[list[str], list[Finding]]:
    """The config keys, in the direction that is decidable.

    NOT "every `[section] key` in prose resolves". That spelling is shared by a config key, a
    DriverCard field and a policy block, so the prose form conflates three registers: 73 of 134
    matches over this corpus are card fields like `[capability.acquire] schemes`. The decidable
    direction is the register's own -- every key `tools/config_axes.toml` names appears in a
    document -- and G18 owns the other one, the override map against `omniweave.toml.example`.
    """
    axes = tomllib.loads((REPO / "tools" / "config_axes.toml").read_text(encoding="utf-8"))
    report: list[str] = []
    findings: list[Finding] = []
    keys = {
        *axes["env"],
        *axes["semantic"]["keys"],
        *axes["operational"]["keys"],
    }
    corpus = "\n".join(one.read_text(encoding="utf-8") for one in walk_documents())
    unnamed = sorted(
        one
        for one in keys
        if not any(form in corpus for form in _key_spellings(str(one)))
        and one not in D2_UNDOCUMENTED_KEYS
    )
    report.append(
        f"  clause (d2) config keys: {len(keys)} in the register, "
        f"{len(D2_UNDOCUMENTED_KEYS)} declared undocumented"
    )
    if unnamed:
        findings.append(
            Finding(
                f"{len(unnamed)} config key(s) no document names: {unnamed[:8]}",
                (
                    FAIL_INDENT
                    + "the other direction is G18's (the override map against "
                    + "omniweave.toml.example); this one is the document side.",
                ),
            )
        )
    return report, findings


def check_clause_d2() -> tuple[list[str], list[Finding]]:
    """d2, family by family. Six resolve hard, two ratchet, and one reports a prose defect.

    The split is measured, not chosen. `G<n>`, the nine invariant families, the `[[job_assertion]]`
    names, the register paths, the `OMNIWEAVE_*` overrides and the config keys all resolve against
    their own registers today -- the invariant families at 0 unresolved over 1,438 occurrences,
    against the register D992 committed. `ow <group> <verb>` and `OW-*` do not, because the plan
    names 146 verb spellings against `ACTIONS`' 51 and 291 codes against `codes.toml`'s 193, and
    the ceilings beside G27's row say why that is a ratchet and not an exception list.
    """
    hard, verb_gap, code_gap, findings = _d2_scan()
    report = [
        "  clause (d2) hard: "
        + ", ".join(f"{name} {count}" for name, count in sorted(hard.items()))
    ]
    for lines, found in (
        _d2_ratchets(verb_gap, code_gap),
        _d2_distributions(),
        _d2_config_keys(),
    ):
        report.extend(lines)
        findings.extend(found)
    return report, findings


def _key_spellings(key: str) -> tuple[str, ...]:
    """How a document writes a config key: dotted, or `[section] leaf`."""
    if "." not in key:
        return (key,)
    section, _, leaf = key.rpartition(".")
    return (key, f"[{section}] {leaf}")


def check_clause_d3() -> tuple[list[str], list[Finding]]:
    """d3: every relative link resolves to a file, and every section reference names a heading.

    The section check is a PREFIX test and that is not a loosening. 08-runtime.md numbers its
    headings `### 1.1` under a `## Part 1` title and has no `## 1` at all, so a reference to
    section 1 of it names the section-1 family rather than one heading; the same is true of
    05-ingest-and-routing.md. An equality test reports four findings over this corpus and every one
    of them is a correct reference.
    """
    findings: list[Finding] = []
    links = 0
    refs = 0
    headings: dict[Path, set[str]] = {}

    def numbers(path: Path) -> set[str]:
        if path not in headings:
            headings[path] = (
                set(_HEADING_NUMBER.findall(path.read_text(encoding="utf-8")))
                if path.is_file()
                else set()
            )
        return headings[path]

    for document in walk_documents():
        text = document.read_text(encoding="utf-8")
        where = _where(document)
        for matched in _LINK.finditer(text):
            target = matched.group(1)
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            links += 1
            if not (document.parent / target).exists():
                findings.append(
                    Finding(
                        f"{where}:{text[: matched.start()].count(chr(10)) + 1} links to {target}, "
                        "which does not exist."
                    )
                )
        for matched in _SECTION_REF.finditer(text):
            target = document.parent / matched.group("target")
            section = matched.group("section")
            refs += 1
            have = numbers(target)
            if not any(one == section or one.startswith(section + ".") for one in have):
                findings.append(
                    Finding(
                        f"{where}:{text[: matched.start()].count(chr(10)) + 1} cites "
                        f"{matched.group('target')} section {section}, which has no heading."
                    )
                )
    return [f"  clause (d3) {links} relative link(s), {refs} section cross-reference(s)"], findings


def check_clause_d4(checked: int) -> tuple[list[str], list[Finding]]:
    """d4: the number of symbols checked, as the Counter `docs_symbols_checked`, ratchet-gated.

    Section 8.6: "a document that stops naming things to make the gate quiet" is the failure, and
    "`docs_symbols_checked` ratchets, so removing a symbol from a document to silence d1 lowers a
    number a gate watches". The ratchet IS `symbol_floor` -- one number, in one place, read by d0
    and by d4 -- because a second ceiling for the same count would be the second home INV-21
    forbids. d0 asks whether the scan matched enough to be meaningful; d4 asks whether the corpus
    stopped naming things. Same number, two questions.
    """
    floor = _register_value("symbol_floor")
    row = next(
        (
            one
            for one in _table(
                tomllib.loads((REPO / "eval" / "counters.toml").read_text(encoding="utf-8")),
                "counter",
            )
            if str(one.get("id")) == COUNTER
        ),
        None,
    )
    findings: list[Finding] = []
    if row is None:
        findings.append(
            Finding(
                f"eval/counters.toml holds no `{COUNTER}` row.",
                (
                    FAIL_INDENT
                    + "section 8.6 emits the count as that Counter with ratchet gating; a count "
                    + "nothing records is a count nothing watches.",
                ),
            )
        )
    line = f"  clause (d4) {COUNTER} = {checked}, ratcheted against symbol_floor {floor}"
    return [line], findings


#  ---------------------------------------------------------------------------------------------
#  Clause (c), read from the register rather than restated


def clause_c_state() -> tuple[list[str], list[Finding]]:
    register = tomllib.loads(GATES.read_text(encoding="utf-8"))
    rows = register.get("gate", [])
    row = next(
        (one for one in rows if isinstance(one, dict) and str(one.get("id")) == "G27"),
        None,
    )
    if row is None:
        return [], [Finding("tools/gates.toml holds no G27 row.")]
    clauses = row.get("clause", [])
    clause = next(
        (one for one in clauses if isinstance(one, dict) and str(one.get("id")) == "c"),
        None,
    )
    if clause is None:
        return [], [Finding("G27's row holds no clause (c); ADR-1 decision 6 requires it.")]
    if clause.get("enabled"):
        return [], [
            Finding(
                "clause (c) is enabled in the register and this script does not run it.",
                (
                    FAIL_INDENT
                    + "ADR-1 decision 6's four turn-on conditions have to hold and the clause has "
                    + "to be implemented in the same change that enables it.",
                ),
            )
        ]
    return [
        f"  clause (c)  registered and OFF, blocked_by {clause.get('blocked_by', '?')}: "
        f"{clause.get('asserts')}"
    ], []


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        sys.stdout.write("usage: tools/gate_docs.py\n")
        return 2
    report: list[str] = []
    findings: list[Finding] = []
    for check in (
        check_clause_a,
        check_clause_a2,
        check_clause_a3,
        clause_c_state,
        check_clause_d1,
        check_clause_d2,
        check_clause_d3,
    ):
        lines, found = check()
        report.extend(lines)
        findings.extend(found)
    #  d4 reports the count d1 checked, so it reads it back out of d1's own report line rather
    #  than walking the corpus a second time. Two walks would be two numbers.
    counted = 0
    for line in report:
        if line.startswith("  clause (d0)"):
            counted = int(line.split()[2])
    lines, found = check_clause_d4(counted)
    report.extend(lines)
    findings.extend(found)
    report.append(
        "  clause (b)  NOT IN THIS SCRIPT: tools/gate_migrations.py carries it (16-roadmap.md:453)"
    )
    for line in report:
        sys.stdout.write(line + "\n")
    if findings:
        for finding in findings:
            sys.stdout.write(finding.render() + "\n")
        sys.stdout.write(f"{PREFIX} FAILED: {len(findings)} finding(s)\n")
        return 1
    sys.stdout.write(
        f"{PREFIX} ok  clauses (a), (a2), (a3) and (d) hold over {len(documents())} document(s) "
        f"and {len(walk_documents())} in d's walk; (c) registered and off\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
