"""Suite 8 of 12 -- `sandbox`: it writes where it was told to, and it does not phone home.

04-driver-system.md:2079: "a write outside `tmp` fails; with `needs_network = false` the run is
socket-blocked and any egress attempt fails the suite". The defect it catches is named and real:
**marker's `--use_llm` shipping page images to a hosted model**.

## Blocked, not merely watched

The network half BLOCKS rather than records, and that is the difference between this suite and
`contract`'s constructor watch. `contract` wants to know what a constructor touched and lets it
succeed so the object finishes being built. Here, letting a connection succeed would mean the kit
had performed the egress it exists to forbid -- once, on the author's machine, with the author's
fixtures. So `socket.socket`, `socket.create_connection` and `socket.socketpair` raise, and the
exception a driver then sees is the one it would see behind a real sandbox.

`needs_network = true` inverts only the verdict, never the instrument: the sockets are still
recorded, and the summary names the hosts, because a driver that declares egress should still be
readable in terms of where it goes.

## The write half is a containment check and not a permission check

`io.tmpdir` is the one writable path a driver has (`DriverIO` carries no `output_root` and no
`cache_root` -- INV-6's audit question is "count `DriverIO`'s fields"). So every open in a writing
mode is resolved and compared against that directory, and anything outside it is the finding.
Resolved, because `tmpdir/../../etc/passwd` is outside `tmpdir` and a string comparison says it is
inside.

## P24: the fragment carries no provenance, because provenance is not the driver's to mint

03-document-model.md:3010 lists exactly what may not appear: "no `block_id`, no `producer_id`, no
`origin_operator`, no `origin_driver`, no `restriction_bits`, no currency field and no cache-hit
claim". And it names the one thing that looks like provenance and is not: `achieved`, which is "the
driver's self-report of what it delivered on *this* document" and is checked by `capability`. The
distinction the row draws is worth keeping in front of a reader -- "forging provenance means naming
a row, a producer or a price, and none of those is representable here".

Specified in 04-driver-system.md section 8.2 row 8 and section 6; 03-document-model.md P24.
"""

from __future__ import annotations

import builtins
import io as _io
import socket
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.errors import DriverHostError
from omniweave_ports.types import DriverError, Port

from omniweave_conform.harness import run_parse
from omniweave_conform.result import Assertion, SuiteResult

if TYPE_CHECKING:
    from collections.abc import Iterator

    from omniweave_conform.subject import Subject

SUITE = "sandbox"

_NS_PER_MS: Final = 1_000_000
"""Nanoseconds per millisecond.

`time.monotonic_ns()` rather than `time.perf_counter()` because
`tools/semgrep/omniweave.yaml`'s `omniweave-no-time-time-in-library-code` bans the latter
across `packages/*/src/**` and the rule's own message names this as the replacement: the
clock is injected, "`time.monotonic_ns()` for a duration". Every reading in this module is a
duration."""

FORBIDDEN_KEYS = (
    "block_id",
    "producer_id",
    "origin_operator",
    "origin_driver",
    "restriction_bits",
    "price",
    "currency",
    "cost_usd",
    "cache_hit",
    "cached",
)
"""03-document-model.md:3010's list, plus the two spellings a price actually takes.

`price`, `currency` and `cost_usd` are three names for "a currency field"; `cache_hit` and `cached`
are two for "a cache-hit claim". The plan names the *categories*, and a key-name check has to name
keys -- so the expansion is stated here rather than left implicit, and it is deliberately generous:
a driver that invents a fourth spelling for a price is not caught by this list, which is why the
list is not the only mechanism: `achieved` is bounded by `capability`, and `DocSink` clamps
it again on the way in."""

_WRITE_MODES = frozenset("wax+")


class EgressBlocked(OSError):  # noqa: N818 -- an OSError leaf; see the docstring on the type.
    """What a driver sees when it reaches for the network under `needs_network = false`.

    An `OSError`, because that is what a real sandbox produces and a driver's own error handling
    should meet the same type here that it will meet in production. A bespoke exception class
    would test the driver against a failure mode that does not exist outside this kit.
    """


@dataclass(slots=True)
class Watch:
    writes: list[str] = field(default_factory=list)
    egress: list[str] = field(default_factory=list)


