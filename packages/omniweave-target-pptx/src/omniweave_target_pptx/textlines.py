"""owsvg/1's text model: a `<text>`'s style, its positioned lines and their runs. **D797.**

09-generation.md section 4.4 has one estimator "imported by **both** `rules/` and `lower/`", so
the checker and the compiler cannot disagree about a text's lines (OUT2). `measure.py` shapes a
line over uharfbuzz, which only a measuring host need hold, so the model it shapes moved here,
free of uharfbuzz, for `lower.text` to read as well. D792's rulings 3 and 4 are this module's:

- **Text properties inherit**, as SVG's do. `font-family`, `font-size` (16 by default),
  `font-weight`, `font-style`, `letter-spacing` and `xml:space` are read from the node, then each
  ancestor, attribute or `style`, the nearest first. A size or spacing is in user units, `px` or
  not.
- **A `<text>` is its positioned lines.** A `<tspan>` with `x` or `dy` starts a line, as the
  carrier's `visible_text` reads it (09 section 3.1). Whitespace collapses unless
  `xml:space="preserve"`. A line keeps the node that starts it, the text or its `<tspan>`, and
  each run keeps the node whose text it is.
- **Whitespace is the carrier's** (D803), `omniweave_core.out.carrier.tree.collapse`, applied
  character by character so each keeps its run. A space, a tab, a newline, a carriage return or
  a form feed is whitespace; each run of them is one space, and a line's ends are trimmed.
  `xml:space="preserve"` keeps every character as written, as `Lines.render` does. D792 dropped a
  newline, as SVG 1.1 does, so `Revenue` and `rose` on two source lines measured and lowered as
  `Revenuerose`, while the carrier's `visible_text`, which R2 compares, reads `Revenue rose`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from omniweave_core.out.carrier import style_declarations

if TYPE_CHECKING:
    from omniweave_core.out.carrier import CarrierNode

__all__ = [
    "BOLD",
    "DEFAULT_SIZE",
    "REGULAR",
    "STARTS_LINE",
    "TEXT",
    "TSPAN",
    "WHITESPACE",
    "Line",
    "TextStyle",
    "collapsed",
    "declared",
    "inherited",
    "length",
    "lines",
    "preserved",
    "style",
]

DEFAULT_SIZE: Final = 16.0
"""CSS's initial `font-size`, in px."""
REGULAR: Final = 400
BOLD: Final = 700
TEXT: Final = "svg|text"
TSPAN: Final = "svg|tspan"
STARTS_LINE: Final = ("x", "dy")
WHITESPACE: Final = frozenset(" \t\n\r\f")
"""The carrier's whitespace, `tree._SPACE`'s five characters."""

Run = tuple[str, "CarrierNode"]


@dataclass(frozen=True, slots=True)
class TextStyle:
    families: tuple[str, ...]
    size: float
    weight: int
    italic: bool
    spacing: float


@dataclass(frozen=True, slots=True)
class Line:
    """One positioned line: the node that starts it, and its runs in order."""

    node: CarrierNode
    runs: list[Run]


def declared(n: CarrierNode, prop: str) -> str | None:
    """`prop` on `n` itself: its `style` declaration, else its attribute."""
    for name, value in style_declarations(n.attr("style") or ""):
        if name == prop:
            return value
    return n.attr(prop)


def inherited(n: CarrierNode, prop: str) -> str | None:
    """`prop` on `n` or its nearest ancestor that states it."""
    node: CarrierNode | None = n
    while node is not None:
        value = declared(node, prop)
        if value is not None:
            return value
        node = getattr(node, "parent", None)
    return None


def style(n: CarrierNode) -> TextStyle:
    families = tuple(f for f in ((inherited(n, "font-family") or "").split(",")) if f.strip())
    weight_text = (inherited(n, "font-weight") or "normal").strip()
    weight = {"normal": REGULAR, "bold": BOLD}.get(weight_text)
    return TextStyle(
        families=families,
        size=length(inherited(n, "font-size"), DEFAULT_SIZE),
        weight=weight
        if weight is not None
        else int(weight_text)
        if weight_text.isdigit()
        else REGULAR,
        italic=(inherited(n, "font-style") or "normal").strip() == "italic",
        spacing=length(inherited(n, "letter-spacing"), 0.0),
    )


def length(text: str | None, default: float) -> float:
    if text is None:
        return default
    stripped = text.strip().removesuffix("px")
    try:
        return float(stripped)
    except ValueError:
        return default


def preserved(n: CarrierNode) -> bool:
    return (inherited(n, "xml:space") or "default").strip() == "preserve"


def lines(n: CarrierNode, *, preserve: bool) -> list[Line]:
    """The positioned lines, each with the node that starts it and its `(text, owner)` runs."""
    raw: list[tuple[CarrierNode, list[Run]]] = [(n, [])]

    def gather(node: CarrierNode, *, first: bool) -> None:
        if not first and any(node.attr(a) is not None for a in STARTS_LINE):
            raw.append((node, []))
        for item in node.contents():
            if isinstance(item, str):
                raw[-1][1].append((item, node))
            elif item.tag == TSPAN:
                gather(item, first=False)

    gather(n, first=True)
    return [Line(start, collapsed(runs, preserve=preserve)) for start, runs in raw]


def collapsed(runs: Sequence[Run], *, preserve: bool) -> list[Run]:
    """The carrier's whitespace (module docstring): each run of whitespace one space and the
    line's ends trimmed, or every character kept under `preserve`, each character kept with the
    run it came from."""
    chars: list[Run] = []
    for text, owner in runs:
        for ch in text:
            if preserve or ch not in WHITESPACE:
                chars.append((ch, owner))
            elif chars and chars[-1][0] != " ":
                chars.append((" ", owner))
    if not preserve:
        while chars and chars[-1][0] == " ":
            chars.pop()
    out: list[Run] = []
    for ch, owner in chars:
        if out and out[-1][1] is owner:
            out[-1] = (out[-1][0] + ch, owner)
        else:
            out.append((ch, owner))
    return out
