"""`omniweave-driver/1` framing: the grammar, the three caps, the attribution, and a sweep.

Where the plan document is the authority this file READS the document rather than restating it:
the eleven kinds and their directions are re-derived from 04-driver-system.md's own table and the
three caps from 02-architecture.md's own S4 cell, so a test cannot pass by agreeing with a number
this file made up. The positions that are OUR engineering call -- the kind numbers as an
`IntEnum`, the wire spelling of `kind`, the `WireFault` taxonomy, the header-before-body order of
the cap refusals -- are pinned as literals beside those, because an order pinned only where the
document prints it leaves the positions we chose pinned by nothing.

The five families:

* **the grammar** -- the eleven kinds, their numbers, their directions, and the byte layout of
  the prefix. Pinned twice: once against the document's table and once as a literal.
* **the caps as refusals before allocation** -- 04-driver-system.md:1791 says the caps are
  "checked **before** any allocation; the reader allocates exactly the declared length and never
  speculatively". A test that fed a 4 GiB declared length and only asserted a refusal would pass
  against a reader that allocated 4 GiB first, so the reads themselves are recorded and the
  assertion is that the reader NEVER ASKED for the declared length. Both boundary values of all
  three caps are pinned, because a cap tested only from above is a cap whose comparison could be
  `<` or `<=` and nobody would know.
* **attribution** -- 02-architecture.md:1060: an unknown `kind` or a cap violation is a
  `DriverHostError`, "**our** bug, never the driver's". Tested in both directions: the framing
  fault is ours, and a `FATAL` frame's `failure_class` is the driver's and crosses unchanged. A
  test for the first alone would pass against a module that attributed EVERYTHING to us.
* **every `WireFault` is reachable** -- one targeted case per member, and the parametrisation is
  checked for completeness against the enum, so a fifteenth member cannot be added without a
  case. A closed set pinned against one excluded member is pinned against nothing.
* **the sweep** -- 16-roadmap.md:482 prices W3.2 with "an atheris target", and atheris is a
  third-party package that INV-2 bars from core and that 11-repo-layout.md:1497 marks
  `sys_platform == 'linux'` -- it does not install on this Windows cell at all. What stands in
  for it is a derandomised sweep: a keyed `blake2b` corpus (11-repo-layout.md:2185 -- "Sampling
  is blake2b. Determinism is a gate, not a habit."), 4,096 mutated frames, and the assertion that
  every one of them either parses to a well-formed `Frame` or raises a NAMED `WireFault` --
  never a bare exception, never a hang, never a read the caps forbid. The corpus digest is pinned
  as a literal so the sweep is the same sweep on every machine. The atheris target itself is
  reported as owed, with the phase that owns it.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Final

import pytest

# `DriverHostError` is bound by DIRECT IMPORT below, and is deliberately never spelled
# `errors.DriverHostError` in an assertion. `test_errors.py`'s
# `test_the_register_is_read_at_use_time_and_memoised` calls `importlib.reload(errors)` to reset a
# memoised register read, and a reload rebuilds every class object in the module. The module
# ATTRIBUTE therefore names the post-reload class while `wire.py` -- imported once, before any of
# that -- still raises the pre-reload one, so `pytest.raises(errors.DriverHostError)` stops
# matching in a full-suite run while passing when this file runs alone. That is the worst
# available failure mode, and a direct import is what avoids it: it binds at this module's import,
# exactly as `wire.py`'s own import does, so the two name one object under every collection order.
# The one surviving `errors.` use is the area-map assertion, where BOTH sides are module
# attributes read in the same expression and the generation therefore cancels out.
from omniweave_core import errors, limits
from omniweave_core.canonical import JsonValue
from omniweave_core.errors import DriverHostError
from omniweave_core.host import wire
from omniweave_core.host.wire import (
    DIRECTION_OF,
    DRIVER_TO_HOST,
    HOST_TO_DRIVER,
    KIND_BY_NAME,
    KIND_KEY,
    MAX_BODY_BYTES,
    MAX_HEADER_BYTES,
    MAX_HEADER_DEPTH,
    PREFIX_BYTES,
    Direction,
    Frame,
    FrameKind,
    WireFault,
    decode,
    decode_prefix,
    encode,
    max_depth,
    read_frame,
)
from omniweave_ports.types import DriverError, FailureClass

PLAN: Final = Path(__file__).resolve().parents[4] / "_plan"
"""`packages/omniweave-core/tests/unit/` -> the repo root's `_plan/`. Four parents up."""


# --------------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------------


class Stream:
    """A `Recv` over a fixed `bytes`, recording every read the reader made.

    The recording is the point: it is what turns "a huge declared length is refused" into "a huge
    declared length is refused WITHOUT the reader asking for it", which is the property
    04-driver-system.md:1791 actually states. `served` is what the reader was given and
    `requested` is what it asked for; the two differ exactly when a stream is short.
    """

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0
        self.requested: list[int] = []
        self.served = 0

    def recv(self, n: int) -> bytes:
        self.requested.append(n)
        chunk = self.data[self.pos : self.pos + n]
        self.pos += len(chunk)
        self.served += len(chunk)
        return chunk


def prefix(header_len: int, body_len: int) -> bytes:
    """The eight-byte prefix, built here by hand so the layout is asserted and not reused."""
    return header_len.to_bytes(4, "little") + body_len.to_bytes(4, "little")