@contextmanager
def _sandboxed(tmpdir: Path, *, block: bool) -> Iterator[Watch]:
    """Record writes outside `tmpdir`; block (or record) every socket."""
    watch = Watch()
    real_open = builtins.open
    real_path_open = Path.open
    real_socket = socket.socket
    real_connection = socket.create_connection
    real_pair = socket.socketpair
    root = tmpdir.resolve()

    def outside(target: Any, mode: str) -> None:
        if not (_WRITE_MODES & set(mode)):
            return
        try:
            resolved = Path(target).resolve()
        except (OSError, TypeError, ValueError):
            watch.writes.append(str(target))
            return
        if root not in resolved.parents and resolved != root:
            watch.writes.append(str(resolved))

    def traced_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        outside(file, mode)
        return real_open(file, mode, *args, **kwargs)

    def traced_path_open(self: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        outside(self, mode)
        return real_path_open(self, mode, *args, **kwargs)

    def traced_socket(*args: Any, **kwargs: Any) -> Any:
        watch.egress.append(f"socket{args!r}")
        if block:
            raise EgressBlocked("egress is blocked: the card declares needs_network = false")
        return real_socket(*args, **kwargs)

    def traced_connection(address: Any, *args: Any, **kwargs: Any) -> Any:
        watch.egress.append(f"connect{address!r}")
        if block:
            raise EgressBlocked(f"egress to {address!r} is blocked: needs_network = false")
        return real_connection(address, *args, **kwargs)

    def traced_pair(*args: Any, **kwargs: Any) -> Any:
        watch.egress.append("socketpair()")
        if block:
            raise EgressBlocked("egress is blocked: the card declares needs_network = false")
        return real_pair(*args, **kwargs)

    builtins.open = traced_open  # type: ignore[assignment]
    _io.open = traced_open  # type: ignore[assignment]
    Path.open = traced_path_open  # type: ignore[method-assign]
    socket.socket = traced_socket  # type: ignore[misc]
    socket.create_connection = traced_connection  # type: ignore[assignment]
    socket.socketpair = traced_pair  # type: ignore[assignment]
    try:
        yield watch
    finally:
        builtins.open = real_open  # type: ignore[assignment]
        _io.open = real_open  # type: ignore[assignment]
        Path.open = real_path_open  # type: ignore[method-assign]
        socket.socket = real_socket  # type: ignore[misc]
        socket.create_connection = real_connection  # type: ignore[assignment]
        socket.socketpair = real_pair  # type: ignore[assignment]


def run(subject: Subject) -> SuiteResult:
    """The `sandbox` suite."""
    started = time.monotonic_ns()
    elapsed = lambda: (time.monotonic_ns() - started) / _NS_PER_MS  # noqa: E731
    needs_network = subject.card.hardware.needs_network

    if subject.card.identity.port is not Port.PARSE:
        return SuiteResult.of(
            SUITE,
            [],
            unknown=f"no {subject.card.identity.port.value}/1 harness in this kit yet",
            elapsed_ms=elapsed(),
        )
    if not subject.fixtures:
        return SuiteResult.of(
            SUITE,
            [],
            unknown="--fixtures named no readable file; a sandbox needs a run to contain",
            elapsed_ms=elapsed(),
        )
    try:
        driver = subject.instantiate()
    except (DriverHostError, DriverError, TypeError, ValueError) as exc:
        return SuiteResult.of(
            SUITE,
            [Assertion("the driver constructs", ok=False, detail=str(exc), locus="construct")],
            elapsed_ms=elapsed(),
        )

    checks = list(_assertions(subject, driver, block=not needs_network))
    writes = sum(1 for a in checks if a.locus.startswith("write:") and not a.ok)
    state = "socket-blocked" if not needs_network else "egress declared and recorded"
    summary = f"{state}; {writes} writes outside tmp"
    return SuiteResult.of(SUITE, checks, summary=summary, elapsed_ms=elapsed())


def _assertions(subject: Subject, driver: object, *, block: bool) -> Iterator[Assertion]:
    scratch = subject.scratch(SUITE)
    for index, fixture in enumerate(subject.fixtures):
        name = fixture.name
        target = scratch / f"f{index}"
        # The sandbox root is `io.tmpdir` EXACTLY, which `run_parse` places at `<target>/tmp`.
        # Rooting at `target` instead would quietly bless `<target>/blobs` -- the kit's own CAS --
        # as a place the driver may write, and "outside tmp" would stop meaning what it says.
        writable = target / "tmp"
        writable.mkdir(parents=True, exist_ok=True)
        with _sandboxed(writable, block=block) as watch:
            try:
                result = run_parse(driver, fixture, target)
            except (EgressBlocked, DriverError):
                result = None
            except Exception as exc:
                yield Assertion(
                    "the run completes or refuses cleanly under the sandbox",
                    ok=False,
                    detail=f"{type(exc).__name__}: {exc}"[:160],
                    fixture=name,
                    locus="run",
                )
                result = None
        yield Assertion(
            "no write outside io.tmpdir",
            ok=not watch.writes,
            detail=", ".join(watch.writes[:3]) if watch.writes else "0 writes outside tmp",
            fixture=name,
            locus=f"write:{name}",
        )
        yield Assertion(
            "no egress under needs_network = false"
            if block
            else "egress is declared, and is recorded here rather than forbidden",
            ok=not watch.egress if block else True,
            detail=(
                ", ".join(watch.egress[:3]) if watch.egress else "0 sockets opened during the run"
            ),
            fixture=name,
            locus=f"egress:{name}",
        )
        if result is not None:
            yield from _provenance_assertions(name, result)


def _provenance_assertions(name: str, result: Any) -> Iterator[Assertion]:
    """P24: no forged provenance anywhere in the fragment."""
    found: dict[str, int] = {}
    for record in result.fragment.records:
        _scan(record, found)
    yield Assertion(
        "the fragment names no row, no producer and no price",
        ok=not found,
        detail=(
            ", ".join(f"{key} x{count}" for key, count in sorted(found.items()))
            if found
            else "achieved is the only self-report present, and capability bounds it"
        ),
        fixture=name,
        locus="P24",
        expected="none of " + ", ".join(FORBIDDEN_KEYS),
        actual=", ".join(sorted(found)) or "none",
    )


def _scan(value: Any, found: dict[str, int], depth: int = 0) -> None:
    """Walk a decoded record looking for forbidden key names at any depth.

    Bounded at eight levels: `owdoc-fragment/1` records are flat by construction and an unbounded
    walk over attacker-supplied JSON is a recursion the kit does not need to own.
    """
    max_depth = 8
    if depth > max_depth:
        return
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_KEYS:
                found[key] = found.get(key, 0) + 1
            _scan(child, found, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _scan(child, found, depth + 1)
