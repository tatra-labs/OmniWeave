"""The conformance-template driver: a complete `parse/1` driver, and the kit's own first subject.

18-api-sketch.md:1937-2097 prints this file as "A minimal `parse/1` driver -- the whole file. No
omniweave import but `omniweave_ports`." This is that driver, transcribed, with the six card keys
D110 records corrected and one record field (`page`) corrected against 03-document-model.md:2275.

## What it is for, in three places at once

* **W3.6's deliverable.** 16-roadmap.md:486 lists "the conformance-template driver" beside the
  twelve suites, and it is the thing `ow drivers scaffold` copies out: a new author starts from a
  driver that already passes, and fills their own card upward from there.
* **G16's subject.** 11-repo-layout.md:1133-1136 builds `omniweave-conform` from each of the last
  two tags, "scaffolds the template driver from that checkout's own" build, and loads it against
  HEAD. A contract break is therefore detected against a driver we control, which
  00-vision.md:819 is careful to say is not the same as detecting it against a real external one.
* **The kit's self-test.** Every suite needs a subject that passes, or a green run proves only that
  the suite found nothing to look at. This driver is that subject, and `template/fixtures/` holds
  the inputs it is run over.

## Why plain text, and why `origin_span = "exact"`

18-api-sketch.md:1850-1858 gives the reason and it is about INV-10 rather than about text. The
`capability` suite must prove `origin_span` on all three of INV-10's branches (16-roadmap.md:486),
04 section 9's worked driver proves the `nodepath` branch because a JSON pointer is a stable node
path, and **this one proves the `bytes` branch**, whose predicate has one home at
03-document-model.md section 7.2:

    nfc(part_bytes[os_a : os_a + os_b].decode(*os_codec.split("/", 1))) == block.text

`nfc()`, never `normalize_k` -- the latter casefolds, and would let a block reading `abc` prove
`verbatim` against source bytes reading `ABC`.

## What this driver does NOT do, each because a protocol obligation forbids it

It never touches a store, cache or ledger; never returns `None` or an empty success; never retries;
never writes outside `io.tmpdir`; never sets `confidence`, `restriction_bits` or a price; and never
re-checks a host-enforced limit. Each absence is a suite rather than a review comment, and the
suites that check them are `contract`, `sandbox`, `cost` and `limits`.

Specified in 18-api-sketch.md section 5.2 and 04-driver-system.md section 9.
"""

from __future__ import annotations

import json
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
"""The fifteen keys of `achieved`, exactly as `driver.toml` declares them.

18-api-sketch.md:1950-1952: "The `capability` suite asserts this constant is <= the card's
`[capability.parse]` on every key -- achieved may be lower, never higher -- so the wire and the card
cannot drift apart." Public rather than `_`-private because the `capability` suite reads it: a
constant the suite must compare against is part of this module's surface, and hiding it would only
mean the suite reached for a private name.
"""

PART = "text/body.txt"
"""The one retained part's path. `retain = True`, which is what makes the `bytes` branch provable:
`origin_span = "exact"` is a claim about bytes that must still be there to be re-read."""

_NUL = b"\x00"
_PARAGRAPH_BREAK = "\n\n"
_TXT_SUFFIXES = (".txt", ".text", ".log")
_NAMED_CONFIDENCE = 0.9
_UNNAMED_CONFIDENCE = 0.4
_HEAD_WINDOW = 65_536


