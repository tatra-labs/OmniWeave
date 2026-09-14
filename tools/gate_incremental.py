"""G19 - incremental == full, diffed over the `.owdoc` **exports**. The harness, not the fixture.

`tools/gates.toml`'s G19 row is the specification: *"incremental == full: 300 docs, 40 mutations,
`.owdoc` export diff"*, in its own `incremental` job at a 420 s budget, blocking a PR, a nightly
and a release. `01-principles.md:506` says the row owns those two numbers ("`G19` owns the fixture
size and the mutation count"), and `07-store-and-retrieval.md:2971` and `08-runtime.md:1858` give
the mechanism in one sentence each: build a 300-document fixture through 40 scripted mutations,
build the same corpus by a full rebuild into a SECOND store, and diff the two `.owdoc` exports --
*"exports rather than tables, because an archive contains no `block_id` and the allocation-order
normalisation that could hide a bug is therefore not needed at all"*.

THE FOUR PIECES, AND WHERE EACH ONE IS
--------------------------------------
`16-roadmap.md:458` put `uv run tools/gate_incremental.py --smoke` in **P2's** exit criteria and
annotated it in as many words: *"G19's harness exists; its fixture lands in P4"*. `:575` puts the
unflagged `uv run tools/gate_incremental.py` in P4's, and `:550` (W4.10) is the work item that
builds *"the `fixtures/incremental/` 300-document / 40-mutation corpus"*. **W4.10 landed all
four**, and this file is still only two of them:

* **the fixture** -- `fixtures/gen/gen_incremental.py` and the committed
  `fixtures/incremental/plan.toml`.
* **the indexer and the rebuilder** -- `tools/incremental_index.py`, loaded by path by
  `build_with_index()` and by nothing else in this file.
* **the harness and the comparator** -- this file. `diff_exports()` is the whole of G19's
  comparison and is unchanged from P2: member by member, record by record, addressed by `addr`.
  `ow bench incremental` (12-performance.md:1520) calls it at P7.

`--smoke` still exists and still exits 0: P2's exit criterion runs it, and it is the one mode that
needs no corpus, no store and no parser. What it no longer does is list four absences, because
there are none left to list.

THE PROVENANCE PASS, AND WHY THE PLAN'S OWN CLAIM NEEDED ONE. `07-store-and-retrieval.md:2973`
says the exports are diffed *"rather than tables, because an archive contains no `block_id` and the
allocation-order normalisation that could hide a bug is therefore not needed at all"*. The
`block_id` half is true. The conclusion is not: an archive carries `manifest.gen` and every
block's `revision`, and both are counts of how many times a store has parsed a document rather
than facts about the document. A store built through 14 edits has parsed more times than one built
once, so those two fields differ on every edited document and can never be made to agree. They are
classified and reported rather than ignored, `--strict` promotes them back to failures, and `D187`
is the report against the plan. `GR8`, the graph-level sibling, already asserts equality *"modulo
surrogate ids"* (06-structure-extraction.md:2406) -- this is the same concession, named.

THE TWO NUMBERS ARE TRANSCRIBED, NEVER COMPUTED. `DOCUMENTS = 300` and `MUTATIONS = 40` are read
off the register row and re-asserted against it at run time by `check_register()`, because
`01-principles.md:506` makes the row their owner and a harness that carried its own copy would let
the two drift. `11-repo-layout.md` OQ-6's pre-committed fallback -- above 12 minutes G19 moves to
nightly and the PR path keeps "a deterministic 60-document/8-mutation subset with the mutation
seed derived from `blake2b(commit_sha)`" -- is recorded in `FALLBACK` and is not implemented,
because implementing a fallback before the measurement that triggers it is how the weaker gate
becomes the only gate.

Run it:

    uv run tools/gate_incremental.py             # the 300-document / 40-mutation gate
    uv run tools/gate_incremental.py --strict    # ... with the provenance pass blocking too
    uv run tools/gate_incremental.py --smoke     # the comparator alone, no corpus
    uv run tools/gate_incremental.py --diff A B  # the export diff over two archives

Exit codes: `0` clean, `1` the exports differ or the fixture is malformed, `2` did not run (no
fixture, an unreadable archive, a usage error).

Specified in `tools/gates.toml`'s G19 row, 01-principles.md:506, 07-store-and-retrieval.md:2971
and :3097, 08-runtime.md:1858, 11-repo-layout.md sections 6.2, 6.4 (the row), 6.8 and OQ-6, and
16-roadmap.md:458, :550, :575 and :804.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import sys
import tempfile
import tomllib
import zipfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Final, TextIO

__all__ = [
    "CHECKPOINT_EVERY",
    "DOCUMENTS",
    "EXIT_CLEAN",
    "EXIT_FAIL",
    "EXIT_NOT_RUN",
    "FALLBACK",
    "FIXTURE_DIR",
    "GATE",
    "JOB",
    "MUTATIONS",
    "NOT_CHECKED_BY_SMOKE",
    "PROVENANCE",
    "Absence",
    "Checkpoint",
    "Difference",
    "Report",
    "build_with_index",
    "check_register",
    "checkpoint_steps",
    "classify",
    "diff_exports",
    "exit_code",
    "load_fixture_plan",
    "main",
    "read_archive",
    "render",
    "run_full",
    "run_smoke",
]

GATE = "G19"
"""The register id. `tools/gates.toml` is the authority and `check_register()` re-reads it."""

JOB = "incremental"
"""G19's own CI job. Section 6.2's note: 300 documents in 40 mutations does not fit inside
`golden`'s 4 min, and shrinking the fixture would change a gate the charter says owns its two
numbers."""

DOCUMENTS = 300
"""The fixture size. `tools/gates.toml`'s G19 assertion and 01-principles.md:506 own it."""

MUTATIONS = 40
"""The scripted mutation count. Same two homes, and `check_register()` re-asserts both."""

