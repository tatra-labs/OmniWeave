"""`parse.page.olmocr` — one rendered page, one model call, blocks in the model's reading order.

02:267 gives this distribution *"`parse.page.olmocr` and nothing else"*, with *"a `derive.*.vlm`
pass is out of the release-1 ladder"* and *"reaching a model through `io.service("vlm")`"*.
05:841 gives the rung: *"one full-part model call"*, olmocr p50
**2.4 s**, 854 micros at the section 6.2 pricebook.

## This driver imports neither torch nor transformers, and that is the seam working

`ServiceHandle`'s own docstring, from 04 section 1.3, says it is *"NOT a client library, which is
why `omniweave-llm` needs neither torch nor an SDK"* -- and it carries `post()`. So the weights
live in a host-managed Service, the HTTP is the host's, and this module's imports are `base64`,
`json` and three names from `omniweave_ports`. The distribution depends on `torch` and
`transformers` because the ENGINE the Service spawns needs them (11-repo-layout.md:122); the
driver does not, and `[hardware] imports_torch = false` on the card is that fact, checkable by
reading this file.

## What it produces, and why `verbatim` is unreachable

A scan has no character source. 03:1420 gives INV-10's `pixels` branch as *"the polygon is the
address"*, and `MAX_QUOTE_BY_OS_KIND` caps a `pixels` block at `RECONSTRUCTED`, so 00:116's
*"`verbatim` is unreachable by construction"* is a property of the wire format rather than a
promise this code keeps. Every block carries `os = {"k": "pixels"}` — which 03:776 says *"carries
neither a page nor a quad on the wire, and that is not an omission"*, because `os_kind = 'pixels'
IMPLIES quad IS NOT NULL` is a CHECK the host applies against the `quad` column it already holds.

The quad this driver supplies is the **page**, and the card says `spatial = "page_bbox"` for it. A
page VLM emits a linearised reading and no per-block geometry; 03:1559's table row pairs "only a
polygon (OCR, VLM)" with `block_bbox`, which is true of a classic OCR engine and of this driver in
crop mode at `REPAIR`, and not true of it at `PAGE`. D226.

## Retry is the runtime's, and the numbers say why

`max_retries = 0` on the card is a contract: olmocr's own pipeline is `MAX_TOKENS = 8000`
(`olmocr/pipeline.py:107`) times `--max_page_retries 8` (`:1221`) = 64,000 output tokens per page,
fired in parallel at `--max_concurrent_requests 1600` (`:1223`). Here a retry is a `Rung` — `REGEN`
— strictly serial per `(unit_part, lane)` and charged to the same per-part budget, and what binds
first on the shipped pricebook is `[budget.per_part] calls = 3` (05:2498).

Specified in 05-ingest-and-routing.md sections 3.2 and 6.3; scheduled by 16-roadmap.md:608.
"""

from __future__ import annotations

import base64
import json
from typing import TYPE_CHECKING, Any, ClassVar, Final

from omniweave_ports.types import (
    ArtifactRef,
    DriverError,
    DriverMetrics,
    DriverResult,
    FailureClass,
    ProbeStatus,
    ProbeVerdict,
    Scalar,
)

from omniweave_vision.prompt import PAGE_PROMPT, PROMPT_VERSION, PageReading, parse_reading

if TYPE_CHECKING:
    from omniweave_ports.detect import FormatGuess, StreamHint
    from omniweave_ports.types import (
        DriverIO,
        PartSelector,
        ProbeEnv,
        ServiceHandle,
        UnitRef,
    )

__all__ = ["ACHIEVED", "SERVICE", "WEIGHTS", "OlmocrParser", "unpinned_weights"]

ACHIEVED: dict[str, object] = {
    "spatial": "page_bbox",
    "origin_span": "none",
    "text_span": False,
    "marks": False,
    "reading_order": "model_emitted",
    "sections": "markdown_only",
    "tables": "none",
    "math": [],
    "assets": "none",
    "asset_origin": False,
    "notes": "none",
    "confidence": "none",
    "furniture": "destroyed",
    "round_trip": "text",
    "forfeits": [],
}
"""The fifteen keys of `achieved`, exactly as `driver.toml` declares them.

`achieved` may be LOWER than `declared` and never higher, and every row here is the declared one
because this driver's output shape does not vary by document: a page either reads or it does not.
The `capability` suite compares the two key by key on every fixture."""