def nested(depth: int) -> bytes:
    """A JSON object whose nesting depth is exactly `depth`, with a `kind` at the top level."""
    inner = "1"
    for _ in range(depth - 1):
        inner = "{" + f'"a":{inner}' + "}"
    return ('{"kind":"LOG","x":' + inner + "}").encode()


def fault_of(exc: DriverHostError) -> str:
    """The `WireFault` value leading a refusal's message."""
    return str(exc).split(":", 1)[0]


def plan_lines(name: str) -> list[str]:
    return (PLAN / name).read_text(encoding="utf-8").splitlines()


# --------------------------------------------------------------------------------------------
# 1. The grammar, derived from the plan and then pinned as a literal
# --------------------------------------------------------------------------------------------

KIND_ROW: Final = re.compile(r"^\|\s*(\d+)\s*\|\s*`([A-Z_]+)`\s*\|\s*(host→drv|drv→host)\s*\|")
"""04-driver-system.md:1695-1705's rows: `| 1 | \\`HELLO\\` | host→drv | {...} |`."""


def plan_frame_table() -> list[tuple[int, str, str]]:
    """The plan's own eleven rows, as `(number, name, direction)`."""
    rows: list[tuple[int, str, str]] = []
    for line in plan_lines("04-driver-system.md"):
        match = KIND_ROW.match(line)
        if match is not None:
            rows.append((int(match.group(1)), match.group(2), match.group(3)))
    return rows


def test_the_frame_table_this_file_reads_is_the_one_the_plan_prints() -> None:
    """The regex finds eleven rows and no more, so the derivation below is over the right table.

    Without this the two document-derived tests could both pass over an empty match set, and an
    assertion over an empty collection passes and proves nothing.
    """
    rows = plan_frame_table()
    assert len(rows) == 11
    assert [number for number, _, _ in rows] == list(range(1, 12))


def test_the_eleven_kinds_are_named_and_numbered_as_the_plans_table_names_them() -> None:
    """04-driver-system.md:1695-1705. The number is the table's first column and the name its
    second, so `FrameKind` is that table and not a re-invention of it."""
    assert {name: number for number, name, _ in plan_frame_table()} == {
        kind.name: int(kind) for kind in FrameKind
    }


def test_each_kinds_direction_is_the_one_the_plans_table_gives_it() -> None:
    """The third column, mapped `host→drv` -> `HOST_TO_DRIVER` and `drv→host` -> its converse."""
    arrows = {"host→drv": Direction.HOST_TO_DRIVER, "drv→host": Direction.DRIVER_TO_HOST}
    assert {KIND_BY_NAME[name]: arrows[arrow] for _, name, arrow in plan_frame_table()} == dict(
        DIRECTION_OF
    )


def test_the_prose_count_of_frame_kinds_agrees_with_the_table_beneath_it() -> None:
    """04-driver-system.md:1690 says "Eleven frame kinds" and its table prints eleven rows.

    The count and the enumeration AGREE here, which is worth an assertion precisely because two
    other tallies in the same document do not: :1557 says "Twenty-five `RejectCode` members" over
    a table of twenty-six and 16-roadmap.md:481 prices W3.1 at "eight gates" over a spec printing
    sixteen. A stated number is a claim, and this one holds.
    """
    prose = [line for line in plan_lines("04-driver-system.md") if "frame kinds." in line]
    assert len(prose) == 1
    assert prose[0].startswith("Eleven frame kinds.")
    assert len(plan_frame_table()) == 11


def test_the_kind_vocabulary_is_pinned_as_a_literal_in_the_plans_own_order() -> None:
    """The names and numbers, written out, so the document-derived tests are not the only pin."""
    assert [(kind.name, int(kind)) for kind in FrameKind] == [
        ("HELLO", 1),
        ("HELLO_ACK", 2),
        ("PROBE", 3),
        ("PROBE_ACK", 4),
        ("INVOKE", 5),
        ("RESULT", 6),
        ("LOG", 7),
        ("PROGRESS", 8),
        ("CANCEL", 9),
        ("SHUTDOWN", 10),
        ("FATAL", 11),
    ]


def test_the_two_directions_partition_the_eleven_kinds_five_and_six() -> None:
    """Five host-to-driver and six driver-to-host, pinned as literal sets.

    A partition is two claims -- covers everything, overlaps nowhere -- and both are asserted,
    because a kind absent from both sets would make `read_frame(expect=...)` refuse a legal frame
    and a kind in both would make it accept an illegal one.
    """
    assert {kind.name for kind in HOST_TO_DRIVER} == {
        "HELLO",
        "PROBE",
        "INVOKE",
        "CANCEL",
        "SHUTDOWN",
    }
    assert {kind.name for kind in DRIVER_TO_HOST} == {
        "HELLO_ACK",
        "PROBE_ACK",
        "RESULT",
        "LOG",
        "PROGRESS",
        "FATAL",
    }
    assert set(FrameKind) == HOST_TO_DRIVER | DRIVER_TO_HOST
    assert not HOST_TO_DRIVER & DRIVER_TO_HOST
    # The two VALUES are ours -- the plan's column prints `host→drv` and `drv→host`, and the
    # snake_case spelling is charter section 5 C9's stored form of a closed vocabulary. Changing
    # them to `host2drv` / `drv2host` left every other test in this file green, and they are what
    # the `direction_unexpected` refusal prints, so they are pinned as literals here.
    assert [direction.value for direction in Direction] == ["host_to_driver", "driver_to_host"]


