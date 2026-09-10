"""`omniweave-driver/1` framing. THE authoritative definition of the frame grammar.

Two length prefixes, a JSON header, a raw body, and three caps. Nothing else: no socket, no
pipe, no worker, no batching, no retry, no per-kind payload schema. 02-architecture.md:238
gives this module as "framing only, ~80 lines, fuzzed" and 04-driver-system.md:1685-1687
repeats it, so every mechanism that is not framing is deliberately somewhere else --
`host/subproc.py` owns the transport and the worker lifecycle (S4), `host/inproc.py` owns the
S1 call boundary, and `omniweave/run/dispatch.py` owns batching, retries and quarantine
(02-architecture.md:238's "does NOT" cell).

**This module is authoritative for the grammar.** `host/subproc.py` derives its `HELLO` /
`INVOKE` / `CANCEL` loop from the same two paragraphs of the plan, and where the two disagree
this file wins: the frame vocabulary, the direction of each kind, the wire spelling of `kind`
and the three caps are defined HERE and imported there. That is stated rather than implied
because the alternative -- two modules each parsing the same sentence -- is how a protocol
acquires two grammars.

## The grammar, and the line each part comes from

04-driver-system.md:1674-1676 prints it:

    Frame     ::= u32 header_len_le | u32 body_len_le | JSON header (UTF-8) | raw body bytes
    Transport ::= AF_UNIX SOCK_STREAM @ 0600  |  Windows named pipe, owner-only DACL
    INLINE_MAX = 262144 bytes for the BODY; anything larger travels as a blob ref.

The body is raw bytes so binary needs no base64 and core needs no MessagePack codec
(04-driver-system.md:1679; 12-performance.md:1132-1137 prices the refused alternative at a 4%
win for a C extension in a zero-dependency distribution). The eleven kinds and their
directions are 04-driver-system.md:1695-1705's table, whose first column is the kind's number
and whose second is its name.

## The three caps, and why they are refusals rather than checks

`MAX_HEADER_BYTES = 1 MiB` (02-architecture.md:238, :831; 04-driver-system.md:1686;
16-roadmap.md:482), `MAX_BODY_BYTES = INLINE_MAX` (the same four lines, and
02-architecture.md:809 for the number) and `MAX_HEADER_DEPTH = 32` (the same four lines, and
04-driver-system.md:1792 for the attack it answers).

04-driver-system.md:1791 is explicit about the mechanism and not only the number: for "a 4 GB
`header_len`", "`header_len <= 1 MiB` and `body_len <= INLINE_MAX` are checked **before** any
allocation; the reader allocates exactly the declared length and never speculatively". So
`decode_prefix()` is a pure function over eight bytes that refuses without ever asking for the
declared length, and `read_frame()` calls it BETWEEN the prefix read and the header read. A cap
applied after the read would allocate the 4 GiB it was written to refuse, which is the whole of
what a cap on a length field is for.

The depth cap is the same shape one level in. `json.loads` takes no depth parameter, so a header
nested 10,000 deep either raises `RecursionError` out of the pure-Python scanner or exhausts the
C stack in the accelerated one -- and `RecursionError` is not a NAMED protocol error, which is
exactly what the fuzz property forbids. `max_depth()` therefore scans the raw bytes, which are
already bounded by `MAX_HEADER_BYTES`, and the refusal happens before the recursive descent
begins. 04-driver-system.md:1792 says "enforced during parse"; enforcing it one step earlier is
strictly stronger and is the only way to keep the error named.

## Attribution: a framing fault is OURS

02-architecture.md:1060 (seam S4's row in section 7.5) fixes it: "A frame that violates
`wire.py`'s caps or carries an unknown `kind` is a `DriverHostError` (`OW-D-*`) -- **our** bug,
never the driver's." 02-architecture.md:1577 repeats it as the glossary entry, and
`omniweave_core.errors.DriverHostError`'s own docstring already cites this section. So every
refusal here raises `DriverHostError` and NEVER a `DriverError`, never `FailureClass.driver_bug`
and never `FailureClass.driver_crashed`: those three are the driver's, and a framework that
reports its own protocol bug as a third party's has told the operator to file the wrong issue.
The one failure_class that does cross this module is the one a `FATAL` or `RESULT` header
CARRIES -- the driver's own attribution, which framing transports verbatim and never invents.

`WireFault` names which refusal fired. It is a taxonomy and not a register: no `codes.toml`
numeric is invented here, so every refusal carries `DriverHostError`'s area default symbol
`OW_DRIVER_HOST` and prints the fault as the first token of its message. The plan says the
condition is `OW-D-*` and allocates no row for it, and that gap is reported rather than filled.

## What this module deliberately does not validate

The per-kind payload. `HELLO` must carry `{port, card_schema, card_sha256, driver_id,
effective_config, roots, blob_base, isolation_granted, traceparent}` and `HELLO_ACK` must be
checked against the card as `CARD_CODE_MISMATCH` "before work" (04-driver-system.md:1695-1696),
but that is a card comparison and not framing: it needs the card, and framing needs nothing.
`unit_index` validation against the batch (04-driver-system.md:1796) needs the batch. Both live
with the code that holds the other half. What framing guarantees to those callers is narrow and
total: a `Frame` exists only if its envelope was well formed, its kind is one of the eleven, its
header is a JSON object no deeper than 32, and its declared lengths were inside the caps.

Specified in 04-driver-system.md section 6.2 (:1668-1722) and section 6.5 (:1784-1804),
02-architecture.md section 2 row 14 (:238), section 5.6's S4 row (:831) and section 7.5's S4 row
(:1060), 16-roadmap.md:482 and 12-performance.md:1132-1137.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from types import MappingProxyType
from typing import Final, NoReturn, TypeAlias

from omniweave_core.canonical import JsonValue, canonical
from omniweave_core.errors import DriverHostError
from omniweave_core.limits import INLINE_MAX

__all__ = [
    "DIRECTION_OF",
    "DRIVER_TO_HOST",
    "HOST_TO_DRIVER",
    "KIND_BY_NAME",
    "KIND_KEY",
    "MAX_BODY_BYTES",
    "MAX_HEADER_BYTES",
    "MAX_HEADER_DEPTH",
    "PREFIX_BYTES",
    "PROTOCOL",
    "Direction",
    "Frame",
    "FrameKind",
    "Recv",
    "WireFault",
    "decode",
    "decode_prefix",
    "encode",
    "max_depth",
    "read_frame",
]

PROTOCOL: Final[str] = "omniweave-driver/1"
"""The protocol name, 04-driver-system.md:1671. A frame does not carry it: the name is bound by
the worker's argv and by `HELLO`'s `card_schema`, and putting a version string in every frame
would be a second home for one fact (INV-21)."""

PREFIX_BYTES: Final[int] = 8
"""Two little-endian `u32` length fields, 04-driver-system.md:1674. Read as one 8-byte unit,
because the caps must be decidable from the smallest read the reader can make."""

MAX_HEADER_BYTES: Final[int] = 1_048_576
"""1 MiB: `header_len`'s ceiling, refused before the header is read.

