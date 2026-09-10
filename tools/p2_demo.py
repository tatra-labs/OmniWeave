"""P2's demo, run as five checks rather than read as five sentences. 16-roadmap.md:434-440.

The roadmap's "#### The demo" paragraph is six lines of prose and every clause in it is an
assertion:

  1. ingest `fixtures/gen/gen_5000p_pdf.py`'s output through a stub `parse/1` driver;
  2. `ow store verify` re-derives every `content_digest` and every `content_sha256` from stored
     bytes and compares;
  3. `unzip -p out.owdoc blocks/000063.ndjson | jq .` works with no external decompressor
     installed;
  4. SIGKILL the writer mid-commit, reopen, and `ow resume` converges to the uninterrupted result
     byte for byte in the `.owdoc` export;
  5. re-parse with a one-paragraph edit and `rebind()` carries every cite except the edited
     paragraphs', which take a fresh `n` from `doc.next_cite_n` and leave a `block_history` row
     naming their successor.

A demo that narrates those is worth nothing; this one runs them, prints PASS or FAIL per clause,
and -- where a clause is only half checkable at P2 -- prints WHICH HALF it enforced and which it
did not. The `.github/workflows/ci.yml` G28 step is the worked example of that discipline and
says why in as many words: *"Enforcing half and saying WHICH half is the point."*

## What this script adds that the library cannot, and why it is in `tools/`

Three things, and each one is why `tools/gate_crash.py` lives beside it rather than under
`packages/*/src/**`:

* **Clause 4 needs a real, uncatchable signal.** `subprocess` is banned in library code
  (02-architecture.md:392, enforced as an `ast` check by `tools/gate_semgrep.py`) and `tools/` is
  explicitly outside that ban (`tools/gate_semgrep.py:26-37`). This script does not reimplement
  the kill loop: it CALLS `tools/gate_crash.py`, which already spawns a child, waits for it to
  park on a statement boundary of `Store.complete()` and kills it, and whose comparison is
  already 16-roadmap.md:437's byte-for-byte `.owdoc` one. Reuse rather than a second kill loop is
  deliberate -- two harnesses that kill differently would be two harnesses that test differently,
  which is the exact failure `crashmatrix.verify_boundary`'s `kill` seam exists to prevent.
* **Clause 1 needs the generator and the stub driver, and neither is a distribution.**
  `fixtures/gen/gen_5000p_pdf.py` and `tools/p2_stub_parse.py` are scripts, loaded here by
  `importlib.util.spec_from_file_location` -- the mechanism `test_gate_crash.py` uses for the
  same reasons (not `importlib.import_module`, which is banned outside `host/`, and not a
  `sys.path` mutation, which leaks into everything loaded afterwards).
* **Clause 2's honest half needs `sqlite3`.** INV-10's bytes branch is a statement about the
  relationship between a `part`'s retained bytes and a `block`'s text, and no store-boundary
  method exposes the pair. `sqlite3` is banned to `omniweave_core.store` by ruff TID251; the
  ban's scope is `packages/*/src/**` and this file takes the escape the way
  `tests/unit/test_gate_crash.py` does, in the open and with a reason.

## The verbs this script stands in for

D25's standing pattern: build the library function plus a `tools/` script now, let P7 or P10 wrap
it in a CLI later. `ow store verify` is `omniweave_core.store.verify.verify_store`,
`ow store export --portable` is `omniweave_core.store.portable.export_portable`, `ow resume` is
`omniweave_core.store.crashmatrix.resume`, and `ow test crash-matrix` is
`omniweave_core.store.crashmatrix.crash_matrix`. Every one of them already exists; none of them
has an `ow` front end, because `ow` is P7's (16-roadmap.md section 10).

## Three numbers this script prints that are NOT budgets

* **blocks per page.** D27 splits F1: bytes-per-block is the store variable and closes at P2;
  blocks-per-page is the CORPUS variable and needs the ten real 200-page documents of
  03-document-model.md:3086, which need W3.4/W3.5 drivers and are P3. Any blocks-per-page number
  this script prints is A PROPERTY OF THIS FIXTURE and is labelled so wherever it appears.
* **the frame it checked.** See `_clause3`. `blocks/000063.ndjson` does not exist at this
  fixture's shape until 7,940 pages, so the script names the frame it actually opened.
* **wall-clock seconds.** There is no `budget_s` cell for this script in `tools/gates.toml`; it is
  not a gate, and 12-performance.md:1966 puts every Budget on `ow-bench-1` regardless.

## Exit codes

`0` every clause run held. `1` a clause failed. `2` the demo did not run -- a missing contract
file, a bad argument, a workspace that could not be made. 1 and 2 are distinguished for the reason
`gate_crash.py` distinguishes them: CI treats both as failure and a human needs to know which.

Specified in 16-roadmap.md:434-440 and :452-460, 03-document-model.md sections 6.5 and 6.6,
07-store-and-retrieval.md:3092-3096, 13-quality.md:586-589 and 12-performance.md:244.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import sqlite3  # noqa: TID251 - not library code; see "Clause 2's honest half" above.
import sys
import tempfile
import time
import unicodedata
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from io import StringIO
from pathlib import Path
from types import ModuleType
from typing import Any, Final, TextIO

from omniweave_core.archive.frames import FRAME_TARGET_BLOCKS, FRAMES_MEMBER, frame_member
from omniweave_core.archive.owdoc import REQUIRED_KEYS
from omniweave_core.blobs import BlobStore
from omniweave_core.store import crashmatrix as cm
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_core.store.doc import DocSink
from omniweave_core.store.portable import export_portable
from omniweave_core.store.verify import DEFAULT_CLAUSES, ClauseState, VerifyClause, verify_store

__all__ = [
    "DEFAULT_PAGES",
    "EXIT_CLEAN",
    "EXIT_FAIL",
    "EXIT_NOT_RUN",
    "FIXTURE_BLOCKS_PER_PAGE",
    "NOW_NS",
    "ROADMAP_FRAME",
    "Check",
    "Emit",
    "MissingContractError",
    "frame_index_of",
    "main",
    "pages_for_frame",
    "predicted_blocks_per_page",
]

EXIT_CLEAN = 0
EXIT_FAIL = 1
EXIT_NOT_RUN = 2

SELF: Final = Path(__file__).resolve()
"""This file, resolved. The three sibling scripts are found relative to it, never to the cwd."""


def _repo_root(start: Path) -> Path:
    """The workspace root, found by walking up rather than by counting `parents[n]`.

    Copied in shape from `tests/unit/test_gate_crash.py` and `tests/conftest.py`: the same two
    markers, so a file that moves between `tools/` and a subdirectory does not silently start
    reading a different tree.
    """
    for candidate in (start, *start.parents):
        if (candidate / "tools" / "layers.toml").is_file() and (candidate / "packages").is_dir():
            return candidate
    message = f"no omniweave workspace root above {start}"
    raise RuntimeError(message)


REPO_ROOT: Final = _repo_root(SELF)

GEN_PATH: Final = REPO_ROOT / "fixtures" / "gen" / "gen_5000p_pdf.py"
"""F1's generator. 13-quality.md:586-589 homes it here and gitignores its output directory."""

STUB_PATH: Final = REPO_ROOT / "tools" / "p2_stub_parse.py"
"""F2's stub `parse/1` driver. 16-roadmap.md:434 is the only line that asks for it."""

