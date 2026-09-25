"""Format detection: 05 section 2's ladder, host side, FREE, once per unit at `op.identify`.

05:530: *"Detection produces a **ranked tuple**, not a value."* 05:559 places it: *"The ladder runs
once per unit at the `acquired -> identified` transition, entirely FREE"* -- which is the transition
`op.identify` makes, so `run.ingest`'s identify dispatcher calls `detect()` before it counts, and
`unit.format`, `unit.media_type` and the evidence ride in the same `complete()` transaction as
`unit.part_count`. Until W7.3x nothing wrote either column (D166), and every routing rule of 05
section 4.4 reads `unit.format` first.

```
0.  bytes == 0                                   -> 'empty'
1.  HEAD = the first 8192 bytes, one read
2.  the magic-byte table (05 section 2.2)        -> basis 'magic',              0.99
3.  a container's own identity part (2.5)        -> basis 'container_identity', 0.98
4.  enabled drivers' sniff(HEAD, hint)           -> NOT RUN here (D568)
5.  content probes for text (2.3)                -> basis 'content_probe',      0.50-0.95
6.  the extension table                          -> basis 'extension',          0.40
7.  hint.declared_media_type                     -> basis 'declared',           0.30
8.  nothing                                      -> 'unknown'
```

Ranked by `(basis_rank, -confidence, format_token)` (05:576): a total order, so a re-run detects the
same way whatever order anything loaded in.

## THE TWO CONTAINERS THIS MODULE OPENS, AND THE BOUND ON EACH

**ZIP** (05:739-746). `mimetype` is the identity for ODF and EPUB. For OPC, the package-level
`officeDocument` relationship in `_rels/.rels` names a part, `[Content_Types].xml` names its type,
and when the types are stale or generic the part's root element decides. Every identity part is
read at most `MAX_IDENTITY_BYTES` under the bounded-read-then-check rule, and one containing
`<!DOCTYPE` or `<!ENTITY` is refused outright: *"`xml.etree.ElementTree`'s default parser *does*
expand internal entities, so billion-laughs otherwise reaches the **host** through detection"*
(05:752-754). The refusal is `DriverError(RESOURCE_LIMIT, limit="MAX_IDENTITY_BYTES")`, which
`op.identify` turns into a permanent failure with that class.

**OLE compound file** (05:756-763). The root storage's children, case-insensitively:
`WordDocument` -> `doc`, `PowerPoint Document` -> `ppt`, `Workbook` / `Book` -> `xls`,
`__properties_version1.0` with `__substg1.0_*` -> `msg`, and `EncryptedPackage` -> `unknown` with
`encrypted = True`. The plan gives the ZIP parts a bound and the CFB none; this module reads the
compound file's header, the FAT sectors the directory chain crosses and the directory sectors, and
the total is held to the same `MAX_IDENTITY_BYTES` (D569).

## WHAT IT DOES NOT DO

- **Step 4, the drivers' `sniff()`.** It needs the catalog (startup step 7, not built into a run)
  and an import of every enabled driver, and `omniweave` may not import `omniweave_pdf` (D568).
  Every format the two shipped decoders read has a host rung above `driver_sniff` -- magic for PDF,
  container identity for the Office and ODF family, the extension for CSV -- so a sniff could only
  have lost the ranking to what is already here.
- **Expansion.** A `zip`, `tar`, `eml` or `mbox` is detected as the container token and nothing
  more; 05:764-776's child units are the expander's.
- **`Diag` rows.** `OW_FORMAT_AMBIGUOUS` and `OW_FORMAT_EXTENSION_MISMATCH` are `diag` rows keyed to
  a document, and no `doc` row exists at identify. The two facts are `ambiguous` and
  `extension_mismatch` in the evidence, which is where `DocSink` will read them from.

Specified in 05-ingest-and-routing.md sections 2.1-2.5 (:528-777) and 04-driver-system.md
section 1.3.
"""

from __future__ import annotations

import csv
import json
import re
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal
from xml.etree import ElementTree

from omniweave_core.limits import MAX_IDENTITY_BYTES
from omniweave_ports.detect import FormatGuess, StreamHint
from omniweave_ports.types import DriverError, FailureClass

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

__all__ = [
    "BASIS_RANK",
    "CONTAINER_FORMATS",
    "CORE_FORMATS",
    "EXTENSIONS",
    "HEAD_BYTES",
    "MEDIA_TYPES",
    "RESOURCE_LIMIT_COOLDOWN_MS",
    "Basis",
    "Detection",
    "RankedGuess",
    "computed_domain",
    "detect",
    "detect_bytes",
    "format_token_for",
    "hint_for",
]

Basis = Literal[
    "magic", "container_identity", "content_probe", "extension", "declared", "driver_sniff"
]

BASIS_RANK: Final[Mapping[str, int]] = MappingProxyType(
    {
        "magic": 0,
        "container_identity": 1,
        "driver_sniff": 2,
        "content_probe": 3,
        "extension": 4,
        "declared": 5,
    }
)
"""05:576: *"`magic` < `container_identity` < `driver_sniff` < `content_probe` < `extension` <
`declared`"*. `driver_sniff` holds its rank though step 4 does not run here (D568)."""

