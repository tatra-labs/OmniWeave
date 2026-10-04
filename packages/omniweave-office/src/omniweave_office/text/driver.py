"""`parse.text.builtin` -- the ten text formats anydoc does not serve, read by the standard library.

04-driver-system.md section 10.1's roster row: *"stdlib only: `codecs`, `json`, `csv`,
`html.parser`, `xml.etree` via `defusedxml`. Serves the ten tokens `decode.text-native` names --
`html`, `xhtml`, `xml`, `md`, `txt`, `json`, `jsonl`, `ipynb`, `tsv`, `svg` -- none of which
anydoc's card declares"*. ADR-3 put it in `[drivers] enabled` and 05 section 4.4's
`decode.text-native` routes to it, so until this driver existed every Markdown, text, HTML and JSON
file a corpus held was routed to a driver nothing installed, and stopped under gate 5 for ever
(D646).

## One read, one decode, one reader

The unit's bytes are read once and decoded once (`decode()`): a byte-order mark names its codec,
then UTF-8, then Latin-1, which decodes anything and says so in a `diag`. The format token comes
from the routed media type (`MEDIA_TYPES`), or from `sniff()` when the host supplies none. The
reader for that token (`readers.READERS`) writes the blocks.

## The card is honest about one thing above all

`origin_span = "none"`, as `parse.office.anydoc`'s is, and for the reason `readers` gives: a block's
text is the format's content and not a byte range of the source. A Markdown heading's text has no
`#`, an HTML paragraph's entities are decoded. Byte-exact quoting of the formats where a block could
be a byte range (`txt`, `md`'s code, `tsv`) is a later card's, and the conform `capability` suite
would fail this one if it claimed it.

Specified in 04-driver-system.md section 10.1; 05-ingest-and-routing.md section 4.4; ADR-3 D3.1.
"""

from __future__ import annotations

import codecs
import json
from typing import TYPE_CHECKING, Any, ClassVar, Final

from omniweave_ports import (
    ArtifactRef,
    DriverError,
    DriverMetrics,
    DriverResult,
    FailureClass,
    FormatGuess,
    ProbeStatus,
    ProbeVerdict,
)

from omniweave_office.text.readers import READERS, Blocks, ReadError

if TYPE_CHECKING:
    from omniweave_ports.detect import StreamHint
    from omniweave_ports.types import DriverIO, PartSelector, ProbeEnv, Scalar, UnitRef

MEDIA_TYPES: Final[dict[str, str]] = {
    "text/html": "html",
    "application/xhtml+xml": "xhtml",
    "application/xml": "xml",
    "text/markdown": "md",
    "text/plain": "txt",
    "application/json": "json",
    "application/jsonl": "jsonl",
    "application/x-ipynb+json": "ipynb",
    "text/tab-separated-values": "tsv",
    "image/svg+xml": "svg",
}
"""The ten served media types -> their format token: `[capability] formats` and `format_tokens`,
and `route.detect`'s own table for the same ten tokens. `ow route lint` check 11 holds the token
set equal to `decode.text-native`'s list."""

_BY_TOKEN: Final[dict[str, str]] = {token: media for media, token in MEDIA_TYPES.items()}

_EXTENSIONS: Final[dict[str, str]] = {
    ".md": "md",
    ".markdown": "md",
    ".qmd": "md",
    ".rmd": "md",
    ".txt": "txt",
    ".text": "txt",
    ".html": "html",
    ".htm": "html",
    ".xhtml": "xhtml",
    ".xml": "xml",
    ".json": "json",
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
    ".ipynb": "ipynb",
    ".tsv": "tsv",
    ".svg": "svg",
}
"""The extensions `route.detect` reads for the same ten tokens, so `sniff()` agrees with it."""

PART: Final = "text/source"
"""The one part, not retained: with `origin_span = "none"` nothing could be re-proved from it, the
anydoc driver's reasoning (`omniweave_office.driver.PART`)."""

LATIN1_DIAG: Final = "OW_TEXT_NOT_UTF8"
"""A `diag` on page 0 when the bytes were not UTF-8 and were read as Latin-1. Severity `warning`:
every byte decodes, and a few characters may be the wrong ones."""

_BOMS: Final[tuple[tuple[bytes, str], ...]] = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)
_PAGE: Final = 0
_HEAD: Final = 4096
_HEAD_WINDOW: Final = 65_536
_EXTENSION_CONFIDENCE: Final = 0.6
_CONTENT_CONFIDENCE: Final = 0.85