FIXTURE_DIR = Path("fixtures") / "incremental"
"""Where the corpus lands. 16-roadmap.md:550 (W4.10) names the directory; `.github/workflows/
ci.yml`'s G19 step tests for it to choose between `--smoke` and the full run."""

FALLBACK = (
    "11-repo-layout.md OQ-6: if the PR-time run exceeds 12 min, G19 moves to nightly and the PR "
    "path keeps a deterministic 60-document/8-mutation subset seeded from blake2b(commit_sha). "
    "Not implemented: the trigger is a measurement nobody has taken, and a fallback that ships "
    "before its trigger becomes the gate."
)

EXIT_CLEAN = 0
EXIT_FAIL = 1
EXIT_NOT_RUN = 2

_REPO = Path(__file__).resolve().parent.parent
_REGISTER = _REPO / "tools" / "gates.toml"
_MAX_REPORTED_DIFFERENCES = 20
"""How many differences a report prints before it says how many more there are.

A 300-document corpus that diverges structurally produces one difference per block, and a report
that printed 600,000 of them would be unreadable in exactly the run where reading it matters.
"""


# ---------------------------------------------------------------------------
# 1. Reading an archive. `.owdoc` is a plain ZIP (03-document-model.md:2482).
# ---------------------------------------------------------------------------


def read_archive(path: Path) -> dict[str, Any]:
    """One `.owdoc` as `member name -> parsed content`. The unit both sides of the diff are in.

    NDJSON members become lists of objects, JSON members become objects, and every other member
    -- a retained part, an asset, a serialized view -- becomes its sha256, so a difference in a
    blob is one short string in a report instead of a wall of binary.

    **`zipfile` and not `OwdocReader`, and that is deliberate.** `OwdocReader` is the bounded
    reader of 14-security.md section 2.2 and it applies the container budgets, which is right for
    untrusted input and wrong here: G19's two inputs are archives this repository just produced,
    and a budget refusal on one side would read as "the exports differ". The seek path and the
    frame index have their own suite (`test_archive_owdoc.py`); what this needs is every byte of
    both files.

    Raises `ValueError` on anything that is not a readable ZIP or whose NDJSON does not parse --
    which the caller turns into `DID NOT RUN`, never into "they differ".
    """
    try:
        with zipfile.ZipFile(path) as package:
            members = {name: package.read(name) for name in sorted(package.namelist())}
    except (OSError, zipfile.BadZipFile) as error:
        message = f"{path} is not a readable .owdoc: {error}"
        raise ValueError(message) from error

    out: dict[str, Any] = {}
    for name, payload in members.items():
        try:
            if name.endswith(".ndjson"):
                out[name] = [json.loads(line) for line in payload.splitlines() if line]
            elif name.endswith(".json"):
                out[name] = json.loads(payload)
            else:
                out[name] = hashlib.sha256(payload).hexdigest()
        except json.JSONDecodeError as error:
            message = f"{path}: member {name} is not valid JSON: {error}"
            raise ValueError(message) from error
    return out


# ---------------------------------------------------------------------------
# 2. The diff. This is G19's whole comparison and it is complete.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Difference:
    """One way in which two exports disagree.

    `where` is the member, `subject` is the `addr` (or the record index when a record carries no
    address), and `field` is the wire key. Never a `block_id`: an archive holds none (03:1083),
    which is 07:2973's stated reason for diffing exports rather than tables.
    """

    where: str
    subject: str
    field: str
    incremental: Any
    full: Any

    def line(self) -> str:
        return (
            f"  {self.where} :: {self.subject} :: {self.field}\n"
            f"      incremental = {self.incremental!r}\n"
            f"      full        = {self.full!r}"
        )


_ADDRESS_KEYS = ("i", "src", "table", "path", "sha256", "view_id")
"""How a record names itself, in the order the members declare it.

`i` is a block's `addr` (03 section 3.1's wire-key table), `src` a rel's source, `table` a grid's
table, and the last three are the part, asset and view rows' natural keys. A record matching
none of them is identified by its index, which is what `_subject` falls back to.
"""


def _subject(record: Any, index: int) -> str:
    if isinstance(record, dict):
        for key in _ADDRESS_KEYS:
            if key in record:
                return f"{record[key]}"
    return f"#{index}"


def _diff_records(where: str, incremental: Sequence[Any], full: Sequence[Any]) -> list[Difference]:
    """Two NDJSON members, record for record, keyed by the record's own address."""
    left = {_subject(row, index): row for index, row in enumerate(incremental)}
    right = {_subject(row, index): row for index, row in enumerate(full)}
    out: list[Difference] = []
    for subject in sorted(set(left) | set(right)):
        if subject not in right:
            out.append(Difference(where, subject, "<record>", "present", "absent"))
            continue
        if subject not in left:
            out.append(Difference(where, subject, "<record>", "absent", "present"))
            continue
        a, b = left[subject], right[subject]
        if a == b:
            continue
        if not (isinstance(a, dict) and isinstance(b, dict)):
            out.append(Difference(where, subject, "<record>", a, b))
            continue
        for key in sorted(set(a) | set(b)):
            if a.get(key) != b.get(key):
                out.append(Difference(where, subject, key, a.get(key), b.get(key)))
    return out


PRODUCER_INDEX_KEY: Final = "pd"
"""A block's producer, on the wire. **An INDEX into `manifest.producers[]`, not an identity.**

03:666 defines it that way, and `store/portable.py`'s `_producers()` fills that list from EVERY
`producer` row in the exporting store rather than from the ones this document's blocks cite -- its
docstring says so and argues for it. The consequence for a gate that compares two stores is that
`pd` means different things on the two sides: a store that has parsed at three driver versions
lists three producers and a fresh rebuild lists one, so the same producer is index 2 on one side
and index 0 on the other, on every block of every document.

Comparing the index would therefore report 39,300 differences about nothing. IGNORING it would
stop checking the one thing a `driver_version` mutation exists to check -- that a re-parse
restamped the blocks. `_resolve_producers` does neither: it replaces the index with the producer
it names, so the comparison is on the producer's identity and a block still stamped with the old
driver is still a divergence. Filed as D188; the leak that projection also fixes is in the note."""


