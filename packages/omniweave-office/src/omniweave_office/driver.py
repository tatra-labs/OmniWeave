"""`parse.office.anydoc` — the office family, decoded once per document across seam S1.

16-roadmap.md:484 is the work item: *"`omniweave-office`: `parse.office.anydoc` over
`firecrawl-anydoc == 0.2.4`, `py.detach` for the decode, one call per document, the **honest** card
(`origin_span = "none"`, `os = {"k": "none"}`), and `vendor/anydoc/` at a recorded SHA with LICENSE
+ NOTICE + `.sha256` + `FORK-TRIGGER.md`"*.

## The honest card, which is the whole point of this driver

Every other first-party parse driver's card is a statement about what its code can do. This one is
a statement about what its dependency **cannot** do, and 03-document-model.md:1561 prints the row:
with neither a source address nor geometry, a block is *"text with a `cite`, at `quote =
NORMALIZED` at best; `verbatim` is unreachable on this path"*. `blocks.py`'s header traces that back
to the eight `Block` variants and their missing address.

That is not a defect being tolerated quietly. It is disclosed three ways before anyone runs a
query: `origin_span = "none"` on the card, `corpus_card.verbatim_fraction` on the corpus, and
`vendor/anydoc/FORK-TRIGGER.md` clause 1 naming the exact upstream change that lifts it. The
alternative -- a driver that re-parsed the OOXML package itself to synthesise an address anydoc
never recorded -- would be claiming INV-10 over an address the *extractor* never saw, which is the
one thing INV-10 is about.

## One call per document, and the seam that call sits on

`to_document(data, format)` is called **exactly once** per unit. 02-architecture.md:149 fixes that
as the S1 contract -- *"omniweave-office only, one call per document, py.detach for the decode"* --
and `vendor/anydoc/python/src/lib.rs:194` is the warrant: the binding wraps the decode in
`py.detach`, releasing the GIL for its duration. That is why `parse.office.anydoc` is the one driver
`[isolation] inproc` names (04:1653) and the only place DR9's five conditions (first-party or
vendored, free, GPU-less, network-less, fuzz-green) are all met.

What `py.detach` does **not** cover is the marshal that follows, and the plan is explicit that this
is the open question rather than a solved one: F2, R-T17, and `rss.gen5000p_peak_bytes` as a fork
trigger rather than a budget (12-performance.md:245). Nothing in this file can fix that; what it can
do is not make it worse, which is why there is one call and not one per part.

## The limits are anydoc's, and this driver does not re-check them

`[limits] max_input_bytes` is refused by the HOST before `INVOKE` (DR20), and `max_xml_depth`,
`max_xml_nodes`, `max_grid_slots`, `max_expansion` and `max_expansion_text_bytes` are enforced
*inside the Rust walk* and surface as `RESOURCE_LIMIT{limit}` (05:797). A Python-side re-check would
be a second ceiling that can disagree with the binding one, which is the defect INV-22 names. What
this file does instead is translate: `limits.classify()` maps anydoc's own name onto omniweave's
vocabulary, and a name this release does not know becomes `OW_SCHEMA_UNKNOWN_KIND` rather than a
silent pass-through (14:505).

Specified in 16-roadmap.md W3.4; 02-architecture.md §2 row 41 and §4 seam S1;
04-driver-system.md §10.1; 05-ingest-and-routing.md §10.2; 14-security.md §2.10.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, ClassVar, Final

import anydoc
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

from omniweave_office.blocks import Walk
from omniweave_office.limits import classify

if TYPE_CHECKING:
    from omniweave_ports.detect import StreamHint
    from omniweave_ports.types import DriverIO, PartSelector, ProbeEnv, Scalar, UnitRef

MEDIA_TYPES: Final[dict[str, tuple[str, str]]] = {
    "application/msword": ("doc", "doc"),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ("docx", "docx"),
    "application/vnd.ms-powerpoint": ("ppt", "ppt"),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (
        "pptx",
        "pptx",
    ),
    "application/vnd.ms-excel": ("xlsx", "xls"),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ("xlsx", "xlsx"),
    "application/vnd.oasis.opendocument.text": ("odt", "odt"),
    "application/vnd.oasis.opendocument.spreadsheet": ("ods", "ods"),
    "application/vnd.oasis.opendocument.presentation": ("odp", "odp"),
    "application/rtf": ("rtf", "rtf"),
    "application/epub+zip": ("epub", "epub"),
    "text/csv": ("csv", "csv"),
}
"""The twelve served media types -> `(anydoc format name, omniweave format token)`.

