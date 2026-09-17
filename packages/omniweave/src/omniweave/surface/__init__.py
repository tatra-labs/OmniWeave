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

`FULL_ROSTER` is bound beside `GROUPS` and for the same reason: both are declaration data the
generator reads, and both answer a question a reviewer asks of the surface rather than of one row --
`GROUPS` what a CLI root may be, `FULL_ROSTER` what the `full` profile is supposed to contain. The
roster is also what `ow surface budget --bless` waits on (10:833), and a command in another package
should not have to reach through a private module to learn whether its day has come.

**The five CLI registers and `resolve_cli()` are bound as one family**, because a caller that had
to reach `CLI_ABSENT` through the private module while `CLI_ROSTER` was public would be reading two
halves of one answer from two places. `tools/plan_lint.py`'s `cli-verbs` rule needs all six: the
roster to resolve a spelling, the two exception registers to know that an unresolved one is
recorded, `CLI_RESOLVED` to know which statuses are findings, and the resolver itself.

`inputs.py` and `omniweave.sdk.reports` are not re-exported. They are the `inp` and `out` types the
generator reads, and a caller reaches them through `ACTIONS[name].inp` -- which is the only spelling
that stays correct when a row's input type changes.
"""

from __future__ import annotations

from omniweave.surface.registry import (
    ACTIONS,
    CLI_ABSENT,
    CLI_FREE,
    CLI_RESOLVED,
    CLI_ROSTER,
    CLI_UNROSTERED,
    FULL_ROSTER,
    GROUPS,
    HUMAN_ONLY,
    PROFILES,
    ActionSpec,
    CliStatus,
    Profile,
    assert_sv1,
    listed,
    resolve_cli,
)

__all__ = [
    "ACTIONS",
    "CLI_ABSENT",
    "CLI_FREE",
    "CLI_RESOLVED",
    "CLI_ROSTER",
    "CLI_UNROSTERED",
    "FULL_ROSTER",
    "GROUPS",
    "HUMAN_ONLY",
    "PROFILES",
    "ActionSpec",
    "CliStatus",
    "Profile",
    "assert_sv1",
    "listed",
    "resolve_cli",
]