# --------------------------------------------------------------------------------------------
# 2. The three caps: the numbers, their home, and both sides of each boundary
# --------------------------------------------------------------------------------------------

S4_CELL: Final = re.compile(
    r"`wire\.py` caps `header_len` at (?P<header>[\d.]+ MiB), `body_len` at "
    r"`(?P<body>\w+)` and JSON depth at (?P<depth>\d+)"
)
"""02-architecture.md:831's S4 cell, which prints all three caps in one sentence."""


def test_the_three_caps_are_the_three_numbers_the_plans_s4_cell_prints() -> None:
    """02-architecture.md:831 is the definition site that carries all three in one clause."""
    found = [S4_CELL.search(line) for line in plan_lines("02-architecture.md")]
    matches = [match for match in found if match is not None]
    assert len(matches) == 1
    cell = matches[0]
    assert cell.group("header") == "1 MiB"
    assert MAX_HEADER_BYTES == 1024 * 1024
    assert cell.group("body") == "INLINE_MAX"
    assert int(cell.group("depth")) == MAX_HEADER_DEPTH


def test_the_three_caps_are_pinned_as_literals_as_well_as_derived() -> None:
    """1,048,576 header bytes, 262,144 body bytes, depth 32, eight prefix bytes."""
    assert MAX_HEADER_BYTES == 1_048_576
    assert MAX_BODY_BYTES == 262_144
    assert MAX_HEADER_DEPTH == 32
    assert PREFIX_BYTES == 8


def test_the_body_cap_is_the_one_home_of_inline_max_and_not_a_second_copy() -> None:
    """INV-22 makes a limit a host constant with ONE home, `omniweave_core.limits:464`.

    Both halves are asserted: the value, as a literal, so the test pins a number and not merely
    an agreement between two names that could drift together; and the identity, so `wire.py`
    cannot be carrying a private 262,144 of its own.
    """
    assert limits.INLINE_MAX == 262_144
    assert MAX_BODY_BYTES == limits.INLINE_MAX


@pytest.mark.parametrize(
    ("header_len", "body_len"),
    [
        (1, 0),
        (MAX_HEADER_BYTES, 0),
        (1, MAX_BODY_BYTES),
        (MAX_HEADER_BYTES, MAX_BODY_BYTES),
    ],
)
def test_a_declared_length_exactly_at_a_cap_is_accepted(header_len: int, body_len: int) -> None:
    """The comparison is `<=`: the plan prints `header_len <= 1 MiB` and `body_len <= INLINE_MAX`.

    Tested from BELOW as well as above, because a cap only ever tested from above cannot
    distinguish `<` from `<=` and one of the two refuses a legal maximum-size frame.
    """
    assert decode_prefix(prefix(header_len, body_len)) == (header_len, body_len)


def test_a_prefix_declaring_four_gibibytes_of_header_is_refused_before_the_read() -> None:
    """04-driver-system.md:1791's first hostile row: "a 4 GB `header_len`".

    The assertion that matters is the last one: the reader asked for eight bytes and nothing else,
    so no allocation proportional to the declared length was ever attempted. A test asserting the
    refusal alone would pass against a reader that allocated 4 GiB first and checked afterwards,
    which is the bug the cap exists to prevent.
    """
    stream = Stream(b"\xff\xff\xff\xff" + b"\x02\x00\x00\x00")
    with pytest.raises(DriverHostError) as caught:
        read_frame(stream.recv)
    assert fault_of(caught.value) == WireFault.HEADER_TOO_LARGE.value
    assert stream.requested == [PREFIX_BYTES]
    assert stream.served == PREFIX_BYTES


def test_a_prefix_declaring_four_gibibytes_of_body_is_refused_before_any_read_of_either() -> None:
    """The body cap refuses at the same instant -- before the HEADER is read, let alone the body.

    That is stronger than it looks: the reader has a legal header length in hand and still does
    not read it, because a frame whose body it will refuse is a frame it will never assemble.
    """
    stream = Stream(prefix(32, 0xFFFFFFFF))
    with pytest.raises(DriverHostError) as caught:
        read_frame(stream.recv)
    assert fault_of(caught.value) == WireFault.BODY_TOO_LARGE.value
    assert stream.requested == [PREFIX_BYTES]


def test_a_frame_violating_both_length_caps_reports_the_header_one() -> None:
    """OUR order, pinned here because the plan does not print one.

    The header is the first field on the wire, so the earlier violation is the one reported --
    the same principle that makes `resolve()`'s gate order observable through the code it returns.
    """
    with pytest.raises(DriverHostError) as caught:
        decode_prefix(prefix(MAX_HEADER_BYTES + 1, MAX_BODY_BYTES + 1))
    assert fault_of(caught.value) == WireFault.HEADER_TOO_LARGE.value


@pytest.mark.parametrize(
    ("header_len", "body_len", "fault"),
    [
        (MAX_HEADER_BYTES + 1, 0, WireFault.HEADER_TOO_LARGE),
        (1, MAX_BODY_BYTES + 1, WireFault.BODY_TOO_LARGE),
    ],
)
def test_one_byte_over_a_cap_is_refused(header_len: int, body_len: int, fault: WireFault) -> None:
    """The other side of the boundary, one byte out, for each of the two length caps."""
    with pytest.raises(DriverHostError) as caught:
        decode_prefix(prefix(header_len, body_len))
    assert fault_of(caught.value) == fault.value