HEAD_BYTES: Final[int] = 8192
"""05:563: *"read HEAD = the first 8192 bytes (one read; the stream is NEVER advanced past it)"*."""

MEDIA_TYPES: Final[Mapping[str, str | None]] = MappingProxyType(
    {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "doc": "application/msword",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "ppt": "application/vnd.ms-powerpoint",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xls": "application/vnd.ms-excel",
        "csv": "text/csv",
        "tsv": "text/tab-separated-values",
        "rtf": "application/rtf",
        "odt": "application/vnd.oasis.opendocument.text",
        "ods": "application/vnd.oasis.opendocument.spreadsheet",
        "odp": "application/vnd.oasis.opendocument.presentation",
        "epub": "application/epub+zip",
        "html": "text/html",
        "xhtml": "application/xhtml+xml",
        "xml": "application/xml",
        "md": "text/markdown",
        "txt": "text/plain",
        "json": "application/json",
        "jsonl": "application/jsonl",
        "ipynb": "application/x-ipynb+json",
        "svg": "image/svg+xml",
        "eml": "message/rfc822",
        "msg": "application/vnd.ms-outlook",
        "mbox": "application/mbox",
        "png": "image/png",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "tiff": "image/tiff",
        "bmp": "image/bmp",
        "gif": "image/gif",
        "mp4": "video/mp4",
        "matroska": "video/x-matroska",
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "flac": "audio/flac",
        "ogg": "audio/ogg",
        "ps": "application/postscript",
        "sqlite": "application/vnd.sqlite3",
        "zip": "application/zip",
        "tar": "application/x-tar",
        "gz": "application/gzip",
        "sevenz": "application/x-7z-compressed",
        "rar": "application/vnd.rar",
        "xz": "application/x-xz",
        "empty": None,
        "unknown": None,
    }
)
"""Core's forty-eight tokens (05:636-639) in the plan's order, each with its media type.

05 section 2.2 prints the media type of the signature rows and of none of the probe rows; the probe
rows' types are the IANA registrations where one exists (`text/tab-separated-values`,
`application/xhtml+xml`, `text/markdown`, `image/svg+xml`) and the de-facto type where none does
(`application/jsonl`, `application/x-ipynb+json`, `application/vnd.ms-outlook`). The twelve Office
rows are exactly `parse.office.anydoc`'s `format_tokens` pairs, which a test asserts, so
`format_token_for()` stays single-valued across the card (05:666, `OW-D-024`). `empty` and
`unknown` have no media type: they are the two terminal non-formats."""

CORE_FORMATS: Final[tuple[str, ...]] = tuple(MEDIA_TYPES)
CONTAINER_FORMATS: Final[frozenset[str]] = frozenset(
    {"zip", "tar", "gz", "sevenz", "rar", "xz", "eml", "msg", "mbox"}
)
"""05:638's six archives, *"never a parse target, only an expansion source"*, plus the three mail
containers 05:764-769 expands rather than parses."""

_TOKEN_FOR_MEDIA: Final[Mapping[str, str]] = MappingProxyType(
    {media: token for token, media in MEDIA_TYPES.items() if media is not None}
)

EXTENSIONS: Final[Mapping[str, str]] = MappingProxyType(
    {
        **{f".{token}": token for token in CORE_FORMATS if token not in {"empty", "unknown"}},
        ".jpg": "jpeg",
        ".jpe": "jpeg",
        ".tif": "tiff",
        ".htm": "html",
        ".markdown": "md",
        ".qmd": "md",
        ".rmd": "md",
        ".text": "txt",
        ".ndjson": "jsonl",
        ".mkv": "matroska",
        ".oga": "ogg",
        ".7z": "sevenz",
        ".tgz": "gz",
        ".eps": "ps",
        ".sqlite3": "sqlite",
        ".db": "sqlite",
    }
)
"""Step 6's *"explicit table"* (05:571). Every token's own spelling is an extension of it, plus the
common aliases; `sevenz` and `matroska` are spelled `.7z` and `.mkv`, not as their tokens."""

_CONFIDENCE: Final[Mapping[str, float]] = MappingProxyType(
    {"magic": 0.99, "container_identity": 0.98, "extension": 0.40, "declared": 0.30}
)

_OPC_RELATIONSHIP: Final[tuple[str, ...]] = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument",
    "http://purl.oclc.org/ooxml/officeDocument/relationships/officeDocument",
)
"""The package-level relationship naming the main part, transitional and strict (ECMA-376)."""

