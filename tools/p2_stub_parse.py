"""The P2 stub `parse/1` driver: a real PDF reader for `gen_5000p_pdf`'s one frozen grammar.

16-roadmap.md:442 is the whole warrant -- P2's demo *"ingest `fixtures/gen/gen_5000p_pdf.py`'s
output through a stub `parse/1` driver"*. This is that driver, and each half of the phrase pulls
in a different direction.

**Why it lives in `tools/` and not in a package.** The real driver system is P3:
`drivers/resolve.py`'s eight-gate INV-5 order and its `Requirement` capability floors are W3.1,
`host/wire.py`'s framing and the `DriverGuard` are W3.2, and the two shipped parse drivers --
`parse.office.anydoc` and `parse.pdf.pdfium` -- are W3.4 and W3.5 (16-roadmap.md:481-485). None of
that exists at P2, so a driver written into `packages/` would have to invent the Port protocol it
plugs into, the driver card it is resolved by, and the `owdoc-fragment/1` wire it speaks across.
D25's standing pattern is the alternative and this tree already works it twice: build the function
now, put the runner under `tools/`, and let P7 or P10 wrap it in a verb later.
`tools/gate_crash.py`'s docstring is the worked example.

**What this deliberately does NOT do**, so nobody mistakes it for W3.5 arriving early:

* it speaks no wire. A real `parse/1` driver emits `owdoc-fragment/1` addressing blocks by a
  per-invocation `tmp` id, and the HOST decodes that and drives `DocSink` -- which is what makes
  INV-6 and INV-7 structural rather than reviewed (03:548-551, restated by `store/doc.py`).
  `ingest()` here calls `DocSink` directly, in-process, so it is host-side code wearing a
  driver's name;
* it ships no `driver.toml` card, no `Requirement`, no `RejectCode` and no capability-floor
  resolution. That is W3.1 entire;
* it reads ONE grammar. It is not a PDF library. It assumes the classic cross-reference TABLE,
  uncompressed objects, unfiltered content streams and the exact `BT`/`Tf`/`Tm`/`Tj`/`ET`
  operator set the P2 fixture generator freezes. Anything outside that is refused loudly instead
  of guessed at, because a stub that guesses reports a bytes-per-block figure about a document it
  did not understand;
* it runs no normaliser. 05-ingest-and-routing.md:263-264 gives the `pdf` format the
  `pdf_trailer_v1` normaliser, and there is no ingest stage at P2 -- so `doc.source_sha256` is the
  digest of the raw file and `doc.normalizer` is NULL, which 05:261 defines as *"the raw bytes
  were hashed"*;
* it does no OCR, no layout analysis, no section building, no furniture detection, no math, no
  notes and no assets. `STUB_CAPABILITIES` says exactly that, in the one vocabulary the framework
  filters drivers on.

**It genuinely parses.** `parse_pdf` is handed `bytes` and nothing else: no sidecar, no hint from
the generator, no import of it. It finds `startxref`, walks the cross-reference table, resolves
the catalogue, walks the page tree, locates each content stream *in the raw file* and scans the
operators. That last part is why `TextRun.byte_start` is an offset into the FILE rather than into
a decoded stream: it is what lets every text Block carry a real `OriginBytes`, and therefore what
lets `ow store verify` re-derive content from stored bytes (16-roadmap.md:435, INV-10's `bytes`
branch at 03:1440).

**On the three text sizes.** `_HEADING_SIZE_PT`, `_BODY_SIZE_PT` and `_CELL_SIZE_PT` are
transcribed from the frozen fixture grammar, and a run at any other size is a refusal rather than
a shrug. Classifying an unrecognised run as prose would move the prose/cell mix that
07-store-and-retrieval.md:1012 makes bytes-per-block depend on, silently.

Specified by 16-roadmap.md:434-445 (the P2 demo and its exit criteria), 03-document-model.md
section 2.10 (`DocSink`'s eleven methods), 03 section 2.9 (the fifteen capability fields), 03
section 6.2 (the `addr` grammar this walks), 03 section 7.2 (`OriginBytes` and the `os_*`
columns), 03 section 8.5 (the `Quote` ladder) and 07-store-and-retrieval.md:1005-1030 (the
bytes-per-block decomposition this fixture feeds).
"""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final

from omniweave_core.archive.manifest import MODEL_VERSION
from omniweave_core.model import Capabilities, Kind, Layer, Method, PageKind, Quote, Trust
from omniweave_core.model.block import BlockDraft, BlockId, CellPos
from omniweave_core.model.grid import build_grid
from omniweave_core.model.records import DocRecord, PageRecord
from omniweave_core.model.spans import OriginBytes, OriginNone, OriginSpan
from omniweave_core.store.doc import DocSink

__all__ = [
    "DRIVER_ID",
    "DRIVER_SCHEMA_V",
    "OPERATOR",
    "OP_VERSION",
    "PORT",
    "STUB_CAPABILITIES",
    "ParsedPage",
    "StubParseError",
    "TextRun",
    "ingest",
    "parse_pdf",
]


# ---------------------------------------------------------------------------
# 1. The card, such as it is: four identity constants and the fifteen fields.
# ---------------------------------------------------------------------------

DRIVER_ID: Final = "parse.pdf.stub"
"""`block.origin_driver` on every row this writes.

Deliberately not `parse.pdf.pdfium`, which is W3.5's name (16-roadmap.md:485). Two drivers that
disagree about what they can do must never share an id, because `achieved` is stored per document
and read back by serve (charter section 5 X9).
"""

PORT: Final = "parse/1"
"""16-roadmap.md:442's own words. The Port PROTOCOL is W3.2 and does not exist; this is its name."""

OPERATOR: Final = "parse.pdf"
"""`block.origin_operator`, and it must start with `parse.`.

`store/doc.py`'s `_clamp_quote` caps a block at `SYNTHETIC` when the operator is not a parse
(03:1683-1686): a `derive.*` block quotes nothing by inheritance. So the prefix is not cosmetic --
it is the second input to the `Quote` ceiling every text block here depends on.
"""

