"""The shared half of a `parse/1` driver target: activate once, then feed it bytes.

14-security.md:477 asks for "`fuzz/`, **one target per format handler**, nightly, seeded from
`anydoc/fuzz/seeds/`", and at P3 this repository has two format handlers -- `parse.office.anydoc`
and `parse.pdf.pdfium`. `office.py` and `pdf.py` are those two targets; everything they have in
common is here, because two copies of a driver-activation loop is two places for it to drift.

## The property

03-document-model.md:3012 (P28) states it at the row grain and 04-driver-system.md:2082 states it
at the suite grain: **a corrupt fixture yields `status='partial'` with `Diag` rows, or a typed
`DriverError` from the closed `FailureClass`; a crash is allowed (one unit), a hang is not.**

So `allowed` is `DriverError`, plus `RecursionError` and `MemoryError` -- the two Python exceptions
that stand in for the crash a host is specified to survive. 04-driver-system.md:2089 is the reason
the crash is allowed at all: "the host already handles a crash as one row and it cannot handle a
hang without a deadline", which is also the whole argument for `subproc` being affordable.
Everything else -- `IndexError`, `struct.error`, `KeyError`, `UnicodeDecodeError`, a bare
`ValueError` -- is a finding, because every one of them is an untyped escape that
`omniweave/run/dispatch.py` would have to guess the `FailureClass` for.

## Why `media_type` is `None`, and the one gap that leaves

libFuzzer hands a target bytes and nothing else. There is no sidecar, no filename and no routing
decision, which is exactly the position a host is in when content sniffing is all it has -- so
these targets pass `media_type=None` rather than inventing a routed type per corpus directory.
That is not a limitation in practice: measured against `parse.office.anydoc`'s own sixteen
fixtures, thirteen parse or refuse identically with the type absent, because anydoc's frontend
"picks the reader from the bytes" (`vendor/anydoc/fuzz/README.md`).

The exceptions are worth naming rather than leaving to be discovered. `rows.csv` becomes
`unsupported_format`, and that is the card's own disclosure -- CSV "carries no signature and
cannot be detected from content by anyone" (`harness.Fixture.media_type`). `memo.doc` becomes
`corrupt_input` for the same reason one layer down. So the CSV and legacy-`.doc` readers are
reachable from the conformance `fuzz` suite, which has the sidecars, and not from here. Two
mechanisms with different reach over one property is the arrangement; a target that faked a
routing decision would be fuzzing the fake.

## Why the corpus is the seeds AND the driver's own fixtures

04-driver-system.md:2094: "a driver whose format overlaps those seeds gets them for free". *Free*
is in addition to, not instead of -- `vendor/anydoc/fuzz/seeds/` holds four corpora, all
spreadsheets, and a target seeded from those alone would fuzz three readers out of twelve and
none at all on the PDF path, where anydoc ships a `pdf.rs` target with no checked-in seeds.

The driver's own fixture directory is a *starting* corpus and not a golden one: nothing here reads
an expected value out of it. 13-quality.md:166's rule is about where crash artefacts land -- "a
fuzz crash never lands in `fixtures/regressions/`" -- and it is not a rule about what a target may
read.

Specified in 14-security.md:477-481, 04-driver-system.md section 8.2 (:2082-2094),
03-document-model.md:3012 and 16-roadmap.md:520.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))

# `_harness` is the sibling the line above reaches, and importing it is also what puts
# `packages/*/src` on the path for everything below.
from _harness import REPO, SEEDS, Target, UnavailableError
from omniweave_conform.harness import Fixture, MemoryBlobStore, run_parse
from omniweave_conform.subject import Subject
from omniweave_ports.types import DriverError

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["ALLOWED", "parse_target"]

ALLOWED: Final[tuple[type[BaseException], ...]] = (DriverError, RecursionError, MemoryError)
"""What a malformed input is allowed to produce. See the module docstring's first section.

`RecursionError` and `MemoryError` are here as the in-process stand-ins for the crash P28 allows:
under a real host both would have been a dead worker, one `driver_crashed` row and a retry at
`batch = 1`. In a library that may not spawn, catching them is the closest thing to surviving one.
"""


class _State:
    """The activated driver, and the scratch directory its runs write into.

    A module-level singleton because `atheris.Fuzz()` calls the probe millions of times and
    activating a driver per input would measure `importlib` rather than the parser. It is also
    what makes the `--replay` timing budget mean anything: a five-second budget that included
    activation would be a budget on the kit.
    """

    def __init__(self) -> None:
        self.driver: object | None = None
        self.scratch: Path | None = None
        self.calls = 0


def parse_target(
    name: str,
    *,
    card: Path,
    fixtures: Path,
    seeds: Sequence[str] = (),
) -> Target:
    """One `parse/1` driver as a fuzz target.

    `card` and `fixtures` are repo-relative. `seeds` names subdirectories of `fuzz/seeds/` whose
    format this driver claims -- the mirrored half of the corpus, and empty for a driver whose
    format `vendor/anydoc` ships no seeds for.
    """
    state = _State()

    def setup() -> None:
        card_path = REPO / card
        if not card_path.is_file():
            raise UnavailableError(f"no card at {card}")
        try:
            subject = Subject.of(card_path, fixtures_dir=None, workdir=Path(tempfile.mkdtemp()))
            state.driver = subject.instantiate()
        except ImportError as exc:
            raise UnavailableError(
                f"{name}: the driver's distribution is not importable here ({exc}). "
                f"`uv sync --frozen --all-packages --group dev` installs every workspace member."
            ) from exc
        state.scratch = Path(tempfile.mkdtemp(prefix=f"ow-fuzz-{name}-"))

    def probe(data: bytes) -> None:
        if state.driver is None or state.scratch is None:
            raise UnavailableError(f"{name}: setup() did not run")
        state.calls += 1
        # A fresh run directory per input, and REMOVED afterwards. Fresh, because `run_parse`
        # seeds a new `MemoryBlobStore` and a new `KitIO` into it and that is what keeps one
        # input's state out of the next one's parse (`harness.run_parse`'s own docstring, for the
        # same reason `idempotence` gets a fresh pair). Removed, because `atheris.Fuzz()` calls
        # this millions of times and `MemoryBlobStore.path()` writes a real file -- a target that
        # left them behind would fill a disk and report it as a hang.
        run = state.scratch / f"run-{state.calls}"
        try:
            run_parse(
                state.driver,
                Fixture(
                    # Absolute and never created: `UnitRef.uri` is a `file:` URI and `as_uri()`
                    # refuses a relative path, but nothing reads the file -- the bytes are
                    # already in hand and travel through the blob store.
                    path=state.scratch / "input.bin",
                    data=data,
                    digest=MemoryBlobStore.digest_of(data),
                    media_type=None,
                ),
                run,
            )
        finally:
            shutil.rmtree(run, ignore_errors=True)

    corpora: list[tuple[str, Path]] = [(f"seeds/{seed}", SEEDS / seed) for seed in seeds]
    corpora.append((f"{Path(fixtures).parent.name}/fixtures", REPO / fixtures))
    return Target(
        name=name,
        probe=probe,
        allowed=ALLOWED,
        corpora=tuple(corpora),
        setup=setup,
    )