02-architecture.md:238 and :831, 04-driver-system.md:1686 and 16-roadmap.md:482 all print
`header_len <= 1 MiB`, so the bound is 1,048,576 and the comparison is `<=`.

**Its home is here and that is our engineering call.** 02-architecture.md:231 makes
`omniweave_core.limits` the home of "every `MAX_*` ceiling", and this is one; but nothing in the
plan names the constant, `limits.py` does not carry it today, and `limits.py:467` instead
DESCRIBES this bound inside `INLINE_MAX`'s docstring ("Fuzzed in `omniweave_core.host.wire`
alongside `header_len <= 1 MiB` and a JSON depth of 32"). Moving it into `limits.py` is a
one-line mechanical extraction and is reported as owed."""

MAX_BODY_BYTES: Final[int] = INLINE_MAX
"""`body_len`'s ceiling, which is `INLINE_MAX` and is IMPORTED rather than restated.

04-driver-system.md:1676 says "INLINE_MAX = 262144 bytes for the BODY; anything larger travels
as a content-addressed blob ref", and INV-22 makes a limit a host constant with one home
(`omniweave_core.limits:464`, set by charter section 6.10). An alias is not a second home: this
name says which of the two length fields the ceiling governs, and its value is the one home's."""

MAX_HEADER_DEPTH: Final[int] = 32
"""The JSON nesting cap on a header. 02-architecture.md:238, :831; 04-driver-system.md:1686.

Depth 1 is a flat object, so a header of `{}` has depth 1 and `{"a":{"b":1}}` has depth 2. The
attack is 04-driver-system.md:1792's "a JSON header nested 10,000 deep". Same home caveat as
`MAX_HEADER_BYTES`."""