DRIVER_SCHEMA_V: Final = 1
"""D3's third ownership column (03:302-304), stamped by the sink on every block and every rel."""

OP_VERSION: Final = 1
"""The `producer` row's `op_version`. The RUNNER resolves that row; `ingest` never mints one --
`Producer` is L5's `OperatorIdentity` (03:396) and minting it is not one of the eleven methods."""

STUB_CAPABILITIES: Final = Capabilities(
    # No `quad` ever reaches `add_block`, and 03:509 derives `spatial` from `block.quad` alone.
    # The MediaBox does reach the store, as `page.w_mpt`/`h_mpt` -- but that is the `page` row and
    # not a Block, so declaring `page_bbox` here would buy a forfeit at `end_doc` and nothing else.
    spatial="none",
    # NOT `exact`, and the reason is the whole point of the Quote ladder. 03:512 makes `exact`
    # mean "every non-`pixels` block's branch re-verifies", and a coalesced paragraph's span
    # necessarily covers the operator bytes BETWEEN its runs, so decoding that range does not
    # reproduce `block.text`. Every span written here is real; not every one is byte-exact.
    origin_span="normalized",
    text_span=False,  # no `ts_a`/`ts_b`: there is no source character stream to index into
    marks=False,  # one font and one size per run, so there is no bold to lose
    # Literally what it is: the order of the content stream's own text-showing operators. `source`
    # is the rung above and would claim the container declares a reading order. PDF does not.
    # 03:506-509 orders `raster < learned < model_emitted < char_stream < source`.
    reading_order="char_stream",
    sections="none",  # a `heading` Block is emitted; no `section` Block, and no outline
    tables="cells",  # real `cell` rows, never a span > 1, so not `cells_with_spans`
    math=frozenset(),
    assets="none",
    asset_origin=False,
    notes="none",
    confidence="none",  # no `block.score` and no page score: nothing here is measured
    furniture="destroyed",  # every run becomes `layer = body`; no header or footer is detected
    round_trip="none",
    # Said out loud rather than left to be discovered. 03:1575 makes `forfeits` the field where a
    # driver states an absence in so many words -- "if a capability is absent, say so" -- and it
    # is the ONE set on a card compared inverted, `subset` rather than `superset`
    # (`drivers/card.py`:1507-1511), so a member added here can only ever narrow what this driver
    # is offered. `spatial` and `round_trip` are exactly the two that `store/doc.py`'s
    # `_forfeited` derives from a committed generation with no `quad` and no round trip.
    forfeits=frozenset({"spatial", "round_trip"}),
)
"""The fifteen fields of 03 section 2.9, every one set deliberately.

A capability floor is a FILTER and never a ranking key (16-roadmap.md:481). An over-declared field
therefore admits this driver to work it cannot do, and an under-declared one excludes it from work
it can -- so the two errors are not symmetric in kind, only in cost.

These fifteen are chosen so that `doc.achieved` comes out EQUAL to them, `forfeits` included.
`achieved` is computed by the host from the committed rows and never reported by the driver
(INV-7 at the capability grain, 03:534-536), so that equality is the one check that can tell a
declaration from a wish -- and `test_p2_stub_parse.py` pins it.
"""


# ---------------------------------------------------------------------------
# 2. The grammar this stub can read. Transcribed from the frozen fixture contract.
# ---------------------------------------------------------------------------

_HEADING_SIZE_PT: Final = 18.0
_BODY_SIZE_PT: Final = 10.0
_CELL_SIZE_PT: Final = 8.0

_LEADING_PT: Final = 12.0
"""The exact `y` decrement between two runs of ONE paragraph, and the coalescing predicate.

Consecutive runs at the same size whose `y` falls by exactly this much are one paragraph; any
other gap ends it. The generator makes the inter-paragraph gap and the table's row pitch strictly
greater than this precisely so a reader with no layout model can find the boundary from geometry
alone.
"""

_EPS_PT: Final = 1e-6
"""Slack on every point comparison, for sizes and for the leading alike.

Coordinates are written as short decimals and read back through `float()`, so they compare
exactly in practice. The epsilon is here so that a generator emitting `10` or `10.00` rather than
`10.0` cannot change a classification, and so a `y` step accumulated by repeated subtraction
still matches the leading.
"""

_COORD_DIGITS: Final = 3
"""Millipoint resolution when bucketing cell coordinates into rows and columns. The store keeps
the page box in millipoints (03:2225), so this is the same grain, and it is fine enough that two
genuinely distinct grid lines can never collide."""

_PART_PATH: Final = "file"
"""The single `part.path` this driver registers.

A PDF is one byte stream and not a container, so there is exactly one part and every
`OriginBytes` names it. `add_part` is the sole inserter of an L2 `part` row (03:591) and it runs
before any block whose origin cites it.
"""

_CODEC: Final = "utf-8/strict"
"""`os_codec` -- the decode policy INV-10's `bytes` branch READS rather than assumes (03:1440).

The fixture's literals are ASCII, so utf-8 is exact for them. On the three container kinds, whose
`text` is NULL and whose `quote` is `SYNTHETIC`, the branch is never evaluated and this records
the policy that would apply if it were; a NULL codec would make the branch *unevaluable*, which
03:1440 distinguishes from merely undocumented.
"""

_MPT_PER_POINT: Final = 1_000
_HEADING_LEVEL: Final = 1
_HEADER_SCAN: Final = 16
_MAX_REF_HOPS: Final = 8
_MAX_TREE_DEPTH: Final = 32
_BOX_LEN: Final = 4
_TM_OPERANDS: Final = 6
_TF_OPERANDS: Final = 2