_OPC_MAIN: Final[Mapping[str, str]] = MappingProxyType(
    {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml": "docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml": "docx",
        "application/vnd.ms-word.document.macroenabled.main+xml": "docx",
        "application/vnd.ms-word.template.macroenabledtemplate.main+xml": "docx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml": (
            "pptx"
        ),
        "application/vnd.openxmlformats-officedocument.presentationml.slideshow.main+xml": "pptx",
        "application/vnd.openxmlformats-officedocument.presentationml.template.main+xml": "pptx",
        "application/vnd.ms-powerpoint.presentation.macroenabled.main+xml": "pptx",
        "application/vnd.ms-powerpoint.slideshow.macroenabled.main+xml": "pptx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml": "xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.template.main+xml": "xlsx",
        "application/vnd.ms-excel.sheet.macroenabled.main+xml": "xlsx",
        "application/vnd.ms-excel.template.macroenabled.main+xml": "xlsx",
    }
)
"""The main part's content type, lower-cased, to its token. Templates, slide shows and the
macro-enabled variants are the same package with the same main part, so they take their family's
token -- a separate token would be a format no rule names and no driver declares."""

_OPC_ROOT: Final[Mapping[str, str]] = MappingProxyType(
    {"document": "docx", "presentation": "pptx", "workbook": "xlsx"}
)
"""05:742: *"fall back to that part's mandated root element"* -- `w:document`, `p:presentation`,
`x:workbook`, matched on the local name under any namespace (strict and transitional differ)."""

_ODF_MIMETYPE: Final[Mapping[str, str]] = MappingProxyType(
    {
        "application/vnd.oasis.opendocument.text": "odt",
        "application/vnd.oasis.opendocument.spreadsheet": "ods",
        "application/vnd.oasis.opendocument.presentation": "odp",
        "application/epub+zip": "epub",
    }
)

_CFB_MAGIC: Final[bytes] = bytes.fromhex("D0CF11E0A1B11AE1")
_CFB_FREE: Final[int] = 0xFFFFFFFF
_CFB_END: Final[int] = 0xFFFFFFFE
_CFB_NOSTREAM: Final[int] = 0xFFFFFFFF
_CFB_ENTRY: Final[int] = 128
_CFB_STREAMS: Final[Mapping[str, str]] = MappingProxyType(
    {"worddocument": "doc", "powerpoint document": "ppt", "workbook": "xls", "book": "xls"}
)

_BINARY: Final = re.compile(rb"[\x00-\x08\x0e-\x1f]")
_HEADER_LINE: Final = re.compile(r"^[!-9;-~]+:[ \t]?.*$")
_COMMENT: Final = re.compile(r"<!--.*?-->", re.DOTALL)
_DOCTYPE_ROOT: Final = re.compile(r"<!DOCTYPE\s+([A-Za-z_][\w.:-]*)", re.IGNORECASE)
_HTML_START: Final = re.compile(
    r"^\s*(?:<script\b.*?</script>\s*)?(?:<!doctype\s+html|<html\b|<head\b|<body\b)",
    re.IGNORECASE | re.DOTALL,
)
_SVG: Final = re.compile(r"<svg\b[^>]*xmlns\s*=\s*[\"']http://www\.w3\.org/2000/svg[\"']", re.I)
_MD_TOKEN: Final = re.compile(r"^(?:#{1,6}\s|\s*[-*+]\s|\s*\d+[.)]\s|```|~~~)", re.MULTILINE)
_MD_EXTENSIONS: Final[frozenset[str]] = frozenset({".md", ".markdown", ".qmd", ".rmd"})

_CFB: Final[str] = "cfb"
"""Row 3's container, which is not a token: its identity or nothing replaces it."""
_CFB_NAME_BYTES: Final[int] = 64
"""[MS-CFB] 2.6.1: a directory entry's name is at most 32 UTF-16 code units with the NUL."""
_UTF16_NUL: Final[int] = 2
_AMBIGUOUS_FLOOR: Final[float] = 0.60
_AMBIGUOUS_WITHIN: Final[float] = 0.05
"""05:700: *"Two candidates within 0.05 of each other, both above 0.60"*."""
_BMP_HEADER_END: Final[int] = 18
_MIN_HEADERS: Final[int] = 2
"""A header block is two or more fields: one `Name: value` line is prose as often as not."""
_MIN_JSONL_LINES: Final[int] = 2
"""One JSON object on one line is `json`; `jsonl` needs a second line to be lines at all."""
_MIN_COLUMNS: Final[int] = 2
_MIN_ROWS: Final[int] = 3
"""05:689: *"≥2 columns on ≥3 consecutive lines"*."""
_SNIFF_LINES: Final[int] = 64
_UTF16LE_BOM: Final[bytes] = bytes.fromhex("FFFE")
RESOURCE_LIMIT_COOLDOWN_MS: Final[int] = 60_000
"""08:568's `resource_limit` row: *"driver or host | transient | 60,000 ms"*. `DriverError` refuses
a transient class without a cooldown, so the host's refusal carries the table's -- and `op.identify`
still fails the unit permanently, because a DTD'd identity part is the same bytes on every retry."""
_MPEG_SYNC: Final = re.compile(rb"\xff[\xf0-\xff]")
"""Row 15's `FF Fx`: an MPEG audio frame's sync bits."""