def test_encode_refuses_a_body_over_the_cap_so_a_host_cannot_emit_what_it_would_refuse() -> None:
    """The caps apply outbound too. A host that can frame it can frame a bug across a process
    boundary, where it surfaces as the far side's protocol error."""
    with pytest.raises(DriverHostError) as caught:
        encode(FrameKind.RESULT, {"invoke_id": "i"}, b"\x00" * (MAX_BODY_BYTES + 1))
    assert fault_of(caught.value) == WireFault.BODY_TOO_LARGE.value
    assert len(encode(FrameKind.RESULT, {"invoke_id": "i"}, b"\x00" * MAX_BODY_BYTES)) == (
        PREFIX_BYTES + MAX_BODY_BYTES + 33
    )


PAD_OVERHEAD: Final = 25
"""`len(canonical({"kind": "HELLO", "pad": ""}))` -- `{"kind":"HELLO","pad":""}`, written out.

A literal and not a `len()` call, so the two encode-cap tests below build a header of a KNOWN
total size instead of one whose size is whatever the encoder happens to produce."""


def padded(total: int) -> Mapping[str, JsonValue]:
    """A `HELLO` header whose CANONICAL encoding is exactly `total` bytes, `kind` included."""
    return {"pad": "x" * (total - PAD_OVERHEAD)}


def test_encode_refuses_a_header_over_the_header_cap_and_accepts_one_exactly_at_it() -> None:
    """The outbound HEADER cap, which nothing else in this file exercised.

    `encode()`'s docstring claims all three caps are applied on the way out -- "a host that can
    emit a 2 MiB `HELLO` has built a frame its own reader must refuse". Only the body half was
    tested, so deleting the header-size check in `encode()` changed no test's colour. Both sides
    of the boundary are here, because a cap tested only from above cannot distinguish `<` from
    `<=`, and the accepted case pins the encoded length as a LITERAL 1,048,576 so the test is not
    merely agreeing with the constant it imports.
    """
    at_cap = encode(FrameKind.HELLO, padded(MAX_HEADER_BYTES))
    assert len(at_cap) - PREFIX_BYTES == 1_048_576
    assert int.from_bytes(at_cap[:4], "little") == MAX_HEADER_BYTES
    with pytest.raises(DriverHostError) as caught:
        encode(FrameKind.HELLO, padded(MAX_HEADER_BYTES + 1))
    assert fault_of(caught.value) == WireFault.HEADER_TOO_LARGE.value
    assert str(MAX_HEADER_BYTES + 1) in str(caught.value)


def deep_header(depth: int) -> Mapping[str, JsonValue]:
    """A header mapping whose canonical encoding nests exactly `depth` deep.

    The outer object is 1, so `depth - 1` dicts hang off `"x"`. Built as Python objects and not
    as bytes, because `encode()` takes a `Mapping` and this is the outbound path.
    """
    inner: JsonValue = 1
    for _ in range(depth - 1):
        inner = {"a": inner}
    return {"x": inner}


def test_encode_refuses_a_header_deeper_than_the_depth_cap_and_accepts_one_exactly_at_it() -> None:
    """The outbound DEPTH cap, the third of `encode()`'s three and the other one nothing pinned.

    Deleting the depth check in `encode()` left every other test in this file green, so a host
    could frame a header its own reader refuses -- and that reader is on the far side of a
    process boundary, which is the failure `encode()`'s symmetry exists to prevent. `max_depth`
    over the produced bytes is asserted too, so the test pins the depth it believes it built.
    """
    at_cap = encode(FrameKind.INVOKE, deep_header(MAX_HEADER_DEPTH))
    assert max_depth(at_cap[PREFIX_BYTES:]) == 32
    assert read_frame(Stream(at_cap).recv).kind is FrameKind.INVOKE
    with pytest.raises(DriverHostError) as caught:
        encode(FrameKind.INVOKE, deep_header(MAX_HEADER_DEPTH + 1))
    assert fault_of(caught.value) == WireFault.HEADER_TOO_DEEP.value
    assert "33" in str(caught.value)


def test_the_protocol_name_is_the_one_the_plan_prints() -> None:
    """04-driver-system.md:1671 names the protocol `omniweave-driver/1`.

    `wire.PROTOCOL` is exported in `__all__`, is what `tools/ow_host.py:1010` prints as the
    worker's banner, and was asserted by nothing: changing it to `omniweave-driver/2` left the
    whole suite green. Pinned twice -- against the document's own sentence, and as a literal,
    because a value read out of the document and compared to itself pins agreement and not value.
    11-repo-layout.md:1100 makes the wire protocol a `CONTRACT`-MINOR surface, so its name is a
    released identity and not an internal string.
    """
    assert wire.PROTOCOL == "omniweave-driver/1"
    sentence = [
        line for line in plan_lines("04-driver-system.md") if line.startswith("over `omniweave-")
    ]
    assert len(sentence) == 1
    assert sentence[0] == f"over `{wire.PROTOCOL}` (seam S4):"


# --------------------------------------------------------------------------------------------
# 3. The depth cap, and why it is enforced before json.loads
# --------------------------------------------------------------------------------------------