class StubParseError(ValueError):
    """This file is not the grammar `parse_pdf` reads.

    A local exception and NOT one of `omniweave_core.errors`' ten, on purpose. Every `OwError`
    carries a symbol from `codes.toml` plus the exact command that clears it; `codes.toml` is
    append-only against the last tag (G13, stated in its own header); and a stub inventing a
    register row is fabrication, not diligence. A refusal raised by a P2 scaffold that P3 deletes
    does not deserve a durable public numeric.
    """


# ---------------------------------------------------------------------------
# 3. What comes out. The two frozen value types.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TextRun:
    """One `(...) Tj` in one content stream, with its address in the FILE.

    `byte_start` and `byte_len` are the load-bearing pair. They address the literal's CONTENT --
    the bytes between the parentheses, exactly as written, escapes included -- at its offset in
    the PDF file and not in a decoded stream. That is what makes `data[byte_start:byte_start +
    byte_len]` a slice a third party can take holding nothing but the file, and therefore what
    makes a Block's `OriginBytes` re-derivable by `ow store verify` (16-roadmap.md:435).

    `text` is the UNESCAPED literal, so `text.encode("utf-8")` differs from the addressed bytes
    exactly when the literal needed unescaping. That is the condition on `Quote.VERBATIM`, and
    `_verbatim()` evaluates it against the real bytes rather than inferring it from a length.

    `page` is 1-BASED here because the driver contract for this wave freezes it that way. The
    store's `page` column is 0-based (03:277, 03:2271), so `ingest()` subtracts one exactly once,
    at the `PageRecord`. The disagreement is reported rather than smoothed over.
    """

    page: int
    x_pt: float
    y_pt: float
    size_pt: float
    text: str
    byte_start: int
    byte_len: int


@dataclass(frozen=True, slots=True)
class ParsedPage:
    """One `/Type /Page`: its box in points, and its runs in content-stream order."""

    page: int
    w_pt: float
    h_pt: float
    runs: tuple[TextRun, ...]


# ---------------------------------------------------------------------------
# 4. A minimal COS object reader -- PDF 1.7 section 7.3, restricted to what P2 emits.
# ---------------------------------------------------------------------------

_WHITESPACE: Final = b"\x00\t\n\x0c\r "
_DELIMITERS: Final = b"()<>[]{}/%"
_DIGIT_LEADS: Final = b"+-.0123456789"

_KEYWORDS: Final[Mapping[bytes, object]] = MappingProxyType(
    {b"true": True, b"false": False, b"null": None}
)

_ESCAPES: Final[Mapping[int, int]] = MappingProxyType(
    {ord("("): ord("("), ord(")"): ord(")"), ord("\\"): ord("\\")}
)
"""The only three escapes the fixture grammar produces, and therefore the only three accepted.

An octal escape or a `\\n` would be a file this stub does not claim to read. Refusing is better
than decoding it one way while the offset arithmetic assumes another, because the offsets are the
part a later `ow store verify` trusts.
"""

_INHERITABLE: Final = ("MediaBox", "CropBox", "Resources", "Rotate")
"""The four page-tree attributes a `/Pages` node may hand its kids (PDF 1.7 table 30)."""


@dataclass(frozen=True, slots=True)
class _Name:
    """A PDF name, `/Type`, carried as its own type so a name never compares equal to a string."""

    value: str


@dataclass(frozen=True, slots=True)
class _Ref:
    """`12 0 R`. Resolved against the cross-reference table on demand, never followed eagerly."""

    num: int
    gen: int


@dataclass(frozen=True, slots=True)
class _Literal:
    """A `(...)` literal inside a content stream, carrying the file offsets a `TextRun` needs."""

    byte_start: int
    byte_len: int
    text: str


@dataclass(frozen=True, slots=True)
class _CellDraft:
    """A stand-in for `CellDraft` (03:337-338), which `model/block.py` has not declared.

    `build_grid` reads `.id` and `.pos` structurally for exactly this reason -- see
    `model/grid.py`'s `_cell_position`, which records the same gap and the same workaround. When
    `block.py` lands the real type this class is deleted and the import replaces it.
    """

    id: BlockId
    pos: CellPos


def _skip_ws(data: bytes, i: int) -> int:
    """Past whitespace and `%` comments. Both are legal between any two tokens."""
    size = len(data)
    while i < size:
        if data[i] in _WHITESPACE:
            i += 1
        elif data[i] == ord("%"):
            while i < size and data[i] not in b"\r\n":
                i += 1
        else:
            return i
    return i


def _read_token(data: bytes, i: int) -> tuple[bytes, int]:
    """One run of regular characters: not whitespace, not a delimiter."""
    start = _skip_ws(data, i)
    j = start
    size = len(data)
    while j < size and data[j] not in _WHITESPACE and data[j] not in _DELIMITERS:
        j += 1
    if j == start:
        found = data[start : start + 8]
        raise StubParseError(f"expected a token at byte {start}, found {found!r}")
    return data[start:j], j


def _as_number(token: bytes) -> int | float:
    """`12`, `-3`, `595.276`. A token that is not a number is a grammar this stub cannot read."""
    text = token.decode("ascii", "replace")
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError as error:
        message = f"{text!r} is neither a number nor a keyword this stub reads"
        raise StubParseError(message) from error


def _read_uint(data: bytes, i: int) -> tuple[int, int]:
    """One non-negative integer token: an xref count, a first object number, an offset."""
    token, j = _read_token(data, i)
    value = _as_number(token)
    if not isinstance(value, int) or value < 0:
        raise StubParseError(f"expected a non-negative integer at byte {i}, found {token!r}")
    return value, j


def _read_name(data: bytes, i: int) -> tuple[_Name, int]:
    token, j = _read_token(data, i + 1)
    return _Name(token.decode("ascii", "replace")), j


