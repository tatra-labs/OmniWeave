"""`measure.py`: owsvg/1's one `TextMeasure`, uharfbuzz shaping over declared fonts. **D792.**

09-generation.md section 4.4: one estimator, "imported by **both** `rules/` and `lower/`", so the
checker and the compiler cannot disagree on how wide a line is (OUT2). A `Box` is in IL user
units, the `viewBox`'s, which for owsvg/1 are CSS px.

## Rulings

1. **The faces are the ones the card's config names, and no others.** `font_dir` names one
   absolute directory (D806), and every `.ttf`, `.otf`, `.ttc` and `.otc` under it, its
   subdirectories included, is read once, in sorted path order. No system font directory is
   read. A target is a purity island (G8), and a measurement that depended on whatever fonts a
   host happens to hold would differ across the nine platform cells its output is compared on
   (OUT13). ppt-master scans the host's font roots (`svg_to_pptx/text_outline.py:679-740`);
   owsvg/1 does not.
2. **A face is found by family, then weight and style.** A face's families are its name IDs 16
   then 1, compared without case and with whitespace collapsed. The first family in the stack
   that names a face wins. Among its faces, an italic request takes an italic face first, and
   then the nearest weight, ties going to the first face in path order. A generic family
   (`sans-serif`, `serif`, `monospace` and the rest) names no face here, because expanding it to
   a platform's faces is the host dependence ruling 1 refuses. A stack that names no face is
   unmeasurable.
3. **Text properties inherit**, as SVG's do. `font-family`, `font-size` (16 by default),
   `font-weight`, `font-style`, `letter-spacing` and `xml:space` are read from the node, then
   each ancestor, attribute or `style`, the nearest first. A size or spacing is read in user
   units, `px` or not.
4. **A `<text>` is its positioned lines.** A `<tspan>` with `x` or `dy` starts a line, as the
   carrier's `visible_text` reads it (09 section 3.1). Whitespace collapses, unless
   `xml:space="preserve"`. Each run is shaped in its own face, and `letter-spacing` is added
   after each character.
5. **The `Box`**: `advance` is the widest line. `ascent` is the first line's tallest ascender and
   `descent` the last line's deepest descender. `height` is `ascent + descent + (lines - 1) x
   leading`, where leading is the node's own face's ascender, descender and line gap at its size.
   `overflow` is `False`, because a `<text>` declares no box to overflow. A `<tspan>` is measured
   as its own content.
6. **`None` is "this node is unmeasurable"** (09 section 4.4): not text, or a run whose stack
   names no face.
7. **uharfbuzz is imported here and nowhere else in the target** (09 section 4.4's one-module
   rule). The driver imports this module when `measure()` is first called, so a missing
   uharfbuzz is a recorded skip and not an import error.

D797: rulings 3 and 4's model (a text's style, its positioned lines and their runs) moved to
`omniweave_target_pptx.textlines`, free of uharfbuzz, so `lower.text` reads the same lines.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import uharfbuzz
from omniweave_core.out import Box

from omniweave_target_pptx.textlines import (
    DEFAULT_SIZE,
    REGULAR,
    TEXT,
    TSPAN,
    lines,
    preserved,
    style,
)

if TYPE_CHECKING:
    from omniweave_core.out.carrier import CarrierNode

__all__ = ["DEFAULT_SIZE", "Face", "FontBook", "HarfBuzzMeasure"]

hb: Final[Any] = uharfbuzz
"""uharfbuzz's compiled module ships no type information, so it is read as `Any`, once."""

_EXTENSIONS: Final = frozenset({".ttf", ".otf", ".ttc", ".otc"})
_FAMILY_IDS: Final = (16, 1)
_ITALIC_AT: Final = 0.5
"""harfbuzz's `ital` style value: 1 for an italic face, 0 for an upright one."""


@dataclass(frozen=True, slots=True)
class Face:
    """One face of one font file, with what matching and metrics need."""

    path: Path
    index: int
    families: tuple[str, ...]
    weight: int
    italic: bool
    upem: int
    ascender: int
    descender: int
    line_gap: int


