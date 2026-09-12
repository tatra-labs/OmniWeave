"""`omniweave-driver/1` framing, under a byte-level fuzzer. W3.2's named target.

16-roadmap.md:482 owes exactly this: `host/wire.py` is "80 lines of framing plus **an atheris
target**". 02-architecture.md:238 and 04-driver-system.md:1685 both give the module as "framing
only (~80 lines), **fuzzed**", and 13-quality.md:133's `core/host, core/host/wire` row names the
property this file asserts in four words: **frame framing under a byte-level fuzzer.**

## The property

A byte string is either a frame or a named refusal. Nothing else.

`omniweave_core.host.wire`'s own docstring states the half that is easy to get wrong, about the
depth cap: a header nested ten thousand deep "either raises `RecursionError` out of the pure-Python
scanner or exhausts the C stack in the accelerated one -- and `RecursionError` is not a NAMED
protocol error, **which is exactly what the fuzz property forbids**." So `allowed` here is the one
type `DriverHostError`, and `RecursionError`, `MemoryError`, `struct.error`, `UnicodeDecodeError`,
`json.JSONDecodeError`, `OverflowError` and `KeyError` are every one of them a finding. A target
that caught `Exception` would pass on all seven.

`DriverError` is deliberately **not** allowed. 02-architecture.md:1060: "A frame that violates
`wire.py`'s caps or carries an unknown `kind` is a `DriverHostError` (`OW-D-*`) -- **our** bug,
never the driver's." A framing fault attributed to a third party tells the operator to file the
wrong issue, so a `DriverError` escaping here is a finding and not a refusal.

## The second clause: what decodes, re-encodes

A frame that decodes and then re-encodes without a refusal must decode again to an equal frame.
That is narrower than "encode and decode are inverse", and the narrowing is the interesting part:
`decode` must accept things `encode` will never emit, because a reader faces a hostile peer and an
emitter does not. A lone surrogate in a header is the worked example -- `json.loads` produces one,
`omniweave_core.canonical.canonical` refuses to write one -- so `encode` raising a *named* refusal
on a frame that decoded is correct behaviour and is counted as such. What would be a finding is a
frame that survived the round trip and came back different, because that is a host and a driver
holding two readings of one exchange.

## The corpus

`fuzz/seeds/wire/` is this repository's own, written by `--write-seeds` and committed, because
framing is a grammar this repository owns -- unlike `fuzz/seeds/xlsx/` and its siblings, which are
mirrored from `vendor/anydoc` and are a format this repository deliberately does not know. One
valid frame per kind gives libFuzzer eleven shapes to mutate toward each other; the malformed seeds
are the shapes a mutator is unlikely to find on its own because they are about *lengths* rather
than about content -- a prefix declaring 4 GiB is eight bytes and a billion mutations away from
being stumbled into.

`fuzz/test_targets.py` asserts the committed seeds are byte-identical to what `--write-seeds`
writes today, so the corpus is generated-and-checked rather than hand-maintained.

Specified in 16-roadmap.md:482, 02-architecture.md:238 and :1060, 04-driver-system.md sections 6.2
and 6.5, and 13-quality.md:133.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# `_harness` is the sibling the `sys.path.insert` above reaches, and importing it is also what
# puts `packages/*/src` on the path for the two `omniweave_core` imports below.
from _harness import Input, Target, main
from omniweave_core.canonical import JsonValue
from omniweave_core.errors import DriverHostError
from omniweave_core.host.wire import (
    MAX_BODY_BYTES,
    MAX_HEADER_BYTES,
    MAX_HEADER_DEPTH,
    PREFIX_BYTES,
    FrameKind,
    encode,
    read_frame,
)

NAME = "wire"


class RoundTripError(Exception):
    """A frame survived encode-then-decode and came back different. Clause 2's finding.

    Its own type rather than an `AssertionError` because `assert` is compiled out under `-O` and
    a property that disappears under an optimisation flag is not a property.
    """


def reader(data: bytes) -> object:
    """A `Recv` over a byte string: read at most `n`, return fewer only at the end."""
    offset = 0

    def recv(n: int) -> bytes:
        nonlocal offset
        chunk = data[offset : offset + n]
        offset += len(chunk)
        return chunk

    return recv


def probe(data: bytes) -> None:
    """Read one frame, then round-trip it. Raises `DriverHostError` or nothing."""
    frame = read_frame(reader(data))  # type: ignore[arg-type]
    # Clause 2. A refusal from `encode` is correct and is the caller's -- it propagates as the
    # allowed type. Only a SUCCESSFUL re-encode is held to producing an equal frame.
    again = encode(frame.kind, dict(frame.header), frame.body)
    round_tripped = read_frame(reader(again))  # type: ignore[arg-type]
    if round_tripped != frame:
        raise RoundTripError(f"{frame.kind.name}: {round_tripped!r} != {frame!r}")


# ---------------------------------------------------------------------------
# the corpus
# ---------------------------------------------------------------------------

HEADERS: dict[FrameKind, dict[str, JsonValue]] = {
    # One header per kind, minimal and plausible. Framing validates no payload key
    # (`wire.py`'s "What this module deliberately does not validate"), so these exist to give a
    # mutator a realistic shape rather than to be schema-correct: a key a mutator can corrupt is
    # worth more here than a key that is right.
    FrameKind.HELLO: {"port": "parse", "card_schema": 1, "driver_id": "parse.x.y"},
    FrameKind.HELLO_ACK: {"driver_id": "parse.x.y", "version": "1.0.0", "schema_version": 1},
    FrameKind.PROBE: {},
    FrameKind.PROBE_ACK: {"ok": True, "detail": ""},
    FrameKind.INVOKE: {"invoke_id": "i1", "deadline_ms": 1000, "budget_micros": 0},
    FrameKind.RESULT: {"invoke_id": "i1", "unit_index": 0, "status": "ok"},
    FrameKind.LOG: {"level": "debug", "message": "x"},
    FrameKind.PROGRESS: {"invoke_id": "i1", "done": 1, "total": 2},
    FrameKind.CANCEL: {"invoke_id": "i1"},
    FrameKind.SHUTDOWN: {},
    FrameKind.FATAL: {"failure_class": "driver_bug", "detail": "x"},
}


def _malformed() -> dict[str, bytes]:
    """The shapes a mutator is unlikely to reach, because they are about lengths and not content.

    Each name is what it asserts, and each maps to a `WireFault` member that is otherwise only
    reachable from a hand-written unit test.
    """
    deep = b"[" * (MAX_HEADER_DEPTH + 1) + b"]" * (MAX_HEADER_DEPTH + 1)
    return {
        "empty": b"",
        "short-prefix": b"\x00" * (PREFIX_BYTES - 1),
        "zero-lengths": b"\x00" * PREFIX_BYTES,
        # 0xFFFFFFFF both ways: eight bytes that claim 4 GiB of header and 4 GiB of body.
        # 04-driver-system.md:1791 is the sentence this seed exists for -- the caps are "checked
        # BEFORE any allocation" -- so the whole input stays eight bytes long.
        "four-gib-prefix": b"\xff\xff\xff\xff\xff\xff\xff\xff",
        "header-over-cap": (MAX_HEADER_BYTES + 1).to_bytes(4, "little") + b"\x00" * 4,
        "body-over-cap": b"\x02\x00\x00\x00" + (MAX_BODY_BYTES + 1).to_bytes(4, "little") + b"{}",
        "header-truncated": b"\x40\x00\x00\x00\x00\x00\x00\x00" + b'{"kind":"PROBE"}',
        "header-not-utf8": b"\x04\x00\x00\x00\x00\x00\x00\x00" + b"\xff\xfe\xfd\xfc",
        "header-not-json": b"\x03\x00\x00\x00\x00\x00\x00\x00" + b"not",
        "header-not-object": b"\x02\x00\x00\x00\x00\x00\x00\x00" + b"[]",
        "kind-absent": b"\x02\x00\x00\x00\x00\x00\x00\x00" + b"{}",
        "kind-unknown": len(b'{"kind":"NOPE"}').to_bytes(4, "little")
        + b"\x00" * 4
        + b'{"kind":"NOPE"}',
        "header-too-deep": len(deep).to_bytes(4, "little") + b"\x00" * 4 + deep,
    }


def write_seeds(directory: Path) -> list[Path]:
    """One valid frame per kind plus the length-shaped malformed set. LF-free; these are bytes."""
    directory.mkdir(parents=True, exist_ok=True)
    for stale in sorted(directory.iterdir()):
        if stale.is_file():
            stale.unlink()
    written: list[Path] = []
    for kind, header in HEADERS.items():
        path = directory / f"valid-{kind.name.lower()}"
        path.write_bytes(encode(kind, header, b"body" if kind is FrameKind.INVOKE else b""))
        written.append(path)
    for name, data in _malformed().items():
        path = directory / name
        path.write_bytes(data)
        written.append(path)
    return sorted(written)


EXTRAS: tuple[Input, ...] = tuple(
    # Two inputs a corpus directory cannot hold. `at-header-cap` is 1 MiB and `at-body-cap` is
    # 256 KiB; committing them would spend 1.25 MB of the repository on two files whose whole
    # content is a length, and a seed corpus that a reviewer will not open is a corpus nobody
    # checks. They are constructed here and replayed unmutated.
    Input("wire", "constructed", name, data)
    for name, data in (
        (
            "at-header-cap",
            MAX_HEADER_BYTES.to_bytes(4, "little") + b"\x00" * 4 + b"\x20" * MAX_HEADER_BYTES,
        ),
        (
            "at-body-cap",
            b"\x10\x00\x00\x00"
            + MAX_BODY_BYTES.to_bytes(4, "little")
            + b'{"kind":"PROBE"}'
            + b"\x00" * MAX_BODY_BYTES,
        ),
    )
)

TARGET = Target(
    name=NAME,
    probe=probe,
    # The one allowed type. What is therefore a finding is the module docstring's first
    # section, and the list is long on purpose.
    allowed=(DriverHostError,),
    corpora=((NAME, Path(__file__).resolve().parent.parent / "seeds" / NAME),),
    write_seeds=write_seeds,
    extras=EXTRAS,
)

__all__ = ["TARGET", "probe", "write_seeds"]

if __name__ == "__main__":
    raise SystemExit(main(TARGET))