def _read_literal(data: bytes, i: int) -> tuple[_Literal, int]:
    """A `(...)` literal. Returns the CONTENT offsets and the unescaped text.

    Parenthesis depth is tracked even though the fixture escapes every parenthesis it emits,
    because a reader that assumed the first `)` closed the string would silently truncate a run
    and then publish a byte range that does not contain what it says it contains -- which is
    exactly the failure a real `OriginBytes` exists to make impossible.
    """
    start = i + 1
    out = bytearray()
    j = start
    depth = 0
    size = len(data)
    while j < size:
        byte = data[j]
        if byte == ord("\\"):
            if j + 1 >= size:
                break
            escaped = _ESCAPES.get(data[j + 1])
            if escaped is None:
                seen = chr(data[j + 1])
                message = (
                    f"the literal at byte {start} carries the escape backslash-{seen}; this stub "
                    f"reads only backslash-( backslash-) and backslash-backslash"
                )
                raise StubParseError(message)
            out.append(escaped)
            j += 2
            continue
        if byte == ord("("):
            depth += 1
        elif byte == ord(")"):
            if depth == 0:
                return _Literal(start, j - start, out.decode("utf-8")), j + 1
            depth -= 1
        out.append(byte)
        j += 1
    raise StubParseError(f"unterminated literal string opened at byte {start}")


def _read_hex_string(data: bytes, i: int) -> tuple[bytes, int]:
    """`<48656C6C6F>`. Present for completeness of the object grammar; the fixture emits none."""
    end = data.find(b">", i)
    if end < 0:
        raise StubParseError(f"unterminated hex string opened at byte {i}")
    digits = bytes(c for c in data[i + 1 : end] if c not in _WHITESPACE)
    if len(digits) % 2:
        digits += b"0"
    return bytes.fromhex(digits.decode("ascii", "replace")), end + 1


def _read_array(data: bytes, i: int) -> tuple[tuple[object, ...], int]:
    """`[ 0 0 595.276 841.890 ]`. Returned as a tuple, so a parsed object is never mutated."""
    out: list[object] = []
    j = i + 1
    while True:
        j = _skip_ws(data, j)
        if j >= len(data):
            raise StubParseError(f"unterminated array opened at byte {i}")
        if data[j] == ord("]"):
            return tuple(out), j + 1
        value, j = _read_object(data, j)
        out.append(value)


def _read_dict(data: bytes, i: int) -> tuple[dict[str, object], int]:
    """`<< /Type /Page /Parent 2 0 R >>`, keyed by the name's text rather than by a `_Name`."""
    out: dict[str, object] = {}
    j = i + 2
    while True:
        j = _skip_ws(data, j)
        if j >= len(data):
            raise StubParseError(f"unterminated dictionary opened at byte {i}")
        if data[j : j + 2] == b">>":
            return out, j + 2
        key, j = _read_object(data, j)
        if not isinstance(key, _Name):
            raise StubParseError(f"a dictionary key at byte {j} is {key!r}, not a name")
        value, j = _read_object(data, j)
        out[key.value] = value


def _peek_token(data: bytes, i: int) -> tuple[bytes, int]:
    """`_read_token` that answers `(b"", i)` instead of raising when there is no token there.

    A lookahead may legitimately land on a delimiter -- `/Root 1 0 R /Info ...` puts a `/` exactly
    where the generation number of a reference would be -- so the miss is a normal outcome and
    must not be an exception. `_read_token` keeps raising because at its call sites a missing
    token IS the malformed file.
    """
    start = _skip_ws(data, i)
    j = start
    size = len(data)
    while j < size and data[j] not in _WHITESPACE and data[j] not in _DELIMITERS:
        j += 1
    return data[start:j], j


def _try_reference(data: bytes, value: int | float, after: int) -> tuple[_Ref, int] | None:
    """`<num> <gen> R`, or `None` when the three tokens are not there. Never consumes on a miss."""
    if not isinstance(value, int) or value < 0:
        return None
    generation, j = _peek_token(data, after)
    if not generation.isdigit():
        return None
    k = _skip_ws(data, j)
    if data[k : k + 1] != b"R":
        return None
    end = k + 1
    if end < len(data) and data[end] not in _WHITESPACE and data[end] not in _DELIMITERS:
        return None
    return _Ref(value, int(generation)), end


def _read_bare(data: bytes, i: int) -> tuple[object, int]:
    """A keyword, a number, or the three-token reference a number may turn out to open."""
    token, j = _read_token(data, i)
    if token in _KEYWORDS:
        return _KEYWORDS[token], j
    number = _as_number(token)
    reference = _try_reference(data, number, j)
    if reference is not None:
        return reference
    return number, j


_LEAD: Final[Mapping[int, Callable[[bytes, int], tuple[object, int]]]] = MappingProxyType(
    {
        ord("<"): _read_hex_string,
        ord("["): _read_array,
        ord("("): _read_literal,
        ord("/"): _read_name,
    }
)
"""Lead byte to reader, so `_read_object` is a dispatch and not a seven-armed `if`."""


def _read_object(data: bytes, i: int) -> tuple[object, int]:
    """One COS object at `i`, and the offset just past it."""
    j = _skip_ws(data, i)
    if j >= len(data):
        raise StubParseError(f"expected an object at byte {i}, reached the end of the file")
    if data[j : j + 2] == b"<<":
        return _read_dict(data, j)
    reader = _LEAD.get(data[j])
    if reader is not None:
        return reader(data, j)
    return _read_bare(data, j)


# ---------------------------------------------------------------------------
# 5. The file: cross-reference table, trailer, indirect objects, page tree.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Pdf:
    """The parsed skeleton: the bytes, `object number -> file offset`, and the trailer."""

    data: bytes
    offsets: Mapping[int, int]
    trailer: Mapping[str, object]

    def object_at(self, num: int) -> tuple[object, tuple[int, int] | None]:
        """One indirect object's value, plus `(stream start, stream length)` when it has one."""
        offset = self.offsets.get(num)
        if offset is None:
            raise StubParseError(f"object {num} is not in the cross-reference table")
        return _indirect(self, offset)

    def resolve(self, value: object) -> object:
        """Follow `_Ref`s until a value falls out. Bounded, so a cyclic file cannot hang a gate."""
        for _hop in range(_MAX_REF_HOPS):
            if not isinstance(value, _Ref):
                return value
            value = self.object_at(value.num)[0]
        raise StubParseError("an indirect reference chain did not terminate")