SERVICE: Final[str] = "vlm"
"""The default `io.service()` name, overridable by `[config] service`.

`vlm` and not `model:olmocr`: the card's `[hardware] services` names the Service's TYPE as the
scheduler sees it, while `io.service(name)` takes the configured instance name whose
`[services.<name>] model_id` and `model_revision` choose the weights (02 row 15 -- choosing a model
is config's job). An operator running two engines names them and points the config here."""

WEIGHTS: Final[str] = "allenai/olmOCR-2-7B-1025-FP8"
"""The repository olmocr's own pipeline defaults to (`olmocr/pipeline.py:1213-1214`), recorded so
that `ow doctor` and a `MeasuredOn` have a name to print.

**With no revision, because upstream pins none.** `pipeline.py:1214` is a bare repository id and
there is no `revision=` anywhere on that path -- which is the exact hazard 04:688-692 describes for
docling and bans framework-wide. The pin that governs a run is `[services.<name>] model_revision`,
which `config.py:771` makes REQUIRED and `semantic`; this constant names WHAT, and that key names
WHICH. D227 records that the config key is the only one of the four revision sites in the framework
with no refusal of `"main"`."""

_ENDPOINT: Final[str] = "/v1/chat/completions"
_MAX_TOKENS: Final[int] = 4096
_TOKENS_CEILING: Final[int] = 8000
_TEMPERATURE: Final[float] = 0.0
_REPETITION_PENALTY: Final[float] = 1.0
_PART: Final[str] = "page/render.png"
_MEDIA: Final[str] = "image/png"
_MIN_BLOCK_CHARS: Final[int] = 1


def unpinned_weights(model_revision: str) -> str:
    """`""` when the revision is an exact sha, else the reason it is not. 13:954's predicate.

    *"`unpinned` is `eval_run`'s bit, set when `MeasuredOn.weights_revision` is not an exact
    SHA"* (13:954), and 13:947's rule is that such a driver *"may not contribute a"* published
    number. The bit belongs to the eval harness; the predicate belongs beside the constant it
    judges, so that one reading of "exact sha" exists rather than two.

    A 40-character lowercase hex string is the shape git and Hugging Face both use. `"main"` is
    named separately because it is the specific value banned framework-wide and a reader deserves
    to be told which rule they tripped rather than a generic shape complaint.
    """
    revision = model_revision.strip()
    if not revision:
        return "no model_revision: [services.*] model_revision is REQUIRED (config.py:771)"
    if revision == "main":
        return "model_revision = 'main' is forbidden framework-wide (04:692, 13-quality.md P-22)"
    if len(revision) != 40 or any(char not in "0123456789abcdef" for char in revision):  # noqa: PLR2004
        return f"model_revision {revision!r} is not a 40-character lowercase sha"
    return ""


def _as_int(value: Scalar, default: int) -> int:
    """A `Scalar` config value as an int. `None` and a non-number take the default.

    Explicit rather than `int(config.get(k, d))`: a `Scalar` is `bool | int | float | str | None`
    and `int(None)` is a `TypeError` at construction time -- inside `__init__`, which 04:2074 says
    *"loads no model and opens no file"* and which a host calls before it has anywhere to attribute
    a crash.
    """
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _as_float(value: Scalar, default: float) -> float:
    """The same, for the two sampler knobs. See `_as_int`."""
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return default
    try:
        return float(value)
    except ValueError:
        return default