def test_a_header_nested_to_the_cap_is_accepted_and_one_deeper_is_refused() -> None:
    """Depth 32 in, depth 33 out. Both sides of the boundary, over handwritten JSON."""
    assert max_depth(nested(MAX_HEADER_DEPTH)) == MAX_HEADER_DEPTH
    assert decode(nested(MAX_HEADER_DEPTH)).kind is FrameKind.LOG
    with pytest.raises(DriverHostError) as caught:
        decode(nested(MAX_HEADER_DEPTH + 1))
    assert fault_of(caught.value) == WireFault.HEADER_TOO_DEEP.value


def test_a_header_nested_ten_thousand_deep_raises_a_named_error_and_not_a_recursion_error() -> None:
    """04-driver-system.md:1792's second hostile row, and the reason the cap precedes the parse.

    `json.loads` takes no depth parameter, so a 10,000-deep header is a `RecursionError` -- which
    is not a NAMED protocol error and is exactly what the sweep below forbids. The assertion is
    therefore about the TYPE of the failure and not only about the fact of one: a
    `DriverHostError` naming `header_too_deep`, with no `RecursionError` anywhere in its chain.
    """
    deep = nested(10_000)
    with pytest.raises(DriverHostError) as caught:
        decode(deep)
    assert fault_of(caught.value) == WireFault.HEADER_TOO_DEEP.value
    assert caught.value.__cause__ is None
    assert not isinstance(caught.value.__context__, RecursionError)
    with pytest.raises(RecursionError):
        json.loads(deep)


@pytest.mark.parametrize(
    ("raw", "depth"),
    [
        (b"{}", 1),
        (b"[]", 1),
        (b'{"a":{"b":1}}', 2),
        (b'{"a":[{"b":1}]}', 3),
        (b'{"a":"{{{{{{"}', 1),
        (b'{"a":"\\"{{{"}', 1),
        (b'{"a":"\\\\"}', 1),
        (b'{"a":{},"b":{}}', 2),
    ],
)
def test_max_depth_counts_structure_and_never_string_contents(raw: bytes, depth: int) -> None:
    """A brace inside a string value is data.

    The `effective_config` an `INVOKE` header carries can legitimately hold a JSON document as a
    string, so a scanner without string awareness would refuse a legal frame -- and the escape
    cases are here because `"\\""` ends no string and `"\\\\"` does.
    """
    assert max_depth(raw) == depth


# --------------------------------------------------------------------------------------------
# 4. Attribution: the framing fault is ours, the failure_class is the driver's
# --------------------------------------------------------------------------------------------


def test_an_unknown_frame_kind_is_our_protocol_error_and_never_the_drivers() -> None:
    """02-architecture.md:1060: "an unknown `kind` is a protocol error attributed to **us**".

    Four assertions, because getting this backwards means a framework bug is filed against a
    third party: the error is a `DriverHostError` in the `OW-D-*` area; it is NOT a
    `DriverError`, which is the only thing a driver may raise; it names neither of the two
    `FailureClass` members that mean "the driver did this"; and it is fatal, so no retry ladder
    can absorb it.
    """
    raw = b'{"kind":"HANDSHAKE","x":1}'
    with pytest.raises(DriverHostError) as caught:
        decode(raw)
    exc = caught.value
    assert fault_of(exc) == WireFault.KIND_UNKNOWN.value
    assert not isinstance(exc, DriverError)
    assert errors.AREA_CLASSES["D"] is errors.DriverHostError
    assert exc.code() == "OW_DRIVER_HOST"
    assert FailureClass.DRIVER_BUG.value not in str(exc)
    assert FailureClass.DRIVER_CRASHED.value not in str(exc)
    assert exc.is_fatal()


def test_a_fatal_frames_failure_class_is_the_drivers_own_and_crosses_unchanged() -> None:
    """The positive control for the test above.

    04-driver-system.md:1705 gives `FATAL` as `{failure_class, detail}` -- "the driver's last
    words" -- and 02-architecture.md:1060 has the worker serialise the five `DriverError` fields
    into `RESULT`. Framing transports that attribution verbatim: it neither invents a
    `failure_class` nor rewrites one. Without this test, a module that attributed EVERYTHING to
    the framework would pass the whole attribution family.
    """
    frame = decode(
        encode(
            FrameKind.FATAL,
            {"failure_class": FailureClass.DRIVER_BUG.value, "detail": "unhandled KeyError"},
        )[PREFIX_BYTES:]
    )
    assert frame.kind is FrameKind.FATAL
    assert frame.header["failure_class"] == "driver_bug"
    assert frame.direction is Direction.DRIVER_TO_HOST


def test_every_framing_refusal_carries_the_runtime_doctor_command_as_its_fix() -> None:
    """`OwError.__init__` refuses an empty `fix`, and charter section 6.4 makes it the exact
    command that clears the error. For a protocol error that command is a report."""
    with pytest.raises(DriverHostError) as caught:
        decode(b"[]")
    assert caught.value.fix.startswith("ow doctor --runtime")


# --------------------------------------------------------------------------------------------
# 5. Every WireFault member is reachable, member by member
# --------------------------------------------------------------------------------------------