def _indirect(pdf: _Pdf, offset: int) -> tuple[object, tuple[int, int] | None]:
    """`<num> <gen> obj <value> [stream ... endstream] endobj` at a known file offset."""
    data = pdf.data
    _num, i = _read_token(data, offset)
    _gen, i = _read_token(data, i)
    i = _skip_ws(data, i)
    if data[i : i + 3] != b"obj":
        raise StubParseError(f"byte {offset} does not open an indirect object")
    value, i = _read_object(data, i + 3)
    i = _skip_ws(data, i)
    if data[i : i + 6] != b"stream":
        return value, None
    i += 6
    if data[i : i + 2] == b"\r\n":
        i += 2
    elif data[i : i + 1] in (b"\n", b"\r"):
        i += 1
    if not isinstance(value, dict):
        raise StubParseError(f"the stream at byte {offset} carries no dictionary")
    if "Filter" in value:
        raise StubParseError(
            f"the stream at byte {offset} declares /Filter; this stub reads uncompressed streams "
            f"only, because a decoded stream has no file offsets to hand an OriginBytes"
        )
    length = pdf.resolve(value.get("Length"))
    if not isinstance(length, int) or length < 0:
        raise StubParseError(f"the stream at byte {offset} has /Length {length!r}")
    return value, (i, length)


def _startxref(data: bytes) -> int:
    """The offset of the last cross-reference section, off the trailing `startxref`."""
    marker = data.rfind(b"startxref")
    if marker < 0:
        raise StubParseError("no `startxref`: this stub reads a classic cross-reference table")
    offset, _ = _read_uint(data, marker + len(b"startxref"))
    return offset


def _xref_entries(data: bytes, i: int, first: int, count: int, into: dict[int, int]) -> int:
    """One subsection's `count` entries, read as tokens rather than as fixed 20-byte records.

    The spec fixes the record at 20 bytes and a writer that pads differently is malformed, but
    tokenising costs nothing and removes a whole class of off-by-one from the one table every
    later offset in this module is derived from.
    """
    for k in range(count):
        at, i = _read_uint(data, i)
        _generation, i = _read_uint(data, i)
        i = _skip_ws(data, i)
        kind = data[i : i + 1]
        i += 1
        if kind == b"n":
            into[first + k] = at
        elif kind != b"f":
            raise StubParseError(f"xref entry {first + k} has type {kind!r}, not `n` or `f`")
    return i


def _xref_section(data: bytes, offset: int) -> tuple[dict[int, int], dict[str, object]]:
    """One `xref` ... `trailer` pair."""
    i = _skip_ws(data, offset)
    if data[i : i + 4] != b"xref":
        raise StubParseError(
            f"byte {i} is not the `xref` keyword; a cross-reference STREAM is outside this stub"
        )
    i += 4
    offsets: dict[int, int] = {}
    while True:
        i = _skip_ws(data, i)
        if data[i : i + 7] == b"trailer":
            trailer, _ = _read_object(data, i + 7)
            if not isinstance(trailer, dict):
                raise StubParseError(f"the trailer at byte {i} is {trailer!r}, not a dictionary")
            return offsets, trailer
        first, i = _read_uint(data, i)
        count, i = _read_uint(data, i)
        i = _xref_entries(data, i, first, count, offsets)


def _read_skeleton(data: bytes) -> _Pdf:
    """Every `xref` section down the `/Prev` chain, newest first. First writer of a key wins."""
    offsets: dict[int, int] = {}
    trailer: dict[str, object] = {}
    seen: set[int] = set()
    at: int | None = _startxref(data)
    while at is not None and at not in seen:
        seen.add(at)
        section, section_trailer = _xref_section(data, at)
        for num, offset in section.items():
            offsets.setdefault(num, offset)
        for key, value in section_trailer.items():
            trailer.setdefault(key, value)
        previous = section_trailer.get("Prev")
        at = previous if isinstance(previous, int) else None
    return _Pdf(data, MappingProxyType(offsets), MappingProxyType(trailer))


def _walk_pages(
    pdf: _Pdf, node: object, inherited: Mapping[str, object], depth: int
) -> Iterator[dict[str, object]]:
    """The page tree in document order, with the four inheritable attributes pushed down."""
    if depth > _MAX_TREE_DEPTH:
        raise StubParseError(f"the page tree is deeper than {_MAX_TREE_DEPTH} levels")
    if not isinstance(node, dict):
        raise StubParseError(f"a page-tree node is {node!r}, not a dictionary")
    merged = dict(inherited)
    merged.update({key: node[key] for key in _INHERITABLE if key in node})
    kind = node.get("Type")
    if isinstance(kind, _Name) and kind.value == "Page":
        yield merged | node
        return
    kids = pdf.resolve(node.get("Kids"))
    if not isinstance(kids, tuple):
        raise StubParseError(f"a page-tree node has /Kids {kids!r}, and is not a /Page either")
    for kid in kids:
        yield from _walk_pages(pdf, pdf.resolve(kid), merged, depth + 1)


def _page_nodes(pdf: _Pdf) -> tuple[dict[str, object], ...]:
    """Catalogue, `/Pages`, then the leaves. The trailer's `/Root` is the only entry point."""
    catalogue = pdf.resolve(pdf.trailer.get("Root"))
    if not isinstance(catalogue, dict):
        raise StubParseError(f"the trailer's /Root resolves to {catalogue!r}, not a dictionary")
    tree = pdf.resolve(catalogue.get("Pages"))
    return tuple(_walk_pages(pdf, tree, {}, 0))


