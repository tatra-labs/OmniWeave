"""`omniweave_vision` — the card, the prompt, the pre-filter and the driver.

The card is the artefact this cell exists for: six `ow route lint` checks deferred on
`parse.page.olmocr` before it and none of them does now, and section 10's **2,732** reserved micros
comes out of it rather than out of a fixture. Those two facts are measured in
`packages/omniweave/tests/unit/test_ow_route.py` and `test_route_checks.py`, where the linter is;
what is measured here is that the card says what this code does.

The driver is exercised against a fake `DriverIO` and a fake `ServiceHandle`, which is not a
compromise: the model is a Service, `ServiceHandle` is a Protocol with a `post()`, and a test that
stood up a 7B VLM would be testing vLLM. 11-repo-layout.md:1660 puts the real thing in the nightly
`ow-gpu-1` cell, *"the only cell where `omniweave-vision` is installed"*.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from omniweave_core.drivers.card import load_card
from omniweave_ports.types import DriverError, DriverIO, FailureClass, ProbeStatus
from omniweave_vision import prefilter as pf
from omniweave_vision import prompt as pr
from omniweave_vision.driver import ACHIEVED, WEIGHTS, OlmocrParser, unpinned_weights

if TYPE_CHECKING:
    from collections.abc import Mapping

PKG = Path(__file__).resolve().parents[2] / "src" / "omniweave_vision"
CARD_PATH = PKG / "driver.toml"


@pytest.fixture(scope="module")
def card() -> Any:
    return load_card(CARD_PATH.read_bytes(), origin="project", source=str(CARD_PATH))


@pytest.fixture(scope="module")
def raw() -> Mapping[str, Any]:
    return tomllib.loads(CARD_PATH.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------------------------
# 1. The card.
# --------------------------------------------------------------------------------------------


def test_the_card_loads_with_no_degradation(card: Any) -> None:
    """A `CARD_CAPABILITY_UNKNOWN` here would be a key the loader ignored, and an ignored key on a
    floor table is a driver that looks less capable than its author meant."""
    assert card.identity.id == "parse.page.olmocr"
    assert card.identity.port.value == "parse"
    assert card.identity.port_major == 1
    assert card.degradations == ()


def test_the_cost_model_is_the_fence_section_6_3_prints(card: Any) -> None:
    """05:2446-2457 prints `[cost.model]` for THIS driver. Every number is that fence."""
    model = card.cost_model
    assert model.cost_class.value == "local_compute"
    assert model.shape == "linear_per_part"
    assert model.unit == "part"
    assert dict(model.per_part) == {
        "gpu_ms": 2400.0,
        "cpu_ms": 120.0,
        "tokens_in": 1800.0,
        "tokens_out": 1100.0,
        "calls": 1.0,
    }
    assert dict(model.per_session) == {"wall_ms": 31_000.0}
    assert model.scaling is not None
    assert (model.scaling.key, model.scaling.exponent, model.scaling.reference) == (
        "render.short_edge_px",
        2.0,
        1384.0,
    )
    assert model.tokens_out_p95_multiple == 3.2
    assert model.max_retries == 0


def test_the_cost_model_does_not_carry_the_service_key_the_plan_prints(
    raw: Mapping[str, Any],
) -> None:
    """D228. 05:2456 prints `service = "model:olmocr"` inside `[cost.model]`, and the loader's key
    set for that table is closed at eight without it (`card.py:2538-2549`), so the plan's own
    worked fence for this driver does not load. The name is declared once, in `[hardware]`."""
    assert "service" not in raw["cost"]["model"]
    assert raw["hardware"]["services"] == ["model:olmocr"]


def test_the_card_declares_no_weights_table_and_the_reason_is_in_the_file(
    card: Any, raw: Mapping[str, Any]
) -> None:
    """D227. `[licence.weights]` present REQUIRES an exact sha (04:1858) and this checkout has
    never contacted the weights repository; 04:1857 makes absence the statement "ships no weights",
    which is true of a driver whose model is loaded by a Service from `[services.*]`."""
    assert "weights" not in raw["licence"]
    assert card.licence_weights is None
    assert card.licence_code.spdx == "Apache-2.0"
    assert card.licence_code.competitor_bar is False
    assert card.licence_code.remote_kill_switch is False


def test_the_served_tokens_are_exactly_what_the_shipped_rules_ask_for(card: Any) -> None:
    """`decode.raster-image` names six image tokens (05:1497) and three PDF rules reach this
    driver from `pdf`. `ow route lint` check 11 compares both directions and finds neither
    surplus nor shortfall."""
    assert sorted(one.token for one in card.parse.format_tokens) == [
        "bmp",
        "gif",
        "jpeg",
        "pdf",
        "png",
        "tiff",
        "webp",
    ]


def test_the_hardware_table_does_not_demand_a_local_gpu(card: Any) -> None:
    """The weights are the SERVICE's. `resolve()` gates `gpu = "required"` on the local host's
    `ProbeEnv.gpu_present` and `vram_gb_min` on the local host's VRAM, so either would reject this
    driver on every deployment whose engine is a remote attach -- which 08 section 3.2's ladder
    exists to support."""
    assert card.hardware.gpu == "optional"
    assert card.hardware.vram_gb_min == 0.0
    assert card.hardware.services == ("model:olmocr",)


def test_the_card_says_this_driver_does_not_import_torch_and_the_file_agrees() -> None:
    """`[hardware] imports_torch = false` is checkable by reading the source, and this is the
    check. The distribution depends on torch for the engine the Service spawns; the driver is an
    HTTP client through `ServiceHandle.post()`."""
    source = (PKG / "driver.py").read_text(encoding="utf-8")
    for banned in ("import torch", "import transformers", "from torch", "from transformers"):
        assert banned not in source, f"driver.py imports {banned!r}"


def test_achieved_matches_the_fifteen_the_card_declares(card: Any, raw: Mapping[str, Any]) -> None:
    """`achieved` may be LOWER than `declared` and never higher; here they are equal, because this
    driver's output shape does not vary by document."""
    declared = {
        key: value for key, value in raw["capability"]["parse"].items() if key != "format_tokens"
    }
    assert set(declared) == set(ACHIEVED)
    assert declared == ACHIEVED
    assert card.parse.spatial == "page_bbox"
    assert card.parse.origin_span == "none"
    assert card.parse.reading_order == "model_emitted"