def _fault_case(fault: WireFault) -> tuple[bytes, Direction | None]:
    """One input per fault, as `(stream bytes, expect)`. Keyed by member, checked for coverage."""
    good = encode(FrameKind.LOG, {"level": "info", "event": "x"})
    cases: dict[WireFault, tuple[bytes, Direction | None]] = {
        WireFault.SHORT_PREFIX: (b"\x01\x02\x03", None),
        WireFault.HEADER_ABSENT: (prefix(0, 0), None),
        WireFault.HEADER_TOO_LARGE: (prefix(MAX_HEADER_BYTES + 1, 0), None),
        WireFault.BODY_TOO_LARGE: (prefix(8, MAX_BODY_BYTES + 1), None),
        WireFault.HEADER_TRUNCATED: (prefix(64, 0) + b'{"kind":"LOG"}', None),
        WireFault.BODY_TRUNCATED: (encode(FrameKind.RESULT, {"i": 1}, b"12345")[:-2], None),
        WireFault.HEADER_NOT_UTF8: (prefix(2, 0) + b"\xff\xfe", None),
        WireFault.HEADER_NOT_JSON: (prefix(3, 0) + b"{{{", None),
        WireFault.HEADER_NOT_OBJECT: (prefix(2, 0) + b"[]", None),
        WireFault.HEADER_TOO_DEEP: (
            prefix(len(nested(MAX_HEADER_DEPTH + 1)), 0) + nested(MAX_HEADER_DEPTH + 1),
            None,
        ),
        WireFault.KIND_ABSENT: (prefix(7, 0) + b'{"a":1}', None),
        WireFault.KIND_UNKNOWN: (prefix(16, 0) + b'{"kind":"NOPE"}\n'[:16], None),
        WireFault.KIND_RESERVED: (b"", None),
        WireFault.DIRECTION_UNEXPECTED: (good, Direction.HOST_TO_DRIVER),
    }
    return cases[fault]


@pytest.mark.parametrize("fault", list(WireFault))
def test_each_wire_fault_is_reachable_and_leads_its_own_message(fault: WireFault) -> None:
    """One case per member of the closed taxonomy.

    Parametrised over `list(WireFault)` rather than over a hand-written list, so a fifteenth
    member arrives as a `KeyError` in `_fault_case` and not as a silently untested code path.
    `KIND_RESERVED` is the one fault only `encode()` can produce -- it is a host that mis-frames
    its own header -- so it takes the other branch.
    """
    if fault is WireFault.KIND_RESERVED:
        with pytest.raises(DriverHostError) as caught:
            encode(FrameKind.LOG, {KIND_KEY: "LOG", "level": "info"})
        assert fault_of(caught.value) == fault.value
        return
    data, expect = _fault_case(fault)
    with pytest.raises(DriverHostError) as caught:
        read_frame(Stream(data).recv, expect=expect)
    assert fault_of(caught.value) == fault.value


def test_the_fault_taxonomy_is_fourteen_members_and_they_are_pinned() -> None:
    """The taxonomy is ours, so it is pinned as a literal: nothing in the plan enumerates it."""
    assert [fault.value for fault in WireFault] == [
        "short_prefix",
        "header_absent",
        "header_too_large",
        "body_too_large",
        "header_truncated",
        "body_truncated",
        "header_not_utf8",
        "header_not_json",
        "header_not_object",
        "header_too_deep",
        "kind_absent",
        "kind_unknown",
        "kind_reserved",
        "direction_unexpected",
    ]


# --------------------------------------------------------------------------------------------
# 6. Round trips, the byte layout, and the direction filter
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", list(FrameKind))
def test_every_kind_round_trips_through_encode_and_read_frame(kind: FrameKind) -> None:
    """All eleven, with a body, so no kind is round-tripped only by the lucky ones."""
    header = {"n": int(kind), "s": kind.name, "nested": {"a": [1, 2, None]}}
    stream = Stream(encode(kind, header, b"\x00\xffbody"))
    frame = read_frame(stream.recv)
    assert frame == Frame(kind=kind, header=frame.header, body=b"\x00\xffbody")
    assert dict(frame.header) == header
    assert KIND_KEY not in frame.header
    assert stream.requested == [PREFIX_BYTES, len(encode(kind, header)) - PREFIX_BYTES, 6]


def test_the_prefix_is_two_little_endian_u32_lengths_in_that_order() -> None:
    """The byte layout of 04-driver-system.md:1674, asserted against literal bytes.

    A big-endian pair would pass every round-trip test in this file and fail against every other
    implementation of the protocol, which is why the literal is here.
    """
    framed = encode(FrameKind.PROBE, {})
    assert framed == b"\x10\x00\x00\x00\x00\x00\x00\x00" + b'{"kind":"PROBE"}'
    assert framed[:4] == (16).to_bytes(4, "little")
    assert framed[4:8] == (0).to_bytes(4, "little")


def test_a_bodyless_frame_costs_no_body_read() -> None:
    """`recv(0)` is never called: a zero-length read is a question with one answer."""
    stream = Stream(encode(FrameKind.CANCEL, {"invoke_id": "i", "generation": 3}))
    assert read_frame(stream.recv).kind is FrameKind.CANCEL
    assert 0 not in stream.requested
    assert len(stream.requested) == 2