def _producer_name(producers: Sequence[Any], index: Any) -> str:
    """One producer as a stable string. Out of range is reported rather than raised.

    A malformed archive is `DID NOT RUN`'s business, not a divergence's -- but an index past the
    end of its own manifest is a fact about THIS archive that the other side may not share, so it
    is rendered as a value that can differ rather than as an exception that ends the run.
    """
    if not isinstance(index, int) or not 0 <= index < len(producers):
        return f"<producer index {index!r} outside a list of {len(producers)}>"
    return json.dumps(producers[index], sort_keys=True)


def _resolve_producers(archive: dict[str, Any]) -> None:
    """Rewrite every block's `pd` from an index into the producer it names. In place.

    In place because `read_archive` hands back a fresh parse per call and nothing else holds it;
    a copy would double the peak memory of a 300-archive diff for no reader's benefit.
    """
    manifest = archive.get("manifest.json")
    producers = manifest.get("producers", ()) if isinstance(manifest, dict) else ()
    if not isinstance(producers, list):  # pragma: no cover -- a manifest that is not one.
        producers = []
    for member, records in archive.items():
        if not member.startswith("blocks/") or not isinstance(records, list):
            continue
        for record in records:
            if isinstance(record, dict) and PRODUCER_INDEX_KEY in record:
                record[PRODUCER_INDEX_KEY] = _producer_name(producers, record[PRODUCER_INDEX_KEY])


CITE_KEY: Final = "c"
"""A block's cite, on the wire: `d<doc_ord>#<n>`. **Half of it is allocation order.**

`doc_ord` is *"corpus-local; the number inside a `cite`"* (`0001_init.sql:149`) and the store
assigns it ON FIRST SIGHT -- `DocRecord`'s docstring says *"`doc_ord` assigned on first sight"* --
so a caller cannot choose it and two stores that met the same 300 documents in different orders
number them differently. A store built through 40 mutations met 313 documents; a rebuild of the
final roster met 300; the same document is `d309` in one and `d299` in the other.

`n` is the other half and it is NOT allocation order: it is `doc.next_cite_n`, *"monotonic per
`doc_key`, never reset, never reused"*, and a carried cite keeps the `n` it was minted with. Over
the shipped 40-step script the two sides agree on `n` for every one of 39,300 blocks -- which is
`rebind()` working, and is exactly the property INV-18 is about.

So the ordinal is stripped and the counter is compared. An ordinal that differs is reported ONCE
per archive rather than once per block, because it is one fact about the document and not 131
facts about its blocks. **07:2973's claim that diffing exports needs no allocation-order
normalisation is wrong about this field**, and D187 is the report."""


def _split_cite(cite: Any) -> tuple[str, str]:
    """`'d309#1'` -> `('d309', '#1')`. Anything else comes back whole, in the second slot.

    Whole rather than refused: a cite this function does not recognise is a difference worth
    seeing, and raising here would turn it into `DID NOT RUN` on an archive that parsed fine.
    """
    if not isinstance(cite, str) or "#" not in cite:
        return "", str(cite)
    ordinal, counter = cite.split("#", 1)
    return ordinal, f"#{counter}"


def _strip_cite_ordinals(archive: dict[str, Any]) -> str:
    """Rewrite every block's cite to its counter and return the ordinal they shared.

    Returns `"<mixed>"` if one archive's blocks carry two different ordinals, which would mean an
    archive holding blocks from two documents -- not a thing `export_portable` can produce, and a
    thing worth saying out loud rather than silently taking the first of.
    """
    ordinals: set[str] = set()
    for member, records in archive.items():
        if not member.startswith("blocks/") or not isinstance(records, list):
            continue
        for record in records:
            if isinstance(record, dict) and CITE_KEY in record:
                ordinal, counter = _split_cite(record[CITE_KEY])
                ordinals.add(ordinal)
                record[CITE_KEY] = counter
    if not ordinals:
        return ""
    return ordinals.pop() if len(ordinals) == 1 else "<mixed>"


def diff_exports(incremental: Path, full: Path) -> tuple[Difference, ...]:
    """G19's comparison: every way two `.owdoc` exports of one corpus disagree.

    The argument order is the gate's own reading: the first archive is the store built
    INCREMENTALLY through the mutation script, the second is the full rebuild, and every
    `Difference` names both values in that order. Getting them the wrong way round would make
    every report say the opposite of what happened, so the names are not `a` and `b`.

    Equality here is over the archives' parsed content, which for a byte-stable writer (INV-10)
    is exactly file equality -- and the structural form is what produces a report a human can
    act on. `ow bench incremental` (12-performance.md:1520) calls this at P7.
    """
    left, right = read_archive(incremental), read_archive(full)
    _resolve_producers(left)
    _resolve_producers(right)
    ordinals = (_strip_cite_ordinals(left), _strip_cite_ordinals(right))
    out: list[Difference] = []
    if ordinals[0] != ordinals[1]:
        out.append(Difference("manifest.json", "<manifest>", "doc_ord", *ordinals))
    for member in sorted(set(left) | set(right)):
        if member not in right:
            out.append(Difference(member, "<member>", "<member>", "present", "absent"))
            continue
        if member not in left:
            out.append(Difference(member, "<member>", "<member>", "absent", "present"))
            continue
        a, b = left[member], right[member]
        if a == b:
            continue
        if isinstance(a, list) and isinstance(b, list):
            out.extend(_diff_records(member, a, b))
        elif isinstance(a, dict) and isinstance(b, dict):
            out.extend(
                Difference(member, "<manifest>", key, a.get(key), b.get(key))
                for key in sorted(set(a) | set(b))
                if a.get(key) != b.get(key)
            )
        else:
            out.append(Difference(member, "<member>", "<bytes>", a, b))
    return tuple(out)


