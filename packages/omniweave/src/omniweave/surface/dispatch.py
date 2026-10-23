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

## `eval`, D833

`eval_entry(verb)` is the same route for 10:286's group. `omniweave-conform` declares one
`[omniweave.eval]` entry point per verb, named for it, and `_load()` is shared, so both refusals
read alike. `eval`'s carries `OW_EVAL_NOT_INSTALLED` and `serve`'s its area's default.

## `trace`, D947

`trace_entry(verb)` is the route for 15-observability.md:233's `ow trace` group, which lives in
`omniweave-serve` beside the OTLP code it drives (02-architecture.md row 40). `omniweave-serve`
declares one `[omniweave.trace]` entry point per verb. No register row names its refusal, so it
carries the area's default symbol, as `serve`'s does.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Protocol

from omniweave_core.errors import CapabilityMissing, ConfigError

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from omniweave_core.retrieve.types import QueryBudget

__all__ = [
    "EVAL_DISTRIBUTION",
    "EVAL_GROUP",
    "EVAL_MISSING",
    "SERVE_DISTRIBUTION",
    "SERVE_GROUP",
    "SERVE_NAME",
    "TRACE_GROUP",
    "Entry",
    "EvalEntry",
    "ServeEntry",
    "TraceEntry",
    "eval_entry",
    "serve_entry",
    "trace_entry",
]

SERVE_GROUP: Final[str] = "omniweave.serve"
SERVE_NAME: Final[str] = "mcp"
SERVE_DISTRIBUTION: Final[str] = "omniweave-serve"

EVAL_GROUP: Final[str] = "omniweave.eval"
"""`ow eval`'s group: one entry point per verb, named for it, in `omniweave-conform`. D833."""
EVAL_DISTRIBUTION: Final[str] = "omniweave-conform"
EVAL_MISSING: Final[str] = "OW_EVAL_NOT_INSTALLED"
"""`OW-A-027`, the register row 10:286 gives `eval`'s refusal."""

TRACE_GROUP: Final[str] = "omniweave.trace"
"""`ow trace`'s group: one entry point per verb, in `omniweave-serve`. D947."""


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
        budget: QueryBudget | None = None,
        deny_restriction_bits: int = 0,
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


class EvalEntry(Protocol):
    """An `omniweave.eval` entry point: builtin keywords in, a `dict` of builtins out. D833."""

    def __call__(self, **kwargs: object) -> Mapping[str, object]:
        """Run one `ow eval` verb in `omniweave-conform`."""
        ...


class TraceEntry(Protocol):
    """An `omniweave.trace` entry point: builtin keywords in, a `dict` of builtins out. D947."""

    def __call__(self, **kwargs: object) -> Mapping[str, object]:
        """Run one `ow trace` verb in `omniweave-serve`."""
        ...


def _installed(group: str = SERVE_GROUP) -> Iterable[Entry]:
    from importlib.metadata import entry_points  # noqa: PLC0415 -- call time, never import time

    return entry_points(group=group)


def serve_entry(entries: Iterable[Entry] | None = None) -> ServeEntry:
    """The server's entry point, loaded. Raises `CapabilityMissing` when it is not installed."""
    rows = _installed() if entries is None else entries
    return _load(rows, SERVE_GROUP, SERVE_NAME, SERVE_DISTRIBUTION, "ow serve")  # type: ignore[return-value]


def eval_entry(verb: str, entries: Iterable[Entry] | None = None) -> EvalEntry:
    """`ow eval <verb>`'s entry point, loaded (10:286, D833).

    No entry point is `OW-A-027 / OW_EVAL_NOT_INSTALLED`, exit 64, naming the install command.
    """
    rows = _installed(EVAL_GROUP) if entries is None else entries
    return _load(  # type: ignore[return-value]
        rows, EVAL_GROUP, verb, EVAL_DISTRIBUTION, f"ow eval {verb}", symbol=EVAL_MISSING
    )


def trace_entry(verb: str, entries: Iterable[Entry] | None = None) -> TraceEntry:
    """`ow trace <verb>`'s entry point, loaded (15-observability.md:233, D947).

    No entry point is `CapabilityMissing`, exit 64, naming `pip install omniweave-serve`.
    """
    rows = _installed(TRACE_GROUP) if entries is None else entries
    return _load(rows, TRACE_GROUP, verb, SERVE_DISTRIBUTION, f"ow trace {verb}")  # type: ignore[return-value]


def _load(
    rows: Iterable[Entry],
    group: str,
    name: str,
    distribution: str,
    command: str,
    *,
    symbol: str | None = None,
) -> object:
    """One named entry point of `group`, loaded and callable, or the refusal that names why."""
    found = [entry for entry in rows if entry.name == name]
    if not found:
        raise CapabilityMissing(
            f"{command} needs {distribution}, which is not installed: no "
            f"[{group}] {name} entry point",
            missing=(distribution,),
            fix=f"pip install {distribution}",
            symbol=symbol,
        )
    if len(found) > 1:
        values = ", ".join(sorted(entry.value for entry in found))
        raise ConfigError(
            f"[{group}] {name} is declared {len(found)} times ({values}); a broken "
            f"install, and choosing one would be choosing by metadata order",
            fix=f"pip install --force-reinstall {distribution}",
        )
    loaded = found[0].load()
    if not callable(loaded):
        raise ConfigError(
            f"[{group}] {name} = {found[0].value} is not callable",
            fix=f"pip install --force-reinstall {distribution}",
        )
    return loaded
