"""The one place `omniweave` reaches a distribution its layers row does not list. 10:286.

10:286 prints this file for the `eval` group -- *"the ONE lazy import, at call time, never at
module import"* -- and the rule it states is the one this module keeps for `serve`: the Action's
row stays in `ACTIONS` unconditionally, and whether the distribution that implements it is
installed is a **dispatch** fact, found at call time and refused by name when absent.

## HOW, AND WHY NOT AN IMPORT

10:286's own spelling is `import omniweave_conform`, and G4 fails it: `omniweave`'s row in
`tools/layers.toml` is `["omniweave_core", "omniweave_ports", "omniweave_office"]`. `serve` is
reached instead through an entry point, `omniweave.serve` / `mcp`, which `omniweave-serve`'s
`pyproject.toml` declares, and `EntryPoint.load()` runs at call time. That is how the framework
already reaches every driver it does not import. It is also inside the semgrep rule's reason for
banning `import_module` outside the host, *"a config value must never be able to name a module"*:
the module named here comes from an installed distribution's metadata, and no configuration key
or argument can change it. The user chose this route over a process handoff on 2026-09-25.

## WHAT CROSSES

Five keyword arguments of builtin types -- `profile: str`, `compact: bool`, `corpus_resolves:
bool`, `corpus: str | None` (the default corpus step 5 resolved) and `corpora: Mapping[str, str]`
(each declared corpus's store, as an absolute path) -- and an `int` back. A type defined on
either side is one the other side cannot import, so the contract is written in the types both
already share.

## THE REFUSAL

No entry point is `CapabilityMissing`: exit 64, 10:1493's *"required capability missing"*, naming
the distribution and the command that installs it -- the shape 10:286 gives `eval`'s refusal.
`eval` has a register row for it (`OW-A-027 / OW_EVAL_NOT_INSTALLED`) and `serve` has none, so the
error carries its area's default symbol rather than a numeric this file would be minting. D512.
Two entry points under one name is a broken install, and it is refused rather than resolved by
whichever the metadata listed first.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Protocol

from omniweave_core.errors import CapabilityMissing, ConfigError

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

__all__ = ["SERVE_DISTRIBUTION", "SERVE_GROUP", "SERVE_NAME", "Entry", "ServeEntry", "serve_entry"]

SERVE_GROUP: Final[str] = "omniweave.serve"
SERVE_NAME: Final[str] = "mcp"
SERVE_DISTRIBUTION: Final[str] = "omniweave-serve"
_INSTALL: Final[str] = f"pip install {SERVE_DISTRIBUTION}"


class ServeEntry(Protocol):
    """`omniweave_serve.launch.run`'s signature, written on this side of the boundary."""

    def __call__(
        self,
        *,
        profile: str,
        compact: bool,
        corpus_resolves: bool,
        corpus: str | None,
        corpora: Mapping[str, str],
        sources: Mapping[str, str],
        sessions: str | None,
    ) -> int:
        """Serve until the host closes the stream; return the process exit code."""
        ...


class Entry(Protocol):
    """The part of `importlib.metadata.EntryPoint` this module reads, so a test can hand in rows."""

    @property
    def name(self) -> str:
        """The entry point's name within its group."""
        ...

    @property
    def value(self) -> str:
        """`module:attr`, from the distribution's metadata."""
        ...

    def load(self) -> object:
        """Import the module and return the attribute."""
        ...


def _installed() -> Iterable[Entry]:
    from importlib.metadata import entry_points  # noqa: PLC0415 -- call time, never import time

    return entry_points(group=SERVE_GROUP)


def serve_entry(entries: Iterable[Entry] | None = None) -> ServeEntry:
    """The server's entry point, loaded. Raises `CapabilityMissing` when it is not installed."""
    rows = _installed() if entries is None else entries
    found = [entry for entry in rows if entry.name == SERVE_NAME]
    if not found:
        raise CapabilityMissing(
            f"ow serve needs {SERVE_DISTRIBUTION}, which is not installed: no "
            f"[{SERVE_GROUP}] {SERVE_NAME} entry point",
            missing=(SERVE_DISTRIBUTION,),
            fix=_INSTALL,
        )
    if len(found) > 1:
        values = ", ".join(sorted(entry.value for entry in found))
        raise ConfigError(
            f"[{SERVE_GROUP}] {SERVE_NAME} is declared {len(found)} times ({values}); a broken "
            f"install, and choosing one would be choosing by metadata order",
            fix=f"pip install --force-reinstall {SERVE_DISTRIBUTION}",
        )
    loaded = found[0].load()
    if not callable(loaded):
        raise ConfigError(
            f"[{SERVE_GROUP}] {SERVE_NAME} = {found[0].value} is not callable",
            fix=f"pip install --force-reinstall {SERVE_DISTRIBUTION}",
        )
    return loaded  # type: ignore[return-value]
