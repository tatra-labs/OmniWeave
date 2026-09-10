"""G19 - incremental == full, diffed over the `.owdoc` **exports**. The harness, not the fixture.

`tools/gates.toml`'s G19 row is the specification: *"incremental == full: 300 docs, 40 mutations,
`.owdoc` export diff"*, in its own `incremental` job at a 420 s budget, blocking a PR, a nightly
and a release. `01-principles.md:506` says the row owns those two numbers ("`G19` owns the fixture
size and the mutation count"), and `07-store-and-retrieval.md:2971` and `08-runtime.md:1858` give
the mechanism in one sentence each: build a 300-document fixture through 40 scripted mutations,
build the same corpus by a full rebuild into a SECOND store, and diff the two `.owdoc` exports --
*"exports rather than tables, because an archive contains no `block_id` and the allocation-order
normalisation that could hide a bug is therefore not needed at all"*.

WHAT LANDS NOW AND WHAT LANDS AT P4, AND WHY THAT SPLIT IS THE PLAN'S
---------------------------------------------------------------------
`16-roadmap.md:458` puts `uv run tools/gate_incremental.py --smoke` in **P2's** exit criteria and
annotates it in as many words: *"G19's harness exists; its fixture lands in P4"*. `:575` puts the
unflagged `uv run tools/gate_incremental.py` in P4's, and `:550` (W4.10) is the work item that
builds *"the `fixtures/incremental/` 300-document / 40-mutation corpus"*. So this file is the
harness and the comparator, and it is deliberately NOT the fixture, the indexer or the rebuilder.

What is real here and runs today:

* `diff_exports()` -- the export diff itself, member by member and record by record, addressed by
  `addr`. This is the whole of G19's comparison and it is complete. It is also what
  `ow bench incremental` (12-performance.md:1520) calls at P7; the `tools/` entry point stays
  because the register names the script.
* `--smoke` -- the harness end to end over a pair of archives it builds itself, proving the
  comparator finds a planted difference and reports none between two equal archives, then listing
  every check it could NOT run with the phase that owns it.
* `--diff A B` -- the comparator over two archives a caller supplies.

What is absent, and how its absence is reported rather than passed over: the fixture corpus, the
40-mutation script, the incremental indexer and the full rebuilder. In the default (full) mode
their absence is `DID NOT RUN` and **exit 2**, never exit 0. `11-repo-layout.md` section 6.8
refuses "a check that cannot yet fail", and a harness that reported success while checking nothing
would be exactly that.

NOT CHECKED IS A REPORTED STATE, NOT A SILENCE. `--smoke` exits 0 -- P2's exit criterion runs it
and expects a pass -- and it prints a NOT CHECKED block naming P4 and `16-roadmap.md:550` for each
missing piece. That is the same asymmetry `tools/gate_coldstart.py` draws between a budget breach
and an unmeasured baseline: an environment with nothing to measure is neither a pass nor a
failure, it is unmeasured, and it says so.

THE TWO NUMBERS ARE TRANSCRIBED, NEVER COMPUTED. `DOCUMENTS = 300` and `MUTATIONS = 40` are read
off the register row and re-asserted against it at run time by `check_register()`, because
`01-principles.md:506` makes the row their owner and a harness that carried its own copy would let
the two drift. `11-repo-layout.md` OQ-6's pre-committed fallback -- above 12 minutes G19 moves to
nightly and the PR path keeps "a deterministic 60-document/8-mutation subset with the mutation
seed derived from `blake2b(commit_sha)`" -- is recorded in `FALLBACK` and is not implemented,
because implementing a fallback before the measurement that triggers it is how the weaker gate
becomes the only gate.

Run it:

    uv run tools/gate_incremental.py --smoke     # P2: the harness, and what it cannot yet check
    uv run tools/gate_incremental.py             # P4: the 300-document / 40-mutation gate
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
import json
import sys
import tomllib
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

__all__ = [
    "DOCUMENTS",
    "EXIT_CLEAN",
    "EXIT_FAIL",
    "EXIT_NOT_RUN",
    "FALLBACK",
    "FIXTURE_DIR",
    "GATE",
    "JOB",
    "MUTATIONS",
    "NOT_CHECKED_AT_P2",
    "Absence",
    "Difference",
    "Report",
    "check_register",
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
    out: list[Difference] = []
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


NOT_CHECKED_AT_P2: tuple[Absence, ...] = (
    Absence(
        f"the {DOCUMENTS}-document fixture corpus at {FIXTURE_DIR.as_posix()}/",
        "P4 / W4.10",
        "16-roadmap.md:550",
    ),
    Absence(
        f"the {MUTATIONS} scripted mutations and their expected-delta assertions",
        "P4 / W4.10",
        "16-roadmap.md:550, priced at ~0.4 engineer-day each",
    ),
    Absence(
        "the incremental indexer: op.converge, anchor_delta and the dep reverse index",
        "P4",
        "08-runtime.md:1846-1860 (section 5.6 a-c)",
    ),
    Absence(
        "the full rebuild into a second store, and the ingest that drives either",
        "P4",
        "07-store-and-retrieval.md:2971",
    ),
)
"""Everything between this harness and the gate the register describes.

Four rows and not one, because they land separately and a reader has to be able to tell which
one is blocking. The first two are W4.10's corpus work; the second two are the runtime the corpus
would be driven through, which 08-runtime.md section 5.6 owns.
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
            f"{GATE} ok  {len(report.checks)} check(s) passed, {len(report.absences)} not checked.",
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
        absences=NOT_CHECKED_AT_P2,
        documents_compared=1,
        records_compared=records,
        detail=(FALLBACK,),
    )


def run_full(fixture: Path, register: Path | None = None) -> Report:
    """P4's mode (16-roadmap.md:575). Refuses to pass while the corpus or the builder is absent.

    Exit 2 and not 0. A `DID NOT RUN` in the `incremental` job is a red PR, which is the correct
    signal for a gate whose subject has not been built: section 6.8's "a check that cannot yet
    fail is either quarantined as `informational` with an issue number ... or it is not in CI",
    and G19 is in CI with `pr = true`.
    """
    try:
        plan = load_fixture_plan(fixture)
    except ValueError as error:
        return Report(mode="full", not_run=str(error), absences=NOT_CHECKED_AT_P2)
    if plan is None:
        return Report(
            mode="full",
            not_run=f"no fixture corpus at {fixture}",
            detail=("run with --smoke until W4.10 lands it (16-roadmap.md:458, :550).",),
            absences=NOT_CHECKED_AT_P2,
        )
    complaints = (*check_register(register), *plan.complaints())
    if complaints:
        return Report(mode="full", complaints=complaints, absences=NOT_CHECKED_AT_P2)
    return Report(
        mode="full",
        not_run=(
            f"{fixture} holds {plan.documents} documents and {len(plan.mutations)} mutations, and "
            f"nothing in this tree can index them"
        ),
        detail=(
            "the corpus landed before its builder; see the NOT CHECKED rows below.",
            FALLBACK,
        ),
        absences=NOT_CHECKED_AT_P2[2:],
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
            "run the harness and report what it cannot yet check. P2's exit criterion "
            "(16-roadmap.md:458); the fixture lands at P4."
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
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    out: TextIO | None = None,
    workdir: Path | None = None,
) -> int:
    """Choose a mode, run it, print the report, return its exit code.

    `workdir` is injectable so a test can see the smoke run's three archives; when it is `None`
    the smoke mode uses a temporary directory it removes on the way out.
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
        report = run_full(fixture, namespace.register)

    render(report, writer)
    return exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