@dataclass(frozen=True, slots=True)
class RankedGuess:
    """05:542-552's host wrapper: a `FormatGuess` plus what only the host can say about it."""

    guess: FormatGuess
    basis: Basis
    detail: str

    @property
    def key(self) -> tuple[int, float, str]:
        """05:576's total order."""
        return (BASIS_RANK[self.basis], -self.guess.confidence, self.guess.format_token)

    def as_json(self) -> dict[str, object]:
        return {
            "format": self.guess.format_token,
            "media_type": self.guess.media_type,
            "confidence": self.guess.confidence,
            "basis": self.basis,
            "detail": self.detail,
            "consumed_bytes": self.guess.consumed_bytes,
        }


@dataclass(frozen=True, slots=True)
class Detection:
    """One unit's ladder: the winner, every loser, and 05 section 2.4's evidence."""

    format: str
    media_type: str | None
    chosen: RankedGuess | None
    rejected: tuple[RankedGuess, ...] = ()
    hint: StreamHint | None = None
    ambiguous: bool = False
    extension_mismatch: bool = False
    encrypted: bool = False

    @property
    def weak(self) -> bool:
        """05:703-705's case 3: an `extension` or `declared` winner, which the `fields` and `table`
        lanes refuse."""
        return self.chosen is not None and self.chosen.basis in {"extension", "declared"}

    def evidence(self) -> dict[str, object]:
        """05:716-732's `doc.format_evidence`, key for key. Serialise with `evidence_json()`."""
        chosen = (
            {"format": self.format, "media_type": self.media_type, "basis": None, "detail": ""}
            if self.chosen is None
            else self.chosen.as_json()
        )
        winner = None if self.chosen is None else self.chosen.basis
        return {
            "v": 1,
            "chosen": chosen,
            "rejected": [{**one.as_json(), "superseded_by": winner} for one in self.rejected],
            "hint": {
                "extension": None if self.hint is None else self.hint.extension,
                "media_type_hint": None if self.hint is None else self.hint.declared_media_type,
            },
            "ambiguous": self.ambiguous,
            "extension_mismatch": self.extension_mismatch,
            "container": {"depth": 0, "member_path": None},
            "providers": [],
            **({"encrypted": True} if self.encrypted else {}),
        }

    def evidence_json(self) -> str:
        """05:713: *"Byte-canonical, sorted keys, `allow_nan=False`"*."""
        return json.dumps(self.evidence(), sort_keys=True, separators=(",", ":"), allow_nan=False)


def format_token_for(media_type: str, cards: Iterable[tuple[str, str]] = ()) -> str | None:
    """05:655's lookup: core's table, then every enabled card's `(media_type, token)` pairs."""
    found = _TOKEN_FOR_MEDIA.get(media_type)
    if found is not None:
        return found
    for media, token in cards:
        if media == media_type:
            return token
    return None


def computed_domain(cards: Iterable[tuple[str, str]] = ()) -> frozenset[str]:
    """`unit.format`'s domain (05:629-631): core's forty-eight union the cards' tokens."""
    return frozenset(CORE_FORMATS) | {token for _media, token in cards}


def hint_for(path: Path, *, byte_len: int | None = None) -> StreamHint:
    """The `fs` connector's hint: a basename, its lower-cased extension, and no declared type."""
    suffix = path.suffix.lower()
    return StreamHint(
        filename=path.name,
        extension=suffix or None,
        declared_media_type=None,
        byte_len=byte_len,
    )


def detect(path: Path) -> Detection:
    """Run the ladder over the file at `path`. HEAD is one read; a container is opened by path.

    Raises `OSError` when the file cannot be read and `DriverError(RESOURCE_LIMIT)` when a
    container's identity part breaks 05:748's bound or carries a DTD.
    """
    size = path.stat().st_size
    with path.open("rb") as handle:
        head = handle.read(HEAD_BYTES)
    return detect_bytes(head, hint_for(path, byte_len=size), opener=_PathOpener(path))


def detect_bytes(head: bytes, hint: StreamHint, *, opener: _PathOpener | None = None) -> Detection:
    """The ladder over HEAD, with `opener` for a container's identity. `detect()` is the caller.

    **A container's identity supersedes its own magic** (D570). 05:576 ranks `magic` above
    `container_identity`, so read literally every DOCX would detect as `zip`; 05:716-732's printed
    evidence has exactly the opposite -- `docx` chosen at `container_identity`, `zip` rejected with
    `"superseded_by": "container_identity"`. The identity is a reading *of* the container the magic
    named, so it replaces that one guess and ranks against everything else as printed.
    """
    if hint.byte_len == 0 or (hint.byte_len is None and not head):
        return Detection(format="empty", media_type=None, chosen=None, hint=hint)
    candidates: list[RankedGuess] = []
    superseded: list[RankedGuess] = []
    magic = _magic(head)
    encrypted = False
    if magic is not None:
        identity, encrypted = _container(magic, opener)
        if identity is not None:
            candidates.append(identity)
            superseded.append(magic)
        elif magic.guess.format_token != _CFB:
            candidates.append(magic)
    text = None if magic is not None else _as_text(head)
    if text is not None:
        truncated = hint.byte_len is None or hint.byte_len > len(head)
        candidates.extend(_probes(text, hint, truncated=truncated))
    binary = text is None and (magic is None or magic.guess.format_token == _CFB)
    binary = binary and _BINARY.search(head) is not None
    if not binary:
        by_extension = EXTENSIONS.get(hint.extension or "")
        if by_extension is not None:
            candidates.append(_guess(by_extension, "extension", f"extension {hint.extension}", 0))
        declared = hint.declared_media_type
        token = None if declared is None else format_token_for(declared)
        if token is not None:
            candidates.append(_guess(token, "declared", f"declared {declared}", 0))
    return _decide(candidates, superseded, hint, encrypted=encrypted)