GATE_CRASH_PATH: Final = REPO_ROOT / "tools" / "gate_crash.py"
"""G21's runner, reused whole for clause 4 rather than reimplemented. See `_clause4`."""

DEFAULT_PAGES = 16
"""How many pages the demo generates unless told otherwise.

**Not 5,000.** 16-roadmap.md:434 names `gen_5000p_pdf`'s output and F1 defaults that generator to
5,000 pages, but this script is the thing a developer runs while changing one of the five clauses,
and a five-thousand-page ingest is not that. The page count changes exactly one reported fact --
which frame clause 3 could open -- and clause 3 prints that fact rather than assuming it. Use
`--pages 5000` for the roadmap's own corpus and `--pages 7940` for the roadmap's own member; see
`pages_for_frame`.
"""

ROADMAP_FRAME: Final = 63
"""The frame 16-roadmap.md:439 names, spelled `blocks/000063.ndjson`.

Six digits and a frame index, per `archive/frames.py:151-152`. A frame closes at
`FRAME_TARGET_BLOCKS = 8_192` blocks, so this member exists only in a document of at least
`63 * 8192 + 1 = 516,097` blocks. `pages_for_frame()` turns that into a page count.
"""

FIXTURE_BLOCKS_PER_PAGE: Final = 65
"""The block count one generated page produces, and **A PROPERTY OF THIS FIXTURE** (D27).

1 page root + 1 `heading` + `PARAGRAPHS_PER_PAGE`(8) coalesced `paragraph` blocks + 1 `table` +
`TABLE_ROWS * TABLE_COLS`(54) `cell` blocks = 65. The 32 body RUNS of an F1 page become 8 blocks
and not 32, because F3's coalescing rule folds the four runs of one paragraph into one block;
forgetting that is the single arithmetic slip that would put every frame number in this report
out by a factor of four.

Written as a literal and ALSO derived from the generator's own constants by
`predicted_blocks_per_page()`, which clause 1 compares against it and against the count actually
measured off the store. A literal alone drifts when F1's constants move; a derivation alone agrees
with whatever the generator happened to emit and can therefore never fail.

This is not blocks-per-page in F1's sense. F1 closes over ten real 200-page documents
(03-document-model.md:3086); a synthetic page with exactly eight paragraphs and one 9x6 table
measures the generator, and D27 says the corpus half of F1 is P3's.
"""

NOW_NS: Final = 1_757_400_000_000_000_000
"""The injected wall clock, fixed.

`time.time` is banned in library code and every store clock is a parameter, so the demo stamps its
migration ledger with a constant -- the same constant `tools/gate_crash.py` uses, and for the same
reason: it is one of the things that makes two runs byte-identical rather than merely equivalent.
"""

DOC_URI: Final = "file:///corpus/gen_5000p.pdf"
"""The document's `uri`, a constant rather than the workspace path.

`doc.uri` is what `verify.py:_content_sha256` joins `unit` on, and it reaches the `.owdoc`
manifest, so an ambient temp path would make both the report and the archive machine-dependent.
"""

EDIT_MARKER: Final = "EDITED-BY-P2-DEMO"
"""The ASCII clause 5's patch writes into one paragraph run, so the edited block is findable.

The patch is byte-length preserving (see `_patch_one_paragraph`), which is what keeps F1's classic
cross-reference TABLE valid without regenerating it: every entry in that table is an absolute byte
offset, and a patch that changed a length would invalidate every entry after it.
"""

SECOND_GEN: Final = 2
"""The generation clause 5's re-parse must publish.

A named constant rather than a literal in the comparison because it is the difference between a
committed re-parse and a QUARANTINED one (03:1298-1302), and that distinction deserves a name
where a reader of the failure message will find it.
"""

REQUIRED_VERIFY_CLAUSES: Final = frozenset(
    {
        VerifyClause.BLOCK_DIGEST,
        VerifyClause.CAS_DIGEST,
        VerifyClause.CONTENT_SHA256,
    }
)
"""The `verify_store` clauses 16-roadmap.md:435 is about, which this demo requires to be PASSED.

Three and not fifteen. A FAILED clause anywhere fails clause 2; an UNCHECKED one is reported with
its own reason and fails clause 2 only if it is in this set. The distinction exists because
`retired_occurrences` is UNCHECKED by construction at P2 -- 03:2792's `tools/wirekeys.toml` does
not exist and `verify.py:_retired_occurrences` refuses to answer an empty question -- so a demand
that all fifteen be PASSED would be a demand this phase cannot meet, and quietly relaxing it to
"not FAILED" would let a clause that never ran read as one that held.
"""

MAX_NOTES: Final = 8
"""How many failure notes one clause prints before the rest are counted rather than listed.

A wrong byte offset in a driver produces one finding per block, and a 5,000-page corpus would
produce 325,000 of them. The cap is on the REPORT and never on the check: the count printed
after the cap is the full count, so a reader can tell 9 findings from 90,000.
"""

CLAUSES: Final = (1, 2, 3, 4, 5)
"""The five clauses of 16-roadmap.md:434-440, in the order the roadmap states them.

`--skip` validates against this tuple, so a sixth clause cannot be skipped by accident and a
clause that was skipped is reported by number rather than silently absent.
"""

_CODE_FINGERPRINT: Final = "p2-demo"
"""`producer.code_fingerprint`, which is `NOT NULL`. The demo resolves the producer row itself
because minting it is not one of `DocSink`'s eleven methods (`store/doc.py`, the constructor)."""


# ---------------------------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------------------------

Emit = Callable[[str], None]
"""One line of the report. `print` is banned repo-wide by ruff `T20`; this needs no waiver."""


def _emitter(out: TextIO) -> Emit:
    """Bind the report to a stream, so a test asserts its TEXT rather than a global's.

    `main(argv, *, out)` is the house shape (`tools/gate_crash.py`, `tools/gate_incremental.py`)
    and the reason is the same here: this script's whole product is its report, and a report
    written unconditionally to `sys.stdout` makes every assertion about it a `capsys` reading.
    """

    def emit(line: str) -> None:
        out.write(line + "\n")
        out.flush()

    return emit


def _capped(failures: Sequence[str]) -> tuple[str, ...]:
    """The first `MAX_NOTES` failures, plus a line counting the ones not shown.

    The count is of the WHOLE list, so truncating the report never truncates the finding: a
    reader sees "and 324,992 more", which is a different fact from eight failures and must not
    look like one.
    """
    if len(failures) <= MAX_NOTES:
        return tuple(failures)
    hidden = len(failures) - MAX_NOTES
    return (*failures[:MAX_NOTES], f"... and {hidden} more finding(s) not listed (MAX_NOTES)")


@dataclass(frozen=True, slots=True)
class Check:
    """One roadmap clause, as this script reports it.

    `enforced` and `deferred` are two fields and not one free-text `notes` blob, on purpose. A
    clause that checked half of its sentence has to say which half somewhere a reader cannot skip,
    and the bottom of a note list is exactly where a reader skips. An empty `deferred` means the
    whole clause was enforced; a non-empty one prints under the row whether the clause passed or
    not, because a passing half-check is the more dangerous of the two.
    """

    clause: int
    title: str
    ok: bool
    enforced: str
    deferred: str = ""
    notes: tuple[str, ...] = ()
    seconds: float = 0.0

    def verdict(self) -> str:
        return "PASS" if self.ok else "FAIL"


