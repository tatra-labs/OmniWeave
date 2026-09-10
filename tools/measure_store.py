"""Measure `store.bytes_per_block` against a real store. P2's one honestly-closable exit number.

16-roadmap.md:434-440 makes P2's demo *"ingest `gen_5000p_pdf` output through a STUB `parse/1`
driver"*, and 17-risks.md:290 calls DP8 *"the earliest a measurement can run against a real
STORE"*. This is that measurement: generate the fixture, ingest it through the stub driver, and
print 07-store-and-retrieval.md:1021-1037's decomposition with a MEASURED column beside the
plan's ESTIMATED one. `omniweave_core.store.inspect.store_sizing` does the arithmetic; everything
here is the part a library may not do -- run a generator, drive an ingest, read a register file,
and print.

## Why a `tools/` script and not `ow store sizing`

D25's standing pattern, already applied to `ow store verify` (`store/verify.py` +
`tools/gate_crash.py`) and to `ow schema emit` (`tools/schemagen.py` at P1, before `ow` existed):
BUILD THE LIBRARY FUNCTION PLUS A `tools/` SCRIPT NOW and let P7 or P10 wrap it. `ow eval perf`
is W10.6 and the Pacer is W10.4; neither exists at P2 and neither is needed to take a
measurement. `tools/gate_crash.py`'s docstring is the worked example and this file is its
sibling.

## THE FOUR THINGS THIS SCRIPT REFUSES TO CLAIM

**1. It never says a budget was met.** 12-performance.md:1966 makes `ow-bench-1` the ONLY machine
a `[[budget]]` may live on, because it is the only one with a Pacer baseline. This script prints
the measured figure, prints `eval/perf.toml`'s `store.bytes_per_block` row beside it, and prints
whether the row is BREACHED -- labelled INDICATION, on the same line, with the machine caveat
under it. Breached and not "outside tolerance": this row carries `ratchet = true`, 12-performance
.md:244 spells that as *"it may fall and never rise"* and :1655 as *"cannot be raised at all"*, so
the band is one-sided and a figure BELOW it is the direction the ratchet is for. It writes no
baseline, and its exit code is 0 for a measurement that
ran no matter what the number was, unless `--gate` is passed by a caller who has decided the
machine is entitled to that (and even then the output still says what the exit code means).

**2. It does not check `rss.gen5000p_peak_bytes`.** Ruling D26: that row *"fires
`vendor/anydoc/FORK-TRIGGER.md`"* (12-performance.md:245) and anydoc is W3.4, which is P3. There
is no anydoc in this process, so a peak-RSS figure measured here bounds a different program than
the one the row is a tripwire for. Peak RSS is printed, labelled INFORMATIONAL, with the phase
that owns the budget named -- and it is NOT compared to 1,610,612,736.

**3. The blocks-per-page figure is a property of the fixture.** Ruling D27 splits F1:
bytes-per-block is the store variable and closes here; blocks-per-page is the corpus variable and
03-document-model.md:3086 says what closes it -- the generator PLUS ten real 200-page documents,
which need W3.4/W3.5 drivers and are P3. `SizingReport.render()` prints the qualification on the
same line as the number.

**4. A single bytes-per-block number is nearly meaningless on its own.** 07:1023: *"A prose
paragraph is ~300 B; a table cell is ~10 B. The 60-120 blocks/page envelope is that wide **because
cells are Blocks**."* So the report carries contract F4's three-way split -- prose, cells, mixed --
and this script additionally measures the store's FIXED FLOOR (a migrated store with no documents
in it: four migrations, seventy-six indexes, two FTS5 shadow families) and prints bytes/block with
that floor removed. At 15 blocks the floor is 99% of the file; at 400,000 it is noise, and a
reader who cannot see which regime a number came from cannot use it.

## Exit codes

0 the measurement ran, 1 only under `--gate` and only when the row is BREACHED (for a ratchet
that means above the ceiling only, never below the band), 2 the measurement did not run -- the
generator or the stub driver is absent, the ingest raised, or
`eval/perf.toml` could not be read. 1 and 2 are distinguished because a human needs to know
whether a number was produced.

Specified in 16-roadmap.md:434-440 and :452-460, 12-performance.md:207-233 and :244,
07-store-and-retrieval.md:1005-1037, 13-quality.md:586-589 and 17-risks.md:290.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.util
import shutil
import sys
import tempfile
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType, ModuleType
from typing import Any, Final, TextIO

from omniweave_core.blobs import BlobStore
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_core.store.doc import DocSink
from omniweave_core.store.inspect import MACHINE_CAVEAT, SizingReport, store_sizing

try:  # POSIX only. Windows has no `resource` module; `_peak_rss` uses psapi there instead.
    import resource
except ImportError:  # pragma: no cover -- taken on Windows, which is where P2 is being built
    resource = None  # type: ignore[assignment]

__all__ = [
    "BUDGET_ID",
    "DEFAULT_PAGES",
    "EXIT_CLEAN",
    "EXIT_FAIL",
    "EXIT_NOT_RUN",
    "GENERATOR",
    "NOW_NS",
    "STUB_DRIVER",
    "Budget",
    "Emit",
    "Measurement",
    "load_budget",
    "main",
    "measure",
]

EXIT_CLEAN = 0
EXIT_FAIL = 1
EXIT_NOT_RUN = 2

ROOT: Final = Path(__file__).resolve().parents[1]
"""The repository root, by absolute path, from this file rather than from the cwd.