def _decide(
    candidates: Sequence[RankedGuess],
    superseded: Sequence[RankedGuess],
    hint: StreamHint,
    *,
    encrypted: bool,
) -> Detection:
    ranked = sorted(candidates, key=lambda one: one.key)
    if encrypted or not ranked:
        return Detection(
            format="unknown",
            media_type=None,
            chosen=None,
            rejected=(*superseded, *ranked),
            hint=hint,
            encrypted=encrypted,
        )
    chosen, rejected = ranked[0], (*superseded, *ranked[1:])
    probes = [one for one in ranked if one.guess.confidence > _AMBIGUOUS_FLOOR]
    ambiguous = (
        len(probes) > 1
        and probes[0].guess.format_token != probes[1].guess.format_token
        and abs(probes[0].guess.confidence - probes[1].guess.confidence) <= _AMBIGUOUS_WITHIN
    )
    by_extension = EXTENSIONS.get(hint.extension or "")
    mismatch = (
        chosen.basis in {"magic", "container_identity"}
        and by_extension is not None
        and by_extension != chosen.guess.format_token
    )
    return Detection(
        format=chosen.guess.format_token,
        media_type=chosen.guess.media_type,
        chosen=chosen,
        rejected=rejected,
        hint=hint,
        ambiguous=ambiguous,
        extension_mismatch=mismatch,
    )


def _guess(
    token: str, basis: Basis, detail: str, consumed: int, confidence: float | None = None
) -> RankedGuess:
    return RankedGuess(
        guess=FormatGuess(
            media_type=MEDIA_TYPES.get(token) or "application/octet-stream",
            format_token=token,
            confidence=_CONFIDENCE[basis] if confidence is None else confidence,
            consumed_bytes=consumed,
        ),
        basis=basis,
        detail=detail,
    )


# =============================================================================================
# Step 2: the magic-byte table, 05 section 2.2, rows 1-20 in order
# =============================================================================================


def _magic(head: bytes) -> RankedGuess | None:  # noqa: PLR0911 -- the table is the function
    """The first row of 05:601-620 that matches, or `None`. Row 21 (text) is `_as_text()`."""
    if b"%PDF-" in head[:1024]:
        return _guess("pdf", "magic", "%PDF- in the first 1024 bytes", head.index(b"%PDF-") + 5)
    for prefix, token, detail in _PREFIXES:
        if head.startswith(prefix):
            return _guess(token, "magic", detail, len(prefix))
    if head[257:262] == b"ustar":
        return _guess("tar", "magic", "ustar at offset 257", 262)
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return _guess("webp", "magic", "RIFF + WEBP at 8", 12)
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return _guess("wav", "magic", "RIFF + WAVE at 8", 12)
    if (
        head[:2] == b"BM"
        and len(head) >= _BMP_HEADER_END
        and struct.unpack_from("<I", head, 14)[0] in {12, 40, 108, 124}
    ):
        return _guess("bmp", "magic", "BM + a DIB header size at 14", 18)
    if head[4:8] == b"ftyp":
        return _guess("mp4", "magic", "an ftyp box at offset 4", 8)
    #  D571: `FF FE` is the UTF-16LE byte-order mark, row 21's text, and row 15's `FF Fx` matches it
    #  first. A BOM is the stronger statement: it is exactly two bytes chosen to say "text".
    if _MPEG_SYNC.match(head) and not head.startswith(_UTF16LE_BOM):
        return _guess("mp3", "magic", "an MPEG audio frame sync", 2)
    mail = _mail(head)
    if mail is not None:
        return mail
    return None