class OlmocrParser:
    """A VLM reading of one rendered page, through a host-managed Service."""

    PORT: ClassVar[str] = "parse/1"
    SCHEMA_VERSION: ClassVar[int] = 1

    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict:
        """Available iff this module imported. It does not look for a GPU, and that is deliberate.

        04:115: *"MUST NOT download, spawn or write"*. The question `probe()` answers is whether
        THIS driver can run here. The weights are the Service's and the Service is attach-or-spawn
        (08 section 3.2): a host with no local GPU and a remote engine is a supported deployment, so
        a probe that read `env.gpu_present` would report unavailable for a configuration that
        works. `[hardware] gpu = "optional"` on the card says the same thing to `resolve()`.

        What the driver genuinely cannot do without is the Service, and that is not knowable here:
        `ProbeEnv` carries no service registry, and attaching to find out would be the spawn this
        method may not perform. 05:1237's `PROBE_UNAVAILABLE` case is the DISTRIBUTION being
        absent, which is answered by this method not existing to call.
        """
        del env
        return ProbeVerdict(
            status=ProbeStatus.OK,
            detail=f"{WEIGHTS} via a host-managed Service; prompt {PROMPT_VERSION}",
        )

    def __init__(self, **config: Scalar) -> None:
        """STATIC CONFIG ONLY. 04:2074: *"`__init__` loads no model and opens no file"*.

        `max_tokens` is clamped to olmocr's own `MAX_TOKENS = 8000` rather than accepted above it,
        because a card's `[config]` maximum and a driver that ignored it would be two answers; the
        card declares the same ceiling and `load_card` enforces it on the operator's side.

        `temperature` defaults to 0.0 and `repetition_penalty` to 1.0. The second is 05:2252's own
        instruction -- *"`repetition_penalty` stays 1.0 -- real documents repeat -- so the guard is
        the detector"* -- and the detector is `verify.repeat_ngram_max`, which is a signal rather
        than a sampler setting.
        """
        self.service = str(config.get("service", SERVICE))
        self.max_tokens = min(_as_int(config.get("max_tokens"), _MAX_TOKENS), _TOKENS_CEILING)
        self.temperature = _as_float(config.get("temperature"), _TEMPERATURE)
        self.repetition_penalty = _as_float(config.get("repetition_penalty"), _REPETITION_PENALTY)
        if self.max_tokens < 1:
            raise DriverError(
                cls=FailureClass.DRIVER_BUG,
                message=f"max_tokens={self.max_tokens}; a token budget is positive",
            )
        if not 0.0 <= self.temperature <= 1.0:
            raise DriverError(
                cls=FailureClass.DRIVER_BUG,
                message=f"temperature={self.temperature} is outside [0.0, 1.0]",
            )

    def sniff(self, head: bytes, hint: StreamHint) -> tuple[FormatGuess, ...]:
        """`()`, always, and it is a statement rather than a stub.

        This driver is never reached by detection. It is reached by an escalation rule that already
        knows the format -- `decode.no-text-layer` from `pdf`, `decode.raster-image` from six image
        tokens -- and what it consumes is a RENDER of a part, not the source stream. A guess here
        would put a page VLM in the detection ladder for every PNG on disk, at the top of the
        confidence order, for a driver that cannot answer the question detection asks.
        """
        del head, hint
        return ()

    def parse(self, unit: UnitRef, parts: PartSelector, io: DriverIO) -> DriverResult:
        """One rendered page in, one `owdoc-fragment/1` out.

        The raster is read from the CAS by `unit.content_sha256`: the render step has already run
        and cached it under `cache_index` layer `render`, which is why this driver never renders
        and why `page_renders` stays a set keyed on `(unit_part, profile)` rather than a count of
        model calls (05:2356).

        Raises:
            DriverError: `TIMEOUT` when the generation is superseded, whose `retry_after_ms` is
                required because the class is transient; `DRIVER_BUG` for a response the Service
                returned that is not the shape its own API documents; `CORRUPT_INPUT` for an empty
                raster.
        """
        del parts
        with io.blobs.open(unit.content_sha256) as handle:
            raster = handle.read()
        if not raster:
            raise DriverError(
                cls=FailureClass.CORRUPT_INPUT,
                message=f"{unit.uri}#{unit.part}: the rendered page is zero bytes",
            )
        if io.cancelled():
            raise DriverError(
                cls=FailureClass.TIMEOUT,
                message=f"cancelled before the model call for {unit.uri}#{unit.part}",
                retry_after_ms=0,
            )

        handle_ = io.service(self.service)
        reading, usage = self._read_page(handle_, raster)
        records = list(self._records(unit, reading, len(raster)))
        body = "".join(
            json.dumps(record, separators=(",", ":")) + "\n" for record in records
        ).encode("utf-8")
        ref = ArtifactRef.of("doc_fragment", body, io)
        outcome = "ok" if reading.text else "ok_partial"
        return DriverResult(
            outcome=outcome,  # type: ignore[arg-type]
            produced=(ref,),
            partial_reason=None if reading.text else "the model returned no text for this page",
            metrics=DriverMetrics(
                bytes_read=len(raster),
                calls=1,
                tokens_in=usage[0],
                tokens_out=usage[1],
            ),
        )

    # ----------------------------------------------------------------------------------------
    # The call.
    # ----------------------------------------------------------------------------------------

    def _request(self, handle: ServiceHandle, raster: bytes) -> bytes:
        """The OpenAI-compatible chat body, with the page as a data URL.

        `model` is the handle's `model_id` and never a literal: the Service chose the weights from
        `[services.*]`, and a driver naming a model would be the driver choosing one -- which 02
        row 15 puts outside a driver's business in the same sentence that makes a Service *"named
        and never routed"*.
        """
        data_url = f"data:{_MEDIA};base64,{base64.b64encode(raster).decode('ascii')}"
        return json.dumps(
            {
                "model": handle.model_id,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "repetition_penalty": self.repetition_penalty,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": PAGE_PROMPT},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    }
                ],
            },
            separators=(",", ":"),
        ).encode("utf-8")

    def _read_page(
        self, handle: ServiceHandle, raster: bytes
    ) -> tuple[PageReading, tuple[int, int]]:
        """One POST through the handle, and the reading it returned. No retry, by contract.

        `handle.post()` and not a socket of this driver's own: the host owns the deadline, the
        token and the connection, which is what lets `[hardware] needs_network = false` be true of
        this file and provable by the conform `sandbox` suite.
        """
        raw = handle.post(_ENDPOINT, self._request(handle, raster))
        try:
            payload: Any = json.loads(raw)
            choice = payload["choices"][0]
            content = choice["message"]["content"]
        except (ValueError, LookupError, TypeError) as exc:
            raise DriverError(
                cls=FailureClass.DRIVER_BUG,
                message=(
                    f"the {handle.name!r} Service returned a body that is not an OpenAI chat "
                    f"completion: {type(exc).__name__}: {exc}"
                ),
            ) from exc
        usage = payload.get("usage") or {}
        return parse_reading(str(content)), (
            int(usage.get("prompt_tokens", 0)),
            int(usage.get("completion_tokens", 0)),
        )

    # ----------------------------------------------------------------------------------------
    # The fragment.
    # ----------------------------------------------------------------------------------------

    def _records(self, unit: UnitRef, reading: PageReading, byte_len: int) -> Any:
        """`doc`, `part`, `page`, then one block per non-empty line of the model's markdown.

        One block per LINE and not per paragraph, for a different reason than pdfium's: there the
        line is what makes `verbatim` true by construction, here there is no address to preserve
        and the line is simply the finest split the model's output supports without inventing
        structure. A `#` line becomes a `heading` because `sections = "markdown_only"` is what the
        card declares and markdown is what the prompt asked for.
        """
        yield {
            "t": "doc",
            "format": "page",
            "media_type": _MEDIA,
            "page_count": 1,
            "achieved": ACHIEVED,
        }
        yield {
            "t": "part",
            "path": _PART,
            "sha256": unit.content_sha256,
            "byte_len": byte_len,
            "retain": False,
        }
        yield {
            "t": "page",
            "index": 0,
            "quad_origin": "topleft",
            "quad_unit": "px",
        }
        if reading.rotated:
            yield {
                "t": "diag",
                "code": "OW_PAGE_ROTATED",
                "severity": "warning",
                "component": "parse.page.olmocr",
                "message": "the model reports this page was not upright",
                "page": 0,
                "part": _PART,
                "detail": {"rotation_correction": reading.rotation_correction},
                "fatal": False,
            }
        index = 0
        for line in reading.text.splitlines():
            stripped = line.strip()
            if len(stripped) < _MIN_BLOCK_CHARS:
                continue
            index += 1
            yield self._block(index, stripped)

    @staticmethod
    def _block(index: int, text: str) -> dict[str, Any]:
        """One `block` row on INV-10's `pixels` branch.

        `os` is `{"k": "pixels"}` and nothing else: 03:776 -- *"The `pixels` variant carries neither
        a page nor a quad on the wire, and that is not an omission"* -- because the page and the
        quad are columns the host already holds, and `os_kind = 'pixels' IMPLIES quad IS NOT NULL`
        is a CHECK it applies against them.

        `quote = "reconstructed"` rather than `normalized`: ADR-5 puts `pixels` at `RECONSTRUCTED`
        in `MAX_QUOTE_BY_OS_KIND` (03:3091), and a driver declaring less than its ceiling would
        make the host's clamp unobservable. `trust = "model"` and `method = "vlm"` are what
        `MAX_TRUST_BY_METHOD` reads.
        """
        heading = text.startswith("#")
        return {
            "t": "block",
            "tmp": f"b{index}",
            "parent": None,
            "page": 0,
            "kind": "heading" if heading else "paragraph",
            "layer": "body",
            "text": text.lstrip("# ").strip() if heading else text,
            "quote": "reconstructed",
            "trust": "model",
            "method": "vlm",
            "os": {"k": "pixels"},
            "quad": None,
            "marks": [],
            "payload": None,
        }