KIND_KEY: Final[str] = "kind"
"""The header key carrying the frame kind, and it is RESERVED: `Frame.header` never holds it.

04-driver-system.md:1693's table separates the kind from the "header payload", and `Frame` types
the kind, so keeping it in the mapping too would put one fact in two places on every frame
(INV-21). `encode()` inserts it and `decode()` removes it."""


class FrameKind(IntEnum):
    """The eleven frame kinds, numbered as 04-driver-system.md:1695-1705 numbers them.

    That table's first column is headed `kind` and runs 1..11 and its second is headed `name`,
    so the number and the name are both the plan's. `IntEnum` keeps the number available to a
    reader of the table while the WIRE spelling is the NAME -- see `encode()`, which writes
    `{"kind": "HELLO"}`. The name is the wire form because charter section 5 C9 makes the
    SCREAMING_SNAKE symbol the stored and wire form of every closed vocabulary in the framework,
    because every other line of the plan refers to these frames by name (`RESULT`, `FATAL`,
    `PROGRESS`), and because a mis-framed integer is indistinguishable from a valid one in a
    hexdump while a mis-framed name is not.

    Eleven, counted from the table's own rows: HELLO, HELLO_ACK, PROBE, PROBE_ACK, INVOKE,
    RESULT, LOG, PROGRESS, CANCEL, SHUTDOWN, FATAL. 04-driver-system.md:1690 states "Eleven
    frame kinds" and its table prints eleven, so the number and the enumeration agree.
    """

    HELLO = 1
    HELLO_ACK = 2
    PROBE = 3
    PROBE_ACK = 4
    INVOKE = 5
    RESULT = 6
    LOG = 7
    PROGRESS = 8
    CANCEL = 9
    SHUTDOWN = 10
    FATAL = 11


class Direction(StrEnum):
    """Which side may SEND a kind. 04-driver-system.md:1693's third column, verbatim.

    A direction is not decoration: a driver that sends `INVOKE` is either confused or hostile,
    and a host that accepts one has given a third party the ability to drive its own protocol.
    `read_frame(..., expect=...)` is where a reader states which half it is willing to hear.
    """

    HOST_TO_DRIVER = "host_to_driver"
    DRIVER_TO_HOST = "driver_to_host"


DIRECTION_OF: Final[Mapping[FrameKind, Direction]] = MappingProxyType(
    {
        FrameKind.HELLO: Direction.HOST_TO_DRIVER,
        FrameKind.HELLO_ACK: Direction.DRIVER_TO_HOST,
        FrameKind.PROBE: Direction.HOST_TO_DRIVER,
        FrameKind.PROBE_ACK: Direction.DRIVER_TO_HOST,
        FrameKind.INVOKE: Direction.HOST_TO_DRIVER,
        FrameKind.RESULT: Direction.DRIVER_TO_HOST,
        FrameKind.LOG: Direction.DRIVER_TO_HOST,
        FrameKind.PROGRESS: Direction.DRIVER_TO_HOST,
        FrameKind.CANCEL: Direction.HOST_TO_DRIVER,
        FrameKind.SHUTDOWN: Direction.HOST_TO_DRIVER,
        FrameKind.FATAL: Direction.DRIVER_TO_HOST,
    }
)
"""One row per kind, transcribed from 04-driver-system.md:1695-1705's `direction` column."""

HOST_TO_DRIVER: Final[frozenset[FrameKind]] = frozenset(
    kind for kind, side in DIRECTION_OF.items() if side is Direction.HOST_TO_DRIVER
)
"""`HELLO`, `PROBE`, `INVOKE`, `CANCEL`, `SHUTDOWN` -- the five the host may send."""