def _media_box(pdf: _Pdf, node: Mapping[str, object]) -> tuple[float, float]:
    """`(width, height)` in points, from `[llx lly urx ury]`."""
    box = pdf.resolve(node.get("MediaBox"))
    if not isinstance(box, tuple) or len(box) != _BOX_LEN:
        raise StubParseError(f"a page has /MediaBox {box!r}, not four numbers")
    numbers = [float(value) for value in box if isinstance(value, (int, float))]
    if len(numbers) != _BOX_LEN:
        raise StubParseError(f"a page has /MediaBox {box!r}, not four numbers")
    return numbers[2] - numbers[0], numbers[3] - numbers[1]


def _content_ranges(pdf: _Pdf, node: Mapping[str, object]) -> tuple[tuple[int, int], ...]:
    """Every `(file offset, length)` of this page's content streams, in order."""
    contents = node.get("Contents")
    refs = contents if isinstance(contents, tuple) else (contents,)
    out: list[tuple[int, int]] = []
    for ref in refs:
        if not isinstance(ref, _Ref):
            raise StubParseError(f"a page's /Contents holds {ref!r}, not an indirect reference")
        _value, extent = pdf.object_at(ref.num)
        if extent is None:
            raise StubParseError(f"object {ref.num} is a page's /Contents but carries no stream")
        out.append(extent)
    return tuple(out)


# ---------------------------------------------------------------------------
# 6. The content stream: `BT` `/F1 s Tf` `1 0 0 1 x y Tm` `(...) Tj` `ET`.
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _TextState:
    """What a text-showing operator needs to know. `Tm` is ABSOLUTE, so there is no accumulator."""

    size_pt: float = 0.0
    x_pt: float = 0.0
    y_pt: float = 0.0


def _numeric(operands: Sequence[object], index: int) -> float:
    value = operands[index]
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise StubParseError(f"expected a number as operand {index}, found {value!r}")
    return float(value)


def _apply(
    state: _TextState, operator: bytes, operands: Sequence[object], page: int
) -> TextRun | None:
    """Fold one operator into the text state, and emit a run on `Tj`.

    Three operators are understood and every other one is ignored rather than refused: `BT`, `ET`
    and any future no-op carry no information this driver reads, while an unreadable *literal* or
    an unknown *escape* does and is refused at its own site.
    """
    if operator == b"Tf" and len(operands) >= _TF_OPERANDS:
        state.size_pt = _numeric(operands, -1)
    elif operator == b"Tm" and len(operands) >= _TM_OPERANDS:
        state.x_pt = _numeric(operands, -2)
        state.y_pt = _numeric(operands, -1)
    elif operator == b"Tj" and operands:
        literal = operands[-1]
        if not isinstance(literal, _Literal):
            raise StubParseError(f"Tj on page {page} takes a literal string, not {literal!r}")
        return TextRun(
            page=page,
            x_pt=state.x_pt,
            y_pt=state.y_pt,
            size_pt=state.size_pt,
            text=literal.text,
            byte_start=literal.byte_start,
            byte_len=literal.byte_len,
        )
    return None


def _stream_runs(data: bytes, start: int, length: int, page: int) -> Iterator[TextRun]:
    """Scan one content stream in place. Offsets stay absolute, which is the whole point."""
    end = start + length
    state = _TextState()
    operands: list[object] = []
    i = start
    while True:
        i = _skip_ws(data, i)
        if i >= end:
            return
        lead = data[i]
        if lead == ord("(") or lead == ord("/"):
            value, i = _LEAD[lead](data, i)
            operands.append(value)
            continue
        token, i = _read_token(data, i)
        if token[:1] in _DIGIT_LEADS:
            operands.append(_as_number(token))
            continue
        run = _apply(state, token, operands, page)
        operands.clear()
        if run is not None:
            yield run


def parse_pdf(data: bytes) -> tuple[ParsedPage, ...]:
    """Every page and every text run, from the bytes of the file and nothing else.

    16-roadmap.md:442's "stub" is the licence to assume one grammar; it is not a licence to be
    told the answer. Nothing here reads a sidecar, takes a hint, or imports the generator: the
    cross-reference table gives the objects, the catalogue gives the page tree, and each content
    stream is located in the raw bytes so that the literals found inside it carry offsets a third
    party can re-slice.
    """
    if not data.startswith(b"%PDF-"):
        raise StubParseError("the file does not begin with %PDF-")
    pdf = _read_skeleton(data)
    pages: list[ParsedPage] = []
    for index, node in enumerate(_page_nodes(pdf), start=1):
        width, height = _media_box(pdf, node)
        runs = tuple(
            run
            for start, length in _content_ranges(pdf, node)
            for run in _stream_runs(data, start, length, index)
        )
        pages.append(ParsedPage(page=index, w_pt=width, h_pt=height, runs=runs))
    return tuple(pages)


# ---------------------------------------------------------------------------
# 7. Classification: three sizes, one coalescing rule, one grid.
# ---------------------------------------------------------------------------


def _is_size(run: TextRun, size_pt: float) -> bool:
    return abs(run.size_pt - size_pt) <= _EPS_PT


def _continues(previous: TextRun, run: TextRun) -> bool:
    """The coalescing predicate: same size, and `y` down by EXACTLY the leading.

    Everything else ends the paragraph -- a larger gap, a smaller one, a rise, a size change. The
    generator makes the inter-paragraph gap strictly greater than the leading for precisely this
    reason, so the boundary is found from geometry and never from a count.
    """
    if abs(previous.size_pt - run.size_pt) > _EPS_PT:
        return False
    return abs((previous.y_pt - run.y_pt) - _LEADING_PT) <= _EPS_PT


def _coalesce(runs: Sequence[TextRun]) -> tuple[tuple[TextRun, ...], ...]:
    """Consecutive runs into paragraph groups, by `_continues` alone."""
    groups: list[list[TextRun]] = []
    for run in runs:
        if groups and _continues(groups[-1][-1], run):
            groups[-1].append(run)
        else:
            groups.append([run])
    return tuple(tuple(group) for group in groups)