# --------------------------------------------------------------------------------------------
# 2. The prompt.
# --------------------------------------------------------------------------------------------


def test_the_prompt_is_olmocrs_unanchored_builder_verbatim() -> None:
    """`_collections/olmocr/olmocr/prompts/prompts.py:156-163`. The upstream spelling `LateX` is
    preserved: the weights were fine-tuned against this string, so a corrected one is a different
    prompt and a different output distribution."""
    assert pr.PAGE_PROMPT.startswith("Attached is one page of a document that you must process.")
    assert "Convert equations to LateX and tables to markdown." in pr.PAGE_PROMPT
    assert "RAW_TEXT_START" not in pr.PAGE_PROMPT
    assert "tables to HTML" not in pr.PAGE_PROMPT
    for key in pr.FRONT_MATTER_KEYS:
        assert key in pr.PAGE_PROMPT


def test_the_front_matter_round_trips_and_leaves_the_body_alone() -> None:
    body = (
        "---\nprimary_language: en\nis_rotation_valid: True\nrotation_correction: 0\n"
        "is_table: False\nis_diagram: True\n---\n# Heading\n\nA paragraph.\n"
    )
    reading = pr.parse_reading(body)
    assert reading.had_front_matter
    assert reading.primary_language == "en"
    assert reading.is_diagram is True
    assert reading.is_table is False
    assert reading.text == "# Heading\n\nA paragraph."
    assert not reading.rotated


def test_a_missing_front_matter_keeps_the_text_rather_than_throwing_it_away() -> None:
    """The front matter is DIAGNOSTIC and the text is the product, so a page whose text arrived is
    not discarded because its header did not. Upstream takes the same disposition
    (`front_matter.py:53`)."""
    reading = pr.parse_reading("Just some text with no header.")
    assert not reading.had_front_matter
    assert reading.text == "Just some text with no header."


def test_a_rotated_page_is_reported_and_not_acted_on() -> None:
    body = "---\nis_rotation_valid: False\nrotation_correction: 90\n---\nsideways\n"
    reading = pr.parse_reading(body)
    assert reading.rotated
    assert reading.rotation_correction == 90


