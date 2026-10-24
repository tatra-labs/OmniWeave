"""SubRip subtitles (`.srt`) as one paragraph Block per cue, each with its exact byte span.

An independent driver, written against `omniweave_ports` alone (D967): it shares no code with the
framework's template. A cue is a counter line, a timing line (`00:00:01,000 --> 00:00:02,500`)
and one or more text lines, and cues are separated by blank lines. The counter and the timing are
the file's structure, not its text, so a Block holds a cue's text lines and the span the text came
from, which the host can re-read and verify.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import TYPE_CHECKING, ClassVar

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

if TYPE_CHECKING:
    from omniweave_ports.detect import StreamHint
    from omniweave_ports.types import DriverIO, PartSelector, ProbeEnv, Scalar, UnitRef

MEDIA_TYPE = "application/x-subrip"
SRT = "srt"
PART = "subtitles/cues.srt"

ACHIEVED: dict[str, object] = {
    "spatial": "none",
    "origin_span": "exact",
    "text_span": True,
    "marks": False,
    "reading_order": "source",
    "sections": "none",
    "tables": "none",
    "math": [],
    "assets": "none",
    "asset_origin": False,
    "notes": "none",
    "confidence": "none",
    "furniture": "flagged",
    "round_trip": "text",
    "forfeits": [],
}
"""What a parse achieves, key for key with the card's `[capability.parse]`."""

_TIMING = re.compile(rb"^\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}")
_COUNTER = re.compile(rb"^\s*\d+\s*$")
_LINE = re.compile(rb"[^\r\n]*(?:\r\n|\n|\r|$)")
_BOM = b"\xef\xbb\xbf"


def _lines(raw: bytes) -> list[tuple[int, bytes]]:
    """Every line with its byte offset, the terminator stripped. A final empty match ends it."""
    out: list[tuple[int, bytes]] = []
    for match in _LINE.finditer(raw):
        if match.start() == len(raw) and not match.group():
            break
        out.append((match.start(), match.group().rstrip(b"\r\n")))
    return out


def cues(raw: bytes) -> list[tuple[int, int]]:
    """Each cue's text as a `(start, end)` byte range, in file order.

    Blank lines separate cues. In each group the timing line is found, and the text is every
    line after it; a group with no timing line is text throughout, so a damaged file still says
    what it holds. The range runs from the first text line's first byte to the last text line's
    last byte, so it includes a cue's inner line breaks and nothing around it.
    """
    start = len(_BOM) if raw.startswith(_BOM) else 0
    groups: list[list[tuple[int, bytes]]] = [[]]
    for offset, line in _lines(raw[start:]):
        if line.strip():
            groups[-1].append((offset + start, line))
        elif groups[-1]:
            groups.append([])
    ranges: list[tuple[int, int]] = []
    for group in groups:
        if not group:
            continue
        timed = next((i for i, (_o, line) in enumerate(group) if _TIMING.match(line)), None)
        text = group if timed is None else group[timed + 1 :]
        if timed is None and len(group) == 1 and _COUNTER.match(group[0][1]):
            continue
        if not text:
            continue
        first, last = text[0], text[-1]
        ranges.append((first[0], last[0] + len(last[1])))
    return ranges


class SubRipParser:
    """`parse/1` over SubRip: stdlib only, one retained part, one Block per cue."""

    PORT: ClassVar[str] = "parse/1"
    SCHEMA_VERSION: ClassVar[int] = 1

    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict:
        del env
        return ProbeVerdict(status=ProbeStatus.OK, detail="regular expressions over bytes only")

    def __init__(self, **config: Scalar) -> None:
        if config:
            raise DriverError(
                cls=FailureClass.DRIVER_BUG,
                message=f"this driver takes no configuration, and was given {sorted(config)}",
            )

    def sniff(self, head: bytes, hint: StreamHint) -> tuple[FormatGuess, ...]:
        """A timing line is the format's signature; the `.srt` name alone is a weaker one."""
        if b"\x00" in head:
            return ()
        named = (hint.filename or "").lower().endswith(".srt")
        timed = any(_TIMING.match(line) for line in head.splitlines()[:64])
        if not timed and not named:
            return ()
        confidence = 0.95 if timed and named else 0.7 if timed else 0.3
        return (
            FormatGuess(
                media_type=MEDIA_TYPE,
                format_token=SRT,
                confidence=confidence,
                consumed_bytes=len(head),
            ),
        )

    def parse(self, unit: UnitRef, parts: PartSelector, io: DriverIO) -> DriverResult:
        del parts
        with io.blobs.open(unit.content_sha256) as handle:
            raw = handle.read()
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DriverError(
                cls=FailureClass.CORRUPT_INPUT,
                message=f"SubRip is UTF-8 here, and byte {exc.start} is not",
            ) from None
        records: list[dict[str, object]] = [
            {
                "t": "doc",
                "format": SRT,
                "media_type": MEDIA_TYPE,
                "page_count": 1,
                "achieved": ACHIEVED,
            },
            {
                "t": "part",
                "path": PART,
                "sha256": unit.content_sha256,
                "byte_len": unit.byte_len,
                "retain": True,
            },
            {
                "t": "page",
                "page": 0,
                "page_kind": "stream",
                "w_mpt": None,
                "h_mpt": None,
                "quad_origin": None,
                "rotation": 0,
                "method": "native",
            },
        ]
        count = 0
        for begin, end in cues(raw):
            if io.cancelled():
                raise DriverError(
                    cls=FailureClass.TIMEOUT, message="cancelled by generation", retry_after_ms=0
                )
            count += 1
            records.append(
                {
                    "t": "block",
                    "tmp": f"cue{count}",
                    "parent": None,
                    "kind": "paragraph",
                    "layer": "body",
                    "text": unicodedata.normalize("NFC", raw[begin:end].decode("utf-8")),
                    "quote": "verbatim",
                    "trust": "extracted",
                    "method": "native",
                    "os": {
                        "k": "bytes",
                        "part": PART,
                        "start": begin,
                        "length": end - begin,
                        "codec": "utf-8/strict",
                    },
                    "quad": None,
                    "marks": [],
                    "payload": None,
                }
            )
            io.progress(done=count, total=None)
        records.append({"t": "end", "status": "ok", "page_stats": {"0": {"blocks": count}}})
        body = "".join(json.dumps(one, separators=(",", ":")) + "\n" for one in records)
        return DriverResult(
            outcome="ok",
            produced=(ArtifactRef.of("doc_fragment", body.encode("utf-8"), io),),
            metrics=DriverMetrics(bytes_read=len(raw)),
        )

    def is_valid_nonempty(self, ref: ArtifactRef) -> bool:
        """A file with no cue text is empty, and an empty success is never cached."""
        return b'"t":"block"' in ref.head(65_536)
