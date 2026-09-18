"""`ow surface emit`: the seven agent-facing artefacts. 02-architecture.md row 31; 11:248.

Row 31's responsibility is *"`ow surface emit`: the seven agent-facing artefacts ... plus
`ow surface typescript <dir>`"*, and its forbidden column is the mirror of row 30's: this package
emits and does not declare, that one declares and does not emit. One definition, seven generated
artefacts, one byte-diff gate -- which is what makes INV-20 checkable instead of aspirational
(02:283).

## THIS PACKAGE'S HOME IS CONTESTED, AND THREE SITES TO ONE SETTLED IT

02:255 gives the generator `omniweave.gen`, 11:248 puts `gen/` in the package tree with the words
*"`ow surface emit [--check|--bless]` -- the seven agent-facing artefacts"*, and 11:487 scopes a
semgrep ban to `omniweave/gen/`. 10:229 says `omniweave/surface/emit.py` instead, and it is the
site that assigns the purity bans -- so the bans and the file they name live in a package 02:255
forbids from generating at all. Three sites to one, and the one that dissents is the one with the
rules; the rules are applied here and D315 is the entry.

## WHAT IS HERE, AND IN WHAT ORDER IT ARRIVES

`artefacts.py` is the register of seven rows. `emit.py` is the byte-diff spine, and it is a gate
from the day the register exists rather than from the day the renderers do: it refuses a committed
file for an artefact nothing can produce, which is LEANN's `llms.txt` exactly (00:851 makes that
G25's named defect).

`instructions.py` is artefact 2 and the only one with a renderer today. It is first because it is
the only one of the seven whose content the plan prints verbatim and measures -- 977 characters at
10:872 -- so it is the only one that can be generated without inventing a document layout.

**Two entry points are deliberately not re-exported here, and the reason is mechanical rather
than stylistic.** `instructions()` lives in `omniweave.gen.instructions` and `emit()` lives in
`omniweave.gen.emit`, and in both cases the function's name is its module's name -- so binding it
on the package overwrites the submodule attribute, and `import omniweave.gen.emit as m` hands the
caller a function. A name that shadows its own module is a name with two meanings.

`check`, `render` and `normalise` collide with nothing and are bound, because `ow surface emit
--check` is the gate every other document cites and it should not need a submodule path. The
surface package draws the same line for `inputs.py` and `schema.py`, for the same reason one level
up: a caller reaches a renderer through its module.
"""

from __future__ import annotations

from omniweave.gen.artefacts import ARTEFACTS, Artefact, State
from omniweave.gen.emit import check, normalise, render

__all__ = [
    "ARTEFACTS",
    "Artefact",
    "State",
    "check",
    "normalise",
    "render",
]