def test_a_rotation_outside_the_four_is_refused() -> None:
    """`PageResponse.__post_init__` refuses it (`prompts.py:77`), and it is the one field a caller
    might act on."""
    with pytest.raises(ValueError, match="rotation_correction"):
        pr.parse_reading("---\nrotation_correction: 45\n---\nx\n")


# --------------------------------------------------------------------------------------------
# 3. The pre-filter.
# --------------------------------------------------------------------------------------------


def test_the_lexicon_is_the_twelve_words_the_plan_counts() -> None:
    """05:2190: *"a 12-word SEO lexicon at threshold 0.004"*, and
    `_collections/olmocr/olmocr/filter/filter.py:34-47` is the list."""
    assert len(pf.SEO_WORDS) == 12
    assert pf.SPAM_THRESHOLD == 0.004
    assert {"download", "ebook", "casino", "ciprofloxacin"} <= pf.SEO_WORDS


def test_an_empty_document_scores_zero_rather_than_dividing_by_it() -> None:
    assert pf.spam_score("") == 0.0
    assert pf.spam_score("   \n\t ") == 0.0


def test_the_score_is_a_number_and_the_threshold_is_a_comparison() -> None:
    """Upstream's `_is_download_spam` returns a boolean and throws the number away; 05:2188 wants
    the number, because `corpus.spam_score` is a registered signal a slice can be sorted by."""
    spammy = pf.verdict("Free ebook download! Download PDF epub mobi now.")
    assert spammy.spam_score > pf.SPAM_THRESHOLD
    assert spammy.is_download_spam
    ordinary = pf.verdict(" ".join(["lorem", "ipsum", "dolor"] * 100))
    assert ordinary.spam_score == 0.0
    assert not ordinary.is_download_spam


def test_a_form_admits_a_lane_and_never_drops_a_document() -> None:
    """05:1411: *"Ours runs always, its verdict ADMITS A LANE"*, and the rule is
    `gate.form-admits-fields` -- `when = { "corpus.is_form" = true }`, `then = { lane = "fields",
    render = "structure" }`. Upstream drops every form by default."""
    assert pf.verdict("anything", is_form=True).admits_fields
    assert not pf.verdict("anything", is_form=False).admits_fields


def test_the_language_is_recorded_and_never_filtered() -> None:
    """`PdfFilter.languages_to_keep` defaults to `[Language.ENGLISH]`, which drops every other
    language in the world. `corpus.lang` is one of `[slice] by`'s four components (05:1276), so
    here it is an accounting dimension."""
    verdict = pf.verdict("Guten Tag.", language="de")
    assert verdict.language == "de"
    assert "de" in verdict.render()


# --------------------------------------------------------------------------------------------
# 4. The driver, against a fake Service.
# --------------------------------------------------------------------------------------------

PAGE = (
    "---\nprimary_language: en\nis_rotation_valid: True\nrotation_correction: 0\n"
    "is_table: False\nis_diagram: False\n---\n# Invoice 41\n\nTotal due: $412.00\n"
)


