"""The page-query prompt, pinned, and the front matter the model answers with.

16-roadmap.md:1139 draws the line this module sits on: *"We take the weights, the page-query
prompt, `PdfFilter` and the `finished_on_attempt_N` metric shape; we own the client, the pre-filter
and the harness."* The prompt is on the taken side and is transcribed below with its source line;
the parser is on the owned side and is written here.

## Which of olmocr's four prompts, and why it is the unanchored one

`_collections/olmocr/olmocr/prompts/prompts.py` declares four builders. `build_finetuning_prompt`
(`:147`) takes a `base_text` -- an anchor extracted from the PDF's own text layer -- and interleaves
it as `RAW_TEXT_START ... RAW_TEXT_END`. **That is the thing whose absence caused the escalation.**
`decode.no-text-layer` fires on `decode.char_count = 0` and `decode.raster-image` on a PNG; both
reach this driver with no text layer to anchor against, and a prompt that carried an empty anchor
would be a prompt asking the model to reconcile a page against nothing.

So the driver takes `build_no_anchoring_yaml_prompt` (`:156`), which asks for markdown with a front
matter block, and takes it in ONE form for every rung. A prompt that varied by why the driver was
called would give one `schema_version` two output distributions, and `schema_version` is the only
driver version in a cache key.

**Not the v4 variant** (`:164`), and the difference is a card row. v4 asks for *"tables to HTML"*
and for figures labelled `![...](page_startx_starty_width_height.png)`. Both would be claims this
card does not make -- `tables = "none"` and `assets = "none"` -- and a prompt that asks for output
the driver then discards is tokens billed for nothing at `tokens_out x 3.2` reserved.

## The front matter is parsed by hand, and PyYAML is the reason

olmocr parses it with `yaml.safe_load` (`olmocr/train/front_matter.py:48`). A YAML parser for five
scalar keys is a parser for the whole YAML grammar -- aliases, anchors, merge keys, the billion
laughs -- accepting text a model emitted, and 14-security.md refuses that shape elsewhere for the
same reason `[Content_Types].xml` is refused on the `<!DOCTYPE` test. Five `key: value` lines need
five `str.partition` calls, so this file has neither a dependency nor an attack surface.

Specified in 16-roadmap.md section 16; the `verify.*` signals that read the result are 05:2252's.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

__all__ = [
    "FRONT_MATTER_KEYS",
    "PAGE_PROMPT",
    "PROMPT_VERSION",
    "ROTATIONS",
    "PageReading",
    "parse_reading",
]

PAGE_PROMPT: Final[str] = (
    "Attached is one page of a document that you must process. "
    "Just return the plain text representation of this document as if you were reading it "
    "naturally. Convert equations to LateX and tables to markdown.\n"
    "Return your output as markdown, with a front matter section on top specifying values for "
    "the primary_language, is_rotation_valid, rotation_correction, is_table, and is_diagram "
    "parameters."
)
"""`build_no_anchoring_yaml_prompt()`, `_collections/olmocr/olmocr/prompts/prompts.py:156-163`.

Transcribed verbatim including `LateX`, which is upstream's spelling and not a typo this file gets
to fix: the weights were fine-tuned against this string, so a corrected one is a different prompt
and a different output distribution. Any edit to it bumps `[driver] schema_version` on the card,
because 18:1876 calls that field *"THE ONLY DRIVER VERSION IN A CACHE KEY"* and a prompt is an
input."""

PROMPT_VERSION: Final[str] = "olmocr-no-anchoring-yaml/1"
"""INV-19's `prompt_version` for every `MeasuredOn` this driver contributes to (04 section 2.6).