def test_the_body_crosses_as_raw_bytes_and_is_never_decoded() -> None:
    """04-driver-system.md:1679: "The body is raw bytes, so binary needs no base64".

    The body here is not valid UTF-8 and is not valid JSON, which is the whole point: a codec on
    the body would be a codec the plan struck (charter section 5 C4).
    """
    body = bytes(range(256)) * 3
    stream = Stream(encode(FrameKind.RESULT, {"invoke_id": "i", "unit_index": 0}, body))
    assert read_frame(stream.recv).body == body


def test_two_hosts_framing_the_same_header_produce_the_same_bytes() -> None:
    """The header is canonical JSON -- sorted keys, no whitespace -- so framing is deterministic
    and a frame digest means something. `omniweave_core.canonical` is the one encoder."""
    assert encode(FrameKind.HELLO, {"b": 1, "a": 2}) == encode(FrameKind.HELLO, {"a": 2, "b": 1})


def test_a_reader_that_expects_one_direction_refuses_the_other_half_by_name() -> None:
    """A driver that sends `INVOKE` is confused or hostile; a host that accepts one has handed a
    third party its own protocol. Both directions are tested, since a filter tested one way round
    could be inverted and nobody would know."""
    host_frame = encode(FrameKind.INVOKE, {"invoke_id": "i"})
    drv_frame = encode(FrameKind.RESULT, {"invoke_id": "i"})
    assert read_frame(Stream(host_frame).recv, expect=Direction.HOST_TO_DRIVER).kind is (
        FrameKind.INVOKE
    )
    assert read_frame(Stream(drv_frame).recv, expect=Direction.DRIVER_TO_HOST).kind is (
        FrameKind.RESULT
    )
    for data, expect in (
        (host_frame, Direction.DRIVER_TO_HOST),
        (drv_frame, Direction.HOST_TO_DRIVER),
    ):
        with pytest.raises(DriverHostError) as caught:
            read_frame(Stream(data).recv, expect=expect)
        assert fault_of(caught.value) == WireFault.DIRECTION_UNEXPECTED.value
        # "by name" is this test's own claim, so the message is asserted to NAME the kind that
        # arrived and the direction the reader accepts. The refusal happens after the envelope is
        # parsed precisely so it can say which kind it was, and a message that dropped the name
        # would satisfy every other assertion here.
        assert decode(data[PREFIX_BYTES:]).kind.name in str(caught.value)
        assert expect.value in str(caught.value)


def test_a_reader_with_no_expectation_reads_both_halves() -> None:
    """The default, for a conformance kit or a recorded exchange reading both sides."""
    for kind in (FrameKind.INVOKE, FrameKind.RESULT):
        assert read_frame(Stream(encode(kind, {"invoke_id": "i"})).recv).kind is kind


# --------------------------------------------------------------------------------------------
# 7. The derandomised sweep that stands in for the atheris target
# --------------------------------------------------------------------------------------------

SWEEP_KEY: Final = b"omniweave-driver/1 wire sweep"
"""The `blake2b` key. A literal, so the corpus is the same corpus on every machine and in every
run -- 11-repo-layout.md:2185, "Sampling is blake2b. Determinism is a gate, not a habit.", which
is also why `random` is a banned import framework-wide."""

SWEEP_CASES: Final = 4096
"""How many mutated frames the sweep runs. 16-roadmap.md:482 asks for a fuzzed framing layer and
prices an atheris target; this is the stdlib stand-in, sized to run inside a unit-test budget."""

SWEEP_DIGEST: Final = "b56dc142d88fbed86cf23824916301700ee1b5cc0759af73fa5bc6cced889b7e"
"""`sha256` over the whole generated corpus, pinned as a LITERAL.

This is a determinism pin and is labelled one: it says the generator draws the same 4,096 inputs
from the same key on every platform, which is the property that makes a sweep a gate rather than
a habit. It is deliberately not the only assertion about the sweep -- a digest is a checksum and
never a structural test -- so the structural claims are the two tests below it.
"""


def sweep_seeds() -> tuple[bytes, ...]:
    """The starting corpus: one valid frame per kind, plus the shapes the caps exist for."""
    valid = tuple(
        encode(kind, {"n": int(kind), "nested": {"a": [1, {"b": "c"}]}}, b"\x00\xffbody")
        for kind in FrameKind
    )
    hostile = (
        b"\xff\xff\xff\xff\xff\xff\xff\xff",
        prefix(0, 0),
        prefix(MAX_HEADER_BYTES, MAX_BODY_BYTES),
        prefix(2, 0) + b"[]",
        prefix(3, 0) + b"{{{",
        nested(MAX_HEADER_DEPTH + 1),
        prefix(len(nested(64)), 0) + nested(64),
        b"",
        b"\x00" * 7,
    )
    return valid + hostile