class FontBook:
    """Ruling 1: the faces under the configured directories, read once, in path order."""

    def __init__(self, roots: Sequence[Path]) -> None:
        self._roots = tuple(roots)
        self._faces: tuple[Face, ...] | None = None
        self._fonts: dict[tuple[Path, int], Any] = {}

    def faces(self) -> tuple[Face, ...]:
        if self._faces is None:
            self._faces = tuple(_read(_files(self._roots)))
        return self._faces

    def find(self, families: Sequence[str], weight: int, *, italic: bool) -> Face | None:
        """Ruling 2: the first family that names a face, then the nearest style."""
        for family in families:
            key = _key(family)
            named = [f for f in self.faces() if key in (_key(n) for n in f.families)]
            if named:
                return min(
                    enumerate(named),
                    key=lambda pair: (
                        pair[1].italic != italic,
                        abs(pair[1].weight - weight),
                        pair[0],
                    ),
                )[1]
        return None

    def font(self, face: Face) -> Any:
        """The uharfbuzz font for `face`, built once."""
        key = (face.path, face.index)
        found = self._fonts.get(key)
        if found is None:
            found = hb.Font(hb.Face(face.path.read_bytes(), face.index))
            self._fonts[key] = found
        return found


@dataclass(frozen=True, slots=True)
class _Line:
    advance: float
    ascent: float
    descent: float


class HarfBuzzMeasure:
    """The one `TextMeasure`: a `<text>` or `<tspan>` shaped over the `FontBook`'s faces."""

    def __init__(self, book: FontBook) -> None:
        self.book = book

    def box(self, n: CarrierNode) -> Box | None:
        """Rulings 4-6."""
        if n.tag not in (TEXT, TSPAN):
            return None
        own = style(n)
        face = self.book.find(own.families, own.weight, italic=own.italic)
        if face is None:
            return None
        shaped: list[_Line] = []
        for found in lines(n, preserve=preserved(n)):
            line = self._line(found.runs)
            if line is None:
                return None
            shaped.append(line)
        scale = own.size / face.upem
        leading = (face.ascender - face.descender + face.line_gap) * scale
        ascent, descent = shaped[0].ascent, shaped[-1].descent
        return Box(
            advance=max(line.advance for line in shaped),
            height=ascent + descent + (len(shaped) - 1) * leading,
            ascent=ascent,
            descent=descent,
            lines=len(shaped),
            overflow=False,
        )

    def _line(self, runs: Sequence[tuple[str, CarrierNode]]) -> _Line | None:
        advance = ascent = descent = 0.0
        for text, owner in runs:
            own = style(owner)
            face = self.book.find(own.families, own.weight, italic=own.italic)
            if face is None:
                return None
            scale = own.size / face.upem
            buf = hb.Buffer()
            buf.add_str(text)
            buf.guess_segment_properties()
            hb.shape(self.book.font(face), buf, {})
            advance += sum(p.x_advance for p in buf.glyph_positions) * scale
            advance += own.spacing * len(text)
            ascent = max(ascent, face.ascender * scale)
            descent = max(descent, -face.descender * scale)
        if not runs:
            return _Line(0.0, 0.0, 0.0)
        return _Line(advance, ascent, descent)


def _files(roots: Iterable[Path]) -> Iterator[Path]:
    seen: set[Path] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix.lower() in _EXTENSIONS and path not in seen:
                seen.add(path)
                yield path


def _read(paths: Iterable[Path]) -> Iterator[Face]:
    for path in paths:
        data = path.read_bytes()
        count = max(1, int(hb.Face(data, 0).count))
        for index in range(count):
            face = hb.Face(data, index)
            families = tuple(
                dict.fromkeys(
                    " ".join(str(name).split())
                    for name in (face.get_name(i) for i in _FAMILY_IDS)
                    if name
                )
            )
            if not families:
                continue
            font = hb.Font(face)
            extents = font.get_font_extents("ltr")
            weight = font.get_style_value(hb.StyleTag.WEIGHT)
            italic = font.get_style_value(hb.StyleTag.ITALIC)
            yield Face(
                path=path,
                index=index,
                families=families,
                weight=round(weight) if math.isfinite(weight) else REGULAR,
                italic=math.isfinite(italic) and italic >= _ITALIC_AT,
                upem=int(face.upem),
                ascender=int(extents.ascender),
                descender=int(extents.descender),
                line_gap=int(extents.line_gap),
            )


def _key(family: str) -> str:
    return " ".join(family.strip().strip("'\"").split()).casefold()
