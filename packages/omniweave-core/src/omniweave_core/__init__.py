"""The omniweave host substrate. Stdlib plus omniweave_ports; zero third-party
dependencies (INV-2, gate G1).

This module is EAGER and it imports NONE of the nine lazy subpackages — model,
store, archive, retrieve, answer, out, host, toolchain, modelserver. G17 asserts a
bare `import omniweave_core` loads none of them and G23 asserts it imports neither
asyncio nor selectors, because `ow hook prompt` has a 250 ms warm p95 budget (G26)
and pays for every module this import touches.

The nine are nonetheless *reachable* as attributes, through `__getattr__` below:
11-repo-layout.md section 1.3 calls their laziness "a STRUCTURAL property, not a
convention", and a name that resolves on access is what makes it structural rather
than a rule about which import statement a caller is allowed to write.

Specified in 11-repo-layout.md section 1.3 and 02-architecture.md section 2.
"""

from __future__ import annotations

from types import ModuleType

__all__ = [
    "answer",
    "archive",
    "host",
    "model",
    "modelserver",
    "out",
    "retrieve",
    "store",
    "toolchain",
]

# The nine, verbatim from 11-repo-layout.md section 1.3 and G17's assertion. `drivers` is NOT
# among them and is deliberately absent: it is T-CONTRACT and eagerly importable, but nothing in
# this file imports it either, so `import omniweave_core` still touches no card code.
LAZY: frozenset[str] = frozenset(__all__)


def __getattr__(name: str) -> ModuleType:
    """Resolve one of the nine lazy subpackages on first attribute access.

    **Nine explicit arms rather than one `importlib.import_module(f"omniweave_core.{name}")`,
    and the verbosity is the point.** `importlib.import_module` and `__import__` are banned
    outside `host/` by `tools/semgrep/omniweave.yaml` (02-architecture.md section 7's semgrep
    row), because the hazard they name is resolving a module from a string that a card, a config
    value or a request body supplied — DR19 and docling's `load_setuptools_entrypoints` receipt
    (04-driver-system.md section 4.6). A dispatch table would launder a constant through exactly
    the API that ban exists to keep greppable, so the nine names are written as nine literal
    import statements: a reader and a grep both see the complete set, and no argument can reach
    an importer from here.

    Relative imports are banned framework-wide (`ban-relative-imports = "all"`), so each arm is
    absolute.

    A name that is not one of the nine raises `AttributeError`, which is what makes
    `hasattr(omniweave_core, "nonsense")` false and keeps `dir()`-driven tooling honest. A name
    that IS one of the nine but whose module has not landed yet raises `ModuleNotFoundError`
    unchanged — at P1 that is `modelserver`, which arrives with P4 W4.9, and reporting the
    absence as an import failure is more honest than reporting it as a missing attribute.
    """
    if name == "model":
        import omniweave_core.model as module  # noqa: PLC0415
    elif name == "store":
        import omniweave_core.store as module  # noqa: PLC0415
    elif name == "archive":
        import omniweave_core.archive as module  # noqa: PLC0415
    elif name == "retrieve":
        import omniweave_core.retrieve as module  # noqa: PLC0415
    elif name == "answer":
        import omniweave_core.answer as module  # noqa: PLC0415
    elif name == "out":
        import omniweave_core.out as module  # noqa: PLC0415
    elif name == "host":
        import omniweave_core.host as module  # noqa: PLC0415
    elif name == "toolchain":
        import omniweave_core.toolchain as module  # noqa: PLC0415
    elif name == "modelserver":
        import omniweave_core.modelserver as module  # noqa: PLC0415
    else:
        raise AttributeError(f"module 'omniweave_core' has no attribute {name!r}")
    return module


def __dir__() -> list[str]:
    """`dir(omniweave_core)` lists the nine alongside whatever is already bound.

    Without this, a lazy name is invisible to tab completion and to `inspect`, which is the
    usual way a `__getattr__` module surface ends up undiscoverable.
    """
    return sorted(set(globals()) | LAZY)