ACHIEVED_CONSTANTS: Final[dict[str, object]] = {
    "spatial": "none",
    "origin_span": "none",
    "text_span": False,
    "marks": False,
    "reading_order": "source",
    "math": [],
    "assets": "none",
    "asset_origin": False,
    "notes": "none",
    "confidence": "none",
    "furniture": "destroyed",
    "round_trip": "structure",
    "forfeits": [],
}
"""The thirteen of the fifteen that are the same for every document. `furniture = "destroyed"` is
the lowest rung and the honest one for a format that has no running header to keep: the rung is a
statement that none was kept, and here there was none to keep. `sections` and `tables` are computed
per document by `_achieved()`."""


class TextParser:
    """HTML, XHTML, XML, Markdown, text, JSON, JSONL, notebooks, TSV and SVG, stdlib only."""

    PORT: ClassVar[str] = "parse/1"
    SCHEMA_VERSION: ClassVar[int] = 1

    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict:
        """The standard library is always there; `defusedxml` is the one thing to check."""
        del env
        try:
            import defusedxml  # noqa: PLC0415, F401 -- the probe's one question
        except ImportError:
            return ProbeVerdict(
                status=ProbeStatus.UNAVAILABLE,
                detail="defusedxml is not installed, and the XML and SVG readers need it",
                missing=("defusedxml",),
                fix_hint="uv pip install 'defusedxml>=0.7.1'",
            )
        from importlib.metadata import version  # noqa: PLC0415

        return ProbeVerdict(status=ProbeStatus.OK, detail=f"defusedxml {version('defusedxml')}")

    def __init__(self, **config: Scalar) -> None:
        """No configuration: the card's `[config]` accepts none."""
        del config

    def sniff(self, head: bytes, hint: StreamHint) -> tuple[FormatGuess, ...]:
        """The content signal for the formats that have one, then the extension.

        Bytes with a NUL in them and no byte-order mark are not text, and get `()`. A notebook, an
        SVG, an HTML document and an XML declaration announce themselves in their first bytes; the
        rest are named by their extension, which is what `route.detect` reads for them too.
        """
        bom = any(head.startswith(mark) for mark, _codec in _BOMS)
        if b"\x00" in head[:_HEAD] and not bom:
            return ()
        start = head[:_HEAD].decode("utf-8", "ignore").lstrip("\ufeff \t\r\n").lower()
        named = None
        if start.startswith("{") and '"nbformat"' in start and '"cells"' in start:
            named = "ipynb"
        elif "<svg" in start:
            named = "svg"
        elif start.startswith(("<!doctype html", "<html")):
            named = "html"
        if named is not None:
            return (_guess(named, _CONTENT_CONFIDENCE, len(head)),)
        named = _EXTENSIONS.get((hint.extension or "").lower())
        if named is None:
            return ()
        return (_guess(named, _EXTENSION_CONFIDENCE, len(head)),)

    def parse(self, unit: UnitRef, parts: PartSelector, io: DriverIO) -> DriverResult:
        """Read, decode, read the format, then `owdoc-fragment/1`.

        Raises:
            DriverError: `UNSUPPORTED_FORMAT` when no media type was routed and the bytes name
                none of the ten; `CORRUPT_INPUT` when they are not the format they were routed as
                (`readers.ReadError`); `TIMEOUT` when cancelled.
        """
        del parts
        with io.blobs.open(unit.content_sha256) as handle:
            raw = handle.read()
        token = MEDIA_TYPES.get(unit.media_type or "") or _sniffed(raw, unit.uri)
        if token is None:
            raise DriverError(
                cls=FailureClass.UNSUPPORTED_FORMAT,
                message="no media type was routed, and these bytes name none of the ten formats",
            )
        text, codec = decode(raw)
        out = Blocks()
        takes_bytes, reader = READERS[token]
        try:
            reader(raw if takes_bytes else text, out)
        except ReadError as exc:
            raise DriverError(cls=FailureClass.CORRUPT_INPUT, message=f"{token}: {exc}") from None
        body = _emit(out.records, io)
        diags = [] if codec != "latin-1" else [_latin1_diag()]
        blocks = len(body)
        records = [
            {
                "t": "doc",
                "format": token,
                "media_type": _BY_TOKEN[token],
                "page_count": 1,
                "achieved": _achieved(out),
            },
            {
                "t": "part",
                "path": PART,
                "sha256": unit.content_sha256,
                "byte_len": len(raw),
                "retain": False,
            },
            _page_record(),
            *body,
            *diags,
            {"t": "end", "status": "ok", "page_stats": {str(_PAGE): {"blocks": blocks}}},
        ]
        payload = "".join(
            json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n"
            for record in records
        ).encode("utf-8")
        return DriverResult(
            outcome="ok",
            produced=(ArtifactRef.of("doc_fragment", payload, io),),
            metrics=DriverMetrics(bytes_read=len(raw)),
        )

    def is_valid_nonempty(self, ref: ArtifactRef) -> bool:
        """The host calls this BEFORE caching: an empty text file is legitimately empty.

        An `ok` with no block becomes `FAILED_PERMANENT(EMPTY_RESULT)` host-side, so an empty
        success is never memoised; the PDF and office drivers ask the same question.
        """
        return b'"t":"block"' in ref.head(_HEAD_WINDOW)


