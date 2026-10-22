"""The redaction canary's hostile drivers: page text held in a frame, then a fault. G29, D936.

15-observability.md:1447 (section 8.3): *"`tests/test_no_content_in_artefacts.py` ingests a
fixture corpus whose every page contains the canary `OWCANARY-7f3a91`, runs a full ingest with a
forced driver crash, a forced budget denial, a forced quarantine and a forced exception inside a
driver frame that holds page text in a local, then greps **every** produced artefact"*.

Two of the four faults are a driver's to force, and these are they:
- **`BugParser`** binds the page to `page_text` and calls `int(page_text)`, so the exception's
  args are the page itself (D934's leak path).
- **`CrashParser`** binds it, writes it to stderr, the channel 15:1371 makes the ring tail, and
  ends the worker with no frame.

Neither is registered as an entry point, so no catalog lists them until a project card names
one: G29 copies the template's card under `.omniweave/drivers/` and routes a format to it with a
`.omniweave/policy.d` rule (D935). The code is here, in an installed distribution, because a
worker imports nothing from `PYTHONPATH` (`subproc.SpawnRequest.env`).

Specified in 15-observability.md section 8.3 and 11-repo-layout.md section 6.4's G29 row.
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING, Final, NoReturn

from omniweave_conform.template.driver import PlainTextParser

if TYPE_CHECKING:
    from omniweave_ports import DriverIO, PartSelector, UnitRef

__all__ = ["CANARY", "CRASH_STATUS", "BugParser", "CrashParser"]

CANARY: Final = "OWCANARY-7f3a91"
"""15:1448's canary. Every page of G29's corpus carries it."""

CRASH_STATUS: Final = 70
"""`CrashParser`'s exit status: EX_SOFTWARE, which `driver_crashed` synthesises a message from."""


def _page_text(unit: UnitRef, io: DriverIO) -> str:
    with io.blobs.open(unit.content_sha256) as fh:
        return fh.read().decode("utf-8", errors="replace")


class BugParser(PlainTextParser):
    """A driver bug whose exception carries the page: `int()` of it. Nothing is returned."""

    def parse(self, unit: UnitRef, parts: PartSelector, io: DriverIO) -> NoReturn:
        del parts
        page_text = _page_text(unit, io)
        int(page_text)
        msg = "int() of a page returned"
        raise AssertionError(msg)


class CrashParser(PlainTextParser):
    """A worker that writes the page to stderr and exits with no frame."""

    def parse(self, unit: UnitRef, parts: PartSelector, io: DriverIO) -> NoReturn:
        del parts
        page_text = _page_text(unit, io)
        sys.stderr.write(page_text)
        sys.stderr.flush()
        os._exit(CRASH_STATUS)
