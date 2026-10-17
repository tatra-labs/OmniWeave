"""The omniweave CLI, SDK, surface registry and its generators, the router, the
Supervisor, the planner, the three host graph passes, install and hooks.
Specified in 11-repo-layout.md section 1.4 and 02-architecture.md section 2
rows 30-39.

18-api-sketch.md:149: *"`import omniweave` re-exports the whole surface; `omniweave.sdk` is the
module and the top-level package is an alias, so `omniweave.corpus(...)` works."* The alias is a
module `__getattr__` (D858), so `import omniweave` imports nothing more than it did before: the
CLI's cold start pays for the SDK only when a caller names it.

**A submodule's name is the submodule's** (D860). `omniweave.doctor` is the `ow doctor` package,
and 18:211 also prints the SDK's `doctor()`. Answering the SDK name here would hand
`from omniweave import doctor` a function where the import system expects the package, so a name
that is a module beside this file is never answered: the SDK's is `omniweave.sdk.doctor`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

_HERE = Path(__file__).parent


def __getattr__(name: str) -> Any:
    """`omniweave.<name>` for every name `omniweave.sdk` exports, imported on first use.

    A dunder, `sdk` itself and any name that is a submodule of this package are never answered:
    `from omniweave import sdk` probes this package for `sdk` before importing it, and a submodule
    such as `doctor` must reach the import system, not the SDK's function of the same name.
    """
    if (
        name.startswith("__")
        or name == "sdk"
        or (_HERE / name).is_dir()
        or (_HERE / f"{name}.py").is_file()
    ):
        message = f"module 'omniweave' has no attribute {name!r}"
        raise AttributeError(message)
    import omniweave.sdk  # noqa: PLC0415 -- the alias is lazy by design

    if name in omniweave.sdk.__all__:
        return getattr(omniweave.sdk, name)
    message = f"module 'omniweave' has no attribute {name!r}"
    raise AttributeError(message)