DRIVER_TO_HOST: Final[frozenset[FrameKind]] = frozenset(
    kind for kind, side in DIRECTION_OF.items() if side is Direction.DRIVER_TO_HOST
)
"""`HELLO_ACK`, `PROBE_ACK`, `RESULT`, `LOG`, `PROGRESS`, `FATAL` -- the six the driver may."""

KIND_BY_NAME: Final[Mapping[str, FrameKind]] = MappingProxyType(
    {kind.name: kind for kind in FrameKind}
)
"""The wire spelling -> the kind. Derived from `FrameKind`, so it cannot drift from it."""

_QUOTE: Final[int] = 0x22
_BACKSLASH: Final[int] = 0x5C
_OPENERS: Final[frozenset[int]] = frozenset({0x7B, 0x5B})  # { [
_CLOSERS: Final[frozenset[int]] = frozenset({0x7D, 0x5D})  # } ]
"""The four JSON structural bytes and the two string bytes `max_depth()` scans for.

Named rather than inline because a depth scanner comparing raw byte values is exactly the code
a reader must be able to check against the JSON grammar without decoding hex in their head."""


class WireFault(StrEnum):
    """Why a frame was refused. A taxonomy, NOT a `codes.toml` register.

    Every member is a condition the plan names or a shape the grammar forbids, and each one is
    reachable by a targeted test in `test_host_wire.py` -- a closed set pinned against one
    excluded member is pinned against nothing, so it is pinned member by member instead.

    No numeric is invented for these. 02-architecture.md:1060 says the condition is a
    `DriverHostError` in area `OW-D-*` and the register allocates no row for it, so a refusal
    carries the area default symbol and names the fault in its message. Reported as a gap.
    """

    SHORT_PREFIX = "short_prefix"
    HEADER_ABSENT = "header_absent"
    HEADER_TOO_LARGE = "header_too_large"
    BODY_TOO_LARGE = "body_too_large"
    HEADER_TRUNCATED = "header_truncated"
    BODY_TRUNCATED = "body_truncated"
    HEADER_NOT_UTF8 = "header_not_utf8"
    HEADER_NOT_JSON = "header_not_json"
    HEADER_NOT_OBJECT = "header_not_object"
    HEADER_TOO_DEEP = "header_too_deep"
    KIND_ABSENT = "kind_absent"
    KIND_UNKNOWN = "kind_unknown"
    KIND_RESERVED = "kind_reserved"
    DIRECTION_UNEXPECTED = "direction_unexpected"


Recv: TypeAlias = Callable[[int], bytes]
"""`recv(n) -> bytes`: read AT MOST `n` bytes, returning fewer only at end of stream.

The reader is a parameter because framing owns no transport: `host/subproc.py` supplies a
socket's or a pipe's read, a test supplies a function over a `bytes`, and neither `socket` nor
`selectors` nor `asyncio` is imported here (G23, INV-3). A short return is a truncation fault
and never a silent partial frame.
"""


@dataclass(frozen=True, slots=True)
class Frame:
    """One well-formed frame. Existence is the guarantee: nothing malformed is representable.

    `header` excludes `KIND_KEY` and `body` is the raw bytes, unexamined -- "the body is raw
    bytes, so binary needs no base64" (04-driver-system.md:1679). Framing makes no claim about
    which payload keys a kind carries; see the module docstring's last section.
    """

    kind: FrameKind
    header: Mapping[str, JsonValue]
    body: bytes = b""

    @property
    def direction(self) -> Direction:
        """Which side is allowed to have sent this. 04-driver-system.md:1693's third column."""
        return DIRECTION_OF[self.kind]


def _refuse(fault: WireFault, detail: str) -> NoReturn:
    """Raise the one error every framing refusal raises. 02-architecture.md:1060.

    `DriverHostError` and not `DriverError`: the fault is ours. The fault value leads the
    message so a caller can identify it without a second register, and `fix` is
    `ow doctor --runtime`, the verb 04-driver-system.md:1777 gives for the runtime's own health.
    """
    raise DriverHostError(
        f"{fault.value}: {detail}",
        fix="ow doctor --runtime --render json   # attach the report to the issue",
    )