The twelve are `[capability] formats` verbatim, and `driver.toml` prints them one per line for the
reason 04:2545 gives: `resolve()` filters on `format in capability.formats` before anything else, so
this list is the input to `format_token_for`, to `ow route lint` check 11 and to `V01-17`.

**The two columns are not the same vocabulary and the spreadsheet row is where that shows.**
`application/vnd.ms-excel` is the legacy BIFF format, its omniweave token is `xls`, and anydoc's
name for it is **`xlsx`** -- `format_from_extension("xls") == "xlsx"`, verified against the pinned
wheel. anydoc's `Format` literal is a *parser family*, not a media type: twelve names of which one
(`pdf`) this driver never uses and one (`xlsx`) covers three container generations, while the
legacy reader itself is `src/formats/sheet/xls.rs` and is reached by content. Collapsing the two
columns into one map would either lose the `xls` token that routing matches on or send a legacy
workbook to a name anydoc does not accept.

`application/pdf` is absent although anydoc decodes it: `parse.pdf.pdfium` owns the PDF path and
`decode.office-native`'s own comment reads "minus pdf" (04:2564). anydoc agrees from its side --
`to_document()` refuses PDF outright with "PDF converts directly to Markdown" -- so the exclusion is
enforced at both ends rather than by this table alone."""

_ZIP_MAGIC: Final = b"PK\x03\x04"
_CFB_MAGIC: Final = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_SPREADSHEET: Final = "xlsx"
_SHEET_BY_CONTAINER: Final[dict[bytes, str]] = {
    _ZIP_MAGIC: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    _CFB_MAGIC: "application/vnd.ms-excel",
}

_BY_ANYDOC_NAME: Final[dict[str, str]] = {
    name: media for media, (name, _token) in MEDIA_TYPES.items() if name != _SPREADSHEET
}
"""anydoc's name -> the one media type it can only mean. The spreadsheet family is excluded
deliberately: it is the one name that maps to two media types, and `_sheet_media_type()` is where
that ambiguity is resolved by the container signature rather than guessed here."""

PART: Final = "office/source"
"""The one part's path, and it carries no extension on purpose.

A part path is a name the fragment and the store agree on, not a filename; twelve formats through
one code path would otherwise need twelve part names for no reader's benefit. `retain` is **false**:
`[store] retain_parts = "when_citable"` retains a part so a citation can be re-proved, and with
`origin_span = "none"` there is nothing this driver could ever re-prove from it (F32, 16:1177).
Retaining it would roughly double corpus storage on a claim nothing backs."""

_HEAD_WINDOW: Final = 65_536
_NAMED_CONFIDENCE: Final = 0.95
_UNNAMED_CONFIDENCE: Final = 0.6
_CSV_CONFIDENCE: Final = 0.5
_CSV_SUFFIXES: Final = (".csv",)
_DEFAULT_MAX_ASSET_BYTES: Final = 33_554_432
_PAGE: Final = 0
_RESOURCE_LIMIT_COOLDOWN_MS: Final = 60_000

ACHIEVED_CONSTANTS: Final[dict[str, object]] = {
    "spatial": "none",
    "origin_span": "none",
    "text_span": False,
    "reading_order": "source",
    "confidence": "none",
    "furniture": "destroyed",
    "round_trip": "structure",
    "forfeits": [],
}
"""The eight of the fifteen that are the same on every document this driver will ever read.

