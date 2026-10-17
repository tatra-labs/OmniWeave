"""The omniweave CLI, SDK, surface registry and its generators, the router, the
Supervisor, the planner, the three host graph passes, install and hooks.
Specified in 11-repo-layout.md section 1.4 and 02-architecture.md section 2
rows 30-39.

18-api-sketch.md:149: *"`import omniweave` re-exports the whole surface; `omniweave.sdk` is the
module and the top-level package is an alias, so `omniweave.corpus(...)` works."* The alias is a
module `__getattr__` (D858), so `import omniweave` imports nothing more than it did before: the
CLI's cold start pays for the SDK only when a caller names it.
"""

from __future__ import annotations

from typing import Any


def __getattr__(name: str) -> Any:
    """`omniweave.<name>` for every name `omniweave.sdk` exports, imported on first use.

    A submodule name or a dunder is never answered here. `from omniweave import sdk` probes this
    package for `sdk` before importing it, and answering would import `omniweave.sdk` from inside
    its own import.
    """
    if name.startswith("__") or name == "sdk":
        message = f"module 'omniweave' has no attribute {name!r}"
        raise AttributeError(message)
    import omniweave.sdk  # noqa: PLC0415 -- the alias is lazy by design

    if name in omniweave.sdk.__all__:
        return getattr(omniweave.sdk, name)
    message = f"module 'omniweave' has no attribute {name!r}"
    raise AttributeError(message)