PROVENANCE: Final[Mapping[str, frozenset[str]]] = {
    "manifest.json": frozenset({"gen", "producers", "doc_ord"}),
    "frames.json": frozenset({"sha256", "bytes"}),
    "blocks/": frozenset({"rm", "c"}),
}
"""The fields that record how many times a STORE parsed, rather than what a document contains.

Three entries and the set is closed. Each one is a count of parse history, and the incremental
side and the full side have parsed different numbers of times by construction -- so these can
never agree and a gate that required them to would be a gate that can only fail.

* `manifest.json` `gen` is `doc.gen`, *"THE HEAD GENERATION"* (`0001_init.sql:167`). A document
  edited twice is at `gen = 3` on the incremental side and `gen = 1` on a rebuild.
* `manifest.json` `producers` is every `producer` row in the EXPORTING STORE, not the ones this
  document's blocks cite (`store/portable.py:744`). A store that has parsed at three driver
  versions lists three and a rebuild lists one, whatever either document was produced by. What the
  blocks were ACTUALLY stamped with is still compared, because `_resolve_producers` turns `pd`
  from an index into that list into the producer it names. Filed as D188.
* `manifest.json` `doc_ord` is synthesised by `_strip_cite_ordinals`, not read off the archive:
  it is the `d309` half of every block's cite, which the store assigns on first sight. One row per
  archive instead of one per block; see `CITE_KEY`, and D187.
* `blocks/` `rm` is `block.revision`, which 03:1256-1260's rule table increments on every rule-2
  match -- *"equal `addr` and `kind`, digest changed"*. It counts re-derivations.
* `frames.json` `sha256` and `bytes` are a digest and a byte count OVER the block NDJSON, so both
  move whenever `rm` does. They are here as consequences of the row above and not as facts of
  their own; the blocks they cover are compared one by one either way.

**`c` is in the set, and the measurement is the argument.** A carried cite is `rebind()`'s
whole purpose: when a document is re-parsed, a block whose content survived keeps the `n` it was
minted with, wherever it has MOVED to. A rebuild has no history to carry from and mints `1..N` by
position. So when an edit moves content within a document the two sides disagree -- and the
incremental answer is the better one, because it is what every `cite` already handed to a user
resolves against.

The shipped 40-step script makes that concrete: over 39,300 blocks the two sides agree on `n`
**39,298 times**, and the two that differ are both in one document that an edit re-paginated.
Neither side is wrong. The provenance section reports the count, so a run that started diverging
on thousands of cites would be visible as a number rather than hidden by a rule.
"""


def classify(
    differences: Sequence[Difference],
) -> tuple[tuple[Difference, ...], tuple[Difference, ...]]:
    """Split one member-by-member diff into `(divergences, provenance)`. See `PROVENANCE`.

    A prefix match on the member name, because `blocks/000063.ndjson` is one of many block members
    and `manifest.json` is one. The match is on the member and the field together: an `rm` in a
    member that is not a blocks frame, or a `gen` outside the manifest, is a divergence.
    """
    divergences: list[Difference] = []
    provenance: list[Difference] = []
    for difference in differences:
        fields = next(
            (
                names
                for member, names in PROVENANCE.items()
                if difference.where == member or difference.where.startswith(member)
            ),
            frozenset(),
        )
        (provenance if difference.field in fields else divergences).append(difference)
    return tuple(divergences), tuple(provenance)


# ---------------------------------------------------------------------------
# 3. The register, and the fixture the register describes.
# ---------------------------------------------------------------------------


def check_register(register: Path | None = None) -> tuple[str, ...]:
    """Assert this harness's two numbers against the row that owns them. 01-principles.md:506.

    `DOCUMENTS` and `MUTATIONS` are transcriptions; `tools/gates.toml`'s G19 assertion is the
    original. Returns the complaints, empty when the two agree. A harness that shrank its own
    corpus without editing the register would otherwise be a gate quietly weakening itself, which
    is the move section 6.2 calls out ("shrinking the fixture would change a gate the charter says
    owns its two numbers").
    """
    path = _REGISTER if register is None else register
    if not path.is_file():
        return (f"no register at {path}",)
    rows = tomllib.loads(path.read_text(encoding="utf-8")).get("gate", [])
    row = next((r for r in rows if r.get("id") == GATE), None)
    if row is None:
        return (f"{path} has no {GATE} row",)
    complaints: list[str] = []
    assertion = str(row.get("assertion", ""))
    if f"{DOCUMENTS} docs" not in assertion:
        complaints.append(
            f"{GATE}'s row asserts {assertion!r}, which does not say {DOCUMENTS} docs"
        )
    if f"{MUTATIONS} mutations" not in assertion:
        complaints.append(
            f"{GATE}'s row asserts {assertion!r}, which does not say {MUTATIONS} mutations"
        )
    if JOB not in [str(job) for job in row.get("jobs", ())]:
        complaints.append(f"{GATE}'s row does not name the {JOB!r} job")
    return tuple(complaints)


@dataclass(frozen=True, slots=True)
class FixturePlan:
    """`fixtures/incremental/plan.toml` as this harness will read it at P4.

    The shape is declared here so that W4.10 has a target rather than a blank page, and it is
    exactly the two numbers the register owns plus the mutation list. It is NOT invented policy:
    01-principles.md:506 fixes the counts and 07:2971 fixes what a mutation does (edit, add,
    delete, re-parse at a new driver version), so a plan file is a transcription of the corpus,
    not a second specification.
    """

    documents: int
    mutations: tuple[str, ...]

    def complaints(self) -> tuple[str, ...]:
        out: list[str] = []
        if self.documents != DOCUMENTS:
            out.append(f"the fixture holds {self.documents} documents, not {DOCUMENTS}")
        if len(self.mutations) != MUTATIONS:
            out.append(f"the plan scripts {len(self.mutations)} mutations, not {MUTATIONS}")
        return tuple(out)