def sweep_corpus() -> tuple[bytes, ...]:
    """`SWEEP_CASES` mutations of the seeds, drawn by keyed `blake2b` and never by an RNG.

    Six mutation shapes, chosen because each attacks a different part of the grammar: a bit flip
    inside a length field or a name, a byte overwrite, a truncation (which is how a real socket
    fails), an extension, a wholesale replacement of the eight-byte prefix with drawn bytes --
    the shape that produces the huge declared lengths -- and a splice of two seeds, which is what
    a stream desynchronised by one frame looks like.
    """
    seeds = sweep_seeds()
    out: list[bytes] = []
    for index in range(SWEEP_CASES):
        draw = hashlib.blake2b(str(index).encode(), key=SWEEP_KEY, digest_size=32).digest()
        seed = bytearray(seeds[draw[0] % len(seeds)])
        other = seeds[draw[1] % len(seeds)]
        op = draw[2] % 6
        at = draw[3] % max(len(seed), 1)
        if op == 0 and seed:
            seed[at] ^= 1 << (draw[4] % 8)
        elif op == 1 and seed:
            seed[at] = draw[5]
        elif op == 2:
            seed = seed[:at]
        elif op == 3:
            seed.extend(bytes([draw[6]]) * (1 + draw[7] % 16))
        elif op == 4:
            seed[:PREFIX_BYTES] = draw[8:16]
        else:
            seed = bytearray(bytes(seed[:at]) + other[at:])
        out.append(bytes(seed))
    return tuple(out)


def test_the_sweep_corpus_is_the_same_corpus_on_every_run_and_every_platform() -> None:
    """The determinism pin. A changed generator changes this digest and says so."""
    corpus = sweep_corpus()
    assert len(corpus) == SWEEP_CASES
    digest = hashlib.sha256(b"\x00".join(corpus)).hexdigest()
    assert digest == SWEEP_DIGEST


def test_every_mutated_frame_either_parses_or_raises_a_named_wire_fault() -> None:
    """The property the roadmap's "fuzzed" asks for, over 4,096 derandomised inputs.

    Three claims in one loop, and the third is the one a `pytest.raises` cannot make: every
    outcome is either a well-formed `Frame` or a `DriverHostError` whose message leads with a
    member of `WireFault` -- never a `ValueError` from `json`, never a `RecursionError`, never a
    `UnicodeDecodeError`, never an `IndexError` off the end of a short buffer; no single `recv`
    is ever asked for more than the largest cap, so no input can provoke an unbounded
    allocation; and a parsed frame re-frames to bytes that parse back to an equal frame, so the
    grammar is not merely permissive but round-trip closed.

    "Never a hang" is carried by the loop terminating: a framing layer with an unbounded read
    loop would not finish, and there is no such loop -- `read_frame` makes at most three reads.
    """
    parsed = 0
    refused: set[str] = set()
    served = 0
    for data in sweep_corpus():
        stream = Stream(data)
        try:
            frame = read_frame(stream.recv)
        except DriverHostError as exc:
            fault = fault_of(exc)
            assert fault in {member.value for member in WireFault}, str(exc)
            refused.add(fault)
        else:
            parsed += 1
            again = Stream(encode(frame.kind, frame.header, frame.body))
            assert read_frame(again.recv) == frame
        assert max(stream.requested, default=0) <= MAX_HEADER_BYTES
        served += stream.served
    assert parsed > 0
    assert served < 4 * 1024 * 1024
    assert refused == {
        "body_too_large",
        "body_truncated",
        "header_absent",
        "header_not_json",
        "header_not_object",
        "header_not_utf8",
        "header_too_deep",
        "header_too_large",
        "header_truncated",
        "kind_absent",
        "kind_unknown",
        "short_prefix",
    }
    assert {member.value for member in WireFault} - refused == {
        WireFault.KIND_RESERVED.value,
        WireFault.DIRECTION_UNEXPECTED.value,
    }


def test_the_sweep_reaches_both_outcomes_in_pinned_numbers() -> None:
    """The counts, pinned, so a generator change that stopped producing valid frames is loud.

    A sweep in which everything is refused proves only that the reader refuses; a sweep in which
    everything parses proves only that it parses. The two literals below are this corpus's actual
    split, and they are what makes the previous test's `parsed > 0` a fact about a real mixture.
    """
    outcomes = []
    for data in sweep_corpus():
        try:
            read_frame(Stream(data).recv)
        except DriverHostError:
            outcomes.append(False)
        else:
            outcomes.append(True)
    assert (outcomes.count(True), outcomes.count(False)) == (666, 3430)


# --------------------------------------------------------------------------------------------
# 8. Purity: what the framing layer may import
# --------------------------------------------------------------------------------------------


def test_the_framing_layer_imports_nothing_that_could_do_io() -> None:
    """A pinned import set over the module's own `ast`.

    G23 forbids `asyncio` and `selectors` in core, INV-2 forbids every third party, and framing
    owns no transport at all -- so `socket`, `subprocess` and `os` have no business here either.
    The set is pinned as a literal rather than filtered by a rule, because a filter passes the
    moment the rule is wrong.
    """
    source = Path(wire.__file__).read_text(encoding="utf-8")
    roots: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            roots.add(node.module.split(".")[0])
    assert roots == {
        "__future__",
        "collections",
        "dataclasses",
        "enum",
        "json",
        "omniweave_core",
        "types",
        "typing",
    }


def test_the_framing_layer_is_the_size_the_plan_prices_it_at() -> None:
    """16-roadmap.md:482 and 02-architecture.md:238 both say "framing only, ~80 lines".

    Counted as STATEMENTS and not as lines, because this file's house style puts several hundred
    lines of cited argument in its docstrings and a line count would measure the prose. The
    ceiling is generous and the point of the assertion is directional: if framing acquires a
    transport, a worker or a retry, it will not fit.
    """
    tree = ast.parse(Path(wire.__file__).read_text(encoding="utf-8"))
    statements = sum(1 for node in ast.walk(tree) if isinstance(node, ast.stmt))
    assert statements < 200