class MissingContractError(RuntimeError):
    """A file this demo drives is not on disk. Exit 2, never exit 1.

    `fixtures/gen/gen_5000p_pdf.py` (F1) and `tools/p2_stub_parse.py` (F2) are built to a frozen
    signature alongside this file. Their absence is a demo that DID NOT RUN, which is a different
    fact from a clause that failed, and 11-repo-layout.md section 6.8's refusal of a check that
    cannot fail is why the two must not read alike.
    """


def _load(name: str, path: Path) -> ModuleType | None:
    """Load a `tools/`-style script by path, or `None` when it is not there yet.

    `spec_from_file_location` and not `importlib.import_module` (banned outside `host/`), and not
    a `sys.path` mutation (it would leak into everything loaded afterwards). This is the mechanism
    `tests/unit/test_gate_crash.py:69-75` uses and it is copied deliberately.
    """
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - a real file always has a loader.
        message = f"cannot load {path}"
        raise MissingContractError(message)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GEN: Final = _load("omniweave_p2_gen_5000p_pdf", GEN_PATH)
STUB: Final = _load("omniweave_p2_stub_parse", STUB_PATH)
GATE: Final = _load("omniweave_p2_gate_crash", GATE_CRASH_PATH)


def _require(module: ModuleType | None, path: Path, contract: str) -> ModuleType:
    """The module, or a `MissingContractError` naming the file and the contract it owes."""
    if module is None:
        message = (
            f"{path.relative_to(REPO_ROOT).as_posix()} is not on disk, so contract {contract} "
            f"has nothing to drive"
        )
        raise MissingContractError(message)
    return module


# ---------------------------------------------------------------------------------------------
# Frame arithmetic. Pure, because clause 3's honesty rests on it and a test must pin it.
# ---------------------------------------------------------------------------------------------


def frame_index_of(block_ordinal: int) -> int:
    """Which frame the `block_ordinal`-th block of a document lands in. Both ends 0-based.

    `archive/frames.py`'s writer closes a frame once it holds `FRAME_TARGET_BLOCKS` blocks, so the
    map is integer division and nothing more. It is a named function rather than an inline `//`
    because clause 3's advice line is derived from it, and a wrong frame number printed with
    authority is worse than no frame number at all.
    """
    if block_ordinal < 0:
        message = f"a block ordinal is non-negative, got {block_ordinal}"
        raise ValueError(message)
    return block_ordinal // FRAME_TARGET_BLOCKS


