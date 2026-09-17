"""`ActionSpec` · `ACTIONS` · `HUMAN_ONLY` · `Profile`. 11:247; 02-architecture.md row 30.

18:851 homes exactly those four names at `omniweave.surface`, `T-PUBLIC`, with the one-line reason
*"one Action declaration, seven generated surfaces"*. They are defined in `registry.py` and bound
here, because 02:254's row 30 gives this package the registry and the startup invariant and gives
the NEXT row the emission: its forbidden column reads *"emitting the artefacts (row 31's job) and
hand-writing any of them (INV-20)"*.

`assert_sv1` and `listed` are bound beside them although 18:851 does not name them, because they are
the invariant row 30 owns -- it names SV1 in the same cell, as a startup check that `listed` is a
subset of `enabled` and that `HUMAN_ONLY` and `enabled` do not intersect. The check is this
package's; the config values it reads are the operator's and arrive as arguments.

`inputs.py` and `omniweave.sdk.reports` are not re-exported. They are the `inp` and `out` types the
generator reads, and a caller reaches them through `ACTIONS[name].inp` -- which is the only spelling
that stays correct when a row's input type changes.
"""

from __future__ import annotations

from omniweave.surface.registry import (
    ACTIONS,
    GROUPS,
    HUMAN_ONLY,
    PROFILES,
    ActionSpec,
    Profile,
    assert_sv1,
    listed,
)

__all__ = [
    "ACTIONS",
    "GROUPS",
    "HUMAN_ONLY",
    "PROFILES",
    "ActionSpec",
    "Profile",
    "assert_sv1",
    "listed",
]
