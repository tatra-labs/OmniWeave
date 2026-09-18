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

`instructions.py` is artefact 2 and `mcp_tools.py` is artefact 1. They are the first two for one
reason: they are the two whose content the plan prints and MEASURES -- 977 characters at 10:872,
and 10:336's eight figures for the four tool objects -- so they are the two that can be produced
without inventing a document layout, and the two whose production can be checked against something
other than itself.

`mcp-tools-v1.json` is also the one file two gates claim: 02:273's row 49 lists it among the
thirteen `ow schema emit` writes (G6) and 02:255's row 31 lists it among these seven (G25). W7.2b
settles that, and the settlement is not a deletion -- `tools/schemagen.py` keeps its inventory row,
resolves it `DEFERRED`, and asks this register whether the artefact is produced. G6 keeps an
assertion over the file; G25 keeps the bytes.

`cli_tree.py` is artefact 3 and the third renderer, and it is the one that made the register grow a
`Shape`. 11:246 homes the argparse tree at `omniweave/cli/`, a package rather than a file, so its
byte diff is over a directory -- and a directory needs the clause a file does not have: a member
inside it that no renderer wrote is hand-written by definition. That is `tools/schemagen.py`'s
`_stray_files()` applied inside a package, and it is what makes *"the directory is generated"* a
gate rather than a sentence. `check()` is five clauses now, and the fifth is over `TREE` rows only.

It also reads artefact 1. `--want`'s five values, `--detail`'s four and `--max-rung`'s seven come
from `mcp_tools.INPUT_SCHEMAS`, which takes them from `surface/inputs.py`, so the two artefacts
cannot disagree about a choice set. 10:206's numbering turns out to be a dependency order for at
least those two.

`sdk_stub.py` is artefact 4, and it is the one renderer whose output is bounded by something other
than the registry: a stub declares what a package EXPORTS, and one that named a symbol
`omniweave.sdk` does not bind would make it type-check and fail at runtime. That is LEANN's
`llms.txt` written in Python, so `render()` emits exactly `omniweave.sdk.__all__` and grows when
the package does. 02:212 makes the file the proof of every `T-PUBLIC` promise the SDK makes, which
is why the binding runs in both directions and not only against over-declaration.

**Two entry points are deliberately not re-exported here, and the reason is mechanical rather
than stylistic.** `instructions()` lives in `omniweave.gen.instructions` and `emit()` lives in
`omniweave.gen.emit`, and in both cases the function's name is its module's name -- so binding it
on the package overwrites the submodule attribute, and `import omniweave.gen.emit as m` hands the
caller a function. A name that shadows its own module is a name with two meanings.

`mcp_tools.render()` is not re-exported either, for the neighbouring reason: `render` is already
`emit.render(artefact)`, the register-wide dispatcher, and a package-level `render` that sometimes
meant *"artefact 1's bytes"* would be the same collision spelled across two modules. Every renderer
is reached through its module and registered in `emit.RENDERERS` by number.

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