_PREFIXES: Final[tuple[tuple[bytes, str, str], ...]] = (
    (b"{\\rtf", "rtf", "{\\rtf prefix"),
    (_CFB_MAGIC, _CFB, "D0 CF 11 E0 A1 B1 1A E1 (MS-CFB)"),
    (b"PK\x03\x04", "zip", "PK 03 04"),
    (b"\x1f\x8b", "gz", "1F 8B"),
    (b"7z\xbc\xaf\x27\x1c", "sevenz", "37 7A BC AF 27 1C"),
    (b"Rar!\x1a\x07", "rar", "52 61 72 21 1A 07"),
    (b"\xfd7zXZ", "xz", "FD 37 7A 58 5A"),
    (b"\x89PNG\r\n\x1a\n", "png", "89 50 4E 47 0D 0A 1A 0A"),
    (b"\xff\xd8\xff", "jpeg", "FF D8 FF"),
    (b"II*\x00", "tiff", "49 49 2A 00"),
    (b"MM\x00*", "tiff", "4D 4D 00 2A"),
    (b"GIF87a", "gif", "GIF87a"),
    (b"GIF89a", "gif", "GIF89a"),
    (b"OggS", "ogg", "OggS"),
    (b"fLaC", "flac", "fLaC"),
    (b"ID3", "mp3", "ID3"),
    (b"\x1aE\xdf\xa3", "matroska", "1A 45 DF A3"),
    (b"SQLite format 3\x00", "sqlite", "SQLite format 3 + 00"),
    (b"%!PS-Adobe", "ps", "%!PS-Adobe"),
)
"""05:601-620's prefix rows in their order. `cfb` is not a token: it is row 3's *"container"*, and
`_container()` replaces it with what the root storage says, or with `unknown`."""


def _mail(head: bytes) -> RankedGuess | None:
    """Rows 18-19: an mbox `From ` line then a header block, or a header block naming a message."""
    try:
        text = head.decode("utf-8")
    except UnicodeDecodeError:
        text = head.decode("latin-1")
    lines = text.splitlines()
    if lines and lines[0].startswith("From ") and _headers(lines[1:]):
        return _guess("mbox", "magic", "From at offset 0 + an RFC 5322 header block", 5)
    names = _headers(lines)
    if names & {"received", "message-id"}:
        return _guess("eml", "magic", "an RFC 5322 header block with Received or Message-ID", 0)
    return None


def _headers(lines: Sequence[str]) -> set[str]:
    """The field names of an RFC 5322 header block at the top of `lines`, or none."""
    names: set[str] = set()
    for line in lines:
        if not line.strip():
            return names if len(names) >= _MIN_HEADERS else set()
        if line[:1] in {" ", "\t"} and names:
            continue
        if not _HEADER_LINE.match(line):
            return set()
        names.add(line.split(":", 1)[0].lower())
    return set()


# =============================================================================================
# Step 3: a container's own identity, 05 section 2.5
# =============================================================================================


class _PathOpener:
    """Opens the unit's file again for a container's identity. The HEAD read never advanced."""

    __slots__ = ("path",)

    def __init__(self, path: Path) -> None:
        self.path = path


def _container(magic: RankedGuess, opener: _PathOpener | None) -> tuple[RankedGuess | None, bool]:
    """`(identity guess or None, encrypted)`. Only ZIP and CFB have an identity this reads."""
    token = magic.guess.format_token
    if opener is None:
        return None, False
    if token == "zip":  # noqa: S105 -- a format token
        return _zip_identity(opener.path), False
    if token == _CFB:
        return _cfb_identity(opener.path)
    return None, False


def _bounded(archive: zipfile.ZipFile, name: str) -> bytes:
    """05:748-754: at most `MAX_IDENTITY_BYTES`, and no DTD. Both breaches are `RESOURCE_LIMIT`."""
    with archive.open(name) as member:
        body = member.read(MAX_IDENTITY_BYTES + 1)
    if len(body) > MAX_IDENTITY_BYTES or b"<!DOCTYPE" in body or b"<!ENTITY" in body:
        raise DriverError(
            cls=FailureClass.RESOURCE_LIMIT,
            message=f"the identity part {name} is over {MAX_IDENTITY_BYTES} bytes or has a DTD",
            limit="MAX_IDENTITY_BYTES",
            retry_after_ms=RESOURCE_LIMIT_COOLDOWN_MS,
        )
    return body


def _zip_identity(path: Path) -> RankedGuess | None:
    """ODF and EPUB by `mimetype`, OPC by relationship, content type and root element."""
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if "mimetype" in names:
                declared = _bounded(archive, "mimetype").decode("ascii", "replace").strip()
                token = _ODF_MIMETYPE.get(declared)
                if token is not None:
                    return _guess(token, "container_identity", f"mimetype {declared}", 0)
            if "_rels/.rels" in names:
                return _opc_identity(archive, names)
    except (zipfile.BadZipFile, ElementTree.ParseError, RuntimeError, OSError, KeyError):
        return None
    return None


def _opc_identity(archive: zipfile.ZipFile, names: set[str]) -> RankedGuess | None:
    rels = ElementTree.fromstring(_bounded(archive, "_rels/.rels"))  # noqa: S314 -- DTD refused
    target = next(
        (rel.get("Target", "") for rel in rels if rel.get("Type", "") in _OPC_RELATIONSHIP),
        None,
    )
    if not target:
        return None
    part = str(PurePosixPath("/", target.lstrip("/")))
    content_type = ""
    if "[Content_Types].xml" in names:
        types = ElementTree.fromstring(_bounded(archive, "[Content_Types].xml"))  # noqa: S314
        for entry in types:
            tag = entry.tag.rsplit("}", 1)[-1]
            if tag == "Override" and entry.get("PartName", "").lower() == part.lower():
                content_type = entry.get("ContentType", "")
                break
    token = _OPC_MAIN.get(content_type.lower())
    if token is not None:
        return _guess(
            token, "container_identity", f"OPC rel officeDocument -> {part}; {content_type}", 0
        )
    member = part.lstrip("/")
    if member not in names:
        return None
    root = ElementTree.fromstring(_bounded_prefix(archive, member))  # noqa: S314
    local = root.tag.rsplit("}", 1)[-1]
    token = _OPC_ROOT.get(local)
    if token is None:
        return None
    return _guess(token, "container_identity", f"OPC rel officeDocument -> {part}; root {local}", 0)