class PlainTextParser:
    """Decode a UTF-8 text file into one `paragraph` Block per blank-line-separated run.

    Reaches `quote = "verbatim"` because it records an `OriginBytes` span per Block, which the
    conformance `capability` suite verifies on INV-10's `bytes` branch by re-reading the retained
    part.
    """

    PORT: ClassVar[str] = "parse/1"
    SCHEMA_VERSION: ClassVar[int] = 1

    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict:
        """No binary, no weights, no GPU. Always OK -- and `detail` still NAMES what was checked.

        18-api-sketch.md:1979-1983: a future dependency then has an honest place to report a
        shortfall rather than degrading silently. A `DEGRADED` verdict must additionally fill
        `capabilities_lost` so the router can re-filter, and an `UNAVAILABLE` one must fill
        `missing` and `fix_hint`.
        """
        del env
        return ProbeVerdict(status=ProbeStatus.OK, detail="stdlib codecs only")

    def __init__(self, **config: Scalar) -> None:
        """STATIC CONFIG ONLY: no file is opened and no model is loaded here.

        `errors` selects the codec error policy and is the one knob. The decode and any later
        re-read must use the SAME codec and error policy (decode symmetry), or `Doc.verify_quote()`
        reports `mismatch` on a file that never changed.
        """
        self.errors = str(config.get("errors", "strict"))
        if self.errors not in ("strict", "replace"):
            raise DriverError(
                cls=FailureClass.DRIVER_BUG,
                message=f"errors={self.errors!r}; expected 'strict' or 'replace'",
            )

    def sniff(self, head: bytes, hint: StreamHint) -> tuple[FormatGuess, ...]:
        """MANY-TO-ONE and RANKED. Must NOT advance a stream.

        `head` is immutable `bytes` and the host re-checks the caller's offset afterwards. A NUL
        byte in the first 8 KiB is decisive against text; otherwise confidence follows the
        filename. Returning `()` is a legitimate 'not mine', not a failure.
        """
        if _NUL in head:
            return ()
        name = (hint.filename or "").lower()
        conf = _NAMED_CONFIDENCE if name.endswith(_TXT_SUFFIXES) else _UNNAMED_CONFIDENCE
        return (
            FormatGuess(
                media_type="text/plain",
                format_token="txt",  # noqa: S106 -- a format token, not a secret.
                confidence=conf,
                consumed_bytes=len(head),
            ),
        )

    def parse(self, unit: UnitRef, parts: PartSelector, io: DriverIO) -> DriverResult:
        """Emit `owdoc-fragment/1`. The HOST mints every block_id, addr and cite.

        This driver addresses blocks by a per-invocation `tmp` id only. A `tmp` referenced but
        never defined fails the WHOLE document with `OW_FRAGMENT_DANGLING_TMP`, because a partial
        spine is worse than no document.

        NO `max_input_bytes` CHECK: the host refused the unit before INVOKE, and re-checking a
        host-enforced ceiling is a second implementation of a safety limit. NO `max_output_bytes`
        CHECK either: `ArtifactRef.of()` meters it once and raises `TOO_LARGE` naming the knob.

        Raises:
            DriverError: `CORRUPT_INPUT` for input undecodable under `errors='strict'`; `TIMEOUT`
                when cancelled or past the deadline, whose `retry_after_ms` is REQUIRED because
                the class is transient. `TOO_LARGE` comes from `ArtifactRef.of`, never from here.
        """
        del parts
        with io.blobs.open(unit.content_sha256) as fh:
            raw = fh.read()
        try:
            text = raw.decode("utf-8", errors=self.errors)
        except UnicodeDecodeError as exc:
            raise DriverError(
                cls=FailureClass.CORRUPT_INPUT,
                message=f"utf-8 decode failed at byte {exc.start}",
            ) from None

        out: list[dict[str, object]] = [
            # `format` holds a format TOKEN, never a media type (05 section 2.2); `media_type` is
            # the next key and it is where the media type goes.
            {
                "t": "doc",
                "format": "txt",
                "media_type": "text/plain",
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
            # `page = 0`, not 1. 03-document-model.md:2275: a `stream` page_kind means "there are
            # no pages: HTML, markdown, code, plain text, email. Always `page = 0`", and :2277
            # adds that `page` is never a batch index. 18-api-sketch.md:2047 prints `1` here and
            # is wrong on both counts (ledger D110).
            {
                "t": "page",
                "page": 0,
                "page_kind": "stream",
                "w_mpt": 0,
                "h_mpt": 0,
                "quad_origin": "topleft",
                "rotation": 0,
                "method": "native",
            },
        ]

        # One pass, and the offsets are computed from a running byte cursor rather than from
        # `text.index()`: a duplicated paragraph would make `index()` return the FIRST occurrence
        # and silently point two Blocks at one span, which the `capability` suite catches on the
        # second fixture but which no reader of the code would see.
        cursor_chars = 0
        cursor_bytes = 0
        n = 0
        chunks = text.split(_PARAGRAPH_BREAK)
        for i, chunk in enumerate(chunks):
            if io.cancelled():  # CHECK AT EVERY LOOP TOP
                raise DriverError(
                    cls=FailureClass.TIMEOUT,
                    message="cancelled by generation",
                    retry_after_ms=0,
                )
            lead = len(chunk) - len(chunk.lstrip())
            body = chunk.strip()
            byte_a = cursor_bytes + len(chunk[:lead].encode("utf-8"))
            byte_len = len(body.encode("utf-8"))
            cursor_chars += len(chunk) + (len(_PARAGRAPH_BREAK) if i + 1 < len(chunks) else 0)
            cursor_bytes = len(text[:cursor_chars].encode("utf-8"))
            if not body:
                continue
            n += 1
            out.append(
                {
                    "t": "block",
                    "tmp": f"b{n}",
                    "parent": None,
                    "kind": "paragraph",
                    "layer": "body",
                    "text": unicodedata.normalize("NFC", body),
                    "quote": "verbatim",
                    "trust": "extracted",
                    "method": "native",
                    "os": {
                        "k": "bytes",
                        "part": PART,
                        "start": byte_a,
                        "length": byte_len,
                        "codec": "utf-8",
                    },
                    "quad": None,
                    "marks": [],
                    "payload": None,
                }
            )
            # Resets `progress_ms`; a silent driver is a DIFFERENT deadline from a chatty one.
            io.progress(done=n, total=None)

        out.append({"t": "end", "status": "ok", "page_stats": {"0": {"blocks": n}}})
        body_bytes = "".join(
            json.dumps(record, separators=(",", ":"), sort_keys=False) + "\n" for record in out
        ).encode("utf-8")
        ref = ArtifactRef.of("doc_fragment", body_bytes, io)  # meters max_output_bytes for us
        return DriverResult(
            outcome="ok",
            produced=(ref,),
            metrics=DriverMetrics(bytes_read=len(raw)),
        )

    def is_valid_nonempty(self, ref: ArtifactRef) -> bool:
        """The host calls this BEFORE caching. An `ok` that fails here is `EMPTY_RESULT`.

        So an empty success is never memoised and never served from cache forever. A text file that
        is entirely whitespace is legitimately empty, and this is where that becomes a named
        permanent failure rather than a zero-block document.
        """
        return b'"t":"block"' in ref.head(_HEAD_WINDOW)