def max_depth(raw: bytes) -> int:
    r"""The maximum JSON nesting depth of `raw`, by a byte scan and never by parsing it.

    A flat object is 1. String contents are skipped, with `\` escaping the next byte, so a
    `"{{{{"` inside a string value counts for nothing -- an implementation that scanned without
    string awareness would refuse a legal header carrying a JSON fragment as a string, and an
    `INVOKE` header's `effective_config` can carry exactly that.

    The scan is O(len) over an input already bounded by `MAX_HEADER_BYTES`, so it is a bounded
    cost paid to keep the depth refusal a NAMED error rather than a `RecursionError` from
    `json.loads`, which takes no depth parameter (see the module docstring).
    """
    depth = 0
    deepest = 0
    in_string = False
    escaped = False
    for byte in raw:
        if in_string:
            if escaped:
                escaped = False
            elif byte == _BACKSLASH:  # the next byte is data, whatever it is
                escaped = True
            elif byte == _QUOTE:
                in_string = False
            continue
        if byte == _QUOTE:
            in_string = True
        elif byte in _OPENERS:
            depth += 1
            deepest = max(deepest, depth)
        elif byte in _CLOSERS:
            depth -= 1
    return deepest


def decode_prefix(prefix: bytes) -> tuple[int, int]:
    """The eight-byte prefix -> `(header_len, body_len)`, WITH the caps applied.

    **This is the pre-allocation refusal.** It is a pure function of eight bytes: it reads no
    stream, allocates nothing proportional to what it was told, and refuses a declared length
    above a cap before any caller has had the chance to ask for it. 04-driver-system.md:1791 --
    "checked **before** any allocation; the reader allocates exactly the declared length and
    never speculatively".

    The header is checked before the body because the header is the first field on the wire, so
    a frame violating both reports the earlier one -- the same principle that makes `resolve()`'s
    gate order observable.
    """
    if len(prefix) != PREFIX_BYTES:
        _refuse(
            WireFault.SHORT_PREFIX,
            f"a frame prefix is {PREFIX_BYTES} bytes (u32 header_len_le, u32 body_len_le); "
            f"got {len(prefix)}",
        )
    header_len = int.from_bytes(prefix[:4], "little")
    body_len = int.from_bytes(prefix[4:], "little")
    if header_len == 0:
        _refuse(WireFault.HEADER_ABSENT, "header_len = 0; every frame carries a JSON header")
    if header_len > MAX_HEADER_BYTES:
        _refuse(
            WireFault.HEADER_TOO_LARGE,
            f"header_len = {header_len} > MAX_HEADER_BYTES = {MAX_HEADER_BYTES}; refused before "
            f"the header was read",
        )
    if body_len > MAX_BODY_BYTES:
        _refuse(
            WireFault.BODY_TOO_LARGE,
            f"body_len = {body_len} > MAX_BODY_BYTES = {MAX_BODY_BYTES} (INLINE_MAX); a larger "
            f"body travels as a content-addressed blob ref",
        )
    return header_len, body_len


def decode(header_raw: bytes, body: bytes = b"") -> Frame:
    """Header bytes plus body bytes -> a `Frame`. Pure; the length caps are the caller's.

    The order is deliberate: UTF-8, then depth, then JSON, then shape, then kind. Depth precedes
    `json.loads` because that is what keeps the refusal named; `kind` is last because the kind's
    own vocabulary check is meaningless until the header is known to be an object.
    """
    try:
        text = header_raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        _refuse(WireFault.HEADER_NOT_UTF8, f"the header is not UTF-8: {exc}")
    depth = max_depth(header_raw)
    if depth > MAX_HEADER_DEPTH:
        _refuse(
            WireFault.HEADER_TOO_DEEP,
            f"header nesting depth {depth} > MAX_HEADER_DEPTH = {MAX_HEADER_DEPTH}; refused "
            f"before json.loads, which takes no depth parameter",
        )
    try:
        parsed = json.loads(text)
    except (ValueError, RecursionError) as exc:
        _refuse(WireFault.HEADER_NOT_JSON, f"the header is not JSON: {exc}")
    if not isinstance(parsed, dict):
        _refuse(
            WireFault.HEADER_NOT_OBJECT,
            f"the header is a JSON {type(parsed).__name__} and not an object",
        )
    raw_kind = parsed.pop(KIND_KEY, None)
    if raw_kind is None:
        _refuse(WireFault.KIND_ABSENT, f"the header carries no {KIND_KEY!r}")
    if not isinstance(raw_kind, str) or raw_kind not in KIND_BY_NAME:
        _refuse(
            WireFault.KIND_UNKNOWN,
            f"{raw_kind!r} is not one of the eleven kinds {sorted(KIND_BY_NAME)}; an unknown "
            f"kind is OUR protocol error (02-architecture.md:1060), never the driver's",
        )
    return Frame(kind=KIND_BY_NAME[raw_kind], header=MappingProxyType(parsed), body=body)