def _bounded_prefix(archive: zipfile.ZipFile, name: str) -> bytes:
    """A main part's root element only: its first `MAX_IDENTITY_BYTES`, closed off after the root
    start tag so a large `document.xml` is not read whole to learn its first element's name."""
    with archive.open(name) as member:
        body = member.read(MAX_IDENTITY_BYTES)
    if b"<!DOCTYPE" in body or b"<!ENTITY" in body:
        raise DriverError(
            cls=FailureClass.RESOURCE_LIMIT,
            message=f"the main part {name} carries a DTD",
            limit="MAX_IDENTITY_BYTES",
            retry_after_ms=RESOURCE_LIMIT_COOLDOWN_MS,
        )
    match = re.search(rb"<([A-Za-z_][\w.:-]*)(\s[^>]*)?>", _skip_prolog(body))
    if match is None:
        raise ElementTree.ParseError("no root element in the first part bytes")
    start = match.group(0)
    return start if start.endswith(b"/>") else start[:-1] + b"/>"


def _skip_prolog(body: bytes) -> bytes:
    """Drop an XML declaration and comments before the root start tag."""
    return re.sub(rb"<\?.*?\?>|<!--.*?-->", b"", body, flags=re.DOTALL)


def _cfb_identity(path: Path) -> tuple[RankedGuess | None, bool]:
    """05:756-763 over the root storage's children, reading at most `MAX_IDENTITY_BYTES` (D569)."""
    try:
        names = _cfb_root_children(path)
    except (OSError, struct.error, ValueError):
        return None, False
    lowered = {name.lower() for name in names}
    if "encryptedpackage" in lowered:
        return None, True
    if "__properties_version1.0" in lowered and any(n.startswith("__substg1.0_") for n in lowered):
        return _guess(
            "msg", "container_identity", "OLE root: __properties_version1.0 + __substg1.0_", 0
        ), False
    for stream, token in _CFB_STREAMS.items():
        if stream in lowered:
            return _guess(token, "container_identity", f"OLE root stream {stream}", 0), False
    return None, False


def _cfb_root_children(path: Path) -> list[str]:
    """The names of the root storage's children in a compound file: header, FAT, directory."""
    budget = [MAX_IDENTITY_BYTES]
    with path.open("rb") as handle:

        def read_at(offset: int, length: int) -> bytes:
            budget[0] -= length
            if budget[0] < 0:
                raise DriverError(
                    cls=FailureClass.RESOURCE_LIMIT,
                    message="the compound file's directory is past the identity read bound",
                    limit="MAX_IDENTITY_BYTES",
                    retry_after_ms=RESOURCE_LIMIT_COOLDOWN_MS,
                )
            handle.seek(offset)
            body = handle.read(length)
            if len(body) != length:
                raise ValueError("a short read inside the compound file")
            return body

        header = read_at(0, 512)
        shift = struct.unpack_from("<H", header, 0x1E)[0]
        if shift not in {9, 12}:
            raise ValueError(f"sector shift {shift}")
        size = 1 << shift
        per_fat = size // 4
        difat = struct.unpack_from("<109I", header, 0x4C)
        fat_cache: dict[int, tuple[int, ...]] = {}

        def next_sector(sector: int) -> int:
            index = sector // per_fat
            if index >= len(difat) or difat[index] in {_CFB_FREE, _CFB_END}:
                raise ValueError("a directory sector past the header's DIFAT")
            if index not in fat_cache:
                fat_cache[index] = struct.unpack(
                    f"<{per_fat}I", read_at((difat[index] + 1) * size, size)
                )
            return fat_cache[index][sector % per_fat]

        entries: list[bytes] = []
        sector = struct.unpack_from("<I", header, 0x30)[0]
        seen: set[int] = set()
        while sector not in {_CFB_END, _CFB_FREE} and sector not in seen:
            seen.add(sector)
            block = read_at((sector + 1) * size, size)
            entries.extend(block[i : i + _CFB_ENTRY] for i in range(0, size, _CFB_ENTRY))
            sector = next_sector(sector)
    return _children(entries)