`spatial` and `origin_span` are `none` because the eight `Block` variants carry neither.
`reading_order = "source"` is the top rung of `raster < learned < model_emitted < char_stream <
source` and it is the honest one: anydoc walks `w:body` / `office:text` / the slide list in the
source's own declared order, so there is no reordering step to get right and none to get wrong.
`furniture = "destroyed"` is verified rather than assumed -- anydoc reads no `w:hdr`/`w:ftr` part at
all and explicitly skips PPTX `hdr`/`ftr`/`sldNum`/`dt` placeholders
(`vendor/anydoc/src/formats/pptx/mod.rs:198,392`) -- which is 03:1036's first rung, "the header text
is gone". `round_trip = "structure"` and `reading_order` are the two keys 03:535 says `achieved`
cannot independently check; they are the declaration, and the conform `capability` suite is what
tests them.

The other seven are computed per document by `_achieved()`, because they are observations about one
document rather than properties of this code."""


class AnydocParser:
    """The office family: DOCX, ODF, legacy binary, RTF, EPUB and CSV, in one call per document."""

    PORT: ClassVar[str] = "parse/1"
    SCHEMA_VERSION: ClassVar[int] = 1

    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict:
        """The wheel is the whole dependency, so the only question is whether it imported.

        `detail` names the version rather than saying "ok", because the version *is* the decoder:
        anydoc's constants are compile-time (14:490) and its `Block` variant set is what the card's
        `origin_span` is honest about, so "which anydoc" is the first thing a reader needs when a
        document decodes differently than it did last week.

        There is no `DEGRADED` state. A partially working `abi3` wheel is not a thing that happens:
        either the extension module loaded and every entry point is present, or the import failed.
        """
        del env
        try:
            version = anydoc.__version__ if hasattr(anydoc, "__version__") else _installed()
        except Exception as exc:  # a broken wheel is UNAVAILABLE, not a crash at import time.
            return ProbeVerdict(
                status=ProbeStatus.UNAVAILABLE,
                detail=f"firecrawl-anydoc present but unusable: {type(exc).__name__}: {exc}",
                missing=("firecrawl-anydoc",),
                fix_hint="uv pip install --force-reinstall 'firecrawl-anydoc==0.2.4'",
            )
        return ProbeVerdict(status=ProbeStatus.OK, detail=f"firecrawl-anydoc {version}")

    def __init__(self, **config: Scalar) -> None:
        """STATIC CONFIG ONLY: no file is opened, no document is parsed, no wheel is probed.

        `max_asset_bytes` is the one knob and it is a CLAMP DOWN, never a widening: an asset anydoc
        retained above it is dropped from `produced` with a `diag`, the block that referenced it
        keeps its `label` and loses its `block_asset` link. INV-22's direction is the whole design
        of the key -- anydoc's own `max_asset_total_bytes` is 128 MiB and compiled in, so this
        cannot raise the ceiling and does not pretend to. It exists because a corpus of
        image-heavy decks can spend its whole output budget on pictures nobody asked for, and
        `ArtifactRef.of()` would then refuse the document rather than the picture.
        """
        raw = config.get("max_asset_bytes", _DEFAULT_MAX_ASSET_BYTES)
        self.max_asset_bytes = int(raw)  # type: ignore[arg-type]
        if self.max_asset_bytes < 0:
            raise DriverError(
                cls=FailureClass.DRIVER_BUG,
                message=f"max_asset_bytes={self.max_asset_bytes}; a byte count is not negative",
            )

    def sniff(self, head: bytes, hint: StreamHint) -> tuple[FormatGuess, ...]:
        """anydoc's own content detector, plus the one thing it structurally cannot answer.

        `format_from_bytes` reads "the signature and identity each container specification
        designates (PDF header, RTF open group, OLE stream names, ZIP package mimetype/content
        types)" -- a real identity read, not an extension guess, which is why its answer outranks
        the filename here rather than the other way round.

        Two cases it cannot answer and this method must:

        - **CSV has no signature.** anydoc returns `None` and says so in its own docstring:
          "Plain-text formats (CSV) carry no signature". The only available evidence is the name,
          so a `.csv` extension yields a deliberately low-confidence guess and anything else yields
          nothing. A driver that sniffed CSV from content would be claiming every comma-separated
          log file in a corpus.
        - **`xlsx` is a parser family, not a media type.** It covers OOXML, BIFF and XLSB alike, so
          the media type comes from the container signature: `PK\\x03\\x04` is the OOXML package,
          `D0CF11E0` is the legacy compound file. Neither is a heuristic -- they are the two
          container formats' own magic numbers.

        Advances nothing, allocates nothing, and returns `()` -- a legitimate "not mine" -- rather
        than a low-confidence guess for a format it has no evidence for.
        """
        detected = anydoc.format_from_bytes(head)
        name = (hint.filename or "").lower()
        if detected is None:
            if not name.endswith(_CSV_SUFFIXES):
                return ()
            return (
                FormatGuess(
                    media_type="text/csv",
                    format_token="csv",  # noqa: S106 -- a format token, not a secret.
                    confidence=_CSV_CONFIDENCE,
                    consumed_bytes=len(head),
                ),
            )
        media_type = (
            _sheet_media_type(head) if detected == _SPREADSHEET else _BY_ANYDOC_NAME.get(detected)
        )
        if media_type is None:  # `pdf`, which parse.pdf.pdfium owns.
            return ()
        token = MEDIA_TYPES[media_type][1]
        confidence = _NAMED_CONFIDENCE if name.endswith(f".{token}") else _UNNAMED_CONFIDENCE
        return (
            FormatGuess(
                media_type=media_type,
                format_token=token,
                confidence=confidence,
                consumed_bytes=len(head),
            ),
        )

    def parse(self, unit: UnitRef, parts: PartSelector, io: DriverIO) -> DriverResult:
        """One `to_document` call, then `owdoc-fragment/1` over what it returned.

        NO `max_input_bytes` CHECK: the host refused the unit before `INVOKE` (DR20). NO
        `max_output_bytes` check either: `ArtifactRef.of()` meters it once, across the fragment and
        every asset together, and raises `TOO_LARGE` naming the knob.

        Raises:
            DriverError: `UNSUPPORTED_FORMAT` for bytes anydoc does not recognise; `ENCRYPTED` for
                a password-protected document; `CORRUPT_INPUT` for one structurally unusable or
                missing a required part; `RESOURCE_LIMIT` carrying anydoc's own limit name;
                `NEEDS_OCR` -- which anydoc raises only for PDFs and this driver therefore never
                expects -- and `TIMEOUT` when cancelled, whose `retry_after_ms` is REQUIRED because
                the class is transient.
        """
        del parts
        with io.blobs.open(unit.content_sha256) as handle:
            raw = handle.read()

        media_type = unit.media_type or _detected_media_type(raw)
        document = self._decode(raw, media_type)
        walk = Walk(PART)
        body = self._emit(walk, document, io)
        assets, dropped = self._asset_refs(document.assets, body, io)
        records = [
            {
                "t": "doc",
                "format": MEDIA_TYPES.get(media_type or "", ("", ""))[1] or "",
                "media_type": media_type,
                "page_count": 1,
                "achieved": _achieved(walk),
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
            *dropped,
            {"t": "end", "status": "ok", "page_stats": {str(_PAGE): {"blocks": _count(body)}}},
        ]
        payload = "".join(
            json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n"
            for record in records
        ).encode("utf-8")
        fragment = ArtifactRef.of("doc_fragment", payload, io)
        return DriverResult(
            outcome="ok",
            produced=(fragment, *assets),
            metrics=DriverMetrics(bytes_read=len(raw)),
        )

    def _emit(self, walk: Walk, document: Any, io: DriverIO) -> list[dict[str, Any]]:
        """Drain the walk, checking cancellation at every loop top and reporting progress.

        **This is the loop, and it is worth saying where it is.** The FFI call is one call and
        cannot be interrupted -- `py.detach` releases the GIL but anydoc has no cancellation
        channel -- so the decode is atomic from the host's side and `wall_ms_hard` is what bounds
        it. What IS interruptible is everything after: the walk over the returned model, which on a
        5,000-block document is the part that takes time in Python. 04-driver-system.md:1738 says
        `io.cancelled()` is checked "at every loop top", and this is the only loop this driver has.

        Progress is reported per TOP-LEVEL block rather than per record, so `done` and `total` are
        commensurable -- `total` is `len(document.blocks)`, the number anydoc returned -- and so a
        deep table does not emit a thousand `PROGRESS` frames for one row of the document. A flood
        would be safe (`wall_ms_hard` does not reset, 04 section 6.5) and still wrong: progress a
        reader cannot interpret is noise.
        """
        total = len(document.blocks)
        done = 0
        body: list[dict[str, Any]] = []
        for record in walk.records(document):
            if io.cancelled():  # CHECK AT EVERY LOOP TOP
                raise DriverError(
                    cls=FailureClass.TIMEOUT,
                    message=f"cancelled by generation after {done} of {total} top-level blocks",
                    retry_after_ms=0,
                )
            body.append(record)
            if record.get("t") == "block" and record.get("parent") is None:
                done += 1
                io.progress(done=done, total=total)
        return body

    def _decode(self, raw: bytes, media_type: str | None) -> Any:
        """THE one FFI call, and the five refusals it can come back with.

        The format is NAMED when the unit's media type names one, because CSV cannot be detected
        from content by anyone -- anydoc's own docstring says so, "Plain-text formats (CSV) carry
        no signature" -- and routing already decided the format before `INVOKE`. When the host
        supplies no media type the call falls back to anydoc's content detection, which reads
        eleven of the twelve and is the same detector `sniff()` uses; CSV is the one that then
        refuses, with the decoder's own message naming the remedy.

        Each refusal maps to the `FailureClass` that means it, and the mapping is deliberately
        narrow: `UnsupportedError` is `UNSUPPORTED_FORMAT` and not `CORRUPT_INPUT`, because anydoc
        raises it both for "this is not a document" and for a container so damaged that detection
        itself failed -- and a truncated DOCX is genuinely indistinguishable from a foreign file at
        that point (verified: `truncated--errors.docx` raises `UnsupportedError`, not
        `MalformedError`). Claiming to know which would be inventing a distinction the decoder did
        not make.
        """
        name = MEDIA_TYPES.get(media_type or "", (None, None))[0]
        try:
            return anydoc.to_document(raw, name)
        except anydoc.ResourceLimitError as exc:
            raise DriverError(
                cls=FailureClass.RESOURCE_LIMIT,
                message=f"anydoc refused this document: {exc}",
                limit=classify(getattr(exc, "limit", None)),
                # `RESOURCE_LIMIT` is TRANSIENT and so `retry_after_ms` is required, which is
                # 08-runtime.md:568's row -- transient, 60,000 ms, and `adapt_batch` halving the
                # batch. 02-architecture.md:1017 says the opposite for the same class
                # (`failed_permanent`, no retry, no cooldown); `_plan/_notes/build-defects.md` D125
                # records the contradiction, and `omniweave_ports` already resolved it in 08's
                # favour, so this is the number the constructor will accept.
                #
                # It is a cooldown, NOT a prediction. Halving a batch helps when the pressure is
                # memory across several units; it changes nothing here, because every limit this
                # driver can hit is compiled into anydoc and the document is unchanged on the
                # retry. The runtime's ladder gets one attempt and then a permanent failure, which
                # is the correct amount of hope to spend on a 400-deep XML document.
                retry_after_ms=_RESOURCE_LIMIT_COOLDOWN_MS,
            ) from None
        except anydoc.EncryptedError as exc:
            raise DriverError(
                cls=FailureClass.ENCRYPTED,
                message=f"anydoc will not open this document: {exc}",
            ) from None
        except anydoc.NeedsOcrError as exc:
            raise DriverError(
                cls=FailureClass.NEEDS_OCR,
                message=f"anydoc reports {len(exc.pages)} page(s) need OCR: {exc}",
                pages=tuple(int(page) for page in exc.pages),
            ) from None
        except anydoc.UnsupportedError as exc:
            raise DriverError(
                cls=FailureClass.UNSUPPORTED_FORMAT,
                message=f"anydoc does not recognise these bytes: {exc}",
            ) from None
        except (anydoc.MalformedError, anydoc.MissingPartError) as exc:
            part = getattr(exc, "part", None)
            where = f" at {part}" if part else ""
            raise DriverError(
                cls=FailureClass.CORRUPT_INPUT,
                message=f"anydoc could not read this document{where}: {exc}",
            ) from None
        except anydoc.ConvertError as exc:
            raise DriverError(
                cls=FailureClass.CORRUPT_INPUT,
                message=f"anydoc failed the conversion: {type(exc).__name__}: {exc}",
            ) from None
        except OSError as exc:  # the stubs' documented non-ConvertError case.
            raise DriverError(
                cls=FailureClass.CORRUPT_INPUT,
                message=f"{type(exc).__name__} reading the document: {exc}",
            ) from None

    def _asset_refs(
        self, assets: Any, body: list[dict[str, Any]], io: DriverIO
    ) -> tuple[tuple[ArtifactRef, ...], list[dict[str, Any]]]:
        """Asset bytes out through `ArtifactRef.of`, in the same order as the `asset` records.

        Order is the pairing, and the `asset` record's `byte_len` is the cross-check on it -- the
        same relationship 03:2130 describes between a driver's claimed digest and the one
        `add_asset` computes: the driver's number is evidence, the host's read is the fact.

        An asset over `max_asset_bytes` is DROPPED rather than refused, with a `diag` naming it and
        the `asset` record removed from the stream. Refusing the document would make one oversized
        logo cost a whole deck; dropping it silently would leave a `picture` block pointing at
        bytes that never arrive.
        """
        refs: list[ArtifactRef] = []
        diags: list[dict[str, Any]] = []
        records = [r for r in body if r.get("t") == "asset"]
        for asset, record in zip(assets, records, strict=True):
            if len(asset.data) > self.max_asset_bytes:
                body.remove(record)
                _unlink(body, str(record["tmp"]))
                diags.append(
                    {
                        "t": "diag",
                        "code": "OW_OFFICE_ASSET_DROPPED",
                        "severity": "warning",
                        "component": "parse.office.anydoc",
                        "message": (
                            f"{asset.origin_part or asset.media_type} is "
                            f"{len(asset.data)} bytes, over this driver's max_asset_bytes of "
                            f"{self.max_asset_bytes}; the picture block keeps its alt text"
                        ),
                        "page": _PAGE,
                        "part": PART,
                        "detail": {"byte_len": len(asset.data), "limit": "max_asset_bytes"},
                        "fatal": False,
                    }
                )
                continue
            refs.append(ArtifactRef.of("asset", bytes(asset.data), io))
        return tuple(refs), diags

    def is_valid_nonempty(self, ref: ArtifactRef) -> bool:
        """The host calls this BEFORE caching, and an empty office document is a real thing.

        An `ok` that fails here becomes `FAILED_PERMANENT(EMPTY_RESULT)`, so an empty success is
        never memoised and never served from cache forever. A DOCX whose body is one empty
        paragraph decodes to zero blocks, which is a legitimate answer about that document and a
        useless thing to have cached as a parse.
        """
        return b'"t":"block"' in ref.head(_HEAD_WINDOW)


def _installed() -> str:
    """anydoc's version, read from installed metadata rather than from a constant here.

    `anydoc` exposes no `__version__`, and a hard-coded string in this file would be a second home
    for a fact `pyproject.toml` already pins -- the defect INV-21 names. `importlib.metadata` is
    the stdlib reader for it and is not `importlib.import_module`, which semgrep bans in a driver.
    """
    from importlib.metadata import version  # noqa: PLC0415 -- read lazily; see above.

    return version("firecrawl-anydoc")


def _detected_media_type(raw: bytes) -> str | None:
    """The media type when the host supplied none: anydoc's content detector, spelled out.

    A host always routes before `INVOKE`, so this is the path a *kit* run and a direct caller
    take. It exists so those two are not strictly harder than a real invocation -- and it reads
    eleven of the twelve, because the twelfth is CSV, which has no signature for anyone to read.
    """
    detected = anydoc.format_from_bytes(raw)
    if detected is None:
        return None
    if detected == _SPREADSHEET:
        return _sheet_media_type(raw)
    return _BY_ANYDOC_NAME.get(detected)


def _sheet_media_type(head: bytes) -> str | None:
    """OOXML workbook or legacy BIFF, decided by the container's own magic number."""
    for magic, media_type in _SHEET_BY_CONTAINER.items():
        if head.startswith(magic):
            return media_type
    return None


