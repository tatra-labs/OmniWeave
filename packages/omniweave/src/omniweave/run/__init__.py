"""The Supervisor's package: the one `asyncio` loop, and the only place a loop may exist.

INV-3, spelled as a ban in the workspace's own lint config: `"asyncio".msg = "INV-3: omniweave/run/
only. Core must not import a loop."` `pyproject.toml`'s per-file-ignore for `TID251` is scoped to
`packages/omniweave/src/omniweave/run/*.py` and nowhere else, so the invariant is a mechanism rather
than a rule about where people should put things.

02-architecture.md section 5.3 step 9 makes one Supervisor per process an **assertion**: a second
`run()` in one process is refused with a `StoreError` before the loop opens. 08-runtime.md section
2.6 lists it among the five things that are deliberately not parallel, beside the commit, two
writers on one store, a `REGEN` retry for one `(unit, part)`, and driver construction.

**`dispatch` is deliberately not re-exported here.** `omniweave/run/dispatch.py` imports
`omniweave_core.host.subproc` for the four mechanisms 02-architecture.md:238 leaves there, and that
module opens `ctypes`, `socket` and `struct` for the job objects and the named pipes. Re-exporting
its names would make `from omniweave.run import Admission` -- which is a pure arithmetic over
`(Config, HostFacts)` -- pay for a driver host. The dispatcher's callers are `supervisor.py` and
`pipeline.py`, both of which import it by module.

Specified in 02-architecture.md section 2 rows 30-39 and section 5, 08-runtime.md Part 2, and
11-repo-layout.md section 1.4.
"""

from __future__ import annotations

from omniweave.run.supervisor import (
    Admission,
    HostFacts,
    StallVerdict,
    derive_admission,
    producer_should_pause,
    ram_required,
    stall_verdict,
)

__all__ = [
    "Admission",
    "HostFacts",
    "StallVerdict",
    "derive_admission",
    "producer_should_pause",
    "ram_required",
    "stall_verdict",
]
