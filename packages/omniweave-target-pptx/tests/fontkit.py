"""A TrueType font built from its tables, so measurement tests hold on every platform. D792.

No font is committed to the repository and fontTools is not a dependency. `tiny_font()` writes
the nine tables uharfbuzz reads to shape and to match a face: `head`, `hhea`, `maxp`, `hmtx`,
`cmap` (format 4), `loca`, `glyf`, `name` and `OS/2`, with `post`. Every glyph is empty and has
the advance it is given, so a line's width is arithmetic a test can state.
"""

from __future__ import annotations

import math
import string
import struct
from collections.abc import Mapping
from pathlib import Path

CHARACTERS = " " + string.ascii_letters + string.digits + ".,%-:!?'"


def tiny_font(
    family: str,
    *,
    advance: int = 500,
    widths: Mapping[str, int] | None = None,
    upem: int = 1000,
    ascender: int = 800,
    descender: int = -200,
    line_gap: int = 0,
    weight: int = 400,
    italic: bool = False,
) -> bytes:
    """A font of `family` whose glyph for each of `CHARACTERS` is `advance` units wide."""
    chars = sorted(set(CHARACTERS))
    advances = [advance] + [(widths or {}).get(c, advance) for c in chars]
    count = len(advances)
    tables = {
        b"head": struct.pack(
            ">IIIIHHqqhhhhHHhhh",
            0x00010000, 0x00010000, 0, 0x5F0F3CF5, 0, upem, 0, 0,
            0, descender, max(advances), ascender, 2 if italic else 0, 8, 2, 0, 0,
        ),
        b"hhea": struct.pack(
            ">I3hH3h3h4hhH",
            0x00010000, ascender, descender, line_gap, max(advances),
            0, 0, max(advances), 1, 0, 0, 0, 0, 0, 0, 0, count,
        ),
        b"maxp": struct.pack(">IH13H", 0x00010000, count, *([0] * 13)),
        b"hmtx": b"".join(struct.pack(">Hh", a, 0) for a in advances),
        b"cmap": _cmap({ord(c): gid for gid, c in enumerate(chars, start=1)}),
        b"loca": struct.pack(f">{count + 1}H", *([0] * (count + 1))),
        b"glyf": b"",
        b"name": _name({1: family, 2: "Italic" if italic else "Regular", 4: family}),
        b"OS/2": _os2(weight=weight, italic=italic, ascender=ascender, descender=descender,
                      line_gap=line_gap),
        b"post": struct.pack(">IiHHIIIII", 0x00030000, 0, 0, 0, 0, 0, 0, 0, 0),
    }  # fmt: skip
    return _sfnt(tables)


def write_font(directory: Path, name: str, data: bytes) -> Path:
    """`data` at `directory/name`, its parents made."""
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _cmap(mapping: Mapping[int, int]) -> bytes:
    codes = sorted(mapping)
    ends = [*codes, 0xFFFF]
    deltas = [(mapping[c] - c) % 0x10000 for c in codes] + [1]
    segments = len(ends)
    selector = int(math.log2(segments))
    search = 2 * 2**selector
    body = (
        struct.pack(f">{segments}H", *ends)
        + b"\x00\x00"
        + struct.pack(f">{segments}H", *ends)
        + struct.pack(f">{segments}H", *deltas)
        + struct.pack(f">{segments}H", *([0] * segments))
    )
    length = 14 + len(body)
    subtable = (
        struct.pack(">7H", 4, length, 0, 2 * segments, search, selector, 2 * segments - search)
        + body
    )
    return struct.pack(">HHHHI", 0, 1, 3, 1, 12) + subtable


def _name(names: Mapping[int, str]) -> bytes:
    records = b""
    strings = b""
    for name_id, text in sorted(names.items()):
        data = text.encode("utf-16-be")
        records += struct.pack(">6H", 3, 1, 0x409, name_id, len(data), len(strings))
        strings += data
    return struct.pack(">3H", 0, len(names), 6 + 12 * len(names)) + records + strings


def _os2(*, weight: int, italic: bool, ascender: int, descender: int, line_gap: int) -> bytes:
    table = bytearray(96)
    struct.pack_into(">HhHH", table, 0, 4, 500, weight, 5)
    struct.pack_into(">H", table, 62, 0x01 if italic else 0x40)
    struct.pack_into(">hhhHH", table, 68, ascender, descender, line_gap, ascender, -descender)
    return bytes(table)


def _sfnt(tables: Mapping[bytes, bytes]) -> bytes:
    tags = sorted(tables)
    selector = int(math.log2(len(tags)))
    search = 16 * 2**selector
    header = struct.pack(">IHHHH", 0x00010000, len(tags), search, selector, 16 * len(tags) - search)
    offset = 12 + 16 * len(tags)
    directory = b""
    body = b""
    for tag in tags:
        data = tables[tag]
        padded = data + b"\x00" * (-len(data) % 4)
        checksum = sum(struct.unpack(f">{len(padded) // 4}I", padded)) & 0xFFFFFFFF
        directory += struct.pack(">4sIII", tag, checksum, offset + len(body), len(data))
        body += padded
    return header + directory + body
