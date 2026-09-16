"""plan, channels, fuse, ceiling, verdict, expand. LAZY. 02-architecture.md section 2 row 27.

11-repo-layout.md:206 names those six modules and this package is being filled in that order:
**W6.1** shipped `types.py` and `plan.py` (16-roadmap.md:657), **W6.2** `channels.py` and the five
Channels behind `Reader.channel()`, and **W6.3** `fuse.py` and `ceiling.py` (16-roadmap.md:659) --
the scorer, its denominator, and the one `_weight()` that ST6 makes them share. **W6.4** put
decision 3's bind-time half in `plan.py` rather than in a module of its own, and **W6.5** ships
`verdict.py` (16-roadmap.md:661) -- the fifteen absence gates and the one citability rule.

`expand` is the last of the six and is absent. The traversal it names shipped inside
`SqliteReader._traverse` at W6.2c, because 07:1343's `Expand` is bounded by construction and the
frontier BFS runs against `block_link` inside the snapshot; what this package still owes is the
`expand()` 18-api-sketch.md:841 puts on the public surface.

**The five scoring constants are re-exported here on purpose.** 07:1382 puts them in this package by
name -- *"`RRF_K = 60 ; SCORER_VERSION = 1` -- ONE constant, in `omniweave_core.retrieve`"* -- and a
constant whose sole home is `omniweave_core.retrieve.types` is one importable spelling away from
that sentence being false. They are defined once, in `types.py`, and bound here.

**The types of 18-api-sketch.md:841 are bound here; the functions in the same row are not.** That
row homes `ChannelStatus ChannelResult ChannelSpec FusedHit CHANNELS RRF_K SCORER_VERSION
DEFAULT_WEIGHTS fuse() ceiling() expand()` at `omniweave_core.retrieve`, and three of its names are
also 11:206's module names. A function bound into a package whose module shares its name shadows the
module: after `from omniweave_core.retrieve import plan` a caller holds the function and cannot
reach `plan.memo_key`, and `omniweave_core.retrieve.fuse` would mean the module before the package
is imported and the function after. W6.1 took that reading for `plan()` and W6.3 takes it for
`fuse()` and `ceiling()`; `expand()` will be the fourth. D260 records that the two documents cannot
both be satisfied for those four names.

`ChannelSpec` is the one type in that row not bound here, because its home is `store/types.py`:
`Reader.channel(spec)` takes it across the P2 protocol boundary, so the store cannot import it from
the query path, and a second importable spelling of a frozen P2 shape is the rival INV-21 forbids.

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
    ChannelResult,
    ChannelStatus,
    FusedHit,
)

__all__ = [
    "ABSENCE_GATES",
    "CEILING_BEARING",
    "CHANNELS",
    "DEFAULT_WEIGHTS",
    "RRF_K",
    "SCORER_VERSION",
    "ChannelResult",
    "ChannelStatus",
    "FusedHit",
]