`tools/gate_crash.py`'s `SELF` records the same decision for the same reason: a script invoked as
`tools/measure_store.py` from another directory must still find `fixtures/gen/`.
"""

GENERATOR: Final = ROOT / "fixtures" / "gen" / "gen_5000p_pdf.py"
"""Contract F1's generator. 13-quality.md:586-589 puts it here, its output in
`fixtures/generated/` (gitignored) and its digest in `fixtures/gen/EXPECTED.sha256`."""

STUB_DRIVER: Final = ROOT / "tools" / "p2_stub_parse.py"
"""Contract F2's stub `parse/1` driver -- 16-roadmap.md:434's *"a STUB parse/1 driver"*."""

PERF_TOML: Final = ROOT / "eval" / "perf.toml"
"""The `[[budget]]` register (12-performance.md section 2.4). Read, never written, never
second-guessed: 660 is transcribed there from charter.md:7617-7622 and nowhere else in this tree
(`store/inspect.py`'s `TOTAL_ESTIMATE` docstring says why it is not also a library constant)."""

BUDGET_ID: Final = "store.bytes_per_block"
"""12-performance.md:244. The one row this script has anything to say about."""

DEFAULT_PAGES: Final = 5_000
"""Contract F1's `DEFAULT_PAGES`, restated so `--pages` has a default when the generator is
absent and the script has to report that it did not run."""

NOW_NS: Final = 1_757_400_000_000_000_000
"""The injected wall clock. `time.time` is banned in library code and every store clock is a
parameter, so the fixture store stamps its migration ledger with a constant -- which is part of
why two runs of this script produce byte-identical stores and therefore comparable sizes."""

DOC_URI: Final = "file:///fixtures/generated/gen.pdf"
"""The document's URI in the measured store. A constant and not the real path, so the store's
`doc.uri` column -- and therefore its size -- does not depend on where the workspace landed."""

Emit = Callable[[str], None]
"""One line of the report. `print` is banned repo-wide by ruff `T20`; this needs no waiver."""


def _emitter(out: TextIO) -> Emit:
    """Bind the report to a stream, so `main(out=...)` is testable without capturing stdout."""

    def emit(line: str) -> None:
        out.write(line + "\n")

    return emit


# ---------------------------------------------------------------------------------------------
# 1. The register. `eval/perf.toml` owns 660; this script reads it and does not restate it.
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Budget:
    """One `[[budget]]` row, as 12-performance.md:207-233's schema defines it.

    Only the four keys this script uses are lifted out; the rest of the row (`gate`, `process`,
    `note`, `ratchet`) is carried in `row` untouched, because a script that re-typed the schema
    would become a second definition site for it. `tools/gate_budgets.py` (Q-G15) is the file
    that validates the whole schema, and it is not this one.
    """

    id: str
    value: float
    tol_pct: int | None
    tol_abs: float | None
    row: MappingProxyType[str, Any]

    @property
    def tolerance(self) -> float:
        """The row's tolerance as an absolute figure in the row's own unit.

        `tol_pct` and `tol_abs` are *"mutually exclusive and exactly one is required"*
        (12-performance.md:216-217). `store.bytes_per_block` carries `tol_pct = 10`.
        """
        if self.tol_abs is not None:
            return float(self.tol_abs)
        return abs(self.value) * float(self.tol_pct or 0) / 100.0

    @property
    def ratchet(self) -> bool:
        """Does this row carry `ratchet = true`?

        Read off `row` rather than lifted into a field, for the reason the class docstring gives:
        `tools/gate_budgets.py` is the schema's validator and this script is not a second one.
        """
        return bool(self.row.get("ratchet", False))

    def within(self, measured: float) -> bool:
        """Is `measured` inside `value ± tolerance`? **An indication, never a verdict.**

        Two-sided, and therefore NOT the question a ratchet asks. See `breaches`.
        """
        return abs(measured - self.value) <= self.tolerance

    def breaches(self, measured: float) -> bool:
        """Would `measured` fail this row? **An indication, never a verdict.**

        **A RATCHET'S TOLERANCE IS ONE-SIDED, and this is the whole reason the method exists.**
        12-performance.md:244 spells `store.bytes_per_block` as *"a ratchet: it may fall and never
        rise"*, and :1655 says it *"cannot be raised at all"*. So for a ratchet the only breach is
        `measured > value + tolerance`; a figure below `value - tolerance` is the outcome the
        ratchet is FOR, and the correct response to it is to ratchet the register down -- which is
        a `nightly` job's write on ow-bench-1, never this script's.

        Reporting a low ratchet as "outside tolerance" was this file's own first defect. It read as
        a failure, on a line whose next line says a breach of this row cannot be raised away, so a
        reader had no way to tell an over-budget store from a store that had just got smaller. That
        is the same shape as the plan defects this wave is recording, committed in our own output.
        """
        if self.ratchet:
            return measured > self.value + self.tolerance
        return not self.within(measured)

    def describe(self) -> str:
        """`<value> +/- <tol>% (<absolute>)`, for the report line.

        The row's own numbers, formatted; no example is written out here, because a literal in a
        docstring is exactly the second home for the register's value that `PERF_TOML` exists to
        prevent (and `test_the_measurement_script_reads_660_from_the_register...` greps for it).
        """
        if self.tol_abs is not None:
            return f"{self.value:g} +/- {self.tol_abs:g} absolute"
        return f"{self.value:g} +/- {self.tol_pct}% ({self.tolerance:g})"


def load_budget(path: Path, budget_id: str) -> Budget:
    """Read one `[[budget]]` row out of `eval/perf.toml`, or raise `LookupError` naming what.

    Raising rather than falling back to a literal 660 is the point (see the module docstring and
    12-performance.md section 2.4): the register is the transcription of charter.md:7617-7622 and
    a second copy in a script is a second thing to keep in step. A missing register means the
    measurement can still be TAKEN -- and it is, and printed -- but the comparison cannot be made,
    and the script says which of the two happened.
    """
    if not path.exists():
        raise LookupError(f"{path} does not exist; it is W10.4 and 12-performance.md:207 owns it")
    rows = tomllib.loads(path.read_text(encoding="utf-8")).get("budget", [])
    for row in rows:
        if row.get("id") == budget_id:
            return Budget(
                id=str(row["id"]),
                value=float(row["value"]),
                tol_pct=None if row.get("tol_pct") is None else int(row["tol_pct"]),
                tol_abs=None if row.get("tol_abs") is None else float(row["tol_abs"]),
                row=MappingProxyType(dict(row)),
            )
    raise LookupError(f"{path} has no [[budget]] row with id = {budget_id!r}")


# ---------------------------------------------------------------------------------------------
# 2. The two P2 scripts this one drives. Both are files, not packages; both may not exist yet.
# ---------------------------------------------------------------------------------------------


def _load_script(path: Path, name: str) -> ModuleType:
    """Import a `tools/`- or `fixtures/`-level script BY PATH, as a module.

    Neither `fixtures/gen/gen_5000p_pdf.py` nor `tools/p2_stub_parse.py` is inside a package, so
    there is no dotted name to import. `importlib.util.spec_from_file_location` is the stdlib
    answer, and the ban it might look like it violates does not reach here: `tools/` is not
    library code (`tools/gate_semgrep.py:26-37` takes that reading for itself in as many words),
    and the rule at 07's INV-4 / DR19 is on `importlib.import_module` *"outside
    `omniweave_core/host/`*", enforced by a semgrep rule whose `paths.include` is
    `packages/*/src/**` only.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover -- a path that is not a .py file
        raise ImportError(f"{path} could not be loaded as a module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _under_root(path: Path) -> str:
    """`path` relative to the repo root when it is under it, and its full text when it is not.

    A test may point `GENERATOR` somewhere else entirely to exercise the absent path, and a
    report that raised `ValueError` while explaining that a file was missing would be the worse
    of the two failures.
    """
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _missing(paths: dict[str, Path]) -> tuple[str, ...]:
    """Which of the named P2 artefacts are not on disk yet, in the order they would be used."""
    return tuple(
        f"{label} ({_under_root(path)})" for label, path in paths.items() if not path.exists()
    )


# ---------------------------------------------------------------------------------------------
# 3. Building the store
# ---------------------------------------------------------------------------------------------


def _new_store(path: Path) -> int:
    """A fresh `.owstore` with the four migrations applied and one `producer` row. Returns its id.

    The producer's `operator` and `op_version` are the stub driver's own (contract F2's
    `OPERATOR` and `OP_VERSION`) rather than invented here, so the `producer` row the blocks
    point at describes the thing that actually produced them.
    """
    driver = _load_script(STUB_DRIVER, "ow_p2_stub_parse")
    connection = ow.connect(path)
    try:
        migrate.apply_pending(connection, now_ns=NOW_NS)
        cursor = connection.execute(
            "INSERT INTO producer(operator, op_version, code_fingerprint, options_digest) "
            "VALUES(?, ?, ?, X'00')",
            (driver.OPERATOR, driver.OP_VERSION, driver.DRIVER_ID),
        )
        connection.commit()
        return int(cursor.lastrowid or 0)
    finally:
        connection.close()


def _fixed_floor(workspace: Path) -> int:
    """Bytes of a migrated store with no document in it. The measurement's zero point.

    A `.owstore` is not empty at zero blocks: four migrations, seventy-six indexes, two FTS5
    shadow families, `enum_val`'s vocabulary and the migration ledger are all there before the
    first block arrives. That cost is per-STORE and 07:1039-1040 is explicit that costs which are
    *"not per-block ... reporting them inside it would hide them"*. So it is measured here, on the
    same machine and the same SQLite build, and subtracted in one of the two figures printed --
    never in both, because which of the two a reader wants depends on whether they are sizing a
    corpus (include it) or attacking 07:1021-1037's row list (exclude it).
    """
    path = workspace / "floor.owstore"
    _new_store(path)
    return path.stat().st_size


def _ingest(store: Path, pdf: Path, cas: Path) -> float:
    """Ingest `pdf` into `store` through the stub driver. Returns the wall seconds it took.

    `time.perf_counter` is read here and not in library code; a `tools/` runner is where a clock
    is allowed to be ambient, and the number it produces is reported as elapsed time and is not
    a Budget (there is no `[[budget]]` row for ingest wall time at P2).
    """
    driver = _load_script(STUB_DRIVER, "ow_p2_stub_parse")
    producer_id = _new_store(store)
    doc_key = hashlib.blake2b(DOC_URI.encode("utf-8"), digest_size=16).digest()
    started = time.perf_counter()
    with ow.StoreThread(lambda: ow.connect(store)) as thread:
        sink = DocSink(
            thread,
            producer_id=producer_id,
            origin_operator=driver.OPERATOR,
            origin_driver=driver.DRIVER_ID,
            driver_schema_v=driver.DRIVER_SCHEMA_V,
            blobs=BlobStore(cas),
        )
        driver.ingest(sink, pdf=pdf, uri=DOC_URI, doc_ord=0, doc_key=doc_key)
    return time.perf_counter() - started


# ---------------------------------------------------------------------------------------------
# 4. Peak RSS -- INFORMATIONAL. Ruling D26; see the module docstring.
# ---------------------------------------------------------------------------------------------

_RSS_DEFERRED: Final = (
    "INFORMATIONAL, not a budget: rss.gen5000p_peak_bytes (12-performance.md:245) fires "
    "vendor/anydoc/FORK-TRIGGER.md, anydoc is W3.4 = P3, and no anydoc ran in this process"
)
"""Printed under every peak-RSS figure. Ruling D26 in one sentence, with the line that fixes it."""


class _WinCounters(ctypes.Structure):
    """`PROCESS_MEMORY_COUNTERS` (psapi.h). `SIZE_T` is `c_size_t`, which is pointer-width.

    Declared rather than reached for through a dependency because 12-performance.md's RSS rows
    are measured, at P10, by the Pacer, and this script needs one number on one machine today.
    `psutil` is not a dependency of this repo and G9 (zero third-party modules in core) is the
    reason it will not become one for a `tools/` convenience.
    """

    _fields_ = (
        ("cb", ctypes.c_uint32),
        ("PageFaultCount", ctypes.c_uint32),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    )


def _peak_rss() -> tuple[int | None, str]:
    """`(bytes, how it was obtained)`, or `(None, why not)`. Never raises.

    Three platforms, three units, and the unit is the part that is easy to get wrong: Linux's
    `ru_maxrss` is KILOBYTES, macOS's is BYTES, and Windows has no `getrusage` at all and reports
    `PeakWorkingSetSize` through psapi in bytes. A figure printed without saying which of the
    three produced it is a figure a reader cannot check, so the source string is returned with it
    and printed on the same line.
    """
    if sys.platform == "win32":
        counters = _WinCounters()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        # `restype` and `argtypes` are set explicitly because ctypes defaults `restype` to
        # `c_int`: on 64-bit Windows that TRUNCATES the HANDLE `GetCurrentProcess` returns, and
        # `GetProcessMemoryInfo` then fails with a perfectly plausible zero rather than raising.
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.GetCurrentProcess.argtypes = []
        get_info = getattr(kernel32, "K32GetProcessMemoryInfo", None)
        if get_info is None:  # pragma: no cover -- pre-Windows-7 puts it in psapi.dll only
            get_info = ctypes.windll.psapi.GetProcessMemoryInfo  # type: ignore[attr-defined]
        get_info.restype = ctypes.c_int
        get_info.argtypes = [ctypes.c_void_p, ctypes.POINTER(_WinCounters), ctypes.c_uint32]
        if not get_info(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            return (None, f"GetProcessMemoryInfo failed, GetLastError {kernel32.GetLastError()}")
        return (int(counters.PeakWorkingSetSize), "K32GetProcessMemoryInfo PeakWorkingSetSize")
    if resource is None:  # pragma: no cover -- neither Windows nor POSIX
        return (None, "no `resource` module and not win32")
    raw = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if sys.platform == "darwin":  # pragma: no cover -- not the machine P2 is built on
        return (raw, "getrusage ru_maxrss (bytes, darwin)")
    return (raw * 1024, "getrusage ru_maxrss (KiB on linux, scaled to bytes)")  # pragma: no cover


# ---------------------------------------------------------------------------------------------
# 5. The measurement
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Measurement:
    """Everything one run produced. No verdict field -- see the module docstring's point 1."""

    pages: int
    pdf: Path
    pdf_bytes: int
    pdf_sha256: str
    ingest_seconds: float
    floor_bytes: int
    report: SizingReport
    peak_rss: int | None
    peak_rss_source: str

    @property
    def bytes_per_block_above_floor(self) -> float:
        """`(database bytes - the empty store's bytes) / blocks`. See `_fixed_floor`."""
        blocks = self.report.blocks
        if blocks == 0:
            return 0.0
        return max(self.report.files.db_bytes - self.floor_bytes, 0) / blocks


def measure(workspace: Path, *, pages: int, out: Path | None) -> Measurement:
    """Generate, ingest, size. Raises on any failure; `main` turns that into exit 2."""
    generator = _load_script(GENERATOR, "ow_gen_5000p_pdf")
    pdf = generator.generate(out or generator.default_out(pages), pages=pages)
    data = Path(pdf).read_bytes()

    store = workspace / "measured.owstore"
    cas = workspace / "cas"
    cas.mkdir(parents=True, exist_ok=True)
    seconds = _ingest(store, Path(pdf), cas)
    floor = _fixed_floor(workspace)

    connection = ow.connect(store)
    try:
        report = store_sizing(connection, path=store)
    finally:
        connection.close()
    peak, source = _peak_rss()
    return Measurement(
        pages=pages,
        pdf=Path(pdf),
        pdf_bytes=len(data),
        pdf_sha256=hashlib.sha256(data).hexdigest(),
        ingest_seconds=seconds,
        floor_bytes=floor,
        report=report,
        peak_rss=peak,
        peak_rss_source=source,
    )


# ---------------------------------------------------------------------------------------------
# 6. Reporting
# ---------------------------------------------------------------------------------------------


def _report_indication(m: Measurement, budget: Budget | None, reason: str, emit: Emit) -> bool:
    """Print the `store.bytes_per_block` comparison. Returns True when the row is NOT breached.

    Not "inside tolerance", because `store.bytes_per_block` carries `ratchet = true` and a
    ratchet's tolerance is ONE-SIDED -- see `Budget.breaches`. A figure below the band is the
    outcome the ratchet exists to produce, so it must not read, or exit, as a failure.

    Returns True as well when there is no register row to compare against, because "nothing said
    it was wrong" is what an absent comparison means and a caller using `--gate` must not fail on
    a file this wave has not written yet. The absence is printed, loudly, on its own line.
    """
    measured = m.report.bytes_per_block
    above = m.bytes_per_block_above_floor
    emit("")
    emit(f"{BUDGET_ID}")
    emit(f"  measured           {measured:>12.2f}  B/block  (database file / blocks)")
    emit(
        f"  above fixed floor  {above:>12.2f}  B/block  "
        f"(minus the {m.floor_bytes:,} B an empty migrated store costs)"
    )
    if budget is None:
        emit(f"  register           UNREADABLE  {reason}")
        emit("  no comparison was made. The measurement above still stands.")
        return True
    breached = budget.breaches(measured)
    emit(f"  register           {budget.describe()}  from {_under_root(PERF_TOML)}")
    if budget.ratchet:
        # A ratchet is one-sided: only the upper bound is a breach (12-performance.md:244, :1655).
        # Print WHICH side the figure fell on, because "inside/outside" cannot say it: below the
        # band and above it are the opposite outcomes on this row, not two flavours of the same one.
        where = (
            "ABOVE the ceiling -- a breach"
            if breached
            else (
                "BELOW the band -- the direction a ratchet is for; the register may be ratcheted "
                "DOWN to it (a nightly write on ow-bench-1, never this script's)"
                if measured < budget.value - budget.tolerance
                else "inside the band"
            )
        )
        emit(f"  INDICATION         ratchet, {where}")
    else:
        emit(f"  INDICATION         {'OUTSIDE' if breached else 'inside'} tolerance")
    emit(f"  {MACHINE_CAVEAT}.")
    emit(
        "  This run is on "
        f"{sys.platform}, not ow-bench-1, and has no Pacer baseline. Nothing above is a "
        "budget verdict and no baseline was written."
    )
    return not breached


def _report(m: Measurement, budget: Budget | None, reason: str, emit: Emit) -> bool:
    """The whole report. Returns the indication, which only `--gate` turns into an exit code."""
    emit(f"measure-store  {m.pages:,}-page fixture")
    emit("")
    emit("1. fixture")
    emit(f"   {_under_root(GENERATOR)} --pages {m.pages}")
    emit(f"   -> {_under_root(m.pdf)}")
    emit(f"   {m.pdf_bytes:,} B   sha256 {m.pdf_sha256}")
    emit("")
    emit("2. ingest")
    emit(f"   {_under_root(STUB_DRIVER)}  ->  measured.owstore")
    emit(f"   {m.ingest_seconds:.2f} s wall (elapsed time, not a [[budget]] row)")
    emit("")
    emit("3. sizing")
    for line in m.report.render().rstrip("\n").split("\n"):
        emit(f"   {line}")
    unbreached = _report_indication(m, budget, reason, emit)
    emit("")
    emit("rss.gen5000p_peak_bytes")
    if m.peak_rss is None:
        emit(f"  peak RSS           unavailable: {m.peak_rss_source}")
    else:
        emit(f"  peak RSS           {m.peak_rss:>12,} B  via {m.peak_rss_source}")
    emit(f"  {_RSS_DEFERRED}.")
    emit("  Owned by P3. Not compared to 1,610,612,736 here, because the comparison would be")
    emit("  against a program that does not contain the thing the row exists to trip on.")
    return unbreached


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="measure_store.py",
        description=(
            "Measure store.bytes_per_block against a real store built from the P2 fixture. "
            "Produces a MEASUREMENT, never a budget verdict (12-performance.md:1966)."
        ),
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=DEFAULT_PAGES,
        help=f"pages in the generated fixture (default {DEFAULT_PAGES}, contract F1)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="where to write the fixture PDF; default fixtures/generated/gen_<pages>p.pdf",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="where to build the stores; default a tempdir, removed unless --keep",
    )
    parser.add_argument("--keep", action="store_true", help="keep the measured store on disk")
    parser.add_argument(
        "--gate",
        action="store_true",
        help=(
            "exit 1 when the indication is outside tolerance. OFF by default: only ow-bench-1 "
            "may hold a Budget (12-performance.md:1966), so on any other machine this flag "
            "turns a measurement into an exit code that does not mean what CI will read it as"
        ),
    )
    return parser