def encode(kind: FrameKind, header: Mapping[str, JsonValue], body: bytes = b"") -> bytes:
    """A frame as bytes: `u32 header_len_le | u32 body_len_le | JSON header | raw body`.

    The caps are applied on the way OUT as well, and that is not symmetry for its own sake: a
    host that can emit a 2 MiB `HELLO` has built a frame its own reader must refuse, and the bug
    then surfaces on the far side of a process boundary. The header is encoded through
    `omniweave_core.canonical.canonical` -- sorted keys, no whitespace, no NaN, no cycles, no
    lone surrogates -- so two hosts framing the same header produce the same bytes.
    """
    if KIND_KEY in header:
        _refuse(
            WireFault.KIND_RESERVED,
            f"{KIND_KEY!r} is the framing's own key and is not part of a header payload; pass "
            f"the kind as the `kind` argument",
        )
    header_raw = canonical({**dict(header), KIND_KEY: kind.name})
    if len(header_raw) > MAX_HEADER_BYTES:
        _refuse(
            WireFault.HEADER_TOO_LARGE,
            f"the encoded header is {len(header_raw)} bytes > MAX_HEADER_BYTES = "
            f"{MAX_HEADER_BYTES}",
        )
    depth = max_depth(header_raw)
    if depth > MAX_HEADER_DEPTH:
        _refuse(
            WireFault.HEADER_TOO_DEEP,
            f"the encoded header nests {depth} deep > MAX_HEADER_DEPTH = {MAX_HEADER_DEPTH}",
        )
    if len(body) > MAX_BODY_BYTES:
        _refuse(
            WireFault.BODY_TOO_LARGE,
            f"the body is {len(body)} bytes > MAX_BODY_BYTES = {MAX_BODY_BYTES} (INLINE_MAX)",
        )
    return (
        len(header_raw).to_bytes(4, "little") + len(body).to_bytes(4, "little") + header_raw + body
    )


def read_frame(recv: Recv, *, expect: Direction | None = None) -> Frame:
    """Read exactly one frame through `recv`, refusing before it asks for what it will not take.

    Three reads at most, and the second and third are made only after `decode_prefix()` has
    accepted the declared lengths -- so a prefix declaring 4 GiB costs one 8-byte read and a
    raise, and the reader "allocates exactly the declared length and never speculatively"
    (04-driver-system.md:1791). `recv(0)` is never called: a bodyless frame does no body read.

    `expect` states which half of the conversation the caller is entitled to hear. It defaults to
    `None` -- "either" -- because a test harness and a conformance kit legitimately read both
    sides of a recorded exchange, while a live reader on either end of the socket passes the
    direction it accepts. A frame from the wrong side is refused AFTER the envelope is parsed,
    because naming the kind is what makes the refusal diagnosable.
    """
    prefix = recv(PREFIX_BYTES)
    header_len, body_len = decode_prefix(prefix)
    header_raw = recv(header_len)
    if len(header_raw) != header_len:
        _refuse(
            WireFault.HEADER_TRUNCATED,
            f"header_len = {header_len} and the stream gave {len(header_raw)} bytes",
        )
    body = recv(body_len) if body_len else b""
    if len(body) != body_len:
        _refuse(
            WireFault.BODY_TRUNCATED,
            f"body_len = {body_len} and the stream gave {len(body)} bytes",
        )
    frame = decode(header_raw, body)
    if expect is not None and frame.direction is not expect:
        _refuse(
            WireFault.DIRECTION_UNEXPECTED,
            f"{frame.kind.name} is {frame.direction.value} and this reader accepts "
            f"{expect.value} only",
        )
    return frame