@dataclass(eq=False)
class FakeHandle:
    """A `ServiceHandle` narrowed to what the driver uses: `model_id`, `name` and `post`.

    `eq=False` keeps the default identity `__hash__`: `FakeIO` is a frozen dataclass and
    `ArtifactRef.of` keys its per-invocation output meter on the `DriverIO` instance, so every
    field of it must hash -- and this one holds a list of what was posted."""

    reply: str = PAGE
    posted: list[bytes] = field(default_factory=list)
    name: str = "vlm"
    model_id: str = "allenai/olmOCR-2-7B-1025-FP8"

    def post(self, path: str, body: bytes, *, headers: Any = None) -> bytes:
        del path, headers
        self.posted.append(body)
        return json.dumps(
            {
                "choices": [{"message": {"content": self.reply}}],
                "usage": {"prompt_tokens": 1800, "completion_tokens": 1100},
            }
        ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class FakeBlobs:
    """FROZEN, because `DriverIO` is frozen and `ArtifactRef.of` keys its output meter on the
    `DriverIO` instance -- so every field of it has to be hashable."""

    data: bytes

    def open(self, digest: str) -> Any:
        del digest
        return BytesIO(self.data)

    def path(self, digest: str) -> str:
        raise NotImplementedError(digest)

    def put(self, data: bytes) -> str:
        raise NotImplementedError(str(len(data)))


@dataclass(frozen=True, slots=True)
class FakeIO(DriverIO):
    """`DriverIO` with the four methods a driver may call, and nothing widened (INV-6).

    A frozen dataclass subclass rather than a hand-written `__init__`: the base is
    `@dataclass(frozen=True, slots=True, weakref_slot=True)` because, in `types.py`'s own words,
    adding a field to it amends the charter -- and a subclass that assigned an attribute would be
    fighting that."""

    handle: FakeHandle = field(default_factory=FakeHandle)
    is_cancelled: bool = False

    def service(self, name: str) -> Any:
        del name
        return self.handle

    def cancelled(self) -> bool:
        return self.is_cancelled

    def log(self, event: str, **fields: Any) -> None:
        del event, fields

    def progress(self, done: int, total: int | None) -> None:
        del done, total


def _io(raster: bytes, handle: FakeHandle, *, cancelled: bool = False) -> FakeIO:
    return FakeIO(
        blobs=FakeBlobs(raster),  # type: ignore[arg-type]
        tmpdir="",
        deadline_ms=60_000,
        max_output_bytes=1 << 20,
        handle=handle,
        is_cancelled=cancelled,
    )


def _unit() -> Any:
    from omniweave_ports.types import UnitRef  # noqa: PLC0415 -- a fixture's own import

    return UnitRef(uri="file:///scan.pdf", part="p1", content_sha256="a" * 64, byte_len=64)


def _selector() -> Any:
    from omniweave_ports.types import PartSelector  # noqa: PLC0415

    return PartSelector()


def _fragment(result: Any) -> list[dict[str, Any]]:
    body = result.produced[0].inline
    return [json.loads(line) for line in body.decode("utf-8").splitlines()]


def test_probe_is_ok_without_looking_for_a_gpu() -> None:
    """A host with no local GPU and a remote engine is a supported deployment, so a probe that read
    `env.gpu_present` would report unavailable for a configuration that works."""
    verdict = OlmocrParser.probe(None)  # type: ignore[arg-type]
    assert verdict.status is ProbeStatus.OK
    assert WEIGHTS in verdict.detail
    assert pr.PROMPT_VERSION in verdict.detail


def test_sniff_returns_nothing_because_this_driver_is_never_reached_by_detection() -> None:
    assert OlmocrParser().sniff(b"\x89PNG\r\n\x1a\n", None) == ()  # type: ignore[arg-type]


def test_config_is_static_and_max_tokens_is_clamped_to_olmocrs_own_ceiling() -> None:
    """olmocr's `MAX_TOKENS = 8000` (`pipeline.py:107`) is a ceiling here rather than a default
    times eight retries."""
    parser = OlmocrParser(max_tokens=99_999, temperature=0.0)
    assert parser.max_tokens == 8000
    assert parser.repetition_penalty == 1.0
    with pytest.raises(DriverError, match="outside"):
        OlmocrParser(temperature=2.0)


def test_one_page_becomes_a_fragment_of_blocks_on_the_pixels_branch() -> None:
    handle = FakeHandle()
    result = OlmocrParser().parse(_unit(), _selector(), _io(b"PNGBYTES", handle))
    assert result.outcome == "ok"
    assert result.metrics.calls == 1
    assert (result.metrics.tokens_in, result.metrics.tokens_out) == (1800, 1100)

    records = _fragment(result)
    kinds = [record["t"] for record in records]
    assert kinds[:3] == ["doc", "part", "page"]
    blocks = [record for record in records if record["t"] == "block"]
    assert [block["kind"] for block in blocks] == ["heading", "paragraph"]
    assert blocks[0]["text"] == "Invoice 41"
    assert all(block["os"] == {"k": "pixels"} for block in blocks)
    assert all(block["quote"] == "reconstructed" for block in blocks)
    assert all(block["method"] == "vlm" for block in blocks)


def test_the_request_carries_the_prompt_the_page_and_the_handles_model() -> None:
    """`model` is the handle's and never a literal: the Service chose the weights from
    `[services.*]`, and a driver naming a model would be the driver choosing one."""
    handle = FakeHandle()
    OlmocrParser().parse(_unit(), _selector(), _io(b"PNGBYTES", handle))
    sent = json.loads(handle.posted[0])
    assert sent["model"] == handle.model_id
    assert sent["temperature"] == 0.0
    assert sent["repetition_penalty"] == 1.0
    content = sent["messages"][0]["content"]
    assert content[0]["text"] == pr.PAGE_PROMPT
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_a_rotated_page_emits_a_diag_and_still_emits_its_blocks() -> None:
    reply = "---\nis_rotation_valid: False\nrotation_correction: 180\n---\nUpside down text\n"
    result = OlmocrParser().parse(_unit(), _selector(), _io(b"PNGBYTES", FakeHandle(reply=reply)))
    records = _fragment(result)
    diags = [record for record in records if record["t"] == "diag"]
    assert [one["code"] for one in diags] == ["OW_PAGE_ROTATED"]
    assert diags[0]["detail"]["rotation_correction"] == 180
    assert any(record["t"] == "block" for record in records)


def test_a_page_the_model_read_as_empty_is_ok_partial_with_a_reason() -> None:
    """`ok_partial` requires `partial_reason` (08 section 1.3's `Outcome` table), and a blank page
    is a real outcome rather than a failure: the render happened and the model had nothing to
    say."""
    blank = "---\nprimary_language: null\nis_rotation_valid: True\nis_table: False\n---\n"
    result = OlmocrParser().parse(_unit(), _selector(), _io(b"PNGBYTES", FakeHandle(reply=blank)))
    assert result.outcome == "ok_partial"
    assert result.partial_reason is not None
    assert not [record for record in _fragment(result) if record["t"] == "block"]


def test_an_empty_raster_is_corrupt_input_rather_than_a_model_call() -> None:
    with pytest.raises(DriverError) as caught:
        OlmocrParser().parse(_unit(), _selector(), _io(b"", FakeHandle()))
    assert caught.value.cls is FailureClass.CORRUPT_INPUT


def test_a_cancelled_generation_raises_before_the_model_call() -> None:
    """A `TIMEOUT` carries `retry_after_ms` because the class is transient, and the check happens
    BEFORE the call so a superseded generation spends no GPU."""
    handle = FakeHandle()
    with pytest.raises(DriverError) as caught:
        OlmocrParser().parse(_unit(), _selector(), _io(b"PNGBYTES", handle, cancelled=True))
    assert caught.value.cls is FailureClass.TIMEOUT
    assert handle.posted == []


def test_a_service_reply_that_is_not_a_chat_completion_is_a_driver_bug() -> None:
    """`DRIVER_HOST`/`DRIVER_BUG` and never a driver_bug attributed to a third party: the Service
    is ours, and a body that is not the shape its own API documents is our mistake."""

    class Broken(FakeHandle):
        def post(self, path: str, body: bytes, *, headers: Any = None) -> bytes:
            del path, body, headers
            return b'{"error": "no model loaded"}'

    with pytest.raises(DriverError) as caught:
        OlmocrParser().parse(_unit(), _selector(), _io(b"PNGBYTES", Broken()))
    assert caught.value.cls is FailureClass.DRIVER_BUG


# --------------------------------------------------------------------------------------------
# 5. The pin.
# --------------------------------------------------------------------------------------------


def test_upstream_pins_no_revision_and_this_records_which_values_are_not_a_pin() -> None:
    """`olmocr/pipeline.py:1214` is a bare repository id with no `revision=` anywhere on the path
    -- the exact hazard 04:688-692 describes for docling. The pin that governs a run is
    `[services.*] model_revision`, and D227 records that it is the only one of the framework's
    four revision sites with no refusal of `"main"`."""
    assert WEIGHTS == "allenai/olmOCR-2-7B-1025-FP8"
    assert unpinned_weights("") != ""
    assert "forbidden framework-wide" in unpinned_weights("main")
    assert unpinned_weights("v2.0") != ""
    assert unpinned_weights("0123456789abcdef0123456789abcdef01234567") == ""