def main(argv: list[str] | None = None, *, out: TextIO | None = None) -> int:
    """Generate, ingest, size, report. 0 measured, 1 only under `--gate`, 2 did not run."""
    emit = _emitter(sys.stdout if out is None else out)
    args = _parser().parse_args(argv)

    absent = _missing({"the generator": GENERATOR, "the stub parse/1 driver": STUB_DRIVER})
    if absent:
        emit(f"measure-store DID NOT RUN  absent: {', '.join(absent)}")
        emit("  Both are P2 stage C artefacts (contracts F1 and F2); an integration pass writes")
        emit(
            "  them. Nothing was measured and no number below this line would have meant anything."
        )
        return EXIT_NOT_RUN

    budget: Budget | None = None
    reason = ""
    try:
        budget = load_budget(PERF_TOML, BUDGET_ID)
    except (LookupError, OSError, tomllib.TOMLDecodeError) as exc:
        reason = str(exc)

    owned = args.workspace is None
    workspace = Path(tempfile.mkdtemp(prefix="ow-sizing-")) if owned else args.workspace
    try:
        workspace.mkdir(parents=True, exist_ok=True)
        measurement = measure(workspace, pages=args.pages, out=args.out)
    except (OSError, ValueError, ImportError, AttributeError, RuntimeError) as exc:
        emit(f"measure-store DID NOT RUN  {type(exc).__name__}: {exc}")
        return EXIT_NOT_RUN
    finally:
        if owned and not args.keep:
            shutil.rmtree(workspace, ignore_errors=True)

    unbreached = _report(measurement, budget, reason, emit)
    if args.gate and not unbreached:
        emit("")
        emit("measure-store EXIT 1  --gate was passed and the row is BREACHED.")
        emit("  That is this flag's contract and not a statement about the budget.")
        return EXIT_FAIL
    return EXIT_CLEAN


if __name__ == "__main__":
    raise SystemExit(main())