Named after the upstream builder rather than after a date: the field answers which prompt a number
was measured under, and a date answers when. A second prompt is a `/2`."""

FRONT_MATTER_KEYS: Final[tuple[str, ...]] = (
    "primary_language",
    "is_rotation_valid",
    "rotation_correction",
    "is_table",
    "is_diagram",
)
"""The five the prompt names, in the prompt's own order. `PageResponse`
(`olmocr/prompts/prompts.py:67-73`) carries these plus `natural_text`, which is the body rather
than a front-matter key."""

ROTATIONS: Final[tuple[int, ...]] = (0, 90, 180, 270)
"""`PageResponse.__post_init__` refuses anything else (`prompts.py:77`), and so does this."""

_FENCE: Final[str] = "---"


@dataclass(frozen=True, slots=True)
class PageReading:
    """One page as the model returned it: five declared facts and the markdown body.

    `primary_language` is `""` rather than `None` where the model returned null, which its own
    schema documents at `prompts.py:105` as *"null if there is no text at all that you think you
    should read"*. The empty string carries the same statement and keeps the record's five
    fields five strings, ints and bools -- a `Scalar` vocabulary, which is what a driver may put on
    a wire.

    `is_rotation_valid = False` with a non-zero `rotation_correction` is the model reporting that
    it read a sideways page: the correction is what the RENDERER should have applied, and this
    driver records it rather than acting on it, because re-rendering is the render step's and a
    driver that re-rendered would spend a `page_render` the counter never authorised (INV-13).
    """

    text: str
    primary_language: str = ""
    is_rotation_valid: bool = True
    rotation_correction: int = 0
    is_table: bool = False
    is_diagram: bool = False
    had_front_matter: bool = False

    def __post_init__(self) -> None:
        if self.rotation_correction not in ROTATIONS:
            raise ValueError(
                f"rotation_correction is one of {ROTATIONS}; got {self.rotation_correction}"
            )

    @property
    def rotated(self) -> bool:
        """True when the model says the page was not upright. `verify.*`'s input, not a retry."""
        return not self.is_rotation_valid or self.rotation_correction != 0


def parse_reading(body: str) -> PageReading:
    """The model's markdown, split into its front matter and its text. Never raises on shape.

    A missing or malformed front matter block yields `had_front_matter = False` and the whole
    response as `text`, which is the same disposition olmocr's own parser takes
    (`front_matter.py:53` returns `{}, markdown_content.strip()`). That leniency is right here for
    a reason the upstream file does not state: the front matter is DIAGNOSTIC -- it feeds the
    `verify.*` signals -- while the text is the product, and a page whose text arrived should not
    be thrown away because its header did not.

    An out-of-vocabulary `rotation_correction` IS refused, because it is the one field a caller
    might act on and `PageResponse` refuses it too.
    """
    if not body.startswith(_FENCE + "\n"):
        return PageReading(text=body.strip())
    end = body.find("\n" + _FENCE, len(_FENCE) + 1)
    if end == -1:
        return PageReading(text=body.strip())
    fields = _fields(body[len(_FENCE) + 1 : end])
    text = body[end + len(_FENCE) + 1 :].strip()
    return PageReading(
        text=text,
        primary_language=fields.get("primary_language", ""),
        is_rotation_valid=_bool(fields.get("is_rotation_valid"), default=True),
        rotation_correction=_rotation(fields.get("rotation_correction")),
        is_table=_bool(fields.get("is_table"), default=False),
        is_diagram=_bool(fields.get("is_diagram"), default=False),
        had_front_matter=True,
    )


def _fields(block: str) -> dict[str, str]:
    """`key: value` per line, last wins, unknown keys ignored. Five partitions, no grammar."""
    found: dict[str, str] = {}
    for line in block.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() in FRONT_MATTER_KEYS:
            found[key.strip()] = value.strip().strip("\"'")
    return found


def _bool(raw: str | None, *, default: bool) -> bool:
    """`True`/`true`/`yes`/`1` and their negations; anything else is the default.

    The default and not a raise, for `parse_reading()`'s reason: these three fields are
    diagnostic. A model that wrote `is_table: maybe` has told us nothing, and nothing is what the
    default records.
    """
    if raw is None:
        return default
    lowered = raw.strip().lower()
    if lowered in ("true", "yes", "1"):
        return True
    if lowered in ("false", "no", "0"):
        return False
    return default


def _rotation(raw: str | None) -> int:
    if raw is None or not raw.strip():
        return 0
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise ValueError(f"rotation_correction {raw!r} is not an integer") from exc
    if value not in ROTATIONS:
        raise ValueError(f"rotation_correction is one of {ROTATIONS}; got {value}")
    return value