def _children(entries: Sequence[bytes]) -> list[str]:
    """Walk the root entry's child red-black tree by its left and right sibling ids."""
    if not entries:
        return []
    root_child = struct.unpack_from("<I", entries[0], 0x4C)[0]
    out: list[str] = []
    stack = [root_child]
    visited: set[int] = set()
    while stack:
        index = stack.pop()
        if index == _CFB_NOSTREAM or index >= len(entries) or index in visited:
            continue
        visited.add(index)
        entry = entries[index]
        length = struct.unpack_from("<H", entry, 0x40)[0]
        if _UTF16_NUL <= length <= _CFB_NAME_BYTES:
            out.append(entry[: length - _UTF16_NUL].decode("utf-16-le", "replace"))
        stack.extend(struct.unpack_from("<2I", entry, 0x44))
    return out


# =============================================================================================
# Step 5: content probes, 05 section 2.3
# =============================================================================================


def _as_text(head: bytes) -> str | None:
    """Row 21: a BOM, or valid UTF-8 with no C0 control but tab, CR and LF. Else `None`."""
    for bom, codec in (
        (b"\xef\xbb\xbf", "utf-8"),
        (b"\xff\xfe", "utf-16-le"),
        (b"\xfe\xff", "utf-16-be"),
    ):
        if head.startswith(bom):
            return head[len(bom) :].decode(codec, "replace")
    try:
        text = head.decode("utf-8")
    except UnicodeDecodeError as error:
        #  HEAD may end mid-character; a clean prefix up to the cut is still text.
        if error.start < len(head) - 3:
            return None
        text = head[: error.start].decode("utf-8")
    if _BINARY.search(text.encode("utf-8")):
        return None
    return text


def _probes(text: str, hint: StreamHint, *, truncated: bool) -> list[RankedGuess]:
    """Every probe of 05:682-691 that fires, at its own confidence. The ranking picks."""
    found: list[tuple[str, float, str]] = []
    head = text[:1024]
    stripped = _COMMENT.sub("", head)
    lead = stripped.lstrip()
    if lead.startswith("{") and '"nbformat"' in text and '"cells"' in text:
        found.append(("ipynb", 0.95, "JSON with nbformat and cells"))
    if "<?xml" in text[:1000] and "xhtml" in text[:1000].lower():
        found.append(("xhtml", 0.90, "<?xml and xhtml in the first 1000 chars"))
    if _SVG.search(stripped):
        found.append(("svg", 0.90, "an svg element in the SVG namespace"))
    doctype = _DOCTYPE_ROOT.search(stripped)
    if lead.startswith("<?xml") or (
        doctype is not None
        and re.search(rf"<{re.escape(doctype.group(1))}[\s>/]", stripped[doctype.end() :])
    ):
        found.append(("xml", 0.85, "<?xml, or a DOCTYPE and its root"))
    if _HTML_START.match(stripped):
        found.append(("html", 0.85, "an html, head or body element first"))
    lines = [
        line
        for line in (text.splitlines()[:-1] if truncated else text.splitlines())
        if line.strip()
    ]
    if len(lines) >= _MIN_JSONL_LINES and all(_is_json_object(line) for line in lines[:8]):
        found.append(("jsonl", 0.80, "each of the first non-blank lines is a JSON object"))
    if lead[:1] in {"{", "["} and _json_prefix(lead, truncated=truncated):
        found.append(("json", 0.75, "HEAD is a prefix of one JSON value"))
    delimited = _delimited(text, truncated=truncated)
    if delimited is not None:
        found.append((delimited, 0.70, "csv.Sniffer over three or more consistent lines"))
    if (hint.extension or "") in _MD_EXTENSIONS and _MD_TOKEN.search(text):
        found.append(("md", 0.65, f"extension {hint.extension} and a markdown token"))
    if not found:
        found.append(("txt", 0.50, "valid text and no other probe fired"))
    return [
        _guess(token, "content_probe", detail, min(len(text), HEAD_BYTES), confidence)
        for token, confidence, detail in found
    ]


def _is_json_object(line: str) -> bool:
    try:
        return isinstance(json.loads(line), dict)
    except ValueError:
        return False


def _json_prefix(text: str, *, truncated: bool) -> bool:
    """Whether `text` is one JSON value, or -- when the file is longer than HEAD -- a prefix."""
    try:
        json.loads(text)
    except json.JSONDecodeError as error:
        if not truncated:
            return False
        return error.pos >= len(text.rstrip()) or error.msg.startswith("Unterminated string")
    return True


def _delimited(text: str, *, truncated: bool) -> str | None:
    """05:689: a newline, `csv.Sniffer`, one of four delimiters, two or more columns on three
    consecutive lines. Tab is `tsv`."""
    if "\n" not in text:
        return None
    lines = text.splitlines()
    if truncated:
        lines = lines[:-1]
    sample = "\n".join(lines[:_SNIFF_LINES])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        return None
    rows = list(csv.reader(lines[:_SNIFF_LINES], dialect))
    run = best = 0
    width: int | None = None
    for row in rows:
        if len(row) >= _MIN_COLUMNS and len(row) == width:
            run += 1
        elif len(row) >= _MIN_COLUMNS:
            run, width = 1, len(row)
        else:
            run, width = 0, None
        best = max(best, run)
    if best < _MIN_ROWS:
        return None
    return "tsv" if dialect.delimiter == "\t" else "csv"
