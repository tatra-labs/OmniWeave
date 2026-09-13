"""Observability's core half: the one typed downgrade record.

`15-observability.md:975` names this package in the header of the code block it prints --
*"omniweave_core/observe/degradation.py -- a T-SCHEMA published read contract"* -- and nothing else
is homed here yet. The sinks and the vocabulary are `omniweave_core.events`, because
`02-architecture.md:245` puts them there; the manifest is `omniweave/run/manifest.py`, in the CLI
distribution, because the process that writes it is the one holding the `store.write` lock.

**Eager, and exporting nothing.** This is not one of `omniweave_core/__init__.py`'s nine lazy names,
so `import omniweave_core` does not load it and `from omniweave_core.observe.degradation import
Degradation` is what a caller writes on purpose. Re-exporting the names here would make
`omniweave_core.observe` a second spelling of a module that `15 §6.3` calls *"the type's sole
home"*, which is the one thing that section is about.
"""

from __future__ import annotations

__all__: list[str] = []