def _page_record() -> dict[str, Any]:
    """One `page` row of kind `stream`, which is what an office document actually is.

    `PageKind.STREAM` exists for exactly this: "`w_mpt` / `h_mpt` are NULL when the kind is
    `stream`". A DOCX has no page boxes -- pagination is a rendering of it, performed by a layout
    engine this framework does not run -- and a PPTX's slides are flattened by anydoc into one
    block stream with no slide boundary in the model. Emitting `page_kind = "slide"` with a made-up
    box, or emitting no page at all, would each be a claim: the first that geometry exists, the
    second that the blocks belong to nothing.

    `quad_origin`, `quad_unit` and `quad_dpi` are null together. A frame with no geometry in it has
    no origin corner, and recording them as null rather than omitting them is what lets a reader
    tell "not applicable" from "not recorded" -- ledger D120's point, arrived at from the other
    side.
    """
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
        "method": "native_xml",
    }


def _achieved(walk: Walk) -> dict[str, object]:
    """The fifteen, seven of them computed from what this document actually produced.

    P15 asks that `achieved <= declared` on every key, on every fixture, and a constant `achieved`
    equal to the card would satisfy it trivially and say nothing. 03 §2.9 gives the rollup the
    STORE computes from the committed rows; these seven are that same algorithm applied to the
    records the walk just wrote, so a CSV honestly reports `math = []` and `assets = "none"` while
    the card keeps the higher declaration that routing filters on.

    `tables` is 03:527 verbatim -- "`none` if no `table` block; `cells_with_spans` if any `cell`
    has a span > 1; `cells` otherwise" -- and it is the one key where a document's own shape, not
    the driver's capability, picks the rung.
    """
    tables = "none"
    if walk.tables:
        tables = "cells_with_spans" if walk.has_spans else "cells"
    return {
        **ACHIEVED_CONSTANTS,
        "marks": walk.has_marks,
        "sections": "outline_from_source" if walk.headings else "none",
        "tables": tables,
        "math": sorted(walk.notations),
        "assets": "bytes" if walk.assets else "none",
        "asset_origin": walk.asset_origins > 0,
        "notes": walk.notes_rung,
    }


def _unlink(body: list[dict[str, Any]], tmp: str) -> None:
    """Drop every `block_asset` link to a dropped asset, leaving the block itself alone."""
    for record in body:
        links = record.get("assets")
        if not links:
            continue
        kept = [link for link in links if link.get("tmp") != tmp]
        record["assets"] = kept or None


def _count(body: list[dict[str, Any]]) -> int:
    return sum(1 for record in body if record.get("t") == "block")