def pages_for_frame(frame: int, *, blocks_per_page: int, roots: int = 1) -> int:
    """The least `--pages` whose block stream reaches `frame`. Clause 3's advice, computed.

    `roots` is the `document` root block, of which there is one per DOCUMENT and not one per page
    (03:283), so an N-page document holds `roots + N * blocks_per_page` blocks. Reaching frame `f`
    needs `f * FRAME_TARGET_BLOCKS + 1` blocks -- one block IN the frame, not a whole frame's
    worth, which is the off-by-8,191 this function exists to get right once.

    At this fixture's 65 blocks per page that puts `blocks/000063.ndjson` at 7,940 pages, which is
    the number clause 3 prints when it cannot open the member 16-roadmap.md:439 names.
    """
    if blocks_per_page <= 0:
        message = f"blocks_per_page is positive, got {blocks_per_page}"
        raise ValueError(message)
    needed = frame * FRAME_TARGET_BLOCKS + 1 - roots
    return max(1, -(-needed // blocks_per_page))


def predicted_blocks_per_page(gen: ModuleType) -> int:
    """`FIXTURE_BLOCKS_PER_PAGE`, derived from F1's own constants instead of asserted.

    The page root, the heading, ONE block per paragraph (F3 coalesces a paragraph's
    `LINES_PER_PARAGRAPH` runs into a single `Kind.PARAGRAPH` block), the table, and one block per
    cell. `LINES_PER_PARAGRAPH` deliberately does not appear: it multiplies runs, not blocks.
    """
    return 1 + 1 + int(gen.PARAGRAPHS_PER_PAGE) + 1 + int(gen.TABLE_ROWS) * int(gen.TABLE_COLS)


# ---------------------------------------------------------------------------------------------
# The store, and the ingest through the stub driver
# ---------------------------------------------------------------------------------------------


def _fresh_store(root: Path, stub: ModuleType) -> tuple[Path, Path, int]:
    """A migrated `.owstore`, a CAS beside it, and the `producer` row every block is stamped with.

    The producer is resolved before the parse runs -- `store/doc.py`'s constructor docstring says
    it in those words, *"the runner resolved the `producer` row before the parse ran"* -- which is
    why this is raw SQL here and not a twelfth sink method.
    """
    path = root / "index.owstore"
    cas = root / "cas"
    cas.mkdir(parents=True, exist_ok=True)
    connection = ow.connect(path)
    try:
        applied = migrate.apply_pending(connection, now_ns=NOW_NS)
        if len(applied) != cm.SHIPPED_MIGRATIONS:
            message = f"expected {cm.SHIPPED_MIGRATIONS} shipped migrations, applied {len(applied)}"
            raise MissingContractError(message)
        cursor = connection.execute(
            "INSERT INTO producer(operator, op_version, code_fingerprint, options_digest) "
            "VALUES(?, ?, ?, X'00')",
            (str(stub.OPERATOR), int(stub.OP_VERSION), _CODE_FINGERPRINT),
        )
        connection.commit()
        producer_id = int(cursor.lastrowid or 0)
    finally:
        connection.close()
    return path, cas, producer_id


def _ingest(
    path: Path, cas: Path, *, producer_id: int, stub: ModuleType, pdf: Path, key: bytes
) -> Any:
    """One ingest through the stub `parse/1` driver, `begin_doc` to `end_doc`.

    The sink is built HERE and handed to the driver, which is INV-6/INV-7's shape: `DocSink` is
    host-side and is never constructed by a driver in the real pipeline either (03:548-551). What
    makes this a stub rather than a driver is only that it is called in-process instead of over
    `owdoc-fragment/1`; everything it writes, it writes through the eleven methods.
    """
    with ow.StoreThread(lambda: ow.connect(path)) as thread:
        sink = DocSink(
            thread,
            producer_id=producer_id,
            origin_operator=str(stub.OPERATOR),
            origin_driver=str(stub.DRIVER_ID),
            driver_schema_v=int(stub.DRIVER_SCHEMA_V),
            blobs=BlobStore(cas),
        )
        return stub.ingest(sink, pdf=pdf, uri=DOC_URI, doc_ord=0, doc_key=key)


def _ordinals(connection: sqlite3.Connection, domain: str) -> Mapping[str, int]:
    """`{member name: ord}` for one closed domain, **read off the store and not off Python**.

    `crashmatrix._enum_names` states the rule for the other direction and it holds here too:
    reading ordinals off this build's enums would make a store built by an older seed answer with
    this build's numbering, which is precisely the drift `enum_val` exists to make impossible.
    """
    return {
        str(name): int(ordinal)
        for name, ordinal in connection.execute(
            "SELECT name, ord FROM enum_val WHERE domain = ?", (domain,)
        )
    }


# ---------------------------------------------------------------------------------------------
# Clause 1 -- ingest the generated PDF through the stub parse/1 driver
# ---------------------------------------------------------------------------------------------


def _clause1(path: Path, record: Any, pages: int, stub: ModuleType, gen: ModuleType) -> Check:
    """16-roadmap.md:434, and the four things that make it more than "no exception was raised".

    A generation that quarantined leaves `doc.gen` where it was and its rows durable and invisible
    (03:1298-1302), so `gen == 1` is the entire difference between an ingest and a refused one.
    `origin_driver` on every block is what says the rows came through THIS driver rather than some
    other path: it is one of D3's three ownership columns, stamped by the sink and unwritable by a
    driver (INV-6/INV-7, 03:302-304). The root's cite is pinned to the LITERAL `d1#1` -- the first
    document is `d1` and its root takes `n = 1` (03:1146) -- rather than compared against another
    column of the same store, which would pin agreement and not value. And the measured
    blocks-per-page is checked against F1's own constants, which turns "some rows landed" into
    "this page produced the blocks F3 says it produces".
    """
    connection = ow.connect_readonly(path)
    try:
        blocks = int(
            connection.execute(
                "SELECT count(*) FROM block WHERE doc_ord = ? AND gen = ?",
                (record.doc_ord, record.gen),
            ).fetchone()[0]
        )
        page_rows = int(
            connection.execute(
                "SELECT count(*) FROM page WHERE doc_ord = ? AND gen = ?",
                (record.doc_ord, record.gen),
            ).fetchone()[0]
        )
        foreign = int(
            connection.execute(
                "SELECT count(*) FROM block WHERE doc_ord = ? AND gen = ? AND origin_driver <> ?",
                (record.doc_ord, record.gen, str(stub.DRIVER_ID)),
            ).fetchone()[0]
        )
        root = connection.execute(
            "SELECT cite, addr FROM block WHERE doc_ord = ? AND gen = ? AND parent_id IS NULL",
            (record.doc_ord, record.gen),
        ).fetchone()
    finally:
        connection.close()

    predicted = predicted_blocks_per_page(gen)
    measured = (blocks - 1) / pages if pages else 0.0
    failures: list[str] = []
    if record.gen != 1:
        failures.append(f"doc.gen is {record.gen}, not 1: the generation did not commit")
    if page_rows != pages:
        failures.append(f"{page_rows} page row(s) for {pages} generated page(s)")
    if foreign:
        failures.append(f"{foreign} block(s) carry an origin_driver other than {stub.DRIVER_ID!r}")
    if root is None or (str(root[0]), str(root[1])) != ("d1#1", "doc"):
        failures.append(f"the root block is {root}, not ('d1#1', 'doc') (03:816, 03:1146)")
    if predicted != FIXTURE_BLOCKS_PER_PAGE:
        failures.append(
            f"F1's constants predict {predicted} blocks/page and this module's literal says "
            f"{FIXTURE_BLOCKS_PER_PAGE}; clause 3's frame arithmetic reads the literal"
        )
    if measured != float(predicted):
        failures.append(
            f"measured {measured:g} blocks/page against {predicted} predicted from F1's "
            f"PARAGRAPHS_PER_PAGE, TABLE_ROWS and TABLE_COLS"
        )
    return Check(
        clause=1,
        title="ingest the generated PDF through the stub parse/1 driver",
        ok=not failures,
        enforced=(
            f"{pages} page(s) -> {blocks} block(s) committed at gen 1 through "
            f"{stub.DRIVER_ID}; every block stamped with that origin_driver; root cite d1#1"
        ),
        deferred=(
            "the corpus is ONE synthetic document. 03-document-model.md:3086 closes F1 over ten "
            "real 200-page documents, which need the W3.4/W3.5 drivers and are P3 (D27)"
        ),
        notes=(
            f"blocks/page = {measured:g} -- A PROPERTY OF THIS FIXTURE and not a corpus "
            f"measurement (D27; F1's blocks-per-page closes at P3, 03:3086)",
            *_capped(failures),
        ),
    )


# ---------------------------------------------------------------------------------------------
# Clause 2 -- every content_digest and every content_sha256, re-derived from stored bytes
# ---------------------------------------------------------------------------------------------

_BYTES_ORIGIN_SQL: Final = """
SELECT b.cite, b.text, b.quote, b.os_part, b.os_a, b.os_b, b.os_codec, p.store_ref
  FROM block b JOIN part p ON p.doc_ord = b.doc_ord AND p.path = b.os_part
 WHERE b.doc_ord = ? AND b.gen = ? AND b.os_kind = ? AND b.text IS NOT NULL
 ORDER BY b.block_id
"""
"""Every block whose `OriginSpan` is the `bytes` variant, joined to the part it cites."""


def _redrive_bytes(
    connection: sqlite3.Connection, blobs: BlobStore, doc_ord: int, gen_no: int
) -> tuple[int, int, list[str]]:
    """INV-10's bytes branch, run: `nfc(part_bytes[a:a+len].decode(codec)) == block.text`.

    `0001_init.sql:409-418` prints the invariant and its three re-verifiable branches and this is
    the first of them. It is the half `verify_store`'s own `content_sha256` clause states it
    cannot do -- *"those bytes are the source file, which is outside the store by construction ...
    a clause that claimed to re-derive it would be claiming to have read a file it never opened"*
    (`store/verify.py:_content_sha256`). The demo CAN read them, because F3 retains the whole PDF
    as `part('file')` in the CAS, so the bytes are inside the store's own content-addressed store
    and the re-derivation is a real one against a real file.

    **Only `VERBATIM` blocks are compared, and that is INV-10's own scope** rather than a
    convenience: the invariant reads *"quote='verbatim' requires ... ONE OF EXACTLY THREE
    RE-VERIFIABLE BRANCHES"*. A coalesced paragraph is `NORMALIZED` because its text is four runs
    joined with a space (F3), and demanding byte equality of it would be demanding that the Quote
    ladder lie in the other direction.

    Returns `(verbatim_compared, below_verbatim_seen, failures)`.
    """
    quote = _ordinals(connection, "quote")
    os_kind = _ordinals(connection, "origin_span_kind")
    verbatim = quote["verbatim"]
    cache: dict[str, bytes] = {}
    compared = 0
    skipped = 0
    failures: list[str] = []
    for cite, text, quote_ord, part, start, length, codec, store_ref in connection.execute(
        _BYTES_ORIGIN_SQL, (doc_ord, gen_no, os_kind["bytes"])
    ):
        if int(quote_ord) != verbatim:
            skipped += 1
            continue
        if store_ref is None:
            failures.append(f"{cite}: part {part!r} was not retained, so VERBATIM is unprovable")
            continue
        raw = cache.get(str(store_ref))
        if raw is None:
            with blobs.open_ref(str(store_ref)) as handle:
                raw = handle.read()
            cache[str(store_ref)] = raw
        encoding, _, errors = str(codec).partition("/")
        window = raw[int(start) : int(start) + int(length)]
        derived = unicodedata.normalize("NFC", window.decode(encoding, errors or "strict"))
        compared += 1
        if derived != str(text):
            failures.append(
                f"{cite}: part[{start}:{int(start) + int(length)}] decodes to {derived!r} but "
                f"the block holds {text!r} -- INV-10's bytes branch fails for a VERBATIM block"
            )
    return compared, skipped, failures


def _clause2(path: Path, cas: Path, record: Any) -> Check:
    """16-roadmap.md:435, in the two halves the sentence conflates.

    *"`ow store verify` re-derives every `content_digest` and every `content_sha256` from stored
    bytes and compares."* `content_digest` is genuinely re-derived: `verify.py:_block_digest`
    calls `identity.content_digest` with each row's own kind, layer, text, payload and child
    digests, so a digest edited in place disagrees with the recipe and a recipe edited in place
    disagrees with every row. `content_sha256` is NOT re-derived by that clause, and the clause
    says so at length -- the bytes it digests are the source file, which the store does not hold.

    So this runs `verify_store` for the first half and INV-10's bytes branch for the second, and
    reports both counts instead of one verdict.

    `blobs` is passed, so the CAS digest clause is PASSED rather than UNCHECKED; without it a
    missing CAS reads as a pass, which `verify.py`'s own docstring names as the failure mode.

    **The three clauses this demo requires to be PASSED are named, and the rest may be UNCHECKED.**
    `VerifyReport.ok` is true over an UNCHECKED clause, so "not FAILED" alone would let a check
    that did not run read as a check that held. But demanding PASSED of all fifteen would be
    demanding something P2 cannot give: `retired_occurrences` is UNCHECKED by construction --
    03:2792's register `tools/wirekeys.toml` does not exist, and `verify.py:_retired_occurrences`
    refuses to rubber-stamp an empty question. So `REQUIRED_VERIFY_CLAUSES` names the three the
    roadmap sentence is actually about, every other UNCHECKED clause is reported with the reason
    it gave, and a FAILED clause anywhere fails the demo.
    """
    blobs = BlobStore(cas)
    connection = ow.connect_readonly(path)
    try:
        report = verify_store(connection, now_ns=NOW_NS, clauses=DEFAULT_CLAUSES, blobs=blobs)
        compared, skipped, failures = _redrive_bytes(connection, blobs, record.doc_ord, record.gen)
    finally:
        connection.close()

    digests = report.by_clause(VerifyClause.BLOCK_DIGEST)
    sha = report.by_clause(VerifyClause.CONTENT_SHA256)
    cas_clause = report.by_clause(VerifyClause.CAS_DIGEST)
    failures.extend(f"{f.clause}/{f.where}: {f.detail}" for f in report.findings)
    required = [
        result.clause
        for result in report.clauses
        if result.clause in REQUIRED_VERIFY_CLAUSES and result.state is not ClauseState.PASSED
    ]
    if required:
        failures.append(f"required clause(s) not PASSED: {', '.join(required)}")
    unchecked = [
        f"{result.clause} UNCHECKED: {result.reason}"
        for result in report.clauses
        if result.state is ClauseState.UNCHECKED
    ]
    if compared == 0:
        failures.append(
            "no VERBATIM block carries a bytes origin, so the re-derivation had nothing to "
            "compare -- a check that cannot fail (11-repo-layout.md section 6.8)"
        )
    return Check(
        clause=2,
        title="ow store verify re-derives every content_digest and content_sha256 and compares",
        ok=not failures,
        enforced=(
            f"{digests.checked} content_digest re-derived from the row's own columns; "
            f"{cas_clause.checked} CAS blob(s) re-hashed; {compared} VERBATIM block(s) "
            f"re-derived from the retained part bytes (INV-10 bytes branch); "
            f"{len(report.clauses) - len(unchecked)} of {len(report.clauses)} verify clause(s) "
            f"PASSED, none FAILED"
        ),
        deferred=(
            f"content_sha256 itself is SHAPE-checked over {sha.checked} column value(s) and "
            f"cannot be re-hashed -- 'those bytes are the source file, which is outside the store "
            f"by construction' (store/verify.py:_content_sha256). The demo substitutes INV-10's "
            f"bytes branch, which re-reads bytes the store DOES retain"
        ),
        notes=(
            f"{skipped} bytes-origin block(s) below VERBATIM were not compared; INV-10 scopes the "
            f"branch to quote='verbatim' (0001_init.sql:409-411)",
            *unchecked,
            *_capped(failures),
        ),
    )


# ---------------------------------------------------------------------------------------------
# Clause 3 -- unzip -p out.owdoc blocks/000063.ndjson | jq . with no external decompressor
# ---------------------------------------------------------------------------------------------


def _jq_findings(member: str, lines: Sequence[str]) -> list[str]:
    """`| jq .` on every line of one frame member, as a list of complaints.

    Split out of `_clause3` so that clause reads as its three claims rather than as a loop, and
    because "every line is a JSON OBJECT carrying the wire keys" is a different assertion from
    "the member inflated at all" and deserves to fail with its own message and line number.

    `REQUIRED_KEYS` is `archive/owdoc.py`'s, not a list retyped here: the archive owns which keys
    a block record must carry, and a second copy in a demo would be a second definition site.
    """
    findings: list[str] = []
    for number, line in enumerate(lines, start=1):
        record = json.loads(line)
        if not isinstance(record, dict):
            findings.append(f"{member}:{number} is a {type(record).__name__}, not an object")
            continue
        missing = REQUIRED_KEYS - set(record)
        if missing:
            findings.append(f"{member}:{number} is missing {sorted(missing)}")
    return findings


def _clause3(path: Path, cas: Path, directory: Path, blocks_per_page: int) -> Check:
    """16-roadmap.md:439, and the reason the frame number is printed rather than assumed.

    Three claims live in that one shell pipeline, and each is checked as a claim:

    1. **"with no external decompressor installed"** is a statement about what a READER needs, so
       the honest test is that stdlib `zipfile` plus stdlib `json` -- and nothing else -- open the
       archive and parse it. This function imports neither `zstandard` nor anything outside the
       stdlib, and it additionally asserts the member's `compress_type` is `ZIP_DEFLATED`: a zstd
       member would still be readable by a library that bundled zstd, and the sentence is
       precisely about not needing one.
    2. **`| jq .` works.** Every line parses as a JSON object carrying `owdoc`'s `REQUIRED_KEYS`.
       A member that inflated to garbage would satisfy claim 1 and fail this one.
    3. **`blocks/000063.ndjson`.** The 63rd frame exists only above 516,097 blocks, which at this
       fixture's shape is 7,940 pages. When the corpus is smaller this opens the LAST frame and
       says which one it opened and what `--pages` would reach the roadmap's -- because checking
       frame 0 and printing the roadmap sentence is the failure this clause exists to avoid.

    The frame's declared `sha256` is re-derived here as well. It is *"over the UNCOMPRESSED NDJSON
    bytes"* (03:2633), which is what lets a reader verify one member without inflating the
    archive, and re-deriving it costs one hash over bytes already in hand.
    """
    title = "unzip -p out.owdoc blocks/NNNNNN.ndjson | jq . with no external decompressor"
    directory.mkdir(parents=True, exist_ok=True)
    connection = ow.connect_readonly(path)
    try:
        exported = export_portable(connection, directory, blobs=BlobStore(cas))
    finally:
        connection.close()
    if not exported.artefacts:
        return Check(
            clause=3,
            title=title,
            ok=False,
            enforced="",
            notes=(f"export_portable wrote no archive; skipped: {exported.skipped}",),
        )

    artefact = exported.artefacts[0]
    wanted = frame_member(ROADMAP_FRAME)
    failures: list[str] = []
    with zipfile.ZipFile(artefact.path) as archive:
        names = sorted(archive.namelist())
        frames = json.loads(archive.read(FRAMES_MEMBER).decode("utf-8"))
        if wanted in names:
            member = wanted
            why = f"the member 16-roadmap.md:439 names; this archive holds {len(frames)} frame(s)"
        else:
            member = str(frames[-1]["path"])
            need = pages_for_frame(ROADMAP_FRAME, blocks_per_page=blocks_per_page)
            why = (
                f"{wanted} does not exist -- this archive holds {len(frames)} frame(s). Frame "
                f"{ROADMAP_FRAME} needs {ROADMAP_FRAME * FRAME_TARGET_BLOCKS + 1} blocks at "
                f"{FRAME_TARGET_BLOCKS} blocks/frame, i.e. --pages {need} at this fixture's "
                f"{blocks_per_page} blocks/page. The LAST frame was checked instead"
            )
        info = archive.getinfo(member)
        raw = archive.read(member)
        undeflated = [n for n in names if archive.getinfo(n).compress_type != zipfile.ZIP_DEFLATED]
        if info.compress_type != zipfile.ZIP_DEFLATED:
            failures.append(
                f"{member} has compress_type {info.compress_type}, not ZIP_DEFLATED (8): a "
                f"reader would need a decompressor the stdlib does not carry"
            )
        lines = raw.decode("utf-8").splitlines()
        failures.extend(_jq_findings(member, lines))
        declared = next((f for f in frames if str(f["path"]) == member), None)
        if declared is None:
            failures.append(f"{member} is in the ZIP but not in {FRAMES_MEMBER}")
        else:
            if int(declared["blocks"]) != len(lines):
                failures.append(
                    f"{FRAMES_MEMBER} claims {declared['blocks']} block(s) in {member}; the "
                    f"member holds {len(lines)} line(s)"
                )
            digest = hashlib.sha256(raw).hexdigest()
            if digest != str(declared["sha256"]):
                failures.append(
                    f"{member}'s uncompressed bytes hash to {digest[:16]} and {FRAMES_MEMBER} "
                    f"declares {str(declared['sha256'])[:16]} (03:2633)"
                )
    if undeflated:
        failures.append(f"member(s) not ZIP_DEFLATED: {', '.join(undeflated)}")
    return Check(
        clause=3,
        title=title,
        ok=not failures,
        enforced=(
            f"stdlib zipfile+json alone read {member}: {len(lines)} NDJSON line(s), "
            f"ZIP_DEFLATED, every line an object carrying owdoc's {len(REQUIRED_KEYS)} required "
            f"keys, frames.json's sha256 over the uncompressed bytes re-derived"
        ),
        deferred=(
            ""
            if member == wanted
            else f"the roadmap names {wanted} and this run could not open it -- {why}"
        ),
        notes=(
            f"frame checked: {member} -- {why}",
            f"archive: {artefact.path.name}",
            *_capped(failures),
        ),
    )


# ---------------------------------------------------------------------------------------------
# Clause 4 -- SIGKILL mid-commit, resume, converge byte for byte
# ---------------------------------------------------------------------------------------------


def _clause4(workspace: Path, gate: ModuleType, *, points: int, in_process: bool) -> Check:
    """16-roadmap.md:436-437, delegated whole to `tools/gate_crash.py`. Reuse, and here is why.

    That script already does every part of the sentence: it spawns a child, waits for it to park
    on a named statement boundary inside `Store.complete()`, sends an uncatchable signal
    (`Popen.kill()` -- `SIGKILL` on POSIX, `TerminateProcess` on Windows), reopens, resumes and
    compares the resumed store against an uninterrupted one through `crashmatrix.fingerprint`,
    whose `owdoc` field IS 16-roadmap.md:437's byte-for-byte `.owdoc` export. A second kill loop
    here would be a second harness that could kill differently, which is the exact failure
    `verify_boundary`'s `kill` seam exists to prevent. So this calls `gate_crash.main()`
    in-process and takes its exit code and its report.

    **WHICH HALF.** The kill lands in the CRASH-MATRIX fixture corpus's `complete()` transaction,
    not inside this PDF ingest's `end_doc()`. `DocSink` exposes no boundary hook and
    `crashmatrix.SCENARIOS` are the only instrumented transactions in the tree, so at P2 there is
    no point at which a PDF ingest could be parked. What that costs is real and the row says it:
    this proves the STORE converges after a kill mid-commit, not that a 5,000-page parse resumes
    at the page it died on -- the latter is `work`-row driven and is P4's.

    `--points 1` by default rather than G21's three, because clause 4 is one of five here and
    G21's own runner is the place its three-point cell is honoured; `--kill-points 3` reproduces
    the gate exactly.
    """
    workspace.mkdir(parents=True, exist_ok=True)
    argv = ["--workspace", str(workspace), "--points", str(points)]
    if in_process:
        argv.append("--in-process")
    buffer = StringIO()
    code = int(gate.main(argv, out=buffer))
    lines = [line for line in buffer.getvalue().splitlines() if line.strip()]
    failures: list[str] = []
    if code != gate.EXIT_CLEAN:
        failures.append(f"tools/gate_crash.py exited {code}")
        failures.extend(line.strip() for line in lines if "FAIL" in line or "diverged" in line)
    return Check(
        clause=4,
        title="SIGKILL the writer mid-commit; resume converges byte for byte in the .owdoc export",
        ok=not failures,
        enforced=(
            f"tools/gate_crash.py over {points} kill point(s), "
            f"{'in-process model' if in_process else 'a real uncatchable signal'}: "
            f"{lines[-1] if lines else '(no report)'}"
        ),
        deferred=(
            "the kill is at a statement boundary of the CRASH-MATRIX fixture's Store.complete(), "
            "not inside this PDF ingest's end_doc(): DocSink exposes no boundary hook and "
            "crashmatrix.SCENARIOS are the only instrumented transactions at P2. Resuming a "
            "part-finished 5,000-page parse is work-row driven and is P4's"
        ),
        notes=tuple(failures),
    )


# ---------------------------------------------------------------------------------------------
# Clause 5 -- re-parse with a one-paragraph edit, and what rebind() actually does
# ---------------------------------------------------------------------------------------------


def _patch_one_paragraph(data: bytes, pages: Sequence[Any], gen: ModuleType) -> tuple[bytes, str]:
    """Overwrite one body run's literal in place, preserving its byte length exactly.

    F2 hands back `byte_start`/`byte_len` -- offsets into the FILE, not into a decoded stream --
    for every run, which is what makes an in-place patch possible at all. Length preservation is
    not tidiness: F1 emits a CLASSIC cross-reference TABLE, every entry of which is an absolute
    byte offset, so a patch that changed a length would invalidate every entry after it and the
    re-parse would be measuring a broken file rather than an edited document.

    The run chosen is the first run of the SECOND body paragraph of page 1, found by
    `size_pt == BODY_SIZE_PT` and counted in `LINES_PER_PARAGRAPH` strides. Not the heading and
    not a cell: those are different Kinds, and clause 5 is a statement about a paragraph.

    Returns the patched bytes and the replacement text, so the caller can find the block again.
    """
    body = [run for run in pages[0].runs if run.size_pt == gen.BODY_SIZE_PT]
    if len(body) <= int(gen.LINES_PER_PARAGRAPH):
        message = "page 1 holds fewer than two body paragraphs; there is nothing to edit"
        raise MissingContractError(message)
    target = body[int(gen.LINES_PER_PARAGRAPH)]
    padding = target.byte_len - len(EDIT_MARKER)
    if padding < 0:
        message = f"a body run is {target.byte_len} B, shorter than the {len(EDIT_MARKER)} B mark"
        raise MissingContractError(message)
    replacement = (EDIT_MARKER + "." * padding).encode("ascii")
    patched = bytearray(data)
    patched[target.byte_start : target.byte_start + target.byte_len] = replacement
    return bytes(patched), replacement.decode("ascii")


_LIVE_BLOCKS_SQL: Final = """
SELECT block_id, cite, addr, revision, text
  FROM block WHERE doc_ord = ? AND gen = ? AND state = 0
"""


def _live_blocks(
    connection: sqlite3.Connection, doc_ord: int, gen_no: int
) -> dict[int, tuple[str, str, int, Any]]:
    """`{block_id: (cite, addr, revision, text)}` for one committed generation."""
    return {
        int(row[0]): (str(row[1]), str(row[2]), int(row[3]), row[4])
        for row in connection.execute(_LIVE_BLOCKS_SQL, (doc_ord, gen_no))
    }


def _clause5(
    path: Path,
    cas: Path,
    *,
    producer_id: int,
    stub: ModuleType,
    gen: ModuleType,
    pdf: Path,
    key: bytes,
    before: Mapping[int, tuple[str, str, int, Any]],
    workspace: Path,
) -> Check:
    """16-roadmap.md:438-440, and the half of it the plan's own definition sites refute.

    The sentence is: *"re-parse the corpus with a one-paragraph edit in each document and watch
    `rebind()` carry every cite except the edited paragraphs', which take a fresh `n` from
    `doc.next_cite_n` and leave a `block_history` row naming their successor."*

    **The first half holds and is checked here:** every cite live at gen 1 is still live at gen 2.

    **The second half does not follow from a paragraph edit, and the plan says so twice.**
    03:1256-1260 is the rule table, and rule 2 is *"equal `addr` and `kind`, digest changed"* --
    its `cite` column reads **carried** and its `revision` column `+= 1`. 03:1345-1358's worked
    example runs exactly this scenario (*"the PDF is re-signed: one paragraph gains a clause"*)
    and reports `p0/2 paragraph rule 2 block_id 4 cite d7#4 revision 1` with `retired = 0`. A
    fresh `n` plus a `block_history` row is rule 3, which fires only when NEITHER the digest NOR
    `addr`+`kind` match; an edited paragraph that keeps its position and its Kind cannot reach it,
    and when a re-parse does reach it at scale 03:1366 calls that the FAILING case, which
    QUARANTINES rather than re-minting.

    So this clause asserts what 03 states -- the edited paragraph carries its cite, its `revision`
    moves to 1, nothing retires and `block_history` stays empty -- which is falsifiable in both
    directions: a matcher that started re-minting would fail it. The divergence from
    16-roadmap.md:438-440 is reported in `deferred`, not smoothed away.

    **`doc_key` is passed unchanged, and that is itself a reported conflict.**
    `0001_init.sql:150` makes `doc_key` *"sha256(NORMALIZED source bytes)[:16]"*, so an edited file
    hashes to a different key and `begin_doc`'s *"insert or look up `doc` by `doc_key`"* (03:576)
    would open a SECOND document at `gen = 1` with no head to rebind against -- yet 03:1316-1370's
    worked example re-parses the same `doc_ord` at `gen = 2` after the source changed. Both cannot
    hold. F2's signature takes `doc_key` as a parameter, so the demo passes the gen-1 key, which
    is what the worked example requires, and names the conflict.
    """
    data = pdf.read_bytes()
    parsed = stub.parse_pdf(data)
    patched_bytes, replacement = _patch_one_paragraph(data, parsed, gen)
    patched = workspace / "edited.pdf"
    patched.write_bytes(patched_bytes)

    record = _ingest(path, cas, producer_id=producer_id, stub=stub, pdf=patched, key=key)
    connection = ow.connect_readonly(path)
    try:
        after = _live_blocks(connection, record.doc_ord, record.gen)
        history = connection.execute(
            "SELECT block_id, retired_gen, superseded_by, reason FROM block_history"
        ).fetchall()
        next_n = int(
            connection.execute(
                "SELECT next_cite_n FROM doc WHERE doc_ord = ?", (record.doc_ord,)
            ).fetchone()[0]
        )
        retired = int(
            connection.execute(
                "SELECT count(*) FROM block WHERE doc_ord = ? AND state = 1", (record.doc_ord,)
            ).fetchone()[0]
        )
    finally:
        connection.close()

    failures: list[str] = []
    if record.gen != SECOND_GEN:
        failures.append(
            f"doc.gen is {record.gen}, not 2: the re-parse quarantined "
            f"(OW_REBIND_UNEXPLAINED, 03:1298-1302)"
        )
    dropped = {row[0] for row in before.values()} - {row[0] for row in after.values()}
    if dropped:
        failures.append(f"{len(dropped)} cite(s) did not carry: {sorted(dropped)[:5]}")
    edited = [
        (block_id, row)
        for block_id, row in after.items()
        if row[3] is not None and EDIT_MARKER in str(row[3])
    ]
    if len(edited) != 1:
        failures.append(
            f"{len(edited)} block(s) carry the edit marker; the patch touched exactly one run"
        )
    else:
        block_id, (cite, addr, revision, _text) = edited[0]
        if block_id not in before:
            failures.append(
                f"the edited paragraph is a NEW block_id {block_id}; 03:1258's rule 2 carries the "
                f"old id and the old cite"
            )
        elif before[block_id][0] != cite:
            failures.append(f"block {block_id} changed cite {before[block_id][0]} -> {cite}")
        elif revision != 1:
            failures.append(
                f"the edited paragraph at {addr} has revision {revision}, not 1 (03:1258)"
            )
    if history:
        failures.append(
            f"{len(history)} block_history row(s) after a text-only edit: {history[:3]}; "
            f"03:1358's worked example reports retired = 0"
        )
    if retired:
        failures.append(f"{retired} block(s) at state = 1 after a text-only edit")
    return Check(
        clause=5,
        title="re-parse with a one-paragraph edit; rebind() carries the cites",
        ok=not failures,
        enforced=(
            f"one body run patched in place ({replacement[: len(EDIT_MARKER)]}...) and "
            f"re-ingested at the same doc_key -> gen {record.gen}: all {len(before)} gen-1 "
            f"cite(s) still live, the edited paragraph carried by rule 2 with revision 1, "
            f"block_history empty, doc.next_cite_n = {next_n}"
        ),
        deferred=(
            "16-roadmap.md:438-440's second half is REFUTED rather than deferred: an edited "
            "paragraph keeps its addr and its Kind, so 03:1256-1260 rule 2 CARRIES its cite and "
            "bumps revision. A fresh n plus a block_history row is rule 3, which needs a "
            "re-segmentation -- 03:1366's FAILING case, which quarantines. Also reported: "
            "doc_key cannot both hash the edited bytes (0001_init.sql:150) and re-open the same "
            "document (03:1316-1370)"
        ),
        notes=(
            f"cites live at gen 1: {len(before)}; at gen 2: {len(after)}; next_cite_n now "
            f"{next_n} -- the carried rows' staged twins leave permanent gaps (03:1157-1159)",
            *_capped(failures),
        ),
    )


# ---------------------------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    """Every flag, in one place."""
    parser = argparse.ArgumentParser(
        description="P2's demo (16-roadmap.md:434-440) as five checks with a PASS/FAIL table."
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=DEFAULT_PAGES,
        help=(
            f"how many pages to generate (default {DEFAULT_PAGES}); --pages 7940 is the first "
            f"count that reaches blocks/{ROADMAP_FRAME:06d}.ndjson"
        ),
    )
    parser.add_argument(
        "--workspace", type=Path, default=None, help="where to build everything; default a tempdir"
    )
    parser.add_argument("--keep", action="store_true", help="keep the workspace on disk")
    parser.add_argument(
        "--kill-points",
        type=int,
        default=1,
        help="how many crash-matrix points clause 4 runs (default 1; G21's PR job draws 3)",
    )
    parser.add_argument(
        "--in-process",
        action="store_true",
        help="clause 4 uses the in-process kill model instead of a real signal (fast, weaker)",
    )
    parser.add_argument(
        "--skip",
        action="append",
        type=int,
        default=[],
        choices=list(CLAUSES),
        metavar="N",
        help="skip clause N; repeatable. A skipped clause is reported, never silently absent",
    )
    return parser


def _timed(check: Check, seconds: float) -> Check:
    """`Check` is frozen, so a duration measured around it is attached rather than mutated."""
    return replace(check, seconds=seconds)


def _run(args: argparse.Namespace, workspace: Path, emit: Emit) -> tuple[list[Check], list[int]]:
    """Every clause, in order, over one store.

    **Clause 5 runs last and the order is load-bearing.** `part` is keyed `(doc_ord, path)` and
    NOT by generation -- `store/doc.py:add_part`: *"a part's identity is its bytes, and a re-parse
    of the same container names the same paths"* -- so the second ingest UPSERTs the edited file
    over the original. Clause 2's INV-10 re-derivation reads exactly those bytes, so running it
    after the re-parse would compare gen-1 offsets against gen-2 bytes and fail for a reason that
    has nothing to do with the store.
    """
    gen = _require(GEN, GEN_PATH, "F1")
    stub = _require(STUB, STUB_PATH, "F2")
    gate = _require(GATE, GATE_CRASH_PATH, "G21's runner")

    skip = set(args.skip)
    checks: list[Check] = []
    emit(f"p2 demo  --pages {args.pages}  workspace {workspace}")
    emit(f"  generator  {GEN_PATH.relative_to(REPO_ROOT).as_posix()}")
    emit(f"  driver     {stub.DRIVER_ID}  port {stub.PORT}  operator {stub.OPERATOR}")
    emit("")

    pdf = Path(gen.generate(workspace / "gen.pdf", pages=args.pages))
    key = hashlib.sha256(pdf.read_bytes()).digest()[:16]
    path, cas, producer_id = _fresh_store(workspace, stub)

    at = time.perf_counter()
    record = _ingest(path, cas, producer_id=producer_id, stub=stub, pdf=pdf, key=key)
    ingested = time.perf_counter() - at

    def clause5() -> Check:
        connection = ow.connect_readonly(path)
        try:
            before = _live_blocks(connection, record.doc_ord, record.gen)
        finally:
            connection.close()
        return _clause5(
            path,
            cas,
            producer_id=producer_id,
            stub=stub,
            gen=gen,
            pdf=pdf,
            key=key,
            before=before,
            workspace=workspace,
        )

    # One thunk per clause, keyed by the roadmap's own numbering. A dispatch table rather than
    # five `if N not in skip:` blocks, so `--skip` reads one clause number against one place and
    # a clause cannot be silently omitted by a missing branch.
    thunks: Mapping[int, Callable[[], Check]] = {
        1: lambda: _clause1(path, record, args.pages, stub, gen),
        2: lambda: _clause2(path, cas, record),
        3: lambda: _clause3(path, cas, workspace / "export", FIXTURE_BLOCKS_PER_PAGE),
        4: lambda: _clause4(
            workspace / "crash", gate, points=args.kill_points, in_process=args.in_process
        ),
        5: clause5,
    }
    for clause in CLAUSES:
        if clause in skip:
            continue
        at = time.perf_counter()
        check = thunks[clause]()
        # Clause 1's cost is the ingest, which ran before any clause could look at it.
        elapsed = ingested if clause == CLAUSES[0] else time.perf_counter() - at
        checks.append(_timed(check, elapsed))
    return checks, sorted(skip)


def _report(checks: Sequence[Check], skipped: Sequence[int], seconds: float, emit: Emit) -> int:
    """The per-clause table and the final line. 0 every clause run held, 1 one did not."""
    emit("")
    emit("  clause  verdict  seconds  assertion")
    for check in checks:
        emit(f"  {check.clause:<6}  {check.verdict():<7} {check.seconds:7.2f}  {check.title}")
        emit(f"          enforced:     {check.enforced}")
        if check.deferred:
            emit(f"          NOT enforced: {check.deferred}")
        for note in check.notes:
            emit(f"          note:         {note}")
    for clause in skipped:
        emit(f"  {clause:<6}  SKIPPED          --skip {clause} was passed")
    emit("")
    failed = [check for check in checks if not check.ok]
    emit(f"p2 demo  {len(checks)} clause(s) run, {len(skipped)} skipped, in {seconds:.1f}s")
    if failed:
        emit(
            f"p2 demo FAIL  clause(s) {', '.join(str(c.clause) for c in failed)} did not hold. "
            f"16-roadmap.md:434-440 is the specification."
        )
        return EXIT_FAIL
    emit(
        "p2 demo ok  every clause run held. The NOT-enforced lines above say which half of "
        "clauses 1-4 this phase can reach; clause 5's second half is refuted by 03:1256-1260."
    )
    return EXIT_CLEAN


def main(argv: list[str] | None = None, *, out: TextIO | None = None) -> int:
    """Run the five clauses and report. 0 all held, 1 one did not, 2 the demo did not run."""
    emit = _emitter(sys.stdout if out is None else out)
    args = _parser().parse_args(argv)
    if args.pages < 1:
        emit(f"p2 demo DID NOT RUN  --pages {args.pages} is below 1")
        return EXIT_NOT_RUN
    if args.kill_points < 1:
        emit(f"p2 demo DID NOT RUN  --kill-points {args.kill_points} is below 1")
        return EXIT_NOT_RUN

    owned = args.workspace is None
    workspace = Path(tempfile.mkdtemp(prefix="ow-p2-demo-")) if owned else args.workspace
    started = time.perf_counter()
    try:
        workspace.mkdir(parents=True, exist_ok=True)
        checks, skipped = _run(args, workspace, emit)
    except (MissingContractError, ValueError, KeyError, OSError) as exc:
        emit(f"p2 demo DID NOT RUN  {type(exc).__name__}: {exc}")
        return EXIT_NOT_RUN
    finally:
        if owned and not args.keep:
            shutil.rmtree(workspace, ignore_errors=True)
    return _report(checks, skipped, time.perf_counter() - started, emit)


if __name__ == "__main__":
    raise SystemExit(main())