def _classify(
    page: ParsedPage,
) -> tuple[tuple[TextRun, ...], tuple[tuple[TextRun, ...], ...], tuple[TextRun, ...]]:
    """`(heading runs, paragraph groups, cell runs)`, by point size and then by geometry."""
    heading = tuple(run for run in page.runs if _is_size(run, _HEADING_SIZE_PT))
    body = tuple(run for run in page.runs if _is_size(run, _BODY_SIZE_PT))
    cells = tuple(run for run in page.runs if _is_size(run, _CELL_SIZE_PT))
    if len(heading) + len(body) + len(cells) != len(page.runs):
        unknown = sorted(
            {
                run.size_pt
                for run in page.runs
                if not any(
                    _is_size(run, size) for size in (_HEADING_SIZE_PT, _BODY_SIZE_PT, _CELL_SIZE_PT)
                )
            }
        )
        raise StubParseError(
            f"page {page.page} carries runs at {unknown} pt; this stub reads only "
            f"{_HEADING_SIZE_PT}/{_BODY_SIZE_PT}/{_CELL_SIZE_PT} pt and will not guess which of "
            f"heading, prose and cell an unknown size is"
        )
    return heading, _coalesce(body), cells


def _cell_positions(cells: Sequence[TextRun]) -> tuple[tuple[int, int], ...]:
    """`(r, c)` per cell run, from the geometry: `y` descending is `r`, `x` ascending is `c`.

    Derived and not assumed. Nothing here knows how many rows or columns the fixture emits, which
    is what keeps the grid a reading of the file rather than a restatement of the generator's
    constants. Row-major arrival is not enforced here either -- `DocSink.add_grid` asserts it
    against the `ord`s `add_block` actually assigned (03:1937), which is the stronger place.
    """
    rows = sorted({round(run.y_pt, _COORD_DIGITS) for run in cells}, reverse=True)
    row_of = {y: index for index, y in enumerate(rows)}
    columns: dict[int, set[float]] = {}
    for run in cells:
        columns.setdefault(row_of[round(run.y_pt, _COORD_DIGITS)], set()).add(
            round(run.x_pt, _COORD_DIGITS)
        )
    col_of = {
        row: {x: index for index, x in enumerate(sorted(values))} for row, values in columns.items()
    }
    out: list[tuple[int, int]] = []
    for run in cells:
        row = row_of[round(run.y_pt, _COORD_DIGITS)]
        out.append((row, col_of[row][round(run.x_pt, _COORD_DIGITS)]))
    return tuple(out)


# ---------------------------------------------------------------------------
# 8. `ingest` -- the eleven methods, driven in the order 03 section 2.10 prints.
# ---------------------------------------------------------------------------


def _origin(start: int, length: int) -> OriginSpan:
    """`OriginBytes`, or `OriginNone()` for an empty extent.

    `os_b` is a LENGTH and never `0`: an empty span has a variant of its own (07:2502, enforced by
    `OriginBytes.__post_init__`). So a zero-length region is `OriginNone()` and not a lie.
    """
    if length < 1:
        return OriginNone()
    return OriginBytes(part=_PART_PATH, start=start, length=length, codec=_CODEC)


def _covering(runs: Sequence[TextRun]) -> OriginSpan:
    """The one byte range that contains every run of a group, first byte to last.

    For a single run this IS the literal. For a coalesced paragraph it necessarily also covers the
    `) Tj` / `Tm` / `(` bytes between the runs -- which is why such a block is `NORMALIZED` and
    never `VERBATIM`, and why `STUB_CAPABILITIES.origin_span` is `normalized` and not `exact`.
    """
    if not runs:
        return OriginNone()
    start = min(run.byte_start for run in runs)
    end = max(run.byte_start + run.byte_len for run in runs)
    return _origin(start, end - start)


def _verbatim(data: bytes, run: TextRun, text: str) -> bool:
    """INV-10's `bytes` predicate, evaluated rather than assumed (03:1470-1476).

    `nfc(part_bytes[os_a : os_a + os_b].decode(codec)) == block.text`. Asking the question of the
    real bytes is the difference between a `Quote` that is a measurement and one that is a hope:
    a literal that needed unescaping fails here, and so would a literal that was not already NFC.
    """
    raw = data[run.byte_start : run.byte_start + run.byte_len]
    try:
        decoded = raw.decode(*_CODEC.split("/", 1))
    except UnicodeDecodeError:
        return False
    return unicodedata.normalize("NFC", decoded) == text


def _container(kind: Kind, parent: BlockId | None, origin: OriginSpan) -> BlockDraft:
    """A structural block with no text of its own.

    `Quote.SYNTHETIC` because that is what a container IS: the driver assembled it, it quotes
    nothing, and `text` is NULL so M-INV-4's "never repeats a descendant's text" holds trivially.
    """
    return BlockDraft(
        kind=kind,
        layer=Layer.BODY,
        method=Method.NATIVE,
        trust=Trust.EXTRACTED,
        quote=Quote.SYNTHETIC,
        parent=parent,
        origin=origin,
    )


def _text_block(
    data: bytes,
    kind: Kind,
    parent: BlockId,
    runs: Sequence[TextRun],
    payload: Mapping[str, object] | None = None,
) -> BlockDraft:
    """One text block out of one or more runs, with its `Quote` decided by the bytes.

    A single run whose literal needed no unescaping is `VERBATIM`: its span decodes to exactly
    its text. Anything else -- an escape, a coalesced group, a non-NFC literal -- is `NORMALIZED`,
    because the framework's ladder exists to stop precisely the claim that assembled text is
    quotable (03 section 8.5).
    """
    text = " ".join(run.text for run in runs)
    single = len(runs) == 1 and _verbatim(data, runs[0], text)
    return BlockDraft(
        kind=kind,
        layer=Layer.BODY,
        method=Method.NATIVE,
        trust=Trust.EXTRACTED,
        quote=Quote.VERBATIM if single else Quote.NORMALIZED,
        parent=parent,
        text=text,
        origin=_covering(runs),
        payload=None if payload is None else dict(payload),
    )