def _emit(records: list[dict[str, Any]], io: DriverIO) -> list[dict[str, Any]]:
    """The records, checking cancellation at every loop top and reporting progress.

    04-driver-system.md:1738 says `io.cancelled()` is checked "at every loop top". The readers
    build the records in one pass over text already in memory; this is the loop over what they
    built, and progress counts top-level blocks, as the anydoc driver's does, so `done` and
    `total` are commensurable.
    """
    total = sum(1 for record in records if record.get("parent") is None)
    done = 0
    body: list[dict[str, Any]] = []
    for record in records:
        if io.cancelled():  # CHECK AT EVERY LOOP TOP
            raise DriverError(
                cls=FailureClass.TIMEOUT,
                message=f"cancelled after {done} of {total} top-level blocks",
                retry_after_ms=0,
            )
        body.append(record)
        if record.get("parent") is None:
            done += 1
            io.progress(done=done, total=total)
    return body


def decode(raw: bytes) -> tuple[str, str]:
    """The text, and the codec that read it: a byte-order mark's, else UTF-8, else Latin-1.

    Latin-1 is the last resort because it cannot fail: every byte is a character. A file in another
    single-byte encoding then reads with a few wrong characters rather than not at all, and the
    `OW_TEXT_NOT_UTF8` diag says which happened.
    """
    for mark, codec in _BOMS:
        if raw.startswith(mark):
            try:
                return raw.decode(codec), codec
            except UnicodeDecodeError:
                break
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return raw.decode("latin-1"), "latin-1"


def _sniffed(raw: bytes, uri: str) -> str | None:
    from omniweave_ports.detect import StreamHint  # noqa: PLC0415 -- the no-media-type path

    name = uri.rsplit("/", 1)[-1]
    extension = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    hint = StreamHint(filename=name, extension=extension, declared_media_type=None, byte_len=None)
    guesses = TextParser().sniff(raw[:_HEAD], hint)
    return guesses[0].format_token if guesses else None


def _guess(token: str, confidence: float, consumed: int) -> FormatGuess:
    return FormatGuess(
        media_type=_BY_TOKEN[token],
        format_token=token,
        confidence=confidence,
        consumed_bytes=consumed,
    )


def _achieved(out: Blocks) -> dict[str, object]:
    """The fifteen: thirteen constants, and `sections` and `tables` from what was written.

    03 section 2.9's rollup applied driver-side, as the anydoc driver does: `sections` is
    `outline_from_source` when the document had a heading, `tables` is `cells_with_spans` when a
    cell spans, `cells` when there was a table, `none` otherwise.
    """
    tables = "none"
    if out.tables:
        tables = "cells_with_spans" if out.has_spans else "cells"
    return {
        **ACHIEVED_CONSTANTS,
        "sections": "outline_from_source" if out.headings else "none",
        "tables": tables,
    }


def _page_record() -> dict[str, Any]:
    """One `stream` page: a text file has no page box, as an office document has none."""
    return {
        "t": "page",
        "page": _PAGE,
        "page_kind": "stream",
        "w_mpt": None,
        "h_mpt": None,
        "quad_origin": None,
        "quad_unit": None,
        "quad_dpi": None,
        "rotation": 0,
        "method": "native",
    }


def _latin1_diag() -> dict[str, Any]:
    return {
        "t": "diag",
        "code": LATIN1_DIAG,
        "severity": "warning",
        "component": "parse.text.builtin",
        "message": "the bytes are not UTF-8 and were read as Latin-1; some characters may be wrong",
        "page": _PAGE,
        "part": PART,
        "detail": {"codec": "latin-1"},
        "fatal": False,
    }