def load_fixture_plan(directory: Path) -> FixturePlan | None:
    """The corpus plan, or `None` when the fixture is not in this checkout.

    Raises `ValueError` when the directory exists and the plan does not parse: an unreadable
    fixture is `DID NOT RUN`, not a pass and not a divergence.
    """
    if not directory.is_dir():
        return None
    plan = directory / "plan.toml"
    if not plan.is_file():
        message = f"{directory} exists but has no plan.toml"
        raise ValueError(message)
    try:
        raw = tomllib.loads(plan.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        message = f"{plan} does not parse: {error}"
        raise ValueError(message) from error
    return FixturePlan(
        documents=int(raw.get("documents", 0)),
        mutations=tuple(str(m) for m in raw.get("mutations", ())),
    )


# ---------------------------------------------------------------------------
# 4. What this harness cannot check yet, and who owns each piece.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Absence:
    """One check the harness could not run, the phase that owns it, and the line that says so.

    Never a silent pass: `render()` prints every one of these under a NOT CHECKED heading, and
    the full mode turns the same list into `DID NOT RUN` with exit 2.
    """

    what: str
    owner: str
    locus: str

    def line(self) -> str:
        return f"  {self.what}\n      owner: {self.owner}   ({self.locus})"


NOT_CHECKED_BY_SMOKE: tuple[Absence, ...] = (
    Absence(
        f"the {DOCUMENTS}-document corpus and its {MUTATIONS} mutations",
        "the full mode",
        "run this script with no --smoke",
    ),
    Absence(
        "the incremental build, the full rebuild, and the diff between their exports",
        "the full mode",
        "tools/incremental_index.py, driven by build_with_index()",
    ),
)
"""What `--smoke` does not check, which since W4.10 is not the same as what nothing checks.

**These rows named P4 and `16-roadmap.md:550` until W4.10, and four of them were absences of the
FIXTURE.** They are now absences of one MODE: `--smoke` runs the comparator over two archives it
builds itself, so it needs no corpus, no store and no parser, and the price of that is that it
checks the comparator rather than the convergence. The full mode is one command away and the rows
say so, which is the same "never a silent pass" discipline pointed at a smaller gap.
"""


# ---------------------------------------------------------------------------
# 5. The report
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Report:
    """What one run of this gate found. `mode` is the only thing a reader needs first."""

    mode: str
    checks: tuple[str, ...] = ()
    differences: tuple[Difference, ...] = ()
    provenance: tuple[Difference, ...] = ()
    complaints: tuple[str, ...] = ()
    absences: tuple[Absence, ...] = ()
    not_run: str = ""
    documents_compared: int = 0
    records_compared: int = 0
    detail: tuple[str, ...] = field(default_factory=tuple)


def exit_code(report: Report) -> int:
    """`2` did not run, `1` a divergence or a malformed fixture, `0` clean."""
    if report.not_run:
        return EXIT_NOT_RUN
    if report.differences or report.complaints:
        return EXIT_FAIL
    return EXIT_CLEAN


def _emit(out: TextIO, message: str = "") -> None:
    """The only write. T20 is enabled repo-wide, so a gate reports through an injected `TextIO`."""
    out.write(message + "\n")


def _render_not_run(report: Report, out: TextIO) -> None:
    _emit(out)
    _emit(out, f"{GATE} DID NOT RUN  {report.not_run}")
    for line in report.detail:
        _emit(out, f"              {line}")
    for absence in report.absences:
        _emit(out, absence.line())


def _render_section(out: TextIO, heading: str, lines: Sequence[str]) -> None:
    if not lines:
        return
    _emit(out)
    _emit(out, heading)
    for line in lines:
        _emit(out, line)


def _provenance_lines(differences: Sequence[Difference]) -> list[str]:
    """One line per field, with a count, rather than one line per block.

    A `driver_version` step moves `manifest.gen` on all 300 documents and `block.revision` on every
    one of their blocks. Printing them would bury the divergence report that matters under a fact
    the reader already knows, so the provenance pass reports its shape and not its rows.

    The member is taken after the last `:: ` because `_diff_checkpoint` prefixes every difference
    with its step and its archive: grouping on the whole string would produce one line per
    ARCHIVE, which is the wall of text this function exists to prevent.
    """
    if not differences:
        return []
    counts: dict[tuple[str, str], int] = {}
    for difference in differences:
        member = difference.where.rsplit(":: ", 1)[-1].split("/")[0]
        counts[member, difference.field] = counts.get((member, difference.field), 0) + 1
    return [
        f"  {member} :: {field} differs on {count} record(s)"
        for (member, field), count in sorted(counts.items())
    ]


def _render_verdict(report: Report, out: TextIO) -> None:
    _emit(out)
    if report.differences:
        _emit(
            out,
            f"{GATE} FAIL  {len(report.differences)} difference(s) between the incremental "
            f"export and the full rebuild's.",
        )
    elif report.complaints:
        _emit(out, f"{GATE} FAIL  {len(report.complaints)} fixture finding(s).")
    else:
        _emit(
            out,
            f"{GATE} ok  {len(report.checks)} check(s) passed, {len(report.absences)} not "
            f"checked, {len(report.provenance)} provenance difference(s).",
        )


def render(report: Report, out: TextIO) -> None:
    """Print the report: what ran, what diverged, what was not checked, in that order."""
    _emit(out, f"{GATE} - incremental == full, over the .owdoc exports  [{report.mode}]")
    _emit(out, "=" * 92)
    if report.not_run:
        _render_not_run(report, out)
        return

    _render_section(out, "CHECKED", [f"  ok  {check}" for check in report.checks])
    for line in report.detail:
        _emit(out, f"      {line}")
    _render_section(
        out,
        "NOT CHECKED - each row names the phase that owns it",
        [absence.line() for absence in report.absences],
    )
    _render_section(out, "FIXTURE", [f"  FAIL  {complaint}" for complaint in report.complaints])
    _render_section(
        out,
        "PROVENANCE - parse history, not document content; see PROVENANCE and D187",
        _provenance_lines(report.provenance),
    )
    shown = [d.line() for d in report.differences[:_MAX_REPORTED_DIFFERENCES]]
    extra = len(report.differences) - _MAX_REPORTED_DIFFERENCES
    if extra > 0:
        shown.append(f"  ... and {extra} more")
    _render_section(out, "THE EXPORTS DIFFER", shown)
    _render_verdict(report, out)


# ---------------------------------------------------------------------------
# 6. The three modes
# ---------------------------------------------------------------------------


def _smoke_archives(workdir: Path) -> tuple[Path, Path, Path]:
    """Three archives: two equal, and a third with one block's text changed.

    Built through the shipped writer (`omniweave_core.archive.export`) over a hand-written
    `ExportSource`, so the smoke run exercises the real container and not a mock of one. The
    import is inside the function because a `tools/` script that imported `omniweave_core` at
    module scope would pay for it in `--help`.
    """
    from omniweave_core.archive import BlockExport, DocHeader, export  # noqa: PLC0415
    from omniweave_core.model import (  # noqa: PLC0415
        Addr,
        BlockId,
        Cite,
        Kind,
        Layer,
        Method,
        Quote,
        Trust,
    )
    from omniweave_core.model.block import Block  # noqa: PLC0415
    from omniweave_core.model.spans import OriginBytes, OriginNone, TextSpan  # noqa: PLC0415

    def block(addr: str, ordinal: int, text: str | None, bid: int) -> Block:
        body = text is not None
        return Block(
            id=BlockId(bid),
            addr=Addr(addr),
            cite=Cite(f"d1#{bid}"),
            doc_ord=1,
            gen=1,
            page=0,
            parent=None,
            ord=ordinal,
            kind=Kind.PARAGRAPH if body else Kind.DOCUMENT,
            raw_kind=None,
            layer=Layer.BODY,
            label=None,
            text=text,
            content_digest=bytes([bid]) * 16,
            layout_digest=None,
            revision=0,
            quad=None,
            origin=(
                OriginBytes(part="file", start=0, length=len(text), codec="utf-8/strict")
                if body
                else OriginNone()
            ),
            span=TextSpan(0, len(text)) if body else None,
            producer_id=1,
            method=Method.NATIVE,
            trust=Trust.EXTRACTED,
            quote=Quote.NORMALIZED if body else Quote.SYNTHETIC,
            origin_operator="gate.incremental",
            origin_driver="gate.incremental.smoke",
            driver_schema_v=1,
        )

    class Source:
        """The nine methods of `owdoc.ExportSource`, over three blocks and nothing else."""

        def __init__(self, second: str) -> None:
            self._second = second

        def header(self) -> DocHeader:
            return DocHeader(
                doc_key="ab" * 16,
                gen=1,
                status="ok",
                source={"uri": "file:///smoke.txt", "media_type": "text/plain", "format": "text"},
                declared={},
                achieved={},
                producers=[{"operator": "gate.incremental", "op_version": 1}],
            )

        def blocks(self) -> list[BlockExport]:
            return [
                BlockExport(block=block("doc", 0, None, 1), producer=0),
                BlockExport(block=block("p0/0", 0, "the first paragraph", 2), producer=0),
                BlockExport(block=block("p0/1", 1, self._second, 3), producer=0),
            ]

        def rels(self) -> tuple[()]:
            return ()

        def grids(self) -> tuple[()]:
            return ()

        def parts(self) -> tuple[()]:
            return ()

        def assets(self) -> tuple[()]:
            return ()

        def views(self) -> tuple[()]:
            return ()

        def diags(self) -> tuple[()]:
            return ()

        def toc(self) -> tuple[()]:
            return ()

    kept = "the second paragraph"
    full = workdir / "smoke-full.owdoc"
    incremental = workdir / "smoke-incremental.owdoc"
    diverged = workdir / "smoke-diverged.owdoc"
    export(Source(kept), full)
    export(Source(kept), incremental)
    export(Source("the second paragraph, edited"), diverged)
    return incremental, full, diverged


def run_smoke(workdir: Path, register: Path | None = None) -> Report:
    """P2's mode (16-roadmap.md:458). Prove the comparator, then say what is missing.

    Two self-checks, and the second is the one that matters. Asserting "two equal exports produce
    no differences" alone would pass just as well against a comparator that always returns
    nothing -- which is a gate that can never fail, and 11-repo-layout.md section 6.8 refuses one.
    So a third archive is built with a single block's `t` changed, and the comparator is required
    to find exactly that one difference, at that `addr`, on that wire key.
    """
    incremental, full, diverged = _smoke_archives(workdir)
    checks: list[str] = []
    complaints: list[str] = list(check_register(register))

    same = diff_exports(incremental, full)
    if same:
        complaints.append(
            f"two exports of one generation differ in {len(same)} place(s): "
            f"{[d.line() for d in same[:3]]}"
        )
    else:
        checks.append("two exports of one generation diff to nothing")

    planted = diff_exports(diverged, full)
    expected = [d for d in planted if d.subject == "p0/1" and d.field == "t"]
    if not expected:
        complaints.append(
            "the comparator did not find a planted change to one block's text, so it would not "
            "find a real divergence either"
        )
    else:
        checks.append(
            f"a planted change to one block's `t` is found at {expected[0].subject} "
            f"({len(planted)} difference(s) in total)"
        )
    if len(planted) != len(expected):
        checks.append(
            f"the planted change also moved {len(planted) - len(expected)} derived field(s), "
            f"which is the byte-stable writer doing its job"
        )

    if not complaints:
        checks.append(f"the {GATE} row's two numbers match this harness: {DOCUMENTS}/{MUTATIONS}")

    records = sum(len(value) for value in read_archive(full).values() if isinstance(value, list))
    return Report(
        mode="smoke",
        checks=tuple(checks),
        complaints=tuple(complaints),
        absences=NOT_CHECKED_BY_SMOKE,
        documents_compared=1,
        records_compared=records,
        detail=(FALLBACK,),
    )


@dataclass(frozen=True, slots=True)
class Checkpoint:
    """Two export directories that must hold the same corpus, and the step they were taken at.

    A step and not merely a pair, because a report that says *"they differ"* without saying WHEN is
    a report that sends a reader back through forty mutations by hand. `step = 0` is the initial
    roster; `step = n` is after the nth scripted mutation.
    """

    step: int
    incremental: Path
    full: Path


Builder = Callable[[Path, Sequence[int]], Iterator[Checkpoint]]
"""What `run_full` drives. One call, one checkpoint per requested step, in order.

A parameter rather than an import, for the reason this file has stated about itself since P2: it
is the harness and the comparator, and the indexer is `tools/incremental_index.py`. Injecting it
also makes every branch of `run_full` testable without a 300-document build -- which matters,
because the branch that must never be wrong is the one that decides a run did not happen.
"""

CHECKPOINT_EVERY: Final = 10
"""How often the full rebuild runs, in mutations. Four rebuilds over a 40-step script.

**The plan's own reading is ONE rebuild** -- 07:2971 says G19 *"builds a 300-document fixture
through 40 scripted mutations and diffs the `.owdoc` exports against a full rebuild into a second
store"*, singular -- and one diff at the end is a diff a later mutation can mask: a document that
diverged at step 7 and was deleted at step 30 leaves no trace in the final pair. Four is strictly
stronger and affordable: a rebuild plus an export plus a 300-archive diff measures ~18 s on this
workspace's runner, against G19's 420 s budget in `tools/gates.toml`.

The last step is ALWAYS a checkpoint whatever this divides into, because the final state is the one
the plan names. `--checkpoint-every 1` is the nightly's setting and runs all forty."""


def checkpoint_steps(mutations: int, every: int = CHECKPOINT_EVERY) -> tuple[int, ...]:
    """Which steps get a full rebuild. Always includes the last one; never includes step 0.

    Step 0 is excluded because the initial roster is the same single ingest on both sides -- a
    rebuild of it would compare a build to a copy of itself, which is the one comparison that
    cannot fail.
    """
    if every < 1:
        message = f"--checkpoint-every must be at least 1, got {every}"
        raise ValueError(message)
    steps = set(range(every, mutations + 1, every))
    steps.add(mutations)
    return tuple(sorted(steps))


def build_with_index(root: Path, steps: Sequence[int]) -> Iterator[Checkpoint]:
    """The real builder: `tools/incremental_index.py`, loaded by path, driven to each step.

    Loaded by path rather than imported, the way `tools/p2_demo.py` loads its two: `tools/` is not
    a distribution, `importlib.import_module` is banned outside `host/`, and a `sys.path` mutation
    leaks into everything loaded afterwards.

    The incremental store is carried forward across checkpoints and the full store is rebuilt from
    nothing at each one, which is the asymmetry the whole gate is about.
    """
    index = _load_index()
    corpus = index.fixture()
    parser = index.stub()
    side = index.Incremental(root=root / "incremental", corpus=corpus, parser=parser)
    side.start()
    wanted = sorted(steps)
    for step in range(1, (wanted[-1] if wanted else 0) + 1):
        side.step(step - 1)
        if step in wanted:
            incremental = root / "incremental" / f"exports-{step}"
            side.export(incremental)
            full = index.rebuild(root / f"full-{step}", step, corpus=corpus, parser=parser)
            yield Checkpoint(step=step, incremental=incremental, full=full)


def _load_index() -> ModuleType:
    """`tools/incremental_index.py`. One site, so the harness names the indexer exactly once."""
    path = Path(__file__).resolve().parent / "incremental_index.py"
    spec = importlib.util.spec_from_file_location("omniweave_incremental_index", path)
    if spec is None or spec.loader is None:  # pragma: no cover -- a broken checkout.
        message = f"cannot load {path}"
        raise ValueError(message)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _diff_checkpoint(checkpoint: Checkpoint) -> tuple[list[Difference], list[Difference], int, int]:
    """Diff one checkpoint's two directories: every archive on either side, matched by name.

    An archive present on one side only is a divergence of its own and is reported before any
    field is compared -- that is a deleted document that survived, or a new one that never arrived,
    and it is the single most likely shape of an incremental bug.
    """
    left = {path.name: path for path in sorted(checkpoint.incremental.glob("*.owdoc"))}
    right = {path.name: path for path in sorted(checkpoint.full.glob("*.owdoc"))}
    divergences: list[Difference] = []
    provenance: list[Difference] = []
    records = 0
    for name in sorted(set(left) | set(right)):
        where = f"step {checkpoint.step} :: {name}"
        if name not in right:
            divergences.append(Difference(where, "<archive>", "<archive>", "present", "absent"))
            continue
        if name not in left:
            divergences.append(Difference(where, "<archive>", "<archive>", "absent", "present"))
            continue
        for difference in diff_exports(left[name], right[name]):
            relocated = Difference(
                f"{where} :: {difference.where}",
                difference.subject,
                difference.field,
                difference.incremental,
                difference.full,
            )
            (divergences if _is_divergence(difference) else provenance).append(relocated)
        records += 1
    return divergences, provenance, len(set(left) | set(right)), records


def _is_divergence(difference: Difference) -> bool:
    """One `Difference`, classified. `classify` over a single row; see `PROVENANCE`."""
    return bool(classify((difference,))[0])


def run_full(
    fixture: Path,
    register: Path | None = None,
    *,
    root: Path | None = None,
    build: Builder | None = None,
    every: int = CHECKPOINT_EVERY,
    strict: bool = False,
) -> Report:
    """P4's mode (16-roadmap.md:575). Builds both sides and diffs them at every checkpoint.

    Exit 2 and never 0 while the corpus is absent or malformed. A `DID NOT RUN` in the
    `incremental` job is a red PR, which is the correct signal for a gate whose subject has not
    been built: section 6.8's *"a check that cannot yet fail is either quarantined as
    `informational` with an issue number ... or it is not in CI"*, and G19 is in CI with
    `pr = true`.

    `strict` folds the provenance pass back into the divergences, which is the plan's literal
    reading of V10-8 (*"exports identical to a full rebuild"*) and is expected to FAIL on any
    corpus containing an edit. It ships because the concession should be measurable rather than
    assumed: `--strict` prints exactly how far the literal claim is from holding.
    """
    try:
        plan = load_fixture_plan(fixture)
    except ValueError as error:
        return Report(mode="full", not_run=str(error), absences=NOT_CHECKED_BY_SMOKE)
    if plan is None:
        return Report(
            mode="full",
            not_run=f"no fixture corpus at {fixture}",
            detail=(f"expected {FIXTURE_DIR.as_posix()}/plan.toml (16-roadmap.md:550).",),
            absences=NOT_CHECKED_BY_SMOKE,
        )
    complaints = (*check_register(register), *plan.complaints())
    if complaints:
        return Report(mode="full", complaints=complaints, absences=NOT_CHECKED_BY_SMOKE)

    builder = build_with_index if build is None else build
    workspace = Path(tempfile.mkdtemp(prefix="ow-g19-")) if root is None else root
    try:
        steps = checkpoint_steps(len(plan.mutations), every)
        divergences: list[Difference] = []
        provenance: list[Difference] = []
        checks: list[str] = []
        documents = 0
        records = 0
        for checkpoint in builder(workspace, steps):
            found, carried, archives, compared = _diff_checkpoint(checkpoint)
            divergences.extend(found)
            provenance.extend(carried)
            documents += archives
            records += compared
            if not found:
                checks.append(f"step {checkpoint.step}: {archives} archive(s) agree")
    except (OSError, ValueError, RuntimeError) as error:
        return Report(mode="full", not_run=f"the build failed: {error}")
    finally:
        if root is None:
            shutil.rmtree(workspace, ignore_errors=True)

    if not checks and not divergences:
        return Report(mode="full", not_run="the builder produced no checkpoints")
    if strict:
        divergences.extend(provenance)
        provenance = []
    return Report(
        mode="full",
        checks=tuple(checks),
        differences=tuple(divergences),
        provenance=tuple(provenance),
        documents_compared=documents,
        records_compared=records,
        detail=(
            f"{plan.documents} documents, {len(plan.mutations)} mutations, "
            f"rebuilt at step(s) {', '.join(str(step) for step in steps)}.",
        ),
    )


def run_diff(incremental: Path, full: Path) -> Report:
    """The comparator over two archives a caller names. What P4's runner will call per document."""
    for path in (incremental, full):
        if not path.is_file():
            return Report(mode="diff", not_run=f"no such archive: {path}")
    try:
        differences = diff_exports(incremental, full)
    except ValueError as error:
        return Report(mode="diff", not_run=str(error))
    records = sum(len(value) for value in read_archive(full).values() if isinstance(value, list))
    return Report(
        mode="diff",
        checks=() if differences else (f"{incremental.name} == {full.name}",),
        differences=differences,
        documents_compared=1,
        records_compared=records,
    )


# ---------------------------------------------------------------------------
# 7. Entry point
# ---------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gate_incremental.py",
        description=(
            f"{GATE}: an incremental index and a full rebuild produce identical .owdoc exports "
            f"over a {DOCUMENTS}-document fixture in {MUTATIONS} scripted mutations."
        ),
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help=(
            "run the comparator alone, over archives it builds itself. Needs no corpus, no store "
            "and no parser; P2's exit criterion (16-roadmap.md:458)."
        ),
    )
    parser.add_argument(
        "--diff",
        nargs=2,
        metavar=("INCREMENTAL", "FULL"),
        type=Path,
        default=None,
        help="diff two .owdoc exports and report every difference",
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=None,
        help=f"the corpus directory (default: <repo root>/{FIXTURE_DIR.as_posix()})",
    )
    parser.add_argument(
        "--register",
        type=Path,
        default=None,
        help="tools/gates.toml, whose G19 row owns the two numbers (default: this checkout's)",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="keep both stores and every export here instead of a temporary directory",
    )
    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=CHECKPOINT_EVERY,
        metavar="N",
        help=f"rebuild and diff every N mutations (default: {CHECKPOINT_EVERY}; the last always)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="fail on the provenance pass too -- V10-8's literal reading; see PROVENANCE",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    out: TextIO | None = None,
    workdir: Path | None = None,
    build: Builder | None = None,
) -> int:
    """Choose a mode, run it, print the report, return its exit code.

    `workdir` is injectable so a test can see the smoke run's three archives; when it is `None`
    the smoke mode uses a temporary directory it removes on the way out. `build` is the same seam
    `run_full` takes and is here for the same reason: every branch of the full mode is reachable
    in a test without a 300-document build, and the branch that must never be wrong is the one
    that decides a run did not happen.
    """
    writer = sys.stdout if out is None else out
    namespace = _parser().parse_args(sys.argv[1:] if argv is None else list(argv))

    if namespace.diff is not None and namespace.smoke:
        _emit(writer, f"{GATE} DID NOT RUN  --diff and --smoke are different runs; pick one.")
        return EXIT_NOT_RUN

    if namespace.diff is not None:
        report = run_diff(*namespace.diff)
    elif namespace.smoke:
        if workdir is not None:
            report = run_smoke(workdir, namespace.register)
        else:
            import tempfile  # noqa: PLC0415 -- use-time, so --help costs nothing

            with tempfile.TemporaryDirectory(prefix="ow-g19-") as scratch:
                report = run_smoke(Path(scratch), namespace.register)
    else:
        fixture = namespace.fixture if namespace.fixture is not None else _REPO / FIXTURE_DIR
        report = run_full(
            fixture,
            namespace.register,
            root=namespace.root,
            build=build,
            every=namespace.checkpoint_every,
            strict=namespace.strict,
        )

    render(report, writer)
    return exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