def _write_table(sink: DocSink, data: bytes, parent: BlockId, cells: Sequence[TextRun]) -> None:
    """One `table` block, its cells, and a real `Grid` through `add_grid`.

    The cells are the point. 07-store-and-retrieval.md:1012-1020 makes bytes-per-block depend on
    the prose/cell mix -- *"a prose paragraph is ~300 B; a table cell is ~10 B. The 60-120
    blocks/page envelope is that wide because cells are Blocks"* -- so a fixture ingested without
    cells would measure a number the plan is not talking about.
    """
    table = sink.add_block(_container(Kind.TABLE, parent, _covering(cells)))
    drafts: list[_CellDraft] = []
    for run, (row, column) in zip(cells, _cell_positions(cells), strict=True):
        draft = _text_block(data, Kind.TABLE_CELL, table, (run,))
        draft.cell = CellPos(row, column)
        drafts.append(_CellDraft(sink.add_block(draft), CellPos(row, column)))
    sink.add_grid(table, build_grid(drafts, diag=sink.diag))


def _write_page(sink: DocSink, data: bytes, page: ParsedPage, parent: BlockId) -> int:
    """A page's content under its page root. Returns how many blocks it wrote."""
    heading, paragraphs, cells = _classify(page)
    written = 0
    for run in heading:
        sink.add_block(_text_block(data, Kind.HEADING, parent, (run,), {"level": _HEADING_LEVEL}))
        written += 1
    for group in paragraphs:
        sink.add_block(_text_block(data, Kind.PARAGRAPH, parent, group))
        written += 1
    if cells:
        _write_table(sink, data, parent, cells)
        written += 1 + len(cells)
    return written


def _doc_record(
    data: bytes, pages: Sequence[ParsedPage], *, uri: str, doc_ord: int, doc_key: bytes
) -> DocRecord:
    """The `doc` row this parse describes, at `gen = 0` -- "no committed generation" (03:82)."""
    header = data[:_HEADER_SCAN].split(b"\n", 1)[0].decode("ascii", "replace").strip()
    return DocRecord(
        doc_ord=doc_ord,
        doc_key=doc_key,
        gen=0,
        source_sha256=hashlib.sha256(data).digest(),
        # NULL, and 05:261 says what NULL means: the raw bytes were hashed. The `pdf_trailer_v1`
        # normaliser of 05:264 belongs to an ingest stage that does not exist at P2, and naming it
        # here would claim a normalisation nothing performed.
        normalizer=None,
        uri=uri,
        media_type="application/pdf",
        format="pdf",
        format_evidence=MappingProxyType({"header": header}),
        source_bytes=len(data),
        status="ok",
        page_count=len(pages),
        model_version=MODEL_VERSION,
        declared=STUB_CAPABILITIES,
        # `end_doc` overwrites this from the committed rows (INV-7 at the capability grain,
        # 03:534-536). It is passed equal to `declared` so that a reader of this record before the
        # commit sees a claim rather than a floor of absences.
        achieved=STUB_CAPABILITIES,
        confidence=MappingProxyType({}),
        timings_ms=MappingProxyType({}),
    )


def _page_record(page: ParsedPage) -> PageRecord:
    """One `page` row. `page` is the ORIGINAL 0-based source index (03:277, 03:2271)."""
    return PageRecord(
        page=page.page - 1,
        page_kind=PageKind.PAGE,
        label=None,
        w_mpt=round(page.w_pt * _MPT_PER_POINT),
        h_mpt=round(page.h_pt * _MPT_PER_POINT),
        rotation=0,
        # NULL is not "unset": it records that this driver declared no coordinate frame, which is
        # the honest reading for a driver that writes no `quad` at all (`records.py` on the field).
        quad_origin=None,
        method=Method.NATIVE,
        status="ok",
    )


def ingest(sink: DocSink, *, pdf: Path, uri: str, doc_ord: int, doc_key: bytes) -> DocRecord:
    """Drive one document through `DocSink`, and return the post-commit `DocRecord`.

    The order is 03 section 2.10's and every step of it is forced by something:

    1. `begin_doc` first (03:56), because it assigns `doc_ord` and fixes `g_t`;
    2. `begin_page` for page 1 -- and `add_part` needs an open page, because it stages its row
       into the page transaction like everything else, so the part is registered here rather than
       before the loop;
    3. `add_part("file", ...)` BEFORE any block whose origin cites it, which is every text block
       in the document;
    4. the `document` root, addr `doc` (03:816). One per `(doc_ord, gen)`, minted on the first
       page because `add_block` requires an open page;
    5. per page a page root under that document root -- 03:1027's "a block whose parent is the
       `document` root" -- then the page's content, then `end_page`, which commits ONE transaction
       (03:594) and leaves the rows durable and invisible while `g_t > doc.gen`;
    6. `end_doc("ok")`, which runs the closure pass, `owcheck`, `rebind` and the `doc.gen` bump.

    Returns what `end_doc` returns, so a caller can see the committed head -- and see that it did
    NOT move if the generation quarantined.
    """
    data = pdf.read_bytes()
    pages = parse_pdf(data)
    if not pages:
        raise StubParseError(f"{pdf} holds no pages; there is nothing to ingest")
    sink.begin_doc(_doc_record(data, pages, uri=uri, doc_ord=doc_ord, doc_key=doc_key))
    root: BlockId | None = None
    for page in pages:
        sink.begin_page(_page_record(page))
        if root is None:
            with pdf.open("rb") as handle:
                sink.add_part(_PART_PATH, handle, hashlib.sha256(data).digest(), len(data))
            root = sink.add_block(_container(Kind.DOCUMENT, None, _origin(0, len(data))))
        page_root = sink.add_block(_container(Kind.CONTAINER, root, _covering(page.runs)))
        written = _write_page(sink, data, page, page_root)
        sink.end_page({"runs": len(page.runs), "blocks": written + 1})
    return sink.end_doc("ok")
