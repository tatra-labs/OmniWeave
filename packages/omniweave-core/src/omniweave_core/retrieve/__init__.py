"""plan, channels, fuse, ceiling, verdict, expand. LAZY. 02-architecture.md section 2 row 27.

11-repo-layout.md:206 names those six modules and this package is being filled in that order:
**W6.1 ships `types.py` and `plan.py`** (16-roadmap.md:657), the planner and the shapes it produces.
`channels`, `fuse`, `ceiling`, `verdict` and `expand` are W6.2 through W6.5 and are absent, which is
why `ChannelResult` is homed here and nothing yet constructs one.

**The five scoring constants are re-exported here on purpose.** 07:1382 puts them in this package by
name -- *"`RRF_K = 60 ; SCORER_VERSION = 1` -- ONE constant, in `omniweave_core.retrieve`"* -- and a
constant whose sole home is `omniweave_core.retrieve.types` is one importable spelling away from
that sentence being false. They are defined once, in `types.py`, and bound here.

Nothing else is re-exported. `plan()` is `omniweave_core.retrieve.plan.plan` and stays there for
`omniweave.route`'s reason: a function bound into a package whose module shares its name shadows the
module, and after `from omniweave_core.retrieve import plan` a caller holds the function and cannot
reach `plan.memo_key`.

This subpackage is one of `omniweave_core/__init__.py`'s nine LAZY names, so `import omniweave_core`
does not reach it (G17) and everything under it is stdlib-only (INV-2 / G1).
"""

from __future__ import annotations

from omniweave_core.retrieve.types import (
    ABSENCE_GATES,
    CEILING_BEARING,
    CHANNELS,
    DEFAULT_WEIGHTS,
    RRF_K,
    SCORER_VERSION,
)

__all__ = [
    "ABSENCE_GATES",
    "CEILING_BEARING",
    "CHANNELS",
    "DEFAULT_WEIGHTS",
    "RRF_K",
    "SCORER_VERSION",
]
